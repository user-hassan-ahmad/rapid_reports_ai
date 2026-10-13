"""Numbers read from a quoted span by code (library spec §12, next slice item 1). The model's number is never
trusted: it must agree with the one reading, or choose between several. `settle` widens the quote to the whole
measurement it sits in before reading it, so a sub-span of a bound, range or dimension set is never read alone. One conversion table; a spoken unit that is neither
the input's unit nor converts to it by that table gives no reading, so the input is asked. A range ("6-8 mm") or a
fraction ("3/12") or a bound ("under 5 mm") gives no reading either: which value is meant is a judgement, so it is
asked. A lesion number whose finding holds another number (`alone`, an allow list: a sibling, a prior, a count of
lesions) is still drafted, but pre-filled rather than read (spec §7.5, WHY_OTHER_NUMBER)."""
from __future__ import annotations

import re

# spoken unit (lower case) -> canonical unit
_CANON = {
    "mm": "mm", "mms": "mm", "millimetre": "mm", "millimetres": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm": "cm", "cms": "cm", "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "mm3": "mm3", "mm³": "mm3", "cubic mm": "mm3", "cu mm": "mm3", "cubic millimetres": "mm3",
    "cubic millimeters": "mm3",
    "cm3": "cm3", "cm³": "cm3", "cc": "cm3", "ml": "cm3", "mls": "cm3", "millilitres": "cm3", "milliliters": "cm3",
    "hu": "HU", "h.u.": "HU", "hounsfield units": "HU",
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
# a space inside a spoken unit matches any run of spaces ("cubic  millimetres")
_UNITS = "|".join(re.escape(u).replace(r"\ ", r"\s+") for u in sorted(_CANON, key=len, reverse=True))
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
    u = " ".join((unit or "").split())
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


_RUN_ON = re.compile(r"\d\s+[-−+]?\d")    # "8 4 mm": a bare number run into the measurement is another number
# a measurement that starts or ends on a connector ("x 8 mm", "8 mm to") is a piece of a larger one (a leading sign
# joined to its digit, "-20 HU", is not a connector)
_EDGE = re.compile(r"^\s*(?:(?:x|×|by|to)(?![a-z])|[-–−](?![\d.]))|(?<![a-z])(?:x|×|by|to|[-–−])\s*$", re.I)


def _widen(text: str, s: int, e: int) -> tuple[int, int]:
    """The whole measurement expression around text[s:e]: adjacent numbers, units, x/by, ranges, bounds and signs.
    An image reference or anatomical label ("segment 6", "image 45") is never part of it."""
    labels = [(m.start(), m.end()) for rx in (_LABEL, _IMAGE) for m in rx.finditer(text)]
    toks = [(m.start(), m.end()) for m in _TOK.finditer(text)
            if not any(a <= m.start() and m.end() <= b for a, b in labels)]
    changed = True
    while changed:
        changed = False
        for ts, te in toks:
            if ts < s and (te > s or not text[te:s].strip()):
                s, changed = ts, True
            if te > e and (ts < e or not text[e:ts].strip()):
                e, changed = te, True
    return s, e


def _at(quote: str, text: str) -> list[tuple[int, int]]:
    """Where each occurrence of the quote in the text (case, spacing and punctuation aside) lies, widened."""
    words = re.findall(r"[^\W_]+(?:[.,][^\W_]+)*", quote or "")
    if not words or not text:
        return []
    pat = re.compile(r"(?<![^\W_])" + r"[\W_]*".join(re.escape(w) for w in words) + r"(?![^\W_])", re.I)
    return [_widen(text, m.start(), m.end()) for m in pat.finditer(text)]


def spans(quote: str, text: str) -> list[str]:
    """Each occurrence of the quote in the text (case, spacing and punctuation aside), widened."""
    return [text[s:e] for s, e in _at(quote, text)]


# numbers a finding may hold besides its one measurement (fix round 4): each never followed by a unit
_NOT_UNIT = rf"(?![.,]?\d)(?!\s*-?\s*(?:{_UNITS})(?![a-z0-9]))"
_DATE = re.compile(rf"(?<![\w.,/-])(\d{{1,4}})([/.-])(\d{{1,4}})(?:\2(\d{{1,4}}))?{_NOT_UNIT}(?![\w/-])", re.I)
_YEAR = re.compile(rf"(?<![\w.,/-])(?:199\d|20\d\d){_NOT_UNIT}(?![\w/-])", re.I)
# a number before a dimension or range connector is part of a measurement ("image 4 x 8 mm"), never a label
_NOT_LINK = r"(?!\s*(?:x|×|by|to|-|–|−)(?![a-z]))"
_IMAGE = re.compile(rf"(?<![a-z])(?:series|slice|image|img|se|im)\s*[(\[]?\s*(?::|#|no\.?)?\s*\d+{_NOT_UNIT}"
                    rf"{_NOT_LINK}\s*[)\]]?", re.I)
_LABEL = re.compile(rf"(?<![a-z])(?:(?:segment|seg|level|rib)\s*\d+|[ctls]\d+)"
                    rf"(?:\s*[/-]\s*[ctls]?\d+)?{_NOT_UNIT}{_NOT_LINK}(?![a-z])", re.I)
_OWN_COUNT = re.compile(r"\b(?:single|solitary)\b", re.I)
_NUMBER_WORDS = ("zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
                 "|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
                 "|hundreds?|half|halves|dozens?|single|solitary|both|several|multiple")
_NUMBER = re.compile(rf"\d|\b(?:{_NUMBER_WORDS})\b", re.I)


def _date(m: re.Match) -> bool:
    """Digit groups joined by / . or - that make a calendar date: d/m/y or m/d/y (a two- or four-digit year), y-m-d,
    or a month and a four-digit year."""
    a, b, c = m.group(1), m.group(3), m.group(4)

    def year(y: str, short: bool = True) -> bool:
        return (short and len(y) == 2) or (len(y) == 4 and 1990 <= int(y) <= 2099)

    def month(x: str) -> bool:
        return len(x) <= 2 and 1 <= int(x) <= 12

    def day(x: str) -> bool:
        return len(x) <= 2 and 1 <= int(x) <= 31
    if c is None:
        return (year(a, False) and month(b)) or (month(a) and year(b, False))
    if len(a) == 4:
        return year(a) and month(b) and day(c)
    return year(c) and ((day(a) and month(b)) or (month(a) and day(b)))


# unit families (lab fix round item 4): a lesion number is blocked only by another number of its own family. Length
# and volume are one family, size: both measure a lesion, so a volume beside a diameter may be a prior or a sibling.
FAMILY = {"mm": "size", "cm": "size", "mm3": "size", "cm3": "size", "HU": "attenuation",
          "days": "time", "weeks": "time", "months": "time", "years": "time"}
_PIECE = rf"{_N}(?:\s*-?\s*(?:{_UNITS})(?![a-z0-9]))?"
_MEASURE = re.compile(rf"[{_SIGN}]?\s?{_PIECE}(?:{_X}{_PIECE}){{0,2}}", re.I)
_UNIT_AT_END = re.compile(rf"(?<![a-z])(?:{_UNITS})$", re.I)
_UNIT_WORD = re.compile(rf"(?<![a-z])({_UNITS})(?![a-z0-9])", re.I)


def _other_family(w: str, unit: str) -> bool:
    """The run is one measurement (a number or a dimension set) whose recognised unit is attached and of another
    family than the input's: "15 mm" beside "20 HU". A bare number, a range, a bound or an unknown unit is not."""
    w, mine = w.strip(), FAMILY.get(canon(unit))
    if mine is None or any(g.search(w) for g in _GUARDS) or not _MEASURE.fullmatch(w) or not _UNIT_AT_END.search(w):
        return False
    fams = {FAMILY.get(canon(m.group(1))) for m in _UNIT_WORD.finditer(w)}
    return bool(fams) and None not in fams and mine not in fams


def alone(text: str, quote: str, value: float, unit: str, dims: str | None = None) -> bool:
    """A lesion number is settled only when, apart from its quoted measurement, the finding holds no other number:
    no digit and no number word (zero to twenty, the tens, hundred, half, dozen, single, solitary, both, several,
    multiple). Allowed besides: the same reading again in the unit's family ("stable at 8 mm"); an image reference
    (series, image, img, slice, se, im); a date or a year 1990-2099; an anatomical label (segment, seg, S, level,
    rib, or a vertebra such as T4 or L2/3); "single" or "solitary", the input's own count; and a measurement whose
    recognised unit is attached and of another FAMILY ("15 mm" beside "20 HU"). Anything else asks: it
    may be a sibling, a prior or a count of lesions, and which number is meant is the radiologist's to say. A count
    input keeps its own rule."""
    if canon(unit) == "count":
        return True
    at = _at(quote, text)
    if not at:
        return False
    rest = list(text)
    for s, e in at:
        rest[s:e] = " " * (e - s)
    rest = "".join(rest)
    rest = _DATE.sub(lambda m: " " if _date(m) else m.group(0), rest)
    for rx in (_YEAR, _IMAGE, _LABEL, _OWN_COUNT):
        rest = rx.sub(" ", rest)
    runs: list[list[int]] = []                      # runs of measurement tokens with only spaces between
    for m in _TOK.finditer(rest):
        if runs and not rest[runs[-1][1]:m.start()].strip():
            runs[-1][1] = m.end()
        else:
            runs.append([m.start(), m.end()])
    for a, b in reversed(runs):
        w = rest[a:b]
        same = not any(g.search(w) for g in _GUARDS) and readings(w, unit, dims) == [value]
        if re.search(r"\d", w) and (same or _other_family(w, unit)):
            rest = rest[:a] + " " * (b - a) + rest[b:]
    return _NUMBER.search(rest) is None


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
        if any(g.search(w) for g in _GUARDS) or _RUN_ON.search(w) or _EDGE.search(w):
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
