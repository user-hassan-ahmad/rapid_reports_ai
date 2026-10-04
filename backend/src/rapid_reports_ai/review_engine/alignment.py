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
    level: Optional[str] = None          # the first of `levels` (kept for callers that read one level)
    levels: List[str] = []               # every canonical level in the line: "L4/5", "L5/S1", "T7", "RLL", "SEGMENT 7"
    negative: bool = False
    background: bool = False             # the omission selector says not reportable (L-49), or a history line


class ReportClause(BaseModel):
    """One report clause. `text` is usually verbatim report text, but an item split out of a negative list
    is synthetic ("No free fluid, lymphadenopathy" → "No lymphadenopathy"). `start`/`end` are the clause's
    own span when its text occurs verbatim in its sentence, else the sentence's span; `sentence_start`/
    `sentence_end` always hold the sentence's span. `side` comes from the clause's own words only; a
    subheading's side ("Left knee:") is `subheading_side`."""
    id: str
    text: str
    section: str
    start: int
    end: int
    sentence_start: int = 0
    sentence_end: int = 0
    side: Optional[Side] = None
    level: Optional[str] = None
    levels: List[str] = []
    negative: bool = False
    subheading_side: Optional[Side] = None


class Pair(BaseModel):
    line_id: str
    clause_id: str
    score: float
    # level_conflict: the pair scores above the floor but its level sets are disjoint. Dictation is truth,
    # so it is kept (one "differs" item), unless the line already pairs with a clause at its own level.
    how: Literal["exact", "lexical", "number", "anatomy", "level_conflict"]


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


_SIDE_RE = re.compile(r"\b(left|right|bilateral(?:ly)?|both|rt|lt)\b", re.I)
_LOBE_CODE_RE = re.compile(r"\b([RL])([UML])L\b")                      # RUL RML RLL LUL LLL (upper case only)
_RL_RE = re.compile(r"(?<![\w/-])([RL])\.?\s+([A-Za-z]+)")             # "R adrenal", "L kidney"
_NOT_BOTH = re.compile(r"\s+(?:in|are|is|was|were|of|normal|appear|appears|show|shows|measure|measures|have|has|"
                       r"unremarkable|within|demonstrate|being|been|and|with)\b", re.I)
_NOT_LEFT_BEFORE = re.compile(r"\b(?:been|was|were|is|are|be|remains?)\s+$", re.I)
_NOT_LEFT_AFTER = re.compile(r"\s+in\s+(?:situ|place)\b", re.I)


def side_of(text: Optional[str]) -> Optional[Side]:
    """left / right / bilateral from side words, rt/lt, a standalone R/L before an anatomy word, and lung
    lobe codes. 'both in size' and 'left in situ' are not sides."""
    t = text or ""
    found: Set[str] = set()
    for m in _SIDE_RE.finditer(t):
        w = m.group(1).lower()
        if w == "both" and (_NOT_BOTH.match(t, m.end()) or m.end() >= len(t.rstrip(" .;,"))):
            continue
        if w == "left" and (_NOT_LEFT_AFTER.match(t, m.end()) or _NOT_LEFT_BEFORE.search(t[:m.start()])):
            continue
        found.add({"rt": "right", "lt": "left", "bilaterally": "bilateral", "both": "bilateral"}.get(w, w))
    for m in _LOBE_CODE_RE.finditer(t):
        found.add("right" if m.group(1) == "R" else "left")
    for m in _RL_RE.finditer(t):
        if m.group(2).lower() in ANATOMY:
            found.add("right" if m.group(1) == "R" else "left")
    if not found:
        return None
    if "bilateral" in found or {"left", "right"} <= found:
        return "bilateral"
    return "left" if "left" in found else "right"


_VERT_RE = re.compile(r"\b([CTLS])(\d{1,2})(?:\s*[/-]\s*([CTLS])?(\d{1,2}))?\b", re.I)
_SEGMENT_RE = re.compile(r"\bsegment\s+([1-8]|[ivx]{1,4})([ab]?)\b", re.I)
_LOBE_RE = re.compile(r"\b(?:(right|left)\s+)?(upper|middle|lower)\s+lobes?\b", re.I)
_SEQ_WORDS = ("weighted", "weighting", "hyperintens", "hypointens", "isointens", "signal", "sequence",
              "flair", "stir", "dwi", "contrast")
_TNM_AFTER = re.compile(r"\s*N[0-3xX]\b")
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}


