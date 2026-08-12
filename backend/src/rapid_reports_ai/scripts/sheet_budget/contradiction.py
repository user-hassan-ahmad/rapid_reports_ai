"""Semantic contradiction detector.

Two existing layers both miss this failure:

  - the structural gate matches six hand-written regex pairs, so it only finds
    contradiction modes someone already thought of;
  - rubric v2.2's `unwarranted_assertion` dimension is meant to cover "normals
    that contradict a dictated positive" and scored 5/5 on a report asserting
    "No pneumatosis intestinalis" over dictated duodenal mural gas.

The rubric dimension fails, plausibly, because it asks several things at once.
This asks one thing, with the terminology-equivalence problem named explicitly.

MEASURED CHARACTERISTICS (labelled corpus of 8, 2026-08-12)
-----------------------------------------------------------
Tuned twice, with opposite failure modes:

  loose remainder exemption   recall 1/2   specificity 4/4
  strict remainder exemption  recall 3/3   specificity 3/5   <- shipped

The strict setting is shipped deliberately. This is a SCREEN, not a verdict:
a false positive costs a few seconds of review, a false negative ships a report
asserting the absence of something the radiologist dictated as present. At
n=8 further prompt tuning would be overfitting to the labelled set, so the
operating point was chosen on the asymmetry of the costs instead.

USE IT AS: a high-recall screen whose flags require review.
DO NOT USE IT AS: an automated pass/fail - at 3/5 specificity it would reject
sound reports. The deterministic regex gate in gate.py remains the hard gate;
this widens coverage to modes nobody hand-wrote a pattern for.
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, Field


class Conflict(BaseModel):
    report_span: str = Field(description="Verbatim span from the report that denies or normalises")
    dictation_span: str = Field(description="Verbatim span from the dictation it conflicts with")
    why: str = Field(description="One sentence: why these concern the same finding or structure")


class ContradictionVerdict(BaseModel):
    conflicts: list[Conflict] = Field(default_factory=list)


PROMPT = """You check radiology reports for exactly one failure mode, and nothing else.

**The failure:** the report asserts the ABSENCE, or the NORMALITY, of a finding or structure that
the dictation reports as PRESENT or ABNORMAL.

Two statements conflict when they concern the same finding or structure, **even when the wording
differs**. A descriptive term and its formal equivalent are the same finding. Judge by what is
being described, not by whether the words match.

**Report a conflict only when the report denies what the dictation asserts.** Do NOT report:

- Negatives about findings the dictation never mentioned. Conventional negatives for unmentioned
  structures are expected and correct.
- Statements that are **themselves** scoped to a remainder — "the remainder of X is unremarkable",
  "the remaining X is normal". Naming the positive and then covering the rest of that structure is
  correct practice, not a contradiction.

  This exemption applies **only to the denying statement itself**. A blanket, unscoped negative is
  not excused because a remainder-scoped sentence appears somewhere else in the report. Judge each
  denying statement on its own wording: if it denies the finding outright, with no remainder or
  residual scoping in that statement, it is a conflict regardless of what other sentences say.
- Findings the report omitted. Omission is not contradiction; it is out of scope here.
- Differences of emphasis, ordering, or wording.

Return each conflict with the verbatim report span, the verbatim dictation span, and one sentence
on why they concern the same thing. Return an empty list when there is no conflict — an empty list
is the expected result for a sound report."""


def check(
    *,
    dictation: str,
    report: str,
    judge: Callable[[str, str], ContradictionVerdict] | None = None,
) -> dict:
    """Return {conflicts: [...], count: int}. `judge` is injectable for tests."""
    case_text = f"## Dictation\n{dictation}\n\n## Report\n{report}"
    verdict = (judge or _default_judge)(PROMPT, case_text)
    return {
        "count": len(verdict.conflicts),
        "conflicts": [c.model_dump() for c in verdict.conflicts],
    }


def _default_judge(prompt: str, case_text: str) -> ContradictionVerdict:
    """Sonnet, same model as the production quality judge. Sync; wrap in a
    thread when calling from inside an event loop."""
    import asyncio

    from ...enhancement_utils import (
        MODEL_CONFIG,
        _get_api_key_for_provider,
        _get_model_provider,
        _run_agent_with_model,
    )

    model = MODEL_CONFIG["QUALITY_JUDGE"]
    api_key = _get_api_key_for_provider(_get_model_provider(model))

    async def _run():
        return await asyncio.wait_for(
            _run_agent_with_model(
                model_name=model,
                output_type=ContradictionVerdict,
                system_prompt=prompt,
                user_prompt=case_text,
                api_key=api_key,
                use_thinking=False,
                model_settings={"temperature": 0.0, "max_tokens": 2000},
            ),
            timeout=90,
        )

    return asyncio.run(_run()).output
