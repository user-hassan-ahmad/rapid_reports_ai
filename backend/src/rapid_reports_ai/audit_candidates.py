"""Candidates for the tier-2 scratchpad audit, proposed by code for Jev to judge.

Jev answers questions; it cannot quote text. So code splits the scratchpad into statements
with exact offsets and proposes what might be wrong: two statements about the same thing
where one negates and the other asserts (or both measure), a side that differs from another
statement or the clinical history, a measurement. A flag then uses the candidate's own
offsets, so every highlight is verbatim by construction.

Plan: docs/superpowers/plans/2026-09-27-jev-scratchpad-audit.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MAX_PAIRS = 12
MAX_CANDIDATES = 24

# Statement ends: a terminal mark followed by whitespace or the end (not a decimal point), or a line break.
_BOUNDARY = re.compile(r"(?<=[.?!])(?=\s|$)|\n")
_BULLET = re.compile(r"^[\s\-*•]+")
_NEGATION = re.compile(r"\b(no|not|without|absent|unremarkable|intact|normal|resolved)\b", re.IGNORECASE)
_SIDE = re.compile(r"\b(left|right)\b", re.IGNORECASE)
_MEASURE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m|millimetres?|centimetres?|metres?|ml|cc|hu|%)(?![a-z])", re.IGNORECASE
)
_WORD = re.compile(r"[a-z]{4,}")
# Words that say nothing about which structure or finding a statement is about.
_STOP = frozenset("""there which with without measuring measures measure measured normal small large mild moderate
severe seen noted identified previously prior study unchanged keeping consistent left right both bilateral upper
lower within size sized appearance further also this that these those have been from into over under each other
some more less than appears likely possible suggest suggesting demonstrated demonstrates evidence feature features
change changes level levels region area part thin simple complete partial present absent intact unremarkable
resolved stable increased decreased interval since about approximately further maximal diameter short axis long
contains containing shows showing noted there""".split())

Kind = Literal["pair", "side", "measure", "negation"]


@dataclass(frozen=True)
class Statement:
    start: int
    end: int
    text: str
    anchors: frozenset[str]
    negated: bool
    side: str | None
    measures: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    statements: tuple[Statement, ...]  # pair: (earlier, later); side: (statement, other?); measure: (statement,)


def _stem(w: str) -> str:
    return w[:-1] if w.endswith("s") and not w.endswith("ss") else w


def anchors(text: str) -> frozenset[str]:
    return frozenset(_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP)


def statements(text: str) -> list[Statement]:
    out, pos = [], 0
    for m in [*_BOUNDARY.finditer(text), None]:
        end = m.start() if m else len(text)
        seg = text[pos:end]
        lead = len(seg) - len(seg.lstrip()) if seg.strip() else 0
        b = _BULLET.match(seg[lead:])
        lead += b.end() if b else 0
        body = seg[lead:].rstrip()
        if body:
            s = pos + lead
            side = _SIDE.search(body)
            out.append(Statement(s, s + len(body), body, anchors(body), bool(_NEGATION.search(body)),
                                 side.group(1).lower() if side else None,
                                 tuple(x.group(0) for x in _MEASURE.finditer(body))))
        pos = m.end() if m else len(text)
    return out


def candidates(text: str, clinical_history: str = "") -> list[Candidate]:
    st = statements(text)
    pairs: list[tuple[int, Candidate]] = []
    for i, a in enumerate(st):
        for b in st[i + 1:]:
            shared = a.anchors & b.anchors
            if shared and (a.negated != b.negated or (a.measures and b.measures)):
                pairs.append((len(shared), Candidate("pair", (a, b))))
    pairs.sort(key=lambda x: -x[0])
    out = [c for _, c in pairs[:MAX_PAIRS]]

    hist_side = _SIDE.search(clinical_history or "")
    hist_anchors = anchors(clinical_history or "")
    for s in st:
        if not s.side:
            continue
        # the later statement of the two carries the flag; the earlier is its other half
        other = next((o for o in st if o.start < s.start and o.side and o.side != s.side and s.anchors & o.anchors), None)
        against_history = bool(hist_side and hist_side.group(1).lower() != s.side and s.anchors & hist_anchors)
        if other is not None or against_history:
            out.append(Candidate("side", (s, other) if other is not None else (s,)))
    out += [Candidate("measure", (s,)) for s in st if s.measures]
    # A negative statement contradicted in other words ("no haemorrhage" / "subdural haematoma")
    # shares no anchor with it, so each one is also asked about as a whole.
    out += [Candidate("negation", (s,)) for s in st if s.negated and len(st) > 1]
    return out[:MAX_CANDIDATES]
