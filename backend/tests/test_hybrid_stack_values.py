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
    """The stated question (ask_values), asked for every item; used only for items no number mapped to."""
    async def ask(dictation, items, cands):
        if seen is not None:
            seen.update(stated_items=items, cands=cands)
        return answers
    return ask


def _nums(answers, seen=None):
    """The number -> item question: (item index or None, confidence) per number."""
    async def ask(dictation, mentions, items):
        if seen is not None:
            seen.update(mentions=mentions, items=items)
        return answers
    return ask


async def _never(*a):
    raise AssertionError("no call")


def test_number_mentions_mark_each_number_in_its_sentence():
    ms = V.number_mentions("LVEF 45%. LVEDVi 98 and LVESVi 40 ml/m2. Native T1 1,050 ms.")
    assert [(m.number, m.value, m.clause) for m in ms] == [
        ("45", "45%", "LVEF 45%."), ("98", "98", "LVEDVi 98 and LVESVi 40 ml/m2."),
        ("40", "40 ml/m2", "LVEDVi 98 and LVESVi 40 ml/m2."), ("1050", "1,050 ms", "Native T1 1,050 ms.")]
    assert ms[2].marked == "LVEDVi 98 and LVESVi [[40]] ml/m2."
    assert V.number_mentions("RV normal, RVEF 50%.")[0].marked == "RV normal, RVEF [[50]]%."


@pytest.mark.parametrize("dictation", [
    "T1 1010 ms (normal 891–1035)",
    "T1 1010 ms, normal range 891-1035 ms.",
    "T1 1010 ms; normal: 891 to 1035.",
    "T1 1010 ms normal (891–1035).",
    "T1 1010 ms, reference range (891-1035)",
])
def test_reference_range_ends_are_never_asked(dictation):
    assert [m.number for m in V.number_mentions(dictation)] == ["1010"]


@pytest.mark.parametrize("dictation,values", [
    ("Normal LV wall thickness (maximum 14 mm in the basal anteroseptum).", ["14 mm"]),   # not reference text
    ("LVEDV 230 ml (EDVi 120 ml/m2).", ["230 ml", "120 ml/m2"]),
    ("LVEF 62% (normal 55-70).", ["62%"]),
    ("LVEF 62% (ref 55%).", ["62%"]),
    ("LVEF 62%, normal 55.", ["62%"]),                       # a single reference number after "normal"
    ("Native T1 1010 ms (950-1050).", ["1010 ms"]),          # a bare bracketed range without a unit
    ("LVEF normal 55-60%.", ["55%", "60%"]),                 # a measured range: no reference word, a unit
    ("LVEF 58%, normal range 55-60%.", ["58%"]),             # a reference word follows "normal"
])
def test_only_reference_text_is_masked(dictation, values):
    assert [m.value for m in V.number_mentions(dictation)] == values


def test_a_reference_limit_after_a_reference_word_is_masked():
    assert [m.number for m in V.number_mentions("Left atrium 20 cm2, normal value <24 cm2.")] == ["20"]


def test_words_starting_like_a_month_are_not_dates():
    assert [m.value for m in V.number_mentions("Mid infero-septal 1070 ms.")] == ["1070 ms"]
    assert [m.number for m in V.number_mentions("Marked 1200 ms. Decreased 900 ms.")] == ["1200", "900"]
    assert not V.has_number("Scanned Sept 2024, 12 October 2024 and Dec 2023.")


async def test_each_number_fills_the_item_jev_maps_it_to():
    seen = {}
    d = "Normal LV size, LVEF 45%. RV normal. LVEDVi 98 and LVESVi 40 ml/m2."
    res = await V.smart_fill(d, ["LVEF", "LVEDVi", "RVEF"], ask=_ask([(0.9, None), (0.9, None), (0.2, None)], seen),
                             ask_numbers=_nums([(0, 0.9), (1, 0.8), (None, 0.7)], seen))
    assert seen["mentions"] == [("45", "Normal LV size, LVEF [[45]]%."),
                                ("98", "LVEDVi [[98]] and LVESVi 40 ml/m2."), ("40", "LVEDVi 98 and LVESVi [[40]] ml/m2.")]
    assert seen["stated_items"] == ["LVEF", "LVEDVi", "RVEF"] and seen["cands"] == []   # all items, in parallel
    lvef, lvedvi, rvef = [v.model_dump() for v in res.values]
    assert lvef == {"item": "LVEF", "state": "filled", "value": "45%", "quote": "LVEF 45%.", "score": 0.9, "picks": []}
    assert (lvedvi["state"], lvedvi["value"], lvedvi["quote"]) == ("filled", "98", "LVEDVi 98 and LVESVi 40 ml/m2.")
    assert rvef["state"] == "open" and [p["clause"] for p in rvef["picks"]] == ["LVEF 45%.", "LVEDVi 98 and LVESVi 40 ml/m2."]
    assert res.error is None


