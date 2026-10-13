"""Semantic (LLM-backed) dictation checks — tier 2 of the integrity gate.

Tier 1 (``dictation_integrity``) is deterministic regex: it catches truncation
and dangling measurements with zero cost and zero false positives, and it GATES
generation. This module handles what regex cannot see — laterality
contradictions, measurements that disagree with their descriptor, statements
that contradict each other — which needs a model.

garbled_phrase (2026-10-12, live "A tiny non-2 mm calculus": the ASR dropped "obstructing"): lab of 13
garbled and 12 valid-but-unusual dictations, 2 runs: caught 11/13 and 10/13 (baseline prompt 1/13), 0/12
false. Misses were sound-alikes whose meaning stays obvious ("pleural infusion"); every lost-meaning
garble (a prefix on a number) was caught.

Suggestion and blocking (2026-10-12, scratchpad only): a garble carries the words to replace it only when one
reading is certain; it blocks Confirm when it is ambiguous, has no suggestion, or a number, side or negation is in
its words or its suggestion (code backstop, widened after review 2026-10-12: a suggestion with one is withheld);
every conflict kind blocks. Lab before the widening: Lab (13 garbled, 12 clean, 2 runs): caught 13/13, suggestion right 9, empty 3
(all ambiguous), "appendix calculus" for "appendix collie" 1; blocking right 13/13; clean flagged 0/12.
`severity` is unchanged (medium), so the old banner path still never gates on a model flag.

laterality_conflict widened (2026-10-13, live miss: history "medial joint line pain", dictated "lateral meniscus" tear,
nothing flagged): a compartment or side within one structure counts as a side, the scan type's picked side is compared,
and an unexpected but possibly true side is still asked, as a question. Lab (gpt-oss), first a single run on 8 planted
slips, 4 true-but-unexpected sides and 10 consistent cases: old wording 6/8, 2/4, 0/10 false; this wording 7/8, 4/4,
1/10. Round 1 (the same 22 plus 5 consistent cases: 3 correct crossed-anatomy, 2 extra findings; 2 runs): this wording
7/8, 4/4, 1/15 false in both runs, the knee compartment cases caught every run; the one false alarm, stable, is a correct
crossed-anatomy case (one-sided weakness with an opposite-hemisphere lesion). A "like with like" rule (compare with the
same structure's side, not a symptom's) cleared it but asked 0/4 unexpected sides and lost the live miss in both runs,
so it was not kept. Every laterality_conflict blocks Confirm.

Two deliberate constraints follow from using a model:

1. **Blocks Confirm in the scratchpad, never generation elsewhere.** Every
   conflict (sides, measurements, contradictions, units) and every garble that
   could change the report sets ``blocking``: the scratchpad holds Confirm until
   the radiologist answers or dismisses it, because a wrong side or number would
   survive into the signed report. A certain garble is advisory. ``severity``
   stays ``medium``, so the older banner path (which gates on ``high``, tier 1)
   still never gates on a model flag. A false positive costs one dismissal.

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
import re
from typing import Callable, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, model_validator

from .dictation_integrity import IntegrityFlag

# Kinds the model may report. Constrained rather than free-text so the frontend
# can treat them differently later without parsing prose.
SemanticKind = Literal[
    "laterality_conflict",
    "measurement_mismatch",
    "internal_contradiction",
    "unit_anomaly",
    "garbled_phrase",
]


class SemanticIssue(BaseModel):
    # gpt-oss sometimes names the field "type" (lab 2026-10-12): accepted rather than failing the whole check.
    kind: SemanticKind = Field(validation_alias=AliasChoices("kind", "type"))
    quote: str = Field(
        description="The exact substring of the dictation the issue refers to, "
                    "copied character-for-character."
    )
    other_quote: str = Field(
        default="",
        description="For a conflict between two statements: the exact substring of the "
                    "other statement, copied character-for-character. Empty otherwise."
    )
    message: str = Field(description="Never empty: one sentence a radiologist can act on, saying what is wrong and, "
                                     "for a conflict, which statement the rest of the dictation supports.")
    suggestion: str = Field(
        default="",
        description="garbled_phrase only: the words to replace `quote` with, only when one reading is certain "
                    "(changes_meaning false). Empty otherwise."
    )
    changes_meaning: bool = Field(
        default=False,
        description="garbled_phrase only: true when the garbled words could stand for findings that mean "
                    "different things, a word seems missing, or it sits on a number, side or negation."
    )


    @model_validator(mode="before")
    @classmethod
    def _tolerate_missing_message(cls, v):
        # Required in the schema so the model writes it (the hover card's "why"); a reply without one is still used.
        if isinstance(v, dict) and not v.get("message"):
            v = {**v, "message": ""}
        return v


class SemanticFindings(BaseModel):
    issues: list[SemanticIssue] = Field(default_factory=list)


SEMANTIC_SYSTEM_PROMPT = (
    "You are a consultant radiologist proof-reading a colleague's raw dictation "
    "before it is turned into a report. You are not rewriting it and not "
    "judging style — you are looking only for internal inconsistencies that "
    "would survive into a signed report and mislead a reader.\n"
    "\n"
    "Report only these:\n"
    "- laterality_conflict: a side that contradicts another side in the "
    "dictation, the clinical history or the scan type. A side is left or "
    "right, and also a compartment or part within one structure where it "
    "denotes a side of that structure (medial or lateral, anterior or "
    "posterior, superior or inferior, upper or lower, inner or outer, or a "
    "named pole, lobe, limb or quadrant). The scan type may carry the side "
    "picked for the examination; a dictated side that differs from it is a "
    "conflict. The history may state a side or point to one; compare the side "
    "each finding is on with the side the history or scan type gives. Ask "
    "even when the dictated side may be true: an unexpected side is the "
    "radiologist's to confirm. Write `message` as a question naming both "
    "sides, never as a statement that one is wrong. Not a conflict: a "
    "matching side, bilateral findings, a side neither the history nor the "
    "scan type gives, a side word that is part of a structure's name, or a "
    "statement that the other side or another compartment is normal.\n"
    "- measurement_mismatch: a measurement inconsistent with its own descriptor "
    "or with another measurement of the same structure.\n"
    "- internal_contradiction: two statements that cannot both be true. This "
    "includes the common dictation pattern where a finding is negated in one "
    "place and asserted in another — the negation and the assertion often use "
    "different wording for the same thing, and may be separated by several "
    "lines, so compare what each statement means rather than how it is "
    "phrased.\n"
    "- garbled_phrase: words that read as a speech-to-text error and change or "
    "obscure what a finding says: a word that makes no sense in its position, a "
    "term broken into sound-alike words, a sound-alike word that is not a real "
    "finding or structure here, or a prefix or negation left attached to the "
    "wrong word (for example to a number). Quote only the garbled words. Not "
    "unusual but valid terminology, named signs, classifications, abbreviations "
    "or a deliberate fragment.\n"
    "- unit_anomaly: a value whose unit or magnitude is implausible for the "
    "structure described.\n"
    "\n"
    "Do NOT report: spelling or wording slips that leave the meaning clear, "
    "incomplete or truncated sentences (handled elsewhere), "
    "missing findings, terminology preferences, brevity, absent normals, or "
    "anything you merely think could have been phrased better. Silence is the "
    "correct answer for a clean dictation, and the overwhelming majority of "
    "dictations are clean.\n"
    "\n"
    "For garbled_phrase only, also decide whether the intended words are "
    "certain. `changes_meaning` is false when only one reading fits the "
    "sentence (a sound-alike or split term of one clear term, such as a "
    "misheard structure name); it is true when the garbled words could stand "
    "for findings that mean different things (a misheard word that sounds "
    "like more than one term that fits the sentence), a word seems to be "
    "missing or only part of a longer term is clear, or "
    "the garble sits on a number, side or negation. `suggestion` is the words "
    "to replace the quote, given only when `changes_meaning` is false; "
    "otherwise leave it empty: never pick between readings, and never supply "
    "a number, side or negation the dictation does not give.\n"
    "\n"
    "Always write `message`: one short sentence saying what is wrong and, for "
    "a conflict, which statement the rest of the dictation supports (the "
    "radiologist corrects it from that reason).\n"
    "\n"
    "When the issue is a conflict between two statements, `quote` is the later one "
    "and `other_quote` is the earlier one it conflicts with; otherwise leave "
    "`other_quote` empty.\n"
    "\n"
    "For each issue, `quote` MUST be copied verbatim from the dictation — the "
    "exact characters, not a paraphrase and not a reconstruction. An issue "
    "whose quote does not appear in the text will be discarded.\n"
    "\n"
    "A radiologist dictating deliberately in fragments is normal practice, not "
    "an error. When uncertain, report nothing."
)

_MEDIUM = "medium"
# A number, side or negation in the garbled words or in the suggestion: never a one-click suggestion, always blocking
# ("Non 4 mm" -> "No 4 mm", "write kidney" -> "right kidney", "for mm" -> "4 mm", "Know free" -> "No free").
_BACKSTOP = re.compile(r"\d|\b(?:left|right|bilateral|no|not|non|without)\b", re.I)


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

    user_prompt = (
        f"Scan type: {scan_type or '(not given)'}\n"
        f"Clinical history: {clinical_history or '(not given)'}\n\n"
        f"Dictation:\n{findings}"
    )

    async def _run(model: str) -> SemanticFindings:
        result = await asyncio.wait_for(
            _run_agent_with_model(
                model_name=model,
                output_type=SemanticFindings,
                system_prompt=SEMANTIC_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                api_key=_get_api_key_for_provider(_get_model_provider(model)),
                use_thinking=False,
                # 800 ran out while reasoning over a whole dictation (live 2026-10-12: "token limit exceeded before any
                # response", so the check returned nothing and no underline showed).
                model_settings={"temperature": 0.0, "max_tokens": 4000},
            ),
            timeout=20,
        )
        return result.output

    try:
        return await _run(MODEL_CONFIG["STRUCTURE_VALIDATOR"])
    except Exception:
        # Cerebras rate limit or any failure: the same model on Groq (STRUCTURE_VALIDATOR_FALLBACK, gpt-oss-120b).
        return await _run(MODEL_CONFIG["STRUCTURE_VALIDATOR_FALLBACK"])


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
        other = (issue.other_quote or "").strip()
        o = findings.find(other) if other else -1  # the earlier statement: first occurrence
        garbled = issue.kind == "garbled_phrase"
        backstop = bool(_BACKSTOP.search(f"{quote} {issue.suggestion or ''}"))
        flags.append(
            IntegrityFlag(
                kind=issue.kind,
                suggestion=(issue.suggestion or "").strip() if garbled and not issue.changes_meaning and not backstop else "",
                # Every conflict holds Confirm; a garble only when it could change the report. Code backstop: a
                # number, side or negation in the words or the suggestion always blocks, whatever the model said.
                blocking=not garbled or issue.changes_meaning or not (issue.suggestion or "").strip()
                or backstop,
                severity=_MEDIUM,
                excerpt=quote[:60],
                message=issue.message,
                start=start,
                end=start + len(quote),
                related_start=o if o != -1 and o != start else None,
                related_end=o + len(other) if o != -1 and o != start else None,
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
