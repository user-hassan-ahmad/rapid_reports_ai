"""Dictated numbers missing from a generated report (spec 2026-10-15, dictated number fidelity step 1).

The reverse of `template_number_check.undictated_numbers`: every number the radiologist dictated must be written in
the report. Code only, both stack paths, review flags only (no repair). A number is digits: an integer, a decimal
(".14" included), a thousands-grouped integer ("1,260"); numbers joined by x, by, -, –, to or / form a chain
("2.3 x 1.8 cm", "50-69%", "132/78 to 118/70 mmHg") and the unit after the chain's last number applies to each.
Number words are not dictated numbers. Identifiers (T2, L4/5, b1000), dates, clock times and list markers are masked
as in `template_number_check`. A dictated value is present when the report holds the same value (float equality:
0.14 = .14, 1.5 != 15) with the same normalised unit or no unit; a dictated value without a unit matches any unit
or, up to twenty, its number word. No unit conversion: 5 mm reported as 0.5 cm is a miss. Never raises.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

from .template_number_check import _masked, _sentence

KIND = "dictated_number_missing"
FLAG = "RR_DICTATED_NUMBERS"


def enabled() -> bool:
    """Off unless RR_DICTATED_NUMBERS is 1/true/on (read per call)."""
    return os.environ.get(FLAG, "0").strip().lower() in ("1", "true", "on")


_PER = r"\s*(?:/|per)\s*"
_SQ = r"(?:2|²|\^2)"
# (pattern, normalised unit), most specific first; matched case-insensitively right after a number or chain
_UNITS = [
    (rf"(?:mcg|µg|μg|ug|micrograms?){_PER}kg{_PER}min(?:ute)?s?", "mcg/kg/min"),
    (rf"(?:mg|milligrams?){_PER}kg", "mg/kg"),
    (rf"mmol{_PER}kg", "mmol/kg"),
    (rf"(?:ml|millilit(?:re|er)s?){_PER}kg", "ml/kg"),
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
_START = re.compile(rf"(?:(?<![\w.])|(?<=\d[x×])){_NUM}")
_LINK = re.compile(rf"(?i)\s*(?:x|×|by|-|–|—|to|/)\s*({_NUM})")
_WORD_NUMS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
              "seventeen eighteen nineteen twenty").split()
_WORD_RX = re.compile(rf"(?i)\b({'|'.join(_WORD_NUMS)})\b")


@dataclass(frozen=True)
class Num:
    value: float
    unit: Optional[str]
    text: str      # the whole chain as written, unit included ("2.3 x 1.8 cm")
    start: int     # where the chain starts


def _f(s: str) -> float:
    return round(float(s.replace(",", "")), 6)


def _unit_at(text: str, pos: int):
    for rx, name in _UNIT_RX:
        m = rx.match(text, pos)
        if m:
            return name, m.end()
    return None, pos


def extract(text: Optional[str]) -> List[Num]:
    """Every digit number in `text`, a chain's unit on each of its numbers. Starts are found on the masked text
    (identifiers, dates, times, list markers blanked); chains and units are read from the original."""
    text = (text or "").replace("\r\n", "\n")
    scan = _masked(text, set())
    out: List[Num] = []
    pos = 0
    for m in _START.finditer(scan):
        if m.start() < pos:
            continue
        values, end = [m.group(0)], m.end()
        while (link := _LINK.match(scan, end)) is not None:
            values.append(link.group(1))
            end = link.end()
        unit, uend = _unit_at(text, end)
        chain = text[m.start():uend].strip()
        out += [Num(_f(v), unit, chain, m.start()) for v in values]
        pos = uend
    return out


def missing_dictated_numbers(report: Optional[str], sources: Iterable[Optional[str]]) -> List[dict]:
    """[{"kind", "text", "sentence", "severity": "high", "message", "values"}], one per dictated chain with a value
    the report does not hold. `sources`: the radiologist's own statements only (dictated units, tapped rows, typed
    values); never the history, assumed normals or a removed sentence."""
    try:
        found = extract(report)
        with_unit = {(n.value, n.unit) for n in found}
        any_unit = {n.value for n in found}
        bare = {n.value for n in found if n.unit is None}
        words = {float(_WORD_NUMS.index(w.lower())) for w in _WORD_RX.findall(report or "")}
        out: List[dict] = []
        seen: set = set()
        for src in sources:
            if not src:
                continue
            chains: dict = {}
            for n in extract(src):
                ok = (n.value in any_unit or n.value in words) if n.unit is None \
                    else ((n.value, n.unit) in with_unit or n.value in bare)
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
