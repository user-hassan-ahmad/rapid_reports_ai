"""One keep-alive HTTP client for every Jev call (triage, boundary, coverage, bundle).

A client per request paid DNS + TCP + TLS on every call, so every measured latency
was a first call. Here one httpx.AsyncClient per event loop is shared and kept
alive; the app closes it on shutdown and warms it when a dictation socket opens.

Tests keep injecting a transport: with one, the call gets its own client on that
transport, exactly as before. RR_JEV_FRESH_CLIENT=1 restores the old per-request
behaviour; it exists only so the before/after latency can be measured in one run.

Spec: docs/superpowers/research/2026-09-26-jev-field-research.md D-01
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

JEV_MODEL = "typesafe/jev-1.13"  # pinned; jev-latest redirects and would drift mid-pilot
JEV_URL = "https://openrouter.ai/api/v1/systemone"
# TypeSafe direct (RR_JEV_ROUTE=direct + JEV_API_KEY): ~25 ms faster at p50 than OpenRouter,
# same answers (A/B 2026-09-27). Same model, versioned name. Default stays OpenRouter:
# going direct changes the sub-processor story in the pre-launch governance item.
JEV_DIRECT_URL = "https://api.typesafe.ai/v1/systemone"
JEV_DIRECT_MODEL = "jev-1.13.0"


def _route(body: dict[str, Any], api_key: str) -> tuple[str, dict[str, Any], str]:
    direct_key = os.environ.get("JEV_API_KEY", "")
    if os.environ.get("RR_JEV_ROUTE") == "direct" and direct_key:
        model = JEV_DIRECT_MODEL if body.get("model") == JEV_MODEL else body.get("model")
        return JEV_DIRECT_URL, {**body, "model": model}, direct_key
    return JEV_URL, body, api_key
WARM_UP_TIMEOUT_S = 5.0
LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=20, keepalive_expiry=60.0)

_SHARED: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None
_WARM_TASKS: set[asyncio.Task] = set()


def _build_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, limits=LIMITS)


def shared_client() -> httpx.AsyncClient:
    """The shared client for the running loop; a new loop (a script's second
    asyncio.run, a pytest loop) gets a new one rather than a dead one."""
    global _SHARED
    loop = asyncio.get_running_loop()
    if _SHARED is None or _SHARED[0] is not loop or _SHARED[1].is_closed:
        _SHARED = (loop, _build_client())
    return _SHARED[1]


def _fresh_per_request() -> bool:
    return os.environ.get("RR_JEV_FRESH_CLIENT") == "1"


async def jev_post(
    body: dict[str, Any],
    api_key: str,
    timeout_s: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    url, body, api_key = _route(body, api_key)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if transport is not None or _fresh_per_request():
        async with _build_client(transport) as client:
            return await client.post(url, json=body, headers=headers, timeout=timeout_s)
    return await shared_client().post(url, json=body, headers=headers, timeout=timeout_s)


async def warm_up(api_key: str | None = None) -> int | None:
    """One minimal Jev call: opens the pooled connection and wakes the route.
    Returns its latency in ms, or None on any failure. Never raises."""
    key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    body = {
        "model": JEV_MODEL,
        "state": {"text": "ok"},
        "questions": {"warm": {"type": "noul", "instructions": "The text is empty."}},
    }
    t0 = time.perf_counter()
    try:
        resp = await jev_post(body, key, WARM_UP_TIMEOUT_S)
    except Exception as e:
        logger.warning("[jev.warm_up] failed: %s", type(e).__name__)
        return None
    ms = int((time.perf_counter() - t0) * 1000)
    if resp.status_code != 200:
        logger.warning("[jev.warm_up] http %s", resp.status_code)
        return None
    logger.info("[jev.warm_up] %dms", ms)
    return ms


def warmup_wanted() -> bool:
    """Only when a Jev path is switched on; with every flag off, nothing is sent."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        return False
    return (
        os.environ.get("RR_TRIAGE_DEBUG") == "1"
        or os.environ.get("RR_TRIAGE_SHADOW") == "1"
        or os.environ.get("RR_COVERAGE_CANDIDATE", "").strip().lower() == "jev"
    )


def schedule_warm_up() -> asyncio.Task | None:
    """Fire-and-forget from the dictation socket; never delays the socket."""
    if not warmup_wanted():
        return None
    task = asyncio.create_task(warm_up())
    _WARM_TASKS.add(task)
    task.add_done_callback(_WARM_TASKS.discard)
    return task


async def aclose() -> None:
    global _SHARED
    if _SHARED is None:
        return
    _, client = _SHARED
    _SHARED = None
    await client.aclose()
