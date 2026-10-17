"""Stable line IDs on the persisting endpoints (spec 2026-10-15-stable-line-ids-design, "Where rebind runs"): every
path that stores a sheet runs template_sheet_save.persist_sheet; stateless paths never mint; server-written keys are
never taken from a client; the normals confirm endpoint."""
import uuid

import pytest

from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database.models import TemplateVersion
from tests.template_sheet_fixtures import GOOD, LEDGER_SHEET
from tests.test_template_sheet_save_routes import _get, _guided, _version_with

EDITED = GOOD + 'NORMAL [ligaments] "The cruciate ligaments are intact."\n'
CONFIRM = "/api/templates/{}/normal-confirms"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def none(st, sheet=""):
        return []

    async def no_repair(sheet, errors):
        raise AssertionError("repair must not run")
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr(S, "_repair", no_repair)
    monkeypatch.setattr("rapid_reports_ai.template_sheet_structure.store_parsed", lambda tid, st: True)


@pytest.fixture
def persisted(monkeypatch):
    seen = []
    real = S.persist_sheet

    async def spy(config, stored_config, origin, **kw):
        seen.append(origin)
        return await real(config, stored_config, origin, **kw)
    monkeypatch.setattr(S, "persist_sheet", spy)
    return seen


def _uids(sheet, reg):
    return tlr.uids_for(tsg.parse_sheet(sheet).structure, reg)


def test_create_mints_the_registry_and_sheet_rev(client, auth_headers, persisted):
    cfg = _guided(client, auth_headers)["template"]["template_config"]
    assert persisted == ["analyser"] and cfg["sheet_rev"] == 1
    assert set(_uids(GOOD, cfg["line_registry"])) == {"S:FINDINGS", "S:IMPRESSION", "p0", "m0"}


def test_create_ignores_client_server_written_keys(client, auth_headers):
    forged = {"v": 1, "units": {"n_aaaaaa": {"kind": "normal", "identity": {}, "status": "live"}}}
    r = client.post("/api/templates", headers=auth_headers, json={"name": "Knee", "template_config": {
        "generation_mode": "skill_sheet_guided", "skill_sheet": GOOD, "line_registry": forged, "sheet_rev": 41,
        "uncertain": [{"uid": "n_aaaaaa"}], "normal_confirms": {"x": {}}}}).json()
    cfg = r["template"]["template_config"]
    assert "n_aaaaaa" not in cfg["line_registry"]["units"] and cfg["sheet_rev"] == 1
    assert "uncertain" not in cfg and "normal_confirms" not in cfg


def test_skill_sheet_save_persists(client, auth_headers, persisted, db_session):
    from rapid_reports_ai.database.models import Template
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee"}).json()
    cfg = db_session.get(Template, uuid.UUID(r["template_id"])).template_config
    assert persisted == ["analyser"] and cfg["sheet_rev"] == 1 and cfg["line_registry"]["units"]


def test_update_keeps_uids_bumps_sheet_rev_and_ignores_a_client_registry(client, auth_headers, persisted):
    t = _guided(client, auth_headers)["template"]
    reg = t["template_config"]["line_registry"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"template_config": {
        **t["template_config"], "skill_sheet": EDITED, "line_registry": {"v": 1, "units": {}}, "sheet_rev": 99}}).json()
    cfg = r["template"]["template_config"]
    assert persisted == ["analyser", "chat"] and cfg["sheet_rev"] == 2
    assert _uids(EDITED, cfg["line_registry"])["m0"] == _uids(GOOD, reg)["m0"]


def test_an_update_without_a_sheet_change_keeps_sheet_rev(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {**t["template_config"], "sheet_rev": 99}}).json()
    assert r["template"]["template_config"]["sheet_rev"] == 1


def test_restore_of_a_version_without_a_registry_rebinds_against_the_current_one(client, auth_headers, db_session,
                                                                                 persisted):
    t = _guided(client, auth_headers, sheet=EDITED)["template"]
    current = t["template_config"]["line_registry"]
    vid = _version_with(db_session, t["id"], GOOD)
    v = db_session.get(TemplateVersion, uuid.UUID(vid))   # a version saved before line IDs: no registry, no sheet_rev
    v.template_config = {k: x for k, x in v.template_config.items() if k not in ("line_registry", "sheet_rev")}
    db_session.commit()
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r["success"], r
    cfg = _get(client, auth_headers, t["id"])["template_config"]
    assert persisted[-1] == "restore" and cfg["sheet_rev"] == 2
    assert _uids(GOOD, cfg["line_registry"])["m0"] == _uids(EDITED, current)["m0"]
    assert len([u for u in cfg["line_registry"]["units"] if u.startswith("n_")]) == 2   # the removed one is gone


def test_stateless_paths_never_persist_or_mint(client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("a stateless path persisted")
    monkeypatch.setattr(S, "persist_sheet", boom)
    seen = []
    real = S.vet_sheet

    async def spy(sheet, origin, previous="", ledger=None, registry=None):
        seen.append(registry)
        return await real(sheet, origin, previous, ledger)
    monkeypatch.setattr(S, "vet_sheet", spy)
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": EDITED, "response": "Done.", "behavioral_claim": "c"}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers,
                    json={"skill_sheet": GOOD, "message": "add the ligaments"}).json()
    assert r["success"] and "line_registry" not in r
    r = client.post("/api/templates/skill-sheet/apply-decisions", headers=auth_headers, json={
        "skill_sheet": GOOD, "source": "creation",
        "changes": [{"kind": "normal", "key": "Knee :: menisci", "choice": {"text": "The menisci are normal."}}]}).json()
    assert r["success"] and all("uid" not in e for e in r["decisions"])
    assert all(reg is None for reg in seen)

