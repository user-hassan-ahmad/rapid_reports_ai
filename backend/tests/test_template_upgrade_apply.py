import json

import pytest

from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database.models import Template, TemplateChatTurn, TemplateExample, TemplateVersion, User
from rapid_reports_ai.scripts import template_upgrade_apply as U
from rapid_reports_ai.template_sheet_checks import NOT_NORMAL, UnitFailure
from tests.conftest import _make_template
from tests.template_sheet_fixtures import BAD_UNIT, GOOD

OLD = "Free-form skill sheet: describe the knee."


@pytest.fixture
def no_jev(monkeypatch):
    async def none(st, sheet=""):
        return []
    monkeypatch.setattr(S, "check_units", none)


@pytest.fixture
def templates(db_session, test_user):
    guided = _make_template(db_session, test_user, "Knee",
                            {"generation_mode": "skill_sheet_guided", "skill_sheet": OLD, "analyser_version": "old-v1"})
    legacy = _make_template(db_session, test_user, "Legacy", {"sections": []})
    return guided, legacy


def _entry(tid, new_sheet, old_hash=None):
    return {"template_id": str(tid), "old_sheet_hash": old_hash or tss.sheet_hash(OLD), "new_sheet": new_sheet}


def _manifest(tmp_path, tid, new_sheet, old_hash=None, legacy_ids=(), **extra):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"templates": [_entry(tid, new_sheet, old_hash)],
                             "legacy_ids": [str(i) for i in legacy_ids], **extra}))
    return p


def _write_manifest(tmp_path, data):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(data))
    return p


def _backups(tmp_path):
    return list(tmp_path.glob("template_upgrade_backup_*.json"))


def _actions(summary):
    return {r["template_id"]: r["action"] for r in summary["templates"]}


def test_apply_writes_vetted_sheet_snapshots_old_and_soft_deletes_legacy(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    summary = U.main(_manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id], analyser_version="grammar-v2"),
                     apply=True, db=db_session)
    assert _actions(summary) == {str(guided.id): "written", str(legacy.id): "soft-deleted"}
    db_session.expire_all()
    cfg = db_session.get(Template, guided.id).template_config
    assert cfg["skill_sheet"] == GOOD and cfg["generation_mode"] == "skill_sheet_guided"
    assert cfg["coverage_sections"] == ["FINDINGS", "IMPRESSION"] and cfg["analyser_version"] == "grammar-v2"
    assert tss.current_grammar(cfg) and tss.fresh(cfg) is not None  # structure stored for the new sheet
    sheets = [v.template_config.get("skill_sheet") for v in
              db_session.query(TemplateVersion).filter(TemplateVersion.template_id == guided.id)]
    assert OLD in sheets and GOOD in sheets
    assert db_session.get(Template, legacy.id).is_active is False
    (backup,) = _backups(tmp_path)
    data = json.loads(backup.read_text())
    assert data["converted"][str(guided.id)]["skill_sheet"] == OLD and str(legacy.id) in data["legacy"]
    assert summary["backup"] == str(backup)


def test_failing_new_unit_is_dropped_and_the_vetted_sheet_written(db_session, templates, tmp_path, monkeypatch):
    async def fails(st, sheet=""):
        return [UnitFailure(0, u.text, NOT_NORMAL) for u in st.normals if u.text == "Mild chondral thinning."]

    async def no_repair(sheet, errors):
        return sheet
    monkeypatch.setattr(S, "check_units", fails)
    monkeypatch.setattr(S, "_repair", no_repair)
    guided, _ = templates
    summary = U.main(_manifest(tmp_path, guided.id, BAD_UNIT), apply=True, db=db_session)
    row = next(r for r in summary["templates"] if r["template_id"] == str(guided.id))
    assert row["action"] == "written" and row["dropped_units"] == 1
    db_session.expire_all()
    assert "chondral" not in db_session.get(Template, guided.id).template_config["skill_sheet"]


def test_stale_hash_is_skipped_and_nothing_written(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    summary = U.main(_manifest(tmp_path, guided.id, GOOD, old_hash="0" * 64), apply=True, db=db_session)
    assert _actions(summary)[str(guided.id)] == "skipped-stale"
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == OLD
    assert db_session.query(TemplateVersion).filter(TemplateVersion.template_id == guided.id).count() == 0


def test_dry_run_writes_nothing_and_reports_the_plan(db_session, templates, tmp_path, no_jev, capsys):
    guided, legacy = templates
    summary = U.main(_manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id]), db=db_session)
    assert summary["apply"] is False and summary["backup"] is None
    assert _actions(summary) == {str(guided.id): "written", str(legacy.id): "soft-deleted"}
    assert summary["totals"] == {"written": 1, "soft-deleted": 1}
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == OLD
    assert db_session.get(Template, legacy.id).is_active is True
    assert db_session.query(TemplateVersion).count() == 0 and not _backups(tmp_path)
    out = capsys.readouterr().out
    assert "would be written" in out and "dry run: nothing written" in out
    assert "Knee" not in out and "menisci" not in out  # ids only: no names, no sheet text


