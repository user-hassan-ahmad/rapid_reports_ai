# Template mirror — production wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the lab-proven template flow run for real users: "Set up workspace" starts Phase 1, Generate waits for it, and the generate endpoint runs master sheet → brief → generator → history → options → check → uniqueness gate → GenerationArtifacts. All of it sits behind `RR_TEMPLATE_MIRROR` (kill switch, default off) and the `RR_PIPELINE_OVERRIDE_USERS` allowlist.

**Architecture:**
- **One orchestration module, `template_pipeline.py`,** extracted from the lab's `run_new` (scripts/template_e2e_lab.py:445). Production and the lab call the same code, so the lab keeps measuring what ships.
- **Phase 1 runs in a new endpoint, `POST /api/templates/{id}/prepare`.** It returns at once and runs Phase 1 as an in-process task. Each result is persisted in a new table `template_case_sheets`, keyed by (user, template, sheet hash, history hash).
- **Generate resolves that key.** It uses a ready row, awaits an in-flight task, or runs Phase 1 inline (the same pattern as quick's `/analyse` then `/generate` with its inline fallback).
- **The mirror is used only when the template's stored structure is grammar-parsed** (`tss.fresh`: source "grammar", mode "template"). Every other template keeps today's path untouched.

**Tech Stack:** FastAPI, SQLAlchemy + Alembic (`backend/migrations/versions`), pytest with the conftest fixtures `db_session`, `test_user`, `auth_headers`, `guided_template` and `legacy_template`; Svelte (one call in `TemplateForm.svelte`).

**Deployment assumption:** one uvicorn process (Procfile `uvicorn rapid_reports_ai.main:app`, no `--workers`). In-flight Phase 1 tasks therefore live in a module dict. If replicas or workers are ever added, a cross-process cache miss costs one inline Phase 1 run (about 15 s) and nothing else. That is tested (W3).

**Out of scope here:**
- Prompt sign-off.
- Lean analyser in the creator path, lint-on-save, the Refine prompt and converting the 26 stored sheets (the G4–G6 plan). Until these land, only templates holding a grammar sheet take the mirror.
- The Review rail UI.
- Post-generation inserter changes (decided separately).

---

### Task W1: `template_case_sheets` table + crud

**Files:**
- Create the migration `backend/migrations/versions/<rev>_add_template_case_sheets.py`. Copy the head revision from `alembic heads`.
- Modify `src/rapid_reports_ai/database/models.py` (after `EphemeralSkillSheet`) and `database/crud.py`.
- Test `tests/test_template_case_sheets.py`.

- [ ] **Step 1: Failing tests**
```python
from rapid_reports_ai.database import crud

def test_case_sheet_roundtrip(db_session, test_user, guided_template):
    row = crud.create_case_sheet(db_session, user_id=str(test_user.id), template_id=str(guided_template.id),
                                 sheet_hash="s1", history_hash="h1", clinical_history="?perforation")
    assert row.status == "running"
    crud.finish_case_sheet(db_session, row.id, master_sheet="## Case Deliberation\n…", case_result={"units": []},
                           model="q", latency_ms=12000, prompt_version="p1")
    got = crud.get_case_sheet(db_session, str(test_user.id), str(guided_template.id), "s1", "h1")
    assert got.status == "ready" and got.master_sheet.startswith("## Case Deliberation")

def test_failed_case_sheet_is_not_returned_as_ready(db_session, test_user, guided_template):
    row = crud.create_case_sheet(db_session, user_id=str(test_user.id), template_id=str(guided_template.id),
                                 sheet_hash="s1", history_hash="h2", clinical_history="x")
    crud.fail_case_sheet(db_session, row.id, error="boom")
    assert crud.get_case_sheet(db_session, str(test_user.id), str(guided_template.id), "s1", "h2").status == "failed"
```
- [ ] **Step 2:** `poetry run pytest -q tests/test_template_case_sheets.py`; expect FAIL (no attribute `create_case_sheet`).
- [ ] **Step 3: Implement**

Model `TemplateCaseSheet`, `__tablename__ = "template_case_sheets"`. Columns:
- `id` (UUID pk);
- `user_id` (FK users, cascade, indexed) and `template_id` (FK templates, cascade, indexed);
- `sheet_hash` and `history_hash` (String(64));
- `clinical_history` (Text);
- `status` (String(16): running / ready / failed);
- `master_sheet` (Text, nullable) and `case_result` (JSON, nullable);
- `model` (String(100)), `latency_ms` (Integer) and `prompt_version` (String(64));
- `error` (Text);
- `created_at` and `updated_at`.

Add a unique index on (user_id, template_id, sheet_hash, history_hash).

Crud functions:
- `create_case_sheet`, which upserts: an existing failed row is reset to running;
- `finish_case_sheet`, `fail_case_sheet`, `get_case_sheet`.

The migration creates the table and index; downgrade drops them.
- [ ] **Step 4:** Run the tests; expect PASS. Run `alembic upgrade head` on the local sqlite DB and check it applies.
- [ ] **Step 5:** Commit `feat(db): template_case_sheets for Phase 1 output`.

### Task W2: `template_pipeline.py` — extract the orchestration from the lab

**Files:**
- Create `src/rapid_reports_ai/template_pipeline.py`.
- Modify `scripts/template_e2e_lab.py` so `run_new` calls it.
- Test `tests/test_template_pipeline.py`, extending the existing file.

API:
```python
def enabled() -> bool                                   # RR_TEMPLATE_MIRROR in ("1","true","on")
def choose_mirror(requested: str | None, email: str | None) -> bool   # allowlist honours "mirror"/"current"
def keys(sheet: str, history: str) -> tuple[str, str]   # sha256[:16] of sheet, of history.strip()
async def run_phase1(sheet: str, scan_type: str, history: str) -> dict
    # {"master_sheet", "case_result" (dict), "model", "latency_ms", "prompt_version"}; raises on model failure
async def generate_template_report(*, sheet: str, scan_type: str, findings: str, history: str,
                                   master_sheet: str | None, signature: str | None) -> dict
    # the lab's run_new body from "Phase 2 brief" on: master parsed (mode="master"), falls back to the lean
    # sheet when the master is missing/unusable; brief fail-soft; generator + write_options in parallel;
    # history inserted; run_quality_check(sections, protected, suppressed, extra_report_qs, history) beside the
    # impression gate; gate_apply; signature appended last.
    # returns {"report_content", "model_used", "description", "brief_used", "brief_text", "brief_decisions",
    #          "options", "gate_dropped", "quality_check", "sections", "history_inserted", "phase1_used",
    #          "lat": {...}, "jev_calls": {...}}
def candidate_record(result: dict, latency_ms: int) -> dict   # quick's candidate fields + sections + lat
```

- [ ] **Step 1: Failing tests.** Stub `compile_template_brief`, the generator, `write_options`, `write_history`, `run_quality_check` and `rc.gate_scores` the way Task 15 of the 2026-09-30 plan does, using the real lean sheet fixture. Assert:
  1. The master sheet is used when usable. An unusable master falls back to the lean sheet with `phase1_used=False`.
  2. A brief failure gives the raw path (brief_text None) and the report is still produced.
  3. History is inserted only when the sheet defines a history section, and it is passed to the check as `history=`.
  4. Gate drops are applied, so a dropped option id is absent from `options`.
  5. The signature comes last, after the check.
  6. `choose_mirror`: flag off → False; allowlisted "mirror" → True; not allowlisted → flag value; flag on with allowlisted "current" → False.
  7. `candidate_record` has `model, content, latency_ms, generated_at, error, description, options, options_applied, quality_check, brief, sections`.
- [ ] **Step 2:** Run; expect FAIL (module missing).
- [ ] **Step 3: Implement.**
  - Move the code; don't rewrite it.
  - `run_new` in the lab becomes: Phase 1 (saved or run), then `generate_template_report(...)`, then its own lab-only scoring and Jev counting.
  - Keep the lab's `--reuse-phase1` / `--phase1-repeat` behaviour.
  - Add `template_pipeline.py` to the import-boundary test in `tests/test_report_path_split.py`: no `quick_report*` imports.
- [ ] **Step 4:** Run `poetry run pytest -q tests/test_template_pipeline.py tests/test_template_e2e_lab.py tests/test_report_path_split.py`, then the full suite. Then run the lab on cmr_cardiomyopathy-d2 with `--reuse-phase1 scratchpad/e2e_small_w_65773`. The report must be byte-identical to that run's apart from the generator's own variance: the brief text and decisions must be identical.
- [ ] **Step 5:** Commit `refactor(template): one orchestration module shared by production and the lab`.

### Task W3: `POST /api/templates/{id}/prepare` and Phase 1 resolution

**Files:**
- Modify `src/rapid_reports_ai/main.py` (next to `generate_report_from_template`, line 1750).
- Modify `template_pipeline.py` to add `resolve_master`.
- Test `tests/test_template_generate_endpoint.py`.

Behaviour:
- **prepare(template_id, {clinical_history, scan_type?}):**
  - Returns `{"success": True, "status": "skipped"}` unless `choose_mirror(None, email)` holds, the template is skill_sheet_guided and `tss.fresh(cfg)` is truthy.
  - Otherwise it computes the keys:
    - a ready row returns `{"status": "ready"}`;
    - a running in-process task returns `{"status": "running"}`;
    - otherwise it creates the row (running), starts `asyncio.create_task(_phase1_job(...))`, records it in `_PHASE1_TASKS[key]` and returns `{"status": "running"}`.
  - The job runs `tp.run_phase1`, then `finish_case_sheet`, or `fail_case_sheet` on any exception. It uses its own DB session and always removes its `_PHASE1_TASKS` entry when done.
- **resolve_master(db, user, template, sheet, scan, history) → (master_sheet | None, source):**
  - a ready row → (master, "cached");
  - an in-flight task → await it with a 60 s timeout, then re-read the row → (master, "awaited");
  - no row or task → run Phase 1 inline, persist it → (master, "inline");
  - a failed row, timeout or exception → (None, "failed"); the pipeline then runs on the lean sheet.

- [ ] **Step 1: Failing tests** (TestClient; stub `tp.run_phase1` with a counter and an `asyncio.Event` to hold it running):
  1. prepare with the flag off returns "skipped" and makes no Phase 1 call.
  2. prepare with the flag on runs Phase 1 once. A second prepare with the same history returns "running" or "ready" without a second call.
  3. A different history starts a new Phase 1.
  4. `resolve_master` while the task is held: it awaits, and returns "awaited" once released.
  5. No prepare at all → "inline", one call.
  6. Phase 1 raises → a failed row, and `resolve_master` returns (None, "failed").
  7. A legacy template → prepare returns `{"success": False, "error": LEGACY_RETIRED}`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** PASS, plus the full suite.
- [ ] **Step 5:** Commit `feat(template): prepare endpoint runs Phase 1 at workspace setup; generate resolves or waits`.

### Task W4: Generate endpoint runs the mirror

**Files:**
- Modify `main.py` (`TemplateGenerateRequest` gains `pipeline: Optional[str] = None`; `generate_report_from_template`).
- Modify `database/crud.py` (`create_report` gains `candidate_reports`), if it isn't already there; check `crud.py:1361` for the quick helper and reuse its shape.
- Test `tests/test_template_generate_endpoint.py`.

- [ ] **Step 1: Failing tests:**
  1. With the flag on, a fresh grammar structure and a stubbed `tp.generate_template_report`, the response has `pipeline == "mirror"`, `artifacts.sections`, and the saved report's `candidate_reports[0].options`.
  2. With the flag off, the response has `pipeline == "current"`, today's path runs (assert the stubbed `TemplateManager.generate_report_from_config` is called), and `artifacts` is None.
  3. With the flag on but `tss.fresh` returning None (an old-format sheet), the result is "current".
  4. An allowlisted user with `pipeline: "current"` and the flag on gets "current".
  5. The mirror's response `response` and `model` keys hold the same shape the frontend reads today (`data.response`, `data.model`, `data.report_id`).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: Implement.**
  - Before generation, for the mirror: `master, p1_source = await tp.resolve_master(...)`, then `tp.generate_template_report(...)`.
  - Skip `ENABLE_TEMPLATE_STRUCTURE_VALIDATION` for the mirror.
  - Persist `candidate_reports=[tp.candidate_record(...)]` with `phase1_source` inside it.
  - Add `"pipeline"` and `"artifacts": GenerationArtifacts.from_candidate(...).model_dump()` to the response.
  - Leave the guideline prefetch scheduling untouched.
- [ ] **Step 4:** PASS, plus the full suite (the quick golden tests unchanged).
- [ ] **Step 5:** Commit `feat(template): generate endpoint runs the mirror behind RR_TEMPLATE_MIRROR and persists artifacts`.

### Task W5: Frontend — call prepare at "Set up workspace"

**Files:** Modify `frontend/src/routes/components/TemplateForm.svelte`, in the `isSkillSheetGuided` branch of `handleSetUpWorkspace` (about line 220).

- [ ] **Step 1:**
  - After the existing workspace setup succeeds, fire-and-forget: `fetch(`${API_URL}/api/templates/${templateId}/prepare`, {method: 'POST', headers, body: JSON.stringify({clinical_history: variableValues['CLINICAL_HISTORY'] || '', scan_type: scanType})}).catch(() => {})`.
  - Don't await it in the UI path. Show no new UI.
  - "Regenerate workspace" (sectionsDirty) calls it again, so a changed history gets its own Phase 1.
- [ ] **Step 2:**
  - `npm run check` and the existing frontend tests pass.
  - Add a unit test if TemplateForm has a test harness; otherwise none, since the behaviour is covered by backend tests and W6.
- [ ] **Step 3:** Commit `feat(template-ui): set up workspace starts Phase 1 (fire and forget)`.

### Task W6: Local production-workflow run (no prod writes)

**Files:** Create `src/rapid_reports_ai/scripts/template_workflow_check.py` (lab).

It starts the app in-process (httpx `ASGITransport`) on a scratch sqlite DB with real models, creates a user and a skill_sheet_guided template carrying a lean grammar sheet from `scratchpad/e2e_small_s_64800`, and sets `RR_TEMPLATE_MIRROR=1`. Then, for ct_ap_acute-d1, d3 and cmr_cardiomyopathy-d2, it:
1. calls prepare;
2. sleeps for a realistic dictation time (20 s);
3. calls generate with the dictation;
4. records `phase1_source` (expect "cached"), every latency, the report, the options and the artifacts.

It also runs one case with generate fired immediately (expect "awaited"), and one with no prepare (expect "inline").

- [ ] Run it. Hand-read the 3 reports against the lab's latest (`e2e_small_v_47875` / `w_65773`); they should match in substance.
- [ ] Write `scratchpad/workflow_check_<pid>/summary.md`.
- [ ] Commit the script only: `test(template): local production-workflow check script`.

---

## After this plan (not tasks here)

- **Prompt sign-off package.**
- **G4–G6:** lean analyser in the creator path, lint-on-save repair, Refine prompt, converting the 26 stored sheets. Until these land, real users' templates stay on the current path even with the flag on.
- **Deploy with the flag off.** Then enable for allowlisted users, run E2 on real templated dictations (old vs new), and do the live Chrome check on a skill_sheet_guided template.
