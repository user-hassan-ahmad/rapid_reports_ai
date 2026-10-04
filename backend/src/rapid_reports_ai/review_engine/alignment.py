"""Alignment: report clauses ↔ dictated lines (spec §5.2). Pure code. Many-to-many is kept for real merges
and splits, but each clause and each line keeps only its best match(es) within BEST_MARGIN; siblings (lines
and clauses whose levels or sides disagree) never pair. Jev is never asked to choose between overlapping spans."""
from __future__ import annotations

import re
from typing import List, Literal, Optional, Set, Tuple

from pydantic import BaseModel

from .. import report_reconcile as rc
from ..report_review import ReportSection, _sentence_positions, clauses_in_context, dictated_items, section_spans

PAIR_FLOOR = 0.34   # provisional: Gate B1 (≥ 95% of clauses correctly paired or correctly unmatched)
BEST_MARGIN = 0.15  # provisional: Gate B1 (a pair survives within this margin of its clause's and its line's best)

Side = Literal["left", "right", "bilateral"]


class DictLine(BaseModel):
    id: str
    text: str
    side: Optional[Side] = None
    level: Optional[str] = None          # the first of `levels` (kept for callers that read one level)
    levels: List[str] = []               # every canonical level in the line: "L4/5", "L5/S1", "T7", "RLL", "SEGMENT 7"
    negative: bool = False
    block_side: Optional[Side] = None    # side of a preceding header line ("MRI knee left"); `side` is the line's own
    block_levels: List[str] = []         # levels of a preceding line that opens with a level ("At L4/5 …"), when it has none
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
    block_levels: List[str] = []         # levels of an earlier sentence in the paragraph that opens with a level


class Pair(BaseModel):
    line_id: str
    clause_id: str
    score: float
    # level_conflict: the pair scores above the floor but its level sets are disjoint. Dictation is truth,
    # so it is kept (one "differs" item), but only when no clause in the report is at the line's own level.
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


_VERT_RE = re.compile(r"\b([CTLS])(\d{1,2})(?:\s*[/\-\u2010-\u2015\u2212]\s*([CTLS])?(\d{1,2}))?\b", re.I)  # any dash
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


_LEAD = re.compile(r"^[\W_]*(?:at\s+(?:the\s+)?|level\s+)?", re.I)


def leading_levels(text: Optional[str]) -> List[str]:
    """The text's levels when it opens with a vertebral level ("At L4–L5 there is …", "L5/S1: …"), else []."""
    t = text or ""
    rest = t[_LEAD.match(t).end():]
    m = next(iter(_vert_matches(rest)), None)
    return levels_of(t) if m is not None and m.start() == 0 else []


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
            "identified", "evidence", "present",
            # grade and normal-status words: frames shared by sibling findings
            "mildly", "severe", "large", "marked", "minimal", "significant", "intact", "clear", "patent", "preserved",
            "abnormal", "abnormality", "change", "changes", "finding", "findings", "otherwise", "likely",
            "suspicious", "remaining", "visualised", "visualized",
            # anatomy umbrella words: shared by many unrelated structures
            "joint", "artery", "tendon", "lesion", "cervical", "previous", "structure", "organ",
            "soft", "tissue", "tissues", "pulmonary", "lobe", "lobar", "segment", "segmental", "branch", "branches",
            "vessel", "vessels", "upper", "lower",
            }                                                          # count only beside a shared content word
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


# Light stemming, for matching only (texts are never altered): plural -s/-es/-ies (Latin -us/-i), then one suffix
# (-ation/-ated/-ed/-ing/-al/-ar/-ic), then -ular → -l, a trailing -at, and a final e/a/y. So dilated ~
# dilatation ~ dilation, lesion ~ lesions, viscera ~ visceral, ventricle ~ ventricular, aorta ~ aortic.
_SUFFIXES = ("ation", "ated", "ating", "ate", "ing", "ed", "al", "ar", "ic")
_NO_STEM = frozenset({"canal", "bleed", "bleeding"})


