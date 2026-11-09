"""实例运行上下文：配置热加载、限频、发送封装、事件去重。"""

import asyncio
import datetime as dt
import logging
import time
from collections import deque
from typing import Any

from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import (
    AiConfig,
    AiGroupPersona,
    ApprovalConfig,
    AutomationRule,
    BotInstance,
    FeatureGroupConfig,
    GroupAdminConfig,
    ModerationConfig,
    ReportConfig,
    RuntimeLog,
    ScheduleTask,
    SigninConfig,
    UsageCounter,
)
from app.qq.client import ApiClient, ApiError
from app.security import decrypt_secret

log = logging.getLogger("runtime")


def today() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d")


class InstanceContext:
    """一个机器人实例运行期的全部状态。"""

    def __init__(self, instance_id: int, appid: str, client_secret: str):
        self.instance_id = instance_id
        self.appid = appid
        self.api = ApiClient(appid, client_secret)
        self.bot_name = ""  # 从 READY 事件取，用于 @前缀剥离
        self.bot_openid = ""  # 机器人在群/C2C 场景的 openid，对应消息里的 <@openid> 标记
        self.configs: dict[str, Any] = {}
        # 每群发送节流锁 + 上次发送时间
        self._group_locks: dict[str, asyncio.Lock] = {}
        self._last_send: dict[str, float] = {}
        self._seen_events: deque[str] = deque(maxlen=1024)
        self._spam_windows: dict[tuple[str, str], list[float]] = {}
        self.known_groups: set[str] = set()  # 本次运行中已见过的群（自动发现日志用）

    # ---------- 配置 ----------

    async def load_config(self) -> None:
        async with SessionLocal() as db:
            ai = (
                await db.execute(
                    select(AiConfig).where(AiConfig.bot_instance_id == self.instance_id)
                )
            ).scalar_one_or_none()
            ai_group_personas = (
                await db.execute(
                    select(AiGroupPersona).where(
                        AiGroupPersona.bot_instance_id == self.instance_id
                    )
                )
            ).scalars().all()
            feature_groups = (
                await db.execute(
                    select(FeatureGroupConfig).where(
                        FeatureGroupConfig.bot_instance_id == self.instance_id
                    )
                )
            ).scalars().all()
            instance = (
                await db.execute(select(BotInstance).where(BotInstance.id == self.instance_id))
            ).scalar_one_or_none()
            moderation = (
                await db.execute(
                    select(ModerationConfig).where(
                        ModerationConfig.bot_instance_id == self.instance_id
                    )
                )
            ).scalar_one_or_none()
            approval = (
                await db.execute(
                    select(ApprovalConfig).where(
                        ApprovalConfig.bot_instance_id == self.instance_id
                    )
                )
            ).scalar_one_or_none()
            report = (
                await db.execute(
                    select(ReportConfig).where(
                        ReportConfig.bot_instance_id == self.instance_id
                    )
                )
            ).scalar_one_or_none()
            signin = (
                await db.execute(
                    select(SigninConfig).where(
                        SigninConfig.bot_instance_id == self.instance_id
                    )
                )
            ).scalar_one_or_none()
            schedules = (
                await db.execute(
                    select(ScheduleTask).where(
                        ScheduleTask.bot_instance_id == self.instance_id
                    )
                )
            ).scalars().all()
            groupadmin = (
                await db.execute(
                    select(GroupAdminConfig).where(
                        GroupAdminConfig.bot_instance_id == self.instance_id
                    )
                )
            ).scalar_one_or_none()
            rules = (
                await db.execute(
                    select(AutomationRule).where(
                        AutomationRule.bot_instance_id == self.instance_id
                    )
                )
            ).scalars().all()

        self.configs = {
            "ai": ai,
            "moderation": moderation,
            "approval": approval,
            "report": report,
            "signin": signin,
            "schedules": list(schedules),
            "groupadmin": groupadmin,
            "rules": list(rules),
            "ai_group_personas": {p.group_openid: p for p in ai_group_personas},
            "feature_groups": {(f.feature, f.group_openid): f.enabled for f in feature_groups},
            "notify_groups": {
                "moderation": (moderation.notify_group_openid if moderation else ""),
                "approval": (approval.notify_group_openid if approval else ""),
                "report": (report.notify_group_openid if report else ""),
            },
            "instance_name": instance.name if instance else "",
        }

    # ---------- 功能开关 ----------

    def feature_enabled(self, feature: str, group_openid: str = "") -> bool:
        """功能 × 群 开关：指定群覆盖 > 全局('*')覆盖 > 默认开。"""
        fg = self.configs.get("feature_groups") or {}
        if group_openid:
            v = fg.get((feature, group_openid))
            if v is not None:
                return v
        v = fg.get((feature, "*"))
        if v is not None:
            return v
        return True

    # ---------- 事件去重 ----------

    def seen(self, event_key: str) -> bool:
        if event_key in self._seen_events:
            return True
        self._seen_events.append(event_key)
        return False

    # ---------- 状态 ----------

    async def set_status(self, status: str, detail: str = "") -> None:
        values: dict[str, Any] = {"status": status, "status_detail": detail[:500]}
        if status == "online":
            values["last_online_at"] = dt.datetime.now(dt.timezone.utc)
        async with SessionLocal() as db:
            await db.execute(
                update(BotInstance)
                .where(BotInstance.id == self.instance_id)
                .values(**values)
            )
            await db.commit()

    async def log(self, level: str, message: str) -> None:
        async with SessionLocal() as db:
            db.add(
                RuntimeLog(
                    bot_instance_id=self.instance_id, level=level, message=message[:1000]
                )
            )
            await db.commit()
        if level == "error":
            log.error("[%s] %s", self.appid, message)
        else:
            log.info("[%s] %s", self.appid, message)

    # ---------- 发送封装（限频 + 额度 + 错误归类） ----------

    async def send_group(
        self,
        group_openid: str,
        content: str = "",
        msg_type: int = 0,
        media: dict | None = None,
        keyboard: dict | None = None,
        msg_id: str = "",
    ) -> dict | None:
        """发群消息：被动回复直接发；主动消息走节流+每日额度。"""
        proactive = not msg_id
        lock = self._group_locks.setdefault(group_openid, asyncio.Lock())
        async with lock:
            if proactive:
                # 每群 1 条/秒 节流 + 每日 1000 条额度
                elapsed = time.time() - self._last_send.get(group_openid, 0)
                if elapsed < 1.1:
                    await asyncio.sleep(1.1 - elapsed)
                if not await self._quota_ok("group_daily", group_openid, 1000):
                    await self.log("warn", f"群 {group_openid} 今日主动消息已达 1000 条上限，跳过发送")
                    return None
            try:
                result = await self.api.send_group(
                    group_openid,
                    msg_type=msg_type,
                    content=content,
                    media=media,
                    keyboard=keyboard,
                    msg_id=msg_id,
                )
                self._last_send[group_openid] = time.time()
                if proactive:
                    await self._quota_incr("group_daily", group_openid)
                return result
            except ApiError as exc:
                await self.log("error", f"群消息发送失败({exc.kind}): {exc}")
                return None

    async def send_c2c(
        self,
        user_openid: str,
        content: str = "",
        msg_type: int = 0,
        media: dict | None = None,
        keyboard: dict | None = None,
        msg_id: str = "",
    ) -> dict | None:
        try:
            return await self.api.send_c2c(
                user_openid,
                msg_type=msg_type,
                content=content,
                media=media,
                keyboard=keyboard,
                msg_id=msg_id,
            )
        except ApiError as exc:
            await self.log("error", f"单聊消息发送失败({exc.kind}): {exc}")
            return None

    # ---------- 额度计数 ----------

    async def _quota_ok(self, scope: str, scope_key: str, limit: int) -> bool:
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(UsageCounter).where(
                        UsageCounter.bot_instance_id == self.instance_id,
                        UsageCounter.day == today(),
                        UsageCounter.scope == scope,
                        UsageCounter.scope_key == scope_key,
                    )
                )
            ).scalar_one_or_none()
            return (row.count if row else 0) < limit

    async def _quota_incr(self, scope: str, scope_key: str, amount: int = 1) -> None:
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(UsageCounter).where(
                        UsageCounter.bot_instance_id == self.instance_id,
                        UsageCounter.day == today(),
                        UsageCounter.scope == scope,
                        UsageCounter.scope_key == scope_key,
                    )
                )
            ).scalar_one_or_none()
            if row:
                row.count += amount
            else:
                db.add(
                    UsageCounter(
                        bot_instance_id=self.instance_id,
                        day=today(),
                        scope=scope,
                        scope_key=scope_key,
                        count=amount,
                    )
                )
            await db.commit()

    async def ai_quota_ok(self, user_openid: str, limit: int) -> bool:
        return await self._quota_ok("ai_user", user_openid, limit)

    async def ai_quota_incr(self, user_openid: str) -> None:
        await self._quota_incr("ai_user", user_openid)

    # ---------- 刷屏检测窗口 ----------

    def spam_check(self, group_openid: str, user_openid: str, window: int, max_msgs: int) -> bool:
        """返回 True 表示超频。"""
        key = (group_openid, user_openid)
        now = time.time()
        hits = [t for t in self._spam_windows.get(key, []) if now - t < window]
        hits.append(now)
        self._spam_windows[key] = hits
        return len(hits) > max_msgs


def decrypt_or_empty(enc: str) -> str:
    return decrypt_secret(enc) if enc else ""
