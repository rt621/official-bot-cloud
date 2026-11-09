"""群管理指令插件：/禁言 /解禁 /踢人 /拉黑 /解除拉黑 /禁言列表 /我的ID。

安全：发送者必须在 GroupAdminConfig.admin_openids 名单内才能使用管理指令。
目标成员从消息里的 <@openid> 提及标记解析（全量消息模式真实格式）。
"""

import datetime as dt
import re

from app.runtime.context import InstanceContext
from app.runtime.plugins.base import Plugin

TAG_RE = re.compile(r"<@([A-Za-z0-9]{8,64})>")

HELP = (
    "🛠 管理指令（需平台授权管理员）\n"
    "/禁言 @某人 分钟\n"
    "/解禁 @某人\n"
    "/踢人 @某人 [拉黑]\n"
    "/拉黑 @某人\n"
    "/解除拉黑 @某人\n"
    "/禁言列表"
)


class AdminPlugin(Plugin):
    name = "admin"
    order = 90

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        content = ev["content"]
        if content == "/我的ID":
            await ctx.send_group(
                ev["group_openid"],
                f"你的 user_openid：\n{ev['user_openid']}\n（复制到平台「群管自动化」页的管理员名单即可授权）",
                msg_id=ev["event_id"],
            )
            return
        if not content.startswith("/"):
            return
        cmd, *rest = content[1:].split()
        if cmd not in ("禁言", "解禁", "踢人", "拉黑", "解除拉黑", "禁言列表", "管理帮助"):
            return

        cfg = ctx.configs.get("groupadmin")
        admins = _admins(cfg)
        group = ev["group_openid"]
        if ev["user_openid"] not in admins:
            await ctx.send_group(
                group,
                "⛔ 该指令需要平台管理员授权：请群主到平台「群管自动化」页，用 /我的ID 获取自己的 openid 加入名单。",
                msg_id=ev["event_id"],
            )
            return

        if cmd == "管理帮助":
            await ctx.send_group(group, HELP, msg_id=ev["event_id"])
            return

        if cmd == "禁言列表":
            await self._mute_list(ctx, ev)
            return

        targets = TAG_RE.findall(content)
        if not targets:
            await ctx.send_group(group, "请 @ 要操作的对象，例如：/禁言 @某人 10", msg_id=ev["event_id"])
            return

        try:
            if cmd == "禁言":
                minutes = 10
                for part in rest:
                    if part.isdigit() and 1 <= int(part) <= 43200:
                        minutes = int(part)
                        break
                await ctx.api.mute_members(
                    group,
                    [{"op": "add", "member_openid": t, "mute_expire_at": _expire(minutes)} for t in targets],
                )
                await ctx.send_group(group, f"🔇 已禁言 {len(targets)} 人，时长 {minutes} 分钟", msg_id=ev["event_id"])
            elif cmd == "解禁":
                await ctx.api.mute_members(
                    group, [{"op": "del", "member_openid": t} for t in targets]
                )
                await ctx.send_group(group, f"🔊 已解除 {len(targets)} 人的禁言", msg_id=ev["event_id"])
            elif cmd == "踢人":
                to_blacklist = "拉黑" in rest
                await ctx.api.remove_members(group, targets[:20], to_blacklist)
                await ctx.send_group(
                    group,
                    f"👢 已移除 {len(targets)} 人" + ("并加入黑名单" if to_blacklist else ""),
                    msg_id=ev["event_id"],
                )
            elif cmd in ("拉黑", "解除拉黑"):
                await ctx.api.group_blacklist_op(group, "add" if cmd == "拉黑" else "del", targets[:20])
                await ctx.send_group(
                    group, f"{'⛔ 已拉黑' if cmd == '拉黑' else '✅ 已移出黑名单'} {len(targets)} 人",
                    msg_id=ev["event_id"],
                )
        except Exception as exc:  # noqa: BLE001
            from app.qq.client import ApiError

            hint = ""
            if isinstance(exc, ApiError):
                if exc.kind == "no_permission":
                    hint = "（可能原因：机器人不是群管理员；或该接口为内邀白名单制，平台无权限）"
                hint += f" 错误码 {exc.code}"
            await ctx.send_group(group, f"❌ 操作失败：{exc}{hint}", msg_id=ev["event_id"])
            await ctx.log("error", f"管理指令 {cmd} 失败：{exc}")

    async def _mute_list(self, ctx: InstanceContext, ev: dict) -> None:
        group = ev["group_openid"]
        try:
            data = await ctx.api.group_mute_state(group)
        except Exception as exc:  # noqa: BLE001
            await ctx.send_group(group, f"❌ 查询失败：{exc}", msg_id=ev["event_id"])
            return
        members = data.get("members") or []
        if not members:
            await ctx.send_group(group, "当前没有成员被禁言", msg_id=ev["event_id"])
            return
        lines = [f"{m.get('member_openid', '?')}  到期：{_fmt_expire(m.get('mute_expire_at'))}" for m in members[:20]]
        await ctx.send_group(group, "🔇 当前禁言中：\n" + "\n".join(lines), msg_id=ev["event_id"])


def _admins(cfg) -> list[str]:
    if not cfg:
        return []
    return [s.strip() for s in (cfg.admin_openids or "").splitlines() if s.strip()]


def _expire(minutes: int) -> str:
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _fmt_expire(value) -> str:
    return str(value or "?").replace("T", " ").replace("+00:00", " UTC")
