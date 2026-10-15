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


async def test_a_failing_existing_unit_is_not_rejudged_on_an_automatic_write(monkeypatch):
    # was test_losing_an_existing_unit_automatically_is_refused: pre-existing failures are no longer re-judged
    monkeypatch.setattr(S, "check_units", _fails_on("The menisci are intact."))
    monkeypatch.setattr(S, "_repair", _no_repair)
    changed = GOOD + 'NORMAL [ligaments] "The cruciate ligaments are intact."\n'
    out = await S.vet_sheet(changed, origin="rebuild", previous=GOOD)
    assert out.status == "saved" and out.sheet == changed and out.dropped == []


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


async def test_repair_that_deletes_a_passing_unit_is_refused(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))

    async def lossy(sheet, errors):
        return (sheet.replace('NORMAL [menisci] "The menisci are intact."\n', "")
                .replace("Mild chondral thinning.", "The cartilage is preserved."))
    monkeypatch.setattr(S, "_repair", lossy)
    out = await S.vet_sheet(BAD_UNIT, origin="analyser", previous="")
    assert out.status == "refused" and out.sheet == "" and "safely" in out.message


async def test_repair_that_only_fixes_the_failing_unit_is_saved(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))

    async def fix(sheet, errors):
        return sheet.replace("Mild chondral thinning.", "The cartilage is preserved.")
    monkeypatch.setattr(S, "_repair", fix)
    out = await S.vet_sheet(BAD_UNIT, origin="analyser", previous="")
    assert out.status == "saved" and "The menisci are intact." in out.sheet
    assert out.message == S.reworded_notice(1)   # an automatic rewrite is reported, never silent


async def test_a_rebuild_whose_repair_rewrites_a_unit_reports_it(monkeypatch):
    """Lab case: the repair stripped the slots from a NORMAL line; the save must say so."""
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))

    async def strip(sheet, errors):
        return sheet.replace("Mild chondral thinning.", "The cartilage is normal.")
    monkeypatch.setattr(S, "_repair", strip)
    out = await S.vet_sheet(BAD_UNIT, origin="rebuild", previous="")
    assert out.status == "saved" and out.dropped == []
    assert out.message == S.reworded_notice(1) and "reworded" in out.message


async def test_a_clean_automatic_write_has_no_notice(no_jev):
    out = await S.vet_sheet(GOOD, origin="rebuild", previous="")
    assert out.status == "saved" and out.message == ""


async def test_a_drop_that_leaves_the_failing_unit_is_refused(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))
    monkeypatch.setattr(S, "_repair", _no_repair)
    monkeypatch.setattr(S, "_drop_lines", lambda sheet, texts: sheet)
    out = await S.vet_sheet(BAD_UNIT, origin="analyser", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD


async def test_a_chat_edit_adjusted_by_the_repair_carries_a_notice(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))

    async def fix(sheet, errors):
        return sheet.replace("Mild chondral thinning.", "The cartilage is preserved.")
    monkeypatch.setattr(S, "_repair", fix)
    out = await S.vet_sheet(BAD_UNIT, origin="chat", previous=GOOD)
    assert out.status == "saved" and out.message == S.ADJUSTED


async def test_a_clean_chat_edit_has_no_notice(no_jev):
    out = await S.vet_sheet(BAD_UNIT, origin="chat", previous=GOOD)
    assert out.status == "saved" and out.message == ""


async def test_chat_refusal_pairs_each_text_with_its_own_reason(monkeypatch):
    from rapid_reports_ai.template_sheet_checks import PLACEHOLDER
    sheet = BAD_UNIT + 'NORMAL [bone] "The bones are {x}."\n'

    async def fails(st, sheet=""):
        return [UnitFailure(0, "Mild chondral thinning.", NOT_NORMAL),
                UnitFailure(0, "The bones are {x}.", PLACEHOLDER)]
    monkeypatch.setattr(S, "check_units", fails)
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(sheet, origin="chat", previous=GOOD)
    assert out.status == "refused"
    assert f'"Mild chondral thinning." ({S.REASON_TEXT[NOT_NORMAL]})' in out.message
    assert f'"The bones are {{x}}." ({S.REASON_TEXT[PLACEHOLDER]})' in out.message
    assert PLACEHOLDER not in out.message and NOT_NORMAL not in out.message  # report language, not sheet terms


