# Guideline Library Next Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pack previews safe enough to gate Apply on: settle each card from its own finding, triage guideline eligibility with shared patient answers, hide preview latency behind a cache, re-run the preview lab as the Apply gate, then author UK management algorithm packs, lookup packs for dictated grades and read-only reference cards in parallel.

**Architecture:** Inputs gain `scope` (lesion | patient), `role` (clinical | eligibility), `fact` (shared patient vocabulary) and `dims` (how "A x B" becomes one number). `pack_preview` settles lesion inputs only from the card's `finding` unit, reads every number from its quote with one conversion table (`library/quantity.py`), and checks every other value with one batched Jev call per scope. The preview gains a card `state` computed in code (§7.4). A bounded, process-local preview cache (`library/preview_cache.py`) is filled by `/match` and read by `/open` and `/preview`. Tier 2 library entries are served as read-only reference cards.

**Tech Stack:** Python 3, FastAPI, pydantic v2, pytest (asyncio_mode auto), pydantic-ai via `_run_agent_with_model` (Qwen on Cerebras), Jev via `jev_post`.

**Spec:** `docs/superpowers/specs/2026-10-12-guideline-library-design.md` (§3.6 input scope and eligibility, §7.4 card states and the eligibility strip, §12 "Next slice"). Approved direction: `.superpowers/sdd/2026-10-12-guideline-library-first-slice/big-picture-review.md` ("Do next", "Don't build"). Evidence: `docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab.md` (failed gate: values from another lesion; p95 3568 ms), `schema_proof.md`, `docs/guidelines/coverage-lab-2026-10.md`, `docs/guidelines/catalogue.json`.

## Global Constraints

