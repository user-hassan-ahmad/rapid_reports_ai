# Findings-Triggered Template Rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A template can carry findings-triggered habits (a required statement, or a habit question answered Yes / No / Not assessed). They are proposed at creation from at least 2 example reports, confirmed on a Rules-step card, triggered in the scratchpad by one Jev call, ranked before the generic checklist rows within the existing caps, and written at Generate as the radiologist's answers.

**Architecture:** The grammar gets two findings-conditioned forms, allowed only inside a findings paragraph: `NEGATIVE "<s>" WHEN [findings: …]` (required statement) and `RULE WHEN [findings: …] ASK "<q>" YES "<s>" NO "<s>"` (habit question). The Rules-step ledger gets a fifth kind, `habit` (key `paragraph :: condition`, choice mode `ask | state | removed`), applied by code on every save; a habit line exists in a sheet only through a confirmed ledger entry. The decision run proposes habits with verified quotes; a card confirms them. In the scratchpad, the end-of-dictation review (`/items`, review mode) asks Jev one `noul` question per distinct condition in parallel with the row writer; met habit questions become `Item(kind="template")` rows ranked before generic finding rows inside `_limit`; met required statements come back as `required` and join the region's assumed normals. Generate needs no change: answers are "Answered by the radiologist:" statements and confirmed required statements are assumed lines.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pydantic-ai (`_run_agent_with_model`), Jev System One (`jev_client.jev_post`), pytest (asyncio auto); SvelteKit with Svelte 5 runes in `hybrid-stack/` and `template-rules/`, Svelte 4 syntax in `DictationScratchpad.svelte`; vitest (browser project for `*.svelte.test.ts`, node/server project for `*.test.ts`), svelte-check.

**Spec:** `docs/superpowers/specs/2026-10-13-findings-triggered-rows-design.md` (approved by Hassan, 2026-10-13). Roadmap item 5 in `docs/superpowers/specs/2026-10-13-template-rules-next-design.md`.

---

## Where and how

- Worktree: `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/triggered-rows`, branch `feat/triggered-rows`. It was cut from `feat/rules-step` at `ada8980e`; **Task 0 brings it up to the latest `feat/rules-step` after the controller has merged `feat/context-rules` into it.** Never push, never `git stash`, never touch another worktree.
- **Locating code.** Line numbers in this plan were read at `ada8980e` and are hints only. Every step locates code by function name and by the exact text it quotes ("replace … with …"); when a quoted anchor is not found after Task 0, find the same function by name, read it, and apply the same change to its current text.
- Backend commands run from `backend/`: one file `.venv/bin/python -m pytest <path> -q`. Full suite: `.venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py` (baseline about 4046 passed; the count must not fall).
- **Baselines after Task 0 (merge 65fa9008, 2026-10-13):** backend 4119 passed (`--deselect tests/test_provider_key_routing.py`); vitest 772 passed / 1 failed (the known `page.svelte.spec` h1 test) of 773; svelte-check 1193 errors, 194 warnings. They replace the counts below for every later check.
- Frontend commands run from `frontend/`: a node test `npx vitest run --project server <path>`; a component test `npx vitest run <path>`; full suite `npx vitest run`; `npm run check` (svelte-check baseline: 1194 problems; the count must not rise).
- Commit after every task with these trailer lines:

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit
```

- Lab data lives only in `~/Code/rr-template-conversion-private/synthetic/triggered_rows/`, never in the repo. Seeds: `~/Code/rr-template-conversion-private/data_all.json` (31 templates; `templates[i].reports`, `scan_type`) and `~/Code/rr-template-conversion-private/final/<slug>.final.md` (curated grammar sheets). Labs are reported, never gated: Hassan sets `TRIGGER_MIN` and `TRIGGER_WORDING` from the report. Labelling and judging are done by Claude subagents (Opus), never by the model under test. Eval economy: at most 2 runs, a runner skips any output file that already exists.

## Facts this plan relies on (checked at `ada8980e` on `feat/triggered-rows`)

- Lean template grammar: `template_sheet_grammar._mode_check` (`:601-624`) makes every findings-conditioned RULE except LIST_MISSING, and every conditioned template NEGATIVE, `NOT_LEAN`. Effects are parsed by `_EFFECTS` (`:191-202`); paragraph-only effects are `_PARAGRAPH_EFFECTS` (`:203`); a condition needs at least two content words (`condition`, `:448-457`, `_content_words`, `:262`), so "a fracture is reported" fails the subject rule while "a long bone fracture is reported" passes. Renderers `render_rule` / `render_negative` (`:783-804`).
- `template_sheet_structure.Rule` (`:101-113`) has no field for a question or a second sentence; `Effect` (`:97-98`); `STRUCTURE_VERSION = 2` (`:37`).
- Ledger: `template_decisions.KINDS` (`:38`), `validate` (`:168-213`), `match_key` (`:148-154`), `item_label` / `state_label` / `describe_change` (`:311-345`), `clean_ledger` (`:348-363`). Apply: `template_ledger_apply.apply_ledger` returns early on an empty ledger (`:363`); `_OPS` (`:356`); `observe` (`:407-437`); `reconcile_chat` / `_wholesale` (`:456-516`). Cards: `template_rules_cards.card_for_change` (`:134-145`), `build_cards` (`:251-262`), `_RANK` (`:26`).
- The save function `template_sheet_save.vet_sheet(sheet, origin, previous="", ledger=None)` skips the ledger entirely when `ledger is None` (`:224-227`); `template_writer.write_sheet` passes `ledger=decisions or None` (`template_writer.py:26`).
- Decision run: `template_decision_run.HabitCandidate(finding, habit, reports)` exists and is only stored as evidence (`:100-103`, `:253`, `:397`); prompt section 3 is `SYSTEM` (`:132`).
- Scratchpad rows: `hybrid_stack/items.py` — `Item` (`:89-97`), `_rows` (`:177-188`), `_split` (`:191-206`), `_dedupe` (`:209-221`), `_check` (`:224-247`), `_limit` (`:250-270`, caps `MAX_ROWS_PER_REGION = 2`, `MAX_ROWS = 4`), `update` (`:273-302`), `recheck` (`:305-315`). Jev: `jev_stack.ask_rows` (`:184-207`), `STATED_MIN = 0.8`, `CONDITION_MIN = 0.5`. Region names: `hybrid_stack/template.template_regions` (`:33-45`); conditioned negatives are never offered as normals (`_offered`, `:110`).
- Routes: `hybrid_stack/routes.stack_items` (`:181-186`) takes no template; `stack_assumed` caps 16 normals per region (`:254`). The route test fakes `items_update` positionally with no `habits` argument (`tests/test_hybrid_stack_routes.py:108`).
- Generate: `template_stack._strip` drops NORMAL / NEGATIVE / IF_PRESENT / case units but keeps RULE lines (`template_stack.py:20-50`). Generation never trusts a stale stored structure: `hybrid_stack/template.template_structure` uses `fresh()` (which requires `version == STRUCTURE_VERSION`) and otherwise re-parses the sheet; `template_pipeline.py` and `template_preview.py` call `parse_sheet` on the fly.
- Item 1's shared Jev state builder (on `feat/context-rules`, commit `f61451c9`, arrives with Task 0): `template_context_rules.condition_state(scan_type: str, history: str, findings: str) -> str` returns `"SCAN TYPE:\n<scan>\n"` (only when given) + `"CLINICAL HISTORY:\n<history or (not given)>\nDICTATED FINDINGS:\n<jev_findings(findings)>"`. Its callers: `resolve_context_rules` and `hybrid_stack/normals.assumed`. Task 6 adds one optional behaviour: `history=None` leaves the history block out.
- Frontend: `DictationScratchpad.svelte` — `gateKey` (`:365-367`), `gateReview` (`:1579-1600`) calls `refreshItems(true)`, `refreshItems` (`:1701-1730`), `skipRow` (`:1778-1782`), `refreshAssumed` (`:1812-1825`), `answerRow` (`:1859-1864`), `openItemsForVoice`, `viewItems` (`:324`), the `HybridStackView` props (`:2633-2640`). `regionState.buildFindingsBlock` (`regionState.ts:113-140`). `HybridStackView.svelte` — `rowsFor` / `looseRows` (`:195-199`) show `kind === 'finding'` only; the `row` snippet (`:585-660`).
- Rules-step frontend: `template-rules/types.ts` (`LedgerKind`, `CardKind`, `DecisionCard`), `cards.changeFor` returns a card choice's own `choice` unchanged, `RulesStep.svelte` card body (`:126-169`), button names `"{title}: {label}"`.
- Chat router (item 4) is an approved plan, not built: `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router/docs/superpowers/plans/2026-10-13-chat-edit-router.md`. Its names used in Phase 5: `chat_router_ledger` (`L.structure`, `L.entry`, `L.check`, `L.card`, `paragraph_entries`, `rekey_paragraph`, `Rejected`), `chat_router_changes` (`OUTPUTS`, `_VALIDATORS`, `validate`, `_gate`, `_ask`, `Verdict`, `Ctx`, `KIND_LABEL`, `claim_for`, `parse_change`), `chat_router_views.VIEWS`, `chat_router_calls._KIND` / `SYSTEM`, `chat_router_jev.KINDS` / `QUESTIONS`, `chat_router.WORK_KINDS`, `scripts/chat_router_lab.py`.

## Decisions this plan makes where the spec is open

1. **Habit choice shape:** `{"mode": "ask" | "state" | "removed", "question", "yes", "no"}`. `state` writes the NO sentence (the pertinent negative) as `NEGATIVE "<no>" WHEN [findings: <condition>]`; `ask` writes the RULE form; `removed` writes nothing and keeps the wording, so a later "ask" restores it.
2. **Conditions name the finding in at least two content words**, ending "is reported" (the grammar's subject rule). The spec's example "a fracture is reported" would fail the lint; prompts ask for e.g. "a fracture of the named structure is reported".
3. **Paragraph of a habit key:** the decision run runs before the sheet exists, so a key's paragraph is matched by paragraph name, else by the one paragraph whose COVERS lists it; otherwise the entry is `unmatched` and becomes a card at the next review (Rules-step rule).
4. **A habit is active only through the ledger (Hassan H3, 2026-10-13).** A habit line with no ledger entry (written by the writer or a whole-sheet chat rewrite) is never stripped silently: it stays in the sheet, inactive (the scratchpad triggers only habits with a confirmed `ask`/`state` entry; the stack brief never shows habit lines to the generator), and becomes a habit card at the next review ("When <condition>: Ask every time / Always state / Not needed", `/decide`). The save reports the pending ones (`LedgerResult.pending`, `VetOutcome.habits_pending`) and logs their count. A chat rewrite that removes a confirmed habit is kept and asked on a card (product decision D3, as for values and concepts).
5. **The trigger runs inside `/items` in review mode** (the `gateReview` hook calls `refreshItems(true)`), in parallel with the row writer, so `_limit` ranks template and generic rows together. The quiet re-check folds template rows but never re-triggers; a material change re-runs the review and so the trigger. No new endpoint.
6. **Already answered** reuses `_check`'s one Jev call: a template row folds when the dictation states either sentence (`STATED_MIN`); a contradiction never folds or edits a template row (both sentences stay as the buttons).
7. **Template rows never block Confirm** (like finding checks). "Not assessed" is a skip recorded as `not_assessed`. A voice "accept" never answers a template row (it cannot choose Yes or No).
8. **A tapped or skipped template row whose condition a successful full review no longer meets loses its answer** (spec: "until its condition stops being met"). A failed trigger call changes nothing on screen.
9. **Required statements join the assumed check** by being merged first into the region normals sent to `/assumed` (never cut by the 16-per-region cap), so they are covered / contradicted / removed exactly like assumed normals, then confirmed or removed in the tray.
10. **Trigger state (Hassan H1):** triggers read the dictation and the scan type only, never the clinical history: `condition_state(scan_type, None, findings)`, item 1's shared builder with `history=None` leaving the history block out. `scan_type` flows from `items.update` through `met_habits` and `ask_triggers`.
11. **Proposal verification:** a habit is kept only with verified quotes from at least 2 distinct reports, with its YES or NO sentence appearing in a cited report, and only if `td.validate` accepts it; duplicates (by `match_key`) merge; at most 4 per run. Habit cards rank with concept cards inside `MAX_CARDS`, are never pre-ticked, and have no "Edit wording" choice (chat changes wording).
12. **Two trigger wordings (A, B) are labbed**; `TRIGGER_MIN = 0.5` (the context-rule cut-off) until Hassan sets it from the report. **A score below `TRIGGER_MIN` is silent, even in the 0.35–0.5 band (Hassan H2);** the lab reports how often that band occurs and how often its rows were truly met.
12b. **Trigger question settled (2026-10-13).** Hedge round, `~/Code/rr-template-conversion-private/synthetic/triggered_rows/runs/hedge_round.json`: arm B1 (wording B plus criteria) at `TRIGGER_MIN` 0.5 gave P .97 / R 1.0 synthetic and P 1.0 / R 8/9 held out. Shipped as a criteria noul: instructions "The DICTATION reports this as present: {condition}. A finding the dictation negates, excludes or only raises as a question is not reported."; true "The dictation reports the finding as present."; false "The dictation does not report it: it negates or excludes it, or only raises it as a question; or the finding is only raised as possible, suspected, equivocal, or not excluded." (`hybrid_stack/habits.py` `TRIGGER_WORDING` and `TRIGGER_CRITERIA`). Habit conditions name where the finding is (proposal prompt; the habit card's Edit wording hints "Name where").
13. **A writer failure** returns no rows that round, as today (`res.error`: what is on screen stays), template rows included.
14. **Generate never sees a habit line, on either path (re-review, 2026-10-13).** Habits are resolved only in the scratchpad (asked rows, assumed statements). `template_lean.generate_template_report_lean` strips every `RULE … ASK …` and `NEGATIVE … WHEN [findings: …]` line from `gen_sheet`, right after the context-rule resolver prepares it, with or without `stack`. **Known limitation:** on the straight-dictation path (`stack=None`) nothing is asked, so a confirmed `state` habit is not written there in this release; nothing is written unasked.

## File map

Backend (`backend/src/rapid_reports_ai/`):

| File | Status | Responsibility |
|---|---|---|
| `template_sheet_structure.py` | modify | `Effect` gains `"ask"`; `Rule.question`, `Rule.else_text`; `STRUCTURE_VERSION = 3` |
| `template_sheet_grammar.py` | modify | ASK effect; habit forms lean only in a findings paragraph; `render_rule` renders ASK |
| `template_stack.py` | modify | the stack brief drops habit RULE lines (NEGATIVE lines already go) |
| `template_decisions.py` | modify | ledger kind `habit`: key, validation, labels |
| `template_ledger_apply.py` | modify | `_habit` apply, `confirmed_habits`, `pending_habits` (lines with no entry: inactive, asked on a card), `observe` habit, chat reconciliation |
| `template_sheet_save.py` | modify | `VetOutcome.habits_pending` on every save, ledger or not; logged |
| `main.py` | modify | `/skill-sheet/decide` shows pending habit cards and counts them in the run record |
| `template_rules_cards.py` | modify | `habit_card`, `card_for_change` habit, `pending_habit_cards`, habit cards in `build_cards` |
| `template_decision_run.py` | modify | habit proposal: prompt section, `HabitCandidate`, verification, evidence |
| `template_context_rules.py` | modify | item 1's `condition_state`: `history=None` leaves the history out |
| `hybrid_stack/template.py` | modify | `paragraph_regions` |
| `hybrid_stack/habits.py` | create | `Habit`, `template_habits`, trigger wordings, `ask_triggers`, `met_habits` |
| `hybrid_stack/items.py` | modify | `Item.yes/no`, template rows, ranking, folding, `update(habits=)` |
| `hybrid_stack/routes.py` | modify | `/items` reads the template's habits |
| `scripts/triggered_rows_lab.py` | create | proposal and trigger lab runners, scorers, tables |
| Phase 5 (router): `chat_router_ledger.py`, `chat_router_changes.py`, `chat_router_views.py`, `chat_router_calls.py`, `chat_router_jev.py`, `chat_router.py`, `scripts/chat_router_lab.py` | modify | the `habit` tag kind |

Tests (`backend/tests/`): `template_sheet_fixtures.py` (append `HABIT_SHEET`), `test_template_sheet_grammar.py`, `test_template_stack.py`, `test_template_decisions.py`, `test_template_ledger_apply.py`, `test_template_ledger_save.py`, `test_template_rules_cards.py`, `test_template_decision_run.py`, `test_hybrid_stack_habits.py` (create), `test_hybrid_stack_items.py`, `test_hybrid_stack_routes.py`, `test_triggered_rows_lab.py` (create), `test_chat_router_habit.py` (create, Phase 5), `test_chat_router_jev.py` (Phase 5).

Frontend (`frontend/src/lib/`):

| File | Status | Responsibility |
|---|---|---|
| `template-rules/types.ts` | modify | `habit` ledger and card kind, `DecisionCard.habit` |
| `template-rules/RulesStep.svelte` (+ test) | modify | the habit card body |
| `hybrid-stack/types.ts` | modify | `StackItem.kind` `'template'`, `yes`, `no`; `ItemsResult.required`, `trigger_error` |
| `hybrid-stack/api.ts` | modify | `postItems` sends `template_id` |
| `hybrid-stack/items.ts` (+ test) | modify | template rows count as unanswered checks |
| `hybrid-stack/templateRows.ts` (+ `templateRows.test.ts`) | create | `chooseTemplate`, `withChosen`, `withRequired`, `unmetTemplate`, `templateKey` |
| `hybrid-stack/regionState.ts` (+ test) | modify | a template answer is stated in its region |
| `hybrid-stack/HybridStackView.svelte` (+ test) | modify | template rows in region cards with Yes / No / Not assessed |
| `components/DictationScratchpad.svelte` | modify | wiring: template id, required statements, answers, gate key |

## Phases

| Phase | Tasks | Leaves working software |
|---|---|---|
| 0. Bring the branch up to date | 0 | the branch has `feat/context-rules` and the latest `feat/rules-step`; baselines recorded |
| 1. Grammar, renderer, ledger kind `habit` | 1–5, 5b | habit lines parse, render and save; only ledger-confirmed habits are active, others are asked on a card; nothing proposes or triggers them yet |
| 2. Labs (controller-run, reported) | 6–10 | trigger and proposal code exists and is measured; nothing in the scratchpad calls it; the decision run stores richer habit evidence |
| 3. Decision-run proposal and Rules-step card | 11–12 | habits are proposed and confirmed at creation; saved sheets carry them |
| 4. Scratchpad trigger, rows, ranking, Generate | 13–17 | confirmed habits are asked and stated in the scratchpad and reach the report |
| 5. Chat tag (**requires item 4 built**) | 18–20 | chat can add, change or remove a habit through the router, routed only after the habit-vs-normal lab report |

---

# Task 0: bring the branch up to date (before Task 1)

The controller first merges `feat/context-rules` into `feat/rules-step` (in the rules-step worktree, not here). Start this task only after it says so.

- [ ] **Step 1: Confirm the base is ready**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/triggered-rows
git status --short   # must be clean
git log --oneline -1 feat/rules-step
git merge-base --is-ancestor f61451c9 feat/rules-step && echo "context-rules is in rules-step"
```

Expected: a clean tree and the line `context-rules is in rules-step`. If that line is missing, stop and tell the controller.

- [ ] **Step 2: Merge** (a merge, not a rebase: the plan commit stays as it is)

```bash
git merge --no-edit feat/rules-step
```

Expected: a merge commit with no conflicts (this branch only adds the spec and this plan). If a conflict appears, stop and tell the controller.

- [ ] **Step 3: Re-check the facts.** Rules-step has since changed `template_decisions.py`, `template_rules_cards.py`, `template_sheet_grammar.py`, `template_writer.py`, `RulesStep.svelte` and `cards.ts`. Confirm every name this plan edits still exists:

```bash
cd backend/src/rapid_reports_ai
grep -n "^def condition_state\|^def jev_findings\|^def resolve_context_rules" template_context_rules.py
grep -n "^def _mode_check\|^def _parse_unit\|^_EFFECTS\|^_PARAGRAPH_EFFECTS\|^def render_rule\|^def render_negative" template_sheet_grammar.py
grep -n "^STRUCTURE_VERSION\|^Effect = \|^class Rule\b\|^class Rule(" template_sheet_structure.py
grep -n "^KINDS\|^def validate\|^def match_key\|^def item_label\|^def state_label\|^def negative_key" template_decisions.py
grep -n "^def apply_ledger\|^def observe\|^def reconcile_chat\|^def _wholesale\|^_OPS\|^def _normal\|^class LedgerResult" template_ledger_apply.py
grep -n "^_RANK\|^def card_for_change\|^def build_cards\|^def uncovered_card\|^def unmatched_cards" template_rules_cards.py
grep -n "^async def vet_sheet\|^def _with_ledger\|^class VetOutcome" template_sheet_save.py
grep -n "^class HabitCandidate\|^def check_quotes\|^def evidence\|^SYSTEM = " template_decision_run.py
grep -n "^class Item\|^class ItemsResult\|^def _split\|^def _dedupe\|^async def _check\|^def _limit\|^async def update\|^async def recheck" hybrid_stack/items.py
grep -n "^async def stack_items\|^class ItemsRequest" hybrid_stack/routes.py
grep -n "_vet_config\|unmatched_cards(cfg" main.py | head
cd ../../../frontend/src/lib
grep -n "export type LedgerKind\|export type CardKind\|export interface DecisionCard" template-rules/types.ts
grep -n "c.wording?.text" template-rules/RulesStep.svelte
grep -n "export function changeFor" template-rules/cards.ts
grep -n "function gateReview\|function refreshItems\|function skipRow\|function refreshAssumed\|function answerRow\|function openItemsForVoice\|\$: viewItems\|\$: gateKey" components/DictationScratchpad.svelte
```

Expected: every grep finds its names; `condition_state` has the signature `(scan_type: str, history: str, findings: str)`. A missing or renamed name: find its replacement by reading the module, note it in the commit message of the task that edits it, and edit by the current text.

- [ ] **Step 4: Record the new baselines**

```bash
cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py 2>&1 | tail -1
cd ../frontend && npx vitest run 2>&1 | tail -4 && npm run check 2>&1 | tail -2
```

Write the three numbers (backend passed, vitest passed/failed, svelte-check problems) at the top of the plan's "Where and how" section as "Baselines after Task 0: …", replacing the old ones for every later "must not fall / must not rise" check, and commit:

```bash
git add docs/superpowers/plans/2026-10-13-findings-triggered-rows.md
git commit -m "docs(plan): triggered rows baselines after merging rules-step and context-rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 1: grammar, renderer, ledger kind `habit`

### Task 1: The two habit forms parse, only inside a findings paragraph

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_structure.py`
- Modify: `backend/src/rapid_reports_ai/template_sheet_grammar.py`
- Test: `backend/tests/test_template_sheet_grammar.py`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_template_sheet_grammar.py`, after `test_v1_mode_keeps_the_full_grammar`)

```python
# ── findings-triggered habits (spec 2026-10-13-findings-triggered-rows-design) ──

HABIT_ASK = ('RULE WHEN [findings: a focal abnormality of the primary organ is reported] ASK "Extension beyond the organ?" '
             'YES "The abnormality extends beyond the organ." NO "No extension beyond the organ."')
HABIT_STATE = 'NEGATIVE "No extension beyond the organ." WHEN [findings: a focal abnormality of the primary organ is reported]'


@pytest.mark.parametrize("mode", ["template", "master"])
def test_habit_forms_are_lean_inside_a_findings_paragraph(mode):
    base = MASTER if mode == "master" else LEAN
    r = g.parse_sheet(in_paragraph(HABIT_ASK + "\n" + HABIT_STATE, base), mode=mode)
    assert r.errors == [] and r.structure.usable, r.errors
    (ask,) = [x for x in r.structure.rules if x.effect == "ask"]
    assert (ask.condition_source, ask.condition, ask.paragraph, ask.section) == (
        "findings", "a focal abnormality of the primary organ is reported", "p0", "FINDINGS")
    assert (ask.question, ask.then_text, ask.else_text) == (
        "Extension beyond the organ?", "The abnormality extends beyond the organ.", "No extension beyond the organ.")
    assert [(n.text, n.condition_source, n.paragraph) for n in r.structure.negatives if n.condition] == [
        ("No extension beyond the organ.", "findings", "p0")]


