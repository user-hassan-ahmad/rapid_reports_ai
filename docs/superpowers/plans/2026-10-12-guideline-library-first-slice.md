# Guideline Library: First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the curated guideline library's schema and engine on Fleischner 2017, Bosniak 2019, BTS 2015 and all of UICC TNM 9, rewire the Copilot preview onto the engine, and run the catalogue research and coverage lab that set the authoring order.

**Architecture:** Entries live as JSON under `guidelines/<entry-id>/` at the repo root. A build step runs the quality gates and compiles them into one versioned bundle (`backend/src/rapid_reports_ai/resources/guideline_bundle.json`), which the backend loads into memory. A pure-Python engine evaluates an entry's data-only logic and returns a trace. The Copilot preview for a pack becomes: the model settles inputs with verbatim quotes, code checks them, the engine evaluates, and every word of the proposal comes from the entry. Nothing calls the web at request time.

**Tech Stack:** Python 3, pydantic v2, pytest + pytest-asyncio (`asyncio_mode = "auto"`), FastAPI routes (existing), Qwen on Cerebras via `_run_agent_with_model`, Jev via `jev_post`, `pdftotext` (Homebrew, authoring only).

**Spec:** `docs/superpowers/specs/2026-10-12-guideline-library-design.md` (read it first). Context: `docs/superpowers/specs/2026-10-12-scratchpad-copilot-design.md` (the front half that stands) and `docs/superpowers/handover/2026-10-12-scratchpad-copilot-handover.md`.

All paths below are relative to the worktree root `.claude/worktrees/scratchpad-copilot/` unless they start with `/`.

## Global Constraints

- No retrieval or web calls at request time. External calls only at authoring time and in labs (spec §2.9).
- Facts are written in our own words, with citations and links; no long verbatim passages or figures copied into entries (spec §2.8).
- Tier 1 logic and tables are written by hand from the primary source (spec §9.2). Never generate them with a parser or a model.
- One entry has exactly one issuing body. Sources from different bodies are never merged (spec §2.3).
- Rules, tables and prerequisites never compare numbers: a number is banded first, so every entry is enumerable (spec §3.2).
- Tables have no default rows (spec §3.2). Bands cover the whole number line exactly (spec §3.2).
- The model only settles inputs; code evaluates; the model writes no report text for a pack (spec §4).
- Jev judges meaning; code only removes things or checks deterministic facts (copilot spec §5 decisions).
- Prompts are case-agnostic: structural wording or multi-domain breadth, never single-domain clinical examples.
- British English in all user-facing text.
- Run tests with `cd backend && PYTHONPATH=src .venv/bin/pytest …` (the editable install points at the main checkout; `PYTHONPATH=src` is required).
- Labs and scripts load keys with `load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")` (the worktree has no `.env`; the shell cannot `source` it). Any lab that writes to a database first asserts `DATABASE_URL` is localhost.
- Lab economy: at most 2 runs, reuse outputs, include the process id in output filenames, keep raw outputs in the session scratchpad, keep the hand read.
- Prod data may be read for analysis (standing permission); raw prod content stays in the scratchpad, never committed.
- Tests live flat in `backend/tests/` as `test_library_*.py` (the repo's convention). Shared library fixtures go in `backend/tests/conftest.py`.

## Review Focus

1. **Centimetres dictated against a millimetre input** ("1.2 cm nodule"): the settled value must be 12, and a model value that is ten times a millimetre figure in the quote ("12 mm" settled as 120) must be rejected. Pinned in Task 11.
2. **A value exactly on a band edge** (6 mm, 8 mm, 5.5 mm under rounding edges): it must land on the side the source states. Pinned in Task 2 (engine) and in every entry's golden cases (Tasks 8–10).
3. **The radiologist's answer disagrees with what the model settled**: the answer wins, and the quote shown is cleared. Pinned in Task 11.
4. **A state the input does not allow** ("absent" for an input without it, or "not assessable" where the source has no such category): the value is dropped and the input is asked. Pinned in Task 2 (engine raises) and Task 11 (preview drops it).
5. **The bundle is missing or corrupt at startup**: the app still runs and the Copilot simply shows no pack cards. Pinned in Task 5.

---

### Task 1: Entry schema

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/__init__.py`
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py`
- Modify: `backend/tests/conftest.py` (append the toy fixtures)
- Test: `backend/tests/test_library_schema.py`

**Interfaces:**
- Produces: `schema.Entry`, `InputDef`, `Cond`, `All`, `AnyOf`, `NoneOf`, `CountGte`, `Expr`, `Num`, `Band`, `BandStep`, `DeriveStep`, `ScoreStep`, `Term`, `TableStep`, `Row`, `RulesStep`, `Case`, `AdjustStep`, `Outcome`, `Reference`, `RefText`, `RefTable`, `AppliesTo`, `Locator`, `SourceDoc`, `Manifest`, `InputValue`, `GoldenCase`, `Cases`, `FACT_ROLES`, `conds(expr) -> list[Cond]`, `as_value(x) -> InputValue`. `Entry.key` is `f"{id}@{version}"`; `Entry.input(id)`, `Entry.step(id)`, `Entry.outcome(id)` return the item or `None`.
- Produces (tests): fixtures `toy` (dict), `toy_entry` (Entry), `manifest` (Manifest), `cases` (Cases), `toy_dir` (Path to a temp `guidelines/` folder holding `toy-nodule/`).

- [ ] **Step 1: Add the toy fixtures to `backend/tests/conftest.py`**

Append at the end of the file:

```python
# ── guideline library: a toy tier 1 entry shared by the test_library_* files ────────────────────────────────────
import copy as _copy
import json as _json

_L1 = {"source": "S1", "page": 2}
TOY_ENTRY = {
    "id": "toy-nodule", "version": "1.0", "topic": "toy-nodule", "issuer": "TOY", "system": "Toy nodule guideline",
    "display": "Toy 2020", "edition": "2020", "tier": 1,
    "applies_to": {"region": ["chest"], "modality": ["CT"], "finding_type": ["nodule"], "context": ["incidental"]},
    "aliases": ["toy nodule", "toy guideline"],
    "inputs": [
        {"id": "kind", "label": "Nodule type", "type": "enum", "options": ["solid", "subsolid"]},
        {"id": "size", "label": "Diameter", "type": "number", "unit": "mm", "how_stated": "diameter in mm"},
        {"id": "risk", "label": "Patient risk", "type": "enum", "options": ["low", "high"],
         "prerequisites": [{"ref": "kind", "eq": "solid"}]},
        {"id": "margin", "label": "Margin", "type": "enum", "options": ["smooth", "spiculated"],
         "states": ["not_assessable"]},
    ],
    "logic": [
        {"step": "band", "id": "size_band", "ref": "size", "locator": _L1, "bands": [
            {"id": "lt6", "label": "<6 mm", "max": 6},
            {"id": "6to8", "label": "6-8 mm", "min": 6, "max": 8, "max_inclusive": True},
            {"id": "gt8", "label": ">8 mm", "min": 8, "min_inclusive": False}]},
        {"step": "rules", "id": "plan", "cases": [
            {"when": {"ref": "kind", "eq": "subsolid"}, "result": "subsolid", "locator": {"source": "S1", "page": 3}},
            {"when": {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "lt6"}]},
             "result": "none", "locator": {"source": "S1", "page": 3}},
            {"when": {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "6to8"},
                              {"ref": "risk", "eq": "low"}]}, "result": "ct12", "locator": {"source": "S1", "page": 3}},
            {"when": {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "6to8"},
                              {"ref": "risk", "eq": "high"}]}, "result": "ct6", "locator": {"source": "S1", "page": 3}},
            {"when": {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "gt8"}]},
             "result": "pet", "locator": {"source": "S1", "page": 3}}]},
    ],
    "result": "plan",
    "outcomes": [
        {"id": "subsolid", "classification": "subsolid nodule", "recommendation": "CT in 12 months", "locator": _L1},
        {"id": "none", "classification": "solid nodule {size_band}", "recommendation": "No follow-up", "locator": _L1},
        {"id": "ct12", "classification": "solid nodule {size_band}, {risk} risk", "recommendation": "CT at 12 months",
         "locator": _L1},
        {"id": "ct6", "classification": "solid nodule {size_band}, {risk} risk", "recommendation": "CT at 6 months",
         "locator": _L1},
        {"id": "pet", "classification": "solid nodule {size_band}", "recommendation": "PET-CT", "locator": _L1},
    ],
    "reference": {"summary": [{"id": "sum.1", "text": "A toy guideline for tests.", "locator": {"source": "S2"}}]},
}
TOY_MANIFEST = {"sources": [
    {"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY", "edition": "2020",
     "url": "https://example.org/toy", "file": "sources/abc.pdf", "text_file": "sources/abc.txt"},
    {"id": "S2", "role": "explanatory", "title": "Toy review", "issuer": "Other", "edition": "2021"}]}
TOY_CASES = {"cases": [
    {"name": "subsolid", "origin": "ours", "inputs": {"kind": "subsolid", "size": 7}, "outcome": "subsolid"},
    {"name": "solid small", "origin": "ours", "inputs": {"kind": "solid", "size": 5.9}, "outcome": "none"},
    {"name": "edge 6 low", "origin": "ours", "inputs": {"kind": "solid", "size": 6, "risk": "low"}, "outcome": "ct12"},
    {"name": "edge 8 high", "origin": "ours", "inputs": {"kind": "solid", "size": 8, "risk": "high"}, "outcome": "ct6"},
    {"name": "just over 8", "origin": "ours", "inputs": {"kind": "solid", "size": 8.1}, "outcome": "pet"},
    {"name": "risk unknown", "origin": "ours", "inputs": {"kind": "solid", "size": 7}, "outcome": None,
     "needed": ["risk"]},
]}


@pytest.fixture
def toy():
    return _copy.deepcopy(TOY_ENTRY)


@pytest.fixture
def toy_entry(toy):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    return Entry.model_validate(toy)


@pytest.fixture
def manifest():
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Manifest
    return Manifest.model_validate(_copy.deepcopy(TOY_MANIFEST))


@pytest.fixture
def cases():
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Cases
    return Cases.model_validate(_copy.deepcopy(TOY_CASES))


@pytest.fixture
def toy_dir(tmp_path, toy):
    d = tmp_path / "guidelines" / "toy-nodule"
    d.mkdir(parents=True)
    (d / "entry.json").write_text(_json.dumps(toy))
    (d / "manifest.json").write_text(_json.dumps(TOY_MANIFEST))
    (d / "cases.json").write_text(_json.dumps(TOY_CASES))
    return tmp_path / "guidelines"
```

If `pytest` is not already imported at the top of `conftest.py`, add `import pytest` there.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_library_schema.py`:

```python
import pytest
from pydantic import ValidationError

from rapid_reports_ai.hybrid_stack.copilot.library import schema as S


def test_toy_validates_and_has_a_key(toy_entry):
    assert toy_entry.key == "toy-nodule@1.0"
    assert toy_entry.input("risk").prerequisites[0].eq == "solid"
    assert toy_entry.step("plan").cases[2].result == "ct12"
    assert toy_entry.outcome("pet").recommendation == "PET-CT"
    assert toy_entry.input("nope") is None and toy_entry.step("nope") is None


def test_cond_needs_exactly_one_test():
    assert S.Cond.model_validate({"ref": "x", "in": ["a", "b"]}).in_ == ["a", "b"]
    assert S.Cond.model_validate({"ref": "x", "eq": False}).eq is False
    with pytest.raises(ValidationError):
        S.Cond.model_validate({"ref": "x", "eq": "a", "state": "absent"})
    with pytest.raises(ValidationError):
        S.Cond.model_validate({"ref": "x"})


def test_expr_shapes_parse():
    e = S.RulesStep.model_validate({"step": "rules", "id": "r", "cases": [
        {"when": {"count_gte": 2, "of": [{"ref": "a", "eq": 1}, {"none": [{"ref": "b", "state": "absent"}]},
                                         {"any": [{"ref": "c", "eq": True}]}]}, "result": "x"}]})
    assert sorted(c.ref for c in S.conds(e.cases[0].when)) == ["a", "b", "c"]
    assert e.refs() == ["a", "b", "c"]


def test_tier_rules(toy):
    bad = {**toy, "logic": []}
    with pytest.raises(ValidationError):
        S.Entry.model_validate(bad)
    with pytest.raises(ValidationError):
        S.Entry.model_validate({**toy, "tier": 2})
    t2 = {k: v for k, v in toy.items() if k not in ("logic", "outcomes", "result", "inputs")}
    assert S.Entry.model_validate({**t2, "tier": 2}).tier == 2


def test_options_only_for_enums():
    with pytest.raises(ValidationError):
        S.InputDef.model_validate({"id": "a", "label": "A", "type": "enum"})
    with pytest.raises(ValidationError):
        S.InputDef.model_validate({"id": "a", "label": "A", "type": "number", "options": ["1"]})


def test_unknown_fields_are_rejected(toy):
    toy["logic"][1]["default"] = "none"          # no default rows, structurally
    with pytest.raises(ValidationError):
        S.Entry.model_validate(toy)


def test_num_arity_and_step_kind():
    with pytest.raises(ValidationError):
        S.Num.model_validate({"op": "ln", "args": []})
    with pytest.raises(ValidationError):
        S.Num.model_validate({"op": "add", "args": [{"const": 1}]})
    assert S.Num.model_validate({"op": "div", "args": [{"ref": "a"}, {"const": 2}]}).refs() == ["a"]
    with pytest.raises(ValidationError):
        S.RulesStep.model_validate({"step": "magic", "id": "r", "cases": []})


def test_as_value():
    assert S.as_value(7) == S.InputValue(value=7)
    assert S.as_value({"state": "absent"}) == S.InputValue(state="absent")
    assert S.as_value({"band": "6to8"}).band == "6to8"
    iv = S.InputValue(value="x")
    assert S.as_value(iv) is iv
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.hybrid_stack.copilot.library'`.

- [ ] **Step 4: Write the schema**

`backend/src/rapid_reports_ai/hybrid_stack/copilot/library/__init__.py`:

```python
"""The curated guideline library (docs/superpowers/specs/2026-10-12-guideline-library-design.md)."""
```

`backend/src/rapid_reports_ai/hybrid_stack/copilot/library/schema.py`:

```python
"""The guideline library's entry model (library spec §3). An entry is data only: typed inputs, a pipeline of
data-only logic steps, outcomes and reference fields, every fact carrying a locator into its manifest's sources.
Numbers are never compared in a rule: a band step turns them into band ids first, so every entry is enumerable."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

State = Literal["present", "absent", "unknown", "not_assessable", "not_applicable"]
OptState = Literal["absent", "not_assessable"]      # states an input may allow besides present and unknown
Role = Literal["primary", "amendment", "explanatory"]
FACT_ROLES = ("primary", "amendment")               # sources a rule, band, score or outcome may cite


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Locator(_M):
    source: str
    page: int | None = None          # 1-based page of the source file
    section: str = ""
    table: str = ""


class Cond(_M):
    """A leaf test on an input or an earlier step: exactly one of eq, in, state."""
    ref: str
    eq: Any = None
    in_: list[Any] | None = Field(default=None, alias="in")
    state: State | None = None

    @model_validator(mode="after")
    def _one(self):
        if sum(x is not None for x in (self.eq, self.in_, self.state)) != 1:
            raise ValueError(f"cond on {self.ref!r}: exactly one of eq, in, state")
        return self


class All(_M):
    all: list["Expr"]


class AnyOf(_M):
    any: list["Expr"]


class NoneOf(_M):
    none: list["Expr"]


class CountGte(_M):
    count_gte: int
    of: list["Expr"]


Expr = Union[Cond, All, AnyOf, NoneOf, CountGte]
for _m in (All, AnyOf, NoneOf, CountGte):
    _m.model_rebuild()


def conds(e: Expr) -> list[Cond]:
    """Every leaf test in an expression."""
    if isinstance(e, Cond):
        return [e]
    kids = e.all if isinstance(e, All) else e.any if isinstance(e, AnyOf) else e.none if isinstance(e, NoneOf) else e.of
    return [c for k in kids for c in conds(k)]


class Num(_M):
    """A formula node for a derive step: exactly one of ref, const, op (with args). A whitelist of operators."""
    ref: str | None = None
    const: float | None = None
    op: Literal["add", "sub", "mul", "div", "pow", "ln", "exp", "neg"] | None = None
    args: list["Num"] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self):
        if sum(x is not None for x in (self.ref, self.const, self.op)) != 1:
            raise ValueError("num: exactly one of ref, const, op")
        if self.op is None and self.args:
            raise ValueError("num: args only with op")
        fixed = {"ln": 1, "exp": 1, "neg": 1, "sub": 2, "div": 2, "pow": 2}
        if self.op in fixed and len(self.args) != fixed[self.op]:
            raise ValueError(f"num: {self.op} takes {fixed[self.op]} argument(s)")
        if self.op in ("add", "mul") and len(self.args) < 2:
            raise ValueError(f"num: {self.op} takes 2 or more arguments")
        return self

    def refs(self) -> list[str]:
        return [self.ref] if self.ref is not None else [r for a in self.args for r in a.refs()]


Num.model_rebuild()


class InputDef(_M):
    id: str
    label: str
    type: Literal["enum", "number", "boolean"]
    options: list[str] = Field(default_factory=list)
    unit: str = ""
    how_stated: str = ""                                   # how a dictation would phrase it
    states: list[OptState] = Field(default_factory=list)
    prerequisites: list[Expr] = Field(default_factory=list)  # all must hold, else the input is not_applicable
    locator: Locator | None = None

    @model_validator(mode="after")
    def _options(self):
        if (self.type == "enum") != bool(self.options):
            raise ValueError(f"input {self.id!r}: options are given exactly when the type is enum")
        return self


class Band(_M):
    id: str
    label: str
    min: float | None = None
    min_inclusive: bool = True
    max: float | None = None
    max_inclusive: bool = False

    def holds(self, x: float) -> bool:
        lo = self.min is None or (x >= self.min if self.min_inclusive else x > self.min)
        hi = self.max is None or (x <= self.max if self.max_inclusive else x < self.max)
        return lo and hi


class BandStep(_M):
    step: Literal["band"]
    id: str
    ref: str
    bands: list[Band]
    locator: Locator | None = None

    def refs(self) -> list[str]:
        return [self.ref]


class DeriveStep(_M):
    step: Literal["derive"]
    id: str
    expr: Num
    unit: str = ""
    locator: Locator | None = None

    def refs(self) -> list[str]:
        return self.expr.refs()


class Term(_M):
    ref: str
    coef: float
    eq: Any = None        # set: an indicator, 1 when the value equals eq; unset: the value itself (true counts 1)


class ScoreStep(_M):
    step: Literal["score"]
    id: str
    kind: Literal["linear", "logistic"]
    intercept: float = 0.0
    terms: list[Term]
    locator: Locator | None = None

    def refs(self) -> list[str]:
        return [t.ref for t in self.terms]


class Row(_M):
    match: list[Any]      # one cell per key: a value, or "@<state>" to match that state
    result: str


class TableStep(_M):
    step: Literal["table"]
    id: str
    keys: list[str]
    rows: list[Row]
    locator: Locator | None = None

    def refs(self) -> list[str]:
        return list(self.keys)


class Case(_M):
    when: Expr
    result: str
    locator: Locator | None = None


class RulesStep(_M):
    step: Literal["rules"]
    id: str
    cases: list[Case]

    def refs(self) -> list[str]:
        return sorted({c.ref for case in self.cases for c in conds(case.when)})


class AdjustStep(_M):
    step: Literal["adjust"]
    id: str
    of: list[str]                     # earlier steps whose values are ids in `order`
    order: list[str]                  # lowest first
    pick: Literal["highest", "lowest"] = "highest"
    floor: str | None = None
    ceiling: str | None = None
    locator: Locator | None = None

    def refs(self) -> list[str]:
        return list(self.of)


Step = Annotated[Union[BandStep, DeriveStep, ScoreStep, TableStep, RulesStep, AdjustStep], Field(discriminator="step")]


class Outcome(_M):
    id: str
    classification: str               # may hold {input_or_step_id} placeholders
    recommendation: str = ""
    caveats: list[str] = Field(default_factory=list)
    locator: Locator | None = None


class RefText(_M):
    id: str
    text: str
    locator: Locator | None = None


class RefTable(_M):
    id: str
    title: str
    columns: list[str]
    rows: list[list[str]]
    locator: Locator | None = None


class Reference(_M):
    summary: list[RefText] = Field(default_factory=list)
    definitions: list[RefText] = Field(default_factory=list)
    tables: list[RefTable] = Field(default_factory=list)
    pitfalls: list[RefText] = Field(default_factory=list)

    def fields(self) -> list[RefText | RefTable]:
        return [*self.summary, *self.definitions, *self.tables, *self.pitfalls]


class AppliesTo(_M):
    region: list[str] = Field(default_factory=list)
    modality: list[str] = Field(default_factory=list)
    finding_type: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)


class Entry(_M):
    id: str
    version: str
    topic: str
    issuer: str
    system: str
    display: str                      # short name for cards and report lines, e.g. "Fleischner Society 2017"
    edition: str
    tier: Literal[1, 2]
    status: Literal["current", "superseded"] = "current"
    applies_to: AppliesTo
    aliases: list[str] = Field(default_factory=list)
    inputs: list[InputDef] = Field(default_factory=list)
    logic: list[Step] = Field(default_factory=list)
    result: str | None = None         # the step whose value is the outcome id
    outcomes: list[Outcome] = Field(default_factory=list)
    reference: Reference = Field(default_factory=Reference)

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    @model_validator(mode="after")
    def _tier(self):
        if self.tier == 1 and not (self.logic and self.result and self.outcomes):
            raise ValueError("a tier 1 entry needs logic, result and outcomes")
        if self.tier == 2 and (self.logic or self.result or self.outcomes):
            raise ValueError("a tier 2 entry has no logic, result or outcomes")
        return self

    def input(self, id: str) -> InputDef | None:
        return next((i for i in self.inputs if i.id == id), None)

    def step(self, id: str):
        return next((s for s in self.logic if s.id == id), None)

    def outcome(self, id: str) -> Outcome | None:
        return next((o for o in self.outcomes if o.id == id), None)


class SourceDoc(_M):
    id: str
    role: Role
    title: str
    issuer: str
    edition: str
    url: str = ""
    sha256: str = ""
    file: str = ""                    # sources/<sha256>.pdf, relative to the entry folder
    text_file: str = ""               # sources/<sha256>.txt (pdftotext -layout; pages split by form feeds)
    retrieved: str = ""


class Manifest(_M):
    sources: list[SourceDoc]


class InputValue(_M):
    state: State = "present"
    value: Any = None
    band: str | None = None           # a number answered as a band id (the radiologist picked "6-8 mm")


def as_value(x: Any) -> InputValue:
    """A golden case or answer value: a scalar is a present value; a mapping is an InputValue."""
    if isinstance(x, InputValue):
        return x
    if isinstance(x, dict):
        return InputValue.model_validate(x)
    return InputValue(value=x)


class GoldenCase(_M):
    name: str
    origin: Literal["source", "ours"]  # source: a worked example from the guideline itself
    inputs: dict[str, Any]
    outcome: str | None = None         # None: no outcome yet, an input is still needed
    needed: list[str] | None = None
    steps: dict[str, Any] = Field(default_factory=dict)   # step id -> expected value (floats within 1e-3)


class Cases(_M):
    cases: list[GoldenCase]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_schema.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library backend/tests/conftest.py backend/tests/test_library_schema.py
git commit -m "feat(library): guideline entry schema (inputs, data-only steps, outcomes, reference)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Engine (evaluation, trace, rendering)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py`
- Test: `backend/tests/test_library_engine.py`

**Interfaces:**
- Consumes: Task 1 schema.
- Produces: `engine.evaluate(entry, given: dict[str, Any]) -> Trace`; `Trace{outcome, possible, bounded, needed, inputs: dict[str, InputValue], steps: list[StepTrace]}`; `StepTrace{id, kind, state, value, fired, uses, locator}`; `EvaluationError`; `render(entry, trace, text) -> str`; internals used by Task 4: `V`, `UNKNOWN`, `truth(expr, env)`, `_inputs(entry, given) -> dict[str, V]`, `run(entry, env, overrides=None) -> list[StepTrace]`, `_iv(V) -> InputValue`, `PH` (placeholder regex). In this task `evaluate` returns `possible=[]`, `needed=[]` for an unknown outcome; Task 3 fills them in.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_library_engine.py`:

```python
import math

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry

CALC = {
    "id": "calc", "version": "1", "topic": "calc", "issuer": "T", "system": "calc", "display": "Calc", "edition": "1",
    "tier": 1, "applies_to": {},
    "inputs": [{"id": "a", "label": "A", "type": "number"}, {"id": "b", "label": "B", "type": "number"},
               {"id": "flag", "label": "Flag", "type": "boolean"},
               {"id": "grade", "label": "Grade", "type": "enum", "options": ["g1", "g2", "g3"]}],
    "logic": [
        {"step": "derive", "id": "r", "expr": {"op": "ln", "args": [{"op": "div", "args": [{"ref": "b"}, {"ref": "a"}]}]}},
        {"step": "derive", "id": "q", "expr": {"op": "div", "args": [{"ref": "a"}, {"ref": "b"}]}},
        {"step": "score", "id": "s", "kind": "linear", "intercept": 1,
         "terms": [{"ref": "a", "coef": 2}, {"ref": "flag", "coef": 3}, {"ref": "grade", "coef": 5, "eq": "g2"}]},
        {"step": "score", "id": "p", "kind": "logistic", "intercept": 0, "terms": [{"ref": "a", "coef": 1}]},
        {"step": "band", "id": "a_band", "ref": "a", "bands": [{"id": "small", "label": "small", "max": 10},
                                                              {"id": "big", "label": "big", "min": 10}]},
        {"step": "table", "id": "t", "keys": ["grade"], "rows": [{"match": ["g1"], "result": "low"},
                                                                 {"match": ["g2"], "result": "mid"},
                                                                 {"match": ["g3"], "result": "high"}]},
        {"step": "rules", "id": "u", "cases": [
            {"when": {"count_gte": 2, "of": [{"ref": "flag", "eq": True}, {"ref": "grade", "in": ["g2", "g3"]},
                                             {"ref": "a_band", "eq": "big"}]}, "result": "high"},
            {"when": {"none": [{"count_gte": 2, "of": [{"ref": "flag", "eq": True},
                                                        {"ref": "grade", "in": ["g2", "g3"]},
                                                        {"ref": "a_band", "eq": "big"}]}]}, "result": "low"}]},
        {"step": "adjust", "id": "final", "of": ["t", "u"], "order": ["low", "mid", "high"], "ceiling": "mid"}],
    "result": "final",
    "outcomes": [{"id": "low", "classification": "low"}, {"id": "mid", "classification": "mid"},
                 {"id": "high", "classification": "high"}],
}


@pytest.fixture
def calc():
    return Entry.model_validate(CALC)


def _step(t, sid):
    return next(s for s in t.steps if s.id == sid)


def test_known_inputs_give_the_outcome_and_a_trace(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7, "risk": "high"})
    assert t.outcome == "ct6" and t.possible == ["ct6"] and t.needed == []
    band, plan = _step(t, "size_band"), _step(t, "plan")
    assert (band.value, band.fired) == ("6to8", "6to8")
    assert (plan.value, plan.fired, plan.uses) == ("ct6", "3", ["kind", "risk", "size_band"])
    assert plan.locator.page == 3


