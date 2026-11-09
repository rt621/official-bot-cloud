"""AI 服务层：供规则引擎（AI 审核）与 AI 对话共用的 LLM 调用。

- OpenAI 兼容 chat/completions（GLM/DeepSeek/OpenAI 等均可）
- chat_json: 要求模型只输出 JSON，带健壮提取（容忍模型夹带说明文字）
"""

import json
import logging
import re

import httpx

log = logging.getLogger("runtime.ai")

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

DEFAULT_AUDIT_PROMPT = (
    "你是QQ群的安全审核员。判断下面的群消息是否违规。违规类型包括："
    "垃圾广告、诈骗引流、发布手机号/QQ号等联系方式拉人、引战辱骂。"
    "正常的聊天、提问、日常交流不算违规。"
    '只输出一个JSON对象，格式：{"violation": true或false, "type": "广告|诈骗|引流|辱骂|其他|无", "reason": "20字以内的理由"}'
)


async def chat(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: int = 45,
) -> str:
    url = api_base.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "stream": False, "temperature": 0.1},
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


async def chat_json(
    api_base: str,
    api_key: str,
    model: str,
    system: str,
    user_content: str,
    timeout: int = 45,
) -> dict | None:
    """调用并解析 JSON 输出；失败返回 None（调用方按'跳过审核'处理）。"""
    try:
        text = await chat(
            api_base,
            api_key,
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("AI 调用失败: %s", exc)
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
