"""机器人实例：绑定、启停、状态、各功能配置、自检。"""

import contextlib

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_for_instance, audit, current_user, get_instance, get_supervisor
from app.config import settings
from app.database import get_db
from app.models import (
    INSTANCE_CASCADE_MODELS,
    AiConfig,
    ApprovalConfig,
    BotInstance,
    ModerationConfig,
    ReportConfig,
    SigninConfig,
    User,
)
from app.qq.client import ApiError
from app.runtime.supervisor import Supervisor
from app.security import encrypt_secret, mask_secret
from app.sysconf import maintenance_on, max_instances_per_user

router = APIRouter(prefix="/api/instances", tags=["instances"])


class BindIn(BaseModel):
    appid: str = Field(min_length=6, max_length=32)
    app_secret: str = Field(min_length=6, max_length=128)
    name: str = Field(default="", max_length=64)


def _inst_out(inst: BotInstance) -> dict:
    return {
        "id": inst.id,
        "appid": inst.appid,
        "name": inst.name,
        "enabled": inst.enabled,
        "status": inst.status,
        "status_detail": inst.status_detail,
        "last_online_at": inst.last_online_at.isoformat() if inst.last_online_at else None,
        "created_at": inst.created_at.isoformat() if inst.created_at else None,
    }


@router.get("")
async def list_instances(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    stmt = select(BotInstance)
    if not user.is_admin:
        stmt = stmt.where(BotInstance.user_id == user.id)
    rows = (await db.execute(stmt.order_by(BotInstance.id))).scalars().all()
    return {"items": [_inst_out(r) for r in rows]}


@router.post("")
async def bind_instance(
    body: BindIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.is_admin and await maintenance_on(db):
        raise HTTPException(503, "平台维护中，暂不能绑定机器人，请稍后再试")
    count = (
        await db.execute(
            select(BotInstance.id).where(BotInstance.user_id == user.id)
        )
    ).scalars().all()
    if not user.is_admin and len(count) >= await max_instances_per_user(db):
        raise HTTPException(400, f"每用户最多绑定 {await max_instances_per_user(db)} 个机器人")
    if (await db.execute(select(BotInstance).where(BotInstance.appid == body.appid))).scalar_one_or_none():
        raise HTTPException(400, "该 AppID 已被绑定")

    # 用官方接口验证凭证有效性
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.bot.qq.com/app/getAppAccessToken",
                json={"appId": body.appid, "clientSecret": body.app_secret},
            )
            data = resp.json() if resp.status_code == 200 else {}
    except httpx.HTTPError:
        raise HTTPException(502, "无法连接 QQ 开放平台，请稍后重试")
    token = data.get("accessToken") or data.get("access_token") or ""
    if not token:
        raise HTTPException(400, "凭证校验失败：AppID 或 AppSecret 不正确")

    inst = BotInstance(
        user_id=user.id,
        appid=body.appid,
        secret_enc=encrypt_secret(body.app_secret),
        name=body.name or body.appid,
        enabled=True,
    )
    db.add(inst)
    await db.flush()
    # 默认配置行
    for model in (AiConfig, ModerationConfig, ApprovalConfig, ReportConfig, SigninConfig):
        db.add(model(bot_instance_id=inst.id))
    from app.models import GroupAdminConfig

    db.add(GroupAdminConfig(bot_instance_id=inst.id))
    await audit(db, user.id, inst.id, "bind_instance", f"绑定机器人 {inst.appid}")
    await db.commit()

    # 立即尝试启动
    supervisor: Supervisor = get_supervisor(request)
    try:
        await supervisor.start_instance(inst.id)
    except Exception:  # noqa: BLE001
        pass  # 错误状态已写入实例表，页面可见
    return _inst_out(inst)


@router.delete("/{instance_id}")
async def unbind_instance(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    supervisor: Supervisor = get_supervisor(request)
    await supervisor.stop_instance(instance_id)
    for model in INSTANCE_CASCADE_MODELS:
        await db.execute(delete(model).where(model.bot_instance_id == instance_id))
    await db.execute(delete(BotInstance).where(BotInstance.id == instance_id))
    await audit(db, user.id, instance_id, "unbind_instance", f"解绑机器人 {inst.appid}")
    await db.commit()
    return {"ok": True}


@router.post("/{instance_id}/start")
async def start_instance(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.is_admin and await maintenance_on(db):
        raise HTTPException(503, "平台维护中，暂不能启动机器人")
    await db.execute(update(BotInstance).where(BotInstance.id == inst.id).values(enabled=True))
    await audit(db, user.id, inst.id, "start_instance")
    await db.commit()
    supervisor: Supervisor = get_supervisor(request)
    await supervisor.start_instance(inst.id)
    return {"ok": True}


@router.post("/{instance_id}/stop")
async def stop_instance(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(update(BotInstance).where(BotInstance.id == inst.id).values(enabled=False))
    await audit(db, user.id, inst.id, "stop_instance")
    await db.commit()
    supervisor: Supervisor = get_supervisor(request)
    await supervisor.stop_instance(inst.id, set_disabled=False)
    return {"ok": True}


@router.post("/{instance_id}/restart")
async def restart_instance(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.is_admin and await maintenance_on(db):
        raise HTTPException(503, "平台维护中，暂不能重启机器人")
    await audit(db, user.id, inst.id, "restart_instance")
    await db.commit()
    supervisor: Supervisor = get_supervisor(request)
    await supervisor.stop_instance(inst.id)
    await supervisor.start_instance(inst.id)
    return {"ok": True}


class CredentialIn(BaseModel):
    appid: str = Field(default="", min_length=0, max_length=32)  # 空=不改
    app_secret: str = Field(min_length=6, max_length=128)
    name: str = Field(default="", max_length=64)  # 空=不改


@router.put("/{instance_id}/credentials")
async def update_credentials(
    instance_id: int,
    body: CredentialIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新机器人凭证：AppSecret 轮换，或整个换成另一台机器人（AppID+Secret 配套，官方校验通过才落库）。"""
    new_appid = body.appid.strip() or inst.appid
    if new_appid != inst.appid:
        if not body.appid.strip():
            raise HTTPException(400, "修改 AppID 时必须同时填写对应的 AppSecret")
        exists = (
            await db.execute(select(BotInstance).where(BotInstance.appid == new_appid))
        ).scalar_one_or_none()
        if exists:
            raise HTTPException(400, f"AppID {new_appid} 已被其他实例绑定")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.bot.qq.com/app/getAppAccessToken",
                json={"appId": new_appid, "clientSecret": body.app_secret},
            )
            data = resp.json() if resp.status_code == 200 else {}
    except httpx.HTTPError:
        raise HTTPException(502, "无法连接 QQ 开放平台，请稍后重试")
    token = data.get("accessToken") or data.get("access_token") or ""
    if not token:
        raise HTTPException(400, "凭证校验失败：AppID 与 AppSecret 不匹配，请到开放平台核对")
    old_appid = inst.appid
    inst.appid = new_appid
    inst.secret_enc = encrypt_secret(body.app_secret)
    if body.name.strip():
        inst.name = body.name.strip()
    detail = f"AppID {old_appid} → {new_appid}" if new_appid != old_appid else f"更新机器人 {new_appid} 的 AppSecret"
    await audit(db, user.id, inst.id, "update_credentials", detail)
    await db.commit()
    supervisor: Supervisor = get_supervisor(request)
    with contextlib.suppress(Exception):
        await supervisor.stop_instance(inst.id)
    if inst.enabled:
        with contextlib.suppress(Exception):
            await supervisor.start_instance(inst.id)  # 失败状态已写入实例表，页面可见
    return {"ok": True, "appid": new_appid, "name": inst.name}


# ---------- 功能配置 ----------
async def _notify_reload(request: Request, instance_id: int) -> None:
    supervisor: Supervisor = get_supervisor(request)
    await supervisor.reload_config(instance_id)


class AiIn(BaseModel):
    enabled: bool = False
    api_base: str = "https://api.z.ai/api/paas/v4"
    api_key: str = ""  # 留空=不修改
    model: str = "glm-4-flash"
    system_prompt: str = "你是一个友好的群聊助手，回答简洁准确。"
    trigger_mode: str = "at"
    trigger_keywords: str = "问答,问问"
    daily_limit_per_user: int = Field(default=20, ge=1, le=1000)
    max_history: int = Field(default=6, ge=0, le=20)
    persona_name: str = Field(default="", max_length=64)
    persona_desc: str = ""
    audit_persona_name: str = Field(default="", max_length=64)
    audit_persona_desc: str = ""
    group_rules_text: str = ""


class ModerationIn(BaseModel):
    enabled: bool = False
    keywords: str = ""
    block_links: bool = True
    spam_window_seconds: int = Field(default=10, ge=3, le=300)
    spam_max_messages: int = Field(default=5, ge=2, le=50)
    auto_recall: bool = True
    auto_mute_minutes: int = Field(default=0, ge=0, le=43200)
    auto_blacklist: bool = False
    notify_group_openid: str = ""
    whitelist_openids: str = ""


class ApprovalIn(BaseModel):
    enabled: bool = False
    mode: str = "manual"
    notify_group_openid: str = ""
    auto_approve_keywords: str = ""


class ReportIn(BaseModel):
    enabled: bool = False
    notify_group_openid: str = ""


class SigninIn(BaseModel):
    enabled: bool = False
    reward_template: str = "签到成功！已连续签到 {days} 天"


def _cfg_out(obj, secret_key: str | None = None) -> dict:
    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    data.pop("id", None)
    data.pop("bot_instance_id", None)
    if secret_key and data.get(secret_key):
        from app.security import decrypt_secret

        data[secret_key + "_masked"] = mask_secret(decrypt_secret(data[secret_key]))
        data.pop(secret_key)
    return data


def _config_routes(model, pydantic_in, path: str, secret_key: str | None = None):
    async def get_cfg(
        inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
    ) -> dict:
        row = (
            await db.execute(select(model).where(model.bot_instance_id == inst.id))
        ).scalar_one_or_none()
        if not row:
            row = model(bot_instance_id=inst.id)
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return _cfg_out(row, secret_key)

    async def put_cfg(
        body: dict,
        request: Request,
        inst: BotInstance = Depends(get_instance),
        user: User = Depends(current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        row = (
            await db.execute(select(model).where(model.bot_instance_id == inst.id))
        ).scalar_one_or_none()
        if not row:
            row = model(bot_instance_id=inst.id)
            db.add(row)
        fields = set(pydantic_in.model_fields)
        for key, value in body.items():
            if key in fields:
                if secret_key and key == secret_key:
                    if value:  # 留空=不修改
                        setattr(row, "api_key_enc", encrypt_secret(str(value)))
                elif hasattr(row, key):
                    setattr(row, key, value)
        await audit(db, user.id, inst.id, f"config.{path}", str(list(body.keys())))
        await db.commit()
        await _notify_reload(request, inst.id)
        return _cfg_out(row, secret_key)

    return get_cfg, put_cfg


for _path, _model, _in, _secret in [
    ("ai", AiConfig, AiIn, "api_key"),
    ("moderation", ModerationConfig, ModerationIn, None),
    ("approval", ApprovalConfig, ApprovalIn, None),
    ("report", ReportConfig, ReportIn, None),
    ("signin", SigninConfig, SigninIn, None),
]:
    _get, _put = _config_routes(_model, _in, _path, _secret)
    router.get(f"/{{instance_id}}/config/{_path}")(_get)
    router.put(f"/{{instance_id}}/config/{_path}")(_put)


@router.post("/{instance_id}/selfcheck")
async def selfcheck(
    instance_id: int,
    body: dict,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    """对指定群做自检：机器人状态（是否管理员、消息范围、主动推送开关）。"""
    group_openid = str(body.get("group_openid", "")).strip()
    if not group_openid:
        raise HTTPException(400, "请提供 group_openid（可从任一群消息事件或日志中获取）")
    supervisor: Supervisor = get_supervisor(request)
    api = await api_for_instance(inst, supervisor)
    checks: dict = {"group_openid": group_openid}
    try:
        state = await api.group_bot_state(group_openid)
        checks["bot_state"] = state
    except ApiError as exc:
        checks["bot_state_error"] = f"{exc.kind}: {exc.message}"
    try:
        checks["group_info"] = await api.group_info(group_openid)
    except ApiError as exc:
        checks["group_info_error"] = f"{exc.kind}: {exc.message}"

    advice: list[str] = []
    state = checks.get("bot_state") or {}
    role = state.get("role") or state.get("bot_role") or ""
    if role and role != "admin":
        advice.append("机器人不是群管理员：请群主在群设置中将机器人设为管理员（撤回/禁言/审批需要管理员身份）")
    msg_scope = state.get("receive_message_mode") or state.get("message_mode") or ""
    if msg_scope and msg_scope != "all":
        advice.append("消息范围不是“获取群内全部消息”：请群主在群设置→机器人→消息范围 中开启，否则关键词/监控收不到非@消息")
    if state.get("active_push_disabled") or state.get("is_allow_active_push") is False:
        advice.append("主动推送被关闭：请群主在群设置中打开“机器人主动在群聊内发言”")
    if "bot_state_error" in checks:
        advice.append("无法读取机器人群内状态：确认机器人已在该群中，且平台有该接口权限")
    checks["advice"] = advice
    return checks
