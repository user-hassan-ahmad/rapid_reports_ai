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


def citation(loc: Locator | None, sources: list[dict]) -> dict:
    """A locator with its source's public fields (title, issuer, edition, url) resolved from the bundle; {} for none."""
    if loc is None:
        return {}
    src = next((s for s in sources if s.get("id") == loc.source), {})
    out = {"source": loc.source, **{k: src[k] for k in ("title", "issuer", "edition", "url") if src.get(k)}}
    out.update({k: v for k, v in (("page", loc.page), ("section", loc.section), ("table", loc.table)) if v})
    return out


def cite_text(c: dict) -> str:
    """A citation as one short line: title (edition), p. N, section, table."""
    if not c:
        return ""
    head = c.get("title") or c.get("source", "")
    if c.get("edition"):
        head += f" ({c['edition']})"
    return ", ".join(x for x in (head, f"p. {c['page']}" if c.get("page") else "", c.get("section", ""),
                                 c.get("table", "")) if x)


def _short(loc: Locator | None) -> str:
    """A compact citation: source id, page, and the table or section name (cut to 40 characters)."""
    if loc is None:
        return ""
    where = ", ".join(x for x in (f"p. {loc.page}" if loc.page else "", (loc.table or loc.section)[:40]) if x)
    return f"{loc.source} {where}".strip()


NA, NA_MARK = "@not_applicable", "–"   # a table cell that matches a not-applicable input, and its mark


def material(e: Entry, sources: list[dict]) -> str:
    """What Ask grounds an answer on for a library entry: its own located facts (rules, bands, outcomes, caveats,
    reference fields) and the rows of its reference tables. Each source's title is printed once; every fact cites it
    by id and page. Nothing from outside the entry, and nothing dropped: each outcome's wording is printed once, rule
    and table rows name the outcome by id, and a caveat shared by several outcomes is printed once with their ids."""
    located = facts(e)
    used = {loc.source for _, _, loc in located} | {t.locator.source for t in e.reference.tables if t.locator}
    lines = [f"{e.display} ({e.issuer}, edition {e.edition}). Sources: " + "; ".join(
        f"{s['id']} = {cite_text({'title': s.get('title', ''), 'edition': s.get('edition', '')})}"
        for s in sources if s.get("id") in used) + "."]
    if e.inputs:
        lines.append("Inputs: " + "; ".join(i.label + (f" ({i.how_stated})" if i.how_stated else "")
                                            for i in e.inputs) + ".")
    by_id = {k: (claim, loc) for k, claim, loc in located}
    for s in e.logic:
        if isinstance(s, RulesStep):
            cases = [c for c in s.cases if c.locator is not None]
            if cases:
                lines.append(f"Rules {s.id} (condition → outcome id):")
            last = None
            for c in cases:
                if _short(c.locator) != last:
                    last = _short(c.locator)
                    lines.append(f"  [{last}]")
                lines.append(f"  {_expr(e, c.when)} → {c.result}")
        elif isinstance(s, TableStep):
            if s.locator is not None and s.rows:
                lines.append(f"Table {s.id} [{_short(s.locator)}]: "
                             + " | ".join(_name(e, k) for k in s.keys) + " → outcome id")
                if any(c == NA for r in s.rows for c in r.match):
                    lines.append(f"  ({NA_MARK} = not applicable)")
                lines += ["  " + " | ".join(NA_MARK if c == NA else _val(e, k, c) for k, c in zip(s.keys, r.match))
                          + f" → {r.result}" for r in s.rows]
        elif s.id in by_id:
            claim, loc = by_id[s.id]
            lines.append(f"- {claim} [{_short(loc)}]")
    located_outcomes = [o for o in e.outcomes if o.locator is not None]
    if located_outcomes:
        lines.append("Outcomes (id: classification → recommendation):")
        by_loc: dict[str, list] = {}
        for o in located_outcomes:
            by_loc.setdefault(_short(o.locator), []).append(o)
        for loc, group in by_loc.items():
            lines.append(f"  [{loc}]")
            lines += [f"- {o.id}: {_result(e, o.id)}" for o in group]
    caveats: dict[str, tuple[list[str], list[str]]] = {}
    for o in located_outcomes:
        for c in o.caveats:
            ids, locs = caveats.setdefault(c, ([], []))
            ids.append(o.id)
            if _short(o.locator) not in locs:
                locs.append(_short(o.locator))
    if caveats:
        lines.append("Caveats (outcome ids they apply to):")
        lines += [f"- ({', '.join(ids)}) {c} [{'; '.join(locs)}]" for c, (ids, locs) in caveats.items()]
    lines += [f"- {claim} [{_short(loc)}]" for k, claim, loc in located if k.startswith("reference.")]
    for t in e.reference.tables:
        lines.append(f"{t.title} [{_short(t.locator)}]: " + " | ".join(t.columns))
        lines += ["  " + " | ".join(r) for r in t.rows]
    return "\n".join(lines)


def reference_view(e: Entry, sources: list[dict]) -> dict:
    """The entry's reference fields for the reading pane, each with its citation instead of its locator. A tier 2
    card shows only this; a tier 1 card shows it beside the preview."""
    def one(f) -> dict:
        return {**f.model_dump(exclude={"locator"}), "citation": citation(f.locator, sources)}
    r = e.reference
    return {k: [one(f) for f in getattr(r, k)] for k in ("summary", "definitions", "tables", "pitfalls")}
