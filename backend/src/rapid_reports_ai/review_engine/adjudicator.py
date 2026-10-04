"""Adjudicator (spec §7): Qwen 3.8 27b with reasoning reads the whole case for one candidate group, decides class
and kind, and writes the smallest fix, in one call. Flat schema on purpose (L-50). Retries at temperature 0 repeat
the same output, so the call runs with no pydantic-ai retries and a failure becomes `minor` with no fix, logged.

Prompts (L-51 / L-52): `adjudicator.txt` is Gate A's v4 (coverage and accuracy); `adjudicator_additions.txt` is v4.1,
used when every candidate in the group is from the additions lane. Both are verbatim copies of the lab files."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

from .. import report_reconcile as rc
from ..enhancement_utils import _run_agent_with_model
from .items import Candidate, Edit, ReviewInput, ReviewItem

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "adjudicator.txt"
ADDITIONS_PROMPT_PATH = Path(__file__).parent / "prompts" / "adjudicator_additions.txt"
MODEL = rc.QWEN
SETTINGS = {"temperature": 0, "max_tokens": 16384, "reasoning_effort": "medium"}
RETRIES = 0         # spec §7: retries at T=0 are futile (binding correction 1)
CONCURRENCY = 8     # spec §7: at most 8 concurrent calls per report
GROUP_CAP = 20      # spec §7: above 20 groups the overflow is minor with no fix
ADJ_TIMEOUT_S = 90.0

ErrorKind = Literal["validation", "transport", "overflow"]


class Judgement(BaseModel):            # FLAT on purpose (L-50); any future list field decodes a JSON string
    cls: Literal["action", "minor", "info", "suppress"]
    kind: str
    label: str
    reason: str
    edit_mode: Literal["none", "replace", "insert", "upgrade", "remove"]
    edit_find: Optional[str] = None
    edit_replace: Optional[str] = None
    edit_after: Optional[str] = None
    edit_section: Optional[str] = None
    probe: Optional[str] = None


class Outcome(BaseModel):
    group: List[Candidate]
    judgement: Optional[Judgement] = None
    error: Optional[str] = None
    error_kind: Optional[ErrorKind] = None


def prompt(additions: bool = False) -> str:
    return (ADDITIONS_PROMPT_PATH if additions else PROMPT_PATH).read_text().strip()


def system_prompt_for(group: List[Candidate]) -> str:
    """v4.1 only when every candidate in the group is an additions candidate (L-52); otherwise v4 (L-51)."""
    return prompt(additions=bool(group) and all(c.lane == "additions" for c in group))


# Ported from scripts/review_labs/judgement.py (_KIND_TEXT); coverage_check is the engine's unsure-coverage kind.
KIND_TEXT = {
    "partial": "The report seems to cover this dictated line but leave out part of it.",
    "absent": "The report seems not to cover this dictated line at all.",
    "differs": "The report seems to say something different from this dictated line.",
    "coverage_check": "Whether the report carries this dictated line, as dictated, is unclear.",
    "laterality": "A side in this dictated line seems missing from the report.",
    "contradicted": "The dictation seems to contradict this report statement.",
    "unsupported": "This report statement seems not to be supported by the dictation or history.",
    "overstated": "This report statement seems more certain than the dictation.",
    "misattributed": "A measurement seems attached to a different structure than dictated.",
    "inconsistent": "This report statement seems internally inconsistent (modality wording or size word).",
    "grade": "A guideline classification is named for this finding; check whether every input it needs is stated.",
    "characterise": "A guideline classification is named for this finding; an input it needs may not be described.",
    "threshold": "A guideline threshold may apply to this finding.",
    "follow_up": "The guideline may change the existing recommendation.",
    "option": "A guideline point the radiologist may want to add.",
}

_LAB_EVIDENCE_KEYS = ("system", "grade", "parameter", "threshold", "significance", "modality", "timing", "indication",
                      "text")
# Engine-only evidence (code checks, Task 3) rendered after the lab lines; the lab never produced these keys.
_CHECK_EVIDENCE_KEYS = ("numbers", "dates", "phrase", "dictated", "report", "number", "source_line", "word")


def _present(v) -> bool:
    return v not in (None, "", [])            # grade 0 is a real grade


def render_candidate(c: Candidate) -> str:
    """One candidate as prompt text (ported from the lab). The kind is named explicitly and quoted, so the model
    copies it rather than the lane. An unsure Jev answer is named, never its leaning (§6.5)."""
    lines = [f'- Flag kind "{c.kind}" (from the {c.lane} check, detector {c.detector}). {KIND_TEXT.get(c.kind, "")}']
    if c.line_text:
        lines.append(f'  Dictated line: "{c.line_text}"')
    if c.anchor:
        lines.append(f'  Report statement: "{c.anchor.text}"')
    ev = c.evidence or {}
    if ev.get("jev_unsure"):
        lines.append(f"  The detector question {ev['jev_unsure'].get('question')} was unsure here; read it fresh.")
    if ev.get("missing_detail"):
        lines.append(f"  Possibly missing detail: {ev['missing_detail']}")
    for k in _LAB_EVIDENCE_KEYS:
        if _present(ev.get(k)):
            lines.append(f"  {k}: {ev[k]}")
    if ev.get("criteria"):
        lines.append(f"  Criteria text for this system: {ev['criteria']}")
    # engine-only additions (brief options and code checks)
    if ev.get("upgrade_target"):
        lines.append(f'  Proposed sentence: "{ev.get("sentence")}". The report already covers this structure; '
                     "rewrite that sentence (edit_mode upgrade) rather than adding a second one.")
    elif ev.get("sentence"):
        lines.append(f'  Proposed sentence: "{ev["sentence"]}"')
    for k in _CHECK_EVIDENCE_KEYS:
        if _present(ev.get(k)):
            lines.append(f"  {k}: {ev[k]}")
    return "\n".join(lines)


def user_message(inp: ReviewInput, group: List[Candidate], report: Optional[str] = None) -> str:
    return ("FLAGS (one group, same place in the report):\n" + "\n".join(render_candidate(c) for c in group) +
            f"\n\nSTUDY TITLE: {inp.study_title or inp.scan_type}\n\nCLINICAL HISTORY:\n{inp.clinical_history or '(none)'}"
            f"\n\nDICTATION:\n{inp.artifacts.dictated_findings}\n\nREPORT:\n{report or inp.artifacts.report}")


def needs_judgement(group: List[Candidate]) -> bool:
    """Pre-classed brief options are not judged again (Principle 2), unless the gate was unsure about one."""
    return not all(c.preclassed and not (c.evidence or {}).get("jev_unsure") for c in group)


def _is_brief(group: List[Candidate]) -> bool:
    return any(c.detector == "brief.option" for c in group)


def cap_brief(j: Judgement, group: List[Candidate]) -> Judgement:
    """A brief option may be lowered (to suppress) but never raised to action (spec §6.4, confirmed 2026-10-03)."""
    return j.model_copy(update={"cls": "minor"}) if _is_brief(group) and j.cls == "action" else j


def to_edit(j: Judgement) -> Optional[Edit]:
    if j.edit_mode == "none":
        return None
    return Edit(mode=j.edit_mode, find=j.edit_find or None, replace=j.edit_replace or None,
                after=j.edit_after or None, section=j.edit_section or None)


def fallback(group: List[Candidate]) -> Judgement:
    """minor, no fix, every field filled (binding correction 8)."""
    return Judgement(cls="minor", kind=(group[0].kind if group else None) or "unknown", label="", reason="",
                     edit_mode="none", edit_find=None, edit_replace=None, edit_after=None, edit_section=None,
                     probe=None)


def _error_kind(e: BaseException) -> ErrorKind:
    name = type(e).__name__
    return "validation" if any(t in name for t in ("Validation", "UnexpectedModelBehavior")) else "transport"


def _failed(group: List[Candidate], error: str, kind: ErrorKind) -> Outcome:
    return Outcome(group=group, judgement=fallback(group), error=error, error_kind=kind)


async def judge(inp: ReviewInput, group: List[Candidate], report: Optional[str] = None) -> Outcome:
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=MODEL, output_type=Judgement, system_prompt=system_prompt_for(group),
            user_prompt=user_message(inp, group, report), api_key="", model_settings=dict(SETTINGS),
            retries=RETRIES), ADJ_TIMEOUT_S)
        return Outcome(group=group, judgement=cap_brief(r.output, group))
    except Exception as e:  # noqa: BLE001 - one failed group never fails the run
        logger.warning("review engine: adjudicator failed (%s: %s)", type(e).__name__, str(e)[:200])
        return _failed(group, f"{type(e).__name__}: {str(e)[:200]}", _error_kind(e))


async def adjudicate(inp: ReviewInput, groups: List[List[Candidate]]) -> List[Outcome]:
    sem = asyncio.Semaphore(CONCURRENCY)
    judged = [i for i, g in enumerate(groups) if needs_judgement(g)]
    overflow = set(judged[GROUP_CAP:])
    if overflow:
        logger.warning("review engine: %d group(s) over the cap of %d → minor, no fix", len(overflow), GROUP_CAP)
    judged_set = set(judged)

    async def one(i: int, g: List[Candidate]) -> Outcome:
        if i in overflow:
            return _failed(g, "overflow: over the group cap", "overflow")
        if i not in judged_set:
            return Outcome(group=g)
        async with sem:
            return await judge(inp, g)
    return list(await asyncio.gather(*(one(i, g) for i, g in enumerate(groups))))


async def reprepare(inp: ReviewInput, item: ReviewItem, report: Optional[str] = None) -> Outcome:
    """One call for one item against the current text (spec §10.3, §12.4)."""
    lane = item.lane if item.lane != "chat" else "accuracy"
    cand = Candidate(lane=lane, kind=item.kind, section=item.section, anchor=item.anchor, line_text=item.source_line,
                     evidence={"previous_label": item.label}, detector=(item.detectors or ["reprepare"])[0])
    return await judge(inp, [cand], report)


__all__ = ["Judgement", "Outcome", "prompt", "system_prompt_for", "render_candidate", "user_message",
           "needs_judgement", "cap_brief", "to_edit", "fallback", "judge", "adjudicate", "reprepare"]
