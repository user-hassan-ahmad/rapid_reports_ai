"""Stored decisions reach the save function on every endpoint that writes a guided template's sheet."""
import pytest

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_save as S
from tests.template_sheet_fixtures import GOOD
from tests.test_template_sheet_save_routes import _get, _guided, _version_with

LINE = 'LIST_MISSING ["Width"]'


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def none(st, sheet=""):
        return []

    async def no_repair(sheet, errors):
        raise AssertionError("repair must not run")
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr(S, "_repair", no_repair)
    monkeypatch.setattr("rapid_reports_ai.template_sheet_structure.store_parsed", lambda tid, st: True)


def _width():
    led, _ = td.set_decision([], "value", "Width", {"need": "every"}, source="creation", at="t")
    return led


def _put(client, auth_headers, t, cfg):
    return client.put(f"/api/templates/{t['id']}", headers=auth_headers,
                      json={"name": t["name"], "template_config": cfg}).json()


def test_update_with_decisions_applies_them_even_when_the_sheet_is_unchanged(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = _put(client, auth_headers, t, {**t["template_config"], "decisions": _width()})
    assert r["success"], r
    cfg = _get(client, auth_headers, t["id"])["template_config"]
    assert LINE in cfg["skill_sheet"] and cfg["decisions"] == _width()


def test_update_without_decisions_keeps_the_stored_ones(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _width()})
    stored = _get(client, auth_headers, t["id"])
    cfg = {k: v for k, v in stored["template_config"].items() if k != "decisions"}
    edited = cfg["skill_sheet"].replace(LINE, 'LIST_MISSING ["Width" | "Depth"]')
    r = _put(client, auth_headers, stored, {**cfg, "skill_sheet": edited})
    assert r["success"], r
    after = _get(client, auth_headers, t["id"])["template_config"]
    # origin "chat": the edit added a value, which the ledger now records
    assert {e["key"] for e in after["decisions"]} == {"Width", "Depth"} and "Depth" in after["skill_sheet"]


def test_restore_applies_the_ledger(client, auth_headers, db_session):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _width()})
    vid = _version_with(db_session, t["id"], GOOD)    # the version holds the decisions but the old sheet
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r["success"], r
    assert LINE in _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"]


def test_creator_save_stores_decisions_and_the_rules_step_record(client, auth_headers, monkeypatch):
    async def store(db, template_id, texts):
        return 0
    monkeypatch.setattr("rapid_reports_ai.template_examples.store_examples", store)
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee", "decisions": _width(),
        "rules_step": {"version": "v", "cards": 3}}).json()
    assert r["success"], r
    cfg = _get(client, auth_headers, r["template_id"])["template_config"]
    assert LINE in cfg["skill_sheet"] and cfg["decisions"] == _width() and cfg["rules_step"] == {"version": "v", "cards": 3}


def test_a_put_without_decisions_keeps_the_ledger_and_the_rules_step_record(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _width(), "rules_step": {"version": "v"}})
    stored = _get(client, auth_headers, t["id"])
    cfg = {k: v for k, v in stored["template_config"].items() if k not in ("decisions", "rules_step")}
    r = _put(client, auth_headers, stored, cfg)                       # same sheet, no ledger fields
    assert r["success"], r
    after = _get(client, auth_headers, t["id"])["template_config"]
    assert after["decisions"] == _width() and after["rules_step"] == {"version": "v"}
