import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import quantity as Q


@pytest.mark.parametrize("quote,unit,dims,want", [
    ("1.2 cm", "mm", None, [12.0]),
    ("1.2cm", "mm", None, [12.0]),
    ("12 mm", "mm", None, [12.0]),
    ("8mm", "mm", None, [8.0]),
    ("7-mm nodule", "mm", None, [7.0]),
    ("9 x 7 mm", "mm", None, [9.0, 7.0]),
    ("9 x 7 mm", "mm", "mean", [8.0]),
    ("9 x 8 mm", "mm", "mean", [8.5]),
    ("9 x 7 mm", "mm", "max", [9.0]),
    ("1.5 x 1.1 cm", "mm", "max", [15.0]),
    ("9 mm x 7 mm", "mm", "max", [9.0]),
    ("9 x 7 x 6 mm", "mm", "mean", []),          # a mean is of the two axial axes only: three dims are asked
    ("20 HU", "HU", None, [20.0]),
    ("20 Hounsfield units", "HU", None, [20.0]),
    ("6 mm", "HU", None, []),                     # a unit that does not convert: no reading
    ("150 mm3", "mm3", None, [150.0]),
    ("2.5 ml", "mm3", None, [2500.0]),
    ("2.5 cm3", "mm3", None, [2500.0]),
    ("3 weeks", "days", None, [21.0]),
    ("91 days", "days", None, [91.0]),
    ("3 months", "days", None, []),               # months and years never convert to days: asked
    ("1 year", "days", None, []),
    ("65-year-old", "years", None, [65.0]),
    ("aged 65", "years", None, []),                # a bare number only for count (and unitless) inputs
    ("interval 3", "years", None, []),
    ("interval 3", "days", None, []),
    ("7 nodule", "mm", None, []),                 # a bare number counts only for unitless, count and age inputs
    ("score 150", "", None, [150.0]),
    ("Solitary nodule", "count", None, [1.0]),
    ("two nodules", "count", None, [2.0]),
    ("3 nodules", "count", None, [3.0]),
    ("No other nodules", "count", None, []),
    ("seven millimetres", "mm", None, []),
    ("single nodule", "mm", None, []),
])
def test_readings(quote, unit, dims, want):
    assert Q.readings(quote, unit, dims) == want


@pytest.mark.parametrize("quote,unit", [("6-8 mm", "mm"), ("6 to 8 mm", "mm"), ("1.2–1.5 cm", "mm"),
                                        ("3/12 interval", "days"), ("seen at 6/52", "days"),
                                        ("5 mm to under 6 mm", "mm")])
def test_a_range_or_fraction_gives_no_reading(quote, unit):
    assert Q.readings(quote, unit) == []


@pytest.mark.parametrize("readings,model,unit,want", [
    ([12.0], None, "mm", 12.0), ([12.0], 12.0, "mm", 12.0), ([12.0], 1.2, "mm", 12.0),   # 1.2 (cm) converts to 12 mm
    ([12.0], 120.0, "mm", None), ([7.0], 9.0, "mm", None),                               # the model disagrees: asked
    ([9.0, 7.0], 7.0, "mm", 7.0), ([9.0, 7.0], 8.0, "mm", None), ([9.0, 7.0], None, "mm", None), ([], 7.0, "mm", None)])
def test_pick_one_reading_needs_the_model_to_agree_several_need_its_choice(readings, model, unit, want):
    assert Q.pick(readings, model, unit) == want


def test_one_conversion_table():
    assert Q.CONVERT == {("cm", "mm"): 10.0, ("mm", "cm"): 0.1, ("cm3", "mm3"): 1000.0, ("mm3", "cm3"): 0.001,
                         ("weeks", "days"): 7.0}
    assert (Q.canon("HU"), Q.canon("mm³"), Q.canon("cc"), Q.canon("count")) == ("HU", "mm3", "cm3", "count")


@pytest.mark.parametrize("quote,unit", [("under 5 mm", "mm"), ("8 mm or more", "mm"), ("<6 mm", "mm"),
                                        ("≥ 8 mm", "mm"), ("less than 1.5 cm", "mm"), ("at least 3 weeks", "days"),
                                        ("more than two nodules", "count"), ("2 years or more", "years")])
def test_a_bound_gives_no_reading(quote, unit):
    """"under 5 mm" or "8 mm or more" names a band edge, not the value: asked, like a range."""
    assert Q.readings(quote, unit) == []


@pytest.mark.parametrize("quote,unit,dims", [("up to 8 x 5 mm", "mm", "max"), ("up to 8 x 5 mm", "mm", None),
                                             ("under 9 x 7 mm", "mm", None), ("under 9 x 7 mm", "mm", "mean"),
                                             ("8 x 5 mm or more", "mm", "max")])
