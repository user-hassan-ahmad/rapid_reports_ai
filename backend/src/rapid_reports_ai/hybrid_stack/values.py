"""Required values of a templated scratchpad session (requirements spec 2026-10-12 part 1, the value cluster).

Number -> item (Decision 11, after the second lab): code extracts every number of the dictation (masked: identifiers,
dates, times, bracketed reference text and reference ranges after a reference word), and Jev says, per number, which
required value it gives (jev_stack.ask_number_items). An item one number maps to is filled with that number and its
unit as written; two or more numbers on one item keep the most confident as a "check" chip, the others selectable. An
item no number maps to gets the stated question (jev_stack.ask_values) on the strict bar: stated -> "stated?" chip.
No model writes a number. An open chip carries the dictation's number-bearing clauses as picks. Fail-soft: any Jev
failure leaves every chip open (the radiologist enters the value, picks a clause or marks it N/A); the scratchpad
never blocks on the network."""
from __future__ import annotations

import logging
import re
import time
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from ..template_number_check import _masked
from .jev_stack import VALUE_UNQUOTED_MIN, ask_number_items, ask_values
from .units import sentences

logger = logging.getLogger(__name__)

MAX_ITEMS = 20     # the largest prod LIST_MISSING has 12 items
MAX_NUMBERS = 60   # numbers asked per dictation (a long CMR dictation holds ~30-50); later ones are not asked
MAX_PICKS = 8      # number-bearing clauses offered on an open chip

_REF = re.compile(r"\([^()]*[A-Za-z][^()]*\)")         # bracketed text with a word: a reference range
_N = r"\d+(?:[.,]\d+)?"
# A reference range or limit after a reference word: "normal 891-1035", "normal range: 891 to 1035", "normal (891-1035)",
# "normal value <24" (the lab's main distractor: range ends mapped to an item)
_REF_RANGE = re.compile(rf"(?i)\b(?:normal|reference|ref|range|nr|uln)\b(?:\s*(?:range|values?|limits?|of|is|:|=|\())*"
                        rf"\s*(?:[<>≤≥]\s*{_N}|{_N}\s*(?:-|–|—|to)\s*{_N})")
_CLAUSE = re.compile(r"(?<!\d)[;,]|[;,](?!\d)")       # a comma or semicolon, except inside a number ("1,050")
_NUMBER = re.compile(r"(?:(?<![^\s(])[-−+])?(?<![\w.,^])\d+(?:,\d{3})*(?:\.\d+)?")   # a sign only at a word start
_UNIT = re.compile(r"\s*(%|per ?cent\b|(?:mm ?Hg|[cm]m(?:2|²|\^2)|mls|mL|ml|g|kg|L|l|mm|cm|msec|ms|s|m|cc|HU|bpm)"
                   r"(?:/(?:m\^?2|m²|min|s|m|beat))?(?![A-Za-z0-9²]))")


def clauses(dictation: str) -> list[str]:
    """The dictation's sentences, each split at its commas and semicolons (never inside a number)."""
    out: list[str] = []
    for s in sentences(dictation or ""):
        out += [c.strip() for c in _CLAUSE.split(s) if c.strip()]
    return out


def _numbers(clause: str) -> list[re.Match]:
    """Number tokens, after list markers, identifiers (T2, L4/5), dates, times, bracketed words with their numbers
    ("(normal 55)") and reference ranges after a reference word ("normal range 891-1035") are blanked (same length)."""
    blank = lambda m: " " * len(m.group(0))  # noqa: E731
    return list(_NUMBER.finditer(_REF_RANGE.sub(blank, _REF.sub(blank, _masked(clause or "", set())))))


def has_number(clause: str) -> bool:
    return bool(_numbers(clause))


_AREA = re.compile(r"([cm]m)(?:2|\^2|²)")


def _unit_after(clause: str, m: re.Match) -> Optional[str]:
    """The unit written right after a number, normalised ("%", "mmHg", "cm²"), else None."""
    u = _UNIT.match(clause, m.end())
    if not u:
        return None
    unit = u.group(1)
    if unit.replace(" ", "") == "mmHg":
        return "mmHg"
    if unit.replace(" ", "").lower() in ("%", "percent"):
        return "%"
    return _AREA.sub(r"\1²", unit)


def _with_unit(number: str, unit: Optional[str]) -> str:
    return number if not unit else number + ("%" if unit == "%" else f" {unit}")


def read_value(clause: str) -> Optional[str]:
    """The clause's one number with its unit as written ("45%", "98 ml/m2", area as "20 cm²"); None for no number, two
    or a range."""
    found = _numbers(clause)
    if len(found) != 1:
        return None
    return _with_unit(found[0].group(0), _unit_after(clause, found[0]))


def read_numbers(clause: str) -> list[str]:
    """Every number of the clause with its unit, for the radiologist to pick one. A number without its own unit takes
    the next unit written after it, a shared trailing unit ("98 and 40 ml/m2", "45-50%"); a unit never carries forward
    ("45% and 98" gives "98")."""
    found = _numbers(clause)
    units = [_unit_after(clause, m) for m in found]
    out: list[str] = []
    for i, m in enumerate(found):
        unit = units[i] or next((u for u in units[i + 1:] if u), None)
        out.append(_with_unit(m.group(0), unit))
    return out


