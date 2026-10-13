"""Required values of a templated scratchpad session (requirements spec 2026-10-12 part 1, the value cluster).

Jev decides which of the template's LIST_MISSING items the dictation states, and which clause states each
(jev_stack.ask_values); code reads the number from that clause. No model writes a number. A clause with no number,
two numbers or a range gives no value: the chip shows the item as stated. Fail-soft: any Jev failure leaves every
chip open (the radiologist enters the value or marks it N/A); the scratchpad never blocks on the network."""
from __future__ import annotations

import re
from typing import Optional

from ..template_number_check import _masked
from .units import sentences

_CLAUSE = re.compile(r"(?<!\d)[;,]|[;,](?!\d)")       # a comma or semicolon, except inside a number ("1,050")
_NUMBER = re.compile(r"(?<![\w.,^])\d+(?:,\d{3})*(?:\.\d+)?")
_UNIT = re.compile(r"\s*(%|per ?cent\b|(?:mL|ml|g|kg|L|l|mm|cm|ms|s|m|cc|HU|mmHg|bpm)"
                   r"(?:/(?:m\^?2|m²|min|s|m|beat))?(?![A-Za-z0-9²]))")


def clauses(dictation: str) -> list[str]:
    """The dictation's sentences, each split at its commas and semicolons (never inside a number)."""
    out: list[str] = []
    for s in sentences(dictation or ""):
        out += [c.strip() for c in _CLAUSE.split(s) if c.strip()]
    return out


def _numbers(clause: str) -> list[re.Match]:
    """Number tokens, after list markers, identifiers (T2, L4/5), dates and times are blanked (same length)."""
    return list(_NUMBER.finditer(_masked(clause or "", set())))


def has_number(clause: str) -> bool:
    return bool(_numbers(clause))


def read_value(clause: str) -> Optional[str]:
    """The clause's one number with its unit as written ("45%", "98 ml/m2"); None for no number, two or a range."""
    found = _numbers(clause)
    if len(found) != 1:
        return None
    m = found[0]
    u = _UNIT.match(clause, m.end())
    if not u:
        return m.group(0)
    unit = u.group(1)
    return m.group(0) + ("%" if unit.replace(" ", "").lower() in ("%", "percent") else f" {unit}")