async def test_two_numbers_on_one_item_keep_the_most_confident_as_a_check_chip_with_the_alternatives():
    d = "LVEF 45%. Previously LVEF 55%."
    res = await V.smart_fill(d, ["LVEF"], ask=_ask([(0.9, None)]), ask_numbers=_nums([(0, 0.6), (0, 0.9)]))
    [v] = res.values
    assert (v.state, v.value, v.quote, v.score) == ("check", "55%", "Previously LVEF 55%.", 0.9)
    assert [(p.clause, p.value) for p in v.picks] == [("Previously LVEF 55%.", "55%"), ("LVEF 45%.", "45%")]


async def test_an_item_no_number_maps_to_keeps_the_strict_stated_question():
    d = "Conus terminates at L1. LVEF 45%."
    res = await V.smart_fill(d, ["Conus level", "LVEF"], ask=_ask([(0.8, None), (0.1, None)]), ask_numbers=_nums([(1, 0.9)]))
    assert (res.values[0].state, res.values[0].value, res.values[0].quote) == ("filled", None, None)   # "stated?"
    res = await V.smart_fill(d, ["Conus level", "LVEF"], ask=_ask([(0.79, None), (0.1, None)]), ask_numbers=_nums([(1, 0.9)]))
    assert res.values[0].state == "open" and V.VALUE_UNQUOTED_MIN == 0.8


async def test_a_dictation_without_numbers_asks_only_the_stated_question():
    seen = {}
    res = await V.smart_fill("Conus terminates normally.", ["Conus level"], ask=_ask([(0.9, None)], seen),
                             ask_numbers=_never)
    assert seen["stated_items"] == ["Conus level"] and res.values[0].state == "filled"


async def test_a_jev_failure_or_a_short_reply_leaves_every_chip_open_with_picks():
    async def boom(*a):
        raise RuntimeError("jev down")
    d = "LVEF 45%."
    res = await V.smart_fill(d, ["LVEF", "RVEF"], ask=_ask([(0.1, None)] * 2), ask_numbers=boom)
    assert [v.state for v in res.values] == ["open", "open"] and "RuntimeError" in res.error
    assert [p.clause for p in res.values[0].picks] == ["LVEF 45%."]
    res = await V.smart_fill(d, ["LVEF", "RVEF"], ask=boom, ask_numbers=_nums([(0, 0.9)]))
    assert [v.state for v in res.values] == ["open", "open"] and "RuntimeError" in res.error
    res = await V.smart_fill(d, ["LVEF", "RVEF"], ask=_ask([]), ask_numbers=_nums([]))
    assert [v.state for v in res.values] == ["open", "open"] and res.error == "jev: answer count mismatch"
    res = await V.smart_fill(d, ["LVEF", "RVEF"], ask=_ask([]), ask_numbers=_nums([(0, 0.9)]))
    assert [v.state for v in res.values] == ["open", "open"] and res.error == "jev: answer count mismatch"


async def test_no_items_or_no_dictation_asks_nothing():
    assert (await V.smart_fill("LVEF 45%.", [], ask=_never, ask_numbers=_never)).values == []
    res = await V.smart_fill("  ", ["LVEF"], ask=_never, ask_numbers=_never)
    assert [v.state for v in res.values] == ["open"] and res.error is None


