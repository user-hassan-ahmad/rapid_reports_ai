# Guideline Draft Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the pack card from a silent decider into a visible draft:
- every value is read, pre-filled or asked, and editable inline;
- Calculate runs the engine over the confirmed values and returns a cited result, which is the only thing Apply
  writes;
- a dictated category is checked, not recomputed;
- a finding with several lesions asks "Which lesion?" once;
- the reference highlights what this case hit.

The gate for Apply is a lab on real production dictations, labelled by Claude Fable 5.1 and spot-checked by Hassan.

**Architecture:**
- **What stays.** The engine (`library/engine.py`) and the Settlement/`finish` split (`library/pack_preview.py`),
  with the preview cache (`library/preview_cache.py`).
- **Settlement.** It keeps every proposal that has a verbatim, in-scope quote, and tags each with a value state
  (`read` or `prefilled`) and the reasons it is not read. The guards that used to force asks become those reasons, or
  are retired.
- **`finish`** builds a `draft` (one `DraftValue` per input) and a draft outcome. It never builds an Apply-able
  proposal for a pack.
- **`POST /calculate`** evaluates exactly the values the client shows and returns a `Calculation` with:
  - the result, with citations and the trace;
  - each value's state;
  - the checker verdict;
  - the reference highlight.
- **The lab** (`scripts/guidelines/real_lab.py`) runs before the redesign, to set a baseline, and again after it.

**Tech Stack:** Python 3, FastAPI, pydantic v2, pytest (asyncio_mode auto), pydantic-ai via `_run_agent_with_model`
(Qwen on Cerebras), Jev via `jev_post`, the Anthropic Python SDK (installed 0.71.0) for the Fable labeller, and
Metabase `/api/dataset` for read-only production SQL.

**Spec:** `docs/superpowers/specs/2026-10-12-guideline-library-design.md`, amended 2026-10-13:
- §7.4 the draft card and the order of `needed`;
- §7.5 value states;
- §7.6 inline edit;
- §7.7 Calculate and Apply;
- §7.8 checker mode;
- §7.9 Which lesion?;
- §7.10 the safety rule and the reversal;
- §7.11 case-aware reference;
- §12 "Draft card slice" and the real-dictation Apply gate.

**Approved direction:** `.superpowers/sdd/2026-10-13-guideline-library-next-slice/settling-root-cause-review.md`.
Binding decisions are in the "Hassan 2026-10-13: redesign approved" section of
`.superpowers/sdd/2026-10-13-guideline-library-next-slice/progress.md`. Current numbers are in
`docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab_next_slice.md` and
`.superpowers/sdd/2026-10-13-guideline-library-next-slice/task-7-run2-report.md`.

**Frontend:** this branch has no Copilot card UI. This plan builds and tests the backend API contract the UI will
read:
- /open and /preview: `Preview.draft`, `waiting`, `draft_outcome`, `lesions`, `checker`, `highlight`;
- /calculate: `Calculation`.

