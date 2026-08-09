# Dictation Phase 1 — Stabilise & Instrument — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the tier-2 semantic dictation check (dead in production) and add per-stage latency instrumentation to the live speech path, plus two dead-code hygiene fixes — all low-risk, no schema changes, no new infrastructure.

**Architecture:** The tier-2 fix makes the semantic analyser run on the request's own event loop instead of `asyncio.run()` (which raises inside a running loop and is silently swallowed). The pure quote-locating logic is extracted so it stays sync-testable while the model call becomes properly async. Latency instrumentation adds a module `logging.Logger` to `canvas_routes.py` and times the untimed `/process` handler, standardising the existing `print()` stopwatches onto the logger; the `/api/transcribe` websocket gets a session-level timing log. Hygiene removes a stale comment and a fully-dead `getFindingCount()`.

**Tech Stack:** Python 3.13, FastAPI, pydantic / pydantic-ai, pytest + pytest-asyncio (`asyncio_mode = "auto"`), Poetry. Frontend: SvelteKit / CodeMirror.

**Spec:** `docs/superpowers/specs/2026-08-09-dictation-fidelity-and-orchestration-design.md` (§7.1, §7.2, §8 Phase 1).

**Scope note / open decision (does NOT block this plan):** Phase 1 in the spec also lists a per-session **zero-edit / manual-correction metric**. The repo has *no* generic events table and *no* frontend telemetry emitter; the established precedent is `compute_edit_burden()` (`quality_scoring.py:479`) persisted as `ReportQualityScore.edit_burden`. Emitting a *live* dictation zero-edit signal therefore requires a persistence decision (reuse/extend the offline `edit_burden` scorer vs. build a new emitter+column). That decision is raised to the user separately; this plan delivers the tier-2 fix, latency instrumentation, and hygiene, which are fully specified and independently shippable.

