# Dictation Phase 2a (core) — Verbatim Clean vs Structured modes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-report **mode** to the scratchpad polish — **Verbatim Clean** (new, default) preserves the radiologist's own words/order/formatting; **Structured** keeps today's anatomical-bullet behaviour — switchable via a UI toggle.

**Architecture:** `/api/canvas/process` gains a `mode` param that selects the system prompt + decoding params via a pure `_canvas_process_config(mode)` helper; everything else (model, `_run_canvas_with_fallback`, `CanvasProcessResponse` schema, error guard, timing) is unchanged. `/api/canvas/review` accepts `mode` (plumbing only in this slice). The frontend owns a `polishMode` state (persisted in the draft store), renders a two-option toggle inside `DictationScratchpad` (shared by both tabs), sends `mode` in the `/process` + `/review` bodies, and re-runs `/process` on flip.

**Tech Stack:** Python 3.13, FastAPI, pydantic-ai, pytest (`asyncio_mode=auto`), Poetry. Frontend: SvelteKit, CodeMirror, Tailwind, localStorage draft store. Model: Cerebras `gemma-4-31b` primary + `gpt-oss-120b` fallback.

**Spec:** `docs/superpowers/specs/2026-08-09-dictation-fidelity-and-orchestration-design.md` (§6.1, §6.2, §6.3, §6.6, D1/D2).

**Scope note — deferred to a 2a-hardening plan (NOT here):** deterministic dictated-break validation (§6.4), the `scratch that`/`delete that` lexicon (§6.5), the IntelliPrompts framing branch (§7.7), and Deepgram finalization-timing (§6.4). Clean mode's corrections + break-preservation ship as *prompt instructions* here; the deterministic guarantees layer on later. Freeze-settled-text/incremental is Phase 2b.

**Run backend tests:** `poetry run pytest` from `/Users/hassan/Code/rapid_reports_ai/backend`. **Frontend check:** `npm run check` from `frontend/` (note: ~1200 pre-existing svelte-check errors unrelated to this work — judge only the touched files).

---

## File Structure

**Backend — modify `backend/src/rapid_reports_ai/canvas_routes.py`:**
- `CanvasProcessRequest` / `CanvasReviewRequest` — add `mode: str = "clean"`.
- Add `CANVAS_CLEAN_SYSTEM_PROMPT` constant (near `CANVAS_PROCESS_SYSTEM_PROMPT`).
- Add `_canvas_process_config(mode)` helper.
- `process_transcript` — select prompt+settings via the helper.

**Backend — create `backend/tests/test_canvas_modes.py`.**

**Frontend:**
- `frontend/src/lib/stores/draft.js` — add `mode` to both tabs; bump `SCHEMA_VERSION` 3→4.
- `frontend/src/lib/components/DictationScratchpad.svelte` — `polishMode` prop + `onModeChange` callback; send `mode` in both fetch bodies; render the toggle; re-run on flip.
- `frontend/src/routes/components/IntelliDictateTab.svelte` — own `polishMode`, persist/restore, pass down.
- `frontend/src/routes/components/TemplateForm.svelte` — same.

---

## Task 1: Backend — `mode` field, Clean prompt, config selector

**Files:**
- Modify: `backend/src/rapid_reports_ai/canvas_routes.py` (`CanvasProcessRequest` :42, `CanvasReviewRequest` :61, add prompt + helper near :239/:504)
- Create: `backend/tests/test_canvas_modes.py`

- [ ] **Step 1: Write the failing tests for the config selector**