The card UI, and the Task 14 mock-up that Hassan approves first, are **out of scope** for this plan (spec §12 "Draft
card slice" item 9).

## Global Constraints

- **Repository rules:**
  - Worktree `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot`, branch
    `feat/scratchpad-copilot`.
  - Never push. Never amend. Never commit `backend/uv.lock`. Stage only the files a task names.
  - Every commit ends with:
    ```
    Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_01FMmCUNDQq6iPV6tn4pSRPH
    ```
- **Tests:**
  - Tests are flat in `backend/tests/`, named `test_library_*.py` or `test_copilot_*.py`. Run them with
    `cd backend && PYTHONPATH=src .venv/bin/pytest …`.
  - Tests make no real model, Jev, Anthropic, Metabase or network calls. Mock `PP._call`, `P.jev_post`, `M._call`
    and `M._pgate`, and the Anthropic client.
- **Safety rule (spec §7.10): nothing reaches the report unseen.**
  - A pack preview never returns an Apply-able `proposal`. Only `/calculate` returns a result.
  - `/calculate` evaluates only the values the client sends. An input the client did not send is `unknown`, never
    filled from the settlement.
  - A value is `read` only by the §7.5 rule. Booleans and the states (absent, not assessable) are never read.
  - No value is proposed without a verbatim, in-scope quote.
- **Production data:**
  - Read only, through Metabase. Hassan has given standing permission to read production content for analysis.
  - Every export, label, run and score file stays in the session scratchpad
    `/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/real_lab/`,
    with the pid in each output filename. None of it is ever committed.
  - Committed docs carry aggregates only, never a production sentence.
- **Lab economy:**
  - At most 2 live settler runs per lab cycle.
  - Fable labels are produced once and reused by every later run. Truth never changes between baseline and re-run
    except by Hassan's verdicts.
  - The fixer never writes truth.
- **Keys:** load them with `load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")`. `METABASE_URL` and
  `METABASE_API_KEY` live there. For Anthropic, use `ANTHROPIC_API_KEY`, or the `ant auth` profile when it is unset
  (check with `ant auth status`).
- **Labeller:**
  - The model is `claude-fable-5-1`. Do not send a `thinking` parameter. Use `output_config.effort: "high"`, with
    structured output through `output_config.format`.
  - Enable the server-side fallback (`fallbacks: "default"` with beta `server-side-fallback-2026-07-01`) and record
    when a fallback model served. That label becomes a boundary item.
  - SDK 0.71.0 predates some of these parameters, so pass `output_config` and `fallbacks` through `extra_body`.
- **Prompts:**
  - Prompts stay case-agnostic: no single-domain clinical example in any system prompt.
  - British English.
- **Packs:** after any change under `guidelines/`, run
  `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py` and then
  `PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py -q`. Pack data changes use the project skill
  `.claude/skills/guideline-pack/SKILL.md`, take values from the source on disk, and get an independent hand read.
- **Regression:** `scripts/guidelines/preview_lab.py --check` stays green. The 51 invented cases are a regression
  suite only. Engine-derived `expect_missing` fields are updated when the engine's order changes. Their `truth` maps
  are never edited.
- **Review:** "reviewed" means an independent reviewer. If one cannot run, stop and ask Hassan before any merge.
  Apply stays off until Hassan rules on the gate.

## Review Focus

1. **Safety invariants.**
   - Could any path put a value into a `Calculation` that the client did not send?
   - Could any pack preview return a non-null `proposal`?
   - Could a boolean, a state, or a value the model inferred become `read`?
2. **Order of `needed`.** Eligibility first, then parents. A child behind an unknown prerequisite waits. A waiting
   child that could change the outcome always brings its parent into `needed`, so `needed` is never empty while the
   outcome is still open and bounded.
3. **Lab independence.**
   - Truth comes from Fable with every pack source in its prompt, and Fable never sees the settler's output.
   - Hassan's verdicts override truth.
   - No production text leaves the scratchpad.
   - The taps definition matches spec §12 exactly.
4. **Retirements are complete.** No dead imports, constants or tests remain for `_no_prior`, the per-input QUOTE
   claim, `quantity.many`, `_ORGANS`, `_QUALIFIER` or `_MANY_WORDS`.
5. **Links are ids, never text.** The verify gate rejects any link that does not name a real outcome, step value or
   input option.
6. **Checker mode never writes text by itself.** A disagreement only flags.

## File Map

| File | Change |
|---|---|
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py` | `parents`, `parents_first`, `Trace.waiting` (Task 1) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` | value states, `Drafted`, `calculate`, checker, lesions; retire guards (Tasks 1, 3, 4, 7, 8) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/quantity.py` | remove `many` and its helpers (Task 4) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py` | `RefLink`, `links`, `row_links` (Task 5); `Outcome.category` (Task 7) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py` | `_links` (Task 5); `_categories` (Task 7) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py` | `highlight` (Task 5) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/preview_cache.py` | `key(..., lesion="")` (Task 8) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` | `DraftValue`, `Calculation`, `Checker`, Preview fields, `CardState` (Tasks 1, 3, 5, 7, 8) |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` | `POST /calculate`, `lesion` field, span prewarm (Tasks 3, 8) |
| `backend/scripts/guidelines/real_lab.py` | new: the real-dictation lab (Task 2) |
| `backend/scripts/guidelines/preview_lab.py` | adapt to `Drafted` and to `draft_outcome` (Tasks 1, 3) |
| `backend/scripts/guidelines/preview_lab_cases.json` | engine-derived `expect_missing` only (Task 1) |
| `guidelines/{cad-rads-2,cac-drs,fleischner-pulmonary-nodule,bts-pulmonary-nodule,bosniak-renal-cyst,pi-rads-2-1}/entry.json` | reference links (Task 6) |
| `guidelines/<computed packs>/entry.json` | `category` on outcomes (Task 7) |
| `.claude/skills/guideline-pack/AUTHORING-RULES.md` | links and category rules (Tasks 6, 7) |
| `backend/tests/test_library_partial.py`, `test_library_pack_preview.py`, `test_library_quantity.py`, `test_library_verify.py`, `test_library_describe.py`, `test_copilot_routes.py`, new `test_library_real_lab.py`, new `test_library_calculate.py`, new `test_library_reference_links.py` | tests |
| `docs/superpowers/specs/2026-10-12-guideline-library-design.md` | §12 results (Task 10) |
| `docs/superpowers/handover/2026-10-12-copilot-evidence/real_lab.md`, `docs/superpowers/handover/2026-10-13-draft-card-handover.md` | new (Tasks 2, 9, 10) |

## Task list

1. Parent questions first in `needed`, eligibility first (spec item (a), goes in now)
2. Real-dictation lab harness and baseline on today's settler (b)
3. Value states in the preview, and the Calculate endpoint (c, part 1)
4. Retire and demote the guards (c, part 2)
5. Case-aware reference: links, verify gate, `highlight` (approved 2026-10-13)
6. Reference links on the most dictated packs (follow-up to Task 5)
7. Checker mode (d)
8. "Which lesion?" (e)
9. Re-run the real-dictation lab against the gate (f)
10. Spec §12 results and handover (g)

Out of scope: the card UI and the Task 14 mock-up.

---

### Task 1: Parent questions first in `needed`, eligibility first

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py` (`Trace`, `evaluate`, new `parents`, `parents_first`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (`_build`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`Preview.waiting`)
- Modify: `backend/scripts/guidelines/preview_lab.py` (`check` uses `t.needed` as given)
- Modify: `backend/scripts/guidelines/preview_lab_cases.json` (engine-derived `expect_missing` only)
- Test: `backend/tests/test_library_partial.py`, `backend/tests/test_library_pack_preview.py`

**Interfaces:**
```python
# engine.py
class Trace(BaseModel):
    ...
    waiting: list[str] = Field(default_factory=list)   # behind a prerequisite still unknown: not asked yet (§7.4)

def parents(entry: Entry) -> set[str]: ...
def parents_first(entry: Entry, needed: list[str], env: dict[str, V]) -> tuple[list[str], list[str]]: ...
```

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_library_partial.py`:

```python
def _bts():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("bts-pulmonary-nodule")


def test_a_child_behind_an_unknown_parent_waits_and_the_parent_is_asked(toy_entry):
    t = E.evaluate(toy_entry, {})
    assert t.needed == ["kind", "size"] and t.waiting == ["risk"]      # kind is risk's parent: asked, first


def test_a_known_parent_releases_its_child(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid"})
    assert t.needed == ["size", "risk"] and t.waiting == []


def test_bts_follow_up_inputs_wait_for_prior_study():
    e = _bts()
    t = E.evaluate(e, {})
    follow_up = {"resolved", "growth", "prior_volume_mm3", "current_volume_mm3", "interval_days"}
    assert not follow_up & set(t.needed) and follow_up <= set(t.waiting)
    assert t.needed[:3] == ["age", "proven_malignant", "prior_study"]   # eligibility, then the parent
    t = E.evaluate(e, {"age": 60, "proven_malignant": False, "prior_study": True})
    assert "resolved" in t.needed and "resolved" not in t.waiting


def test_parents_first_never_leaves_an_open_bounded_card_with_nothing_to_ask(toy_entry):
    for given in ({}, {"size": 7}, {"kind": "solid"}):
        t = E.evaluate(toy_entry, given)
        assert t.outcome is not None or t.needed
```

Then update `test_nothing_known` in the same file to the new contract:

```python
def test_nothing_known(toy_entry):
    t = E.evaluate(toy_entry, {})
    assert t.needed == ["kind", "size"] and t.waiting == ["risk"]   # margin never changes the outcome: never asked
    assert t.possible == ["ct12", "ct6", "none", "pet", "subsolid"]
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_partial.py -q`
Expected: FAIL. `Trace` has no `waiting`, and `needed` still lists `risk`.

- [ ] **Step 3: Implement** in `engine.py`. Add `waiting` to `Trace`, add the two functions below `reaching`, and
  apply them in `evaluate`:

```python
def parents(entry: Entry) -> set[str]:
    """The inputs some other input's prerequisite tests (spec §7.4)."""
    return {c.ref for i in entry.inputs for p in i.prerequisites for c in conds(p) if entry.input(c.ref) is not None}


def parents_first(entry: Entry, needed: list[str], env: dict[str, V]) -> tuple[list[str], list[str]]:
    """(needed, waiting), spec §7.4. An input behind a prerequisite that is still unknown is not asked yet: it waits,
    and its unknown parents are asked in its place, transitively. Order: eligibility inputs, then parents, then the
    rest, each in the pack's input order."""
    order = [i.id for i in entry.inputs]
    par = parents(entry)
    ask: list[str] = []
    waiting: list[str] = []
    todo, seen = list(needed), set()
    while todo:
        k = todo.pop(0)
        if k in seen:
            continue
        seen.add(k)
        i = entry.input(k)
        up = [c.ref for p in i.prerequisites for c in conds(p)
              if entry.input(c.ref) is not None and env.get(c.ref, UNKNOWN).state == "unknown"]
        if up:
            waiting.append(k)
            todo += [u for u in up if u not in seen]
        else:
            ask.append(k)
    rank = {k: (entry.input(k).role != "eligibility", k not in par, order.index(k)) for k in ask}
    return sorted(ask, key=rank.get), sorted((w for w in waiting if w not in ask), key=order.index)
```

```python
def evaluate(entry: Entry, given: dict[str, Any]) -> Trace:
    ...
    possible, bounded, needed, decides = _partial(entry, given, env)
    if bounded and len(possible) == 1:      # the unknown inputs cannot change the outcome: it is settled
        return Trace(outcome=possible[0], possible=possible, bounded=True, needed=[], inputs=inputs, steps=steps)
    needed, waiting = parents_first(entry, needed, env)
    decides = {k: decides.get(k) or possible for k in needed}
    return Trace(possible=possible, bounded=bounded, needed=needed, waiting=waiting, decides=decides, inputs=inputs,
                 steps=steps)
```

In `pack_preview._build`, the engine now owns the order. Replace the `elig`/`order`/`sorted(...)` lines with:

```python
    elig = [i.id for i in e.inputs if i.role == "eligibility"]
    needed = list(t.needed)                       # engine order (spec §7.4): eligibility, parents, the rest
```

Pass `waiting=list(t.waiting)` into `Preview(...)`. In `types.py`, add to `Preview`:

```python
    waiting: list[str] = Field(default_factory=list)   # library packs: inputs behind a prerequisite still unknown
```

In `preview_lab.check`, replace `missing = sorted(t.needed, key=order.index)` with `missing = list(t.needed)`, and
remove the now-unused `elig`/`order` lines there.

- [ ] **Step 4: Run the tests**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_partial.py tests/test_library_engine.py tests/test_library_pack_preview.py tests/test_library_eligibility_packs.py -q`
Expected: PASS. If an existing assertion on `needed` or `missing` lists a waiting child, update it to the parent-first
contract. Change only the expectation, never the engine.

- [ ] **Step 5: Bring the regression lab's engine-derived expectations up to date**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check`

For each "engine gives … the case says …" line whose difference is **only** in `expect_missing`, set that case's
`expect_missing` to the engine's list. Leave `truth`, `expect_outcome` and `expect_final` alone. Re-run until it
prints `51 cases checked, 0 disagree`. Report the mean `len(expect_missing)` per pack, before and after, in the
commit body. This is the engine-only friction change, and the review predicted BTS would fall from about 8 asks to
about 2.6.

- [ ] **Step 6: Full library suite, then commit**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: PASS (one known transient is allowed only if it also fails on HEAD).

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py \
  backend/scripts/guidelines/preview_lab.py backend/scripts/guidelines/preview_lab_cases.json \
  backend/tests/test_library_partial.py backend/tests/test_library_pack_preview.py
git commit -m "feat(library): parent questions first; a child behind an unknown prerequisite waits"
```

---

### Task 2: Real-dictation lab harness and baseline

**Files:**
- Create: `backend/scripts/guidelines/real_lab.py`
- Create: `backend/tests/test_library_real_lab.py`
- Create: `docs/superpowers/handover/2026-10-12-copilot-evidence/real_lab.md` (aggregates only)

**Pipeline.** Every file goes in `…/scratchpad/real_lab/`, with the pid in its name.
1. `export`: a read-only SQL query through Metabase, written to `export_<pid>.json`.
2. `group`: the stack grouper offline (`service.resolve_schema` with no database, then `service.group_update`). Then
   the matcher's naming call (`M._call(M._prompt(...))`), the library lookup (`Library.find`), tier 1 only, and the
   pack gate (`M._pgate` ≥ `M.PACK_GATE_MIN`). The cards are sampled per pack and written to `cards_<pid>.json`.
3. `hassan`: Hassan's own dictations (`hassan_cases.json`, which he writes) go through the same grouping and
   matching, appended with `source: "hassan"`.
4. `label`: Fable labels each card, giving `labels_<pid>.json`.
5. `run`: the current settler (`settle_pack` + `finish`) on each card, giving `settler_<pid>.json`, with timings.
6. `sheet`: boundary items for Hassan, giving `spotcheck_<pid>.csv`.
7. `score`: the metrics against the gate, giving `score_<pid>.json` and a markdown table on stdout.

**Interfaces (pure, tested):**
```python
def sample_cards(cards: list[dict], per_pack: int, total: int, seed: int = 13) -> list[dict]: ...
def label_request(e: Entry, card: dict, sources: list[Path]) -> dict: ...      # Anthropic create() kwargs
def parse_label(e: Entry, raw: dict) -> dict: ...                              # validated label, boundary flags
def drafts(s) -> dict[str, tuple[InputValue, str, str]]: ...                   # input -> (value, quote, tier)
def verdicts(e: Entry, s, label: dict) -> dict[str, str]: ...                  # input -> ok | wrong | missed | asked
def taps(e: Entry, s, label: dict, patient: dict, picked: bool = False) -> tuple[int, str | None]: ...
def spot_rows(e: Entry, card: dict, s, label: dict) -> list[dict]: ...
def metrics(rows: list[dict]) -> dict: ...
```

**Truth semantics (spec §12):**
- Each input of each card gets a label: `stated` (true or false), `value` (a display value the pack can take, or
  null), `quote`, `locator`, `assumed` (for an input that is not stated: the value a radiologist would most likely
  give from the whole report, used only to continue the tap count), `boundary` (true or false) and `note`.
- A drafted value is **wrong** when the label says not stated (it was inferred), or when its value differs from the
  stated value.
- Correctness never uses `assumed`.

**Taps (spec §12):**
- one per asked input the engine needs, filled from the stated value or else `assumed`;
- one per wrong drafted value, corrected to truth;
- one for the "Which lesion?" pick, if it was shown.

Taps are counted until the engine reaches an outcome or nothing more is asked. The Calculate tap is not counted.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_library_real_lab.py`, loading the script as
  `test_library_coverage_lab.py` does:

```python
import importlib.util
from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import Settlement
from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputValue

spec = importlib.util.spec_from_file_location(
    "real_lab", Path(__file__).resolve().parents[1] / "scripts" / "guidelines" / "real_lab.py")
RL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RL)


def _label(**inputs):
    return {"inputs": {k: {"stated": v is not None, "value": v, "quote": "", "locator": "", "assumed": a,
                           "boundary": False, "note": ""} for k, (v, a) in inputs.items()},
            "lesions": [], "category": None, "served_by": "claude-fable-5-1"}


def test_sampling_caps_each_pack_and_the_total():
    cards = [{"pack": p, "id": f"{p}{n}"} for p in ("a", "b") for n in range(50)]
    got = RL.sample_cards(cards, per_pack=30, total=40)
    assert len(got) == 40 and max(sum(c["pack"] == p for c in got) for p in ("a", "b")) <= 30
    assert got == RL.sample_cards(cards, per_pack=30, total=40)          # seeded: the same sample every run


def test_an_inferred_value_is_wrong_and_a_stated_one_is_ok(toy_entry):
    s = Settlement(values={"kind": (InputValue(value="solid"), "solid"), "risk": (InputValue(value="high"), "x")})
    v = RL.verdicts(toy_entry, s, _label(kind=("solid", None), size=("7", None), risk=(None, "low"),
                                         margin=(None, None)))
    assert v == {"kind": "ok", "risk": "wrong", "size": "asked", "margin": "asked"}


def test_taps_count_answers_and_corrections_never_the_calculate_tap(toy_entry):
    s = Settlement(values={"kind": (InputValue(value="subsolid"), "subsolid")})       # wrong: truth is solid
    n, outcome = RL.taps(toy_entry, s, _label(kind=("solid", None), size=("7", None), risk=(None, "high"),
                                              margin=(None, None)), patient={})
    assert (n, outcome) == (3, "ct6")          # correct kind, answer size, answer risk (assumed)


def test_the_label_request_carries_every_source_and_caches_the_pack(toy_entry, tmp_path):
    pdf = tmp_path / "s1.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    req = RL.label_request(toy_entry, {"finding": "f", "findings": "d", "clinical_history": "h"}, [pdf])
    content = req["messages"][0]["content"]
    assert req["model"] == "claude-fable-5-1" and "thinking" not in req
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert any(b.get("cache_control") for b in content[:-1]) and "cache_control" not in content[-1]
    assert req["extra_body"]["output_config"]["format"]["type"] == "json_schema"
    assert req["extra_body"]["fallbacks"] == "default"


def test_a_label_value_the_pack_cannot_take_becomes_a_boundary_item(toy_entry):
    raw = {"inputs": [{"input": "kind", "stated": True, "value": "cystic", "quote": "q", "locator": "S1 p2",
                       "assumed": None, "boundary": False, "note": ""}], "lesions": [], "category": None}
    got = RL.parse_label(toy_entry, raw)
    assert got["inputs"]["kind"]["boundary"] is True and "size" in got["inputs"]     # missing inputs: not stated


def test_spot_rows_list_flagged_and_disagreeing_items_only(toy_entry):
    s = Settlement(values={"kind": (InputValue(value="solid"), "solid"), "size": (InputValue(value=8.0), "8 mm")})
    lab = _label(kind=("solid", None), size=("7", None), risk=(None, "low"), margin=(None, None))
    lab["inputs"]["risk"]["boundary"] = True
    rows = RL.spot_rows(toy_entry, {"id": "c1", "pack": "toy-nodule"}, s, lab)
    assert sorted(r["input"] for r in rows) == ["risk", "size"]
    assert set(rows[0]) >= {"case", "pack", "input", "label_value", "label_quote", "locator", "settler_value",
                            "settler_tier", "settler_quote", "hassan_value", "hassan_note"}


def test_metrics_report_the_gate():
    rows = [{"pack": "p", "taps": 1, "verdicts": {"a": "ok"}, "tiers": {"a": "read"}},
            {"pack": "p", "taps": 3, "verdicts": {"a": "wrong", "b": "ok"}, "tiers": {"a": "prefilled", "b": "read"}}]
    m = RL.metrics(rows)
    assert m["wrong_read"] == 0 and m["median_taps"] == 2
    assert m["prefill_error"] == {"p.a": {"wrong": 1, "prefilled": 1, "rate": 1.0}}
```

The toy pack's key is `toy-nodule` (`tests/conftest.py`).

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_real_lab.py -q`
Expected: FAIL. `real_lab.py` does not exist.

- [ ] **Step 3: Write `backend/scripts/guidelines/real_lab.py`**

```python
"""Real-dictation lab (library spec §12, "Draft card slice": the Apply gate). Production findings, read only through
Metabase, grouped offline by the stack grouper, matched to library packs (matcher naming + pack gate); truth from a
Claude Fable 5.1 labeller holding every pack source; Hassan spot-checks the boundary items; the settler is scored.
Everything stays in <scratchpad>/real_lab/, pid in each name; nothing from production is ever committed.

  export  <dir>                       read-only SQL via Metabase           -> export_<pid>.json
  group   <export.json> <dir> [--per-pack 30 --total 100]                  -> cards_<pid>.json
  hassan  <hassan_cases.json> <cards.json> <dir>   Hassan's own dictations, appended -> cards_<pid>.json
  label   <cards.json> <dir>          Fable 5.1 truth (once; reused)       -> labels_<pid>.json
  run     <cards.json> <dir>          the settler as it stands             -> settler_<pid>.json
  sheet   <cards> <labels> <settler> <dir>                                 -> spotcheck_<pid>.csv
  score   <cards> <labels> <settler> [--verdicts spotcheck.csv]            -> score_<pid>.json + table
Gate: 0 wrong values shown as read; median taps to Calculate <= 2; pre-fill error rate per input reported.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/real_lab.py <cmd> ..."""
import asyncio
import base64
import csv
import importlib.util
import json
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")    # model keys only, never the app database
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot import matcher as M  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import (  # noqa: E402
    _answer, _show, display_options, finish, settle_pack)
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry, InputValue  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
LABEL_MODEL = "claude-fable-5-1"
MAX_FILL = 10
NOT_STATED = "Not stated"
SQL = """select id::text as id,
  coalesce(input_data->'variables'->>'SCAN_TYPE', input_data->>'extracted_scan_type', '') as scan_type,
  coalesce(input_data->'variables'->>'CLINICAL_HISTORY', '') as clinical_history,
  input_data->'variables'->>'FINDINGS' as findings
from reports
where created_at > now() - interval '365 days' and input_data->'variables'->>'FINDINGS' is not null
order by created_at desc limit 2000"""

LABEL_SYS = """You label radiology dictations against one published guideline, as the ground truth for a test.
You hold the guideline's own source documents and the library's encoding of it (PACK). For the FINDING given, and
for every input listed in PACK, decide what the dictation itself states, reading the sources for what each input
means. An input is stated only when the FINDING (lesion inputs) or the CLINICAL HISTORY or DICTATION (patient inputs)
gives it in words; a value that is usual, likely or merely not contradicted is not stated.
For each input return: stated; value (exactly one of the input's listed values when stated, else null); quote (the
shortest verbatim span that states it, else ""); locator (where in the sources the input is defined, as "S<n> p<page>
<section or table>"); assumed (when not stated: the value a radiologist would most likely give from the whole report
and the images it describes, else null); boundary (true when a careful reader could label it differently); note.
Also return lesions (when the FINDING describes more than one lesion of any kind, the shortest verbatim span for each;
else []) and category (when the FINDING states the system's category by name: {label, quote}; else null)."""

LABEL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["inputs", "lesions", "category"],
    "properties": {
        "inputs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["input", "stated", "value", "quote", "locator", "assumed", "boundary", "note"],
            "properties": {"input": {"type": "string"}, "stated": {"type": "boolean"},
                           "value": {"type": ["string", "null"]}, "quote": {"type": "string"},
                           "locator": {"type": "string"}, "assumed": {"type": ["string", "null"]},
                           "boundary": {"type": "boolean"}, "note": {"type": "string"}}}},
        "lesions": {"type": "array", "items": {"type": "string"}},
        "category": {"type": ["object", "null"], "additionalProperties": False, "required": ["label", "quote"],
                     "properties": {"label": {"type": "string"}, "quote": {"type": "string"}}}}}


