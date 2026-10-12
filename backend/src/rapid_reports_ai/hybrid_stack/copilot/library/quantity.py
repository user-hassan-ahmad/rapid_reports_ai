"""Numbers read from a quoted span by code (library spec §12, next slice item 1). The model's number is never
trusted: it only chooses between several readings of one quote. One conversion table; a spoken unit that is neither
the input's unit nor converts to it by that table gives no reading, so the input is asked. A range ("6-8 mm") or a
fraction ("3/12") or a bound ("under 5 mm") gives no reading either: which value is meant is a judgement, so it is
asked."""
from __future__ import annotations

import re

# spoken unit (lower case) -> canonical unit
_CANON = {
    "mm": "mm", "millimetre": "mm", "millimetres": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm": "cm", "cms": "cm", "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "mm3": "mm3", "mm³": "mm3", "cubic millimetres": "mm3", "cubic millimeters": "mm3",
    "cm3": "cm3", "cm³": "cm3", "cc": "cm3", "ml": "cm3", "mls": "cm3", "millilitres": "cm3", "milliliters": "cm3",
    "hu": "HU", "hounsfield units": "HU",
    "day": "days", "days": "days", "week": "weeks", "weeks": "weeks", "month": "months", "months": "months",
    "year": "years", "years": "years", "yr": "years", "yrs": "years", "yo": "years",
}
# the one conversion table, (from, to) -> factor. Months and years never become days (their length varies): asked.
CONVERT = {("cm", "mm"): 10.0, ("mm", "cm"): 0.1, ("cm3", "mm3"): 1000.0, ("mm3", "cm3"): 0.001,
           ("weeks", "days"): 7.0}
BARE = {"", "count", "years"}       # input units a number without a spoken unit may be read in
COUNT_WORDS = {"single": 1, "solitary": 1, "sole": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
               "seven": 7, "eight": 8, "nine": 9, "ten": 10}

_NUM = r"(\d+(?:\.\d+)?)"
_UNITS = "|".join(sorted((re.escape(u) for u in _CANON), key=len, reverse=True))
_U = rf"(?:\s*-?\s*({_UNITS})(?![a-z0-9]))?"
_X = r"\s*(?:x|×|by)\s*"
_RANGE = re.compile(rf"(?<![\d.]){_NUM}{_U}\s*(?:-|–|to(?:\s+(?:under|below|less than))?)\s*{_NUM}{_U}", re.I)
_FRACTION = re.compile(r"(?<![\d.])\d+\s*/\s*\d+")
_DIMS = re.compile(rf"(?<![\d.]){_NUM}{_U}{_X}{_NUM}{_U}(?:{_X}{_NUM}{_U})?", re.I)
_QTY = re.compile(rf"(?<![\d.]){_NUM}{_U}", re.I)
_COUNT_RE = re.compile(r"\b(" + "|".join(sorted(COUNT_WORDS, key=len, reverse=True)) + r")\b", re.I)
_CW = "|".join(sorted(COUNT_WORDS, key=len, reverse=True))
# a bound ("under 5 mm", "8 mm or more", "<6 mm") names a band edge, not the value: no reading, like a range
_BOUND = re.compile(
    rf"(?:[<>≤≥]=?|\b(?:under|over|below|above|less than|more than|greater than|fewer than|smaller than|larger than"
    rf"|up to|at least|at most)\b)\s*(?:\d+(?:\.\d+)?|\b(?:{_CW})\b){_U}"
    rf"|(?<![\d.])\d+(?:\.\d+)?{_U}\s*(?:\bor (?:more|less|greater|larger|smaller|above|below|over|under)\b"
    rf"|\band (?:above|over|below|under)\b|\+)", re.I)


def canon(unit: str) -> str:
    u = (unit or "").strip()
    return _CANON.get(u.lower(), u)


def _conv(n: float, spoken: str | None, want: str) -> float | None:
    if spoken is None:
        return n if want in BARE else None
    have = canon(spoken)
    if have == want:
        return n
    f = CONVERT.get((have, want))
    return None if f is None else round(n * f, 6)


def readings(quote: str, unit: str, dims: str | None = None) -> list[float]:
    """Every value the quote gives an input in `unit`. A dimension group "A x B [x C] unit" gives its mean (exactly
    two dims) or its max when `dims` says so, else each member; a count input also reads count words when no digit
    reads."""
    want = canon(unit)
    out: list[float] = []

    def group(m: re.Match) -> str:
        nums = [float(x) for x in (m.group(1), m.group(3), m.group(5)) if x is not None]
        units = [m.group(2), m.group(4), m.group(6)][:len(nums)]
        last = next((u for u in reversed(units) if u), None)
        vals = [_conv(n, u or last, want) for n, u in zip(nums, units)]
        if None not in vals:
            if dims == "mean":
                out.extend([round(sum(vals) / 2, 6)] if len(vals) == 2 else [])
            elif dims == "max":
                out.append(max(vals))
            else:
                out.extend(vals)
        return " "

    text = _BOUND.sub(" ", _FRACTION.sub(" ", _RANGE.sub(" ", quote or "")))
    text = _DIMS.sub(group, text)
    for m in _QTY.finditer(text):
        v = _conv(float(m.group(1)), m.group(2), want)
        if v is not None:
            out.append(v)
    if not out and want == "count":
        out += [float(COUNT_WORDS[m.group(1).lower()]) for m in _COUNT_RE.finditer(text)]
    return list(dict.fromkeys(out))


def pick(readings: list[float], model: float | None) -> float | None:
    """One reading is the value whatever the model said; several need the model's number to equal one of them."""
    if len(readings) == 1:
        return readings[0]
    if model is None:
        return None
    hits = [r for r in readings if abs(r - model) < 1e-6]
    return hits[0] if hits else None
