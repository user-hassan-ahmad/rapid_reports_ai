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
    picks = [{"clause": "LVEF 45%.", "value": "45%", "numbers": []},
             {"clause": "LVEDVi 98 and LVESVi 40 ml/m2.", "value": None, "numbers": ["98 ml/m2", "40 ml/m2"]}]
    assert [v.model_dump() for v in res.values] == [
        {"item": "LVEF", "state": "filled", "value": "45%", "quote": "LVEF 45%.", "score": 0.95, "numbers": [],
         "picks": []},
        {"item": "LVEDVi", "state": "filled", "value": None, "quote": "LVEDVi 98 and LVESVi 40 ml/m2.", "score": 0.9,
         "numbers": ["98 ml/m2", "40 ml/m2"], "picks": []},
        {"item": "RVEF", "state": "open", "value": None, "quote": None, "score": 0.1, "numbers": [], "picks": picks}]
    assert res.error is None


async def test_stated_without_a_named_clause_is_filled_without_a_value_or_quote():
    res = await V.smart_fill("Conus terminates at L1.", ["Conus level"], ask=_ask([(0.9, None)]))
    [v] = res.values
    assert (v.state, v.value, v.quote) == ("filled", None, None)   # the chip asks for a look (frontend "check")


async def test_below_the_cut_off_is_open():
    res = await V.smart_fill("EF 45.", ["LVEF"], ask=_ask([(V.VALUE_STATED_MIN - 0.01, 0)]))
    assert res.values[0].state == "open" and res.values[0].value is None


async def test_a_named_clause_fills_from_the_low_bar():
    """Hassan 2026-10-13, after the lab: a named clause and p >= 0.3 fills (the clause question carries the precision)."""
    assert V.VALUE_STATED_MIN == 0.3 and V.VALUE_UNQUOTED_MIN == 0.8
    res = await V.smart_fill("EF 45.", ["LVEF"], ask=_ask([(0.3, 0)]))
    assert (res.values[0].state, res.values[0].value, res.values[0].quote) == ("filled", "45", "EF 45.")
    res = await V.smart_fill("EF 45.", ["LVEF"], ask=_ask([(0.55, 0)]))
    assert res.values[0].state == "filled"


async def test_no_clause_named_keeps_the_strict_bar_for_a_stated_chip():
    res = await V.smart_fill("Conus terminates at L1.", ["Conus level"], ask=_ask([(0.79, None)]))
    assert res.values[0].state == "open"                      # p >= 0.3 but no clause and below 0.8: open
    res = await V.smart_fill("Conus terminates at L1.", ["Conus level"], ask=_ask([(0.8, None)]))
    assert (res.values[0].state, res.values[0].quote) == ("filled", None)   # the "stated?" chip
    res = await V.smart_fill("EF 45.", ["LVEF"], ask=_ask([(0.29, None)]))
    assert res.values[0].state == "open"


@pytest.mark.parametrize("clause,value", [
    ("LA 20 cm2", "20 cm²"),
    ("LA area 20 cm^2", "20 cm²"),
    ("LA area 20.5 cm²", "20.5 cm²"),
    ("AVA 85 mm2", "85 mm²"),
])
def test_area_units_are_read_and_written_as_squared(clause, value):
    assert V.read_value(clause) == value


@pytest.mark.parametrize("clause,numbers", [
    ("LVEDVi 98 and LVESVi 40 ml/m2", ["98 ml/m2", "40 ml/m2"]),   # a trailing unit is shared
    ("EF 45-50%", ["45%", "50%"]),
    ("LVEF 45% and LVEDVi 98", ["45%", "98"]),                      # a unit never reaches back to an earlier number
    ("LVEF 45%", ["45%"]),
    ("No late gadolinium enhancement", []),
])
def test_read_numbers_gives_every_number_with_its_unit(clause, numbers):
    assert V.read_numbers(clause) == numbers


async def test_a_named_clause_with_two_numbers_offers_them_to_pick():
    d = "LVEDVi 98 and LVESVi 40 ml/m2."
    res = await V.smart_fill(d, ["LVEDVi"], ask=_ask([(0.9, 0)]))
    [v] = res.values
    assert (v.state, v.value, v.numbers) == ("filled", None, ["98 ml/m2", "40 ml/m2"])


async def test_an_open_chip_offers_the_number_clauses_ranked_by_the_where_scores():
    d = "LVEF 45%. RVEF 50%. LV mass 60 g/m2. Normal valves."
    res = await V.smart_fill(d, ["RVEF", "LV mass"], ask=_ask([(0.1, None, [0.1, 0.7, 0.2]), (0.2, 2)]))
    rvef, mass = res.values
    assert [p.clause for p in rvef.picks] == ["RVEF 50%.", "LV mass 60 g/m2.", "LVEF 45%."]
    assert rvef.picks[0].value == "50%"
    assert [p.clause for p in mass.picks] == ["LVEF 45%.", "RVEF 50%.", "LV mass 60 g/m2."]   # no scores: dictation order


async def test_picks_are_capped_and_offered_when_jev_fails():
    d = " ".join(f"Value {i} is {i}." for i in range(1, 20))

    async def boom(*a):
        raise RuntimeError("jev down")
    res = await V.smart_fill(d, ["LVEF"], ask=boom)
    assert V.MAX_PICKS == 8 and [p.clause for p in res.values[0].picks] == [f"Value {i} is {i}." for i in range(1, 9)]


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
