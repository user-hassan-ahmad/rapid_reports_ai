"""System 1 utterance triage: Jev's answer about the latest dictation utterance.

A triager answers one question about the latest dictation utterance — what should
the scratchpad do with it — plus two yes/no signals. It returns typed values, never
prose. The dictation package asks these questions inside one bundle per final
(utterance_bundle), which parses the answers with JevTriager.parse; routing lives in
fast_append.

JevTriager — TypeSafe Jev 1.13 via OpenRouter's System One endpoint. Calibrated
probabilities and a confidence. ~0.3 s. (The Qwen candidate and the /process
route/debug/shadow modes were retired on 2026-09-29.)

Spec: docs/superpowers/specs/2026-09-24-jev-dictation-triage-shadow-design.md
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional, get_args

import httpx

from .jev_client import JEV_MODEL, JEV_URL, jev_post  # noqa: F401  (re-exported)
from .jev_questions import ACTION_DESCRIPTIONS, QSET_VERSION, TRIAGE_QUESTIONS  # noqa: F401  (re-exported)

TriageAction = Literal[
    "append_new_finding",
    "correct_previous_finding",
    "restate_existing_finding",
    "delete_previous_utterance",
    "formatting_command",
    "ignore_noise",
]
TRIAGE_ACTIONS: tuple[str, ...] = get_args(TriageAction)

JEV_TIMEOUT_S = 3.0

Candidate = Literal["jev", "qwen"]


class TriageError(RuntimeError):
    """Any failure that means there is no valid decision. Never swallowed into a default."""


@dataclass(frozen=True)
class TriageState:
    committed: str
    active: str
    latest_utterance: str
    scan_type: str = ""

    def as_payload(self) -> dict[str, str]:
        return {
            "committed": self.committed,
            "active": self.active,
            "latest_utterance": self.latest_utterance,
            "scan_type": self.scan_type,
        }


@dataclass(frozen=True)
class TriageDecision:
    candidate: Candidate
    action: str
    confidence: Optional[float]
    probabilities: Optional[dict[str, float]]
    is_correction: Optional[float]
    needs_committed_edit: Optional[float]
    latency_ms: int
    input_tokens: Optional[int]
    cost_usd: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _check_unit(value: Any, what: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not (0.0 <= float(value) <= 1.0):
        raise TriageError(f"{what} out of range: {value!r}")
    return float(value)


class JevTriager:
    name: str = "jev"

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

    def build_request(self, state: TriageState) -> dict[str, Any]:
        return {"model": JEV_MODEL, "state": state.as_payload(), "questions": TRIAGE_QUESTIONS}

    async def classify(self, state: TriageState) -> TriageDecision:
        t0 = time.perf_counter()
        try:
            resp = await jev_post(self.build_request(state), self._api_key, self._timeout_s, self._transport)
        except httpx.HTTPError as e:
            raise TriageError(f"jev transport failure: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            raise TriageError(f"jev http {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise TriageError("jev returned non-JSON") from e
        return self.parse(data, latency_ms)

    @staticmethod
    def parse(data: dict[str, Any], latency_ms: int) -> TriageDecision:
        answers = data.get("answers") or {}
        for qid in TRIAGE_QUESTIONS:
            if qid not in answers:
                raise TriageError(f"jev answer missing: {qid}")
        action_ans = answers["action"]
        action = action_ans.get("choice")
        if action not in TRIAGE_ACTIONS:
            raise TriageError(f"jev unknown choice: {action!r}")
        raw_probs = action_ans.get("probabilities") or {}
        probabilities = {k: _check_unit(v, f"probability[{k}]") for k, v in raw_probs.items()}
        confidence = _check_unit(action_ans.get("confidence"), "confidence")
        is_correction = _check_unit(answers["is_correction"].get("noul"), "is_correction")
        needs_committed_edit = _check_unit(answers["needs_committed_edit"].get("noul"), "needs_committed_edit")
        usage = data.get("usage") or {}
        return TriageDecision(
            candidate="jev",
            action=action,
            confidence=confidence,
            probabilities=probabilities,
            is_correction=is_correction,
            needs_committed_edit=needs_committed_edit,
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            cost_usd=usage.get("cost"),
        )


# --- Qwen candidate ---------------------------------------------------------------


YesNo = Literal["yes", "no"]
