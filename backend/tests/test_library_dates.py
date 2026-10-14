"""Spec §7.12 item 4: an interval from a dated comparison. The model quotes the earlier study's date; code parses it
(UK day-month order) and subtracts it from today in Europe/London. Exact: read, labelled with the study. Month or year
only: pre-filled, approximate. Several dates, a future date or a zero interval: asked."""
from datetime import date

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import dates as D
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
from tests.test_library_assume_band import _bts
from tests.test_library_pack_preview import _model, jev  # noqa: F401  (fixture)

TODAY = date(2026, 10, 14)
COMPARISON = "Compared with the CT thorax of 12 March 2025."
NODULE = "The solid nodule in the right lower lobe now measures 9 mm, previously 6 mm."
DICTATION = f"{COMPARISON}\n{NODULE}"


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(D, "today", lambda: TODAY)
    return TODAY


@pytest.mark.parametrize("quote", ["12 March 2025", "12th March 2025", "12 Mar 2025", "12/03/2025", "12.03.2025",
                                   "12-03-2025", "2025-03-12", "the CT thorax of 12 March 2025", "12th of March 2025"])
def test_parse_formats(quote):
    p = D.parse(quote)
    assert p is not None and p.day == date(2025, 3, 12) and p.exact


def test_uk_day_first():
    assert D.parse("03/12/2025").day == date(2025, 12, 3)


def test_month_year_approx():
    p = D.parse("CT from March 2025")
    assert p.day == date(2025, 3, 15) and not p.exact and p.text == "March 2025"


def test_bare_year_approx(today):
    p = D.parse("CT 2023")
    assert p.day == date(2023, 7, 1) and not p.exact
    assert D.parse("CT 1989") is None and D.parse("CT 2027") is None       # outside 1990 to this year


@pytest.mark.parametrize("quote", ["18 months", "9 mm", "previously", "", "31/02/2025",
                                   "12 March 2025 and 1 June 2024", "13/13/2025"])
def test_garbage_none(quote, today):
    assert D.parse(quote) is None


def test_days_since():
    assert D.days_since(date(2025, 3, 12), today=date(2026, 10, 14)) == 581


def test_distinct_dates(today):
    assert D.distinct_dates(DICTATION) == [date(2025, 3, 12)]
    assert D.distinct_dates("CT 12 March 2025. Also CT 12/03/2025.") == [date(2025, 3, 12)]
    assert D.distinct_dates("CT 12 March 2025 and CT 1 June 2024.") == [date(2025, 3, 12), date(2024, 6, 1)]


def test_since_study_only_on_a_number_in_days():
    InputDef(id="a", label="A", type="number", unit="days", since_study=True)
    with pytest.raises(ValueError):
        InputDef(id="a", label="A", type="number", unit="mm", since_study=True)
    with pytest.raises(ValueError):
        InputDef(id="a", label="A", type="boolean", since_study=True)


def test_bts_interval_is_since_study():
    assert _bts().input("interval_days").since_study is True


async def _settle(monkeypatch, dictation, quote, history=""):
    _model(monkeypatch, {"input": "interval_days", "value": quote, "quote": quote},
           {"input": "prior_study", "value": True, "quote": "Compared with the CT thorax"})
    return await PP.settle_pack(_bts(), dictation, history, finding=NODULE)


async def test_interval_from_comparison_date(monkeypatch, jev, today):
    prompts = []
    _model(monkeypatch, {"input": "interval_days", "value": "12 March 2025", "quote": "12 March 2025"},
           prompts=prompts)
    s = await PP.settle_pack(_bts(), DICTATION, "", finding=NODULE)
    d = s.values["interval_days"]
    assert d.value.value == 581 and d.tier == "read" and d.basis == "from the CT of 12 Mar 2025"
    assert "DICTATION" in prompts[0]                    # the date may come from the whole dictation
    p = PP.finish(_bts(), s, {"prior_study": "Yes", "resolved": "No"}, {}, [])
    row = next(x for x in p.draft if x.input == "interval_days")
    assert row.state == "read" and row.value == "581 days" and row.basis == "from the CT of 12 Mar 2025"


async def test_two_dates_asks(monkeypatch, jev, today):
    s = await _settle(monkeypatch, f"{DICTATION}\nAlso compared with CT 1 June 2024.", "12 March 2025")
    assert "interval_days" not in s.values


async def test_approx_date_prefilled(monkeypatch, jev, today):
    s = await _settle(monkeypatch, f"Compared with CT from March 2025.\n{NODULE}", "March 2025")
    d = s.values["interval_days"]
    assert d.tier == "prefilled" and any("approximate date" in w for w in d.why)
    assert d.basis.endswith("(approximate)") and d.value.value == (TODAY - date(2025, 3, 15)).days


