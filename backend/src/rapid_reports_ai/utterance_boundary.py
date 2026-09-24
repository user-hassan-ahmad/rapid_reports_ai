"""Per-chunk boundary decision: has the radiologist finished a statement?

Replaces Deepgram's silence timers as the trigger for polish in the lab. One Jev
call per finalised chunk answers boundary (complete/continues/command) and records
an ASR-risk signal. Thresholds live here, not in the model.

Spec: docs/superpowers/specs/2026-09-24-utterance-front-door-design.md
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx

from .dictation_triage import JEV_MODEL, JEV_TIMEOUT_S, JEV_URL, TriageError, _check_unit

Boundary = Literal["complete", "continues", "command"]
BOUNDARIES: tuple[str, ...] = ("complete", "continues", "command")
Placement = Literal["extend_previous_line", "new_line", "new_paragraph"]
PLACEMENTS: tuple[str, ...] = ("extend_previous_line", "new_line", "new_paragraph")
PLACEMENT_THRESHOLD = 0.5  # below this, the cheap error: a new line
# Bake-off run 1 (38 cases): the raw choice is right 0.868 of the time; every threshold
# above 0.4 only converted correct answers into stalls (the three wrong sends are the same
# three at any setting). Thresholds are therefore a floor against near-uniform
# distributions, not a precision lever. Waiting is bounded by the frontend backstop.
# Run 2 (mic): a 0.4 floor demoted three correct completes at 0.26-0.38 into 1.5 s waits.
# On a three-way choice confidence sits low whenever two options are plausible; the floor
# is a near-uniform guard only.
COMPLETE_THRESHOLD = 0.2
COMMAND_THRESHOLD = 0.2
# Not acted on yet. On the same run 0.7 separated the three true ASR cases from every
# clean one (baseline noul sits ~0.5–0.65 on clean text).
ASR_RISK_THRESHOLD = 0.7

BOUNDARY_QUESTIONS: dict[str, dict[str, Any]] = {
    "boundary": {
        "type": "choice",
        "instructions": (
            "Taking the buffered words and the chunk together as what the radiologist has said since the "
            "last statement was sent, which is true?"
        ),
        "criteria": {
            "complete": (
                "The buffered words plus the chunk form a finished clinical statement a radiologist would end "
                "here: a finding, a measurement, a normality claim, or a correction that is fully specified."
            ),
            "continues": (
                "The statement is still in progress: it ends on a preposition, article, conjunction, a verb "
                "without its object, an unfinished measurement, an unfinished correction such as 'actually' or "
                "'make that', or otherwise needs more words to be a claim."
            ),
            "command": (
                "The chunk is an instruction to the application or a dictation command rather than report "
                "content: scratch that, delete that, new paragraph, new line, full stop, generate report, "
                "switch mode, and similar."
            ),
        },
    },
    "placement": {
        "type": "choice",
        "instructions": (
            "If the buffered words plus the chunk are a finished statement, where does it belong in the "
            "scratchpad relative to the last line? The scratchpad captures dictation as it is spoken; it is "
            "not the report."
        ),
        "criteria": {
            "extend_previous_line": (
                "It adds to the same observation as the last line: a descriptor, a measurement, a qualifier, "
                "a consequence, or a clause such as 'with' or 'which' that continues that finding."
            ),
            "new_line": (
                "It is a separate finding or normality claim about the same region or system as the last line."
            ),
            "new_paragraph": (
                "It moves to a different anatomical region or system from the last line, or the last line is "
                "empty."
            ),
        },
    },
    "asr_risk": {
        "type": "noul",
        "instructions": (
            "The buffered words plus the chunk contain a likely speech-to-text error: a word that is "
            "phonetically close to a radiological term the scan type or the scratchpad makes expected, and "
            "that makes no clinical sense as heard."
        ),
    },
}


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

    async def classify(self, scan_type: str, buffered: str, chunk: str, scratchpad_tail: str) -> BoundaryDecision:
        body = {
            "model": JEV_MODEL,
            "state": {
                "scan_type": scan_type or "",
                "buffered": buffered or "",
                "chunk": chunk or "",
                "scratchpad_tail": scratchpad_tail or "",
            },
            "questions": BOUNDARY_QUESTIONS,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
                resp = await client.post(JEV_URL, json=body, headers=headers)
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
        if "boundary" not in answers or "asr_risk" not in answers or "placement" not in answers:
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
