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


def _ask(scores: dict, calls: list | None = None):
    async def ask(state, conditions):
        if calls is not None:
            calls.append((state, list(conditions)))
        return [scores.get(c, 0.0) for c in conditions]
    return ask


async def test_resolve_asks_each_distinct_condition_once_on_history_and_findings():
    calls: list = []
    res = await cr.resolve_context_rules(SHEET, "?lesion", "Compared with the CT of 02/12/2025.",
                                         ask=_ask({PRIOR: 0.9}, calls))
    (state, conds), = calls
    assert conds == [PRIOR, NOCON, OFFSITE, NOLIVER]
    assert state == "CLINICAL HISTORY:\n?lesion\nDICTATED FINDINGS:\nCompared with the CT of 02/12/2025."
    assert "Comparison made with previous {study} dated {date}." in res.sheet
    assert res.decided == ["Comparison made with previous {study} dated {date}."]
    rec = res.record
    assert rec["asked"] == 4 and rec["error"] is None and rec["skipped"] is None and rec["slot_leaks"] == 0
    first = rec["rules"][0]
    assert first == {"line": 8, "condition": PRIOR, "effect": "replace", "met": True, "score": 0.9,
                     "outcome": "applied"}


async def test_the_cut_off_is_the_scratchpads_and_silence_is_not_met():
    res = await cr.resolve_context_rules(SHEET, "", "Liver normal.", ask=_ask({PRIOR: 0.49, NOCON: 0.5}))
    assert "No previous imaging available for comparison." in res.sheet
    assert 'FIXED "No contrast."' in res.sheet
    assert "(not given)" not in res.sheet   # the history placeholder is state only


async def test_a_jev_failure_leaves_the_stored_sheet_unchanged():
    async def down(state, conditions):
        raise RuntimeError("jev 503")
    res = await cr.resolve_context_rules(SHEET, "", "x", ask=down)
    assert res.sheet == SHEET and res.decided == []
    assert res.record["error"].startswith("RuntimeError: jev 503") and res.record["rules"] == []


async def test_a_non_grammar_sheet_or_a_sheet_without_rules_asks_nothing():
    calls: list = []
    legacy = "# Skill Sheet\nSome prose only.\n"
    res = await cr.resolve_context_rules(legacy, "", "x", ask=_ask({}, calls))
    assert res.sheet == legacy and res.record["skipped"] == "parse" and calls == []
    bare = SHEET.split("## Report-wide")[0] + "## Paragraph: Liver (FINDINGS)\nCOVERS [\"liver\"]\n"
    res = await cr.resolve_context_rules(bare, "", "x", ask=_ask({}, calls))
    assert res.sheet == bare and res.record["skipped"] == "no_rules" and calls == []


LIVER_SUPPRESS = 'RULE WHEN [context: the liver was not imaged] SUPPRESS "The liver is normal."'


async def test_on_stack_a_findings_section_rule_is_left_as_written_and_not_asked():
    calls: list = []
    res = await cr.resolve_context_rules(SHEET, "", "x", ask=_ask({NOLIVER: 0.9}, calls), stack=True)
    (_, conds), = calls
    assert conds == [PRIOR, NOCON, OFFSITE]
    assert LIVER_SUPPRESS in res.sheet and 'NORMAL [liver] "The liver is normal."' in res.sheet
    left = res.record["rules"][-1]
    assert left == {"line": 16, "condition": NOLIVER, "effect": "suppress", "met": None, "score": None,
                    "outcome": "left_stack"}
    assert res.record["asked"] == 3


async def test_on_stack_a_replace_of_a_normal_or_negative_line_is_left_and_applied_off_stack():
    liver = SHEET.replace(LIVER_SUPPRESS, 'RULE WHEN [context: the liver was not imaged] REPLACE '
                                          '"The liver is normal." WITH "The liver was not imaged."')
    neg = SHEET.replace('FIXED "Images reviewed on PACS." | section: COMPARISON',
                        'NEGATIVE "No prior imaging." | section: COMPARISON\n'
                        'RULE WHEN [context: a prior CT was seen] REPLACE "No prior imaging." WITH "Prior CT seen." '
                        '| section: COMPARISON\nFIXED "Images reviewed on PACS." | section: COMPARISON')
    for sheet, cond, rule_text, written in (
            (liver, NOLIVER, "REPLACE \"The liver is normal.\"", "The liver was not imaged."),
            (neg, "a prior CT was seen", "REPLACE \"No prior imaging.\"", "Prior CT seen.")):
        on = await cr.resolve_context_rules(sheet, "", "x", ask=_ask({cond: 0.9}), stack=True)
        assert rule_text in on.sheet
        assert next(e for e in on.record["rules"] if e["condition"] == cond)["outcome"] == "left_stack"
        off = await cr.resolve_context_rules(sheet, "", "x", ask=_ask({cond: 0.9}))
        assert rule_text not in off.sheet and written in off.sheet


