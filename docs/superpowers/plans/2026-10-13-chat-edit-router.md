# Chat-Edit Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under this plan, code applies a refine-chat instruction that changes a template's rules. It goes through the Rules step's decision ledger, the same way a card tap does. A style instruction is applied by a lightweight call that can edit prose only. No model rewrites the whole sheet.

**Architecture:**
1. One Jev call tags the instruction with seven yes/no questions.
2. One targeted Qwen call runs for each tagged kind, in parallel. Each call returns structured changes, or for style, edited prose blocks.
3. Code validates every change and then either applies it, turns it into a one-tap card or asks a question. Rule kinds are written through the ledger. Layout and new unit lines are written by small, lint-guarded code edits.
4. The save function (origin "chat") vets the result and applies the ledger last.

Every router module reaches the Rules step through one adapter, `chat_router_ledger.py`, so renames there cost one edit. If the Jev tag call fails, the turn falls back to today's whole-sheet refine.

**Tech Stack:** Python 3 / FastAPI / pydantic-ai (`_run_agent_with_model`), Jev (`jev_client.jev_post`, noul answers), pytest (asyncio auto), Alembic, SvelteKit + Svelte 5, vitest (server and browser projects).

**Spec:** `docs/superpowers/specs/2026-10-13-chat-edit-router-design.md` (all of it).

---

## Where and how

- Worktree: `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router`, branch `feat/chat-router`. The branch starts from `feat/rules-step` at 591a1549. Never push, never `git stash`, never touch another worktree.
- **Dependency.** This plan executes **after** the Rules-step plan (`docs/superpowers/plans/2026-10-13-rules-step.md`) is implemented on this branch's base. Before Task 1, merge or rebase onto the implemented `feat/rules-step`. Then confirm that these exist: `backend/src/rapid_reports_ai/template_decisions.py`, `template_ledger_apply.py`, `template_rules_cards.py`, `vet_sheet(..., ledger=)`, `frontend/src/lib/template-rules/{types.ts,cards.ts}`, and the `decisions` field on `SkillSheetRefineRequest`. Check with:

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router && ls backend/src/rapid_reports_ai/template_decisions.py backend/src/rapid_reports_ai/template_ledger_apply.py backend/src/rapid_reports_ai/template_rules_cards.py frontend/src/lib/template-rules/cards.ts && grep -n "ledger: Optional" backend/src/rapid_reports_ai/template_sheet_save.py && grep -n "decisions: Optional" backend/src/rapid_reports_ai/main.py | head -3
```

Expected: four paths, one `vet_sheet` line, at least one `decisions: Optional` line. If anything is missing, stop and tell the controller.
- Backend commands run from `backend/`: `.venv/bin/python -m pytest <path> -q`. Full suite: `.venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`. Record the post-Rules-step baseline count before Task 1.
- Frontend commands run from `frontend/`: `npx vitest run --project server <path>` for `.test.ts`, `npx vitest run --project client <path>` for `.svelte.test.ts`, and `npx vitest run` for the full suite. The baseline has one known failure, the `page.svelte.spec` h1 test. `npm run check` must not raise the svelte-check problem count.
- Commit after every task with these trailer lines:

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit
```

- Lab data lives only in `~/Code/rr-template-conversion-private/synthetic/chat_router/`, never in the repo. Seeds: `~/Code/rr-template-conversion-private/data_all.json` (31 templates, `templates[i].skill_sheet`, `scan_type`) and the curated sheets `~/Code/rr-template-conversion-private/final/<slug>.final.md` (31). **No stored refine chat turns exist locally** (searched `rr-template-conversion-private` and `docs/`). Task 13 pulls any production `template_chat_turns` rows through Metabase into the private folder. Those rows are the real held-out set, and an empty pull is reported as such.

## Facts this plan relies on (router base checked at 591a1549; Rules-step code checked at 68493ba9)

- `/skill-sheet/refine` is `main.skill_sheet_refine_endpoint` (`backend/src/rapid_reports_ai/main.py:2688-2765`), with request `SkillSheetRefineRequest` (`main.py:746-751`) and `SkillSheetRejectionContext` (`main.py:742-744`). It needs a Cerebras key (`:2704-2706`) and calls `TemplateManager.refine_skill_sheet` (`:2714-2720`). It vets the rewrite with `tsave.vet_sheet(..., origin="chat", previous=request.skill_sheet)` (`:2730`), maps refused / unchanged / saved to a reply (`:2732-2746`), and records the turn when `template_id` is set (`:2747-2757`). Rules-step Task 10 adds `decisions` to the request and `ledger=` to the vet call.
- `TemplateManager.refine_skill_sheet` (`backend/src/rapid_reports_ai/template_manager.py:3630-3720+`) runs a single whole-sheet rewrite on `MODEL_CONFIG["SKILL_SHEET_REFINER"]` (`qwen-3.8-27b` on Cerebras, `enhancement_utils.py:150,173`) and returns `{skill_sheet, response, behavioral_claim}`. Its `rejection_context` is `{original_instruction, rejected_claim}`. This plan keeps it unchanged as the fallback.
- `template_chat_turns.record_turn(db, template_id, instruction, response, applied, sheet_before, sheet_after)` (`backend/src/rapid_reports_ai/template_chat_turns.py:26-37`) scrubs with `template_examples.scrub` and never raises. The `TemplateChatTurn` model (`database/models.py:942-952`) has no routing field. The table is created in migration `20261013090000_template_evidence.py` (the head at 591a1549). `JSONBType` is the JSON column type used in `models.py:415,926`.
- The save function: `template_sheet_save.vet_sheet(sheet, origin, previous="", ledger=None)` after Rules Task 8. Its `VetOutcome` gains `ledger`, `ledger_changes`, `ledger_unmatched`, `ledger_drift` and `stale_quotes`. For origin "chat" with a changed sheet, `reconcile_chat` folds sheet changes to decided items back into the ledger. A refused save returns the previous sheet and the ledger it was given. `_vet` may call the repair model (`template_sheet_save.py:163-176`).
- Jev: `jev_client.jev_post(body, api_key, timeout_s, transport)` (`jev_client.py:65-76`), `JEV_MODEL` pinned at `jev-1.13` (`:25`). The several-questions-in-one-call pattern is `hybrid_stack/jev_stack.py:106-131`: `{"model", "state", "questions": {id: {"type": "noul", "instructions"}}}`, with answers read as `answers[id]["noul"]`. Tests use `httpx.MockTransport`.
- The Qwen structured call with a gpt-oss retry follows `hybrid_stack/items.py:136-158` and Rules Task 14: `_run_agent_with_model(model_name, output_type, system_prompt, user_prompt, api_key="", model_settings)` inside `asyncio.wait_for`, falling back to `MODEL_CONFIG["STACK_REVIEW_FALLBACK"]` (`openai/gpt-oss-120b` on Groq). Tests patch `rapid_reports_ai.enhancement_utils._run_agent_with_model`.
- Grammar: `template_sheet_grammar.KEYWORDS` (`:83-84`) are the unit keywords. `paragraph_heading(title)` (`:241-255`) parses `Paragraph: <name> (<SECTION>) [| header: "…"]`. `_undecorate` (`:304-308`). `parse_sheet(sheet, mode="template").errors` lists `LintError(text, reason)`. `FREE_PROSE_SECTIONS` (`:221-222`). `ROLES` (`:91`). `### ` headings are prose (`:158`). The sheet title is `# Skill Sheet: <scan type>` (all 31 curated sheets).
- **The behavioral_claim verification loop is in `SkillSheetCreator.svelte`, not in `TemplateRefinePanel.svelte`.** Creator: `rejectTurn` (`:384-406`) restores `preMutationSkillSheet`, and `sendAnswer` (`:421-490`) builds `rejection_context` from the last rejected assistant turn and posts `/skill-sheet/refine`. The pending card renders "Not quite" / "Looks right" (`:1012-1080`). Rules Task 25 adds `preMutationDecisions`. `TemplateRefinePanel.svelte` (`:57-85`) has no reject loop. The Rules-step plan's risk 4 hands that loop to this plan.
- **Rules-step ledger API, verified in the code on `feat/rules-step` at 68493ba9** (`.claude/worktrees/rules-step/backend/src/rapid_reports_ai/`):
  - `template_decisions.py`: `set_decision(ledger, kind, key, choice, *, source, by="radiologist", at=None) -> (ledger, Change|None)` (`:223`; refuses a FIXED key a concept owns, via `concept_texts` `:244`); `rekey_decision(...)` (`:250`, a reworded line keeps its choice); `remove_decision` (`:270`); `undo_change(ledger, change)` (`:276`; restores `change["old"]`, the whole old entry, or removes a new one); `find`, `validate` (`:166`), `clean_ledger` (`:346`), `describe_change` (`:334`, which also names a rekey), `concept_of_condition` (`:112`).
  - A concept choice is `{use, default, when_met, condition, dictated}`. "Whichever is dictated" is `use: False, dictated: True`, with the wording blanked. A used concept needs `condition` to be one of `CONCEPTS[name].conditions`, auto-filled when there is exactly one. Contrast has two (`states`: `given` / `not_given`), and `validate` raises without one. The Rules step asks "Is contrast usually given?" when the examples show no clear majority.
  - `template_ledger_apply.py`: `observe(st, kind, key)` (`:407`, which reads a concept from the rule carrying its standard condition: REPLACE / SUPPRESS / USE) and `apply_ledger(sheet, ledger, before="")` (`:359`). `reconcile_chat` (`:466`) folds a reworded concept default into the ledger as the new default (8bc22083). It keeps, and cards, a rewrite that drops a whole list or concept unasked (`_wholesale`).
  - `template_rules_cards.py`: `card_for_change(kind, key, proposed)` (`:106`). Card shape: `{id, kind, step, title, evidence, ledger_kind, key, choices: [{id, label, choice|None}], selected, rank, wording?}`.
  - `template_sheet_save.VetOutcome` has `ledger`, `ledger_changes`, `ledger_cards`, `ledger_unmatched` and `ledger_drift` (`:69-73`).
  - `/apply-decisions` refuses source "chat". **The value list:** once the ledger holds any value entry, it owns the whole LIST_MISSING list.
  - Only `chat_router_ledger` imports these modules. This plan adds one thing to the ledger: `td.ROUTES` and a kept `route` field (D-R2, Task 1).
- `backend/tests/conftest.py` creates `TemplateChatTurn.__table__` from metadata (`:41,69`). Fixtures: `client`, `auth_headers`, `guided_template`, `db_session`. `pytest` runs with `asyncio_mode = "auto"` (`pyproject.toml:53`). The case-agnostic word list lives in `tests/test_template_sheet_lab_prompts.py:3-7` (`CLINICAL`).
- `main.py` already imports a module named `chat_edits` (`:93`). This plan's modules are all prefixed `chat_router_` to avoid confusion.

## Decisions this plan makes where the spec is open

1. **Kill switch, default OFF (Hassan, D-R3).** The router runs only when `RR_CHAT_ROUTER=1` and `OPENROUTER_API_KEY` is set. Otherwise every turn takes today's path. Hassan switches it on after reading the tagging lab. Tests pin `RR_CHAT_ROUTER=0` through an autouse fixture.
2. **Superseded 2026-10-13 (Hassan, after the design consult): no unsure band.** Only a tag at or above `TAG_MIN` (0.5) routes. `TAG_UNSURE` and the `llm_unsure` mark are removed: nothing stored the mark, so the ledger keeps no `route` field. When nothing tags at 0.5, the turn takes today's whole-sheet refine (`Fallback("no_tag")`) for now. Misfit (the lab's misfit_B wording) still blocks at 0.5. The fixed, misfit, value and requires questions are the wording lab's fixed_B, misfit_B, value_A and requires_A. The text below is kept for the record.
   *(Old, superseded)* **Tag bands (Hassan, D-R2).** A kind at or above `TAG_MIN` (0.5) is worked. A kind from `TAG_UNSURE` (0.35) up to `TAG_MIN` is also sent to its targeted call, which decides; there is no card for the band itself. Its changes go through the same code validation and are applied or not. Each applied change is marked `route: "llm_unsure"`: on the ledger entry (`td.ROUTES`, kept by `clean_ledger`), on the turn's undo record, and in the chat-turn `routing` evidence. The labs report how often the band occurs, and how often its decisions are wrong (e2e) or later undone (production). Below 0.35 the kind is ignored. A `misfit` yes, or no kind at 0.35 or above, gives no change and a question that names the scan type (from the sheet title).
3. **Wording rule.** New wording is accepted as given only when it appears in the instruction word for word. The match ignores case, spacing, quote marks and a final full stop. Wording already printed in the sheet is not new: a concept default that copies an existing FIXED sentence passes. Anything else becomes a card prefilled with the proposed wording. When a call claimed `sure` but its wording is not in the instruction, the evidence counts it as `invented`.
4. **Allowed slots** are `{study}`, `{date}` and any `{…}` slot already present in the sheet. Normal wording takes no slots (the ledger enforces this). A change with any other slot is rejected with a reply line.
5. **Two card shapes** (used for invented wording, a call's own `sure: false`, and the save function's cards). Ledger kinds use the Rules step's card (`trc.card_for_change`, prefilled, nothing pre-selected). Changes with no ledger card (layout, a new FIXED line, a new normal or negative line, a FIXED rewording) use a router **proposal card**: `{id, kind: "proposal", title, apply}`. Tapping Apply runs the stored change through the same code (the wording and `sure` checks are skipped, because the radiologist confirmed it).
6. **Rewording a FIXED line, and adding a FIXED, NORMAL or NEGATIVE line,** are code edits of one sheet line, not ledger writes. The ledger has no "insert" for fixed lines or normals (those entries report as unmatched). The edit is lint-guarded. A new line is then also recorded as a decision (source "chat"). A reworded FIXED line has its entry moved by `td.rekey_decision`, which is checked during validation so a clash becomes a reply, not a broken turn. **A FIXED edit on a line a concept owns** (`td.concept_texts(ledger)`, or the target / wording of a standard-condition rule) is re-routed to the concept kind:
   - a reword becomes the concept's new default or when-met wording (the path the Rules step uses at 8bc22083);
   - "only when dictated" becomes the concept's `dictated` state;
   - a removal blanks that wording, or sets the concept to not used when it was the concept's only wording.
7. **Layout operations** are rename, move, remove and add, for a paragraph or for a section. A section rename changes its printed heading; the SECTION name used in paragraph headings stays. Removing the only findings or impression section is refused. A new findings section or paragraph needs the structures it reports (COVERS), or the grammar check refuses it. Section names are shown to the model in Title Case and matched back case-insensitively (Cerebras Qwen corrupts upper-case words; see memory `reference_cerebras_uppercase_corruption`).
8. **Order of application within a turn:** the style splice runs first, on the sheet the call saw, so the block ids stay valid. Then come the layout edits, then the unit edits, then the ledger writes. Ledger keys follow a paragraph rename or removal.
9. **Rule-in-disguise.** Each new or changed prose line is asked "Does this LINE require the report to state something?" in one Jev call per line, in parallel. A line at or above `REQUIRES_MIN` (0.5) is dropped from the style edit and re-routed: the normal and fixed calls get `Every report should state: "<line>"`, and their change is always carded, because its wording is the model's. When neither call proposes a change, the reply asks where the line belongs. If the requires call fails, the style part is not applied and the reply asks the radiologist to try again.
10. **Undo is per change, through the backend, wrapping `td.undo_change`** (`POST /api/templates/skill-sheet/refine/undo`). A ledger write is reversed only if its entry still holds the turn's value. Dropped entries sent back by the client are re-validated (`L.restore` → `L.check`). A code edit runs its stored inverse operations. A style block is restored only if its edited text is still present. A part that a later turn changed is left alone, and the reply says so. Rejecting an older turn therefore no longer clobbers later turns. The creator uses it for router turns and keeps the snapshot restore for today's path. The refine panel gains a one-tap **Undo** on router turns that applied a change.
11. **Card answers** go to `POST /api/templates/skill-sheet/refine/card` and are written with source "chat". A card answer appends a plain assistant message: a tap is the radiologist's own choice, so it has no verification banner.
12. **Evidence:** `template_chat_turns.routing` (JSON, new migration). It holds the tags, each change's verdict (kind, action, key or op, route, invented, reason, detail), the number applied, the cards, the failed kinds, the disguise scores, refused, ms and the version. It is scrubbed with `template_examples.scrub` and capped at 20 000 characters. Undo and card answers are recorded as turns too (instruction `[undo] …` / `[card] …`, routing route `undo` / `card`).
13. **Explicit removals are applied (Hassan, D-R1).** "Stop listing <value>" and "never mention comparison" are ledger writes like any other. The reply names the change ("This changes something you confirmed: …", from `td.describe_change`), and the turn has a one-tap Undo. Only an implicit whole-item removal, where a rewrite drops a whole list or concept unasked, becomes a card. The save function does this already (`ledger_cards`), and the router passes those cards on.
14. **`applied` means something changed.** A turn is `applied: true` only when the saved sheet or the ledger differs from the turn's input. A turn that changed nothing returns no undo records. Decided items the sheet no longer has (`ledger_unmatched`) get a reply line, and the response carries them.
15. **No internal error text in replies.** A code rejection reads "I couldn't apply the change to <kind> as asked. Could you say it another way?", and the internal reason goes only to the evidence (`detail`).
17. **2026-10-13 (Hassan): style claims verified, not word overlap.** The content-word-overlap prose check is removed: it refused ordinary style requests ("more concise", "British spelling", "less formal").
    - The style call changes only what the instruction asks for and returns, per changed block, a claim that names the block (its heading or id) and what changed.
    - A claim that names no block is unverified and is not applied, with no Jev call (a structural check).
    - Every other claim gets Jev V1 ("Does the INSTRUCTION ask for this change: "<claim>"?", from the verify lab) at 0.5, all claims in one call, in parallel with the line questions.
    - A block that fails is not applied and gets an ask line. The unit-line and grammar guards stay.
    - This applies in both arm 1's style path and arm 2.
18. **2026-10-13 (Hassan): the habit guard covers the style path.** When it fires, a prose line flagged as requiring content is left out and is not re-routed, so it cannot become a normal or fixed card.
16. **Prose the style call never sees:** `## Scan Context` and `## Report Structure` (the fit check reads the scan context, and the structure block is layout).

## File map

Backend (`backend/src/rapid_reports_ai/`):

| File | Status | Responsibility |
|---|---|---|
| `chat_router_ledger.py` | create | **the only module that imports the Rules step**: ledger writes, undo, value seeding, concept choice shape, cards, observe, save |
| `template_decisions.py` | modify | `ROUTES`; `clean_ledger` keeps a valid `route` (D-R2) |
| `chat_router_sheet.py` | create | line walk, unit vs prose lines, prose blocks, splice, unit-line guard, paragraph spans, scan type |
| `chat_router_edits.py` | create | one-line unit edits (FIXED reword/add, NORMAL/NEGATIVE add, COVERS), lint guard, `apply_op` dispatcher |
| `chat_router_layout.py` | create | section and paragraph operations with their inverses |
| `chat_router_changes.py` | create | structured-change models (call output types), validation into verdicts, wording/slot gate, proposal cards, claims |
| `chat_router_views.py` | create | the part of the template each targeted call sees |
| `chat_router_jev.py` | create | the seven tag questions; the rule-in-disguise question; thresholds |
| `chat_router_calls.py` | create | the targeted-call prompts and the Qwen call with its gpt-oss retry |
| `chat_router.py` | create | `route_turn`, `undo_turn`, `answer_card`, `enabled`, `response` |
| `scripts/chat_router_lab.py` | create | lab runner and scorers (tag, calls, e2e) |
| `database/models.py` | modify `:942-952` | `TemplateChatTurn.routing` |
| `migrations/versions/20261014090000_chat_turn_routing.py` | create | the column |
| `template_chat_turns.py` | modify `:26-37` | `record_turn(..., routing=None)` |
| `main.py` | modify | refine endpoint routes first; `/skill-sheet/refine/undo`, `/skill-sheet/refine/card` |

Tests (`backend/tests/`): `template_sheet_fixtures.py` (append `ROUTER_SHEET`), `test_chat_router_ledger.py`, `test_chat_router_sheet.py`, `test_chat_router_edits.py`, `test_chat_router_layout.py`, `test_chat_router_changes.py`, `test_chat_router_views.py`, `test_chat_router_jev.py`, `test_chat_router_calls.py`, `test_chat_router.py`, `test_chat_router_lab.py`, `test_chat_router_routes.py`, `conftest.py` (autouse `RR_CHAT_ROUTER=0`).

Frontend (`frontend/src/`):

| File | Status | Responsibility |
|---|---|---|
| `lib/chat-router/types.ts` | create | router wire types (proposal card, turn response, card answer) |
| `lib/chat-router/api.ts` (+ `api.test.ts`) | create | `postRouterUndo`, `postRouterCard` |
| `lib/chat-router/ChatCards.svelte` (+ `.svelte.test.ts`) | create | one-tap cards inside the chat (decision cards and proposal cards) |
| `routes/components/SkillSheetCreator.svelte` | modify | router turns: undo through the backend, cards, card answers |
| `routes/components/TemplateRefinePanel.svelte` (+ `TemplateRefinePanel.router.svelte.test.ts`) | modify | the reject loop, cards and card answers |

There are no new pages, so no dev-route guard is needed.

## Phases

| Phase | Tasks | Leaves working software | Notes |
|---|---|---|---|
| 1. Pure code: adapter, sheet reading, edits, layout, validation, views | 1-6 | importable, fully unit-tested, nothing calls it | no model calls |
| 2. Jev tags, targeted calls, the orchestrator | 7-11 | `route_turn` / `undo_turn` / `answer_card` tested with fakes; nothing wired | |
| 3. Labs (**before the wiring**) | 12-15 | lab script; synthetic and real sets; tagging report, then targeted-call and end-to-end report | **The tagging lab (Task 14) runs before any wiring.** Hassan sets `TAG_MIN`, `TAG_UNSURE` and `REQUIRES_MIN` from it |
| 4. Wiring and evidence | 16-19 | the refine endpoint routes; undo and card endpoints; routing evidence stored | the kill switch keeps today's path one env var away |
| 5. Frontend | 20-24 | creator and refine panel: router turns, undo, cards | needs Phase 4 |

Labs are reported, not gated. Each lab task ends with a report and recommendations, and Hassan decides. No pass/fail threshold blocks the next task, but the wiring uses the constants he sets.

---

# Phase 1: pure code

### Task 1: The adapter: the router's one door to the Rules step

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decisions.py` (`ROUTES`; `clean_ledger` keeps a valid `route`)
- Modify: `backend/tests/template_sheet_fixtures.py` (append `ROUTER_SHEET`)
- Create: `backend/src/rapid_reports_ai/chat_router_ledger.py`
- Test: `backend/tests/test_chat_router_ledger.py`

- [ ] **Step 1: Confirm the ledger API this adapter wraps** (verified at `feat/rules-step` 68493ba9; a later amendment must touch only this module)

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router/backend/src/rapid_reports_ai && grep -n "^def set_decision\|^def rekey_decision\|^def undo_change\|^def concept_texts\|^def concept_of_condition\|^def clean_ledger\|^def validate\|^def find" template_decisions.py && grep -n "^def observe\|^def apply_ledger\|^def reconcile_chat" template_ledger_apply.py && grep -n "^def card_for_change" template_rules_cards.py && grep -n "ledger_cards\|ledger_unmatched" template_sheet_save.py | head -4
```

Expected: every name above is found. These are the shapes the adapter relies on, as read at 68493ba9:
- A concept choice is `{use, default, when_met, condition, dictated}`. "Whichever is dictated" is `use: False, dictated: True`, with the wording and condition blanked.
- A used concept needs `condition` to be one of `td.CONCEPTS[name].conditions`, which is filled automatically when there is exactly one. Contrast has two (`states` given / not_given).
- `Change["old"]` is the whole old entry, or None.
- `td.undo_change(ledger, change)` reverses a change.
- `td.rekey_decision` moves a fixed entry to reworded text.
- `set_decision` / `rekey_decision` refuse a FIXED key that a concept owns (`td.concept_texts`).
- `VetOutcome` carries `ledger_cards` (a whole decided item a chat rewrite removed: kept, asked) and `ledger_unmatched`.

If any differs, change only this module and keep the tests' expected router-side values.

- [ ] **Step 2: Add the fixture** (append to `backend/tests/template_sheet_fixtures.py`)

```python
# The chat-edit router's sheet: a value list, two FIXED lines, two findings paragraphs (one NORMAL + one NEGATIVE,
# and one NORMAL), prose blocks (Voice, an Opening line, Impression Construction) and a Scan Context the style call
# never sees. Abstract names keep the router's tests case-agnostic.
ROUTER_SHEET = """# Skill Sheet: Router test

## Scan Context
An imaging study of one body region.

## Voice
Sentences are short and declarative.

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["Width" | "Depth"] AT TOP | section: FINDINGS

## Paragraph: Technique (TECHNIQUE)
FIXED "Axial images were acquired."
FIXED "No previous imaging available."

## Paragraph: Upper (FINDINGS)
COVERS ["alpha" | "beta"]
Opening: The paragraph opens with alpha.
NORMAL [alpha] "Alpha is normal."
NEGATIVE "No beta abnormality."

## Paragraph: Lower (FINDINGS)
COVERS ["gamma"]
NORMAL [gamma] "Gamma is normal."

## Paragraph: Impression (IMPRESSION)
Opening: The impression opens with the main finding.

## Impression Construction
Lead with the most important finding.
Keep it brief.
"""

# The same sheet with the comparison concept written by the Rules step: its FIXED default plus a standard REPLACE.
ROUTER_SHEET_CONCEPT = ROUTER_SHEET.replace(
    'FIXED "No previous imaging available."\n',
    'FIXED "No previous imaging available."\n'
    'RULE WHEN [context: the dictation names a previous imaging study for comparison] '
    'REPLACE "No previous imaging available." WITH "Compared with the {study} of {date}."\n')
```

- [ ] **Step 3: Write the failing tests** (`backend/tests/test_chat_router_ledger.py`)

```python
"""The router's adapter over the Rules step's ledger (chat-edit router spec, Flow 2 and 5)."""
import pytest

from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import ROUTER_SHEET, ROUTER_SHEET_CONCEPT

COMPARED = "Compared with the {study} of {date}."
NO_PRIOR = "No previous imaging available."


@pytest.fixture(autouse=True)
def no_unit_checks(monkeypatch):
    """The save function's unit checks call a model; these tests check the ledger only."""
    from rapid_reports_ai import template_sheet_save as S

    async def none(structure, sheet):
        return []
    monkeypatch.setattr(S, "check_units", none)


def test_the_fixtures_are_lint_clean():
    assert not tsg.parse_sheet(ROUTER_SHEET, mode="template").errors
    assert not tsg.parse_sheet(ROUTER_SHEET_CONCEPT, mode="template").errors


def test_seed_values_records_the_listed_values_as_defaults_once():
    led = L.seed_values([], ROUTER_SHEET)
    assert [(e["key"], e["choice"], e["source"], e["by"]) for e in led] == [
        ("Width", {"need": "every"}, "default", "code"), ("Depth", {"need": "every"}, "default", "code")]
    assert L.seed_values(led, ROUTER_SHEET) == led
    assert L.values(ROUTER_SHEET, []) == [("Width", "every"), ("Depth", "every")]


def test_set_choice_writes_a_chat_entry_and_returns_the_change():
    led, change = L.set_choice([], "value", "Width", {"need": "not_needed"})
    assert led[0]["source"] == "chat" and led[0]["by"] == "radiologist" and "route" not in led[0]
    assert change["kind"] == "value" and change["key"] == "Width" and change["old"] is None
    with pytest.raises(L.Rejected):
        L.set_choice([], "value", 'a "quoted" name', {"need": "every"})
    with pytest.raises(L.Rejected):
        L.set_choice([], "concept", "no-such-concept", {"use": False})


def test_a_route_marks_the_entry_and_survives_clean():
    led, _ = L.set_choice([], "value", "Width", {"need": "relevant"}, route="llm_unsure")
    assert led[0]["route"] == "llm_unsure" and L.clean(led)[0]["route"] == "llm_unsure"
    assert "route" not in td.clean_ledger([{**led[0], "route": "made-up"}])[0]
    with pytest.raises(L.Rejected):
        L.set_choice([], "value", "Width", {"need": "every"}, route="made-up")


def test_undo_wraps_undo_change_and_restores_the_old_entry_whole():
    led, change = L.set_choice([], "value", "Width", {"need": "not_needed"})
    assert L.undo(led, change) == []
    seeded = L.seed_values([], ROUTER_SHEET)
    led2, change2 = L.set_choice(seeded, "value", "Width", {"need": "relevant"})
    width = L.entry(L.undo(led2, change2), "value", "Width")
    assert width["choice"] == {"need": "every"} and width["source"] == "default" and width["by"] == "code"


def test_undo_leaves_an_entry_a_later_turn_changed():
    led, change = L.set_choice([], "value", "Width", {"need": "not_needed"})
    led, _ = L.set_choice(led, "value", "Width", {"need": "relevant"})
    assert L.entry(L.undo(led, change), "value", "Width")["choice"] == {"need": "relevant"}


def test_concept_choice_round_trips_every_state_through_the_real_validate():
    cond = L.condition_for("comparison", "compared")
    assert cond == "the dictation names a previous imaging study for comparison"
    _, used = L.check("concept", "comparison", L.concept_choice("used", NO_PRIOR, COMPARED, cond))
    assert L.concept_state(used) == ("used", NO_PRIOR, COMPARED, cond)
    _, auto = L.check("concept", "comparison", L.concept_choice("used", NO_PRIOR, COMPARED))
    assert auto["condition"] == cond      # one standard condition: filled by the ledger
    _, dictated = L.check("concept", "comparison", L.concept_choice("dictated", NO_PRIOR, COMPARED))
    assert dictated["use"] is False and dictated["dictated"] is True
    assert L.concept_state(dictated) == ("dictated", "", "", "")
    _, off = L.check("concept", "comparison", L.concept_choice("not_used", NO_PRIOR, COMPARED))
    assert L.concept_state(off) == ("not_used", "", "", "")


def test_contrast_needs_one_of_its_two_conditions():
    with pytest.raises(L.Rejected):
        L.check("concept", "contrast", L.concept_choice("used", "Contrast was given.", "No contrast was given."))
    cond = L.condition_for("contrast", "not_given")
    assert cond == "the dictation states no contrast agent was given" and L.condition_for("contrast", cond) == cond
    _, choice = L.check("concept", "contrast",
                        L.concept_choice("used", "Contrast was given.", "No contrast was given.", cond))
    assert choice["condition"] == cond
    assert L.concept_states("contrast") == {"given": "the dictation states a contrast agent was given",
                                            "not_given": cond}
    assert L.condition_for("contrast", "sometimes") == ""


def test_concept_owner_finds_a_line_by_the_ledger_or_the_sheet():
    led, _ = L.set_choice([], "concept", "comparison", L.concept_choice("used", NO_PRIOR, COMPARED))
    assert L.concept_owner(ROUTER_SHEET, led, "no previous imaging available") == "comparison"
    assert L.concept_owner(ROUTER_SHEET_CONCEPT, [], NO_PRIOR) == "comparison"
    assert L.concept_owner(ROUTER_SHEET_CONCEPT, [], COMPARED) == "comparison"
    assert L.concept_owner(ROUTER_SHEET, [], NO_PRIOR) is None
    with pytest.raises(L.Rejected):     # the ledger refuses a FIXED decision on a concept's line
        L.set_choice(led, "fixed", NO_PRIOR, {"keep": "remove"})


def test_current_reads_the_sheet():
    assert L.current(ROUTER_SHEET, "fixed", "Axial images were acquired.") == {"keep": "always"}
    assert L.current(ROUTER_SHEET, "normal", L.normal_key("Upper", "alpha")) == {"text": "Alpha is normal."}
    assert L.current(ROUTER_SHEET, "normal", L.normal_key("Nowhere", "alpha")) is None
    assert L.concept_state(L.current(ROUTER_SHEET_CONCEPT, "concept", "comparison"))[:3] == ("used", NO_PRIOR, COMPARED)


def test_card_is_the_rules_step_card_or_none():
    card = L.card("value", "Width", {"need": "not_needed"})
    assert card["ledger_kind"] == "value" and card["key"] == "Width" and card["selected"] is None
    assert L.card("normal", "no separator", {"text": "x"}) is None


def test_rekeys_follow_a_paragraph_rename_and_a_fixed_reword():
    led, _ = L.set_choice([], "normal", L.normal_key("Upper", "alpha"), {"text": "Alpha is fine."})
    led, _ = L.set_choice(led, "fixed", "Axial images were acquired.", {"keep": "always"})
    led = L.rekey_paragraph(led, "upper", "Top")
    assert L.entry(led, "normal", L.normal_key("Top", "alpha"))["choice"] == {"text": "Alpha is fine."}
    led, change = L.rekey_fixed(led, "Axial images were acquired.", "Axial and coronal images were acquired.")
    assert L.entry(led, "fixed", "Axial and coronal images were acquired.") is not None
    assert change["old"]["key"] == "Axial images were acquired."
    assert L.entry(L.undo(led, change), "fixed", "Axial images were acquired.") is not None
    assert L.rekey_fixed(led, "Not decided.", "Other.") == (led, None)
    assert [e["key"] for e in L.paragraph_entries(led, "TOP")] == [L.normal_key("Top", "alpha")]
    assert L.normal_label(L.negative_key("Upper", "No beta abnormality.")) == ("Upper", "No beta abnormality.")


def test_restore_validates_a_client_sent_entry():
    good = {"kind": "normal", "key": L.normal_key("Lower", "gamma"), "choice": {"text": "Gamma is fine."},
            "by": "radiologist", "at": "t", "source": "chat"}
    assert L.entry(L.restore([], good), "normal", good["key"])["choice"] == {"text": "Gamma is fine."}
    assert L.restore([good], good) == [good]
    with pytest.raises(L.Rejected):
        L.restore([], {"kind": "value", "key": 'a "b"', "choice": {"need": "every"}})


async def test_save_applies_the_ledger_and_reports_unmatched_and_cards():
    led, _ = L.set_choice(L.seed_values([], ROUTER_SHEET), "value", "Width", {"need": "not_needed"})
    saved = await L.save(ROUTER_SHEET, ROUTER_SHEET, led)
    assert saved.status == "saved" and 'LIST_MISSING ["Depth"]' in saved.sheet
    assert L.entry(saved.ledger, "value", "Width")["choice"] == {"need": "not_needed"}
    assert saved.cards == [] and saved.unmatched == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_ledger.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router_ledger'`