- Worktree `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot`, branch `feat/scratchpad-copilot`. Never push. Never commit `backend/uv.lock`.
- Every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests are flat in `backend/tests/` as `test_library_*.py` / `test_copilot_*.py`. Run them with `cd backend && PYTHONPATH=src .venv/bin/pytest …`.
- No real model, Jev or network calls in tests: mock `PP._call`, `P.jev_post`, `M._call`, `M._pack_gate`.
- Labs: at most 2 runs; keys via `load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")`; outputs in `/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad` with the pid in the filename.
- The model's number is never trusted: code reads every number and its unit from the quote. Any failure ends in "asked, never wrong" (spec §3.6, big-picture review §2).
- "An unstated eligibility input stays unknown and is never assumed eligible." A pack has at most three eligibility inputs, each from the guideline's own scope text with a locator. Never invent criteria (spec §3.6).
- An eligibility boolean is phrased as the exclusion: `true` leads to `does_not_apply`.
- A `does_not_apply` outcome never has an Apply (spec §3.6 Logic, §7.4).
- Facts are written in our own words; every rule, band, outcome and eligibility input cites a `primary` or `amendment` source; `explanatory` sources shape reference wording only (spec §3.4).
- Pack sources are fetched by a controller step into `…/scratchpad/sources3/<pack-id>/` (CAD-RADS and CAC-DRS: `…/scratchpad/sources2/`). A pack task never fetches and never substitutes a secondary source; a missing source stops that pack and is reported to Hassan.
- Every pack task authors with the project skill `/Users/hassan/Code/rapid_reports_ai/.claude/skills/guideline-pack/SKILL.md` (and its `AUTHORING-RULES.md`, `TRAPS.md`, `SOURCES.md`) and reports skill friction. Pack tasks write only `guidelines/<id>/`; only Task 29 rebuilds the bundle.
- Publisher files stay in git-ignored `guidelines/<id>/sources/`; the manifest keeps `url` and `sha256`. If a primary source can't be fetched, the task stops and asks Hassan to drop the PDF in.
- Data-authoring tasks take clinical values from the source on disk, never from this plan or from memory: the source wins.
- Prompts stay case-agnostic (no single-domain clinical examples in any system prompt).
- After any change under `guidelines/`: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py`, then the drift test `PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py -q`.
- Fail open: a Copilot failure never crashes a route; it shows less, never something wrong.
- Don't build (big-picture review): a unit-pair type system; a faster settle model or settle-prompt tuning before the cache; per-chip confirmation; a same-lesion Jev check or a "which nodule" input; a regex settle; sibling columns or a preferred body; full trace provenance; the monthly routine, the parser lab or catalogue growth; a runtime TNM migration; a Jev evidence merge blocker; a new classification-only pack type.

## Review Focus

- A dictated range or UK fraction in a quote ("6-8 mm", "3/12") must give no number, so the input is asked rather than settled to one end. Test: Task 2 `test_a_range_or_fraction_gives_no_reading`.
- A patient answer the pack cannot take ("seventy", an unknown band) must be ignored and the input asked, never crash or fill a neighbour. Test: Task 4 `test_a_patient_answer_the_pack_cannot_take_is_ignored`.
- When Jev fails for one scope only, only that scope's values are asked, and the preview is marked degraded. Test: Task 3 `test_a_jev_failure_on_one_scope_asks_only_that_scopes_values`.
- The same pack opened on two different findings in one case must never share a cached preview. Test: Task 6 `test_the_key_reads_every_input`.
- A degraded or failed preview must be returned once and never served from the cache again (otherwise one Cerebras blip sticks to a card). Test: Task 6 `test_a_degraded_or_failed_preview_is_never_served_again`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/quantity.py` (new) | Read numbers and units from a quoted span; the one conversion table | 2 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py` | `InputDef.scope/dims/role/fact`, `FACTS`, `DOES_NOT_APPLY` | 2, 4 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py` | Validate a given value behind an unknown prerequisite | 1 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py` | Eligibility gate; `MAX_VERIFY` | 4, 5 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py` | `_short` keeps table/section; `reference_view`; tier 2 material | 1, 8 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` | Per-finding settle, Jev value check, card state, patient answers, reference branch | 1, 3, 4, 8 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/preview_cache.py` (new) | Bounded, process-local preview task cache | 6 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/bundle.py` | `known_text` lists tier 2 too | 8 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` | `Preview.state/exclusion/degraded`, `Settled.fact`, `Card.reference` | 3, 4, 8 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` | `finding`, `patient`, `dictation` request fields; cache; prewarm; reference cards | 3, 4, 6, 8 |
| `backend/src/rapid_reports_ai/hybrid_stack/copilot/matcher.py` | Tier 2 entries become read-only cards | 8 |
| `guidelines/{fleischner-pulmonary-nodule,bts-pulmonary-nodule,bosniak-renal-cyst}/` | Scope on every input; eligibility inputs; golden cases | 3, 5 |
| `backend/scripts/guidelines/check_pack.py` (new) | Gates 1–4 for one pack folder, so packs are authored in parallel | 9 |
| `guidelines/<id>/` (19 new folders) | One pack each: 6 UK algorithm packs, 8 lookup packs, 5 tier 2 cards; each task writes only its own folder | 10–28 |
| `backend/src/rapid_reports_ai/resources/guideline_bundle.json` | Rebuilt bundle | 3, 5, 29 |
| `backend/tests/test_library_new_packs.py` (new) | Shape tests per pack type | 29 |
| `backend/scripts/guidelines/preview_lab.py`, `preview_lab_cases.json` | The Apply gate lab | 7 |
| `backend/tests/conftest.py` | Toy risk is patient-scoped; cache cleared per test; tier 2 toy | 3, 6, 8 |

---

### Task 1: Deferred minors (engine validation, short citations, count display)

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py:105-117` (`_inputs`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py:107-112` (`_short`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py:79-88` (`_show`)
- Test: `backend/tests/test_library_engine.py`, `backend/tests/test_library_describe.py`, `backend/tests/test_library_pack_preview.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `engine.evaluate` raises `ValueError` for an invalid given value even when the input is behind an unknown or false prerequisite. `describe._short(loc) -> str` gives `"S1 p. 3, Table 2"`. `pack_preview._show` renders a count without a unit (`"1"`, not `"1 count"`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_library_engine.py`:

```python
def test_a_bad_value_behind_an_unknown_or_false_prerequisite_is_refused(toy_entry):
    """A given value is validated even when its prerequisite is unknown (kind not given) or false (subsolid)."""
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"size": 7, "risk": "medium"})
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"kind": "subsolid", "size": 7, "risk": "medium"})
    assert E.evaluate(toy_entry, {"size": 7, "risk": "low"}).needed == ["kind"]
```

Append to `backend/tests/test_library_describe.py`:

```python
def test_a_short_citation_keeps_the_table_or_section_beside_the_page():
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Locator
    assert D._short(Locator(source="S1", page=3, table="Table 2")) == "S1 p. 3, Table 2"
    assert D._short(Locator(source="S1", page=3)) == "S1 p. 3"
    assert D._short(Locator(source="S1", section="Groups not covered")) == "S1 Groups not covered"
    assert D._short(Locator(source="S1", page=3, section="x" * 80)) == "S1 p. 3, " + "x" * 40
```

Append to `backend/tests/test_library_pack_preview.py`:

```python
def test_a_count_shows_as_a_bare_number():
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry, InputDef, InputValue
    from tests.test_library_partial import _bts
    e = _bts()
    assert PP._show(e, e.input("nodule_count"), InputValue(value=1.0)) == "1"
    assert PP._show(e, e.input("diameter_mm"), InputValue(value=9.0)) == "9 mm"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_engine.py::test_a_bad_value_behind_an_unknown_or_false_prerequisite_is_refused tests/test_library_describe.py::test_a_short_citation_keeps_the_table_or_section_beside_the_page tests/test_library_pack_preview.py::test_a_count_shows_as_a_bare_number -q`
Expected: 3 failed (`DID NOT RAISE`, `'S1 p. 3' != 'S1 p. 3, Table 2'`, `'1 count' != '1'`).

- [ ] **Step 3: Implement**

In `engine.py`, replace the body of `_inputs` with:

```python
def _inputs(entry: Entry, given: dict[str, InputValue]) -> dict[str, V]:
    env: dict[str, V] = {}
    for i in entry.inputs:
        g = given.get(i.id)
        v = UNKNOWN if g is None or g.state == "unknown" else _coerce(i, g)   # validated even when not used yet
        held = [truth(p, env) for p in i.prerequisites]
        if False in held:
            env[i.id] = V(state="not_applicable")
        elif None in held:           # a prerequisite still unknown: the input is not used yet, so the prerequisite
            env[i.id] = UNKNOWN      # gets asked before a value behind it can settle anything
        else:
            env[i.id] = v
    return env
```

In `describe.py`, replace `_short` with:

```python
def _short(loc: Locator | None) -> str:
    """A compact citation: source id, page, and the table or section name (cut to 40 characters)."""
    if loc is None:
        return ""
    where = ", ".join(x for x in (f"p. {loc.page}" if loc.page else "", (loc.table or loc.section)[:40]) if x)
    return f"{loc.source} {where}".strip()
```

In `pack_preview.py` `_show`, replace the number branch's last line:

```python
        unit = "" if i.unit == "count" else i.unit
        return f"{float(v.value):g} {unit}".strip()
```

- [ ] **Step 4: Run the tests to verify they pass, then the library suites**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: all pass. If `test_library_describe.py` reports a pack's Ask material over `PACK_MATERIAL_MAX` (the citations are longer now), raise `PACK_MATERIAL_MAX` in `backend/src/rapid_reports_ai/hybrid_stack/copilot/ask.py` from `32000` to `40000` and re-run (the material goes to Qwen, whose context is ample).

- [ ] **Step 5: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py backend/src/rapid_reports_ai/hybrid_stack/copilot/ask.py backend/tests/test_library_engine.py backend/tests/test_library_describe.py backend/tests/test_library_pack_preview.py
git commit -m "fix(library): validate values behind unknown prerequisites; fuller short citations; bare counts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Numbers read from the quote, and `scope` / `dims` on inputs

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/quantity.py`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py:10-13` (types), `:98-123` (`InputDef`)
- Test: `backend/tests/test_library_quantity.py` (new), `backend/tests/test_library_schema.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `quantity.readings(quote: str, unit: str, dims: str | None = None) -> list[float]` — every value the quote gives an input in `unit`, de-duplicated, in order.
  - `quantity.pick(readings: list[float], model: float | None) -> float | None` — one reading wins outright; several need the model's number to equal one of them.
  - `quantity.canon(unit: str) -> str`, `quantity.CONVERT: dict[tuple[str, str], float]`.
  - `schema.Scope = Literal["lesion", "patient"]`; `InputDef.scope: Scope = "lesion"`; `InputDef.dims: Literal["mean", "max"] | None = None` (numbers only).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_library_quantity.py`:

```python
import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import quantity as Q


@pytest.mark.parametrize("quote,unit,dims,want", [
    ("1.2 cm", "mm", None, [12.0]),
    ("1.2cm", "mm", None, [12.0]),
    ("12 mm", "mm", None, [12.0]),
    ("8mm", "mm", None, [8.0]),
    ("7-mm nodule", "mm", None, [7.0]),
    ("9 x 7 mm", "mm", None, [9.0, 7.0]),
    ("9 x 7 mm", "mm", "mean", [8.0]),
    ("9 x 8 mm", "mm", "mean", [8.5]),
    ("9 x 7 mm", "mm", "max", [9.0]),
    ("1.5 x 1.1 cm", "mm", "max", [15.0]),
    ("9 mm x 7 mm", "mm", "max", [9.0]),
    ("9 x 7 x 6 mm", "mm", "mean", []),          # a mean is of the two axial axes only: three dims are asked
    ("20 HU", "HU", None, [20.0]),
    ("20 Hounsfield units", "HU", None, [20.0]),
    ("6 mm", "HU", None, []),                     # a unit that does not convert: no reading
    ("150 mm3", "mm3", None, [150.0]),
    ("2.5 ml", "mm3", None, [2500.0]),
    ("2.5 cm3", "mm3", None, [2500.0]),
    ("3 weeks", "days", None, [21.0]),
    ("91 days", "days", None, [91.0]),
    ("3 months", "days", None, []),               # months and years never convert to days: asked
    ("1 year", "days", None, []),
    ("65-year-old", "years", None, [65.0]),
    ("aged 65", "years", None, [65.0]),
    ("7 nodule", "mm", None, []),                 # a bare number counts only for unitless, count and age inputs
    ("score 150", "", None, [150.0]),
    ("Solitary nodule", "count", None, [1.0]),
    ("two nodules", "count", None, [2.0]),
    ("3 nodules", "count", None, [3.0]),
    ("No other nodules", "count", None, []),
    ("seven millimetres", "mm", None, []),
    ("single nodule", "mm", None, []),
])
def test_readings(quote, unit, dims, want):
    assert Q.readings(quote, unit, dims) == want


@pytest.mark.parametrize("quote,unit", [("6-8 mm", "mm"), ("6 to 8 mm", "mm"), ("1.2–1.5 cm", "mm"),
                                        ("3/12 interval", "days"), ("seen at 6/52", "days")])
def test_a_range_or_fraction_gives_no_reading(quote, unit):
    assert Q.readings(quote, unit) == []


@pytest.mark.parametrize("readings,model,want", [
    ([12.0], None, 12.0), ([12.0], 120.0, 12.0), ([9.0, 7.0], 7.0, 7.0), ([9.0, 7.0], 8.0, None),
    ([9.0, 7.0], None, None), ([], 7.0, None)])
def test_pick_one_reading_wins_several_need_the_model(readings, model, want):
    assert Q.pick(readings, model) == want


def test_one_conversion_table():
    assert Q.CONVERT == {("cm", "mm"): 10.0, ("mm", "cm"): 0.1, ("cm3", "mm3"): 1000.0, ("mm3", "cm3"): 0.001,
                         ("weeks", "days"): 7.0}
    assert (Q.canon("HU"), Q.canon("mm³"), Q.canon("cc"), Q.canon("count")) == ("HU", "mm3", "cm3", "count")
```

Append to `backend/tests/test_library_schema.py`:

```python
def test_scope_defaults_to_lesion_and_dims_belong_to_numbers():
    assert S.InputDef(id="a", label="A", type="boolean").scope == "lesion"
    assert S.InputDef(id="p", label="P", type="boolean", scope="patient").scope == "patient"
    assert S.InputDef(id="d", label="D", type="number", unit="mm", dims="mean").dims == "mean"
    with pytest.raises(ValidationError):
        S.InputDef(id="k", label="K", type="enum", options=["x"], dims="max")
    with pytest.raises(ValidationError):
        S.InputDef(id="s", label="S", type="boolean", scope="case")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_quantity.py tests/test_library_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rapid_reports_ai.hybrid_stack.copilot.library.quantity'` and the schema test failing on `scope`.

- [ ] **Step 3: Implement**

Create `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/quantity.py`:

```python
"""Numbers read from a quoted span by code (library spec §12, next slice item 1). The model's number is never
trusted: it only chooses between several readings of one quote. One conversion table; a spoken unit that is neither
the input's unit nor converts to it by that table gives no reading, so the input is asked. A range ("6-8 mm") or a
fraction ("3/12") gives no reading either: which end is meant is a judgement, so it is asked."""
from __future__ import annotations

import re

# spoken unit (lower case) -> canonical unit
_CANON = {
    "mm": "mm", "millimetre": "mm", "millimetres": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm": "cm", "cms": "cm", "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "mm3": "mm3", "mm³": "mm3", "cubic millimetres": "mm3", "cubic millimeters": "mm3",
    "cm3": "cm3", "cm³": "cm3", "cc": "cm3", "ml": "cm3", "mls": "cm3", "millilitres": "cm3", "milliliters": "cm3",
    "hu": "HU", "hounsfield units": "HU",
    "day": "days", "days": "days", "week": "weeks", "weeks": "weeks", "month": "months", "months": "months",
    "year": "years", "years": "years", "yr": "years", "yrs": "years", "yo": "years",
}
# the one conversion table, (from, to) -> factor. Months and years never become days (their length varies): asked.
CONVERT = {("cm", "mm"): 10.0, ("mm", "cm"): 0.1, ("cm3", "mm3"): 1000.0, ("mm3", "cm3"): 0.001,
           ("weeks", "days"): 7.0}
BARE = {"", "count", "years"}       # input units a number without a spoken unit may be read in
COUNT_WORDS = {"single": 1, "solitary": 1, "sole": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
               "seven": 7, "eight": 8, "nine": 9, "ten": 10}

_NUM = r"(\d+(?:\.\d+)?)"
_UNITS = "|".join(sorted((re.escape(u) for u in _CANON), key=len, reverse=True))
_U = rf"(?:\s*-?\s*({_UNITS})(?![a-z0-9]))?"
_X = r"\s*(?:x|×|by)\s*"
_RANGE = re.compile(rf"(?<![\d.]){_NUM}{_U}\s*(?:-|–|to)\s*{_NUM}{_U}", re.I)
_FRACTION = re.compile(r"(?<![\d.])\d+\s*/\s*\d+")
_DIMS = re.compile(rf"(?<![\d.]){_NUM}{_U}{_X}{_NUM}{_U}(?:{_X}{_NUM}{_U})?", re.I)
_QTY = re.compile(rf"(?<![\d.]){_NUM}{_U}", re.I)
_COUNT_RE = re.compile(r"\b(" + "|".join(sorted(COUNT_WORDS, key=len, reverse=True)) + r")\b", re.I)


def canon(unit: str) -> str:
    u = (unit or "").strip()
    return _CANON.get(u.lower(), u)


def _conv(n: float, spoken: str | None, want: str) -> float | None:
    if spoken is None:
        return n if want in BARE else None
    have = canon(spoken)
    if have == want:
        return n
    f = CONVERT.get((have, want))
    return None if f is None else round(n * f, 6)


def readings(quote: str, unit: str, dims: str | None = None) -> list[float]:
    """Every value the quote gives an input in `unit`. A dimension group "A x B [x C] unit" gives its mean (exactly
    two dims) or its max when `dims` says so, else each member; a count input also reads count words when no digit
    reads."""
    want = canon(unit)
    out: list[float] = []

    def group(m: re.Match) -> str:
        nums = [float(x) for x in (m.group(1), m.group(3), m.group(5)) if x is not None]
        units = [m.group(2), m.group(4), m.group(6)][:len(nums)]
        last = next((u for u in reversed(units) if u), None)
        vals = [_conv(n, u or last, want) for n, u in zip(nums, units)]
        if None not in vals:
            if dims == "mean":
                out.extend([round(sum(vals) / 2, 6)] if len(vals) == 2 else [])
            elif dims == "max":
                out.append(max(vals))
            else:
                out.extend(vals)
        return " "

    text = _FRACTION.sub(" ", _RANGE.sub(" ", quote or ""))
    text = _DIMS.sub(group, text)
    for m in _QTY.finditer(text):
        v = _conv(float(m.group(1)), m.group(2), want)
        if v is not None:
            out.append(v)
    if not out and want == "count":
        out += [float(COUNT_WORDS[m.group(1).lower()]) for m in _COUNT_RE.finditer(text)]
    return list(dict.fromkeys(out))


def pick(readings: list[float], model: float | None) -> float | None:
    """One reading is the value whatever the model said; several need the model's number to equal one of them."""
    if len(readings) == 1:
        return readings[0]
    if model is None:
        return None
    hits = [r for r in readings if abs(r - model) < 1e-6]
    return hits[0] if hits else None
```

In `schema.py`, after the `Role = ...` line add:

```python
Scope = Literal["lesion", "patient"]                # lesion: the card's own finding; patient: history + dictation
```

In `InputDef`, after `locator: Locator | None = None` add:

```python
    scope: Scope = "lesion"                                # where a value may be quoted from (spec §3.6)
    dims: Literal["mean", "max"] | None = None             # a number dictated "A x B": its mean or its max
```

and in `InputDef._options`, before `return self`, add:

```python
        if self.dims is not None and self.type != "number":
            raise ValueError(f"input {self.id!r}: only a number has dims")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_quantity.py tests/test_library_schema.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/quantity.py backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py backend/tests/test_library_quantity.py backend/tests/test_library_schema.py
git commit -m "feat(library): read numbers and units from the quote; input scope and dims

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Per-finding settling

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (header and imports `:1-40`, `_answer :91-108`, `_value :111-140`, `_inputs_text :143-151`, `_asks :201-211`, `preview_pack :214-264`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py:121-130` (`Preview.degraded`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py:170-174` (`OpenRequest.finding`), `:277-286` (`_pack_result`)
- Modify: `backend/tests/conftest.py` (`TOY_ENTRY` risk input gets `"scope": "patient"`)
- Modify: `guidelines/{fleischner-pulmonary-nodule,bts-pulmonary-nodule,bosniak-renal-cyst}/entry.json` (scope and dims)
- Modify: `backend/src/rapid_reports_ai/resources/guideline_bundle.json` (rebuilt)
- Test: `backend/tests/test_library_pack_preview.py`, `backend/tests/test_copilot_routes.py`

**Interfaces:**
- Consumes: `quantity.readings`, `quantity.pick` (Task 2); `InputDef.scope`, `InputDef.dims` (Task 2); `preview._verbatim`, `preview.SETTLED_MIN`, `preview.JEV_MODEL`, `preview.JEV_TIMEOUT_S`, `preview.jev_post` (existing); `jev.scores` (existing).
- Produces:
  - `preview_pack(e, findings, history, answered, sources=None, finding="") -> Preview` — `finding` is the card's own unit text; empty means the whole dictation.
  - `Preview.degraded: bool` — the settle model or a Jev call failed, so inputs it could have settled are asked.
  - `OpenRequest.finding: str` (max 1000) passed through `/open` and `/preview`.
  - Helpers later tasks change: `_given(e, answered) -> dict[str, InputValue]`, `_build(e, t, given, quotes, sources, degraded) -> Preview`, `_asks(e, t, sources, needed) -> list[dict]`, `_outcome_text(e, t, sources) -> Proposal | None`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/conftest.py`, in `TOY_ENTRY["inputs"]`, change the `risk` input to:

```python
        {"id": "risk", "label": "Patient risk", "type": "enum", "options": ["low", "high"], "scope": "patient",
         "prerequisites": [{"ref": "kind", "eq": "solid"}]},
```

In `backend/tests/test_library_pack_preview.py`, replace the `jev` fixture and `_model` helper with:

```python
@pytest.fixture
def jev(monkeypatch):
    st = {"score": 0.9, "fail": False, "fail_if": None, "calls": 0, "payloads": []}

    async def post(payload, key, timeout, transport=None):
        st["calls"] += 1
        st["payloads"].append(payload)
        if st["fail"] or (st["fail_if"] and st["fail_if"] in payload["state"]):
            raise TimeoutError("jev slow")
        return _Resp({"answers": {k: {"noul": st["score"]} for k in payload["questions"]}})
    monkeypatch.setattr(P, "jev_post", post)
    return st


def _model(monkeypatch, *items, prompts=None):
    async def call(system, prompt):
        if prompts is not None:
            prompts.append(prompt)
        return PP.RawSettle(settled=[PP.RawItem(**i) for i in items])
    monkeypatch.setattr(PP, "_call", call)
```

Change these existing tests:
- In `test_settled_inputs_reach_a_proposal_copied_from_the_entry`, replace `and jev["calls"] == 0       # every quote verbatim: no Jev call` with `and jev["calls"] == 2       # one batched value check per scope`.
- Replace `test_unconfirmed_quote_is_asked` with:

```python
async def test_unconfirmed_values_are_asked(toy_entry, monkeypatch, jev):
    jev["fail"] = True
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "heavy smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Heavy smoker.", {})
    assert out.missing == ["kind", "risk"] and out.proposal is None and out.degraded is True
    assert [s.input for s in out.settled] == ["size"]           # a number is read by code, never put to Jev
```

- In `test_model_failure_uses_answers_only`, add `assert out.degraded is True` at the end.
- Delete `test_number_must_come_from_its_quote` (replaced below).
- Replace `test_a_count_may_be_dictated_in_words_but_a_measurement_may_not` with:

```python
@pytest.mark.parametrize("unit,quote,want", [
    ("count", "Solitary nodule", 1), ("count", "two nodules", 2), ("count", "No other nodules", None),
    ("count", "no other abnormality", None), ("mm", "seven millimetres", None), ("mm", "single nodule", None),
    ("", "single nodule", None), ("nodules", "Solitary nodule", None)])
def test_a_count_may_be_dictated_in_words_but_a_measurement_may_not(unit, quote, want):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
    i = InputDef(id="n", label="N", type="number", unit=unit, min_value=0, min_inclusive=False)
    v = PP._value(i, PP.RawItem(input="n", value=99, quote=quote))       # the model's number is ignored
    assert (v.value if v is not None else None) == want
```

Append to `backend/tests/test_library_pack_preview.py`:

```python
FINDING = "7 mm solid nodule in the right upper lobe."
TWO = FINDING + " Separately, a 12 mm densely calcified granuloma in the left lower lobe."


async def test_a_lesion_value_quoted_from_another_finding_is_asked(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, {"input": "size", "value": 12, "quote": "12 mm densely calcified granuloma"})
    out = await PP.preview_pack(toy_entry, TWO, "", {}, finding=FINDING)
    assert "size" not in {s.input for s in out.settled} and "size" in out.missing


async def test_a_patient_value_may_quote_the_history(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, TWO, "Smoker.", {}, finding=FINDING)
    assert out.proposal.recommendation == "CT at 6 months"


async def test_without_a_finding_the_whole_dictation_is_the_finding(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, {"input": "size", "value": 12, "quote": "12 mm densely calcified granuloma"})
    out = await PP.preview_pack(toy_entry, TWO, "", {})
    assert ("size", "12 mm") in {(s.input, s.value) for s in out.settled}


async def test_every_enum_and_boolean_value_is_put_to_jev_with_its_scope_as_state(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {}, finding=FINDING)
    by_state = {p["state"]: [q["instructions"] for q in p["questions"].values()] for p in jev["payloads"]}
    assert by_state[f"FINDING:\n{FINDING}"] == ["The FINDING states Nodule type: solid"]
    patient = next(s for s in by_state if s.startswith("CLINICAL HISTORY"))
    assert TWO in patient and by_state[patient] == ["The CLINICAL HISTORY or DICTATION state Patient risk: high"]


async def test_a_value_jev_does_not_find_stated_is_asked(toy_entry, monkeypatch, jev):
    jev["score"] = P.SETTLED_MIN - 0.1
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDING, "", {}, finding=FINDING)
    assert [s.input for s in out.settled] == ["size"] and "kind" in out.missing and out.degraded is False


async def test_a_jev_failure_on_one_scope_asks_only_that_scopes_values(toy_entry, monkeypatch, jev):
    jev["fail_if"] = "CLINICAL HISTORY"
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDING, "Smoker.", {}, finding=FINDING)
    assert {s.input for s in out.settled} == {"kind", "size"} and out.missing == ["risk"] and out.degraded is True


@pytest.mark.parametrize("model_value,quote,want", [
    (12, "1.2 cm", "12 mm"), (120, "12 mm", "12 mm"), (9, "7 mm", "7 mm"), (None, "8mm", "8 mm"),
    (7, "9 x 7 mm", "7 mm"), (8, "9 x 7 mm", None), (7, "6-8 mm", None), (7, "seven millimetres", None)])
async def test_the_number_is_read_from_its_quote_never_taken_from_the_model(toy_entry, monkeypatch, jev,
                                                                           model_value, quote, want):
    _model(monkeypatch, KIND, {"input": "size", "value": model_value, "quote": quote})
    out = await PP.preview_pack(toy_entry, f"{quote} solid nodule.", "", {})
    assert {s.input: s.value for s in out.settled}.get("size") == want


async def test_the_settle_prompt_is_the_finding_alone_when_no_patient_input_is_open(toy_entry, monkeypatch, jev):
    prompts = []
    _model(monkeypatch, KIND, SIZE, prompts=prompts)
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {"risk": "low"}, finding=FINDING)
    assert prompts[0].endswith(f"FINDING:\n{FINDING}")
    assert "granuloma" not in prompts[0] and "Smoker" not in prompts[0] and "- risk" not in prompts[0]


async def test_the_settle_prompt_offers_the_history_and_dictation_for_patient_inputs(toy_entry, monkeypatch, jev):
    prompts = []
    _model(monkeypatch, prompts=prompts)
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {}, finding=FINDING)
    assert "- risk [patient]:" in prompts[0] and "- kind [lesion]:" in prompts[0]
    assert "CLINICAL HISTORY: Smoker." in prompts[0] and f"DICTATION:\n{TWO}" in prompts[0]


async def test_nothing_open_calls_no_model(toy_entry, monkeypatch, jev):
    async def boom(system, prompt):
        raise AssertionError("no open input: no settle call")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(toy_entry, FINDING, "", {"kind": "solid", "size": "7", "risk": "low",
                                                         "margin": "smooth"}, finding=FINDING)
    assert out.proposal.recommendation == "CT at 12 months" and out.degraded is False


def test_a_typed_answer_is_read_like_a_quote(toy_entry):
    i = toy_entry.input("size")
    assert PP._answer(toy_entry, i, "1.2 cm").value == 12 and PP._answer(toy_entry, i, "7").value == 7
    assert PP._answer(toy_entry, i, "6-8 mm").band == "6to8" and PP._answer(toy_entry, i, "big") is None
```

In `backend/tests/test_copilot_routes.py`, add `from rapid_reports_ai.hybrid_stack.copilot import preview as P` to the imports, and in the `toy_lib` fixture, before `return lib`, add:

```python
    class _JevResp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    async def jev(payload, key, timeout, transport=None):
        return _JevResp({"answers": {k: {"noul": 0.9} for k in payload["questions"]}})
    monkeypatch.setattr(P, "jev_post", jev)
```

Append to `backend/tests/test_copilot_routes.py`:

```python
def test_open_settles_lesion_inputs_from_the_cards_own_finding(authed, toy_lib, monkeypatch):
    async def call(system, prompt):
        return PP.RawSettle(settled=[PP.RawItem(input="kind", value="solid", quote="solid"),
                                     PP.RawItem(input="size", value=12, quote="12 mm granuloma")])
    monkeypatch.setattr(PP, "_call", call)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "finding": "7 mm solid nodule.", "findings": "7 mm solid nodule. 12 mm granuloma.",
        "answered": {}}).json()
    assert "size" in d["preview"]["missing"] and d["preview"]["settled"][0]["input"] == "kind"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_pack_preview.py tests/test_copilot_routes.py -q`
Expected: FAIL — `TypeError: preview_pack() got an unexpected keyword argument 'finding'`, `degraded` missing, and the Jev-count assertions.

- [ ] **Step 3: Implement `types.py` and `routes.py`**

In `types.py` `Preview`, after `trace: ...` add:

```python
    degraded: bool = False        # library packs: the settle model or a Jev check failed, so inputs it could have
                                  # settled are asked; never served from the preview cache again
```

In `routes.py` `OpenRequest`, after `card: CardIn` add:

```python
    finding: _s(1000) = ""        # the card's own finding unit; lesion-scoped inputs are settled only from it
```

and in `_pack_result`, change the `preview_pack(...)` call to:

```python
        prev = await asyncio.wait_for(preview_pack(e, req.findings[:6000], req.clinical_history[:2000], req.answered,
                                                   L.get().sources(e.key), finding=req.finding),
                                      PREVIEW_TIMEOUT_S)
```

- [ ] **Step 4: Implement `pack_preview.py`**

Replace lines 1–40 (docstring, imports, constants, `SETTLE_SYS`) with:

```python
"""Preview for a library pack (library spec §4, §12 next slice). The model only settles inputs, each with the shortest
verbatim span that settles it, and only from that input's scope: a lesion input from the card's own finding unit, a
patient input from the clinical history or the whole dictation. Code reads every number and its unit from the quote
(the model's number is never trusted); one batched Jev call per scope checks every other value as stated; the
radiologist's answers win; the engine evaluates. Every word of the proposal comes from the entry. Any failure leaves
the input asked, never assumed."""
from __future__ import annotations

import asyncio
import json
import logging
import os

from pydantic import BaseModel, Field, field_validator

from ....enhancement_utils import _run_agent_with_model
from ....report_reconcile import QWEN
from .. import jev as J
from .. import preview as P
from .. import registry as R
from ..types import Branch, Entry as CardEntry, GuidelineContent, Input, Preview, Proposal, Publication, Settled, Source
from . import engine
from . import quantity as Q
from .describe import citation
from .schema import BandStep, Entry, InputDef, InputValue, RulesStep, conds

logger = logging.getLogger(__name__)

PACK_BRANCH = "Pack"
TIMEOUT_S = 10.0
_STATE_LABEL = {"absent": "Absent", "not_assessable": "Not assessable"}
_LEAD = {"lesion": "The FINDING states", "patient": "The CLINICAL HISTORY or DICTATION state"}

SETTLE_SYS = """You settle the inputs of one published radiology classification system for ONE finding. INPUTS lists each open input's id, scope, type and allowed values: use nothing else.
An input's scope decides where it may be settled from:
- [lesion]: the FINDING only, never another lesion in the dictation, even one of the same kind;
- [patient]: the CLINICAL HISTORY or the DICTATION (the patient, the examination or the study as a whole).
For each input its scope states, return one item:
- input: the input's id;
- state: "present" when the value is given; "absent" when the feature is said not to be there and the input lists absent; "not_assessable" when it is said that it cannot be assessed and the input lists not_assessable;
- value: when present, for an enum exactly one of its options, for a boolean true or false, for a number the number as dictated; otherwise null;
- quote: the shortest span, copied verbatim from the FINDING ([lesion]) or from the CLINICAL HISTORY or DICTATION ([patient]), that settles it; a number's quote includes its unit.
Leave out every input that is not stated: never settle a value from what is usual or likely, and never invent an input, option or state."""
```

Replace `_answer`'s last lines (from `band = next(...)` to the end of the function) with:

```python
    band = next((b for b in _bands_for(e, i) if b.label == s), None)
    if band is not None:
        return InputValue(band=band.id)
    try:
        x = float(s)
    except ValueError:
        xs = Q.readings(s, i.unit)                    # "72 years", "1.2 cm": read as a quote would be
        x = xs[0] if len(xs) == 1 else None
    return InputValue(value=x) if x is not None and i.in_range(x) else None     # out of range: still asked
```

Replace `_value` with:

```python
def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _value(i: InputDef, item: RawItem) -> InputValue | None:
    """The model's value if it is a real one: an allowed state, an option, a boolean, or a number read by code from
    the quote in the input's unit (the model's own number only chooses between several readings)."""
    if item.state in _STATE_LABEL:
        return InputValue(state=item.state) if item.state in i.states else None
    if item.state != "present":
        return None
    if i.type == "number":
        x = Q.pick(Q.readings(item.quote, i.unit, i.dims), _num(item.value))
        return InputValue(value=x) if x is not None and i.in_range(x) else None   # out of range: asked
    if item.value is None:
        return None
    if i.type == "enum":
        m = {R.norm(o): o for o in i.options}
        hit = m.get(R.norm(str(item.value)))
        return InputValue(value=hit) if hit is not None else None
    return InputValue(value=item.value) if isinstance(item.value, bool) else None
```

Replace `_inputs_text` with:

```python
def _inputs_text(e: Entry, ids: list[str]) -> str:
    lines = []
    for i in (e.input(k) for k in ids):
        allowed = (" | ".join(i.options) if i.type == "enum" else "true | false" if i.type == "boolean"
                   else f"number in {i.unit or 'the unit dictated'}")
        states = f"; states allowed: {', '.join(i.states)}" if i.states else ""
        hint = f" (dictated as: {i.how_stated})" if i.how_stated else ""
        lines.append(f"- {i.id} [{i.scope}]: {i.label}{hint} [{allowed}{states}]")
    return "\n".join(lines)


def _prompt(e: Entry, ids: list[str], finding: str, findings: str, history: str) -> str:
    """Only the open inputs; the history and the whole dictation only when a patient input is open."""
    s = f"SYSTEM: {e.display}\nINPUTS:\n{_inputs_text(e, ids)}"
    if any(e.input(k).scope == "patient" for k in ids):
        s += f"\n\nCLINICAL HISTORY: {history or 'none given'}\n\nDICTATION:\n{findings}"
    return s + f"\n\nFINDING:\n{finding}"


def _in_scope(i: InputDef, quote: str, finding: str, findings: str, history: str) -> bool:
    """A lesion input's quote lies verbatim in the card's own finding; a patient input's in the history or dictation."""
    return P._verbatim(quote, finding, "") if i.scope == "lesion" else P._verbatim(quote, findings, history)
```

Change `_asks` to take the ordered `needed` list:

```python
def _asks(e: Entry, t: engine.Trace, sources: list[dict], needed: list[str]) -> list[dict]:
    """One ask per missing input, in `needed` order: what it is, how it is answered, which outcomes it decides
    between, and where."""
    out = []
    for k in needed:
        i = e.input(k)
        decides = [{"outcome": o, "classification": engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)),
                    "citation": citation(e.outcome(o).locator, sources)} for o in t.decides.get(k, t.possible)]
        out.append({"input": k, "label": i.label,
                    "definition": {"text": i.how_stated, "citation": citation(i.locator, sources)},
                    "options": display_options(e, i), "decides_between": decides, "citations": _reads(e, k, sources)})
    return out
```

Replace `preview_pack` with:

```python
def _given(e: Entry, answered: dict[str, str]) -> dict[str, InputValue]:
    """The radiologist's answers that are real values of this entry (anything else is ignored: still asked)."""
    out: dict[str, InputValue] = {}
    for k, s in answered.items():
        i = e.input(k)
        v = _answer(e, i, s) if i is not None else None
        if v is not None:
            out[k] = v
    return out


async def _settle(e: Entry, given: dict[str, InputValue], finding: str, findings: str,
                  history: str) -> tuple[dict[str, tuple[InputValue, Settled]], bool]:
    """(the model's real values for the open inputs whose quotes lie in their scope, whether the call failed)."""
    ids = [i.id for i in e.inputs if i.id not in given]
    if not ids:
        return {}, False
    try:
        raw = await _call(SETTLE_SYS, _prompt(e, ids, finding, findings, history))
    except Exception as ex:
        logger.warning("[library.preview] settle %s: %s", type(ex).__name__, str(ex)[:200])
        return {}, True
    out: dict[str, tuple[InputValue, Settled]] = {}
    for item in raw.settled:
        i = e.input(item.input)
        q = item.quote.strip()
        if i is None or i.id not in ids or not q or not _in_scope(i, q, finding, findings, history):
            continue
        v = _value(i, item)
        if v is not None:
            out[i.id] = (v, Settled(input=i.id, value=_show(e, i, v), quote=q))
    return out, False


async def _jev(claims: list[str], state: str) -> list[float]:
    qs = {f"v{n}": {"type": "noul", "instructions": c} for n, c in enumerate(claims)}
    r = await P.jev_post({"model": P.JEV_MODEL, "state": state, "questions": qs},
                         os.environ.get("OPENROUTER_API_KEY", ""), P.JEV_TIMEOUT_S)
    r.raise_for_status()
    s = J.scores(r.json(), qs)        # malformed raises: an outage, never a low score
    return [s[f"v{n}"] for n in range(len(claims))]


async def _confirm(e: Entry, pending: dict[str, InputValue], finding: str, findings: str,
                   history: str) -> tuple[set[str], bool]:
    """(confirmed ids, whether a Jev call failed). One batched Jev call per scope, run together: "The FINDING states
    <label>: <value>" with the finding unit alone as state (lesion), or the same of the history and the dictation
    (patient). Below SETTLED_MIN, or a failed call, leaves the input asked."""
    states = {"lesion": f"FINDING:\n{finding}",
              "patient": f"CLINICAL HISTORY:\n{history or 'none given'}\n\nDICTATION:\n{findings}"}

    async def one(scope: str) -> tuple[set[str], bool]:
        ids = [k for k in pending if e.input(k).scope == scope]
        if not ids:
            return set(), False
        claims = [f"{_LEAD[scope]} {e.input(k).label}: {_show(e, e.input(k), pending[k]).replace('_', ' ')}"
                  for k in ids]
        try:
            got = await _jev(claims, states[scope])
        except Exception as ex:
            logger.info("[library.preview] value check failed (%s): %d value(s) asked", type(ex).__name__, len(ids))
            return set(), True
        return {k for k, s in zip(ids, got) if s >= P.SETTLED_MIN}, False

    (a, fa), (b, fb) = await asyncio.gather(one("lesion"), one("patient"))
    return a | b, fa or fb


def _outcome_text(e: Entry, t: engine.Trace, sources: list[dict]) -> Proposal | None:
    """The reached outcome as the entry words it, or None when its text still cites an unknown input."""
    o = e.outcome(t.outcome)
    cls, rec = engine.render(e, t, o.classification), engine.render(e, t, o.recommendation)
    caveats = [engine.render(e, t, c) for c in o.caveats]
    if any(engine.PH.search(x) for x in (cls, rec, *caveats)):
        logger.info("[library.preview] %s: outcome %s cites an input still unknown; no proposal", e.key, o.id)
        return None
    return Proposal(classification=f"{e.display} · {cls}", line=f"{e.display}: {cls}.", recommendation=rec,
                    caveats=caveats, citations=_fired(e, t, sources))


def _build(e: Entry, t: engine.Trace, given: dict[str, InputValue], quotes: dict[str, str], sources: list[dict],
           degraded: bool) -> Preview:
    settled = [Settled(input=k, value=_show(e, e.input(k), given[k]), quote=quotes.get(k, ""))
               for k in (i.id for i in e.inputs) if k in given]
    possible = [engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)) for o in t.possible]
    return Preview(settled=settled, missing=t.needed,
                   proposal=_outcome_text(e, t, sources) if t.outcome is not None else None,
                   possible=possible, bounded=t.bounded, asks=_asks(e, t, sources, t.needed),
                   trace=t.model_dump(mode="json") if t.outcome is not None else None, degraded=degraded)


async def preview_pack(e: Entry, findings: str, history: str, answered: dict[str, str],
                       sources: list[dict] | None = None, finding: str = "") -> Preview:
    sources = sources or []
    finding = finding.strip() or findings          # no unit sent (an older client): the whole dictation, as before
    given = _given(e, answered)
    model, degraded = await _settle(e, given, finding, findings, history)
    # a present number is read from its in-scope quote by code; every other value is put to Jev
    pending = {k: v for k, (v, _) in model.items() if not (e.input(k).type == "number" and v.state == "present")}
    confirmed, failed = await _confirm(e, pending, finding, findings, history) if pending else (set(), False)
    keep = [k for k in model if k not in pending or k in confirmed]
    given.update({k: model[k][0] for k in keep})
    try:
        t = engine.evaluate(e, given)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.preview] %s cannot be evaluated: %s", e.key, ex)
        return Preview(degraded=True)
    return _build(e, t, given, {k: model[k][1].quote for k in keep}, sources, degraded or failed)
```

- [ ] **Step 5: Mark scope and dims on the three packs and rebuild**

Write `/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/mark_scope.py`:

```python
"""One-off (next slice Task 3): scope on every input of the three packs, dims on the diameters. Run with the repo's
guidelines/ folder as the argument. Patient scope = the patient, the examination or the study as a whole."""
import json
import sys
from pathlib import Path

G = Path(sys.argv[1])
PATIENT = {
    "fleischner-pulmonary-nodule": {"exclusion", "count", "risk"},
    "bts-pulmonary-nodule": {"age", "sex", "family_history", "emphysema", "nodule_count", "prior_study",
                             "interval_days"},
    "bosniak-renal-cyst": {"technique"},
}
# Fleischner: average of long and short axes (its table footnote); BTS: maximum diameter (its Figure 1)
DIMS = {"fleischner-pulmonary-nodule": {"diameter_mm": "mean"}, "bts-pulmonary-nodule": {"diameter_mm": "max"}}
for pack, patient in PATIENT.items():
    p = G / pack / "entry.json"
    e = json.loads(p.read_text())
    for i in e["inputs"]:
        i["scope"] = "patient" if i["id"] in patient else "lesion"
        if i["id"] in DIMS.get(pack, {}):
            i["dims"] = DIMS[pack][i["id"]]
    p.write_text(json.dumps(e, indent=2, ensure_ascii=False) + "\n")
    print(pack, sorted(i["id"] for i in e["inputs"] if i["scope"] == "patient"))
```

Run:

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot
python3 /private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/mark_scope.py guidelines
cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py
```

Expected: three lines listing each pack's patient inputs, then `wrote …/guideline_bundle.json (3 entries)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: all pass (the drift test included).

- [ ] **Step 7: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py backend/tests/conftest.py backend/tests/test_library_pack_preview.py backend/tests/test_copilot_routes.py guidelines/fleischner-pulmonary-nodule/entry.json guidelines/bts-pulmonary-nodule/entry.json guidelines/bosniak-renal-cyst/entry.json backend/src/rapid_reports_ai/resources/guideline_bundle.json
git commit -m "feat(library): settle each card from its own finding; code-read numbers; Jev checks every value

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Eligibility triage: roles, shared facts, card state

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py` (types near `:10-13`, `InputDef`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py:8-24` (imports, `check`), add `_eligibility`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`Settled.fact`, `Preview.state`, `Preview.exclusion`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (`_given`, `_asks`, `_build`, `preview_pack`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` (`OpenRequest.patient`, `_check_patient`, `_pack_result`)
- Test: `backend/tests/test_library_schema.py`, `backend/tests/test_library_verify.py`, `backend/tests/test_library_pack_preview.py`, `backend/tests/test_copilot_routes.py`

**Interfaces:**
- Consumes: Task 3's `_given`, `_asks(e, t, sources, needed)`, `_build`, `_outcome_text`, `preview_pack(..., finding="")`.
- Produces:
  - `schema.InputRole = Literal["clinical", "eligibility"]`; `schema.Fact`; `schema.FACTS: dict[str, tuple[str, str, tuple[str, ...]]]` (fact -> type, unit, options); `schema.DOES_NOT_APPLY = "does_not_apply"`.
  - `InputDef.role: InputRole = "clinical"`; `InputDef.fact: Fact | None = None` (patient scope, matching type/unit/options).
  - `verify.MAX_ELIGIBILITY = 3`; `verify._eligibility(e) -> list[str]`, run by `check`.
  - `types.CardState = Literal["applies", "check_first", "does_not_apply"]`; `Preview.state: CardState = "applies"`; `Preview.exclusion: Proposal | None` (the does-not-apply reason with its citations; never Apply-able); `Settled.fact: str = ""`.
  - `preview_pack(e, findings, history, answered, sources=None, finding="", patient=None) -> Preview`; `_given(e, answered, patient) -> dict[str, InputValue]`.
  - Each ask dict gains `"role"`, `"scope"`, `"fact"`; `Preview.missing` and `Preview.asks` list eligibility inputs first, then clinical, each in pack order.
  - `OpenRequest.patient: dict[str, str]` (keys from `FACTS`, values ≤ 200 chars); `routes._check_patient(v) -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_library_schema.py`:

```python
def test_a_fact_needs_a_patient_scoped_input_of_its_own_form():
    assert S.InputDef(id="a", label="Age", type="number", unit="years", scope="patient", fact="age_years").fact == "age_years"
    assert S.InputDef(id="k", label="K", type="boolean", scope="patient", role="eligibility",
                      fact="known_primary_cancer").role == "eligibility"
    for bad in [dict(type="number", unit="years", fact="age_years"),                      # lesion scope
                dict(type="number", unit="months", scope="patient", fact="age_years"),    # wrong unit
                dict(type="boolean", scope="patient", fact="age_years"),                  # wrong type
                dict(type="enum", options=["m", "f"], scope="patient", fact="sex"),       # wrong options
                dict(type="boolean", scope="patient", fact="shoe_size")]:                 # not in the vocabulary
        with pytest.raises(ValidationError):
            S.InputDef(id="x", label="X", **bad)
    assert S.InputDef(id="s", label="Sex", type="enum", options=["female", "male"], scope="patient", fact="sex")
```

Append to `backend/tests/test_library_verify.py`:

```python
import copy as _copy

ELIG = {"id": "known_cancer", "label": "Known primary cancer", "type": "boolean", "scope": "patient",
        "role": "eligibility", "fact": "known_primary_cancer", "locator": {"source": "S1", "page": 1, "section": "Scope"}}


def _eligible_toy(toy, elig=ELIG):
    t = _copy.deepcopy(toy)
    t["inputs"].insert(0, _copy.deepcopy(elig))
    rules = t["logic"][1]
    for c in rules["cases"]:
        c["when"] = {"all": [{"ref": elig["id"], "eq": False}, c["when"]]}
    rules["cases"].insert(0, {"when": {"ref": elig["id"], "eq": True}, "result": "does_not_apply",
                              "locator": {"source": "S1", "page": 1}})
    t["outcomes"].append({"id": "does_not_apply", "classification": "the toy guideline does not apply",
                          "recommendation": "Manage per the clinical context.",
                          "locator": {"source": "S1", "page": 1, "section": "Scope"}})
    return t


def test_an_eligible_pack_passes_the_eligibility_gate(toy):
    assert V._eligibility(Entry.model_validate(_eligible_toy(toy))) == []


def test_the_eligibility_gate(toy):
    t = _eligible_toy(toy)
    for n in range(3):            # four eligibility inputs in all
        t["inputs"].insert(1, {**ELIG, "id": f"other{n}", "fact": None})
    assert any("at most 3" in p for p in V._eligibility(Entry.model_validate(t)))
    t = _eligible_toy(toy, {**ELIG, "locator": None})
    assert any("no locator" in p for p in V._eligibility(Entry.model_validate(t)))
    t = _eligible_toy(toy)
    t["outcomes"] = [o for o in t["outcomes"] if o["id"] != "does_not_apply"]
    t["logic"][1]["cases"][0]["result"] = "none"
    assert any("does_not_apply outcome" in p for p in V._eligibility(Entry.model_validate(t)))
    t = _copy.deepcopy(toy)
    t["inputs"].insert(0, _copy.deepcopy(ELIG))       # declared, but no rule reads it
    t["outcomes"].append({"id": "does_not_apply", "classification": "x", "locator": {"source": "S1", "page": 1}})
    assert any("never reaches the result" in p for p in V._eligibility(Entry.model_validate(t)))
```

Append to `backend/tests/test_library_pack_preview.py`:

```python
def _elig(toy):
    from tests.test_library_verify import _eligible_toy
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    return Entry.model_validate(_eligible_toy(toy))


async def test_an_unknown_eligibility_input_puts_the_card_in_check_first(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING)
    assert out.state == "check_first" and out.proposal is None and out.missing == ["known_cancer"]
    assert out.asks[0]["role"] == "eligibility" and out.asks[0]["fact"] == "known_primary_cancer"


async def test_eligibility_asks_come_before_clinical_asks(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING)
    assert out.missing == ["known_cancer", "risk"] and [a["input"] for a in out.asks] == out.missing


async def test_a_shared_patient_answer_excludes_with_a_reason_and_no_apply(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING,
                                patient={"known_primary_cancer": "Yes"})
    assert out.state == "does_not_apply" and out.proposal is None
    assert out.exclusion.classification == "Toy 2020 · the toy guideline does not apply"
    assert out.exclusion.citations and out.exclusion.recommendation == "Manage per the clinical context."
    assert next(s for s in out.settled if s.input == "known_cancer").fact == "known_primary_cancer"


async def test_an_eligible_patient_gets_the_normal_card(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "No"})
    assert out.state == "applies" and out.proposal.recommendation == "CT at 6 months" and out.exclusion is None


async def test_the_cards_own_answer_beats_the_shared_one(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"known_cancer": "No", "risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "Yes"})
    assert out.state == "applies"


async def test_a_patient_answer_the_pack_cannot_take_is_ignored(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "seventy", "age_years": "60"})
    assert out.state == "check_first" and out.missing == ["known_cancer"]
```

Append to `backend/tests/test_copilot_routes.py`:

```python
def test_open_passes_the_patient_map_and_rejects_unknown_facts(authed, toy_lib, monkeypatch):
    seen = {}

    async def fake(e, findings, history, answered, sources=None, finding="", patient=None):
        seen["patient"] = patient
        return Preview()
    monkeypatch.setattr(CR, "preview_pack", fake)
    ok = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "findings": "x", "patient": {"age_years": "60"}})
    assert ok.status_code == 200 and seen["patient"] == {"age_years": "60"}
    bad = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "findings": "x", "patient": {"shoe_size": "9"}})
    assert bad.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_schema.py tests/test_library_verify.py tests/test_library_pack_preview.py tests/test_copilot_routes.py -q`
Expected: FAIL — `role`/`fact` are extra fields (`extra="forbid"`), `V._eligibility` missing, `patient` keyword missing.

- [ ] **Step 3: Implement `schema.py`**

After the `Scope = ...` line add:

```python
InputRole = Literal["clinical", "eligibility"]      # eligibility: the guideline's own scope, asked first (spec §3.6)
Fact = Literal["known_primary_cancer", "immunocompromised", "screening_programme", "age_years", "sex"]
# a shared patient fact -> (input type, unit, enum options). Every input carrying a fact has exactly this form, so one
# answer per case fills it on every card (spec §3.6 "Shared answers")
FACTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "known_primary_cancer": ("boolean", "", ()), "immunocompromised": ("boolean", "", ()),
    "screening_programme": ("boolean", "", ()), "age_years": ("number", "years", ()),
    "sex": ("enum", "", ("female", "male"))}
