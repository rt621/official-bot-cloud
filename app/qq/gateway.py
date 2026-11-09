"""QQ 网关 WebSocket 长连接客户端。

协议（依据官方文档 dev-prepare/event-emit/websocket.html）：
- Op 10 Hello: 下发心跳周期(ms)
- Op 2 Identify: token="QQBot {AccessToken}" + intents
- Op 0 Dispatch: 事件，带 t(类型) s(序号) d(数据)
- Op 1 Heartbeat: d=最近序号；Op 11 HeartbeatACK
- Op 6 Resume: 断线恢复；Op 7 Reconnect 服务端要求重连
- 4014 = intent 无权限（需开放平台申请）；4009 = 可恢复
"""

import asyncio
import contextlib
import json
import logging
from typing import Any, Awaitable, Callable

import websockets

log = logging.getLogger("qq.gateway")

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# 订阅的 intents：群/C2C 消息与好友 + 群成员变动 + 互动回调
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_GROUP_MEMBER = 1 << 24
INTENT_INTERACTION = 1 << 26
DEFAULT_INTENTS = INTENT_GROUP_AND_C2C | INTENT_GROUP_MEMBER | INTENT_INTERACTION


class GatewayError(Exception):
    def __init__(self, message: str, close_code: int | None = None):
        super().__init__(message)
        self.close_code = close_code


class GatewayConnection:
    """单实例长连接。断线自动重连；resume 失败则重新 identify。"""

    def __init__(
        self,
        api,  # ApiClient
        intents: int = DEFAULT_INTENTS,
        on_event: Callable[[str, dict], Awaitable[None]] | None = None,
        on_status: Callable[[str, str], Awaitable[None]] | None = None,
        max_reconnect_delay: int = 60,
    ):
        self.api = api
        self.intents = intents
        self.on_event = on_event
        self.on_status = on_status
        self.max_reconnect_delay = max_reconnect_delay
        self._session_id: str = ""
        self._last_seq: int = 0
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def _status(self, status: str, detail: str = "") -> None:
        if self.on_status:
            with contextlib.suppress(Exception):
                await self.on_status(status, detail)

    async def run(self) -> None:
        """主循环：直到 stop()。"""
        delay = 3
        while not self._stop.is_set():
            try:
                await self._run_once()
                if self._stop.is_set():
                    break
                raise GatewayError("connection closed")
            except GatewayError as exc:
                if self._stop.is_set():
                    break
                if exc.close_code == 4014:
                    await self._status(
                        "error", "事件订阅权限未申请（intent 无权限）：请到开放平台为该机器人申请对应事件权限后重试"
                    )
                    self._stop.set()
                    break
                await self._status("connecting", f"连接断开，{delay}s 后重连：{exc}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                await self._status("connecting", f"连接异常，{delay}s 后重连：{exc}")
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.max_reconnect_delay)

    async def _run_once(self) -> None:
        url = await self.api.gateway()
        await self._status("connecting", "连接网关…")
        async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
            hello = json.loads(await ws.recv())
            if hello.get("op") != OP_HELLO:
                raise GatewayError(f"握手异常: {hello}")
            heartbeat_interval = hello.get("d", {}).get("heartbeat_interval", 45000) / 1000

            if self._session_id and self._last_seq:
                await ws.send(
                    json.dumps(
                        {
                            "op": OP_RESUME,
                            "d": {
                                "token": f"QQBot {await self.api.tokens.get()}",
                                "session_id": self._session_id,
                                "seq": self._last_seq,
                            },
                        }
                    )
                )
            else:
                await ws.send(
                    json.dumps(
                        {
                            "op": OP_IDENTIFY,
                            "d": {
                                "token": f"QQBot {await self.api.tokens.get()}",
                                "intents": self.intents,
                                "shard": [0, 1],
                            },
                        }
                    )
                )

            await self._status("online", "")
            delay = 3

            async def heartbeat() -> None:
                while True:
                    await asyncio.sleep(heartbeat_interval)
                    with contextlib.suppress(Exception):
                        await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._last_seq}))

            hb_task = asyncio.create_task(heartbeat())
            try:
                async for raw in ws:
                    payload = json.loads(raw)
                    op = payload.get("op")
                    if op == OP_DISPATCH:
                        self._last_seq = payload.get("s", self._last_seq)
                        event_type = payload.get("t") or ""
                        data = payload.get("d") or {}
                        if event_type == "READY":
                            self._session_id = data.get("session_id", "")
                            await self._status("online", f"已连接（{data.get('user', {}).get('username', '')}）")
                        elif event_type == "RESUMED":
                            await self._status("online", "会话已恢复")
                        elif self.on_event and event_type:
                            await self.on_event(event_type, data)
                    elif op == OP_HEARTBEAT_ACK:
                        pass
                    elif op == OP_RECONNECT:
                        raise GatewayError("服务端要求重连")
            finally:
                hb_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await hb_task
