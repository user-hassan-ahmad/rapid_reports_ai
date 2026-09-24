# Utterance Front Door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two silence timers with one Jev boundary decision per Deepgram chunk, buffering fragments and sending whole statements for polish, lab-only, with chunk-level traces, fixtures and a bake-off.

**Architecture:** A new `utterance_boundary` module owns the boundary/ASR questions, the Jev client and the thresholds. A lab-gated `POST /api/canvas/utterance` exposes it. The scratchpad, when the lab's front door is `jev`, classifies each finalised chunk, buffers on `continues`, sends the merged statement as `last_utterance` on `complete`/`command`, and arms a 1.5 s backstop. The home page keeps the timers.

**Tech Stack:** Python 3.13 / FastAPI / httpx / pytest; SvelteKit 2 (legacy syntax) / vitest server project.

**Spec:** `docs/superpowers/specs/2026-09-24-utterance-front-door-design.md`
**Branch:** `dictation-triage-lab`, same worktree and run commands as the previous two plans.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/src/rapid_reports_ai/utterance_boundary.py` (new) | Questions, `BoundaryDecision`, `JevBoundary`, `resolve`, singleton |
| `backend/src/rapid_reports_ai/canvas_routes.py` (modify) | `POST /api/canvas/utterance` (lab-gated) |
| `backend/tests/fixtures/boundary_cases.jsonl` (new) | 36 labelled chunks |
| `backend/src/rapid_reports_ai/scripts/boundary_bakeoff.py` (new) | Scores Jev on the fixtures |
| `backend/tests/test_utterance_boundary.py`, `test_canvas_utterance_route.py`, `test_boundary_fixtures.py` (new) | Tests |
| `frontend/src/lib/dictation-lab/frontDoor.ts` + `.test.ts` (new) | `applyBoundary`, `flushBuffer`, `lastNonEmptyLine` |
| `frontend/src/lib/dictation-lab/types.ts`, `labConfig.ts` (modify) | `ChunkTrace`, `FrontDoor`, `LabConfig.frontDoor` |
| `frontend/src/lib/components/DictationScratchpad.svelte` (modify) | chunk classification, buffer, backstop, `pendingUtterance` |
| `frontend/src/routes/components/IntelliDictateTab.svelte` (modify) | `onChunkTrace` pass-through |
| `frontend/src/lib/components/DictationLabPanel.svelte`, `frontend/src/routes/dictation-lab/+page.svelte` (modify) | front-door radio, chunk rows, counters, export |

---

### Task 1: Boundary module

**Files:** create `backend/src/rapid_reports_ai/utterance_boundary.py`; test `backend/tests/test_utterance_boundary.py`

- [x] **Step 1: Failing tests**

```python
# backend/tests/test_utterance_boundary.py
from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.dictation_triage import JEV_MODEL, JEV_URL, TriageError
from rapid_reports_ai.utterance_boundary import (
    BOUNDARY_QUESTIONS, COMMAND_THRESHOLD, COMPLETE_THRESHOLD, BoundaryDecision, JevBoundary, resolve,
)


def _resp(boundary="complete", conf=0.9, asr=0.05):
    probs = {"complete": 0.0, "continues": 0.0, "command": 0.0}
    probs[boundary] = 1.0
    return {"model": "typesafe/jev-1.13-20260917",
            "answers": {"boundary": {"type": "choice", "choice": boundary, "confidence": conf, "probabilities": probs},
                        "asr_risk": {"type": "noul", "noul": asr}},
            "usage": {"input_tokens": 220, "output_tokens": 20, "cost": 9e-06}}


def test_questions_shape():
    assert set(BOUNDARY_QUESTIONS) == {"boundary", "asr_risk"}
    assert set(BOUNDARY_QUESTIONS["boundary"]["criteria"]) == {"complete", "continues", "command"}
    assert BOUNDARY_QUESTIONS["asr_risk"]["type"] == "noul"


async def test_request_and_parse():
    captured = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json=_resp())

    d = await JevBoundary(api_key="k", transport=httpx.MockTransport(handler)).classify(
        "CT chest", "further satellite lesions noted in the", "left lower lobe", "There is a 10 mm nodule.")
    b = captured["body"]
    assert b["model"] == JEV_MODEL and captured is not None
    assert b["state"] == {"scan_type": "CT chest", "buffered": "further satellite lesions noted in the",
                          "chunk": "left lower lobe", "scratchpad_tail": "There is a 10 mm nodule."}
    assert b["questions"] == BOUNDARY_QUESTIONS
    assert d.boundary == "complete" and d.confidence == 0.9 and d.asr_risk == 0.05 and d.input_tokens == 220


