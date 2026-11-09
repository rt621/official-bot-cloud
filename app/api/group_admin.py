"""群管自动化 API：规则 CRUD、总开关、群管理工具代理、审批策略。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_for_instance, audit, current_user, get_instance, get_supervisor
from app.database import get_db
from app.models import (
    AutomationRule,
    BotInstance,
    GroupAdminConfig,
    User,
)
from app.qq.client import ApiError
from app.runtime.supervisor import Supervisor

router = APIRouter(prefix="/api/instances", tags=["group-admin"])


class RuleIn(BaseModel):
    name: str = Field(default="未命名规则", max_length=64)
    group_openid: str = Field(default="*", max_length=64)
    enabled: bool | None = None  # 不传=不改（行级总开关）
    priority: int = Field(default=100, ge=0, le=10000)
    trigger_type: str = Field(pattern="^(keyword|link|spam|member_join|msg_type|ai_audit)$")
    trigger_params: dict = Field(default_factory=dict)
    actions: list[dict] = Field(default_factory=list)
    # 综合规则：{触发类型: {enabled, params, actions}}；提供时以它为准（trigger_type 等单类型字段作镜像）
    type_configs: dict | None = None


def _rule_out(r: AutomationRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "group_openid": r.group_openid,
        "enabled": r.enabled,
        "priority": r.priority,
        "trigger_type": r.trigger_type,
        "trigger_params": r.trigger_params or {},
        "actions": r.actions or [],
        "type_configs": r.type_configs,
    }


@router.get("/{instance_id}/rules")
async def list_rules(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    rows = (
        await db.execute(
            select(AutomationRule)
            .where(AutomationRule.bot_instance_id == inst.id)
            .order_by(AutomationRule.priority, AutomationRule.id)
        )
    ).scalars().all()
    # 触发类型门禁：装了哪个规则类插件，编辑器里才出现哪些类型
    from app import presets

    installed = await presets.installed_keys(inst.id)
    available = sorted(
        {t for key, types in presets.PRESET_RULE_TYPES.items() if key in installed for t in types}
    )
    return {"items": [_rule_out(r) for r in rows], "available_types": available}


@router.post("/{instance_id}/rules")
async def create_rule(
    instance_id: int,
    body: RuleIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_rule(body)
    data = body.model_dump(exclude_unset=True)
    data.setdefault("enabled", True)
    if data.get("type_configs"):
        # 综合规则：单类型字段存第一份配置作镜像，引擎以 type_configs 为准
        first_t, first_c = next(iter(data["type_configs"].items()))
        data.setdefault("trigger_type", first_t)
        data.setdefault("trigger_params", first_c.get("params") or {})
        data.setdefault("actions", first_c.get("actions") or [])
    row = AutomationRule(bot_instance_id=inst.id, **data)
    db.add(row)
    await audit(db, user.id, inst.id, "rule.create", f"{body.name}({body.trigger_type})")
    await db.commit()
    await _reload(request, inst.id)
    return _rule_out(row)


@router.put("/{instance_id}/rules/{rule_id}")
async def update_rule(
    instance_id: int,
    rule_id: int,
    body: RuleIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_rule(body)
    row = (
        await db.execute(
            select(AutomationRule).where(
                AutomationRule.id == rule_id, AutomationRule.bot_instance_id == inst.id
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "规则不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await audit(db, user.id, inst.id, "rule.update", body.name)
    await db.commit()
    await _reload(request, inst.id)
    return _rule_out(row)


@router.delete("/{instance_id}/rules/{rule_id}")
async def delete_rule(
    instance_id: int,
    rule_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(
        delete(AutomationRule).where(
            AutomationRule.id == rule_id, AutomationRule.bot_instance_id == inst.id
        )
    )
    await audit(db, user.id, inst.id, "rule.delete", str(rule_id))
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


def _validate_rule(body: RuleIn) -> None:
    if body.trigger_type == "keyword" and not (body.trigger_params.get("keywords") or []):
        raise HTTPException(400, "关键词规则至少需要 1 个关键词")
    if body.trigger_type == "msg_type" and not (body.trigger_params.get("msg_types") or []):
        raise HTTPException(400, "消息类型规则至少需要选择 1 个类型")
    if body.trigger_type == "ai_audit":
        p = body.trigger_params
        if not any([
            p.get("send_keywords"), p.get("send_regex"), p.get("send_link"),
            p.get("send_digit_len"), p.get("send_long_text"),
        ]):
            raise HTTPException(400, "AI 审核规则至少要配置一个送审条件（关键词/正则/链接/连续数字/长文本），否则每条消息都会送审")
        import re as _re

        for pat in p.get("send_regex") or []:
            try:
                _re.compile(pat)
            except _re.error as exc:
                raise HTTPException(400, f"送审正则无效：{pat}（{exc}）")
    known = {"recall", "mute", "kick", "blacklist", "notify", "reply", "log"}
    for action in body.actions:
        if action.get("type") not in known:
            raise HTTPException(400, f"未知动作类型：{action.get('type')}")


# ---------- 总开关 + 管理员名单 ----------


class GroupAdminIn(BaseModel):
    master_enabled: bool = True
    admin_openids: str = ""
    default_notify_group: str = ""


@router.get("/{instance_id}/config/groupadmin")
async def get_groupadmin(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    row = (
        await db.execute(
            select(GroupAdminConfig).where(GroupAdminConfig.bot_instance_id == inst.id)
        )
    ).scalar_one_or_none()
    if not row:
        row = GroupAdminConfig(bot_instance_id=inst.id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return {
        "master_enabled": row.master_enabled,
        "admin_openids": row.admin_openids,
        "default_notify_group": row.default_notify_group,
    }


@router.put("/{instance_id}/config/groupadmin")
async def put_groupadmin(
    instance_id: int,
    body: GroupAdminIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(GroupAdminConfig).where(GroupAdminConfig.bot_instance_id == inst.id)
        )
    ).scalar_one_or_none()
    if not row:
        row = GroupAdminConfig(bot_instance_id=inst.id)
        db.add(row)
    row.master_enabled = body.master_enabled
    row.admin_openids = body.admin_openids
    row.default_notify_group = body.default_notify_group
    await audit(db, user.id, inst.id, "config.groupadmin", f"master={body.master_enabled}")
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


@router.get("/{instance_id}/groups")
async def known_groups(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    from app.models import KnownGroup

    rows = (
        await db.execute(
            select(KnownGroup)
            .where(KnownGroup.bot_instance_id == inst.id)
            .order_by(KnownGroup.last_seen.desc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "group_openid": r.group_openid,
                "group_name": r.group_name or "",
                "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            }
            for r in rows
        ]
    }


@router.post("/{instance_id}/groups/refresh-names")
async def refresh_group_names(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动拉取全部已知群的名称（进群后立即点一下即可，不必等机器人收到消息）。"""
    from app.models import KnownGroup

    rows = (
        await db.execute(
            select(KnownGroup).where(KnownGroup.bot_instance_id == inst.id)
        )
    ).scalars().all()
    api = await api_for_instance(inst, get_supervisor(request))
    updated = 0
    for r in rows:
        try:
            info = await api.group_info(r.group_openid)
        except Exception:  # noqa: BLE001  # 机器人不在该群/无权限：保留原记录
            continue
        name = (info.get("group_name") or info.get("name") or "").strip()
        if name and name != r.group_name:
            r.group_name = name[:120]
            updated += 1
    if updated:
        await db.commit()
    return {"ok": True, "updated": updated}