**Run tests with:** `poetry run pytest` from `/Users/hassan/Code/rapid_reports_ai/backend` (config: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["src"]`).

---

## File Structure

**Modify:**
- `backend/src/rapid_reports_ai/dictation_semantic.py` — extract pure `_locate_flags()`; make `_default_analyse` and `check_semantic` `async`.
- `backend/src/rapid_reports_ai/main.py` — `await check_semantic(...)` in `/api/dictation/check`; add session timing log to `/api/transcribe`.
- `backend/src/rapid_reports_ai/canvas_routes.py` — add module logger; time `process_transcript`; convert coverage/IntelliPrompts `print()` stopwatches to the logger.
- `backend/tests/test_dictation_semantic.py` — adapt to async `check_semantic`; add locating tests against `_locate_flags`.
- `backend/tests/test_dictation_check_route.py` — make monkeypatched `check_semantic` fakes async.
- `frontend/src/lib/components/DictationScratchpad.svelte` — fix stale comment; delete dead `getFindingCount()`.
- `frontend/src/routes/components/IntelliDictateTab.svelte` — drop `getFindingCount` from the `scratchpadRef` interface.
- `frontend/src/routes/components/TemplateForm.svelte` — drop `getFindingCount` from the `scratchpadRef` interface.

**Create:**
- `backend/tests/test_dictation_semantic_async.py` — regression test that reproduces and locks the running-loop bug.
- `backend/tests/test_canvas_timing.py` — asserts `process_transcript` emits a timing log.

---

## Task 1: Regression test that reproduces the tier-2 running-loop bug

The production path is `POST /api/dictation/check` (async) → `check_semantic(...)` (no `analyse=` injected) → `_default_analyse` → `asyncio.run(...)`, which raises `RuntimeError` inside the already-running loop and is swallowed by `check_semantic`'s bare `except`, so it always returns `[]`. This test exercises that real default path with the model call stubbed, and will pass only once the analyser runs on the request loop.

**Files:**
- Create: `backend/tests/test_dictation_semantic_async.py`

- [ ] **Step 1: Write the failing regression test**

```python
# backend/tests/test_dictation_semantic_async.py
"""Regression test for the tier-2 semantic check running-loop bug.

The default analyser must run on the caller's event loop. Previously it used
asyncio.run() inside the async /api/dictation/check handler, which raised
RuntimeError, was swallowed, and made tier-2 silently return no flags in prod.
"""
from __future__ import annotations

import rapid_reports_ai.enhancement_utils as eu
from rapid_reports_ai.dictation_semantic import (
    SemanticIssue,
    SemanticFindings,
    check_semantic,
)

FINDINGS = (
    "- MRI of the right ankle demonstrates a joint effusion.\n"
    "- There is oedema within the left ankle mortise."
)


async def test_default_analyser_runs_on_the_request_loop(monkeypatch):
    """check_semantic, called from a running loop with NO injected analyser,
    must reach the model and return a located flag — not swallow a RuntimeError."""

    class _Result:
        output = SemanticFindings(
            issues=[
                SemanticIssue(
                    kind="laterality_conflict",
                    quote="left ankle mortise",
                    message="Findings mention both a right and a left ankle.",
                )
            ]
        )

    async def _stub_run(**kwargs):
        return _Result()

    # _default_analyse imports these from enhancement_utils at call time, so we
    # patch them at the source module.
    monkeypatch.setattr(eu, "_run_agent_with_model", _stub_run)
    monkeypatch.setattr(eu, "_get_api_key_for_provider", lambda provider: "test-key")
    monkeypatch.setattr(eu, "_get_model_provider", lambda model: "cerebras")

    flags = await check_semantic("MRI ankle", "right ankle pain", FINDINGS)

    assert len(flags) == 1
    assert FINDINGS[flags[0].start:flags[0].end] == "left ankle mortise"
    assert flags[0].kind == "laterality_conflict"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `poetry run pytest tests/test_dictation_semantic_async.py -v`
Expected: FAIL. Against current code `check_semantic` is synchronous and returns a `list`, so `await check_semantic(...)` raises `TypeError: object list can't be used in 'await' expression` (a red result driving the async refactor).

---

## Task 2: Make the semantic analyser async; extract pure locating logic

**Files:**
- Modify: `backend/src/rapid_reports_ai/dictation_semantic.py:93-180`
- Modify: `backend/tests/test_dictation_semantic.py`

- [ ] **Step 1: Extract the pure quote-locating logic into `_locate_flags`**

Replace the body of `check_semantic` (lines 137-180) so the locating loop lives in a standalone pure function. New code:

```python
def _locate_flags(findings: str, result: SemanticFindings) -> list[IntegrityFlag]:
    """Turn model-reported issues into located advisory flags (pure, no I/O).

    Drops any issue whose quote is not a verbatim substring of ``findings`` —
    an unplaceable flag is worse than none. Uses rfind so a repeated phrase
    resolves to the later (contradicting) restatement.
    """
    flags: list[IntegrityFlag] = []
    for issue in result.issues:
        quote = (issue.quote or "").strip()
        if not quote:
            continue
        start = findings.rfind(quote)
        if start == -1:
            continue
        flags.append(
            IntegrityFlag(
                kind=issue.kind,
                severity=_MEDIUM,
                excerpt=quote[:60],
                message=issue.message,
                start=start,
                end=start + len(quote),
            )
        )
    return flags
```

- [ ] **Step 2: Make `_default_analyse` async (drop `asyncio.run`)**

Replace `_default_analyse` (lines 93-134). It now awaits the model call directly on the caller's loop:

```python
async def _default_analyse(
    scan_type: str, clinical_history: str, findings: str
) -> SemanticFindings:
    """Real analyser: one model call via the shared agent runner, on the caller's loop.

    Uses the STRUCTURE_VALIDATOR slot (a fast Cerebras model): this runs in a
    user-facing pause, so latency matters more than depth.
    """
    import asyncio

    from .enhancement_utils import (
        MODEL_CONFIG,
        _get_api_key_for_provider,
        _get_model_provider,
        _run_agent_with_model,
    )

    model = MODEL_CONFIG["STRUCTURE_VALIDATOR"]
    api_key = _get_api_key_for_provider(_get_model_provider(model))

    user_prompt = (
        f"Scan type: {scan_type or '(not given)'}\n"
        f"Clinical history: {clinical_history or '(not given)'}\n\n"
        f"Dictation:\n{findings}"
    )

    result = await asyncio.wait_for(
        _run_agent_with_model(
            model_name=model,
            output_type=SemanticFindings,
            system_prompt=SEMANTIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=False,
            model_settings={"temperature": 0.0, "max_tokens": 800},
        ),
        timeout=20,
    )
    return result.output
```

- [ ] **Step 3: Make `check_semantic` async and delegate to `_locate_flags`**

Replace the `check_semantic` definition. It supports a sync *or* async injected `analyse` (tests inject sync fakes; production uses the async default):

```python
import inspect  # add to the imports block at top of file (line ~26)


async def check_semantic(
    scan_type: str,
    clinical_history: str,
    findings: str | None,
    *,
    analyse: Optional[Callable[[str, str, str], SemanticFindings]] = None,
) -> list[IntegrityFlag]:
    """Return advisory flags for semantic problems. Empty list means clean.

    ``analyse`` is injected in tests; it defaults to the model-backed analyser
    and may be sync or async. Any failure returns an empty list — a degraded
    check must never block or surface an error to a radiologist mid-dictation.
    """
    if not findings or not findings.strip():
        return []

    try:
        result = (analyse or _default_analyse)(
            scan_type or "", clinical_history or "", findings
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        return []

    return _locate_flags(findings, result)
```

Note: `import inspect` goes in the top imports block (around line 26, alongside `from typing import ...`). Keep `_MEDIUM = "medium"` where it is.

- [ ] **Step 4: Adapt the existing unit tests to the new shapes**

In `backend/tests/test_dictation_semantic.py`: the pure locating assertions move to `_locate_flags` (still sync); the behaviour tests (`check_semantic`) become `async`. Update imports and tests:

```python
from rapid_reports_ai.dictation_semantic import (
    SemanticIssue,
    SemanticFindings,
    check_semantic,
    _locate_flags,
)


def _fake(issues):
    def _analyse(scan_type, clinical_history, findings):
        return SemanticFindings(issues=issues)
    return _analyse


FINDINGS = (
    "- MRI of the right ankle demonstrates a joint effusion.\n"
    "- There is oedema within the left ankle mortise."
)


# --- pure locating logic (was exercised via check_semantic) ---

def test_issue_is_located_and_offsets_are_exact():
    issue = SemanticIssue(
        kind="laterality_conflict",
        quote="left ankle mortise",
        message="Findings mention both a right and a left ankle.",
    )
    flags = _locate_flags(FINDINGS, SemanticFindings(issues=[issue]))
    assert len(flags) == 1
    assert FINDINGS[flags[0].start:flags[0].end] == "left ankle mortise"
    assert flags[0].kind == "laterality_conflict"


def test_hallucinated_span_is_dropped():
    issue = SemanticIssue(
        kind="internal_contradiction",
        quote="the spleen is enlarged",
        message="m",
    )
    assert _locate_flags(FINDINGS, SemanticFindings(issues=[issue])) == []


def test_last_occurrence_is_used_for_repeated_quotes():
    repeated = "no effusion. no effusion."
    issue = SemanticIssue(kind="internal_contradiction", quote="no effusion", message="m")
    flags = _locate_flags(repeated, SemanticFindings(issues=[issue]))
    assert flags[0].start == repeated.rfind("no effusion")


# --- async check_semantic behaviour (injected sync analyser) ---

async def test_no_issues_returns_empty():
    assert await check_semantic("MRI ankle", "", FINDINGS, analyse=_fake([])) == []


async def test_blank_dictation_never_calls_the_model():
    called = []

    def _spy(scan_type, clinical_history, findings):
        called.append(1)
        return SemanticFindings(issues=[])

    assert await check_semantic("MRI ankle", "", "   ", analyse=_spy) == []
    assert called == []


async def test_model_failure_is_non_blocking():
    def _boom(scan_type, clinical_history, findings):
        raise RuntimeError("model exploded")

    assert await check_semantic("MRI ankle", "", FINDINGS, analyse=_boom) == []
```

(Retain any other existing tests, converting `check_semantic(...)` calls to `await check_semantic(...)` inside `async def` and pointing pure-locating assertions at `_locate_flags`.)

- [ ] **Step 5: Run the semantic unit + regression tests to green**

Run: `poetry run pytest tests/test_dictation_semantic.py tests/test_dictation_semantic_async.py -v`
Expected: PASS (all). The Task 1 regression test now passes because `_default_analyse` awaits on the request loop.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/dictation_semantic.py backend/tests/test_dictation_semantic.py backend/tests/test_dictation_semantic_async.py
git commit -m "fix(dictation): run tier-2 semantic analyser on request loop (was dead in prod)"
```

---

## Task 3: Await `check_semantic` in the endpoint; fix route-test fakes

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py:2597-2602`
- Modify: `backend/tests/test_dictation_check_route.py`

- [ ] **Step 1: Update the route-test fakes to async (write the expectation first)**

In `backend/tests/test_dictation_check_route.py`, the endpoint will now `await check_semantic`, so monkeypatched fakes must be awaitable. Update `test_semantic_is_off_by_default`:

```python
def test_semantic_is_off_by_default(authed_client, monkeypatch):
    """The idle path must never spend a model call."""
    called = []
    import rapid_reports_ai.dictation_semantic as ds

    async def _fake_check(*a, **k):
        called.append(1)
        return []

    monkeypatch.setattr(ds, "check_semantic", _fake_check)

    r = authed_client.post(
        "/api/dictation/check", json={"findings": "- lungs are clear."}
    )
    assert r.status_code == 200
    assert called == []
```

Apply the same async-fake change to any other test in this file that monkeypatches `ds.check_semantic` (e.g. `test_semantic_skipped_when_tier1_already_flagged`, `test_semantic_flags_do_not_gate`): replace `lambda *a, **k: ...` with an `async def _fake_check(*a, **k): return <list>`.

- [ ] **Step 2: Run the route tests and confirm they fail**

Run: `poetry run pytest tests/test_dictation_check_route.py -v`
Expected: FAIL — endpoint still calls `check_semantic` synchronously, so the semantic-enabled path returns a coroutine (or the async fake is never awaited). This drives the endpoint change.

- [ ] **Step 3: Await `check_semantic` in the endpoint**

In `backend/src/rapid_reports_ai/main.py`, `dictation_check_endpoint`, change the tier-2 call (line ~2600):

```python
    if request.include_semantic and not flags:
        from .dictation_semantic import check_semantic

        flags = flags + await check_semantic(
            request.scan_type or "", request.clinical_history or "", request.findings
        )
```

(Only `flags = flags + check_semantic(...)` → `flags = flags + await check_semantic(...)`. The endpoint is already `async def`.)

- [ ] **Step 4: Run the route tests to green**

Run: `poetry run pytest tests/test_dictation_check_route.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `poetry run pytest -q`
Expected: PASS (no new failures introduced).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_dictation_check_route.py
git commit -m "fix(dictation): await tier-2 semantic check in /api/dictation/check"
```

---

## Task 4: Time the `/process` handler (the dominant, untimed live-path cost)

`process_transcript` has no timing today. Add a module logger and record model latency.

**Files:**
- Modify: `backend/src/rapid_reports_ai/canvas_routes.py` (imports/top + `process_transcript` ~501-538)
- Create: `backend/tests/test_canvas_timing.py`

- [ ] **Step 1: Write the failing timing test**

```python
# backend/tests/test_canvas_timing.py
"""process_transcript must emit a per-request latency log for the live path."""
from __future__ import annotations

import logging

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.canvas_routes import process_transcript, CanvasProcessRequest, CanvasProcessResponse


async def test_process_transcript_logs_latency(monkeypatch, caplog):
    async def _stub_run(**kwargs):
        class _R:
            output = CanvasProcessResponse(scratchpad="- liver is normal", covered_sections=[])
        return _R()

    monkeypatch.setattr(cr, "_run_agent_with_model", _stub_run)
    monkeypatch.setattr(cr, "_get_model_provider", lambda model: "groq")
    monkeypatch.setattr(cr, "_get_api_key_for_provider", lambda provider: "test-key")

    req = CanvasProcessRequest(
        session_transcript="the liver is normal",
        scratchpad_content="",
        scan_type="CT abdomen",
        clinical_history="",
        preferred_section_names=[],
    )

    with caplog.at_level(logging.INFO, logger="rapid_reports_ai.canvas_routes"):
        out = await process_transcript(req, current_user=None)

    assert out.scratchpad == "- liver is normal"
    assert any("[canvas.process]" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `poetry run pytest tests/test_canvas_timing.py -v`
Expected: FAIL — no `[canvas.process]` log record is emitted (and `_run_agent_with_model`/`_get_model_provider` may not yet be module-level names monkeypatchable on `cr`; if the test errors on `AttributeError`, that is still red — the next step wires them as module-level references used by the handler).

- [ ] **Step 3: Add a module logger and time the model call**

At the top of `canvas_routes.py` (with the other imports), add:

```python
import logging
import time as _time  # if not already imported at module level

logger = logging.getLogger(__name__)
```

In `process_transcript`, wrap the model call with timing and log on both success and failure:

```python
    t0 = _time.perf_counter()
    try:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=CanvasProcessResponse,
            system_prompt=CANVAS_PROCESS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=False,
            model_settings={"temperature": 0.7, "top_p": 0.8, "max_tokens": 8000, "extra_body": {"reasoning_effort": "none"}},
        )
        elapsed = _time.perf_counter() - t0
        logger.info(
            "[canvas.process] %.2fs model=%s transcript_chars=%d scratchpad_chars=%d",
            elapsed, model_name, len(request.session_transcript or ""), len(request.scratchpad_content or ""),
        )
        return result.output
    except Exception as e:
        elapsed = _time.perf_counter() - t0
        import traceback
        logger.error("[canvas.process] ❌ %.2fs %s: %s", elapsed, type(e).__name__, e)
        traceback.print_exc()
        return CanvasProcessResponse(scratchpad=request.scratchpad_content, covered_sections=[])
