"""Deterministic checks (spec §6.2 laterality and level, §6.3 accuracy). Every lexicon here is provisional until
Gate B1 measures it on the 41 audit-comparison reports; a missed phrasing is a recall gap, never a false fix,
because every hit still goes to the adjudicator.

Certainty and severity are NOT checked here: they are owned by the Jev C1n question in the Accuracy lane (Task 6;
decision 2026-10-04, certainty lab: Jev 12/14 real upgrades at 2% false alarms against this module's old 6/14).
`hedge_tag` stays as a helper the engine uses to render evidence."""
from __future__ import annotations

import re
from typing import List, Literal, Optional, Set, Tuple

from .alignment import ANATOMY, Alignment, Pair, ReportClause, numbers, side_of, words
from .items import Candidate, Span

# ── hedges (evidence rendering only) ─────────────────────────────────────────
# Ladder: possible < probable < definite; negated sits outside it. UK convention: "in keeping with" and
# "consistent with" are PROBABLE.
HEDGE_NOT_EXCLUDED = (r"can ?not (?:be )?(?:excluded|ruled out)", r"can ?not exclude", r"can['’]t exclude",
                      r"can['’]t be (?:excluded|ruled out)", r"not (?:be )?excluded",
                      r"not (?:be )?ruled out")                                        # provisional: Gate B1
HEDGE_NEGATED_LEAD = ("no", "nil", "without", "there is no", "there are no")           # provisional: Gate B1
HEDGE_NEGATED_ANY = ("not seen", "absent", "negative for", "nothing to suggest")       # provisional: Gate B1
HEDGE_POSSIBLE = ("may", "might", "possible", "possibly", "could", "query", "questionable")  # provisional: Gate B1
HEDGE_PROBABLE = ("likely", "probable", "probably", "suggestive of", "suggest", "suggests", "suspicious for",
                  "favoured", "favored", "in keeping with", "consistent with", "compatible with",
                  "presumed")                                                          # provisional: Gate B1
# Definite is the fallback (a bare finding, "is", "are", "diagnostic of"); listed for the record, never matched.
HEDGE_DEFINITE = ("is", "are", "diagnostic of")                                        # provisional: Gate B1


def _alt(words_: tuple) -> str:
    return "|".join(sorted(words_, key=len, reverse=True))


_NOT_EXCLUDED = re.compile(rf"\b(?:{_alt(HEDGE_NOT_EXCLUDED)})\b", re.I)
_NEGATED = re.compile(rf"^\s*(?:{_alt(HEDGE_NEGATED_LEAD)})\b|\b(?:{_alt(HEDGE_NEGATED_ANY)})\b", re.I)
_POSSIBLE = re.compile(rf"\b(?:{_alt(HEDGE_POSSIBLE)})\b|\?", re.I)
_PROBABLE = re.compile(rf"\b(?:{_alt(HEDGE_PROBABLE)})\b", re.I)

Hedge = Literal["negated", "possible", "probable", "definite"]

# ── dates and priors ─────────────────────────────────────────────────────────
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_PATTERN = (rf"\b\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}\b|\b\d{{4}}-\d{{1,2}}-\d{{1,2}}\b|\b\d{{1,2}}/\d{{4}}\b"
                rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{2,4}}\b|\b{_MONTH}\s+\d{{4}}\b")  # provisional: Gate B1
# Report side: any of these is a reference to an earlier study.
PRIOR_PHRASES = (r"compared (?:with|to)", "comparison", "prior", r"previous(?:ly)?", r"interval(?:ly)?",
                 "unchanged", "new since", r"stable (?:in|since|compared)")           # provisional: Gate B1
# ... except "prior/previous <surgical or medical noun>" ("previous cholecystectomy", "previous MI").
PRIOR_HISTORY_NOUNS = (r"\w+ectomy", r"\w+otomy", r"\w+ostomy", r"\w+plasty", "surgery", "operation", "resection",
                       "repair", "procedure", "intervention", "biopsy", "treatment", "chemotherapy", "radiotherapy",
                       "MI", "myocardial infarction", "stroke", "CVA", "TIA", "infarct", "PE", "DVT", "fracture",
                       "trauma", "injury", "history", "episodes?", "admissions?", "infection",
                       "malignancy", "cancer")                                         # provisional: Gate B1
