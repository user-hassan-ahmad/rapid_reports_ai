"""The conversion's way back (integration spec D17): restore converted templates' old configs and undo the
legacy soft-deletes, with their examples and chat turns, from the conversion's own backup."""
import hashlib
import json
import uuid

from rapid_reports_ai.database.models import Template, TemplateChatTurn, TemplateExample, TemplateVersion
from rapid_reports_ai.scripts import template_upgrade_apply as U
from rapid_reports_ai.scripts import template_upgrade_restore as R
from tests.template_sheet_fixtures import GOOD
from tests.test_template_upgrade_apply import OLD, _backups, _manifest, no_jev, templates  # noqa: F401


def _example(db, t, text="example report"):
    db.add(TemplateExample(id=uuid.uuid4(), template_id=t.id, text=text, sha256=hashlib.sha256(text.encode()).hexdigest()))
    db.commit()


def _converted(db_session, templates, tmp_path):
    guided, legacy = templates
    _example(db_session, legacy)
    U.main(_manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id]), apply=True, db=db_session)
    (backup,) = _backups(tmp_path)
    return guided, legacy, backup


def test_dry_run_changes_nothing(db_session, templates, tmp_path, no_jev):
    guided, legacy, backup = _converted(db_session, templates, tmp_path)
    out = R.main(backup, apply=False, db=db_session)
    assert {r["action"] for r in out["templates"]} == {"would restore", "would reactivate"}
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == GOOD
    assert db_session.get(Template, legacy.id).is_active is False


def test_apply_restores_configs_and_reactivates_legacy_with_its_rows(db_session, templates, tmp_path, no_jev):
    guided, legacy, backup = _converted(db_session, templates, tmp_path)
    out = R.main(backup, apply=True, db=db_session)
    assert {r["template_id"]: r["action"] for r in out["templates"]} == {
        str(guided.id): "restored", str(legacy.id): "reactivated"}
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == OLD
    assert db_session.get(Template, legacy.id).is_active is True
    assert db_session.query(TemplateExample).filter(TemplateExample.template_id == legacy.id).count() == 1
    sheets = [v.template_config.get("skill_sheet") for v in
              db_session.query(TemplateVersion).filter(TemplateVersion.template_id == guided.id)]
    assert GOOD in sheets   # the converted state is snapshotted before it is replaced


def test_rerun_is_a_no_op(db_session, templates, tmp_path, no_jev):
    guided, legacy, backup = _converted(db_session, templates, tmp_path)
    R.main(backup, apply=True, db=db_session)
    out = R.main(backup, apply=True, db=db_session)
    assert {r["action"] for r in out["templates"]} == {"already-restored", "already-active"}
    assert db_session.query(TemplateExample).filter(TemplateExample.template_id == legacy.id).count() == 1


def test_missing_template_is_reported_not_raised(db_session, tmp_path):
    p = tmp_path / "template_upgrade_backup_1.json"
    p.write_text(json.dumps({"converted": {str(uuid.uuid4()): {"sections": []}}, "legacy": {}}))
    out = R.main(p, apply=True, db=db_session)
    assert [r["action"] for r in out["templates"]] == ["skipped-missing"]


def test_sheet_edited_after_the_upgrade_is_not_overwritten(db_session, templates, tmp_path, no_jev):
    guided, legacy, backup = _converted(db_session, templates, tmp_path)
    t = db_session.get(Template, guided.id)
    t.template_config = {**t.template_config, "skill_sheet": "Edited after the ship."}
    db_session.commit()
    for apply in (False, True):
        out = R.main(backup, apply=apply, db=db_session)
        assert {r["template_id"]: r["action"] for r in out["templates"]}[str(guided.id)] == "skipped-edited-since"
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == "Edited after the ship."


def test_a_template_the_upgrade_skipped_as_stale_is_not_restored(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, _ = templates
    real = U._plan_entry

    async def plan_then_edit(db, entry, analyser_version=None):
        row = await real(db, entry, analyser_version)
        t = db.get(Template, guided.id)
        t.template_config = {**t.template_config, "skill_sheet": "Edited meanwhile."}
        db.commit()
        return row
    monkeypatch.setattr(U, "_plan_entry", plan_then_edit)
    U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    (backup,) = _backups(tmp_path)
    out = R.main(backup, apply=True, db=db_session)
    assert {r["template_id"]: r["action"] for r in out["templates"]}[str(guided.id)] != "restored"
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == "Edited meanwhile."


def test_a_legacy_template_the_upgrade_did_not_delete_stays_deleted(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, legacy = templates
    real = U._soft_delete

    def user_deletes_first(db, row):
        t = db.get(Template, legacy.id)
        t.is_active = False   # the radiologist deleted it between plan and write
        db.commit()
        real(db, row)
    monkeypatch.setattr(U, "_soft_delete", user_deletes_first)
    U.main(_manifest(tmp_path, guided.id, GOOD, legacy_ids=[legacy.id]), apply=True, db=db_session)
    (backup,) = _backups(tmp_path)
    out = R.main(backup, apply=True, db=db_session)
    assert {r["template_id"]: r["action"] for r in out["templates"]}[str(legacy.id)] == "skipped-not-deleted"
    db_session.expire_all()
    assert db_session.get(Template, legacy.id).is_active is False


def test_failed_snapshot_leaves_the_converted_sheet(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, legacy, backup = _converted(db_session, templates, tmp_path)
    monkeypatch.setattr(R.crud, "create_template_version", lambda db, t, skip_if_unchanged=False: None)
    out = R.main(backup, apply=True, db=db_session)
    row = {r["template_id"]: r for r in out["templates"]}[str(guided.id)]
    assert (row["action"], row.get("reason")) == ("error", "snapshot failed")
    db_session.expire_all()
    assert db_session.get(Template, guided.id).template_config["skill_sheet"] == GOOD


def test_chat_turns_come_back_with_a_reactivated_template(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    db_session.add(TemplateChatTurn(id=uuid.uuid4(), template_id=legacy.id, instruction="make it shorter"))
    db_session.commit()
    _, _, backup = _converted(db_session, (guided, legacy), tmp_path)
    assert db_session.query(TemplateChatTurn).filter(TemplateChatTurn.template_id == legacy.id).count() == 0
    R.main(backup, apply=True, db=db_session)
    assert db_session.query(TemplateChatTurn).filter(TemplateChatTurn.template_id == legacy.id).count() == 1