@router.post("/{instance_id}/groups/refresh-names")
async def refresh_group_names(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """逐个拉取已知群的名称（官方 30 QPM，群少时瞬间完成；无权限的群跳过）。"""
    from app.models import KnownGroup

    api = await api_for_instance(inst, get_supervisor(request))
    rows = (
        await db.execute(
            select(KnownGroup).where(KnownGroup.bot_instance_id == inst.id)
        )
    ).scalars().all()
    updated = 0
    failed = 0
    for row in rows:
        try:
            info = await api.group_info(row.group_openid)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        name = info.get("group_name") or info.get("name") or ""
        if name:
            row.group_name = str(name)[:120]
            updated += 1
    await db.commit()
    await audit(db, user.id, inst.id, "groups.refresh_names", f"更新{updated} 失败{failed}")
    await db.commit()
    return {"ok": True, "updated": updated, "failed": failed}


# ---------- 群管理工具代理（页面 → 官方接口） ----------


def _api_error_response(exc: ApiError) -> HTTPException:
    if exc.code in (11252, 11253, 11254):
        return HTTPException(
            502, f"该接口为内邀白名单制或平台无权限（官方错误码 {exc.code}），需联系 QQ 开放平台申请开通"
        )
    if exc.kind == "no_permission":
        return HTTPException(502, f"机器人无权限：请确认机器人已是群管理员（错误码 {exc.code}）")
    return HTTPException(502, f"官方接口错误（{exc.kind}）：{exc.message}")


@router.get("/{instance_id}/groups/{group_openid}/mute-state")
async def mute_state(
    instance_id: int,
    group_openid: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.group_mute_state(group_openid)
    except ApiError as exc:
        raise _api_error_response(exc)


class MuteIn(BaseModel):
    member_openids: list[str] = Field(min_length=1, max_length=20)
    minutes: int = Field(default=10, ge=1, le=43200)


@router.post("/{instance_id}/groups/{group_openid}/mute")
async def mute(
    instance_id: int,
    group_openid: str,
    body: MuteIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.mute_members(
            group_openid,
            [
                {"op": "add", "member_openid": m, "mute_expire_at": _expire(body.minutes)}
                for m in body.member_openids
            ],
        )
    except ApiError as exc:
        raise _api_error_response(exc)
    finally:
        await audit(db, user.id, inst.id, "group.mute", f"{group_openid} {body.member_openids} {body.minutes}min")


@router.post("/{instance_id}/groups/{group_openid}/unmute")
async def unmute(
    instance_id: int,
    group_openid: str,
    body: MuteIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.mute_members(
            group_openid,
            [{"op": "del", "member_openid": m} for m in body.member_openids],
        )
    except ApiError as exc:
        raise _api_error_response(exc)


class KickIn(BaseModel):
    member_openids: list[str] = Field(min_length=1, max_length=20)
    add_to_blacklist: bool = False


@router.post("/{instance_id}/groups/{group_openid}/kick")
async def kick(
    instance_id: int,
    group_openid: str,
    body: KickIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.remove_members(group_openid, body.member_openids, body.add_to_blacklist)
    except ApiError as exc:
        raise _api_error_response(exc)
    finally:
        await audit(db, user.id, inst.id, "group.kick", f"{group_openid} {body.member_openids}")


@router.get("/{instance_id}/groups/{group_openid}/blacklist")
async def blacklist(
    instance_id: int,
    group_openid: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.group_blacklist(group_openid)
    except ApiError as exc:
        raise _api_error_response(exc)


class BlacklistOpIn(BaseModel):
    op: str = Field(pattern="^(add|del)$")
    member_openids: list[str] = Field(min_length=1, max_length=20)


@router.post("/{instance_id}/groups/{group_openid}/blacklist")
async def blacklist_op(
    instance_id: int,
    group_openid: str,
    body: BlacklistOpIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.group_blacklist_op(group_openid, body.op, body.member_openids)
    except ApiError as exc:
        raise _api_error_response(exc)


@router.get("/{instance_id}/groups/{group_openid}/members")
async def members(
    instance_id: int,
    group_openid: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.group_members(group_openid)
    except ApiError as exc:
        raise _api_error_response(exc)


# ---------- 入群自动审批策略 ----------


@router.get("/{instance_id}/join-strategies")
async def list_strategies(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.join_strategies()
    except ApiError as exc:
        raise _api_error_response(exc)


class StrategyIn(BaseModel):
    group_openids: list[str] = Field(min_length=1, max_length=100)
    is_enable: str = Field(default="on", pattern="^(on|off)$")
    remark: str = Field(default="", max_length=255)


@router.post("/{instance_id}/join-strategies")
async def create_strategy(
    instance_id: int,
    body: StrategyIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.create_join_strategy(group_openids=body.group_openids, is_enable=body.is_enable, remark=body.remark)
    except ApiError as exc:
        raise _api_error_response(exc)


@router.delete("/{instance_id}/join-strategies/{strategy_id}")
async def delete_strategy(
    instance_id: int,
    strategy_id: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.delete_join_strategy(strategy_id)
    except ApiError as exc:
        raise _api_error_response(exc)


class WhitelistIn(BaseModel):
    op: str = Field(pattern="^(add|del)$")
    qq_numbers: list[str] = Field(min_length=1, max_length=10000)


@router.post("/{instance_id}/join-strategies/{strategy_id}/whitelist")
async def strategy_whitelist(
    instance_id: int,
    strategy_id: str,
    body: WhitelistIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.join_strategy_whitelist(strategy_id, body.op, body.qq_numbers)
    except ApiError as exc:
        raise _api_error_response(exc)


@router.post("/{instance_id}/join-strategies/{strategy_id}/execute")
async def strategy_execute(
    instance_id: int,
    strategy_id: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.execute_join_strategy(strategy_id)
    except ApiError as exc:
        raise _api_error_response(exc)


@router.get("/{instance_id}/groups/{group_openid}/join-requests-official")
async def official_join_requests(
    instance_id: int,
    group_openid: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.join_requests(group_openid)
    except ApiError as exc:
        raise _api_error_response(exc)


# ---------- 插件市场（预设插件包） ----------


@router.get("/{instance_id}/plugins")
async def list_plugins(
    instance_id: int,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    from app import presets
    from app.models import GroupAdminConfig

    installed = await presets.installed_keys(inst.id)
    items = []
    for p in presets.PRESETS:
        items.append(
            {
                "key": p["key"],
                "name": p["name"],
                "icon": p.get("icon", "🧩"),
                "category": p.get("category", "其他"),
                "type": p["type"],
                "config": p.get("config", ""),
                "tab": p.get("tab", "home"),
                "description": p.get("description", ""),
                "needs": p.get("needs", ""),
                "installed": p["key"] in installed,
            }
        )
    return {"items": items}


@router.post("/{instance_id}/plugins/{key}/install")
async def install_plugin(
    instance_id: int,
    key: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app import presets

    preset = presets.preset_by_key(key)
    if not preset:
        raise HTTPException(404, "插件不存在")
    ga_row = (
        await db.execute(
            select(GroupAdminConfig).where(GroupAdminConfig.bot_instance_id == inst.id)
        )
    ).scalar_one_or_none()
    await presets.install_preset(inst.id, preset)
    await audit(db, user.id, inst.id, "plugin.install", key)
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True, "installed": True}


@router.delete("/{instance_id}/plugins/{key}")
async def uninstall_plugin(
    instance_id: int,
    key: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app import presets

    preset = presets.preset_by_key(key)
    if not preset:
        raise HTTPException(404, "插件不存在")
    await presets.uninstall_preset(inst.id, preset)
    await audit(db, user.id, inst.id, "plugin.uninstall", key)
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True, "installed": False}


@router.post("/plugins/reload")
async def reload_plugins(
    user: User = Depends(current_user),
) -> dict:
    """热重载内置插件（开发期往 plugins 目录放新插件后调用）。"""
    from app.runtime.plugins.loader import plugin_loader

    names = plugin_loader.reload()
    return {"ok": True, "plugins": names}


# ---------- 欢迎插件：按群覆盖配置 ----------


# ---------- 单聊自定义菜单 / 指令面板 ----------


@router.get("/{instance_id}/menu")
async def get_menu_cfg(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.get_menu()
    except ApiError as exc:
        raise _api_error_response(exc)


@router.put("/{instance_id}/menu")
async def put_menu_cfg(
    instance_id: int,
    body: dict,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = body.get("items") or []
    _validate_menu(items)
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        result = await api.put_menu({"items": items})
    except ApiError as exc:
        raise _api_error_response(exc)
    await audit(db, user.id, inst.id, "menu.put", f"{len(items)}项")
    await db.commit()
    return result


def _char_width(s: str) -> int:
    return sum(2 if ord(ch) > 255 else 1 for ch in s)


def _validate_menu(items: list) -> None:
    if not items:
        raise HTTPException(400, "菜单不能为空（如需清空菜单请留一个占位项或联系官方）")
    if len(items) > 10:
        raise HTTPException(400, "一级菜单最多 10 个")
    for item in items:
        name = str(item.get("name", ""))
        if not name:
            raise HTTPException(400, "菜单项缺少名称")
        if _char_width(name) > 10:
            raise HTTPException(400, f"菜单名称「{name}」超长（≤5个汉字）")
        mtype = item.get("type")
        if mtype not in ("send_message", "link", "menu", "switch"):
            raise HTTPException(400, f"菜单类型不合法：{mtype}")
        if mtype == "send_message" and not item.get("send_message"):
            raise HTTPException(400, f"「{name}」缺少要填入的指令内容")
        if mtype == "link":
            link = item.get("link") or ""
            if not link.startswith("https://"):
                raise HTTPException(400, f"「{name}」的链接必须以 https:// 开头")
        if mtype == "menu":
            subs = item.get("sub_menu_items") or []
            if not subs:
                raise HTTPException(400, f"「{name}」是子菜单，至少要有 1 个子项")
            if len(subs) > 5:
                raise HTTPException(400, f"「{name}」子菜单最多 5 个")
            for sub in subs:
                if _char_width(str(sub.get("name", ""))) > 14:
                    raise HTTPException(400, f"「{name}」的子菜单名称超长（≤7个汉字）")
                if sub.get("type") == "menu":
                    raise HTTPException(400, "子菜单不能再嵌套子菜单")
                if sub.get("type") == "link" and not (sub.get("link") or "").startswith("https://"):
                    raise HTTPException(400, f"「{name}」的子菜单链接必须 https://")


@router.get("/{instance_id}/panels")
async def list_panels_cfg(
    instance_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    scope: str = "group",
) -> dict:
    if scope not in ("c2c", "group", "channel", "dm"):
        raise HTTPException(400, "scope 不合法")
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.list_panels(scope)
    except ApiError as exc:
        raise _api_error_response(exc)


class PanelIn(BaseModel):
    scope: str = Field(pattern="^(c2c|group)$")
    target_type: str = Field(default="all", pattern="^(all|specific)$")
    group_openids: list[str] = Field(default_factory=list, max_length=20)
    remark: str = Field(default="", max_length=64)
    items: list[dict] = Field(default_factory=list, max_length=20)


@router.post("/{instance_id}/panels")
async def create_panel_cfg(
    instance_id: int,
    body: PanelIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.items:
        raise HTTPException(400, "指令面板至少要有一个指令项")
    panel = {
        "items": body.items,
        "remark": body.remark or None,
        "version": 1,
    }
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        result = await api.create_panel(
            body.scope,
            panel,
            target_type=body.target_type,
            group_openids=body.group_openids or None,
        )
    except ApiError as exc:
        raise _api_error_response(exc)
    await audit(db, user.id, inst.id, "panel.create", body.scope)
    await db.commit()
    return result


@router.delete("/{instance_id}/panels/{panel_id}")
async def delete_panel_cfg(
    instance_id: int,
    panel_id: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    api = await api_for_instance(inst, get_supervisor(request))
    try:
        return await api.delete_panel(panel_id)
    except ApiError as exc:
        raise _api_error_response(exc)
    finally:
        await audit(db, user.id, inst.id, "panel.delete", panel_id)


# ---------- AI 人设：按群覆盖 ----------


@router.get("/{instance_id}/ai-personas")
async def list_ai_personas(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    from app.models import AiGroupPersona

    rows = (
        await db.execute(
            select(AiGroupPersona).where(AiGroupPersona.bot_instance_id == inst.id)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "group_openid": r.group_openid,
                "chat_persona_name": r.chat_persona_name,
                "chat_persona_desc": r.chat_persona_desc,
                "audit_persona_name": r.audit_persona_name,
                "audit_persona_desc": r.audit_persona_desc,
            }
            for r in rows
        ]
    }


class AiPersonaIn(BaseModel):
    chat_persona_name: str = Field(default="", max_length=64)
    chat_persona_desc: str = ""
    audit_persona_name: str = Field(default="", max_length=64)
    audit_persona_desc: str = ""


@router.put("/{instance_id}/ai-personas/{group_openid}")
async def upsert_ai_persona(
    instance_id: int,
    group_openid: str,
    body: AiPersonaIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import AiGroupPersona

    row = (
        await db.execute(
            select(AiGroupPersona).where(
                AiGroupPersona.bot_instance_id == inst.id,
                AiGroupPersona.group_openid == group_openid,
            )
        )
    ).scalar_one_or_none()
    if not row:
        row = AiGroupPersona(bot_instance_id=inst.id, group_openid=group_openid)
        db.add(row)
    row.chat_persona_name = body.chat_persona_name
    row.chat_persona_desc = body.chat_persona_desc
    row.audit_persona_name = body.audit_persona_name
    row.audit_persona_desc = body.audit_persona_desc
    await audit(db, user.id, inst.id, "ai_persona.upsert", group_openid)
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


@router.delete("/{instance_id}/ai-personas/{group_openid}")
async def delete_ai_persona(
    instance_id: int,
    group_openid: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import AiGroupPersona

    await db.execute(
        delete(AiGroupPersona).where(
            AiGroupPersona.bot_instance_id == inst.id,
            AiGroupPersona.group_openid == group_openid,
        )
    )
    await audit(db, user.id, inst.id, "ai_persona.delete", group_openid)
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


# ---------- 入群审批按群关键词 ----------


class ApprovalGroupIn(BaseModel):
    auto_approve_keywords: str = Field(default="", max_length=10000)


@router.get("/{instance_id}/approval-groups/{group_openid}")
async def get_approval_group(
    group_openid: str,
    inst: BotInstance = Depends(get_instance),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import ApprovalGroupConfig

    row = (
        await db.execute(
            select(ApprovalGroupConfig).where(
                ApprovalGroupConfig.bot_instance_id == inst.id,
                ApprovalGroupConfig.group_openid == group_openid,
            )
        )
    ).scalar_one_or_none()
    return {"auto_approve_keywords": row.auto_approve_keywords if row else ""}


@router.put("/{instance_id}/approval-groups/{group_openid}")
async def put_approval_group(
    group_openid: str,
    body: ApprovalGroupIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import ApprovalGroupConfig

    row = (
        await db.execute(
            select(ApprovalGroupConfig).where(
                ApprovalGroupConfig.bot_instance_id == inst.id,
                ApprovalGroupConfig.group_openid == group_openid,
            )
        )
    ).scalar_one_or_none()
    keywords = body.auto_approve_keywords.strip()
    if not keywords:
        if row:
            await db.delete(row)
    elif row:
        row.auto_approve_keywords = keywords
    else:
        db.add(ApprovalGroupConfig(
            bot_instance_id=inst.id,
            group_openid=group_openid,
            auto_approve_keywords=keywords,
        ))
    await audit(db, user.id, inst.id, "approval.group_keywords", group_openid)
    await db.commit()
    return {"auto_approve_keywords": keywords}


# ---------- 通用功能 × 群 开关 ----------

VALID_FEATURES = {"keywords", "ai", "approval", "report", "fun", "signin", "stats", "schedule"}


@router.get("/{instance_id}/feature-groups")
async def list_feature_groups(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    from app.models import FeatureGroupConfig

    rows = (
        await db.execute(
            select(FeatureGroupConfig).where(
                FeatureGroupConfig.bot_instance_id == inst.id
            )
        )
    ).scalars().all()
    return {
        "items": [
            {"feature": r.feature, "group_openid": r.group_openid, "enabled": r.enabled}
            for r in rows
        ]
    }


class FeatureSwitchIn(BaseModel):
    enabled: bool


@router.put("/{instance_id}/feature-groups/{feature}/{group_openid}")
async def set_feature_group(
    instance_id: int,
    feature: str,
    group_openid: str,
    body: FeatureSwitchIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import FeatureGroupConfig

    if feature not in VALID_FEATURES:
        raise HTTPException(400, f"未知功能：{feature}")
    row = (
        await db.execute(
            select(FeatureGroupConfig).where(
                FeatureGroupConfig.bot_instance_id == inst.id,
                FeatureGroupConfig.feature == feature,
                FeatureGroupConfig.group_openid == group_openid,
            )
        )
    ).scalar_one_or_none()
    if not row:
        row = FeatureGroupConfig(
            bot_instance_id=inst.id, feature=feature, group_openid=group_openid
        )
        db.add(row)
    row.enabled = body.enabled
    await audit(db, user.id, inst.id, f"feature.{feature}", f"{group_openid} -> {'on' if body.enabled else 'off'}")
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


@router.delete("/{instance_id}/feature-groups/{feature}/{group_openid}")
async def reset_feature_group(
    instance_id: int,
    feature: str,
    group_openid: str,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import FeatureGroupConfig

    await db.execute(
        delete(FeatureGroupConfig).where(
            FeatureGroupConfig.bot_instance_id == inst.id,
            FeatureGroupConfig.feature == feature,
            FeatureGroupConfig.group_openid == group_openid,
        )
    )
    await audit(db, user.id, inst.id, f"feature.{feature}", f"{group_openid} -> inherit")
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


# ---------- 工具 ----------


async def _reload(request: Request, instance_id: int) -> None:
    supervisor: Supervisor = get_supervisor(request)
    await supervisor.reload_config(instance_id)


def _expire(minutes: int) -> str:
    import datetime as dt

    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")
