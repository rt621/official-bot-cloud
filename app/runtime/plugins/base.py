"""插件基类与事件分发。"""

import logging
import re

from app.runtime.context import InstanceContext

log = logging.getLogger("runtime.plugin")

_MENTION_RE = re.compile(r"^@(?P<tok>[^\s@]{0,64})(?P<ws>\s*)(?P<rest>.*)$", re.DOTALL)
_TAG_RE = re.compile(r"^<@(?P<id>[^>]{1,64})>\s*(?P<rest>.*)$", re.DOTALL)
_ZWSP_RE = re.compile("[\u200b\u200c\u200d\ufeff]")


class Plugin:
    """插件基类：覆写需要的事件钩子即可。"""

    name = "base"

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        """群消息（@ 或全量，取决于事件类型）。ev 含 author/content/group_openid/id。"""

    async def on_c2c_message(self, ctx: InstanceContext, ev: dict) -> None:
        """单聊消息。"""

    async def on_group_member_add(self, ctx: InstanceContext, ev: dict) -> None:
        """进群事件。"""

    async def on_group_member_remove(self, ctx: InstanceContext, ev: dict) -> None:
        """退群事件。"""

    async def on_group_add_robot(self, ctx: InstanceContext, ev: dict) -> None:
        """机器人被添加进群。"""

    async def on_join_request(self, ctx: InstanceContext, ev: dict) -> None:
        """加群申请。"""

    async def on_interaction(self, ctx: InstanceContext, ev: dict) -> None:
        """按钮点击等互动回调。"""


class Dispatcher:
    def __init__(self, plugins: list[Plugin]):
        self.plugins = plugins

    async def dispatch(self, event_type: str, ctx: InstanceContext, data: dict) -> None:
        try:
            if event_type in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"):
                ev = _group_event(data)
                ev["content"] = normalize_content(
                    ev["content"], getattr(ctx, "bot_name", ""), getattr(ctx, "bot_openid", "")
                )
                for plugin in self.plugins:
                    await plugin.on_group_message(ctx, ev)
            elif event_type == "C2C_MESSAGE_CREATE":
                ev = _c2c_event(data)
                ev["content"] = normalize_content(
                    ev["content"], getattr(ctx, "bot_name", ""), getattr(ctx, "bot_openid", "")
                )
                for plugin in self.plugins:
                    await plugin.on_c2c_message(ctx, ev)
            elif event_type == "GROUP_MEMBER_ADD":
                ev = _member_event(data)
                for plugin in self.plugins:
                    await plugin.on_group_member_add(ctx, ev)
            elif event_type == "GROUP_MEMBER_REMOVE":
                ev = _member_event(data)
                for plugin in self.plugins:
                    await plugin.on_group_member_remove(ctx, ev)
            elif event_type == "GROUP_ADD_ROBOT":
                for plugin in self.plugins:
                    await plugin.on_group_add_robot(ctx, data)
            elif event_type == "GROUP_JOIN_REQUEST":
                for plugin in self.plugins:
                    await plugin.on_join_request(ctx, data)
            elif event_type == "INTERACTION_CREATE":
                for plugin in self.plugins:
                    await plugin.on_interaction(ctx, data)
        except Exception:  # noqa: BLE001
            log.exception("插件处理事件 %s 异常", event_type)
            await ctx.log("error", f"插件处理事件 {event_type} 出错，详见服务端日志")


def _author_id(data: dict) -> str:
    author = data.get("author") or {}
    return author.get("id") or author.get("user_openid") or data.get("user_id") or ""


def normalize_content(content: str, bot_name: str = "", bot_openid: str = "") -> str:
    """统一消息内容：剥掉 @机器人 前缀、全角斜杠转半角、去零宽字符与首尾空白。

    群"全量消息"模式下 @机器人 的原文会保留在 content 里，且格式是官方
    提及标记 `<@{bot_openid}>`（见 text-chain 文档），不剥掉会导致
    "<@bot> /帮助" 不匹配指令；也兼容纯文本 "@昵称" 形式。
    """
    if not content:
        return content
    content = _ZWSP_RE.sub("", content).strip()
    m = _TAG_RE.match(content)
    if m:
        rest = m.group("rest")
        id_hit = bool(bot_openid) and m.group("id").upper() == bot_openid.upper()
        cmd_hit = rest.lstrip().startswith(("/", "／"))
        if (id_hit or cmd_hit) and rest.strip():
            content = rest
    m = _MENTION_RE.match(content)
    if m:
        tok = m.group("tok")
        rest = m.group("rest")
        name_hit = bool(bot_name) and bot_name.lower() in tok.lower()
        cmd_hit = rest.lstrip().startswith(("/", "／"))
        if name_hit or cmd_hit:
            if rest.strip():
                content = rest  # "@机器人 /帮助" / "@机器人 群规是什么"
            elif name_hit and "/" in tok:
                content = "/" + tok.split("/", 1)[1]  # "@机器人/帮助" 连写
    if content.startswith("／"):
        content = "/" + content[1:]
    return content.strip()


def _group_event(data: dict) -> dict:
    return {
        "event_id": data.get("id", ""),
        "group_openid": data.get("group_openid", ""),
        "user_openid": _author_id(data),
        "user_name": (data.get("author") or {}).get("member_openid", "")
        or _author_id(data),
        "content": (data.get("content") or "").strip(),
        "attachments": data.get("attachments") or [],
        "raw": data,
    }


def _c2c_event(data: dict) -> dict:
    return {
        "event_id": data.get("id", ""),
        "user_openid": _author_id(data),
        "content": (data.get("content") or "").strip(),
        "attachments": data.get("attachments") or [],
        "raw": data,
    }


def _member_event(data: dict) -> dict:
    return {
        "event_id": data.get("id", ""),
        "group_openid": data.get("group_openid", ""),
        "user_openid": _author_id(data) or data.get("op_user_openid", ""),
        "raw": data,
    }
