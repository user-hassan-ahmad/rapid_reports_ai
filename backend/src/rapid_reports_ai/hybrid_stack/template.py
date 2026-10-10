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
