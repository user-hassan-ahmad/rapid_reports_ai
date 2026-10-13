import json

import pytest

from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database.models import Template, TemplateVersion
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


def _manifest(tmp_path, tid, new_sheet, old_hash=None):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps([{"template_id": str(tid), "old_sheet_hash": old_hash or tss.sheet_hash(OLD),
                              "new_sheet": new_sheet}]))
    return p


def _backups(tmp_path):
    return list(tmp_path.glob("template_upgrade_backup_*.json"))


def _actions(summary):
    return {r["template_id"]: r["action"] for r in summary["templates"]}


def test_apply_writes_vetted_sheet_snapshots_old_and_soft_deletes_legacy(db_session, templates, tmp_path, no_jev):
    guided, legacy = templates
    summary = U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    assert _actions(summary) == {str(guided.id): "written", str(legacy.id): "soft-deleted"}
    db_session.expire_all()
    cfg = db_session.get(Template, guided.id).template_config
    assert cfg["skill_sheet"] == GOOD and cfg["generation_mode"] == "skill_sheet_guided"
    assert cfg["coverage_sections"] == ["FINDINGS", "IMPRESSION"] and cfg["analyser_version"] == "old-v1"
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
    summary = U.main(_manifest(tmp_path, guided.id, GOOD), db=db_session)
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
