# Value Cluster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a templated scratchpad session, the template's required values (its `LIST_MISSING` items) show as chips at the top of the scratchpad, and Generate writes exactly what was decided.
- Jev decides which values the dictation states, and code reads each number.
- The radiologist types the rest or marks them N/A.
- Confirm waits until every chip is resolved.

**Architecture:** This builds on `feat/context-rules`, which already settles context rules by Jev and applies them by code before the lean Generate.

Backend:
- A new endpoint, `POST /api/canvas/stack/values`, sends parallel Jev calls of about 4 items each. Each item gets a `noul` "stated?" question and a `choice` "which clause?" question, and code reads the number from the chosen clause.
- `/slim-sheet` also returns the item list.
- At Generate, code removes the `LIST_MISSING` lines from the sheet the generator reads, and the stack brief tells the generator to write no missing-values list.
- Beside the post-generation check, a **backstop** runs: one Jev call with a `q_stated` noul per **filled** item, asking whether the *report* states it. Any "no" is added to that list's N/A items and flagged `value_missing` in `quality_check["review"]`.
- After the post-generation check, code writes the literal `Values not provided: <items>.` line at the list's position (TOP or END of its section). It also strips any line the generator wrote in that wording.

Frontend:
- A pure `values.ts` module holds the chip state machine. States are `filled`, `entered`, `na`, `open`, plus `check` (stated, but Jev named no clause) and `filling` (a fill is running).
- A small `ValueChips.svelte` component renders the chips.
- `HybridStackView` adds `open` and `check` chips to the Confirm blockers and the walkthrough, with the ring highlight.
- `DictationScratchpad` runs the fill when the slim sheet loads and at the `gateReview` hook. Chip states go into `gateKey`, and `filling` holds Confirm ("Updating…").
- `buildFindingsBlock` writes **typed** values as "Answered by the radiologist: …".
- `TemplateForm` sends the N/A items.

**Tech Stack:**
- Backend: FastAPI, pydantic, httpx (Jev via `jev_client.jev_post`), pytest (asyncio auto).
- Frontend: SvelteKit, with Svelte 5 runes components (legacy `$:` in `DictationScratchpad`).
- Frontend tests: vitest, with a server project for `*.test.ts` and a browser project for `*.svelte.test.ts`.

---

## Context for the implementer (read once)

- **Spec:** `docs/superpowers/specs/2026-10-12-template-requirements-design.md`, part 1 ("Required values — the value cluster") only. The roadmap entry is `docs/superpowers/specs/2026-10-13-template-rules-next-design.md` item 2.
  - **Out of scope:** template-editor chips, required statements (part 2), and any grammar change.
  - Open question 1 is answered: every template now has a grammar sheet.
- **Departures from the spec text, by Hassan's decision on 2026-10-13:**
  - (A) Only **entered** (typed) chips become "Answered by the radiologist" statements. Filled chips are display and check only; their numbers reach the report only through the dictation.
  - (B) The N/A line is always the literal `Values not provided: <items>.` for every template. Code writes it; the generator does not.
- **Worktree:** `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/value-cluster`, branch `feat/value-cluster` (from `feat/context-rules` at `6026fd7b`).
  - Never push, never use `git stash`, and never touch other worktrees.
  - Commit with the trailer lines below.
- **Principles:**
  - Jev decides and code applies; no model writes a number.
  - Judgements about meaning are validated Jev questions. Regex is used only on the grammar's own syntax, on digits, and on our own literal "Values not provided".
  - Each decision has one owner.
  - Fail-soft: a Jev error leaves every chip `open`, and the scratchpad never blocks on the network.
  - Prompts stay case-agnostic.
- **Commands:**
  - Backend, from `backend/`: `.venv/bin/python -m pytest <path> -q`. Pytest's `pythonpath=src` handles imports; the editable install points elsewhere.
  - Backend full suite: `.venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`. Baseline: **3878 passed**.
  - Frontend, from `frontend/`: `bunx vitest run <path>`; full run `bunx vitest run`. Baseline: **716/717**; the one failure is the known `page.svelte.spec` h1.
  - svelte-check: `bun run check`. Baseline: **1194**.
- **Commit trailer** (every commit):
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit
  ```

### What exists (cited)

**Backend Jev questions** (`backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py`):
- `ask_stated` (`:122-131`) is the model shape: one Jev call, `noul` per key, read as `float(... or 0.0)`.
- `ask_checks` (`:106-119`) and `ask_conditions` (`:297-308`) work the same way.
- `chip_question` (`:47-51`) and `parse_command` (`:74-84`) show the `choice` shape: `{"type": "choice", "criteria": {key: text}}`, answered as `{"choice": key, "confidence": x}`.
- `ask_unfinished` (`:274-291`) shows parallel batches through `asyncio.gather`.
- Constants: `TIMEOUT_S = 3.0` (`:13`), `NONE = "none"` (`:14`), and `STATED_MIN = 0.8` (`:135`; scratchpad lab, 0 false "stated").

**The validated `LIST_MISSING` wording.** `template_brief.q_stated(item)` (`backend/src/rapid_reports_ai/template_brief.py:105-113`) is the brief's per-item "stated" question.
- It has true/false criteria, and counts a negative result as stated.
- The brief asks it per item at `template_brief.py:424-427`, with cut-off `MET` 0.5 at `:835-841`.
- This plan uses it as the default wording (arm A). The lab compares it with the spec's plain wording (arm B).

**Number masking.** `template_number_check._masked(text, header_lines)` (`backend/src/rapid_reports_ai/template_number_check.py:70-76`) blanks list markers, identifiers (T2, L4/5), dates and times, and keeps the text length (`_MASKS` at `:50-59`). The new number reader reuses it.

**Sentence split.** `hybrid_stack/units.sentences` (`backend/src/rapid_reports_ai/hybrid_stack/units.py:24`).

**Template structure:**
- `hybrid_stack/template.template_structure(config)` (`template.py:13-30`) returns the session's parsed structure, or `None`.
- `norm_key` (`template.py:71-74`) ignores case, spacing and a final full stop.
- For `list_missing` rules, `Rule.items`, `Rule.position` and `Rule.section` are at `backend/src/rapid_reports_ai/template_sheet_structure.py:101-113`.
- `Rule.source_lines[0]` is the raw sheet line. `template_context_rules.apply_rules` matches rule lines that way (`template_context_rules.py:70-72`).
- `StructSection.name/role/header` are at `template_sheet_structure.py:74-79`.
- The grammar parses `LIST_MISSING [...] AT TOP|END` at `template_sheet_grammar.py:198`.
- A `LIST_MISSING` under `## Report-wide` belongs to the first findings-role section (`template_sheet_grammar.py:50-53`).
- `template_context_rules._clean(sheet)` (`:33-40`) returns the parsed structure of a lint-clean grammar sheet, else `None`.

**Report sections** (for placing the line by code):
- `template_lean.report_sections(report, sheet)` (`template_lean.py:56-96`) builds the section list.
- `report_review.section_spans(report, sections)` (`report_review.py:386-396`) gives `(section, start, end)`. A headed section starts after its header line, and an implicit body section has `name="FINDINGS"`.

**Stack routes** (`backend/src/rapid_reports_ai/hybrid_stack/routes.py`):
- `/slim-sheet` is at `:338-359`; its template branch is `:344-349`, and `SlimResult` is `:147-152`.
- `/assumed` (`:251-267`) reads the template owner-only, via `get_template(db, req.template_id, str(user.id))`.
- Route tests are in `backend/tests/test_hybrid_stack_routes.py`: the `authed` fixture is `:20-28`, the template-row pattern is `:267-288`, and `_RULED_SHEET` is `:255-264`.

**The Generate path:**
- `main.py:672-679` defines `TemplateGenerateRequest` with the `stack*` fields.
- `main.py:1912-1913` builds `_stack`, and `main.py:1944-1947` calls `template_lean.generate_template_report_lean(..., stack=_stack)`.
- `template_lean.py:438-452` (`gen()`) runs `resolve_context_rules`, then `decided_block`, then the generator.
- `template_lean.py:513-537` runs the post-generation check, then the number flags and the signature.
- `template_manager.py:2573-2583` builds the stack brief through `stack_brief(skill_sheet, conclusion, declined)`.
- `template_stack.stack_brief` (`template_stack.py:53-103`) keeps RULE lines.
- `template_pipeline.candidate_record` (`template_pipeline.py:375-383`) carries `context_rules`.
- Endpoint tests are in `backend/tests/test_template_generate_endpoint.py:371-386` (`stubs["mirror"][i]` holds the lean kwargs).
- Lean tests are in `backend/tests/test_template_lean.py:136-172` (`_gen_fakes`; the fake check appends `"\nCHECKED"`).

**Frontend:**
- `frontend/src/lib/components/DictationScratchpad.svelte`:
  - `gateKey` is at `:365-367`; the gate re-arms at `:368-371`.
  - The `gateReview` hook is at `:1579-1600`, scheduled by `scheduleReview` (`:1570-1576`) once the mic is off and the text has been still for `REVIEW_IDLE_MS = 800` (`:274`).
  - `loadSlimSheet` (`:1791-1809`) is how a session gets the template's region normals.
  - `stackConfirm` (`:1950-1985`) builds the `GateRecord`; `resetStack` is at `:2024-2061`.
  - The `<HybridStackView …>` props are at `:2633-2640`, including `syncing` at `:2640`.
- `frontend/src/lib/hybrid-stack/HybridStackView.svelte`:
  - Props are at `:24-158`.
  - The Confirm blockers (`stops`) are at `:285-295`: open referral rows, then blocking checks. The spec cites `:273-275`, but the code has moved.
  - The current-stop ring is `current === \`row:…\` ? 'ring-2 ring-orange-400/60'` (`:899`, `:701`).
  - The walkthrough bar is at `:1134-1153`; the Confirm bar at `:1154-1176`.
  - Keydown handling: `walkKey` (`:356-370`) ignores keys typed in an INPUT.
- `frontend/src/lib/hybrid-stack/regionState.ts:108-140` is `buildFindingsBlock`; the `ANSWERED` prefix is at `:108`.
- `frontend/src/lib/hybrid-stack/types.ts`: `SlimSheet` at `:59`, `GateRecord` at `:71-92`.
- `frontend/src/lib/hybrid-stack/api.ts`: `post()` at `:5-11`, `postSlimSheet` at `:66-67`.
- `frontend/src/routes/components/TemplateForm.svelte:460-464` sends `stack`, `stack_declined` and `stack_conclusion`.
- No new frontend route is added, so no `$lib/guards/dev-route` guard is needed.

### Decisions

1. **How code finds the matched sentence.**
   - In the same Jev call, each item also gets a `choice`: "Which SENTENCE of the DICTATION gives the value of this item?" The options are only the dictation's **clauses that hold a number** (sentences split at commas and semicolons not inside a number).
   - `MAX_CLAUSES = 80`: the cap is **raised, not windowed**. A long CMR dictation holds roughly 30–50 numbers. If a dictation exceeds 80, the later clauses are not offered, and an item whose clause was cut becomes a `check` chip.
   - Code reads the chosen clause. Exactly one number (after masking identifiers, dates and times) gives the value with its unit as written, including `mL/m^2`. Zero numbers, two numbers or a range give no value.
2. **A false "stated" silently drops a value, so the strict threshold comes first.**
   - `VALUE_STATED_MIN = STATED_MIN` (0.8), the scratchpad's lab-tested bar. The lab's headline is the **false-stated rate**, and it reports the lower thresholds as alternatives.
   - A stated item for which Jev named no clause becomes a `check` chip ("stated?"). It is a walkthrough stop until the radiologist keeps it, types a value, or marks N/A.
3. **Wording.** Arm A is `template_brief.q_stated` (the default); arm B is the plain spec wording. The lab compares them, and Hassan chooses.
4. **FINDINGS (Hassan, A).** Only entered values go in, as one standalone paragraph: `Answered by the radiologist: LVEDVi 98 mL/m².` (items carry no region).
5. **The N/A line (Hassan, B).**
   - When the client sent the values and code rewrote the sheet cleanly, every matched `LIST_MISSING` line leaves the sheet the generator reads.
   - The stack brief adds "write no list of missing values".
   - After the post-generation check, code strips any generator line beginning "Values not provided" and writes `Values not provided: <N/A items>.` at TOP or END of the list's section. The section is found by its sheet name or header in the report's sections, else the first findings section, else the report itself.
   - An item on two lists is listed once.
   - This replaces the earlier `NA_CONDITION` idea, whose findings condition was never met by FINDINGS text.
6. **Fail-soft consistency.**
   - `values_decided` is passed to the generator as `{**stack, "values_decided": ok}`, where `ok` is true only when `apply_required_values` applied cleanly: no error, no skip, every list line matched.
   - When it is false, the generator reads the sheet with its `LIST_MISSING` line, gets no extra session rule, and code writes nothing. This is today's behaviour.
   - An old client sends no `stack_values_na`, so everything stays as today.
7. **Where the chip list comes from.**
   - `/slim-sheet` (template branch) returns `required_values`, so the chips show `open` from the start, and the first fill runs as soon as the slim sheet loads if there is text.
   - `/values` re-reads the template server-side; it never trusts the item list from the client.
8. **Chip ownership.**
   - A fill never overrides `entered` or `na`.
   - A `check` chip the radiologist kept stays kept on the next fill while Jev still names no clause.
   - A filled chip the next fill does not confirm goes back to `open`.
   - Any chip edit re-arms the gate through `gateKey`.
   - While a fill runs, every other chip is `filling`: Confirm shows "Updating…" and the chip shows "…".
9. **Post-generation backstop for filled chips.** A false "stated" must never let a required value vanish from both the report and the N/A line.
   - The client sends the filled items (`stack_values_filled`).
   - In parallel with the post-generation check, one Jev call (batches of `VALUE_BATCH`, state `REPORT:`) asks the `q_stated` question per filled item against the generated report. The threshold is `BACKSTOP_MIN = 0.5`, because this check is recall-oriented; the lab reports the alternatives.
   - Code adds each "no" to its list's N/A items, so it appears in the `Values not provided` line (created at the list's position when absent). It also adds a review flag `{"kind": "value_missing", "text": item, "message": "Required value <item> not found in the report"}`.
   - A Jev failure leaves the report as it is, records the error, and adds no flags.
   - With no filled items, no call is made.
   - The backstop runs only when code took over the lists (`values_applied`).

### Where the lab sits

Task 4, the lab, comes **after** the Jev question and the smart fill exist in code (Tasks 1–3), and **before** the endpoint and wiring (Tasks 5–12).
- The wiring does not depend on the lab's numbers.
- **The lab may change the design, not just a constant.** For example, if clause-choice accuracy is poor, a per-clause Jev yes/no "this SENTENCE gives the <item>" could replace the choice question. Hassan decides after the lab (Task 4, Step 8).
- The controller may let a code agent run Tasks 5–12 while the lab data is being written. **No merge before Hassan has read the lab report** and an independent review has run (Task 13).

## File structure

| File | Responsibility |
|---|---|
| Create `backend/src/rapid_reports_ai/hybrid_stack/values.py` | Clauses, the number reader, `smart_fill` (Jev answers → chips). Fail-soft. |
| Modify `backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py` | `VALUE_STATED_MIN`, `VALUE_BATCH`, `BACKSTOP_MIN`, the two questions, `ask_values` and `ask_report_values` (parallel batches). |
| Modify `backend/src/rapid_reports_ai/hybrid_stack/template.py` | `template_required_values(st)`: the `LIST_MISSING` items in sheet order, each once. |
| Modify `backend/src/rapid_reports_ai/hybrid_stack/routes.py` | `SlimResult.required_values`, `POST /values`. |
| Create `backend/src/rapid_reports_ai/template_required_values.py` | `apply_required_values` (the sheet), `values_applied`, `backstop` (filled values the report lacks), `write_missing` (the report line, by code). |
| Modify `backend/src/rapid_reports_ai/template_lean.py` | Apply before the generator; pass `values_decided`; backstop beside the check; write the line after it. |
| Modify `backend/src/rapid_reports_ai/template_stack.py` | `MISSING_VALUES_RULE` under `values_decided`. |
| Modify `backend/src/rapid_reports_ai/template_manager.py` | Read `stack["values_decided"]` for `stack_brief`. |
| Modify `backend/src/rapid_reports_ai/main.py` | `TemplateGenerateRequest.stack_values_na` / `stack_values_filled` → `_stack["values_na"]` / `_stack["values_filled"]`. |
| Modify `backend/src/rapid_reports_ai/template_pipeline.py` | The candidate record carries `required_values`. |
| Create `backend/src/rapid_reports_ai/scripts/value_cluster_lab.py` | The wording lab: arms, scoring, report. |
| Create `backend/tests/test_hybrid_stack_values.py`, `backend/tests/test_template_required_values.py`, `backend/tests/test_value_cluster_lab.py` | New tests. |
| Modify `backend/tests/test_hybrid_stack_jev_stack.py`, `test_hybrid_stack_routes.py`, `test_template_stack.py`, `test_template_lean.py`, `test_template_generate_endpoint.py` | New cases. |
| Create `frontend/src/lib/hybrid-stack/values.ts` (+ `values.test.ts`) | Chip state machine, labels, gate key, Generate statements. |
| Create `frontend/src/lib/hybrid-stack/ValueChips.svelte` (+ `.svelte.test.ts`) | The chip line: click to type, N/A, keep a stated value, Mark rest N/A, ring. |
| Modify `frontend/src/lib/hybrid-stack/types.ts`, `api.ts` (+ test), `regionState.ts` (+ test), `HybridStackView.svelte` (+ test) | Types, `postValues`, findings line, blockers. |
| Modify `frontend/src/lib/components/DictationScratchpad.svelte`, `frontend/src/routes/components/TemplateForm.svelte` | Session wiring and the Generate body. |
| Private, never in the repo: `~/Code/rr-template-conversion-private/synthetic/value_cluster/` | Lab fixtures and results. |