```

Ensure `_run_agent_with_model`, `_get_model_provider`, `_get_api_key_for_provider` are referenced as module-level names in `canvas_routes.py` (they are already imported there — verify the imports so the monkeypatch in Step 1 targets the right module).

- [ ] **Step 4: Run the timing test to green**

Run: `poetry run pytest tests/test_canvas_timing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/tests/test_canvas_timing.py
git commit -m "feat(dictation): instrument /api/canvas/process latency"
```

---

## Task 5: Standardise review stopwatches on the logger; add `/transcribe` session timing

Consistency + basic ASR-stage observability. Low-risk log-line changes (no behaviour change), verified by not breaking the suite.

**Files:**
- Modify: `backend/src/rapid_reports_ai/canvas_routes.py` (coverage `:623/:627`, IntelliPrompts `:661/:707`)
- Modify: `backend/src/rapid_reports_ai/main.py` (`websocket_transcribe` ~4881-5020)

- [ ] **Step 1: Convert the coverage/IntelliPrompts `print()` stopwatches to the logger**

Replace the existing `print(...)` timing lines with `logger.info(...)` / `logger.error(...)` using the module `logger` added in Task 4:

```python
# coverage (was canvas_routes.py:623 / :627)
logger.info("[canvas.coverage] %.2fs → %s", elapsed, covered)
# ...
logger.error("[canvas.coverage] ❌ %.2fs %s: %s", elapsed, type(e).__name__, e)

