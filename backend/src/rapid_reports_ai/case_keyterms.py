"""Per-case Deepgram keyterms: one model pass at workspace setup, filtered by code.

Deepgram keyterms bias recognition towards the listed words (nova-3; 500 tokens in total,
20–50 focused terms advised, no common words). The fixed core list missed every word
misheard in the lab ("adrenal", "hypodense", "subsegmental", "paracentral", "nodule"…).
A model proposes up to 50 terms for the scan type, clinical history and checklist once,
when the workspace is set up (never on the dictation path); code keeps only specialised
terms and merges a trimmed core list after them. Lab only (DEEPGRAM_CASE_KEYTERMS=1).

Plan: docs/superpowers/plans/2026-09-27-deepgram-params-keyterms-scratch.md
"""
from __future__ import annotations

import re

from .deepgram_config import CORE_KEYTERMS, keyterm_tokens

# Words Deepgram rarely mishears and that would only add bias: English function words and
# everyday radiology qualifiers. A term made only of these is dropped.
COMMON_WORDS = set("""a an the of in on at to for from by with and or no not is are was be this that there
normal abnormal left right bilateral mild moderate severe small large tiny new old acute chronic
lesion finding findings seen noted evidence change changes size sizes measure measuring measures
upper lower middle anterior posterior medial lateral superior inferior proximal distal
unremarkable stable present absent within without""".split())
MAX_WORDS = 3
KEYTERM_CAP = 50
TOKEN_BUDGET = 450  # under Deepgram's 500 with room for its own counting


def _clean(term: str) -> str:
    t = re.sub(r"[^\w\s'/-]", "", term or "").strip()
    return re.sub(r"\s+", " ", t)


_FUNCTION = set("a an the of in on at to for from by with and or".split())


def filter_keyterms(raw: list[str], cap: int = KEYTERM_CAP) -> list[str]:
    """Specialised terms only: function words trimmed from the edges, ≤ 3 words, not made
    only of common words, de-duplicated (case-insensitively), capped. Casing is kept as
    given: the prompt asks for lowercase except names and acronyms (Deepgram's advice)."""
    out: dict[str, str] = {}
    for term in raw:
        words = _clean(term).split()
        while words and words[0].lower() in _FUNCTION:
            words = words[1:]
        while words and words[-1].lower() in _FUNCTION:
            words = words[:-1]
        if not words or len(words) > MAX_WORDS or all(w.lower() in COMMON_WORDS for w in words):
            continue
        t = " ".join(words)
        out.setdefault(t.lower(), t)
        if len(out) >= cap:
            break
    return list(out.values())


def merge_with_core(case_terms: list[str], core=CORE_KEYTERMS, budget: int = TOKEN_BUDGET,
                    cap: int = KEYTERM_CAP) -> list[str]:
    """Case terms first, then core terms not already present: at most `cap` terms (Deepgram
    advises 20–50 focused terms; each one biases recognition) and within the token budget."""
    out, seen = [], set()
    for t in [*case_terms, *core]:
        if len(out) >= cap:
            break
        k = t.lower()
        if k in seen:
            continue
        if keyterm_tokens(out + [t]) > budget:
            continue
        out.append(t)
        seen.add(k)
    return out


def keyterms_for_socket(case_terms: list[str], enabled: bool) -> list[str] | None:
    """What the websocket sends Deepgram: None means the core list (unchanged behaviour)."""
    if not enabled:
        return None
    terms = filter_keyterms(case_terms)
    return merge_with_core(terms) if terms else None


KEYTERM_SYSTEM_PROMPT = """You list the specialised terms a radiologist is likely to dictate for one examination, so a speech recogniser can expect them.

Return at most 40 terms, favouring the words a recogniser is most likely to mishear: the likely findings for the clinical question and this scan, imaging descriptors (density, attenuation, signal, enhancement, morphology), anatomical sub-regions and segments, and named classification systems. Plain anatomy adjectives only where they are easy to mishear. One to three words each. Lowercase, except proper names and acronyms. No everyday words (normal, left, small, lesion), no sentences, no numbers, no duplicates, no variants of a term already listed (list "nerve root" once, not with each sequence or plane)."""

KEYTERM_USER_TEMPLATE = """Scan type: {scan_type}
Clinical history: {clinical_history}
Checklist sections: {sections}"""