- [ ] **Step 5: Let the ledger keep how a chat decision was reached** (D-R2). In `backend/src/rapid_reports_ai/template_decisions.py`, add after the `SOURCES = (...)` line:

```python
ROUTES = ("llm_unsure",)   # how a chat decision was reached, when not plainly: the chat-edit router's unsure band
```

and in `clean_ledger` replace

```python
        out.append({"kind": e["kind"], "key": key, "choice": choice,
                    "by": e.get("by") if e.get("by") in BY else "code", "at": str(e.get("at") or ""),
                    "source": e.get("source") if e.get("source") in SOURCES else "default"})
```

with

```python
        kept = {"kind": e["kind"], "key": key, "choice": choice,
                "by": e.get("by") if e.get("by") in BY else "code", "at": str(e.get("at") or ""),
                "source": e.get("source") if e.get("source") in SOURCES else "default"}
        if e.get("route") in ROUTES:   # the chat-edit router's mark (decision D-R2); anything else is dropped
            kept["route"] = e["route"]
        out.append(kept)
```

- [ ] **Step 6: Write the module** (`backend/src/rapid_reports_ai/chat_router_ledger.py`)

```python
"""The chat-edit router's one door to the Rules step (spec 2026-10-13-chat-edit-router-design, Flow 2 and 5).

Router modules call the decision ledger, its one-tap cards and the save function only through this module, never
template_decisions / template_ledger_apply / template_rules_cards / template_sheet_save directly, so a rename or a
shape change there is one edit here (verified against feat/rules-step 68493ba9). Ledger kinds: value, concept,
fixed, normal; layout and style have none. Only concept_choice / concept_state / condition_for know the concept
choice shape."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import template_decisions as td
from . import template_ledger_apply as tla
from . import template_rules_cards as trc
from . import template_sheet_grammar as tsg
from . import template_sheet_save as tsave
from .hybrid_stack.template import norm_key

LEDGER_KINDS: Tuple[str, ...] = tuple(td.KINDS)
NEEDS: Tuple[str, ...] = tuple(td.NEEDS)
KEEPS: Tuple[str, ...] = tuple(td.KEEPS)
ROUTES: Tuple[str, ...] = tuple(td.ROUTES)
CONCEPTS: Dict[str, str] = {name: c.label for name, c in td.CONCEPTS.items()}
CONCEPT_STATES = ("used", "dictated", "not_used")


class Rejected(ValueError):
    """Code cannot apply this change as given. Its text is internal (evidence only), never a reply."""


@dataclass
class Saved:
    status: str                 # the save function's status: "saved" | "unchanged" | "refused"
    sheet: str
    ledger: List[dict]
    message: str = ""           # an adjustment notice or the refusal reason (written for the radiologist)
    ledger_changes: List[dict] = field(default_factory=list)   # confirmed items a sheet change moved
    cards: List[dict] = field(default_factory=list)            # whole items a rewrite removed unasked: kept, asked
    unmatched: List[dict] = field(default_factory=list)        # decided items the sheet no longer has


def _n(s: str) -> str:
    return " ".join((s or "").lower().split())


def structure(sheet: str):
    return tsg.parse_sheet(sheet or "", mode="template").structure


def clean(entries) -> List[dict]:
    return td.clean_ledger(entries or [])


def normal_key(paragraph: str, structure_name: str) -> str:
    return td.normal_key(paragraph, structure_name)


def negative_key(paragraph: str, text: str) -> str:
    return td.negative_key(paragraph, text)


def normal_label(key: str) -> Tuple[str, str]:
    """(paragraph, structure or negative text) of a normal key."""
    try:
        para, label, _ = td.split_normal_key(key)
    except td.DecisionError as e:
        raise Rejected(str(e)) from e
    return para, label


def check(kind: str, key: str, choice: dict) -> Tuple[str, dict]:
    """(key, choice) in the ledger's canonical form; Rejected when code cannot apply it."""
    try:
        return td.validate(kind, key, choice)
    except td.DecisionError as e:
        raise Rejected(str(e)) from e


# ── concepts ────────────────────────────────────────────────────────────────────────────────────────────────────
def concept_states(name: str) -> Dict[str, Optional[str]]:
    """state name -> the standard condition under which that state's wording applies (None: the usual state)."""
    return dict(td.CONCEPTS[name].states)


def condition_for(name: str, given: str) -> str:
    """The standard condition named by `given` (a state name such as "compared" / "not_given", or the condition
    text itself); "" when it names none."""
    g = _n(given)
    states = td.CONCEPTS[name].states
    if g in states:
        return states[g] or ""
    return next((c for c in td.CONCEPTS[name].conditions if _n(c) == g), "")


def concept_choice(state: str, default: str, when_met: str, condition: str = "") -> dict:
    """The ledger choice for a concept in one of CONCEPT_STATES. "dictated" is use False + dictated True with the
    wording blanked (the ledger's form)."""
    if state == "dictated":
        return {"use": False, "dictated": True, "default": "", "when_met": "", "condition": ""}
    if state == "not_used":
        return {"use": False, "dictated": False, "default": "", "when_met": "", "condition": ""}
    return {"use": True, "dictated": False, "default": default or "", "when_met": when_met or "",
            "condition": condition or ""}


def concept_state(choice: Optional[dict]) -> Tuple[str, str, str, str]:
    """(state, default wording, wording when its condition is met, condition) of a concept choice."""
    c = choice or {}
    if c.get("dictated"):
        return "dictated", "", "", ""
    if not c.get("use"):
        return "not_used", "", "", ""
    return "used", c.get("default", "") or "", c.get("when_met", "") or "", c.get("condition", "") or ""


def concept_owner(sheet: str, ledger: List[dict], text: str) -> Optional[str]:
    """The concept whose wording `text` is: decided in the ledger, or the target / wording of a rule carrying a
    standard condition in the sheet. Such a line is the concept's, never a FIXED decision's."""
    k = norm_key(text or "")
    if not k:
        return None
    for e in ledger or []:
        if e.get("kind") == "concept":
            ch = e.get("choice") or {}
            if k in {norm_key(ch.get("default", "")), norm_key(ch.get("when_met", ""))} - {""}:
                return e["key"]
    for r in structure(sheet).rules:
        name = td.concept_of_condition(r.condition) if r.condition_source == "context" else None
        if name and k in {norm_key(r.target or ""), norm_key(r.then_text or "")} - {""}:
            return name
    return None


# ── reading and writing ─────────────────────────────────────────────────────────────────────────────────────────
def current(sheet: str, kind: str, key: str) -> Optional[dict]:
    """The choice the sheet expresses now for (kind, key); None when a normal's paragraph is gone."""
    try:
        return tla.observe(structure(sheet), kind, key)
    except (td.DecisionError, KeyError, StopIteration) as e:
        raise Rejected(str(e)) from e


def entry(ledger: List[dict], kind: str, key: str) -> Optional[dict]:
    try:
        return td.find(ledger or [], kind, key)
    except td.DecisionError:
        return None


def listed_values(sheet: str) -> List[str]:
    return [x for r in structure(sheet).rules if r.effect == "list_missing" for x in r.items]


def seed_values(ledger: List[dict], sheet: str) -> List[dict]:
    """Before the first value decision, the values the sheet lists now become default entries: once the ledger has
    any value entry it owns the whole list, so a single chat change must not empty it."""
    out = list(ledger or [])
    if any(e.get("kind") == "value" for e in out):
        return out
    for name in listed_values(sheet):
        try:
            out, _ = td.set_decision(out, "value", name, {"need": "every"}, source="default", by="code")
        except td.DecisionError:
            continue
    return out


def values(sheet: str, ledger: List[dict]) -> List[Tuple[str, str]]:
    """(name, need) of every value: the ledger's entries, or the sheet's list when the ledger has none."""
    return [(e["key"], e["choice"]["need"]) for e in seed_values(ledger, sheet) if e["kind"] == "value"]


def set_choice(ledger: List[dict], kind: str, key: str, choice: dict,
               route: Optional[str] = None) -> Tuple[List[dict], Optional[dict]]:
    """One chat decision (source "chat", by the radiologist); `route` marks how it was reached (ROUTES). Returns the
    ledger and the change, or None when the choice was already so."""
    if route is not None and route not in ROUTES:
        raise Rejected(f"unknown route {route!r}")
    try:
        out, change = td.set_decision(list(ledger or []), kind, key, choice, source="chat")
    except td.DecisionError as e:
        raise Rejected(str(e)) from e
    if route:
        e = td.find(out, kind, key)
        out = [{**x, "route": route} if x is e else x for x in out]
    return out, (dict(change) if change else None)


def undo(ledger: List[dict], change: dict) -> List[dict]:
    """Reverse one change this router made (td.undo_change), only while its entry still holds it: a later turn's
    change is never undone."""
    e = entry(ledger, change["kind"], change["key"])
    if e is None or e.get("choice") != change.get("new"):
        return list(ledger or [])
    return td.undo_change(list(ledger), change)


def rekey_fixed(ledger: List[dict], old: str, new: str) -> Tuple[List[dict], Optional[dict]]:
    """A decided FIXED line follows its rewording (td.rekey_decision); (ledger, None) when it is not decided."""
    if entry(ledger, "fixed", old) is None:
        return list(ledger or []), None
    try:
        out, change = td.rekey_decision(list(ledger), "fixed", old, new, source="chat")
    except td.DecisionError as e:
        raise Rejected(str(e)) from e
    return out, dict(change)


def restore(ledger: List[dict], e: dict) -> List[dict]:
    """A dropped entry put back (undo of a removed paragraph). Client-sent, so validated first."""
    if not isinstance(e, dict):
        raise Rejected("entry: object expected")
    check(e.get("kind", ""), e.get("key", ""), e.get("choice") or {})
    if entry(ledger, e["kind"], e["key"]) is not None:
        return list(ledger or [])
    return [*(ledger or []), *clean([e])]


def note(change: Optional[dict]) -> str:
    """"This changes something you confirmed: …" for a confirmed item, else ""."""
    return td.describe_change(change) if change else ""


def card(kind: str, key: str, proposed: dict) -> Optional[dict]:
    """The Rules step's one-tap card for this proposal, or None when code cannot make one."""
    try:
        return trc.card_for_change(kind, key, proposed)
    except td.DecisionError:
        return None


def paragraph_entries(ledger: List[dict], paragraph: str) -> List[dict]:
    out = []
    for e in ledger or []:
        if e.get("kind") != "normal":
            continue
        try:
            para, _, _ = td.split_normal_key(e["key"])
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
            _, label, neg = td.split_normal_key(e["key"])
            e = {**e, "key": td.negative_key(new, label) if neg else td.normal_key(new, label)}
        out.append(e)
    return out


async def save(sheet: str, previous: str, ledger: List[dict]) -> Saved:
    """The save function (origin "chat"), which applies the ledger last."""
    v = await tsave.vet_sheet(sheet, origin="chat", previous=previous, ledger=list(ledger or []))
    return Saved(v.status, v.sheet, list(v.ledger), v.message or "", [dict(c) for c in v.ledger_changes],
                 list(v.ledger_cards or []), list(v.ledger_unmatched or []))
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_ledger.py tests/test_template_decisions.py -q`
Expected: PASS (14 new tests, and the Rules-step decision tests unchanged)

- [ ] **Step 8: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_ledger.py backend/src/rapid_reports_ai/template_decisions.py backend/tests/test_chat_router_ledger.py backend/tests/template_sheet_fixtures.py
git commit -m "feat(chat-router): adapter over the Rules-step ledger, cards and save function; ledger keeps a route

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 2: Reading the sheet: units, prose blocks, splice, guard

**Files:**
- Create: `backend/src/rapid_reports_ai/chat_router_sheet.py`
- Test: `backend/tests/test_chat_router_sheet.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_sheet.py`)

```python
"""Which sheet lines are code-owned units and which are prose the style call may edit."""
import pytest

from rapid_reports_ai import chat_router_sheet as sh
from tests.template_sheet_fixtures import ROUTER_SHEET


def test_walk_marks_units_headings_and_paragraphs():
    lines = sh.walk(ROUTER_SHEET)
    normal = next(l for l in lines if l.text.startswith("NORMAL [alpha]"))
    assert normal.keyword == "NORMAL" and normal.paragraph == "Upper" and normal.section == "FINDINGS"
    opening = next(l for l in lines if l.text.startswith("Opening: The paragraph"))
    assert opening.keyword == "" and opening.paragraph == "Upper"
    assert next(l for l in lines if l.text == "## Voice").keyword == "#"


def test_prose_blocks_skip_scan_context_and_blank_runs():
    blocks = sh.prose_blocks(ROUTER_SHEET)
    assert [(b.id, b.heading) for b in blocks] == [
        ("b1", "Voice"), ("b2", "Paragraph: Upper (FINDINGS)"), ("b3", "Paragraph: Impression (IMPRESSION)"),
        ("b4", "Impression Construction")]
    assert blocks[3].text == "Lead with the most important finding.\nKeep it brief."


def test_splice_replaces_a_block_and_keeps_every_unit_line():
    out = sh.splice(ROUTER_SHEET, {"b4": "Lead with the main finding in one sentence."})
    assert "Keep it brief." not in out and "Lead with the main finding in one sentence." in out
    assert sh.units_unchanged(ROUTER_SHEET, out) and out.endswith("\n")


def test_the_guard_catches_a_unit_line_written_into_prose():
    out = sh.splice(ROUTER_SHEET, {"b1": 'Sentences are short.\nNORMAL [alpha] "Alpha is fine."'})
    assert not sh.units_unchanged(ROUTER_SHEET, out)


def test_new_lines_lists_only_lines_that_were_not_there():
    assert sh.new_lines("A.\nB.", "A.\nC.\n\n b. ") == ["C."]


def test_scan_type_paragraphs_and_spans():
    assert sh.scan_type(ROUTER_SHEET) == "Router test"
    assert sh.paragraphs(ROUTER_SHEET) == [("Technique", "TECHNIQUE"), ("Upper", "FINDINGS"), ("Lower", "FINDINGS"),
                                           ("Impression", "IMPRESSION")]
    start, end = sh.paragraph_span(ROUTER_SHEET, "lower")
    assert ROUTER_SHEET.splitlines()[start] == "## Paragraph: Lower (FINDINGS)"
    assert ROUTER_SHEET.splitlines()[end] == "## Paragraph: Impression (IMPRESSION)"
    with pytest.raises(KeyError):
        sh.paragraph_span(ROUTER_SHEET, "nowhere")
    assert sh.quoted('FIXED "No previous imaging available."') == "No previous imaging available."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_sheet.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router_sheet'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/chat_router_sheet.py`)

```python
"""Reading a grammar sheet line by line for the chat-edit router (spec 2026-10-13-chat-edit-router-design): which
lines are units (owned by code), which are prose (the only lines the style call may edit), each line's heading and
paragraph, splicing edited prose back, and the unit-line guard ("code rejects the result if any unit line differs
from the input"). Pure."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from . import template_sheet_grammar as tsg

_HEAD = re.compile(r"^(#{1,2})\s+(.*?)\s*$")       # "#"/"##" open a context; "###" is prose (grammar :158)
_FIRST = re.compile(r"^([A-Z][A-Z_]*)\b")
_QUOTED = re.compile(r'"([^"]*)"')
_TITLE = re.compile(r"^#\s+Skill Sheet:\s*(.+?)\s*$", re.M)
NO_STYLE = ("scan context", "report structure")      # prose the style call never sees or edits


def norm(s: str) -> str:
    return " ".join((s or "").lower().split())


@dataclass(frozen=True)
class Line:
    i: int            # 0-based index in sheet.splitlines()
    text: str
    heading: str      # the current "#"/"##" heading title ("" before the first)
    paragraph: str    # the paragraph name under "## Paragraph: …", else ""
    section: str      # that paragraph's section as written, else ""
    keyword: str      # a unit keyword (FIXED, NORMAL, …), "#" for a heading, "" for prose


@dataclass(frozen=True)
class Block:
    id: str           # "b1", "b2", … in sheet order
    heading: str
    start: int        # lines [start, end)
    end: int
    text: str


def _keyword(raw: str) -> str:
    m = _FIRST.match(tsg._undecorate(raw))
    return m.group(1) if m and m.group(1) in tsg.KEYWORDS else ""


def walk(sheet: str) -> List[Line]:
    out: List[Line] = []
    heading = para = sec = ""
    for i, raw in enumerate((sheet or "").splitlines()):
        h = _HEAD.match(raw)
        if h:
            heading = h.group(2)
            ph = tsg.paragraph_heading(heading) if h.group(1) == "##" else None
            para, sec = (ph[0], ph[1]) if ph else ("", "")
            out.append(Line(i, raw, heading, para, sec, "#"))
        else:
            out.append(Line(i, raw, heading, para, sec, _keyword(raw)))
    return out


def unit_lines(sheet: str) -> List[str]:
    """Every heading and unit line, in order (what a style edit must leave exactly as it was)."""
    return [l.text.strip() for l in walk(sheet) if l.keyword]


def units_unchanged(before: str, after: str) -> bool:
    return unit_lines(before) == unit_lines(after)


def prose_blocks(sheet: str) -> List[Block]:
    """Maximal runs of prose lines between units and headings, blank edges trimmed, outside NO_STYLE headings."""
    blocks: List[Block] = []
    run: List[Line] = []

    def flush() -> None:
        body = list(run)
        run.clear()
        while body and not body[0].text.strip():
            body.pop(0)
        while body and not body[-1].text.strip():
            body.pop()
        if body and norm(body[0].heading) not in NO_STYLE:
            blocks.append(Block(f"b{len(blocks) + 1}", body[0].heading, body[0].i, body[-1].i + 1,
                                "\n".join(l.text for l in body)))

    for l in walk(sheet):
        if l.keyword:
            flush()
        else:
            run.append(l)
    flush()
    return blocks


def join(lines: List[str], like: str) -> str:
    return "\n".join(lines) + ("\n" if (like or "").endswith("\n") else "")


def splice(sheet: str, edits: Dict[str, str]) -> str:
    """The sheet with each prose block (by id) replaced by its edited text; unknown ids are ignored."""
    blocks = {b.id: b for b in prose_blocks(sheet)}
    lines = (sheet or "").splitlines()
    for b in sorted((blocks[k] for k in edits if k in blocks), key=lambda b: -b.start):
        lines[b.start:b.end] = (edits[b.id] or "").strip("\n").splitlines()
    return join(lines, sheet)


def new_lines(before: str, after: str) -> List[str]:
    """Non-blank lines of `after` that `before` does not have (case and spacing ignored)."""
    old = {norm(x) for x in (before or "").splitlines() if x.strip()}
    return [x.strip() for x in (after or "").splitlines() if x.strip() and norm(x) not in old]


def quoted(line: str) -> str:
    m = _QUOTED.search(line or "")
    return m.group(1) if m else ""


def scan_type(sheet: str) -> str:
    m = _TITLE.search(sheet or "")
    return m.group(1) if m else ""


def paragraphs(sheet: str) -> List[Tuple[str, str]]:
    """(name, section as written) of every paragraph, in sheet order."""
    return [(l.paragraph, l.section) for l in walk(sheet) if l.keyword == "#" and l.paragraph]


def paragraph_span(sheet: str, name: str) -> Tuple[int, int]:
    """[start, end) lines of the paragraph block `name` (its heading up to the next heading); KeyError if absent."""
    walked = walk(sheet)
    start = next((l.i for l in walked if l.keyword == "#" and l.paragraph and norm(l.paragraph) == norm(name)), None)
    if start is None:
        raise KeyError(name)
    end = next((l.i for l in walked if l.keyword == "#" and l.i > start), len(walked))
    return start, end


def section_lines(sheet: str) -> List[Line]:
    return [l for l in walk(sheet) if l.keyword == "SECTION"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_sheet.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_sheet.py backend/tests/test_chat_router_sheet.py
git commit -m "feat(chat-router): read a sheet as units and prose blocks; the unit-line guard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 3: One-line unit edits and the `apply_op` dispatcher

**Files:**
- Create: `backend/src/rapid_reports_ai/chat_router_edits.py`
- Test: `backend/tests/test_chat_router_edits.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_edits.py`)

```python
"""Code edits of one unit line (decision 6), each lint-guarded, each with an inverse that restores the sheet."""
import pytest

from rapid_reports_ai import chat_router_edits as E
from tests.template_sheet_fixtures import ROUTER_SHEET


def _undo(sheet, inverse):
    for op in reversed(inverse):
        sheet, _ = E.apply_op(sheet, op)
    return sheet


def test_fixed_reword_changes_one_line_and_undoes():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "fixed_reword", "line": "axial images were acquired",
                                         "text": "Axial and coronal images were acquired."})
    assert 'FIXED "Axial and coronal images were acquired."' in out and 'FIXED "Axial images' not in out
    assert _undo(out, inv) == ROUTER_SHEET


def test_fixed_add_goes_after_the_paragraphs_last_unit():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "technique",
                                         "text": "Images were reviewed in three planes."})
    lines = out.splitlines()
    assert lines[lines.index('FIXED "No previous imaging available."') + 1] == 'FIXED "Images were reviewed in three planes."'
    assert _undo(out, inv) == ROUTER_SHEET


def test_fixed_add_refuses_a_duplicate_and_an_unknown_paragraph():
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "Technique", "text": "No previous imaging available"})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "Nowhere", "text": "A sentence."})


def test_normal_add_extends_covers_and_undoes_in_order():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "normal_add", "paragraph": "Lower", "structure": "delta",
                                         "text": "Delta is normal."})
    assert 'COVERS ["gamma" | "delta"]' in out and 'NORMAL [delta] "Delta is normal."' in out
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "normal_add", "paragraph": "Lower", "structure": "gamma", "text": "x."})


def test_negative_add_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "negative_add", "paragraph": "Upper", "text": "No beta collection."})
    assert 'NEGATIVE "No beta collection."' in out
    assert _undo(out, inv) == ROUTER_SHEET


def test_wording_with_quotes_or_slots_is_refused():
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "Technique", "text": 'Say "this".'})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "negative_add", "paragraph": "Upper", "text": "No {x}."})


def test_the_guard_refuses_an_edit_that_adds_a_lint_error():
    with pytest.raises(E.EditError):
        E.guarded(ROUTER_SHEET, ROUTER_SHEET + 'NORMAL [x] "unclosed\n')


def test_unknown_ops_and_bad_arguments_are_edit_errors():
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "rewrite_everything"})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "nonsense": 1})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_edits.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router_edits'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/chat_router_edits.py`)

```python
"""Code edits of single unit lines for the chat-edit router (plan decision 6): reword or add an always-printed
sentence, add a normal or a negative line to a paragraph (extending COVERS), and the inverse of each, for undo. An
edit that adds a grammar error is refused (EditError). Layout operations live in chat_router_layout; apply_op
dispatches both and returns (sheet, inverse ops); undo applies the inverse ops in reverse order."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import chat_router_sheet as sh
from . import template_sheet_grammar as tsg
from .hybrid_stack.template import norm_key


class EditError(ValueError):
    """The edit cannot be made as asked (no such target, or it would break the sheet)."""


_PLAIN = re.compile(r'^[^"“”{}\[\]|]+$')
_BRACKET = re.compile(r"\[([^\]]+)\]")
_ITEM = re.compile(r'"([^"]+)"')


def _errors(sheet: str) -> set:
    return {(e.text.strip(), e.reason) for e in tsg.parse_sheet(sheet, mode="template").errors}


def guarded(before: str, after: str) -> str:
    """`after`, or EditError when it has a grammar error `before` did not have."""
    new = _errors(after) - _errors(before)
    if new:
        raise EditError("the edit would break the template (" + "; ".join(sorted({r for _, r in new})) + ")")
    return after


def plain(t: str, what: str) -> str:
    t = " ".join((t or "").split())
    if not t or not _PLAIN.match(t):
        raise EditError(f"{what}: plain wording expected (no quotes, brackets, bars or {{slots}})")
    return t


def _span(sheet: str, paragraph: str) -> Tuple[int, int]:
    try:
        return sh.paragraph_span(sheet, paragraph)
    except KeyError:
        raise EditError(f"no paragraph {paragraph!r}") from None


def _unit(sheet: str, keyword: str, text: str, paragraph: str = "") -> sh.Line:
    for l in sh.walk(sheet):
        if l.keyword == keyword and norm_key(sh.quoted(l.text)) == norm_key(text) and (
                not paragraph or sh.norm(l.paragraph) == sh.norm(paragraph)):
            return l
    raise EditError(f"no {keyword} line {text!r}")


def _last_unit(sheet: str, paragraph: str) -> int:
    start, end = _span(sheet, paragraph)
    idx = [l.i for l in sh.walk(sheet)[start + 1:end] if l.keyword]
    return idx[-1] if idx else start


def _covers(sheet: str, paragraph: str) -> Optional[sh.Line]:
    start, end = _span(sheet, paragraph)
    return next((l for l in sh.walk(sheet)[start:end] if l.keyword == "COVERS"), None)


def _covers_line(items: List[str]) -> str:
    return "COVERS [" + " | ".join(f'"{x}"' for x in items) + "]"


def _insert_after(sheet: str, i: int, line: str) -> str:
    lines = sheet.splitlines()
    lines.insert(i + 1, line)
    return sh.join(lines, sheet)


def _replace(sheet: str, i: int, line: Optional[str]) -> str:
    lines = sheet.splitlines()
    if line is None:
        del lines[i]
    else:
        lines[i] = line
    return sh.join(lines, sheet)


# ── operations: (sheet, **args) -> (sheet, inverse ops) ──────────────────────────────────────────────────────────
def fixed_reword(sheet: str, line: str, text: str):
    l = _unit(sheet, "FIXED", line)
    old, new = sh.quoted(l.text), plain(text, "new wording")
    return _replace(sheet, l.i, l.text.replace(f'"{old}"', f'"{new}"', 1)), [
        {"op": "fixed_reword", "line": new, "text": old}]


def fixed_add(sheet: str, paragraph: str, text: str):
    t = plain(text, "sentence")
    if any(l.keyword == "FIXED" and norm_key(sh.quoted(l.text)) == norm_key(t) for l in sh.walk(sheet)):
        raise EditError("that sentence is already printed")
    return _insert_after(sheet, _last_unit(sheet, paragraph), f'FIXED "{t}"'), [
        {"op": "unit_drop", "keyword": "FIXED", "text": t}]


def normal_add(sheet: str, paragraph: str, structure: str, text: str):
    s, t = plain(structure, "structure"), plain(text, "normal wording")
    start, end = _span(sheet, paragraph)
    if any(l.keyword == "NORMAL" and sh.norm((_BRACKET.search(l.text) or [None, ""])[1]) == sh.norm(s)
           for l in sh.walk(sheet)[start:end]):
        raise EditError("that structure already has a normal line")
    inverse: List[dict] = []
    cov = _covers(sheet, paragraph)
    if cov is None:
        sheet = _insert_after(sheet, start, _covers_line([s]))
        inverse.append({"op": "covers_drop", "paragraph": paragraph, "structure": s})
    else:
        items = _ITEM.findall(cov.text)
        if sh.norm(s) not in {sh.norm(x) for x in items}:
            sheet = _replace(sheet, cov.i, _covers_line([*items, s]))
            inverse.append({"op": "covers_drop", "paragraph": paragraph, "structure": s})
    inverse.append({"op": "unit_drop", "keyword": "NORMAL", "text": t, "paragraph": paragraph})
    return _insert_after(sheet, _last_unit(sheet, paragraph), f'NORMAL [{s}] "{t}"'), inverse


def negative_add(sheet: str, paragraph: str, text: str):
    t = plain(text, "negative wording")
    start, end = _span(sheet, paragraph)
    if any(l.keyword == "NEGATIVE" and norm_key(sh.quoted(l.text)) == norm_key(t) for l in sh.walk(sheet)[start:end]):
        raise EditError("that negative is already stated")
    return _insert_after(sheet, _last_unit(sheet, paragraph), f'NEGATIVE "{t}"'), [
        {"op": "unit_drop", "keyword": "NEGATIVE", "text": t, "paragraph": paragraph}]


def unit_drop(sheet: str, keyword: str, text: str, paragraph: str = ""):
    return _replace(sheet, _unit(sheet, keyword, text, paragraph).i, None), []


def covers_drop(sheet: str, paragraph: str, structure: str):
    cov = _covers(sheet, paragraph)
    if cov is None:
        raise EditError(f"{paragraph} has no COVERS line")
    items = [x for x in _ITEM.findall(cov.text) if sh.norm(x) != sh.norm(structure)]
    return _replace(sheet, cov.i, _covers_line(items) if items else None), []


UNIT_OPS = {"fixed_reword": fixed_reword, "fixed_add": fixed_add, "normal_add": normal_add,
            "negative_add": negative_add, "unit_drop": unit_drop, "covers_drop": covers_drop}


def apply_op(sheet: str, op: dict) -> Tuple[str, List[dict]]:
    """Apply one edit (unit or layout); (sheet, inverse ops). EditError when it cannot be made or breaks the sheet."""
    from . import chat_router_layout as lay
    fns = {**UNIT_OPS, **lay.OPS}
    name = (op or {}).get("op")
    if name not in fns:
        raise EditError(f"unknown edit {name!r}")
    try:
        after, inverse = fns[name](sheet, **{k: v for k, v in op.items() if k != "op"})
    except (KeyError, TypeError) as e:
        raise EditError(f"{name}: {e}") from e
    return guarded(sheet, after), inverse
```

- [ ] **Step 4: Create an empty layout module so the dispatcher imports** (`backend/src/rapid_reports_ai/chat_router_layout.py`; Task 4 fills it)

```python
"""Layout operations for the chat-edit router (filled in by the next task)."""
OPS: dict = {}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_edits.py -q`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_edits.py backend/src/rapid_reports_ai/chat_router_layout.py backend/tests/test_chat_router_edits.py
git commit -m "feat(chat-router): lint-guarded one-line unit edits with inverses

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 4: Layout operations (sections and paragraphs)

**Files:**
- Modify: `backend/src/rapid_reports_ai/chat_router_layout.py` (replace the stub)
- Test: `backend/tests/test_chat_router_layout.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_layout.py`)