def stem(w: str) -> str:
    w = w.lower()
    if w in _NO_STEM:
        return w
    # British/American spellings: oedema ~ edema, haemorrhage ~ hemorrhage, artefact ~ artifact, -ise ~ -ize
    w = w.replace("ae", "e").replace("oe", "e").replace("artefact", "artifact").replace("iz", "is")
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "xes", "ches", "shes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    elif len(w) > 5 and w.endswith("us"):                              # Latin -us / -i: calculus ~ calculi
        w = w[:-2]
    elif len(w) > 5 and w.endswith("i"):
        w = w[:-1]
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3 and not (suf == "ed" and w.endswith("eed")):
            w = w[:-len(suf)]
            break
    if len(w) > 4 and w.endswith("ul"):
        w = w[:-2] + "l"
    if len(w) > 4 and w.endswith("at"):
        w = w[:-2]
    if len(w) > 3 and w[-1] in "eay":
        w = w[:-1]
    return w


# Matching-only stop words (words() keeps them for checks.py): function words and hedges that carry no finding.
_MATCH_STOP = frozenset({
    "all", "more", "most", "but", "due", "via", "show", "shows", "showing", "two", "three", "one", "multiple", "other",
    "further", "these", "those", "such", "may", "can", "could", "would", "will", "than", "then", "also", "each",
    "some", "few", "several", "very", "well", "however", "overall", "again", "including", "consistent", "keeping",
    "features", "suggest", "suggestive", "suggesting", "representing", "represent", "represents", "involving",
    "throughout", "grossly", "possible", "possibly", "probable", "probably", "predominantly", "reasonably",
    "likely", "without", "there", "here", "where", "what", "when", "only", "just", "now", "per", "since",
    "major",
})
# Expansions for matching: a finding word that names its structure ("lymphadenopathy" ~ "lymph nodes").
_EXPAND = {"lymphadenopathy": ("lymph", "node"), "adenopathy": ("lymph", "node"), "nodal": ("lymph", "node"),
           # common abbreviations ("ACL" ~ "anterior cruciate ligament")
           "acl": ("anterior", "cruciate"), "pcl": ("posterior", "cruciate"), "mcl": ("medial", "collateral"),
           "lcl": ("lateral", "collateral"), "cbd": ("common", "bile", "duct"), "ivc": ("inferior", "vena", "cava"),
           "svc": ("superior", "vena", "cava"), "sfa": ("superficial", "femoral"), "cfa": ("common", "femoral"),
           "ica": ("internal", "carotid"), "cca": ("common", "carotid"), "sma": ("superior", "mesenteric")}


def stems(text: Optional[str]) -> Set[str]:
    """Stemmed content words of `words(text)` (generic words included), for matching only."""
    out: Set[str] = set()
    for w in words(text):
        if w in _MATCH_STOP:
            continue
        out.add(stem(w))
        out |= {stem(x) for x in _EXPAND.get(w, ())}
    return out


_GENERIC_STEMS = frozenset(stem(w) for w in _GENERIC)
_ANATOMY_STEMS = frozenset(stem(w) for w in ANATOMY)


def core_stems(text: Optional[str]) -> Set[str]:
    """Stems that can carry a pair: content stems without the generic ones."""
    out: Set[str] = set()
    for w in words(text):
        if w in _GENERIC or w in _MATCH_STOP:
            continue
        out.add(stem(w))
        out |= {stem(x) for x in _EXPAND.get(w, ())}
    return out - _GENERIC_STEMS


_UNSET = object()
SIDE_MATCH, SIDE_CLASH = 0.1, 0.4


def _pair_gate(line: str, clause: str, shared_level: bool = False) -> bool:
    """A pair needs ≥ 2 shared core stems, or 1 plus a shared number or level, or 1 that is the whole core
    of one side ("Liver normal" ~ "The liver is normal in size")."""
    ca, cb = core_stems(line), core_stems(clause)
    shared = ca & cb
    if len(shared) >= 2:
        return True
    if len(shared) == 1:
        return bool(shared_level or (numbers(line) & numbers(clause)) or min(len(ca), len(cb)) == 1)
    return False


