# Scratchpad checklist: implementation plan

**Spec:** `docs/superpowers/specs/2026-10-11-scratchpad-checklist-design.md`
**Branch:** `feat/hybrid-stack` (inline execution, on top of PR #31)
**Ship:** update PR #31; independent review before merge; merge on Hassan's go-ahead.

Rules for every task:
- TDD: test first, see it fail, implement, see it pass.
- Match the surrounding code.
- Commit per task.
- Prompts case-agnostic.
- Fail open on every model call: nothing is assumed when a call fails.
- Stack sessions only: the non-stack path and today's analyser stay byte-identical.

## Backend (`backend/src/rapid_reports_ai/`)

### B1 Lab harness and fixtures into the repo
- `scripts/checklist_lab.py` and `tests/fixtures/hybrid_stack/checklist_cases.json` (already written in the lab).
- Keep arms D and S. Remove the D1, J3 and D2 arms. Spec §10 records them.
- No tests (script).

### B1b Jev wording lab: removed and multiple findings
- `tests/fixtures/hybrid_stack/jev_rows_fixture.json`: about 40 blind pairs per question (spec §10.2).
- `scripts/scratchpad_v2_labs.py` gains `rows`: two wordings per question, asked in one call with stated and
  contradicted. Print scores by gold class and the threshold table.
- Record the chosen wording and thresholds in spec §10.2 and as constants in `jev_stack.py`.

### B2 Items writer and chain: `hybrid_stack/items.py` (replaces `chips.py`)
- `WRITER_SYS`: the lab's arm D prompt (`_CORE + D_FIELDS + REFERRAL_LINE`). The user prompt adds
  "NOT ASSESSABLE ON THIS SCAN" when known and "REMOVED BY THE RADIOLOGIST" when any.
- Models:
  - `Item{id, kind: "finding"|"referral", region, question, why, sentences: list[str], answered: bool}`;
  - `ItemsResult{items, capped, cached, ms, error}`.
- `async update(scan_type, history, regions, dictation, not_assessable="", removed=()) -> ItemsResult`, the spec
  §4.2 chain:
  1. writer: Qwen (Cerebras, reasoning off, temperature 0, timeout 8 s); empty dictation still runs, which yields
     the referral item; `kind="referral"` when `source_text` is empty (first one only); ids are a hash of
     (kind, region, question);
  2. `report_reconcile._split_bundled` on the row sentences (it pre-selects candidates and guards with
     `_split_keeps_claims`, as in the brief); on failure keep the sentences;
  3. `jev_stack.ask_rows(dictation, sentences, removed)`: one call, three questions per sentence (stated,
     contradicted, removed ≥ 0.6); drop those sentences; mark a row with none left `answered`;
  4. limits: exact repeats; 2 sentences per row; 2 finding rows per region; 4 rows per case including the
     referral row; the rest into `capped`.
- Cache: the writer's raw items, LRU 256, keyed by (scan key, normalised history, abnormal sentences, regions,
  removed).
- Failure rules:
  - writer failure → no items plus error;
  - Jev failure → rows as written, removed filtered by exact match;
  - splitter failure → the sentence kept.
- Tests (`tests/test_hybrid_stack_items.py`, Qwen and Jev mocked):
  - referral detection, and only one;
  - stated, contradicted and removed drops; a row folding to answered;
  - split parts stay in their row;
  - limits order (caps applied after the checks), `capped`;
  - stable ids;
  - cache hit re-runs the checks on the new dictation;
  - each failure path.

### B3 Region normals check: `hybrid_stack/normals.py`
- `async assumed(dictation, region_normals: dict[str, list[str]], abnormal: list[str], dictated_normal: list[str]) -> dict[str, list[str]]`:
  - untouched regions: all sentences, unchecked;
  - dictated-normal regions: none (their words stand);
  - abnormal regions: `ask_rows`, keeping only sentences with stated < 0.3, contradicted < 0.3 and not removed
    (spec §5);
  - untouched regions: checked against removed only;
  - check failure → abnormal regions empty.
- Tests: the four cases plus failure.

### B4 Routes: `hybrid_stack/routes.py`
- `POST /api/canvas/stack/items`
  - request `{scan_type, clinical_history, regions, dictation, not_assessable, removed}`;
  - response `{items, capped, cached, ms, error}`;
  - `write` then `check`.
- `POST /api/canvas/stack/assumed`
  - request `{dictation, region_normals, abnormal, dictated_normal}`;
  - response `{assumed: {region: [..]}, ms, error}`.
- Remove `/chips`, `ChipsRequest`, `GroupRequest.chips` and `GroupResult.chips_stated`. Row re-checks happen
  through `/items`, whose cache makes repeats cheap.
- Tests: round trips, auth required, `_require()` flag gate.

