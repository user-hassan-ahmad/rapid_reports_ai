"""UICC TNM 9th edition as a Copilot provider (spec §5.8): offline (resources/tnm_9th_clean.json v2.2), verified by
provenance, no fetch. One branch with T, N and M inputs (X first: the reporting convention for an axis that cannot
be assessed), plus histology where a site's stage table varies by it. The proposal is assembled in code; the stage
comes from the rebuilt, hand-checked stage_tables (scripts/tnm/rebuild_stage_tables.py: keep lookup identical)."""
from __future__ import annotations

import json
from itertools import product
from functools import lru_cache
from pathlib import Path

from ...tnm_lookup import TnmResult, format_tnm_evidence
from .registry import slug
from .types import Branch, Entry, GuidelineContent, Input, Output, Proposal, Publication, Source

DATA = Path(__file__).resolve().parents[2] / "resources" / "tnm_9th_clean.json"
# Not TNM-staged in practice: CNS (WHO grade), lymphomas (Lugano), GTN (FIGO + prognostic score).
EXCLUDED = {"Brain & Spinal Cord", "Hodgkin Lymphoma", "Non-Hodgkin Lymphomas", "Gestational Trophoblastic Neoplasms"}
X = {"T": "TX", "N": "NX", "M": "MX"}
TAG = "UICC TNM 9th"
SOURCE = "UICC TNM Classification of Malignant Tumours, 9th edition (offline)"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text())["tumours"]


def sites() -> list[str]:
    return [s for s, r in _data().items() if s not in EXCLUDED and any(r["tnm"].get(a) for a in "TNM")]


def key_for(site: str) -> str:
    return f"tnm-{slug(site)}@9"


def is_tnm(key: str) -> bool:
    return key.startswith("tnm-")


def site_for(key: str) -> str | None:
    return next((s for s in sites() if key_for(s) == key), None)


def _tables(site: str) -> list[dict]:
    return [t for t in _data()[site].get("stage_tables") or [] if t.get("verified")]


def variants(site: str) -> list[str]:
    return [t["variant"] for t in _tables(site) if t["variant"]]


def _pt_only(site: str) -> bool:
    """T is classified only after excision (pT): no clinical T categories, a pT table or a T_note instead."""
    t = _data()[site]["tnm"]
    return not t.get("T") and bool(t.get("pT") or t.get("T_note"))


def axes(site: str) -> list[str]:
    """The axes this site defines; a pT-only site keeps T (reported as TX clinically)."""
    t = _data()[site]["tnm"]
    return [a for a in "TNM" if t.get(a) or (a == "T" and _pt_only(site))]


def _cats(site: str) -> dict[str, list[str]]:
    return {a: list((_data()[site]["tnm"].get(a) or {}).keys()) for a in "TNM"}


def _options(site: str, axis: str) -> list[str]:
    cats = _cats(site)[axis]
    return cats if X[axis] in cats else [X[axis], *cats]


def _result(site: str) -> TnmResult:
    r = _data()[site]
    return TnmResult(tumour=site, icd_o=r.get("icd_o", ""), edition_uicc="9th", edition_ajcc=None,
                     tnm_json={a: r["tnm"].get(a) or {} for a in "TNM"},
                     stage_grouping=[{"stage": g["stage"], **{a: ", ".join(g[a]) for a in "TNM"}}
                                     for t in _tables(site) for g in t["rows"]],
                     rules=r.get("rules", ""), rrf_score=1.0)


def material(site: str) -> str:
    return format_tnm_evidence(_result(site))


def _inputs(site: str) -> list[Input]:
    inputs = [Input(id=a, question=f"{a} category", options=_options(site, a)) for a in axes(site)]
    if variants(site):
        inputs.append(Input(id="histology", question="Histology", options=variants(site)))
    return inputs


