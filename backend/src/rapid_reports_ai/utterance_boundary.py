"""Per-chunk boundary decision: has the radiologist finished a statement?

Replaces Deepgram's silence timers as the trigger for polish in the lab. One Jev
call per finalised chunk answers boundary (complete/continues/command) and records
an ASR-risk signal. Thresholds live in code (jev_questions), not in the model.

Spec: docs/superpowers/specs/2026-09-24-utterance-front-door-design.md
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx

from .dictation_triage import JEV_MODEL, JEV_TIMEOUT_S, TriageError, _check_unit
from .jev_client import jev_post
from .jev_questions import (  # noqa: F401  (re-exported)
    ASR_RISK_THRESHOLD,
    BOUNDARY_QUESTIONS,
    COMMAND_THRESHOLD,
    COMPLETE_THRESHOLD,
    PLACEMENT_THRESHOLD,
)

Boundary = Literal["complete", "continues", "command"]
BOUNDARIES: tuple[str, ...] = ("complete", "continues", "command")
Placement = Literal["extend_previous_line", "new_line", "new_paragraph"]
PLACEMENTS: tuple[str, ...] = ("extend_previous_line", "new_line", "new_paragraph")
@dataclass(frozen=True)
class BoundaryDecision:
    boundary: str
    confidence: float
    probabilities: dict[str, float]
    asr_risk: float
    latency_ms: int
    input_tokens: Optional[int]
    cost_usd: Optional[float]
    placement: str = "new_line"
    placement_confidence: float = 0.0
    placement_probabilities: dict[str, float] | None = None
    standalone: float = 0.0


class JevBoundary:
    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = JEV_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
        if not self._api_key:
            raise TriageError("OPENROUTER_API_KEY is not set")
        self._transport = transport
        self._timeout_s = timeout_s

    async def classify(
        self, scan_type: str, buffered: str, chunk: str, scratchpad_tail: str, silence_s: float = 0.0
    ) -> BoundaryDecision:
        body = {
            "model": JEV_MODEL,
            "state": {
                "scan_type": scan_type or "",
                "buffered": buffered or "",
                "chunk": chunk or "",
                "scratchpad_tail": scratchpad_tail or "",
                "silence_s": round(float(silence_s or 0.0), 1),
            },
            "questions": BOUNDARY_QUESTIONS,
        }
        t0 = time.perf_counter()
        try:
            resp = await jev_post(body, self._api_key, self._timeout_s, self._transport)
        except httpx.HTTPError as e:
            raise TriageError(f"jev boundary transport failure: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            raise TriageError(f"jev boundary http {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise TriageError("jev boundary returned non-JSON") from e
        answers = data.get("answers") or {}
        if any(k not in answers for k in ("boundary", "asr_risk", "placement", "standalone")):
            raise TriageError("jev boundary answer missing")
        b = answers["boundary"]
        boundary = b.get("choice")
        if boundary not in BOUNDARIES:
            raise TriageError(f"jev boundary unknown choice: {boundary!r}")
        probabilities = {k: _check_unit(v, f"probability[{k}]") for k, v in (b.get("probabilities") or {}).items()}
        pl = answers["placement"]
        placement = pl.get("choice")
        if placement not in PLACEMENTS:
            raise TriageError(f"jev placement unknown choice: {placement!r}")
        usage = data.get("usage") or {}
        return BoundaryDecision(
            boundary=boundary,
            confidence=_check_unit(b.get("confidence"), "confidence"),
            probabilities=probabilities,
            asr_risk=_check_unit(answers["asr_risk"].get("noul"), "asr_risk"),
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            cost_usd=usage.get("cost"),
            placement=placement,
            placement_confidence=_check_unit(pl.get("confidence"), "placement confidence"),
            placement_probabilities={k: _check_unit(v, f"placement[{k}]") for k, v in (pl.get("probabilities") or {}).items()},
            standalone=_check_unit(answers["standalone"].get("noul"), "standalone"),
        )


def resolve(result: BoundaryDecision | BaseException) -> Boundary:
    """Apply thresholds. Waiting is the cheap error, so anything uncertain continues;
    a failed call falls open to 'complete', which is today's timer behaviour."""
    if isinstance(result, BaseException):
        return "complete"
    if result.boundary == "complete" and result.confidence >= COMPLETE_THRESHOLD:
        return "complete"
    if result.boundary == "command" and result.confidence >= COMMAND_THRESHOLD:
        return "command"
    return "continues"


_JEV: JevBoundary | None = None


def get_jev_boundary() -> JevBoundary:
    global _JEV
    if _JEV is None:
        _JEV = JevBoundary()
    return _JEV


def resolve_placement(result: BoundaryDecision | BaseException) -> Placement:
    """A new line is the cheap error (easy to see and fix; a wrong merge rewrites a sentence)."""
    if isinstance(result, BaseException):
        return "new_line"
    if result.placement_confidence >= PLACEMENT_THRESHOLD:
        return result.placement  # type: ignore[return-value]
    return "new_line"
