"""apply_ledger: the ledger applied to a grammar sheet by code (Rules-step spec, "Decision ledger")."""
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import GOOD, LEDGER_SHEET


def _led(*changes):
    led = []
    for kind, key, choice in changes:
        led, _ = td.set_decision(led, kind, key, choice, source="creation", at="t")
    return led


def _clean(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def test_fixture_is_clean():
    _clean(LEDGER_SHEET)


def test_empty_ledger_or_non_grammar_sheet_is_unchanged():
    assert tla.apply_ledger(LEDGER_SHEET, []).sheet == LEDGER_SHEET
    led = _led(("value", "LVEF", {"need": "every"}))
    assert tla.apply_ledger("# Free\nprose", led).sheet == "# Free\nprose"


def test_every_values_are_inserted_under_report_wide():
    led = _led(("value", "LVEF", {"need": "every"}), ("value", "ECV", {"need": "relevant"}))
    res = tla.apply_ledger(LEDGER_SHEET, led)
    st = _clean(res.sheet)
    lm = [r for r in st.rules if r.effect == "list_missing"]
    assert [r.items for r in lm] == [["LVEF"]] and lm[0].section == "FINDINGS" and lm[0].position == "top"
    assert ('RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF"] AT TOP | section: FINDINGS'
            in res.sheet.split("## Report-wide")[1].split("## Paragraph")[0])
    assert res.applied == [{"kind": "value", "key": "*", "action": "inserted"}] and res.changed == 1


def test_a_sheet_without_report_wide_gets_the_block():
    res = tla.apply_ledger(GOOD, _led(("value", "Width", {"need": "every"})))
    assert "## Report-wide\nRULE WHEN" in res.sheet
    assert [r.items for r in _clean(res.sheet).rules if r.effect == "list_missing"] == [["Width"]]


def test_the_ledger_owns_the_list_existing_order_kept_extras_dropped():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["B" | "Extra" | "A"] '
        'AT END | section: FINDINGS\n')
    _clean(sheet)
    led = _led(("value", "a", {"need": "every"}), ("value", "b", {"need": "every"}), ("value", "C", {"need": "every"}),
               ("value", "Extra", {"need": "not_needed"}))
    res = tla.apply_ledger(sheet, led)
    lm = [r for r in _clean(res.sheet).rules if r.effect == "list_missing"]
    assert lm[0].items == ["b", "a", "C"] and lm[0].position == "end"   # sheet order, then new; ledger spelling
    assert res.applied[0]["action"] == "rewritten"


def test_no_every_value_removes_the_line():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["A"] AT TOP '
        '| section: FINDINGS\n')
    res = tla.apply_ledger(sheet, _led(("value", "A", {"need": "not_needed"})))
    assert "LIST_MISSING" not in res.sheet and res.applied[0]["action"] == "removed"