```python
# backend/tests/test_canvas_modes.py
"""Mode → (system prompt, decoding params) selection for the scratchpad polish."""
from __future__ import annotations

from rapid_reports_ai.canvas_routes import (
    _canvas_process_config,
    CANVAS_CLEAN_SYSTEM_PROMPT,
    CANVAS_PROCESS_SYSTEM_PROMPT,
)


def test_clean_mode_uses_clean_prompt_and_low_temp():
    prompt, settings = _canvas_process_config("clean")
    assert prompt is CANVAS_CLEAN_SYSTEM_PROMPT
    assert settings["temperature"] == 0.15


def test_structured_mode_uses_structured_prompt_and_retuned_temp():
    prompt, settings = _canvas_process_config("structured")
    assert prompt is CANVAS_PROCESS_SYSTEM_PROMPT
    assert settings["temperature"] == 0.3  # down from the current 0.7


def test_unknown_or_missing_mode_defaults_to_clean():
    assert _canvas_process_config("")[0] is CANVAS_CLEAN_SYSTEM_PROMPT
    assert _canvas_process_config("wobble")[0] is CANVAS_CLEAN_SYSTEM_PROMPT


def test_clean_prompt_forbids_bullets_and_regrouping():
    # Guard the load-bearing Clean-mode instructions against accidental edits.
    p = CANVAS_CLEAN_SYSTEM_PROMPT
    assert "do NOT reduce to bullet fragments" in p
    assert "Revisions" in p
    assert "authoritative" in p  # dictated line/paragraph breaks
```

- [ ] **Step 2: Run and confirm failure**

Run: `poetry run pytest tests/test_canvas_modes.py -v`
Expected: FAIL — `ImportError: cannot import name '_canvas_process_config'` (and `CANVAS_CLEAN_SYSTEM_PROMPT`).

- [ ] **Step 3: Add the Clean system prompt**

In `canvas_routes.py`, immediately after `CANVAS_PROCESS_SYSTEM_PROMPT` (ends line 239), add:

```python
CANVAS_CLEAN_SYSTEM_PROMPT = """# Role

You clean up a radiologist's live dictation so it reads as their own words, tidied. Your single source of truth is the transcript. You preserve what they said and how they said it; you remove only the debris of speaking aloud.

# Hard fidelity rule

You do not complete, restructure, or summarise. Do not add findings, descriptors, or qualifiers they did not dictate. Do not reorganise, regroup, or reorder their findings. Do not compress sentences into notes. The radiologist must recognise the result as their own speech with the ums removed — not a rewritten summary.

# Remove (and nothing else)

- Filler / disfluency: "um", "uh", "you know", "sort of", stutters, repeated words
- Dictation control debris left in the text: stray "okay", "let's start", "next"
- Thinking-aloud with no clinical content: "right so", "let me see", "as I was saying"
- False starts / self-corrections: keep the corrected intent, drop the abandoned attempt

# Preserve exactly

- Their sentence structure, phrasing, word choice, and the order they said things in
- All clinical substance: measurements with units, laterality, location, confidence qualifiers, temporal comparators, staging, specific pathology terms
- Natural connecting prose — keep whole sentences; do NOT reduce to bullet fragments

# Speech-to-text correction (surface form only)

Fix clear homophones / phonetic ASR errors using radiology knowledge, the scan type and clinical history, and terms already established this session. Phonetic proximity plus context consistency is the test. Correction changes spelling, never substance or phrasing. When unsure, keep the transcript verbatim.

# Date format

Dates use British format — DD/MM/YYYY. Only the surface form changes.

# Revisions (explicit changes to prior content)

When a later utterance explicitly corrects, replaces, or retracts something said earlier — signalled by "actually", "no", "sorry", "I mean", "scratch that", "correction", or by directly contradicting a prior value — apply the change to the earlier text and remove the correction utterance itself, so the scratchpad reads as if the final version was said first. Make the MINIMAL edit: change only what the correction changes; leave the rest of that finding, every other finding, and all dictated line/paragraph breaks exactly as dictated. This is a licence to apply directed corrections only — never to rephrase or reorganise anything the radiologist did not ask you to change.

Correction versus comparison: "it's not 5 mm, it's 10 mm" is a correction (5 mm is gone); "it was 5 mm on the prior, now 10 mm" is a temporal comparison (both stay). When genuinely ambiguous, KEEP BOTH and let the radiologist resolve it — never silently erase a measurement.

# Output

Preserve the radiologist's own structure. Treat existing line and paragraph breaks in the transcript as authoritative — never merge across them or reorder across them. One distinct statement per line, in the order dictated. Where the radiologist ran several findings together without a break, you MAY add a line break for readability, but explicit breaks always win. Apply sensible punctuation and capitalisation (surface tidying, never new words). Do NOT regroup by anatomy or add bullet symbols. Plain text, update in place.

# Scratchpad field content

These rules describe what goes *inside* the `scratchpad` string of your structured response — plain text only, no markdown, no headings, no bold.

# Response shape

Your reply is a structured object with two fields:

- `scratchpad` — the complete updated cleaned dictation, formatted per the Output rules
- `covered_sections` — always return an empty list `[]`. Coverage is computed in a separate pass.

When the transcript contains no clinical content yet, return an empty `scratchpad` string. Never emit raw text outside the structured response."""
```

