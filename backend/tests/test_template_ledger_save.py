"""The save function applies the decision ledger last, by code, on every origin (Rules-step spec)."""
import pytest

from rapid_reports_ai import template_context_rules as tcr
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
    assert out.status == "unchanged" and out.sheet == APPLIED and out.ledger == LVEF and out.ledger_changes == []
    assert [c["id"] for c in out.ledger_cards] == ["value:lvef"]


PRIOR = "the dictation names a previous imaging study for comparison"
CMP = _led(("concept", "comparison", {"use": True, "default": "No previous imaging available.",
                                      "when_met": "Compared with the previous {modality} of {date}.",
                                      "condition": PRIOR}))
CMP_SHEET = tla.apply_ledger(LEDGER_SHEET, CMP).sheet
REWORDED = CMP_SHEET.replace('FIXED "No previous imaging available."', 'FIXED "No prior imaging."')


def _one_comparison_line_each_way(sheet):
    rules = tcr.rules_in_scope(sheet)
    for met in (True, False):
        out = tcr.apply_rules(sheet, rules, {PRIOR: met})[0]
        hits = [ln for ln in out.split("\n") if "FIXED" in ln and any(w in ln for w in ("previous", "prior", "Compared"))]
        assert len(hits) == 1 and "RULE WHEN" not in out, (met, hits)


async def test_chat_rewording_a_concept_default_saves_one_line_and_updates_the_ledger():
    out = await S.vet_sheet(REWORDED, origin="chat", previous=CMP_SHEET, ledger=CMP)
    assert out.ledger[0]["choice"]["default"] == "No prior imaging." and out.ledger_cards == []
    assert "No previous imaging available." not in out.sheet
    _one_comparison_line_each_way(out.sheet)


async def test_chat_orphaning_a_concept_rule_otherwise_keeps_the_ledgers_line():
    after = REWORDED.replace('FIXED "Axial images were acquired."\n', "")
    out = await S.vet_sheet(after, origin="chat", previous=CMP_SHEET, ledger=CMP)
    assert out.ledger == CMP and [c["id"] for c in out.ledger_cards] == ["concept:comparison"]
    assert "No prior imaging." not in out.sheet
    _one_comparison_line_each_way(out.sheet)


@pytest.mark.parametrize("origin,previous", [("rebuild", CMP_SHEET), ("restore", CMP_SHEET), ("rebuild", "")])
async def test_rebuild_and_restore_never_leave_two_comparison_lines(origin, previous):
    out = await S.vet_sheet(REWORDED, origin=origin, previous=previous, ledger=CMP)
    assert out.sheet == CMP_SHEET and out.ledger == CMP
    assert [e["key"] for e in out.ledger_unmatched] == ["comparison"]
    _one_comparison_line_each_way(out.sheet)


_PRIOR = "No previous imaging available."
COMPARISON = _led(("concept", "comparison", {"use": True, "default": _PRIOR, "when_met": "Compared with {date}."}))
RESTATED = LEDGER_SHEET.replace('Opening: "Axial images were acquired."',
                                f'Opening: "Axial images were acquired. {_PRIOR}"')


async def test_prose_quoting_a_decided_concepts_line_is_a_non_blocking_warning():
    out = await S.vet_sheet(RESTATED, origin="analyser", ledger=COMPARISON)
    assert out.status == "saved"
    assert [(w["reason"], w["detail"]) for w in out.ledger_warnings] == [
        ("prose quotes a decided standard line", _PRIOR)]
    assert out.ledger_warnings[0]["text"].startswith("Opening:")
    assert out.sheet.split("\n")[out.ledger_warnings[0]["line"] - 1] == out.ledger_warnings[0]["text"]
    # no quote, no warning; a line the ledger does not own is not flagged; no ledger, no check
    assert (await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=COMPARISON)).ledger_warnings == []
    assert (await S.vet_sheet(RESTATED, origin="analyser", ledger=LVEF)).ledger_warnings == []
    assert (await S.vet_sheet(RESTATED, origin="analyser")).ledger_warnings == []
    assert tla.apply_ledger(RESTATED, COMPARISON).restated[0]["detail"] == _PRIOR


_FRAG = "assessment is limited by {limitation}"
FRAGMENT = [{"kind": "concept", "key": "limitation", "by": "radiologist", "at": "t", "source": "creation",
             "choice": {"use": True, "default": "", "when_met": _FRAG,
                        "condition": "the dictation states a technical limitation of the study"}}]