def test_apply_is_idempotent():
    led = _led(("value", "LVEF", {"need": "every"}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and again.changed == 0


from rapid_reports_ai import template_context_rules as tcr

PRIOR = "the dictation names a previous imaging study for comparison"
GIVEN = "the dictation states a contrast agent was given"
NOT_GIVEN = "the dictation states no contrast agent was given"
COMPARISON = {"use": True, "default": "No previous imaging available.",
              "when_met": "Compared with the previous {modality} of {date}.", "condition": PRIOR, "dictated": False}


def test_comparison_reuses_the_writers_fixed_line_and_adds_the_standard_rule():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison", COMPARISON)))
    st = _clean(res.sheet)
    rule = next(r for r in st.rules if r.condition_source == "context")
    assert (rule.condition, rule.effect, rule.target, rule.then_text) == (
        PRIOR, "replace", "No previous imaging available.", "Compared with the previous {modality} of {date}.")
    assert rule.paragraph == "p1"                      # where the writer's FIXED line was
    assert [f.text for f in st.fixed_blocks].count("No previous imaging available.") == 1
    assert res.applied == [{"kind": "concept", "key": "comparison", "action": "rewritten"}]


def test_item_one_resolves_the_comparison_concept_both_ways():
    sheet = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison", COMPARISON))).sheet
    rules = tcr.rules_in_scope(sheet)
    met, _, per = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert 'FIXED "Compared with the previous {modality} of {date}."' in met and per[0]["outcome"] == "applied"
    not_met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
    assert 'FIXED "No previous imaging available."' in not_met and "RULE WHEN" not in not_met


def test_a_default_only_concept_gets_a_drop_rule_item_one_resolves():
    # D2: every concept is found by its condition; the default line is dropped when the dictation contradicts it
    led = _led(("concept", "comparison", {"use": True, "default": "No previous imaging available.", "when_met": ""}))
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    rule = next(r for r in _clean(sheet).rules if r.condition_source == "context")
    assert (rule.condition, rule.effect, rule.target) == (PRIOR, "suppress", "No previous imaging available.")
    rules = tcr.rules_in_scope(sheet)
    met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert "No previous imaging available." not in met and "RULE WHEN" not in met
    not_met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
    assert 'FIXED "No previous imaging available."' in not_met


def test_contrast_takes_the_condition_opposite_its_default_either_way():
    usual_given = {"use": True, "default": "Following a contrast agent.", "when_met": "No contrast agent was given.",
                   "condition": NOT_GIVEN}
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "contrast", usual_given)))
    tech = res.sheet.split("## Paragraph: Technique (TECHNIQUE)")[1].split("## Paragraph:")[0]
    assert ('FIXED "Following a contrast agent."\nRULE WHEN [context: the dictation states no contrast agent was given] '
            'REPLACE "Following a contrast agent." WITH "No contrast agent was given."') in tech
    assert res.applied[0]["action"] == "inserted"
    # a non-contrast protocol: the usual line is the no-agent wording; the other replaces it only when dictated
    usual_none = {"use": True, "default": "No contrast agent was given.", "when_met": "Following a contrast agent.",
                  "condition": GIVEN}
    sheet = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "contrast", usual_none))).sheet
    rules = tcr.rules_in_scope(sheet)
    assert [r.condition for r in rules] == [GIVEN]
    assert 'FIXED "No contrast agent was given."' in tcr.apply_rules(sheet, rules, {GIVEN: False})[0]
    assert 'FIXED "Following a contrast agent."' in tcr.apply_rules(sheet, rules, {GIVEN: True})[0]
    # switching the stored polarity rewrites the pair; nothing doubles
    back = tla.apply_ledger(sheet, _led(("concept", "contrast", usual_given)))
    assert len(tcr.rules_in_scope(back.sheet)) == 1 and back.applied[0]["action"] == "rewritten"


def test_a_when_met_only_concept_is_a_use_rule():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "limitation",
                                              {"use": True, "default": "", "when_met": "The study is limited by {cause}."})))
    rule = next(r for r in _clean(res.sheet).rules if r.condition_source == "context")
    assert rule.effect == "use" and rule.then_text == "The study is limited by {cause}."


def test_not_used_or_dictated_removes_the_concept_lines_and_a_writer_rule_on_its_target():
    sheet = LEDGER_SHEET.replace(
        'FIXED "No previous imaging available."\n',
        'FIXED "No previous imaging available."\n'
        'RULE WHEN [context: prior imaging is available for comparison] REPLACE "No previous imaging available." '
        'WITH "Compared with prior."\n')
    _clean(sheet)
    used = tla.apply_ledger(sheet, _led(("concept", "comparison", COMPARISON))).sheet
    assert "prior imaging is available" not in used               # the writer's own rule on the same line is gone
    assert len([r for r in _clean(used).rules if r.condition_source == "context"]) == 1
    for choice in ({"use": False}, {"use": False, "dictated": True}):
        gone = tla.apply_ledger(used, _led(("concept", "comparison", choice)))
        assert "No previous imaging available." not in gone.sheet and "RULE WHEN" not in gone.sheet
        assert gone.applied[0]["action"] == "removed"


def test_report_wide_lines_keep_their_own_section_suffix():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nFIXED "No previous imaging available." | section: TECHNIQUE\n'
        'RULE WHEN [context: the dictation names a previous imaging study for comparison] REPLACE "No previous '
        'imaging available." WITH "Compared with prior."\n').replace('FIXED "No previous imaging available."\n\n', '\n')
    _clean(sheet)
    res = tla.apply_ledger(sheet, _led(("concept", "comparison", {**COMPARISON, "when_met": "Compared with {date}."})))
    wide = res.sheet.split("## Report-wide")[1].split("## Paragraph")[0]
    assert 'FIXED "No previous imaging available." | section: TECHNIQUE\n' in wide
    assert 'WITH "Compared with {date}."\n' in wide                    # no section added to the rule line
    assert _clean(res.sheet) and tla.apply_ledger(res.sheet, _led(("concept", "comparison",
                                                                   {**COMPARISON, "when_met": "Compared with {date}."}))).changed == 0


def test_concepts_are_idempotent():
    led = _led(("concept", "comparison", COMPARISON),
               ("concept", "contrast", {"use": True, "default": "With a contrast agent.", "when_met": "",
                                        "condition": NOT_GIVEN}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and again.changed == 0