def test_habit_forms_outside_a_findings_paragraph_are_not_lean():
    in_measured = LEAN.replace("RULE WHEN [findings: any listed value is not stated] LIST_MISSING",
                               HABIT_STATE + "\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING")
    assert [e.reason for e in g.parse_sheet(in_measured).errors] == [g.NOT_LEAN]
    wide = 'FIXED "Images reviewed on a diagnostic workstation."\n'
    assert [e.reason for e in g.parse_sheet(LEAN.replace(wide, wide + HABIT_STATE + "\n")).errors] == [g.NOT_LEAN]
    assert [e.reason for e in g.parse_sheet(LEAN.replace(wide, wide + HABIT_ASK + "\n")).errors] == [g.MALFORMED_UNIT]


def test_ask_needs_a_findings_condition_and_a_question_mark():
    history = HABIT_ASK.replace("[findings:", "[history:")
    no_mark = HABIT_ASK.replace('"Extension beyond the organ?"', '"Extension beyond the organ"')
    for line in (history, no_mark):
        assert [e.reason for e in g.parse_sheet(in_paragraph(line)).errors] == [g.MALFORMED_UNIT], line
```

And in `NOT_LEAN_LINES` (same file, `:661-683`) delete this one line, which is now a lean required statement:

```python
    'NEGATIVE "No surrounding collection." WHEN [findings: an inflammatory process of the organ is reported]',
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_grammar.py -q -k "habit or ask_needs or not_lean"`
Expected: FAIL — `test_habit_forms_are_lean_inside_a_findings_paragraph` reports `NOT_LEAN` / `unknown effect 'ASK ...'`.

- [ ] **Step 3: Add the rule fields** (`template_sheet_structure.py`)

Replace:

```python
Effect = Literal["suppress", "replace", "append", "use", "insert_before", "suppress_paragraph_negatives",
                 "list_missing", "suppress_section", "suppress_headers", "order"]
```

with:

```python
Effect = Literal["suppress", "replace", "append", "use", "insert_before", "suppress_paragraph_negatives",
                 "list_missing", "suppress_section", "suppress_headers", "order", "ask"]
```

and in `class Rule`, after the `position` line, add:

```python
    question: SkipJsonSchema[str] = ""   # ask (a habit question): the question; then_text is its YES sentence
    else_text: SkipJsonSchema[str] = ""  # ask: the NO sentence
```

- [ ] **Step 4: Parse ASK and allow the two forms in a findings paragraph** (`template_sheet_grammar.py`)

In the module docstring, replace the "template" mode bullet (`:12-16`) with:

```python
- "template" (default; the save path): a stored template sheet in the LEAN grammar (spec
  2026-10-01-template-two-phase "Lean template sheet"). Findings- or history-conditioned RULEs (except
  LIST_MISSING, whose WHEN is the fixed findings statement, and the habit question ASK), NEGATIVE … WHEN
  [history|context: …], IF_PRESENT, context RULEs with an effect other than REPLACE/SUPPRESS/USE/SUPPRESS_SECTION/
  SUPPRESS_HEADERS, and every case unit are lint errors. Two findings-conditioned forms are allowed, only inside a
  findings-role paragraph (spec 2026-10-13-findings-triggered-rows-design): the required statement
  NEGATIVE "<s>" WHEN [findings: …] and the habit question RULE WHEN [findings: …] ASK "<q>" YES "<s>" NO "<s>".
  Every findings-role paragraph needs one COVERS.
```

and after the `RULE WHEN [<source>: <statement>] <EFFECT>` line of the unit list (`:31`) add:

```python
    RULE WHEN [findings: <statement>] ASK "<question>?" YES "<sentence>" NO "<sentence>"   (a paragraph only)
```

Append to `_EFFECTS` (after the `order` entry):

```python
    ("ask", re.compile(rf"ASK\s*{_Q}\s*YES\s*{_Q}\s*NO\s*{_Q}")),
```

Replace `_PARAGRAPH_EFFECTS = {"suppress_paragraph_negatives", "order"}  # meaningless outside a paragraph` with:

```python
_PARAGRAPH_EFFECTS = {"suppress_paragraph_negatives", "order", "ask"}  # meaningless outside a paragraph
```

In `_parse_unit`, after the block

```python
    if effect in _PARAGRAPH_EFFECTS and ctx.kind != "paragraph":
        err(i, MALFORMED_UNIT, f"{effect} outside a paragraph")
        return None
```

add:

```python
    if effect == "ask":
        if cond[0] != "findings":
            err(i, MALFORMED_UNIT, "ASK is conditioned on findings")
            return None
        if not e.group(1).rstrip().endswith("?"):
            err(i, MALFORMED_UNIT, 'ASK "<question>?": the question ends with "?"')
            return None
```

and in the effect chain, after `elif effect == "order": rule.update(position=e.group(1).lower())`, add:

```python
    elif effect == "ask":
        rule.update(question=e.group(1), then_text=e.group(2), else_text=e.group(3))
```

Replace the whole `_mode_check` function with:

```python
def _mode_check(i, unit, mode: str, role_of, err) -> None:
    """Template and master sheets carry the lean template grammar: study/context rules only, unconditional
    negatives only, no template IF_PRESENT (spec 2026-10-01-template-two-phase), except the two findings-triggered
    habit forms inside a findings-role paragraph (spec 2026-10-13-findings-triggered-rows-design). A case IF_PRESENT
    belongs to a findings-role paragraph."""
    kind, data = unit
    if kind == "if_present" and data["origin"] == "case" and role_of.get(data["section"]) != "findings":
        err(i, MALFORMED_UNIT, "a case IF_PRESENT belongs in a findings-role paragraph")
        return
    if mode == "v1":
        return
    if kind == "rule":
        src, effect = data["condition_source"], data["effect"]
        if effect == "list_missing":
            if src != "findings":
                err(i, NOT_LEAN, f"LIST_MISSING conditioned on {src}")
        elif effect == "ask":
            if role_of.get(data["section"]) != "findings":
                err(i, NOT_LEAN, "a habit question belongs in a findings paragraph")
        elif src != "context":
            err(i, NOT_LEAN, f"{src}-conditioned RULE (case-dependent: Phase 1 or voice prose)")
        elif effect not in CONTEXT_EFFECTS:
            err(i, NOT_LEAN, f"context RULE with {effect} (context rules: {', '.join(CONTEXT_EFFECTS)})")
    elif kind == "negative" and data["origin"] == "template" and data["condition"]:
        if not (data["condition_source"] == "findings" and data["paragraph"]
                and role_of.get(data["section"]) == "findings"):
            err(i, NOT_LEAN, f"NEGATIVE … WHEN [{data['condition_source']}: …] (a template negative is unconditional, "
                             "or a required statement WHEN [findings: …] inside a findings paragraph)")
    elif kind == "if_present" and data["origin"] == "template":
        err(i, NOT_LEAN, "IF_PRESENT without | origin: case (case-dependent: Phase 1)")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_grammar.py tests/test_template_structure_triggers.py -q`
Expected: PASS (the old suite plus 5 new tests; `test_save_path_parses_in_template_mode` still reports `NOT_LEAN` for a findings SUPPRESS).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_structure.py backend/src/rapid_reports_ai/template_sheet_grammar.py backend/tests/test_template_sheet_grammar.py
git commit -m "feat(grammar): habit question and required statement, lean only inside a findings paragraph

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 2: Renderer round trip, structure version, and the stack brief drops habit lines

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_grammar.py`
- Modify: `backend/src/rapid_reports_ai/template_sheet_structure.py`
- Modify: `backend/src/rapid_reports_ai/template_stack.py`
- Test: `backend/tests/test_template_sheet_grammar.py`, `backend/tests/test_template_stack.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_sheet_grammar.py`:

```python
def test_habit_forms_round_trip_and_bump_the_structure_version():
    s = g.parse_sheet(in_paragraph(HABIT_ASK + "\n" + HABIT_STATE)).structure
    (ask,) = [x for x in s.rules if x.effect == "ask"]
    (neg,) = [n for n in s.negatives if n.condition]
    assert g.render_rule(ask) == HABIT_ASK and g.render_negative(neg) == HABIT_STATE
    assert tss.STRUCTURE_VERSION == 3
    assert "question" not in tss.DraftRule.model_json_schema()["properties"]
    assert "else_text" not in tss.DraftRule.model_json_schema()["properties"]
```

(`tss` is already imported in this test file; if it is not, add `from rapid_reports_ai import template_sheet_structure as tss` at the top.)

Append to `backend/tests/test_template_stack.py`:

```python
def test_habit_lines_never_reach_the_generator():
    sheet = ('## Report Structure\nSECTION FINDINGS | header: "Findings:" | role: findings\n'
             'SECTION IMPRESSION | header: "Impression:" | role: impression\n\n'
             '## Paragraph: Upper (FINDINGS)\nCOVERS ["alpha"]\nNORMAL [alpha] "Alpha is normal."\n'
             'RULE WHEN [findings: an alpha abnormality is reported] ASK "Extension beyond alpha?" '
             'YES "The abnormality extends beyond alpha." NO "No extension beyond alpha."\n'
             '  - NEGATIVE "No beta extension." WHEN [findings: an alpha abnormality is reported]\n\n'
             '## Report-wide\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["Width"] AT TOP\n')
    b = stack_brief(sheet, "", [])
    assert "ASK" not in b and "No beta extension" not in b and "Extension beyond alpha" not in b
    assert "LIST_MISSING" in b and "COVERS [" in b
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_grammar.py tests/test_template_stack.py -q -k "round_trip_and_bump or habit_lines_never"`
Expected: FAIL with `KeyError: 'ask'` in `render_rule`, and `assert "ASK" not in b`.

- [ ] **Step 3: Render ASK, bump the version, strip habit RULE lines**

In `render_rule` (`template_sheet_grammar.py`), add to the effect table after the `"order"` entry:

```python
        "ask": lambda: f'ASK "{rule.question}" YES "{rule.then_text}" NO "{rule.else_text}"',
```

In `template_sheet_structure.py` replace

```python
STRUCTURE_VERSION = 2  # 2: lean template grammar + case units (spec 2026-10-01-template-two-phase)
```

with

```python
STRUCTURE_VERSION = 3  # 2: lean template grammar + case units; 3: findings-triggered habits (ASK, NEGATIVE … WHEN)
```

In `template_stack.py`, after the line `_CONTENT_UNIT = re.compile(rf"(?:{'|'.join(_CONTENT_UNITS)})\b")` add:

```python
# A habit question (spec 2026-10-13-findings-triggered-rows-design) is asked in the scratchpad, never by the generator:
# its answer reaches the FINDINGS input as "Answered by the radiologist". (Its required-statement twin is a NEGATIVE.)
_HABIT_RULE = re.compile(r"RULE\s+WHEN\s*\[\s*findings\s*:[^\]]*\]\s*ASK\b")
```

and in `_strip` replace

```python
        if _CONTENT_UNIT.match(body) or _INTERPRETIVE.match(body):
            continue
```

with

```python
        if _CONTENT_UNIT.match(body) or _INTERPRETIVE.match(body) or _HABIT_RULE.match(body):
            continue
```

The bump is safe for generation: it re-parses on the fly. `hybrid_stack/template.template_structure` takes a stored structure only through `fresh()`, which requires `version == STRUCTURE_VERSION`, and otherwise parses the sheet; `template_pipeline.py` and `template_preview.py` call `parse_sheet` directly. A stored version-2 structure is therefore never used once the version is 3.

- [ ] **Step 3b: Confirm no generation path reads a stored structure directly**

```bash
cd backend/src/rapid_reports_ai && grep -rn "_stored(\|fresh_any_source(\|\[\"structure\"\]\|get(\"structure\")" --include="*.py" . | grep -v "^./scripts/" | grep -v "template_sheet_structure.py"
```

Expected: no hit in a generation module (`template_pipeline.py`, `template_preview.py`, `template_stack.py`, `template_writer.py`, `hybrid_stack/`, the generate endpoints in `main.py`). A hit in a non-generation module (a lab, an admin view, a structuring queue) is fine; a hit in a generation module must go through `fresh()` instead, and is reported to the controller before going on.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_grammar.py tests/test_template_stack.py tests/test_template_generate_endpoint.py -q`
Expected: PASS (the generate-endpoint stamp tests read `STRUCTURE_VERSION`, so they follow the bump).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_grammar.py backend/src/rapid_reports_ai/template_sheet_structure.py backend/src/rapid_reports_ai/template_stack.py backend/tests/test_template_sheet_grammar.py backend/tests/test_template_stack.py
git commit -m "feat(grammar): render the habit question; structure version 3; the stack brief drops habit lines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 3: Ledger kind `habit`

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decisions.py`
- Test: `backend/tests/test_template_decisions.py`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_template_decisions.py`; add `import pytest` at the top if it is missing)

```python
# ── habit (spec 2026-10-13-findings-triggered-rows-design) ──
H = "Upper :: an alpha abnormality is reported"
HASK = {"mode": "ask", "question": "Extension beyond alpha?", "yes": "The abnormality extends beyond alpha.",
        "no": "No extension beyond alpha."}


def test_habit_is_a_ledger_kind_keyed_by_paragraph_and_condition():
    assert "habit" in td.KINDS and td.HABIT_MODES == ("ask", "state", "removed")
    assert td.habit_key(" Upper ", "an  alpha abnormality is reported") == H
    assert td.split_habit_key(H) == ("Upper", "an alpha abnormality is reported")
    assert td.match_key("habit", "upper ::  An alpha abnormality is REPORTED") == td.match_key("habit", H)
    with pytest.raises(td.DecisionError):
        td.split_habit_key("Upper")


def test_habit_choices_validate():
    assert td.validate("habit", H, HASK) == (H, HASK)
    assert td.validate("habit", H, {"mode": "state", "no": "No extension beyond alpha."})[1] == {
        "mode": "state", "question": "", "yes": "", "no": "No extension beyond alpha."}
    assert td.validate("habit", H, {"mode": "removed"})[1]["mode"] == "removed"
    for bad in ({**HASK, "mode": "maybe"}, {**HASK, "question": "Extension beyond alpha"}, {**HASK, "yes": HASK["no"]},
                {**HASK, "no": 'No "quoted" extension.'}, {"mode": "state"}, {**HASK, "yes": "Width {value} mm."},
                {**HASK, "question": ""}):
        with pytest.raises(td.DecisionError):
            td.validate("habit", H, bad)
    with pytest.raises(td.DecisionError):   # one content word: the grammar's subject rule would refuse it
        td.validate("habit", "Upper :: alpha is reported", HASK)


def test_habit_set_find_describe_and_clean():
    led, ch = td.set_decision([], "habit", H, HASK, source="creation", at="t")
    assert ch["old"] is None and td.find(led, "habit", "upper :: an alpha abnormality is reported")
    led, ch = td.set_decision(led, "habit", H, {**HASK, "mode": "state"}, source="chat", at="t2")
    assert td.describe_change(ch) == (
        'This changes something you confirmed: Upper: when an alpha abnormality is reported '
        'asked: "Extension beyond alpha?" → always stated: "No extension beyond alpha.".')
    assert td.state_label("habit", {**HASK, "mode": "removed"}) == "not used"
    assert td.clean_ledger(led) == led
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py -q -k habit`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.template_decisions' has no attribute 'HABIT_MODES'`.

- [ ] **Step 3: Implement the kind** (`template_decisions.py`)

In the module docstring table, after the `normal` row, add:

```python
    habit    habit_key(paragraph, condition)                 {"mode": "ask" | "state" | "removed", "question": str,
                                                              "yes": str, "no": str}

A habit (spec 2026-10-13-findings-triggered-rows-design) is written in its paragraph as RULE WHEN [findings: condition]
ASK "question" YES "yes" NO "no" (mode ask: the scratchpad asks it when the condition is met) or NEGATIVE "no" WHEN
[findings: condition] (mode state: a required statement); mode removed writes nothing and keeps the wording. A habit
is active only through its entry: a habit line with no entry stays inactive and is asked on a card at the next review
(template_ledger_apply.pending_habits).
```

Replace

```python
KINDS = ("value", "concept", "fixed", "normal")
```

with

```python
KINDS = ("value", "concept", "fixed", "normal", "habit")
HABIT_MODES = ("ask", "state", "removed")
MAX_QUESTION_WORDS = 15
```

After `negative_key` add:

```python
def habit_key(paragraph: str, condition: str) -> str:
    return f"{' '.join((paragraph or '').split())}{_SEP}{' '.join((condition or '').split())}"


def split_habit_key(key: str) -> Tuple[str, str]:
    """(paragraph, condition) of a habit key."""
    para, sep, cond = (key or "").partition(_SEP)
    if not sep or not para.strip() or not cond.strip():
        raise DecisionError(f"habit key {key!r}: '<paragraph> :: <condition>'")
    return " ".join(para.split()), " ".join(cond.split())
```

In `match_key`, before `if kind == "fixed":` add:

```python
    if kind == "habit":
        para, cond = split_habit_key(key)
        return f"{_name(para)}{_SEP}{_name(cond)}"
```

In `validate`, before the final `split_normal_key(key)` line add:

```python
    if kind == "habit":
        from .template_sheet_grammar import _content_words
        para, cond = split_habit_key(key)
        if any(c in cond for c in '"[]|{}') or len(_content_words(cond)) < 2:
            raise DecisionError(f"habit condition {cond!r}: name the finding in at least two words")
        mode = choice.get("mode")
        if mode not in HABIT_MODES:
            raise DecisionError(f"habit mode: one of {HABIT_MODES}")
        q = _text(choice.get("question", ""), "habit question", allow_slots=False)
        yes = _text(choice.get("yes", ""), "habit yes sentence", allow_slots=False)
        no = _text(choice.get("no", ""), "habit no sentence", allow_slots=False)
        if mode == "ask":
            if not (q and yes and no):
                raise DecisionError("habit ask: a question and both sentences")
            if not q.endswith("?") or len(q.split()) > MAX_QUESTION_WORDS:
                raise DecisionError("habit question: a short question ending with ?")
            if norm_key(yes) == norm_key(no):
                raise DecisionError("habit: the two sentences are the same")
        if mode == "state" and not no:
            raise DecisionError("habit state: the sentence to state")
        return habit_key(para, cond), {"mode": mode, "question": q, "yes": yes, "no": no}
```

In `item_label`, before `if kind == "normal":` add:

```python
    if kind == "habit":
        para, cond = split_habit_key(key)
        return f"{para}: when {cond}"
```

In `state_label`, before the final `return f'"{choice.get("text")}"' …` line add:

```python
    if kind == "habit":
        return {"ask": f'asked: "{choice.get("question")}"',
                "state": f'always stated: "{choice.get("no")}"'}.get(choice.get("mode"), "not used")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py tests/test_template_ledger_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decisions.py backend/tests/test_template_decisions.py
git commit -m "feat(ledger): habit kind keyed paragraph :: condition (ask / state / removed)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 4: Apply, observe and reconcile habits; habit lines the ledger does not hold are pending, never stripped

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py`
- Modify: `backend/src/rapid_reports_ai/template_rules_cards.py`
- Modify: `backend/tests/template_sheet_fixtures.py` (append)
- Test: `backend/tests/test_template_ledger_apply.py`, `backend/tests/test_template_rules_cards.py`

- [ ] **Step 1: Add the fixture** (append to `backend/tests/template_sheet_fixtures.py`)

```python
# LEDGER_SHEET with a second findings paragraph ("Lower", covering "delta"), so a habit can be placed by paragraph name
# or by a structure a paragraph covers.
HABIT_SHEET = LEDGER_SHEET.replace(
    "## Paragraph: Impression (IMPRESSION)",
    '## Paragraph: Lower (FINDINGS)\nCOVERS ["delta"]\nNORMAL [delta] "Delta is normal."\n\n'
    "## Paragraph: Impression (IMPRESSION)")
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_template_ledger_apply.py` (and add `HABIT_SHEET` to the fixtures import line):

```python
# ── habit (spec 2026-10-13-findings-triggered-rows-design) ──
HK = "Liver :: a focal liver abnormality is reported"
HASK = {"mode": "ask", "question": "Extension into the gallbladder?",
        "yes": "The abnormality extends into the gallbladder.", "no": "No extension into the gallbladder."}
ASK_LINE = ('RULE WHEN [findings: a focal liver abnormality is reported] ASK "Extension into the gallbladder?" '
            'YES "The abnormality extends into the gallbladder." NO "No extension into the gallbladder."')
STATE_LINE = 'NEGATIVE "No extension into the gallbladder." WHEN [findings: a focal liver abnormality is reported]'


def _liver(sheet):
    return sheet.split("## Paragraph: Liver (FINDINGS)")[1].split("## Paragraph: Lower")[0]


def test_habit_fixture_is_clean():
    _clean(HABIT_SHEET)


def test_a_habit_is_inserted_at_the_end_of_its_paragraph_and_read_back():
    res = tla.apply_ledger(HABIT_SHEET, _led(("habit", HK, HASK)))
    st = _clean(res.sheet)
    assert res.applied == [{"kind": "habit", "key": HK, "action": "inserted"}]
    assert _liver(res.sheet).rstrip().endswith(ASK_LINE)
    assert tla.observe(st, "habit", HK) == HASK
    again = tla.apply_ledger(res.sheet, _led(("habit", HK, HASK)))
    assert again.sheet == res.sheet and again.applied == [{"kind": "habit", "key": HK, "action": "kept"}]


def test_state_rewrites_the_question_and_removed_takes_it_out():
    asked = tla.apply_ledger(HABIT_SHEET, _led(("habit", HK, HASK))).sheet
    stated = tla.apply_ledger(asked, _led(("habit", HK, {**HASK, "mode": "state"})))
    assert stated.applied[0]["action"] == "rewritten" and STATE_LINE in stated.sheet and " ASK " not in stated.sheet
    assert tla.observe(_clean(stated.sheet), "habit", HK) == {
        "mode": "state", "question": "", "yes": "", "no": "No extension into the gallbladder."}
    gone = tla.apply_ledger(stated.sheet, _led(("habit", HK, {**HASK, "mode": "removed"})))
    assert gone.applied[0]["action"] == "removed" and "WHEN [findings: a focal" not in gone.sheet
    assert tla.observe(_clean(gone.sheet), "habit", HK)["mode"] == "removed"


def test_a_habit_finds_its_paragraph_by_a_covered_structure_else_it_is_unmatched():
    key = "delta :: a focal delta abnormality is reported"
    res = tla.apply_ledger(HABIT_SHEET, _led(("habit", key, {"mode": "state", "no": "No delta extension."})))
    lower = res.sheet.split("## Paragraph: Lower (FINDINGS)")[1]
    assert 'NEGATIVE "No delta extension." WHEN [findings: a focal delta abnormality is reported]' in lower
    miss = tla.apply_ledger(HABIT_SHEET, _led(("habit", "Nowhere :: a focal liver abnormality is reported", HASK)))
    assert miss.sheet == HABIT_SHEET and [e["key"] for e in miss.unmatched] == [
        "Nowhere :: a focal liver abnormality is reported"]


def test_a_habit_line_the_ledger_does_not_hold_stays_inactive_and_pending():
    # Hassan H3: never stripped silently; inactive until a card at the next review confirms it
    stray = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n',
                                'NEGATIVE "No focal liver lesion."\n' + STATE_LINE + "\n")
    st = _clean(stray)
    res = tla.apply_ledger(stray, [])
    assert res.sheet == stray and res.applied == []
    assert res.pending == [{"kind": "habit", "key": HK, "choice": {
        "mode": "state", "question": "", "yes": "", "no": "No extension into the gallbladder."}}]
    assert tla.confirmed_habits(st, []) == set()
    led = _led(("habit", HK, {**HASK, "mode": "state"}))
    confirmed = tla.apply_ledger(stray, led)
    assert confirmed.sheet == stray and confirmed.pending == []
    liver = next(p.id for p in st.paragraphs if p.name == "Liver")
    assert tla.confirmed_habits(st, led) == {(liver, "a focal liver abnormality is reported")}
    gone = tla.apply_ledger(stray, _led(("habit", HK, {**HASK, "mode": "removed"})))   # "Not needed" on its card
    assert STATE_LINE not in gone.sheet and gone.pending == []
    assert tla.confirmed_habits(_clean(gone.sheet), _led(("habit", HK, {**HASK, "mode": "removed"}))) == set()


def test_a_paragraph_negative_entry_never_reads_a_required_statement():
    sheet = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n',
                                'NEGATIVE "No focal liver lesion."\n'
                                'NEGATIVE "No focal liver lesion." WHEN [findings: a focal liver abnormality is reported]\n')
    st = _clean(sheet)
    key = td.negative_key("Liver", "No focal liver lesion.")
    assert tla.observe(st, "normal", key) == {"text": "No focal liver lesion."}
    no_plain = sheet.replace('NEGATIVE "No focal liver lesion."\nNEGATIVE', "NEGATIVE")
    assert tla.observe(_clean(no_plain), "normal", key) == {"text": ""}


def test_a_habit_the_grammar_refuses_is_not_saved_and_comes_back_as_a_card():
    key = "Technique :: a focal liver abnormality is reported"   # a technique paragraph: NOT_LEAN there
    res = tla.apply_ledger(HABIT_SHEET, _led(("habit", key, HASK)))
    assert res.sheet == HABIT_SHEET
    assert [e["key"] for e in res.failed] == [key] and [e["key"] for e in res.unmatched] == [key]


def test_a_chat_rewrite_that_drops_a_confirmed_habit_is_kept_and_asked():
    led = _led(("habit", HK, HASK))
    before = tla.apply_ledger(HABIT_SHEET, led).sheet
    after = before.replace(ASK_LINE + "\n", "").replace(ASK_LINE, "")
    out, changes, cards = tla.reconcile_chat(before, after, led)
    assert out == led and changes == [] and [c["kind"] for c in cards] == ["habit"]
    restated = before.replace(ASK_LINE, STATE_LINE)
    out, changes, cards = tla.reconcile_chat(before, restated, led)
    assert cards == [] and out[0]["choice"] == {**HASK, "mode": "state"} and out[0]["source"] == "chat"
```

