"""Numbers in a generated template report that the radiologist did not dictate (review flags, never edits)."""
from __future__ import annotations

from rapid_reports_ai.template_number_check import undictated_numbers


def texts(report, sources, sheet=""):
    return [f["text"] for f in undictated_numbers(report, sources, sheet)]


def test_dictated_numbers_pass_and_invented_ones_are_flagged():
    report = "A 2.3 cm lesion. ASPECTS 7. Consistent with onset within the first 4.5 hours."
    assert texts(report, ["Lesion 2.3cm."]) == ["ASPECTS 7", "4.5"]


def test_ranges_percent_and_decimals():
    assert texts("Stenosis of 50-70%. Measures 12 x 8 mm.", ["50-70% stenosis, 12 by 8 mm"]) == []
    assert texts("Stenosis of 50-70%.", ["50% stenosis"]) == ["50-70%"]
    assert texts("Ejection fraction 55%.", ["EF 55.0 percent"]) == []


def test_grade_and_score_patterns_need_the_label_dictated_too():
    # the value alone appearing elsewhere does not license a grade
    assert texts("Fazekas grade 2 change.", ["2 small foci of white matter change"]) == ["grade 2"]
    assert texts("Fazekas grade 2 change.", ["Fazekas grade 2"]) == []
    assert texts("AAST grade III splenic injury.", ["splenic laceration"]) == ["AAST grade III"]
    assert texts("Grade III splenic injury.", ["grade 3 splenic laceration"]) == []


def test_word_numbers_in_the_dictation_count():
    assert texts("Two lesions, the larger 3 cm.", ["two lesions, larger three centimetres"]) == []


def test_list_markers_identifiers_dates_and_times_are_not_numbers():
    report = ("Findings:\nT2 and DWI sequences. Right M1 occlusion. L4/5 disc.\n"
              "Compared with 03/04/2025 and 12 October 2024 at 14:30.\n\nConclusion:\n1. No acute finding.\n2) Stable.")
    assert texts(report, ["no acute finding"]) == []


def test_fixed_sheet_text_and_section_headers_are_excluded():
    sheet = ('SECTION SEGMENT 7 | header: "Segment 7 review:" | role: findings\n'
             'FIXED "MRI at 1.5 T following 0.1 mmol/kg gadobutrol."\n'
             'RULE WHEN [context: x] REPLACE "a" WITH "Imaged at 3 T."\n'
             'Abnormal pattern: "Measures 9 mm."')
    report = "Segment 7 review:\nMRI at 1.5 T following 0.1 mmol/kg gadobutrol. Imaged at 3 T. Measures 9 mm."
    assert texts(report, ["normal"], sheet) == ["9"]   # an example's value is not fixed text


def test_each_flag_carries_its_sentence_and_repeats_are_one_flag():
    out = undictated_numbers("Grade 4 tear. Again grade 4 here.", ["tear"])
    assert len(out) == 1 and out[0]["kind"] == "undictated_number"
    assert out[0]["sentence"] == "Grade 4 tear."


def test_never_raises():
    assert undictated_numbers(None, [None]) == []  # type: ignore[arg-type]


def test_the_sentence_survives_a_decimal_point():
    out = undictated_numbers("No bleed. Acute infarct within the first 4.5 hours. Stable.", ["infarct"])
    assert out == [{"kind": "undictated_number", "text": "4.5",
                    "sentence": "Acute infarct within the first 4.5 hours."}]


def test_inline_list_markers_and_sheet_reference_limits_are_not_flagged():
    sheet = "## Reference Values\n- Right atrial area: normal < 22 cm²"
    report = "1) No change. 2) 5 mm nodule. Right atrium: 21 cm² (normal value <22 cm²). ASPECTS score is 5."
    assert texts(report, ["5 mm nodule, right atrium 21 cm2, ASPECTS 5"], sheet) == []
    # a limit the sheet does not give, or a sheet value written as a patient value, is still flagged
    assert texts("Right atrium (normal <30 cm²).", ["right atrium normal"], sheet) == ["30"]
    assert texts("Right atrium 22 cm².", ["right atrium normal"], sheet) == ["22"]


def test_a_two_word_label_passes_when_either_word_was_dictated_and_bracket_markers_are_skipped():
    assert texts("Infarct with ASPECTS score 5.\n1] Infarct.", ["ASPECTS 5"]) == []
    assert texts("Infarct with ASPECTS score 5.", ["5 regions"]) == ["ASPECTS score 5"]
