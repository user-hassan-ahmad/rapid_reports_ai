"""Every endpoint that stores a guided template's sheet goes through template_sheet_save.vet_sheet (template pipeline
spec, block 2): create, update (the refine panel), the creator's /skill-sheet/save and version restore."""
import uuid

import pytest

from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import Template
from tests.template_sheet_fixtures import GOOD

FREE = "# Free-form\nProse only."
EDITED = GOOD + 'NORMAL [ligaments] "The cruciate ligaments are intact."\n'


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def none(st, sheet=""):
        return []

    async def no_repair(sheet, errors):
        raise AssertionError("repair must not run")

    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr(S, "_repair", no_repair)
    monkeypatch.setattr("rapid_reports_ai.template_sheet_structure.store_parsed", lambda tid, st: True)


def _guided(client, auth_headers, sheet=GOOD):
    return client.post("/api/templates", headers=auth_headers, json={
        "name": "Knee", "template_config": {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet,
                                            "scan_type": "MRI knee"}}).json()


def _get(client, auth_headers, tid):
    return client.get(f"/api/templates/{tid}", headers=auth_headers).json()["template"]


def test_create_saves_a_grammar_sheet_with_derived_coverage(client, auth_headers):
    r = _guided(client, auth_headers)
    assert r["success"] and r["template"]["template_config"]["coverage_sections"] == ["FINDINGS", "IMPRESSION"]


def test_create_refuses_a_free_form_guided_sheet(client, auth_headers):
    r = _guided(client, auth_headers, sheet=FREE)
    assert r["success"] is False and "structure" in r["error"]


def test_create_of_a_non_guided_template_is_not_vetted(client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("vetted a non-guided template")
    monkeypatch.setattr(S, "vet_sheet", boom)
    r = client.post("/api/templates", headers=auth_headers, json={
        "name": "Legacy", "template_config": {"generation_mode": "legacy", "sections": []}}).json()
    assert r["success"]


def test_update_refuses_a_revert_to_free_form(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {**t["template_config"], "skill_sheet": FREE}}).json()
    assert r["success"] is False and "structure" in r["error"]
    assert _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"] == GOOD


def test_update_without_a_sheet_change_skips_vetting(client, auth_headers, monkeypatch):
    t = _guided(client, auth_headers)["template"]

    async def boom(*a, **k):
        raise AssertionError("vetted an unchanged sheet")
    monkeypatch.setattr(S, "vet_sheet", boom)
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"name": "Knee 2"}).json()
    assert r["success"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": t["template_config"]}).json()
    assert r["success"]


def test_update_saves_a_changed_sheet_with_coverage_and_origin_chat(client, auth_headers, monkeypatch):
    t = _guided(client, auth_headers)["template"]
    seen = {}
    real = S.vet_sheet

    async def spy(sheet, origin, previous=""):
        seen.update(origin=origin, previous=previous)
        return await real(sheet, origin, previous)
    monkeypatch.setattr(S, "vet_sheet", spy)
    stale = {**t["template_config"], "skill_sheet": EDITED, "coverage_sections": ["STALE"]}
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"template_config": stale}).json()
    assert r["success"] and "notice" not in r
    assert seen == {"origin": "chat", "previous": GOOD}
    cfg = _get(client, auth_headers, t["id"])["template_config"]
    assert cfg["skill_sheet"] == EDITED and cfg["coverage_sections"] == ["FINDINGS", "IMPRESSION"]


def test_update_returns_the_adjustment_notice(client, auth_headers, monkeypatch):
    t = _guided(client, auth_headers)["template"]

    async def adjusted(sheet, origin, previous=""):
        return S.VetOutcome("saved", sheet, message=S.ADJUSTED, coverage_sections=["FINDINGS", "IMPRESSION"])
    monkeypatch.setattr(S, "vet_sheet", adjusted)
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {**t["template_config"], "skill_sheet": EDITED}}).json()
    assert r["success"] and r["notice"] == S.ADJUSTED


def test_skill_sheet_save_vets_and_derives_coverage(client, auth_headers):
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee"}).json()
    assert r["success"]
    cfg = _get(client, auth_headers, r["template_id"])["template_config"]
    assert cfg["coverage_sections"] == ["FINDINGS", "IMPRESSION"] and cfg["skill_sheet"] == GOOD


def test_skill_sheet_save_refuses_a_free_form_sheet(client, auth_headers):
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": FREE, "scan_type": "MRI knee", "template_name": "Knee"}).json()
    assert r["success"] is False and "structure" in r["error"]


def test_extract_coverage_endpoint_is_gone(client, auth_headers):
    r = client.post("/api/templates/skill-sheet/extract-coverage", headers=auth_headers, json={"skill_sheet": GOOD})
    assert r.status_code in (404, 405)