class Mention(BaseModel):
    """One number of the dictation: as asked (commas dropped), with its unit, its clause, and its sentence with the
    number marked [[ ]]."""
    number: str
    value: str
    clause: str
    marked: str


def number_mentions(dictation: str) -> list[Mention]:
    """Every number of the dictation in order (the lab's extraction): per sentence, per clause, `_numbers` masking."""
    out: list[Mention] = []
    for s in sentences(dictation or ""):
        cur = 0
        for c in [c.strip() for c in _CLAUSE.split(s) if c.strip()]:
            off = s.find(c, cur)
            off = off if off >= 0 else cur
            cur = off + len(c)
            for m, value in zip(_numbers(c), read_numbers(c)):
                pos = off + m.start()
                out.append(Mention(number=m.group(0).replace(",", ""), value=value, clause=c,
                                   marked=s[:pos] + "[[" + m.group(0) + "]]" + s[pos + len(m.group(0)):]))
    return out


class ClausePick(BaseModel):
    """A number-bearing clause of the dictation the radiologist can tap to fill a chip."""
    clause: str
    value: Optional[str] = None                        # its one number with unit
    numbers: list[str] = Field(default_factory=list)   # two or more numbers: each selectable


def pick(clause: str) -> ClausePick:
    value = read_value(clause)
    return ClausePick(clause=clause, value=value, numbers=[] if value else read_numbers(clause))


class ValueFill(BaseModel):
    item: str
    state: Literal["filled", "check", "open"] = "open"
    value: Optional[str] = None      # the number Jev mapped here, with its unit (check: the most confident)
    quote: Optional[str] = None      # its clause (None with filled: stated, no number -> "stated?" chip)
    score: Optional[float] = None    # the number's confidence, or P(stated) for an item no number maps to
    picks: list[ClausePick] = Field(default_factory=list)   # open: number clauses; check: the numbers mapped here


class ValuesResult(BaseModel):
    values: list[ValueFill] = Field(default_factory=list)
    ms: int = 0
    error: Optional[str] = None


Ask = Callable[[str, list[str], list[str]], Awaitable[list[tuple]]]   # the stated question: (p, k, ...) per item
AskNumbers = Callable[[str, list[tuple[str, str]], list[str]], Awaitable[list[tuple[Optional[int], float]]]]


async def smart_fill(dictation: str, items: list[str], ask: Optional[Ask] = None,
                     ask_numbers: Optional[AskNumbers] = None) -> ValuesResult:
    """Each required value filled from the dictation, a check chip, or open. Never raises; a Jev failure leaves every
    chip open with the error recorded."""
    t0 = time.perf_counter()
    items = [i for i in items if i.strip()][:MAX_ITEMS]
    cands: list[str] = []

    def done(values: list[ValueFill], error: Optional[str] = None) -> ValuesResult:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.log(logging.WARNING if error else logging.INFO,
                   "[stack.values] items=%d filled=%d valued=%d check=%d error=%s ms=%d", len(items),
                   sum(v.state == "filled" for v in values), sum(v.value is not None for v in values),
                   sum(v.state == "check" for v in values), error, ms)
        return ValuesResult(values=values, ms=ms, error=error)

    def opened(item: str, score: Optional[float] = None) -> ValueFill:
        return ValueFill(item=item, score=score, picks=[pick(c) for c in cands[:MAX_PICKS]])

    if not items or not (dictation or "").strip():
        return done([opened(i) for i in items])
    cands = [c for c in clauses(dictation) if has_number(c)]
    mentions = number_mentions(dictation)[:MAX_NUMBERS]
    try:
        mapped = await (ask_numbers or ask_number_items)(dictation, [(m.number, m.marked) for m in mentions], items) \
            if mentions else []
        if len(mapped) != len(mentions):
            return done([opened(i) for i in items], "jev: answer count mismatch")
        by_item: dict[int, list[tuple[float, Mention]]] = {}
        for m, (i, conf) in zip(mentions, mapped):
            if i is not None and 0 <= i < len(items):
                by_item.setdefault(i, []).append((conf, m))
        rest = [k for k in range(len(items)) if k not in by_item]
        stated = await (ask or ask_values)(dictation, [items[k] for k in rest], []) if rest else []
        if len(stated) != len(rest):
            return done([opened(i) for i in items], "jev: answer count mismatch")
    except Exception as e:  # noqa: BLE001 -- fail-soft: every chip open, the radiologist fills or marks N/A
        return done([opened(i) for i in items], f"{type(e).__name__}: {e}"[:200])
    p_stated = {k: float(a[0]) for k, a in zip(rest, stated)}
    out: list[ValueFill] = []
    for k, item in enumerate(items):
        if k in by_item:
            ranked = sorted(by_item[k], key=lambda x: -x[0])   # stable: equal confidence keeps dictation order
            conf, best = ranked[0]
            if len(ranked) == 1:
                out.append(ValueFill(item=item, state="filled", value=best.value, quote=best.clause,
                                     score=round(conf, 3)))
            else:
                out.append(ValueFill(item=item, state="check", value=best.value, quote=best.clause,
                                     score=round(conf, 3),
                                     picks=[ClausePick(clause=m.clause, value=m.value) for _, m in ranked]))
        elif p_stated[k] >= VALUE_UNQUOTED_MIN:
            out.append(ValueFill(item=item, state="filled", score=round(p_stated[k], 3)))   # "stated?": needs a look
        else:
            out.append(opened(item, round(p_stated[k], 3)))
    return done(out)
