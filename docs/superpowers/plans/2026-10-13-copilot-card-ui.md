# Copilot Card UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one Copilot interface for guideline cards, made of the same components in two places:
- **the scratchpad**, while dictating and before Generate;
- **the post-generation report view**, later.

The scratchpad Copilot copies the existing post-generation review rail. It uses the same rail frame (a 340 px dark panel, white/10 borders and a tabs row, collapsing to a strip below 1100 px) and the same guideline card shell (`.gl-card`, from `GuidelinesPanel.svelte`). It is not a second design. After generation, the same rail shows the Review tab (outstanding issues) beside the same Guidelines tab, and that tab holds the same Copilot cards.

The frontend is built in slices that run alongside the backend draft-card plan. A slice starts only once the API it reads is stable, and each later slice names the backend task it waits for.

**Architecture:**
- **A typed client, `frontend/src/lib/copilot/`.** It is the only place that names backend fields:
- `types.ts`, which mirrors `copilot/types.py` and the request models in `routes.py`;
- `api.ts`, with one function per endpoint;
- `contract.json`, which lists every field the UI reads. A backend test asserts those fields exist, so a backend task cannot silently break the UI.
- **Pure state, `copilot/state.ts`.** It holds:
- the stability rule: which findings are ready to match;
- the match plan: whether a /match call is needed, based on a cache of unit texts;
- card grouping: exam cards first, then findings in dictation order, with siblings as columns;
- each card's kind;
- `outcomeOf(preview)`, which bridges `proposal` today and `draft_outcome` after Task 3;
- the quiet-line rule.
- **The session store, `copilot/session.ts`.** It holds the calls, the per-card UI state, sequence guards and fail-open handling. The host builds it, so the scratchpad (a legacy-mode component) only forwards grouping rounds to it.
- **The shared shell, `frontend/src/lib/rail/`.**
- `RailFrame.svelte` and `RailTabs.svelte`, extracted from `ReviewRail.svelte`;
- `GlCard.svelte`, extracted from `GuidelinesPanel.svelte`'s `.gl-card`.

ReviewRail and GuidelinesPanel are refactored onto these with no change in behaviour, and their existing tests are the guard.
- **Card components, `frontend/src/lib/copilot/cards/`.**
- `CopilotCards.svelte` is the guideline pane: the list, "Other guidelines", the empty, failure and skeleton states, and the quiet exam line.
- `PackCard.svelte`, `SiblingColumns.svelte` and `ReadOnlyCard.svelte` (needs-modality, tier 2 reference, TNM and "other") all sit on `GlCard`.
- `CopilotRail.svelte` is `RailFrame` with one tab, "Guidelines", rendering `CopilotCards`. It is the scratchpad placement.
- Post-generation, `ReportResponseViewer`'s existing `ReviewRail` Guidelines snippet renders `CopilotCards` above today's `/enhance` cards (Slice G).

**Tech Stack:**
- SvelteKit with Svelte 5. New components use runes. `DictationScratchpad.svelte` stays in legacy mode (`export let`, `$:`), so it takes the session store as a Svelte `writable`.
- Tests use vitest (`*.test.ts`) and vitest-browser-svelte (`*.svelte.test.ts`). Types are checked with `npm run check`.
- Each UI task ends with a browser check through the `claude-in-chrome` skill, on a guarded dev page.

**Spec:**
- `docs/superpowers/specs/2026-10-12-scratchpad-copilot-design.md`: §3 layout, §4 interaction, §7 failure.
- `docs/superpowers/specs/2026-10-12-guideline-library-design.md`:
- §5.1–5.3: two kinds of pack, who decides, card weight;
- §7.1: siblings;
- §7.4–7.11: draft card, value states, inline edit, Calculate and Apply, checker, Which lesion, safety rule, case-aware reference.
- Backend contract: `docs/superpowers/plans/2026-10-13-guideline-draft-card.md`, Tasks 1, 3, 5, 7, 8 and 9.
- The mock-up brief to build on is `docs/superpowers/plans/2026-10-12-scratchpad-copilot.md` §Task 14. Task 0 replaces it, because the 2026-10-12 card states were superseded by the draft card (§7.4).

## Global Constraints

- **Repository rules:**
- Work in a separate worktree branched from `feat/scratchpad-copilot`, for example `.claude/worktrees/copilot-card-ui` on branch `feat/copilot-card-ui`. Never run implementers in parallel in one worktree (controller ruling, progress.md).
- Rebase onto `feat/scratchpad-copilot` before each slice that reads a newly landed backend task.
- Never push. Never amend. Never commit `backend/uv.lock`. Stage only the files a task names.
- Every commit ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FMmCUNDQq6iPV6tn4pSRPH
  ```
- **Off by default.**
- The Copilot UI renders only when all three hold: the server reports `stack_copilot: true` (`copilot_allowed()`, kill switch `RR_STACK_COPILOT=0`), the hybrid stack is on, and the browser opted in (`localStorage.rr_stack_copilot === '1'`; anything else is off).
- With the UI off, no Copilot request is ever sent.
- A 404 from any Copilot route (the server's `_require()`) turns the session off for the rest of the page.
- **Apply stays off.** No slice before Slice F renders Apply, even though today's pack `/open` can still return an Apply-able `proposal`. Outcomes show as read-only text labelled "on these values". Slice F ships behind a second flag and lands only after Hassan enables Apply (backend Task 9).
- **Nothing reaches the report** from any slice before F. The scratchpad's findings block, `/draft`, `GateRecord` and Generate are untouched until Slice F.
- **Fail open everywhere** (copilot spec §7):
- no Copilot failure blocks dictation, grouping, Confirm or Generate;
- a failed /match shows no cards;
- a failed /open shows a retry state on that card only;
- every request has a timeout and an `AbortController`, and stale responses are dropped by sequence number.
- **Dev and test routes** ship guarded with `$lib/guards/dev-route` (`+page.ts`: `export const load = () => requireDevRoute();`) from their first commit.
- **No patient data** in fixtures, tests or commits. Fixtures are synthetic, mark it in a comment (`// SYNTHETIC`), and are built from pack names and generic phrases.
- **British English** in user-facing strings. House style: terse comments that say why, the rail's CSS variables (`--rv-*`), and no new hue families beyond those Task 0 agrees.
- **Tests:**
- Pure modules get `vitest` unit tests (`npx vitest run <file>`). Components get `*.svelte.test.ts` with `vitest-browser-svelte` and a mocked `$lib/copilot/api`.
- Every task runs `npm run check` (no new errors) and the full suites of any file it touched.
- A4 also runs every existing rail test unchanged: `src/lib/review/rail/*.svelte.test.ts` and `src/routes/components/ReportResponseViewer.railpolish.svelte.test.ts`.
- **Browser check step (every UI task):**
- Start `npm run dev` with `PUBLIC_ENABLE_DEV_ROUTES=true`. Set `localStorage.rr_stack_copilot = '1'` and run the backend with the copilot routes on.
- Open the task's dev page in Chrome through the `claude-in-chrome` skill. Exercise the named states, read the console for errors, and take one screenshot per state for the review.
- If the browser cannot run, stop and ask the controller. Never skip the check.
- **Review:** "reviewed" means an independent reviewer. Each slice ends with a review of its commit range before the next slice starts.

## Review Focus

