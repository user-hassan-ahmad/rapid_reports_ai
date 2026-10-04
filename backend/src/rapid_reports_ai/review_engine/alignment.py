"""Alignment: report clauses ↔ dictated lines (spec §5.2). Pure code. Ambiguity is kept: every pair above
the floor is returned, and Jev is never asked to choose between overlapping spans."""
from __future__ import annotations

import re
from typing import List, Literal, Optional, Set, Tuple

from pydantic import BaseModel

from .. import report_reconcile as rc
from ..report_review import ReportSection, _sentence_positions, clauses_in_context, dictated_items, section_spans

PAIR_FLOOR = 0.34   # provisional: Gate B1 (≥ 95% of clauses correctly paired or correctly unmatched)

Side = Literal["left", "right", "bilateral"]


class DictLine(BaseModel):
    id: str
    text: str
    side: Optional[Side] = None
    level: Optional[str] = None
    negative: bool = False
    background: bool = False             # the omission selector says not reportable (L-49), or a history line


class ReportClause(BaseModel):
    id: str
    text: str
    section: str
    start: int                           # offsets of the clause's sentence in the report
    end: int
    side: Optional[Side] = None
    level: Optional[str] = None
    negative: bool = False
    subheading_side: Optional[Side] = None


class Pair(BaseModel):
    line_id: str
    clause_id: str
    score: float
    how: Literal["exact", "lexical", "number", "anatomy"]


class Alignment(BaseModel):
    lines: List[DictLine]
    clauses: List[ReportClause]
    pairs: List[Pair]
    unmatched_lines: List[str]
    unmatched_clauses: List[str]
    history: List[DictLine] = []         # clinical history: a second source for Accuracy, never a coverage target

    def clause(self, cid: str) -> ReportClause:
        return next(c for c in self.clauses if c.id == cid)

    def line(self, lid: str) -> DictLine:
        return next(l for l in self.lines if l.id == lid)

    def paired_clauses(self, line_id: str) -> List[ReportClause]:
        ids = [p.clause_id for p in sorted(self.pairs, key=lambda p: -p.score) if p.line_id == line_id]
        return [self.clause(i) for i in ids]

    def paired_lines(self, clause_id: str) -> List[DictLine]:
        ids = [p.line_id for p in sorted(self.pairs, key=lambda p: -p.score) if p.clause_id == clause_id]
        return [self.line(i) for i in ids]


# ── small text helpers (shared with checks.py) ──────────────────────────────

_ROLE_WORDS = (("impression", "impression"), ("conclusion", "impression"), ("summary", "impression"),
               ("comment", "impression"), ("opinion", "impression"), ("history", "history"),
               ("indication", "history"), ("technique", "technique"), ("protocol", "technique"),
               ("comparison", "comparison"))
_SKIP_ROLES = {"history", "technique", "comparison"}


def section_models(sections: List[str]) -> List[ReportSection]:
    """Generic headings → ReportSection with a role guessed from the heading's words."""
    out = []
    for h in sections:
        low = h.lower()
        role = next((r for w, r in _ROLE_WORDS if w in low), "findings")
        out.append(ReportSection(name=h, header=h, role=role))
    return out


_SIDE_RE = re.compile(r"\b(left|right|bilateral(?:ly)?|both)\b", re.I)


def side_of(text: Optional[str]) -> Optional[Side]:
    found = {m.lower() for m in _SIDE_RE.findall(text or "")}
    if not found:
        return None
    if found & {"bilateral", "bilaterally", "both"} or {"left", "right"} <= found:
        return "bilateral"
    return "left" if "left" in found else "right"


_LEVEL_RE = re.compile(r"\b([CTLS]\d{1,2}(?:\s*[/-]\s*[CTLS]?\d{1,2})?|segment\s+(?:[1-8]|[ivx]{1,4})[ab]?"
                       r"|(?:upper|middle|lower)\s+lobe)\b", re.I)


def level_of(text: Optional[str]) -> Optional[str]:
    m = _LEVEL_RE.search(text or "")
    return re.sub(r"\s+", " ", m.group(1)).upper() if m else None


_NUM_RE = re.compile(r"(?<![A-WYZa-wyz\d.])(\d+(?:\.\d+)?)\s*(mm|cm|ml|hu|%)?(?![A-WYZa-wyz])", re.I)   # "x" allowed: 5x4 mm


def numbers(text: Optional[str]) -> Set[str]:
    """Numbers with their unit, cm normalised to mm ("1.4 cm" → "14mm"); vertebral-level digits are skipped."""
    out = set()
    for val, unit in _NUM_RE.findall(text or ""):
        v, u = float(val), (unit or "").lower()
        if u == "cm":
            v, u = v * 10, "mm"
        out.add(f"{round(v, 3):g}{u}")
    return out


