# Template Rules Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settle a template's rules once, at creation: the radiologist answers short evidence-backed cards (required values, study-level wording, always-printed lines, the normal report), the answers are stored as a decision ledger, and code applies that ledger to the grammar sheet on every save.

**Architecture:** A pure-code ledger (`template_decisions.py` for the data and its operations, `template_ledger_apply.py` for the sheet edits) runs as the save function's last step (`template_sheet_save.vet_sheet(..., ledger=)`), on every origin: creation, chat, rebuild, restore and the upgrade script. A new decision run (`template_decision_run.py`) runs before the writer: one Qwen structured call proposes candidate values and concept wording, with quotes that code verifies against the examples, and Jev decides per example whether each study-level concept is stated. A card builder (`template_rules_cards.py`) turns the run into ranked one-tap cards, and the Svelte Rules step replaces the Questions step. The writer gets the confirmed decisions as authoritative context. Sheet checks after the build (`template_sheet_review.py`: a Jev FIXED-line check, the code-built normal report, and uncovered structures) feed the Style-step cards. Every model step is fail-soft: nothing blocks template creation.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pydantic-ai (`_run_agent_with_model`), Jev System One (`jev_client.jev_post`), pytest (asyncio auto); SvelteKit with Svelte 5 (runes in the new components), vitest (browser project for `*.svelte.test.ts`, node project for `*.test.ts`), svelte-check.

**Spec:** `docs/superpowers/specs/2026-10-13-template-rules-step-design.md` (all of it). Roadmap item 3 in `docs/superpowers/specs/2026-10-13-template-rules-next-design.md` (it absorbs §4's creation-time FIXED check and the §5 writer items). The next item, `docs/superpowers/specs/2026-10-13-chat-edit-router-design.md`, reuses this plan's ledger API and cards: see "Ledger API for the chat-edit router" at the end.

---

## Where and how

- Worktree: `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/rules-step`, branch `feat/rules-step` (from `feat/context-rules` at 6026fd7b). Never push, never `git stash`, never touch another worktree.
- Backend commands run from `backend/`: `.venv/bin/python -m pytest <path> -q`. Full suite: `.venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py` (baseline 3878 passed).
- Frontend commands run from `frontend/`: one file `npx vitest run <path>`; full suite `npx vitest run` (baseline 716/717; the known failure is the `page.svelte.spec` h1 test); `npm run check` (svelte-check baseline: 1194 problems; the count must not rise).
- Commit after every task with these trailer lines:

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit
```

- Synthetic lab data lives only in `~/Code/rr-template-conversion-private/synthetic/rules_step/`, never in the repo. Production seeds: `~/Code/rr-template-conversion-private/data_all.json` (31 templates; `templates[i].reports`, 11 templates have 3 or more) and the curated sheets `~/Code/rr-template-conversion-private/final/<slug>.final.md`.

## Facts this plan relies on (checked in the code at 6026fd7b)

- `template_writer.write_sheet` (`backend/src/rapid_reports_ai/template_writer.py:14-28`) makes one `model_call` with `P.ANALYSER_SYSTEM_PROMPT` and `P.analyser_user_prompt(...)`, then `vet_sheet(..., origin="analyser")`. It returns `summary` and `questions`.
- The only live writer prompt is `template_sheet_lab_prompts.ANALYSER_SYSTEM_PROMPT` (`template_sheet_lab_prompts.py:148-179`), used by `write_sheet` and by the lab script `scripts/template_sheet_lab.py:162`. The legacy copy, `TemplateManager.analyze_examples_to_skill_sheet` (`template_manager.py:3299`), is called only by `scripts/template_e2e_lab.py:327` and never in production, so it is left alone (standing rule: legacy code stays, never runs). The conversion prompt `TEMPLATE_SHEET_CONVERT_PROMPT` (`template_sheet_lab_prompts.py:331`) is the upgrade writer. It runs without decisions, so its context-rule guidance (lines 348-349) stays, and the ledger covers it at save. **The "edit both" check: there is one writer prompt to change.**
- The save function is `template_sheet_save.vet_sheet(sheet, origin, previous="")` (`template_sheet_save.py:148-208`), with origins `analyser | repair | rebuild | chat | restore` (`:32`) and `AUTOMATIC = {"analyser","repair","rebuild"}` (`:33`). Its callers: `main._vet_config` (`main.py:1673-1697`; used by create `:1736`, update `:1775` with origin "chat", restore `:2331`, `/skill-sheet/save` `:2809`), the refine endpoint (`main.py:2730`), `write_sheet`, and `scripts/template_upgrade_apply.py:67,97`.
- `_vet_config` skips the save function when the sheet is unchanged (`main.py:1692`): a ledger-only change must not be skipped.
- The grammar parser keeps each unit's own sheet line: `Normal.source_line`, `Negative.source_lines[0]`, `Rule.source_lines[0]` (`template_sheet_grammar.py:712-752`). `FixedBlock` keeps none (`template_sheet_grammar.py:731`, `template_sheet_structure.py:154-162`); Task 1 adds it. Renderers: `render_rule`, `render_negative`, `render_condition` (`template_sheet_grammar.py:779-804`).
- Item 1 (`template_context_rules.py`) resolves context `REPLACE`/`SUPPRESS`/`USE` rules at Generate. It matches a rule's target to a unit line by `norm_key` (`:59-110`). A `REPLACE` of a FIXED line is safe on the scratchpad path (`_left_on_stack`, `:113-121`).
- Jev: `jev_client.jev_post(body, api_key, timeout, transport)`; `noul` answers; the pattern for several questions in one call is `hybrid_stack/jev_stack.py:106-131`. Qwen with structured output and a gpt-oss fallback: `hybrid_stack/items.py:136-158` (`MODEL_CONFIG["STACK_REVIEW_FALLBACK"]`).
- Stored examples: the `TemplateExample` rows (`database/models.py:931-939`), written by `template_examples.store_examples` (`template_examples.py:80`). Nothing reads them yet; Task 15 adds the reader.
- Frontend: `SkillSheetCreator.svelte` has stages `summary | questions | test | refine` (`:115-116`, `:176-183`). `analyzeExamples` posts `/skill-sheet/analyze` (`:345-381`), `sendAnswer` posts `/skill-sheet/refine` (`:421-490`), and `saveAsTemplate` posts `/skill-sheet/save` (`:576-599`). `TemplateRefinePanel.svelte` posts `/skill-sheet/refine` (`:57-85`) and PUTs `/api/templates/{id}` with `{...template.template_config, skill_sheet}` (`:94-136`). The "Every report will include" chips (requirements spec, step 3) were never built: the Required-values card replaces them.
- The analyser-prompt case-agnostic test (`tests/test_template_sheet_lab_prompts.py:3-14`) forbids clinical words, including "contrast", in `ANALYSER_SYSTEM_PROMPT`. The decided-variant system prompt must pass the same test.

## Decisions (Hassan's D1-D3 of 2026-10-13, review fixes, and choices this plan makes where the spec is open)

1. **Concepts and their conditions (D1, D2).** `template_decisions.CONCEPTS` gives each concept two states, each with a fixed standard condition or none. Comparison: "the dictation names a previous imaging study for comparison" (exactly the text item 1 resolves). Contrast has a condition for both states: "the dictation states a contrast agent was given" and "the dictation states no contrast agent was given". Sequences: "the dictation states that part of the planned acquisition was not performed". Limitation: "the dictation states a technical limitation of the study". A concept choice stores `condition`, which is always the opposite of the default's state. A used concept is written as: `FIXED default` + `RULE WHEN [context: condition] REPLACE default WITH when_met`; or, with no alternative wording, `FIXED default` + `… SUPPRESS default`, so item 1 drops the line when the dictation contradicts it (D2); or a lone `USE when_met`. Every concept is therefore found by its condition, and `observe` reads its true state.
2. **Which wording is the default (D1).** Qwen labels each wording only with the state it states, never which one is usual. Code decides. For comparison, sequences and limitation, the default is the base state (no prior, everything performed, no limitation). For contrast, it is the state the examples use most, so a non-contrast protocol gets "no agent given" as its default and the other wording only when dictated. No concept card is ever pre-ticked or folded into "kept".
3. **Where a written-from-scratch line goes.** LIST_MISSING goes under `## Report-wide` (created before the first paragraph if missing) with `| section: <first findings SECTION>`, `AT TOP`. A concept goes at the end of the first paragraph of the first non-optional section with one of the concept's roles (comparison: comparison → technique → history; the others: technique), else of the first findings section. A rewritten line keeps its own `| section:` suffix, line by line (review fix 6).
4. **The ledger owns the value list.** Once the ledger has any `value` entry, the LIST_MISSING items are exactly the "every" entries. An automatic write's extra items are dropped and counted as drift. A chat rewrite's added items become entries (source "chat"). With no value entries, LIST_MISSING is left as written.
5. **NEGATIVE lines** are keyed `<paragraph> :: "<text>"` and match the key's text or the entry's current text. When neither is found, the entry is a card at the next review; a NEGATIVE is never inserted (review fix 1). Only a NORMAL, keyed by its structure label, is ever inserted. A paragraph name used more than once is never guessed: the entry goes to `unmatched` (review fix 5).
6. **Chat edits (D3).** A chat edit to a decided item is applied, and the reply names it ("This changes something you confirmed: …"). An edit that removes the whole LIST_MISSING list, or all of a used concept's lines, never changes the ledger: the ledger is kept, the save writes the lines back, and the reply carries `card_for_change` cards. Restore applies the restored version's own `decisions` when it has them, else the current ones; restore, rebuild and the writer never override the ledger. A PUT that omits `decisions` or `rules_step` keeps the stored ones (review fix 3).
7. **A fixed entry on a concept's wording** is refused by `set_decision`, and skipped by `apply_ledger` for old ledgers, so the two never fight (review fix 7).
8. **"Use whichever is dictated"** is its own choice, `{"use": false, "dictated": true}`. It writes no line, and `describe_change` words it as "whichever is dictated" (review fix 12). A `Change` carries the old entry whole, and `undo_change` restores its source, by and at (review fix 11).
9. **`by`** is `"radiologist"` (a card or a chat turn) or `"code"` (a default). No user ids go into template config. Kept items left untouched on Continue are recorded with source "default", as on Skip.
10. **Card budget:** at most 8 open cards, ranked: disagreements, then uncertain values, then concept wording. The rest sit under a collapsed "More decisions (N)", and the lab reports the count against the ≤ 8 target. A report counts as stating a concept when Jev says so or when it holds a verified quote (review fix 9/10).
11. **The writer's questions go.** PART 2 returns the summary only, and the slot-conflict wording (§5) is fixed. The writer lab (Tasks 29-30) runs before the writer is wired (Task 31, review fix 8); the temperature stays 0.8 until Hassan reads it.
12. **Thresholds are lab-set constants:** `STATES_MIN`, `FIXED_MIN` and `DUP_MIN`, each 0.5. The labs report score distributions, and Hassan sets the values.
13. **First-use review of existing templates** runs once. `/decide` with a `template_id` stamps `rules_step` on the server as soon as the run returns, saved or not (review fix 4). Its value cards come from the stored sheet's LIST_MISSING line.
14. **The Style FIXED check** leaves out only lines the ledger owns. An undecided concept's default is checked like any other line, so a wrong polarity shows up. The code absence backstop skips a line that a context rule targets (§4a). Lines the ledger does not own that Jev says state a decided concept become "May be stated twice" cards; the writer lab counts them (review fix 2).
15. **After the decision-run lab (2026-10-13; `REPORT_decide.md` in the private folder; Hassan's decisions).** These amend items 2, 10 and 12, and Tasks 13-18:
    - **Contrast default only with a clear majority.** Code takes the usual contrast state from the examples only when at least 2 reports state it and more reports state it than the other state (`template_rules_cards.MAJORITY_MIN`). Otherwise there is no default. The card (`usual_card`) asks "Is contrast usually given for this scan?" and offers the two wordings as choices ("Usually given" / "Usually not given"). It is never pre-ticked. This replaces "the most-used state wins, ties go to the first state".
    - **The concept questions ask whether the report mentions the concept at all.** The sequences and limitation questions now ask whether the report says if all planned acquisition was performed, and whether it comments on image quality or a technical limitation. Before, they asked only about the not-performed and limited states (precision 0.23-0.31). `STATES_MIN` stays at 0.5.
    - **Decision-run prompt.** One sentence counts for one concept only, and the model quotes the shortest span. Code also rejects wording that is made of slots only (it would match anything), and a fallback quote that contains braces.
    - **Card budget.** A value seen in only one report goes under "More", never into the main cards, even when there is room.
    - **Reliability.** The lab saw the decision call fail in 8-12% of runs. Qwen timed out at 25 s, and the gpt-oss fallback then hit "Exceeded maximum output retries" (16 of 19 fallbacks). The cause: `max_tokens` 6000 is shared with gpt-oss's reasoning, so its tool-call JSON was cut off on the large sets, and each re-ask was cut off the same way. Qwen was already raised to 16384 by `normalise_model_settings`, but gpt-oss was not. The changes: `max_tokens` is now 16384 for both models, the Qwen timeout is 40 s, and the whole Qwen step, fallback included, is bounded by `RUN_TIMEOUT_S` (60 s). The fallback gets the time left, capped at 25 s.
16. **After the follow-up lab (2026-10-13).** The sequences Jev question is the lab's arm b, word for word (type noul, no criteria): "The REPORT lists the acquisitions performed (sequences, series, phases or views), or says the planned protocol was complete or incomplete." "More" holds at most `MAX_MORE` (5) entries. Values seen in one report form one collapsed group ("Seen in one report: …"). Other values past the cap form a second collapsed group ("More values: …"). Every card in a group stays choosable when it is expanded. Concept cards sit in "More" outside the cap. `template_rules_cards.flat` expands the groups.
17. **The study setup is first evidence (Hassan, 2026-10-13).** The study name, scan type and protocol often state contrast, the protocol or comparison outright. The setup fields that exist today:
    - In the creator: `scanType` and `protocolNotes` (`SkillSheetCreator.svelte:44-45`; `/analyze` already takes `protocol_notes`), and `templateName` (`:125`, set at save).
    - On a saved template: `Template.name`, `Template.description` and `template_config.scan_type`.

    How the setup is used:
    - `/decide` takes `template_name` and `protocol_notes`, each truncated to the `SETUP_*` caps and never refused. The frontend sends them in Phase 3. A saved template falls back to its own name and description.
    - `run_decisions(..., setup)` puts a STUDY SETUP block, labelled authoritative, into the Qwen prompt.
    - Jev answers the four concept questions over the setup, and the two contrast conditions as statements (`ask_setup`). Code checks Qwen's setup quote against the setup text.
    - Contrast: the setup's state wins over an example tie. A setup that disagrees with a clear example majority gets the "usual?" card, which shows both. A silent setup keeps the example-majority rule.
    - A concept the setup states is evidence shown as "From the study setup: '…'", never as a report number.
    - No setup, an empty one, or a failed Jev setup call leaves the run exactly as before.
18. **After the FIXED-question lab (2026-10-13; `fixed_lab/scored_wording.json` in the private folder).** The plain question separated poorly (AUC 0.67). `template_sheet_review` now asks a criteria noul (`q_fixed`: "Can this sentence differ between patients having this same scan?", with true/false criteria) after structural pre-filters in code: a line with a `{slot}` and a sign-off line (a tiny anchored backstop pattern; the grammar has no sign-off role) are never asked and never carded. The lab's arm scored AUC 0.96, precision 0.93 and recall 0.97 at `FIXED_MIN` 0.5, which stays. The absence-wording backstop stays.

## File map

Backend (`backend/src/rapid_reports_ai/`):

| File | Status | Responsibility |
|---|---|---|
| `template_sheet_structure.py` | modify `:154-162` | `FixedBlock.source_line` |
| `template_sheet_grammar.py` | modify `:731` | store the FIXED line itself |
| `template_decisions.py` | create | ledger data, the concept registry, keys, validation, `set_decision`, `remove_decision`, `ledger_from_changes`, `describe_change` |
| `template_ledger_apply.py` | create | `apply_ledger`, `observe`, `reconcile_chat` |
| `template_sheet_save.py` | modify `:62-68`, `:148` | `vet_sheet(..., ledger=)`, ledger fields on `VetOutcome` |
| `main.py` | modify | `_vet_config`, request models, `/skill-sheet/analyze`, `/refine`, `/save`, new `/apply-decisions`, `/decide`, `/sheet-checks` |
| `template_writer.py` | modify | `decisions` in, decided prompt, drift |
| `scripts/template_upgrade_apply.py` | modify `:59-90` | pass the stored ledger |
| `template_decision_run.py` | create | the Qwen decision call, Jev concept questions, quote check |
| `template_rules_cards.py` | create | the card shapes, `build_cards`, `current_value_cards`, `card_for_change` |
| `template_examples.py` | modify | `stored_texts` |
| `template_sheet_lab_prompts.py` | modify | decided-variant prompts, no questions, the slot wording |
| `template_sheet_review.py` | create | the FIXED check, concept duplicates, the normal report, uncovered structures |
| `scripts/rules_step_lab.py` | create | lab runner and scorer (decision run, writer arms, FIXED check) |

Tests (`backend/tests/`): `template_sheet_fixtures.py` (add `LEDGER_SHEET`), `test_template_decisions.py`, `test_template_ledger_apply.py`, `test_template_ledger_save.py`, `test_template_ledger_routes.py`, `test_template_decision_run.py`, `test_template_rules_cards.py`, `test_template_decide_route.py`, `test_template_sheet_review.py`, `test_rules_step_lab.py`; existing tests updated where noted.

Frontend (`frontend/src/`):

| File | Status | Responsibility |
|---|---|---|
| `lib/template-rules/types.ts` | create | the wire types |
| `lib/template-rules/api.ts` (+ `api.test.ts`) | create | `postDecide`, `postApplyDecisions`, `postSheetChecks` |
| `lib/template-rules/cards.ts` (+ `cards.test.ts`) | create | pure card logic: the evidence line, the change from an answer, changes on Continue/Skip |
| `lib/template-rules/RulesStep.svelte` (+ `.svelte.test.ts`) | create | the Rules-step cards |
| `lib/template-rules/StyleChecks.svelte` (+ `.svelte.test.ts`) | create | Always printed, Your normal report, uncovered structures, cards at review |
| `routes/components/SkillSheetCreator.svelte` | modify | Rules phase in place of Questions; decisions through analyze, refine, save; Style checks |
| `routes/components/TemplateRefinePanel.svelte` | modify | Required values and first-use review; decisions on refine and PUT; Style checks |

No new route, so there is no dev-route guard to add. The lab is a backend script, not a frontend page. If a lab viewer page is ever added, it ships with `$lib/guards/dev-route` from its first commit.

## Phases

| Phase | Tasks | Leaves working software | Ships independently? |
|---|---|---|---|
| 1. Ledger + `apply_ledger` in the save function | 1-12 | every save applies `decisions`; `/apply-decisions` endpoint; no UI yet | **Yes.** Dormant: no template has decisions until a card writes one |
| 2. Decision run + Jev concept questions (+ lab) | 13-21 | `/decide` returns cards; lab report in the private folder | **Yes** (backend only, nothing calls `/decide` yet). The lab runs here, **before wiring** |
| 3. Rules-step cards UI | 22-27 | the creator flow Rules → Style → Test → Refine; refine panel Required values + first-use review; a rejected refine turn restores the ledger with the sheet | Needs phases 1 and 2. Ships without phase 4 (the ledger already applies the decisions at save) |
| 4. Writer change | 28-31 | prompts (28), writer lab (29-30), then the writer wiring (31): decisions as ground truth, no questions, slot wording fixed | Needs phase 1. The questions removal must ship with or after phase 3 (the old creator reads `questions`) |
| 5. Style-step sheet checks | 32-36 | the FIXED check, normal report and uncovered cards on the Style step and in the refine panel | Backend (Tasks 32-34) needs Phase 1 only and **ships independently**. The UI wiring (Task 36) is written on top of Phase 3's edits. Its Jev lab (Task 33) runs **before** the cards reach the UI |

The labs are reported, not gated. Each lab task ends with a report and recommendations for Hassan. No pass/fail threshold blocks the next task, but the wiring tasks that follow a lab use the constants Hassan sets from it.

---

# Phase 1: the decision ledger, applied by the save function

Outcome: `template_config["decisions"]` exists, is validated, and is applied by code as the save function's last step on every origin. There is no UI yet, so the feature is dormant until a card writes an entry. **Ships independently.**

### Task 1: The grammar keeps a FIXED line's own sheet line

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_structure.py:154-162`
- Modify: `backend/src/rapid_reports_ai/template_sheet_grammar.py:731`
- Test: `backend/tests/test_template_sheet_grammar.py`

- [ ] **Step 1: Write the failing test** (append to `backend/tests/test_template_sheet_grammar.py`)

```python
def test_fixed_unit_keeps_its_sheet_line():
    from rapid_reports_ai import template_sheet_grammar as tsg
    sheet = ('## Report Structure\nSECTION FINDINGS | header: "Findings:" | role: findings\n'
             'SECTION IMPRESSION | header: "Impression:" | role: impression\n\n'
             '## Paragraph: Knee (FINDINGS)\nCOVERS ["menisci"]\n- FIXED "Standard views were obtained."\n')
    st = tsg.parse_sheet(sheet).structure
    assert st.usable
    assert st.fixed_blocks[0].source_line == '- FIXED "Standard views were obtained."'
    # the extractor's JSON schema never sees it
    from rapid_reports_ai import template_sheet_structure as tss
    assert "source_line" not in tss.StructureDraft.model_json_schema()["$defs"]["FixedBlock"]["properties"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_grammar.py::test_fixed_unit_keeps_its_sheet_line -q`
Expected: FAIL with `AttributeError: 'FixedBlock' object has no attribute 'source_line'`

- [ ] **Step 3: Implement**

In `template_sheet_structure.py`, `class FixedBlock`, add the field after `text: str`:

```python
    text: str
    source_line: SkipJsonSchema[str] = ""  # grammar: the sheet line itself (the decision ledger edits it)
```

In `template_sheet_grammar.py:731` replace

```python
        return "fixed", {"section": section, "text": m.group(1)}
```

with

```python
        return "fixed", {"section": section, "text": m.group(1), "source_line": raw}
```

- [ ] **Step 4: Run the grammar and structure tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_grammar.py tests/test_template_sheet_structure.py tests/test_template_context_rules.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_structure.py backend/src/rapid_reports_ai/template_sheet_grammar.py backend/tests/test_template_sheet_grammar.py
git commit -m "feat(template): the grammar keeps a FIXED line's own sheet line

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 2: Ledger data, concepts, keys and validation

**Files:**
- Create: `backend/src/rapid_reports_ai/template_decisions.py`
- Test: `backend/tests/test_template_decisions.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The decision ledger's data and validation (Rules-step spec, "Decision ledger")."""
import pytest

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_grammar as tsg


def test_concepts_are_the_four_standard_ones_with_parseable_conditions():
    assert list(td.CONCEPTS) == ["comparison", "contrast", "sequences", "limitation"]
    assert td.CONCEPTS["comparison"].conditions == ("the dictation names a previous imaging study for comparison",)
    # contrast has a condition for both states: its default is whatever is usual in the template's examples
    assert td.CONCEPTS["contrast"].conditions == ("the dictation states a contrast agent was given",
                                                  "the dictation states no contrast agent was given")
    for c in td.CONCEPTS.values():
        for cond in c.conditions:
            assert len(tsg._content_words(cond)) >= 2, c.name   # the grammar's subject rule
            assert td.concept_of_condition(cond.upper()) == c.name


def test_normal_and_negative_keys_round_trip():
    assert td.split_normal_key(td.normal_key("Liver", "liver")) == ("Liver", "liver", False)
    assert td.split_normal_key(td.negative_key("Liver", "No focal lesion.")) == ("Liver", "No focal lesion.", True)
    with pytest.raises(td.DecisionError):
        td.split_normal_key("no separator")


def test_match_key_ignores_case_spacing_and_final_full_stop():
    assert td.match_key("value", " LVEF ") == td.match_key("value", "lvef")
    assert td.match_key("fixed", "Axial images.") == td.match_key("fixed", "axial  images")
    assert td.match_key("normal", "Liver :: Liver") == td.match_key("normal", "liver ::  liver")
    assert td.match_key("normal", 'Liver :: "No lesion."') == td.match_key("normal", 'liver :: "no lesion"')


@pytest.mark.parametrize("kind,key,choice", [
    ("value", "LVEF", {"need": "sometimes"}),
    ("value", 'a "quoted" name', {"need": "every"}),
    ("value", "one two three four five six seven eight nine", {"need": "every"}),
    ("concept", "laterality", {"use": True, "default": "x", "when_met": ""}),
    ("concept", "comparison", {"use": "yes", "default": "x", "when_met": ""}),
    ("concept", "comparison", {"use": True, "default": "", "when_met": ""}),
    ("concept", "comparison", {"use": True, "default": "Same.", "when_met": "same"}),
    ("concept", "contrast", {"use": True, "default": "With an agent.", "when_met": ""}),           # which condition?
    ("concept", "comparison", {"use": True, "default": "x", "when_met": "", "condition": "some other text"}),
    ("fixed", "Line.", {"keep": "maybe"}),
    ("normal", "Liver :: liver", {"text": "The liver measures {size}."}),
    ("normal", "Liver :: liver", {"text": 'Has a "quote".'}),
    ("other", "k", {}),
])
def test_invalid_changes_are_refused(kind, key, choice):
    with pytest.raises(td.DecisionError):
        td.validate(kind, key, choice)


def test_validate_canonicalises():
    assert td.validate("value", "  LV  EF ", {"need": "every", "extra": 1}) == ("LV EF", {"need": "every"})
    assert td.validate("concept", "comparison", {"use": False, "default": "x", "when_met": "y"}) == (
        "comparison", {"use": False, "default": "", "when_met": "", "condition": "", "dictated": False})
    assert td.validate("concept", "contrast", {"use": False, "dictated": True})[1]["dictated"] is True
    assert td.validate("concept", "comparison", {"use": True, "default": "None.", "when_met": ""}) == (
        "comparison", {"use": True, "default": "None.", "when_met": "",
                       "condition": "the dictation names a previous imaging study for comparison", "dictated": False})
    assert td.validate("concept", "contrast", {"use": True, "default": "No agent.", "when_met": "",
                                               "condition": "The dictation states a contrast agent was given"}
                       )[1]["condition"] == "the dictation states a contrast agent was given"
    assert td.validate("normal", "Liver :: liver", {"text": " The liver  is normal. "}) == (
        "Liver :: liver", {"text": "The liver is normal."})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.template_decisions'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/template_decisions.py`)

```python
"""The decision ledger (Rules-step spec 2026-10-13-template-rules-step-design): what the radiologist settled about a
template's rules, stored as template_config["decisions"] and applied by code on every save
(template_ledger_apply.apply_ledger, called by template_sheet_save.vet_sheet).

One entry per (kind, key): {"kind", "key", "choice", "by", "at", "source"}.

    kind     key                                             choice
    value    the value's short name                          {"need": "every" | "relevant" | "not_needed"}
    concept  comparison | contrast | sequences | limitation  {"use": bool, "default": str, "when_met": str,
                                                              "condition": str, "dictated": bool}
    fixed    the FIXED line's text                           {"keep": "always" | "dictated" | "remove"}
    normal   normal_key(paragraph, structure) for a NORMAL,  {"text": str}  ("" = removed / left unmentioned)
             negative_key(paragraph, text) for a NEGATIVE

A used concept is written as: FIXED default + RULE WHEN [context: condition] REPLACE default WITH when_met; FIXED
default + SUPPRESS default (no alternative wording: the line is dropped when the dictation contradicts it); or USE
when_met (no default). `condition` is one of the concept's standard conditions, the opposite of the default's state.
"Use whichever is dictated" is {"use": false, "dictated": true}: no line, recorded as its own choice.

source: creation | chat | first_use_review | default (a skipped step's pre-ticked choice; never "confirmed").
by: "radiologist" (a card or a chat turn) or "code" (a default).

This module is the API the Rules-step cards and the chat-edit router both call: set_decision validates and records
one change and returns it (with the old entry whole); undo_change reverses it; ledger_from_changes records a batch of card answers;
describe_change words a change for the radiologist. Keys are matched by match_key (case and spacing ignored; a final
full stop ignored for sentence keys), never by free-text similarity."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, TypedDict

from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

KINDS = ("value", "concept", "fixed", "normal")
SOURCES = ("creation", "chat", "first_use_review", "default")
BY = ("radiologist", "code")
NEEDS = ("every", "relevant", "not_needed")
KEEPS = ("always", "dictated", "remove")
MAX_VALUE_WORDS = 8
_SEP = " :: "


class DecisionError(ValueError):
    """A change code cannot apply as given (unknown kind or concept, malformed key or choice)."""


class Entry(TypedDict):
    kind: str
    key: str
    choice: dict
    by: str
    at: str
    source: str


class Change(TypedDict):
    kind: str
    key: str
    old: Optional[dict]   # the old entry whole (choice, by, at, source); None: a new entry
    new: dict             # the new choice
    source: str
    confirmed: bool       # the old entry was the radiologist's (any source but "default")


@dataclass(frozen=True)
class Concept:
    name: str
    label: str                          # how a card and a chat reply name it
    states: Dict[str, Optional[str]]    # state of a wording -> the standard condition under which it applies (None:
                                        # the usual state, written as the default)
    question: str                       # decision run: does an example report state this concept? (Jev noul)
    roles: Tuple[str, ...]              # home section roles, in preference order

    @property
    def conditions(self) -> Tuple[str, ...]:
        return tuple(c for c in self.states.values() if c)


# The standard study-level concepts. Their condition texts are fixed: apply_ledger finds a concept's lines by them,
# and Generate resolves them per case (template_context_rules). Contrast has a condition for both states, so its
# default is whichever wording is usual in the template's own examples (product decision D1, 2026-10-13); the other
# three have one condition and a base state. Case-agnostic wording only.
CONCEPTS: Dict[str, Concept] = {
    "comparison": Concept(
        "comparison", "Comparison with previous imaging",
        {"none": None, "compared": "the dictation names a previous imaging study for comparison"},
        "The REPORT says whether previous imaging was available or was compared with this study.",
        ("comparison", "technique", "history")),
    "contrast": Concept(
        "contrast", "Contrast",
        {"given": "the dictation states a contrast agent was given",
         "not_given": "the dictation states no contrast agent was given"},
        "The REPORT says whether a contrast agent was given for this study.", ("technique",)),
    "sequences": Concept(
        "sequences", "Parts of the study not performed",
        {"complete": None, "not_performed": "the dictation states that part of the planned acquisition was not performed"},
        "The REPORT says that part of the planned acquisition (a sequence, phase or view) was not performed.",
        ("technique",)),
    "limitation": Concept(
        "limitation", "Technical limitation",
        {"none": None, "limited": "the dictation states a technical limitation of the study"},
        "The REPORT states a technical limitation of the study (for example artefact or incomplete coverage).",
        ("technique",)),
}
STANDARD_CONDITIONS = {" ".join(c.lower().split()): name for name, k in CONCEPTS.items() for c in k.conditions}


def concept_of_condition(condition: str) -> Optional[str]:
    """The concept whose standard condition this is (case and spacing ignored), else None."""
    return STANDARD_CONDITIONS.get(" ".join((condition or "").lower().split()))


def _name(s: str) -> str:
    return " ".join((s or "").lower().split())


def normal_key(paragraph: str, structure: str) -> str:
    return f"{paragraph.strip()}{_SEP}{structure.strip()}"


def negative_key(paragraph: str, text: str) -> str:
    return f'{paragraph.strip()}{_SEP}"{text.strip()}"'


def split_normal_key(key: str) -> Tuple[str, str, bool]:
    """(paragraph, structure or negative text, is_negative)."""
    para, sep, label = (key or "").partition(_SEP)
    label = label.strip()
    if not sep or not para.strip() or not label:
        raise DecisionError(f"normal key {key!r}: '<paragraph> :: <structure>' or '<paragraph> :: \"<text>\"'")
    if len(label) > 2 and label.startswith('"') and label.endswith('"'):
        return para.strip(), label[1:-1].strip(), True
    return para.strip(), label, False


def match_key(kind: str, key: str) -> str:
    if kind == "normal":
        para, label, neg = split_normal_key(key)
        return f"{_name(para)}{_SEP}" + (f'"{norm_key(label)}"' if neg else _name(label))
    if kind == "fixed":
        return norm_key(key)
    return _name(key)


def _text(v, what: str, allow_slots: bool = True) -> str:
    if not isinstance(v, str):
        raise DecisionError(f"{what}: text expected")
    t = " ".join(v.split())
    if '"' in t or "“" in t or "”" in t:
        raise DecisionError(f"{what}: no double quotes")
    if not allow_slots and ("{" in t or "}" in t):
        raise DecisionError(f"{what}: no value to fill in")
    return t


def validate(kind: str, key: str, choice: dict) -> Tuple[str, dict]:
    """(key, choice) in canonical form; DecisionError when code cannot apply it."""
    if kind not in KINDS:
        raise DecisionError(f"unknown kind {kind!r}")
    if not isinstance(choice, dict):
        raise DecisionError("choice: object expected")
    key = " ".join((key or "").split())
    if kind == "value":
        if not key or len(key.split()) > MAX_VALUE_WORDS or any(c in key for c in '"|[]{}'):
            raise DecisionError(f"value name {key!r}: a short plain name")
        if choice.get("need") not in NEEDS:
            raise DecisionError(f"value need: one of {NEEDS}")
        return key, {"need": choice["need"]}
    if kind == "concept":
        if key not in CONCEPTS:
            raise DecisionError(f"unknown concept {key!r}")
        use = choice.get("use")
        if not isinstance(use, bool):
            raise DecisionError("concept use: true or false")
        if not use:
            return key, {"use": False, "default": "", "when_met": "", "condition": "",
                         "dictated": bool(choice.get("dictated"))}
        default = _text(choice.get("default", ""), "concept default")
        when_met = _text(choice.get("when_met", ""), "concept wording")
        if not (default or when_met):
            raise DecisionError("concept: a used concept needs wording")
        if default and when_met and norm_key(default) == norm_key(when_met):
            raise DecisionError("concept: the two wordings are the same")
        conds = CONCEPTS[key].conditions
        given = " ".join((choice.get("condition") or "").lower().split())
        if not given and len(conds) == 1:
            condition = conds[0]
        else:
            condition = next((c for c in conds if c == given), "")
            if not condition:
                raise DecisionError(f"concept {key}: condition must be one of {conds}")
        return key, {"use": True, "default": default, "when_met": when_met, "condition": condition, "dictated": False}
    if kind == "fixed":
        key = _text(key, "fixed line")
        if not key:
            raise DecisionError("fixed line: text expected")
        if choice.get("keep") not in KEEPS:
            raise DecisionError(f"fixed keep: one of {KEEPS}")
        return key, {"keep": choice["keep"]}
    split_normal_key(key)
    return key, {"text": _text(choice.get("text", ""), "normal wording", allow_slots=False)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py -q`
Expected: PASS (5 tests, 13 parametrised cases)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decisions.py backend/tests/test_template_decisions.py
git commit -m "feat(template): decision ledger data, standard concepts and validation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 3: Ledger operations: set, remove, record a batch, describe a change

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decisions.py` (append)
- Test: `backend/tests/test_template_decisions.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_set_decision_adds_then_changes_and_reports_the_change():
    led, ch = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation", at="t0")
    assert led == [{"kind": "value", "key": "LVEF", "choice": {"need": "every"}, "by": "radiologist", "at": "t0",
                    "source": "creation"}]
    assert ch == {"kind": "value", "key": "LVEF", "old": None, "new": {"need": "every"}, "source": "creation",
                  "confirmed": False}
    led2, ch2 = td.set_decision(led, "value", "lvef", {"need": "not_needed"}, source="chat", at="t1")
    assert len(led2) == 1 and led2[0]["key"] == "LVEF" and led2[0]["source"] == "chat"
    assert ch2["old"] == led[0] and ch2["confirmed"] is True             # the old entry whole
    assert led[0]["choice"] == {"need": "every"}          # never mutates the input


def test_same_choice_is_no_change_but_a_reconfirmation_updates_the_source():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="default", by="code")
    led2, ch = td.set_decision(led, "value", "LVEF", {"need": "every"}, source="creation")
    assert ch is None and led2[0]["source"] == "creation" and led2[0]["by"] == "radiologist"


def test_a_change_to_a_default_is_not_a_confirmed_change():
    led, _ = td.set_decision([], "fixed", "Line.", {"keep": "always"}, source="default", by="code")
    _, ch = td.set_decision(led, "fixed", "Line.", {"keep": "remove"}, source="chat")
    assert ch["confirmed"] is False and td.describe_change(ch) == ""


def test_remove_decision_undoes_an_entry():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="chat")
    assert td.remove_decision(led, "value", "lvef") == []


def test_unknown_source_or_by_is_refused():
    with pytest.raises(td.DecisionError):
        td.set_decision([], "value", "LVEF", {"need": "every"}, source="writer")
    with pytest.raises(td.DecisionError):
        td.set_decision([], "value", "LVEF", {"need": "every"}, source="chat", by="someone")


def test_ledger_from_changes_records_valid_changes_and_lists_invalid_ones():
    led, errors = td.ledger_from_changes([
        {"kind": "value", "key": "LVEF", "choice": {"need": "every"}},
        {"kind": "value", "key": "ECV", "choice": {"need": "relevant"}, "source": "default"},
        {"kind": "concept", "key": "nonsense", "choice": {"use": False}},
    ], source="creation")
    assert [(e["key"], e["source"], e["by"]) for e in led] == [("LVEF", "creation", "radiologist"),
                                                               ("ECV", "default", "code")]
    assert len(errors) == 1 and "nonsense" in errors[0]


def test_describe_change_words_a_confirmed_change():
    led, _ = td.set_decision([], "concept", "comparison",
                             {"use": True, "default": "No previous imaging.", "when_met": "Compared with {date}."},
                             source="creation")
    _, ch = td.set_decision(led, "concept", "comparison", {"use": False}, source="chat")
    assert td.describe_change(ch) == ('This changes something you confirmed: Comparison with previous imaging '
                                      '"No previous imaging." → not used.')
    _, ch = td.set_decision(led, "concept", "comparison", {"use": False, "dictated": True}, source="chat")
    assert td.describe_change(ch).endswith("→ whichever is dictated.")


def test_undo_change_restores_the_old_entry_whole():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation", at="t0")
    led2, ch = td.set_decision(led, "value", "LVEF", {"need": "not_needed"}, source="chat", at="t1")
    assert td.undo_change(led2, ch) == led                               # source, by and at come back too
    led3, ch_new = td.set_decision(led, "value", "ECV", {"need": "every"}, source="chat")
    assert td.undo_change(led3, ch_new) == led


def test_a_fixed_entry_on_a_concepts_wording_is_refused():
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging.",
                                                           "when_met": ""}, source="creation")
    with pytest.raises(td.DecisionError):
        td.set_decision(led, "fixed", "No previous imaging", {"keep": "remove"}, source="creation")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py -q`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.template_decisions' has no attribute 'set_decision'`