async def test_repair_that_rewrites_an_existing_unit_is_refused(monkeypatch):
    # was ..._rewrites_a_failing_existing_unit_...: the existing unit no longer fails, so a new failure triggers repair
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))

    async def rewrite(sheet, errors):
        return sheet.replace("The menisci are intact.", "The menisci are preserved.")
    monkeypatch.setattr(S, "_repair", rewrite)
    for origin in ("rebuild", "chat"):
        out = await S.vet_sheet(BAD_UNIT, origin=origin, previous=GOOD)
        assert out.status == "refused" and out.sheet == GOOD


# ── only what a write adds or changes is checked (pre-existing failures are not the editor's) ──

OLD_SLOT_LINE = 'NORMAL [lv] "Normal LV size ({value} ml/m2)."'
PREV_SLOTTED = GOOD + OLD_SLOT_LINE + "\n"


def _slot_fails():
    from rapid_reports_ai.template_sheet_checks import PLACEHOLDER

    async def fails(st, sheet=""):
        return [UnitFailure(0, u.text, PLACEHOLDER) for u in [*st.normals, *st.negatives] if "{" in u.text]
    return fails


@pytest.mark.parametrize("origin", ["chat", "rebuild", "restore"])
async def test_a_pre_existing_failing_unit_does_not_block_an_edit(monkeypatch, origin):
    repairs = []

    async def repair(sheet, errors):
        repairs.append(errors)
        return sheet
    monkeypatch.setattr(S, "check_units", _slot_fails())
    monkeypatch.setattr(S, "_repair", repair)
    edited = PREV_SLOTTED + 'NORMAL [ligaments] "The cruciate ligaments are intact."\n'
    out = await S.vet_sheet(edited, origin=origin, previous=PREV_SLOTTED)
    assert out.status == "saved" and out.sheet == edited and out.message == "" and repairs == []
    assert OLD_SLOT_LINE in out.sheet.splitlines()  # byte-identical


async def test_a_new_failing_unit_beside_an_old_one_refuses_naming_only_the_new(monkeypatch):
    monkeypatch.setattr(S, "check_units", _slot_fails())
    monkeypatch.setattr(S, "_repair", _no_repair)
    edited = PREV_SLOTTED + 'NORMAL [bone] "The bones are {x}."\n'
    out = await S.vet_sheet(edited, origin="chat", previous=PREV_SLOTTED)
    assert out.status == "refused" and out.sheet == PREV_SLOTTED
    assert "The bones are {x}." in out.message and "Normal LV size" not in out.message


async def test_repair_is_asked_only_about_new_failures_and_must_keep_old_units(monkeypatch):
    seen = []

    async def repair(sheet, errors):
        seen.append([e["text"] for e in errors])
        return sheet.replace('NORMAL [bone] "The bones are {x}."\n', 'NORMAL [bone] "The bones are normal."\n')
    monkeypatch.setattr(S, "check_units", _slot_fails())
    monkeypatch.setattr(S, "_repair", repair)
    edited = PREV_SLOTTED + 'NORMAL [bone] "The bones are {x}."\n'
    out = await S.vet_sheet(edited, origin="chat", previous=PREV_SLOTTED)
    assert seen == [["The bones are {x}."]]
    assert out.status == "saved" and OLD_SLOT_LINE in out.sheet.splitlines() and out.message == S.ADJUSTED


async def test_a_lint_error_already_in_the_previous_sheet_is_ignored(no_jev, monkeypatch):
    bad_line = "COVERS menisci without brackets"
    prev = GOOD + bad_line + "\n"
    assert any(e.text.strip() == bad_line for e in tsg.parse_sheet(prev, mode="template").errors)
    repairs = []

    async def repair(sheet, errors):
        repairs.append(errors)
        return sheet
    monkeypatch.setattr(S, "_repair", repair)
    edited = prev + 'NORMAL [ligaments] "The cruciate ligaments are intact."\n'
    out = await S.vet_sheet(edited, origin="chat", previous=prev)
    assert out.status == "saved" and out.sheet == edited and repairs == []


async def test_a_whitespace_only_change_is_unchanged_without_checks(monkeypatch):
    async def boom(st, sheet=""):
        raise AssertionError("checked")
    monkeypatch.setattr(S, "check_units", boom)
    out = await S.vet_sheet("\n" + GOOD.replace("\n\n", "\n\n\n").replace('"Findings:"', '"Findings:"  ') + "\n\n",
                            origin="chat", previous=GOOD)
    assert out.status == "unchanged" and out.sheet == GOOD


