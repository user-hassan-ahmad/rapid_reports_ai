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


# ============================================================================
# Rubric v2 — recalibrated to the system's design (global_style_guide.py):
#   the report is DESIGNED to add skill-sheet-sanctioned normals for un-dictated
#   structures; the dictation is the source of truth for all factual content.
#   So faithfulness splits into:
#     - dictation_fidelity: dictated content preserved exactly (strict)
#     - normal_fill_appropriateness: added normals are sanctioned + in-scope
#   sheet_fit is retired (not comparable across pipelines). The judge is given
#   the skill sheet so it can tell a sanctioned normal from a fabrication.
# ============================================================================
RUBRIC_VERSION_V2 = "v2.1"
DIMENSIONS_V2 = ("output_adherence", "dictation_fidelity", "normal_fill_appropriateness")

# v2.1 OA prompt: same role/dimension, plus a clause telling the judge to use the
# dictation (now provided) to tell "model dropped a mandated item" from "dictation
# didn't supply input for a conditional item". v2 (Haiku) saw only sheet + report
# and could not make this distinction → over-penalised undictated conditionals.
OUTPUT_ADHERENCE_PROMPT_V2 = OUTPUT_ADHERENCE_PROMPT + (
    "\n\nThe dictation is also provided so you can distinguish two cases:\n"
    "- A sheet item that is ALWAYS REQUIRED (mandatory negative, mandatory structural section): "
    "absence in the report is a real omission and lowers the score.\n"
    "- A sheet item that is CONDITIONAL on a finding (e.g. characterise X if present, measure Y if abnormal): "
    "if the dictation provides no basis for the conditional, the report not addressing it is NOT an omission."
)

DICTATION_FIDELITY_PROMPT = (
    "# Role\n"
    "You verify that a generated report preserves the radiologist's DICTATED findings without corruption.\n\n"
    "# What you are given\n"
    "The dictation (the radiologist's source-of-truth observations — clinical history and dictated findings), "
    "the skill sheet (which defines sanctioned conventional normal statements and any reference-value "
    "thresholds), and the report.\n\n"
    "# Dimension: dictation fidelity\n"
    "This measures ONLY the fidelity of DICTATED content. Two additions are EXPECTED and must NOT be penalised:\n"
    "1. Conventional normal/negative statements sanctioned by the skill sheet for structures the radiologist "
    "did not dictate (the system's job).\n"
    "2. A diagnosis or interpretation that a radiologist would reasonably draw FROM a dictated finding — "
    "grounded diagnostic synthesis, where a dictated descriptive finding directly supports the stated reading. "
    "The system is DESIGNED to synthesise findings into diagnoses; reward grounded synthesis, do not score it "
    "as fabrication.\n\n"
    "Penalise ONLY genuine corruption of dictated content, most heavily first:\n"
    "- altering any dictated value, unit, laterality, severity, or qualifier (e.g. presenting a dictated "
    "absolute value as a derived/indexed one, or attaching a qualifier the dictation did not give);\n"
    "- fabricating a reference value or threshold the skill sheet does not define, or borrowing a qualifier "
    "from a different parameter;\n"
    "- introducing a NEW positive observation with no basis in any dictated finding (an invented finding — as "
    "distinct from a grounded interpretation OF a dictated finding), or any claim that CONTRADICTS the dictation;\n"
    "- dropping a finding the dictation provided;\n"
    "- asserting normality that contradicts a dictated positive.\n\n"
    "Score 1 (dictated content materially corrupted, safety-relevant) to 5 (every dictated finding preserved "
    "exactly, with only grounded synthesis and sanctioned normals added). Give a one-sentence rationale and "
    "list verbatim offending spans."
)

NORMAL_FILL_PROMPT = (
    "# Role\n"
    "You assess whether the report's ADDED normal statements (those not from the dictation) are appropriate.\n\n"
    "# What you are given\n"
    "The dictation, the skill sheet (which defines which normal/negative statements are conventional for this "
    "template and the structures in scope), and the report.\n\n"
    "# Dimension: normal-fill appropriateness\n"
    "The report is DESIGNED to pad un-dictated structures with conventional normal statements — reward "
    "appropriate, skill-sheet-sanctioned normal-filling. Penalise ONLY:\n"
    "- normal/negative statements not sanctioned by the skill sheet's conventions (invented boilerplate);\n"
    "- asserting a structure or region is normal when it falls OUTSIDE the study's actual scope (a "
    "complete-looking but unsupported assertion about something not examined);\n"
    "- fabricated reference ranges presented to imply normality or abnormality.\n\n"
    "Score 1 (pervasive unsanctioned or out-of-scope normal-filling) to 5 (all added normals are conventional "
    "and in scope). Give a one-sentence rationale and list verbatim offending spans."
)