1. **No unseen writes.** No path before Slice F changes the editor text, `GateRecord`, the findings block or a Generate payload.
2. **Off means silent.** With the flag off, or after a 404, no Copilot request is made. Check the network tab in the browser check.
3. **Stability rule.** /match is never called for a unit still growing while the radiologist is mid-sentence. A unit is matched once per distinct normalised text. Re-sending unchanged findings is allowed, because the server caches them, but there are no duplicate calls for the same plan.
4. **One field list.** Every backend field the UI reads is in `copilot/types.ts` and `contract.json`. Components never index raw JSON.
5. **Shared shell.** After A4 the post-generation rail renders exactly as before: existing tests unchanged and green, and a before/after screenshot compared.
6. **Read-only cards.** Needs-modality, tier 2 reference and TNM cards never show inputs, Calculate or Apply. Needs-modality cards never call /open.

## Scaffold decision

**What the post-generation scaffold is today:**
- **Frame.** `ReviewRail.svelte` holds an `<aside class="rv-rail">` 340 px wide, with the `--rv-*` theme tokens, `data-theme`, a narrow strip below 1100 px that opens an overlay, and a head with tabs (Review / Guidelines, `role="tablist"`). The Guidelines tab body comes in as a `guidelines` snippet from the host. The frame also has a skeleton (`rv-skel-card`) and a `pending` slot for when a rail is expected.
- **Guideline pane.** `RailGuidelines.svelte` loads `/enhance` (through `lib/guidelines/enhance.ts`) and renders `GuidelinesPanel.svelte`, whose `.gl-card` is a head (title, grade badge, action hint, controls, chevron) above a body that expands.
- **Mounting.** `ReportResponseViewer.svelte` (lines ~1274 and ~1560) puts `ReviewRail` in a flex row beside the editor and passes the `railGuidelines` snippet. `railActive.ts` tells the page to hold back the old `ReportEnhancementSidebar` ("Copilot aside") while a rail shows.

**Decision.** Extract the frame and the card shell into a neutral `lib/rail/`. Both placements then use the same components.

| New shared component | Extracted from | Used by |
|---|---|---|
| `lib/rail/RailFrame.svelte` (aside, `--rv-*` tokens, theme, narrow strip and overlay, `head` and `body` snippets, `stripLabel`) | `ReviewRail.svelte` outer markup and its `.rv-rail`/strip/overlay CSS | `ReviewRail`, `CopilotRail` |
| `lib/rail/RailTabs.svelte` (`tabs: {id,label}[]`, bindable `active`) | ReviewRail's `.rv-tabs` | `ReviewRail`, `CopilotRail` (one tab now; Review joins post-generation) |
| `lib/rail/RailSkeleton.svelte` | ReviewRail's `rv-skel-*` block | both |
| `lib/rail/GlCard.svelte` (`title`, `badge`, `hint`, `accent`, bindable `open`, `dim`, `controls` and `body` snippets) | `GuidelinesPanel.svelte`'s `.gl-card` head and body and their CSS | `GuidelinesPanel`, every Copilot card |

Scratchpad placement: `DictationScratchpad.svelte`'s root gets a flex row of `[scratchpad-wrapper | CopilotRail]`. The rail is full height and outside the editor's scroll container, as `ReportResponseViewer` places `ReviewRail`. The 240 px IntelliPrompts margin column is left alone; it is already hidden in the stack view.

```
Scratchpad (stack view on, Copilot on)
┌─ Scratchpad ───────────────────────────────┐ ┌─ Copilot rail (RailFrame, 340 px) ─────┐
│ HEART                                      │ │ [Guidelines]                            │
│  Coronary arteries smooth, no plaque.      │ │ ─ CAD-RADS 2.0 · CAD-RADS 0 ········ › │  quiet exam line (§5.3)
│ LUNGS                                      │ │ ─ 7 mm solid nodule, right lower lobe ─ │  finding header
│  7 mm solid nodule, right lower lobe.      │ │ ┌ Fleischner 2017 ──┬ BTS 2015 ───────┐ │  siblings = columns (§7.1)
│ THYROID                                    │ │ │ applies           │ check first     │ │
│  1.8 cm left thyroid nodule.               │ │ │ on these values:  │ Does this apply?│ │
│ KIDNEYS                                    │ │ │ …                 │ …               │ │
│  …                                         │ │ └───────────────────┴─────────────────┘ │
│ CONCLUSION                                 │ │ ─ 1.8 cm left thyroid nodule ────────── │
│  …                                         │ │ BTA U grading · needs ultrasound        │  read-only (needs_modality)
└────────────────────────────────────────────┘ │ ─ 4 cm right upper lobe mass ───────── │
                                             │ TNM 9 · Lung                       ›    │  read-only
                                             │ [ Other guidelines ]                    │  POST /match/other
                                             └─────────────────────────────────────────┘
 below 1100 px: the rail is a strip "3 guidelines" that opens the same panel as an overlay

Post-generation (Slice G)
┌─ Report editor ────────────────────────────┐ ┌─ Review rail (same RailFrame) ─────────┐
│ FINDINGS …                                 │ │ [Review] [Guidelines]                  │
│                                            │ │ Guidelines tab:                        │
│                                            │ │   CopilotCards (same components)       │
│                                            │ │   ── Supporting information ──         │
│                                            │ │   today's /enhance GlCards             │
└────────────────────────────────────────────┘ └────────────────────────────────────────┘
```

## File Map

| File | Change |
|---|---|
| `frontend/src/lib/copilot/types.ts` | new: wire types mirroring `copilot/types.py` and the request models (A1; later slices add optional fields) |
| `frontend/src/lib/copilot/api.ts` (+ `api.test.ts`) | new: `postMatch`, `postMatchOther`, `postOpen`, `postPreview` (A1); `postCalculate` (B2) |
| `frontend/src/lib/copilot/contract.json` | new: model → fields the UI reads (A1; each slice appends) |
| `backend/tests/test_copilot_ui_contract.py` | new: asserts every `contract.json` field exists on the pydantic models (A1) |
| `frontend/src/lib/copilot/flag.ts` (+ test) | new: `copilotOn(store, serverAllows, stackOn)`, key `rr_stack_copilot` (A2) |
| `frontend/src/routes/+page.svelte`, `routes/components/IntelliDictateTab.svelte`, `routes/components/TemplateForm.svelte` | pass `stack_copilot` → `stackCopilot` prop (A2) |
| `frontend/src/lib/copilot/state.ts` (+ test) | new: stability, match plan, grouping, kinds, `outcomeOf`, quiet rule (A3); value/edit helpers (B) |
| `frontend/src/lib/rail/RailFrame.svelte`, `RailTabs.svelte`, `RailSkeleton.svelte`, `GlCard.svelte`, `rail.css` | new, extracted (A4) |
| `frontend/src/lib/review/rail/ReviewRail.svelte`, `GuidelinesPanel.svelte` | refactored onto `lib/rail` with no change in behaviour (A4) |
| `frontend/src/lib/copilot/cards/CopilotCards.svelte`, `PackCard.svelte`, `SiblingColumns.svelte`, `ReadOnlyCard.svelte`, `QuietLine.svelte`, `CopilotRail.svelte` (+ tests) | new (A5); `ValueRow.svelte`, `ValueEdit.svelte`, `CalcResult.svelte` (B); `LessonPick.svelte` (C); `CheckerFlag.svelte` (D); `Reference.svelte` (A5, highlight in E) |
| `frontend/src/lib/copilot/session.ts` (+ test) | new: the session store (A6); edits and Calculate (B2); lesion (C) |
| `frontend/src/routes/dev/copilot/+page.ts`, `+page.svelte` (+ `page.svelte.test.ts`) | new, guarded: fixture gallery of every card state (A5), extended by each slice |
| `frontend/src/routes/dev/hybrid-stack/+page.svelte` | add the Copilot rail beside the replayed stack view, for the live browser check (A7) |
| `frontend/src/lib/components/DictationScratchpad.svelte` | mount `CopilotRail`; feed grouping rounds and recording state to the session (A7) |
| `frontend/src/lib/hybrid-stack/api.ts` | `StackLog.copilot?` (A7: keys, states and ms only, no text) |
| `frontend/src/lib/review/rail/RailGuidelines.svelte`, `routes/components/ReportResponseViewer.svelte` | Copilot cards in the Guidelines tab behind `rr_report_copilot` (G) |