# Source side: a prior-study phrase is a prior word followed within a few tokens by a study noun or a date.
SOURCE_PRIOR_WORDS = ("prior", "previous", "previously", "comparison", "compared", "old", "last", "since",
                      "earlier")                                                       # provisional: Gate B1
SOURCE_STUDY_NOUNS = ("CT", "CTs", "MRI?", "MRIs", "US", "USS", "ultrasound", "x-?ray", "XR", "CXR", "radiographs?",
                      "PET", "scans?", "study", "studies", "examinations?", "exams?", "imaging", "films?",
                      "images")                                                        # provisional: Gate B1
PRIOR_WINDOW_TOKENS = 3  # provisional: Gate B1 (tokens allowed between the prior word and the study noun)
_DATE = re.compile(DATE_PATTERN, re.I)
_PRIOR = re.compile(rf"\b(?:{'|'.join(PRIOR_PHRASES)})\b", re.I)
_PRIOR_HISTORY = re.compile(rf"\b(?:prior|previous)\s+(?:\w+\s+)?(?:{_alt(PRIOR_HISTORY_NOUNS)})\b", re.I)
_SRC_PRIOR = re.compile(rf"\b(?:{_alt(SOURCE_PRIOR_WORDS)})\b(?:\W+\w+){{0,{PRIOR_WINDOW_TOKENS}}}?\W+"
                        rf"(?:{_alt(SOURCE_STUDY_NOUNS)}|(?:19|20)\d\d|{DATE_PATTERN})\b", re.I)
# Signature / registration lines are not findings: "GMC 7662932", "Reported by Dr X", "tel 0123", "ext 4567".
_SIGNATURE = re.compile(r"\b(?:GMC|NMC|HCPC|registration|reg\.?\s*(?:no|number)|ext(?:ension)?|tel(?:ephone)?|"
                        r"phone|bleep|pager)\b\.?\s*(?:no\.?|number|#|:)?\s*\d|"
                        r"\b(?:reported|dictated|verified|authori[sz]ed|signed)\s+by\b", re.I)
# A comparator number inside a negative / normal clause is a reference threshold, not a measurement.
_NORMAL_CLAUSE = re.compile(r"\b(?:normal|unremarkable|within normal limits|wnl)\b", re.I)
_THRESHOLD = re.compile(r"(?:[<>≥≤]=?|\b(?:greater|more|larger|bigger|less|smaller|fewer)\s+than|\bup\s+to|"
                        r"\bover|\bunder|\bexceeding)\s*\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?)*"
                        r"(?:\s*(?:mm|cm|ml|%|HU))?", re.I)
_LIST_MARK = re.compile(r"^\s*\d+(?:[.)]\s+|\s*[-–]\s+(?=[A-Za-z]))")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), 1)}

# ── number normalisation ─────────────────────────────────────────────────────
UNIT_SPELLINGS = ((r"millimet(?:re|er)s?", "mm"), (r"centimet(?:re|er)s?", "cm"),
                  (r"cc|cm3|cubic centimet(?:re|er)s?", "ml"), (r"millilit(?:re|er)s?", "ml"),
                  (r"per ?cent", "%"), (r"hounsfield\s+units?|h\.u(?=\.|\b)\.?|hu", "HU"))  # provisional: Gate B1
NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
                "twenty")                                                              # provisional: Gate B1
GRADE_WORDS = ("grade", "type", "stage", "class", "category", "bosniak")               # provisional: Gate B1
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
_UNITS = [(re.compile(rf"(?<=\d)\s*(?:{a})\b", re.I), f" {b}") for a, b in UNIT_SPELLINGS]
_NUMWORD = re.compile(rf"\b(?:{_alt(NUMBER_WORDS)})\b", re.I)
_GRADE_ROMAN = re.compile(rf"\b({_alt(GRADE_WORDS)})\s+(viii|vii|iii|ix|iv|vi|ii|x|v|i)(?=[a-z]?\b)", re.I)