- [ ] **Step 4: Add the config selector**

Add near the other module helpers (e.g. just above `_run_canvas_with_fallback` at line 504):

```python
def _canvas_process_config(mode: str) -> tuple[str, dict]:
    """Return (system_prompt, model_settings) for the polish mode. Defaults to Clean.

    Cerebras settings form (max_completion_tokens + reasoning_effort); reasoning_effort
    'low' keeps Gemma 4 fast and literal. Both Gemma and the gpt-oss fallback accept it.
    """
    if mode == "structured":
        return (
            CANVAS_PROCESS_SYSTEM_PROMPT,
            {"temperature": 0.3, "max_completion_tokens": 8000, "reasoning_effort": "low"},
        )
    # Clean is the default for any other/blank value.
    return (
        CANVAS_CLEAN_SYSTEM_PROMPT,
        {"temperature": 0.15, "max_completion_tokens": 8000, "reasoning_effort": "low"},
    )
```

- [ ] **Step 5: Add the `mode` request field**

`CanvasProcessRequest` (line 42) — add `mode`:

```python
class CanvasProcessRequest(BaseModel):
    session_transcript: str
    scratchpad_content: str
    scan_type: str = ""
    clinical_history: str = ""
    preferred_section_names: list[str] = []
    mode: str = "clean"  # "clean" (Verbatim Clean, default) | "structured"
```

`CanvasReviewRequest` (line 61) — add the same field (plumbing; framing branch deferred):

```python
class CanvasReviewRequest(BaseModel):
    scratchpad_content: str
    checklist_sections: list[str] = []
    scan_type: str = ""
    clinical_history: str = ""
    mode: str = "clean"
```

- [ ] **Step 6: Run the tests to green**

Run: `poetry run pytest tests/test_canvas_modes.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/tests/test_canvas_modes.py
git commit -m "feat(dictation): add Clean-mode prompt + mode config selector"
```

---

## Task 2: Backend — `/process` selects prompt + params by mode

**Files:**
- Modify: `backend/src/rapid_reports_ai/canvas_routes.py` (`process_transcript` :564-575)
- Modify: `backend/tests/test_canvas_modes.py`

- [ ] **Step 1: Write the failing integration test**

Append to `test_canvas_modes.py`:

```python
import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.canvas_routes import process_transcript, CanvasProcessRequest, CanvasProcessResponse


async def _capture_process(mode, monkeypatch):
    """Call process_transcript with _run_canvas_with_fallback stubbed to record args."""
    captured = {}

    async def _stub(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings, use_thinking=False, label=""):
        captured["system_prompt"] = system_prompt
        captured["model_settings"] = model_settings
        return CanvasProcessResponse(scratchpad="- ok", covered_sections=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _stub)
    req = CanvasProcessRequest(session_transcript="the liver is normal", scratchpad_content="", mode=mode)
    await process_transcript(req, current_user=None)
    return captured


async def test_process_clean_mode_selects_clean_prompt(monkeypatch):
    captured = await _capture_process("clean", monkeypatch)
    assert captured["system_prompt"] is cr.CANVAS_CLEAN_SYSTEM_PROMPT
    assert captured["model_settings"]["temperature"] == 0.15


async def test_process_structured_mode_selects_structured_prompt(monkeypatch):
    captured = await _capture_process("structured", monkeypatch)
    assert captured["system_prompt"] is cr.CANVAS_PROCESS_SYSTEM_PROMPT
    assert captured["model_settings"]["temperature"] == 0.3


async def test_process_defaults_to_clean(monkeypatch):
    captured = await _capture_process("", monkeypatch)
    assert captured["system_prompt"] is cr.CANVAS_CLEAN_SYSTEM_PROMPT
```

