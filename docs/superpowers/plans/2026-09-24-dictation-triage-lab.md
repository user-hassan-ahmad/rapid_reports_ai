# Dictation Triage + Dictation Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two System 1 utterance classifiers (Jev 1.13 via OpenRouter, Qwen 27B reasoning-off) behind one interface, a gated `/dictation-lab` dev route that mounts the production dictation UI with a scripted feeder and per-utterance triage traces, a lab-only routing mode, and a production log-only shadow mode.

**Architecture:** Backend gains three small pure-ish modules (`dictation_triage`, `dictation_triage_labels`, `dictation_triage_router`) and three env-gated modes inside the existing `/api/canvas/process` route. Frontend gains an exported `injectTranscript` on the production scratchpad, two optional pass-through props, pure TS lab helpers under `src/lib/dictation-lab/`, and a dev route that reuses `IntelliDictateTab` unchanged.

**Tech Stack:** Python 3.13, FastAPI, pydantic, httpx (already a dependency), pytest (`asyncio_mode=auto`); SvelteKit 2 / Svelte 5 (legacy `export let` style, as the codebase uses), vitest "server" project for pure TS modules.

**Spec:** `docs/superpowers/specs/2026-09-24-jev-dictation-triage-shadow-design.md`

**Working branch:** create `dictation-triage-lab` from `main` in a fresh worktree (`superpowers:using-git-worktrees`). Do not build on `skill-sheet-v3`; it carries unrelated uncommitted work.

**Run commands (from `backend/`):** `.venv/bin/pytest tests/<file> -v` for backend. From `frontend/`: `bun run test -- --project server` for pure TS tests (no browser needed); `bun run dev` for the lab.

---

## File structure

**Backend (`backend/`)**

| File | Responsibility |
|---|---|
| `src/rapid_reports_ai/dictation_triage.py` (new) | Action set, state/decision types, question constants, `JevTriager`, `QwenTriager`, `get_triager`, trace pydantic models |
| `src/rapid_reports_ai/dictation_triage_labels.py` (new) | `derive_action`, `AGREEMENT_MAP`, `agrees` |
| `src/rapid_reports_ai/dictation_triage_router.py` (new) | `apply_deterministic`, `route`, formatting lexicon |
| `src/rapid_reports_ai/canvas_routes.py` (modify) | Request/response fields, env flags, route/debug/shadow modes, fixtures endpoint |
| `src/rapid_reports_ai/scripts/triage_summary.py` (new) | Pure `summarise(records)` shared by bake-off and shadow report |
| `src/rapid_reports_ai/scripts/triage_bakeoff.py` (new) | Runs fixtures through both candidates live |
| `src/rapid_reports_ai/scripts/triage_shadow_report.py` (new) | Summarises a shadow log dump |
| `tests/fixtures/triage_utterances.jsonl` (new) | Hand-labelled cases |
| `tests/test_dictation_triage.py`, `tests/test_dictation_triage_labels.py`, `tests/test_dictation_triage_router.py`, `tests/test_canvas_triage_modes.py`, `tests/test_triage_fixtures.py`, `tests/test_triage_summary.py`, `tests/test_dictation_triage_live.py` (new) | Tests |
| `.env.example` (modify) | Document `RR_TRIAGE_DEBUG`, `RR_TRIAGE_SHADOW` |

**Frontend (`frontend/`)**

| File | Responsibility |
|---|---|
| `src/lib/dictation-lab/types.ts` (new) | `LabConfig`, `TriageTrace`, `ProcessTrace`, `FixtureCase` |
| `src/lib/dictation-lab/delta.ts` (new) | `computeDelta` |
| `src/lib/dictation-lab/labConfig.ts` (new) | store + localStorage persistence + `toRequestFields` |
| `src/lib/dictation-lab/fixtureExport.ts` (new) | `buildFixtureLine` |
| `src/lib/dictation-lab/summary.ts` (new) | `agreementClass`, `summariseTraces` |
| `src/lib/dictation-lab/*.test.ts` (new) | vitest server-project tests |
| `src/lib/components/DictationScratchpad.svelte` (modify) | `handleFinalTranscript`, `injectTranscript`, delta, lab props |
| `src/routes/components/IntelliDictateTab.svelte` (modify) | pass-through props + `injectTranscript` export |
| `src/lib/components/DictationLabPanel.svelte` (new) | Feeder, strategy, timeline, export, summary |
| `src/routes/dictation-lab/+page.ts`, `+page.svelte` (new) | Gated lab route |

---

### Task 1: Triage types, questions and the Jev client

**Files:**
- Create: `backend/src/rapid_reports_ai/dictation_triage.py`
- Test: `backend/tests/test_dictation_triage.py`

- [x] **Step 1: Write the failing tests for the Jev client**

```python
# backend/tests/test_dictation_triage.py
"""Unit tests for the System 1 triage candidates. Offline: Jev is exercised through
an httpx MockTransport; Qwen through an injected runner."""
from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.dictation_triage import (
    ACTION_DESCRIPTIONS,
    JEV_MODEL,
    JEV_URL,
    TRIAGE_ACTIONS,
    JevTriager,
    TriageError,
    TriageState,
)

STATE = TriageState(
    committed="- 12 mm hypodense lesion segment 7",
    active="- 6 mm nodule right upper lobe",
    latest_utterance="actually make that the left upper lobe",
    scan_type="CT chest",
)


def _jev_response(action="correct_previous_finding", confidence=0.97, extra=None):
    probs = {a: 0.0 for a in TRIAGE_ACTIONS}
    probs[action] = 1.0
    body = {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "action": {"type": "choice", "choice": action, "confidence": confidence, "probabilities": probs},
            "is_correction": {"type": "noul", "noul": 0.94},
            "needs_committed_edit": {"type": "noul", "noul": 0.03},
        },
        "usage": {"input_tokens": 578, "output_tokens": 40, "cost": 2.4e-05},
    }
    if extra:
        body.update(extra)
    return body


def _transport(handler):
    return httpx.MockTransport(handler)


def test_action_set_has_six_entries_with_descriptions():
    assert len(TRIAGE_ACTIONS) == 6
    assert set(ACTION_DESCRIPTIONS) == set(TRIAGE_ACTIONS)


async def test_jev_sends_expected_request_shape():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_jev_response())

    triager = JevTriager(api_key="sk-test", transport=_transport(handler))
    await triager.classify(STATE)

    assert captured["url"] == JEV_URL
    assert captured["auth"] == "Bearer sk-test"
    body = captured["body"]
    assert body["model"] == JEV_MODEL
    assert body["state"] == {
        "committed": STATE.committed,
        "active": STATE.active,
        "latest_utterance": STATE.latest_utterance,
        "scan_type": STATE.scan_type,
    }
    q = body["questions"]
    assert q["action"]["type"] == "choice"
    assert q["action"]["criteria"] == ACTION_DESCRIPTIONS
    assert q["is_correction"]["type"] == "noul"
    assert q["needs_committed_edit"]["type"] == "noul"


async def test_jev_parses_success_into_decision():
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(200, json=_jev_response())))
    d = await triager.classify(STATE)
    assert d.candidate == "jev"
    assert d.action == "correct_previous_finding"
    assert d.confidence == 0.97
    assert d.probabilities["correct_previous_finding"] == 1.0
    assert d.is_correction == 0.94
    assert d.needs_committed_edit == 0.03
    assert d.input_tokens == 578
    assert d.cost_usd == 2.4e-05
    assert d.latency_ms >= 0


@pytest.mark.parametrize(
    "status, body",
    [
        (400, {"error": {"message": "bad"}}),
        (500, {"error": {"message": "boom"}}),
    ],
)
async def test_jev_raises_on_non_2xx(status, body):
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(status, json=body)))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_missing_answer():
    resp = _jev_response()
    del resp["answers"]["needs_committed_edit"]
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(200, json=resp)))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_unknown_choice():
    triager = JevTriager(
        api_key="k", transport=_transport(lambda r: httpx.Response(200, json=_jev_response(action="explode")))
    )
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_out_of_range_values():
    resp = _jev_response()
    resp["answers"]["is_correction"]["noul"] = 1.4
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(200, json=resp)))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    triager = JevTriager(api_key="k", transport=_transport(handler))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


def test_jev_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(TriageError):
        JevTriager()
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.dictation_triage'`

- [x] **Step 3: Create the module with types, questions and the Jev client**

```python
# backend/src/rapid_reports_ai/dictation_triage.py
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
from dataclasses import dataclass, asdict
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol, get_args

import httpx
from pydantic import BaseModel

TriageAction = Literal[
    "append_new_finding",
    "correct_previous_finding",
    "restate_existing_finding",
    "delete_previous_utterance",
    "formatting_command",
    "ignore_noise",
]
TRIAGE_ACTIONS: tuple[str, ...] = get_args(TriageAction)

# One sentence per option. Both candidates receive exactly these words, so they
# answer the same question. Edit here, nowhere else.
ACTION_DESCRIPTIONS: dict[str, str] = {
    "append_new_finding": "The utterance states a new clinical observation or normality claim that is not yet in the scratchpad",
    "correct_previous_finding": "The utterance revises, replaces or retracts a value or descriptor of something already in the scratchpad",
    "restate_existing_finding": "The utterance repeats something already captured in the scratchpad, with no new information",
    "delete_previous_utterance": "The utterance asks to remove the immediately preceding statement, such as scratch that or delete that",
    "formatting_command": "The utterance is a formatting instruction such as new line, new paragraph or full stop",
    "ignore_noise": "The utterance is filler, hesitation or thinking aloud with no clinical content",
}

TRIAGE_QUESTIONS: dict[str, dict[str, Any]] = {
    "action": {
        "type": "choice",
        "instructions": "What should the dictation scratchpad system do with the latest utterance?",
        "criteria": ACTION_DESCRIPTIONS,
    },
    "is_correction": {
        "type": "noul",
        "instructions": "The latest utterance revises or corrects something said earlier.",
    },
    "needs_committed_edit": {
        "type": "noul",
        "instructions": "Applying the latest utterance requires changing text in the COMMITTED (frozen) section rather than the ACTIVE section.",
    },
}

JEV_MODEL = "typesafe/jev-1.13"  # pinned; jev-latest redirects and would drift mid-pilot
JEV_URL = "https://openrouter.ai/api/v1/systemone"
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
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
                resp = await client.post(JEV_URL, json=self.build_request(state), headers=headers)
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
```

- [x] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage.py -v`
Expected: all 9 tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictation_triage.py backend/tests/test_dictation_triage.py
git commit -m "feat(triage): action set, state/decision types and Jev System One client"
```

---

### Task 2: Qwen candidate, registry, and trace models

**Files:**
- Modify: `backend/src/rapid_reports_ai/dictation_triage.py` (append)
- Test: `backend/tests/test_dictation_triage.py` (append)

- [x] **Step 1: Append the failing tests**

```python
# append to backend/tests/test_dictation_triage.py
from rapid_reports_ai.dictation_triage import (  # noqa: E402
    QWEN_SYSTEM_PROMPT,
    QwenTriageOutput,
    QwenTriager,
    TriageCandidateTrace,
    decision_to_trace,
    get_triager,
)


class _FakeResult:
    def __init__(self, output):
        self.output = output


async def test_qwen_passes_reasoning_off_schema_and_maps_booleans():
    captured = {}

    async def runner(**kwargs):
        captured.update(kwargs)
        return _FakeResult(QwenTriageOutput(action="delete_previous_utterance", is_correction=True, needs_committed_edit=False))

    triager = QwenTriager(runner=runner, model_name="qwen-3.8-27b", api_key="ck")
    d = await triager.classify(STATE)

    assert captured["output_type"] is QwenTriageOutput
    assert captured["use_thinking"] is False
    assert captured["api_key"] == "ck"
    ms = captured["model_settings"]
    assert ms["temperature"] == 0.0
    assert ms["extra_body"]["reasoning_effort"] == "none"
    assert "max_completion_tokens" in ms or "max_tokens" in ms
    assert STATE.latest_utterance in captured["user_prompt"]
    assert d.candidate == "qwen"
    assert d.action == "delete_previous_utterance"
    assert d.confidence is None and d.probabilities is None and d.cost_usd is None
    assert d.is_correction == 1.0 and d.needs_committed_edit == 0.0


def test_qwen_prompt_contains_every_action_description_verbatim():
    for action, desc in ACTION_DESCRIPTIONS.items():
        assert action in QWEN_SYSTEM_PROMPT
        assert desc in QWEN_SYSTEM_PROMPT


async def test_qwen_wraps_runner_errors_in_triage_error():
    async def runner(**kwargs):
        raise RuntimeError("provider down")

    triager = QwenTriager(runner=runner, model_name="qwen-3.8-27b", api_key="ck")
    with pytest.raises(TriageError):
        await triager.classify(STATE)


def test_get_triager_returns_named_candidate(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert get_triager("jev").name == "jev"
    with pytest.raises(ValueError):
        get_triager("nope")  # type: ignore[arg-type]


def test_decision_to_trace_handles_exceptions():
    t = decision_to_trace(TriageError("boom"))
    assert isinstance(t, TriageCandidateTrace)
    assert t.action is None and t.error == "TriageError"
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage.py -v -k "qwen or get_triager or trace"`
Expected: FAIL with `ImportError: cannot import name 'QWEN_SYSTEM_PROMPT'`

- [x] **Step 3: Append the Qwen candidate, registry and trace models**

```python
# append to backend/src/rapid_reports_ai/dictation_triage.py


class QwenTriageOutput(BaseModel):
    """Tiny typed schema: three fields, nothing that invites prose."""

    action: TriageAction
    is_correction: bool
    needs_committed_edit: bool


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
        "is_correction: true when " + TRIAGE_QUESTIONS["is_correction"]["instructions"].lower(),
        "needs_committed_edit: true when " + TRIAGE_QUESTIONS["needs_committed_edit"]["instructions"].lower(),
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
        from .enhancement_utils import MODEL_CONFIG, _get_api_key_for_provider, _get_model_provider, _run_agent_with_model
        from .canvas_routes import _adapt_canvas_settings

        model = self._model_name or MODEL_CONFIG["CANVAS_PROCESS"]
        api_key = self._api_key or _get_api_key_for_provider(_get_model_provider(model))
        settings = _adapt_canvas_settings(
            model,
            {"temperature": 0.0, "max_completion_tokens": 120, "extra_body": {"reasoning_effort": "none"}},
        )
        return (self._runner or _run_agent_with_model), model, api_key, settings

    async def classify(self, state: TriageState) -> TriageDecision:
        runner, model, api_key, settings = self._resolve()
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
            is_correction=1.0 if out.is_correction else 0.0,
            needs_committed_edit=1.0 if out.needs_committed_edit else 0.0,
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
```