Append to `backend/tests/test_template_rules_cards.py`:

```python
def test_card_for_change_makes_a_habit_card_never_preticked():
    c = trc.card_for_change("habit", "Upper :: an alpha abnormality is reported",
                            {"mode": "ask", "question": "Extension beyond alpha?",
                             "yes": "The abnormality extends beyond alpha.", "no": "No extension beyond alpha."})
    assert (c["kind"], c["ledger_kind"], c["selected"], c["step"]) == ("habit", "habit", None, "chat")
    assert c["title"] == "Upper: when an alpha abnormality is reported"
    assert [(x["id"], x["label"], x["choice"]["mode"]) for x in c["choices"]] == [
        ("ask", "Ask every time", "ask"), ("state", "Always state", "state"), ("removed", "Not needed", "removed")]
    assert c["habit"] == {"condition": "an alpha abnormality is reported", "question": "Extension beyond alpha?",
                          "yes": "The abnormality extends beyond alpha.", "no": "No extension beyond alpha."}
```

(`trc` is the existing alias in that file; if it is not, add `from rapid_reports_ai import template_rules_cards as trc`.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py tests/test_template_rules_cards.py -q -k "habit or required_statement or drops_a_confirmed"`
Expected: FAIL — `apply_ledger` leaves the sheet unchanged for a habit entry, `AttributeError: 'LedgerResult' object has no attribute 'pending'`, `card_for_change` raises for a habit.

- [ ] **Step 4: The habit card** (`template_rules_cards.py`)

Replace

```python
_RANK = {"disagree": 0, "value": 1, "concept": 2, "fixed": 3, "normal": 4, "uncovered": 5}
```

with

```python
_RANK = {"disagree": 0, "value": 1, "concept": 2, "habit": 2, "fixed": 3, "normal": 4, "uncovered": 5}
```

After `uncovered_card` add:

```python
def habit_card(paragraph: str, condition: str, question: str, yes: str, no: str, evidence: List[dict],
               step: str = "rules") -> dict:
    """A findings-triggered habit (spec 2026-10-13-findings-triggered-rows-design): "When <condition>: Ask every time
    / Always state / Not needed". Never pre-ticked: nothing is active until the radiologist confirms it. Every choice
    keeps the wording, so "Not needed" can be undone by choosing again."""
    key = td.habit_key(paragraph, condition)
    texts = {"question": question, "yes": yes, "no": no}
    return {"id": f"habit:{td.match_key('habit', key)}", "kind": "habit", "step": step,
            "title": f"{' '.join(paragraph.split())}: when {' '.join(condition.split())}", "evidence": evidence,
            "ledger_kind": "habit", "key": key, "habit": {"condition": " ".join(condition.split()), **texts},
            "choices": [_choice("ask", "Ask every time", {"mode": "ask", **texts}),
                        _choice("state", "Always state", {"mode": "state", **texts}),
                        _choice("removed", "Not needed", {"mode": "removed", **texts})],
            "selected": None, "rank": _RANK["habit"]}
```

In `card_for_change`, before `return normal_card(key, proposed.get("text", ""), step="chat")` add:

```python
    if kind == "habit":
        para, cond = td.split_habit_key(key)
        return habit_card(para, cond, proposed.get("question", ""), proposed.get("yes", ""), proposed.get("no", ""),
                          [], step="chat")
```

- [ ] **Step 5: Apply, pending, observe, reconcile** (`template_ledger_apply.py`)

In the module docstring, after the paragraph that starts "Where an entry's target cannot be found", add:

```python
A habit entry (kind "habit", spec 2026-10-13-findings-triggered-rows-design) is placed in the paragraph its key names,
or in the one paragraph whose COVERS lists that name; otherwise it is unmatched. A habit is active only through its
entry (confirmed_habits: the scratchpad triggers nothing else). A habit unit (RULE … ASK, NEGATIVE … WHEN [findings:
…]) with no entry, written by the writer or a whole-sheet rewrite, is never removed silently (Hassan H3, 2026-10-13):
it stays in the sheet, inactive, and is returned in `pending` (template_rules_cards.pending_habit_cards asks it at the
next review).
```

After `_normal` (before `_OPS`) add:

```python
def _habit_paragraph(st: tss.SheetStructure, name: str) -> Optional[tss.Paragraph]:
    """The paragraph a habit key names: by paragraph name, else the one paragraph whose COVERS lists it."""
    p = _paragraph(st, name)
    if p is not None:
        return p
    hits = [q for q in st.paragraphs if any(td._name(c) == td._name(name) for c in q.covers)]
    return hits[0] if len(hits) == 1 else None


def _habit_units(st: tss.SheetStructure, pid: str, cond: str) -> Tuple[List[tss.Rule], List[tss.Negative]]:
    k = td._name(cond)
    rules = [r for r in st.rules if r.effect == "ask" and r.paragraph == pid and td._name(r.condition) == k]
    negs = [n for n in st.negatives if n.paragraph == pid and n.origin == "template" and n.condition
            and n.condition_source == "findings" and td._name(n.condition) == k]
    return rules, negs


def habit_line(cond: str, choice: dict) -> Optional[str]:
    """The canonical line of a habit choice; None for "removed"."""
    if choice["mode"] == "ask":
        return tsg.render_rule(tss.Rule(id="ledger", section="", condition=cond, condition_source="findings",
                                        effect="ask", question=choice["question"], then_text=choice["yes"],
                                        else_text=choice["no"], source_lines=[]))
    if choice["mode"] == "state":
        return tsg.render_negative(tss.Negative(id="ledger", section="", text=choice["no"], condition=cond,
                                                condition_source="findings", source_lines=[]))
    return None


def _habit(lines, st, entry):
    para_name, cond = td.split_habit_key(entry["key"])
    row = {"kind": "habit", "key": entry["key"], "action": "kept"}
    para = _habit_paragraph(st, para_name)
    if para is None:
        return lines, [], [entry], []
    rules, negs = _habit_units(st, para.id, cond)
    idx: List[int] = []
    for raw in [r.source_lines[0] for r in rules] + [n.source_lines[0] for n in negs]:
        i = _index(lines, raw, set(idx))
        if i is not None:
            idx.append(i)
    new = habit_line(cond, entry["choice"])
    if not idx:
        if new is None:
            return lines, [row], [], []
        span = _paragraph_span(lines, para.id)
        if span is None:
            return lines, [], [entry], []
        at = _block_end(lines, *span)
        out = list(lines)
        out[at:at] = [new]
        return out, [{**row, "action": "inserted"}], [], []
    first = lines[idx[0]]
    if new is not None and len(idx) == 1 and first == _prefix(first) + new:
        return lines, [row], [], []
    out2: List[Optional[str]] = list(lines)
    for i in idx[1:]:
        out2[i] = None
    out2[idx[0]] = None if new is None else _prefix(first) + new
    return [x for x in out2 if x is not None], [{**row, "action": "removed" if new is None else "rewritten"}], [], []


def _habit_ids(st: tss.SheetStructure, ledger: List[dict], modes: Tuple[str, ...]) -> Set[Tuple[str, str]]:
    out: Set[Tuple[str, str]] = set()
    for e in ledger or []:
        if e.get("kind") != "habit" or (e.get("choice") or {}).get("mode") not in modes:
            continue
        try:
            para_name, cond = td.split_habit_key(e["key"])
        except td.DecisionError:
            continue
        p = _habit_paragraph(st, para_name)
        if p is not None:
            out.add((p.id, td._name(cond)))
    return out


def confirmed_habits(st: tss.SheetStructure, ledger: List[dict]) -> Set[Tuple[str, str]]:
    """(paragraph id, condition name) of every habit the ledger holds as "ask" or "state": the only active ones."""
    return _habit_ids(st, ledger, ("ask", "state"))


def pending_habits(st: tss.SheetStructure, ledger: List[dict]) -> List[dict]:
    """Habit units with no ledger entry at all, as entries {kind, key, choice} read from the sheet (module doc)."""
    decided = _habit_ids(st, ledger, td.HABIT_MODES)
    names = {p.id: p.name for p in st.paragraphs}
    out: List[dict] = []
    seen: Set[Tuple[str, str]] = set()
    units = [(r.paragraph, r.condition) for r in st.rules if r.effect == "ask"]
    units += [(n.paragraph, n.condition) for n in st.negatives
              if n.origin == "template" and n.condition and n.condition_source == "findings"]
    for pid, cond in units:
        k = (pid, td._name(cond))
        if k in decided or k in seen or pid not in names:
            continue
        seen.add(k)
        key = td.habit_key(names[pid], cond)
        out.append({"kind": "habit", "key": key, "choice": observe(st, "habit", key)})
    return out
```

Replace

```python
_OPS: List[Tuple[str, Callable]] = [("concept", _concept), ("fixed", _fixed), ("normal", _normal)]
```

with

```python
_OPS: List[Tuple[str, Callable]] = [("concept", _concept), ("fixed", _fixed), ("normal", _normal), ("habit", _habit)]
```

In `class LedgerResult`, after the `stale_quotes` field add:

```python
    pending: List[dict] = field(default_factory=list)    # habit lines with no entry: inactive, asked on a card
```

In `apply_ledger`, replace

```python
    res = LedgerResult(sheet=sheet)
    if not ledger or not tsg.is_grammar_sheet(sheet or ""):
        return res
```

with

```python
    res = LedgerResult(sheet=sheet)
    if not tsg.is_grammar_sheet(sheet or ""):
        return res
    ledger = list(ledger or [])
```

and at its end replace

```python
    res.stale_quotes = sorted({t for t in stale if t and any(f'"{t}"' in ln for ln in prose)})
    return res
```

with

```python
    res.stale_quotes = sorted({t for t in stale if t and any(f'"{t}"' in ln for ln in prose)})
    res.pending = pending_habits(_parse(res.sheet), ledger)
    if res.pending:
        logger.info("[ledger] habits_pending=%d (inactive until a card confirms them)", len(res.pending))
    return res
```

(With an empty ledger and no habit lines nothing is edited, so `test_empty_ledger_or_non_grammar_sheet_is_unchanged` still holds.)

In the same function's `except Exception as e:` branch, replace

```python
            res.failed += entries
            continue
```

with

```python
            res.failed += entries
            # spec failure table: a habit the grammar refuses is not saved and shows as a card at the next review
            res.unmatched += [x for x in entries if x.get("kind") == "habit"]
            continue
```

In `observe`, before the final `para_name, label, neg = td.split_normal_key(key)` line add:

```python
    if kind == "habit":
        para_name, cond = td.split_habit_key(key)
        para = _habit_paragraph(st, para_name)
        if para is None:
            return None
        rules, negs = _habit_units(st, para.id, cond)
        if rules:
            return {"mode": "ask", "question": rules[0].question, "yes": rules[0].then_text, "no": rules[0].else_text}
        if negs:
            return {"mode": "state", "question": "", "yes": "", "no": negs[0].text}
        return {"mode": "removed", "question": "", "yes": "", "no": ""}
```

and in the same function replace

```python
        u = next((n for n in st.negatives if n.paragraph == para.id and norm_key(n.text) == norm_key(label)), None)
```

with

```python
        u = next((n for n in st.negatives if n.paragraph == para.id and not n.condition
                  and norm_key(n.text) == norm_key(label)), None)
```

In `_wholesale`, before `return False` add:

```python
    if e["kind"] == "habit":
        return ob.get("mode") in ("ask", "state") and oa.get("mode") == "removed"
```

In `reconcile_chat`, replace

```python
            else:
                out, ch = td.set_decision(out, e["kind"], e["key"], oa, source="chat")
```

with

```python
            else:
                if e["kind"] == "habit":   # a sheet reading keeps the decided wording it cannot see
                    oa = {**e["choice"], **{k: v for k, v in oa.items() if v}}
                out, ch = td.set_decision(out, e["kind"], e["key"], oa, source="chat")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py tests/test_template_rules_cards.py tests/test_template_ledger_save.py tests/test_template_ledger_routes.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/src/rapid_reports_ai/template_rules_cards.py backend/tests/template_sheet_fixtures.py backend/tests/test_template_ledger_apply.py backend/tests/test_template_rules_cards.py
git commit -m "feat(ledger): apply, observe and reconcile habits; a habit line with no entry is pending, never stripped

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 5: Pending habits are reported on every save and asked at the next review; Phase 1 check

Hassan H3 (2026-10-13): a habit line with no confirmed ledger entry (from the writer or a whole-sheet chat edit) is never stripped silently. It stays in the sheet, inactive (Task 14 triggers only confirmed habits), every save reports and logs it, and the next review (`/skill-sheet/decide`) shows it as a habit card.

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_save.py` (`class VetOutcome`, `vet_sheet`, `_with_ledger`)
- Modify: `backend/src/rapid_reports_ai/template_rules_cards.py` (after `unmatched_cards`)
- Modify: `backend/src/rapid_reports_ai/main.py` (the `/api/templates/skill-sheet/decide` endpoint: the block that adds `trc.unmatched_cards(cfg.get("ledger_unmatched"))`, and the line `record = tdr.evidence(run, out)`)
- Test: `backend/tests/test_template_ledger_save.py`, `backend/tests/test_template_rules_cards.py`, `backend/tests/test_template_ledger_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_ledger_save.py`:

```python
async def test_habit_lines_nobody_confirmed_are_kept_inactive_and_reported():
    from tests.template_sheet_fixtures import HABIT_SHEET
    line = 'NEGATIVE "No extension into the gallbladder." WHEN [findings: a focal liver abnormality is reported]'
    stray = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n', 'NEGATIVE "No focal liver lesion."\n' + line + "\n")
    for ledger in (None, []):
        out = await S.vet_sheet(stray, origin="analyser", ledger=ledger)
        assert out.status == "saved" and line in out.sheet, ledger
        assert [e["key"] for e in out.habits_pending] == ["Liver :: a focal liver abnormality is reported"], ledger
    plain = await S.vet_sheet(HABIT_SHEET, origin="analyser")
    assert plain.sheet == HABIT_SHEET and plain.habits_pending == []
```

Append to `backend/tests/test_template_rules_cards.py`:

```python
def test_pending_habit_cards_ask_about_habit_lines_nobody_confirmed():
    from rapid_reports_ai import template_decisions as td
    from tests.template_sheet_fixtures import HABIT_SHEET
    ask = ('RULE WHEN [findings: a focal liver abnormality is reported] ASK "Extension into the gallbladder?" '
           'YES "The abnormality extends into the gallbladder." NO "No extension into the gallbladder."')
    state = 'NEGATIVE "No delta extension." WHEN [findings: a focal delta abnormality is reported]'
    sheet = (HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n', 'NEGATIVE "No focal liver lesion."\n' + ask + "\n")
             .replace('NORMAL [delta] "Delta is normal."\n', 'NORMAL [delta] "Delta is normal."\n' + state + "\n"))
    cards = trc.pending_habit_cards(sheet, [])
    assert [(c["kind"], c["key"], c["step"], c["note"], c["selected"]) for c in cards] == [
        ("habit", "Liver :: a focal liver abnormality is reported", "review", trc.PENDING_HABIT_NOTE, None),
        ("habit", "Lower :: a focal delta abnormality is reported", "review", trc.PENDING_HABIT_NOTE, None)]
    assert [x["id"] for x in cards[0]["choices"]] == ["ask", "state", "removed"]
    assert [x["id"] for x in cards[1]["choices"]] == ["state", "removed"]   # a required statement has no question
    led, _ = td.set_decision([], "habit", cards[0]["key"], cards[0]["choices"][0]["choice"], source="first_use_review")
    assert [c["key"] for c in trc.pending_habit_cards(sheet, led)] == [cards[1]["key"]]
    assert trc.pending_habit_cards("# Not a grammar sheet", []) == []
```

Append to `backend/tests/test_template_ledger_routes.py` (add `from rapid_reports_ai import template_rules_cards as trc` to its imports):

```python
def test_decide_asks_about_a_habit_line_nobody_confirmed(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    cfg = t["template_config"]
    line = 'NEGATIVE "No meniscal extrusion." WHEN [findings: a meniscal tear is reported]'
    r = _put(client, auth_headers, t, {**cfg, "skill_sheet": cfg["skill_sheet"].rstrip("\n") + "\n" + line + "\n"})
    assert r["success"], r
    assert line in _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"]   # kept, not stripped
    d = client.post("/api/templates/skill-sheet/decide", headers=auth_headers, json={"template_id": t["id"]}).json()
    (c,) = [c for c in d["cards"] if c["kind"] == "habit"]
    assert c["key"] == "Knee :: a meniscal tear is reported" and c["note"] == trc.PENDING_HABIT_NOTE
    assert c["selected"] is None and [x["id"] for x in c["choices"]] == ["state", "removed"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_save.py tests/test_template_rules_cards.py tests/test_template_ledger_routes.py -q -k "nobody_confirmed"`
Expected: FAIL with `AttributeError: 'VetOutcome' object has no attribute 'habits_pending'` and `… has no attribute 'pending_habit_cards'`.

- [ ] **Step 3: The save reports pending habits** (`template_sheet_save.py`)

In `class VetOutcome`, after the `stale_quotes` field add:

```python
    habits_pending: List[dict] = field(default_factory=list)    # habit lines with no ledger entry: inactive, asked
```

In `vet_sheet`, replace

```python
    out = await _vet(sheet, origin, previous)
    if ledger is None:
        return out
    return _with_ledger(out, origin, previous, list(ledger))
```

with

```python
    out = await _vet(sheet, origin, previous)
    if ledger is None:
        return _with_pending_habits(out)
    return _with_ledger(out, origin, previous, list(ledger))


def _with_pending_habits(out: VetOutcome) -> VetOutcome:
    """No ledger: the save is as before the Rules step; a habit line nobody confirmed is kept, inactive, and reported
    (Hassan H3, 2026-10-13: never stripped silently; the next review asks it on a card)."""
    from . import template_ledger_apply as tla
    if out.status == "refused" or not tsg.is_grammar_sheet(out.sheet or ""):
        return out
    pending = tla.pending_habits(tsg.parse_sheet(out.sheet, mode="template").structure, [])
    if pending:
        logger.info("[sheet-save] habits_pending=%d (inactive until a card confirms them)", len(pending))
    return dataclasses.replace(out, habits_pending=pending)
```

In `_with_ledger`, in its final `return dataclasses.replace(out, …)` call, replace `ledger_drift=drift, stale_quotes=res.stale_quotes)` with:

```python
                               ledger_drift=drift, stale_quotes=res.stale_quotes, habits_pending=res.pending)
```

(`apply_ledger` already logs `habits_pending=<n>` for the ledger path.)

- [ ] **Step 4: The review card** (`template_rules_cards.py`, after `unmatched_cards`)

```python
PENDING_HABIT_NOTE = "Your template has this habit, but it is not active until you choose."


def pending_habit_cards(sheet: str, ledger: List[dict]) -> List[dict]:
    """A review card for each habit line the ledger does not hold (written by the writer or a whole-sheet chat edit;
    Hassan H3): "When <condition>: Ask every time / Always state / Not needed", never pre-ticked. The habit stays
    inactive until a choice is recorded; "Not needed" removes its line at the next save. A required statement read
    from the sheet has no question, so it is offered "Always state" or "Not needed" only."""
    from . import template_ledger_apply as tla
    from . import template_sheet_grammar as tsg
    if not tsg.is_grammar_sheet(sheet or ""):
        return []
    out = []
    for e in tla.pending_habits(tsg.parse_sheet(sheet, mode="template").structure, ledger):
        para, cond = td.split_habit_key(e["key"])
        c = e["choice"]
        card = habit_card(para, cond, c["question"], c["yes"], c["no"], [], step="review")
        if not c["question"]:
            card["choices"] = [x for x in card["choices"] if x["id"] != "ask"]
        out.append({**card, "note": PENDING_HABIT_NOTE})
    return out
```

- [ ] **Step 5: `/decide` shows them** (`main.py`, the skill-sheet decide endpoint)

After the line

```python
            current += [c for c in trc.unmatched_cards(cfg.get("ledger_unmatched")) if c["id"] not in have_ids]
```

add

```python
            # habit lines nobody confirmed (the writer or a whole-sheet chat edit): inactive until a card answers them
            have_ids = {c["id"] for c in current}
            current += [c for c in trc.pending_habit_cards(cfg.get("skill_sheet") or "",
                                                           td.clean_ledger(cfg.get("decisions")))
                        if c["id"] not in have_ids]
```

and replace

```python
        record = tdr.evidence(run, out)
```

with

```python
        record = {**tdr.evidence(run, out),
                  "habits_pending": sum(1 for c in current if c.get("note") == trc.PENDING_HABIT_NOTE)}
```

- [ ] **Step 6: Run the Phase 1 suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_save.py tests/test_template_rules_cards.py tests/test_template_ledger_routes.py -q && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: PASS; the full suite count is the Task 0 baseline plus the new tests, with no failures.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_save.py backend/src/rapid_reports_ai/template_rules_cards.py backend/src/rapid_reports_ai/main.py backend/tests/test_template_ledger_save.py backend/tests/test_template_rules_cards.py backend/tests/test_template_ledger_routes.py
git commit -m "feat(rules-step): a habit line nobody confirmed stays inactive and is asked at the next review

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 5b: Generate never sees a habit line, on both paths

Habits are resolved only in the scratchpad, as asked rows or assumed statements. The straight-dictation Generate (`template_lean.generate_template_report_lean` with `stack=None`) reads the raw sheet, so without this task a habit line would reach the generator as text. Code strips every habit line from `gen_sheet` right after the context-rule resolver prepares it, on both paths (on the scratchpad path `template_stack._strip` drops them too; stripping twice is harmless). **Known limitation:** on the straight path nothing is asked, so a confirmed `state` habit is not written there in this release (nothing is written unasked).

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_context_rules.py` (after `jev_findings`)
- Modify: `backend/src/rapid_reports_ai/template_lean.py` (`generate_template_report_lean`, its inner `gen()`, the line that builds `gen_sheet`)
- Test: `backend/tests/test_template_context_rules.py`, `backend/tests/test_template_lean.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_context_rules.py` (`tcr` is the module alias there; if it is not, add `from rapid_reports_ai import template_context_rules as tcr`):

```python
def test_without_habits_drops_both_habit_forms_and_nothing_else():
    sheet = "\n".join([
        "## Paragraph: Upper (FINDINGS)",
        'NEGATIVE "No beta abnormality."',
        'RULE WHEN [findings: an alpha abnormality is reported] ASK "Extension?" YES "It extends." NO "No extension."',
        '  - NEGATIVE "No extension beyond alpha." WHEN [findings: an alpha abnormality is reported]',
        'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["Width"] AT TOP',
        'RULE WHEN [context: a previous study is available] SUPPRESS "No beta abnormality."',
        "Voice: when present, say ASK nothing."])
    out, n = tcr.without_habits(sheet)
    assert n == 2 and "ASK \"" not in out and "WHEN [findings: an alpha" not in out
    assert out.split("\n") == [sheet.split("\n")[i] for i in (0, 1, 4, 5, 6)]
    assert tcr.without_habits("") == ("", 0)
```

Append to `backend/tests/test_template_lean.py` (add `import pytest` to its imports if missing):

```python
@pytest.mark.parametrize("stack", [None, {"conclusion": "Lesion.", "declined": []}])
async def test_no_habit_line_reaches_the_generator_pending_or_confirmed(monkeypatch, stack):
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_ledger_apply as tla
    from tests.template_sheet_fixtures import HABIT_SHEET
    ask = {"mode": "ask", "question": "Extension into the gallbladder?",
           "yes": "The abnormality extends into the gallbladder.", "no": "No extension into the gallbladder."}
    led, _ = td.set_decision([], "habit", "Liver :: a focal liver abnormality is reported", ask, source="creation", at="t")
    confirmed = tla.apply_ledger(HABIT_SHEET, led).sheet
    pending = 'NEGATIVE "No delta extension." WHEN [findings: a focal delta abnormality is reported]'
    sheet = confirmed.replace('NORMAL [delta] "Delta is normal."\n', 'NORMAL [delta] "Delta is normal."\n' + pending + "\n")
    assert " ASK " in sheet and pending in sheet
    calls = {}
    _gen_fakes(monkeypatch, calls)
    out = await tl.generate_template_report_lean(sheet=sheet, scan_type="CT", findings="A focal liver abnormality.",
                                                 history="", case=CASE, signature="Dr A", stack=stack)
    gen_sheet = calls["gen"]["sheet"]
    assert " ASK " not in gen_sheet and "WHEN [findings: a focal" not in gen_sheet
    assert 'NEGATIVE "No focal liver lesion."' in gen_sheet   # unconditional units are untouched
    assert out["report_generated"] == REPORT
    if out.get("options_job") is not None:
        await out["options_job"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_context_rules.py tests/test_template_lean.py -q -k "habit"`
Expected: FAIL with `AttributeError: module … has no attribute 'without_habits'` and, for both `stack` values, `assert " ASK " not in gen_sheet`.

- [ ] **Step 3: The strip** (`template_context_rules.py`, after `jev_findings`)

```python
# The two findings-triggered habit forms (spec 2026-10-13-findings-triggered-rows-design), with the grammar's optional
# indentation and "- " bullet. Habits are resolved only in the scratchpad (asked rows, assumed statements): the
# generator never reads one, on either Generate path.
_HABIT_LINE = re.compile(r'^\s*(?:-\s+)?(?:RULE\s+WHEN\s*\[\s*findings\s*:[^\]]*\]\s*ASK\b'
                         r'|NEGATIVE\s*"[^"]*"\s+WHEN\s*\[\s*findings\s*:)')


def without_habits(sheet: str) -> Tuple[str, int]:
    """(the sheet without its habit lines, how many were removed). Every other line is kept byte for byte."""
    lines = (sheet or "").split("\n")
    kept = [ln for ln in lines if not _HABIT_LINE.match(ln)]
    return "\n".join(kept), len(lines) - len(kept)
```

(`re` and `Tuple` are already imported in the module.)

- [ ] **Step 4: Use it where `gen_sheet` is prepared** (`template_lean.py`)

Add `without_habits` to the existing `from .template_context_rules import …` line. In `gen()` replace

```python
        gen_sheet = resolved.sheet + ("\n\n" + block if block else "")
```

with

```python
        # habits are resolved only in the scratchpad; on the straight path nothing is asked, so nothing is written
        # (a confirmed "state" habit is not written there in this release: findings-triggered rows plan, decision 14)
        base, rec["habit_lines_stripped"] = without_habits(resolved.sheet)
        gen_sheet = base + ("\n\n" + block if block else "")
```

- [ ] **Step 5: Confirm no other generation path reads the sheet raw**

```bash
cd backend/src/rapid_reports_ai && grep -rn "_generate_report_skill_sheet_guided(\|generate_template_report(\|generate_template_report_lean(" --include="*.py" . | grep -v "^./scripts/"
```

Expected hits: `template_lean.py` (fixed above), `template_manager.py` (the method's definition and its skill-sheet early exit in the generic `generate_report`), `template_pipeline.py` (the heavy mirror, parked: `main.py` says "The heavy mirror (tp.generate_template_report) is parked"), and the `main.py` call of `generate_template_report_lean`. For every hit other than `template_lean.py`, follow its callers (`grep -n "<function name>(" main.py hybrid_stack/*.py template_*.py`) and confirm no live endpoint reaches it with a guided template. If one does, pass its sheet through `without_habits(...)[0]` in the same way, add the same parametrised test for that path, and say so in the commit message.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_context_rules.py tests/test_template_lean.py tests/test_template_stack.py tests/test_template_generate_endpoint.py -q`
Expected: PASS (`test_lean_generation_is_todays_generator_then_check_then_vetted_options` still sees `OLD_SHEET` unchanged: it has no habit line).

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/template_context_rules.py backend/src/rapid_reports_ai/template_lean.py backend/tests/test_template_context_rules.py backend/tests/test_template_lean.py
git commit -m "feat(generate): no habit line reaches the generator, scratchpad or straight dictation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 2: labs (controller-run, reported before any scratchpad wiring)

The trigger code and the proposal code are written first (pure, tested, not yet called by the scratchpad or shown as cards), so the labs measure the code that ships. The labs run on Opus-generated synthetic data in the private folder, with real production dictations as a separate held-out set. Nothing here is a gate: the controller writes the report, and Hassan sets `TRIGGER_MIN` and `TRIGGER_WORDING`.

### Task 6: `condition_state` without history, region names, and the trigger module

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_context_rules.py` (`condition_state`, from item 1)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/template.py` (after `template_regions`)
- Create: `backend/src/rapid_reports_ai/hybrid_stack/habits.py`
- Test: `backend/tests/test_hybrid_stack_habits.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_hybrid_stack_habits.py`)

```python
"""Findings-triggered habits in the scratchpad (spec 2026-10-13-findings-triggered-rows-design): read from the
template, triggered by one Jev call."""
import json

import httpx
import pytest

from rapid_reports_ai import template_context_rules as tcr
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai.hybrid_stack import habits as H
from rapid_reports_ai.hybrid_stack.template import paragraph_regions, template_regions
from tests.template_sheet_fixtures import HABIT_SHEET
from tests.test_template_sheet_lab_prompts import CLINICAL

ASK_LINE = ('RULE WHEN [findings: a focal liver abnormality is reported] ASK "Extension into the gallbladder?" '
            'YES "The abnormality extends into the gallbladder." NO "No extension into the gallbladder."')
STATE_LINE = 'NEGATIVE "No delta extension." WHEN [findings: a focal delta abnormality is reported]'
SHEET = (HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n', 'NEGATIVE "No focal liver lesion."\n' + ASK_LINE + "\n")
         .replace('NORMAL [delta] "Delta is normal."\n', 'NORMAL [delta] "Delta is normal."\n' + STATE_LINE + "\n"))


def _st():
    r = tsg.parse_sheet(SHEET)
    assert not r.errors and r.structure.usable, r.errors
    return r.structure


def test_paragraph_regions_name_paragraphs_as_template_regions_does():
    st = _st()
    assert list(paragraph_regions(st).values()) == [r.name for r in template_regions(st)][:-1] == ["Liver", "Lower"]


def test_template_habits_reads_both_forms_under_their_region_names():
    hs = H.template_habits(_st())   # no ledger: every habit in the sheet (the labs' hand-written sheets)
    assert [(h.region, h.mode, h.condition) for h in hs] == [
        ("Liver", "ask", "a focal liver abnormality is reported"), ("Lower", "state", "a focal delta abnormality is reported")]
    assert (hs[0].question, hs[0].yes, hs[0].no) == (
        "Extension into the gallbladder?", "The abnormality extends into the gallbladder.", "No extension into the gallbladder.")
    assert hs[1].no == "No delta extension."


def test_with_a_ledger_only_confirmed_habits_are_active():
    st = _st()
    assert H.template_habits(st, []) == []   # Hassan H3: a line nobody confirmed is inactive
    led, _ = td.set_decision([], "habit", "Lower :: a focal delta abnormality is reported",
                             {"mode": "state", "no": "No delta extension."}, source="creation", at="t")
    assert [h.region for h in H.template_habits(st, led)] == ["Lower"]
    led, _ = td.set_decision(led, "habit", "Lower :: a focal delta abnormality is reported", {"mode": "removed"},
                             source="chat", at="t2")
    assert H.template_habits(st, led) == []


def test_condition_state_leaves_the_history_out_when_none():
    # item 1's shared builder; Hassan H1: a trigger reads the dictation and the scan type only
    assert tcr.condition_state("MR knee", None, "Liver: x.") == "SCAN TYPE:\nMR knee\nDICTATED FINDINGS:\nLiver: x."
    assert tcr.condition_state("MR knee", "Pain.", "Liver: x.") == (
        "SCAN TYPE:\nMR knee\nCLINICAL HISTORY:\nPain.\nDICTATED FINDINGS:\nLiver: x.")
    assert tcr.condition_state("", "", "Liver: x.") == "CLINICAL HISTORY:\n(not given)\nDICTATED FINDINGS:\nLiver: x."
    assert tcr.condition_state("MR knee", None, "Liver: x.\nDO NOT ASSERT (removed by the radiologist): y.") == (
        "SCAN TYPE:\nMR knee\nDICTATED FINDINGS:\nLiver: x.")


async def test_ask_triggers_asks_every_condition_in_one_call_on_the_scan_type_and_findings_only():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.9 if k == "t0" else 0.1} for k in body["questions"]}})
    conds = ["a focal liver abnormality is reported", "a focal delta abnormality is reported"]
    out = await H.ask_triggers("MR knee", "Liver: a focal abnormality.", conds, transport=httpx.MockTransport(handler))
    assert out == [0.9, 0.1] and len(seen) == 1
    assert seen[0]["state"] == "SCAN TYPE:\nMR knee\nDICTATED FINDINGS:\nLiver: a focal abnormality."
    assert "CLINICAL HISTORY" not in seen[0]["state"]
    q = seen[0]["questions"]["t0"]
    assert q["type"] == "noul" and q["instructions"] == H.TRIGGER_WORDING.format(condition=conds[0])
    b = H.TRIGGER_WORDINGS["A"]
    await H.ask_triggers("MR knee", "x", conds[:1], transport=httpx.MockTransport(handler), wording=b)
    assert seen[1]["questions"]["t0"]["instructions"] == b.format(condition=conds[0])


async def test_ask_triggers_raises_on_incomplete_answers():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"answers": {}}))
    with pytest.raises(ValueError):
        await H.ask_triggers("MR knee", "x", ["a focal liver abnormality is reported"], transport=t)


async def test_met_habits_uses_the_cut_off_and_fails_soft():
    hs = H.template_habits(_st())

    seen = []

    async def ask(scan_type, findings, conds):
        seen.append(scan_type)
        return [H.TRIGGER_MIN, H.TRIGGER_MIN - 0.01]   # Hassan H2: just below the cut-off stays silent
    met, err = await H.met_habits(hs, "MR knee", "x", ask=ask)
    assert [h.mode for h in met] == ["ask"] and err is None and seen == ["MR knee"]

    async def band(scan_type, findings, conds):
        return [0.49, 0.36]
    assert await H.met_habits(hs, "MR knee", "x", ask=band) == ([], None)

    async def boom(scan_type, findings, conds):
        raise RuntimeError("jev down")
    assert await H.met_habits(hs, "MR knee", "x", ask=boom) == ([], "RuntimeError: jev down")
    assert await H.met_habits(hs, "MR knee", "   ", ask=ask) == ([], None)
    assert await H.met_habits([], "MR knee", "x", ask=ask) == ([], None)


def test_trigger_wordings_are_case_agnostic_and_the_cut_off_is_the_context_rules_one():
    for w in H.TRIGGER_WORDINGS.values():
        assert "{condition}" in w
        for word in CLINICAL:
            assert word not in w.lower(), word
    assert H.TRIGGER_WORDING in H.TRIGGER_WORDINGS.values() and H.TRIGGER_MIN == 0.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_habits.py -q`
Expected: FAIL with `ImportError: cannot import name 'paragraph_regions'`.

- [ ] **Step 3: `history=None` in item 1's `condition_state`** (`template_context_rules.py`)

Do not add a new function: item 1's shared builder is reused (Hassan H1: a trigger reads the dictation and the scan type only). Replace the whole of `condition_state` with:

```python
def condition_state(scan_type: str, history: Optional[str], findings: str) -> str:
    """The one Jev state every condition is asked on (resolve_context_rules, the checklist's template suppressions and
    the findings-triggered habits): the scan type when given, the clinical history, and the dictated findings without
    what the radiologist did not dictate (jev_findings). history None leaves the history block out: a habit trigger
    reads the dictation and the scan type only (Hassan H1, 2026-10-13)."""
    head = f"SCAN TYPE:\n{scan_type}\n" if (scan_type or "").strip() else ""
    hist = "" if history is None else f"CLINICAL HISTORY:\n{history or '(not given)'}\n"
    return head + hist + f"DICTATED FINDINGS:\n{jev_findings(findings)}"
```

Its two existing callers must keep their state byte for byte even if they are ever handed `None`: in `resolve_context_rules` change the call to `condition_state(scan_type, history or "", findings)`, and in `hybrid_stack/normals.assumed` to `condition_state(scan_type, clinical_history or "", dictation)`. If `Optional` is not imported in the module, add it to the `typing` import.

- [ ] **Step 4: `paragraph_regions`** (`hybrid_stack/template.py`, after `template_regions`)

```python
def paragraph_regions(st: SheetStructure) -> dict[str, str]:
    """Findings paragraph id -> its region name, exactly as template_regions names it (the region a habit row sits
    in and its required statement joins)."""
    order = {sec.name: sec.order for sec in st.sections}
    findings = {sec.name for sec in st.sections if sec.role == "findings"}
    paras = sorted((p for p in st.paragraphs if p.section in findings), key=lambda p: order.get(p.section, 0))
    out: dict[str, str] = {}
    seen: set[str] = set()
    for p in paras:
        name = p.name if p.name.lower() not in seen else f"{p.name} ({p.section.title()})"
        seen.add(name.lower())
        out[p.id] = name
    return out
```

- [ ] **Step 5: The trigger module** (`hybrid_stack/habits.py`)

```python
"""Findings-triggered habits in the scratchpad (spec 2026-10-13-findings-triggered-rows-design).

A template's confirmed habits are read from its grammar structure: a habit question (RULE WHEN [findings: …] ASK) and a
required statement (NEGATIVE … WHEN [findings: …]), each in a findings paragraph, active only with a confirmed ledger
entry (Hassan H3). At the end-of-dictation review one Jev call asks one noul question per distinct condition, on the
scan type and the dictated findings only, never the clinical history (Hassan H1); a score below TRIGGER_MIN is silent
(Hassan H2). Jev decides; items.py turns the met questions into rows and the met statements into the assumed tray;
code applies. Fail-soft: a failed call gives no template rows (the generic rows are as today), logged."""
from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel

from ..jev_client import JEV_MODEL, jev_post
from ..template_sheet_structure import SheetStructure
from .template import paragraph_regions

logger = logging.getLogger(__name__)

TIMEOUT_S = 3.0
TRIGGER_MIN = 0.5   # = jev_stack.CONDITION_MIN until the trigger lab reports (Hassan sets it)
# Two wordings labbed (scripts/triggered_rows_lab.py); B names what does not count. Case-agnostic.
TRIGGER_WORDINGS = {
    "A": "The DICTATION reports this: {condition}.",
    "B": ("The DICTATION reports this as present: {condition}. A finding the dictation negates, excludes or only raises "
          "as a question is not reported."),
}
TRIGGER_WORDING = TRIGGER_WORDINGS["B"]


class Habit(BaseModel):
    region: str                       # the paragraph-region it belongs to (template_regions' name)
    condition: str                    # the findings condition, as the sheet writes it
    mode: Literal["ask", "state"]
    question: str = ""                # ask: the template's question
    yes: str = ""                     # ask: the sentence a Yes writes
    no: str = ""                      # ask: the sentence a No writes; state: the required statement


def template_habits(st: SheetStructure, ledger: Optional[list[dict]] = None) -> list[Habit]:
    """The sheet's habits in sheet order, questions first, under their region names. With a ledger (every production
    caller), only habits it holds as "ask" or "state" are returned: a line nobody confirmed is inactive (Hassan H3).
    None (the labs' hand-written sheets): every habit in the sheet."""
    from ..template_decisions import _name
    from ..template_ledger_apply import confirmed_habits
    names = paragraph_regions(st)
    ok = None if ledger is None else confirmed_habits(st, ledger)

    def active(pid: str, cond: str) -> bool:
        return pid in names and (ok is None or (pid, _name(cond)) in ok)
    out = [Habit(region=names[r.paragraph], condition=r.condition, mode="ask", question=r.question,
                 yes=r.then_text, no=r.else_text)
           for r in st.rules if r.effect == "ask" and r.condition_source == "findings" and active(r.paragraph, r.condition)]
    out += [Habit(region=names[n.paragraph], condition=n.condition, mode="state", no=n.text)
            for n in st.negatives if n.origin == "template" and n.condition and n.condition_source == "findings"
            and active(n.paragraph, n.condition)]
    return out


def trigger_question(condition: str, wording: str = TRIGGER_WORDING) -> dict:
    return {"type": "noul", "instructions": wording.format(condition=" ".join(condition.split()).rstrip("."))}


async def ask_triggers(scan_type: str, findings: str, conditions: list[str], transport=None,
                       wording: str = TRIGGER_WORDING) -> list[float]:
    """P(the dictation reports it) per condition, in order, in one Jev call on the scan type and the dictated findings
    (item 1's condition_state with no history). Raises on any failure."""
    from ..template_context_rules import condition_state
    if not conditions:
        return []
    qs = {f"t{i}": trigger_question(c, wording) for i, c in enumerate(conditions)}
    r = await jev_post({"model": JEV_MODEL, "state": condition_state(scan_type, None, findings), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out = []
    for i in range(len(conditions)):
        v = (ans.get(f"t{i}") or {}).get("noul")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("jev: incomplete answers")
        out.append(float(v))
    return out


Ask = Callable[[str, str, list[str]], Awaitable[list[float]]]


async def met_habits(habits: list[Habit], scan_type: str, findings: str,
                     ask: Optional[Ask] = None) -> tuple[list[Habit], Optional[str]]:
    """(the habits whose condition the dictation meets, error). A score below TRIGGER_MIN is not met, however close
    (Hassan H2). Never raises: a failed call meets nothing."""
    if not habits or not (findings or "").strip():
        return [], None
    conds = list(dict.fromkeys(h.condition for h in habits))
    try:
        scores = await (ask or ask_triggers)(scan_type, findings, conds)
        if len(scores) != len(conds):
            raise ValueError("jev: answer count mismatch")
    except Exception as e:  # noqa: BLE001 -- fail-soft: no template rows, generic rows as today
        err = f"{type(e).__name__}: {e}"[:200]
        logger.warning("[stack.habits] trigger failed: %s", err)
        return [], err
    met = {c for c, s in zip(conds, scores) if s >= TRIGGER_MIN}
    logger.info("[stack.habits] conditions=%d met=%d", len(conds), len(met))
    return [h for h in habits if h.condition in met], None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_habits.py tests/test_template_context_rules.py tests/test_hybrid_stack_normals.py -q`
Expected: PASS (the context-rule and assumed-normal tests see the same state string as before).

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/template_context_rules.py backend/src/rapid_reports_ai/hybrid_stack/template.py backend/src/rapid_reports_ai/hybrid_stack/normals.py backend/src/rapid_reports_ai/hybrid_stack/habits.py backend/tests/test_hybrid_stack_habits.py
git commit -m "feat(stack): read a template's habits and trigger them with one Jev call (not wired yet)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 7: The decision run proposes habits with verified quotes (evidence only until Phase 3)

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decision_run.py`
- Test: `backend/tests/test_template_decision_run.py`

- [ ] **Step 1: Update the old habit tests and write the new ones** (`backend/tests/test_template_decision_run.py`)

At the top, after the imports, add `from rapid_reports_ai import template_decisions as td`.

In `test_check_quotes_drops_unverifiable_quotes_and_empty_candidates`, replace

```python
        habits=[R.HabitCandidate(finding="x", habit="y", reports=[1, 3]), R.HabitCandidate(finding="z", habit="w", reports=[2])])
