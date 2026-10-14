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
                     NoneOf, Num, RulesStep, ScoreStep, TableStep, as_value, conds)
from .schema import DOES_NOT_APPLY

PH = re.compile(r"\{([A-Za-z0-9_]+)\}")
MAX_COMBOS = 10_000      # partial evaluation (≈0.75 s at the cap); beyond it every reaching unknown is asked
OVER_MAX = 4_000          # unbounded over-approximation: beyond this many combinations, every outcome (≈0.2 s)
_ORDER = ("not_applicable", "unknown", "not_assessable", "absent")   # the state a blocked step takes, first wins:
# not_applicable is final (no later answer undoes a false prerequisite), so it beats unknown; the other states wait for
# the unknowns, which keeps the result monotone as answers arrive


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
    decides: dict[str, list[str]] = Field(default_factory=dict)   # needed input -> the outcomes its value decides between
    waiting: list[str] = Field(default_factory=list)   # unanswered inputs behind a prerequisite still unknown: not
                                                       # asked yet (§7.4); an input with a value is never listed
    assumed: dict[str, InputValue] = Field(default_factory=dict)   # assume_eligible: each unknown eligibility input
    # evaluated at its in-scope value (a number through its band: InputValue(band=...)), never a stated value
    inputs: dict[str, InputValue] = Field(default_factory=dict)
    steps: list[StepTrace] = Field(default_factory=list)


def _coerce(i: InputDef, g: InputValue) -> V:
    if g.state != "present":
        if g.state not in i.states:
            raise ValueError(f"input {i.id}: state {g.state} is not allowed")
        return V(state=g.state)
    if i.type == "number":
        if g.band is not None:
            return V(band=g.band)
        x = float(g.value)
        if not i.in_range(x):
            raise ValueError(f"input {i.id}: {x:g} is outside its valid range")
        return V(value=x)
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
        try:
            return math.exp(a[0])
        except OverflowError as ex:
            raise EvaluationError(f"exp({a[0]}) overflows") from ex
    if n.op == "pow":
        try:
            r = a[0] ** a[1]
        except (ZeroDivisionError, OverflowError) as ex:
            raise EvaluationError(f"pow({a[0]}, {a[1]}): {ex}") from ex
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
    if s.kind == "linear":
        return V(value=z), ""
    p = 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))   # never overflows
    return V(value=p), ""


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


def _once(entry: Entry, given: dict[str, InputValue],
          over: dict[str, V] | None = None) -> tuple[dict[str, V], list[StepTrace]]:
    env = _inputs(entry, given)
    return env, run(entry, env, over)


def _edges(entry: Entry, input_id: str) -> list[float] | None:
    """One number per region the band edges cut the line into, edges included; None when the number also feeds a
    formula (its effect cannot be enumerated)."""
    users = [s for s in entry.logic if input_id in s.refs()]
    if any(not isinstance(s, BandStep) for s in users):
        return None
    pts = sorted({x for s in users for b in s.bands for x in (b.min, b.max) if x is not None})
    i = entry.input(input_id)
    if i is not None and i.ranged:                    # never sample outside the input's valid range
        return i.representatives(pts)
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


def reaching(entry: Entry) -> set[str]:
    """Every input id the result step depends on, through any chain of steps (and input prerequisites)."""
    deps = {s.id: set(s.refs()) for s in entry.logic}
    deps.update({i.id: {c.ref for p in i.prerequisites for c in conds(p)} for i in entry.inputs})
    seen, todo = set(), [entry.result]
    while todo:
        k = todo.pop()
        if k in seen:
            continue
        seen.add(k)
        todo += deps.get(k, set())
    return {i.id for i in entry.inputs} & seen


def parents(entry: Entry) -> set[str]:
    """The inputs some other input's prerequisite tests (spec §7.4)."""
    return {c.ref for i in entry.inputs for p in i.prerequisites for c in conds(p) if entry.input(c.ref) is not None}


