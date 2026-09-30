"""Save-time structure of a stored template skill sheet (spec 2026-09-30-template-pipeline-mirror §2).

A template sheet is the radiologist's voice with irregular conditionals. A model pass turns it into
typed items once; code keeps only what it can ground in the sheet, and marks the structure usable
only when every conditional line and every negative line is covered. The lean _BRIEF prompts only
ever meet a fully labelled sheet; anything else generates down the raw path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator

from .report_review import is_negative

logger = logging.getLogger(__name__)

STRUCTURE_VERSION = 1
Role = Literal["history", "technique", "comparison", "findings", "impression", "other"]


def _listify(v):
    return json.loads(v) if isinstance(v, str) else v


class StructSection(BaseModel):
    name: str
    role: Role
    header: Optional[str] = None
    order: int


class Paragraph(BaseModel):
    id: str
    section: str
    name: str


class Rule(BaseModel):
    id: str
    section: str
    paragraph: str = ""
    condition: str
    condition_source: Literal["findings", "history", "context"] = "findings"
    effect: Literal["suppress", "replace", "append", "use"]
    target: str = ""
    then_text: str = ""
    source_lines: List[str]


class Negative(BaseModel):
    id: str
    section: str
    paragraph: str = ""
    text: str
    condition: Optional[str] = None
    source_lines: List[str]


class Normal(BaseModel):
    id: str
    section: str
    paragraph: str = ""
    structure: str
    text: str
    source_line: str


class FixedBlock(BaseModel):
    id: str
    section: str
    text: str


class Terminology(BaseModel):
    preferred: List[str] = []
    suppressed: List[str] = []


class IfPresentNeg(BaseModel):
    text: str
    tag: Literal["core", "contextual"]


class IfPresent(BaseModel):
    finding: str
    section: str
    paragraph: str = ""
    negatives: List[IfPresentNeg]


class Coverage(BaseModel):
    if_lines: int = 0
    if_covered: int = 0
    negative_lines: int = 0
    negative_covered: int = 0
    uncovered: List[str] = []
    verbatim_failures: List[str] = []


class StructureDraft(BaseModel):
    """What the model returns; build_structure verifies it."""
    sections: List[StructSection]
    paragraphs: List[Paragraph] = []
    rules: List[Rule] = []
    negatives: List[Negative] = []
    normals: List[Normal] = []
    fixed_blocks: List[FixedBlock] = []
    terminology: Terminology = Terminology()
    if_present: List[IfPresent] = []

    @field_validator("sections", "paragraphs", "rules", "negatives", "normals", "fixed_blocks", "if_present",
                     mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return _listify(v)


class SheetStructure(StructureDraft):
    version: int = STRUCTURE_VERSION
    sheet_hash: str
    model: str
    created_at: str
    usable: bool = False
    coverage: Coverage = Coverage()


# ── verification ─────────────────────────────────────────────────────────────

def sheet_hash(sheet: str) -> str:
    return hashlib.sha256(sheet.encode()).hexdigest()


def _norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = s.replace("—", "-").replace("–", "-").replace("*", "").replace("`", "")
    s = re.sub(r"^\s*(?:-|\d+\.)\s+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", _norm(s)))


def _covers(source_line: str, line: str) -> bool:
    a, b = _norm(source_line), _norm(line)
    return bool(a) and (a == b or (a in b and len(a) >= 0.6 * len(b)) or b in a)


def conditional_lines(sheet: str) -> List[str]:
    """Sheet lines that carry a conditional (an uppercase IF), outside headings."""
    return [ln for ln in sheet.splitlines() if re.search(r"\bIF\b", ln) and not ln.lstrip().startswith("#")]


def negative_lines(sheet: str) -> List[str]:
    """Quoted lines under a paragraph's Mandatory negatives bullet, and every quoted bullet under
    '## Negative Finding Rules'."""
    out, section, in_mand, mand_indent = [], "", False, 0
    for ln in sheet.splitlines():
        if ln.startswith("## "):
            section, in_mand = ln[3:].strip(), False
            continue
        if ln.startswith("#"):
            in_mand = False
            continue
        indent = len(ln) - len(ln.lstrip())
        if "Mandatory negatives" in ln:
            in_mand, mand_indent = True, indent
            continue
        if in_mand and ln.strip() and indent <= mand_indent:
            in_mand = False
        quoted = re.match(r'^\s*-\s+["“]', ln)
        if quoted and (in_mand or section == "Negative Finding Rules"):
            out.append(ln)
    return out


def _structural_pattern(sheet: str) -> str:
    m = re.search(r"^## Structural Pattern\n(.*?)(?=^## |\Z)", sheet, re.M | re.S)
    return m.group(1) if m else ""


def build_structure(sheet: str, draft: StructureDraft, model: str) -> SheetStructure:
    """Keep only what is grounded in the sheet, then gate on coverage."""
    ns = _norm(sheet)
    failures: List[str] = []

    def grounded(label: str, *texts: str) -> bool:
        bad = [t for t in texts if t and _norm(t) not in ns]
        failures.extend(f"{label}: {t}" for t in bad)
        return not bad

    pattern = _structural_pattern(sheet).lower()
    sections = [s for s in draft.sections if s.name.lower() in pattern]
    rules = [r for r in draft.rules if grounded(f"rule {r.id}", r.target, r.then_text, *r.source_lines)]
    negatives = [n for n in draft.negatives if grounded(f"negative {n.id}", n.text, *n.source_lines)]
    normals = [n for n in draft.normals
               if grounded(f"normal {n.id}", n.source_line) and _words(n.text) <= _words(n.source_line)
               or failures.append(f"normal {n.id}: {n.text}")]
    fixed = [b for b in draft.fixed_blocks if grounded(f"fixed {b.id}", b.text)]
    term = Terminology(preferred=[t for t in draft.terminology.preferred if grounded("preferred", t)],
                       suppressed=[t for t in draft.terminology.suppressed if grounded("suppressed", t)])
    sheet_negs = {_norm(n.text).rstrip(".") for n in negatives}
    if_present = []
    for ip in draft.if_present:
        keep = [x for x in ip.negatives if is_negative(x.text) and _norm(x.text).rstrip(".") not in sheet_negs]
        if keep:
            if_present.append(ip.model_copy(update={"negatives": keep}))

    ifs, negs = conditional_lines(sheet), negative_lines(sheet)
    rule_src = [sl for r in rules for sl in r.source_lines]
    neg_src = [sl for n in negatives for sl in n.source_lines]
    unc_if = [ln for ln in ifs if not any(_covers(sl, ln) for sl in rule_src)]
    unc_neg = [ln for ln in negs if not any(_covers(sl, ln) for sl in neg_src)]
    cov = Coverage(if_lines=len(ifs), if_covered=len(ifs) - len(unc_if), negative_lines=len(negs),
                   negative_covered=len(negs) - len(unc_neg), uncovered=[ln.strip() for ln in unc_if + unc_neg],
                   verbatim_failures=failures)
    return SheetStructure(
        sections=sections, paragraphs=draft.paragraphs, rules=rules, negatives=negatives, normals=normals,
        fixed_blocks=fixed, terminology=term, if_present=if_present, sheet_hash=sheet_hash(sheet), model=model,
        created_at=datetime.now(timezone.utc).isoformat(), coverage=cov,
        usable=bool(sections) and not unc_if and not unc_neg)


def _stored(config: dict) -> Optional[SheetStructure]:
    raw = (config or {}).get("sheet_structure")
    if not raw:
        return None
    try:
        return SheetStructure.model_validate(raw)
    except Exception:
        return None


def fresh(config: dict) -> Optional[SheetStructure]:
    """The stored structure if it matches this sheet, this version, and passed the gate."""
    s = _stored(config)
    sheet = (config or {}).get("skill_sheet", "")
    if s and s.version == STRUCTURE_VERSION and s.sheet_hash == sheet_hash(sheet) and s.usable:
        return s
    return None


def needs_restructure(config: dict) -> bool:
    """Missing, old or stale (an unusable but current structure is not rebuilt on every request)."""
    s = _stored(config)
    sheet = (config or {}).get("skill_sheet", "")
    return bool(sheet) and (s is None or s.version != STRUCTURE_VERSION or s.sheet_hash != sheet_hash(sheet))