- [ ] **Step 3: Implement** (append to `template_decisions.py`)

```python
def find(ledger: List[Entry], kind: str, key: str) -> Optional[Entry]:
    k = match_key(kind, key)
    return next((e for e in ledger or [] if e.get("kind") == kind and match_key(kind, e["key"]) == k), None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_decision(ledger: List[Entry], kind: str, key: str, choice: dict, *, source: str,
                 by: str = "radiologist", at: Optional[str] = None) -> Tuple[List[Entry], Optional[Change]]:
    """The ledger with (kind, key) set to `choice`, and the change (None when the choice is unchanged; a
    re-confirmation still updates source, by and at). Never mutates `ledger`. DecisionError when invalid."""
    if source not in SOURCES:
        raise DecisionError(f"unknown source {source!r}")
    if by not in BY:
        raise DecisionError(f"unknown by {by!r}")
    key, choice = validate(kind, key, choice)
    if kind == "fixed" and norm_key(key) in concept_texts(ledger):
        raise DecisionError("this line belongs to a study-level wording; change it there")
    old = find(ledger, kind, key)
    entry: Entry = {"kind": kind, "key": old["key"] if old else key, "choice": choice, "by": by,
                    "at": at or _now(), "source": source}
    out = [entry if e is old else e for e in ledger] if old else [*(ledger or []), entry]
    if old and old["choice"] == choice:
        return out, None
    return out, Change(kind=kind, key=entry["key"], old=dict(old) if old else None, new=choice, source=source,
                       confirmed=bool(old) and old.get("source") != "default")


def concept_texts(ledger: List[Entry]) -> set:
    """norm_key of every wording a decided concept owns (its lines are the concept's, never a fixed entry's)."""
    return {norm_key(t) for e in ledger or [] if e.get("kind") == "concept"
            for t in ((e.get("choice") or {}).get("default", ""), (e.get("choice") or {}).get("when_met", "")) if t}


def remove_decision(ledger: List[Entry], kind: str, key: str) -> List[Entry]:
    """The ledger without (kind, key)."""
    old = find(ledger, kind, key)
    return [e for e in ledger if e is not old]


def undo_change(ledger: List[Entry], change: Change) -> List[Entry]:
    """Reverse one change (a rejected router change): the old entry back whole (choice, by, at, source), or the entry
    removed when the change added it."""
    if change["old"] is None:
        return remove_decision(ledger, change["kind"], change["key"])
    cur = find(ledger, change["kind"], change["key"])
    if cur is None:
        return [*ledger, dict(change["old"])]
    return [dict(change["old"]) if e is cur else e for e in ledger]


def ledger_from_changes(changes: List[dict], base: Optional[List[Entry]] = None,
                        source: str = "creation") -> Tuple[List[Entry], List[str]]:
    """Record card answers [{"kind", "key", "choice", "source"?}] on `base`. A change with source "default" is
    recorded as by "code". Returns (ledger, one message per change code could not apply; those are skipped)."""
    ledger: List[Entry] = list(base or [])
    errors: List[str] = []
    for c in changes or []:
        src = c.get("source") or source
        try:
            ledger, _ = set_decision(ledger, c.get("kind", ""), c.get("key", ""), c.get("choice") or {},
                                     source=src, by="code" if src == "default" else "radiologist")
        except DecisionError as e:
            errors.append(f"{c.get('kind')} {c.get('key')!r}: {e}")
    if errors:
        logger.warning("[ledger] %d change(s) not recorded: %s", len(errors), errors[:5])
    return ledger, errors


_NEED = {"every": "every report", "relevant": "only when relevant", "not_needed": "not needed"}
_KEEP = {"always": "always printed", "dictated": "only when dictated", "remove": "removed"}


def item_label(kind: str, key: str) -> str:
    if kind == "concept":
        return CONCEPTS[key].label if key in CONCEPTS else key
    if kind == "fixed":
        return f'"{key}"'
    if kind == "normal":
        para, label, neg = split_normal_key(key)
        return f'{para}: "{label}"' if neg else f"{para}: {label}"
    return key


def state_label(kind: str, choice: Optional[dict]) -> str:
    if choice is None:
        return "not set"
    if kind == "value":
        return _NEED.get(choice.get("need"), "not set")
    if kind == "fixed":
        return _KEEP.get(choice.get("keep"), "not set")
    if kind == "concept":
        if not choice.get("use"):
            return "whichever is dictated" if choice.get("dictated") else "not used"
        return f'"{choice.get("default") or choice.get("when_met")}"'
    return f'"{choice.get("text")}"' if choice.get("text") else "removed"


def describe_change(change: Change) -> str:
    """The reply line for a change to a confirmed item; "" for a new or default item."""
    if not change.get("confirmed"):
        return ""
    k = change["kind"]
    return (f"This changes something you confirmed: {item_label(k, change['key'])} "
            f"{state_label(k, change['old']['choice'])} → {state_label(k, change['new'])}.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decisions.py backend/tests/test_template_decisions.py
git commit -m "feat(template): ledger operations (set, remove, batch, describe a change)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 4: `apply_ledger` skeleton and the value list

**Files:**
- Create: `backend/src/rapid_reports_ai/template_ledger_apply.py`
- Modify: `backend/tests/template_sheet_fixtures.py` (append `LEDGER_SHEET`)
- Test: `backend/tests/test_template_ledger_apply.py`

- [ ] **Step 1: Add the fixture** (append to `backend/tests/template_sheet_fixtures.py`)

```python
# A lint-clean sheet with a technique section, a findings paragraph (COVERS two structures, one NORMAL, one
# NEGATIVE, one patient-variable FIXED line) and a free-prose Voice block quoting the NORMAL.
LEDGER_SHEET = """# Skill Sheet: Ledger test

## Voice
Prose about the voice. Quoted: "The liver is normal in size."

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Report-wide
TERM PREFER "hepatic"

## Paragraph: Technique (TECHNIQUE)
Opening: "Axial images were acquired."
FIXED "Axial images were acquired."

## Paragraph: Liver (FINDINGS)
COVERS ["liver" | "gallbladder"]
Opening: "The liver"
NORMAL [liver] "The liver is normal in size."
NEGATIVE "No focal liver lesion."
FIXED "No previous imaging available."

## Paragraph: Impression (IMPRESSION)
Opening: "Normal study."
"""
```

- [ ] **Step 2: Write the failing tests** (`backend/tests/test_template_ledger_apply.py`)

```python
"""apply_ledger: the ledger applied to a grammar sheet by code (Rules-step spec, "Decision ledger")."""
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import GOOD, LEDGER_SHEET


def _led(*changes):
    led = []
    for kind, key, choice in changes:
        led, _ = td.set_decision(led, kind, key, choice, source="creation", at="t")
    return led


def _clean(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def test_fixture_is_clean():
    _clean(LEDGER_SHEET)


def test_empty_ledger_or_non_grammar_sheet_is_unchanged():
    assert tla.apply_ledger(LEDGER_SHEET, []).sheet == LEDGER_SHEET
    led = _led(("value", "LVEF", {"need": "every"}))
    assert tla.apply_ledger("# Free\nprose", led).sheet == "# Free\nprose"


def test_every_values_are_inserted_under_report_wide():
    led = _led(("value", "LVEF", {"need": "every"}), ("value", "ECV", {"need": "relevant"}))
    res = tla.apply_ledger(LEDGER_SHEET, led)
    st = _clean(res.sheet)
    lm = [r for r in st.rules if r.effect == "list_missing"]
    assert [r.items for r in lm] == [["LVEF"]] and lm[0].section == "FINDINGS" and lm[0].position == "top"
    assert ('RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF"] AT TOP | section: FINDINGS'
            in res.sheet.split("## Report-wide")[1].split("## Paragraph")[0])
    assert res.applied == [{"kind": "value", "key": "*", "action": "inserted"}] and res.changed == 1


def test_a_sheet_without_report_wide_gets_the_block():
    res = tla.apply_ledger(GOOD, _led(("value", "Width", {"need": "every"})))
    assert "## Report-wide\nRULE WHEN" in res.sheet
    assert [r.items for r in _clean(res.sheet).rules if r.effect == "list_missing"] == [["Width"]]


def test_the_ledger_owns_the_list_existing_order_kept_extras_dropped():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["B" | "Extra" | "A"] '
        'AT END | section: FINDINGS\n')
    _clean(sheet)
    led = _led(("value", "a", {"need": "every"}), ("value", "b", {"need": "every"}), ("value", "C", {"need": "every"}),
               ("value", "Extra", {"need": "not_needed"}))
    res = tla.apply_ledger(sheet, led)
    lm = [r for r in _clean(res.sheet).rules if r.effect == "list_missing"]
    assert lm[0].items == ["b", "a", "C"] and lm[0].position == "end"   # sheet order, then new; ledger spelling
    assert res.applied[0]["action"] == "rewritten"


def test_no_every_value_removes_the_line():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["A"] AT TOP '
        '| section: FINDINGS\n')
    res = tla.apply_ledger(sheet, _led(("value", "A", {"need": "not_needed"})))
    assert "LIST_MISSING" not in res.sheet and res.applied[0]["action"] == "removed"


def test_apply_is_idempotent():
    led = _led(("value", "LVEF", {"need": "every"}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and again.changed == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.template_ledger_apply'`

- [ ] **Step 4: Write the module** (`backend/src/rapid_reports_ai/template_ledger_apply.py`)

```python
"""Apply the decision ledger to a grammar sheet (Rules-step spec, "Decision ledger"). Pure code, no model call.

apply_ledger(sheet, ledger) runs as the save function's last step on every origin. Each entry is located through the
parsed structure (the grammar stores each unit's own sheet line) and its stable key; unit lines are rewritten,
removed or inserted in canonical form (template_sheet_grammar renderers); the sheet is re-parsed after each entry,
and an entry whose edit would add a lint error is not applied (`failed`: a bug, logged). Prose is never rewritten;
`stale_quotes` lists a sentence an entry rewrote or removed that a free-prose block still quotes.

Where an entry's target cannot be found: values and concepts are written from scratch (code knows where); a fixed
line to keep, or a normal whose paragraph is gone, is returned in `unmatched` (a card at the next review), never
guessed.

observe() reads what a sheet currently says for a ledger item; reconcile_chat() folds a chat rewrite's changes to
ledger items back into the ledger (source "chat") before the ledger is applied."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Tuple

from . import template_decisions as td
from . import template_sheet_grammar as tsg
from . import template_sheet_structure as tss
from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

_SECTION_SUFFIX = re.compile(r'\s*\|\s*section:\s*[^"]*$')
_PREFIX = re.compile(r"^\s*(?:-\s+)?")


@dataclass
class LedgerResult:
    sheet: str
    applied: List[dict] = field(default_factory=list)    # {"kind", "key", "action": kept|rewritten|removed|inserted}
    unmatched: List[dict] = field(default_factory=list)  # entries shown as cards at the next review
    failed: List[dict] = field(default_factory=list)     # entries whose edit would break the sheet (a bug)
    stale_quotes: List[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return sum(a["action"] != "kept" for a in self.applied)


def _parse(sheet: str) -> tss.SheetStructure:
    return tsg.parse_sheet(sheet, mode="template").structure


def _err_keys(sheet: str) -> Set[tuple]:
    return {(e.text.strip(), e.reason) for e in tsg.parse_sheet(sheet, mode="template").errors}


def _prefix(line: str) -> str:
    return _PREFIX.match(line).group(0)


def _suffix(line: str) -> str:
    m = _SECTION_SUFFIX.search(line)
    return m.group(0) if m else ""


def _index(lines: List[str], raw: str, taken: Set[int] = frozenset()) -> Optional[int]:
    return next((i for i, ln in enumerate(lines) if i not in taken and ln == raw), None)


def _blocks(lines: List[str]) -> List[Tuple[str, int, int]]:
    """(title, heading index, end index exclusive) of every "## " block, in order."""
    heads = [(i, ln[3:].strip()) for i, ln in enumerate(lines) if ln.startswith("## ")]
    return [(t, i, heads[k + 1][0] if k + 1 < len(heads) else len(lines)) for k, (i, t) in enumerate(heads)]


def _paragraph_span(lines: List[str], pid: str) -> Optional[Tuple[int, int]]:
    """(heading index, end exclusive) of paragraph `pid` (the parser numbers paragraph headings p0, p1, …)."""
    n = 0
    for title, start, end in _blocks(lines):
        if tsg.paragraph_heading(title) is not None:
            if f"p{n}" == pid:
                return start, end
            n += 1
    return None


def _block_end(lines: List[str], start: int, end: int) -> int:
    """The index after a block's last non-blank line (an insert there keeps the blank line before the next block)."""
    k = end
    while k > start + 1 and not lines[k - 1].strip():
        k -= 1
    return k


def _free_prose_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    for title, start, end in _blocks(lines):
        if title.lower() in tsg.FREE_PROSE_SECTIONS:
            out += lines[start + 1:end]
    return out


# ── operations: (lines, structure, arg) -> (lines, applied rows, unmatched entries, old texts) ─────────────────

def _values(lines, st, entries):
    every = [e["key"] for e in entries if e["choice"]["need"] == "every"]
    rules = [r for r in st.rules if r.effect == "list_missing"]
    idx: List[int] = []
    for r in rules:
        i = _index(lines, r.source_lines[0], set(idx))
        if i is not None:
            idx.append(i)
    if idx:
        first = rules[0]
        spell = {td._name(k): k for k in every}
        ordered = [spell[td._name(x)] for x in first.items if td._name(x) in spell]
        ordered += [k for k in every if td._name(k) not in {td._name(x) for x in first.items}]
        out: List[Optional[str]] = list(lines)
        for i in idx[1:]:
            out[i] = None
        if not ordered:
            out[idx[0]] = None
            action = "removed"
        else:
            new = _prefix(lines[idx[0]]) + tsg.render_rule(first.model_copy(update={"items": ordered})) \
                + _suffix(lines[idx[0]])
            action = "kept" if new == lines[idx[0]] and len(idx) == 1 else "rewritten"
            out[idx[0]] = new
        return [x for x in out if x is not None], [{"kind": "value", "key": "*", "action": action}], [], []
    if not every:
        return lines, [{"kind": "value", "key": "*", "action": "kept"}], [], []
    findings = next((s.name for s in sorted(st.sections, key=lambda s: s.order) if s.role == "findings"), None)
    if findings is None:
        return lines, [], list(entries), []
    rule = tss.Rule(id="ledger", section=findings, condition="any listed value is not stated",
                    condition_source="findings", effect="list_missing", items=every, position="top", source_lines=[])
    line = f"{tsg.render_rule(rule)} | section: {findings}"
    out2 = list(lines)
    wide = next(((s, e) for t, s, e in _blocks(lines) if t.lower() == "report-wide"), None)
    if wide:
        at = _block_end(out2, *wide)
        out2[at:at] = [line]
    else:
        first_para = next((s for t, s, e in _blocks(lines) if tsg.paragraph_heading(t) is not None), len(out2))
        out2[first_para:first_para] = ["## Report-wide", line, ""]
    return out2, [{"kind": "value", "key": "*", "action": "inserted"}], [], []


_OPS: List[Tuple[str, Callable]] = []   # (kind, op) for single-entry kinds; filled in by the tasks that add them


def apply_ledger(sheet: str, ledger: List[dict]) -> LedgerResult:
    """The sheet with every ledger entry applied (module doc). A non-grammar sheet or an empty ledger is unchanged."""
    res = LedgerResult(sheet=sheet)
    if not ledger or not tsg.is_grammar_sheet(sheet or ""):
        return res
    steps: List[Tuple[Callable, object, List[dict]]] = []
    values = [e for e in ledger if e.get("kind") == "value"]
    if values:
        steps.append((_values, values, values))
    owned = td.concept_texts(ledger)
    for kind, op in _OPS:
        for e in ledger:
            if e.get("kind") != kind:
                continue
            if kind == "fixed" and norm_key(e["key"]) in owned:   # a concept's line: the concept entry decides it
                res.applied.append({"kind": "fixed", "key": e["key"], "action": "kept"})
                continue
            steps.append((op, e, [e]))
    stale: List[str] = []
    for op, arg, entries in steps:
        before_errors = _err_keys(res.sheet)
        try:
            lines, applied, unmatched, olds = op(res.sheet.split("\n"), _parse(res.sheet), arg)
            new = "\n".join(lines)
            added = _err_keys(new) - before_errors
            if added:
                raise ValueError(f"lint: {sorted(added)[:3]}")
        except Exception as e:  # a bug, never a refused save: the sheet stays without this decision
            logger.error("[ledger] %s not applied: %s: %s", [x.get("key") for x in entries], type(e).__name__,
                         str(e)[:200])
            res.failed += entries
            continue
        res.sheet = new
        res.applied += applied
        res.unmatched += unmatched
        stale += olds
    prose = _free_prose_lines(res.sheet.split("\n"))
    res.stale_quotes = sorted({t for t in stale if t and any(f'"{t}"' in ln for ln in prose)})
    return res
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_ledger_apply.py backend/tests/template_sheet_fixtures.py
git commit -m "feat(template): apply_ledger with the required-value list

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 5: Concepts: FIXED default plus one standard context rule (REPLACE, SUPPRESS or USE; item 1 resolves it)

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py`
- Test: `backend/tests/test_template_ledger_apply.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
from rapid_reports_ai import template_context_rules as tcr

PRIOR = "the dictation names a previous imaging study for comparison"
GIVEN = "the dictation states a contrast agent was given"
NOT_GIVEN = "the dictation states no contrast agent was given"
COMPARISON = {"use": True, "default": "No previous imaging available.",
              "when_met": "Compared with the previous {modality} of {date}.", "condition": PRIOR, "dictated": False}


def test_comparison_reuses_the_writers_fixed_line_and_adds_the_standard_rule():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison", COMPARISON)))
    st = _clean(res.sheet)
    rule = next(r for r in st.rules if r.condition_source == "context")
    assert (rule.condition, rule.effect, rule.target, rule.then_text) == (
        PRIOR, "replace", "No previous imaging available.", "Compared with the previous {modality} of {date}.")
    assert rule.paragraph == "p1"                      # where the writer's FIXED line was
    assert [f.text for f in st.fixed_blocks].count("No previous imaging available.") == 1
    assert res.applied == [{"kind": "concept", "key": "comparison", "action": "rewritten"}]


def test_item_one_resolves_the_comparison_concept_both_ways():
    sheet = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison", COMPARISON))).sheet
    rules = tcr.rules_in_scope(sheet)
    met, _, per = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert 'FIXED "Compared with the previous {modality} of {date}."' in met and per[0]["outcome"] == "applied"
    not_met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
    assert 'FIXED "No previous imaging available."' in not_met and "RULE WHEN" not in not_met


def test_a_default_only_concept_gets_a_drop_rule_item_one_resolves():
    # D2: every concept is found by its condition; the default line is dropped when the dictation contradicts it
    led = _led(("concept", "comparison", {"use": True, "default": "No previous imaging available.", "when_met": ""}))
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    rule = next(r for r in _clean(sheet).rules if r.condition_source == "context")
    assert (rule.condition, rule.effect, rule.target) == (PRIOR, "suppress", "No previous imaging available.")
    rules = tcr.rules_in_scope(sheet)
    met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert "No previous imaging available." not in met and "RULE WHEN" not in met
    not_met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
    assert 'FIXED "No previous imaging available."' in not_met


def test_contrast_takes_the_condition_opposite_its_default_either_way():
    usual_given = {"use": True, "default": "Following a contrast agent.", "when_met": "No contrast agent was given.",
                   "condition": NOT_GIVEN}
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "contrast", usual_given)))
    tech = res.sheet.split("## Paragraph: Technique (TECHNIQUE)")[1].split("## Paragraph:")[0]
    assert ('FIXED "Following a contrast agent."\nRULE WHEN [context: the dictation states no contrast agent was given] '
            'REPLACE "Following a contrast agent." WITH "No contrast agent was given."') in tech
    assert res.applied[0]["action"] == "inserted"
    # a non-contrast protocol: the usual line is the no-agent wording; the other replaces it only when dictated
    usual_none = {"use": True, "default": "No contrast agent was given.", "when_met": "Following a contrast agent.",
                  "condition": GIVEN}
    sheet = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "contrast", usual_none))).sheet
    rules = tcr.rules_in_scope(sheet)
    assert [r.condition for r in rules] == [GIVEN]
    assert 'FIXED "No contrast agent was given."' in tcr.apply_rules(sheet, rules, {GIVEN: False})[0]
    assert 'FIXED "Following a contrast agent."' in tcr.apply_rules(sheet, rules, {GIVEN: True})[0]
    # switching the stored polarity rewrites the pair; nothing doubles
    back = tla.apply_ledger(sheet, _led(("concept", "contrast", usual_given)))
    assert len(tcr.rules_in_scope(back.sheet)) == 1 and back.applied[0]["action"] == "rewritten"


def test_a_when_met_only_concept_is_a_use_rule():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "limitation",
                                              {"use": True, "default": "", "when_met": "The study is limited by {cause}."})))
    rule = next(r for r in _clean(res.sheet).rules if r.condition_source == "context")
    assert rule.effect == "use" and rule.then_text == "The study is limited by {cause}."


def test_not_used_or_dictated_removes_the_concept_lines_and_a_writer_rule_on_its_target():
    sheet = LEDGER_SHEET.replace(
        'FIXED "No previous imaging available."\n',
        'FIXED "No previous imaging available."\n'
        'RULE WHEN [context: prior imaging is available for comparison] REPLACE "No previous imaging available." '
        'WITH "Compared with prior."\n')
    _clean(sheet)
    used = tla.apply_ledger(sheet, _led(("concept", "comparison", COMPARISON))).sheet
    assert "prior imaging is available" not in used               # the writer's own rule on the same line is gone
    assert len([r for r in _clean(used).rules if r.condition_source == "context"]) == 1
    for choice in ({"use": False}, {"use": False, "dictated": True}):
        gone = tla.apply_ledger(used, _led(("concept", "comparison", choice)))
        assert "No previous imaging available." not in gone.sheet and "RULE WHEN" not in gone.sheet
        assert gone.applied[0]["action"] == "removed"


def test_report_wide_lines_keep_their_own_section_suffix():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nFIXED "No previous imaging available." | section: TECHNIQUE\n'
        'RULE WHEN [context: the dictation names a previous imaging study for comparison] REPLACE "No previous '
        'imaging available." WITH "Compared with prior."\n').replace('FIXED "No previous imaging available."\n\n', '\n')
    _clean(sheet)
    res = tla.apply_ledger(sheet, _led(("concept", "comparison", {**COMPARISON, "when_met": "Compared with {date}."})))
    wide = res.sheet.split("## Report-wide")[1].split("## Paragraph")[0]
    assert 'FIXED "No previous imaging available." | section: TECHNIQUE\n' in wide
    assert 'WITH "Compared with {date}."\n' in wide                    # no section added to the rule line
    assert _clean(res.sheet) and tla.apply_ledger(res.sheet, _led(("concept", "comparison",
                                                                   {**COMPARISON, "when_met": "Compared with {date}."}))).changed == 0


def test_concepts_are_idempotent():
    led = _led(("concept", "comparison", COMPARISON),
               ("concept", "contrast", {"use": True, "default": "With a contrast agent.", "when_met": "",
                                        "condition": NOT_GIVEN}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and again.changed == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: FAIL (the concept tests: no `RULE WHEN [context:` in the result)

- [ ] **Step 3: Implement** (in `template_ledger_apply.py`, after `_values` and before `_OPS`)

```python
def _targeting(st: tss.SheetStructure, texts: Set[str]) -> List[tss.Rule]:
    """Context REPLACE / SUPPRESS rules whose target is one of `texts` (norm_key)."""
    return [r for r in st.rules if r.condition_source == "context" and r.effect in ("replace", "suppress")
            and norm_key(r.target) in texts]


def _concept_rules(st: tss.SheetStructure, name: str) -> List[tss.Rule]:
    """The context rules carrying one of the concept's standard conditions (how a concept is found)."""
    return [r for r in st.rules if r.condition_source == "context" and td.concept_of_condition(r.condition) == name]


def _concept_lines(choice: dict, fixed_suffix: str = "", rule_suffix: str = "") -> List[str]:
    """A used concept's lines: FIXED default + REPLACE, FIXED default + SUPPRESS (no alternative wording), or USE."""
    default, when_met, cond = choice.get("default", ""), choice.get("when_met", ""), choice["condition"]
    out = []
    if default:
        out.append(f'FIXED "{default}"{fixed_suffix}')
    effect = "replace" if default and when_met else ("suppress" if default else "use")
    rule = tss.Rule(id="ledger", section="", condition=cond, condition_source="context", effect=effect,
                    target=default, then_text=when_met, source_lines=[])
    out.append(tsg.render_rule(rule) + rule_suffix)
    return out


def _home(lines, st, c: td.Concept) -> Optional[int]:
    """Insert index for a concept written from scratch: the end of the first paragraph of the first non-optional
    section with one of the concept's roles, else of the first findings section."""
    ordered = sorted(st.sections, key=lambda s: s.order)
    for role in [*c.roles, "findings"]:
        for s in ordered:
            if s.role != role or s.optional:
                continue
            para = next((p for p in st.paragraphs if p.section == s.name), None)
            span = _paragraph_span(lines, para.id) if para else None
            if span:
                return _block_end(lines, *span)
    return None


def _concept(lines, st, entry):
    name, choice = entry["key"], entry["choice"]
    row = {"kind": "concept", "key": name, "action": "kept"}
    rules = _concept_rules(st, name)
    texts = {norm_key(r.target) for r in rules if r.target}
    if choice.get("default"):
        texts.add(norm_key(choice["default"]))
    drop: Set[int] = set()
    rule_line = fixed_line = None
    for r in [*rules, *(x for x in _targeting(st, texts) if x not in rules)]:
        i = _index(lines, r.source_lines[0], drop)
        if i is not None:
            drop.add(i)
            rule_line = rule_line or lines[i]
    for f in st.fixed_blocks:
        if norm_key(f.text) in texts:
            i = _index(lines, f.source_line, drop)
            if i is not None:
                drop.add(i)
                fixed_line = fixed_line or lines[i]
    olds = [t for r in rules for t in (r.target, r.then_text) if t]
    if drop:
        at = min(drop)
    elif choice["use"]:
        at = _home(lines, st, td.CONCEPTS[name])
        if at is None:
            return lines, [], [entry], []
    else:
        return lines, [row], [], []
    # each new line keeps the trailing "| section:" of the line it replaces (a Report-wide unit without one belongs
    # to the first findings section, so nothing is added)
    fixed_suffix = _suffix(fixed_line) if fixed_line else (_suffix(rule_line) if rule_line else "")
    rule_suffix = _suffix(rule_line) if rule_line else fixed_suffix
    new = _concept_lines(choice, fixed_suffix, rule_suffix) if choice["use"] else []
    old = [lines[i] for i in sorted(drop)]
    if [ln.strip() for ln in old] == [ln.strip() for ln in new]:
        return lines, [row], [], []
    out = [ln for i, ln in enumerate(lines) if i not in drop]
    if new:
        prefix = _prefix(old[0]) if old else ""
        out[at:at] = [prefix + ln for ln in new]
    action = "removed" if not new else ("rewritten" if drop else "inserted")
    keep = {norm_key(choice.get("default", "")), norm_key(choice.get("when_met", ""))}
    return out, [{**row, "action": action}], [], [t for t in olds if norm_key(t) not in keep]
```

and replace the `_OPS` line with

```python
_OPS: List[Tuple[str, Callable]] = [("concept", _concept)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_ledger_apply.py
git commit -m "feat(template): ledger concepts write the FIXED default and the standard context rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 6: Fixed lines, normals, stale quotes, unmatched entries (reworded negatives, repeated paragraph names) and the lint guard

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py`
- Test: `backend/tests/test_template_ledger_apply.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_fixed_remove_and_dictated_drop_the_line_and_rules_on_it():
    sheet = LEDGER_SHEET.replace(
        'FIXED "Axial images were acquired."\n',
        'FIXED "Axial images were acquired."\n'
        'RULE WHEN [context: the coronal series was not acquired] SUPPRESS "Axial images were acquired."\n')
    _clean(sheet)
    for keep in ("remove", "dictated"):
        res = tla.apply_ledger(sheet, _led(("fixed", "Axial images were acquired.", {"keep": keep})))
        st = _clean(res.sheet)
        assert "Axial images were acquired." not in [f.text for f in st.fixed_blocks]
        assert not [r for r in st.rules if r.condition_source == "context"]
        assert 'Opening: "Axial images were acquired."' in res.sheet       # prose is never rewritten


def test_fixed_always_on_a_missing_line_is_unmatched_not_guessed():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("fixed", "A line the sheet lacks.", {"keep": "always"})))
    assert res.sheet == LEDGER_SHEET and [e["key"] for e in res.unmatched] == ["A line the sheet lacks."]


def test_normal_rewrite_insert_and_remove():
    led = _led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."}),
               ("normal", td.normal_key("Liver", "gallbladder"), {"text": "The gallbladder is unremarkable."}),
               ("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": ""}))
    res = tla.apply_ledger(LEDGER_SHEET, led)
    st = _clean(res.sheet)
    assert {(n.structure, n.text) for n in st.normals} == {("liver", "The liver is unremarkable."),
                                                           ("gallbladder", "The gallbladder is unremarkable.")}
    assert not st.negatives
    assert [a["action"] for a in res.applied] == ["rewritten", "inserted", "removed"]
    assert res.stale_quotes == ["The liver is normal in size."]      # the Voice block still quotes the old normal


def test_a_reworded_negative_stays_matched():
    key = td.negative_key("Liver", "No focal liver lesion.")
    led = _led(("normal", key, {"text": "No focal hepatic lesion."}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and [n.text for n in _clean(once).negatives] == ["No focal hepatic lesion."]


def test_a_normal_in_a_missing_paragraph_is_unmatched():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("normal", "Spleen :: spleen", {"text": "The spleen is normal."})))
    assert res.sheet == LEDGER_SHEET and len(res.unmatched) == 1


def test_an_edit_that_would_break_the_sheet_is_not_applied(monkeypatch):
    def broken(lines, st, entry):
        return [*lines, "NORMAL broken"], [{"kind": "normal", "key": entry["key"], "action": "inserted"}], [], []
    monkeypatch.setattr(tla, "_OPS", [("normal", broken)])
    res = tla.apply_ledger(LEDGER_SHEET, _led(("normal", "Liver :: liver", {"text": "The liver is fine."})))
    assert res.sheet == LEDGER_SHEET and len(res.failed) == 1 and not res.applied


def test_everything_together_is_idempotent_and_clean():
    led = _led(("value", "LVEF", {"need": "every"}), ("concept", "comparison", COMPARISON),
               ("fixed", "Axial images were acquired.", {"keep": "remove"}),
               ("normal", td.normal_key("Liver", "gallbladder"), {"text": "The gallbladder is unremarkable."}))
    once = tla.apply_ledger(LEDGER_SHEET, led)
    _clean(once.sheet)
    assert not once.failed and not once.unmatched
    assert tla.apply_ledger(once.sheet, led).sheet == once.sheet


def test_a_negative_whose_wordings_are_both_gone_is_a_card_never_inserted():
    gone = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', "")
    reword = _led(("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": "No focal hepatic lesion."}))
    res = tla.apply_ledger(gone, reword)
    assert res.sheet == gone and [e["key"] for e in res.unmatched] == ['Liver :: "No focal liver lesion."']
    remove = _led(("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": ""}))
    res = tla.apply_ledger(gone, remove)                                   # already gone: nothing to do, nothing added
    assert res.sheet == gone and not res.unmatched and res.changed == 0


def test_a_paragraph_name_used_twice_is_never_guessed():
    twice = LEDGER_SHEET.replace("## Paragraph: Impression (IMPRESSION)", "## Paragraph: Liver (IMPRESSION)")
    _clean(twice)
    res = tla.apply_ledger(twice, _led(("normal", "Liver :: liver", {"text": "The liver is unremarkable."})))
    assert res.sheet == twice and len(res.unmatched) == 1
    assert tla.observe(_clean(twice), "normal", "Liver :: liver") is None


def test_a_fixed_entry_on_a_concepts_line_is_skipped_not_fought_over():
    led = _led(("concept", "comparison", COMPARISON))
    led.append({"kind": "fixed", "key": "No previous imaging available.", "choice": {"keep": "remove"}, "by": "code",
                "at": "", "source": "default"})                       # a stored ledger from before the refusal
    once = tla.apply_ledger(LEDGER_SHEET, led)
    again = tla.apply_ledger(once.sheet, led)
    assert 'FIXED "No previous imaging available."' in once.sheet and again.sheet == once.sheet and again.changed == 0


def test_removing_a_fixed_entry_also_removes_a_use_rule_writing_it():
    sheet = LEDGER_SHEET.replace(
        'FIXED "Axial images were acquired."\n',
        'FIXED "Axial images were acquired."\nRULE WHEN [context: the coronal series was not acquired] USE '
        '"Coronal images were not acquired."\n')
    _clean(sheet)
    res = tla.apply_ledger(sheet, _led(("fixed", "Coronal images were not acquired.", {"keep": "remove"})))
    assert "Coronal images were not acquired." not in res.sheet and res.applied[0]["action"] == "removed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: FAIL (fixed and normal entries are ignored: no `_OPS` for them)

- [ ] **Step 3: Implement** (in `template_ledger_apply.py`, after `_concept`)

```python
def _uses(st: tss.SheetStructure, key: str) -> List[tss.Rule]:
    """Context USE rules writing this sentence (a line printed when its condition is met)."""
    return [r for r in st.rules if r.condition_source == "context" and r.effect == "use" and norm_key(r.then_text) == key]


def _fixed(lines, st, entry):
    key = norm_key(entry["key"])
    found = [f for f in st.fixed_blocks if norm_key(f.text) == key]
    uses = _uses(st, key)
    row = {"kind": "fixed", "key": entry["key"], "action": "kept"}
    if entry["choice"]["keep"] == "always":
        return (lines, [row], [], []) if found or uses else (lines, [], [entry], [])
    if not found and not uses:
        return lines, [row], [], []
    drop: Set[int] = set()
    raws = [f.source_line for f in found] + [r.source_lines[0] for r in [*_targeting(st, {key}), *uses]]
    for raw in raws:
        i = _index(lines, raw, drop)
        if i is not None:
            drop.add(i)
    out = [ln for i, ln in enumerate(lines) if i not in drop]
    return out, [{**row, "action": "removed"}], [], [found[0].text if found else uses[0].then_text]


def _paragraph(st: tss.SheetStructure, name: str) -> Optional[tss.Paragraph]:
    """The one paragraph with this name; None when there is none or more than one (never guessed)."""
    hits = [p for p in st.paragraphs if td._name(p.name) == td._name(name)]
    return hits[0] if len(hits) == 1 else None


def _normal(lines, st, entry):
    para_name, label, neg = td.split_normal_key(entry["key"])
    text = entry["choice"]["text"]
    row = {"kind": "normal", "key": entry["key"], "action": "kept"}
    para = _paragraph(st, para_name)
    if para is None:
        return lines, [], [entry], []
    if neg:
        keys = {norm_key(label)} | ({norm_key(text)} if text else set())
        units = [n for n in st.negatives if n.paragraph == para.id and n.origin == "template" and not n.condition
                 and norm_key(n.text) in keys]
        raws = [n.source_lines[0] for n in units]
    else:
        units = [n for n in st.normals if n.paragraph == para.id and td._name(n.structure) == td._name(label)]
        raws = [n.source_line for n in units]
    if not units:
        if not text:
            return lines, [row], [], []
        if neg:   # a negative is keyed by its own wording: when neither wording is found, ask (never insert)
            return lines, [], [entry], []
        span = _paragraph_span(lines, para.id)
        if span is None:
            return lines, [], [entry], []
        at = _block_end(lines, *span)
        out = list(lines)
        out[at:at] = [f'NORMAL [{label}] "{text}"']
        return out, [{**row, "action": "inserted"}], [], []
    idx: List[int] = []
    for raw in raws:
        i = _index(lines, raw, set(idx))
        if i is not None:
            idx.append(i)
    if not idx:
        return lines, [], [entry], []
    if text and len(idx) == 1 and units[0].text == text:
        return lines, [row], [], []
    olds = [u.text for u in units]
    old_keys = {norm_key(t) for t in olds}
    out2: List[Optional[str]] = list(lines)
    for i in idx[1:]:
        out2[i] = None
    rules = _targeting(st, old_keys)
    if text:
        first = lines[idx[0]]
        body = f'NEGATIVE "{text}"' if neg else f'NORMAL [{units[0].structure}] "{text}"'
        out2[idx[0]] = _prefix(first) + body + _suffix(first)
        for r in rules:   # a context rule on the old wording follows it
            i = _index(lines, r.source_lines[0])
            if i is not None:
                out2[i] = _prefix(lines[i]) + tsg.render_rule(r.model_copy(update={"target": text})) + _suffix(lines[i])
        action = "rewritten"
    else:
        out2[idx[0]] = None
        for r in rules:
            i = _index(lines, r.source_lines[0])
            if i is not None:
                out2[i] = None
        action = "removed"
    stale = [t for t in olds if norm_key(t) != norm_key(text)]
    return [x for x in out2 if x is not None], [{**row, "action": action}], [], stale
```

and set

