"""Quick-report generator: ephemeral skill sheet + dictated findings -> report.

Owned by the quick-report path alone, with its own prompt stack (quick_report_prompts.py)
and model role (QUICK_REPORT_GENERATOR). Template reports keep their own generator in
TemplateManager and their own prompts in global_style_guide.py. The paths started as one
and were split on 2026-09-29 because their sheets, reasoning and failure modes differ;
see scripts/prompt_drift_report.py for rules that exist in both.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List

from pydantic import BaseModel

from .enhancement_utils import (
    MODEL_CONFIG,
    _get_api_key_for_provider,
    _get_model_provider,
    _run_agent_with_model,
)
from .quick_report_brief import compile_brief
from .quick_report_quality import run_quality_check
from .report_reconcile import write_options
from .quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE, QUICK_REPORT_HARDENING_PREAMBLE_BRIEF
from .quick_report_prompts import (
    QR_PRE_WRITING_ANALYSIS,
    QR_PRE_WRITING_ANALYSIS_BRIEF,
    QR_SHEET_HEADER,
    QR_SHEET_HEADER_BRIEF,
    QR_STYLE_GUIDE,
    QR_STYLE_GUIDE_BRIEF,
    QR_SYSTEM_PREAMBLE,
    QR_SYSTEM_PREAMBLE_BRIEF,
    QR_VERIFICATION_CHECKLIST,
    QR_VERIFICATION_CHECKLIST_BRIEF,
)

logger = logging.getLogger(__name__)

# Anthropic models called without thinking treat the analysis scaffolds as output-shaping
# instructions and verbalise them (~2k -> ~14k chars, ~10s -> ~60s), so they get a direct
# instruction instead. The sheet and hardening preamble carry the reasoning discipline.
_ANTHROPIC_INSTRUCTION = """Generate the report now. Output the report content ONLY — no analysis, no commentary, no restatement of the skill sheet. Emit exactly the sections declared in the skill sheet's Structural Pattern, in order.

**Voice.** Write as a consultant dictating clinical observations at pace — each finding a compressed declarative, noun-dense, connective-sparse. Separate observations get separate sentences; a consultant states what is, not what they saw. Hedge only where diagnostic uncertainty is genuine.