## Task list

0. Mock-up checkpoint, with Hassan's approval (waits for nothing)
- **Slice A** (waits for M4 to pass review):
1. Typed client and contract test
2. Feature flag plumbing
3. Pure state: stability, match plan, grouping, kinds, quiet rule
4. Shared shell extraction (`lib/rail`)
5. Card components and `/dev/copilot`
6. Session store
7. Scratchpad mount and live browser check
- **Later slices:**
- **B1.** Value rows, value states and "set by the exam" (waits for backend Task 3, and R1)
- **B2.** Inline edit, shared patient answers and Calculate (waits for Task 3 `/calculate`)
- **C.** Which lesion? (waits for Task 8)
- **D.** Checker flag (waits for Task 7)
- **E.** Case-aware reference highlight (waits for Task 5; Task 6 adds data only)
- **F.** Apply, off until Hassan enables it (waits for Task 9 and his decision)
- **G.** Post-generation placement (waits for a backend data source not yet planned; see Q6)

A1–A3 are not visual, so they may start before Task 0 is approved. A4–A7 and every later slice wait for the approval.

---

### Task 0: Mock-up checkpoint (Hassan approves)

**Reads:** nothing (static).

- [ ] **Step 1:** Load the `artifact-design` skill and publish one clickable page in the house dark theme. Use the rail tokens `--rv-*`: purple accent, amber means "needs your answer", emerald normals, rose for the radiologist's additions. Show the scratchpad on the left and the Copilot rail (340 px) on the right, with these states:
- a quiet exam line (CAD-RADS 0) and its expanded form;
- a finding card collapsed, loading, "applies" (outcome read-only, "on these values"), "check first" (one to three "Does this apply?" rows above dimmed values), and "does not apply" (dimmed, with the reason and citation);
- siblings as two columns, neither preselected;
- a needs-ultrasound card ("BTA U grading needs ultrasound to grade");
- a TNM card; an "other guidelines" card;
- failure states: match failed (nothing, with a quiet retry), open failed (retry), degraded ("some values could not be checked");
- later slices, greyed and labelled as future: value rows read / pre-filled (with the "why" chip) / asked / answered / edited / N/A, and "set by the exam"; the inline edit menu with "Not stated", "Absent" and "Not assessable"; Calculate with its result and citations; the checker flag (agrees / disagrees); the Which-lesion pick; the reference with highlighted rows and the rest collapsed; Apply (marked "off");
- the narrow strip (below 1100 px) with its overlay;
- the post-generation rail with [Review] [Guidelines], the Guidelines tab holding the same cards above "Supporting information".
- [ ] **Step 2:** Propose the tints: pre-filled uses the existing amber-soft (`--rv-amber-bg`) highlight only on the value, never on the card; "set by the exam" is a neutral chip. Send Hassan the link and put Q1–Q9 (below) to him. **Stop until he approves the layout and tints.** Record the agreed classes in a comment at the top of `lib/rail/GlCard.svelte` (A4).

---

### Task A1: Typed client and contract test

**Waits for:** M4 reviewed (the `needs_modality` field).
**Reads:** `POST /match`, `POST /match/other` → `MatchResult`; `POST /open`, `POST /preview` → `OpenResult`.

**Files:**
- Create: `frontend/src/lib/copilot/types.ts`, `api.ts`, `api.test.ts`, `contract.json`
- Create: `backend/tests/test_copilot_ui_contract.py`

**Interfaces** (`types.ts`; fields from later slices are optional, and each comment names its backend task):
```ts
// Wire types for /api/canvas/stack/guidelines/* (backend hybrid_stack/copilot/types.py, routes.py).
// The ONLY place the UI names backend fields; contract.json lists them for the backend's contract test.
export type CardState = 'applies' | 'check_first' | 'does_not_apply' | 'which_lesion'; // which_lesion: Task 8
export interface Publication { title: string; body: string; year: string }
export interface Card {
	key: string; name: string; version: string;
	finding_id: string;            // "u<unit>" | "u<unit>.<part>" | "exam" (exam-level card)
	why: string; branch: string; skeleton: string[]; publication: Publication; known: boolean;
	status: 'draft' | 'verified' | 'new';
	siblings: string[];            // other bodies' pack keys on the same topic: columns on this card (§7.1)
	reference: boolean;            // tier 2: read-only
	finding: string;               // the unit text (exam card: the dictation) as /match returned it
	needs_modality: string;        // e.g. "US": read-only, never opened (M4)
}
export interface Citation { [k: string]: unknown }  // rendered as given (label, locator, url)
export interface Proposal { classification: string; line: string; recommendation: string; caveats: string[]; citations: Citation[] }
export interface Settled { input: string; value: string; quote: string; fact: string; by: '' | 'exam' }
export interface Ask { [k: string]: unknown }       // label, definition, options, decides, citations (rendered as given)
export type ValueState = 'read' | 'prefilled' | 'asked' | 'answered' | 'edited' | 'not_applicable'; // Task 3
export interface DraftValue {                        // Task 3
	input: string; label: string; role: string; scope: string; fact: string; state: ValueState;
	value: string; quote: string; why: string[]; needed: boolean; waiting: boolean; options: string[];
	by?: '' | 'exam';                                // contract request R1
}
export interface Checker { category: string; quote: string; verdict: 'agrees' | 'disagrees' | 'unchecked'; outcomes: string[]; computed: string[] } // Task 7
export interface Highlight { linked: boolean; ids: string[]; rows: Record<string, number[]> }  // Task 5
export interface Preview {
	settled: Settled[]; missing: string[]; proposal: Proposal | null; state: CardState; exclusion: Proposal | null;
	possible: string[]; bounded: boolean; asks: Ask[]; trace: Record<string, unknown> | null; degraded: boolean;
	waiting?: string[];                              // Task 1
	draft?: DraftValue[]; draft_outcome?: Proposal | null;   // Task 3
	checker?: Checker | null;                        // Task 7
	lesions?: string[]; lesion?: string;             // Task 8
	highlight?: Highlight | null;                    // Task 5
}
export interface ReferenceView { summary: RefItem[]; definitions: RefItem[]; tables: RefItem[]; pitfalls: RefItem[] }
export interface RefItem { id?: string; citation?: string; [k: string]: unknown }
export interface Entry { key: string; name: string; version: string; status: 'draft' | 'verified';
	publication: Publication; content: { applies_to: string; summary: string; branches: unknown[] }; sources: { url: string; title: string; tier: number }[] }
export interface OpenResult { entry: Entry | null; preview: Preview | null; branch: string; ms: number;
	error: 'unavailable' | 'loading' | 'unknown guideline' | string | null; reference: ReferenceView | null; needs_modality: string }
export interface MatchResult { cards: Card[]; ms: number }
export interface Calculation { outcome: string | null; result: Proposal | null; exclusion: Proposal | null; possible: string[];
	needed: string[]; values: DraftValue[]; trace: Record<string, unknown> | null; pack: string; bundle: string;
	checker?: Checker | null; highlight?: Highlight | null; lesion?: string }        // Task 3 (+5, 7, 8)
export interface CalculateResult { calculation: Calculation | null; ms: number; error: string | null }

export interface MatchBody { scan_type: string; clinical_history: string; findings: { id: string; text: string }[]; dictation: string; patient: Record<string, string> }
export interface OpenBody { card: Card; finding: string; findings: string; clinical_history: string;
	answered: Record<string, string>; patient: Record<string, string>; lesion?: string }       // lesion: Task 8
export interface CalculateBody extends OpenBody { values: Record<string, string> }            // Task 3
```

