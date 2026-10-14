# Trust fixes before the prototype ships — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the guideline cards trustworthy on growth cases and make Confirm respect unresolved guideline cards (spec §7.12).

**Architecture:** Backend changes live in the library engine/settler (`hybrid_stack/copilot/library/`) and one new
route; pack data changes are in `guidelines/`. Frontend changes live in `lib/copilot/` plus one optional prop on
`HybridStackView.svelte` wired from `DictationScratchpad.svelte`. Backend tasks run on `feat/scratchpad-copilot`;
frontend tasks on `feat/copilot-ui` after merging the backend branch in.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pytest; Svelte 5, TypeScript, vitest (browser mode).

**Spec:** `docs/superpowers/specs/2026-10-12-guideline-library-design.md` §7.12 (commits ff5e4a75, 1c3fa014, 191a7ec8),
read with §3.6 (eligibility, assumed in scope, scope doubt) and §7.4–7.7 (draft card).

## Global Constraints

- Worktrees: backend `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot` (branch
  `feat/scratchpad-copilot`); frontend `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/copilot-ui` (branch
  `feat/copilot-ui`).
- Never push, never amend, never merge to main. Never commit `backend/uv.lock` or `frontend/vite.local.config.js`.
  Stage only files you changed.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01FMmCUNDQq6iPV6tn4pSRPH`
- No live model or Jev calls in tests (mock `jev_post` / `_call`). No subagents.
- British English in all user-facing text. Prompts/Jev questions are case-agnostic (no single-domain clinical examples).
- Never generate guidance a source does not contain (spec §7.12 principle).
- A guessed (pre-filled or approximate) value never excludes and never decides alone (spec §3.6).
- Copilot failures never block Confirm (integration D24): a failed/timed-out/loading card has no verdict and never
  blocks; only a significant verdict whose conclusion check fails stays blocking, and "Seen, leave as is" always clears.
- Backend tests: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/ -q -k "library or copilot or real_lab" 2>&1 | tail -3`
  plus `PYTHONPATH=src .venv/bin/python scripts/guidelines/check_pack.py` and
  `PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py` (bundle must be rebuilt and committed when
  `guidelines/` changes; follow how earlier pack commits did it).
- Frontend tests: `cd frontend && npx vitest run src/lib/copilot src/lib/hybrid-stack src/lib/components 2>&1 | tail -5`
  and `npx svelte-check --threshold error 2>&1 | tail -3`.

## Review Focus

1. A dictation with two dated comparisons ("CT 12 March 2025 and CT 1 June 2024") — interval is asked, never guessed
   from either (Task 3 test `test_two_dates_asks`).
2. A slash date ("03/12/2025") — read as UK day-month (3 December 2025), and a date in the future is dropped (Task 3 tests `test_uk_day_first`, `test_future_date_dropped`).
3. Fleischner on a nodule stated "stable" or "new" — `prior_growth` is No, the table answers as before (Task 1 test
   `test_stable_nodule_unchanged`).
4. The conclusion check endpoint failing or timing out — cards with significant verdicts stay unresolved but "Seen"
   clears them; Confirm is never disabled by a card with no verdict (Task 7 tests `gate: failed card never blocks`,
   `gate: seen clears`).
5. A long verdict or name in a 280 px rail — no pill crosses the card's right edge (Task 6 test
   `pills stay inside the card at 280px`).

---

### Task 1: Fleischner scope — interval growth

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py` (InputDef: new optional field)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py` (gate for the new field)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (`_outcome_text`, `_build`,
  `calculate`, `_exclusion_reason`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`ExclusionReason.outcome`)
- Modify: `guidelines/fleischner-pulmonary-nodule/entry.json`, `cases.json` (and manifest if locators need it)
- Rebuild: the compiled bundle (as earlier pack commits)
- Test: `backend/tests/test_library_*.py` — add `test_library_fleischner_growth.py`