# ── modality vocabulary (arm 1) and size words ───────────────────────────────
MODALITY_VOCAB = {                                                                     # provisional: Gate B1
    "MR": re.compile(r"\b(?:(?i:signal|stir|flair|diffusion restriction|restricted diffusion|gadolinium|susceptibility"
                     r"|(?:hyper|hypo|iso)intens\w*)|T[12][- ]?weighted|ADC)\b"),
    "CT": re.compile(r"\b(?:attenuation|hounsfield|HU|hyperdense|hypodense|isodense)\b", re.I),
    "US": re.compile(r"\b(?:echogenic\w*|hypoechoic|hyperechoic|anechoic|isoechoic|posterior acoustic)\b", re.I),
}
# Flow "signal" is ultrasound vocabulary, not MR.
US_SIGNAL_OK = re.compile(r"\b(?:doppler|colou?r|power|flow|vascular)\s+signal\b", re.I)  # provisional: Gate B1
SIZE_SMALL_WORDS = ("small", "tiny", "minute")                                         # provisional: Gate B1
SIZE_SUBCM_WORDS = ("subcentimetre", "subcentimeter")                                  # provisional: Gate B1
SIZE_LARGE_WORDS = ("large", "huge", "massive", "bulky")                               # provisional: Gate B1
# Names, not sizes: "small bowel", "large intestine", "small amount", "large volume".
SIZE_IGNORE = re.compile(r"\b(?:small|large)\s+(?:bowel|intestines?|amounts?|volumes?)\b", re.I)  # provisional: Gate B1
SIZE_WINDOW_TOKENS = 4  # provisional: Gate B1 (size word and measurement at most this many tokens apart)
# "The kidney is small, measuring 80 mm": an organ length, not a lesion size.
SIZE_ORGAN_NOUNS = ("kidney", "kidneys", "liver", "spleen", "uterus", "prostate", "thyroid", "ovary", "ovaries",
                    "testis", "testes", "pancreas", "gallbladder", "bladder", "heart", "gland", "lobe",
                    "lobes")                                                           # provisional: Gate B1
SIZE_LESION_NOUNS = ("mass", "lesion", "lesions", "nodule", "nodules", "cyst", "cysts", "stone", "stones", "calculus",
                     "collection", "node", "nodes", "polyp", "aneurysm", "tumour", "tumor", "abscess", "haematoma",
                     "hematoma", "effusion", "deposit", "deposits", "focus")           # provisional: Gate B1
_SMALL = re.compile(rf"\b(?:{_alt(SIZE_SMALL_WORDS)})\b", re.I)
_SUBCM = re.compile(rf"\b(?:{_alt(SIZE_SUBCM_WORDS)})\b", re.I)
_LARGE = re.compile(rf"\b(?:{_alt(SIZE_LARGE_WORDS)})\b", re.I)
_MEAS = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?:\s*(?:mm|cm))?(?:\s*[x×]\s*\d+(?:\.\d+)?(?:\s*(?:mm|cm))?)*"
                   r"\s*(?:mm|cm)\b", re.I)
_TOKEN = re.compile(r"[A-Za-z]+|\d+(?:\.\d+)?")
SMALL_MAX_MM = 30.0     # provisional: Gate B1
SUBCM_MAX_MM = 10.0     # provisional: Gate B1
LARGE_MIN_MM = 10.0     # provisional: Gate B1


def hedge_tag(clause: str) -> Hedge:
    text = _DATE.sub(" ", clause or "")          # "12 May 2024" is not a hedge
    if _NOT_EXCLUDED.search(text):
        return "possible"
    if _NEGATED.search(text):
        return "negated"
    if _POSSIBLE.search(text):
        return "possible"
    if _PROBABLE.search(text):
        return "probable"
    return "definite"


def modality(scan: Optional[str]) -> Optional[str]:
    s = scan or ""
    if re.search(r"\bMR(?:I|CP|A|V)?\b|magnetic", s, re.I):
        return "MR"
    if re.search(r"\bCT(?:PA|KUB|A|C)?\b|computed tom", s, re.I):
        return "CT"
    if re.search(r"\bUSS?\b|ultrasound|sonograph|doppler", s, re.I):
        return "US"
    if re.search(r"\bX-?ray\b|radiograph|\bC?XR\b", s, re.I):
        return "XR"
    return None


