"""插件市场：预设插件包目录（声明式，零代码执行）。

每个预设 = 安装时生成的一组规则 / 打开的功能开关。
- type="rules"  → 安装=创建带 _preset 标记的 AutomationRule；卸载=删除这些规则
- type="config" → 安装=打开对应功能模块开关；卸载=关闭（保留参数）
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AutomationRule, FeatureGroupConfig

PRESETS: list[dict] = [
    {
        "key": "keywords",
        "tab": "keywords",
        "name": "关键词回复",
        "icon": "💬",
        "category": "互动",
        "type": "feature",
        "description": "触发词自动回复。这里的启停是总开关，各群可在「关键词回复」页单独开关；规则本身支持指定作用群。",
        "needs": "无",
    },
    {
        "key": "stats",
        "tab": "stats",
        "name": "活跃统计",
        "icon": "📊",
        "category": "运营",
        "type": "feature",
        "description": "记录全群发言统计、生成排行榜。总开关在此，各群可在「统计」页单独开关。",
        "needs": "无",
    },
    {
        "key": "schedule",
        "tab": "schedule",
        "name": "定时推送",
        "icon": "⏰",
        "category": "运营",
        "type": "feature",
        "description": "定时任务总开关。任务本身按群指定目标，各群还可在「定时推送」页单独停用。",
        "needs": "需先在「定时推送」页建任务",
    },
    {
        "key": "automation_toolkit",
        "tab": "automation",
        "name": "自动化综合工具",
        "icon": "🛠️",
        "category": "群管",
        "type": "rules",
        "description": "群管自动化全家桶：关键词/链接引流拦截、防刷屏、新人进群通知、AI 智能审核、指定消息类型撤回，一次装齐六条标准规则。装完在「群管自动化」里逐条调整，不需要的可以单独删除。",
        "needs": "机器人需为群管理员（撤回/禁言）；AI 审核需先配 LLM Key",
        "rules": [
            {
                "name": "广告词拦截",
                "group_openid": "*",
                "trigger_type": "keyword",
                "trigger_params": {
                    "keywords": ["低价代练", "兼职刷单", "扫码进群", "免费领取", "加微信", "诚招推广"],
                    "match_mode": "contains",
                },
                "actions": [
                    {"type": "recall"},
                    {"type": "mute", "minutes": 10},
                    {"type": "notify"},
                    {"type": "log"},
                ],
            },
            {
                "name": "链接拦截",
                "group_openid": "*",
                "trigger_type": "link",
                "trigger_params": {"block_group_invite": True},
                "actions": [{"type": "recall"}, {"type": "notify"}, {"type": "log"}],
            },
            {
                "name": "刷屏拦截",
                "group_openid": "*",
                "trigger_type": "spam",
                "trigger_params": {"spam_window": 10, "spam_max": 5},
                "actions": [
                    {"type": "recall"},
                    {"type": "mute", "minutes": 5},
                    {"type": "log"},
                ],
            },
            {
                "name": "新人进群通知",
                "group_openid": "*",
                "trigger_type": "member_join",
                "trigger_params": {"delay_seconds": 2},
                "actions": [{"type": "notify"}, {"type": "log"}],
            },
            {
                "name": "图片消息撤回",
                "group_openid": "*",
                "trigger_type": "msg_type",
                "trigger_params": {"msg_types": ["图片"]},
                "actions": [
                    {"type": "recall"},
                    {"type": "log"},
                ],
            },
            {
                "name": "AI 审核可疑消息",
                "group_openid": "*",
                "trigger_type": "ai_audit",
                "trigger_params": {
                    "send_digit_len": 11,
                    "send_link": True,
                    "send_keywords": ["加", "私", "联系", "兼职", "副业", "免费"],
                    "max_per_day": 200,
                    "min_interval_sec": 3,
                },
                "actions": [
                    {"type": "notify"},
                    {"type": "log"},
                ],
                "priority": 200,
            },
        ],
    },
    {
        "key": "ai_chat",
        "tab": "ai",
        "name": "AI 对话助手",
        "icon": "🤖",
        "category": "互动",
        "type": "config",
        "config": "ai",
        "description": "@机器人 提问接大模型回答。安装后到「AI 对话」页签填自己的 API Key。",
        "needs": "需自备 LLM API Key",
    },
    {
        "key": "signin",
        "tab": "fun",
        "name": "每日签到",
        "icon": "📅",
        "category": "互动",
        "type": "config",
        "config": "signin",
        "description": "群友 /签到 打卡，统计连续天数。到「每日签到」页签可改回复模板。",
        "needs": "无",
    },
    {
        "key": "report",
        "tab": "report",
        "name": "举报通道",
        "icon": "📮",
        "category": "群管",
        "type": "config",
        "config": "report",
        "description": "群友发「举报 + 内容」自动转交管理群。到「入群审批」外请先在配置里填通知群。",
        "needs": "需配置管理群 openid",
    },
    {
        "key": "approval",
        "tab": "approval",
        "name": "入群审批",
        "icon": "🚪",
        "category": "群管",
        "type": "config",
        "config": "approval",
        "description": "加群申请转发管理群人工审批，支持答案关键词自动通过。机器人需为群管理员。",
        "needs": "机器人需为群管理员",
    },
]


def preset_by_key(key: str) -> dict | None:
    return next((p for p in PRESETS if p["key"] == key), None)


# 规则类插件 → 解锁的自动化规则触发类型（装了哪个插件，规则编辑里才出现哪些类型）
PRESET_RULE_TYPES: dict[str, list[str]] = {
    "automation_toolkit": ["keyword", "link", "spam", "member_join", "msg_type", "ai_audit"],
}

# 规则类插件的历史标记：老版本装过的规则包（已合并进「自动化综合工具」），识别时视同已装
RULE_PRESET_MARKERS: set[str] = {
    "automation_toolkit",
    "anti_ad_basic",
    "anti_spam",
    "newcomer_notify",
    "ai_audit_basic",
    "type_recall",
}


async def installed_keys(instance_id: int) -> set[str]:
    """计算每个预设是否已安装。"""
    result: set[str] = set()
    async with SessionLocal() as db:
        rules = (
            await db.execute(
                select(AutomationRule).where(
                    AutomationRule.bot_instance_id == instance_id
                )
            )
        ).scalars().all()
        for rule in rules:
            preset = (rule.trigger_params or {}).get("_preset")
            # 规则类插件统一挂「自动化综合工具」：老版本装的规则包（旧标记）也视同已装
            if preset and preset in RULE_PRESET_MARKERS:
                result.add("automation_toolkit")
                continue
            # 综合规则行：任一类型的配置带插件标记即算已装
            tc = rule.type_configs
            if isinstance(tc, dict):
                for c in tc.values():
                    if (c.get("params") or {}).get("_preset") in RULE_PRESET_MARKERS:
                        result.add("automation_toolkit")
                        break
        fg_rows = (
            await db.execute(
                select(FeatureGroupConfig).where(
                    FeatureGroupConfig.bot_instance_id == instance_id,
                    FeatureGroupConfig.group_openid == "*",
                )
            )
        ).scalars().all()
        feature_keys = {p["key"] for p in PRESETS if p.get("type") == "feature"}
        fg_map = {row.feature: row.enabled for row in fg_rows}
        for fk in feature_keys:
            # 无记录 = 默认开启；有记录看开关
            if fg_map.get(fk, True):
                result.add(fk)
        # config 型：读各功能自身的总开关状态
        from app.models import (
            AiConfig,
            ApprovalConfig,
            ReportConfig,
            SigninConfig,
            WelcomeConfig,
        )

        cfg_models = {
            "ai": AiConfig,
            "signin": SigninConfig,
            "report": ReportConfig,
            "approval": ApprovalConfig,
        }
        for p in PRESETS:
            if p.get("type") != "config":
                continue
            model = cfg_models[p["config"]]
            row = (
                await db.execute(
                    select(model).where(model.bot_instance_id == instance_id)
                )
            ).scalar_one_or_none()
            if row and row.enabled:
                result.add(p["key"])
    return result


async def install_preset(instance_id: int, preset: dict, default_notify_group: str = "") -> None:
    if preset["type"] == "rules":
        # 规则类插件统一生成一条综合规则：type_configs 按类型独立存储
        configs: dict = {}
        first = None
        for template in preset.get("rules", []):
            params = dict(template.get("trigger_params") or {})
            params["_preset"] = preset["key"]
            actions = []
            for action in template.get("actions", []):
                actions.append(dict(action))
            ttype = template["trigger_type"]
            configs[ttype] = {"enabled": True, "params": params, "actions": actions}
            if first is None:
                first = template
        if not first:
            return
        async with SessionLocal() as db:
            db.add(
                AutomationRule(
                    bot_instance_id=instance_id,
                    name=preset["name"],
                    group_openid=first.get("group_openid", "*"),
                    enabled=True,
                    priority=first.get("priority", 50),
                    trigger_type=first["trigger_type"],
                    trigger_params=configs[first["trigger_type"]]["params"],
                    actions=configs[first["trigger_type"]]["actions"],
                    type_configs=configs,
                )
            )
            await db.commit()
    elif preset["type"] == "feature":
        from app.models import FeatureGroupConfig

        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(FeatureGroupConfig).where(
                        FeatureGroupConfig.bot_instance_id == instance_id,
                        FeatureGroupConfig.feature == preset["key"],
                        FeatureGroupConfig.group_openid == "*",
                    )
                )
            ).scalar_one_or_none()
            if not row:
                row = FeatureGroupConfig(
                    bot_instance_id=instance_id,
                    feature=preset["key"],
                    group_openid="*",
                )
                db.add(row)
            row.enabled = True
            await db.commit()
    elif preset["type"] == "config":
        from app.models import (
            AiConfig,
            ApprovalConfig,
            ReportConfig,
            SigninConfig,
            WelcomeConfig,
        )

        model = {
            "ai": AiConfig,
            "signin": SigninConfig,
            "report": ReportConfig,
            "approval": ApprovalConfig,
        }[preset["config"]]
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(model).where(model.bot_instance_id == instance_id)
                )
            ).scalar_one_or_none()
            if not row:
                row = model(bot_instance_id=instance_id)
                db.add(row)
            row.enabled = True
            await db.commit()


async def uninstall_preset(instance_id: int, preset: dict) -> None:
    if preset["type"] == "feature":
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(FeatureGroupConfig).where(
                        FeatureGroupConfig.bot_instance_id == instance_id,
                        FeatureGroupConfig.feature == preset["key"],
                        FeatureGroupConfig.group_openid == "*",
                    )
                )
            ).scalar_one_or_none()
            if not row:
                # 从未动过开关时没有任何记录（默认=开启），必须补一条全局关闭行，
                # 否则停用是空操作：运行时按"无记录=开启"继续跑，卡片状态也不变。
                row = FeatureGroupConfig(
                    bot_instance_id=instance_id,
                    feature=preset["key"],
                    group_openid="*",
                )
                db.add(row)
            row.enabled = False
            await db.commit()
    elif preset["type"] == "rules":
        async with SessionLocal() as db:
            rules = (
                await db.execute(
                    select(AutomationRule).where(
                        AutomationRule.bot_instance_id == instance_id
                    )
                )
            ).scalars().all()
            for rule in rules:
                tc = rule.type_configs
                if isinstance(tc, dict) and tc:
                    # 综合规则行：任一类型带标记（含旧标记）就整行删除
                    if any(
                        (c.get("params") or {}).get("_preset") in RULE_PRESET_MARKERS
                        for c in tc.values()
                    ):
                        await db.delete(rule)
                    continue
                # 连老版本规则包的旧标记一起清掉，避免卸载后残留
                if (rule.trigger_params or {}).get("_preset") in RULE_PRESET_MARKERS:
                    await db.delete(rule)
            await db.commit()
    elif preset["type"] == "config":
        from app.models import (
            AiConfig,
            ApprovalConfig,
            ReportConfig,
            SigninConfig,
            WelcomeConfig,
        )

        model = {
            "ai": AiConfig,
            "signin": SigninConfig,
            "report": ReportConfig,
            "approval": ApprovalConfig,
        }[preset["config"]]
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(model).where(model.bot_instance_id == instance_id)
                )
            ).scalar_one_or_none()
            if row:
                row.enabled = False
                await db.commit()