- [x] **Step 4: Run the full test file**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage.py -v`
Expected: all 14 tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictation_triage.py backend/tests/test_dictation_triage.py
git commit -m "feat(triage): Qwen reasoning-off candidate, registry and trace models"
```

---

### Task 3: Derived labels

**Files:**
- Create: `backend/src/rapid_reports_ai/dictation_triage_labels.py`
- Test: `backend/tests/test_dictation_triage_labels.py`

- [x] **Step 1: Write the failing tests**

```python
# backend/tests/test_dictation_triage_labels.py
"""derive_action is the shadow-mode ground truth. It is a heuristic, so it is pinned
by tables rather than trusted."""
from __future__ import annotations

import pytest

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS
from rapid_reports_ai.dictation_triage_labels import AGREEMENT_MAP, agrees, derive_action

A = "- 6 mm nodule right upper lobe\n- no pleural effusion"


@pytest.mark.parametrize(
    "before, after, edits, expected",
    [
        (A, A, [], "noop"),
        (A, A + "\n", [], "noop"),                                   # trailing blank line
        (A, "- 6 MM  nodule right upper lobe\n- no pleural effusion", [], "noop"),  # case + spacing
        ("- no pleural effusion\n- 6 mm nodule right upper lobe", A, [], "noop"),   # reordered
        (A, A + "\n- no pneumothorax", [], "append"),
        ("", "- lungs clear", [], "append"),
        (A, "- 6 mm nodule right upper lobe", [], "delete"),
        (A, "", [], "delete"),
        (A, "- 6 mm nodule left upper lobe\n- no pleural effusion", [], "correct"),
        (A, "- 6 mm nodule right upper lobe\n- small pleural effusion", [], "correct"),
        (A, A, [("- 12 mm lesion", "- 14 mm lesion")], "committed_edit"),
        (A, A + "\n- x", [("a", "b")], "committed_edit"),          # edits win over append
    ],
)
def test_derive_action_table(before, after, edits, expected):
    assert derive_action(before, after, edits) == expected


def test_agreement_map_covers_every_action():
    assert set(AGREEMENT_MAP) == set(TRIAGE_ACTIONS)
    for v in AGREEMENT_MAP.values():
        assert v  # non-empty


@pytest.mark.parametrize(
    "action, derived, expected",
    [
        ("append_new_finding", "append", True),
        ("append_new_finding", "correct", False),
        ("correct_previous_finding", "committed_edit", True),
        ("restate_existing_finding", "noop", True),
        ("formatting_command", "append", True),
        ("ignore_noise", "delete", False),
    ],
)
def test_agrees(action, derived, expected):
    assert agrees(action, derived) is expected
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage_labels.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement**

```python
# backend/src/rapid_reports_ai/dictation_triage_labels.py
"""Derive what the live scratchpad model actually did from its before/after text.

This is the ground-truth label for shadow mode. It is line-based (one finding per
line), deterministic, and deliberately lenient in AGREEMENT_MAP because a rewrite
by the live model is not a clean signal. Precise labels live in the fixture file.
"""
from __future__ import annotations

import re
from typing import Literal

DerivedAction = Literal["append", "correct", "delete", "noop", "committed_edit"]

_WS = re.compile(r"\s+")


def _lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = _WS.sub(" ", raw).strip().casefold()
        if line:
            out.append(line)
    return out


def derive_action(before_active: str, after_active: str, committed_edits: list[tuple[str, str]]) -> DerivedAction:
    if committed_edits:
        return "committed_edit"
    before = _lines(before_active)
    after = _lines(after_active)
    if sorted(before) == sorted(after):
        return "noop"
    if len(after) > len(before) and set(before) <= set(after):
        return "append"
    if len(after) < len(before):
        return "delete"
    return "correct"


AGREEMENT_MAP: dict[str, frozenset[str]] = {
    "append_new_finding": frozenset({"append"}),
    "correct_previous_finding": frozenset({"correct", "committed_edit"}),
    "restate_existing_finding": frozenset({"noop", "correct"}),
    "delete_previous_utterance": frozenset({"delete"}),
    "formatting_command": frozenset({"noop", "append"}),
    "ignore_noise": frozenset({"noop"}),
}


def agrees(action: str, derived: str) -> bool:
    return derived in AGREEMENT_MAP.get(action, frozenset())
```

- [x] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage_labels.py -v`
Expected: all PASS

- [x] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictation_triage_labels.py backend/tests/test_dictation_triage_labels.py
git commit -m "feat(triage): derived labels from scratchpad before/after"
```

---

### Task 4: Deterministic router (lab routing)

**Files:**
- Create: `backend/src/rapid_reports_ai/dictation_triage_router.py`
- Test: `backend/tests/test_dictation_triage_router.py`

- [x] **Step 1: Write the failing tests**

```python
# backend/tests/test_dictation_triage_router.py
from __future__ import annotations

import pytest

from rapid_reports_ai.dictation_triage import TriageDecision, TriageState
from rapid_reports_ai.dictation_triage_router import DETERMINISTIC_ACTIONS, apply_deterministic, map_formatting, route

ACTIVE = "- 6 mm nodule right upper lobe\n- no pleural effusion"


def _state(utterance: str, active: str = ACTIVE) -> TriageState:
    return TriageState(committed="", active=active, latest_utterance=utterance)


def _decision(action: str, confidence: float | None, candidate="jev") -> TriageDecision:
    return TriageDecision(
        candidate=candidate, action=action, confidence=confidence, probabilities=None,
        is_correction=None, needs_committed_edit=None, latency_ms=1, input_tokens=None, cost_usd=None,
    )


@pytest.mark.parametrize(
    "utterance, expected",
    [
        ("new paragraph", "\n\n"),
        ("New Line", "\n"),
        ("full stop", "."),
        ("fullstop", "."),
        ("<\\n\\n>", "\n\n"),
        ("<\\n>", "\n"),
        ("um", ""),
    ],
)
def test_map_formatting(utterance, expected):
    assert map_formatting(utterance) == expected


def test_formatting_command_appends_mapped_text():
    assert apply_deterministic("formatting_command", _state("new paragraph")) == ACTIVE + "\n\n"


def test_formatting_command_with_nothing_to_map_leaves_active_unchanged():
    assert apply_deterministic("formatting_command", _state("er")) == ACTIVE


@pytest.mark.parametrize("action", ["ignore_noise", "restate_existing_finding"])
def test_noop_actions_return_active_unchanged(action):
    assert apply_deterministic(action, _state("um so")) == ACTIVE


def test_delete_removes_last_non_blank_line():
    assert apply_deterministic("delete_previous_utterance", _state("scratch that", ACTIVE + "\n")) == "- 6 mm nodule right upper lobe"


def test_delete_on_empty_active_falls_through():
    assert apply_deterministic("delete_previous_utterance", _state("scratch that", "")) is None
    assert apply_deterministic("delete_previous_utterance", _state("scratch that", "\n\n")) is None


@pytest.mark.parametrize("action", ["append_new_finding", "correct_previous_finding"])
def test_model_actions_fall_through(action):
    assert apply_deterministic(action, _state("anything")) is None


def test_route_deterministic_above_threshold():
    kind, text = route(_decision("ignore_noise", 0.95), 0.9, _state("um"))
    assert kind == "deterministic" and text == ACTIVE


def test_route_falls_to_model_below_threshold():
    kind, text = route(_decision("ignore_noise", 0.5), 0.9, _state("um"))
    assert kind == "model" and text is None


def test_route_no_confidence_counts_as_certain():
    kind, _ = route(_decision("formatting_command", None, candidate="qwen"), 0.99, _state("new line"))
    assert kind == "deterministic"


def test_route_model_action_never_deterministic():
    kind, _ = route(_decision("correct_previous_finding", 1.0), 0.5, _state("actually left"))
    assert kind == "model"


def test_deterministic_set():
    assert DETERMINISTIC_ACTIONS == {"formatting_command", "delete_previous_utterance", "ignore_noise", "restate_existing_finding"}
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage_router.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement**

```python
# backend/src/rapid_reports_ai/dictation_triage_router.py
"""Lab-only routing: act on a triage decision without calling the live model.

Only the four classes with an obvious deterministic effect are handled here.
Appends and corrections always go to the live model (homophone correction and
consolidation live there). The formatting lexicon mirrors
main.process_dictation_transcript plus the spoken forms the lab feeder types.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from .dictation_triage import TriageDecision, TriageState

DETERMINISTIC_ACTIONS: frozenset[str] = frozenset(
    {"formatting_command", "delete_previous_utterance", "ignore_noise", "restate_existing_finding"}
)

_FORMATTING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\\n\\n>"), "\n\n"),
    (re.compile(r"<\\n>"), "\n"),
    (re.compile(r"\bnew\s+paragraph\b", re.IGNORECASE), "\n\n"),
    (re.compile(r"\bnew\s+line\b", re.IGNORECASE), "\n"),
    (re.compile(r"\bfull\s*stop\b", re.IGNORECASE), "."),
)


def map_formatting(utterance: str) -> str:
    """Return only the characters a formatting utterance stands for ('' if none)."""
    out: list[str] = []
    for pattern, replacement in _FORMATTING_RULES:
        for _ in pattern.findall(utterance or ""):
            out.append(replacement)
    return "".join(out)


def apply_deterministic(action: str, state: TriageState) -> Optional[str]:
    """New active text, or None to fall through to the live model."""
    active = state.active or ""
    if action == "formatting_command":
        mapped = map_formatting(state.latest_utterance)
        return active + mapped if mapped else active
    if action in ("ignore_noise", "restate_existing_finding"):
        return active
    if action == "delete_previous_utterance":
        lines = active.split("\n")
        idx = max((i for i, line in enumerate(lines) if line.strip()), default=None)
        if idx is None:
            return None
        return "\n".join(lines[:idx]).rstrip("\n")
    return None


def route(
    decision: TriageDecision, threshold: float, state: TriageState
) -> tuple[Literal["deterministic", "model"], Optional[str]]:
    if decision.action not in DETERMINISTIC_ACTIONS:
        return "model", None
    confidence = 1.0 if decision.confidence is None else decision.confidence
    if confidence < threshold:
        return "model", None
    new_active = apply_deterministic(decision.action, state)
    if new_active is None:
        return "model", None
    return "deterministic", new_active
```

- [x] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage_router.py -v`
Expected: all PASS

- [x] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictation_triage_router.py backend/tests/test_dictation_triage_router.py
git commit -m "feat(triage): deterministic router for lab routing mode"
```

---

### Task 5: Fixture seed and validation test

**Files:**
- Create: `backend/tests/fixtures/triage_utterances.jsonl`
- Test: `backend/tests/test_triage_fixtures.py`

- [x] **Step 1: Write the failing validation test**

```python
# backend/tests/test_triage_fixtures.py
"""The fixture file is data the bake-off and the lab depend on; keep it well-formed."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS

FIXTURES = Path(__file__).parent / "fixtures" / "triage_utterances.jsonl"
REQUIRED = {
    "id", "committed", "active", "utterance", "scan_type",
    "expected_action", "expected_is_correction", "expected_needs_committed_edit", "hard", "note",
}


def load_cases() -> list[dict]:
    return [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]


def test_every_line_is_well_formed():
    cases = load_cases()
    assert cases, "fixture file is empty"
    for c in cases:
        assert REQUIRED <= set(c), f"{c.get('id')} missing {REQUIRED - set(c)}"
        assert c["expected_action"] in TRIAGE_ACTIONS, c["id"]
        assert isinstance(c["expected_is_correction"], bool)
        assert isinstance(c["expected_needs_committed_edit"], bool)
        assert isinstance(c["hard"], bool)
        assert c["utterance"].strip()


def test_ids_unique():
    ids = [c["id"] for c in load_cases()]
    assert len(ids) == len(set(ids))


def test_at_least_eight_cases_per_action():
    counts = Counter(c["expected_action"] for c in load_cases())
    for action in TRIAGE_ACTIONS:
        assert counts[action] >= 8, f"{action}: {counts[action]}"
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_triage_fixtures.py -v`
Expected: FAIL with `FileNotFoundError`

- [x] **Step 3: Write the seed fixture file (48 cases, 8 per action)**