def entry(site: str) -> Entry:
    r = _data()[site]
    rule = "\n".join(f"{k}: {v}" for a in "TNM" for k, v in (r["tnm"].get(a) or {}).items())
    if _pt_only(site) and r["tnm"].get("T_note"):
        rule = f"T: {r['tnm']['T_note']}\n{rule}"
    outputs = [Output(when=f"{t['variant'] + ': ' if t['variant'] else ''}{', '.join(g['T'])} | {', '.join(g['N'])} | "
                           f"{', '.join(g['M'])}", classification=g["stage"],
                      quote=f"{g['stage']}: {' '.join(g['T'])} {' '.join(g['N'])} {' '.join(g['M'])}")
               for t in _tables(site) for g in t["rows"]]
    return Entry(key=key_for(site), name=f"TNM {site}", version="9", status="verified",
                 publication=Publication(title=SOURCE, body="UICC", year="2025"),
                 content=GuidelineContent(applies_to=(r.get("rules") or "").split(". ")[0] or f"{site} tumours",
                                          summary=f"{TAG} staging of {site.lower()} tumours.",
                                          branches=[Branch(name="Staging", state="checked", inputs=_inputs(site),
                                                           rule=rule, outputs=outputs)]),
                 sources=[Source(url="", title=SOURCE, tier=1)])


def _matches(cat: str, cells: list[str]) -> int:
    """2: exact cell; 1: 'Any' or the cell is its parent (T2b under 'T2'); 0: no match. An X category matches only a
    cell that lists it (Lung 'Occult carcinoma TX N0 M0') or 'Any'."""
    if cat in cells:
        return 2
    if "Any" in cells:
        return 1
    if cat.endswith("X"):
        return 0
    return 1 if any(cat.startswith(c) for c in cells) else 0


def _direct(rows: list[dict], t: str, n: str, m: str) -> str | None:
    hits = []
    for g in rows:
        s = [_matches(c, g[a]) for c, a in ((t, "T"), (n, "N"), (m, "M"))]
        if all(s):
            hits.append((sum(s), g["stage"]))
    if not hits:
        return None
    best = max(h for h, _ in hits)
    stages = {st for h, st in hits if h == best}
    stages = {st for st in stages if not any(o != st and o.startswith(st) for o in stages)}   # IIA over II
    return stages.pop() if len(stages) == 1 else None


def _leaves(cat: str, cats: list[str]) -> list[str]:
    """The most specific subcategories of `cat` (M1 -> M1a, M1b, M1c1, M1c2), or [] when it has none."""
    kids = [k for k in cats if k != cat and k.startswith(cat) and not k.endswith("X")]
    return [k for k in kids if not any(o != k and o.startswith(k) for o in kids)]


def lookup(rows: list[dict], t: str, n: str, m: str, cats: dict[str, list[str]] | None = None) -> str | None:
    """A parent category no row lists exactly (Lung M1 over M1a-M1c2) is resolved through its subcategories: one
    stage when they all agree, else None. A row that lists the parent itself (Colon 'Stage IV ... M1') wins."""
    cats = cats or {}
    q = {"T": t, "N": n, "M": m}
    split = {a: _leaves(c, cats.get(a, [])) for a, c in q.items()}
    split = {a: kids for a, kids in split.items() if kids and not any(q[a] in g[a] for g in rows)}
    if not split:
        return _direct(rows, t, n, m)
    got = {_direct(rows, *combo) for combo in product(*(split.get(a) or [q[a]] for a in "TNM"))}
    return got.pop() if len(got) == 1 and None not in got else None


def stage(site: str, variant: str, t: str, n: str, m: str) -> str | None:
    tables = _tables(site)
    if len(tables) > 1:
        tables = [x for x in tables if x["variant"] == variant]
    return lookup(tables[0]["rows"], t, n, m, _cats(site)) if len(tables) == 1 else None


def proposal(site: str, settled: dict[str, str]) -> Proposal | None:
    """Every input answered (a single-option input, the pT-only TX, is answered by itself); prints only the site's
    axes, and a stage only where a verified table gives one."""
    settled = {**{i.id: i.options[0] for i in _inputs(site) if len(i.options) == 1}, **settled}
    ax = axes(site)
    if any(not settled.get(a) for a in ax) or (variants(site) and settled.get("histology") not in variants(site)):
        return None
    tnm = "c" + " ".join(settled[a] for a in ax)
    st = stage(site, settled.get("histology", ""), settled["T"], settled["N"], settled["M"]) if ax == list("TNM") else None
    text = f"{tnm}, {st}" if st else tnm
    return Proposal(classification=f"{text} ({TAG})", line=f"Staging ({TAG}): {text}.")