**Interfaces:**
- Produces: `InputDef.exclusion_outcome: str | None = None` — an outcome id whose wording replaces `does_not_apply`'s
  when this input is the single exclusion reason. `ExclusionReason.outcome: str | None = None` — set to that id.
  `_outcome_text(e, t, sources, outcome_id: str | None = None)`.

Mechanism ruling (spec §7.12 item 1 says "a new outcome `outside_table_growth`"): the engine and ~20 call sites treat
`does_not_apply` as THE excluding outcome. Do not add a second excluding outcome to the engine. Instead the rules still
reach `does_not_apply`; the new outcome exists in `outcomes` for its wording/locators only, and the input points at
it with `exclusion_outcome`. The user sees exactly the spec's wording.

- [ ] **Step 1: Pack data.** In `entry.json` add input (after `exclusion`):
```json
{"id": "prior_growth", "label": "Earlier imaging shows this nodule has grown", "type": "boolean",
 "role": "eligibility", "scope": "lesion", "exclusion_outcome": "outside_table_growth",
 "how_stated": "true when the dictation says this nodule is larger than on an earlier study, e.g. 'now 9 mm, previously 6 mm', 'interval growth', 'enlarging'; false when it is new, stable or smaller, or there is no earlier imaging",
 "locator": {"source": "S1", "page": 5, "section": "Prior imaging studies should always be reviewed whenever they are available to determine possible growth or stability (grade 1A)"}}
```
Add `{"ref": "prior_growth", "eq": true}` to the `any` of the rules case(s) whose result is `does_not_apply` (match the
existing shape exactly; if the pathway's later cases require eligibility values `eq false`, add
`{"ref": "prior_growth", "eq": false}` wherever `exclusion` is required false — read the logic first).
Add outcome:
```json
{"id": "outside_table_growth", "headline": "Outside the Fleischner table: interval growth",
 "action": "See the BTS card", "category": "not_applicable",
 "classification": "Fleischner 2017 does not apply: the table covers newly detected incidental nodules, and this nodule has grown on prior imaging.",
 "recommendation": "The Fleischner table covers newly detected nodules. Prior imaging shows growth: see the BTS card.",
 "caveats": [],
 "locator": {"source": "S1", "page": 3, "table": "Fleischner Society 2017 Guidelines for Management of Incidentally Detected Pulmonary Nodules in Adults"}}
```
(If the schema caps `action` at 6 words, "See the BTS card" fits.) Add golden cases: growth Yes → `does_not_apply`;
growth No + solid single 9 mm → `solid_single_gt8`.

- [ ] **Step 2: Schema + verify.** `InputDef.exclusion_outcome: str | None = None`. verify: when set, the input's role
is `eligibility`, the outcome exists, its category is `not_applicable`, and the outcome is exempt from any
"every outcome is reachable by rules" check (find that check; exempt outcomes named by an `exclusion_outcome`).

- [ ] **Step 3: Failing tests** (`test_library_fleischner_growth.py`), using the bundle's Fleischner entry and
`finish(e, Settlement-with-values, {}, {}, sources)` or `engine.evaluate` as neighbouring tests do:
  - `test_growth_read_excludes_with_growth_wording`: read values nodule_type solid, count single, diameter 9, prior_growth
    True → `state == "does_not_apply"`, `exclusion.headline == "Outside the Fleischner table: interval growth"`,
    `exclusion.recommendation` contains "see the BTS card", `exclusion_reason.input == "prior_growth"`,
    `exclusion_reason.outcome == "outside_table_growth"`, citations include page 3 and page 5 locators.
  - `test_stable_nodule_unchanged`: prior_growth False → outcome `solid_single_gt8` as before.
  - `test_growth_unstated_assumed_in_scope`: prior_growth absent → assumed No (in `assumptions`), outcome drafted.
  - `test_growth_prefilled_is_scope_doubt`: prior_growth True pre-filled (not read) → `prior_growth in scope_doubt`,
    not excluded.
  - `test_generic_exclusion_keeps_generic_wording`: exclusion True (screening) read → generic `does_not_apply` text,
    `exclusion_reason.outcome is None`.
  - verify test: an `exclusion_outcome` naming a missing outcome, or one with category `workup`, is rejected.
