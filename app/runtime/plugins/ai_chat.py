"""AI 对话插件：OpenAI 兼容接口（GLM/Z.ai/DeepSeek/OpenAI 均可），支持单聊流式输出。"""

import logging

import httpx
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import AiConfig, AiMessage
from app.runtime.context import InstanceContext
from app.runtime.plugins.base import Plugin

log = logging.getLogger("runtime.ai")


class AiChatPlugin(Plugin):
    name = "ai_chat"
    order = 30

    async def on_group_message(self, ctx: InstanceContext, ev: dict) -> None:
        cfg: AiConfig | None = ctx.configs.get("ai")
        if not cfg or not cfg.enabled or not ctx.feature_enabled("ai", ev["group_openid"]):
            return
        content = ev["content"]
        question = ""
        if content.startswith("<@") or "@" in content[:8]:
            # 去掉 @前缀（官方推送的群@消息 content 已去@，防御性处理）
            question = content.split(">", 1)[-1].strip() if ">" in content[:8] else content.strip()
        else:
            if cfg.trigger_mode != "keyword":
                return
            for kw in cfg.trigger_keywords.split(","):
                kw = kw.strip()
                if kw and content.startswith(kw):
                    question = content[len(kw):].strip()
                    break
        if not question:
            return
        if not cfg.api_key_enc:
            await ctx.send_group(
                ev["group_openid"],
                "「AI 对话」还没有配置 API Key，请管理员在平台「AI 对话」页填写",
                msg_id=ev["event_id"],
            )
            return
        await self._answer(
            ctx, ev["group_openid"], ev["user_openid"], ev["event_id"],
            question, group=True, group_openid=ev["group_openid"],
        )

    async def on_c2c_message(self, ctx: InstanceContext, ev: dict) -> None:
        cfg: AiConfig | None = ctx.configs.get("ai")
        if not cfg or not cfg.enabled:
            return
        content = ev["content"]
        if not content or content.startswith("/"):
            return
        if not cfg.api_key_enc:
            await ctx.send_c2c(
                ev["user_openid"],
                "「AI 对话」还没有配置 API Key，请管理员在平台「AI 对话」页填写",
                msg_id=ev["event_id"],
            )
            return
        await self._answer(ctx, ev["user_openid"], ev["user_openid"], ev["event_id"], content, group=False)

    async def _answer(
        self, ctx: InstanceContext, target: str, user_openid: str,
        msg_id: str, question: str, group: bool, group_openid: str = "",
    ) -> None:
        cfg: AiConfig = ctx.configs["ai"]
        if not await ctx.ai_quota_ok(user_openid, cfg.daily_limit_per_user):
            await ctx.log("warn", f"用户 {user_openid} 今日 AI 次数已达上限 {cfg.daily_limit_per_user}")
            await self._reply(ctx, target, group, msg_id,
                              f"今天的 AI 次数用完啦（每人每日 {cfg.daily_limit_per_user} 次），明天再来吧")
            return
        from app.security import decrypt_secret

        api_key = decrypt_secret(cfg.api_key_enc)
        if not api_key:
            await self._reply(ctx, target, group, msg_id,
                              "「AI 对话」的 API Key 读取失败，请联系管理员在平台重新保存")
            return

        group_row = (ctx.configs.get("ai_group_personas") or {}).get(group_openid)
        persona = resolve_persona(cfg, group_row, "chat")
        history = await self._history(ctx, user_openid, cfg.max_history)
        system = _build_system(
            cfg, extra=cfg.system_prompt or "你是一个友好的群聊助手，回答简洁准确。", persona=persona
        )
        # 实时上下文：当前时间 + 按意图抓取的天气/汇率等，让回答基于当下而不是训练数据
        from app.runtime import realtime

        blocks = await realtime.gather(question)
        system = system + "\n" + realtime.HONESTY_LINE
        if blocks:
            system += "\n\n" + "\n".join(blocks)
        messages = [{"role": "system", "content": system}]
        messages += history
        messages.append({"role": "user", "content": question})

        await ctx.ai_quota_incr(user_openid)
        reply, err = await self._call_llm(
            cfg.api_base, api_key, cfg.model, messages, api_key_stream=False
        )
        if err:
            reply = f"⚠️ AI 调用失败：{err}\n请管理员检查「AI 对话」页的 API Key 和模型名称"
        elif not reply:
            reply = "（AI 没有返回内容，稍后再试试）"
        reply = _filter_output(reply)
        await self._save_history(ctx, user_openid, question, reply, cfg.max_history)
        await self._reply(ctx, target, group, msg_id, reply)

    async def _reply(
        self, ctx: InstanceContext, target: str, group: bool, msg_id: str, text: str
    ) -> None:
        if group:
            await ctx.send_group(target, text, msg_id=msg_id)
        else:
            await ctx.send_c2c(target, text, msg_id=msg_id)

    async def _history(self, ctx: InstanceContext, user_openid: str, limit: int) -> list[dict]:
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(AiMessage)
                    .where(
                        AiMessage.bot_instance_id == ctx.instance_id,
                        AiMessage.user_openid == user_openid,
                    )
                    .order_by(AiMessage.id.desc())
                    .limit(limit)
                )
            ).scalars().all()
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]

    async def _save_history(
        self, ctx: InstanceContext, user_openid: str, question: str, reply: str, limit: int
    ) -> None:
        async with SessionLocal() as db:
            # 控制单用户上下文总量
            rows = (
                await db.execute(
                    select(AiMessage.id)
                    .where(
                        AiMessage.bot_instance_id == ctx.instance_id,
                        AiMessage.user_openid == user_openid,
                    )
                    .order_by(AiMessage.id.desc())
                    .offset(max(0, limit * 2 - 2))
                )
            ).scalars().all()
            if rows:
                await db.execute(delete(AiMessage).where(AiMessage.id.in_(rows)))
            db.add(
                AiMessage(
                    bot_instance_id=ctx.instance_id,
                    user_openid=user_openid,
                    role="user",
                    content=question[:2000],
                )
            )
            db.add(
                AiMessage(
                    bot_instance_id=ctx.instance_id,
                    user_openid=user_openid,
                    role="assistant",
                    content=reply[:2000],
                )
            )
            await db.commit()

    async def _call_llm(
        self, api_base: str, api_key: str, model: str, messages: list[dict], api_key_stream: bool
    ) -> tuple[str, str | None]:
        url = api_base.rstrip("/") + "/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": messages, "stream": False},
                )
                resp.raise_for_status()
                data = resp.json()
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", ""), None
        except httpx.HTTPStatusError as exc:
            brief = ""
            try:
                brief = exc.response.json().get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                pass
            brief = brief or f"接口返回 HTTP {exc.response.status_code}"
            log.error("LLM 调用失败: %s", brief)
            return "", brief[:160]
        except Exception as exc:  # noqa: BLE001
            log.error("LLM 调用失败: %s", exc)
            return "", str(exc)[:160]