# ── helpers ──────────────────────────────────────────────────────────────────

def _grade_words(text: str) -> Set[str]:
    """Classification words (grade, type, Bosniak...) the text actually grades ("Bosniak IIF", "grade 2")."""
    return {m.group(1).lower() for m in re.finditer(rf"\b({_alt(GRADE_WORDS)})\s+(?:[ivx]+|\d+)\b", text or "", re.I)}


def _norm_numbers(text: str, spelled: bool = False, grades: Optional[Set[str]] = None) -> str:
    """Units to their abbreviation (cc → ml, millimetres → mm), roman grades to arabic, and (source side only)
    spelled numbers one–twenty to digits. With `grades` (report side), a roman grade converts only when the
    source grades with the same classification word; otherwise the numeral is dropped (grading is not a number
    check's job)."""
    def _roman(m):
        if grades is not None and m.group(1).lower() not in grades:
            return m.group(1)
        return f"{m.group(1)} {_ROMAN[m.group(2).lower()]}"
    t = _GRADE_ROMAN.sub(_roman, text or "")
    if spelled:
        t = _NUMWORD.sub(lambda m: str(NUMBER_WORDS.index(m.group(0).lower()) + 1), t)
    for pat, rep in _UNITS:
        t = pat.sub(rep, t)
    return t


def _value(n: str) -> str:
    """"6mm" → "6", "70%" → "70": the number without its unit."""
    return re.match(r"[\d.]+", n).group(0)


