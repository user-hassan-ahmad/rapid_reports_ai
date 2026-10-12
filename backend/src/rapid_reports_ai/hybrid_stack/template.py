"""Regions from the radiologist's own template (spec §3.3, template path): the findings
paragraphs of a fresh grammar structure in template order, each paragraph's COVERS as includes."""
from __future__ import annotations

import re
from typing import Optional

from ..template_sheet_grammar import is_grammar_sheet, parse_sheet
from ..template_sheet_structure import SheetStructure, fresh
from .schemas import OTHER, Region, other_region


def template_structure(config: dict) -> Optional[SheetStructure]:
    """The structure a template scratchpad session uses, for its regions, its assumed normals and its Generate: the
    stored parse when it is fresh, else the sheet parsed now (a copy gone stale after an edit or a grammar version
    bump; the parser is pure code). None when the sheet is not a guided grammar sheet or does not parse clean: the
    session then has no assumed normals and Generate takes today's template path (a stack brief strips the sheet's
    normals, which only the assumed normals would have replaced)."""
    config = config if isinstance(config, dict) else {}
    st = fresh(config)
    if st is not None:
        return st
    sheet = config.get("skill_sheet") or ""
    if config.get("generation_mode") != "skill_sheet_guided" or not is_grammar_sheet(sheet):
        return None
    try:
        st = parse_sheet(sheet, mode="template").structure
    except Exception:
        return None
    return st if st.usable else None


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


_WORD = re.compile(r"[a-z]+")


def _named(text: str, structure: str) -> str:
    """A Normal whose own text does not name its structure ("Unremarkable." under NORMAL [liver]) is offered as
    "Liver: unremarkable.", so the check and the writer know what it is about (conversion lab 2026-10-12: Jev never
    kept a subject-less normal)."""
    words = set(_WORD.findall(text.lower()))
    label = (structure or "").strip()
    if not label or words & set(_WORD.findall(label.lower())):
        return text
    body = text.strip()
    return f"{label[:1].upper()}{label[1:]}: {body[:1].lower()}{body[1:]}"


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
        texts = [_named(n.text, n.structure) for n in st.normals if n.paragraph == p.id]
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
