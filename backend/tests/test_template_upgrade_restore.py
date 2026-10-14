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