def _raw_score(line: str, clause: str, line_side, clause_side, shared_level: bool = False) -> Tuple[float, str]:
    """Uncapped score used for ranking (0 when the pair gate fails)."""
    a, b = line.lower().strip(" ."), clause.lower().strip(" .")
    if a == b:
        return 1.5, "exact"
    if not _pair_gate(line, clause, shared_level):
        return 0.0, "lexical"
    wa, wb = stems(line), stems(clause)
    shared = wa & wb
    lex = len(shared) / min(len(wa), len(wb))
    jac = len(shared) / len(wa | wb)
    num = bool(numbers(line) & numbers(clause))
    anat = bool(shared & _ANATOMY_STEMS)
    score = lex + 0.2 * jac + (0.3 if num else 0.0) + (0.2 if anat else 0.0)
    sa = side_of(line) if line_side is _UNSET else line_side
    sb = side_of(clause) if clause_side is _UNSET else clause_side
    if sa and sb and "bilateral" not in (sa, sb):
        score = score + SIDE_MATCH if sa == sb else score - SIDE_CLASH
    how = "lexical" if lex >= PAIR_FLOOR else ("number" if num else ("anatomy" if anat else "lexical"))
    return max(0.0, score), how


def score_pair(line: str, clause: str, line_side=_UNSET, clause_side=_UNSET) -> Tuple[float, str]:
    """Stemmed lexical overlap + shared number + shared anatomy, then side: a small bonus when the sides agree,
    a penalty when left meets right. 0 unless the pair gate passes (see _pair_gate). Sides default to side_of()
    of each text; align() passes the clause's subheading side when the clause has none."""
    raw, how = _raw_score(line, clause, line_side, clause_side)
    return round(min(1.0, raw), 3), how


# ── clauses and lines ────────────────────────────────────────────────────────

_NEG_LINE = re.compile(r"^\s*(?:(?:left|right|bilateral|both|rt|lt)\s+)?(no|nil|without|there is no|there are no)\b"
                       r"|\b(?:not\s+(?:seen|identified|demonstrated|visuali[sz]ed|present|detected)|absent|"
                       r"unremarkable)\b", re.I)