```python
"""Rename, move, remove and add a paragraph or a section (spec Flow 2, layout; plan decision 7)."""
import pytest

from rapid_reports_ai import chat_router_edits as E
from rapid_reports_ai import chat_router_layout as lay
from rapid_reports_ai import chat_router_sheet as sh
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import ROUTER_SHEET


def _undo(sheet, inverse):
    for op in reversed(inverse):
        sheet, _ = E.apply_op(sheet, op)
    return sheet


def _order(sheet):
    st = tsg.parse_sheet(sheet, mode="template").structure
    return [s.name for s in sorted(st.sections, key=lambda s: s.order)]


def test_rename_paragraph_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "rename_paragraph", "paragraph": "upper", "to": "Top"})
    assert "## Paragraph: Top (FINDINGS)" in out and _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "rename_paragraph", "paragraph": "Upper", "to": "Lower"})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "rename_paragraph", "paragraph": "Upper", "to": "Bad (name)"})


def test_move_paragraph_within_its_section_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "move_paragraph", "paragraph": "Lower", "before": "Upper"})
    assert [n for n, _ in sh.paragraphs(out)] == ["Technique", "Lower", "Upper", "Impression"]
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "move_paragraph", "paragraph": "Lower", "before": "Technique"})


def test_remove_paragraph_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "remove_paragraph", "paragraph": "Lower"})
    assert "Gamma is normal." not in out and _undo(out, inv) == ROUTER_SHEET


def test_add_paragraph_needs_covers_in_findings_and_undoes():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "add_paragraph", "name": "Middle", "section": "Findings",
                                         "covers": ["delta"]})
    assert [n for n, _ in sh.paragraphs(out)] == ["Technique", "Upper", "Lower", "Middle", "Impression"]
    assert 'COVERS ["delta"]' in out and _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "add_paragraph", "name": "Middle", "section": "FINDINGS", "covers": []})


def test_rename_section_by_name_or_printed_heading_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "rename_section", "section": "Findings:", "header": "Results:"})
    assert 'SECTION FINDINGS | header: "Results:" | role: findings' in out and _undo(out, inv) == ROUTER_SHEET


def test_move_section_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "move_section", "section": "technique", "after": "findings"})
    assert _order(out) == ["FINDINGS", "TECHNIQUE", "IMPRESSION"] and _undo(out, inv) == ROUTER_SHEET


def test_remove_section_takes_its_paragraphs_and_undoes():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "remove_section", "section": "Technique"})
    assert "SECTION TECHNIQUE" not in out and "Axial images were acquired." not in out
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "remove_section", "section": "IMPRESSION"})


def test_add_section_with_its_paragraph_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "add_section", "name": "Comparison", "header": "Comparison:",
                                         "role": "comparison", "after": "Technique"})
    assert _order(out) == ["TECHNIQUE", "COMPARISON", "FINDINGS", "IMPRESSION"]
    assert [n for n, _ in sh.paragraphs(out)][:2] == ["Technique", "Comparison"]
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "add_section", "name": "Other", "header": "", "role": "nonsense"})


def test_section_name_resolves_a_printed_heading():
    assert lay.section_name(ROUTER_SHEET, "Impression:") == "IMPRESSION"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_layout.py -q`
Expected: FAIL (`unknown edit 'rename_paragraph'`; `module … has no attribute 'section_name'`)

- [ ] **Step 3: Write the module** (replace `backend/src/rapid_reports_ai/chat_router_layout.py`)

```python
"""Layout operations for the chat-edit router (spec Flow 2: "Layout changes use the same structure operations on
SECTION / paragraph headings"; plan decision 7): rename, move, remove or add a paragraph or a section. Each returns
(sheet, inverse ops). Names match case-insensitively; a section matches by its name or its printed heading. Called
through chat_router_edits.apply_op, which refuses any result that adds a grammar error."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import chat_router_sheet as sh
from . import template_sheet_grammar as tsg
from .chat_router_edits import EditError

_PLAIN_NAME = re.compile(r'^[A-Za-z0-9][^()|"“”#\[\]{}]{0,59}$')
_SECTION_NAME = re.compile(r"^[A-Z0-9][A-Z0-9 /&-]*$")
_SEC = re.compile(r'SECTION\s+(?P<name>.+?)\s*\|\s*header:\s*(?:none|"(?P<header>[^"]*)")')
_HEADER_ATTR = re.compile(r'header:\s*(?:none|"[^"]*")')
_ITEM_BAD = re.compile(r'["|\[\]{}]')


def _name(t: str, what: str) -> str:
    t = " ".join((t or "").split())
    if not _PLAIN_NAME.match(t):
        raise EditError(f"{what}: a short plain name")
    return t


def _para(sheet: str, name: str) -> sh.Line:
    l = next((l for l in sh.walk(sheet) if l.keyword == "#" and l.paragraph and sh.norm(l.paragraph) == sh.norm(name)),
             None)
    if l is None:
        raise EditError(f"no paragraph {name!r}")
    return l


def _sections(sheet: str) -> List[Tuple[sh.Line, str, Optional[str]]]:
    out = []
    for l in sh.section_lines(sheet):
        m = _SEC.match(tsg._undecorate(l.text))
        if m:
            out.append((l, m.group("name").strip(), m.group("header")))
    return out


def _section(sheet: str, target: str) -> Tuple[sh.Line, str, Optional[str]]:
    t = sh.norm((target or "").strip().rstrip(":"))
    for l, name, header in _sections(sheet):
        if sh.norm(name) == t or (header and sh.norm(header.strip().rstrip(":")) == t):
            return l, name, header
    raise EditError(f"no section {target!r}")


def section_name(sheet: str, target: str) -> str:
    return _section(sheet, target)[1]


def _heading(name: str, section: str, header: Optional[str] = None) -> str:
    return f"## Paragraph: {name} ({section})" + (f' | header: "{header}"' if header else "")


def _covers_items(covers) -> List[str]:
    items = [" ".join(str(c).split()) for c in covers or [] if str(c).strip()]
    if any(_ITEM_BAD.search(c) for c in items):
        raise EditError("covered structures: plain names only")
    return items


# ── paragraphs ──────────────────────────────────────────────────────────────────────────────────────────────────
def rename_paragraph(sheet: str, paragraph: str, to: str):
    l = _para(sheet, paragraph)
    new = _name(to, "paragraph name")
    if sh.norm(new) != sh.norm(l.paragraph) and any(sh.norm(n) == sh.norm(new) for n, _ in sh.paragraphs(sheet)):
        raise EditError(f"there is already a paragraph called {new}")
    header = tsg.paragraph_heading(l.heading)[2]
    lines = sheet.splitlines()
    lines[l.i] = _heading(new, l.section, header)
    return sh.join(lines, sheet), [{"op": "rename_paragraph", "paragraph": new, "to": l.paragraph}]


def move_paragraph(sheet: str, paragraph: str, before: str = "", after: str = ""):
    l = _para(sheet, paragraph)
    if not (before or after):
        raise EditError("move: say which paragraph it goes before or after")
    a = _para(sheet, before or after)
    if sh.norm(a.section) != sh.norm(l.section):
        raise EditError("those paragraphs are in different sections")
    if a.i == l.i:
        raise EditError("a paragraph cannot move next to itself")
    same = [n for n, s in sh.paragraphs(sheet) if sh.norm(s) == sh.norm(l.section)]
    k = [sh.norm(n) for n in same].index(sh.norm(l.paragraph))
    inverse = ({"op": "move_paragraph", "paragraph": l.paragraph, "before": same[k + 1]} if k + 1 < len(same)
               else {"op": "move_paragraph", "paragraph": l.paragraph, "after": same[k - 1]})
    start, end = sh.paragraph_span(sheet, l.paragraph)
    lines = sheet.splitlines()
    block = lines[start:end]
    del lines[start:end]
    cut = sh.join(lines, sheet)
    s2, e2 = sh.paragraph_span(cut, a.paragraph)
    if block and block[-1].strip():
        block = [*block, ""]
    lines = cut.splitlines()
    lines[(s2 if before else e2):(s2 if before else e2)] = block
    return sh.join(lines, sheet), [inverse]


def remove_paragraph(sheet: str, paragraph: str):
    _para(sheet, paragraph)
    start, end = sh.paragraph_span(sheet, paragraph)
    lines = sheet.splitlines()
    block = lines[start:end]
    del lines[start:end]
    following = sh.walk(sh.join(lines, sheet))
    before = following[start].heading if start < len(following) and following[start].keyword == "#" else None
    return sh.join(lines, sheet), [{"op": "insert_block", "lines": block, "before_heading": before}]


def insert_block(sheet: str, lines: List[str], before_heading: Optional[str] = None):
    cur = sheet.splitlines()
    at = len(cur)
    if before_heading is not None:
        at = next((l.i for l in sh.walk(sheet) if l.keyword == "#" and l.heading == before_heading), len(cur))
    block = list(lines)
    if at == len(cur) and cur and cur[-1].strip():
        block = ["", *block]
    cur[at:at] = block
    return sh.join(cur, sheet), []


def add_paragraph(sheet: str, name: str, section: str, covers=None, after: str = ""):
    nm = _name(name, "paragraph name")
    if any(sh.norm(n) == sh.norm(nm) for n, _ in sh.paragraphs(sheet)):
        raise EditError(f"there is already a paragraph called {nm}")
    sec = section_name(sheet, section)
    items = _covers_items(covers)
    block = [_heading(nm, sec)] + (["COVERS [" + " | ".join(f'"{c}"' for c in items) + "]"] if items else []) + [""]
    paras = sh.paragraphs(sheet)
    order = [sh.norm(n) for _, n, _ in _sections(sheet)]
    if after:
        a = _para(sheet, after)
        if sh.norm(a.section) != sh.norm(sec):
            raise EditError("that paragraph is in a different section")
        at = sh.paragraph_span(sheet, a.paragraph)[1]
    else:
        same = [n for n, s in paras if sh.norm(s) == sh.norm(sec)]
        rank = order.index(sh.norm(sec))
        earlier = [n for n, s in paras if sh.norm(s) in order and order.index(sh.norm(s)) < rank]
        if same:
            at = sh.paragraph_span(sheet, same[-1])[1]
        elif earlier:
            at = sh.paragraph_span(sheet, earlier[-1])[1]
        elif paras:
            at = sh.paragraph_span(sheet, paras[0][0])[0]
        else:
            at = len(sheet.splitlines())
    lines = sheet.splitlines()
    if at > 0 and at <= len(lines) and lines[at - 1].strip():
        block = ["", *block]
    lines[at:at] = block
    return sh.join(lines, sheet), [{"op": "remove_paragraph", "paragraph": nm}]


# ── sections ────────────────────────────────────────────────────────────────────────────────────────────────────
def rename_section(sheet: str, section: str, header: str):
    l, name, old = _section(sheet, section)
    new = (header or "").strip()
    if new.lower() == "none":
        new = ""
    if '"' in new or "|" in new:
        raise EditError("section heading: plain wording only")
    lines = sheet.splitlines()
    lines[l.i] = _HEADER_ATTR.sub(f'header: "{new}"' if new else "header: none", l.text, count=1)
    return sh.join(lines, sheet), [{"op": "rename_section", "section": name, "header": old or "none"}]


def move_section(sheet: str, section: str, before: str = "", after: str = ""):
    l, name, _ = _section(sheet, section)
    if not (before or after):
        raise EditError("move: say which section it goes before or after")
    a, _, _ = _section(sheet, before or after)
    if a.i == l.i:
        raise EditError("a section cannot move next to itself")
    names = [n for _, n, _ in _sections(sheet)]
    k = names.index(name)
    inverse = ({"op": "move_section", "section": name, "before": names[k + 1]} if k + 1 < len(names)
               else {"op": "move_section", "section": name, "after": names[k - 1]})
    lines = sheet.splitlines()
    text = lines.pop(l.i)
    ai = a.i - (1 if a.i > l.i else 0)
    lines.insert(ai if before else ai + 1, text)
    return sh.join(lines, sheet), [inverse]


def remove_section(sheet: str, section: str):
    _, name, _ = _section(sheet, section)
    st = tsg.parse_sheet(sheet, mode="template").structure
    role = next((s.role for s in st.sections if sh.norm(s.name) == sh.norm(name)), "")
    if role in ("findings", "impression") and sum(s.role == role for s in st.sections) <= 1:
        raise EditError(f"every report needs a {role} section")
    inverses: List[dict] = []
    for pname, psec in reversed(sh.paragraphs(sheet)):
        if sh.norm(psec) == sh.norm(name):
            sheet, inv = remove_paragraph(sheet, pname)
            inverses.extend(inv)
    l, _, _ = _section(sheet, name)
    names = [n for _, n, _ in _sections(sheet)]
    k = names.index(name)
    lines = sheet.splitlines()
    text = lines.pop(l.i)
    inverses.append({"op": "insert_section_line", "line": text,
                     "before_section": names[k + 1] if k + 1 < len(names) else None})
    return sh.join(lines, sheet), inverses


def insert_section_line(sheet: str, line: str, before_section: Optional[str] = None):
    secs = sh.section_lines(sheet)
    if before_section:
        at = _section(sheet, before_section)[0].i
    elif secs:
        at = secs[-1].i + 1
    else:
        raise EditError("the template has no Report Structure sections")
    lines = sheet.splitlines()
    lines.insert(at, line)
    return sh.join(lines, sheet), []


def add_section(sheet: str, name: str, header: str, role: str, after: str = "", covers=None):
    nm = " ".join((name or "").upper().replace(":", " ").split())
    if not _SECTION_NAME.match(nm):
        raise EditError("section name: plain words")
    if role not in tsg.ROLES:
        raise EditError(f"section role: one of {', '.join(tsg.ROLES)}")
    if any(sh.norm(n) == sh.norm(nm) for _, n, _ in _sections(sheet)):
        raise EditError(f"there is already a section called {nm}")
    head = (header or "").strip()
    if '"' in head or "|" in head:
        raise EditError("section heading: plain wording only")
    line = f"SECTION {nm} | header: " + (f'"{head}"' if head else "none") + f" | role: {role}"
    if after:
        at = _section(sheet, after)[0].i + 1
    else:
        secs = sh.section_lines(sheet)
        if not secs:
            raise EditError("the template has no Report Structure sections")
        at = secs[-1].i + 1
    lines = sheet.splitlines()
    lines.insert(at, line)
    sheet2 = sh.join(lines, sheet)
    pname = _name((head.rstrip(":").strip() or nm.title()), "paragraph name")
    sheet3, _ = add_paragraph(sheet2, pname, nm, covers or [])
    return sheet3, [{"op": "remove_section", "section": nm}]


OPS = {"rename_paragraph": rename_paragraph, "move_paragraph": move_paragraph, "remove_paragraph": remove_paragraph,
       "insert_block": insert_block, "add_paragraph": add_paragraph, "rename_section": rename_section,
       "move_section": move_section, "remove_section": remove_section, "insert_section_line": insert_section_line,
       "add_section": add_section}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_layout.py tests/test_chat_router_edits.py -q`
Expected: PASS (9 + 8 tests). If `test_move_section_and_undo` or `test_add_section…` fails on `_order`, print `tsg.parse_sheet(out).errors` first. A lint rule about section order is a real constraint: keep the test's expectation that the grammar refuses it (`pytest.raises(E.EditError)`) and note it in the task report. Never loosen the guard.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_layout.py backend/tests/test_chat_router_layout.py
git commit -m "feat(chat-router): section and paragraph layout operations with inverses

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 5: Structured changes and their validation by code

**Files:**
- Create: `backend/src/rapid_reports_ai/chat_router_changes.py`
- Test: `backend/tests/test_chat_router_changes.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_changes.py`)

```python
"""Code validates each structured change (spec Flow 2, "Uncertain or rejected changes become cards"; plan
decisions 3-6)."""
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_ledger as L
from tests.template_sheet_fixtures import ROUTER_SHEET


def _ctx(instruction, ledger=None, confirmed=False):
    return CH.Ctx(ROUTER_SHEET, ledger or [], instruction, confirmed=confirmed)


def test_a_listed_value_is_applied_through_the_ledger():
    v = CH.validate("value", CH.ValueChange(name="width", to="not_needed"), _ctx("drop width"))
    assert (v.action, v.key, v.choice, v.claim) == ("ledger", "Width", {"need": "not_needed"},
                                                    "Width is no longer required.")
    assert v.change == {"kind": "value", "name": "width", "to": "not_needed", "sure": True}


def test_a_new_value_needs_its_name_in_the_instruction():
    ok = CH.validate("value", CH.ValueChange(name="Height", to="every"), _ctx("always give the height"))
    assert ok.action == "ledger" and ok.key == "Height"
    card = CH.validate("value", CH.ValueChange(name="Height", to="every"), _ctx("add the other size"))
    assert card.action == "card" and card.card["ledger_kind"] == "value" and card.invented
    ask = CH.validate("value", CH.ValueChange(name="Mass", to="not_needed"), _ctx("drop mass"))
    assert ask.action == "ask" and "Mass" in ask.reason


def test_concept_wording_from_the_instruction_or_the_sheet_is_applied():
    instr = 'when there is a prior say "Compared with the {study} of {date}."'
    v = CH.validate("concept", CH.ConceptChange(concept="comparison", state="used",
                                                default="No previous imaging available.",
                                                when_met="Compared with the {study} of {date}."), _ctx(instr))
    assert v.action == "ledger" and L.concept_state(v.choice) == (
        "used", "No previous imaging available.", "Compared with the {study} of {date}.",
        L.condition_for("comparison", "compared"))


def test_contrast_carries_its_condition_and_asks_which_is_usual():
    instr = 'say "Contrast was given." normally and "No contrast was given." when none'
    change = dict(concept="contrast", state="used", default="Contrast was given.", when_met="No contrast was given.")
    ask = CH.validate("concept", CH.ConceptChange(**change), _ctx(instr))
    assert ask.action == "ask" and ask.reason == CH.USUAL_QUESTION.format(label="contrast")
    ok = CH.validate("concept", CH.ConceptChange(**change, condition="not_given"), _ctx(instr))
    assert ok.action == "ledger" and ok.choice["condition"] == L.condition_for("contrast", "not_given")
    led, _ = L.set_choice([], "concept", "contrast", ok.choice)
    kept = CH.validate("concept", CH.ConceptChange(concept="contrast", when_met="No contrast agent was given."),
                       _ctx('use "No contrast agent was given."', led))
    assert kept.action == "ledger" and kept.choice["condition"] == ok.choice["condition"]   # carried forward


def test_dictated_and_not_used_concepts():
    d = CH.validate("concept", CH.ConceptChange(concept="comparison", state="dictated"), _ctx("whichever is dictated"))
    assert d.action == "ledger" and L.concept_state(d.choice) == ("dictated", "", "", "")
    off = CH.validate("concept", CH.ConceptChange(concept="comparison", state="not_used"), _ctx("never mention it"))
    assert off.action == "ledger" and off.claim == f"{L.CONCEPTS['comparison']}: no longer stated."


def test_a_code_rejection_never_leaks_its_internal_text():
    v = CH.validate("concept", CH.ConceptChange(concept="comparison", state="used"), _ctx("use it"))
    assert v.action == "reject" and v.reason == CH.REJECT.format(label=CH.KIND_LABEL["concept"])
    assert "wording" in v.detail and "wording" not in v.reason


def test_invented_concept_wording_becomes_a_prefilled_card_and_a_bad_slot_is_rejected():
    v = CH.validate("concept", CH.ConceptChange(concept="comparison", when_met="Compared with the {study}."),
                    _ctx("mention the prior study"))
    assert v.action == "card" and v.card["ledger_kind"] == "concept" and v.invented
    bad = CH.validate("concept", CH.ConceptChange(concept="comparison", when_met="Compared, see {reason}."),
                      _ctx('say "Compared, see {reason}."'))
    assert bad.action == "reject" and "{reason}" in bad.reason
    unknown = CH.validate("concept", CH.ConceptChange(concept="weather", state="not_used"), _ctx("x"))
    assert unknown.action == "ask"


def test_fixed_keep_reword_and_add():
    rm = CH.validate("fixed", CH.FixedChange(to="remove", line="No previous imaging available"), _ctx("stop that"))
    assert rm.action == "ledger" and rm.choice == {"keep": "remove"} and rm.key == "No previous imaging available."
    rw = CH.validate("fixed", CH.FixedChange(to="reword", line="Axial images were acquired.",
                                             text="Axial and coronal images were acquired."),
                     _ctx("say Axial and coronal images were acquired. instead"))
    assert rw.action == "edit" and rw.op == {"op": "fixed_reword", "line": "Axial images were acquired.",
                                             "text": "Axial and coronal images were acquired."}
    add = CH.validate("fixed", CH.FixedChange(to="add", paragraph="technique", text="Images were reviewed."),
                      _ctx("add Images were reviewed. to the technique"))
    assert add.action == "edit" and add.op["op"] == "fixed_add" and add.choice == {"keep": "always"}
    missing = CH.validate("fixed", CH.FixedChange(to="remove", line="Not a sentence here."), _ctx("x"))
    assert missing.action == "ask"


def test_a_fixed_edit_on_a_concepts_line_goes_through_the_concept():
    led, _ = L.set_choice([], "concept", "comparison",
                          L.concept_choice("used", "No previous imaging available.", ""))
    rm = CH.validate("fixed", CH.FixedChange(to="remove", line="No previous imaging available."),
                     _ctx("stop saying no previous imaging", led))
    assert rm.kind == "concept" and rm.action == "ledger" and L.concept_state(rm.choice)[0] == "not_used"
    rw = CH.validate("fixed", CH.FixedChange(to="reword", line="No previous imaging available.",
                                             text="No prior imaging."), _ctx("say No prior imaging. instead", led))
    assert rw.kind == "concept" and L.concept_state(rw.choice)[1] == "No prior imaging."
    dic = CH.validate("fixed", CH.FixedChange(to="dictated", line="No previous imaging available."),
                      _ctx("only when dictated", led))
    assert dic.kind == "concept" and L.concept_state(dic.choice)[0] == "dictated"
    add = CH.validate("fixed", CH.FixedChange(to="add", paragraph="Technique", text="No previous imaging available."),
                      _ctx("add No previous imaging available.", led))
    assert add.action == "ask"


def test_a_reword_that_would_clash_with_a_decided_line_is_rejected():
    led, _ = L.set_choice([], "fixed", "Axial images were acquired.", {"keep": "always"})
    led, _ = L.set_choice(led, "fixed", "Axial and coronal images were acquired.", {"keep": "dictated"})
    v = CH.validate("fixed", CH.FixedChange(to="reword", line="Axial images were acquired.",
                                            text="Axial and coronal images were acquired."),
                    _ctx("say Axial and coronal images were acquired.", led))
    assert v.action == "reject" and v.detail


def test_a_reword_not_in_the_instruction_is_a_proposal_card():
    v = CH.validate("fixed", CH.FixedChange(to="reword", line="Axial images were acquired.",
                                            text="Axial images were obtained."), _ctx("change the technique line"))
    assert v.action == "card" and v.card["kind"] == "proposal" and v.card["apply"]["op"]["op"] == "fixed_reword"
    assert v.card["title"].startswith("Make this change?")


def test_normals_reword_remove_and_add():
    rw = CH.validate("normal", CH.NormalChange(paragraph="upper", structure="alpha", to="reword",
                                               text="Alpha is unremarkable."), _ctx("say Alpha is unremarkable."))
    assert rw.action == "ledger" and rw.key == L.normal_key("Upper", "alpha") and rw.choice == {
        "text": "Alpha is unremarkable."}
    rm = CH.validate("normal", CH.NormalChange(paragraph="Upper", negative="No beta abnormality.", to="removed"),
                     _ctx("stop saying no beta abnormality"))
    assert rm.action == "ledger" and rm.choice == {"text": ""}
    add = CH.validate("normal", CH.NormalChange(paragraph="Lower", structure="delta", to="add",
                                                text="Delta is normal."), _ctx("add Delta is normal."))
    assert add.action == "edit" and add.op["op"] == "normal_add" and add.choice == {"text": "Delta is normal."}
    absent = CH.validate("normal", CH.NormalChange(paragraph="Lower", structure="delta", to="reword", text="x"),
                         _ctx("x"))
    assert absent.action == "ask"


def test_layout_is_dry_run_and_gated_on_new_names():
    ok = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top"),
                     _ctx("call the upper paragraph Top"))
    assert ok.action == "edit" and ok.op == {"op": "rename_paragraph", "paragraph": "Upper", "to": "Top"}
    bad = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Lower"),
                      _ctx("call it Lower"))
    assert bad.action == "ask"
    guess = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top"),
                        _ctx("rename the upper paragraph"))
    assert guess.action == "card" and guess.card["kind"] == "proposal"
    inside_a_word = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top"),
                                _ctx("stop using the upper name"))
    assert inside_a_word.action == "card"


def test_unsure_is_a_card_and_confirmed_skips_the_gate():
    unsure = CH.validate("value", CH.ValueChange(name="Width", to="relevant", sure=False), _ctx("width sometimes"))
    assert unsure.action == "card" and not unsure.invented
    tapped = CH.validate("value", CH.ValueChange(name="Height", to="every"), _ctx("", confirmed=True))
    assert tapped.action == "ledger"


def test_to_card_and_claim_for():
    v = CH.validate("value", CH.ValueChange(name="Width", to="every"), _ctx("width"))
    assert CH.to_card(v).card["ledger_kind"] == "value"
    assert CH.claim_for("fixed", "A line.", {"keep": "dictated"}) == '"A line." is now printed only when dictated.'
    assert CH.claim_for("normal", L.normal_key("Upper", "alpha"), {"text": ""}) == (
        "Upper: alpha is no longer stated when normal.")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_changes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router_changes'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/chat_router_changes.py`)

