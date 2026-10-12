"""Evaluates one tier 1 library entry for one lesion (library spec §4). Code only: the model settles inputs; this
computes the outcome and a trace of what fired, with the locators behind it. Three-valued: an input not yet known
makes whatever depends on it unknown. When the outcome is unknown, partial evaluation (Task 3) enumerates the unknown
inputs to say which of them could still change it and which outcomes remain possible."""
from __future__ import annotations

import math
import re
from itertools import product
from typing import Any

from pydantic import BaseModel, Field

from .schema import (AdjustStep, All, AnyOf, BandStep, Cond, DeriveStep, Entry, Expr, InputDef, InputValue, Locator,
                     NoneOf, Num, RulesStep, ScoreStep, TableStep, as_value)

PH = re.compile(r"\{([A-Za-z0-9_]+)\}")
MAX_COMBOS = 50_000
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