```

with

```python
        habits=[])
```

and delete the line `    assert [h.finding for h in run.habits] == ["x"]`.

Replace the body of `test_evidence_record_is_small_and_names_the_version` with:

```python
    run = R.DecisionRun(ok=True, habits=[_h()], dropped_quotes=2)
    ev = R.evidence(run, {"cards": [1, 2], "more": [], "kept": [3]})
    assert ev["version"] == R.RUN_VERSION and ev["dropped_quotes"] == 2 and ev["cards"] == 2 and ev["kept"] == 1
    assert ev["habits"] == [{"paragraph": "Upper", "condition": "an alpha abnormality is reported",
                             "question": "Extension beyond alpha?", "yes": "The abnormality extends beyond alpha.",
                             "no": "No extension beyond alpha.", "reports": [1, 3]}]   # never example text
```

Append:

```python
# ── habits (spec 2026-10-13-findings-triggered-rows-design) ──
HEX = ["Upper: An alpha abnormality. No extension beyond alpha.", "Upper: Normal.",
       "Upper: A second alpha abnormality. No extension beyond alpha."]


def _h(**k):
    base = dict(paragraph="Upper", condition="an alpha abnormality is reported", question="Extension beyond alpha?",
                yes="The abnormality extends beyond alpha.", no="No extension beyond alpha.",
                quotes=[R.Quote(report=1, text="No extension beyond alpha."), R.Quote(report=3, text="No extension beyond alpha.")])
    base.update(k)
    return R.HabitCandidate(**base)


def test_a_habit_needs_two_reports_a_quoted_sentence_and_a_valid_ledger_entry():
    out = R.RunOutput(habits=[
        _h(),
        _h(condition="an alpha abnormality type two is reported", quotes=[R.Quote(report=1, text="No extension beyond alpha.")]),
        _h(condition="a beta abnormality is reported", yes="Beta extends.", no="No beta extension."),
        _h(condition="alpha is reported"),
        _h(condition="an alpha abnormality type three is reported", question="Extension beyond alpha"),
        _h(condition="an alpha abnormality type four is reported", quotes=[R.Quote(report=2, text="never written"),
                                                                         R.Quote(report=3, text="No extension beyond alpha.")])])
    run = R.check_quotes(out, HEX)
    assert [h.condition for h in run.habits] == ["an alpha abnormality is reported"]
    assert run.habits[0].reports == [1, 3] and run.dropped_quotes == 1


def test_habits_merge_by_key_and_are_capped():
    many = [_h(condition=f"an alpha abnormality type {w} is reported") for w in ("one", "two", "three", "four", "five")]
    run = R.check_quotes(R.RunOutput(habits=[_h(), _h(paragraph="upper"), *many]), HEX)
    assert len(run.habits) == R.MAX_HABITS == 4
    assert len({td.match_key("habit", td.habit_key(h.paragraph, h.condition)) for h in run.habits}) == 4