_BLOCKLIST_OUTPUT = ["色情", "赌博", "毒品"]


def _persona_text(name: str, desc: str) -> str:
    parts = []
    if name:
        parts.append(f"你的名字是「{name}」。")
    if desc:
        parts.append(desc)
    return "".join(parts)


def resolve_persona(cfg, group_row, kind: str) -> str:
    """解析人设：按群字段非空优先，否则全局；kind = chat / audit。

    全局字段名：对话 = persona_*，审核 = audit_persona_*（历史命名）。
    """
    if kind == "chat":
        gname = getattr(group_row, "chat_persona_name", "") if group_row else ""
        gdesc = getattr(group_row, "chat_persona_desc", "") if group_row else ""
        name = gname or (getattr(cfg, "persona_name", "") if cfg else "")
        desc = gdesc or (getattr(cfg, "persona_desc", "") if cfg else "")
    else:
        gname = getattr(group_row, "audit_persona_name", "") if group_row else ""
        gdesc = getattr(group_row, "audit_persona_desc", "") if group_row else ""
        name = gname or (getattr(cfg, "audit_persona_name", "") if cfg else "")
        desc = gdesc or (getattr(cfg, "audit_persona_desc", "") if cfg else "")
    return _persona_text(name, desc)


def _build_system(cfg, extra: str = "", persona: str = "") -> str:
    system = persona or "你是一个友好的群聊助手。"
    if extra:
        system += "\n" + extra
    if getattr(cfg, "group_rules_text", ""):
        system += "\n\n以下是本群的群规/常见问题资料，回答时优先依据这些内容：\n" + cfg.group_rules_text[:4000]
    return system


def _filter_output(text: str) -> str:
    """输出侧兜底过滤：命中平台词表则拒答。"""
    for word in _BLOCKLIST_OUTPUT:
        if word in text:
            return "（回答内容涉及不适宜话题，已被平台过滤）"
    return text