`api.ts`:
- A `post<T>(path, body, timeoutMs, signal?)` on `${API_URL}/api/canvas/stack/guidelines/`, with a bearer token from `get(token)` (as `lib/review/api.ts` does).
- Errors are typed: `CopilotOff` on 404, so the session turns off; `CopilotError` otherwise.
- Timeouts:
- match 45 s;
- match/other 60 s;
- open 90 s (`OPEN_TIMEOUT_S` is 60 on the server, and its comment asks for 90 or more);
- preview 35 s (`PREVIEW_TIMEOUT_S` is 25);
- calculate 35 s.
- Client caps, mirroring the server: at most 20 findings; each finding's text ≤ 1000 characters (`FindingIn`); `answered` ≤ 20.

- [ ] **Step 1: Failing tests** (`api.test.ts`):
- each helper posts to its route;
- the body holds exactly the `MatchBody`/`OpenBody` keys;
- a 404 throws `CopilotOff`;
- a timeout aborts;
- findings are capped at 20 and each text at 1000.
- [ ] **Step 2:** Write `contract.json`, for example `{"Card": ["key", …, "needs_modality"], "Preview": ["settled", …, "degraded"], "OpenResult": […], "MatchResult": ["cards", "ms"], "MatchRequest": […], "OpenRequest": […]}`, listing only the fields Slice A reads. Each later slice appends its own fields in its own task.
- [ ] **Step 3:** Write `backend/tests/test_copilot_ui_contract.py`. It loads `../frontend/src/lib/copilot/contract.json` relative to the repo root and asserts every name is in `Model.model_fields`, for the models in `copilot/types.py` (`Card`, `Preview`, `Settled`, `Proposal`) and `copilot/routes.py` (`OpenResult`, `MatchResult`, `MatchRequest`, `OpenRequest`, `CardIn`). It skips cleanly if the frontend folder is absent. No network.
- [ ] **Step 4:** Run `cd frontend && npx vitest run src/lib/copilot/api.test.ts && npm run check`, then `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_copilot_ui_contract.py -q`.
- [ ] **Step 5: Commit** `feat(copilot-ui): typed client, contract list and backend contract test`.

---

### Task A2: Feature flag plumbing

**Reads:** `GET /api/settings/status` → `stack_copilot` (`main.py`; `copilot_allowed()`).

**Files:** `frontend/src/lib/copilot/flag.ts` (+ `flag.test.ts`), `frontend/src/routes/+page.svelte` (`apiKeyStatus.stack_copilot = data.stack_copilot === true`), `routes/components/IntelliDictateTab.svelte` and `routes/components/TemplateForm.svelte` (`$: stackCopilot = copilotOn(undefined, stackStatus?.stack_copilot === true, hybridStack)`, passed to `DictationScratchpad` as `stackCopilot`), and `DictationScratchpad.svelte` (`export let stackCopilot = false;`, unused until A7).

```ts
export const COPILOT_KEY = 'rr_stack_copilot';
/** On only when the server allows it, the stack is on, and this browser opted in ("1"); default off. */
export function copilotOn(store = storage(), serverAllows = false, stackOn = false): boolean
```

- [ ] **Step 1:** Write failing tests for the full truth table, covering a blocked `localStorage` (which means off) and a missing key (also off).
- [ ] **Step 2:** Implement, then run the tests and `npm run check`.
- [ ] **Step 3:** Browser check: with the key unset, the network tab shows no `/guidelines/` request while you dictate on `/`.
- [ ] **Step 4: Commit** `feat(copilot-ui): stack_copilot flag, off unless opted in`.

---

### Task A3: Pure state

**Reads:** the `Card` fields above; `Preview.state`, `missing`, `proposal`, `degraded`, `settled[].by`; `draft_outcome` once it exists.

**Files:** `frontend/src/lib/copilot/state.ts`, `state.test.ts`.

**Interfaces:**
```ts
export interface Finding { id: string; unitId: number; text: string; region: string }
export const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ').replace(/[.;,]$/, '');

/** Abnormal, placed findings in dictation order, ids as the matcher expects ("u<id>" / "u<id>.<part>"),
 *  from effectiveItems (hybrid-stack/regionState). */
export function abnormalFindings(units: StackUnit[]): Finding[];

/** Spec (brief): a finding is ready to match once its text did not change across a grouping round, or the
 *  radiologist has moved on (a later placed unit exists), or dictation is not running. */
export function stableFindings(prev: Map<string, string>, now: Finding[], lastUnitId: number, recording: boolean): Finding[] {
	return now.filter((f) => !recording || prev.get(f.id) === f.text || f.unitId < lastUnitId);
}

export interface MatchPlan { call: boolean; findings: Finding[]; reason: 'new_text' | 'context' | 'exam' | 'none' }
/** Call /match when a stable finding's normalised text has not been sent under this context (scan type +
 *  history), or when no call has yet been made for this context and the dictation has placed text (exam cards
 *  bind with no abnormal finding). The body always carries ALL stable findings (≤ 20, dictation order): the server
 *  applies case-level caps and the one-TNM-per-site rule, and caches each unit, so unchanged findings cost nothing. */
export function planMatch(sent: Set<string>, ctx: string, sentCtx: string | null, stable: Finding[], hasText: boolean): MatchPlan;

/** Card identity that survives unit renumbering: key + "exam" or the normalised finding text. */
export const cardRef = (c: Card) => `${c.key}|${c.finding_id === 'exam' ? 'exam' : norm(c.finding)}`;

export type CardKind = 'exam' | 'finding' | 'tnm' | 'needs_modality' | 'reference' | 'other';
export function kindOf(c: Card, fromOther = false): CardKind;  // needs_modality > reference > tnm (key "tnm-") > exam > other > finding

export interface Group { finding: Finding | null; cards: Card[] }   // null: the exam group
/** Exam cards first, then one group per current finding in dictation order; cards whose finding text is no
 *  longer dictated are dropped (a deleted finding takes its cards, copilot spec §4.1). */
export function groupCards(cards: Card[], findings: Finding[]): Group[];

/** The outcome the card shows, read-only: Task 3's draft_outcome, else today's proposal (never Applied). */
export const outcomeOf = (p: Preview | null) => p?.draft_outcome ?? p?.proposal ?? null;

/** §5.3 quiet one-line card. Interim rule until contract request R3 (see Q2): an exam card whose preview applies,
 *  reached an outcome, needs nothing, is not degraded, and has no pre-filled value. */
export function quiet(c: Card, p: Preview | null): boolean;

export const modalityLabel = (m: string) => ({ US: 'ultrasound', CT: 'CT', MRI: 'MRI', XR: 'a radiograph' } as Record<string, string>)[m] ?? m;
```