### B5 Slim sheet: `hybrid_stack/slim_sheet.py`, table, migration
- Migration `20261012090000_stack_slim_sheets` (down_revision `20261011120000`).
  - Table `stack_slim_sheets`: id, scan_key, family, prompt_version, model, markdown, region_normals JSON,
    not_assessable text, created_at.
  - Unique (scan_key, family, prompt_version).
  - Model in `database/models.py`.
- `SLIM_SYS`: the sections of spec §8.1 in Markdown, case-agnostic. Region names are passed in. A "Region normals"
  section with one `- **{Region}:**` bullet per region and quoted sentences.
- `parse_slim(markdown) -> (region_normals, not_assessable)`. Regions not in the list are ignored. Sentences with a
  measurement are dropped (as the brief does today).
- `async get_or_make(db, scan_type, family, regions) -> SlimSheet | None`:
  - cache hit → row;
  - otherwise generate with `MODEL_CONFIG["STACK_SLIM_SHEET"]` (new key, default Qwen Cerebras at medium
    reasoning), parse, store;
  - one generation per key at a time (an in-process lock);
  - failure → None.
- Route `POST /api/canvas/stack/slim-sheet`
  - request `{scan_type, family, regions}`;
  - response `{id, region_normals, not_assessable, ready, error}`.
- Tests:
  - parse (normal; missing section; unknown region; measurement dropped);
  - cache hit makes no model call;
  - failure → None;
  - the migration's upgrade and downgrade on SQLite, or as the repo's migration tests do.

### B6 Template region normals
- `template_region_normals(template) -> dict[str, list[str]]` from the stored `SheetStructure`: paragraph → region;
  its `Normal` and unconditioned `Negative` statements.
- Find where the template pipeline stores the structure (`template_pipeline`), and reuse its loader.
- Served by `POST /api/canvas/stack/slim-sheet` when `template_id` is given. No model call.
- Tests on a fixture structure.

### B7 Generate (quick): stack brief on the slim sheet
- `quick_report_brief.compile_stack_brief(slim_markdown, conclusion, removed) -> Brief`:
  - renders the slim sections and the confirmed-conclusion bullet;
  - DO NOT ASSERT lines for `removed`;
  - no model call;
  - `decisions={"stack": True, "options": []}`.
- `quick_report_generator.generate_quick_report(..., stack_sheet_id=None)`: in stack mode with a slim sheet, use
  `compile_stack_brief`; otherwise today's `stack_fallback`.
- Remove the stack branches in `compile_brief` (`stack_offers`, finding-linked offering in stack mode, declined
  matching). `compile_brief(stack=…)` is no longer called. Delete the parameter and its tests.
- `quick_report_api.GenerateRequest.stack_sheet_id: str | None`, threaded through `_run_one_generator`.
- `stack_declined` is renamed `stack_removed` (same meaning).
- Tests:
  - stack brief contents;
  - generator chooses the stack brief, or falls back;
  - the non-stack brief is unchanged (existing tests pass untouched).

### B8 Voice: answer a row
- `jev_stack`: rename target_chip → target_item. The criteria are the visible rows' questions.
  `decide_command` returns `{"action": "answer", "item": id}`.
- `canvas_routes.BundleRequest.stack_chips` becomes `stack_items: list[{id, question}]`.
- Tests updated.

### B9 Gate log
- `LogRequest.gate` is JSON already; no schema change.
- Update the route test fixture to the new gate shape: `items`, `assumed`, `removed`, `capped`.

## Frontend (`frontend/src/lib/hybrid-stack/`)

### F1 Types and API
- `types.ts`:
  - `Item`, `ItemsResult`, `SlimSheet`;
  - `GateRecord` gains `items`, `assumed`, `removed`, `capped`;
  - remove `Chip`, `ChipState`, `ChipsResult`.
- `api.ts`: `postItems`, `postAssumed`, `postSlimSheet`; remove `postChips`; `postGroup` loses `chips`.
- `chips.ts` is removed; `items.ts` is new (pure):
  - `openRows(items, answered)`;
  - `rowsByRegion`;
  - `answerLabel(item)`: the single sentence, shortened to a button label, or "Both normal";
  - `rowSentences(item, removed)`: the sentences still listed;
  - `quietLine(sentences, max=3)`.
- Vitest.

### F2 Findings block
`regionState.buildFindingsBlock(units, groups, gate)` per spec §7:
- tapped rows: "Answered by the radiologist:";
- per region: "Assumed normal (confirmed by the radiologist):";
- tray regions' sentences;
- the referral answer;
- the conclusion;
- DO NOT ASSERT for removed.

Vitest, including a region with no slim sheet and a template region list.

