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

_PROMPTS = {
    "sheet_fit": SHEET_FIT_PROMPT,
    "output_adherence": OUTPUT_ADHERENCE_PROMPT,
    "input_faithfulness": INPUT_FAITHFULNESS_PROMPT,
}


# --- Case assembly + judging -------------------------------------------------

def _format_input_data(input_data) -> str:
    if not input_data or not isinstance(input_data, dict):
        return ""
    return "\n".join(f"{k}: {v}" for k, v in input_data.items() if v)


def _assemble_case(db, report) -> dict:
    """Pull the input / skill-sheet / output / final text for one report."""
    from .database.models import ReportFeedback  # local: avoid import cost when unused

    ai_output = report.report_content or ""
    if report.report_type == "auto":
        pipeline = "quick"
        ess = report.ephemeral_skill_sheet
        inputs = (
            f"Scan type: {ess.scan_type}\nClinical history: {ess.clinical_history}"
            if ess else ""
        )
        skill_sheet = ess.skill_sheet_markdown if ess else ""
        final = report.final_report_content
    else:
        pipeline = "template"
        tmpl = report.template
        cfg = (tmpl.template_config or {}) if tmpl else {}
        inputs = _format_input_data(report.input_data)
        skill_sheet = cfg.get("skill_sheet") if isinstance(cfg, dict) else None
        if not skill_sheet:
            skill_sheet = str(cfg)
        fb = (
            db.query(ReportFeedback)
            .filter(ReportFeedback.report_id == report.id)
            .order_by(ReportFeedback.updated_at.desc())
            .first()
        )
        final = fb.final_output if fb else None
    return {
        "pipeline": pipeline,
        "inputs": inputs or "",
        "skill_sheet": skill_sheet or "",
        "ai_output": ai_output,
        "final_output": final,
    }


def _case_text(dimension: str, case: dict) -> str:
    output = case["final_output"] or case["ai_output"]
    if dimension == "sheet_fit":
        return f"## Case inputs\n{case['inputs']}\n\n## Skill sheet\n{case['skill_sheet']}"
    if dimension == "output_adherence":
        return f"## Skill sheet\n{case['skill_sheet']}\n\n## Report\n{output}"
    if dimension == "input_faithfulness":
        return f"## Case inputs\n{case['inputs']}\n\n## Report\n{output}"
    raise ValueError(f"unknown dimension: {dimension}")


def _default_judge(prompt: str, case_text: str) -> JudgeScore:
    """Real judge: one model call per dimension via the shared agent runner."""
    import asyncio
    from .enhancement_utils import (
        MODEL_CONFIG, _get_model_provider, _get_api_key_for_provider, _run_agent_with_model,
    )

    model = MODEL_CONFIG["QUALITY_JUDGE"]
    provider = _get_model_provider(model)
    api_key = _get_api_key_for_provider(provider)
    result = asyncio.run(_run_agent_with_model(
        model_name=model,
        output_type=JudgeScore,
        system_prompt=prompt,
        user_prompt=case_text,
        api_key=api_key,
        use_thinking=False,
        model_settings={"temperature": 0.0, "max_tokens": 800},
    ))
    return result.output


def upsert_score(db, *, report_id, pipeline, scores: dict, edit_burden,
                 dimensions: dict, judge_model: str, rubric_version: str = RUBRIC_VERSION):
    """Insert or update the score row for (report_id, rubric_version)."""
    import uuid as _uuid
    from .database.models import ReportQualityScore

    row = (
        db.query(ReportQualityScore)
        .filter_by(report_id=report_id, rubric_version=rubric_version)
        .one_or_none()
    )
    if row is None:
        row = ReportQualityScore(id=_uuid.uuid4(), report_id=report_id,
                                 rubric_version=rubric_version)
        db.add(row)
    row.pipeline = pipeline
    row.sheet_fit = scores.get("sheet_fit")
    row.output_adherence = scores.get("output_adherence")
    row.input_faithfulness = scores.get("input_faithfulness")
    row.edit_burden = edit_burden
    row.dimensions_json = dimensions
    row.judge_model = judge_model
    db.commit()
    return row


def score_report(db, report, *, rescore: bool = False, judge=None):
    """Score one report on all rubric dimensions + edit_burden and upsert the row.

    ``judge`` is a callable ``(prompt, case_text) -> JudgeScore`` (injected in tests);
    defaults to the real model-backed judge.
    """
    from .database.models import ReportQualityScore
    from .enhancement_utils import MODEL_CONFIG

    existing = (
        db.query(ReportQualityScore)
        .filter_by(report_id=report.id, rubric_version=RUBRIC_VERSION)
        .one_or_none()
    )
    if existing is not None and not rescore:
        return existing

    judge = judge or _default_judge
    case = _assemble_case(db, report)
    scores, dimensions = {}, {}
    for dim in DIMENSIONS:
        js = judge(_PROMPTS[dim], _case_text(dim, case))
        scores[dim] = js.score
        dimensions[dim] = {
            "score": js.score,
            "rationale": js.rationale,
            "issues": [i.model_dump() for i in js.issues],
        }
    edit_burden = compute_edit_burden(case["ai_output"], case["final_output"])
    return upsert_score(
        db, report_id=report.id, pipeline=case["pipeline"], scores=scores,
        edit_burden=edit_burden, dimensions=dimensions,
        judge_model=MODEL_CONFIG["QUALITY_JUDGE"],
    )


def compute_edit_burden(ai_text: str, final_text: Optional[str]) -> Optional[float]:
    """Normalised edit distance between the AI draft and the radiologist's final text.

    Returns 0.0 when identical, approaching 1.0 as the final diverges, and ``None``
    when there is no final text to compare against (signal simply absent).
    """
    if not final_text:
        return None
    ratio = difflib.SequenceMatcher(None, ai_text or "", final_text).ratio()
    return round(1.0 - ratio, 4)
