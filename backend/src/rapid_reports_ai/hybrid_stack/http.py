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
