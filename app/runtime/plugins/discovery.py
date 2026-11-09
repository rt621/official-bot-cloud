"""群自动发现：记录实例见到过的群 openid（落库 + 日志），并尽量拉取群名称。"""

import asyncio

from sqlalchemy import select

from app.database import SessionLocal
from app.models import KnownGroup
from app.runtime.context import InstanceContext
from app.runtime.plugins.base import Plugin


class GroupDiscoveryPlugin(Plugin):
    name = "group_discovery"
    order = 80

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        await self._mark(ctx, ev.get("group_openid", ""))

    async def on_group_member_add(self, ctx: InstanceContext, ev: dict) -> None:
        await self._mark(ctx, ev.get("group_openid", ""))

    async def on_group_member_remove(self, ctx: InstanceContext, ev: dict) -> None:
        await self._mark(ctx, ev.get("group_openid", ""))

    async def on_group_add_robot(self, ctx: InstanceContext, ev: dict) -> None:
        group = ev.get("group_openid", "")
        await self._mark(ctx, group)
        await ctx.log("info", f"机器人被加入群 {group}（感谢添加，发送 /帮助 查看指令）")

    async def _mark(self, ctx: InstanceContext, group: str) -> None:
        if not group:
            return
        is_new = group not in ctx.known_groups
        ctx.known_groups.add(group)
        need_name = False
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(KnownGroup).where(
                        KnownGroup.bot_instance_id == ctx.instance_id,
                        KnownGroup.group_openid == group,
                    )
                )
            ).scalar_one_or_none()
            if not row:
                db.add(KnownGroup(bot_instance_id=ctx.instance_id, group_openid=group))
                await db.commit()
                need_name = True
            elif not row.group_name:
                need_name = True
        if is_new:
            await ctx.log(
                "info",
                f"发现新群 group_openid={group} —— 关键词/监控/定时/审批/自检配置都会用到这个标识",
            )
        if need_name:
            asyncio.create_task(self._fetch_name(ctx, group))

    async def _fetch_name(self, ctx: InstanceContext, group: str) -> None:
        """拉取群名称（官方 group_info 接口；无权限时静默跳过，页面回退显示缩写）。"""
        await asyncio.sleep(1)  # 避开事件洪峰
        try:
            info = await ctx.api.group_info(group)
        except Exception:  # noqa: BLE001  # 11253 等无权限情况直接放弃
            return
        name = info.get("group_name") or info.get("name") or ""
        if not name:
            return
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(KnownGroup).where(
                        KnownGroup.bot_instance_id == ctx.instance_id,
                        KnownGroup.group_openid == group,
                    )
                )
            ).scalar_one_or_none()
            if row:
                row.group_name = str(name)[:120]
                await db.commit()
        await ctx.log("info", f"群 {group} 名称：{name}")
