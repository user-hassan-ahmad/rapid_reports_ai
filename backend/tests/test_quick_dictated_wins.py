"""Quick stack writer: dictated FINDINGS statements win over a removed sentence (Q7, 2026-10-16).

The quick path has no house style to match: a FINDINGS statement always appears with its meaning and wording kept
(light grammar fixes only), even when it resembles a removed sentence; a removed sentence is suppressed only where
nothing dictated says it. Pure string checks on the three instruction sites; no LLM call.
"""
from __future__ import annotations

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE_STACK
from rapid_reports_ai.quick_report_prompts import QR_STYLE_GUIDE_STACK, QR_VERIFICATION_CHECKLIST_STACK

SLIM = "## Structural Pattern\n- **Sections:** FINDINGS, IMPRESSION\n"


def _removed_block(text: str) -> str:
    """The Mandatory negatives bullet: from its label to the next section."""
    return text.split("- **Mandatory negatives:**", 1)[1].split("\n## ", 1)[0]


def test_stack_brief_says_findings_win_over_removed_sentences():
    block = _removed_block(qb.stack_fallback(SLIM, "", ["Normal aortic root."]).text)
    rule, bullets = block.split('- DO NOT ASSERT: "', 1)
    assert "Normal aortic root." in bullets
    assert qb.REMOVED_RULE in rule                         # the rule sits before the removed bullets
    assert qb.REMOVED_RULE.startswith("FINDINGS statements always win over these removed sentences")
    assert "except its Conclusion, Recommendations and DO NOT ASSERT lines" in qb.REMOVED_RULE
    assert "meaning and wording kept (light grammar fixes only;" in qb.REMOVED_RULE
    assert "same structure" in qb.REMOVED_RULE
    assert "never removes, shortens or rewords a FINDINGS statement" in qb.REMOVED_RULE
    assert "where no FINDINGS statement says it" in qb.REMOVED_RULE


def test_stack_brief_has_no_removed_rule_without_removals():
    assert qb.REMOVED_RULE not in qb.stack_fallback(SLIM, "", []).text


def test_stack_brief_content_rule_keeps_wording():
    t = qb.stack_fallback(SLIM, "", []).text
    assert "appears, with its meaning and wording kept (light grammar fixes only;" in t


def test_hardening_principle_12_lets_findings_win():
    p12 = QUICK_REPORT_HARDENING_PREAMBLE_STACK.split("**12. ", 1)[1].split("\n\n", 1)[0]
    assert "it never appears, in any wording or section, unless a FINDINGS statement says it" in p12
    assert "never removes, shortens or rewords a FINDINGS statement" in p12


def test_stack_checklist_lets_findings_win():
    lines = QR_VERIFICATION_CHECKLIST_STACK.splitlines()
    every = next(l for l in lines if l.startswith("- Every FINDINGS statement"))
    no_assert = next(l for l in lines if l.startswith("- No DO NOT ASSERT statement"))
    assert "DO NOT ASSERT lines excepted)" in every
    assert "meaning and wording kept (light grammar fixes only;" in every
    assert "in any wording" in no_assert and "unless a FINDINGS statement says it" in no_assert
    assert "same structure as a DO NOT ASSERT line or worded like it" in every


# ---- review of 65dbf914 + Q17-Q20 (2026-10-17) ----
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE, \
    QUICK_REPORT_HARDENING_PREAMBLE_BRIEF  # noqa: E402
from rapid_reports_ai.quick_report_prompts import QR_STYLE_GUIDE, QR_STYLE_GUIDE_BRIEF, \
    QR_VERIFICATION_CHECKLIST_BRIEF  # noqa: E402

KEPT = "light grammar fixes only; statements may be joined as the Report Flow allows; abbreviations stay as dictated"
EXEMPT = "Conclusion, Recommendations and DO NOT ASSERT lines"


def test_wording_rule_names_joining_and_abbreviations_everywhere_in_the_stack_prompts():
    brief = qb.stack_fallback(SLIM, "", ["X."]).text
    assert KEPT in qb.REMOVED_RULE and KEPT in brief
    assert KEPT in QR_VERIFICATION_CHECKLIST_STACK and KEPT in QR_STYLE_GUIDE_STACK


def test_wording_rule_exempts_conclusion_recommendations_and_the_removed_line():
    """Q19: the conclusion and selected recommendations are written in report style; the DO NOT ASSERT line is no
    statement to write."""
    every = next(l for l in QR_VERIFICATION_CHECKLIST_STACK.splitlines() if l.startswith("- Every FINDINGS statement"))
    assert EXEMPT in every and EXEMPT in qb.REMOVED_RULE
    content = qb.stack_fallback(SLIM, "", []).text.split("- **Content and flow:**", 1)[1].split("\n", 1)[0]
    assert EXEMPT in content


def test_checklist_has_one_findings_line_covering_removed_structure():
    lines = QR_VERIFICATION_CHECKLIST_STACK.splitlines()
    assert not any(l.startswith("- Every FINDINGS statement stays") for l in lines)
    every = [l for l in lines if l.startswith("- Every FINDINGS statement")]
    assert len(every) == 1 and "same structure as a DO NOT ASSERT line" in every[0]


def test_a_narrower_dictated_statement_never_licenses_the_broader_removed_sentence():
    no_assert = next(l for l in QR_VERIFICATION_CHECKLIST_STACK.splitlines() if l.startswith("- No DO NOT ASSERT"))
    for t in (no_assert, qb.REMOVED_RULE):
        assert "licenses only what it says itself, never a broader removed sentence" in t


def test_stack_voice_keeps_dictated_wording():
    voice = QR_STYLE_GUIDE_STACK.split("### Voice", 1)[1].split("###", 1)[0]
    assert "Do not copy input" not in voice and "interpret and reframe" not in voice
    assert "FINDINGS statements keep the radiologist's wording" in voice
    assert "conclusion and any selected recommendation are written in report style" in voice


def test_stack_hardening_keeps_abbreviations_as_dictated():
    assert "Expanding \"local perf\"" not in QUICK_REPORT_HARDENING_PREAMBLE_STACK
    assert "Sanctioned synonym mapping" not in QUICK_REPORT_HARDENING_PREAMBLE_STACK
    assert "transcription exceptions below" not in QUICK_REPORT_HARDENING_PREAMBLE_STACK
    assert "abbreviations and shorthand stay as dictated" in QUICK_REPORT_HARDENING_PREAMBLE_STACK


def test_stack_terminology_rules_never_rename_a_findings_statement():
    term = QR_STYLE_GUIDE_STACK.split("### Terminology Enforcement", 1)[1].split("###", 1)[0]
    assert "a FINDINGS statement keeps the dictated terms" in term


def test_non_stack_quick_prompts_are_unchanged():
    """Scope guard: the wording rule and its swaps reach stack sessions only."""
    for t in (QR_VERIFICATION_CHECKLIST_BRIEF, QUICK_REPORT_HARDENING_PREAMBLE, QUICK_REPORT_HARDENING_PREAMBLE_BRIEF,
              QR_STYLE_GUIDE, QR_STYLE_GUIDE_BRIEF):
        assert KEPT not in t and "light grammar fixes only" not in t and "keeps the dictated terms" not in t
    for t in (QR_STYLE_GUIDE, QR_STYLE_GUIDE_BRIEF):
        assert "interpret and reframe into your own radiological language" in t
    for t in (QUICK_REPORT_HARDENING_PREAMBLE, QUICK_REPORT_HARDENING_PREAMBLE_BRIEF):
        assert "Sanctioned synonym mapping" in t and "Expanding \"local perf\"" in t
