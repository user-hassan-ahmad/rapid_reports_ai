# Section Pill Coverage (Jev Nouls) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Checklist pill coverage as one Jev call with one Noul per section, traced beside the current Qwen path in the lab, selectable for production by an env setting that defaults to Qwen.

**Architecture:** A new `section_coverage` module owns the Noul criteria, the Jev client and the decision/trace types. The review endpoint's Qwen closure is lifted to a module-level function returning the same decision shape; the endpoint picks the selected candidate, optionally runs the other for the lab trace, and returns `coverage_scores` beside `covered_sections`. The frontend threads scores and the trace through the existing callbacks; three-state pills and a coverage section appear only in the lab.

**Tech Stack:** Python 3.13, FastAPI, pydantic, httpx, pytest; SvelteKit 2 / Svelte 5 legacy syntax, vitest server project.

**Spec:** `docs/superpowers/specs/2026-09-24-section-coverage-jev-design.md`
**Branch:** continue on `dictation-triage-lab` in the existing worktree. Backend commands run from the worktree root with `--rootdir backend -c backend/pyproject.toml`, using the main tree's venv at `/Users/hassan/Code/rapid_reports_ai/backend/.venv`.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/src/rapid_reports_ai/section_coverage.py` (new) | `COVERAGE_CRITERIA`, `coverage_questions`, `CoverageDecision`, trace models, `JevCoverage`, `decision_to_coverage_trace` |
| `backend/src/rapid_reports_ai/canvas_routes.py` (modify) | `qwen_coverage` lifted out of the endpoint; `_coverage_candidate`; review request/response fields; review flow |
| `backend/tests/fixtures/coverage_cases.jsonl` (new) | 24 labelled scratchpads, ≥ 3 per rule |
| `backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py` (new) | Scores both candidates on the fixtures |
| `backend/tests/test_section_coverage.py`, `test_canvas_coverage_modes.py`, `test_coverage_fixtures.py`, `test_coverage_bakeoff.py` (new) | Tests |
| `frontend/src/lib/dictation-lab/coverage.ts` + `coverage.test.ts` (new) | `pillState`, `coverageAgreement`, `buildCoverageFixtureLine` |
| `frontend/src/lib/dictation-lab/types.ts`, `labConfig.ts` (modify) | `CoverageTrace`, `LabConfig.coverageDebug`, `pillThresholds` |
| `frontend/src/lib/components/DictationScratchpad.svelte` (modify) | `_runReview` sends `coverage_debug`, forwards scores and trace |
| `frontend/src/routes/components/IntelliDictateTab.svelte` (modify) | pass-through + three-state pills when `pillThresholds` set |
| `frontend/src/lib/components/DictationLabPanel.svelte`, `frontend/src/routes/dictation-lab/+page.svelte` (modify) | Coverage section, sliders, export |

---

### Task 1: Coverage questions, Jev client, trace models

**Files:**
- Create: `backend/src/rapid_reports_ai/section_coverage.py`
- Test: `backend/tests/test_section_coverage.py`

- [x] **Step 1: Write the failing tests**

```python
# backend/tests/test_section_coverage.py
from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.canvas_routes import CANVAS_COVERAGE_SYSTEM_PROMPT
from rapid_reports_ai.dictation_triage import JEV_MODEL, JEV_URL, TriageError
from rapid_reports_ai.section_coverage import (
    COVERAGE_CRITERIA,
    CoverageCandidateTrace,
    JevCoverage,
    coverage_questions,
    decision_to_coverage_trace,
)

SECTIONS = ["LUNGS", "PLEURA", "MEDIASTINUM"]
PAD = "- 6 mm nodule right upper lobe\n- no pleural effusion\n- mediastinum"


def _resp(scores: dict[str, float]):
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {k: {"type": "noul", "noul": v} for k, v in scores.items()},
        "usage": {"input_tokens": 410, "output_tokens": 30, "cost": 1.7e-05},
    }


def test_one_noul_per_section_with_section_substituted():
    q = coverage_questions(SECTIONS)
    assert list(q) == SECTIONS
    for s in SECTIONS:
        assert q[s]["type"] == "noul"
        assert s in q[s]["instructions"]
        assert s in q[s]["criteria"]["true"] and s in q[s]["criteria"]["false"]
        assert "{SECTION}" not in q[s]["criteria"]["true"]


@pytest.mark.parametrize(
    "phrase",
    ["bare mention", "collective", "adjacent", "abbreviation", "normality", "incidental co-mention", "vague filler"],
)
def test_criteria_share_key_phrases_with_the_qwen_prompt(phrase):
    joined = (COVERAGE_CRITERIA["true"] + " " + COVERAGE_CRITERIA["false"]).lower()
    assert phrase in joined
    assert phrase.split()[0] in CANVAS_COVERAGE_SYSTEM_PROMPT.lower()


async def test_jev_request_and_decision():
    captured = {}

    def handler(req: httpx.Request):
        captured["body"] = json.loads(req.content)
        captured["url"] = str(req.url)
        return httpx.Response(200, json=_resp({"LUNGS": 0.97, "PLEURA": 0.9, "MEDIASTINUM": 0.12}))

    cov = JevCoverage(api_key="k", transport=httpx.MockTransport(handler))
    d = await cov.classify(PAD, SECTIONS, "CT chest")

    assert captured["url"] == JEV_URL
    body = captured["body"]
    assert body["model"] == JEV_MODEL
    assert body["state"] == {"scan_type": "CT chest", "checklist": SECTIONS, "scratchpad": PAD}
    assert list(body["questions"]) == SECTIONS
    assert d.candidate == "jev"
    assert d.scores == {"LUNGS": 0.97, "PLEURA": 0.9, "MEDIASTINUM": 0.12}
    assert d.covered == ["LUNGS", "PLEURA"]
    assert d.input_tokens == 410 and d.cost_usd == 1.7e-05 and d.latency_ms >= 0


async def test_jev_empty_checklist_makes_no_call():
    def handler(req):
        raise AssertionError("must not be called")

    d = await JevCoverage(api_key="k", transport=httpx.MockTransport(handler)).classify(PAD, [], "")
    assert d.scores == {} and d.covered == []


async def test_jev_raises_on_missing_section():
    cov = JevCoverage(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_resp({"LUNGS": 0.5}))))
    with pytest.raises(TriageError):
        await cov.classify(PAD, SECTIONS, "")


async def test_jev_raises_on_out_of_range_and_http_error():
    bad = JevCoverage(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_resp({"LUNGS": 1.3, "PLEURA": 0, "MEDIASTINUM": 0}))))
    with pytest.raises(TriageError):
        await bad.classify(PAD, SECTIONS, "")
    err = JevCoverage(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"error": "x"})))
    with pytest.raises(TriageError):
        await err.classify(PAD, SECTIONS, "")


async def test_jev_raises_on_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(TriageError):
        await JevCoverage(api_key="k", transport=httpx.MockTransport(handler)).classify(PAD, SECTIONS, "")


def test_trace_from_exception():
    t = decision_to_coverage_trace(TriageError("boom"))
    assert isinstance(t, CoverageCandidateTrace) and t.error == "TriageError" and t.scores is None
```

- [x] **Step 2: Run to verify failure**

Run: `/Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/pytest backend/tests/test_section_coverage.py -q --rootdir backend -c backend/pyproject.toml`
Expected: `ModuleNotFoundError: No module named 'rapid_reports_ai.section_coverage'`

- [x] **Step 3: Implement**

