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
RETRY_AFTER_S = 3600  # a failed structuring attempt for the same sheet is retried after this long
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
    kind: Literal["negative", "stated_normal"] = "negative"  # stated_normal: a quoted normal-state line


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


def _words(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", _norm(s))


def _key(s: str) -> str:
    """Comparison key for a statement: normalised, trailing punctuation dropped."""
    return re.sub(r"[\s.!?]+$", "", _norm(s))


def _covers(source_line: str, line: str) -> bool:
    """A source line covers a sheet line only when it IS that line (after normalisation)."""
    a = _norm(source_line)
    return bool(a) and "\n" not in source_line and a == _norm(line)


_QUOTED = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|`([^`\n]+)`')
_QUOTE_CHARS = re.compile(r'["“”`]')
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
_NEGATION = {"no", "not", "without", "nil"}


def _quoted(line: str) -> List[str]:
    return [next(g for g in m.groups() if g) for m in _QUOTED.finditer(line)]


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _indent(line: str) -> int:
    ln = line.expandtabs(4)
    return len(ln) - len(ln.lstrip())


def _bullet_body(line: str) -> str:
    return _BULLET.sub("", line).replace("*", "").strip()


_IF = re.compile(r"\bIF\b")


def conditional_lines(sheet: str) -> List[str]:
    """Sheet lines that carry a conditional (an uppercase IF), outside headings."""
    return [ln for ln in sheet.splitlines() if _IF.search(ln) and not ln.lstrip().startswith("#")]


_MANDATORY = re.compile(r"mandatory negatives?", re.I)
_INSTRUCTION = re.compile(r"\b(?:never|instead|rather than|replace[sd]?|avoid|do not|don't|only when)\b"
                          r"|\bwhen\b.*\bis seen\b", re.I)
_NORMAL_STATE = re.compile(r"\b(?:unremarkable|normal|patent|intact|preserved|(?:is|are) clear|within normal limits"
                           r"|not (?:dilated|enlarged))\b", re.I)
# a qualifier outside the quotes that says when the line applies, in any form: "(if x)", "— if x",
# "(when x)", "(only in x)", "if x: ...", "[if x]", "(in x cases)"
_COND_WORD = re.compile(r"\b(?:if|when|whenever|where|unless|only|provided)\b|\bin [^)\]]*cases?\b", re.I)
_MANDATORY_NONE = re.compile(r"mandatory negatives?\W*none\b", re.I)  # "Mandatory negatives: None …"


def _quoted_statements(line: str) -> List[str]:
    return [s for q in _quoted(line) for s in [q, *_sentences(q)]]


def _outside_quotes(line: str) -> str:
    return _QUOTED.sub(" ", _bullet_body(line))


def _cond_noted(line: str) -> bool:
    """The line qualifies when its statement applies (text outside the quotes)."""
    return bool(_COND_WORD.search(_outside_quotes(line)))


_MAND_LABEL = re.compile(r"^\s*mandatory negatives?\s*:?\s*$", re.I)
_STATEMENT_TAIL = re.compile(r"^(?:[\s/,;.]|\x00|\bor\b|\band\b)*(?:$|[(\[]|[—–-]\s)", re.I)


def _statement_shape(line: str) -> bool:
    """Allow-list of the shape a listed statement takes: an optional bullet (or a bare Mandatory
    negatives label), then the quote(s), then optionally a trailing "(…)", "[…]" or "— …" note. Any other
    text before the first quote makes it wording guidance ("Prefer "…" for …", "Use "…" when …")."""
    body = _bullet_body(line)
    m = _QUOTE_CHARS.search(body)
    if not m or (body[:m.start()].strip() and not _MAND_LABEL.match(body[:m.start()])):
        return False
    return bool(_STATEMENT_TAIL.match(_QUOTED.sub("\x00", body[m.start():])))


_LABEL = re.compile(r"^\s*(?:[-*]\s+)?\*\*")


def _quotes_a_negative(line: str) -> bool:
    return any(is_negative(q) for q in _quoted_statements(line))


