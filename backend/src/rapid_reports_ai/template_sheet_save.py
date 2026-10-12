"""The one path that writes a template's skill sheet (template pipeline spec, block 2). Parse; save-time unit
checks; one repair call; then drop (automatic writes, new units only) or refuse (a user's chat edit, a broken or
reverted sheet, an existing unit an automatic write would lose, a check that could not run).

Why drop vs refuse: a missing normal only leaves the report silent on a structure, while a wrong normal puts a false
statement in it. So an automatic write may drop a NEW bad unit, but never silently drops something the user asked
for (a chat edit is refused instead) or something every report already states (a unit the previous sheet had)."""
from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass, field
from typing import List, Literal

from . import template_sheet_grammar as tsg
from . import template_sheet_lab_prompts as P
from .template_sheet_checks import UnitFailure, check_units

logger = logging.getLogger(__name__)
Origin = Literal["analyser", "repair", "rebuild", "chat", "restore"]
AUTOMATIC = {"analyser", "repair", "rebuild"}

# The quoted unit text of a NORMAL / NEGATIVE line (same quoting as the grammar: straight quotes, no escapes);
# a NORMAL line carries its [structure] label before the quote.
_UNIT_LINE = re.compile(r'^\s*(?:NORMAL\s*\[[^\]]+\]|NEGATIVE)\s*"([^"]+)"')

UNREADABLE = "This change could not be applied: the template would not be readable."


@dataclass
class VetOutcome:
    status: Literal["unchanged", "saved", "refused"]
    sheet: str  # the sheet to store: the vetted one when saved, the previous one otherwise
    message: str = ""
    dropped: List[dict] = field(default_factory=list)
    coverage_sections: List[str] = field(default_factory=list)


def _norm(t: str) -> str:
    return " ".join(t.lower().split()).rstrip(".")


def _unit_texts(sheet: str) -> set:
    st = tsg.parse_sheet(sheet, mode="template").structure
    return {_norm(u.text) for u in [*st.normals, *st.negatives]}


async def _repair(sheet: str, errors: List[dict]) -> str:
    from .scripts.template_sheet_convert import model_call
    out = await model_call(P.REPAIR_SYSTEM_PROMPT, P.repair_user_prompt(sheet, errors), P.REPAIR_SETTINGS)
    return P.strip_fences(out)


def _errors(res, fails: List[UnitFailure]) -> List[dict]:
    errs = [dataclasses.asdict(e) for e in res.errors]
    if not res.errors and not res.structure.usable:
        errs.append({"line": 0, "text": "", "reason": "structure not usable", "detail": ""})
    errs += [{"line": f.line, "text": f.text, "reason": f.reason, "detail": ""} for f in fails]
    return errs


def _drop_lines(sheet: str, texts: set) -> str:
    """The sheet without the NORMAL / NEGATIVE lines whose quoted unit text is one of `texts`."""
    keep = []
    for line in sheet.splitlines():
        m = _UNIT_LINE.match(line)
        if m and m.group(1) in texts:
            continue
        keep.append(line)
    return "\n".join(keep) + ("\n" if sheet.endswith("\n") else "")


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
        return _refuse(previous, "This change could not be applied: the template would lose its structure.")
    try:
        res, fails = await _parse_and_check(sheet)
        if res.errors or not res.structure.usable or fails:
            sheet = await _repair(sheet, _errors(res, fails))
            if not tsg.is_grammar_sheet(sheet):
                return _refuse(previous, UNREADABLE)
            res, fails = await _parse_and_check(sheet)
    except Exception as e:  # a check or repair that could not run never lets an unchecked sheet through
        logger.warning("[sheet-save] %s refused: %s: %s", origin, type(e).__name__, str(e)[:200])
        return _refuse(previous, "The template could not be checked just now. Please try again.")
    if res.errors or not res.structure.usable:
        return _refuse(previous, UNREADABLE)
    dropped: List[dict] = []
    if fails:
        failed = {f.text for f in fails}
        if origin not in AUTOMATIC:
            quoted = "; ".join(f'"{t}"' for t in sorted(failed))
            return _refuse(previous, f"Couldn't apply: {quoted} ({fails[0].reason}).")
        existing = _unit_texts(previous) if previous and tsg.is_grammar_sheet(previous) else set()
        if existing & {_norm(t) for t in failed}:
            return _refuse(previous, "This change would remove a statement every report includes.")
        sheet = _drop_lines(sheet, failed)
        dropped = [{"text": f.text, "reason": f.reason} for f in fails]
        logger.info("[sheet-save] %s dropped %d unit(s): %s", origin, len(fails), dropped)
        res = tsg.parse_sheet(sheet, mode="template")
        if res.errors or not res.structure.usable:
            return _refuse(previous, UNREADABLE)
    coverage = [s.name for s in sorted(res.structure.sections, key=lambda s: s.order)]
    return VetOutcome("saved", sheet, dropped=dropped, coverage_sections=coverage)
