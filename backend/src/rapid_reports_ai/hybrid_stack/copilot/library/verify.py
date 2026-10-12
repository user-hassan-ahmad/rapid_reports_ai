"""Quality gates 1–4 for one entry (library spec §8), run by the bundle build and by pytest. Returns problems, empty
when the entry passes. Gate 5 (Jev evidence) is scripts/guidelines/jev_evidence.py; gate 6 is the hand read."""
from __future__ import annotations

import math
from itertools import product

from .engine import PH, EvaluationError, Trace, V, _inputs, _iv, _num, domain, evaluate, reach_states, render, run
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
        p += _formulas(entry) + _enumerate(entry) + _golden(entry, cases)
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
    return reach_states(e, ref)


def _txt(v) -> str:
    return str(v.value) if v.state == "present" else f"@{v.state}"


def _enumerated_inputs(e: Entry) -> list:
    """The discrete inputs the enumeration needs: those the result reaches without passing through a band step (every
    band step is overridden with each band id, so what feeds it cannot matter), the inputs their prerequisites name,
    and any input an outcome placeholder names. Brock's risk factors, for example, reach the result only through the
    banded score, so enumerating them would only multiply identical combinations."""
    need, todo = set(), [e.result]
    todo += [m.group(1) for o in e.outcomes for t in (o.classification, o.recommendation, *o.caveats)
             for m in PH.finditer(t)]
    while todo:
        k = todo.pop()
        if k in need:
            continue
        need.add(k)
        s, i = e.step(k), e.input(k)
        if s is not None and not isinstance(s, BandStep):
            todo += s.refs()
        if i is not None:
            todo += [c.ref for p in i.prerequisites for c in conds(p)]
    return [i for i in e.inputs if i.type != "number" and i.id in need]


def _enumerate(e: Entry) -> list[str]:
    """Gate 2: every combination of discrete inputs and band ids gives exactly one outcome, and fills every
    placeholder in it. Numbers are not enumerated: their band steps are overridden with each band id instead, and
    inputs that reach the result only through a band step are left unknown (_enumerated_inputs)."""
    free = [("in", i.id, domain(e, i)) for i in _enumerated_inputs(e)]
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


def _samples(i) -> list[float]:
    """Values across a ranged input's valid range: near and at each bound, ordinary values, and far out."""
    xs = set(i.representatives([])) | {-1.0, 0.0, 1.0, 1e-9, -1e-9, 1e6, -1e6}
    for b in (i.min_value, i.max_value):
        if b is not None:
            xs |= {b, b + 1e-9, b - 1e-9, b + 1, b - 1, b + 1e6, b - 1e6}
    return sorted(x for x in xs if i.in_range(x))


def _formulas(e: Entry) -> list[str]:
    """A derive step whose inputs all declare a valid range must compute for every value in that range: it is
    sampled across the range (bounds, near-bounds, ordinary and far values). Steps on other values are skipped."""
    p: list[str] = []
    for s in e.logic:
        if not isinstance(s, DeriveStep):
            continue
        ins = [e.input(r) for r in dict.fromkeys(s.refs())]
        if not ins or any(i is None or i.type != "number" or not i.ranged for i in ins):
            continue
        grid = [_samples(i) for i in ins]
        if math.prod(len(g) for g in grid) > 20_000:
            p.append(f"{s.id}: too many range samples to check")
            continue
        for xs in product(*grid):
            env = {i.id: V(value=x) for i, x in zip(ins, xs)}
            try:
                _num(s.expr, env)
            except (EvaluationError, ArithmeticError) as ex:
                shown = ", ".join(f"{i.id}={x:g}" for i, x in zip(ins, xs))
                p.append(f"{s.id}: fails inside the declared ranges [{shown}]: {ex}")
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