def negative_lines(sheet: str) -> List[str]:
    """Lines that state a negative the structure must cover. Fails closed: inside a Mandatory
    negatives block (header line included) or a '## Negative Finding Rules…' section, every line that
    carries a quote, or whose bullet body is itself a negative statement, counts."""
    out: List[str] = []
    in_nfr = in_mand = False
    mand_indent, mand_bulleted = 0, True
    for ln in sheet.splitlines():
        stripped = ln.strip()
        if stripped.startswith("#"):
            if ln.startswith("## "):
                in_nfr = ln[3:].strip().lower().startswith("negative finding rules")
            in_mand, mand_indent = bool(_MANDATORY.search(ln)), -1
            continue
        if not stripped:
            continue
        ind = _indent(ln)
        if _MANDATORY.search(ln):
            in_mand, mand_indent, mand_bulleted = True, ind, bool(_BULLET.match(ln))
            says_none = _MANDATORY_NONE.search(ln) and not any(is_negative(q) for q in _quoted_statements(ln))
            if (_QUOTE_CHARS.search(ln) and not _IF.search(ln) and not says_none
                    and (_quotes_a_negative(ln) or _statement_shape(ln))):
                out.append(ln)
            continue
        if in_mand and mand_indent >= 0 and ind <= mand_indent:
            child = not mand_bulleted and ind == mand_indent and _BULLET.match(ln) and not _LABEL.match(ln)
            if not child:
                in_mand = False
        if _IF.search(ln):
            continue  # a conditional line is gated as a rule, not twice
        if _INSTRUCTION.search(ln) and not _quotes_a_negative(ln):
            continue  # guidance about wording, with no negative statement of its own
        if not (in_mand or in_nfr):
            continue
        if _QUOTE_CHARS.search(ln):
            # a quote-bearing line counts when it quotes a negative, or is a listed statement; a
            # guidance-shaped line quoting only positives is never required (the gate must never
            # demand a positive statement)
            if _quotes_a_negative(ln) or _statement_shape(ln):
                out.append(ln)
        elif is_negative(_bullet_body(ln)):
            out.append(ln)
    return out


