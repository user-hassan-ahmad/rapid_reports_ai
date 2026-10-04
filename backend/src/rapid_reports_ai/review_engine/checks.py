"""Deterministic checks (spec §6.2 laterality and level, §6.3 accuracy). Every lexicon here is provisional until
Gate B1 measures it on the 41 audit-comparison reports; a missed phrasing is a recall gap, never a false fix,
because every hit still goes to the adjudicator.

`hedge_tag` plus the overstated check is the dedicated detector for dropped hedges (ledger L-53: the Jev
wording cannot see certainty)."""
from __future__ import annotations

import re
from typing import List, Literal, Optional

from .alignment import ANATOMY, Alignment, ReportClause, numbers, side_of, words
from .items import Candidate, Span

# ── hedges ───────────────────────────────────────────────────────────────────
# Ladder: possible < probable < definite; negated sits outside it. UK convention: "in keeping with" and
# "consistent with" are PROBABLE, so "may represent" → "in keeping with" is an upgrade of exactly one step.
HEDGE_NOT_EXCLUDED = (r"can ?not be (?:excluded|ruled out)", r"not be (?:excluded|ruled out)",
                      r"not excluded")                                                 # provisional: Gate B1
HEDGE_NEGATED_LEAD = ("no", "nil", "without", "there is no", "there are no")           # provisional: Gate B1
HEDGE_NEGATED_ANY = ("not seen", "absent", "negative for")                             # provisional: Gate B1
HEDGE_POSSIBLE = ("may", "might", "possible", "possibly", "could", "query", "questionable", "equivocal",
                  "indeterminate")                                                     # provisional: Gate B1