---

### Task 1: Clauses and the number reader

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/values.py`
- Test: `backend/tests/test_hybrid_stack_values.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_hybrid_stack_values.py`:

```python
import pytest

from rapid_reports_ai.hybrid_stack import values as V


@pytest.mark.parametrize("clause,value", [
    ("EF 45", "45"),
    ("ejection fraction mildly reduced at 45", "45"),
    ("LVEF=61%", "61%"),
    ("LVEF 55 %", "55%"),
    ("LVEF 45 percent", "45%"),
    ("LVEF 45.5%.", "45.5%"),
    ("LVEDVi 98 ml/m2", "98 ml/m2"),
    ("LVEDVi 98 mL/m^2", "98 mL/m^2"),
    ("LV mass index 60 g/m²", "60 g/m²"),
    ("aortic root 3.4 cm", "3.4 cm"),
    ("native T1 1,050 ms", "1,050 ms"),
    ("dated 02/12/2025 EF 50%", "50%"),
])
def test_read_value_reads_the_one_number_and_its_unit(clause, value):
    assert V.read_value(clause) == value


@pytest.mark.parametrize("clause", [
    "LVEDVi 98 and LVESVi 40 ml/m2",       # two numbers: stated, no single value
    "EF 45-50%",                           # a range
    "Conus terminates at L1/2",            # an identifier, not a measurement
    "No late gadolinium enhancement",
    "",
])
def test_read_value_gives_nothing_unless_exactly_one_number(clause):
    assert V.read_value(clause) is None


def test_identifiers_dates_and_times_are_not_numbers():
    assert not V.has_number("T2 and STIR sequences at L4/5")
    assert not V.has_number("Scanned 02/12/2025 at 10:30")
    assert V.has_number("RVEF 50%")


def test_clauses_split_sentences_at_commas_and_semicolons_but_not_inside_numbers():
    text = "LVEF 45%. LVEDVi 98 ml/m2, LVESVi 40 ml/m2; normal wall thickness.\nNative T1 1,050 ms."
    assert V.clauses(text) == ["LVEF 45%.", "LVEDVi 98 ml/m2", "LVESVi 40 ml/m2", "normal wall thickness.",
                               "Native T1 1,050 ms."]
    assert V.clauses("") == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_values.py -q`
Expected: FAIL with `ImportError: cannot import name 'values' from 'rapid_reports_ai.hybrid_stack'`.

- [ ] **Step 3: Write the minimal implementation**

Create `backend/src/rapid_reports_ai/hybrid_stack/values.py`:

```python
"""Required values of a templated scratchpad session (requirements spec 2026-10-12 part 1, the value cluster).

Jev decides which of the template's LIST_MISSING items the dictation states, and which clause states each
(jev_stack.ask_values); code reads the number from that clause. No model writes a number. A clause with no number,
two numbers or a range gives no value: the chip shows the item as stated. Fail-soft: any Jev failure leaves every
chip open (the radiologist enters the value or marks it N/A); the scratchpad never blocks on the network."""
from __future__ import annotations

import re
from typing import Optional

from ..template_number_check import _masked
from .units import sentences

_CLAUSE = re.compile(r"(?<!\d)[;,]|[;,](?!\d)")       # a comma or semicolon, except inside a number ("1,050")
_NUMBER = re.compile(r"(?<![\w.,])\d+(?:,\d{3})*(?:\.\d+)?")
_UNIT = re.compile(r"\s*(%|per ?cent\b|(?:mL|ml|g|kg|L|l|mm|cm|ms|s|m|cc|HU|mmHg|bpm)"
                   r"(?:/(?:m\^?2|m²|min|s|m|beat))?(?![A-Za-z0-9²]))")


def clauses(dictation: str) -> list[str]:
    """The dictation's sentences, each split at its commas and semicolons (never inside a number)."""
    out: list[str] = []
    for s in sentences(dictation or ""):
        out += [c.strip() for c in _CLAUSE.split(s) if c.strip()]
    return out


def _numbers(clause: str) -> list[re.Match]:
    """Number tokens, after list markers, identifiers (T2, L4/5), dates and times are blanked (same length)."""
    return list(_NUMBER.finditer(_masked(clause or "", set())))


def has_number(clause: str) -> bool:
    return bool(_numbers(clause))


def read_value(clause: str) -> Optional[str]:
    """The clause's one number with its unit as written ("45%", "98 ml/m2"); None for no number, two or a range."""
    found = _numbers(clause)
    if len(found) != 1:
        return None
    m = found[0]
    u = _UNIT.match(clause, m.end())
    if not u:
        return m.group(0)
    unit = u.group(1)
    return m.group(0) + ("%" if unit.replace(" ", "").lower() in ("%", "percent") else f" {unit}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_values.py -q`
Expected: PASS (19 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/values.py backend/tests/test_hybrid_stack_values.py
git commit -m "feat(values): clauses and a code number reader for required values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 2: The Jev question (`ask_values`, parallel batches)

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py` (append after `ask_conditions`, `:297-308`)
- Test: `backend/tests/test_hybrid_stack_jev_stack.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_hybrid_stack_jev_stack.py`:

```python
async def test_ask_values_asks_stated_and_where_per_item_in_one_call(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {
            "value_0": {"noul": 0.9}, "where_0": {"choice": "s_1"},
            "value_1": {"noul": 0.2}, "where_1": {"choice": "none"},
            "value_2": {"noul": 0.8}, "where_2": {"choice": "s_7"}}})
    out = await J.ask_values("LVEF 45%. RVEF 50%.", ["LVEF", "RVEF", "LV mass"], ["LVEF 45%.", "RVEF 50%."],
                             transport=httpx.MockTransport(handler))
    assert out == [(0.9, 1), (0.2, None), (0.8, None)]   # an out-of-range choice names no clause
    assert set(seen["questions"]) == {"value_0", "where_0", "value_1", "where_1", "value_2", "where_2"}
    assert seen["state"] == "DICTATION:\nLVEF 45%. RVEF 50%."
    assert seen["questions"]["value_0"]["type"] == "noul"
    assert seen["questions"]["value_0"]["instructions"].endswith("LVEF")      # template_brief.q_stated
    w = seen["questions"]["where_1"]
    assert w["type"] == "choice" and w["instructions"].endswith("RVEF")
    assert w["criteria"] == {"s_0": "LVEF 45%.", "s_1": "RVEF 50%.", "none": "No SENTENCE gives this item's value."}


async def test_ask_values_splits_items_into_parallel_batches_keeping_global_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    asked = []

    def handler(req):
        qs = json.loads(req.content)["questions"]
        asked.append(sorted(qs))
        return httpx.Response(200, json={"answers": {
            k: ({"noul": 0.9} if k.startswith("value_") else {"choice": "s_0"}) for k in qs}})
    items = ["A", "B", "C", "D", "E", "F"]
    out = await J.ask_values("A 1.", items, ["A 1."], transport=httpx.MockTransport(handler))
    assert out == [(0.9, 0)] * 6
    assert J.VALUE_BATCH == 4 and len(asked) == 2
    assert sorted(asked) == [sorted(f"{p}_{i}" for i in range(4) for p in ("value", "where")),
                             sorted(f"{p}_{i}" for i in (4, 5) for p in ("value", "where"))]


async def test_ask_values_without_clauses_asks_only_whether_stated(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"value_0": {"noul": 0.7}}})
    assert await J.ask_values("Conus at L1.", ["Conus level"], [], transport=httpx.MockTransport(handler)) == [(0.7, None)]
    assert list(seen["questions"]) == ["value_0"]

    def fail(req):
        raise AssertionError("no call without items")
    assert await J.ask_values("x", [], ["x 1"], transport=httpx.MockTransport(fail)) == []


async def test_ask_values_takes_another_stated_wording(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"value_0": {"noul": 0.6}}})
    plain = lambda item: {"type": "noul", "instructions": f"The DICTATION states the {item}."}   # noqa: E731
    await J.ask_values("EF 45.", ["LVEF"], [], transport=httpx.MockTransport(handler), stated=plain)
    assert seen["questions"]["value_0"]["instructions"] == "The DICTATION states the LVEF."


def test_the_value_cut_off_starts_at_the_scratchpads_strict_stated_bar():
    assert J.VALUE_STATED_MIN == J.STATED_MIN == 0.8
    assert J.BACKSTOP_MIN == 0.5   # the post-generation backstop is recall-oriented


async def test_ask_report_values_asks_the_report_per_item_in_batches(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.2 if k == "value_4" else 0.9} for k in body["questions"]}})
    items = ["A", "B", "C", "D", "E"]
    out = await J.ask_report_values("Findings:\nA 1.", items, transport=httpx.MockTransport(handler))
    assert out == [0.9, 0.9, 0.9, 0.9, 0.2] and len(bodies) == 2
    assert all(b["state"] == "REPORT:\nFindings:\nA 1." for b in bodies)
    assert bodies[0]["questions"]["value_0"]["instructions"].endswith("A")   # template_brief.q_stated

    def fail(req):
        raise AssertionError("no call without items")
    assert await J.ask_report_values("x", [], transport=httpx.MockTransport(fail)) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_jev_stack.py -q -k "ask_values or value_cut_off or report_values"`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.hybrid_stack.jev_stack' has no attribute 'ask_values'`.

- [ ] **Step 3: Write the minimal implementation**

In `backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py`, change `from typing import Any` to:

```python
from typing import Any, Callable, Optional
```

Then append at the end of the file:

```python
# ── Required values: the value cluster (requirements spec 2026-10-12 part 1) ──────────
# Per LIST_MISSING item, "stated?" (noul, value_<i>) and "which clause gives its value?" (choice over the dictation's
# clauses that hold a number, where_<i>). Code reads the number (hybrid_stack.values); Jev never does.
VALUE_STATED_MIN = STATED_MIN   # 0.8: a false "stated" silently drops a value from the cluster, so the strict
                                # scratchpad bar first; the value cluster lab reports the alternatives, Hassan sets it
VALUE_BATCH = 4                 # items per Jev call; batches run in parallel (12 items -> 3 calls)


def value_key(i: int) -> str:
    return f"value_{i}"


def where_key(i: int) -> str:
    return f"where_{i}"


def value_stated_question(item: str) -> dict[str, Any]:
    """Does the dictation state this required value? The brief's LIST_MISSING question (template_brief.q_stated)."""
    from ..template_brief import q_stated
    return q_stated(item)


def value_where_question(item: str, clauses: list[str]) -> dict[str, Any]:
    crit: dict[str, str] = {f"s_{k}": c for k, c in enumerate(clauses)}
    crit[NONE] = "No SENTENCE gives this item's value."
    return {"type": "choice", "instructions": f"Which SENTENCE of the DICTATION gives the value of this item: {item}",
            "criteria": crit}


async def ask_values(dictation: str, items: list[str], clauses: list[str], transport=None,
                     stated: Callable[[str], dict[str, Any]] = value_stated_question) -> list[tuple[float, Optional[int]]]:
    """(P stated, index into `clauses` of the clause that gives its value, or None) per item, in order. Items go in
    parallel calls of VALUE_BATCH; keys keep the item's global index. The clause question is asked only when there
    are clauses. `stated`: the wording (the lab passes its arms)."""
    if not items:
        return []
    key = os.environ.get("OPENROUTER_API_KEY", "")

    async def batch(start: int, chunk: list[str]) -> list[tuple[float, Optional[int]]]:
        qs: dict[str, dict[str, Any]] = {}
        for j, item in enumerate(chunk):
            qs[value_key(start + j)] = stated(item)
            if clauses:
                qs[where_key(start + j)] = value_where_question(item, clauses)
        r = await jev_post({"model": JEV_MODEL, "state": f"DICTATION:\n{dictation}", "questions": qs},
                           key, TIMEOUT_S * 2, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out: list[tuple[float, Optional[int]]] = []
        for j in range(len(chunk)):
            p = float((ans.get(value_key(start + j)) or {}).get("noul") or 0.0)
            c = (ans.get(where_key(start + j)) or {}).get("choice")
            k = int(c[2:]) if isinstance(c, str) and c.startswith("s_") and c[2:].isdigit() else None
            out.append((p, k if k is not None and k < len(clauses) else None))
        return out

    parts = await asyncio.gather(*(batch(k, items[k:k + VALUE_BATCH]) for k in range(0, len(items), VALUE_BATCH)))
    return [x for p in parts for x in p]


# Post-generation backstop (value cluster): does the generated REPORT state each value whose chip was filled? A "no"
# is listed as not provided and flagged by code (template_required_values.backstop). Recall-oriented.
BACKSTOP_MIN = 0.5   # provisional; the value cluster lab reports backstop recall on planted missing values


async def ask_report_values(report: str, items: list[str], transport=None,
                            stated: Callable[[str], dict[str, Any]] = value_stated_question) -> list[float]:
    """P(the report states the item) per item, in order; parallel calls of VALUE_BATCH."""
    if not items:
        return []
    key = os.environ.get("OPENROUTER_API_KEY", "")

    async def batch(start: int, chunk: list[str]) -> list[float]:
        qs = {value_key(start + j): stated(item) for j, item in enumerate(chunk)}
        r = await jev_post({"model": JEV_MODEL, "state": f"REPORT:\n{report}", "questions": qs},
                           key, TIMEOUT_S * 2, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        return [float((ans.get(value_key(start + j)) or {}).get("noul") or 0.0) for j in range(len(chunk))]

    parts = await asyncio.gather(*(batch(k, items[k:k + VALUE_BATCH]) for k in range(0, len(items), VALUE_BATCH)))
    return [x for p in parts for x in p]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_jev_stack.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py backend/tests/test_hybrid_stack_jev_stack.py
git commit -m "feat(values): Jev asks whether each required value is stated and where; report backstop question

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 3: The template's items and `smart_fill`

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/template.py` (append after `template_suppressions`, `:139-151`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/values.py`
- Test: `backend/tests/test_hybrid_stack_values.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_hybrid_stack_values.py`:

```python
from rapid_reports_ai.hybrid_stack.template import template_required_values
from rapid_reports_ai.template_sheet_grammar import parse_sheet

VALUES_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
"""


def test_required_values_are_the_list_missing_items_in_sheet_order_once():
    st = parse_sheet(VALUES_SHEET, mode="template").structure
    assert template_required_values(st) == ["LVEF", "LV mass index", "RVEF"]
    two = VALUES_SHEET + 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["lvef" | "LV wall thickness"] AT END\n'
    st = parse_sheet(two, mode="template").structure
    assert template_required_values(st) == ["LVEF", "LV mass index", "RVEF", "LV wall thickness"]
    plain = VALUES_SHEET.replace(
        'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP\n', "")
    assert template_required_values(parse_sheet(plain, mode="template").structure) == []


def _ask(answers, seen=None):
    async def ask(dictation, items, cands):
        if seen is not None:
            seen.update(dictation=dictation, items=items, cands=cands)
        return answers
    return ask


async def test_smart_fill_reads_the_number_from_the_clause_jev_names():
    seen = {}
    d = "Normal LV size, LVEF 45%. RV normal. LVEDVi 98 and LVESVi 40 ml/m2."
    res = await V.smart_fill(d, ["LVEF", "LVEDVi", "RVEF"], ask=_ask([(0.95, 0), (0.9, 1), (0.1, None)], seen))
    assert seen["cands"] == ["LVEF 45%.", "LVEDVi 98 and LVESVi 40 ml/m2."]   # only clauses holding a number
    assert [v.model_dump() for v in res.values] == [
        {"item": "LVEF", "state": "filled", "value": "45%", "quote": "LVEF 45%.", "score": 0.95},
        {"item": "LVEDVi", "state": "filled", "value": None, "quote": "LVEDVi 98 and LVESVi 40 ml/m2.", "score": 0.9},
        {"item": "RVEF", "state": "open", "value": None, "quote": None, "score": 0.1}]
    assert res.error is None


async def test_stated_without_a_named_clause_is_filled_without_a_value_or_quote():
    res = await V.smart_fill("Conus terminates at L1.", ["Conus level"], ask=_ask([(0.9, None)]))
    [v] = res.values
    assert (v.state, v.value, v.quote) == ("filled", None, None)   # the chip asks for a look (frontend "check")


async def test_below_the_cut_off_is_open():
    res = await V.smart_fill("EF 45.", ["LVEF"], ask=_ask([(V.VALUE_STATED_MIN - 0.01, 0)]))
    assert res.values[0].state == "open" and res.values[0].value is None


async def test_a_jev_failure_or_a_short_reply_leaves_every_chip_open():
    async def boom(*a):
        raise RuntimeError("jev down")
    res = await V.smart_fill("LVEF 45%.", ["LVEF", "RVEF"], ask=boom)
    assert [v.state for v in res.values] == ["open", "open"] and "RuntimeError" in res.error
    res = await V.smart_fill("LVEF 45%.", ["LVEF", "RVEF"], ask=_ask([(0.9, 0)]))
    assert [v.state for v in res.values] == ["open", "open"] and res.error == "jev: answer count mismatch"


async def test_no_items_or_no_dictation_asks_nothing():
    async def fail(*a):
        raise AssertionError("no call")
    assert (await V.smart_fill("LVEF 45%.", [], ask=fail)).values == []
    res = await V.smart_fill("  ", ["LVEF"], ask=fail)
    assert [v.state for v in res.values] == ["open"] and res.error is None


async def test_the_default_ask_is_the_jev_call(monkeypatch):
    seen = {}

    async def fake(dictation, items, cands):
        seen["items"] = items
        return [(0.9, 0)]
    monkeypatch.setattr(V, "ask_values", fake)
    res = await V.smart_fill("LVEF 45%.", ["LVEF"])
    assert seen["items"] == ["LVEF"] and res.values[0].value == "45%"


async def test_clauses_are_capped_at_max_clauses():
    seen = {}
    d = " ".join(f"Value {i} is {i}." for i in range(1, 100))
    await V.smart_fill(d, ["LVEF"], ask=_ask([(0.1, None)], seen))
    assert V.MAX_CLAUSES == 80 and len(seen["cands"]) == 80
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_values.py -q`
Expected: FAIL with `ImportError: cannot import name 'template_required_values'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `backend/src/rapid_reports_ai/hybrid_stack/template.py`:

```python
def template_required_values(st: SheetStructure) -> list[str]:
    """The values every report of this template carries (its LIST_MISSING items: the value cluster), in sheet
    order, each once (norm_key)."""
    out: list[str] = []
    seen: set[str] = set()
    for r in st.rules:
        if r.effect != "list_missing":
            continue
        for item in r.items:
            k = norm_key(item)
            if k and k not in seen:
                seen.add(k)
                out.append(item.strip())
    return out
```

In `backend/src/rapid_reports_ai/hybrid_stack/values.py`, replace the import block

```python
import re
from typing import Optional

from ..template_number_check import _masked
from .units import sentences
```

with

```python
import logging
import re
import time
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from ..template_number_check import _masked
from .jev_stack import VALUE_STATED_MIN, ask_values
from .units import sentences

logger = logging.getLogger(__name__)

MAX_ITEMS = 20     # the largest prod LIST_MISSING has 12 items
MAX_CLAUSES = 80   # numeric clauses offered to the "which clause" question: raised, not windowed (a long CMR dictation
                   # holds ~30-50 numbers); an item whose clause falls past the cap comes back stated without a quote,
                   # which the scratchpad shows as a chip to look at, never as a value
```

Then append at the end of `values.py`:

```python
class ValueFill(BaseModel):
    item: str
    state: Literal["filled", "open"] = "open"
    value: Optional[str] = None      # code's read; None when filled without one unambiguous number
    quote: Optional[str] = None      # the clause Jev named (None: stated, no clause named -> "check" chip)
    score: Optional[float] = None    # P(stated)


class ValuesResult(BaseModel):
    values: list[ValueFill] = Field(default_factory=list)
    ms: int = 0
    error: Optional[str] = None


Ask = Callable[[str, list[str], list[str]], Awaitable[list[tuple[float, Optional[int]]]]]


async def smart_fill(dictation: str, items: list[str], ask: Optional[Ask] = None) -> ValuesResult:
    """Each required value filled from the dictation or left open. Never raises; a Jev failure leaves every chip
    open with the error recorded."""
    t0 = time.perf_counter()
    items = [i for i in items if i.strip()][:MAX_ITEMS]

    def done(values: list[ValueFill], error: Optional[str] = None) -> ValuesResult:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.log(logging.WARNING if error else logging.INFO,
                   "[stack.values] items=%d filled=%d valued=%d unquoted=%d error=%s ms=%d", len(items),
                   sum(v.state == "filled" for v in values), sum(v.value is not None for v in values),
                   sum(v.state == "filled" and v.quote is None for v in values), error, ms)
        return ValuesResult(values=values, ms=ms, error=error)

    def all_open() -> list[ValueFill]:
        return [ValueFill(item=i) for i in items]

    if not items or not (dictation or "").strip():
        return done(all_open())
    cands = [c for c in clauses(dictation) if has_number(c)][:MAX_CLAUSES]
    try:
        answers = await (ask or ask_values)(dictation, items, cands)
    except Exception as e:  # noqa: BLE001 -- fail-soft: every chip open, the radiologist fills or marks N/A
        return done(all_open(), f"{type(e).__name__}: {e}"[:200])
    if len(answers) != len(items):
        return done(all_open(), "jev: answer count mismatch")
    out: list[ValueFill] = []
    for item, (p, k) in zip(items, answers):
        if p < VALUE_STATED_MIN:
            out.append(ValueFill(item=item, score=round(p, 3)))
            continue
        quote = cands[k] if k is not None and 0 <= k < len(cands) else None
        out.append(ValueFill(item=item, state="filled", value=read_value(quote) if quote else None, quote=quote,
                             score=round(p, 3)))
    return done(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_values.py tests/test_hybrid_stack_jev_stack.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/template.py backend/src/rapid_reports_ai/hybrid_stack/values.py backend/tests/test_hybrid_stack_values.py
git commit -m "feat(values): the template's required values and the smart fill (fail-soft: all open)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 4: LAB — the Jev wording lab for "Does the dictation state the <item>?" (controller-run)

**The controller runs this task, not a code agent.** It produces results and a recommendation; it does not gate. Hassan decides the wording, the threshold and any design change.

**Data.**
- **Synthetic:** Opus-written and seeded from the five `LIST_MISSING` sheets in `~/Code/rr-template-conversion-private/final/`, with the truth planted:
  - `cmr_non_stress_dr_sabeeh_syed` (6 items)
  - `cardiac_mr_2` (12 items)
  - `mri_lumbar_spine_non_contrast_anjali` (Conus level)
  - `mri_lumbar_sacrum` (Conus level)
  - `mri_arthrogram_shoulder_ma` (Anterior capsule medial insertion distance)
- **Held-out:** real prod dictations for those five templates, run separately.
- Everything lives in `~/Code/rr-template-conversion-private/synthetic/value_cluster/`, never in the repo.

**Measures.** Two runs per arm on synthetic, then one run on held-out with the chosen arm.
- **Headline:** the **false-stated rate** (truly unstated items Jev calls stated), because those values silently vanish from the cluster.
- Then:
  - stated precision and recall across thresholds 0.5 to 0.95;
  - clause-choice accuracy;
  - stated items with no clause named (`check` chips);
  - the number read, split into exact, blank (safe) and **wrong**;
  - each of the above by tag;
  - latency per fill, i.e. per `ask_values` call (parallel batches), as median and max.
- **Secondary:** post-generation **backstop recall on planted missing values**, using reports with values deliberately left out, and its false-missing count on values the report does state.

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/value_cluster_lab.py`
- Test: `backend/tests/test_value_cluster_lab.py`
- Private: `~/Code/rr-template-conversion-private/synthetic/value_cluster/{cases.json,heldout.json,results/}`

- [ ] **Step 1: Write the failing scorer test**

Create `backend/tests/test_value_cluster_lab.py`:

```python
from rapid_reports_ai.scripts import value_cluster_lab as L


def _row(p, stated, value=None, truth_value=None, quote=None, truth_quote=None, tags=()):
    return {"case": "c", "item": "i", "tags": list(tags), "p": p, "quote": quote, "value": value,
            "truth_stated": stated, "truth_value": truth_value, "truth_quote": truth_quote}


def test_score_leads_with_false_stated_and_counts_the_number_read_classes():
    rows = [
        _row(0.9, True, "45%", "45 %", "LVEF 45%.", "LVEF 45%"),            # tp, clause ok, exact
        _row(0.9, True, None, "98 ml/m2", "LVEDVi 98 and 40", "LVEDVi 98"),  # tp, clause ok, blank (safe)
        _row(0.9, True, "40 ml/m2", "98 ml/m2", "LVESVi 40 ml/m2", "LVEDVi 98"),  # tp, wrong clause, wrong number
        _row(0.9, True, None, None, None, "conus at L1"),                     # tp, no clause named (check chip)
        _row(0.9, False),                                                    # fp: a false "stated"
        _row(0.2, True, truth_value="50%"),                                  # fn
        _row(0.1, False),                                                    # tn
    ]
    s = L.score(rows, 0.5)
    assert list(s)[:2] == ["t", "false_stated_rate"] and s["false_stated_rate"] == 0.5   # 1 of 2 negatives
    assert (s["tp"], s["fp"], s["fn"]) == (4, 1, 1)
    assert s["precision"] == 0.8 and s["recall"] == 0.8 and s["no_quote"] == 1
    assert (s["valued"], s["clause_ok"], s["value_exact"], s["value_blank"], s["value_wrong"]) == (3, 2, 1, 1, 1)


def test_by_tag_scores_each_tag_alone():
    rows = [_row(0.9, True, tags=["abbrev"]), _row(0.9, False, tags=["qualitative"])]
    t = L.by_tag(rows, 0.5)
    assert t["abbrev"]["tp"] == 1 and t["qualitative"]["fp"] == 1 and t["qualitative"]["false_stated_rate"] == 1.0


def test_score_backstop_counts_planted_missing_values_caught_and_false_missing():
    rows = [{"case": "c", "item": "a", "p": 0.1, "in_report": False},   # caught
            {"case": "c", "item": "b", "p": 0.7, "in_report": False},   # missed
            {"case": "c", "item": "c", "p": 0.2, "in_report": True},    # false missing
            {"case": "c", "item": "d", "p": 0.9, "in_report": True}]
    assert L.score_backstop(rows, 0.5) == {"t": 0.5, "missing": 2, "caught": 1, "recall": 0.5, "present": 2,
                                           "false_missing": 1}


def test_norm_value_ignores_spacing_case_and_superscripts():
    assert L.norm_value("98 mL/m²") == L.norm_value("98ml/m2") == L.norm_value("98 mL/m^2")
    assert L.norm_value("45 percent") == L.norm_value("45%")
    assert L.norm_value(None) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_value_cluster_lab.py -q`
Expected: FAIL with `ImportError: cannot import name 'value_cluster_lab'`.

- [ ] **Step 3: Write the lab script**

Create `backend/src/rapid_reports_ai/scripts/value_cluster_lab.py`:

```python
"""Value cluster wording lab (2026-10-13): "Does the dictation state the <item>?" (requirements spec part 1).

Arms for the stated question (the clause question and code's number read are the same in both):
  A  template_brief.q_stated (production default, jev_stack.value_stated_question)
  B  the spec's plain wording: "The DICTATION states the <item>."
Fixtures (private folder, never the repo): {"cases": [{"id", "template", "items": [...], "dictation",
"truth": {item: {"stated": bool, "value": str|null, "quote": str|null, "tags": [...]}},
"report": str (optional), "report_truth": {item: bool in the report} (optional)}]}.
Headline: the false-stated rate (a false "stated" silently drops a value). Then precision / recall per threshold,
clause-choice accuracy, stated-without-clause, number read exact / blank / wrong, by tag, and latency per fill.
Reported, not gated.

  DATABASE_URL=sqlite:///:memory: .venv/bin/python -m rapid_reports_ai.scripts.value_cluster_lab \
      <cases.json> <out.json> --env <.env> [--arms A,B] [--runs 2] [--t 0.8]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path

from rapid_reports_ai.hybrid_stack.jev_stack import ask_report_values, ask_values, value_stated_question
from rapid_reports_ai.hybrid_stack.values import MAX_CLAUSES, clauses, has_number, read_value

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
BACKSTOP_THRESHOLDS = (0.3, 0.5, 0.7)


def plain_question(item: str) -> dict:
    return {"type": "noul", "instructions": f"The DICTATION states the {item}."}


ARMS = {"A": value_stated_question, "B": plain_question}


def norm_value(v):
    if v is None:
        return None
    return re.sub(r"\s+", "", v).lower().replace("²", "2").replace("^2", "2").replace("percent", "%")


def quote_ok(chosen, truth_quote) -> bool:
    if not chosen or not truth_quote:
        return False
    a, b = chosen.lower().strip(" ."), truth_quote.lower().strip(" .")
    return a in b or b in a


def score(rows: list[dict], t: float) -> dict:
    said = [r for r in rows if r["p"] >= t]
    tp = sum(bool(r["truth_stated"]) for r in said)
    fp = len(said) - tp
    fn = sum(bool(r["truth_stated"]) for r in rows if r["p"] < t)
    negatives = sum(not r["truth_stated"] for r in rows)
    hits = [r for r in said if r["truth_stated"] and r["truth_value"] is not None]
    exact = sum(r["value"] is not None and norm_value(r["value"]) == norm_value(r["truth_value"]) for r in hits)
    blank = sum(r["value"] is None for r in hits)
    return {"t": t, "false_stated_rate": round(fp / negatives, 3) if negatives else None,
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "no_quote": sum(r["quote"] is None for r in said if r["truth_stated"]),
            "valued": len(hits), "clause_ok": sum(quote_ok(r["quote"], r["truth_quote"]) for r in hits),
            "value_exact": exact, "value_blank": blank, "value_wrong": len(hits) - exact - blank}


def by_tag(rows: list[dict], t: float) -> dict:
    tags = sorted({g for r in rows for g in r["tags"]})
    return {g: score([r for r in rows if g in r["tags"]], t) for g in tags}


def score_backstop(rows: list[dict], t: float) -> dict:
    """The post-generation backstop: planted missing values caught (p < t), and present values called missing."""
    missing = [r for r in rows if not r["in_report"]]
    present = [r for r in rows if r["in_report"]]
    caught = sum(r["p"] < t for r in missing)
    return {"t": t, "missing": len(missing), "caught": caught,
            "recall": round(caught / len(missing), 3) if missing else None, "present": len(present),
            "false_missing": sum(r["p"] < t for r in present)}


async def run_backstop(case: dict, stated) -> list[dict]:
    items = list(case["report_truth"])
    ps = await ask_report_values(case["report"], items, stated=stated)
    return [{"case": case["id"], "item": i, "p": round(p, 3), "in_report": bool(case["report_truth"][i])}
            for i, p in zip(items, ps)]


async def run_case(case: dict, stated) -> tuple[list[dict], int]:
    cands = [c for c in clauses(case["dictation"]) if has_number(c)][:MAX_CLAUSES]
    t0 = time.perf_counter()
    ans = await ask_values(case["dictation"], case["items"], cands, stated=stated)
    ms = int((time.perf_counter() - t0) * 1000)   # one fill: every batch, in parallel
    rows = []
    for item, (p, k) in zip(case["items"], ans):
        truth = case["truth"].get(item) or {"stated": False}
        quote = cands[k] if k is not None else None
        rows.append({"case": case["id"], "item": item, "tags": list(truth.get("tags") or []), "p": round(p, 3),
                     "quote": quote, "value": read_value(quote) if quote else None,
                     "truth_stated": bool(truth.get("stated")), "truth_value": truth.get("value"),
                     "truth_quote": truth.get("quote")})
    return rows, ms


async def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("out")
    ap.add_argument("--env")
    ap.add_argument("--arms", default="A,B")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--t", type=float, default=0.8)
    a = ap.parse_args(argv)
    if a.env:
        from dotenv import load_dotenv
        load_dotenv(a.env, override=True)
    cases = json.loads(Path(a.cases).read_text())["cases"]
    sem = asyncio.Semaphore(6)

    async def one(c, stated):
        async with sem:
            try:
                return await run_case(c, stated)
            except Exception as e:  # noqa: BLE001 -- counted, reported
                print(f"  error {c['id']}: {type(e).__name__}: {str(e)[:120]}")
                return [], -1

    report = {"cases": a.cases, "n_cases": len(cases), "t": a.t, "arms": {}}
    for arm in a.arms.split(","):
        for run in range(1, a.runs + 1):
            res = await asyncio.gather(*(one(c, ARMS[arm]) for c in cases))
            rows = [r for rs, _ in res for r in rs]
            ms = sorted(m for _, m in res if m >= 0)
            entry = {"run": run, "grid": [score(rows, t) for t in THRESHOLDS], "at_t": score(rows, a.t),
                     "by_tag": by_tag(rows, a.t), "errors": sum(m < 0 for _, m in res),
                     "ms_median": ms[len(ms) // 2] if ms else None, "ms_max": ms[-1] if ms else None, "rows": rows}
            report["arms"].setdefault(arm, []).append(entry)
            s = entry["at_t"]
            print(f"{arm} run{run} t={a.t}: FALSE-STATED {s['false_stated_rate']} (fp {s['fp']}) | P {s['precision']} "
                  f"R {s['recall']} (tp {s['tp']} fn {s['fn']}) | no clause {s['no_quote']} | clause "
                  f"{s['clause_ok']}/{s['valued']} | value exact {s['value_exact']} blank {s['value_blank']} WRONG "
                  f"{s['value_wrong']} | errors {entry['errors']} | ms/fill median {entry['ms_median']} max {entry['ms_max']}")
            for g in entry["grid"]:
                print(f"     t={g['t']}: false-stated {g['false_stated_rate']} fp {g['fp']} | P {g['precision']} "
                      f"R {g['recall']} fn {g['fn']}")
            for r in rows:
                wrong = (r["truth_stated"] and r["truth_value"] is not None and r["p"] >= a.t and r["value"] is not None
                         and norm_value(r["value"]) != norm_value(r["truth_value"]))
                if wrong or (r["p"] >= a.t) != r["truth_stated"]:
                    print(f"     {'WRONG' if wrong else 'FALSE' if r['p'] >= a.t else 'MISS'} {r['p']:.2f} "
                          f"{r['case']} | {r['item']} | read {r['value']} truth {r['truth_value']} | {r['quote']}")
            # Secondary: the post-generation backstop on reports with planted missing values
            with_report = [c for c in cases if c.get("report") and c.get("report_truth")]
            if with_report:
                async def bs(c, stated=ARMS[arm]):
                    async with sem:
                        try:
                            return await run_backstop(c, stated)
                        except Exception as e:  # noqa: BLE001 -- counted, reported
                            print(f"  backstop error {c['id']}: {type(e).__name__}: {str(e)[:120]}")
                            return []
                brows = [r for rs in await asyncio.gather(*(bs(c) for c in with_report)) for r in rs]
                entry["backstop"] = {"grid": [score_backstop(brows, t) for t in BACKSTOP_THRESHOLDS], "rows": brows}
                for g in entry["backstop"]["grid"]:
                    print(f"     BACKSTOP t={g['t']}: recall {g['recall']} ({g['caught']}/{g['missing']} planted missing) "
                          f"| false missing {g['false_missing']}/{g['present']}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run the scorer test to verify it passes, then commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_value_cluster_lab.py -q`
Expected: PASS (4 passed).

```bash
git add backend/src/rapid_reports_ai/scripts/value_cluster_lab.py backend/tests/test_value_cluster_lab.py
git commit -m "chore(lab): value cluster wording lab (false-stated first, clause choice, number read)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

- [ ] **Step 5: Write the synthetic fixtures (Opus subagent, private folder)**

Create the folder: `mkdir -p ~/Code/rr-template-conversion-private/synthetic/value_cluster/results`

Dispatch one Agent (`model: "opus"`, general-purpose) with this prompt, verbatim:

> You are writing synthetic radiology dictations for a lab. Write ONLY to `~/Code/rr-template-conversion-private/synthetic/value_cluster/cases.json`, never inside any git repository.
>
> **Sources.** Read these five grammar sheets: `~/Code/rr-template-conversion-private/final/{cmr_non_stress_dr_sabeeh_syed,cardiac_mr_2,mri_lumbar_spine_non_contrast_anjali,mri_lumbar_sacrum,mri_arthrogram_shoulder_ma}.final.md`. Each has one line `RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["<item>" | ...] AT TOP|END`. Its items are the values every report must carry. Use each sheet's Opening, Order and Measurement lines for the radiologist's real phrasing and units.
>
> **Cases.** Write 56 dictations as free speech-to-text findings: 20 per CMR sheet, 5 per lumbar sheet, and 6 for the shoulder. Mix normal and abnormal studies, and include 6 dictations that state none of the items.
>
> **Items.** `items` is the sheet's full LIST_MISSING item list, exactly as spelled there.
>
> **Truth.** Plant the truth for every item:
> - `stated` (bool);
> - `value`: the item's number with its unit, exactly as written in the dictation, or null when no number is given for it;
> - `quote`: the shortest exact substring of the dictation that gives the item, or null;
> - `tags`: from the list below.
>
> **Tags.** Each tag must appear at least 8 times across the set (lumbar and shoulder cases may cover only the tags that apply):
> - `abbrev`: "EF 45", "LVEDVi 98".
> - `wordy`: "ejection fraction mildly reduced at 45", "the indexed end-diastolic volume measures 98 ml per metre squared".
> - `value_free`: the item is not mentioned at all.
> - `qualitative`: described in words with no number, e.g. "RV systolic function is normal". Truth: `stated: false`, value null.
> - `two_numbers`: two items' numbers in one sentence with no comma between them, e.g. "LVEDVi 98 and LVESVi 40 ml/m2". Truth: `stated: true` for each, each with its own value.
> - `units`: %, ml/m2, mL/m², mL/m^2, g/m², mm, cm, ms, L/min, "percent".
> - `decoy`: a neighbouring item's value is given but this one is not (e.g. LVEDVi given, LVESVi asked). Truth: `stated: false`.
> - `range`: "EF 45-50%". Truth: `stated: true`, value "45-50%".
> - `non_numeric`: e.g. "conus terminates at L1/2". Truth: `stated: true`, value null.
> - `negative_result`: e.g. "no aortic flow abnormality, forward flow 4.5 L/min".
> - `long`: 6 CMR dictations with more than 40 numbers in total.
>
> **Reports (backstop).** For 20 CMR cases, also write a `report` field: a finished radiology report written from the dictation. In each one, leave out one or two values that the dictation states. Add `report_truth`, which gives `true`/`false` for every item the dictation states, saying whether that item's value is in the report.
>
> **Output.** JSON in this shape:
> ```
> {"cases": [{"id": "<sheet>-<n>", "template": "<sheet stem>", "items": [...], "dictation": "...",
>   "truth": {"<item>": {"stated": true, "value": "45%", "quote": "EF 45%", "tags": ["abbrev", "units"]}}}]}
> ```
> Every item in `items` has a truth entry. Every non-null `quote` is an exact substring of `dictation`. Every `report_truth` key is in `items`.

- [ ] **Step 6: Validate the fixtures**

Run:

```bash
cd backend && .venv/bin/python - <<'EOF'
import json, os, collections
p = os.path.expanduser("~/Code/rr-template-conversion-private/synthetic/value_cluster/cases.json")
cases = json.load(open(p))["cases"]
bad, tags = [], collections.Counter()
for c in cases:
    for it in c["items"]:
        t = c["truth"].get(it)
        if t is None: bad.append((c["id"], it, "no truth")); continue
        if t.get("quote") and t["quote"] not in c["dictation"]: bad.append((c["id"], it, "quote not in dictation"))
        if t.get("value") and not t.get("stated"): bad.append((c["id"], it, "value but not stated"))
        tags.update(t.get("tags") or [])
    for it in (c.get("report_truth") or {}):
        if it not in c["items"]: bad.append((c["id"], it, "report_truth item not in items"))
print(sum(bool(c.get("report")) for c in cases), "cases with a report (want 20)")
print(len(cases), "cases;", sum(len(c["items"]) for c in cases), "items;", dict(tags))
print("problems:", bad[:20], len(bad))
EOF
```

Expected: 56 cases, every tag listed, and `problems: [] 0`. If there are problems, send them back to the same subagent (SendMessage) for repair, then run this step again.

- [ ] **Step 7: Run the lab (synthetic: both arms, 2 runs; then held-out)**

Run the synthetic set:

```bash
cd backend && DATABASE_URL=sqlite:///:memory: .venv/bin/python -m rapid_reports_ai.scripts.value_cluster_lab \
  ~/Code/rr-template-conversion-private/synthetic/value_cluster/cases.json \
  ~/Code/rr-template-conversion-private/synthetic/value_cluster/results/2026-10-13-synthetic.json \
  --env /Users/hassan/Code/rapid_reports_ai/backend/.env --arms A,B --runs 2
```

Expected: four summary blocks (A run1, A run2, B run1, B run2). Each opens with FALSE-STATED, then gives the threshold grid and the listed FALSE / MISS / WRONG lines.

Then build the held-out set from real cases, run separately:
1. Pull the reports. Standing permission covers reading prod content; use the Chrome session on Metabase `/api/dataset` (memory `reference_prod_smoke_testing`). Query: `select r.id, t.name, r.created_at, r.input_data::text from reports r join templates t on t.id = r.template_id where t.name in (<the five templates' names, from each sheet's "# Skill Sheet:" title>) order by r.created_at desc limit 60`.
2. Take the FINDINGS text from `input_data`, and save the cases in the same schema to `~/Code/rr-template-conversion-private/synthetic/value_cluster/heldout.json`.
3. Have one Opus subagent label `truth`, using the same field rules as Step 5 (no tags beyond `real`).
4. If fewer than 10 real cases exist, say so in the report rather than padding the set.

Run the held-out set once, with the arm the synthetic run favoured:

```bash
cd backend && DATABASE_URL=sqlite:///:memory: .venv/bin/python -m rapid_reports_ai.scripts.value_cluster_lab \
  ~/Code/rr-template-conversion-private/synthetic/value_cluster/heldout.json \
  ~/Code/rr-template-conversion-private/synthetic/value_cluster/results/2026-10-13-heldout.json \
  --env /Users/hassan/Code/rapid_reports_ai/backend/.env --arms A --runs 1
```

(Use `--arms B` instead if B led.)

- [ ] **Step 8: Report to Hassan; apply his choice (which may be a design change)**

Send Hassan a short report. Lead with the **false-stated rate** per arm at 0.8, and the rates at the lower thresholds as alternatives. Then give:
- precision and recall;
- `no_quote` (the `check` chips the radiologist will see);
- clause-choice accuracy;
- the number read (exact / blank / **wrong**), with every WRONG line quoted;
- the by-tag table, especially qualitative, decoy, two_numbers, range and long;
- latency per fill;
- backstop recall on planted missing values, with false missing, at 0.3 / 0.5 / 0.7 (the secondary metric);
- the held-out result;
- a recommendation covering the arm, the threshold, whether `qualitative` should count as stated, and whether the clause question is good enough.

**The result may change the design, not just one line.** For example, if clause-choice accuracy is poor, the `where_i` choice question could become one Jev yes/no per numeric clause ("This SENTENCE gives the <item>"). That would get its own plan amendment.

Do not change code before Hassan answers. Then apply the change he chooses:
- **A different threshold:** edit the `VALUE_STATED_MIN = STATED_MIN` line in `backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py` to the chosen number, with a comment citing the lab (`# lab 2026-10-13 (N item pairs): false-stated …, recall …`). Update `test_the_value_cut_off_starts_at_the_scratchpads_strict_stated_bar` to assert the new number.
- **Arm B:** replace the body of `value_stated_question` with `return {"type": "noul", "instructions": f"The DICTATION states the {item}."}`. In `test_ask_values_asks_stated_and_where_per_item_in_one_call`, change the assertion `.endswith("LVEF")` to `== "The DICTATION states the LVEF."`.
- **A different backstop threshold:** edit `BACKSTOP_MIN = 0.5` in the same file, with the lab citation, and update the `J.BACKSTOP_MIN == 0.5` assertion.
- **A design change:** write it as an amendment to this plan before building.

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_jev_stack.py tests/test_hybrid_stack_values.py -q` (expected PASS), and commit:

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py backend/tests/test_hybrid_stack_jev_stack.py
git commit -m "tune(values): stated wording and threshold from the value cluster lab

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 5: Endpoint `/values` and `required_values` on `/slim-sheet`

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/routes.py`:
  - imports (`:19-25`);
  - `SlimResult` (`:147-152`);
  - the slim-sheet template branch (`:344-349`);
  - the new route, after `/assumed` (`:267`).
- Test: `backend/tests/test_hybrid_stack_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_hybrid_stack_routes.py`:

```python
_VALUES_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
"""


def _values_template(db_session, user):
    from rapid_reports_ai.database.models import Template
    t = Template(name="CMR", user_id=user.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _VALUES_SHEET})
    db_session.add(t)
    db_session.commit()
    return t


def test_slim_sheet_carries_the_templates_required_values(authed, db_session, user):
    t = _values_template(db_session, user)
    d = authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": "CMR", "template_id": str(t.id)}).json()
    assert d["status"] == "template" and d["required_values"] == ["LVEF", "LV mass index", "RVEF"]


def test_values_route_fills_the_templates_items_read_on_the_server(authed, monkeypatch, db_session, user):
    from rapid_reports_ai.hybrid_stack.values import ValueFill, ValuesResult
    t = _values_template(db_session, user)
    seen = {}

    async def fake(dictation, items):
        seen.update(dictation=dictation, items=items)
        return ValuesResult(values=[ValueFill(item="LVEF", state="filled", value="45%", quote="LVEF 45%.", score=0.9),
                                    ValueFill(item="LV mass index"), ValueFill(item="RVEF")])
    monkeypatch.setattr(R, "smart_fill", fake)
    d = authed.post("/api/canvas/stack/values", json={"dictation": "LVEF 45%.", "template_id": str(t.id)}).json()
    assert seen == {"dictation": "LVEF 45%.", "items": ["LVEF", "LV mass index", "RVEF"]}
    assert d["values"][0] == {"item": "LVEF", "state": "filled", "value": "45%", "quote": "LVEF 45%.", "score": 0.9}
    assert [v["state"] for v in d["values"][1:]] == ["open", "open"] and d["error"] is None


def test_values_route_without_a_usable_template_has_no_items(authed, monkeypatch):
    seen = {}

    async def fake(dictation, items):
        seen["items"] = items
        from rapid_reports_ai.hybrid_stack.values import ValuesResult
        return ValuesResult()
    monkeypatch.setattr(R, "smart_fill", fake)
    assert authed.post("/api/canvas/stack/values", json={"dictation": "x"}).json()["values"] == []
    assert seen["items"] == []
    other = authed.post("/api/canvas/stack/values", json={"dictation": "x", "template_id": str(uuid.uuid4())})
    assert other.status_code == 200 and seen["items"] == []   # unknown / another user's template: nothing asked
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_routes.py -q -k "required_values or values_route"`
Expected: FAIL, in two ways:
- the slim-sheet test with `KeyError: 'required_values'`;
- the values tests with 404 / `AttributeError: ... has no attribute 'smart_fill'`.

- [ ] **Step 3: Write the minimal implementation**

In `backend/src/rapid_reports_ai/hybrid_stack/routes.py`, replace

```python
from .template import template_normal_labels, template_region_normals, template_structure, template_suppressions
```

with

```python
from .template import (template_normal_labels, template_region_normals, template_required_values, template_structure,
                       template_suppressions)
from .values import ValuesResult, smart_fill
```

In `class SlimResult(BaseModel)`, after `ready: bool = False`, add:

```python
    required_values: list[str] = Field(default_factory=list)   # template sessions: the LIST_MISSING items (value cluster)
```

In `stack_slim_sheet`, replace

```python
        return SlimResult(region_normals=template_region_normals(st), status="template", ready=True)
```

with

```python
        return SlimResult(region_normals=template_region_normals(st), required_values=template_required_values(st),
                          status="template", ready=True)
```

After the `stack_assumed` function, and before `@router.post("/draft", ...)`, add:

```python
class ValuesRequest(BaseModel):
    dictation: str = ""
    template_id: str | None = None   # the items are read from the template on the server, never sent by the client


@router.post("/values", response_model=ValuesResult)
async def stack_values(req: ValuesRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The value cluster's smart fill (requirements spec 2026-10-12 part 1): the template's required values, each
    filled from the dictation (Jev says stated and where; code reads the number) or open. Never errors: a Jev
    failure leaves every value open."""
    _require()
    items: list[str] = []
    if req.template_id:
        t = get_template(db, req.template_id, str(user.id))   # the string id as a UUID, owner only
        st = template_structure(t.template_config) if t is not None else None
        if st is not None:
            items = template_required_values(st)
    return await smart_fill(req.dictation[:20000], items)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_hybrid_stack_routes.py -q`
Expected: PASS (the whole file).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/routes.py backend/tests/test_hybrid_stack_routes.py
git commit -m "feat(values): /values smart fill endpoint; slim sheet carries the required values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 6: Code owns the list: the sheet loses `LIST_MISSING`, the backstop runs, and code writes the literal N/A line

**Files:**
- Create: `backend/src/rapid_reports_ai/template_required_values.py`
- Test: `backend/tests/test_template_required_values.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_template_required_values.py`:

```python
import pytest

from rapid_reports_ai.template_required_values import (apply_required_values, backstop, missing_line, values_applied,
                                                       write_missing)
from rapid_reports_ai.template_sheet_grammar import parse_sheet

SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
"""
LINE = 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP'

HEADED = """## Report Structure
SECTION OPENING | header: none | role: other
SECTION LV | header: "LEFT VENTRICLE" | role: findings
SECTION RV | header: "RIGHT VENTRICLE" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["RVEF"] AT TOP

## Paragraph: Left ventricle (LV)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal LV."
"""


def test_the_list_line_leaves_the_sheet_and_the_record_keeps_the_na_items():
    text, rec = apply_required_values(SHEET, ["rvef.", " LV MASS INDEX"])
    assert LINE not in text and "LIST_MISSING" not in text and text.endswith("\n")
    assert rec == {"lists": [{"line": 6, "items": ["LVEF", "LV mass index", "RVEF"], "na": ["LV mass index", "RVEF"],
                              "position": "top", "section": "FINDINGS", "outcome": "applied"}],
                   "skipped": None, "error": None}
    assert values_applied(rec)
    res = parse_sheet(text, mode="template")
    assert res.errors == [] and res.structure.usable


def test_nothing_marked_na_still_removes_the_line():
    text, rec = apply_required_values(SHEET, [])
    assert "LIST_MISSING" not in text and rec["lists"][0]["na"] == [] and values_applied(rec)


def test_an_item_on_two_lists_is_listed_once():
    two = SHEET + 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["lvef" | "LV wall thickness"] AT END\n'
    text, rec = apply_required_values(two, ["LVEF", "LV wall thickness"])
    assert "LIST_MISSING" not in text
    assert [e["na"] for e in rec["lists"]] == [["LVEF"], ["LV wall thickness"]]


def test_a_sheet_without_a_list_or_not_parsing_clean_is_unchanged_and_not_applied():
    plain = SHEET.replace(LINE + "\n", "")
    assert apply_required_values(plain, ["LVEF"]) == (plain, {"lists": [], "skipped": "no_list", "error": None})
    legacy = "## FINDINGS\nLVEF: {value}\n"
    text, rec = apply_required_values(legacy, [])
    assert (text, rec) == (legacy, {"lists": [], "skipped": "parse", "error": None}) and not values_applied(rec)


def test_never_raises(monkeypatch):
    import rapid_reports_ai.template_required_values as M

    def boom(sheet):
        raise RuntimeError("parser down")
    monkeypatch.setattr(M, "_clean", boom)
    text, rec = apply_required_values(SHEET, [])
    assert text == SHEET and rec["error"].startswith("RuntimeError") and not values_applied(rec)


def test_code_writes_the_literal_line_at_the_top_of_its_section_and_strips_the_generators():
    _, rec = apply_required_values(SHEET, ["RVEF", "LV mass index"])
    report = "Findings:\nValues not provided: LVEF, RVEF.\nNormal LV.\n\nConclusion:\nNormal."
    assert write_missing(report, SHEET, rec["lists"]) == (
        "Findings:\nValues not provided: LV mass index, RVEF.\nNormal LV.\n\nConclusion:\nNormal.", 1)
    assert missing_line(["RVEF"]) == "Values not provided: RVEF."


def test_at_end_without_headers_and_by_section_header():
    end = SHEET.replace("AT TOP", "AT END")
    _, rec = apply_required_values(end, ["LVEF"])
    assert write_missing("Findings:\nNormal LV.\n\nConclusion:\nNormal.", end, rec["lists"])[0] == \
        "Findings:\nNormal LV.\nValues not provided: LVEF.\n\nConclusion:\nNormal."
    _, rec = apply_required_values(SHEET, ["LVEF"])
    assert write_missing("Normal LV.", SHEET, rec["lists"])[0] == "Values not provided: LVEF.\nNormal LV."
    _, rec = apply_required_values(HEADED, ["RVEF"])
    report = "No previous CMR available.\n\nLEFT VENTRICLE\nNormal LV.\n\nRIGHT VENTRICLE\nNormal RV.\n\nConclusion:\nNormal."
    assert write_missing(report, HEADED, rec["lists"])[0] == (
        "No previous CMR available.\n\nLEFT VENTRICLE\nValues not provided: RVEF.\nNormal LV.\n\nRIGHT VENTRICLE\n"
        "Normal RV.\n\nConclusion:\nNormal.")


def test_nothing_na_writes_nothing_but_strips_an_unrequested_list():
    _, rec = apply_required_values(SHEET, [])
    assert write_missing("Findings:\nValues not provided: RVEF.\nNormal LV.", SHEET, rec["lists"]) == ("Findings:\nNormal LV.", 1)


def test_write_missing_never_raises(monkeypatch):
    import rapid_reports_ai.template_required_values as M

    def boom(sheet):
        raise RuntimeError("parser down")
    monkeypatch.setattr(M, "_clean", boom)
    assert write_missing("Normal LV.", SHEET, [{"na": ["LVEF"], "position": "top", "section": "FINDINGS",
                                                "outcome": "applied"}]) == ("Normal LV.", 0)


def _scores(ps, seen=None):
    async def ask(report, items):
        if seen is not None:
            seen.update(report=report, items=items)
        return ps
    return ask


async def test_backstop_lists_and_flags_a_filled_value_the_report_lacks():
    _, rec = apply_required_values(SHEET, ["RVEF"])
    seen = {}
    lists, flags, b = await backstop("Findings:\nLVEF 45%.", rec["lists"], ["LVEF", "LV mass index"],
                                     ask=_scores([0.9, 0.2], seen))
    assert seen == {"report": "Findings:\nLVEF 45%.", "items": ["LVEF", "LV mass index"]}
    assert lists[0]["na"] == ["RVEF", "LV mass index"] and rec["lists"][0]["na"] == ["RVEF"]   # the input is untouched
    assert flags == [{"kind": "value_missing", "text": "LV mass index",
                      "message": "Required value LV mass index not found in the report"}]
    assert b == {"asked": 2, "missing": ["LV mass index"], "error": None}
    assert write_missing("Findings:\nLVEF 45%.", SHEET, lists)[0] == \
        "Findings:\nValues not provided: RVEF, LV mass index.\nLVEF 45%."


async def test_backstop_creates_the_line_when_nothing_was_marked_na():
    _, rec = apply_required_values(SHEET, [])
    lists, flags, _ = await backstop("Findings:\nNormal.", rec["lists"], ["LVEF"], ask=_scores([0.1]))
    assert write_missing("Findings:\nNormal.", SHEET, lists)[0] == "Findings:\nValues not provided: LVEF.\nNormal."
    assert [f["text"] for f in flags] == ["LVEF"]


async def test_backstop_leaves_a_value_the_report_states_alone():
    _, rec = apply_required_values(SHEET, [])
    lists, flags, b = await backstop("Findings:\nLVEF 45%.", rec["lists"], ["LVEF"], ask=_scores([0.9]))
    assert lists == rec["lists"] and flags == [] and b["missing"] == []
    assert write_missing("Findings:\nLVEF 45%.", SHEET, lists)[0] == "Findings:\nLVEF 45%."


async def test_backstop_jev_failure_changes_nothing_and_flags_nothing():
    _, rec = apply_required_values(SHEET, [])

    async def boom(report, items):
        raise RuntimeError("jev down")
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], ["LVEF"], ask=boom)
    assert lists is rec["lists"] and flags == [] and b["error"].startswith("RuntimeError")
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], ["LVEF"], ask=_scores([]))
    assert lists is rec["lists"] and flags == [] and b["error"] == "jev: answer count mismatch"


@pytest.mark.parametrize("filled", [[], [" "], None])
async def test_backstop_without_filled_items_asks_nothing(filled):
    _, rec = apply_required_values(SHEET, [])

    async def fail(report, items):
        raise AssertionError("no call")
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], filled or [], ask=fail)
    assert lists is rec["lists"] and flags == [] and b == {"asked": 0, "missing": [], "error": None}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_required_values.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.template_required_values'`.

- [ ] **Step 3: Write the minimal implementation**

Create `backend/src/rapid_reports_ai/template_required_values.py`:

```python
"""Required values decided in the scratchpad (requirements spec 2026-10-12 part 1, Generate).

The radiologist resolved every LIST_MISSING item in the scratchpad's value cluster: filled from the dictation,
typed, or marked N/A. Code owns the missing-values list (Hassan 2026-10-13: always the literal wording):
- apply_required_values: every LIST_MISSING line leaves the sheet the generator reads (the stack brief then says to
  write no list); the record keeps the N/A items, the list's position and its section. An item on two lists is
  listed once.
- write_missing: after generation, any generator line beginning "Values not provided" is removed and code writes
  "Values not provided: <items>." at the TOP or END of the list's section (by its sheet name or header in the
  report's sections; else the first findings section; else the report itself).
- backstop: before the line is written, Jev asks whether the generated report states each value whose chip was
  filled (a false "stated" must never let a value vanish from both the report and the line); each "no" joins its
  list's N/A items and becomes a value_missing review flag.
The stored sheet is never changed. Regex here only reads the grammar's own syntax and our own literal line. Never
raises: a sheet that does not parse clean, or any error, leaves things as they came with the reason in the record;
values_applied() then says the generator must not be told the values were decided."""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Sequence, Tuple

from .hybrid_stack.jev_stack import BACKSTOP_MIN, ask_report_values
from .hybrid_stack.template import norm_key
from .template_context_rules import _clean

logger = logging.getLogger(__name__)

NA_PREFIX = "Values not provided"
VALUE_MISSING = "value_missing"
_NA_LINE = re.compile(r"(?im)^[ \t]*(?:[-*•][ \t]*)?values not provided\b[^\n]*\n?")


def missing_line(items: Sequence[str]) -> str:
    return f"{NA_PREFIX}: {', '.join(items)}."


def apply_required_values(sheet: str, na: Sequence[str]) -> Tuple[str, dict]:
    """(the sheet the generator reads, the record). `na`: the items the radiologist marked N/A."""
    rec: dict = {"lists": [], "skipped": None, "error": None}
    try:
        st = _clean(sheet)
        if st is None:
            rec["skipped"] = "parse"
            return sheet, rec
        rules = [r for r in st.rules if r.effect == "list_missing"]
        if not rules:
            rec["skipped"] = "no_list"
            return sheet, rec
        gone = {norm_key(x) for x in na if isinstance(x, str) and x.strip()}
        lines = sheet.splitlines()
        out: List[Optional[str]] = list(lines)
        taken: set[int] = set()
        listed: set[str] = set()
        for r in rules:
            raw = r.source_lines[0] if r.source_lines else None
            i = next((k for k, ln in enumerate(lines) if k not in taken and ln == raw), None)
            keep: List[str] = []
            for x in r.items:
                k = norm_key(x)
                if k in gone and k not in listed:
                    listed.add(k)
                    keep.append(x)
            rec["lists"].append({"line": None if i is None else i + 1, "items": list(r.items), "na": keep,
                                 "position": r.position or "top", "section": r.section,
                                 "outcome": "unmatched" if i is None else "applied"})
            if i is not None:
                taken.add(i)
                out[i] = None
        text = "\n".join(x for x in out if x is not None)
        return (text + "\n" if sheet.endswith("\n") else text), rec
    except Exception as e:  # noqa: BLE001 -- fail-soft: the generator reads the sheet as it came
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        logger.warning("[template.required_values] error=%s", rec["error"])
        return sheet, rec


def values_applied(rec: dict) -> bool:
    """True only when code took over every list: no error, no skip, every LIST_MISSING line matched."""
    return (rec.get("error") is None and rec.get("skipped") is None and bool(rec.get("lists"))
            and all(e.get("outcome") == "applied" for e in rec["lists"]))


async def backstop(report: str, lists: List[dict], filled: Sequence[str], ask=None) -> Tuple[List[dict], List[dict], dict]:
    """The post-generation backstop: (lists with every filled value the report does not state added to its list's
    N/A items, value_missing review flags, record). Jev decides (ask_report_values, BACKSTOP_MIN); code lists and
    flags. A Jev failure or a short reply changes nothing and flags nothing; no filled items: no call."""
    rec: dict = {"asked": 0, "missing": [], "error": None}
    items = list(dict.fromkeys(x.strip() for x in filled if isinstance(x, str) and x.strip()))
    if not items or not lists:
        return lists, [], rec
    rec["asked"] = len(items)
    try:
        scores = await (ask or ask_report_values)(report, items)
        if len(scores) != len(items):
            raise ValueError("jev: answer count mismatch")
    except Exception as e:  # noqa: BLE001 -- fail-soft: the report as it is, no flags
        rec["error"] = ("jev: answer count mismatch" if isinstance(e, ValueError) and "mismatch" in str(e)
                        else f"{type(e).__name__}: {e}"[:200])
        logger.warning("[template.required_values] backstop error=%s", rec["error"])
        return lists, [], rec
    missing = [i for i, p in zip(items, scores) if p < BACKSTOP_MIN]
    rec["missing"] = missing
    if not missing:
        return lists, [], rec
    out = [dict(e, na=list(e["na"])) for e in lists]
    listed = {norm_key(x) for e in out for x in e["na"]}
    for item in missing:
        k = norm_key(item)
        if k in listed:
            continue
        listed.add(k)
        home = next((e for e in out if k in {norm_key(x) for x in e["items"]}), out[0])
        home["na"].append(item)
    flags = [{"kind": VALUE_MISSING, "text": i, "message": f"Required value {i} not found in the report"} for i in missing]
    logger.info("[template.required_values] backstop asked=%d missing=%d", len(items), len(missing))
    return out, flags, rec


def _insert(text: str, a: int, b: int, line: str, end: bool) -> str:
    body = text[a:b]
    if end:
        k = a + len(body.rstrip())
        return text[:k] + ("\n" if k > a else "") + line + text[k:]
    k = a + len(body) - len(body.lstrip())
    return text[:k] + line + ("\n" if text[k:b].strip() else "") + text[k:]


def write_missing(report: str, sheet: str, lists: List[dict]) -> Tuple[str, int]:
    """(the report with code's "Values not provided" lines, generator lines in that wording removed). Never raises:
    on any error the report comes back as it was."""
    try:
        from .report_review import section_spans
        from .template_lean import report_sections
        text, stripped = _NA_LINE.subn("", report or "")
        st = _clean(sheet)
        names = {s.name.upper(): {s.name.upper(), (s.header or s.name).strip().rstrip(":").strip().upper()}
                 for s in (st.sections if st else [])}
        for e in lists:
            if not e.get("na"):
                continue
            spans = section_spans(text, report_sections(text, sheet))
            want = names.get(e["section"].upper(), {e["section"].upper()})
            hit = (next(((a, b) for s, a, b in spans if s.name in want), None)
                   or next(((a, b) for s, a, b in spans if s.role == "findings"), None) or (0, len(text)))
            text = _insert(text, hit[0], hit[1], missing_line(e["na"]), e.get("position") == "end")
        logger.info("[template.required_values] written=%d stripped=%d", sum(bool(e.get("na")) for e in lists), stripped)
        return text, stripped
    except Exception as e:  # noqa: BLE001 -- never break Generate
        logger.warning("[template.required_values] write error=%s", f"{type(e).__name__}: {e}"[:200])
        return report, 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_required_values.py -q`
Expected: PASS (17 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_required_values.py backend/tests/test_template_required_values.py
git commit -m "feat(values): code owns the missing-values list; literal line; backstop for filled values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 7: Generate wiring (request field, lean path, `values_decided`, the line, record)

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py` (`:672-679`, `:1912-1913`)
- Modify: `backend/src/rapid_reports_ai/template_lean.py` (imports `:30`; `gen()` `:438-452`; after the check, `:513-520`)
- Modify: `backend/src/rapid_reports_ai/template_stack.py` (`:53-103`)
- Modify: `backend/src/rapid_reports_ai/template_manager.py` (`:2583`)
- Modify: `backend/src/rapid_reports_ai/template_pipeline.py` (`:382`)
- Test: `backend/tests/test_template_stack.py`, `backend/tests/test_template_lean.py`, `backend/tests/test_template_generate_endpoint.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_stack.py`:

```python
def test_missing_values_rule_only_when_the_scratchpad_decided_the_values():
    assert "Missing values" not in stack_brief(LEAN, "", ())
    b = stack_brief(LEAN, "", (), values_decided=True)
    assert "**Missing values:**" in b and "write no list of missing or unprovided values" in b
    assert b.index("**Missing values:**") > b.index("## Scratchpad Session")
```

Append to `backend/tests/test_template_lean.py`:

```python
VALUES = '''## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
'''


def _values_gen(monkeypatch, calls, report):
    async def gen(self, template_config, user_inputs, user_signature=None, model_override=None, brief_text=None,
                  history_supplied=False, stack=None):
        calls["gen"] = {"sheet": template_config["skill_sheet"], "stack": stack}
        return {"report_content": report, "model_used": "q", "description": "d", "scan_type": "CMR"}
    monkeypatch.setattr(tl.TemplateManager, "_generate_report_skill_sheet_guided", gen)


async def test_a_stack_session_with_values_has_code_write_the_literal_na_line(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nValues not provided: LVEF, RVEF.\nNormal LV.\n\nConclusion:\nNormal.")
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%.", history="",
                                                 case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": ["RVEF"]})
    assert "LIST_MISSING" not in calls["gen"]["sheet"]
    assert calls["gen"]["stack"]["values_decided"] is True
    assert "Findings:\nValues not provided: RVEF.\nNormal LV." in out["report_content"]
    assert "LVEF, RVEF" not in out["report_content"]
    assert out["required_values"]["stripped"] == 1 and out["required_values"]["lists"][0]["na"] == ["RVEF"]


async def test_a_filled_value_the_report_lacks_is_listed_and_flagged(monkeypatch):
    from rapid_reports_ai import template_required_values as trv
    calls, seen = {}, {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.\n\nConclusion:\nNormal.")

    async def ask(report, items):
        seen.update(report=report, items=items)
        return [0.1, 0.9]
    monkeypatch.setattr(trv, "ask_report_values", ask)
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%. RVEF 50%.",
                                                 history="", case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": [],
                                                        "values_filled": ["LVEF", "RVEF"]})
    assert seen["items"] == ["LVEF", "RVEF"] and seen["report"].startswith("Findings:\nNormal LV.")
    assert "Findings:\nValues not provided: LVEF.\nNormal LV." in out["report_content"]
    assert {"kind": "value_missing", "text": "LVEF", "message": "Required value LVEF not found in the report"} \
        in out["quality_check"]["review"]
    assert out["required_values"]["backstop"] == {"asked": 2, "missing": ["LVEF"], "error": None}


async def test_a_backstop_failure_leaves_the_report_and_flags_nothing(monkeypatch):
    from rapid_reports_ai import template_required_values as trv
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.\n\nConclusion:\nNormal.")

    async def boom(report, items):
        raise RuntimeError("jev down")
    monkeypatch.setattr(trv, "ask_report_values", boom)
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%.", history="",
                                                 case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": [],
                                                        "values_filled": ["LVEF"]})
    assert "Values not provided" not in out["report_content"]
    assert not any(f.get("kind") == "value_missing" for f in (out["quality_check"] or {}).get("review") or [])
    assert out["required_values"]["backstop"]["error"].startswith("RuntimeError")


async def test_nothing_na_gives_no_list_and_no_line(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.\n\nConclusion:\nNormal.")
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%. RVEF 50%.",
                                                 history="", case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": []})
    assert "LIST_MISSING" not in calls["gen"]["sheet"] and calls["gen"]["stack"]["values_decided"] is True
    assert "Values not provided" not in out["report_content"]


async def test_values_not_applied_leave_the_sheet_and_the_generator_as_today(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.")
    legacy = "## FINDINGS\nLVEF: {value}\n"
    out = await tl.generate_template_report_lean(sheet=legacy, scan_type="CMR", findings="LV normal.", history="",
                                                 case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": ["RVEF"]})
    assert calls["gen"]["sheet"] == legacy and calls["gen"]["stack"]["values_decided"] is False
    assert out["required_values"]["skipped"] == "parse" and "Values not provided" not in out["report_content"]


async def test_a_stack_session_without_values_leaves_the_list_as_today(monkeypatch):
    for stack in ({"conclusion": "", "declined": []}, None):
        calls = {}
        _gen_fakes(monkeypatch, calls)
        out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%.", history="",
                                                     case=CASE, signature=None, stack=stack)
        assert 'LIST_MISSING ["LVEF" | "RVEF"] AT TOP' in calls["gen"]["sheet"]
        assert "values_decided" not in (calls["gen"]["stack"] or {}) and "required_values" not in out
        if out.get("options_job") is not None:
            await out["options_job"]


def test_candidate_record_carries_required_values():
    rec = tp.candidate_record({"report_content": "x", "required_values": {"lists": []}}, 10)
    assert rec["required_values"] == {"lists": []}
```

Append to `backend/tests/test_template_generate_endpoint.py`:

```python
async def test_stack_session_passes_the_values_marked_na(aclient, auth_headers, mirror_template, stubs, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    body = {"user_inputs": {"FINDINGS": "LV normal.", "CLINICAL_HISTORY": "?HCM"}, "stack": True,
            "stack_conclusion": "Normal cardiac MRI.", "stack_declined": [], "stack_values_na": ["RVEF", " ", 3]}
    r = (await aclient.post(f"/api/templates/{mirror_template.id}/generate", headers=auth_headers, json=body))
    assert r.status_code == 422   # a non-string item is rejected by the request model
    body["stack_values_na"] = ["RVEF", " "]
    body["stack_values_filled"] = ["LVEF"]
    r = (await aclient.post(f"/api/templates/{mirror_template.id}/generate", headers=auth_headers, json=body)).json()
    assert r["success"] and stubs["mirror"][0]["stack"]["values_na"] == ["RVEF"]
    assert stubs["mirror"][0]["stack"]["values_filled"] == ["LVEF"]
    await _drain_options()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_stack.py tests/test_template_lean.py tests/test_template_generate_endpoint.py -q -k "missing_values or values or required_values or na_"`
Expected: FAIL:
- `TypeError: stack_brief() got an unexpected keyword argument 'values_decided'`;
- the lean tests at `"LIST_MISSING" not in …`;
- `KeyError: 'required_values'`;
- the endpoint test with `KeyError: 'values_na'`.

- [ ] **Step 3: Write the minimal implementation**

**`template_stack.py`.** Add this module constant after `_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")`:

```python
# The value cluster settled the template's required values in the scratchpad: code removed LIST_MISSING from this
# sheet and writes the "Values not provided" line itself (template_required_values), so the generator writes none.
MISSING_VALUES_RULE = (
    "\n- **Missing values:** the radiologist settled this template's required values in the scratchpad, and code "
    "adds the \"Values not provided\" line itself: write no list of missing or unprovided values, and no "
    "placeholder for one.")
```

Change

```python
def stack_brief(sheet: str, conclusion: str, declined: Sequence[str] = ()) -> str:
```

to

```python
def stack_brief(sheet: str, conclusion: str, declined: Sequence[str] = (), values_decided: bool = False) -> str:
```

Replace

```python
    parts.append(
        "## Scratchpad Session\n"
```

with

```python
    session = (
        "## Scratchpad Session\n"
```

and replace

```python
        "leave it out — never estimate, infer or fill one in.")
    removed = [t.strip() for t in declined if t.strip()]
```

with

```python
        "leave it out — never estimate, infer or fill one in.")
    if values_decided:
        session += MISSING_VALUES_RULE
    parts.append(session)
    removed = [t.strip() for t in declined if t.strip()]
```

**`template_manager.py`** (`:2583`). Replace

```python
            brief = stack_brief(skill_sheet, stack.get("conclusion") or "", stack.get("declined") or ())
```

with

```python
            brief = stack_brief(skill_sheet, stack.get("conclusion") or "", stack.get("declined") or (),
                                values_decided=stack.get("values_decided") is True)
```

**`template_lean.py`.** After `from .template_context_rules import decided_block, resolve_context_rules, sheet_headers, strip_slot_sentences`, add:

```python
from .template_required_values import apply_required_values, backstop, values_applied, write_missing
```

In `gen()`, replace

```python
        rec["context_rules"] = resolved.record
        block = decided_block(resolved.decided)
        gen_sheet = resolved.sheet + ("\n\n" + block if block else "")
        rec["lat"]["rules_s"] = round(time.time() - t0, 1)
        t1 = time.time()
        out = await TemplateManager()._generate_report_skill_sheet_guided(
            template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": gen_sheet, "scan_type": scan_type},
            user_inputs={"FINDINGS": findings, "CLINICAL_HISTORY": history}, stack=stack)
```

with

```python
        rec["context_rules"] = resolved.record
        base, gen_stack = resolved.sheet, stack
        if stack is not None and stack.get("values_na") is not None:
            # The value cluster (requirements spec 2026-10-12 part 1): code takes the LIST_MISSING lines out and writes
            # the N/A line itself after the check. Only a clean apply tells the generator; otherwise today's sheet.
            text, rec["required_values"] = apply_required_values(resolved.sheet, stack["values_na"])
            ok = values_applied(rec["required_values"])
            base = text if ok else resolved.sheet
            gen_stack = {**stack, "values_decided": ok}
        block = decided_block(resolved.decided)
        gen_sheet = base + ("\n\n" + block if block else "")
        rec["lat"]["rules_s"] = round(time.time() - t0, 1)
        t1 = time.time()
        out = await TemplateManager()._generate_report_skill_sheet_guided(
            template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": gen_sheet, "scan_type": scan_type},
            user_inputs={"FINDINGS": findings, "CLINICAL_HISTORY": history}, stack=gen_stack)
```

Then, around the check, replace

```python
    vet_t = asyncio.ensure_future(vetted()) if opts_t is not None else None
    try:
        final, checked_opts, quality = await checked()
    except BaseException:
        if vet_t is not None:
            vet_t.cancel()
            opts_t.cancel()
        raise
```

with

```python
    vet_t = asyncio.ensure_future(vetted()) if opts_t is not None else None
    # The value cluster's backstop, beside the check: a filled value the report does not state is listed and flagged
    vrec = rec.get("required_values")
    values_on = vrec is not None and values_applied(vrec)
    bs_t = (asyncio.ensure_future(backstop(report, vrec["lists"], (stack or {}).get("values_filled") or []))
            if values_on else None)
    try:
        final, checked_opts, quality = await checked()
    except BaseException:
        if bs_t is not None:
            bs_t.cancel()
        if vet_t is not None:
            vet_t.cancel()
            opts_t.cancel()
        raise
    if bs_t is not None:
        # The N/A line, by code, at its section's TOP / END (never sent through the check's repair)
        lists, flags, vrec["backstop"] = await bs_t
        if flags:
            quality = {**(quality or {"enabled": False})}
            quality["review"] = [*(quality.get("review") or []), *flags]
        final, vrec["stripped"] = write_missing(final, sheet, lists)
```

`backstop` never raises, so awaiting it cannot break Generate.

**`main.py`** (`TemplateGenerateRequest`, `:679`). After `stack_conclusion: str = ""  # the conclusion the radiologist confirmed (the impression phrases it)`, add:

```python
    stack_values_na: Optional[List[str]] = None  # value cluster: required values marked N/A (None: no cluster this session)
    stack_values_filled: Optional[List[str]] = None  # value cluster: values filled from the dictation (post-gen backstop)
```

Then (`:1912-1913`) replace

```python
        _stack = ({"conclusion": request.stack_conclusion, "declined": request.stack_declined or []}
                  if request.stack else None)
```

with

```python
        _stack = ({"conclusion": request.stack_conclusion, "declined": request.stack_declined or []}
                  if request.stack else None)
        if _stack is not None and request.stack_values_na is not None:
            # The value cluster settled the template's required values: these were marked N/A (template_required_values)
            _stack["values_na"] = [x.strip() for x in request.stack_values_na if x.strip()][:40]
            _stack["values_filled"] = [x.strip() for x in (request.stack_values_filled or []) if x.strip()][:40]
```

**`template_pipeline.py`** (`candidate_record`, `:382`). Replace

```python
            "context_rules": result.get("context_rules"),
```

with

```python
            "context_rules": result.get("context_rules"),
            "required_values": result.get("required_values"),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_template_stack.py tests/test_template_lean.py tests/test_template_generate_endpoint.py tests/test_template_required_values.py -q`
Expected: PASS. The existing stack tests keep asserting `stack == {"conclusion": …, "declined": […]}`, because `values_na` and `values_decided` are added only when the client sends values.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py`
Expected: the 3878 baseline plus the new tests, all passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/src/rapid_reports_ai/template_lean.py backend/src/rapid_reports_ai/template_stack.py backend/src/rapid_reports_ai/template_manager.py backend/src/rapid_reports_ai/template_pipeline.py backend/tests/test_template_stack.py backend/tests/test_template_lean.py backend/tests/test_template_generate_endpoint.py
git commit -m "feat(values): Generate — code writes the radiologist's N/A line; generator writes no list

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 8: Frontend chip state machine (`values.ts`), types, API

**Files:**
- Create: `frontend/src/lib/hybrid-stack/values.ts`
- Modify: `frontend/src/lib/hybrid-stack/types.ts` (`:59`, `:71-92`)
- Modify: `frontend/src/lib/hybrid-stack/api.ts`
- Test: `frontend/src/lib/hybrid-stack/values.test.ts`, `frontend/src/lib/hybrid-stack/api.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/hybrid-stack/values.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
	blockingValues, chipLabel, enterValue, failFill, filledItems, initialChips, isFilling, keepStated, markNa, markRestNa, mergeFill,
	naItems, startFill, valueStatements, valuesKey
} from './values';
import type { ValueChip } from './types';

const ITEMS = ['LVEF', 'LVEDVi', 'RVEF'];
const open = (item: string): ValueChip => ({ item, state: 'open', value: null, quote: null });

describe('value cluster chips', () => {
	it('start open, in the template order', () => {
		expect(initialChips(ITEMS)).toEqual(ITEMS.map(open));
		expect(blockingValues(initialChips(ITEMS))).toEqual(ITEMS);
	});

	it('a fill sets filled and open chips; the radiologist\'s entries and N/A marks stand', () => {
		let c = enterValue(initialChips(ITEMS), 'LVEDVi', '98 mL/m²');
		c = markNa(c, 'RVEF');
		c = mergeFill(c, [
			{ item: 'lvef', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
			{ item: 'LVEDVi', state: 'filled', value: '90', quote: 'LVEDVi 90.' },
			{ item: 'RVEF', state: 'open', value: null, quote: null }
		]);
		expect(c).toEqual([
			{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
			{ item: 'LVEDVi', state: 'entered', value: '98 mL/m²', quote: null },
			{ item: 'RVEF', state: 'na', value: null, quote: null }
		]);
		expect(blockingValues(c)).toEqual([]);
		expect(mergeFill(c, [])[0]).toEqual(open('LVEF')); // a filled chip the next fill does not confirm opens again
	});

	it('stated with no sentence named needs a look; once kept it stays kept', () => {
		let c = mergeFill(initialChips(['Conus level']), [{ item: 'Conus level', state: 'filled', value: null, quote: null }]);
		expect(c[0]).toEqual({ item: 'Conus level', state: 'check', value: null, quote: null });
		expect(blockingValues(c)).toEqual(['Conus level']);
		c = keepStated(c, 'Conus level');
		expect(c[0]).toEqual({ item: 'Conus level', state: 'filled', value: null, quote: null, kept: true });
		expect(blockingValues(c)).toEqual([]);
		c = mergeFill(startFill(c), [{ item: 'Conus level', state: 'filled', value: null, quote: null }]);
		expect(c[0].state).toBe('filled');
	});

	it('while a fill runs every chip but the radiologist\'s own is filling; a failed fill opens them', () => {
		let c = markNa(mergeFill(initialChips(ITEMS), [{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' }]), 'RVEF');
		c = startFill(c);
		expect(c.map((x) => x.state)).toEqual(['filling', 'filling', 'na']);
		expect(isFilling(c)).toBe(true);
		expect(chipLabel(c[0])).toBe('LVEF …');
		expect(failFill(c).map((x) => x.state)).toEqual(['open', 'open', 'na']);
		expect(isFilling(failFill(c))).toBe(false);
	});

	it('typing empty reopens a chip; Mark rest N/A closes only the open ones', () => {
		let c = enterValue(initialChips([...ITEMS, 'Conus level']), 'LVEF', ' 45% ');
		expect(c[0]).toEqual({ item: 'LVEF', state: 'entered', value: '45%', quote: null });
		expect(enterValue(c, 'LVEF', '  ')[0]).toEqual(open('LVEF'));
		c = mergeFill(c, [{ item: 'Conus level', state: 'filled', value: null, quote: null }]);
		c = markRestNa(c);
		expect(c.map((x) => x.state)).toEqual(['entered', 'na', 'na', 'check']); // a stated value is never marked N/A in bulk
	});

	it('Generate states only the values the radiologist typed (Hassan 2026-10-13); N/A items are listed', () => {
		const c: ValueChip[] = [
			{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
			{ item: 'Conus level', state: 'filled', value: null, quote: null, kept: true },
			{ item: 'LVEDVi', state: 'entered', value: '98 mL/m²', quote: null },
			{ item: 'RVEF', state: 'na', value: null, quote: null },
			open('LV mass index')
		];
		expect(valueStatements(c)).toEqual(['LVEDVi 98 mL/m²']);
		expect(naItems(c)).toEqual(['RVEF']);
		expect(filledItems(c)).toEqual(['LVEF', 'Conus level']); // the post-generation backstop checks these in the report
	});

	it('labels each state, and the gate key changes with any chip', () => {
		expect(chipLabel({ item: 'LVEF', state: 'filled', value: '45%', quote: 'q' })).toBe('LVEF 45%');
		expect(chipLabel({ item: 'Conus level', state: 'filled', value: null, quote: null, kept: true })).toBe('Conus level stated');
		expect(chipLabel({ item: 'Conus level', state: 'check', value: null, quote: null })).toBe('Conus level stated?');
		expect(chipLabel({ item: 'LVEDVi', state: 'entered', value: '98', quote: null })).toBe('LVEDVi 98');
		expect(chipLabel({ item: 'RVEF', state: 'na', value: null, quote: null })).toBe('RVEF N/A');
		expect(chipLabel(open('LV mass index'))).toBe('LV mass index —');
		const a = initialChips(ITEMS);
		expect(valuesKey(a)).toBe(valuesKey(initialChips(ITEMS)));
		expect(valuesKey(markNa(a, 'RVEF'))).not.toBe(valuesKey(a));
		expect(valuesKey(startFill(a))).not.toBe(valuesKey(a));
		expect(valuesKey(enterValue(a, 'LVEF', '45'))).not.toBe(valuesKey(enterValue(a, 'LVEF', '46')));
	});
});
```

Append to `frontend/src/lib/hybrid-stack/api.test.ts`:

```ts
describe('postValues', () => {
	it('posts the dictation and the template id to /values', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ values: [], ms: 1, error: null })));
		vi.stubGlobal('fetch', fetchMock);
		const { postValues } = await import('./api');
		await postValues('tok', { dictation: 'LVEF 45%.', template_id: 't1' });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/canvas/stack/values')).toBe(true);
		expect(JSON.parse(init.body as string)).toEqual({ dictation: 'LVEF 45%.', template_id: 't1' });
	});
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/values.test.ts src/lib/hybrid-stack/api.test.ts`
Expected: FAIL with `Failed to resolve import "./values"`, and `postValues is not a function`.

- [ ] **Step 3: Write the minimal implementation**

In `frontend/src/lib/hybrid-stack/types.ts`, replace the `SlimSheet` line

```ts
export interface SlimSheet { id: string | null; region_normals: Record<string, string[]>; not_assessable: string; status: string; ready: boolean }
```

with

```ts
export interface SlimSheet { id: string | null; region_normals: Record<string, string[]>; not_assessable: string; status: string; ready: boolean; required_values?: string[] }
/** The value cluster (requirements spec 2026-10-12 part 1): a template's required value and how it was resolved.
 *  check: stated, but no single sentence named (needs a look); filling: a fill is running. */
export type ValueState = 'filled' | 'entered' | 'na' | 'open' | 'check' | 'filling';
export interface ValueChip { item: string; state: ValueState; value: string | null; quote: string | null; kept?: boolean }
/** The server's smart fill: filled from the dictation (value null: stated without one number) or open. */
export interface ValueFill { item: string; state: 'filled' | 'open'; value: string | null; quote: string | null; score?: number | null }
export interface ValuesResult { values: ValueFill[]; ms: number; error: string | null }
```

In the `GateRecord` interface, replace

```ts
	units_hash: string;
}
```

with

```ts
	values?: ValueChip[]; // the value cluster at Confirm (absent: the template has no required values)
	units_hash: string;
}
```

Create `frontend/src/lib/hybrid-stack/values.ts`:

```ts
// The value cluster (requirements spec 2026-10-12 part 1): the template's required values as chips. The server fills
// what the dictation states (Jev decides, code reads the number); the radiologist types the rest or marks them N/A.
// The radiologist's own entries, N/A marks and kept "stated" chips are never overwritten by a fill. Open and check
// chips block Confirm (walkthrough stops); filling ones hold it while the fill runs.
import type { ValueChip, ValueFill } from './types';

const key = (s: string) => s.trim().toLowerCase();
const opened = (item: string): ValueChip => ({ item, state: 'open', value: null, quote: null });
const own = (c: ValueChip) => c.state === 'entered' || c.state === 'na';

export function initialChips(items: string[]): ValueChip[] {
	return items.map(opened);
}

/** A fill is running: every chip but the radiologist's own shows progress and holds Confirm. */
export function startFill(chips: ValueChip[]): ValueChip[] {
	return chips.map((c) => (own(c) ? c : { ...c, state: 'filling' }));
}

/** A fill from the server: entered and N/A chips stand; a stated value with its sentence is filled; one with no
 *  sentence named needs a look (check), unless the radiologist already kept it; anything else is open. */
export function mergeFill(chips: ValueChip[], fill: ValueFill[]): ValueChip[] {
	const by = new Map(fill.map((f) => [key(f.item), f]));
	return chips.map((c) => {
		if (own(c)) return c;
		const f = by.get(key(c.item));
		if (!f || f.state !== 'filled') return opened(c.item);
		if (f.quote) return { item: c.item, state: 'filled', value: f.value, quote: f.quote };
		return c.kept ? { item: c.item, state: 'filled', value: null, quote: null, kept: true } : { item: c.item, state: 'check', value: null, quote: null };
	});
}

/** The fill failed: chips the dictation filled are open again (never blocks on the network). */
export const failFill = (chips: ValueChip[]): ValueChip[] => mergeFill(chips, []);

/** A typed value; empty reopens the chip. */
export function enterValue(chips: ValueChip[], item: string, text: string): ValueChip[] {
	const t = text.trim();
	return chips.map((c) => (c.item !== item ? c : t ? { item, state: 'entered', value: t, quote: null } : opened(item)));
}

export function markNa(chips: ValueChip[], item: string): ValueChip[] {
	return chips.map((c) => (c.item === item ? { item, state: 'na', value: null, quote: null } : c));
}

/** The radiologist looked at a "stated?" chip and keeps it: stated in the dictation, no value read. */
export function keepStated(chips: ValueChip[], item: string): ValueChip[] {
	return chips.map((c) => (c.item === item ? { item, state: 'filled', value: null, quote: null, kept: true } : c));
}

/** "Mark rest N/A": every open chip (a sequence not acquired); a stated one is never marked N/A in bulk. */
export function markRestNa(chips: ValueChip[]): ValueChip[] {
	return chips.map((c) => (c.state === 'open' ? { item: c.item, state: 'na', value: null, quote: null } : c));
}

/** Items that block Confirm and are walkthrough stops: open, or stated with no sentence named. */
export const blockingValues = (chips: ValueChip[]): string[] => chips.filter((c) => c.state === 'open' || c.state === 'check').map((c) => c.item);
export const isFilling = (chips: ValueChip[]): boolean => chips.some((c) => c.state === 'filling');
export const naItems = (chips: ValueChip[]): string[] => chips.filter((c) => c.state === 'na').map((c) => c.item);
/** Values filled from the dictation: sent with Generate so the post-generation backstop checks the report states each. */
export const filledItems = (chips: ValueChip[]): string[] => chips.filter((c) => c.state === 'filled').map((c) => c.item);
export const valuesKey = (chips: ValueChip[]): string => chips.map((c) => `${c.item}\u0001${c.state}\u0001${c.value ?? ''}`).join('\u0002');

/** What Generate states as the radiologist's answers: only values they typed (Hassan 2026-10-13). A filled value
 *  reaches the report through the dictation alone. */
export const valueStatements = (chips: ValueChip[]): string[] =>
	chips.filter((c) => c.state === 'entered' && c.value).map((c) => `${c.item} ${c.value}`);

export function chipLabel(c: ValueChip): string {
	if (c.state === 'na') return `${c.item} N/A`;
	if (c.state === 'open') return `${c.item} —`;
	if (c.state === 'filling') return `${c.item} …`;
	if (c.state === 'check') return `${c.item} stated?`;
	return c.value ? `${c.item} ${c.value}` : `${c.item} stated`;
}
```

In `frontend/src/lib/hybrid-stack/api.ts`, change the type import to

```ts
import type { AssumedResult, DraftResult, GateRecord, GroupResult, ItemsResult, Region, SlimSheet, StackItem, StackSchema, StackUnit, ValuesResult } from './types';
```

and after `postSlimSheet` add:

```ts
/** The value cluster's smart fill: the template's required values filled from the dictation or open (fails open). */
export const postValues = (token: string | null, body: { dictation: string; template_id: string | null }) =>
	post<ValuesResult>(token, 'values', body);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/values.test.ts src/lib/hybrid-stack/api.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hybrid-stack/values.ts frontend/src/lib/hybrid-stack/values.test.ts frontend/src/lib/hybrid-stack/types.ts frontend/src/lib/hybrid-stack/api.ts frontend/src/lib/hybrid-stack/api.test.ts
git commit -m "feat(values): chip state machine (check, filling, kept), types and the /values call

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 9: Typed values in the FINDINGS block

**Files:**
- Modify: `frontend/src/lib/hybrid-stack/regionState.ts` (`:108-140`)
- Test: `frontend/src/lib/hybrid-stack/regionState.test.ts`

- [ ] **Step 1: Write the failing test**

In `frontend/src/lib/hybrid-stack/regionState.test.ts`, inside the `describe` that holds `'answers only: tapped rows, …'`, add this directly after that test:

```ts
	it('required values the radiologist typed are one answered line; filled ones stay as dictated (Hassan 2026-10-13)', () => {
		const gate: GateRecord = {
			confirmed_at: 't', conclusion_text: 'Normal.', conclusion_source: 'dictated', assumed_normal: [], remainder_normal: [],
			dictated_normal: [], units_hash: 'h', items: [], assumed: {}, removed: [], capped: [],
			values: [
				{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
				{ item: 'LVEDVi', state: 'entered', value: '98 mL/m²', quote: null },
				{ item: 'RVEF', state: 'na', value: null, quote: null }
			]
		};
		const block = buildFindingsBlock([u(0, 'LVEF 45%.', 'Liver', { abnormal: true })], GROUPS, gate);
		expect(block).toContain('\n\nAnswered by the radiologist: LVEDVi 98 mL/m².\n\n');
		expect(block).not.toContain('Answered by the radiologist: LVEF');
		expect(block).not.toContain('RVEF');
		expect(buildFindingsBlock([u(0, 'LVEF 45%.', 'Liver')], GROUPS, { ...gate, values: undefined })).not.toContain('Answered by');
	});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/regionState.test.ts`
Expected: FAIL: the block does not contain `Answered by the radiologist: LVEDVi 98 mL/m².`

- [ ] **Step 3: Write the minimal implementation**

In `frontend/src/lib/hybrid-stack/regionState.ts`, add beside the existing imports at the top of the file:

```ts
import { valueStatements } from './values';
```

In `buildFindingsBlock`, replace

```ts
	const parts = [findingsText(units, groups, extra), standalone.join('\n')];
	if (tray.length) parts.push(`${ASSUMED} ${tray.join(' ')}`);
```

with

```ts
	const parts = [findingsText(units, groups, extra), standalone.join('\n')];
	// The value cluster: required values the radiologist typed, stated as answers (filled ones are in the dictation)
	const values = valueStatements(gate.values ?? []);
	if (values.length) parts.push(`${ANSWERED} ${values.map((v) => `${v}.`).join(' ')}`);
	if (tray.length) parts.push(`${ASSUMED} ${tray.join(' ')}`);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/regionState.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hybrid-stack/regionState.ts frontend/src/lib/hybrid-stack/regionState.test.ts
git commit -m "feat(values): typed required values reach FINDINGS as the radiologist's answers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 10: `ValueChips.svelte`

**Files:**
- Create: `frontend/src/lib/hybrid-stack/ValueChips.svelte`
- Test: `frontend/src/lib/hybrid-stack/ValueChips.svelte.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/hybrid-stack/ValueChips.svelte.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import ValueChips from './ValueChips.svelte';
import type { ValueChip } from './types';

const VALUES: ValueChip[] = [
	{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
	{ item: 'LVEDVi', state: 'entered', value: '98', quote: null },
	{ item: 'RVEF', state: 'na', value: null, quote: null },
	{ item: 'LV mass index', state: 'open', value: null, quote: null },
	{ item: 'Conus level', state: 'check', value: null, quote: null },
	{ item: 'Aortic flow', state: 'filling', value: null, quote: null }
];
const props = () => ({ values: VALUES, onEnter: vi.fn(), onNa: vi.fn(), onRestNa: vi.fn(), onKeep: vi.fn() });

describe('ValueChips', () => {
	it('one line of chips, each with its state; a filled chip shows its source on hover', async () => {
		render(ValueChips, props());
		await expect.element(page.getByRole('button', { name: 'LVEF 45%' })).toHaveAttribute('data-state', 'filled');
		await expect.element(page.getByRole('button', { name: 'LVEF 45%' })).toHaveAttribute('title', 'From the dictation: "LVEF 45%."');
		await expect.element(page.getByRole('button', { name: 'LVEDVi 98' })).toHaveAttribute('data-state', 'entered');
		await expect.element(page.getByRole('button', { name: 'RVEF N/A' })).toHaveAttribute('data-state', 'na');
		await expect.element(page.getByRole('button', { name: 'LV mass index —' })).toHaveAttribute('data-state', 'open');
		await expect.element(page.getByRole('button', { name: 'Conus level stated?' })).toHaveAttribute('data-state', 'check');
		await expect.element(page.getByRole('button', { name: 'Aortic flow …' })).toHaveAttribute('data-state', 'filling');
	});

	it('click an open chip to type its value; Enter saves it', async () => {
		const p = props();
		render(ValueChips, p);
		await page.getByRole('button', { name: 'LV mass index —' }).click();
		await page.getByLabelText('Value for LV mass index').fill('60 g/m²');
		await userEvent.keyboard('{Enter}');
		expect(p.onEnter).toHaveBeenCalledWith('LV mass index', '60 g/m²');
	});

	it('a "stated?" chip can be kept as stated; N/A marks one chip; Escape cancels', async () => {
		const p = props();
		render(ValueChips, p);
		await page.getByRole('button', { name: 'Conus level stated?' }).click();
		await page.getByRole('button', { name: 'Stated ✓' }).click();
		expect(p.onKeep).toHaveBeenCalledWith('Conus level');
		await page.getByRole('button', { name: 'LV mass index —' }).click();
		await expect.element(page.getByRole('button', { name: 'Stated ✓' })).not.toBeInTheDocument();   // only for "stated?"
		await page.getByRole('button', { name: 'N/A', exact: true }).click();
		expect(p.onNa).toHaveBeenCalledWith('LV mass index');
		await page.getByRole('button', { name: 'LVEF 45%' }).click();
		await expect.element(page.getByLabelText('Value for LVEF')).toHaveValue('45%');
		await userEvent.keyboard('{Escape}');
		expect(p.onEnter).not.toHaveBeenCalled();
	});

	it('Mark rest N/A shows only while a chip is open; the walkthrough\'s current chip is ringed', async () => {
		const p = props();
		const r = render(ValueChips, { ...p, current: 'value:LV mass index' });
		await expect.element(page.getByRole('button', { name: 'LV mass index —' })).toHaveClass('ring-2');
		await expect.element(page.getByRole('button', { name: 'LVEF 45%' })).not.toHaveClass('ring-2');
		await page.getByRole('button', { name: 'Mark rest N/A' }).click();
		expect(p.onRestNa).toHaveBeenCalled();
		r.rerender({ ...p, values: VALUES.map((v) => (v.state === 'open' ? { ...v, state: 'na' as const } : v)) });
		await expect.element(page.getByRole('button', { name: 'Mark rest N/A' })).not.toBeInTheDocument();
	});

	it('renders nothing without required values', async () => {
		render(ValueChips, { ...props(), values: [] });
		await expect.element(page.getByTestId('value-cluster')).not.toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/ValueChips.svelte.test.ts`
Expected: FAIL with `Failed to resolve import "./ValueChips.svelte"`.

- [ ] **Step 3: Write the minimal implementation**

Create `frontend/src/lib/hybrid-stack/ValueChips.svelte`:

```svelte
<script lang="ts">
	// The value cluster (requirements spec 2026-10-12 part 1): the template's required values as one wrapped line of
	// chips at the top of the scratchpad. Filled from the dictation (its source on hover), typed, N/A, open, "stated?"
	// (stated, no sentence named: needs a look) or filling. Open and "stated?" chips block Confirm. Click a chip to
	// type its value; "Mark rest N/A" closes every open one (a sequence not acquired). Each chip is a walkthrough stop
	// (data-stop "value:<item>"), ringed while it is the current stop.
	import { tick } from 'svelte';
	import { chipLabel } from './values';
	import type { ValueChip } from './types';

	let {
		values,
		current = null,
		onEnter,
		onNa,
		onRestNa,
		onKeep
	}: {
		values: ValueChip[];
		/** The walkthrough's current stop ("value:<item>" rings that chip). */
		current?: string | null;
		/** A typed value (empty: the chip opens again). */
		onEnter: (item: string, text: string) => void;
		onNa: (item: string) => void;
		onRestNa: () => void;
		/** A "stated?" chip kept as stated. */
		onKeep: (item: string) => void;
	} = $props();

	let editing: string | null = $state(null);
	let text = $state('');
	const openCount = $derived(values.filter((v) => v.state === 'open').length);
	const tone: Record<ValueChip['state'], string> = {
		filled: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200',
		entered: 'border-sky-400/30 bg-sky-500/10 text-sky-200',
		na: 'border-white/10 bg-white/[0.03] text-gray-500',
		open: 'border-amber-400/50 bg-amber-500/10 text-amber-200',
		check: 'border-orange-400/50 bg-orange-500/10 text-orange-200',
		filling: 'border-white/10 bg-white/[0.03] text-gray-400 animate-pulse'
	};
	const ring = (v: ValueChip) => (current === `value:${v.item}` ? 'ring-2 ring-orange-400/60' : '');

	async function edit(v: ValueChip) {
		editing = v.item;
		text = v.value ?? '';
		await tick();
		document.querySelector<HTMLInputElement>('[data-testid="value-input"]')?.focus();
	}
	function save() {
		if (editing === null) return;
		onEnter(editing, text);
		editing = null;
	}
	function na() {
		if (editing === null) return;
		onNa(editing);
		editing = null;
	}
	function keep() {
		if (editing === null) return;
		onKeep(editing);
		editing = null;
	}
	function key(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			save();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			editing = null;
		}
	}
	const title = (v: ValueChip) =>
		v.state === 'filled' && v.quote ? `From the dictation: "${v.quote}"`
		: v.state === 'check' ? 'Stated in the dictation, but no single sentence gives its value: check it'
		: v.state === 'filling' ? 'Reading the dictation…'
		: v.state === 'open' ? 'Click to type the value' : 'Click to change';
</script>

{#if values.length}
	<section aria-label="Required values" data-testid="value-cluster"
		class="flex flex-wrap items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2 text-xs">
		<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500">Required values</span>
		{#each values as v (v.item)}
			{#if editing === v.item}
				<span class="flex items-center gap-1 rounded {ring(v)}" data-stop={`value:${v.item}`}>
					<span class="text-gray-300">{v.item}</span>
					<input data-testid="value-input" aria-label={`Value for ${v.item}`} bind:value={text} onkeydown={key}
						class="w-24 rounded border border-white/15 bg-black/30 px-1.5 py-0.5 text-gray-100" />
					<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-gray-300 hover:bg-white/[0.06]" onclick={save}>Save</button>
					{#if v.state === 'check'}
						<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-emerald-200 hover:bg-white/[0.06]" onclick={keep}>Stated ✓</button>
					{/if}
					<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-gray-400 hover:bg-white/[0.06]" onclick={na}>N/A</button>
				</span>
			{:else}
				<button type="button" class="rounded border px-1.5 py-0.5 {tone[v.state]} {ring(v)}" data-state={v.state} data-stop={`value:${v.item}`}
					title={title(v)} onclick={() => edit(v)}>{chipLabel(v)}</button>
			{/if}
		{/each}
		{#if openCount}
			<button type="button" class="ml-auto rounded border border-white/15 px-1.5 py-0.5 text-gray-400 hover:bg-white/[0.06]" onclick={onRestNa}>Mark rest N/A</button>
		{/if}
	</section>
{/if}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/ValueChips.svelte.test.ts`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hybrid-stack/ValueChips.svelte frontend/src/lib/hybrid-stack/ValueChips.svelte.test.ts
git commit -m "feat(values): the required-values chip line (type, N/A, keep stated, Mark rest N/A, ring)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 11: `HybridStackView` — chips at the top; open and "stated?" chips block Confirm

**Files:**
- Modify: `frontend/src/lib/hybrid-stack/HybridStackView.svelte`:
  - imports (`:9-12`);
  - props (`:24-158`);
  - `stops` (`:285-295`);
  - the walkthrough label (`:1137`);
  - the Confirm bar (`:1156`);
  - the top of the markup (`:826`).
- Test: `frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts`

- [ ] **Step 1: Write the failing test**

Add this test inside `describe('HybridStackView v2', …)` in `frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts`:

```ts
	it('open and "stated?" required values block Confirm and are walked to, ringed; resolving them frees Confirm', async () => {
		const onEnterValue = vi.fn();
		const onKeepValue = vi.fn();
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })];
		const values = [
			{ item: 'LVEF', state: 'filled' as const, value: '45%', quote: 'LVEF 45%.' },
			{ item: 'RVEF', state: 'open' as const, value: null, quote: null },
			{ item: 'Conus level', state: 'check' as const, value: null, quote: null }
		];
		const props = { ...base(), units, onEnterValue, onKeepValue, conclusion: { kind: 'draft', text: 'Liver cyst.', edited: false } as const, namedNormals: true };
		const r = render(HybridStackView, { ...props, values });
		await expect.element(page.getByTestId('value-cluster')).toBeInTheDocument();
		await expect.element(page.getByText('2 required values to resolve')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Confirm · 2 to resolve' }).click();
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Checking 1 of 2 · Required value');
		await expect.element(page.getByRole('button', { name: 'RVEF —' })).toHaveClass('ring-2');
		await page.getByRole('button', { name: 'RVEF —' }).click();
		await page.getByLabelText('Value for RVEF').fill('50%');
		await userEvent.keyboard('{Enter}');
		expect(onEnterValue).toHaveBeenCalledWith('RVEF', '50%');
		const typed = [values[0], { item: 'RVEF', state: 'entered' as const, value: '50%', quote: null }, values[2]];
		r.rerender({ ...props, values: typed });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Checking 2 of 2 · Required value · needs a look');
		await page.getByRole('button', { name: 'Conus level stated?' }).click();
		await page.getByRole('button', { name: 'Stated ✓' }).click();
		expect(onKeepValue).toHaveBeenCalledWith('Conus level');
		r.rerender({ ...props, values: [typed[0], typed[1], { item: 'Conus level', state: 'filled' as const, value: null, quote: null, kept: true }] });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('All checked');
		await page.getByRole('button', { name: 'Confirm', exact: true }).click();
		expect(props.onConfirm).toHaveBeenCalled();
	});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/HybridStackView.svelte.test.ts -t "required values"`
Expected: FAIL: `value-cluster` is not in the document.

- [ ] **Step 3: Write the minimal implementation**

In `frontend/src/lib/hybrid-stack/HybridStackView.svelte`, make these edits.

**Imports.** Replace

```ts
	import type { StackItem, StackUnit, ViewRow } from './types';
```

with

```ts
	import type { StackItem, StackUnit, ValueChip, ViewRow } from './types';
	import ValueChips from './ValueChips.svelte';
```

**Destructure.** Replace

```ts
		skipped = [],
		reviewing = false,
```

with

```ts
		skipped = [],
		values = [],
		onEnterValue = () => {},
		onValueNa = () => {},
		onValuesRestNa = () => {},
		onKeepValue = () => {},
		reviewing = false,
```

**Prop types.** Replace

```ts
		skipped?: string[];
		/** The end-of-dictation review is running / will run when dictation stops. */
```

with

```ts
		skipped?: string[];
		/** The value cluster (template sessions): the template's required values; open and "stated?" ones block Confirm. */
		values?: ValueChip[];
		onEnterValue?: (item: string, text: string) => void;
		onValueNa?: (item: string) => void;
		onValuesRestNa?: () => void;
		/** A "stated?" chip kept as stated. */
		onKeepValue?: (item: string) => void;
		/** The end-of-dictation review is running / will run when dictation stops. */
```

**Count.** Replace

```ts
	const openRows = $derived(openCount(items, tapped, removed, skipped));
```

with

```ts
	const openRows = $derived(openCount(items, tapped, removed, skipped));
	const openValueCount = $derived(values.filter((v) => v.state === 'open' || v.state === 'check').length);
```

**Stops.** Replace

```ts
	// What blocks Confirm, top to bottom: open referral rows, then each blocking check by its line's position.
```

with

```ts
	// What blocks Confirm, top to bottom: open referral rows, open or "stated?" required values, then each blocking
	// check by its line's position.
```

and replace

```ts
		const all = [...rows, ...blocking];
```

with

```ts
		const valueStops = values.filter((v) => v.state === 'open' || v.state === 'check').map((v) => `value:${v.item}`);
		const all = [...rows, ...valueStops, ...blocking];
```

Directly after the line `const currentCheck = $derived(...);`, add:

```ts
	const currentValue = $derived(current?.startsWith('value:') ? (values.find((v) => `value:${v.item}` === current) ?? null) : null);
```

**Walkthrough label.** Replace

```svelte
{current?.startsWith('row:') ? 'Referral question' : currentCheck ? checkLabel(currentCheck.kind) : ''}
```

with

```svelte
{current?.startsWith('row:') ? 'Referral question' : currentValue ? (currentValue.state === 'check' ? 'Required value · needs a look' : 'Required value') : currentCheck ? checkLabel(currentCheck.kind) : ''}
```

**Top of the scratchpad.** Replace

```svelte
<div class="space-y-3" data-testid="hybrid-stack">
```

with

```svelte
<div class="space-y-3" data-testid="hybrid-stack">
	<ValueChips {values} {current} onEnter={onEnterValue} onNa={onValueNa} onRestNa={onValuesRestNa} onKeep={onKeepValue} />
```

**Confirm bar.** After the line

```svelte
			<span class="rounded px-1.5 py-0.5 {openRows ? 'bg-amber-500/15 text-amber-200' : 'bg-white/5 text-gray-500'}">{openRows} referral {openRows === 1 ? 'question' : 'questions'} open</span>
```

add

```svelte
			{#if openValueCount}<span class="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-200" data-gate="values">{openValueCount} required {openValueCount === 1 ? 'value' : 'values'} to resolve</span>{/if}
```

- [ ] **Step 4: Run the component tests to verify they pass**

Run: `cd frontend && bunx vitest run src/lib/hybrid-stack/HybridStackView.svelte.test.ts src/lib/hybrid-stack/ValueChips.svelte.test.ts`
Expected: PASS (all). The existing tests are unchanged, because `values` defaults to `[]`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hybrid-stack/HybridStackView.svelte frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts
git commit -m "feat(values): chips at the top of the scratchpad; open and stated? values block Confirm

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 12: Session wiring (`DictationScratchpad`, `TemplateForm`)

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`:
  - imports (`:41-47`);
  - state (`:301`);
  - `gateKey` (`:365-367`);
  - `gateReview` (`:1579`);
  - `loadSlimSheet` (`:1791-1809`);
  - `stackConfirm` (`:1971`);
  - `resetStack` (`:2053-2054`);
  - the `HybridStackView` props (`:2639-2640`).
- Modify: `frontend/src/routes/components/TemplateForm.svelte` (imports `:12-14`; body `:463`)

This task wires tested units together inside two large legacy-syntax components that have no unit tests. It is verified by svelte-check, the full suite, and a hand check (Step 4).

- [ ] **Step 1: Wire `DictationScratchpad.svelte`**

**API import.** Replace

```ts
	import { postAssumed, postChanged, postDictationCheck, postUnfinished, postClose, postConclusionCheck, postDraft, postGroup, postItems, postLog, postRecheck, postSlimSheet } from '$lib/hybrid-stack/api';
```

with

```ts
	import { postAssumed, postChanged, postDictationCheck, postUnfinished, postClose, postConclusionCheck, postDraft, postGroup, postItems, postLog, postRecheck, postSlimSheet, postValues } from '$lib/hybrid-stack/api';
	import { enterValue, failFill, initialChips, isFilling, keepStated, markNa, markRestNa, mergeFill, startFill, valuesKey } from '$lib/hybrid-stack/values';
```

**Types import.** Replace

```ts
	import type { GateItem, GateRecord, ItemsResult, Region, StackCommand, StackItem, StackUnit } from '$lib/hybrid-stack/types';
```

with

```ts
	import type { GateItem, GateRecord, ItemsResult, Region, StackCommand, StackItem, StackUnit, ValueChip } from '$lib/hybrid-stack/types';
```

**State.** Replace

```ts
	let stackTemplateUnusable = false;
	let slimSeq = 0;
```

with

```ts
	let stackTemplateUnusable = false;
	let slimSeq = 0;
	// The value cluster (requirements spec 2026-10-12 part 1): the template's required values (from the slim-sheet call),
	// filled when the sheet loads and at each end-of-dictation review; the radiologist's own answers stand.
	let valueChips: ValueChip[] = [];
	let valuesSeq = 0;
```

**`gateKey`.** Replace

```ts
		JSON.stringify(confirmedAssumed)].join('\u0003');
```

with

```ts
		JSON.stringify(confirmedAssumed), valuesKey(valueChips)].join('\u0003');
```

**`gateReview`.** Replace

```ts
	async function gateReview(text: string): Promise<void> {
		const before = reviewedAbnormal;
```

with

```ts
	async function gateReview(text: string): Promise<void> {
		void refreshValues(text);
		const before = reviewedAbnormal;
```

**`loadSlimSheet`.** Replace

```ts
		stackNotAssessable = '';
		stackTemplateUnusable = false;
		onStackSheet(null);
```

with

```ts
		stackNotAssessable = '';
		stackTemplateUnusable = false;
		valueChips = [];
		onStackSheet(null);
```

and replace

```ts
			stackNotAssessable = res.not_assessable;
			onStackSheet(res.id);
```

with

```ts
			stackNotAssessable = res.not_assessable;
			valueChips = initialChips(res.required_values ?? []);
			if (verbatimNow.trim()) void refreshValues(verbatimNow); // dictation already there: fill now, not at the next review
			onStackSheet(res.id);
```

**`refreshValues`.** Directly after the closing `}` of `loadSlimSheet` (before the `/** Which region normals stay assumed` comment), add:

```ts
	/** The value cluster's smart fill: Jev says which required values the dictation states, code reads each number.
	 *  The chips show "filling" (Confirm waits) until it answers; a failure leaves them open (never blocks for long). */
	async function refreshValues(text: string): Promise<void> {
		if (!stackTemplateId || !valueChips.length) return;
		const seq = ++valuesSeq;
		valueChips = startFill(valueChips);
		try {
			const res = await postValues($token, { dictation: text, template_id: stackTemplateId });
			if (seq !== valuesSeq) return;
			valueChips = res.error ? failFill(valueChips) : mergeFill(valueChips, res.values);
		} catch {
			if (seq === valuesSeq) valueChips = failFill(valueChips);
		}
	}
```

**`stackConfirm`.** Replace

```ts
			units_hash: gateKey,
```

with

```ts
			units_hash: gateKey,
			...(valueChips.length ? { values: valueChips } : {}),
```

**`resetStack`.** Replace

```ts
		assumedSnap = null;
		scheduleItems(0);
```

with

```ts
		assumedSnap = null;
		valuesSeq++; // a fill still running belongs to the old case
		valueChips = initialChips(valueChips.map((c) => c.item));
		scheduleItems(0);
```

**`HybridStackView` props.** Replace

```svelte
							onConfirm={stackConfirm} onConfirmGenerate={onStackGenerate ? () => { stackConfirm(); onStackGenerate?.(); } : null} onDeleteRegion={stackDeleteRegion} onAppend={stackAppend}
							syncing={assumedBehind || checksBehind ||
```

with

```svelte
							onConfirm={stackConfirm} onConfirmGenerate={onStackGenerate ? () => { stackConfirm(); onStackGenerate?.(); } : null} onDeleteRegion={stackDeleteRegion} onAppend={stackAppend}
							values={valueChips} onEnterValue={(i, t) => (valueChips = enterValue(valueChips, i, t))} onValueNa={(i) => (valueChips = markNa(valueChips, i))}
							onValuesRestNa={() => (valueChips = markRestNa(valueChips))} onKeepValue={(i) => (valueChips = keepStated(valueChips, i))}
							syncing={isFilling(valueChips) || assumedBehind || checksBehind ||
```

- [ ] **Step 2: Send the N/A items with Generate (`TemplateForm.svelte`)**

Replace

```ts
	import { hybridStackOn } from '$lib/hybrid-stack/flag';
```

with

```ts
	import { hybridStackOn } from '$lib/hybrid-stack/flag';
	import { filledItems, naItems } from '$lib/hybrid-stack/values';
```

and replace

```ts
						? { stack: true, stack_declined: declined, stack_conclusion: stackGate?.conclusion_text ?? '' }
```

with

```ts
						? { stack: true, stack_declined: declined, stack_conclusion: stackGate?.conclusion_text ?? '',
							...(stackGate?.values
								? { stack_values_na: naItems(stackGate.values), stack_values_filled: filledItems(stackGate.values) }
								: {}) }
```

- [ ] **Step 3: Type-check and run the full frontend suite**

Run: `cd frontend && bun run check 2>&1 | tail -3`
Expected: the same problem count as the 1194 baseline, with no new entries in the touched files. If the count rose, run `bun run check 2>&1 | grep -E "DictationScratchpad|TemplateForm|HybridStackView|ValueChips|values.ts"` and fix what it names.

Run: `cd frontend && bunx vitest run 2>&1 | tail -6`
Expected: the 716 baseline plus the new tests passing; the only failure is the known `page.svelte.spec` h1.

- [ ] **Step 4: Hand check in the app (controller or Hassan)**

Start the app as usual (the `run` skill). Open a template session with a CMR template that has a `LIST_MISSING` line (e.g. CMR Non-Stress), and check each of these:
1. The chips show open at the top before any dictation. Pasting or dictating text before the sheet loads fills them once it loads.
2. Dictate "LVEF 45%. RV normal." and stop.
   - The chips pulse "…" and Confirm reads "Updating…".
   - Then LVEF shows `LVEF 45%` (green, with the quote on hover), and the others are open.
3. Confirm reads `Confirm · N to resolve`. The walkthrough stops at each open chip with the orange ring, and at any "stated?" chip ("needs a look").
4. "Mark rest N/A" resolves the open ones, and Confirm works.
5. Editing a chip after Confirm re-arms the gate.
6. In the Generate request body (devtools), `stack_values_na` lists the N/A items and `stack_values_filled` the filled ones.
7. **In the report:**
   - one line reads exactly `Values not provided: <N/A items>.`, at the top (or end) of the template's list section;
   - there is no other missing-values list, in any wording (the sheet's own prose may describe one, e.g. "MISSING VALUES - PLEASE SUPPLY:");
   - LVEF 45% appears only as dictated;
   - a typed value appears once.
8. **Backstop.** In a dictation where a filled value's sentence is easy to lose (e.g. buried mid-paragraph), check two things:
   - if the report omits it, it joins the `Values not provided` line and shows as a `value_missing` review flag;
   - if the report keeps it, nothing is added.

Note any surprise for Hassan; change no behaviour beyond this plan.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte frontend/src/routes/components/TemplateForm.svelte
git commit -m "feat(values): fill on sheet load and at the review, filling holds Confirm, N/A items to Generate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 13: Full verification and independent review (no merge)

- [ ] **Step 1: Backend full suite**

Run: `cd backend && .venv/bin/python -m pytest -q --deselect tests/test_provider_key_routing.py 2>&1 | tail -3`
Expected: `3878 + N passed`, 0 failed.

- [ ] **Step 2: Frontend full suite and svelte-check**

Run: `cd frontend && bunx vitest run 2>&1 | tail -6 && bun run check 2>&1 | tail -3`
Expected: the only failure is the known `page.svelte.spec` h1, and svelte-check stays at the 1194 baseline.

- [ ] **Step 3: Independent review**

Dispatch `superpowers:code-reviewer` on `git diff 6026fd7b..HEAD`, against this plan and spec part 1 with the two departures (A, B) above. If it cannot run, stop and ask Hassan before any merge.

- [ ] **Step 4: Hand-off**

Report to Hassan:
- the lab result (Task 4, Step 8);
- the review outcome;
- the hand check (Task 12, Step 4);
- the risks below.

Merge only on his go-ahead; never push.

---

## Risks (for the reviewer and Hassan)

- **A false "stated".** The chip shows filled, but the number never reaches the report, because filled values come only from the dictation. Three guards cover this:
  - starting at 0.8;
  - leading the lab with the false-stated rate;
  - the post-generation backstop, which lists and flags any filled value the report lacks.
  
  The backstop's own misses (recall) and false missing (a present value listed as not provided) are measured by the lab's secondary metric. It reads the report with `q_stated`, whose wording names "the dictated findings"; the lab shows whether that matters.
- **The backstop reads the report before the check's repair.** A value sentence that the post-generation check's repair then removes is not caught: the value leaves the report and is not added to the N/A line.
- **Backstop latency.** One extra Jev call (batched) runs in parallel with the post-generation check, so it adds wall time only when it is slower than the check.
- **Clause choice is the weakest Jev step** (Jev is weak at overlapping spans). A wrong clause holding one number shows a **wrong number** with its quote on the chip. Since decision A, that number is display only (the report uses the dictation), but it can mislead the radiologist's look. The lab's `value_wrong` count measures this, and a poor result can change the design (Task 4, Step 8).
- **The generator's own missing-values wording.** Sheet prose such as "MISSING VALUES - PLEASE SUPPLY:" may still lead the generator to write a list in its own words. The session rule forbids it, but code strips only lines beginning "Values not provided". Watch for it in the hand check.
- **"stated?" chips add clicks.** This happens when Jev states an item but names no clause (non-numeric values like "Conus at L1", or long dictations past 80 clauses). The lab's `no_quote` count measures it.
- **Number reader gaps.** A unit outside the list (e.g. `mmol/L`) gives the bare number. The clause split ignores " and ", so two values joined by "and" give "stated" with no value. Both are safe.
- **Fill latency.** Up to 12 items run as 3 parallel calls with a 6 s timeout each, and Confirm shows "Updating…" meanwhile. A timeout leaves the chips open, which is safe, but the radiologist then types values the dictation already stated. The lab reports milliseconds per fill.
- **Old clients.** They send no `stack_values_na`, so the sheet, the brief and the report stay exactly as today.