async def test_a_whitespace_only_repair_of_a_chat_edit_has_no_notice(monkeypatch):
    calls = []

    async def fails(st, sheet=""):
        calls.append(sheet)
        return [UnitFailure(0, "Mild chondral thinning.", NOT_NORMAL)] if len(calls) == 1 else []

    async def respace(sheet, errors):
        return sheet.replace("\n\n", "\n\n\n")
    monkeypatch.setattr(S, "check_units", fails)
    monkeypatch.setattr(S, "_repair", respace)
    out = await S.vet_sheet(BAD_UNIT, origin="chat", previous=GOOD)
    assert out.status == "saved" and out.sheet != BAD_UNIT and out.message == ""


# ── voice lines (W1): a style line never refuses an automatic write ─────────────

VOICE_LINE = "Opening: When the study is normal, no further comment is made."
VOICE = GOOD + VOICE_LINE + "\n"
LABELLED = GOOD + 'Opening (normal): "The menisci are intact."\nOpening (abnormal): "There is a {pattern} tear."\n'


def _counting_no_repair(calls):
    async def repair(sheet, errors):
        calls.append(errors)
        return sheet
    return repair


@pytest.mark.parametrize("origin", ["analyser", "repair", "rebuild"])
async def test_a_voice_line_still_failing_after_the_repair_is_dropped(no_jev, monkeypatch, origin):
    calls = []
    monkeypatch.setattr(S, "_repair", _counting_no_repair(calls))
    out = await S.vet_sheet(VOICE, origin=origin, previous="")
    assert out.status == "saved" and out.sheet == GOOD
    assert out.dropped == [{"text": VOICE_LINE, "reason": tsg.CONDITIONAL_NEGATIVE}]
    assert len(calls) == 1  # no second repair pass


@pytest.mark.parametrize("origin", ["chat", "restore"])
async def test_a_voice_line_in_a_user_edit_is_refused(no_jev, monkeypatch, origin):
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(VOICE, origin=origin, previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD and out.message == S.UNREADABLE


async def test_a_voice_line_with_a_unit_error_is_still_refused(no_jev, monkeypatch):
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(VOICE + 'NORMAL "no structure label"\n', origin="analyser")
    assert out.status == "refused" and out.message == S.UNREADABLE


async def test_a_prose_negative_outside_a_paragraph_is_still_refused(no_jev, monkeypatch):
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(GOOD + "\n## Notes\nAscites is absent.\n", origin="analyser")
    assert out.status == "refused"


async def test_units_are_checked_after_a_voice_line_drop(monkeypatch):
    monkeypatch.setattr(S, "check_units", _fails_on("Mild chondral thinning."))
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(BAD_UNIT + VOICE_LINE + "\n", origin="analyser")
    assert out.status == "saved" and out.sheet == GOOD
    assert [d["text"] for d in out.dropped] == [VOICE_LINE, "Mild chondral thinning."]


async def test_labelled_openings_save_unchanged_without_a_repair(no_jev, monkeypatch):
    calls = []
    monkeypatch.setattr(S, "_repair", _counting_no_repair(calls))
    out = await S.vet_sheet(LABELLED, origin="analyser")
    assert out.status == "saved" and out.sheet == LABELLED and calls == [] and out.dropped == []


@pytest.mark.parametrize("change", ["drop_impression", "new_lint_error"])
async def test_old_lint_errors_do_not_excuse_new_damage(no_jev, monkeypatch, change):
    prev = GOOD + "COVERS menisci without brackets\n"
    if change == "drop_impression":
        edited = prev.replace('SECTION IMPRESSION | header: "Impression:" | role: impression\n', "")
    else:
        edited = prev + "NEGATIVE without quotes\n"
    monkeypatch.setattr(S, "_repair", _no_repair)
    out = await S.vet_sheet(edited, origin="chat", previous=prev)
    assert out.status == "refused" and out.sheet == prev and "readable" in out.message


# ── persist_sheet: the one persisted save (stable line IDs spec, "Where rebind runs") ─────────────────────────────

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_line_registry as tlr
from tests.template_sheet_fixtures import LEDGER_SHEET


def _cfg(sheet, **extra):
    return {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, **extra}


def _uids(sheet, reg):
    return tlr.uids_for(tsg.parse_sheet(sheet).structure, reg)


async def test_a_first_save_mints_the_registry_and_sheet_rev_1(no_jev):
    p = await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")
    assert p.outcome.status == "saved" and p.config["sheet_rev"] == 1
    assert len(p.report["new"]) == len(p.config["line_registry"]["units"]) == 10
    assert p.config["coverage_sections"] == ["TECHNIQUE", "FINDINGS", "IMPRESSION"]


async def test_sheet_rev_increments_from_the_stored_value_only_on_a_sheet_change(no_jev):
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    stored = {**first, "sheet_rev": 7}
    same = await S.persist_sheet(_cfg(LEDGER_SHEET, sheet_rev=99), stored, "chat", now="T")
    assert same.outcome.status == "unchanged" and same.config["sheet_rev"] == 7
    edited = LEDGER_SHEET.replace('FIXED "No previous imaging available."\n', "")
    changed = await S.persist_sheet(_cfg(edited, sheet_rev=99), stored, "chat", now="T")
    assert changed.config["sheet_rev"] == 8 and len(changed.report["gone"]) == 1


async def test_the_stored_registry_is_used_never_the_clients(no_jev):
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    forged = {"v": 1, "units": {"n_aaaaaa": {"kind": "normal", "identity": {}, "status": "live"}}}
    p = await S.persist_sheet(_cfg(LEDGER_SHEET, line_registry=forged), first, "chat", now="T")
    assert p.config["line_registry"] == first["line_registry"]


async def test_the_ledger_is_stamped_after_the_rebind(no_jev):
    led, _ = td.set_decision([], "normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."},
                             source="creation", at="t")
    p = await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", ledger=led, now="T")
    reg = p.config["line_registry"]
    assert p.config["decisions"][0]["uid"] == _uids(p.config["skill_sheet"], reg)["m0"]


