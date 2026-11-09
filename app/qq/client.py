"""QQ 开放平台 v2 API 客户端：Access Token 管理 + 全部业务接口。

接口地址与限制依据官方文档（2026-10 核对）：
- 统一域名 https://api.bot.qq.com
- 鉴权头 Authorization: QQBot {access_token}
- Token 有效期 7200s，到期前 60s 过渡期
"""

import asyncio
import datetime as dt
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("qq.client")

TOKEN_URL = "https://api.bot.qq.com/app/getAppAccessToken"


class ApiError(Exception):
    """业务错误：按官方错误码分类。"""

    def __init__(self, code: int | str, message: str, http_status: int = 200):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.http_status = http_status

    @property
    def kind(self) -> str:
        """错误分类，供页面展示与限频退避。"""
        code = self.code
        try:
            code = int(code)
        except (TypeError, ValueError):
            return "unknown"
        if code == 100001 or 304045 <= code <= 304050 or code == 20028:
            return "rate_limited"
        if code in (11252, 11253, 11254, 11273, 11274, 40034105):
            return "no_permission"
        if code in (100007, 11265, 4915):
            return "banned"
        if 1100100 <= code <= 1100104 or code == 3300006:
            return "content_blocked"
        if code in (40064004,):
            return "recall_expired"
        return "api_error"