def test_flat_string_quotes_are_read_for_habits_too():
    h = R.HabitCandidate(paragraph="Upper", condition="an alpha abnormality is reported", question="Q?", yes="a.",
                         no="b.", quotes=["Report 1: No extension beyond alpha.", "no number here"])
    assert [(q.report, q.text) for q in h.quotes] == [(1, "No extension beyond alpha.")]


def test_the_prompt_asks_for_each_habit_field():
    for field in ("paragraph:", "condition:", "question:", "yes:", "no:", "at least two reports", "is reported"):
        assert field in R.SYSTEM, field
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decision_run.py -q`
Expected: FAIL with `pydantic ValidationError` / `AttributeError: … has no attribute 'MAX_HABITS'`.

- [ ] **Step 3: The prompt section** (`template_decision_run.py`)

Replace the line beginning `3. HABITS:` in `SYSTEM` with:

```python
3. HABITS: a check the radiologist writes only when a particular finding is reported (for example, whether that finding extends into a neighbouring structure), seen in at least two reports. Never a statement every report makes whatever the findings (that is a normal), never a measured value. For each habit give:
- paragraph: the part of the report it is written in (the structure or region the reports name there, a few words);
- condition: the finding that sets it off, as a statement naming the finding in at least two words and ending "is reported" (for example "a focal abnormality of the main structure is reported");
- question: the check as a short question (at most 12 words, ending with "?");
- yes: the sentence a report writes when the check is positive; no: the sentence when it is negative. Copy at least one of them word for word from the reports and write the other in the same style;
- quotes: the sentence that writes the habit in every report that has it, copied word for word, with the report's number.
```

- [ ] **Step 4: The model, verification and evidence** (`template_decision_run.py`)

After `MIN_QUOTE_CHARS = 6 …` add:

```python
MIN_HABIT_REPORTS = 2   # spec: a habit is proposed only with evidence in at least 2 example reports
MAX_HABITS = 4
```

Replace `class HabitCandidate` with:

```python
class HabitCandidate(BaseModel):
    paragraph: str = ""
    condition: str = ""
    question: str = ""
    yes: str = ""
    no: str = ""
    quotes: List[Quote] = []

    _quotes = field_validator("quotes", mode="before")(staticmethod(_read_quotes))

    @property
    def reports(self) -> List[int]:
        return sorted({q.report for q in self.quotes})
```

After `_wording_matches` add:

```python
def _sentence(s: str) -> str:
    s = " ".join((s or "").split())
    return s if not s or s.endswith((".", "?", "!")) else s + "."


def _habit(h: HabitCandidate, examples: List[str]):
    """(the habit with verified quotes and normalised wording, or None; quotes dropped). Kept only with verified
    quotes from MIN_HABIT_REPORTS reports, its YES or NO sentence written in a cited report, and a ledger entry code
    can apply (td.validate: a two-word condition, a question, two different sentences, no quotes or slots)."""
    ok = [q for q in h.quotes if verified(q, examples)]
    dropped = len(h.quotes) - len(ok)
    clean = HabitCandidate(paragraph=" ".join(h.paragraph.split()), condition=" ".join(h.condition.split()).rstrip("."),
                           question=" ".join(h.question.split()), yes=_sentence(h.yes), no=_sentence(h.no), quotes=ok)
    if len(clean.reports) < MIN_HABIT_REPORTS:
        return None, dropped
    cited = [_norm(examples[q.report - 1]) for q in ok]
    if not any(_norm(s).rstrip(".") in ex for s in (clean.yes, clean.no) if s for ex in cited):
        return None, dropped
    try:
        td.validate("habit", td.habit_key(clean.paragraph, clean.condition),
                    {"mode": "ask", "question": clean.question, "yes": clean.yes, "no": clean.no})
    except td.DecisionError:
        return None, dropped
    return clean, dropped
```

In `check_quotes`, replace

```python
    habits = [h for h in out.habits if len({r for r in h.reports if 1 <= r <= len(examples)}) >= 2]
```

with

```python
    habits: List[HabitCandidate] = []
    seen_habits: set = set()
    for h in out.habits:
        good, d = _habit(h, examples)
        dropped += d
        if good is None:
            continue
        k = td.match_key("habit", td.habit_key(good.paragraph, good.condition))
        if k not in seen_habits:
            seen_habits.add(k)
            habits.append(good)
    habits = sorted(habits, key=lambda h: -len(h.reports))[:MAX_HABITS]
```

and update its docstring's first sentence to: `"""Keep only verified quotes; drop a candidate left with none, a value name code could not store, and a habit that fails _habit.`

In `evidence`, replace `"habits": [h.model_dump() for h in run.habits]` with:

```python
"habits": [{**h.model_dump(exclude={"quotes"}), "reports": h.reports} for h in run.habits]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decision_run.py tests/test_template_rules_cards.py tests/test_rules_step_lab.py -q`
Expected: PASS (including `test_prompt_is_case_agnostic`).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decision_run.py backend/tests/test_template_decision_run.py
git commit -m "feat(decision-run): propose habits with paragraph, condition, question and both sentences; quotes verified

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 8: The lab script: runners, scorers, tables

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/triggered_rows_lab.py`
- Test: `backend/tests/test_triggered_rows_lab.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_triggered_rows_lab.py`)

```python
"""The findings-triggered rows lab's pure scoring (the runners call Jev / Qwen and are run by the controller)."""
from rapid_reports_ai.scripts import triggered_rows_lab as lab

SET = {"slug": "s", "examples": ["a", "b", "c"], "truth": {"habits": [
    {"id": "h1", "paragraph": "Upper", "condition": "c1", "reports": [1, 3]},
    {"id": "h2", "paragraph": "Upper", "condition": "c2", "reports": [2]},
    {"id": "h3", "paragraph": "Lower", "condition": "c3", "reports": [1, 2]}]}}


def test_score_propose_counts_matches_singles_and_quotes():
    payload = {"habits": [{}, {}, {}], "raw_quotes": 8, "verified_quotes": 6}
    row = lab.score_propose(SET, payload, {"0": "h1", "1": "h2", "2": None})
    assert row == {"slug": "s", "proposed": 3, "tp": 1, "fp": 2, "single_proposed": 1, "real": 2, "found": 1,
                   "raw_quotes": 8, "verified_quotes": 6}
    s = lab.summarise_propose([row, {**row, "slug": "t", "tp": 2, "fp": 1, "found": 2}])
    assert (s["precision"], s["recall"], s["quotes_verified"], s["single_proposed"]) == (0.5, 0.75, 0.75, 2)


def test_score_trigger_rows_and_tables():
    tset = {"slug": "t", "dictations": [
        {"id": "d1", "category": "met", "met": ["c1"], "answered": {"c1": "no"}},
        {"id": "d2", "category": "negated", "met": []},
        {"id": "d3", "category": "hedged", "met": []}]}
    payload = {"habits": [{"condition": "c1", "region": "Upper", "mode": "ask"}],
               "scores": {"d1": {"c1": 0.9}, "d2": {"c1": 0.6}, "d3": {"c1": 0.2}},
               "stated": {"d1": {"c1": [0.1, 0.95]}, "d2": {"c1": [0.0, 0.0]}, "d3": {"c1": [0.0, 0.0]}}}
    rows = lab.score_trigger(tset, payload)
    assert [(r["category"], r["truth"], r["score"]) for r in rows] == [("met", True, 0.9), ("negated", False, 0.6),
                                                                       ("hedged", False, 0.2)]
    table = lab.trigger_table(rows, thresholds=(0.5, 0.7))
    assert table["negated"] == {"n": 1, 0.5: 0.0, 0.7: 1.0} and table["all"]["n"] == 3
    assert lab.answered_table(rows, 0.8) == {"n": 1, "correct": 1, "false_fold": 0, "missed": 0}
    assert lab.band_table(rows, 0.35, 0.5) == {"n": 3, "in_band": 0, "in_band_met": 0, "rate": 0.0}
    banded = [{**rows[0], "score": 0.4}, rows[1], rows[2]]
    assert lab.band_table(banded, 0.35, 0.5) == {"n": 3, "in_band": 1, "in_band_met": 1, "rate": 0.333}


def test_cap_pressure_ranks_template_rows_first_within_the_caps():
    assert lab.cap_pressure(["A"], ["A", "A", "B"]) == {"template_rows": 1, "template_capped": 0, "generic_pushed": 1}
    assert lab.cap_pressure(["A", "B", "C", "D", "E"], ["A"]) == {"template_rows": 4, "template_capped": 1,
                                                                   "generic_pushed": 1}
    assert lab.cap_pressure([], ["A"]) == {"template_rows": 0, "template_capped": 0, "generic_pushed": 0}


def test_session_caps_uses_met_ask_habits_only():
    tset = {"slug": "t", "dictations": [{"id": "d1", "category": "met", "met": ["c1"], "generic": ["Upper", "Upper"]}]}
    payload = {"habits": [{"condition": "c1", "region": "Upper", "mode": "ask"},
                          {"condition": "c2", "region": "Upper", "mode": "state"}],
               "scores": {"d1": {"c1": 0.9, "c2": 0.9}}, "stated": {}}
    assert lab.session_caps(tset, payload, 0.5) == [{"id": "d1", "template_rows": 1, "template_capped": 0,
                                                    "generic_pushed": 1}]


def test_md_table():
    assert lab.md_table(["a", "b"], [[1, 2]]) == "| a | b |\n|---|---|\n| 1 | 2 |"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_triggered_rows_lab.py -q`
Expected: FAIL with `ImportError: cannot import name 'triggered_rows_lab'`.

- [ ] **Step 3: Write the script** (`backend/src/rapid_reports_ai/scripts/triggered_rows_lab.py`)

```python
"""Findings-triggered rows lab (spec 2026-10-13-findings-triggered-rows-design, "Lab first"). Reported, not gated:
it prints tables and writes JSON under the private folder; Hassan decides (TRIGGER_MIN, TRIGGER_WORDING).

    .venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab propose --root <dir> [--run 1|2] [--only a,b]
    .venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab trigger --root <dir> [--run 1|2] [--sets sets|heldout] [--wording A|B]
    .venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab report --root <dir> --stage propose|trigger [--sets ...] [--run 1|2] [--wording A|B]

<dir> is ~/Code/rr-template-conversion-private/synthetic/triggered_rows (never the repo).
Proposal sets <dir>/propose/<slug>.json:
  {"slug", "scan_type", "examples": [str], "truth": {"habits": [{"id", "paragraph", "condition", "reports": [int]}]}}
Proposal labels (a Claude subagent; never the model under test) <dir>/labels/propose/run<k>/<slug>.json:
  {"<index into the run's habits>": "<truth id>" | null}
Trigger sets <dir>/<sets>/<slug>.json (sets: synthetic; heldout: real dictations):
  {"slug", "scan_type", "sheet", "dictations": [{"id", "category", "text", "met": [condition], "answered": {condition: "yes"|"no"},
   "generic": [region]}]}
Outputs <dir>/runs/<stage>/<sets>/run<k>[-<wording>]/<slug>.json and <dir>/REPORT_<stage>_<sets>.md. A runner skips any
output file that already exists (eval economy)."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
CATEGORIES = ("met", "not_met", "negated", "hedged", "other_region", "two_findings", "real")


def md_table(head: List[str], rows: List[list]) -> str:
    out = ["| " + " | ".join(str(h) for h in head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 3) if b else None


def load(root: Path, sub: str, only: Optional[List[str]] = None) -> List[dict]:
    sets = [json.loads(p.read_text()) for p in sorted((root / sub).glob("*.json"))]
    return [s for s in sets if not only or s["slug"] in only]


# ── proposal lab ─────────────────────────────────────────────────────────────────────────────────────────────────

def score_propose(s: dict, payload: dict, labels: Dict[str, Optional[str]]) -> dict:
    """One set: proposals matched (by the labeller) to planted habits. A habit planted in 2+ reports is real; one
    planted in a single report must not be proposed."""
    truth = {h["id"]: h for h in s["truth"].get("habits", [])}
    real = {k for k, h in truth.items() if len(set(h["reports"])) >= 2}
    proposed = payload.get("habits", [])
    matched = [labels.get(str(i)) for i in range(len(proposed))]
    tp = sum(1 for m in matched if m in real)
    return {"slug": s["slug"], "proposed": len(proposed), "tp": tp, "fp": len(proposed) - tp,
            "single_proposed": sum(1 for m in matched if m in truth and m not in real), "real": len(real),
            "found": len({m for m in matched if m in real}), "raw_quotes": payload.get("raw_quotes", 0),
            "verified_quotes": payload.get("verified_quotes", 0)}


def summarise_propose(rows: List[dict]) -> dict:
    tot = {k: sum(r[k] for r in rows) for k in ("proposed", "tp", "real", "found", "raw_quotes", "verified_quotes",
                                                "single_proposed")}
    return {"precision": _ratio(tot["tp"], tot["proposed"]), "recall": _ratio(tot["found"], tot["real"]),
            "quotes_verified": _ratio(tot["verified_quotes"], tot["raw_quotes"]),
            "single_proposed": tot["single_proposed"], "sets": len(rows)}


async def _propose_one(s: dict) -> dict:
    from rapid_reports_ai import template_decision_run as tdr
    raw = await tdr._qwen(s["examples"], s.get("scan_type", ""))
    run = tdr.check_quotes(raw, s["examples"])
    return {"slug": s["slug"], "raw_habits": [h.model_dump() for h in raw.habits],
            "habits": [h.model_dump() for h in run.habits],
            "raw_quotes": sum(len(h.quotes) for h in raw.habits),
            "verified_quotes": sum(1 for h in raw.habits for q in h.quotes if tdr.verified(q, s["examples"]))}


async def propose(root: Path, run_no: int, only: Optional[List[str]]) -> None:
    out = root / "runs" / "propose" / "sets" / f"run{run_no}"
    out.mkdir(parents=True, exist_ok=True)
    for s in load(root, "propose", only):
        f = out / f"{s['slug']}.json"
        if f.exists():
            continue
        payload = await _propose_one(s)
        f.write_text(json.dumps(payload, indent=1))
        print(f"{s['slug']}: raw={len(payload['raw_habits'])} kept={len(payload['habits'])}")


# ── trigger lab ──────────────────────────────────────────────────────────────────────────────────────────────────

def score_trigger(s: dict, payload: dict) -> List[dict]:
    """One row per (dictation, condition): the planted truth, Jev's score, and the stated scores of an ask habit."""
    rows = []
    for d in s["dictations"]:
        for cond, p in (payload["scores"].get(d["id"]) or {}).items():
            rows.append({"id": d["id"], "category": d["category"], "condition": cond, "truth": cond in d.get("met", []),
                         "score": p, "answered": (d.get("answered") or {}).get(cond),
                         "stated": (payload.get("stated", {}).get(d["id"]) or {}).get(cond)})
    return rows


def trigger_table(rows: List[dict], thresholds: Sequence[float] = THRESHOLDS) -> Dict[str, dict]:
    """Accuracy per category (and "all") at each threshold."""
    out: Dict[str, dict] = {}
    for cat in [*sorted({r["category"] for r in rows}), "all"]:
        sel = [r for r in rows if cat == "all" or r["category"] == cat]
        out[cat] = {"n": len(sel), **{t: _ratio(sum((r["score"] >= t) == r["truth"] for r in sel), len(sel))
                                      for t in thresholds}}
    return out


def band_table(rows: List[dict], lo: float = 0.35, hi: float = 0.5) -> dict:
    """Hassan H2: a score in [lo, hi) stays silent. How often that band occurs, and how many of its rows were truly
    met (rows the scratchpad does not ask although the finding was there)."""
    band = [r for r in rows if lo <= r["score"] < hi]
    return {"n": len(rows), "in_band": len(band), "in_band_met": sum(r["truth"] for r in band),
            "rate": _ratio(len(band), len(rows))}


def answered_table(rows: List[dict], stated_min: float) -> dict:
    """Already-answered folding on met ask habits: folded when either sentence is stated at stated_min."""
    sel = [r for r in rows if r["truth"] and r["stated"] is not None]
    pred = [max(r["stated"]) >= stated_min for r in sel]
    truth = [r["answered"] in ("yes", "no") for r in sel]
    return {"n": len(sel), "correct": sum(p == t for p, t in zip(pred, truth)),
            "false_fold": sum(p and not t for p, t in zip(pred, truth)),
            "missed": sum(t and not p for p, t in zip(pred, truth))}


def cap_pressure(template_regions: List[str], generic_regions: List[str], per_region: int = 0, total: int = 0) -> dict:
    """The spec's ranking simulated: template rows first, then generic finding rows, within the same caps (2 per
    region, 4 in all). generic_pushed: generic rows shown without the template rows but not with them."""
    from rapid_reports_ai.hybrid_stack.items import MAX_ROWS, MAX_ROWS_PER_REGION
    per_region, total = per_region or MAX_ROWS_PER_REGION, total or MAX_ROWS

    def fit(rows):
        shown, count = [], {}
        for kind, region in rows:
            if count.get(region, 0) >= per_region or len(shown) >= total:
                continue
            count[region] = count.get(region, 0) + 1
            shown.append(kind)
        return shown
    alone = fit([("finding", r) for r in generic_regions])
    both = fit([*(("template", r) for r in template_regions), *(("finding", r) for r in generic_regions)])
    return {"template_rows": both.count("template"), "template_capped": len(template_regions) - both.count("template"),
            "generic_pushed": len(alone) - both.count("finding")}


def session_caps(s: dict, payload: dict, threshold: float) -> List[dict]:
    asks = {h["condition"]: h["region"] for h in payload["habits"] if h["mode"] == "ask"}
    out = []
    for d in s["dictations"]:
        sc = payload["scores"].get(d["id"]) or {}
        regions = [asks[c] for c, p in sc.items() if c in asks and p >= threshold]
        out.append({"id": d["id"], **cap_pressure(regions, d.get("generic", []))})
    return out


async def _trigger_one(s: dict, wording: str) -> dict:
    from rapid_reports_ai import template_sheet_grammar as tsg
    from rapid_reports_ai.hybrid_stack import habits as H
    from rapid_reports_ai.hybrid_stack import jev_stack as J
    habits = H.template_habits(tsg.parse_sheet(s["sheet"]).structure)
    conds = list(dict.fromkeys(h.condition for h in habits))
    asks = [h for h in habits if h.mode == "ask"]
    out = {"slug": s["slug"], "wording": wording, "habits": [h.model_dump() for h in habits], "scores": {}, "stated": {}}
    for d in s["dictations"]:
        sc = await H.ask_triggers(s.get("scan_type", ""), d["text"], conds, wording=H.TRIGGER_WORDINGS[wording])
        out["scores"][d["id"]] = dict(zip(conds, sc))
        checks = await J.ask_rows(d["text"], [x for h in asks for x in (h.yes, h.no)], [], contra=False)
        out["stated"][d["id"]] = {h.condition: [checks[2 * k].stated, checks[2 * k + 1].stated]
                                  for k, h in enumerate(asks)}
    return out


async def trigger(root: Path, run_no: int, sets: str, wording: str, only: Optional[List[str]]) -> None:
    out = root / "runs" / "trigger" / sets / f"run{run_no}-{wording}"
    out.mkdir(parents=True, exist_ok=True)
    for s in load(root, sets, only):
        f = out / f"{s['slug']}.json"
        if f.exists():
            continue
        f.write_text(json.dumps(await _trigger_one(s, wording), indent=1))
        print(f"{s['slug']}: {len(s['dictations'])} dictations")


# ── reports (tables only; the controller writes the prose) ───────────────────────────────────────────────────────

def report(root: Path, stage: str, sets: str, run_no: int, wording: str) -> str:
    parts = [f"# Triggered rows lab: {stage} ({sets}, run {run_no})"]
    if stage == "propose":
        rows = []
        for s in load(root, "propose"):
            f = root / "runs" / "propose" / "sets" / f"run{run_no}" / f"{s['slug']}.json"
            lf = root / "labels" / "propose" / f"run{run_no}" / f"{s['slug']}.json"
            if f.exists() and lf.exists():
                rows.append(score_propose(s, json.loads(f.read_text()), json.loads(lf.read_text())))
        parts.append(md_table(list(rows[0]) if rows else ["slug"], [list(r.values()) for r in rows]))
        parts.append(md_table(["metric", "value"], [[k, v] for k, v in summarise_propose(rows).items()]))
    else:
        from rapid_reports_ai.hybrid_stack.habits import TRIGGER_MIN
        from rapid_reports_ai.hybrid_stack.jev_stack import STATED_MIN
        rows, caps = [], []
        for s in load(root, sets):
            f = root / "runs" / "trigger" / sets / f"run{run_no}-{wording}" / f"{s['slug']}.json"
            if not f.exists():
                continue
            payload = json.loads(f.read_text())
            rows += score_trigger(s, payload)
            caps += session_caps(s, payload, TRIGGER_MIN)
        table = trigger_table(rows)
        parts.append(f"## Trigger accuracy by category (wording {wording})\n"
                     + md_table(["category", "n", *THRESHOLDS], [[c, v["n"], *(v[t] for t in THRESHOLDS)]
                                                                for c, v in table.items()]))
        parts.append(f"## Silent band [0.35, {TRIGGER_MIN}) (Hassan H2: never asked)\n"
                     + md_table(["metric", "value"], [[k, v] for k, v in band_table(rows, 0.35, TRIGGER_MIN).items()]))
        parts.append(f"## Already answered (STATED_MIN {STATED_MIN})\n"
                     + md_table(["metric", "value"], [[k, v] for k, v in answered_table(rows, STATED_MIN).items()]))
        n = len(caps)
        parts.append(f"## Rows per session against the caps (TRIGGER_MIN {TRIGGER_MIN})\n" + md_table(
            ["sessions", "with a template row", "template rows capped", "sessions pushing out a generic row"],
            [[n, sum(c["template_rows"] > 0 for c in caps), sum(c["template_capped"] for c in caps),
              sum(c["generic_pushed"] > 0 for c in caps)]]))
    text = "\n\n".join(parts) + "\n"
    (root / f"REPORT_{stage}_{sets}.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["propose", "trigger", "report"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--sets", default="sets")
    ap.add_argument("--wording", default="B", choices=["A", "B"])
    ap.add_argument("--only", default="")
    ap.add_argument("--stage", dest="report_stage", default="trigger")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.stage == "propose":
        asyncio.run(propose(a.root, a.run, only))
    elif a.stage == "trigger":
        asyncio.run(trigger(a.root, a.run, a.sets, a.wording, only))
    else:
        print(report(a.root, a.report_stage, a.sets if a.report_stage == "trigger" else "sets", a.run, a.wording))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_triggered_rows_lab.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/triggered_rows_lab.py backend/tests/test_triggered_rows_lab.py
git commit -m "feat(lab): triggered-rows lab runners and scorers (proposal, trigger, caps)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 9: Controller — generate the synthetic sets (Opus subagents, private folder)

No repository change. The controller runs these steps.

- [ ] **Step 1: Make the folders**

```bash
R=~/Code/rr-template-conversion-private/synthetic/triggered_rows
mkdir -p $R/propose $R/sets $R/heldout $R/labels/propose $R/runs
```

- [ ] **Step 2: Proposal sets — dispatch one Opus subagent** (`Agent`, `model: "opus"`) with this prompt:

```
You generate synthetic lab data. Never write inside /Users/hassan/Code/rapid_reports_ai. Read
~/Code/rr-template-conversion-private/data_all.json (31 templates; templates[i].scan_type and templates[i].reports).
Pick 6 templates of different scan types that have 3 or more reports. For each, write 8 example reports in the same
style, sections and phrasing as that template's real reports (copy its voice; never copy a patient detail), and plant
findings-triggered habits: a sentence the radiologist writes only when a particular finding is present (for example
whether that finding extends into a neighbouring structure), in the paragraph where that finding is written.
Across the 6 sets: 4 sets each have 2 habits written in 2 to 4 reports (only reports that contain the triggering
finding), and 1 habit written in exactly 1 report; 1 set has a triggering finding in several reports but no habit at
all; 1 set has 1 habit in 2 reports and nothing else. Vary the wording slightly across reports, as a real
radiologist does, but keep one sentence clearly the habit's. Write each set to
~/Code/rr-template-conversion-private/synthetic/triggered_rows/propose/<slug>.json as
{"slug", "scan_type", "examples": [8 report texts], "truth": {"habits": [{"id": "h1", "paragraph": "<the paragraph
or structure the reports write it under>", "condition": "<the finding, at least two words, ending 'is reported'>",
"reports": [1-based report numbers that write the habit]}]}}. Report back the 6 slugs and the planted counts.
```

