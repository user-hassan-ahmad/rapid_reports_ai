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

import asyncio
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

_N = r"\d+(?:[.,]\d+)?"
_REF_WORDS = r"normal|norm|reference|ref|range|nr|rr|uln|lln|upper limit|lower limit"
# Reference text only (the review: a bracket holding any word lost "(maximum 14 mm in the ...)"):
_REF_BRACKET = re.compile(rf"(?i)\(\s*(?:{_REF_WORDS})\b[^()]*\)")              # "(normal 55-70)", "(ref 55%)"
_BARE_RANGE = re.compile(rf"\(\s*{_N}\s*(?:-|–|—|to)\s*{_N}\s*\)")               # "(950-1050)": no unit
# A reference number, limit or range after a reference word: "normal 55", "normal range: 891 to 1035", "normal (a-b)",
# "normal value <24". Kept: "normal" straight before a number with a unit ("LVEF normal 55-60%" is the measurement).
_REF_AFTER = re.compile(rf"(?i)\b(?P<word>{_REF_WORDS})\b(?P<fill>(?:\s*(?:range|values?|limits?|of|is|:|=|\())*)"
                        rf"\s*(?P<num>(?:[<>≤≥]|up\s+to)\s*{_N}|{_N}(?:\s*(?P<rng>-|–|—|to)\s*{_N})?)")
_JOIN = re.compile(r"\s*(?:and|-|–|—|to|x|×|/)\s*", re.I)   # numbers that share a trailing unit
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
    text = _BARE_RANGE.sub(blank, _REF_BRACKET.sub(blank, _masked(clause or "", set())))

    def ref(m: re.Match) -> str:
        """After "normal", only a range, a limit or a range/value word is reference text; a bare number ("normal
        997") or a range with a unit and no such word ("normal 55-60%") is the measurement."""
        if m["word"].lower() != "normal":
            return blank(m)
        worded = re.search(r"(?i)range|value|limit", m["fill"])
        limit = not m["num"][0].isdigit()
        if worded or limit or (m["rng"] and not _unit_at(text, m.end())):
            return blank(m)
        return m.group(0)
    return list(_NUMBER.finditer(_REF_AFTER.sub(ref, text)))


def has_number(clause: str) -> bool:
    return bool(_numbers(clause))


_AREA = re.compile(r"([cm]m)(?:2|\^2|²)")


_VOL = r"(?:mls?|mL|millilit(?:re|er)s?)"
_SQ_M = r"(?:met(?:re|er)s?\s+squared|square\s+met(?:re|er)s?|m\s+squared|m2|m²|m\^2)"
# Spelled-out units, tried before the symbols; each normalised (lab: dictated units read as "ml", "84 ml per metre
# squared" lost its index)
_SPELLED = [(re.compile(rf"\s*{_VOL}\s*(?:per\s+{_SQ_M}|/\s*m\s+squared)(?![A-Za-z0-9])", re.I), "ml/m²"),
            (re.compile(rf"\s*{_VOL}\s*(?:per\s+|/\s*)beat\b", re.I), "ml/beat"),
            (re.compile(r"\s*(?:cm|centimet(?:re|er)s?)\s+squared\b|\s*square\s+centimet(?:re|er)s?\b", re.I), "cm²"),
            (re.compile(r"\s*(?:mm|millimet(?:re|er)s?)\s+squared\b|\s*square\s+millimet(?:re|er)s?\b", re.I), "mm²"),
            (re.compile(r"\s*millimet(?:re|er)s?\b", re.I), "mm"),
            (re.compile(r"\s*centimet(?:re|er)s?\b", re.I), "cm"),
            (re.compile(r"\s*millisec(?:ond)?s?\b", re.I), "ms"),
            (re.compile(r"\s*millilit(?:re|er)s?\b", re.I), "ml"),
            (re.compile(r"\s*per\s*cent\b", re.I), "%")]


