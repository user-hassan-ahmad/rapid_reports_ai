"""Cosmetic equality of two sheet-line texts (spec 2026-10-15-stable-line-ids-design, "Wrong matches are worse than lost
answers"; Hassan's decision 4). No similarity threshold: two texts are the same line only when they are exactly equal
after norm_key, or cosmetically equal:

1. lookalike characters unified (dashes and minus -> "-", curly -> straight quotes, "×" -> "x", Unicode spaces ->
   space): the only step that merges characters;
2. tokenised, nothing removed: numbers (".5" and "1.5" are one token each), comparators and operators, units,
   in-sentence punctuation (. ; : , ( ) ?) and hyphenated words (one token each);
3. normalised: lower case, only a final full stop and quotation marks dropped, a fixed UK/US spelling table, a fixed
   list of filler phrases removed only as exact whole phrases;
4. every remaining token compared in order, and the clinical gate tokens (negation, hedging, laterality, severity,
   numbers, comparators, operators, units) identical in order.
Protected words: no filler phrase contains a negation or hedge word, so "is not seen" never tidies to "is seen".
When in doubt, not the same.

Versioned constants: changing LOOKALIKES, FILLERS or SPELLING changes which lines keep their uid, so bump MATCH_VERSION
and keep the constant tests green."""
from __future__ import annotations

import re
from typing import Optional, Tuple

from .hybrid_stack.template import norm_key

MATCH_VERSION = 1

# Lookalike characters -> one form. The only merging step.
LOOKALIKES = {
    "–": "-", "—": "-", "−": "-", "‒": "-", "‐": "-", "‑": "-",
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'",
    "×": "x",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", "　": " ",
}
_LOOKALIKE = str.maketrans(LOOKALIKES)

# A number (".5", "5", "1.5"), a comparator, operator or in-sentence punctuation mark, a word (hyphenated and
# apostrophe words are one token), or any other single non-space character.
_TOKEN = re.compile(r"\d*\.\d+|\d+|[<>≤≥=±+/%.;:,()?]|[a-z]+(?:[-'][a-z0-9]+)*|\S")
_QUOTE_TOKENS = frozenset({'"', "'"})

# Filler phrases, removed only as exact whole-phrase token runs. Never a negation or hedge word (test enforced).
FILLERS: Tuple[Tuple[str, ...], ...] = (
    ("there", "is"), ("there", "are"), ("is", "seen"), ("is", "noted"), ("is", "identified"),
    ("is", "demonstrated"),
)

# UK -> US spelling, whole words only (no suffix rules). Both spellings normalise to the US form.
SPELLING = {
    "oedema": "edema", "oedematous": "edematous", "haemorrhage": "hemorrhage", "haemorrhagic": "hemorrhagic",
    "haematoma": "hematoma", "haemangioma": "hemangioma", "haemodynamic": "hemodynamic",
    "haemodynamically": "hemodynamically", "ischaemia": "ischemia", "ischaemic": "ischemic",
    "oesophagus": "esophagus", "oesophageal": "esophageal", "anaemia": "anemia", "paediatric": "pediatric",
    "orthopaedic": "orthopedic", "tumour": "tumor", "tumours": "tumors", "colour": "color", "grey": "gray",
    "centre": "center", "centres": "centers", "fibre": "fiber", "fibres": "fibers", "calibre": "caliber",
    "localised": "localized", "visualised": "visualized", "characterised": "characterized",
    "faeces": "feces", "faecal": "fecal", "foetal": "fetal",
    "leukaemia": "leukemia", "diarrhoea": "diarrhea", "aetiology": "etiology", "haemothorax": "hemothorax",
}

NEGATION = frozenset({"no", "not", "without", "absent", "neither", "nor", "negative"})
_NEGATION_PREFIX = re.compile(r"^(?:non-?|un)[a-z]")   # non-enhancing, nonspecific, unremarkable, … (fail closed)
HEDGE_WORDS = frozenset({"possible", "possibly", "likely", "probable", "probably", "suspicious", "suggestive", "may",
                         "query", "?"})