@pytest.mark.parametrize("size,band", [(5.99, "lt6"), (6, "6to8"), (8, "6to8"), (8.01, "gt8"), (-1, "lt6")])
def test_band_edges_follow_inclusivity(toy_entry, size, band):
    assert _step(E.evaluate(toy_entry, {"kind": "solid", "size": size}), "size_band").value == band


def test_prerequisite_false_makes_an_input_not_applicable(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "subsolid", "risk": "high"})
    assert t.outcome == "subsolid" and t.inputs["risk"].state == "not_applicable"


def test_a_number_answered_as_a_band(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": {"band": "6to8"}, "risk": "low"})
    assert t.outcome == "ct12" and _step(t, "size_band").value == "6to8"


def test_states_and_values_are_validated(toy_entry):
    assert E.evaluate(toy_entry, {"kind": "subsolid", "margin": {"state": "not_assessable"}}).outcome == "subsolid"
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"kind": "subsolid", "margin": {"state": "absent"}})
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"kind": "cystic"})


def test_unknown_blocks_the_outcome(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7})
    assert t.outcome is None and _step(t, "plan").state == "unknown"


def test_two_cases_holding_is_an_entry_error(toy):
    toy["logic"][1]["cases"][2]["when"] = {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "6to8"}]}
    with pytest.raises(E.EvaluationError, match="all hold"):
        E.evaluate(Entry.model_validate(toy), {"kind": "solid", "size": 7, "risk": "high"})


def test_render_fills_inputs_and_band_labels(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7, "risk": "high"})
    assert E.render(toy_entry, t, "solid nodule {size_band}, {risk} risk, {size} mm") == \
        "solid nodule 6-8 mm, high risk, 7 mm"
    t2 = E.evaluate(toy_entry, {"kind": "subsolid"})
    assert E.render(toy_entry, t2, "x {size_band}") == "x {size_band}"     # nothing to fill: left as written


def test_derive_score_table_rules_adjust(calc):
    t = E.evaluate(calc, {"a": 2, "b": 2 * math.e, "flag": True, "grade": "g3"})
    assert math.isclose(_step(t, "r").value, 1.0)
    assert _step(t, "s").value == 1 + 2 * 2 + 3 * 1 + 0          # g3 is not g2
    assert math.isclose(_step(t, "p").value, 1 / (1 + math.exp(-2)))
    assert _step(t, "t").value == "high" and _step(t, "u").value == "high"
    assert t.outcome == "mid"                                       # highest is high, ceiling mid
    t2 = E.evaluate(calc, {"a": 2, "b": 3, "flag": False, "grade": "g1"})
    assert _step(t2, "u").value == "low" and t2.outcome == "low"


def test_formula_edges(calc):
    assert _step(E.evaluate(calc, {"a": 0, "b": 3, "flag": False, "grade": "g1"}), "r").value == math.inf   # ln(3/0)
    with pytest.raises(E.EvaluationError, match="ln"):
        E.evaluate(calc, {"a": 2, "b": -1, "flag": False, "grade": "g1"})


def test_a_band_only_number_cannot_feed_a_formula(calc):
    t = E.evaluate(calc, {"a": {"band": "big"}, "b": 3, "flag": True, "grade": "g2"})
    assert _step(t, "r").state == "unknown" and _step(t, "a_band").value == "big"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_engine.py -q`
Expected: FAIL with `ImportError: cannot import name 'engine'`.

- [ ] **Step 3: Write the engine**

`backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py`:

```python
"""Evaluates one tier 1 library entry for one lesion (library spec §4). Code only: the model settles inputs; this
computes the outcome and a trace of what fired, with the locators behind it. Three-valued: an input not yet known
makes whatever depends on it unknown. When the outcome is unknown, partial evaluation (Task 3) enumerates the unknown
inputs to say which of them could still change it and which outcomes remain possible."""
from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, Field

from .schema import (AdjustStep, All, AnyOf, BandStep, Cond, DeriveStep, Entry, Expr, InputDef, InputValue, Locator,
                     NoneOf, Num, RulesStep, ScoreStep, TableStep, as_value)

PH = re.compile(r"\{([A-Za-z0-9_]+)\}")
_ORDER = ("unknown", "not_assessable", "not_applicable", "absent")   # the state a blocked step takes, first wins


class EvaluationError(Exception):
    """The entry is wrong (two cases hold, no row matches, a formula is undefined), never the case. The quality gates
    enumerate every combination before an entry merges, so reaching this at runtime is a bug."""


class V(BaseModel):
    state: str = "present"
    value: Any = None
    band: str | None = None           # a number answered as a band id instead of a value


UNKNOWN = V(state="unknown")


class StepTrace(BaseModel):
    id: str
    kind: str
    state: str = "present"
    value: Any = None
    fired: str = ""                   # rules: the case index; table: the row index; band, adjust: the id chosen
    uses: list[str] = Field(default_factory=list)
    locator: Locator | None = None


class Trace(BaseModel):
    outcome: str | None = None
    possible: list[str] = Field(default_factory=list)
    bounded: bool = True              # False: an unknown number feeds a formula, so `possible` may be incomplete
    needed: list[str] = Field(default_factory=list)
    inputs: dict[str, InputValue] = Field(default_factory=dict)
    steps: list[StepTrace] = Field(default_factory=list)


def _coerce(i: InputDef, g: InputValue) -> V:
    if g.state != "present":
        if g.state not in i.states:
            raise ValueError(f"input {i.id}: state {g.state} is not allowed")
        return V(state=g.state)
    if i.type == "number":
        return V(band=g.band) if g.band is not None else V(value=float(g.value))
    if i.type == "boolean":
        if not isinstance(g.value, bool):
            raise ValueError(f"input {i.id}: {g.value!r} is not true or false")
        return V(value=g.value)
    if g.value not in i.options:
        raise ValueError(f"input {i.id}: {g.value!r} is not an option")
    return V(value=g.value)


def truth(e: Expr, env: dict[str, V]) -> bool | None:
    """True, False, or None when an unknown value decides it."""
    if isinstance(e, Cond):
        v = env.get(e.ref, UNKNOWN)
        if v.state == "unknown":
            return None
        if e.state is not None:
            return v.state == e.state
        if v.state != "present":
            return False
        return v.value == e.eq if e.in_ is None else v.value in e.in_
    if isinstance(e, All):
        got = [truth(x, env) for x in e.all]
        return False if False in got else (None if None in got else True)
    if isinstance(e, AnyOf):
        got = [truth(x, env) for x in e.any]
        return True if True in got else (None if None in got else False)
    if isinstance(e, NoneOf):
        got = [truth(x, env) for x in e.none]
        return False if True in got else (None if None in got else True)
    got = [truth(x, env) for x in e.of]
    yes, maybe = got.count(True), got.count(None)
    return True if yes >= e.count_gte else (False if yes + maybe < e.count_gte else None)


def _inputs(entry: Entry, given: dict[str, InputValue]) -> dict[str, V]:
    env: dict[str, V] = {}
    for i in entry.inputs:
        if any(truth(p, env) is False for p in i.prerequisites):
            env[i.id] = V(state="not_applicable")
            continue
        g = given.get(i.id)
        env[i.id] = UNKNOWN if g is None or g.state == "unknown" else _coerce(i, g)
    return env


def _blocked(refs: list[str], env: dict[str, V]) -> V | None:
    """The state a formula step takes when a value it needs is not present; None when it can compute."""
    states = {env.get(r, UNKNOWN).state for r in refs} - {"present"}
    for s in _ORDER:
        if s in states:
            return UNKNOWN if s == "unknown" else V(state=s)
    if any(env[r].value is None for r in refs):      # a number answered only as a band cannot feed a formula
        return UNKNOWN
    return None


