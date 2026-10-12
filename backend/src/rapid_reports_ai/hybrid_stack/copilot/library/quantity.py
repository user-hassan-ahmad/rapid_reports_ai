"""Numbers read from a quoted span by code (library spec §12, next slice item 1). The model's number is never
trusted: it must agree with the one reading, or choose between several. `settle` widens the quote to the whole
measurement it sits in before reading it, so a sub-span of a bound, range or dimension set is never read alone. One conversion table; a spoken unit that is neither
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
BARE = {"", "count"}                # input units a number without a spoken unit may be read in
SIGNED = {"HU"}                     # units whose values may be negative: a leading sign is kept, elsewhere refused
COUNT_WORDS = {"single": 1, "solitary": 1, "sole": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
               "seven": 7, "eight": 8, "nine": 9, "ten": 10}

_NUM = r"(\d+(?:\.\d+)?)"
_N = r"\d+(?:\.\d+)?"
_UNITS = "|".join(sorted((re.escape(u) for u in _CANON), key=len, reverse=True))
_U = rf"(?:\s*-?\s*({_UNITS})(?![a-z0-9]))?"
_UQ = rf"(?:\s*-?\s*(?:{_UNITS})(?![a-z0-9]))?"           # the same, not captured
_X = r"\s*(?:x|×|by)\s*"
_CHAIN = rf"{_N}{_UQ}(?:{_X}{_N}{_UQ}){{0,2}}"             # one number or a dimension set, each with an optional unit
_SIGN = "-−+"
_COMMA = re.compile(r"(?<![\d.])\d+(?:,\d+)+(?:\.\d+)?")   # decimal comma or thousands separator: ambiguous
_RANGE = re.compile(rf"(?<![\d.]){_NUM}{_U}\s*(?:-|–|−|to(?:\s+(?:under|below|less than))?)\s*[{_SIGN}]?\s*{_NUM}{_U}",
                    re.I)
_FRACTION = re.compile(r"(?<![\d.])\d+\s*/\s*\d+")
_DIMS = re.compile(rf"(?<![\d.,]){_NUM}{_U}{_X}{_NUM}{_U}(?:{_X}{_NUM}{_U})?", re.I)
_SIGNED = re.compile(rf"(?<![\w.,])([{_SIGN}])\s?({_CHAIN})", re.I)
_QTY = re.compile(rf"(?<![\d.,]){_NUM}{_U}", re.I)
_CW = "|".join(sorted(COUNT_WORDS, key=len, reverse=True))
# a count word counts findings ("two nodules", "single"), never a size ("a six millimetre nodule") or a part ("one of")
_COUNT_RE = re.compile(rf"\b({_CW})\b(?!\s*-?\s*(?:{_UNITS})(?![a-z0-9]))(?!\s+of\b)", re.I)
_BOUND_WORDS = (r"under|over|below|above|less than|more than|greater than|fewer than|smaller than|larger than|up to"
                r"|at least|at most")
_OR_MORE = r"or (?:more|less|greater|larger|smaller|above|below|over|under)|and (?:above|over|below|under)"
# a bound ("under 5 mm", "up to 8 x 5 mm", "8 mm or more", "<6 mm") names a band edge, not the value: no reading, like
# a range. It covers the whole dimension set after (or before) it.
_BOUND = re.compile(
    rf"(?:[<>≤≥]=?|\b(?:{_BOUND_WORDS})\b)\s*(?:{_CHAIN}|\b(?:{_CW})\b)"
    rf"|(?<![\d.]){_CHAIN}\s*(?:\b(?:{_OR_MORE})\b|\+)", re.I)
_GUARDS = (_COMMA, _RANGE, _FRACTION, _BOUND)
# measurement tokens a quote is widened over: numbers, units, dimension and range words, bounds, signs
_TOK = re.compile(rf"(?<![a-wyz_\d.,])\d+(?:[.,]\d+)*|(?<![a-z])(?:{_UNITS}|{_BOUND_WORDS}|{_OR_MORE}|to|by|x)"
                  rf"(?![a-z0-9])|[-–−+×<>≤≥=/]", re.I)


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
    reads. A leading sign is kept for a signed unit (HU) and gives no reading for any other."""
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

    def signed(m: re.Match) -> str:
        q = _QTY.fullmatch(m.group(2).strip())
        if want in SIGNED and q is not None:            # one number, not a dimension set
            v = _conv(float(q.group(1)), q.group(2), want)
            if v is not None:
                out.append(-v if m.group(1) in "-−" else v)
        return " "

    text = quote or ""
    for g in _GUARDS:
        text = g.sub(" ", text)
    text = _SIGNED.sub(signed, text)
    text = _DIMS.sub(group, text)
    for m in _QTY.finditer(text):
        v = _conv(float(m.group(1)), m.group(2), want)
        if v is not None:
            out.append(v)
    if not out and want == "count":
        out += [float(COUNT_WORDS[m.group(1).lower()]) for m in _COUNT_RE.finditer(text)]
    return list(dict.fromkeys(out))


