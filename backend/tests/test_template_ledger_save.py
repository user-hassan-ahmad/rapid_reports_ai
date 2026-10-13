"""The save function applies the decision ledger last, by code, on every origin (Rules-step spec)."""
import pytest

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_save as S
from tests.template_sheet_fixtures import LEDGER_SHEET


@pytest.fixture(autouse=True)
def no_jev(monkeypatch):
    async def none(st, sheet=""):
        return []

    async def no_repair(sheet, errors):
        raise AssertionError("repair must not run")
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr(S, "_repair", no_repair)


def _led(*changes):
    led = []
    for kind, key, choice in changes:
        led, _ = td.set_decision(led, kind, key, choice, source="creation", at="t")
    return led


LVEF = _led(("value", "LVEF", {"need": "every"}))
APPLIED = tla.apply_ledger(LEDGER_SHEET, LVEF).sheet


async def test_without_a_ledger_the_save_is_as_today():
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser")
    assert out.status == "saved" and out.sheet == LEDGER_SHEET and out.ledger == [] and out.ledger_drift == 0


async def test_the_writer_cannot_override_the_ledger_and_drift_is_counted():
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=LVEF)
    assert out.sheet == APPLIED and out.ledger == LVEF and out.ledger_drift == 1
    assert out.coverage_sections == ["TECHNIQUE", "FINDINGS", "IMPRESSION"]


async def test_a_ledger_only_change_saves_the_unchanged_sheet():
    out = await S.vet_sheet(LEDGER_SHEET, origin="chat", previous=LEDGER_SHEET, ledger=LVEF)
    assert out.status == "saved" and out.sheet == APPLIED and out.coverage_sections


async def test_an_unchanged_sheet_that_already_satisfies_the_ledger_is_unchanged():
    out = await S.vet_sheet(APPLIED, origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "unchanged" and out.sheet == APPLIED


async def test_a_chat_edit_of_a_decided_item_updates_the_ledger_and_says_so():
    after = APPLIED.replace('LIST_MISSING ["LVEF"]', 'LIST_MISSING ["RVEF"]')
    out = await S.vet_sheet(after, origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "saved" and out.sheet == after
    assert {(e["key"], e["choice"]["need"], e["source"]) for e in out.ledger} == {
        ("LVEF", "not_needed", "chat"), ("RVEF", "every", "chat")}
    assert td.describe_change(out.ledger_changes[0]).startswith("This changes something you confirmed: LVEF")


async def test_a_rebuild_never_overrides_the_ledger():
    after = APPLIED.replace('LIST_MISSING ["LVEF"]', 'LIST_MISSING ["RVEF"]')
    out = await S.vet_sheet(after, origin="rebuild", previous=APPLIED, ledger=LVEF)
    assert out.sheet == APPLIED and out.ledger == LVEF and out.ledger_drift == 1 and out.ledger_changes == []


async def test_a_refused_write_keeps_the_previous_sheet_and_the_ledger():
    out = await S.vet_sheet("# Free form\nprose", origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "refused" and out.sheet == APPLIED and out.ledger == LVEF


async def test_unmatched_entries_are_reported_for_the_next_review():
    led = _led(("fixed", "A line the sheet lacks.", {"keep": "always"}))
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=led)
    assert [e["key"] for e in out.ledger_unmatched] == ["A line the sheet lacks."]


async def test_a_chat_edit_that_drops_the_whole_value_list_is_kept_and_carded():
    after = "\n".join(ln for ln in APPLIED.split("\n") if "LIST_MISSING" not in ln)
    out = await S.vet_sheet(after, origin="chat", previous=APPLIED, ledger=LVEF)
    assert out.status == "saved" and out.sheet == APPLIED and out.ledger == LVEF and out.ledger_changes == []
    assert [c["id"] for c in out.ledger_cards] == ["value:lvef"]