HEDGE_PHRASES: Tuple[Tuple[str, ...], ...] = (
    ("cannot", "be", "excluded"), ("not", "excluded"), ("in", "keeping", "with"), ("consistent", "with"),
)
_HEDGE_PHRASE_WORDS = frozenset({"cannot", "excluded", "keeping", "consistent"})
LATERALITY = frozenset({"left", "right", "bilateral", "unilateral"})
SEVERITY = frozenset({"minimal", "mild", "moderate", "severe", "marked", "small", "large", "grade", "category"})
UNIT_QUOTES = {"'": "\u2032", '"': "\u2033"}   # 5' and 5": prime and double prime unit tokens
UNITS = frozenset({"mm", "cm", "m", "ml", "l", "mg", "g", "kg", "mgy", "mgycm", "msv", "hu", "ms", "s", "bpm",
                   "mmhg", "cc", *UNIT_QUOTES.values()})
_SENTENCE_END = frozenset({".", ";"})
OPERATORS = frozenset("<>≤≥=±+/%")
_NUMBER = re.compile(r"\d*\.\d+$|\d+$")


def tokens(text: str) -> Tuple[str, ...]:
    """Every token of the text after the lookalike map, lower case, nothing removed. A quote mark directly after a
    digit is a unit (5' feet, 5" inches) and becomes its own unit token, never a dropped quotation mark."""
    t = (text or "").translate(_LOOKALIKE).lower()
    out = []
    for m in _TOKEN.finditer(t):
        tok = m.group()
        if tok in _QUOTE_TOKENS and m.start() > 0 and t[m.start() - 1].isdigit():
            tok = UNIT_QUOTES[tok]
        out.append(tok)
    return tuple(out)


def _gate(toks: Tuple[str, ...], i: int) -> bool:
    t = toks[i]
    if _NUMBER.match(t) or t in OPERATORS:
        return True
    if t == "x":   # an operator only between two numbers ("5 x 3 mm")
        return 0 < i < len(toks) - 1 and bool(_NUMBER.match(toks[i - 1])) and bool(_NUMBER.match(toks[i + 1]))
    return (t in NEGATION or bool(_NEGATION_PREFIX.match(t)) or t in HEDGE_WORDS or t in LATERALITY
            or t in SEVERITY or t in UNITS)


def gates(text: str) -> Tuple[str, ...]:
    """The clinical gate tokens of the raw text, in order (they must be identical for a cosmetic match); a hedge
    phrase ("cannot be excluded") is one gate."""
    toks = tokens(text)
    out = []
    i = 0
    while i < len(toks):
        phrase = next((p for p in HEDGE_PHRASES if toks[i:i + len(p)] == p), None)
        if phrase:
            out.append(" ".join(phrase))
            i += len(phrase)
            continue
        if _gate(toks, i):
            out.append(toks[i])
        i += 1
    return tuple(out)


def _protected(t: str) -> bool:
    return t in NEGATION or bool(_NEGATION_PREFIX.match(t)) or t in HEDGE_WORDS or t in _HEDGE_PHRASE_WORDS


def form(text: str) -> Tuple[str, ...]:
    """The cosmetic form: tokens without quotation marks or a final full stop, spelling mapped, filler phrases removed
    as exact whole runs, order kept. Scope: a filler is never removed once a negation or hedge token has appeared in
    the same sentence (since the last "." or ";"): "No collapse, there is consolidation." keeps its "there is"."""
    toks = [SPELLING.get(t, t) for t in tokens(text) if t not in _QUOTE_TOKENS]
    if toks and toks[-1] == ".":
        toks.pop()
    out: list = []
    guarded = False   # a negation or hedge token earlier in this sentence
    i = 0
    while i < len(toks):
        hit = None if guarded else next((f for f in FILLERS if tuple(toks[i:i + len(f)]) == f), None)
        if hit:
            i += len(hit)
            continue
        t = toks[i]
        guarded = False if t in _SENTENCE_END else guarded or _protected(t)
        out.append(t)
        i += 1
    return tuple(out)


def cosmetic_key(text: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    return form(text), gates(text)


def same_text(a: str, b: str) -> Optional[str]:
    """"exact" (equal after norm_key), "cosmetic" (equal cosmetic form and identical gate tokens), else None."""
    if norm_key(a or "") == norm_key(b or ""):
        return "exact"
    if cosmetic_key(a) == cosmetic_key(b):
        return "cosmetic"
    return None