def _coverage_lab():
    spec = importlib.util.spec_from_file_location("coverage_lab", Path(__file__).with_name("coverage_lab.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _lib() -> LB.Library:
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _pid(d: Path, stem: str, ext: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{stem}_{os.getpid()}.{ext}"


# ── export ──────────────────────────────────────────────────────────────────────────────────────────────────────

def export(out_dir: Path) -> Path:
    """Read-only SQL through Metabase /api/dataset (database 2). If Cloudflare refuses the script (1010), run SQL in
    the Chrome session's Metabase and save the JSON response as export_<pid>.json yourself."""
    import httpx
    r = httpx.post(os.environ["METABASE_URL"].rstrip("/") + "/api/dataset",
                   headers={"x-api-key": os.environ["METABASE_API_KEY"], "User-Agent": "curl/8",
                            "Content-Type": "application/json"},
                   json={"database": 2, "type": "native", "native": {"query": SQL}}, timeout=180)
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise SystemExit(body["error"])
    p = _pid(out_dir, "export", "json")
    p.write_text(json.dumps(body))
    return p


# ── group ───────────────────────────────────────────────────────────────────────────────────────────────────────

async def _cards_for(case: dict, sem: asyncio.Semaphore) -> list[dict]:
    from rapid_reports_ai.hybrid_stack import service as S
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
    async with sem:
        schema = await S.resolve_schema(case["scan_type"], case["clinical_history"], None, None)
        g = await S.group_update(case["scan_type"], case["findings"], schema.regions, [])
        fs = _coverage_lab().findings([u.model_dump() for u in g.units])
        if not fs:
            return []
        raw = await M._call(M._prompt(case["scan_type"], case["clinical_history"], [M.Finding(**f) for f in fs], ""))
        lib, out = L.get(), []
        for rf in raw.findings:
            f = next((x for x in fs if x["id"] == M._rid(rf.id)), None)
            for s in rf.systems if f else []:
                pack = lib.find(s.name, s.version) or lib.find(s.name)
                if pack is None or pack.tier != 1:
                    continue
                score = await M._pgate(f["text"], pack, case["clinical_history"])
                if score is not None and score >= M.PACK_GATE_MIN:
                    out.append({"id": f"{case['id']}:{f['id']}:{pack.key}", "case": case["id"], "pack": pack.key,
                                "source": case.get("source", "prod"), "scan_type": case["scan_type"],
                                "clinical_history": case["clinical_history"], "findings": case["findings"],
                                "finding": f["text"]})
        return out


def sample_cards(cards: list[dict], per_pack: int, total: int, seed: int = 13) -> list[dict]:
    """At most per_pack cards of each pack, at most total overall, spread round-robin across packs; seeded."""
    rng = random.Random(seed)
    by: dict[str, list[dict]] = defaultdict(list)
    for c in sorted(cards, key=lambda c: c["id"]):
        by[c["pack"]].append(c)
    for v in by.values():
        rng.shuffle(v)
    pools = {k: v[:per_pack] for k, v in sorted(by.items())}
    out: list[dict] = []
    while len(out) < total and any(pools.values()):
        for k in sorted(pools):
            if pools[k] and len(out) < total:
                out.append(pools[k].pop(0))
    return out


def cases_from_export(body: dict, source: str = "prod") -> list[dict]:
    cols = [c["name"] for c in body["data"]["cols"]]
    seen, out = set(), []
    for row in body["data"]["rows"]:
        r = dict(zip(cols, row))
        text = (r.get("findings") or "").strip()
        if text and text not in seen:                    # unique dictations only
            seen.add(text)
            out.append({"id": r["id"], "scan_type": r.get("scan_type") or "", "source": source,
                        "clinical_history": r.get("clinical_history") or "", "findings": text})
    return out


async def group(src: Path, out_dir: Path, per_pack: int = 30, total: int = 100) -> Path:
    cases = cases_from_export(json.loads(src.read_text()))
    sem = asyncio.Semaphore(4)
    cards = [c for cs in await asyncio.gather(*(_cards_for(c, sem) for c in cases)) for c in cs]
    p = _pid(out_dir, "cards", "json")
    p.write_text(json.dumps(sample_cards(cards, per_pack, total), indent=1))
    print(f"{len(cases)} dictations, {len(cards)} pack cards -> {p} ({Counter(c['pack'] for c in cards)})")
    return p


# ── label ───────────────────────────────────────────────────────────────────────────────────────────────────────

def pack_text(e: Entry) -> str:
    rows = [f"- {i.id} [{i.scope}{', eligibility' if i.role == 'eligibility' else ''}]: {i.label}; "
            f"values: {' | '.join(display_options(e, i)) or 'a number in ' + (i.unit or 'its unit')}; "
            f"definition: {i.how_stated or i.label}" for i in e.inputs]
    return f"PACK: {e.display} ({e.issuer} {e.edition})\nINPUTS:\n" + "\n".join(rows)


def label_request(e: Entry, card: dict, sources: list[Path]) -> dict:
    docs = [{"type": "document", "title": p.name,
             "source": {"type": "base64", "media_type": "application/pdf",
                        "data": base64.standard_b64encode(p.read_bytes()).decode()}} for p in sources]
    pack = {"type": "text", "text": pack_text(e), "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    case = {"type": "text", "text": f"CLINICAL HISTORY:\n{card['clinical_history'] or 'none given'}\n\n"
                                    f"DICTATION:\n{card['findings']}\n\nFINDING:\n{card['finding']}"}
    return {"model": LABEL_MODEL, "max_tokens": 16000, "system": LABEL_SYS,
            "messages": [{"role": "user", "content": [*docs, pack, case]}],
            "extra_body": {"output_config": {"effort": "high",
                                             "format": {"type": "json_schema", "schema": LABEL_SCHEMA}},
                           "fallbacks": "default"}}


def _sources(e: Entry) -> list[Path]:
    """Every source file the pack's manifest lists (primary, amendment and explanatory), from guidelines/<id>/sources."""
    m = json.loads((ROOT / "guidelines" / e.id / "manifest.json").read_text())
    return [ROOT / "guidelines" / e.id / s["file"] for s in m["sources"] if s.get("file")]


def parse_label(e: Entry, raw: dict) -> dict:
    """The label keyed by input; every pack input present (an unlabelled one: not stated, boundary); a value the
    pack cannot take becomes a boundary item with no value."""
    got = {x["input"]: x for x in raw.get("inputs", []) if e.input(x["input"]) is not None}
    out = {}
    for i in e.inputs:
        x = dict(got.get(i.id) or {"stated": False, "value": None, "quote": "", "locator": "", "assumed": None,
                                   "boundary": True, "note": "not labelled"})
        for k in ("value", "assumed"):
            if x.get(k) is not None and _answer(e, i, str(x[k])) is None:
                x["boundary"], x["note"], x[k] = True, f"{k} {x[k]!r} is not a value of the pack", None
        if x["value"] is None:
            x["stated"] = False
        out[i.id] = x
    return {"inputs": out, "lesions": raw.get("lesions", []), "category": raw.get("category"),
            "served_by": raw.get("served_by", LABEL_MODEL)}


async def label(cards_path: Path, out_dir: Path) -> Path:
    import anthropic
    client, lib = anthropic.AsyncAnthropic(), _lib()
    sem, out = asyncio.Semaphore(3), {}

    async def one(c: dict) -> None:
        e = lib.lookup(c["pack"])
        req = label_request(e, c, _sources(e))
        async with sem:
            r = await client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], **req)
        if r.stop_reason == "refusal":
            out[c["id"]] = {"error": "refusal"}
            return
        text = next(b.text for b in r.content if b.type == "text")
        out[c["id"]] = parse_label(e, {**json.loads(text), "served_by": r.model})
    await asyncio.gather(*(one(c) for c in json.loads(cards_path.read_text())))
    p = _pid(out_dir, "labels", "json")
    p.write_text(json.dumps(out, indent=1))
    return p


# ── run / score ─────────────────────────────────────────────────────────────────────────────────────────────────

def drafts(s) -> dict[str, tuple[InputValue, str, str]]:
    """input -> (value, quote, tier). Today's settler has no tiers: every settled value is shown as read."""
    out = {}
    for k, v in s.values.items():
        if isinstance(v, tuple):
            out[k] = (v[0], v[1], "read")
        else:                                   # Task 3's Drafted
            out[k] = (v.value, v.quote, v.tier)
    return out


def _same(e: Entry, k: str, v: InputValue, label_value: str | None) -> bool:
    if label_value is None:
        return False
    t = _answer(e, e.input(k), label_value)
    return t is not None and _show(e, e.input(k), t) == _show(e, e.input(k), v)


def verdicts(e: Entry, s, label: dict) -> dict[str, str]:
    """ok: drafted and true; wrong: drafted but not stated, or not what was stated; asked: not drafted."""
    d = drafts(s)
    out = {}
    for i in e.inputs:
        lab = label["inputs"][i.id]
        if i.id not in d:
            out[i.id] = "asked"
        else:
            out[i.id] = "ok" if lab["stated"] and _same(e, i.id, d[i.id][0], lab["value"]) else "wrong"
    return out


def _truth(label: dict) -> dict[str, str | None]:
    return {k: (x["value"] if x["stated"] else x["assumed"]) for k, x in label["inputs"].items()}


def taps(e: Entry, s, label: dict, patient: dict, picked: bool = False) -> tuple[int, str | None]:
    truth, d = _truth(label), drafts(s)
    answered: dict[str, str] = {}
    n = 1 if picked else 0
    for k, (v, _, _) in d.items():                          # correct every wrong drafted value
        lab = label["inputs"][k]
        if not (lab["stated"] and _same(e, k, v, lab["value"])):
            answered[k] = truth[k] if truth[k] is not None else NOT_STATED
            n += 1
    p = finish(e, s, answered, patient)
    for _ in range(MAX_FILL):
        new = {k: truth[k] for k in p.missing if k not in answered and truth.get(k) is not None}
        if not new:
            break
        answered.update(new)
        n += len(new)
        p = finish(e, s, answered, patient)
    t = p.trace or {}
    return n, t.get("outcome")


def spot_rows(e: Entry, card: dict, s, label: dict) -> list[dict]:
    """Boundary items for Hassan: the labeller's own flags, every disagreement with the settler, fallback labels."""
    d, v = drafts(s), verdicts(e, s, label)
    fallback = label.get("served_by") != LABEL_MODEL
    rows = []
    for i in e.inputs:
        lab = label["inputs"][i.id]
        if not (lab["boundary"] or v[i.id] == "wrong" or fallback):
            continue
        val, q, tier = d.get(i.id, (None, "", "asked"))
        rows.append({"case": card["id"], "pack": card["pack"], "input": i.id, "label_value": lab["value"] or "",
                     "label_quote": lab["quote"], "locator": lab["locator"], "label_note": lab["note"],
                     "settler_value": _show(e, i, val) if val is not None else "", "settler_tier": tier,
                     "settler_quote": q, "hassan_value": "", "hassan_note": ""})
    return rows


def metrics(rows: list[dict]) -> dict:
    """rows: one per card with pack, taps, verdicts (input -> ok|wrong|asked) and tiers (input -> read|prefilled)."""
    wrong_read = sum(1 for r in rows for k, v in r["verdicts"].items() if v == "wrong" and r["tiers"].get(k) == "read")
    pf: dict[str, dict] = defaultdict(lambda: {"wrong": 0, "prefilled": 0})
    for r in rows:
        for k, t in r["tiers"].items():
            if t == "prefilled":
                key = f"{r['pack']}.{k}"
                pf[key]["prefilled"] += 1
                pf[key]["wrong"] += r["verdicts"][k] == "wrong"
    return {"cards": len(rows), "wrong_read": wrong_read,
            "median_taps": statistics.median(r["taps"] for r in rows) if rows else None,
            "taps_le_2": sum(r["taps"] <= 2 for r in rows),
            "prefill_error": {k: {**v, "rate": v["wrong"] / v["prefilled"]} for k, v in sorted(pf.items())}}
```

Then add `run`, `sheet`, `score` and `main`, all using the functions above:
- `run` times `settle_pack` per card on a cold cache, as scenario (a), and records `drafts`, `finish(...).missing`,
  `draft_outcome` (`proposal` on today's code) and `ms`.
- `score` applies Hassan's `hassan_value` overrides from the filled spot-check CSV to the labels before
  `verdicts`/`taps`. It reports the gate and the "also reported" list in spec §12. Checker and lesion rows are `n/a`
  until Tasks 7 and 8.
- `main` dispatches on `sys.argv[1]`.

`run` re-settles from the stored dictation, so after Task 3 it measures the new settler with no other change.

- [ ] **Step 4: Run the tests**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_real_lab.py -q`
Expected: PASS.

- [ ] **Step 5: Commit the harness** (no data)

```bash
git add backend/scripts/guidelines/real_lab.py backend/tests/test_library_real_lab.py
git commit -m "lab(library): real-dictation lab harness (Metabase export, offline grouping, Fable labels, spot sheet, score)"
```

- [ ] **Step 6: Check source sizes before labelling.** For each pack in the sample, list `_sources(e)`. The request
  limit is 32 MB and 600 pages. A pack over the limit sends its `sources/*.txt` siblings as text `document` blocks
  instead; record which. Estimate the cost: (input tokens per pack × 1.25 cache write) + (cards × cached reads) +
  (cards × about 5k output), at $10 in and $50 out per MTok. Expect about $30–60. Stop and ask Hassan if the estimate
  is above $100.

- [ ] **Step 7: Export, group and ask Hassan for his dictations**
  - Run `export`, or the Chrome fallback, then `group … --per-pack 30 --total 100`.
  - Ask Hassan, through the coordinator, for about 20 dictations in his own style, written without looking at the
    guards. They go in `real_lab/hassan_cases.json` as `[{"id", "scan_type", "clinical_history", "findings"}]`.
  - Run `hassan`.
  - Report the per-pack counts.

- [ ] **Step 8: Label once.** Run `label`. Rows with `error` or a fallback `served_by` go to the spot-check sheet.

- [ ] **Step 9: Baseline on today's settler.** Run `run` once, then `sheet`. Hand `spotcheck_<pid>.csv` to Hassan
  through the coordinator. He fills `hassan_value` and `hassan_note` on boundary items only. Then run `score` with
  `--verdicts`.

- [ ] **Step 10: Write the evidence and commit**

Create `docs/superpowers/handover/2026-10-12-copilot-evidence/real_lab.md`, aggregates only:
- the sample: counts per pack and source;
- truth: labels, boundary items, Hassan's overrides, fallback count;
- baseline: wrong read values (on today's settler every settled value counts as read), median taps, cards with 2
  taps or fewer, per-input settle error, and how often the category was dictated per pack;
- latency p50 and p95;
- the run pid.

```bash
git add docs/superpowers/handover/2026-10-12-copilot-evidence/real_lab.md
git commit -m "lab(library): real-dictation lab baseline on today's settler"
```

---

### Task 3: Value states in the preview, and the Calculate endpoint

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py`
- Modify: `backend/scripts/guidelines/preview_lab.py` (adapt to `Drafted` and to `draft_outcome`)
- Create: `backend/tests/test_library_calculate.py`
- Modify: `backend/tests/test_library_pack_preview.py`, `backend/tests/test_copilot_routes.py`, `backend/tests/test_library_real_lab.py`

**Interfaces:**
```python
# types.py
ValueState = Literal["read", "prefilled", "asked", "answered", "edited", "not_applicable"]

class DraftValue(BaseModel):
    input: str
    label: str
    role: str = "clinical"
    scope: str = "lesion"
    fact: str = ""
    state: ValueState
    value: str = ""                    # display form; "" when asked
    quote: str = ""
    why: list[str] = Field(default_factory=list)      # pre-filled: why it is not read (spec §7.5)
    needed: bool = False               # in `needed`: can still change the outcome
    waiting: bool = False              # behind a prerequisite still unknown
    options: list[str] = Field(default_factory=list)  # display_options + "Not stated" (spec §7.6)

class Calculation(BaseModel):
    outcome: str | None = None
    result: Proposal | None = None     # what Apply writes (spec §7.7); None while incomplete or excluded
    exclusion: Proposal | None = None
    possible: list[str] = Field(default_factory=list)
    needed: list[str] = Field(default_factory=list)
    values: list[DraftValue] = Field(default_factory=list)
    trace: dict[str, Any] | None = None
    pack: str = ""                     # pack_id@version
    bundle: str = ""

# Preview gains:
    draft: list[DraftValue] = Field(default_factory=list)
    draft_outcome: Proposal | None = None    # "on these values"; never Apply-able (spec §7.7)
# and `proposal` stays None for library packs.

# pack_preview.py
@dataclass
class Drafted:
    value: InputValue
    quote: str
    tier: Literal["read", "prefilled"]
    why: list[str] = field(default_factory=list)

NOT_STATED = "Not stated"
def calculate(e: Entry, s: Settlement, values: dict[str, str], patient: dict[str, str] | None,
              sources: list[dict], bundle: str) -> Calculation: ...

# routes.py
class CalculateRequest(OpenRequest):
    values: dict[str, str] = Field(default_factory=dict)   # every value the card shows, display form

@router.post("/calculate", response_model=CalculateResult)
```

**The read rule** (spec §7.5), in `settle_pack` after the Jev batch. A proposal is `read` only if every check below
holds. Otherwise it is `prefilled`, with the reason for each failed check in `why`.

| Check | Reason when it fails |
|---|---|
| The input is a number, or an enum (`WHY_KIND` = "yes/no and absent values are never read") | `WHY_KIND` |
| An enum's option words appear in the quote as whole tokens | `WHY_NOT_OPTION_WORD` = "the quote does not use the option's own words" |
| No `_MODIFIER` before the quote | `WHY_MODIFIED` = "a negation or hedge before the quote" |
| A lesion number passes `Q.alone` | `WHY_OTHER_NUMBER` = "another number in this finding" |
| The scope's batched Jev claim reaches its bar | `WHY_UNCONFIRMED` = "the finding does not clearly state it" |
| An attenuation passes the phase claim | `WHY_PHASE` = "attenuation not stated as unenhanced" |
| A lesion value has `ONE_LESION` at or above its bar | `WHY_SEVERAL` = "the finding may describe more than one lesion" |
| The Jev call succeeded | `WHY_NO_CHECK` = "the check did not run" |

A proposal is dropped (the input is asked) only when its quote is not verbatim in scope, or a number cannot be read
(`Q.settle` returns None) or is out of range. In this task the existing retire-list guards still run. Task 4 removes
them.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_library_calculate.py`, using the `jev` fixture and
  `_model` helper from `test_library_pack_preview.py` (import them):

```python
import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from tests.test_library_pack_preview import FINDINGS, _model, jev  # noqa: F401  (fixture)

KIND = {"input": "kind", "value": "solid", "quote": "solid"}
SIZE = {"input": "size", "value": 7, "quote": "7 mm"}
RISK = {"input": "risk", "value": "high", "quote": "smoker"}


async def _s(toy_entry, monkeypatch, *items, history="Smoker."):
    _model(monkeypatch, *items)
    return await PP.settle_pack(toy_entry, FINDINGS, history, finding=FINDINGS)


async def test_a_code_read_number_and_an_option_word_are_read_others_prefilled(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    assert s.values["size"].tier == "read" and s.values["kind"].tier == "read"
    assert s.values["risk"].tier == "prefilled" and PP.WHY_NOT_OPTION_WORD in s.values["risk"].why


async def test_a_jev_failure_reads_nothing_but_keeps_every_proposal(toy_entry, monkeypatch, jev):
    jev["fail"] = True
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    assert {k: d.tier for k, d in s.values.items()} == {"kind": "prefilled", "size": "prefilled", "risk": "prefilled"}
    assert all(PP.WHY_NO_CHECK in d.why for d in s.values.values())


async def test_a_quote_not_in_scope_is_still_asked(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, {"input": "kind", "value": "solid", "quote": "solid mass elsewhere"})
    assert "kind" not in s.values


async def test_the_preview_shows_a_draft_and_never_an_apply_able_proposal(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    p = PP.finish(toy_entry, s, {}, None, [])
    assert p.proposal is None and p.draft_outcome.recommendation == "CT at 6 months"
    by = {d.input: d for d in p.draft}
    assert by["size"].state == "read" and by["risk"].state == "prefilled" and by["margin"].state == "asked"
    assert by["margin"].needed is False and PP.NOT_STATED in by["kind"].options


async def test_calculate_uses_only_the_values_sent(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    c = PP.calculate(toy_entry, s, {"kind": "solid", "size": "7 mm"}, None, [], "b1")   # risk not sent
    assert c.outcome is None and c.result is None and c.needed == ["risk"]
    c = PP.calculate(toy_entry, s, {"kind": "solid", "size": "7 mm", "risk": "low"}, None, [], "b1")
    assert c.outcome == "ct12" and c.result.recommendation and c.pack.startswith(toy_entry.key)
    states = {v.input: v.state for v in c.values}
    assert states == {"kind": "read", "size": "read", "risk": "edited", "margin": "asked"}


async def test_not_stated_clears_a_drafted_value(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    c = PP.calculate(toy_entry, s, {"kind": "solid", "size": PP.NOT_STATED, "risk": "high"}, None, [], "b1")
    assert c.outcome is None and "size" in c.needed


def test_a_does_not_apply_calculation_is_an_exclusion_never_a_result():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("fleischner-pulmonary-nodule")
    c = PP.calculate(e, PP.Settlement(), {"age": "30"}, None, [], "b1")
    assert c.result is None and c.exclusion is not None
```

Before writing the last test, check the Fleischner age band's exact label and cut-off in its entry. Use a value
below the cut-off, typed as `_answer` reads it.

In `backend/tests/test_copilot_routes.py`, add a route test. Monkeypatch `CR.settle_pack` to return a fixed
`Settlement`, post to `/api/canvas/stack/guidelines/calculate` with a toy pack card and `values`, and assert that:
- the response's `calculation.result` is present only when every needed value was sent;
- the route never calls the model when the settlement is cached.

Follow `test_open_route_returns_entry_and_preview` for the auth fixture, and patch `routes._pack` to return the toy
pack.

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_calculate.py -q`
Expected: FAIL. `Drafted`, `calculate` and `draft` do not exist.

- [ ] **Step 3: Implement.**

In `pack_preview.py`:

1. Add `Drafted`, `NOT_STATED` and the `WHY_*` constants. Change `Settlement.values` to `dict[str, Drafted]`.
2. Make `_answer` map `NOT_STATED` to `InputValue(state="unknown")`, before the other branches:

```python
    if s == NOT_STATED:
        return InputValue(state="unknown")
```

3. Make `_confirm` return per-input reasons instead of a confirmed set. Keep the batched scope call, the phase claim
   and `ONE_LESION`:

```python
async def _confirm(e: Entry, pending: dict[str, tuple[InputValue, str]], finding: str, findings: str,
                   history: str) -> tuple[dict[str, list[str]], bool]:
    """(input -> the reasons it is not read (empty: confirmed), whether a Jev call failed). One batched call per
    scope: "<LEAD> <label>: <value>"; attenuations add the phase claim; the lesion batch adds ONE_LESION."""
```

   Each `batch(scope)` returns `{k: reasons}`:
   - a score below its bar adds `WHY_UNCONFIRMED`. Until Task 4 deletes it, the per-quote claim still runs, and a
     score below `QUOTE_MIN` there also adds `WHY_UNCONFIRMED`;
   - a phased input adds `WHY_PHASE`;
   - `ONE_LESION` below its bar adds `WHY_SEVERAL` to every lesion input;
   - a failure adds `WHY_NO_CHECK` to every input of that scope.

4. Add `_read_reasons(i, v, quote, texts)`. It returns `WHY_KIND`, `WHY_NOT_OPTION_WORD`, `WHY_MODIFIED` and
   `WHY_OTHER_NUMBER` as they apply:

```python
def _words(s: str) -> list[str]:
    return R.norm(s.replace("_", " ")).split()


def _has_option_words(option: str, quote: str) -> bool:
    w, q = _words(option), _words(quote)
    return bool(w) and any(q[n:n + len(w)] == w for n in range(len(q) - len(w) + 1))


def _read_reasons(e: Entry, i: InputDef, v: InputValue, quote: str, texts: list[str]) -> list[str]:
    if v.state != "present" or i.type == "boolean":
        return [WHY_KIND]
    out = []
    if i.type == "enum" and not _has_option_words(str(v.value), quote):
        out.append(WHY_NOT_OPTION_WORD)
    if i.type != "number" and _modified(quote, texts):
        out.append(WHY_MODIFIED)
    if i.type == "number" and i.scope == "lesion" and not Q.alone(texts[0], quote, float(v.value), i.unit, i.dims):
        out.append(WHY_OTHER_NUMBER)
    return out
```

5. In `_settle`, stop dropping values for `_modified` and for the `Q.alone` refusal inside `_value`. Remove that
   refusal from `_value`; `Q.settle`'s refusals stay. Keep the `several`/`Q.many` drop until Task 4. Return
   `{k: (value, Settled)}` as now.
6. In `settle_pack`, build `values[k] = Drafted(v, quote, "read" if not why else "prefilled", why)`, where
   `why = _read_reasons(...) + confirm_reasons[k]`. A Jev failure no longer drops values. It marks them through
   `WHY_NO_CHECK`.
7. `finish`:
   - `given` is the drafted values plus the answers, with answers winning.
   - It builds the `draft` with `_draft(e, t, s, given_answers)`. That gives a state per input:
     - answered: `answered`;
     - drafted and not overridden: the tier;
     - not applicable in the trace: `not_applicable`;
     - otherwise: `asked`.
   - It sets `draft_outcome` from `_outcome_text`.
   - It sets `proposal=None`.
   - `_build` keeps `missing`, `asks`, `possible`, `state`, `exclusion` and `trace`.
8. `calculate`:

```python
def calculate(e: Entry, s: Settlement, values: dict[str, str], patient: dict[str, str] | None,
              sources: list[dict], bundle: str) -> Calculation:
    """Spec §7.7: the engine over exactly the values the card shows (an input not sent is unknown, never taken from
    the settlement); no model, no Jev. A value equal to its draft keeps the draft's state; any other is edited
    (answered when nothing was drafted)."""
    given = _given(e, values, patient)               # NOT_STATED -> unknown
    try:
        t = engine.evaluate(e, given)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.calculate] %s cannot be evaluated: %s", e.key, ex)
        return Calculation(pack=f"{e.key}@{e.version}", bundle=bundle)
    used = []
    for i in e.inputs:
        d, g = s.values.get(i.id), given.get(i.id)
        if t.inputs[i.id].state == "not_applicable":
            st = "not_applicable"
        elif g is None or g.state == "unknown":
            st = "asked"
        elif d is not None and _show(e, i, d.value) == _show(e, i, g):
            st = d.tier
        else:
            st = "edited" if d is not None else "answered"
        used.append(_draft_value(e, i, t, st, g, d))
    text = _outcome_text(e, t, sources) if t.outcome is not None else None
    excluded = t.outcome == DOES_NOT_APPLY
    return Calculation(outcome=t.outcome, result=None if excluded else text, exclusion=text if excluded else None,
                       possible=[engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification))
                                 for o in t.possible],
                       needed=list(t.needed), values=used,
                       trace=t.model_dump(mode="json") if t.outcome is not None else None,
                       pack=f"{e.key}@{e.version}", bundle=bundle)