def _num(n: Num, env: dict[str, V]) -> float:
    if n.ref is not None:
        return float(env[n.ref].value)
    if n.const is not None:
        return n.const
    a = [_num(x, env) for x in n.args]
    if n.op == "add":
        return math.fsum(a)
    if n.op == "mul":
        return math.prod(a)
    if n.op == "sub":
        return a[0] - a[1]
    if n.op == "neg":
        return -a[0]
    if n.op == "exp":
        return math.exp(a[0])
    if n.op == "pow":
        r = a[0] ** a[1]
        if isinstance(r, complex):
            raise EvaluationError(f"pow({a[0]}, {a[1]}) is not real")
        return r
    if n.op == "div":
        if a[1] == 0:
            if a[0] == 0:
                raise EvaluationError("0/0 in a formula")
            return math.copysign(math.inf, a[0])
        return a[0] / a[1]
    if a[0] <= 0:
        raise EvaluationError(f"ln of {a[0]}")
    return math.log(a[0])


def _band(s: BandStep, env):
    v = env.get(s.ref, UNKNOWN)
    if v.state != "present":
        return (UNKNOWN if v.state == "unknown" else V(state=v.state)), ""
    if v.value is None:                               # answered as a band: only this step's own ids count
        return (V(value=v.band), v.band) if any(b.id == v.band for b in s.bands) else (UNKNOWN, "")
    hits = [b.id for b in s.bands if b.holds(float(v.value))]
    if len(hits) != 1:
        raise EvaluationError(f"{s.id}: {v.value} falls in {len(hits)} bands")
    return V(value=hits[0]), hits[0]


def _derive(s: DeriveStep, env):
    b = _blocked(s.refs(), env)
    return (b, "") if b else (V(value=_num(s.expr, env)), "")


def _score(s: ScoreStep, env):
    b = _blocked(s.refs(), env)
    if b:
        return b, ""
    z = s.intercept + math.fsum(
        t.coef * ((1.0 if env[t.ref].value == t.eq else 0.0) if t.eq is not None else float(env[t.ref].value))
        for t in s.terms)
    return V(value=z if s.kind == "linear" else 1.0 / (1.0 + math.exp(-z))), ""


def _cell(c: Any, v: V) -> bool:
    if isinstance(c, str) and c.startswith("@"):
        return v.state == c[1:]
    return v.state == "present" and v.value == c


def _table(s: TableStep, env):
    vals = [env.get(k, UNKNOWN) for k in s.keys]
    if any(v.state == "unknown" for v in vals):
        return UNKNOWN, ""
    hits = [n for n, r in enumerate(s.rows) if all(_cell(c, v) for c, v in zip(r.match, vals))]
    if len(hits) != 1:
        shown = [v.value if v.state == "present" else f"@{v.state}" for v in vals]
        raise EvaluationError(f"{s.id}: {len(hits)} rows match {shown}")
    return V(value=s.rows[hits[0]].result), str(hits[0])


def _rules(s: RulesStep, env):
    got = [truth(c.when, env) for c in s.cases]
    yes = [n for n, t in enumerate(got) if t is True]
    if len(yes) > 1:
        raise EvaluationError(f"{s.id}: cases {yes} all hold")
    if yes:
        return V(value=s.cases[yes[0]].result), str(yes[0])
    if None in got:
        return UNKNOWN, ""
    raise EvaluationError(f"{s.id}: no case holds")


def _adjust(s: AdjustStep, env):
    vals = [env.get(r, UNKNOWN) for r in s.of]
    if any(v.state == "unknown" for v in vals):
        return UNKNOWN, ""
    ranks = [s.order.index(v.value) for v in vals if v.state == "present"]
    if not ranks:
        return V(state="not_applicable"), ""
    r = max(ranks) if s.pick == "highest" else min(ranks)
    if s.floor is not None:
        r = max(r, s.order.index(s.floor))
    if s.ceiling is not None:
        r = min(r, s.order.index(s.ceiling))
    return V(value=s.order[r]), s.order[r]


_STEPS = {"band": _band, "derive": _derive, "score": _score, "table": _table, "rules": _rules, "adjust": _adjust}


def run(entry: Entry, env: dict[str, V], overrides: dict[str, V] | None = None) -> list[StepTrace]:
    """Runs the logic in order, writing each step's value into env. `overrides` fixes a step's value without
    computing it (the gates enumerate band ids this way)."""
    traces = []
    for s in entry.logic:
        if overrides and s.id in overrides:
            v, fired = overrides[s.id], "override"
        else:
            v, fired = _STEPS[s.step](s, env)
        env[s.id] = v
        loc = s.cases[int(fired)].locator if isinstance(s, RulesStep) and fired.isdigit() else getattr(s, "locator", None)
        traces.append(StepTrace(id=s.id, kind=s.step, state=v.state, value=v.value, fired=fired, uses=s.refs(),
                                locator=loc))
    return traces


def _iv(v: V) -> InputValue:
    return InputValue(state=v.state, value=v.value, band=v.band)


def _once(entry: Entry, given: dict[str, InputValue]) -> tuple[dict[str, V], list[StepTrace]]:
    env = _inputs(entry, given)
    return env, run(entry, env)


def _partial(entry: Entry, given: dict[str, InputValue], env: dict[str, V]) -> tuple[list[str], bool, list[str]]:
    return [], True, []          # Task 3


def evaluate(entry: Entry, given: dict[str, Any]) -> Trace:
    """The outcome for these inputs (unknown inputs simply left out), with a trace. Raises ValueError for an input
    value the entry does not allow, EvaluationError for a defect in the entry."""
    given = {k: as_value(v) for k, v in given.items() if entry.input(k) is not None}
    env, steps = _once(entry, given)
    out = env[entry.result]
    inputs = {i.id: _iv(env[i.id]) for i in entry.inputs}
    if out.state == "present":
        return Trace(outcome=out.value, possible=[out.value], inputs=inputs, steps=steps)
    if out.state != "unknown":
        raise EvaluationError(f"result step {entry.result} ended {out.state}")
    possible, bounded, needed = _partial(entry, given, env)
    return Trace(possible=possible, bounded=bounded, needed=needed, inputs=inputs, steps=steps)


def _fmt(x: Any) -> str:
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:g}"
    return str(x)


def render(entry: Entry, trace: Trace, text: str) -> str:
    """Fills {id} with an input's value or a step's value (a band step's label). An id with no present value is left
    as written; the gates reject an outcome whose text can be left unfilled."""
    vals = {k: _fmt(v.value) for k, v in trace.inputs.items() if v.state == "present" and v.value is not None}
    for st in trace.steps:
        if st.state != "present":
            continue
        s = entry.step(st.id)
        vals[st.id] = next(b.label for b in s.bands if b.id == st.value) if isinstance(s, BandStep) else _fmt(st.value)
    return PH.sub(lambda m: vals.get(m.group(1), m.group(0)), text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py backend/tests/test_library_engine.py
git commit -m "feat(library): three-valued engine with trace and rendering

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Partial evaluation (which unknown inputs still matter)

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py` (replace the `_partial` stub; add `domain`, `MAX_COMBOS`)
- Test: `backend/tests/test_library_partial.py`

**Interfaces:**
- Produces: `engine.domain(entry, input_def) -> list[InputValue] | None` (None for a number that feeds a formula); `engine.MAX_COMBOS`; `Trace.needed` is ordered as `entry.inputs`; `Trace.possible` is sorted outcome ids.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_library_partial.py`:

```python
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry

from test_library_engine import CALC


def test_only_inputs_that_change_the_outcome_are_needed(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7})
    assert t.outcome is None and t.needed == ["risk"] and t.possible == ["ct12", "ct6"] and t.bounded


def test_numbers_are_enumerated_through_their_band_edges(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid"})
    assert t.needed == ["size", "risk"] and t.possible == ["ct12", "ct6", "none", "pet"]


def test_nothing_known(toy_entry):
    t = E.evaluate(toy_entry, {})
    assert t.needed == ["kind", "size", "risk"]          # margin never changes the outcome: never asked
    assert t.possible == ["ct12", "ct6", "none", "pet", "subsolid"]


def test_number_domain_covers_edges_and_regions(toy_entry):
    xs = [v.value for v in E.domain(toy_entry, toy_entry.input("size"))]
    assert xs == [5, 6, 7, 8, 9]
    assert [v.state for v in E.domain(toy_entry, toy_entry.input("margin"))][-1] == "not_assessable"


def test_a_number_feeding_a_formula_is_unbounded():
    calc = Entry.model_validate(CALC)
    t = E.evaluate(calc, {"b": 3, "flag": True, "grade": "g1"})
    assert E.domain(calc, calc.input("a")) is None
    assert t.outcome is None and "a" in t.needed and t.bounded is False


def test_too_many_combinations_falls_back_to_everything(toy_entry, monkeypatch):
    monkeypatch.setattr(E, "MAX_COMBOS", 1)
    t = E.evaluate(toy_entry, {"kind": "solid"})
    assert t.bounded is False and t.needed == ["size", "risk", "margin"]    # cannot tell: every unknown is asked
    assert t.possible == sorted(o.id for o in toy_entry.outcomes)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_partial.py -q`
Expected: FAIL (`needed == []` from the stub; `domain` missing).

- [ ] **Step 3: Implement partial evaluation**

In `engine.py`, add `from itertools import product` to the imports, add `MAX_COMBOS = 50_000` under `PH`, and replace the `_partial` stub with:

```python
def _edges(entry: Entry, input_id: str) -> list[float] | None:
    """One number per region the band edges cut the line into, edges included; None when the number also feeds a
    formula (its effect cannot be enumerated)."""
    users = [s for s in entry.logic if input_id in s.refs()]
    if any(not isinstance(s, BandStep) for s in users):
        return None
    pts = sorted({x for s in users for b in s.bands for x in (b.min, b.max) if x is not None})
    if not pts:
        return [0.0]
    mids = [(a + b) / 2 for a, b in zip(pts, pts[1:])]
    return sorted({pts[0] - 1, *pts, pts[-1] + 1, *mids})


def domain(entry: Entry, i: InputDef) -> list[InputValue] | None:
    """Every value class of an input: its options, true and false, or its band regions; plus the states it allows."""
    extra = [InputValue(state=s) for s in i.states]
    if i.type == "enum":
        return [InputValue(value=o) for o in i.options] + extra
    if i.type == "boolean":
        return [InputValue(value=True), InputValue(value=False)] + extra
    xs = _edges(entry, i.id)
    return None if xs is None else [InputValue(value=x) for x in xs] + extra


def _partial(entry: Entry, given: dict[str, InputValue], env: dict[str, V]) -> tuple[list[str], bool, list[str]]:
    """(possible outcomes, bounded, needed inputs). An unknown input is needed when changing it alone can change the
    outcome for some value of the other unknown inputs."""
    unknown = [i for i in entry.inputs if env[i.id].state == "unknown"]
    doms = {i.id: domain(entry, i) for i in unknown}
    unbounded = [k for k, d in doms.items() if d is None]
    names = [k for k, d in doms.items() if d is not None]
    order = [i.id for i in entry.inputs]
    if math.prod(len(doms[n]) for n in names) > MAX_COMBOS:
        return sorted(o.id for o in entry.outcomes), False, [i.id for i in unknown]
    results = []
    for combo in product(*(doms[n] for n in names)):
        e2, _ = _once(entry, {**given, **dict(zip(names, combo))})
        v = e2[entry.result]
        results.append((combo, v.value if v.state == "present" else None))
    possible = sorted({r for _, r in results if r is not None})
    bounded = all(r is not None for _, r in results)
    needed = []
    for k, n in enumerate(names):
        groups: dict[tuple, set] = {}
        for combo, r in results:
            rest = tuple((v.state, v.value, v.band) for v in combo[:k] + combo[k + 1:])   # InputValue is unhashable
            groups.setdefault(rest, set()).add(r)
        if any(len(g) > 1 for g in groups.values()):
            needed.append(n)
    if not bounded:
        needed += unbounded
    return possible, bounded, sorted(set(needed), key=order.index)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_partial.py tests/test_library_engine.py -q`
Expected: PASS. (`test_library_partial.py` imports `CALC` from `test_library_engine`; pytest's default rootdir import mode makes sibling test modules importable.)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/engine.py backend/tests/test_library_partial.py
git commit -m "feat(library): partial evaluation asks only inputs that can change the outcome

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Quality gates 1–4

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py`
- Test: `backend/tests/test_library_verify.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `verify.check(entry: Entry, manifest: Manifest, cases: Cases | None) -> list[str]` (empty when the entry passes); `verify.MAX_VERIFY`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_library_verify.py`:

```python
import pytest

from rapid_reports_ai.hybrid_stack.copilot.library.schema import Cases, Entry
from rapid_reports_ai.hybrid_stack.copilot.library.verify import check


def _check(toy, manifest, cases):
    return check(Entry.model_validate(toy), manifest, cases)


def test_toy_passes(toy_entry, manifest, cases):
    assert check(toy_entry, manifest, cases) == []


def test_band_gap_and_overlap(toy, manifest, cases):
    toy["logic"][0]["bands"][1]["min"] = 6.5
    assert any("size_band" in p and "do not meet" in p for p in _check(toy, manifest, cases))
    toy["logic"][0]["bands"][1]["min"] = 6
    toy["logic"][0]["bands"][0]["max_inclusive"] = True
    assert any("in both" in p for p in _check(toy, manifest, cases))


def test_rule_overlap_and_gap_are_found_by_enumeration(toy, manifest, cases):
    toy["logic"][1]["cases"][2]["when"] = {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "6to8"}]}
    assert any("all hold" in p for p in _check(toy, manifest, cases))
    toy = {**toy}
    toy["logic"] = [toy["logic"][0], {**toy["logic"][1], "cases": toy["logic"][1]["cases"][:4]}]
    assert any("no case holds" in p for p in _check(toy, manifest, cases))


def test_a_rule_may_not_compare_a_number(toy, manifest, cases):
    toy["logic"][1]["cases"][0]["when"] = {"all": [{"ref": "kind", "eq": "subsolid"}, {"ref": "size", "eq": 7}]}
    assert any("band it first" in p for p in _check(toy, manifest, cases))


def test_locators(toy, manifest, cases):
    del toy["outcomes"][0]["locator"]
    toy["logic"][1]["cases"][0]["locator"] = {"source": "S2"}
    probs = _check(toy, manifest, cases)
    assert any("outcome subsolid: no locator" in p for p in probs)
    assert any("explanatory" in p for p in probs)


def test_result_values_must_be_outcomes(toy, manifest, cases):
    toy["logic"][1]["cases"][4]["result"] = "biopsy"
    assert any("biopsy" in p and "not an outcome" in p for p in _check(toy, manifest, cases))


def test_golden_cases(toy, manifest, cases):
    cases.cases[3].outcome = "ct12"
    assert any("edge 8 high" in p for p in _check(toy, manifest, cases))
    short = Cases(cases=[c for c in cases.cases if c.name != "subsolid"])
    assert any("outcome subsolid has no golden case" in p for p in _check(toy, manifest, short))
    assert _check(toy, manifest, Cases(cases=[])) == ["no golden cases"]


def test_unfillable_placeholder(toy, manifest, cases):
    toy["outcomes"][0]["classification"] = "subsolid nodule {size}"
    assert any("placeholder" in p for p in _check(toy, manifest, cases))


SCORED = {
    "id": "scored", "version": "1", "topic": "s", "issuer": "T", "system": "s", "display": "S", "edition": "1",
    "tier": 1, "applies_to": {},
    "inputs": [{"id": "x", "label": "X", "type": "number"}],
    "logic": [
        {"step": "score", "id": "s", "kind": "linear", "terms": [{"ref": "x", "coef": 1}],
         "locator": {"source": "S1"}},
        {"step": "band", "id": "s_band", "ref": "s", "locator": {"source": "S1"},
         "bands": [{"id": "lo", "label": "low", "max": 0.5}, {"id": "hi", "label": "high", "min": 0.5}]},
        {"step": "rules", "id": "r", "cases": [
            {"when": {"ref": "s_band", "eq": "lo"}, "result": "a", "locator": {"source": "S1"}},
            {"when": {"ref": "s_band", "eq": "hi"}, "result": "b", "locator": {"source": "S1"}}]}],
    "result": "r",
    "outcomes": [{"id": "a", "classification": "a", "locator": {"source": "S1"}},
                 {"id": "b", "classification": "b", "locator": {"source": "S1"}}],
}


def test_a_banded_score_needs_cases_either_side_of_its_cut_off(manifest):
    e = Entry.model_validate(SCORED)
    one_side = Cases.model_validate({"cases": [
        {"name": "lo", "origin": "ours", "inputs": {"x": 0.2}, "outcome": "a", "steps": {"s": 0.2}}]})
    probs = check(e, manifest, one_side)
    assert any("no golden case reaches band hi" in p for p in probs)
    assert any("s: 1 golden case(s)" in p for p in probs)
    both = Cases.model_validate({"cases": [
        {"name": "lo", "origin": "ours", "inputs": {"x": 0.2}, "outcome": "a", "steps": {"s": 0.2}},
        {"name": "hi", "origin": "ours", "inputs": {"x": 0.5}, "outcome": "b", "steps": {"s": 0.5}}]})
    assert check(e, manifest, both) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_verify.py -q`
Expected: FAIL with `ModuleNotFoundError ... verify`.

- [ ] **Step 3: Write the gates**

`backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py`:

```python
"""Quality gates 1–4 for one entry (library spec §8), run by the bundle build and by pytest. Returns problems, empty
when the entry passes. Gate 5 (Jev evidence) is scripts/guidelines/jev_evidence.py; gate 6 is the hand read."""
from __future__ import annotations