def test_a_bound_covers_the_whole_dimension_expression(quote, unit, dims):
    assert Q.readings(quote, unit, dims) == []


@pytest.mark.parametrize("quote,unit,want", [
    ("-20 HU", "HU", [-20.0]), ("−15 HU", "HU", [-15.0]), ("+10 HU", "HU", [10.0]), ("20 HU", "HU", [20.0]),
    ("-5 mm", "mm", []), ("−5 mm", "mm", []), ("T2-20 HU", "HU", []), ("-10 to -20 HU", "HU", [])])
def test_a_sign_is_kept_for_signed_units_and_refused_for_others(quote, unit, want):
    assert Q.readings(quote, unit) == want


@pytest.mark.parametrize("quote,unit", [("1,5 cm", "mm"), ("1,200 mm3", "mm3"), ("1,5 x 1,2 cm", "mm")])
def test_a_decimal_comma_or_thousands_separator_gives_no_reading(quote, unit):
    assert Q.readings(quote, unit) == []


@pytest.mark.parametrize("quote,want", [
    ("a six millimetre nodule", []), ("a six-millimetre nodule", []), ("two mm", []), ("one of the nodules", []),
    ("two nodules", [2.0]), ("single nodule", [1.0]), ("Solitary nodule", [1.0])])
def test_a_count_word_counts_findings_never_a_size(quote, want):
    assert Q.readings(quote, "count") == want


TEXT = "Nodule measuring under 5 mm. Another 12 x 7 mm nodule. Range 6 to 8 mm. Was 5 mm, now 9 mm."


@pytest.mark.parametrize("quote,text,unit,dims,model", [
    ("5 mm", "Nodule measuring under 5 mm.", "mm", None, 5),
    ("8 mm", "Range 6 to 8 mm.", "mm", None, 8),
    ("7 mm", "Another 12 x 7 mm nodule.", "mm", "max", 7),
    ("7 mm", "Another 12 x 7 mm nodule.", "mm", "mean", 7),
    ("5 mm", "Measuring up to 8 x 5 mm.", "mm", "max", 5),
    ("8 x 5 mm", "Measuring up to 8 x 5 mm.", "mm", "max", 8),
    ("7 mm", "Nodule under 9 x 7 mm.", "mm", None, 7),
    ("5 mm", "Nodule 1,5 mm.", "mm", None, 5),
    ("12 mm", "A 12 mm nodule.", "mm", None, 9),              # one reading, the model disagrees
    ("7 mm", "A 12 mm nodule.", "mm", None, 7),               # not in the text
])
def test_settle_reads_the_whole_measurement_and_asks_when_it_is_ambiguous(quote, text, unit, dims, model):
    assert Q.settle(quote, [text], unit, dims, model) is None


@pytest.mark.parametrize("quote,text,unit,dims,model,want", [
    ("12 mm", "A 12 mm nodule.", "mm", None, 12, 12.0),
    ("1.2 cm", "A 1.2 cm nodule.", "mm", None, 12, 12.0),
    ("1.2 cm", "A 1.2 cm nodule.", "mm", None, 1.2, 12.0),
    ("8mm", "An 8mm nodule.", "mm", None, None, 8.0),
    ("7-mm", "A 7-mm nodule.", "mm", None, 7, 7.0),
    ("7 mm", "Another 12 x 7 mm nodule.", "mm", "max", 12, 12.0),   # widened to 12 x 7 mm, whose max is 12
    ("12 x 7 mm", "Another 12 x 7 mm nodule.", "mm", "max", 12, 12.0),
    ("9 x 7 mm", "A 9 x 7 mm nodule.", "mm", "mean", 8, 8.0),
    ("9 mm", "Was 5 mm, now 9 mm.", "mm", None, 9, 9.0),            # read by code; Jev checks it is the current size
    ("-20 HU", "Attenuation -20 HU.", "HU", None, -20, -20.0),
    ("two nodules", "Two nodules in the right lung.", "count", None, 2, 2.0),
])
def test_settle_gives_the_one_reading_of_the_whole_measurement(quote, text, unit, dims, model, want):
    assert Q.settle(quote, [text], unit, dims, model) == want


