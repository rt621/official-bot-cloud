"""注册 / 登录 / 当前用户。"""

import datetime as dt
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.database import get_db
from app.models import EmailVerification, InviteCode, LoginLog, User
from app.security import create_token, hash_password, verify_password
from app.sysconf import registration_mode
from app.user_state import user_expired
from app.registration_security import get_registration_security, secret_digest, send_email, verify_turnstile

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    email: str = Field(min_length=5, max_length=254)
    email_code: str = Field(min_length=6, max_length=6)
    turnstile_token: str = Field(default="", max_length=4096)
    invite_code: str = Field(default="", max_length=32)


class LoginIn(BaseModel):
    username: str
    password: str


class EmailCodeIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    turnstile_token: str = Field(default="", max_length=4096)


@router.post("/email-code")
async def send_registration_email_code(
    body: EmailCodeIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    mode = await registration_mode(db)
    if mode == "closed":
        raise HTTPException(403, "平台未开放注册")
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(400, "邮箱格式不正确")
    if (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(409, "该邮箱已被注册")
    now = dt.datetime.now(dt.timezone.utc)
    recent = (
        await db.execute(
            select(EmailVerification).where(
                EmailVerification.email == email,
                EmailVerification.created_at >= now - dt.timedelta(seconds=60),
            ).order_by(EmailVerification.id.desc()).limit(1)
        )
    ).scalars().first()
    if recent:
        raise HTTPException(429, "验证码已发送，请 60 秒后再试")
    ip = request.client.host if request.client else ""
    ip_count = (
        await db.execute(
            select(func.count()).select_from(EmailVerification).where(
                EmailVerification.request_ip == ip,
                EmailVerification.created_at >= now - dt.timedelta(hours=1),
            )
        )
    ).scalar_one()
    if ip_count >= 10:
        raise HTTPException(429, "请求过于频繁，请稍后再试")
    config = await get_registration_security(db)
    await verify_turnstile(config, body.turnstile_token, request.client.host if request.client else "", request.url.hostname or "")
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        await send_email(config, email, code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "邮件发送失败，请稍后再试") from exc
    db.add(EmailVerification(
        email=email,
        code_hash=secret_digest(code),
        expires_at=now + dt.timedelta(minutes=10),
        request_ip=ip,
    ))
    await db.commit()
    return {"ok": True, "cooldown_seconds": 60}


@router.post("/register")
async def register(body: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    mode = await registration_mode(db)
    if mode == "closed":
        raise HTTPException(403, "平台未开放注册，请联系管理员开通账号")
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(400, "邮箱格式不正确")
    config = await get_registration_security(db)
    await verify_turnstile(config, body.turnstile_token, request.client.host if request.client else "", request.url.hostname or "")
    if await db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(400, "用户名已存在")
    if await db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(400, "该邮箱已被注册")
    now = dt.datetime.now(dt.timezone.utc)
    verification = (
        await db.execute(
            select(EmailVerification)
            .where(
                EmailVerification.email == email,
                EmailVerification.used_at.is_(None),
                EmailVerification.expires_at > now,
            )
            .order_by(EmailVerification.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if not verification or verification.attempts >= 5:
        raise HTTPException(400, "验证码无效或已过期")
    if not secrets.compare_digest(verification.code_hash, secret_digest(body.email_code)):
        claimed = await db.execute(
            update(EmailVerification)
            .where(
                EmailVerification.id == verification.id,
                EmailVerification.used_at.is_(None),
                EmailVerification.attempts < 5,
            )
            .values(attempts=EmailVerification.attempts + 1)
        )
        await db.commit()
        if claimed.rowcount != 1:
            raise HTTPException(400, "验证码无效或已过期")
        raise HTTPException(400, "验证码错误")

    invite: InviteCode | None = None
    if mode == "invite":
        if not body.invite_code.strip():
            raise HTTPException(400, "注册需要邀请码")
        invite = (
            await db.execute(
                select(InviteCode).where(
                    InviteCode.code == body.invite_code.strip(),
                    InviteCode.used_by.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not invite:
            raise HTTPException(400, "邀请码无效或已被使用")
    user = User(
        username=body.username,
        email=email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    claimed = await db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.id == verification.id,
            EmailVerification.used_at.is_(None),
            EmailVerification.expires_at > now,
            EmailVerification.attempts < 5,
        )
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(400, "验证码已使用或过期")
    if invite:
        invite.used_by = user.id
        invite.used_at = now
    db.add(LoginLog(user_id=user.id, ip=request.client.host if request.client else ""))
    await db.commit()
    return {"token": create_token(user.id, user.is_admin), "username": user.username}



@router.post("/login")
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "用户名或密码错误")
    if user.disabled:
        raise HTTPException(403, "账号已被停用，请联系平台管理员")
    if user_expired(user):
        raise HTTPException(403, "账号已到期，请联系平台管理员续期")
    db.add(LoginLog(user_id=user.id, ip=request.client.host if request.client else ""))
    await db.commit()
    return {"token": create_token(user.id, user.is_admin), "username": user.username, "is_admin": user.is_admin}


@router.get("/me")
async def me(user: User = Depends(current_user)) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "expires_at": user.expires_at,
        "expired": user_expired(user),
    }


@router.get("/registration-mode")
async def get_registration_mode(db: AsyncSession = Depends(get_db)) -> dict:
    """注册页判断要不要显示邀请码输入框（无需登录）。"""
    config = await get_registration_security(db)
    return {
        "mode": await registration_mode(db),
        "turnstile_enabled": config["turnstile_enabled"],
        "turnstile_site_key": config["turnstile_site_key"],
    }
