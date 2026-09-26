"""System 1 utterance triage: two interchangeable classifiers behind one interface.

A triager answers one question about the latest dictation utterance — what should
the scratchpad do with it — plus two yes/no signals. It returns typed values, never
prose. Nothing here edits the scratchpad; routing lives in dictation_triage_router.

Candidates:
  JevTriager  — TypeSafe Jev 1.13 via OpenRouter's System One endpoint. Calibrated
                probabilities and a confidence. ~0.3 s.
  QwenTriager — the production canvas model with reasoning off and a 3-field schema.
                No confidence (an LLM's self-reported confidence is not calibrated).

Spec: docs/superpowers/specs/2026-09-24-jev-dictation-triage-shadow-design.md
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol, get_args

import httpx
from pydantic import BaseModel

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
QWEN_TIMEOUT_S = 8.0

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


class Triager(Protocol):
    name: str

    async def classify(self, state: TriageState) -> TriageDecision: ...


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


class QwenTriageOutput(BaseModel):
    """Tiny typed schema: three fields, nothing that invites prose.

    The two signals are yes/no string literals, not JSON booleans: Groq's tool-call
    validator rejects the "True"/"False" strings the model emits for bool fields
    (seen on 11 of 48 fixtures in the first bake-off)."""

    action: TriageAction
    is_correction: YesNo
    needs_committed_edit: YesNo


def _build_qwen_system_prompt() -> str:
    lines = [
        "You classify the latest utterance of a radiologist's live dictation. Return only the structured fields.",
        "",
        "Choose exactly one action:",
    ]
    for action, desc in ACTION_DESCRIPTIONS.items():
        lines.append(f"- {action}: {desc}")
    lines += [
        "",
        "is_correction: yes when " + TRIAGE_QUESTIONS["is_correction"]["instructions"].lower() + " Otherwise no.",
        "needs_committed_edit: yes when " + TRIAGE_QUESTIONS["needs_committed_edit"]["instructions"].lower() + " Otherwise no.",
        "",
        "Do not explain. Do not reason. Output the fields only.",
    ]
    return "\n".join(lines)


QWEN_SYSTEM_PROMPT = _build_qwen_system_prompt()

QWEN_USER_PROMPT_TEMPLATE = """## Scan type
{scan_type}

## COMMITTED (frozen)
{committed}

## ACTIVE
{active}

## Latest utterance
{latest_utterance}"""

Runner = Callable[..., Awaitable[Any]]


class QwenTriager:
    name: str = "qwen"

    def __init__(
        self,
        runner: Runner | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
        timeout_s: float = QWEN_TIMEOUT_S,
    ) -> None:
        self._runner = runner
        self._model_name = model_name
        self._api_key = api_key
        self._timeout_s = timeout_s

    def _resolve(self) -> tuple[Runner, str, str, dict[str, Any]]:
        # Lazy imports: enhancement_utils is heavy and canvas_routes imports this module.
        from .canvas_routes import _adapt_canvas_settings
        from .enhancement_utils import (
            MODEL_CONFIG,
            _get_api_key_for_provider,
            _get_model_provider,
            _run_agent_with_model,
        )

        model = self._model_name or MODEL_CONFIG["CANVAS_PROCESS"]
        api_key = self._api_key or _get_api_key_for_provider(_get_model_provider(model))
        settings = _adapt_canvas_settings(
            model,
            {"temperature": 0.0, "max_completion_tokens": 120, "extra_body": {"reasoning_effort": "none"}},
        )
        return (self._runner or _run_agent_with_model), model, api_key, settings

    async def classify(self, state: TriageState) -> TriageDecision:
        try:
            runner, model, api_key, settings = self._resolve()
        except Exception as e:  # unknown model / missing key => no decision
            raise TriageError(f"qwen configuration failure: {type(e).__name__}") from e
        user_prompt = QWEN_USER_PROMPT_TEMPLATE.format(
            scan_type=state.scan_type or "(not specified)",
            committed=state.committed or "(empty)",
            active=state.active or "(empty)",
            latest_utterance=state.latest_utterance,
        )
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                runner(
                    model_name=model,
                    output_type=QwenTriageOutput,
                    system_prompt=QWEN_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    api_key=api_key,
                    use_thinking=False,
                    model_settings=settings,
                ),
                timeout=self._timeout_s,
            )
        except Exception as e:  # any provider/schema/timeout failure => no decision
            raise TriageError(f"qwen failure: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - t0) * 1000)
        out: QwenTriageOutput = result.output
        return TriageDecision(
            candidate="qwen",
            action=out.action,
            confidence=None,
            probabilities=None,
            is_correction=1.0 if out.is_correction == "yes" else 0.0,
            needs_committed_edit=1.0 if out.needs_committed_edit == "yes" else 0.0,
            latency_ms=latency_ms,
            input_tokens=None,
            cost_usd=None,
        )


_TRIAGERS: dict[str, Triager] = {}


def get_triager(name: Candidate) -> Triager:
    """Singleton per candidate. Raises ValueError for an unknown name, TriageError if
    the candidate cannot be constructed (e.g. missing key)."""
    if name not in ("jev", "qwen"):
        raise ValueError(f"unknown triage candidate: {name!r}")
    if name not in _TRIAGERS:
        _TRIAGERS[name] = JevTriager() if name == "jev" else QwenTriager()
    return _TRIAGERS[name]


# --- Trace models: what the lab and the shadow log carry ------------------------


class TriageCandidateTrace(BaseModel):
    action: Optional[str] = None
    confidence: Optional[float] = None
    probabilities: Optional[dict[str, float]] = None
    is_correction: Optional[float] = None
    needs_committed_edit: Optional[float] = None
    latency_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


class TriageTrace(BaseModel):
    mode: Literal["debug", "route"]
    derived: Optional[str] = None
    routed: Optional[Literal["deterministic", "model"]] = None
    routed_by: Optional[Candidate] = None
    live_latency_ms: Optional[int] = None
    jev: Optional[TriageCandidateTrace] = None
    qwen: Optional[TriageCandidateTrace] = None


def decision_to_trace(result: TriageDecision | BaseException) -> TriageCandidateTrace:
    if isinstance(result, BaseException):
        return TriageCandidateTrace(error=type(result).__name__)
    return TriageCandidateTrace(
        action=result.action,
        confidence=result.confidence,
        probabilities=result.probabilities,
        is_correction=result.is_correction,
        needs_committed_edit=result.needs_committed_edit,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        cost_usd=result.cost_usd,
    )