```jsonl
{"id": "append-01", "committed": "", "active": "", "utterance": "there is a six millimetre nodule in the right upper lobe", "scan_type": "CT chest", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "first finding into empty scratchpad"}
{"id": "append-02", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "no pleural effusion no pneumothorax", "scan_type": "CT chest", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "run-on negatives"}
{"id": "append-03", "committed": "- 6 mm nodule right upper lobe", "active": "- no pleural effusion", "utterance": "the heart size is normal", "scan_type": "CT chest", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "normality claim with committed context"}
{"id": "append-04", "committed": "", "active": "- liver normal", "utterance": "simple cyst in the upper pole of the left kidney measuring two centimetres", "scan_type": "CT abdomen pelvis", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "new organ finding with measurement"}
{"id": "append-05", "committed": "", "active": "- no acute intracranial haemorrhage", "utterance": "small vessel ischaemic change in the deep white matter", "scan_type": "CT head", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "second finding"}
{"id": "append-06", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "it was five millimetres on the prior now ten millimetres", "scan_type": "CT chest", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "temporal comparison, both values kept — not a correction"}
{"id": "append-07", "committed": "", "active": "- L4 L5 disc bulge", "utterance": "no nerve root compression", "scan_type": "MRI lumbar spine", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "negative statement"}
{"id": "append-08", "committed": "", "active": "- gallbladder wall thickened", "utterance": "pericholecystic fluid is present", "scan_type": "US abdomen", "expected_action": "append_new_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "adds a descriptor to a related but distinct observation"}
{"id": "correct-01", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "actually make that the left upper lobe", "scan_type": "CT chest", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "explicit actually"}
{"id": "correct-02", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "sorry eight millimetres", "scan_type": "CT chest", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "sorry + bare value"}
{"id": "correct-03", "committed": "", "active": "- simple cyst left kidney 2 cm", "utterance": "no I mean the right kidney", "scan_type": "CT abdomen pelvis", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "no I mean"}
{"id": "correct-04", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "it's not six millimetres it's ten millimetres", "scan_type": "CT chest", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": true, "note": "not X it's Y — correction not comparison"}
{"id": "correct-05", "committed": "- 12 mm hypodense lesion segment 7 of the liver", "active": "- no free fluid", "utterance": "change the liver lesion to say hepatic haemangioma", "scan_type": "CT abdomen pelvis", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": true, "hard": false, "note": "directed at committed zone"}
{"id": "correct-06", "committed": "- 6 mm nodule right upper lobe", "active": "- no pleural effusion", "utterance": "correction the nodule is in the right lower lobe", "scan_type": "CT chest", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": true, "hard": true, "note": "committed edit signalled by the word correction"}
{"id": "correct-07", "committed": "", "active": "- moderate hydronephrosis right kidney", "utterance": "mild not moderate", "scan_type": "US renal", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": true, "note": "terse descriptor swap"}
{"id": "correct-08", "committed": "", "active": "- disc protrusion L5 S1", "utterance": "make that L4 L5", "scan_type": "MRI lumbar spine", "expected_action": "correct_previous_finding", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "level correction"}
{"id": "restate-01", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "there is a six millimetre nodule in the right upper lobe", "scan_type": "CT chest", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "verbatim repeat"}
{"id": "restate-02", "committed": "", "active": "- no pleural effusion", "utterance": "no effusion", "scan_type": "CT chest", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "shortened repeat"}
{"id": "restate-03", "committed": "- liver normal", "active": "- spleen normal", "utterance": "the liver is normal", "scan_type": "CT abdomen pelvis", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "repeat of a committed line"}
{"id": "restate-04", "committed": "", "active": "- simple cyst left kidney 2 cm", "utterance": "so that's a two centimetre simple cyst on the left", "scan_type": "CT abdomen pelvis", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "reworded summary of existing finding"}
{"id": "restate-05", "committed": "", "active": "- no acute intracranial haemorrhage", "utterance": "no haemorrhage", "scan_type": "CT head", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "shortened negative"}
{"id": "restate-06", "committed": "", "active": "- heart size normal", "utterance": "as I said heart size is normal", "scan_type": "CXR", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "explicit as I said"}
{"id": "restate-07", "committed": "", "active": "- 6 mm nodule right upper lobe\n- no pleural effusion", "utterance": "six millimetre right upper lobe nodule", "scan_type": "CT chest", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "reordered words"}
{"id": "restate-08", "committed": "", "active": "- gallbladder wall thickened", "utterance": "thickened gallbladder wall", "scan_type": "US abdomen", "expected_action": "restate_existing_finding", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "reordered"}
{"id": "delete-01", "committed": "", "active": "- 6 mm nodule right upper lobe\n- no pleural effusion", "utterance": "scratch that", "scan_type": "CT chest", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "canonical"}
{"id": "delete-02", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "delete that", "scan_type": "CT chest", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "delete that"}
{"id": "delete-03", "committed": "", "active": "- liver normal\n- spleen enlarged", "utterance": "no scrap that last one", "scan_type": "CT abdomen pelvis", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": true, "note": "scrap that last one"}
{"id": "delete-04", "committed": "", "active": "- no acute haemorrhage\n- mass effect", "utterance": "ignore that", "scan_type": "CT head", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": true, "note": "ignore that = remove previous"}
{"id": "delete-05", "committed": "", "active": "- disc bulge L4 L5", "utterance": "remove that", "scan_type": "MRI lumbar spine", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "remove that"}
{"id": "delete-06", "committed": "", "active": "- 6 mm nodule right upper lobe\n- no pleural effusion", "utterance": "strike that", "scan_type": "CT chest", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "strike that"}
{"id": "delete-07", "committed": "", "active": "- gallbladder wall thickened", "utterance": "scratch that sorry", "scan_type": "US abdomen", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "with trailing sorry"}
{"id": "delete-08", "committed": "", "active": "- heart size normal\n- bibasal atelectasis", "utterance": "delete the last line", "scan_type": "CXR", "expected_action": "delete_previous_utterance", "expected_is_correction": true, "expected_needs_committed_edit": false, "hard": false, "note": "explicit last line"}
{"id": "format-01", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "new paragraph", "scan_type": "CT chest", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "new paragraph"}
{"id": "format-02", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "new line", "scan_type": "CT chest", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "new line"}
{"id": "format-03", "committed": "", "active": "- liver normal", "utterance": "full stop", "scan_type": "CT abdomen pelvis", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "full stop"}
{"id": "format-04", "committed": "", "active": "- liver normal", "utterance": "next paragraph", "scan_type": "CT abdomen pelvis", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "variant phrasing"}
{"id": "format-05", "committed": "", "active": "- no acute haemorrhage", "utterance": "new heading impression", "scan_type": "CT head", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "heading command"}
{"id": "format-06", "committed": "", "active": "- disc bulge L4 L5", "utterance": "paragraph", "scan_type": "MRI lumbar spine", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "bare paragraph"}
{"id": "format-07", "committed": "", "active": "- heart size normal", "utterance": "comma", "scan_type": "CXR", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "punctuation"}
{"id": "format-08", "committed": "", "active": "- gallbladder wall thickened", "utterance": "new line please", "scan_type": "US abdomen", "expected_action": "formatting_command", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "polite form"}
{"id": "noise-01", "committed": "", "active": "- 6 mm nodule right upper lobe", "utterance": "um so er let me see", "scan_type": "CT chest", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "filler"}
{"id": "noise-02", "committed": "", "active": "- liver normal", "utterance": "hang on a second", "scan_type": "CT abdomen pelvis", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "aside"}
{"id": "noise-03", "committed": "", "active": "- no acute haemorrhage", "utterance": "right okay", "scan_type": "CT head", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "right as discourse marker, not laterality"}
{"id": "noise-04", "committed": "", "active": "- disc bulge L4 L5", "utterance": "let me just scroll down", "scan_type": "MRI lumbar spine", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "workstation talk"}
{"id": "noise-05", "committed": "", "active": "- heart size normal", "utterance": "where's the comparison", "scan_type": "CXR", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "question to self"}
{"id": "noise-06", "committed": "", "active": "", "utterance": "testing testing", "scan_type": "CT chest", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "mic check"}
{"id": "noise-07", "committed": "", "active": "- gallbladder wall thickened", "utterance": "hmm", "scan_type": "US abdomen", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": false, "note": "single filler"}
{"id": "noise-08", "committed": "", "active": "- liver normal", "utterance": "yeah can you close the door", "scan_type": "CT abdomen pelvis", "expected_action": "ignore_noise", "expected_is_correction": false, "expected_needs_committed_edit": false, "hard": true, "note": "speech to a colleague"}
```

Save exactly these lines to `backend/tests/fixtures/triage_utterances.jsonl` (create the `fixtures` directory). The lab's export buffer appends more later.

- [x] **Step 4: Run the validation tests**

Run: `cd backend && .venv/bin/pytest tests/test_triage_fixtures.py -v`
Expected: 3 PASS

- [x] **Step 5: Commit**

```bash
git add backend/tests/fixtures/triage_utterances.jsonl backend/tests/test_triage_fixtures.py
git commit -m "test(triage): seed fixture set, 8 cases per action, with validation"
```

---

### Task 6: Canvas route — request/response fields, flags, and the three modes

**Files:**
- Modify: `backend/src/rapid_reports_ai/canvas_routes.py` (imports at lines 1-20; models at 42-73; `process_transcript` at 695-755)
- Modify: `backend/.env.example` (append two lines)
- Test: `backend/tests/test_canvas_triage_modes.py`

- [x] **Step 1: Write the failing route tests**

```python
# backend/tests/test_canvas_triage_modes.py
"""Route-level tests for the three triage modes on POST /api/canvas/process.

The live model and both triagers are replaced with fakes. What is under test is
the wiring: which mode runs, that production responses are byte-identical when no
flag is set, that the lab fields are honoured only under RR_TRIAGE_DEBUG, and that
the shadow log carries no utterance text.
"""
from __future__ import annotations

import json
import logging
import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_triage import TriageDecision, TriageError, TriageState
from rapid_reports_ai.main import app

UTTERANCE = "actually make that the left upper lobe"
ACTIVE = "- 6 mm nodule right upper lobe"
BASE = {
    "session_transcript": f"there is a six millimetre nodule in the right upper lobe {UTTERANCE}",
    "scratchpad_content": ACTIVE,
    "scan_type": "CT chest",
    "clinical_history": "",
    "mode": "clean",
}


@pytest.fixture
def authed_client(client, db_session):
    user = User(
        id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x",
        full_name="Test Radiologist", is_active=True, is_verified=True, is_approved=True,
    )
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class FakeTriager:
    def __init__(self, name, action="correct_previous_finding", confidence=0.97, raise_=False):
        self.name = name
        self.action = action
        self.confidence = confidence
        self.raise_ = raise_
        self.calls: list[TriageState] = []

    async def classify(self, state):
        self.calls.append(state)
        if self.raise_:
            raise TriageError("boom")
        return TriageDecision(
            candidate=self.name, action=self.action, confidence=self.confidence if self.name == "jev" else None,
            probabilities=None, is_correction=0.9, needs_committed_edit=0.1, latency_ms=5, input_tokens=None, cost_usd=None,
        )


@pytest.fixture
def fakes(monkeypatch):
    jev = FakeTriager("jev")
    qwen = FakeTriager("qwen")
    monkeypatch.setattr(cr, "get_triager", lambda name: {"jev": jev, "qwen": qwen}[name])
    return jev, qwen


@pytest.fixture
def live(monkeypatch):
    calls = []

    async def fake_live(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings, use_thinking=False, label="canvas"):
        calls.append(label)
        return output_type(scratchpad=ACTIVE.replace("right", "left"), covered_sections=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", fake_live)
    return calls


def _post(client, **extra):
    return client.post("/api/canvas/process", json={**BASE, **extra})


# --- no flags: production behaviour --------------------------------------------

def test_no_flags_ignores_lab_fields_and_calls_no_triager(authed_client, fakes, live, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.delenv("RR_TRIAGE_SHADOW", raising=False)
    plain = _post(authed_client).json()
    with_fields = _post(
        authed_client, last_utterance=UTTERANCE, triage_debug=True,
        triage_route={"candidate": "jev", "threshold": 0.5},
    ).json()
    assert plain == with_fields
    assert "triage" not in plain or plain["triage"] is None
    jev, qwen = fakes
    assert jev.calls == [] and qwen.calls == []
    assert live == ["canvas.process", "canvas.process"]


# --- shadow --------------------------------------------------------------------

def test_shadow_runs_both_and_logs_without_text(authed_client, fakes, live, monkeypatch, caplog):
    monkeypatch.setenv("RR_TRIAGE_SHADOW", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.canvas_routes")

    r = _post(authed_client, last_utterance=UTTERANCE)
    assert r.status_code == 200
    body = r.json()
    assert body.get("triage") is None
    assert body["scratchpad"] == ACTIVE.replace("right", "left")

    jev, qwen = fakes
    assert len(jev.calls) == 1 and len(qwen.calls) == 1
    st = jev.calls[0]
    assert st.latest_utterance == UTTERANCE and st.active == ACTIVE and st.committed == ""

    records = [rec.getMessage() for rec in caplog.records if "canvas.triage.shadow" in rec.getMessage()]
    assert len(records) == 1
    payload = json.loads(records[0].split(" ", 1)[1])
    assert payload["derived"] == "correct"
    assert payload["jev"]["action"] == "correct_previous_finding" and payload["jev"]["agrees"] is True
    assert payload["utterance_len"] == len(UTTERANCE)
    assert UTTERANCE not in records[0]
    assert ACTIVE not in records[0]


def test_shadow_jev_error_is_recorded_and_qwen_still_logged(authed_client, fakes, live, monkeypatch, caplog):
    monkeypatch.setenv("RR_TRIAGE_SHADOW", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.canvas_routes")
    jev, qwen = fakes
    jev.raise_ = True

    r = _post(authed_client, last_utterance=UTTERANCE)
    assert r.status_code == 200
    payload = json.loads([m.getMessage() for m in caplog.records if "canvas.triage.shadow" in m.getMessage()][0].split(" ", 1)[1])
    assert payload["jev"]["error"] == "TriageError" and payload["jev"]["action"] is None
    assert payload["qwen"]["action"] == "correct_previous_finding"


def test_shadow_without_utterance_calls_nothing(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_SHADOW", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    _post(authed_client)
    jev, qwen = fakes
    assert jev.calls == [] and qwen.calls == []


# --- debug ---------------------------------------------------------------------

def test_debug_attaches_both_candidates_and_derived(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    r = _post(authed_client, last_utterance=UTTERANCE, triage_debug=True)
    body = r.json()
    assert body["scratchpad"] == ACTIVE.replace("right", "left")
    t = body["triage"]
    assert t["mode"] == "debug" and t["routed"] == "model"
    assert t["derived"] == "correct"
    assert t["jev"]["action"] == "correct_previous_finding" and t["jev"]["confidence"] == 0.97
    assert t["qwen"]["action"] == "correct_previous_finding" and t["qwen"]["confidence"] is None
    assert isinstance(t["live_latency_ms"], int)


# --- route ---------------------------------------------------------------------

def test_route_deterministic_skips_live_model(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, qwen = fakes
    jev.action = "delete_previous_utterance"
    r = _post(
        authed_client, last_utterance="scratch that",
        scratchpad_content=ACTIVE + "\n- no pleural effusion",
        triage_route={"candidate": "jev", "threshold": 0.9},
    )
    body = r.json()
    assert body["scratchpad"] == ACTIVE
    assert body["covered_sections"] == []
    t = body["triage"]
    assert t["mode"] == "route" and t["routed"] == "deterministic" and t["routed_by"] == "jev"
    assert t["jev"]["action"] == "delete_previous_utterance"
    assert t["qwen"] is None
    assert live == []
    assert qwen.calls == []


def test_route_below_threshold_falls_to_model(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, _ = fakes
    jev.action, jev.confidence = "ignore_noise", 0.4
    body = _post(authed_client, last_utterance="um", triage_route={"candidate": "jev", "threshold": 0.9}).json()
    assert body["triage"]["routed"] == "model"
    assert body["triage"]["jev"]["action"] == "ignore_noise"
    assert live == ["canvas.process"]


def test_route_triager_error_falls_to_model(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, _ = fakes
    jev.raise_ = True
    body = _post(authed_client, last_utterance="um", triage_route={"candidate": "jev", "threshold": 0.9}).json()
    assert body["triage"]["routed"] == "model"
    assert body["triage"]["jev"]["error"] == "TriageError"
    assert live == ["canvas.process"]


def test_route_plus_debug_runs_other_candidate_only_once(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, qwen = fakes
    body = _post(
        authed_client, last_utterance=UTTERANCE, triage_debug=True,
        triage_route={"candidate": "jev", "threshold": 0.9},
    ).json()
    assert body["triage"]["routed"] == "model"
    assert body["triage"]["jev"]["action"] and body["triage"]["qwen"]["action"]
    assert len(jev.calls) == 1 and len(qwen.calls) == 1


# --- fixtures endpoint ----------------------------------------------------------

def test_fixtures_endpoint_gated(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert authed_client.get("/api/canvas/triage/fixtures").status_code == 404
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    r = authed_client.get("/api/canvas/triage/fixtures")
    assert r.status_code == 200
    cases = r.json()["cases"]
    assert cases and {"id", "utterance", "expected_action"} <= set(cases[0])
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_canvas_triage_modes.py -v`
Expected: FAIL — `AttributeError: module 'rapid_reports_ai.canvas_routes' has no attribute 'get_triager'` (from the `fakes` fixture) and 404 for the fixtures route.