_PROMPTS_V2 = {
    "output_adherence": OUTPUT_ADHERENCE_PROMPT_V2,
    "dictation_fidelity": DICTATION_FIDELITY_PROMPT,
    "normal_fill_appropriateness": NORMAL_FILL_PROMPT,
}

# ============================================================================
# RUBRIC v2.2 — split normal-fill into two questions
#
#   v2.1's normal_fill_appropriateness conflated:
#     (a) "is this a plausible normal for this scan type?"  -> genuinely ~5.0
#     (b) "did we put words in the radiologist's mouth?"    -> never measured
#
#   It sat at 4.92/5.0 while human review of the same reports found real
#   defects: a cervical-spine normal on a vertex-to-skull-base head CT, clear
#   basal cisterns asserted beside a dictated 3mm midline shift, and negatives
#   about structures the radiologist never indicated they had reviewed. A
#   dimension that scores near-ceiling while those pass is not measuring them.
#
#   v2.2 keeps (a) as normal_fill_appropriateness, narrowed to conventionality
#   alone, and adds unwarranted_assertion for (b). Every filled normal is a
#   statement the signing radiologist implicitly certifies; that deserves its
#   own number.
#
#   Storage: unwarranted_assertion has no DB column — it lives in
#   dimensions_json, which already carries per-dimension detail. No migration.
# ============================================================================
RUBRIC_VERSION_V22 = "v2.2"
RUBRIC_VERSION_CURRENT = RUBRIC_VERSION_V22
DIMENSIONS_V22 = DIMENSIONS_V2 + ("unwarranted_assertion",)

# Narrowed: the out-of-scope clause moves to unwarranted_assertion. Scoring the
# same defect in both dimensions would double-penalise it and defeat the split.
NORMAL_FILL_PROMPT_V22 = (
    "# Role\n"
    "You assess whether the report's ADDED normal statements (those not from the dictation) follow "
    "this study's reporting conventions.\n\n"
    "# What you are given\n"
    "The dictation, the skill sheet (which defines which normal/negative statements are conventional for "
    "this template), and the report.\n\n"
    "# Dimension: normal-fill conventionality\n"
    "The report is DESIGNED to pad un-dictated structures with conventional normal statements — reward "
    "appropriate, skill-sheet-sanctioned normal-filling. This dimension judges CONVENTIONALITY ONLY: "
    "whether an added normal is phrased and placed the way a consultant would for this study type.\n\n"
    "Penalise ONLY:\n"
    "- normal/negative statements not sanctioned by the skill sheet's conventions (invented boilerplate);\n"
    "- normal statements phrased in a way a consultant would not use for this study;\n"
    "- fabricated reference ranges presented to imply normality or abnormality.\n\n"
    "Do NOT penalise here whether an assertion was WARRANTED by the evidence — that is judged separately. "
    "A normal line can be perfectly conventional and still unwarranted; score only the convention.\n\n"
    "Score 1 (pervasive unsanctioned or unconventional normal-filling) to 5 (all added normals are "
    "conventional). Give a one-sentence rationale and list verbatim offending spans."
)

UNWARRANTED_ASSERTION_PROMPT = (
    "# Role\n"
    "You find statements the report asserts as verified that the study or the dictation does not support.\n\n"
    "# What you are given\n"
    "The dictation, the skill sheet (which declares the study's imaged volume, in-scope structures, and "
    "the companion findings associated with each pathology), and the report.\n\n"
    "# Dimension: unwarranted assertion\n"
    "Every normal statement in a report is a claim the signing radiologist certifies. This dimension asks "
    "one question: does the report state as checked-and-normal anything that was not, or could not have "
    "been, checked?\n\n"
    "Penalise, most heavily first:\n"
    "- ASSERTIONS OUTSIDE THE IMAGED VOLUME: a normal statement about a region the skill sheet's declared "
    "imaged volume does not contain. A study cannot evaluate what it did not cover, however conventional "
    "the phrasing. Regions conventionally co-acquired with this study are NOT in the volume unless the "
    "volume contains them.\n"
    "- ASSERTIONS THAT CONTRADICT A DICTATED FINDING: stating a structure is clear or normal when a "
    "dictated positive implicates it — for example, the skill sheet's companion matrix names it as a "
    "secondary effect or complication of a finding the radiologist reported. Such a normal asserts as "
    "settled something the dictation puts in question.\n"
    "- UNSOLICITED CERTIFICATION: negatives beyond the skill sheet's mandatory and conventional set, about "
    "structures the radiologist did not indicate they reviewed. A mandatory negative that answers the "
    "clinical question is warranted and must NOT be penalised; a volunteered negative about an unrelated "
    "structure is the report putting words in the radiologist's mouth.\n\n"
    "Do NOT penalise conventional, in-volume, uncontradicted normal-filling — that is the system working "
    "as designed and is scored elsewhere.\n\n"
    "Score 1 (multiple unwarranted assertions, at least one safety-relevant) to 5 (every assertion is "
    "within the imaged volume, consistent with the dictation, and earned). Give a one-sentence rationale "
    "and list verbatim offending spans.\n\n"
    "SCORE AND EVIDENCE MUST AGREE. If you list no offending spans, the score is 5. Never deduct on a "
    "general impression without naming the span you object to — an unevidenced deduction is the same "
    "failure this dimension exists to detect."
)

