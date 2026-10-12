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
    ("aged 65", "years", None, [65.0]),
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


@pytest.mark.parametrize("readings,model,want", [
    ([12.0], None, 12.0), ([12.0], 120.0, 12.0), ([9.0, 7.0], 7.0, 7.0), ([9.0, 7.0], 8.0, None),
    ([9.0, 7.0], None, None), ([], 7.0, None)])
def test_pick_one_reading_wins_several_need_the_model(readings, model, want):
    assert Q.pick(readings, model) == want


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