# ── the normals confirm endpoint ──────────────────────────────────────────────────────────────────────────────

def _confirmable(client, auth_headers):
    t = client.post("/api/templates", headers=auth_headers, json={"name": "Liver", "template_config": {
        "generation_mode": "skill_sheet_guided", "skill_sheet": LEDGER_SHEET}}).json()["template"]
    cfg = t["template_config"]
    return t, cfg, _uids(LEDGER_SHEET, cfg["line_registry"])["p1"]


def test_a_confirm_is_computed_server_side_and_records_the_session_user(client, auth_headers, test_user):
    t, cfg, group = _confirmable(client, auth_headers)
    r = client.post(CONFIRM.format(t["id"]), headers=auth_headers, json={
        "group": group, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET),
        "units": {"n_forged": "sha256:x"}, "user_id": "someone-else"})
    assert r.status_code == 200, r.text
    rec = r.json()["confirm"]
    uids = _uids(LEDGER_SHEET, cfg["line_registry"])
    assert set(rec["units"]) == {uids["m0"], uids["n0"]} and rec["user_id"] == str(test_user.id)
    assert rec["units"][uids["m0"]] == cfg["line_registry"]["units"][uids["m0"]]["text_hash"]
    assert _get(client, auth_headers, t["id"])["template_config"]["normal_confirms"] == {group: rec}


@pytest.mark.parametrize("field", ["sheet_rev", "sheet_hash"])
def test_a_confirm_on_a_stale_sheet_is_409(client, auth_headers, field):
    t, cfg, group = _confirmable(client, auth_headers)
    body = {"group": group, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET)}
    body[field] = 0 if field == "sheet_rev" else "f" * 64
    assert client.post(CONFIRM.format(t["id"]), headers=auth_headers, json=body).status_code == 409
    assert "normal_confirms" not in _get(client, auth_headers, t["id"])["template_config"]


def test_a_confirm_for_a_missing_template_is_404_and_an_unknown_group_422(client, auth_headers):
    body = {"group": "p_aaaaaa", "sheet_rev": 1, "sheet_hash": "x"}
    assert client.post(CONFIRM.format(uuid.uuid4()), headers=auth_headers, json=body).status_code == 404
    t, cfg, _ = _confirmable(client, auth_headers)
    body = {**body, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET)}
    assert client.post(CONFIRM.format(t["id"]), headers=auth_headers, json=body).status_code == 422


def test_confirms_survive_a_put_that_sends_its_own_copy(client, auth_headers):
    t, cfg, group = _confirmable(client, auth_headers)
    client.post(CONFIRM.format(t["id"]), headers=auth_headers, json={
        "group": group, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET)})
    stored = _get(client, auth_headers, t["id"])["template_config"]["normal_confirms"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"template_config": {
        **cfg, "normal_confirms": {}}}).json()
    assert r["template"]["template_config"]["normal_confirms"] == stored


def test_a_confirm_on_a_template_saved_before_sheet_rev_compares_against_0(client, auth_headers, db_session):
    from rapid_reports_ai.database.models import Template
    t, cfg, group = _confirmable(client, auth_headers)
    row = db_session.get(Template, uuid.UUID(t["id"]))
    row.template_config = {k: v for k, v in row.template_config.items() if k != "sheet_rev"}
    db_session.commit()
    r = client.post(CONFIRM.format(t["id"]), headers=auth_headers, json={
        "group": group, "sheet_rev": 0, "sheet_hash": tss.sheet_hash(LEDGER_SHEET)})
    assert r.status_code == 200, r.text


def test_a_put_keeps_a_confirm_committed_while_it_was_vetting(client, auth_headers, db_session, monkeypatch):
    from sqlalchemy.orm.attributes import flag_modified
    from rapid_reports_ai import main
    from rapid_reports_ai.database.models import Template
    t, cfg, group = _confirmable(client, auth_headers)
    real = main._vet_config
    rec = {"group": group, "units": {}, "user_id": "u"}

    async def racing(new_cfg, old_cfg, origin, creating=False):   # a confirm commits while the PUT is vetting
        out = await real(new_cfg, old_cfg, origin, creating)
        row = db_session.get(Template, uuid.UUID(t["id"]))
        row.template_config = {**row.template_config, "normal_confirms": {group: rec}, "uncertain": [{"x": 1}]}
        flag_modified(row, "template_config")
        db_session.commit()
        return out
    monkeypatch.setattr(main, "_vet_config", racing)
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"template_config": {
        **cfg, "skill_sheet": LEDGER_SHEET + 'NORMAL [spleen] "The spleen is normal."\n'}}).json()
    assert r["success"], r
    stored = _get(client, auth_headers, t["id"])["template_config"]
    assert stored["normal_confirms"] == {group: rec} and stored["uncertain"] == [{"x": 1}]


def test_another_user_cannot_confirm_a_template_404(client, auth_headers, db_session):
    from tests.test_review_engine_api import _other_headers
    t, cfg, group = _confirmable(client, auth_headers)
    r = client.post(CONFIRM.format(t["id"]), headers=_other_headers(db_session), json={
        "group": group, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET)})
    assert r.status_code == 404
    assert "normal_confirms" not in _get(client, auth_headers, t["id"])["template_config"]