# (finding, quote, unit, dims): another number in the finding besides the quoted measurement, so the size is asked
OTHER_NUMBER = [
    # fix round 3 re-review: spelled-out siblings and unrecognised unit spellings
    ("Two solid nodules measuring eight millimetres and 4 mm.", "4 mm", "mm", "mean"),
    ("Nodule eight millimetres, previously 6 mm.", "6 mm", "mm", "mean"),
    ("Two solid nodules, 8 mms and 4 mm.", "4 mm", "mm", "mean"),
    ("Volume 180 cubic mm, previously 120 mm3.", "120 mm3", "mm3", None),
    ("Cyst 20 HU on unenhanced, 45 H.U. post contrast.", "20 HU", "HU", None),
    ("Cyst 20 HU on unenhanced, 45 H.U. post contrast.", "45 H.U.", "HU", None),
    # fix round 3: several measurements
    ("Two nodules measuring 8 and 4 mm.", "4 mm", "mm", "mean"), ("Two nodules measuring 8 and 4 mm.", "8 and 4 mm", "mm", None),
    ("8 mm, 4 mm.", "8 mm", "mm", None), ("8 mm and 4 mm.", "4 mm", "mm", None),
    ("5 mm nodule; 9 mm nodule.", "9 mm", "mm", "max"),
    ("Cyst 20 HU on unenhanced, 45 HU post contrast.", "45 HU", "HU", None),
    ("8 mm (previously 6 mm).", "8 mm", "mm", None), ("Was 5 mm, now 9 mm.", "9 mm", "mm", None),
    ("Nodule 8 mm, previously 0.6 cm.", "8 mm", "mm", None), ("Nodule 0.8 cm, previously 6 mm.", "0.8 cm", "mm", None),
    ("9 mm (6 mm in 2019).", "9 mm", "mm", None), ("9 mm vs 6 mm.", "9 mm", "mm", None),
    ("9 mm from 6 mm.", "9 mm", "mm", None), ("6 mm → 9 mm.", "9 mm", "mm", None),
    ("7 x 5 mm, previously 4 x 3 mm.", "7 x 5 mm", "mm", "mean"),
    ("Volume 200 mm3, previously 0.1 cm3.", "200 mm3", "mm3", None),
    ("Volume 200 mm3, previously 0.1 ml.", "200 mm3", "mm3", None),
    ("Volume 200 mm3, previously 0.1 cc.", "200 mm3", "mm3", None),
    ("8-mm, prior 6-mm.", "8-mm", "mm", None), ("8mm, prior 6mm.", "8mm", "mm", None),
    ("8 millimeter, prior 6 mm.", "8 millimeter", "mm", None),
    ("20 HU, 45 Hounsfield units.", "20 HU", "HU", None),
    ("Seen 12 weeks ago and 6 weeks ago.", "6 weeks", "days", None),
    ("Nodule 9 mm. Adjacent 1 cm lymph node.", "9 mm", "mm", None),
    ("8 mm nodule (series 3 image 45), 2019 CT 200 mm3.", "8 mm", "mm", None),
    # lab fix round item 4: a number of the same family still blocks; so does one without an attached unit
    ("20 HU unenhanced, enhancing by 25 HU.", "25 HU", "HU", None),
    ("20 HU unenhanced, enhancing by 25 HU.", "20 HU", "HU", None),
    ("Cyst 20 HU, measuring 3 x 2.", "20 HU", "HU", None), ("Cyst 20 HU, 3.", "20 HU", "HU", None),
    ("Cyst 20 HU, 3 to 4 cm.", "20 HU", "HU", None),
    ("Cyst 3 cm, about twenty HU.", "3 cm", "mm", None),
    # the ruling: a count of nodules, or a size elsewhere, asks which one is meant
    ("Two nodules, the larger 8 mm.", "8 mm", "mm", None), ("Both nodules 8 mm.", "8 mm", "mm", None),
    ("Several nodules, the largest 8 mm.", "8 mm", "mm", None),
    ("Multiple nodules, the largest 8 mm.", "8 mm", "mm", None),
    ("8 mm nodule, half the size of the dozen others.", "8 mm", "mm", None),
    ("8 mm nodule; another of twenty millimetres.", "8 mm", "mm", None),
    ("8 mm nodule, one of three.", "8 mm", "mm", None),
    ("8 mm nodule, previously 8 mm3.", "8 mm", "mm", None),         # the same number in another family
    ("8 mm nodule, stable at 8.", "8 mm", "mm", None),              # a bare 8 has no unit: not the same reading
    ("Nodules 8 4 mm.", "4 mm", "mm", None),                         # a bare number run into the measurement
]