- [ ] **Step 4: Run, see them fail.**
- [ ] **Step 5: Implement.** `_outcome_text(..., outcome_id=None)` uses `e.outcome(outcome_id or t.outcome)`. In
`_build` and `calculate`: when the outcome is `does_not_apply` and the exclusion reason's input has
`exclusion_outcome`, the exclusion text is `_outcome_text(e, t, sources, that_id)` (fall back to the generic text if
it returns None). `_exclusion_reason` sets `outcome=i.exclusion_outcome`. Rebuild the bundle.
- [ ] **Step 6: Run all backend tests + check_pack + preview_lab `--check` (`PYTHONPATH=src .venv/bin/python
scripts/guidelines/preview_lab.py --check`); all green.**
- [ ] **Step 7: Commit** `feat(library): Fleischner scope — interval growth points to BTS`.

### Task 2: Number eligibility thresholds can be assumed

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py` (`_assume`, docstring)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (display of an assumed band)
- Test: add to `backend/tests/test_library_engine*.py` (or a new `test_library_assume_band.py`)

**Interfaces:**
- Consumes: `engine._assume(entry, given)` → `(fill, over, assumed)`; `assumed[ref] = InputValue(band=...)`.
- Produces: assumed number eligibility inputs that also feed a formula now appear in `Trace.assumed` as a band value.

Spec §7.12 item 2 amends §3.6: an eligibility number is assumed at its in-scope band as a range value even when the
number feeds a formula (BTS age → Brock). The formula still needs the exact number, so the number stays asked only
when that formula can still change the outcome.

- [ ] **Step 1: Failing tests:**
  - `test_bts_growth_case_reaches_growth_workup_2d`: BTS entry, given (as read) nodule_type solid, diameter_mm 9,
    benign_features False, prior_study True, resolved False, growth "diameter_clear_growth", spiculation False,
    upper_lobe False; `evaluate(e, given, assume_eligible=True)` → `outcome == "growth_workup_2d"`, `assumed` has
    `age` with band `ge18` (use the real band id from the entry) and `proven_malignant` False.
  - `test_bts_no_prior_still_asks_age_for_brock`: same but prior_study False, growth absent → no outcome, `"age" in
    needed` (Brock needs the exact age), and `assumed["age"]` band ge18 present.
  - `test_fleischner_age_unchanged`: Fleischner age assumption behaves exactly as before.
  - Preview: through `finish`, the BTS draft shows age as `assumed` with display value "18 or over" (use the band's
    label from the entry), and `most_likely`/draft outcome is the clear-growth outcome; `decisive` is True for age.
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement.** In `_assume`, `answerable` returns True for an eligibility input's band step even when the
input also feeds a non-band step; keep the band override (`over`) and `assumed[ref] = InputValue(band=...)`, and do
NOT put the number into `fill`. Check `_partial` still lists the number in `needed` when a formula branch is open
(test 2). Update the `_assume` docstring and §3.6 comment lines that say "never assumed". Make the draft row show the
band label for an assumed band value (find how an answered band is displayed and reuse it).
- [ ] **Step 4: Run all backend tests; preview_lab --check.**
- [ ] **Step 5: Commit** `feat(library): assume a number eligibility threshold at its in-scope band`.

### Task 3: Interval from a dated comparison

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/dates.py`
- Modify: `schema.py` (InputDef `since_study: bool = False`; verify: only on a number input with unit `days`)
- Modify: `pack_preview.py` (`_inputs_text`, `_prompt`, `_in_scope`, `_texts`, `_value`, `_read_reasons`, draft basis)
- Modify: `types.py` (`DraftValue.basis: str = ""`)
- Modify: `guidelines/bts-pulmonary-nodule/entry.json` (`interval_days`: `"since_study": true`, how_stated adds
  "or the date of the earlier study as dictated, e.g. 'CT of 12 March 2025'"); rebuild bundle