@pytest.mark.parametrize("bad", [
    lambda: httpx.Response(500, json={"error": "x"}),
    lambda: httpx.Response(200, json={"answers": {"boundary": {"choice": "complete", "confidence": 1, "probabilities": {}}}}),
    lambda: httpx.Response(200, json=_resp(boundary="maybe")),
    lambda: httpx.Response(200, json=_resp(asr=1.5)),
])
async def test_raises_on_invalid(bad):
    with pytest.raises(TriageError):
        await JevBoundary(api_key="k", transport=httpx.MockTransport(lambda r: bad())).classify("", "", "x", "")


def _d(boundary, conf):
    return BoundaryDecision(boundary=boundary, confidence=conf, probabilities={}, asr_risk=0.0,
                            latency_ms=1, input_tokens=None, cost_usd=None)


def test_resolve_thresholds():
    assert resolve(_d("complete", COMPLETE_THRESHOLD)) == "complete"
    assert resolve(_d("complete", COMPLETE_THRESHOLD - 0.01)) == "continues"
    assert resolve(_d("command", COMMAND_THRESHOLD)) == "command"
    assert resolve(_d("command", COMMAND_THRESHOLD - 0.01)) == "continues"
    assert resolve(_d("continues", 1.0)) == "continues"


def test_resolve_fails_open_to_complete():
    assert resolve(TriageError("boom")) == "complete"
```

- [x] **Step 2: Implement**

```python
# backend/src/rapid_reports_ai/utterance_boundary.py
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
COMPLETE_THRESHOLD = 0.6
COMMAND_THRESHOLD = 0.8

