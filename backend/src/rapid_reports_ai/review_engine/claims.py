"""One card per claim across FINDINGS and IMPRESSION (pure code).

A claim stated in FINDINGS and repeated in IMPRESSION is one claim: when both copies are flagged, the engine groups
them BEFORE adjudication (lane candidates) or classification routing (negatives), so one verdict covers both and the
rail never shows two verdicts on the same claim. The FINDINGS copy is the primary anchor; the IMPRESSION copy is
listed in `evidence.also_anchors`.

Matching is conservative (never merge different findings):
- one copy in a findings-role section, the other in an impression-role section; same lane and kind (the caller's key);
- same polarity (both negated or both not);
- no conflicting side (left / right / bilateral) and no conflicting numbers when both state them;
- content words (hedges, negation, articles, units dropped; plurals folded): the smaller set is contained in the larger
  (one stray word allowed when the smaller has 5 or more), the larger is at most 2×smaller+2 words (a compound
  impression clause is not the same claim), and they share ≥2 content words (≥1 for a negative, or identical sets);
- one-to-one: a clause with more than one acceptable partner is ambiguous and never merged."""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Set, Tuple

from .alignment import _role

_STOP = set("""
a an the and or of in on at to for from by with without within into onto over under this that these those its it
is are was were be been being has have had there here which who whose also again both either each any some
no not nil none negative absent free
seen noted identified demonstrated present visualised visualized evident appreciated shown shows show
consistent keeping in likely probable probably possible possibly suggestive suggest suggests suggesting compatible
represents represent representing suspicious suspected query may might could cannot excluded exclude favour favor
favoured favored appearance appearances feature features evidence finding findings
measuring measures measure measured approximately approx about mm cm ml hu
""".split())
_SIDES = {"left", "right", "bilateral"}
_WORD = re.compile(r"[a-z]+")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_NEGATED = re.compile(r"^\s*(?:no|nil|there (?:is|are) no|without)\b", re.I)


def _fold(w: str) -> str:
    if len(w) > 4 and w.endswith("ses"):
        return w[:-3] + "sis"                   # metastases → metastasis
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]                           # nodes → node, lesions → lesion
    return w


def content_words(text: str) -> Set[str]:
    return {_fold(w) for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1}


def negated(text: str) -> bool:
    return bool(_NEGATED.match(text or ""))


def _conflict(a: Set[str], b: Set[str]) -> bool:
    return bool(a) and bool(b) and a != b


def same_claim(a: str, b: str, negative: Optional[bool] = None) -> bool:
    """Do two report clauses state the same claim? `negative` (default: whether `a` is negated) lowers the shared-
    word floor to 1 for a negative ("No lymphadenopathy" / "No peritoneal deposit or lymphadenopathy")."""
    if negated(a) != negated(b):
        return False
    negative = negated(a) if negative is None else negative
    la, lb = (set(_WORD.findall(t.lower())) & _SIDES for t in (a, b))
    if _conflict(la, lb) or _conflict(set(_NUM.findall(a)), set(_NUM.findall(b))):
        return False
    ca, cb = content_words(a), content_words(b)
    small, large = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if not small:
        return False
    if small == large:
        return True
    shared = small & large
    if len(shared) < (1 if negative else 2) or len(large) > 2 * len(small) + 2:
        return False
    return len(small - large) <= (1 if len(small) >= 5 else 0)


def role_of(section: Optional[str]) -> Optional[str]:
    return _role(section) if section else None


def link_pairs(entries: Sequence[Tuple[Optional[str], str, str]], negative: Optional[bool] = None
               ) -> List[Tuple[int, int]]:
    """entries: (section name or None, clause text, match key e.g. lane|kind). Returns (findings index, impression
    index) pairs, one-to-one; a clause with more than one acceptable partner is never linked."""
    roles = [role_of(s) for s, _, _ in entries]
    f_idx = [i for i, r in enumerate(roles) if r == "findings"]
    i_idx = [i for i, r in enumerate(roles) if r == "impression"]
    ok = {(f, m) for f in f_idx for m in i_idx
          if entries[f][2] == entries[m][2] and same_claim(entries[f][1], entries[m][1], negative)}
    out = []
    for f, m in sorted(ok):
        if sum(1 for x in ok if x[0] == f) == 1 and sum(1 for x in ok if x[1] == m) == 1:
            out.append((f, m))
    return out


__all__ = ["content_words", "negated", "same_claim", "link_pairs", "role_of"]