```python
# backend/src/rapid_reports_ai/section_coverage.py
"""Checklist pill coverage as System 1 decisions: one Noul per section, one call.

The criteria reproduce the rules in canvas_routes.CANVAS_COVERAGE_SYSTEM_PROMPT so
that Jev and the Qwen path answer the same question. Edit COVERAGE_CRITERIA and that
prompt together; test_section_coverage pins the shared phrases.

Spec: docs/superpowers/specs/2026-09-24-section-coverage-jev-design.md
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel

from .dictation_triage import JEV_MODEL, JEV_TIMEOUT_S, JEV_URL, TriageError, _check_unit

Candidate = Literal["jev", "qwen"]
BINARY_THRESHOLD = 0.5

COVERAGE_CRITERIA: dict[str, str] = {
    "true": (
        "The scratchpad contains a definitive clinical claim about {SECTION} or a standard radiological "
        "abbreviation of it: a finding, a measurement, a qualifier, or an explicit normality statement. "
        "The claim may be direct ({SECTION} is the grammatical subject, the location via a prepositional "
        "phrase, or an adjectival modifier of the subject) or collective (a definitive claim over a "
        "recognisable anatomical group that {SECTION} genuinely belongs to, such as normality or absence "
        "of pathology). A specific claim about {SECTION} counts even when a collective also exists."
    ),
    "false": (
        "There is no definitive claim about {SECTION}: only a bare mention with nothing asserted; a claim "
        "about an adjacent but distinct structure; a parent-structure claim that does not enumerate "
        "{SECTION} when the checklist lists it separately; an incidental co-mention inside a statement "
        "about another structure; a vague filler with no anatomical scope; or a collective whose group "
        "{SECTION} does not clearly belong to. When in doubt, this is the answer."
    ),
}


def coverage_questions(sections: list[str]) -> dict[str, dict[str, Any]]:
    """One noul per checklist section, keyed by the exact section string."""
    return {
        s: {
            "type": "noul",
            "instructions": f"The scratchpad meaningfully addresses the checklist section {s}.",
            "criteria": {
                "true": COVERAGE_CRITERIA["true"].replace("{SECTION}", s),
                "false": COVERAGE_CRITERIA["false"].replace("{SECTION}", s),
            },
        }
        for s in sections
    }


@dataclass(frozen=True)
class CoverageDecision:
    candidate: Candidate
    scores: dict[str, float]
    covered: list[str]
    latency_ms: int
    input_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    raw: list[str] = field(default_factory=list)  # qwen only: the model's unnormalised list


def covered_from_scores(scores: dict[str, float], sections: list[str], threshold: float = BINARY_THRESHOLD) -> list[str]:
    return [s for s in sections if scores.get(s, 0.0) >= threshold]


class JevCoverage:
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

    async def classify(self, scratchpad: str, sections: list[str], scan_type: str) -> CoverageDecision:
        if not sections:
            return CoverageDecision(candidate="jev", scores={}, covered=[], latency_ms=0)
        body = {
            "model": JEV_MODEL,
            "state": {"scan_type": scan_type or "", "checklist": list(sections), "scratchpad": scratchpad or ""},
            "questions": coverage_questions(sections),
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
                resp = await client.post(JEV_URL, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise TriageError(f"jev coverage transport failure: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            raise TriageError(f"jev coverage http {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise TriageError("jev coverage returned non-JSON") from e
        answers = data.get("answers") or {}
        scores: dict[str, float] = {}
        for s in sections:
            if s not in answers:
                raise TriageError(f"jev coverage answer missing: {s}")
            scores[s] = _check_unit(answers[s].get("noul"), f"coverage[{s}]")
        usage = data.get("usage") or {}
        return CoverageDecision(
            candidate="jev",
            scores=scores,
            covered=covered_from_scores(scores, sections),
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            cost_usd=usage.get("cost"),
        )


_JEV: JevCoverage | None = None


def get_jev_coverage() -> JevCoverage:
    global _JEV
    if _JEV is None:
        _JEV = JevCoverage()
    return _JEV


class CoverageCandidateTrace(BaseModel):
    scores: Optional[dict[str, float]] = None
    covered: Optional[list[str]] = None
    raw: Optional[list[str]] = None
    latency_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


class CoverageTrace(BaseModel):
    selected: Candidate
    jev: Optional[CoverageCandidateTrace] = None
    qwen: Optional[CoverageCandidateTrace] = None


def decision_to_coverage_trace(result: CoverageDecision | BaseException) -> CoverageCandidateTrace:
    if isinstance(result, BaseException):
        return CoverageCandidateTrace(error=type(result).__name__)
    return CoverageCandidateTrace(
        scores=result.scores, covered=result.covered, raw=result.raw or None,
        latency_ms=result.latency_ms, input_tokens=result.input_tokens, cost_usd=result.cost_usd,
    )
```

`_check_unit` is imported from `dictation_triage`; it is module-private by underscore only. Leave it there (both modules are System 1 clients) rather than duplicating.

- [x] **Step 4: Run the tests**

Run: `/Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/pytest backend/tests/test_section_coverage.py -q --rootdir backend -c backend/pyproject.toml`
Expected: all PASS (the phrase test depends on the criteria wording above containing "abbreviation", "normality", "incidental co-mention", "vague filler", "adjacent", "collective", "bare mention"; the Qwen prompt contains each first word).

- [x] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/section_coverage.py backend/tests/test_section_coverage.py
git commit -m "feat(coverage): section coverage as one Jev noul per checklist section"
```

---

### Task 2: Review endpoint — lifted Qwen path, candidate selection, trace

**Files:**
- Modify: `backend/src/rapid_reports_ai/canvas_routes.py` (models near lines 111-128; `review_scratchpad` at 966-1122)
- Modify: `backend/.env.example` (append)
- Test: `backend/tests/test_canvas_coverage_modes.py`

- [x] **Step 1: Write the failing route tests**

```python
# backend/tests/test_canvas_coverage_modes.py
"""Coverage candidate selection and lab trace on POST /api/canvas/review.
Both candidates and IntelliPrompts are faked; wiring is under test."""
from __future__ import annotations

import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_triage import TriageError
from rapid_reports_ai.main import app
from rapid_reports_ai.section_coverage import CoverageDecision

SECTIONS = ["LUNGS", "PLEURA", "MEDIASTINUM"]
BASE = {"scratchpad_content": "- no pleural effusion", "checklist_sections": SECTIONS, "scan_type": "CT chest", "clinical_history": "", "mode": "clean"}


@pytest.fixture
def authed_client(client, db_session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
                is_active=True, is_verified=True, is_approved=True)
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class FakeJev:
    def __init__(self):
        self.calls = 0
        self.raise_ = False

    async def classify(self, scratchpad, sections, scan_type):
        self.calls += 1
        if self.raise_:
            raise TriageError("boom")
        scores = {"LUNGS": 0.2, "PLEURA": 0.95, "MEDIASTINUM": 0.6}
        return CoverageDecision("jev", scores, ["PLEURA", "MEDIASTINUM"], 300, 400, 1e-05)


@pytest.fixture
def fakes(monkeypatch):
    jev = FakeJev()
    qwen_calls = []
    qwen_state = {"raise": False}

    async def fake_qwen(scratchpad, sections, scan_type):
        qwen_calls.append(1)
        if qwen_state["raise"]:
            raise RuntimeError("model down")
        return CoverageDecision("qwen", {"LUNGS": 0.0, "PLEURA": 1.0, "MEDIASTINUM": 0.0}, ["PLEURA"], 900, raw=["PLEURA"])

    async def fake_prompts():
        return []

    monkeypatch.setattr(cr, "get_jev_coverage", lambda: jev)
    monkeypatch.setattr(cr, "qwen_coverage", fake_qwen)
    monkeypatch.setattr(cr, "_intelliprompts", lambda request: fake_prompts())
    return jev, qwen_calls, qwen_state


def _post(client, **extra):
    return client.post("/api/canvas/review", json={**BASE, **extra})


def test_default_is_qwen_no_jev_call(authed_client, fakes, monkeypatch):
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    jev, qwen_calls, _ = fakes
    body = _post(authed_client).json()
    assert body["covered_sections"] == ["PLEURA"]
    assert body["coverage_scores"] == {"LUNGS": 0.0, "PLEURA": 1.0, "MEDIASTINUM": 0.0}
    assert body.get("coverage") is None
    assert jev.calls == 0 and len(qwen_calls) == 1


