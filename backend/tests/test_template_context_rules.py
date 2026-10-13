"""Context rules resolved before generation (spec 2026-10-13-context-rules-resolved-design)."""
from __future__ import annotations

from rapid_reports_ai import template_context_rules as cr
from rapid_reports_ai.template_sheet_grammar import parse_sheet

PRIOR = "the dictation names a previous imaging study for comparison"
NOCON = "the study was performed without intravenous contrast"
OFFSITE = "images were reviewed off site"
NOLIVER = "the liver was not imaged"

SHEET = '''## Report Structure
SECTION COMPARISON | header: "Comparison:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
FIXED "No previous imaging available for comparison." | section: COMPARISON
RULE WHEN [context: the dictation names a previous imaging study for comparison] REPLACE "No previous imaging available for comparison." WITH "Comparison made with previous {study} dated {date}." | section: COMPARISON
RULE WHEN [context: the study was performed without intravenous contrast] USE "No contrast." | section: COMPARISON
FIXED "Images reviewed on PACS." | section: COMPARISON
RULE WHEN [context: images were reviewed off site] SUPPRESS "Images reviewed on PACS." | section: COMPARISON

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
NORMAL [liver] "The liver is normal."
RULE WHEN [context: the liver was not imaged] SUPPRESS "The liver is normal."
'''


def _apply(met: set[str], sheet: str = SHEET):
    rules = cr.rules_in_scope(sheet)
    return cr.apply_rules(sheet, rules, {r.condition: r.condition in met for r in rules})


def test_rules_in_scope_are_the_context_replace_suppress_use_rules():
    rules = cr.rules_in_scope(SHEET)
    assert [(r.effect, r.condition) for r in rules] == [
        ("replace", PRIOR), ("use", NOCON), ("suppress", OFFSITE), ("suppress", NOLIVER)]


def test_rules_in_scope_is_none_for_a_non_grammar_or_unclean_sheet():
    assert cr.rules_in_scope("# Skill Sheet\nSome prose only.\n") is None
    assert cr.rules_in_scope(SHEET + 'FIXED "unclosed\n') is None


def test_nothing_met_keeps_every_default_and_removes_every_rule_line():
    sheet, decided, per = _apply(set())
    assert "RULE " not in sheet and decided == []
    assert 'FIXED "No previous imaging available for comparison."' in sheet
    assert 'FIXED "Images reviewed on PACS."' in sheet and 'NORMAL [liver] "The liver is normal."' in sheet
    assert "No contrast." not in sheet
    assert [e["outcome"] for e in per] == ["applied"] * 4 and not any(e["met"] for e in per)


def test_met_replace_rewrites_the_default_line_and_records_the_slot_line():
    sheet, decided, _ = _apply({PRIOR})
    assert ('FIXED "Comparison made with previous {study} dated {date}." | section: COMPARISON' in sheet)
    assert "No previous imaging available" not in sheet
    assert decided == ["Comparison made with previous {study} dated {date}."]


def test_met_use_becomes_a_fixed_line_in_place_and_met_suppress_removes_the_line():
    sheet, decided, _ = _apply({NOCON, OFFSITE, NOLIVER})
    assert 'FIXED "No contrast." | section: COMPARISON' in sheet
    assert "Images reviewed on PACS." not in sheet and "The liver is normal." not in sheet
    assert decided == []   # no slots


def test_the_resolved_sheet_still_lints_clean():
    for met in (set(), {PRIOR, NOCON, OFFSITE, NOLIVER}):
        sheet, _, _ = _apply(met)
        res = parse_sheet(sheet, mode="template")
        assert res.errors == [] and res.structure.usable


def test_target_match_ignores_case_spacing_and_the_final_full_stop():
    sheet = SHEET.replace('SUPPRESS "Images reviewed on PACS."', 'SUPPRESS "images  reviewed on PACS"')
    out, _, per = _apply({OFFSITE}, sheet)
    assert "Images reviewed on PACS." not in out
    assert next(e for e in per if e["condition"] == OFFSITE)["outcome"] == "applied"


def test_an_unmatched_target_leaves_the_rule_line_for_the_generator():
    sheet = SHEET.replace('SUPPRESS "Images reviewed on PACS."', 'SUPPRESS "A sentence in no unit line."')
    out, _, per = _apply({OFFSITE}, sheet)
    assert 'RULE WHEN [context: images were reviewed off site] SUPPRESS "A sentence in no unit line."' in out
    assert next(e for e in per if e["condition"] == OFFSITE)["outcome"] == "unmatched"


def test_two_met_rules_on_one_target_apply_the_first_and_leave_the_second():
    extra = ('RULE WHEN [context: the patient declined comparison] REPLACE '
             '"No previous imaging available for comparison." WITH "Comparison declined." | section: COMPARISON\n')
    sheet = SHEET.replace("FIXED \"Images reviewed on PACS.\"", extra + "FIXED \"Images reviewed on PACS.\"")
    out, _, per = _apply({PRIOR, "the patient declined comparison"}, sheet)
    assert "Comparison made with previous {study} dated {date}." in out and 'FIXED "Comparison declined."' not in out
    assert "RULE WHEN [context: the patient declined comparison]" in out
    assert [e["outcome"] for e in per if e["condition"] == "the patient declined comparison"] == ["conflict"]


def test_rules_outside_scope_are_untouched():
    sheet = SHEET.replace("## Paragraph: Liver (FINDINGS)",
                          "RULE WHEN [context: T2 imaging was not acquired] SUPPRESS_SECTION CONCLUSION | section: CONCLUSION\n\n"
                          "## Paragraph: Liver (FINDINGS)")
    out, _, per = _apply(set(), sheet)
    assert "SUPPRESS_SECTION CONCLUSION" in out and len(per) == 4
