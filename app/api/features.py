"""关键词规则、定时任务、审批、统计、日志等横切资源接口。"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_for_instance, audit, current_user, get_instance, get_supervisor
from app.database import get_db, SessionLocal
from app.models import (
    AuditLog,
    BotInstance,
    ModerationHit,
    PendingJoinRequest,
    RuntimeLog,
    ScheduleTask,
    User,
    DailyStat,
    SigninRecord,
)
from app.qq.client import ApiError
from app.runtime.supervisor import Supervisor

router = APIRouter(prefix="/api/instances", tags=["features"])


# ---------- 关键词规则 ----------


class KeywordIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=256)
    reply_type: str = Field(default="text", pattern="^(text|image)$")
    reply_content: str = Field(min_length=1)
    trigger_scope: str = Field(default="all", pattern="^(all|at)$")
    group_openid: str = Field(default="*", max_length=64)
    enabled: bool = True


@router.get("/{instance_id}/keywords")
async def list_keywords(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    from app.models import KeywordRule

    rows = (
        await db.execute(
            select(KeywordRule)
            .where(KeywordRule.bot_instance_id == inst.id)
            .order_by(KeywordRule.id)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "pattern": r.pattern,
                "reply_type": r.reply_type,
                "reply_content": r.reply_content,
                "trigger_scope": r.trigger_scope,
                "group_openid": getattr(r, "group_openid", "*") or "*",
                "enabled": r.enabled,
            }
            for r in rows
        ]
    }


@router.post("/{instance_id}/keywords")
async def create_keyword(
    instance_id: int,
    body: KeywordIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import KeywordRule

    row = KeywordRule(bot_instance_id=inst.id, **body.model_dump())
    db.add(row)
    await audit(db, user.id, inst.id, "keyword.create", body.pattern)
    await db.commit()
    await _reload(request, inst.id)
    return {"id": row.id}


@router.put("/{instance_id}/keywords/{rule_id}")
async def update_keyword(
    instance_id: int,
    rule_id: int,
    body: KeywordIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import KeywordRule
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(KeywordRule)
        .where(KeywordRule.id == rule_id, KeywordRule.bot_instance_id == inst.id)
        .values(**body.model_dump())
    )
    await audit(db, user.id, inst.id, "keyword.update", body.pattern)
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


@router.delete("/{instance_id}/keywords/{rule_id}")
async def delete_keyword(
    instance_id: int,
    rule_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import KeywordRule

    await db.execute(
        delete(KeywordRule).where(
            KeywordRule.id == rule_id, KeywordRule.bot_instance_id == inst.id
        )
    )
    await audit(db, user.id, inst.id, "keyword.delete", str(rule_id))
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


# ---------- 定时任务 ----------


class ScheduleIn(BaseModel):
    name: str = Field(default="定时任务", max_length=64)
    cron: str = Field(min_length=3, max_length=64)
    target_group_openid: str = Field(default="", max_length=64)
    task_type: str = Field(default="text", pattern="^(text|image)$")
    content: str = Field(min_length=1)
    enabled: bool = True


def _check_schedule_target(body: ScheduleIn) -> None:
    """每条定时任务都必须指定一个真实群：留空是用户漏选，不是全局任务。"""
    body.target_group_openid = body.target_group_openid.strip()
    if len(body.target_group_openid) < 6:
        raise HTTPException(400, "请选择目标群：每条定时任务都要指定发到哪个群")


@router.get("/{instance_id}/schedules")
async def list_schedules(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    rows = (
        await db.execute(
            select(ScheduleTask)
            .where(ScheduleTask.bot_instance_id == inst.id)
            .order_by(ScheduleTask.id)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "cron": r.cron,
                "target_group_openid": r.target_group_openid,
                "task_type": r.task_type,
                "content": r.content,
                "enabled": r.enabled,
                "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
            }
            for r in rows
        ]
    }


@router.post("/{instance_id}/schedules")
async def create_schedule(
    instance_id: int,
    body: ScheduleIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_cron(body.cron)
    _check_schedule_target(body)
    row = ScheduleTask(bot_instance_id=inst.id, **body.model_dump())
    db.add(row)
    await audit(db, user.id, inst.id, "schedule.create", body.name)
    await db.commit()
    await _reload(request, inst.id)
    return {"id": row.id}


@router.put("/{instance_id}/schedules/{task_id}")
async def update_schedule(
    instance_id: int,
    task_id: int,
    body: ScheduleIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_cron(body.cron)
    _check_schedule_target(body)
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(ScheduleTask)
        .where(ScheduleTask.id == task_id, ScheduleTask.bot_instance_id == inst.id)
        .values(**body.model_dump())
    )
    await audit(db, user.id, inst.id, "schedule.update", body.name)
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


@router.delete("/{instance_id}/schedules/{task_id}")
async def delete_schedule(
    instance_id: int,
    task_id: int,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(
        delete(ScheduleTask).where(
            ScheduleTask.id == task_id, ScheduleTask.bot_instance_id == inst.id
        )
    )
    await audit(db, user.id, inst.id, "schedule.delete", str(task_id))
    await db.commit()
    await _reload(request, inst.id)
    return {"ok": True}


def _validate_cron(cron: str) -> None:
    from croniter import croniter

    try:
        croniter(cron)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"cron 表达式无效：{exc}")


# ---------- 入群审批 ----------


@router.get("/{instance_id}/join-requests")
async def list_join_requests(
    inst: BotInstance = Depends(get_instance),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(PendingJoinRequest)
            .where(PendingJoinRequest.bot_instance_id == inst.id)
            .order_by(PendingJoinRequest.id.desc())
            .limit(100)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "group_openid": r.group_openid,
                "member_openid": r.member_openid,
                "answer": r.answer,
                "risk_tips": r.risk_tips,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


class ReviewIn(BaseModel):
    request_id: int
    op: str = Field(pattern="^(approve|decline)$")
    reject_reason: str = ""
    add_to_blacklist: bool = False


@router.post("/{instance_id}/join-requests/review")
async def review_join_request(
    instance_id: int,
    body: ReviewIn,
    request: Request,
    inst: BotInstance = Depends(get_instance),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(PendingJoinRequest).where(
                PendingJoinRequest.id == body.request_id,
                PendingJoinRequest.bot_instance_id == inst.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "申请不存在")
    if row.status != "pending":
        raise HTTPException(400, "该申请已处理")

    supervisor: Supervisor = get_supervisor(request)
    api = await api_for_instance(inst, supervisor)
    try:
        await api.approve_join_request(
            row.group_openid,
            row.member_openid,
            body.op,
            body.reject_reason,
            body.add_to_blacklist,
        )
    except ApiError as exc:
        raise HTTPException(502, f"调用官方接口失败（{exc.kind}）：{exc.message}")
    row.status = "approved" if body.op == "approve" else "declined"
    await audit(db, user.id, inst.id, f"join_request.{body.op}", row.member_openid)
    await db.commit()
    return {"ok": True}


# ---------- 监控命中记录 ----------


@router.get("/{instance_id}/moderation-hits")
async def list_moderation_hits(
    inst: BotInstance = Depends(get_instance), db: AsyncSession = Depends(get_db)
) -> dict:
    rows = (
        await db.execute(
            select(ModerationHit)
            .where(ModerationHit.bot_instance_id == inst.id)
            .order_by(ModerationHit.id.desc())
            .limit(200)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "group_openid": r.group_openid,
                "user_openid": r.user_openid,
                "reason": r.reason,
                "excerpt": r.excerpt,
                "actions": r.actions,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


# ---------- 统计 ----------


@router.get("/{instance_id}/stats")
async def get_stats(
    instance_id: int,
    inst: BotInstance = Depends(get_instance),
    db: AsyncSession = Depends(get_db),
    days: int = 7,
    group_openid: str = "",
) -> dict:
    from datetime import date, timedelta

    since = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    stats_stmt = select(DailyStat).where(
        DailyStat.bot_instance_id == inst.id, DailyStat.day >= since
    )
    if group_openid:
        # 按群视图：只看这个群的统计
        stats_stmt = stats_stmt.where(DailyStat.group_openid == group_openid)
    stats_rows = (await db.execute(stats_stmt.order_by(DailyStat.day))).scalars().all()
    # 签到记录没有群维度：按群视图不返回签到数据
    signin_rows = []
    if not group_openid:
        signin_rows = (
            await db.execute(
                select(SigninRecord)
                .where(SigninRecord.bot_instance_id == inst.id, SigninRecord.day >= since)
                .order_by(SigninRecord.day)
            )
        ).scalars().all()

    by_day: dict[str, int] = {}
    top_users: dict[str, dict] = {}
    for r in stats_rows:
        by_day[r.day] = by_day.get(r.day, 0) + r.msg_count
        entry = top_users.setdefault(
            r.user_openid, {"user": r.user_name or r.user_openid, "count": 0}
        )
        entry["count"] += r.msg_count
    top = sorted(top_users.values(), key=lambda x: -x["count"])[:20]
    return {
        "messages_by_day": by_day,
        "top_users": top,
        "signins_by_day": {
            d: sum(1 for r in signin_rows if r.day == d) for d in sorted({r.day for r in signin_rows})
        },
        "signin_streaks": sorted(
            (
                {"user": r.user_name or r.user_openid, "streak": r.streak}
                for r in signin_rows
                if r.day == date.today().strftime("%Y-%m-%d")
            ),
            key=lambda x: -x["streak"],
        )[:20],
    }


# ---------- 日志 ----------


@router.get("/{instance_id}/logs")
async def get_logs(
    instance_id: int,
    inst: BotInstance = Depends(get_instance),
    db: AsyncSession = Depends(get_db),
    level: str = "",
    limit: int = 200,
) -> dict:
    stmt = (
        select(RuntimeLog)
        .where(RuntimeLog.bot_instance_id == inst.id)
        .order_by(RuntimeLog.id.desc())
        .limit(min(limit, 500))
    )
    if level:
        stmt = stmt.where(RuntimeLog.level == level)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "level": r.level,
                "message": r.message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/audit-logs")
async def get_audit_logs(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db), limit: int = 200
) -> dict:
    rows = (
        await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)))
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "bot_instance_id": r.bot_instance_id,
                "action": r.action,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


async def _reload(request: Request, instance_id: int) -> None:
    supervisor: Supervisor = get_supervisor(request)
    await supervisor.reload_config(instance_id)
