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
_STOP = {"and", "of", "the", "with", "in", "on", "to", "a", "an", "or", "both"}


def _stem(w: str) -> str:
    w = w.lower()
    if w.endswith("us"):
        w = w[:-2] + "i"          # meniscus / menisci
    elif w.endswith("es"):
        w = w[:-2]
    elif w.endswith("s"):
        w = w[:-1]
    return w[:5]


def _names_structure(text: str, label: str) -> bool:
    """True when the sentence already names the structure (loose: stopwords and short words dropped from the label,
    crude plural stems, a 5-character prefix match)."""
    words = {_stem(w) for w in _WORD.findall(text.lower())}
    lab = {_stem(w) for w in _WORD.findall(label.lower()) if w not in _STOP and len(w) >= 3}
    return not lab or bool(words & lab)


def _normalise(t: str) -> str:
    t = " ".join(t.split()).strip()
    return t if t.endswith(".") else t + "."


def jev_text(sentence: str, label: str) -> str:
    """The sentence as put to the Jev check: "<Label>: <sentence>". Quotes stripped from the label, sentence-cased
    unless a word is an acronym (all caps, up to 4 letters). The sentence itself is kept as written."""
    label = " ".join(label.strip().strip("\"'`\u201c\u201d\u2018\u2019").split())
    words = label.split()
    if label.isupper() and any(len(w) > 4 for w in words):
        words = [w.lower() for w in words]            # a shouted label ("LEFT VENTRICLE"), not acronyms
    else:
        words = [w if (w.isalpha() and w.isupper() and len(w) <= 4) else w.lower() for w in words]
    label = " ".join(words)
    label = label[:1].upper() + label[1:]
    return f"{label}: {sentence}"


_SLOT = re.compile(r"\{[^{}]*\}")   # a fill-in placeholder ("LVEDVi {value} ml/m2"): never assumed


def _offered(st: SheetStructure):
    """(region name, sentence, structure label or None) for every sentence template_region_normals offers."""
    from ..report_reconcile import _MEASUREMENT
    order = {sec.name: sec.order for sec in st.sections}
    findings = {sec.name for sec in st.sections if sec.role == "findings"}
    paras = sorted((p for p in st.paragraphs if p.section in findings), key=lambda p: order.get(p.section, 0))
    seen: set[str] = set()
    for p in paras:
        name = p.name if p.name.lower() not in seen else f"{p.name} ({p.section.title()})"
        seen.add(name.lower())
        texts = [(n.text, n.structure) for n in st.normals if n.paragraph == p.id]
        texts += [(n.text, None) for n in st.negatives if n.paragraph == p.id and n.condition is None]
        keep: set[str] = set()
        for raw, label in texts:
            t = _normalise(raw)
            if t != "." and not _MEASUREMENT.search(t) and not _SLOT.search(t) and t.lower() not in keep:
                keep.add(t.lower())
                yield name, t, label


def template_region_normals(st: SheetStructure) -> dict[str, list[str]]:
    """Each paragraph-region's normal sentences (checklist spec §8.3): its Normal statements and unconditioned
    Negative statements, as the template wrote them. Named as template_regions names them; a sentence with a
    measurement is never assumed; conditioned negatives are not used in this release."""
    out: dict[str, list[str]] = {}
    for name, t, _ in _offered(st):
        out.setdefault(name, []).append(t)
    return out


def template_normal_labels(st: SheetStructure) -> dict[str, str]:
    """Offered sentence -> its NORMAL structure label, only for sentences that do not already name the structure.
    Used for the Jev check alone (jev_text); the offered text itself is never changed."""
    out: dict[str, str] = {}
    for _, t, label in _offered(st):
        if label and label.strip() and not _names_structure(t, label):
            out.setdefault(t, label)
    return out


def template_suppressions(st: SheetStructure) -> list[tuple[str, str]]:
    """(condition, sentence) for each context RULE that suppresses or replaces a sentence the scratchpad would
    assume: when the condition is met for the case, that sentence is not assumed (conversion lab 2026-10-12: a
    "no prior study" rule did not stop "compared with the previous MRI"). The sentence is returned as offered."""
    offered = {_key(t): t for _, t, _ in _offered(st)}
    out: list[tuple[str, str]] = []
    for r in st.rules:
        if r.condition_source != "context" or r.effect not in ("suppress", "replace") or not r.target:
            continue
        t = offered.get(_key(r.target))
        if t is not None and (r.condition, t) not in out:
            out.append((r.condition, t))
    return out


def _key(t: str) -> str:
    return " ".join(t.lower().split()).rstrip(".")
