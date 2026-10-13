"""Required values of a templated scratchpad session (requirements spec 2026-10-12 part 1, the value cluster).

Jev decides which of the template's LIST_MISSING items the dictation states, and which clause states each
(jev_stack.ask_values); code reads the number from that clause. No model writes a number. A clause with no number,
two numbers or a range gives no value: the chip shows the item as stated. Fail-soft: any Jev failure leaves every
chip open (the radiologist enters the value or marks it N/A); the scratchpad never blocks on the network."""
from __future__ import annotations

import logging
import re
import time
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from ..template_number_check import _masked
from .jev_stack import VALUE_STATED_MIN, ask_values
from .units import sentences

logger = logging.getLogger(__name__)

MAX_ITEMS = 20     # the largest prod LIST_MISSING has 12 items
MAX_CLAUSES = 80   # numeric clauses offered to the "which clause" question: raised, not windowed (a long CMR dictation
                   # holds ~30-50 numbers); an item whose clause falls past the cap comes back stated without a quote,
                   # which the scratchpad shows as a chip to look at, never as a value

_REF = re.compile(r"\([^()]*[A-Za-z][^()]*\)")         # bracketed text with a word: a reference range
_CLAUSE = re.compile(r"(?<!\d)[;,]|[;,](?!\d)")       # a comma or semicolon, except inside a number ("1,050")
_NUMBER = re.compile(r"(?:(?<![^\s(])[-−+])?(?<![\w.,^])\d+(?:,\d{3})*(?:\.\d+)?")   # a sign only at a word start
_UNIT = re.compile(r"\s*(%|per ?cent\b|(?:mm ?Hg|mls|mL|ml|g|kg|L|l|mm|cm|msec|ms|s|m|cc|HU|bpm)"
                   r"(?:/(?:m\^?2|m²|min|s|m|beat))?(?![A-Za-z0-9²]))")


def clauses(dictation: str) -> list[str]:
    """The dictation's sentences, each split at its commas and semicolons (never inside a number)."""
    out: list[str] = []
    for s in sentences(dictation or ""):
        out += [c.strip() for c in _CLAUSE.split(s) if c.strip()]
    return out


def _numbers(clause: str) -> list[re.Match]:
    """Number tokens, after list markers, identifiers (T2, L4/5), dates, times and bracketed words with their numbers
    ("(normal 55)") are blanked (same length)."""
    return list(_NUMBER.finditer(_REF.sub(lambda m: " " * len(m.group(0)), _masked(clause or "", set()))))


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
    if unit.replace(" ", "") == "mmHg":
        unit = "mmHg"
    return m.group(0) + ("%" if unit.replace(" ", "").lower() in ("%", "percent") else f" {unit}")


class ValueFill(BaseModel):
    item: str
    state: Literal["filled", "open"] = "open"
    value: Optional[str] = None      # code's read; None when filled without one unambiguous number
    quote: Optional[str] = None      # the clause Jev named (None: stated, no clause named -> "check" chip)
    score: Optional[float] = None    # P(stated)


class ValuesResult(BaseModel):
    values: list[ValueFill] = Field(default_factory=list)
    ms: int = 0
    error: Optional[str] = None


Ask = Callable[[str, list[str], list[str]], Awaitable[list[tuple[float, Optional[int]]]]]


async def smart_fill(dictation: str, items: list[str], ask: Optional[Ask] = None) -> ValuesResult:
    """Each required value filled from the dictation or left open. Never raises; a Jev failure leaves every chip
    open with the error recorded."""
    t0 = time.perf_counter()
    items = [i for i in items if i.strip()][:MAX_ITEMS]

    def done(values: list[ValueFill], error: Optional[str] = None) -> ValuesResult:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.log(logging.WARNING if error else logging.INFO,
                   "[stack.values] items=%d filled=%d valued=%d unquoted=%d error=%s ms=%d", len(items),
                   sum(v.state == "filled" for v in values), sum(v.value is not None for v in values),
                   sum(v.state == "filled" and v.quote is None for v in values), error, ms)
        return ValuesResult(values=values, ms=ms, error=error)

    def all_open() -> list[ValueFill]:
        return [ValueFill(item=i) for i in items]

    if not items or not (dictation or "").strip():
        return done(all_open())
    cands = [c for c in clauses(dictation) if has_number(c)][:MAX_CLAUSES]
    try:
        answers = await (ask or ask_values)(dictation, items, cands)
    except Exception as e:  # noqa: BLE001 -- fail-soft: every chip open, the radiologist fills or marks N/A
        return done(all_open(), f"{type(e).__name__}: {e}"[:200])
    if len(answers) != len(items):
        return done(all_open(), "jev: answer count mismatch")
    out: list[ValueFill] = []
    for item, (p, k) in zip(items, answers):
        if p < VALUE_STATED_MIN:
            out.append(ValueFill(item=item, score=round(p, 3)))
            continue
        quote = cands[k] if k is not None and 0 <= k < len(cands) else None
        out.append(ValueFill(item=item, state="filled", value=read_value(quote) if quote else None, quote=quote,
                             score=round(p, 3)))
    return done(out)