def test_jev_selected(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_COVERAGE_CANDIDATE", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, qwen_calls, _ = fakes
    body = _post(authed_client).json()
    assert body["covered_sections"] == ["PLEURA", "MEDIASTINUM"]
    assert body["coverage_scores"]["PLEURA"] == 0.95
    assert jev.calls == 1 and qwen_calls == []


def test_jev_selected_without_key_falls_back_to_qwen(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_COVERAGE_CANDIDATE", "jev")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    jev, qwen_calls, _ = fakes
    body = _post(authed_client).json()
    assert body["covered_sections"] == ["PLEURA"] and jev.calls == 0


def test_selected_failure_with_no_other_candidate_degrades_to_empty(authed_client, fakes, monkeypatch):
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    _, _, qwen_state = fakes
    qwen_state["raise"] = True
    r = _post(authed_client)
    assert r.status_code == 200
    assert r.json()["covered_sections"] == [] and r.json()["coverage_scores"] is None


def test_debug_runs_both_and_attaches_trace(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    jev, qwen_calls, _ = fakes
    body = _post(authed_client, coverage_debug=True).json()
    assert body["covered_sections"] == ["PLEURA"]           # qwen still selected
    t = body["coverage"]
    assert t["selected"] == "qwen"
    assert t["jev"]["scores"]["PLEURA"] == 0.95 and t["jev"]["latency_ms"] == 300
    assert t["qwen"]["covered"] == ["PLEURA"] and t["qwen"]["raw"] == ["PLEURA"]
    assert jev.calls == 1 and len(qwen_calls) == 1


def test_debug_selected_failure_uses_other_candidate(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("RR_COVERAGE_CANDIDATE", "jev")
    jev, _, _ = fakes
    jev.raise_ = True
    body = _post(authed_client, coverage_debug=True).json()
    assert body["covered_sections"] == ["PLEURA"]
    assert body["coverage"]["jev"]["error"] == "TriageError"


def test_debug_field_ignored_without_flag(authed_client, fakes, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    jev, _, _ = fakes
    body = _post(authed_client, coverage_debug=True).json()
    assert body.get("coverage") is None and jev.calls == 0
```

- [x] **Step 2: Run to verify failure**

Run: `/Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/pytest backend/tests/test_canvas_coverage_modes.py -q --rootdir backend -c backend/pyproject.toml`
Expected: `AttributeError: ... has no attribute 'get_jev_coverage'`

- [x] **Step 3: Models and imports**

Add to the `from .dictation_triage import (...)` block's neighbourhood in `canvas_routes.py`:

```python
from .section_coverage import (
    CoverageDecision,
    CoverageTrace,
    decision_to_coverage_trace,
    get_jev_coverage,
)
```

Replace `CanvasReviewRequest` and `CanvasReviewResponse`:

```python
class CanvasReviewRequest(BaseModel):
    scratchpad_content: str
    checklist_sections: list[str] = []
    scan_type: str = ""
    clinical_history: str = ""
    mode: str = "clean"
    # Lab-only (RR_TRIAGE_DEBUG=1): run both coverage candidates and attach the trace.
    coverage_debug: bool = False


class CanvasReviewResponse(BaseModel):
    covered_sections: list[str]
    prompts: list[IntelliPrompt] = []
    # Per-section score from the selected coverage candidate (Qwen gives 1.0/0.0).
    coverage_scores: Optional[dict[str, float]] = None
    coverage: Optional[CoverageTrace] = None  # lab only
```

`CanvasReviewResponse` is never handed to a model as an output schema (the model-facing types are `CoverageOnlyResponse` and `PromptsOnlyResponse`), so adding fields here is safe.

- [x] **Step 4: Lift the Qwen closure and add candidate selection (insert above `@canvas_router.post("/review"`)**

```python
def _coverage_candidate() -> Literal["jev", "qwen"]:
    """RR_COVERAGE_CANDIDATE selects the production coverage path. Defaults to qwen;
    jev is honoured only when the OpenRouter key exists (warn once otherwise)."""
    if os.environ.get("RR_COVERAGE_CANDIDATE") == "jev":
        if os.environ.get("OPENROUTER_API_KEY"):
            return "jev"
        if "RR_COVERAGE_CANDIDATE" not in _TRIAGE_WARNED:
            _TRIAGE_WARNED.add("RR_COVERAGE_CANDIDATE")
            logger.warning("[canvas.coverage] RR_COVERAGE_CANDIDATE=jev but OPENROUTER_API_KEY is unset; using qwen")
    return "qwen"


async def qwen_coverage(scratchpad: str, sections: list[str], scan_type: str) -> CoverageDecision:
    """The pre-existing coverage path, lifted out of the review endpoint unchanged in
    behaviour (prompt, settings, fallback, normaliser). Raises on total failure so the
    caller decides how to degrade."""
    coverage_model = MODEL_CONFIG["CANVAS_COVERAGE"]
    coverage_fallback = MODEL_CONFIG.get("CANVAS_COVERAGE_FALLBACK")
    checklist_str = ", ".join(sections) if sections else "(none)"
    coverage_prompt = CANVAS_COVERAGE_USER_PROMPT_TEMPLATE.format(
        scratchpad_content=scratchpad, checklist_sections=checklist_str,
    )
    coverage_model_settings = {"temperature": 0.1, "max_completion_tokens": 1500}
    t0 = _time.perf_counter()
    output = await _run_canvas_with_fallback(
        coverage_model,
        coverage_fallback,
        output_type=CoverageOnlyResponse,
        system_prompt=CANVAS_COVERAGE_SYSTEM_PROMPT,
        user_prompt=coverage_prompt,
        model_settings=coverage_model_settings,
        label="canvas.coverage",
    )
    raw_covered = output.covered_sections
    latency_ms = int((_time.perf_counter() - t0) * 1000)

    # Defensive post-validation — the schema is list[str] so any string is valid at
    # the schema layer, but Qwen occasionally comma-concatenates sections or emits a
    # name that isn't on the checklist. Split when every part matches, then filter.
    checklist_set = set(sections)
    normalised: list[str] = []
    split_count = 0
    dropped: list[str] = []
    for item in raw_covered:
        if "," in item:
            parts = [p.strip() for p in item.split(",")]
            if all(p in checklist_set for p in parts):
                normalised.extend(parts)
                split_count += 1
                continue
        if item in checklist_set:
            normalised.append(item)
        else:
            dropped.append(item)
    covered = [s for s in sections if s in set(normalised)]  # checklist order, deduped
    if split_count or dropped:
        logger.info("[canvas.coverage] normalised raw=%s split=%d dropped=%s", raw_covered, split_count, dropped)
    logger.info("[canvas.coverage] %dms → %s", latency_ms, covered)
    scores = {s: (1.0 if s in covered else 0.0) for s in sections}
    return CoverageDecision(candidate="qwen", scores=scores, covered=covered, latency_ms=latency_ms, raw=list(raw_covered))


async def _coverage_safe(name: str, request: CanvasReviewRequest) -> CoverageDecision | BaseException:
    try:
        if name == "jev":
            return await get_jev_coverage().classify(request.scratchpad_content, request.checklist_sections, request.scan_type)
        return await qwen_coverage(request.scratchpad_content, request.checklist_sections, request.scan_type)
    except Exception as e:
        logger.error("[canvas.coverage] ❌ %s %s: %s", name, type(e).__name__, e)
        return e
```

- [x] **Step 5: Restructure `review_scratchpad`**

Replace the whole function. The IntelliPrompts closure is moved verbatim into a module-level `_intelliprompts(request)` so tests can patch it; nothing inside it changes.

```python
async def _intelliprompts(request: CanvasReviewRequest) -> list[IntelliPrompt]:
    """IntelliPrompts generation — unchanged from the previous inline closure."""
    intelliprompts_model = MODEL_CONFIG["CANVAS_INTELLIPROMPTS"]
    intelliprompts_fallback = MODEL_CONFIG.get("CANVAS_INTELLIPROMPTS_FALLBACK")
    intelliprompts_provider = _get_model_provider(intelliprompts_model)
    intelliprompts_api_key = _get_api_key_for_provider(intelliprompts_provider)
    intelliprompts_prompt = CANVAS_INTELLIPROMPTS_USER_PROMPT_TEMPLATE.format(
        scan_type=request.scan_type or "(not specified)",
        clinical_history=request.clinical_history or "(not specified)",
        scratchpad_content=request.scratchpad_content,
    )
    if intelliprompts_provider == "cerebras":
        intelliprompts_model_settings = {"temperature": 0.1, "max_completion_tokens": 1500, "reasoning_effort": "medium"}
        use_thinking = False
    else:
        intelliprompts_model_settings = {"temperature": 0.1, "max_tokens": 3000}
        use_thinking = True

    scratchpad_lower = request.scratchpad_content.lower()

    async def _call_model(model_name: str, api_key: str, thinking: bool, settings: dict) -> PromptsOnlyResponse:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=PromptsOnlyResponse,
            system_prompt=CANVAS_INTELLIPROMPTS_SYSTEM_PROMPT,
            user_prompt=intelliprompts_prompt,
            api_key=api_key,
            use_thinking=thinking,
            model_settings=settings,
        )
        return result.output

    def _validate_and_log(raw: list[IntelliPrompt], elapsed: float, label: str) -> list[IntelliPrompt]:
        validated = []
        for p in raw:
            if p.source_text and p.source_text.lower() not in scratchpad_lower:
                print(f"[INTELLIPROMPTS] ⚠️  Clearing fabricated source_text: '{p.source_text}'")
                validated.append(IntelliPrompt(question=p.question, source_text="", rationale=p.rationale))
            else:
                validated.append(p)
        logger.info("[canvas.intelliprompts] %s %.2fs → %d prompts", label, elapsed, len(validated))
        for p in validated:
            rationale_preview = (p.rationale[:80] + "…") if p.rationale and len(p.rationale) > 80 else (p.rationale or "⚠️ NO RATIONALE")
            print(f"[INTELLIPROMPTS]   • {p.question}")
            print(f"[INTELLIPROMPTS]     ↳ {rationale_preview}")
        return validated

    print(f"\n[INTELLIPROMPTS] ── New call ──────────────────────────")
    print(f"[INTELLIPROMPTS] Model: {intelliprompts_model} | use_thinking: {use_thinking} | stateless")
    t0 = _time.perf_counter()
    try:
        response = await _call_model(intelliprompts_model, intelliprompts_api_key, use_thinking, intelliprompts_model_settings)
        elapsed = _time.perf_counter() - t0
        return _validate_and_log(response.prompts, elapsed, "✅")
    except Exception as e:
        fallback_model = intelliprompts_fallback or "gpt-oss-120b"
        try:
            fallback_api_key = _get_api_key_for_provider(_get_model_provider(fallback_model))
            response = await _call_model(
                fallback_model, fallback_api_key, False,
                {"temperature": 0.1, "max_completion_tokens": 1500, "reasoning_effort": "medium"},
            )
            elapsed = _time.perf_counter() - t0
            logger.warning("[canvas.intelliprompts] primary %s failed (%s); served by fallback %s", intelliprompts_model, type(e).__name__, fallback_model)
            return _validate_and_log(response.prompts, elapsed, "⚡ fallback")
        except Exception as fallback_e:
            logger.error("[canvas.intelliprompts] ❌ both failed: %s: %s", type(fallback_e).__name__, fallback_e)
            return []


@canvas_router.post("/review", response_model=CanvasReviewResponse)
async def review_scratchpad(
    request: CanvasReviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Parallel pass: coverage (selected candidate, plus the other in lab debug) and IntelliPrompts."""
    try:
        _get_api_key_for_provider(_get_model_provider(MODEL_CONFIG["CANVAS_COVERAGE"]))
        _get_api_key_for_provider(_get_model_provider(MODEL_CONFIG["CANVAS_INTELLIPROMPTS"]))
    except ValueError:
        raise HTTPException(status_code=503, detail="Service not available. Contact your administrator.")

    selected = _coverage_candidate()
    other = "qwen" if selected == "jev" else "jev"
    debug = _triage_debug_enabled() and request.coverage_debug

    tasks = [_coverage_safe(selected, request), _intelliprompts(request)]
    if debug:
        tasks.append(_coverage_safe(other, request))
    results = await asyncio.gather(*tasks)
    primary, prompts = results[0], results[1]
    secondary = results[2] if debug else None

    chosen: CoverageDecision | None = primary if isinstance(primary, CoverageDecision) else None
    if chosen is None and isinstance(secondary, CoverageDecision):
        logger.warning("[canvas.coverage] selected %s failed; serving %s", selected, other)
        chosen = secondary

    trace = None
    if debug:
        trace = CoverageTrace(
            selected=selected,
            **{selected: decision_to_coverage_trace(primary), other: decision_to_coverage_trace(secondary)},
        )
    return CanvasReviewResponse(
        covered_sections=chosen.covered if chosen else [],
        prompts=prompts,
        coverage_scores=chosen.scores if chosen else None,
        coverage=trace,
    )
```

Delete the old `review_scratchpad` body entirely (lines 966-1122 in the pre-change file), including the inline `run_coverage` and `run_intelliprompts` closures and the `coverage_*`/`intelliprompts_*` variable setup.

- [x] **Step 6: Document the env setting**

Append to `backend/.env.example`:

```
RR_COVERAGE_CANDIDATE=qwen   # jev = serve checklist pill coverage from Jev nouls (needs OPENROUTER_API_KEY)
```

- [x] **Step 7: Run coverage tests and the whole backend suite**

Run: `/Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/pytest backend/tests -q --rootdir backend -c backend/pyproject.toml`
Expected: all pass. Existing canvas tests that call `review_scratchpad` directly, if any, keep working because the signature is unchanged.

- [x] **Step 8: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/.env.example backend/tests/test_canvas_coverage_modes.py
git commit -m "feat(canvas): coverage candidate selection (RR_COVERAGE_CANDIDATE), lab trace, scores on /review"
```

---

### Task 3: Coverage fixtures and validation

**Files:**
- Create: `backend/tests/fixtures/coverage_cases.jsonl`
- Test: `backend/tests/test_coverage_fixtures.py`

- [x] **Step 1: Write the validation test**

```python
# backend/tests/test_coverage_fixtures.py
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "coverage_cases.jsonl"
REQUIRED = {"id", "scan_type", "checklist", "scratchpad", "expected_covered", "rule", "hard", "note"}
RULES = {
    "direct-subject", "direct-location", "direct-modifier", "collective-group", "collective-boundary",
    "specific-overrides-collective", "bare-mention", "adjacent-structure", "parent-not-enumerating",
    "incidental-co-mention", "vague-filler", "abbreviation",
}


def load():
    return [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]


def test_well_formed():
    cases = load()
    assert cases
    for c in cases:
        assert REQUIRED <= set(c), c.get("id")
        assert c["rule"] in RULES, c["id"]
        assert set(c["expected_covered"]) <= set(c["checklist"]), c["id"]
        assert isinstance(c["hard"], bool)


def test_ids_unique():
    ids = [c["id"] for c in load()]
    assert len(ids) == len(set(ids))


def test_every_rule_has_at_least_two_cases():
    counts = Counter(c["rule"] for c in load())
    for r in RULES:
        assert counts[r] >= 2, r
```

- [x] **Step 2: Write the fixture file (24 cases)**

```jsonl
{"id": "ds-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "SPLEEN", "KIDNEYS", "BOWEL"], "scratchpad": "The liver is normal.", "expected_covered": ["LIVER"], "rule": "direct-subject", "hard": false, "note": "structure as subject, normality claim"}
{"id": "ds-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "MEDIASTINUM", "HEART"], "scratchpad": "The mediastinum is unremarkable.\nThe heart is enlarged.", "expected_covered": ["MEDIASTINUM", "HEART"], "rule": "direct-subject", "hard": false, "note": "two subjects"}
{"id": "dl-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "SPLEEN", "KIDNEYS", "PELVIS"], "scratchpad": "There is a 12 mm hypodense lesion in the liver.\nSmall collection in the pelvis.", "expected_covered": ["LIVER", "PELVIS"], "rule": "direct-location", "hard": false, "note": "prepositional location"}
{"id": "dl-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "MEDIASTINUM"], "scratchpad": "6 mm nodule in the right upper lobe of the lung.", "expected_covered": ["LUNGS"], "rule": "direct-location", "hard": false, "note": "lobe of the lung"}
{"id": "dm-01", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "MEDIASTINUM"], "scratchpad": "Small left pleural effusion.\nMediastinal lymphadenopathy.", "expected_covered": ["PLEURA", "MEDIASTINUM"], "rule": "direct-modifier", "hard": false, "note": "adjectival modifiers"}
{"id": "dm-02", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "KIDNEYS", "ADRENALS"], "scratchpad": "Hepatic haemangioma.\nRenal cyst on the left.", "expected_covered": ["LIVER", "KIDNEYS"], "rule": "direct-modifier", "hard": true, "note": "latinate modifiers hepatic/renal"}
{"id": "cg-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "SPLEEN", "PANCREAS", "BOWEL"], "scratchpad": "The solid abdominal organs are normal.", "expected_covered": ["LIVER", "SPLEEN", "PANCREAS"], "rule": "collective-group", "hard": false, "note": "solid organs group"}
{"id": "cg-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "BONES", "CHEST WALL"], "scratchpad": "No focal lung lesion.\nThe visualised bones and chest wall are unremarkable.", "expected_covered": ["LUNGS", "BONES", "CHEST WALL"], "rule": "collective-group", "hard": false, "note": "bones and chest wall named together"}
{"id": "cb-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "SPLEEN", "BOWEL", "AORTA"], "scratchpad": "The solid organs are normal.", "expected_covered": ["LIVER", "SPLEEN"], "rule": "collective-boundary", "hard": true, "note": "solid organs do not cover bowel or vessels"}
{"id": "cb-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "MEDIASTINUM", "UPPER ABDOMEN"], "scratchpad": "The thoracic structures are unremarkable.", "expected_covered": ["LUNGS", "PLEURA", "MEDIASTINUM"], "rule": "collective-boundary", "hard": true, "note": "thoracic claim does not reach upper abdomen"}
{"id": "cb-03", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "KIDNEYS", "LYMPH NODES", "BONES"], "scratchpad": "The abdominal viscera are normal.", "expected_covered": ["LIVER", "KIDNEYS"], "rule": "collective-boundary", "hard": true, "note": "viscera do not cover nodes or bones"}
{"id": "so-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "SPLEEN", "PANCREAS"], "scratchpad": "2 cm hypodense lesion in the liver.\nOtherwise the solid organs are normal.", "expected_covered": ["LIVER", "SPLEEN", "PANCREAS"], "rule": "specific-overrides-collective", "hard": false, "note": "specific plus clean-up collective"}
{"id": "so-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "MEDIASTINUM"], "scratchpad": "Right pleural effusion.\nThe remaining thoracic structures are normal.", "expected_covered": ["LUNGS", "PLEURA", "MEDIASTINUM"], "rule": "specific-overrides-collective", "hard": false, "note": "remaining structures"}
{"id": "bm-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "GALLBLADDER", "PANCREAS"], "scratchpad": "- Gallbladder\n- Pancreas normal", "expected_covered": ["PANCREAS"], "rule": "bare-mention", "hard": false, "note": "bare gallbladder line"}
{"id": "bm-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "HEART"], "scratchpad": "heart\nlungs clear", "expected_covered": ["LUNGS"], "rule": "bare-mention", "hard": false, "note": "bare word heart"}
{"id": "as-01", "scan_type": "CT abdomen pelvis", "checklist": ["GALLBLADDER", "BILE DUCTS", "LIVER"], "scratchpad": "The gallbladder wall is thickened.", "expected_covered": ["GALLBLADDER"], "rule": "adjacent-structure", "hard": true, "note": "gallbladder claim does not cover bile ducts"}
{"id": "as-02", "scan_type": "CT chest", "checklist": ["PLEURA", "LUNGS", "CHEST WALL"], "scratchpad": "Bibasal atelectasis.", "expected_covered": ["LUNGS"], "rule": "adjacent-structure", "hard": true, "note": "lung claim does not cover pleura"}
{"id": "pn-01", "scan_type": "CT abdomen pelvis", "checklist": ["KIDNEYS", "ADRENALS", "URETERS", "BLADDER"], "scratchpad": "The urinary tract is normal.", "expected_covered": ["KIDNEYS", "URETERS", "BLADDER"], "rule": "parent-not-enumerating", "hard": true, "note": "urinary tract covers its members but not adrenals"}
{"id": "pn-02", "scan_type": "CT chest", "checklist": ["TRACHEA", "MAIN BRONCHI", "LUNGS"], "scratchpad": "The central airways are patent.", "expected_covered": ["TRACHEA", "MAIN BRONCHI"], "rule": "parent-not-enumerating", "hard": true, "note": "central airways group"}
{"id": "ic-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "KIDNEYS", "SPLEEN"], "scratchpad": "Lesion in the liver abutting the right kidney.", "expected_covered": ["LIVER"], "rule": "incidental-co-mention", "hard": true, "note": "kidney only mentioned as a neighbour"}
{"id": "ic-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "MEDIASTINUM"], "scratchpad": "Nodule in the right lower lobe adjacent to the pleura.", "expected_covered": ["LUNGS"], "rule": "incidental-co-mention", "hard": true, "note": "pleura as location reference only"}
{"id": "vf-01", "scan_type": "CT abdomen pelvis", "checklist": ["LIVER", "SPLEEN", "KIDNEYS"], "scratchpad": "Everything else looks fine.", "expected_covered": [], "rule": "vague-filler", "hard": false, "note": "no anatomical scope"}
{"id": "vf-02", "scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "MEDIASTINUM"], "scratchpad": "Nothing else to report.", "expected_covered": [], "rule": "vague-filler", "hard": false, "note": "no scope"}
{"id": "ab-01", "scan_type": "CT abdomen pelvis", "checklist": ["COMMON BILE DUCT", "IVC", "AORTA"], "scratchpad": "CBD 4 mm.\nIVC patent.", "expected_covered": ["COMMON BILE DUCT", "IVC"], "rule": "abbreviation", "hard": false, "note": "CBD abbreviation with measurement"}
{"id": "ab-02", "scan_type": "MRI lumbar spine", "checklist": ["VERTEBRAL BODIES", "INTERVERTEBRAL DISCS", "SPINAL CANAL"], "scratchpad": "L4/5 disc bulge.\nCanal capacious.", "expected_covered": ["INTERVERTEBRAL DISCS", "SPINAL CANAL"], "rule": "abbreviation", "hard": true, "note": "level shorthand and canal short form"}
```

- [x] **Step 3: Run the validation test**

Run: `/Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/pytest backend/tests/test_coverage_fixtures.py -q --rootdir backend -c backend/pyproject.toml`
Expected: 3 PASS

- [x] **Step 4: Commit**

```bash
git add backend/tests/fixtures/coverage_cases.jsonl backend/tests/test_coverage_fixtures.py
git commit -m "test(coverage): 24 labelled coverage cases, two or more per rule"
```

---

### Task 4: Coverage bake-off script

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py`
- Test: `backend/tests/test_coverage_bakeoff.py`

- [x] **Step 1: Write the failing test for the pure scorer**

```python
# backend/tests/test_coverage_bakeoff.py
from rapid_reports_ai.scripts.coverage_bakeoff import Row, score


def test_score_per_section_and_exact_set():
    rows = [
        Row("a", "jev", ["L", "P", "M"], ["L", "P"], {"L": 0.9, "P": 0.8, "M": 0.1}, 300, None, False, "direct-subject", None),
        Row("b", "jev", ["L", "P", "M"], ["L"], {"L": 0.3, "P": 0.9, "M": 0.1}, 400, None, True, "bare-mention", None),
        Row("c", "jev", ["L"], ["L"], None, 0, None, False, "direct-subject", "TriageError"),
    ]
    s = score(rows)["jev"]
    assert s["n"] == 3 and s["errors"] == 1
    # sections: a: L tp, P tp, M tn; b: L fn, P fp, M tn  => tp=2 fp=1 fn=1
    assert s["precision"] == 2 / 3 and s["recall"] == 2 / 3
    assert s["exact_set_accuracy"] == 0.5
    assert s["by_rule"]["bare-mention"]["exact"] == 0.0
    assert s["hard"]["exact"] == 0.0
    assert s["latency_p50_ms"] == 350
    assert s["buckets"][">=0.95"]["n"] == 0 and s["buckets"]["0.8-0.95"]["n"] == 3
```

- [x] **Step 2: Implement**

```python
# backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py
"""Score both coverage candidates on tests/fixtures/coverage_cases.jsonl.

Usage (from backend/, keys loaded):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.coverage_bakeoff', run_name='__main__')"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Optional

from rapid_reports_ai.scripts.triage_summary import BUCKETS, _p

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "coverage_cases.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"


@dataclass(frozen=True)
class Row:
    id: str
    candidate: str
    checklist: list[str]
    expected: list[str]
    scores: Optional[dict[str, float]]
    latency_ms: int
    cost_usd: Optional[float]
    hard: bool
    rule: str
    error: Optional[str]


def _exact(row: Row, threshold: float = 0.5) -> bool:
    got = {s for s in row.checklist if (row.scores or {}).get(s, 0.0) >= threshold}
    return got == set(row.expected)


def score(rows: list[Row], threshold: float = 0.5) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    by_cand: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_cand[r.candidate].append(r)
    for cand, rs in by_cand.items():
        ok = [r for r in rs if r.error is None and r.scores is not None]
        tp = fp = fn = 0
        for r in ok:
            exp = set(r.expected)
            for s in r.checklist:
                got = r.scores.get(s, 0.0) >= threshold
                if got and s in exp:
                    tp += 1
                elif got:
                    fp += 1
                elif s in exp:
                    fn += 1
        by_rule: dict[str, dict[str, float]] = {}
        for rule in sorted({r.rule for r in ok}):
            rr = [r for r in ok if r.rule == rule]
            by_rule[rule] = {"n": len(rr), "exact": sum(_exact(r, threshold) for r in rr) / len(rr)}
        hard = [r for r in ok if r.hard]
        lat = [r.latency_ms for r in ok]
        buckets: dict[str, dict[str, float]] = {}
        per_section = [(r.scores[s], s in set(r.expected)) for r in ok for s in r.checklist if r.candidate == "jev"]
        if per_section:
            for name, lo, hi in BUCKETS:
                # bucket by distance from 0.5 mapped to a confidence in [0.5, 1]: conf = 0.5 + |p - 0.5|
                items = [(p, e) for p, e in per_section if lo <= 0.5 + abs(p - 0.5) < hi]
                buckets[name] = {
                    "n": len(items),
                    "accuracy": (sum((p >= threshold) == e for p, e in items) / len(items)) if items else 0.0,
                }
        out[cand] = {
            "n": len(rs),
            "errors": len(rs) - len(ok),
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "exact_set_accuracy": (sum(_exact(r, threshold) for r in ok) / len(ok)) if ok else 0.0,
            "by_rule": by_rule,
            "hard": {"n": len(hard), "exact": (sum(_exact(r, threshold) for r in hard) / len(hard)) if hard else 0.0},
            "latency_p50_ms": int(median(lat)) if lat else 0,
            "latency_p95_ms": _p(lat, 0.95),
            "cost_usd": round(sum(r.cost_usd or 0.0 for r in rs), 8),
            "buckets": buckets,
        }
    return out


def fmt(s: dict[str, dict[str, Any]]) -> str:
    lines = []
    for cand, m in s.items():
        lines.append(f"== {cand}: n={m['n']} errors={m['errors']} P={m['precision']:.3f} R={m['recall']:.3f} "
                     f"exact={m['exact_set_accuracy']:.3f} p50={m['latency_p50_ms']}ms p95={m['latency_p95_ms']}ms cost=${m['cost_usd']:.5f}")
        lines.append(f"   hard: n={m['hard']['n']} exact={m['hard']['exact']:.3f}")
        for rule, v in m["by_rule"].items():
            lines.append(f"   {rule:<30} n={v['n']:<3} exact={v['exact']:.2f}")
        for b, v in m["buckets"].items():
            lines.append(f"   conf {b:<8} n={v['n']:<4} accuracy={v['accuracy']:.3f}")
    return "\n".join(lines)


async def main() -> int:
    from rapid_reports_ai.canvas_routes import qwen_coverage
    from rapid_reports_ai.section_coverage import get_jev_coverage

    missing = [k for k in ("OPENROUTER_API_KEY", "CEREBRAS_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 2
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]
    sem = asyncio.Semaphore(4)

    async def run(case: dict) -> list[Row]:
        rows = []
        async with sem:
            for cand in ("jev", "qwen"):
                try:
                    if cand == "jev":
                        d = await get_jev_coverage().classify(case["scratchpad"], case["checklist"], case["scan_type"])
                    else:
                        d = await qwen_coverage(case["scratchpad"], case["checklist"], case["scan_type"])
                    rows.append(Row(case["id"], cand, case["checklist"], case["expected_covered"], d.scores, d.latency_ms, d.cost_usd, case["hard"], case["rule"], None))
                except Exception as e:
                    rows.append(Row(case["id"], cand, case["checklist"], case["expected_covered"], None, 0, None, case["hard"], case["rule"], type(e).__name__))
        return rows

    nested = await asyncio.gather(*(run(c) for c in cases))
    rows = [r for rs in nested for r in rs]
    s = score(rows)
    print(fmt(s))
    print("\n-- non-exact cases --")
    for r in rows:
        if r.error is None and not _exact(r):
            got = [x for x in r.checklist if r.scores.get(x, 0) >= 0.5]
            print(f"   {r.candidate:<4} {r.id:<6} {r.rule:<28} expected={r.expected} got={got}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"coverage-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": s, "rows": [r.__dict__ for r in rows]}, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [x] **Step 3: Run the test and commit**

Run: `/Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/pytest backend/tests/test_coverage_bakeoff.py -q --rootdir backend -c backend/pyproject.toml`
Expected: PASS

```bash
git add backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py backend/tests/test_coverage_bakeoff.py
git commit -m "feat(coverage): bake-off script scoring both candidates per section, per rule, by confidence"
```

---

### Task 5: Frontend pure helpers, types and lab config

**Files:**
- Modify: `frontend/src/lib/dictation-lab/types.ts` (append)
- Modify: `frontend/src/lib/dictation-lab/labConfig.ts`
- Create: `frontend/src/lib/dictation-lab/coverage.ts`, `coverage.test.ts`
- Modify: `frontend/src/lib/dictation-lab/labConfig.test.ts` (one expectation)

- [x] **Step 1: Types (append to `types.ts`)**

```ts
/** Mirrors backend CoverageCandidateTrace / CoverageTrace. */
export interface CoverageCandidateTrace {
	scores: Record<string, number> | null;
	covered: string[] | null;
	raw: string[] | null;
	latency_ms: number | null;
	input_tokens: number | null;
	cost_usd: number | null;
	error: string | null;
}
export interface CoverageTrace {
	selected: Candidate;
	jev: CoverageCandidateTrace | null;
	qwen: CoverageCandidateTrace | null;
}
export interface PillThresholds {
	hi: number; // >= hi → covered
	lo: number; // >= lo and < hi → partial
}
export type PillState = 'covered' | 'partial' | 'absent';
/** One line of tests/fixtures/coverage_cases.jsonl. */
export interface CoverageFixtureCase {
	id: string;
	scan_type: string;
	checklist: string[];
	scratchpad: string;
	expected_covered: string[];
	rule: string;
	hard: boolean;
	note: string;
}
```

Extend `LabConfig` in the same file:

```ts
export interface LabConfig {
	strategy: Strategy;
	threshold: number; // 0.5–1.0
	showBoth: boolean; // sets triage_debug
	coverageDebug: boolean; // sets coverage_debug on /review
	pillThresholds: PillThresholds;
}
```

- [x] **Step 2: labConfig defaults and validation**

In `labConfig.ts` set `DEFAULT_LAB_CONFIG` to `{ strategy: 'shadow', threshold: 0.9, showBoth: true, coverageDebug: true, pillThresholds: { hi: 0.8, lo: 0.4 } }`, and extend the `ok` check in `loadLabConfig`:

```ts
		const pt = p?.pillThresholds;
		const ok =
			STRATEGIES.includes(p?.strategy) &&
			typeof p?.threshold === 'number' && p.threshold >= 0.5 && p.threshold <= 1 &&
			typeof p?.showBoth === 'boolean' &&
			typeof p?.coverageDebug === 'boolean' &&
			typeof pt?.hi === 'number' && typeof pt?.lo === 'number' && pt.lo >= 0 && pt.lo < pt.hi && pt.hi <= 1;
		return ok
			? { strategy: p.strategy, threshold: p.threshold, showBoth: p.showBoth, coverageDebug: p.coverageDebug, pillThresholds: { hi: pt.hi, lo: pt.lo } }
			: { ...DEFAULT_LAB_CONFIG };
```

Update `labConfig.test.ts`: every literal `LabConfig` in the tests gains `coverageDebug: true, pillThresholds: { hi: 0.8, lo: 0.4 }` (the `toRequestFields` calls and the round-trip case); add one case:

```ts
	it('rejects inverted pill thresholds', () => {
		const fake = { getItem: () => JSON.stringify({ ...DEFAULT_LAB_CONFIG, pillThresholds: { hi: 0.3, lo: 0.6 } }) } as unknown as Storage;
		expect(loadLabConfig(fake)).toEqual(DEFAULT_LAB_CONFIG);
	});
```

- [x] **Step 3: Failing coverage helper tests**

```ts
// frontend/src/lib/dictation-lab/coverage.test.ts
import { describe, expect, it } from 'vitest';
import { buildCoverageFixtureLine, coverageAgreement, pillState } from './coverage';

const T = { hi: 0.8, lo: 0.4 };

describe('pillState', () => {
	it('maps scores to three states', () => {
		expect(pillState(0.95, T)).toBe('covered');
		expect(pillState(0.8, T)).toBe('covered');
		expect(pillState(0.5, T)).toBe('partial');
		expect(pillState(0.4, T)).toBe('partial');
		expect(pillState(0.1, T)).toBe('absent');
		expect(pillState(undefined, T)).toBe('absent');
	});
});

describe('coverageAgreement', () => {
	it('compares jev at 0.5 with qwen membership per section', () => {
		const a = coverageAgreement(['L', 'P', 'M'], { L: 0.9, P: 0.2, M: 0.6 }, ['L', 'M']);
		expect(a).toEqual({ L: 'agree', P: 'agree', M: 'agree' });
		const b = coverageAgreement(['L', 'P'], { L: 0.9, P: 0.7 }, ['L']);
		expect(b.P).toBe('jev-only');
		const c = coverageAgreement(['L'], { L: 0.2 }, ['L']);
		expect(c.L).toBe('qwen-only');
	});
});

describe('buildCoverageFixtureLine', () => {
	it('emits one JSON line in fixture key order', () => {
		const line = buildCoverageFixtureLine(
			{ scratchpad: '- liver normal', checklist: ['LIVER', 'SPLEEN'], scanType: 'CT AP' },
			{ id: 'lab-01', expected_covered: ['LIVER'], rule: 'direct-subject', hard: false, note: 'n' }
		);
		expect(line.includes('\n')).toBe(false);
		expect(Object.keys(JSON.parse(line))).toEqual(['id', 'scan_type', 'checklist', 'scratchpad', 'expected_covered', 'rule', 'hard', 'note']);
	});
});
```

- [x] **Step 4: Implement**

```ts
// frontend/src/lib/dictation-lab/coverage.ts
import type { CoverageFixtureCase, PillState, PillThresholds } from './types';

export function pillState(score: number | undefined, t: PillThresholds): PillState {
	if (score == null) return 'absent';
	if (score >= t.hi) return 'covered';
	if (score >= t.lo) return 'partial';
	return 'absent';
}

export type SectionAgreement = 'agree' | 'jev-only' | 'qwen-only';

/** Jev at the binary threshold versus Qwen membership, per section. */
export function coverageAgreement(
	sections: string[],
	jevScores: Record<string, number>,
	qwenCovered: string[],
	threshold = 0.5
): Record<string, SectionAgreement> {
	const q = new Set(qwenCovered);
	const out: Record<string, SectionAgreement> = {};
	for (const s of sections) {
		const j = (jevScores[s] ?? 0) >= threshold;
		const qq = q.has(s);
		out[s] = j === qq ? 'agree' : j ? 'jev-only' : 'qwen-only';
	}
	return out;
}

export type CoverageLabels = Pick<CoverageFixtureCase, 'id' | 'expected_covered' | 'rule' | 'hard' | 'note'>;

export function buildCoverageFixtureLine(
	state: { scratchpad: string; checklist: string[]; scanType: string },
	labels: CoverageLabels
): string {
	const c: CoverageFixtureCase = {
		id: labels.id,
		scan_type: state.scanType,
		checklist: state.checklist,
		scratchpad: state.scratchpad,
		expected_covered: labels.expected_covered,
		rule: labels.rule,
		hard: labels.hard,
		note: labels.note
	};
	return JSON.stringify(c);
}
```

- [x] **Step 5: Run and commit**

Run: `cd frontend && bun run test -- --project server src/lib/dictation-lab`
Expected: all pass (existing 14 plus the new ones).

Commit: `frontend/src/lib/dictation-lab` with message `feat(lab): coverage helpers, pill thresholds and coverage debug in lab config`.

---

### Task 6: Wire scores, trace and three-state pills through the components

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte` (`_runReview`, props)
- Modify: `frontend/src/routes/components/IntelliDictateTab.svelte` (props, pill block, scratchpad mount)
- Modify: `frontend/src/lib/components/DictationLabPanel.svelte` (Coverage section)
- Modify: `frontend/src/routes/dictation-lab/+page.svelte` (wiring)

- [x] **Step 1: DictationScratchpad**

Add to the type import: `CoverageTrace`. Add two props after `onProcessTrace`:

```ts
	/** Dictation Lab only. Per-section scores from the selected coverage candidate. */
	export let onCoverageScoresChange: (scores: Record<string, number> | null) => void = () => {};
	/** Dictation Lab only. Both candidates' coverage results when coverage_debug is on. */
	export let onCoverageTrace: (trace: CoverageTrace) => void = () => {};
```

In `_runReview`, change the request body and the response handling:

```ts
				body: JSON.stringify({
					scratchpad_content,
					checklist_sections: checklistSections,
					scan_type: scanType,
					clinical_history: clinicalHistory,
					mode: polishMode,
					...(labConfig ? { coverage_debug: labConfig.coverageDebug } : {})
				})
```

and after the existing `onCoveredSectionsChange(...)` block:

```ts
			onCoverageScoresChange(data.coverage_scores ?? null);
			if (data.coverage) onCoverageTrace(data.coverage as CoverageTrace);
```

- [x] **Step 2: IntelliDictateTab**

Imports: add `CoverageTrace, PillThresholds` to the type import and `import { pillState } from '$lib/dictation-lab/coverage';`. Props after `onProcessTrace`:

```ts
	export let pillThresholds: PillThresholds | null = null;   // lab only: three-state pills
	export let onCoverageTrace: (trace: CoverageTrace) => void = () => {};
	let coverageScores: Record<string, number> | null = null;
```

Pill block: replace the `{#each allChecklistSections as section}` body with:

```svelte
			{#each allChecklistSections as section}
				{@const state = pillThresholds && coverageScores
					? pillState(coverageScores[section], pillThresholds)
					: (coveredSections.has(section) ? 'covered' : 'absent')}
				<span
					class="px-2.5 py-1 rounded-full text-[11px] font-medium transition-all duration-300
					{state === 'covered'
						? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
						: state === 'partial'
							? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
							: 'bg-white/[0.04] text-gray-600 border border-white/[0.06]'}"
					title={coverageScores && coverageScores[section] != null ? coverageScores[section].toFixed(2) : undefined}
				>
					{section.replace(/_/g, ' ')}
				</span>
			{/each}
```

Scratchpad mount: add

```svelte
			onCoverageScoresChange={(s) => { coverageScores = s; }}
			{onCoverageTrace}
```

Also export, next to `injectTranscript`:

```ts
	export function getCoverageState(): { scratchpad: string; checklist: string[]; scanType: string } {
		return { scratchpad: scratchpadRef?.getContent() ?? '', checklist: prePoppedSections, scanType };
	}
```

Home page passes neither `pillThresholds` nor `onCoverageTrace`, so production pills keep the binary path.

- [x] **Step 3: Lab panel Coverage section**

Add props and state at the top of `DictationLabPanel.svelte`:

```ts
	import { buildCoverageFixtureLine, coverageAgreement } from '$lib/dictation-lab/coverage';
	import type { CoverageTrace } from '$lib/dictation-lab/types';
	export let coverageTrace: CoverageTrace | null = null;
	export let coverageState: { scratchpad: string; checklist: string[]; scanType: string } | null = null;

	let coverageBuffer = '';
	let coverageSeq = 1;
	let covExp = { expected: new Set<string>(), rule: 'direct-subject', hard: false, note: '' };
	const RULES = ['direct-subject', 'direct-location', 'direct-modifier', 'collective-group', 'collective-boundary', 'specific-overrides-collective', 'bare-mention', 'adjacent-structure', 'parent-not-enumerating', 'incidental-co-mention', 'vague-filler', 'abbreviation'];
	$: sections = coverageState?.checklist ?? [];
	$: agreement = coverageTrace?.jev?.scores && coverageTrace?.qwen?.covered
		? coverageAgreement(sections, coverageTrace.jev.scores, coverageTrace.qwen.covered)
		: {};
	function startCoverageExport(): void {
		const jev = coverageTrace?.jev?.scores ?? {};
		covExp = { expected: new Set(sections.filter((s) => (jev[s] ?? 0) >= 0.5)), rule: 'direct-subject', hard: false, note: '' };
	}
	function toggleExpected(s: string): void {
		const n = new Set(covExp.expected);
		if (n.has(s)) n.delete(s); else n.add(s);
		covExp = { ...covExp, expected: n };
	}
	function appendCoverageLine(): void {
		if (!coverageState) return;
		const line = buildCoverageFixtureLine(coverageState, {
			id: `lab-cov-${String(coverageSeq++).padStart(2, '0')}`,
			expected_covered: sections.filter((s) => covExp.expected.has(s)),
			rule: covExp.rule, hard: covExp.hard, note: covExp.note
		});
		coverageBuffer = coverageBuffer ? `${coverageBuffer}\n${line}` : line;
	}
```

Insert this section between **Strategy** and **Feeder** in the markup:

```svelte
	<!-- Coverage -->
	<section class="card-dark space-y-2">
		<h3 class="font-semibold">Coverage
			<span class="text-gray-400 font-normal">
				{#if coverageTrace}selected={coverageTrace.selected} · jev {coverageTrace.jev?.latency_ms ?? '—'}ms · qwen {coverageTrace.qwen?.latency_ms ?? '—'}ms{/if}
			</span>
		</h3>
		<label class="flex items-center gap-2"><input type="checkbox" bind:checked={$labConfig.coverageDebug} /> compare both candidates (coverage_debug)</label>
		<div class="flex gap-4 text-xs">
			<label>hi <input type="range" min="0.5" max="1" step="0.05" bind:value={$labConfig.pillThresholds.hi} /> {$labConfig.pillThresholds.hi.toFixed(2)}</label>
			<label>lo <input type="range" min="0" max="0.75" step="0.05" bind:value={$labConfig.pillThresholds.lo} /> {$labConfig.pillThresholds.lo.toFixed(2)}</label>
		</div>
		{#if coverageTrace}
			<table class="w-full text-xs">
				<thead><tr class="text-gray-400"><th class="text-left">section</th><th>jev p</th><th>qwen</th><th></th></tr></thead>
				<tbody>
					{#each sections as s}
						{@const p = coverageTrace.jev?.scores?.[s]}
						{@const q = coverageTrace.qwen?.covered?.includes(s)}
						<tr class={agreement[s] === 'agree' ? '' : agreement[s] === 'jev-only' ? 'text-amber-300' : 'text-red-300'}>
							<td>{s}</td>
							<td class="text-center tabular-nums">{p == null ? (coverageTrace.jev?.error ?? '—') : p.toFixed(2)}</td>
							<td class="text-center">{coverageTrace.qwen?.error ?? (q ? '✓' : '·')}</td>
							<td class="text-right text-gray-500">{agreement[s] ?? ''}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<button class="btn-secondary text-xs" on:click={startCoverageExport} disabled={!coverageState}>Add to coverage fixtures</button>
			{#if covExp.expected.size > 0 || coverageBuffer}
				<div class="flex flex-wrap gap-2">
					{#each sections as s}
						<label class="text-xs"><input type="checkbox" checked={covExp.expected.has(s)} on:change={() => toggleExpected(s)} /> {s}</label>
					{/each}
				</div>
				<div class="flex flex-wrap gap-2 items-center text-xs">
					<select class="bg-gray-900 rounded px-1" bind:value={covExp.rule}>{#each RULES as r}<option value={r}>{r}</option>{/each}</select>
					<label><input type="checkbox" bind:checked={covExp.hard} /> hard</label>
					<input class="bg-gray-900 rounded px-2 py-1 flex-1" placeholder="note" bind:value={covExp.note} />
					<button class="btn-primary text-xs" on:click={appendCoverageLine}>Append</button>
				</div>
				<textarea class="w-full h-16 bg-gray-900 rounded p-2 font-mono text-xs" readonly value={coverageBuffer}></textarea>
			{/if}
		{/if}
	</section>
```

- [x] **Step 4: Lab page wiring**

In `+page.svelte` add state and pass-throughs:

```ts
	import type { CoverageTrace } from '$lib/dictation-lab/types';
	let coverageTrace: CoverageTrace | null = null;
	let coverageState: { scratchpad: string; checklist: string[]; scanType: string } | null = null;
```

In the tab mount add:

```svelte
				pillThresholds={$labConfig.pillThresholds}
				onCoverageTrace={(t) => { coverageTrace = t; coverageState = tabRef?.getCoverageState?.() ?? null; }}
```

Update the page's `tabRef` type to `{ injectTranscript: (text: string, speechFinal?: boolean) => void; getCoverageState: () => { scratchpad: string; checklist: string[]; scanType: string } } | null`, and pass `{coverageTrace} {coverageState}` to `<DictationLabPanel>`.

- [x] **Step 5: Type-check the touched files and commit**

Run: `cd frontend && bun run check 2>&1 | grep -c 'DictationScratchpad.svelte\|IntelliDictateTab.svelte\|DictationLabPanel.svelte\|dictation-lab/'`
Expected: `0`

Commit `frontend/src` with message `feat(lab): coverage trace, three-state pills and coverage fixture export in the Dictation Lab`.

---

### Task 7: Bake-off, lab check, docs

- [x] **Step 1: Run the coverage bake-off**

Run from `backend/`: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv('/Users/hassan/Code/rapid_reports_ai/backend/.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.coverage_bakeoff', run_name='__main__')"`
Expected: two candidate blocks, non-exact cases listed, JSON written to `docs/model-migration/`.

- [x] **Step 2: Lab check**

Restart the backend (same command as before, `RR_TRIAGE_DEBUG=1`). In `/dictation-lab`, set up a CT abdomen workspace, feed `the liver is normal`, `the solid organs are unremarkable`, `gallbladder`, `everything else looks fine`. Expect: the Coverage table shows Jev probabilities next to Qwen ticks; LIVER covered; GALLBLADDER absent or partial, never covered; bowel-type sections not covered by the solid-organ collective; sliders move pill states live. Export one coverage case, append it to `coverage_cases.jsonl`, run `test_coverage_fixtures.py`.

- [x] **Step 3: Record and commit**

Add `## 7. Bake-off run 1 (<date>)` to the coverage spec with the summary block and two sentences against §5; set the spec status to implemented. Commit the JSON, the spec and the fixture line with message `docs(coverage): bake-off run 1 and lab-exported fixture`.

---

## Self-review notes

- Spec §3 → Task 1 (`COVERAGE_CRITERIA`, thresholds in code); §4.1 → Task 1; §4.2 → Task 2 (selection, debug, fallback rule, `coverage_scores`); §4.3 → Tasks 5–6; §4.4 → Tasks 3–4; §4.5 tests → Tasks 1–5; §5 → Task 7 records the run.
- Names: `get_jev_coverage`, `qwen_coverage`, `_intelliprompts`, `_coverage_safe` (Task 2) are what the route tests patch; `CoverageDecision.raw` (Task 1) is what `qwen_coverage` fills; frontend `pillState`, `coverageAgreement`, `buildCoverageFixtureLine` (Task 5) are what Task 6 imports; `getCoverageState` is defined on the tab and called by the page.
- The Qwen path's behaviour is preserved except that its log lines go through `logger` instead of `print`, and its covered list is returned in checklist order (previously in the model's order). Both are intentional.