def _version_with(db_session, tid, sheet):
    """Snapshot the template as a version, then give the snapshot `sheet`."""
    tpl = db_session.query(Template).filter(Template.id == uuid.UUID(tid)).first()
    v = crud.create_template_version(db_session, tpl)
    v.template_config = {**(v.template_config or {}), "skill_sheet": sheet}
    db_session.commit()
    return str(v.id)


def test_restore_refuses_a_pre_upgrade_version(client, auth_headers, db_session):
    t = _guided(client, auth_headers, sheet=EDITED)["template"]
    vid = _version_with(db_session, t["id"], FREE)
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r["success"] is False and "before the template upgrade" in r["error"]
    assert _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"] == EDITED


def test_restore_vets_a_grammar_version_with_origin_restore(client, auth_headers, db_session, monkeypatch):
    t = _guided(client, auth_headers, sheet=EDITED)["template"]
    vid = _version_with(db_session, t["id"], GOOD)
    seen = {}
    real = S.vet_sheet

    async def spy(sheet, origin, previous=""):
        seen.update(origin=origin, previous=previous)
        return await real(sheet, origin, previous)
    monkeypatch.setattr(S, "vet_sheet", spy)
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r["success"], r
    assert seen == {"origin": "restore", "previous": EDITED}
    cfg = _get(client, auth_headers, t["id"])["template_config"]
    assert cfg["skill_sheet"] == GOOD and cfg["coverage_sections"] == ["FINDINGS", "IMPRESSION"]


def test_restore_refusal_leaves_the_template_unchanged(client, auth_headers, db_session, monkeypatch):
    t = _guided(client, auth_headers, sheet=EDITED)["template"]
    vid = _version_with(db_session, t["id"], GOOD)

    async def refuse(sheet, origin, previous=""):
        return S.VetOutcome("refused", previous, S.UNSAFE)
    monkeypatch.setattr(S, "vet_sheet", refuse)
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r == {"success": False, "error": S.UNSAFE}
    assert _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"] == EDITED


def test_create_refuses_an_empty_guided_sheet(client, auth_headers):
    r = _guided(client, auth_headers, sheet="")
    assert r == {"success": False, "error": S.LOST_STRUCTURE}


def test_update_refuses_emptying_the_sheet(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {**t["template_config"], "skill_sheet": ""}}).json()
    assert r == {"success": False, "error": S.LOST_STRUCTURE}
    assert _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"] == GOOD


def test_update_refuses_switching_a_grammar_template_to_another_mode(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {**t["template_config"], "generation_mode": "legacy"}}).json()
    assert r == {"success": False, "error": "This template can't be switched to another mode."}
    assert _get(client, auth_headers, t["id"])["template_config"]["generation_mode"] == "skill_sheet_guided"


def test_update_of_a_non_guided_template_is_not_vetted(client, auth_headers, monkeypatch):
    t = client.post("/api/templates", headers=auth_headers, json={
        "name": "Legacy", "template_config": {"generation_mode": "legacy", "sections": []}}).json()["template"]

    async def boom(*a, **k):
        raise AssertionError("vetted a non-guided template")
    monkeypatch.setattr(S, "vet_sheet", boom)
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {"generation_mode": "legacy", "sections": [{"name": "X"}]}}).json()
    assert r["success"]


def test_restore_of_another_users_version_is_not_found(client, auth_headers, db_session):
    from tests.conftest import _make_template
    from rapid_reports_ai.database.models import User
    other = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="O",
                 is_active=True, is_verified=True, is_approved=True)
    db_session.add(other)
    db_session.commit()
    theirs = _make_template(db_session, other, "Theirs", {"generation_mode": "skill_sheet_guided", "skill_sheet": GOOD})
    vid = _version_with(db_session, str(theirs.id), GOOD)
    mine = _guided(client, auth_headers, sheet=EDITED)["template"]
    for tid in (str(theirs.id), mine["id"]):
        r = client.post(f"/api/templates/{tid}/versions/{vid}/restore", headers=auth_headers).json()
        assert r["success"] is False and "not found" in r["error"]
    assert _get(client, auth_headers, mine["id"])["template_config"]["skill_sheet"] == EDITED


def test_restore_of_the_current_sheet_skips_vetting(client, auth_headers, db_session, monkeypatch):
    t = _guided(client, auth_headers)["template"]
    vid = _version_with(db_session, t["id"], GOOD)

    async def boom(*a, **k):
        raise AssertionError("vetted an unchanged sheet")
    monkeypatch.setattr(S, "vet_sheet", boom)
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r["success"], r
