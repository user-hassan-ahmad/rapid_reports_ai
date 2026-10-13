import pytest

from rapid_reports_ai.hybrid_stack import values as V


@pytest.mark.parametrize("clause,value", [
    ("EF 45", "45"),
    ("ejection fraction mildly reduced at 45", "45"),
    ("LVEF=61%", "61%"),
    ("LVEF 55 %", "55%"),
    ("LVEF 45 percent", "45%"),
    ("LVEF 45.5%.", "45.5%"),
    ("LVEDVi 98 ml/m2", "98 ml/m2"),
    ("LVEDVi 98 mL/m^2", "98 mL/m^2"),
    ("LV mass index 60 g/m²", "60 g/m²"),
    ("aortic root 3.4 cm", "3.4 cm"),
    ("native T1 1,050 ms", "1,050 ms"),
    ("dated 02/12/2025 EF 50%", "50%"),
])
def test_read_value_reads_the_one_number_and_its_unit(clause, value):
    assert V.read_value(clause) == value


@pytest.mark.parametrize("clause", [
    "LVEDVi 98 and LVESVi 40 ml/m2",       # two numbers: stated, no single value
    "EF 45-50%",                           # a range
    "Conus terminates at L1/2",            # an identifier, not a measurement
    "No late gadolinium enhancement",
    "",
])
def test_read_value_gives_nothing_unless_exactly_one_number(clause):
    assert V.read_value(clause) is None


def test_identifiers_dates_and_times_are_not_numbers():
    assert not V.has_number("T2 and STIR sequences at L4/5")
    assert not V.has_number("Scanned 02/12/2025 at 10:30")
    assert V.has_number("RVEF 50%")


def test_clauses_split_sentences_at_commas_and_semicolons_but_not_inside_numbers():
    text = "LVEF 45%. LVEDVi 98 ml/m2, LVESVi 40 ml/m2; normal wall thickness.\nNative T1 1,050 ms."
    assert V.clauses(text) == ["LVEF 45%.", "LVEDVi 98 ml/m2", "LVESVi 40 ml/m2", "normal wall thickness.",
                               "Native T1 1,050 ms."]
    assert V.clauses("") == []


from rapid_reports_ai.hybrid_stack.template import template_required_values
from rapid_reports_ai.template_sheet_grammar import parse_sheet

VALUES_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
"""


def test_required_values_are_the_list_missing_items_in_sheet_order_once():
    st = parse_sheet(VALUES_SHEET, mode="template").structure
    assert template_required_values(st) == ["LVEF", "LV mass index", "RVEF"]
    two = VALUES_SHEET + 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["lvef" | "LV wall thickness"] AT END\n'
    st = parse_sheet(two, mode="template").structure
    assert template_required_values(st) == ["LVEF", "LV mass index", "RVEF", "LV wall thickness"]
    plain = VALUES_SHEET.replace(
        'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP\n', "")
    assert template_required_values(parse_sheet(plain, mode="template").structure) == []


def _ask(answers, seen=None):
    async def ask(dictation, items, cands):
        if seen is not None:
            seen.update(dictation=dictation, items=items, cands=cands)
        return answers
    return ask


async def test_smart_fill_reads_the_number_from_the_clause_jev_names():
    seen = {}
    d = "Normal LV size, LVEF 45%. RV normal. LVEDVi 98 and LVESVi 40 ml/m2."
    res = await V.smart_fill(d, ["LVEF", "LVEDVi", "RVEF"], ask=_ask([(0.95, 0), (0.9, 1), (0.1, None)], seen))
    assert seen["cands"] == ["LVEF 45%.", "LVEDVi 98 and LVESVi 40 ml/m2."]   # only clauses holding a number
    assert [v.model_dump() for v in res.values] == [
        {"item": "LVEF", "state": "filled", "value": "45%", "quote": "LVEF 45%.", "score": 0.95},
        {"item": "LVEDVi", "state": "filled", "value": None, "quote": "LVEDVi 98 and LVESVi 40 ml/m2.", "score": 0.9},
        {"item": "RVEF", "state": "open", "value": None, "quote": None, "score": 0.1}]
    assert res.error is None


async def test_stated_without_a_named_clause_is_filled_without_a_value_or_quote():
    res = await V.smart_fill("Conus terminates at L1.", ["Conus level"], ask=_ask([(0.9, None)]))
    [v] = res.values
    assert (v.state, v.value, v.quote) == ("filled", None, None)   # the chip asks for a look (frontend "check")


async def test_below_the_cut_off_is_open():
    res = await V.smart_fill("EF 45.", ["LVEF"], ask=_ask([(V.VALUE_STATED_MIN - 0.01, 0)]))
    assert res.values[0].state == "open" and res.values[0].value is None


async def test_a_jev_failure_or_a_short_reply_leaves_every_chip_open():
    async def boom(*a):
        raise RuntimeError("jev down")
    res = await V.smart_fill("LVEF 45%.", ["LVEF", "RVEF"], ask=boom)
    assert [v.state for v in res.values] == ["open", "open"] and "RuntimeError" in res.error
    res = await V.smart_fill("LVEF 45%.", ["LVEF", "RVEF"], ask=_ask([(0.9, 0)]))
    assert [v.state for v in res.values] == ["open", "open"] and res.error == "jev: answer count mismatch"


async def test_no_items_or_no_dictation_asks_nothing():
    async def fail(*a):
        raise AssertionError("no call")
    assert (await V.smart_fill("LVEF 45%.", [], ask=fail)).values == []
    res = await V.smart_fill("  ", ["LVEF"], ask=fail)
    assert [v.state for v in res.values] == ["open"] and res.error is None


async def test_the_default_ask_is_the_jev_call(monkeypatch):
    seen = {}

    async def fake(dictation, items, cands):
        seen["items"] = items
        return [(0.9, 0)]
    monkeypatch.setattr(V, "ask_values", fake)
    res = await V.smart_fill("LVEF 45%.", ["LVEF"])
    assert seen["items"] == ["LVEF"] and res.values[0].value == "45%"


async def test_clauses_are_capped_at_max_clauses():
    seen = {}
    d = " ".join(f"Value {i} is {i}." for i in range(1, 100))
    await V.smart_fill(d, ["LVEF"], ask=_ask([(0.1, None)], seen))
    assert V.MAX_CLAUSES == 80 and len(seen["cands"]) == 80


@pytest.mark.parametrize("clause,value", [
    ("GLS -18%", "-18%"),
    ("GLS -18.5 %", "-18.5%"),
    ("strain +3", "+3"),
    ("GLS (−18%)", "−18%"),
    ("PA 25 mm Hg", "25 mmHg"),
    ("PA 25 mmHg", "25 mmHg"),
    ("LVEDVi 98 mls/m2", "98 mls/m2"),
    ("native T1 1050 msec", "1050 msec"),
    ("LVEF 45 % (normal 55)", "45%"),
])
def test_read_value_keeps_signs_pressure_units_and_ignores_bracketed_ranges(clause, value):
    assert V.read_value(clause) == value


async def test_exactly_the_cut_off_is_filled():
    res = await V.smart_fill("EF 45.", ["LVEF"], ask=_ask([(V.VALUE_STATED_MIN, 0)]))
    assert res.values[0].state == "filled" and res.values[0].value == "45"
