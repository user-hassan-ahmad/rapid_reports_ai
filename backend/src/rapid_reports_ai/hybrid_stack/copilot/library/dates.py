"""Dates of an earlier study, read by code (library spec §7.12 item 4). The model quotes the date; this parses it in UK
day-month order and counts the days to today in Europe/London. Requests carry no study date yet, so today stands in.
- exact: "12 March 2025", "12th March 2025", "12 Mar 2025", "12/03/2025", "12.03.2025", "12-03-2025", "2025-03-12";
- approximate: a month and year ("March 2025": the 15th), or a bare year from 1990 to this year ("CT 2023": 1 July);
- exact too: the month first, "March 12, 2025" (a month name is never ambiguous);
- anything else, an impossible date, or more than one distinct date in the quote: None.
An image or series number, a vertebral or segment label, or a number with a unit ("2010 mm3", "2000 days") is never a
year (quantity.py's own guards). several_dates also counts the forms parse refuses (a two-digit year, no year), so a
second comparison written that way still makes the interval asked."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import quantity as Q

LONDON = ZoneInfo("Europe/London")
_MONTHS = {m: n for n, names in enumerate(
    (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
     ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
     ("december", "dec")), start=1) for m in names}
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NOT_DIGIT_GROUP = r"(?<![\d/.\-])"            # never part of a longer digit group ("13/13/2025", "1.2025")
_END_GROUP = r"(?![\d/\-]|\.\d)"
_WORDY = re.compile(rf"(?<![\w])(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?,?\s+(\d{{4}})(?!\d)", re.I)
_ISO = re.compile(rf"{_NOT_DIGIT_GROUP}(\d{{4}})-(\d{{1,2}})-(\d{{1,2}}){_END_GROUP}")
_NUMERIC = re.compile(rf"{_NOT_DIGIT_GROUP}(\d{{1,2}})([/.\-])(\d{{1,2}})\2(\d{{4}}){_END_GROUP}")
_WORDY_US = re.compile(rf"(?<![\w])({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.I)
_MONTH_YEAR = re.compile(rf"(?<![\w])({_MON})\.?,?\s+(\d{{4}})(?!\d)", re.I)
_YEAR = Q._YEAR                                 # 1990-2099, never before a unit; bounded by this year below
# forms parse refuses but several_dates counts (review I-1): d/m/yy, a day and month, a month and a short number
_SHORT_NUMERIC = re.compile(rf"{_NOT_DIGIT_GROUP}(\d{{1,2}})([/.\-])(\d{{1,2}})\2(\d{{2}}){_END_GROUP}")
_DAY_MONTH = re.compile(rf"(?<![\w])(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\b", re.I)
_MONTH_NUM = re.compile(rf"(?<![\w])({_MON})\.?[\s\-']+(\d{{1,2}})(?:st|nd|rd|th)?(?![\d.,/]?\d)", re.I)
_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")   # never the locale's
_MOD = re.compile(r"\b(PET-CT|PET/CT|MRI|MR|CT|PET|ultrasound|radiograph|X-ray)(?![\w-])", re.I)
_MOD_NAME = {"pet/ct": "PET-CT", "pet-ct": "PET-CT", "mri": "MRI", "mr": "MR", "ct": "CT", "pet": "PET",
             "ultrasound": "ultrasound", "radiograph": "radiograph", "x-ray": "X-ray"}
_SENTENCE_END = re.compile(r"(?<!\d)\.(?!\d)|[;\n]")


@dataclass(frozen=True)
class ParsedDate:
    day: date
    exact: bool
    text: str            # the date as written in the quote
    start: int = 0       # where it sits in the quote
    end: int = 0


def today() -> date:
    """Today in Europe/London; tests patch this module function."""
    return datetime.now(LONDON).date()


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _mask(text: str) -> str:
    """The text with image or series numbers and labels blanked (same length), as quantity.alone does."""
    out = list(text)
    for rx in (Q._IMAGE, Q._LABEL):
        for m in rx.finditer(text):
            out[m.start():m.end()] = " " * (m.end() - m.start())
    return "".join(out)


def _scan(text: str) -> list[ParsedDate] | None:
    """Every date written in the text, in order: exact forms first, then a month and year, then a bare year, each
    span used once. None when a span looks like a date but is not a real one (31/02/2025): never guessed."""
    text = _mask(text)
    found: list[ParsedDate] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return not any(m.start() < b and a < m.end() for a, b in taken)

    def add(m: re.Match, d: date | None, exact: bool) -> bool:
        if d is None:
            return False
        found.append(ParsedDate(d, exact, m.group(0), m.start(), m.end()))
        taken.append((m.start(), m.end()))
        return True
    this_year = today().year
    for m in _WORDY.finditer(text):
        if free(m) and not add(m, _make(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))), True):
            return None
    for m in _WORDY_US.finditer(text):
        if free(m) and not add(m, _make(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))), True):
            return None
    for m in _ISO.finditer(text):
        if free(m) and not add(m, _make(int(m.group(1)), int(m.group(2)), int(m.group(3))), True):
            return None
    for m in _NUMERIC.finditer(text):           # UK order: day, month, year
        if free(m) and not add(m, _make(int(m.group(4)), int(m.group(3)), int(m.group(1))), True):
            return None
    for m in _MONTH_YEAR.finditer(text):
        if free(m):
            add(m, _make(int(m.group(2)), _MONTHS[m.group(1).lower()], 15), False)
    for m in _YEAR.finditer(text):
        if free(m) and int(m.group(0)) <= this_year:
            add(m, _make(int(m.group(0)), 7, 1), False)
    return sorted(found, key=lambda p: p.start)


def parse(quote: str) -> ParsedDate | None:
    """The one date in a quote, exact or approximate; None when there is none, more than one, or an impossible one."""
    got = _scan(quote or "")
    if not got or len({p.day for p in got}) != 1:
        return None
    return got[0]


def days_since(d: date, today: date | None = None) -> int:
    """Days from d to today (the module's today(), looked up at call time so a test may patch it)."""
    return ((today if today is not None else globals()["today"]()) - d).days


def distinct_dates(text: str) -> list[date]:
    """Every distinct date parse can read in the text, in order of first appearance. An impossible date anywhere
    (31/02/2025) gives [] for the whole text: the caller then asks, never guesses."""
    out: list[date] = []
    for p in _scan(text or "") or []:
        if p.day not in out:
            out.append(p.day)
    return out


def several_dates(text: str) -> bool:
    """More than one date is written in the text, counting the forms parse refuses: a two-digit year ("01/06/24"), a
    day and month with no year ("1 June"), a month and a short number ("June 24", "Jun-24"). One of those that may be
    a date already read (12/03/25 beside 12 March 2025) is the same date. An impossible date counts as another."""
    text = text or ""
    strict = _scan(text)
    if strict is None:
        return True
    days = {p.day for p in strict}
    taken = [(p.start, p.end) for p in strict]
    other = 0
    masked = _mask(text)

    def free(m: re.Match) -> bool:
        return not any(m.start() < b and a < m.end() for a, b in taken)
    loose = [(m, _make(2000 + int(m.group(4)), int(m.group(3)), int(m.group(1))), None)
             for m in _SHORT_NUMERIC.finditer(masked)]
    loose += [(m, None, (_MONTHS[m.group(2).lower()], int(m.group(1)), None)) for m in _DAY_MONTH.finditer(masked)]
    loose += [(m, None, (_MONTHS[m.group(1).lower()], int(m.group(2)), 2000 + int(m.group(2))))
              for m in _MONTH_NUM.finditer(masked)]
    for m, d, md in sorted(loose, key=lambda x: x[0].start()):
        if not free(m):
            continue
        taken.append((m.start(), m.end()))
        if d is not None:
            same = d in days
        elif md is not None:        # (month, day, or the year a two-digit number may be)
            same = any(x.month == md[0] and (x.day == md[1] or x.year == md[2]) for x in days)
        else:                       # an impossible short date
            same = False
        if not same:
            other += 1
    return len(days) + other > 1


def modality(quote: str, p: ParsedDate, texts: list[str]) -> str:
    """The first modality named in the quote's sentence before the date (CT, MRI, MR, PET-CT, PET, ultrasound,
    radiograph, X-ray), else "study"."""
    low_q = quote.lower()
    for t in texts:
        low = (t or "").lower()
        n = low.find(low_q)
        if n < 0:
            continue
        start = max((m.end() for m in _SENTENCE_END.finditer(t, 0, n)), default=0)
        m = _MOD.search(t[start:n + p.start])
        if m:
            return _MOD_NAME[m.group(1).lower()]
    m = _MOD.search(quote[:p.start])
    return _MOD_NAME[m.group(1).lower()] if m else "study"


def basis(quote: str, p: ParsedDate, texts: list[str]) -> str:
    """The value's label: "from the CT of 12 Mar 2025"; an approximate date as written, marked "(approximate)"."""
    mod = modality(quote, p, texts)
    if p.exact:
        return f"from the {mod} of {p.day.day} {_ABBR[p.day.month - 1]} {p.day.year}"
    shown = f"{_ABBR[p.day.month - 1]} {p.day.year}" if _MONTH_YEAR.fullmatch(p.text) else str(p.day.year)
    return f"from the {mod} of {shown} (approximate)"