- [x] **Step 3: Add imports and models**

In `backend/src/rapid_reports_ai/canvas_routes.py`, replace the import block (lines 1-20) with:

```python
"""Canvas routes for intelligent dictation — section generation and transcript processing."""

import asyncio
import hashlib
import json
import logging
import os
import time as _time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import get_current_user
from .database.models import User
from .dictation_triage import (
    TriageDecision,
    TriageState,
    TriageTrace,
    decision_to_trace,
    get_triager,
)
from .dictation_triage_labels import agrees, derive_action
from .dictation_triage_router import route as triage_route_decision
from .enhancement_utils import (
    MODEL_CONFIG,
    _get_api_key_for_provider,
    _get_model_provider,
    _run_agent_with_model,
)

logger = logging.getLogger(__name__)

canvas_router = APIRouter(prefix="/api/canvas", tags=["canvas"])
```

Replace `CanvasProcessRequest` (lines 42-51) with:

```python
class TriageRouteConfig(BaseModel):
    candidate: Literal["jev", "qwen"]
    threshold: float = Field(0.9, ge=0.0, le=1.0)


class CanvasProcessRequest(BaseModel):
    session_transcript: str
    scratchpad_content: str
    scan_type: str = ""
    clinical_history: str = ""
    preferred_section_names: list[str] = []
    mode: str = "clean"  # "clean" (Verbatim Clean, default) | "structured"
    # Incremental mode: when set, scratchpad_content is the ACTIVE tail and
    # committed_context is the FROZEN prefix (read-only). Absent => full regeneration.
    committed_context: str | None = None
    # Trimmed transcript delta since the previous process call. Feeds triage only;
    # never affects the live response.
    last_utterance: str | None = None
    # Lab-only (honoured under RR_TRIAGE_DEBUG=1): attach both candidates' decisions.
    triage_debug: bool = False
    # Lab-only (honoured under RR_TRIAGE_DEBUG=1): act on the selected candidate.
    triage_route: TriageRouteConfig | None = None
```

Add `triage: Optional[TriageTrace] = None` as the last field of both `CanvasProcessResponse` and `CanvasIncrementalResponse`:

```python
class CanvasProcessResponse(BaseModel):
    scratchpad: str
    covered_sections: list[str] = []
    triage: Optional[TriageTrace] = None


class CanvasIncrementalResponse(BaseModel):
    active_scratchpad: str
    committed_edits: list[CommittedEdit] = []
    triage: Optional[TriageTrace] = None
```

- [x] **Step 4: Add the flag helpers and mode helpers just above `@canvas_router.post("/process")`**

```python
# -----------------------------------------------------------------------------
# Triage modes (spec 2026-09-24-jev-dictation-triage-shadow-design.md §5.4)
# -----------------------------------------------------------------------------

_TRIAGE_WARNED: set[str] = set()


def _flag_on(env_name: str) -> bool:
    """A triage flag counts only when set to "1" AND the OpenRouter key exists.
    Warn once per flag when the key is missing so a misconfigured deploy is visible."""
    if os.environ.get(env_name) != "1":
        return False
    if not os.environ.get("OPENROUTER_API_KEY"):
        if env_name not in _TRIAGE_WARNED:
            _TRIAGE_WARNED.add(env_name)
            logger.warning("[canvas.triage] %s=1 but OPENROUTER_API_KEY is unset; mode disabled", env_name)
        return False
    return True


def _triage_debug_enabled() -> bool:
    return _flag_on("RR_TRIAGE_DEBUG")


def _triage_shadow_enabled() -> bool:
    return _flag_on("RR_TRIAGE_SHADOW")


def _triage_state(request: CanvasProcessRequest) -> TriageState:
    return TriageState(
        committed=request.committed_context or "",
        active=request.scratchpad_content or "",
        latest_utterance=request.last_utterance or "",
        scan_type=request.scan_type or "",
    )


async def _classify_safe(name: str, state: TriageState) -> TriageDecision | BaseException:
    try:
        return await get_triager(name).classify(state)
    except Exception as e:  # a triage failure is data, never a request failure
        return e


def _after_and_edits(output, incremental: bool) -> tuple[str, list[tuple[str, str]]]:
    if incremental:
        return output.active_scratchpad, [(e.original, e.corrected) for e in output.committed_edits]
    return output.scratchpad, []


async def _shadow_triage(state: TriageState, before_active: str, output, incremental: bool, mode: str) -> None:
    """Fire-and-forget: both candidates, derived label, one JSON log line, no text."""
    try:
        jev, qwen = await asyncio.gather(_classify_safe("jev", state), _classify_safe("qwen", state))
        after, edits = _after_and_edits(output, incremental)
        derived = derive_action(before_active, after, edits)

        def slot(result):
            t = decision_to_trace(result).model_dump()
            t["agrees"] = agrees(t["action"], derived) if t["action"] else None
            return t

        payload = {
            "event": "canvas.triage.shadow",
            "mode": mode,
            "incremental": incremental,
            "utterance_len": len(state.latest_utterance),
            "utterance_sha8": hashlib.sha256(state.latest_utterance.encode()).hexdigest()[:8],
            "derived": derived,
            "jev": slot(jev),
            "qwen": slot(qwen),
        }
        logger.info("[canvas.triage.shadow] %s", json.dumps(payload))
    except Exception as e:
        logger.error("[canvas.triage.shadow] ❌ %s: %s", type(e).__name__, e)


async def _run_live_or_fallback(request: CanvasProcessRequest, incremental: bool):
    """The live path exactly as before this change, including its degrade-to-input behaviour."""
    primary_model = MODEL_CONFIG["CANVAS_PROCESS"]
    fallback_model = MODEL_CONFIG.get("CANVAS_PROCESS_FALLBACK")
    system_prompt, model_settings = _canvas_process_config(request.mode, incremental=incremental)

    if incremental:
        user_prompt = CANVAS_INCREMENTAL_USER_PROMPT_TEMPLATE.format(
            scan_type=request.scan_type or "(not specified)",
            clinical_history=request.clinical_history or "(not specified)",
            committed_context=request.committed_context,
            active_scratchpad=request.scratchpad_content,
            session_transcript=request.session_transcript,
        )
        output_type = CanvasIncrementalResponse
    else:
        user_prompt = CANVAS_PROCESS_USER_PROMPT_TEMPLATE.format(
            scan_type=request.scan_type or "(not specified)",
            clinical_history=request.clinical_history or "(not specified)",
            scratchpad_content=request.scratchpad_content,
            session_transcript=request.session_transcript,
        )
        output_type = CanvasProcessResponse

    t0 = _time.perf_counter()
    try:
        output = await _run_canvas_with_fallback(
            primary_model,
            fallback_model,
            output_type=output_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_settings=model_settings,
            use_thinking=False,
            label="canvas.process",
        )
        elapsed = _time.perf_counter() - t0
        logger.info(
            "[canvas.process] %.2fs mode=%s incremental=%s primary=%s active_chars=%d committed_chars=%d",
            elapsed, request.mode, incremental, primary_model,
            len(request.scratchpad_content or ""), len(request.committed_context or ""),
        )
        return output
    except Exception as e:
        elapsed = _time.perf_counter() - t0
        import traceback
        logger.error("[canvas.process] ❌ %.2fs all models failed %s: %s", elapsed, type(e).__name__, e)
        traceback.print_exc()
        if incremental:
            return CanvasIncrementalResponse(active_scratchpad=request.scratchpad_content, committed_edits=[])
        return CanvasProcessResponse(scratchpad=request.scratchpad_content, covered_sections=[])


def _deterministic_response(request: CanvasProcessRequest, incremental: bool, new_active: str, trace: TriageTrace):
    if incremental:
        return CanvasIncrementalResponse(active_scratchpad=new_active, committed_edits=[], triage=trace)
    return CanvasProcessResponse(scratchpad=new_active, covered_sections=[], triage=trace)
```

- [x] **Step 5: Replace `process_transcript` (the whole function from `@canvas_router.post("/process")` to just before `@canvas_router.post("/review", ...)`)**

```python
@canvas_router.post("/process")
async def process_transcript(
    request: CanvasProcessRequest,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Process the session transcript and return the updated scratchpad.

    Three optional, env-gated triage modes ride on top (spec §5.4):
      route  — lab only: the selected candidate may short-circuit the live model
      debug  — lab only: both candidates' decisions are attached to the response
      shadow — production: both candidates run after the response (BackgroundTasks), log-only
    Without flags this function is behaviourally identical to before.
    """
    incremental = request.committed_context is not None
    lab = _triage_debug_enabled() and bool(request.last_utterance)
    state = _triage_state(request) if request.last_utterance else None
    before_active = request.scratchpad_content or ""

    # --- route mode -------------------------------------------------------------
    route_result: TriageDecision | BaseException | None = None
    route_cfg = request.triage_route if lab else None
    if route_cfg and state is not None:
        route_result = await _classify_safe(route_cfg.candidate, state)
        if isinstance(route_result, TriageDecision):
            kind, new_active = triage_route_decision(route_result, route_cfg.threshold, state)
            if kind == "deterministic" and new_active is not None:
                trace = TriageTrace(
                    mode="route", routed="deterministic", routed_by=route_cfg.candidate,
                    **{route_cfg.candidate: decision_to_trace(route_result)},
                )
                logger.info("[canvas.triage.route] deterministic %s by %s", route_result.action, route_cfg.candidate)
                return _deterministic_response(request, incremental, new_active, trace)

    # --- live call (+ debug candidates concurrently) ----------------------------
    debug = lab and request.triage_debug and state is not None
    t0 = _time.perf_counter()
    if debug:
        already = {route_cfg.candidate} if route_cfg and route_result is not None else set()
        names = [n for n in ("jev", "qwen") if n not in already]
        results = await asyncio.gather(
            _run_live_or_fallback(request, incremental),
            *(_classify_safe(n, state) for n in names),
        )
        output, candidate_results = results[0], dict(zip(names, results[1:]))
    else:
        output = await _run_live_or_fallback(request, incremental)
        candidate_results = {}
    live_latency_ms = int((_time.perf_counter() - t0) * 1000)

    if lab and (debug or route_cfg):
        if route_cfg and route_result is not None:
            candidate_results[route_cfg.candidate] = route_result
        after, edits = _after_and_edits(output, incremental)
        output.triage = TriageTrace(
            mode="route" if route_cfg else "debug",
            derived=derive_action(before_active, after, edits),
            routed="model",
            routed_by=route_cfg.candidate if route_cfg else None,
            live_latency_ms=live_latency_ms,
            jev=decision_to_trace(candidate_results["jev"]) if "jev" in candidate_results else None,
            qwen=decision_to_trace(candidate_results["qwen"]) if "qwen" in candidate_results else None,
        )
    elif state is not None and _triage_shadow_enabled():
        # BackgroundTasks: runs after the response is sent in production (zero added
        # latency) and before TestClient returns (deterministic tests). A bare
        # asyncio.create_task would be unreferenced and could be garbage-collected.
        background.add_task(_shadow_triage, state, before_active, output, incremental, request.mode)

    return output


_TRIAGE_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "triage_utterances.jsonl"


@canvas_router.get("/triage/fixtures")
async def triage_fixtures(current_user: User = Depends(get_current_user)):
    """Lab only: the hand-labelled fixture cases, for the feeder. Read-only."""
    if not _triage_debug_enabled() or not _TRIAGE_FIXTURES.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    cases = [json.loads(line) for line in _TRIAGE_FIXTURES.read_text().splitlines() if line.strip()]
    return {"cases": cases}
```

- [x] **Step 6: Document the flags**

Append to `backend/.env.example`:

```
# Dictation triage (spec 2026-09-24). Never set RR_TRIAGE_DEBUG in production.
RR_TRIAGE_SHADOW=0   # 1 = log-only shadow of both triage candidates on /api/canvas/process
RR_TRIAGE_DEBUG=0    # 1 = honour lab fields (triage_debug / triage_route) and serve fixtures
```

- [x] **Step 7: Run the new tests and the existing canvas tests**

Run: `cd backend && .venv/bin/pytest tests/test_canvas_triage_modes.py tests/test_canvas_modes.py tests/test_canvas_incremental.py tests/test_canvas_fallback.py tests/test_canvas_timing.py -v`
Expected: all PASS. If an existing canvas test monkeypatches something inside the old `process_transcript` body, it still works because `_run_canvas_with_fallback` and `_canvas_process_config` kept their names and signatures.

- [x] **Step 8: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/.env.example backend/tests/test_canvas_triage_modes.py
git commit -m "feat(canvas): env-gated triage modes on /process — route, debug, shadow; fixtures endpoint"
```

---

### Task 7: Summary helper, bake-off script, shadow-log report

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/triage_summary.py`
- Create: `backend/src/rapid_reports_ai/scripts/triage_bakeoff.py`
- Create: `backend/src/rapid_reports_ai/scripts/triage_shadow_report.py`
- Test: `backend/tests/test_triage_summary.py`

- [x] **Step 1: Write the failing test for the pure summary**

