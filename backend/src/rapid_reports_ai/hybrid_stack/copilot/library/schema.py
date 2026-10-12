"""The guideline library's entry model (library spec §3). An entry is data only: typed inputs, a pipeline of
data-only logic steps, outcomes and reference fields, every fact carrying a locator into its manifest's sources.
Numbers are never compared in a rule: a band step turns them into band ids first, so every entry is enumerable."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

State = Literal["present", "absent", "unknown", "not_assessable", "not_applicable"]
OptState = Literal["absent", "not_assessable"]      # states an input may allow besides present and unknown
Role = Literal["primary", "amendment", "explanatory"]
Scope = Literal["lesion", "patient"]                # lesion: the card's own finding; patient: history + dictation
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
    min_value: float | None = None                         # a number's valid range; a value outside it is refused
    min_inclusive: bool = True
    max_value: float | None = None
    max_inclusive: bool = True
    locator: Locator | None = None
    scope: Scope = "lesion"                                # where a value may be quoted from (spec §3.6)
    dims: Literal["mean", "max"] | None = None             # a number dictated "A x B": its mean or its max

    @model_validator(mode="after")
    def _options(self):
        if (self.type == "enum") != bool(self.options):
            raise ValueError(f"input {self.id!r}: options are given exactly when the type is enum")
        if self.type != "number" and self.ranged:
            raise ValueError(f"input {self.id!r}: only a number has a range")
        if self.min_value is not None and self.max_value is not None and not (
                self.min_value < self.max_value
                or (self.min_value == self.max_value and self.min_inclusive and self.max_inclusive)):
            raise ValueError(f"input {self.id!r}: empty range")
        if self.dims is not None and self.type != "number":
            raise ValueError(f"input {self.id!r}: only a number has dims")
        return self

    @property
    def ranged(self) -> bool:
        return self.min_value is not None or self.max_value is not None

    def in_range(self, x: float) -> bool:
        if x != x:                                         # NaN is never valid
            return False
        lo = self.min_value is None or (x >= self.min_value if self.min_inclusive else x > self.min_value)
        hi = self.max_value is None or (x <= self.max_value if self.max_inclusive else x < self.max_value)
        return lo and hi

    def representatives(self, cuts: list[float]) -> list[float]:
        """Values inside the range: every cut and inclusive bound inside it, and one value in each region that the
        cuts and the range bounds divide it into."""
        pts = sorted(set(cuts) | {b for b in (self.min_value, self.max_value) if b is not None})
        if not pts:
            return [0.0]
        reps = {pts[0] - 1, pts[-1] + 1, *pts, *((a + b) / 2 for a, b in zip(pts, pts[1:]))}
        return sorted(x for x in reps if self.in_range(x))


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