```python
_OPS: List[Tuple[str, Callable]] = [("concept", _concept), ("fixed", _fixed), ("normal", _normal)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: PASS (26 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_ledger_apply.py
git commit -m "feat(template): ledger fixed lines and normals; stale prose quotes; unmatched and lint guard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 7: `observe` and `reconcile_chat` (chat updates the ledger, except whole-item removals (D3); automatic writes never do)

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py` (append)
- Test: `backend/tests/test_template_ledger_apply.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_observe_reads_each_kind():
    led = _led(("value", "LVEF", {"need": "every"}), ("concept", "comparison", COMPARISON))
    st = _clean(tla.apply_ledger(LEDGER_SHEET, led).sheet)
    assert tla.observe(st, "value", "lvef") == {"need": "every"}
    assert tla.observe(st, "value", "ECV") == {"need": "not_needed"}
    assert tla.observe(st, "concept", "comparison") == COMPARISON
    assert tla.observe(st, "concept", "contrast") == {"use": False, "default": "", "when_met": "", "condition": "",
                                                      "dictated": False}
    drop = _clean(tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison",
                                                      {**COMPARISON, "when_met": ""}))).sheet)
    assert tla.observe(drop, "concept", "comparison") == {**COMPARISON, "when_met": ""}   # the drop rule is read too
    assert tla.observe(st, "fixed", "Axial images were acquired.") == {"keep": "always"}
    assert tla.observe(st, "normal", "Liver :: liver") == {"text": "The liver is normal in size."}
    assert tla.observe(st, "normal", "Liver :: gallbladder") == {"text": ""}
    assert tla.observe(st, "normal", "Spleen :: spleen") is None


def test_a_chat_rewrite_that_changes_a_decided_item_updates_the_ledger():
    led = _led(("value", "LVEF", {"need": "every"}))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace('LIST_MISSING ["LVEF"]', 'LIST_MISSING ["RVEF"]')
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert {(e["key"], e["choice"]["need"], e["source"]) for e in new} == {("LVEF", "not_needed", "chat"),
                                                                           ("RVEF", "every", "chat")}
    assert td.describe_change(changes[0]) == ("This changes something you confirmed: LVEF every report → "
                                              "not needed.")
    assert tla.apply_ledger(after, new).sheet == after                # the rewrite stands
    assert cards == []


def test_items_a_chat_rewrite_left_alone_keep_their_entry():
    led = _led(("value", "LVEF", {"need": "every"}), ("value", "ECV", {"need": "relevant"}))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace("Opening: \"The liver\"", "Opening: \"The liver is described first\"")
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert new == led and changes == []


def test_no_value_entries_means_the_ledger_does_not_own_the_list():
    led = _led(("fixed", "Axial images were acquired.", {"keep": "always"}))
    before = LEDGER_SHEET
    after = before.replace('TERM PREFER "hepatic"\n', 'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value '
                                                     'is not stated] LIST_MISSING ["A"] AT TOP | section: FINDINGS\n')
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert new == led and changes == []



def test_a_rewrite_that_drops_a_whole_decided_item_keeps_the_ledger_and_returns_a_card():
    led = _led(("value", "LVEF", {"need": "every"}), ("concept", "comparison", COMPARISON))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    lines = [ln for ln in before.split("\n") if "LIST_MISSING" not in ln and "previous" not in ln.lower()]
    after = "\n".join(lines)
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert new == led and changes == []                                # D3: never folded in silently
    assert [c["id"] for c in cards] == ["value:lvef", "concept:comparison"]
    back = _clean(tla.apply_ledger(after, new).sheet)                 # the save writes the decided lines again
    assert tla.observe(back, "value", "LVEF") == {"need": "every"}
    assert tla.observe(back, "concept", "comparison") == COMPARISON
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.template_ledger_apply' has no attribute 'observe'`

- [ ] **Step 3: Implement** (append to `template_ledger_apply.py`)

```python
# ── reading a sheet for a ledger item (chat reconciliation; the router's targeted calls) ───────────────────────

def observe(st: tss.SheetStructure, kind: str, key: str) -> Optional[dict]:
    """The choice the sheet currently expresses for (kind, key), in the ledger's choice form. A value: "every" when
    the LIST_MISSING line lists it, else "not_needed". A concept: read from the rule carrying one of its standard
    conditions (REPLACE: default + when_met; SUPPRESS: default only; USE: when_met only). A normal: the unit's text
    ("" when absent); None when its paragraph is gone or its name is not unique."""
    if kind == "value":
        items = [td._name(x) for r in st.rules if r.effect == "list_missing" for x in r.items]
        return {"need": "every" if td._name(key) in items else "not_needed"}
    if kind == "concept":
        rules = _concept_rules(st, key)
        if not rules:
            return {"use": False, "default": "", "when_met": "", "condition": "", "dictated": False}
        r = rules[0]
        cond = next(c for c in td.CONCEPTS[key].conditions if td._name(c) == td._name(r.condition))
        default = r.target if r.effect in ("replace", "suppress") else ""
        when_met = r.then_text if r.effect in ("replace", "use") else ""
        return {"use": True, "default": default, "when_met": when_met, "condition": cond, "dictated": False}
    if kind == "fixed":
        k = norm_key(key)
        present = any(norm_key(f.text) == k for f in st.fixed_blocks) or bool(_uses(st, k))
        return {"keep": "always" if present else "remove"}
    para_name, label, neg = td.split_normal_key(key)
    para = _paragraph(st, para_name)
    if para is None:
        return None
    if neg:
        u = next((n for n in st.negatives if n.paragraph == para.id and norm_key(n.text) == norm_key(label)), None)
    else:
        u = next((n for n in st.normals if n.paragraph == para.id and td._name(n.structure) == td._name(label)), None)
    return {"text": u.text if u else ""}


def _wholesale(e: dict, ob: dict, oa: dict, sb: tss.SheetStructure, sa: tss.SheetStructure) -> bool:
    """A rewrite that removed a whole decided item: the whole LIST_MISSING list, or every line of a used concept.
    Product decision D3: never folded into the ledger silently; the ledger is kept and a card asks."""
    if e["kind"] == "value":
        had = any(r.effect == "list_missing" and r.items for r in sb.rules)
        return had and not any(r.effect == "list_missing" for r in sa.rules) and e["choice"]["need"] == "every"
    if e["kind"] == "concept":
        return bool(ob.get("use")) and not oa.get("use") and bool(e["choice"].get("use"))
    return False


def reconcile_chat(before: str, after: str, ledger: List[dict]) -> Tuple[List[dict], List[td.Change], List[dict]]:
    """Fold a chat rewrite into the ledger: an entry whose item the rewrite changed (before != after) takes the new
    state (source "chat"; the reply names a confirmed one); values the rewrite added to LIST_MISSING become entries
    when the ledger owns the value list. A rewrite that removed a whole item (_wholesale) leaves the entry as it was
    and returns a one-tap card instead. Returns (ledger, changes, cards)."""
    from . import template_rules_cards as trc
    if not ledger or not tsg.is_grammar_sheet(before or "") or not tsg.is_grammar_sheet(after or ""):
        return list(ledger or []), [], []
    sb, sa = _parse(before), _parse(after)
    out, changes, cards = list(ledger), [], []
    for e in ledger:
        try:
            ob, oa = observe(sb, e["kind"], e["key"]), observe(sa, e["kind"], e["key"])
            if oa is None or ob == oa:
                continue
            if _wholesale(e, ob, oa, sb, sa):
                cards.append(trc.card_for_change(e["kind"], e["key"], e["choice"]))
                continue
            out, ch = td.set_decision(out, e["kind"], e["key"], oa, source="chat")
        except (td.DecisionError, KeyError, StopIteration):
            continue
        if ch:
            changes.append(ch)
    if any(e["kind"] == "value" for e in ledger):
        known = {td._name(e["key"]) for e in out if e["kind"] == "value"}
        before_items = {td._name(x) for r in sb.rules if r.effect == "list_missing" for x in r.items}
        for x in [x for r in sa.rules if r.effect == "list_missing" for x in r.items]:
            if td._name(x) in known or td._name(x) in before_items:
                continue
            try:
                out, ch = td.set_decision(out, "value", x, {"need": "every"}, source="chat")
            except td.DecisionError:
                continue
            known.add(td._name(x))
            if ch:
                changes.append(ch)
    return out, changes, cards
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_apply.py -q`
Expected: PASS (31 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_ledger_apply.py
git commit -m "feat(template): observe a ledger item; reconcile a chat rewrite into the ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 8: The save function applies the ledger last, on every origin

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_save.py` (`:28` imports, `:62-68` `VetOutcome`, `:148` `vet_sheet`)
- Modify (fake signatures only): `backend/tests/test_template_refine.py`, `backend/tests/test_template_writer.py`, `backend/tests/test_template_sheet_save_routes.py`
- Test: `backend/tests/test_template_ledger_save.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_template_ledger_save.py`)

```python
"""The save function applies the decision ledger last, by code, on every origin (Rules-step spec)."""
import pytest

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_save as S
from tests.template_sheet_fixtures import LEDGER_SHEET


@pytest.fixture(autouse=True)
def no_jev(monkeypatch):
    async def none(st, sheet=""):
        return []

    async def no_repair(sheet, errors):
        raise AssertionError("repair must not run")
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr(S, "_repair", no_repair)


def _led(*changes):
    led = []
    for kind, key, choice in changes:
        led, _ = td.set_decision(led, kind, key, choice, source="creation", at="t")
    return led


LVEF = _led(("value", "LVEF", {"need": "every"}))
APPLIED = tla.apply_ledger(LEDGER_SHEET, LVEF).sheet


async def test_without_a_ledger_the_save_is_as_today():
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser")
    assert out.status == "saved" and out.sheet == LEDGER_SHEET and out.ledger == [] and out.ledger_drift == 0


async def test_the_writer_cannot_override_the_ledger_and_drift_is_counted():
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=LVEF)
    assert out.sheet == APPLIED and out.ledger == LVEF and out.ledger_drift == 1
    assert out.coverage_sections == ["TECHNIQUE", "FINDINGS", "IMPRESSION"]


async def test_a_ledger_only_change_saves_the_unchanged_sheet():
    out = await S.vet_sheet(LEDGER_SHEET, origin="chat", previous=LEDGER_SHEET, ledger=LVEF)
    assert out.status == "saved" and out.sheet == APPLIED and out.coverage_sections


async def test_an_unchanged_sheet_that_already_satisfies_the_ledger_is_unchanged():
    out = await S.vet_sheet(APPLIED, origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "unchanged" and out.sheet == APPLIED


async def test_a_chat_edit_of_a_decided_item_updates_the_ledger_and_says_so():
    after = APPLIED.replace('LIST_MISSING ["LVEF"]', 'LIST_MISSING ["RVEF"]')
    out = await S.vet_sheet(after, origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "saved" and out.sheet == after
    assert {(e["key"], e["choice"]["need"], e["source"]) for e in out.ledger} == {
        ("LVEF", "not_needed", "chat"), ("RVEF", "every", "chat")}
    assert td.describe_change(out.ledger_changes[0]).startswith("This changes something you confirmed: LVEF")


async def test_a_rebuild_never_overrides_the_ledger():
    after = APPLIED.replace('LIST_MISSING ["LVEF"]', 'LIST_MISSING ["RVEF"]')
    out = await S.vet_sheet(after, origin="rebuild", previous=APPLIED, ledger=LVEF)
    assert out.sheet == APPLIED and out.ledger == LVEF and out.ledger_drift == 1 and out.ledger_changes == []


async def test_a_refused_write_keeps_the_previous_sheet_and_the_ledger():
    out = await S.vet_sheet("# Free form\nprose", origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "refused" and out.sheet == APPLIED and out.ledger == LVEF


async def test_unmatched_entries_are_reported_for_the_next_review():
    led = _led(("fixed", "A line the sheet lacks.", {"keep": "always"}))
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=led)
    assert [e["key"] for e in out.ledger_unmatched] == ["A line the sheet lacks."]


async def test_a_chat_edit_that_drops_the_whole_value_list_is_kept_and_carded():
    after = "\n".join(ln for ln in APPLIED.split("\n") if "LIST_MISSING" not in ln)
    out = await S.vet_sheet(after, origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "saved" and out.sheet == APPLIED and out.ledger == LVEF and out.ledger_changes == []
    assert [c["id"] for c in out.ledger_cards] == ["value:lvef"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_save.py -q`
Expected: FAIL with `TypeError: vet_sheet() got an unexpected keyword argument 'ledger'`

- [ ] **Step 3: Implement** in `template_sheet_save.py`

Change the typing import (line 28) to

```python
from typing import List, Literal, Optional, Set, TypedDict
```

Add to `VetOutcome`, after `coverage_sections`:

```python
    ledger: List[dict] = field(default_factory=list)            # the decisions after this save (chat may change them)
    ledger_changes: List[dict] = field(default_factory=list)    # decided items a chat rewrite changed (td.Change)
    ledger_cards: List[dict] = field(default_factory=list)      # whole decided items a chat rewrite removed: kept, asked
    ledger_unmatched: List[dict] = field(default_factory=list)  # entries shown as cards at the next review
    ledger_drift: int = 0      # automatic writes: ledger lines the write had wrong and code rewrote (writer drift)
    stale_quotes: List[str] = field(default_factory=list)       # prose still quoting a sentence the ledger changed
```

Rename the existing `async def vet_sheet(sheet: str, origin: Origin, previous: str = "") -> VetOutcome:` to `async def _vet(sheet: str, origin: Origin, previous: str = "") -> VetOutcome:` (body and docstring unchanged), and append after it:

```python
async def vet_sheet(sheet: str, origin: Origin, previous: str = "", ledger: Optional[List[dict]] = None) -> VetOutcome:
    """Vet a sheet before it is stored (see _vet), then apply the decision ledger by code as the last step
    (template_ledger_apply.apply_ledger), on every origin. `ledger` is template_config["decisions"]; None leaves the
    save exactly as before the Rules step. Only a chat edit folds its own changes to decided items back into the
    ledger (reported in ledger_changes), except one that removes a whole decided item: that entry is kept and
    returned as a card (ledger_cards; product decision D3). Every other origin is overwritten by the ledger
    (counted in ledger_drift)."""
    out = await _vet(sheet, origin, previous)
    if ledger is None:
        return out
    return _with_ledger(out, origin, previous, list(ledger))


def _with_ledger(out: VetOutcome, origin: str, previous: str, ledger: List[dict]) -> VetOutcome:
    from . import template_ledger_apply as tla
    if out.status == "refused":
        return dataclasses.replace(out, ledger=ledger)
    changes: List[dict] = []
    cards: List[dict] = []
    if origin == "chat" and previous and out.status == "saved":
        ledger, changes, cards = tla.reconcile_chat(previous, out.sheet, ledger)
    res = tla.apply_ledger(out.sheet, ledger)
    drift = res.changed if origin in AUTOMATIC else 0
    if res.failed:
        logger.error("[sheet-save] %s: ledger entries not applied (a bug): %s", origin,
                     [e.get("key") for e in res.failed])
    logger.info("[ledger] origin=%s entries=%d changed=%d drift=%d unmatched=%d failed=%d chat_changes=%d stale=%d",
                origin, len(ledger), res.changed, drift, len(res.unmatched), len(res.failed), len(changes),
                len(res.stale_quotes))
    status, coverage = out.status, out.coverage_sections
    if res.sheet != out.sheet:
        status = "saved"
        st = tsg.parse_sheet(res.sheet, mode="template").structure
        coverage = [s.name for s in sorted(st.sections, key=lambda s: s.order)]
    return dataclasses.replace(out, status=status, sheet=res.sheet, coverage_sections=coverage, ledger=ledger,
                               ledger_changes=[dict(c) for c in changes], ledger_cards=cards,
                               ledger_unmatched=res.unmatched,
                               ledger_drift=drift, stale_quotes=res.stale_quotes)


LEDGER_KEPT = "This would remove something you confirmed, so it was kept; use the card below to change it."
```

- [ ] **Step 4: Give the existing fakes the new keyword**

Every caller now passes `ledger=` (Tasks 9-10), so the test fakes accept it:

```bash
cd backend && sed -i '' -E 's/async def (vet|spy|adjusted|refuse)\(sheet, origin, previous=""\):/async def \1(sheet, origin, previous="", ledger=None):/' tests/test_template_refine.py tests/test_template_writer.py tests/test_template_sheet_save_routes.py && grep -c 'ledger=None' tests/test_template_refine.py tests/test_template_writer.py tests/test_template_sheet_save_routes.py
```

Expected: `tests/test_template_refine.py:11`, `tests/test_template_writer.py:2`, `tests/test_template_sheet_save_routes.py:4`

- [ ] **Step 5: Run the save tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_save.py tests/test_template_sheet_save.py tests/test_template_sheet_save_routes.py tests/test_template_refine.py tests/test_template_writer.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_save.py backend/tests/test_template_ledger_save.py backend/tests/test_template_refine.py backend/tests/test_template_writer.py backend/tests/test_template_sheet_save_routes.py
git commit -m "feat(template): the save function applies the decision ledger last on every origin

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 9: Stored decisions reach the save function (create, update, restore, creator save)

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decisions.py` (append `clean_ledger`)
- Modify: `backend/src/rapid_reports_ai/main.py:1659-1667` (`_carry_structure`), `:1673-1697` (`_vet_config`), `:764-771` (`SkillSheetSaveRequest`), `:2809-2816` (`/skill-sheet/save`)
- Test: `backend/tests/test_template_decisions.py` (append), `backend/tests/test_template_ledger_routes.py` (create)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_decisions.py`:

```python
def test_clean_ledger_drops_what_code_cannot_apply():
    good, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation", at="t")
    dirty = [*good, {"kind": "value", "key": "X", "choice": {"need": "bogus"}}, "junk",
             {"kind": "fixed", "key": "Line.", "choice": {"keep": "remove"}, "source": "weird", "by": "x"}]
    out = td.clean_ledger(dirty)
    assert out[0] == good[0]
    assert out[1] == {"kind": "fixed", "key": "Line.", "choice": {"keep": "remove"}, "by": "code", "at": "",
                      "source": "default"}
    assert len(out) == 2
```

Create `backend/tests/test_template_ledger_routes.py`:

```python
"""Stored decisions reach the save function on every endpoint that writes a guided template's sheet."""
import pytest

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_save as S
from tests.template_sheet_fixtures import GOOD
from tests.test_template_sheet_save_routes import _get, _guided, _version_with

LINE = 'LIST_MISSING ["Width"]'


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def none(st, sheet=""):
        return []

    async def no_repair(sheet, errors):
        raise AssertionError("repair must not run")
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr(S, "_repair", no_repair)
    monkeypatch.setattr("rapid_reports_ai.template_sheet_structure.store_parsed", lambda tid, st: True)


def _width():
    led, _ = td.set_decision([], "value", "Width", {"need": "every"}, source="creation", at="t")
    return led


def _put(client, auth_headers, t, cfg):
    return client.put(f"/api/templates/{t['id']}", headers=auth_headers,
                      json={"name": t["name"], "template_config": cfg}).json()


def test_update_with_decisions_applies_them_even_when_the_sheet_is_unchanged(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = _put(client, auth_headers, t, {**t["template_config"], "decisions": _width()})
    assert r["success"], r
    cfg = _get(client, auth_headers, t["id"])["template_config"]
    assert LINE in cfg["skill_sheet"] and cfg["decisions"] == _width()


def test_update_without_decisions_keeps_the_stored_ones(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _width()})
    stored = _get(client, auth_headers, t["id"])
    cfg = {k: v for k, v in stored["template_config"].items() if k != "decisions"}
    edited = cfg["skill_sheet"].replace(LINE, 'LIST_MISSING ["Width" | "Depth"]')
    r = _put(client, auth_headers, stored, {**cfg, "skill_sheet": edited})
    assert r["success"], r
    after = _get(client, auth_headers, t["id"])["template_config"]
    # origin "chat": the edit added a value, which the ledger now records
    assert {e["key"] for e in after["decisions"]} == {"Width", "Depth"} and "Depth" in after["skill_sheet"]


def test_restore_applies_the_ledger(client, auth_headers, db_session):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _width()})
    vid = _version_with(db_session, t["id"], GOOD)    # the version holds the decisions but the old sheet
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r["success"], r
    assert LINE in _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"]


def test_creator_save_stores_decisions_and_the_rules_step_record(client, auth_headers, monkeypatch):
    async def store(db, template_id, texts):
        return 0
    monkeypatch.setattr("rapid_reports_ai.template_examples.store_examples", store)
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee", "decisions": _width(),
        "rules_step": {"version": "v", "cards": 3}}).json()
    assert r["success"], r
    cfg = _get(client, auth_headers, r["template_id"])["template_config"]
    assert LINE in cfg["skill_sheet"] and cfg["decisions"] == _width() and cfg["rules_step"] == {"version": "v", "cards": 3}


def test_a_put_without_decisions_keeps_the_ledger_and_the_rules_step_record(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _width(), "rules_step": {"version": "v"}})
    stored = _get(client, auth_headers, t["id"])
    cfg = {k: v for k, v in stored["template_config"].items() if k not in ("decisions", "rules_step")}
    r = _put(client, auth_headers, stored, cfg)                       # same sheet, no ledger fields
    assert r["success"], r
    after = _get(client, auth_headers, t["id"])["template_config"]
    assert after["decisions"] == _width() and after["rules_step"] == {"version": "v"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py tests/test_template_ledger_routes.py -q`
Expected: FAIL (`clean_ledger` missing; the routes ignore `decisions`)

- [ ] **Step 3: Implement**

Append to `template_decisions.py`:

```python
def clean_ledger(entries) -> List[Entry]:
    """Stored or client-sent entries, re-validated: an entry code cannot apply is dropped (logged), never guessed. An
    unknown source or by becomes "default" / "code" (never counted as the radiologist's confirmation)."""
    out: List[Entry] = []
    for e in entries or []:
        try:
            if not isinstance(e, dict):
                raise DecisionError("entry: object expected")
            key, choice = validate(e.get("kind", ""), e.get("key", ""), e.get("choice") or {})
        except DecisionError as err:
            logger.warning("[ledger] stored entry dropped: %s", err)
            continue
        out.append({"kind": e["kind"], "key": key, "choice": choice,
                    "by": e.get("by") if e.get("by") in BY else "code", "at": str(e.get("at") or ""),
                    "source": e.get("source") if e.get("source") in SOURCES else "default"})
    return out
```

In `main.py` add `from . import template_decisions as td` after `from . import template_chat_turns` (line 77), then replace the body of `_vet_config` from `sheet = new_cfg.get("skill_sheet") or ""` to its end with:

```python
    sheet = new_cfg.get("skill_sheet") or ""
    if not sheet:
        if creating or before:
            return None, tsave.LOST_STRUCTURE, ""
        return new_cfg, "", ""
    # the decision ledger: the incoming config's, else the stored one (a restore of a version without decisions,
    # a client that does not send them); applied by the save function even when only the ledger changed
    stored = td.clean_ledger(old.get("decisions"))
    ledger = td.clean_ledger(new_cfg["decisions"]) if isinstance(new_cfg.get("decisions"), list) else stored
    if sheet == before and ledger == stored:
        return new_cfg, "", ""
    out = await tsave.vet_sheet(sheet, origin=origin, previous=before, ledger=ledger or None)
    if out.status == "refused":
        return None, out.message, ""
    cfg = {**new_cfg, "decisions": out.ledger} if ledger else new_cfg
    if out.status == "unchanged":
        return cfg, "", ""
    notes = [td.describe_change(c) for c in out.ledger_changes] + ([tsave.LEDGER_KEPT] if out.ledger_cards else [])
    notice = " ".join(x for x in [out.message or "", *notes] if x)
    return {**cfg, "skill_sheet": out.sheet, "coverage_sections": out.coverage_sections}, "", notice
```

In `_carry_structure` (main.py:1659-1667) the ledger and its run record must survive a PUT that omits them (the refine panel and older clients send the whole config, but a client may not). Replace

```python
    if not new.get("analyser_version") and old.get("analyser_version"):
        new["analyser_version"] = old["analyser_version"]   # the writer of the base sheet survives edits
    return new
```

with

```python
    if not new.get("analyser_version") and old.get("analyser_version"):
        new["analyser_version"] = old["analyser_version"]   # the writer of the base sheet survives edits
    for k in ("decisions", "rules_step"):   # the decision ledger and its run record survive a PUT that omits them
        if k not in new and old.get(k):
            new[k] = old[k]
    return new
```

In `SkillSheetSaveRequest` (main.py:764-771) add:

```python
    decisions: List[Dict[str, Any]] = []   # the decision ledger from the Rules step (applied at save)
    rules_step: Dict[str, Any] = {}        # evidence: the decision run's record (cards, dropped quotes, habits)
```

In `skill_sheet_save_endpoint` replace

```python
        template_config, refusal, _ = await _vet_config({
            "generation_mode": "skill_sheet_guided",
            "skill_sheet": request.skill_sheet,
            "scan_type": request.scan_type,
        }, {}, "analyser", creating=True)
        if refusal:
            return {"success": False, "error": refusal}
```

with

```python
        new_config = {"generation_mode": "skill_sheet_guided", "skill_sheet": request.skill_sheet,
                      "scan_type": request.scan_type}
        if request.decisions:
            new_config["decisions"] = request.decisions
        template_config, refusal, _ = await _vet_config(new_config, {}, "analyser", creating=True)
        if refusal:
            return {"success": False, "error": refusal}
        if request.rules_step:
            template_config = {**template_config, "rules_step": request.rules_step}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decisions.py tests/test_template_ledger_routes.py tests/test_template_sheet_save_routes.py tests/test_template_examples.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decisions.py backend/src/rapid_reports_ai/main.py backend/tests/test_template_decisions.py backend/tests/test_template_ledger_routes.py
git commit -m "feat(template): stored decisions reach the save function on create, update, restore and creator save

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 10: The writer, `/skill-sheet/analyze` and `/skill-sheet/refine` carry the ledger

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_writer.py`
- Modify: `backend/src/rapid_reports_ai/main.py:729-732` (`SkillSheetAnalyzeRequest`), `:746-751` (`SkillSheetRefineRequest`), `:2615-2619` (analyze), `:2728-2747` (refine)
- Test: `backend/tests/test_template_writer.py` (append), `backend/tests/test_template_ledger_routes.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_writer.py`:

```python
async def test_write_passes_the_decisions_to_the_save_function(calls, monkeypatch):
    seen = {}

    async def vet(sheet, origin, previous="", ledger=None):
        seen["ledger"] = ledger
        return VetOutcome("saved", sheet, ledger=list(ledger or []), ledger_drift=2)
    monkeypatch.setattr(W, "vet_sheet", vet)
    led = [{"kind": "value", "key": "A", "choice": {"need": "every"}, "by": "radiologist", "at": "t",
            "source": "creation"}]
    out = await W.write_sheet([{"label": "", "content": "r1"}], "MRI knee", decisions=led)
    assert seen["ledger"] == led and out["decisions"] == led and out["ledger_drift"] == 2
    out2 = await W.write_sheet([{"label": "", "content": "r1"}], "MRI knee")
    assert seen["ledger"] is None and out2["decisions"] == []
```

Append to `backend/tests/test_template_ledger_routes.py`:

```python
def test_analyze_records_the_card_answers_and_passes_them_to_the_writer(client, auth_headers, monkeypatch):
    seen = {}
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def write(examples, scan_type, protocol_notes="", decisions=None):
        seen["decisions"] = decisions
        return {"skill_sheet": GOOD, "summary": {}, "questions": [], "dropped": [], "notice": "",
                "analyser_version": "v", "decisions": decisions or [], "ledger_drift": 0}

    async def test_case(self, examples, scan_type, api_key):
        return {"sample_clinical_history": "", "sample_findings": ""}
    monkeypatch.setattr("rapid_reports_ai.template_writer.write_sheet", write)
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.generate_test_case", test_case)
    r = client.post("/api/templates/skill-sheet/analyze", headers=auth_headers, json={
        "scan_type": "MRI knee", "examples": [{"content": "a"}, {"content": "b"}, {"content": "c"}],
        "changes": [{"kind": "value", "key": "Width", "choice": {"need": "every"}},
                    {"kind": "value", "key": "Depth", "choice": {"need": "every"}, "source": "default"}]}).json()
    assert r["success"], r
    assert [(e["key"], e["source"], e["by"]) for e in seen["decisions"]] == [
        ("Width", "creation", "radiologist"), ("Depth", "default", "code")]
    assert [e["key"] for e in r["decisions"]] == ["Width", "Depth"]


def test_refine_carries_the_ledger_and_names_a_changed_decision(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_ledger_apply as tla
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")
    led = _width()
    before = tla.apply_ledger(GOOD, led).sheet
    after = before.replace(LINE, 'LIST_MISSING ["Depth"]')

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": after, "response": "Done.", "behavioral_claim": "c"}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers, json={
        "skill_sheet": before, "message": "swap width for depth", "decisions": led}).json()
    assert r["success"] and r["applied"] is True and r["skill_sheet"] == after
    assert {(e["key"], e["choice"]["need"]) for e in r["decisions"]} == {("Width", "not_needed"), ("Depth", "every")}
    assert r["response"] == ("Done. This changes something you confirmed: Width every report → not needed.")


def test_refine_without_decisions_returns_none(client, auth_headers, monkeypatch):
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": GOOD, "response": "Nothing to change?", "behavioral_claim": ""}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers,
                    json={"skill_sheet": GOOD, "message": "m"}).json()
    assert r["success"] and "decisions" not in r



def test_refine_that_drops_a_whole_decided_list_keeps_it_and_returns_the_card(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_ledger_apply as tla
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")
    led = _width()
    before = tla.apply_ledger(GOOD, led).sheet
    after = "\n".join(ln for ln in before.split("\n") if "LIST_MISSING" not in ln)

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": after, "response": "Done.", "behavioral_claim": "c"}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers, json={
        "skill_sheet": before, "message": "remove the values", "decisions": led}).json()
    assert r["success"] and LINE in r["skill_sheet"] and r["decisions"] == led
    assert [c["id"] for c in r["cards"]] == ["value:width"] and r["response"].endswith(S.LEDGER_KEPT)
```

The analyze endpoint now always passes `decisions=`, so give the two existing `write` fakes in `test_template_writer.py` (lines 92 and 105) the keyword:

```bash
cd backend && sed -i '' 's/async def write(examples, scan_type, protocol_notes=""):/async def write(examples, scan_type, protocol_notes="", decisions=None):/' tests/test_template_writer.py && grep -c 'decisions=None):' tests/test_template_writer.py
```

Expected: `2`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_writer.py tests/test_template_ledger_routes.py -q`
Expected: FAIL (`write_sheet() got an unexpected keyword argument 'decisions'`; the analyze and refine requests ignore the new fields)

- [ ] **Step 3: Implement**

Replace `template_writer.py` from `from typing import Dict, List` to the end with:

```python
import logging
from typing import Dict, List, Optional

from . import template_sheet_lab_prompts as P
from .template_sheet_model import model_call
from .template_sheet_save import vet_sheet

logger = logging.getLogger(__name__)

ANALYSER_VERSION = "grammar-analyser-2026-10-13"


async def write_sheet(examples: List[Dict[str, str]], scan_type: str, protocol_notes: str = "",
                      decisions: Optional[List[dict]] = None) -> Dict:
    """{"skill_sheet", "summary", "questions", "dropped", "notice", "analyser_version", "decisions",
    "ledger_drift"} (notice: the save function's report of a reworded unit, "" when none). `decisions`: the Rules
    step's ledger, applied by the save function after the write (ledger_drift counts the lines it had to
    overwrite). Raises ValueError with the save function's message when it refuses the sheet."""
    raw = await model_call(P.ANALYSER_SYSTEM_PROMPT, P.analyser_user_prompt(examples, scan_type, protocol_notes),
                           P.ANALYSER_SETTINGS)
    ans = P.split_answer(raw)
    v = await vet_sheet(ans["skill_sheet"] or "", origin="analyser", ledger=decisions or None)
    if v.status != "saved":
        raise ValueError(v.message or "The template could not be written, try again")
    if decisions:
        logger.info("[writer] decisions=%d drift=%d unmatched=%d", len(decisions), v.ledger_drift,
                    len(v.ledger_unmatched))
    summary = ans.get("summary")
    questions = ans.get("questions")
    return {"skill_sheet": v.sheet, "summary": summary if isinstance(summary, dict) else {},
            "questions": questions if isinstance(questions, list) else [], "dropped": v.dropped,
            "notice": v.message, "analyser_version": ANALYSER_VERSION,
            "decisions": v.ledger if decisions else [], "ledger_drift": v.ledger_drift}
```

In `main.py`, `SkillSheetAnalyzeRequest` add:

```python
    changes: List[Dict[str, Any]] = []   # Rules-step card answers [{kind, key, choice, source?}]
```

`SkillSheetRefineRequest` add:

```python
    decisions: Optional[List[Dict[str, Any]]] = None   # the template's decision ledger (None: not tracked)
```

In `skill_sheet_analyze_endpoint` replace

```python
        analysis_task = template_writer.write_sheet(
            [{"label": e["label"] or "", "content": e["content"]} for e in examples],
            request.scan_type,
            protocol_notes,
        )
```

with

```python
        ledger, _ = td.ledger_from_changes(request.changes, source="creation")
        analysis_task = template_writer.write_sheet(
            [{"label": e["label"] or "", "content": e["content"]} for e in examples],
            request.scan_type,
            protocol_notes,
            decisions=ledger or None,
        )
```

In `skill_sheet_refine_endpoint` replace

```python
        v = await tsave.vet_sheet(result.get("skill_sheet", ""), origin="chat", previous=request.skill_sheet)
```

with

```python
        decisions = td.clean_ledger(request.decisions) if request.decisions is not None else None
        v = await tsave.vet_sheet(result.get("skill_sheet", ""), origin="chat", previous=request.skill_sheet,
                                  ledger=decisions)
```

and replace

```python
        else:
            out = {"success": True, **result, "skill_sheet": v.sheet, "applied": True}
            if v.message:  # ADJUSTED: saved, with a small repair
                out["notice"] = v.message
                out["response"] = f"{result.get('response', '').rstrip()} {v.message}".strip()
```

with

```python
        else:
            out = {"success": True, **result, "skill_sheet": v.sheet, "applied": True}
            if v.message:  # ADJUSTED: saved, with a small repair
                out["notice"] = v.message
                out["response"] = f"{result.get('response', '').rstrip()} {v.message}".strip()
            notes = [n for n in (td.describe_change(c) for c in v.ledger_changes) if n]
            if v.ledger_cards:   # D3: a whole decided item removed by the rewrite is kept and asked about
                notes.append(tsave.LEDGER_KEPT)
                out["cards"] = v.ledger_cards
            if notes:   # a chat edit that changes a confirmed decision says so
                out["response"] = f"{out.get('response', '').rstrip()} {' '.join(notes)}".strip()
        if decisions is not None:
            out["decisions"] = v.ledger
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_writer.py tests/test_template_ledger_routes.py tests/test_template_refine.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_writer.py backend/src/rapid_reports_ai/main.py backend/tests/test_template_writer.py backend/tests/test_template_ledger_routes.py
git commit -m "feat(template): writer, analyze and refine carry the decision ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 11: The upgrade script applies a template's stored ledger

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/template_upgrade_apply.py:59-90`
- Test: `backend/tests/test_template_upgrade_apply.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_the_stored_ledger_is_applied_to_the_upgraded_sheet(db_session, test_user, tmp_path, no_jev):
    from rapid_reports_ai import template_decisions as td
    led, _ = td.set_decision([], "value", "Width", {"need": "every"}, source="creation", at="t")
    t = _make_template(db_session, test_user, "Knee 2", {"generation_mode": "skill_sheet_guided",
                                                         "skill_sheet": OLD, "decisions": led})
    summary = U.main(_manifest(tmp_path, t.id, GOOD), apply=True, db=db_session)
    assert _actions(summary) == {str(t.id): "written"}
    db_session.refresh(t)
    assert 'LIST_MISSING ["Width"]' in t.template_config["skill_sheet"] and t.template_config["decisions"] == led
    # a re-run sees its own vetted sheet as already written
    again = U.main(_manifest(tmp_path, t.id, GOOD), apply=True, db=db_session)
    assert _actions(again) == {str(t.id): "already-written"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_upgrade_apply.py::test_the_stored_ledger_is_applied_to_the_upgraded_sheet -q`
Expected: FAIL (`assert 'LIST_MISSING ["Width"]' in ...`)

- [ ] **Step 3: Implement** in `scripts/template_upgrade_apply.py`

Replace `_already_written` with:

```python
async def _already_written(current: str, new_sheet: str, ledger=None) -> bool:
    """Whether the stored sheet is what this entry writes: the new sheet itself or its vetted form (a re-run)."""
    if tss.sheet_hash(current) == tss.sheet_hash(new_sheet):
        return True
    try:
        out = await tsave.vet_sheet(new_sheet, origin=ORIGIN, previous="", ledger=ledger)
    except Exception:  # noqa: BLE001 -- a re-run check only; stale is the safe answer
        return False
    return out.status != "refused" and tss.sheet_hash(current) == tss.sheet_hash(out.sheet)
```

In `_plan_entry`, after `cfg = dict(t.template_config or {})` and the mode check, add

```python
    from rapid_reports_ai import template_decisions as td
    ledger = td.clean_ledger(cfg.get("decisions")) or None   # the decision ledger applies on every origin
```

then change `written = await _already_written(current, entry.get("new_sheet") or "")` to `written = await _already_written(current, entry.get("new_sheet") or "", ledger)` and `out = await tsave.vet_sheet(new_cfg["skill_sheet"], origin=ORIGIN, previous=current)` to `out = await tsave.vet_sheet(new_cfg["skill_sheet"], origin=ORIGIN, previous=current, ledger=ledger)`.

- [ ] **Step 4: Run the upgrade tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_upgrade_apply.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/template_upgrade_apply.py backend/tests/test_template_upgrade_apply.py
git commit -m "feat(template): the upgrade script applies a template's stored decisions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 12: `/skill-sheet/apply-decisions`, and the Phase 1 suite

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py` (request model next to `SkillSheetSaveRequest`; endpoint after `skill_sheet_refine_endpoint`)
- Test: `backend/tests/test_template_ledger_routes.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
APPLY = "/api/templates/skill-sheet/apply-decisions"


def test_apply_decisions_records_answers_and_returns_the_applied_sheet(client, auth_headers):
    r = client.post(APPLY, headers=auth_headers, json={
        "skill_sheet": GOOD, "decisions": _width(), "source": "first_use_review",
        "changes": [{"kind": "normal", "key": "Knee :: menisci", "choice": {"text": "The menisci are normal."}}]}).json()
    assert r["success"], r
    assert LINE in r["skill_sheet"] and 'NORMAL [menisci] "The menisci are normal."' in r["skill_sheet"]
    assert [(e["key"], e["source"]) for e in r["decisions"]] == [("Width", "creation"),
                                                                 ("Knee :: menisci", "first_use_review")]
    assert r["unmatched"] == [] and r["stale_quotes"] == []


def test_apply_decisions_refuses_a_change_code_cannot_apply(client, auth_headers):
    r = client.post(APPLY, headers=auth_headers, json={
        "skill_sheet": GOOD, "changes": [{"kind": "normal", "key": "Knee :: menisci",
                                          "choice": {"text": "Measures {size}."}}]}).json()
    assert r["success"] is False and "Couldn't apply" in r["error"]