# (finding, quote, unit, dims, value): nothing but the quoted measurement and the allowed exceptions
ALONE = [
    ("A solitary 8 mm nodule.", "8 mm", "mm", None, 8), ("A single 8 mm nodule.", "8 mm", "mm", None, 8),
    ("8 mm nodule in segment 6.", "8 mm", "mm", None, 8), ("Segment 6, 8 mm lesion.", "8 mm", "mm", None, 8),
    ("8 mm nodule in S6.", "8 mm", "mm", None, 8), ("8 mm nodule, seg 6.", "8 mm", "mm", None, 8),
    ("8 mm nodule (series 3, image 45).", "8 mm", "mm", None, 8),
    ("8 mm nodule (Series: 3, Image: 45).", "8 mm", "mm", None, 8),
    ("8 mm nodule (se 3 im 45).", "8 mm", "mm", None, 8), ("8 mm nodule, slice [112].", "8 mm", "mm", None, 8),
    ("8 mm nodule, stable since 12/03/2024.", "8 mm", "mm", None, 8),
    ("8 mm nodule, stable since 2024-03-12.", "8 mm", "mm", None, 8),
    ("8 mm nodule, stable since 12.03.24.", "8 mm", "mm", None, 8),
    ("8 mm nodule, stable since 2019.", "8 mm", "mm", None, 8),
    ("8 mm nodule at the level of T4, near rib 5.", "8 mm", "mm", None, 8),
    ("8 mm nodule abutting the L2/3 disc, level 4.", "8 mm", "mm", None, 8),
    ("A 12 x 7 mm nodule.", "12 x 7 mm", "mm", "mean", 9.5), ("Attenuation -20 HU.", "-20 HU", "HU", None, -20),
    ("8 mm nodule, stable at 8 mm.", "8 mm", "mm", None, 8), ("8 mm nodule, stable at 8 mm.", "8 mm nodule", "mm", None, 8),
    ("Nodule 8 mm, previously 0.8 cm.", "8 mm", "mm", None, 8),
    ("7 x 5 mm (mean 6 mm).", "7 x 5 mm", "mm", "mean", 6), ("7 x 5 mm (mean 6 mm).", "6 mm", "mm", "mean", 6),
    ("Two nodules, 8 and 4 mm.", "two nodules", "count", None, 2),   # a count keeps its own rule
    # lab fix round item 4: another number with an attached unit of another family does not block
    ("Cyst 20 HU, 3 cm.", "20 HU", "HU", None, 20), ("Cyst 20 HU, 3 cm.", "3 cm", "mm", None, 30),
    ("Left renal cyst 32 x 28 mm, 20 HU.", "20 HU", "HU", None, 20),
    ("Left renal cyst 32 x 28 mm, -5 HU.", "32 x 28 mm", "mm", "max", 32),
    ("Interval 91 days, nodule 9 mm.", "91 days", "days", None, 91), ("Nodule 8 mm, 3 months.", "8 mm", "mm", None, 8),
]


@pytest.mark.parametrize("text,quote,unit,dims", OTHER_NUMBER)
def test_a_finding_with_another_number_is_not_alone(text, quote, unit, dims):
    v = Q.settle(quote, [text], unit, dims)
    assert v is None or not Q.alone(text, quote, v, unit, dims)


@pytest.mark.parametrize("text,quote,unit,dims,value", ALONE)
def test_a_finding_with_only_its_measurement_and_the_allowed_numbers_is_alone(text, quote, unit, dims, value):
    assert Q.settle(quote, [text], unit, dims) == value
    assert Q.alone(text, quote, value, unit, dims)


@pytest.mark.parametrize("quote,unit,want", [
    ("8 mms", "mm", 8.0), ("8 millimetres", "mm", 8.0), ("8 millimeter", "mm", 8.0), ("180 cubic mm", "mm3", 180.0),
    ("180 cu mm", "mm3", 180.0), ("180 cubic  millimetres", "mm3", 180.0), ("45 H.U.", "HU", 45.0),
    ("45 Hounsfield units", "HU", 45.0)])
def test_further_unit_spellings_read(quote, unit, want):
    assert Q.readings(quote, unit) == [want]


def test_a_bare_number_run_into_the_measurement_gives_no_reading_for_any_scope():
    assert Q.settle("4 mm", ["Nodules 8 4 mm."], "mm") is None
    assert Q.settle("65 years", ["Aged 3 65 years."], "years") is None


@pytest.mark.parametrize("text,quote", [("Segment 6 8 mm lesion.", "8 mm"), ("Image 45 8 mm nodule.", "8 mm")])
def test_a_label_number_before_the_measurement_is_not_widened_in(text, quote):
    assert Q.settle(quote, [text], "mm") == 8 and Q.alone(text, quote, 8, "mm")


