"""自动化规则引擎：触发条件评估 → 动作链执行。

规则来源 AutomationRule 表（ctx.configs["rules"]），支持分群（group_openid）
与实例总开关（GroupAdminConfig.master_enabled）。
触发类型：keyword / link / spam / member_join / ai_audit（AI 语义审核）。
"""

import asyncio
import logging
import re
import time
from types import SimpleNamespace

from app.database import SessionLocal
from app.models import ModerationHit
from app.runtime import ai as ai_svc
from app.runtime.context import InstanceContext
from app.qq.client import ApiError

log = logging.getLogger("runtime.rules")

URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
QQ_GROUP_INVITE_RE = re.compile(r"(群聊|加群|进群|群号)[^\d]{0,6}\d{5,}")
DIGITS_RE = re.compile(r"\d+")

# ai_audit 送审节流：rule_id -> 上次送审时间戳
_audit_last_ts: dict[int, float] = {}


def _whitelist(params: dict) -> list[str]:
    return [s.strip() for s in (params.get("whitelist_openids") or []) if s.strip()]


def ai_audit_filters_match(params: dict, content: str) -> bool:
    """送审条件（用户的'筛子'）：任一条件命中即送审；全部为空则不过滤（全送审，不推荐）。"""
    content = content or ""
    has_any = False
    keywords = params.get("send_keywords") or []
    if keywords:
        has_any = True
        if params.get("send_char_mode"):
            # 单字模式：输入的每个字符独立触发（抓 加V/薇心 之类的变体）
            chars = {ch for kw in keywords for ch in kw.strip() if ch.strip()}
            if any(ch in content for ch in chars):
                return True
        elif any(kw.strip() and kw.strip() in content for kw in keywords):
            return True
    patterns = params.get("send_regex") or []
    if patterns:
        has_any = True
        for pat in patterns:
            try:
                if re.search(pat, content):
                    return True
            except re.error:
                continue
    if params.get("send_link"):
        has_any = True
        if URL_RE.search(content) or QQ_GROUP_INVITE_RE.search(content):
            return True
    min_digits = int(params.get("send_digit_len") or 0)
    if min_digits >= 4:
        has_any = True
        if any(len(m.group(0)) >= min_digits for m in DIGITS_RE.finditer(content)):
            return True
    if params.get("send_long_text"):
        has_any = True
        if len(content) >= int(params.get("send_long_text") or 200):
            return True
    return not has_any


async def _ai_quota_ok(ctx: InstanceContext, rule_id: int, params: dict) -> tuple[bool, str]:
    """每日上限 + 最小间隔。返回 (是否送审, 拒绝原因)。"""
    max_per_day = int(params.get("max_per_day") or 200)
    if not await ctx._quota_ok(f"ai_audit_{rule_id}", "daily", max_per_day):
        return False, "daily_limit"
    interval = float(params.get("min_interval_sec") or 0)
    if interval > 0:
        last = _audit_last_ts.get(rule_id, 0)
        if time.time() - last < interval:
            return False, "interval"
    return True, ""


def _audit_system(params: dict, ctx: InstanceContext, group_openid: str = "") -> str:
    """审核员 system prompt = 审核职责 + 审核人设（按群覆盖）+ 规则自定义判定要求。"""
    from app.runtime.plugins.ai_chat import resolve_persona

    parts = ["你是这个群的 AI 管理助手，负责识别违规消息、维护群内秩序。"]
    ai_cfg = ctx.configs.get("ai")
    group_row = (ctx.configs.get("ai_group_personas") or {}).get(group_openid)
    persona = resolve_persona(ai_cfg, group_row, "audit")
    if persona:
        parts.append(persona)
    custom = str(params.get("ai_prompt") or "").strip()
    if custom:
        parts.append(custom)
    else:
        parts.append(ai_svc.DEFAULT_AUDIT_PROMPT)
    return "\n".join(parts)


async def ai_audit_execute(ctx: InstanceContext, rule, ev: dict) -> None:
    """异步执行 AI 审核：调用 LLM 判定，违规则走动作链。"""
    params = rule.trigger_params or {}
    from app.security import decrypt_secret

    ai_cfg = ctx.configs.get("ai")
    api_key = decrypt_secret(ai_cfg.api_key_enc) if ai_cfg and ai_cfg.api_key_enc else ""
    if not api_key:
        await ctx.log("error", f"规则「{rule.name}」需要 AI 审核，但未配置 LLM API Key（AI 对话页）")
        return
    api_base = params.get("ai_api_base") or ai_cfg.api_base
    model = params.get("ai_model") or ai_cfg.model

    verdict = await ai_svc.chat_json(
        api_base,
        api_key,
        model,
        _audit_system(params, ctx, ev["group_openid"]),
        (ev["content"] or "")[:1500],
    )
    _audit_last_ts[rule.id] = time.time()
    await ctx._quota_incr(f"ai_audit_{rule.id}", "daily")

    if verdict is None:
        await ctx.log("warn", f"规则「{rule.name}」AI 判定失败（无有效返回），本条跳过")
        return
    if not verdict.get("violation"):
        return  # 正常消息，静默放行

    reason = f"AI 判定{verdict.get('type') or ''}：{verdict.get('reason') or ''}".strip("：")
    await execute_actions(ctx, rule, ev, reason=reason)


