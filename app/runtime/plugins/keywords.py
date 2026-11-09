"""关键词自动回复插件。"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import KeywordRule
from app.runtime.context import InstanceContext
from app.runtime.plugins.base import Plugin


class KeywordPlugin(Plugin):
    name = "keywords"
    order = 20

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        if not ctx.feature_enabled("keywords", ev["group_openid"]):
            return
        await self._handle(ctx, ev["group_openid"], ev["user_openid"], ev["event_id"], ev["content"], scope="group")

    async def on_c2c_message(self, ctx: InstanceContext, ev: dict) -> None:
        if not ctx.feature_enabled("keywords", "*"):
            return
        await self._handle(ctx, ev["user_openid"], ev["user_openid"], ev["event_id"], ev["content"], scope="c2c")

    async def _handle(
        self, ctx: InstanceContext, target_openid: str, user_openid: str,
        msg_id: str, content: str, scope: str,
    ) -> None:
        if not content or content.startswith("/"):
            return
        group = target_openid if scope == "group" else ""
        async with SessionLocal() as db:
            rules = (
                await db.execute(
                    select(KeywordRule).where(
                        KeywordRule.bot_instance_id == ctx.instance_id,
                        KeywordRule.enabled.is_(True),
                    )
                )
            ).scalars().all()
        # 指定群规则优先，'*' 规则兜底
        rules = [r for r in rules if r.group_openid == group] + [
            r for r in rules if r.group_openid == "*"
        ]
        if not rules:
            return
        for rule in rules:
            if not _match(rule.pattern, content):
                continue
            if rule.reply_type == "image":
                media = await ctx.api.upload_group_media(
                    target_openid, 1, rule.reply_content
                ) if scope == "group" else await ctx.api.upload_c2c_media(
                    target_openid, 1, rule.reply_content
                )
                if media and media.get("file_info"):
                    if scope == "group":
                        await ctx.send_group(
                            target_openid, msg_type=7, media=media, msg_id=msg_id
                        )
                    else:
                        await ctx.send_c2c(
                            target_openid, msg_type=7, media=media, msg_id=msg_id
                        )
            else:
                reply = rule.reply_content
                if "{at}" in reply and scope == "group":
                    reply = reply.replace("{at}", f"<qqbot-at-user id=\"{user_openid}\" />")
                if scope == "group":
                    await ctx.send_group(target_openid, reply, msg_id=msg_id)
                else:
                    await ctx.send_c2c(target_openid, reply, msg_id=msg_id)
            return  # 只回第一条命中的规则


def _match(pattern: str, content: str) -> bool:
    """模式支持 | 分隔多关键词，任一命中即匹配（子串包含）。"""
    for kw in pattern.split("|"):
        kw = kw.strip()
        if kw and kw in content:
            return True
    return False