DOES_NOT_APPLY = "does_not_apply"                   # the outcome an excluding eligibility input reaches; never Applied
```

In `InputDef`, after `dims` add:

```python
    role: InputRole = "clinical"
    fact: Fact | None = None                               # a shared patient fact (FACTS); patient scope only
```

and in `_options`, before `return self`, add:

```python
        if self.fact is not None:
            t, unit, opts = FACTS[self.fact]
            if self.scope != "patient" or self.type != t or self.unit != unit or tuple(self.options) != opts:
                raise ValueError(f"input {self.id!r}: fact {self.fact} needs a patient-scoped {t}"
                                 + (f" in {unit}" if unit else "") + (f" with options {list(opts)}" if opts else ""))
```

- [ ] **Step 4: Implement `verify.py`**

Change the engine import line to add `reaching`, and the schema import to add `DOES_NOT_APPLY`:

```python
from .engine import PH, EvaluationError, Trace, V, _inputs, _iv, _num, domain, evaluate, reach_states, reaching, render, run
from .schema import (DOES_NOT_APPLY, FACT_ROLES, AdjustStep, BandStep, Cases, DeriveStep, Entry, Manifest, RulesStep,
                     ScoreStep, TableStep, conds)
```

After `TOL = 1e-3` add `MAX_ELIGIBILITY = 3`. In `check`, change `p += _bands(entry) + _locators(entry, manifest)` to `p += _bands(entry) + _locators(entry, manifest) + _eligibility(entry)`. Add:

```python
def _eligibility(e: Entry) -> list[str]:
    """Spec §3.6: at most three eligibility inputs, each with its scope clause's locator, each able to change the
    result, and a does_not_apply outcome for them to reach. A wider scope belongs in applies_to or a pitfall."""
    el = [i for i in e.inputs if i.role == "eligibility"]
    if not el:
        return []
    p = []
    if len(el) > MAX_ELIGIBILITY:
        p.append(f"{len(el)} eligibility inputs: at most {MAX_ELIGIBILITY} (a wider scope belongs in applies_to or a "
                 f"pitfall)")
    p += [f"eligibility input {i.id}: no locator for its scope clause" for i in el if i.locator is None]
    if e.tier == 1:
        if e.outcome(DOES_NOT_APPLY) is None:
            p.append(f"eligibility inputs need a {DOES_NOT_APPLY} outcome")
        reach = reaching(e)
        p += [f"eligibility input {i.id} never reaches the result" for i in el if i.id not in reach]
    return p
