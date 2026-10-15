"""Dictated numbers missing from a generated report (spec 2026-10-15, dictated number fidelity step 1).

The reverse of `template_number_check.undictated_numbers`: every number the radiologist dictated must be written in
the report. Code only, both stack paths, review flags only (no repair). A number is digits: an integer, a decimal
(".14" included), a thousands-grouped integer ("1,260"); numbers joined by x, by, -, –, to or / form a chain
("2.3 x 1.8 cm", "50-69%", "132/78 to 118/70 mmHg") and the unit after the chain's last number applies to each.
Number words are not dictated numbers. Identifiers (T2, L4/5, b1000), dates, clock times and list markers are masked
as in `template_number_check`. A dictated value is present when the report holds the same value (float equality:
0.14 = .14, 1.5 != 15) with the same normalised unit (a number word followed by that unit counts: "three minutes" holds 3 min); a bare
report number never satisfies a dictated unit ("segment 4" does not hold "4 minutes"). Matching is one-to-one: each
report occurrence satisfies one dictated (value, unit), so "4 mm and 4 mm" needs two, unless its report sentence
says it covers several ("both", "each", "bilateral(ly)", "all", or a count: "two 4 mm nodules"). Each source is matched afresh,
so a value repeated across sources (dictation and a tapped row) is one fact. A dictated value without a unit
matches any report value or, up to twenty, its number word, and uses up nothing. No unit conversion: 5 mm reported
as 0.5 cm is a miss. Never raises.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from collections import Counter
from typing import Iterable, List, Optional

from .template_number_check import _masked, _sentence

KIND = "dictated_number_missing"
FLAG = "RR_DICTATED_NUMBERS"


def enabled() -> bool:
    """Off unless RR_DICTATED_NUMBERS is 1/true/on (read per call)."""
    return os.environ.get(FLAG, "0").strip().lower() in ("1", "true", "on")


_PER = r"\s*(?:/|per)\s*"
_KG = r"(?:kg|kilograms?)"
_SQ = r"(?:2|²|\^2)"
# (pattern, normalised unit), most specific first; matched case-insensitively right after a number or chain
_UNITS = [
    (rf"(?:mcg|µg|μg|ug|micrograms?){_PER}{_KG}{_PER}min(?:ute)?s?", "mcg/kg/min"),
    (rf"(?:mg|milligrams?){_PER}{_KG}", "mg/kg"),
    (rf"mmol{_PER}{_KG}", "mmol/kg"),
    (rf"(?:ml|millilit(?:re|er)s?){_PER}{_KG}", "ml/kg"),
    (rf"(?:ml|millilit(?:re|er)s?){_PER}m{_SQ}", "ml/m2"),
    (rf"(?:g|grams?){_PER}m{_SQ}", "g/m2"),
    (rf"(?:ml|millilit(?:re|er)s?){_PER}s(?:ec(?:ond)?)?", "ml/s"),
    (rf"(?:l|lit(?:re|er)s?){_PER}min(?:ute)?", "l/min"),
    (rf"cm{_PER}s(?:ec(?:ond)?)?", "cm/s"),
    (rf"m{_PER}s(?:ec(?:ond)?)?", "m/s"),
    (rf"mmol{_PER}l", "mmol/l"),
    (r"mgy\s*[·.\-*×⋅]?\s*cm", "mgycm"),
    (r"mgy", "mgy"),
    (r"msv", "msv"),
    (r"mm\s*hg", "mmhg"),
    (rf"beats{_PER}min(?:ute)?|bpm", "bpm"),
    (rf"(?:mm|millimet(?:re|er)s?){_SQ}{_PER}s(?:ec(?:ond)?)?", "mm2/s"),
    (rf"(?:mm|millimet(?:re|er)s?){_SQ}|sq(?:uare)?\s*mm", "mm2"),
    (rf"(?:cm|centimet(?:re|er)s?){_SQ}|sq(?:uare)?\s*cm", "cm2"),
    (r"(?:cm|centimet(?:re|er)s?)(?:3|³)|cc|ml|millilit(?:re|er)s?", "ml"),
    (r"millimet(?:re|er)s?|mm", "mm"),
    (r"centimet(?:re|er)s?|cm", "cm"),
    (r"lit(?:re|er)s?", "l"),
    (r"micrograms?|mcg|µg|μg|ug", "mcg"),
    (r"milligrams?|mg", "mg"),
    (r"kilograms?|kg", "kg"),
    (r"grams?|g", "g"),
    (r"mmol", "mmol"),
    (r"milliseconds?|msecs?|ms", "ms"),
    (r"seconds?|secs?|s", "s"),
    (r"%|per\s*cent|percent", "%"),
    (r"minutes?|mins?", "min"),
    (r"hours?|hrs?|h", "h"),
    (r"days?", "day"),
    (r"weeks?|wks?", "week"),
    (r"months?", "month"),
    (r"years?|yrs?", "year"),
    (r"hu", "hu"),
    (r"degrees?|°", "deg"),
    (r"tesla|t", "t"),
]
_UNIT_RX = [(re.compile(rf"(?i)[\s-]*(?:{p})(?![a-z0-9])"), n) for p, n in _UNITS]
_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
_NUM_RX = re.compile(_NUM)
_START = re.compile(rf"(?:(?<![\w.])|(?<=\d[x×])){_NUM}")
_LINK = re.compile(r"(?i)\s*(?:(to)|x|×|by|-|–|—|/)\s*")
_COMMA_DEC = re.compile(r",(\d{1,2})(?![\d,])")             # "1,5" (kept only when a unit follows the chain)
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻−", "0123456789--")
# "x 10-3", "x10^-3", "×10⁻³", "* 10^3": a power of ten belongs to the number before it
_EXP = re.compile(r"\s*[x×*]\s*10\s*(?:\^\s*([-−⁻]?\s*\d{1,2})|([-−]\d{1,2})|(⁻?[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,2}))(?![\d.])")
_MINUS = re.compile(r"(?i)\bminus\s+\Z")
_SIGN_AFTER = re.compile(r"(?i)[-−](?=\d)|minus\s+")
_FOLLOW_UP = re.compile(r"(\d{1,2})\s*/\s*(12|52)(?![\d/]|[.,]\d)")   # UK "3/12" = 3 months, "6/52" = 6 weeks
_REF_MASKS = [   # numbers that are not findings
    re.compile(r"(?i)\b(?:series|image|img|se|im)\s*(?:no\.?|number|#)?\s*:?\s*\d+(?:\s*/\s*\d+)?\b"),
    re.compile(r"\(\s*\d+\s*/\s*\d+\s*\)"),                                     # "(3/45)" image reference
]
_YEAR = re.compile(r"(?i)\b(?:since|in|from)\s+((?:19|20)\d{2})\b(?![.,]\d)")
_WORD_NUMS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
              "seventeen eighteen nineteen twenty").split()
_WORD_RX = re.compile(rf"(?i)\b({'|'.join(_WORD_NUMS)})\b")
_COVER_CUE = re.compile(r"(?i)\b(?:both|each|bilateral(?:ly)?|all)\b")
_COUNT_BEFORE = re.compile(rf"(?i)(?:\b(?:{'|'.join(_WORD_NUMS[2:])})|(?<![\w.])\d+)\s+\Z")   # "two 4 mm nodules"
_ORDINALS = ("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
             "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth").split()
_ORDINAL_RX = re.compile(rf"(?i)\b({'|'.join(_ORDINALS)})\b")
_ROMAN = {r: i + 1 for i, r in enumerate("I II III IV V VI VII VIII IX X XI XII".split())}
# upper case only, an optional subtype suffix ("IIF", "IVa"); "IV contrast" is intravenous
_ROMAN_RX = re.compile(r"\b(XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)(?:[A-F]|[ab])?\b"
                       r"(?!\s+(?:contrast|access|cannula|line|injection|administration|fluids?|drug)\b)")
_ROMAN_CUE = re.compile(r"(?i)\b(?:segments?|grade|stage|class|type|category|level|tier|bosniak|zone|phase|lobe)"
                        r"\s+(?:and\s+|or\s+)?\Z")   # a one-letter numeral ("I", "V", "X") needs one of these


@dataclass(frozen=True)
class Num:
    value: float
    unit: Optional[str]
    text: str      # the whole chain as written, unit included ("2.3 x 1.8 cm")
    start: int     # where the chain starts


def _f(s: str) -> float:
    return float(f"{float(s.replace(',', '')):.10g}")


def _unit_at(text: str, pos: int):
    for rx, name in _UNIT_RX:
        m = rx.match(text, pos)
        if m:
            return name, m.end()
    return None, pos


def _value_at(scan: str, text: str, pos: int, comma: bool):
    """(value, end, used a comma decimal) for the number at `pos`, its power of ten included, or None."""
    m = _NUM_RX.match(scan, pos)
    if not m:
        return None
    raw, end, used = m.group(0), m.end(), False
    if comma and "," not in raw and "." not in raw and (c := _COMMA_DEC.match(scan, end)):
        raw, end, used = f"{raw}.{c.group(1)}", c.end(), True
    if e := _EXP.match(text, end):
        exp = next(g for g in e.groups() if g).translate(_SUP).replace(" ", "")
        return _f(f"{raw.replace(',', '')}e{exp}"), e.end(), used
    return _f(raw), end, used


def _chain(scan: str, text: str, start: int, comma: bool, negative: bool):
    """([values], end, used a comma decimal) for the chain whose first number starts at `start`."""
    v, end, used = _value_at(scan, text, start, comma)
    values = [-v if negative else v]
    while (link := _LINK.match(scan, end)) is not None:
        p, neg = link.end(), False
        if link.group(1) and (sg := _SIGN_AFTER.match(scan, p)):   # "-20 to -10 HU"; a bare hyphen is a range
            p, neg = sg.end(), True
        nxt = _value_at(scan, text, p, comma)
        if nxt is None:
            break
        values.append(-nxt[0] if neg else nxt[0])
        end, used = nxt[1], used or nxt[2]
    return values, end, used


def _sign_start(scan: str, s: int) -> int:
    """Where a minus sign ("-20", "−20", "minus 20") before the number at `s` starts, else `s`. A hyphen after a
    word or number ("3-5", "T2-") is not a sign: those are links or masked."""
    if s >= 1 and scan[s - 1] in "-−" and (s == 1 or scan[s - 2] in " \t\n(:=,;["):
        return s - 1
    m = _MINUS.search(scan, max(0, s - 12), s)
    return m.start() if m else s


def _scan(text: str) -> str:
    """`text` with identifiers, dates, times, list markers, image references and years after since/in/from blanked."""
    out = _masked(text, set())
    for rx in _REF_MASKS:
        for m in list(rx.finditer(out)):
            out = out[:m.start()] + " " * (m.end() - m.start()) + out[m.end():]
    for m in list(_YEAR.finditer(out)):
        if _unit_at(text, m.end(1))[0] is None:
            out = out[:m.start(1)] + "    " + out[m.end(1):]
    return out


def extract(text: Optional[str]) -> List[Num]:
    """Every digit number in `text`, a chain's unit on each of its numbers. Starts are found on the masked text
    (identifiers, dates, times, list markers, image references, years blanked); chains and units are read from the
    original."""
    text = (text or "").replace("\r\n", "\n")
    scan = _scan(text)
    out: List[Num] = []
    pos = 0
    for m in _START.finditer(scan):
        s = m.start()
        if s < pos:
            continue
        f = _FOLLOW_UP.match(scan, s)
        if f and _unit_at(text, f.end())[0] is None:
            out.append(Num(_f(f.group(1)), "month" if f.group(2) == "12" else "week", text[s:f.end()], s))
            pos = f.end()
            continue
        first = _sign_start(scan, s)
        values, end, used = _chain(scan, text, s, True, first < s)
        unit, uend = _unit_at(text, end)
        if used and unit is None:   # "segments 6,7" is a list, not 6.7
            values, end, _ = _chain(scan, text, s, False, first < s)
            unit, uend = _unit_at(text, end)
        chain = text[first:uend].strip()
        out += [Num(v, unit, chain, first) for v in values]
        pos = uend
    return out


def missing_dictated_numbers(report: Optional[str], sources: Iterable[Optional[str]]) -> List[dict]:
    """[{"kind", "text", "sentence", "severity": "high", "message", "values"}], one per dictated chain with a value
    the report does not hold. `sources`: the radiologist's own statements only (dictated units, tapped rows, typed
    values); never the history, assumed normals or a removed sentence."""
    try:
        found = extract(report)
        bare = {n.value for n in found}   # what a dictated value without a unit may match
        bare |= {float(_ORDINALS.index(m.group(1).lower()) + 1) for m in _ORDINAL_RX.finditer(report or "")}
        for m in _ROMAN_RX.finditer(report or ""):
            if len(m.group(1)) > 1 or _ROMAN_CUE.search(report, max(0, m.start() - 24), m.start()):
                bare.add(float(_ROMAN[m.group(1)]))
        words = set()   # number words: (value, unit) when a unit follows, else (value, None)
        held: Counter = Counter((n.value, n.unit) for n in found if n.unit)   # report occurrences per (value, unit)
        # Q5: a report value said to cover several ("both kidneys 11 cm", "11 cm each", "two 4 mm nodules") satisfies
        # every dictated occurrence of that (value, unit). A dimension chain ("3 x 5 mm") is not a count.
        covers = {(n.value, n.unit) for n in found if n.unit and (
            _COVER_CUE.search(_sentence(report, n.start)) or _COUNT_BEFORE.search(report, max(0, n.start - 12), n.start))}
        for m in _WORD_RX.finditer(report or ""):
            v = float(_WORD_NUMS.index(m.group(1).lower()))
            u = _unit_at(report, m.end())[0]
            words.add((v, u))
            bare.add(v)
            if u:
                held[(v, u)] += 1
        out: List[dict] = []
        seen: set = set()
        for src in sources:
            if not src:
                continue
            chains: dict = {}
            used: Counter = Counter()   # one-to-one within a source; each source is matched afresh
            for n in extract(src):
                if n.unit is None:
                    ok = n.value in bare
                else:
                    key = (n.value, n.unit)
                    ok = key in covers or used[key] < held[key]
                    used[key] += 1
                c = chains.setdefault((n.start, n.text), [])
                if not ok and n.value not in c:
                    c.append(n.value)
            for (start, text), gone in chains.items():
                if not gone or text.lower() in seen:
                    continue
                seen.add(text.lower())
                out.append({"kind": KIND, "text": text, "sentence": _sentence(src, start), "severity": "high",
                            "message": f"Dictated number not in the report: {text}", "values": gone})
        return out
    except Exception:  # noqa: BLE001 - a flag is never worth a failed report
        return []


__all__ = ["KIND", "FLAG", "Num", "enabled", "extract", "missing_dictated_numbers"]