```python
# backend/tests/test_triage_summary.py
from __future__ import annotations

from rapid_reports_ai.scripts.triage_summary import Record, summarise


def _rec(candidate, expected, action, conf=None, lat=100, hard=False, err=None, ic=None, eic=None):
    return Record(
        id=f"{expected}-{action}", candidate=candidate, expected_action=expected, action=action,
        confidence=conf, latency_ms=lat, cost_usd=0.00002 if candidate == "jev" else None, hard=hard, error=err,
        is_correction=ic, expected_is_correction=eic, needs_committed_edit=None, expected_needs_committed_edit=None,
    )


def test_summarise_accuracy_latency_and_buckets():
    records = [
        _rec("jev", "ignore_noise", "ignore_noise", 0.99, 200),
        _rec("jev", "ignore_noise", "append_new_finding", 0.6, 300),
        _rec("jev", "append_new_finding", "append_new_finding", 0.97, 250, hard=True),
        _rec("jev", "append_new_finding", None, None, 0, err="TriageError"),
        _rec("qwen", "ignore_noise", "ignore_noise", None, 700),
        _rec("qwen", "ignore_noise", "ignore_noise", None, 900),
    ]
    s = summarise(records)

    jev = s["jev"]
    assert jev["n"] == 4 and jev["errors"] == 1
    assert jev["accuracy"] == 2 / 3                       # errors excluded from accuracy
    assert jev["per_action"]["ignore_noise"]["recall"] == 0.5
    assert jev["per_action"]["append_new_finding"]["precision"] == 0.5
    assert jev["confusion"]["ignore_noise"]["append_new_finding"] == 1
    assert jev["latency_p50_ms"] == 250 and jev["latency_p95_ms"] == 300
    assert jev["cost_usd"] == 0.00008
    assert jev["hard"]["n"] == 1 and jev["hard"]["accuracy"] == 1.0
    assert jev["confidence_buckets"][">=0.95"] == {"n": 2, "accuracy": 1.0, "coverage": 2 / 3}
    assert jev["confidence_buckets"]["0.5-0.8"] == {"n": 1, "accuracy": 0.0, "coverage": 1 / 3}

    qwen = s["qwen"]
    assert qwen["accuracy"] == 1.0 and "confidence_buckets" not in qwen
    assert qwen["latency_p50_ms"] == 800


def test_summarise_aux_signals_at_half():
    records = [
        _rec("jev", "correct_previous_finding", "correct_previous_finding", 0.9, ic=0.8, eic=True),
        _rec("jev", "append_new_finding", "append_new_finding", 0.9, ic=0.6, eic=False),
    ]
    assert summarise(records)["jev"]["is_correction_accuracy"] == 0.5
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_triage_summary.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement the summary module**

```python
# backend/src/rapid_reports_ai/scripts/triage_summary.py
"""Pure summary of triage records. Shared by the bake-off (fixture labels) and the
shadow report (derived labels) so both print the same shape."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any, Optional

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS

BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<0.5", 0.0, 0.5),
    ("0.5-0.8", 0.5, 0.8),
    ("0.8-0.95", 0.8, 0.95),
    (">=0.95", 0.95, 1.01),
)


@dataclass(frozen=True)
class Record:
    id: str
    candidate: str
    expected_action: str
    action: Optional[str]
    confidence: Optional[float]
    latency_ms: int
    cost_usd: Optional[float]
    hard: bool
    error: Optional[str]
    is_correction: Optional[float]
    expected_is_correction: Optional[bool]
    needs_committed_edit: Optional[float]
    expected_needs_committed_edit: Optional[bool]


def _p(values: list[int], q: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return s[idx]


def _acc(records: list[Record]) -> float:
    return sum(r.action == r.expected_action for r in records) / len(records) if records else 0.0


def _aux(records: list[Record], value_attr: str, expected_attr: str) -> Optional[float]:
    pairs = [(getattr(r, value_attr), getattr(r, expected_attr)) for r in records]
    pairs = [(v, e) for v, e in pairs if v is not None and e is not None]
    if not pairs:
        return None
    return sum((v >= 0.5) == e for v, e in pairs) / len(pairs)


def _candidate_summary(records: list[Record]) -> dict[str, Any]:
    ok = [r for r in records if r.error is None and r.action is not None]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in ok:
        confusion[r.expected_action][r.action] += 1
    per_action = {}
    for a in TRIAGE_ACTIONS:
        tp = confusion[a][a]
        fn = sum(confusion[a].values()) - tp
        fp = sum(confusion[x][a] for x in TRIAGE_ACTIONS if x != a)
        per_action[a] = {
            "n": tp + fn,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
        }
    lat = [r.latency_ms for r in ok]
    hard = [r for r in ok if r.hard]
    out: dict[str, Any] = {
        "n": len(records),
        "errors": len(records) - len(ok),
        "accuracy": _acc(ok),
        "per_action": per_action,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "latency_p50_ms": int(median(lat)) if lat else 0,
        "latency_p95_ms": _p(lat, 0.95),
        "cost_usd": round(sum(r.cost_usd or 0.0 for r in records), 8),
        "hard": {"n": len(hard), "accuracy": _acc(hard)},
        "is_correction_accuracy": _aux(ok, "is_correction", "expected_is_correction"),
        "needs_committed_edit_accuracy": _aux(ok, "needs_committed_edit", "expected_needs_committed_edit"),
    }
    with_conf = [r for r in ok if r.confidence is not None]
    if with_conf:
        buckets = {}
        for name, lo, hi in BUCKETS:
            rs = [r for r in with_conf if lo <= r.confidence < hi]
            buckets[name] = {"n": len(rs), "accuracy": _acc(rs), "coverage": len(rs) / len(with_conf)}
        out["confidence_buckets"] = buckets
    return out


def summarise(records: list[Record]) -> dict[str, dict[str, Any]]:
    by: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        by[r.candidate].append(r)
    return {c: _candidate_summary(rs) for c, rs in by.items()}


def format_summary(summary: dict[str, dict[str, Any]]) -> str:
    lines = []
    for cand, s in summary.items():
        lines.append(f"== {cand}: n={s['n']} errors={s['errors']} accuracy={s['accuracy']:.3f} "
                     f"p50={s['latency_p50_ms']}ms p95={s['latency_p95_ms']}ms cost=${s['cost_usd']:.5f}")
        lines.append(f"   hard: n={s['hard']['n']} accuracy={s['hard']['accuracy']:.3f}   "
                     f"is_correction@0.5={s['is_correction_accuracy']}  needs_committed_edit@0.5={s['needs_committed_edit_accuracy']}")
        for a, m in s["per_action"].items():
            lines.append(f"   {a:<28} n={m['n']:<3} recall={m['recall']} precision={m['precision']}")
        if "confidence_buckets" in s:
            for b, m in s["confidence_buckets"].items():
                lines.append(f"   conf {b:<8} n={m['n']:<3} accuracy={m['accuracy']:.3f} coverage={m['coverage']:.2f}")
    return "\n".join(lines)
```

- [x] **Step 4: Run the summary tests**

Run: `cd backend && .venv/bin/pytest tests/test_triage_summary.py -v`
Expected: 2 PASS

- [x] **Step 5: Write the bake-off script**

```python
# backend/src/rapid_reports_ai/scripts/triage_bakeoff.py
"""Run the fixture set through both triage candidates, live, and print/save a summary.

Usage (from backend/, keys in .env):
    set -a; . ./.env; set +a
    .venv/bin/python -m rapid_reports_ai.scripts.triage_bakeoff [--only jev|qwen] [--concurrency 4]

Never run by pytest. Writes docs/model-migration/triage-bakeoff-<date>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from rapid_reports_ai.dictation_triage import TriageState, get_triager
from rapid_reports_ai.scripts.triage_summary import Record, format_summary, summarise

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "triage_utterances.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"


def load_cases() -> list[dict]:
    return [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]