import math
from itertools import product

from .engine import PH, EvaluationError, Trace, V, _inputs, _iv, domain, evaluate, render, run
from .schema import (FACT_ROLES, AdjustStep, BandStep, Cases, DeriveStep, Entry, Manifest, RulesStep, ScoreStep,
                     TableStep, conds)

MAX_VERIFY = 200_000
NUMERIC = {"number", "derive", "score"}
TOL = 1e-3


def check(entry: Entry, manifest: Manifest, cases: Cases | None) -> list[str]:
    p = _refs(entry)
    if p:
        return p                      # the later gates assume every reference resolves
    p += _bands(entry) + _locators(entry, manifest)
    if entry.tier == 1:
        p += _enumerate(entry) + _golden(entry, cases)
    return p


def _results(s) -> list[str] | None:
    if isinstance(s, RulesStep):
        return [c.result for c in s.cases]
    if isinstance(s, TableStep):
        return [r.result for r in s.rows]
    if isinstance(s, AdjustStep):
        return list(s.order)
    return None


def _refs(e: Entry) -> list[str]:
    p: list[str] = []
    kind: dict[str, str] = {}
    ids = [i.id for i in e.inputs] + [s.id for s in e.logic]
    p += [f"duplicate id {x}" for x in sorted({x for x in ids if ids.count(x) > 1})]
    outs = [o.id for o in e.outcomes]
    p += [f"duplicate outcome {x}" for x in sorted({x for x in outs if outs.count(x) > 1})]
    for i in e.inputs:
        for c in (c for pr in i.prerequisites for c in conds(pr)):
            if c.ref not in kind:
                p.append(f"input {i.id}: prerequisite on {c.ref}, which is not an earlier input")
            elif kind[c.ref] in NUMERIC and c.state is None:
                p.append(f"input {i.id}: prerequisite compares the number {c.ref}; band it first")
        kind[i.id] = i.type
    for s in e.logic:
        p += [f"step {s.id}: {r} is not defined earlier" for r in s.refs() if r not in kind]
        if isinstance(s, RulesStep):
            p += [f"step {s.id}: a rule compares the number {c.ref}; band it first"
                  for case in s.cases for c in conds(case.when) if kind.get(c.ref) in NUMERIC and c.state is None]
        if isinstance(s, TableStep):
            p += [f"step {s.id}: key {k} is a number; band it first" for k in s.keys if kind.get(k) in NUMERIC]
            p += [f"step {s.id}: row {n} has {len(r.match)} cells for {len(s.keys)} keys"
                  for n, r in enumerate(s.rows) if len(r.match) != len(s.keys)]
        if isinstance(s, BandStep) and kind.get(s.ref) not in NUMERIC:
            p.append(f"step {s.id}: bands {s.ref}, which is not a number")
        if isinstance(s, DeriveStep):
            p += [f"step {s.id}: {r} is not a number" for r in s.refs() if kind.get(r) not in NUMERIC]
        if isinstance(s, ScoreStep):
            p += [f"step {s.id}: term on {t.ref} needs eq (it is not a number or boolean)"
                  for t in s.terms if t.eq is None and kind.get(t.ref) not in NUMERIC | {"boolean"}]
        if isinstance(s, AdjustStep):
            p += [f"step {s.id}: {x} is not in its order" for x in (s.floor, s.ceiling) if x is not None and x not in s.order]
        kind[s.id] = s.step if s.step in NUMERIC else "value"
    if e.tier == 1:
        s = e.step(e.result)
        res = _results(s) if s is not None else None
        if s is None:
            p.append(f"result {e.result} is not a step")
        elif res is None:
            p.append(f"result step {s.id} is a {s.step} step; it must be rules, table or adjust")
        else:
            p += [f"result {r} of {s.id} is not an outcome" for r in sorted(set(res) - set(outs))]
        for o in e.outcomes:
            p += [f"outcome {o.id}: {{{ph}}} is not an input or step"
                  for ph in PH.findall(" ".join([o.classification, o.recommendation, *o.caveats])) if ph not in kind]
    return p


def _bands(e: Entry) -> list[str]:
    p = []
    for s in e.logic:
        if not isinstance(s, BandStep):
            continue
        if len({b.id for b in s.bands}) != len(s.bands) or len({b.label for b in s.bands}) != len(s.bands):
            p.append(f"{s.id}: band ids and labels must be unique")
        bs = sorted(s.bands, key=lambda b: -math.inf if b.min is None else b.min)
        if bs[0].min is not None:
            p.append(f"{s.id}: gap below {bs[0].min}")
        if bs[-1].max is not None:
            p.append(f"{s.id}: gap above {bs[-1].max}")
        for a, b in zip(bs, bs[1:]):
            if a.max is None or b.min is None or a.max != b.min:
                p.append(f"{s.id}: {a.id} and {b.id} do not meet ({a.max} vs {b.min}): a gap or an overlap")
            elif a.max_inclusive == b.min_inclusive:
                p.append(f"{s.id}: edge {a.max} is {'in both' if a.max_inclusive else 'in neither'} of {a.id} and {b.id}")
        for b in bs:
            if b.min is not None and b.max is not None and (
                    b.min > b.max or (b.min == b.max and not (b.min_inclusive and b.max_inclusive))):
                p.append(f"{s.id}: band {b.id} is empty")
    return p


def _locators(e: Entry, m: Manifest) -> list[str]:
    src = {s.id: s for s in m.sources}
    p = [] if any(s.role == "primary" for s in m.sources) else ["manifest has no primary source"]

    def need(where, loc, fact=True):
        if loc is None:
            p.append(f"{where}: no locator")
        elif loc.source not in src:
            p.append(f"{where}: unknown source {loc.source}")
        elif fact and src[loc.source].role not in FACT_ROLES:
            p.append(f"{where}: cites the {src[loc.source].role} source {loc.source}; facts need primary or amendment")

    for s in e.logic:
        if isinstance(s, RulesStep):
            for n, c in enumerate(s.cases):
                need(f"{s.id} case {n}", c.locator)
        else:
            need(s.id, s.locator)
    for o in e.outcomes:
        need(f"outcome {o.id}", o.locator)
    for i in e.inputs:
        if i.locator is not None:
            need(f"input {i.id}", i.locator)
    for f in e.reference.fields():
        need(f"reference {f.id}", f.locator, fact=False)
    return p


def _reach(e: Entry, ref: str) -> set[str]:
    """The non-present states a value can take: an input's allowed states (plus not_applicable behind a
    prerequisite), or the union over a step's inputs."""
    i = e.input(ref)
    if i is not None:
        return set(i.states) | ({"not_applicable"} if i.prerequisites else set())
    s = e.step(ref)
    return set().union(*(_reach(e, r) for r in s.refs())) if s is not None else set()


def _txt(v) -> str:
    return str(v.value) if v.state == "present" else f"@{v.state}"


def _enumerate(e: Entry) -> list[str]:
    """Gate 2: every combination of discrete inputs and band ids gives exactly one outcome, and fills every
    placeholder in it. Numbers are not enumerated: their band steps are overridden with each band id instead."""
    free = [("in", i.id, domain(e, i)) for i in e.inputs if i.type != "number"]
    free += [("step", s.id, [V(value=b.id) for b in s.bands] + [V(state=x) for x in sorted(_reach(e, s.ref))])
             for s in e.logic if isinstance(s, BandStep)]
    total = math.prod(len(d) for _, _, d in free)
    if total > MAX_VERIFY:
        return [f"{total} combinations: too many to enumerate"]
    p: list[str] = []
    for combo in product(*(d for _, _, d in free)):
        given = {n: v for (k, n, _), v in zip(free, combo) if k == "in"}
        over = {n: v for (k, n, _), v in zip(free, combo) if k == "step"}
        label = ", ".join(f"{n}={_txt(v)}" for (_, n, _), v in zip(free, combo))
        try:
            env = _inputs(e, given)
            steps = run(e, env, over)
            out = env[e.result]
            if out.state != "present":
                p.append(f"[{label}] no outcome ({out.state})")
            else:
                o = e.outcome(out.value)
                t = Trace(outcome=out.value, inputs={i.id: _iv(env[i.id]) for i in e.inputs}, steps=steps)
                if any(PH.search(render(e, t, x)) for x in (o.classification, o.recommendation, *o.caveats)):
                    p.append(f"[{label}] outcome {o.id} leaves a placeholder unfilled")
        except EvaluationError as ex:
            p.append(f"[{label}] {ex}")
        if len(p) >= 20:
            p.append("… more")
            break
    return p


def _close(a, b) -> bool:
    nums = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b))
    return math.isclose(a, b, rel_tol=TOL, abs_tol=TOL) if nums else a == b


def _golden(e: Entry, cases: Cases | None) -> list[str]:
    """Gate 3: golden cases pass, every outcome has one, every formula value is checked twice, and every band over a
    formula is reached (either side of each cut-off)."""
    if cases is None or not cases.cases:
        return ["no golden cases"]
    p: list[str] = []
    reached: set[str] = set()
    hit: dict[str, set] = {}
    for c in cases.cases:
        try:
            t = evaluate(e, c.inputs)
        except (EvaluationError, ValueError) as ex:
            p.append(f"case {c.name!r}: {ex}")
            continue
        if t.outcome != c.outcome:
            p.append(f"case {c.name!r}: outcome {t.outcome} != expected {c.outcome}")
        if c.needed is not None and t.needed != c.needed:
            p.append(f"case {c.name!r}: needed {t.needed} != expected {c.needed}")
        got = {s.id: s for s in t.steps}
        for sid, want in c.steps.items():
            s = got.get(sid)
            if s is None or s.state != "present" or not _close(s.value, want):
                p.append(f"case {c.name!r}: step {sid} = {None if s is None else s.value} != expected {want}")
        if t.outcome:
            reached.add(t.outcome)
        for s in t.steps:
            if s.state == "present":
                hit.setdefault(s.id, set()).add(s.value)
    p += [f"outcome {o.id} has no golden case" for o in e.outcomes if o.id not in reached]
    for s in e.logic:
        if isinstance(s, BandStep) and isinstance(e.step(s.ref), (ScoreStep, DeriveStep)):
            p += [f"{s.id}: no golden case reaches band {b.id}" for b in s.bands if b.id not in hit.get(s.id, set())]
        if isinstance(s, (ScoreStep, DeriveStep)):
            n = sum(1 for c in cases.cases if s.id in c.steps)
            if n < 2:
                p.append(f"{s.id}: {n} golden case(s) check its value; at least 2 needed")
    return p
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_verify.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/verify.py backend/tests/test_library_verify.py
git commit -m "feat(library): quality gates 1-4 (schema refs, bands, enumeration, locators, golden cases)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Bundle (compile, load, interface) and the build script

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/bundle.py`
- Create: `backend/scripts/guidelines/build_bundle.py`
- Create: `backend/src/rapid_reports_ai/resources/guideline_bundle.json` (generated, committed)
- Create: `guidelines/README.md`
- Modify: `backend/tests/conftest.py` (autouse: tests see an empty library unless they opt in)
- Test: `backend/tests/test_library_bundle.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `bundle.GUIDELINES` (repo `guidelines/`), `bundle.BUNDLE` (the JSON path), `BundleError`, `compile_bundle(root=GUIDELINES) -> dict`, `dumps(bundle) -> str`, `Library(bundle_dict)` with `version() -> str`, `lookup(key_or_id, version=None) -> Entry | None`, `list(region=None, modality=None, finding_type=None, context=None) -> list[Entry]`, `siblings(entry) -> list[Entry]`, `find(name, version="") -> Entry | None`, `sources(key) -> list[dict]`, `evaluate(key, given) -> Trace`, `known_text() -> str`; `get() -> Library` (cached; fail-open to an empty library).

- [ ] **Step 1: Make tests see an empty library by default**

Append to `backend/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _empty_guideline_library(monkeypatch):
    """Matcher and route tests must not depend on whichever packs the real bundle holds; a test that needs packs
    sets L.get itself."""
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
    monkeypatch.setattr(L, "get", lambda: L.Library({}))
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_library_bundle.py`:

```python
import json

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L


def _lib(toy_dir):
    return L.Library(L.compile_bundle(toy_dir))


def test_compile_is_deterministic_and_strips_file_paths(toy_dir):
    b = L.compile_bundle(toy_dir)
    assert len(b["version"]) == 12 and list(b["entries"]) == ["toy-nodule@1.0"]
    assert b == L.compile_bundle(toy_dir)
    src = b["entries"]["toy-nodule@1.0"]["sources"][0]
    assert src == {"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY", "edition": "2020",
                   "url": "https://example.org/toy"}


def test_a_failing_gate_fails_the_build(toy_dir):
    p = toy_dir / "toy-nodule" / "entry.json"
    d = json.loads(p.read_text())
    d["logic"][1]["cases"].pop()
    p.write_text(json.dumps(d))
    with pytest.raises(L.BundleError, match="no case holds"):
        L.compile_bundle(toy_dir)


def test_folder_must_match_the_entry_id(toy_dir):
    (toy_dir / "toy-nodule").rename(toy_dir / "other")
    with pytest.raises(L.BundleError, match="folder"):
        L.compile_bundle(toy_dir)


def test_superseded_versions_are_kept(toy_dir, toy):
    h = toy_dir / "toy-nodule" / "history"
    h.mkdir()
    (h / "0.9.json").write_text(json.dumps({**toy, "version": "0.9", "status": "superseded"}))
    lib = _lib(toy_dir)
    assert lib.lookup("toy-nodule@0.9").status == "superseded"
    assert lib.lookup("toy-nodule").version == "1.0"
    assert lib.lookup("toy-nodule", "0.9").version == "0.9"


def test_library_interface(toy_dir, toy):
    sib = toy_dir / "toy-other"
    sib.mkdir()
    (sib / "entry.json").write_text(json.dumps({**toy, "id": "toy-other", "issuer": "OTHER", "display": "Other 2021",
                                                "aliases": ["other nodule"]}))
    for f in ("manifest.json", "cases.json"):
        (sib / f).write_text((toy_dir / "toy-nodule" / f).read_text())
    lib = _lib(toy_dir)
    toy_e = lib.lookup("toy-nodule@1.0")
    assert [e.id for e in lib.list(region="chest", finding_type="nodule")] == ["toy-nodule", "toy-other"]
    assert lib.list(region="abdomen") == []
    assert [e.id for e in lib.siblings(toy_e)] == ["toy-other"]
    assert lib.find("Toy Nodule").id == "toy-nodule" and lib.find("TOY NODULE", "2020").id == "toy-nodule"
    assert lib.find("Toy Nodule", "1999") is None and lib.find("Fleischner") is None
    assert lib.evaluate("toy-nodule@1.0", {"kind": "subsolid"}).outcome == "subsolid"
    assert "- toy-nodule@1.0: Toy 2020 [aliases: toy nodule | toy guideline]" in lib.known_text()
    assert lib.sources("toy-nodule@1.0")[0]["id"] == "S1"


def test_get_fails_open(monkeypatch, tmp_path):
    monkeypatch.undo()                                  # drop the autouse empty-library patch
    monkeypatch.setattr(L, "BUNDLE", tmp_path / "missing.json")
    L._load.cache_clear()
    try:
        assert L.get().version() == "" and L.get().lookup("x@1") is None
    finally:
        L._load.cache_clear()


def test_committed_bundle_matches_the_guidelines_folder():
    assert json.loads(L.BUNDLE.read_text()) == L.compile_bundle(L.GUIDELINES)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py -q`
Expected: FAIL (the autouse fixture itself errors on the missing `bundle` module).

- [ ] **Step 4: Write the bundle module**

`backend/src/rapid_reports_ai/hybrid_stack/copilot/library/bundle.py`:

```python
"""The compiled guideline library (library spec §4, §6). guidelines/<entry>/ is compiled, through the quality gates,
into one versioned bundle committed under resources/. The backend loads that bundle once and never reads the source
folders or the network. A bundle that fails to load gives an empty library: the Copilot shows no pack cards, and
nothing else is affected."""
from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..registry import norm
from . import engine
from .schema import Cases, Entry, Manifest
from .verify import check

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve()
GUIDELINES = _HERE.parents[6] / "guidelines"
BUNDLE = _HERE.parents[3] / "resources" / "guideline_bundle.json"
_PUBLIC = ("id", "role", "title", "issuer", "edition", "url")


class BundleError(Exception):
    pass


def _read(d: Path) -> list[tuple[Entry, Manifest, Cases | None]]:
    m = Manifest.model_validate_json((d / "manifest.json").read_text())
    c = Cases.model_validate_json((d / "cases.json").read_text()) if (d / "cases.json").exists() else None
    out = [(Entry.model_validate_json((d / "entry.json").read_text()), m, c)]
    hist = d / "history"
    out += [(Entry.model_validate_json(h.read_text()), m, None) for h in sorted(hist.glob("*.json"))] if hist.exists() else []
    return out


def compile_bundle(root: Path = GUIDELINES) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    problems: list[str] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        try:
            loaded = _read(d)
        except (OSError, ValidationError) as ex:
            problems.append(f"{d.name}: {ex}")
            continue
        for n, (e, m, c) in enumerate(loaded):
            if n == 0:
                if e.id != d.name:
                    problems.append(f"{d.name}: entry id {e.id} does not match its folder")
                if e.status != "current":
                    problems.append(f"{d.name}: entry.json must be the current version")
                problems += [f"{e.key}: {x}" for x in check(e, m, c)]
            elif e.status != "superseded":
                problems.append(f"{e.key}: a history version must be superseded")
            if e.key in entries:
                problems.append(f"{e.key}: duplicate version")
            entries[e.key] = {"entry": e.model_dump(mode="json", by_alias=True, exclude_none=True),
                              "sources": [s.model_dump(include=set(_PUBLIC)) for s in m.sources]}
    if problems:
        raise BundleError("\n".join(problems))
    body = json.dumps(entries, sort_keys=True, ensure_ascii=False)
    return {"version": hashlib.sha256(body.encode()).hexdigest()[:12], "entries": entries}


def dumps(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


class Library:
    def __init__(self, bundle: dict[str, Any]):
        raw = bundle.get("entries", {})
        self._version = bundle.get("version", "")
        self._entries = {k: Entry.model_validate(v["entry"]) for k, v in raw.items()}
        self._sources = {k: v.get("sources", []) for k, v in raw.items()}

    def version(self) -> str:
        return self._version

    def _current(self) -> list[Entry]:
        return sorted((e for e in self._entries.values() if e.status == "current"), key=lambda e: e.id)

    def lookup(self, key_or_id: str, version: str | None = None) -> Entry | None:
        if "@" in key_or_id:
            return self._entries.get(key_or_id)
        if version is not None:
            return self._entries.get(f"{key_or_id}@{version}")
        return next((e for e in self._current() if e.id == key_or_id), None)

    def list(self, region: str | None = None, modality: str | None = None, finding_type: str | None = None,
             context: str | None = None) -> list[Entry]:
        want = {"region": region, "modality": modality, "finding_type": finding_type, "context": context}
        return [e for e in self._current()
                if all(v is None or v in getattr(e.applies_to, k) for k, v in want.items())]

    def siblings(self, entry: Entry) -> list[Entry]:
        return [e for e in self._current() if e.topic == entry.topic and e.id != entry.id]

    def find(self, name: str, version: str = "") -> Entry | None:
        """The current entry a model-named system is: its display, system name or an alias, normalised; a version,
        when given, must equal the edition."""
        n = norm(name)
        if not n:
            return None
        hits = [e for e in self._current() if n in {norm(x) for x in (e.display, e.system, *e.aliases)}]
        if version:
            hits = [e for e in hits if norm(e.edition) == norm(version)]
        return hits[0] if len(hits) == 1 else None

    def sources(self, key: str) -> list[dict]:
        return list(self._sources.get(key, []))

    def evaluate(self, key: str, given: dict[str, Any]) -> engine.Trace:
        e = self.lookup(key)
        if e is None or e.tier != 1:
            raise KeyError(key)
        return engine.evaluate(e, given)

    def known_text(self) -> str:
        """Lines for the matcher prompt's KNOWN SYSTEMS block, in its `- key: name` format."""
        return "\n".join(f"- {e.key}: {e.display} [aliases: {' | '.join(e.aliases)}]" for e in self._current()
                         if e.tier == 1)


@lru_cache(maxsize=1)
def _load() -> Library:
    try:
        return Library(json.loads(BUNDLE.read_text()))
    except Exception as ex:   # fail open: no pack cards, nothing else affected
        logger.error("[library] bundle failed to load (%s): %s", type(ex).__name__, str(ex)[:200])
        return Library({})


def get() -> Library:
    return _load()
```

- [ ] **Step 5: Write the build script and the folder README**

`backend/scripts/guidelines/build_bundle.py`:

```python
"""Compile guidelines/ into the committed bundle (library spec §8). Every entry passes gates 1–4 or nothing is
written. --check exits 1 when the committed bundle is stale.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py [--check]"""
import argparse
import json
import sys

from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, BundleError, compile_bundle, dumps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    try:
        text = dumps(compile_bundle())
    except BundleError as ex:
        print(ex, file=sys.stderr)
        return 1
    if args.check:
        ok = BUNDLE.exists() and BUNDLE.read_text() == text
        print("bundle up to date" if ok else "bundle stale: run scripts/guidelines/build_bundle.py")
        return 0 if ok else 1
    BUNDLE.write_text(text)
    print(f"wrote {BUNDLE} ({len(json.loads(text)['entries'])} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`guidelines/README.md`:

```markdown
# Guideline library sources

One folder per entry, named by the entry id (spec: `docs/superpowers/specs/2026-10-12-guideline-library-design.md`).

- `entry.json`: the entry (inputs, logic, outcomes, reference), facts in our own words, every fact with a locator.
- `manifest.json`: its sources, each with a role (`primary`, `amendment`, `explanatory`).
- `cases.json`: golden cases.
- `sources/<sha256>.pdf` and `.txt`: the publisher files and their `pdftotext -layout` text. Private repo only;
  never shipped (only the compiled bundle is).
- `history/<version>.json`: superseded versions, kept so old report stamps resolve.
- `evidence.md` and `review.md`: the gate 5 Jev table and the gate 6 hand read.

After any change: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py`, then
`PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py -q`.
```

- [ ] **Step 6: Build the (empty) bundle and run the tests**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py && PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py tests/test_library_schema.py tests/test_library_engine.py tests/test_library_partial.py tests/test_library_verify.py -q`
Expected: `wrote …guideline_bundle.json (0 entries)`, then all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/bundle.py backend/scripts/guidelines/build_bundle.py \
  backend/src/rapid_reports_ai/resources/guideline_bundle.json guidelines/README.md backend/tests/conftest.py \
  backend/tests/test_library_bundle.py
git commit -m "feat(library): compiled bundle, Library interface, build script, drift test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: TNM re-expressed in the schema (schema proof, part 1)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/tnm_schema.py`
- Test: `backend/tests/test_library_tnm.py`

**Interfaces:**
- Consumes: `copilot/tnm.py` (`sites`, `axes`, `variants`, `stage`, `proposal`, `_options`, `_tables`, `TAG`, `SOURCE`), `registry.slug`, Tasks 1–4.
- Produces: `tnm_schema.staged_sites() -> list[str]`, `site_entry(site) -> Entry`, `MANIFEST`. Not added to the bundle in this slice; the runtime TNM path is unchanged.

The proof: every staged site becomes a plain tier 1 entry, with no TNM-specific attribute, whose stage step is a fully enumerated `table` built from the verified lookup. The engine must reproduce all 6,479 combinations (36 sites; counted on 2026-10-12), and the rendered classification must equal `tnm.proposal(...)`'s byte for byte. TX/NX/MX stay ordinary enum options because UICC defines them as categories.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_library_tnm.py`:

```python
from itertools import product

from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import tnm_schema as TS
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Cases, GoldenCase
from rapid_reports_ai.hybrid_stack.copilot.library.verify import check


def _golden(e):
    """One case per outcome, from the first row that reaches it."""
    t = e.step("stage")
    keys, seen, out = t.keys, set(), []
    for r in t.rows:
        if r.result not in seen:
            seen.add(r.result)
            out.append(GoldenCase(name=r.result, origin="ours", inputs=dict(zip(keys, r.match)), outcome=r.result))
    return Cases(cases=out)


def test_every_staged_site_passes_the_gates():
    assert len(TS.staged_sites()) == 36
    for site in TS.staged_sites():
        e = TS.site_entry(site)
        assert check(e, TS.MANIFEST, _golden(e)) == [], site


def test_the_engine_reproduces_every_verified_combination():
    n = 0
    for site in TS.staged_sites():
        e = TS.site_entry(site)
        for h in tnm.variants(site) or [""]:
            for t, nn, m in product(*(tnm._options(site, a) for a in "TNM")):
                given = {"T": t, "N": nn, "M": m, **({"histology": h} if h else {})}
                tr = E.evaluate(e, given)
                cls = E.render(e, tr, e.outcome(tr.outcome).classification)
                assert cls == tnm.proposal(site, given).classification, (site, given)
                n += 1
    assert n == 6479
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_tnm.py -q`
Expected: FAIL with `ImportError ... tnm_schema`.

- [ ] **Step 3: Write the generator**

`backend/src/rapid_reports_ai/hybrid_stack/copilot/library/tnm_schema.py`:

```python
"""UICC TNM 9 re-expressed as library entries (library spec §12, schema proof). Each staged site becomes an ordinary
tier 1 entry: T, N, M (and histology where the stage table varies by it) as enum inputs, and a stage step that is a
fully enumerated table built from the rebuilt, hand-checked lookup in copilot/tnm.py. No TNM-specific attribute: the
X categories are ordinary options, as UICC defines them. Not in the bundle yet; the runtime TNM path is unchanged."""
from __future__ import annotations

from itertools import product

from .. import tnm
from ..registry import slug
from .schema import Entry, Manifest, SourceDoc

MANIFEST = Manifest(sources=[SourceDoc(id="S1", role="primary", title=tnm.SOURCE, issuer="UICC", edition="9")])


def staged_sites() -> list[str]:
    return [s for s in tnm.sites() if tnm.axes(s) == list("TNM") and tnm._tables(s)]


def _sid(stage: str) -> str:
    return "stage-" + slug(stage)


def site_entry(site: str) -> Entry:
    vs = tnm.variants(site)
    opts = {a: tnm._options(site, a) for a in "TNM"}
    loc = {"source": "S1", "section": site}
    rows, stages = [], set()
    for h in vs or [""]:
        for t, n, m in product(opts["T"], opts["N"], opts["M"]):
            st = tnm.stage(site, h, t, n, m)
            if st:
                stages.add(st)
            rows.append({"match": ([h] if vs else []) + [t, n, m], "result": _sid(st) if st else "no-stage"})
    outcomes = [{"id": _sid(s), "classification": f"c{{T}} {{N}} {{M}}, {s} ({tnm.TAG})", "locator": loc}
                for s in sorted(stages)]
    outcomes.append({"id": "no-stage", "classification": f"c{{T}} {{N}} {{M}} ({tnm.TAG})", "locator": loc})
    inputs = [{"id": a, "label": f"{a} category", "type": "enum", "options": opts[a]} for a in "TNM"]
    if vs:
        inputs.append({"id": "histology", "label": "Histology", "type": "enum", "options": vs})
    return Entry.model_validate({
        "id": f"tnm-{slug(site)}", "version": "9.0", "topic": f"tnm-{slug(site)}", "issuer": "UICC",
        "system": tnm.SOURCE, "display": f"TNM {site}", "edition": "9", "tier": 1,
        "applies_to": {"finding_type": ["primary malignancy"]},
        "inputs": inputs,
        "logic": [{"step": "table", "id": "stage", "keys": (["histology"] if vs else []) + ["T", "N", "M"],
                   "rows": rows, "locator": loc}],
        "result": "stage", "outcomes": outcomes})
```

The `histology` input sits last in `inputs` while the table lists it first among `keys`; both are fine (inputs are resolved before any step runs).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_tnm.py -q`
Expected: PASS. If a site fails `check` with an unfilled placeholder or a duplicate outcome id, report it in the task summary with the site name: it is a real finding about the schema, not something to special-case.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/tnm_schema.py backend/tests/test_library_tnm.py
git commit -m "test(library): TNM 9 re-expressed in the schema reproduces all 6,479 combinations

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Gate 5 tooling (fact descriptions and the Jev evidence script)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py`
- Create: `backend/scripts/guidelines/jev_evidence.py`
- Test: `backend/tests/test_library_describe.py`

**Interfaces:**
- Consumes: Tasks 1–2; `copilot/jev.py` (`evidence(source, claims) -> list[float]`, `EVIDENCE_MIN`).
- Produces: `describe.facts(entry) -> list[tuple[str, str, Locator]]` (field id, plain-English claim, locator), used by the script and by the hand read.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_library_describe.py`:

```python
from rapid_reports_ai.hybrid_stack.copilot.library.describe import facts


def test_facts_cover_every_located_item(toy_entry):
    got = {fid: claim for fid, claim, _ in facts(toy_entry)}
    assert got["size_band"] == "Diameter bands: <6 mm; 6-8 mm; >8 mm"
    assert got["plan.case2"] == ("solid nodule …, … risk → CT at 12 months: when Nodule type is solid and size_band "
                                 "is 6-8 mm and Patient risk is low")
    assert got["outcome.pet"] == "solid nodule … → PET-CT"
    assert got["reference.sum.1"] == "A toy guideline for tests."
    assert all(loc is not None for _, _, loc in facts(toy_entry))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_describe.py -q`
Expected: FAIL with `ModuleNotFoundError ... describe`.

- [ ] **Step 3: Write `describe.py`**

```python
"""Plain-English claims for each located fact of an entry (gate 5 and the hand read). Jev judges each claim against
the source text at its locator; the wording only has to be faithful, not elegant."""
from __future__ import annotations

from .engine import PH
from .schema import (AdjustStep, All, AnyOf, BandStep, Cond, CountGte, DeriveStep, Entry, Expr, Locator, NoneOf, Num,
                     RulesStep, ScoreStep, TableStep)


def _name(e: Entry, ref: str) -> str:
    i = e.input(ref)
    return i.label if i is not None else ref


def _val(e: Entry, ref: str, v) -> str:
    s = e.step(ref)
    if isinstance(s, BandStep):
        return next((b.label for b in s.bands if b.id == v), str(v))
    return str(v)


def _expr(e: Entry, x: Expr) -> str:
    if isinstance(x, Cond):
        if x.state is not None:
            return f"{_name(e, x.ref)} is {x.state.replace('_', ' ')}"
        if x.in_ is not None:
            return f"{_name(e, x.ref)} is one of {', '.join(_val(e, x.ref, v) for v in x.in_)}"
        return f"{_name(e, x.ref)} is {_val(e, x.ref, x.eq)}"
    if isinstance(x, All):
        return " and ".join(_expr(e, k) for k in x.all)
    if isinstance(x, AnyOf):
        return "(" + " or ".join(_expr(e, k) for k in x.any) + ")"
    if isinstance(x, NoneOf):
        return "none of (" + "; ".join(_expr(e, k) for k in x.none) + ")"
    assert isinstance(x, CountGte)
    return f"at least {x.count_gte} of (" + "; ".join(_expr(e, k) for k in x.of) + ")"


def _num(n: Num) -> str:
    if n.ref is not None:
        return n.ref
    if n.const is not None:
        return f"{n.const:g}"
    a = [_num(x) for x in n.args]
    sym = {"add": " + ", "sub": " - ", "mul": " × ", "div": " / ", "pow": " ^ "}
    return f"({sym[n.op].join(a)})" if n.op in sym else f"{n.op}({a[0]})"


def _result(e: Entry, r: str) -> str:
    o = e.outcome(r)
    if o is None:
        return r
    cls = PH.sub("…", o.classification)
    return f"{cls} → {o.recommendation}" if o.recommendation else cls