- [ ] **Step 3: Trigger sets — dispatch one Opus subagent** with this prompt:

```
You generate synthetic lab data. Never write inside /Users/hassan/Code/rapid_reports_ai. Pick 5 curated template
sheets of different scan types from ~/Code/rr-template-conversion-private/final/*.final.md. In each, add exactly 2
findings-triggered habits inside findings paragraphs (## Paragraph: <name> (<a findings-role SECTION>)), one of each
form, written exactly as:
RULE WHEN [findings: <finding in at least two words> is reported] ASK "<short question?>" YES "<sentence>" NO "<sentence>"
NEGATIVE "<sentence>" WHEN [findings: <finding in at least two words> is reported]
Choose habits a consultant in that specialty genuinely writes. Then write about 72 short dictations per sheet (as a
radiologist dictates into a scratchpad: one region per sentence, plain sentences), 12 in each category:
met (the finding plainly present), not_met (the finding absent, other findings present), negated ("no <finding>"),
hedged ("possible", "cannot exclude", "?"), other_region (a similar finding in a different structure or region),
two_findings (both habits' findings present). In about a third of the met and two_findings dictations, the
radiologist already states the ask habit's YES or NO sentence in other words. For each dictation also list
"generic": 0 to 4 region names (paragraph names of that sheet) where a generic decision-support check would be
raised for the dictated findings. Write each sheet to
~/Code/rr-template-conversion-private/synthetic/triggered_rows/sets/<slug>.json as {"slug", "scan_type": "<the
sheet's scan type>", "sheet": "<the whole
sheet with the 2 habits>", "dictations": [{"id": "<slug>-<n>", "category", "text", "met": [the conditions met, copied
exactly from the sheet], "answered": {"<condition>": "yes"|"no"} only where already stated, "generic": [...]}]}.
Report back the slugs and the counts per category.
```

- [ ] **Step 4: Lint the trigger sheets** (from `backend/`)

```bash
cd backend && .venv/bin/python - <<'EOF'
import json, pathlib
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai.hybrid_stack import habits as H
root = pathlib.Path.home() / "Code/rr-template-conversion-private/synthetic/triggered_rows"
for p in sorted((root / "sets").glob("*.json")):
    s = json.loads(p.read_text())
    r = tsg.parse_sheet(s["sheet"])
    hs = H.template_habits(r.structure)
    print(p.name, "errors", [(e.reason, e.text[:60]) for e in r.errors], "habits", len(hs), "dictations", len(s["dictations"]))
EOF
```

Expected: every sheet `errors []` and `habits 2`. A sheet with errors goes back to the subagent with the error lines (SendMessage), then is linted again.

- [ ] **Step 5: Held-out real set.** Pull real scratchpad dictations for the 5 sheets' scan types from production through Metabase `/api/dataset` in the Chrome session (memory: `reference_prod_smoke_testing.md`; standing permission to read prod content; Cloudflare blocks scripts), at most 30 per scan type, into the scratchpad directory. Dispatch one Opus subagent to label them: for each dictation, `category: "real"`, `met` (which of that sheet's two conditions the dictation plainly reports), `answered`, `generic`; write `<root>/heldout/<slug>.json` with the same sheet. If production has fewer than 10 dictations for a scan type, report that as such; never pad with synthetic text.

### Task 10: Controller — run the labs, label, report; Hassan decides

No code change unless Hassan changes a constant (Step 6).

- [ ] **Step 1: Run the proposal lab (2 runs)**

```bash
cd backend && R=~/Code/rr-template-conversion-private/synthetic/triggered_rows
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab propose --root $R --run 1
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab propose --root $R --run 2
```

- [ ] **Step 2: Label the proposals.** Dispatch one Opus subagent: "For each file in `$R/runs/propose/sets/run<k>/` and its set in `$R/propose/`, decide for each entry of `habits` which planted truth habit (by `id`) it is the same habit as (same paragraph and the same triggering finding, any wording), or null. Write `$R/labels/propose/run<k>/<slug>.json` as `{"<index>": "<id>" | null}`. Never edit the run files." Then:

```bash
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab report --root $R --stage propose --run 1
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab report --root $R --stage propose --run 2
```

- [ ] **Step 3: Run the trigger lab, both wordings, synthetic sets (wording A once, B twice)**

```bash
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab trigger --root $R --run 1 --wording A
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab trigger --root $R --run 1 --wording B
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab trigger --root $R --run 2 --wording B
for w in A B; do .venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab report --root $R --stage trigger --sets sets --run 1 --wording $w; done
```

- [ ] **Step 4: Run the held-out set** with the better wording from Step 3 (one run):

```bash
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab trigger --root $R --run 1 --sets heldout --wording B
.venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab report --root $R --stage trigger --sets heldout --run 1 --wording B
```

(Use `--wording A` in both lines if A did better in Step 3.)

- [ ] **Step 5: Write `$R/REPORT.md`** (prose, in the private folder): proposal precision, recall, quotes verified, and singles proposed (both runs); trigger accuracy per category at each threshold for both wordings, how often a score falls in the silent 0.35–0.5 band and how many of those were truly met (Hassan H2), the run-to-run spread for B, the held-out result separately; already-answered correct / false folds / missed; sessions with a template row and sessions that push out a generic row. End with recommendations (a threshold and a wording), and hand-read three false triggers and three misses verbatim. Tell Hassan the report path; he sets the values.

- [ ] **Step 6: Apply Hassan's choice** (only if it differs from the defaults). In `backend/src/rapid_reports_ai/hybrid_stack/habits.py` change the line `TRIGGER_MIN = 0.5   # = jev_stack.CONDITION_MIN until the trigger lab reports (Hassan sets it)` to the chosen value with the comment `# trigger lab 2026-10-<dd> (REPORT.md): <one-line reason>`, and/or `TRIGGER_WORDING = TRIGGER_WORDINGS["B"]` to `["A"]`. Update the last assertion of `test_trigger_wordings_are_case_agnostic_and_the_cut_off_is_the_context_rules_one` to the chosen value, run `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_habits.py -q` (PASS), and commit:

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/habits.py backend/tests/test_hybrid_stack_habits.py
git commit -m "chore(stack): trigger cut-off and wording from the triggered-rows lab

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 3: decision-run proposal and the Rules-step card

### Task 11: Habit cards from the decision run

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_rules_cards.py`
- Test: `backend/tests/test_template_rules_cards.py`

- [ ] **Step 1: Write the failing test** (append to `backend/tests/test_template_rules_cards.py`)

```python
def test_the_run_s_habits_become_cards_with_quotes_never_preticked():
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai.template_decision_run import DecisionRun, HabitCandidate, Quote
    run = DecisionRun(ok=True, states={}, habits=[HabitCandidate(
        paragraph="Upper", condition="an alpha abnormality is reported", question="Extension beyond alpha?",
        yes="The abnormality extends beyond alpha.", no="No extension beyond alpha.",
        quotes=[Quote(report=1, text="No extension beyond alpha."), Quote(report=3, text="No extension beyond alpha.")])])
    built = trc.build_cards(run, 3)
    (c,) = [c for c in built["cards"] if c["kind"] == "habit"]
    assert c["selected"] is None and c["step"] == "rules" and c["key"] == "Upper :: an alpha abnormality is reported"
    assert [trc.evidence_line(e) for e in c["evidence"]] == [
        "report 1: 'No extension beyond alpha.'", "report 3: 'No extension beyond alpha.'"]
    assert built["kept"] == [] and built["defaults"] == []
    led, errors = td.ledger_from_changes([{"kind": "habit", "key": c["key"], "choice": c["choices"][0]["choice"]}])
    assert errors == [] and led[0]["choice"]["mode"] == "ask" and led[0]["source"] == "creation"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_rules_cards.py -q -k habits_become_cards`
Expected: FAIL with `ValueError: not enough values to unpack (expected 1, got 0)`.

- [ ] **Step 3: Build habit cards** (`template_rules_cards.py`)

After `_concept_cards` add:

```python
def _habit_cards(run: DecisionRun) -> List[dict]:
    """One card per proposed habit (verified quotes from at least two examples, template_decision_run._habit), with
    up to three quotes. Never pre-ticked and never "kept": nothing is active until the radiologist confirms it."""
    return [habit_card(h.paragraph, h.condition, h.question, h.yes, h.no,
                       [{"reports": [q.report], "quote": q.text} for q in h.quotes[:3]])
            for h in run.habits]
```

In `build_cards` replace

```python
    every = [*_value_cards(run, n_examples), *_concept_cards(run, n_examples)]
```

with

```python
    every = [*_value_cards(run, n_examples), *_concept_cards(run, n_examples), *_habit_cards(run)]
```

and in the module docstring after "Only values every example states are kept; a study-level concept is always a card (D1)." add: ` A proposed habit is always a card ("Ask every time / Always state / Not needed"), ranked with concepts.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_rules_cards.py tests/test_template_decision_run.py tests/test_template_ledger_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_rules_cards.py backend/tests/test_template_rules_cards.py
git commit -m "feat(rules-step): proposed habits become cards (Ask every time / Always state / Not needed)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 12: The habit card in the Rules step (frontend); Phase 3 check

**Files:**
- Modify: `frontend/src/lib/template-rules/types.ts`
- Modify: `frontend/src/lib/template-rules/RulesStep.svelte`
- Test: `frontend/src/lib/template-rules/RulesStep.svelte.test.ts`

- [ ] **Step 1: Write the failing test** (append inside the `describe('RulesStep', …)` block of `RulesStep.svelte.test.ts`; add the helper above the `describe`)

```ts
const HKEY = 'Upper :: an alpha abnormality is reported';
const HTEXTS = { question: 'Extension beyond alpha?', yes: 'The abnormality extends beyond alpha.', no: 'No extension beyond alpha.' };
const habit = (): DecisionCard => ({
	id: 'habit:upper :: an alpha abnormality is reported', kind: 'habit', step: 'rules',
	title: 'Upper: when an alpha abnormality is reported',
	evidence: [{ reports: [1], quote: 'No extension beyond alpha.' }, { reports: [3], quote: 'No extension beyond alpha.' }],
	ledger_kind: 'habit', key: HKEY, habit: { condition: 'an alpha abnormality is reported', ...HTEXTS },
	choices: [
		{ id: 'ask', label: 'Ask every time', choice: { mode: 'ask', ...HTEXTS } },
		{ id: 'state', label: 'Always state', choice: { mode: 'state', ...HTEXTS } },
		{ id: 'removed', label: 'Not needed', choice: { mode: 'removed', ...HTEXTS } }
	],
	selected: null, rank: 2
});
```

```ts
	it('a habit card shows the question and both sentences, and records the habit chosen', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [habit()], kept: [], onContinue });
		await expect.element(page.getByText('report 3: \'No extension beyond alpha.\'')).toBeInTheDocument();
		await expect.element(page.getByText('Ask: “Extension beyond alpha?”')).toBeInTheDocument();
		await expect.element(page.getByText('Yes: “The abnormality extends beyond alpha.” · No: “No extension beyond alpha.”')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Upper: when an alpha abnormality is reported: Always state' }).click();
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'habit', key: HKEY, choice: { mode: 'state', ...HTEXTS }, source: 'creation' }]);
	});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/template-rules/RulesStep.svelte.test.ts`
Expected: FAIL — the type check rejects `kind: 'habit'` / the text `Ask: “Extension beyond alpha?”` is not found.

- [ ] **Step 3: Types** (`template-rules/types.ts`)

Replace

```ts
export type LedgerKind = 'value' | 'concept' | 'fixed' | 'normal';
export type CardKind = 'value' | 'concept' | 'disagree' | 'fixed' | 'normal' | 'uncovered' | 'duplicate' | 'group';
```

with

```ts
export type LedgerKind = 'value' | 'concept' | 'fixed' | 'normal' | 'habit';
export type CardKind = 'value' | 'concept' | 'disagree' | 'fixed' | 'normal' | 'uncovered' | 'duplicate' | 'group' | 'habit';
```

and in `interface DecisionCard`, after `usual?: Record<string, string>;` add:

```ts
	/** kind "habit" (findings-triggered rows): the condition, the question and the sentence each answer writes */
	habit?: { condition: string; question: string; yes: string; no: string };
```

- [ ] **Step 4: The card body** (`RulesStep.svelte`)

Replace

```svelte
		{:else if c.wording?.text}
			<p class="text-xs text-gray-300">“{c.wording.text}”</p>
		{/if}
```

with

```svelte
		{:else if c.kind === 'habit' && c.habit}
			<p class="text-xs text-gray-300">Ask: “{c.habit.question}”</p>
			<p class="text-xs text-gray-400">Yes: “{c.habit.yes}” · No: “{c.habit.no}”</p>
		{:else if c.wording?.text}
			<p class="text-xs text-gray-300">“{c.wording.text}”</p>
		{/if}
```

- [ ] **Step 5: Run the tests and the check**

Run: `cd frontend && npx vitest run src/lib/template-rules && npm run check 2>&1 | tail -3`
Expected: PASS; svelte-check reports no more than 1194 problems.

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: PASS (Phase 3 check).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/template-rules/types.ts frontend/src/lib/template-rules/RulesStep.svelte frontend/src/lib/template-rules/RulesStep.svelte.test.ts
git commit -m "feat(rules-step): the habit card shows its question and sentences

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 4: scratchpad trigger, rows, ranking, Generate

### Task 13: Template rows in `items.py` (rank, fold, dedupe, caps)

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/items.py`
- Test: `backend/tests/test_hybrid_stack_items.py`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_hybrid_stack_items.py`)

```python
# ── template rows (spec 2026-10-13-findings-triggered-rows-design) ──
from rapid_reports_ai.hybrid_stack.habits import Habit

TASK = Habit(region="Pelvic organs", condition="an adnexal mass is reported", mode="ask", question="Mass vascularity?",
             yes="The mass is vascular.", no="No internal vascularity.")
TSTATE = Habit(region="Pelvic organs", condition="an adnexal mass is reported", mode="state", no="No free fluid")


def test_template_rows_and_required_statements_from_met_habits():
    (row,) = I.template_rows([TASK, TSTATE])
    assert (row.kind, row.region, row.question, row.sentences, row.yes, row.no) == (
        "template", "Pelvic organs", "Mass vascularity?", ["The mass is vascular.", "No internal vascularity."],
        "The mass is vascular.", "No internal vascularity.")
    assert row.id == I._id("template", "Pelvic organs", "Mass vascularity?")
    assert row.why == "Your template asks this when an adnexal mass is reported."
    assert I.template_required([TASK, TSTATE]) == {"Pelvic organs": ["No free fluid."]}


def test_template_rows_rank_after_referrals_before_findings_and_share_the_caps():
    def r(kind, i, region):
        return I.Item(id=f"{kind}{i}", kind=kind, region=region, question="q?", sentences=["s."])
    rows = [r("finding", 0, "A"), r("finding", 1, "A"), r("finding", 2, "B"), r("referral", 0, ""), r("template", 0, "A"),
            r("template", 1, "C")]
    shown, capped = I._limit(rows)
    assert [x.id for x in shown] == ["referral0", "template0", "template1", "finding0"]
    assert [x.id for x in capped] == ["finding1", "finding2"]


async def _met_all(habits, scan_type, findings, ask=None):
    assert scan_type == "CT"   # the scan type reaches the trigger (Hassan H1: never the history)
    return list(habits), None


async def test_a_template_row_folds_when_either_sentence_is_stated_and_is_never_split(monkeypatch):
    splits = []

    async def split(negs):
        splits.append(list(negs))
        return [[n] for n in negs]
    _setup(monkeypatch, _raw(CYST), _checks({"No internal vascularity.": (0.9, 0.0, 0.0)}), split=split)
    monkeypatch.setattr(I, "met_habits", _met_all)
    res = await I.update("CT", "", ["Pelvic organs"], "Adnexal mass, no internal vascularity.", ["Adnexal mass."],
                         review=True, habits=[TASK])
    (t,) = [x for x in res.items if x.kind == "template"]
    assert t.answered and t.sentences == ["The mass is vascular.", "No internal vascularity."]
    assert all("The mass is vascular." not in part for part in splits)


async def test_an_open_template_row_keeps_both_sentences_and_wins_over_a_generic_duplicate(monkeypatch):
    _setup(monkeypatch, _raw({**CYST, "negatives": ["No internal vascularity."]}),
           _checks({"The mass is vascular.": (0.0, 0.9, 0.0)}))   # a contradiction never edits a template row
    monkeypatch.setattr(I, "met_habits", _met_all)
    res = await I.update("CT", "", ["Pelvic organs"], "Adnexal mass.", ["Adnexal mass."], review=True, habits=[TASK])
    assert [x.kind for x in res.items] == ["template"]
    assert res.items[0].sentences == ["The mass is vascular.", "No internal vascularity."] and not res.items[0].answered


async def test_required_statements_come_back_and_a_failed_trigger_leaves_generic_rows(monkeypatch):
    _setup(monkeypatch, _raw(CYST))
    monkeypatch.setattr(I, "met_habits", _met_all)
    res = await I.update("CT", "", ["Pelvic organs"], "Adnexal mass.", ["Adnexal mass."], review=True, habits=[TSTATE])
    assert res.required == {"Pelvic organs": ["No free fluid."]} and res.trigger_error is None

    async def failed(habits, scan_type, findings, ask=None):
        return [], "RuntimeError: jev down"
    monkeypatch.setattr(I, "met_habits", failed)
    res = await I.update("CT", "", ["Pelvic organs"], "Adnexal mass.", ["Adnexal mass."], review=True, habits=[TASK])
    assert [x.kind for x in res.items] == ["finding"] and res.required == {}
    assert res.trigger_error == "RuntimeError: jev down"


async def test_no_trigger_without_dictation_or_habits(monkeypatch):
    calls = []

    async def met(habits, scan_type, findings, ask=None):
        calls.append(findings)
        return [], None
    _setup(monkeypatch, _raw(CYST))
    monkeypatch.setattr(I, "met_habits", met)
    await I.update("CT", "", ["Pelvic organs"], "", [], habits=[TASK])
    await I.update("CT", "", ["Pelvic organs"], "Adnexal mass.", ["Adnexal mass."], review=True)
    assert calls == []


async def test_recheck_folds_a_template_row_the_dictation_now_answers(monkeypatch):
    _setup(monkeypatch, _raw(), _checks({"The mass is vascular.": (0.9, 0.0, 0.0)}))
    res = await I.recheck("Vascular adnexal mass.", I.template_rows([TASK]))
    assert res.items[0].answered and res.items[0].kind == "template"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_items.py -q -k "template or trigger"`
Expected: FAIL with `AttributeError: module … has no attribute 'template_rows'`.

- [ ] **Step 3: Implement** (`hybrid_stack/items.py`)

In the module docstring, append: ` A template's findings-triggered habits (spec 2026-10-13-findings-triggered-rows-design) are triggered by one Jev call in the review, in parallel with the writer: met habit questions are rows of kind "template", ranked after referral rows and before finding rows within the same caps; met required statements are returned for the assumed tray.`

Add `from .habits import Habit, met_habits` after the `from .jev_stack import …` line.

In `class Item`, replace `    kind: str              # finding | referral` with `    kind: str              # finding | referral | template` and after `answered: bool = False …` add:

```python
    yes: str = ""          # template rows: the template's sentence for Yes
    no: str = ""           # template rows: the template's sentence for No
```

In `class ItemsResult`, after `contradicted: list[str] = []   …` add:

```python
    required: dict[str, list[str]] = {}   # met template required statements, region -> sentences (the assumed tray)
    trigger_error: str | None = None      # the template trigger call failed: no template rows this review
```

After `_rows` add:

```python
_ORDER = {"referral": 0, "template": 1, "finding": 2}


def _rank(rows: list[Item]) -> list[Item]:
    """Referral rows, then template rows, then finding rows; stable within each kind."""
    return sorted(rows, key=lambda r: _ORDER.get(r.kind, 2))


def template_rows(met: list[Habit]) -> list[Item]:
    """A row per met habit question: the template's own question and sentences, in its paragraph-region."""
    return [Item(id=_id("template", h.region, h.question), kind="template", region=h.region, question=h.question,
                 why=f"Your template asks this when {h.condition}.", sentences=[_sentence(h.yes), _sentence(h.no)],
                 yes=_sentence(h.yes), no=_sentence(h.no))
            for h in met if h.mode == "ask"]


def template_required(met: list[Habit]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for h in met:
        if h.mode == "state" and h.no.strip():
            out.setdefault(h.region, []).append(_sentence(h.no))
    return out
```

In `_split`, replace `    flat = [s for r in rows for s in r.sentences]` with `    flat = [s for r in rows if r.kind != "template" for s in r.sentences]`, and replace the reassignment loop

```python
    k = 0
    for r in rows:
        n = len(r.sentences)
        r.sentences = [_sentence(p) for ps in parts[k:k + n] for p in ps]
        k += n
```

with

```python
    k = 0
    for r in rows:
        if r.kind == "template":   # the template's own sentences are its buttons: never split
            continue
        n = len(r.sentences)
        r.sentences = [_sentence(p) for ps in parts[k:k + n] for p in ps]
        k += n
```

In `_dedupe`, at the top of the `for r in rows:` loop add:

```python
        if r.kind == "template":   # a template row wins: its sentences are seen first, it is never dropped
            seen.update(_norm(s) for s in r.sentences)
            out.append(r)
            continue
```

In `_check`, inside the final loop, replace

```python
        n = len(r.sentences)
        mine = fates[k:k + n]
        k += n
        r.sentences = [s for s, f in zip(r.sentences, mine) if f == "keep"]
```

with

```python
        n = len(r.sentences)
        mine = fates[k:k + n]
        k += n
        if r.kind == "template":   # folds when the dictation states either sentence; never edited (its buttons)
            r.answered = "answered" in mine
            continue
        r.sentences = [s for s, f in zip(r.sentences, mine) if f == "keep"]
```

Replace `_limit` with:

```python
def _limit(rows: list[Item]) -> tuple[list[Item], list[Item]]:
    # Referral rows are never capped: _rank puts them first and there are at most MAX_REFERRALS (< MAX_ROWS) of them,
    # so the case cap is always reached on template or finding rows. The scratchpad relies on this: a capped row (shown
    # behind "N more checks") never blocks Confirm, which an unanswered referral row must. Template rows come before
    # finding rows and count against the same caps (spec 2026-10-13-findings-triggered-rows-design).
    out, capped, per_region, total = [], [], {}, 0
    for r in _rank(rows):
        if r.answered:
            out.append(r)
            continue
        if not r.sentences:
            continue
        r.sentences = r.sentences[:MAX_SENTENCES]
        regional = r.kind in ("finding", "template")
        over_region = regional and per_region.get(r.region, 0) >= MAX_ROWS_PER_REGION
        if over_region or total >= MAX_ROWS:
            capped.append(r)
            continue
        if regional:
            per_region[r.region] = per_region.get(r.region, 0) + 1
        total += 1
        out.append(r)
    return out, capped
```

Replace `update` with:

