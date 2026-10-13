"""Templated scratchpad session: the stack brief and the _STACK prompts (template mirror of quick's stack_fallback)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rapid_reports_ai import enhancement_utils as eu
from rapid_reports_ai import global_style_guide as g
from rapid_reports_ai.template_manager import TemplateManager
from rapid_reports_ai.template_stack import stack_brief

FIX = Path(__file__).parent / "fixtures" / "template_pipeline"
LEAN = (FIX / "lean_cmr.md").read_text()      # a stored template sheet (lean grammar)
MASTER = (FIX / "master_cmr.md").read_text()  # with the Phase-1 case units
_CONTENT = re.compile(r"^\s*(?:-\s+)?(?:NORMAL|NEGATIVE|IF_PRESENT|RECOMMEND|DIFFERENTIAL|QUESTION)\b|Interpretive phrasing:")


@pytest.mark.parametrize("sheet", [LEAN, MASTER])
def test_content_units_go_structure_and_style_stay(sheet):
    b = stack_brief(sheet, "", [])
    assert not [l for l in b.splitlines() if _CONTENT.search(l)]
    assert "## Case Deliberation" not in b and "## Open Questions" not in b and "### Inclusion logic" not in b
    for kept in ("## Report Structure", "SECTION CONCLUSION", "TERM PREFER", 'FIXED "Cardiac MRI at 1.5 T.',
                 "Abnormal pattern:", "Measurement:", "COVERS [", "RULE WHEN", "## Reference Values"):
        assert kept in b


def test_bulleted_and_indented_units_go_too():
    """The grammar allows indentation and a "- " bullet before the keyword (review 2026-10-12)."""
    sheet = ('## Paragraph: Liver (FINDINGS)\nCOVERS ["liver"]\n- NORMAL [liver] "The liver is normal."\n'
             '  NEGATIVE "No focal lesion."\n  - IF_PRESENT [cirrhosis] "No ascites" (core)\nOpening: "The liver..."')
    b = stack_brief(sheet, "", [])
    assert "normal." not in b and "focal lesion" not in b and "ascites" not in b
    assert 'COVERS ["liver"]' in b and "Opening:" in b


def test_a_dropped_block_ends_at_the_next_grammar_context():
    sheet = "## Open Questions\n- [NEEDS CLARIFICATION] x\n### sub\nprose\n# Next\nkept line"
    b = stack_brief(sheet, "", [])
    assert "NEEDS CLARIFICATION" not in b and "prose" not in b and "# Next" in b and "kept line" in b


def test_conclusion_and_removed_sentences_are_carried():
    b = stack_brief(LEAN, "  Normal cardiac MRI.  ", ["No pericardial effusion.", "  "])
    assert '- DO NOT ASSERT: "No pericardial effusion."' in b and b.count("DO NOT ASSERT") == 1
    assert b.rstrip().endswith('"Normal cardiac MRI."') and "## Confirmed Conclusion" in b
    assert "outrank every other rule" in b


def test_no_conclusion_or_removals_no_sections():
    b = stack_brief(LEAN, " ", ["  ", ""])
    assert "## Confirmed Conclusion" not in b and "## Removed by the Radiologist" not in b


def test_a_blank_sheet_still_gives_the_session_rules():
    b = stack_brief("", "C.", [])
    assert b.startswith("## Scratchpad Session") and "## Confirmed Conclusion" in b


def test_session_rules_hold_back_statements_a_sheet_rule_requires():
    b = stack_brief("## Domain Rules\nThe LGE paragraph always closes with a thrombus statement.\n", "C.", [])
    assert "always closes with a thrombus statement" in b  # free prose stays; the session rule subordinates it
    assert "applies only when the FINDINGS input contains that statement" in b


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
    assert "except over its Scratchpad Session rules" in " ".join(g.TEMPLATE_SHEET_HEADER_STACK.split())
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
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": LEAN, "scan_type": "CMR"}
    await TemplateManager().generate_report_from_config(
        cfg, {"FINDINGS": "Left ventricle: dilated.", "CLINICAL_HISTORY": "SOB"}, None,
        stack={"conclusion": "Dilated left ventricle.", "declined": ["No pericardial effusion."]})
    gen = next(k for k in capture if k["output_type"] is str)
    sp, up = gen["system_prompt"], gen["user_prompt"]
    assert g.GLOBAL_STYLE_GUIDE_STACK in sp and g.TEMPLATE_SHEET_HEADER_STACK in sp
    assert g.GLOBAL_STYLE_GUIDE not in sp and "No significant valvular regurgitation" not in sp
    assert '"Dilated left ventricle."' in sp and 'DO NOT ASSERT: "No pericardial effusion."' in sp
    assert g.PRE_WRITING_ANALYSIS_STACK in up and g.VERIFICATION_CHECKLIST_STACK in up
    assert "Findings: Left ventricle: dilated." in up and "Clinical History: SOB" in up


async def test_no_stack_keeps_the_raw_path(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": LEAN, "scan_type": "CMR"}
    await TemplateManager().generate_report_from_config(cfg, {"FINDINGS": "f"}, None)
    gen = next(k for k in capture if k["output_type"] is str)
    assert g.GLOBAL_STYLE_GUIDE in gen["system_prompt"] and "No significant valvular regurgitation" in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS in gen["user_prompt"]


def test_session_rules_cover_fixed_lines_and_examples():
    b = stack_brief("", "C.", [])
    assert "FIXED line" in b and "written as it stands" in b
    assert "examples of the radiologist's wording" in b
    assert "even when the input does not mention its structure" in b
    assert "style note" in b


def test_stack_terminology_applies_only_to_sheet_wording():
    from rapid_reports_ai.global_style_guide import GLOBAL_STYLE_GUIDE_STACK, TEMPLATE_SHEET_HEADER_STACK
    assert "a term in the FINDINGS input or the confirmed conclusion" in GLOBAL_STYLE_GUIDE_STACK
    assert "suppression rules" not in TEMPLATE_SHEET_HEADER_STACK.split("were taken out")[0]


def test_fixed_lines_never_contradict_the_input():
    b = stack_brief("", "C.", [])
    assert "a FIXED line never contradicts the input, the clinical history" in b
    assert "written only when that RULE applies" in b
    assert "gives every slot's value" in b


def test_stack_terminology_keeps_the_conclusion_wording():
    assert "a term in the FINDINGS input or the confirmed conclusion is kept as the radiologist said it" \
        in g.GLOBAL_STYLE_GUIDE_STACK
    assert "the wording the report adds" in g.GLOBAL_STYLE_GUIDE_STACK


async def test_session_rules_reach_the_generation_system_prompt(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": LEAN, "scan_type": "CMR"}
    await TemplateManager().generate_report_from_config(
        cfg, {"FINDINGS": "Left ventricle: dilated.", "CLINICAL_HISTORY": "SOB"}, None,
        stack={"conclusion": "Dilated left ventricle.", "declined": []})
    sp = next(k for k in capture if k["output_type"] is str)["system_prompt"]
    for s in ("**Fixed lines:**", "a FIXED line never contradicts the input, the clinical history",
              "**Examples are wording only:**", "the wording the report adds"):
        assert s in sp


def test_scores_and_values_only_when_supplied():
    b = stack_brief("", "C.", [])
    assert "**Scores, grades and values:**" in b
    for s in ("score, grade, classification, time window, measurement, value, image coordinate or recommendation",
              "only when the FINDINGS input or the confirmed conclusion supplies it",
              "never estimate, infer or fill one in"):
        assert s in b


async def test_scores_rule_reaches_the_generation_system_prompt(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": LEAN, "scan_type": "CMR"}
    await TemplateManager().generate_report_from_config(
        cfg, {"FINDINGS": "Left ventricle: dilated.", "CLINICAL_HISTORY": "SOB"}, None,
        stack={"conclusion": "Dilated left ventricle.", "declined": []})
    sp = next(k for k in capture if k["output_type"] is str)["system_prompt"]
    assert "**Scores, grades and values:**" in sp and "never estimate, infer or fill one in" in sp


def test_labelled_openings_reach_the_brief_as_written():
    lines = ['Opening (normal): "The left ventricle is normal in size."',
             'Opening (abnormal): "The left ventricle is {severity} dilated."']
    sheet = '## Paragraph: Left ventricle (FINDINGS)\nCOVERS ["left ventricle"]\n' + "\n".join(lines)
    b = stack_brief(sheet, "", [])
    assert all(l in b.splitlines() for l in lines)


def test_fixed_line_rule_names_the_decided_block_exception():
    from rapid_reports_ai.template_context_rules import DECIDED_HEADING
    from rapid_reports_ai.template_stack import stack_brief
    assert DECIDED_HEADING.lstrip("# ") in stack_brief("", "", ())


def test_habit_lines_never_reach_the_generator():
    sheet = ('## Report Structure\nSECTION FINDINGS | header: "Findings:" | role: findings\n'
             'SECTION IMPRESSION | header: "Impression:" | role: impression\n\n'
             '## Paragraph: Upper (FINDINGS)\nCOVERS ["alpha"]\nNORMAL [alpha] "Alpha is normal."\n'
             'RULE WHEN [findings: an alpha abnormality is reported] ASK "Extension beyond alpha?" '
             'YES "The abnormality extends beyond alpha." NO "No extension beyond alpha."\n'
             '  - NEGATIVE "No beta extension." WHEN [findings: an alpha abnormality is reported]\n\n'
             '## Report-wide\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["Width"] AT TOP\n')
    b = stack_brief(sheet, "", [])
    assert "ASK" not in b and "No beta extension" not in b and "Extension beyond alpha" not in b
    assert "LIST_MISSING" in b and "COVERS [" in b


@pytest.mark.parametrize("stack", [None, {"conclusion": "C.", "declined": []}])
async def test_the_fallback_path_never_shows_a_habit_line_to_the_generator(capture, stack):
    # today's path (the lean mirror failed or is not on) reads the stored sheet: habit lines are stripped there too
    habits = ('\nRULE WHEN [findings: an alpha abnormality is reported] ASK "Extension beyond alpha?" '
              'YES "The abnormality extends beyond alpha." NO "No extension beyond alpha."\n'
              'NEGATIVE "No delta extension." WHEN [findings: a delta abnormality is reported]\n')
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": LEAN + habits, "scan_type": "CMR"}
    await TemplateManager().generate_report_from_config(cfg, {"FINDINGS": "f"}, None, stack=stack)
    gen = next(k for k in capture if k["output_type"] is str)
    assert "Extension beyond alpha" not in gen["system_prompt"] and "No delta extension" not in gen["system_prompt"]


def test_missing_values_rule_only_when_the_scratchpad_decided_the_values():
    assert "Missing values" not in stack_brief(LEAN, "", ())
    b = stack_brief(LEAN, "", (), values_decided=True)
    assert "**Missing values:**" in b and "write no list of missing or unprovided values" in b
    assert b.index("**Missing values:**") > b.index("## Scratchpad Session")
