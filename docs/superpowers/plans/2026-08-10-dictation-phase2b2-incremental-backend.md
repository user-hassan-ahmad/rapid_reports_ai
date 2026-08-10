# Dictation Phase 2b.2 (backend) — Incremental /process with frozen committed + patch edits — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `/api/canvas/process` an **incremental** path: the scratchpad is split into a **frozen committed** prefix (read-only context, never regenerated) and a mutable **active** tail. The model rewrites only `active`, and emits explicit `committed_edits` for directed corrections to frozen text — so settled findings can't drift, generation stays small, and corrections still reach back.

**Architecture:** Backward-compatible and behind the request shape — when `committed_context` is present, run incremental (new prompt suffix + `CanvasIncrementalResponse` output = `active_scratchpad` + `committed_edits`); when it's absent, run today's full regeneration unchanged. The freeze guarantee holds because the model never re-emits committed text — the frontend (next plan) applies the verbatim `committed_edits` deterministically. This plan is the backend contract only; **nothing changes in production until the frontend opts in** (separate plan).

**Tech Stack:** Python 3.13, FastAPI, pydantic-ai (structured output forces the response schema), pytest `asyncio_mode=auto`. Model: Cerebras `gemma-4-31b` + `gpt-oss-120b` fallback via `_run_canvas_with_fallback`.

**Spec:** `docs/superpowers/specs/2026-08-09-dictation-fidelity-and-orchestration-design.md` §7.3. Design agreed in-session: freeze-on-pause + **always-send-committed-as-context**, model decides + patches (no regex correction-detection).

**Run tests:** `poetry run pytest` from `/Users/hassan/Code/rapid_reports_ai/backend`.

---

## File Structure
- Modify `backend/src/rapid_reports_ai/canvas_routes.py`: add `CommittedEdit` + `CanvasIncrementalResponse` models; `committed_context` field on `CanvasProcessRequest`; `CANVAS_INCREMENTAL_SUFFIX` + `CANVAS_INCREMENTAL_USER_PROMPT_TEMPLATE`; extend `_canvas_process_config(mode, incremental=False)`; branch `process_transcript` on `committed_context`.
- Create `backend/tests/test_canvas_incremental.py`.

---

## Task 1: Models + request field

**Files:** Modify `canvas_routes.py:42-59`. Create `backend/tests/test_canvas_incremental.py`.

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_canvas_incremental.py
from __future__ import annotations

from rapid_reports_ai.canvas_routes import (
    CanvasProcessRequest,
    CommittedEdit,
    CanvasIncrementalResponse,
)


def test_committed_context_defaults_none_full_mode():
    req = CanvasProcessRequest(session_transcript="x", scratchpad_content="")
    assert req.committed_context is None  # absent => full regeneration


def test_incremental_response_shape():
    r = CanvasIncrementalResponse(
        active_scratchpad="- liver normal",
        committed_edits=[CommittedEdit(original="5 mm nodule", corrected="10 mm nodule")],
    )
    assert r.active_scratchpad == "- liver normal"
    assert r.committed_edits[0].corrected == "10 mm nodule"


def test_incremental_response_defaults_no_edits():
    assert CanvasIncrementalResponse(active_scratchpad="x").committed_edits == []
```

- [ ] **Step 2: Run — expect ImportError**

Run: `poetry run pytest tests/test_canvas_incremental.py -q`
Expected: FAIL — `cannot import name 'CommittedEdit'`.

- [ ] **Step 3: Add the `committed_context` field** to `CanvasProcessRequest` (after line 48):

```python
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
```

- [ ] **Step 4: Add the incremental response models** (after `CanvasProcessResponse`, line 59):

```python
class CommittedEdit(BaseModel):
    original: str   # exact verbatim line from the committed (frozen) zone
    corrected: str  # its directed correction


class CanvasIncrementalResponse(BaseModel):
    active_scratchpad: str
    committed_edits: list[CommittedEdit] = []
```

- [ ] **Step 5: Run — green**

Run: `poetry run pytest tests/test_canvas_incremental.py -q`
Expected: PASS (3).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/tests/test_canvas_incremental.py
git commit -m "feat(dictation): incremental request field + response models"
```

---

## Task 2: Incremental prompt + config selector

**Files:** Modify `canvas_routes.py` (add prompts near `CANVAS_PROCESS_USER_PROMPT_TEMPLATE` :415-434; extend `_canvas_process_config` :559-574). Modify the test file.

- [ ] **Step 1: Failing test** — append to `test_canvas_incremental.py`:

