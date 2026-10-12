"""Numbers in a generated template report that the radiologist did not dictate (template path, after generation).

A score, grade, time window, measurement or other value the writer took from a sheet instruction or example rather
than from the FINDINGS input, the clinical history or the confirmed conclusion is a review flag, never an edit.
Code only: a number token (digits, decimals, ranges, percent) is dictated when every value in it appears among the
sources' numbers (digits, number words, roman numerals after a grade/stage word); a labelled token ("grade 2",
"ASPECTS 7", "Fazekas 1", "grade III") also needs one of its label words in the sources. Not numbers: list markers, identifiers
(a letter run followed by digits, such as a sequence, vessel segment or vertebral level), dates and times, section
header lines; a reference limit after <, >, ≤ or ≥ whose value the sheet gives. Values in the sheet's FIXED text, RULE replacement (WITH) text and section headers count as sources:
they are the template's own wording. Never raises.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set

KIND = "undictated_number"

_NUM = r"\d+(?:\.\d+)?"
_TOKEN = re.compile(rf"(?<![\w.]){_NUM}(?:\s*(?:-|–|to)\s*{_NUM})?(?:\s*%)?")
_ROMAN_AFTER = re.compile(r"(?i:\b(grade|stage|class|type|category|level|tier))\s+([IVX]{1,4})\b")
_LABEL_WORDS = {"grade", "score", "stage", "class", "type", "category", "level", "tier", "classification", "scale"}
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_MASKS = [
    re.compile(r"(?m)^\s*\d+[.)\]](?=\s)"),                                     # list markers
    re.compile(r"(?<!\S)\d+[)\]](?=\s)"),                                      # inline "2) " / "1] " markers
    re.compile(r"\b[A-Za-z]+\d+(?:[/-]\d+)*\b"),                               # identifiers (T2, M1, L4/5, b1000)
    re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{2,4}\b"),                        # numeric dates
    re.compile(rf"(?i)\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{4}}\b"),     # 12 October 2024
    re.compile(rf"(?i)\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"),   # October 12, 2024
    re.compile(rf"(?i)\b{_MONTH}\s+\d{{4}}\b"),                                # October 2024
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),                               # times
]
_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
_SHEET_TEXT = re.compile(r'(?:\bFIXED\s+|\bWITH\s+|\bheader:\s*)"([^"]*)"')
_END = re.compile(r"[.!?]+(?=\s|$)|\n")


def _blank(text: str, a: int, b: int) -> str:
    return text[:a] + " " * (b - a) + text[b:]


def _masked(text: str, header_lines: Set[str]) -> str:
    lines = [(" " * len(l) if l.strip().lower() in header_lines else l) for l in text.split("\n")]
    out = "\n".join(lines)
    for rx in _MASKS:
        for m in list(rx.finditer(out)):
            out = _blank(out, m.start(), m.end())
    return out


def _values(token: str) -> List[float]:
    return [float(x) for x in re.findall(_NUM, token)]


def _source_values(text: str) -> Set[float]:
    vals = {float(x) for x in re.findall(_NUM, text)}
    vals |= {float(_WORDS[w]) for w in re.findall(r"[a-z]+", text.lower()) if w in _WORDS}
    vals |= {float(_ROMAN[r.upper()]) for _, r in _ROMAN_AFTER.findall(text) if r.upper() in _ROMAN}
    return vals


def _labels(text: str, start: int) -> List[str]:
    """Up to two words just before a token (nearest first) that name a score, grade or classification: a
    grade/stage word, an acronym, or a capitalised word that does not open its sentence (an eponym)."""
    out: List[str] = []
    while len(out) < 2 and (m := re.search(r"([A-Za-z][A-Za-z-]*)\s+$", text[:start])):
        w, before = m.group(1), text[:m.start()].rstrip()
        if not (w.lower() in _LABEL_WORDS or (w.isupper() and len(w) >= 3)
                or (w[0].isupper() and before and before[-1] not in ".!?:\n")):
            break
        out.append(w)
        start = m.start()
    return out


def _sentence(report: str, start: int) -> str:
    """The sentence holding `start`: from the last end (., !, ? before a space, or a line break) to the next."""
    a = max((m.end() for m in _END.finditer(report, 0, start)), default=0)
    m = _END.search(report, start)
    return report[a:m.end() if m else len(report)].strip()


def undictated_numbers(report: str, sources: Iterable[Optional[str]], sheet: str = "") -> List[dict]:
    """[{"kind": "undictated_number", "text", "sentence"}] for each distinct number token in `report` not supplied
    by `sources` (FINDINGS input, clinical history, confirmed conclusion) or the sheet's own fixed wording."""
    try:
        report = (report or "").replace("\r\n", "\n")
        fixed = _SHEET_TEXT.findall(sheet or "")
        headers = {h.strip().lower() for h in re.findall(r'header:\s*"([^"]*)"', sheet or "") if h.strip()}
        src = "\n".join(s for s in sources if s) + "\n" + "\n".join(fixed)
        allowed, src_l, limits = _source_values(src), src.lower(), _source_values(sheet or "")
        scan = _masked(report, headers)
        found: List[tuple] = []   # (start, text, values, label words)
        for m in _ROMAN_AFTER.finditer(scan):
            r = m.group(2).upper()
            if r in _ROMAN:
                labels = _labels(scan, m.start(2))
                found.append((m.start(), " ".join([*reversed(labels), r]), [float(_ROMAN[r])], labels))
                scan = _blank(scan, m.start(2), m.end(2))
        for m in _TOKEN.finditer(scan):
            if re.search(r"[<>≤≥]\s*$", scan[:m.start()]) and all(v in limits for v in _values(m.group(0))):
                continue   # a reference limit the sheet gives ("normal < 22"), not a patient value
            labels = _labels(scan, m.start())
            found.append((m.start(), " ".join([*reversed(labels), m.group(0).strip()]), _values(m.group(0)), labels))
        out, seen = [], set()
        for start, text, vals, labels in sorted(found, key=lambda f: f[0]):
            ok = all(v in allowed for v in vals)
            if ok and labels:   # a labelled value: one of its label words was dictated too
                ok = any(re.search(rf"(?i)\b{re.escape(w)}\b", src_l) for w in labels)
            if ok or text.lower() in seen:
                continue
            seen.add(text.lower())
            out.append({"kind": KIND, "text": text, "sentence": _sentence(report, start)})
        return out
    except Exception:  # noqa: BLE001 - a flag is never worth a failed report
        return []
