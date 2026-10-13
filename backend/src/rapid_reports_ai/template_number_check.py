"""Numbers in a generated template report that the radiologist did not dictate (template path, after generation).

A score, grade, time window, measurement or other value the writer took from a sheet instruction or example rather
than from the FINDINGS input, the clinical history or the confirmed conclusion is a review flag, never an edit.
Code only. A number token is digits, a decimal, a range ("50-70") or a fraction ("15/15"), with the unit word after
it if any (mm, cm, %, hours, weeks, HU...). A token with a unit is dictated when the sources give every value with
the same unit (spellings normalised; mm and cm are different units, never converted) or without a unit (the report
reads a unit into a dictated bare value: "volume 87" -> "87 ml/m2"); a unitless token when every
value appears among the sources' numbers (digits, number words, roman numerals after a grade/stage word).
A labelled value also needs one of its label words in the sources: always after a score/grade word ("grade 2",
"grade III", "ASPECTS score 5"); after an acronym or eponym ("ASPECTS 7", "Fazekas 1") only when the value has no
unit, so a measured structure ("CBD 6 mm") is not a label. Not numbers: list markers, identifiers (a letter run
followed by digits: a sequence, vessel segment or vertebral level), dates and times, section header lines, and a
reference limit after <, >, ≤ or ≥ whose value a FIXED, WITH or Measurement line of the sheet gives. The sheet's
FIXED text, RULE replacement (WITH) text and section headers count as sources: the template's own wording.
Never raises.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set, Tuple

KIND = "undictated_number"

_NUM = r"\d+(?:\.\d+)?"
_WORD_NUMS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
              "seventeen eighteen nineteen twenty").split()
_WORDS = {w: i for i, w in enumerate(_WORD_NUMS)}
# Unit spellings -> one name (longest first in the pattern)
_UNIT_NAMES = {
    "mm": "mm", "millimetre": "mm", "millimetres": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm": "cm", "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "ml": "ml", "millilitre": "ml", "millilitres": "ml", "milliliter": "ml", "milliliters": "ml", "cc": "ml",
    "%": "%", "percent": "%", "per cent": "%",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "min": "min", "mins": "min", "minute": "min", "minutes": "min",
    "day": "day", "days": "day", "week": "week", "weeks": "week", "wk": "week", "wks": "week",
    "month": "month", "months": "month", "mo": "month", "year": "year", "years": "year", "yr": "year", "yrs": "year",
    "hu": "hu", "degree": "deg", "degrees": "deg", "°": "deg",
}
_UNIT = "|".join(re.escape(u) for u in sorted(_UNIT_NAMES, key=len, reverse=True))
_UNIT_AFTER = re.compile(rf"(?i)[\s-]*({_UNIT})[²³]?(?![A-Za-z])")
_VALUE = rf"{_NUM}(?:\s*(?:-|–|to|/)\s*{_NUM})?"
# A value starts after a non-word character, or right after "<digit>x" ("3x4 cm" scans both)
_TOKEN = re.compile(rf"(?:(?<![\w.])|(?<=\d[x×])){_VALUE}")
_SRC_TOKEN = re.compile(rf"(?i)(?:(?<![A-Za-z\d.]){_VALUE}|\b(?:{'|'.join(_WORD_NUMS)})\b)")
_ROMAN_AFTER = re.compile(r"(?i:\b(grade|stage|class|type|category|level|tier))\s+([IVX]{1,4})\b")
_LABEL_WORDS = {"grade", "score", "stage", "class", "type", "category", "level", "tier", "classification", "scale"}
# Month names whole, never a word that starts like one ("septal 1070 ms", "marked 1200 ms")
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|"
          r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?")
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
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
_SHEET_TEXT = re.compile(r'(?:\bFIXED\s*|\bWITH\s*|\bheader:\s*)"([^"]*)"')
_MEASUREMENT_LINE = re.compile(r"(?im)^.*\bMeasurement\s*:.*$")
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
    words = [float(_WORDS[w]) for w in re.findall(r"[a-z]+", token.lower()) if w in _WORDS]
    return [float(x) for x in re.findall(_NUM, token)] + words


def _unit(text: str, end: int) -> Tuple[Optional[str], int]:
    """(normalised unit, end of the unit) for the unit word right after `end`, or (None, end)."""
    m = _UNIT_AFTER.match(text, end)
    if not m:
        return None, end
    return _UNIT_NAMES[re.sub(r"\s+", " ", m.group(1).lower())], m.end()


def _sources(text: str) -> Tuple[Set[float], Set[Tuple[float, str]], Set[float]]:
    """(every value, every (value, unit) pair, every value stated without a unit) in the sources."""
    vals = {float(x) for x in re.findall(_NUM, text)}
    vals |= {float(_WORDS[w]) for w in re.findall(r"[a-z]+", text.lower()) if w in _WORDS}
    vals |= {float(_ROMAN[r.upper()]) for _, r in _ROMAN_AFTER.findall(text) if r.upper() in _ROMAN}
    pairs: Set[Tuple[float, str]] = set()
    bare: Set[float] = set()
    for m in _SRC_TOKEN.finditer(text):
        unit, _ = _unit(text, m.end())
        if unit:
            pairs |= {(v, unit) for v in _values(m.group(0))}
        else:
            bare |= set(_values(m.group(0)))
    return vals, pairs, bare


def _labels(text: str, start: int) -> List[str]:
    """Up to two words just before a token (nearest first) that may name a score, grade or classification: a
    score/grade word, an acronym, or a capitalised word that does not open its sentence (an eponym)."""
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
        sheet = sheet or ""
        fixed = _SHEET_TEXT.findall(sheet)
        headers = {h.strip().lower() for h in re.findall(r'header:\s*"([^"]*)"', sheet) if h.strip()}
        src = "\n".join(s for s in sources if s) + "\n" + "\n".join(fixed)
        (allowed, pairs, bare), src_l = _sources(src), src.lower()
        limits = _sources("\n".join(fixed + _MEASUREMENT_LINE.findall(sheet)))[0]
        scan = _masked(report, headers)
        found: List[tuple] = []   # (start, text, values, unit, label words)
        for m in _ROMAN_AFTER.finditer(scan):
            r = m.group(2).upper()
            if r in _ROMAN:
                labels = _labels(scan, m.start(2))
                found.append((m.start(), " ".join([*reversed(labels), r]), [float(_ROMAN[r])], None, labels))
                scan = _blank(scan, m.start(2), m.end(2))
        for m in _TOKEN.finditer(scan):
            vals = _values(m.group(0))
            if re.search(r"[<>≤≥]\s*$", scan[:m.start()]) and all(v in limits for v in vals):
                continue   # a reference limit the sheet's fixed wording gives ("normal < 22"), not a patient value
            unit, end = _unit(scan, m.end())
            labels = _labels(scan, m.start())
            found.append((m.start(), " ".join([*reversed(labels), report[m.start():end].strip()]), vals, unit, labels))
        out, seen = [], set()
        for start, text, vals, unit, labels in sorted(found, key=lambda f: f[0]):
            ok = all((v, unit) in pairs or v in bare for v in vals) if unit else all(v in allowed for v in vals)
            # a labelled value: one of its label words was dictated too (an acronym/eponym only when unitless)
            need = [w for w in labels if w.lower() in _LABEL_WORDS or not unit]
            if ok and need:
                ok = any(re.search(rf"(?i)\b{re.escape(w)}\b", src_l) for w in labels)
            if ok or text.lower() in seen:
                continue
            seen.add(text.lower())
            out.append({"kind": KIND, "text": text, "sentence": _sentence(report, start)})
        return out
    except Exception:  # noqa: BLE001 - a flag is never worth a failed report
        return []