def _unit_at(text: str, pos: int) -> Optional[str]:
    """The unit written at `pos` (right after a number), normalised ("%", "mmHg", "cm²", "ml/m²"), else None."""
    for rx, unit in _SPELLED:
        if rx.match(text, pos):
            return unit
    u = _UNIT.match(text, pos)
    if not u:
        return None
    unit = u.group(1)
    if unit.replace(" ", "") == "mmHg":
        return "mmHg"
    if unit.replace(" ", "").lower() in ("%", "percent"):
        return "%"
    return _AREA.sub(r"\1²", unit)


def _unit_after(clause: str, m: re.Match) -> Optional[str]:
    return _unit_at(clause, m.end())


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
    """Every number of the clause with its unit, for the radiologist to pick one. A number without its own unit shares
    the next number's unit only when the two are joined by "and", "-", "to", "x" or "/" ("98 and 40 ml/m2", "45-50%",
    "3 x 4 cm"); never across other words ("87 with normal systolic function of 64%" gives "87")."""
    found = _numbers(clause)
    units = [_unit_after(clause, m) for m in found]
    for i in range(len(found) - 2, -1, -1):
        if not units[i] and _JOIN.fullmatch(clause[found[i].end():found[i + 1].start()]):
            units[i] = units[i + 1]
    return [_with_unit(m.group(0), u) for m, u in zip(found, units)]


class Mention(BaseModel):
    """One number of the dictation: as asked (commas dropped), with its unit, its clause, and its sentence with the
    number marked [[ ]]."""
    number: str
    value: str
    clause: str
    marked: str
    cid: int = 0     # which clause of the dictation
    start: int = 0   # the number's span in its clause
    end: int = 0


def number_mentions(dictation: str) -> list[Mention]:
    """Every number of the dictation in order (the lab's extraction): per sentence, per clause, `_numbers` masking."""
    out: list[Mention] = []
    cid = 0
    for s in sentences(dictation or ""):
        cur = 0
        for c in [c.strip() for c in _CLAUSE.split(s) if c.strip()]:
            cid += 1
            off = s.find(c, cur)
            off = off if off >= 0 else cur
            cur = off + len(c)
            for m, value in zip(_numbers(c), read_numbers(c)):
                pos = off + m.start()
                out.append(Mention(number=m.group(0).replace(",", ""), value=value, clause=c, cid=cid,
                                   start=m.start(), end=m.end(),
                                   marked=s[:pos] + "[[" + m.group(0) + "]]" + s[pos + len(m.group(0)):]))
    return out


_SPAN_JOIN = re.compile(r"\s*(?:x|×|-|–|—|to)\s*", re.I)   # dimensions ("30 x 31 mm") and measured ranges ("30–35%")


def _span(ms: list[Mention]) -> Optional[str]:
    """Numbers of one span (one clause, adjacent, joined by x / - / to) as one value with the last number's unit
    ("30 x 31 mm", "30–35%"); None when they are not one span."""
    ms = sorted(ms, key=lambda m: m.start)
    if len({m.cid for m in ms}) != 1:
        return None
    c = ms[0].clause
    if not all(_SPAN_JOIN.fullmatch(c[a.end:b.start]) for a, b in zip(ms, ms[1:])):
        return None
    last = ms[-1]
    return c[ms[0].start:last.end] + last.value[len(c[last.start:last.end]):]


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
AskNumbers = Callable[[str, list[tuple[str, str]], list[str]], Awaitable[list[tuple]]]   # (item, conf[, P(items)])


