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
