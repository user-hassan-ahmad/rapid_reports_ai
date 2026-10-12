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


def material(e: Entry, sources: list[dict]) -> str:
    """What Ask grounds an answer on for a library entry: its own located facts (rules, bands, outcomes, caveats,
    reference fields) and the rows of its reference tables. Each source's title is printed once; every line cites it
    by id and page. Nothing from outside the entry."""
    used = {loc.source for _, _, loc in facts(e)} | {t.locator.source for t in e.reference.tables if t.locator}
    lines = [f"{e.display} ({e.issuer}, edition {e.edition}). Sources: " + "; ".join(
        f"{s['id']} = {cite_text({'title': s.get('title', ''), 'edition': s.get('edition', '')})}"
        for s in sources if s.get("id") in used) + "."]
    lines.append("Inputs: " + "; ".join(i.label + (f" ({i.how_stated})" if i.how_stated else "") for i in e.inputs) + ".")
    lines += [f"- {claim} [{_short(loc)}]" for _, claim, loc in facts(e)]
    for t in e.reference.tables:
        lines.append(f"{t.title} [{_short(t.locator)}]: " + " | ".join(t.columns))
        lines += ["  " + " | ".join(r) for r in t.rows]
    return "\n".join(lines)