async def test_a_stored_fragment_wording_is_never_a_rule_and_comes_back_as_a_card():
    from rapid_reports_ai import template_rules_cards as trc
    cond = "the dictation states a technical limitation of the study"
    with_rule = LEDGER_SHEET.replace('FIXED "Axial images were acquired."\n',
                                     f'FIXED "Axial images were acquired."\nRULE WHEN [context: {cond}] USE "{_FRAG}"\n', 1)
    for sheet in (LEDGER_SHEET, with_rule):
        out = await S.vet_sheet(sheet, origin="analyser", ledger=FRAGMENT)
        assert out.status == "saved" and _FRAG not in out.sheet and cond not in out.sheet
        assert out.ledger == FRAGMENT and len(td.clean_ledger(out.ledger)) == 1     # never silently forgotten
        assert [e["key"] for e in out.ledger_unmatched] == ["limitation"]
        cards = trc.unmatched_cards(out.ledger_unmatched)
        assert len(cards) == 1 and cards[0]["step"] == "review"
        assert cards[0]["title"] == f"Your wording '{_FRAG}' can't be used as a full sentence"
        assert [c["id"] for c in cards[0]["choices"]] == ["edit", "dictated"]
        assert cards[0]["choices"][1]["choice"] == {"use": False, "default": "", "when_met": "", "condition": "",
                                                    "dictated": True}


async def test_a_stored_fragment_with_a_default_keeps_the_default_only_shape_until_answered():
    from rapid_reports_ai import template_rules_cards as trc
    cond = "the dictation states a technical limitation of the study"
    led = [{**FRAGMENT[0], "choice": {**FRAGMENT[0]["choice"], "default": "Image quality is adequate."}}]
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=led)
    assert out.status == "saved" and _FRAG not in out.sheet
    assert 'FIXED "Image quality is adequate."' in out.sheet
    assert f'RULE WHEN [context: {cond}] SUPPRESS "Image quality is adequate."' in out.sheet
    assert [e["key"] for e in out.ledger_unmatched] == ["limitation"]
    card = trc.unmatched_cards(out.ledger_unmatched)[0]
    assert card["wording"] == {"default": "Image quality is adequate.", "when_met": _FRAG, "condition": cond}
    assert [c["id"] for c in card["choices"]] == ["edit", "dictated"]
    from rapid_reports_ai import template_sheet_lab_prompts as P
    block = P.decided_block(led)
    assert _FRAG not in block and f'SUPPRESS "Image quality is adequate."' in block
    # no default: whichever is dictated, and the card still starts from the fragment
    out = await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=FRAGMENT)
    assert cond not in out.sheet
    assert trc.unmatched_cards(out.ledger_unmatched)[0]["wording"]["when_met"] == _FRAG


async def test_a_chat_edit_that_breaks_a_decided_wording_is_unchanged_with_a_card():
    after = CMP_SHEET.replace("Compared with the previous {modality} of {date}.", "compared with the prior study")
    out = await S.vet_sheet(after, origin="chat", previous=CMP_SHEET, ledger=CMP)
    assert out.status == "unchanged" and out.sheet == CMP_SHEET and out.ledger == CMP and out.ledger_changes == []
    assert [(c["id"], c["reason"]) for c in out.ledger_cards] == [("concept:comparison", "invalid")]
    assert S.LEDGER_INVALID in S.ledger_notes(out) and S.LEDGER_KEPT not in S.ledger_notes(out)


async def test_a_chat_reworded_negative_is_rekeyed_not_removed():
    key = td.negative_key("Liver", "No focal liver lesion.")
    led = _led(("normal", key, {"text": "No focal liver lesion."}))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace('NEGATIVE "No focal liver lesion."', 'NEGATIVE "No focal hepatic lesion."')
    out = await S.vet_sheet(after, origin="chat", previous=before, ledger=led)
    assert out.sheet == after and out.ledger_unmatched == []
    assert [(e["key"], e["choice"], e["source"]) for e in out.ledger] == [
        ('Liver :: "No focal hepatic lesion."', {"text": "No focal hepatic lesion."}, "chat")]
    assert td.describe_change(out.ledger_changes[0]) == ('This changes something you confirmed: Liver: "No focal liver '
                                                         'lesion." → Liver: "No focal hepatic lesion.".')


async def test_a_restated_line_is_a_short_notice():
    out = await S.vet_sheet(RESTATED, origin="analyser", ledger=COMPARISON)
    assert S.LEDGER_RESTATED in S.ledger_notes(out)
    assert S.ledger_notes(await S.vet_sheet(LEDGER_SHEET, origin="analyser", ledger=COMPARISON)) == []


async def test_habit_lines_nobody_confirmed_are_kept_inactive_and_reported():
    from tests.template_sheet_fixtures import HABIT_SHEET
    line = 'NEGATIVE "No extension into the gallbladder." WHEN [findings: a focal liver abnormality is reported]'
    stray = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n', 'NEGATIVE "No focal liver lesion."\n' + line + "\n")
    for ledger in (None, []):
        out = await S.vet_sheet(stray, origin="analyser", ledger=ledger)
        assert out.status == "saved" and line in out.sheet, ledger
        assert [e["key"] for e in out.habits_pending] == ["Liver :: a focal liver abnormality is reported"], ledger
    plain = await S.vet_sheet(HABIT_SHEET, origin="analyser")
    assert plain.sheet == HABIT_SHEET and plain.habits_pending == []
