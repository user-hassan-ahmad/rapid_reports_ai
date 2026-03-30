"""
Agentic planning-then-execution report pipeline.

Phase 1  — generate_report_plan():       GLM reasoning ON  → ReportPlan (structured fields)
Phase 1.5 — intent-driven evidence fetch: Perplexity per retrieval_intent (case-conditioned queries)
Phase 2  — execute_report_from_plan():   zai-glm-4.7 (Cerebras, reasoning ON) → ReportOutput
Phase 3  — check_plan_adherence():       Qwen/Groq cross-check output vs plan (optional)

Brief construction: _build_execution_brief() programmatically renders the execution brief
from ReportPlan structured fields — guaranteeing companion/impression fidelity and
eliminating GLM hallucination risk in the brief itself.

run_agentic_pipeline() orchestrates all phases → AgenticReportOutput.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import List, Optional

from .enhancement_utils import (
    _run_agent_with_model,
    _append_signature_to_report,
    _get_model_provider,
    run_perplexity_search_chat,
    MODEL_CONFIG,
)
from .agentic_models import (
    ReportPlan,
    AgenticReportOutput,
    CompanionFinding,
    ImpressionPlan,
    ClinicalContextItem,
    RetrievalIntent,
)
from .enhancement_models import ReportOutput

# ---------------------------------------------------------------------------
# Prompt loading — direct path, bypassing PromptManager (which maps model
# names to existing use-case files; planning.json / execution.json are new).
# ---------------------------------------------------------------------------
_PROMPTS_DIR = Path(__file__).parent / "prompts" / "radiology_report"


def _load_planning_prompt() -> dict:
    with open(_PROMPTS_DIR / "planning.json") as f:
        return json.load(f)


def _load_execution_prompt() -> dict:
    with open(_PROMPTS_DIR / "execution.json") as f:
        return json.load(f)


def _render_template(template: str, variables: dict) -> str:
    """Simple {{KEY}} substitution."""
    for key, value in variables.items():
        template = template.replace(f"{{{{{key}}}}}", value or "")
    return template


# ---------------------------------------------------------------------------
# Programmatic execution brief construction
# ---------------------------------------------------------------------------
# Replaces GLM's free-text execution_brief with a deterministically-rendered
# document built from ReportPlan structured fields. Guarantees:
#   - Companion obligations exactly match companion_findings[] (no drift)
#   - Impression contract lists included_findings / management_altering_negatives only (no sentence_plan)
#   - LIMITATIONS decision is rule-based, not model-generated
#   - excluded_differentials and unexplained_findings always injected
#   - is_normal_scan flag always signalled to execution model
# ---------------------------------------------------------------------------

_HIGH_STAKES_KEYWORDS = {
    "ctpa", "ct pulmonary angiogram", "ct pulmonary angiography",
    "cta", "ct angiogram", "ct angiography", "ct aortogram",
    "ct mesenteric", "ct renal artery", "ct coronary",
    "contrast-enhanced ct", "ce-ct", "post-contrast ct",
    "staging ct", "emergency ct", "trauma ct",
}


def _is_high_stakes(scan_type: str) -> bool:
    s = scan_type.lower()
    return any(kw in s for kw in _HIGH_STAKES_KEYWORDS)


def _render_limitations_handling(scan_type: str) -> str:
    if _is_high_stakes(scan_type):
        return (
            "LIMITATIONS HANDLING\n"
            f"Protocol: {scan_type} — contrast-enhanced/high-stakes study.\n"
            "Document technical adequacy in LIMITATIONS:\n"
            "  - Opacification adequacy (arterial, venous, or organ-specific as appropriate)\n"
            "  - Scan coverage (e.g. thoracic inlet to lung bases)\n"
            "  - Any technical problems (motion, artefact, limited coverage)\n"
            "Paraphrase freshly — do not transcribe this wording into the report."
        )
    return (
        "LIMITATIONS HANDLING\n"
        f"Protocol: {scan_type} — adequacy documentation not required for this protocol type.\n"
        "Write \"None\" in LIMITATIONS unless a specific technical problem needs documenting."
    )


def _render_clinical_conclusion(plan: "ReportPlan") -> str:
    lines = [
        "CLINICAL CONCLUSION",
        f"Primary diagnosis: {plan.primary_diagnosis}",
        f"Clinical question: {plan.clinical_question}",
    ]
    if plan.cross_finding_connections:
        lines.append("\nCausal chain / cross-finding connections:")
        for c in plan.cross_finding_connections:
            lines.append(f"  - {c}")
    if plan.excluded_differentials:
        lines.append("\nExcluded differentials (document in FINDINGS; impression only if clinically warranted):")
        for d in plan.excluded_differentials:
            lines.append(f"  - {d}")
    if plan.unexplained_findings:
        lines.append("\nUnexplained findings — require impression-level flagging and investigation recommendation:")
        for u in plan.unexplained_findings:
            lines.append(f"  - {u}")
    return "\n".join(lines)


def _prose_companion_instruction(
    cf: "CompanionFinding",
    cross_connections: "List[str]",
    placement: str,
) -> str:
    """
    Render a single companion as a prose handover note rather than a structured directive.
    placement: 'primary finding paragraph' | 'appropriate anatomical paragraph'
    """
    name = cf.structure
    detail_clause = f" ({cf.detail})" if cf.detail else ""
    causal = any(name.lower() in conn.lower() for conn in cross_connections)

    if cf.status == "present":
        if causal:
            return (
                f"{name} is confirmed{detail_clause} — document it as a direct consequence of the primary "
                f"finding in the {placement}; a full active-verb clause is required."
            )
        return (
            f"{name} is present{detail_clause} — document it in full in the {placement} "
            f"with a precise active-verb clause."
        )

    if cf.status == "absent":
        return (
            f"{name} is absent — state this explicitly in the {placement}."
        )

    if cf.status == "not_mentioned":
        aetiology = f" Aetiological context: {cf.detail}." if cf.detail else ""
        return (
            f"{name} is not in the input but is assessable on this protocol — "
            f"assess from standard modality norms and state present or absent in the {placement}. "
            f"Do not write 'not assessable on this study'.{aetiology}"
        )

    # not_assessable
    return (
        f"{name} cannot be assessed on this protocol — "
        f"omit entirely, or note as not assessable only if clinically relevant."
    )


def _render_companion_obligations(
    companions: "List[CompanionFinding]",
    cross_connections: "List[str]",
) -> str:
    if not companions:
        return "COMPANION OBLIGATIONS\nNo companions identified for this case."

    cluster = [cf for cf in companions if cf.companion_type == "clinical_cluster"]
    sweep = [cf for cf in companions if cf.companion_type == "systematic_sweep"]

    lines = [
        "COMPANION OBLIGATIONS",
        "Every companion below must appear in FINDINGS. Omission is a clinical error.\n",
    ]

    if cluster:
        lines.append("Clinical cluster — integrate into the primary finding paragraph:")
        for cf in cluster:
            lines.append(
                _prose_companion_instruction(cf, cross_connections, "primary finding paragraph")
            )
        lines.append("")

    if sweep:
        lines.append("Systematic sweep — distribute to the appropriate anatomical paragraph:")
        for cf in sweep:
            lines.append(
                _prose_companion_instruction(cf, cross_connections, "appropriate anatomical paragraph")
            )

    return "\n".join(lines)


def _render_impression_contract(impression_plan: "ImpressionPlan") -> str:
    lines = ["IMPRESSION CONTRACT"]

    if impression_plan.is_normal_scan:
        lines += [
            "NORMAL SCAN.",
            "Write ONE sentence only, answering the clinical question directly.",
            "Do not list excluded differentials. Do not suggest clinical correlation.",
        ]
        return "\n".join(lines)

    if impression_plan.included_findings:
        lines.append("Include in impression:")
        for f in impression_plan.included_findings:
            lines.append(f"  - {f}")

    if impression_plan.management_altering_negatives:
        lines.append(
            "\nManagement-altering negatives — state as clinical conclusions in IMPRESSION "
            "(these directly alter surgical or management decisions; do NOT omit):"
        )
        for n in impression_plan.management_altering_negatives:
            lines.append(f"  - {n}")

    actionable = [r for r in impression_plan.recommendation_decisions if r.recommendation]
    if actionable:
        lines.append("\nRecommendations (radiological remit only — referral, imaging, sampling):")
        for r in actionable:
            lines.append(f"  - {r.finding}: {r.recommendation}")

    if impression_plan.excluded_from_impression:
        lines.append("\nExcluded from impression — FINDINGS only, never in IMPRESSION:")
        for e in impression_plan.excluded_from_impression:
            lines.append(f"  - {e}")

    lines.append(
        "\nSynthesise into a concise impression. Group findings sharing the same management pathway "
        "into one sentence. Routine negatives and normal structures belong in FINDINGS only. "
        "Management-altering negatives listed above ARE impression-worthy — state them as clinical conclusions, "
        "not as imaging descriptions.\n"
        "Integration rule: if a management-altering negative shares the same management pathway as the primary "
        "finding and has no independent recommendation in the RECOMMENDATIONS block above, integrate it into "
        "the primary impression sentence as a semicolon clause — do not write it as a separate sentence.\n"
        "  ❌ 'Acute appendicitis... urgent surgical referral. No perforation or abscess.'\n"
        "  ✅ 'Acute appendicitis; no perforation or abscess; urgent surgical referral advised.'\n"
        "Only write a separate impression sentence for a management-altering negative that carries its own "
        "distinct recommendation not already captured by the primary finding."
    )
    return "\n".join(lines)


def _render_clinical_context(context_items: "List[ClinicalContextItem]") -> str:
    if not context_items:
        return ""
    lines = [
        "CLINICAL CONTEXT NOTES",
        "The following modify impression urgency, differential weighting, or management:",
    ]
    for item in context_items:
        lines.append(f"  - {item.item}: {item.management_impact}")
    return "\n".join(lines)


def _build_execution_brief(plan: "ReportPlan") -> str:
    """
    Programmatically construct the execution brief from structured ReportPlan fields.
    Used by execute_report_from_plan() instead of plan.execution_brief (GLM free text).
    """
    sections = [
        _render_limitations_handling(plan.scan_type_extracted),
        _render_clinical_conclusion(plan),
        _render_companion_obligations(plan.companion_findings, plan.cross_finding_connections),
        _render_impression_contract(plan.impression_plan),
    ]
    ctx = _render_clinical_context(plan.clinical_context_items)
    if ctx:
        sections.append(ctx)
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Phase 1.5 — Intent-driven clinical evidence fetch
# ---------------------------------------------------------------------------

_MAX_RETRIEVAL_INTENTS = 3


def _case_query_prefix(plan: ReportPlan) -> str:
    return (
        f"{plan.scan_type_extracted}. Modality: {plan.modality}. Region: {plan.body_region}. "
        f"Clinical question: {plan.clinical_question}. Primary diagnosis: {plan.primary_diagnosis}."
    )


def _intent_to_queries(ri: RetrievalIntent, plan: ReportPlan) -> List[str]:
    """Build case-conditioned Perplexity queries for one retrieval intent."""
    base = _case_query_prefix(plan)
    anchor = ri.anchor_finding
    extra = f" {ri.optional_params}" if ri.optional_params else ""
    uk = "UK radiology NHS RCR guidance"

    if ri.intent == "staging_taxonomy":
        return [
            f"{base} TNM staging radiology reporting {anchor}{extra} {uk}",
            f"{base} oncological staging CT MRI nodal stations {anchor} {uk}",
        ]
    if ri.intent == "surveillance_protocol":
        return [
            f"{base} imaging follow-up interval surveillance {anchor}{extra} {uk}",
            f"{base} repeat scan timing radiology {anchor} Fleischner BTS {uk}",
        ]
    if ri.intent == "classification_scale":
        return [
            f"{base} LI-RADS BI-RADS PI-RADS Fleischner classification {anchor}{extra} {uk}",
            f"{base} radiology categorisation reporting criteria {anchor} {uk}",
        ]
    if ri.intent == "acute_severity":
        return [
            f"{base} severity grading complications imaging {anchor}{extra} {uk}",
            f"{base} acute {anchor} radiological criteria {uk}",
        ]
    if ri.intent == "pathway_trigger":
        return [
            f"{base} urgent referral pathway 2WW cancer {anchor}{extra} NHS {uk}",
            f"{base} imaging threshold specialist referral {anchor} {uk}",
        ]
    # general_reference
    return [
        f"{base} {anchor}{extra} radiology guidelines {uk}",
        f"{anchor} criteria imaging management {uk}",
    ]


def _normalize_retrieval_intents(intents: List[RetrievalIntent]) -> List[RetrievalIntent]:
    """Drop duplicate intent+anchor pairs, then cap at _MAX_RETRIEVAL_INTENTS."""
    seen = set()
    out: List[RetrievalIntent] = []
    for ri in intents:
        key = (ri.intent, (ri.anchor_finding or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(ri)
        if len(out) >= _MAX_RETRIEVAL_INTENTS:
            break
    return out


async def _fetch_single_retrieval_intent(ri: RetrievalIntent, plan: ReportPlan) -> str:
    try:
        evidence_block, _ = await run_perplexity_search_chat(_intent_to_queries(ri, plan))
        if not evidence_block:
            return ""
        header = (
            f"--- intent={ri.intent} | anchor={ri.anchor_finding} | rationale={ri.rationale} ---"
        )
        return f"{header}\n{evidence_block}"
    except Exception as exc:
        print(f"[agentic_pipeline] Retrieval fetch failed for intent={ri.intent}: {exc}")
        return ""


async def _fetch_clinical_evidence(plan: ReportPlan) -> str:
    """
    Parallel Perplexity fetch per retrieval intent (case-conditioned queries).
    Returns formatted evidence string for Phase 2, or "" if none / all fail.
    """
    intents = _normalize_retrieval_intents(list(plan.retrieval_intents or []))
    if not intents:
        return ""

    blocks = await asyncio.gather(
        *[_fetch_single_retrieval_intent(ri, plan) for ri in intents],
        return_exceptions=True,
    )
    return "\n\n".join(b for b in blocks if isinstance(b, str) and b.strip())


# ---------------------------------------------------------------------------
# Phase 1 — Planning
# ---------------------------------------------------------------------------

async def generate_report_plan(
    clinical_history: str,
    scan_type: str,
    findings: str,
    api_key: str,
    prior_report: str = "",
) -> ReportPlan:
    """
    Phase 1: run planning agent (GLM reasoning ON) → ReportPlan.

    reasoning ON:  disable_reasoning=False, temperature=0.8, top_p=0.95,
                   max_completion_tokens=16000
    Output type:   ReportPlan (10-step structured fields; execution_brief optional audit only)

    Note: no fallback in initial build. Add @with_retry + Claude fallback
    after the evaluation gate passes (Section 11 of the plan).
    """
    prompt_data = _load_planning_prompt()
    system_prompt = prompt_data["system_prompt"]

    prior_block = f"\nPRIOR REPORT:\n{prior_report}" if prior_report.strip() else ""
    user_prompt = _render_template(
        prompt_data["template"],
        {
            "SCAN_TYPE": scan_type,
            "CLINICAL_HISTORY": clinical_history,
            "FINDINGS": findings,
            "PRIOR_REPORT": prior_block,
        },
    )

    model_name = MODEL_CONFIG["REPORT_PLANNER"]
    model_settings = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 16000,
        "extra_body": {"disable_reasoning": False},
    }

    print(f"[agentic_pipeline] Phase 1 — {model_name} reasoning ON")
    result = await _run_agent_with_model(
        model_name=model_name,
        output_type=ReportPlan,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        use_thinking=False,
        model_settings=model_settings,
    )

    plan: ReportPlan = result.output
    n_ri = len(plan.retrieval_intents or [])
    print(
        f"[agentic_pipeline] Phase 1 complete — "
        f"confidence={plan.plan_confidence}, retrieval_intents={n_ri}"
    )
    return plan


# ---------------------------------------------------------------------------
# Phase 2 — Execution
# ---------------------------------------------------------------------------

async def execute_report_from_plan(
    plan: ReportPlan,
    clinical_history: str,
    scan_type: str,
    findings: str,
    evidence_context: str,
    api_key: str,
    signature: Optional[str] = None,
) -> ReportOutput:
    """
    Phase 2: run execution agent (Cerebras zai-glm-4.7, reasoning ON) → ReportOutput.

    Injects plan.dictation_brief into {{EXECUTION_BRIEF}} — the planner's prose narration of
    its committed structured fields (Step 11). _build_execution_brief() is retained as dead
    code during the hybrid evaluation phase.
    Injects evidence_context into {{EVIDENCE_CONTEXT}}.

    Groq: max_tokens + use_thinking=True. GLM: reasoning ON (disable_reasoning=False),
    temperature=0.8, top_p=0.95, max_completion_tokens=16000. gpt-oss-120b: reasoning_effort=high.
    Other Cerebras: temperature=0.3, max_completion_tokens=6000.
    Output type:   ReportOutput (identical shape to generate_auto_report — drop-in)

    Note: no fallback in initial build. Add Claude fallback after evaluation
    gate passes (same pattern as generate_auto_report's _generate_report_with_claude_model).
    """
    prompt_data = _load_execution_prompt()
    system_prompt = prompt_data["system_prompt"]

    prior_block = ""  # prior_report not threaded through here; plan already accounts for it
    user_prompt = _render_template(
        prompt_data["template"],
        {
            "EXECUTION_BRIEF": plan.dictation_brief,
            "EVIDENCE_CONTEXT": evidence_context or "(No external clinical evidence retrieved for this case.)",
            "SCAN_TYPE": scan_type,
            "CLINICAL_HISTORY": clinical_history,
            "FINDINGS": findings,
            "PRIOR_REPORT": prior_block,
        },
    )

    model_name = MODEL_CONFIG["REPORT_EXECUTOR"]
    executor_provider = _get_model_provider(model_name)
    if executor_provider == "groq":
        # PydanticAI Groq maps max_tokens; use_thinking enables groq_reasoning_format=parsed.
        # If the API still returns tool_use_failed, _run_agent_with_model recovers from
        # error.failed_generation when it is valid ReportOutput JSON.
        model_settings = {"temperature": 0.3, "max_tokens": 6000}
        use_thinking = True
    elif model_name == "zai-glm-4.7":
        model_settings = {
            "temperature": 0.8,
            "top_p": 0.95,
            "max_completion_tokens": 16000,
            "extra_body": {"disable_reasoning": False},
        }
        use_thinking = False
    elif model_name == "gpt-oss-120b":
        model_settings = {
            "temperature": 1,
            "max_completion_tokens": 6500,
            "reasoning_effort": "high",
        }
        use_thinking = False
    else:
        model_settings = {"temperature": 0.3, "max_completion_tokens": 6000}
        use_thinking = False

    print(f"[agentic_pipeline] Phase 2 — {model_name}")
    result = await _run_agent_with_model(
        model_name=model_name,
        output_type=ReportOutput,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        use_thinking=use_thinking,
        model_settings=model_settings,
    )

    report_output: ReportOutput = result.output

    report_output = _append_signature_to_report(report_output, signature)
    print("[agentic_pipeline] Phase 2 complete")
    return report_output


# ---------------------------------------------------------------------------
# Phase 3 — Optional plan-adherence check
# ---------------------------------------------------------------------------

async def check_plan_adherence(
    plan: ReportPlan,
    report_output: ReportOutput,
    groq_api_key: str,
) -> List[str]:
    """
    Phase 3: cross-check report output against plan (Qwen/Groq — fast, cheap).

    Triggers when plan.plan_confidence != "high".
    Returns list of violation strings (empty = passed).
    """
    model_name = MODEL_CONFIG["PLAN_ADHERENCE_CHECKER"]

    companion_obligations = "\n".join(
        f"- [{cf.companion_type}] {cf.structure}: {cf.status}"
        + (f" — {cf.detail}" if cf.detail else "")
        for cf in plan.companion_findings
    )

    ip = plan.impression_plan
    imp_lines = [f"- included_findings: {', '.join(ip.included_findings) or '(none)'}"]
    if ip.management_altering_negatives:
        imp_lines.append(
            "- management_altering_negatives: " + ", ".join(ip.management_altering_negatives)
        )
    for r in ip.recommendation_decisions:
        imp_lines.append(
            f"- recommendation: {r.finding} → {r.recommendation or '(none)'}"
        )
    impression_contract = "\n".join(imp_lines)

    system_prompt = (
        "You are a radiology report quality checker. "
        "Check whether the report faithfully executes the plan. "
        "Return a JSON object: {\"violations\": [\"...\", \"...\"]} "
        "— empty array if the report passes. Be concise; list only genuine omissions or contradictions."
    )

    user_prompt = (
        f"COMPANION OBLIGATIONS FROM PLAN:\n{companion_obligations}\n\n"
        f"IMPRESSION CONTRACT FROM PLAN:\n{impression_contract}\n\n"
        f"GENERATED REPORT:\n{report_output.report_content}\n\n"
        "List any companions omitted from FINDINGS with wrong status, any impression contract items "
        "clearly missing from IMPRESSION, or any status contradictions. Return JSON only."
    )

    from pydantic import BaseModel as PydanticBaseModel

    class AdherenceResult(PydanticBaseModel):
        violations: List[str]

    model_settings = {
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    print(f"[agentic_pipeline] Phase 3 — {model_name} adherence check")
    try:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=AdherenceResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=groq_api_key,
            use_thinking=True,
            model_settings=model_settings,
        )
        violations = result.output.violations
        if violations:
            print(f"[agentic_pipeline] Phase 3 found {len(violations)} violation(s)")
        else:
            print("[agentic_pipeline] Phase 3 passed — no violations")
        return violations
    except Exception as exc:
        print(f"[agentic_pipeline] Phase 3 adherence check failed (non-blocking): {exc}")
        return []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_agentic_pipeline(
    clinical_history: str,
    scan_type: str,
    findings: str,
    cerebras_api_key: str,
    groq_api_key: str,
    signature: Optional[str] = None,
    prior_report: str = "",
    skip_guidelines: bool = False,
) -> AgenticReportOutput:
    """
    Full agentic pipeline: Phase 1 → 1.5 → 2 → Phase 3 (if confidence != high).

    Returns AgenticReportOutput, which is drop-in compatible with ReportOutput
    (report_content, description, scan_type, model_used are identical fields).
    """
    pipeline_start = time.time()

    # Phase 1 — planning
    plan = await generate_report_plan(
        clinical_history=clinical_history,
        scan_type=scan_type,
        findings=findings,
        api_key=cerebras_api_key,
        prior_report=prior_report,
    )

    # Phase 1.5 — intent-driven evidence fetch (parallel, skip if requested)
    if skip_guidelines:
        evidence_context = ""
        print("[agentic_pipeline] Phase 1.5 skipped (skip_guidelines=True)")
    else:
        evidence_context = await _fetch_clinical_evidence(plan)
        fetched = len([b for b in evidence_context.split("---") if b.strip()])
        print(f"[agentic_pipeline] Phase 1.5 complete — {fetched} evidence block(s) fetched")

    executor_model = MODEL_CONFIG["REPORT_EXECUTOR"]
    executor_key = (
        groq_api_key
        if _get_model_provider(executor_model) == "groq"
        else cerebras_api_key
    )

    # Phase 2 — execution
    report_output = await execute_report_from_plan(
        plan=plan,
        clinical_history=clinical_history,
        scan_type=scan_type,
        findings=findings,
        evidence_context=evidence_context,
        api_key=executor_key,
        signature=signature,
    )

    # Phase 3 — optional adherence check (only when plan confidence is not high)
    violations: List[str] = []
    if plan.plan_confidence != "high":
        print(f"[agentic_pipeline] plan_confidence={plan.plan_confidence} — running Phase 3")
        violations = await check_plan_adherence(
            plan=plan,
            report_output=report_output,
            groq_api_key=groq_api_key,
        )

    pipeline_ms = int((time.time() - pipeline_start) * 1000)
    print(f"[agentic_pipeline] Pipeline complete in {pipeline_ms}ms")

    return AgenticReportOutput(
        report_content=report_output.report_content,
        description=report_output.description,
        scan_type=report_output.scan_type,
        model_used=MODEL_CONFIG["REPORT_EXECUTOR"],
        plan=plan,
        plan_adherence_violations=violations,
        pipeline_ms=pipeline_ms,
    )