def facts(e: Entry) -> list[tuple[str, str, Locator]]:
    out: list[tuple[str, str, Locator]] = []
    for s in e.logic:
        if isinstance(s, RulesStep):
            out += [(f"{s.id}.case{n}", f"{_result(e, c.result)}: when {_expr(e, c.when)}", c.locator)
                    for n, c in enumerate(s.cases)]
        elif isinstance(s, BandStep):
            out.append((s.id, f"{_name(e, s.ref)} bands: " + "; ".join(b.label for b in s.bands), s.locator))
        elif isinstance(s, TableStep):
            out += [(f"{s.id}.row{n}", f"{_result(e, r.result)}: when "
                     + " and ".join(f"{_name(e, k)} is {_val(e, k, c)}" for k, c in zip(s.keys, r.match)), s.locator)
                    for n, r in enumerate(s.rows)]
        elif isinstance(s, ScoreStep):
            terms = "; ".join(f"{t.coef:g} × {t.ref}" + (f" is {t.eq}" if t.eq is not None else "") for t in s.terms)
            out.append((s.id, f"{s.kind} model: intercept {s.intercept:g}; {terms}", s.locator))
        elif isinstance(s, DeriveStep):
            out.append((s.id, f"{s.id} = {_num(s.expr)}", s.locator))
        elif isinstance(s, AdjustStep):
            out.append((s.id, f"{s.pick} of {', '.join(s.of)} in the order {' < '.join(s.order)}"
                        + (f", at least {s.floor}" if s.floor else "") + (f", at most {s.ceiling}" if s.ceiling else ""),
                        s.locator))
    for o in e.outcomes:
        out.append((f"outcome.{o.id}", _result(e, o.id), o.locator))
        out += [(f"outcome.{o.id}.caveat{n}", c, o.locator) for n, c in enumerate(o.caveats)]
    out += [(f"reference.{f.id}", getattr(f, "text", None) or f"{f.title}: " + " | ".join(f.columns), f.locator)
            for f in e.reference.fields()]
    return [x for x in out if x[2] is not None]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_describe.py -q`
Expected: PASS. If the expected strings differ only in wording you judge clearer, change the test and the code together; the test pins whatever wording you settle on.

- [ ] **Step 5: Write the evidence script**

`backend/scripts/guidelines/jev_evidence.py`:

```python
"""Gate 5 (library spec §8): Jev checks each located fact of an entry against its source text (the locator's page
and its neighbours, from the manifest's text_file). Prints a markdown table; save it as <entry>/evidence.md.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/jev_evidence.py ../guidelines/<entry-id>"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot import jev as J  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.describe import facts  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry, Manifest  # noqa: E402


def source_text(d: Path, m: Manifest, source: str, page: int | None) -> str:
    src = next(s for s in m.sources if s.id == source)
    pages = (d / src.text_file).read_text().split("\f")
    if page is None:
        return "\n".join(pages)
    return "\n".join(pages[max(page - 2, 0):page + 1])      # 1-based page, with one page either side


async def main(d: Path) -> int:
    e = Entry.model_validate_json((d / "entry.json").read_text())
    m = Manifest.model_validate_json((d / "manifest.json").read_text())
    groups: dict[tuple, list] = {}
    for fid, claim, loc in facts(e):
        groups.setdefault((loc.source, loc.page), []).append((fid, claim))
    rows = []
    for (source, page), items in groups.items():
        scores = await J.evidence(source_text(d, m, source, page), [("", f"{e.display}: {c}") for _, c in items])
        rows += [(fid, c, s, source, page) for (fid, c), s in zip(items, scores)]
    low = 0
    print(f"# Gate 5: Jev evidence for {e.key}\n\n| field | claim | source | Jev | |\n|---|---|---|---|---|")
    for fid, c, s, source, page in rows:
        flag = s < J.EVIDENCE_MIN
        low += flag
        print(f"| {fid} | {c} | {source} p{page} | {s:.2f} | {'**check**' if flag else ''} |")
    print(f"\n{len(rows)} facts; {low} below {J.EVIDENCE_MIN}: read each against the source in review.md.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]).resolve())))
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/describe.py backend/scripts/guidelines/jev_evidence.py \
  backend/tests/test_library_describe.py
git commit -m "feat(library): gate 5 tooling, plain-English facts and the Jev evidence script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Authoring procedure (used by Tasks 8, 9 and 10)

Each entry is written by hand from its primary source. Values in this plan are orientation only: **the source wins every disagreement**, and an implementer who finds the plan's sketch wrong records that in `review.md`.

1. **Get the source.** `mkdir -p guidelines/<id>/sources`. Download the PDF into the session scratchpad with `curl -L -o <scratchpad>/<id>.pdf '<url>'`. If that returns HTML or a login page, try `mcp__claude_ai_Firecrawl_MCP_Server__firecrawl_scrape` on the article page to find the PDF link. If that also fails, **stop and ask Hassan to drop the PDF into `guidelines/<id>/sources/`**. Do not substitute a secondary source.
2. **File it.** Compute `shasum -a 256 <file>` and move the file to `guidelines/<id>/sources/<sha256>.pdf`. Then run `pdftotext -layout guidelines/<id>/sources/<sha256>.pdf guidelines/<id>/sources/<sha256>.txt`. Pages are split by form feeds, and locator page numbers are 1-based PDF pages.
3. **Write `manifest.json`.** List each source with `id`, `role`, `title`, `issuer`, `edition`, `url`, `sha256`, `file`, `text_file` and `retrieved` (today's date).
4. **Write `entry.json`:**
   - Inputs come first. Give each one `how_stated` (how a dictation phrases it) and allow only the states the source recognises.
   - Then the logic, with a locator on every band, step, rules case and outcome.
   - Write everything in our own words: the classification and the recommendation as a radiologist would put them in a report, each under about 25 words.
   - Use `caveats` for the conditions the source attaches to an outcome.
   - The reference holds a 3–5 line summary, the definitions a reader needs, and the pitfalls (exclusions and "does not apply to …").
5. **Write `cases.json`:**
   - Every worked example the source gives, with `origin: "source"`.
   - Then cases of our own (`origin: "ours"`) so that:
     - every outcome is reached;
     - each band edge is tested on both sides;
     - at least two cases leave an input unknown and assert `needed`;
     - every formula step's value is checked in at least two cases.
6. **Run gates 1–4:** `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py`. Fix every problem it prints by correcting the entry, never by weakening a gate.
7. **Run gate 5:** `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/jev_evidence.py ../guidelines/<id> > ../guidelines/<id>/evidence.md`.
8. **Gate 6, the hand read.** Read the entry side by side with the source text. Write `guidelines/<id>/review.md` with three parts:
   - a checklist row for every outcome, rules case and band, marked ✓ or with the correction;
   - each Jev `check` item resolved;
   - a short **"For Hassan"** list of boundary items only: judgement calls the source leaves open, plus any departure from this plan's sketch.
9. **Rebuild and run the tests.** Rebuild the bundle, then run `PYTHONPATH=src .venv/bin/pytest tests/test_library_bundle.py -q`. The drift test must pass.

---

### Task 8: Fleischner Society 2017 pack (a `table`)

**Files:**
- Create: `guidelines/fleischner-pulmonary-nodule/{entry.json,manifest.json,cases.json,evidence.md,review.md,sources/…}`
- Modify: `backend/src/rapid_reports_ai/resources/guideline_bundle.json` (rebuilt)

**Interfaces:**
- Produces: entry `fleischner-pulmonary-nodule@2017.1`, topic `pulmonary-nodule-incidental` (shared with BTS, Task 10, so the two are siblings), display `Fleischner Society 2017`, issuer `Fleischner Society`, edition `2017`, aliases `["fleischner", "fleischner society", "fleischner 2017", "fleischner criteria"]`, applies_to `{"region": ["chest"], "modality": ["CT"], "finding_type": ["pulmonary nodule"], "context": ["incidental"]}`.

**Source:** MacMahon H, et al. "Guidelines for Management of Incidental Pulmonary Nodules Detected on CT Images: From the Fleischner Society 2017." *Radiology* 2017;284:228–243. doi:10.1148/radiol.2017161659 (article: https://pubs.rsna.org/doi/10.1148/radiol.2017161659; PDF: https://pubs.rsna.org/doi/pdf/10.1148/radiol.2017161659).

**Shape (verify every value against the source's Table 1):**
- **Inputs:**
  - `nodule_type`: enum `solid` | `ground-glass` | `part-solid`.
  - `count`: enum `single` | `multiple`. The host's cross-lesion context, stated as how many nodules were dictated.
  - `diameter_mm`: number, mm. `how_stated`: "average of long and short axis, as dictated".
  - `risk`: enum `low` | `high`, with prerequisite `{"ref": "nodule_type", "eq": "solid"}`. Risk applies to solid nodules only.
- **Rounding.** The source rounds measurements to the nearest millimetre. Encode that as band edges rather than a formula, as one band step `size_band` with no `round` operator:
  - `lt6`: "<6 mm", max 5.5, exclusive;
  - `6to8`: "6–8 mm", from 5.5 inclusive to 8.5 exclusive;
  - `gt8`: ">8 mm", from 8.5 inclusive.

  Cite the rounding statement in the band step's locator. Subsolid rows that say "≥6 mm" list both `6to8` and `gt8`.
- **Logic.** One `table` step `management` with keys `[nodule_type, count, size_band, risk]`. That is 24 rows: solid 2 × 3 × 2; ground-glass and part-solid 2 × 3 × `@not_applicable` each. The result is `management`.
- **Outcomes.** One per distinct recommendation in Table 1. Carry the table's comments as caveats where they attach to a row (e.g. the solid-component condition for part-solid nodules).
- **Exclusions.** These are **pitfalls plus a caveat on every outcome, not inputs**, so they are not asked on every card: lung cancer screening, age under 35, immunocompromise, and a known primary cancer. Raise this choice in "For Hassan".
- **Not in this slice:** volumetric thresholds (mm³). Add a pitfall saying volumes are not supported yet.

- [ ] **Step 1: Follow the authoring procedure, steps 1–9.**
- [ ] **Step 2: Confirm the gates and tests pass.**

Run: `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py --check && PYTHONPATH=src .venv/bin/pytest tests/test_library_*.py -q`
Expected: `bundle up to date`, then all PASS.

- [ ] **Step 3: Commit**

```bash
git add guidelines/fleischner-pulmonary-nodule backend/src/rapid_reports_ai/resources/guideline_bundle.json
git commit -m "data(library): Fleischner Society 2017 pack (table), gates 1-6

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Bosniak 2019 pack (`rules`)

**Files:**
- Create: `guidelines/bosniak-renal-cyst/{entry.json,manifest.json,cases.json,evidence.md,review.md,sources/…}`
- Modify: `backend/src/rapid_reports_ai/resources/guideline_bundle.json`

**Interfaces:**
- Produces: entry `bosniak-renal-cyst@2019.1`, topic `cystic-renal-mass`, display `Bosniak 2019`, issuer the paper's author group as the source names it, edition `2019`, aliases `["bosniak", "bosniak classification", "bosniak 2019", "bosniak v2019"]`, applies_to `{"region": ["abdomen"], "modality": ["CT"], "finding_type": ["renal cyst", "cystic renal mass"], "context": []}`.

**Source:** Silverman SG, et al. "Bosniak Classification of Cystic Renal Masses, Version 2019: An Update Proposal and Needs Assessment." *Radiology* 2019;292:475–488. doi:10.1148/radiol.2019182646. Verify the DOI and the page range when you download.

**Shape (verify against the source's CT classification table and definitions):**
- **Scope:** CT features only. MRI features are a pitfall ("MRI criteria not encoded in this version").
- **Inputs:** one per CT feature the table uses, each an enum whose options are the source's own categories. These include wall thickness, septa number, septa thickness, enhancement, protrusions and their size and angle, and attenuation for homogeneous masses.
  - Use `states: ["not_assessable"]` only where the source itself allows a feature to be indeterminate.
  - Numbers the source bands (HU, mm) are number inputs with band steps, edges exactly as the source states them.
- **Logic:**
  - One `rules` step `class`, using `all`, `any`, `none` and `count_gte` as the definitions require, with result `class`.
  - Each class appears once per distinct definition in the table. Class II has several distinct definitions, so it has several cases leading to the same outcome.
  - Gate 2 must prove the cases are mutually exclusive and exhaustive. Where the source leaves a combination undefined, add a case leading to an outcome `unclassifiable` ("Features do not fit a Bosniak 2019 class; manage on its features") and list each such combination in "For Hassan".
- **Outcomes:** classes I, II, IIF, III and IV (plus `unclassifiable` if needed). The recommendation is the management the source gives for each class, in our own words.

- [ ] **Step 1: Follow the authoring procedure, steps 1–9.**
- [ ] **Step 2: Run the gates and tests** (same commands as Task 8, Step 2). Expected: up to date, all PASS.
- [ ] **Step 3: Commit**

```bash
git add guidelines/bosniak-renal-cyst backend/src/rapid_reports_ai/resources/guideline_bundle.json
git commit -m "data(library): Bosniak 2019 pack (rules), gates 1-6

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: BTS 2015 pulmonary nodule pack (derive → score → band → rules)

**Files:**
- Create: `guidelines/bts-pulmonary-nodule/{entry.json,manifest.json,cases.json,evidence.md,review.md,sources/…}`
- Modify: `backend/src/rapid_reports_ai/resources/guideline_bundle.json`

**Interfaces:**
- Produces: entry `bts-pulmonary-nodule@2015.1`, topic `pulmonary-nodule-incidental` (sibling of Fleischner), display `BTS 2015`, issuer `British Thoracic Society`, edition `2015`, aliases `["bts nodule", "bts nodule guideline", "bts 2015", "british thoracic society nodule guideline"]`, applies_to `{"region": ["chest"], "modality": ["CT"], "finding_type": ["pulmonary nodule"], "context": ["incidental"]}`.

**Sources:**
- **S1 (primary):** Callister MEJ, et al. "British Thoracic Society guidelines for the investigation and management of pulmonary nodules." *Thorax* 2015;70(Suppl 2):ii1–ii54. doi:10.1136/thoraxjnl-2015-207168. Check whether the BTS website hosts a free PDF.
- **Brock model:** if the BTS document prints the Brock (PanCan) coefficients, cite it. If it only adopts the model, add McWilliams A, et al. *N Engl J Med* 2013;369:910–919 (doi:10.1056/NEJMoa1214726) as a second `primary` source, and say so in "For Hassan". The guideline formally adopts it, so it is part of BTS's own rule, not a second issuing body.

**Shape (verify every threshold against the source's algorithms):**
- **Scope:** the solid-nodule management algorithm, up to the decision for PET-CT, plus growth assessment by volume doubling time. Herder scoring after PET-CT is out of scope: the outcome that leads to it says "PET-CT, then Herder risk assessment". Volumetric thresholds are out of scope too, and get a pitfall.
- **Inputs:**
  - diameter (mm);
  - the Brock model's inputs: age, sex, family history of lung cancer, emphysema, nodule type, upper-lobe location, nodule count (host context, a number) and spiculation;
  - for growth: `prior_volume_mm3`, `current_volume_mm3` and `interval_days`, all with prerequisite `{"ref": "prior_study", "eq": true}` on a boolean `prior_study`.
- **Logic, in order:**
  1. `derive` steps for the Brock size transform and the centred age and count terms, exactly as the published model defines them.
  2. `derive` `vdt_days` = ln(2) × interval ÷ ln(current ÷ prior).
  3. `score` `brock` (logistic).
  4. `band` steps on diameter, on `brock` (the source's probability cut-off) and on `vdt_days` (the source's VDT thresholds; shrinkage, a negative VDT, gets its own band).
  5. `rules` `pathway`, which is the result.
- **Golden cases:**
  - at least two Brock values computed with the published calculator, recorded in `steps.brock`. If no calculator page can be reached, compute them by hand from the coefficients in a short separate snippet (not the engine) and say so in `review.md`;
  - cases either side of every diameter, Brock and VDT cut-off;
  - a no-prior-study case, where VDT is `not_applicable`.

- [ ] **Step 1: Follow the authoring procedure, steps 1–9.**
- [ ] **Step 2: Run the gates and tests** (same commands as Task 8, Step 2). Expected: up to date, all PASS.
- [ ] **Step 3: Commit**

```bash
git add guidelines/bts-pulmonary-nodule backend/src/rapid_reports_ai/resources/guideline_bundle.json
git commit -m "data(library): BTS 2015 nodule pack (derive, score, band, rules), gates 1-6

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Checkpoint: schema proof (stop for Hassan)

**Spec gate (§12.1):** all four systems fit with no special-case attributes.

- [ ] **Step 1: Write the report.** `docs/superpowers/handover/2026-10-12-copilot-evidence/schema_proof.md` should cover:
  - for each of the four systems, which step types it used, and any place the schema felt strained (with the exact workaround);
  - the TNM result (6,479 of 6,479);
  - the gate 5 flags and how each was resolved;
  - the merged "For Hassan" lists from the three `review.md` files.
- [ ] **Step 2: Commit the report, then stop.** Give Hassan the boundary items. Continue to Task 11 only on his go-ahead. If the schema needed a special case, the next step is a schema change, not Task 11.

---

### Task 11: Pack preview (model settles, code checks, engine evaluates)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py`
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/preview.py` (public `confirm_quotes`)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py` (`Preview.possible`, `Preview.trace`, `Card.siblings`)
- Test: `backend/tests/test_library_pack_preview.py`

**Interfaces:**
- Consumes: `preview.confirm_quotes(model: dict[str, Settled], findings: str, history: str) -> set[str]`; `engine.evaluate`, `engine.render`; `types.Preview`, `Proposal`, `Settled`, `Entry as CardEntry`, `Branch`, `Input`, `GuidelineContent`, `Publication`, `Source`.
- Produces: `pack_preview.PACK_BRANCH = "Pack"`; `async preview_pack(entry, findings, history, answered: dict[str, str]) -> Preview`; `as_entry(entry, sources: list[dict]) -> types.Entry`; `display_options(entry, input_def) -> list[str]`; `RawItem`, `RawSettle`; `_call(system, prompt) -> RawSettle` (patched in tests).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_library_pack_preview.py`:

```python
import pytest

from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP

FINDINGS = "7 mm solid nodule in the right upper lobe."


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


@pytest.fixture
def jev(monkeypatch):
    st = {"score": 0.9, "fail": False, "calls": 0}

    async def post(payload, key, timeout, transport=None):
        st["calls"] += 1
        if st["fail"]:
            raise TimeoutError("jev slow")
        return _Resp({"answers": {k: {"noul": st["score"]} for k in payload["questions"]}})
    monkeypatch.setattr(P, "jev_post", post)
    return st


def _model(monkeypatch, *items):
    async def call(system, prompt):
        return PP.RawSettle(settled=[PP.RawItem(**i) for i in items])
    monkeypatch.setattr(PP, "_call", call)


KIND = {"input": "kind", "value": "solid", "quote": "solid"}
SIZE = {"input": "size", "value": 7, "quote": "7 mm"}


async def test_settled_inputs_reach_a_proposal_copied_from_the_entry(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {})
    assert [(s.input, s.value) for s in out.settled] == [("kind", "solid"), ("size", "7 mm"), ("risk", "high")]
    assert out.missing == [] and out.proposal.recommendation == "CT at 6 months"
    assert out.proposal.classification == "Toy 2020 · solid nodule 6-8 mm, high risk"
    assert out.proposal.line == "Toy 2020: solid nodule 6-8 mm, high risk."
    assert out.trace["outcome"] == "ct6" and jev["calls"] == 0       # every quote verbatim: no Jev call


async def test_missing_input_shows_possible_outcomes(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {})
    assert out.proposal is None and out.missing == ["risk"]
    assert out.possible == ["solid nodule 6-8 mm, … risk"] * 2      # ct12 and ct6 render alike while risk is unknown


@pytest.mark.parametrize("value,quote,ok", [(12, "1.2 cm", True), (120, "12 mm", False), (9, "7 mm", False)])
async def test_number_must_come_from_its_quote(toy_entry, monkeypatch, jev, value, quote, ok):
    _model(monkeypatch, KIND, {"input": "size", "value": value, "quote": quote})
    out = await PP.preview_pack(toy_entry, f"{quote} solid nodule.", "", {})
    assert ("size" in {s.input for s in out.settled}) is ok


async def test_bad_options_and_disallowed_states_are_dropped(toy_entry, monkeypatch, jev):
    _model(monkeypatch, {"input": "kind", "value": "cystic", "quote": "cystic"},
           {"input": "margin", "state": "absent", "quote": "no spiculation"},
           {"input": "ghost", "value": "x", "quote": "x"})
    out = await PP.preview_pack(toy_entry, "cystic lesion, no spiculation, x", "", {})
    assert out.settled == [] and "kind" in out.missing


async def test_the_radiologists_answer_wins(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {"risk": "low"})
    risk = next(s for s in out.settled if s.input == "risk")
    assert (risk.value, risk.quote) == ("low", "") and out.proposal.recommendation == "CT at 12 months"


async def test_band_label_answer(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND)
    out = await PP.preview_pack(toy_entry, "solid nodule", "", {"size": "6-8 mm", "risk": "low"})
    assert out.proposal.recommendation == "CT at 12 months"


async def test_unconfirmed_quote_is_asked(toy_entry, monkeypatch, jev):
    jev["fail"] = True
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "heavy smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {})
    assert out.missing == ["risk"] and out.proposal is None


async def test_model_failure_uses_answers_only(toy_entry, monkeypatch, jev):
    async def boom(system, prompt):
        raise TimeoutError("slow")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {"kind": "subsolid"})
    assert out.proposal.recommendation == "CT in 12 months"


async def test_entry_defect_gives_no_proposal(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)

    def broken(entry, given):
        raise E.EvaluationError("two cases hold")
    monkeypatch.setattr(PP.engine, "evaluate", broken)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {})
    assert out.proposal is None


def test_as_entry_shows_inputs_as_choices(toy_entry):
    e = PP.as_entry(toy_entry, [{"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY",
                                 "edition": "2020", "url": "https://example.org/toy"}])
    b = e.content.branches[0]
    assert (e.key, e.status, b.name, b.state) == ("toy-nodule@1.0", "verified", "Pack", "checked")
    opts = {i.id: i.options for i in b.inputs}
    assert opts["size"] == ["<6 mm", "6-8 mm", ">8 mm"] and opts["margin"] == ["smooth", "spiculated", "Not assessable"]
    assert e.sources[0].url == "https://example.org/toy"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_pack_preview.py -q`
Expected: FAIL with `ImportError ... pack_preview`.

- [ ] **Step 3: Expose `confirm_quotes` in `preview.py`**

Rename `_check`'s body to a public function that takes no branch, and keep `_check` as a thin wrapper so existing callers and tests are untouched:

```python
async def confirm_quotes(model: dict[str, Settled], findings: str, history: str) -> set[str]:
    """The model-settled inputs whose quoted evidence is confirmed: by code when the quote is verbatim in the
    dictation, else by Jev. No quote, no confirmation; a Jev failure confirms none of the quotes it was asked about
    (ask, never assume)."""
    ids = [i for i, s in model.items() if s.quote.strip()]
    confirmed = {i for i in ids if _verbatim(model[i].quote, findings, history)}
    ask = [i for i in ids if i not in confirmed]
    if not ask:
        return confirmed
    try:
        scores = await _jev_settled(findings, history, [model[i].quote.strip() for i in ask])
    except Exception as ex:
        logger.info("[copilot.preview] settled check failed (%s): %d unconfirmed model value(s) asked",
                    type(ex).__name__, len(ask))
        return confirmed
    return confirmed | {i for n, i in enumerate(ask) if scores.get(f"s{n}", 0.0) >= SETTLED_MIN}


async def _check(model: dict[str, Settled], b: Branch, findings: str, history: str) -> set[str]:
    return await confirm_quotes(model, findings, history)
```

- [ ] **Step 4: Add the type fields in `types.py`**

In `Preview`, add after `proposal`:

```python
    possible: list[str] = Field(default_factory=list)   # library packs: outcomes still possible, rendered
    trace: dict[str, Any] | None = None                 # library packs: the engine trace behind the proposal
```

In `Card`, add after `status`:

```python
    siblings: list[str] = Field(default_factory=list)   # library packs: other bodies' packs on the same topic
```

Add `from typing import Any, Literal` (replacing `from typing import Literal`).

- [ ] **Step 5: Write `pack_preview.py`**

```python
"""Preview for a library pack (library spec §4). The model only settles inputs, each with the shortest verbatim span
that settles it; code checks every value (a real option, an allowed state, a number present in its quote) and every
quote (verbatim, else Jev); the radiologist's answers win; the engine evaluates. Every word of the proposal comes
from the entry: no model-written line, no output index."""
from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel, Field

from ....enhancement_utils import _run_agent_with_model
from ....report_reconcile import QWEN
from .. import preview as P
from .. import registry as R
from ..types import Branch, Entry as CardEntry, GuidelineContent, Input, Preview, Proposal, Publication, Settled, Source
from . import engine
from .schema import BandStep, Entry, InputDef, InputValue

logger = logging.getLogger(__name__)

PACK_BRANCH = "Pack"
TIMEOUT_S = 10.0
_NUM = re.compile(r"\d+(?:\.\d+)?")
_STATE_LABEL = {"absent": "Absent", "not_assessable": "Not assessable"}

SETTLE_SYS = """You settle the inputs of one published radiology classification system from a radiologist's dictation. INPUTS lists each input's id, type and allowed values: use nothing else.
For each input the FINDINGS or CLINICAL HISTORY state, return one item:
- input: the input's id;
- state: "present" when the dictation gives its value; "absent" when the dictation says the feature is not there and the input lists absent; "not_assessable" when the dictation says it cannot be assessed and the input lists not_assessable;
- value: when present, for an enum exactly one of its options, for a boolean true or false, for a number the number in the input's unit (centimetres converted to millimetres when the unit is mm); otherwise null;
- quote: the shortest span, copied verbatim from the FINDINGS or CLINICAL HISTORY, that settles it.
Leave out every input the dictation does not state: never settle a value from what is usual or likely, and never invent an input, option or state."""


class RawItem(BaseModel):
    input: str
    state: str = "present"
    value: str | float | bool | None = None
    quote: str = ""


class RawSettle(BaseModel):
    settled: list[RawItem] = Field(default_factory=list)


def _bands_for(e: Entry, i: InputDef) -> list:
    return next((s.bands for s in e.logic if isinstance(s, BandStep) and s.ref == i.id), [])


def display_options(e: Entry, i: InputDef) -> list[str]:
    base = i.options if i.type == "enum" else ["Yes", "No"] if i.type == "boolean" else [b.label for b in _bands_for(e, i)]
    return [*base, *(_STATE_LABEL[s] for s in i.states)]


def _show(e: Entry, i: InputDef, v: InputValue) -> str:
    if v.state != "present":
        return _STATE_LABEL.get(v.state, v.state)
    if i.type == "boolean":
        return "Yes" if v.value else "No"
    if i.type == "number":
        if v.band is not None:
            return next((b.label for b in _bands_for(e, i) if b.id == v.band), v.band)
        return f"{float(v.value):g} {i.unit}".strip()
    return str(v.value)


def _answer(e: Entry, i: InputDef, s: str) -> InputValue | None:
    """A radiologist's choice, as display_options offers it (or a typed number)."""
    s = s.strip()
    for st, label in _STATE_LABEL.items():
        if s == label:
            return InputValue(state=st) if st in i.states else None
    if i.type == "enum":
        return InputValue(value=s) if s in i.options else None
    if i.type == "boolean":
        return {"Yes": InputValue(value=True), "No": InputValue(value=False)}.get(s)
    band = next((b for b in _bands_for(e, i) if b.label == s), None)
    if band is not None:
        return InputValue(band=band.id)
    try:
        return InputValue(value=float(s))
    except ValueError:
        return None


