"""平台级系统设置：存 DB 的 key-value，覆盖 .env 默认值。

键：registration_mode(closed/open/invite)、max_instances_per_user(int)、
announcement(文本)、maintenance_mode("1"/"0")。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemSetting

REGISTRATION_MODES = ("closed", "open", "invite")


async def get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    row = await db.get(SystemSetting, key)
    return row.value if row else default


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))
    await db.commit()


async def registration_mode(db: AsyncSession) -> str:
    """当前注册模式；未设置时按 .env 的 open_registration 兜底。"""
    from app.config import settings

    mode = await get_setting(db, "registration_mode")
    if mode in REGISTRATION_MODES:
        return mode
    return "open" if settings.open_registration else "closed"


async def max_instances_per_user(db: AsyncSession) -> int:
    from app.config import settings

    raw = await get_setting(db, "max_instances_per_user")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return settings.max_instances_per_user


async def maintenance_on(db: AsyncSession) -> bool:
    return (await get_setting(db, "maintenance_mode")) == "1"