```python
from rapid_reports_ai.canvas_routes import (
    _canvas_process_config,
    CANVAS_CLEAN_SYSTEM_PROMPT,
    CANVAS_PROCESS_SYSTEM_PROMPT,
    CANVAS_INCREMENTAL_SUFFIX,
)


def test_full_config_unchanged():
    prompt, _ = _canvas_process_config("clean")  # incremental defaults False
    assert prompt is CANVAS_CLEAN_SYSTEM_PROMPT
    assert CANVAS_INCREMENTAL_SUFFIX not in prompt


def test_incremental_clean_appends_suffix():
    prompt, settings = _canvas_process_config("clean", incremental=True)
    assert prompt.startswith(CANVAS_CLEAN_SYSTEM_PROMPT)
    assert CANVAS_INCREMENTAL_SUFFIX in prompt
    assert settings["temperature"] == 0.15


def test_incremental_structured_appends_suffix():
    prompt, settings = _canvas_process_config("structured", incremental=True)
    assert prompt.startswith(CANVAS_PROCESS_SYSTEM_PROMPT)
    assert CANVAS_INCREMENTAL_SUFFIX in prompt
    assert settings["temperature"] == 0.3
```

- [ ] **Step 2: Run — expect failure** (`cannot import name 'CANVAS_INCREMENTAL_SUFFIX'`).

- [ ] **Step 3: Add the incremental prompt suffix + user template** (after `CANVAS_PROCESS_USER_PROMPT_TEMPLATE`, line 434):

```python
CANVAS_INCREMENTAL_SUFFIX = """

# Incremental mode

The scratchpad is split into two zones:

- COMMITTED — findings the radiologist has already settled. FROZEN context. Do not rewrite, reorder, or re-emit any of it.
- ACTIVE — the finding(s) currently in flight. This is the ONLY text you rewrite.

Apply the new dictation to the ACTIVE text, following every rule above.

Reaching back: if — and only if — the new dictation explicitly corrects, retracts, or changes something already in COMMITTED (e.g. "actually that was 10 mm", "no, the mass is on the left"), emit a committed_edit giving the exact original COMMITTED line and its corrected version. Never edit committed text for style — only to apply a directed correction. When nothing in COMMITTED is corrected, emit no committed_edits.

# Response shape (incremental — overrides the shape above)

- `active_scratchpad` — the complete updated ACTIVE text, per the rules above
- `committed_edits` — list of `{original, corrected}` for directed corrections to COMMITTED; empty when none. `original` MUST be copied verbatim from the COMMITTED zone or it will be discarded."""


CANVAS_INCREMENTAL_USER_PROMPT_TEMPLATE = """## Reference context — disambiguation only, never a source of findings

- **Scan type:** {scan_type}
- **Clinical history:** {clinical_history}

## COMMITTED — frozen, context only, do not rewrite

{committed_context}

## ACTIVE — update this

{active_scratchpad}

## Dictation transcript — single source of truth

{session_transcript}

---

Update the ACTIVE text. Emit committed_edits only for directed corrections to COMMITTED."""
```

- [ ] **Step 4: Extend `_canvas_process_config`** (replace lines 559-574):

```python
def _canvas_process_config(mode: str, incremental: bool = False) -> tuple[str, dict]:
    """Return (system_prompt, model_settings) for the polish mode. Defaults to Clean.

    Cerebras settings form (max_completion_tokens + reasoning_effort); reasoning_effort
    'low' keeps Gemma 4 fast and literal. When ``incremental`` is set, the incremental
    suffix (frozen COMMITTED + patch-edit response) is appended to the base prompt.
    """
    if mode == "structured":
        base_prompt = CANVAS_PROCESS_SYSTEM_PROMPT
        settings = {"temperature": 0.3, "max_completion_tokens": 8000, "reasoning_effort": "low"}
    else:
        base_prompt = CANVAS_CLEAN_SYSTEM_PROMPT
        settings = {"temperature": 0.15, "max_completion_tokens": 8000, "reasoning_effort": "low"}
    if incremental:
        return base_prompt + CANVAS_INCREMENTAL_SUFFIX, settings
    return base_prompt, settings
```

- [ ] **Step 5: Run — green** (`poetry run pytest tests/test_canvas_incremental.py -q`). Also `poetry run pytest tests/test_canvas_modes.py -q` (the existing `_canvas_process_config` tests still pass — the default `incremental=False` keeps them valid).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/tests/test_canvas_incremental.py
git commit -m "feat(dictation): incremental prompt suffix + config selector branch"
```

---

## Task 3: `/process` incremental branch

**Files:** Modify `process_transcript` (`canvas_routes.py:619-662`). Modify the test file.

- [ ] **Step 1: Failing tests** — append to `test_canvas_incremental.py`:

```python
import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.canvas_routes import process_transcript, CanvasProcessResponse