- Test: `backend/tests/test_library_dates.py`, and settle tests alongside existing pack_preview settle tests

**Interfaces:**
- Produces: `dates.parse(quote: str) -> ParsedDate | None` with `ParsedDate(day: date, exact: bool, text: str)`;
  `dates.days_since(d: date, today: date | None = None) -> int` (today defaults to `datetime.now(ZoneInfo("Europe/London")).date()`);
  `dates.distinct_dates(text: str) -> list[date]`; `DraftValue.basis` e.g. "from the CT of 12 Mar 2025".

Rules (spec §7.12 item 4):
- Formats: "12 March 2025", "12th March 2025", "12 Mar 2025", "12/03/2025", "12.03.2025", "12-03-2025" (UK
  day-month), "2025-03-12" (ISO) → exact. "March 2025" → approximate (15th). A bare 4-digit year 1990–today's year
  inside the quote ("CT 2023") → approximate (1 July). Anything else → None.
- The model may answer a `since_study` input with the date quote; code converts. A quote that is a plain duration
  ("3 months") keeps today's quantity path.
- A `since_study` input's quote may come from the whole dictation or history (not only the finding), so the prompt
  includes DICTATION when one is open and `_in_scope` / `_texts` treat it like a patient input for quote checks.
- Exact → value read; approximate → value pre-filled with why `"approximate date"`; more than one distinct date in the
  dictation+history → dropped (asked); future date or days ≤ 0 → dropped.
- `basis`: "from the {MOD} of {d %-d %b %Y}" where MOD is the first of CT|MRI|MR|PET-CT|PET|ultrasound|radiograph|
  X-ray found in the quote's sentence before the date, else "study"; approximate adds " (approximate)".

- [ ] **Step 1: Failing tests** `test_library_dates.py`: `test_parse_formats` (each format above),
  `test_uk_day_first` ("03/12/2025" → 3 Dec 2025), `test_month_year_approx`, `test_bare_year_approx`,
  `test_garbage_none`, `test_days_since` (12 Mar 2025 → 14 Oct 2026 = 581 with an injected today),
  `test_future_date_dropped` (settle path).
- Settle tests (mock `_call` returning RawSettle items as other settle tests do), BTS entry, dictation
  "Compared with the CT thorax of 12 March 2025.\nThe solid nodule in the right lower lobe now measures 9 mm,
  previously 6 mm.", finding = the nodule sentence, injected today 2026-10-14:
  - `test_interval_from_comparison_date`: model returns interval_days quote "12 March 2025" → value 581, state read,
    basis "from the CT of 12 Mar 2025".
  - `test_two_dates_asks`: dictation also contains "CT 1 June 2024" → interval_days not settled (asked).
  - `test_approx_date_prefilled`: "Compared with CT from March 2025" → pre-filled, why contains "approximate date",
    basis ends "(approximate)".
  - `test_duration_quote_unchanged`: quote "18 months" still read as today (≈ 548 days per existing conversion).
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement** (`today` injectable via a module-level function patched in tests).
- [ ] **Step 4: Run all backend tests; check_pack; preview_lab --check.**
- [ ] **Step 5: Commit** `feat(library): interval from a dated comparison, computed in code`.

### Task 4: Suspected cancer raises a scope doubt

**Files:**
- Modify: `pack_preview.py` (`_settle` around the `_hedged_cancer` drop; `_read_reasons` or the read/pre-filled split)
- Test: extend the existing hedged-cancer tests (grep `_hedged_cancer` in `backend/tests/`)

Spec §7.12 item 6: a hedged "known primary cancer: yes" is no longer dropped (then silently assumed No). It is kept
as a **pre-filled** Yes with why `"suspected, not established"`. The existing scope-doubt machinery then shows
"this pre-filled value would make the guideline not apply: confirm it", keeps the card `check_first`, never excludes.

