"""用户有效期与访问状态判断。"""

import datetime as dt


def as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def user_expired(user, now: dt.datetime | None = None) -> bool:
    """NULL=永久；兼容 SQLite 返回的无时区 datetime。"""
    expires_at = getattr(user, "expires_at", None)
    if expires_at is None:
        return False
    current = now or dt.datetime.now(dt.timezone.utc)
    return as_utc(expires_at) <= as_utc(current)


def user_restricted(user, now: dt.datetime | None = None) -> bool:
    return bool(getattr(user, "disabled", False) or user_expired(user, now))