- [ ] **Step 2: Run and confirm failure**

Run: `poetry run pytest tests/test_canvas_modes.py -k process -v`
Expected: FAIL — `/process` still passes the hardcoded `CANVAS_PROCESS_SYSTEM_PROMPT` and `{"temperature": 0.7, ...}`, so clean-mode assertions fail.

- [ ] **Step 3: Wire the config into `process_transcript`**

Replace the `system_prompt=` / `model_settings=` args in the `_run_canvas_with_fallback` call (currently lines 570 & 572) so they come from the selector. The block becomes:

```python
    system_prompt, model_settings = _canvas_process_config(request.mode)

    # Cerebras settings form (max_completion_tokens; no top_p/extra_body). Gemma 4 and the
    # gpt-oss-120b fallback are both Cerebras and accept the same shape.
    t0 = _time.perf_counter()
    try:
        output = await _run_canvas_with_fallback(
            primary_model,
            fallback_model,
            output_type=CanvasProcessResponse,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_settings=model_settings,
            use_thinking=False,
            label="canvas.process",
        )
        elapsed = _time.perf_counter() - t0
        logger.info(
            "[canvas.process] %.2fs mode=%s primary=%s transcript_chars=%d scratchpad_chars=%d",
            elapsed, request.mode, primary_model, len(request.session_transcript or ""), len(request.scratchpad_content or ""),
        )
        return output
```

(Insert `system_prompt, model_settings = _canvas_process_config(request.mode)` just before the `t0 = ...` line; add `mode=%s` / `request.mode` to the log as shown. Leave the `except` block unchanged.)

- [ ] **Step 4: Run modes tests + full suite**

Run: `poetry run pytest tests/test_canvas_modes.py -v && poetry run pytest -q`
Expected: PASS (all). The Phase-1 `test_canvas_timing.py` still passes (it uses default mode → clean; it only asserts a `[canvas.process]` log exists).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/canvas_routes.py backend/tests/test_canvas_modes.py
git commit -m "feat(dictation): /process selects prompt + params by mode (Clean default)"
```

---

## Task 3: Frontend — persist `mode` in the draft store

**Files:**
- Modify: `frontend/src/lib/stores/draft.js` (`SCHEMA_VERSION` :6, `EMPTY_STATE` :8-23, `saveIntelliTab` :60, `saveTemplateTab` :76)

- [ ] **Step 1: Bump the schema version** (line 6) — this discards stale v3 drafts on next load:

```javascript
const SCHEMA_VERSION = 4;
```

- [ ] **Step 2: Add `mode` to `EMPTY_STATE`** (lines 10-21):

```javascript
	intelliTab: {
		clinicalHistory: '',
		scanType: '',
		prePoppedSections: [],
		scratchpadContent: '',
		mode: 'clean'
	},
	templateTab: {
		templateId: null,
		variables: {},
		prePoppedSections: [],
		scratchpadContent: '',
		mode: 'clean'
	},
```

- [ ] **Step 3: Thread `mode` through the save functions**

`saveIntelliTab` (line 60) — add a `mode` param and persist it:

```javascript
		saveIntelliTab(clinicalHistory, scanType, prePoppedSections, scratchpadContent, mode = 'clean') {
			let latest;
			update((draft) => {
				latest = {
					...draft,
					intelliTab: { clinicalHistory, scanType, prePoppedSections: prePoppedSections ?? [], scratchpadContent, mode },
					savedAt: Date.now()
				};
				return latest;
			});
			if (browser) {
				clearTimeout(intelliDebounce);
				intelliDebounce = setTimeout(() => persistToStorage(latest), DEBOUNCE_MS);
			}
		},