def gates(entry: Entry) -> set[str]:
    """The inputs one answer to which can settle the outcome on its own: a result rules case (not does_not_apply)
    that tests only that input and eligibility inputs, e.g. PI-RADS finding_above_1 = no settles the exam at PI-RADS 1.
    Asked straight after eligibility, since that one answer may close the card."""
    s = entry.step(entry.result)
    if not isinstance(s, RulesStep):
        return set()
    out: set[str] = set()
    for case in s.cases:
        refs = {c.ref for c in conds(case.when)}
        if case.result == DOES_NOT_APPLY or any(entry.input(r) is None for r in refs):
            continue
        rest = {r for r in refs if entry.input(r).role != "eligibility"}
        if len(rest) == 1:
            out |= rest
    return out


def parents_first(entry: Entry, needed: list[str], env: dict[str, V],
                  held: frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """(needed, waiting), spec §7.4. An input behind a prerequisite that is still unknown is not asked yet: it waits,
    and its unknown parents are asked in its place, transitively. The walk goes through a parent that has a value
    (`held`: its own unknown prerequisite must still be asked), but an input with a value is never returned as waiting.
    Order: eligibility inputs, then gates, then parents, then the rest, each in the pack's input order."""
    order = [i.id for i in entry.inputs]
    par, gate = parents(entry), gates(entry)
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
    rank = {k: (entry.input(k).role != "eligibility", k not in gate, k not in par, order.index(k)) for k in ask}
    return sorted(ask, key=rank.get), sorted((w for w in waiting if w not in ask and w not in held), key=order.index)


def reach_states(e: Entry, ref: str) -> set[str]:
    """The non-present states a value can take: an input's allowed states (plus not_applicable behind a
    prerequisite), or the union over a step's inputs."""
    i = e.input(ref)
    if i is not None:
        return set(i.states) | ({"not_applicable"} if i.prerequisites else set())
    s = e.step(ref)
    return set().union(*(reach_states(e, r) for r in s.refs())) if s is not None else set()


def _over(entry: Entry, given: dict[str, InputValue], env: dict[str, V], names: list[str],
          doms: dict[str, list[InputValue] | None], possible: list[str],
          fixed: dict[str, V] | None = None) -> list[str]:
    """Unbounded: the outcomes still possible, over-approximated. Every band step left unknown (it reads a formula or a
    number that feeds one) is enumerated over its own band ids, with the enumerable unknown inputs; more than
    OVER_MAX combinations gives every outcome. Safe: it may list an outcome no real value reaches, never miss one."""
    bands = [s for s in entry.logic if isinstance(s, BandStep) and env.get(s.id, UNKNOWN).state == "unknown"]
    bdoms = [[V(value=b.id) for b in s.bands] + [V(state=x) for x in sorted(reach_states(entry, s.ref))]
             for s in bands]           # band ids and the states the band can take, as gate 2 enumerates them
    if math.prod(len(doms[n]) for n in names) * math.prod(len(d) for d in bdoms) > OVER_MAX:
        return _all_results(entry)
    out = set(possible)
    for combo in product(*(doms[n] for n in names)):
        for bc in product(*bdoms):
            e2 = _inputs(entry, {**given, **dict(zip(names, combo))})
            try:
                run(entry, e2, {**(fixed or {}), **{s.id: v for s, v in zip(bands, bc)}})
            except EvaluationError:    # an override no real value produces; gate 2 owns the entry's correctness
                continue
            r = e2[entry.result]
            if r.state == "present":
                out.add(r.value)
    return sorted(out)


def _all_results(entry: Entry) -> list[str]:
    """Every outcome the rules can reach: an outcome named by an input's exclusion_outcome is wording for
    does_not_apply (spec §7.12 item 1), never a result."""
    wording = {i.exclusion_outcome for i in entry.inputs if i.exclusion_outcome is not None}
    return sorted(o.id for o in entry.outcomes if o.id not in wording)


def _deps(entry: Entry) -> dict[str, set[str]]:
    d = {s.id: set(s.refs()) for s in entry.logic}
    d.update({i.id: {c.ref for p in i.prerequisites for c in conds(p)} for i in entry.inputs})
    return d


def _reach_from(deps: dict[str, set[str]], start: list[str], stop: set[str]) -> set[str]:
    seen, todo = set(), list(start)
    while todo:
        k = todo.pop()
        if k in seen or k in stop:
            continue
        seen.add(k)
        todo += deps.get(k, set())
    return seen


def _unbounded(entry: Entry, given: dict[str, InputValue], env: dict[str, V], names: list[str],
               doms: dict[str, list[InputValue] | None], fixed: dict[str, V] | None) -> tuple[list[str], list[str]] | None:
    """(needed, possible) when an unknown number feeds a formula, instead of asking every reaching input. Each band
    step left unknown is a free variable over its own band ids (as _over); an input that reaches the result only
    through such bands is not enumerated, since the band stands for it. An enumerated input is needed when changing it
    alone can change the outcome; a free band that can is needed through every unknown input that feeds it. BTS: a
    6 mm solid nodule never asks the Brock inputs, which reach the result only through brock_band, which no 6 mm
    pathway reads. None over OVER_MAX combinations: the caller asks every reaching input (safe over-asking)."""
    bands = [s for s in entry.logic if isinstance(s, BandStep) and env.get(s.id, UNKNOWN).state == "unknown"]
    deps, free = _deps(entry), {s.id for s in bands}
    direct = _reach_from(deps, [entry.result], free)
    enum = [n for n in names if n in direct]
    bdoms = [[V(value=b.id) for b in s.bands] + [V(state=x) for x in sorted(reach_states(entry, s.ref))]
             for s in bands]
    if math.prod(len(doms[n]) for n in enum) * math.prod(len(d) for d in bdoms) > OVER_MAX:
        return None
    # lazily: each combination runs with the free bands unknown first; only one whose result is still unknown is run
    # again over the band values (most combinations never read a free band, so this stays far under OVER_MAX runs)
    table: dict[tuple, Any] = {}          # enumerated values -> outcome (bands not read) or {band values -> outcome}
    for combo in product(*(doms[n] for n in enum)):
        key = tuple((v.state, v.value, v.band) for v in combo)
        e2, _ = _once(entry, {**given, **dict(zip(enum, combo))}, fixed)
        r = e2[entry.result]
        if r.state == "present" or not bands:
            table[key] = r.value if r.state == "present" else None
            continue
        sub = {}
        for bc in product(*bdoms):
            e3 = _inputs(entry, {**given, **dict(zip(enum, combo))})
            try:
                run(entry, e3, {**(fixed or {}), **{s.id: v for s, v in zip(bands, bc)}})
            except EvaluationError:    # an override no real value produces; gate 2 owns the entry's correctness
                continue
            x = e3[entry.result]
            sub[tuple((v.state, v.value) for v in bc)] = x.value if x.state == "present" else None
        table[key] = sub

    def at(key: tuple, bkey: tuple):
        t = table.get(key)
        return t.get(bkey, ...) if isinstance(t, dict) else t

    bkeys = sorted({bk for t in table.values() if isinstance(t, dict) for bk in t}, key=str) or [()]
    decisive = set()
    for k, n in enumerate(enum):
        groups: dict[tuple, dict] = {}
        for key in table:
            groups.setdefault(key[:k] + key[k + 1:], {})[key[k]] = key
        for members in groups.values():
            if len(members) > 1 and any(len({at(m, bk) for m in members.values()} - {...}) > 1 for bk in bkeys):
                decisive.add(n)
                break
    for j, s in enumerate(bands):
        for t in table.values():
            if not isinstance(t, dict):
                continue
            groups = {}
            for bk, r in t.items():
                groups.setdefault(bk[:j] + bk[j + 1:], set()).add(r)
            if any(len(g) > 1 for g in groups.values()):
                decisive.add(s.id)
                break
    outs = {r for t in table.values() for r in (t.values() if isinstance(t, dict) else [t]) if r is not None}
    unknown = {i.id for i in entry.inputs if env[i.id].state == "unknown" and i.id not in given}
    needed = [n for n in enum if n in decisive]
    for s in bands:
        if s.id in decisive:
            needed += [k for k in _reach_from(deps, [s.id], set()) if k in unknown and entry.input(k) is not None]
    return needed, sorted(outs)


def _excluded_whatever(entry: Entry, given: dict[str, InputValue], elig: list[InputDef]) -> bool:
    """Every value of the unknown eligibility inputs leads to a does_not_apply case that holds, so the card is excluded
    whatever they are (BTS: a 38 mm opacity is outside the nodule definition at any age). Nothing need be asked."""
    return _non_excluding(entry, given, elig, excluded=True)


def _non_excluding(entry: Entry, given: dict[str, InputValue],
                   elig: list[InputDef], excluded: bool = False):
    """For each unknown eligibility input, its one value that cannot lead to does_not_apply, worked out from the entry:
    the candidate values (a choice or yes/no, or a number's band ids on the band steps that read it) for which every
    rules case reaching does_not_apply is false. An input with no such single value stays unknown. Returns (input
    values, band-step overrides): a number is held out through its band, never given a made-up value, so a formula it
    also feeds stays unknown. With `excluded`, returns instead whether every candidate value excludes
    (_excluded_whatever)."""
    dna = [c.when for s in entry.logic if isinstance(s, RulesStep) for c in s.cases if c.result == DOES_NOT_APPLY]
    if not dna:
        return False if excluded else ({}, {})
    slots: list[tuple[str, str, list]] = []          # (kind, id, candidates)
    for i in elig:
        if i.type in ("enum", "boolean"):
            slots.append(("in", i.id, [v for v in domain(entry, i) if v.state == "present"]))
        else:
            for b in (s for s in entry.logic if isinstance(s, BandStep) and s.ref == i.id):
                slots.append(("step", b.id, [V(value=x.id) for x in b.bands]))
    if not slots or math.prod(len(c) for _, _, c in slots) > MAX_COMBOS:
        return False if excluded else ({}, {})
    ok: list[tuple] = []
    every_excluded = True
    for combo in product(*(c for _, _, c in slots)):
        g = {**given, **{n: v for (k, n, _), v in zip(slots, combo) if k == "in"}}
        o = {n: v for (k, n, _), v in zip(slots, combo) if k == "step"}
        env = _inputs(entry, g)
        try:
            run(entry, env, o)
        except EvaluationError:
            every_excluded = False
            continue
        out = env[entry.result]               # the entry's own result, so rule order and intermediate steps count
        every_excluded = every_excluded and out.state == "present" and out.value == DOES_NOT_APPLY
        # a does_not_apply case that also reads a clinical input still unknown (BTS: an opacity over 3 cm is a mass)
        # cannot be ruled out here: the eligibility value is in scope when no exclusion holds for it
        if all(truth(w, env) is not True for w in dna):
            ok.append(combo)
    if excluded:
        return every_excluded
    fill, over = {}, {}
    for n, (k, name, _) in enumerate(slots):
        vals = {(v.state, v.value, getattr(v, "band", None)) for v in (c[n] for c in ok)}
        if len(vals) == 1:
            (fill if k == "in" else over)[name] = ok[0][n]
    return fill, over


def _pinned(entry: Entry, input_id: str, fixed: dict[str, V] | None) -> bool:
    """Every step that reads the input is a band step overridden in `fixed`, and no prerequisite tests it: its value
    cannot move anything, so it is not enumerated (the held-out eligibility number in the clinical pass)."""
    users = [s for s in entry.logic if input_id in s.refs()]
    return (bool(fixed) and bool(users) and all(isinstance(s, BandStep) and s.id in fixed for s in users)
            and not any(c.ref == input_id for i in entry.inputs for p in i.prerequisites for c in conds(p)))


def _partial(entry: Entry, given: dict[str, InputValue], env: dict[str, V], fixed: dict[str, V] | None = None,
             hold_out: bool = True) -> tuple[list[str], bool, list[str], dict[str, list[str]]]:
    """(possible outcomes, bounded, needed inputs). An unknown input is needed when changing it alone can change the
    outcome for some value of the other unknown inputs. Unbounded (an unknown number feeds a formula): enumeration
    cannot tell, so every unknown applicable input that reaches the result is needed (safe over-asking). `decides`:
    for each needed input, the outcomes that changing it alone moves between (all still possible when unknown)."""
    # a given value behind a still-unknown prerequisite is not enumerated: each combination re-applies it once the
    # enumerated prerequisite allows it, so only the prerequisite is asked
    held = {k for k, v in given.items() if v.state != "unknown"}
    unknown = [i for i in entry.inputs if env[i.id].state == "unknown" and i.id not in held]
    # an eligibility number assumed through its band (pinned in `fixed`) is not held out again: it is assumed
    elig = [i for i in unknown if i.role == "eligibility" and not _pinned(entry, i.id, fixed)]
    if hold_out and elig and _excluded_whatever(entry, given, elig):
        return [DOES_NOT_APPLY], True, [], {}
    if hold_out and elig:
        # the clinical asks are worked out as for an eligible patient; the unknown eligibility inputs are asked first,
        # and does_not_apply stays possible (no outcome, so no proposal) until each is settled
        fill, fix = _non_excluding(entry, given, elig)
        if fill or fix:
            g2, f2 = {**given, **fill}, {**(fixed or {}), **fix}
            env2, _ = _once(entry, g2, f2)
            r = env2[entry.result]
            possible, bounded, needed, decides = (([r.value], True, [], {}) if r.state == "present"
                                                  else _partial(entry, g2, env2, f2, hold_out=False))
            first = [i.id for i in elig]
            possible = sorted(set(possible) | ({DOES_NOT_APPLY} if entry.outcome(DOES_NOT_APPLY) else set()))
            needed = first + [n for n in needed if n not in first]
            if not bounded:    # as below: enumeration cannot tell what one input moves
                return possible, bounded, needed, {n: possible for n in needed}
            return possible, bounded, needed, {n: possible if n in first else decides.get(n) or possible
                                               for n in needed}
    doms = {i.id: domain(entry, i) for i in unknown}
    names = [k for k, d in doms.items() if d is not None and not _pinned(entry, k, fixed)]
    order = [i.id for i in entry.inputs]
    reach = reaching(entry)
    every = [i.id for i in unknown if i.id in reach]
    if math.prod(len(doms[n]) for n in names) > MAX_COMBOS:
        allo = _all_results(entry)
        return allo, False, every, {k: allo for k in every}
    results = []
    for combo in product(*(doms[n] for n in names)):
        e2, _ = _once(entry, {**given, **dict(zip(names, combo))}, fixed)
        v = e2[entry.result]
        results.append((combo, v.value if v.state == "present" else None))
    possible = sorted({r for _, r in results if r is not None})
    bounded = all(r is not None for _, r in results)
    needed, decides = [], {}
    for k, n in enumerate(names):
        groups: dict[tuple, set] = {}
        for combo, r in results:
            rest = tuple((v.state, v.value, v.band) for v in combo[:k] + combo[k + 1:])   # InputValue is unhashable
            groups.setdefault(rest, set()).add(r)
        moved = {r for g in groups.values() if len(g) > 1 for r in g if r is not None}
        if any(len(g) > 1 for g in groups.values()):
            needed.append(n)
            decides[n] = sorted(moved)
    if not bounded:
        got = _unbounded(entry, given, env, names, doms, fixed)
        if got is None:
            needed = every
            possible = _over(entry, given, env, names, doms, possible, fixed)
        else:
            needed, over_possible = got
            possible = sorted(set(possible) | set(over_possible))
    needed = sorted(set(needed), key=order.index)
    if not bounded:            # enumeration cannot tell what one input moves: each decides between all still possible
        return possible, bounded, needed, {n: possible for n in needed}
    return possible, bounded, needed, {n: decides.get(n) or possible for n in needed}


def _assume(entry: Entry, given: dict[str, InputValue]) -> tuple[dict[str, InputValue], dict[str, V],
                                                                  dict[str, InputValue]]:
    """(input values, band-step overrides, input -> the value assumed) for every unknown eligibility input that has
    one in-scope value (_non_excluding) the radiologist could answer back: a choice, yes/no, or a number's band when
    band steps alone read it. A number that also feeds a formula (BTS age, in Brock) has no answerable band, so it is
    never assumed: it stays unknown and is asked like any other input (review I1)."""
    elig = [i for i in entry.inputs if i.role == "eligibility" and i.id not in given]
    if not elig:
        return {}, {}, {}
    fill, over = _non_excluding(entry, given, elig)

    def answerable(input_id: str) -> bool:
        return all(isinstance(s, BandStep) for s in entry.logic if input_id in s.refs())
    over = {k: v for k, v in over.items() if answerable(entry.step(k).ref)}
    assumed = dict(fill)
    for s in entry.logic:
        if isinstance(s, BandStep) and s.id in over:
            assumed[s.ref] = InputValue(band=over[s.id].value)
    return fill, over, assumed


def assumptions(entry: Entry, given: dict[str, Any]) -> dict[str, InputValue]:
    """input -> the in-scope value evaluate(assume_eligible=True) would assume for it, over these given values."""
    g = {k: as_value(v) for k, v in given.items() if entry.input(k) is not None}
    return _assume(entry, {k: v for k, v in g.items() if v.state != "unknown"})[2]


def evaluate(entry: Entry, given: dict[str, Any], assume_eligible: bool = False) -> Trace:
    """The outcome for these inputs (unknown inputs simply left out), with a trace. Raises ValueError for an input
    value the entry does not allow, EvaluationError for a defect in the entry. `assume_eligible` (the draft card,
    Hassan 2026-10-13): each unknown eligibility input is evaluated at its in-scope value (`Trace.assumed`), so the
    card can draft the outcome for an eligible patient; a stated value always wins, and one that excludes still gives
    does_not_apply."""
    given = {k: as_value(v) for k, v in given.items() if entry.input(k) is not None}
    fixed, assumed = None, {}
    if assume_eligible:
        fill, over, assumed = _assume(entry, {k: v for k, v in given.items() if v.state != "unknown"})
        given, fixed = {**given, **fill}, (over or None)
    env, steps = _once(entry, given, fixed)
    out = env[entry.result]
    inputs = {i.id: _iv(env[i.id]) for i in entry.inputs}
    if out.state == "present":
        return Trace(outcome=out.value, possible=[out.value], inputs=inputs, steps=steps, assumed=assumed)
    if out.state != "unknown":
        raise EvaluationError(f"result step {entry.result} ended {out.state}")
    # an eligibility input left unassumed (no answerable in-scope value) is held out as without assume_eligible: asked
    # first, the clinical asks worked out for an eligible patient
    possible, bounded, needed, decides = _partial(entry, given, env, fixed)
    if bounded and len(possible) == 1:      # the unknown inputs cannot change the outcome: it is settled
        return Trace(outcome=possible[0], possible=possible, bounded=True, needed=[], inputs=inputs, steps=steps,
                     assumed=assumed)
    needed, waiting = parents_first(entry, needed, env,
                                    frozenset(k for k, v in given.items() if v.state != "unknown"))
    decides = {k: decides.get(k) or possible for k in needed}
    return Trace(possible=possible, bounded=bounded, needed=needed, waiting=waiting, decides=decides, inputs=inputs,
                 steps=steps, assumed=assumed)


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