async def test_the_default_asks_are_the_jev_calls(monkeypatch):
    seen = {}

    async def numbers(dictation, mentions, items):
        seen["mentions"] = mentions
        return [(0, 0.9)]

    async def stated(dictation, items, cands):
        seen["stated"] = items
        return [(0.9, None, None), (0.1, None, None)]
    monkeypatch.setattr(V, "ask_number_items", numbers)
    monkeypatch.setattr(V, "ask_values", stated)
    res = await V.smart_fill("LVEF 45%.", ["LVEF", "RVEF"])
    assert seen == {"mentions": [("45", "LVEF [[45]]%.")], "stated": ["LVEF", "RVEF"]} and res.values[0].value == "45%"


async def test_numbers_are_capped_and_picks_stay_capped():
    seen = {}
    d = " ".join(f"Value {i} is {i}." for i in range(1, 100))
    res = await V.smart_fill(d, ["LVEF"], ask=_ask([(0.1, None)]), ask_numbers=_nums([(None, 0.5)] * 60, seen))
    assert V.MAX_NUMBERS == 60 and len(seen["mentions"]) == 60
    assert V.MAX_PICKS == 8 and [p.clause for p in res.values[0].picks] == [f"Value {i} is {i}." for i in range(1, 9)]


@pytest.mark.parametrize("clause,value", [
    ("LA 20 cm2", "20 cm²"),
    ("LA area 20 cm^2", "20 cm²"),
    ("LA area 20.5 cm²", "20.5 cm²"),
    ("AVA 85 mm2", "85 mm²"),
])
def test_area_units_are_read_and_written_as_squared(clause, value):
    assert V.read_value(clause) == value


@pytest.mark.parametrize("clause,numbers", [
    ("LVEDVi 98 and LVESVi 40 ml/m2", ["98", "40 ml/m2"]),         # another word between: not shared
    ("LVEDVi and LVESVi 98 and 40 ml/m2", ["98 ml/m2", "40 ml/m2"]),   # a trailing unit is shared
    ("EF 45-50%", ["45%", "50%"]),
    ("LVEF 45% and LVEDVi 98", ["45%", "98"]),                      # a unit never reaches back to an earlier number
    ("volume at 87 with normal systolic function of 64%", ["87", "64%"]),   # only across "and", "-", "to", "x", "/"
    ("3 x 4 x 5 cm", ["3 cm", "4 cm", "5 cm"]),
    ("22 to 25 mm", ["22 mm", "25 mm"]),
    ("LVEF 45%", ["45%"]),
    ("No late gadolinium enhancement", []),
])
def test_read_numbers_gives_every_number_with_its_unit(clause, numbers):
    assert V.read_numbers(clause) == numbers



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



async def test_a_conflict_of_the_same_value_fills():
    res = await V.smart_fill("Ascending aorta 22 x 22 mm.", ["Ascending aorta diameter"], ask=_ask([(0.1, None)]),
                             ask_numbers=_nums([(0, 0.7), (0, 0.9)]))
    [v] = res.values
    assert (v.state, v.value, v.picks) == ("filled", "22 mm", [])


async def test_open_chip_picks_rank_by_the_items_probability_then_dictation_order():
    d = "LVEF 45%. RV dilated, 120 ml/m2. Mass 60 g/m2."
    ans = [(0, 0.9, [0.9, 0.05]), (None, 0.5, [0.1, 0.4]), (None, 0.8, [0.0, 0.1])]
    res = await V.smart_fill(d, ["LVEF", "RVEDVi"], ask=_ask([(0.1, None)] * 2), ask_numbers=_nums(ans))
    assert [p.clause for p in res.values[1].picks] == ["120 ml/m2.", "Mass 60 g/m2.", "LVEF 45%."]


async def test_the_stated_question_runs_with_the_number_calls_for_every_item():
    import asyncio
    seen, order = {}, []

    async def numbers(dictation, mentions, items):
        order.append("numbers start")
        await asyncio.sleep(0)
        order.append("numbers end")
        return [(0, 0.9)]

    async def stated(dictation, items, cands):
        order.append("stated start")
        seen["items"] = items
        return [(0.95, None), (0.9, None)]
    res = await V.smart_fill("LVEF 45%.", ["LVEF", "Conus level"], ask=stated, ask_numbers=numbers)
    assert seen["items"] == ["LVEF", "Conus level"] and order.index("stated start") < order.index("numbers end")
    assert (res.values[0].state, res.values[0].value) == ("filled", "45%")   # the mapped item's stated answer is dropped
    assert (res.values[1].state, res.values[1].quote) == ("filled", None)