def _value(i: InputDef, item: RawItem) -> InputValue | None:
    """The model's value if it is a real one: an option, a boolean, an allowed state, or a number that appears in its
    quote (or is ten times one, when the quote is in cm and the unit mm)."""
    if item.state in _STATE_LABEL:
        return InputValue(state=item.state) if item.state in i.states else None
    if item.state != "present" or item.value is None:
        return None
    if i.type == "enum":
        m = {R.norm(o): o for o in i.options}
        hit = m.get(R.norm(str(item.value)))
        return InputValue(value=hit) if hit is not None else None
    if i.type == "boolean":
        return InputValue(value=item.value) if isinstance(item.value, bool) else None
    try:
        x = float(item.value)
    except (TypeError, ValueError):
        return None
    nums = [float(n) for n in _NUM.findall(item.quote)]
    cm = i.unit == "mm" and re.search(r"\bcm\b", item.quote, re.I) is not None
    ok = any(abs(x - n) < 1e-9 or (cm and abs(x - n * 10) < 1e-6) for n in nums)
    return InputValue(value=x) if ok else None


def _inputs_text(e: Entry) -> str:
    lines = []
    for i in e.inputs:
        allowed = (" | ".join(i.options) if i.type == "enum" else "true | false" if i.type == "boolean"
                   else f"number in {i.unit or 'the unit dictated'}")
        states = f"; states allowed: {', '.join(i.states)}" if i.states else ""
        hint = f" (dictated as: {i.how_stated})" if i.how_stated else ""
        lines.append(f"- {i.id}: {i.label}{hint} [{allowed}{states}]")
    return "\n".join(lines)


async def _call(system: str, prompt: str) -> RawSettle:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawSettle, system_prompt=system, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def preview_pack(e: Entry, findings: str, history: str, answered: dict[str, str]) -> Preview:
    given: dict[str, InputValue] = {}
    for k, s in answered.items():
        i = e.input(k)
        v = _answer(e, i, s) if i is not None else None
        if v is not None:
            given[k] = v
    model: dict[str, tuple[InputValue, Settled]] = {}
    prompt = (f"SYSTEM: {e.display}\nINPUTS:\n{_inputs_text(e)}\n\nANSWERED BY THE RADIOLOGIST: "
              f"{', '.join(given) or 'none'}\n\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n{findings}")
    try:
        raw = await _call(SETTLE_SYS, prompt)
        for item in raw.settled:
            i = e.input(item.input)
            if i is None or i.id in given or not item.quote.strip():
                continue
            v = _value(i, item)
            if v is not None:
                model[i.id] = (v, Settled(input=i.id, value=_show(e, i, v), quote=item.quote.strip()))
    except Exception as ex:
        logger.warning("[library.preview] settle %s: %s", type(ex).__name__, str(ex)[:200])
    confirmed = await P.confirm_quotes({k: s for k, (_, s) in model.items()}, findings, history) if model else set()
    given.update({k: v for k, (v, _) in model.items() if k in confirmed})
    try:
        t = engine.evaluate(e, given)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.preview] %s cannot be evaluated: %s", e.key, ex)
        return Preview()
    order = [i.id for i in e.inputs]
    settled = [Settled(input=k, value=_show(e, e.input(k), given[k]),
                       quote=model[k][1].quote if k in model and k in confirmed else "")
               for k in order if k in given]
    possible = [engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)) for o in t.possible]
    proposal = None
    if t.outcome is not None:
        o = e.outcome(t.outcome)
        cls = engine.render(e, t, o.classification)
        proposal = Proposal(classification=f"{e.display} · {cls}", line=f"{e.display}: {cls}.",
                            recommendation=engine.render(e, t, o.recommendation))
    return Preview(settled=settled, missing=t.needed, proposal=proposal, possible=possible,
                   trace=t.model_dump(mode="json") if t.outcome is not None else None)


def as_entry(e: Entry, sources: list[dict]) -> CardEntry:
    """The pack in the card's existing Entry shape, so the open/preview response contract is unchanged."""
    primary = next((s for s in sources if s.get("role") == "primary"), {})
    return CardEntry(
        key=e.key, name=e.display, version=e.edition, status="verified",
        publication=Publication(title=primary.get("title", ""), body=e.issuer, year=e.edition),
        content=GuidelineContent(
            applies_to=", ".join(e.applies_to.finding_type), summary=" ".join(t.text for t in e.reference.summary),
            branches=[Branch(name=PACK_BRANCH, state="checked", inputs=[
                Input(id=i.id, question=i.label, options=display_options(e, i), settled_by=i.how_stated)
                for i in e.inputs])]),
        sources=[Source(url=s.get("url", ""), title=s.get("title", ""), tier=1) for s in sources
                 if s.get("role") in ("primary", "amendment")])
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_pack_preview.py tests/test_copilot_preview.py tests/test_copilot_types.py -q`
Expected: PASS (the existing preview tests still pass through the `_check` wrapper).

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/library/pack_preview.py \
  backend/src/rapid_reports_ai/hybrid_stack/copilot/preview.py backend/src/rapid_reports_ai/hybrid_stack/copilot/types.py \
  backend/tests/test_library_pack_preview.py
git commit -m "feat(library): pack preview, model settles inputs and the engine decides

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Wire packs into the matcher and the open/preview routes

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/matcher.py` (`_card`, `match` prompt)
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py` (`_check_card`, `/open`, `/preview`)
- Test: `backend/tests/test_copilot_matcher.py`, `backend/tests/test_copilot_routes.py` (append)

**Interfaces:**
- Consumes: `library.bundle.get()`, `Library.find`, `Library.lookup`, `Library.siblings`, `Library.sources`, `Library.known_text`; `pack_preview.preview_pack`, `as_entry`, `PACK_BRANCH`.
- Produces: a matched pack becomes `Card(key=<pack key>, branch="Pack", skeleton=["Pack"], known=True, status="verified", siblings=[...])`; `/open` and `/preview` on a pack key never fetch and return `branch="Pack"` with the engine preview.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_copilot_matcher.py`:

```python
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L


def _toy_lib(toy, *extra):
    entries = {f"{e['id']}@{e['version']}": {"entry": e, "sources": []} for e in (toy, *extra)}
    return L.Library({"version": "v1", "entries": entries})


async def test_a_library_pack_hit_becomes_a_pack_card(db_session, monkeypatch, toy):
    sib = {**toy, "id": "toy-other", "issuer": "OTHER", "display": "Other 2021", "aliases": ["other nodule"]}
    monkeypatch.setattr(L, "get", lambda: _toy_lib(toy, sib))

    async def call(prompt):
        assert "- toy-nodule@1.0: Toy 2020 [aliases: toy nodule | toy guideline]" in prompt
        return _raw(u1=[_sys("Toy Nodule", "2020")])
    monkeypatch.setattr(M, "_call", call)
    cards = await M.match(db_session, "CT chest", "", U[:1])
    assert [(c.key, c.branch, c.skeleton, c.status, c.known, c.siblings) for c in cards] == \
        [("toy-nodule@1.0", "Pack", ["Pack"], "verified", True, ["toy-other@1.0"])]
```

Append to `backend/tests/test_copilot_routes.py`:

```python
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP

TOY_SOURCES = [{"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY", "edition": "2020",
                "url": "https://example.org/toy"}]


@pytest.fixture
def toy_lib(monkeypatch, toy):
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def resolve(db, card):
        raise AssertionError("a pack is never fetched")

    async def call(system, prompt):
        return PP.RawSettle(settled=[PP.RawItem(input="kind", value="solid", quote="solid"),
                                     PP.RawItem(input="size", value=7, quote="7 mm")])
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(PP, "_call", call)
    return lib


PACK_CARD = {"key": "toy-nodule@1.0", "name": "Toy 2020", "version": "2020", "finding_id": "u1", "branch": "Pack"}


def test_open_a_library_pack(authed, toy_lib):
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "findings": "7 mm solid nodule.", "answered": {"risk": "high"}}).json()
    assert d["error"] is None and d["entry"]["key"] == "toy-nodule@1.0" and d["branch"] == "Pack"
    assert d["preview"]["proposal"]["recommendation"] == "CT at 6 months"
    assert d["entry"]["sources"][0]["url"] == "https://example.org/toy"


def test_preview_a_library_pack(authed, toy_lib):
    d = authed.post("/api/canvas/stack/guidelines/preview", json={
        "card": PACK_CARD, "findings": "7 mm solid nodule.", "answered": {}}).json()
    assert d["preview"]["missing"] == ["risk"] and len(d["preview"]["possible"]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_copilot_matcher.py tests/test_copilot_routes.py -q -k "library or pack"`
Expected: FAIL. The matcher returns a `toy-nodule@2020` new key, and `/open` returns 400 for the key mismatch.

- [ ] **Step 3: Wire the matcher**

In `matcher.py`, add the imports:

```python
from .library import bundle as L
from .library.pack_preview import PACK_BRANCH
```

In `_card`, after the `TNM` early return and before `row = await _resolve(...)`:

```python
    lib = L.get()
    pack = lib.find(s.name, s.version) or lib.find(s.name)
    if pack is not None and pack.tier == 1:
        return Card(key=pack.key, name=pack.display, version=pack.edition, finding_id=f.id, why=s.why,
                    branch=PACK_BRANCH, skeleton=[PACK_BRANCH], publication=Publication(body=pack.issuer, year=pack.edition),
                    known=True, status="verified", siblings=[x.key for x in lib.siblings(pack)])
```

In `match`, change the prompt call so the model sees the packs as known systems:

```python
            known = "\n".join(x for x in (rows.known_text(), L.get().known_text()) if x)
            raw = await _call(_prompt(scan_type, history, todo, known))
```

- [ ] **Step 4: Wire the routes**

In `routes.py`, add the imports:

```python
from .library import bundle as L
from .library.pack_preview import PACK_BRANCH, as_entry, preview_pack
```

At the top of `_check_card`, after the TNM line:

```python
    if L.get().lookup(card.key) is not None:
        return
```

Add the helpers after `_offline`:

```python
def _pack(key: str):
    """The library pack for a card key, as (pack, card-shaped entry), or None."""
    lib = L.get()
    e = lib.lookup(key)
    return (e, as_entry(e, lib.sources(e.key))) if e is not None and e.tier == 1 else None


async def _pack_result(pack, req: OpenRequest, t0: float) -> OpenResult:
    """Offline and engine-decided: never a fetch. Fail open, bounded, as _branch_and_preview."""
    e, view = pack
    try:
        prev = await asyncio.wait_for(preview_pack(e, req.findings[:6000], req.clinical_history[:2000], req.answered),
                                      PREVIEW_TIMEOUT_S)
    except Exception as ex:   # TimeoutError included
        logger.warning("[copilot.routes] pack preview %s: %s", type(ex).__name__, str(ex)[:200])
        prev = Preview()
    return OpenResult(entry=_public(view), preview=prev, branch=PACK_BRANCH, ms=_ms(t0))
```

In `copilot_open`, after `card = req.card.card()`:

```python
    pack = _pack(card.key)
    if pack is not None:
        return await _pack_result(pack, req, t0)
```

In `copilot_preview`, after `card = req.card.card()`, add the same three lines.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_copilot_*.py tests/test_library_*.py -q`
Expected: PASS, with no regressions in the existing copilot suites (the autouse fixture keeps their library empty).

- [ ] **Step 6: Run the wider suites the copilot touches**

Run: `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_hybrid_stack_*.py tests/test_copilot_*.py tests/test_library_*.py -q`
Expected: PASS. Report the count.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/copilot/matcher.py backend/src/rapid_reports_ai/hybrid_stack/copilot/routes.py \
  backend/tests/test_copilot_matcher.py backend/tests/test_copilot_routes.py
git commit -m "feat(copilot): packs reach cards through the matcher; open/preview use the engine

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Preview lab on the three packs

**Files:**
- Create: `backend/scripts/guidelines/preview_lab.py`
- Create: `backend/scripts/guidelines/preview_lab_cases.json`
- Create: `docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab.md` (results summary)

**Gate (spec §12.3):** zero wrong proposals; inputs settled and missing correctly; p95 latency under 2 s.

- [ ] **Step 1: Write the cases.** Create `preview_lab_cases.json` with 10 cases per pack (30 in total) in this shape:

```json
{"cases": [
  {"pack": "fleischner-pulmonary-nodule", "name": "cm measurement, smoker",
   "findings": "1.2 cm solid nodule in the left lower lobe.", "history": "Ex-smoker, 40 pack-years.",
   "expect_settled": {"nodule_type": "solid", "diameter_mm": "12 mm", "count": "single"},
   "expect_missing": [], "expect_outcome": "<outcome id from the pack>"}
]}
```

Each pack's 10 cases must include:
- a measurement in cm;
- a measurement exactly on an edge;
- a negated feature;
- a feature stated as not assessable (only where the pack allows it);
- an input left unstated, so it is expected in `expect_missing` and `expect_outcome` is `null`;
- a distractor finding in the same dictation that belongs to another lesion;
- clinical history settling an input (risk, family history);
- an abbreviation-heavy dictation;
- two cases a radiologist would plausibly dictate differently from the guideline's wording.

Write the dictation the way a UK radiologist would, in British English. Leave `expect_settled` out for inputs the case does not test.

- [ ] **Step 2: Write the lab script**

```python
"""Preview lab (library spec §12.3): each case through preview_pack live (Qwen + Jev), scored against its expected
settled inputs, missing inputs and outcome. At most 2 runs; output in the session scratchpad with the pid.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py <scratchpad-dir>"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, Library  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import preview_pack  # noqa: E402

CASES = Path(__file__).with_name("preview_lab_cases.json")


async def one(lib: Library, c: dict) -> dict:
    e = lib.lookup(c["pack"])
    t0 = time.perf_counter()
    p = await preview_pack(e, c["findings"], c.get("history", ""), {})
    ms = int((time.perf_counter() - t0) * 1000)
    settled = {s.input: s.value for s in p.settled}
    outcome = (p.trace or {}).get("outcome")
    wrong_settled = {k: (settled.get(k), v) for k, v in c.get("expect_settled", {}).items() if settled.get(k) != v}
    return {"name": c["name"], "pack": c["pack"], "ms": ms, "outcome": outcome, "expect_outcome": c["expect_outcome"],
            "wrong_proposal": outcome is not None and outcome != c["expect_outcome"],
            "outcome_ok": outcome == c["expect_outcome"], "missing": p.missing, "expect_missing": c["expect_missing"],
            "missing_ok": p.missing == c["expect_missing"], "wrong_settled": wrong_settled,
            "settled": [s.model_dump() for s in p.settled], "possible": p.possible}


async def main(out_dir: Path) -> int:
    lib = Library(json.loads(BUNDLE.read_text()))
    cases = json.loads(CASES.read_text())["cases"]
    rows = []
    for c in cases:                      # sequential: latency is part of the gate
        rows.append(await one(lib, c))
    out = out_dir / f"preview_lab_{os.getpid()}.json"
    out.write_text(json.dumps(rows, indent=1))
    ms = sorted(r["ms"] for r in rows)
    p95 = ms[min(len(ms) - 1, int(0.95 * len(ms)))]
    print(f"{len(rows)} cases -> {out}")
    print(f"wrong proposals: {sum(r['wrong_proposal'] for r in rows)}  outcome ok: {sum(r['outcome_ok'] for r in rows)}"
          f"  missing ok: {sum(r['missing_ok'] for r in rows)}  settled clean: {sum(not r['wrong_settled'] for r in rows)}")
    print(f"latency ms p50 {ms[len(ms) // 2]}  p95 {p95}")
    for r in rows:
        if r["wrong_proposal"] or not r["missing_ok"] or r["wrong_settled"]:
            print(f"- {r['pack']} / {r['name']}: outcome {r['outcome']} (want {r['expect_outcome']}), "
                  f"missing {r['missing']} (want {r['expect_missing']}), settled diffs {r['wrong_settled']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
```

- [ ] **Step 3: Run it once.** Use `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py <session scratchpad>`. Hand-read every failing row: is the case's expectation wrong, or is it the system? Fix wrong expectations in the cases file. For system errors, fix the cause (the prompt, a pack's `how_stated`, or the value guard) and write a unit test for each fix, then run once more. **Two runs at most.**
- [ ] **Step 4: Write `preview_lab.md`.** Record the counts, the p50 and p95, every failure with its cause and fix, and whether the gate passed. A wrong proposal in the final run means the gate fails: stop and report it to Hassan rather than tuning further.
- [ ] **Step 5: Commit**

```bash
git add backend/scripts/guidelines/preview_lab.py backend/scripts/guidelines/preview_lab_cases.json \
  docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab.md
git commit -m "lab(library): preview lab on Fleischner, Bosniak and BTS packs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Catalogue research (can start at any time, in parallel)

**Files:**
- Create: `docs/guidelines/catalogue.json`, `docs/guidelines/catalogue.md`
- Test: `backend/tests/test_library_catalogue.py`

- [ ] **Step 1: Write the shape test**

```python
import json
from pathlib import Path

CAT = Path(__file__).resolve().parents[2] / "docs" / "guidelines" / "catalogue.json"
FIELDS = {"id", "issuer", "system", "edition", "year", "url", "uk_body", "topic", "finding_types", "modalities",
          "tier_candidate", "licence_notes", "frequency", "frequency_basis"}


def test_catalogue_rows_have_every_field():
    rows = json.loads(CAT.read_text())["systems"]
    assert len(rows) >= 40
    for r in rows:
        assert set(r) == FIELDS, r.get("id")
        assert r["tier_candidate"] in (1, 2) and r["frequency"] in ("high", "medium", "low")
    assert len({r["id"] for r in rows}) == len(rows)
    uk = [r for r in rows if r["uk_body"]]
    assert uk and rows.index(uk[0]) == 0       # UK bodies listed first
```

- [ ] **Step 2: Run the research.** Invoke the `research` skill with this brief:

  > Build a catalogue of the radiology guidelines and classification systems a UK radiologist applies when reporting.
  > - **Order:** UK bodies first (RCR, BTS, NICE, BSGAR, BSTI, BSUR, BSNR, UKHSA/NHS screening programmes, British Society of Skeletal Radiologists), then international systems used in UK practice (Fleischner, ACR \*-RADS, ESUR, ESGAR, ESR, ESSR, WHO).
  > - **Fields per system:** issuer, system name, current edition and year, a primary-source URL, and the topic. Also record:
  >   - finding types and modalities;
  >   - whether it is executable decision logic (`tier_candidate` 1) or reference material (2);
  >   - licence notes: open access or not, and any stated reuse terms;
  >   - an estimated clinical frequency (high, medium or low), with the basis for the estimate (an incidence paper or a survey; cite it).
  > - **Sources:** primary sources only for editions and URLs.

  Write `docs/guidelines/catalogue.json` (`{"systems": [...]}` with exactly the test's fields) and `catalogue.md`, a readable table with the method and the sources.
- [ ] **Step 3: Run the test.** `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_catalogue.py -q`. Expected: PASS.
- [ ] **Step 4: Commit**

```bash
git add docs/guidelines backend/tests/test_library_catalogue.py
git commit -m "docs(library): UK-first catalogue of guideline and classification systems

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Coverage lab on prod dictations

**Files:**
- Create: `backend/scripts/guidelines/coverage_lab.py`
- Test: `backend/tests/test_library_coverage_lab.py`
- Create: `docs/guidelines/coverage-lab-2026-10.md` (results; no raw prod text)

**Gates (spec §12.2):**
- N entries cover about 90% of correctly named systems.
- Negative controls yield no card that could be Applied.

- [ ] **Step 1: Write the failing test for the extraction**

```python
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "coverage_lab", Path(__file__).resolve().parents[1] / "scripts" / "guidelines" / "coverage_lab.py")
CL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CL)


def test_abnormal_units_become_findings_with_frontend_ids():
    units = [{"id": 0, "text": "Clinical history.", "heading": True, "abnormal": True},
             {"id": 1, "text": "8 mm nodule.", "abnormal": True},
             {"id": 2, "text": "Normal liver.", "abnormal": False},
             {"id": 3, "text": "Kidneys: a 2 cm cyst; normal spleen.", "abnormal": True,
              "parts": [{"text": "a 2 cm cyst", "group": "kidneys", "abnormal": True},
                        {"text": "normal spleen", "group": "spleen", "abnormal": False}]}]
    assert CL.findings(units) == [{"id": "u1", "text": "8 mm nodule."}, {"id": "u3.0", "text": "a 2 cm cyst"}]


def test_metabase_rows_become_cases():
    body = {"data": {"cols": [{"name": "id"}, {"name": "scan_type"}, {"name": "units"}],
                     "rows": [["a", "CT chest", '[{"id": 1, "text": "8 mm nodule.", "abnormal": true}]'],
                              ["b", "CT head", "[]"]]}}
    assert CL.cases_from_metabase(body) == [
        {"id": "a", "scan_type": "CT chest", "clinical_history": "", "findings": [{"id": "u1", "text": "8 mm nodule."}]}]
```

- [ ] **Step 2: Write the script**

```python
"""Coverage lab (library spec §12.2): which systems the unchanged matcher names on real prod stack dictations.
1. export: run the SQL below through Metabase /api/dataset in the Chrome session (Cloudflare blocks scripts) and save
   the JSON response in the session scratchpad. Raw prod text never leaves the scratchpad.
2. run:  coverage_lab.py run <metabase.json> <scratchpad>   -> matches_<pid>.json + handread_<pid>.csv
3. hand read: fill handread_<pid>.csv columns correct (y/n) and expected_none (y if no system should apply).
4. summarise: coverage_lab.py summarise <handread.csv>      -> the coverage curve and the negative-control count.
SQL: select id, scan_type, units::text as units from dictation_stack_logs
     where units is not null and created_at > now() - interval '90 days' order by created_at desc limit 400"""
import asyncio
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot import matcher as M  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot import registry as R  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot import tnm  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, Library  # noqa: E402


def findings(units: list[dict]) -> list[dict]:
    """The abnormal units as the frontend sends them to /match: u<id>, or u<id>.<part> for an abnormal part."""
    out = []
    for u in units:
        if u.get("heading"):
            continue
        if u.get("parts"):
            out += [{"id": f"u{u['id']}.{n}", "text": p["text"]} for n, p in enumerate(u["parts"]) if p.get("abnormal")]
        elif u.get("abnormal"):
            out.append({"id": f"u{u['id']}", "text": u["text"]})
    return out


def cases_from_metabase(body: dict) -> list[dict]:
    cols = [c["name"] for c in body["data"]["cols"]]
    out = []
    for row in body["data"]["rows"]:
        r = dict(zip(cols, row))
        fs = findings(json.loads(r["units"] or "[]"))
        if fs:
            out.append({"id": r["id"], "scan_type": r.get("scan_type") or "", "clinical_history": "", "findings": fs})
    return out


async def _match(case: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        fs = [M.Finding(**f) for f in case["findings"]]
        try:
            raw = await M._call(M._prompt(case["scan_type"], case["clinical_history"], fs, ""))
            got = {M._rid(rf.id): [s.model_dump() for s in rf.systems] for rf in raw.findings}
        except Exception as ex:
            got = {"error": str(ex)[:200]}
        return {**case, "systems": got}


async def run(src: Path, out_dir: Path) -> None:
    cases = cases_from_metabase(json.loads(src.read_text()))
    sem = asyncio.Semaphore(4)
    done = await asyncio.gather(*(_match(c, sem) for c in cases))
    pid = os.getpid()
    (out_dir / f"matches_{pid}.json").write_text(json.dumps(done, indent=1))
    with open(out_dir / f"handread_{pid}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "finding", "text", "system", "version", "site", "correct", "expected_none"])
        for c in done:
            for f in c["findings"]:
                systems = c["systems"].get(f["id"], []) if isinstance(c["systems"], dict) else []
                for s in systems or [{"name": "", "version": "", "site": ""}]:
                    w.writerow([c["id"], f["id"], f["text"], s["name"], s.get("version", ""), s.get("site", ""), "", ""])
    print(f"{len(done)} cases -> {out_dir}/matches_{pid}.json, handread_{pid}.csv")


def summarise(path: Path) -> None:
    rows = list(csv.DictReader(open(path)))
    lib = Library(json.loads(BUNDLE.read_text()))
    named = [r for r in rows if r["system"] and r["correct"] == "y"]
    counts = Counter("TNM" if r["system"].strip().upper() == "TNM" else R.norm(r["system"]) for r in named)
    total, run_sum = sum(counts.values()), 0
    print(f"{total} correctly named mentions across {len(counts)} systems")
    for n, (name, k) in enumerate(counts.most_common(), 1):
        run_sum += k
        print(f"{n:>3}. {name:<40} {k:>4}  cumulative {run_sum / total:.0%}")
    applicable = [r for r in rows if r["expected_none"] == "y" and r["system"]
                  and (r["system"].strip().upper() == "TNM" or lib.find(r["system"], r["version"]) or lib.find(r["system"]))]
    print(f"negative controls with a card that could be Applied: {len(applicable)} (gate: 0)")
    for r in applicable:
        print(f"- {r['case']} {r['finding']}: {r['system']}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        asyncio.run(run(Path(sys.argv[2]), Path(sys.argv[3])))
    else:
        summarise(Path(sys.argv[2]))
```

`tnm` is imported for reference in the hand read (`tnm.sites()` is the closed list); keep or drop it to suit the linter.

- [ ] **Step 3: Run the extraction test.** `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_library_coverage_lab.py -q`. Expected: PASS.
- [ ] **Step 4: Export and run.**
  1. Run the SQL through Metabase in the Chrome session (memory `reference_prod_smoke_testing`: Metabase `/api/dataset`). Save the response to the scratchpad.
  2. Run `coverage_lab.py run <file> <scratchpad>` once.
  3. Hand-read the CSV, marking `correct` and `expected_none` on every row.
  4. Run `summarise`.
- [ ] **Step 5: Write `docs/guidelines/coverage-lab-2026-10.md`.** It holds only counts and system names, never dictation text:
  - the ranked list, with cumulative coverage;
  - N at 90%;
  - the negative-control result;
  - the merge with `catalogue.json`: the authoring order, with our usage first and the literature estimate second;
  - any systems the matcher named that are missing from the catalogue.
- [ ] **Step 6: Commit**

```bash
git add backend/scripts/guidelines/coverage_lab.py backend/tests/test_library_coverage_lab.py docs/guidelines/coverage-lab-2026-10.md
git commit -m "lab(library): coverage lab on prod stack dictations sets the authoring order

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Close the slice

**Files:**
- Modify: `docs/superpowers/specs/2026-10-12-guideline-library-design.md` (record what the slice learned)
- Modify: `docs/superpowers/handover/2026-10-12-scratchpad-copilot-handover.md` (next steps)

- [ ] **Step 1: Update the spec.** In §12, mark items 1–3 done, linking `schema_proof.md`, `preview_lab.md` and `coverage-lab-2026-10.md`. Correct any part of §3 or §4 that the build changed.
- [ ] **Step 2: Update the handover's top note.** The next work is frontend Tasks 14–19 from `docs/superpowers/plans/2026-10-12-scratchpad-copilot.md`, with Apply only on pack and TNM cards. Task 14 (the mock-up) still needs Hassan's approval. After that come the next packs in coverage-lab order.
- [ ] **Step 3: Run the full suites once.** `cd backend && PYTHONPATH=src .venv/bin/pytest tests/test_hybrid_stack_*.py tests/test_copilot_*.py tests/test_library_*.py tests/test_quick_report*.py tests/test_report_review*.py -q`. Report the counts. A failure blocks the commit.
- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-12-guideline-library-design.md docs/superpowers/handover/2026-10-12-scratchpad-copilot-handover.md
git commit -m "docs(library): first slice closed, results and next steps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Frontend Tasks 14–19 are deliberately not in this plan: they already exist in the copilot plan, and Task 14 is gated on Hassan's mock-up approval.