```python
"""Structured changes from the router's targeted calls and their validation by code (spec Flow 2 and "Uncertain or
rejected changes become cards"; plan decisions 3-6). validate() turns one change into a Verdict:
  ledger  apply through the ledger (value, concept, fixed keep, normal reword/remove)
  edit    apply a code edit (layout, FIXED reword/add, NORMAL/NEGATIVE add); `choice` set = also a decision
  card    nothing applied; a prefilled card (the Rules step's card for ledger kinds, else a proposal card)
  ask     nothing applied; `reason` is the question in the reply
  reject  nothing applied; `reason` says why
New wording passes only when the instruction holds it word for word or the sheet already prints it; a {slot} must
be {study}, {date} or one the sheet already uses."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import List, Literal, Optional

from pydantic import BaseModel

from . import chat_router_edits as E
from . import chat_router_ledger as L
from . import chat_router_sheet as sh
from .hybrid_stack.template import norm_key


# ── what the targeted calls return ──────────────────────────────────────────────────────────────────────────────
class ValueChange(BaseModel):
    name: str
    to: Literal["every", "relevant", "not_needed"]
    sure: bool = True


class ConceptChange(BaseModel):
    concept: str
    state: Optional[Literal["used", "dictated", "not_used"]] = None
    default: Optional[str] = None
    when_met: Optional[str] = None
    condition: Optional[str] = None   # the state (from CURRENT) in which when_met applies; null keeps the current one
    sure: bool = True


class FixedChange(BaseModel):
    to: Literal["always", "dictated", "remove", "reword", "add"]
    line: str = ""
    text: str = ""
    paragraph: str = ""
    sure: bool = True


class NormalChange(BaseModel):
    paragraph: str
    to: Literal["reword", "removed", "add"]
    structure: str = ""
    negative: str = ""
    text: str = ""
    sure: bool = True


class LayoutChange(BaseModel):
    op: Literal["rename_paragraph", "move_paragraph", "remove_paragraph", "add_paragraph", "rename_section",
                "move_section", "remove_section", "add_section"]
    target: str = ""
    name: str = ""
    section: str = ""
    role: str = ""
    covers: List[str] = []
    before: str = ""
    after: str = ""
    sure: bool = True


class ValueOut(BaseModel):
    changes: List[ValueChange] = []
    question: str = ""


class ConceptOut(BaseModel):
    changes: List[ConceptChange] = []
    question: str = ""


class FixedOut(BaseModel):
    changes: List[FixedChange] = []
    question: str = ""


class NormalOut(BaseModel):
    changes: List[NormalChange] = []
    question: str = ""


class LayoutOut(BaseModel):
    changes: List[LayoutChange] = []
    question: str = ""


class StyleBlock(BaseModel):
    id: str
    text: str


class StyleOut(BaseModel):
    blocks: List[StyleBlock] = []
    summary: str = ""
    question: str = ""


OUTPUTS = {"value": ValueOut, "concept": ConceptOut, "fixed": FixedOut, "normal": NormalOut, "layout": LayoutOut,
           "style": StyleOut}


# ── verdicts ────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Verdict:
    kind: str
    action: str                     # ledger | edit | card | ask | reject
    key: str = ""
    choice: Optional[dict] = None
    op: Optional[dict] = None
    card: Optional[dict] = None
    claim: str = ""                 # the reply line once applied
    reason: str = ""                # ask / reject
    invented: bool = False          # the call said sure, but its wording is neither in the instruction nor the sheet
    change: Optional[dict] = None   # the structured change as the call returned it (evidence)
    route: str = ""                 # "llm_unsure": its kind was tagged in the unsure band (decision D-R2)
    detail: str = ""                # the internal reason for a reject (evidence only, never a reply)


@dataclass
class Ctx:
    sheet: str
    ledger: List[dict]
    instruction: str                # the wording new text must come from (instruction + a rejected original)
    confirmed: bool = False         # a tapped card: the wording and sureness checks are skipped


_SLOT = re.compile(r"\{[^{}\n]*\}")
STANDARD_SLOTS = frozenset({"{study}", "{date}"})
KIND_LABEL = {"value": "the required values", "concept": "the study-level statements",
              "fixed": "the sentences printed in every report", "normal": "the normal findings",
              "layout": "the sections and paragraphs", "style": "the style"}
REJECT = "I couldn't apply the change to {label} as asked. Could you say it another way?"
USUAL_QUESTION = "Is {label} usually given for this scan? Then I'll know which wording is the usual one."


def _plain(s: str) -> str:
    return " ".join(re.sub(r"[\"“”‘’']", "", s or "").lower().split()).rstrip(".")


def in_instruction(text: str, instruction: str) -> bool:
    """The instruction holds `text` word for word (case, spacing, quote marks and a final full stop ignored)."""
    t = _plain(text)
    return bool(t) and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", _plain(instruction)) is not None


def in_sheet(text: str, sheet: str) -> bool:
    return any(l.keyword and norm_key(sh.quoted(l.text)) == norm_key(text) for l in sh.walk(sheet) if text)


def bad_slots(text: str, sheet: str) -> List[str]:
    allowed = STANDARD_SLOTS | set(_SLOT.findall(sheet or ""))
    return [s for s in _SLOT.findall(text or "") if s not in allowed]


_NEED_CLAIM = {"every": "{name} is now required in every report.",
               "relevant": "{name} is now stated only when relevant.",
               "not_needed": "{name} is no longer required."}
_KEEP_CLAIM = {"always": 'Every report now prints "{key}".', "dictated": '"{key}" is now printed only when dictated.',
               "remove": '"{key}" is no longer printed.'}


def claim_for(kind: str, key: str, choice: dict) -> str:
    """The reply line for a ledger write (also used for a tapped card)."""
    if kind == "value":
        return _NEED_CLAIM[choice["need"]].format(name=key)
    if kind == "fixed":
        return _KEEP_CLAIM[choice["keep"]].format(key=key)
    if kind == "concept":
        label = L.CONCEPTS.get(key, key)
        state, d, w, _ = L.concept_state(choice)
        if state == "not_used":
            return f"{label}: no longer stated."
        if state == "dictated":
            return f"{label}: reports now use whichever wording is dictated."
        if d and w:
            return f'{label}: reports now say "{d}", or "{w}" when it applies.'
        return f'{label}: reports now say "{d or w}".'
    para, label = L.normal_label(key)
    text = choice.get("text", "")
    return (f'{para}: the normal line for {label} now reads "{text}".' if text
            else f"{para}: {label} is no longer stated when normal.")


def proposal_card(v: Verdict) -> dict:
    """A one-tap card for a change with no ledger card (plan decision 5); Apply sends `apply` back unchanged."""
    apply = {"kind": v.kind, "key": v.key, "choice": v.choice, "op": v.op, "claim": v.claim}
    pid = hashlib.sha1(json.dumps(apply, sort_keys=True).encode()).hexdigest()[:10]
    return {"id": f"proposal:{pid}", "kind": "proposal", "title": f"Make this change? {v.claim}", "apply": apply}


def to_card(v: Verdict) -> Verdict:
    """The verdict as a card (never applied): the ledger's card for a ledger write, else a proposal card."""
    if v.action not in ("ledger", "edit"):
        return v
    c = (L.card(v.kind, v.key, v.choice) if v.action == "ledger" else None) or proposal_card(v)
    return replace(v, action="card", card=c)


def _ask(kind: str, reason: str) -> Verdict:
    return Verdict(kind, "ask", reason=reason)


def _gate(v: Verdict, texts: List[str], sure: bool, ctx: Ctx) -> Verdict:
    if ctx.confirmed:
        return v
    for t in texts:
        bad = bad_slots(t, ctx.sheet)
        if bad:
            return Verdict(v.kind, "reject", key=v.key,
                           reason=f'"{t}" uses {", ".join(bad)}, which this template cannot fill.')
    new = [t for t in texts if t and not in_instruction(t, ctx.instruction) and not in_sheet(t, ctx.sheet)]
    if not new and sure:
        return v
    return replace(to_card(v), invented=bool(new) and sure)


def _para(sheet: str, name: str) -> Optional[str]:
    return next((n for n, _ in sh.paragraphs(sheet) if sh.norm(n) == sh.norm(name)), None)


# ── one validator per kind ──────────────────────────────────────────────────────────────────────────────────────
def _value(c: ValueChange, ctx: Ctx) -> Verdict:
    known = {sh.norm(n): n for n, _ in L.values(ctx.sheet, ctx.ledger)}
    name = known.get(sh.norm(c.name))
    texts: List[str] = []
    if name is None:
        if c.to == "not_needed":
            return _ask("value", f'"{c.name}" is not one of the values reports must state.')
        name = " ".join(c.name.split())
        texts = [name]
    key, choice = L.check("value", name, {"need": c.to})
    return _gate(Verdict("value", "ledger", key=key, choice=choice, claim=claim_for("value", key, choice)),
                 texts, c.sure, ctx)


def _concept_now(name: str, ctx: Ctx):
    e = L.entry(ctx.ledger, "concept", name)
    return L.concept_state(e["choice"] if e else L.current(ctx.sheet, "concept", name))


def _concept(c: ConceptChange, ctx: Ctx) -> Verdict:
    if c.concept not in L.CONCEPTS:
        return _ask("concept", "I can change these study-level statements: " + ", ".join(L.CONCEPTS.values())
                    + ". Which did you mean?")
    state0, d0, w0, cond0 = _concept_now(c.concept, ctx)
    d = d0 if c.default is None else c.default.strip()
    w = w0 if c.when_met is None else c.when_met.strip()
    state = c.state or ("used" if (c.default or c.when_met) else state0)
    cond = L.condition_for(c.concept, c.condition) if c.condition else cond0   # carried forward
    conditions = [x for x in L.concept_states(c.concept).values() if x]
    if state == "used" and not cond and len(conditions) > 1:
        return _ask("concept", USUAL_QUESTION.format(label=L.CONCEPTS[c.concept].lower()))
    key, choice = L.check("concept", c.concept, L.concept_choice(state, d, w, cond))
    texts = [t for t, old in ((c.default, d0), (c.when_met, w0)) if t and norm_key(t) != norm_key(old)]
    return _gate(Verdict("concept", "ledger", key=key, choice=choice, claim=claim_for("concept", key, choice)),
                 texts, c.sure, ctx)


def _fixed_as_concept(c: FixedChange, owner: str, line: str, ctx: Ctx) -> ConceptChange:
    """A FIXED edit on a line a concept owns, as the concept change it means (plan decision 6)."""
    _, d0, w0, _ = _concept_now(owner, ctx)
    is_default = norm_key(line) == norm_key(d0)
    field_ = "default" if is_default else "when_met"
    if c.to == "reword":
        return ConceptChange(concept=owner, sure=c.sure, **{field_: c.text})
    if c.to == "dictated":
        return ConceptChange(concept=owner, state="dictated", sure=c.sure)
    if c.to == "remove":
        if w0 if is_default else d0:     # the concept keeps its other wording
            return ConceptChange(concept=owner, sure=c.sure, **{field_: ""})
        return ConceptChange(concept=owner, state="not_used", sure=c.sure)
    return ConceptChange(concept=owner, sure=c.sure)   # "always": the concept keeps its wording as it is


def _fixed(c: FixedChange, ctx: Ctx) -> Verdict:
    lines = [sh.quoted(l.text) for l in sh.walk(ctx.sheet) if l.keyword == "FIXED"]
    match = next((t for t in lines if c.line and norm_key(t) == norm_key(c.line)), None)
    if c.to == "add":
        if match or any(norm_key(t) == norm_key(c.text) for t in lines) or L.concept_owner(
                ctx.sheet, ctx.ledger, c.text):
            return _ask("fixed", f'"{c.text or c.line}" is already printed in every report.')
        para = _para(ctx.sheet, c.paragraph)
        if para is None:
            return _ask("fixed", f'Which part of the report should "{c.text}" go in?')
        key, choice = L.check("fixed", c.text, {"keep": "always"})
        v = Verdict("fixed", "edit", key=key, choice=choice, op={"op": "fixed_add", "paragraph": para, "text": key},
                    claim=f'Every report now prints "{key}" in {para}.')
        return _gate(v, [key], c.sure, ctx)
    if match is None:
        return _ask("fixed", f'I couldn\'t find "{c.line}" among the sentences printed in every report.')
    owner = L.concept_owner(ctx.sheet, ctx.ledger, match)
    if owner:
        return _concept(_fixed_as_concept(c, owner, match, ctx), ctx)
    if c.to == "reword":
        key, _ = L.check("fixed", c.text, {"keep": "always"})
        L.rekey_fixed(ctx.ledger, match, key)          # a clash with a decided line is a reject now, not later
        v = Verdict("fixed", "edit", key=key, op={"op": "fixed_reword", "line": match, "text": key},
                    claim=f'"{match}" now reads "{key}".')
        return _gate(v, [key], c.sure, ctx)
    key, choice = L.check("fixed", match, {"keep": c.to})
    return _gate(Verdict("fixed", "ledger", key=key, choice=choice, claim=claim_for("fixed", key, choice)),
                 [], c.sure, ctx)


def _normal(c: NormalChange, ctx: Ctx) -> Verdict:
    para = _para(ctx.sheet, c.paragraph)
    if para is None:
        return _ask("normal", f"I couldn't find the {c.paragraph} part of the report.")
    if c.to == "add":
        text = " ".join((c.text or c.negative).split())
        if c.structure and not c.negative:
            key = L.normal_key(para, c.structure)
            if (L.current(ctx.sheet, "normal", key) or {}).get("text"):
                return _ask("normal", f"{para} already has a normal line for {c.structure}.")
            op = {"op": "normal_add", "paragraph": para, "structure": " ".join(c.structure.split()), "text": text}
        else:
            key = L.negative_key(para, text)
            op = {"op": "negative_add", "paragraph": para, "text": text}
        key, choice = L.check("normal", key, {"text": text})
        v = Verdict("normal", "edit", key=key, choice=choice, op=op, claim=f'{para}: reports now state "{text}".')
        return _gate(v, [text], c.sure, ctx)
    if c.negative:
        key = L.negative_key(para, c.negative)
    elif c.structure:
        key = L.normal_key(para, c.structure)
    else:
        return _ask("normal", f"Which normal line in {para} did you mean?")
    if not (L.current(ctx.sheet, "normal", key) or {}).get("text"):
        return _ask("normal", f"{para} has no normal line for {c.negative or c.structure}.")
    text = "" if c.to == "removed" else " ".join(c.text.split())
    key, choice = L.check("normal", key, {"text": text})
    return _gate(Verdict("normal", "ledger", key=key, choice=choice, claim=claim_for("normal", key, choice)),
                 [text] if text else [], c.sure, ctx)


_LAYOUT_CLAIM = {
    "rename_paragraph": "The {target} paragraph is now called {name}.",
    "move_paragraph": "The {target} paragraph now comes {where}.",
    "remove_paragraph": "The {target} paragraph is removed.",
    "add_paragraph": "A new {name} paragraph is added.",
    "rename_section": 'The {target} section heading now reads "{name}".',
    "move_section": "The {target} section now comes {where}.",
    "remove_section": "The {target} section is removed.",
    "add_section": "A new {name} section is added.",
}


def layout_op(c: LayoutChange) -> dict:
    o = c.op
    if o == "rename_paragraph":
        return {"op": o, "paragraph": c.target, "to": c.name}
    if o == "move_paragraph":
        return {"op": o, "paragraph": c.target, "before": c.before, "after": c.after}
    if o == "remove_paragraph":
        return {"op": o, "paragraph": c.target}
    if o == "add_paragraph":
        return {"op": o, "name": c.name, "section": c.section, "covers": list(c.covers), "after": c.after}
    if o == "rename_section":
        return {"op": o, "section": c.target, "header": c.name}
    if o == "move_section":
        return {"op": o, "section": c.target, "before": c.before, "after": c.after}
    if o == "remove_section":
        return {"op": o, "section": c.target}
    return {"op": "add_section", "name": c.name, "header": c.name, "role": c.role, "after": c.after,
            "covers": list(c.covers)}


def _layout(c: LayoutChange, ctx: Ctx) -> Verdict:
    op = layout_op(c)
    try:
        E.apply_op(ctx.sheet, op)            # dry run: the target exists and the result is lint-clean
    except E.EditError as e:
        return _ask("layout", f"I couldn't change the layout that way: {e}.")
    where = f"before {c.before}" if c.before else f"after {c.after}"
    claim = _LAYOUT_CLAIM[c.op].format(target=c.target, name=c.name, where=where)
    texts = [c.name] if c.op in ("rename_paragraph", "add_paragraph", "rename_section", "add_section") else []
    if c.op in ("add_paragraph", "add_section"):
        texts += list(c.covers)
    return _gate(Verdict("layout", "edit", op=op, claim=claim), texts, c.sure, ctx)


_VALIDATORS = {"value": _value, "concept": _concept, "fixed": _fixed, "normal": _normal, "layout": _layout}


def validate(kind: str, change: BaseModel, ctx: Ctx) -> Verdict:
    try:
        v = _VALIDATORS[kind](change, ctx)
    except L.Rejected as e:   # internal text goes to the evidence only (plan decision 15)
        v = Verdict(kind, "reject", reason=REJECT.format(label=KIND_LABEL[kind]), detail=str(e)[:300])
    v.change = {"kind": kind, **change.model_dump()}
    return v


def parse_change(kind: str, data: dict) -> BaseModel:
    """A stored or re-routed change dict back into its model (kind key dropped)."""
    model = {"value": ValueChange, "concept": ConceptChange, "fixed": FixedChange, "normal": NormalChange,
             "layout": LayoutChange}[kind]
    return model(**{k: v for k, v in (data or {}).items() if k != "kind"})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_changes.py -q`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_changes.py backend/tests/test_chat_router_changes.py
git commit -m "feat(chat-router): structured changes validated by code into apply, card or ask

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 6: What each targeted call sees

**Files:**
- Create: `backend/src/rapid_reports_ai/chat_router_views.py`
- Test: `backend/tests/test_chat_router_views.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_views.py`)

```python
"""Each targeted call gets only its part of the sheet (spec Flow 2)."""
from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import chat_router_views as V
from tests.template_sheet_fixtures import ROUTER_SHEET


def test_value_view_lists_each_value_with_its_need():
    led, _ = L.set_choice(L.seed_values([], ROUTER_SHEET), "value", "Depth", {"need": "relevant"})
    v = V.view("value", ROUTER_SHEET, led)
    assert "- Width: every report must state it" in v and "- Depth: stated only when relevant" in v
    assert "NORMAL" not in v and "Alpha" not in v


def test_concept_view_names_every_concept_and_the_printed_sentences():
    v = V.view("concept", ROUTER_SHEET, [])
    for name in L.CONCEPTS:
        assert f"- {name} (" in v
    assert "- contrast (Contrast; states: given, not_given): not stated" in v
    assert '- "No previous imaging available."' in v


def test_concept_view_names_the_usual_state_and_the_condition():
    from tests.template_sheet_fixtures import ROUTER_SHEET_CONCEPT
    v = V.view("concept", ROUTER_SHEET_CONCEPT, [])
    assert ('- comparison (Comparison with previous imaging; states: none, compared): default '
            '"No previous imaging available." (printed when none); when_met "Compared with the {study} of {date}." '
            '(condition: compared)') in v


def test_fixed_view_lists_sentences_with_their_paragraph():
    v = V.view("fixed", ROUTER_SHEET, [])
    assert '- in Technique: "Axial images were acquired."' in v and "PARAGRAPHS: Technique, Upper, Lower" in v


def test_normal_view_groups_by_paragraph():
    v = V.view("normal", ROUTER_SHEET, [])
    assert 'Paragraph "Upper" (reports: alpha, beta):' in v
    assert '  normal alpha: "Alpha is normal."' in v and '  negative: "No beta abnormality."' in v


def test_layout_view_uses_title_case_section_names():
    v = V.view("layout", ROUTER_SHEET, [])
    assert '- Findings (printed heading "Findings:", role findings)' in v and "- Lower, in section Findings" in v
    assert "FINDINGS" not in v


def test_style_view_shows_prose_blocks_only():
    v = V.view("style", ROUTER_SHEET, [])
    assert '[b4] under "Impression Construction":\nLead with the most important finding.' in v
    assert "An imaging study" not in v and "NORMAL" not in v and "FIXED" not in v
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_views.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router_views'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/chat_router_views.py`)

```python
"""What each targeted call of the chat-edit router sees (spec Flow 2: "gets only the part of the sheet it needs").
Plain text in report terms; section names in Title Case (plan decision 7: upper-case words are a Cerebras risk) and
matched back case-insensitively by code."""
from __future__ import annotations

import re
from typing import List

from . import chat_router_ledger as L
from . import chat_router_sheet as sh

_BRACKET = re.compile(r"\[([^\]]+)\]")
_ITEM = re.compile(r'"([^"]+)"')
_SEC = re.compile(r'SECTION\s+(?P<name>.+?)\s*\|\s*header:\s*(?:none|"(?P<header>[^"]*)")\s*\|\s*role:\s*(?P<role>\w+)')
NEED_TEXT = {"every": "every report must state it", "relevant": "stated only when relevant",
             "not_needed": "not needed"}


def _values(sheet: str, ledger: List[dict]) -> str:
    rows = [f"- {n}: {NEED_TEXT.get(need, need)}" for n, need in L.values(sheet, ledger)]
    return "VALUES:\n" + ("\n".join(rows) or "- (none yet)")


def _printed(sheet: str) -> List[str]:
    return [sh.quoted(l.text) for l in sh.walk(sheet) if l.keyword == "FIXED"]


def _concepts(sheet: str, ledger: List[dict]) -> str:
    rows = []
    for name, label in L.CONCEPTS.items():
        e = L.entry(ledger, "concept", name)
        try:
            choice = e["choice"] if e else L.current(sheet, "concept", name)
        except L.Rejected:
            choice = None
        state, d, w, cond = L.concept_state(choice)
        states = L.concept_states(name)
        when = next((s for s, c in states.items() if c and c == cond), "")
        usual = next((s for s in states if s != when), "") if when else ""
        head = f"- {name} ({label}; states: {', '.join(states)})"
        if state == "not_used":
            rows.append(f"{head}: not stated")
        elif state == "dictated":
            rows.append(f"{head}: whichever wording is dictated")
        else:
            rows.append(f'{head}: default "{d}" (printed when {usual or "nothing else is dictated"}); '
                        f'when_met "{w}" (condition: {when or "none"})')
    printed = [f'- "{t}"' for t in _printed(sheet)]
    return ("STUDY-LEVEL STATEMENTS (key (label): current wording):\n" + "\n".join(rows)
            + "\n\nSENTENCES PRINTED IN EVERY REPORT (a default may reuse one):\n" + ("\n".join(printed) or "- (none)"))


def _fixed(sheet: str, ledger: List[dict]) -> str:
    rows = [f'- in {l.paragraph or l.heading}: "{sh.quoted(l.text)}"' for l in sh.walk(sheet) if l.keyword == "FIXED"]
    return ("SENTENCES PRINTED IN EVERY REPORT:\n" + ("\n".join(rows) or "- (none)")
            + "\n\nPARAGRAPHS: " + ", ".join(n for n, _ in sh.paragraphs(sheet)))


def _normals(sheet: str, ledger: List[dict]) -> str:
    lines = sh.walk(sheet)
    out = []
    for name, _ in sh.paragraphs(sheet):
        start, end = sh.paragraph_span(sheet, name)
        block = lines[start:end]
        covers = [x for l in block if l.keyword == "COVERS" for x in _ITEM.findall(l.text)]
        out.append(f'Paragraph "{name}"' + (f" (reports: {', '.join(covers)})" if covers else "") + ":")
        for l in block:
            if l.keyword == "NORMAL":
                m = _BRACKET.search(l.text)
                out.append(f'  normal {m.group(1) if m else "?"}: "{sh.quoted(l.text)}"')
            elif l.keyword == "NEGATIVE":
                out.append(f'  negative: "{sh.quoted(l.text)}"')
    return "NORMAL FINDINGS BY PARAGRAPH:\n" + "\n".join(out)


def _layout(sheet: str, ledger: List[dict]) -> str:
    secs = []
    for l in sh.section_lines(sheet):
        m = _SEC.search(l.text)
        if m:
            head = f'"{m.group("header")}"' if m.group("header") else "none"
            secs.append(f"- {m.group('name').strip().title()} (printed heading {head}, role {m.group('role')})")
    paras = [f"- {n}, in section {s.title()}" for n, s in sh.paragraphs(sheet)]
    return "SECTIONS (in print order):\n" + "\n".join(secs) + "\n\nPARAGRAPHS (in order):\n" + "\n".join(paras)


def _style(sheet: str, ledger: List[dict]) -> str:
    return "PROSE BLOCKS:\n" + "\n\n".join(f'[{b.id}] under "{b.heading}":\n{b.text}' for b in sh.prose_blocks(sheet))


VIEWS = {"value": _values, "concept": _concepts, "fixed": _fixed, "normal": _normals, "layout": _layout,
         "style": _style}


def view(kind: str, sheet: str, ledger: List[dict]) -> str:
    return VIEWS[kind](sheet, ledger or [])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_views.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Run Phase 1 together and commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_ledger.py tests/test_chat_router_sheet.py tests/test_chat_router_edits.py tests/test_chat_router_layout.py tests/test_chat_router_changes.py tests/test_chat_router_views.py -q`
Expected: PASS (all)

```bash
git add backend/src/rapid_reports_ai/chat_router_views.py backend/tests/test_chat_router_views.py
git commit -m "feat(chat-router): the part of the template each targeted call sees

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 2: Jev tags, targeted calls, the orchestrator

### Task 7: The Jev questions (tags and rule-in-disguise)

**Files:**
- Create: `backend/src/rapid_reports_ai/chat_router_jev.py`
- Test: `backend/tests/test_chat_router_jev.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_jev.py`)

```python
"""The router's Jev questions (spec Flow 1 and 3)."""
import json

import httpx
import pytest

from rapid_reports_ai import chat_router_jev as J


def _transport(answers, seen):
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": answers(body)})
    return httpx.MockTransport(handler)


def test_the_seven_questions_are_the_specs():
    assert J.KINDS == ("value", "concept", "fixed", "normal", "layout", "style", "misfit")
    assert all(J.QUESTIONS[k].startswith("Does the INSTRUCTION ask") for k in J.KINDS)
    assert "values every report must state" in J.QUESTIONS["value"]
    assert "does not belong in a report of this scan type" in J.QUESTIONS["misfit"]
    assert (J.TAG_UNSURE, J.TAG_MIN, J.REQUIRES_MIN) == (0.35, 0.5, 0.5)


async def test_tag_asks_all_kinds_in_one_call_with_the_scan_type_and_context():
    seen = []
    scores = {k: 0.1 * i for i, k in enumerate(J.KINDS)}
    t = _transport(lambda body: {k: {"noul": scores[k]} for k in body["questions"]}, seen)
    out = await J.tag("drop width and keep it short", "Router test", context="Done.", transport=t)
    assert out == scores and len(seen) == 1
    assert "SCAN TYPE: Router test" in seen[0]["state"] and "drop width" in seen[0]["state"]
    assert "PREVIOUS REPLY" in seen[0]["state"]
    assert all(q["type"] == "noul" for q in seen[0]["questions"].values())


async def test_tag_raises_on_incomplete_answers():
    t = _transport(lambda body: {"value": {"noul": 0.9}}, [])
    with pytest.raises(ValueError):
        await J.tag("x", "", transport=t)


async def test_requires_asks_one_call_per_line_in_order():
    seen = []
    t = _transport(lambda body: {"q": {"noul": 0.9 if "Always" in body["state"] else 0.1}}, seen)
    assert await J.requires(["Keep it brief.", "Always state the size."], transport=t) == [0.1, 0.9]
    assert len(seen) == 2 and seen[0]["questions"]["q"]["instructions"] == J.REQUIRES
    assert await J.requires([], transport=t) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_jev.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router_jev'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/chat_router_jev.py`)

```python
"""The chat-edit router's Jev questions (spec Flow 1 and 3): one call tags a whole instruction with a yes/no per
kind of change (no splitting: a mixed instruction is several yeses); one call per new prose line asks whether a
style edit hid a rule. Thresholds are lab-set constants (scripts/chat_router_lab.py; Hassan sets them)."""
from __future__ import annotations

import asyncio
import os
from typing import Dict, List

from .jev_client import JEV_MODEL, jev_post

TIMEOUT_S = 4.0
TAG_MIN = 0.5        # a kind at or above is worked (spec: threshold 0.5 as elsewhere)
TAG_UNSURE = 0.35    # [TAG_UNSURE, TAG_MIN): the kind's changes become cards, never applied
REQUIRES_MIN = 0.5   # a new prose line at or above is a rule in disguise

KINDS = ("value", "concept", "fixed", "normal", "layout", "style", "misfit")
QUESTIONS: Dict[str, str] = {
    "value": "Does the INSTRUCTION ask to change which values every report must state?",
    "concept": "Does the INSTRUCTION ask to change how comparison / prior imaging, contrast, sequences not acquired "
               "or a technical limitation is worded?",
    "fixed": "Does the INSTRUCTION ask to change a sentence printed in every report?",
    "normal": "Does the INSTRUCTION ask to change how a normal finding for a region is worded, or whether it is "
              "stated?",
    "layout": "Does the INSTRUCTION ask to add, remove, rename or reorder a section or paragraph?",
    "style": "Does the INSTRUCTION ask to change style, tone, length or phrasing?",
    "misfit": "Does the INSTRUCTION ask for something that does not belong in a report of this scan type?",
}
REQUIRES = "Does this LINE require the report to state something?"


def _score(answers: dict, key: str) -> float:
    v = (answers.get(key) or {}).get("noul")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("jev: incomplete answers")
    return float(v)


async def tag(instruction: str, scan_type: str = "", context: str = "", transport=None) -> Dict[str, float]:
    """P(yes) per kind in KINDS, one Jev call. Raises on any failure (the caller falls back)."""
    state = f"SCAN TYPE: {scan_type or 'not given'}\n\nINSTRUCTION:\n{(instruction or '').strip()}"
    if (context or "").strip():
        state += f"\n\nPREVIOUS REPLY (context only):\n{context.strip()}"
    r = await jev_post({"model": JEV_MODEL, "state": state,
                        "questions": {k: {"type": "noul", "instructions": QUESTIONS[k]} for k in KINDS}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    answers = r.json().get("answers") or {}
    return {k: _score(answers, k) for k in KINDS}


async def requires(lines: List[str], transport=None) -> List[float]:
    """P(the line requires the report to state something), one Jev call per line, in order. Raises on failure."""
    async def one(line: str) -> float:
        r = await jev_post({"model": JEV_MODEL, "state": f"LINE:\n{line}",
                            "questions": {"q": {"type": "noul", "instructions": REQUIRES}}},
                           os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
        r.raise_for_status()
        return _score(r.json().get("answers") or {}, "q")
    if not lines:
        return []
    return list(await asyncio.gather(*(one(l) for l in lines)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_jev.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_jev.py backend/tests/test_chat_router_jev.py
git commit -m "feat(chat-router): Jev kind tags and the rule-in-disguise question

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 8: The targeted calls (prompts and the Qwen call)

**Files:**
- Create: `backend/src/rapid_reports_ai/chat_router_calls.py`
- Test: `backend/tests/test_chat_router_calls.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_calls.py`)

```python
"""The targeted calls: one kind each, the whole instruction, only their part of the sheet (spec Flow 2)."""
from rapid_reports_ai import chat_router_calls as C
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import enhancement_utils as eu
from tests.test_template_sheet_lab_prompts import CLINICAL


def test_prompts_are_case_agnostic_and_scoped():
    for kind, system in C.SYSTEM.items():
        low = system.lower()
        for word in CLINICAL:
            assert word not in low, (kind, word)
        assert "Ignore every other part of the INSTRUCTION" in system, kind
    assert set(C.SYSTEM) == set(CH.OUTPUTS)


def test_user_prompt_carries_instruction_view_context_and_a_rejection():
    p = C.user_prompt("drop width", "VALUES:\n- Width", "Done.",
                      {"original_instruction": "remove width", "rejected_claim": "Width is no longer required."})
    assert p.startswith("INSTRUCTION:\ndrop width") and "CURRENT:\nVALUES:" in p and "YOUR PREVIOUS REPLY" in p
    assert 'They had asked: "remove width"' in p and "Width is no longer required." in p
    assert "REJECTED" not in C.user_prompt("x", "v")


async def test_call_kind_uses_qwen_with_the_kinds_output_type(monkeypatch):
    seen = {}

    async def run(model_name, output_type, system_prompt, user_prompt, api_key, model_settings):
        seen.update(model=model_name, out=output_type, system=system_prompt, settings=model_settings)
        return type("R", (), {"output": output_type()})()
    monkeypatch.setattr(eu, "_run_agent_with_model", run)
    out = await C.call_kind("value", "drop width", "VALUES:\n- Width")
    assert isinstance(out, CH.ValueOut) and seen["model"] == eu.MODEL_CONFIG["SKILL_SHEET_REFINER"]
    assert seen["system"] == C.SYSTEM["value"] and seen["settings"]["temperature"] == 0