def _date_key(raw: str) -> str:
    """Canonical date: "yyyy-mm-dd", or "yyyy-mm" for a month-year; the raw text when it does not parse."""
    s = raw.lower().strip()
    try:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            y, mo, d = int(m[1]), int(m[2]), int(m[3])
        elif re.fullmatch(r"\d{1,2}/\d{4}", s):
            mo, y = (int(x) for x in s.split("/"))
            return f"{y:04d}-{mo:02d}"
        elif (m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", s)):
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
        elif (m := re.fullmatch(r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?([a-z]{3})[a-z]*\.?\s+(\d{2,4})", s)):
            mo, y = _MONTHS[m[2]], int(m[3])
            if y < 100:
                y += 2000
            if not m[1]:
                return f"{y:04d}-{mo:02d}"
            d = int(m[1])
        else:
            return s
        if y < 100:
            y += 2000
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except (KeyError, ValueError):
        return s


def _date_supported(key: str, src: Set[str]) -> bool:
    """A month-year is supported by any source date in that month; a full date only by the same date."""
    return key in src or (len(key) == 7 and any(k.startswith(key + "-") for k in src))


def _prior_refs(text: str) -> List[str]:
    """Prior-study references in a report clause (surgical / medical "previous X" removed)."""
    return [m.group(0) for m in _PRIOR.finditer(_PRIOR_HISTORY.sub(" ", text))]


def _size_conflict(text: str) -> Optional[float]:
    """The measurement (mm) a size word contradicts, when both sit within SIZE_WINDOW_TOKENS tokens."""
    t = SIZE_IGNORE.sub(" ", text)
    toks = [(m.start(), m.group(0).lower()) for m in _TOKEN.finditer(t)]
    idx = lambda pos: sum(1 for s, _ in toks if s < pos)          # noqa: E731  token index at a char position
    meas = []
    for m in _MEAS.finditer(t):
        mm = [float(n[:-2]) for n in numbers(m.group(0)) if n.endswith("mm")]
        if mm:
            meas.append((idx(m.start()), idx(m.end()) - 1, max(mm)))
    for pat, bad in ((_SMALL, lambda v: v >= SMALL_MAX_MM), (_SUBCM, lambda v: v >= SUBCM_MAX_MM),
                     (_LARGE, lambda v: v < LARGE_MIN_MM)):
        for w in pat.finditer(t):
            i = idx(w.start())
            organ = any(tok in SIZE_ORGAN_NOUNS for _, tok in toks[max(0, i - 3):i + 4])
            for a, b, v in meas:
                if min(abs(i - a), abs(i - b)) > SIZE_WINDOW_TOKENS or not bad(v):
                    continue
                between = {tok for _, tok in toks[min(i, a):max(i, b) + 1]}
                if organ and not (between & set(SIZE_LESION_NOUNS)):
                    continue                     # the organ's own length
                return v
    return None


def _span(report: str, c: ReportClause) -> Span:
    """The clause's own span (the sentence's span for a synthetic negative-list item)."""
    return Span(start=c.start, end=c.end, text=report[c.start:c.end])


def _cand(report: str, c: ReportClause, kind: str, detector: str, evidence: dict, lane: str = "accuracy",
          line_id: Optional[str] = None, line_text: Optional[str] = None) -> Candidate:
    return Candidate(lane=lane, kind=kind, section=c.section, anchor=_span(report, c), line_id=line_id,
                     line_text=line_text, evidence=evidence, detector=detector)


# Alignment is a confidence-gated supporting tool (ledger L-56): misattributed, laterality and level_conflict fire
# only on confident pairs. Same rule and constant as lanes.confident() (lanes/__init__.py, used by lanes/coverage.py);
# duplicated here because lanes imports jev_pass, which imports this module (a circular import). Keep them in step.
PAIR_CONFIDENT = 0.5   # provisional: Gate F (same value as lanes.PAIR_CONFIDENT)


def _confident(p: Pair) -> bool:
    return p.how in ("exact", "number") or (p.how != "level_conflict" and p.score >= PAIR_CONFIDENT)


def _conflict_confident(p: Pair) -> bool:
    """A level_conflict pair is never confident for anchoring, but the conflict itself is worth raising when the
    pair is otherwise confident: align() scores it with the ordinary lexical/number/anatomy score (levels add
    nothing to the score; a disjoint level only relabels `how`), so that score is the pair's non-level confidence."""
    return p.how == "level_conflict" and p.score >= PAIR_CONFIDENT


# Owner-line fallback words (no ANATOMY word): drop the generic ones before comparing.
_OWNER_GENERIC = frozenset({"normal", "normally", "unremarkable", "small", "mild", "moderate", "size", "appearance",
                            "seen", "noted", "identified", "evidence", "present", "large", "measuring"})  # provisional: Gate B1


def _source_numbers(source: str) -> Tuple[Set[str], Set[str], Set[str]]:
    """(numbers, values, grade words) of the dictation-plus-history text."""
    src_nums = numbers(_norm_numbers(_DATE.sub(" ", source), spelled=True))   # numbers() already drops level tokens
    return src_nums, {_value(n) for n in src_nums}, _grade_words(source)


def _unsupported_numbers(text: str, src_nums: Set[str], src_vals: Set[str], src_grades: Set[str]) -> List[str]:
    """`text` is a clause with its list marker already removed."""
    ntext = _norm_numbers(_DATE.sub(" ", text), grades=src_grades)
    if _NEGATED.search(text) or _NORMAL_CLAUSE.search(text):
        ntext = _THRESHOLD.sub(" ", ntext)
    return [] if _SIGNATURE.search(text) else sorted(
        n for n in numbers(ntext) if n not in src_nums and _value(n) not in src_vals)


def undictated_numbers(text: str, dictation: str, history: str) -> List[str]:
    """The numbers (with unit, normalised) in a report clause that the dictation and history lack: the
    `code.numbers` rule. A value that matches with a different or missing unit on one side is supported."""
    return _unsupported_numbers(_LIST_MARK.sub("", text), *_source_numbers(f"{dictation}\n{history}"))


def is_measurement(n: str) -> bool:
    """A normalised number that carries a unit ("6mm", "45ml", "55%"), not a bare count or list number."""
    return bool(re.search(r"[A-Za-z%]", n))


def run_checks(report: str, dictation: str, history: str, scan: str, al: Alignment,
               study_title: Optional[str] = None) -> List[Candidate]:
    source = f"{dictation}\n{history}"
    src_nums, src_vals, src_grades = _source_numbers(source)
    src_dates = {_date_key(d) for d in _DATE.findall(source)}
    src_prior = bool(_SRC_PRIOR.search(source))
    mod = modality(scan)
    out: List[Candidate] = []
    seen = set()

    def add(c: Candidate) -> None:
        key = (c.kind, c.detector, c.anchor.start if c.anchor else None, c.line_id)
        if key not in seen:
            seen.add(key)
            out.append(c)

    for c in al.clauses:
        text = _LIST_MARK.sub("", c.text)
        # unsupported: numbers, dates, prior-study references with no match in dictation or history. A value that
        # matches with a different or missing unit on one side is supported ("6" / "6 mm", "45 cc" / "45 ml").
        dates = [d for d in _DATE.findall(text) if not _date_supported(_date_key(d), src_dates)]
        nums = _unsupported_numbers(text, src_nums, src_vals, src_grades)
        if nums:
            add(_cand(report, c, "unsupported", "code.numbers", {"numbers": nums}))
        if dates:
            add(_cand(report, c, "unsupported", "code.dates", {"dates": dates}))
        refs = _prior_refs(text)
        if refs and not src_prior:
            add(_cand(report, c, "unsupported", "code.prior", {"phrase": refs[0]}))
        # misattributed: a dictated measurement attached to a different structure (confidently paired clauses
        # only, L-56). Any pair, weak or not, still exempts its line as the number's owner: a weak pair never
        # creates a flag.
        paired_ids = {l.id for l in al.paired_lines(c.id)}
        sure = any(_confident(p) for p in al.pairs if p.clause_id == c.id)
        cwords = words(text)
        for n in sorted(x for x in numbers(text) if x.endswith("mm")) if sure else ():
            owners = [l for l in al.lines if n in numbers(l.text)]
            if not owners or any(o.id in paired_ids for o in owners):
                continue
            o = owners[0]
            owner_words = (words(o.text) & ANATOMY) or (words(o.text) - _OWNER_GENERIC)
            if owner_words and not (owner_words & cwords):
                add(_cand(report, c, "misattributed", "code.measurement", {"number": n, "source_line": o.text},
                          line_id=o.id, line_text=o.text))
        # inconsistent: another modality's vocabulary (not in dictation or history), size word against measurement
        if mod in MODALITY_VOCAB:
            mtext = US_SIGNAL_OK.sub(" ", text) if mod == "US" else text
            for other, pat in MODALITY_VOCAB.items():
                m = pat.search(mtext) if other != mod else None
                if m and not pat.search(source):
                    add(_cand(report, c, "inconsistent", "code.modality", {"word": m.group(0), "modality": mod}))
        mm = _size_conflict(text)
        if mm is not None:
            add(_cand(report, c, "inconsistent", "code.size_word", {"max_mm": mm}))

    # level conflict (coverage lane): the report put a dictated finding at another level. Dictation is truth;
    # align() keeps these pairs only when the line has no pair at its own level. One item per pair.
    for p in al.pairs:
        if not _conflict_confident(p):
            continue
        l, c = al.line(p.line_id), al.clause(p.clause_id)
        add(_cand(report, c, "differs", "code.level_conflict",
                  {"dictated_level": ", ".join(l.levels), "report_levels": list(c.levels)},
                  lane="coverage", line_id=l.id, line_text=l.text))

    # laterality (coverage lane): a dictated side missing from every paired clause, nothing bounding it. The line
    # needs a confident pair (L-56); every pair, weak or not, can still bound it. Anchored on the best confident one.
    if side_of(study_title) not in ("left", "right"):
        for l in al.lines:
            if l.side not in ("left", "right") or l.negative or l.background:
                continue
            cs = al.paired_clauses(l.id)
            sure = [al.clause(p.clause_id) for p in sorted(al.pairs, key=lambda p: -p.score)
                    if p.line_id == l.id and _confident(p)]
            if not sure or any(c.side in (l.side, "bilateral") or c.subheading_side == l.side for c in cs):
                continue
            if any(c.side and c.side != l.side for c in cs):
                continue                         # the other side is stated: classify-first's `differs`
            add(_cand(report, sure[0], "laterality", "code.laterality", {"side": l.side}, lane="coverage",
                      line_id=l.id, line_text=l.text))
    return out
