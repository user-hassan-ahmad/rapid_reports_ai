"""Regions from the radiologist's own template (spec §3.3, template path): the findings
paragraphs of a fresh grammar structure in template order, each paragraph's COVERS as includes."""
from __future__ import annotations

from ..template_sheet_structure import SheetStructure
from .schemas import OTHER, Region, other_region


def template_regions(st: SheetStructure) -> list[Region]:
    order = {sec.name: sec.order for sec in st.sections}
    findings = {sec.name for sec in st.sections if sec.role == "findings"}
    paras = sorted((p for p in st.paragraphs if p.section in findings), key=lambda p: order.get(p.section, 0))
    out: list[Region] = []
    seen: set[str] = set()
    for p in paras:
        name = p.name if p.name.lower() not in seen else f"{p.name} ({p.section.title()})"
        seen.add(name.lower())
        out.append(Region(name=name, includes=", ".join(p.covers) or p.name))
    if OTHER.lower() not in seen:
        out.append(other_region())
    return out


def template_region_normals(st: SheetStructure) -> dict[str, list[str]]:
    """Each paragraph-region's normal sentences (checklist spec §8.3): its Normal statements and unconditioned
    Negative statements, as the template wrote them. Named as template_regions names them; a sentence with a
    measurement is never assumed; conditioned negatives are not used in this release."""
    from ..report_reconcile import _MEASUREMENT
    order = {sec.name: sec.order for sec in st.sections}
    findings = {sec.name for sec in st.sections if sec.role == "findings"}
    paras = sorted((p for p in st.paragraphs if p.section in findings), key=lambda p: order.get(p.section, 0))
    out: dict[str, list[str]] = {}
    seen: set[str] = set()
    for p in paras:
        name = p.name if p.name.lower() not in seen else f"{p.name} ({p.section.title()})"
        seen.add(name.lower())
        texts = [n.text for n in st.normals if n.paragraph == p.id]
        texts += [n.text for n in st.negatives if n.paragraph == p.id and n.condition is None]
        keep: list[str] = []
        for t in texts:
            t = " ".join(t.split()).strip()
            t = t if t.endswith(".") else t + "."
            if t != "." and not _MEASUREMENT.search(t) and t.lower() not in {k.lower() for k in keep}:
                keep.append(t)
        if keep:
            out[name] = keep
    return out