def test_apply_decisions_refuses_an_unknown_source(client, auth_headers):
    r = client.post(APPLY, headers=auth_headers, json={"skill_sheet": GOOD, "changes": [], "source": "chat"}).json()
    assert r["success"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_routes.py -q`
Expected: FAIL with 404 / `KeyError: 'success'`

- [ ] **Step 3: Implement** in `main.py`

Request model (after `SkillSheetSaveRequest`):

```python
class SkillSheetApplyDecisionsRequest(BaseModel):
    skill_sheet: str
    decisions: List[Dict[str, Any]] = []   # the ledger so far
    changes: List[Dict[str, Any]] = []     # card answers [{kind, key, choice, source?}]
    source: str = "creation"               # creation | first_use_review (chat goes through /refine)
```

Endpoint (after `skill_sheet_refine_endpoint`):

```python
@app.post("/api/templates/skill-sheet/apply-decisions")
async def skill_sheet_apply_decisions_endpoint(
    request: SkillSheetApplyDecisionsRequest,
    current_user: User = Depends(get_current_user),
):
    """Record card answers on the decision ledger and apply it to the sheet in hand, by code (no model call). The
    creator keeps the result until Create; the refine panel PUTs it, where the save function applies it again."""
    from . import template_ledger_apply as tla
    if request.source not in ("creation", "first_use_review"):
        return {"success": False, "error": "Unknown source."}
    ledger, errors = td.ledger_from_changes(request.changes, base=td.clean_ledger(request.decisions),
                                            source=request.source)
    if errors:
        return {"success": False, "error": f"Couldn't apply that choice ({errors[0]})."}
    res = tla.apply_ledger(request.skill_sheet, ledger)
    if res.failed:
        logger.error("apply-decisions: entries not applied (a bug): %s", [e.get("key") for e in res.failed])
    return {"success": True, "skill_sheet": res.sheet, "decisions": ledger, "applied": res.applied,
            "unmatched": res.unmatched, "stale_quotes": res.stale_quotes}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_routes.py -q`
Expected: all PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: 3878 + the new tests pass, 0 failures. A failure in an untouched test means a fake still lacks `ledger=None` (Task 8 Step 4) or a stored-structure equality now sees `FixedBlock.source_line`: fix the fake or the expected value, never the behaviour.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_template_ledger_routes.py
git commit -m "feat(template): /skill-sheet/apply-decisions records card answers and applies the ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

**Phase 1 checkpoint:** the ledger is live on every save path and dormant until a card writes an entry. Request an independent review (superpowers:requesting-code-review) before Phase 2. Do not merge without Hassan's go-ahead.

---

# Phase 2: the decision run, Jev concept questions, cards and the lab

Outcome: `/api/templates/skill-sheet/decide` returns ranked cards for pasted examples, or for a saved template's stored examples. No UI calls it yet. The lab (Tasks 20-21) runs on synthetic sets **before** Phase 3 wires the cards. **Ships independently** (a dark endpoint).

### Task 13: Decision-run models, prompt and quote check (pure)

**Files:**
- Create: `backend/src/rapid_reports_ai/template_decision_run.py`
- Test: `backend/tests/test_template_decision_run.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The decision run (Rules-step spec, "New flow" step 2): Qwen proposes, code checks every quote, Jev decides."""
import pytest

from rapid_reports_ai import template_decision_run as R
from tests.test_template_sheet_lab_prompts import CLINICAL

EX = ["Findings: LVEF 55%. ECV 28%. No previous imaging.",
      "Findings: LVEF 60%. Compared with CT of 01/01/2020.",
      "Findings: LVEF 50%. ECV 30%. No previous imaging."]


def test_prompt_is_case_agnostic():
    # "contrast" is one of the four standard study-level concepts the spec names (every modality); nothing else
    for word in CLINICAL:
        if word == "contrast":
            continue
        assert word not in R.SYSTEM.lower(), word


def test_user_prompt_numbers_the_reports():
    u = R.user_prompt(["A.", "B."], "<scan>")
    assert "SCAN TYPE: <scan>" in u and "### Report 1\nA." in u and "### Report 2\nB." in u


def test_verified_ignores_case_and_spacing_and_checks_the_cited_report():
    assert R.verified(R.Quote(report=1, text="ecv  28%"), EX)
    assert not R.verified(R.Quote(report=2, text="ECV 28%"), EX)      # not in report 2
    assert not R.verified(R.Quote(report=9, text="LVEF"), EX)
    assert not R.verified(R.Quote(report=1, text="  "), EX)


def test_check_quotes_drops_unverifiable_quotes_and_empty_candidates():
    out = R.RunOutput(
        values=[R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=1, text="LVEF 55%"), R.Quote(report=2, text="LVEF 99%")]),
                R.ValueCandidate(name="Invented", quotes=[R.Quote(report=1, text="never written")]),
                R.ValueCandidate(name='Bad "name"', quotes=[R.Quote(report=1, text="LVEF 55%")])],
        concepts=[R.ConceptWording(concept="comparison", state="none", text="No previous imaging.",
                                   quotes=[R.Quote(report=1, text="No previous imaging.")]),
                  R.ConceptWording(concept="comparison", state="compared", text="Compared with {study}.",
                                   quotes=[R.Quote(report=3, text="Compared with CT")])],
        habits=[R.HabitCandidate(finding="x", habit="y", reports=[1, 3]), R.HabitCandidate(finding="z", habit="w", reports=[2])])
    run = R.check_quotes(out, EX)
    assert [v.name for v in run.values] == ["LVEF"] and len(run.values[0].quotes) == 1
    assert [c.state for c in run.concepts] == ["none"]
    assert [h.finding for h in run.habits] == ["x"]
    assert run.dropped_quotes == 3 and run.ok
    bad = R.RunOutput(concepts=[R.ConceptWording(concept="contrast", state="none", text="x.",
                                                 quotes=[R.Quote(report=1, text="LVEF 55%")])])
    assert R.check_quotes(bad, EX).concepts == []                     # a state the concept does not have
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decision_run.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.template_decision_run'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/template_decision_run.py`)

```python
"""The decision run (Rules-step spec, "New flow" step 2): from the pasted example reports alone, list what needs the
radiologist before the sheet is written. One Qwen call (low temperature, structured output, one job) proposes
candidate required values and the wording of the standard study-level concepts (each wording with the state it states,
never which one is usual: code counts that), each with quotes from the examples;
in parallel Jev answers, per example and per concept, whether the report states it. Code checks every quote against
the example it cites (a candidate left with no verified quote is dropped) and the card builder
(template_rules_cards) turns the result into cards. Jev decides which examples state a concept; Qwen only proposes
wording; code applies.

Fail-soft: a failed or slow Qwen call gives no run (`ok` False, the writer infers rules as today); a failed Jev call
gives `states` None (no study-level cards; value cards still shown)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from . import template_decisions as td

logger = logging.getLogger(__name__)

RUN_VERSION = "decision-run-2026-10-13"
QWEN_TIMEOUT_S = 25.0
FALLBACK_TIMEOUT_S = 25.0
JEV_TIMEOUT_S = 6.0
STATES_MIN = 0.5   # lab-set (scripts/rules_step_lab.py decide): one cut-off for every concept question
SETTINGS = {"temperature": 0.2, "max_tokens": 6000, "reasoning_effort": "low"}

ConceptName = Literal["comparison", "contrast", "sequences", "limitation"]


class Quote(BaseModel):
    report: int   # 1-based example number
    text: str     # copied word for word from that example


class ValueCandidate(BaseModel):
    name: str
    quotes: List[Quote] = []


class ConceptWording(BaseModel):
    concept: ConceptName
    state: str    # what the wording says (one of the concept's states in template_decisions.CONCEPTS)
    text: str     # the wording as a template line, {slots} for what varies
    quotes: List[Quote] = []


class HabitCandidate(BaseModel):
    finding: str
    habit: str
    reports: List[int] = []


class RunOutput(BaseModel):
    values: List[ValueCandidate] = []
    concepts: List[ConceptWording] = []
    habits: List[HabitCandidate] = []


SYSTEM = """You read a radiologist's example reports for one scan type and list the decisions a report template needs from them. You never write the template.

List three things, each grounded in quotes copied word for word from the examples (a quote is a short span of one report, exactly as written there, with the report's number).

1. VALUES: measured or graded values the reports state, each by a short plain name (a few words, no number or unit in the name). One entry per distinct value, with one quote from every report that states it. A value stated in only some reports is still listed. Never list a finding, a diagnosis or a structure that is only described.

2. CONCEPTS: how the reports word four study-level circumstances, when they word them at all, each wording with its state:
- comparison: state "none" (no previous imaging available or compared) or "compared" (a previous study is compared);
- contrast: state "given" (a contrast agent was given) or "not_given" (no contrast agent was given);
- sequences: state "complete" (everything planned was performed) or "not_performed" (a sequence, phase or view was not performed);
- limitation: state "none" (no limitation stated) or "limited" (a technical limitation is stated).
The state says what the wording states, never how often it is used: do not decide which wording is the usual one. Write the wording as a template line: copied from the reports, with the varying parts (dates, study names, the part not performed, the limitation) replaced by a named slot in curly braces such as {date}. Give the quotes it comes from. Different wordings with the same state are separate entries. Leave out a concept that no report words.

3. HABITS: a statement the radiologist adds only when a particular finding is present (the finding, and what they always add), seen in at least two reports. Give the report numbers.

Copy quotes exactly; never paraphrase or invent one. If nothing fits a list, return it empty."""


def user_prompt(examples: List[str], scan_type: str) -> str:
    parts = [f"SCAN TYPE: {scan_type}"]
    for i, ex in enumerate(examples, 1):
        parts.append(f"### Report {i}\n{ex.strip()}")
    return "\n\n".join(parts)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def verified(q: Quote, examples: List[str]) -> bool:
    """The quote appears in the example it cites (case and spacing ignored)."""
    if not 1 <= q.report <= len(examples) or not q.text.strip():
        return False
    return _norm(q.text) in _norm(examples[q.report - 1])


@dataclass
class DecisionRun:
    ok: bool
    values: List[ValueCandidate] = field(default_factory=list)
    concepts: List[ConceptWording] = field(default_factory=list)
    habits: List[HabitCandidate] = field(default_factory=list)
    states: Optional[Dict[str, List[int]]] = None   # concept -> example numbers Jev says state it; None: Jev failed
    dropped_quotes: int = 0
    ms: int = 0
    error: str = ""


def check_quotes(out: RunOutput, examples: List[str]) -> DecisionRun:
    """Keep only verified quotes; drop a candidate left with none, a value name code could not store, and a habit
    seen in fewer than two examples."""
    dropped = 0
    values, concepts = [], []
    for v in out.values:
        ok = [q for q in v.quotes if verified(q, examples)]
        dropped += len(v.quotes) - len(ok)
        name = " ".join(v.name.split())
        if ok and name and len(name.split()) <= td.MAX_VALUE_WORDS and not any(c in name for c in '"|[]{}'):
            values.append(ValueCandidate(name=name, quotes=ok))
    for c in out.concepts:
        ok = [q for q in c.quotes if verified(q, examples)]
        dropped += len(c.quotes) - len(ok)
        if ok and c.text.strip() and '"' not in c.text and c.state in td.CONCEPTS[c.concept].states:
            concepts.append(ConceptWording(concept=c.concept, state=c.state, text=" ".join(c.text.split()), quotes=ok))
    habits = [h for h in out.habits if len({r for r in h.reports if 1 <= r <= len(examples)}) >= 2]
    return DecisionRun(ok=True, values=values, concepts=concepts, habits=habits, dropped_quotes=dropped)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decision_run.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decision_run.py backend/tests/test_template_decision_run.py
git commit -m "feat(template): decision-run models, prompt and quote check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 14: The Qwen call, the Jev concept questions and `run_decisions`

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decision_run.py` (append)
- Test: `backend/tests/test_template_decision_run.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
import httpx

from rapid_reports_ai import template_decisions as td


def _jev(scores_by_report):
    """A transport answering each report's concept questions with the given scores (by concept order)."""
    def handler(request):
        import json
        body = json.loads(request.content)
        report = next(i for i, ex in enumerate(EX) if ex in body["state"])
        return httpx.Response(200, json={"answers": {f"c{i}": {"noul": s}
                                                     for i, s in enumerate(scores_by_report[report])}})
    return httpx.MockTransport(handler)


async def test_ask_states_lists_the_reports_jev_says_state_each_concept():
    t = _jev([[0.9, 0.1, 0.0, 0.0], [0.8, 0.6, 0.0, 0.2], [0.4, 0.0, 0.0, 0.0]])
    states = await R.ask_states(EX, transport=t)
    assert states == {"comparison": [1, 2], "contrast": [2], "sequences": [], "limitation": []}


async def test_ask_states_raises_on_incomplete_answers():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"answers": {"c0": {"noul": 0.9}}}))
    with pytest.raises(ValueError):
        await R.ask_states(EX, transport=t)


async def test_run_decisions_combines_qwen_and_jev(monkeypatch):
    async def qwen(examples, scan_type):
        return R.RunOutput(values=[R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=1, text="LVEF 55%")])])

    async def states(examples, transport=None):
        return {n: [] for n in td.CONCEPTS}
    monkeypatch.setattr(R, "_qwen", qwen)
    monkeypatch.setattr(R, "ask_states", states)
    run = await R.run_decisions(EX, "<scan>")
    assert run.ok and [v.name for v in run.values] == ["LVEF"] and run.states == {n: [] for n in td.CONCEPTS}


async def test_a_failed_qwen_call_gives_no_run_and_a_failed_jev_call_gives_no_states(monkeypatch):
    async def boom(*a, **k):
        raise TimeoutError()

    async def qwen(examples, scan_type):
        return R.RunOutput()
    monkeypatch.setattr(R, "_qwen", boom)
    monkeypatch.setattr(R, "ask_states", boom)
    run = await R.run_decisions(EX, "<scan>")
    assert run.ok is False and run.error == "TimeoutError"
    monkeypatch.setattr(R, "_qwen", qwen)
    run = await R.run_decisions(EX, "<scan>")
    assert run.ok and run.states is None


def test_evidence_record_is_small_and_names_the_version():
    run = R.DecisionRun(ok=True, habits=[R.HabitCandidate(finding="f", habit="h", reports=[1, 2])], dropped_quotes=2)
    ev = R.evidence(run, {"cards": [1, 2], "more": [], "kept": [3]})
    assert ev["version"] == R.RUN_VERSION and ev["dropped_quotes"] == 2 and ev["cards"] == 2 and ev["kept"] == 1
    assert ev["habits"] == [{"finding": "f", "habit": "h", "reports": [1, 2]}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decision_run.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'ask_states'`

- [ ] **Step 3: Implement** (append to `template_decision_run.py`)

```python
async def _qwen(examples: List[str], scan_type: str) -> RunOutput:
    """The decision call on the analyser's model (Qwen); one retry on gpt-oss (another provider) if it fails."""
    from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model

    prompt = user_prompt(examples, scan_type)

    async def call(model: str, timeout: float) -> RunOutput:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=model, output_type=RunOutput, system_prompt=SYSTEM, user_prompt=prompt, api_key="",
            model_settings=dict(SETTINGS)), timeout)
        return r.output

    try:
        return await call(MODEL_CONFIG["SKILL_SHEET_ANALYZER"], QWEN_TIMEOUT_S)
    except Exception as e:
        logger.warning("[decision-run] qwen %s: %s; fallback %s", type(e).__name__, str(e)[:200],
                       MODEL_CONFIG["STACK_REVIEW_FALLBACK"])
        return await call(MODEL_CONFIG["STACK_REVIEW_FALLBACK"], FALLBACK_TIMEOUT_S)


