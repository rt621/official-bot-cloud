"""运营后台（大后台）：用户管理、全平台实例、统计、审计/运行日志、系统设置、邀请码、公告、维护模式。

所有 /api/admin/* 接口仅 is_admin 可访问（router 级依赖）；公告接口单独挂在 /api/announcement。
"""

import datetime as dt
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_required, audit, current_user, get_supervisor
from app.database import get_db
from app.models import (
    INSTANCE_CASCADE_MODELS,
    AuditLog,
    BotInstance,
    DailyStat,
    InviteCode,
    KnownGroup,
    LoginLog,
    PaymentOrder,
    PaymentPlan,
    RuntimeLog,
    User,
)
from app.security import decrypt_secret, encrypt_secret, hash_password, mask_secret
from app.user_state import as_utc, user_expired, user_restricted
from app.sysconf import (
    REGISTRATION_MODES,
    get_setting,
    max_instances_per_user,
    registration_mode,
    set_setting,
)

router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_required)])
public = APIRouter(prefix="/api", tags=["announcement"])

TZ_CN = dt.timezone(dt.timedelta(hours=8))


def _local_today_utc() -> dt.datetime:
    """本地（东八区）今天 0 点对应的 UTC 时刻，用于按"今天"过滤时间字段。"""
    now_cn = dt.datetime.now(TZ_CN)
    return now_cn.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)


def _today_str() -> str:
    return dt.date.today().isoformat()


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    return user


# ---------- A. 用户管理 ----------