- [ ] **Step 1: Failing tests** (synthetic units):
- a growing last unit is not stable while recording, and is stable once a later unit exists or recording stops;
- an unchanged text across two rounds is stable;
- `planMatch` calls once per new normalised text and not again for whitespace or case changes;
- a context change resets the plan;
- an empty-findings first call happens when the text exists (exam);
- `groupCards` drops cards for deleted findings and keeps exam cards first;
- `kindOf` covers every kind;
- `outcomeOf` prefers `draft_outcome`;
- `quiet` is true for a settled exam card and false when any of these hold: a value is pre-filled, `missing` is non-empty, `degraded`, or `state !== 'applies'`.
- [ ] **Step 2:** Implement, then run the tests and `npm run check`.
- [ ] **Step 3: Commit** `feat(copilot-ui): pure state — stability, match plan, grouping, card kinds`.

---

### Task A4: Shared shell extraction (`lib/rail`)

**Waits for:** Task 0 approved.
**Reads:** no API.

**Files:**
- Create: `frontend/src/lib/rail/RailFrame.svelte`, `RailTabs.svelte`, `RailSkeleton.svelte`, `GlCard.svelte`, `rail.css`
- Modify: `frontend/src/lib/review/rail/ReviewRail.svelte`, `GuidelinesPanel.svelte`