async def fetch_access_token(appid: str, client_secret: str) -> tuple[str, int]:
    """换取 AccessToken，返回 (token, expires_in秒)。"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            json={"appId": appid, "clientSecret": client_secret},
            headers={"Content-Type": "application/json"},
        )
        data = _parse_body(resp)
    token = data.get("accessToken") or data.get("access_token") or ""
    expires = data.get("expiresIn") or data.get("expires_in") or 7200
    if not token:
        raise ApiError(-1, "获取 AccessToken 失败：" + str(data)[:200])
    try:
        expires = int(expires)
    except (TypeError, ValueError):
        expires = 7200
    return token, expires


def _parse_body(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code // 100 != 2:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        code = body.get("code", resp.status_code)
        raise ApiError(code, str(body.get("message", resp.text[:200])), resp.status_code)
    if not resp.content:
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    if isinstance(data, dict) and data.get("code") not in (None, 0, "0"):
        # 业务错误可能在 HTTP 200 里返回
        raise ApiError(data["code"], str(data.get("message", "")), resp.status_code)
    return data


class TokenManager:
    """每实例一个；带提前刷新与并发去重。"""

    def __init__(self, appid: str, client_secret: str):
        self.appid = appid
        self.client_secret = client_secret
        self._token: str = ""
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        async with self._lock:
            # 提前 120 秒刷新，避开官方 60 秒过渡期边界
            if self._token and time.time() < self._expires_at - 120:
                return self._token
            token, expires = await fetch_access_token(self.appid, self.client_secret)
            self._token = token
            self._expires_at = time.time() + expires
            log.info("token refreshed for %s, expires in %ss", self.appid, expires)
            return self._token

    def invalidate(self) -> None:
        self._token = ""
        self._expires_at = 0


class ApiClient:
    """一个机器人实例的业务 API 客户端。"""

    def __init__(self, appid: str, client_secret: str):
        self.tokens = TokenManager(appid, client_secret)
        self.appid = appid
        self._http = httpx.AsyncClient(
            base_url="https://api.bot.qq.com", timeout=20
        )
        self._msg_seq: dict[str, int] = {}
        self._gateway_url: str = ""
        self._gateway_cached_at: float = 0

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = await self.tokens.get()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"QQBot {token}"
        resp = await self._http.request(method, path, headers=headers, **kwargs)
        return _parse_body(resp)

    # ---------- 消息 ----------

    def _next_seq(self, msg_id: str) -> int:
        self._msg_seq[msg_id] = self._msg_seq.get(msg_id, 0) + 1
        return self._msg_seq[msg_id]

    async def send_group(
        self,
        group_openid: str,
        msg_type: int = 0,
        content: str = "",
        media: dict | None = None,
        keyboard: dict | None = None,
        msg_id: str = "",
        event_id: str = "",
    ) -> dict:
        """发群消息。msg_id 非空=被动回复（5分钟窗口内最多5次），空=主动消息。"""
        body: dict[str, Any] = {"msg_type": msg_type, "msg_seq": self._next_seq(msg_id or "proactive")}
        if content:
            body["content"] = content
        if media:
            body["media"] = media
        if keyboard:
            body["keyboard"] = keyboard
        if msg_id:
            body["msg_id"] = msg_id
        if event_id:
            body["event_id"] = event_id
        return await self._request(
            "POST", f"/v2/groups/{group_openid}/messages", json=body
        )

    async def send_c2c(
        self,
        user_openid: str,
        msg_type: int = 0,
        content: str = "",
        media: dict | None = None,
        keyboard: dict | None = None,
        msg_id: str = "",
        event_id: str = "",
    ) -> dict:
        body: dict[str, Any] = {"msg_type": msg_type, "msg_seq": self._next_seq(msg_id or "proactive")}
        if content:
            body["content"] = content
        if media:
            body["media"] = media
        if keyboard:
            body["keyboard"] = keyboard
        if msg_id:
            body["msg_id"] = msg_id
        if event_id:
            body["event_id"] = event_id
        return await self._request(
            "POST", f"/v2/users/{user_openid}/messages", json=body
        )

    async def send_c2c_stream_start(
        self, user_openid: str, content: str, msg_id: str = "", index: int = 0
    ) -> dict:
        """单聊流式输出首片，返回含 stream_msg_id。"""
        body: dict[str, Any] = {
            "msg_type": 0,
            "content": content,
            "input_state": 1,
            "index": index,
            "msg_seq": self._next_seq(msg_id or "proactive"),
        }
        if msg_id:
            body["msg_id"] = msg_id
        return await self._request(
            "POST", f"/v2/users/{user_openid}/stream_messages", json=body
        )

    async def send_c2c_stream_chunk(
        self,
        user_openid: str,
        stream_msg_id: str,
        content: str,
        index: int,
        finish: bool = False,
    ) -> dict:
        body = {
            "msg_type": 0,
            "content": content,
            "stream_msg_id": stream_msg_id,
            "index": index,
            "input_mode": "append",
            "input_state": 10 if finish else 1,
        }
        return await self._request(
            "POST", f"/v2/users/{user_openid}/stream_messages", json=body
        )

    async def recall_group(self, group_openid: str, message_id: str) -> dict:
        return await self._request(
            "DELETE", f"/v2/groups/{group_openid}/messages/{message_id}"
        )

    async def recall_c2c(self, user_openid: str, message_id: str) -> dict:
        return await self._request(
            "DELETE", f"/v2/users/{user_openid}/messages/{message_id}"
        )

    # ---------- 富媒体 ----------

    async def upload_group_media(
        self, group_openid: str, file_type: int, url: str, srv_send_msg: bool = False
    ) -> dict:
        """URL 方式上传，返回 file_info。file_type: 1图/2视频/3语音/4文件。"""
        return await self._request(
            "POST",
            f"/v2/groups/{group_openid}/files",
            json={
                "file_type": file_type,
                "url": url,
                "srv_send_msg": srv_send_msg,
            },
        )

    async def upload_c2c_media(
        self, user_openid: str, file_type: int, url: str, srv_send_msg: bool = False
    ) -> dict:
        return await self._request(
            "POST",
            f"/v2/users/{user_openid}/files",
            json={
                "file_type": file_type,
                "url": url,
                "srv_send_msg": srv_send_msg,
            },
        )

    # ---------- 群管理 ----------

    async def group_info(self, group_openid: str) -> dict:
        return await self._request("GET", f"/v2/groups/{group_openid}/info")

    async def group_bot_state(self, group_openid: str) -> dict:
        """机器人群内状态：是否管理员、消息范围 all/only_mention、主动推送开关等。"""
        return await self._request("GET", f"/v2/groups/{group_openid}/bot_state")

    async def group_mute_state(self, group_openid: str) -> dict:
        """查询群禁言状态：global_rule（全员禁言配置）+ members（禁言中成员及到期）。"""
        return await self._request(
            "GET", f"/v2/groups/{group_openid}/restrict_chat_setting"
        )

    async def mute_members(
        self, group_openid: str, members: list[dict]
    ) -> dict:
        """成员级禁言。members: [{op: add/update/del, member_openid, mute_expire_at(RFC3339)}]"""
        return await self._request(
            "POST",
            f"/v2/groups/{group_openid}/restrict_chat_setting",
            json={"members": members},
        )

    async def mute_member_for(
        self, group_openid: str, member_openid: str, minutes: int
    ) -> dict:
        expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
        return await self.mute_members(
            group_openid,
            [
                {
                    "op": "add",
                    "member_openid": member_openid,
                    "mute_expire_at": expire.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                }
            ],
        )

    async def unmute_member(self, group_openid: str, member_openid: str) -> dict:
        return await self.mute_members(
            group_openid, [{"op": "del", "member_openid": member_openid}]
        )

    async def remove_members(
        self, group_openid: str, member_openids: list[str], add_to_blacklist: bool = False
    ) -> dict:
        """批量移除群成员（官方标注内邀白名单）。"""
        body: dict[str, Any] = {"member_openids": member_openids[:20]}
        if add_to_blacklist:
            body["add_to_member_blacklist"] = True
        return await self._request(
            "POST", f"/v2/groups/{group_openid}/batch_remove_members", json=body
        )

    async def group_blacklist(self, group_openid: str, limit: int = 100, cursor: str = "") -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET", f"/v2/groups/{group_openid}/member_blacklist", params=params
        )

    async def group_blacklist_op(
        self, group_openid: str, op: str, member_openids: list[str]
    ) -> dict:
        return await self._request(
            "POST",
            f"/v2/groups/{group_openid}/member_blacklist",
            json={"op": op, "member_openids": member_openids[:20]},
        )

    async def join_requests(self, group_openid: str, limit: int = 20, cursor: str = "") -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET", f"/v2/groups/{group_openid}/join_request_list", params=params
        )

    async def approve_join_request(
        self,
        group_openid: str,
        member_openid: str,
        op: str = "approve",
        reject_reason: str = "",
        add_to_blacklist: bool = False,
    ) -> dict:
        body: dict[str, Any] = {"op": op}
        if op == "decline":
            if reject_reason:
                body["reject_reason"] = reject_reason
            if add_to_blacklist:
                body["add_to_member_blacklist"] = True
        return await self._request(
            "POST",
            f"/v2/groups/{group_openid}/approval_join_request/{member_openid}",
            json=body,
        )

    # ---------- 群成员（内邀白名单） ----------

    async def group_members(self, group_openid: str, limit: int = 30, cursor: str = "") -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET", f"/v2/groups/{group_openid}/members", params=params
        )

    # ---------- 入群自动审批策略 ----------

    async def join_strategies(self, limit: int = 20, cursor: str = "") -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET", "/v2/groups/join_approval_strategy", params=params
        )

    async def create_join_strategy(
        self,
        group_openids: list[str] | None = None,
        group_ids: list[str] | None = None,
        is_enable: str = "on",
        remark: str = "",
        expire_at: str = "",
    ) -> dict:
        body: dict[str, Any] = {"is_enable": is_enable}
        if group_openids:
            body["group_openids"] = group_openids[:100]
        elif group_ids:
            body["group_ids"] = group_ids[:100]
        if remark:
            body["remark"] = remark[:255]
        if expire_at:
            body["expire_at"] = expire_at
        return await self._request(
            "POST", "/v2/groups/join_approval_strategy", json=body
        )

    async def update_join_strategy(
        self,
        strategy_id: str,
        is_enable: str | None = None,
        remark: str | None = None,
        expire_at: str | None = None,
        add_group_openids: list[str] | None = None,
        del_group_openids: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if is_enable is not None:
            body["is_enable"] = is_enable
        if remark is not None:
            body["remark"] = remark[:255]
        if expire_at:
            body["expire_at"] = expire_at
        if add_group_openids or del_group_openids:
            action: dict[str, Any] = {"op": "add" if add_group_openids else "del"}
            action["group_openids"] = (add_group_openids or del_group_openids or [])[:100]
            body["group_action"] = action
        return await self._request(
            "PATCH", f"/v2/groups/join_approval_strategy/{strategy_id}", json=body
        )

    async def delete_join_strategy(self, strategy_id: str) -> dict:
        return await self._request(
            "DELETE", f"/v2/groups/join_approval_strategy/{strategy_id}"
        )

    async def execute_join_strategy(self, strategy_id: str) -> dict:
        return await self._request(
            "POST", f"/v2/groups/join_approval_strategy/{strategy_id}/execute"
        )

    async def join_strategy_whitelist(
        self, strategy_id: str, op: str, qq_numbers: list[str]
    ) -> dict:
        return await self._request(
            "POST",
            f"/v2/groups/join_approval_strategy/{strategy_id}/whitelist_users",
            json={"op": op, "whitelist_users": qq_numbers[:10000]},
        )

    # ---------- 网关 / 自身 ----------

    async def gateway(self) -> str:
        # 官方限制 2 QPM，必须缓存
        if self._gateway_url and time.time() - self._gateway_cached_at < 600:
            return self._gateway_url
        data = await self._request("GET", "/gateway")
        self._gateway_url = data.get("url", "")
        self._gateway_cached_at = time.time()
        return self._gateway_url

    async def me(self) -> dict:
        return await self._request("GET", "/users/@me")

    # ---------- 互动 ----------

    async def ack_interaction(self, interaction_id: str, code: int = 0) -> dict:
        return await self._request(
            "PUT", f"/interactions/{interaction_id}", json={"code": code}
        )

    # ---------- 菜单 ----------

    async def put_menu(self, menu: dict) -> dict:
        """整体覆盖单聊自定义菜单。menu 形如 {"items": [...]}，返回 {version}。"""
        return await self._request("PUT", "/v2/menu", json={"menu": menu})

    async def get_menu(self) -> dict:
        return await self._request("GET", "/v2/menu")

    # ---------- 指令面板 ----------

    async def list_panels(self, scope: str, limit: int = 20, cursor: str = "") -> dict:
        params: dict[str, Any] = {"scope": scope, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/v2/panels", params=params)

    async def create_panel(
        self,
        scope: str,
        panel: dict,
        target_type: str = "all",
        user_openids: list[str] | None = None,
        group_openids: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "scope": scope,
            "target_type": target_type if scope in ("c2c", "group") else "all",
            "panel": panel,
        }
        if body["target_type"] == "specific":
            if user_openids:
                body["user_openids"] = user_openids[:20]
            if group_openids:
                body["group_openids"] = group_openids[:20]
        return await self._request("POST", "/v2/panels", json=body)

    async def get_panel(self, panel_id: str) -> dict:
        return await self._request("GET", f"/v2/panels/{panel_id}")

    async def update_panel(self, panel_id: str, panel: dict) -> dict:
        return await self._request("PUT", f"/v2/panels/{panel_id}", json={"panel": panel})

    async def delete_panel(self, panel_id: str) -> dict:
        return await self._request("DELETE", f"/v2/panels/{panel_id}")

    async def update_panel_target(
        self, panel_id: str, op: str, user_openids: list[str] | None = None,
        group_openids: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"op": op}
        if user_openids:
            body["user_openids"] = user_openids[:20]
        if group_openids:
            body["group_openids"] = group_openids[:20]
        return await self._request(
            "PUT", f"/v2/panels/{panel_id}/target", json=body
        )