```

   `_draft_value(e, i, t, state, g, d)` builds one `DraftValue`: label, role, scope, fact, `value=_show(...)` when
   `g` is present, the quote from `d`, `why` from `d` when its state is `prefilled`, `needed=i.id in t.needed`,
   `waiting=i.id in t.waiting`, and `options=[*display_options(e, i), NOT_STATED]`. `finish` uses the same helper.

In `routes.py`:

```python
class CalculateRequest(OpenRequest):
    values: dict[str, str] = Field(default_factory=dict)   # every value the card shows, in display form

    @field_validator("values")
    @classmethod
    def _cap_values(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 40 or any(len(k) > 60 or len(x) > 200 for k, x in v.items()):
            raise ValueError("values: at most 40 inputs, ids up to 60 and values up to 200 characters")
        return v


class CalculateResult(BaseModel):
    calculation: Calculation | None = None
    ms: int = 0
    error: str | None = None      # "not a pack"


@router.post("/calculate", response_model=CalculateResult)
async def copilot_calculate(req: CalculateRequest, user: User = Depends(get_current_user)):
    """Spec §7.7: Calculate over the values the card shows. The cached settlement only labels each value's state;
    the engine never reads it."""
    _require()
    t0 = time.perf_counter()
    pack = _pack(req.card.card().key)
    if pack is None:
        return CalculateResult(ms=_ms(t0), error="not a pack")
    e, _ = pack
    lib = L.get()
    settled = await _settlement(e, req, opened=False)
    return CalculateResult(calculation=calculate(e, settled, req.values, req.patient, lib.sources(e.key),
                                                 lib.version()), ms=_ms(t0))
```

   Extract `_settlement(e, req, opened)` from `_pack_result`: the `PC.start` and `wait_for` block, returning
   `Settlement(failed=True)` on any error. `_pack_result` and `copilot_calculate` both use it.

In `preview_lab.py`:
- `Settlement.values[k]` is now a `Drafted`. Read `.value` and `.quote`.
- "Proposed before any answer" reads `p.draft_outcome`.
- Wrong values are counted per tier and reported as `read` / `prefilled`.

- [ ] **Step 4: Run the tests and update the old preview tests to the new contract**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_calculate.py tests/test_library_pack_preview.py tests/test_copilot_routes.py -q`

Tests that asserted `out.proposal` for packs now assert `out.draft_outcome`. In `tests/test_library_real_lab.py`,
build the `Settlement` fixtures with `PP.Drafted(value, quote, "read")` in place of tuples. `real_lab.drafts` reads
both forms. Tests that asserted a value was asked
because of `_modified`, `Q.alone`, a Jev score below its bar or a Jev failure now assert it is `prefilled` with the
matching `WHY_*` reason. Change the expectation; keep the scenario.

Expected: PASS.

- [ ] **Step 5: Regression lab check, then commit**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: `0 disagree`; PASS.

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py backend/scripts/guidelines/preview_lab.py \
  backend/tests/test_library_calculate.py backend/tests/test_library_pack_preview.py backend/tests/test_copilot_routes.py \
  backend/tests/test_library_real_lab.py
git commit -m "feat(library): read / pre-filled / asked draft values and POST /calculate over the confirmed values"
```

---

### Task 4: Retire and demote the guards

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/quantity.py`
- Modify: `backend/tests/test_library_pack_preview.py`, `backend/tests/test_library_quantity.py`

**Retired.** Delete the code and its tests:
- In `pack_preview.py`: `QUOTE_MIN`, `_QUOTE_OF`, `_quote_state`, `_quote_claim`, the `quote()` coroutine and
  `choices`/`quoted` in `_confirm`, and `NO_PRIOR_INPUT`, `NO_PRIOR_MIN`, `PRIOR_MENTIONED_MAX`, `PRIOR_MENTIONED`,
  `HISTORY_MENTIONED`, `_FOLLOW_UP`, `_ELSEWHERE`, `_PRIOR_WORD`, `_SENTENCE`, `_no_prior_claim` and `_no_prior`.
  In `settle_pack`, delete the `asyncio.gather` with `_no_prior` and every `NO_PRIOR_INPUT` branch. In `_settle`,
  delete `several = … Q.many(...)` and its `continue`. Delete `_nouns` if nothing else uses it (check with grep).
- In `quantity.py`: `_MANY_WORDS`, `_plural`, `_QUALIFIER`, `_ORGANS`, `many`, and `_CLAUSE` if only `many` used it
  (check with grep).

**Demoted** (already done in Task 3): `Q.alone` becomes `WHY_OTHER_NUMBER`, `ONE_LESION` becomes `WHY_SEVERAL` (and
the trigger in Task 8), `_MODIFIER` becomes `WHY_MODIFIED`, and the phase claim becomes `WHY_PHASE`.

**prior_study** is now an ordinary lesion input:
- the model may propose Yes or No with a quote;
- as a boolean it is never read, so it is always pre-filled or asked;
- as a parent it is asked first (Task 1).

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_library_pack_preview.py`:

```python
async def test_each_scope_is_one_jev_call_and_there_is_no_per_quote_call(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    await PP.settle_pack(toy_entry, FINDINGS, "Smoker.", finding=FINDINGS)
    assert jev["calls"] == 2                                     # lesion batch + patient batch


async def test_a_finding_naming_other_lesions_still_drafts_its_values(toy_entry, monkeypatch, jev):
    finding = "7 mm solid nodule in the right upper lobe. Further tiny nodules."
    _model(monkeypatch, {"input": "size", "value": 7, "quote": "7 mm"})
    s = await PP.settle_pack(toy_entry, finding, "", finding=finding)
    assert "size" in s.values                                   # no multiplicity-word refusal any more


def test_the_retired_guards_are_gone():
    from rapid_reports_ai.hybrid_stack.copilot.library import quantity as Q
    for name in ("_no_prior", "_quote_claim", "QUOTE_MIN", "_FOLLOW_UP", "_ELSEWHERE"):
        assert not hasattr(PP, name)
    for name in ("many", "_ORGANS", "_QUALIFIER", "_MANY_WORDS"):
        assert not hasattr(Q, name)


async def test_prior_study_is_proposed_like_any_input():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("bts-pulmonary-nodule")
    assert e.input("prior_study").type == "boolean"             # never read: pre-filled or asked (§7.5)
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_pack_preview.py -q -k "jev_call or other_lesions or retired"`
Expected: FAIL (3 Jev calls with an enum quote; `many` still drops; the names still exist).

- [ ] **Step 3: Delete the code above.** Then find the tests that exercise the retired code:

```bash
cd backend && grep -n "many\|_ORGANS\|_QUALIFIER\|no_prior\|NO_PRIOR\|quote_claim\|QUOTE_MIN\|FOLLOW_UP\|ELSEWHERE\|PRIOR_WORD\|HISTORY_MENTIONED\|PRIOR_MENTIONED" tests/*.py
```

  - Delete tests that only test a retired function.
  - Tests that asserted an ask caused by a retired guard: keep the scenario and assert the value is now drafted.
  - Update the docstrings at the top of `pack_preview.py` and `quantity.py` to the §7.5 model. Remove "asked, never
    assumed" and describe the read, pre-filled and asked states.

- [ ] **Step 4: Run the full suite and the regression check**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check`
Expected: PASS; `0 disagree`. Then run `cd backend && .venv/bin/python -m pyflakes src/rapid_reports_ai/hybrid_stack/copilot/library/` if it is available, else a grep for each deleted name. Either way the result must be no unused import and no reference left.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/quantity.py \
  backend/tests/test_library_pack_preview.py backend/tests/test_library_quantity.py
git commit -m "refactor(library): retire the per-quote Jev claim, _no_prior and quantity.many; guards become highlight reasons"
```

---

### Task 5: Case-aware reference (links, verify gate, `highlight`)

Spec §7.11, approved 2026-10-13.

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py` (`RefLink`, `RefText.links`, `RefTable.links`, `RefTable.row_links`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py` (`_links`, called from `check`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py` (`highlight`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (`_build`, `calculate` set `highlight`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`Preview.highlight`, `Calculation.highlight`)
- Create: `backend/tests/test_library_reference_links.py`

**Interfaces:**
```python
# schema.py
class RefLink(_M):
    """What a reference item describes, by id (spec §7.11). Exactly one of outcome / step / input. A step link names
    a discrete value of that step (a band id, a table or rules result, an adjust id); an input link names an option of
    an enum or true/false of a boolean (a number is linked through the band step that reads it)."""
    outcome: str | None = None
    step: str | None = None
    input: str | None = None
    value: Any = None

class RefText(_M):  ...; links: list[RefLink] = Field(default_factory=list)
class RefTable(_M): ...; links: list[RefLink] = Field(default_factory=list)
                         row_links: list[list[RefLink]] = Field(default_factory=list)   # [] or one list per row

# describe.py
def highlight(e: Entry, t: engine.Trace | None, extra_outcomes: list[str] | None = None) -> dict:
    """{"linked": bool, "ids": [field ids hit], "rows": {table id: [row indices hit]}}"""

# types.py: Preview.highlight / Calculation.highlight: dict[str, Any] | None = None
```

**The UI contract:**
- `highlight.linked` false: show the full reference, expanded (today's behaviour).
- `highlight.linked` true: expand `ids` and the `rows` of each table, and collapse the rest.

`/open` and `/preview` carry the draft's highlight in `preview.highlight`. `/calculate` carries the result's highlight
in `calculation.highlight`. In checker mode (Task 7), the dictated category's outcomes are passed as
`extra_outcomes`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_library_reference_links.py`:

```python
import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
from rapid_reports_ai.hybrid_stack.copilot.library.verify import check


def _linked(toy):
    toy["reference"]["definitions"] = [
        {"id": "def.mid", "text": "6-8 mm solid", "locator": {"source": "S1", "page": 2},
         "links": [{"step": "size_band", "value": "6to8"}]},
        {"id": "def.sub", "text": "subsolid", "locator": {"source": "S1", "page": 2},
         "links": [{"input": "kind", "value": "subsolid"}]}]
    toy["reference"]["tables"] = [
        {"id": "tab.mgmt", "title": "Management", "columns": ["Size", "Action"],
         "rows": [["<6 mm", "none"], ["6-8 mm", "CT"]], "locator": {"source": "S1", "page": 3},
         "row_links": [[{"step": "size_band", "value": "lt6"}], [{"outcome": "ct6"}, {"outcome": "ct12"}]]}]
    return toy


def test_hits_come_from_the_trace_never_from_text(toy):
    e = Entry.model_validate(_linked(toy))
    h = D.highlight(e, E.evaluate(e, {"kind": "solid", "size": 7, "risk": "high"}))
    assert h == {"linked": True, "ids": ["def.mid"], "rows": {"tab.mgmt": [1]}}


def test_a_partial_draft_still_highlights_what_it_reached(toy):
    e = Entry.model_validate(_linked(toy))
    h = D.highlight(e, E.evaluate(e, {"size": 5}))
    assert h["ids"] == [] and h["rows"] == {"tab.mgmt": [0]}


def test_a_pack_without_links_highlights_nothing(toy_entry):
    assert D.highlight(toy_entry, E.evaluate(toy_entry, {"kind": "solid", "size": 7})) == \
        {"linked": False, "ids": [], "rows": {}}


def test_extra_outcomes_count_as_hits(toy):
    e = Entry.model_validate(_linked(toy))
    assert D.highlight(e, E.evaluate(e, {}), ["ct12"])["rows"] == {"tab.mgmt": [1]}


@pytest.mark.parametrize("link,msg", [
    ({"outcome": "nope"}, "no outcome nope"),
    ({"step": "size_band", "value": "9to10"}, "not a value of step size_band"),
    ({"step": "nope", "value": "x"}, "no step nope"),
    ({"input": "kind", "value": "cystic"}, "not a value of input kind"),
    ({"input": "size", "value": "6to8"}, "link the band step"),
])
def test_the_verify_gate_rejects_a_link_to_nothing(toy, manifest, cases, link, msg):
    toy = _linked(toy)
    toy["reference"]["definitions"][0]["links"] = [link]
    assert any(msg in p for p in check(Entry.model_validate(toy), manifest, cases))


def test_row_links_must_line_up_with_rows(toy, manifest, cases):
    toy = _linked(toy)
    toy["reference"]["tables"][0]["row_links"] = [[]]
    assert any("row_links" in p for p in check(Entry.model_validate(toy), manifest, cases))


def test_a_link_names_exactly_one_target(toy):
    toy = _linked(toy)
    toy["reference"]["definitions"][0]["links"] = [{"outcome": "ct6", "step": "size_band", "value": "6to8"}]
    with pytest.raises(ValueError):
        Entry.model_validate(toy)


def test_linked_toy_passes_the_gates(toy, manifest, cases):
    assert check(Entry.model_validate(_linked(toy)), manifest, cases) == []
```

Before writing these, check the toy entry's `result` step id and band ids in `tests/conftest.py` (`size_band`:
`lt6`, `6to8`, `gt8`). Use the names that are there.

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_reference_links.py -q`
Expected: FAIL. `links` is forbidden (`extra="forbid"`), and `highlight` does not exist.

- [ ] **Step 3: Implement.**

`schema.py`: add `RefLink` above `RefText`, and the fields above, with this validator:

```python
    @model_validator(mode="after")
    def _one_target(self) -> "RefLink":
        if sum(x is not None for x in (self.outcome, self.step, self.input)) != 1:
            raise ValueError("a reference link names exactly one of outcome, step or input")
        if self.outcome is None and self.value is None:
            raise ValueError("a step or input link names a value")
        return self
```

`verify.py`: add `_links(e)` and call it in `check` after `_refs`. Run it before the tier 1 gates, so that a broken
link fails fast:

```python
def _link_problem(e: Entry, l) -> str | None:
    if l.outcome is not None:
        return None if e.outcome(l.outcome) is not None else f"no outcome {l.outcome}"
    if l.step is not None:
        s = e.step(l.step)
        if s is None:
            return f"no step {l.step}"
        vals = {b.id for b in s.bands} if isinstance(s, BandStep) else set(_results(s) or [])
        if not vals:
            return f"step {l.step} has no discrete values to link"
        return None if l.value in vals else f"{l.value!r} is not a value of step {l.step}"
    i = e.input(l.input)
    if i is None:
        return f"no input {l.input}"
    if i.type == "number":
        return f"input {l.input} is a number: link the band step that reads it"
    vals = set(i.options) if i.type == "enum" else {True, False}
    return None if l.value in vals else f"{l.value!r} is not a value of input {l.input}"


def _links(e: Entry) -> list[str]:
    """Spec §7.11: every reference link names a real outcome, step value or input value; row links line up."""
    out = []
    for f in e.reference.fields():
        for l in f.links:
            if (p := _link_problem(e, l)) is not None:
                out.append(f"reference {f.id}: {p}")
    for tb in e.reference.tables:
        if tb.row_links and len(tb.row_links) != len(tb.rows):
            out.append(f"reference {tb.id}: row_links has {len(tb.row_links)} entries for {len(tb.rows)} rows")
        for n, ls in enumerate(tb.row_links):
            for l in ls:
                if (p := _link_problem(e, l)) is not None:
                    out.append(f"reference {tb.id} row {n}: {p}")
    return out
```

`describe.py` (import `engine` lazily inside the function if `describe` is imported by `engine`; today
`describe` imports only `engine.PH`, so a module import is fine):

```python
def _key(l) -> tuple:
    if l.outcome is not None:
        return ("outcome", l.outcome, None)
    return ("step", l.step, l.value) if l.step is not None else ("input", l.input, l.value)


def _hits(t, extra: list[str]) -> set[tuple]:
    h = {("outcome", o, None) for o in ([t.outcome] if t.outcome else []) + list(extra)}
    h |= {("step", s.id, s.value) for s in t.steps if s.state == "present" and s.value is not None}
    h |= {("input", k, v.value) for k, v in t.inputs.items() if v.state == "present" and v.value is not None}
    return h


def highlight(e: Entry, t, extra_outcomes: list[str] | None = None) -> dict:
    """Spec §7.11: the reference items the case hit, by explicit links only. No links: nothing is highlighted and
    the card shows the full reference."""
    r = e.reference
    linked = any(f.links for f in r.fields()) or any(any(ls) for tb in r.tables for ls in tb.row_links)
    if not linked or t is None:
        return {"linked": linked, "ids": [], "rows": {}}
    hits = _hits(t, extra_outcomes or [])
    ids = [f.id for f in r.fields() if any(_key(l) in hits for l in f.links)]
    rows = {tb.id: [n for n, ls in enumerate(tb.row_links) if any(_key(l) in hits for l in ls)]
            for tb in r.tables}
    return {"linked": True, "ids": ids, "rows": {k: v for k, v in rows.items() if v}}
```

`pack_preview._build` sets `highlight=highlight(e, t)` (import from `.describe`). `calculate` sets
`highlight=highlight(e, t)`. `types.py` adds `highlight: dict[str, Any] | None = None` to `Preview` and to
`Calculation`.

- [ ] **Step 4: Run the tests, the bundle and the drift test**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_reference_links.py tests/test_library_verify.py tests/test_library_describe.py tests/test_library_calculate.py -q && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py && PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py -q`
Expected: PASS. The bundle is unchanged, because no pack has links yet. If the drift test shows a diff, it is only the
new empty fields. Rebuild and commit the bundle with this task in that case.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py backend/tests/test_library_reference_links.py
git commit -m "feat(library): case-aware reference: id links in pack data, verify gate, highlight on preview and calculate"
```

---

### Task 6: Reference links on the most dictated packs

Follow-up to Task 5. One pack per dispatch, in this order: `cad-rads-2`, `cac-drs` (Agatston), `fleischner-pulmonary-nodule`, `bts-pulmonary-nodule`, `bosniak-renal-cyst`, `pi-rads-2-1`.

**Files:**
- Modify: `guidelines/<id>/entry.json` (reference `links` / `row_links` only)
- Modify: `.claude/skills/guideline-pack/AUTHORING-RULES.md` (a "Reference links" rule)
- Modify: `backend/src/rapid_reports_ai/resources/guideline_bundle.json` (rebuilt)
- Test: `backend/tests/test_library_reference_links.py`

- [ ] **Step 1: Add the authoring rule** to `.claude/skills/guideline-pack/AUTHORING-RULES.md`:

```markdown
## Reference links (spec §7.11)

- Link a reference item only to what it describes. A definition of a category links that category's outcome(s). A
  table row for a size range links the band id. A definition of an option links that input value.
- Links are ids, never text. Numbers are linked through their band step, never the input.
- Leave an item unlinked when it describes no single outcome, band or option (summaries usually).
- Never change reference text, ids or locators to make a link fit. The source wins.
- The verify gate rejects any link to a missing id; a reviewer reads every link against the source page.
```

- [ ] **Step 2: Write the failing test** in `backend/tests/test_library_reference_links.py`:

```python
LINKED = ["cad-rads-2", "cac-drs", "fleischner-pulmonary-nodule", "bts-pulmonary-nodule", "bosniak-renal-cyst",
          "pi-rads-2-1"]
NO_REFERENCE_TEXT: dict[str, set[str]] = {}   # pack -> outcomes the reference truly never describes (reviewed)


@pytest.mark.parametrize("key", LINKED)
def test_dictated_packs_are_linked_and_every_golden_outcome_hits_something(key):
    import json
    from pathlib import Path
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Cases
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup(key)
    root = Path(__file__).resolve().parents[2] / "guidelines" / key
    cases = Cases.model_validate(json.loads((root / "cases.json").read_text())).cases
    assert D.highlight(e, E.evaluate(e, {}))["linked"]
    for c in cases:
        if c.outcome is None or c.outcome in NO_REFERENCE_TEXT.get(key, set()):
            continue
        h = D.highlight(e, E.evaluate(e, c.inputs))
        assert h["ids"] or h["rows"], f"{key}: golden case {c.name} ({c.outcome}) highlights nothing"
```

The golden cases are read from `guidelines/<key>/cases.json` (`schema.Cases`: `name`, `inputs`, `outcome`).

- [ ] **Step 3: Author the links, one pack at a time.** For each pack:
  - Dispatch an authoring agent with the guideline-pack skill. It edits only `links` and `row_links` in that pack's
    `entry.json`, with the source on disk.
  - Run `build_bundle.py`, the drift test and the test above for that key.
  - Dispatch an independent reader to check each link against the source page.
  - Commit each pack on its own:

```bash
git add guidelines/<id>/entry.json backend/src/rapid_reports_ai/resources/guideline_bundle.json
git commit -m "pack(<id>): reference links for case-aware highlighting"
```

Commit the authoring-rule change with the first pack. Any outcome placed in `NO_REFERENCE_TEXT` needs the reader's
agreement, which is recorded in the commit body.

- [ ] **Step 4: Run the full suite**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py -q`
Expected: PASS.

---

### Task 7: Checker mode

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py` (`Outcome.category`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py` (`_categories`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (settle prompt, `RawSettle`, `Settlement.category`, `checker`, `finish`, `calculate`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`Checker`, `Preview.checker`, `Calculation.checker`)
- Modify: `guidelines/<computed packs>/entry.json` (`category` on outcomes)
- Modify: `.claude/skills/guideline-pack/AUTHORING-RULES.md`
- Test: `backend/tests/test_library_pack_preview.py`, `backend/tests/test_library_calculate.py`, `backend/tests/test_library_verify.py`

**Interfaces:**
```python
# schema.py
class Outcome(_M): ...; category: str | None = None    # short category label from the source, e.g. as dictated

# types.py
class Checker(BaseModel):
    category: str                      # the dictated label
    quote: str
    verdict: Literal["agrees", "disagrees", "unchecked"]
    outcomes: list[str]                # the outcomes with that category (D)
    computed: list[str] = Field(default_factory=list)   # rendered classifications still possible from the values
# Preview.checker / Calculation.checker: Checker | None = None

# pack_preview.py
CATEGORY_MIN = 0.8
def categories(e: Entry) -> dict[str, list[str]]: ...       # label -> outcome ids
def check_category(e: Entry, t: engine.Trace, label: str, quote: str) -> Checker: ...
```

**The rules (spec §7.8):**
- **Detection.** All of these must hold:
  - the settle call returns `category` with a `category_quote`;
  - the label is one of `categories(e)`;
  - the quote is verbatim in the finding;
  - `R.norm(label)` is contained in `R.norm(quote)`;
  - the lesion batch's claim `The FINDING states the {e.display} category {label}` scores at least `CATEGORY_MIN`.

  Anything else means no checker, and the card computes as usual.
- **The verdict over the draft trace `t`.** P is `{t.outcome}` if reached, else `set(t.possible)`:
  - **agrees:** P ⊆ D;
  - **disagrees:** P ∩ D is empty;
  - **unchecked:** otherwise.
- **Calculate** runs the checker over the confirmed values.
  - When the verdict is `unchecked` and D has one outcome whose text renders, `result` is that outcome's text.
  - When D has more than one outcome, `needed` is limited to the inputs whose `decides` set meets D.
  - When the verdict is `disagrees`, `result` is the computed result, as for any Calculate, and the flag is carried
    in `checker`. This is pending Hassan's decision (see the handover).
- **`highlight`** passes D as `extra_outcomes` (Task 5).
- **No lookup packs.** A pack whose category is an input (CAD-RADS, CAC-DRS, SINS, BTA U) gets no `category` labels.

- [ ] **Step 1: Write the failing tests.**

In `test_library_verify.py`:

```python
def test_a_category_label_must_be_short_and_non_empty(toy, manifest, cases):
    toy["outcomes"][0]["category"] = " "
    assert any("category" in p for p in check(Entry.model_validate(toy), manifest, cases))
```

In `test_library_calculate.py` (use a toy copy with categories `"Toy A"` on `ct6` and `ct12`, and `"Toy B"` on
`pet`):

```python
def _cat(toy):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    for o in toy["outcomes"]:
        o["category"] = {"ct6": "Toy A", "ct12": "Toy A", "pet": "Toy B"}.get(o["id"])
    return Entry.model_validate(toy)


def test_checker_agrees_disagrees_and_cannot_check(toy):
    from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
    e = _cat(toy)
    assert PP.check_category(e, E.evaluate(e, {"kind": "solid", "size": 7}), "Toy A", "Toy A").verdict == "agrees"
    assert PP.check_category(e, E.evaluate(e, {"kind": "solid", "size": 9}), "Toy A", "Toy A").verdict == "disagrees"
    assert PP.check_category(e, E.evaluate(e, {"kind": "solid"}), "Toy A", "Toy A").verdict == "unchecked"


async def test_a_dictated_category_puts_the_card_in_checker_mode(toy, monkeypatch, jev):
    e = _cat(toy)
    finding = "Toy A solid nodule, 9 mm."
    _model_cat(monkeypatch, "Toy A", "Toy A", {"input": "kind", "value": "solid", "quote": "solid"},
               {"input": "size", "value": 9, "quote": "9 mm"})
    s = await PP.settle_pack(e, finding, "", finding=finding)
    p = PP.finish(e, s, {}, None, [])
    assert p.checker.verdict == "disagrees" and p.checker.computed


async def test_an_unconfirmed_category_is_ignored(toy, monkeypatch, jev):
    e = _cat(toy)
    jev["scores"] = {"category Toy A": 0.3}
    finding = "Toy A solid nodule, 9 mm."
    _model_cat(monkeypatch, "Toy A", "Toy A")
    s = await PP.settle_pack(e, finding, "", finding=finding)
    assert s.category is None and PP.finish(e, s, {}, None, []).checker is None
```

Here `_model_cat(monkeypatch, label, quote, *items)` patches `PP._call` to return
`PP.RawSettle(settled=[...], category=label, category_quote=quote)`.

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_calculate.py tests/test_library_verify.py -q -k "checker or category"`
Expected: FAIL.

- [ ] **Step 3: Implement.**
  - **`schema.Outcome`:** add `category`. **`verify._categories`:** a set `category` must be stripped and non-empty,
    at most 40 characters, and the same label across outcomes is allowed. Call it from `check`.
  - **The settle prompt.** `_prompt` adds `CATEGORIES: <labels joined by " | ">` when the pack has any. Add one line
    to `SETTLE_SYS`, case-agnostic:

    ```
    Also return category: when the FINDING itself names one of CATEGORIES, that category exactly as listed, and category_quote: the shortest verbatim span of the FINDING naming it; otherwise both empty.
    ```

  - **`RawSettle`** gains `category: str = ""` and `category_quote: str = ""`.
  - **`settle_pack`.** If the detection rules pass code-side, add the category claim to the lesion batch (in
    `_confirm`, an optional `extra_claims` list), and set `Settlement.category = (label, quote)` when it reaches
    `CATEGORY_MIN`.
  - **`check_category`:**

```python
def categories(e: Entry) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for o in e.outcomes:
        if o.category:
            out.setdefault(o.category, []).append(o.id)
    return out


def check_category(e: Entry, t: engine.Trace, label: str, quote: str) -> Checker:
    d = categories(e).get(label, [])
    p = {t.outcome} if t.outcome is not None else set(t.possible)
    verdict = "agrees" if p and p <= set(d) else "disagrees" if not p & set(d) else "unchecked"
    shown = [engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)) for o in sorted(p)]
    return Checker(category=label, quote=quote, verdict=verdict, outcomes=d, computed=shown)
```

  - **`finish` and `calculate`** set `checker` when `s.category` is set, and pass `checker.outcomes` to `highlight`.
  - **The `unchecked` result in `calculate`.** When D has exactly one outcome, render it with
    `_outcome_text(e, t.model_copy(update={"outcome": d[0]}), sources)`. If that returns None (an unfilled
    placeholder), keep `result=None` and limit `needed` to the inputs with `set(t.decides.get(k, [])) & set(d)`.

- [ ] **Step 4: Fill `category` on the computed packs.** List the tier 1 packs whose category is computed, not an
  input:

```bash
cd backend && PYTHONPATH=src .venv/bin/python - <<'E'
import json
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
lib = LB.Library(json.loads(LB.BUNDLE.read_text()))
for e in lib._current():
    if e.tier == 1:
        print(e.key, [i.id for i in e.inputs if i.type == "enum" and len(i.options) >= 4][:3])
E
```

  - For each computed pack whose source names categories a radiologist dictates (Bosniak first; PI-RADS,
    ESE/adrenal and RCOG as their sources name them), dispatch the guideline-pack skill to set `category` from the
    source's own label, one pack per dispatch.
  - Add to `AUTHORING-RULES.md`: "`category` is the source's own short label; set it only on computed packs, never
    when the category is itself an input."
  - Rebuild the bundle and run the drift test. An independent reader checks each label against the source.

- [ ] **Step 5: Run the tests and commit**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check`
Expected: PASS; `0 disagree`.

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py \
  backend/tests/test_library_calculate.py backend/tests/test_library_verify.py
git commit -m "feat(library): checker mode: a dictated category is checked against the drafted values"
```

Then commit each pack's `category` labels on its own:
`pack(<id>): category labels for checker mode`, staging `guidelines/<id>/entry.json`, the bundle, and the skill
file the first time.

---

### Task 8: "Which lesion?"

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (`RawSettle.lesions`, `Settlement.lesions`, `settle_pack(..., picked=False)`, `_build`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/preview_cache.py` (`key(..., lesion="")`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`CardState` adds `"which_lesion"`; `Preview.lesions`, `Preview.lesion`; `Calculation.lesion`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` (`OpenRequest.lesion`, `_settlement`, span prewarm)
- Modify: `backend/scripts/guidelines/real_lab.py` (count the pick in `taps`; score pick correctness against `label["lesions"]`)
- Test: `backend/tests/test_library_pack_preview.py`, `backend/tests/test_library_preview_cache.py`, `backend/tests/test_copilot_routes.py`

**The rules (spec §7.9):**
- **`RawSettle`** gains `lesions: list[str] = []`. Add to `SETTLE_SYS`: "Also return lesions: when the FINDING
  describes more than one lesion of any kind, the shortest verbatim span of the FINDING for each; otherwise []."
- **Several lesions.** A finding has several lesions when `ONE_LESION` scores below `ONE_LESION_MIN`, or the model
  lists two or more spans that are verbatim and distinct (`P._verbatim(span, finding, "")`).
  - If it has several lesions and two or more valid spans, and nothing was picked: `Settlement.lesions = spans`,
    every lesion value is dropped, and patient values are kept.
  - If it has several lesions and fewer than two valid spans: the lesion values are dropped, so they are asked.
  - With `picked=True`, the finding is the picked span. Several lesions again means its lesion values are dropped,
    and no new pick is offered.
- **`_build`:** `state = "which_lesion"` when `s.lesions` and no pick. Eligibility still shows as `check_first`
  rows, because patient inputs are drafted.
- **Routes:**
  - `OpenRequest.lesion: _s(1000) = ""` is honoured only when it is verbatim in the finding. Otherwise it is ignored.
  - The settlement key is `PC.key(e.key, finding, findings, history, lesion=lesion)`. The make function is
    `settle_pack(e, findings, history, finding=lesion or finding, picked=bool(lesion))`.
  - When a fresh settlement has `lesions` and no pick, `_pack_result` prewarms each span's key, up to
    `LESION_PREWARM_MAX = 3`.
- **`Calculation.lesion`** echoes the pick.

- [ ] **Step 1: Write the failing tests.**

```python
TWO = "8 mm nodule right lower lobe, calcified granuloma left upper lobe."


def _model_lesions(monkeypatch, lesions, *items):
    async def call(system, prompt):
        return PP.RawSettle(settled=[PP.RawItem(**i) for i in items], lesions=lesions)
    monkeypatch.setattr(PP, "_call", call)


async def test_several_lesions_ask_which_one_and_draft_no_lesion_value(toy_entry, monkeypatch, jev):
    jev["scores"] = {"only one lesion": 0.05}
    _model_lesions(monkeypatch, ["8 mm nodule right lower lobe", "calcified granuloma left upper lobe"],
                   {"input": "size", "value": 8, "quote": "8 mm"}, {"input": "risk", "value": "high", "quote": "smoker"})
    s = await PP.settle_pack(toy_entry, TWO, "Smoker.", finding=TWO)
    p = PP.finish(toy_entry, s, {}, None, [])
    assert p.state == "which_lesion" and p.lesions == s.lesions and len(s.lesions) == 2
    assert "size" not in s.values and "risk" in s.values


async def test_a_span_that_is_not_verbatim_is_never_offered(toy_entry, monkeypatch, jev):
    jev["scores"] = {"only one lesion": 0.05}
    _model_lesions(monkeypatch, ["an 8 mm nodule", "granuloma"])
    s = await PP.settle_pack(toy_entry, TWO, "", finding=TWO)
    assert s.lesions == [] and not any(toy_entry.input(k).scope == "lesion" for k in s.values)


async def test_a_picked_span_drafts_from_the_span_alone(toy_entry, monkeypatch, jev):
    prompts = []

    async def call(system, prompt):
        prompts.append(prompt)
        return PP.RawSettle(settled=[PP.RawItem(input="size", value=8, quote="8 mm")])
    monkeypatch.setattr(PP, "_call", call)
    s = await PP.settle_pack(toy_entry, TWO, "", finding="8 mm nodule right lower lobe", picked=True)
    assert "FINDING:\n8 mm nodule right lower lobe" in prompts[0] and s.lesions == [] and "size" in s.values


def test_the_cache_key_separates_a_pick():
    from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
    assert PC.key("p", "f", "d", "h") != PC.key("p", "f", "d", "h", lesion="f1")
```

Add a route test as well. `/open` with `lesion` set to a verbatim span settles with `picked=True` (patch
`CR.settle_pack` and record its arguments). A non-verbatim `lesion` is ignored.

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_pack_preview.py tests/test_library_preview_cache.py tests/test_copilot_routes.py -q -k "lesion or pick"`
Expected: FAIL.

- [ ] **Step 3: Implement** to the rules above. In `preview_cache.key`:

```python
def key(pack_key: str, finding: str, findings: str, history: str, lesion: str = "") -> tuple:
    """Everything the settlement reads; never an answer. A picked lesion span is part of the key."""
    return (pack_key, _t(finding), _t(findings), _t(history), _t(lesion))
```

In `real_lab.taps`, `picked` is `bool(s.lesions)`. `score` compares the settler's spans with
`label["lesions"]` (same count; each settler span overlaps exactly one label span) and reports the agreement rate.
For the tap count, the truth pick is the label span that contains the card's matched lesion. Take it from the
labeller's span list as the first span. Report this assumption in the evidence doc.

- [ ] **Step 4: Run the tests and commit**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check`
Expected: PASS. The regression lab's two-lesion cases now show `which_lesion` and their `expect_state` changes. Update
only the engine-derived `expect_state` and `expect_missing` fields, and list the cases in the commit body.

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/library/preview_cache.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py \
  backend/scripts/guidelines/real_lab.py backend/scripts/guidelines/preview_lab_cases.json \
  backend/tests/test_library_pack_preview.py backend/tests/test_library_preview_cache.py backend/tests/test_copilot_routes.py
git commit -m "feat(library): which lesion? one pick drafts lesion values from the chosen verbatim span"
```

---

### Task 9: Re-run the real-dictation lab against the gate

**Files:**
- Modify: `docs/superpowers/handover/2026-10-12-copilot-evidence/real_lab.md`

- [ ] **Step 1: Reuse the Task 2 cards and labels.** Do not re-export and do not re-label. Run `run` on the same
  `cards_<pid>.json`, using the new settler. At most 2 runs. Run 2 only confirms a run 1 that missed on latency
  alone.
- [ ] **Step 2: Make a new spot-check sheet**, with the same Hassan verdicts carried over by (case, input), and send
  Hassan only the rows that are new: disagreements the old settler did not have. Then run `score` with every
  verdict.
- [ ] **Step 3: Judge the gate.**
  - **0 wrong `read` values.** Any wrong read stops the gate. Report the input and the reason; do not tune and
    re-run.
  - **Median taps of 2 or fewer.**
  - **Pre-fill error rate** per input. List each input above the agreed rate (Hassan sets it; until then, report the
    rates and do not demote).
  - **Also reported:**
    - checker share and flag correctness, against the labeller's `category` and Hassan's verdicts;
    - "Which lesion?" share and pick agreement;
    - Calculate outcome against the truth outcome;
    - latency p50 and p95 for first paint and for the draft;
    - the baseline beside each number.
- [ ] **Step 4: Demote, if Hassan agreed a rate.** Each input above the rate goes into a `DEMOTED: dict[str, set[str]]`
  (pack → inputs) constant in `pack_preview.py`. A demoted input's proposals are dropped, so it is asked. Add this
  test:

```python
def test_a_demoted_input_is_asked(toy_entry, monkeypatch, jev):
    monkeypatch.setitem(PP.DEMOTED, toy_entry.key, {"risk"})
    ...  # settle with a risk proposal; assert "risk" not in s.values
```

  Commit it as `feat(library): demote inputs above the agreed pre-fill error rate (real lab <pid>)`. Re-scoring after
  demotion needs no new run: drop the demoted inputs' drafts in `score`.
- [ ] **Step 5: Write the evidence and commit.** Update `real_lab.md` with the re-run section, aggregates only.

```bash
git add docs/superpowers/handover/2026-10-12-copilot-evidence/real_lab.md
git commit -m "lab(library): real-dictation lab re-run on the draft card"
```

Apply stays off whatever the result. Hassan rules on the gate.

---

### Task 10: Spec §12 results and handover

**Files:**
- Modify: `docs/superpowers/specs/2026-10-12-guideline-library-design.md` (§12, the "*Results:*" line under "Draft card slice")
- Create: `docs/superpowers/handover/2026-10-13-draft-card-handover.md`

- [ ] **Step 1: Replace** `*Results:* written here by plan task G.` with the gate table: baseline beside re-run, for
  wrong read, median taps, cards with 2 taps or fewer, the inputs with the highest pre-fill error, checker, lesion
  pick and latency. Add the evidence path and the commit range. Leave every other section alone.
- [ ] **Step 2: Write the handover:**
  - the state of each task, with commits;
  - the API contract the UI will read. Name the fields: `Preview.draft`, `waiting`, `draft_outcome`, `lesions`,
    `checker`, `highlight`; `POST /calculate` → `Calculation`;
  - what stays off (Apply, the UI);
  - the open decisions for Hassan, listed in that order;
  - the next plan, which is the card UI with the Task 14 mock-up first.
- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-12-guideline-library-design.md docs/superpowers/handover/2026-10-13-draft-card-handover.md
git commit -m "docs(library): draft card slice results and handover"
```

---

### Out of scope: the card UI

There is no Copilot card UI on this branch. The Svelte card belongs to a separate plan, written after this one
merges, against the contract above. That plan covers:
- the value states with their highlight reasons;
- inline edit with "Not stated";
- the Calculate button;
- the Apply line;
- the checker flag;
- the Which-lesion pick;
- the collapsed reference with highlights.

Its first task is the Task 14 mock-up, for Hassan's approval.
