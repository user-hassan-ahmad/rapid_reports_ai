"""Quick stack writer: dictated FINDINGS statements win over a removed sentence (Q7, 2026-10-16).

The quick path has no house style to match: a FINDINGS statement always appears with its meaning and wording kept
(light grammar fixes only), even when it resembles a removed sentence; a removed sentence is suppressed only where
nothing dictated says it. Pure string checks on the three instruction sites; no LLM call.
"""
from __future__ import annotations

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE_STACK
from rapid_reports_ai.quick_report_prompts import QR_VERIFICATION_CHECKLIST_STACK

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
    assert "except its own DO NOT ASSERT line" in qb.REMOVED_RULE
    assert "meaning and wording kept (light grammar fixes only)" in qb.REMOVED_RULE
    assert "same structure" in qb.REMOVED_RULE
    assert "never removes, shortens or rewords a FINDINGS statement" in qb.REMOVED_RULE
    assert "where no FINDINGS statement says it" in qb.REMOVED_RULE


def test_stack_brief_has_no_removed_rule_without_removals():
    assert qb.REMOVED_RULE not in qb.stack_fallback(SLIM, "", []).text


def test_stack_brief_content_rule_keeps_wording():
    t = qb.stack_fallback(SLIM, "", []).text
    assert "Every statement in the input appears, with its meaning and wording kept (light grammar fixes only)" in t


def test_hardening_principle_12_lets_findings_win():
    p12 = QUICK_REPORT_HARDENING_PREAMBLE_STACK.split("**12. ", 1)[1].split("\n\n", 1)[0]
    assert "it never appears, in any wording or section, unless a FINDINGS statement says it" in p12
    assert "never removes, shortens or rewords a FINDINGS statement" in p12


def test_stack_checklist_lets_findings_win():
    lines = QR_VERIFICATION_CHECKLIST_STACK.splitlines()
    every = next(l for l in lines if l.startswith("- Every statement in FINDINGS"))
    no_assert = next(l for l in lines if l.startswith("- No DO NOT ASSERT statement"))
    stays = next(l for l in lines if l.startswith("- Every FINDINGS statement stays"))
    assert "(its DO NOT ASSERT line excepted)" in every
    assert "meaning and wording kept (light grammar fixes only)" in every
    assert "in any wording" in no_assert and no_assert.endswith("unless a FINDINGS statement says it")
    assert "same structure as a DO NOT ASSERT line" in stays and "own words" in stays