```

- [ ] **Step 5: Implement `types.py`**

After `BranchState = ...` add `CardState = Literal["applies", "check_first", "does_not_apply"]`. In `Settled` add `fact: str = ""                # library packs: the shared patient fact this input carries ("" for none)`. In `Preview`, after `proposal`, add:

```python
    state: CardState = "applies"  # library packs (spec §7.4): does_not_apply (an eligibility input excludes), check_first
                                  # (an unknown eligibility input could change the outcome), else applies
    exclusion: Proposal | None = None   # does_not_apply: the reason and the scope clause's citations; never Applied
```

- [ ] **Step 6: Implement `pack_preview.py`**

Add `DOES_NOT_APPLY` to the schema import: `from .schema import DOES_NOT_APPLY, BandStep, Entry, InputDef, InputValue, RulesStep, conds`.

Replace `_given` with:

```python
def _given(e: Entry, answered: dict[str, str], patient: dict[str, str] | None = None) -> dict[str, InputValue]:
    """The radiologist's answers on this card, then the case's shared patient answers for inputs carrying that fact
    (one answer fills every card; a card's own answer wins). A value the entry cannot take is ignored: still asked."""
    out: dict[str, InputValue] = {}
    for k, s in answered.items():
        i = e.input(k)
        v = _answer(e, i, s) if i is not None else None
        if v is not None:
            out[k] = v
    for i in e.inputs:
        s = (patient or {}).get(i.fact) if i.fact else None
        if s is not None and i.id not in out:
            v = _answer(e, i, s)
            if v is not None:
                out[i.id] = v
    return out
```

In `_asks`, change the appended dict to:

```python
        out.append({"input": k, "label": i.label, "role": i.role, "scope": i.scope, "fact": i.fact or "",
                    "definition": {"text": i.how_stated, "citation": citation(i.locator, sources)},
                    "options": display_options(e, i), "decides_between": decides, "citations": _reads(e, k, sources)})
```

Replace `_build` with:

```python
def _build(e: Entry, t: engine.Trace, given: dict[str, InputValue], quotes: dict[str, str], sources: list[dict],
           degraded: bool) -> Preview:
    """The card (spec §7.4): eligibility asks first; the state worked out in code; a does_not_apply outcome is shown as
    an exclusion, never as a proposal, so it can never be Applied."""
    elig = [i.id for i in e.inputs if i.role == "eligibility"]
    order = elig + [i.id for i in e.inputs if i.role != "eligibility"]
    needed = sorted(t.needed, key=order.index)
    settled = [Settled(input=k, value=_show(e, e.input(k), given[k]), quote=quotes.get(k, ""),
                       fact=e.input(k).fact or "") for k in (i.id for i in e.inputs) if k in given]
    possible = [engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)) for o in t.possible]
    text = _outcome_text(e, t, sources) if t.outcome is not None else None
    if t.outcome == DOES_NOT_APPLY:
        state, proposal, exclusion = "does_not_apply", None, text
        logger.info("[library.preview] %s does not apply (eligibility given: %s)", e.key,
                    ", ".join(k for k in elig if k in given) or "none")
    else:
        state = "check_first" if set(elig) & set(needed) else "applies"
        proposal, exclusion = text, None
    return Preview(settled=settled, missing=needed, proposal=proposal, exclusion=exclusion, state=state,
                   possible=possible, bounded=t.bounded, asks=_asks(e, t, sources, needed),
                   trace=t.model_dump(mode="json") if t.outcome is not None else None, degraded=degraded)
```

In `preview_pack`, change the signature and the `given` line:

```python
async def preview_pack(e: Entry, findings: str, history: str, answered: dict[str, str],
                       sources: list[dict] | None = None, finding: str = "",
                       patient: dict[str, str] | None = None) -> Preview:
    sources = sources or []
    finding = finding.strip() or findings          # no unit sent (an older client): the whole dictation, as before
    given = _given(e, answered, patient)
```

(the rest of `preview_pack` is unchanged from Task 3).

- [ ] **Step 7: Implement `routes.py`**

Add `from .library.schema import FACTS` to the imports. Above `class OpenRequest` add:

```python
def _check_patient(v: dict[str, str]) -> dict[str, str]:
    """The case's shared patient answers: keys from the fact vocabulary only, values capped."""
    if any(k not in FACTS or len(x) > 200 for k, x in v.items()):
        raise ValueError(f"patient: keys from {sorted(FACTS)}, values up to 200 characters")
    return v
```

In `OpenRequest`, after `answered` add `patient: dict[str, str] = Field(default_factory=dict)   # shared patient answers, by fact (spec §3.6)` and the validator:

```python
    @field_validator("patient")
    @classmethod
    def _cap_patient(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_patient(v)
```

In `_pack_result`, pass `patient=req.patient` to `preview_pack` (after `finding=req.finding`).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py backend/tests/test_library_schema.py backend/tests/test_library_verify.py backend/tests/test_library_pack_preview.py backend/tests/test_copilot_routes.py
git commit -m "feat(library): eligibility inputs, shared patient facts and the three card states

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Eligibility inputs in the three packs

Data authoring: the structure is fixed here; every clinical value comes from the locator text in the repo or the source on disk (`guidelines/<id>/sources/*.txt`), and **the source wins**. Use the `guideline-pack` skill (`/Users/hassan/Code/rapid_reports_ai/.claude/skills/guideline-pack/SKILL.md`) for the hand read.