async def test_call_kind_retries_once_on_gpt_oss(monkeypatch):
    models = []

    async def run(model_name, output_type, system_prompt, user_prompt, api_key, model_settings):
        models.append(model_name)
        if len(models) == 1:
            raise TimeoutError()
        return type("R", (), {"output": output_type()})()
    monkeypatch.setattr(eu, "_run_agent_with_model", run)
    out = await C.call_kind("style", "shorter", "PROSE BLOCKS:")
    assert isinstance(out, CH.StyleOut)
    assert models == [eu.MODEL_CONFIG["SKILL_SHEET_REFINER"], eu.MODEL_CONFIG["STACK_REVIEW_FALLBACK"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_calls.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router_calls'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/chat_router_calls.py`)

```python
"""The chat-edit router's targeted calls (spec Flow 2): one lightweight Qwen call per tagged kind. Each reads the
whole instruction, is told to handle only its own kind and ignore the rest, sees only its part of the template
(chat_router_views), and answers with structured changes (chat_router_changes.OUTPUTS); style answers with edited
prose blocks. One retry on gpt-oss (another provider) if the call fails. Prompts are case-agnostic."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel

from . import chat_router_changes as CH

logger = logging.getLogger(__name__)

CALL_TIMEOUT_S = 15.0
FALLBACK_TIMEOUT_S = 20.0
SETTINGS = {"temperature": 0, "max_tokens": 2500, "reasoning_effort": "low"}
STYLE_SETTINGS = {"temperature": 0, "max_tokens": 6000, "reasoning_effort": "low"}

COMMON = (
    "You change one part of a radiology report template by returning structured changes. The radiologist never "
    "sees the template; code applies your changes and writes the reply.\n"
    "Read the whole INSTRUCTION. Handle only SCOPE. Ignore every other part of the INSTRUCTION: other editors "
    "handle it. If nothing in the INSTRUCTION is about SCOPE, return no changes.\n"
    "Use only the names shown under CURRENT, copied exactly. Copy new wording exactly as the INSTRUCTION gives it. "
    "If the INSTRUCTION does not give the exact wording, write the wording you think is meant and set sure to false. "
    "Set sure to false whenever you are not certain what is meant.\n"
    "If the INSTRUCTION is about SCOPE but you cannot tell what to change, return no changes and put one short "
    'question for the radiologist in "question", in plain report language.\n\n')

_KIND = {
    "value": (
        "which values (measured quantities) every report must state",
        'Each change names a value and sets "to": "every" (every report must state it; it is flagged when missing), '
        '"relevant" (stated only when relevant, never flagged) or "not_needed" (no longer required). A value not '
        'listed under CURRENT may be added only with "every" or "relevant", using the name the INSTRUCTION gives.'),
    "concept": (
        "how the study-level statements listed under CURRENT are worded, or whether they are stated",
        'Each change names one statement by its key (the word before the brackets under CURRENT) and sets any of: '
        '"state" ("used"; "dictated": use whichever wording is dictated; "not_used": not stated), "default" (the '
        'usual sentence, printed unless the dictation says otherwise; it may reuse a sentence listed under '
        'CURRENT), "when_met" (the sentence printed when the dictation states the other state; it may hold {study} '
        'and {date} for values the dictation gives) and "condition" (that other state, one of the states listed '
        'for the statement; the default belongs to the remaining, usual state). Leave a field null to keep it as it '
        'is. If a statement has two states and you cannot tell which is usual, leave "condition" null.'),
    "fixed": (
        "the sentences printed in every report",
        '"to": "always" (printed in every report), "dictated" (printed only when the dictation says it), "remove" '
        '(no longer printed), "reword" ("line" is the current sentence, "text" the new wording) or "add" ("text" is '
        'the new sentence, "paragraph" the paragraph it goes in, from CURRENT). "line" is copied exactly from '
        'CURRENT.'),
    "normal": (
        "how a normal finding is worded for a part of the report, or whether it is stated",
        'Each change names the "paragraph", and either the "structure" of a normal line or the current text of a '
        'negative line ("negative"), copied exactly from CURRENT. "to": "reword" (with the new "text"), "removed" '
        '(no longer stated) or "add" (a new normal line for a structure, or, with "negative" set, a new negative '
        'sentence; "text" is the sentence).'),
    "layout": (
        "the sections and paragraphs of the report: adding, removing, renaming or reordering them",
        '"op" is one of rename_paragraph, move_paragraph, remove_paragraph, add_paragraph, rename_section, '
        'move_section, remove_section, add_section. "target" names the existing paragraph or section as shown '
        'under CURRENT. "name" is the new name (rename_paragraph, add_paragraph), the new printed heading '
        '(rename_section) or the new section\'s printed heading (add_section). "before" or "after" names the '
        'paragraph or section it goes next to. add_paragraph: "section" it belongs to and "covers", the structures '
        'it reports. add_section: "role" (one of findings, impression, history, technique, comparison, other), and '
        '"covers" when its role is findings.'),
}

STYLE = (
    "You edit the prose guidance of a radiology report template: how reports are written (voice, tone, length, "
    "phrasing). The radiologist never sees the template.\n"
    "Read the whole INSTRUCTION. Handle only style, tone, length or phrasing. Ignore every other part of the "
    "INSTRUCTION: other editors handle which values reports state, study-level statements, sentences printed in "
    "every report, normal findings, and sections and paragraphs.\n"
    "You get the template's prose BLOCKS under CURRENT, each with an id. Return only the blocks you change, each "
    "with its id and its complete new text. Never add a line that tells reports to always state something. Never "
    "write a line that starts with an upper-case keyword. Change nothing the INSTRUCTION does not ask for.\n"
    '"summary": one sentence, in plain report language, saying what future reports will do differently (for '
    'example: "The impression will be shorter."). If nothing in the INSTRUCTION is about style, return no blocks. '
    'If it is about style but unclear, return no blocks and put one short question in "question".')

SYSTEM = {k: COMMON.replace("SCOPE", scope) + detail for k, (scope, detail) in _KIND.items()}
SYSTEM["style"] = STYLE


def user_prompt(instruction: str, view: str, context: str = "", rejection: Optional[dict] = None) -> str:
    s = f"INSTRUCTION:\n{(instruction or '').strip()}\n\nCURRENT:\n{(view or '').strip()}"
    if (context or "").strip():
        s += f"\n\nYOUR PREVIOUS REPLY (context only):\n{context.strip()}"
    if rejection:
        s += ("\n\nTHE RADIOLOGIST REJECTED THE LAST CHANGE.\n"
              f'They had asked: "{(rejection.get("original_instruction") or "").strip()}"\n'
              f'The change made was: "{(rejection.get("rejected_claim") or "").strip()}"\n'
              "Treat the INSTRUCTION as their clarification of that request.")
    return s


async def call_kind(kind: str, instruction: str, view: str, context: str = "",
                    rejection: Optional[dict] = None) -> BaseModel:
    """The kind's structured output (CH.OUTPUTS[kind]); raises when both models fail."""
    from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model
    out_type = CH.OUTPUTS[kind]
    settings = STYLE_SETTINGS if kind == "style" else SETTINGS
    prompt = user_prompt(instruction, view, context, rejection)

    async def call(model: str, timeout: float) -> BaseModel:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=model, output_type=out_type, system_prompt=SYSTEM[kind], user_prompt=prompt, api_key="",
            model_settings=dict(settings)), timeout)
        return r.output

    try:
        return await call(MODEL_CONFIG["SKILL_SHEET_REFINER"], CALL_TIMEOUT_S)
    except Exception as e:
        logger.warning("[chat-router.%s] %s: %s; fallback %s", kind, type(e).__name__, str(e)[:200],
                       MODEL_CONFIG["STACK_REVIEW_FALLBACK"])
        return await call(MODEL_CONFIG["STACK_REVIEW_FALLBACK"], FALLBACK_TIMEOUT_S)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_calls.py -q`
Expected: PASS (4 tests). If the case-agnostic test fails, reword the prompt; never trim `CLINICAL`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router_calls.py backend/tests/test_chat_router_calls.py
git commit -m "feat(chat-router): targeted per-kind calls with case-agnostic prompts and a gpt-oss retry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 9: `route_turn` for the rule kinds

**Files:**
- Create: `backend/src/rapid_reports_ai/chat_router.py`
- Test: `backend/tests/test_chat_router.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router.py`)

```python
"""The chat-edit router end to end with fake Jev and fake targeted calls (spec "Testing", unit)."""
import pytest

from rapid_reports_ai import chat_router as R
from rapid_reports_ai import chat_router_calls as C
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_jev as J
from rapid_reports_ai import chat_router_ledger as L
from tests.template_sheet_fixtures import ROUTER_SHEET


@pytest.fixture(autouse=True)
def no_unit_checks(monkeypatch):
    from rapid_reports_ai import template_sheet_save as S

    async def none(structure, sheet):
        return []
    monkeypatch.setattr(S, "check_units", none)


def tags(**scores):
    return {k: scores.get(k, 0.0) for k in J.KINDS}


@pytest.fixture
def fake(monkeypatch):
    state = {"tags": tags(), "calls": {}, "requires": {}, "seen": []}

    async def tag(instruction, scan_type="", context="", transport=None):
        if isinstance(state["tags"], Exception):
            raise state["tags"]
        return state["tags"]

    async def call_kind(kind, instruction, view, context="", rejection=None):
        state["seen"].append((kind, instruction))
        r = state["calls"].get(kind)
        if isinstance(r, Exception):
            raise r
        return r if r is not None else CH.OUTPUTS[kind]()

    async def requires(lines, transport=None):
        if isinstance(state["requires"], Exception):
            raise state["requires"]
        return [state["requires"].get(l, 0.0) for l in lines]

    monkeypatch.setattr(J, "tag", tag)
    monkeypatch.setattr(C, "call_kind", call_kind)
    monkeypatch.setattr(J, "requires", requires)
    return state


async def test_a_failed_tag_call_falls_back(fake):
    fake["tags"] = TimeoutError()
    with pytest.raises(R.Fallback):
        await R.route_turn(ROUTER_SHEET, [], "drop width")


async def test_misfit_or_no_kind_asks_and_changes_nothing(fake):
    fake["tags"] = tags(misfit=0.9, value=0.8)
    t = await R.route_turn(ROUTER_SHEET, [], "add the weather")
    assert not t.applied and t.sheet == ROUTER_SHEET and "Router test" in t.reply and fake["seen"] == []
    fake["tags"] = tags(value=0.2)
    t = await R.route_turn(ROUTER_SHEET, [], "hmm")
    assert not t.applied and "What should they do differently?" in t.reply
    assert t.evidence["route"] == "ask"


async def test_a_value_change_is_applied_through_the_ledger(fake):
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and t.reply == "Width is no longer required."
    assert t.claim == "Width is no longer required." and t.records[0]["type"] == "ledger"
    width = L.entry(t.ledger, "value", "Width")
    assert width["choice"] == {"need": "not_needed"} and width["source"] == "chat"
    assert [k for k, _ in fake["seen"]] == ["value"]


async def test_a_mixed_instruction_applies_each_tagged_kind(fake):
    fake["tags"] = tags(value=0.9, fixed=0.8)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    fake["calls"]["fixed"] = CH.FixedOut(changes=[CH.FixedChange(to="remove", line="No previous imaging available.")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and stop printing no previous imaging")
    assert t.applied and "No previous imaging available." not in t.sheet and 'LIST_MISSING ["Depth"]' in t.sheet
    assert sorted(k for k, _ in fake["seen"]) == ["fixed", "value"]
    assert t.reply.splitlines() == ["Width is no longer required.", '"No previous imaging available." is no longer printed.']


async def test_an_unsure_tag_lets_the_call_decide_and_marks_the_route(fake):
    fake["tags"] = tags(value=0.4)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "width maybe")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and not t.cards
    assert L.entry(t.ledger, "value", "Width")["route"] == "llm_unsure"
    assert t.records[0]["route"] == "llm_unsure" and t.evidence["changes"][0]["route"] == "llm_unsure"
    assert t.evidence["unsure"] == ["value"]


async def test_an_unsure_call_that_decides_nothing_changes_nothing(fake):
    fake["tags"] = tags(value=0.4)
    t = await R.route_turn(ROUTER_SHEET, [], "width maybe")
    assert not t.applied and t.records == [] and t.reply == "No change was needed."


async def test_applied_only_when_the_sheet_or_ledger_changed(fake, monkeypatch):
    async def same(sheet, previous, ledger):
        return L.Saved("unchanged", previous, [], "")
    monkeypatch.setattr(L, "save", same)
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert not t.applied and t.records == [] and t.claim == ""


async def test_unmatched_decisions_are_surfaced(fake, monkeypatch):
    real = L.save

    async def with_unmatched(sheet, previous, ledger):
        out = await real(sheet, previous, ledger)
        out.unmatched = [{"kind": "normal", "key": "Gone :: x"}]
        return out
    monkeypatch.setattr(L, "save", with_unmatched)
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and t.unmatched == [{"kind": "normal", "key": "Gone :: x"}] and R.UNMATCHED_LINE in t.reply


async def test_an_explicit_removal_of_a_confirmed_concept_is_applied_and_named(fake):
    led, _ = L.set_choice([], "concept", "comparison",
                          L.concept_choice("used", "No previous imaging available.", "Compared with the {study} of {date}."))
    fake["tags"] = tags(concept=0.9)
    fake["calls"]["concept"] = CH.ConceptOut(changes=[CH.ConceptChange(concept="comparison", state="not_used")])
    t = await R.route_turn(ROUTER_SHEET, led, "never mention comparison")
    assert t.applied and "This changes something you confirmed" in t.reply and t.records
    assert L.concept_state(L.entry(t.ledger, "concept", "comparison")["choice"])[0] == "not_used"


async def test_a_failed_targeted_call_leaves_the_other_parts_applied(fake):
    fake["tags"] = tags(value=0.9, normal=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    fake["calls"]["normal"] = TimeoutError()
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and reword the alpha normal")
    assert t.applied and "Width is no longer required." in t.reply
    assert "I couldn't change the normal findings just now" in t.reply and t.evidence["failed"] == ["normal"]
    assert "TimeoutError" not in t.reply


async def test_invented_wording_cards_that_part_and_applies_the_rest(fake):
    fake["tags"] = tags(value=0.9, normal=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    fake["calls"]["normal"] = CH.NormalOut(changes=[CH.NormalChange(paragraph="Upper", structure="alpha",
                                                                    to="reword", text="Alpha looks fine.")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and make the alpha normal friendlier")
    assert t.applied and "Alpha is normal." in t.sheet and t.cards[0]["ledger_kind"] == "normal"
    assert t.evidence["changes"][1]["invented"] is True


async def test_a_paragraph_rename_rekeys_the_ledger(fake):
    led, _ = L.set_choice([], "normal", L.normal_key("Upper", "alpha"), {"text": "Alpha is normal."})
    fake["tags"] = tags(layout=0.9)
    fake["calls"]["layout"] = CH.LayoutOut(changes=[CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top")])
    t = await R.route_turn(ROUTER_SHEET, led, "call the upper paragraph Top")
    assert "## Paragraph: Top (FINDINGS)" in t.sheet and L.entry(t.ledger, "normal", L.normal_key("Top", "alpha"))
    assert t.records[0]["inverse"] == [{"op": "rename_paragraph", "paragraph": "Top", "to": "Upper"}]


async def test_a_change_to_a_confirmed_item_says_so(fake):
    led, _ = L.set_choice(L.seed_values([], ROUTER_SHEET), "value", "Width", {"need": "every"})  # re-confirmed
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, led, "drop width")
    assert "This changes something you confirmed" in t.reply


async def test_a_refused_save_keeps_the_previous_sheet_and_ledger(fake, monkeypatch):
    async def refuse(sheet, previous, ledger):
        return L.Saved("refused", previous, ledger, "Couldn't apply: it would break the template.")
    monkeypatch.setattr(L, "save", refuse)
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert not t.applied and t.refused and t.sheet == ROUTER_SHEET and t.ledger == [] and t.reply.startswith("Couldn't")


async def test_a_clarification_after_a_rejection_may_use_the_original_wording(fake):
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Height", to="every")])
    t = await R.route_turn(ROUTER_SHEET, [], "no, in every report",
                           rejection={"original_instruction": "always give the height", "rejected_claim": "x"})
    assert t.applied and L.entry(t.ledger, "value", "Height")["choice"] == {"need": "every"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.chat_router'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/chat_router.py`)

```python
"""The chat-edit router (spec 2026-10-13-chat-edit-router-design). A chat instruction that changes a template's
rules is applied by code through the decision ledger, the way a card tap is; a change of style is applied by a
lightweight call that can only touch prose. No model rewrites the whole sheet.

route_turn: Jev tags -> one targeted call per tagged kind (parallel; a kind in the unsure band is decided by its
call and marked route "llm_unsure", decision D-R2) -> code validates each structured change -> applied (style first,
then layout and unit edits, then ledger writes; plan decision 8), carded or asked -> the save function (origin
"chat"), which applies the ledger last -> the reply, one line per applied change. A failed tag call raises Fallback
and the endpoint runs today's whole-sheet refine (the fallback stays until the lab and live data say otherwise)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import chat_router_calls as C
from . import chat_router_changes as CH
from . import chat_router_edits as E
from . import chat_router_jev as J
from . import chat_router_layout as lay
from . import chat_router_ledger as L
from . import chat_router_sheet as sh
from . import chat_router_views as V

logger = logging.getLogger(__name__)

ROUTER_VERSION = "router-1"
UNSURE_ROUTE = "llm_unsure"
WORK_KINDS = ("value", "concept", "fixed", "normal", "layout", "style")
KIND_LABEL = CH.KIND_LABEL
CARDS_LINE = "I wasn't sure about part of that: choose below."
UNMATCHED_LINE = ("Some decisions no longer match a line in the template; they will be asked again at the next "
                  "review.")
STYLE_TOUCHED_RULES = ("The style change also touched the template's rules, so I left it out. Could you say it as "
                       "a change of wording only?")


class Fallback(Exception):
    """The tag call failed: the endpoint runs today's whole-sheet refine for this turn."""


@dataclass
class Turn:
    sheet: str
    ledger: List[dict]
    applied: bool                 # the saved sheet or the ledger differs from the turn's input (decision 14)
    reply: str
    claim: str = ""
    records: List[dict] = field(default_factory=list)   # what undo_turn reverses
    cards: List[dict] = field(default_factory=list)
    notice: str = ""
    refused: bool = False
    unmatched: List[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _ev(v: CH.Verdict) -> dict:
    return {"kind": v.kind, "action": v.action, "key": v.key, "op": (v.op or {}).get("op"), "route": v.route,
            "invented": v.invented, "reason": (v.reason or "")[:200], "detail": (v.detail or "")[:300]}


def _ask_reply(scan: str, misfit: bool) -> str:
    s = f"{scan} " if scan else ""
    if misfit:
        return f"That doesn't look like part of a {s}report. What should these reports do differently?"
    return f"I'm not sure what to change in these {s}reports. What should they do differently?"


def _ledger_for_edit(ledger: List[dict], before: str, op: dict, rec: dict,
                     undoing: bool = False) -> Tuple[List[dict], dict, Optional[dict]]:
    """Ledger keys follow a code edit: a paragraph rename rekeys its normals; a removal drops them (kept on the record
    for undo); a FIXED rewording moves its decided entry (td.rekey_decision), returned as a change so undo reverses it
    through the ledger (so `undoing` skips it). (ledger, record, change or None)."""
    name = op.get("op")
    change = None
    if name == "rename_paragraph":
        ledger = L.rekey_paragraph(ledger, op["paragraph"], op["to"])
    elif name in ("remove_paragraph", "remove_section"):
        if name == "remove_paragraph":
            paras = [op["paragraph"]]
        else:
            sec = lay.section_name(before, op["section"])
            paras = [n for n, s in sh.paragraphs(before) if sh.norm(s) == sh.norm(sec)]
        dropped = [e for p in paras for e in L.paragraph_entries(ledger, p)]
        ledger = [e for e in ledger if not any(e is d for d in dropped)]
        rec["dropped"] = list(rec.get("dropped") or []) + dropped
    elif name == "fixed_reword" and not undoing:
        ledger, change = L.rekey_fixed(ledger, op["line"], op["text"])
    return ledger, rec, change


def _apply(sheet: str, ledger: List[dict], verdicts: List[CH.Verdict]):
    """Layout edits, then unit edits, then ledger writes. (sheet, ledger, records, claims, notes, problems, detail)."""
    records: List[dict] = []
    claims: List[str] = []
    notes: List[str] = []
    problems: List[str] = []
    detail: List[str] = []
    seeded = False

    def rank(v: CH.Verdict) -> int:
        return 0 if (v.action == "edit" and v.kind == "layout") else 1 if v.action == "edit" else 2

    for v in sorted(verdicts, key=rank):
        route = v.route or None
        try:
            if v.action == "edit":
                before = sheet
                sheet, inverse = E.apply_op(sheet, v.op)
                rec = {"type": "edit", "kind": v.kind, "op": v.op, "inverse": inverse, "claim": v.claim,
                       "route": v.route}
                ledger, rec, moved = _ledger_for_edit(ledger, before, v.op, rec)
                records.append(rec)
                if moved:
                    records.append({"type": "ledger", "change": moved, "claim": "", "route": v.route})
                    notes.append(L.note(moved))
                if v.choice is not None:            # a new unit line is also a decision
                    ledger, change = L.set_choice(ledger, v.kind, v.key, v.choice, route=route)
                    if change:
                        records.append({"type": "ledger", "change": change, "claim": "", "route": v.route})
                claims.append(v.claim)
                continue
            if v.kind == "value" and not seeded:
                ledger, seeded = L.seed_values(ledger, sheet), True
            ledger, change = L.set_choice(ledger, v.kind, v.key, v.choice, route=route)
            if change is None:
                problems.append(f"Already the case: {v.claim}")
                continue
            records.append({"type": "ledger", "change": change, "claim": v.claim, "route": v.route})
            claims.append(v.claim)
            notes.append(L.note(change))
        except (E.EditError, L.Rejected) as e:   # the reason is internal: evidence only (decision 15)
            problems.append(f"I couldn't make this change: {v.claim.rstrip('.')}.")
            detail.append(f"{v.kind}: {str(e)[:200]}")
    return sheet, ledger, records, claims, [n for n in notes if n], problems, detail


async def _style(sheet: str, out: CH.StyleOut, ctx: CH.Ctx):
    """(sheet, style record or None, reply lines, extra verdicts, evidence) for a style output."""
    blocks = {b.id: b for b in sh.prose_blocks(sheet)}
    edits = {b.id: b.text.strip("\n") for b in out.blocks
             if b.id in blocks and b.text.strip("\n") != blocks[b.id].text}
    if not edits:
        return sheet, None, [], [], {}
    styled = sh.splice(sheet, edits)
    if not sh.units_unchanged(sheet, styled):
        return sheet, None, [STYLE_TOUCHED_RULES], [], {"style": "unit_line_changed"}
    rec = {"type": "style", "blocks": [{"before": blocks[b].text, "after": edits[b]} for b in edits],
           "claim": out.summary.strip() or "The wording guidance is updated."}
    return styled, rec, [], [], {"style": "applied"}


async def route_turn(sheet: str, ledger: List[dict], instruction: str, *, context: str = "",
                     rejection: Optional[dict] = None) -> Turn:
    t0 = time.monotonic()
    scan = sh.scan_type(sheet)
    try:
        tags = await J.tag(instruction, scan, context)
    except Exception as e:
        logger.warning("[chat-router] tag call failed: %s: %s", type(e).__name__, str(e)[:200])
        raise Fallback(type(e).__name__) from e
    ledger = L.clean(ledger)
    yes = [k for k in WORK_KINDS if tags[k] >= J.TAG_MIN]
    unsure = [k for k in WORK_KINDS if J.TAG_UNSURE <= tags[k] < J.TAG_MIN]
    ev = {"version": ROUTER_VERSION, "route": "router", "tags": {k: round(v, 3) for k, v in tags.items()},
          "yes": yes, "unsure": unsure}
    misfit = tags["misfit"] >= J.TAG_MIN
    if misfit or not (yes or unsure):
        ev.update(route="ask", applied=0, ms=_ms(t0))
        return Turn(sheet, ledger, False, _ask_reply(scan, misfit), evidence=ev)

    wording = instruction + ("\n" + (rejection.get("original_instruction") or "") if rejection else "")
    ctx = CH.Ctx(sheet, ledger, wording)
    kinds = yes + unsure
    results = await asyncio.gather(*(C.call_kind(k, instruction, V.view(k, sheet, ledger), context, rejection)
                                     for k in kinds), return_exceptions=True)
    verdicts: List[CH.Verdict] = []
    asks: List[str] = []
    failed: List[str] = []
    style_out, style_route = None, ""
    for k, res in zip(kinds, results):
        if isinstance(res, BaseException):
            logger.warning("[chat-router] %s call failed: %s", k, type(res).__name__)
            failed.append(k)
            continue
        if (res.question or "").strip():
            asks.append(res.question.strip())
        route = UNSURE_ROUTE if k in unsure else ""
        if k == "style":
            style_out, style_route = res, route
            continue
        for c in res.changes:
            v = CH.validate(k, c, ctx)
            v.route = route
            verdicts.append(v)

    styled, style_rec, style_lines, style_ev = sheet, None, [], {}
    if style_out is not None and style_out.blocks:
        styled, style_rec, style_lines, extra, style_ev = await _style(sheet, style_out, ctx)
        if style_rec:
            style_rec["route"] = style_route
        verdicts += extra

    new_sheet, new_ledger, records, claims, notes, problems, detail = _apply(
        styled, ledger, [v for v in verdicts if v.action in ("ledger", "edit")])
    if style_rec:
        records.insert(0, style_rec)
        claims.insert(0, style_rec["claim"])
    cards = [v.card for v in verdicts if v.action == "card" and v.card]
    asks += [v.reason for v in verdicts if v.action in ("ask", "reject") and v.reason]
    fails = [f"I couldn't change {KIND_LABEL[k]} just now; please try that part again." for k in failed]
    ev.update(changes=[_ev(v) for v in verdicts], cards=len(cards), failed=failed, problems=detail, **style_ev)

    def tail(cards_: List[dict]) -> List[str]:
        return ([CARDS_LINE] if cards_ else []) + asks + style_lines + problems + fails

    if not records:
        ev.update(applied=0, ms=_ms(t0))
        return Turn(sheet, ledger, False, "\n".join(tail(cards)) or "No change was needed.", cards=cards, evidence=ev)

    saved = await L.save(new_sheet, sheet, new_ledger)
    if saved.status == "refused":
        ev.update(applied=0, refused=True, ms=_ms(t0))
        return Turn(sheet, ledger, False, saved.message, cards=cards, refused=True, evidence=ev)
    cards += saved.cards
    if saved.sheet == sheet and saved.ledger == ledger:      # nothing actually changed (decision 14)
        ev.update(applied=0, ms=_ms(t0))
        return Turn(sheet, ledger, False, "\n".join(tail(cards)) or "No change was needed.", cards=cards,
                    evidence=ev)
    notes += [n for n in (L.note(c) for c in saved.ledger_changes) if n]
    lines = claims + notes + tail(cards) + ([UNMATCHED_LINE] if saved.unmatched else []) + (
        [saved.message] if saved.message else [])
    ev.update(applied=len(records), unmatched=len(saved.unmatched), ms=_ms(t0))
    logger.info("[chat-router] yes=%s unsure=%s applied=%d cards=%d failed=%s ms=%d", yes, unsure, len(records),
                len(cards), failed, ev["ms"])
    return Turn(saved.sheet, saved.ledger, True, "\n".join(lines), claim=" ".join(claims), records=records,
                cards=cards, notice=saved.message, unmatched=saved.unmatched, evidence=ev)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router.py -q`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router.py backend/tests/test_chat_router.py
git commit -m "feat(chat-router): route a turn: tags, targeted calls, validation, ledger, save, reply

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 10: Style edits: the guard, the rule-in-disguise check and the re-route

**Files:**
- Modify: `backend/src/rapid_reports_ai/chat_router.py` (replace `_style`; add `_reroute`, `REQUIRES_FAILED`)
- Test: `backend/tests/test_chat_router.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_chat_router.py`)

```python
NEW_IC = "Lead with the main finding in one sentence."


async def test_a_style_edit_touches_prose_only(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)],
                                         summary="The impression will be one sentence.")
    t = await R.route_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert t.applied and NEW_IC in t.sheet and "Keep it brief." not in t.sheet
    assert t.records[0] == {"type": "style", "claim": "The impression will be one sentence.", "route": "",
                            "blocks": [{"before": "Lead with the most important finding.\nKeep it brief.",
                                        "after": NEW_IC}]}
    assert t.reply == "The impression will be one sentence." and t.evidence["style"] == "applied"


async def test_a_style_edit_that_changes_a_unit_line_is_rejected(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b1", text='NORMAL [alpha] "Alpha is fine."')])
    t = await R.route_turn(ROUTER_SHEET, [], "tone it down")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.reply == R.STYLE_TOUCHED_RULES


async def test_a_rule_in_disguise_is_left_out_and_rerouted_to_a_card(fake):
    hidden = "Always state the alpha size."
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=f"{NEW_IC}\n{hidden}")],
                                         summary="The impression will be one sentence.")
    fake["requires"] = {hidden: 0.9, NEW_IC: 0.1}
    fake["calls"]["normal"] = CH.NormalOut(changes=[CH.NormalChange(paragraph="Upper", structure="alpha", to="reword",
                                                                    text="Alpha is normal in size.")])
    t = await R.route_turn(ROUTER_SHEET, [], "shorter impression, and always mention the alpha size")
    assert t.applied and NEW_IC in t.sheet and hidden not in t.sheet
    assert t.cards and t.cards[0]["ledger_kind"] == "normal"
    assert ("normal", f'Every report should state: "{hidden}"') in fake["seen"]
    assert t.evidence["disguise"] == [{"line": NEW_IC, "score": 0.1}, {"line": hidden, "score": 0.9}]


async def test_a_disguised_line_with_no_rule_kind_asks(fake):
    hidden = "Always state the alpha size."
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b1", text=hidden)], summary="x")
    fake["requires"] = {hidden: 0.9}
    t = await R.route_turn(ROUTER_SHEET, [], "always mention the alpha size")
    assert not t.applied and "Which part of the report should state it?" in t.reply


async def test_a_failed_requires_check_leaves_the_style_out(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)], summary="x")
    fake["requires"] = TimeoutError()
    t = await R.route_turn(ROUTER_SHEET, [], "shorter")
    assert not t.applied and t.reply == R.REQUIRES_FAILED


async def test_an_unsure_style_tag_is_decided_by_the_call(fake):
    fake["tags"] = tags(style=0.4)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)], summary="Shorter impression.")
    t = await R.route_turn(ROUTER_SHEET, [], "maybe shorter")
    assert t.applied and NEW_IC in t.sheet and t.records[0]["route"] == "llm_unsure"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router.py -q`
Expected: FAIL. `test_a_rule_in_disguise…` applies the hidden line, `test_a_failed_requires…` applies the edit, and `R.REQUIRES_FAILED` is missing.

- [ ] **Step 3: Implement.** In `chat_router.py`, add after `STYLE_TOUCHED_RULES`:

```python
REQUIRES_FAILED = "I couldn't check that wording change just now, so I left it out. Please try again."
```

and replace the whole `_style` function with:

```python
async def _reroute(lines: List[str], ctx: CH.Ctx) -> List[CH.Verdict]:
    """A prose line that requires the report to state something goes back through the rule route (normal, fixed);
    its wording is the model's, so it is always a card. No rule kind fits: the reply asks (spec Flow 3)."""
    out: List[CH.Verdict] = []
    for line in lines:
        instr = f'Every report should state: "{line}"'
        res = await asyncio.gather(*(C.call_kind(k, instr, V.view(k, ctx.sheet, ctx.ledger)) for k in ("normal", "fixed")),
                                   return_exceptions=True)
        found = [CH.to_card(CH.validate(k, c, ctx)) for k, r in zip(("normal", "fixed"), res)
                 if not isinstance(r, BaseException) for c in r.changes]
        found = [v for v in found if v.action == "card"]
        out.append(found[0] if found else CH.Verdict(
            "style", "ask", reason=f'I left out "{line}": it reads as something every report must state. Which part '
                                   "of the report should state it?"))
    return out


async def _style(sheet: str, out: CH.StyleOut, ctx: CH.Ctx):
    """(sheet, style record or None, reply lines, extra verdicts, evidence) for a style output: unit lines must be
    untouched; each new prose line is asked whether it requires the report to state something, and a yes is left out
    of the edit and re-routed."""
    blocks = {b.id: b for b in sh.prose_blocks(sheet)}
    edits = {b.id: b.text.strip("\n") for b in out.blocks
             if b.id in blocks and b.text.strip("\n") != blocks[b.id].text}
    if not edits:
        return sheet, None, [], [], {}
    if not sh.units_unchanged(sheet, sh.splice(sheet, edits)):
        return sheet, None, [STYLE_TOUCHED_RULES], [], {"style": "unit_line_changed"}
    new = [l for b, t in edits.items() for l in sh.new_lines(blocks[b].text, t)]
    try:
        scores = await J.requires(new)
    except Exception as e:
        logger.warning("[chat-router] requires check failed: %s", type(e).__name__)
        return sheet, None, [REQUIRES_FAILED], [], {"style": "requires_failed"}
    flagged = [l for l, s in zip(new, scores) if s >= J.REQUIRES_MIN]
    ev = {"style": "applied", "disguise": [{"line": l[:200], "score": round(s, 3)} for l, s in zip(new, scores)]}
    if flagged:
        fl = {sh.norm(x) for x in flagged}
        edits = {b: "\n".join(x for x in t.splitlines() if sh.norm(x) not in fl) for b, t in edits.items()}
        # a block left empty keeps its old prose (the radiologist did not ask to delete it)
        edits = {b: t for b, t in edits.items() if t.strip() and t.strip("\n") != blocks[b].text}
    rerouted = await _reroute(flagged, ctx)
    if not edits:
        return sheet, None, [], rerouted, {**ev, "style": "all_rerouted"}
    rec = {"type": "style", "blocks": [{"before": blocks[b].text, "after": edits[b]} for b in edits],
           "claim": out.summary.strip() or "The wording guidance is updated."}
    return sh.splice(sheet, edits), rec, [], rerouted, ev
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router.py -q`
Expected: PASS (21 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/chat_router.py backend/tests/test_chat_router.py
git commit -m "feat(chat-router): style edits guarded; rules in disguise re-routed to cards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 11: Undo a turn, answer a card, the response shape

**Files:**
- Modify: `backend/src/rapid_reports_ai/chat_router.py` (append)
- Test: `backend/tests/test_chat_router.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_chat_router.py`)

```python
async def _turn(fake, kind, out, instruction, ledger=None):
    fake["tags"] = tags(**{kind: 0.9})
    fake["calls"][kind] = out
    return await R.route_turn(ROUTER_SHEET, ledger or [], instruction)


async def test_undo_reverses_a_ledger_turn(fake):
    t = await _turn(fake, "value", CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")]), "drop width")
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert u.applied and 'LIST_MISSING ["Width" | "Depth"]' in u.sheet
    assert L.entry(u.ledger, "value", "Width")["choice"] == {"need": "every"}
    assert u.reply == "Undone: Width is no longer required." and u.evidence["route"] == "undo"


async def test_undo_reverses_a_layout_edit_and_its_rekey(fake):
    led, _ = L.set_choice([], "normal", L.normal_key("Upper", "alpha"), {"text": "Alpha is normal."})
    t = await _turn(fake, "layout", CH.LayoutOut(changes=[CH.LayoutChange(op="rename_paragraph", target="Upper",
                                                                           name="Top")]), "call it Top", led)
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert "## Paragraph: Upper (FINDINGS)" in u.sheet and L.entry(u.ledger, "normal", L.normal_key("Upper", "alpha"))


async def test_undo_reverses_a_fixed_reword_and_its_decided_entry(fake):
    led, _ = L.set_choice([], "fixed", "Axial images were acquired.", {"keep": "always"})
    t = await _turn(fake, "fixed", CH.FixedOut(changes=[CH.FixedChange(
        to="reword", line="Axial images were acquired.", text="Axial and coronal images were acquired.")]),
        "say Axial and coronal images were acquired.", led)
    assert L.entry(t.ledger, "fixed", "Axial and coronal images were acquired.") is not None
    assert [r["type"] for r in t.records] == ["edit", "ledger"]
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert 'FIXED "Axial images were acquired."' in u.sheet
    assert L.entry(u.ledger, "fixed", "Axial images were acquired.")["choice"] == {"keep": "always"}
    assert L.entry(u.ledger, "fixed", "Axial and coronal images were acquired.") is None


async def test_undo_puts_back_validated_dropped_entries_only(fake):
    led, _ = L.set_choice([], "normal", L.normal_key("Lower", "gamma"), {"text": "Gamma is fine."})
    t = await _turn(fake, "layout", CH.LayoutOut(changes=[CH.LayoutChange(op="remove_paragraph", target="Lower")]),
                    "remove the lower paragraph", led)
    assert L.entry(t.ledger, "normal", L.normal_key("Lower", "gamma")) is None
    tampered = [{**t.records[0], "dropped": [*t.records[0]["dropped"],
                                             {"kind": "value", "key": 'a "b"', "choice": {"need": "every"}}]}]
    u = await R.undo_turn(t.sheet, t.ledger, tampered)
    assert "## Paragraph: Lower (FINDINGS)" in u.sheet
    assert L.entry(u.ledger, "normal", L.normal_key("Lower", "gamma"))["choice"] == {"text": "Gamma is fine."}
    assert not any(e["kind"] == "value" for e in u.ledger)


async def test_undo_restores_the_previous_prose(fake):
    fake["requires"] = {}
    t = await _turn(fake, "style", CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)], summary="Shorter."),
                    "shorter")
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert "Keep it brief." in u.sheet and NEW_IC not in u.sheet


async def test_undo_leaves_what_a_later_turn_changed(fake):
    t = await _turn(fake, "value", CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")]), "drop width")
    led, _ = L.set_choice(t.ledger, "value", "Width", {"need": "relevant"})
    u = await R.undo_turn(t.sheet, led, t.records)
    assert not u.applied and u.reply.startswith("Nothing to undo") and u.evidence["skipped"] == 1


async def test_answer_card_writes_the_ledger_as_chat():
    t = await R.answer_card(ROUTER_SHEET, [], {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}})
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and t.reply == "Width is no longer required."
    assert L.entry(t.ledger, "value", "Width")["source"] == "chat" and t.evidence["route"] == "card"


async def test_answer_card_applies_a_proposal():
    apply = {"kind": "fixed", "key": "Axial images were obtained.", "choice": None,
             "op": {"op": "fixed_reword", "line": "Axial images were acquired.", "text": "Axial images were obtained."},
             "claim": '"Axial images were acquired." now reads "Axial images were obtained."'}
    t = await R.answer_card(ROUTER_SHEET, [], {"proposal": apply})
    assert t.applied and 'FIXED "Axial images were obtained."' in t.sheet and t.records[0]["type"] == "edit"


async def test_answer_card_refuses_what_code_cannot_apply_without_internal_text():
    t = await R.answer_card(ROUTER_SHEET, [], {"kind": "value", "key": 'a "bad" name', "choice": {"need": "every"}})
    assert not t.applied and t.sheet == ROUTER_SHEET and t.reply == R.CARD_REJECTED
    assert "short plain name" in t.evidence["detail"]


def test_response_and_the_kill_switch_defaults_off(monkeypatch):
    t = R.Turn("S", [{"kind": "value"}], True, "Done.", claim="c", records=[{"type": "ledger"}], cards=[{"id": "x"}])
    assert R.response(t) == {"success": True, "skill_sheet": "S", "response": "Done.", "behavioral_claim": "c",
                             "applied": True, "route": "router", "changes": [{"type": "ledger"}],
                             "cards": [{"id": "x"}], "decisions": [{"kind": "value"}], "unmatched": []}
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_CHAT_ROUTER", raising=False)
    assert not R.enabled()                                  # D-R3: off unless switched on
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    assert R.enabled()
    monkeypatch.setenv("RR_CHAT_ROUTER", "0")
    assert not R.enabled()
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert not R.enabled()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router.py -q`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.chat_router' has no attribute 'undo_turn'` (and `answer_card`, `response`, `enabled`)

