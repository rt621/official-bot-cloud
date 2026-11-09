"""共享依赖与工具：当前用户、实例权限校验、审计、API 客户端获取。"""

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, BotInstance, User
from app.qq.client import ApiClient
from app.security import decode_token
from app.runtime.supervisor import Supervisor
from app.user_state import user_expired

bearer = HTTPBearer(auto_error=False)


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(401, "未登录")
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(401, "登录已过期")
    user = (
        await db.execute(select(User).where(User.id == int(payload["sub"])))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(401, "用户不存在")
    if user.disabled:
        raise HTTPException(403, "账号已被停用，请联系平台管理员")
    if user_expired(user):
        raise HTTPException(403, "账号已到期，请联系平台管理员续期")
    return user


async def admin_required(user: User = Depends(current_user)) -> User:
    """运营后台专用：仅 is_admin 可通过。"""
    if not user.is_admin:
        raise HTTPException(403, "需要平台管理员权限")
    return user


async def get_instance(
    instance_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> BotInstance:
    inst = (
        await db.execute(select(BotInstance).where(BotInstance.id == instance_id))
    ).scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "实例不存在")
    if not user.is_admin and inst.user_id != user.id:
        raise HTTPException(403, "无权访问该实例")
    return inst


async def audit(
    db: AsyncSession, user_id: int | None, instance_id: int | None, action: str, detail: str = ""
) -> None:
    db.add(AuditLog(user_id=user_id, bot_instance_id=instance_id, action=action, detail=detail[:500]))
    await db.commit()


def get_supervisor(request) -> Supervisor:  # noqa: ANN001
    supervisor = getattr(request.app.state, "supervisor", None)
    if supervisor is None:
        raise HTTPException(503, "运行时未就绪")
    return supervisor


async def api_for_instance(inst: BotInstance, supervisor: Supervisor | None = None) -> ApiClient:
    """页面触发的 API 调用：优先复用运行中实例的客户端（共享 token 缓存）。"""
    if supervisor:
        runner = supervisor.runners.get(inst.id)
        if runner:
            return runner.ctx.api
    from app.security import decrypt_secret

    return ApiClient(inst.appid, decrypt_secret(inst.secret_enc))