```

`saveTemplateTab` (line 76) — add `mode` param and include it in the `templateTab` object:

```javascript
		saveTemplateTab(templateId, variables, prePoppedSections, scratchpadContent, mode = 'clean') {
			let latest;
			update((draft) => {
				latest = {
					...draft,
					templateTab: {
						templateId,
						variables: { ...variables },
						prePoppedSections: prePoppedSections ?? [],
						scratchpadContent: scratchpadContent ?? '',
						mode
					},
					savedAt: Date.now()
				};
				return latest;
			});
			if (browser) {
				clearTimeout(templateDebounce);
				templateDebounce = setTimeout(() => persistToStorage(latest), DEBOUNCE_MS);
			}
		},
```

(Do NOT add `mode` to the `hasIntelliContent`/`hasTemplateContent` predicates — mode alone must not count as draft content.)

- [ ] **Step 4: Verify it parses**

Run: `cd frontend && npm run check 2>&1 | grep -iE "draft.js" | grep -i error || echo "no new errors in draft.js"`
Expected: no new errors in `draft.js`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/stores/draft.js
git commit -m "feat(dictation): persist polish mode in draft store (schema v4)"
```

---

## Task 4: Frontend — `DictationScratchpad` sends `mode` + hosts the toggle

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte` (props :15-25, `processTranscript` :275-281, `_runReview` :358-363, header :606-623)

- [ ] **Step 1: Add the `polishMode` prop + change callback** (in the `export let` block, after line 18):

```svelte
	export let polishMode: 'clean' | 'structured' = 'clean';
	export let onModeChange: (mode: 'clean' | 'structured') => void = () => {};
```

- [ ] **Step 2: Send `mode` in the `/process` body** (line 275-281 object) — add `mode: polishMode`:

```javascript
				body: JSON.stringify({
					session_transcript: sessionTranscript,
					scratchpad_content: editor.state.doc.toString(),
					scan_type: scanType,
					clinical_history: clinicalHistory,
					preferred_section_names: checklistSections,
					mode: polishMode
				})
```

- [ ] **Step 3: Send `mode` in the `/review` body** (line 358-363 object) — add `mode: polishMode`:

```javascript
				body: JSON.stringify({
					scratchpad_content,
					checklist_sections: checklistSections,
					scan_type: scanType,
					clinical_history: clinicalHistory,
					mode: polishMode
				})
```

- [ ] **Step 4: Add the toggle + flip handler**

Add a handler near the other functions (e.g. after `processTranscript`):

```javascript
	function setMode(mode: 'clean' | 'structured') {
		if (mode === polishMode) return;
		polishMode = mode;
		onModeChange(mode);
		// Re-run the polish on the current context so the visible scratchpad
		// starts converting to the new mode. (Full re-derivation of long
		// scratchpads waits on Phase 2b's incremental rework.)
		if (editor && editor.state.doc.length > 0) processTranscriptQueue();
	}
```

Render the toggle inside the header strip (the `<div class="flex flex-col items-center gap-1.5 relative z-10">` at line 609), directly under the dictate button, using the project's existing segmented-control idiom:

```svelte
			<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5" role="group" aria-label="Polish mode">
				<button type="button" onclick={() => setMode('clean')}
					class={polishMode === 'clean'
						? 'px-2.5 py-1 text-xs rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
						: 'px-2.5 py-1 text-xs rounded-md text-gray-400 hover:text-gray-300'}>
					Verbatim
				</button>
				<button type="button" onclick={() => setMode('structured')}
					class={polishMode === 'structured'
						? 'px-2.5 py-1 text-xs rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
						: 'px-2.5 py-1 text-xs rounded-md text-gray-400 hover:text-gray-300'}>
					Structured
				</button>
			</div>
```

- [ ] **Step 5: Verify it parses**

Run: `cd frontend && npm run check 2>&1 | grep -iE "DictationScratchpad" | grep -i error || echo "no new errors in DictationScratchpad"`
Expected: no new errors in the file.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(dictation): mode toggle in scratchpad; send mode to /process and /review"
```

