"""统计插件：群发言统计 + 举报通道。"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import DailyStat, ReportConfig
from app.runtime.context import InstanceContext, today
from app.runtime.plugins.base import Plugin


class StatsPlugin(Plugin):
    name = "stats"
    order = 50

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        if not ev["content"] or ev["content"].startswith("/"):
            return
        if not ctx.feature_enabled("stats", ev["group_openid"]):
            return
        day = today()
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(DailyStat).where(
                        DailyStat.bot_instance_id == ctx.instance_id,
                        DailyStat.day == day,
                        DailyStat.group_openid == ev["group_openid"],
                        DailyStat.user_openid == ev["user_openid"],
                    )
                )
            ).scalar_one_or_none()
            if row:
                row.msg_count += 1
                row.user_name = ev["user_name"] or row.user_name
            else:
                db.add(
                    DailyStat(
                        bot_instance_id=ctx.instance_id,
                        day=day,
                        group_openid=ev["group_openid"],
                        user_openid=ev["user_openid"],
                        user_name=ev["user_name"] or ev["user_openid"],
                        msg_count=1,
                    )
                )
            await db.commit()


class ReportPlugin(Plugin):
    name = "report"
    order = 60

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        # 先确认是举报指令再判断开关，否则功能关闭时会对群里每条消息回复"未开启"
        content = ev["content"]
        if not content.startswith(("/举报", "举报 ")):
            return
        cfg: ReportConfig | None = ctx.configs.get("report")
        if not cfg or not cfg.enabled or not ctx.feature_enabled("report", ev["group_openid"]):
            await ctx.send_group(
                ev["group_openid"], "「举报」功能未开启（可在管理面板开启）", msg_id=ev["event_id"]
            )
            return
        target = ctx.configs.get("notify_groups", {}).get("report", "")
        if not target:
            await ctx.send_group(
                ev["group_openid"], "举报通道暂未配置管理群，请联系管理员", msg_id=ev["event_id"]
            )
            return
        text = (
            f"📮 收到举报\n来源群：{ev['group_openid']}\n举报人：{ev['user_openid']}\n"
            f"内容：{content[2:].strip()[:300] or '（无具体内容）'}"
        )
        await ctx.send_group(target, text)
        await ctx.send_group(ev["group_openid"], "✅ 举报已转交管理员，感谢反馈", msg_id=ev["event_id"])
