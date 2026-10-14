"""One keep-alive httpx client per event loop for the stack's model calls (as jev_client does)."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=20, keepalive_expiry=60.0)
_SHARED: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None


def _shared() -> httpx.AsyncClient:
    global _SHARED
    loop = asyncio.get_running_loop()
    if _SHARED is None or _SHARED[0] is not loop or _SHARED[1].is_closed:
        _SHARED = (loop, httpx.AsyncClient(limits=_LIMITS))
    return _SHARED[1]


async def post_json(url: str, api_key: str, body: dict[str, Any], timeout_s: float,
                    transport: httpx.AsyncBaseTransport | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if transport is not None:  # tests
        async with httpx.AsyncClient(transport=transport) as c:
            return await c.post(url, json=body, headers=headers, timeout=timeout_s)
    return await _shared().post(url, json=body, headers=headers, timeout=timeout_s)


CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# The same model on Groq: the prompts were validated on these models (Groq Qwen: reasoning is on or off, 16,384 cap).
_ON_GROQ = {"qwen-3.8-27b": "qwen/qwen3.8-27b", "gpt-oss-120b": "openai/gpt-oss-120b"}
_GROQ_QWEN_MAX = 16384


def groq_body(body: dict[str, Any]) -> dict[str, Any] | None:
    model = _ON_GROQ.get(body.get("model", ""))
    if model is None:
        return None
    out = {**body, "model": model}
    if model.startswith("qwen/"):
        if "reasoning_effort" in out:
            out["reasoning_effort"] = "none" if out["reasoning_effort"] == "none" else "default"
        if "max_tokens" in out:
            out["max_tokens"] = min(int(out["max_tokens"]), _GROQ_QWEN_MAX)
    return out


async def post_chat(body: dict[str, Any], timeout_s: float, transport: httpx.AsyncBaseTransport | None = None,
                    label: str = "stack") -> httpx.Response:
    """A chat call on Cerebras; on a rate limit, a server error or no response, the same request on Groq (live
    2026-10-12: Cerebras 'high traffic' 429s blanked the steps that had no fallback). The caller handles the reply."""
    import logging, os
    try:
        r = await post_json(CEREBRAS_URL, os.environ.get("CEREBRAS_API_KEY", ""), body, timeout_s, transport)
        if r.status_code != 429 and r.status_code < 500:
            return r
        reason = f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        reason = type(e).__name__
    alt = groq_body(body)
    if alt is None or not os.environ.get("GROQ_API_KEY"):
        raise httpx.HTTPError(f"Cerebras {reason}; no Groq fallback")
    logging.getLogger(__name__).warning("[%s] Cerebras %s; Groq %s", label, reason, alt["model"])
    return await post_json(GROQ_URL, os.environ["GROQ_API_KEY"], alt, timeout_s, transport)