```python
async def update(scan_type: str, history: str, regions: list[str], dictation: str, abnormal: list[str],
                 not_assessable: str = "", removed: list[str] | None = None,
                 tapped: list[str] | None = None, referrals: list[Referral] | None = None,
                 review: bool = False, habits: list[Habit] | None = None) -> ItemsResult:
    """The open rows for this dictation. referrals: the session's fixed referral rows (None on the first call, whose
    referral_questions then become them). The writer's reply is cached per (scan, history, abnormal sentences,
    regions, referral questions); the splitter and the checks always run on the current dictation and removals.
    habits: the template's confirmed habits; with a dictation, their trigger runs alongside the writer (never cached),
    on the scan type and the dictation only (never the clinical history)."""
    t0 = time.perf_counter()
    removed = [r for r in (removed or []) if r.strip()]
    trig = asyncio.create_task(met_habits(habits, scan_type, dictation)) if habits and dictation.strip() else None
    key = (*_key(scan_type, history, regions, abnormal, referrals), review)
    cached = key in _CACHE
    if cached:
        _CACHE.move_to_end(key)
        raw = _CACHE[key]
    else:
        try:
            raw = await _write(scan_type, history, regions, dictation, not_assessable, removed, referrals, review)
        except Exception as e:  # fail open: no rows
            logger.warning("[stack.items] %s: %s", type(e).__name__, str(e)[:200])
            if trig is not None:
                trig.cancel()
            return ItemsResult(items=[], ms=int((time.perf_counter() - t0) * 1000), error=f"{type(e).__name__}: {e}")
        _CACHE[key] = raw
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    met, trigger_error = (await trig) if trig is not None else ([], None)
    rows = _rank([*template_rows(met), *_rows(raw, referrals)])
    await _split(rows)
    rows = _dedupe(rows)
    contradicted = await _check(rows, dictation, removed, [t for t in (tapped or []) if t.strip()])
    items, capped = _limit(rows)
    return ItemsResult(items=items, capped=capped, contradicted=contradicted, cached=cached,
                       ms=int((time.perf_counter() - t0) * 1000), required=template_required(met),
                       trigger_error=trigger_error)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_items.py tests/test_hybrid_stack_habits.py -q`