_NORMAL_WORD = re.compile(r"\b(?:normal|unremarkable|intact|clear|patent|preserved|satisfactory)\b", re.I)
_LINE_RE = re.compile(r"[^\n]+")
_HEADING = re.compile(r"^([^:.\n\d]{1,40}):(?:\s+|$)")                 # "Left knee:" / "Both knees: text"
_MARKER = re.compile(r"^(?:\d{1,2}[.)]|[-*•])\s+")
_SENT_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z0-9])")
_NEG_LIST = re.compile(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", re.I)
_ITEM_SPLIT = re.compile(r",\s*(?:or\s+|and\s+)?|\s+(?:or|and)\s+")
_ADJ_ONLY = re.compile(r"^[a-z]+(?:ic|al|ar|ous|ive|ary)$|-$", re.I)   # "pericolic or paracolic …", "intra- or …"
_PREP = re.compile(r"\b(?:in|of|at|within|on|to|from|around)\b", re.I)
_PREDICATE = re.compile(r"\s+(?:is|are|was|were)\s+(?:seen|identified|noted|demonstrated|present|detected)\b.*$", re.I)
_PART_WORDS = frozenset({"body", "process", "wall", "base", "margin", "head", "shaft", "arch", "plate"})
# Signature / sign-off lines (not clauses); mirrors checks._SIGNATURE plus a bare registration line.
_SIGNATURE = re.compile(r"\b(?:GMC|NMC|HCPC|registration|reg\.?\s*(?:no|number))\b\.?\s*(?:no\.?|number|#|:)?\s*\d|"
                        r"\b(?:reported|dictated|verified|authori[sz]ed|signed)\s+by\b", re.I)
_HEADER_WORDS = frozenset({"mri", "mr", "ct", "us", "ultrasound", "xray", "x-ray", "radiograph", "radiographs", "scan",
                           "study", "of", "the", "side", "lower", "upper", "rt", "lt", "left", "right", "bilateral",
                           "both"})
_BODY_WORDS = frozenset({"limb", "limbs", "extremity", "knees", "legs", "arms", "hips", "shoulders", "feet", "hands",
                         "thigh", "calf", "forearm"})


def _is_negative(t: str) -> bool:
    return bool(_NEG_LINE.search(t))


def _is_normalish(t: str) -> bool:
    return _is_negative(t) or bool(_NORMAL_WORD.search(t))


def side_header(text: Optional[str]) -> Optional[Side]:
    """The side of a short header line without a colon that names only a side and a body part ("MRI knee left",
    "Right leg", "LEFT KNEE"); None for anything else (a finding line, a heading with a colon)."""
    t = (text or "").strip().rstrip(".")
    if not t or ":" in t:
        return None
    ws = [w.lower() for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)?", t)]
    if not 2 <= len(ws) <= 5 or re.search(r"\d", t):
        return None
    side = side_of(t)
    body = [w for w in ws if w in _BODY_WORDS or w in ANATOMY or stem(w) in _ANATOMY_STEMS]
    if side is None or not body:
        return None
    return side if all(w in _HEADER_WORDS or w in body for w in ws) else None


def _heading_only(text: str) -> bool:
    """A heading alone on its line ("Conclusion:", "Left knee:")."""
    h = _HEADING.match(text.strip())
    return bool(h) and not text.strip()[h.end():].strip()


def _negative_items(s: str) -> List[str]:
    """A negative list split into one item per finding, on commas and on 'or'/'and'. A bare adjective or
    prefix before 'or'/'and' joins the next item ('No pericolic or paracolic fluid collection' stays one),
    and an 'and'/'or' after a preposition never splits ('No fluid in the liver and spleen' stays one).
    The last item's head noun is carried to an earlier item that is a modifier ('No rib, hip or pelvic
    fractures' → 'No rib fractures'; 'No suspicious calvarial or skull base lesion' → 'No suspicious
    calvarial lesion'): an earlier item ending in an adjective, or, for a plural head, in a body part."""
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
    if len(items) <= 1:
        return [s]
    last = _PREDICATE.sub("", items[-1]).split()
    if len(last) >= 2:
        head = last[-1]
        plural = head.lower().endswith("s") and not head.lower().endswith(("ss", "us", "is"))
        for k, it in enumerate(items[:-1]):
            tail = it.split()[-1].lower()
            if " " in it and (" or " in it or " and " in it):
                continue
            if _ADJ_ONLY.match(tail) or (plural and (tail in _PART_WORDS or tail in ANATOMY
                                                      or stem(tail) in _ANATOMY_STEMS)):
                items[k] = f"{it} {head}"
    return [f"No {i}" for i in items]


def _role(section: str) -> str:
    low = section.lower()
    return next((r for w, r in _ROLE_WORDS if w in low), "findings")


def report_clauses(report: str, sections: List[str]) -> List[ReportClause]:
    """Each section is read line by line. A short heading ending in ':' (alone on its line or inline before
    text) sets subheading_side = side_of(heading), so 'Both knees:' gives bilateral and 'Other findings:'
    resets it to None; the heading is not clause text. A header line without a colon naming a side and a
    body part ('MRI knee left', 'RIGHT KNEE') does the same and is not a clause; sides reset at each section.
    Signature lines are skipped. List markers ('1.', '2)') are dropped. Each line is split into sentences
    (also before a sentence starting with a digit), and a negative list into one clause per item."""
    spans = section_spans(report, section_models(sections)) if sections else []
    if not spans:
        spans = [(ReportSection(name="Report", role="findings"), 0, len(report))]
    out: List[ReportClause] = []
    for sec, a, b in spans:
        if sec.role in _SKIP_ROLES:
            continue
        sub: Optional[Side] = None
        block: List[str] = []
        prev_end = a
        for lm in _LINE_RE.finditer(report, a, b):
            if report[prev_end:lm.start()].count("\n") > 1:
                block = []                         # a blank line ends a level block
            prev_end = lm.end()
            i, line = lm.start(), lm.group(0)
            lead = len(line) - len(line.lstrip())
            i, line = i + lead, line.strip()
            if _SIGNATURE.search(line):
                continue
            hs = side_header(line)
            if hs:
                sub, block = hs, []
                continue
            h = _HEADING.match(line)
            if h and len(h.group(1).split()) <= 5:
                sub, block = side_of(h.group(1)), []
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
                if levels_of(s):
                    block = leading_levels(s)
                for c in _negative_items(s):
                    k = s.find(c)
                    cs, ce = (si + k, si + k + len(c)) if k >= 0 else (si, si + len(s))
                    lv = levels_of(c)
                    out.append(ReportClause(id=f"r{len(out)}", text=c, section=sec.name, start=cs, end=ce,
                                            sentence_start=si, sentence_end=si + len(s), side=side_of(c),
                                            level=lv[0] if lv else None, levels=lv, negative=_is_negative(c),
                                            subheading_side=sub, block_levels=[] if lv else list(block)))
    return out


def _lines(texts: List[str], prefix: str, background: Set[int], all_background: bool = False) -> List[DictLine]:
    """One DictLine per item, id by the item's index (so `background` indices stay valid). A heading alone
    ("Conclusion:") or a side header ("MRI knee left") is not a line: it sets block_side for the lines after it.
    A line opening with a level ("At L4/5 …") gives its levels as block_levels to the level-less lines after it,
    until the next line with levels or heading."""
    out, block, lblock = [], None, []
    for i, t in enumerate(texts):
        hs = side_header(t)
        if hs or _heading_only(t):
            block = hs if hs else side_of(_HEADING.match(t.strip()).group(1))
            lblock = []
            continue
        lv = levels_of(t)
        if lv:
            lblock = leading_levels(t)
        out.append(DictLine(id=f"{prefix}{i}", text=t, side=side_of(t), level=lv[0] if lv else None, levels=lv,
                            negative=_is_negative(t), block_side=block, block_levels=[] if lv else list(lblock),
                            background=all_background or i in background))
    return out


# Grouped normal summaries: a normal/negative clause naming a group carries the dictated normal lines whose
# structure belongs to it. Empty members = any otherwise-unpaired normal line ("visualised structures").
GROUP_TERMS = {                                                        # provisional: Gate B1
    "solid organs": ("liver", "spleen", "pancreas", "kidneys", "adrenals"),
    "abdominal viscera": ("liver", "spleen", "pancreas", "kidneys", "adrenals", "gallbladder", "bowel", "stomach"),
    "viscera": ("liver", "spleen", "pancreas", "kidneys", "adrenals", "gallbladder", "bowel", "stomach", "bladder"),
    "pelvic viscera": ("bladder", "uterus", "ovaries", "prostate", "seminal vesicles", "rectum"),
    "pelvic organs": ("bladder", "uterus", "ovaries", "prostate", "seminal vesicles", "rectum"),
    "bowel": ("small bowel", "large bowel", "colon", "stomach", "duodenum", "rectum", "caecum", "appendix"),
    "ligaments": ("cruciate", "collateral", "acl", "pcl", "mcl", "lcl"),
    "menisci": ("meniscus",),
    "rotator cuff": ("supraspinatus", "infraspinatus", "subscapularis", "teres minor"),
    "great vessels": ("aorta", "pulmonary artery", "vena cava", "svc", "ivc"),
    "visualised structures": (),
    "remaining structures": (),
}
_GROUPS = [(frozenset(stem(w) for w in k.split()),
            [frozenset(stem(w) for w in m.split()) for m in v] + ([frozenset(stem(w) for w in k.split())] if v else []))
           for k, v in GROUP_TERMS.items()]                                 # a line naming the group itself is a member


def _group_members(clause: str):
    """The member stem sets of every group the clause names, or None when it names none. [] = any."""
    cs = {stem(w) for w in re.findall(r"[a-z]{3,}", clause.lower())}
    found = [members for key, members in _GROUPS if key <= cs]
    if not found:
        return None
    return [] if any(not m for m in found) else [m for ms in found for m in ms]


def _sides_clash(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b and "bilateral" not in (a, b) and a != b)


def align(report: str, dictation: str, history: str, sections: List[str],
          background: Optional[Set[int]] = None) -> Alignment:
    lines = _lines(dictated_items(dictation), "d", background or set())
    hist = _lines(rc.split_findings(history or ""), "h", set(), all_background=True)
    clauses = report_clauses(report, sections)
    role = {c.id: _role(c.section) for c in clauses}
    cands: List[Tuple[Pair, bool]] = []            # (pair, protected)
    conflicts: List[Pair] = []
    clv = {c.id: c.levels or c.block_levels for c in clauses}            # own levels, else the block's
    for l in lines:
        ls = l.side or l.block_side
        llv = l.levels or l.block_levels
        lkeys = _level_keys(llv)
        own_level_exists = bool(lkeys) and any(lkeys & _level_keys(clv[c.id]) for c in clauses)
        mine: List[Pair] = []
        for c in clauses:
            cs = c.side or c.subheading_side
            if _sides_clash(ls, cs):
                continue                           # left/right siblings never pair
            shared_level = bool(lkeys & _level_keys(clv[c.id]))
            raw, how = _raw_score(l.text, c.text, ls, cs, shared_level)
            if raw < PAIR_FLOOR:
                continue
            p = Pair(line_id=l.id, clause_id=c.id, score=raw, how=how)
            if levels_disjoint(llv, clv[c.id]):
                if not own_level_exists and l.levels and c.levels:
                    mine.append(p.model_copy(update={"how": "level_conflict"}))
                continue                           # level siblings never pair; inherited levels never conflict
            protected = (how == "exact" or (bool(llv) and set(llv) == set(clv[c.id]))
                         or bool(numbers(l.text) & numbers(c.text)))
            cands.append((p, protected))
        if mine:                                   # dictation is truth: the report put it at another level
            top = max(p.score for p in mine)
            conflicts.extend(p for p in mine if p.score >= top - BEST_MARGIN)
    best_c: dict = {}
    best_l: dict = {}
    for p, _ in cands:
        best_c[p.clause_id] = max(best_c.get(p.clause_id, 0.0), p.score)
        k = (p.line_id, role[p.clause_id])
        best_l[k] = max(best_l.get(k, 0.0), p.score)
    # a pair survives when it is near-best for its clause or for its line (in that section role): real merges
    # and splits keep every member, a sibling that is near-best for neither end is dropped
    pairs = [p for p, prot in cands if prot or p.score >= best_c[p.clause_id] - BEST_MARGIN
             or p.score >= best_l[(p.line_id, role[p.clause_id])] - BEST_MARGIN]
    pairs.extend(conflicts)
    # grouped normal summaries carry normal lines with no pair of their own in that section role
    own = {(p.line_id, role[p.clause_id]) for p in pairs}
    for c in clauses:
        if not _is_normalish(c.text):
            continue
        members = _group_members(c.text)
        if members is None:
            continue
        cs = c.side or c.subheading_side
        for l in lines:
            if not _is_normalish(l.text) or _sides_clash(l.side or l.block_side, cs):
                continue
            if (l.id, role[c.id]) in own:
                continue
            lst = stems(l.text)
            if members and not any(m <= lst for m in members):
                continue
            pairs.append(Pair(line_id=l.id, clause_id=c.id, score=0.5, how="anatomy"))
    pairs = [p.model_copy(update={"score": round(min(1.0, p.score), 3)}) for p in pairs]
    pl, pc = {p.line_id for p in pairs}, {p.clause_id for p in pairs}
    return Alignment(lines=lines, clauses=clauses, pairs=pairs, history=hist,
                     unmatched_lines=[l.id for l in lines if l.id not in pl],
                     unmatched_clauses=[c.id for c in clauses if c.id not in pc])