def _near_sequence_word(t: str, i: int, j: int) -> bool:
    before = re.findall(r"[A-Za-z]+", t[:i])[-3:]
    after = re.findall(r"[A-Za-z]+", t[j:])[:3]
    return any(w.lower().startswith(_SEQ_WORDS) for w in before + after)


def _vert_matches(t: str):
    """Vertebral-level matches, without MRI sequences (T1/T2 near a signal word) or TNM T stages."""
    for m in _VERT_RE.finditer(t):
        letter = m.group(1).upper()
        if letter == "T" and (_TNM_AFTER.match(t, m.end()) or re.search(r"\bN[0-3xX]\s*$", t[:m.start()])):
            continue
        if letter == "T" and m.group(2) in ("1", "2") and _near_sequence_word(t, m.start(), m.end()):
            continue
        yield m


def levels_of(text: Optional[str]) -> List[str]:
    """Every level in the text, canonical and in order of first appearance: L4-5 / L4-L5 / L4/L5 → "L4/5",
    L5-S1 → "L5/S1", "T7", liver "SEGMENT 7", lung lobes "RLL" (or "LOWER LOBE" without a side)."""
    t = text or ""
    found: List[Tuple[int, str]] = []
    for m in _vert_matches(t):
        a, n1, b, n2 = m.group(1).upper(), m.group(2), (m.group(3) or "").upper(), m.group(4)
        lv = f"{a}{n1}" if n2 is None else (f"{a}{n1}/{n2}" if b in ("", a) else f"{a}{n1}/{b}{n2}")
        found.append((m.start(), lv))
    for m in _SEGMENT_RE.finditer(t):
        n = m.group(1).lower()
        found.append((m.start(), f"SEGMENT {_ROMAN.get(n, n)}{m.group(2).upper()}"))
    for m in _LOBE_RE.finditer(t):
        side, pos = m.group(1), m.group(2).upper()
        found.append((m.start(), f"{side[0].upper()}{pos[0]}L" if side else f"{pos} LOBE"))
    for m in _LOBE_CODE_RE.finditer(t):
        found.append((m.start(), m.group(0)))
    out: List[str] = []
    for _, lv in sorted(found):
        if lv not in out:
            out.append(lv)
    return out


def level_of(text: Optional[str]) -> Optional[str]:
    lv = levels_of(text)
    return lv[0] if lv else None


_LOBE_NAME = {"U": "UPPER LOBE", "M": "MIDDLE LOBE", "L": "LOWER LOBE"}


def _level_keys(levels: List[str]) -> Set[str]:
    """Comparison keys: a lobe code also matches the side-less lobe name ("RLL" ~ "LOWER LOBE")."""
    keys = set(levels)
    keys |= {_LOBE_NAME[lv[1]] for lv in levels if re.fullmatch(r"[RL][UML]L", lv)}
    return keys


def levels_disjoint(a: List[str], b: List[str]) -> bool:
    """True only when both sides name levels and no level is shared."""
    return bool(a) and bool(b) and not (_level_keys(a) & _level_keys(b))


_NUM_RE = re.compile(r"(?<![A-WYZa-wyz\d.])(\d+(?:\.\d+)?)\s*(mm|cm|ml|hu|%)?(?![A-WYZa-wyz])", re.I)
_DIM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?:\s*(?:mm|cm))?(?:\s*[x×]\s*\d+(?:\.\d+)?(?:\s*(?:mm|cm))?)+\b", re.I)
_DIM_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|cm)?", re.I)
_DATE_RE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}-\d{1,2}-\d{1,2}\b")


def _num(v: float, u: str) -> str:
    if u == "cm":
        v, u = v * 10, "mm"
    return f"{round(v, 3):g}{u}"


def numbers(text: Optional[str]) -> Set[str]:
    """Numbers with their unit, cm normalised to mm ("1.4 cm" → "14mm"). A trailing unit carries back across
    "x" ("5 x 4 cm" → 50mm, 40mm). Level tokens (L4/5, segment 7) and dates give no numbers."""
    t = _DATE_RE.sub(" ", text or "")
    for m in sorted(list(_vert_matches(t)) + list(_SEGMENT_RE.finditer(t)), key=lambda m: -m.start()):
        t = t[:m.start()] + " " + t[m.end():]
    out = set()
    for m in _DIM_RE.finditer(t):
        parts = _DIM_PART.findall(m.group(0))
        tail = (parts[-1][1] or "").lower()
        out |= {_num(float(v), (u or tail).lower()) for v, u in parts}
    for val, unit in _NUM_RE.findall(_DIM_RE.sub(" ", t)):
        out.add(_num(float(val), (unit or "").lower()))
    return out


