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


def test_analyze_records_the_card_answers_and_passes_them_to_the_writer(client, auth_headers, monkeypatch):
    seen = {}
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def write(examples, scan_type, protocol_notes="", decisions=None):
        seen["decisions"] = decisions
        return {"skill_sheet": GOOD, "summary": {}, "questions": [], "dropped": [], "notice": "",
                "analyser_version": "v", "decisions": decisions or [], "ledger_drift": 0}

    async def test_case(self, examples, scan_type, api_key):
        return {"sample_clinical_history": "", "sample_findings": ""}
    monkeypatch.setattr("rapid_reports_ai.template_writer.write_sheet", write)
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.generate_test_case", test_case)
    r = client.post("/api/templates/skill-sheet/analyze", headers=auth_headers, json={
        "scan_type": "MRI knee", "examples": [{"content": "a"}, {"content": "b"}, {"content": "c"}],
        "changes": [{"kind": "value", "key": "Width", "choice": {"need": "every"}},
                    {"kind": "value", "key": "Depth", "choice": {"need": "every"}, "source": "default"}]}).json()
    assert r["success"], r
    assert [(e["key"], e["source"], e["by"]) for e in seen["decisions"]] == [
        ("Width", "creation", "radiologist"), ("Depth", "default", "code")]
    assert [e["key"] for e in r["decisions"]] == ["Width", "Depth"]


def test_refine_carries_the_ledger_and_names_a_changed_decision(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_ledger_apply as tla
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")
    led = _width()
    before = tla.apply_ledger(GOOD, led).sheet
    after = before.replace(LINE, 'LIST_MISSING ["Depth"]')

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": after, "response": "Done.", "behavioral_claim": "c"}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers, json={
        "skill_sheet": before, "message": "swap width for depth", "decisions": led}).json()
    assert r["success"] and r["applied"] is True and r["skill_sheet"] == after
    assert {(e["key"], e["choice"]["need"]) for e in r["decisions"]} == {("Width", "not_needed"), ("Depth", "every")}
    assert r["response"] == ("Done. This changes something you confirmed: Width every report → not needed.")


def test_refine_without_decisions_returns_none(client, auth_headers, monkeypatch):
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": GOOD, "response": "Nothing to change?", "behavioral_claim": ""}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers,
                    json={"skill_sheet": GOOD, "message": "m"}).json()
    assert r["success"] and "decisions" not in r



def test_refine_that_drops_a_whole_decided_list_keeps_it_and_returns_the_card(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_ledger_apply as tla
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")
    led = _width()
    before = tla.apply_ledger(GOOD, led).sheet
    after = "\n".join(ln for ln in before.split("\n") if "LIST_MISSING" not in ln)

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": after, "response": "Done.", "behavioral_claim": "c"}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers, json={
        "skill_sheet": before, "message": "remove the values", "decisions": led}).json()
    assert r["success"] and LINE in r["skill_sheet"] and r["decisions"] == led
    assert [c["id"] for c in r["cards"]] == ["value:width"] and r["response"].endswith(S.LEDGER_KEPT)
