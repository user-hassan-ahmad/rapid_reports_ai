"""The one writer (template pipeline spec, block 1): example reports -> grammar sheet, vetted by the save function.
The grammar analyser writes the sheet directly (writer lab arm D). Creation and any future rebuild use this call."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from . import template_sheet_lab_prompts as P
from .template_sheet_model import model_call
from .template_sheet_save import vet_sheet

logger = logging.getLogger(__name__)

ANALYSER_VERSION = "grammar-analyser-2026-10-13"


async def write_sheet(examples: List[Dict[str, str]], scan_type: str, protocol_notes: str = "",
                      decisions: Optional[List[dict]] = None) -> Dict:
    """{"skill_sheet", "summary", "questions", "dropped", "notice", "analyser_version", "decisions",
    "ledger_drift"} (notice: the save function's report of a reworded unit, "" when none). `decisions`: the Rules
    step's ledger, applied by the save function after the write (ledger_drift counts the lines it had to
    overwrite). Raises ValueError with the save function's message when it refuses the sheet."""
    decided = bool(decisions)
    raw = await model_call(P.analyser_system_prompt(decided),
                           P.writer_user_prompt(examples, scan_type, protocol_notes, decisions=decisions),
                           P.DECIDED_WRITER_SETTINGS if decided else P.ANALYSER_SETTINGS)
    ans = P.split_answer(raw)
    v = await vet_sheet(ans["skill_sheet"] or "", origin="analyser", ledger=decisions or None)
    if v.status != "saved":
        raise ValueError(v.message or "The template could not be written, try again")
    if decisions:
        logger.info("[writer] decisions=%d drift=%d unmatched=%d", len(decisions), v.ledger_drift,
                    len(v.ledger_unmatched))
    summary = ans.get("summary")
    questions = ans.get("questions")
    return {"skill_sheet": v.sheet, "summary": summary if isinstance(summary, dict) else {},
            "questions": questions if isinstance(questions, list) else [], "dropped": v.dropped,
            "notice": v.message, "analyser_version": ANALYSER_VERSION,
            "decisions": v.ledger if decisions else [], "ledger_drift": v.ledger_drift}