_STOP = {"the", "and", "with", "are", "is", "of", "in", "at", "to", "an", "or", "seen", "noted", "there", "this",
         "that", "which", "also", "present", "identified", "demonstrated", "measures", "measuring", "measure",
         "appears", "appear", "within", "from", "for", "has", "have", "been", "was", "were", "its", "into", "on",
         "by", "as", "be", "no", "not", "any",
         "left", "right", "bilateral", "bilaterally", "both"}          # side is scored separately
_GENERIC = {"normal", "normally", "unremarkable", "small", "mild", "moderate", "size", "appearance", "seen", "noted",
            "identified", "evidence", "present"}                       # count only beside a shared content word
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
    """Content words (3+ letters), without stop words or side words; generic words stay (see score_pair)."""
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP or w in _GENERIC}


_UNSET = object()
SIDE_MATCH, SIDE_CLASH = 0.1, 0.4


def score_pair(line: str, clause: str, line_side=_UNSET, clause_side=_UNSET) -> Tuple[float, str]:
    """Lexical overlap (counted only when a non-generic content word is shared) + shared number + shared
    anatomy, then side: a small bonus when the sides agree, a penalty when left meets right. Sides default
    to side_of() of each text; align() passes the clause's subheading side when the clause has none."""
    a, b = line.lower().strip(" ."), clause.lower().strip(" .")
    if a == b:
        return 1.0, "exact"
    wa, wb = words(line), words(clause)
    shared = wa & wb
    lex = len(shared) / min(len(wa), len(wb)) if (shared - _GENERIC) else 0.0
    num = bool(numbers(line) & numbers(clause))
    anat = bool(shared & ANATOMY)
    score = min(1.0, lex + (0.3 if num else 0.0) + (0.2 if anat else 0.0))
    if score > 0:
        sa = side_of(line) if line_side is _UNSET else line_side
        sb = side_of(clause) if clause_side is _UNSET else clause_side
        if sa and sb and "bilateral" not in (sa, sb):
            score = score + SIDE_MATCH if sa == sb else score - SIDE_CLASH
        score = max(0.0, min(1.0, score))
    how = "lexical" if lex >= PAIR_FLOOR else ("number" if num else ("anatomy" if anat else "lexical"))
    return round(score, 3), how


# ── clauses and lines ────────────────────────────────────────────────────────

_NEG_LINE = re.compile(r"^\s*(?:(?:left|right|bilateral|both|rt|lt)\s+)?(no|nil|without|there is no|there are no)\b"
                       r"|\b(?:not\s+(?:seen|identified|demonstrated|visuali[sz]ed|present|detected)|absent|"
                       r"unremarkable)\b", re.I)
