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
        "id": f"tnm-{slug(site)}", "version": "9.0", "topic": f"tnm-{slug(site)}",
        "purpose": f"Stages a primary cancer of this site by its T, N and M categories (UICC TNM, 9th edition): {site}.",
        "issuer": "UICC",
        "system": tnm.SOURCE, "display": f"TNM {site}", "edition": "9", "tier": 1,
        "applies_to": {"finding_type": ["primary malignancy"]},
        "inputs": inputs,
        "logic": [{"step": "table", "id": "stage", "keys": (["histology"] if vs else []) + ["T", "N", "M"],
                   "rows": rows, "locator": loc}],
        "result": "stage", "outcomes": outcomes})
