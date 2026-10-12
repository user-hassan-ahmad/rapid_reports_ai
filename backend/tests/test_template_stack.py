"""Templated scratchpad session: the stack brief and the _STACK prompts (template mirror of quick's stack_fallback)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rapid_reports_ai import enhancement_utils as eu
from rapid_reports_ai import global_style_guide as g
from rapid_reports_ai.template_manager import TemplateManager
from rapid_reports_ai.template_stack import stack_brief

FIX = Path(__file__).parent / "fixtures"
V1 = (FIX / "template_sheet.md").read_text()
GRAMMAR = (FIX / "template_pipeline" / "master_cmr.md").read_text()
_CONTENT = re.compile(r"^\s*(?:NORMAL|NEGATIVE|IF_PRESENT|RECOMMEND|DIFFERENTIAL|QUESTION)\b|Interpretive phrasing:")


def test_v1_sheet_keeps_structure_and_style_and_drops_content():
    b = stack_brief(V1, "", [])
    for kept in ("## Structural Pattern", '`header: "Impression"`', "## Terminology Rules", "Suppressed terms",
                 "### Quoted examples", "### Normal study impression", "### Primary Pathology Paragraph"):
        assert kept in b
    for gone in ("Mandatory negatives", "No pneumoperitoneum", "No periappendiceal collection", "Normal pattern",
                 "Interpretive Clause Rules", "Conditional Suppression Rules", "Negative Finding Rules",
                 "Inclusion logic", "Promoted to Impression"):
        assert gone not in b
    assert "## Fixed Blocks" in b and "## Scan Context" in b


def test_grammar_sheet_drops_every_content_statement():
    b = stack_brief(GRAMMAR, "", [])
    assert not [l for l in b.splitlines() if _CONTENT.search(l)]
    assert "## Case Deliberation" not in b and "## Open Questions" not in b and "### Inclusion logic" not in b
    for kept in ("## Report Structure", "SECTION CONCLUSION", "TERM PREFER", "FIXED \"Cardiac MRI at 1.5 T.",
                 "Abnormal pattern:", "Measurement:", "## Reference Values", "## Domain Rules",
                 "### Full impressions (verbatim)", "Recommendation phrasing:"):
        assert kept in b


def test_conclusion_and_removed_sentences_are_carried():
    b = stack_brief(V1, "  Acute appendicitis.  ", ["No free fluid.", "  "])
    assert '- DO NOT ASSERT: "No free fluid."' in b and b.count("DO NOT ASSERT") == 1
    assert b.rstrip().endswith('"Acute appendicitis."') and "## Confirmed Conclusion" in b
    assert "## Scratchpad Session" in b


def test_no_conclusion_or_removals_no_sections():
    b = stack_brief(V1, " ", [])
    assert "## Confirmed Conclusion" not in b and "## Removed by the Radiologist" not in b


def test_a_blank_sheet_still_gives_the_session_rules():
    b = stack_brief("", "C.", [])
    assert b.startswith("## Scratchpad Session") and "## Confirmed Conclusion" in b


def test_stack_prompts_take_out_what_the_scratchpad_confirmed():
    for text in (g.GLOBAL_STYLE_GUIDE_STACK, g.PRE_WRITING_ANALYSIS_STACK, g.VERIFICATION_CHECKLIST_STACK):
        assert "mandatory negative" not in text.lower()
    assert "### Impression as Synthesis" not in g.GLOBAL_STYLE_GUIDE_STACK
    assert "### Conditional Awareness" not in g.GLOBAL_STYLE_GUIDE_STACK
    assert "state it and\ncommit" not in g.GLOBAL_STYLE_GUIDE_STACK
    assert "adds no finding, diagnosis, negative, synthesis or" in g.GLOBAL_STYLE_GUIDE_STACK
    assert "interpretive clauses" not in g.VERIFICATION_CHECKLIST_STACK
    assert "Companion inventory" not in g.PRE_WRITING_ANALYSIS_STACK
    # A sheet-defined CLINICAL HISTORY section is still written as on today's raw path
    assert "If a CLINICAL HISTORY section is defined in the skill sheet" in g.GLOBAL_STYLE_GUIDE_STACK
    assert "supplied separately" not in g.GLOBAL_STYLE_GUIDE_STACK
    # Unchanged style rules
    for kept in ("### Terminology Enforcement", "### Data Authority", "### Fixed Blocks and Parametrisation"):
        assert kept in g.GLOBAL_STYLE_GUIDE_STACK


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


async def test_stack_session_uses_the_stack_brief_and_prompts(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": V1, "scan_type": "CT AP"}
    await TemplateManager().generate_report_from_config(
        cfg, {"FINDINGS": "Appendix: dilated.", "CLINICAL_HISTORY": "RIF pain"}, None,
        stack={"conclusion": "Acute appendicitis.", "declined": ["No free fluid."]})
    gen = next(k for k in capture if k["output_type"] is str)
    sp, up = gen["system_prompt"], gen["user_prompt"]
    assert g.GLOBAL_STYLE_GUIDE_STACK in sp and g.TEMPLATE_SHEET_HEADER_STACK in sp
    assert g.GLOBAL_STYLE_GUIDE not in sp and "No pneumoperitoneum" not in sp
    assert '"Acute appendicitis."' in sp and 'DO NOT ASSERT: "No free fluid."' in sp
    assert g.PRE_WRITING_ANALYSIS_STACK in up and g.VERIFICATION_CHECKLIST_STACK in up
    assert "Findings: Appendix: dilated." in up and "Clinical History: RIF pain" in up


async def test_no_stack_keeps_the_raw_path(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": V1, "scan_type": "CT AP"}
    await TemplateManager().generate_report_from_config(cfg, {"FINDINGS": "f"}, None)
    gen = next(k for k in capture if k["output_type"] is str)
    assert g.GLOBAL_STYLE_GUIDE in gen["system_prompt"] and "No pneumoperitoneum" in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS in gen["user_prompt"]