# final fix: a label or image number never splits a dimension set
@pytest.mark.parametrize("text,quote,dims", [
    ("Image 4 x 8 mm nodule.", "8 mm", "mean"), ("Image 4 x 8 mm nodule.", "4 x 8 mm", "mean"),
    ("Image 4 x 8 mm nodule.", "8 mm", "max"), ("Image 4 x 8 mm nodule.", "4 x 8 mm", "max"),
    ("Nodule level 4 x 8 mm.", "8 mm", "mean"), ("Nodule level 4 x 8 mm.", "8 mm", "max"),
    ("Nodule im 4 x 8 mm.", "8 mm", "mean"), ("Nodule im 4 by 8 mm.", "8 mm", "mean"),
    ("Segment 6 x 8 mm lesion.", "8 mm", "mean"), ("Segment 6 × 8 mm lesion.", "8 mm", "max"),
    ("Segment 6 x 8 mm lesion.", "8 mm", None), ("Segment 4 to 8 mm lesion.", "8 mm", None),
    ("Segment 4 - 8 mm lesion.", "8 mm", None), ("Segment 4 – 8 mm lesion.", "8 mm", None)])
def test_a_number_before_a_dimension_or_range_connector_is_never_a_label(text, quote, dims):
    v = Q.settle(quote, [text], "mm", dims)
    whole = Q.readings(text.split(" ", 1)[1] if text.startswith(("Image", "Segment")) else text, "mm", dims)
    assert v is None or (v in whole and v != 8.0) or (dims == "max" and whole == [8.0] and v == 8.0)


@pytest.mark.parametrize("text", ["Segment 6 8 mm lesion.", "Image 45 8 mm nodule.",
                                  "8 mm nodule (series 3, image 45)."])
def test_a_label_number_without_a_connector_still_settles(text):
    assert Q.settle("8 mm", [text], "mm") == 8 and Q.alone(text, "8 mm", 8, "mm")


@pytest.mark.parametrize("span", ["x 8 mm", "by 8 mm", "to 8 mm", "- 8 mm", "8 mm x", "8 mm -", "8 mm to"])
def test_a_widened_span_on_a_connector_gives_no_reading(span):
    assert Q.settle(span, [span], "mm") is None


NODULE = ["pulmonary nodule"]


@pytest.mark.parametrize("text,nouns", [
    ("8 mm solid nodule in the RUL. No other pulmonary nodules.", NODULE),
    ("8 mm solid nodule in the RUL; no further nodules.", NODULE),
    ("8 mm solid nodule. No additional nodules are seen.", NODULE),
    ("8 mm solid nodule. No further pulmonary nodules or masses.", NODULE),
    ("8 mm solid nodule. No other nodules identified bilaterally.", NODULE),
    ("Left renal cyst of -20 HU. No other renal lesions.", ["renal cyst", "cystic renal mass"])])
def test_an_unqualified_negation_does_not_fire_the_backstop(text, nouns):
    assert not Q.many(text, nouns)


@pytest.mark.parametrize("text", [
    "4 mm solid nodule. No other new nodules.", "4 mm solid nodule. No other enlarging nodules.",
    "New 4 mm solid nodule. No other nodules have changed.",
    "4 mm solid nodule. No other nodules apart from stable subpleural nodularity.",
    "4 mm solid nodule. No other suspicious nodules.", "4 mm solid nodule. No further nodules since 2019.",
    "4 mm solid nodule. No other nodules except a calcified granuloma.",
    "4 mm solid nodule. No other significant nodules.", "4 mm solid nodule. No larger nodules.",
    "4 mm solid nodule. Further nodules bilaterally."])
def test_a_qualified_negation_still_fires_the_backstop(text):
    assert Q.many(text, NODULE)


@pytest.mark.parametrize("word", ["increasing", "enlarged", "evolving", "worsening", "progressing", "developing",
                                  "interval", "incident", "stable", "bigger", "concerning", "indeterminate",
                                  "subsolid", "measurable"])
def test_the_negation_slot_holds_only_an_organ_word(word):
    assert Q.many(f"4 mm solid nodule in the right upper lobe. No other {word} nodules.", NODULE)


@pytest.mark.parametrize("text,nouns", [
    ("4 mm solid nodule. No other pulmonary nodules.", NODULE), ("4 mm solid nodule. No other lung nodules.", NODULE),
    ("Cyst -20 HU. No other renal lesions.", ["renal cyst", "cystic renal mass"]),
    ("Cyst -20 HU. No other kidney lesions.", ["renal cyst", "cystic renal mass"]),
    ("4 mm solid nodule; no further nodules.", NODULE), ("4 mm solid nodule. No additional nodules are seen.", NODULE)])
def test_an_organ_word_in_the_negation_slot_stays_exempt(text, nouns):
    assert not Q.many(text, nouns)
