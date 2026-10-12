"""The one path that writes a template's skill sheet (template pipeline spec, block 2). Parse; save-time unit
checks; one repair call; then drop (automatic writes, new units only) or refuse (a user's chat edit, a broken or
reverted sheet, an automatic write whose drop or repair would remove or rewrite a unit the previous sheet had, a
check that could not run).

Why drop vs refuse: a missing normal only leaves the report silent on a structure, while a wrong normal puts a false
statement in it. So an automatic write may drop a NEW bad unit, but never silently drops something the user asked
for (a chat edit is refused instead) or something every report already states.

What is guaranteed: vetting (drop or repair) never removes or rewrites a unit the previous sheet had on an automatic
write, and the repair call never removes or rewrites a unit it was not asked to fix. What is NOT checked here: whether the incoming sheet itself keeps every unit of the previous
one (a new template has no previous; a rebuild may legitimately reword units, a later regression gate covers it).

Voice lines: a prose line under a paragraph (Opening:, Order:, Abnormal pattern: …) is wording, not content. On an
automatic write, such a line that still fails the lint after the one repair is dropped (reported in `dropped`) rather
than refusing the whole sheet; the sheet is then re-parsed and its units checked as usual. A user's edit (chat,
restore) with such a line is refused, and so is any sheet left unusable for another reason."""
from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass, field
from typing import List, Literal, Set, TypedDict

from . import template_sheet_grammar as tsg
from . import template_sheet_lab_prompts as P
from .hybrid_stack.template import norm_key
from .template_sheet_checks import UnitFailure, check_units

logger = logging.getLogger(__name__)
Origin = Literal["analyser", "repair", "rebuild", "chat", "restore"]
AUTOMATIC = {"analyser", "repair", "rebuild"}

# The quoted unit text of a NORMAL / NEGATIVE line (same quoting as the grammar: straight quotes, no escapes);
# a NORMAL line carries its [structure] label before the quote.
_UNIT_LINE = re.compile(r'^\s*(?:NORMAL\s*\[[^\]]+\]|NEGATIVE)\s*"([^"]+)"')

UNREADABLE = "This change could not be applied: the template would not be readable."
UNSAFE = "This change could not be applied safely."
LOST_STRUCTURE = "This change could not be applied: the template would lose its structure."
ADJUSTED = "Applied, with a small adjustment so the template stays consistent."


class DroppedUnit(TypedDict):
    text: str
    reason: str


@dataclass
class VetOutcome:
    status: Literal["unchanged", "saved", "refused"]
    sheet: str  # the sheet to store: the vetted one when saved, the previous one otherwise
    message: str = ""
    dropped: List[DroppedUnit] = field(default_factory=list)
    coverage_sections: List[str] = field(default_factory=list)


def _shape(sheet: str) -> tuple:
    """What a reader of the sheet would notice changed: its unit texts and section names (not spacing)."""
    st = tsg.parse_sheet(sheet, mode="template").structure
    return (sorted(norm_key(u.text) for u in [*st.normals, *st.negatives]), [x.name for x in st.sections])


def _unit_texts(sheet: str) -> Set[str]:
    st = tsg.parse_sheet(sheet, mode="template").structure
    return {norm_key(u.text) for u in [*st.normals, *st.negatives]}


async def _repair(sheet: str, errors: List[dict]) -> str:
    from .template_sheet_model import model_call
    out = await model_call(P.REPAIR_SYSTEM_PROMPT, P.repair_user_prompt(sheet, errors), P.REPAIR_SETTINGS)
    return P.strip_fences(out)


def _errors(res, fails: List[UnitFailure]) -> List[dict]:
    errs = [dataclasses.asdict(e) for e in res.errors]
    if not res.errors and not res.structure.usable:
        errs.append({"line": 0, "text": "", "reason": "structure not usable", "detail": ""})
    errs += [{"line": f.line, "text": f.text, "reason": f.reason, "detail": ""} for f in fails]
    return errs


def _drop_lines(sheet: str, texts: Set[str]) -> str:
    """The sheet without the NORMAL / NEGATIVE lines whose quoted unit text is one of `texts`."""
    keep = []
    for line in sheet.splitlines():
        m = _UNIT_LINE.match(line)
        if m and m.group(1) in texts:
            continue
        keep.append(line)
    return "\n".join(keep) + ("\n" if sheet.endswith("\n") else "")