@router.get("/users")
async def list_users(
    q: str = "", page: int = 1, page_size: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict:
    page, page_size = max(1, page), min(100, max(1, page_size))
    stmt = select(User)
    if q.strip():
        stmt = stmt.where(User.username.contains(q.strip()))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
    rows = (await db.execute(stmt.order_by(User.id).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    ids = [u.id for u in rows]
    inst_counts, last_logins = {}, {}
    if ids:
        counts = await db.execute(
            select(BotInstance.user_id, func.count()).where(BotInstance.user_id.in_(ids)).group_by(BotInstance.user_id)
        )
        inst_counts = dict(counts.all())
        logins = await db.execute(
            select(LoginLog.user_id, func.max(LoginLog.created_at)).where(LoginLog.user_id.in_(ids)).group_by(LoginLog.user_id)
        )
        last_logins = dict(logins.all())
    return {
        "total": total,
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "is_admin": u.is_admin,
                "disabled": u.disabled,
                "expires_at": u.expires_at,
                "expired": user_expired(u),
                "created_at": u.created_at,
                "instance_count": inst_counts.get(u.id, 0),
                "last_login_at": last_logins.get(u.id),
            }
            for u in rows
        ],
    }


class UserExpiryIn(BaseModel):
    expires_at: dt.datetime | None = None
    extend_days: int | None = Field(default=None, ge=1, le=3650)
    permanent: bool = False


@router.post("/users/{user_id}/expiry")
async def set_user_expiry(
    user_id: int,
    body: UserExpiryIn,
    request: Request,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id and not body.permanent and (body.expires_at is not None or body.extend_days is not None):
        raise HTTPException(400, "不能为当前管理员账号设置到期时间")

    now = dt.datetime.now(dt.timezone.utc)
    if body.permanent:
        user.expires_at = None
        detail = f"用户 {user.username} 设置为永久有效"
    elif body.extend_days is not None:
        base = as_utc(user.expires_at) if user.expires_at else None
        if base is None or base < now:
            base = now
        user.expires_at = base + dt.timedelta(days=body.extend_days)
        detail = f"用户 {user.username} 延长 {body.extend_days} 天"
    elif body.expires_at is not None:
        expiry = body.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=dt.timezone.utc)
        user.expires_at = expiry.astimezone(dt.timezone.utc)
        detail = f"设置用户 {user.username} 到期时间 {user.expires_at.isoformat()}"
    else:
        raise HTTPException(400, "请提供到期时间、延长天数，或选择永久有效")

    await audit(db, admin.id, None, "user.expiry", detail)
    await db.commit()

    supervisor = get_supervisor(request)
    rows = (
        await db.execute(select(BotInstance).where(BotInstance.user_id == user.id))
    ).scalars().all()
    if user_restricted(user):
        for inst in rows:
            try:
                await supervisor.stop_instance(inst.id)
            except Exception:  # noqa: BLE001
                pass
    elif not user.disabled:
        for inst in rows:
            if inst.enabled:
                try:
                    await supervisor.start_instance(inst.id)
                except Exception:  # noqa: BLE001
                    pass
    return {"ok": True, "expires_at": user.expires_at, "expired": user_expired(user)}


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: int, request: Request,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(400, "不能停用自己")
    user.disabled = True
    await audit(db, admin.id, None, "user.disable", f"停用用户 {user.username}")
    await db.commit()
    supervisor = get_supervisor(request)
    rows = (await db.execute(select(BotInstance).where(BotInstance.user_id == user.id))).scalars().all()
    for inst in rows:  # 只停 runner，不动 enabled 期望状态，启用后原样恢复
        try:
            await supervisor.stop_instance(inst.id)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: int, request: Request,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_user_or_404(db, user_id)
    if user_expired(user):
        raise HTTPException(400, "该账号已到期，请先在有效期设置中续期")
    user.disabled = False
    await audit(db, admin.id, None, "user.enable", f"启用用户 {user.username}")
    await db.commit()
    supervisor = get_supervisor(request)
    if not user_expired(user):
        rows = (
            await db.execute(
                select(BotInstance).where(BotInstance.user_id == user.id, BotInstance.enabled.is_(True))
            )
        ).scalars().all()
        if not user.disabled:
            for inst in rows:
                try:
                    await supervisor.start_instance(inst.id)
                except Exception:  # noqa: BLE001
                    pass
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_user_or_404(db, user_id)
    alphabet = string.ascii_letters + string.digits
    new_password = "".join(secrets.choice(alphabet) for _ in range(10))
    user.password_hash = hash_password(new_password)
    await audit(db, admin.id, None, "user.reset_password", f"重置用户 {user.username} 的密码")
    await db.commit()
    return {"ok": True, "new_password": new_password}


@router.post("/users/{user_id}/set-admin")
async def set_admin(
    user_id: int, body: dict,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(400, "不能修改自己的管理员身份")
    flag = bool(body.get("is_admin"))
    user.is_admin = flag
    await audit(db, admin.id, None, "user.set_admin", f"{user.username} 管理员={'开' if flag else '关'}")
    await db.commit()
    return {"ok": True, "is_admin": flag}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int, request: Request,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(400, "不能删除自己")
    instances = (await db.execute(select(BotInstance).where(BotInstance.user_id == user.id))).scalars().all()
    supervisor = get_supervisor(request)
    for inst in instances:
        try:
            await supervisor.stop_instance(inst.id)
        except Exception:  # noqa: BLE001
            pass
    inst_ids = [i.id for i in instances]
    if inst_ids:
        for model in INSTANCE_CASCADE_MODELS:
            await db.execute(delete(model).where(model.bot_instance_id.in_(inst_ids)))
        await db.execute(delete(BotInstance).where(BotInstance.user_id == user.id))
    await db.execute(delete(LoginLog).where(LoginLog.user_id == user.id))
    await db.delete(user)
    await audit(db, admin.id, None, "user.delete", f"删除用户 {user.username}（实例 {len(inst_ids)} 个）")
    await db.commit()
    return {"ok": True}


@router.get("/users/{user_id}/logins")
async def user_logins(
    user_id: int, page: int = 1, page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_user_or_404(db, user_id)
    page, page_size = max(1, page), min(100, max(1, page_size))
    base = select(LoginLog).where(LoginLog.user_id == user_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar()
    rows = (
        await db.execute(base.order_by(LoginLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return {
        "total": total,
        "items": [{"id": r.id, "ip": r.ip, "created_at": r.created_at} for r in rows],
    }


# ---------- B. 全平台实例 ----------


@router.get("/instances")
async def list_all_instances(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(BotInstance).order_by(BotInstance.id))).scalars().all()
    users = {u.id: u.username for u in (await db.execute(select(User))).scalars().all()}
    group_counts = dict(
        (
            await db.execute(
                select(KnownGroup.bot_instance_id, func.count()).group_by(KnownGroup.bot_instance_id)
            )
        ).all()
    )
    today_msgs = dict(
        (
            await db.execute(
                select(DailyStat.bot_instance_id, func.sum(DailyStat.msg_count))
                .where(DailyStat.day == _today_str())
                .group_by(DailyStat.bot_instance_id)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": i.id,
                "appid": i.appid,
                "name": i.name,
                "status": i.status,
                "status_detail": i.status_detail,
                "enabled": i.enabled,
                "user_id": i.user_id,
                "username": users.get(i.user_id, f"#{i.user_id}"),
                "groups_count": group_counts.get(i.id, 0),
                "today_msgs": int(today_msgs.get(i.id, 0)),
                "created_at": i.created_at,
            }
            for i in rows
        ]
    }


# ---------- C. 平台统计 ----------


@router.get("/stats/overview")
async def stats_overview(db: AsyncSession = Depends(get_db)) -> dict:
    today_start = _local_today_utc()
    users_total = (await db.execute(select(func.count()).select_from(User))).scalar()
    users_today = (
        await db.execute(select(func.count()).select_from(User).where(User.created_at >= today_start))
    ).scalar()
    users_disabled = (
        await db.execute(
            select(func.count()).select_from(User).where(
                User.disabled.is_(True)
                | (
                    User.expires_at.is_not(None)
                    & (User.expires_at <= dt.datetime.now(dt.timezone.utc))
                )
            )
        )
    ).scalar()
    users_expired = (
        await db.execute(
            select(func.count()).select_from(User).where(
                User.expires_at.is_not(None),
            User.expires_at <= dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
            )
        )
    ).scalar()
    instances_total = (await db.execute(select(func.count()).select_from(BotInstance))).scalar()
    instances_online = (
        await db.execute(select(func.count()).select_from(BotInstance).where(BotInstance.status == "online"))
    ).scalar()
    msgs_today = (
        await db.execute(
            select(func.coalesce(func.sum(DailyStat.msg_count), 0)).where(DailyStat.day == _today_str())
        )
    ).scalar()
    invites_unused = (
        await db.execute(select(func.count()).select_from(InviteCode).where(InviteCode.used_by.is_(None)))
    ).scalar()
    return {
        "users_total": users_total,
        "users_today": users_today,
        "users_disabled": users_disabled,
        "users_expired": users_expired,
        "instances_total": instances_total,
        "instances_online": instances_online,
        "msgs_today": int(msgs_today),
        "invites_unused": invites_unused,
    }


@router.get("/stats/ranking")
async def stats_ranking(days: int = 1, db: AsyncSession = Depends(get_db)) -> dict:
    days = 7 if days >= 7 else max(1, days)
    start = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    rows = (
        await db.execute(
            select(
                DailyStat.bot_instance_id,
                func.sum(DailyStat.msg_count).label("total"),
            )
            .where(DailyStat.day >= start)
            .group_by(DailyStat.bot_instance_id)
            .order_by(func.sum(DailyStat.msg_count).desc())
            .limit(10)
        )
    ).all()
    instances = {i.id: i for i in (await db.execute(select(BotInstance))).scalars().all()}
    users = {u.id: u.username for u in (await db.execute(select(User))).scalars().all()}
    items = []
    for inst_id, total in rows:
        inst = instances.get(inst_id)
        items.append(
            {
                "instance_id": inst_id,
                "name": inst.name if inst else f"#{inst_id}",
                "appid": inst.appid if inst else "",
                "username": users.get(inst.user_id, "") if inst else "",
                "msgs": int(total),
            }
        )
    return {"days": days, "items": items}


# ---------- D. 审计 / 运行日志 ----------


@router.get("/audit-logs")
async def audit_logs(
    user_id: int | None = None, action: str = "", q: str = "",
    page: int = 1, page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict:
    page, page_size = max(1, page), min(100, max(1, page_size))
    stmt = select(AuditLog)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action.strip():
        stmt = stmt.where(AuditLog.action.contains(action.strip()))
    if q.strip():
        stmt = stmt.where(AuditLog.detail.contains(q.strip()))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
    rows = (
        await db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    users = {u.id: u.username for u in (await db.execute(select(User))).scalars().all()}
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": users.get(r.user_id) if r.user_id else "",
                "bot_instance_id": r.bot_instance_id,
                "action": r.action,
                "detail": r.detail,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


@router.get("/runtime-logs")
async def runtime_logs(
    instance_id: int | None = None, level: str = "", q: str = "",
    page: int = 1, page_size: int = 30,
    db: AsyncSession = Depends(get_db),
) -> dict:
    page, page_size = max(1, page), min(100, max(1, page_size))
    stmt = select(RuntimeLog)
    if instance_id:
        stmt = stmt.where(RuntimeLog.bot_instance_id == instance_id)
    if level.strip():
        stmt = stmt.where(RuntimeLog.level == level.strip())
    if q.strip():
        stmt = stmt.where(RuntimeLog.message.contains(q.strip()))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
    rows = (
        await db.execute(stmt.order_by(RuntimeLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    instances = {i.id: i for i in (await db.execute(select(BotInstance))).scalars().all()}
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "instance_id": r.bot_instance_id,
                "instance_name": instances[r.bot_instance_id].name if r.bot_instance_id in instances else "",
                "level": r.level,
                "message": r.message,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


# ---------- 系统设置（注册模式 / 实例上限 / 公告 / 维护模式） ----------


class SettingsIn(BaseModel):
    registration_mode: str | None = None
    max_instances_per_user: int | None = Field(default=None, ge=1, le=1000)
    announcement: str | None = Field(default=None, max_length=2000)


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db)) -> dict:
    raw_max = await get_setting(db, "max_instances_per_user")
    return {
        "registration_mode": await registration_mode(db),
        "max_instances_per_user": int(raw_max) if raw_max.isdigit() else None,
        "announcement": await get_setting(db, "announcement"),
        "maintenance_mode": (await get_setting(db, "maintenance_mode")) == "1",
    }


@router.put("/settings")
async def put_settings(
    body: SettingsIn,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.registration_mode is not None:
        if body.registration_mode not in REGISTRATION_MODES:
            raise HTTPException(400, "注册模式只能是 closed / open / invite")
        await set_setting(db, "registration_mode", body.registration_mode)
    if body.max_instances_per_user is not None:
        await set_setting(db, "max_instances_per_user", str(body.max_instances_per_user))
    if body.announcement is not None:
        await set_setting(db, "announcement", body.announcement.strip())
    await audit(db, admin.id, None, "settings.update", f"系统设置更新 {body.model_dump(exclude_none=True)}")
    await db.commit()
    return await get_settings(db=db)


# ---------- 注册安全 / 支付配置 ----------


class AdminServiceSettingsIn(BaseModel):
    mail_host: str | None = Field(default=None, max_length=255)
    mail_port: int | None = Field(default=None, ge=1, le=65535)
    mail_user: str | None = Field(default=None, max_length=255)
    mail_password: str | None = Field(default=None, max_length=2048)
    mail_sender: str | None = Field(default=None, max_length=255)
    mail_starttls: bool | None = None
    turnstile_enabled: bool | None = None
    turnstile_site_key: str | None = Field(default=None, max_length=512)
    turnstile_secret: str | None = Field(default=None, max_length=2048)
    epay_enabled: bool | None = None
    epay_gateway: str | None = Field(default=None, max_length=512)
    epay_pid: str | None = Field(default=None, max_length=255)
    epay_secret: str | None = Field(default=None, max_length=2048)
    epay_notify_url: str | None = Field(default=None, max_length=1024)
    epay_return_url: str | None = Field(default=None, max_length=1024)


_SECRET_SETTING_FIELDS = {
    "mail_password": "mail_password_enc",
    "turnstile_secret": "turnstile_secret_enc",
    "epay_secret": "epay_secret_enc",
}


async def _admin_service_settings(db: AsyncSession) -> dict:
    from app.registration_security import get_registration_security

    config = await get_registration_security(db)
    result = {
        "mail_host": config["mail_host"],
        "mail_port": config["mail_port"],
        "mail_user": config["mail_user"],
        "mail_sender": config["mail_sender"],
        "mail_starttls": config["mail_starttls"],
        "turnstile_enabled": config["turnstile_enabled"],
        "turnstile_site_key": config["turnstile_site_key"],
        "epay_enabled": config["epay_enabled"],
        "epay_gateway": config["epay_gateway"],
        "epay_pid": config["epay_pid"],
        "epay_notify_url": config["epay_notify_url"],
        "epay_return_url": config["epay_return_url"],
    }
    for field, secret_key in _SECRET_SETTING_FIELDS.items():
        value = config.get(field, "")
        result[f"{field}_configured"] = bool(value)
        result[f"{field}_masked"] = mask_secret(value) if value else ""
    return result


@router.get("/service-settings")
async def get_admin_service_settings(db: AsyncSession = Depends(get_db)) -> dict:
    return await _admin_service_settings(db)


@router.put("/service-settings")
async def put_admin_service_settings(
    body: AdminServiceSettingsIn,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    values = body.model_dump(exclude_unset=True)
    for key, value in values.items():
        if key in _SECRET_SETTING_FIELDS:
            # 空字符串表示未提交新值；敏感字段只能更新，不能通过读取后回传清空。
            if value:
                await set_setting(db, f"registration.{_SECRET_SETTING_FIELDS[key]}", encrypt_secret(value))
            continue
        if value is not None:
            await set_setting(db, f"registration.{key}", str(value).lower() if isinstance(value, bool) else str(value))
    await audit(db, admin.id, None, "service_settings.update", f"更新字段：{', '.join(values.keys())}")
    await db.commit()
    return await _admin_service_settings(db)


class SmtpTestIn(BaseModel):
    to_email: str = Field(min_length=5, max_length=254)


@router.post("/service-settings/smtp-test")
async def test_admin_smtp(
    body: SmtpTestIn,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    import asyncio
    import smtplib
    import ssl
    from email.message import EmailMessage
    import re

    recipient = body.to_email.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
        raise HTTPException(400, "邮箱地址格式不正确")
    from app.registration_security import get_registration_security

    config = await get_registration_security(db)
    if not config["mail_host"] or not (config["mail_sender"] or config["mail_user"]):
        raise HTTPException(400, "SMTP 邮件服务尚未配置")

    def _send_test() -> None:
        msg = EmailMessage()
        msg["Subject"] = "官机云 SMTP 测试邮件"
        msg["From"] = config["mail_sender"] or config["mail_user"]
        msg["To"] = recipient
        msg.set_content("这是一封官机云后台发送的 SMTP 测试邮件。")
        with smtplib.SMTP(config["mail_host"], config["mail_port"], timeout=15) as server:
            if config["mail_starttls"]:
                server.starttls(context=ssl.create_default_context())
            if config["mail_user"]:
                server.login(config["mail_user"], config["mail_password"])
            server.send_message(msg)

    try:
        await asyncio.to_thread(_send_test)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(502, f"SMTP 测试邮件发送失败：{type(exc).__name__}") from exc
    await audit(db, admin.id, None, "smtp.test", f"SMTP 测试邮件发送至 {recipient}")
    await db.commit()
    return {"ok": True}


# ---------- 套餐 / 订单 ----------


class PaymentPlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    duration_days: int = Field(ge=1, le=36500)
    price_cents: int = Field(ge=0, le=100_000_000)
    enabled: bool = True


def _plan_data(plan: PaymentPlan) -> dict:
    return {
        "id": plan.id,
        "name": plan.name,
        "duration_days": plan.duration_days,
        "price_cents": plan.price_cents,
        "enabled": plan.enabled,
        "created_at": plan.created_at,
    }


@router.get("/payment/plans")
async def list_payment_plans(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(PaymentPlan).order_by(PaymentPlan.id))).scalars().all()
    return {"items": [_plan_data(row) for row in rows]}


@router.post("/payment/plans")
async def create_payment_plan(
    body: PaymentPlanIn,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plan = PaymentPlan(**body.model_dump())
    db.add(plan)
    await db.flush()
    await audit(db, admin.id, None, "payment_plan.create", f"创建套餐 {plan.name}（ID {plan.id}）")
    await db.commit()
    await db.refresh(plan)
    return _plan_data(plan)


@router.put("/payment/plans/{plan_id}")
async def update_payment_plan(
    plan_id: int,
    body: PaymentPlanIn,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plan = await db.get(PaymentPlan, plan_id)
    if not plan:
        raise HTTPException(404, "套餐不存在")
    for key, value in body.model_dump().items():
        setattr(plan, key, value)
    await audit(db, admin.id, None, "payment_plan.update", f"更新套餐 {plan.name}（ID {plan.id}）")
    await db.commit()
    await db.refresh(plan)
    return _plan_data(plan)


@router.post("/payment/plans/{plan_id}/enabled")
async def set_payment_plan_enabled(
    plan_id: int,
    body: dict,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plan = await db.get(PaymentPlan, plan_id)
    if not plan:
        raise HTTPException(404, "套餐不存在")
    if not isinstance(body.get("enabled"), bool):
        raise HTTPException(422, "enabled 必须是布尔值")
    plan.enabled = body["enabled"]
    await audit(db, admin.id, None, "payment_plan.enabled", f"套餐 {plan.id} 启用={plan.enabled}")
    await db.commit()
    return {"ok": True, "enabled": plan.enabled}


@router.delete("/payment/plans/{plan_id}")
async def delete_payment_plan(
    plan_id: int,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plan = await db.get(PaymentPlan, plan_id)
    if not plan:
        raise HTTPException(404, "套餐不存在")
    plan_name = plan.name
    await db.delete(plan)
    await audit(db, admin.id, None, "payment_plan.delete", f"删除套餐 {plan_name}（ID {plan_id}）")
    await db.commit()
    return {"ok": True}


@router.get("/payment/orders")
async def list_payment_orders(
    q: str = "", status: str = "", user_id: int | None = None,
    page: int = 1, page_size: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict:
    page, page_size = max(1, page), min(100, max(1, page_size))
    stmt = select(PaymentOrder)
    if q.strip():
        term = q.strip()
        filters = [PaymentOrder.out_trade_no.contains(term), PaymentOrder.plan_name.contains(term)]
        if term.isdigit():
            filters.append(PaymentOrder.id == int(term))
        stmt = stmt.where(or_(*filters))
    if status.strip():
        stmt = stmt.where(PaymentOrder.status == status.strip())
    if user_id is not None:
        stmt = stmt.where(PaymentOrder.user_id == user_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
    rows = (await db.execute(stmt.order_by(PaymentOrder.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    usernames = {u.id: u.username for u in (await db.execute(select(User))).scalars().all()}
    return {
        "total": total,
        "items": [
            {
                "id": order.id,
                "out_trade_no": order.out_trade_no,
                "user_id": order.user_id,
                "username": usernames.get(order.user_id, ""),
                "plan_id": order.plan_id,
                "plan_name": order.plan_name,
                "duration_days": order.duration_days,
                "amount_cents": order.amount_cents,
                "status": order.status,
                "gateway_trade_no": order.gateway_trade_no,
                "paid_at": order.paid_at,
                "expires_at": order.expires_at,
                "created_at": order.created_at,
            }
            for order in rows
        ],
    }


@public.get("/announcement")
async def get_announcement(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"content": await get_setting(db, "announcement")}


@router.get("/maintenance")
async def get_maintenance(db: AsyncSession = Depends(get_db)) -> dict:
    return {"on": (await get_setting(db, "maintenance_mode")) == "1"}


@router.post("/maintenance")
async def set_maintenance(
    body: dict, request: Request,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    on = bool(body.get("on"))
    await set_setting(db, "maintenance_mode", "1" if on else "0")
    supervisor = get_supervisor(request)
    affected = 0
    if on:  # 停掉所有 runner（不动 enabled 期望状态，关闭维护后按 enabled 恢复）
        for instance_id in list(supervisor.runners):
            try:
                await supervisor.stop_instance(instance_id)
                affected += 1
            except Exception:  # noqa: BLE001
                pass
    else:
        rows = (
            await db.execute(select(BotInstance).where(BotInstance.enabled.is_(True)))
        ).scalars().all()
        for inst in rows:
            try:
                await supervisor.start_instance(inst.id)
                affected += 1
            except Exception:  # noqa: BLE001
                pass
    await audit(db, admin.id, None, "maintenance", f"维护模式={'开启' if on else '关闭'}，影响 {affected} 个实例")
    await db.commit()
    return {"ok": True, "on": on, "affected": affected}


# ---------- 邀请码 ----------

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(10))


class InviteIn(BaseModel):
    count: int = Field(default=1, ge=1, le=50)


@router.get("/invites")
async def list_invites(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(InviteCode).order_by(InviteCode.id.desc()).limit(200))).scalars().all()
    users = {u.id: u.username for u in (await db.execute(select(User))).scalars().all()}
    return {
        "items": [
            {
                "id": r.id,
                "code": r.code,
                "created_at": r.created_at,
                "used": r.used_by is not None,
                "used_by": users.get(r.used_by) if r.used_by else "",
                "used_at": r.used_at,
            }
            for r in rows
        ]
    }


@router.post("/invites")
async def create_invites(
    body: InviteIn,
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
) -> dict:
    codes = []
    for _ in range(body.count):
        code = _new_code()
        while (await db.execute(select(InviteCode).where(InviteCode.code == code))).scalar_one_or_none():
            code = _new_code()
        db.add(InviteCode(code=code, created_by=admin.id))
        codes.append(code)
    await audit(db, admin.id, None, "invite.create", f"生成 {len(codes)} 个邀请码")
    await db.commit()
    return {"items": codes}


@router.delete("/invites/{invite_id}")
async def delete_invite(
    invite_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    invite = await db.get(InviteCode, invite_id)
    if not invite:
        raise HTTPException(404, "邀请码不存在")
    if invite.used_by is not None:
        raise HTTPException(400, "已使用的邀请码是注册记录，不能删除")
    await db.delete(invite)
    await db.commit()
    return {"ok": True}
