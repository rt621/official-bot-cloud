"""实例运行器：一个机器人实例 = 网关连接 + 事件分发 + 定时任务调度。"""

import asyncio
import contextlib
import datetime as dt
import logging

from croniter import croniter
from sqlalchemy import update

from app.database import SessionLocal
from app.models import ScheduleTask
from app.qq.gateway import GatewayConnection
from app.runtime.context import InstanceContext
from app.runtime.plugins.loader import plugin_loader
from app.runtime.plugins.base import Dispatcher

log = logging.getLogger("runtime.runner")


def build_dispatcher() -> Dispatcher:
    """从热加载器取插件构建分发器（插件目录变化自动生效）。"""
    return Dispatcher(plugin_loader.get_plugins())


class InstanceRunner:
    """管理一个实例的运行。stop() 后不可复用，重新创建。"""

    def __init__(self, instance_id: int, appid: str, client_secret: str):
        self.instance_id = instance_id
        self.appid = appid
        self.ctx = InstanceContext(instance_id, appid, client_secret)
        self.gateway: GatewayConnection | None = None
        self._task: asyncio.Task | None = None
        self._schedule_task: asyncio.Task | None = None
        self._reload_event = asyncio.Event()
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped = asyncio.Event()
        await self.ctx.load_config()
        self.gateway = GatewayConnection(
            self.ctx.api,
            on_event=self._on_event,
            on_status=self._on_status,
        )
        self._task = asyncio.create_task(self.gateway.run(), name=f"gw-{self.appid}")
        self._schedule_task = asyncio.create_task(
            self._schedule_loop(), name=f"cron-{self.appid}"
        )
        log.info("instance %s started", self.appid)

    async def stop(self) -> None:
        self._stopped.set()
        self._reload_event.set()
        if self.gateway:
            self.gateway.stop()
        for task in (self._task, self._schedule_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self.ctx.set_status("offline", "已停止")
        await self.ctx.api.close()
        log.info("instance %s stopped", self.appid)

    def reload_config(self) -> None:
        self._reload_event.set()

    async def _on_status(self, status: str, detail: str) -> None:
        await self.ctx.set_status(status, detail)

    async def _on_event(self, event_type: str, data: dict) -> None:
        if event_type == "READY":
            user = data.get("user") or {}
            self.ctx.bot_name = user.get("username", "")
            self.ctx.bot_openid = user.get("id", "")
        # 联调诊断日志：只进服务端日志文件（data/uvicorn.log），不落库不进页面
        if event_type in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"):
            log.info(
                "event=%s group=%s author=%s message_type=%s attachments=%s content=%r",
                event_type,
                data.get("group_openid", "-")[:12],
                str((data.get("author") or {}).get("id", "-"))[:12],
                data.get("message_type", "-"),
                len(data.get("attachments") or []),
                (data.get("content") or "")[:80],
            )
        event_key = str(data.get("id") or "")
        if event_key and self.ctx.seen(event_type + ":" + event_key):
            return
        await build_dispatcher().dispatch(event_type, self.ctx, data)

    async def _schedule_loop(self) -> None:
        """每 30 秒或配置变更后重新加载配置并检查定时任务。"""
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._reload_event.wait(), timeout=30)
                self._reload_event.clear()
            except asyncio.TimeoutError:
                pass
            await self.ctx.load_config()
            await self._run_due_tasks()

    async def _run_due_tasks(self) -> None:
        now = _now_local()
        for task_cfg in self.ctx.configs.get("schedules", []):
            if not task_cfg.enabled or not task_cfg.target_group_openid:
                continue
            if _should_fire(task_cfg, now):
                await self._fire_task(task_cfg)

    async def _fire_task(self, task_cfg: ScheduleTask) -> None:
        if not self.ctx.feature_enabled("schedule", task_cfg.target_group_openid):
            return
        try:
            if task_cfg.task_type == "image":
                media = await self.ctx.api.upload_group_media(
                    task_cfg.target_group_openid, 1, task_cfg.content
                )
                if media and media.get("file_info"):
                    await self.ctx.send_group(
                        task_cfg.target_group_openid, msg_type=7, media=media
                    )
            else:
                await self.ctx.send_group(task_cfg.target_group_openid, task_cfg.content)
        except Exception as exc:  # noqa: BLE001
            await self.ctx.log("error", f"定时任务「{task_cfg.name}」执行失败：{exc}")
            return
        async with SessionLocal() as db:
            await db.execute(
                update(ScheduleTask)
                .where(ScheduleTask.id == task_cfg.id)
                .values(last_run_at=dt.datetime.now(dt.timezone.utc))
            )
            await db.commit()
        await self.ctx.log("info", f"定时任务「{task_cfg.name}」已执行")


def _now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _should_fire(task_cfg: ScheduleTask, now: dt.datetime) -> bool:
    """分钟级精度：cron 上一个触发点晚于上次执行且距今 90 秒内。"""
    try:
        cron = croniter(task_cfg.cron, now - dt.timedelta(seconds=61))
        prev_fire = cron.get_prev(datetime)
    except Exception:  # noqa: BLE001
        return False
    last_run = task_cfg.last_run_at
    if last_run is None:
        return True
    last_run_local = last_run.astimezone(prev_fire.tzinfo) if last_run.tzinfo else last_run
    return prev_fire > last_run_local and (now - prev_fire).total_seconds() < 90