async def run_case(case: dict, candidates: list[str], sem: asyncio.Semaphore) -> list[Record]:
    state = TriageState(case["committed"], case["active"], case["utterance"], case.get("scan_type", ""))
    out: list[Record] = []
    async with sem:
        for cand in candidates:  # sequential per case so the two latencies are not contended
            try:
                d = await get_triager(cand).classify(state)
                out.append(Record(
                    id=case["id"], candidate=cand, expected_action=case["expected_action"], action=d.action,
                    confidence=d.confidence, latency_ms=d.latency_ms, cost_usd=d.cost_usd, hard=case["hard"], error=None,
                    is_correction=d.is_correction, expected_is_correction=case["expected_is_correction"],
                    needs_committed_edit=d.needs_committed_edit, expected_needs_committed_edit=case["expected_needs_committed_edit"],
                ))
            except Exception as e:
                out.append(Record(
                    id=case["id"], candidate=cand, expected_action=case["expected_action"], action=None,
                    confidence=None, latency_ms=0, cost_usd=None, hard=case["hard"], error=type(e).__name__,
                    is_correction=None, expected_is_correction=None, needs_committed_edit=None, expected_needs_committed_edit=None,
                ))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["jev", "qwen"])
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    missing = [k for k in ("OPENROUTER_API_KEY", "CEREBRAS_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 2

    candidates = [args.only] if args.only else ["jev", "qwen"]
    cases = load_cases()
    sem = asyncio.Semaphore(args.concurrency)
    nested = await asyncio.gather(*(run_case(c, candidates, sem) for c in cases))
    records = [r for rs in nested for r in rs]

    summary = summarise(records)
    print(format_summary(summary))
    wrong = [r for r in records if r.error is None and r.action != r.expected_action]
    if wrong:
        print("\n-- disagreements --")
        for r in wrong:
            print(f"   {r.candidate:<4} {r.id:<14} expected={r.expected_action:<26} got={r.action} conf={r.confidence}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"triage-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": summary, "records": [r.__dict__ for r in records]}, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [x] **Step 6: Write the shadow-log report**

```python
# backend/src/rapid_reports_ai/scripts/triage_shadow_report.py
"""Summarise a dump of production logs containing canvas.triage.shadow lines.

Usage:
    railway logs ... > /tmp/shadow.log
    .venv/bin/python -m rapid_reports_ai.scripts.triage_shadow_report /tmp/shadow.log

Labels come from the derived action, so 'expected_action' here is the derived
label and accuracy means agreement (lenient by construction; see AGREEMENT_MAP).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rapid_reports_ai.scripts.triage_summary import Record, format_summary, summarise

MARK = "[canvas.triage.shadow] "


def parse_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        i = line.find(MARK)
        if i == -1:
            continue
        try:
            out.append(json.loads(line[i + len(MARK):]))
        except json.JSONDecodeError:
            continue
    return out


def to_records(events: list[dict]) -> list[Record]:
    records: list[Record] = []
    for n, ev in enumerate(events):
        for cand in ("jev", "qwen"):
            slot = ev.get(cand) or {}
            # 'agrees' already encodes the lenient map; represent agreement as a match.
            expected = slot.get("action") if slot.get("agrees") else f"derived:{ev.get('derived')}"
            records.append(Record(
                id=f"{n}-{ev.get('utterance_sha8')}", candidate=cand, expected_action=expected or "",
                action=slot.get("action"), confidence=slot.get("confidence"), latency_ms=slot.get("latency_ms") or 0,
                cost_usd=slot.get("cost_usd"), hard=False, error=slot.get("error"),
                is_correction=None, expected_is_correction=None, needs_committed_edit=None, expected_needs_committed_edit=None,
            ))
    return records


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: triage_shadow_report <logfile>", file=sys.stderr)
        return 2
    events = parse_lines(Path(argv[1]).read_text())
    print(f"{len(events)} shadow events")
    print(format_summary(summarise(to_records(events))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [x] **Step 7: Smoke the scripts import cleanly (no network)**

Run: `cd backend && .venv/bin/python -c "import rapid_reports_ai.scripts.triage_bakeoff, rapid_reports_ai.scripts.triage_shadow_report; print('ok')"`
Expected: `ok`

- [x] **Step 8: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/triage_summary.py backend/src/rapid_reports_ai/scripts/triage_bakeoff.py backend/src/rapid_reports_ai/scripts/triage_shadow_report.py backend/tests/test_triage_summary.py
git commit -m "feat(triage): bake-off script, shadow-log report, shared summary"
```

---

### Task 8: Opt-in live contract test

**Files:**
- Test: `backend/tests/test_dictation_triage_live.py`

- [x] **Step 1: Write the test**

```python
# backend/tests/test_dictation_triage_live.py
"""Documents the real wire contract. Skipped unless RR_LIVE_TESTS=1 and a key exists.
Asserts shape only — answers are the bake-off's job."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS, JevTriager, TriageState

pytestmark = pytest.mark.skipif(
    os.environ.get("RR_LIVE_TESTS") != "1" or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live test: set RR_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)

FIXTURES = Path(__file__).parent / "fixtures" / "triage_utterances.jsonl"


async def test_jev_live_shape_on_first_five_fixtures():
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()][:5]
    triager = JevTriager()
    for c in cases:
        d = await triager.classify(TriageState(c["committed"], c["active"], c["utterance"], c["scan_type"]))
        assert d.action in TRIAGE_ACTIONS
        assert 0.0 <= d.confidence <= 1.0
        assert abs(sum(d.probabilities.values()) - 1.0) < 0.02
        assert 0.0 <= d.is_correction <= 1.0 and 0.0 <= d.needs_committed_edit <= 1.0
        assert d.latency_ms < 3000
```

- [x] **Step 2: Run skipped, then run live once**

Run: `cd backend && .venv/bin/pytest tests/test_dictation_triage_live.py -v`
Expected: `1 skipped`

Run: `cd backend && set -a && . ./.env && set +a && RR_LIVE_TESTS=1 .venv/bin/pytest tests/test_dictation_triage_live.py -v`
Expected: `1 passed` (network). If `.env` has lines the shell cannot source, export `OPENROUTER_API_KEY` directly instead.

- [x] **Step 3: Commit**

```bash
git add backend/tests/test_dictation_triage_live.py
git commit -m "test(triage): opt-in live contract test against Jev"
```

- [x] **Step 4: Run the whole backend suite once before moving to the frontend**

Run: `cd backend && .venv/bin/pytest -q`
Expected: all pass (live test skipped).

---

### Task 9: Frontend pure lab helpers (types, delta, config, export, summary)

**Files:**
- Create: `frontend/src/lib/dictation-lab/types.ts`
- Create: `frontend/src/lib/dictation-lab/delta.ts`, `delta.test.ts`
- Create: `frontend/src/lib/dictation-lab/labConfig.ts`, `labConfig.test.ts`
- Create: `frontend/src/lib/dictation-lab/fixtureExport.ts`, `fixtureExport.test.ts`
- Create: `frontend/src/lib/dictation-lab/summary.ts`, `summary.test.ts`

These are plain TS so the vitest "server" project (node, no browser) runs them: `cd frontend && bun run test -- --project server`.

- [x] **Step 1: Types**

```ts
// frontend/src/lib/dictation-lab/types.ts
/** Mirrors backend dictation_triage.TriageAction. */
export type TriageAction =
	| 'append_new_finding'
	| 'correct_previous_finding'
	| 'restate_existing_finding'
	| 'delete_previous_utterance'
	| 'formatting_command'
	| 'ignore_noise';

export const TRIAGE_ACTIONS: TriageAction[] = [
	'append_new_finding',
	'correct_previous_finding',
	'restate_existing_finding',
	'delete_previous_utterance',
	'formatting_command',
	'ignore_noise'
];

export type Candidate = 'jev' | 'qwen';
export type Strategy = 'shadow' | 'route:jev' | 'route:qwen';

export interface LabConfig {
	strategy: Strategy;
	threshold: number; // 0.5–1.0
	showBoth: boolean; // sets triage_debug
}

/** Fields merged into the /api/canvas/process body. Mirrors CanvasProcessRequest. */
export interface LabRequestFields {
	triage_debug: boolean;
	triage_route: { candidate: Candidate; threshold: number } | null;
}

/** Mirrors backend TriageCandidateTrace. */
export interface TriageCandidateTrace {
	action: TriageAction | null;
	confidence: number | null;
	probabilities: Record<string, number> | null;
	is_correction: number | null;
	needs_committed_edit: number | null;
	latency_ms: number | null;
	input_tokens: number | null;
	cost_usd: number | null;
	error: string | null;
}

/** Mirrors backend TriageTrace. */
export interface TriageTrace {
	mode: 'debug' | 'route';
	derived: 'append' | 'correct' | 'delete' | 'noop' | 'committed_edit' | null;
	routed: 'deterministic' | 'model' | null;
	routed_by: Candidate | null;
	live_latency_ms: number | null;
	jev: TriageCandidateTrace | null;
	qwen: TriageCandidateTrace | null;
}

/** One completed /process call, as reported by DictationScratchpad.onProcessTrace. */
export interface ProcessTrace {
	seq: number;
	at: number; // Date.now()
	utterance: string;
	committed: string;
	activeBefore: string;
	activeAfter: string;
	scanType: string;
	latency_ms: number;
	triage: TriageTrace | null;
}

/** One line of tests/fixtures/triage_utterances.jsonl. */
export interface FixtureCase {
	id: string;
	committed: string;
	active: string;
	utterance: string;
	scan_type: string;
	expected_action: TriageAction;
	expected_is_correction: boolean;
	expected_needs_committed_edit: boolean;
	hard: boolean;
	note: string;
}
```

- [x] **Step 2: Write the failing delta test**

```ts
// frontend/src/lib/dictation-lab/delta.test.ts
import { describe, expect, it } from 'vitest';
import { computeDelta } from './delta';

describe('computeDelta', () => {
	it('returns the trimmed tail when the transcript extends the last sent one', () => {
		expect(computeDelta('a b c  new words ', 'a b c')).toEqual({ delta: 'new words', next: 'a b c  new words ' });
	});
	it('returns null when nothing new', () => {
		expect(computeDelta('a b c', 'a b c').delta).toBeNull();
		expect(computeDelta('a b c   ', 'a b c').delta).toBeNull();
	});
	it('returns null and resyncs when the prefix no longer matches (window slide or reset)', () => {
		expect(computeDelta('c d e', 'a b c')).toEqual({ delta: null, next: 'c d e' });
	});
	it('treats an empty last-sent as everything new', () => {
		expect(computeDelta('first words', '').delta).toBe('first words');
	});
});
```

- [x] **Step 3: Run to verify failure**

Run: `cd frontend && bun run test -- --project server src/lib/dictation-lab/delta.test.ts`
Expected: FAIL, cannot resolve `./delta`

- [x] **Step 4: Implement delta**

```ts
// frontend/src/lib/dictation-lab/delta.ts
/**
 * The transcript delta since the previous /process call. The backend only ever
 * sees the whole session transcript, so the utterance boundary is computed here,
 * where the previous value is known. When the transcript no longer starts with the
 * last-sent value (the sliding window dropped the prefix, or a reset), send no
 * delta this call and resync.
 */
export function computeDelta(sessionTranscript: string, lastSent: string): { delta: string | null; next: string } {
	if (!sessionTranscript.startsWith(lastSent)) {
		return { delta: null, next: sessionTranscript };
	}
	const tail = sessionTranscript.slice(lastSent.length).trim();
	return { delta: tail.length ? tail : null, next: sessionTranscript };
}
```

- [x] **Step 5: Write the failing labConfig test**

```ts
// frontend/src/lib/dictation-lab/labConfig.test.ts
import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { DEFAULT_LAB_CONFIG, labConfig, loadLabConfig, saveLabConfig, toRequestFields } from './labConfig';

describe('toRequestFields', () => {
	it('shadow strategy sends debug only when showBoth', () => {
		expect(toRequestFields({ strategy: 'shadow', threshold: 0.9, showBoth: true })).toEqual({ triage_debug: true, triage_route: null });
		expect(toRequestFields({ strategy: 'shadow', threshold: 0.9, showBoth: false })).toEqual({ triage_debug: false, triage_route: null });
	});
	it('route strategies set the candidate and threshold', () => {
		expect(toRequestFields({ strategy: 'route:jev', threshold: 0.85, showBoth: false })).toEqual({
			triage_debug: false,
			triage_route: { candidate: 'jev', threshold: 0.85 }
		});
		expect(toRequestFields({ strategy: 'route:qwen', threshold: 0.7, showBoth: true }).triage_route).toEqual({ candidate: 'qwen', threshold: 0.7 });
	});
});

describe('persistence', () => {
	it('falls back to defaults when storage is unavailable or corrupt', () => {
		const fake = { getItem: () => '{not json', setItem: () => { throw new Error('quota'); } } as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
		expect(() => saveLabConfig({ ...DEFAULT_LAB_CONFIG, threshold: 0.6 }, fake)).not.toThrow();
		expect(loadLabConfig(undefined)).toEqual(DEFAULT_LAB_CONFIG);
	});
	it('round-trips through a storage object', () => {
		const mem: Record<string, string> = {};
		const fake = { getItem: (k: string) => mem[k] ?? null, setItem: (k: string, v: string) => { mem[k] = v; } } as unknown as Storage;
		saveLabConfig({ strategy: 'route:jev', threshold: 0.75, showBoth: true }, fake);
		expect(loadLabConfig(fake)).toEqual({ strategy: 'route:jev', threshold: 0.75, showBoth: true });
	});
	it('rejects out-of-range or unknown values', () => {
		const fake = { getItem: () => JSON.stringify({ strategy: 'route:gpt', threshold: 7, showBoth: 'yes' }) } as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
	});
	it('exposes a store seeded from defaults', () => {
		expect(get(labConfig)).toEqual(DEFAULT_LAB_CONFIG);
	});
});
```

- [x] **Step 6: Implement labConfig**

```ts
// frontend/src/lib/dictation-lab/labConfig.ts
import { writable } from 'svelte/store';
import type { LabConfig, LabRequestFields, Strategy } from './types';

export const LAB_CONFIG_KEY = 'rr_lab_config';
export const DEFAULT_LAB_CONFIG: LabConfig = { strategy: 'shadow', threshold: 0.9, showBoth: true };
const STRATEGIES: Strategy[] = ['shadow', 'route:jev', 'route:qwen'];

function storage(): Storage | undefined {
	try {
		return typeof localStorage !== 'undefined' ? localStorage : undefined;
	} catch {
		return undefined;
	}
}

export function loadLabConfig(store: Storage | undefined = storage()): LabConfig {
	if (!store) return { ...DEFAULT_LAB_CONFIG };
	try {
		const raw = store.getItem(LAB_CONFIG_KEY);
		if (!raw) return { ...DEFAULT_LAB_CONFIG };
		const p = JSON.parse(raw);
		const ok =
			STRATEGIES.includes(p?.strategy) &&
			typeof p?.threshold === 'number' && p.threshold >= 0.5 && p.threshold <= 1 &&
			typeof p?.showBoth === 'boolean';
		return ok ? { strategy: p.strategy, threshold: p.threshold, showBoth: p.showBoth } : { ...DEFAULT_LAB_CONFIG };
	} catch {
		return { ...DEFAULT_LAB_CONFIG };
	}
}

export function saveLabConfig(config: LabConfig, store: Storage | undefined = storage()): void {
	if (!store) return;
	try {
		store.setItem(LAB_CONFIG_KEY, JSON.stringify(config));
	} catch {
		/* per-viewer convenience only */
	}
}

export function toRequestFields(config: LabConfig): LabRequestFields {
	const triage_route =
		config.strategy === 'route:jev' ? { candidate: 'jev' as const, threshold: config.threshold }
		: config.strategy === 'route:qwen' ? { candidate: 'qwen' as const, threshold: config.threshold }
		: null;
	return { triage_debug: config.showBoth, triage_route };
}

/** Page-level store; the lab page subscribes and persists on change. */
export const labConfig = writable<LabConfig>(loadLabConfig());
```

- [x] **Step 7: Write the failing fixtureExport test**

```ts
// frontend/src/lib/dictation-lab/fixtureExport.test.ts
import { describe, expect, it } from 'vitest';
import { buildFixtureLine, suggestId } from './fixtureExport';
import type { ProcessTrace } from './types';

const trace: ProcessTrace = {
	seq: 3, at: 0, utterance: 'scratch that', committed: '', activeBefore: '- a\n- b', activeAfter: '- a',
	scanType: 'CT chest', latency_ms: 10, triage: null
};

describe('buildFixtureLine', () => {
	it('produces one valid JSON line with the required keys', () => {
		const line = buildFixtureLine(trace, {
			id: 'delete-lab-01', expected_action: 'delete_previous_utterance',
			expected_is_correction: true, expected_needs_committed_edit: false, hard: false, note: 'from lab'
		});
		expect(line.includes('\n')).toBe(false);
		const obj = JSON.parse(line);
		expect(obj).toEqual({
			id: 'delete-lab-01', committed: '', active: '- a\n- b', utterance: 'scratch that', scan_type: 'CT chest',
			expected_action: 'delete_previous_utterance', expected_is_correction: true,
			expected_needs_committed_edit: false, hard: false, note: 'from lab'
		});
	});
	it('suggestId derives a prefix from the action and a sequence', () => {
		expect(suggestId('formatting_command', 7)).toBe('format-lab-07');
		expect(suggestId('append_new_finding', 12)).toBe('append-lab-12');
	});
});
```

- [x] **Step 8: Implement fixtureExport**

```ts
// frontend/src/lib/dictation-lab/fixtureExport.ts
import type { FixtureCase, ProcessTrace, TriageAction } from './types';

const PREFIX: Record<TriageAction, string> = {
	append_new_finding: 'append',
	correct_previous_finding: 'correct',
	restate_existing_finding: 'restate',
	delete_previous_utterance: 'delete',
	formatting_command: 'format',
	ignore_noise: 'noise'
};

export function suggestId(action: TriageAction, n: number): string {
	return `${PREFIX[action]}-lab-${String(n).padStart(2, '0')}`;
}

export type FixtureLabels = Pick<
	FixtureCase,
	'id' | 'expected_action' | 'expected_is_correction' | 'expected_needs_committed_edit' | 'hard' | 'note'
>;

/** One JSONL line for tests/fixtures/triage_utterances.jsonl. Key order matches the seed file. */
export function buildFixtureLine(trace: ProcessTrace, labels: FixtureLabels): string {
	const c: FixtureCase = {
		id: labels.id,
		committed: trace.committed,
		active: trace.activeBefore,
		utterance: trace.utterance,
		scan_type: trace.scanType,
		expected_action: labels.expected_action,
		expected_is_correction: labels.expected_is_correction,
		expected_needs_committed_edit: labels.expected_needs_committed_edit,
		hard: labels.hard,
		note: labels.note
	};
	return JSON.stringify(c);
}
```

- [x] **Step 9: Write the failing summary test**

```ts
// frontend/src/lib/dictation-lab/summary.test.ts
import { describe, expect, it } from 'vitest';
import { agreementClass, summariseTraces } from './summary';
import type { ProcessTrace, TriageCandidateTrace, TriageTrace } from './types';

const cand = (action: TriageCandidateTrace['action'], conf: number | null = 0.9): TriageCandidateTrace => ({
	action, confidence: conf, probabilities: null, is_correction: null, needs_committed_edit: null,
	latency_ms: 300, input_tokens: null, cost_usd: null, error: null
});
const tr = (t: Partial<TriageTrace> | null, latency = 1000): ProcessTrace => ({
	seq: 1, at: 0, utterance: 'x', committed: '', activeBefore: '', activeAfter: '', scanType: '', latency_ms: latency,
	triage: t ? { mode: 'debug', derived: null, routed: 'model', routed_by: null, live_latency_ms: null, jev: null, qwen: null, ...t } : null
});

describe('agreementClass', () => {
	it('classifies', () => {
		expect(agreementClass(tr(null))).toBe('none');
		expect(agreementClass(tr({ routed: 'deterministic' }))).toBe('deterministic');
		expect(agreementClass(tr({ derived: 'append', jev: cand('append_new_finding'), qwen: cand('append_new_finding', null) }))).toBe('both');
		expect(agreementClass(tr({ derived: 'append', jev: cand('append_new_finding'), qwen: cand('ignore_noise', null) }))).toBe('one');
		expect(agreementClass(tr({ derived: 'append', jev: cand('ignore_noise'), qwen: cand('ignore_noise', null) }))).toBe('neither');
		expect(agreementClass(tr({ derived: 'correct', jev: cand('correct_previous_finding'), qwen: null }))).toBe('both');
	});
});

describe('summariseTraces', () => {
	it('counts handlers, mean latencies and per-candidate agreement', () => {
		const s = summariseTraces([
			tr({ routed: 'deterministic', routed_by: 'jev', jev: cand('ignore_noise') }, 120),
			tr({ derived: 'append', jev: cand('append_new_finding'), qwen: cand('ignore_noise', null) }, 1100),
			tr({ derived: 'noop', jev: cand('ignore_noise'), qwen: cand('ignore_noise', null) }, 900),
			tr(null, 1000)
		]);
		expect(s.total).toBe(4);
		expect(s.deterministic).toBe(1);
		expect(s.model).toBe(3);
		expect(s.meanLatencyDeterministicMs).toBe(120);
		expect(s.meanLatencyModelMs).toBe(1000);
		expect(s.agreement.jev).toEqual({ n: 2, agreed: 2 });
		expect(s.agreement.qwen).toEqual({ n: 2, agreed: 1 });
	});
});
```

- [x] **Step 10: Implement summary**

```ts
// frontend/src/lib/dictation-lab/summary.ts
import type { Candidate, ProcessTrace, TriageAction, TriageTrace } from './types';

/** Mirrors backend dictation_triage_labels.AGREEMENT_MAP. */
const AGREEMENT: Record<TriageAction, string[]> = {
	append_new_finding: ['append'],
	correct_previous_finding: ['correct', 'committed_edit'],
	restate_existing_finding: ['noop', 'correct'],
	delete_previous_utterance: ['delete'],
	formatting_command: ['noop', 'append'],
	ignore_noise: ['noop']
};

export function candidateAgrees(t: TriageTrace, c: Candidate): boolean | null {
	const slot = t[c];
	if (!slot || !slot.action || !t.derived) return null;
	return AGREEMENT[slot.action].includes(t.derived);
}

export type AgreementClass = 'none' | 'deterministic' | 'both' | 'one' | 'neither';

export function agreementClass(p: ProcessTrace): AgreementClass {
	const t = p.triage;
	if (!t) return 'none';
	if (t.routed === 'deterministic') return 'deterministic';
	const votes = (['jev', 'qwen'] as Candidate[]).map((c) => candidateAgrees(t, c)).filter((v): v is boolean => v !== null);
	if (votes.length === 0) return 'none';
	const yes = votes.filter(Boolean).length;
	if (yes === votes.length) return 'both';
	return yes === 0 ? 'neither' : 'one';
}

export interface LabSummary {
	total: number;
	deterministic: number;
	model: number;
	meanLatencyDeterministicMs: number | null;
	meanLatencyModelMs: number | null;
	agreement: Record<Candidate, { n: number; agreed: number }>;
}

function mean(xs: number[]): number | null {
	return xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null;
}

export function summariseTraces(traces: ProcessTrace[]): LabSummary {
	const det = traces.filter((p) => p.triage?.routed === 'deterministic');
	const model = traces.filter((p) => p.triage?.routed !== 'deterministic');
	const agreement = { jev: { n: 0, agreed: 0 }, qwen: { n: 0, agreed: 0 } };
	for (const p of traces) {
		if (!p.triage) continue;
		for (const c of ['jev', 'qwen'] as Candidate[]) {
			const a = candidateAgrees(p.triage, c);
			if (a === null) continue;
			agreement[c].n += 1;
			if (a) agreement[c].agreed += 1;
		}
	}
	return {
		total: traces.length,
		deterministic: det.length,
		model: model.length,
		meanLatencyDeterministicMs: mean(det.map((p) => p.latency_ms)),
		meanLatencyModelMs: mean(model.map((p) => p.latency_ms)),
		agreement
	};
}
```

- [x] **Step 11: Run all four test files**

Run: `cd frontend && bun run test -- --project server src/lib/dictation-lab`
Expected: all PASS

- [x] **Step 12: Commit**

```bash
git add frontend/src/lib/dictation-lab
git commit -m "feat(lab): pure dictation-lab helpers — delta, config, fixture export, summary"
```

---

### Task 10: DictationScratchpad — `handleFinalTranscript`, `injectTranscript`, delta, lab props

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`
  - props block (lines 15-27), state (around line 143-151), `processTranscript` (302-395), websocket `is_final` branch (538-572)

No component test (the repo's browser-mode vitest needs Playwright); the pure helpers are tested in Task 9 and the wiring is verified in Task 13. Keep every edit a pure move or an additive prop.

- [x] **Step 1: Add imports and the two new props**

After the existing imports at the top of the `<script lang="ts">` block add:

```ts
	import { computeDelta } from '$lib/dictation-lab/delta';
	import { toRequestFields } from '$lib/dictation-lab/labConfig';
	import type { LabConfig, ProcessTrace, TriageTrace } from '$lib/dictation-lab/types';
```

After `export let onReviewingChange: (reviewing: boolean) => void = () => {};` (line 27) add:

```ts
	/** Dictation Lab only. null in production: nothing is added to the request. */
	export let labConfig: LabConfig | null = null;
	/** Dictation Lab only. Called once per completed /process call. */
	export let onProcessTrace: (trace: ProcessTrace) => void = () => {};
```

- [x] **Step 2: Add the delta bookkeeping next to `sessionTranscript`**

After `const SESSION_TRANSCRIPT_WINDOW = 2500;` (line 144) add:

```ts
	// Transcript as of the last /process call that completed, so the next call can
	// send the delta as `last_utterance` (triage only; never affects the live response).
	let lastSentTranscript = '';
	let traceSeq = 0;
```

- [x] **Step 3: Extract the `is_final` branch into `handleFinalTranscript` and add `injectTranscript`**

Add these two functions immediately before `async function processTranscript(): Promise<void> {` (line 302):

```ts
	/**
	 * One committed word-group from the speech engine (or from the lab feeder).
	 * Accumulates into the session transcript, renders it faded when Phase 2b.3 is
	 * on, and fires the polish at a pause. This is the body the websocket handler
	 * used to hold inline; it moved so the lab can drive it without a microphone.
	 */
	function handleFinalTranscript(transcript: string, speechFinal: boolean): void {
		currentInterim = '';

		// Accumulate into session transcript
		const appended = sessionTranscript ? `${sessionTranscript} ${transcript}` : transcript;
		sessionTranscript =
			appended.length > SESSION_TRANSCRIPT_WINDOW
				? appended.slice(appended.length - SESSION_TRANSCRIPT_WINDOW)
				: appended;

		// Phase 2b.3: optimistically drop the raw word-group into the doc, rendered
		// faded, so it lands instantly instead of waiting for the polish. The whole
		// raw region is display-only — excluded from the model input and replaced by
		// the polish (see processTranscript). isRecording gates the manual-edit branch.
		if (fadedEnabled() && editor) {
			const docLength = editor.state.doc.length;
			const pend = editor.state.field(pendingField, false);
			const hasPending = !!pend && pend.size > 0;
			// New utterance starts on its own faded line; groups within one are space-joined.
			const sep = docLength === 0 ? '' : hasPending ? ' ' : '\n';
			const to = docLength + sep.length + transcript.length;
			isQwenWriting = true;
			editor.dispatch({
				changes: { from: docLength, insert: sep + transcript },
				effects: markPending.of({ from: docLength, to })
			});
			isQwenWriting = false;
		}

		// Phase 2b.1: fire the polish only at a pause (speech_final), not every
		// is_final — UtteranceEnd is the long-pause backup. Cuts redundant
		// full regenerations; the transcript still accumulates on every chunk.
		if (speechFinal) processTranscriptQueue();
	}

	/** Dictation Lab: feed text exactly as a Deepgram final word-group would arrive. */
	export function injectTranscript(text: string, speechFinal = true): void {
		const t = text.trim();
		if (!t) return;
		handleFinalTranscript(t, speechFinal);
	}
```

Then replace the websocket `else` branch (the block from `// is_final: word-group committed` through `if (data.speech_final) processTranscriptQueue();` inside `websocket.onmessage`) with the single call:

```ts
						} else {
							handleFinalTranscript(data.transcript, !!data.speech_final);
						}
```

The surrounding `if (!data.is_final) { currentInterim = data.transcript; }` stays as it is.

- [x] **Step 4: Send the delta and lab fields, record the trace**

In `processTranscript`, replace the `const body: Record<string, unknown> = { ... };` literal (the one with `session_transcript: sessionTranscript`) with:

```ts
			const sentTranscript = sessionTranscript;
			const { delta } = computeDelta(sentTranscript, lastSentTranscript);
			const activeBefore = faded ? doc.slice(0, pendingStart) : doc;
			const body: Record<string, unknown> = {
				session_transcript: sentTranscript,
				scratchpad_content: activeBefore,
				scan_type: scanType,
				clinical_history: clinicalHistory,
				preferred_section_names: checklistSections,
				mode: polishMode
			};
			if (delta) body.last_utterance = delta;
			if (labConfig) Object.assign(body, toRequestFields(labConfig));
			const t0 = performance.now();
```

Immediately after `const data = await res.json();` add:

```ts
			// The call completed: everything up to sentTranscript has been seen by the model.
			// (An aborted/superseded call never reaches here, so its words stay in the next delta.)
			lastSentTranscript = sentTranscript;
```

Immediately after the `if (data.covered_sections && Array.isArray(data.covered_sections)) { ... }` block (still inside the `try`) add:

```ts
			onProcessTrace({
				seq: ++traceSeq,
				at: Date.now(),
				utterance: delta ?? '',
				committed: '',
				activeBefore,
				activeAfter: content ?? activeBefore,
				scanType,
				latency_ms: Math.round(performance.now() - t0),
				triage: (data.triage as TriageTrace | null | undefined) ?? null
			});
```

- [x] **Step 5: Type-check and lint**

Run: `cd frontend && bun run check`
Expected: no new errors in `DictationScratchpad.svelte` (pre-existing warnings elsewhere are fine).

- [x] **Step 6: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(scratchpad): extract handleFinalTranscript, add injectTranscript, delta + lab props"
```

---

### Task 11: IntelliDictateTab pass-through

**Files:**
- Modify: `frontend/src/routes/components/IntelliDictateTab.svelte` (props ~97-113, `scratchpadRef` type 72-79, exports ~574-600, `<DictationScratchpad` mount)

- [x] **Step 1: Import the types and add the props**

Add to the script imports:

```ts
	import type { LabConfig, ProcessTrace } from '$lib/dictation-lab/types';
```

After `export let apiKeyStatus = { ... };` add:

```ts
	/** Dictation Lab only; the home page never sets these. */
	export let labConfig: LabConfig | null = null;
	export let onProcessTrace: (trace: ProcessTrace) => void = () => {};
```

- [x] **Step 2: Extend the scratchpad ref type and export the feeder entry point**

Change the `scratchpadRef` type to include the new method:

```ts
	let scratchpadRef: {
		getContent: () => string;
		reset: (doc: string) => void;
		highlightSource: (text: string) => void;
		clearHighlight: () => void;
		setIntegrityRanges: (ranges: { from: number; to: number }[]) => void;
		revealIntegrityRange: (range: { from: number; to: number }) => void;
		injectTranscript: (text: string, speechFinal?: boolean) => void;
	} | null = null;
```

Next to the other `export function handleExternal...` functions add:

```ts
	/** Dictation Lab: feed one utterance into the scratchpad as if dictated. */
	export function injectTranscript(text: string, speechFinal = true): void {
		scratchpadRef?.injectTranscript(text, speechFinal);
	}
```

- [x] **Step 3: Pass the props through at the mount**

In the `<DictationScratchpad ... />` element add two attributes before the closing `/>`:

```svelte
			{labConfig}
			{onProcessTrace}
```

- [x] **Step 4: Type-check**

Run: `cd frontend && bun run check`
Expected: clean for this file.

- [x] **Step 5: Commit**

```bash
git add frontend/src/routes/components/IntelliDictateTab.svelte
git commit -m "feat(dictate-tab): pass lab props through and expose injectTranscript"
```

---

### Task 12: The Dictation Lab route and panel

**Files:**
- Create: `frontend/src/routes/dictation-lab/+page.ts`
- Create: `frontend/src/routes/dictation-lab/+page.svelte`
- Create: `frontend/src/lib/components/DictationLabPanel.svelte`

- [x] **Step 1: Gate the route (first commit, per the dev-route rule)**

```ts
// frontend/src/routes/dictation-lab/+page.ts
import { requireDevRoute } from '$lib/guards/dev-route';

export const load = () => requireDevRoute();
```

- [x] **Step 2: Write the lab panel**

```svelte
<!-- frontend/src/lib/components/DictationLabPanel.svelte -->
<script lang="ts">
	import { onDestroy } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { labConfig } from '$lib/dictation-lab/labConfig';
	import { buildFixtureLine, suggestId } from '$lib/dictation-lab/fixtureExport';
	import { agreementClass, summariseTraces, type AgreementClass } from '$lib/dictation-lab/summary';
	import { TRIAGE_ACTIONS, type FixtureCase, type ProcessTrace, type TriageAction, type TriageCandidateTrace } from '$lib/dictation-lab/types';

	/** Feeds one utterance into the production scratchpad (IntelliDictateTab.injectTranscript). */
	export let inject: (text: string) => void = () => {};
	export let traces: ProcessTrace[] = [];
	export let onClear: () => void = () => {};

	// ── Feeder ─────────────────────────────────────────────────────────────────
	let feederText = '';
	let cursor = 0;
	let delayMs = 1500;
	let playing = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let fixtureNote = '';

	$: lines = feederText.split('\n').map((l) => l.trim()).filter(Boolean);

	function step(): void {
		if (cursor >= lines.length) { stop(); return; }
		inject(lines[cursor]);
		cursor += 1;
	}
	function play(): void {
		if (playing) return;
		playing = true;
		const tick = () => {
			if (!playing || cursor >= lines.length) { stop(); return; }
			step();
			timer = setTimeout(tick, delayMs);
		};
		tick();
	}
	function stop(): void {
		playing = false;
		if (timer) { clearTimeout(timer); timer = null; }
	}
	function resetFeeder(): void { stop(); cursor = 0; }
	onDestroy(stop);

	async function loadFixtures(): Promise<void> {
		fixtureNote = '';
		try {
			const headers: Record<string, string> = {};
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/triage/fixtures`, { headers });
			if (!res.ok) { fixtureNote = `fixtures unavailable (${res.status}) — is RR_TRIAGE_DEBUG=1 on the backend?`; return; }
			const data = (await res.json()) as { cases: FixtureCase[] };
			feederText = data.cases.map((c) => c.utterance).join('\n');
			cursor = 0;
			fixtureNote = `${data.cases.length} fixture utterances loaded (state is whatever the scratchpad holds now)`;
		} catch (e) {
			fixtureNote = `fixtures failed: ${(e as Error).message}`;
		}
	}

	// ── Timeline ───────────────────────────────────────────────────────────────
	let expanded: number | null = null;
	const CLASS_STYLE: Record<AgreementClass, string> = {
		none: 'border-gray-700',
		deterministic: 'border-blue-500',
		both: 'border-emerald-500',
		one: 'border-amber-500',
		neither: 'border-red-500'
	};
	function fmtCand(c: TriageCandidateTrace | null): string {
		if (!c) return '—';
		if (c.error) return `error:${c.error}`;
		const conf = c.confidence == null ? '' : ` ${c.confidence.toFixed(2)}`;
		return `${c.action}${conf} · ${c.latency_ms ?? '?'}ms`;
	}
	$: summary = summariseTraces(traces);

	// ── Export ─────────────────────────────────────────────────────────────────
	let exportBuffer = '';
	let exportSeq = 1;
	let exporting: ProcessTrace | null = null;
	let exp = { expected_action: 'append_new_finding' as TriageAction, expected_is_correction: false, expected_needs_committed_edit: false, hard: false, note: '' };

	function startExport(p: ProcessTrace): void {
		exporting = p;
		const guess = (p.triage?.jev?.action ?? p.triage?.qwen?.action ?? 'append_new_finding') as TriageAction;
		exp = { expected_action: guess, expected_is_correction: guess === 'correct_previous_finding' || guess === 'delete_previous_utterance', expected_needs_committed_edit: false, hard: false, note: '' };
	}
	function confirmExport(): void {
		if (!exporting) return;
		const line = buildFixtureLine(exporting, { id: suggestId(exp.expected_action, exportSeq++), ...exp });
		exportBuffer = exportBuffer ? `${exportBuffer}\n${line}` : line;
		exporting = null;
	}
	async function copyBuffer(): Promise<void> {
		try { await navigator.clipboard.writeText(exportBuffer); } catch { /* clipboard may be blocked; the textarea is selectable */ }
	}
</script>

<div class="space-y-4 text-sm">
	<!-- Strategy -->
	<section class="card-dark space-y-2">
		<h3 class="font-semibold">Strategy</h3>
		<div class="flex flex-wrap gap-3">
			{#each [['shadow', 'observe'], ['route:jev', 'route on Jev'], ['route:qwen', 'route on Qwen']] as [value, label]}
				<label class="flex items-center gap-1"><input type="radio" bind:group={$labConfig.strategy} {value} /> {label}</label>
			{/each}
		</div>
		<label class="flex items-center gap-2">
			threshold <input type="range" min="0.5" max="1" step="0.05" bind:value={$labConfig.threshold} disabled={$labConfig.strategy === 'route:qwen'} />
			<span class="tabular-nums">{$labConfig.threshold.toFixed(2)}</span>
			{#if $labConfig.strategy === 'route:qwen'}<span class="text-gray-400">(Qwen has no confidence; always routes)</span>{/if}
		</label>
		<label class="flex items-center gap-2"><input type="checkbox" bind:checked={$labConfig.showBoth} /> show both candidates (triage_debug)</label>
	</section>

	<!-- Feeder -->
	<section class="card-dark space-y-2">
		<h3 class="font-semibold">Utterance feeder <span class="text-gray-400 font-normal">({cursor}/{lines.length})</span></h3>
		<textarea class="w-full h-32 bg-gray-900 rounded p-2 font-mono text-xs" bind:value={feederText} placeholder="one utterance per line"></textarea>
		<div class="flex flex-wrap gap-2 items-center">
			<button class="btn-secondary" on:click={step} disabled={playing || cursor >= lines.length}>Step</button>
			<button class="btn-secondary" on:click={play} disabled={playing || cursor >= lines.length}>Play</button>
			<button class="btn-secondary" on:click={stop} disabled={!playing}>Stop</button>
			<label class="flex items-center gap-1">delay <input type="number" class="w-20 bg-gray-900 rounded px-1" bind:value={delayMs} min="200" step="100" /> ms</label>
			<button class="btn-secondary" on:click={resetFeeder}>Reset feeder</button>
			<button class="btn-secondary" on:click={loadFixtures}>Load fixtures</button>
		</div>
		{#if fixtureNote}<p class="text-gray-400">{fixtureNote}</p>{/if}
	</section>

	<!-- Summary -->
	<section class="card-dark grid grid-cols-2 gap-x-4 gap-y-1">
		<h3 class="font-semibold col-span-2">Session <button class="text-xs text-gray-400 underline ml-2" on:click={onClear}>clear timeline</button></h3>
		<span>calls</span><span class="tabular-nums">{summary.total}</span>
		<span>deterministic / model</span><span class="tabular-nums">{summary.deterministic} / {summary.model}</span>
		<span>mean latency deterministic</span><span class="tabular-nums">{summary.meanLatencyDeterministicMs ?? '—'} ms</span>
		<span>mean latency model</span><span class="tabular-nums">{summary.meanLatencyModelMs ?? '—'} ms</span>
		<span>Jev agreement</span><span class="tabular-nums">{summary.agreement.jev.agreed}/{summary.agreement.jev.n}</span>
		<span>Qwen agreement</span><span class="tabular-nums">{summary.agreement.qwen.agreed}/{summary.agreement.qwen.n}</span>
	</section>

	<!-- Timeline -->
	<section class="card-dark space-y-1 max-h-[28rem] overflow-y-auto">
		<h3 class="font-semibold">Timeline</h3>
		{#if traces.length === 0}<p class="text-gray-400">No calls yet. Dictate or use the feeder.</p>{/if}
		{#each traces as p (p.seq)}
			{@const cls = agreementClass(p)}
			<div class="border-l-4 pl-2 py-1 {CLASS_STYLE[cls]}">
				<button class="text-left w-full" on:click={() => (expanded = expanded === p.seq ? null : p.seq)}>
					<div class="flex justify-between gap-2">
						<span class="font-mono truncate">#{p.seq} “{p.utterance || '(no delta)'}”</span>
						<span class="tabular-nums text-gray-400">{p.latency_ms} ms</span>
					</div>
					<div class="text-xs text-gray-300">
						derived={p.triage?.derived ?? '—'} · routed={p.triage?.routed ?? '—'}{p.triage?.routed_by ? ` by ${p.triage.routed_by}` : ''}
						· jev: {fmtCand(p.triage?.jev ?? null)} · qwen: {fmtCand(p.triage?.qwen ?? null)}
					</div>
				</button>
				{#if expanded === p.seq}
					<pre class="text-xs bg-gray-900 rounded p-2 overflow-x-auto">{JSON.stringify(p, null, 1)}</pre>
					<button class="btn-secondary text-xs" on:click={() => startExport(p)}>Add to fixtures</button>
				{/if}
			</div>
		{/each}
	</section>

	<!-- Export form -->
	{#if exporting}
		<section class="card-dark space-y-2 border border-amber-500/50">
			<h3 class="font-semibold">Label #{exporting.seq}: “{exporting.utterance}”</h3>
			<label class="block">expected action
				<select class="bg-gray-900 rounded px-1 ml-2" bind:value={exp.expected_action}>
					{#each TRIAGE_ACTIONS as a}<option value={a}>{a}</option>{/each}
				</select>
			</label>
			<label class="flex items-center gap-2"><input type="checkbox" bind:checked={exp.expected_is_correction} /> is_correction</label>
			<label class="flex items-center gap-2"><input type="checkbox" bind:checked={exp.expected_needs_committed_edit} /> needs_committed_edit</label>
			<label class="flex items-center gap-2"><input type="checkbox" bind:checked={exp.hard} /> hard</label>
			<input class="w-full bg-gray-900 rounded px-2 py-1" placeholder="note" bind:value={exp.note} />
			<div class="flex gap-2">
				<button class="btn-primary" on:click={confirmExport}>Append line</button>
				<button class="btn-secondary" on:click={() => (exporting = null)}>Cancel</button>
			</div>
		</section>
	{/if}

	<section class="card-dark space-y-2">
		<h3 class="font-semibold">Fixture buffer <span class="text-gray-400 font-normal">→ paste into backend/tests/fixtures/triage_utterances.jsonl</span></h3>
		<textarea class="w-full h-24 bg-gray-900 rounded p-2 font-mono text-xs" readonly value={exportBuffer}></textarea>
		<button class="btn-secondary" on:click={copyBuffer} disabled={!exportBuffer}>Copy fixtures</button>
	</section>
</div>
```

If `btn-primary` / `btn-secondary` / `card-dark` are not global classes in this app (check `src/app.css`), replace them with the Tailwind utilities the other dev routes use (`skill-sheet-proto/+page.svelte` is the reference).

- [x] **Step 3: Write the lab page**

```svelte
<!-- frontend/src/routes/dictation-lab/+page.svelte -->
<script lang="ts">
	import { onMount } from 'svelte';
	import IntelliDictateTab from '../components/IntelliDictateTab.svelte';
	import DictationLabPanel from '$lib/components/DictationLabPanel.svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { labConfig, saveLabConfig } from '$lib/dictation-lab/labConfig';
	import type { ProcessTrace } from '$lib/dictation-lab/types';

	// Same bindings the home page gives the tab (src/routes/+page.svelte ~975-1000).
	let tabRef: { injectTranscript: (text: string, speechFinal?: boolean) => void } | null = null;
	let response: any = null;
	let responseModel: any = null;
	let loading = false;
	let error: any = null;
	let reportId: any = null;
	let apiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		cerebras_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false
	};
	let statusError = '';

	let traces: ProcessTrace[] = [];
	function pushTrace(t: ProcessTrace): void {
		traces = [...traces, t];
	}

	$: saveLabConfig($labConfig);

	onMount(async () => {
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/settings/status`, { headers });
			if (!res.ok) { statusError = `service status ${res.status} — log in on the home page first`; return; }
			const data = await res.json();
			if (data.success) {
				apiKeyStatus = {
					anthropic_configured: data.anthropic_configured || false,
					groq_configured: data.groq_configured || false,
					cerebras_configured: data.cerebras_configured || false,
					deepgram_configured: data.deepgram_configured || false,
					has_at_least_one_model: Boolean(data.has_at_least_one_model ?? (data.anthropic_configured || data.groq_configured || data.cerebras_configured))
				};
			}
		} catch (e) {
			statusError = (e as Error).message;
		}
	});
</script>

<svelte:head><title>Dictation Lab</title></svelte:head>

<div class="min-h-screen p-4 space-y-3">
	<header class="flex items-baseline gap-3">
		<h1 class="text-xl font-semibold">Dictation Lab</h1>
		<span class="text-sm text-gray-400">production dictation tab + triage instrumentation · dev only</span>
		{#if statusError}<span class="text-sm text-amber-400">{statusError}</span>{/if}
	</header>

	<div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_28rem] gap-4">
		<div class="min-w-0">
			<IntelliDictateTab
				bind:this={tabRef}
				bind:response
				bind:responseModel
				bind:loading
				bind:error
				bind:reportId
				{apiKeyStatus}
				labConfig={$labConfig}
				onProcessTrace={pushTrace}
				on:resetForm={() => { traces = []; }}
				on:openSidebar={() => {}}
				on:auditStateChange={() => {}}
				on:showHoverPopup={() => {}}
				on:hideHoverPopup={() => {}}
			/>
		</div>
		<aside class="min-w-0">
			<DictationLabPanel
				inject={(text) => tabRef?.injectTranscript(text, true)}
				{traces}
				onClear={() => { traces = []; }}
			/>
		</aside>
	</div>
</div>
```

- [x] **Step 4: Type-check and start both servers**

Run: `cd frontend && bun run check`
Expected: clean for the new files.

Backend (new terminal): `cd backend && set -a && . ./.env && set +a && RR_TRIAGE_DEBUG=1 .venv/bin/uvicorn rapid_reports_ai.main:app --reload --port 8000` (or `./start.sh` with `RR_TRIAGE_DEBUG=1` exported first).
Frontend (new terminal): `cd frontend && bun run dev`

Open `http://localhost:5173/dictation-lab` (log in on `/` first if the status line says so).

- [x] **Step 5: Smoke in the browser** (done 2026-09-24; mic check left to the user)

1. Paste into the feeder: `there is a six millimetre nodule in the right upper lobe`, `actually make that the left upper lobe`, `um so er`, `new paragraph`, `scratch that`. Strategy: observe, show both. Press *Step* five times. Expect five timeline rows; the "actually" row shows derived=correct with Jev and Qwen both `correct_previous_finding`.
2. Switch to *route on Jev*, threshold 0.9, Reset feeder, Play. Expect the `um so er`, `new paragraph` and `scratch that` rows to show routed=deterministic with a latency well under the model rows, and the scratchpad to reflect the delete and the paragraph break.
3. Click a row → *Add to fixtures* → *Append line* → *Copy fixtures*. Paste the line at the end of `backend/tests/fixtures/triage_utterances.jsonl` and run `cd backend && .venv/bin/pytest tests/test_triage_fixtures.py -q` → pass.
4. Turn the mic on and dictate one sentence: a new timeline row arrives with a real utterance delta.
5. Stop the backend, restart it **without** `RR_TRIAGE_DEBUG`: rows keep arriving with `triage: null`; the route still works. Restart with the flag for the rest.

- [x] **Step 6: Commit**

```bash
git add frontend/src/routes/dictation-lab frontend/src/lib/components/DictationLabPanel.svelte
git commit -m "feat(lab): /dictation-lab dev route mounting the production tab with feeder, traces and routing controls"
```

---

### Task 13: Bake-off run, docs, and verification

**Files:**
- Create: `docs/model-migration/triage-bakeoff-<date>.json` (generated)
- Modify: `docs/superpowers/specs/2026-09-24-jev-dictation-triage-shadow-design.md` (status line only)

- [x] **Step 1: Run the bake-off once and read the numbers**

Run: `cd backend && set -a && . ./.env && set +a && .venv/bin/python -m rapid_reports_ai.scripts.triage_bakeoff`
Expected: a per-candidate summary, a disagreements list, and `wrote docs/model-migration/triage-bakeoff-<date>.json`. Paste the summary block into the spec under a new heading `## 12. Bake-off run 1 (<date>)` with two sentences on what it says against §9.

- [x] **Step 2: Full verification**

Run: `cd backend && .venv/bin/pytest -q` → all pass, live skipped.
Run: `cd frontend && bun run test -- --project server && bun run check` → pass.
Run: `cd frontend && PUBLIC_ENABLE_DEV_ROUTES= bun run build && bun run preview` and open `/dictation-lab` → 404 (the production gate). Stop preview.

- [x] **Step 3: Update the spec status and commit**

Change the spec's `**Status:**` line to `Implemented on branch dictation-triage-lab; bake-off run 1 recorded in §12`.

```bash
git add docs/model-migration/triage-bakeoff-*.json docs/superpowers/specs/2026-09-24-jev-dictation-triage-shadow-design.md
git commit -m "docs(triage): first bake-off run and spec status"
```

- [ ] **Step 4: Hand off**

Use `superpowers:finishing-a-development-branch`. Production deploy needs no env change (both flags default off). To start shadow in production later, set `RR_TRIAGE_SHADOW=1` on Railway and summarise a log dump with `triage_shadow_report.py`.

---

## Self-review notes (done while writing)

- **Spec coverage:** §5.1 → Tasks 1–2; §5.2 → Task 3; §5.3 → Task 4; §5.4 → Task 6; §5.5 → Tasks 10–11; §5.6 → Task 12; §5.7 → Task 5 (+ export in Task 12); §5.8 → Task 7; §8 tests → Tasks 1–9; §9 exit criteria → Task 13 records run 1 (the decision itself is a later spec).
- **Names used across tasks:** `TriageState`, `TriageDecision`, `TriageError`, `get_triager`, `decision_to_trace`, `TriageTrace`, `TriageCandidateTrace` (Task 2) are what Task 6 imports; `derive_action`/`agrees` (Task 3) and `route` (Task 4, imported as `triage_route_decision`) match; frontend `computeDelta`, `toRequestFields`, `labConfig`, `buildFixtureLine`, `suggestId`, `agreementClass`, `summariseTraces` (Task 9) are what Tasks 10–12 import; `injectTranscript` is exported by the scratchpad (Task 10), forwarded by the tab (Task 11), called by the page (Task 12).
- **Known simplification:** the frontend sends no `committed_context` today (full-regeneration path), so `ProcessTrace.committed` is `''` and `TriageState.committed` is empty in the lab. The backend handles the incremental shape regardless, so enabling `rr_incremental` later needs no triage change.
