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


# --- review fixes 2026-10-15 ---

@pytest.mark.parametrize("dictated, report", [
    ("Defect in segment 4.", "Defect in segment IV."),
    ("Bosniak 2F cyst.", "Bosniak IIF cyst."),
    ("Grade 2 reflux.", "Grade II reflux."),
    ("Segment 1 is spared.", "Segment I is spared."),
    ("Segment 4 defect.", "Defect in the 4th segment."),
    ("Segment 4 defect.", "Defect in the fourth segment."),
    ("Rib 2 fracture.", "Fracture of the second rib."),
    ("Rib 12 fracture.", "Fracture of the twelfth rib."),
])
def test_a_bare_value_matches_a_roman_numeral_or_an_ordinal(dictated, report):
    assert missing(report, dictated) == []


def test_a_lone_roman_i_or_iv_contrast_is_not_a_numeral():
    assert missing("I reviewed the images.", "Thinned 1.") == ["1"]
    assert missing("IV contrast was given.", "Segment 4 defect.") == ["4"]


def test_a_minus_sign_is_part_of_the_value():
    assert vals("density -20 HU") == [(-20.0, "hu")]
    assert vals("density minus 20 HU") == [(-20.0, "hu")]
    assert vals("density −20 HU") == [(-20.0, "hu")]
    assert missing("Density 20 HU.", "Density -20 HU.") == ["-20 HU"]
    assert missing("Density minus 20 HU.", "Density -20 HU.") == []
    assert missing("Density 20.", "Density -20.") == ["-20"]


def test_a_range_hyphen_is_not_a_sign():
    assert vals("3-5 mm") == [(3.0, "mm"), (5.0, "mm")]
    assert vals("from -20 to -10 HU") == [(-20.0, "hu"), (-10.0, "hu")]


def test_comma_decimals_before_a_unit():
    assert vals("1,5 cm") == [(1.5, "cm")]
    assert vals("1,25 x 0,8 cm") == [(1.25, "cm"), (0.8, "cm")]
    assert missing("Nodule 1.5 cm.", "Nodule 1,5 cm.") == []
    assert vals("Agatston 1,260") == [(1260.0, None)]
    assert vals("1,000 ml") == [(1000.0, "ml")]


def test_a_comma_list_without_a_unit_is_not_a_decimal():
    assert vals("segments 6,7") == [(6.0, None), (7.0, None)]


def test_series_and_image_references_are_not_numbers():
    assert vals("nodule (series 3, image 45) measures 4 mm") == [(4.0, "mm")]
    assert vals("nodule (3/45) measures 4 mm") == [(4.0, "mm")]
    assert vals("see image 112 of series 4") == []
    assert vals("se 5 im 88") == []


def test_a_year_after_since_in_or_from_is_not_a_number():
    assert vals("stable since 2019, unchanged from 2021, resected in 2015") == []
    assert vals("drained 2015 ml") == [(2015.0, "ml")]


def test_uk_follow_up_fractions_read_as_months_or_weeks():
    assert vals("follow-up CT in 3/12") == [(3.0, "month")]
    assert vals("repeat in 6/52") == [(6.0, "week")]
    assert missing("Follow-up CT in 3 months.", "Follow up CT in 3/12.") == []
    assert missing("Follow-up CT in 6 months.", "Follow up CT in 3/12.") == ["3/12"]


@pytest.mark.parametrize("text", [
    "ADC 0.8 x 10-3 mm2/s", "ADC 0.8 x 10^-3 mm2/s", "ADC 0.8×10⁻³ mm²/s", "ADC 0.8 x10-3 mm2/s",
    "ADC 0.0008 mm2/s", "ADC 800 x 10^-6 mm2/s"])
def test_an_exponent_reads_as_one_value(text):
    assert vals(text) == [(0.0008, "mm2/s")]


def test_exponent_notations_match_each_other():
    assert missing("ADC 0.8 × 10⁻³ mm²/s.", "ADC 0.8 x 10-3 mm2/s.") == []
    assert missing("ADC 0.9 × 10⁻³ mm²/s.", "ADC 0.8 x 10-3 mm2/s.") == ["0.8 x 10-3 mm2/s"]


# --- Q5 (Hassan 2026-10-15): one report value may cover several dictated ones when the report says so ---

@pytest.mark.parametrize("report, dictated", [
    ("Both kidneys 11 cm.", "Right kidney 11 cm, left kidney 11 cm."),
    ("Kidneys 11 cm each.", "Kidneys 11 cm and 11 cm."),
    ("Two 4 mm nodules.", "4 mm and 4 mm nodules."),
    ("2 4 mm nodules.", "4 mm and 4 mm nodules."),
    ("Bilateral 4 mm nodules.", "4 mm and 4 mm nodules."),
    ("Ovaries bilaterally 3 cm.", "Right ovary 3 cm, left ovary 3 cm."),
    ("All three nodes 8 mm.", "Nodes 8 mm, 8 mm and 8 mm."),
])
def test_a_report_value_said_to_cover_several_satisfies_them_all(report, dictated):
    assert missing(report, dictated) == []


def test_a_plain_repeat_still_needs_two_occurrences():
    assert missing("Kidney 11 cm.", "Right kidney 11 cm, left kidney 11 cm.") == ["11 cm"]


def test_a_dimension_chain_is_not_a_count():
    assert missing("Lesion 3 x 5 mm.", "Lesions 5 mm and 5 mm.") == ["5 mm"]


def test_the_cover_cue_must_be_in_the_sentence_holding_the_value():
    assert missing("Both kidneys normal. Kidney 11 cm.", "Right kidney 11 cm, left kidney 11 cm.") == ["11 cm"]


# --- re-check fixes 2026-10-15 ---

@pytest.mark.parametrize("report, dictated", [
    ("Both kidneys normal; a 4 mm nodule in the RLL.", "4 mm nodule RLL and 4 mm nodule LLL."),
    ("Each ovary is normal; 5 mm cyst left adnexa.", "5 mm cyst left adnexa, 5 mm cyst right adnexa."),
    ("Not all margins seen; 4 mm nodule.", "4 mm nodule and 4 mm nodule."),
])
def test_a_cover_cue_in_another_clause_does_not_cover(report, dictated):
    assert len(missing(report, dictated)) == 1


def test_a_labelled_digit_before_a_value_is_not_a_count():
    out = missing_dictated_numbers("Segment 7 4 mm lesion.", ["4 mm lesion seg 7. 4 mm lesion seg 8."])
    assert [i["text"] for i in out] == ["4 mm", "8"]
    assert out[0]["sentence"] == "4 mm lesion seg 8."


def test_a_bare_hyphen_power_of_ten_needs_a_decimal_mantissa():
    assert vals("3 x 10-12 mm") == [(3.0, "mm"), (10.0, "mm"), (12.0, "mm")]
    assert missing("Lesion 3 x 10 to 12 mm.", "Lesion 3 x 10-12 mm.") == []
    assert vals("ADC 1.1 x 10-3 mm2/s") == [(0.0011, "mm2/s")]


def test_an_image_number_followed_by_a_unit_is_kept():
    assert vals("image 4 cm lesion") == [(4.0, "cm")]


def test_a_year_like_start_of_a_range_with_a_unit_is_kept():
    assert vals("output from 1950 to 2100 ml") == [(1950.0, "ml"), (2100.0, "ml")]