### F3 The view: `HybridStackView.svelte`
Layout, wording and skin per spec §3:
- live strip;
- **referral row**;
- region cards: lines, **amber finding rows** (each sentence on its own line with ×, the button directly
  below), **quiet line** with ×, "+n more";
- type-a-finding;
- tray with keys and pill sentences;
- conclusion;
- **gate bar** with counts and Confirm (`btn-primary-subtle`).

Props: `items`, `assumed`, `removed`, `onAnswer(id)`, `onRemoveSentence(id, sentence)`, `onDictateInto(region)`, `onRemoveAssumed(region, sentence)`,
plus v2's existing props. Chip props removed.

Animations:
- rows: `fade`; an answered row shows green for 1.2 s, then folds;
- quiet line: no transition (the hidden-tab outro lesson);
- reduced motion → 0 ms.

Component tests (vitest-browser-svelte):
- referral row shows, and tapping calls `onAnswer`;
- an amber row's single-sentence label versus "Both normal" with both sentences listed;
- × on a row sentence calls `onRemoveSentence`, and the tap then adds only the remaining one;
- quiet line capped at 3 with "+2 more";
- × calls `onRemoveAssumed`;
- the gate bar counts, and Confirm disabled while a question is open;
- an answered row turns green, then leaves;
- tray pill shows its sentences.

### F4 Scratchpad wiring: `DictationScratchpad.svelte`
State:
- `items`, `answered` (ids tapped), `removed`, `slim` (region normals, not_assessable), `assumedByRegion`.

At setup:
- `postSlimSheet` (quick: scan type and family; template: template id);
- `postItems` with empty dictation, which gives the referral row.

On grouped units changing (debounced 500 ms):
- `postItems` with the dictation, region list, not_assessable and removed;
- `postAssumed` with the region normals and the abnormal and dictated-normal lists.

Then:
- an item returned `answered` and visible → mark it "answered in your dictation", fold after 1.2 s.
- Tap answer → add the id to `answered` (its listed sentences only); the gate re-arms.
- × on a row sentence → add it to `removed` (never stated; DO NOT ASSERT).
- Dictate → focus "Type a finding…" with that region as the placement hint (v2's `stackAppend` path).
- Remove assumed → add to `removed`, refresh the assumed list.
- Voice "answer" → `onAnswer(item)`.
- The gate key adds items, answered, removed and assumed.
- Confirm needs no open rows; it builds the GateRecord per spec §6.

Remove: `chipsByRegion`, `capturedChips`, `declinedChips`, `optedIn`, `refreshChips`, `acceptChip`, `removeChip`.

### F5 Parents
`IntelliDictateTab.svelte` and `TemplateForm.svelte`:
- send `stack_sheet_id` (quick) and `stack_removed` (both) instead of `stack_declined`;
- everything else unchanged (Generate gated on Confirm, findings block, `postReportId`).

### F6 Dev page
`src/routes/dev/hybrid-stack/+page.svelte`: new props and sample items, so the view can be checked without a
backend. The page is still gated by `requireDevRoute`.

## Verification

### V1 Automated
- Backend: full suite, expecting today's 3546 plus new tests to pass.
- Frontend: vitest, expecting 671/672 with the known `page.svelte.spec.js` failure.
- svelte-check at baseline (1198).

### V2 Lab re-run
`checklist_lab` arm D through the production `items.write` + `check` path on the 20 cases. Confirms:
- recall unchanged (surfaced ≈ 35/46);
- amber rows per case (median ≤ 2, max ≤ 4) from the real cap and Jev checks;
- row sentences graded "fine to ask" or "wrong to ask" (new rubric: wrong to ask means it contradicts the
  dictation, denies a typical sign of a dictated diagnosis, or can't be shown on this scan). Target: at most 1 row
  in 10 holds a wrong-to-ask sentence.

### V3 Hand reads (local, Chrome)
- **Quick:** the diverticulitis case, the "?appendicitis" + ovarian cyst case, and one staging case.
- **Template:** one case.
- Record for each: amber rows, taps, row sentences removed with × and why, the findings block, the generated
  report.
- **Gate:** no statement in the report that was not dictated, tapped or confirmed.

### V4 Independent review
Code-reviewer agent over the branch diff since PR #31's last commit. Fix the findings, then re-run V1.

### V5 PR #31
Update the description:
- the checklist design;
- the lab table;
- the slim sheet and its migration;
- the post-merge steps (Railway: `RR_STACK_REVIEWERS`, migrations `20261011120000` and `20261012090000`,
  Cerebras rate check, prod smoke, live testing).

Merge only on Hassan's go-ahead.

## Order
1. B1, B1b, B2–B4, then F1–F4 against the dev page. This gives a usable checklist without the slim sheet: rows only, no
   quiet lines.
2. B5–B7 and F5: the slim sheet and Generate.
3. B8 and B9.
4. V1–V5.
