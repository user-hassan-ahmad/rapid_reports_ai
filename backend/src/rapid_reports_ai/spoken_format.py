"""Spoken formatting in code: punctuation words, spine levels, the two-faced 'colon', and
what starts a paragraph.

Deepgram dictation mode is off in the lab because it turns the organ 'colon' into ':'.
Without it, spoken punctuation arrives as words ("L3 slash four", "Conclusion, colon,").
Most punctuation words are never report words, so they are converted unconditionally.
'colon' is the one ambiguous word: it becomes ':' only after a heading or a disc level,
stays the organ after an article or anatomical modifier, and is reported as ambiguous
otherwise (the caller fails open to polish). Deepgram's formatter also glues disc levels
("L3four"); levels are normalised to L3/4, L5/S1, adjacent levels and junctions only.

Lexicon change on purpose (2026-09-26, lab sessions): recorded in the work order.
"""
from __future__ import annotations

import re

_I = re.IGNORECASE

# Unambiguous spoken punctuation, in application order. Each consumes the spaces and any
# comma Deepgram itself placed around the spoken word.
_PUNCTUATION: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\s*\bslash\b\s*", _I), "/"),
    (re.compile(r"\s*\bhyphen\b\s*", _I), "-"),
    (re.compile(r"\s*\bsemi-?colon\b[,;]?", _I), ";"),
    (re.compile(r"\s*\bcomma\b,?", _I), ","),
    (re.compile(r"\s*\bquestion mark\b[.,?]?", _I), "?"),
    (re.compile(r"\bopen (?:bracket|parenthesis)\b\s*", _I), "("),
    (re.compile(r"\s*\bclose (?:bracket|parenthesis)\b", _I), ")"),
)

_NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
_NUM = r"(\d{1,2}|" + "|".join(_NUM_WORDS) + r")"
_JUNCTIONS = {("C", 7, "T", 1), ("T", 12, "L", 1), ("L", 5, "S", 1)}


def _n(s: str) -> int:
    return int(s) if s.isdigit() else _NUM_WORDS[s.lower()]


def _adjacent_pair(m: re.Match[str]) -> str:
    letter, a, b = m.group(1).upper(), int(m.group(2)), _n(m.group(3))
    return f"{letter}{a}/{b}" if b == a + 1 else m.group(0)


def _junction(m: re.Match[str]) -> str:
    l1, a, l2, b = m.group(1).upper(), int(m.group(2)), m.group(3).upper(), int(m.group(4))
    return f"{l1}{a}/{l2}{b}" if (l1, a, l2, b) in _JUNCTIONS else m.group(0)


_LEVEL_SEP = re.compile(r"\b([CTLS])(\d{1,2})\s*[/-]\s*" + _NUM + r"\b", _I)       # L3/four, L4-5
_LEVEL_GLUED = re.compile(r"\b([CTLS])(\d{1,2})" + _NUM + r"\b", _I)              # L3four
_LEVEL_JUNCTION = re.compile(r"\b([CTLS])(\d{1,2})(?:\s*[/-]\s*|\s+)([CTLS])(\d{1,2})\b", _I)  # L5 S1


def normalise_spine_levels(text: str) -> str:
    s = _LEVEL_JUNCTION.sub(_junction, text)
    s = _LEVEL_SEP.sub(_adjacent_pair, s)
    return _LEVEL_GLUED.sub(lambda m: _adjacent_pair(m) if not m.group(3).isdigit() else m.group(0), s)


def apply_spoken_format(text: str) -> str:
    """Unambiguous spoken punctuation and disc levels. Safe on any transcript."""
    s = text or ""
    for pattern, mark in _PUNCTUATION:
        s = pattern.sub(mark, s)
    s = re.sub(r",{2,}", ",", s)
    return normalise_spine_levels(s)


# --- colon -------------------------------------------------------------------------------

HEADINGS = ("conclusion", "impression", "findings", "comparison", "technique", "indication",
            "history", "clinical history", "clinical details", "opinion", "summary", "recommendation")
_HEADING_RE = "|".join(re.escape(h) for h in sorted(HEADINGS, key=len, reverse=True))
_LEVEL_LABEL = re.compile(r"^[CTLS]\d{1,2}/(?:[CTLS])?\d{1,2}$", _I)
_ORGAN_BEFORE = {"the", "a", "sigmoid", "transverse", "ascending", "descending", "rectosigmoid", "right",
                 "left", "distal", "proximal", "mid", "whole", "entire", "of", "and", "visualised",
                 "visualized", "redundant", "thickened"}
_ORGAN_AFTER = {"is", "are", "wall", "walls", "shows", "demonstrates", "appears", "contains", "and"}
_COLON = re.compile(r"(?P<pre>,?\s*)\bcolon\b(?P<post>\s*,)?", _I)


def _last_word(s: str) -> str:
    words = re.findall(r"[\w/]+", s)
    return words[-1] if words else ""


def resolve_colon(text: str, preceding: str = "") -> tuple[str, bool]:
    """Spoken 'colon' → ':' after a heading or disc level; the organ after a modifier or
    before a verb; otherwise left as spoken and reported ambiguous."""
    out, pos, ambiguous = [], 0, False
    for m in _COLON.finditer(text or ""):
        before = text[: m.start()]
        prev = _last_word(before) if before.strip() else _last_word(preceding)
        nxt = (re.findall(r"\w+", text[m.end():]) or [""])[0].lower()
        heading_before = re.search(r"(?:" + _HEADING_RE + r")\W*$", (before if before.strip() else preceding), _I)
        if prev.lower() in _ORGAN_BEFORE or nxt in _ORGAN_AFTER:
            continue  # the organ: leave as spoken
        if heading_before or _LEVEL_LABEL.match(prev):
            out.append(text[pos: m.start()].rstrip(" ,"))
            out.append(":")
            pos = m.end()
            continue
        ambiguous = True
    out.append(text[pos:])
    return "".join(out), ambiguous


# --- structure -----------------------------------------------------------------------------

_STARTS_PARAGRAPH = re.compile(
    r"^\s*(?:[CTLS]\d{1,2}/(?:[CTLS])?\d{1,2}\b|(?:" + _HEADING_RE + r")\b\s*(?:[:.]|$))", _I)


def starts_paragraph(text: str) -> bool:
    """A disc level or a report heading opens its own paragraph."""
    return bool(_STARTS_PARAGRAPH.match(text or ""))


def heading_only(text: str) -> str | None:
    """'Conclusion.', 'Conclusion, colon,', 'impression' → 'Conclusion:' etc.; else None."""
    s = re.sub(r"\bcolon\b", "", text or "", flags=_I)
    s = re.sub(r"[\s,.:;]+", " ", s).strip().lower()
    if s in HEADINGS:
        return s[0].upper() + s[1:] + ":"
    return None


_ENDS_WITH_HEADING = re.compile(r"(?:^|\n)\s*(?:" + _HEADING_RE + r")\s*:\s*$", _I)


def ends_with_heading(preceding: str) -> bool:
    """The scratchpad's last line is a bare heading ('Conclusion:'): what follows is its content."""
    return bool(_ENDS_WITH_HEADING.search(preceding or ""))
