"""Quality scoring for skill-sheet-driven reports.

Two kinds of signal:
- objective ``compute_edit_burden`` — how much the radiologist changed the AI draft
  (pure, no model call);
- LLM-judged rubric scores (sheet fit / output adherence / input faithfulness) — added
  in later tasks.

Scores are persisted to ``report_quality_scores`` and read by Metabase.
"""
from __future__ import annotations

import difflib
from typing import Optional

RUBRIC_VERSION = "v1"


def compute_edit_burden(ai_text: str, final_text: Optional[str]) -> Optional[float]:
    """Normalised edit distance between the AI draft and the radiologist's final text.

    Returns 0.0 when identical, approaching 1.0 as the final diverges, and ``None``
    when there is no final text to compare against (signal simply absent).
    """
    if not final_text:
        return None
    ratio = difflib.SequenceMatcher(None, ai_text or "", final_text).ratio()
    return round(1.0 - ratio, 4)