Expected: PASS (the existing caps and referral tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/items.py backend/tests/test_hybrid_stack_items.py
git commit -m "feat(stack): template rows ranked before finding rows within the caps; required statements returned

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 14: `/items` reads the template's habits

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/routes.py`
- Test: `backend/tests/test_hybrid_stack_routes.py`

- [ ] **Step 1: Write the failing test** (append to `backend/tests/test_hybrid_stack_routes.py`)

```python
_HABIT_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Upper (FINDINGS)
COVERS ["alpha"]
NORMAL [alpha] "Alpha is normal."
RULE WHEN [findings: an alpha abnormality is reported] ASK "Extension beyond alpha?" YES "The abnormality extends beyond alpha." NO "No extension beyond alpha."
"""


def test_items_passes_the_templates_confirmed_habits_only(authed, monkeypatch, db_session, user):
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai.database.models import Template
    from rapid_reports_ai.hybrid_stack.items import ItemsResult
    led, _ = td.set_decision([], "habit", "Upper :: an alpha abnormality is reported",
                             {"mode": "ask", "question": "Extension beyond alpha?",
                              "yes": "The abnormality extends beyond alpha.", "no": "No extension beyond alpha."},
                             source="creation", at="t")
    t = Template(name="T", user_id=user.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _HABIT_SHEET, "decisions": led})
    unconfirmed = Template(name="U", user_id=user.id, is_active=True, tags=[],
                           template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _HABIT_SHEET})
    db_session.add_all([t, unconfirmed])
    db_session.commit()
    seen = {}

    async def items(*a, **k):
        seen.clear()
        seen.update(k)
        return ItemsResult(items=[])
    monkeypatch.setattr(R, "items_update", items)
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x", "template_id": str(t.id)})
    assert [(h.region, h.mode, h.question) for h in seen["habits"]] == [("Upper", "ask", "Extension beyond alpha?")]
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x"})
    assert "habits" not in seen
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x", "template_id": str(uuid.uuid4())})
    assert "habits" not in seen
    # Hassan H3: the same line with no confirmed entry is inactive
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x", "template_id": str(unconfirmed.id)})
    assert "habits" not in seen
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_routes.py -q -k confirmed_habits_only`
Expected: FAIL with `KeyError: 'habits'`.

- [ ] **Step 3: Implement** (`hybrid_stack/routes.py`)

Add `from .habits import template_habits` after `from .draft import DraftResult, draft_conclusion`, and `from ..template_decisions import clean_ledger` after `from ..template_sheet_structure import generation_stamp`.

In `class ItemsRequest`, after `review: bool = False …` add:

```python
    template_id: str | None = None                       # its findings-triggered habits are asked in the review
```

Replace `stack_items` with:

```python
@router.post("/items", response_model=ItemsResult)
async def stack_items(req: ItemsRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    extra = {}
    if req.template_id:
        t = get_template(db, req.template_id, str(user.id))   # the string id as a UUID, owner only
        st = template_structure(t.template_config) if t is not None else None
        # only habits the radiologist confirmed are asked (Hassan H3: a line with no entry is inactive)
        habits = template_habits(st, clean_ledger((t.template_config or {}).get("decisions"))) if st is not None else []
        if habits:
            extra["habits"] = habits
    return await items_update(req.scan_type, req.clinical_history, req.regions[:40], req.dictation,
                              req.abnormal[:40], req.not_assessable[:2000], req.removed[:50], req.tapped[:20],
                              req.referrals[:2] if req.referrals is not None else None, req.review, **extra)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_routes.py -q`
Expected: PASS (the positional fake in `test_items_assumed_and_draft_routes` still works: no template, no `habits`).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/routes.py backend/tests/test_hybrid_stack_routes.py
git commit -m "feat(stack): /items asks a template's habits in the review

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 15: Frontend types, API and the template-row helpers

**Files:**
- Modify: `frontend/src/lib/hybrid-stack/types.ts`, `frontend/src/lib/hybrid-stack/api.ts`, `frontend/src/lib/hybrid-stack/items.ts`
- Create: `frontend/src/lib/hybrid-stack/templateRows.ts`
- Test: `frontend/src/lib/hybrid-stack/templateRows.test.ts`, `frontend/src/lib/hybrid-stack/items.test.ts`

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/hybrid-stack/templateRows.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { chooseTemplate, templateKey, unmetTemplate, withChosen, withRequired } from './templateRows';
import type { StackItem } from './types';

const t = (id: string, extra: Partial<StackItem> = {}): StackItem => ({
	id, kind: 'template', region: 'Liver', question: 'Septation?', why: '', sentences: ['The cyst is septated.', 'No septation.'],
	answered: false, yes: 'The cyst is septated.', no: 'No septation.', ...extra
});

describe('template rows', () => {
	it('Yes and No keep only the template sentence chosen', () => {
		expect(chooseTemplate(t('a'), 'yes').sentences).toEqual(['The cyst is septated.']);
		expect(chooseTemplate(t('a'), 'no').sentences).toEqual(['No septation.']);
	});
	it('the view shows an answered template row with its chosen sentence; other rows are untouched', () => {
		const finding: StackItem = { ...t('f'), kind: 'finding' };
		const out = withChosen([t('a'), finding], { a: chooseTemplate(t('a'), 'no'), f: { ...finding, sentences: ['x.'] } });
		expect(out[0].sentences).toEqual(['No septation.']);
		expect(out[1]).toBe(finding);
	});
	it('required statements are offered first, without repeats', () => {
		expect(withRequired({ Liver: ['The liver is normal.', 'No septation.'], Spleen: ['Normal spleen.'] }, { Liver: ['No septation'], Kidneys: ['No calculus.'] }))
			.toEqual({ Liver: ['No septation', 'The liver is normal.'], Kidneys: ['No calculus.'], Spleen: ['Normal spleen.'] });
	});
	it('answers to template rows a full review no longer returns are unmet; other rows are not', () => {
		const answered = { a: t('a'), b: t('b'), f: { ...t('f'), kind: 'finding' as const } };
		expect(unmetTemplate(answered, { items: [t('a')], capped: [] })).toEqual(['b']);
		expect(unmetTemplate(answered, { items: [], capped: [t('b')] })).toEqual(['a']);
	});
	it('the gate key changes with a chosen sentence and with the required statements', () => {
		const k = templateKey({ a: chooseTemplate(t('a'), 'yes') }, {});
		expect(templateKey({ a: chooseTemplate(t('a'), 'no') }, {})).not.toBe(k);
		expect(templateKey({ a: chooseTemplate(t('a'), 'yes') }, { Liver: ['No free fluid.'] })).not.toBe(k);
		expect(templateKey({ a: chooseTemplate(t('a'), 'yes'), f: { ...t('f'), kind: 'finding' } }, {})).toBe(k);
	});
});
```

Append inside the `describe('checklist rows', …)` block of `items.test.ts`:

```ts
	it('a template row left open counts as an unanswered check and never blocks', () => {
		const tpl = item('t', ['A.', 'B.'], { kind: 'template', yes: 'A.', no: 'B.' });
		expect(unansweredChecks([tpl], [], [])).toBe(1);
		expect(openCount([tpl], [], [])).toBe(0);
	});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run --project server src/lib/hybrid-stack/templateRows.test.ts src/lib/hybrid-stack/items.test.ts`
Expected: FAIL — `Failed to resolve import "./templateRows"`; `unansweredChecks` returns 0.

- [ ] **Step 3: Types and API**

In `hybrid-stack/types.ts`, replace the `StackItem` interface with:

```ts
export interface StackItem {
	id: string;
	kind: 'finding' | 'referral' | 'template';
	region: string;
	source_text?: string; // the dictated phrase that set a finding check off
	question: string;
	why: string;
	sentences: string[]; // still to be answered (at most 2); a template row: its Yes and No sentences
	answered: boolean; // the dictation answered every sentence: the row folds
	/** kind 'template' (a findings-triggered habit of the template): the sentence a Yes writes, and a No */
	yes?: string;
	no?: string;
}
```

and replace the `ItemsResult` line with:

```ts
export interface ItemsResult {
	items: StackItem[];
	capped: StackItem[];
	contradicted: string[];
	cached: boolean;
	ms: number;
	error: string | null;
	/** met template required statements, region -> sentences (offered in the assumed tray) */
	required?: Record<string, string[]>;
	/** the template trigger call failed: no template rows this review (what is on screen stays) */
	trigger_error?: string | null;
}
```

In `hybrid-stack/api.ts`, replace

```ts
	review?: boolean;
}) => post<ItemsResult>(token, 'items', body);
```

with

```ts
	review?: boolean;
	template_id?: string | null;
}) => post<ItemsResult>(token, 'items', body);
```

In `hybrid-stack/items.ts`, replace the body of `unansweredChecks` with:

```ts
	return items.filter((i) => i.kind !== 'referral' && waiting(i, tapped, removed, skipped)).length;
```

and its doc comment with `/** Finding checks and template rows left unanswered: they never block; nothing is stated for them. */`.

- [ ] **Step 4: The helpers** (`frontend/src/lib/hybrid-stack/templateRows.ts`)

```ts
// Findings-triggered template rows (spec 2026-10-13-findings-triggered-rows-design): pure helpers for the scratchpad.
// A template row asks the template's own question; Yes or No writes the template's own sentence; Not assessed writes
// nothing. Its required statements join the assumed tray.
import type { StackItem } from './types';

const norm = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

/** Yes or No on a template row: the answer record keeps only the sentence chosen (what Generate states). */
export function chooseTemplate(item: StackItem, which: 'yes' | 'no'): StackItem {
	const s = (which === 'yes' ? item.yes : item.no) ?? '';
	return { ...item, sentences: s ? [s] : [] };
}

/** The rows the view shows: an answered template row shows the sentence chosen, not both. */
export function withChosen(items: StackItem[], tapped: Record<string, StackItem>): StackItem[] {
	return items.map((i) => (i.kind === 'template' && tapped[i.id] ? tapped[i.id] : i));
}

/** The region normals offered to the assumed check: each region's met required statements first (never cut by the
 *  per-region cap), then the sheet's own, without repeats. */
export function withRequired(normals: Record<string, string[]>, required: Record<string, string[]>): Record<string, string[]> {
	const out: Record<string, string[]> = {};
	for (const r of [...Object.keys(required), ...Object.keys(normals)]) {
		if (out[r]) continue;
		const seen = new Set<string>();
		out[r] = [...(required[r] ?? []), ...(normals[r] ?? [])].filter((s) => {
			const k = norm(s);
			if (seen.has(k)) return false;
			seen.add(k);
			return true;
		});
	}
	return out;
}

/** Template rows answered (or skipped) whose condition a successful full review no longer meets: not in its reply.
 *  Their answers are dropped (an answer stands only while its condition is met). */
export function unmetTemplate(answered: Record<string, StackItem>, reply: { items: StackItem[]; capped: StackItem[] }): string[] {
	const live = new Set([...reply.items, ...reply.capped].map((r) => r.id));
	return Object.values(answered).filter((r) => r.kind === 'template' && !live.has(r.id)).map((r) => r.id);
}

/** The template rows' part of the gate key: each answered row's chosen sentence and the required statements met. */
export function templateKey(tapped: Record<string, StackItem>, required: Record<string, string[]>): string {
	const rows = Object.values(tapped).filter((r) => r.kind === 'template').map((r) => `${r.id}=${r.sentences.join(' ')}`).sort();
	return JSON.stringify([rows, required]);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run --project server src/lib/hybrid-stack`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/hybrid-stack/types.ts frontend/src/lib/hybrid-stack/api.ts frontend/src/lib/hybrid-stack/items.ts frontend/src/lib/hybrid-stack/items.test.ts frontend/src/lib/hybrid-stack/templateRows.ts frontend/src/lib/hybrid-stack/templateRows.test.ts
git commit -m "feat(scratchpad): template row types and pure helpers (answer, required statements, gate key)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 16: Generate statement and the template row in the view

**Files:**
- Modify: `frontend/src/lib/hybrid-stack/regionState.ts`
- Modify: `frontend/src/lib/hybrid-stack/HybridStackView.svelte`
- Test: `frontend/src/lib/hybrid-stack/regionState.test.ts`, `frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts`

- [ ] **Step 1: Write the failing tests**

Append inside the `describe` block that holds `answers only: …` in `regionState.test.ts`:

```ts
	it('a template answer is stated in its region; Not assessed states nothing', () => {
		const cyst = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'] })];
		const gate: GateRecord = {
			confirmed_at: 't', conclusion_text: '', conclusion_source: 'draft', assumed_normal: [], remainder_normal: [], dictated_normal: [],
			units_hash: 'h', capped: [], removed: [], assumed: {},
			items: [
				{ id: 't', kind: 'template', region: 'Liver', question: 'Septation?', sentences: ['No septation.'], answered_by: 'tap' },
				{ id: 'k', kind: 'template', region: 'Kidneys', question: 'Calculus?', sentences: ['No calculus.'], answered_by: 'tap' },
				{ id: 'n', kind: 'template', region: 'Spleen', question: 'Size?', sentences: [], answered_by: 'not_assessed' }
			]
		};
		const block = buildFindingsBlock(cyst, GROUPS, gate);
		expect(block).toContain('Liver: An 8 mm liver cyst. Answered by the radiologist: No septation.');
		expect(block).toContain('Kidneys: Answered by the radiologist: No calculus.');
		expect(block).not.toContain('Spleen');
	});
```

Append inside `describe('HybridStackView v2', …)` in `HybridStackView.svelte.test.ts`:

```ts
	it('a template row asks the template question: Yes / No write its sentence, Not assessed writes nothing', async () => {
		const props = { ...base(), onAnswerTemplate: vi.fn(), onSkip: vi.fn(), onAnswer: vi.fn() };
		const tpl = row('t', ['The cyst is septated.', 'No septation.'], {
			kind: 'template', question: 'Septation?', why: 'Your template asks this when a liver cyst is reported.',
			yes: 'The cyst is septated.', no: 'No septation.'
		});
		render(HybridStackView, { ...props, units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'] })], items: [tpl] });
		await expect.element(page.getByText('Septation?')).toBeInTheDocument();
		await page.getByRole('button', { name: 'No', exact: true }).click();
		expect(props.onAnswerTemplate).toHaveBeenCalledWith('t', 'no');
		await page.getByRole('button', { name: 'Yes', exact: true }).click();
		expect(props.onAnswerTemplate).toHaveBeenCalledWith('t', 'yes');
		await page.getByRole('button', { name: 'Not assessed' }).click();
		expect(props.onSkip).toHaveBeenCalledWith('t');
		expect(props.onAnswer).not.toHaveBeenCalled();
	});

	it('an answered template row shows the sentence chosen', async () => {
		render(HybridStackView, {
			...base(), units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'] })], tapped: ['t'],
			items: [row('t', ['No septation.'], { kind: 'template', question: 'Septation?', yes: 'The cyst is septated.', no: 'No septation.' })]
		});
		await expect.element(page.getByText('✓ No septation.')).toBeInTheDocument();
	});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack/regionState.test.ts src/lib/hybrid-stack/HybridStackView.svelte.test.ts`
Expected: FAIL — the Liver line lacks the answer for a template item… (`Kidneys` goes to the standalone line), and `Septation?` is not rendered (rows show `kind === 'finding'` only).

- [ ] **Step 3: Generate statement** (`regionState.ts`)

In `buildFindingsBlock`, replace

```ts
		if (groups.includes(it.region) && (dictatedRegion(it.region) || it.kind === 'finding')) add(it.region, `${ANSWERED} ${it.sentences.join(' ')}`);
```

with

```ts
		if (groups.includes(it.region) && (dictatedRegion(it.region) || it.kind !== 'referral')) add(it.region, `${ANSWERED} ${it.sentences.join(' ')}`);
```

- [ ] **Step 4: The view** (`HybridStackView.svelte`)

In the props destructuring, after `onAnswer = () => {},` add `onAnswerTemplate = () => {},`. In the props type, after the `onAnswer?: (id: string) => void;` line add:

```ts
		/** Yes or No on a template row: the template's own sentence for that answer is added. */
		onAnswerTemplate?: (id: string, which: 'yes' | 'no') => void;
```

Replace

```ts
	const rowsFor = (region: string) => items.filter((i) => i.kind === 'finding' && anchorRegion(i, units) === region);
```

with

```ts
	const rowsFor = (region: string) => items.filter((i) => i.kind !== 'referral' && anchorRegion(i, units) === region);
```

and

```ts
	const looseRows = $derived(items.filter((i) => i.kind === 'finding' && !covered.has(anchorRegion(i, units))));
```

with

```ts
	const looseRows = $derived(items.filter((i) => i.kind !== 'referral' && !covered.has(anchorRegion(i, units))));
```

In the `row` snippet, immediately before `{:else if listed.length && !actionsReady}`, add:

```svelte
	{:else if it.kind === 'template' && actionsReady}
		<!-- A template row (a findings-triggered habit): the template's own question. Yes / No add the template's own
		     sentence for that answer; Not assessed states nothing. -->
		<div class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border-l-2 border-amber-400/80 bg-amber-500/[0.07] px-2 py-1.5" data-row="template" transition:fade={{ duration: ms }}>
			{#if label}<span class="text-[10px] font-semibold uppercase tracking-wide text-amber-300/90">{label}</span>{/if}
			<span class="text-sm font-medium text-amber-100">{it.question}</span>
			{#if it.why}<span class="cursor-help text-xs text-gray-500" title={it.why} aria-label="Why: {it.why}">ⓘ</span>{/if}
			<span class="ml-auto flex gap-1">
				<button type="button" class="rounded-md border border-amber-300/40 bg-amber-400/15 px-2 py-0.5 text-xs font-medium text-amber-100 hover:bg-amber-400/25"
					title="Add: {it.yes}" onclick={() => onAnswerTemplate(it.id, 'yes')}>Yes</button>
				<button type="button" class="rounded-md border border-amber-300/40 bg-amber-400/15 px-2 py-0.5 text-xs font-medium text-amber-100 hover:bg-amber-400/25"
					title="Add: {it.no}" onclick={() => onAnswerTemplate(it.id, 'no')}>No</button>
				<button type="button" class="rounded-md px-2 py-0.5 text-xs text-gray-500 hover:text-gray-300" title="Nothing is stated"
					onclick={() => onSkip(it.id)}>Not assessed</button>
			</span>
		</div>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/hybrid-stack`
Expected: PASS (existing view and region tests unchanged).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/hybrid-stack/regionState.ts frontend/src/lib/hybrid-stack/regionState.test.ts frontend/src/lib/hybrid-stack/HybridStackView.svelte frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts
git commit -m "feat(scratchpad): template rows in their region with Yes / No / Not assessed; answers stated at Generate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 17: Wire the scratchpad; Phase 4 check and smoke

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`

- [ ] **Step 1: Import and state.** After the line `import { postAssumed, postChanged, … } from '$lib/hybrid-stack/api';` (`:41`) add:

```ts
	import { chooseTemplate, templateKey, unmetTemplate, withChosen, withRequired } from '$lib/hybrid-stack/templateRows';
```

After `let fixedReferrals: { question: string; region: string; sentences: string[] }[] | null = null;` (`:305`) add:

```ts
	let templateRequired: Record<string, string[]> = {}; // the template's required statements met at the last review
```

- [ ] **Step 2: View items and gate key.** Replace

```ts
	$: viewItems = [...stackItems, ...Object.values(tappedRows).filter((t) => !stackItems.some((i) => i.id === t.id) && !moreView.rows.some((c) => c.id === t.id))];
```

with

```ts
	$: viewItems = withChosen([...stackItems, ...Object.values(tappedRows).filter((t) => !stackItems.some((i) => i.id === t.id) && !moreView.rows.some((c) => c.id === t.id))], tappedRows);
```

and in the `gateKey` statement replace `JSON.stringify(confirmedAssumed)].join('\u0003');` with:

```ts
		JSON.stringify(confirmedAssumed), templateKey(tappedRows, templateRequired)].join('\u0003');
```

- [ ] **Step 3: The review sends the template and applies its result.** In `refreshItems`, replace

```ts
				tapped: Object.values(tappedRows).flatMap((r) => r.sentences), referrals: fixedReferrals, review });
```

with

```ts
				tapped: Object.values(tappedRows).flatMap((r) => r.sentences), referrals: fixedReferrals, review, template_id: stackTemplateId });
```

and replace

```ts
			if (review) reviewedAbnormal = abnormal;
```

with

```ts
			if (review) reviewedAbnormal = abnormal;
			if (review && !res.trigger_error) {
				// The template's habits for this dictation: its met required statements, and answers to rows whose condition
				// is no longer met dropped (a failed trigger changes nothing on screen).
				templateRequired = res.required ?? {};
				const skippedItems = Object.fromEntries(Object.entries(skippedRows).map(([k, v]) => [k, v.item]));
				const gone = new Set([...unmetTemplate(tappedRows, res), ...unmetTemplate(skippedItems, res)]);
				if (gone.size) {
					tappedRows = Object.fromEntries(Object.entries(tappedRows).filter(([k]) => !gone.has(k)));
					skippedRows = Object.fromEntries(Object.entries(skippedRows).filter(([k]) => !gone.has(k)));
				}
			}
```

- [ ] **Step 4: Skip, answer and voice.** In `skipRow`, replace

```ts
		skippedRows = { ...skippedRows, [id]: { item: it, how: it.kind === 'referral' ? 'not_assessed' : 'skip' } };
```

with

```ts
		skippedRows = { ...skippedRows, [id]: { item: it, how: it.kind === 'finding' ? 'skip' : 'not_assessed' } };
```

In `answerRow`, replace `		if (!it || !isOpenRow(id)) return;` with `		if (!it || it.kind === 'template' || !isOpenRow(id)) return; // a template row needs Yes or No`, and after the `answerRow` function add:

```ts
	/** Yes or No on a template row: the template's own sentence for that answer becomes the radiologist's answer. */
	function answerTemplateRow(id: string, which: 'yes' | 'no'): void {
		const it = findRow(id);
		if (!it || it.kind !== 'template' || !isOpenRow(id)) return;
		tappedRows = { ...tappedRows, [id]: chooseTemplate(it, which) };
		if (moreView.rows.some((c) => c.id === id) && !cappedTapped.includes(id)) cappedTapped = [...cappedTapped, id];
	}
```

In `openItemsForVoice`, replace `.filter((i) => isOpenRow(i.id))` with `.filter((i) => isOpenRow(i.id) && i.kind !== 'template')`.

- [ ] **Step 5: Required statements in the assumed check.** In `refreshAssumed`, replace

```ts
		if (!Object.keys(stackRegionNormals).length) return;
		const seq = ++assumedSeq;
		const snap = { offered: { ...stackRegionNormals }, dictation: verbatimNow, abnormal: [...regionView.abnormal], untouched: [...regionView.assumedNormal] };
		try {
			const res = await postAssumed($token, { dictation: snap.dictation, region_normals: stackRegionNormals, abnormal: snap.abnormal,
```

with

```ts
		const offered = withRequired(stackRegionNormals, templateRequired); // the template's met required statements first
		if (!Object.keys(offered).length) return;
		const seq = ++assumedSeq;
		const snap = { offered, dictation: verbatimNow, abnormal: [...regionView.abnormal], untouched: [...regionView.assumedNormal] };
		try {
			const res = await postAssumed($token, { dictation: snap.dictation, region_normals: offered, abnormal: snap.abnormal,
```

- [ ] **Step 6: Pass the handler to the view.** In the `<HybridStackView …>` props, replace `onAnswer={answerRow}` with `onAnswer={answerRow} onAnswerTemplate={answerTemplateRow}`.

- [ ] **Step 7: Run the checks**

Run: `cd frontend && npx vitest run && npm run check 2>&1 | tail -3`
Expected: the full suite at its baseline plus the new tests (the known `page.svelte.spec` h1 failure only); svelte-check no more than 1194 problems.

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: PASS.

- [ ] **Step 8: Smoke in the app** (the `run` skill; local backend and frontend). Create a template with two example reports that share a habit, confirm its card ("Ask every time") in the Rules step, save, open a scratchpad session on it, dictate a sentence that meets the condition, stop the mic: the template row appears in that region before any generic row; tap No; Confirm; Generate: the report states the NO sentence. Dictate a sentence that negates the finding: no template row. Record what was seen in the commit message body.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(scratchpad): ask a template's habits at the review; required statements in the assumed tray

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 5: the `habit` chat tag (requires item 4 built)

**Requires item 4 built.** This phase changes the chat-edit router's modules, which do not exist until the router plan (`/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router/docs/superpowers/plans/2026-10-13-chat-edit-router.md`) is built and merged into this branch's base. Every router module reaches the Rules step through its adapter, `chat_router_ledger.py`; this phase keeps that rule.

### Task 18: Verify the router; add the habit tag question

**Files:**
- Modify: `backend/src/rapid_reports_ai/chat_router_jev.py`
- Modify: `backend/tests/test_chat_router_jev.py`

- [ ] **Step 1: Verify the router names this phase uses**

```bash
cd backend && ls src/rapid_reports_ai/chat_router*.py && grep -n "^KINDS\|^QUESTIONS\|^OUTPUTS\|^_VALIDATORS\|^KIND_LABEL\|^def claim_for\|^def parse_change\|^VIEWS\|^_KIND\|^SYSTEM\|^WORK_KINDS\|^def entry\|^def check\|^def card\|^def structure\|^def paragraph_entries\|^def rekey_paragraph" src/rapid_reports_ai/chat_router*.py
```

Expected: the seven router modules exist and every name is found. If any is missing or renamed, stop and report the difference to the controller before changing anything (this phase is written against the approved plan, not built code).

- [ ] **Step 2: Write the failing test.** In `backend/tests/test_chat_router_jev.py`, replace the body of `test_the_seven_questions_are_the_specs` with:

```python
    assert J.KINDS == ("value", "concept", "fixed", "normal", "habit", "layout", "style", "misfit")
    assert all(J.QUESTIONS[k].startswith("Does the INSTRUCTION ask") for k in J.KINDS)
    assert "values every report must state" in J.QUESTIONS["value"]
    assert "does not belong in a report of this scan type" in J.QUESTIONS["misfit"]
    assert "only when a particular finding is reported" in J.QUESTIONS["habit"]
    assert (J.TAG_UNSURE, J.TAG_MIN, J.REQUIRES_MIN) == (0.35, 0.5, 0.5)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_jev.py -q`
Expected: FAIL on the `KINDS` tuple.

- [ ] **Step 4: Add the question** (`chat_router_jev.py`). Replace

```python
KINDS = ("value", "concept", "fixed", "normal", "layout", "style", "misfit")
```

with

```python
KINDS = ("value", "concept", "fixed", "normal", "habit", "layout", "style", "misfit")
```

and in `QUESTIONS`, after the `"normal"` entry add:

```python
    "habit": "Does the INSTRUCTION ask to add, change or stop a question or statement that reports make only when a "
             "particular finding is reported?",
```

- [ ] **Step 5: Run the router's Jev tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_jev.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_jev.py backend/tests/test_chat_router_jev.py
git commit -m "feat(chat-router): habit tag question

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 19: The habit change: adapter, validation, view, prompt, routing

**Files:**
- Modify: `backend/src/rapid_reports_ai/chat_router_ledger.py`, `chat_router_changes.py`, `chat_router_views.py`, `chat_router_calls.py`, `chat_router.py`
- Create: `backend/tests/test_chat_router_habit.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_habit.py`)

```python
"""The router's habit kind (findings-triggered rows spec, "Chat add and remove through the router")."""
from rapid_reports_ai import chat_router as R
from rapid_reports_ai import chat_router_calls as C
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import chat_router_views as V
from rapid_reports_ai import template_decisions as td
from tests.template_sheet_fixtures import ROUTER_SHEET

KEY = "Upper :: an alpha abnormality is reported"
TEXTS = {"question": "Extension beyond alpha?", "yes": "The abnormality extends beyond alpha.",
         "no": "No extension beyond alpha."}


def _ctx(instruction, ledger=None, confirmed=False):
    return CH.Ctx(ROUTER_SHEET, ledger or [], instruction, confirmed=confirmed)


def _ledger(mode="ask"):
    led, _ = td.set_decision([], "habit", KEY, {"mode": mode, **TEXTS}, source="creation", at="t")
    return led


def test_habit_has_an_output_a_view_and_a_prompt():
    assert "habit" in CH.OUTPUTS and "habit" in V.VIEWS and "habit" in C.SYSTEM
    assert "habit" in L.LEDGER_KINDS
    assert "Ignore every other part of the INSTRUCTION" in C.SYSTEM["habit"]


def test_removing_a_confirmed_habit_is_a_ledger_write_with_a_plain_claim():
    v = CH.validate("habit", CH.HabitChange(paragraph="upper", condition="an alpha abnormality is reported", to="removed"),
                    _ctx("stop asking about extension", _ledger()))
    assert v.action == "ledger" and v.key == KEY and v.choice == {"mode": "removed", **TEXTS}
    assert v.claim == "Upper: nothing is asked or stated when an alpha abnormality is reported."


def test_a_new_habit_with_wording_not_in_the_instruction_is_a_card():
    v = CH.validate("habit", CH.HabitChange(paragraph="Upper", condition="an alpha abnormality is reported", to="ask", **TEXTS),
                    _ctx("ask me about extension whenever there is an alpha abnormality"))
    assert v.action == "card" and v.card["kind"] == "habit" and v.card["key"] == KEY


def test_a_tapped_card_applies_and_an_unknown_paragraph_is_asked():
    ok = CH.validate("habit", CH.HabitChange(paragraph="Upper", condition="an alpha abnormality is reported", to="state", **TEXTS),
                     _ctx("", confirmed=True))
    assert ok.action == "ledger" and ok.choice["mode"] == "state"
    assert ok.claim == 'Upper: when an alpha abnormality is reported, reports state "No extension beyond alpha."'
    ask = CH.validate("habit", CH.HabitChange(paragraph="Nowhere", condition="an alpha abnormality is reported", to="ask", **TEXTS),
                      _ctx("x"))
    assert ask.action == "ask"
    bad = CH.validate("habit", CH.HabitChange(paragraph="Upper", condition="alpha is reported", to="ask", **TEXTS),
                      _ctx("", confirmed=True))
    assert bad.action == "reject"


def test_the_view_lists_findings_paragraphs_and_current_habits():
    view = V.view("habit", ROUTER_SHEET, _ledger())
    assert "FINDINGS PARAGRAPHS: Upper, Lower" in view
    assert '- Upper, when an alpha abnormality is reported: asks "Extension beyond alpha?"' in view


def test_a_paragraph_rename_keeps_its_habits():
    led, _ = td.set_decision(_ledger(), "normal", L.normal_key("Upper", "alpha"), {"text": "Alpha is normal."},
                             source="creation", at="t")
    led, _ = td.set_decision(led, "habit", "Lower :: a gamma abnormality is reported",
                             {"mode": "state", "no": "No gamma extension."}, source="creation", at="t")
    assert [e["kind"] for e in L.paragraph_entries(led, "upper")] == ["habit", "normal"]
    moved = L.rekey_paragraph(led, "Upper", "Top")
    assert [e["key"] for e in moved] == ["Top :: an alpha abnormality is reported", L.normal_key("Top", "alpha"),
                                         "Lower :: a gamma abnormality is reported"]
    assert [e["choice"] for e in moved] == [e["choice"] for e in led]
    assert td.clean_ledger(moved) == moved
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_habit.py -q`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.chat_router_changes' has no attribute 'HabitChange'`.

- [ ] **Step 3: The adapter** (`chat_router_ledger.py`)

After `negative_key` add:

```python
def habit_key(paragraph: str, condition: str) -> str:
    return td.habit_key(paragraph, condition)


def habit_label(key: str) -> Tuple[str, str]:
    """(paragraph, condition) of a habit key."""
    try:
        return td.split_habit_key(key)
    except td.DecisionError as e:
        raise Rejected(str(e)) from e
```

Replace `paragraph_entries` and `rekey_paragraph` with:

```python
def paragraph_entries(ledger: List[dict], paragraph: str) -> List[dict]:
    out = []
    for e in ledger or []:
        try:
            if e.get("kind") == "normal":
                para, _, _ = td.split_normal_key(e["key"])
            elif e.get("kind") == "habit":
                para, _ = td.split_habit_key(e["key"])
            else:
                continue
        except td.DecisionError:
            continue
        if _n(para) == _n(paragraph):
            out.append(e)
    return out


def rekey_paragraph(ledger: List[dict], old: str, new: str) -> List[dict]:
    moved = paragraph_entries(ledger, old)
    out = []
    for e in ledger or []:
        if any(e is m for m in moved):
            if e["kind"] == "habit":
                _, cond = td.split_habit_key(e["key"])
                e = {**e, "key": td.habit_key(new, cond)}
            else:
                _, label, neg = td.split_normal_key(e["key"])
                e = {**e, "key": td.negative_key(new, label) if neg else td.normal_key(new, label)}
        out.append(e)
    return out
```

- [ ] **Step 4: The change and its validator** (`chat_router_changes.py`)

After `class FixedChange` (and its siblings) add:

```python
class HabitChange(BaseModel):
    paragraph: str
    condition: str
    to: Literal["ask", "state", "removed"]
    question: str = ""
    yes: str = ""
    no: str = ""
    sure: bool = True


class HabitOut(BaseModel):
    changes: List[HabitChange] = []
    question: str = ""
```

Replace the `OUTPUTS` assignment with:

```python
OUTPUTS = {"value": ValueOut, "concept": ConceptOut, "fixed": FixedOut, "normal": NormalOut, "habit": HabitOut,
           "layout": LayoutOut, "style": StyleOut}
```

In `KIND_LABEL` add `"habit": "the questions and statements a finding sets off",`.

In `claim_for`, before the final normal-key lines (`para, label = L.normal_label(key)`), add:

```python
    if kind == "habit":
        para, cond = L.habit_label(key)
        if choice["mode"] == "ask":
            return f'{para}: when {cond}, the scratchpad asks "{choice["question"]}"'
        if choice["mode"] == "state":
            return f'{para}: when {cond}, reports state "{choice["no"]}"'
        return f"{para}: nothing is asked or stated when {cond}."
```

Before `_VALIDATORS` add:

```python
def _habit(c: HabitChange, ctx: Ctx) -> Verdict:
    """A habit change (findings-triggered rows spec): a removal of a confirmed habit is applied; new wording passes only
    when the instruction holds it word for word, else it is a card (the radiologist taps it)."""
    st = L.structure(ctx.sheet)
    findings = {s.name for s in st.sections if s.role == "findings"}
    para = next((p.name for p in st.paragraphs if p.section in findings and sh.norm(p.name) == sh.norm(c.paragraph)), None)
    if para is None:
        names = ", ".join(p.name for p in st.paragraphs if p.section in findings)
        return _ask("habit", f'Which paragraph should this go in: {names}?')
    key = L.habit_key(para, c.condition)
    old = L.entry(ctx.ledger, "habit", key)
    base = dict(old["choice"]) if old else {"question": "", "yes": "", "no": ""}
    choice = {"mode": c.to, "question": c.question.strip() or base.get("question", ""),
              "yes": c.yes.strip() or base.get("yes", ""), "no": c.no.strip() or base.get("no", "")}
    key, choice = L.check("habit", key, choice)
    texts = [t for t, k in ((c.question, "question"), (c.yes, "yes"), (c.no, "no"))
             if t.strip() and norm_key(t) != norm_key(base.get(k, ""))]
    if old is None:
        texts.append(c.condition)
    return _gate(Verdict("habit", "ledger", key=key, choice=choice, claim=claim_for("habit", key, choice)),
                 texts, c.sure, ctx)
```

Replace `_VALIDATORS = {…}` with:

```python
_VALIDATORS = {"value": _value, "concept": _concept, "fixed": _fixed, "normal": _normal, "habit": _habit,
               "layout": _layout}
```

and in `parse_change` add `"habit": HabitChange,` to the model map.

- [ ] **Step 5: The view** (`chat_router_views.py`). Before `VIEWS = {…}` add:

```python
def _habits(sheet: str, ledger: List[dict]) -> str:
    st = L.structure(sheet)
    findings = {s.name for s in st.sections if s.role == "findings"}
    out = ["FINDINGS PARAGRAPHS: " + ", ".join(p.name for p in st.paragraphs if p.section in findings),
           "HABITS (asked or stated only when their finding is reported):"]
    for e in L.clean(ledger):
        if e["kind"] != "habit":
            continue
        para, cond = L.habit_label(e["key"])
        c = e["choice"]
        what = {"ask": f'asks "{c["question"]}" (yes: "{c["yes"]}"; no: "{c["no"]}")',
                "state": f'states "{c["no"]}"'}.get(c["mode"], "not used")
        out.append(f"- {para}, when {cond}: {what}")
    return "\n".join(out)
```

and replace the `VIEWS` assignment with:

```python
VIEWS = {"value": _values, "concept": _concepts, "fixed": _fixed, "normal": _normals, "habit": _habits,
         "layout": _layout, "style": _style}
```

(The test expects `'- Upper, when an alpha abnormality is reported: asks "Extension beyond alpha?"'` as a prefix of that line: the view line continues with the two sentences.)

- [ ] **Step 6: The prompt** (`chat_router_calls.py`). In `_KIND`, after the `"normal"` entry add:

```python
    "habit": (
        "the questions and statements reports make only when a particular finding is reported",
        'Each change names the "paragraph" (a findings paragraph from CURRENT) and the "condition": the finding that '
        'sets it off, as a statement naming the finding in at least two words and ending "is reported". "to": "ask" '
        '(the scratchpad asks "question" every time the condition is met; "yes" and "no" are the sentences each '
        'answer writes), "state" (reports always state "no" when the condition is met) or "removed" (nothing is asked '
        'or stated). To change or remove an existing one, copy its paragraph and condition exactly from CURRENT and '
        'leave the wording you keep empty.'),
```

- [ ] **Step 7: Not routed yet.** `chat_router.WORK_KINDS` is left unchanged here: Task 20 adds `"habit"` only after the tagging lab has reported the habit-vs-normal overlap and the habit cases (review fix, 2026-10-13).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_habit.py tests/test_chat_router_calls.py tests/test_chat_router_changes.py tests/test_chat_router_views.py tests/test_chat_router_ledger.py tests/test_chat_router.py -q`
Expected: PASS (`test_prompts_are_case_agnostic_and_scoped` also covers the habit prompt; `set(C.SYSTEM) == set(CH.OUTPUTS)` holds).

- [ ] **Step 9: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_ledger.py backend/src/rapid_reports_ai/chat_router_changes.py backend/src/rapid_reports_ai/chat_router_views.py backend/src/rapid_reports_ai/chat_router_calls.py backend/src/rapid_reports_ai/chat_router.py backend/tests/test_chat_router_habit.py
git commit -m "feat(chat-router): add, change or remove a habit through the router

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 20: The router lab learns the habit kind, reports the habit-vs-normal overlap, then routes it; final check

A habit ("when <finding>, always state …") and a normal ("always state … is normal") are close in wording. The tag lab reports how often Jev confuses them, on habit cases added for that purpose, before the router acts on the habit tag.

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/chat_router_lab.py` (its kinds; a `confusion` table)
- Modify: `backend/src/rapid_reports_ai/chat_router.py` (`WORK_KINDS`, Step 6 only)
- Modify: `backend/tests/test_chat_router_lab.py` (the local `KINDS`), `backend/tests/test_chat_router_habit.py`

- [ ] **Step 1: Write the failing tests.** In `backend/tests/test_chat_router_lab.py` replace

```python
KINDS = ("value", "concept", "fixed", "normal", "layout", "style", "misfit")
```

with

```python
KINDS = ("value", "concept", "fixed", "normal", "habit", "layout", "style", "misfit")
```

and append:

```python
def test_confusion_counts_habit_and_normal_cross_tags():
    items = [_item(1, habit=1), _item(2, normal=1), _item(3, habit=1, normal=1), _item(4), _item(5, normal=1)]
    scores = {"i1": {"habit": 0.9, "normal": 0.6}, "i2": {"habit": 0.2, "normal": 0.8},
              "i3": {"habit": 0.9, "normal": 0.9}, "i4": {}, "i5": {"habit": 0.7, "normal": 0.3}}
    assert lab.confusion(items, scores) == {"habit_as_habit": 1, "habit_as_normal": 1,
                                            "normal_as_normal": 1, "normal_as_habit": 1, "n": 3}
    md = lab.confusion_report(items, scores, 0.5)
    assert md.startswith("## Habit vs normal (TAG_MIN 0.5)") and "habit" in md and "normal" in md
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_lab.py -q`
Expected: FAIL with `AttributeError: module … has no attribute 'confusion'` (and, where the lab keeps its own kinds tuple, on the missing `habit` label).

- [ ] **Step 3: Implement** (`scripts/chat_router_lab.py`)

Replace every kinds tuple the script defines itself with `J.KINDS` (importing `from rapid_reports_ai import chat_router_jev as J` if the script does not already). Then, after the script's `prf` function, add:

```python
def confusion(items: List[dict], scores: Dict[str, Dict[str, float]], a: str = "habit", b: str = "normal",
              thr: float = 0.5) -> Dict[str, int]:
    """Items labelled exactly one of a / b: how often Jev tags each as its own kind and as the other (the
    habit-vs-normal overlap, findings-triggered rows plan Task 20). Items labelled both or neither are left out."""
    out = {f"{a}_as_{a}": 0, f"{a}_as_{b}": 0, f"{b}_as_{b}": 0, f"{b}_as_{a}": 0, "n": 0}
    for it in items:
        lab_, sc = it.get("labels") or {}, scores.get(it["id"])
        if sc is None or bool(lab_.get(a)) == bool(lab_.get(b)):
            continue
        gold = a if lab_.get(a) else b
        other = b if gold == a else a
        out["n"] += 1
        out[f"{gold}_as_{gold}"] += sc.get(gold, 0.0) >= thr
        out[f"{gold}_as_{other}"] += sc.get(other, 0.0) >= thr
    return out


def confusion_report(items: List[dict], scores: Dict[str, Dict[str, float]], thr: float) -> str:
    c = confusion(items, scores, thr=thr)
    return (f"## Habit vs normal (TAG_MIN {thr})\n"
            + md_table(["labelled", "tagged as itself", "tagged as the other"],
                       [["habit", c["habit_as_habit"], c["habit_as_normal"]],
                        ["normal", c["normal_as_normal"], c["normal_as_habit"]]]))
```

In the tag-stage report function (find it by the line that builds `md_table(["kind", "labelled yes", "labelled no"], …)`), append `confusion_report(<that function's items>, <its per-item tag scores>, J.TAG_MIN)` to the parts it writes, using the same item list and score map that function already passes to its per-kind table. `md_table`, `List` and `Dict` already exist in the script (the router plan's Task 12); if `md_table` is named differently there, use that name.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_lab.py -q`
Expected: PASS.

- [ ] **Step 5: Habit cases, relabel, run the tag lab (controller).** The lab's loader refuses items without a label for every kind. Dispatch one Opus subagent: "In `~/Code/rr-template-conversion-private/synthetic/chat_router/`, add `"habit": 0 or 1` to the `labels` of every existing item (1 only when the instruction asks to add, change or stop a question or statement made only when a particular finding is reported). Then write 30 new items in the same format on the existing sheets: 6 add a habit, 6 change one, 6 remove one, 2 mix a habit with another kind, and 10 near misses that are normals, not habits (an instruction to always state that a structure is normal, or to reword a normal line, with no triggering finding), labelled `normal: 1, habit: 0`. Never edit the repo." Run the tag stage once, as the router plan's Task 14 describes; its report now carries the habit row and the habit-vs-normal table. Tell Hassan the report path; he decides whether the habit tag is used.

- [ ] **Step 6: Route the kind (after Hassan's go-ahead on Step 5).** In `chat_router.py` replace

```python
WORK_KINDS = ("value", "concept", "fixed", "normal", "layout", "style")
```

with

```python
WORK_KINDS = ("value", "concept", "fixed", "normal", "habit", "layout", "style")
```

and append to `backend/tests/test_chat_router_habit.py`:

```python
def test_habit_is_routed():
    assert "habit" in R.WORK_KINDS
```

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_habit.py tests/test_chat_router.py -q`
Expected: PASS.

- [ ] **Step 7: Final suites**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: PASS.

Run: `cd frontend && npx vitest run && npm run check 2>&1 | tail -3`
Expected: the Task 0 vitest baseline plus the new tests; svelte-check no more problems than the Task 0 baseline.

- [ ] **Step 8: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/chat_router_lab.py backend/src/rapid_reports_ai/chat_router.py backend/tests/test_chat_router_lab.py backend/tests/test_chat_router_habit.py
git commit -m "feat(chat-router): habit kind in the tagging lab with the habit-vs-normal table; habit routed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

## Spec coverage

| Spec item | Task |
|---|---|
| Template rows only; guideline cards untouched | whole plan (no copilot change) |
| Two shapes: required statement (assumed tray), habit question (Yes / No / Not assessed) | 1, 2, 13, 16, 17 |
| Proposed with evidence in ≥2 reports, with quotes; confirmed on a Rules-step card | 7, 11, 12 |
| Chat add / remove through the router; a paragraph rename keeps habits | 18–20 |
| Hassan H1: triggers read the dictation and scan type only | 6, 13 |
| Hassan H2: below `TRIGGER_MIN` is silent; the band is reported | 6, 8, 10 |
| Hassan H3: a habit line with no entry is inactive and asked on a card, never stripped | 4, 5, 6, 14 |
| Template rows first within the caps (2 per region, 4 in all); "N more checks" | 13 |
| Grammar forms; other findings forms still NOT_LEAN; STRUCTURE_VERSION bumped | 1, 2 |
| Ledger kind `habit` (`paragraph :: condition`; ask / state / removed) | 3, 4 |
| Trigger at the review hook, one Jev noul per distinct condition, threshold | 6, 13, 14, 17 |
| An answered row stays answered until its condition stops being met | 15, 17 |
| Already answered: stated check folds the row | 13 |
| Generate: answers as "Answered by the radiologist:", required as assumed lines, removed as DO NOT ASSERT | 2, 5b, 16, 17 |
| No habit line reaches the generator on the straight path either (re-review) | 5b |
| Failure table (trigger fails, stated check fails, no habits, lint rejects a habit) | 4, 6, 13, 17 (a habit the grammar refuses is `failed` and `unmatched` in `apply_ledger`, so the Rules step's existing `ledger_unmatched` path shows it as a card at the next review) |
| Lab first: proposal lab, trigger lab, held-out real set, reported | 8–10 |
| Unit and frontend tests listed in the spec | 1–4, 13, 15, 16 |