**What to move:**
- **`RailFrame`** takes the `<aside class="rv-rail">` markup and props `theme`, `layout`, `ariaLabel`, `testid`, `stripLabel` (the narrow strip's text), `stripCount`, `expanded`, plus `head` and `body` snippets. It moves ReviewRail's `matchMedia('(max-width: 1099.98px)')` logic, the overlay, and the `.rv-rail`, `.rv-narrow`, `.rv-strip`, `.rv-overlay` and `--rv-*` CSS.
- **`RailTabs`** takes the `.rv-tabs` markup and CSS.
- **`RailSkeleton`** takes the `rv-skel-*` markup.
- **`GlCard`** takes the `.gl-card` head and body and its CSS (`.gl-card`, `::before` accent, hover, `.gl-head`, `.gl-meta`, `.gl-title-row`, `.gl-title`, `.gl-grade-badge`, `.gl-action-hint`, `.gl-controls`, `.gl-chevron`, `.gl-body`). Its props are `title`, `badge {text, variant}`, `hint`, `accent`, `open` (bindable), `dim`, and `controls` and `body` snippets. Keyboard toggling (Enter and Space) stays.

ReviewRail keeps every behaviour: chat head, status line, urgency, reveal, pending skeleton and density. It renders `<RailFrame>` with its existing head and body. GuidelinesPanel renders each guideline through `<GlCard>`. Class names stay the same, so existing selectors in tests still match.

- [ ] **Step 1:** Before changing anything, take a screenshot of `/dev/review-rail`: one report, Review and Guidelines tabs, wide and narrow.
- [ ] **Step 2:** Extract, then run every rail test unchanged: `npx vitest run src/lib/review/rail src/routes/components/ReportResponseViewer.railpolish.svelte.test.ts` and `npm run check`.
- [ ] **Step 3:** Write `GlCard.svelte.test.ts`: it toggles on click and Enter, shows controls, and `dim` sets `aria-disabled`. Write `RailFrame.svelte.test.ts`: in the narrow layout the strip opens the overlay, and in the wide layout the head and body render.
- [ ] **Step 4: Browser check.** Screenshot `/dev/review-rail` again in the same states. It must be identical apart from sub-pixel differences; attach both sets.
- [ ] **Step 5: Commit** `refactor(rail): extract RailFrame, RailTabs, GlCard shared by the review rail and the Copilot`.

---

### Task A5: Card components and `/dev/copilot`

**Reads:**
- `Card`: every field;
- `OpenResult`: `entry.name`, `preview.state`, `missing`, `exclusion`, `possible`, `degraded`, `settled`, `proposal` / `draft_outcome` (through `outcomeOf`), `reference`, `needs_modality`, `error`;
- `MatchResult.cards`.

**Files:**
- Create: `frontend/src/lib/copilot/cards/CopilotCards.svelte`, `PackCard.svelte`, `SiblingColumns.svelte`, `ReadOnlyCard.svelte`, `QuietLine.svelte`, `Reference.svelte`, `CopilotRail.svelte`, each with a `*.svelte.test.ts` where it has logic
- Create: `frontend/src/routes/dev/copilot/+page.ts` (guard), `+page.svelte`, `page.svelte.test.ts`

The components are presentational: they take state and callbacks and never call the API. The props of `CopilotCards`:
```ts
{ groups: Group[]; views: Record<string, CardView>; matching: boolean; matchFailed: boolean; otherState: 'idle'|'loading'|'done'|'failed';
onOpen(ref: string): void; onClose(ref: string): void; onRetry(ref: string): void; onRetryMatch(): void; onOther(): void }
export type CardView = { open: boolean; loading: boolean; error: string | null; result: OpenResult | null;
columns?: Record<string, { loading: boolean; error: string | null; result: OpenResult | null }>; fromOther?: boolean }
```

**Rendering rules:**
- **Header per group.** The finding text, truncated to one line, sits in `.gl-inline-label` style. The exam group has no header.
- **Exam card.**
- When `quiet(card, preview)` holds, render `QuietLine`: one line, "`<name>` · `<outcome classification>`", with a chevron that expands the full card. Never show optional inputs and never show Apply (§5.3).
- Otherwise, render it as a `PackCard`.
- The badge "set by the exam" appears on the line when any `settled[].by === 'exam'` (Settled.by is live since M1b).
- **PackCard, collapsed:** name, version, and a badge carrying the state once a preview exists ("applies", "check first", "does not apply"). The hint shows the outcome classification, prefixed "on these values ·".
- **PackCard, opened (read-only in Slice A):**
- `does_not_apply`: the card dims (`GlCard dim`) and shows `exclusion.classification` with its citations.
- `check_first`: the line "Some eligibility questions need an answer before this applies", then the `missing` labels from `asks`, read-only.
- `applies`: the outcome (classification, recommendation, caveats, citations) labelled "on these values", read-only; or, with no outcome, "Possible:" followed by the `possible` list.
- `degraded`: the note "Some values could not be checked".
- `Reference` renders `reference` (summary, definitions, tables, pitfalls with citations), collapsed under "Reference".
- **No inputs, no Calculate, no Apply.**
- **SiblingColumns.** Used when `card.siblings.length > 0`. Two (at most three) equal columns inside one `GlCard`, the primary card's column first, neither preselected (§7.1).
- Each column header shows `result.entry.name` once the column has opened, and falls back to the pack key's issuer slug.
- Each column body is the opened PackCard body, compact.
- Narrower than 300 px, the columns stack with a column switcher (Q5).
- **ReadOnlyCard:**
- `needs_modality`: "`<name>` needs `<modalityLabel>` to grade". No chevron and no request.
- `reference` (tier 2): opens to `Reference` only.
- TNM: opens to `entry.content.summary` and the branch criteria as text, with no Apply.
- "other": opens to the entry. `error === 'unavailable'` shows "Not in the guideline library yet".
- **States:**
- first match in flight: `RailSkeleton`;
- `matchFailed` with no cards: a muted "Couldn't check guidelines · Retry";
- no cards and not matching: "No guideline applies yet";
- per card, `loading` shows a skeleton line; `error` shows "Couldn't open · Retry", and "Still loading · Retry" for `error === 'loading'`.
- **The "Other guidelines" button** sits at the foot of the list. Its cards are tagged `fromOther` and grouped under their findings with the small label "other".
- **`CopilotRail`:** `RailFrame` + `RailTabs` with one tab, "Guidelines", + `CopilotCards`. The narrow strip label is "`<n>` guidelines".

**`/dev/copilot`:** a fixture gallery (`// SYNTHETIC`) with one section per state above, built from pack names only, plus a toggle to render in `CopilotRail` at wide and narrow widths.

- [ ] **Step 1: Failing component tests:**
- quiet exam line text, and that it expands;
- "set by the exam" badge;
- needs-modality text, no chevron, and `onOpen` never called;
- TNM read-only, with no button named Apply or Calculate anywhere;
- siblings render two columns with neither preselected;
- `does_not_apply` dims and shows the reason;
- `check_first` copy;
- `degraded` note;
- match-failed retry;
- the Other button calls `onOther`;
- a group whose finding was deleted renders nothing.
- [ ] **Step 2:** Implement, then run the tests and `npm run check`.
- [ ] **Step 3: Browser check** on `/dev/copilot`: every section, wide and narrow; keyboard open and close; no console errors; screenshots.
- [ ] **Step 4: Commit** `feat(copilot-ui): guideline cards on the shared rail shell; /dev/copilot gallery`.

---

### Task A6: Session store

**Reads:** `POST /match` (`MatchBody` → `MatchResult`), `POST /match/other`, `POST /open` (`OpenBody` → `OpenResult`).

**Files:** `frontend/src/lib/copilot/session.ts`, `session.test.ts`.

```ts
export interface CopilotContext { scanType: string; history: string }
export interface CopilotSession {
	state: Readable<{ on: boolean; groups: Group[]; views: Record<string, CardView>; matching: boolean; matchFailed: boolean; otherState: … }>;
	/** After each successful /group: units as placed, whether dictation runs, and the findings text Generate would
	 *  send (findingsText(units, groups)) — sent as /match `dictation` AND /open `findings` (contract R4). */
	round(units: StackUnit[], recording: boolean, findingsText: string): void;
	setContext(ctx: CopilotContext): void;    // a change resets the sent cache and the cards
	open(ref: string): void; close(ref: string): void; retry(ref: string): void; retryMatch(): void; other(): void;
	log(): { matched: string[]; opened: string[]; quiet: string[]; failed: Record<string, number>; ms: Record<string, number> };
	destroy(): void;
}
export function createCopilotSession(api = defaultApi): CopilotSession;
```

**Rules:**
- **`round`:**
- compute `abnormalFindings`, then `stableFindings` against the previous round's `id → text` map, then `planMatch`;
- at most one /match in flight; a plan made during the flight queues one follow-up (the latest wins);
- responses carry a `seq`, and stale ones are dropped;
- a successful response replaces the matched cards (the server is case-level), keeps `views` by `cardRef`, and adds every sent normalised text to `sent`;
- a failure sets `matchFailed`, caches nothing and leaves dictation alone.
- **Exam cards** auto-open (`/open` with `finding = findingsText`, the current dictation) as soon as they arrive, because the quiet rule needs their preview. They re-open, debounced 1.5 s, when recording stops and the findings text changed since their last open. Finding cards open only on click (Q3).
- **`open(ref)`:**
- the body is `{card, finding: card.finding_id === 'exam' ? findingsText : card.finding, findings: findingsText, clinical_history, answered: {}, patient: {}}`;
- for a card with siblings, every column opens in parallel, each with `{...card, key: siblingKey, name: siblingKey}` (`_check_card` accepts library keys whatever the name; the column header uses `entry.name`);
- `needs_modality` cards never open.
- **`other()`:** POST /match/other with the same stable findings, merged and deduped by `cardRef`, each tagged `fromOther`.
- **Off:** a `CopilotOff` (404) from any call sets `on = false`, aborts everything and stops all further calls.
- **`destroy`** aborts everything in flight.

- [ ] **Step 1: Failing tests** with a mocked api and fake timers, using synthetic rounds:
- a growing last unit makes no call until it is stable;
- a second identical round makes no call;
- a new finding calls once with all stable findings;
- an edit to a finding drops its cards and later matches the new text;
- a context change resets;
- a stale response is dropped;
- one call is in flight at a time, with one queued follow-up;
- exam cards auto-open with `finding = findingsText`, and the /match `dictation` equals the /open `findings`;
- siblings open in parallel;
- needs-modality never opens;
- a 404 turns the session off and later rounds make no call;
- a /match failure leaves no cards and sets `matchFailed`;
- "other" merges without duplicates.
- [ ] **Step 2:** Implement, then run the tests and `npm run check`.
- [ ] **Step 3: Commit** `feat(copilot-ui): session store — stable-unit matching, per-card state, fail-open`.

---

### Task A7: Scratchpad mount and live browser check

**Reads:** as A6. `POST /api/canvas/stack/log` gains `copilot` (the backend `LogRequest.copilot` field already exists).

**Files:**
- `frontend/src/lib/components/DictationScratchpad.svelte`
- `frontend/src/routes/dev/hybrid-stack/+page.svelte`
- `frontend/src/lib/hybrid-stack/api.ts` (`StackLog.copilot?: Record<string, unknown>`)

**Steps:**
- [ ] **Step 1:** In the scratchpad, add `$: copilotActive = stackCopilot && hybridStack && stackView;` and create one session on mount (only when active), destroyed on unmount or when it turns inactive.
- In `runGroup`, right after `stackUnits = res.units;`, call `copilot?.round(stackUnits, isRecording, findingsText(stackUnits, stackGroups))`.
- When recording stops, call `round(…, false, …)`.
- `$: copilot?.setContext({ scanType, history: clinicalHistory })`.
- Wrap the root in a flex row with `{#if copilotActive && $copilotState.on}<CopilotRail …/>{/if}`.
- On clear (`onScratchpadClear`), destroy the session and create a fresh one.
- [ ] **Step 2:** Add `copilot: session.log()` to the existing `postLog` payload. It holds keys, kinds, ms and error counts only, never text. The server caps it with `LOG_COPILOT_MAX`.
- [ ] **Step 3:** In `/dev/hybrid-stack`, add a "Copilot" checkbox that mounts `CopilotRail` with a session fed by the page's replay loop. Each replayed sentence is one round; a "recording" toggle simulates the pause and stop.
- [ ] **Step 4: Tests.** Extend `HybridStackView`'s tests only if its props change (they should not). Add a scratchpad-level test only if a harness exists; otherwise the session tests (A6) and this browser check cover it.
- [ ] **Step 5: Browser check** on `/dev/hybrid-stack` against the local backend (synthetic dictations only), checking each case in the network tab:
- **(a)** replaying a normal coronary CTA gives a quiet CAD-RADS line;
- **(b)** a nodule sentence gives a card with Fleischner and BTS columns only after the next sentence arrives (stability);
- **(c)** a thyroid nodule on CT gives the needs-ultrasound card with no /open;
- **(d)** a lung mass gives a TNM card;
- **(e)** "Other guidelines" works;
- **(f)** the backend stopped gives nothing, and dictation still works;
- **(g)** with `RR_STACK_COPILOT=0` there is no rail and no repeated calls after the first 404;
- **(h)** below 1100 px the strip and overlay work.

Then on `/` with the flag unset, confirm there is no rail and no request.
- [ ] **Step 6: Commit** `feat(copilot-ui): Copilot rail beside the scratchpad, fed by stable grouping rounds`.
- [ ] **Step 7:** Independent review of the Slice A range against Review Focus 1–6.

---

### Slice B1: Value rows, value states and "set by the exam"

**Waits for:** backend Task 3, plus R1 (`DraftValue.by`). Task 4 changes only the `why` strings, which the UI renders verbatim.
**Reads:**
- `Preview.draft[]`: `input`, `label`, `role`, `state`, `value`, `quote`, `why`, `needed`, `waiting`, `options`, `by`;
- `Preview.draft_outcome`, `waiting` (Task 1), `state`, `asks`.

**Files:** `copilot/cards/ValueRow.svelte` (+ test), `PackCard.svelte`, `state.ts` (`rowsOf(preview)`: eligibility rows first in `check_first`, then `needed` order; `waiting` hidden; `not_applicable` shown as "N/A"), `contract.json` (append), `/dev/copilot` fixtures.

**Rendering (§7.5):**

| State | Shown as |
|---|---|
| read | plain, with the quote on hover or focus |
| prefilled | highlighted (the agreed amber-soft), with the quote and a "why" chip listing `why[]` |
| asked | empty, with the `asks` explanation (definition, the outcomes it decides between, citations) |
| answered / edited | as set |
| `by === 'exam'` | the neutral chip "set by the exam" |

The draft outcome reads "on these values", read-only.

- [ ] Write failing tests for each state, the ordering, and waiting rows staying hidden; implement; browser check on `/dev/copilot` and live; commit `feat(copilot-ui): value states on the draft card`.

### Slice B2: Inline edit, shared patient answers and Calculate

**Waits for:** backend Task 3 (`POST /calculate`).
**Reads:**
- `POST /preview` with `answered`;
- `POST /calculate` (`CalculateBody.values`) → `Calculation`: `result`, `exclusion`, `possible`, `needed`, `values`, `pack`, `bundle`;
- `DraftValue.fact` (for patient answers).

**Files:** `ValueEdit.svelte`, `CalcResult.svelte` (+ tests), `api.ts` (`postCalculate`), `session.ts` (`edit(ref, input, value)`, `calculate(ref)`, a case-level `patient` map), `state.ts` (`valuesShown(preview, edits)`).

**Rules (§7.6–7.7, §7.4 "once per case"):**
- **The edit menu** offers the input's `options` (which already include "Not stated") plus "Absent" and "Not assessable" where the options carry them. N/A rows are not editable.
- **An edit** goes to the card's `answered` and re-posts `/preview`; the backend runs the engine only. An edit to an input with a `fact` also goes into the case `patient` map and re-previews every other open card that has that fact.
- **Calculate** sends `values`: every value the card shows, in display form, edits included. An input not shown is never sent.
- **The result** shows the classification, recommendation, caveats and citations, plus each value used with its state. With no outcome it shows the possible outcomes and what is still needed. An exclusion shows as an exclusion.
- **Any edit after Calculate** clears the result.
- **Still no Apply.**

- [ ] Write failing tests: `values` equals exactly the rows shown; an edit clears the result; a patient answer propagates; "Not stated" is sent as the backend's `NOT_STATED`. Then implement, run the browser check, and commit `feat(copilot-ui): inline edit, shared patient answers and Calculate`.

### Slice C: Which lesion?

**Waits for:** backend Task 8.
**Reads:** `Preview.state === 'which_lesion'`, `Preview.lesions`, `Preview.lesion`, `OpenRequest.lesion`, `Calculation.lesion`.

**Files:** `LesionPick.svelte` (+ test), `session.ts` (`pick(ref, span)` re-opens with `lesion`), `PackCard.svelte`.

**Rules (§7.9):**
- Before anything else, the card offers one pick from the verbatim spans. Patient values stay drafted.
- The picked span shows on the card and goes with each preview and calculate.
- Changing the pick clears edits to lesion inputs only.

- [ ] Tests, implementation, browser check, then commit.

### Slice D: Checker flag

**Waits for:** backend Task 7.
**Reads:** `Preview.checker` and `Calculation.checker`: `category`, `quote`, `verdict`, `outcomes`, `computed`.

**Files:** `CheckerFlag.svelte` (+ test), `PackCard.svelte`.

**Rules (§7.8):**
- `agrees`: a quiet tick, "Dictated `<category>` agrees".
- `disagrees`: a flag showing the computed category, or the possible ones, with the values and citations behind it. It never writes anything. Correcting a value re-checks.
- `unchecked`: "Cannot be checked on these values".

- [ ] Tests, implementation, browser check, then commit.

### Slice E: Case-aware reference

**Waits for:** backend Task 5. Task 6 adds links to packs; no UI change.
**Reads:** `Preview.highlight`, `Calculation.highlight` (`linked`, `ids`, `rows`); the reference item `id`s in `OpenResult.reference`.

**Files:** `Reference.svelte`, `state.ts` (`refView(reference, highlight)`).

**Rules (§7.11):**
- `linked` false: the full reference, expanded (today's behaviour).
- `linked` true: expand the `ids` items and the `rows` of each table, and collapse the rest under "Show full reference".
- The last Calculate's highlight replaces the draft's.

- [ ] Tests, implementation, browser check, then commit.

### Slice F: Apply (off until Hassan enables it)

**Waits for:** backend Task 9 (lab metrics) and Hassan's decision.
**Reads:** the last `Calculation` only.

**Files:**
- `copilot/apply.ts` (+ test): the enrichment and recommendation merge, following the 2026-10-12 copilot plan Task 16's pure functions, adapted. Each enrichment carries `outcome_id`, the trace, and the values with their states (§7.2).
- `hybrid-stack/types.ts` (`GateRecord.enrichments`, `recommendations`), `hybrid-stack/regionState.ts` (`buildFindingsBlock`), `HybridStackView.svelte` (the enrichment line under the finding and the Recommendations checklist), and `DictationScratchpad.svelte`.

**Flag and rules:**
- Server `stack_copilot` plus `localStorage.rr_copilot_apply === '1'`, and a server flag if Hassan wants one (Q1).
- Apply writes exactly the last Calculate result. Any edit clears it.
- The panel's Undo and the line's × do the same thing.
- The not-applied sibling column is logged as seen.

- [ ] Tests, implementation, browser check, independent review, then commit. **Do not start without Hassan's go-ahead.**

### Slice G: Post-generation placement

**Waits for:** a backend data source for report-side cards, which no plan has yet. See Q6. The shared components are ready after Slice A.
**Reads:** the same `CopilotCards` state, from whichever source Q6 picks.

**Files:** `frontend/src/lib/review/rail/RailGuidelines.svelte` (render `CopilotCards` above `GuidelinesPanel`, under the label "Guidelines for this case", when `rr_report_copilot === '1'` and the session has cards); `frontend/src/routes/components/ReportResponseViewer.svelte` (create or attach the session for the report).

**Rules:**
- The Review tab (outstanding issues) is unchanged.
- The guideline pane stays hidden until the source exists and the flag is on.
- `railActive.ts` is unchanged: the rail still holds the old aside back.

- [ ] Tests, implementation, browser check on `/dev/review-rail`, then commit.

---

## API contract (what the UI reads; backend tasks must not break it)

The base is `/api/canvas/stack/guidelines`. Every route returns 404 when `copilot_allowed()` is false, and the UI treats that as "off". `contract.json` is the list a machine checks (`backend/tests/test_copilot_ui_contract.py`); this table is the human view.

| Endpoint | Request fields the UI sends | Response fields the UI reads | Slice |
|---|---|---|---|
| `GET /api/settings/status` | — | `stack_copilot` | A |
| `POST /match` | `scan_type`, `clinical_history`, `findings[{id,text}]` (≤ 20, text ≤ 1000), `dictation`, `patient` | `cards[]`: `key`, `name`, `version`, `finding_id` (`"exam"` for exam cards), `siblings`, `reference`, `finding`, `needs_modality`, `publication`, `status`; `ms` | A |
| `POST /match/other` | as /match | as /match | A |
| `POST /open`, `POST /preview` | `card` (the `Card` echoed back, including `finding` and `needs_modality`), `finding` (an exam card sends the current dictation), `findings` (**equal to /match `dictation`**, R4), `clinical_history`, `answered`, `patient`; `lesion` (C) | `entry.name`, `entry.content.summary`, `entry.sources`; `preview.state`, `missing`, `proposal`, `exclusion`, `possible`, `bounded`, `asks`, `degraded`, `settled[].by` (A); `preview.draft[]`, `draft_outcome`, `waiting` (B1); `lesions`, `lesion` (C); `checker` (D); `highlight` (E); `reference`, `needs_modality`, `error` ∈ {`unavailable`, `loading`, `unknown guideline`} (A) | A–E |
| `POST /calculate` | `/open` fields + `values` (every value shown, display form) | `calculation.outcome`, `result`, `exclusion`, `possible`, `needed`, `values[]`, `trace`, `pack`, `bundle`; `checker` (D), `highlight` (E), `lesion` (C); `error` (`"not a pack"`) | B2 |
| `POST /api/canvas/stack/log` | `copilot` (keys, kinds, ms and counts only) | — | A |

**Invariants the UI relies on:**
1. A needs-modality card is never settled or previewed. `/open` returns `preview: null` with `needs_modality` set. The UI never calls it anyway.
2. A pack preview never carries an Apply-able proposal after Task 3. The UI shows any `proposal` or `draft_outcome` as read-only, so it is safe either way.
3. `/calculate` evaluates only the `values` sent.
4. `/match` is case-level: caps, one TNM card per site and exam merges apply over the whole request. The client therefore sends all stable findings each time.

**Contract requests to the backend** (gaps found while planning; each blocks or degrades the named slice):
- **R1 (Task 3, blocks B1's "set by the exam"):** `DraftValue.by: str = ""`, with `"exam"` when an exam preset filled the value, mirroring `Settled.by`. Without it, presets are indistinguishable from pre-fills once `draft` replaces `settled`.
- **R2 (any time, degrades A):**
- `Card.siblings` carries keys only. Add sibling display names, for example `sibling_names: list[str]` or siblings as `{key, name, version}`, so column headers paint before /open.
- `_prewarm` starts only primary cards' settlements, so a sibling column's first /open settles cold (up to `PREVIEW_TIMEOUT_S`). Prewarm siblings too.
- **R3 (any time, improves A's quiet line):** a pack-data flag for the normal outcomes behind the §5.3 quiet card, for example `Outcome.normal: bool`, surfaced as `Preview.normal`. Until then A3's interim rule applies (see Q2).
- **R4 (documentation only):** the /match `dictation` and the /open `findings` must be the same string for the prewarmed settlement to hit (`_prewarm` keys by `dictation`, `_pack_result` by `req.findings`). The UI sends `findingsText(units, groups)` to both. Note it in `routes.py`.

## Open questions for Hassan (UX only)

1. **How to turn the Copilot on.** Today the server allows it with the stack (`RR_STACK_COPILOT` defaults to "1").
 - *Recommendation:* the server flag plus a per-browser opt-in `rr_stack_copilot = "1"`, off by default, as A2 does. Add a Settings toggle once Slice B lands. Apply gets its own opt-in.
2. **The quiet line before R3.**
 - *Recommendation:* use the interim rule (an exam card fully settled, nothing pre-filled, nothing needed) and show the classification on the line, so a settled CAD-RADS 3 is also one line but says "CAD-RADS 3". Add R3 so "quiet" means "normal" as §5.3 says. The alternative is to show every exam card in full until R3.
3. **Do finding cards open automatically?**
 - *Recommendation:* no. Paint name and finding, and open on click: opening is cheap because it is prewarmed. Only exam cards auto-preview, because the quiet rule needs it.
4. **What counts as a finding being stable.** The brief says: unchanged across a grouping round, or the radiologist moves to the next finding.
 - *Recommendation:* also treat a stopped or paused recording as stable, so the last finding is matched without waiting for another sentence.
5. **Siblings in a 340 px rail.** Two columns of about 160 px are tight.
 - *Recommendation:* side-by-side columns with the outcome only, and a tap to expand one column to full width. Below 300 px, a two-segment switcher, neither preselected.
6. **Where post-generation cards come from.**
 - *Recommendation:* carry the scratchpad session's cards and answers to the report through the stack log or gate record (the report id is already linked). Reports with no scratchpad session keep today's `/enhance` pane only. The other option is a new report-side /match over the generated findings. Either needs a backend task.
7. **Ask on cards.** `/ask` exists but is not in this plan.
 - *Recommendation:* defer it until after Slice B2, and reuse the review rail's chat composer (`ChatThread.svelte`) so the two places stay one design.
8. **"Other guidelines" cards.**
 - *Recommendation:* label them "other", read-only, under their finding. Show "Not in the guideline library yet" when they cannot open, since web fetch is off.
9. **Rail width in the scratchpad.**
 - *Recommendation:* keep 340 px, the same as post-generation, collapsing to the strip below 1100 px. The scratchpad text column narrows instead.

### Critical Files for Implementation
- `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot/frontend/src/lib/review/rail/ReviewRail.svelte`
- `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot/frontend/src/lib/review/rail/GuidelinesPanel.svelte`
- `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot/frontend/src/lib/components/DictationScratchpad.svelte` (runGroup at about line 1520, layout at about line 2580)
- `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot/backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` and `types.py`
- `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot/frontend/src/routes/components/ReportResponseViewer.svelte` (rail mount at about lines 1274 and 1560)