def _drop_voice_lines(sheet: str, errors) -> tuple:
    """The sheet without the voice lines that carry a lint error (tsg.is_voice_error), and what was dropped."""
    voice = {e.line: e for e in errors if tsg.is_voice_error(e)}
    kept = [line for i, line in enumerate(sheet.splitlines(), 1) if i not in voice]
    out = "\n".join(kept) + ("\n" if sheet.endswith("\n") else "")
    return out, [DroppedUnit(text=e.text, reason=e.reason) for _, e in sorted(voice.items())]


def _refuse(previous: str, message: str) -> VetOutcome:
    return VetOutcome("refused", previous, message)


async def _parse_and_check(sheet: str):
    res = tsg.parse_sheet(sheet, mode="template")
    fails = await check_units(res.structure, sheet) if res.structure.usable else []
    return res, fails


async def vet_sheet(sheet: str, origin: Origin, previous: str = "") -> VetOutcome:
    """Vet a sheet before it is stored. `previous` is the stored sheet ("" for a new template)."""
    if previous and sheet == previous:
        return VetOutcome("unchanged", previous)
    if not tsg.is_grammar_sheet(sheet):
        return _refuse(previous, LOST_STRUCTURE)
    requested = sheet
    existing = _unit_texts(previous) if previous and tsg.is_grammar_sheet(previous) else set()
    dropped: List[DroppedUnit] = []
    try:
        res, fails = await _parse_and_check(sheet)
        if res.errors or not res.structure.usable or fails:
            asked = {norm_key(f.text) for f in fails}
            # units the repair may not remove or rewrite: those it was not asked to fix and, on an automatic write,
            # every unit the previous sheet had (an existing unit that still fails is refused below)
            keep = _unit_texts(sheet) - (asked - existing if origin in AUTOMATIC else asked)
            sheet = await _repair(sheet, _errors(res, fails))
            if not tsg.is_grammar_sheet(sheet):
                return _refuse(previous, UNREADABLE)
            if keep - _unit_texts(sheet):
                logger.warning("[sheet-save] %s refused: repair removed %s", origin, sorted(keep - _unit_texts(sheet)))
                return _refuse(previous, UNSAFE)
            res, fails = await _parse_and_check(sheet)
            if origin in AUTOMATIC and any(tsg.is_voice_error(e) for e in res.errors):
                sheet, dropped = _drop_voice_lines(sheet, res.errors)
                logger.info("[sheet-save] %s dropped %d voice line(s): %s", origin, len(dropped), dropped)
                res, fails = await _parse_and_check(sheet)
    except Exception as e:  # a check or repair that could not run never lets an unchecked sheet through
        logger.warning("[sheet-save] %s refused: %s: %s", origin, type(e).__name__, str(e)[:200])
        return _refuse(previous, "The template could not be checked just now. Please try again.")
    if res.errors or not res.structure.usable:
        return _refuse(previous, UNREADABLE)
    if fails:
        failed = {f.text for f in fails}
        failed_keys = {norm_key(t) for t in failed}
        if origin not in AUTOMATIC:
            pairs = dict.fromkeys(f'"{f.text}" ({f.reason})' for f in fails)  # ordered, de-duplicated
            return _refuse(previous, f"Couldn't apply: {'; '.join(pairs)}.")
        if existing & failed_keys:
            return _refuse(previous, "This change would remove a statement every report includes.")
        sheet = _drop_lines(sheet, failed)
        if _unit_texts(sheet) & failed_keys:
            logger.warning("[sheet-save] %s refused: failing unit(s) survived the drop", origin)
            return _refuse(previous, UNSAFE)
        dropped += [DroppedUnit(text=f.text, reason=f.reason) for f in fails]
        logger.info("[sheet-save] %s dropped %d unit(s): %s", origin, len(fails), dropped[-len(fails):])
        res = tsg.parse_sheet(sheet, mode="template")
        if res.errors or not res.structure.usable:
            return _refuse(previous, UNREADABLE)
    coverage = [s.name for s in sorted(res.structure.sections, key=lambda s: s.order)]
    notice = ADJUSTED if origin not in AUTOMATIC and _shape(sheet) != _shape(requested) else ""
    return VetOutcome("saved", sheet, message=notice, dropped=dropped, coverage_sections=coverage)
