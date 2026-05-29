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

from pydantic import BaseModel, Field

RUBRIC_VERSION = "v1"


# --- Judge output schema -----------------------------------------------------

class JudgeIssue(BaseModel):
    """A specific problem the judge flagged, with the verbatim offending span."""
    span: str = Field(description="Verbatim substring from the material that is problematic")
    note: str = Field(description="Why this span is a problem for the dimension being judged")


class JudgeScore(BaseModel):
    """Structured result for one rubric dimension."""
    score: int = Field(ge=1, le=5, description="1 (poor) to 5 (excellent)")
    rationale: str = Field(description="One sentence justifying the score")
    issues: list[JudgeIssue] = Field(default_factory=list)


# --- Rubric prompts (case-agnostic: structural framing, no single-domain examples) ---

_SCORE_INSTRUCTION = (
    "Score from 1 (poor) to 5 (excellent). Give a one-sentence rationale and a list of "
    "verbatim problem spans (may be empty). Judge ONLY the dimension described; do not reward "
    "or penalise unrelated qualities."
)

SHEET_FIT_PROMPT = (
    "# Role\n"
    "You assess whether a generated review guide ('skill sheet') is well-matched to the case "
    "it was produced for.\n\n"
    "# Dimension: skill-sheet fit\n"
    "Given the case inputs and the skill sheet, judge whether the sheet covers the assessments "
    "the inputs make relevant, in proportion, without irrelevant filler or items unsupported by "
    "the inputs. Breadth and specificity should track what the inputs justify — neither padded "
    "nor sparse.\n\n" + _SCORE_INSTRUCTION
)

OUTPUT_ADHERENCE_PROMPT = (
    "# Role\n"
    "You assess whether a generated report addressed the points raised by its review guide.\n\n"
    "# Dimension: output-to-sheet adherence\n"
    "Given the skill sheet and the report, judge the degree to which the report substantively "
    "addresses the sheet's items — each item either resolved with a definite statement or "
    "appropriately acknowledged. Items the sheet raised but the report ignores lower the score.\n\n"
    + _SCORE_INSTRUCTION
)

INPUT_FAITHFULNESS_PROMPT = (
    "# Role\n"
    "You assess whether a report is faithful to the case inputs it was generated from.\n\n"
    "# Dimension: input faithfulness\n"
    "Given the inputs and the report, judge whether the report introduces no claim absent from or "
    "contradicting the inputs (fabrication), omits no input-stated finding (omission), and preserves "
    "laterality, quantities, and qualifiers exactly. List any violating spans. This is "
    "safety-critical; weight fabrication and laterality/quantity errors most heavily.\n\n"
    + _SCORE_INSTRUCTION
)

# Maps the score-row column -> (prompt, which case fields the judge sees).
DIMENSIONS = ("sheet_fit", "output_adherence", "input_faithfulness")


def compute_edit_burden(ai_text: str, final_text: Optional[str]) -> Optional[float]:
    """Normalised edit distance between the AI draft and the radiologist's final text.

    Returns 0.0 when identical, approaching 1.0 as the final diverges, and ``None``
    when there is no final text to compare against (signal simply absent).
    """
    if not final_text:
        return None
    ratio = difflib.SequenceMatcher(None, ai_text or "", final_text).ratio()
    return round(1.0 - ratio, 4)