async def test_full_path_when_no_committed_context(monkeypatch):
    captured = {}

    async def _stub(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings, use_thinking=False, label=""):
        captured["output_type"] = output_type
        return CanvasProcessResponse(scratchpad="- full", covered_sections=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _stub)
    out = await process_transcript(
        CanvasProcessRequest(session_transcript="t", scratchpad_content="- full"), current_user=None
    )
    assert captured["output_type"] is CanvasProcessResponse
    assert out.scratchpad == "- full"


async def test_incremental_path_when_committed_context_present(monkeypatch):
    captured = {}

    async def _stub(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings, use_thinking=False, label=""):
        captured["output_type"] = output_type
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return CanvasIncrementalResponse(active_scratchpad="- active updated", committed_edits=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _stub)
    out = await process_transcript(
        CanvasProcessRequest(
            session_transcript="new words",
            scratchpad_content="- active",       # the ACTIVE tail
            committed_context="- committed line", # frozen prefix
        ),
        current_user=None,
    )
    assert captured["output_type"] is CanvasIncrementalResponse
    assert cr.CANVAS_INCREMENTAL_SUFFIX in captured["system_prompt"]
    assert "- committed line" in captured["user_prompt"]   # committed sent as context
    assert out.active_scratchpad == "- active updated"


async def test_incremental_error_guard_returns_active_unchanged(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("all models failed")

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _boom)
    out = await process_transcript(
        CanvasProcessRequest(session_transcript="t", scratchpad_content="- active", committed_context="- c"),
        current_user=None,
    )
    assert isinstance(out, CanvasIncrementalResponse)
    assert out.active_scratchpad == "- active"  # unchanged; committed untouched
    assert out.committed_edits == []
```

- [ ] **Step 2: Run — expect failure** (incremental request still runs the full path → returns `CanvasProcessResponse`, assertions fail).

- [ ] **Step 3: Branch `process_transcript` on `committed_context`.** Replace the body from line 625 (`primary_model = ...`) down to the end of the handler (line 662) with:

```python
    primary_model = MODEL_CONFIG["CANVAS_PROCESS"]
    fallback_model = MODEL_CONFIG.get("CANVAS_PROCESS_FALLBACK")
    incremental = request.committed_context is not None
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
```

Also relax the route decorator so both response shapes serialize — change line 619:

```python
@canvas_router.post("/process")
```

(drop `response_model=CanvasProcessResponse`; the handler returns the correct model per path. Full-mode JSON is unchanged.)

- [ ] **Step 4: Run incremental tests + full suite**

Run: `poetry run pytest tests/test_canvas_incremental.py -v && poetry run pytest -q`
Expected: PASS (all). `test_canvas_timing.py` + `test_canvas_modes.py` still green (full path unchanged; default request has `committed_context=None`).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/tests/test_canvas_incremental.py
git commit -m "feat(dictation): /process incremental branch (frozen committed + patch edits)"
```

---

## Self-Review

**Spec coverage (§7.3, backend half):** frozen committed as read-only context ✅ (Task 2 prompt, Task 3 wiring); model returns active + patch edits, never regenerates committed ✅ (`CanvasIncrementalResponse`, structured-output-enforced); backward-compatible full path ✅ (Task 3 branch, default `committed_context=None`). Frontend boundary tracking / commit-on-pause / edit application = **next plan** (this is backend only).

**Placeholder scan:** none. The conflicting "Response shape" in the base prompt vs the incremental suffix is intentional and safe — pydantic-ai's structured output *forces* `CanvasIncrementalResponse`, so the schema wins regardless of prose; the suffix text just aligns the model's reasoning.

**Type consistency:** `CanvasIncrementalResponse{active_scratchpad, committed_edits}` and `CommittedEdit{original, corrected}` are defined in Task 1 and used identically in Tasks 2–3 and tests. `_canvas_process_config(mode, incremental=False)` — the new kwarg defaults False, so existing callers (the full path, `test_canvas_modes.py`) are unaffected.

**Risk note:** dropping `response_model=` loses OpenAPI response validation for this route. Acceptable — the handler returns validated pydantic models either way; the trade buys a clean dual-shape response without a union wrapper.

---

## Execution Handoff

Plan complete. Two options: **1. Subagent-driven** (fresh subagent per task) or **2. Inline** (here, with checkpoints). Which?

**After this:** the paired **2b.2-frontend plan** — track the committed boundary in the editor doc, freeze all-but-last statement on `UtteranceEnd`, send `committed_context`/active, and apply `committed_edits` verbatim (drop-if-not-found) — behind a client flag so we can A/B against full regeneration.