# intelliprompts (was canvas_routes.py:661 / :707)
logger.info("[canvas.intelliprompts] %s %.2fs → %d prompts", label, elapsed, len(validated))
# ...
logger.error("[canvas.intelliprompts] ❌ %.2fs %s: %s", elapsed, type(e).__name__, e)
```

- [ ] **Step 2: Add session-level timing to the transcribe websocket**

In `main.py` `websocket_transcribe`, add a module logger reference (`logger` already exists at `main.py:8`) and record session duration + finalised-utterance count. At the start of the accepted session:

```python
    _t_session = _perf.perf_counter()
    _finals = 0
```

(Add `import time as _perf` near the top of `main.py` if no suitable timer alias exists.) Increment `_finals` where finalised transcripts are handled (inside `forward_from_deepgram`, in the `if is_final and transcript:` branch), and on disconnect/close log:

```python
    logger.info("[transcribe] session %.1fs finals=%d", _perf.perf_counter() - _t_session, _finals)
```

Place the summary log in the disconnect/cleanup path so it fires when the socket closes. Keep the existing per-utterance `print(f"📝 ...")` line (or convert it to `logger.info`) — that is a judgement call; converting keeps output consistent.

- [ ] **Step 3: Run the full suite (no regressions)**

Run: `poetry run pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/src/rapid_reports_ai/main.py
git commit -m "chore(dictation): route review stopwatches through logger; add transcribe session timing"
```

---

## Task 6: Hygiene — stale comment + dead `getFindingCount`

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte:110-113` and `:221-223`
- Modify: `frontend/src/routes/components/IntelliDictateTab.svelte:73`
- Modify: `frontend/src/routes/components/TemplateForm.svelte:125`

