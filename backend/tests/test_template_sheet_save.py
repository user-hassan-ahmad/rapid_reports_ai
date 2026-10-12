import pytest

from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai.template_sheet_checks import NOT_NORMAL, UnitFailure
from tests.template_sheet_fixtures import BAD_UNIT, GOOD


def _fails_on(*texts):
    async def fails(st, sheet=""):
        units = [*st.normals, *st.negatives]
        return [UnitFailure(0, u.text, NOT_NORMAL) for u in units if u.text in texts]
    return fails


async def _no_repair(sheet, errors):
    return sheet


@pytest.fixture
def no_jev(monkeypatch):
    async def none(st, sheet=""):
        return []
    monkeypatch.setattr(S, "check_units", none)


def test_fixtures_are_usable():
    assert tsg.parse_sheet(GOOD, mode="template").structure.usable
    assert tsg.parse_sheet(BAD_UNIT, mode="template").structure.usable


async def test_unchanged_sheet_is_skipped(no_jev):
    out = await S.vet_sheet(GOOD, origin="chat", previous=GOOD)
    assert out.status == "unchanged" and out.sheet == GOOD


async def test_clean_sheet_is_saved_with_coverage(no_jev):
    out = await S.vet_sheet(GOOD, origin="analyser", previous="")
    assert out.status == "saved" and out.sheet == GOOD
    assert out.coverage_sections == ["FINDINGS", "IMPRESSION"]


async def test_check_units_gets_the_sheet_text(monkeypatch):
    seen = []

    async def spy(st, sheet=""):
        seen.append(sheet)
        return []
    monkeypatch.setattr(S, "check_units", spy)
    await S.vet_sheet(GOOD, origin="analyser")
    assert seen == [GOOD]


async def test_failing_new_unit_from_the_analyser_is_dropped(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(BAD_UNIT, origin="analyser", previous="")
    assert out.status == "saved" and out.sheet == GOOD
    assert out.dropped == [{"text": "Mild chondral thinning.", "reason": NOT_NORMAL}]


async def test_failing_new_unit_in_a_rebuild_is_dropped_keeping_existing(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(BAD_UNIT, origin="rebuild", previous=GOOD)
    assert out.status == "saved" and out.sheet == GOOD


async def test_repair_that_fixes_the_unit_is_saved_without_drops(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))
    calls = []

    async def fix(sheet, errors):
        calls.append(errors)
        return sheet.replace("Mild chondral thinning.", "The cartilage is preserved.")
    monkeypatch.setattr(S, "_repair", fix)
    out = await S.vet_sheet(BAD_UNIT, origin="chat", previous=GOOD)
    assert out.status == "saved" and "The cartilage is preserved." in out.sheet and out.dropped == []
    assert len(calls) == 1 and calls[0][0]["text"] == "Mild chondral thinning."


async def test_failing_unit_in_a_chat_edit_is_refused(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(BAD_UNIT, origin="chat", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD
    assert "Mild chondral thinning." in out.message


async def test_grammar_to_free_form_is_refused(no_jev):
    out = await S.vet_sheet("# Old free-form sheet\nSome prose.", origin="chat", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD


async def test_unusable_sheet_that_repair_cannot_fix_is_refused(no_jev, monkeypatch):
    monkeypatch.setattr(S, "_repair", _no_repair)
    broken = GOOD.replace('SECTION IMPRESSION | header: "Impression:" | role: impression\n', "")
    out = await S.vet_sheet(broken, origin="analyser", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD and "readable" in out.message


async def test_losing_an_existing_unit_automatically_is_refused(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("The menisci are intact."))
    monkeypatch.setattr(S, "_repair", _no_repair)
    changed = GOOD + 'NORMAL [ligaments] "The cruciate ligaments are intact."\n'
    out = await S.vet_sheet(changed, origin="rebuild", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD and "every report" in out.message


async def test_a_jev_error_refuses_the_write(monkeypatch):
    async def boom(st, sheet=""):
        raise RuntimeError("jev down")
    monkeypatch.setattr(S, "check_units", boom)
    out = await S.vet_sheet(GOOD, origin="analyser", previous="")
    assert out.status == "refused" and "try again" in out.message.lower()


async def test_a_repair_error_refuses_the_write(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))

    async def boom(sheet, errors):
        raise RuntimeError("model down")
    monkeypatch.setattr(S, "_repair", boom)
    out = await S.vet_sheet(BAD_UNIT, origin="analyser", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD and "try again" in out.message.lower()


def test_drop_lines_removes_exactly_the_failing_unit_lines():
    sheet = (GOOD
             + 'NEGATIVE "No effusion."\n'
             + 'NORMAL [bone] "No effusion. Bones normal."\n'
             + 'RULE WHEN [context: x] REPLACE "No effusion." WITH "Small effusion."\n')
    out = S._drop_lines(sheet, {"No effusion."})
    assert 'NEGATIVE "No effusion."' not in out
    assert 'NORMAL [bone] "No effusion. Bones normal."' in out
    assert 'REPLACE "No effusion."' in out
    assert out.count("\n") == sheet.count("\n") - 1
