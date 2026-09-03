"""OpenAI 兼容的 LLM 客户端（httpx 直连，支持 DeepSeek / 智谱 / OpenAI 等）。"""
from __future__ import annotations

import json
import logging
import re

import httpx

from . import config

log = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


async def chat(messages: list[dict], temperature: float = 0.3,
               max_tokens: int = 3000, retries: int = 2) -> str:
    if not config.LLM_CONFIGURED:
        raise LLMNotConfigured("未配置 LLM_API_KEY（.env），无法调用大模型")
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    last_err = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
                r = await client.post(f"{config.LLM_BASE_URL}/chat/completions",
                                      json=payload, headers=headers)
            if r.status_code == 429 or r.status_code >= 500:
                raise LLMError(f"LLM 服务返回 {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return content or ""
        except Exception as e:
            last_err = e
            log.warning("LLM 调用失败(第 %s 次): %s", attempt + 1, e)
    raise LLMError(f"LLM 调用失败: {last_err}")


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


def parse_json(text: str) -> dict:
    """从模型输出中稳健地提取 JSON（容忍代码围栏与前后缀文本）。"""
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    start = min((i for i in (text.find("{"), text.find("["))
                 if i >= 0), default=-1)
    if start > 0:
        text = text[start:]
    end = max(text.rfind("}"), text.rfind("]"))
    if end != -1 and end < len(text) - 1:
        text = text[:end + 1]
    return json.loads(text)