- [ ] **Step 1: Fix the stale sliding-window comment**

Replace `DictationScratchpad.svelte:110-111`:

```javascript
	// Sliding window of recent dictation — last 600 chars. The scratchpad is the persistent
	// memory; Qwen only needs recent context to resolve the current utterance.
```

with:

```javascript
	// Sliding window of recent dictation — last SESSION_TRANSCRIPT_WINDOW chars. The
	// scratchpad is the persistent memory; the model only needs recent context to
	// resolve the current utterance.
```

- [ ] **Step 2: Delete the dead `getFindingCount()` definition**

Remove `DictationScratchpad.svelte:221-223`:

```javascript
	export function getFindingCount(): number {
		return (getContent().match(/^- /gm) || []).length;
	}
```

- [ ] **Step 3: Remove it from both `scratchpadRef` interface declarations**

In `IntelliDictateTab.svelte` (line 73) and `TemplateForm.svelte` (line 125), delete the line:

```javascript
		getFindingCount: () => number;
```

- [ ] **Step 4: Verify no references remain**

Run: `grep -rn "getFindingCount" /Users/hassan/Code/rapid_reports_ai/frontend/src`
Expected: no output (zero matches).

- [ ] **Step 5: Verify the frontend still type-checks**

Run the frontend type-check from `/Users/hassan/Code/rapid_reports_ai/frontend` (confirm the exact script in `frontend/package.json` — typically `npm run check`, i.e. `svelte-check`).
Expected: no new type errors from these files.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte frontend/src/routes/components/IntelliDictateTab.svelte frontend/src/routes/components/TemplateForm.svelte
git commit -m "chore(dictation): fix stale window comment; remove dead getFindingCount"
```

---

## Task 7: Zero-edit baseline via the existing `edit_burden` signal (reuse, no new infra)

The spec's per-session zero-edit metric reuses `compute_edit_burden()` (`quality_scoring.py:479`), where `edit_burden == 0.0` means the AI draft was signed unchanged — already persisted on `ReportQualityScore.edit_burden` by the offline scorer. Phase 1 adds a deterministic aggregate so the pre-Phase-2 baseline is computable. This is a whole-pipeline (report-level) proxy; a dictation-isolated scratchpad-edit signal remains the deferred frontend-emitter option.

**Files:**
- Modify: `backend/src/rapid_reports_ai/quality_scoring.py` (add `zero_edit_rate` beside `compute_edit_burden`)
- Create: `backend/tests/test_zero_edit_rate.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_zero_edit_rate.py
from rapid_reports_ai.quality_scoring import zero_edit_rate


