"""Template pipeline (spec §4)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import enhancement_utils as eu
from rapid_reports_ai import global_style_guide as g
from rapid_reports_ai.template_manager import TemplateManager


@pytest.fixture
def capture(monkeypatch):
    seen = []

    class R:
        output = "FINDINGS\nX."

    async def fake(**kw):
        seen.append(kw)
        return R
    monkeypatch.setattr(eu, "_run_agent_with_model", fake)
    monkeypatch.setattr(eu, "_get_api_key_for_provider", lambda p, fallback_api_key=None: "k")
    monkeypatch.setattr(eu, "_get_model_provider", lambda m: "cerebras")
    return seen


async def test_brief_path_uses_brief_prompts_and_history_note(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f", "CLINICAL_HISTORY": "h"}, None, brief_text="BRIEF TEXT", history_supplied=True)
    gen = next(k for k in capture if k["output_type"] is str)
    assert "BRIEF TEXT" in gen["system_prompt"] and "RAW SHEET" not in gen["system_prompt"]
    assert g.TEMPLATE_SHEET_HEADER_BRIEF in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE_BRIEF in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS_BRIEF in gen["user_prompt"]
    assert "The CLINICAL HISTORY section is supplied separately; do not write it." in gen["user_prompt"]


async def test_raw_path_is_unchanged(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(cfg, {"FINDINGS": "f"}, None)
    gen = next(k for k in capture if k["output_type"] is str)
    assert "RAW SHEET" in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS in gen["user_prompt"] and "supplied separately" not in gen["user_prompt"]


def _gen(capture):
    return next(k for k in capture if k["output_type"] is str)


@pytest.mark.parametrize("blank", ["", "   \n  "])
async def test_blank_brief_takes_raw_path(capture, blank):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(cfg, {"FINDINGS": "f"}, None, brief_text=blank)
    gen = _gen(capture)
    assert "RAW SHEET" in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE in gen["system_prompt"]
    assert g.TEMPLATE_SHEET_HEADER_BRIEF not in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS in gen["user_prompt"] and g.VERIFICATION_CHECKLIST in gen["user_prompt"]


async def test_brief_path_does_not_leak_raw_prompts(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f"}, None, brief_text="BRIEF TEXT")
    gen = _gen(capture)
    assert g.GLOBAL_STYLE_GUIDE not in gen["system_prompt"]
    assert "RAW SHEET" not in gen["system_prompt"] and "RAW SHEET" not in gen["user_prompt"]
    assert g.PRE_WRITING_ANALYSIS not in gen["user_prompt"]
    assert g.VERIFICATION_CHECKLIST_BRIEF in gen["user_prompt"]
    # The _BRIEF constants themselves mention "supplied separately"; check the exact note.
    assert "The CLINICAL HISTORY section is supplied separately; do not write it." not in gen["user_prompt"]


async def test_brief_path_anthropic_provider(capture, monkeypatch):
    monkeypatch.setattr(eu, "_get_model_provider", lambda m: "anthropic")
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f", "CLINICAL_HISTORY": "h"}, None, brief_text="BRIEF TEXT", history_supplied=True)
    gen = _gen(capture)
    assert "BRIEF TEXT" in gen["system_prompt"] and "RAW SHEET" not in gen["system_prompt"]
    assert ("Findings: f\n\nThe CLINICAL HISTORY section is supplied separately; do not write it.\n\n"
            "Generate the report now.") in gen["user_prompt"]
    assert g.PRE_WRITING_ANALYSIS_BRIEF not in gen["user_prompt"]
    assert g.PRE_WRITING_ANALYSIS not in gen["user_prompt"]


# Byte-identity guard: the raw path must send exactly the pre-mirror prompts (old f-string layout).
_RAW_SHEET = "RAW SHEET\n## x {braces}"
_ANTHROPIC_TAIL = (
    "Generate the report now. Output the report content ONLY — no analysis, no commentary, no "
    "restatement of the skill sheet. Emit exactly the sections declared in the skill sheet's "
    "Structural Pattern, in order.\n\n"
    "**Voice.** Write as a consultant dictating clinical observations at pace — each finding a "
    "compressed declarative, noun-dense, connective-sparse. Separate observations get separate "
    "sentences; a consultant states what is, not what they saw. Hedge only where diagnostic "
    "uncertainty is genuine.\n\n"
    "**Impression.** Write as a consultant handing over to the referring clinician — they need to "
    "know what you concluded and what to do about it, and nothing else. Every sentence earns its "
    "place by changing what happens next. The voice is clinical handover: specific, unsentimental, "
    "and calibrated by consequence rather than adjective."
)


def _expected_raw(provider: str) -> tuple[str, str]:
    system = f"""{g.SYSTEM_PREAMBLE}

{g.GLOBAL_STYLE_GUIDE}

## TEMPLATE SKILL SHEET

The following skill sheet defines scan-specific reporting conventions for this template.
It inherits all rules from the Global Style Guide above. Where a skill sheet rule
conflicts with a global rule, the skill sheet takes precedence.

{_RAW_SHEET}"""
    inputs = "## INPUTS\n\nScan Type: CT abdo\nClinical History: hist\nFindings: f1\nf2\n\n"
    if provider == "anthropic":
        user = inputs + _ANTHROPIC_TAIL
    else:
        user = inputs + f"{g.PRE_WRITING_ANALYSIS}\n\n{g.VERIFICATION_CHECKLIST}"
    return system, user


@pytest.mark.parametrize("provider", ["cerebras", "anthropic"])
async def test_raw_path_prompts_are_byte_identical(capture, monkeypatch, provider):
    monkeypatch.setattr(eu, "_get_model_provider", lambda m: provider)
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": _RAW_SHEET, "scan_type": "CT abdo"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f1\nf2", "CLINICAL_HISTORY": "hist"}, None)
    gen = _gen(capture)
    system, user = _expected_raw(provider)
    assert gen["system_prompt"] == system
    assert gen["user_prompt"] == user