def _agrees(r: float, model: float | None, unit: str) -> bool:
    """The model's number equals the reading, or is the dictated number before a conversion into this unit."""
    if model is None:
        return True
    want = canon(unit)
    return any(abs(r - model * f) < 1e-6 for f in (1.0, *(f for (_, b), f in CONVERT.items() if b == want)))


def _widen(text: str, s: int, e: int) -> str:
    """The whole measurement expression around text[s:e]: adjacent numbers, units, x/by, ranges, bounds and signs."""
    toks = [(m.start(), m.end()) for m in _TOK.finditer(text)]
    changed = True
    while changed:
        changed = False
        for ts, te in toks:
            if ts < s and (te > s or not text[te:s].strip()):
                s, changed = ts, True
            if te > e and (ts < e or not text[e:ts].strip()):
                e, changed = te, True
    return text[s:e]


def spans(quote: str, text: str) -> list[str]:
    """Each occurrence of the quote in the text (case, spacing and punctuation aside), widened."""
    words = re.findall(r"[^\W_]+(?:[.,][^\W_]+)*", quote or "")
    if not words or not text:
        return []
    pat = re.compile(r"(?<![^\W_])" + r"[\W_]*".join(re.escape(w) for w in words) + r"(?![^\W_])", re.I)
    return [_widen(text, m.start(), m.end()) for m in pat.finditer(text)]


_LIST_GAP = re.compile(r"\s*(?:,|;|&|\band\b|\bor\b)\s*", re.I)


def several(text: str, unit: str, dims: str | None = None) -> bool:
    """The text holds more than one distinct measurement in the unit's family (every unit that converts to it): a
    dimension set is one measurement; a bare number listed before one ("8 and 4 mm") shares its unit; the same
    measurement repeated is one. Counts and unitless numbers have no family."""
    want = canon(unit)
    if want in BARE or not text:
        return False
    fam = {u for u in set(_CANON.values()) if u == want or (u, want) in CONVERT}
    exprs: list[list[int]] = []                      # runs of measurement tokens with only spaces between
    for m in _TOK.finditer(text):
        if exprs and not text[exprs[-1][1]:m.start()].strip():
            exprs[-1][1] = m.end()
        else:
            exprs.append([m.start(), m.end()])
    exprs = [x for x in exprs if re.search(r"\d", text[x[0]:x[1]])]
    units = [{canon(u.group(0)) for u in re.finditer(rf"(?<![a-z])(?:{_UNITS})(?![a-z0-9])", text[a:b], re.I)}
             for a, b in exprs]
    member = [bool(u & fam) for u in units]
    for k in range(len(exprs) - 2, -1, -1):          # "8 and 4 mm", "8, 4 mm": the bare number shares the unit
        if not member[k] and not units[k] and member[k + 1] and _LIST_GAP.fullmatch(text[exprs[k][1]:exprs[k + 1][0]]):
            member[k] = True
    sigs = set()
    for (a, b), m in zip(exprs, member):
        if m:
            w = text[a:b]
            sigs.add(tuple(readings(w, unit, dims)) or " ".join(w.lower().split()))
    return len(sigs) > 1


def settle(quote: str, texts: list[str], unit: str, dims: str | None = None,
           model: float | None = None) -> float | None:
    """The value a quote settles, read from the whole measurement it sits in. None (asked) when the quote is not in
    the texts, or any occurrence widens to a bound, a range, a fraction, a decimal comma, a dimension set that does
    not fit `dims`, or more than one reading; or when occurrences differ; or the model's number disagrees."""
    vals = set()
    found = [w for t in texts for w in spans(quote, t)]
    if not found:
        return None
    for w in found:
        if any(g.search(w) for g in _GUARDS):
            return None
        rs = readings(w, unit, dims)
        if len(rs) != 1:
            return None
        vals.add(rs[0])
    if len(vals) != 1:
        return None
    v = vals.pop()
    return v if _agrees(v, model, unit) else None


def pick(readings: list[float], model: float | None, unit: str = "") -> float | None:
    """One reading is the value unless the model's number disagrees with it (asked); several need the model's number
    to equal one of them."""
    if len(readings) == 1:
        return readings[0] if _agrees(readings[0], model, unit) else None
    if model is None:
        return None
    hits = [r for r in readings if abs(r - model) < 1e-6]
    return hits[0] if hits else None