_PROMPTS_V22 = {
    "output_adherence": OUTPUT_ADHERENCE_PROMPT_V2,
    "dictation_fidelity": DICTATION_FIDELITY_PROMPT,
    "normal_fill_appropriateness": NORMAL_FILL_PROMPT_V22,
    "unwarranted_assertion": UNWARRANTED_ASSERTION_PROMPT,
}


def _case_text_v2(dimension: str, case: dict) -> str:
    """v2 case text — always includes the skill sheet so the judge can tell a
    sanctioned normal from a fabrication. v2.1 also gives output_adherence the
    dictation so the judge can distinguish 'model dropped a mandated item' from
    'dictation didn't supply input for a conditional item'."""
    report = case["final_output"] or case["ai_output"]
    inputs, sheet = case["inputs"], case["skill_sheet"]
    if dimension == "output_adherence":
        return (f"## Dictation\n{inputs}\n\n"
                f"## Skill sheet\n{sheet}\n\n"
                f"## Report\n{report}")
    if dimension == "dictation_fidelity":
        return (f"## Dictation (source of truth)\n{inputs}\n\n"
                f"## Skill sheet (defines sanctioned normals & reference values)\n{sheet}\n\n"
                f"## Report\n{report}")
    if dimension == "normal_fill_appropriateness":
        return (f"## Dictation\n{inputs}\n\n"
                f"## Skill sheet (defines conventional normals & scope)\n{sheet}\n\n"
                f"## Report\n{report}")
    if dimension == "unwarranted_assertion":
        # The sheet header is labelled to point the judge at the two fields it
        # must actually consult — the declared imaged volume and the companion
        # matrix — rather than reading it as a style reference.
        return (f"## Dictation (what the radiologist actually reported)\n{inputs}\n\n"
                f"## Skill sheet (declares the imaged volume, in-scope structures, "
                f"and companion findings)\n{sheet}\n\n"
                f"## Report\n{report}")
    raise ValueError(f"unknown v2 dimension: {dimension}")


# --- Case assembly + judging -------------------------------------------------

def _format_input_data(input_data) -> str:
    """Clean dictation text from a report's input_data.

    The dictation fields are nested under ``input_data['variables']`` (CLINICAL_HISTORY,
    SCAN_TYPE, FINDINGS). Earlier this stringified the whole nested dict, which the judge
    mis-read — so this now extracts the dictation as labelled plain text.
    """
    if not isinstance(input_data, dict):
        return ""
    v = input_data.get("variables") if isinstance(input_data.get("variables"), dict) else input_data
    if not isinstance(v, dict):
        return ""
    parts = []
    # Quick reports store scan type at variables.SCAN_TYPE; template reports store
    # it at input_data.extracted_scan_type (top-level). Read both so the judge
    # always sees a scan type — without this template judge calls began with
    # "Clinical history: ..." and the judge had to infer the modality from the sheet.
    scan_type = v.get("SCAN_TYPE") or input_data.get("extracted_scan_type")
    if scan_type:
        parts.append(f"Scan type: {scan_type}")
    if v.get("CLINICAL_HISTORY"):
        parts.append(f"Clinical history: {v['CLINICAL_HISTORY']}")
    if v.get("FINDINGS"):
        parts.append(f"Dictated findings: {v['FINDINGS']}")
    if not parts:  # fallback: any scalar fields
        parts = [f"{k}: {val}" for k, val in v.items() if val and not isinstance(val, (dict, list))]
    return "\n".join(parts)


