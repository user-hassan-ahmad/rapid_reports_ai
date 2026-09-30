"""Signed-off §5 package: brief variants carry the labels and none of the duplicated rules."""
from __future__ import annotations

from rapid_reports_ai import global_style_guide as g


def test_t0_allows_only_a_sheet_defined_history_section():
    assert "never reproduced outside a\nCLINICAL HISTORY section the skill sheet defines" in g.GLOBAL_STYLE_GUIDE
    assert "Restate the clinical history input only; add nothing." in g.GLOBAL_STYLE_GUIDE


def test_brief_variants_drop_what_the_brief_resolves():
    brief = g.GLOBAL_STYLE_GUIDE_BRIEF + g.PRE_WRITING_ANALYSIS_BRIEF + g.VERIFICATION_CHECKLIST_BRIEF
    for gone in ("### Conditional Awareness", "### Conditional Style Application", "### Parameter Placeholders",
                 "Clinical history as checklist", "Conditional Suppression Rule", "All triggered interpretive clauses",
                 "Verify all IF/THEN"):
        assert gone not in brief, gone
    for kept in ("Reference Values table", "header: none", "Impression format matches skill sheet",
                 "demonstrated style always takes precedence", "### Consolidation", "[NEEDS VERIFICATION]"):
        assert kept in brief, kept


def test_brief_header_defines_every_label():
    for label in ("KEEP", "OMIT", "DO NOT ASSERT", "INSTEAD", "APPLY", "USE", "Do not assert as normal",
                  "Carry forward", "Coverage is obligatory, assertion is earned"):
        assert label in g.TEMPLATE_SHEET_HEADER_BRIEF, label


def test_checklist_carries_the_l48_plus_line_and_slot_rule():
    v = g.VERIFICATION_CHECKLIST_BRIEF
    assert "or one cluster of negatives bearing on the index finding's next step" in v
    assert "No curly-brace slot appears as text" in v
