"""实例管理器（supervisor）：启动/停止/重载实例，进程级单例。"""

import asyncio
import datetime as dt
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models import BotInstance, User
from app.qq.client import ApiError
from app.runtime.runner import InstanceRunner
from app.security import decrypt_secret
from app.user_state import user_restricted

log = logging.getLogger("runtime.supervisor")


class Supervisor:
    def __init__(self) -> None:
        self.runners: dict[int, InstanceRunner] = {}
        self._lock = asyncio.Lock()

    async def bootstrap(self) -> None:
        """进程启动时拉起 enabled 实例，跳过受限用户和维护模式。"""
        from app.sysconf import maintenance_on

        async with SessionLocal() as db:
            users = (await db.execute(select(User))).scalars().all()
            skip_ids = {u.id for u in users if user_restricted(u)}
            maintenance = await maintenance_on(db)
            stmt = select(BotInstance).where(BotInstance.enabled.is_(True))
            if maintenance:
                log.info("维护模式开启中，本次启动不拉起任何实例")
                return
            instances = (await db.execute(stmt)).scalars().all()
        for inst in instances:
            if inst.user_id in skip_ids:
                log.info("跳过受限用户的实例 %s（%s）", inst.appid, inst.user_id)
                continue
            try:
                await self.start_instance(inst.id)
            except Exception as exc:  # noqa: BLE001
                log.error("bootstrap 启动实例 %s 失败: %s", inst.appid, exc)

    async def start_instance(self, instance_id: int) -> None:
        async with self._lock:
            if instance_id in self.runners:
                return
            inst, owner = await self._load_with_owner(instance_id)
            if not inst:
                raise ValueError("实例不存在")
            if not owner or user_restricted(owner):
                raise ValueError("账号已停用或到期，无法启动机器人")
            runner = InstanceRunner(inst.id, inst.appid, decrypt_secret(inst.secret_enc))
            self.runners[instance_id] = runner
            try:
                await runner.start()
            except Exception as exc:
                self.runners.pop(instance_id, None)
                await runner.ctx.set_status("error", f"启动失败：{exc_text(exc)}")
                raise

    async def stop_instance(self, instance_id: int, set_disabled: bool = False) -> None:
        async with self._lock:
            runner = self.runners.pop(instance_id, None)
            if runner:
                await runner.stop()
        if set_disabled:
            from sqlalchemy import update

            async with SessionLocal() as db:
                await db.execute(
                    update(BotInstance)
                    .where(BotInstance.id == instance_id)
                    .values(enabled=False)
                )
                await db.commit()

    async def restart_instance(self, instance_id: int) -> None:
        await self.stop_instance(instance_id)
        await self.start_instance(instance_id)

    async def reload_config(self, instance_id: int) -> None:
        """配置热加载：运行中的实例刷新内存配置。"""
        runner = self.runners.get(instance_id)
        if runner:
            runner.reload_config()

    async def _load_with_owner(self, instance_id: int) -> tuple[BotInstance | None, User | None]:
        async with SessionLocal() as db:
            inst = (
                await db.execute(select(BotInstance).where(BotInstance.id == instance_id))
            ).scalar_one_or_none()
            if not inst:
                return None, None
            owner = await db.get(User, inst.user_id)
            return inst, owner

    async def enforce_expirations(self) -> None:
        """停止到期/停用用户的 runner；用户恢复后只启动其 enabled 实例。"""
        from app.sysconf import maintenance_on

        async with SessionLocal() as db:
            users = (await db.execute(select(User))).scalars().all()
            restricted_ids = {u.id for u in users if user_restricted(u)}
            active = (await db.execute(select(BotInstance))).scalars().all()
            maintenance = await maintenance_on(db)
            eligible_ids = {
                inst.id for inst in active
                if inst.enabled and inst.user_id not in restricted_ids and not maintenance
            }

        for instance_id in list(self.runners):
            if instance_id not in eligible_ids:
                try:
                    await self.stop_instance(instance_id)
                except Exception:  # noqa: BLE001
                    log.exception("停止受限账号实例失败：%s", instance_id)
        for instance_id in eligible_ids:
            if instance_id not in self.runners:
                try:
                    await self.start_instance(instance_id)
                except Exception:  # noqa: BLE001
                    log.exception("恢复有效账号实例失败：%s", instance_id)

    async def shutdown(self) -> None:
        for instance_id in list(self.runners):
            await self.stop_instance(instance_id)


def exc_text(exc: BaseException) -> str:
    if isinstance(exc, ApiError):
        return f"{exc.kind}: {exc.message}"
    return str(exc)