async def smart_fill(dictation: str, items: list[str], ask: Optional[Ask] = None,
                     ask_numbers: Optional[AskNumbers] = None) -> ValuesResult:
    """Each required value filled from the dictation, a check chip, or open. The number calls and the stated question
    (every item, answers kept only for items no number maps to) run in parallel. Never raises; a Jev failure leaves
    every chip open with the error recorded."""
    t0 = time.perf_counter()
    items = [i for i in items if i.strip()][:MAX_ITEMS]
    cands: list[str] = []
    p_clause: dict[int, dict[str, float]] = {}   # item -> clause -> best P(item) of its numbers

    def done(values: list[ValueFill], error: Optional[str] = None) -> ValuesResult:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.log(logging.WARNING if error else logging.INFO,
                   "[stack.values] items=%d filled=%d valued=%d check=%d error=%s ms=%d", len(items),
                   sum(v.state == "filled" for v in values), sum(v.value is not None for v in values),
                   sum(v.state == "check" for v in values), error, ms)
        return ValuesResult(values=values, ms=ms, error=error)

    def opened(k: int, score: Optional[float] = None) -> ValueFill:
        """Open, with the number clauses: those whose numbers Jev rates likelier for this item first, then dictation
        order (the numbers' answers went to none or other items)."""
        best = p_clause.get(k, {})
        ranked = sorted(cands, key=lambda c: -best.get(c, 0.0))
        return ValueFill(item=items[k], score=score, picks=[pick(c) for c in ranked[:MAX_PICKS]])

    def all_open(error: Optional[str] = None) -> ValuesResult:
        p_clause.clear()
        return done([opened(k) for k in range(len(items))], error)

    async def fill() -> ValuesResult:
        nonlocal cands
        cands = [c for c in clauses(dictation) if has_number(c)]
        mentions = number_mentions(dictation)[:MAX_NUMBERS]
        # Latency: the stated question (every item) starts with the number calls, so the fill waits for the slowest
        # single call, never their sum; when every item is mapped it is cancelled, not awaited.
        stated_task = asyncio.ensure_future((ask or ask_values)(dictation, items, []))
        stated_task.add_done_callback(lambda t: t.cancelled() or t.exception())   # an unawaited failure is not logged
        try:
            mapped = await (ask_numbers or ask_number_items)(dictation, [(m.number, m.marked) for m in mentions],
                                                             items) if mentions else []
        except BaseException:
            stated_task.cancel()
            raise
        if len(mapped) != len(mentions):
            stated_task.cancel()
            return all_open("jev: answer count mismatch")
        by_item: dict[int, list[tuple[float, Mention]]] = {}
        for m, a in zip(mentions, mapped):
            i, conf = a[0], float(a[1])
            probs = a[2] if len(a) > 2 else None
            if i is not None and 0 <= i < len(items):
                by_item.setdefault(i, []).append((conf, m))
            for k, pk in enumerate(probs or []):
                p_clause.setdefault(k, {})[m.clause] = max(p_clause.get(k, {}).get(m.clause, 0.0), float(pk))
        if len(by_item) == len(items):
            stated_task.cancel()
            stated: list = [(0.0,)] * len(items)
        else:
            stated = await stated_task
            if len(stated) != len(items):
                return all_open("jev: answer count mismatch")
        out: list[ValueFill] = []
        for k, item in enumerate(items):
            if k in by_item:
                ranked = sorted(by_item[k], key=lambda x: -x[0])   # stable: equal confidence keeps dictation order
                conf, best = ranked[0]
                span = _span([m for _, m in ranked]) if len(ranked) > 1 else None
                if span is not None:   # one dimension or measured range ("30 x 31 mm", "30–35%"): one value
                    out.append(ValueFill(item=item, state="filled", value=span, quote=best.clause,
                                         score=round(conf, 3)))
                elif len({_num(m.number) for _, m in ranked}) == 1:   # one number, or the same value twice
                    out.append(ValueFill(item=item, state="filled", value=best.value, quote=best.clause,
                                         score=round(conf, 3)))
                else:
                    out.append(ValueFill(item=item, state="check", value=best.value, quote=best.clause,
                                         score=round(conf, 3),
                                         picks=[ClausePick(clause=m.clause, value=m.value) for _, m in ranked]))
                continue
            p = float(stated[k][0])
            if p >= VALUE_UNQUOTED_MIN:
                out.append(ValueFill(item=item, state="filled", score=round(p, 3)))   # "stated?": needs a look
            else:
                out.append(opened(k, round(p, 3)))
        return done(out)

    if not items or not (dictation or "").strip():
        return all_open()
    try:
        return await fill()
    except Exception as e:  # noqa: BLE001 -- fail-soft: every chip open, the radiologist fills or marks N/A
        return all_open(f"{type(e).__name__}: {e}"[:200])


def _num(n: str) -> float:
    """A number token as a float: a Unicode minus or dash is a minus ("−5"), thousands commas dropped."""
    return float(n.replace("−", "-").replace("–", "-").replace(",", ""))