- [ ] **Step 1: Failing tests:** Fleischner, history "?primary lung carcinoma" (or dictation "likely primary lung
  carcinoma"), mock model returns exclusion True with that quote → `exclusion` draft state `prefilled`, why contains
  "suspected, not established", `"exclusion" in scope_doubt`, card not `does_not_apply`. Unhedged "known breast
  cancer" → read, excludes (unchanged). "Breast ca ?liver mets" quoted "Breast ca" → read (unchanged).
- [ ] **Step 2: Run, fail. Step 3: Implement. Step 4: all backend tests green.**
- [ ] **Step 5: Commit** `feat(library): a suspected cancer is a scope doubt, never assumed away`.

### Task 5: Conclusion check route

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` (new route + models)
- Possibly create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/conclusion_check.py` (logic, cache)
- Test: `backend/tests/test_copilot_conclusion_check.py`; update `backend/tests/test_copilot_ui_contract.py` /
  `frontend/src/lib/copilot/contract.json` only if the contract test requires every route listed (check it)

**Interfaces:**
- Produces: `POST /api/hybrid-stack/copilot/conclusion_check` (same prefix/auth/`_require` as `/match`) with body
  `{"conclusion": str ≤ 4000, "cards": [{"key": str ≤ 120, "finding": str ≤ 6000}] (≤ 10)}` → `{"results":
  {key: "none" | "surveillance" | "workup" | "refer" | null}}` — the type of recommendation the conclusion gives for
  that card's finding (category match, Hassan 2026-10-14). null = not checked (empty conclusion, Jev failure or
  timeout, or confidence below the floor).

- [ ] **Step 1: Failing tests** (mock `jev_post`): per card one Jev `choice` question "What does the CONCLUSION
  recommend for the FINDING?" with neutral ids and these options (case-agnostic, verbatim): c0 "No follow-up or
  management is recommended for the FINDING." → none; c1 "Follow-up imaging of the FINDING." → surveillance; c2
  "Further tests or investigation of the FINDING, such as another imaging test or tissue sampling." → workup; c3
  "Referral to a specialist team or multidisciplinary meeting for the FINDING." → refer. State text per card is
  `CONCLUSION:\n{conclusion}\n\nFINDING:\n{finding}` (one call per card concurrently, bounded by
  `asyncio.Semaphore(4)`, unless the Jev API takes several states per call); confidence ≥ 0.6 (CHOICE floor) → the
  mapped category, else null; Jev error/timeout → null for that card;
  empty conclusion → all null, no call; results cached by (norm conclusion, key, norm finding) for successes only;
  >10 cards → 422; auth required.
- [ ] **Step 2: Run, fail. Step 3: Implement using `jev_client.jev_post`, `JEV_MODEL`, `jev.scores` exactly as
  `library_match.py` does. Step 4: all backend tests green.**
- [ ] **Step 5: Commit** `feat(copilot): conclusion check route for the confirm gate`.

### Task 6: Card and rail layout (frontend; independent of Tasks 1–5)