_STOP = {"the", "and", "with", "are", "is", "of", "in", "at", "to", "an", "or", "seen", "noted", "there", "this",
         "that", "which", "also", "present", "identified", "demonstrated", "measures", "measuring", "measure",
         "appears", "appear", "within", "from", "for", "has", "have", "been", "was", "were", "its", "into", "on",
         "by", "as", "be", "no", "not", "any"}
ANATOMY = frozenset({
    "brain", "skull", "orbit", "sinus", "sinuses", "neck", "thyroid", "larynx", "pharynx", "trachea", "lung", "lungs",
    "lobe", "pleura", "pleural", "mediastinum", "mediastinal", "heart", "pericardium", "pericardial", "aorta",
    "aortic", "artery", "arteries", "vein", "veins", "liver", "hepatic", "gallbladder", "biliary", "bile", "duct",
    "cbd", "pancreas", "pancreatic", "spleen", "splenic", "kidney", "kidneys", "renal", "adrenal", "ureter",
    "bladder", "prostate", "uterus", "ovary", "ovaries", "bowel", "colon", "rectum", "stomach", "duodenum",
    "appendix", "peritoneum", "peritoneal", "lymph", "nodes", "node", "spine", "vertebra", "vertebral", "disc",
    "cord", "canal", "foramen", "rib", "ribs", "pelvis", "hip", "femur", "knee", "ankle", "foot", "shoulder",
    "elbow", "wrist", "hand", "carpal", "joint", "tendon", "ligament", "muscle", "bone", "breast", "axilla",
    "testis", "scrotum", "soft", "tissue", "tissues", "leg", "arm",
})


def words(text: Optional[str]) -> Set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP}


def score_pair(line: str, clause: str) -> Tuple[float, str]:
    a, b = line.lower().strip(" ."), clause.lower().strip(" .")
    if a == b:
        return 1.0, "exact"
    wa, wb = words(line), words(clause)
    lex = len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0
    num = bool(numbers(line) & numbers(clause))
    anat = bool(wa & wb & ANATOMY)
    score = min(1.0, lex + (0.3 if num else 0.0) + (0.2 if anat else 0.0))
    how = "lexical" if lex >= PAIR_FLOOR else ("number" if num else ("anatomy" if anat else "lexical"))
    return round(score, 3), how


# ── clauses and lines ────────────────────────────────────────────────────────

_NEG_LINE = re.compile(r"^\s*(no|nil|without|there is no|there are no)\b", re.I)
_SUBHEAD = re.compile(r"^[ \t]*(left|right)\b[^:\n]{0,40}:", re.I | re.M)


def report_clauses(report: str, sections: List[str]) -> List[ReportClause]:
    spans = section_spans(report, section_models(sections)) if sections else []
    if not spans:
        spans = [(ReportSection(name="Report", role="findings"), 0, len(report))]
    out: List[ReportClause] = []
    for sec, a, b in spans:
        if sec.role in _SKIP_ROLES:
            continue
        subs = [(m.start(), side_of(m.group(1))) for m in _SUBHEAD.finditer(report, a, b)]
        for s, i, j in _sentence_positions(report, a, b):
            sub = next((sd for p, sd in reversed(subs) if p <= i), None)
            for c, _ in clauses_in_context(s):
                out.append(ReportClause(id=f"r{len(out)}", text=c, section=sec.name, start=i, end=j, side=side_of(c),
                                        level=level_of(c), negative=bool(_NEG_LINE.match(c)), subheading_side=sub))
    return out


def _lines(texts: List[str], prefix: str, background: Set[int], all_background: bool = False) -> List[DictLine]:
    return [DictLine(id=f"{prefix}{i}", text=t, side=side_of(t), level=level_of(t), negative=bool(_NEG_LINE.match(t)),
                     background=all_background or i in background) for i, t in enumerate(texts)]


def align(report: str, dictation: str, history: str, sections: List[str],
          background: Optional[Set[int]] = None) -> Alignment:
    lines = _lines(dictated_items(dictation), "d", background or set())
    hist = _lines(rc.split_findings(history or ""), "h", set(), all_background=True)
    clauses = report_clauses(report, sections)
    pairs: List[Pair] = []
    for l in lines:
        for c in clauses:
            if l.level and c.level and l.level != c.level:
                continue                     # a different level never pairs
            sc, how = score_pair(l.text, c.text)
            if sc >= PAIR_FLOOR:
                pairs.append(Pair(line_id=l.id, clause_id=c.id, score=sc, how=how))
    pl, pc = {p.line_id for p in pairs}, {p.clause_id for p in pairs}
    return Alignment(lines=lines, clauses=clauses, pairs=pairs, history=hist,
                     unmatched_lines=[l.id for l in lines if l.id not in pl],
                     unmatched_clauses=[c.id for c in clauses if c.id not in pc])
