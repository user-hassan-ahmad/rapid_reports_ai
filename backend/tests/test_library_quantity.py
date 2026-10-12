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
