"""入群审批插件：GROUP_JOIN_REQUEST 事件 → 记录 + 通知管理员，页面端/指令审批。"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApprovalGroupConfig, PendingJoinRequest
from app.runtime.context import InstanceContext
from app.runtime.plugins.base import Plugin


class ApprovalPlugin(Plugin):
    name = "approval"
    order = 65

    async def on_join_request(self, ctx: InstanceContext, ev: dict) -> None:
        cfg = ctx.configs.get("approval")
        if not cfg or not cfg.enabled:
            return
        group = ev.get("group_openid", "")
        if not ctx.feature_enabled("approval", group):
            return
        member = ev.get("member_openid") or ev.get("user_openid") or ""
        if not group or not member:
            return
        answer = str(ev.get("verify_info", {}).get("verify_message", "") or "")
        risk = str(ev.get("risk_tips", "") or "")

        async with SessionLocal() as db:
            db.add(
                PendingJoinRequest(
                    bot_instance_id=ctx.instance_id,
                    group_openid=group,
                    member_openid=member,
                    user_name=member,
                    answer=answer[:500],
                    risk_tips=risk[:250],
                )
            )
            group_cfg = (
                await db.execute(
                    select(ApprovalGroupConfig).where(
                        ApprovalGroupConfig.bot_instance_id == ctx.instance_id,
                        ApprovalGroupConfig.group_openid == group,
                    )
                )
            ).scalar_one_or_none()
            await db.commit()

        # A blank group value inherits the global approval keywords.
        keyword_text = (
            group_cfg.auto_approve_keywords
            if group_cfg and group_cfg.auto_approve_keywords.strip()
            else cfg.auto_approve_keywords
        )
        keywords = [k.strip() for k in keyword_text.splitlines() if k.strip()]
        if keywords and any(k in answer for k in keywords):
            await ctx.api.approve_join_request(group, member, "approve")
            async with SessionLocal() as db:
                row = (
                    await db.execute(
                        select(PendingJoinRequest)
                        .where(
                            PendingJoinRequest.bot_instance_id == ctx.instance_id,
                            PendingJoinRequest.member_openid == member,
                            PendingJoinRequest.status == "pending",
                        )
                        .order_by(PendingJoinRequest.id.desc())
                        .limit(1)
                    )
                ).scalars().first()
                if row:
                    row.status = "approved"
                await db.commit()
            await ctx.log("info", f"自动通过 {member} 的入群申请（命中关键词）")
            return