**Impression.** Write as a consultant handing over to the referring clinician — they need to know what you concluded and what to do about it, and nothing else. Every sentence earns its place by changing what happens next. The voice is clinical handover: specific, unsentimental, and calibrated by consequence rather than adjective."""

# One settings dict; normalise_model_settings fits it per provider (Cerebras Qwen: medium,
# 64k; Groq Qwen: low, 16,384 ceiling; Sonnet: no sampling params).
_SETTINGS = {"temperature": 0.8, "top_p": 0.95, "max_tokens": 65536}


def build_prompts(skill_sheet: str, scan_type: str, findings: str, clinical_history: str,
                  provider: str, brief: bool = False) -> tuple[str, str]:
    """System and user prompt for one quick report. `skill_sheet` is the analyser's sheet, or
    the compiled brief when `brief` is set; the hardening preamble is prepended here."""
    style, hardening = (QR_STYLE_GUIDE_BRIEF, QUICK_REPORT_HARDENING_PREAMBLE_BRIEF) if brief else (QR_STYLE_GUIDE, QUICK_REPORT_HARDENING_PREAMBLE)
    pre, ver = (QR_PRE_WRITING_ANALYSIS_BRIEF, QR_VERIFICATION_CHECKLIST_BRIEF) if brief else (QR_PRE_WRITING_ANALYSIS, QR_VERIFICATION_CHECKLIST)
    preamble, header = (QR_SYSTEM_PREAMBLE_BRIEF, QR_SHEET_HEADER_BRIEF) if brief else (QR_SYSTEM_PREAMBLE, QR_SHEET_HEADER)
    system_prompt = f"{preamble}\n\n{style}\n\n{header}\n\n{hardening}{skill_sheet}"
    inputs = f"## INPUTS\n\nScan Type: {scan_type}\nClinical History: {clinical_history}\nFindings: {findings}"
    if provider == "anthropic":
        user_prompt = f"{inputs}\n\n{_ANTHROPIC_INSTRUCTION}"
    else:
        user_prompt = f"{inputs}\n\n{pre}\n\n{ver}"
    return system_prompt, user_prompt


async def _describe(findings: str, clinical_history: str, scan_type: str) -> str:
    """Short summary for the history tab, in parallel with the report."""
    class _Desc(BaseModel):
        description: str
    try:
        model = MODEL_CONFIG["REPORT_DESCRIPTION"]
        r = await _run_agent_with_model(
            model_name=model, output_type=_Desc,
            system_prompt=("You generate brief radiology report descriptions for a history tab. Return a JSON object "
                           "with a single key 'description' containing 5-15 words summarising the key findings. "
                           "No scan type, no patient demographics. British English."),
            user_prompt=f"Clinical history: {clinical_history}\nFindings: {findings}",
            api_key=_get_api_key_for_provider(_get_model_provider(model)),
            use_thinking=False,
            model_settings={"temperature": 0.1, "max_tokens": 300, "reasoning_effort": "none"},
        )
        return r.output.description.strip()[:150]
    except Exception:
        return f"Report for {scan_type}"


async def _write_options(options: List[dict], findings: str, scan_type: str) -> List[dict]:
    """Reporter-choice items; the writer is shared (report_reconcile.write_options)."""
    return await write_options(options, findings, scan_type, model=MODEL_CONFIG["QUICK_REPORT_GENERATOR"],
                               runner=_run_agent_with_model)


async def generate_quick_report(
    *,
    skill_sheet: str,
    scan_type: str,
    findings: str,
    clinical_history: str,
    user_signature: str | None = None,
    model_override: str | None = None,
    use_brief: bool = True,
) -> dict:
    """Write one quick report from a compiled brief (the sheet reconciled with this dictation),
    or from the raw sheet with the full prompts if the brief cannot be compiled. Falls back
    once to QUICK_REPORT_GENERATOR_FALLBACK when the configured primary raises; an override
    naming a different model is an explicit comparison and does not fall back."""
    brief = None
    if use_brief:
        try:
            brief = await compile_brief(skill_sheet, scan_type, findings, clinical_history)
        except Exception as e:
            logger.warning("quick-report brief failed (%s: %s); generating from the raw sheet", type(e).__name__, str(e)[:200])
    sheet_for_generator = brief.text if brief else skill_sheet
    primary = MODEL_CONFIG["QUICK_REPORT_GENERATOR"]
    model_name = model_override or primary
    fallback = MODEL_CONFIG.get("QUICK_REPORT_GENERATOR_FALLBACK") if model_name == primary else None

    async def _write(model: str):
        provider = _get_model_provider(model)
        system_prompt, user_prompt = build_prompts(sheet_for_generator, scan_type, findings, clinical_history, provider, brief=brief is not None)
        return await _run_agent_with_model(
            model_name=model, output_type=str, system_prompt=system_prompt, user_prompt=user_prompt,
            api_key=_get_api_key_for_provider(provider), use_thinking=True, model_settings=_SETTINGS,
        )

    fallback_from = None

    async def _write_with_fallback():
        nonlocal model_name, fallback_from
        try:
            return await _write(model_name)
        except Exception as e:
            if not fallback:
                raise
            logger.warning("quick-report generator %s failed (%s); falling back to %s", model_name, type(e).__name__, fallback)
            fallback_from, model_name = model_name, fallback
            return await _write(model_name)

    result, description, options = await asyncio.gather(
        _write_with_fallback(), _describe(findings, clinical_history, scan_type),
        _write_options(brief.decisions.get("options", []) if brief else [], findings, scan_type))
    report = result.output if hasattr(result, "output") else str(result)
    # Jev checks every clause and option against the dictation; one focal Qwen call repairs what
    # it flags before the report ships (spec 2026-09-30-post-generation-check-design).
    report, options, quality = await run_quality_check(report, findings, scan_type, options)
    if user_signature:
        report = report.rstrip() + "\n\n" + user_signature
    return {"report_content": report, "description": description, "scan_type": scan_type,
            "model_used": model_name, "fallback_from": fallback_from,
            "brief_used": brief is not None,
            "brief_reconcile_ms": brief.reconcile_ms if brief else None,
            "brief_decisions": brief.decisions if brief else None,
            "brief_text": brief.text if brief else None,
            "brief_options": options,
            "quality_check": quality}