# 接收侧消息类型检测（官方口径：message_type 0=文本 3=结构化卡片 103=引用；图片/视频/语音/文件在 attachments.content_type）
def _detect_msg_types(ev: dict) -> set[str]:
    raw = ev.get("raw") or {}
    atts = ev.get("attachments") or []
    mt = raw.get("message_type")
    types: set[str] = set()
    for a in atts:
        ct = str(a.get("content_type") or "").lower()
        blob = ct + " " + str(a.get("filename") or "") + " " + str(a.get("url") or "")
        if "image" in ct or any(x in blob for x in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
            types.add("图片")
        elif "video" in ct or ".mp4" in blob:
            types.add("视频")
        elif "audio" in ct or "voice" in ct or ".silk" in blob or ".amr" in blob:
            types.add("语音")
        elif "file" in ct or any(x in blob for x in (".pdf", ".doc", ".xls", ".ppt", ".zip", ".rar", ".txt")):
            types.add("文件")
    if mt == 3:
        types.add("结构化卡片")
    if mt == 103:
        types.add("引用消息")
    if not types and (ev.get("content") or "").strip():
        types.add("文本")
    return types


def rule_matches(rule, ev: dict, ctx: InstanceContext) -> bool:
    """评估非 AI 触发类型的条件。"""
    params = rule.trigger_params or {}
    if ev["user_openid"] in _whitelist(params):
        return False
    content = ev["content"] or ""
    ttype = rule.trigger_type
    if ttype == "member_join":
        # 只在进群事件上命中（综合规则行的虚拟规则也会出现在消息事件里）
        return bool(ev.get("member_join"))
    if ttype == "msg_type":
        selected = set(params.get("msg_types") or [])
        if not selected:
            return False
        return bool(selected & _detect_msg_types(ev))
    if ttype == "keyword":
        keywords = params.get("keywords") or []
        if not keywords:
            return False
        mode = params.get("match_mode", "contains")
        if mode == "regex":
            for kw in keywords:
                try:
                    if re.search(kw, content):
                        return True
                except re.error:
                    continue
            return False
        return any(kw.strip() and kw.strip() in content for kw in keywords)
    if ttype == "link":
        if params.get("block_group_invite", True) and QQ_GROUP_INVITE_RE.search(content):
            return True
        return bool(URL_RE.search(content))
    if ttype == "spam":
        window = int(params.get("spam_window") or 10)
        max_msgs = int(params.get("spam_max") or 5)
        return ctx.spam_check(ev["group_openid"], ev["user_openid"], window, max_msgs)
    return False


async def execute_actions(ctx: InstanceContext, rule, ev: dict, reason: str = "") -> None:
    """按动作列表顺序执行；单个动作失败不中断后续。"""
    group = ev["group_openid"]
    user = ev["user_openid"]
    results: dict = {}
    notify_target = ""
    reply_text = ""

    # 先把 notify/reply 的目标取出来（kick 之后用户已退群，回复无意义，故 reply 先发）
    for action in rule.actions or []:
        atype = action.get("type")
        if atype == "notify":
            notify_target = action.get("target", "")
        elif atype == "reply":
            reply_text = action.get("content", "")

    recall_result = ""
    for action in rule.actions or []:
        atype = action.get("type")
        try:
            if atype == "recall" and ev["event_id"] and not ev.get("member_join"):
                await ctx.api.recall_group(group, ev["event_id"])
                results["recall"] = True
            elif atype == "reply" and reply_text:
                text = (
                    reply_text.replace("{user}", user)
                    .replace("{rule}", rule.name)
                    .replace("{group}", group)
                )
                # 欢迎语：未写 {at} 时可自动在开头 @新人
                if action.get("at") and "{at}" not in text:
                    text = f'<qqbot-at-user id="{user}" /> ' + text
                text = text.replace("{at}", f'<qqbot-at-user id="{user}" />')
                # 进群事件没有可引用的消息，回复走主动消息；markdown=官方 msg_type 2
                await ctx.send_group(
                    group,
                    text,
                    msg_type=2 if action.get("markdown") else 0,
                    msg_id="" if ev.get("member_join") else ev["event_id"],
                )
                results["reply"] = True
            elif atype == "mute":
                minutes = int(action.get("minutes") or 10)
                await ctx.api.mute_member_for(group, user, minutes)
                results["mute_minutes"] = minutes
            elif atype == "kick":
                await ctx.api.remove_members(group, [user], bool(action.get("blacklist")))
                results["kick"] = True
            elif atype == "blacklist":
                await ctx.api.group_blacklist_op(group, action.get("op", "add"), [user])
                results[f"blacklist_{action.get('op', 'add')}"] = True
            elif atype == "log":
                results["logged"] = True
        except ApiError as exc:
            results[f"error_{atype}"] = f"{exc.kind}: {exc.message}"
        except Exception as exc:  # noqa: BLE001
            results[f"error_{atype}"] = str(exc)[:120]

    if notify_target:
        action_text = "、".join(
            filter(
                None,
                [
                    "已撤回" if results.get("recall") else "",
                    f"已禁言{results['mute_minutes']}分钟" if results.get("mute_minutes") else "",
                    "已踢出" if results.get("kick") else "",
                    "已拉黑" if results.get("blacklist_add") else "",
                    "已回复" if results.get("reply") else "",
                ],
            )
        )
        errors = "; ".join(v for k, v in results.items() if k.startswith("error_"))
        text = (
            f"⚠️ 规则触发告警\n规则：{rule.name}\n群：{group}\n用户：{user}\n"
            + (f"原因：{reason}\n" if reason else "")
            + f"内容：{(ev['content'] or '')[:200]}\n处置：{action_text or '仅记录'}"
            + (f"\n错误：{errors}" if errors else "")
        )
        # 通知到主人：target 是 user openid，私聊发送；失败记入结果（不中断）
        try:
            await ctx.send_c2c(notify_target, text)
            results["notify"] = True
        except ApiError as exc:
            results["error_notify"] = f"{exc.kind}: {exc.message}"
        except Exception as exc:  # noqa: BLE001
            results["error_notify"] = str(exc)[:120]

    async with SessionLocal() as db:
        db.add(
            ModerationHit(
                bot_instance_id=ctx.instance_id,
                rule_id=rule.id,
                rule_name=rule.name,
                group_openid=group,
                user_openid=user,
                user_name=user,
                reason=reason or f"规则「{rule.name}」({rule.trigger_type})",
                excerpt=(ev["content"] or "")[:200],
                actions=results,
            )
        )
        await db.commit()
    await ctx.log("warn", f"规则「{rule.name}」命中：用户 {user}，结果 {results}")


async def run_rules(ctx: InstanceContext, ev: dict) -> bool:
    """对一条群消息执行规则评估。返回是否有规则命中。"""
    admin_cfg = ctx.configs.get("groupadmin")
    if admin_cfg and not admin_cfg.master_enabled:
        return False
    rules = ctx.configs.get("rules") or []
    if not rules:
        return False
    group = ev["group_openid"]
    # 分群优先：先指定群规则，再 '*' 规则；同优先级按 id
    ordered = sorted(
        [r for r in rules if r.group_openid == group]
        + [r for r in rules if r.group_openid == "*"],
        key=lambda r: (r.priority, r.id),
    )
    # 综合规则（一行存多个触发类型的独立配置）展开成虚拟规则，逐条评估
    entries = []
    for rule in ordered:
        tc = getattr(rule, "type_configs", None)
        if isinstance(tc, dict) and tc:
            for t, c in tc.items():
                if not isinstance(c, dict):
                    continue
                entries.append(
                    SimpleNamespace(
                        id=rule.id,
                        name=rule.name,
                        group_openid=rule.group_openid,
                        enabled=bool(rule.enabled) and bool(c.get("enabled", True)),
                        priority=rule.priority,
                        trigger_type=t,
                        trigger_params=c.get("params") or {},
                        actions=c.get("actions") or [],
                    )
                )
        else:
            entries.append(rule)
    for rule in entries:
        if not rule.enabled:
            continue
        try:
            if rule.trigger_type == "ai_audit":
                # AI 审核：送审条件匹配 → 异步送审（不阻塞其他插件和规则）
                params = rule.trigger_params or {}
                if ev["user_openid"] in _whitelist(params):
                    continue
                if not ai_audit_filters_match(params, ev["content"]):
                    continue
                quota_ok, why = await _ai_quota_ok(ctx, rule.id, params)
                if not quota_ok:
                    if why == "daily_limit":
                        await ctx.log("warn", f"规则「{rule.name}」今日 AI 送审已达上限，剩余消息跳过")
                    continue
                asyncio.create_task(_safe_ai_audit(ctx, rule, ev))
                continue
            if rule_matches(rule, ev, ctx):
                delay = int((rule.trigger_params or {}).get("delay_seconds") or 0)
                if delay > 0:
                    asyncio.create_task(_delayed_execute(ctx, rule, dict(ev), delay))
                    return True
                await execute_actions(ctx, rule, ev)
                return True
        except Exception as exc:  # noqa: BLE001
            await ctx.log("error", f"规则「{rule.name}」评估异常：{exc}")
    return False


async def _delayed_execute(ctx: InstanceContext, rule, ev: dict, delay: int) -> None:
    """延迟执行动作（新人进群类规则常用：等几秒再欢迎/禁言，更自然也更稳）。"""
    try:
        await asyncio.sleep(delay)
        await execute_actions(ctx, rule, ev)
    except Exception as exc:  # noqa: BLE001
        await ctx.log("error", f"规则「{rule.name}」延迟执行异常：{exc}")


async def _safe_ai_audit(ctx: InstanceContext, rule, ev: dict) -> None:
    try:
        await ai_audit_execute(ctx, rule, ev)
    except Exception as exc:  # noqa: BLE001
        await ctx.log("error", f"规则「{rule.name}」AI 审核异常：{exc}")