---

## Task 5: Frontend — parents own `polishMode`, persist + pass down

**Files:**
- Modify: `frontend/src/routes/components/IntelliDictateTab.svelte` (state ~:17, embed :850-863, save :548, restore :552-565)
- Modify: `frontend/src/routes/components/TemplateForm.svelte` (state ~:136, embed :761-774, its save/restore)

- [ ] **Step 1: IntelliDictateTab — add state, pass down, persist, restore**

Add state near `scanType`/`clinicalHistory` (line ~18):

```javascript
	let polishMode: 'clean' | 'structured' = 'clean';
```

Pass into the embed (in the `<DictationScratchpad ... />` at line 850-863, add):

```svelte
				{polishMode}
				onModeChange={(m) => { polishMode = m; }}
```

Persist — update the `saveIntelliTab` call (line 548) to include mode:

```javascript
		) draftStore.saveIntelliTab(clinicalHistory, scanType, prePoppedSections, scratchpadContent, polishMode);
```

Restore — in `restoreIntelliDraft` (line 552-565), after reading the other fields:

```javascript
		polishMode = draft.intelliTab.mode ?? 'clean';
```

- [ ] **Step 2: TemplateForm — same wiring**

Add `let polishMode: 'clean' | 'structured' = 'clean';` near line 136. Pass `{polishMode}` + `onModeChange={(m) => { polishMode = m; }}` into the `<DictationScratchpad>` embed (line 761-774). Thread `polishMode` into its `draftStore.saveTemplateTab(...)` call and read `draft.templateTab.mode ?? 'clean'` in its restore path. (Mirror the exact save/restore call sites that already exist in this file.)

- [ ] **Step 3: Verify both parse**

Run: `cd frontend && npm run check 2>&1 | grep -iE "IntelliDictateTab|TemplateForm" | grep -i error || echo "no new errors in touched tab components"`
Expected: no new errors in the two files.

- [ ] **Step 4: Manual smoke (dev or deployed)**

With the app running: dictate → confirm the scratchpad reads as Verbatim Clean by default; click **Structured** → confirm it re-runs and re-groups into bullets; reload the page → confirm the last mode is restored. Backend logs show `[canvas.process] …s mode=clean|structured …`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/components/IntelliDictateTab.svelte frontend/src/routes/components/TemplateForm.svelte
git commit -m "feat(dictation): tabs own + persist polish mode, pass to scratchpad"
```

---

## Self-Review

**Spec coverage (2a-core):**
- §6.1 mode routing → Tasks 1-2 (`/process`), Task 1 (`/review` field). ✅ (IntelliPrompts framing branch deferred — noted.)
- §6.2 Verbatim Clean prompt (default) → Task 1. ✅
- §6.3 Structured retune (0.7→0.3) → Task 1 config + Task 2 wiring. ✅
- §6.6 params (Cerebras form, per mode) → Task 1. ✅
- D2 Clean default + per-report toggle + remember last → Tasks 3-5. ✅
- Deferred (documented): §6.4 break-validation + finalization, §6.5 scratch-that lexicon, §7.7 framing branch → 2a-hardening.

**Placeholder scan:** No TBD/"handle errors". Frontend TemplateForm save/restore (Task 5 Step 2) references "the exact call sites that already exist" — acceptable because the file's `saveTemplateTab`/restore pattern was captured and mirrors IntelliDictateTab; the executor mirrors Step 1's concrete edits.

**Type consistency:** `mode`/`polishMode` is `'clean' | 'structured'` everywhere; backend field `mode: str = "clean"`; `_canvas_process_config(mode) -> (str, dict)` used identically in Task 1 tests and Task 2 wiring; draft `mode` defaults to `'clean'` in `EMPTY_STATE`, both save fns, and both restores.

**Behaviour caveat surfaced:** flip re-runs `/process` on the windowed transcript, so long scratchpads convert incrementally, not in one shot — called out in Task 4 Step 4 and gated on Phase 2b.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.
2. **Inline Execution** — execute here with checkpoints.

Which approach?
