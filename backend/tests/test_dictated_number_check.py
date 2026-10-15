"""Dictated number fidelity (spec 2026-10-15): every number the radiologist dictated appears in the report. SYNTHETIC."""
import pytest

from rapid_reports_ai.dictated_number_check import KIND, enabled, extract, missing_dictated_numbers


def vals(text):
    return [(n.value, n.unit) for n in extract(text)]


def missing(report, *sources):
    return [i["text"] for i in missing_dictated_numbers(report, list(sources))]


# --- extraction ---

def test_integers_decimals_and_leading_dot_decimals():
    assert vals("LVEF 62%, ratio .14 and 0.5 cm") == [(62.0, "%"), (0.14, None), (0.5, "cm")]


def test_a_chain_shares_the_unit_after_its_last_number():
    assert vals("2.3 x 1.8 cm") == [(2.3, "cm"), (1.8, "cm")]
    assert vals("stenosis 50-69%") == [(50.0, "%"), (69.0, "%")]
    assert vals("heart rate 64 to 88 bpm") == [(64.0, "bpm"), (88.0, "bpm")]
    assert vals("BP 132/78 to 118/70 mmHg") == [(132.0, "mmhg"), (78.0, "mmhg"), (118.0, "mmhg"), (70.0, "mmhg")]
    assert vals("3x4 mm") == [(3.0, "mm"), (4.0, "mm")]


def test_unit_spellings_normalise():
    assert vals("140 micrograms per kg per minute") == vals("140 mcg/kg/min") == [(140.0, "mcg/kg/min")]
    assert vals("800 micrograms") == vals("800 mcg") == [(800.0, "mcg")]
    assert vals("245 mGy·cm") == vals("245 mGycm") == vals("245 mGy.cm") == vals("245 mGy cm") == [(245.0, "mgycm")]
    assert vals("78 ml/m²") == vals("78 mL/m2") == [(78.0, "ml/m2")]
    assert vals("4 minutes") == vals("4 min") == [(4.0, "min")]
    assert vals("5 millimetres") == [(5.0, "mm")]


def test_thousands_separators_read_as_one_number():
    assert vals("Agatston 1,260") == [(1260.0, None)]


def test_identifiers_dates_times_and_list_markers_are_not_numbers():
    assert vals("T2 STIR, L4/5 disc, b1000, S1") == []
    assert vals("compared with 12/03/2025 at 10:30") == []
    assert vals("1. Normal study.") == []


def test_no_number_words_from_the_dictation():
    assert vals("two lesions, one cyst") == []


# --- matching ---

def test_present_numbers_raise_nothing():
    assert missing("Heart rate 64 to 88 bpm.", "HR 64 to 88 bpm.") == []


def test_a_dropped_number_is_flagged_with_its_dictated_sentence():
    out = missing_dictated_numbers("Adenosine stress perfusion was performed.",
                                   ["Adenosine 140 mcg/kg/min for 4 minutes."])
    assert [(i["kind"], i["text"], i["severity"]) for i in out] == [
        (KIND, "140 mcg/kg/min", "high"), (KIND, "4 minutes", "high")]
    assert out[0]["sentence"] == "Adenosine 140 mcg/kg/min for 4 minutes."
    assert out[0]["message"] == "Dictated number not in the report: 140 mcg/kg/min"


@pytest.mark.parametrize("dictated, report", [
    ("1.5 m/s", "15 m/s"), ("15 mm", "1.5 mm"), ("5 mm", ".5 mm"), ("0.5 cm", "5 cm")])
def test_adversarial_values_never_match(dictated, report):
    assert missing(f"Measures {report}.", f"Measures {dictated}.") == [dictated]


def test_formatting_variants_match():
    assert missing("ECV .14.", "ECV 0.14.") == []
    assert missing("ECV 0.140.", "ECV .14.") == []
    assert missing("Total radiation dose: 245 mGy·cm.", "DLP 245 mGycm.") == []
    assert missing("Stenosis (50–69%).", "stenosis 50-69%.") == []
    assert missing("Agatston score 1260.", "Agatston 1,260.") == []


def test_a_different_unit_is_a_miss_and_there_is_no_conversion():
    assert missing("Node 9 cm.", "Node 9 mm.") == ["9 mm"]
    assert missing("Nodule 0.5 cm.", "Nodule 5 mm.") == ["5 mm"]


def test_a_dictated_unit_needs_the_same_unit_in_the_report():   # Q1: a bare report number no longer matches
    assert missing("The wall is thinned to 5 in segment 4.", "Wall 5 mm.") == ["5 mm"]
    assert missing("Perfusion defect in segment 4.", "Defect in segment 4 after 4 minutes.") == ["4 minutes"]


def test_each_report_number_satisfies_one_dictated_number():
    assert missing("Two nodules of 4 mm.", "Nodules 4 mm and 4 mm.") == ["4 mm"]
    assert missing("Nodules of 4 mm and 4 mm.", "Nodules 4 mm and 4 mm.") == []
    assert missing("Nodule 4 x 4 mm.", "Nodule 4 x 4 mm.") == []
    assert missing("Nodule 4 mm.", "Nodule 4 x 4 mm.") == ["4 x 4 mm"]


def test_a_repeat_across_sources_is_one_fact():   # dictation and a tapped row restate the same value
    assert missing("LVEF 62%.", "LVEF 62%.", "LVEF 62%") == []


def test_a_dictated_bare_value_still_matches_any_report_number():
    assert missing("Segment 4 is thinned.", "Thinned 4.") == []


def test_a_dictated_bare_value_matches_any_unit_or_a_number_word():
    assert missing("LVEF 55%.", "LVEF 55.") == []
    assert missing("Two new nodules.", "2 new nodules.") == []


def test_a_range_with_one_end_dropped_is_flagged_once():
    out = missing_dictated_numbers("Moderate stenosis (50%).", ["moderate stenosis 50-69%."])
    assert [i["text"] for i in out] == ["50-69%"] and out[0]["values"] == [69.0]


def test_the_same_number_in_two_sentences_is_flagged_once():
    assert missing("Nothing.", "LVEF 62%.", "LVEF 62% again.") == ["62%"]


def test_empty_or_broken_input_never_raises():
    assert missing_dictated_numbers("", []) == []
    assert missing_dictated_numbers(None, [None, ""]) == []


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_NUMBERS", raising=False)
    assert enabled() is False
    monkeypatch.setenv("RR_DICTATED_NUMBERS", "1")
    assert enabled() is True


def test_lab_spellings_match():   # lab 2026-10-15: both were false flags on a faithful report
    assert missing("Adenosine 140 micrograms per kilogram per minute.", "Adenosine 140 mcg/kg/min.") == []
    assert missing("Escalated at three minutes.", "Escalated after 3 minutes.") == []
    assert missing("Escalated at three mm.", "Escalated after 3 minutes.") == ["3 minutes"]
