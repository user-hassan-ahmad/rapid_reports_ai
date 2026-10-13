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
from .template_sheet_checks import MULTI_STRUCTURE, NOT_NORMAL, PLACEHOLDER, UnitFailure, check_units

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


def reworded_notice(n: int) -> str:
    """An automatic write's notice when the repair reworded units (a drop is reported in `dropped` instead)."""
    return f"Saved, with {n} statement{'s' if n != 1 else ''} reworded so the template stays consistent."
# A unit check's reason in the radiologist's language (a chat refusal is shown to them; the sheet never is).
REASON_TEXT = {
    PLACEHOLDER: "a normal statement can't contain a value to fill in",
    NOT_NORMAL: "it describes an abnormality, so it can't be a normal statement",
    MULTI_STRUCTURE: "a normal statement should cover one structure",
}


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


def _errors(res, errors, fails: List[UnitFailure]) -> List[dict]:
    errs = [dataclasses.asdict(e) for e in errors]
    if not errors and not _usable(res, errors):
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


def _ws(sheet: str) -> str:
    """The sheet with spacing normalised: blank lines dropped, runs of whitespace in a line collapsed."""
    return "\n".join(" ".join(ln.split()) for ln in sheet.splitlines() if ln.strip())


# Old lint errors are matched by (text, reason), not line number, so they survive edits that shift lines. A copied
# erroneous line therefore also passes as "old"; the sheet is unusable at generation either way (any lint error).
def _err_key(e) -> tuple:
    return (e.text.strip(), e.reason)


def _usable(res, errors) -> bool:
    """Usable, or unusable only through lint errors the previous sheet already had (a second structure block is
    itself a lint error, so the rest of the grammar's usable test is the findings and impression roles)."""
    if res.structure.usable:
        return True
    roles = {s.role for s in res.structure.sections}
    return bool(res.errors) and not errors and "findings" in roles and "impression" in roles


async def _parse_and_check(sheet: str, existing: Set[str] = frozenset(), old_errors: Set[tuple] = frozenset()):
    """Parse and check the sheet, keeping only what this write adds or changes: unit failures whose unit the previous
    sheet already had, and lint errors the previous sheet already had, are not the editor's and are left alone."""
    res = tsg.parse_sheet(sheet, mode="template")
    errors = [e for e in res.errors if _err_key(e) not in old_errors]
    fails = await check_units(res.structure, sheet) if _usable(res, errors) else []
    fails = [f for f in fails if norm_key(f.text) not in existing]
    return res, errors, fails


async def vet_sheet(sheet: str, origin: Origin, previous: str = "") -> VetOutcome:
    """Vet a sheet before it is stored. `previous` is the stored sheet ("" for a new template).

    Only what this write adds or changes is checked: a unit the previous grammar sheet already had, or a lint error
    it already had, is neither judged, repaired, dropped nor refused (it is not the editor's doing)."""
    if previous and _ws(sheet) == _ws(previous):
        return VetOutcome("unchanged", previous)
    if not tsg.is_grammar_sheet(sheet):
        return _refuse(previous, LOST_STRUCTURE)
    requested = sheet
    old_grammar = bool(previous) and tsg.is_grammar_sheet(previous)
    existing = _unit_texts(previous) if old_grammar else set()
    old_errors = {_err_key(e) for e in tsg.parse_sheet(previous, mode="template").errors} if old_grammar else set()
    dropped: List[DroppedUnit] = []
    try:
        res, errors, fails = await _parse_and_check(sheet, existing, old_errors)
        if errors or not _usable(res, errors) or fails:
            # the repair may fix only the new failing units: every other unit must survive it
            keep = _unit_texts(sheet) - {norm_key(f.text) for f in fails}
            sheet = await _repair(sheet, _errors(res, errors, fails))
            if not tsg.is_grammar_sheet(sheet):
                return _refuse(previous, UNREADABLE)
            if keep - _unit_texts(sheet):
                logger.warning("[sheet-save] %s refused: repair removed %s", origin, sorted(keep - _unit_texts(sheet)))
                return _refuse(previous, UNSAFE)
            res, errors, fails = await _parse_and_check(sheet, existing, old_errors)
            if origin in AUTOMATIC and any(tsg.is_voice_error(e) for e in errors):
                sheet, dropped = _drop_voice_lines(sheet, errors)
                logger.info("[sheet-save] %s dropped %d voice line(s): %s", origin, len(dropped), dropped)
                res, errors, fails = await _parse_and_check(sheet, existing, old_errors)
    except Exception as e:  # a check or repair that could not run never lets an unchecked sheet through
        logger.warning("[sheet-save] %s refused: %s: %s", origin, type(e).__name__, str(e)[:200])
        return _refuse(previous, "The template could not be checked just now. Please try again.")
    if errors or not _usable(res, errors):
        return _refuse(previous, UNREADABLE)
    if fails:
        failed = {f.text for f in fails}
        failed_keys = {norm_key(t) for t in failed}
        if origin not in AUTOMATIC:
            pairs = dict.fromkeys(f'"{f.text}" ({REASON_TEXT.get(f.reason, f.reason)})' for f in fails)
            return _refuse(previous, f"Couldn't apply: {'; '.join(pairs)}.")
        sheet = _drop_lines(sheet, failed)
        if _unit_texts(sheet) & failed_keys:
            logger.warning("[sheet-save] %s refused: failing unit(s) survived the drop", origin)
            return _refuse(previous, UNSAFE)
        dropped += [DroppedUnit(text=f.text, reason=f.reason) for f in fails]
        logger.info("[sheet-save] %s dropped %d unit(s): %s", origin, len(fails), dropped[-len(fails):])
        res = tsg.parse_sheet(sheet, mode="template")
        errors = [e for e in res.errors if _err_key(e) not in old_errors]
        if errors or not _usable(res, errors):
            return _refuse(previous, UNREADABLE)
    coverage = [s.name for s in sorted(res.structure.sections, key=lambda s: s.order)]
    if origin in AUTOMATIC:
        # a repair that rewrote a unit (e.g. stripped the slots from a NORMAL line) is reported, never silent
        reworded = _unit_texts(sheet) - _unit_texts(requested)
        notice = reworded_notice(len(reworded)) if reworded else ""
        if reworded:
            logger.info("[sheet-save] %s reworded %d unit(s)", origin, len(reworded))
    else:
        notice = ADJUSTED if _shape(sheet) != _shape(requested) else ""
    return VetOutcome("saved", sheet, message=notice, dropped=dropped, coverage_sections=coverage)