- [ ] **Step 3: Implement** (append to `chat_router.py`)

```python
CARD_REJECTED = "I couldn't apply that choice. Could you tell me in the chat what you want instead?"


def enabled() -> bool:
    """The kill switch (plan decision 1, D-R3): off unless RR_CHAT_ROUTER=1 and a Jev key is set; off sends every
    turn down today's path."""
    return os.environ.get("RR_CHAT_ROUTER", "0") == "1" and bool(os.environ.get("OPENROUTER_API_KEY"))


def response(turn: Turn) -> dict:
    """The /skill-sheet/refine (and /undo, /card) response for a router turn."""
    out = {"success": True, "skill_sheet": turn.sheet, "response": turn.reply,
           "behavioral_claim": turn.claim if turn.applied else "", "applied": turn.applied, "route": "router",
           "changes": turn.records, "cards": turn.cards, "decisions": turn.ledger, "unmatched": turn.unmatched}
    if turn.notice:
        out["notice"] = turn.notice
    return out


async def undo_turn(sheet: str, ledger: List[dict], records: List[dict]) -> Turn:
    """Reverse a turn's records, newest first (plan decision 10): a ledger write only while its entry still holds
    the turn's value; a code edit by its inverse ops; a style block only while its edited text is still there.
    Anything a later turn changed is left alone and counted as skipped."""
    t0 = time.monotonic()
    original = L.clean(ledger)
    led, cur = list(original), sheet
    undone: List[str] = []
    skipped = 0
    for rec in reversed(records or []):
        try:
            kind = rec.get("type")
            if kind == "ledger":
                before = led
                led = L.undo(led, rec["change"])
                if led == before:
                    skipped += 1
                    continue
            elif kind == "edit":
                for inv in reversed(rec.get("inverse") or []):
                    prev = cur
                    cur, _ = E.apply_op(cur, inv)
                    led, _, _ = _ledger_for_edit(led, prev, inv, {}, undoing=True)
                for e in rec.get("dropped") or []:   # client-sent: validated before it goes back (L.restore)
                    try:
                        led = L.restore(led, e)
                    except L.Rejected as err:
                        logger.info("[chat-router] undo refused a dropped entry: %s", err)
            elif kind == "style":
                hit = False
                for b in rec.get("blocks") or []:
                    if b.get("after") and b["after"] in cur:
                        cur, hit = cur.replace(b["after"], b["before"], 1), True
                if not hit:
                    skipped += 1
                    continue
            else:
                continue
            if rec.get("claim"):
                undone.append(rec["claim"])
        except (E.EditError, L.Rejected, KeyError) as e:
            logger.info("[chat-router] undo skipped a %s record: %s", rec.get("type"), e)
            skipped += 1
    ev = {"version": ROUTER_VERSION, "route": "undo", "records": len(records or []), "skipped": skipped}
    if cur == sheet and led == original:
        ev["ms"] = _ms(t0)
        return Turn(sheet, original, False, "Nothing to undo: it has changed since.", evidence=ev)
    saved = await L.save(cur, sheet, led)
    ev["ms"] = _ms(t0)
    if saved.status == "refused":
        return Turn(sheet, original, False, saved.message, refused=True, evidence={**ev, "refused": True})
    reply = "\n".join(f"Undone: {c}" for c in undone) or "Undone."
    if skipped:
        reply += "\nPart of it had changed since, so I left that part as it is."
    return Turn(saved.sheet, saved.ledger, True, reply, notice=saved.message, unmatched=saved.unmatched, evidence=ev)


async def answer_card(sheet: str, ledger: List[dict], answer: dict) -> Turn:
    """Apply a tapped card (plan decision 11): {"kind", "key", "choice"} for a ledger card, or {"proposal": <the
    card's apply>} for a proposal card. Written as source "chat"; the wording check is skipped (the radiologist
    chose it); code still validates and the save function still vets."""
    t0 = time.monotonic()
    ledger = L.clean(ledger)
    p = (answer or {}).get("proposal")
    if p:
        v = CH.Verdict(p.get("kind") or "", "edit" if p.get("op") else "ledger", key=p.get("key") or "",
                       choice=p.get("choice"), op=p.get("op"), claim=p.get("claim") or "")
        if v.action == "ledger" and not v.choice:
            return Turn(sheet, ledger, False, "That card has nothing to apply.")
    else:
        try:
            key, choice = L.check((answer or {}).get("kind", ""), (answer or {}).get("key", ""),
                                  (answer or {}).get("choice") or {})
        except L.Rejected as e:   # internal text stays in the evidence (decision 15)
            return Turn(sheet, ledger, False, CARD_REJECTED,
                        evidence={"version": ROUTER_VERSION, "route": "card", "detail": str(e)[:300]})
        v = CH.Verdict(answer["kind"], "ledger", key=key, choice=choice, claim=CH.claim_for(answer["kind"], key, choice))
    new_sheet, new_ledger, records, claims, notes, problems, detail = _apply(sheet, ledger, [v])
    ev = {"version": ROUTER_VERSION, "route": "card", "kind": v.kind, "proposal": bool(p), "applied": len(records),
          "detail": "; ".join(detail)}
    if not records:
        ev["ms"] = _ms(t0)
        return Turn(sheet, ledger, False, "\n".join(problems) or "No change was needed.", evidence=ev)
    saved = await L.save(new_sheet, sheet, new_ledger)
    ev["ms"] = _ms(t0)
    if saved.status == "refused":
        return Turn(sheet, ledger, False, saved.message, refused=True, evidence={**ev, "refused": True})
    notes += [n for n in (L.note(c) for c in saved.ledger_changes) if n]
    if saved.sheet == sheet and saved.ledger == ledger:
        return Turn(sheet, ledger, False, "No change was needed.", evidence=ev)
    return Turn(saved.sheet, saved.ledger, True, "\n".join(claims + notes + ([UNMATCHED_LINE] if saved.unmatched else [])
                                                              + ([saved.message] if saved.message else [])),
                claim=" ".join(claims), records=records, cards=saved.cards, notice=saved.message,
                unmatched=saved.unmatched, evidence=ev)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router.py -q`
Expected: PASS (31 tests)

- [ ] **Step 5: Run Phases 1-2 and commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_ledger.py tests/test_chat_router_sheet.py tests/test_chat_router_edits.py tests/test_chat_router_layout.py tests/test_chat_router_changes.py tests/test_chat_router_views.py tests/test_chat_router_jev.py tests/test_chat_router_calls.py tests/test_chat_router.py -q`
Expected: PASS (all)

```bash
git add backend/src/rapid_reports_ai/chat_router.py backend/tests/test_chat_router.py
git commit -m "feat(chat-router): undo a turn per change; answer a card; response shape and kill switch

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 3: labs, before the wiring

The tagging lab (Task 14) runs **before** any wiring that depends on it (Phase 4), as the spec requires. The router reads `TAG_MIN`, `TAG_UNSURE` and `REQUIRES_MIN` from `chat_router_jev`, and Hassan sets them from the Task 14 report. The targeted-call and end-to-end lab (Task 15) runs on the same data and reports before Phase 4 starts. All lab data stays in `~/Code/rr-template-conversion-private/synthetic/chat_router/`. The generator is Opus (a Claude subagent). The models under test are Jev and Qwen, so the generator is never the model under test. Eval economy applies: at most 2 runs, outputs are reused (a runner skips any item whose output file already exists), and output filenames carry the item id.

### Task 12: Lab script: runners and scorers

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/chat_router_lab.py`
- Test: `backend/tests/test_chat_router_lab.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_router_lab.py`)

```python
"""The chat-edit router lab's pure scorers (the runners call models and are run by the controller)."""
import json

import pytest

from rapid_reports_ai.scripts import chat_router_lab as lab
from tests.template_sheet_fixtures import ROUTER_SHEET

KINDS = ("value", "concept", "fixed", "normal", "layout", "style", "misfit")


def _item(i, **labels):
    return {"id": f"i{i}", "set": "synthetic", "category": "single", "sheet": "s", "instruction": "x",
            "labels": {k: labels.get(k, 0) for k in KINDS}, "truth": []}


def test_prf_counts():
    out = lab.prf([(True, True), (True, False), (False, True), (False, False)])
    assert (out["p"], out["r"], out["tp"], out["fp"], out["fn"], out["n"]) == (0.5, 0.5, 1, 1, 1, 4)
    assert lab.prf([(False, False)])["p"] is None


def test_tag_table_and_band():
    items = [_item(1, value=1), _item(2), _item(3, value=1)]
    scores = {"i1": {k: 0.9 if k == "value" else 0.1 for k in KINDS},
              "i2": {k: 0.4 if k == "value" else 0.1 for k in KINDS},
              "i3": {k: 0.45 for k in KINDS}}
    t = lab.tag_table(items, scores, thresholds=(0.4, 0.5))
    assert t["value"][0.5]["tp"] == 1 and t["value"][0.5]["fn"] == 1
    assert t["value"][0.4]["fp"] == 1 and t["value"][0.4]["tp"] == 2
    assert lab.band(items, scores, 0.35, 0.5)["value"] == {"pos": 1, "neg": 1}


def test_match_ledger_layout_card_and_style():
    rec = {"kind": "value", "action": "ledger", "key": "width", "choice": {"need": "not_needed"}, "op": None}
    assert lab.match(rec, {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}})
    assert not lab.match(rec, {"kind": "value", "key": "Width", "choice": {"need": "every"}})
    lay = {"kind": "layout", "action": "edit", "key": "", "choice": None,
           "op": {"op": "rename_paragraph", "paragraph": "Upper", "to": "Top"}}
    assert lab.match(lay, {"kind": "layout", "op": {"op": "rename_paragraph", "paragraph": "upper", "to": "Top."}})
    card = {"kind": "normal", "action": "card", "key": "k", "choice": {"text": "x"}, "op": None}
    assert lab.match(card, {"kind": "normal", "expect": "card"}) and not lab.match(card, {"kind": "normal",
                                                                                          "key": "k", "choice": {"text": "x"}})
    assert lab.match({"kind": "style", "action": "style"}, {"kind": "style"})
    cond = "the dictation states no contrast agent was given"
    rec_c = {"kind": "concept", "action": "ledger", "key": "contrast", "op": None,
             "choice": {"use": True, "dictated": False, "default": "Contrast was given.",
                        "when_met": "No contrast was given.", "condition": cond}}
    assert lab.match(rec_c, {"kind": "concept", "key": "contrast", "choice": {
        "use": True, "default": "contrast was given", "when_met": "No contrast was given.", "condition": "not_given"}})
    assert not lab.match(rec_c, {"kind": "concept", "key": "contrast", "choice": {
        "use": True, "default": "Contrast was given.", "when_met": "No contrast was given.", "condition": "given"}})
    dictated = {"kind": "concept", "action": "ledger", "key": "comparison", "op": None,
                "choice": {"use": False, "dictated": True, "default": "", "when_met": "", "condition": ""}}
    assert lab.match(dictated, {"kind": "concept", "key": "comparison", "choice": {"use": False, "dictated": True}})


def test_score_changes_counts_correct_missing_extra_cards_and_invented():
    truth = [{"kind": "value", "key": "Width", "choice": {"need": "not_needed"}},
             {"kind": "fixed", "key": "A.", "choice": {"keep": "remove"}}]
    recs = [{"kind": "value", "action": "ledger", "key": "Width", "choice": {"need": "not_needed"}},
            {"kind": "normal", "action": "ledger", "key": "P :: x", "choice": {"text": ""}},
            {"kind": "fixed", "action": "card", "key": "A.", "choice": {"keep": "remove"}, "invented": True}]
    assert lab.score_changes(truth, recs) == {"truth": 2, "correct": 1, "missing": 1, "extra_applied": 1, "cards": 1,
                                              "rejected": 0, "asked": 0, "invented": 1}


def test_unrelated_changes_counts_lines_outside_the_touched_parts():
    edited = ROUTER_SHEET.replace('NORMAL [alpha] "Alpha is normal."', 'NORMAL [alpha] "Alpha is fine."')
    assert lab.unrelated_changes(ROUTER_SHEET, edited, ["Upper"]) == 0
    assert lab.unrelated_changes(ROUTER_SHEET, edited, ["Lower"]) == 2


def test_unsure_counts_how_many_band_decisions_were_wrong():
    truth = [{"kind": "value", "key": "Width", "choice": {"need": "not_needed"}}]
    recs = [{"kind": "value", "action": "ledger", "key": "Width", "choice": {"need": "not_needed"}, "route": "llm_unsure"},
            {"kind": "normal", "action": "ledger", "key": "P :: x", "choice": {"text": ""}, "route": "llm_unsure"},
            {"kind": "fixed", "action": "ledger", "key": "A.", "choice": {"keep": "remove"}, "route": ""}]
    assert lab.unsure_counts(recs, truth) == {"unsure": 2, "unsure_wrong": 1}


def test_load_items_requires_every_label(tmp_path):
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "a.json").write_text(json.dumps({**_item(1), "labels": {"value": 1}}))
    with pytest.raises(ValueError):
        lab.load_items(tmp_path)


def test_md_table():
    assert lab.md_table(["a", "b"], [[1, None]]) == "| a | b |\n|---|---|\n| 1 | – |"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_lab.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.scripts.chat_router_lab'`

- [ ] **Step 3: Write the script** (`backend/src/rapid_reports_ai/scripts/chat_router_lab.py`)

