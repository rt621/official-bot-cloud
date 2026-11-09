"""基础指令插件：/帮助 /状态 /签到。"""

import datetime as dt

from sqlalchemy import select

from app.database import SessionLocal
from app.models import SigninConfig, SigninRecord
from app.runtime.context import InstanceContext, today
from app.runtime.plugins.base import Plugin

HELP_TEXT = (
    "📖 机器人指令\n"
    "/帮助 - 查看指令\n"
    "/状态 - 机器人运行状态\n"
    "/签到 - 每日签到\n"
    "🛡️ 管理员指令（群主在「群管自动化」页加名单后可用）\n"
    "/禁言 @某人 分钟 - 禁言\n"
    "/解禁 @某人 - 解除禁言\n"
    "/踢人 @某人 - 踢出本群\n"
    "/拉黑 @某人 - 加入黑名单\n"
    "/禁言列表 - 查看禁言中的成员\n"
    "/管理帮助 - 管理指令详解"
)


async def _deny(ctx: InstanceContext, ev: dict, name: str) -> None:
    """指令对应的功能被关闭时，给用户明确反馈而不是静默忽略。"""
    await ctx.send_group(
        ev["group_openid"], f"「{name}」功能未开启（可在管理面板开启）", msg_id=ev["event_id"]
    )


class CommandsPlugin(Plugin):
    name = "commands"
    order = 10

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        content = ev["content"]
        if not content.startswith("/"):
            return
        cmd, *_ = content[1:].split()
        cmd = cmd.lower()
        if cmd == "帮助":
            await ctx.send_group(ev["group_openid"], HELP_TEXT, msg_id=ev["event_id"])
        elif cmd == "状态":
            await self._status(ctx, ev)
        elif cmd == "签到":
            await self._signin(ctx, ev)

    async def on_c2c_message(self, ctx: InstanceContext, ev: dict) -> None:
        if ev["content"] == "/帮助":
            await ctx.send_c2c(ev["user_openid"], HELP_TEXT, msg_id=ev["event_id"])

    async def _status(self, ctx: InstanceContext, ev: dict) -> None:
        inst = ctx.configs.get("instance_name", "")
        text = (
            f"🤖 机器人运行正常\n"
            f"实例：{inst or ctx.appid}\n"
            f"当前群 group_openid：{ev['group_openid']}\n"
            f"你的 user_openid：{ev['user_openid']}\n"
            f"（配置群目标/管理员名单时需要这些标识）\n"
            f"当前时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        await ctx.send_group(ev["group_openid"], text, msg_id=ev["event_id"])

    async def _signin(self, ctx: InstanceContext, ev: dict) -> None:
        cfg: SigninConfig | None = ctx.configs.get("signin")
        if not cfg or not cfg.enabled or not ctx.feature_enabled("signin", ev["group_openid"]):
            await _deny(ctx, ev, "签到")
            return
        day = today()
        async with SessionLocal() as db:
            existing = (
                await db.execute(
                    select(SigninRecord).where(
                        SigninRecord.bot_instance_id == ctx.instance_id,
                        SigninRecord.day == day,
                        SigninRecord.user_openid == ev["user_openid"],
                    )
                )
            ).scalar_one_or_none()
            if existing:
                text = f"{ev['user_openid']} 今天已经签到过啦"
            else:
                yesterday = (
                    await db.execute(
                        select(SigninRecord)
                        .where(
                            SigninRecord.bot_instance_id == ctx.instance_id,
                            SigninRecord.user_openid == ev["user_openid"],
                        )
                        .order_by(SigninRecord.day.desc())
                        .limit(1)
                    )
                ).scalars().first()
                streak = 1
                if yesterday and yesterday.day == _yesterday():
                    streak = yesterday.streak + 1
                db.add(
                    SigninRecord(
                        bot_instance_id=ctx.instance_id,
                        day=day,
                        user_openid=ev["user_openid"],
                        user_name=ev["user_openid"],
                        streak=streak,
                    )
                )
                text = cfg.reward_template.format(days=streak)
            await db.commit()
        await ctx.send_group(ev["group_openid"], text, msg_id=ev["event_id"])


def _yesterday() -> str:
    return (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