def test_refused_sheet_is_skipped_with_the_reason(db_session, templates, tmp_path, no_jev):
    guided, _ = templates
    summary = U.main(_manifest(tmp_path, guided.id, "Still a free-form sheet."), apply=True, db=db_session)
    row = next(r for r in summary["templates"] if r["template_id"] == str(guided.id))
    assert row["action"] == "skipped-refused" and row["reason"] == S.LOST_STRUCTURE
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == OLD


def test_analyser_version_is_carried_when_the_manifest_sets_none(db_session, templates, tmp_path, no_jev):
    guided, _ = templates
    U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["analyser_version"] == "old-v1"


def test_bare_list_manifest_writes_templates_and_deletes_nothing(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    summary = U.main(_write_manifest(tmp_path, [_entry(guided.id, GOOD)]), apply=True, db=db_session)
    assert _actions(summary) == {str(guided.id): "written"}
    db_session.expire_all()
    assert db_session.get(Template, legacy.id).is_active is True


def test_rerun_reports_already_written_and_adds_no_version(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    path = _manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id])
    U.main(path, apply=True, db=db_session)
    versions = db_session.query(TemplateVersion).filter(TemplateVersion.template_id == guided.id).count()
    summary = U.main(path, apply=True, db=db_session)
    assert _actions(summary) == {str(guided.id): "already-written", str(legacy.id): "skipped-legacy-changed"}
    assert db_session.query(TemplateVersion).filter(TemplateVersion.template_id == guided.id).count() == versions


def test_rerun_after_a_dropped_unit_is_already_written(db_session, templates, tmp_path, monkeypatch):
    async def fails(st, sheet=""):
        return [UnitFailure(0, u.text, NOT_NORMAL) for u in st.normals if u.text == "Mild chondral thinning."]

    async def no_repair(sheet, errors):
        return sheet
    monkeypatch.setattr(S, "check_units", fails)
    monkeypatch.setattr(S, "_repair", no_repair)
    guided, _ = templates
    path = _manifest(tmp_path, guided.id, BAD_UNIT)
    U.main(path, apply=True, db=db_session)
    assert _actions(U.main(path, apply=True, db=db_session))[str(guided.id)] == "already-written"


def test_structure_failure_keeps_the_written_sheet_and_the_others_go_on(db_session, test_user, templates, tmp_path, no_jev,
                                                                    monkeypatch):
    guided, legacy = templates
    other = _make_template(db_session, test_user, "Hip", {"generation_mode": "skill_sheet_guided", "skill_sheet": OLD})
    real = tss.store_structure

    def boom(db, template_id, structure):
        if str(template_id) == str(guided.id):
            raise RuntimeError("secret sheet text")
        return real(db, template_id, structure)
    monkeypatch.setattr(tss, "store_structure", boom)
    path = _write_manifest(tmp_path, {"templates": [_entry(guided.id, GOOD), _entry(other.id, GOOD)],
                                      "legacy_ids": [str(legacy.id)]})
    summary = U.main(path, apply=True, db=db_session)
    rows = {r["template_id"]: r for r in summary["templates"]}
    assert rows[str(guided.id)] == {"template_id": str(guided.id), "action": "written", "dropped_units": 0,
                                    "structure_stored": False, "reason": "RuntimeError"}
    assert rows[str(other.id)]["action"] == "written" and rows[str(legacy.id)]["action"] == "soft-deleted"
    assert "secret" not in json.dumps(summary)
    db_session.expire_all()
    assert db_session.get(Template, other.id).template_config["skill_sheet"] == GOOD
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == GOOD


