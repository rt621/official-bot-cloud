"""规则引擎挂载插件：群消息与进群事件进入自动化规则评估。"""

from app.runtime import rules_engine
from app.runtime.context import InstanceContext
from app.runtime.plugins.base import Plugin


class RulesPlugin(Plugin):
    name = "rules"
    order = 40

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        await rules_engine.run_rules(ctx, ev)

    async def on_group_member_add(self, ctx: InstanceContext, ev: dict) -> None:
        await rules_engine.run_rules(
            ctx,
            {
                "event_id": ev.get("event_id", ""),
                "group_openid": ev.get("group_openid", ""),
                "user_openid": ev.get("user_openid", ""),
                "content": "",
                "member_join": True,
            },
        )
