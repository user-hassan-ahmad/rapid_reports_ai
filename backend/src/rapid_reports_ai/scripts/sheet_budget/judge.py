"""Score harness output on rubric v2.2 without a database row.

quality_scoring.score_report() requires an ORM Report; _assemble_case() does
not - it returns a plain dict. Building that dict directly lets the experiment
reuse the production rubric and judge model unchanged.
"""
from __future__ import annotations

from typing import Callable

from ... import quality_scoring as qs


def format_inputs(*, scan_type: str, clinical_history: str, findings: str) -> str:
    """Build the ``inputs`` string in the exact shape production uses.

    Delegates to quality_scoring._format_input_data rather than reproducing its
    formatting, so the two cannot drift. The dictation must be present: the
    judge assesses dictation_fidelity by comparing the report against it, and
    omitting it depresses that dimension uniformly and silently.
    """
    return qs._format_input_data({"variables": {
        "SCAN_TYPE": scan_type,
        "CLINICAL_HISTORY": clinical_history,
        "FINDINGS": findings,
    }})


def build_case(*, inputs: str, skill_sheet: str, report: str) -> dict:
    """Mirror _assemble_case()'s contract for the quick pipeline.

    final_output is None: the harness has no radiologist-edited final, so the
    judge assesses ai_output, which is what _case_text_v2 falls back to.
    """
    return {
        "pipeline": "quick",
        "inputs": inputs or "",
        "skill_sheet": skill_sheet or "",
        "ai_output": report or "",
        "final_output": None,
    }


def score_case(
    *,
    inputs: str,
    skill_sheet: str,
    report: str,
    judge: Callable[[str, str], "qs.JudgeScore"] | None = None,
) -> dict[str, dict]:
    """Score one report across all v2.2 dimensions.

    ``judge`` defaults to the production Sonnet judge. It is sync and calls
    asyncio.run() internally, so callers inside an event loop must dispatch
    this through asyncio.to_thread.
    """
    judge = judge or qs._default_judge
    case = build_case(inputs=inputs, skill_sheet=skill_sheet, report=report)
    out: dict[str, dict] = {}
    for dim in qs.DIMENSIONS_V22:
        prompt = qs._PROMPTS_V22[dim]
        result = judge(prompt, qs._case_text_v2(dim, case))
        out[dim] = {
            "score": result.score,
            "rationale": result.rationale,
            "issues": [i.model_dump() for i in result.issues],
        }
    return out