def test_rerun_stores_a_missing_structure(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, _ = templates

    def boom(db, template_id, structure):
        raise RuntimeError("down")
    path = _manifest(tmp_path, guided.id, GOOD)
    with monkeypatch.context() as m:
        m.setattr(tss, "store_structure", boom)
        U.main(path, apply=True, db=db_session)
    db_session.expire_all()
    assert tss.fresh(db_session.get(Template, guided.id).template_config) is None
    row = U.main(path, apply=True, db=db_session)["templates"][0]
    assert row["action"] == "already-written" and row["structure_stored"] is True
    db_session.expire_all()
    assert tss.fresh(db_session.get(Template, guided.id).template_config) is not None


def test_sheet_edited_during_the_snapshot_is_stale(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, _ = templates
    real = U.crud.create_template_version

    def snapshot_then_edit(db, t, skip_if_unchanged=False):
        v = real(db, t, skip_if_unchanged=skip_if_unchanged)
        t.template_config = {**t.template_config, "skill_sheet": "Edited meanwhile."}
        db.commit()
        return v
    monkeypatch.setattr(U.crud, "create_template_version", snapshot_then_edit)
    summary = U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    assert _actions(summary)[str(guided.id)] == "skipped-stale"
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == "Edited meanwhile."


def test_failed_snapshot_skips_the_template_as_error(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, _ = templates
    monkeypatch.setattr(U.crud, "create_template_version", lambda db, t, skip_if_unchanged=False: None)
    summary = U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    assert _actions(summary)[str(guided.id)] == "error"
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == OLD


def test_sheet_edited_between_plan_and_write_is_stale(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, _ = templates
    real = U._plan_entry

    async def plan_then_edit(db, entry, analyser_version=None):
        row = await real(db, entry, analyser_version)
        t = db.get(Template, guided.id)
        t.template_config = {**t.template_config, "skill_sheet": "Edited meanwhile."}
        db.commit()
        return row
    monkeypatch.setattr(U, "_plan_entry", plan_then_edit)
    summary = U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    assert _actions(summary)[str(guided.id)] == "skipped-stale"
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == "Edited meanwhile."
    assert db_session.query(TemplateVersion).filter(TemplateVersion.template_id == guided.id).count() == 0


def test_skip_paths(db_session, test_user, tmp_path, no_jev):
    import uuid
    inactive = _make_template(db_session, test_user, "Gone",
                              {"generation_mode": "skill_sheet_guided", "skill_sheet": OLD})
    inactive.is_active = False
    db_session.commit()
    other_mode = _make_template(db_session, test_user, "Quick", {"generation_mode": "quick", "skill_sheet": OLD})
    same = _make_template(db_session, test_user, "Same", {"generation_mode": "skill_sheet_guided", "skill_sheet": OLD})
    missing = uuid.uuid4()
    path = _write_manifest(tmp_path, {"templates": [_entry(missing, GOOD), _entry(inactive.id, GOOD),
                                                    _entry(other_mode.id, GOOD), _entry(same.id, OLD)]})
    summary = U.main(path, apply=True, db=db_session)
    assert _actions(summary) == {str(missing): "skipped-missing", str(inactive.id): "skipped-inactive",
                                 str(other_mode.id): "skipped-mode", str(same.id): "skipped-unchanged"}
    assert db_session.query(TemplateVersion).count() == 0


def test_templates_outside_the_manifest_are_untouched(db_session, test_user, templates, tmp_path, no_jev):
    guided, legacy = templates
    mine = _make_template(db_session, test_user, "Other", {"generation_mode": "skill_sheet_guided", "skill_sheet": OLD})
    stranger = User(email="s@nhs.net", password_hash="x", full_name="S", is_active=True, is_verified=True,
                    is_approved=True)
    db_session.add(stranger)
    db_session.commit()
    theirs = _make_template(db_session, stranger, "Theirs",
                            {"generation_mode": "skill_sheet_guided", "skill_sheet": OLD})
    summary = U.main(_manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id]), apply=True, db=db_session)
    assert set(_actions(summary)) == {str(guided.id), str(legacy.id)}
    db_session.expire_all()
    for t in (mine, theirs):
        got = db_session.get(Template, t.id)
        assert got.is_active and got.template_config["skill_sheet"] == OLD


def test_backup_holds_the_examples_and_chat_turns_a_delete_removes(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    db_session.add(TemplateExample(template_id=legacy.id, text="An example report.", sha256="a" * 64))
    db_session.add(TemplateChatTurn(template_id=legacy.id, instruction="Shorter impression.", response="Done."))
    db_session.commit()
    summary = U.main(_manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id]), apply=True, db=db_session)
    assert _actions(summary)[str(legacy.id)] == "soft-deleted"
    assert db_session.query(TemplateExample).count() == 0 and db_session.query(TemplateChatTurn).count() == 0
    data = json.loads(_backups(tmp_path)[0].read_text())["legacy"][str(legacy.id)]
    (ex,) = data["examples"]
    (turn,) = data["chat_turns"]
    assert ex["text"] == "An example report." and ex["template_id"] == str(legacy.id) and ex["created_at"]
    assert turn["instruction"] == "Shorter impression." and turn["response"] == "Done." and turn["applied"] is True


def test_legacy_deletion_is_scoped_to_listed_ids(db_session, test_user, templates, tmp_path, no_jev):
    guided, legacy = templates
    unlisted = _make_template(db_session, test_user, "Legacy 2", {"sections": []})
    path = _write_manifest(tmp_path, {"templates": [_entry(guided.id, GOOD)],
                                      "legacy_ids": [str(legacy.id), str(guided.id)]})
    summary = U.main(path, apply=True, db=db_session)
    assert _actions(summary) == {str(guided.id): "written", str(legacy.id): "soft-deleted"}
    assert summary["totals"] == {"written": 1, "soft-deleted": 1}
    db_session.expire_all()
    assert db_session.get(Template, unlisted.id).is_active is True
    assert db_session.get(Template, guided.id).is_active is True


def test_listed_legacy_id_that_changed_is_reported(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    legacy.template_config = {"generation_mode": "skill_sheet_guided", "skill_sheet": OLD}
    db_session.commit()
    summary = U.main(_manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id]), apply=True, db=db_session)
    assert _actions(summary)[str(legacy.id)] == "skipped-legacy-changed"
    db_session.expire_all()
    assert db_session.get(Template, legacy.id).is_active is True