_LINE_RE = re.compile(r"[^\n]+")
_HEADING = re.compile(r"^([^:.\n\d]{1,40}):(?:\s+|$)")                 # "Left knee:" / "Both knees: text"
_MARKER = re.compile(r"^(?:\d{1,2}[.)]|[-*•])\s+")
_SENT_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z0-9])")
_NEG_LIST = re.compile(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", re.I)
_ITEM_SPLIT = re.compile(r",\s*(?:or\s+|and\s+)?|\s+(?:or|and)\s+")
_ADJ_ONLY = re.compile(r"^[a-z]+(?:ic|al|ar|ous|ive|ary)$|-$", re.I)   # "pericolic or paracolic …", "intra- or …"
_PREP = re.compile(r"\b(?:in|of|at|within|on|to|from|around)\b", re.I)


def _is_negative(t: str) -> bool:
    return bool(_NEG_LINE.search(t))


def _negative_items(s: str) -> List[str]:
    """A negative list split into one item per finding, on commas and on 'or'/'and'. A bare adjective or
    prefix before 'or'/'and' joins the next item ('No pericolic or paracolic fluid collection' stays one),
    and an 'and'/'or' after a preposition never splits ('No fluid in the liver and spleen' stays one)."""
    m = _NEG_LIST.match(s)
    if not m:
        return [s]
    body, items, cur, pos = m.group(2), [], "", 0
    for sep in _ITEM_SPLIT.finditer(body):
        piece = body[pos:sep.start()]
        cur = f"{cur}{piece}"
        is_comma = sep.group(0).lstrip().startswith(",")
        single = " " not in cur.strip()
        if not is_comma and ((single and _ADJ_ONLY.match(cur.strip())) or _PREP.search(cur)):
            cur += sep.group(0)
        else:
            items.append(cur.strip())
            cur = ""
        pos = sep.end()
    items.append(f"{cur}{body[pos:]}".strip())
    items = [i for i in items if i]
    return [f"No {i}" for i in items] if len(items) > 1 else [s]


def report_clauses(report: str, sections: List[str]) -> List[ReportClause]:
    """Each section is read line by line. A short heading ending in ':' (alone on its line or inline before
    text) sets subheading_side = side_of(heading), so 'Both knees:' gives bilateral and 'Other findings:'
    resets it to None; the heading is not clause text. List markers ('1.', '2)') are dropped. Each line is
    split into sentences (also before a sentence starting with a digit), and a negative list into one
    clause per item."""
    spans = section_spans(report, section_models(sections)) if sections else []
    if not spans:
        spans = [(ReportSection(name="Report", role="findings"), 0, len(report))]
    out: List[ReportClause] = []
    for sec, a, b in spans:
        if sec.role in _SKIP_ROLES:
            continue
        sub: Optional[Side] = None
        for lm in _LINE_RE.finditer(report, a, b):
            i, line = lm.start(), lm.group(0)
            lead = len(line) - len(line.lstrip())
            i, line = i + lead, line.strip()
            h = _HEADING.match(line)
            if h and len(h.group(1).split()) <= 5:
                sub = side_of(h.group(1))
                i, line = i + h.end(), line[h.end():]
            mk = _MARKER.match(line)
            if mk:
                i, line = i + mk.end(), line[mk.end():]
            pos = 0
            bounds = [m.start() for m in _SENT_SPLIT.finditer(line)] + [len(line)]
            for end in bounds:
                raw = line[pos:end]
                s = raw.strip()
                si = i + pos + (len(raw) - len(raw.lstrip()))
                pos = end
                if len(s) <= 3:
                    continue
                for c in _negative_items(s):
                    k = s.find(c)
                    cs, ce = (si + k, si + k + len(c)) if k >= 0 else (si, si + len(s))
                    lv = levels_of(c)
                    out.append(ReportClause(id=f"r{len(out)}", text=c, section=sec.name, start=cs, end=ce,
                                            sentence_start=si, sentence_end=si + len(s), side=side_of(c),
                                            level=lv[0] if lv else None, levels=lv, negative=_is_negative(c),
                                            subheading_side=sub))
    return out


def _lines(texts: List[str], prefix: str, background: Set[int], all_background: bool = False) -> List[DictLine]:
    out = []
    for i, t in enumerate(texts):
        lv = levels_of(t)
        out.append(DictLine(id=f"{prefix}{i}", text=t, side=side_of(t), level=lv[0] if lv else None, levels=lv,
                            negative=_is_negative(t), background=all_background or i in background))
    return out


def align(report: str, dictation: str, history: str, sections: List[str],
          background: Optional[Set[int]] = None) -> Alignment:
    lines = _lines(dictated_items(dictation), "d", background or set())
    hist = _lines(rc.split_findings(history or ""), "h", set(), all_background=True)
    clauses = report_clauses(report, sections)
    pairs: List[Pair] = []
    for l in lines:
        ok: List[Pair] = []
        conflicts: List[Pair] = []
        for c in clauses:
            sc, how = score_pair(l.text, c.text, l.side, c.side or c.subheading_side)
            if sc < PAIR_FLOOR:
                continue
            if levels_disjoint(l.levels, c.levels):
                conflicts.append(Pair(line_id=l.id, clause_id=c.id, score=sc, how="level_conflict"))
            else:
                ok.append(Pair(line_id=l.id, clause_id=c.id, score=sc, how=how))
        pairs.extend(ok)
        own_level = any(_level_keys(l.levels) & _level_keys(next(c for c in clauses if c.id == p.clause_id).levels)
                        for p in ok)
        if not own_level:
            pairs.extend(conflicts)      # dictation is truth: the report put this finding at another level
    pl, pc = {p.line_id for p in pairs}, {p.clause_id for p in pairs}
    return Alignment(lines=lines, clauses=clauses, pairs=pairs, history=hist,
                     unmatched_lines=[l.id for l in lines if l.id not in pl],
                     unmatched_clauses=[c.id for c in clauses if c.id not in pc])
