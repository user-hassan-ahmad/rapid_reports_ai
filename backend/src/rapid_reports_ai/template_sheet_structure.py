"""Save-time structure of a stored template skill sheet (spec 2026-09-30-template-pipeline-mirror §2).

A template sheet is the radiologist's voice with irregular conditionals. A model pass turns it into
typed items once; code keeps only what it can ground in the sheet, and marks the structure usable
only when every conditional line and every negative line is covered. The lean _BRIEF prompts only
ever meet a fully labelled sheet; anything else generates down the raw path.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator
from sqlalchemy.orm.attributes import flag_modified

from .database import SessionLocal
from .database.models import Template
from .enhancement_utils import _run_agent_with_model
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


# ── structuring call and background store ───────────────────────────────────

STRUCTURE_TIMEOUT_S = 120.0


def structure_model() -> str:
    """Chosen in E1 (ledger); overridable on Railway."""
    return os.environ.get("RR_STRUCTURE_MODEL", "gpt-oss-120b")


STRUCTURE_SYS = """You convert a radiology report skill sheet into typed items. The sheet is the reporter's own style guide; you do not change it, judge it or add to it, except for the if_present list. Copy text exactly as it appears in the sheet (same words, same punctuation) wherever a field says "verbatim". Return JSON only.

sections — the report's OUTPUT sections from the Structural Pattern, in order: name, role (history | technique | comparison | findings | impression | other), header exactly as reports write it (null when the sheet says the header is none or implicit), order (0-based). Paragraph groupings inside a section are not sections.

paragraphs — each "### <name>" block under Per-Section Construction Rules: id (p0, p1, …), the output section it belongs to, name.

rules — one per sheet line that holds a conditional, in any form: IF [condition] THEN suppress "[negative]", IF [condition] THEN append "[clause]", IF x: "[text]", bold **IF [..]**, compound OR conditions. id (r0, …); section and paragraph id where it applies; condition rewritten as one plain statement that can be judged true or false for a case ("The dictated findings report [X]" for an imaging condition; "The clinical history reports [Y]" or "The clinical context is [Z]" for a history or context condition); condition_source: findings | history | context; effect: suppress (drop the target text) | replace (drop the target text and write then_text) | append (add then_text, e.g. an interpretive clause) | use (a phrasing variant); target: the text it suppresses or replaces, verbatim, else ""; then_text: the text it adds, verbatim, else ""; source_lines: the whole sheet line(s), verbatim. Every conditional line in the sheet must appear in some rule's source_lines.

negatives — every quoted negative statement listed under a paragraph's Mandatory negatives and under Negative Finding Rules. One item per statement: a line holding two quoted statements gives two items with the same source line. The same statement listed in several places is ONE item whose source_lines lists every line it appears on. text verbatim (the quoted statement); condition: when the line attaches one ("(if [X])"), the plain statement "The dictated findings report [X]", else null; source_lines verbatim.

normals — split every Normal pattern into one item per structure it names: structure (the structure's name), text (a sentence for that structure alone, using only words from the pattern line: "Unremarkable appearances of the [A], [B] and [C]." gives "Unremarkable appearances of the [A]." and so on), source_line verbatim.

fixed_blocks — each fixed block's text, verbatim. Empty when the sheet says none were identified.

terminology — preferred and suppressed terms, verbatim, one term each.

if_present — the only list you write rather than copy. For the findings this scan commonly reports, give the finding (a short general name) and up to three negatives a consultant states once that finding is reported: the absence of each extension, spread or complication this technique shows and the next management step depends on. One finding per negative, starting "No", written in this sheet's own negative style. tag core when the next management step depends on it, contextual otherwise. Never repeat a negative the sheet already lists. Assign each to the section and paragraph where the finding is described."""


async def structure_sheet(sheet: str, model: Optional[str] = None) -> SheetStructure:
    model = model or structure_model()
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=model, output_type=StructureDraft, system_prompt=STRUCTURE_SYS,
        user_prompt=f"SKILL SHEET:\n\n{sheet}", api_key="",
        model_settings={"temperature": 0, "max_tokens": 32000, "reasoning_effort": "low"}), STRUCTURE_TIMEOUT_S)
    return build_structure(sheet, r.output, model)


def store_structure(db, template_id: str, structure: SheetStructure) -> bool:
    """Write the structure only if the template's sheet is still the one it was built from."""
    tpl = db.query(Template).filter(Template.id == uuid.UUID(str(template_id))).first()
    if not tpl or sheet_hash((tpl.template_config or {}).get("skill_sheet", "")) != structure.sheet_hash:
        return False
    tpl.template_config = {**tpl.template_config, "sheet_structure": structure.model_dump(mode="json")}
    flag_modified(tpl, "template_config")
    db.commit()
    return True


_inflight: set = set()
_tasks: set = set()


def schedule_structure(template_id: str, sheet: str) -> None:
    """Background: structure the sheet and store it. Never raises; one task per (template, sheet)."""
    key = (str(template_id), sheet_hash(sheet))
    if key in _inflight:
        return
    _inflight.add(key)

    async def run():
        try:
            s = await structure_sheet(sheet)
            db = SessionLocal()
            try:
                ok = store_structure(db, template_id, s)
            finally:
                db.close()
            logger.info("sheet structure %s: stored=%s usable=%s coverage=%s", template_id, ok, s.usable,
                        s.coverage.model_dump())
        except Exception as e:
            logger.warning("sheet structure %s failed (%s: %s)", template_id, type(e).__name__, str(e)[:200])
        finally:
            _inflight.discard(key)
    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        _inflight.discard(key)
        return
    _tasks.add(task)  # the loop holds only a weak reference to a task
    task.add_done_callback(_tasks.discard)
