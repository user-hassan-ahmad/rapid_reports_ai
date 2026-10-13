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