**Files:**
- Modify: `guidelines/fleischner-pulmonary-nodule/{entry,cases,review}.json|md`, `guidelines/bts-pulmonary-nodule/{entry,cases,review}`, `guidelines/bosniak-renal-cyst/{entry,cases,review}`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py:12` (`MAX_VERIFY = 400_000`)
- Modify: `backend/src/rapid_reports_ai/resources/guideline_bundle.json` (rebuilt)
- Test: `backend/tests/test_library_eligibility_packs.py` (new); existing real-pack tests in `test_library_partial.py`, `test_library_pack_preview.py`, `test_library_describe.py`, `test_library_verify.py` as needed

**Interfaces:**
- Consumes: `InputDef.role/scope/fact`, `DOES_NOT_APPLY`, `verify._eligibility` (Task 4); `pack_preview._given(e, answered, patient)` (Task 4).
- Produces (later tasks and the lab rely on these ids):
  - Fleischner: eligibility `age` (number, years, patient, fact `age_years`, band step `age_band` = `lt35` / `ge35`) and `exclusion` (boolean, patient, card-local: lung cancer screening, immunocompromise or known primary cancer); outcome `does_not_apply` (existing).
  - BTS: `age` becomes eligibility (patient, fact `age_years`, `min_value` 0), band step `age_band` = `lt18` / `ge18`, new outcome `does_not_apply`; `sex` gains fact `sex`. The previous-or-active-cancer clause stays a caveat and pitfall (decision T2), not an input.
  - Bosniak: eligibility `mimic` (boolean, lesion scope: infectious, inflammatory or vascular lesion, or necrotic solid mass), new outcome `does_not_apply`.

**Acceptance criteria:**
- Fleischner's `age` and `exclusion` locators, its `age_band` locator and its `does_not_apply` locator point at the scope clause (S1 p2 "Implications for Patient Care", already cited by `exclusion`) or the table note (S1 p3); the 35-year edge is "younger than 35 years" exclusive, as that clause states.
- BTS's `age` locator, `age_band` locator and new `does_not_apply` locator point at the "Groups not covered" clause (S1 p13, already cited by `pit.scope`); the 18-year edge follows that clause's wording.
- Bosniak's `mimic` locator and `does_not_apply` locator point at the scope clause behind `pit.scope` (S1, section "Proposed Update to the Bosniak Classification of Cystic Renal Masses", table 2). Read the clause in `guidelines/bosniak-renal-cyst/sources/*.txt` first; if it sits elsewhere, cite where it actually is, and if its list differs from "infectious, inflammatory or vascular lesions, or necrotic solid masses", word the input from the source.
- Every `does_not_apply` outcome says, in our words, that the guideline does not apply and why, recommends managing on clinical context, and has no Apply (enforced in code).
- Gates 1–4 pass; every existing golden case keeps its expected outcome (given an eligible value); new golden cases test each eligibility edge both sides and leave each eligibility input unknown once (asserting `needed`).
- `review.md` of each pack gains rows for the new inputs, bands, cases and outcomes, and a For Hassan line for the Fleischner split (age moved out of the combined exclusion so one age answer serves both nodule cards).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_library_eligibility_packs.py`:

```python
import json

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY


def _lib():
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _elig(e):
    return [i.id for i in e.inputs if i.role == "eligibility"]


def test_each_pack_declares_its_scope_clause_as_eligibility():
    lib = _lib()
    f, b, k = (lib.lookup(x) for x in ("fleischner-pulmonary-nodule", "bts-pulmonary-nodule", "bosniak-renal-cyst"))
    assert _elig(f) == ["age", "exclusion"] and _elig(b) == ["age"] and _elig(k) == ["mimic"]
    assert f.input("age").fact == b.input("age").fact == "age_years" and b.input("sex").fact == "sex"
    assert f.input("exclusion").scope == "patient" and k.input("mimic").scope == "lesion"
    assert all(e.outcome(DOES_NOT_APPLY) is not None for e in (f, b, k))


def test_one_age_answer_fills_both_nodule_cards():
    lib = _lib()
    f, b = lib.lookup("fleischner-pulmonary-nodule"), lib.lookup("bts-pulmonary-nodule")
    assert E.evaluate(f, PP._given(f, {"exclusion": "No"}, {"age_years": "30"})).outcome == DOES_NOT_APPLY
    assert E.evaluate(b, PP._given(b, {}, {"age_years": "16"})).outcome == DOES_NOT_APPLY
    tf = E.evaluate(f, PP._given(f, {"exclusion": "No", "nodule_type": "solid", "count": "single",
                                     "diameter_mm": "7", "risk": "low"}, {"age_years": "60"}))
    assert tf.outcome not in (None, DOES_NOT_APPLY)


def test_an_excluding_answer_settles_without_the_other_eligibility_input():
    f = _lib().lookup("fleischner-pulmonary-nodule")
    assert E.evaluate(f, {"exclusion": True}).outcome == DOES_NOT_APPLY        # age unknown, still excluded


def test_a_bosniak_mimic_does_not_apply():
    k = _lib().lookup("bosniak-renal-cyst")
    assert E.evaluate(k, {"mimic": True}).outcome == DOES_NOT_APPLY
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_eligibility_packs.py -q`
Expected: FAIL — `assert ['exclusion'] == ['age', 'exclusion']` (or `[] == ...`).

- [ ] **Step 3: Read the three scope clauses in the sources**

Run (the grep only locates; read the matching pages in full with the Read tool):

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot/guidelines
grep -n -i "younger than 35\|immunocompromised\|screening" fleischner-pulmonary-nodule/sources/*.txt | head -20
grep -n -i "not covered\|under 18\|children" bts-pulmonary-nodule/sources/*.txt | head -20
grep -n -i "infectious\|inflammatory\|vascular\|necrotic" bosniak-renal-cyst/sources/*.txt | head -20
```

Expected: each clause found. Record the exact page/section of each in your notes for `review.md`. If a `sources/` folder is empty (they are git-ignored), stop and ask Hassan to restore the file named in that pack's `manifest.json` (`file` / `text_file`).

- [ ] **Step 4: Apply the structural edit**

Write `/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/add_eligibility.py`. Before running, check each string marked `# FROM SOURCE` against the clause you read in Step 3 and correct it there if the source says otherwise:

```python
"""One-off (next slice Task 5): eligibility inputs for the three packs (spec §3.6). Run once with the repo's
guidelines/ folder as the argument. Wording marked FROM SOURCE was checked against the clause read in Step 3."""
import copy
import json
import sys
from pathlib import Path

G = Path(sys.argv[1])


def load(p):
    return json.loads(p.read_text())


def save(p, d):
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def wrap(cases, cond, first, extra_cases):
    """Every existing case gains `cond`; the new exclusion cases go first."""
    for c in cases:
        c["when"] = {"all": [cond, c["when"]]}
    return extra_cases + cases


def fleischner():
    d = G / "fleischner-pulmonary-nodule"
    e = load(d / "entry.json")
    ex = next(i for i in e["inputs"] if i["id"] == "exclusion")
    loc = copy.deepcopy(ex["locator"])                     # S1 p2, the scope clause
    ex.update(role="eligibility", scope="patient",
              label="Lung cancer screening, immunocompromise or known primary cancer",            # FROM SOURCE
              how_stated=("patient-level, usually from the clinical history or request: true when the scan is a lung "
                          "cancer screening CT, the patient is immunocompromised (e.g. transplant, chemotherapy, HIV) "
                          "or has a known primary cancer; false when the history states none of these. Leave it unset "
                          "when the history does not say."))
    e["inputs"].insert(0, {"id": "age", "label": "Age", "type": "number", "unit": "years", "scope": "patient",
                           "role": "eligibility", "fact": "age_years",
                           "how_stated": "patient age in years, usually from the clinical history or request",
                           "min_value": 0, "max_value": 110, "locator": loc})
    e["logic"].insert(0, {"step": "band", "id": "age_band", "ref": "age", "locator": loc, "bands": [
        {"id": "lt35", "label": "Under 35 years", "max": 35},                                  # FROM SOURCE
        {"id": "ge35", "label": "35 years or over", "min": 35}]})
    applies = next(s for s in e["logic"] if s["id"] == "applies")
    first = applies["cases"][0]
    assert first["result"] == "does_not_apply", first
    first["when"] = {"any": [first["when"], {"ref": "age_band", "eq": "lt35"}]}
    for c in applies["cases"][1:]:
        c["when"] = {"all": [{"ref": "age_band", "eq": "ge35"}, c["when"]]}
    save(d / "entry.json", e)
    cs = load(d / "cases.json")
    for c in cs["cases"]:
        c["inputs"].setdefault("age", 60)
    base = {"exclusion": False, "nodule_type": "solid", "count": "single", "diameter_mm": 7, "risk": "low"}
    ok = next(c["outcome"] for c in cs["cases"] if c["inputs"] == {**base, "age": 60}) \
        if any(c["inputs"] == {**base, "age": 60} for c in cs["cases"]) else "solid_single_6to8_low"
    cs["cases"] += [
        {"name": "age 34 is under 35: does not apply", "origin": "ours", "inputs": {**base, "age": 34},
         "outcome": "does_not_apply"},
        {"name": "age 35 is in scope", "origin": "ours", "inputs": {**base, "age": 35}, "outcome": ok},
        {"name": "age not stated", "origin": "ours", "inputs": dict(base), "outcome": None, "needed": ["age"]},
        {"name": "excluded, age not stated", "origin": "ours", "inputs": {"exclusion": True},
         "outcome": "does_not_apply"}]
    save(d / "cases.json", cs)


def bts():
    d = G / "bts-pulmonary-nodule"
    e = load(d / "entry.json")
    loc = copy.deepcopy(next(p for p in e["reference"]["pitfalls"] if p["id"] == "pit.scope")["locator"])  # S1 p13
    age = next(i for i in e["inputs"] if i["id"] == "age")
    age.update(role="eligibility", scope="patient", fact="age_years", min_value=0, locator=loc)
    sex = next(i for i in e["inputs"] if i["id"] == "sex")
    sex.update(scope="patient", fact="sex")
    e["logic"].insert(0, {"step": "band", "id": "age_band", "ref": "age", "locator": loc, "bands": [
        {"id": "lt18", "label": "Under 18 years", "max": 18},                                  # FROM SOURCE
        {"id": "ge18", "label": "18 years or over", "min": 18}]})
    pathway = next(s for s in e["logic"] if s["id"] == e["result"])
    pathway["cases"] = wrap(pathway["cases"], {"ref": "age_band", "eq": "ge18"}, None,
                            [{"when": {"ref": "age_band", "eq": "lt18"}, "result": "does_not_apply", "locator": loc}])
    e["outcomes"].append({"id": "does_not_apply",
                          "classification": "BTS 2015 does not apply: the guidelines do not cover patients under 18",  # FROM SOURCE
                          "recommendation": "Manage per the clinical context.", "locator": loc})
    save(d / "entry.json", e)
    cs = load(d / "cases.json")
    for c in cs["cases"]:
        if "age" not in c["inputs"] and "age" not in (c.get("needed") or []):
            c["inputs"]["age"] = 65
    first = next(c for c in cs["cases"] if c["inputs"].get("age") == 65 and c.get("outcome"))
    cs["cases"] += [
        {"name": "age 17 is under 18: does not apply", "origin": "ours", "inputs": {**first["inputs"], "age": 17},
         "outcome": "does_not_apply"},
        {"name": "age 18 is in scope", "origin": "ours", "inputs": {**first["inputs"], "age": 18},
         "outcome": first["outcome"]}]
    save(d / "cases.json", cs)


def bosniak():
    d = G / "bosniak-renal-cyst"
    e = load(d / "entry.json")
    loc = copy.deepcopy(next(p for p in e["reference"]["pitfalls"] if p["id"] == "pit.scope")["locator"])
    e["inputs"].insert(0, {
        "id": "mimic", "label": "Infectious, inflammatory or vascular lesion, or necrotic solid mass",   # FROM SOURCE
        "type": "boolean", "scope": "lesion", "role": "eligibility",
        "how_stated": ("true when the finding is called an abscess, an infected or inflamed collection, a vascular "
                       "lesion or a necrotic solid mass rather than a cystic renal mass; false when it is described "
                       "as a renal cyst or cystic renal mass"),
        "locator": loc})
    cls = next(s for s in e["logic"] if s["id"] == e["result"])
    cls["cases"] = wrap(cls["cases"], {"ref": "mimic", "eq": False}, None,
                        [{"when": {"ref": "mimic", "eq": True}, "result": "does_not_apply", "locator": loc}])
    e["outcomes"].append({"id": "does_not_apply",
                          "classification": ("Bosniak 2019 does not apply: an infectious, inflammatory or vascular "
                                             "lesion, or a necrotic solid mass, is outside the classification"),  # FROM SOURCE
                          "recommendation": "Manage per the clinical context.", "locator": loc})
    save(d / "entry.json", e)
    cs = load(d / "cases.json")
    for c in cs["cases"]:
        c["inputs"].setdefault("mimic", False)
    first = next(c for c in cs["cases"] if c.get("outcome"))
    cs["cases"] += [
        {"name": "abscess: does not apply", "origin": "ours", "inputs": {"mimic": True}, "outcome": "does_not_apply"},
        {"name": "mimic not stated", "origin": "ours",
         "inputs": {k: v for k, v in first["inputs"].items() if k != "mimic"}, "outcome": None, "needed": ["mimic"]}]
    save(d / "cases.json", cs)


fleischner()
bts()
bosniak()
print("done")
```

In `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py` change `MAX_VERIFY = 200_000` to `MAX_VERIFY = 400_000   # Bosniak with its eligibility input enumerates 368,640 (ruling: up to 1,000,000)`.

Run:

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot
python3 /private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/add_eligibility.py guidelines
cd backend && time PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py
```

Expected: `done`, then `wrote …/guideline_bundle.json (3 entries)` (build time roughly doubles from 26 s; note it). If the build prints problems, fix the entry or a stale case expectation (a case's `needed` list now led by an eligibility input is a stale case), never a gate.

- [ ] **Step 5: Update the real-pack tests that predate eligibility**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: failures only in tests that evaluate a real pack without an eligible value. Fix each by adding the eligible value to its inputs (`"age": 65` for BTS, `"age": 60, "exclusion": False` for Fleischner, `"mimic": False` for Bosniak), never by changing its expected outcome. `BTS_BROCK` in `test_library_partial.py` keeps `age` (it is still asked). Re-run until all pass.

- [ ] **Step 6: Gate 5 (advisory) and the hand read**

Run, for each of the three packs:

```bash
cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/jev_evidence.py ../guidelines/fleischner-pulmonary-nodule > ../guidelines/fleischner-pulmonary-nodule/evidence.md
PYTHONPATH=src .venv/bin/python scripts/guidelines/jev_evidence.py ../guidelines/bts-pulmonary-nodule > ../guidelines/bts-pulmonary-nodule/evidence.md
PYTHONPATH=src .venv/bin/python scripts/guidelines/jev_evidence.py ../guidelines/bosniak-renal-cyst > ../guidelines/bosniak-renal-cyst/evidence.md
```

Then dispatch one independent read-only reviewer (most capable model, sources on disk) with the brief: check each new eligibility input, band, rules case and `does_not_apply` outcome against its scope clause; check the new golden cases; report Critical / Important / Minor. Fix Critical and Important, have the same reviewer re-check. Add the rows and the For Hassan line to each `review.md`.

- [ ] **Step 7: Run all tests**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py --check && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: `bundle up to date`, all pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot
git add guidelines/fleischner-pulmonary-nodule guidelines/bts-pulmonary-nodule guidelines/bosniak-renal-cyst backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py backend/src/rapid_reports_ai/resources/guideline_bundle.json backend/tests/
git status --short guidelines | grep sources && echo "STOP: sources must stay ignored"
git commit -m "data(library): scope clauses as eligibility inputs for Fleischner, BTS and Bosniak

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Preview cache, filled by /match

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/preview_cache.py`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` (`MatchRequest`, `copilot_match`, `_pack_result`, new `_prewarm`)
- Modify: `backend/tests/conftest.py` (`_empty_guideline_library` also clears the cache)
- Test: `backend/tests/test_library_preview_cache.py` (new), `backend/tests/test_copilot_routes.py`

**Interfaces:**
- Consumes: `preview_pack(e, findings, history, answered, sources, finding=, patient=)` and `Preview.degraded` (Tasks 3–4); `_check_patient` (Task 4).
- Produces:
  - `preview_cache.key(pack_key, finding, findings, history, answered, patient) -> tuple`
  - `preview_cache.start(k, make: Callable[[], Coroutine[Any, Any, Preview]]) -> asyncio.Task[Preview]`
  - `preview_cache.clear() -> None`; `preview_cache.MAX_ENTRIES = 256`; `preview_cache._RUNNING: set[asyncio.Task]`
  - `MatchRequest.dictation: str` (the whole findings text the client will send as `findings` to /open; empty means the finding texts joined by newlines) and `MatchRequest.patient: dict[str, str]`.
  - Frontend contract: /open sends `finding` = the card's `FindingIn.text`, `findings` = the same `dictation`, the same `clinical_history` and `patient`, and `answered` = `{}` until a tap, to hit the cache.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_library_preview_cache.py`:

```python
import asyncio

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
from rapid_reports_ai.hybrid_stack.copilot.types import Preview

K = PC.key("p@1", "7 mm nodule.", "7 mm nodule. Liver normal.", "", {}, {})


def _maker(calls, out):
    async def make():
        calls.append(1)
        await asyncio.sleep(0)
        if isinstance(out, Exception):
            raise out
        return out
    return make


async def test_the_same_key_shares_one_preview():
    calls = []
    make = _maker(calls, Preview(missing=["x"]))
    a, b = PC.start(K, make), PC.start(K, make)
    assert a is b and (await a).missing == ["x"]
    assert (await PC.start(K, make)).missing == ["x"] and len(calls) == 1


def test_the_key_reads_every_input():
    base = ["p@1", "f", "d", "h", {"a": "1"}, {"age_years": "60"}]
    variants = [base, ["p@2", *base[1:]], ["p@1", "g", *base[2:]], [*base[:2], "e", *base[3:]],
                [*base[:3], "i", *base[4:]], [*base[:4], {"a": "2"}, base[5]], [*base[:5], {"age_years": "61"}]]
    assert len({PC.key(*v) for v in variants}) == len(variants)
    assert PC.key("p@1", "", "d", "h", {}, {}) == PC.key("p@1", "d", "d", "h", {}, {})   # no unit = the dictation
    assert PC.key("p@1", "f  x\n", "d", "h", {}, {}) == PC.key("p@1", "f x", "d", "h", {}, {})


@pytest.mark.parametrize("first", [Preview(degraded=True), RuntimeError("boom")])
async def test_a_degraded_or_failed_preview_is_never_served_again(first):
    calls = []
    t = PC.start(K, _maker(calls, first))
    try:
        await t
    except RuntimeError:
        pass
    again = await PC.start(K, _maker(calls, Preview(missing=["fresh"])))
    assert again.missing == ["fresh"] and len(calls) == 2


async def test_the_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(PC, "MAX_ENTRIES", 2)
    calls = []
    for n in range(3):
        await PC.start(("k", n), _maker(calls, Preview()))
    await PC.start(("k", 0), _maker(calls, Preview()))          # evicted: computed again
    assert len(calls) == 4
```

Append to `backend/tests/test_copilot_routes.py`:

```python
async def test_match_starts_pack_previews_and_open_reuses_them(db_session, user, monkeypatch, toy):
    from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    card = Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id="u1", branch="Pack")

    async def fake_match(db, scan, history, findings):
        return [card]
    calls = []

    async def fake_preview(e, findings, history, answered, sources=None, finding="", patient=None):
        calls.append((finding, findings, patient))
        return Preview(missing=["risk"])
    monkeypatch.setattr(CR, "match", fake_match)
    monkeypatch.setattr(CR, "preview_pack", fake_preview)
    dictation = "7 mm solid nodule. Liver normal."
    await CR.copilot_match(CR.MatchRequest(scan_type="CT", findings=[CR.FindingIn(id="u1", text="7 mm solid nodule.")],
                                           dictation=dictation, patient={"age_years": "60"}),
                           user=user, db=db_session)
    await asyncio.gather(*list(PC._RUNNING))
    out = await CR.copilot_open(CR.OpenRequest(card=CR.CardIn(**PACK_CARD), finding="7 mm solid nodule.",
                                               findings=dictation, patient={"age_years": "60"}), user=user)
    assert out.preview.missing == ["risk"]
    assert calls == [("7 mm solid nodule.", dictation, {"age_years": "60"})]      # computed once, at match time
    again = await CR.copilot_open(CR.OpenRequest(card=CR.CardIn(**PACK_CARD), finding="7 mm solid nodule.",
                                                 findings=dictation, answered={"risk": "low"},
                                                 patient={"age_years": "60"}), user=user)
    assert again.preview.missing == ["risk"] and len(calls) == 2                 # an answer is a new key
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_preview_cache.py tests/test_copilot_routes.py -q`
Expected: FAIL — `ModuleNotFoundError: … preview_cache` and `MatchRequest` has no `dictation`.

- [ ] **Step 3: Implement `preview_cache.py`**

```python
"""Pack previews computed before the card is opened (library spec §12 next slice, item 3). /match starts the preview
of every pack card it returns; /open and /preview await the same task, so opening a card is a cache hit and the
settle latency is hidden. Process-local, bounded (LRU, MAX_ENTRIES), never persisted; the key holds clinical text
(finding, dictation, history) and is never logged. Fail open: a failed or degraded preview reaches the caller once
and is never served again."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Coroutine

from ..types import Preview

logger = logging.getLogger(__name__)

MAX_ENTRIES = 256
_C: "OrderedDict[tuple, asyncio.Task]" = OrderedDict()
_RUNNING: set[asyncio.Task] = set()        # strong refs, so an evicted task still finishes


def _t(s: str) -> str:
    return " ".join((s or "").split())


def key(pack_key: str, finding: str, findings: str, history: str, answered: dict[str, str],
        patient: dict[str, str]) -> tuple:
    """Everything the preview reads. An empty finding is the whole dictation, as in preview_pack."""
    return (pack_key, _t(finding) or _t(findings), _t(findings), _t(history), tuple(sorted(answered.items())),
            tuple(sorted(patient.items())))


def _good(t: asyncio.Task, loop: asyncio.AbstractEventLoop) -> bool:
    if t.get_loop() is not loop or t.cancelled():
        return False
    if not t.done():
        return True
    if t.exception() is not None:
        return False
    r = t.result()
    return isinstance(r, Preview) and not r.degraded


def _done(t: asyncio.Task) -> None:
    _RUNNING.discard(t)
    if not t.cancelled() and t.exception() is not None:
        ex = t.exception()
        logger.warning("[library.cache] preview %s: %s", type(ex).__name__, str(ex)[:200])


def start(k: tuple, make: Callable[[], Coroutine[Any, Any, Preview]]) -> asyncio.Task:
    """The cached task for this key while it is good (running, or done with a full preview), else a new one."""
    loop = asyncio.get_running_loop()
    t = _C.get(k)
    if t is not None and _good(t, loop):
        _C.move_to_end(k)
        return t
    t = loop.create_task(make())
    _RUNNING.add(t)
    t.add_done_callback(_done)
    _C[k] = t
    _C.move_to_end(k)
    while len(_C) > MAX_ENTRIES:
        _C.popitem(last=False)
    return t


def clear() -> None:
    _C.clear()
```

- [ ] **Step 4: Implement `routes.py` and conftest**

Add `from .library import preview_cache as PC` to the imports. In `MatchRequest` add:

```python
    dictation: str = ""           # the whole findings text the client sends as `findings` on /open (cache key)
    patient: dict[str, str] = Field(default_factory=dict)

    @field_validator("patient")
    @classmethod
    def _cap_patient(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_patient(v)
```

(move `_check_patient` above `class MatchRequest` if it sits below it). Replace `_pack_result` with:

```python
async def _pack_result(pack, req: OpenRequest, t0: float) -> OpenResult:
    """Offline and engine-decided: never a fetch. The preview comes from the cache (started by /match) or starts now.
    Fail open, bounded, as _branch_and_preview."""
    e, view = pack
    sources = L.get().sources(e.key)
    findings, history = req.findings[:6000], req.clinical_history[:2000]
    k = PC.key(e.key, req.finding, findings, history, req.answered, req.patient)
    try:
        task = PC.start(k, lambda: preview_pack(e, findings, history, req.answered, sources, finding=req.finding,
                                                patient=req.patient))
        prev = await asyncio.wait_for(asyncio.shield(task), PREVIEW_TIMEOUT_S)
    except Exception as ex:   # TimeoutError included
        logger.warning("[copilot.routes] pack preview %s: %s", type(ex).__name__, str(ex)[:200])
        prev = Preview()
    return OpenResult(entry=_public(view), preview=prev, branch=PACK_BRANCH, ms=_ms(t0))


def _prewarm(req: MatchRequest, cards: list[Card]) -> int:
    """Start each pack card's preview now, keyed as /open will key it before any answer. Fail open."""
    lib = L.get()
    texts = {f.id: f.text for f in req.findings}
    dictation = (req.dictation or "\n".join(f.text for f in req.findings))[:6000]
    history = req.clinical_history[:2000]
    n = 0
    for c in cards:
        e = lib.lookup(c.key)
        finding = texts.get(c.finding_id, "")
        if e is None or e.tier != 1 or not finding:
            continue
        try:
            PC.start(PC.key(e.key, finding, dictation, history, {}, req.patient),
                     lambda e=e, finding=finding: preview_pack(e, dictation, history, {}, lib.sources(e.key),
                                                               finding=finding, patient=req.patient))
            n += 1
        except Exception as ex:
            logger.warning("[copilot.routes] prewarm %s: %s", type(ex).__name__, str(ex)[:200])
    return n
```

In `copilot_match`, after `cards = await match(...)` add `_prewarm(req, cards)`.

In `backend/tests/conftest.py` `_empty_guideline_library`, add at the end:

```python
    from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
    PC.clear()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/preview_cache.py backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py backend/tests/conftest.py backend/tests/test_library_preview_cache.py backend/tests/test_copilot_routes.py
git commit -m "feat(copilot): pack previews start at match time and are cached for open

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Preview lab re-run (the gate for Apply)

**Files:**
- Modify: `backend/scripts/guidelines/preview_lab.py` (rewrite)
- Modify: `backend/scripts/guidelines/preview_lab_cases.json`
- Create: `docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab_next_slice.md`

**Interfaces:**
- Consumes: `preview_cache.key/start` (Task 6); `preview_pack(..., finding=, patient=)`, `_given`, `_answer` (Tasks 3–4); `Preview.state`, `Settled.fact` (Task 4); the pack ids of Task 5.
- Produces: the gate result (0 wrong proposals; settled/missing correct; p95 < 2 s on a cache MISS; cache HIT reported apart) in `preview_lab_next_slice.md`.

Case format (`preview_lab_cases.json` → `{"cases": [...]}`), every case:
`pack`, `name`, `finding` (the index lesion's unit), `findings` (the whole dictation), `history`, optional `answered`, optional `patient`, optional `patient_from` (the name of an earlier case whose settled patient facts become this case's patient map), `expect_settled` (input → display value), optional `accept_missing` (inputs that may be asked instead of settled), `expect_missing`, `expect_outcome`, `expect_state`.

- [ ] **Step 1: Rewrite the script**

Replace `backend/scripts/guidelines/preview_lab.py` with:

```python
"""Preview lab (library spec §12 next slice, item 4: the gate for Apply). Each case runs through the preview cache
live (Qwen + Jev): the first call is a cache MISS (the latency gate), the second a cache HIT (reported apart). Scored
against expected settled values, missing inputs, outcome and card state; an input in accept_missing may be asked
instead of settled ("asked, never wrong"). At most 2 runs; output in the session scratchpad with the pid.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check
       cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py <scratchpad-dir>"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")   # the lab needs model keys only, never the app database
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot.library import engine  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, Library  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import _answer, _given, preview_pack  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY  # noqa: E402

CASES = Path(__file__).with_name("preview_lab_cases.json")


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _pct(xs: list[int], q: float) -> int:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


def _facts(e, settled: dict[str, str]) -> dict[str, str]:
    return {e.input(k).fact: v for k, v in settled.items() if e.input(k) is not None and e.input(k).fact}


def _state(e, t, missing) -> str:
    elig = {i.id for i in e.inputs if i.role == "eligibility"}
    return "does_not_apply" if t.outcome == DOES_NOT_APPLY else "check_first" if elig & set(missing) else "applies"


def check(lib: Library, cases: list[dict]) -> int:
    """Each case's expectations through the engine alone (no model call): its expected settled values, answers and
    patient map must give expect_outcome, expect_missing and expect_state."""
    bad, shared = 0, {}
    for c in cases:
        e = lib.lookup(c["pack"])
        patient = {**c.get("patient", {}), **shared.get(c.get("patient_from", ""), {})}
        given = _given(e, c.get("answered", {}), patient)
        for k, v in c["expect_settled"].items():
            x = _answer(e, e.input(k), v) if e.input(k) is not None else None
            if x is None:
                print(f"- {c['name']}: expect_settled {k}={v!r} is not a value of {e.key}")
                bad += 1
                continue
            given[k] = x
        shared[c["name"]] = _facts(e, c["expect_settled"])
        t = engine.evaluate(e, given)
        elig = [i.id for i in e.inputs if i.role == "eligibility"]
        order = elig + [i.id for i in e.inputs if i.id not in elig]
        missing = sorted(t.needed, key=order.index)
        got = (t.outcome, missing, _state(e, t, missing))
        want = (c["expect_outcome"], c["expect_missing"], c["expect_state"])
        if got != want:
            print(f"- {c['name']}: engine gives {got}; the case says {want}")
            bad += 1
    print(f"{len(cases)} cases checked, {bad} disagree")
    return 1 if bad else 0


async def one(lib: Library, c: dict, shared: dict) -> dict:
    e = lib.lookup(c["pack"])
    patient = {**c.get("patient", {}), **shared.get(c.get("patient_from", ""), {})}
    finding, findings, history = c.get("finding", ""), c["findings"], c.get("history", "")
    answered = c.get("answered", {})
    k = PC.key(e.key, finding, findings, history, answered, patient)

    def make():
        return preview_pack(e, findings, history, answered, lib.sources(e.key), finding=finding, patient=patient)
    t0 = time.perf_counter()
    p = await PC.start(k, make)
    miss = _ms(t0)
    t1 = time.perf_counter()
    await PC.start(k, make)
    hit = _ms(t1)
    settled = {s.input: s.value for s in p.settled}
    shared[c["name"]] = {s.fact: s.value for s in p.settled if s.fact}
    want, may = c["expect_settled"], set(c.get("accept_missing", []))
    outcome = (p.trace or {}).get("outcome")
    wrong_settled = {x: (settled[x], v) for x, v in want.items() if x in settled and settled[x] != v}
    unasked = [x for x in want if x not in settled and x not in may]
    asked_instead = [x for x in want if x not in settled and x in may]
    return {"name": c["name"], "pack": c["pack"], "ms_miss": miss, "ms_hit": hit, "degraded": p.degraded,
            "outcome": outcome, "expect_outcome": c["expect_outcome"], "state": p.state,
            "expect_state": c["expect_state"],
            "wrong_proposal": outcome is not None and outcome != c["expect_outcome"],
            "outcome_ok": outcome == c["expect_outcome"], "state_ok": p.state == c["expect_state"],
            "missing": p.missing, "expect_missing": c["expect_missing"],
            "missing_ok": p.missing == c["expect_missing"] or bool(asked_instead),
            "wrong_settled": wrong_settled, "unasked": unasked, "asked_instead": asked_instead,
            "settled": [s.model_dump() for s in p.settled], "possible": p.possible}


async def main(out_dir: Path) -> int:
    lib = Library(json.loads(BUNDLE.read_text()))
    cases = json.loads(CASES.read_text())["cases"]
    rows, shared = [], {}
    for c in cases:                      # sequential: latency is part of the gate
        rows.append(await one(lib, c, shared))
    out = out_dir / f"preview_lab_{os.getpid()}.json"
    out.write_text(json.dumps(rows, indent=1))
    miss = [r["ms_miss"] for r in rows if not r["degraded"]]
    hit = [r["ms_hit"] for r in rows if not r["degraded"]]
    n = lambda key: sum(bool(r[key]) for r in rows)   # noqa: E731
    print(f"{len(rows)} cases -> {out}")
    print(f"wrong proposals: {n('wrong_proposal')}  wrong settled: {n('wrong_settled')}  unasked: {n('unasked')}  "
          f"outcome ok: {n('outcome_ok')}  state ok: {n('state_ok')}  missing ok: {n('missing_ok')}  "
          f"asked instead: {sum(len(r['asked_instead']) for r in rows)}  degraded: {n('degraded')}")
    print(f"MISS ms p50 {_pct(miss, 0.5)} p95 {_pct(miss, 0.95)}   HIT ms p50 {_pct(hit, 0.5)} p95 {_pct(hit, 0.95)}")
    for pack in sorted({r["pack"] for r in rows}):
        print(f"  {pack}: miss ms {sorted(r['ms_miss'] for r in rows if r['pack'] == pack)}")
    for r in rows:
        if r["wrong_proposal"] or r["wrong_settled"] or r["unasked"] or not r["state_ok"] or r["asked_instead"]:
            print(f"- {r['pack']} / {r['name']}: outcome {r['outcome']} (want {r['expect_outcome']}), state "
                  f"{r['state']} (want {r['expect_state']}), wrong {r['wrong_settled']}, unasked {r['unasked']}, "
                  f"asked instead {r['asked_instead']}, missing {r['missing']}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check(Library(json.loads(BUNDLE.read_text())), json.loads(CASES.read_text())["cases"]))
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
```

- [ ] **Step 2: Update the 30 existing cases**

Edit `preview_lab_cases.json` by hand; for every existing case:
- add `"finding"`: the sentence of `findings` that describes the index lesion (for the BTS distractor case, the first sentence only);
- Fleischner: add `"answered": {"exclusion": "No"}`, and `"patient": {"age_years": "60"}` unless the history states the age;
- BTS: add `"patient": {"age_years": "65"}` unless the history states the age; for the case "unstated: age", add nothing (it becomes `expect_state: "check_first"` with `age` first in `expect_missing` and `expect_outcome: null`);
- Bosniak: add `"answered": {"mimic": "No"}`;
- BTS cases whose `nodule_count` rested on "No other … nodules": move `nodule_count` into `accept_missing` (that quote is no longer a count);
- every case: add `"expect_state"` (`"applies"` unless stated otherwise above).

- [ ] **Step 3: Add the new cases**

Append to `cases` (exact text; expectations come from the engine in Step 4):

```json
{"pack": "fleischner-pulmonary-nodule", "name": "history states every eligibility fact; per-finding",
 "finding": "Solitary 7 mm solid nodule in the right middle lobe.",
 "findings": "Solitary 7 mm solid nodule in the right middle lobe. Mild dependent atelectasis. No pleural effusion.",
 "history": "68-year-old. High risk: ex-smoker, 30 pack-years. No history of cancer and not immunocompromised. Incidental finding, not a screening scan.",
 "expect_settled": {"age": "68 years", "exclusion": "No", "nodule_type": "solid", "count": "single", "diameter_mm": "7 mm", "risk": "high"},
 "accept_missing": ["exclusion"], "expect_missing": [], "expect_outcome": "solid_single_6to8_high", "expect_state": "applies"},
{"pack": "fleischner-pulmonary-nodule", "name": "eligibility exclusion in the history: known cancer",
 "finding": "8 mm solid nodule in the left lower lobe.",
 "findings": "8 mm solid nodule in the left lower lobe. No mediastinal lymphadenopathy.",
 "history": "Known metastatic breast cancer; restaging CT.",
 "expect_settled": {"exclusion": "Yes", "nodule_type": "solid", "diameter_mm": "8 mm"},
 "accept_missing": ["exclusion"], "expect_missing": [], "expect_outcome": "does_not_apply", "expect_state": "does_not_apply"},
{"pack": "fleischner-pulmonary-nodule", "name": "eligibility exclusion in the history: under 35",
 "finding": "5 mm solid nodule in the right lower lobe.",
 "findings": "5 mm solid nodule in the right lower lobe. The lungs are otherwise clear.",
 "history": "28-year-old; incidental finding on CT abdomen.",
 "expect_settled": {"age": "28 years", "nodule_type": "solid", "diameter_mm": "5 mm"},
 "accept_missing": ["age"], "expect_missing": [], "expect_outcome": "does_not_apply", "expect_state": "does_not_apply"},
{"pack": "fleischner-pulmonary-nodule", "name": "two lesions in one sentence",
 "finding": "A 7 mm solid nodule in the right upper lobe and a 4 mm calcified granuloma in the left lower lobe.",
 "findings": "A 7 mm solid nodule in the right upper lobe and a 4 mm calcified granuloma in the left lower lobe. No other nodules.",
 "history": "70-year-old. High risk: current smoker. No history of cancer, not immunocompromised, not a screening scan.",
 "expect_settled": {"age": "70 years", "exclusion": "No", "nodule_type": "solid", "count": "single", "diameter_mm": "7 mm", "risk": "high"},
 "accept_missing": ["exclusion", "diameter_mm", "count"], "expect_missing": [], "expect_outcome": "solid_single_6to8_high", "expect_state": "applies"},
{"pack": "fleischner-pulmonary-nodule", "name": "eligibility unstated: check first",
 "finding": "7 mm solid nodule in the left lower lobe.",
 "findings": "7 mm solid nodule in the left lower lobe. No other nodules.", "history": "",
 "expect_settled": {"nodule_type": "solid", "diameter_mm": "7 mm", "count": "single"},
 "accept_missing": ["count"], "expect_missing": ["age", "exclusion", "risk"], "expect_outcome": null, "expect_state": "check_first"},
{"pack": "bts-pulmonary-nodule", "name": "two lesions in one sentence",
 "finding": "6 mm solid nodule with no calcification in the right lower lobe and a 12 mm densely calcified granuloma in the left upper lobe.",
 "findings": "6 mm solid nodule with no calcification in the right lower lobe and a 12 mm densely calcified granuloma in the left upper lobe. No previous imaging.",
 "history": "64-year-old woman.",
 "expect_settled": {"age": "64 years", "benign_features": "No", "nodule_type": "solid", "diameter_mm": "6 mm", "prior_study": "No"},
 "accept_missing": ["benign_features", "diameter_mm"], "expect_missing": [], "expect_outcome": "ct_3m", "expect_state": "applies"},
{"pack": "bts-pulmonary-nodule", "name": "eligibility exclusion in the history: under 18",
 "finding": "4 mm solid nodule in the left upper lobe.",
 "findings": "4 mm solid nodule in the left upper lobe. No other abnormality.", "history": "16-year-old; CT for trauma.",
 "expect_settled": {"age": "16 years"},
 "accept_missing": ["age"], "expect_missing": [], "expect_outcome": "does_not_apply", "expect_state": "does_not_apply"},
{"pack": "bts-pulmonary-nodule", "name": "shared answer from a tap: age in the patient map",
 "finding": "9 mm solid nodule in the right upper lobe.",
 "findings": "9 mm solid nodule in the right upper lobe. No previous imaging. No emphysema.", "history": "",
 "patient": {"age_years": "60"},
 "expect_settled": {"age": "60 years", "nodule_type": "solid", "diameter_mm": "9 mm", "prior_study": "No", "upper_lobe": "Yes", "emphysema": "No"},
 "expect_missing": ["benign_features", "sex", "family_history", "nodule_count", "spiculation"], "expect_outcome": null, "expect_state": "applies"},
{"pack": "bosniak-renal-cyst", "name": "eligibility exclusion in the finding: abscess",
 "finding": "4 cm thick-walled rim-enhancing collection in the right kidney, in keeping with a renal abscess.",
 "findings": "4 cm thick-walled rim-enhancing collection in the right kidney, in keeping with a renal abscess. Perinephric fat stranding.",
 "history": "Fever and right loin pain.",
 "expect_settled": {"mimic": "Yes"},
 "accept_missing": ["mimic"], "expect_missing": [], "expect_outcome": "does_not_apply", "expect_state": "does_not_apply"},
{"pack": "fleischner-pulmonary-nodule", "name": "shared age: source card",
 "finding": "Solitary 6 mm solid nodule with no calcification or fat in the right upper lobe.",
 "findings": "Solitary 6 mm solid nodule with no calcification or fat in the right upper lobe. No previous imaging.",
 "history": "Age 72. Low risk: never smoker. No history of cancer, not immunocompromised; incidental finding.",
 "expect_settled": {"age": "72 years", "exclusion": "No", "nodule_type": "solid", "count": "single", "diameter_mm": "6 mm", "risk": "low"},
 "accept_missing": ["exclusion"], "expect_missing": [], "expect_outcome": "solid_single_6to8_low", "expect_state": "applies"},
{"pack": "bts-pulmonary-nodule", "name": "shared age: second card takes it from the first",
 "finding": "Solitary 6 mm solid nodule with no calcification or fat in the right upper lobe.",
 "findings": "Solitary 6 mm solid nodule with no calcification or fat in the right upper lobe. No previous imaging.",
 "history": "", "patient_from": "shared age: source card",
 "expect_settled": {"age": "72 years", "benign_features": "No", "nodule_type": "solid", "diameter_mm": "6 mm", "prior_study": "No"},
 "accept_missing": ["benign_features"], "expect_missing": [], "expect_outcome": "ct_3m", "expect_state": "applies"}
```

- [ ] **Step 4: Check every expectation against the engine (no model calls)**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py --check`
Expected: `41 cases checked, 0 disagree`. Where it disagrees, the engine is right given the case's own expected values: correct the case's `expect_missing` / `expect_outcome` / `expect_state` (and record why in the results doc), never the pack. Re-run until 0.

- [ ] **Step 5: Run the lab (run 1)**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py /private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad`
Expected output shape: `41 cases -> …/preview_lab_<pid>.json`, the counts line, the `MISS ms … HIT ms …` line, per-pack latencies, and one line per case needing attention.

Read the result:
- **Any wrong proposal: STOP.** Do not tune. Write the results doc (Step 6), commit it, and report to Hassan with the case, its quotes and the settled values. Do not start Task 8 until Hassan decides.
- A system error (exception, schema rejection, every case degraded): fix the bug with a test, then run 2. No case expectations change between runs.
- Otherwise there is no run 2.

- [ ] **Step 6: Write the results**

Create `docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab_next_slice.md` with: the gate line (PASSED / FAILED and on what); a results table (run, wrong proposals, wrong settled, unasked, outcome ok, state ok, missing ok, asked instead, degraded, MISS p50/p95, HIT p50/p95); per-pack miss latencies; each wrong, unasked or asked-instead case with its quotes; the case corrections from Step 4; the raw output filename(s).

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/guidelines/preview_lab.py backend/scripts/guidelines/preview_lab_cases.json docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab_next_slice.md
git commit -m "lab(library): preview lab re-run on per-finding settling, eligibility and the cache

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Tier 2 entries as read-only reference cards

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`Card.reference`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py` (`REFERENCE_BRANCH`, `as_entry`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py` (`reference_view`, `material`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/bundle.py:130-133` (`known_text`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/matcher.py:373-384` (`_card`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` (`OpenResult.reference`, `_check_card`, `copilot_open`, `copilot_preview`, `_pack_result`)
- Modify: `backend/tests/conftest.py` (`TOY_REFERENCE`, `toy_reference` fixture)
- Test: `backend/tests/test_copilot_matcher.py`, `backend/tests/test_copilot_routes.py`, `backend/tests/test_library_describe.py`, `backend/tests/test_copilot_ask.py`

**Interfaces:**
- Consumes: `Library.lookup/find/siblings/sources`, `as_entry`, `describe.citation`, `ask._in_card` (existing; already tier-agnostic).
- Produces:
  - `pack_preview.REFERENCE_BRANCH = "Reference"`; `as_entry` names the branch `Pack` (tier 1) or `Reference` (tier 2).
  - `describe.reference_view(e, sources) -> dict[str, list[dict]]` (keys `summary`, `definitions`, `tables`, `pitfalls`; each field without `locator`, with `citation`).
  - `Card.reference: bool = False` (a tier 2 card: read-only, no preview, no Apply).
  - `OpenResult.reference: dict[str, Any] | None` for every library entry; tier 2 opens with `preview=None`, `branch="Reference"`.
  - Matcher: a tier 2 name hit passes the same applicability gate and becomes a `reference=True` card. `Library.known_text()` lists tier 2 entries too.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/conftest.py`, after `TOY_CASES` add:

```python
TOY_REFERENCE = {
    "id": "toy-grade", "version": "1.0", "topic": "toy-grade", "issuer": "TOY", "system": "Toy grading",
    "display": "Toy grade 2020", "edition": "2020", "tier": 2,
    "applies_to": {"region": ["knee"], "modality": ["MRI"], "finding_type": ["cartilage defect"], "context": []},
    "aliases": ["toy grade"],
    "reference": {
        "summary": [{"id": "sum.1", "text": "A toy grading for tests.", "locator": {"source": "S1", "page": 1}}],
        "definitions": [{"id": "def.g2", "text": "Grade 2: a partial-thickness defect.",
                         "locator": {"source": "S1", "page": 2}}],
        "tables": [{"id": "tab.grades", "title": "Grade table", "columns": ["Grade", "Meaning"],
                    "rows": [["1", "softening"], ["2", "partial-thickness defect"]],
                    "locator": {"source": "S1", "page": 2, "table": "1"}}],
        "pitfalls": []}}
```

and after the `toy` fixture:

```python
@pytest.fixture
def toy_reference():
    return _copy.deepcopy(TOY_REFERENCE)
```

Append to `backend/tests/test_copilot_matcher.py`:

```python
async def test_a_reference_entry_hit_becomes_a_read_only_card(db_session, monkeypatch, toy, toy_reference):
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy, toy_reference))

    async def call(prompt):
        assert "- toy-grade@1.0: Toy grade 2020 [aliases: toy grade]" in prompt
        return _raw(u1=[_sys("Toy grade", "2020")])
    gated = []

    async def pack_gate(finding, pack, history=""):
        gated.append(pack.key)
        return 0.9
    monkeypatch.setattr(M, "_call", call)
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    cards = await M.match(db_session, "MRI knee", "", U[:1])
    assert [(c.key, c.branch, c.skeleton, c.reference) for c in cards] == \
        [("toy-grade@1.0", "Reference", ["Reference"], True)]
    assert gated == ["toy-grade@1.0"]
```

In `backend/tests/test_copilot_routes.py`, delete `test_a_non_servable_library_key_is_rejected_and_never_fetched` and append:

```python
def test_a_reference_card_opens_read_only_and_is_never_fetched(authed, monkeypatch, toy_reference):
    lib = L.Library({"version": "v1", "entries": {"toy-grade@1.0": {"entry": toy_reference, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def resolve(db, card):
        raise AssertionError("never fetched")

    async def call(system, prompt):
        raise AssertionError("a reference card is never previewed")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(PP, "_call", call)
    card = {"key": "toy-grade@1.0", "name": "Toy grade 2020", "version": "2020", "finding_id": "u1",
            "branch": "Reference"}
    for path in ("open", "preview"):
        d = authed.post(f"/api/canvas/stack/guidelines/{path}", json={"card": card, "findings": "grade 2."}).json()
        assert d["error"] is None and d["preview"] is None and d["branch"] == "Reference"
        assert d["entry"]["content"]["branches"][0]["name"] == "Reference"
        assert d["reference"]["tables"][0]["rows"][1] == ["2", "partial-thickness defect"]
        assert d["reference"]["tables"][0]["citation"]["page"] == 2


def test_a_pack_open_carries_its_reference_fields(authed, toy_lib):
    d = authed.post("/api/canvas/stack/guidelines/open", json={"card": PACK_CARD, "findings": "7 mm solid nodule."}).json()
    assert d["reference"]["summary"][0]["id"] == "sum.1"
```

Append to `backend/tests/test_library_describe.py`:

```python
def test_reference_view_gives_every_field_with_its_citation(toy_reference):
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    v = D.reference_view(Entry.model_validate(toy_reference), [{"id": "S1", "title": "Toy grading", "edition": "2020"}])
    assert v["tables"][0]["rows"] == [["1", "softening"], ["2", "partial-thickness defect"]]
    assert v["definitions"][0]["citation"] == {"source": "S1", "title": "Toy grading", "edition": "2020", "page": 2}
    assert v["pitfalls"] == [] and "locator" not in v["summary"][0]


def test_material_for_a_reference_entry_has_no_inputs_line(toy_reference):
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    m = D.material(Entry.model_validate(toy_reference), [{"id": "S1", "title": "Toy grading", "edition": "2020"}])
    assert "Inputs:" not in m and "Grade table" in m and "2 | partial-thickness defect" in m
```

Append to `backend/tests/test_copilot_ask.py`:

```python
async def test_ask_on_a_reference_card_is_grounded_in_its_fields(db_session, monkeypatch, toy_reference):
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
    lib = L.Library({"version": "v1", "entries": {"toy-grade@1.0": {"entry": toy_reference, "sources": []}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    seen = {}

    async def grounded(question, material, ctx, history):
        seen["material"] = material
        return "Grade 2 is a partial-thickness defect."
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "what is grade 2?", "toy-grade@1.0", A.Context(), [])
    assert res.answer == "Grade 2 is a partial-thickness defect." and "Grade table" in seen["material"]
    assert res.entry.content.branches[0].name == "Reference"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_copilot_matcher.py tests/test_copilot_routes.py tests/test_library_describe.py tests/test_copilot_ask.py -q`
Expected: FAIL — no `reference` on `Card`, 400 on the tier 2 open, no `reference_view`.

- [ ] **Step 3: Implement**

`types.py` `Card`, after `siblings`:

```python
    reference: bool = False       # a tier 2 library entry: read-only (reference fields and Ask), no preview, no Apply
```

`pack_preview.py`: after `PACK_BRANCH = "Pack"` add `REFERENCE_BRANCH = "Reference"`; in `as_entry` replace `branches=[Branch(name=PACK_BRANCH, ...` with `branches=[Branch(name=PACK_BRANCH if e.tier == 1 else REFERENCE_BRANCH, ...`.

`describe.py`: in `material`, replace the `lines.append("Inputs: " ...)` line with:

```python
    if e.inputs:
        lines.append("Inputs: " + "; ".join(i.label + (f" ({i.how_stated})" if i.how_stated else "")
                                            for i in e.inputs) + ".")
```

and add:

```python
def reference_view(e: Entry, sources: list[dict]) -> dict:
    """The entry's reference fields for the reading pane, each with its citation instead of its locator. A tier 2
    card shows only this; a tier 1 card shows it beside the preview."""
    def one(f) -> dict:
        return {**f.model_dump(exclude={"locator"}), "citation": citation(f.locator, sources)}
    r = e.reference
    return {k: [one(f) for f in getattr(r, k)] for k in ("summary", "definitions", "tables", "pitfalls")}
```

`bundle.py` `known_text`: drop the tier filter:

```python
    def known_text(self) -> str:
        """Lines for the matcher prompt's KNOWN SYSTEMS block, in its `- key: name` format (both tiers)."""
        return "\n".join(f"- {e.key}: {e.display} [aliases: {' | '.join(e.aliases)}]" for e in self._current())
```

`matcher.py`: import `REFERENCE_BRANCH` beside `PACK_BRANCH`; in `_card` replace the library block with:

```python
    if pack is not None:
        # A name hit is not applicability: Jev must agree the finding is the kind this entry is for (fails closed: no
        # card, never a fall-through to the registry). Siblings share topic and applies_to: gated once, on the hit.
        if gate:
            score = await _pgate(f.text, pack, history)
            if score is None or score < PACK_GATE_MIN:
                return None
        branch = PACK_BRANCH if pack.tier == 1 else REFERENCE_BRANCH
        return Card(key=pack.key, name=pack.display, version=pack.edition, finding_id=f.id, why=s.why,
                    branch=branch, skeleton=[branch], publication=Publication(body=pack.issuer, year=pack.edition),
                    known=True, status="verified", siblings=[x.key for x in lib.siblings(pack)],
                    reference=pack.tier == 2)
```

`routes.py`: import `REFERENCE_BRANCH` and `from .library import describe as D`. In `OpenResult` add `reference: dict[str, Any] | None = None   # library entries: reference fields with citations`. In `_check_card`, replace

```python
    if _pack(card.key) is not None:
        return
    if L.get().lookup(card.key) is not None:
        raise HTTPException(status_code=400, detail="Not an openable guideline")
```

with

```python
    if L.get().lookup(card.key) is not None:      # a library entry of either tier
        return
```

Add below `_pack`:

```python
def _reference(key: str):
    """The tier 2 library entry for a card key, as (entry, card-shaped entry), or None."""
    lib = L.get()
    e = lib.lookup(key)
    return (e, as_entry(e, lib.sources(e.key))) if e is not None and e.tier == 2 else None


def _reference_result(ref, t0: float) -> OpenResult:
    """Read-only: the reference fields and the entry; no preview, so no Apply."""
    e, view = ref
    return OpenResult(entry=_public(view), preview=None, branch=REFERENCE_BRANCH,
                      reference=D.reference_view(e, L.get().sources(e.key)), ms=_ms(t0))
```

In `copilot_open` and `copilot_preview`, after the `if pack is not None: return await _pack_result(...)` lines add:

```python
    ref = _reference(card.key)
    if ref is not None:
        return _reference_result(ref, t0)
```

In `_pack_result`, change the return to `return OpenResult(entry=_public(view), preview=prev, branch=PACK_BRANCH, reference=D.reference_view(e, sources), ms=_ms(t0))`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/ backend/tests/conftest.py backend/tests/test_copilot_matcher.py backend/tests/test_copilot_routes.py backend/tests/test_library_describe.py backend/tests/test_copilot_ask.py
git commit -m "feat(copilot): tier 2 library entries open as read-only reference cards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: A gate check for one pack folder (enables parallel pack authoring)

**Files:**
- Create: `backend/scripts/guidelines/check_pack.py`
- Test: `backend/tests/test_library_check_pack.py` (new)

**Interfaces:**
- Consumes: `bundle.compile_bundle(root)`, `bundle.guidelines_root()`, `bundle.BundleError` (existing).
- Produces: `check_pack.check(pack_dir: Path) -> int` (0 = gates 1–4 pass for that folder alone) and the CLI `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/check_pack.py <entry-id>`. Pack tasks (10–28) use it instead of rebuilding the shared bundle; only Task 29 rebuilds the bundle.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_library_check_pack.py`:

```python
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_pack", Path(__file__).resolve().parents[1] / "scripts" / "guidelines" / "check_pack.py")
CP = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(CP)


def test_a_good_pack_folder_passes_alone(toy_dir, capsys):
    assert CP.check(toy_dir / "toy-nodule") == 0
    assert "toy-nodule: gates 1-4 pass" in capsys.readouterr().out


def test_a_broken_pack_folder_fails_with_its_problems(toy_dir, capsys):
    e = json.loads((toy_dir / "toy-nodule" / "entry.json").read_text())
    e["outcomes"] = e["outcomes"][1:]                   # an outcome the rules still name
    (toy_dir / "toy-nodule" / "entry.json").write_text(json.dumps(e))
    assert CP.check(toy_dir / "toy-nodule") == 1
    assert "is not an outcome" in capsys.readouterr().out


def test_a_missing_folder_fails(tmp_path):
    assert CP.check(tmp_path / "nope") == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_check_pack.py -q`
Expected: FAIL — `FileNotFoundError` for `check_pack.py`.

- [ ] **Step 3: Implement**

Create `backend/scripts/guidelines/check_pack.py`:

```python
"""Gates 1–4 for one pack folder alone (library spec §8). Pack tasks run in parallel and never touch the shared
bundle; the integration task rebuilds it once. The folder is compiled from a temporary copy without its sources/.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/check_pack.py <entry-id>"""
import shutil
import sys
import tempfile
from pathlib import Path

from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BundleError, compile_bundle, guidelines_root


def check(pack_dir: Path) -> int:
    if not (pack_dir / "entry.json").exists():
        print(f"{pack_dir}: no entry.json")
        return 1
    with tempfile.TemporaryDirectory() as d:
        shutil.copytree(pack_dir, Path(d) / pack_dir.name, ignore=shutil.ignore_patterns("sources"))
        try:
            b = compile_bundle(Path(d))
        except BundleError as ex:
            print(ex)
            return 1
    print(f"{pack_dir.name}: gates 1-4 pass ({', '.join(sorted(b['entries']))})")
    return 0


if __name__ == "__main__":
    sys.exit(check(guidelines_root() / sys.argv[1]))
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_check_pack.py -q && PYTHONPATH=src .venv/bin/python scripts/guidelines/check_pack.py bts-pulmonary-nodule`
Expected: `3 passed`, then `bts-pulmonary-nodule: gates 1-4 pass (bts-pulmonary-nodule@2015.1)`.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/guidelines/check_pack.py backend/tests/test_library_check_pack.py
git commit -m "feat(library): gate check for one pack folder

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Pack tasks (10–28): the shared procedure

Tasks 10–28 author one pack each. They are independent: each writes **only** `guidelines/<id>/` and can run in parallel with the others (dispatch them concurrently once Tasks 1–9 are merged into the branch). None of them rebuilds the bundle or edits tests; Task 29 does that once. Every pack task follows this procedure in full; its own section adds only the pack's id, type, source and structure.

**REQUIRED SUB-SKILL for every pack task:** author with the project skill `/Users/hassan/Code/rapid_reports_ai/.claude/skills/guideline-pack/SKILL.md`. Read it and its `AUTHORING-RULES.md`, `TRAPS.md` and `SOURCES.md` before starting. Two overrides for this slice: run gates 1–4 with `check_pack.py` (skill step 5's `build_bundle.py` is for Task 29), and skip skill step 9's bundle rebuild and test run (Task 29 does it). The gate-2 cap is now 400,000 (Task 5), not the 200,000 TRAPS.md states.

**Sources.** A controller step (not a pack task) fetches the primary sources into `/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/sources3/<id>/` (CAD-RADS and CAC-DRS are already in `…/scratchpad/sources2/`). A pack task never fetches and never substitutes a secondary source (review, Radiopaedia, poster). If its source folder is missing, empty, or lacks the tables the pack needs, the task **stops and reports** the full citation and what is missing; Hassan supplies blocked sources.

**Procedure variants.**
- **Full** (tier 1 algorithm packs, Tasks 10–15): every skill step, including step 8's independent clinical read on the most capable model *and its re-check of the fixes*; every worked example in the source becomes a golden case.
- **Light** (tier 1 lookup packs, Tasks 16–23; tier 2 cards, Tasks 24–28): author, gates 1–4, gate 5 advisory, one independent read with no re-check unless it reports a Critical finding; escalate to Hassan only where the source is silent or ambiguous.

**Steps (every pack task):**

- [ ] **P1: Read the skill** (`SKILL.md`, `AUTHORING-RULES.md`, `TRAPS.md`, `SOURCES.md`).
- [ ] **P2: File the source.** `ls` the pack's source folder; if it is missing or lacks what the pack needs, STOP and report (see Sources). Otherwise, for each document: `shasum -a 256 <file>`, copy it to `guidelines/<id>/sources/<sha256>.<ext>`, extract text (`pdftotext -layout` for PDF; for PMC HTML use the provided `.txt` and view table images with the Read tool), and write `guidelines/<id>/manifest.json` (`id`, `role`, `title`, `issuer`, `edition`, `url` = DOI or publisher URL, `sha256`, `file`, `text_file`, `retrieved`).
- [ ] **P3: Author** `entry.json` (and `cases.json` for tier 1) to the pack's structure below, the skill's rules and every trap. Mark `scope` and `role` on every input; eligibility only from the source's own scope text (at most three, each to `does_not_apply` with the scope clause's locator); patient facts from the vocabulary (`known_primary_cancer`, `immunocompromised`, `screening_programme`, `age_years`, `sex`) where an input is one of them.
- [ ] **P4: Gates 1–4.** Run `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/check_pack.py <id>`. Expected: `<id>: gates 1-4 pass (<id>@<version>)`. Fix the entry, never a gate.
- [ ] **P5: Gate 5 (advisory).** Run `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/jev_evidence.py ../guidelines/<id> > ../guidelines/<id>/evidence.md`.
- [ ] **P6: `review.md`** per skill step 7 (checklist, gate 5 flags resolved, For Hassan only for what the source leaves open).
- [ ] **P7: Independent read** per the task's variant (skill step 8). Fix every Critical and Important finding.
- [ ] **P8: Commit the pack folder only.**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot
git add guidelines/<id>
git status --short guidelines/<id> | grep sources && echo "STOP: sources must stay ignored"
git commit -m "data(library): <display> pack

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(Parallel tasks share one index: if `git commit` reports `index.lock`, wait a few seconds and retry the add and commit.)

- [ ] **P9: Report** to the controller: the pack key, the gate result, the For Hassan items, any blocked or incomplete source, and **skill friction** (any step of the `guideline-pack` skill that was unclear, wrong for this pack type, or missing something you needed).

**Acceptance (every pack):** `check_pack.py` passes; every rule, row, band, input and outcome cites a page/section/table of a `primary` or `amendment` source; wording is our own and keeps the source's hedges; tier 1: every outcome has a golden case and every band edge is tested both sides; tier 2: every grade or component of the source's table is in `reference.tables` cell for cell, with no management the source does not give; `review.md` exists; the independent read has no open Critical or Important finding.

---

### Task 10: BTA U-grading (thyroid ultrasound) — tier 1 algorithm, full procedure

**Files:** Create `guidelines/bta-thyroid-u-grading/` (`entry.json`, `manifest.json`, `cases.json`, `evidence.md`, `review.md`). Source: `…/scratchpad/sources3/bta-thyroid-u-grading/` (British Thyroid Association guidelines for the management of thyroid cancer, the U classification of thyroid nodules on ultrasound and its FNA recommendation).

**Structure:** the U grade (U1–U5) as the source defines it from ultrasound features: either a dictated-grade `enum` input (when the source's table is grade → action) or feature inputs mapped by `rules`/`table` to the grade, whichever the source's own table encodes; outcomes are the grade with its FNA/management recommendation. `applies_to`: region `neck`, modality `US`, finding_type `thyroid nodule`. Eligibility only from the source's scope text.

**Interfaces:** Consumes the Pack procedure, `check_pack.py` (Task 9) and the schema of Tasks 2 and 4. Produces `bta-thyroid-u-grading@<edition>.1` (tier 1) for Task 29.

- [ ] Follow steps P1–P9 (Full variant).

---

### Task 11: ESE 2023 adrenal incidentaloma — tier 1 algorithm, full procedure

**Files:** Create `guidelines/ese-adrenal-incidentaloma/`. Source: `…/sources3/ese-adrenal-incidentaloma/` (European Society of Endocrinology clinical practice guideline on adrenal incidentalomas, 2023, with ENSAT).

**Structure:** inputs for the imaging features the source's imaging algorithm uses (e.g. unenhanced attenuation as a `number` in HU banded at the source's edges, size, homogeneity; a washout input only if the source still uses it); outcomes are the source's imaging conclusions and follow-up/work-up recommendations. Biochemical work-up the guideline requires for every incidentaloma is a caveat on each outcome, not an input. `applies_to`: region `abdomen`, modality `CT`/`MRI` as the source covers, finding_type `adrenal mass`. Eligibility from the source's scope (e.g. its stated exclusions of known malignancy or young patients, if it states them; at most three).

**Interfaces:** as Task 10. Produces `ese-adrenal-incidentaloma@<edition>.1`.

- [ ] Follow steps P1–P9 (Full variant).

---

### Task 12: RCOG ovarian masses in premenopausal women (GTG 62) — tier 1 algorithm, full procedure

**Files:** Create `guidelines/rcog-ovarian-mass-premenopausal/`. Source: `…/sources3/rcog-ovarian-mass-premenopausal/` (RCOG Green-top Guideline No. 62, and the IOTA rules document where GTG 62 adopts IOTA simple rules).

**Structure:** the inputs GTG 62's ultrasound pathway uses; where GTG 62 adopts the IOTA simple rules, the IOTA B- and M-features are boolean inputs and a `rules` step gives benign / malignant / inconclusive exactly as IOTA defines it (cite the IOTA document as `primary` only if GTG 62 formally adopts it, and say so in For Hassan); outcomes are GTG 62's management and referral recommendations. Eligibility: premenopausal status from the source's scope (patient-scoped). `topic` shared with Task 13 so the two appear side by side. `applies_to`: region `pelvis`, modality `US`, finding_type `ovarian mass`.

**Interfaces:** as Task 10. Produces `rcog-ovarian-mass-premenopausal@<edition>.1`.

- [ ] Follow steps P1–P9 (Full variant).

---

### Task 13: RCOG ovarian cysts in postmenopausal women — tier 1 algorithm, full procedure

**Files:** Create `guidelines/rcog-ovarian-mass-postmenopausal/`. Source: `…/sources3/rcog-ovarian-mass-postmenopausal/` (the RCOG guidance on ovarian cysts in postmenopausal women; IOTA as in Task 12 where RCOG adopts it).

**Structure:** the inputs RCOG's postmenopausal pathway uses (ultrasound morphology or IOTA features as RCOG adopts them; the risk-of-malignancy index only if RCOG's pathway computes it, then as `score` with the published formula and inputs including CA-125 as a patient-scoped number); outcomes are RCOG's management and referral recommendations. Eligibility: postmenopausal status (patient-scoped). Same `topic` as Task 12. `applies_to` as Task 12.

**Interfaces:** as Task 10. Produces `rcog-ovarian-mass-postmenopausal@<edition>.1`.

- [ ] Follow steps P1–P9 (Full variant).

---

### Task 14: PI-RADS v2.1 — tier 1 algorithm, full procedure

**Files:** Create `guidelines/pi-rads-2-1/`. Source: `…/sources3/pi-rads-2-1/` (PI-RADS v2.1, ACR–ESUR–AdMeTech, 2019).

**Structure:** zone (`enum`: peripheral / transition, as the source defines), the dominant-sequence score (DWI for PZ, T2W for TZ) and the secondary sequence scores as `enum` 1–5 inputs, DCE as positive/negative with a prerequisite on the zone/score path where the source uses it; `rules`/`table` steps give the overall PI-RADS category exactly per the source's assessment tables; outcomes are the category with its stated likelihood of clinically significant cancer. No biopsy recommendation the source does not give. `applies_to`: region `pelvis`, modality `MRI`, finding_type `prostate lesion`.

**Interfaces:** as Task 10. Produces `pi-rads-2-1@<edition>.1`.

- [ ] Follow steps P1–P9 (Full variant).

---

### Task 15: NHS AAA screening surveillance — tier 1 algorithm, full procedure

**Files:** Create `guidelines/nhs-aaa-surveillance/`. Source: `…/sources3/nhs-aaa-surveillance/` (UKHSA NHS Abdominal Aortic Aneurysm Screening Programme standard operating procedures / surveillance and referral thresholds).

**Structure:** maximum aortic diameter as a `number` (the measurement plane and unit the programme uses, in `how_stated`), banded at the programme's thresholds; outcomes are the programme's surveillance intervals and referral routes. Eligibility from the programme's own scope (it is a screening programme: the context in which it applies, e.g. `screening_programme` fact, at most three inputs). `applies_to`: region `abdomen`, modality `US`, finding_type `abdominal aortic aneurysm`, context `screening`.

**Interfaces:** as Task 10. Produces `nhs-aaa-surveillance@<edition>.1`.

- [ ] Follow steps P1–P9 (Full variant).

---

### Task 16: CAD-RADS 2.0 — tier 1 lookup, light procedure

**Files:** Create `guidelines/cad-rads-2/`. Source: already fetched in `/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/sources2/` (`cadrads_pmc.html`, `cadrads_pmc.txt`, `cadrads_ryct.220183.tbl*.jpg`: the *Radiology: Cardiothoracic Imaging* co-publication, PMC full text and table images; record the DOI as `url`).

**Structure:** the first clinical input is the dictated CAD-RADS category (`enum`, `scope: "lesion"`, the source's categories as options); one `table` step to outcomes (category meaning in our words and the source's management recommendation); a modifier input only if the source's management table keys a recommendation on it. `applies_to`: region `heart`, modality `CT`, finding_type `coronary stenosis`.

**Interfaces:** as Task 10. Produces `cad-rads-2@<edition>.1`.

- [ ] Follow steps P1–P9 (Light variant).

---

### Task 17: CAC-DRS — tier 1 lookup, light procedure

**Files:** Create `guidelines/cac-drs/`. Source: already fetched in `…/scratchpad/sources2/` (`cacdrs.pdf`, `cacdrs.txt`; Hecht et al., *JCCT* 2018;12:185–191, DOI `10.1016/j.jcct.2018.03.008`).

**Structure:** the first clinical input is the dictated CAC-DRS category (`enum`, `scope: "lesion"`, the source's categories); one `table` step to outcomes (risk statement and management recommendation, hedges kept). The Agatston bands that define the categories go into `reference.tables`, not logic. A vessel-count modifier becomes an input only if the source keys a recommendation on it. `applies_to`: region `heart`, modality `CT`, finding_type `coronary calcification`.

**Interfaces:** as Task 10. Produces `cac-drs@<edition>.1`.

- [ ] Follow steps P1–P9 (Light variant).

---

### Tasks 18–23: Lookup packs for dictated grades — tier 1 lookup, light procedure

Each is its own task, with its own folder and its own source folder `…/scratchpad/sources3/<id>/`. **Structure for all six:** the first clinical input is the grade or score the radiologist dictates (`enum` of the source's grades, `scope: "lesion"`; a `number` banded at the source's edges when the source defines a numeric score); one `table` (or `band` + `rules`) step to one outcome per grade; each outcome states the grade's meaning in our words and, **only where the source gives it**, the management or prognosis line (otherwise the recommendation is empty: a lookup pack never invents management). If the source gives no management for any grade, stop and report: the system belongs in tier 2 instead (Hassan decides). Interfaces as Task 10; each produces `<id>@<edition>.1` for Task 29. Follow steps P1–P9 (Light variant).

| Task | id | System | `applies_to` (region / modality / finding_type) |
|---|---|---|---|
| 18 | `kellgren-lawrence` | Kellgren–Lawrence osteoarthritis grading | the joint regions the source covers / `XR` / `osteoarthritis` |
| 19 | `garden-hip-fracture` | Garden classification of intracapsular femoral neck fractures | `hip` / `XR` / `femoral neck fracture` |
| 20 | `weber-ankle` | Danis–Weber ankle fracture classification | `ankle` / `XR` / `ankle fracture` |
| 21 | `salter-harris` | Salter–Harris physeal fracture classification | as the source / `XR` / `physeal fracture` |
| 22 | `fazekas` | Fazekas white matter hyperintensity scale | `head` / `MRI` / `white matter hyperintensities` |
| 23 | `aspects` | Alberta Stroke Program Early CT Score | `head` / `CT` / `acute ischaemic stroke` |

---

### Tasks 24–28: Tier 2 reference cards — light procedure

Each is its own task (folder `guidelines/<id>/`, source `…/scratchpad/sources3/<id>/`). **Structure for all five:** `tier: 2`; no `inputs`, `logic`, `result`, `outcomes` or `cases.json`; `reference.summary` (3–5 lines), `reference.definitions` (one per grade or component), `reference.tables` (the source's grading or scoring table as rows and cells, every row as wide as `columns`), `reference.pitfalls` (scope limits and misuse the source names); every field has a locator; `aliases` include how reports name the system; `applies_to.finding_type` names the graded finding (the pack gate's question uses it). No management the source does not give. Served read-only by Task 8. Interfaces as Task 10; each produces `<id>@<edition>.1` (tier 2) for Task 29. Follow steps P1–P9 (Light variant).

| Task | id | System | Primary source (the controller fetches; the source wins) |
|---|---|---|---|
| 24 | `ao-spine-thoracolumbar` | AO Spine thoracolumbar injury classification | Vaccaro AR et al., *Spine* 2013;38:2028–2037 |
| 25 | `sins` | Spinal Instability Neoplastic Score | Fisher CG et al., *Spine* 2010;35:E1221–E1229 |
| 26 | `stoller-meniscus` | Stoller MRI meniscal signal grading | Stoller DW et al., *Radiology* 1987;163:731–735 |
| 27 | `outerbridge` | Outerbridge cartilage grading | Outerbridge RE, *J Bone Joint Surg Br* 1961;43-B:752–757, DOI `10.1302/0301-620x.43b4.752` |
| 28 | `lund-mackay` | Lund–Mackay CT sinus staging | Lund VJ, Mackay IS, *Rhinology* 1993;31:183–184 |

---

### Task 29: Integration — rebuild the bundle and test every new pack

**Files:**
- Modify: `backend/src/rapid_reports_ai/resources/guideline_bundle.json`
- Create: `backend/tests/test_library_new_packs.py`

**Interfaces:**
- Consumes: every pack committed by Tasks 10–28 (a pack that stopped on a blocked source is simply absent); Task 8's tier 2 serving.
- Produces: the rebuilt bundle; tests that hold each pack type to its shape.

- [ ] **Step 1: List what was authored**

Run: `cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/scratchpad-copilot && ls guidelines/ && git log --oneline c412632..HEAD -- guidelines | head -40`
Expected: one folder and one commit per completed pack task. Note which pack tasks stopped (blocked sources) from their reports.

- [ ] **Step 2: Write the tests**

Create `backend/tests/test_library_new_packs.py`, then edit the three lists so each holds exactly the ids that were authored:

```python
import json

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY

ALGORITHM = ["bta-thyroid-u-grading", "ese-adrenal-incidentaloma", "rcog-ovarian-mass-premenopausal",
             "rcog-ovarian-mass-postmenopausal", "pi-rads-2-1", "nhs-aaa-surveillance"]
LOOKUP = ["cad-rads-2", "cac-drs", "kellgren-lawrence", "garden-hip-fracture", "weber-ankle", "salter-harris",
          "fazekas", "aspects"]
TIER2 = ["ao-spine-thoracolumbar", "sins", "stoller-meniscus", "outerbridge", "lund-mackay"]


def _lib():
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _eligible(e) -> dict:
    """Eligibility booleans name the exclusion (true leads to does_not_apply), so false is in scope."""
    return {i.id: False for i in e.inputs if i.role == "eligibility" and i.type == "boolean"}


@pytest.mark.parametrize("pack_id", ALGORITHM + LOOKUP)
def test_a_tier1_pack_is_current_scoped_and_eligibility_bounded(pack_id):
    e = _lib().lookup(pack_id)
    assert e is not None and e.tier == 1 and e.status == "current"
    elig = [i for i in e.inputs if i.role == "eligibility"]
    assert len(elig) <= 3 and all(i.locator is not None for i in elig)
    assert (e.outcome(DOES_NOT_APPLY) is not None) == bool(elig)


@pytest.mark.parametrize("pack_id", LOOKUP)
def test_a_lookup_pack_reads_one_dictated_grade(pack_id):
    e = _lib().lookup(pack_id)
    cat = next(i for i in e.inputs if i.role == "clinical")
    assert cat.type in ("enum", "number") and cat.scope == "lesion" and cat.how_stated and cat.locator is not None
    if cat.type == "enum":
        modifiers = {i.id for i in e.inputs if i.role == "clinical" and i.id != cat.id}
        for opt in cat.options:
            t = E.evaluate(e, {**_eligible(e), cat.id: opt})
            if t.outcome is None:
                assert t.needed and set(t.needed) <= modifiers, (opt, t.needed)
            else:
                assert t.outcome != DOES_NOT_APPLY and e.outcome(t.outcome).classification, opt


@pytest.mark.parametrize("entry_id", TIER2)
def test_a_reference_card_is_read_only_and_located(entry_id):
    e = _lib().lookup(entry_id)
    assert e is not None and e.tier == 2 and not e.inputs and not e.logic and not e.outcomes
    r = e.reference
    assert r.summary and r.definitions and r.tables and all(f.locator is not None for f in r.fields())
    assert all(len(row) == len(t.columns) for t in r.tables for row in t.rows)
    assert e.applies_to.finding_type and e.aliases
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_new_packs.py -q`
Expected: FAIL — the packs are not in the committed bundle yet (`assert None is not None`).

- [ ] **Step 4: Rebuild the bundle**

Run: `cd backend && time PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py`
Expected: `wrote …/guideline_bundle.json (N entries)` with N = 3 + the packs authored. A problem here that `check_pack.py` did not show (a duplicate key or alias across packs) goes back to the pack's owner task, fixed in its folder.

- [ ] **Step 5: Run every library and copilot test**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py --check && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py tests/test_copilot_*.py -q`
Expected: `bundle up to date`, all pass (the Ask material size test in `test_library_describe.py` now covers every pack; if a pack exceeds `PACK_MATERIAL_MAX`, raise it in `ask.py` and say so in the commit).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/resources/guideline_bundle.json backend/tests/test_library_new_packs.py backend/src/rapid_reports_ai/hybrid_stack/copilot/ask.py
git commit -m "data(library): bundle with the next-slice packs; shape tests per pack type

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 30: Spec §12 results and the handover note

**Files:**
- Modify: `docs/superpowers/specs/2026-10-12-guideline-library-design.md` (§3.6 and §7.4 status lines, §12)
- Create: `docs/superpowers/handover/2026-10-13-guideline-library-next-slice-handover.md`

**Interfaces:**
- Consumes: the commits of Tasks 1–29, `preview_lab_next_slice.md` (Task 7), the pack task reports (For Hassan, blocked sources, skill friction).
- Produces: the spec and handover the next session starts from.

- [ ] **Step 1: Update the spec**

- §3.6: replace "Not built yet: it is part of the next slice (§12)." with "Built in the next slice (§12): `scope`, `role`, `fact` (vocabulary `known_primary_cancer`, `immunocompromised`, `screening_programme`, `age_years`, `sex`) and `dims` on inputs; the gates enforce at most three eligibility inputs, each with a locator and a `does_not_apply` outcome."
- §7.4: replace "Not built yet: it is part of the next slice." with "Built in the next slice: `Preview.state`, `Preview.exclusion` (the reason; never Apply-able), eligibility asks first, shared answers via the request's `patient` map. The frontend strip and chip logging are not built."
- §12 "Next slice": replace item 5 with the scope Hassan set on 2026-10-12 (5a UK algorithm packs: BTA U-grading, ESE 2023 adrenal, RCOG premenopausal GTG 62 and postmenopausal, PI-RADS v2.1, NHS AAA surveillance; 5b CAD-RADS 2.0 and CAC-DRS lookups; 5c Kellgren–Lawrence, Garden, Weber, Salter–Harris, Fazekas, ASPECTS lookups; 5d tier 2 cards for AO Spine thoracolumbar, SINS, Stoller, Outerbridge, Lund–Mackay). Then add a "Status" paragraph: one line per item (1–5, and per pack for 5) as DONE / FAILED / BLOCKED (source) with commit SHAs from `git log --oneline c412632..HEAD`, and for item 4 the lab's gate line with MISS p95 and HIT p95 from `preview_lab_next_slice.md`. Add the decisions this slice made: Fleischner's age split out of the combined exclusion so one age answer serves both nodule cards; one batched Jev call per scope (two at most, concurrent); the cache key adds the whole dictation; ranges and fractions give no number; months and years never convert to days; `MAX_VERIFY` 400,000; packs authored in parallel with `check_pack.py` and one integration rebuild.

- [ ] **Step 2: Write the handover**

Create `docs/superpowers/handover/2026-10-13-guideline-library-next-slice-handover.md` with sections: **State** (branch, HEAD, test count from the last full run, bundle version and entry count); **What changed** (one line per task); **The Apply gate** (lab result, and whether the frontend may now start Apply); **Frontend contract** (`finding`, `findings` = the `dictation` sent to /match, `patient` map keyed by fact, `answered`; `Preview.state`, `exclusion`, `asks[].role/fact`, `Settled.fact`; tier 2 cards: `Card.reference`, `OpenResult.reference`, no preview; eligibility chip taps and `does_not_apply` to be logged in the stack log); **For Hassan** (every For Hassan line from the pack `review.md` files of Tasks 5 and 10–28; every blocked source with its citation); **Skill friction** (the pack tasks' reports, grouped, with proposed edits to the `guideline-pack` skill, including TRAPS.md's gate-2 cap 200,000 → 400,000 and the `check_pack.py` step); **Next** (frontend Tasks 14–19 if the gate passed).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-12-guideline-library-design.md docs/superpowers/handover/2026-10-13-guideline-library-next-slice-handover.md
git commit -m "docs(library): next slice results and handover

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.**
- §12 next slice 1 (per-finding settling, `finding`, verbatim lesion quotes, code-read numbers with one table, batched Jev "the FINDING states …"): Tasks 2–3. Scope marked on every input of the three packs: Task 3 Step 5.
- §12 next slice 2 / §3.6 / §7.4 (role, ≤3 eligibility with locators, does_not_apply with citation and no Apply, state computed in code, eligibility asks first, shared patient facts, packs reclassified, golden cases, bundle): Tasks 4–5. Logging: backend logs `does_not_apply`; chip taps are frontend (handover).
- §12 next slice 3 (cache by pack, unit text, history, answered; run at card time; open instant): Task 6 (the key also holds the dictation and patient map).
- §12 next slice 4 (lab with history, two lesions in one sentence, eligibility exclusions, shared answers; per-finding; ≤2 runs; stop on a wrong proposal; miss/hit latency apart): Task 7.
- §12 next slice 5, as rescoped by Hassan: tier 2 serving (Task 8); 5a UK algorithm packs, full procedure (Tasks 10–15); 5b CAD-RADS 2.0 and CAC-DRS lookups from `sources2/` (Tasks 16–17); 5c dictated-grade lookups (Tasks 18–23); 5d tier 2 cards after those (Tasks 24–28); each pack task uses the `guideline-pack` skill, stops on a missing source, reports skill friction, writes only its own folder (parallel-safe via `check_pack.py`, Task 9); one integration rebuild (Task 29).
- Deferred minors (value validation behind an unknown prerequisite, `_short`, "1 count"): Task 1.
- Spec §12 update and handover: Task 30.
- "Don't build": none of the listed items appears in any task.

**Placeholder scan.** Code steps carry complete code. Data-authoring tasks (5, 10–28) give fixed structure, acceptance criteria, exact commands and the shared procedure; clinical values come from the sources, as the brief requires. Task 7's new cases are exact; their expectations are confirmed by `--check` against the engine before any model call. The pack tasks reference the shared "Pack tasks" procedure section by name (a deliberate exception for leanness, asked for by Hassan): every pack task must read that section in full.

**Type consistency.** `preview_pack(e, findings, history, answered, sources=None, finding="", patient=None)` is used the same way in routes (Tasks 3, 4, 6), the cache prewarm (Task 6) and the lab (Task 7). `_given(e, answered, patient=None)` (Task 4) is used by Task 5's tests and Task 7's `--check`. `_asks(e, t, sources, needed)` from Task 3 is extended in Task 4. `PC.key(...)` and `PC.start(k, make)` match across Tasks 6–7. `check_pack.check(pack_dir)` (Task 9) is the gate command of every pack task. `DOES_NOT_APPLY`, `FACTS`, `REFERENCE_BRANCH`, `Card.reference`, `OpenResult.reference`, `Preview.state/exclusion/degraded`, `Settled.fact` are each defined once and named the same everywhere.

**Review Focus.** Each of the five lines has its test in its owning task: ranges/fractions (Task 2), unparseable patient answers (Task 4), one-scope Jev failure (Task 3), two findings sharing a pack (Task 6 key test), degraded previews not re-served (Task 6).