def _section_body(sheet: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", sheet, re.M | re.S)
    return m.group(1) if m else ""


def _structural_pattern(sheet: str) -> str:
    return _section_body(sheet, "Structural Pattern")


def _name_key(name: str) -> str:
    s = re.sub(r"\([^)]*\)", "", name.replace("*", "").replace("`", ""))
    return re.sub(r"[\s.,:;]+$", "", _norm(s))


def _item_names(item: str) -> List[str]:
    body = _BULLET.sub("", item)
    names = [re.split(r"\s+[-—–]\s+|:|\(", body.replace("*", "").replace("`", ""), maxsplit=1)[0]]
    names += re.findall(r"\*\*([^*]+)\*\*", body)
    return [k for k in (_name_key(n) for n in names) if k]


def section_names(sheet: str) -> set:
    """Output section names listed under the Structural Pattern's 'Sections included' (list items or
    an inline comma list). Without that line, the pattern's top-level item labels."""
    lines = _structural_pattern(sheet).splitlines()
    names: set = set()
    for i, ln in enumerate(lines):
        if "sections included" not in ln.lower():
            continue
        inline = ln.replace("*", "").split(":", 1)
        if len(inline) == 2 and inline[1].strip():
            names |= {k for part in re.sub(r"\([^)]*\)", "", inline[1]).split(",") if (k := _name_key(part))}
        head, level = _indent(ln), None
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            ind = _indent(nxt)
            if ind <= head:
                break
            level = ind if level is None else level
            if ind == level and _BULLET.match(nxt):
                names.update(_item_names(nxt))
        return names
    items = [ln for ln in lines if _BULLET.match(ln)]
    top = min((_indent(ln) for ln in items), default=0)
    for ln in items:
        if _indent(ln) == top:
            names.update(_item_names(ln))
    return names


def _paragraph_headings(sheet: str) -> set:
    return {_norm(ln[4:]) for ln in sheet.splitlines() if ln.startswith("### ")}


def _is_subsequence(needle: List[str], hay: List[str]) -> bool:
    it = iter(hay)
    return all(w in it for w in needle)


def _atomic_normal_ok(text: str, source_line: str) -> bool:
    """The atomic sentence uses the pattern's words in order and keeps every negation of the
    pattern sentence it is drawn from (so a split can never invert a statement)."""
    words = _words(text)
    if not words:
        return False
    pattern = " ".join(_quoted(source_line)) or re.split(r"normal pattern\W*", _norm(source_line), maxsplit=1)[-1]
    for sent in _sentences(pattern):
        sw = _words(sent)
        if _is_subsequence(words, sw) and all(w in words for w in _NEGATION & set(sw)):
            return True
    return False


def _negative_kind(text: str, source_lines: List[str]) -> Optional[str]:
    """'negative' for a negative statement. 'stated_normal' for a normal-state statement the sheet
    quotes whole on one of the item's own negative lines (sheets list mandatory normals such as
    "[structure] is patent." there), provided every such line has the listed-statement shape (an
    allow-list, never a word deny-list). Else None. Conditional lines are never negative lines, so
    a replacement clause cannot pass."""
    k = _key(text)
    if not k:
        return None
    if is_negative(text):
        return "negative"
    quoted_on = [ln for ln in source_lines if any(k == _key(s) for s in _quoted_statements(ln))]
    if (_NORMAL_STATE.search(text) and quoted_on and all(_statement_shape(ln) for ln in quoted_on)
            and not any(_INSTRUCTION.search(ln) for ln in quoted_on)):
        return "stated_normal"
    return None


def _dedupe(items: list, label: str, failures: List[str]) -> list:
    seen, out = set(), []
    for it in items:
        if it.id in seen:
            failures.append(f"duplicate {label} id {it.id}")
            continue
        seen.add(it.id)
        out.append(it)
    return out


def build_structure(sheet: str, draft: StructureDraft, model: str) -> SheetStructure:
    """Keep only what is grounded in the sheet, each item in its own whole source line(s), then gate
    on coverage. Everything fails closed: an item that cannot be verified is dropped and logged."""
    failures: List[str] = []
    sheet_lines = {_norm(ln) for ln in sheet.splitlines()} - {""}
    if_set = {_norm(ln) for ln in conditional_lines(sheet)}
    neg_lines = negative_lines(sheet)
    neg_set = {_norm(ln) for ln in neg_lines}

    def whole_lines(label: str, lines: List[str], allowed: set) -> bool:
        bad = [ln for ln in lines if not ln.strip() or "\n" in ln or _norm(ln) not in allowed]
        failures.extend(f"{label} source line: {ln}" for ln in bad)
        if not lines:
            failures.append(f"{label}: no source line")
        return bool(lines) and not bad

    def in_own_line(label: str, text: str, lines: List[str]) -> bool:
        ok = not text or any(_norm(text) in _norm(ln) for ln in lines)
        if not ok:
            failures.append(f"{label}: {text}")
        return ok

    def reject(label: str) -> bool:
        failures.append(label)
        return False

    allowed_sections = section_names(sheet)
    sections, kept = [], set()
    for s in draft.sections:
        k = _name_key(s.name)
        if not (k and k in allowed_sections):
            reject(f"section: {s.name}")
        elif k in kept:
            reject(f"duplicate section: {s.name}")
        else:
            kept.add(k)
            sections.append(s)

    def in_section(label: str, item) -> bool:
        """Every item must belong to a kept output section; no remapping."""
        return _name_key(item.section) in kept or reject(f"{label}: unknown section {item.section}")

    def condition_matches(n) -> bool:
        noted = any(_cond_noted(ln) for ln in n.source_lines)
        return noted == bool(n.condition and _norm(n.condition)) or reject(
            f"negative {n.id}: condition {'missing' if noted else 'not on its line'}")

    headings = _paragraph_headings(sheet)
    paragraphs = [p for p in _dedupe(draft.paragraphs, "paragraph", failures)
                  if ((_norm(p.name) and _norm(p.name) in headings) or reject(f"paragraph {p.id}: {p.name}"))
                  and in_section(f"paragraph {p.id}", p)]
    para_ids = {p.id for p in paragraphs}

    def para(item):
        return item if not item.paragraph or item.paragraph in para_ids else item.model_copy(update={"paragraph": ""})

    rules = [para(r) for r in _dedupe(draft.rules, "rule", failures)
             if in_section(f"rule {r.id}", r)
             and (_norm(r.condition) or reject(f"rule {r.id}: empty condition"))
             and whole_lines(f"rule {r.id}", r.source_lines, if_set)
             and in_own_line(f"rule {r.id} target", r.target, r.source_lines)
             and in_own_line(f"rule {r.id} then_text", r.then_text, r.source_lines)]
    negatives = [para(n).model_copy(update={"kind": _negative_kind(n.text, n.source_lines)})
                 for n in _dedupe(draft.negatives, "negative", failures)
                 if in_section(f"negative {n.id}", n)
                 and (_negative_kind(n.text, n.source_lines) or reject(f"negative {n.id}: not a negative: {n.text}"))
                 and whole_lines(f"negative {n.id}", n.source_lines, neg_set)
                 and in_own_line(f"negative {n.id}", n.text, n.source_lines)
                 and condition_matches(n)]
    normals = [para(n) for n in _dedupe(draft.normals, "normal", failures)
               if in_section(f"normal {n.id}", n)
               and (n.source_line.strip() and "normal pattern" in _norm(n.source_line)
                   and whole_lines(f"normal {n.id}", [n.source_line], sheet_lines)
                   and _atomic_normal_ok(n.text, n.source_line))
               or reject(f"normal {n.id}: {n.text}")]

    sheet_norm_lines = "\n".join(_norm(ln) for ln in sheet.splitlines() if _norm(ln))
    fixed = [b for b in _dedupe(draft.fixed_blocks, "fixed", failures)
             if in_section(f"fixed {b.id}", b)
             and (((body := "\n".join(_norm(ln) for ln in b.text.splitlines() if _norm(ln)))
                   and body in sheet_norm_lines) or reject(f"fixed {b.id}: {b.text}"))]

    term_body = _norm(_section_body(sheet, "Terminology Rules"))

    def terms(kind: str, items: List[str]) -> List[str]:
        """Whole-word terms of the Terminology Rules section, one each (case-insensitive)."""
        out, seen = [], set()
        for t in items:
            k = _norm(t)
            if not (k and re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", term_body)):
                reject(f"{kind}: {t}")
            elif k not in seen:
                seen.add(k)
                out.append(t)
        return out
    term = Terminology(preferred=terms("preferred", draft.terminology.preferred),
                       suppressed=terms("suppressed", draft.terminology.suppressed))

    sheet_negs = {_key(s) for q in _QUOTED.finditer(sheet) for s in _sentences(next(g for g in q.groups() if g))}
    sheet_negs |= {_key(n.text) for n in negatives}
    if_present = []
    for ip in draft.if_present:
        keep, seen = [], set()
        for x in ip.negatives:
            k = _key(x.text)
            if is_negative(x.text) and k and k not in sheet_negs and k not in seen:
                keep.append(x)
                seen.add(k)
        if _norm(ip.finding) and keep and in_section(f"if_present {ip.finding}", ip):
            if_present.append(para(ip.model_copy(update={"negatives": keep[:3]})))

    ifs = conditional_lines(sheet)
    rule_src = {_norm(sl) for r in rules for sl in r.source_lines}
    neg_src = {_norm(sl) for n in negatives for sl in n.source_lines}
    unc_if = [ln for ln in ifs if _norm(ln) not in rule_src]
    unc_neg = [ln for ln in neg_lines if _norm(ln) not in neg_src]
    cov = Coverage(if_lines=len(ifs), if_covered=len(ifs) - len(unc_if), negative_lines=len(neg_lines),
                   negative_covered=len(neg_lines) - len(unc_neg), uncovered=[ln.strip() for ln in unc_if + unc_neg],
                   verbatim_failures=failures)
    return SheetStructure(
        sections=sections, paragraphs=paragraphs, rules=rules, negatives=negatives, normals=normals,
        fixed_blocks=fixed, terminology=term, if_present=if_present, sheet_hash=sheet_hash(sheet), model=model,
        created_at=datetime.now(timezone.utc).isoformat(), coverage=cov,
        usable=bool(sections) and not unc_if and not unc_neg)


def _raw(config: dict) -> dict:
    raw = (config or {}).get("sheet_structure")
    return raw if isinstance(raw, dict) else {}


def _stored(config: dict) -> Optional[SheetStructure]:
    raw = _raw(config)
    if not raw or raw.get("failed"):
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
    """Missing, old or stale. An unusable-but-current structure is not rebuilt on every request, nor is
    a failure marker for the current sheet and version until it is RETRY_AFTER_S old; a sheet edit
    retries at once."""
    sheet = (config or {}).get("skill_sheet", "")
    if not sheet:
        return False
    raw = _raw(config)
    if raw.get("version") == STRUCTURE_VERSION and raw.get("sheet_hash") == sheet_hash(sheet):
        if raw.get("failed"):
            return _age_s(raw.get("created_at")) > RETRY_AFTER_S  # transient failures retry later
        return _stored(config) is None
    return True


def _age_s(created_at) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(created_at)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


# ── structuring call and background store ───────────────────────────────────

STRUCTURE_TIMEOUT_S = 120.0


def structure_model() -> str:
    """Chosen in E1 (ledger); overridable on Railway."""
    return os.environ.get("RR_STRUCTURE_MODEL", "gpt-oss-120b")


STRUCTURE_SYS = """You convert a radiology report skill sheet into typed items. The sheet is the reporter's own style guide; you do not change it, judge it or add to it, except for the if_present list. Copy text exactly as it appears in the sheet (same words, same punctuation) wherever a field says "verbatim". Each source line (every entry of source_lines, and source_line) is exactly one whole sheet line, copied verbatim; never join lines. Return JSON only.

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


def _store(db, template_id: str, digest: str, payload: dict, keep_usable: bool = False) -> bool:
    """Write sheet_structure only if the template's sheet is still the one the payload was built from
    (and, with keep_usable, never over a usable structure of that sheet). The row is locked for the
    read-check-write so a concurrent sheet save cannot be overwritten."""
    tpl = (db.query(Template).filter(Template.id == uuid.UUID(str(template_id))).with_for_update().first())
    if (not tpl or sheet_hash((tpl.template_config or {}).get("skill_sheet", "")) != digest
            or (keep_usable and fresh(tpl.template_config) is not None)):
        db.rollback()
        return False
    tpl.template_config = {**tpl.template_config, "sheet_structure": payload}
    flag_modified(tpl, "template_config")
    db.commit()
    return True


def store_structure(db, template_id: str, structure: SheetStructure) -> bool:
    """Write the structure only if the template's sheet is still the one it was built from."""
    return _store(db, template_id, structure.sheet_hash, structure.model_dump(mode="json"))


def store_failure(db, template_id: str, sheet: str, error: str) -> bool:
    """Record that structuring this sheet failed, so repeated triggers for the same sheet do not call
    the model again until RETRY_AFTER_S has passed (fresh() treats the marker as unusable). An edit
    retries at once. Never replaces a usable structure of the same sheet."""
    digest = sheet_hash(sheet)
    return _store(db, template_id, digest,
                  {"version": STRUCTURE_VERSION, "sheet_hash": digest, "failed": True, "error": error[:500],
                   "created_at": datetime.now(timezone.utc).isoformat()}, keep_usable=True)


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
            try:
                s = await structure_sheet(sheet)
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                logger.warning("sheet structure %s failed (%s)", template_id, err)
                db = SessionLocal()
                try:
                    store_failure(db, template_id, sheet, err)
                finally:
                    db.close()
                return
            db = SessionLocal()
            try:
                ok = store_structure(db, template_id, s)
            finally:
                db.close()
            logger.info("sheet structure %s: stored=%s usable=%s coverage=%s", template_id, ok, s.usable,
                        s.coverage.model_dump())
        except Exception as e:
            logger.warning("sheet structure %s not stored (%s: %s)", template_id, type(e).__name__, str(e)[:200])
        finally:
            _inflight.discard(key)
    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        _inflight.discard(key)
        logger.warning("sheet structure %s not scheduled: no running event loop", template_id)
        return
    _tasks.add(task)  # the loop holds only a weak reference to a task
    task.add_done_callback(_tasks.discard)