def _assemble_case(db, report) -> dict:
    """Pull the input / skill-sheet / output / final text for one report.

    ``ai_output`` is always ``report.report_content`` (reliable, same-report).
    ``final`` is only used where it is trustworthy:
      - quick:    ``report.final_report_content`` (stored on the row, same report);
      - template: ``None`` — ``report_feedback.final_output`` is NOT used because the
        global copy-capture can record text from a *different* report (verified:
        a trauma report whose feedback final_output was an unrelated lumbar study).
        Until template edit-capture is fixed, templates have no reliable final, so
        edit_burden is null and the judge assesses ``report_content``.
    """
    ai_output = report.report_content or ""
    inputs = _format_input_data(report.input_data)  # dictation lives here for BOTH pipelines
    if report.report_type == "auto":
        pipeline = "quick"
        ess = report.ephemeral_skill_sheet
        skill_sheet = ess.skill_sheet_markdown if ess else ""
        if not inputs and ess:  # fallback if input_data is sparse
            inputs = f"Scan type: {ess.scan_type}\nClinical history: {ess.clinical_history}"
        final = report.final_report_content
    else:
        pipeline = "template"
        tmpl = report.template
        cfg = (tmpl.template_config or {}) if tmpl and isinstance(tmpl.template_config, dict) else {}
        skill_sheet = cfg.get("skill_sheet") or ""
        final = None  # report_feedback.final_output is unreliable (cross-report copy capture)
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
    """Real judge: one model call per dimension via the shared agent runner.

    Hardened for unattended batch use: a per-call timeout (so a hung provider
    request can't stall the whole batch) and a short retry on transient errors.
    """
    import asyncio
    import time as _time
    from .enhancement_utils import (
        MODEL_CONFIG, _get_model_provider, _get_api_key_for_provider, _run_agent_with_model,
    )

    model = MODEL_CONFIG["QUALITY_JUDGE"]
    provider = _get_model_provider(model)
    api_key = _get_api_key_for_provider(provider)

    async def _run():
        return await asyncio.wait_for(
            _run_agent_with_model(
                model_name=model, output_type=JudgeScore,
                system_prompt=prompt, user_prompt=case_text, api_key=api_key,
                use_thinking=False, model_settings={"temperature": 0.0, "max_tokens": 1500},
            ),
            timeout=60,
        )

    last = None
    for attempt in range(3):
        try:
            return asyncio.run(_run()).output
        except Exception as exc:
            last = exc
            if attempt < 2:
                _time.sleep(2.0 * (attempt + 1))
    raise last


# All score columns on the row; score_report sets whichever the rubric produced.
_SCORE_COLUMNS = (
    "sheet_fit", "output_adherence", "input_faithfulness",
    "dictation_fidelity", "normal_fill_appropriateness",
)


def upsert_score(db, *, report_id, pipeline, scores: dict, edit_burden,
                 dimensions: dict, judge_model: str, rubric_version: str = RUBRIC_VERSION_V2):
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
    for col in _SCORE_COLUMNS:
        setattr(row, col, scores.get(col))  # dimensions not in this rubric stay None
    row.edit_burden = edit_burden
    row.dimensions_json = dimensions
    row.judge_model = judge_model
    db.commit()
    return row


def _rubric(version: str):
    """Return (dimensions, prompts, case_text_fn) for a rubric version."""
    if version == RUBRIC_VERSION_V22:
        # v2.2 reuses the v2.1 case text: every dimension needs dictation +
        # skill sheet + report, and unwarranted_assertion needs exactly the
        # same three (imaged volume and companions come from the sheet).
        return DIMENSIONS_V22, _PROMPTS_V22, _case_text_v2
    if version == RUBRIC_VERSION_V2:
        return DIMENSIONS_V2, _PROMPTS_V2, _case_text_v2
    return DIMENSIONS, _PROMPTS, _case_text


def score_report(db, report, *, rescore: bool = False, judge=None,
                 version: str = RUBRIC_VERSION_CURRENT):
    """Score one report on the rubric's dimensions + edit_burden and upsert the row.

    Defaults to rubric v2. ``judge`` is a callable ``(prompt, case_text) -> JudgeScore``
    (injected in tests); defaults to the real model-backed judge.
    """
    from .database.models import ReportQualityScore
    from .enhancement_utils import MODEL_CONFIG

    existing = (
        db.query(ReportQualityScore)
        .filter_by(report_id=report.id, rubric_version=version)
        .one_or_none()
    )
    if existing is not None and not rescore:
        return existing

    judge = judge or _default_judge
    dimensions_set, prompts, case_fn = _rubric(version)
    case = _assemble_case(db, report)
    scores, dimensions = {}, {}
    for dim in dimensions_set:
        js = judge(prompts[dim], case_fn(dim, case))
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
        judge_model=MODEL_CONFIG["QUALITY_JUDGE"], rubric_version=version,
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
