# backend/src/rapid_reports_ai/scripts/jev_tool_lab/calls.py
"""Transport: Qwen via the shared agent runner (applies normalise_model_settings), Jev via OpenRouter systemone."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Tuple

import httpx
from pydantic import BaseModel

from rapid_reports_ai.enhancement_utils import _run_agent_with_model
from rapid_reports_ai.report_reconcile import JEV_MODEL, JEV_URL

QWEN_MODEL = "qwen-3.8-27b"
JEV_TIMEOUT_S = 30
QWEN_TIMEOUT_S = 180


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    requests: int = 0


async def qwen(output_type, system: str, user: str, reasoning: bool) -> Tuple[Any, Usage]:
    t = time.monotonic()
    # 16384 when reasoning: normalise_model_settings raises max_tokens to that floor anyway.
    settings = {"temperature": 0, "max_tokens": 16384 if reasoning else 3000,
                "reasoning_effort": "medium" if reasoning else "none"}
    r = await asyncio.wait_for(_run_agent_with_model(model_name=QWEN_MODEL, output_type=output_type,
                                                     system_prompt=system, user_prompt=user, api_key="",
                                                     model_settings=settings), QWEN_TIMEOUT_S)
    usage = Usage(latency_s=time.monotonic() - t)
    try:
        u = r.usage()
        usage.input_tokens = getattr(u, "input_tokens", None) or getattr(u, "request_tokens", 0) or 0
        usage.output_tokens = getattr(u, "output_tokens", None) or getattr(u, "response_tokens", 0) or 0
        usage.requests = getattr(u, "requests", 0) or 0
    except Exception:
        pass
    return r.output, usage


async def jev(by_state: Dict[str, Dict[str, dict]]) -> Tuple[Dict[str, Any], int, float]:
    """{state text: {qid: question}} -> ({qid: raw answer}, calls made, wall-clock seconds). One call per state,
    all concurrent."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    t = time.monotonic()
    async with httpx.AsyncClient() as client:
        async def one(state: str, qs: Dict[str, dict]) -> Dict[str, Any]:
            r = await client.post(JEV_URL, headers={"Authorization": f"Bearer {key}"},
                                  json={"model": JEV_MODEL, "state": state, "questions": qs}, timeout=JEV_TIMEOUT_S)
            r.raise_for_status()
            d = r.json()
            if "answers" not in d:
                raise RuntimeError(f"jev: no answers in response: {str(d)[:200]}")
            return d["answers"]
        parts = await asyncio.gather(*(one(s, qs) for s, qs in by_state.items() if qs))
    merged: Dict[str, Any] = {}
    for p in parts:
        merged.update(p)
    return merged, len(parts), time.monotonic() - t