def test_zero_edit_rate_ignores_none_and_rounds():
    # 4 comparable (2 zero-edit) → 0.5; the None is excluded
    assert zero_edit_rate([0.0, 0.0, 0.2, None, 0.5]) == 0.5


def test_zero_edit_rate_all_none_is_none():
    assert zero_edit_rate([None, None]) is None


def test_zero_edit_rate_empty_is_none():
    assert zero_edit_rate([]) is None
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `poetry run pytest tests/test_zero_edit_rate.py -v`
Expected: FAIL — `ImportError: cannot import name 'zero_edit_rate'`.

- [ ] **Step 3: Implement `zero_edit_rate`**

Add beside `compute_edit_burden` in `quality_scoring.py` (ensure `Iterable` is imported from `typing`):

```python
def zero_edit_rate(edit_burdens: Iterable[Optional[float]]) -> Optional[float]:
    """Fraction of reports signed with no edits (edit_burden == 0.0).

    Ignores ``None`` (no final text to compare against). Returns ``None`` when
    there is no comparable report.
    """
    scored = [b for b in edit_burdens if b is not None]
    if not scored:
        return None
    return round(sum(1 for b in scored if b == 0.0) / len(scored), 4)
```

- [ ] **Step 4: Run the test to green**

Run: `poetry run pytest tests/test_zero_edit_rate.py -v`
Expected: PASS.