**Files:**
- Modify: `frontend/src/lib/copilot/cards/PackCard.svelte`, `VerdictPill.svelte`, `AssumedChip.svelte`,
  `ValueRow.svelte`, `CopilotRail.svelte`, `Reference.svelte`, `PackBody.svelte`, `cards.css`
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte` only for the rail's container height if needed
- Test: `frontend/src/lib/copilot/cards/*.svelte.test.ts` (vitest browser mode measures real layout)

Spec §7.12 item 7. Screens of the defects: card head pills overlap the name and run past the card edge in a narrow
rail; the expanded card's name wraps under a pill; value-row tags spill right; the rail grows without bound.

- [ ] **Step 1: Failing tests** (render with fixtures at a 280 px wide container; read `getBoundingClientRect()`):
  - `pills stay inside the card at 280px`: every pill's right ≤ the card's right; no two pills' rects intersect; the
    name's rect intersects no pill.
  - `a shortened verdict keeps its full text`: the pill element has `title` = full action text.
  - `value tags wrap under the value`: in a 280 px row, each tag's right ≤ the row's right.
  - `rail scrolls inside`: CopilotRail root has a bounded height (`max-height` resolves to the container/viewport
    height) and `overflow-y: auto`; with 8 cards its scrollHeight > clientHeight and the page body does not grow.
  - `long reference block scrolls`: an open card's reference/notes region has a max-height and `overflow-y: auto`.
- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Implement:** head as CSS grid (`grid-template-columns: minmax(0,1fr) auto` for name + chevron;
  pills on their own row with `display:flex; flex-wrap:wrap; gap`), pills `max-width:100%; min-width:0;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap` with `title`; no absolute positioning; value row
  `flex-wrap: wrap` with tags on a new line under the value; rail `max-height: calc(100vh - <offset>)` (or
  `height:100%` of a bounded parent) + `overflow-y:auto` + `overscroll-behavior: contain`; reference/notes/citations
  `max-height: 16rem; overflow-y: auto`. Keep existing tokens and colours.
- [ ] **Step 4: All frontend tests + svelte-check green.**
- [ ] **Step 5: Commit** `fix(copilot-ui): cards wrap within the rail; the rail and long blocks scroll`.

### Task 7: Truthful count, not-needed line, growth exclusion, interval basis, Confirm gate (frontend)

Precondition: merge `feat/scratchpad-copilot` (with Tasks 1–5) into `feat/copilot-ui` first
(`git merge --no-edit feat/scratchpad-copilot` in the copilot-ui worktree; resolve only if trivial, else stop).

**Files:**
- Modify: `frontend/src/lib/copilot/types.ts` (`ExclusionReason.outcome?: string | null`, `DraftValue.basis?: string`)
- Modify: `frontend/src/lib/copilot/cards/format.ts` (`openQuestions`, new `notNeeded`, `verdictOf` exclusion branch)
- Modify: `frontend/src/lib/copilot/cards/PackBody.svelte`, `ValueRow.svelte` (not-needed line; basis under value)
- Create: `frontend/src/lib/copilot/gate.ts` (+ `gate.test.ts`)
- Modify: `frontend/src/lib/copilot/session.ts`, `api.ts` (conclusion check; Seen), `cards/PackCard.svelte`
  ("Seen, leave as is"), `CopilotRail.svelte` (scroll to/open a card by key)
- Modify: `frontend/src/lib/hybrid-stack/HybridStackView.svelte` (prop, chip, disabled clause)
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte` (wire)
- Modify: `frontend/src/lib/copilot/contract.json` + `backend/tests/test_copilot_ui_contract.py` if the contract test
  covers the new fields/route

**Interfaces:**
- `notNeeded(p: Preview): string[]` — labels of draft rows in state `asked` with `needed === false` and not waiting.
- `openQuestions(p)` — draft rows `asked` with `needed === true` only (pre-draft fallback unchanged).
- `gate.ts`: `export type Unresolved = { key: string; name: string }`;
  `export function significant(p: Preview | null | undefined): boolean` — true when the card's current verdict
  (draft outcome or `most_likely`) has category `workup` | `refer` | `surveillance`, or `openQuestions(p).length > 0`,
  or `p.scope_doubt.length > 0`; false for null/degraded/failed previews, `does_not_apply`, reference (tier 2) and
  off-modality cards.
  `export function unresolved(state: CopilotState, seen: Record<string, string>, concl: Record<string, ConclusionCategory | null>): Unresolved[]`
  (`ConclusionCategory = 'none' | 'surveillance' | 'workup' | 'refer'`; `Unresolved` gains `reason?: string`)
  — a card is unresolved when `significant`, not cleared by the category rule below, and not `seen[key] === verdictKey(p)`
  (`verdictKey` = category + headline, so a changed verdict re-opens it).
- `CopilotSession` gains `seen(ref: string): void` and `checkConclusion(conclusion: string): void` (debounced 800 ms;
  calls `/conclusion_check` with the significant cards; stores the categories in state; a failure stores null);
  `CopilotState` gains `seen: Record<string,string>`, `concl: Record<string, ConclusionCategory | null>`.
- `HybridStackView` props: `guidelinesUnresolved: { key: string; name: string }[] = []`,
  `onOpenGuideline: (key: string) => void = () => {}`. Confirm `disabled` adds `|| guidelinesUnresolved.length > 0`.
  Chip text: `${n} guideline${n === 1 ? '' : 's'} unresolved`, a button calling `onOpenGuideline(first.key)`.

- [ ] **Step 1: Failing tests:**
  - format: `openQuestions` counts only needed asked rows; `notNeeded` lists the others; the head shows
    "1 question open" and the body a collapsed "4 not needed on this branch" that expands to the labels.
  - format: an exclusion with `exclusion_reason.outcome` uses `exclusion.headline` and `exclusion.recommendation` as
    headline/action; a generic exclusion keeps today's reason-first headline.
  - ValueRow: a row with `basis` shows it under the value.
  - gate: `significant` true for a workup verdict; false for degraded/failed/loading/does_not_apply/tier 2/
    off-modality; `unresolved` drops a card whose conclusion category rank ≥ its verdict category rank
    (none 0 < surveillance 1 < workup 2 < refer 3), and for a card with no verdict category any category other than
    none clears; a lower rank keeps it with `reason` "Conclusion gives {follow-up imaging|further tests|referral|no
    recommendation}; {name} says {follow-up imaging|further tests|referral}" shown on the card; `seen` clears until the verdict changes ("gate: seen clears");
    "gate: failed card never blocks".
  - session: `checkConclusion` debounces, sends only significant cards, stores the categories; a rejected request stores
    null for those keys and does not throw.
  - HybridStackView: with `guidelinesUnresolved=[{key:'k',name:'BTS 2015'}]` Confirm is disabled and the chip reads
    "1 guideline unresolved"; clicking it calls `onOpenGuideline('k')`; with `[]` behaviour is identical to today
    (existing tests unchanged).
  - PackCard: an unresolved card shows "Seen, leave as is"; clicking calls `seen(key)`.
- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Implement.** In DictationScratchpad: `$: guidelinesUnresolved = copilotActive && $copilotState?.on ?
  unresolved($copilotState, $copilotState.seen, $copilotState.concl) : []`; call `copilot?.checkConclusion(text)`
  reactively on the current conclusion text (use the same conclusion source the confirm bar's `hasConclusion` uses);
  `onOpenGuideline` opens the card in the rail and scrolls it into view.
- [ ] **Step 4: All frontend tests + svelte-check; backend contract test.**
- [ ] **Step 5: Commit** `feat(copilot-ui): truthful counts, growth exclusion wording, interval basis, confirm gate`.

### Task 8: Checkpoint and hand-off (controller)

- [ ] Restart local servers on the new tips (backend :8010 from copilot-ui/backend, frontend :5173), message Hassan
  before the Chrome run, replay the 12 March 2025 nodule case: BTS shows "Clear growth → investigate further" with age
  "assumed 18 or over"; Fleischner shows "Outside the Fleischner table: interval growth"; interval shows 581 days "from
  the CT of 12 Mar 2025" (or the day count for the run date); Confirm is blocked with "2 guidelines unresolved" until the
  conclusion states a recommendation or "Seen" is tapped. Record a GIF to Downloads.
- [ ] Whole-branch independent review (most capable model) on both branches; one fix round; re-review.
- [ ] Tell backend-1b the new tips. The walk's second Confirm button and walk stops exist only on the integration
  branch: ask backend-1b to add `|| guidelinesUnresolved.length > 0` to the walk's Confirm and include the unresolved
  cards in `stops` at merge (agreed in principle 2026-10-14).