async def test_a_refused_sheet_persists_nothing(no_jev):
    p = await S.persist_sheet(_cfg("# Free\nprose"), {}, "analyser", now="T")
    assert p.outcome.status == "refused" and p.config is None


async def test_persist_strips_client_server_written_keys_and_keeps_the_stored_ones(no_jev):
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    client = _cfg(LEDGER_SHEET, uncertain=[{"uid": "x"}], normal_confirms={"x": {}}, sheet_rev=50)
    fresh = await S.persist_sheet(client, {}, "analyser", now="T")
    assert "uncertain" not in fresh.config and "normal_confirms" not in fresh.config and fresh.config["sheet_rev"] == 1
    stored = {**first, "uncertain": [{"uid": "kept"}], "normal_confirms": {"g": {"kept": True}}}
    again = await S.persist_sheet(client, stored, "chat", now="T")
    assert again.config["uncertain"] == [{"uid": "kept"}] and again.config["normal_confirms"] == {"g": {"kept": True}}


async def test_a_registry_error_starts_a_fresh_registry_and_never_fails_the_save(no_jev, monkeypatch):
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    real = tlr.rebind

    def boom(registry, st, carried=None, *, now=None):
        if tlr.load(registry)["units"]:
            raise TypeError("malformed registry")
        return real(registry, st, carried, now=now)
    monkeypatch.setattr(tlr, "rebind", boom)
    edited = LEDGER_SHEET.replace('FIXED "No previous imaging available."\n', "")
    p = await S.persist_sheet(_cfg(edited), first, "chat", now="T")
    assert p.outcome.status == "saved" and p.config["sheet_rev"] == 2
    assert len(p.config["line_registry"]["units"]) == 9 and len(p.report["new"]) == 9


async def test_persist_prunes_gone_units_but_keeps_those_the_ledger_or_confirms_name(no_jev, monkeypatch):
    monkeypatch.setattr(tlr, "MAX_GONE", 1)
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    uids = _uids(LEDGER_SHEET, first["line_registry"])
    gone_fixed, gone_neg = uids["f1"], uids["n0"]
    edited = LEDGER_SHEET.replace('FIXED "No previous imaging available."\n', "").replace(
        'NEGATIVE "No focal liver lesion."\n', "").replace('FIXED "Axial images were acquired."\n', "")
    stored = {**first, "normal_confirms": {"g": {"units": {gone_neg: "sha256:x"}}}}
    p = await S.persist_sheet(_cfg(edited), stored, "chat", now="T")
    units = p.config["line_registry"]["units"]
    assert len(p.report["gone"]) == 3 and gone_neg in units
    assert len([u for u, e in units.items() if e["status"] == "gone"]) == 2   # the cap (1) + the referenced one