async def test_on_stack_a_use_rule_in_a_findings_paragraph_is_left():
    rule = 'RULE WHEN [context: the liver was resected] USE "The liver has been resected."'
    sheet = SHEET.replace('NORMAL [liver]', rule + "\nNORMAL [liver]")
    res = await cr.resolve_context_rules(sheet, "", "x", ask=_ask({"the liver was resected": 0.9}), stack=True)
    assert rule in res.sheet and 'FIXED "The liver has been resected."' not in res.sheet


async def test_jev_reads_only_what_the_radiologist_dictated():
    calls: list = []
    findings = ("DO NOT ASSERT (removed by the radiologist): Compared with MRI 01/01/2024.\n"
                "  Assumed normal (confirmed by the radiologist): The spleen is normal.\n"
                "Confirmed normal (not dictated; confirmed by the radiologist): The kidneys are normal.\n"
                "Compared with CT 02/12/2025.")
    await cr.resolve_context_rules(SHEET, "", findings, ask=_ask({}, calls))
    (state, _), = calls
    assert state.endswith("DICTATED FINDINGS:\nCompared with CT 02/12/2025.")


def test_jev_findings_cuts_a_mid_line_assumed_tail_and_drops_a_bare_label():
    mid = ("Liver: Compared with CT 02/12/2025. Assumed normal (confirmed by the radiologist): "
           "No previous imaging available for comparison.")
    assert cr.jev_findings(mid) == "Liver: Compared with CT 02/12/2025."
    bare = "Spleen: Assumed normal (confirmed by the radiologist): The spleen is normal.\nKidneys: Normal."
    assert cr.jev_findings(bare) == "Kidneys: Normal."
    answered = "Liver: 2 cm cyst. Answered by the radiologist: segment 4."
    assert cr.jev_findings(answered) == answered


def test_decided_block_lists_each_slot_line_once_with_the_partial_fill_instruction():
    assert cr.decided_block([]) == ""
    block = cr.decided_block(["Compared with the {study} of {date}.", "Compared with the {study} of {date}."])
    assert block.startswith(cr.DECIDED_HEADING + "\n")
    assert block.count('- "Compared with the {study} of {date}."') == 1
    assert "leave out the words that carry it" in block


def test_slot_guard_removes_only_the_sentence_holding_a_slot():
    report = ("Comparison: Comparison made with previous CT dated {date}.\n"
              "Findings: The liver is normal. A {size} cyst. No ascites.\n"
              "- Note made of previous {study}.\n"
              "Conclusion: Normal study.")
    out, n = cr.strip_slot_sentences(report, {"Comparison:"})
    assert n == 3
    assert out == "Comparison:\nFindings: The liver is normal. No ascites.\nConclusion: Normal study."


def test_slot_guard_keeps_a_bare_lead_only_when_it_is_a_declared_header():
    report = "Medication given: {medication}.\nScan quality: {quality}\nAverage HR: {rate} bpm.\nFindings: Normal."
    assert cr.strip_slot_sentences(report, {"Findings:"}) == ("Findings: Normal.", 3)
    bold = "**Comparison:** Comparison made with previous CT dated {date}. Stable."
    assert cr.strip_slot_sentences(bold) == ("**Comparison:** Stable.", 1)
    line = "Comparison: Comparison made with previous CT dated {date}."
    assert cr.strip_slot_sentences(line, {"Comparison:"}) == ("Comparison:", 1)
    assert cr.strip_slot_sentences(line) == ("", 1)
    assert cr.strip_slot_sentences("- Note made of previous {study}.") == ("", 1)


def test_slot_guard_leaves_a_report_without_slots_untouched():
    report = "Findings: Normal.\n\nConclusion: Normal study."
    assert cr.strip_slot_sentences(report) == (report, 0)


def test_sheet_headers_are_the_declared_section_and_paragraph_headers():
    assert cr.sheet_headers(SHEET) == {"Comparison:", "Findings:", "Conclusion:"}
    assert cr.sheet_headers("# Skill Sheet\nSome prose only.\n") == set()
