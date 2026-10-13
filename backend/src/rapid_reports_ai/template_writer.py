"""The one writer (template pipeline spec, block 1): example reports -> grammar sheet, vetted by the save function.
The grammar analyser writes the sheet directly (writer lab arm D). Creation and any future rebuild use this call."""
from __future__ import annotations

from typing import Dict, List

from . import template_sheet_lab_prompts as P
from .template_sheet_model import model_call
from .template_sheet_save import vet_sheet

ANALYSER_VERSION = "grammar-analyser-2026-10-13"


async def write_sheet(examples: List[Dict[str, str]], scan_type: str, protocol_notes: str = "") -> Dict:
    """{"skill_sheet", "summary", "questions", "dropped", "notice", "analyser_version"} (notice: the save
    function's report of a reworded unit, "" when none). Raises ValueError with the save
    function's message when it refuses the sheet."""
    raw = await model_call(P.ANALYSER_SYSTEM_PROMPT, P.analyser_user_prompt(examples, scan_type, protocol_notes),
                           P.ANALYSER_SETTINGS)
    ans = P.split_answer(raw)
    v = await vet_sheet(ans["skill_sheet"] or "", origin="analyser")
    if v.status != "saved":
        raise ValueError(v.message or "The template could not be written, try again")
    summary = ans.get("summary")
    questions = ans.get("questions")
    return {"skill_sheet": v.sheet, "summary": summary if isinstance(summary, dict) else {},
            "questions": questions if isinstance(questions, list) else [], "dropped": v.dropped,
            "notice": v.message, "analyser_version": ANALYSER_VERSION}