async def ask_states(examples: List[str], transport=None) -> Dict[str, List[int]]:
    """concept -> example numbers whose report states it (Jev noul >= STATES_MIN). One Jev call per example (the four
    questions together), in parallel. Raises on any Jev failure."""
    from .jev_client import JEV_MODEL, jev_post

    names = list(td.CONCEPTS)

    async def one(text: str) -> List[float]:
        qs = {f"c{i}": {"type": "noul", "instructions": td.CONCEPTS[n].question} for i, n in enumerate(names)}
        r = await jev_post({"model": JEV_MODEL, "state": f"REPORT:\n{text}", "questions": qs},
                           os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out = []
        for i in range(len(names)):
            v = (ans.get(f"c{i}") or {}).get("noul")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError("jev: incomplete answers")
            out.append(float(v))
        return out

    scores = await asyncio.gather(*(one(t) for t in examples))
    return {n: [k + 1 for k, s in enumerate(scores) if s[i] >= STATES_MIN] for i, n in enumerate(names)}


async def run_decisions(examples: List[str], scan_type: str) -> DecisionRun:
    """The decision run for these examples. Never raises."""
    t0 = time.monotonic()
    qwen, jev = await asyncio.gather(_qwen(examples, scan_type), ask_states(examples), return_exceptions=True)
    ms = int((time.monotonic() - t0) * 1000)
    if isinstance(qwen, BaseException):
        logger.warning("[decision-run] failed: %s: %s", type(qwen).__name__, str(qwen)[:200])
        return DecisionRun(ok=False, ms=ms, error=type(qwen).__name__)
    run = check_quotes(qwen, examples)
    run.ms = ms
    if isinstance(jev, BaseException):
        logger.warning("[decision-run] jev failed: %s", type(jev).__name__)
    else:
        run.states = jev
    logger.info("[decision-run] values=%d concepts=%d habits=%d dropped_quotes=%d jev=%s ms=%d", len(run.values),
                len(run.concepts), len(run.habits), run.dropped_quotes, run.states is not None, ms)
    return run


def evidence(run: DecisionRun, built: Optional[dict] = None) -> dict:
    """The record stored with the template (template_config["rules_step"]): counts, timings, hidden habit candidates
    for the findings-triggered rows lab. No example text."""
    out = {"version": RUN_VERSION, "ok": run.ok, "ms": run.ms, "error": run.error, "values": len(run.values),
           "concepts": len(run.concepts), "dropped_quotes": run.dropped_quotes, "jev": run.states is not None,
           "habits": [h.model_dump() for h in run.habits]}
    if built:
        out.update(cards=len(built["cards"]), more=len(built["more"]), kept=len(built["kept"]))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decision_run.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decision_run.py backend/tests/test_template_decision_run.py
git commit -m "feat(template): decision run: Qwen proposals, Jev concept questions, fail-soft

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 15: Read a template's stored examples

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_examples.py` (append)
- Test: `backend/tests/test_template_examples.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_stored_texts_returns_the_templates_examples_newest_first(db_session, guided_template):
    from datetime import datetime, timedelta
    from rapid_reports_ai.database.models import TemplateExample
    now = datetime.utcnow()
    for i, text in enumerate(["old report", "new report"]):
        db_session.add(TemplateExample(template_id=guided_template.id, text=text, sha256=str(i) * 64,
                                       source="pasted", created_at=now + timedelta(minutes=i)))
    db_session.commit()
    assert E.stored_texts(db_session, guided_template.id) == ["new report", "old report"]
    assert E.stored_texts(db_session, "not-a-uuid") == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_examples.py::test_stored_texts_returns_the_templates_examples_newest_first -q`
Expected: FAIL with `AttributeError: ... has no attribute 'stored_texts'`

- [ ] **Step 3: Implement** (append to `template_examples.py`)

```python
def stored_texts(db, template_id, limit: int = MAX_EXAMPLES) -> list[str]:
    """The template's stored (scrubbed) example reports, newest first; [] on any error (the first-use review then
    shows only the Style-step cards)."""
    try:
        tid = template_id if isinstance(template_id, uuid.UUID) else uuid.UUID(str(template_id))
        rows = (db.query(TemplateExample.text).filter(TemplateExample.template_id == tid)
                .order_by(TemplateExample.created_at.desc()).limit(limit).all())
        return [t for (t,) in rows if t]
    except Exception as e:
        logger.warning("template examples not read for %s: %s", template_id, type(e).__name__)
        return []
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_examples.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_examples.py backend/tests/test_template_examples.py
git commit -m "feat(template): read a template's stored example reports

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 16: Card shapes and `build_cards` (evidence, ranking, budget, kept list, defaults)

**Files:**
- Create: `backend/src/rapid_reports_ai/template_rules_cards.py`
- Test: `backend/tests/test_template_rules_cards.py`

- [ ] **Step 1: Write the failing tests**

```python
"""One-tap decision cards (Rules-step spec, "Cards")."""
from rapid_reports_ai import template_decision_run as R
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_rules_cards as C

EX = ["Findings: LVEF 55%. ECV 28%. No previous imaging.",
      "Findings: LVEF 60%. Compared with CT of 01/01/2020.",
      "Findings: LVEF 50%. ECV 30%. No previous imaging."]


def _run(values=(), concepts=(), states=None):
    out = R.RunOutput(values=list(values), concepts=list(concepts))
    run = R.check_quotes(out, EX)
    run.states = states
    return run


def _q(r, t):
    return R.Quote(report=r, text=t)


LVEF = R.ValueCandidate(name="LVEF", quotes=[_q(1, "LVEF 55%"), _q(2, "LVEF 60%"), _q(3, "LVEF 50%")])
ECV = R.ValueCandidate(name="ECV", quotes=[_q(1, "ECV 28%"), _q(3, "ECV 30%")])
NO_PRIOR = R.ConceptWording(concept="comparison", state="none", text="No previous imaging.",
                            quotes=[_q(1, "No previous imaging."), _q(3, "No previous imaging.")])
PRIOR = R.ConceptWording(concept="comparison", state="compared", text="Compared with {study} of {date}.",
                         quotes=[_q(2, "Compared with CT of 01/01/2020.")])
ALL = {"comparison": [1, 2, 3], "contrast": [], "sequences": [], "limitation": []}
PRIOR_COND = "the dictation names a previous imaging study for comparison"


def test_evidence_line_names_reports_never_percentages():
    assert C.evidence_line({"reports": [4, 1, 2], "quote": "ECV 28%"}) == "reports 1, 2, 4: 'ECV 28%'"
    assert C.evidence_line({"reports": [3], "quote": None}) == "report 3: not stated"


def test_a_value_in_every_example_is_kept_pre_ticked_and_a_partial_one_is_a_card():
    out = C.build_cards(_run([LVEF, ECV], states=ALL), 3)
    assert [c["id"] for c in out["kept"]] == ["value:lvef"] and out["kept"][0]["selected"] == "every"
    ecv = out["cards"][0]
    assert ecv["id"] == "value:ecv" and ecv["selected"] is None
    assert [C.evidence_line(e) for e in ecv["evidence"]] == ["reports 1, 3: 'ECV 28%'", "report 2: not stated"]
    assert [c["id"] for c in ecv["choices"]] == ["every", "relevant", "not_needed"]
    assert out["defaults"] == [{"kind": "value", "key": "LVEF", "choice": {"need": "every"}}]


def test_a_varying_concept_is_a_card_with_both_wordings_never_pre_ticked():
    out = C.build_cards(_run([], [NO_PRIOR, PRIOR], states=ALL), 3)
    card = next(c for c in out["cards"] if c["id"] == "concept:comparison")
    assert card["wording"] == {"default": "No previous imaging.", "when_met": "Compared with {study} of {date}.",
                               "condition": PRIOR_COND}
    assert card["selected"] is None
    keep = next(x for x in card["choices"] if x["id"] == "keep")["choice"]
    assert td.validate("concept", "comparison", keep)[1] == keep


def test_a_default_only_concept_is_still_asked():
    out = C.build_cards(_run([], [NO_PRIOR], states={**ALL, "comparison": [1, 2, 3]}), 3)
    assert [c["id"] for c in out["cards"]] == ["concept:comparison"] and not out["kept"]


def test_two_wordings_for_one_role_are_a_disagreement_ranked_first():
    other = R.ConceptWording(concept="comparison", state="none", text="LVEF 60%.", quotes=[_q(2, "LVEF 60%.")])
    out = C.build_cards(_run([ECV], [NO_PRIOR, other, PRIOR], states=ALL), 3)
    assert out["cards"][0]["kind"] == "disagree" and out["cards"][0]["key"] == "comparison"
    labels = [x["label"] for x in out["cards"][0]["choices"]]
    assert labels[-1] == "Use whichever is dictated" and len(labels) == 3
    dictated = out["cards"][0]["choices"][-1]["choice"]                 # its own choice, not "not used"
    assert td.validate("concept", "comparison", dictated)[1]["dictated"] is True


def test_no_jev_means_no_study_level_cards():
    out = C.build_cards(_run([ECV], [NO_PRIOR, PRIOR], states=None), 3)
    assert [c["kind"] for c in out["cards"]] == ["value"]


def test_a_verified_quote_counts_as_stating_when_jev_misses_it():
    out = C.build_cards(_run([], [NO_PRIOR, PRIOR], states={n: [] for n in td.CONCEPTS}), 3)
    card = out["cards"][0]
    assert card["id"] == "concept:comparison" and not any(e["quote"] is None for e in card["evidence"])


def test_a_concept_every_example_words_the_same_way_is_still_a_card():
    prior_all = R.ConceptWording(concept="comparison", state="compared", text="Compared with {study}.",
                                 quotes=[_q(1, "LVEF 55%"), _q(2, "LVEF 60%"), _q(3, "LVEF 50%")])
    out = C.build_cards(_run([], [prior_all], states=ALL), 3)
    assert [c["id"] for c in out["cards"]] == ["concept:comparison"] and out["kept"] == []


EX_C = ["Technique: No contrast agent was given. LVEF 55%.", "Technique: No contrast agent was given. LVEF 60%.",
        "Technique: Following a contrast agent. LVEF 50%."]


def test_contrast_default_is_the_usual_wording_and_the_condition_is_its_opposite():
    none = R.ConceptWording(concept="contrast", state="not_given", text="No contrast agent was given.",
                            quotes=[_q(1, "No contrast agent was given."), _q(2, "No contrast agent was given.")])
    given = R.ConceptWording(concept="contrast", state="given", text="Following a contrast agent.",
                             quotes=[_q(3, "Following a contrast agent.")])
    run = R.check_quotes(R.RunOutput(concepts=[none, given]), EX_C)
    run.states = {n: [] for n in td.CONCEPTS}
    card = C.build_cards(run, 3)["cards"][0]
    assert card["wording"] == {"default": "No contrast agent was given.", "when_met": "Following a contrast agent.",
                               "condition": "the dictation states a contrast agent was given"}
    # the same wordings, with the given wording usual: the other way round
    given2 = given.model_copy(update={"quotes": [_q(3, "Following a contrast agent."), _q(1, "LVEF 55%"),
                                                 _q(2, "LVEF 60%")]})
    run = R.check_quotes(R.RunOutput(concepts=[none.model_copy(update={"quotes": [_q(1, "No contrast agent was given.")]}),
                                               given2]), EX_C)
    run.states = {n: [] for n in td.CONCEPTS}
    card = C.build_cards(run, 3)["cards"][0]
    assert card["wording"]["default"] == "Following a contrast agent."
    assert card["wording"]["condition"] == "the dictation states no contrast agent was given"


def test_the_budget_moves_the_rest_to_more():
    vals = [R.ValueCandidate(name=f"Value {i}", quotes=[_q(1, "LVEF 55%")]) for i in range(11)]
    out = C.build_cards(_run(vals, states=ALL), 3)
    assert len(out["cards"]) == C.MAX_CARDS and len(out["more"]) == 3


def test_a_failed_run_has_no_cards():
    assert C.build_cards(R.DecisionRun(ok=False), 3) == {"cards": [], "more": [], "kept": [], "defaults": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_rules_cards.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.template_rules_cards'`

- [ ] **Step 3: Write the module** (`backend/src/rapid_reports_ai/template_rules_cards.py`)

```python
"""One-tap decision cards (Rules-step spec, "Cards"): one shape for the Rules step, the Style step and the chat-edit
router's uncertain changes. A card names a ledger item (ledger_kind, key) and offers choices, each carrying the
ledger choice it records (None: the radiologist writes the wording). Answering a card is set_decision on its item.

Card: {"id", "kind", "step", "title", "evidence": [{"reports": [..], "quote": str | None}], "ledger_kind", "key",
       "choices": [{"id", "label", "choice": dict | None}], "selected": choice id | None, "rank", "wording"?}

build_cards(run, n_examples) -> {"cards", "more", "kept", "defaults"}: exceptions only, ranked (examples disagree,
then uncertain values, then concept wording); at most MAX_CARDS open, the rest in "more"; items every example agrees
on fold into "kept" (pre-ticked); nothing seen in fewer than every example is pre-ticked; "defaults" are the
pre-ticked choices, recorded with source "default" when the step is skipped or the kept items are left alone.
Only values every example states are kept; a study-level concept is always a card (D1)."""
from __future__ import annotations

from typing import Dict, List, Optional

from . import template_decisions as td
from .template_decision_run import DecisionRun

MAX_CARDS = 8
_RANK = {"disagree": 0, "value": 1, "concept": 2, "fixed": 3, "normal": 4, "uncovered": 5}


def _reports(nums) -> str:
    nums = sorted(set(nums))
    return ("report " if len(nums) == 1 else "reports ") + ", ".join(str(n) for n in nums)


def evidence_line(e: dict) -> str:
    """"reports 1, 2, 4: 'ECV 28%'" or "report 3: not stated" (never percentages)."""
    return f"{_reports(e['reports'])}: " + (f"'{e['quote']}'" if e.get("quote") else "not stated")


def _choice(cid: str, label: str, choice: Optional[dict]) -> dict:
    return {"id": cid, "label": label, "choice": choice}


def value_card(name: str, evidence: List[dict], selected: Optional[str] = None, step: str = "rules") -> dict:
    return {"id": f"value:{td._name(name)}", "kind": "value", "step": step, "title": name, "evidence": evidence,
            "ledger_kind": "value", "key": name,
            "choices": [_choice("every", "Every report", {"need": "every"}),
                        _choice("relevant", "Only when relevant", {"need": "relevant"}),
                        _choice("not_needed", "Not needed", {"need": "not_needed"})],
            "selected": selected, "rank": _RANK["value"]}


def concept_card(concept: str, default: str, when_met: str, evidence: List[dict], condition: str = "",
                 step: str = "rules") -> dict:
    """Study-level wording. Never pre-ticked (product decision D1): the radiologist always sees which wording is
    printed and when the other replaces it (`condition`)."""
    return {"id": f"concept:{concept}", "kind": "concept", "step": step, "title": td.CONCEPTS[concept].label,
            "evidence": evidence, "ledger_kind": "concept", "key": concept,
            "wording": {"default": default, "when_met": when_met, "condition": condition},
            "choices": [_choice("keep", "Keep", {"use": True, "default": default, "when_met": when_met,
                                                 "condition": condition, "dictated": False}),
                        _choice("edit", "Edit wording", None),
                        _choice("not_used", "Not used", {"use": False, "default": "", "when_met": "", "condition": "",
                                                         "dictated": False})],
            "selected": None, "rank": _RANK["concept"]}


def disagree_card(concept: str, options: List[dict], other: str, role: str, evidence: List[dict],
                  condition: str) -> dict:
    """options: [{"text", "reports"}] for one side; `other` the single wording of the other side ("" if none).
    "Use whichever is dictated" is its own choice ({"use": false, "dictated": true}), not "not used"."""
    choices = []
    for k, o in enumerate(options):
        default, when_met = (o["text"], other) if role == "default" else (other, o["text"])
        choices.append(_choice(f"w{k}", f"Use \u201c{o['text']}\u201d",
                               {"use": True, "default": default, "when_met": when_met, "condition": condition,
                                "dictated": False}))
    choices.append(_choice("dictated", "Use whichever is dictated",
                           {"use": False, "default": "", "when_met": "", "condition": "", "dictated": True}))
    return {"id": f"disagree:{concept}", "kind": "disagree", "step": "rules",
            "title": f"Your examples word {td.CONCEPTS[concept].label.lower()} differently", "evidence": evidence,
            "ledger_kind": "concept", "key": concept, "choices": choices, "selected": None, "rank": _RANK["disagree"]}


def fixed_card(text: str, step: str = "style", selected: Optional[str] = None) -> dict:
    return {"id": f"fixed:{td.match_key('fixed', text)}", "kind": "fixed", "step": step, "title": text,
            "evidence": [], "ledger_kind": "fixed", "key": text,
            "choices": [_choice("always", "Always the same", {"keep": "always"}),
                        _choice("dictated", "Only when dictated", {"keep": "dictated"}),
                        _choice("remove", "Remove", {"keep": "remove"})],
            "selected": selected, "rank": _RANK["fixed"]}


def normal_card(key: str, text: str, step: str = "style") -> dict:
    para, label, neg = td.split_normal_key(key)
    return {"id": f"normal:{td.match_key('normal', key)}", "kind": "normal", "step": step,
            "title": para if neg else f"{para}: {label}", "evidence": [], "ledger_kind": "normal", "key": key,
            "wording": {"text": text},
            "choices": [_choice("keep", "Keep", {"text": text}), _choice("edit", "Edit wording", None),
                        _choice("remove", "Remove", {"text": ""})],
            "selected": None, "rank": _RANK["normal"]}


def uncovered_card(paragraph: str, structure: str) -> dict:
    key = td.normal_key(paragraph, structure)
    return {"id": f"uncovered:{td.match_key('normal', key)}", "kind": "uncovered", "step": "style",
            "title": f"{paragraph}: {structure}", "evidence": [], "ledger_kind": "normal", "key": key,
            "choices": [_choice("add", "Add wording", None), _choice("leave", "Leave unmentioned", {"text": ""})],
            "selected": None, "rank": _RANK["uncovered"]}


def defaults_of(cards: List[dict]) -> List[dict]:
    """The pre-ticked choice of each card, as a change [{kind, key, choice}]."""
    out = []
    for c in cards:
        ch = next((x["choice"] for x in c["choices"] if x["id"] == c.get("selected")), None)
        if ch is not None:
            out.append({"kind": c["ledger_kind"], "key": c["key"], "choice": ch})
    return out


def _value_cards(run: DecisionRun, n: int) -> List[dict]:
    out = []
    for v in run.values:
        reports = sorted({q.report for q in v.quotes})
        ev = [{"reports": reports, "quote": v.quotes[0].text}]
        missing = [k for k in range(1, n + 1) if k not in reports]
        if missing:
            ev.append({"reports": missing, "quote": None})
        out.append(value_card(v.name, ev, selected=None if missing else "every"))
    return out


def _concept_cards(run: DecisionRun, n: int) -> List[dict]:
    """One card per concept the examples word (never folded into "kept"). The default is the base state's wording
    (no previous study, everything performed, no limitation); for contrast, whose two states both have a condition,
    it is the state the examples use most (D1), and the condition stored is the opposite state's."""
    if run.states is None:
        return []
    out = []
    for name, c in td.CONCEPTS.items():
        by_state: Dict[str, List[dict]] = {s: [] for s in c.states}
        seen: Dict[str, dict] = {}
        for w in run.concepts:
            if w.concept != name:
                continue
            k = f"{w.state}:{td.match_key('fixed', w.text)}"
            if k in seen:
                seen[k]["reports"] = sorted(set(seen[k]["reports"]) | {q.report for q in w.quotes})
                continue
            seen[k] = {"text": w.text, "reports": sorted({q.report for q in w.quotes}), "quote": w.quotes[0].text}
            by_state[w.state].append(seen[k])
        if not any(by_state.values()):
            continue
        quoted = {r for ws in by_state.values() for w in ws for r in w["reports"]}
        stating = set(run.states.get(name) or []) | quoted     # a verified quote counts even when Jev missed it
        base = next((s for s, cond in c.states.items() if cond is None), None)
        if base is None:
            counts = {s: len({r for w in ws for r in w["reports"]}) for s, ws in by_state.items()}
            base = max(c.states, key=lambda s: counts[s])
        other = next(s for s in c.states if s != base)
        condition = c.states[other]
        silent = [k for k in range(1, n + 1) if k not in stating]
        ev = [{"reports": w["reports"], "quote": w["quote"]} for w in [*by_state[base], *by_state[other]]]
        if silent:
            ev.append({"reports": silent, "quote": None})
        split = next((s for s in (base, other) if len(by_state[s]) > 1), None)
        if split:
            rest = by_state[other if split == base else base]
            out.append(disagree_card(name, by_state[split], rest[0]["text"] if len(rest) == 1 else "",
                                     "default" if split == base else "when_met", ev, condition))
            continue
        default = by_state[base][0]["text"] if by_state[base] else ""
        when_met = by_state[other][0]["text"] if by_state[other] else ""
        out.append(concept_card(name, default, when_met, ev, condition))
    return out


def build_cards(run: DecisionRun, n_examples: int) -> dict:
    if not run.ok:
        return {"cards": [], "more": [], "kept": [], "defaults": []}
    every = [*_value_cards(run, n_examples), *_concept_cards(run, n_examples)]
    kept = [c for c in every if c["selected"] is not None]
    open_ = sorted((c for c in every if c["selected"] is None),
                   key=lambda c: (c["rank"], -sum(len(e["reports"]) for e in c["evidence"] if e.get("quote"))))
    return {"cards": open_[:MAX_CARDS], "more": open_[MAX_CARDS:], "kept": kept, "defaults": defaults_of(kept)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_rules_cards.py -q`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_rules_cards.py backend/tests/test_template_rules_cards.py
git commit -m "feat(template): decision cards (evidence, ranking, budget, kept list, defaults)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 17: Value cards for a stored template, and the router's one-tap card

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_rules_cards.py` (append)
- Test: `backend/tests/test_template_rules_cards.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
from rapid_reports_ai import template_ledger_apply as tla
from tests.template_sheet_fixtures import LEDGER_SHEET


def test_current_value_cards_show_the_sheets_list_and_the_ledgers_other_values():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation")
    led, _ = td.set_decision(led, "value", "ECV", {"need": "relevant"}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    cards = C.current_value_cards(sheet, led)
    assert [(c["key"], c["selected"]) for c in cards] == [("LVEF", "every"), ("ECV", "relevant")]
    assert C.current_value_cards("# not grammar", led) == []


def test_card_for_change_is_prefilled_and_not_preselected():
    card = C.card_for_change("value", "ECV", {"need": "not_needed"})
    assert card["id"] == "value:ecv" and card["step"] == "chat" and card["selected"] is None
    card = C.card_for_change("concept", "comparison", {"use": True, "default": "", "when_met": "Compared with {date}."})
    assert card["wording"] == {"default": "", "when_met": "Compared with {date}.", "condition": PRIOR_COND}
    card = C.card_for_change("normal", "Liver :: liver", {"text": "The liver is normal."})
    assert card["wording"] == {"text": "The liver is normal."} and card["kind"] == "normal"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_rules_cards.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'current_value_cards'`

- [ ] **Step 3: Implement** (append to `template_rules_cards.py`)

```python
def current_value_cards(sheet: str, ledger: List[dict]) -> List[dict]:
    """The Required-values rows for a stored template (the refine panel): every LIST_MISSING item (selected as the
    ledger says, else "every") and every value the ledger records as only-when-relevant or not needed."""
    from . import template_sheet_grammar as tsg
    if not tsg.is_grammar_sheet(sheet or ""):
        return []
    st = tsg.parse_sheet(sheet, mode="template").structure
    out, seen = [], set()
    for name in [x for r in st.rules if r.effect == "list_missing" for x in r.items]:
        if td._name(name) in seen:
            continue
        e = td.find(ledger, "value", name)
        out.append(value_card(name, [], selected=e["choice"]["need"] if e else "every", step="review"))
        seen.add(td._name(name))
    for e in ledger or []:
        if e.get("kind") == "value" and td._name(e["key"]) not in seen:
            out.append(value_card(e["key"], [], selected=e["choice"]["need"], step="review"))
            seen.add(td._name(e["key"]))
    return out


def card_for_change(kind: str, key: str, proposed: dict) -> dict:
    """The one-tap card for a change code could not apply as given (the chat-edit router's uncertain or rejected
    parts), prefilled with the proposed wording and not pre-selected. DecisionError on an invalid proposal."""
    key, proposed = td.validate(kind, key, proposed)
    if kind == "value":
        return value_card(key, [], step="chat")
    if kind == "concept":
        return concept_card(key, proposed.get("default", ""), proposed.get("when_met", ""), [],
                            proposed.get("condition", ""), step="chat")
    if kind == "fixed":
        return fixed_card(key, step="chat")
    return normal_card(key, proposed.get("text", ""), step="chat")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_rules_cards.py -q`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_rules_cards.py backend/tests/test_template_rules_cards.py
git commit -m "feat(template): value cards for a stored template; the router's one-tap card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 18: `/api/templates/skill-sheet/decide`

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decision_run.py` (append `stamp_review`)
- Modify: `backend/src/rapid_reports_ai/main.py` (request model after `SkillSheetApplyDecisionsRequest`; endpoint after `/apply-decisions`)
- Test: `backend/tests/test_template_decide_route.py`

- [ ] **Step 1: Write the failing tests**

```python
"""/skill-sheet/decide: the Rules step's cards; fail-soft (Rules-step spec, "Failure behaviour")."""
import pytest

from rapid_reports_ai import template_decision_run as R
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai.database.models import TemplateExample
from tests.conftest import _make_template
from tests.template_sheet_fixtures import LEDGER_SHEET

URL = "/api/templates/skill-sheet/decide"
EX = [{"content": "Findings: LVEF 55%. ECV 28%."}, {"content": "Findings: LVEF 60%."},
      {"content": "Findings: LVEF 50%. ECV 30%."}]


@pytest.fixture
def run_returns(monkeypatch):
    seen = {}

    def set_run(run):
        async def fake(examples, scan_type):
            seen.update(examples=examples, scan_type=scan_type)
            return run
        monkeypatch.setattr(R, "run_decisions", fake)
    return set_run, seen


def _run():
    out = R.RunOutput(values=[
        R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=i, text=t) for i, t in
                                              [(1, "LVEF 55%"), (2, "LVEF 60%"), (3, "LVEF 50%")]]),
        R.ValueCandidate(name="ECV", quotes=[R.Quote(report=1, text="ECV 28%"), R.Quote(report=3, text="ECV 30%")])])
    run = R.check_quotes(out, [e["content"] for e in EX])
    run.states = {n: [] for n in td.CONCEPTS}
    return run


def test_decide_returns_cards_kept_defaults_and_the_run_record(client, auth_headers, run_returns):
    set_run, seen = run_returns
    set_run(_run())
    r = client.post(URL, headers=auth_headers, json={"scan_type": "<scan>", "examples": EX}).json()
    assert r["success"] and r["ran"] and r["notice"] == ""
    assert [c["id"] for c in r["cards"]] == ["value:ecv"] and [c["id"] for c in r["kept"]] == ["value:lvef"]
    assert r["defaults"] == [{"kind": "value", "key": "LVEF", "choice": {"need": "every"}}]
    assert r["run"]["version"] == R.RUN_VERSION and r["run"]["cards"] == 1
    assert seen["scan_type"] == "<scan>" and len(seen["examples"]) == 3


def test_a_failed_run_gives_no_cards_and_the_notice(client, auth_headers, run_returns):
    set_run, _ = run_returns
    set_run(R.DecisionRun(ok=False, error="TimeoutError"))
    r = client.post(URL, headers=auth_headers, json={"scan_type": "<scan>", "examples": EX}).json()
    assert r["success"] and r["ran"] is False and r["cards"] == []
    assert r["notice"] == "We couldn't pre-check your rules; review them on the Style step."


def test_an_exception_is_still_fail_soft(client, auth_headers, monkeypatch):
    async def boom(examples, scan_type):
        raise RuntimeError("x")
    monkeypatch.setattr(R, "run_decisions", boom)
    r = client.post(URL, headers=auth_headers, json={"scan_type": "<scan>", "examples": EX}).json()
    assert r["success"] and r["cards"] == [] and r["notice"]


def test_a_saved_template_uses_its_stored_examples_and_shows_its_current_values(
        client, auth_headers, db_session, test_user, run_returns):
    set_run, seen = run_returns
    set_run(_run())
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation")
    # an upgraded template: LIST_MISSING in the sheet, no decisions and no decision-run record yet
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided", "scan_type": "<scan>",
                                                    "skill_sheet": tla.apply_ledger(LEDGER_SHEET, led).sheet})
    for i, e in enumerate(EX):
        db_session.add(TemplateExample(template_id=t.id, text=e["content"], sha256=str(i) * 64, source="pasted"))
    db_session.commit()
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["success"] and r["ran"] and len(seen["examples"]) == 3 and seen["scan_type"] == "<scan>"
    assert [(c["id"], c["selected"]) for c in r["cards"]] == [("value:lvef", "every"), ("value:ecv", None)]
    assert r["kept"] == [] and r["defaults"] == []      # LVEF is already shown as the template's current value


def test_the_first_use_review_is_stamped_on_the_server_and_never_repeats(client, auth_headers, db_session, test_user,
                                                                          run_returns):
    set_run, seen = run_returns
    set_run(_run())
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided",
                                                    "skill_sheet": LEDGER_SHEET})
    for i, e in enumerate(EX):
        db_session.add(TemplateExample(template_id=t.id, text=e["content"], sha256=str(i) * 64, source="pasted"))
    db_session.commit()
    assert client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()["ran"] is True
    db_session.refresh(t)
    assert t.template_config["rules_step"]["version"] == R.RUN_VERSION and t.template_config["rules_step"]["first_use"]
    seen.clear()
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["ran"] is False and "examples" not in seen               # not run again, saved or not


def test_a_saved_template_without_examples_shows_only_its_values(client, auth_headers, db_session, test_user,
                                                                  run_returns):
    set_run, seen = run_returns
    set_run(_run())
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided",
                                                    "skill_sheet": LEDGER_SHEET})
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["success"] and r["ran"] is False and r["cards"] == [] and "examples" not in seen


def test_a_reviewed_template_is_not_re_run(client, auth_headers, db_session, test_user, run_returns):
    set_run, seen = run_returns
    set_run(_run())
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided",
                                                    "skill_sheet": LEDGER_SHEET, "rules_step": {"version": "v"}})
    for i, e in enumerate(EX):
        db_session.add(TemplateExample(template_id=t.id, text=e["content"], sha256=str(i) * 64, source="pasted"))
    db_session.commit()
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["success"] and r["ran"] is False and "examples" not in seen


def test_another_users_template_is_not_found(client, auth_headers, db_session, run_returns):
    import uuid
    r = client.post(URL, headers=auth_headers, json={"template_id": str(uuid.uuid4())}).json()
    assert r == {"success": False, "error": "Template not found"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decide_route.py -q`
Expected: FAIL (404 on the URL)

- [ ] **Step 3: Implement.** Append to `template_decision_run.py`:

```python
def stamp_review(db, template_id, record: dict) -> bool:
    """Mark a saved template's first-use review as run (template_config["rules_step"]), so the paid run is not
    repeated on the next open, even when the panel is closed without saving. Never overwrites a record; never
    raises (the review is evidence, not a reason to fail)."""
    import uuid
    from sqlalchemy.orm.attributes import flag_modified
    from .database.models import Template
    try:
        tpl = (db.query(Template).filter(Template.id == uuid.UUID(str(template_id))).with_for_update().first())
        if tpl is None or (tpl.template_config or {}).get("rules_step"):
            db.rollback()
            return False
        tpl.template_config = {**(tpl.template_config or {}), "rules_step": {**record, "first_use": True}}
        flag_modified(tpl, "template_config")
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning("[decision-run] review not stamped for %s: %s", template_id, type(e).__name__)
        return False
```

In `main.py`, the request model (after `SkillSheetApplyDecisionsRequest`):

```python
class SkillSheetDecideRequest(BaseModel):
    scan_type: str = ""
    examples: List[SkillSheetExample] = []
    template_id: Optional[str] = None      # a saved template: its stored examples and current values


NO_PRECHECK = "We couldn't pre-check your rules; review them on the Style step."
MIN_DECIDE_EXAMPLES = 2
```

Endpoint (after `skill_sheet_apply_decisions_endpoint`):

```python
@app.post("/api/templates/skill-sheet/decide")
async def skill_sheet_decide_endpoint(
    request: SkillSheetDecideRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The Rules step: the decision run on the pasted examples (or a saved template's stored examples) as cards.
    Fail-soft: a failed run returns no cards and a notice; nothing here blocks template creation."""
    from . import template_decision_run as tdr
    from . import template_rules_cards as trc
    empty = {"success": True, "ran": False, "cards": [], "more": [], "kept": [], "defaults": [], "notice": "",
             "run": {}}
    try:
        examples = [e.content for e in request.examples if e.content.strip()]
        scan_type = request.scan_type
        current: list = []
        if request.template_id:
            owned = get_template(db, request.template_id, user_id=str(current_user.id))
            if not owned:
                return {"success": False, "error": "Template not found"}
            cfg = owned.template_config or {}
            current = trc.current_value_cards(cfg.get("skill_sheet") or "", td.clean_ledger(cfg.get("decisions")))
            scan_type = scan_type or cfg.get("scan_type") or ""
            # first-use review only: a template that has decisions or a decision-run record is not re-run
            reviewed = bool(cfg.get("decisions")) or bool(cfg.get("rules_step"))
            if not examples and not reviewed:
                examples = template_examples.stored_texts(db, owned.id)
        if len(examples) < MIN_DECIDE_EXAMPLES:
            return {**empty, "cards": current}
        run = await tdr.run_decisions(examples, scan_type)
        if not run.ok:
            return {**empty, "cards": current, "notice": NO_PRECHECK, "run": tdr.evidence(run)}
        if request.template_id:   # first-use review: stamped on the server so it never runs twice
            tdr.stamp_review(db, request.template_id, tdr.evidence(run))
        built = trc.build_cards(run, len(examples))
        have = {c["id"] for c in current}
        kept = [c for c in built["kept"] if c["id"] not in have]
        out = {"cards": [*current, *(c for c in built["cards"] if c["id"] not in have)],
               "more": [c for c in built["more"] if c["id"] not in have], "kept": kept}
        return {"success": True, "ran": True, **out, "defaults": trc.defaults_of(kept), "notice": "",
                "run": tdr.evidence(run, out)}
    except Exception as e:
        logger.warning("skill-sheet decide failed: %s", type(e).__name__)
        return {**empty, "notice": NO_PRECHECK}
```

The `get_template` call raises on a malformed id in some code paths. If `test_another_users_template_is_not_found` fails on a malformed id, wrap `get_template` exactly as the refine endpoint does (`main.py:2750-2756`: `try … except Exception: db.rollback(); owned = None`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_decide_route.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: 0 failures

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decision_run.py backend/src/rapid_reports_ai/main.py backend/tests/test_template_decide_route.py
git commit -m "feat(template): /skill-sheet/decide returns the Rules-step cards (fail-soft)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 19: Lab script: decision-run runner and scorer

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/rules_step_lab.py`
- Test: `backend/tests/test_rules_step_lab.py`

The lab reads synthetic sets from the private folder and never writes into the repo. Set file format (`<root>/sets/<slug>.json`):

```json
{"slug": "cardiac_mr_2__ecv_partial", "seed": "cardiac_mr_2", "kind": "base|variant|real", "scan_type": "...",
 "examples": ["<report 1>", "..."],
 "truth": {
   "values": [{"name": "LVEF", "aliases": ["ejection fraction"], "reports": [1, 2, 3, 4, 5], "need": "every"}],
   "concepts": {"comparison": {"stated_in": [2, 4], "default": "<wording>", "when_met": "<wording with {slots}>"}},
   "disagreements": ["contrast"],
   "patient_specific_fixed": ["<a sentence repeated across examples that is false for some patients>"],
   "only_when_abnormal": [{"paragraph": "<name>", "structure": "<structure>"}]
 }}
```

- [ ] **Step 1: Write the failing tests**

```python
"""Pure scorers of the Rules-step lab (no network)."""
from rapid_reports_ai.scripts import rules_step_lab as L

SET = {"slug": "s", "examples": ["a", "b", "c", "d"], "truth": {
    "values": [{"name": "LVEF", "aliases": ["ejection fraction"], "reports": [1, 2, 3, 4], "need": "every"},
               {"name": "ECV", "aliases": [], "reports": [1, 3], "need": "relevant"}],
    "concepts": {"comparison": {"stated_in": [2, 4]}, "contrast": {"stated_in": [], "usual_state": "not_given"}},
    "disagreements": ["contrast"], "patient_specific_fixed": [], "only_when_abnormal": []}}


def _card(cid, kind="value", key=None, evidence=()):
    return {"id": cid, "kind": kind, "key": key or cid.split(":")[1], "evidence": list(evidence)}


def test_score_decide_counts_values_concepts_disagreements_and_budget():
    contrast = {**_card("concept:contrast", "concept", "contrast"),
                "wording": {"condition": "the dictation states a contrast agent was given"}}
    payload = {"cards": [_card("value:ecv"), _card("value:heart rate"), _card("disagree:contrast", "disagree", "contrast"),
                         contrast],
               "more": [], "kept": [_card("value:ejection fraction", key="Ejection fraction")],
               "run": {"dropped_quotes": 2}, "states": {"comparison": [2, 4], "contrast": [1],
                                                         "sequences": [], "limitation": []}}
    s = L.score_decide(SET, payload)
    assert s["values_found"] == 2 and s["values_total"] == 2 and s["values_extra"] == 1
    assert s["every_kept"] == 1 and s["partial_carded"] == 1
    assert s["concept_cells"] == 8 and s["concept_correct"] == 7      # 2 truth concepts x 4 reports; contrast wrong in report 1
    assert s["disagreements_found"] == 1 and s["disagreements_total"] == 1
    assert s["polarity_correct"] == 1 and s["polarity_total"] == 1      # usual "not_given" -> condition "given"
    assert s["cards"] == 4 and s["over_budget"] is False and s["dropped_quotes"] == 2


def test_summarise_totals_by_kind():
    rows = [{"kind": "base", "values_found": 1, "values_total": 2, "cards": 3},
            {"kind": "base", "values_found": 2, "values_total": 2, "cards": 9},
            {"kind": "real", "values_found": 0, "values_total": 1, "cards": 1}]
    out = L.summarise(rows, ["values_found", "values_total", "cards"])
    assert out["base"] == {"n": 2, "values_found": 3, "values_total": 4, "cards": 12}
    assert out["real"]["n"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rules_step_lab.py -q`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the script** (`backend/src/rapid_reports_ai/scripts/rules_step_lab.py`)

```python
"""Rules-step lab (spec 2026-10-13-template-rules-step-design, "The lab for this spec"). Reported, not gated: it
prints tables and writes JSON under the private folder; Hassan decides.

    .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab decide --root <dir> [--run 1|2] [--only slug,...]
    .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab report --root <dir> --stage decide

<dir> is ~/Code/rr-template-conversion-private/synthetic/rules_step (never the repo). Sets: <dir>/sets/*.json (format
in the plan, Task 19). Outputs: <dir>/runs/<stage>/run<k>/<slug>.json and <dir>/REPORT_<stage>.md. The generator of
the synthetic sets (Claude) is never the model under test (Qwen, Jev)."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional


def _n(s: str) -> str:
    return " ".join((s or "").lower().split())


def load_sets(root: Path, only: Optional[List[str]] = None) -> List[dict]:
    sets = [json.loads(p.read_text()) for p in sorted((root / "sets").glob("*.json"))]
    return [s for s in sets if not only or s["slug"] in only]


def _value_names(truth_value: dict) -> set:
    return {_n(truth_value["name"]), *(_n(a) for a in truth_value.get("aliases") or [])}


def score_decide(s: dict, payload: dict) -> dict:
    """One set's decision-run result against its planted truth."""
    truth = s["truth"]
    n = len(s["examples"])
    cards = payload.get("cards", []) + payload.get("more", [])
    value_cards = {_n(c["key"]): c for c in cards + payload.get("kept", []) if c["id"].startswith("value:")}
    kept_ids = {c["id"] for c in payload.get("kept", [])}
    found = every_kept = partial_carded = 0
    matched = set()
    for v in truth.get("values", []):
        hit = next((k for k in value_cards if k in _value_names(v)), None)
        if hit is None:
            continue
        found += 1
        matched.add(hit)
        in_all = len(v["reports"]) == n
        every_kept += in_all and value_cards[hit]["id"] in kept_ids
        partial_carded += (not in_all) and value_cards[hit]["id"] not in kept_ids
    states = payload.get("states") or {}
    cells = correct = 0
    for name, t in truth.get("concepts", {}).items():
        said = set(states.get(name) or [])
        for k in range(1, n + 1):
            cells += 1
            correct += (k in said) == (k in set(t.get("stated_in") or []))
    # contrast polarity (D1): the stored condition is the opposite of the usual state the set was planted with
    from rapid_reports_ai import template_decisions as td
    pol_total = pol_ok = 0
    for name, t in truth.get("concepts", {}).items():
        card = next((c for c in cards if c.get("key") == name and c.get("wording")), None)
        if not t.get("usual_state") or card is None:
            continue
        pol_total += 1
        other = next(st for st in td.CONCEPTS[name].states if st != t["usual_state"])
        pol_ok += card["wording"].get("condition") == td.CONCEPTS[name].states[other]
    dis = {c["key"] for c in cards if c.get("kind") == "disagree"}
    return {"slug": s["slug"], "kind": s.get("kind", "base"), "values_found": found,
            "values_total": len(truth.get("values", [])), "values_extra": len(set(value_cards) - matched),
            "every_kept": every_kept, "partial_carded": partial_carded, "concept_cells": cells,
            "concept_correct": correct, "disagreements_found": len(dis & set(truth.get("disagreements", []))),
            "disagreements_total": len(truth.get("disagreements", [])), "polarity_correct": pol_ok,
            "polarity_total": pol_total, "cards": len(cards),
            "over_budget": len(cards) > 8, "dropped_quotes": (payload.get("run") or {}).get("dropped_quotes", 0)}


def summarise(rows: List[dict], fields: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for r in rows:
        agg = out.setdefault(r.get("kind", "base"), {"n": 0, **{f: 0 for f in fields}})
        agg["n"] += 1
        for f in fields:
            agg[f] += int(r.get(f) or 0)
    return out


async def _decide_one(s: dict) -> dict:
    from rapid_reports_ai import template_decision_run as tdr
    from rapid_reports_ai import template_rules_cards as trc
    run = await tdr.run_decisions(s["examples"], s.get("scan_type", ""))
    built = trc.build_cards(run, len(s["examples"]))
    return {**built, "ok": run.ok, "states": run.states, "run": tdr.evidence(run, built),
            "candidates": {"values": [v.model_dump() for v in run.values],
                           "concepts": [c.model_dump() for c in run.concepts]}}


async def decide(root: Path, run_no: int, only: Optional[List[str]]) -> None:
    out_dir = root / "runs" / "decide" / f"run{run_no}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in load_sets(root, only):
        payload = await _decide_one(s)
        payload["score"] = score_decide(s, payload)
        (out_dir / f"{s['slug']}.json").write_text(json.dumps(payload, indent=1))
        print(s["slug"], json.dumps(payload["score"]))


FIELDS = {"decide": ["values_found", "values_total", "values_extra", "every_kept", "partial_carded", "concept_cells",
                     "concept_correct", "disagreements_found", "disagreements_total", "polarity_correct", "polarity_total",
                     "cards", "dropped_quotes"]}


def report(root: Path, stage: str) -> str:
    lines = [f"# Rules-step lab: {stage}", ""]
    for run_dir in sorted((root / "runs" / stage).glob("run*")):
        rows = [json.loads(p.read_text())["score"] for p in sorted(run_dir.glob("*.json"))]
        lines += [f"## {run_dir.name}", "", "| slug | kind | " + " | ".join(FIELDS[stage]) + " |",
                  "|---|---|" + "---|" * len(FIELDS[stage])]
        lines += [f"| {r['slug']} | {r['kind']} | " + " | ".join(str(r.get(f)) for f in FIELDS[stage]) + " |"
                  for r in rows]
        lines += ["", "Totals by kind (synthetic and real reported apart):", ""]
        for kind, agg in summarise(rows, FIELDS[stage]).items():
            lines.append(f"- {kind}: " + ", ".join(f"{k} {v}" for k, v in agg.items()))
        lines.append("")
    text = "\n".join(lines)
    (root / f"REPORT_{stage}.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["decide", "report"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--stage", dest="report_stage", default="decide")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.stage == "decide":
        asyncio.run(decide(a.root, a.run, only))
    else:
        print(report(a.root, a.report_stage))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rules_step_lab.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/rules_step_lab.py backend/tests/test_rules_step_lab.py
git commit -m "feat(lab): Rules-step lab runner and decision-run scorer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

### Task 20 (controller-run): Synthetic example sets seeded from production

The controller (the session running this plan) runs this task, not an implementer subagent. The data goes only to `~/Code/rr-template-conversion-private/synthetic/rules_step/`. Nothing is committed to the repo.

- [ ] **Step 1: Make the folders and list the seeds**

```bash
mkdir -p ~/Code/rr-template-conversion-private/synthetic/rules_step/{sets,seeds,runs,answers}
cd ~/Code/rr-template-conversion-private && python3 -c "
import json; d=json.load(open('data_all.json'))['templates']
for t in d:
    if len(t.get('reports') or [])>=3: print(t['slug'], len(t['reports']), t.get('scan_type'))" | tee synthetic/rules_step/seeds/SEEDS.txt
```

Expected: 11 lines (the templates with 3 or more reports).

- [ ] **Step 2: Write the real held-out sets** (the 11 templates' own reports, `kind: "real"`, truth hand-labelled by a Claude subagent reading the reports and the curated sheet `final/<slug>.final.md`; reported apart from synthetic)

```bash
cd ~/Code/rr-template-conversion-private && python3 -c "
import json; d=json.load(open('data_all.json'))['templates']
for t in d:
    reps=[r.get('final_content') or r.get('report_content') or '' for r in (t.get('reports') or [])]
    reps=[r for r in reps if r.strip()]
    if len(reps)>=3:
        json.dump({'slug':t['slug']+'__real','seed':t['slug'],'kind':'real','scan_type':t.get('scan_type') or '',
                   'examples':reps[:6],'truth':None}, open(f'synthetic/rules_step/sets/{t[\"slug\"]}__real.json','w'), indent=1)
print('ok')"
```

Each report row has `final_content` (the radiologist's final report) and `report_content` (the generated one); the final is the example.

- [ ] **Step 3: Dispatch Opus subagents to generate the synthetic sets**

Dispatch one subagent per seed (11, in parallel, `model: "opus"`), each with this prompt (fill `<slug>`):

> You generate a synthetic test set for a lab of report-template creation. Read `~/Code/rr-template-conversion-private/data_all.json` (the template whose slug is `<slug>`: its `reports` and `skill_sheet`) and `~/Code/rr-template-conversion-private/final/<slug>.final.md` (the curated sheet). Write new example reports in the same radiologist's voice, section layout, headings, measurement style and modality. Never copy a sentence that holds patient details. Use no real names, dates of birth, hospital numbers or real dates. Write these files to `~/Code/rr-template-conversion-private/synthetic/rules_step/sets/`, each in the JSON format below:
> 1. `<slug>__base.json`: 5 reports, a realistic mix of normal and abnormal studies, with what the curated sheet expects.
> 2. Two variants. Pick the two of these that fit this scan type best, and do not reuse a variant another seed of the same modality already has: (a) `__value_partial`: a measured value stated in 4 of 6 reports; (b) `__contrast_split`: one report says the agent was given, another says none was given, worded differently; (c) `__patient_line`: a sentence repeated in 3 or more reports that would be false for some patients (for example a statement about previous imaging or about the patient's state); (d) `__priors`: 2 of 5 reports compare with a named previous study (with a date), the rest say there is none; (e) `__abnormal_only`: one structure mentioned only in the reports where it is abnormal; (f) `__near_duplicate`: 4 reports that differ only in numbers; (g) `__all_normal`: 4 all-normal reports.
> 3. `<slug>__no_contrast.json` (every seed, product decision D1): 5 reports of a protocol run without a contrast agent, where 4 reports say no agent was given and 1 says one was given, in this radiologist's wording. Here the usual wording is the no-agent one, so the template's default flips.
> Plant the ground truth and record it in `truth` exactly: every measured value with its report numbers and whether it should be in every report ("every") or only sometimes ("relevant"); for each study-level concept (comparison, contrast, sequences, limitation) the reports that state it, the usual wording in this set (`default`), the other wording (`when_met`) and the state the usual wording states (`usual_state`: for contrast `given` or `not_given`); the concepts whose wording differs across reports (`disagreements`); `patient_specific_fixed` sentences; `only_when_abnormal` structures with their paragraph name.
> JSON: `{"slug","seed","kind":"base"|"variant","scan_type","examples":[...],"truth":{"values":[{"name","aliases","reports","need"}],"concepts":{"<name>":{"stated_in","default","when_met","usual_state"}},"disagreements":[],"patient_specific_fixed":[],"only_when_abnormal":[{"paragraph","structure"}]}}`.
> Afterwards, note in `<slug>.notes.md` (same folder) how your set may be easier or cleaner than real reports. Report back only the file names you wrote.

- [ ] **Step 4: Label the real sets.** Dispatch one subagent (`model: "opus"`) to fill `truth` in each `__real.json` from the reports and the curated sheet, using the same truth schema. It changes nothing else.

- [ ] **Step 5: Hassan's spot-check.** Pick 5 sets at random (`ls sets | shuf -n 5`). Show Hassan one example report and the truth of each, and record his realism verdict in `synthetic/rules_step/SPOTCHECK.md`. If he rejects a set, regenerate it with his note added to the prompt. The lab goes on with the others.

### Task 21 (controller-run): Decision-run lab and report

- [ ] **Step 1: Two runs** (eval economy: 2 runs, outputs kept and reused)

```bash
cd backend && for k in 1 2; do .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab decide --root ~/Code/rr-template-conversion-private/synthetic/rules_step --run $k; done
.venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab report --root ~/Code/rr-template-conversion-private/synthetic/rules_step --stage decide
```

- [ ] **Step 2: Jev threshold table.** For each (example, concept) cell, compute Jev's raw score against the planted `stated_in`. Re-run `ask_states` with `STATES_MIN = 0` in a scratch script that prints the scores. Report the score distribution of stated and not-stated cells, and precision and recall at 0.3, 0.4, 0.5, 0.6 and 0.7.

- [ ] **Step 3: Answer the cards.** Dispatch one Claude subagent per set (`model: "opus"`), given the set's `truth` and its `runs/decide/run1/<slug>.json`, to answer every open card as the radiologist would. It writes `answers/<slug>.json` as `[{kind, key, choice}]`, plus the kept items' defaults. Hassan spot-checks 3 answer files.

- [ ] **Step 4: Write the report** in `synthetic/rules_step/REPORT_decide.md`. Cover: values found / extra / every-kept / partial-carded; concept accuracy per concept; disagreements found; cards per template against the ≤ 8 target; quotes dropped as unverifiable; run-to-run differences between run 1 and run 2; synthetic and real reported apart; how the synthetic sets may be easier than production (from the notes files). End with recommendations: the `STATES_MIN` value, prompt wording changes, and whether the card budget holds. Tell Hassan the report path and the recommendations. **He decides.** Phase 3 starts when he has seen it. If he changes `STATES_MIN` or the prompt, make that change as a one-line commit with its test updated.

---

# Phase 3: Rules-step cards in the creator and the refine panel

Outcome: the creator runs Paste → Rules → (writer) → Style → Test → Refine → Create. The refine panel shows the Required-values card and, the first time an existing template is opened, the decision run's cards. The answers go through `/apply-decisions` and the save function. Needs Phases 1 and 2. It ships without Phase 4, because the ledger already applies the decisions at save.

**Phase 1 review carry-over (must land in Phase 3):** the PUT (`_vet_config`) adds the `LEDGER_KEPT` notice ("use the card below") but returns no card, and `VetOutcome.ledger_unmatched` is not persisted. Phase 3 must persist `ledger_unmatched` with the template and surface those entries, and the PUT's kept-item cards, as cards in the refine panel.

### Task 22: Wire types and API client

**Files:**
- Create: `frontend/src/lib/template-rules/types.ts`
- Create: `frontend/src/lib/template-rules/api.ts`
- Test: `frontend/src/lib/template-rules/api.test.ts`

- [ ] **Step 1: Write the failing test** (`frontend/src/lib/template-rules/api.test.ts`)

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { postApplyDecisions, postDecide } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('template-rules api', () => {
	it('posts the decide request with the bearer token', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ success: true, ran: true, cards: [], more: [], kept: [], defaults: [], notice: '', run: {} })));
		vi.stubGlobal('fetch', fetchMock);
		const r = await postDecide('tok', { scan_type: 'CT', examples: [{ content: 'A.' }] });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/templates/skill-sheet/decide')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
		expect(JSON.parse(init.body as string).examples).toEqual([{ content: 'A.' }]);
		expect(r.ran).toBe(true);
	});

	it('posts apply-decisions and throws on an HTTP error', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { status: 500 })));
		await expect(postApplyDecisions(null, { skill_sheet: 's', decisions: [], changes: [], source: 'creation' })).rejects.toThrow('apply-decisions 500');
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project server src/lib/template-rules/api.test.ts`
Expected: FAIL (`Failed to resolve import "./api"`)

- [ ] **Step 3: Write the types** (`frontend/src/lib/template-rules/types.ts`)

```ts
// Wire types of the Rules step (backend: template_decisions, template_rules_cards, main /skill-sheet/decide,
// /apply-decisions, /sheet-checks). The sheet itself is never shown: cards speak in report behaviour.

export type LedgerKind = 'value' | 'concept' | 'fixed' | 'normal';
export type CardKind = 'value' | 'concept' | 'disagree' | 'fixed' | 'normal' | 'uncovered' | 'duplicate';
export type ChangeSource = 'creation' | 'first_use_review' | 'default';
export type Choice = Record<string, unknown>;

export interface Evidence {
	reports: number[];
	quote: string | null;
}

export interface CardChoice {
	id: string;
	label: string;
	choice: Choice | null; // null: the radiologist writes the wording
}

export interface DecisionCard {
	id: string;
	kind: CardKind;
	step: string;
	title: string;
	evidence: Evidence[];
	ledger_kind: LedgerKind;
	key: string;
	choices: CardChoice[];
	selected: string | null;
	rank: number;
	wording?: { default?: string; when_met?: string; condition?: string; text?: string };
	note?: string;
}

export interface LedgerEntry {
	kind: LedgerKind;
	key: string;
	choice: Choice;
	by: string;
	at: string;
	source: string;
}

export interface DecisionChange {
	kind: LedgerKind;
	key: string;
	choice: Choice;
	source?: ChangeSource;
}

export interface DecideResponse {
	success: boolean;
	ran: boolean;
	cards: DecisionCard[];
	more: DecisionCard[];
	kept: DecisionCard[];
	defaults: DecisionChange[];
	notice: string;
	run: Record<string, unknown>;
	error?: string;
}

export interface ApplyResponse {
	success: boolean;
	skill_sheet: string;
	decisions: LedgerEntry[];
	applied: { kind: string; key: string; action: string }[];
	unmatched: LedgerEntry[];
	stale_quotes: string[];
	error?: string;
}
```

- [ ] **Step 4: Write the client** (`frontend/src/lib/template-rules/api.ts`)

```ts
import { API_URL } from '$lib/config.js';
import type { ApplyResponse, DecideResponse, DecisionChange, LedgerEntry } from './types';

async function post<T>(token: string | null, path: string, body: unknown): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/templates/skill-sheet/${path}`, { method: 'POST', headers, body: JSON.stringify(body) });
	if (!res.ok) throw new Error(`skill-sheet ${path} ${res.status}`);
	return (await res.json()) as T;
}

export const postDecide = (
	token: string | null,
	body: { scan_type: string; examples: { label?: string | null; content: string }[]; template_id?: string | null }
) => post<DecideResponse>(token, 'decide', body);

export const postApplyDecisions = (
	token: string | null,
	body: { skill_sheet: string; decisions: LedgerEntry[]; changes: DecisionChange[]; source: 'creation' | 'first_use_review' }
) => post<ApplyResponse>(token, 'apply-decisions', body);
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run --project server src/lib/template-rules/api.test.ts`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/template-rules/types.ts frontend/src/lib/template-rules/api.ts frontend/src/lib/template-rules/api.test.ts
git commit -m "feat(template-rules): wire types and API client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 23: Pure card logic

**Files:**
- Create: `frontend/src/lib/template-rules/cards.ts`
- Test: `frontend/src/lib/template-rules/cards.test.ts`

- [ ] **Step 1: Write the failing test** (`frontend/src/lib/template-rules/cards.test.ts`)

```ts
import { describe, expect, it } from 'vitest';
import { changeFor, changesOnContinue, changesOnSkip, evidenceLine, validValueName } from './cards';
import type { DecisionCard } from './types';

const value = (name: string, selected: string | null = null): DecisionCard => ({
	id: `value:${name.toLowerCase()}`, kind: 'value', step: 'rules', title: name, evidence: [], ledger_kind: 'value', key: name,
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'relevant', label: 'Only when relevant', choice: { need: 'relevant' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected, rank: 1
});
const concept: DecisionCard = {
	id: 'concept:comparison', kind: 'concept', step: 'rules', title: 'Comparison with previous imaging', evidence: [],
	ledger_kind: 'concept', key: 'comparison', wording: { default: 'No previous imaging.', when_met: 'Compared with {date}.', condition: 'the dictation names a previous imaging study for comparison' },
	choices: [
		{ id: 'keep', label: 'Keep', choice: { use: true, default: 'No previous imaging.', when_met: 'Compared with {date}.' } },
		{ id: 'edit', label: 'Edit wording', choice: null },
		{ id: 'not_used', label: 'Not used', choice: { use: false, default: '', when_met: '' } }
	],
	selected: null, rank: 2
};

describe('template-rules cards', () => {
	it('words evidence as reports, never percentages', () => {
		expect(evidenceLine({ reports: [4, 1, 2], quote: 'ECV 28%' })).toBe("reports 1, 2, 4: 'ECV 28%'");
		expect(evidenceLine({ reports: [3], quote: null })).toBe('report 3: not stated');
	});

	it('records a tapped choice, and edited wording only when written', () => {
		expect(changeFor(value('ECV'), { choiceId: 'relevant' }, 'creation')).toEqual({ kind: 'value', key: 'ECV', choice: { need: 'relevant' }, source: 'creation' });
		expect(changeFor(concept, { choiceId: 'edit' }, 'creation')).toBeNull();
		expect(changeFor(concept, { choiceId: 'edit', edited: { default: ' None. ', when_met: '' } }, 'creation')).toEqual({
			kind: 'concept', key: 'comparison', choice: { use: true, default: 'None.', when_met: '', condition: 'the dictation names a previous imaging study for comparison' }, source: 'creation'
		});
	});

	it('Continue sends answers, kept defaults and added values; unanswered open cards send nothing', () => {
		const lvef = value('LVEF', 'every');
		const out = changesOnContinue([value('ECV'), concept], [lvef], { 'value:ecv': { choiceId: 'not_needed' } }, ['Heart rate'], 'creation');
		expect(out).toEqual([
			{ kind: 'value', key: 'ECV', choice: { need: 'not_needed' }, source: 'creation' },
			{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' },
			{ kind: 'value', key: 'Heart rate', choice: { need: 'every' }, source: 'creation' }
		]);
	});

	it('Skip records the defaults as defaults', () => {
		expect(changesOnSkip([{ kind: 'value', key: 'LVEF', choice: { need: 'every' } }])).toEqual([
			{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' }
		]);
	});

	it('accepts only short plain value names', () => {
		expect(validValueName('Heart rate')).toBe(true);
		expect(validValueName('a "b"')).toBe(false);
		expect(validValueName('one two three four five six seven eight nine')).toBe(false);
		expect(validValueName('  ')).toBe(false);
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project server src/lib/template-rules/cards.test.ts`
Expected: FAIL (`Failed to resolve import "./cards"`)

- [ ] **Step 3: Write the module** (`frontend/src/lib/template-rules/cards.ts`)

```ts
// Pure card logic of the Rules step (mirrors backend template_rules_cards): the evidence line, the ledger change an
// answer records, and the changes sent on Continue or Skip. Nothing seen in fewer than every example is pre-ticked;
// only tapped cards are the radiologist's ("creation" / "first_use_review"); kept items left alone are "default".
import type { ChangeSource, DecisionCard, DecisionChange, Evidence } from './types';

export interface Answer {
	choiceId: string;
	edited?: { default?: string; when_met?: string; text?: string };
}

export function evidenceLine(e: Evidence): string {
	const nums = [...new Set(e.reports)].sort((a, b) => a - b);
	const head = (nums.length === 1 ? 'report ' : 'reports ') + nums.join(', ');
	return `${head}: ${e.quote ? `'${e.quote}'` : 'not stated'}`;
}

/** The change an answer records; null when it needs wording the radiologist has not written. */
export function changeFor(card: DecisionCard, a: Answer, source: ChangeSource): DecisionChange | null {
	const c = card.choices.find((x) => x.id === a.choiceId);
	if (!c) return null;
	if (c.choice) return { kind: card.ledger_kind, key: card.key, choice: c.choice, source };
	if (!a.edited) return null;
	if (card.ledger_kind === 'concept') {
		const d = (a.edited.default ?? '').trim();
		const w = (a.edited.when_met ?? '').trim();
		if (!d && !w) return null;
		// the condition stays the card's: which wording is usual was decided from the examples (D1)
		const condition = card.wording?.condition ?? '';
		return { kind: 'concept', key: card.key, choice: { use: true, default: d, when_met: w, condition }, source };
	}
	const text = (a.edited.text ?? '').trim();
	return text ? { kind: card.ledger_kind, key: card.key, choice: { text }, source } : null;
}

/** A value name code can store: a few plain words, no quotes, bars, brackets or braces. */
export function validValueName(name: string): boolean {
	const n = name.trim();
	return n.length > 0 && n.split(/\s+/).length <= 8 && !/["|[\]{}]/.test(n);
}

/** Continue: every answered card (as `source`), the kept items left alone ("default"), and added values. */
export function changesOnContinue(
	open: DecisionCard[],
	kept: DecisionCard[],
	answers: Record<string, Answer>,
	added: string[],
	source: ChangeSource
): DecisionChange[] {
	const out: DecisionChange[] = [];
	for (const card of [...open, ...kept]) {
		const a = answers[card.id];
		const ch = a
			? changeFor(card, a, source)
			: kept.includes(card) && card.selected
				? changeFor(card, { choiceId: card.selected }, 'default')
				: null;
		if (ch) out.push(ch);
	}
	for (const name of added) out.push({ kind: 'value', key: name.trim(), choice: { need: 'every' }, source });
	return out;
}

/** Skip: the pre-ticked choices, recorded as defaults (never as confirmed). */
export function changesOnSkip(defaults: DecisionChange[]): DecisionChange[] {
	return defaults.map((d) => ({ ...d, source: 'default' as const }));
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run --project server src/lib/template-rules/cards.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/template-rules/cards.ts frontend/src/lib/template-rules/cards.test.ts
git commit -m "feat(template-rules): pure card logic (evidence line, answers to ledger changes)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 24: The `RulesStep` component

**Files:**
- Create: `frontend/src/lib/template-rules/RulesStep.svelte`
- Test: `frontend/src/lib/template-rules/RulesStep.svelte.test.ts`

- [ ] **Step 1: Write the failing test** (`frontend/src/lib/template-rules/RulesStep.svelte.test.ts`)

```ts
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import RulesStep from './RulesStep.svelte';
import type { DecisionCard } from './types';

const value = (name: string, selected: string | null = null, evidence = [{ reports: [1, 3], quote: `${name} 28%` }, { reports: [2], quote: null }]): DecisionCard => ({
	id: `value:${name.toLowerCase()}`, kind: 'value', step: 'rules', title: name, evidence, ledger_kind: 'value', key: name,
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'relevant', label: 'Only when relevant', choice: { need: 'relevant' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected, rank: 1
});
const concept = (): DecisionCard => ({
	id: 'concept:comparison', kind: 'concept', step: 'rules', title: 'Comparison with previous imaging',
	evidence: [{ reports: [1, 3], quote: 'No previous imaging.' }], ledger_kind: 'concept', key: 'comparison',
	wording: { default: 'No previous imaging.', when_met: '', condition: 'the dictation names a previous imaging study for comparison' },
	choices: [
		{ id: 'keep', label: 'Keep', choice: { use: true, default: 'No previous imaging.', when_met: '' } },
		{ id: 'edit', label: 'Edit wording', choice: null },
		{ id: 'not_used', label: 'Not used', choice: { use: false, default: '', when_met: '' } }
	],
	selected: null, rank: 2
});

describe('RulesStep', () => {
	it('shows evidence as reports, a three-way value chip, nothing pre-ticked for a partial value', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [value('ECV')], kept: [value('LVEF', 'every', [{ reports: [1, 2, 3], quote: 'LVEF 55%' }])], onContinue });
		await expect.element(page.getByText("reports 1, 3: 'ECV 28%'")).toBeInTheDocument();
		await expect.element(page.getByText('report 2: not stated')).toBeInTheDocument();
		const relevant = page.getByRole('button', { name: 'ECV: Only when relevant' });
		await expect.element(relevant).toHaveAttribute('aria-pressed', 'false');
		await relevant.click();
		await expect.element(relevant).toHaveAttribute('aria-pressed', 'true');
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([
			{ kind: 'value', key: 'ECV', choice: { need: 'relevant' }, source: 'creation' },
			{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' }
		]);
	});

	it('folds agreed items into a collapsed Kept as-is list; Change brings one back as a card', async () => {
		render(RulesStep, { cards: [], kept: [value('LVEF', 'every')], onContinue: vi.fn() });
		await expect.element(page.getByText('LVEF: Every report')).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Kept as-is (1)' }).click();
		await expect.element(page.getByText('LVEF: Every report')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Change LVEF' }).click();
		await expect.element(page.getByRole('button', { name: 'LVEF: Every report' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('keeps cards over the budget under a collapsed More decisions', async () => {
		render(RulesStep, { cards: [value('A')], more: [value('B'), value('C')], onContinue: vi.fn() });
		await expect.element(page.getByRole('button', { name: 'B: Every report' })).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'More decisions (2)' }).click();
		await expect.element(page.getByRole('button', { name: 'B: Every report' })).toBeInTheDocument();
	});

	it('Edit wording opens the wording fields and records the written wording', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [concept()], onContinue });
		await expect.element(page.getByText('Usually: “No previous imaging.”')).toBeInTheDocument();
		await expect.element(page.getByText('Left out when the dictation names a previous imaging study for comparison.')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Comparison with previous imaging: Edit wording' }).click();
		await userEvent.fill(page.getByLabelText('When it applies'), 'Compared with the {study} of {date}.');
		await page.getByRole('button', { name: 'Use this wording' }).click();
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'concept', key: 'comparison', source: 'creation',
			choice: { use: true, default: 'No previous imaging.', when_met: 'Compared with the {study} of {date}.', condition: 'the dictation names a previous imaging study for comparison' } }]);
	});

	it('adds a required value', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [value('ECV')], onContinue });
		await userEvent.fill(page.getByLabelText('Add a value'), 'Heart rate');
		await page.getByRole('button', { name: '+ Add' }).click();
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'value', key: 'Heart rate', choice: { need: 'every' }, source: 'creation' }]);
	});

	it('Skip records the defaults; review mode records first-use answers and has no Skip', async () => {
		const onSkip = vi.fn();
		const { unmount } = render(RulesStep, { cards: [], defaults: [{ kind: 'value', key: 'LVEF', choice: { need: 'every' } }], onContinue: vi.fn(), onSkip });
		await page.getByRole('button', { name: 'Skip' }).click();
		expect(onSkip).toHaveBeenCalledWith([{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' }]);
		unmount();
		const onContinue = vi.fn();
		render(RulesStep, { cards: [value('LVEF', 'every')], mode: 'review', onContinue });
		await expect.element(page.getByRole('button', { name: 'Skip' })).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'LVEF: Not needed' }).click();
		await page.getByRole('button', { name: 'Apply' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'value', key: 'LVEF', choice: { need: 'not_needed' }, source: 'first_use_review' }]);
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project client src/lib/template-rules/RulesStep.svelte.test.ts`
Expected: FAIL (`Failed to resolve import "./RulesStep.svelte"`)

- [ ] **Step 3: Write the component** (`frontend/src/lib/template-rules/RulesStep.svelte`)

```svelte
<script lang="ts">
	/**
	 * The Rules step (spec 2026-10-13-template-rules-step-design, "Cards"): exceptions only, quoted evidence, about 8
	 * decisions; the rest under "More decisions"; items every example agrees on folded into "Kept as-is". No
	 * "confirm all". Continue sends the answers (plus the kept defaults); Skip records the pre-ticked defaults.
	 * Used by the creator (mode "create") and the refine panel's first-use review (mode "review").
	 */
	import { changeFor, changesOnContinue, changesOnSkip, evidenceLine, validValueName, type Answer } from './cards';
	import type { DecisionCard, DecisionChange } from './types';

	let {
		cards,
		more = [],
		kept = [],
		defaults = [],
		notice = '',
		mode = 'create',
		busy = false,
		onContinue,
		onSkip
	}: {
		cards: DecisionCard[];
		more?: DecisionCard[];
		kept?: DecisionCard[];
		defaults?: DecisionChange[];
		notice?: string;
		mode?: 'create' | 'review';
		busy?: boolean;
		onContinue: (changes: DecisionChange[]) => void;
		onSkip?: (changes: DecisionChange[]) => void;
	} = $props();

	let answers = $state<Record<string, Answer>>({});
	let editing = $state<string | null>(null);
	let draft = $state<{ default?: string; when_met?: string; text?: string }>({});
	let showMore = $state(false);
	let showKept = $state(false);
	let promoted = $state<string[]>([]);
	let added = $state<string[]>([]);
	let newValue = $state('');

	const source = $derived(mode === 'review' ? 'first_use_review' : 'creation');
	const keptLeft = $derived(kept.filter((c) => !promoted.includes(c.id)));
	const openCards = $derived([...cards, ...kept.filter((c) => promoted.includes(c.id))]);
	const valueCards = $derived(openCards.filter((c) => c.kind === 'value'));
	const otherCards = $derived(openCards.filter((c) => c.kind !== 'value'));

	function selectedOf(c: DecisionCard): string | null {
		return answers[c.id]?.choiceId ?? c.selected;
	}

	function choose(c: DecisionCard, choiceId: string) {
		const ch = c.choices.find((x) => x.id === choiceId);
		if (ch && ch.choice === null) {
			editing = c.id;
			draft = { ...(c.wording ?? {}) };
			return;
		}
		answers = { ...answers, [c.id]: { choiceId } };
		if (editing === c.id) editing = null;
	}

	function useWording(c: DecisionCard, choiceId: string) {
		const a: Answer = { choiceId, edited: { ...draft } };
		if (!changeFor(c, a, source)) return;
		answers = { ...answers, [c.id]: a };
		editing = null;
	}

	function addValue() {
		const n = newValue.trim();
		if (!validValueName(n) || added.some((x) => x.toLowerCase() === n.toLowerCase())) return;
		added = [...added, n];
		newValue = '';
	}

	function finish() {
		onContinue(changesOnContinue([...cards, ...more], kept, answers, added, source));
	}
</script>

{#snippet chips(c: DecisionCard)}
	<div class="flex flex-wrap gap-1.5">
		{#each c.choices as ch (ch.id)}
			<button
				type="button"
				class="text-xs px-2.5 py-1 rounded-full border transition-colors {selectedOf(c) === ch.id ? 'border-purple-400 bg-purple-500/20 text-white' : 'border-white/10 text-gray-400 hover:text-gray-200'}"
				aria-pressed={selectedOf(c) === ch.id}
				aria-label="{c.title}: {ch.label}"
				onclick={() => choose(c, ch.id)}
				disabled={busy}>{ch.label}</button
			>
		{/each}
	</div>
{/snippet}

{#snippet evidence(c: DecisionCard)}
	{#each c.evidence as e, i (i)}
		<p class="text-xs text-gray-500">{evidenceLine(e)}</p>
	{/each}
{/snippet}

{#snippet card(c: DecisionCard)}
	<section class="rounded-lg border border-white/10 p-3 space-y-2" aria-label={c.title}>
		<h4 class="text-sm text-gray-200">{c.title}</h4>
		{@render evidence(c)}
		{#if c.wording && c.kind === 'concept'}
			{#if c.wording.default}<p class="text-xs text-gray-300">Usually: “{c.wording.default}”</p>{/if}
			{#if c.wording.when_met}
				<p class="text-xs text-gray-300">When {c.wording.condition || 'it applies'}: “{c.wording.when_met}”</p>
			{:else if c.wording.default && c.wording.condition}
				<p class="text-xs text-gray-400">Left out when {c.wording.condition}.</p>
			{/if}
		{/if}
		{@render chips(c)}
		{#if editing === c.id}
			{@const editChoice = c.choices.find((x) => x.choice === null)?.id ?? 'edit'}
			<div class="space-y-1.5">
				{#if c.ledger_kind === 'concept'}
					<label class="block text-xs text-gray-400">Usually
						<input class="input w-full text-sm" bind:value={draft.default} />
					</label>
					<label class="block text-xs text-gray-400">When it applies
						<input class="input w-full text-sm" bind:value={draft.when_met} />
					</label>
				{:else}
					<label class="block text-xs text-gray-400">Wording
						<input class="input w-full text-sm" bind:value={draft.text} />
					</label>
				{/if}
				<button type="button" class="btn-primary text-xs" onclick={() => useWording(c, editChoice)}>Use this wording</button>
			</div>
		{/if}
	</section>
{/snippet}

<div class="space-y-3">
	{#if notice}<p class="text-xs text-amber-300/80">{notice}</p>{/if}

	{#if valueCards.length || mode === 'review' || added.length}
		<section class="rounded-lg border border-white/10 p-3 space-y-3" aria-label="Required values">
			<h4 class="text-sm text-gray-200">Required values</h4>
			{#each valueCards as c (c.id)}
				<div class="space-y-1">
					<p class="text-sm text-gray-300">{c.title}</p>
					{@render evidence(c)}
					{@render chips(c)}
				</div>
			{/each}
			{#each added as name (name)}
				<p class="text-sm text-gray-300">{name} <span class="text-xs text-gray-500">(every report)</span></p>
			{/each}
			<div class="flex gap-2">
				<input class="input flex-1 text-sm" placeholder="Add a value" aria-label="Add a value" bind:value={newValue}
					onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addValue(); } }} />
				<button type="button" class="btn-ghost text-xs" onclick={addValue} disabled={!validValueName(newValue)}>+ Add</button>
			</div>
		</section>
	{/if}

	{#each otherCards as c (c.id)}
		{@render card(c)}
	{/each}

	{#if more.length}
		<button type="button" class="text-xs text-gray-400 hover:text-gray-200" aria-expanded={showMore} onclick={() => (showMore = !showMore)}>
			More decisions ({more.length})
		</button>
		{#if showMore}
			{#each more as c (c.id)}
				{@render card(c)}
			{/each}
		{/if}
	{/if}

	{#if keptLeft.length}
		<button type="button" class="text-xs text-gray-400 hover:text-gray-200" aria-expanded={showKept} onclick={() => (showKept = !showKept)}>
			Kept as-is ({keptLeft.length})
		</button>
		{#if showKept}
			<ul class="space-y-1">
				{#each keptLeft as c (c.id)}
					<li class="flex items-center justify-between text-xs text-gray-400">
						<span>{c.title}: {c.choices.find((x) => x.id === c.selected)?.label}</span>
						<button type="button" class="text-gray-500 hover:text-gray-200" aria-label="Change {c.title}"
							onclick={() => (promoted = [...promoted, c.id])}>Change</button>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}

	<div class="flex justify-end gap-2 pt-2">
		{#if onSkip}
			<button type="button" class="btn-ghost text-sm" onclick={() => onSkip?.(changesOnSkip(defaults))} disabled={busy}>Skip</button>
		{/if}
		<button type="button" class="btn-primary text-sm" onclick={finish} disabled={busy}>
			{mode === 'review' ? 'Apply' : 'Continue'}
		</button>
	</div>
</div>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run --project client src/lib/template-rules/RulesStep.svelte.test.ts`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/template-rules/RulesStep.svelte frontend/src/lib/template-rules/RulesStep.svelte.test.ts
git commit -m "feat(template-rules): RulesStep cards (value chips, wording, kept list, budget, skip)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 25: The creator: Rules in place of Questions; decisions through analyze, refine and save

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte`

This component has no unit test of its own (it is too large to mount without the app shell). Its new logic sits in the tested `RulesStep` and `cards.ts`. This task is checked by svelte-check and by the manual run in Step 3.

- [ ] **Step 1: Make these exact replacements** (each `old` text occurs exactly once)


1. The chat-state comment no longer mentions the questions stage. Replace

```svelte
	 * Chat state shared between the questions stage (Q&A) and the refine stage.
	 * Refine-stage turns carry verification-loop metadata on both the user and
	 * assistant halves; questions-stage turns only carry {role, content}.
```

with

```svelte
	 * Chat state of the refine stage. Refine-stage turns carry verification-loop
	 * metadata on both the user and assistant halves.
```

2. Imports: add the Rules-step component and API after the `ImpressionFlow` import. Replace

```svelte
	import ImpressionFlow from './skill-sheet-summary/ImpressionFlow.svelte';
```

with

```svelte
	import ImpressionFlow from './skill-sheet-summary/ImpressionFlow.svelte';
	import RulesStep from '$lib/template-rules/RulesStep.svelte';
	import { postDecide } from '$lib/template-rules/api';
```

3. Replace the questions state with the Rules-step state. Replace

```svelte
	// Questions — unified model: each Q has question, suggestions, and a status
	/** @type {{ question: string, suggestions: string[], status: 'pending'|'answered'|'skipped', answer: string }[]} */
	let questions = [];
	let activeQuestionIdx = -1; // which Q has the custom input open
```

with

```svelte
	// Rules step (spec 2026-10-13-template-rules-step-design): the decision run's cards, answered before the writer
	// runs; the answers become the decision ledger, applied by code on every save.
	/** @type {import('$lib/template-rules/types').DecideResponse | null} */
	let rules = null;
	let rulesLoading = false;
	let rulesNotice = '';
	/** @type {Record<string, unknown>} */
	let rulesRecord = {};
	/** @type {import('$lib/template-rules/types').LedgerEntry[]} */
	let decisions = [];
	/** @type {import('$lib/template-rules/types').DecisionChange[]} */
	let lastChanges = [];
	const NO_PRECHECK = "We couldn't pre-check your rules; review them on the Style step.";
```

4. Phase and stage types. Replace

```svelte
	let phase = /** @type {1|2} */ (1);
	/** @type {'summary'|'questions'|'test'|'refine'} */
```

with

```svelte
	let phase = /** @type {1|'rules'|2} */ (1);
	/** @type {'summary'|'test'|'refine'} */
```

5. Stages: Style → Test → Refine (the Rules step comes before the writer, as its own phase). Replace

```svelte
	const stageOrder = /** @type {const} */ (['summary', 'questions', 'test', 'refine']);
	const stageLabels = { summary: 'Style', questions: 'Questions', test: 'Test', refine: 'Refine' };
	const stageDescriptions = {
		summary: "Here's what we learned from your reports",
		questions: 'We have a few questions to fine-tune your template',
```

with

```svelte
	const stageOrder = /** @type {const} */ (['summary', 'test', 'refine']);
	const stageLabels = { summary: 'Style', test: 'Test', refine: 'Refine' };
	const stageDescriptions = {
		summary: "Here's what we learned from your reports",
```

6. Drop the question counters. Replace

```svelte
	$: pendingCount = questions.filter(q => q.status === 'pending').length;
	$: allQuestionsResolved = questions.length > 0 && pendingCount === 0;
```

with

nothing (delete it).

7. `analyzeExamples` runs the decision run first; `buildTemplate` runs the writer with the answers. Replace

```svelte
	async function analyzeExamples() {
		error = '';
		const filled = examples.filter((e) => e.content.trim());
		if (filled.length < 3) { error = 'Please provide at least 3 example reports.'; return; }
		loading = true;
		try {
			const data = await postJson('/api/templates/skill-sheet/analyze', {
				scan_type: scanType,
				protocol_notes: protocolNotes.trim(),
				examples: filled
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			analyserVersion = data.analyser_version || '';
			sheetNotice = typeof data.notice === 'string' ? data.notice : '';
			summary = (typeof data.summary === 'object' && data.summary !== null) ? data.summary : null;
			sampleFindings = coerceToText(data.sample_findings);
			sampleClinicalHistory = coerceToText(data.sample_clinical_history);
			testFindings = sampleFindings;
			testClinicalHistory = sampleClinicalHistory;
			questions = (data.questions || []).slice(0, 3).map(q => ({
				question: q.question,
				suggestions: q.suggestions || [],
				status: /** @type {'pending'} */ ('pending'),
				answer: ''
			}));
			activeQuestionIdx = -1;
			chatHistory = [];
```

with

```svelte
	async function analyzeExamples() {
		error = '';
		const filled = examples.filter((e) => e.content.trim());
		if (filled.length < 3) { error = 'Please provide at least 3 example reports.'; return; }
		rules = null; rulesNotice = ''; rulesRecord = {};
		phase = 'rules';
		rulesLoading = true;
		let notice = '';
		try {
			rules = await postDecide($token, { scan_type: scanType, examples: filled });
			if (!rules.success) rules = null;
			notice = rules?.notice || '';
		} catch (e) {
			rules = null;
			notice = NO_PRECHECK;
		} finally { rulesLoading = false; }
		rulesRecord = rules?.run ?? {};
		// nothing to ask (or the run failed): straight on to the writer, which infers rules as before
		if (!rules || (!rules.cards.length && !rules.more.length && !rules.kept.length)) {
			rulesNotice = notice;
			await buildTemplate(rules?.defaults ?? []);
		}
	}

	/** @param {import('$lib/template-rules/types').DecisionChange[]} changes */
	async function buildTemplate(changes) {
		error = '';
		lastChanges = changes;
		const filled = examples.filter((e) => e.content.trim());
		loading = true;
		try {
			const data = await postJson('/api/templates/skill-sheet/analyze', {
				scan_type: scanType,
				protocol_notes: protocolNotes.trim(),
				examples: filled,
				changes
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			decisions = Array.isArray(data.decisions) ? data.decisions : [];
			analyserVersion = data.analyser_version || '';
			sheetNotice = [rulesNotice, typeof data.notice === 'string' ? data.notice : ''].filter(Boolean).join(' ');
			summary = (typeof data.summary === 'object' && data.summary !== null) ? data.summary : null;
			sampleFindings = coerceToText(data.sample_findings);
			sampleClinicalHistory = coerceToText(data.sample_clinical_history);
			testFindings = sampleFindings;
			testClinicalHistory = sampleClinicalHistory;
			chatHistory = [];
```

8. `sendAnswer`: no question bookkeeping. Replace

```svelte
		let fullMsg = msg;

		// If answering a specific question, mark it
		if (activeQuestionIdx >= 0 && questions[activeQuestionIdx]) {
			const q = questions[activeQuestionIdx];
			fullMsg = `Q: ${q.question}\nA: ${msg}`;
			questions[activeQuestionIdx] = { ...q, status: 'answered', answer: msg };
			questions = questions; // trigger reactivity
			activeQuestionIdx = -1;
		}
```

with

```svelte
		const fullMsg = msg;
```

9. `sendAnswer`: the refine call carries the ledger and takes back the updated one. Replace

```svelte
				chat_history: toWireChatHistory(chatHistory.slice(0, -1)),
				rejection_context: rejectionContext
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
```

with

```svelte
				chat_history: toWireChatHistory(chatHistory.slice(0, -1)),
				rejection_context: rejectionContext,
				decisions
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			if (Array.isArray(data.decisions)) decisions = data.decisions;
```

10. Drop the question handlers. Replace

```svelte
	function clickSuggestion(/** @type {number} */ qIdx, /** @type {string} */ suggestion) {
		activeQuestionIdx = qIdx; sendAnswer(suggestion);
	}
	function openCustomAnswer(/** @type {number} */ qIdx) { activeQuestionIdx = qIdx; chatInput = ''; }
	function skipQuestion(/** @type {number} */ qIdx) {
		questions[qIdx] = { ...questions[qIdx], status: 'skipped', answer: '' };
		questions = questions;
	}
	function unskipQuestion(/** @type {number} */ qIdx) {
		questions[qIdx] = { ...questions[qIdx], status: 'pending', answer: '' };
		questions = questions;
	}
	function skipAllQuestions() {
		questions = questions.map(q => q.status === 'pending' ? { ...q, status: 'skipped' } : q);
		goToStage('test');
	}
```

with

nothing (delete it).

11. Save: the ledger and the decision-run record go with the template. Replace

```svelte
				analyser_version: analyserVersion,
				examples: examples.filter((e) => e.content.trim()),
```

with

```svelte
				analyser_version: analyserVersion,
				decisions,
				rules_step: rulesRecord,
				examples: examples.filter((e) => e.content.trim()),
```

12. Markup: the Rules phase, before the workbench. Replace

```svelte
<!-- ── Phase 2: Workbench ──────────────────────────────────────────────── -->
{:else if phase === 2}
```

with

```svelte
<!-- ── Rules step: decisions before the sheet ────────────────────────── -->
{:else if phase === 'rules'}
	<div class="max-w-2xl mx-auto py-6 space-y-4">
		<div class="flex items-center justify-between">
			<button class="text-xs text-gray-500 hover:text-gray-300 transition-colors" on:click={() => { phase = 1; }} disabled={loading}>&larr; Reports</button>
			<span class="text-xs font-medium text-gray-400 uppercase tracking-wider truncate ml-2">{scanType}</span>
		</div>
		<h3 class="text-lg text-white">Check your rules</h3>
		{#if rulesLoading}
			<p class="text-sm text-gray-400 flex items-center gap-2"><span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>Checking your examples…</p>
		{:else if loading}
			<p class="text-sm text-gray-400 flex items-center gap-2"><span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>Building your template…</p>
		{:else if error}
			<p class="text-sm text-red-400">{error}</p>
			<button class="btn-primary text-sm" on:click={() => buildTemplate(lastChanges)}>Try again</button>
		{:else if rules}
			<RulesStep cards={rules.cards} more={rules.more} kept={rules.kept} defaults={rules.defaults}
				notice={rules.notice} busy={loading} onContinue={buildTemplate} onSkip={buildTemplate} />
		{/if}
	</div>

<!-- ── Phase 2: Workbench ──────────────────────────────────────────────── -->
{:else if phase === 2}
```

13. Markup: the refine stage no longer lists answered questions. Replace

```svelte
							<!-- Answered questions (compact) -->
							{#if questions.some(q => q.status === 'answered')}
								<div class="space-y-1.5 pb-3 mb-3 border-b border-white/[0.06]">
									{#each questions.filter(q => q.status === 'answered') as aq}
										<div class="flex items-start gap-2 text-xs">
											<svg class="w-3 h-3 text-emerald-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" /></svg>
											<span class="text-gray-500 truncate flex-1">{aq.question}</span>
											<span class="text-gray-300 shrink-0">{aq.answer}</span>
										</div>
									{/each}
								</div>
							{/if}
```

with

nothing (delete it).

14. A rejected refine turn restores the ledger with the sheet (typedef). Replace

```svelte
	 *   preMutationSkillSheet?: string | null,
```

with

```svelte
	 *   preMutationSkillSheet?: string | null,
	 *   preMutationDecisions?: any[] | null,
```

15. A rejected refine turn restores the ledger with the sheet (snapshot). Replace

```svelte
		const preMutationSkillSheet = isRefineTurn ? skillSheet : null;
```

with

```svelte
		const preMutationSkillSheet = isRefineTurn ? skillSheet : null;
		const preMutationDecisions = isRefineTurn ? decisions : null;
```

16. A rejected refine turn restores the ledger with the sheet (kept on the turn). Replace

```svelte
						preMutationSkillSheet,
```

with

```svelte
						preMutationSkillSheet,
						preMutationDecisions,
```

17. A rejected refine turn restores the ledger with the sheet (restore). Replace

```svelte
		if (typeof target.preMutationSkillSheet === 'string') {
			skillSheet = target.preMutationSkillSheet;
		}
```

with

```svelte
		if (typeof target.preMutationSkillSheet === 'string') {
			skillSheet = target.preMutationSkillSheet;
		}
		if (Array.isArray(target.preMutationDecisions)) decisions = target.preMutationDecisions;
```

18. Markup: delete the Questions stage, from the line `				<!-- STAGE: Questions -->` up to, not including, the line `				<!-- STAGE: Test -->`.


- [ ] **Step 2: Check nothing still refers to the questions**

Run: `cd frontend && grep -n "questions\|activeQuestionIdx\|pendingCount\|allQuestionsResolved" src/routes/components/SkillSheetCreator.svelte`
Expected: no output

Run: `cd frontend && npm run check 2>&1 | tail -3`
Expected: the error count is at or below the baseline (1194 problems; the scratch run of this plan gave 1193 errors). No new error in `SkillSheetCreator.svelte` or `src/lib/template-rules/`.

- [ ] **Step 3: Manual run** (backend and frontend dev servers, a dev account). Paste 3 example reports and press "Analyse my style". Check: "Checking your examples…", then the Rules cards (or straight to "Building your template…" when there is nothing to ask). Continue → Style. Ask the Refine chat something → the request carries `decisions` (devtools Network tab). Create → the saved template's `template_config.decisions` is set. Record what you saw in the task report.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte
git commit -m "feat(creator): the Rules step replaces Questions; decisions flow through analyze, refine and save

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 26: The refine panel: Required values, first-use review, decisions on refine and save

**Files:**
- Modify: `frontend/src/routes/components/TemplateRefinePanel.svelte`
- Test: `frontend/src/routes/components/TemplateRefinePanel.rules.svelte.test.ts`

- [ ] **Step 1: Write the failing test** (`frontend/src/routes/components/TemplateRefinePanel.rules.svelte.test.ts`)

```ts
// The refine panel's rules review: Required values (and the first-use decision run) applied through the ledger.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import TemplateRefinePanel from './TemplateRefinePanel.svelte';

const card = {
	id: 'value:lvef', kind: 'value', step: 'review', title: 'LVEF', evidence: [], ledger_kind: 'value', key: 'LVEF',
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'relevant', label: 'Only when relevant', choice: { need: 'relevant' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected: 'every', rank: 1
};
const template = { id: 't1', name: 'Cardiac', tags: [], template_config: { generation_mode: 'skill_sheet_guided', skill_sheet: 'SHEET', scan_type: 'MR' } };

afterEach(() => vi.unstubAllGlobals());

function routes(calls: { url: string; body: any; method: string }[]) {
	return vi.fn(async (url: string, init: RequestInit) => {
		const body = init?.body ? JSON.parse(init.body as string) : null;
		calls.push({ url, body, method: init?.method ?? 'GET' });
		if (url.endsWith('/skill-sheet/decide')) return new Response(JSON.stringify({ success: true, ran: false, cards: [card], more: [], kept: [], defaults: [], notice: '', run: {} }));
		if (url.endsWith('/skill-sheet/apply-decisions')) return new Response(JSON.stringify({ success: true, skill_sheet: 'SHEET2', decisions: [{ kind: 'value', key: 'LVEF', choice: { need: 'not_needed' }, by: 'radiologist', at: 't', source: 'first_use_review' }], applied: [], unmatched: [], stale_quotes: [] }));
		if (url.endsWith('/api/templates/t1')) return new Response(JSON.stringify({ success: true, template: { ...template, template_config: { ...template.template_config, skill_sheet: 'SHEET2' } } }));
		return new Response(JSON.stringify({ success: true, templates: [] }));
	});
}

describe('TemplateRefinePanel rules review', () => {
	it('shows Required values, applies a change through the ledger and saves the ledger', async () => {
		const calls: { url: string; body: any; method: string }[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await expect.element(page.getByText("Your template's rules")).toBeInTheDocument();
		await page.getByText("Your template's rules").click();
		await page.getByRole('button', { name: 'LVEF: Not needed' }).click();
		await page.getByRole('button', { name: 'Apply' }).click();
		await expect.element(page.getByText('Rules updated. Save to apply them to future reports.')).toBeInTheDocument();
		const apply = calls.find((c) => c.url.endsWith('/apply-decisions'))!;
		expect(apply.body).toMatchObject({ skill_sheet: 'SHEET', source: 'first_use_review',
			changes: [{ kind: 'value', key: 'LVEF', choice: { need: 'not_needed' }, source: 'first_use_review' }] });
		await page.getByRole('button', { name: 'Save' }).click();
		await vi.waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
		const put = calls.find((c) => c.method === 'PUT')!;
		expect(put.body.template_config.skill_sheet).toBe('SHEET2');
		expect(put.body.template_config.decisions[0]).toMatchObject({ key: 'LVEF', choice: { need: 'not_needed' } });
	});

	it('works without the review when the decide call fails', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { status: 500 })));
		render(TemplateRefinePanel, { template });
		await expect.element(page.getByText('Tell me what to change', { exact: false })).toBeInTheDocument();
		await expect.element(page.getByText("Your template's rules")).not.toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project client src/routes/components/TemplateRefinePanel.rules.svelte.test.ts`
Expected: FAIL (no "Your template's rules")

- [ ] **Step 3: Make these exact replacements in `TemplateRefinePanel.svelte`**


1. Imports. Replace

```svelte
	import { templatesStore } from '$lib/stores/templates';
```

with

```svelte
	import { templatesStore } from '$lib/stores/templates';
	import RulesStep from '$lib/template-rules/RulesStep.svelte';
	import { postApplyDecisions, postDecide } from '$lib/template-rules/api';
```

2. State: the ledger, the decision-run record and the review. Replace

```svelte
	let hasChanges = false;
	let chatScrollEl = null;
```

with

```svelte
	let hasChanges = false;
	let chatScrollEl = null;
	/** @type {import('$lib/template-rules/types').LedgerEntry[]} */
	let decisions = [];
	/** @type {Record<string, unknown> | null} */
	let rulesStep = null;
	/** @type {import('$lib/template-rules/types').DecideResponse | null} */
	let review = null;
	let reviewLoading = false;
	let reviewBusy = false;
	let reviewDone = false;
```

3. Opening a template loads its ledger and its review (Required values; the first-use decision run). Replace

```svelte
	$: if (template) {
		skillSheet = template.template_config?.skill_sheet || '';
		chatHistory = [];
		hasChanges = false;
		error = '';
	}
```

with

```svelte
	$: if (template) {
		skillSheet = template.template_config?.skill_sheet || '';
		decisions = Array.isArray(template.template_config?.decisions) ? template.template_config.decisions : [];
		rulesStep = template.template_config?.rules_step ?? null;
		chatHistory = [];
		hasChanges = false;
		error = '';
		reviewDone = false;
		loadReview(template);
	}

	/** The Required-values card, plus the first-use decision run when the template has never been reviewed. */
	async function loadReview(/** @type {any} */ t) {
		review = null;
		if (!t?.id) return;
		reviewLoading = true;
		try {
			const r = await postDecide($token, { scan_type: t.template_config?.scan_type || '', examples: [], template_id: t.id });
			if (r.success && t === template) review = r;
		} catch (e) {
			review = null;   // fail-soft: the panel works without the review
		} finally {
			reviewLoading = false;
		}
	}

	async function applyReview(/** @type {import('$lib/template-rules/types').DecisionChange[]} */ changes) {
		if (!changes.length) { reviewDone = true; return; }
		reviewBusy = true;
		error = '';
		try {
			const r = await postApplyDecisions($token, { skill_sheet: skillSheet, decisions, changes, source: 'first_use_review' });
			if (!r.success) throw new Error(r.error || 'Could not apply that choice');
			skillSheet = r.skill_sheet;
			decisions = r.decisions;
			if (review?.ran) rulesStep = { ...(review.run ?? {}), reviewed_at: new Date().toISOString() };
			hasChanges = true;
			reviewDone = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			reviewBusy = false;
		}
	}
```

4. The refine call carries the ledger and takes back the updated one. Replace

```svelte
				chat_history: toWireChatHistory(chatHistory.slice(0, -1)),
				template_id: template?.id ?? null
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
```

with

```svelte
				chat_history: toWireChatHistory(chatHistory.slice(0, -1)),
				template_id: template?.id ?? null,
				decisions
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			if (Array.isArray(data.decisions)) decisions = data.decisions;
```

5. Save sends the ledger and the review record. Replace

```svelte
			const updatedConfig = { ...template.template_config, skill_sheet: skillSheet };
```

with

```svelte
			const updatedConfig = { ...template.template_config, skill_sheet: skillSheet, decisions,
				...(rulesStep ? { rules_step: rulesStep } : {}) };
```

6. After a save, continue from the stored ledger. Replace

```svelte
			skillSheet = data.template?.template_config?.skill_sheet ?? skillSheet;
```

with

```svelte
			skillSheet = data.template?.template_config?.skill_sheet ?? skillSheet;
			decisions = data.template?.template_config?.decisions ?? decisions;
```

7. Markup: the review sits above the chat. Replace

```svelte
		<div class="flex-1 overflow-y-auto px-5 py-4 space-y-3" bind:this={chatScrollEl}>
			{#if chatHistory.length === 0}
```

with

```svelte
		<div class="flex-1 overflow-y-auto px-5 py-4 space-y-3" bind:this={chatScrollEl}>
			{#if reviewLoading}
				<p class="text-xs text-gray-500">Checking your template's rules…</p>
			{:else if reviewDone}
				<p class="text-xs text-gray-400">Rules updated. Save to apply them to future reports.</p>
			{:else if review && (review.cards.length || review.more.length || review.kept.length)}
				<details class="rounded-lg border border-white/10 p-3" open={review.ran}>
					<summary class="text-sm text-gray-200 cursor-pointer">Your template's rules</summary>
					<div class="pt-3">
						<RulesStep cards={review.cards} more={review.more} kept={review.kept} defaults={review.defaults}
							notice={review.notice} mode="review" busy={reviewBusy} onContinue={applyReview} />
					</div>
				</details>
			{/if}
			{#if chatHistory.length === 0}
```


- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run --project client src/routes/components/TemplateRefinePanel.rules.svelte.test.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/components/TemplateRefinePanel.svelte frontend/src/routes/components/TemplateRefinePanel.rules.svelte.test.ts
git commit -m "feat(refine-panel): Required values and first-use rules review through the ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 27: Phase 3 suites

- [ ] **Step 1: Frontend suite**

Run: `cd frontend && npx vitest run 2>&1 | tail -6`
Expected: baseline 716/717 plus the 15 new tests pass; the only failure is the known `page.svelte.spec` h1 test.

- [ ] **Step 2: svelte-check**

Run: `cd frontend && npm run check 2>&1 | tail -3`
Expected: at or below the 1194 baseline.

- [ ] **Step 3: Backend suite** (unchanged by this phase; it must still pass)

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: 0 failures

**Phase 3 checkpoint:** request an independent review. Merging needs Hassan's go-ahead.

---

# Phase 4: the writer takes the decisions as ground truth

Order (review fix 8): the prompts (Task 28), then the writer lab on them (Tasks 29-30), then the writer wiring (Task 31) with the arm Hassan picks.

Outcome: with decisions, the writer copies the decided LIST_MISSING line and concept lines instead of guessing them. It never writes questions. The slot conflict is fixed in the grammar text. **Needs Phase 1.** Removing the questions changes the old creator's Questions stage, so this phase ships with or after Phase 3. The prompt changes are case-agnostic, and the existing case-agnostic test now also covers the decided variant. There is one live writer prompt (`template_sheet_lab_prompts.ANALYSER_SYSTEM_PROMPT`); the legacy `TemplateManager.analyze_examples_to_skill_sheet` copy never runs in production and is not edited.

### Task 28: Decided prompts, no questions, the slot wording

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_lab_prompts.py` (`:50`, `:179`, `:182-209`, `:211-249`, append)
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py` (append)
- Test: `backend/tests/test_template_sheet_lab_prompts.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_template_sheet_lab_prompts.py`, change line 32 from


```python
    assert P.SHEET_OPEN in u and P.SHEET_CLOSE in u and '"summary"' in u and '"questions"' in u
```

to

```python
    assert P.SHEET_OPEN in u and P.SHEET_CLOSE in u and '"summary"' in u and '"questions"' not in u
```

and append:

```python
def test_the_decided_prompt_replaces_the_guessing_and_stays_case_agnostic():
    p = P.analyser_system_prompt(True)
    assert P.analyser_system_prompt(False) == P.ANALYSER_SYSTEM_PROMPT
    assert P.DECIDED_HEADING in p and "Use it when an example shows a list of values not provided" not in p
    assert "write exactly the lines given there" in p and "LIST_MISSING [" in p
    for clinical in CLINICAL:
        assert clinical not in p.lower(), clinical


def test_the_writer_asks_no_questions_and_places_a_normals_measured_part():
    u = P.analyser_user_prompt([{"content": "X"}], "<scan>")
    assert '"questions"' not in u and 'exactly one key, "summary"' in u
    assert "so it can be raised as a question" not in P.ANALYSER_SYSTEM_PROMPT
    assert "the measured part goes in a FIXED field line" in P.ANALYSER_SYSTEM_PROMPT


def test_the_user_prompt_carries_the_decided_lines():
    from rapid_reports_ai import template_decisions as td
    led, _ = td.set_decision([], "value", "Value A", {"need": "every"}, source="creation")
    led, _ = td.set_decision(led, "value", "Value B", {"need": "relevant"}, source="creation")
    led, _ = td.set_decision(led, "concept", "comparison", {"use": True, "default": "No previous imaging.",
                                                            "when_met": "Compared with the {study} of {date}."},
                             source="creation")
    led, _ = td.set_decision(led, "concept", "limitation", {"use": False}, source="creation")
    u = P.analyser_user_prompt([{"content": "X"}], "<scan>", decisions=led)
    assert P.DECIDED_HEADING in u
    assert 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["Value A"] AT TOP' in u
    assert "Not required in every report (never list them): Value B." in u
    assert ('FIXED "No previous imaging."\nRULE WHEN [context: the dictation names a previous imaging study for '
            'comparison] REPLACE "No previous imaging." WITH "Compared with the {study} of {date}."') in u
    assert "Technical limitation: not used." in u
    assert P.decided_block([]) == "" and P.SHEET_OPEN in u
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_lab_prompts.py -q`
Expected: FAIL (`analyser_system_prompt` missing; `"questions"` still in the user prompt)

- [ ] **Step 3: Add the render helpers** (append to `template_ledger_apply.py`; they render exactly what `apply_ledger` writes)


```python
# ── rendering for the writer's prompt (the same lines apply_ledger writes) ─────────────────────────────────────

def render_list_missing(items: List[str]) -> str:
    rule = tss.Rule(id="ledger", section="", condition="any listed value is not stated", condition_source="findings",
                    effect="list_missing", items=list(items), position="top", source_lines=[])
    return tsg.render_rule(rule)


def render_concept(name: str, choice: dict) -> List[str]:
    """A concept's lines inside a paragraph ([] for "not used")."""
    return _concept_lines(td.validate("concept", name, choice)[1]) if choice.get("use") else []
```

- [ ] **Step 4: Edit the prompts** in `template_sheet_lab_prompts.py` (each `old` occurs exactly once)


1. The slot conflict (§5): say where a normal sentence's measured part goes. Replace

```python
put a named slot in curly braces in its place ({value}, {measurement}, {laterality}, {date} ...). Never paraphrase quoted text.
```

with

```python
put a named slot in curly braces in its place ({value}, {measurement}, {laterality}, {date} ...). Never paraphrase quoted text. A NORMAL or NEGATIVE line is the exception: it never holds a slot. Where a normal sentence carries a measured value, the NORMAL quotes the sentence without the measured part, and the measured part goes in a FIXED field line ("<Label>: {value} <unit>") or in the paragraph's Measurement prose.
```

2. No clarifying questions: the Rules step asks instead. Replace

```python
Where something cannot be determined from the examples alone, flag it under Open Questions as [NEEDS CLARIFICATION] so it can be raised as a question."""
```

with

```python
Where something cannot be determined from the examples alone, flag it under Open Questions as [NEEDS CLARIFICATION]."""
```

3. The summary JSON has no questions. Replace

```python
  },
  "questions": [
    { "question": "<clarifying question>", "suggestions": ["<answer option>", "<answer option>"] }
  ]
}"""
```

with

```python
  }
}"""
```

4. PART 2 asks for the summary only. Replace

```python
PART 2: after the closing delimiter, one JSON object with exactly two keys, "summary" and "questions":
```

with

```python
PART 2: after the closing delimiter, one JSON object with exactly one key, "summary":
```

5. No question rules in the user prompt. Replace

```python
- impression.detail: one short sentence about sentence count, grouping, recommendation integration.
- questions: exactly 3 objects, each with "question" and "suggestions" (2-3 short clickable answer options). Target the most impactful Open Questions or where examples were ambiguous. Suggestions are concrete, specific answers. Do not ask about things clearly evidenced in the reports."""
```

with

```python
- impression.detail: one short sentence about sentence count, grouping, recommendation integration."""
```

6. The user prompt takes the decisions (signature). Replace

```python
def analyser_user_prompt(examples: List[Dict[str, str]], scan_type: str, protocol_notes: str = "") -> str:
```

with

```python
def analyser_user_prompt(examples: List[Dict[str, str]], scan_type: str, protocol_notes: str = "",
                         decisions: Optional[List[dict]] = None) -> str:
```

7. The user prompt carries the decided block after the radiologist's notes. Replace

```python
    return f"""Analyse these example radiology reports for scan type: **{scan_type}**
{notes}{examples_text}
```

with

```python
    decided = decided_block(decisions) if decisions else ""
    return f"""Analyse these example radiology reports for scan type: **{scan_type}**
{notes}{decided}{examples_text}
```

8. Append the decided variant and the decided block:

```python
# ── The Rules step's decisions as ground truth (spec 2026-10-13-template-rules-step-design, step 4) ─────────────
# With decisions, the writer no longer guesses LIST_MISSING or the standard study-level context rules: it copies the
# decided lines. The save function applies the same decisions by code afterwards (drift is logged), so this prompt
# change lowers drift; it is not what makes the decisions hold.

DECIDED_HEADING = "DECIDED BY THE RADIOLOGIST"

_GUESS_LIST_MISSING = "- LIST_MISSING: the values the radiologist expects in every report of this type, unconditionally."
_DECIDED_LIST_MISSING = (f"- LIST_MISSING: when {DECIDED_HEADING} gives a LIST_MISSING line, write exactly that line and no "
                         "other value; when it says no value is required, write no LIST_MISSING line; when it says "
                         "nothing about values, the values the radiologist expects in every report of this type, "
                         "unconditionally.")
_GUESS_CONTEXT = ("- Context rules: where examples differ because of what was performed, the protocol, a technical "
                  "limitation or prior imaging, write the context RULE that produces the variant wording, quoting it.")
_DECIDED_CONTEXT = (f"- Context rules: for each study-level circumstance listed under {DECIDED_HEADING}, write exactly the "
                    "lines given there, word for word, and no other line or rule about that circumstance; a "
                    "circumstance marked not used gets no line at all. For any other circumstance where the examples "
                    "differ because of what was performed or the protocol, write the context RULE that produces the "
                    "variant wording, quoting it.")
_GUESS_GRAMMAR = ("Use it when an example shows a list of values not provided (under any label), or contains unfilled "
                  "placeholders (curly-brace slots or blank values), or when every example states the same set of "
                  "measured values.")
_DECIDED_GRAMMAR = f"When {DECIDED_HEADING} decides the values, use exactly its line."


def analyser_system_prompt(decided: bool = False) -> str:
    """The writer's system prompt; `decided`: the Rules step's decisions are in the user prompt, so the guessing
    instructions for those items are replaced by "copy the decided lines"."""
    if not decided:
        return ANALYSER_SYSTEM_PROMPT
    p = ANALYSER_SYSTEM_PROMPT
    for old, new in ((_GUESS_LIST_MISSING, _DECIDED_LIST_MISSING), (_GUESS_CONTEXT, _DECIDED_CONTEXT),
                     (_GUESS_GRAMMAR, _DECIDED_GRAMMAR)):
        assert p.count(old) == 1, old[:60]
        p = p.replace(old, new)
    return p


def decided_block(decisions: List[dict]) -> str:
    """The decisions as lines the writer copies: the LIST_MISSING line and each concept's lines, rendered by the same
    code that applies them at save (template_ledger_apply)."""
    from . import template_decisions as td
    from . import template_ledger_apply as tla
    ledger = td.clean_ledger(decisions)
    values = [e for e in ledger if e["kind"] == "value"]
    concepts = [e for e in ledger if e["kind"] == "concept"]
    if not values and not concepts:
        return ""
    out = [f"\n\n**{DECIDED_HEADING}**: ground truth from the radiologist's own answers. Copy these lines word for "
           "word; they take precedence over anything the examples suggest.\n"]
    if values:
        every = [e["key"] for e in values if e["choice"]["need"] == "every"]
        other = [e["key"] for e in values if e["choice"]["need"] != "every"]
        if every:
            out.append("Required values: write this line under ## Report-wide, followed by \"| section: <NAME of the "
                       "first findings section>\":\n" + tla.render_list_missing(every))
        else:
            out.append("Required values: none. Write no LIST_MISSING line.")
        if other:
            out.append("Not required in every report (never list them): " + ", ".join(other) + ".")
    for e in concepts:
        c = td.CONCEPTS[e["key"]]
        lines = tla.render_concept(e["key"], e["choice"])
        if lines:
            out.append(f"{c.label}: write these lines at the end of the paragraph of the section that says how the "
                       "study was done (else the first findings paragraph):\n" + "\n".join(lines))
        else:
            out.append(f"{c.label}: not used. Write no line and no rule about it.")
    return "\n".join(out) + "\n"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_lab_prompts.py tests/test_template_ledger_apply.py tests/test_template_writer.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_lab_prompts.py backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_sheet_lab_prompts.py
git commit -m "feat(writer): decided-variant prompt, no clarifying questions, slot wording for normals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 29: Lab: the writer arms and their scorer

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/rules_step_lab.py`
- Test: `backend/tests/test_rules_step_lab.py` (append)

- [ ] **Step 1: Write the failing test** (append the first test of this block; the threshold test is added in Task 33)

```python
def test_score_sheet_counts_values_patient_lines_and_gold_normals():
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_ledger_apply as tla
    from tests.template_sheet_fixtures import LEDGER_SHEET
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation")
    led, _ = td.set_decision(led, "value", "Other", {"need": "every"}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    s = {"slug": "s", "kind": "base", "truth": {
        "values": [{"name": "LVEF", "aliases": [], "reports": [1], "need": "every"},
                   {"name": "RVEF", "aliases": [], "reports": [1], "need": "every"}],
        "patient_specific_fixed": ["No previous imaging available."]}}
    out = L.score_sheet(s, sheet, gold=LEDGER_SHEET)
    assert out["usable"] == 1 and out["required_values_listed"] == 1 and out["required_values_total"] == 2
    assert out["extra_values_listed"] == 1 and out["patient_fixed_present"] == 1
    assert out["gold_normals_hit"] == 1 and out["gold_normals_total"] == 1 and out["duplicate_normals"] == 0
    assert L.score_sheet(s, "# free")["usable"] == 0
```
- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rules_step_lab.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'score_sheet'`

- [ ] **Step 3: Implement.** Insert this block just before the line `FIELDS = {"decide": [`:

```python
# ── writer arms (Task 30): with and without the decisions, two temperatures ────────────────────────────────────
import re
import time

ARMS = {"A": (False, 0.8), "B": (True, 0.8), "C": (True, 0.4)}   # A = today's writer


def score_sheet(s: dict, sheet: str, gold: Optional[str] = None) -> dict:
    """One written sheet against the set's planted truth and (when given) the curated production sheet."""
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_ledger_apply as tla
    from rapid_reports_ai import template_sheet_grammar as tsg
    from rapid_reports_ai.hybrid_stack.template import norm_key
    base = {"slug": s["slug"], "kind": s.get("kind", "base")}
    if not tsg.is_grammar_sheet(sheet or ""):
        return {**base, "usable": 0}
    st = tsg.parse_sheet(sheet, mode="template").structure
    truth = s.get("truth") or {}
    normals = [td._name(n.structure) for n in st.normals]
    items = {td._name(x) for r in st.rules if r.effect == "list_missing" for x in r.items}
    every = [v for v in truth.get("values", []) if v.get("need") == "every"]
    out = {**base, "usable": int(st.usable),
           "duplicate_normals": len(normals) - len(set(normals)),
           "multi_structure_normals": sum(1 for n in st.normals if re.search(r"\band\b|/|,", n.structure)),
           "patient_fixed_present": sum(1 for t in truth.get("patient_specific_fixed", [])
                                        if any(norm_key(f.text) == norm_key(t) for f in st.fixed_blocks)),
           "comparison_rule": int(tla.observe(st, "concept", "comparison")["use"]),
           "context_rules": sum(1 for r in st.rules if r.condition_source == "context"),
           "required_values_listed": sum(1 for v in every if items & _value_names(v)),
           "required_values_total": len(every),
           "extra_values_listed": sum(1 for x in items
                                      if not any(x in _value_names(v) for v in truth.get("values", [])))}
    if gold:
        gold_n = {td._name(n.structure) for n in tsg.parse_sheet(gold, mode="template").structure.normals}
        out.update(gold_normals_hit=len(gold_n & set(normals)), gold_normals_total=len(gold_n))
    return out


async def _write_one(s: dict, answers: List[dict], decided: bool, temperature: float) -> dict:
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_sheet_lab_prompts as P
    from rapid_reports_ai.template_sheet_model import model_call
    from rapid_reports_ai.template_sheet_save import vet_sheet
    ledger = td.ledger_from_changes(answers, source="creation")[0] if decided else []
    ex = [{"label": "", "content": e} for e in s["examples"]]
    t0 = time.monotonic()
    raw = await model_call(P.analyser_system_prompt(decided),
                           P.analyser_user_prompt(ex, s.get("scan_type", ""), "", decisions=ledger or None),
                           {**P.ANALYSER_SETTINGS, "temperature": temperature})
    ans = P.split_answer(raw)
    v = await vet_sheet(ans["skill_sheet"] or "", origin="analyser", ledger=ledger or None)
    return {"status": v.status, "sheet": v.sheet if v.status == "saved" else (ans["skill_sheet"] or ""),
            "drift": v.ledger_drift, "ms": int((time.monotonic() - t0) * 1000)}


async def write(root: Path, run_no: int, arms: List[str], only: Optional[List[str]], gold_dir: Path) -> None:
    for arm in arms:
        decided, temperature = ARMS[arm]
        out_dir = root / "runs" / "write" / f"run{run_no}" / arm
        out_dir.mkdir(parents=True, exist_ok=True)
        for s in load_sets(root, only):
            ans_path = root / "answers" / f"{s['slug']}.json"
            if decided and not ans_path.exists():
                continue
            answers = json.loads(ans_path.read_text()) if ans_path.exists() else []
            res = await _write_one(s, answers, decided, temperature)
            gold_path = gold_dir / f"{s.get('seed', '')}.final.md"
            res["score"] = {**score_sheet(s, res["sheet"], gold_path.read_text() if gold_path.exists() else None),
                            "arm": arm, "drift": res["drift"], "refused": int(res["status"] != "saved")}
            (out_dir / f"{s['slug']}.json").write_text(json.dumps(res, indent=1))
            print(arm, s["slug"], json.dumps(res["score"]))
```

then replace everything from `FIELDS = {"decide": [` to the end of the file with:

```python
FIELDS = {"decide": ["values_found", "values_total", "values_extra", "every_kept", "partial_carded", "concept_cells",
                     "concept_correct", "disagreements_found", "disagreements_total", "polarity_correct",
                     "polarity_total", "cards", "dropped_quotes"],
          "write": ["usable", "refused", "drift", "required_values_listed", "required_values_total",
                    "extra_values_listed", "patient_fixed_present", "comparison_rule", "context_rules",
                    "duplicate_normals", "multi_structure_normals", "gold_normals_hit", "gold_normals_total",
                    "concept_duplicates"]}


def report(root: Path, stage: str) -> str:
    """Tables per run; totals by kind (writer: by arm and kind). Synthetic and real are reported apart."""
    lines = [f"# Rules-step lab: {stage}", ""]
    for run_dir in sorted((root / "runs" / stage).glob("run*")):
        rows = [json.loads(p.read_text())["score"] for p in sorted(run_dir.rglob("*.json"))]
        for r in rows:
            if r.get("arm"):
                r["kind"] = f"{r['arm']}:{r['kind'].split(':')[-1]}"
        lines += [f"## {run_dir.name}", "", "| slug | kind | " + " | ".join(FIELDS[stage]) + " |",
                  "|---|---|" + "---|" * len(FIELDS[stage])]
        lines += [f"| {r['slug']} | {r['kind']} | " + " | ".join(str(r.get(f, "")) for f in FIELDS[stage]) + " |"
                  for r in rows]
        lines += ["", "Totals by kind:", ""]
        for kind, agg in summarise(rows, FIELDS[stage]).items():
            lines.append(f"- {kind}: " + ", ".join(f"{k} {v}" for k, v in agg.items()))
        lines.append("")
    text = "\n".join(lines)
    (root / f"REPORT_{stage}.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["decide", "write", "report"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--gold-dir", type=Path, default=Path.home() / "Code/rr-template-conversion-private/final")
    ap.add_argument("--stage", dest="report_stage", default="decide")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.stage == "decide":
        asyncio.run(decide(a.root, a.run, only))
    elif a.stage == "write":
        asyncio.run(write(a.root, a.run, [x for x in a.arms.split(",") if x], only, a.gold_dir))
    else:
        print(report(a.root, a.report_stage))


if __name__ == "__main__":
    main()
```
- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rules_step_lab.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/rules_step_lab.py backend/tests/test_rules_step_lab.py
git commit -m "feat(lab): writer arms (decisions on/off, temperature) and sheet scorer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 30 (controller-run): Writer lab, with and without the decisions, before the writer is wired

Arms: **A** today's writer (no decisions, temperature 0.8), **B** decided at 0.8, **C** decided at 0.4 (roadmap §5's temperature item). The inputs are the synthetic and real sets and the card answers from Task 21. The gold sheets are `~/Code/rr-template-conversion-private/final/<seed>.final.md`. The earlier baseline was 33/43 required normals captured.

- [ ] **Step 1: Run.** One run per arm; a second run only of the arm Hassan prefers, if he asks for it (eval economy):

```bash
cd backend && .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab write --root ~/Code/rr-template-conversion-private/synthetic/rules_step --run 1 --arms A,B,C
.venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab report --root ~/Code/rr-template-conversion-private/synthetic/rules_step --stage write
```

- [ ] **Step 2: Hand read.** For 5 sets (2 real, 3 synthetic variants), read arm A's and arm C's sheets side by side (Claude subagent, `model: "opus"`, peer read). Check the comparison and contrast handling, patient-specific FIXED lines, duplicate and multi-structure normals, and that the voice prose is unchanged. Record the result in `synthetic/rules_step/HANDREAD_write.md`.

- [ ] **Step 3: Report** in `synthetic/rules_step/REPORT_write.md`. Cover: required normals captured against gold, per arm; patient-specific FIXED lines present; standard comparison rule present; required values listed / extra; drift (lines the ledger had to overwrite) for B and C; refusals; latency; synthetic and real apart; n = 1 per cell, so the noise is noted. Recommendations: whether to keep the decided prompt (B/C against A), the temperature (0.8 or 0.4), and any remaining slot-conflict symptoms. Tell Hassan the path. **He decides.** If he picks 0.4, change `ANALYSER_SETTINGS["temperature"]` in `template_sheet_lab_prompts.py` in a one-line commit; `test_write_returns_a_vetted_sheet_summary_and_questions` compares against `P.ANALYSER_SETTINGS`, so it follows.


### Task 31: The writer uses the decided prompts (after the writer lab)

Run this after Hassan has read `REPORT_write.md`. If he keeps arm A (today's writer), skip this task: the ledger still applies the decisions at save.

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_writer.py`
- Test: `backend/tests/test_template_writer.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
async def test_write_with_decisions_uses_the_decided_prompts(calls, monkeypatch):
    async def vet(sheet, origin, previous="", ledger=None):
        return VetOutcome("saved", sheet, ledger=list(ledger or []))
    monkeypatch.setattr(W, "vet_sheet", vet)
    led = [{"kind": "value", "key": "Value A", "choice": {"need": "every"}, "by": "radiologist", "at": "t",
            "source": "creation"}]
    await W.write_sheet([{"label": "", "content": "r1"}], "<scan>", decisions=led)
    assert calls["system"] == P.analyser_system_prompt(True) and P.DECIDED_HEADING in calls["user"]
    await W.write_sheet([{"label": "", "content": "r1"}], "<scan>")
    assert calls["system"] == P.ANALYSER_SYSTEM_PROMPT and P.DECIDED_HEADING not in calls["user"]
```
- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_writer.py::test_write_with_decisions_uses_the_decided_prompts -q`
Expected: FAIL (`calls["system"]` is the undecided prompt)

- [ ] **Step 3: Implement.** In `write_sheet` replace

```python
    raw = await model_call(P.ANALYSER_SYSTEM_PROMPT, P.analyser_user_prompt(examples, scan_type, protocol_notes),
                           P.ANALYSER_SETTINGS)
```

with

```python
    raw = await model_call(P.analyser_system_prompt(decided=bool(decisions)),
                           P.analyser_user_prompt(examples, scan_type, protocol_notes, decisions=decisions),
                           P.ANALYSER_SETTINGS)
```

- [ ] **Step 4: Run the writer tests and the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_writer.py -q && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_writer.py backend/tests/test_template_writer.py
git commit -m "feat(writer): decisions reach the writer as ground truth

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


---

# Phase 5: Style-step sheet checks

Outcome: after the build, the Style step (and the refine panel) shows "Always printed" cards for FIXED lines Jev says could be false for another patient, "May be stated twice" cards for lines the ledger does not own that state a decided concept again, "Your normal report" built by code with tap-to-edit, structures mentioned with no normal sentence, and ledger entries that need a look. The backend (Tasks 32-34) needs Phase 1 only and ships independently. The UI wiring (Task 36) builds on Phase 3's edits. The Jev FIXED-question lab (Task 33) runs before the cards reach the UI (Task 36).

### Task 32: `template_sheet_review` (FIXED check, concept duplicates, normal report, uncovered, sheet checks)

**Files:**
- Create: `backend/src/rapid_reports_ai/template_sheet_review.py`
- Test: `backend/tests/test_template_sheet_review.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_template_sheet_review.py`)

```python
"""Style-step sheet checks (Rules-step spec, step 5)."""
import httpx

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_review as V
from tests.template_sheet_fixtures import LEDGER_SHEET


def _st(sheet=LEDGER_SHEET):
    return tsg.parse_sheet(sheet).structure


def _jev(score):
    def handler(request):
        import json
        qs = json.loads(request.content)["questions"]
        return httpx.Response(200, json={"answers": {k: {"noul": score} for k in qs}})
    return httpx.MockTransport(handler)


def test_fixed_candidates_skip_targeted_and_decided_lines():
    assert V.fixed_candidates(_st(), []) == ["Axial images were acquired.", "No previous imaging available."]
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging available.",
                                                           "when_met": "Compared with {date}."}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    assert V.fixed_candidates(_st(sheet), led) == ["Axial images were acquired."]     # the default has its rule
    led2, _ = td.set_decision([], "fixed", "Axial images were acquired.", {"keep": "always"}, source="creation")
    assert V.fixed_candidates(_st(), led2) == ["No previous imaging available."]


def test_an_undecided_concepts_default_is_still_checked():
    sheet = LEDGER_SHEET.replace(
        'FIXED "No previous imaging available."\n',
        'FIXED "No previous imaging available."\nRULE WHEN [context: the dictation names a previous imaging study for '
        'comparison] REPLACE "No previous imaging available." WITH "Compared with {date}."\n')
    assert "No previous imaging available." in V.fixed_candidates(_st(sheet), [])   # polarity stays checkable


async def test_the_absence_backstop_skips_a_line_a_context_rule_targets():
    sheet = LEDGER_SHEET.replace(
        'FIXED "No previous imaging available."\n',
        'FIXED "No previous imaging available."\nRULE WHEN [context: the dictation names a previous imaging study for '
        'comparison] REPLACE "No previous imaging available." WITH "Compared with {date}."\n')
    assert await V.fixed_flags(_st(sheet), [], transport=_jev(0.1)) == []
    assert await V.fixed_flags(_st(sheet), [], transport=_jev(0.9)) == ["Axial images were acquired.",
                                                                         "No previous imaging available."]


async def test_absence_worded_lines_are_flagged_by_code_the_rest_by_jev():
    assert await V.fixed_flags(_st(), [], transport=_jev(0.1)) == ["No previous imaging available."]
    assert await V.fixed_flags(_st(), [], transport=_jev(0.9)) == ["Axial images were acquired.",
                                                                    "No previous imaging available."]


def test_the_normal_report_is_built_in_section_and_sheet_order():
    rep = V.normal_report(LEDGER_SHEET, _st())
    assert rep == [{"section": "FINDINGS", "header": "Findings:", "sentences": [
        {"key": "Liver :: liver", "text": "The liver is normal in size.", "kind": "normal", "paragraph": "Liver"},
        {"key": 'Liver :: "No focal liver lesion."', "text": "No focal liver lesion.", "kind": "negative",
         "paragraph": "Liver"}]}]


def test_uncovered_lists_covered_structures_without_a_normal():
    assert [(c["title"], c["key"]) for c in V.uncovered(_st())] == [("Liver: gallbladder", "Liver :: gallbladder")]


async def test_sheet_checks_is_fail_soft_and_reports_unmatched_entries():
    led, _ = td.set_decision([], "normal", "Spleen :: spleen", {"text": "The spleen is normal."}, source="creation")
    out = await V.sheet_checks(LEDGER_SHEET, led, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert out["errors"] == ["fixed"] and out["fixed_cards"] == []
    assert [c["key"] for c in out["unmatched_cards"]] == ["Spleen :: spleen"]
    assert out["normal_report"] and out["uncovered_cards"]
    assert (await V.sheet_checks("# free", []))["errors"] == ["parse"]



def _jev_on(word):
    def handler(request):
        import json
        qs = json.loads(request.content)["questions"]
        return httpx.Response(200, json={"answers": {
            k: {"noul": 0.9 if word in q["instructions"].split("REPORT: ")[-1].lower() else 0.1} for k, q in qs.items()}})
    return httpx.MockTransport(handler)


async def test_a_line_that_may_state_a_decided_concept_twice_is_a_card():
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging available.",
                                                           "when_met": "Compared with {date}."}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet.replace(
        'FIXED "Axial images were acquired."\n', 'FIXED "Axial images were acquired."\nFIXED "There is no prior study."\n')
    out = await V.sheet_checks(sheet, led, transport=_jev_on("prior"))
    assert [(c["key"], c["note"]) for c in out["duplicate_cards"]] == [
        ("There is no prior study.", "May be stated twice: Comparison with previous imaging")]
    assert "There is no prior study." not in [c["key"] for c in out["fixed_cards"]]   # one card per line
    assert await V.concept_duplicates(_st(LEDGER_SHEET), [], transport=_jev_on("prior")) == []   # nothing decided
```
- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_review.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.template_sheet_review'`

- [ ] **Step 3: Write the module.** Append the card shape to `template_rules_cards.py`:

```python
def duplicate_card(text: str, concept_label: str) -> dict:
    """A line that may state a decided study-level concept a second time (Style step)."""
    return {"id": f"duplicate:{td.match_key('fixed', text)}", "kind": "duplicate", "step": "style", "title": text,
            "evidence": [], "note": f"May be stated twice: {concept_label}", "ledger_kind": "fixed", "key": text,
            "choices": [_choice("remove", "Remove this line", {"keep": "remove"}),
                        _choice("keep", "Keep both", {"keep": "always"})],
            "selected": None, "rank": _RANK["fixed"]}
```

and create `backend/src/rapid_reports_ai/template_sheet_review.py`:

```python
"""Sheet checks after the build, shown on the Style step as report behaviour (Rules-step spec, step 5, cards
"Always printed" and "Your normal report"); roadmap §4's creation-time FIXED check.

- fixed_flags: a FIXED line is printed in every report. Each one not covered by a context rule and not already
  decided is asked of Jev ("could this be false for a different patient having this scan?"); an absence-worded line
  ("No …", "There is no …", "Without …") is flagged by code as a tiny backstop. Flags become "Always printed" cards;
  nothing is ever dropped silently.
- normal_report: the all-normal report built by code from the NORMAL / NEGATIVE lines in section order, each sentence
  tagged with its ledger key (tap to edit or remove).
- uncovered: structures a findings paragraph COVERS with no NORMAL ("mentioned in your examples but no normal
  sentence": Add wording / Leave unmentioned).
- concept_duplicates: a FIXED line or a non-standard context rule the ledger does not own that Jev says states a
  decided concept again ("may be stated twice").
- sheet_checks: all of the above plus the ledger entries that could not be matched (cards at the next review)."""
from __future__ import annotations

import logging
import os
from typing import List, Optional, Set

from . import template_decisions as td
from . import template_ledger_apply as tla
from . import template_rules_cards as trc
from . import template_sheet_grammar as tsg
from . import template_sheet_structure as tss
from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

TIMEOUT_S = 6.0
FIXED_MIN = 0.5   # lab-set (scripts/rules_step_lab.py fixed)
FIXED_QUESTION = ("This SENTENCE is printed in every report of this scan type. It could be false for a different "
                  "patient having this scan: {s}")


def _clean(sheet: str) -> Optional[tss.SheetStructure]:
    if not tsg.is_grammar_sheet(sheet or ""):
        return None
    res = tsg.parse_sheet(sheet, mode="template")
    return None if res.errors else res.structure


def fixed_candidates(st: tss.SheetStructure, ledger: List[dict]) -> List[str]:
    """FIXED texts printed for every patient and not yet decided. Only the ledger's own lines are left out (a decided
    concept's wordings, a decided fixed line); the default of an undecided concept is checked like any other line,
    so a default with the wrong polarity still shows up."""
    owned = td.concept_texts(ledger) | {norm_key(e["key"]) for e in ledger if e["kind"] == "fixed"}
    out, seen = [], set()
    for f in st.fixed_blocks:
        k = norm_key(f.text)
        if k in owned or k in seen:
            continue
        seen.add(k)
        out.append(f.text)
    return out


def _targeted(st: tss.SheetStructure) -> Set[str]:
    return {norm_key(r.target) for r in st.rules if r.condition_source == "context" and r.target}


async def _jev_scores(texts: List[str], transport=None) -> List[float]:
    from .jev_client import JEV_MODEL, jev_post
    qs = {f"f{i}": {"type": "noul", "instructions": FIXED_QUESTION.format(s=t)} for i, t in enumerate(texts)}
    r = await jev_post({"model": JEV_MODEL, "state": "Statements from a radiology report template.", "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out = []
    for i in range(len(texts)):
        v = (ans.get(f"f{i}") or {}).get("noul")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("jev: incomplete answers")
        out.append(float(v))
    return out


async def fixed_flags(st: tss.SheetStructure, ledger: List[dict], transport=None) -> List[str]:
    """The FIXED lines to show as "Always printed" cards. Raises when Jev fails (the caller shows no such cards)."""
    texts = fixed_candidates(st, ledger)
    targeted = _targeted(st)   # roadmap §4(a): the default-plus-context-rule pattern is legal for the backstop
    backstop = [t for t in texts if tsg._ABSENCE_START.match(t) and norm_key(t) not in targeted]
    rest = [t for t in texts if t not in backstop]
    scores = await _jev_scores(rest, transport) if rest else []
    flagged = set(backstop) | {t for t, s in zip(rest, scores) if s >= FIXED_MIN}
    return [t for t in texts if t in flagged]


DUP_MIN = 0.5   # lab-set (scripts/rules_step_lab.py dups)


def duplicate_candidates(st: tss.SheetStructure, ledger: List[dict]) -> List[str]:
    """Lines the ledger does not own that a decided concept could also be stating: FIXED lines and the sentences of
    context USE / REPLACE rules whose condition is not a standard one."""
    owned = td.concept_texts(ledger)
    out: List[str] = []
    for t in [f.text for f in st.fixed_blocks] + [r.then_text for r in st.rules if r.condition_source == "context"
                                                  and r.then_text and not td.concept_of_condition(r.condition)]:
        if norm_key(t) not in owned and t not in out:
            out.append(t)
    return out


async def concept_duplicates(st: tss.SheetStructure, ledger: List[dict], transport=None) -> List[dict]:
    """Style cards for a line that may state a decided concept a second time (Jev: the concept's own question over
    each line the ledger does not own). Raises when Jev fails."""
    from .jev_client import JEV_MODEL, jev_post
    decided = [e["key"] for e in ledger if e["kind"] == "concept" and e["key"] in td.CONCEPTS]
    lines = duplicate_candidates(st, ledger)
    if not decided or not lines:
        return []
    pairs = [(c, t) for c in decided for t in lines]
    qs = {f"d{i}": {"type": "noul", "instructions": f"{td.CONCEPTS[c].question} REPORT: {t}"}
          for i, (c, t) in enumerate(pairs)}
    r = await jev_post({"model": JEV_MODEL, "state": "Each question quotes one REPORT sentence from a template.",
                        "questions": qs}, os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out, seen = [], set()
    for i, (c, t) in enumerate(pairs):
        v = (ans.get(f"d{i}") or {}).get("noul")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("jev: incomplete answers")
        if v >= DUP_MIN and t not in seen:
            seen.add(t)
            out.append(trc.duplicate_card(t, td.CONCEPTS[c].label))
    return out


def _line_order(sheet: str, raws: List[str]) -> List[int]:
    lines = sheet.split("\n")
    taken: Set[int] = set()
    out = []
    for raw in raws:
        i = next((k for k, ln in enumerate(lines) if k not in taken and ln == raw), len(lines))
        taken.add(i)
        out.append(i)
    return out


def normal_report(sheet: str, st: tss.SheetStructure) -> List[dict]:
    """[{"section", "header", "sentences": [{"key", "text", "kind", "paragraph"}]}] for every non-impression section
    with NORMAL / NEGATIVE lines, in section order; sentences in sheet order."""
    paras = {p.id: p.name for p in st.paragraphs}
    units = []
    for n in st.normals:
        if n.paragraph:
            units.append((n.source_line, n.section, {"key": td.normal_key(paras[n.paragraph], n.structure),
                                                     "text": n.text, "kind": "normal", "paragraph": paras[n.paragraph]}))
    for n in st.negatives:
        if n.paragraph and n.origin == "template" and not n.condition:
            units.append((n.source_lines[0], n.section, {"key": td.negative_key(paras[n.paragraph], n.text),
                                                         "text": n.text, "kind": "negative",
                                                         "paragraph": paras[n.paragraph]}))
    order = _line_order(sheet, [u[0] for u in units])
    units = [u for _, u in sorted(zip(order, units), key=lambda x: x[0])]
    out = []
    for s in sorted(st.sections, key=lambda s: s.order):
        if s.role == "impression":
            continue
        sentences = [u[2] for u in units if u[1] == s.name]
        if sentences:
            out.append({"section": s.name, "header": s.header or s.name.title(), "sentences": sentences})
    return out


def uncovered(st: tss.SheetStructure) -> List[dict]:
    """Cards for structures a findings paragraph COVERS with no NORMAL line."""
    findings = {s.name for s in st.sections if s.role == "findings"}
    out = []
    for p in st.paragraphs:
        if p.section not in findings:
            continue
        have = {td._name(n.structure) for n in st.normals if n.paragraph == p.id}
        out += [trc.uncovered_card(p.name, c) for c in p.covers if td._name(c) not in have]
    return out


async def sheet_checks(sheet: str, ledger: List[dict], transport=None) -> dict:
    """Everything the Style step shows. Fail-soft per part: a part that fails is empty and named in "errors"."""
    out = {"fixed_cards": [], "duplicate_cards": [], "normal_report": [], "uncovered_cards": [], "unmatched_cards": [],
           "stale_quotes": [], "errors": []}
    st = _clean(sheet)
    if st is None:
        out["errors"].append("parse")
        return out
    ledger = td.clean_ledger(ledger)
    res = tla.apply_ledger(sheet, ledger)
    out["stale_quotes"] = res.stale_quotes
    for e in res.unmatched:
        out["unmatched_cards"].append(trc.fixed_card(e["key"], step="review") if e["kind"] == "fixed"
                                      else trc.normal_card(e["key"], e["choice"].get("text", ""), step="review")
                                      if e["kind"] == "normal" else None)
    out["unmatched_cards"] = [c for c in out["unmatched_cards"] if c]
    out["normal_report"] = normal_report(sheet, st)
    out["uncovered_cards"] = uncovered(st)
    try:
        out["duplicate_cards"] = await concept_duplicates(st, ledger, transport)
    except Exception as e:
        logger.warning("[sheet-checks] duplicate check failed: %s", type(e).__name__)
        out["errors"].append("duplicates")
    dup = {td.match_key("fixed", c["key"]) for c in out["duplicate_cards"]}
    try:
        out["fixed_cards"] = [trc.fixed_card(t) for t in await fixed_flags(st, ledger, transport)
                              if td.match_key("fixed", t) not in dup]
    except Exception as e:
        logger.warning("[sheet-checks] fixed check failed: %s", type(e).__name__)
        out["errors"].append("fixed")
    return out
```
- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_sheet_review.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_review.py backend/src/rapid_reports_ai/template_rules_cards.py backend/tests/test_template_sheet_review.py
git commit -m "feat(template): Style-step sheet checks (FIXED check, normal report, uncovered structures)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 33: FIXED-question lab (code, then controller-run), before the cards reach the UI

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/rules_step_lab.py`
- Test: `backend/tests/test_rules_step_lab.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_threshold_table():
    rows = [{"score": 0.9, "variable": True}, {"score": 0.45, "variable": True}, {"score": 0.6, "variable": False},
            {"score": 0.1, "variable": False}]
    t = {r["cut"]: r for r in L.threshold_table(rows, cuts=(0.4, 0.7))}
    assert (t[0.4]["tp"], t[0.4]["fp"], t[0.4]["fn"]) == (2, 1, 0) and t[0.4]["precision"] == 0.67
    assert (t[0.7]["tp"], t[0.7]["fp"], t[0.7]["fn"]) == (1, 0, 1) and t[0.7]["recall"] == 0.5
```
- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rules_step_lab.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'threshold_table'`

- [ ] **Step 3: Implement.** Insert this block just before the line `def main() -> None:`

```python
# ── FIXED-line question (Task 33): Jev scores of labelled FIXED lines, two wordings ────────────────────────────
FIXED_WORDINGS = {
    "statement": ("This SENTENCE is printed in every report of this scan type. It could be false for a different "
                  "patient having this scan: {s}"),
    "question": "Could this sentence be false for a different patient having this scan? Sentence: {s}",
}


def threshold_table(rows: List[dict], cuts=(0.3, 0.4, 0.5, 0.6, 0.7)) -> List[dict]:
    """rows: [{"score", "variable": bool}] -> precision / recall of "flag when score >= cut" per cut."""
    out = []
    for c in cuts:
        tp = sum(1 for r in rows if r["score"] >= c and r["variable"])
        fp = sum(1 for r in rows if r["score"] >= c and not r["variable"])
        fn = sum(1 for r in rows if r["score"] < c and r["variable"])
        out.append({"cut": c, "tp": tp, "fp": fp, "fn": fn,
                    "precision": round(tp / (tp + fp), 2) if tp + fp else None,
                    "recall": round(tp / (tp + fn), 2) if tp + fn else None})
    return out


async def fixed(root: Path, run_no: int) -> None:
    """<root>/fixed_lines.json: [{"text", "variable": bool, "source"}] (labelled by a Claude subagent, Task 33)."""
    from rapid_reports_ai import template_sheet_review as tsr
    items = json.loads((root / "fixed_lines.json").read_text())
    out_dir = root / "runs" / "fixed" / f"run{run_no}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, wording in FIXED_WORDINGS.items():
        tsr.FIXED_QUESTION = wording
        scores: List[float] = []
        for k in range(0, len(items), 40):
            scores += await tsr._jev_scores([i["text"] for i in items[k:k + 40]])
        rows = [{**i, "score": s} for i, s in zip(items, scores)]
        (out_dir / f"{name}.json").write_text(json.dumps({"rows": rows, "table": threshold_table(rows)}, indent=1))
        print(name, json.dumps(threshold_table(rows)))



async def dups(root: Path, run_no: int) -> None:
    """Count, in the writer lab's sheets, lines Jev says state a decided concept a second time (review fix 2): adds
    "concept_duplicates" to each stored score; `report --stage write` then shows it."""
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_sheet_grammar as tsg
    from rapid_reports_ai import template_sheet_review as tsr
    for path in sorted((root / "runs" / "write" / f"run{run_no}").rglob("*.json")):
        res = json.loads(path.read_text())
        ans = root / "answers" / f"{path.stem}.json"
        ledger = td.ledger_from_changes(json.loads(ans.read_text()), source="creation")[0] if ans.exists() else []
        sheet = res.get("sheet") or ""
        if not tsg.is_grammar_sheet(sheet) or not ledger:
            continue
        st = tsg.parse_sheet(sheet, mode="template").structure
        res["score"]["concept_duplicates"] = len(await tsr.concept_duplicates(st, ledger))
        path.write_text(json.dumps(res, indent=1))
        print(path.parent.name, path.stem, res["score"]["concept_duplicates"])
```

and replace `main` (from `def main() -> None:` to the end of the file) with:

```python
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["decide", "write", "fixed", "dups", "report"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--gold-dir", type=Path, default=Path.home() / "Code/rr-template-conversion-private/final")
    ap.add_argument("--stage", dest="report_stage", default="decide")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.stage == "decide":
        asyncio.run(decide(a.root, a.run, only))
    elif a.stage == "write":
        asyncio.run(write(a.root, a.run, [x for x in a.arms.split(",") if x], only, a.gold_dir))
    elif a.stage == "fixed":
        asyncio.run(fixed(a.root, a.run))
    elif a.stage == "dups":
        asyncio.run(dups(a.root, a.run))
    else:
        print(report(a.root, a.report_stage))


if __name__ == "__main__":
    main()
```
- [ ] **Step 4: Run the tests and commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rules_step_lab.py -q`
Expected: PASS (4 tests)

```bash
git add backend/src/rapid_reports_ai/scripts/rules_step_lab.py backend/tests/test_rules_step_lab.py
git commit -m "feat(lab): FIXED-question wording arms and threshold table

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

- [ ] **Step 5 (controller): Label the FIXED lines.** Dispatch one Claude subagent (`model: "opus"`). It parses every FIXED line of the 31 curated sheets (`final/*.final.md`, through `template_sheet_grammar.parse_sheet`) and of the arm-C sheets from Task 30, adds every planted `patient_specific_fixed` sentence, and labels each line `variable: true` when it could be false for another patient having the scan, citing the reason in one phrase. It writes `synthetic/rules_step/fixed_lines.json` as `[{"text", "variable", "source"}]`. Hassan spot-checks 10 labels.

- [ ] **Step 6 (controller): Run and report.** Two runs:

```bash
cd backend && for k in 1 2; do .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab fixed --root ~/Code/rr-template-conversion-private/synthetic/rules_step --run $k; done
```

Write `synthetic/rules_step/REPORT_fixed.md` with: score distributions of variable and fixed lines per wording; precision and recall at 0.3-0.7; run-to-run drift; how often the code backstop (absence-worded lines) caught what Jev missed; synthetic and real apart. Recommend a wording and a `FIXED_MIN`. Hassan decides. Set `template_sheet_review.FIXED_QUESTION` and `FIXED_MIN` to his choice in a one-line commit (the review tests stub the Jev score, so they hold).

- [ ] **Step 7 (controller): Count possible duplicates in the writer lab's sheets** (review fix 2). The `dups` stage re-reads Task 30's stored sheets, asks each decided concept's Jev question over the lines the ledger does not own, and adds `concept_duplicates` to each score:

```bash
cd backend && .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab dups --root ~/Code/rr-template-conversion-private/synthetic/rules_step --run 1
.venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab report --root ~/Code/rr-template-conversion-private/synthetic/rules_step --stage write
```

Append the per-arm duplicate counts to `REPORT_write.md`. Hand-read every hit for 3 sets (true duplicate or not), and report the precision with a recommended `DUP_MIN`. Hassan decides.


### Task 34: `/api/templates/skill-sheet/sheet-checks`

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py` (request model and endpoint, after `/decide`)
- Test: `backend/tests/test_template_ledger_routes.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
SHEET_CHECKS = "/api/templates/skill-sheet/sheet-checks"


def test_sheet_checks_returns_the_style_step_cards(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_sheet_review as V
    from tests.template_sheet_fixtures import LEDGER_SHEET

    async def scores(texts, transport=None):
        return [0.9 for _ in texts]
    monkeypatch.setattr(V, "_jev_scores", scores)
    r = client.post(SHEET_CHECKS, headers=auth_headers, json={"skill_sheet": LEDGER_SHEET, "decisions": []}).json()
    assert r["success"] and r["errors"] == [] and r["duplicate_cards"] == []      # nothing decided yet
    assert [c["key"] for c in r["fixed_cards"]] == ["Axial images were acquired.", "No previous imaging available."]
    assert r["normal_report"][0]["sentences"][0]["text"] == "The liver is normal in size."
    assert [c["key"] for c in r["uncovered_cards"]] == ["Liver :: gallbladder"]


def test_sheet_checks_never_fails_the_request(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_sheet_review as V

    async def boom(sheet, ledger, transport=None):
        raise RuntimeError("x")
    monkeypatch.setattr(V, "sheet_checks", boom)
    r = client.post(SHEET_CHECKS, headers=auth_headers, json={"skill_sheet": "x"}).json()
    assert r["success"] and r["errors"] == ["all"] and r["fixed_cards"] == [] and r["duplicate_cards"] == []
```
- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_routes.py -q`
Expected: FAIL (404)

- [ ] **Step 3: Implement** (in `main.py`, after `skill_sheet_decide_endpoint`)

```python
class SkillSheetChecksRequest(BaseModel):
    skill_sheet: str
    decisions: List[Dict[str, Any]] = []


@app.post("/api/templates/skill-sheet/sheet-checks")
async def skill_sheet_checks_endpoint(
    request: SkillSheetChecksRequest,
    current_user: User = Depends(get_current_user),
):
    """The Style step's checks: always-printed lines (Jev), lines that may state a decided concept twice (Jev), the
    normal report, covered structures without a normal,
    and ledger entries to review. Fail-soft: a part that fails is empty and named in "errors"."""
    from . import template_sheet_review as tsr
    try:
        return {"success": True, **(await tsr.sheet_checks(request.skill_sheet, request.decisions))}
    except Exception as e:
        logger.warning("sheet checks failed: %s", type(e).__name__)
        return {"success": True, "fixed_cards": [], "duplicate_cards": [], "normal_report": [], "uncovered_cards": [],
                "unmatched_cards": [], "stale_quotes": [], "errors": ["all"]}
```
- [ ] **Step 4: Run the tests and the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_ledger_routes.py -q && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: all PASS (the scratch run of this plan: 4009 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_template_ledger_routes.py
git commit -m "feat(template): /skill-sheet/sheet-checks for the Style step (fail-soft)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 35: `StyleChecks` component and its API call

**Files:**
- Modify: `frontend/src/lib/template-rules/types.ts`, `frontend/src/lib/template-rules/api.ts`, `frontend/src/lib/template-rules/api.test.ts`
- Create: `frontend/src/lib/template-rules/StyleChecks.svelte`
- Test: `frontend/src/lib/template-rules/StyleChecks.svelte.test.ts`

- [ ] **Step 1: Write the failing tests**

In `api.test.ts` change the import to `import { postApplyDecisions, postDecide, postSheetChecks } from './api';` and append:

```ts
describe('sheet checks api', () => {
	it('posts the sheet and the ledger', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ success: true, fixed_cards: [], normal_report: [], uncovered_cards: [], unmatched_cards: [], stale_quotes: [], errors: [] })));
		vi.stubGlobal('fetch', fetchMock);
		await postSheetChecks('tok', { skill_sheet: 'S', decisions: [] });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/templates/skill-sheet/sheet-checks')).toBe(true);
		expect(JSON.parse(init.body as string)).toEqual({ skill_sheet: 'S', decisions: [] });
	});
});
```

Create `StyleChecks.svelte.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import StyleChecks from './StyleChecks.svelte';
import type { SheetChecksResponse } from './types';

const fixedCard = {
	id: 'fixed:no previous imaging available', kind: 'fixed', step: 'style', title: 'No previous imaging available.', evidence: [],
	ledger_kind: 'fixed', key: 'No previous imaging available.', selected: null, rank: 3,
	choices: [
		{ id: 'always', label: 'Always the same', choice: { keep: 'always' } },
		{ id: 'dictated', label: 'Only when dictated', choice: { keep: 'dictated' } },
		{ id: 'remove', label: 'Remove', choice: { keep: 'remove' } }
	]
} as const;
const uncoveredCard = {
	id: 'uncovered:liver :: gallbladder', kind: 'uncovered', step: 'style', title: 'Liver: gallbladder', evidence: [],
	ledger_kind: 'normal', key: 'Liver :: gallbladder', selected: null, rank: 5,
	choices: [{ id: 'add', label: 'Add wording', choice: null }, { id: 'leave', label: 'Leave unmentioned', choice: { text: '' } }]
} as const;
const checks = (): SheetChecksResponse => ({
	success: true, errors: [], stale_quotes: [], unmatched_cards: [], duplicate_cards: [],
	fixed_cards: [structuredClone(fixedCard) as never],
	uncovered_cards: [structuredClone(uncoveredCard) as never],
	normal_report: [{ section: 'FINDINGS', header: 'Findings:', sentences: [
		{ key: 'Liver :: liver', text: 'The liver is normal in size.', kind: 'normal', paragraph: 'Liver' }] }]
});

describe('StyleChecks', () => {
	it('an always-printed line is one tap', async () => {
		const onChange = vi.fn();
		render(StyleChecks, { checks: checks(), onChange });
		await page.getByRole('button', { name: 'No previous imaging available.: Only when dictated' }).click();
		expect(onChange).toHaveBeenCalledWith([{ kind: 'fixed', key: 'No previous imaging available.', choice: { keep: 'dictated' }, source: 'creation' }]);
	});

	it('the normal report: tap a sentence to edit it or remove it', async () => {
		const onChange = vi.fn();
		render(StyleChecks, { checks: checks(), source: 'first_use_review', onChange });
		await page.getByRole('button', { name: 'Edit: The liver is normal in size.' }).click();
		await userEvent.fill(page.getByLabelText('Edit sentence'), 'The liver is unremarkable.');
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: liver', choice: { text: 'The liver is unremarkable.' }, source: 'first_use_review' }]);
		await page.getByRole('button', { name: 'Edit: The liver is normal in size.' }).click();
		await page.getByRole('button', { name: 'Remove', exact: true }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: liver', choice: { text: '' }, source: 'first_use_review' }]);
	});

	it('a covered structure without a normal: add wording or leave unmentioned', async () => {
		const onChange = vi.fn();
		render(StyleChecks, { checks: checks(), onChange });
		await page.getByRole('button', { name: 'Liver: gallbladder: Add wording' }).click();
		await userEvent.fill(page.getByLabelText('Wording for Liver: gallbladder'), 'The gallbladder is unremarkable.');
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: gallbladder', choice: { text: 'The gallbladder is unremarkable.' }, source: 'creation' }]);
		await page.getByRole('button', { name: 'Liver: gallbladder: Leave unmentioned' }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: gallbladder', choice: { text: '' }, source: 'creation' }]);
	});

	it('a line that may state a decided concept twice: remove it or keep both', async () => {
		const onChange = vi.fn();
		const dup = { id: 'duplicate:there is no prior study', kind: 'duplicate', step: 'style', title: 'There is no prior study.',
			evidence: [], note: 'May be stated twice: Comparison with previous imaging', ledger_kind: 'fixed', key: 'There is no prior study.',
			selected: null, rank: 3, choices: [{ id: 'remove', label: 'Remove this line', choice: { keep: 'remove' } },
				{ id: 'keep', label: 'Keep both', choice: { keep: 'always' } }] };
		render(StyleChecks, { checks: { ...checks(), duplicate_cards: [dup as never] }, onChange });
		await expect.element(page.getByText('May be stated twice: Comparison with previous imaging')).toBeInTheDocument();
		await page.getByRole('button', { name: 'There is no prior study.: Remove this line' }).click();
		expect(onChange).toHaveBeenCalledWith([{ kind: 'fixed', key: 'There is no prior study.', choice: { keep: 'remove' }, source: 'creation' }]);
	});

	it('renders nothing without checks', async () => {
		render(StyleChecks, { checks: null, onChange: vi.fn() });
		await expect.element(page.getByText('Your normal report')).not.toBeInTheDocument();
	});
});
```
- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/template-rules`
Expected: FAIL (`postSheetChecks` and `./StyleChecks.svelte` missing)

- [ ] **Step 3: Implement.** Append to `types.ts`:

```ts
export interface NormalSentence {
	key: string;
	text: string;
	kind: 'normal' | 'negative';
	paragraph: string;
}

export interface SheetChecksResponse {
	success: boolean;
	fixed_cards: DecisionCard[];
	duplicate_cards: DecisionCard[];
	normal_report: { section: string; header: string; sentences: NormalSentence[] }[];
	uncovered_cards: DecisionCard[];
	unmatched_cards: DecisionCard[];
	stale_quotes: string[];
	errors: string[];
}
```

In `api.ts` change the type import to `import type { ApplyResponse, DecideResponse, DecisionChange, LedgerEntry, SheetChecksResponse } from './types';` and append:

```ts
export const postSheetChecks = (token: string | null, body: { skill_sheet: string; decisions: LedgerEntry[] }) =>
	post<SheetChecksResponse>(token, 'sheet-checks', body);
```

Create `StyleChecks.svelte`:

```svelte
<script lang="ts">
	/**
	 * The Style step's checks (spec 2026-10-13-template-rules-step-design, cards "Always printed" and "Your normal
	 * report"), shown as report behaviour, never as the sheet. Every tap is one ledger change, applied at once by the
	 * parent (postApplyDecisions) so the sheet and these checks stay in step.
	 */
	import { changeFor } from './cards';
	import type { ChangeSource, DecisionCard, DecisionChange, NormalSentence, SheetChecksResponse } from './types';

	let {
		checks,
		source = 'creation',
		busy = false,
		onChange
	}: {
		checks: SheetChecksResponse | null;
		source?: ChangeSource;
		busy?: boolean;
		onChange: (changes: DecisionChange[]) => void;
	} = $props();

	let editing = $state<string | null>(null);
	let draft = $state('');

	function tap(card: DecisionCard, choiceId: string) {
		const ch = card.choices.find((x) => x.id === choiceId);
		if (ch && ch.choice === null) {
			editing = card.id;
			draft = card.wording?.text ?? '';
			return;
		}
		const change = changeFor(card, { choiceId }, source);
		if (change) onChange([change]);
	}

	function saveCard(card: DecisionCard) {
		const editId = card.choices.find((x) => x.choice === null)?.id ?? 'edit';
		const change = changeFor(card, { choiceId: editId, edited: { text: draft } }, source);
		if (change) onChange([change]);
		editing = null;
	}

	function editSentence(s: NormalSentence) {
		editing = s.key;
		draft = s.text;
	}

	function saveSentence(s: NormalSentence, text: string) {
		onChange([{ kind: 'normal', key: s.key, choice: { text: text.trim() }, source }]);
		editing = null;
	}
</script>

{#snippet chips(card: DecisionCard)}
	<div class="flex flex-wrap gap-1.5">
		{#each card.choices as ch (ch.id)}
			<button type="button" class="text-xs px-2.5 py-1 rounded-full border border-white/10 text-gray-400 hover:text-gray-200"
				aria-label="{card.title}: {ch.label}" onclick={() => tap(card, ch.id)} disabled={busy}>{ch.label}</button>
		{/each}
	</div>
	{#if editing === card.id}
		<div class="flex gap-2 pt-1.5">
			<input class="input flex-1 text-sm" aria-label="Wording for {card.title}" bind:value={draft} />
			<button type="button" class="btn-primary text-xs" onclick={() => saveCard(card)} disabled={!draft.trim()}>Save</button>
		</div>
	{/if}
{/snippet}

{#if checks}
	<div class="space-y-4">
		{#if checks.unmatched_cards.length}
			<section class="space-y-2" aria-label="Needs a look">
				<h4 class="text-sm text-gray-200">Needs a look</h4>
				<p class="text-xs text-gray-500">Something you decided could not be found in the template any more.</p>
				{#each checks.unmatched_cards as card (card.id)}
					<div class="rounded-lg border border-white/10 p-3 space-y-1.5">
						<p class="text-sm text-gray-300">{card.title}</p>
						{@render chips(card)}
					</div>
				{/each}
			</section>
		{/if}

		{#if checks.duplicate_cards.length}
			<section class="space-y-2" aria-label="May be stated twice">
				<h4 class="text-sm text-gray-200">May be stated twice</h4>
				{#each checks.duplicate_cards as card (card.id)}
					<div class="rounded-lg border border-white/10 p-3 space-y-1.5">
						<p class="text-sm text-gray-300">“{card.title}”</p>
						{#if card.note}<p class="text-xs text-gray-500">{card.note}</p>{/if}
						{@render chips(card)}
					</div>
				{/each}
			</section>
		{/if}

		{#if checks.fixed_cards.length}
			<section class="space-y-2" aria-label="Always printed">
				<h4 class="text-sm text-gray-200">Always printed</h4>
				<p class="text-xs text-gray-500">These sentences go into every report. Each might not be true for every patient.</p>
				{#each checks.fixed_cards as card (card.id)}
					<div class="rounded-lg border border-white/10 p-3 space-y-1.5">
						<p class="text-sm text-gray-300">“{card.title}”</p>
						{@render chips(card)}
					</div>
				{/each}
			</section>
		{/if}

		{#if checks.normal_report.length}
			<section class="space-y-2" aria-label="Your normal report">
				<h4 class="text-sm text-gray-200">Your normal report</h4>
				<p class="text-xs text-gray-500">What an all-normal report will say. Tap a sentence to edit or remove it.</p>
				{#each checks.normal_report as sec (sec.section)}
					<div class="space-y-1">
						<p class="text-xs uppercase tracking-wider text-gray-500">{sec.header}</p>
						{#each sec.sentences as s (s.key)}
							{#if editing === s.key}
								<div class="flex gap-2">
									<input class="input flex-1 text-sm" aria-label="Edit sentence" bind:value={draft} />
									<button type="button" class="btn-primary text-xs" onclick={() => saveSentence(s, draft)} disabled={!draft.trim() || busy}>Save</button>
									<button type="button" class="btn-ghost text-xs" onclick={() => saveSentence(s, '')} disabled={busy}>Remove</button>
								</div>
							{:else}
								<button type="button" class="block text-left text-sm text-gray-300 hover:text-white" aria-label="Edit: {s.text}"
									onclick={() => editSentence(s)} disabled={busy}>{s.text}</button>
							{/if}
						{/each}
					</div>
				{/each}
			</section>
		{/if}

		{#if checks.uncovered_cards.length}
			<section class="space-y-2" aria-label="Mentioned but no normal sentence">
				<h4 class="text-sm text-gray-200">Mentioned in your examples but no normal sentence</h4>
				{#each checks.uncovered_cards as card (card.id)}
					<div class="rounded-lg border border-white/10 p-3 space-y-1.5">
						<p class="text-sm text-gray-300">{card.title}</p>
						{@render chips(card)}
					</div>
				{/each}
			</section>
		{/if}
	</div>
{/if}
```
- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/template-rules`
Expected: PASS (cards 5, api 3, RulesStep 6, StyleChecks 5)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/template-rules/types.ts frontend/src/lib/template-rules/api.ts frontend/src/lib/template-rules/api.test.ts frontend/src/lib/template-rules/StyleChecks.svelte frontend/src/lib/template-rules/StyleChecks.svelte.test.ts
git commit -m "feat(template-rules): StyleChecks (always printed, normal report, uncovered, needs a look)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```


### Task 36: Style checks in the creator and the refine panel; final suites

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte`
- Modify: `frontend/src/routes/components/TemplateRefinePanel.svelte`
- Test: `frontend/src/routes/components/TemplateRefinePanel.rules.svelte.test.ts` (extend)

- [ ] **Step 1: Write the failing test.** In `TemplateRefinePanel.rules.svelte.test.ts`, replace

```ts
afterEach(() => vi.unstubAllGlobals());
```

with

```ts
let checksBody: Record<string, unknown> = { success: true, fixed_cards: [], normal_report: [], uncovered_cards: [], unmatched_cards: [], stale_quotes: [], errors: [] };

afterEach(() => vi.unstubAllGlobals());
```

and in `routes`, replace

```ts
		if (url.endsWith('/skill-sheet/apply-decisions'))
```

with

```ts
		if (url.endsWith('/skill-sheet/sheet-checks')) return new Response(JSON.stringify(checksBody));
		if (url.endsWith('/skill-sheet/apply-decisions'))
```

then append:

```ts
describe('TemplateRefinePanel style checks', () => {
	it('shows how the report will read and applies a tap through the ledger', async () => {
		checksBody = { success: true, fixed_cards: [], duplicate_cards: [], uncovered_cards: [], unmatched_cards: [], stale_quotes: [], errors: [],
			normal_report: [{ section: 'FINDINGS', header: 'Findings:', sentences: [{ key: 'Heart :: pericardium', text: 'The pericardium is normal.', kind: 'normal', paragraph: 'Heart' }] }] };
		const calls: { url: string; body: any; method: string }[] = [];
		vi.stubGlobal('fetch', routes(calls));
		render(TemplateRefinePanel, { template });
		await page.getByText('How your report will read').click();
		await page.getByRole('button', { name: 'Edit: The pericardium is normal.' }).click();
		await page.getByRole('button', { name: 'Remove', exact: true }).click();
		await vi.waitFor(() => expect(calls.some((c) => c.url.endsWith('/apply-decisions'))).toBe(true));
		const apply = calls.find((c) => c.url.endsWith('/apply-decisions'))!;
		expect(apply.body.changes).toEqual([{ kind: 'normal', key: 'Heart :: pericardium', choice: { text: '' }, source: 'first_use_review' }]);
	});
});
```
- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run --project client src/routes/components/TemplateRefinePanel.rules.svelte.test.ts`
Expected: FAIL (no "How your report will read")

- [ ] **Step 3: Creator edits** (`SkillSheetCreator.svelte`, on top of Task 25; each `old` occurs exactly once)

1. Imports. Replace

```svelte
	import RulesStep from '$lib/template-rules/RulesStep.svelte';
	import { postDecide } from '$lib/template-rules/api';
```

with

```svelte
	import RulesStep from '$lib/template-rules/RulesStep.svelte';
	import StyleChecks from '$lib/template-rules/StyleChecks.svelte';
	import { postApplyDecisions, postDecide, postSheetChecks } from '$lib/template-rules/api';
```

2. State. Replace

```svelte
	const NO_PRECHECK = "We couldn't pre-check your rules; review them on the Style step.";
```

with

```svelte
	const NO_PRECHECK = "We couldn't pre-check your rules; review them on the Style step.";
	/** @type {import('$lib/template-rules/types').SheetChecksResponse | null} */
	let checks = null;
	let styleBusy = false;
```

3. Load the checks and apply a Style-step tap (before `rejectTurn`). Replace

```svelte
	function rejectTurn(/** @type {number} */ assistantIndex) {
```

with

```svelte
	/** The Style step's checks for the sheet in hand (fail-soft: the summary shows alone). */
	async function loadChecks() {
		try {
			const r = await postSheetChecks($token, { skill_sheet: skillSheet, decisions });
			checks = r.success ? r : null;
		} catch (e) {
			checks = null;
		}
	}

	/** @param {import('$lib/template-rules/types').DecisionChange[]} changes */
	async function applyStyle(changes) {
		styleBusy = true;
		error = '';
		try {
			const r = await postApplyDecisions($token, { skill_sheet: skillSheet, decisions, changes, source: 'creation' });
			if (!r.success) throw new Error(r.error || 'Could not apply that choice');
			if (r.skill_sheet !== skillSheet && testReport) previewStale = true;
			skillSheet = r.skill_sheet;
			decisions = r.decisions;
			await loadChecks();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			styleBusy = false;
		}
	}

	function rejectTurn(/** @type {number} */ assistantIndex) {
```

4. Run the checks once the sheet is built. Replace

```svelte
			lastAnalyzedSnapshot = currentExamplesSnapshot;
			phase = 2;
```

with

```svelte
			lastAnalyzedSnapshot = currentExamplesSnapshot;
			phase = 2;
			checks = null;
			loadChecks();
```

5. Re-run them after an applied chat edit. Replace

```svelte
			if (Array.isArray(data.decisions)) decisions = data.decisions;
```

with

```svelte
			if (Array.isArray(data.decisions)) decisions = data.decisions;
			if (data.applied !== false) loadChecks();
```

6. Markup: the checks under the Style summary. Replace

```svelte
								<p class="text-sm text-gray-600">No summary available.</p>
							{/if}
```

with

```svelte
								<p class="text-sm text-gray-600">No summary available.</p>
							{/if}
							<div class="pt-4">
								<StyleChecks {checks} source="creation" busy={styleBusy} onChange={applyStyle} />
							</div>
```

- [ ] **Step 4: Refine-panel edits** (`TemplateRefinePanel.svelte`, on top of Task 26)

1. Imports. Replace

```svelte
	import RulesStep from '$lib/template-rules/RulesStep.svelte';
	import { postApplyDecisions, postDecide } from '$lib/template-rules/api';
```

with

```svelte
	import RulesStep from '$lib/template-rules/RulesStep.svelte';
	import StyleChecks from '$lib/template-rules/StyleChecks.svelte';
	import { postApplyDecisions, postDecide, postSheetChecks } from '$lib/template-rules/api';
```

2. State. Replace

```svelte
	let reviewDone = false;
```

with

```svelte
	let reviewDone = false;
	/** @type {import('$lib/template-rules/types').SheetChecksResponse | null} */
	let checks = null;
```

3. Opening a template also loads its checks. Replace

```svelte
		reviewDone = false;
		loadReview(template);
	}
```

with

```svelte
		reviewDone = false;
		checks = null;
		loadReview(template);
		loadChecks();
	}

	async function loadChecks() {
		try {
			const r = await postSheetChecks($token, { skill_sheet: skillSheet, decisions });
			checks = r.success ? r : null;
		} catch (e) {
			checks = null;
		}
	}
```

4. After an applied review, refresh the checks. Replace

```svelte
			hasChanges = true;
			reviewDone = true;
```

with

```svelte
			hasChanges = true;
			reviewDone = true;
			await loadChecks();
```

5. Markup: the checks after the review. Replace

```svelte
				</details>
			{/if}
			{#if chatHistory.length === 0}
```

with

```svelte
				</details>
			{/if}
			{#if checks && (checks.fixed_cards.length || checks.duplicate_cards.length || checks.normal_report.length || checks.uncovered_cards.length || checks.unmatched_cards.length)}
				<details class="rounded-lg border border-white/10 p-3">
					<summary class="text-sm text-gray-200 cursor-pointer">How your report will read</summary>
					<div class="pt-3">
						<StyleChecks {checks} source="first_use_review" busy={reviewBusy} onChange={applyReview} />
					</div>
				</details>
			{/if}
			{#if chatHistory.length === 0}
```

- [ ] **Step 5: Run the frontend suites**

Run: `cd frontend && npx vitest run 2>&1 | tail -6`
Expected: 739 tests, 738 pass. The only failure is the known `page.svelte.spec` h1 test (the scratch run of this plan gave exactly that).

Run: `cd frontend && npm run check 2>&1 | tail -3`
Expected: at or below the 1194 baseline (the scratch run gave 1193 errors).

- [ ] **Step 6: Manual run.** Create a template from 3 examples, answer the Rules cards, and on the Style step tap an "Always printed" line ("Only when dictated") and edit a normal sentence. Then Test: the preview reflects both. Open an upgraded template in the refine panel: "Your template's rules" and "How your report will read" appear. Save, and the stored config holds `decisions`.

- [ ] **Step 7: Backend suite, then commit**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: 0 failures

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte frontend/src/routes/components/TemplateRefinePanel.svelte frontend/src/routes/components/TemplateRefinePanel.rules.svelte.test.ts
git commit -m "feat(template-rules): Style-step checks in the creator and the refine panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

**Final checkpoint:** independent review of the whole branch (superpowers:requesting-code-review). Merge only on Hassan's go-ahead. Never push from this worktree.

---

## Ledger API for the chat-edit router (next roadmap item)

The router's rule kinds (value, concept, fixed, normal) call these in-process. No HTTP is needed; `/apply-decisions` is for cards only and refuses source "chat".

```python
from rapid_reports_ai import template_decisions as td, template_ledger_apply as tla, template_rules_cards as trc
from rapid_reports_ai import template_sheet_grammar as tsg, template_sheet_save as tsave

# What a targeted call sees for its kind (only its part of the sheet):
st = tsg.parse_sheet(sheet, mode="template").structure
current = tla.observe(st, kind, key)   # the choice the sheet expresses now; None: paragraph gone or not unique

# A structured change {"change": kind, ...} becomes one validated ledger write:
#   value   key = value name               choice {"need": "every" | "relevant" | "not_needed"}
#   concept key in td.CONCEPTS              choice {"use": bool, "default": str, "when_met": str,
#                                                   "condition": one of td.CONCEPTS[key].conditions (optional when
#                                                   the concept has one), "dictated": bool}
#   fixed   key = the FIXED line's text     choice {"keep": "always" | "dictated" | "remove"} (refused on a
#                                                   concept's own wording)
#   normal  key = td.normal_key(paragraph, structure) or td.negative_key(paragraph, text); choice {"text": str}
ledger, change = td.set_decision(ledger, kind, key, choice, source="chat")   # never mutates; change None = no-op
# td.DecisionError = code rejects the change (unknown target or concept, wrong condition, quotes or a {slot} in
# normal wording, a fixed entry on a concept's line): nothing is applied for that part; the reply asks, or shows
# trc.card_for_change for a valid proposal.

# Apply: either directly (pure, lint-guarded, idempotent) ...
res = tla.apply_ledger(sheet, ledger)   # res.sheet, .applied, .unmatched (→ cards), .failed (bug), .stale_quotes
# ... or through the save function, as every save does (a chat rewrite is reconciled first, D3 included):
out = await tsave.vet_sheet(sheet, origin="chat", previous=stored_sheet, ledger=ledger)
#     out.sheet, out.ledger, out.ledger_changes (named in the reply), out.ledger_cards (whole items kept, D3)
ledger, changes, cards = tla.reconcile_chat(before_sheet, after_sheet, ledger)   # the same step, standalone

# Reply line for a change to a confirmed item ("" for new or default items):
td.describe_change(change)       # "This changes something you confirmed: ECV every report → not needed."

# Undo a rejected change (the behavioral_claim loop): the old entry comes back whole (choice, by, at, source)
ledger = td.undo_change(ledger, change)

# Uncertain or rejected parts become the same one-tap card the Rules step uses (prefilled, not pre-selected):
card = trc.card_for_change(kind, key, proposed_choice)
```

Out of scope here, for the router's own plan: `layout` (section and paragraph operations) has no ledger kind; style edits are prose-only with the unit-line guard.

## Spec coverage (self-review)

| Spec item | Task(s) |
|---|---|
| New flow 1-6 (paste → decision run → Rules → writer → Style checks → Test/Refine/Create) | 13-18, 22-25, 28, 31, 32-36 |
| Cards table: Required values, Study-level wording, Disagree, Always printed, Your normal report (+ "mentioned but no normal") | 16-17, 24, 32, 35 |
| Exceptions only, ranked, ~8, kept-as-is collapsed, no confirm-all, evidence as report numbers, nothing partial pre-ticked, quotes checked by code | 13, 16, 23, 24 |
| "Only when relevant" recorded, not required; habit candidates recorded hidden | 2, 4 (`relevant` never listed), 14 (`evidence.habits` stored in `rules_step`) |
| Decision ledger `{kind, key, choice, by, at, source}`, four kinds, applied last on every origin (creation, chat, rebuild, restore, upgrade) | 2-12 |
| Stable keys only; unmatched → re-insert (values, concepts) or card at next review (normals, fixed) | 4-6, 32 (`unmatched_cards`), 35-36 |
| Automatic writes never override; chat updates the ledger and says so; whole-item removals kept and carded (D3) | 7, 8, 9 (PUT keeps the ledger), 10 |
| Prose not rewritten; lint for stale quotes in free prose | 6 (`stale_quotes`), 8, 12, 32 |
| Existing templates: decision run on first edit from stored examples; without examples only Style cards | 15, 18, 26, 36 |
| Failure table (run fails, Jev fails, quote not found, writer drift, ledger edit fails lint, sheet checks fail, step skipped) | 14, 18, 25 (notice), 13, 8 (`ledger_drift`), 4 (`failed`), 32-34, 24-25 (Skip → defaults) |
| Testing: unit (card builder, each ledger op round-tripped, key matching after rewording, unmatched → cards, never override, chat updates) | 3-8, 16-17, 32 |
| Testing: frontend (card states, budget, kept list, three-way chip, tap-to-edit normal report, skipped step) | 23-24, 26, 35-36 |
| Labs before wiring, synthetic seeded from production, planted truth (non-contrast sets included), Hassan spot-checks, real held out, generator never under test | 19-21 (before Phase 3), 29-30 (before Task 31), 33 (before Task 36) |
| Roadmap §4 creation-time FIXED check (absence backstop + Jev) | 32-33 |
| Roadmap §5 writer items (concepts as defaults, values proposed, slot conflict, temperature lab) | 2/5 (concept defaults), 13 (values proposed), 28 (slot wording), 29-30 (temperature arms) |
| Item 1 resolves the comparison concept (FIXED default + one REPLACE with the standard condition), the default-only drop rule (D2) and both contrast polarities (D1) | 2, 5 (`test_item_one_resolves_…`, `test_a_default_only_concept_gets_a_drop_rule…`, `test_contrast_takes_the_condition_opposite…`) |
| Measuring after launch | evidence only: `[ledger]` and `[decision-run]` log lines, `rules_step` record, `ledger_drift`; the dashboards are not in this plan |

## Risks

1. **A writer line beside the concept's own.** If the writer words "no prior" on another line, the ledger adds the standard pair and two sentences can print. Mitigations: the decided prompt (Task 28), drift logging, the "May be stated twice" cards (Task 32), and the duplicate count in the writer lab (Task 33 Step 7). Jev decides what counts as a duplicate, so its precision is unknown until that lab.
2. **Contrast polarity (D1).** The default comes from report counts, and the condition is the opposite state. A Qwen state label that is wrong flips the polarity. The card shows "Usually … / When <condition> …", the decide lab scores polarity against planted truth (`polarity_correct`), and non-contrast sets are planted.
3. **The ledger owns the value list.** Once any value is decided, an automatic rebuild cannot add a value without a card or a chat turn. A value the writer finds can be dropped; it is counted as drift.
4. **Chat rewrites of single decided items are trusted (spec).** Each one is named in the reply, and the creator's reject restores both the sheet and the ledger. The refine panel has no reject loop, so the router plan should add one. Whole-item removals are never trusted (D3).
5. **New Jev questions** (concept stated, FIXED variable, concept duplicate). Their 0.5 thresholds are placeholders until the labs.
6. **Synthetic sets may be cleaner than production.** The generator notes how; real held-out sets are reported apart.
7. **First-use run cost:** one paid run per template with stored examples, stamped on the server (review fix 4).
8. **Existing upgraded sheets** whose writer used non-standard conditions for these concepts are not recognised as concepts until the first-use review decides them. Their FIXED defaults stay checkable by the Style FIXED check (review fix 9).

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-13-rules-step.md`. Two execution options:

1. **Subagent-driven (recommended).** A fresh subagent per task, a review between tasks. Controller-run tasks (20, 21, 30, 33 Steps 5-7) stay with the controller.
2. **Inline execution** with superpowers:executing-plans, in batches with checkpoints at the end of each phase.

The labs are reported, not gated: each one ends with a report and recommendations, and Hassan decides before the wiring task that follows it.