```python
"""Chat-edit router lab (spec "Testing", labs). Reported, not gated: Hassan reads the reports and decides.

Data, never in the repo: ~/Code/rr-template-conversion-private/synthetic/chat_router/
  sheets/<slug>.md              the sheet an item edits
  items/<id>.json               {"id","seed","set":"synthetic"|"real","category","sheet","instruction","context",
                                 "labels":{kind: 0|1 for every chat_router_jev.KINDS},"truth":[...]}
  lines/<id>.json               {"id","set","line","requires": 0|1}   (the rule-in-disguise question)
  sequences/<id>.json           {"id","sheet","touches":[heading or paragraph names],"turns":[{"instruction","truth"}]}
  runs/<stage>/run<k>/<id>.json raw outputs (a runner skips ids it already has)
Truth entries: {"kind","key","choice"} for a ledger write (a new FIXED / NORMAL / NEGATIVE line too) |
  {"kind":"layout","op":{apply_op dict}} | {"kind":<k>,"expect":"card"} | {"kind":"style"}.

  python -m rapid_reports_ai.scripts.chat_router_lab tag|requires|calls|e2e --root R --run K
  python -m rapid_reports_ai.scripts.chat_router_lab score --root R --stage tag|requires|calls|e2e --runs 1 2"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import statistics
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from rapid_reports_ai import chat_router as R
from rapid_reports_ai import chat_router_calls as C
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_jev as J
from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import chat_router_sheet as sh
from rapid_reports_ai import chat_router_views as V

THRESHOLDS = (0.3, 0.35, 0.4, 0.5, 0.6, 0.7)
CONCURRENCY = 4


# ── pure scoring ────────────────────────────────────────────────────────────────────────────────────────────────
def prf(pairs: Iterable) -> dict:
    pairs = list(pairs)
    tp = sum(1 for t, p in pairs if t and p)
    fp = sum(1 for t, p in pairs if not t and p)
    fn = sum(1 for t, p in pairs if t and not p)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return {"p": prec, "r": rec, "f1": f1, "n": len(pairs), "tp": tp, "fp": fp, "fn": fn}


def tag_table(items: List[dict], scores: Dict[str, dict], thresholds: Sequence[float] = THRESHOLDS) -> dict:
    """kind -> threshold -> prf over the items with a score."""
    have = [it for it in items if isinstance(scores.get(it["id"]), dict) and "error" not in scores[it["id"]]]
    return {k: {thr: prf((bool(it["labels"][k]), scores[it["id"]][k] >= thr) for it in have) for thr in thresholds}
            for k in J.KINDS}


def band(items: List[dict], scores: Dict[str, dict], lo: float, hi: float) -> dict:
    """kind -> {"pos", "neg"}: items scored in [lo, hi), by their label (what the card band would catch)."""
    out = {k: {"pos": 0, "neg": 0} for k in J.KINDS}
    for it in items:
        s = scores.get(it["id"])
        if not isinstance(s, dict) or "error" in s:
            continue
        for k in J.KINDS:
            if lo <= s[k] < hi:
                out[k]["pos" if it["labels"][k] else "neg"] += 1
    return out


def _norm_obj(x):
    if isinstance(x, str):
        return sh.norm(x).rstrip(".")
    if isinstance(x, dict):
        return {k: _norm_obj(v) for k, v in x.items() if v not in ("", [], None)}
    if isinstance(x, list):
        return [_norm_obj(v) for v in x]
    return x


def _concept_view(choice: Optional[dict]):
    state, d, w, cond = L.concept_state(choice or {})
    return state, _norm_obj(d), _norm_obj(w), cond


def _concept_match(rec: dict, truth: dict) -> bool:
    """A concept compares by state and wordings; a truth "condition" (a state name or the text) must match too."""
    if rec.get("action") not in ("ledger", "edit") or _norm_obj(rec.get("key")) != _norm_obj(truth.get("key")):
        return False
    tc = truth.get("choice") or {}
    rs, rd, rw, rc = _concept_view(rec.get("choice"))
    ts, tdf, tw, _ = _concept_view(tc)
    cond_ok = not tc.get("condition") or L.condition_for(truth["key"], tc["condition"]) == rc
    return (rs, rd, rw) == (ts, tdf, tw) and cond_ok


def match(rec: dict, truth: dict) -> bool:
    if rec.get("kind") != truth.get("kind"):
        return False
    if truth["kind"] == "concept" and truth.get("expect") != "card":
        return _concept_match(rec, truth)
    if truth.get("expect") == "card":
        return rec.get("action") == "card"
    if truth["kind"] == "style":
        return rec.get("action") == "style"
    if truth["kind"] == "layout":
        return rec.get("action") == "edit" and _norm_obj(rec.get("op")) == _norm_obj(truth.get("op"))
    return (rec.get("action") in ("ledger", "edit") and _norm_obj(rec.get("key")) == _norm_obj(truth.get("key"))
            and _norm_obj(rec.get("choice")) == _norm_obj(truth.get("choice")))


def score_changes(truth: List[dict], records: List[dict]) -> dict:
    used = set()
    correct = 0
    for t in truth:
        hit = next((i for i, r in enumerate(records) if i not in used and match(r, t)), None)
        if hit is not None:
            used.add(hit)
            correct += 1
    extra = [r for i, r in enumerate(records) if i not in used and r.get("action") in ("ledger", "edit")]
    return {"truth": len(truth), "correct": correct, "missing": len(truth) - correct, "extra_applied": len(extra),
            "cards": sum(r.get("action") == "card" for r in records),
            "rejected": sum(r.get("action") == "reject" for r in records),
            "asked": sum(r.get("action") == "ask" for r in records),
            "invented": sum(bool(r.get("invented")) for r in records)}


def _allowed(line: sh.Line, allowed: set) -> bool:
    return sh.norm(line.heading) in allowed or bool(line.paragraph and sh.norm(line.paragraph) in allowed)


def unrelated_changes(start: str, end: str, touches: List[str]) -> int:
    """Non-blank lines changed (either side) outside the headings / paragraphs a sequence may touch."""
    allowed = {sh.norm(t) for t in touches}
    a, b = start.splitlines(), end.splitlines()
    wa, wb = sh.walk(start), sh.walk(end)
    n = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        n += sum(1 for i in range(i1, i2) if a[i].strip() and not _allowed(wa[i], allowed))
        n += sum(1 for j in range(j1, j2) if b[j].strip() and not _allowed(wb[j], allowed))
    return n


def unsure_counts(records: List[dict], truth: List[dict]) -> dict:
    """Changes applied for a kind tagged in the unsure band (route llm_unsure, decision D-R2), and how many match no
    planted truth: the lab's stand-in for "later undone"."""
    unsure = [r for r in records if r.get("route") == "llm_unsure" and r.get("action") in ("ledger", "edit", "style")]
    return {"unsure": len(unsure), "unsure_wrong": sum(1 for r in unsure if not any(match(r, t) for t in truth))}


def verdict_record(v: CH.Verdict) -> dict:
    return {"kind": v.kind, "action": v.action, "key": v.key, "choice": v.choice, "op": v.op, "route": v.route,
            "invented": v.invented, "reason": v.reason, "detail": v.detail}


def turn_records(t: R.Turn) -> List[dict]:
    """What a routed turn did, in the scorer's record form."""
    out = []
    for r in t.records:
        if r["type"] == "ledger":
            new = r["change"].get("new")
            out.append({"kind": r["change"]["kind"], "action": "ledger", "key": r["change"]["key"],
                        "choice": new.get("choice") if isinstance(new, dict) and "choice" in new else new, "op": None,
                        "route": r.get("route", "")})
        elif r["type"] == "edit":
            out.append({"kind": r["kind"], "action": "edit", "key": "", "choice": None, "op": r["op"],
                        "route": r.get("route", "")})
        elif r["type"] == "style":
            out.append({"kind": "style", "action": "style", "route": r.get("route", "")})
    for c in t.cards:
        out.append({"kind": c.get("ledger_kind") or (c.get("apply") or {}).get("kind"), "action": "card",
                    "key": c.get("key", ""), "choice": None, "op": None})
    return out


def md_table(header: List[str], rows: List[list]) -> str:
    def cell(v):
        if v is None:
            return "–"
        return f"{v:.2f}" if isinstance(v, float) else str(v)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


# ── data ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _load(root: Path, sub: str) -> List[dict]:
    return [json.loads(p.read_text()) for p in sorted((Path(root) / sub).glob("*.json"))]


def load_items(root: Path) -> List[dict]:
    items = _load(root, "items")
    for it in items:
        missing = [k for k in J.KINDS if k not in (it.get("labels") or {})]
        if missing:
            raise ValueError(f"{it.get('id')}: labels missing {missing}")
    return items


def _sheet(root: Path, slug: str) -> str:
    return (Path(root) / "sheets" / f"{slug}.md").read_text()


def _out(root: Path, stage: str, run: int) -> Path:
    d = Path(root) / "runs" / stage / f"run{run}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _runs(root: Path, stage: str, run: int) -> Dict[str, dict]:
    d = Path(root) / "runs" / stage / f"run{run}"
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.exists() else {}


# ── runners (call Jev / Qwen; run by the controller) ────────────────────────────────────────────────────────────
async def _each(rows: List[dict], out: Path, fn) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(row):
        dest = out / f"{row['id']}.json"
        if dest.exists():
            return
        async with sem:
            t0 = time.monotonic()
            try:
                res = await fn(row)
            except Exception as e:
                res = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            res["ms"] = int((time.monotonic() - t0) * 1000)
        dest.write_text(json.dumps({"id": row["id"], **res}, indent=1))
    await asyncio.gather(*(one(r) for r in rows))


async def run_tag(root: Path, run: int) -> None:
    async def fn(it):
        sheet = _sheet(root, it["sheet"])
        return {"scores": await J.tag(it["instruction"], sh.scan_type(sheet), it.get("context", ""))}
    await _each(load_items(root), _out(root, "tag", run), fn)


async def run_requires(root: Path, run: int) -> None:
    async def fn(row):
        return {"score": (await J.requires([row["line"]]))[0]}
    await _each(_load(root, "lines"), _out(root, "requires", run), fn)


async def run_calls(root: Path, run: int) -> None:
    """The targeted calls for the planted kinds (not Jev's tags): call accuracy on its own."""
    async def fn(it):
        sheet = _sheet(root, it["sheet"])
        ctx = CH.Ctx(sheet, [], it["instruction"])
        records, questions, errors = [], [], []
        for k in [k for k in R.WORK_KINDS if it["labels"].get(k)]:
            try:
                res = await C.call_kind(k, it["instruction"], V.view(k, sheet, []), it.get("context", ""))
            except Exception as e:
                errors.append(f"{k}: {type(e).__name__}")
                continue
            if res.question:
                questions.append(res.question)
            if k == "style":
                edited = sh.splice(sheet, {b.id: b.text for b in res.blocks})
                records.append({"kind": "style", "action": "style" if res.blocks else "none",
                                "units_unchanged": sh.units_unchanged(sheet, edited), "blocks": len(res.blocks)})
            else:
                records += [verdict_record(CH.validate(k, c, ctx)) for c in res.changes]
        return {"records": records, "questions": questions, "errors": errors}
    await _each(load_items(root), _out(root, "calls", run), fn)


async def run_e2e(root: Path, run: int) -> None:
    """route_turn over each scripted sequence (real Jev, Qwen and the save function)."""
    async def fn(seq):
        start = sheet = _sheet(root, seq["sheet"])
        ledger: List[dict] = []
        turns = []
        for turn in seq["turns"]:
            try:
                t = await R.route_turn(sheet, ledger, turn["instruction"])
            except R.Fallback as e:
                turns.append({"instruction": turn["instruction"], "fallback": str(e)})
                continue
            sheet, ledger = t.sheet, t.ledger
            recs = turn_records(t)
            turns.append({"instruction": turn["instruction"], "records": recs, "reply": t.reply,
                          "applied": t.applied, "ms": t.evidence.get("ms"), "unsure_kinds": t.evidence.get("unsure", []),
                          "score": {**score_changes(turn.get("truth") or [], recs),
                                    **unsure_counts(recs, turn.get("truth") or [])}})
        return {"turns": turns, "final_sheet": sheet, "unrelated": unrelated_changes(start, sheet, seq["touches"])}
    await _each(_load(root, "sequences"), _out(root, "e2e", run), fn)


# ── reports (tables only; the controller writes the prose report) ───────────────────────────────────────────────
def _sum(dicts: List[dict]) -> dict:
    out: Dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def report_tag(root: Path, runs: List[int]) -> str:
    items = load_items(root)
    parts = []
    for run in runs:
        scores = {k: v.get("scores") or {"error": v.get("error")} for k, v in _runs(root, "tag", run).items()}
        for subset in ("synthetic", "real"):
            its = [it for it in items if it["set"] == subset]
            if not its:
                parts.append(f"### run {run}, {subset}: no items")
                continue
            t = tag_table(its, scores)
            rows = [[k, thr, t[k][thr]["p"], t[k][thr]["r"], t[k][thr]["f1"], t[k][thr]["n"]]
                    for k in J.KINDS for thr in THRESHOLDS]
            parts.append(f"### run {run}, {subset}: precision / recall per kind\n\n"
                         + md_table(["kind", "threshold", "P", "R", "F1", "n"], rows))
            b = band(its, scores, J.TAG_UNSURE, J.TAG_MIN)
            parts.append(f"### run {run}, {subset}: unsure band [{J.TAG_UNSURE}, {J.TAG_MIN}), decided by the call\n\n"
                         + md_table(["kind", "labelled yes", "labelled no"], [[k, b[k]["pos"], b[k]["neg"]] for k in J.KINDS]))
            cats = sorted({it["category"] for it in its})
            rows = []
            for cat in cats:
                ci = [it for it in its if it["category"] == cat]
                ct = tag_table(ci, scores, (J.TAG_MIN,))
                rows.append([cat, len(ci)] + [ct[k][J.TAG_MIN]["r"] for k in J.KINDS])
            parts.append(f"### run {run}, {subset}: recall at {J.TAG_MIN} by category\n\n"
                         + md_table(["category", "n", *J.KINDS], rows))
    if len(runs) >= 2:
        a, b2 = (_runs(root, "tag", r) for r in runs[:2])
        same = [(a[i]["scores"][k] >= J.TAG_MIN) == (b2[i]["scores"][k] >= J.TAG_MIN)
                for i in a if i in b2 and "scores" in a[i] and "scores" in b2[i] for k in J.KINDS]
        parts.append(f"### run-to-run agreement at {J.TAG_MIN}: {sum(same)}/{len(same)}")
    errors = sum(1 for run in runs for v in _runs(root, "tag", run).values() if "error" in v)
    ms = [v["ms"] for run in runs for v in _runs(root, "tag", run).values() if "ms" in v]
    parts.append(f"### errors: {errors}; median ms: {statistics.median(ms) if ms else None}")
    return "\n\n".join(parts)


def report_requires(root: Path, runs: List[int]) -> str:
    lines = {r["id"]: r for r in _load(root, "lines")}
    parts = []
    for run in runs:
        got = _runs(root, "requires", run)
        for subset in ("synthetic", "real"):
            ids = [i for i, r in lines.items() if r["set"] == subset and "score" in got.get(i, {})]
            rows = [[thr, *(lambda m: [m["p"], m["r"], m["f1"], m["n"]])(
                prf((bool(lines[i]["requires"]), got[i]["score"] >= thr) for i in ids))] for thr in THRESHOLDS]
            parts.append(f"### run {run}, {subset}\n\n" + md_table(["threshold", "P", "R", "F1", "n"], rows))
    return "\n\n".join(parts)


def report_calls(root: Path, runs: List[int]) -> str:
    items = {it["id"]: it for it in load_items(root)}
    parts = []
    for run in runs:
        got = _runs(root, "calls", run)
        for subset in ("synthetic", "real"):
            rows = []
            for k in R.WORK_KINDS:
                scores, errors, questions, unit_breaks = [], 0, 0, 0
                for i, out in got.items():
                    it = items.get(i)
                    if not it or it["set"] != subset or not it["labels"].get(k):
                        continue
                    recs = [r for r in out.get("records", []) if r.get("kind") == k]
                    truth = [t for t in it.get("truth", []) if t.get("kind") == k]
                    scores.append(score_changes(truth, recs))
                    errors += sum(e.startswith(k) for e in out.get("errors", []))
                    questions += len(out.get("questions", []))
                    unit_breaks += sum(1 for r in recs if r.get("units_unchanged") is False)
                s = _sum(scores)
                rows.append([k, len(scores), s.get("truth", 0), s.get("correct", 0), s.get("missing", 0),
                             s.get("extra_applied", 0), s.get("cards", 0), s.get("rejected", 0), s.get("asked", 0),
                             s.get("invented", 0), errors, questions, unit_breaks])
            parts.append(f"### run {run}, {subset}\n\n" + md_table(
                ["kind", "items", "truth", "correct", "missing", "extra applied", "cards", "rejected", "asked",
                 "invented", "errors", "questions", "style broke a unit"], rows))
    return "\n\n".join(parts)


def report_e2e(root: Path, runs: List[int]) -> str:
    parts = []
    for run in runs:
        got = _runs(root, "e2e", run)
        rows, ms = [], []
        for i, out in sorted(got.items()):
            turns = out.get("turns", [])
            s = _sum([t["score"] for t in turns if "score" in t])
            ms += [t["ms"] for t in turns if t.get("ms") is not None]
            rows.append([i, len(turns), sum("fallback" in t for t in turns), s.get("truth", 0), s.get("correct", 0),
                         s.get("extra_applied", 0), s.get("cards", 0), sum(bool(t.get("unsure_kinds")) for t in turns),
                         s.get("unsure", 0), s.get("unsure_wrong", 0), out.get("unrelated")])
        parts.append(f"### run {run} (median ms per turn: {statistics.median(ms) if ms else None})\n\n" + md_table(
            ["sequence", "turns", "fallbacks", "truth", "correct", "extra applied", "cards", "turns with an unsure band",
             "unsure-band changes", "of them wrong", "unrelated lines"], rows))
    return "\n\n".join(parts)


REPORTS = {"tag": report_tag, "requires": report_requires, "calls": report_calls, "e2e": report_e2e}
RUNNERS = {"tag": run_tag, "requires": run_requires, "calls": run_calls, "e2e": run_e2e}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=[*RUNNERS, "score"])
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--stage", choices=list(REPORTS))
    ap.add_argument("--runs", type=int, nargs="+", default=[1])
    a = ap.parse_args()
    root = a.root.expanduser()
    if a.cmd == "score":
        out = root / f"REPORT_{a.stage}_tables.md"
        out.write_text(REPORTS[a.stage](root, a.runs) + "\n")
        print(out)
        return
    asyncio.run(RUNNERS[a.cmd](root, a.run))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_lab.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/chat_router_lab.py backend/tests/test_chat_router_lab.py
git commit -m "feat(chat-router): lab runners and scorers (tags, requires, targeted calls, end to end)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 13 (controller-run): Lab data: production turns as the held-out set; synthetic sets seeded from them and the 31 templates

The controller (the session running this plan) runs this task, not an implementer subagent. Nothing from this task is committed. Production reads are covered by Hassan's standing permission (memory `feedback_prod_access`), and the data stays in the private folder.

- [ ] **Step 1: Folders and the curated sheets**

```bash
R=~/Code/rr-template-conversion-private/synthetic/chat_router
mkdir -p $R/{sheets,items,lines,sequences,real,runs,notes}
for f in ~/Code/rr-template-conversion-private/final/*.final.md; do cp "$f" "$R/sheets/$(basename "$f" .final.md).md"; done
ls $R/sheets | wc -l
```

Expected: `31`

- [ ] **Step 2: Pull the stored refine turns from production** (read-only SQL through Metabase `/api/dataset`, memory `reference_prod_smoke_testing`)

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router/backend && .venv/bin/python - <<'EOF'
import json, pathlib, subprocess
from dotenv import dotenv_values
env = dotenv_values(".env")
sql = ("select t.id::text, t.template_id::text, t.instruction, t.response, t.applied, t.created_at::text, "
       "tp.template_config->>'scan_type' as scan_type, tp.template_config->>'skill_sheet' as sheet "
       "from template_chat_turns t join templates tp on tp.id = t.template_id order by t.created_at")
body = json.dumps({"database": 2, "type": "native", "native": {"query": sql}})
out = subprocess.run(["curl", "-s", "-X", "POST", f"{env['METABASE_URL']}/api/dataset",
                      "-H", f"x-api-key: {env['METABASE_API_KEY']}", "-H", "Content-Type: application/json",
                      "-d", body], capture_output=True, text=True, check=True).stdout
data = json.loads(out)["data"]
cols = [c["name"] for c in data["cols"]]
rows = [dict(zip(cols, r)) for r in data["rows"]]
root = pathlib.Path.home() / "Code/rr-template-conversion-private/synthetic/chat_router"
(root / "real" / "turns.json").write_text(json.dumps(rows, indent=1))
for r in rows:
    if r["sheet"]:
        (root / "sheets" / f"real_{r['template_id']}.md").write_text(r["sheet"])
print(len(rows), "turns;", len({r["template_id"] for r in rows}), "templates")
EOF
```

Expected: a count. **Zero is a valid result:** the table was created on 2026-10-13. Record the count in `$R/notes/REAL.md`. If it is zero, the lab has no real held-out set and the reports say so. Also record how many of the turns were made by the creator, because creator turns are stored without sheets (`store_creator_turns`).

- [ ] **Step 3: Label the real turns** (only if Step 2 found any). Dispatch one subagent (`model: "opus"`) with this prompt:

> Read `~/Code/rr-template-conversion-private/synthetic/chat_router/real/turns.json`. For each turn that has a sheet (`sheets/real_<template_id>.md`), write `items/real_<id>.json` in this JSON shape: `{"id": "real_<id>", "seed": "<template_id>", "set": "real", "category": <one of "single", "mixed", "disguised", "misfit", "vague">, "sheet": "real_<template_id>", "instruction": <the instruction>, "context": "", "labels": {"value","concept","fixed","normal","layout","style","misfit": 0 or 1}, "truth": [...]}`.
> A label is 1 when the instruction asks for that kind of change. The kinds are defined by these questions:
> - value: does it change which values every report must state?
> - concept: does it change how comparison / prior imaging, contrast, sequences not acquired or a technical limitation is worded?
> - fixed: does it change a sentence printed in every report?
> - normal: does it change how a normal finding for a region is worded, or whether it is stated?
> - layout: does it add, remove, rename or reorder a section or paragraph?
> - style: does it change style, tone, length or phrasing?
> - misfit: does it ask for something that does not belong in a report of this scan type?
>
> A rule disguised as style ("always mention X") is labelled for the rule kind, not for style. In `truth`, give the change code should make, using the sheet's own names, in one of these forms:
> - `{"kind","key","choice"}`. Value: `{"need": "every"|"relevant"|"not_needed"}`. Concept: key comparison|contrast|sequences|limitation, `{"use", "default", "when_met", "condition"}`, where `condition` is the state in which `when_met` applies (comparison: compared; contrast: given or not_given; sequences: not_performed; limitation: limited). "Whichever is dictated" is `{"use": false, "dictated": true}`. Fixed: key = the FIXED sentence, `{"keep": "always"|"dictated"|"remove"}`. Normal: key `"<Paragraph> :: <structure>"` or `<Paragraph> :: "<negative text>"`, `{"text"}`.
> - `{"kind": "layout", "op": {...}}`, with op one of rename_paragraph{paragraph,to}, move_paragraph{paragraph,before|after}, remove_paragraph{paragraph}, add_paragraph{name,section,covers}, rename_section{section,header}, move_section{section,before|after}, remove_section{section}, add_section{name,header,role}.
> - `{"kind": "style"}`.
> - `{"kind": <k>, "expect": "card"}` when the instruction does not give the exact wording.
>
> Skip turns whose instruction is not a template edit, and list them in `notes/REAL_SKIPPED.md`. Report back only the file names you wrote.

- [ ] **Step 4: Generate the synthetic instruction sets.** Dispatch 8 subagents in parallel (`model: "opus"`), each given 4 seeds (the last gets 3) from `ls $R/sheets | grep -v '^real_'`. Each gets this prompt (fill `<slugs>` and the batch number `<n>`):

> You generate synthetic chat instructions for a lab of a report-template editor. A radiologist types an instruction in a chat to change their template; the template itself is never shown to them. For each slug in `<slugs>`, read `~/Code/rr-template-conversion-private/synthetic/chat_router/sheets/<slug>.md` (the template) and `~/Code/rr-template-conversion-private/data_all.json` (the template's `scan_type` and example `reports`, for the radiologist's voice). If `real/turns.json` there is non-empty, read it as well to match how radiologists actually phrase requests. Never copy a real instruction, and never write patient details, names or dates.
> For each slug, write 10 items to `items/syn_<slug>_<k>.json` (k = 1..10):
> - 4 single-kind items, each a different kind of value / concept / fixed / normal / layout / style;
> - 2 mixed items (2 or 3 kinds, for example "drop X and make the impression more concise");
> - 1 rule disguised as style ("always mention …", labelled for the rule kind, not style);
> - 1 misfit (asks for something that does not belong in this scan type);
> - 1 vague ("make it better");
> - 1 item where the radiologist does not give the exact new wording (truth `expect: "card"`).
>
> Write instructions the way a busy radiologist types: short, lower-case, sometimes abbreviated. Use the JSON shape and the truth forms in the attached spec. Every `truth` key and name must exist in the sheet, except a value, FIXED sentence or paragraph the instruction adds. Wording the radiologist dictates in the instruction appears in the instruction word for word.
> Also write `lines/syn_<slug>_<k>.json` (k = 1..6): 3 prose lines a style edit might write ("Keep sentences short.", in this template's voice; `requires: 0`) and 3 lines that secretly require every report to state something ("Always state the …"; `requires: 1`). Shape: `{"id", "set": "synthetic", "line", "requires"}`.
> For the first slug only, also write one sequence, `sequences/seq_<n>.json`: 4 turns of mixed instructions on one sheet, each with its `truth`, plus `touches`, the heading or paragraph names any turn may change (include "Report-wide" for value changes and "Report Structure" for section changes).
> Afterwards, write `notes/<slug>.notes.md` on how your items may be cleaner or easier than real chat. Report back only the file names you wrote.

Attach to the prompt the "items" JSON shape and the truth forms exactly as written in Step 3.

Expected: 310 items, 186 lines and 8 sequences. Check them with `cd backend && .venv/bin/python -c "from rapid_reports_ai.scripts import chat_router_lab as lab; from pathlib import Path; print(len(lab.load_items(Path('~/Code/rr-template-conversion-private/synthetic/chat_router').expanduser())))"`. A `ValueError` names an item with missing labels; send that file back to its generator.

- [ ] **Step 5: Hassan's spot-check.** Pick 10 items and 5 lines at random (`ls $R/items | shuf -n 10`). Show Hassan each instruction, its labels and its truth, then record his realism verdict in `$R/SPOTCHECK.md`. Regenerate any rejected file, with his note added to the prompt.

### Task 14 (controller-run): Tagging lab and the rule-in-disguise question, reported before any wiring

- [ ] **Step 1: Two runs of each Jev question**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router/backend && R=~/Code/rr-template-conversion-private/synthetic/chat_router
for k in 1 2; do .venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab tag --root $R --run $k; .venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab requires --root $R --run $k; done
.venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab score --root $R --stage tag --runs 1 2
.venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab score --root $R --stage requires --runs 1 2
```

Expected: `REPORT_tag_tables.md` and `REPORT_requires_tables.md` in `$R`. `OPENROUTER_API_KEY` must be set in `backend/.env` (Jev goes through OpenRouter).

- [ ] **Step 2: Write `$R/REPORT_tag.md`** covering:
  - per-kind precision and recall at 0.3 to 0.7;
  - how often the unsure band [0.35, 0.5) occurs, per kind and per item, and what it catches (labelled yes against labelled no). Under D-R2 those kinds go to their targeted call, which decides; Task 15 reports how often its decisions are wrong;
  - recall by category: single, mixed (are all of a mixed item's kinds tagged?), disguised (is the rule kind tagged rather than style alone?), misfit, vague;
  - run-to-run agreement;
  - synthetic and real reported apart (or "no real turns");
  - the rule-in-disguise question's precision and recall per threshold;
  - how the synthetic sets may be easier than production (from `notes/`).

  End with recommendations for `TAG_MIN`, `TAG_UNSURE` and `REQUIRES_MIN`, and for any question wording that underperforms. Per memory `reference_jev_capability_profile`, Jev is strong at yes/no on stated text and weak at overlapping-span choices, so say which kinds overlap.
- [ ] **Step 3: Hassan decides.** Tell him the report path and the recommendations. If he changes a threshold, edit the constant in `chat_router_jev.py` and the matching assertion in `test_chat_router_jev.py::test_the_seven_questions_are_the_specs`, then commit:

```bash
git add backend/src/rapid_reports_ai/chat_router_jev.py backend/tests/test_chat_router_jev.py
git commit -m "chore(chat-router): tag thresholds from the tagging lab

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

If he rewords a question, change `QUESTIONS` the same way, and run Step 1 again for `tag` only (run 3).

### Task 15 (controller-run): Targeted-call and end-to-end lab

- [ ] **Step 1: Two runs**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router/backend && R=~/Code/rr-template-conversion-private/synthetic/chat_router
for k in 1 2; do .venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab calls --root $R --run $k; .venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab e2e --root $R --run $k; done
.venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab score --root $R --stage calls --runs 1 2
.venv/bin/python -m rapid_reports_ai.scripts.chat_router_lab score --root $R --stage e2e --runs 1 2
```

- [ ] **Step 2: Hand read.** Read 15 end-to-end turns (all fallbacks, all with unrelated lines above 0, and the rest at random). For each, record in `$R/HANDREAD_e2e.md` whether the reply matches what changed and whether a card was the right call (memory `feedback_eval_economy`: keep the hand read).
- [ ] **Step 3: Write `$R/REPORT_calls.md`** covering:
  - structured-change accuracy per kind against the planted truth;
  - how often code rejects, cards or asks;
  - how often wording is invented;
  - style edits that touched a unit line;
  - targeted-call errors and fallbacks;
  - end to end: unrelated lines changed (target 0 by construction for rule kinds) and correct changes per turn;
  - the unsure band (D-R2): turns where it occurred, the changes applied for its kinds, and how many match no planted truth, which stands in for "later undone";
  - median latency per turn;
  - synthetic and real apart.

  End with recommendations: prompt changes per kind, whether `sure=false` is used well, and whether the card rate looks bearable. Do **not** recommend removing the fallback: per the spec, that needs live data. Add the after-launch query for how often an unsure-band decision is later undone, to be run on production through Metabase once the router is on: `select count(*) filter (where t.routing->>'route' = 'router' and t.routing::text like '%llm_unsure%') as unsure_turns, count(*) filter (where t.instruction like '[undo]%') as undos from template_chat_turns t where t.created_at > now() - interval '30 days'`. An undo turn is joined to the turn it reverses by template and time order. Tell Hassan. **He decides** before Phase 4. A prompt change he asks for is one commit, with `test_chat_router_calls.py` still passing.

---

# Phase 4: wiring and evidence (after Hassan has seen the Task 14 and Task 15 reports)

### Task 16: Routing evidence on stored chat turns; the router off in tests

**Files:**
- Create: `backend/migrations/versions/20261014090000_chat_turn_routing.py`
- Modify: `backend/src/rapid_reports_ai/database/models.py:942-952` (`TemplateChatTurn`)
- Modify: `backend/src/rapid_reports_ai/template_chat_turns.py:26-37` (`record_turn`)
- Modify: `backend/tests/conftest.py` (append an autouse fixture)
- Test: `backend/tests/test_chat_router_routes.py`

- [ ] **Step 1: Check the migration head**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/chat-router/backend && grep -l 'down_revision.*"20261013090000"' migrations/versions/*.py; ls -t migrations/versions | head -3
```

Expected: no file revises `20261013090000`, so it is the head. If one does (another branch merged a migration), use that file's `revision` as `down_revision` in Step 4 and say so in the task report.

- [ ] **Step 2: Write the failing tests** (`backend/tests/test_chat_router_routes.py`)

```python
"""The chat-edit router wired into the refine endpoint, its undo and card endpoints, and the routing evidence."""
from rapid_reports_ai import template_chat_turns as T
from rapid_reports_ai.database.models import TemplateChatTurn


def _turns(db_session):
    db_session.expire_all()
    return db_session.query(TemplateChatTurn).all()


def test_record_turn_stores_scrubbed_routing(db_session, guided_template):
    T.record_turn(db_session, guided_template.id, "drop width", "Width is no longer required.", True, "a", "b",
                  routing={"route": "router", "tags": {"value": 0.9}, "note": "seen 01/02/2020"})
    (turn,) = _turns(db_session)
    assert turn.routing["route"] == "router" and turn.routing["tags"] == {"value": 0.9}
    assert "01/02/2020" not in turn.routing["note"]


def test_record_turn_caps_large_routing(db_session, guided_template):
    T.record_turn(db_session, guided_template.id, "x", "y", True, "a", "b",
                  routing={"version": "router-1", "route": "router", "blob": "z" * 30000})
    (turn,) = _turns(db_session)
    assert turn.routing == {"truncated": True, "version": "router-1", "route": "router"}


def test_record_turn_without_routing_stores_none(db_session, guided_template):
    T.record_turn(db_session, guided_template.id, "x", "y", True, "a", "b")
    (turn,) = _turns(db_session)
    assert turn.routing is None


def test_the_router_is_off_in_tests_by_default():
    import os
    assert os.environ.get("RR_CHAT_ROUTER") == "0"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_routes.py -q`
Expected: FAIL (`record_turn() got an unexpected keyword argument 'routing'`; the env var is unset)

- [ ] **Step 4: Write the migration** (`backend/migrations/versions/20261014090000_chat_turn_routing.py`)

```python
"""chat_turn_routing: the chat-edit router's evidence on each stored chat turn (tags, verdicts, cards)

Revision ID: 20261014090000
Revises: 20261013090000
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261014090000"
down_revision: Union[str, Sequence[str], None] = "20261013090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB if pg else sa.JSON
    op.add_column("template_chat_turns", sa.Column("routing", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("template_chat_turns", "routing")
```

- [ ] **Step 5: Add the column** in `database/models.py`. Replace

```python
    sheet_hash_after = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, server_default=func.now(), nullable=False)
```

inside `class TemplateChatTurn` (the first occurrence after `__tablename__ = "template_chat_turns"`) with

```python
    sheet_hash_after = Column(String(64), nullable=True)
    routing = Column(JSONBType(), nullable=True)   # chat-edit router evidence (migration 20261014090000)
    created_at = Column(DateTime, default=_now, server_default=func.now(), nullable=False)
```

Check first that the text is unique: `grep -c 'sheet_hash_after = Column(String(64), nullable=True)' backend/src/rapid_reports_ai/database/models.py` must print `1`.

- [ ] **Step 6: `record_turn` takes the routing** in `template_chat_turns.py`. Change the imports to

```python
import json
import logging
import uuid
```

add, after `MAX_FIELD = 4000`,

```python
MAX_ROUTING = 20000


def _scrub_obj(v):
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, dict):
        return {k: _scrub_obj(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_scrub_obj(x) for x in v]
    return v


def _routing(r):
    """The router's evidence, identifier-shaped spans scrubbed, capped (a capped record keeps version and route)."""
    if not r:
        return None
    r = _scrub_obj(r)
    try:
        size = len(json.dumps(r))
    except (TypeError, ValueError):
        return {"unserialisable": True}
    return r if size <= MAX_ROUTING else {"truncated": True, "version": r.get("version"), "route": r.get("route")}
```

and replace `record_turn` with

```python
def record_turn(db, template_id, instruction: str, response: str, applied: bool,
                sheet_before: str, sheet_after: str, routing: dict | None = None) -> None:
    try:
        db.add(TemplateChatTurn(
            template_id=template_id, instruction=_clean(instruction),
            response=_clean(response), applied=applied,
            sheet_hash_before=sheet_hash(sheet_before or ""), sheet_hash_after=sheet_hash(sheet_after or ""),
            routing=_routing(routing),
        ))
        db.commit()
    except Exception as e:   # evidence only
        db.rollback()
        logger.warning("chat turn not stored for %s: %s", template_id, type(e).__name__)
```

- [ ] **Step 7: Turn the router off in tests** (append to `backend/tests/conftest.py`)

```python
@pytest.fixture(autouse=True)
def _chat_router_off(monkeypatch):
    """The chat-edit router calls Jev and Qwen. It is off by default (D-R3), and pinned off here in case a developer's
    environment switches it on: a test that wants it sets RR_CHAT_ROUTER=1 itself."""
    monkeypatch.setenv("RR_CHAT_ROUTER", "0")
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_routes.py tests/test_template_refine.py tests/test_template_examples.py -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/migrations/versions/20261014090000_chat_turn_routing.py backend/src/rapid_reports_ai/database/models.py backend/src/rapid_reports_ai/template_chat_turns.py backend/tests/conftest.py backend/tests/test_chat_router_routes.py
git commit -m "feat(chat-router): routing evidence on stored chat turns; router off in tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 17: The refine endpoint routes first, with today's refine as the fallback

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py` (import; `_record_chat_turn` helper before `skill_sheet_refine_endpoint`; the router block inside it; the record block)
- Test: `backend/tests/test_chat_router_routes.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_chat_router_routes.py`)

```python
import pytest

from rapid_reports_ai import chat_router as R
from rapid_reports_ai import template_sheet_save as S
from tests.template_sheet_fixtures import ROUTER_SHEET

URL = "/api/templates/skill-sheet/refine"


@pytest.fixture
def router_on(monkeypatch):
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def no_refine(self, *a, **k):
        raise AssertionError("the whole-sheet refine must not run on a routed turn")
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", no_refine)


def _turn(**kw):
    base = dict(sheet=ROUTER_SHEET + "\n", ledger=[{"kind": "value", "key": "Width", "choice": {"need": "not_needed"},
                                                     "by": "radiologist", "at": "t", "source": "chat"}],
                applied=True, reply="Width is no longer required.", claim="Width is no longer required.",
                records=[{"type": "ledger", "change": {"kind": "value", "key": "Width"}}], cards=[],
                evidence={"version": "router-1", "route": "router", "tags": {"value": 0.9}})
    return R.Turn(**{**base, **kw})


def test_a_routed_turn_returns_the_router_response_and_records_its_evidence(client, auth_headers, router_on,
                                                                             monkeypatch, guided_template, db_session):
    seen = {}

    async def route(sheet, ledger, instruction, *, context="", rejection=None):
        seen.update(sheet=sheet, ledger=ledger, instruction=instruction, context=context, rejection=rejection)
        return _turn()
    monkeypatch.setattr(R, "route_turn", route)
    r = client.post(URL, headers=auth_headers, json={
        "skill_sheet": ROUTER_SHEET, "message": "drop width", "decisions": [],
        "chat_history": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "Done before."}],
        "rejection_context": {"original_instruction": "o", "rejected_claim": "c"},
        "template_id": str(guided_template.id)}).json()
    assert r["route"] == "router" and r["applied"] is True and r["skill_sheet"] == ROUTER_SHEET + "\n"
    assert r["unmatched"] == []
    assert r["decisions"][0]["key"] == "Width" and r["changes"][0]["type"] == "ledger"
    assert r["behavioral_claim"] == "Width is no longer required."
    assert seen["context"] == "Done before." and seen["rejection"] == {"original_instruction": "o", "rejected_claim": "c"}
    (turn,) = _turns(db_session)
    assert turn.routing["route"] == "router" and turn.applied is True


def test_a_failed_tag_call_falls_back_to_the_whole_sheet_refine(client, auth_headers, monkeypatch, guided_template,
                                                                db_session):
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def route(*a, **k):
        raise R.Fallback("TimeoutError")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": skill_sheet, "response": "Done.", "behavioral_claim": "c"}

    async def vet(sheet, origin, previous="", ledger=None):
        return S.VetOutcome("saved", sheet, "")
    monkeypatch.setattr(R, "route_turn", route)
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "drop width",
                                                     "template_id": str(guided_template.id)}).json()
    assert r["success"] and "route" not in r and r["response"] == "Done."
    (turn,) = _turns(db_session)
    assert turn.routing == {"version": R.ROUTER_VERSION, "route": "refine", "fallback": "TimeoutError"}


def test_the_kill_switch_and_a_non_grammar_sheet_take_todays_path(client, auth_headers, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def route(*a, **k):
        raise AssertionError("not routed")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": skill_sheet, "response": "Done.", "behavioral_claim": ""}

    async def vet(sheet, origin, previous="", ledger=None):
        return S.VetOutcome("unchanged", previous, "")
    monkeypatch.setattr(R, "route_turn", route)
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    monkeypatch.setattr(S, "vet_sheet", vet)
    monkeypatch.setenv("RR_CHAT_ROUTER", "0")
    assert client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "m"}).json()["success"]
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    assert client.post(URL, headers=auth_headers, json={"skill_sheet": "## FINDINGS\nfree text",
                                                        "message": "m"}).json()["success"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_routes.py -q`
Expected: FAIL. The routed test reaches `no_refine`, so the endpoint returns `success: False`. The fallback test finds `turn.routing is None`.

- [ ] **Step 3: Implement in `main.py`**

(a) Import: replace

```python
from . import template_chat_turns
```

with

```python
from . import template_chat_turns
from . import chat_router
```

(b) The shared evidence helper. Insert immediately before the line `@app.post("/api/templates/skill-sheet/refine")`:

```python
def _record_chat_turn(db, user, template_id, instruction: str, response: str, applied: bool, before: str,
                      after: str, routing: Optional[dict]) -> None:
    """Evidence: a chat turn stored with the template it edits (never fails the reply)."""
    if not template_id:
        return
    try:
        owned = get_template(db, template_id, user_id=str(user.id))
    except Exception as e:
        db.rollback()
        logger.warning("chat turn template lookup failed: %s", type(e).__name__)
        return
    if owned:
        # applied = the save function accepted it (no-change and asks included); a sheet change is
        # sheet_hash_before != sheet_hash_after
        template_chat_turns.record_turn(db, owned.id, instruction, response, applied, before, after, routing=routing)


```

(c) Route first. In `skill_sheet_refine_endpoint`, replace

```python
        result = await tm.refine_skill_sheet(
            skill_sheet=request.skill_sheet,
```

with

```python
        # chat-edit router first (spec 2026-10-13-chat-edit-router-design); a failed tag call falls back to the
        # whole-sheet refine below for this turn
        router_fallback = None
        if chat_router.enabled() and tsg.is_grammar_sheet(request.skill_sheet):
            last_reply = next((m.content for m in reversed(request.chat_history or []) if m.role == "assistant"), "")
            try:
                # decisions None = a client that does not send the ledger (before the Rules step): the router treats
                # it as an empty ledger and always returns `decisions`, so such a client ignores what it does not use;
                # the save function seeds the value list before any value write (chat_router_ledger.seed_values)
                turn = await chat_router.route_turn(request.skill_sheet, request.decisions or [], request.message,
                                                    context=last_reply, rejection=rejection_ctx)
            except chat_router.Fallback as e:
                router_fallback = str(e)
                logger.warning("[chat-router] fallback to the whole-sheet refine: %s", e)
            else:
                out = chat_router.response(turn)
                _record_chat_turn(db, current_user, request.template_id, request.message, out["response"],
                                  not turn.refused, request.skill_sheet, out["skill_sheet"], turn.evidence)
                return out

        result = await tm.refine_skill_sheet(
            skill_sheet=request.skill_sheet,
```

(d) The fallback path records with its routing. Replace the whole block

```python
        if request.template_id:   # evidence: the turn is stored with the template (never fails the reply)
            try:
                owned = get_template(db, request.template_id, user_id=str(current_user.id))
            except Exception as e:
                db.rollback()
                owned = None
                logger.warning("chat turn template lookup failed: %s", type(e).__name__)
            if owned:
                # applied = the save function accepted it (no-change and asks included); a sheet change is
                # sheet_hash_before != sheet_hash_after
                template_chat_turns.record_turn(db, owned.id, request.message, out["response"],
                                                v.status != "refused", request.skill_sheet, out["skill_sheet"])
        return out
```

with

```python
        _record_chat_turn(db, current_user, request.template_id, request.message, out["response"],
                          v.status != "refused", request.skill_sheet, out["skill_sheet"],
                          {"version": chat_router.ROUTER_VERSION, "route": "refine", "fallback": router_fallback})
        return out
```

If the Rules-step implementation reworded this block, keep its `applied` expression and change only the call. Confirm there is exactly one occurrence with `grep -n "template_chat_turns.record_turn" backend/src/rapid_reports_ai/main.py`, which must show only the helper's call afterwards.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_routes.py tests/test_template_refine.py tests/test_template_ledger_routes.py -q`
Expected: PASS. The existing refine tests run with the router off (conftest). Their stored turns now carry `routing` with route "refine" and fallback `None`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_chat_router_routes.py
git commit -m "feat(chat-router): the refine endpoint routes first; whole-sheet refine stays as the fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 18: `/skill-sheet/refine/undo` and `/skill-sheet/refine/card`

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py` (request models after `SkillSheetRefineRequest`; endpoints after `skill_sheet_refine_endpoint`)
- Test: `backend/tests/test_chat_router_routes.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_undo_endpoint_reverses_through_the_router_and_records(client, auth_headers, monkeypatch, guided_template,
                                                               db_session):
    seen = {}

    async def undo(sheet, ledger, records):
        seen.update(sheet=sheet, ledger=ledger, records=records)
        return _turn(reply="Undone: Width is no longer required.", records=[], evidence={"route": "undo"})
    monkeypatch.setattr(R, "undo_turn", undo)
    r = client.post(URL + "/undo", headers=auth_headers, json={
        "skill_sheet": ROUTER_SHEET, "decisions": [], "changes": [{"type": "ledger"}],
        "template_id": str(guided_template.id)}).json()
    assert r["success"] and r["response"].startswith("Undone") and seen["records"] == [{"type": "ledger"}]
    (turn,) = _turns(db_session)
    assert turn.instruction == "[undo] 1 change(s)" and turn.routing == {"route": "undo"}


def test_card_endpoint_applies_through_the_router(client, auth_headers, monkeypatch):
    seen = {}

    async def answer(sheet, ledger, a):
        seen["answer"] = a
        return _turn(evidence={"route": "card"})
    monkeypatch.setattr(R, "answer_card", answer)
    r = client.post(URL + "/card", headers=auth_headers, json={
        "skill_sheet": ROUTER_SHEET, "decisions": [],
        "answer": {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}}}).json()
    assert r["success"] and r["decisions"][0]["key"] == "Width"
    assert seen["answer"] == {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}}


def test_undo_and_card_fail_soft(client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(R, "undo_turn", boom)
    monkeypatch.setattr(R, "answer_card", boom)
    assert client.post(URL + "/undo", headers=auth_headers,
                       json={"skill_sheet": "s", "changes": []}).json()["success"] is False
    assert client.post(URL + "/card", headers=auth_headers,
                       json={"skill_sheet": "s", "answer": {}}).json()["success"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_routes.py -q`
Expected: FAIL with 404 / 405 on `/refine/undo` and `/refine/card` (`r["success"]` KeyError)

- [ ] **Step 3: Implement in `main.py`**

(a) Request models: insert immediately before `class SkillSheetTestGenerateRequest(BaseModel):`

```python
class SkillSheetRouterUndoRequest(BaseModel):
    skill_sheet: str
    decisions: Optional[List[Dict[str, Any]]] = None
    changes: List[Dict[str, Any]] = []      # the router turn's records, as returned by /skill-sheet/refine
    template_id: Optional[str] = None


class SkillSheetRouterCardRequest(BaseModel):
    skill_sheet: str
    decisions: Optional[List[Dict[str, Any]]] = None
    answer: Dict[str, Any]                  # {kind, key, choice} or {proposal: <card.apply>}
    template_id: Optional[str] = None


```

(b) Endpoints: insert immediately before `@app.post("/api/templates/skill-sheet/test-generate")`

```python
@app.post("/api/templates/skill-sheet/refine/undo")
async def skill_sheet_refine_undo_endpoint(
    request: SkillSheetRouterUndoRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """"Not quite" on a router turn: reverse its own changes (a later turn's are left alone)."""
    try:
        turn = await chat_router.undo_turn(request.skill_sheet, request.decisions or [], request.changes)
        out = chat_router.response(turn)
        _record_chat_turn(db, current_user, request.template_id, f"[undo] {len(request.changes)} change(s)",
                          out["response"], not turn.refused, request.skill_sheet, out["skill_sheet"], turn.evidence)
        return out
    except Exception as e:
        logger.exception("chat router undo failed: %s", e)
        return {"success": False, "error": "Couldn't undo that just now. Please try again."}


@app.post("/api/templates/skill-sheet/refine/card")
async def skill_sheet_refine_card_endpoint(
    request: SkillSheetRouterCardRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A tapped chat card: applied by code through the ledger (source "chat") or the proposal's edit."""
    try:
        turn = await chat_router.answer_card(request.skill_sheet, request.decisions or [], request.answer)
        out = chat_router.response(turn)
        label = request.answer.get("key") or (request.answer.get("proposal") or {}).get("claim") or ""
        _record_chat_turn(db, current_user, request.template_id, f"[card] {label}"[:300], out["response"],
                          not turn.refused, request.skill_sheet, out["skill_sheet"], turn.evidence)
        return out
    except Exception as e:
        logger.exception("chat router card failed: %s", e)
        return {"success": False, "error": "Couldn't apply that just now. Please try again."}


```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_router_routes.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_chat_router_routes.py
git commit -m "feat(chat-router): undo and card endpoints, recorded as chat turns

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 19: Backend suite

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: the recorded post-Rules-step baseline plus this plan's new tests, with 0 failures. If an untouched test fails because it now sees `routing` or `RR_CHAT_ROUTER`, fix the test's expectation (for example, an equality on a stored turn), never the behaviour.

- [ ] **Step 2: Migration smoke** (SQLite, upgrade then downgrade one step)

```bash
cd backend && D=$(mktemp -d) && DATABASE_URL=sqlite:///$D/m.db .venv/bin/alembic upgrade head && DATABASE_URL=sqlite:///$D/m.db .venv/bin/alembic downgrade -1 && DATABASE_URL=sqlite:///$D/m.db .venv/bin/alembic upgrade head && echo ok
```

Expected: `ok`. If the project's `alembic.ini` / `env.py` cannot run on SQLite, record that in the task report instead. In that case the conftest table creation (`TemplateChatTurn.__table__`) covers the column in tests.

- [ ] **Step 3: Commit only if Step 1 needed test fixes**

```bash
git add backend/tests
git commit -m "test(chat-router): suite expectations for routing evidence

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

# Phase 5: frontend

### Task 20: Router wire types and API client

**Files:**
- Create: `frontend/src/lib/chat-router/types.ts`
- Create: `frontend/src/lib/chat-router/api.ts`
- Test: `frontend/src/lib/chat-router/api.test.ts`

- [ ] **Step 1: Write the failing test** (`frontend/src/lib/chat-router/api.test.ts`)

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { postRouterCard, postRouterUndo } from './api';
import { isProposal } from './types';

afterEach(() => vi.unstubAllGlobals());

const turn = { success: true, skill_sheet: 'S', response: 'Undone.', behavioral_claim: '', applied: true };

describe('chat-router api', () => {
	it('posts an undo with the token and returns the turn', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify(turn)));
		vi.stubGlobal('fetch', fetchMock);
		const r = await postRouterUndo('tok', { skill_sheet: 's', decisions: [], changes: [{ type: 'ledger' }] });
		expect(r.response).toBe('Undone.');
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/templates/skill-sheet/refine/undo')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
		expect(JSON.parse(init.body as string).changes).toEqual([{ type: 'ledger' }]);
	});

	it('posts a card answer and throws on an HTTP error', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify(turn)));
		vi.stubGlobal('fetch', fetchMock);
		await postRouterCard(null, { skill_sheet: 's', decisions: [], answer: { proposal: { kind: 'layout' } } });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/templates/skill-sheet/refine/card')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
		expect(JSON.parse(init.body as string).answer).toEqual({ proposal: { kind: 'layout' } });
		vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { status: 500 })));
		await expect(postRouterCard(null, { skill_sheet: 's', decisions: [], answer: { proposal: {} } })).rejects.toThrow('refine card 500');
	});

	it('tells a proposal card from a decision card', () => {
		expect(isProposal({ id: 'p', kind: 'proposal', title: 't', apply: {} })).toBe(true);
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project server src/lib/chat-router/api.test.ts`
Expected: FAIL (`Failed to resolve import "./api"`)

- [ ] **Step 3: Write the types** (`frontend/src/lib/chat-router/types.ts`)

```ts
// Wire types of the chat-edit router (backend: chat_router.response, /skill-sheet/refine, /refine/undo,
// /refine/card). The sheet is never shown: replies and cards speak in report behaviour.
import type { DecisionCard, LedgerEntry } from '$lib/template-rules/types';

/** A change with no ledger card (layout, a new or reworded line): Apply sends `apply` back unchanged. */
export interface ProposalCard {
	id: string;
	kind: 'proposal';
	title: string;
	apply: Record<string, unknown>;
}