HEDGE_PROBABLE = ("likely", "probable", "probably", "suggestive of", "suggests", "suspicious for",
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
_RANK = {"possible": 1, "probable": 2, "definite": 3}

Hedge = Literal["negated", "possible", "probable", "definite"]

# ── dates and priors ─────────────────────────────────────────────────────────
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_PATTERN = (rf"\b\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}\b|\b\d{{4}}-\d{{1,2}}-\d{{1,2}}\b"
                rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{2,4}}\b|\b{_MONTH}\s+\d{{4}}\b")  # provisional: Gate B1
PRIOR_PHRASES = (r"compared (?:with|to)", "comparison", "prior", r"previous(?:ly)?", r"interval(?:ly)?",
                 "since the", "unchanged", "new since", r"stable (?:in|since|compared)")  # provisional: Gate B1
_DATE = re.compile(DATE_PATTERN, re.I)
_PRIOR = re.compile(rf"\b(?:{'|'.join(PRIOR_PHRASES)})\b", re.I)
_LIST_MARK = re.compile(r"^\s*\d+[.)]\s+")

# ── modality vocabulary (arm 1) and size words ───────────────────────────────
MODALITY_VOCAB = {                                                                     # provisional: Gate B1
    "MR": re.compile(r"\b(?:(?i:signal|stir|flair|diffusion restriction|restricted diffusion|gadolinium|susceptibility)"
                     r"|T[12][- ]?weighted|T[12] (?:hyper|hypo)intens\w*|ADC)\b"),
    "CT": re.compile(r"\b(?:attenuation|hounsfield|HU|hyperdense|hypodense|isodense)\b", re.I),
    "US": re.compile(r"\b(?:echogenic\w*|hypoechoic|hyperechoic|anechoic|isoechoic|posterior acoustic)\b", re.I),
}
SIZE_SMALL_WORDS = ("small", "tiny", "minute")                                         # provisional: Gate B1
SIZE_SUBCM_WORDS = ("subcentimetre", "subcentimeter")                                  # provisional: Gate B1
SIZE_LARGE_WORDS = ("large", "huge", "massive", "bulky")                               # provisional: Gate B1
_SMALL = re.compile(rf"\b(?:{_alt(SIZE_SMALL_WORDS)})\b", re.I)
_SUBCM = re.compile(rf"\b(?:{_alt(SIZE_SUBCM_WORDS)})\b", re.I)
_LARGE = re.compile(rf"\b(?:{_alt(SIZE_LARGE_WORDS)})\b", re.I)
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
    if re.search(r"\bMRI?\b|magnetic", s, re.I):
        return "MR"
    if re.search(r"\bCT\b|computed tom", s, re.I):
        return "CT"
    if re.search(r"\bUS\b|ultrasound|sonograph|doppler", s, re.I):
        return "US"
    if re.search(r"\bX-?ray\b|radiograph|\bXR\b", s, re.I):
        return "XR"
    return None


def _span(report: str, c: ReportClause) -> Span:
    """The clause's own span (the sentence's span for a synthetic negative-list item)."""
    return Span(start=c.start, end=c.end, text=report[c.start:c.end])


def _cand(report: str, c: ReportClause, kind: str, detector: str, evidence: dict, lane: str = "accuracy",
          line_id: Optional[str] = None, line_text: Optional[str] = None) -> Candidate:
    return Candidate(lane=lane, kind=kind, section=c.section, anchor=_span(report, c), line_id=line_id,
                     line_text=line_text, evidence=evidence, detector=detector)


def _max_mm(text: str) -> Optional[float]:
    mm = [float(n[:-2]) for n in numbers(text) if n.endswith("mm")]
    return max(mm) if mm else None


def run_checks(report: str, dictation: str, history: str, scan: str, al: Alignment,
               study_title: Optional[str] = None) -> List[Candidate]:
    source = f"{dictation}\n{history}"
    src_nums = numbers(_DATE.sub(" ", source))           # numbers() already drops level tokens
    src_dates = {d.lower() for d in _DATE.findall(source)}
    src_prior = bool(_PRIOR.search(source))
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
        # unsupported: numbers, dates, prior-study references with no match in dictation or history
        dates = [d for d in _DATE.findall(text) if d.lower() not in src_dates]
        nums = sorted(numbers(_DATE.sub(" ", text)) - src_nums)
        if nums:
            add(_cand(report, c, "unsupported", "code.numbers", {"numbers": nums}))
        if dates:
            add(_cand(report, c, "unsupported", "code.dates", {"dates": dates}))
        prior = _PRIOR.search(text)
        if prior and not src_prior:
            add(_cand(report, c, "unsupported", "code.prior", {"phrase": prior.group(0)}))
        # overstated: report certainty above every paired dictated line's (a dropped hedge)
        tag = hedge_tag(text)
        lines = al.paired_lines(c.id)
        if tag in _RANK and lines:
            ltags = [hedge_tag(l.text) for l in lines]
            if all(t in _RANK for t in ltags):
                top = max(ltags, key=lambda t: _RANK[t])
                if _RANK[tag] > _RANK[top]:
                    add(_cand(report, c, "overstated", "code.hedge", {"dictated": top, "report": tag}))
        # misattributed: a dictated measurement attached to a different structure
        paired_ids = {l.id for l in lines}
        for n in sorted(x for x in numbers(text) if x.endswith("mm")):
            owners = [l for l in al.lines if n in numbers(l.text)]
            if not owners or any(o.id in paired_ids for o in owners):
                continue
            o = owners[0]
            if words(o.text) & ANATOMY and not (words(o.text) & words(text) & ANATOMY):
                add(_cand(report, c, "misattributed", "code.measurement", {"number": n, "source_line": o.text},
                          line_id=o.id, line_text=o.text))
        # inconsistent: another modality's vocabulary (not dictated), size word against measurement
        if mod in MODALITY_VOCAB:
            for other, pat in MODALITY_VOCAB.items():
                m = pat.search(text) if other != mod else None
                if m and not pat.search(dictation):
                    add(_cand(report, c, "inconsistent", "code.modality", {"word": m.group(0), "modality": mod}))
        mm = _max_mm(text)
        if mm is not None and ((_SMALL.search(text) and mm >= SMALL_MAX_MM)
                               or (_SUBCM.search(text) and mm >= SUBCM_MAX_MM)
                               or (_LARGE.search(text) and mm < LARGE_MIN_MM)):
            add(_cand(report, c, "inconsistent", "code.size_word", {"max_mm": mm}))

    # level conflict (coverage lane): the report put a dictated finding at another level. Dictation is truth;
    # align() keeps these pairs only when the line has no pair at its own level. One item per pair.
    for p in al.pairs:
        if p.how != "level_conflict":
            continue
        l, c = al.line(p.line_id), al.clause(p.clause_id)
        out.append(_cand(report, c, "differs", "code.level_conflict",
                         {"dictated_level": ", ".join(l.levels), "report_levels": list(c.levels)},
                         lane="coverage", line_id=l.id, line_text=l.text))

    # laterality (coverage lane): a dictated side missing from every paired clause, nothing bounding it
    if side_of(study_title) not in ("left", "right"):
        for l in al.lines:
            if l.side not in ("left", "right") or l.negative or l.background:
                continue
            cs = al.paired_clauses(l.id)
            if not cs or any(c.side in (l.side, "bilateral") or c.subheading_side == l.side for c in cs):
                continue
            if any(c.side and c.side != l.side for c in cs):
                continue                         # the other side is stated: classify-first's `differs`
            add(_cand(report, cs[0], "laterality", "code.laterality", {"side": l.side}, lane="coverage",
                      line_id=l.id, line_text=l.text))
    return out