BOUNDARY_QUESTIONS: dict[str, dict[str, Any]] = {
    "boundary": {
        "type": "choice",
        "instructions": "Taking the buffered words and the chunk together as what the radiologist has said since the last statement was sent, which is true?",
        "criteria": {
            "complete": "The buffered words plus the chunk form a finished clinical statement a radiologist would end here: a finding, a measurement, a normality claim, or a correction that is fully specified.",
            "continues": "The statement is still in progress: it ends on a preposition, article, conjunction, a verb without its object, an unfinished measurement, an unfinished correction such as 'actually' or 'make that', or otherwise needs more words to be a claim.",
            "command": "The chunk is an instruction to the application or a dictation command rather than report content: scratch that, delete that, new paragraph, new line, full stop, generate report, switch mode, and similar.",
        },
    },
    "asr_risk": {
        "type": "noul",
        "instructions": "The buffered words plus the chunk contain a likely speech-to-text error: a word that is phonetically close to a radiological term the scan type or the scratchpad makes expected, and that makes no clinical sense as heard.",
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


class JevBoundary:
    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = JEV_TIMEOUT_S) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
        if not self._api_key:
            raise TriageError("OPENROUTER_API_KEY is not set")
        self._transport = transport
        self._timeout_s = timeout_s

    async def classify(self, scan_type: str, buffered: str, chunk: str, scratchpad_tail: str) -> BoundaryDecision:
        body = {"model": JEV_MODEL,
                "state": {"scan_type": scan_type or "", "buffered": buffered or "", "chunk": chunk or "",
                          "scratchpad_tail": scratchpad_tail or ""},
                "questions": BOUNDARY_QUESTIONS}
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
        if "boundary" not in answers or "asr_risk" not in answers:
            raise TriageError("jev boundary answer missing")
        b = answers["boundary"]
        boundary = b.get("choice")
        if boundary not in BOUNDARIES:
            raise TriageError(f"jev boundary unknown choice: {boundary!r}")
        probabilities = {k: _check_unit(v, f"probability[{k}]") for k, v in (b.get("probabilities") or {}).items()}
        usage = data.get("usage") or {}
        return BoundaryDecision(
            boundary=boundary, confidence=_check_unit(b.get("confidence"), "confidence"),
            probabilities=probabilities, asr_risk=_check_unit(answers["asr_risk"].get("noul"), "asr_risk"),
            latency_ms=latency_ms, input_tokens=usage.get("input_tokens"), cost_usd=usage.get("cost"),
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
```

- [x] **Step 3: Run, commit** — `pytest backend/tests/test_utterance_boundary.py`; commit `feat(boundary): per-chunk boundary + ASR-risk questions and Jev client`.

---

### Task 2: Route

**Files:** modify `canvas_routes.py`; test `backend/tests/test_canvas_utterance_route.py`

- [x] **Step 1: Failing tests**

```python
# backend/tests/test_canvas_utterance_route.py
from __future__ import annotations

import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_triage import TriageError
from rapid_reports_ai.main import app
from rapid_reports_ai.utterance_boundary import BoundaryDecision

BODY = {"scan_type": "CT chest", "buffered": "further satellite lesions noted in the",
        "chunk": "left lower lobe", "scratchpad_tail": "There is a 10 mm nodule."}


@pytest.fixture
def authed_client(client, db_session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
                is_active=True, is_verified=True, is_approved=True)
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class Fake:
    def __init__(self, boundary="complete", conf=0.9, raise_=False):
        self.boundary, self.conf, self.raise_, self.calls = boundary, conf, raise_, []

    async def classify(self, scan_type, buffered, chunk, scratchpad_tail):
        self.calls.append((scan_type, buffered, chunk, scratchpad_tail))
        if self.raise_:
            raise TriageError("boom")
        return BoundaryDecision(self.boundary, self.conf, {self.boundary: 1.0}, 0.1, 250, 200, 8e-06)


def test_404_without_flag(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert authed_client.post("/api/canvas/utterance", json=BODY).status_code == 404


def test_resolved_decision(authed_client, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    fake = Fake("continues", 0.7)
    monkeypatch.setattr(cr, "get_jev_boundary", lambda: fake)
    r = authed_client.post("/api/canvas/utterance", json=BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] == "continues" and body["boundary"] == "continues" and body["confidence"] == 0.7
    assert body["asr_risk"] == 0.1 and body["latency_ms"] == 250 and body["error"] is None
    assert fake.calls == [("CT chest", BODY["buffered"], "left lower lobe", "There is a 10 mm nodule.")]


def test_low_confidence_complete_resolves_to_continues(authed_client, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(cr, "get_jev_boundary", lambda: Fake("complete", 0.5))
    assert authed_client.post("/api/canvas/utterance", json=BODY).json()["resolved"] == "continues"


def test_error_fails_open(authed_client, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(cr, "get_jev_boundary", lambda: Fake(raise_=True))
    body = authed_client.post("/api/canvas/utterance", json=BODY).json()
    assert body["resolved"] == "complete" and body["error"] == "TriageError" and body["boundary"] is None
```

- [x] **Step 2: Implement** — add to the imports `from .utterance_boundary import BoundaryDecision, get_jev_boundary, resolve as resolve_boundary`, and append after the fixtures endpoint:

```python
class UtteranceRequest(BaseModel):
    scan_type: str = ""
    buffered: str = ""
    chunk: str
    scratchpad_tail: str = ""


class UtteranceResponse(BaseModel):
    resolved: Literal["complete", "continues", "command"]
    boundary: Optional[str] = None
    confidence: Optional[float] = None
    probabilities: Optional[dict[str, float]] = None
    asr_risk: Optional[float] = None
    latency_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


@canvas_router.post("/utterance", response_model=UtteranceResponse)
async def classify_utterance(request: UtteranceRequest, current_user: User = Depends(get_current_user)):
    """Lab only: boundary decision for one finalised chunk (spec 2026-09-24-utterance-front-door)."""
    if not _triage_debug_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        d: BoundaryDecision | BaseException = await get_jev_boundary().classify(
            request.scan_type, request.buffered, request.chunk, request.scratchpad_tail)
    except Exception as e:
        logger.error("[canvas.utterance] ❌ %s: %s", type(e).__name__, e)
        d = e
    resolved = resolve_boundary(d)
    if isinstance(d, BaseException):
        return UtteranceResponse(resolved=resolved, error=type(d).__name__)
    logger.info("[canvas.utterance] %s (%s %.2f) asr=%.2f %dms", resolved, d.boundary, d.confidence, d.asr_risk, d.latency_ms)
    return UtteranceResponse(resolved=resolved, boundary=d.boundary, confidence=d.confidence,
                             probabilities=d.probabilities, asr_risk=d.asr_risk, latency_ms=d.latency_ms,
                             input_tokens=d.input_tokens, cost_usd=d.cost_usd)
```

- [x] **Step 3: Run the suite, commit** `feat(canvas): lab-gated /api/canvas/utterance boundary endpoint`.

---

### Task 3: Fixtures and bake-off

**Files:** create `backend/tests/fixtures/boundary_cases.jsonl`, `backend/tests/test_boundary_fixtures.py`, `backend/src/rapid_reports_ai/scripts/boundary_bakeoff.py`

- [x] **Step 1: Validation test**

```python
# backend/tests/test_boundary_fixtures.py
import json
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "boundary_cases.jsonl"
REQUIRED = {"id", "scan_type", "buffered", "chunk", "scratchpad_tail", "expected_boundary", "expected_asr_risk", "hard", "note"}


def load():
    return [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]


def test_well_formed():
    for c in load():
        assert REQUIRED <= set(c), c.get("id")
        assert c["expected_boundary"] in {"complete", "continues", "command"}, c["id"]
        assert isinstance(c["expected_asr_risk"], bool) and isinstance(c["hard"], bool)
        assert c["chunk"].strip()


def test_ids_unique_and_ten_per_class():
    cases = load()
    assert len({c["id"] for c in cases}) == len(cases)
    counts = Counter(c["expected_boundary"] for c in cases)
    for k in ("complete", "continues", "command"):
        assert counts[k] >= 10, k
```

- [x] **Step 2: Fixture file (36 cases)**

```jsonl
{"id": "cmp-01", "scan_type": "CT chest", "buffered": "", "chunk": "there is abnormal nodular pleural thickening at the left base", "scratchpad_tail": "Further satellite lesions noted in the left lower lobe.", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "single-chunk finding"}
{"id": "cmp-02", "scan_type": "CT chest", "buffered": "there is a 10 millimeter nodule", "chunk": "in the right upper lobe which is spiculated in nature", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "buffer + closing chunk"}
{"id": "cmp-03", "scan_type": "CT chest", "buffered": "", "chunk": "the mediastinum is unremarkable", "scratchpad_tail": "There is abnormal nodular pleural thickening at the left base.", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "normality claim"}
{"id": "cmp-04", "scan_type": "CT chest", "buffered": "further satellite lesions noted in the left lower lobe", "chunk": "the largest measuring 8 mm in size", "scratchpad_tail": "There is a 10 mm nodule in the right upper lobe.", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "measurement closes"}
{"id": "cmp-05", "scan_type": "CT abdomen pelvis", "buffered": "", "chunk": "the liver is normal", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "short normality"}
{"id": "cmp-06", "scan_type": "CT chest", "buffered": "actually", "chunk": "make that the left upper lobe", "scratchpad_tail": "There is a 10 mm nodule in the right upper lobe.", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "correction fully specified"}
{"id": "cmp-07", "scan_type": "CT chest", "buffered": "", "chunk": "no pleural effusion no pneumothorax", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "run-on negatives"}
{"id": "cmp-08", "scan_type": "CT chest", "buffered": "the adrenal glands", "chunk": "are unremarkable as well as the remaining visualised upper abdominal viscera", "scratchpad_tail": "Several mixed lytic and sclerotic lesions in the ribs.", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "long closing chunk"}
{"id": "cmp-09", "scan_type": "MRI lumbar spine", "buffered": "", "chunk": "L4 L5 disc bulge without nerve root compression", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "level + negative"}
{"id": "cmp-10", "scan_type": "CT chest", "buffered": "several mixed lytic and sclerotic lesions in the ribs", "chunk": "and upper thoracic spine", "scratchpad_tail": "The mediastinum is unremarkable.", "expected_boundary": "complete", "expected_asr_risk": false, "hard": true, "note": "'and X' can close a list"}
{"id": "cmp-11", "scan_type": "US abdomen", "buffered": "", "chunk": "gallbladder wall thickened with pericholecystic fluid", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "two features one claim"}
{"id": "cmp-12", "scan_type": "CT chest", "buffered": "", "chunk": "it was five millimetres on the prior now ten millimetres", "scratchpad_tail": "There is a nodule in the right upper lobe.", "expected_boundary": "complete", "expected_asr_risk": false, "hard": true, "note": "temporal comparison is a whole statement"}
{"id": "cnt-01", "scan_type": "CT chest", "buffered": "", "chunk": "there is a 10 millimeter nodule", "scratchpad_tail": "", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "noun phrase, location pending"}
{"id": "cnt-02", "scan_type": "CT chest", "buffered": "there is a 10 millimeter nodule", "chunk": "in the right upper lobe", "scratchpad_tail": "", "expected_boundary": "continues", "expected_asr_risk": false, "hard": true, "note": "could close, but 'which is' followed in session; treat location-only as complete? No: pause pattern says more coming"}
{"id": "cnt-03", "scan_type": "CT chest", "buffered": "", "chunk": "further satellite lesions noted in the", "scratchpad_tail": "There is a 10 mm nodule.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "ends on article"}
{"id": "cnt-04", "scan_type": "CT chest", "buffered": "further satellite lesions noted in the", "chunk": "left lower lobe the largest measuring", "scratchpad_tail": "There is a 10 mm nodule.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "measurement unfinished"}
{"id": "cnt-05", "scan_type": "CT chest", "buffered": "", "chunk": "the", "scratchpad_tail": "There is abnormal nodular pleural thickening.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "single article"}
{"id": "cnt-06", "scan_type": "CT chest", "buffered": "", "chunk": "several", "scratchpad_tail": "The mediastinum is unremarkable.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "single quantifier"}
{"id": "cnt-07", "scan_type": "CT chest", "buffered": "", "chunk": "actually", "scratchpad_tail": "There is a 10 mm nodule in the right upper lobe.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "correction opener"}
{"id": "cnt-08", "scan_type": "CT chest", "buffered": "", "chunk": "the adrenal glands", "scratchpad_tail": "Several lesions in the ribs.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "subject without predicate"}
{"id": "cnt-09", "scan_type": "CT abdomen pelvis", "buffered": "there is a", "chunk": "2 centimetre simple cyst in the", "scratchpad_tail": "", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "ends on preposition"}
{"id": "cnt-10", "scan_type": "CT chest", "buffered": "", "chunk": "make that", "scratchpad_tail": "There is a 10 mm nodule in the right upper lobe.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "correction without value"}
{"id": "cnt-11", "scan_type": "CT chest", "buffered": "", "chunk": "there is abnormal nodular pleural thickening", "scratchpad_tail": "Further satellite lesions noted in the left lower lobe.", "expected_boundary": "continues", "expected_asr_risk": false, "hard": true, "note": "grammatically complete but location typically follows; session showed 'at the left base' next"}
{"id": "cnt-12", "scan_type": "MRI lumbar spine", "buffered": "", "chunk": "at L4 L5 there is", "scratchpad_tail": "", "expected_boundary": "continues", "expected_asr_risk": false, "hard": false, "note": "verb without object"}
{"id": "cmd-01", "scan_type": "CT chest", "buffered": "", "chunk": "scratch that", "scratchpad_tail": "The heart size is normal.", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "delete"}
{"id": "cmd-02", "scan_type": "CT chest", "buffered": "", "chunk": "new paragraph", "scratchpad_tail": "No pleural effusion.", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "formatting"}
{"id": "cmd-03", "scan_type": "CT chest", "buffered": "", "chunk": "new line", "scratchpad_tail": "No pleural effusion.", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "formatting"}
{"id": "cmd-04", "scan_type": "CT chest", "buffered": "", "chunk": "generate report", "scratchpad_tail": "No pleural effusion.", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "app command"}
{"id": "cmd-05", "scan_type": "CT chest", "buffered": "", "chunk": "delete that", "scratchpad_tail": "The heart size is normal.", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "delete"}
{"id": "cmd-06", "scan_type": "CT chest", "buffered": "", "chunk": "full stop", "scratchpad_tail": "No pleural effusion", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "punctuation"}
{"id": "cmd-07", "scan_type": "CT chest", "buffered": "", "chunk": "switch to structured mode", "scratchpad_tail": "", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "mode switch"}
{"id": "cmd-08", "scan_type": "CT chest", "buffered": "", "chunk": "undo that", "scratchpad_tail": "The heart size is normal.", "expected_boundary": "command", "expected_asr_risk": false, "hard": true, "note": "undo phrasing"}
{"id": "cmd-09", "scan_type": "CT chest", "buffered": "", "chunk": "next paragraph", "scratchpad_tail": "No pleural effusion.", "expected_boundary": "command", "expected_asr_risk": false, "hard": true, "note": "variant phrasing"}
{"id": "cmd-10", "scan_type": "CT chest", "buffered": "", "chunk": "strike that", "scratchpad_tail": "The heart size is normal.", "expected_boundary": "command", "expected_asr_risk": false, "hard": false, "note": "delete variant"}
{"id": "asr-01", "scan_type": "CT chest", "buffered": "there is abnormal nodular pleural thickening", "chunk": "at the white base", "scratchpad_tail": "Further satellite lesions noted in the left lower lobe.", "expected_boundary": "complete", "expected_asr_risk": true, "hard": true, "note": "white base = left base"}
{"id": "asr-02", "scan_type": "CT chest", "buffered": "there is a 10 millimeter nodule in the right upper lobe", "chunk": "which is speculated in nature", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": true, "hard": true, "note": "speculated = spiculated"}
{"id": "asr-03", "scan_type": "CT abdomen pelvis", "buffered": "", "chunk": "there is a hepatic haemangioma in segment seven", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": false, "hard": false, "note": "correct term, no risk"}
{"id": "asr-04", "scan_type": "CT head", "buffered": "", "chunk": "no acute intracranial hemorrhage or mass affect", "scratchpad_tail": "", "expected_boundary": "complete", "expected_asr_risk": true, "hard": true, "note": "mass affect = mass effect"}
```

- [x] **Step 3: Bake-off script**

```python
# backend/src/rapid_reports_ai/scripts/boundary_bakeoff.py
"""Score Jev's boundary + ASR-risk decisions on tests/fixtures/boundary_cases.jsonl."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import median

from rapid_reports_ai.scripts.triage_summary import BUCKETS, _p
from rapid_reports_ai.utterance_boundary import get_jev_boundary, resolve

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "boundary_cases.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"


async def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("missing OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]
    sem = asyncio.Semaphore(4)

    async def run(c):
        async with sem:
            try:
                d = await get_jev_boundary().classify(c["scan_type"], c["buffered"], c["chunk"], c["scratchpad_tail"])
                return {**c, "raw": d.boundary, "resolved": resolve(d), "confidence": d.confidence,
                        "asr_risk": d.asr_risk, "latency_ms": d.latency_ms, "cost_usd": d.cost_usd, "error": None}
            except Exception as e:
                return {**c, "raw": None, "resolved": "complete", "confidence": None, "asr_risk": None,
                        "latency_ms": 0, "cost_usd": None, "error": type(e).__name__}

    rows = await asyncio.gather(*(run(c) for c in cases))
    ok = [r for r in rows if r["error"] is None]
    by_class = defaultdict(list)
    for r in ok:
        by_class[r["expected_boundary"]].append(r)
    print(f"== jev boundary: n={len(rows)} errors={len(rows) - len(ok)} "
          f"resolved_acc={sum(r['resolved'] == r['expected_boundary'] for r in ok) / len(ok):.3f} "
          f"raw_acc={sum(r['raw'] == r['expected_boundary'] for r in ok) / len(ok):.3f} "
          f"p50={int(median([r['latency_ms'] for r in ok]))}ms p95={_p([r['latency_ms'] for r in ok], 0.95)}ms "
          f"cost=${sum(r['cost_usd'] or 0 for r in rows):.5f}")
    for k, rs in by_class.items():
        print(f"   {k:<10} n={len(rs):<3} resolved_acc={sum(r['resolved'] == k for r in rs) / len(rs):.2f} "
              f"raw_acc={sum(r['raw'] == k for r in rs) / len(rs):.2f}")
    hard = [r for r in ok if r["hard"]]
    print(f"   hard       n={len(hard):<3} resolved_acc={sum(r['resolved'] == r['expected_boundary'] for r in hard) / max(1, len(hard)):.2f}")
    asr = [r for r in ok if r["asr_risk"] is not None]
    print(f"   asr_risk@0.5 acc={sum((r['asr_risk'] >= 0.5) == r['expected_asr_risk'] for r in asr) / max(1, len(asr)):.3f}")
    for name, lo, hi in BUCKETS:
        rs = [r for r in ok if lo <= r["confidence"] < hi]
        if rs:
            print(f"   conf {name:<8} n={len(rs):<3} raw_acc={sum(r['raw'] == r['expected_boundary'] for r in rs) / len(rs):.3f}")
    print("\n-- misses --")
    for r in ok:
        if r["resolved"] != r["expected_boundary"]:
            print(f"   {r['id']:<7} expected={r['expected_boundary']:<9} raw={r['raw']:<9} conf={r['confidence']:.2f} resolved={r['resolved']}  '{r['buffered']} | {r['chunk']}'")
    conf = Counter(r["expected_asr_risk"] for r in asr)
    print(f"\nasr cases: {dict(conf)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"boundary-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [x] **Step 4: Run validation, commit** `test(boundary): 36 boundary cases and bake-off script`.

---

### Task 4: Frontend helpers, types, config

**Files:** create `frontend/src/lib/dictation-lab/frontDoor.ts` + `frontDoor.test.ts`; modify `types.ts`, `labConfig.ts`, `labConfig.test.ts`

- [x] **Step 1: Types** (append to `types.ts`; add `frontDoor: FrontDoor` to `LabConfig`)

```ts
export type FrontDoor = 'timer' | 'jev';
export type Boundary = 'complete' | 'continues' | 'command';
/** One finalised Deepgram chunk classified by the front door. */
export interface ChunkTrace {
	seq: number;
	at: number;
	chunk: string;
	buffered: string;
	resolved: Boundary;
	boundary: Boundary | null;
	confidence: number | null;
	asr_risk: number | null;
	latency_ms: number;
	error: string | null;
	sent: string | null; // the merged statement handed to polish, when one was
	viaBackstop: boolean;
}
/** Mirrors UtteranceResponse. */
export interface UtteranceResponse {
	resolved: Boundary;
	boundary: Boundary | null;
	confidence: number | null;
	probabilities: Record<string, number> | null;
	asr_risk: number | null;
	latency_ms: number | null;
	error: string | null;
}
```

`labConfig.ts`: `DEFAULT_LAB_CONFIG.frontDoor = 'timer'`; `loadLabConfig` requires `p?.frontDoor === 'timer' || p?.frontDoor === 'jev'` and copies it. `labConfig.test.ts`: `base` gains `frontDoor: 'timer'`, the round-trip config uses `frontDoor: 'jev'`.

- [x] **Step 2: Failing helper tests**

```ts
// frontend/src/lib/dictation-lab/frontDoor.test.ts
import { describe, expect, it } from 'vitest';
import { applyBoundary, flushBuffer, lastNonEmptyLine } from './frontDoor';

describe('applyBoundary', () => {
	it('buffers on continues', () => {
		expect(applyBoundary(['there is a'], '10 mm nodule', 'continues')).toEqual({ send: null, buffer: ['there is a', '10 mm nodule'] });
	});
	it('sends the merged statement on complete and clears the buffer', () => {
		expect(applyBoundary(['there is a', '10 mm nodule'], 'in the right upper lobe', 'complete')).toEqual({
			send: 'there is a 10 mm nodule in the right upper lobe', buffer: []
		});
	});
	it('sends on command too', () => {
		expect(applyBoundary([], 'scratch that', 'command')).toEqual({ send: 'scratch that', buffer: [] });
	});
});

describe('flushBuffer', () => {
	it('sends whatever is buffered, or nothing', () => {
		expect(flushBuffer(['a', 'b'])).toEqual({ send: 'a b', buffer: [] });
		expect(flushBuffer([])).toEqual({ send: null, buffer: [] });
	});
});

describe('lastNonEmptyLine', () => {
	it('returns the last non-blank line, trimmed', () => {
		expect(lastNonEmptyLine('- a\n- b  \n\n')).toBe('- b');
		expect(lastNonEmptyLine('')).toBe('');
	});
});
```

- [x] **Step 3: Implement**

```ts
// frontend/src/lib/dictation-lab/frontDoor.ts
import type { Boundary } from './types';

/** Fold a resolved boundary into the chunk buffer. Pure. */
export function applyBoundary(buffer: string[], chunk: string, resolved: Boundary): { send: string | null; buffer: string[] } {
	const next = [...buffer, chunk];
	if (resolved === 'continues') return { send: null, buffer: next };
	return { send: next.join(' '), buffer: [] };
}

export function flushBuffer(buffer: string[]): { send: string | null; buffer: string[] } {
	return { send: buffer.length ? buffer.join(' ') : null, buffer: [] };
}

export function lastNonEmptyLine(text: string): string {
	const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
	return lines.length ? lines[lines.length - 1] : '';
}
```

- [x] **Step 4: Run vitest, commit** `feat(lab): front-door helpers and config`.

---

### Task 5: Component wiring

**Files:** modify `DictationScratchpad.svelte`, `IntelliDictateTab.svelte`, `DictationLabPanel.svelte`, `dictation-lab/+page.svelte`

- [x] **Step 1: Scratchpad**

Imports: `import { applyBoundary, flushBuffer, lastNonEmptyLine } from '$lib/dictation-lab/frontDoor';` and add `ChunkTrace, UtteranceResponse` to the type import. Props after `onCoverageTrace`:

```ts
	/** Dictation Lab only. One record per finalised chunk when the front door is 'jev'. */
	export let onChunkTrace: (trace: ChunkTrace) => void = () => {};
```

State after `traceSeq`:

```ts
	// Front door (lab): chunks held until Jev says the statement is complete.
	let chunkBuffer: string[] = [];
	let pendingUtterance: string | null = null;
	let chunkSeq = 0;
	let backstopTimer: ReturnType<typeof setTimeout> | null = null;
	let classifyChain: Promise<void> = Promise.resolve();
	const BACKSTOP_MS = 1500;
	function frontDoorIsJev(): boolean {
		return labConfig?.frontDoor === 'jev';
	}
```

Replace the tail of `handleFinalTranscript` (the `if (speechFinal) processTranscriptQueue();` line) with:

```ts
		if (frontDoorIsJev()) {
			// Serialise so decisions see the buffer in arrival order.
			classifyChain = classifyChain.then(() => classifyChunk(transcript)).catch(() => {});
			return;
		}
		if (speechFinal) processTranscriptQueue();
```

Add after `injectTranscript`:

```ts
	function armBackstop(): void {
		if (backstopTimer) clearTimeout(backstopTimer);
		backstopTimer = setTimeout(() => {
			backstopTimer = null;
			const { send, buffer } = flushBuffer(chunkBuffer);
			chunkBuffer = buffer;
			if (send) {
				onChunkTrace({ seq: ++chunkSeq, at: Date.now(), chunk: '', buffered: send, resolved: 'complete', boundary: null,
					confidence: null, asr_risk: null, latency_ms: 0, error: null, sent: send, viaBackstop: true });
				pendingUtterance = send;
				processTranscriptQueue();
			}
		}, BACKSTOP_MS);
	}

	async function classifyChunk(chunk: string): Promise<void> {
		if (backstopTimer) { clearTimeout(backstopTimer); backstopTimer = null; }
		const buffered = chunkBuffer.join(' ');
		const doc = editor ? editor.state.doc.toString() : '';
		let pendingStart = doc.length;
		editor?.state.field(pendingField, false)?.between(0, doc.length, (from) => { pendingStart = from; return false; });
		const tail = lastNonEmptyLine(doc.slice(0, pendingStart));
		const t0 = performance.now();
		let data: UtteranceResponse = { resolved: 'complete', boundary: null, confidence: null, probabilities: null, asr_risk: null, latency_ms: null, error: null };
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/utterance`, {
				method: 'POST', headers,
				body: JSON.stringify({ scan_type: scanType, buffered, chunk, scratchpad_tail: tail })
			});
			if (res.ok) data = (await res.json()) as UtteranceResponse;
			else data.error = `http ${res.status}`;
		} catch (e) {
			data.error = (e as Error).name;
		}
		const { send, buffer } = applyBoundary(chunkBuffer, chunk, data.resolved);
		chunkBuffer = buffer;
		onChunkTrace({ seq: ++chunkSeq, at: Date.now(), chunk, buffered, resolved: data.resolved, boundary: data.boundary,
			confidence: data.confidence, asr_risk: data.asr_risk, latency_ms: Math.round(performance.now() - t0),
			error: data.error, sent: send, viaBackstop: false });
		if (send !== null) {
			pendingUtterance = send;
			processTranscriptQueue();
		} else {
			armBackstop();
		}
	}
```

In `processTranscript`, change `if (delta) body.last_utterance = delta;` to:

```ts
			const utterance = pendingUtterance ?? delta;
			pendingUtterance = null;
			if (utterance) body.last_utterance = utterance;
```

and in the trace `utterance: delta ?? ''` becomes `utterance: utterance ?? ''`.

In the websocket `utterance_end` branch, wrap the existing call: `if (!frontDoorIsJev() && !isProcessingQueue) processTranscriptQueue();`.

In `stopRecording`, before the existing flush (`if (sessionTranscript.trim()) processTranscriptQueue();`):

```ts
		if (backstopTimer) { clearTimeout(backstopTimer); backstopTimer = null; }
		const flushed = flushBuffer(chunkBuffer);
		chunkBuffer = flushed.buffer;
		if (flushed.send) pendingUtterance = flushed.send;
```

- [x] **Step 2: Tab** — add `ChunkTrace` to the type import, prop `export let onChunkTrace: (trace: ChunkTrace) => void = () => {};`, and `{onChunkTrace}` on the scratchpad mount.

- [x] **Step 3: Panel** — prop `export let chunkTraces: ChunkTrace[] = [];`, a **Front door** radio (`timer` / `jev`) in the Strategy section bound to `$labConfig.frontDoor`, a **Chunks** section listing each chunk (text, resolved, confidence, asr risk, latency, backstop marker, and `→ sent` when a statement went out), a summary line (`chunks`, `statements sent`, `polish calls saved = chunks − sent`, mean latency), and per-chunk **Add to boundary fixtures** producing `{"id","scan_type","buffered","chunk","scratchpad_tail","expected_boundary","expected_asr_risk","hard","note"}` lines into a third buffer. Reuse the existing card/button classes.

- [x] **Step 4: Page** — `let chunkTraces: ChunkTrace[] = [];`, `onChunkTrace={(t) => { chunkTraces = [...chunkTraces, t]; }}` on the tab, `{chunkTraces}` on the panel, cleared with the timeline.

- [x] **Step 5: svelte-check the touched files (0 diagnostics), commit** `feat(lab): Jev front door — chunk classification, buffering, backstop, chunk traces`.

---

### Task 6: Bake-off, lab check, docs

- [x] Run `boundary_bakeoff` (same runpy pattern as the others). Restart the backend. In the lab set Front door = jev and dictate one report; expect fragments buffered and one polish per statement, chunk rows in the panel, `polish calls saved` > 0. Export one chunk as a boundary fixture. Record a `## 7. Bake-off run 1` in the spec with the numbers against §5, set the status line, tick the plan, commit.