- [ ] **Step 5: Surface it in Metabase (analytics, no app code)**

Add a card over `report_quality_scores` restricted to in-scope reports (see `analytics_scope.in_scope_reports`), e.g. `SELECT pipeline, AVG((edit_burden = 0)::int) AS zero_edit_rate, COUNT(*) FROM report_quality_scores WHERE edit_burden IS NOT NULL GROUP BY pipeline;` (confirm exact column/scope join against `docs/analytics/metabase/build_dashboard.py`). Confirm the offline scorer populates `edit_burden` for dictation-pipeline reports so the baseline is non-empty before Phase 2 ships.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/quality_scoring.py backend/tests/test_zero_edit_rate.py
git commit -m "feat(dictation): zero_edit_rate aggregate over existing edit_burden signal"
```

---

## Self-Review

**Spec coverage (Phase 1):**
- §7.1 tier-2 fix → Tasks 1–3. ✅ (with a regression test that reproduces the exact bug)
- §7.2 per-stage latency on `/process` and `/transcribe` → Tasks 4–5. ✅
- §7.2 zero-edit metric → Task 7 (deterministic aggregate reusing `edit_burden` + Metabase card). ✅ Report-level baseline; dictation-isolated scratchpad-edit signal still deferred to the frontend-emitter option.
- §8 hygiene (stale comment, dead `getFindingCount`) → Task 6. ✅

**Placeholder scan:** No "TBD"/"add error handling"/"similar to". The one non-code judgement (whether to convert the per-utterance transcribe `print`) is called out explicitly with both options, not left vague. The frontend type-check command is flagged to confirm against `package.json` (the deletion is verified independently by the Step-4 grep).

**Type consistency:** `_locate_flags(findings: str, result: SemanticFindings) -> list[IntegrityFlag]` is defined in Task 2 Step 1 and imported/called identically in Task 2 Step 4 tests. `check_semantic` is `async` everywhere it is called post-Task-2 (Task 3 endpoint `await`s it; route-test fakes are `async`). `IntegrityFlag` is the frozen dataclass from `dictation_integrity.py` (unchanged). The `cr`-module monkeypatch targets (`_run_agent_with_model`, `_get_model_provider`, `_get_api_key_for_provider`) match the names Task 4 Step 3 requires at module level.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, two-stage review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.