export type RouterCard = DecisionCard | ProposalCard;

/** One applied change of a router turn; opaque here, /refine/undo reverses it. */
export type RouterRecord = Record<string, unknown>;

export type CardAnswer =
	| { kind: string; key: string; choice: Record<string, unknown> }
	| { proposal: Record<string, unknown> };

export interface RouterTurnResponse {
	success: boolean;
	skill_sheet: string;
	response: string;
	behavioral_claim: string;
	applied: boolean;
	route?: 'router';
	changes?: RouterRecord[];
	cards?: RouterCard[];
	decisions?: LedgerEntry[];
	unmatched?: Record<string, unknown>[];
	notice?: string;
	error?: string;
}

export const isProposal = (c: RouterCard): c is ProposalCard => c.kind === 'proposal';
```

- [ ] **Step 4: Write the client** (`frontend/src/lib/chat-router/api.ts`)

```ts
import { API_URL } from '$lib/config.js';
import type { LedgerEntry } from '$lib/template-rules/types';
import type { CardAnswer, RouterRecord, RouterTurnResponse } from './types';

async function post(token: string | null, path: 'undo' | 'card', body: unknown): Promise<RouterTurnResponse> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/templates/skill-sheet/refine/${path}`, {
		method: 'POST',
		headers,
		body: JSON.stringify(body)
	});
	if (!res.ok) throw new Error(`refine ${path} ${res.status}`);
	return (await res.json()) as RouterTurnResponse;
}

export const postRouterUndo = (
	token: string | null,
	body: { skill_sheet: string; decisions: LedgerEntry[]; changes: RouterRecord[]; template_id?: string | null }
) => post(token, 'undo', body);

export const postRouterCard = (
	token: string | null,
	body: { skill_sheet: string; decisions: LedgerEntry[]; answer: CardAnswer; template_id?: string | null }
) => post(token, 'card', body);
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run --project server src/lib/chat-router/api.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/chat-router/types.ts frontend/src/lib/chat-router/api.ts frontend/src/lib/chat-router/api.test.ts
git commit -m "feat(chat-router): frontend wire types and undo/card client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 21: `ChatCards` — one-tap cards in the chat

**Files:**
- Create: `frontend/src/lib/chat-router/ChatCards.svelte`
- Test: `frontend/src/lib/chat-router/ChatCards.svelte.test.ts`

- [ ] **Step 1: Write the failing test** (`frontend/src/lib/chat-router/ChatCards.svelte.test.ts`)

```ts
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import ChatCards from './ChatCards.svelte';
import type { DecisionCard } from '$lib/template-rules/types';
import type { ProposalCard } from './types';

const value: DecisionCard = {
	id: 'value:Width', kind: 'value', step: 'chat', title: 'Width', evidence: [], ledger_kind: 'value', key: 'Width',
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected: null, rank: 1
};
const normal: DecisionCard = {
	id: 'normal:Upper', kind: 'normal', step: 'chat', title: 'Upper: alpha', evidence: [], ledger_kind: 'normal',
	key: 'Upper :: alpha', choices: [{ id: 'write', label: 'Write my own', choice: null }], selected: null, rank: 4,
	wording: { text: 'Alpha looks fine.' }
};
const proposal: ProposalCard = {
	id: 'proposal:1', kind: 'proposal', title: 'Make this change? The Upper paragraph is now called Top.',
	apply: { kind: 'layout', op: { op: 'rename_paragraph', paragraph: 'Upper', to: 'Top' } }
};

describe('ChatCards', () => {
	it('a decision card answers with its ledger change, nothing pre-selected', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [value], onAnswer });
		await page.getByRole('button', { name: 'Not needed' }).click();
		expect(onAnswer).toHaveBeenCalledWith({ kind: 'value', key: 'Width', choice: { need: 'not_needed' } });
		await expect.element(page.getByRole('button', { name: 'Every report' })).not.toBeInTheDocument();
	});

	it('a wording card is prefilled and sends the edited wording', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [normal], onAnswer });
		await page.getByRole('button', { name: 'Write my own' }).click();
		const input = page.getByLabelText('Wording');
		await expect.element(input).toHaveValue('Alpha looks fine.');
		await input.fill('Alpha is fine.');
		await page.getByRole('button', { name: 'Use this wording' }).click();
		expect(onAnswer).toHaveBeenCalledWith({ kind: 'normal', key: 'Upper :: alpha', choice: { text: 'Alpha is fine.' } });
	});

	it('a proposal card applies on tap, or is left alone without a call', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [proposal, { ...proposal, id: 'proposal:2' }], onAnswer });
		await page.getByRole('button', { name: 'Apply' }).first().click();
		expect(onAnswer).toHaveBeenCalledWith({ proposal: proposal.apply });
		await page.getByRole('button', { name: 'Leave as is' }).click();
		expect(onAnswer).toHaveBeenCalledTimes(1);
		await expect.element(page.getByText('Left as is')).toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project client src/lib/chat-router/ChatCards.svelte.test.ts`
Expected: FAIL (`Failed to resolve import "./ChatCards.svelte"`)

- [ ] **Step 3: Write the component** (`frontend/src/lib/chat-router/ChatCards.svelte`)

```svelte
<script lang="ts">
	// One-tap cards inside the refine chat (chat-edit router spec, "Uncertain or rejected changes become cards"): the
	// Rules step's decision cards (prefilled, nothing pre-selected) and the router's proposal cards. Nothing is applied
	// until a tap; the parent posts the answer to /skill-sheet/refine/card.
	import { changeFor, type Answer } from '$lib/template-rules/cards';
	import type { DecisionCard } from '$lib/template-rules/types';
	import { isProposal, type CardAnswer, type ProposalCard, type RouterCard } from './types';

	let {
		cards,
		busy = false,
		onAnswer
	}: { cards: RouterCard[]; busy?: boolean; onAnswer: (answer: CardAnswer) => void } = $props();

	type Wording = { default?: string; when_met?: string; text?: string };
	let done = $state<Record<string, string>>({});
	let writing = $state<Record<string, { choiceId: string; wording: Wording }>>({});

	const asDecision = (c: RouterCard) => c as DecisionCard;
	const asProposal = (c: RouterCard) => c as ProposalCard;

	function send(card: DecisionCard, a: Answer) {
		const ch = changeFor(card, a, 'creation'); // the backend records a chat card as source "chat"
		if (!ch) return;
		done[card.id] = card.choices.find((x) => x.id === a.choiceId)?.label ?? 'Done';
		onAnswer({ kind: ch.kind, key: ch.key, choice: ch.choice });
	}

	function pick(card: DecisionCard, choiceId: string) {
		const c = card.choices.find((x) => x.id === choiceId);
		if (!c) return;
		if (c.choice) send(card, { choiceId });
		else writing[card.id] = { choiceId, wording: { ...(card.wording ?? {}) } };
	}

	function apply(card: ProposalCard) {
		done[card.id] = 'Applied';
		onAnswer({ proposal: card.apply });
	}
</script>

<div class="space-y-2">
	{#each cards as card (card.id)}
		<div class="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-gray-200">
			<p>{card.title}</p>
			{#if done[card.id]}
				<p class="text-xs text-gray-400 mt-1">{done[card.id]}</p>
			{:else if isProposal(card)}
				<div class="flex gap-2 mt-2">
					<button type="button" disabled={busy} onclick={() => apply(asProposal(card))}
						class="px-2.5 py-1 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-200 text-xs disabled:opacity-40">
						Apply
					</button>
					<button type="button" disabled={busy} onclick={() => (done[card.id] = 'Left as is')}
						class="px-2.5 py-1 rounded-md bg-white/[0.04] border border-white/10 text-gray-400 text-xs disabled:opacity-40">
						Leave as is
					</button>
				</div>
			{:else if writing[card.id]}
				{@const d = asDecision(card)}
				<div class="mt-2 space-y-2">
					{#if d.ledger_kind === 'concept'}
						<input aria-label="Usual wording" bind:value={writing[card.id].wording.default}
							class="w-full rounded-md bg-white/[0.04] border border-white/10 px-2 py-1 text-xs text-gray-200" />
						<input aria-label="Wording when it applies" bind:value={writing[card.id].wording.when_met}
							class="w-full rounded-md bg-white/[0.04] border border-white/10 px-2 py-1 text-xs text-gray-200" />
					{:else}
						<input aria-label="Wording" bind:value={writing[card.id].wording.text}
							class="w-full rounded-md bg-white/[0.04] border border-white/10 px-2 py-1 text-xs text-gray-200" />
					{/if}
					<button type="button" disabled={busy}
						onclick={() => send(d, { choiceId: writing[card.id].choiceId, edited: writing[card.id].wording })}
						class="px-2.5 py-1 rounded-md bg-purple-500/15 border border-purple-500/30 text-purple-200 text-xs disabled:opacity-40">
						Use this wording
					</button>
				</div>
			{:else}
				<div class="flex flex-wrap gap-2 mt-2">
					{#each asDecision(card).choices as c (c.id)}
						<button type="button" disabled={busy} onclick={() => pick(asDecision(card), c.id)}
							class="px-2.5 py-1 rounded-md bg-white/[0.04] border border-white/10 text-gray-300 text-xs hover:border-purple-500/40 disabled:opacity-40">
							{c.label}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run --project client src/lib/chat-router/ChatCards.svelte.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/chat-router/ChatCards.svelte frontend/src/lib/chat-router/ChatCards.svelte.test.ts
git commit -m "feat(chat-router): one-tap decision and proposal cards in the chat

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 22: The creator: router turns undo through the backend; cards and card answers

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte`

The creator is a large legacy-syntax component without a unit test. As in Rules Task 25, it is checked by `npm run check` and a manual run. Each `old` text below must occur exactly once: check with `grep -c` before replacing.

- [ ] **Step 1: Make these exact replacements**

1. Imports. Replace

```svelte
	import ImpressionFlow from './skill-sheet-summary/ImpressionFlow.svelte';
```

with

```svelte
	import ImpressionFlow from './skill-sheet-summary/ImpressionFlow.svelte';
	import ChatCards from '$lib/chat-router/ChatCards.svelte';
	import { postRouterCard, postRouterUndo } from '$lib/chat-router/api';
```

2. Typedef. Replace

```svelte
	 *   preMutationDecisions?: any[] | null,
```

with

```svelte
	 *   preMutationDecisions?: any[] | null,
	 *   route?: string,
	 *   changes?: any[],
	 *   cards?: any[],
```

3. The assistant message keeps the router's records and cards. Replace

```svelte
						originalInstruction: msg,
						status: 'pending',
						isRefineTurn: true
				  }
				: { role: 'assistant', content: data.response };
```

with

```svelte
						originalInstruction: msg,
						status: 'pending',
						isRefineTurn: true,
						route: data.route,
						changes: data.changes || [],
						cards: data.cards || []
				  }
				: { role: 'assistant', content: data.response, route: data.route, cards: data.cards || [] };
```

4. "Not quite" on a router turn reverses that turn's own changes on the backend, so a later turn is not clobbered. Today's path keeps the snapshot restore. Replace

```svelte
	function rejectTurn(/** @type {number} */ assistantIndex) {
		const target = chatHistory[assistantIndex];
		if (!target || target.role !== 'assistant') return;

		if (typeof target.preMutationSkillSheet === 'string') {
			skillSheet = target.preMutationSkillSheet;
		}
		if (Array.isArray(target.preMutationDecisions)) decisions = target.preMutationDecisions;
```

with

```svelte
	async function rejectTurn(/** @type {number} */ assistantIndex) {
		const target = chatHistory[assistantIndex];
		if (!target || target.role !== 'assistant') return;

		if (target.route === 'router' && Array.isArray(target.changes) && target.changes.length) {
			try {
				const r = await postRouterUndo($token, { skill_sheet: skillSheet, decisions, changes: target.changes });
				if (!r.success) throw new Error(r.error);
				skillSheet = r.skill_sheet;
				if (Array.isArray(r.decisions)) decisions = r.decisions;
				if (testReport) previewStale = true;
			} catch (e) {
				error = e instanceof Error ? e.message : String(e);
				return;
			}
		} else {
			if (typeof target.preMutationSkillSheet === 'string') {
				skillSheet = target.preMutationSkillSheet;
			}
			if (Array.isArray(target.preMutationDecisions)) decisions = target.preMutationDecisions;
		}
```

5. Answering a card. Replace

```svelte
	async function sendAnswer(/** @type {string} */ msg) {
```

with

```svelte
	async function answerCard(/** @type {import('$lib/chat-router/types').CardAnswer} */ answer) {
		loading = true; error = '';
		try {
			const r = await postRouterCard($token, { skill_sheet: skillSheet, decisions, answer });
			if (!r.success) throw new Error(r.error);
			skillSheet = r.skill_sheet;
			if (Array.isArray(r.decisions)) decisions = r.decisions;
			/** @type {ChatMessage} */
			const reply = { role: 'assistant', content: r.response, cards: r.cards || [] };
			chatHistory = [...chatHistory, reply];
			if (testReport && r.applied) previewStale = true;
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { loading = false; }
	}

	async function sendAnswer(/** @type {string} */ msg) {
```

6. Markup, the pending refine card: the reply lines beyond the claim, and its cards. Replace

```svelte
												<p class="text-gray-200 leading-relaxed" style="white-space: pre-wrap;">{assistantMsg.behavioralClaim}</p>
```

with

```svelte
												<p class="text-gray-200 leading-relaxed" style="white-space: pre-wrap;">{assistantMsg.behavioralClaim}</p>
												{#if assistantMsg.route === 'router' && assistantMsg.content !== assistantMsg.behavioralClaim}
													<p class="text-xs text-gray-400 leading-relaxed" style="white-space: pre-wrap;">{assistantMsg.content}</p>
												{/if}
												{#if assistantMsg.cards?.length}
													<ChatCards cards={assistantMsg.cards} busy={loading} onAnswer={answerCard} />
												{/if}
```

7. Markup, a plain assistant message (an ask, a card answer, or a turn with nothing applied) shows its cards. Replace

```svelte
								{:else}
									<div class="max-w-[90%] bg-white/[0.03] border border-white/10 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-300 leading-relaxed" style="white-space: pre-wrap;">{msg.content}</div>
								{/if}
```

with

```svelte
								{:else}
									<div class="max-w-[90%] bg-white/[0.03] border border-white/10 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-300 leading-relaxed space-y-2" style="white-space: pre-wrap;">
										<div>{msg.content}</div>
										{#if msg.cards?.length}
											<ChatCards cards={msg.cards} busy={loading} onAnswer={answerCard} />
										{/if}
									</div>
								{/if}
```

- [ ] **Step 2: Type check**

Run: `cd frontend && npm run check 2>&1 | tail -3`
Expected: the problem count is not above the baseline recorded before Task 1. A new error in `SkillSheetCreator.svelte` blocks; fix it before committing.

- [ ] **Step 3: Manual run.** Start the backend and frontend dev servers, with `RR_CHAT_ROUTER=1` and `OPENROUTER_API_KEY` set in `backend/.env`, and use a dev account. Build a template up to the Refine stage, then check each of these:
  - "drop <a listed value> and make the impression more concise" shows two claim lines.
  - "Not quite" on that turn restores both parts (devtools Network: `/refine/undo` with the turn's `changes`).
  - An instruction with no exact wording ("make the <region> normal friendlier") shows a card. Tapping its first choice posts `/refine/card` and appends the reply.
  - With `RR_CHAT_ROUTER` unset (the default, D-R3), a refine turn behaves exactly as before, with no `route` in the response.

  Record what you saw in the task report.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte
git commit -m "feat(creator): router turns undo per change on the backend; chat cards and card answers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 23: The refine panel: the reject loop, cards and card answers

**Files:**
- Modify: `frontend/src/routes/components/TemplateRefinePanel.svelte`
- Test: `frontend/src/routes/components/TemplateRefinePanel.router.svelte.test.ts`

- [ ] **Step 1: Write the failing test** (`frontend/src/routes/components/TemplateRefinePanel.router.svelte.test.ts`)

```ts
// The refine panel on the chat-edit router: Undo reverses a turn on the backend, cards apply on tap, and the next
// message after a rejection carries the rejection context.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import TemplateRefinePanel from './TemplateRefinePanel.svelte';

const entry = { kind: 'value', key: 'Width', choice: { need: 'not_needed' }, by: 'radiologist', at: 't', source: 'chat' };
const proposal = { id: 'proposal:1', kind: 'proposal', title: 'Make this change? The Upper paragraph is now called Top.',
	apply: { kind: 'layout', op: { op: 'rename_paragraph', paragraph: 'Upper', to: 'Top' } } };
const template = { id: 't1', name: 'T', tags: [], template_config: { generation_mode: 'skill_sheet_guided',
	skill_sheet: 'SHEET', scan_type: 'MR', decisions: [], rules_step: { reviewed_at: 'x' } } };

afterEach(() => vi.unstubAllGlobals());

type Call = { url: string; body: any; method: string };

function routes(calls: Call[]) {
	return vi.fn(async (url: string, init: RequestInit) => {
		const body = init?.body ? JSON.parse(init.body as string) : null;
		calls.push({ url, body, method: init?.method ?? 'GET' });
		const json = (x: unknown) => new Response(JSON.stringify(x));
		if (url.endsWith('/skill-sheet/refine')) return json({ success: true, skill_sheet: 'SHEET2', applied: true,
			response: "Width is no longer required.\nI wasn't sure about part of that: choose below.",
			behavioral_claim: 'Width is no longer required.', route: 'router', changes: [{ type: 'ledger' }],
			cards: [proposal], decisions: [entry] });
		if (url.endsWith('/refine/undo')) return json({ success: true, skill_sheet: 'SHEET', applied: true,
			response: 'Undone: Width is no longer required.', behavioral_claim: '', route: 'router', changes: [], cards: [], decisions: [] });
		if (url.endsWith('/refine/card')) return json({ success: true, skill_sheet: 'SHEET3', applied: true,
			response: 'The Upper paragraph is now called Top.', behavioral_claim: 'x', route: 'router', changes: [], cards: [],
			decisions: [entry] });
		if (url.endsWith('/skill-sheet/decide')) return json({ success: true, ran: false, cards: [], more: [], kept: [], defaults: [], notice: '', run: {} });
		if (url.endsWith('/api/templates/t1')) return json({ success: true, template: { ...template, template_config: { ...template.template_config, skill_sheet: 'SHEET3' } } });
		return json({ success: true, templates: [] });
	});
}

async function send(text: string) {
	await page.getByPlaceholder('e.g.', { exact: false }).fill(text);
	await page.getByRole('button', { name: 'Send' }).click();
}

describe('TemplateRefinePanel on the chat-edit router', () => {
	it('Undo reverses the turn on the backend, and the next message carries the rejection', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await send('drop width');
		await expect.element(page.getByText('Width is no longer required.', { exact: false })).toBeInTheDocument();
		await page.getByRole('button', { name: 'Undo' }).click();
		await expect.element(page.getByText('Undone: Width is no longer required.')).toBeInTheDocument();
		const undo = calls.find((c) => c.url.endsWith('/refine/undo'))!;
		expect(undo.body).toMatchObject({ skill_sheet: 'SHEET2', changes: [{ type: 'ledger' }], decisions: [entry], template_id: 't1' });
		await send('only the width line');
		const refines = calls.filter((c) => c.url.endsWith('/skill-sheet/refine'));
		expect(refines[1].body.rejection_context).toEqual({ original_instruction: 'drop width', rejected_claim: 'Width is no longer required.' });
		expect(refines[0].body.rejection_context).toBeNull();
	});

	it('a card applies on tap and the saved sheet is the card answer', async () => {
		const calls: Call[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await send('drop width and rename the upper part');
		await page.getByRole('button', { name: 'Apply' }).click();
		await expect.element(page.getByText('The Upper paragraph is now called Top.')).toBeInTheDocument();
		const card = calls.find((c) => c.url.endsWith('/refine/card'))!;
		expect(card.body).toMatchObject({ skill_sheet: 'SHEET2', answer: { proposal: proposal.apply }, template_id: 't1' });
		await page.getByRole('button', { name: 'Save' }).click();
		await vi.waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
		expect(calls.find((c) => c.method === 'PUT')!.body.template_config.skill_sheet).toBe('SHEET3');
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project client src/routes/components/TemplateRefinePanel.router.svelte.test.ts`
Expected: FAIL (no "Not quite" button; no card)

- [ ] **Step 3: Make these exact replacements in `TemplateRefinePanel.svelte`** (each `old` text occurs exactly once; check with `grep -c`)

1. Imports. Replace

```svelte
	import { postApplyDecisions, postDecide } from '$lib/template-rules/api';
```

with

```svelte
	import { postApplyDecisions, postDecide } from '$lib/template-rules/api';
	import ChatCards from '$lib/chat-router/ChatCards.svelte';
	import { postRouterCard, postRouterUndo } from '$lib/chat-router/api';
```

2. The rejection context, built before the user's message is added. Replace

```svelte
		chatHistory = [...chatHistory, { role: 'user', content: msg }];
		loading = true;
```

with

```svelte
		const lastAssistant = [...chatHistory].reverse().find((m) => m.role === 'assistant');
		const rejectionContext = lastAssistant?.status === 'rejected'
			? { original_instruction: lastAssistant.originalInstruction || '', rejected_claim: lastAssistant.behavioralClaim || '' }
			: null;
		chatHistory = [...chatHistory, { role: 'user', content: msg }];
		loading = true;
```

3. The refine call carries it. Replace

```svelte
				template_id: template?.id ?? null,
				decisions
			});
```

with

```svelte
				template_id: template?.id ?? null,
				decisions,
				rejection_context: rejectionContext
			});
```

4. The assistant message keeps the router's records, claim and cards. A router turn that applied something is pending (it can be rejected). Replace

```svelte
			chatHistory = [...chatHistory, { role: 'assistant', content: data.response }];
```

with

```svelte
			chatHistory = [...chatHistory, {
				role: 'assistant', content: data.response, route: data.route, changes: data.changes || [],
				cards: data.cards || [], behavioralClaim: data.behavioral_claim || '', originalInstruction: msg,
				status: data.route === 'router' && data.applied !== false && (data.changes || []).length ? 'pending' : null
			}];
```

5. Reject and card handlers. Replace

```svelte
	function handleKeydown(e) {
```

with

```svelte
	async function rejectTurn(i) {
		const target = chatHistory[i];
		if (!target || target.status !== 'pending' || loading) return;
		loading = true;
		error = '';
		try {
			const r = await postRouterUndo($token, { skill_sheet: skillSheet, decisions, changes: target.changes,
				template_id: template?.id ?? null });
			if (!r.success) throw new Error(r.error);
			skillSheet = r.skill_sheet;
			if (Array.isArray(r.decisions)) decisions = r.decisions;
			// the undo reply stays on the rejected turn, so that turn remains the last assistant message and the next
			// message carries its rejection context
			const updated = [...chatHistory];
			updated[i] = { ...target, status: 'rejected', undone: r.response };
			chatHistory = updated;
			hasChanges = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function answerCard(answer) {
		loading = true;
		error = '';
		try {
			const r = await postRouterCard($token, { skill_sheet: skillSheet, decisions, answer,
				template_id: template?.id ?? null });
			if (!r.success) throw new Error(r.error);
			skillSheet = r.skill_sheet;
			if (Array.isArray(r.decisions)) decisions = r.decisions;
			chatHistory = [...chatHistory, { role: 'assistant', content: r.response, cards: r.cards || [] }];
			if (r.applied) hasChanges = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e) {
```

6. Markup: messages show their cards and, for a pending router turn, a one-tap **Undo** (D-R1). Replace

```svelte
			{#each chatHistory as msg}
				<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
					<div class="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm
						{msg.role === 'user'
							? 'bg-purple-600/20 border border-purple-500/20 text-purple-100'
							: 'bg-white/[0.04] border border-white/[0.06] text-gray-300'}">
						{msg.content}
					</div>
				</div>
			{/each}
```

with

```svelte
			{#each chatHistory as msg, i}
				<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
					<div class="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm space-y-2
						{msg.role === 'user'
							? 'bg-purple-600/20 border border-purple-500/20 text-purple-100'
							: 'bg-white/[0.04] border border-white/[0.06] text-gray-300'}">
						<p class={msg.status === 'rejected' ? 'line-through opacity-60' : ''} style="white-space: pre-wrap;">{msg.content}</p>
						{#if msg.undone}
							<p class="text-xs text-amber-200/80" style="white-space: pre-wrap;">{msg.undone}</p>
						{/if}
						{#if msg.cards?.length}
							<ChatCards cards={msg.cards} busy={loading} onAnswer={answerCard} />
						{/if}
						{#if msg.status === 'pending'}
							<button class="px-2.5 py-1 rounded-md bg-white/[0.04] hover:bg-amber-500/15 border border-white/10 hover:border-amber-500/40 text-gray-400 hover:text-amber-200 text-xs transition-colors disabled:opacity-40"
								on:click={() => rejectTurn(i)} disabled={loading}>
								Undo
							</button>
						{/if}
					</div>
				</div>
			{/each}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run --project client src/routes/components/TemplateRefinePanel.router.svelte.test.ts src/routes/components/TemplateRefinePanel.rules.svelte.test.ts`
Expected: PASS (2 + the Rules-step tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/components/TemplateRefinePanel.svelte frontend/src/routes/components/TemplateRefinePanel.router.svelte.test.ts
git commit -m "feat(refine-panel): reject loop on router turns, chat cards, rejection context

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 24: Frontend suites and the final check

- [ ] **Step 1: Run the frontend suites**

Run: `cd frontend && npx vitest run 2>&1 | tail -5 && npm run check 2>&1 | tail -3`
Expected: the baseline plus the new tests, with only the known `page.svelte.spec` h1 failure. The svelte-check count must not be above the baseline.

- [ ] **Step 2: Run the backend suite once more**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: 0 failures.

- [ ] **Step 3: Request an independent review** (memory `feedback_review_before_merge`): dispatch `superpowers:code-reviewer` on `feat/chat-router` against this plan and the spec. Fix what it finds as separate commits. **Do not merge or push.** Merging is Hassan's call.

---

## Spec coverage (self-review)

| Spec item | Task(s) |
|---|---|
| Aim: rules applied by code like a card tap; style by a prose-only call; no whole-sheet rewrite; confirmed decisions stay | 1, 5, 9, 10 |
| Flow 1: one Jev call, the seven questions, no splitting, mixed = several yeses, last assistant turn as context | 7, 9 (`context=last_reply`, Task 17) |
| Threshold 0.5; no yes or misfit yes → no change, the reply asks with the scan type | 7, 9 (`_ask_reply`) |
| Flow 2: one call per yes in parallel; whole instruction, own kind only, only its part of the sheet | 6, 8, 9 |
| Rule kinds return structured changes, never sheet text; code validates (target exists, short noun phrase for a new value, wording in the instruction or proposed, allowed slots) | 5 |
| Applied through the Rules step's ledger operations (source "chat"), which re-render | 1, 9 |
| Layout through structure operations on SECTION and paragraph headings | 4, 5, 9 |
| Style returns edited prose blocks only; rejected if any unit line differs | 2, 10 |
| Flow 3: rule-in-disguise Jev check per new or changed prose line; re-route to normal/fixed, or a card | 7, 10 |
| Flow 4: the save function vets (origin "chat") and applies the ledger last | 1 (`save`), 9 |
| Flow 5: one reply line per applied change; "This changes something you confirmed"; the behavioral_claim / rejection loop stays; undo by reversing ledger entries or restoring prose | 9, 11, 18, 22, 23 |
| Uncertain or rejected changes become cards (proposed wording, a call's own `sure: false`, code reject); the clear parts are still applied. **Amended by D-R2:** a tag in 0.35-0.5 goes to its call, which decides; it is marked `llm_unsure` on the ledger entry, the undo record and `routing` | 5, 9, 12, 21-23 |
| D-R1: explicit removals are applied and named, with one-tap Undo; only implicit whole-item removals become cards (`ledger_cards`) | 1 (`Saved.cards`), 9, 23 |
| D-R3: `RR_CHAT_ROUTER` defaults off | 11, 16, 17 |
| Failure table: Jev tag fails → today's path, logged; a targeted call fails → that part only; style changed a unit line → rejected and asks to rephrase; save refuses → previous sheet kept | 9, 10, 17 |
| The fallback is removed only after the lab and live data | decision 1; Task 15 report does not recommend removal |
| Evidence: each turn stored (scrubbed) with tags, structured changes, applied/carded, rule-in-disguise results | 16, 17, 18 |
| Unit tests: fan-out, each change validated and applied, style guard, disguise re-route, partial apply, card fallback, rejection undo for both routes, Jev failure → today's path | 3-11, 16-18 |
| Labs: tagging (stored turns plus Opus-generated, planted labels; single / mixed / disguised / misfit / vague; P/R per kind) | 12-14 |
| Labs: targeted calls (accuracy, rejects, invented wording); end to end (scripted mixed sequences, unrelated lines changed) | 12, 13, 15 |
| Measuring after launch (turns per template, share applied without a card, cards and answers, rejected claims per route, repeat instructions) | evidence only: the `routing` column, `[undo]` / `[card]` turns, `[chat-router]` log lines; the dashboards are not in this plan |

## Risks

1. **Rules-step API drift.** That plan is under review, and its amendments are absorbed in the adapter (decision list above). Any further change should touch only `chat_router_ledger.py`. Task 1 Step 1 checks the shapes, and its round-trip test fails loudly on a mismatch.
2. **The ledger owns the value list.** If a template has no value entries, the router seeds the listed values as defaults before its first value write (`seed_values`). If the Rules step ever seeds differently (for example, from the first-use review), two sources could disagree. The seed only runs when the ledger has no value entry at all.
3. **Card fatigue, and unsure-band mistakes.** The wording rule cards any wording the radiologist did not type, so "make the alpha normal friendlier" always ends in a card. Under D-R2, an unsure-band kind is decided by its call and applied under the same checks, so a wrong decision lands in the template. It is visible (`llm_unsure`, a reply line, Undo), and the labs and the after-launch query count how often it happens.
4. **Jev on new questions.** The seven tag questions and the requires question are new wordings. Concept and fixed overlap ("no prior imaging" is both), and Jev is weak at overlapping choices. Both kinds then run, and a duplicated change resolves to one ledger key. The lab measures this before any wiring.
5. **Upper-case section names on Cerebras Qwen.** Views use Title Case and code matches case-insensitively. A model that still writes "FINDINGS" is matched. A garbled name ("FINDINGSINGS") fails the dry run and becomes a question.
6. **Latency.** A turn is one Jev call plus N parallel Qwen calls, plus requires calls for a style edit, plus the save function's unit checks (and a repair model on refusal). Expect two to four seconds against today's single rewrite. The lab reports the median.
7. **Undo of a deleted prose block** is skipped, because its text cannot be found again. The reply says part of it was left as it is.
8. **A layout change in the same turn as a dependent change** (for example, add a paragraph and then put a normal in it) fails the second change's validation, because it is dry-run on the pre-turn sheet. It becomes a question. The radiologist repeats it, and it then works.
9. **Synthetic sets may be cleaner than production,** and the real held-out set may be empty (the table is new). The reports say so, and Hassan spot-checks realism.
10. **The creator has no unit test** (as in Rules Task 25). It is covered by svelte-check and the manual run in Task 22.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-13-chat-edit-router.md`. There are two ways to execute it:

1. **Subagent-driven (recommended).** A fresh subagent per task, with a review between tasks. The controller-run tasks (13, 14, 15) and the manual run in Task 22 stay with the controller.
2. **Inline execution** with superpowers:executing-plans, in batches with a checkpoint at the end of each phase.

Phase 4 (wiring) starts only after Hassan has seen the Task 14 tagging report and the Task 15 targeted-call report. The labs are reported, not gated: Hassan sets the thresholds.