async def test_future_date_dropped(monkeypatch, jev, today):
    s = await _settle(monkeypatch, f"Compared with the CT of 20 November 2026.\n{NODULE}", "20 November 2026")
    assert "interval_days" not in s.values
    s = await _settle(monkeypatch, f"Compared with the CT of 14 October 2026.\n{NODULE}", "14 October 2026")
    assert "interval_days" not in s.values                 # a zero interval


async def test_duration_quote_unchanged(monkeypatch, jev, today):
    """A plain duration keeps today's quantity path: weeks and days convert; months never do (their length varies),
    so "18 months" is asked exactly as before."""
    s = await _settle(monkeypatch, f"Compared with CT 18 months ago.\n{NODULE}", "18 months")
    assert "interval_days" not in s.values
    finding = "The solid nodule now measures 9 mm, previously 6 mm on the CT 400 days ago."
    _model(monkeypatch, {"input": "interval_days", "value": 400, "quote": "400 days"})
    s = await PP.settle_pack(_bts(), finding, "", finding=finding)             # a duration in the finding itself
    assert s.values["interval_days"].value.value == 400 and s.values["interval_days"].basis == ""


async def test_a_date_outside_the_dictation_is_asked(monkeypatch, jev, today):
    s = await _settle(monkeypatch, DICTATION, "1 June 2024")             # not verbatim anywhere
    assert "interval_days" not in s.values


async def test_a_date_in_the_history_counts(monkeypatch, jev, today):
    s = await _settle(monkeypatch, NODULE, "12/03/2025", history="Follow-up of nodule seen on CT 12/03/2025.")
    d = s.values["interval_days"]
    assert d.tier == "read" and d.value.value == 581 and d.basis == "from the CT of 12 Mar 2025"


# fix round 1 (task-3-review I-1, I-2, M-1, M-2, N-3)
@pytest.mark.parametrize("second", ["CT 01/06/24", "CT 1 June", "CT of the 1st of June", "CT June 24", "CT Jun-24"])
async def test_two_dates_asks_when_the_second_is_not_parseable(monkeypatch, jev, today, second):
    """I-1: a second comparison with a two-digit year or no year still counts: the interval is asked, never read."""
    s = await _settle(monkeypatch, f"{DICTATION}\nAlso compared with {second}.", "12 March 2025")
    assert "interval_days" not in s.values


def test_the_same_date_written_twice_is_one_date(today):
    assert not D.several_dates("CT 12 March 2025. As on the CT of 12/03/25.")
    assert D.several_dates("CT 12 March 2025 and CT 01/06/24.")


@pytest.mark.parametrize("quote", ["image 2024", "series 3 image 2024", "2010 mm3", "1995 HU", "2000 days",
                                   "volume 2010 mm3"])
def test_a_bare_year_needs_its_context(quote, today):
    """I-2: an image number, a volume, an attenuation or a duration is never a year."""
    assert D.parse(quote) is None


def test_measurements_never_count_as_dates(today):
    assert D.distinct_dates("CT 12 March 2025, volume 2010 mm3, series 3 image 2024.") == [date(2025, 3, 12)]
    assert not D.several_dates("CT 12 March 2025, volume 2010 mm3, series 3 image 2024.")


async def test_a_duration_in_days_keeps_the_quantity_path(monkeypatch, jev, today):
    s = await _settle(monkeypatch, f"{NODULE} Compared with CT 2000 days ago.", "2000 days")
    assert "interval_days" not in s.values or s.values["interval_days"].basis == ""


def test_us_order_is_exact():
    """M-1: "March 12, 2025" names the month, so it is unambiguous: never a bare-year approximation."""
    p = D.parse("CT of March 12, 2025")
    assert p.day == date(2025, 3, 12) and p.exact


async def test_a_duration_outside_the_finding_is_out_of_scope(monkeypatch, jev, today):
    """M-2: only a date widens a since-study input's scope; a duration keeps the finding's."""
    s = await _settle(monkeypatch, NODULE, "400 days", history="Follow-up, previous CT 400 days ago.")
    assert "interval_days" not in s.values


def test_month_names_never_follow_the_locale():
    import locale
    q = "CT of 12 March 2025"
    old = locale.setlocale(locale.LC_TIME)
    try:
        try:
            locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
        except locale.Error:
            pytest.skip("no French locale")
        assert D.basis(q, D.parse(q), [q]) == "from the CT of 12 Mar 2025"
    finally:
        locale.setlocale(locale.LC_TIME, old)
