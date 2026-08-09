"""Semantic (LLM-backed) dictation checks — tier 2 of the integrity gate.

Tier 1 (``dictation_integrity``) is deterministic regex: it catches truncation
and dangling measurements with zero cost and zero false positives, and it GATES
generation. This module handles what regex cannot see — laterality
contradictions, measurements that disagree with their descriptor, statements
that contradict each other — which needs a model.

Two deliberate constraints follow from using a model:

1. **Advisory, never gating.** Tier 1 is deterministic, so a flag is a fact and
   blocking on it is fair. A model's judgement is not a fact. Every issue here
   is emitted at ``medium`` severity, which the frontend renders but does not
   gate on. A false positive costs a glance, never a blocked report.

2. **Verbatim spans only.** The model returns the exact text it objects to and
   we locate it ourselves. If the quote is not present character-for-character,
   the issue is dropped rather than approximated — a highlight pointing at the
   wrong words is worse than no highlight, because it teaches the radiologist
   the marks are unreliable.

Cost means this cannot run on every keystroke-idle like tier 1. It is intended
for the natural pauses: when dictation settles, or immediately before generate.
"""
from __future__ import annotations

import inspect
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from .dictation_integrity import IntegrityFlag

# Kinds the model may report. Constrained rather than free-text so the frontend
# can treat them differently later without parsing prose.
SemanticKind = Literal[
    "laterality_conflict",
    "measurement_mismatch",
    "internal_contradiction",
    "unit_anomaly",
]


class SemanticIssue(BaseModel):
    kind: SemanticKind
    quote: str = Field(
        description="The exact substring of the dictation the issue refers to, "
                    "copied character-for-character."
    )
    message: str = Field(description="One sentence a radiologist can act on.")


class SemanticFindings(BaseModel):
    issues: list[SemanticIssue] = Field(default_factory=list)


SEMANTIC_SYSTEM_PROMPT = (
    "You are a consultant radiologist proof-reading a colleague's raw dictation "
    "before it is turned into a report. You are not rewriting it and not "
    "judging style — you are looking only for internal inconsistencies that "
    "would survive into a signed report and mislead a reader.\n"
    "\n"
    "Report only these:\n"
    "- laterality_conflict: left/right, or a side that contradicts the clinical "
    "history or scan type.\n"
    "- measurement_mismatch: a measurement inconsistent with its own descriptor "
    "or with another measurement of the same structure.\n"
    "- internal_contradiction: two statements that cannot both be true. This "
    "includes the common dictation pattern where a finding is negated in one "
    "place and asserted in another — the negation and the assertion often use "
    "different wording for the same thing, and may be separated by several "
    "lines, so compare what each statement means rather than how it is "
    "phrased.\n"
    "- unit_anomaly: a value whose unit or magnitude is implausible for the "
    "structure described.\n"
    "\n"
    "Do NOT report: incomplete or truncated sentences (handled elsewhere), "
    "missing findings, terminology preferences, brevity, absent normals, or "
    "anything you merely think could have been phrased better. Silence is the "
    "correct answer for a clean dictation, and the overwhelming majority of "
    "dictations are clean.\n"
    "\n"
    "For each issue, `quote` MUST be copied verbatim from the dictation — the "
    "exact characters, not a paraphrase and not a reconstruction. An issue "
    "whose quote does not appear in the text will be discarded.\n"
    "\n"
    "A radiologist dictating deliberately in fragments is normal practice, not "
    "an error. When uncertain, report nothing."
)

_MEDIUM = "medium"


async def _default_analyse(
    scan_type: str, clinical_history: str, findings: str
) -> SemanticFindings:
    """Real analyser: one model call via the shared agent runner, on the caller's loop.

    Uses the STRUCTURE_VALIDATOR slot (a fast Cerebras model) rather than the
    judge tier — this runs in a user-facing pause, not an offline batch, so
    latency matters more than depth.
    """
    import asyncio

    from .enhancement_utils import (
        MODEL_CONFIG,
        _get_api_key_for_provider,
        _get_model_provider,
        _run_agent_with_model,
    )

    model = MODEL_CONFIG["STRUCTURE_VALIDATOR"]
    api_key = _get_api_key_for_provider(_get_model_provider(model))

    user_prompt = (
        f"Scan type: {scan_type or '(not given)'}\n"
        f"Clinical history: {clinical_history or '(not given)'}\n\n"
        f"Dictation:\n{findings}"
    )

    result = await asyncio.wait_for(
        _run_agent_with_model(
            model_name=model,
            output_type=SemanticFindings,
            system_prompt=SEMANTIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=False,
            model_settings={"temperature": 0.0, "max_tokens": 800},
        ),
        timeout=20,
    )
    return result.output


def _locate_flags(findings: str, result: SemanticFindings) -> list[IntegrityFlag]:
    """Turn model-reported issues into located advisory flags (pure, no I/O).

    Drops any issue whose quote is not a verbatim substring of ``findings`` — an
    unplaceable flag is worse than none. Uses rfind so a repeated phrase resolves
    to the later (contradicting) restatement.
    """
    flags: list[IntegrityFlag] = []
    for issue in result.issues:
        quote = (issue.quote or "").strip()
        if not quote:
            continue
        start = findings.rfind(quote)
        if start == -1:
            continue  # not verbatim — drop rather than approximate
        flags.append(
            IntegrityFlag(
                kind=issue.kind,
                severity=_MEDIUM,
                excerpt=quote[:60],
                message=issue.message,
                start=start,
                end=start + len(quote),
            )
        )
    return flags


async def check_semantic(
    scan_type: str,
    clinical_history: str,
    findings: str | None,
    *,
    analyse: Optional[Callable[[str, str, str], SemanticFindings]] = None,
) -> list[IntegrityFlag]:
    """Return advisory flags for semantic problems. Empty list means clean.

    ``analyse`` is injected in tests; it defaults to the model-backed analyser
    and may be sync or async. Any failure returns an empty list — a degraded
    check must never block or surface an error to a radiologist mid-dictation.
    """
    if not findings or not findings.strip():
        return []

    try:
        result = (analyse or _default_analyse)(
            scan_type or "", clinical_history or "", findings
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        return []

    return _locate_flags(findings, result)
