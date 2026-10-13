"""Stored decisions reach the save function on every endpoint that writes a guided template's sheet."""
import pytest

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_rules_cards as trc
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


APPLY = "/api/templates/skill-sheet/apply-decisions"


def test_apply_decisions_records_answers_and_returns_the_applied_sheet(client, auth_headers):
    r = client.post(APPLY, headers=auth_headers, json={
        "skill_sheet": GOOD, "decisions": _width(), "source": "first_use_review",
        "changes": [{"kind": "normal", "key": "Knee :: menisci", "choice": {"text": "The menisci are normal."}}]}).json()
    assert r["success"], r
    assert LINE in r["skill_sheet"] and 'NORMAL [menisci] "The menisci are normal."' in r["skill_sheet"]
    assert [(e["key"], e["source"]) for e in r["decisions"]] == [("Width", "creation"),
                                                                 ("Knee :: menisci", "first_use_review")]
    assert r["unmatched"] == [] and r["stale_quotes"] == []


def test_apply_decisions_refuses_a_change_code_cannot_apply(client, auth_headers):
    r = client.post(APPLY, headers=auth_headers, json={
        "skill_sheet": GOOD, "changes": [{"kind": "normal", "key": "Knee :: menisci",
                                          "choice": {"text": "Measures {size}."}}]}).json()
    assert r["success"] is False and "Couldn't apply" in r["error"]


def test_apply_decisions_refuses_an_unknown_source(client, auth_headers):
    r = client.post(APPLY, headers=auth_headers, json={"skill_sheet": GOOD, "changes": [], "source": "writer"}).json()
    assert r["success"] is False


def test_apply_decisions_records_a_refine_panel_chat_card_as_chat(client, auth_headers):
    r = client.post(APPLY, headers=auth_headers, json={
        "skill_sheet": GOOD, "source": "chat",
        "changes": [{"kind": "value", "key": "Width", "choice": {"need": "every"}}]}).json()
    assert r["success"] and [(e["key"], e["source"]) for e in r["decisions"]] == [("Width", "chat")]


def test_apply_decisions_needs_a_login(client):
    assert client.post(APPLY, json={"skill_sheet": GOOD}).status_code == 401


@pytest.mark.parametrize("body", [
    {"skill_sheet": "x" * 200_001},
    {"skill_sheet": GOOD, "decisions": [{}] * 201},
    {"skill_sheet": GOOD, "changes": [{}] * 201},
])
def test_apply_decisions_caps_its_inputs(client, auth_headers, body):
    assert client.post(APPLY, headers=auth_headers, json=body).status_code == 422


def test_creator_save_caps_the_rules_step_record(client, auth_headers):
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee", "rules_step": {"x": "y" * 50_001}})
    assert r.status_code == 422


# ── Phase 1 carry-over (Phase 3): unmatched entries are stored and become cards; the PUT's kept item is a card ──

MISSING = "A line the sheet lacks."


def _missing_fixed():
    led, _ = td.set_decision(_width(), "fixed", MISSING, {"keep": "always"}, source="creation", at="t")
    return led


def test_a_put_stores_the_unmatched_entries_with_the_template(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = _put(client, auth_headers, t, {**t["template_config"], "decisions": _missing_fixed()})
    assert r["success"], r
    cfg = _get(client, auth_headers, t["id"])["template_config"]
    assert [e["key"] for e in cfg["ledger_unmatched"]] == [MISSING]
    # once the entry is gone from the ledger, nothing is left unmatched
    r = _put(client, auth_headers, t, {**cfg, "decisions": _width()})
    assert r["success"], r
    assert _get(client, auth_headers, t["id"])["template_config"]["ledger_unmatched"] == []


def test_a_client_copy_of_the_unmatched_entries_is_never_stored(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = _put(client, auth_headers, t, {**t["template_config"], "ledger_unmatched": [{"kind": "fixed", "key": "x"}]})
    assert r["success"], r
    assert "ledger_unmatched" not in _get(client, auth_headers, t["id"])["template_config"]


def test_a_put_that_drops_a_whole_decided_list_keeps_it_and_returns_the_card(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _width()})
    stored = _get(client, auth_headers, t["id"])
    cfg = stored["template_config"]
    dropped = "\n".join(ln for ln in cfg["skill_sheet"].split("\n") if "LIST_MISSING" not in ln)
    r = _put(client, auth_headers, stored, {**cfg, "skill_sheet": dropped})
    assert r["success"], r
    assert [c["id"] for c in r["cards"]] == ["value:width"] and r["notice"].endswith(S.LEDGER_KEPT)
    assert LINE in _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"]


def test_decide_shows_a_saved_templates_unmatched_entries_as_cards(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    _put(client, auth_headers, t, {**t["template_config"], "decisions": _missing_fixed()})
    r = client.post("/api/templates/skill-sheet/decide", headers=auth_headers, json={"template_id": t["id"]}).json()
    assert r["success"] and r["ran"] is False
    fixed = [c for c in r["cards"] if c["ledger_kind"] == "fixed"]
    assert [c["key"] for c in fixed] == [MISSING] and fixed[0]["step"] == "review" and fixed[0]["note"]
    assert [c["id"] for c in r["cards"] if c["kind"] == "value"] == ["value:width"]


SHEET_CHECKS = "/api/templates/skill-sheet/sheet-checks"


def test_sheet_checks_returns_the_style_step_cards(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_sheet_review as V
    from tests.template_sheet_fixtures import LEDGER_SHEET

    async def scores(texts, transport=None):
        return [0.9 for _ in texts]
    monkeypatch.setattr(V, "_jev_scores", scores)
    r = client.post(SHEET_CHECKS, headers=auth_headers, json={"skill_sheet": LEDGER_SHEET, "decisions": []}).json()
    assert r["success"] and r["errors"] == [] and r["duplicate_cards"] == []      # nothing decided yet
    assert [c["key"] for c in r["fixed_cards"]] == ["Axial images were acquired.", "No previous imaging available."]
    assert r["normal_report"][0]["sentences"][0]["text"] == "The liver is normal in size."
    assert [c["key"] for c in r["uncovered_cards"]] == ["Liver :: gallbladder"]


def test_sheet_checks_leave_out_a_structure_already_answered(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_sheet_review as V
    from tests.template_sheet_fixtures import LEDGER_SHEET

    async def scores(texts, transport=None):
        return [0.1 for _ in texts]
    monkeypatch.setattr(V, "_jev_scores", scores)
    led, _ = td.set_decision([], "normal", "Liver :: gallbladder", {"text": ""}, source="creation", at="t")
    r = client.post(SHEET_CHECKS, headers=auth_headers, json={"skill_sheet": LEDGER_SHEET, "decisions": led}).json()
    assert r["success"] and r["uncovered_cards"] == []      # "Leave unmentioned" stays answered


def test_sheet_checks_never_fails_the_request(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_sheet_review as V

    async def boom(sheet, ledger, transport=None):
        raise RuntimeError("x")
    monkeypatch.setattr(V, "sheet_checks", boom)
    r = client.post(SHEET_CHECKS, headers=auth_headers, json={"skill_sheet": "x"}).json()
    assert r["success"] and r["errors"] == ["all"] and r["fixed_cards"] == [] and r["duplicate_cards"] == []


def test_sheet_checks_need_a_login_and_cap_their_inputs(client, auth_headers):
    assert client.post(SHEET_CHECKS, json={"skill_sheet": "x"}).status_code in (401, 403)
    r = client.post(SHEET_CHECKS, headers=auth_headers, json={"skill_sheet": "x" * 200_001})
    assert r.status_code == 422


FRAGMENT = {"kind": "concept", "key": "comparison",
            "choice": {"use": True, "default": "No prior.", "when_met": "compared with prior {date}",
                       "condition": "the dictation names a previous imaging study for comparison"}}


def test_analyze_refuses_a_card_answer_code_cannot_apply(client, auth_headers, monkeypatch):
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def write(*a, **k):
        raise AssertionError("the writer must not run")
    monkeypatch.setattr("rapid_reports_ai.template_writer.write_sheet", write)
    r = client.post("/api/templates/skill-sheet/analyze", headers=auth_headers, json={
        "scan_type": "MRI knee", "examples": [{"content": "a"}, {"content": "b"}, {"content": "c"}],
        "changes": [FRAGMENT]}).json()
    assert r["success"] is False and "comparison" in r["error"]


def test_refine_that_breaks_a_decided_wording_keeps_it_and_returns_the_card(client, auth_headers, monkeypatch):
    from rapid_reports_ai import template_ledger_apply as tla
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")
    led, _ = td.set_decision([], "concept", "comparison", {
        "use": True, "default": "No previous imaging available.", "when_met": "Compared with the previous {date}.",
        "condition": "the dictation names a previous imaging study for comparison"}, source="creation", at="t")
    before = tla.apply_ledger(GOOD, led).sheet
    after = before.replace("Compared with the previous {date}.", "compared with the prior study")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": after, "response": "Done.", "behavioral_claim": "c"}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers, json={
        "skill_sheet": before, "message": "shorten it", "decisions": led}).json()
    assert r["success"] and r["applied"] is False and r["skill_sheet"] == before and r["decisions"] == led
    assert [c["id"] for c in r["cards"]] == ["concept:comparison"] and S.LEDGER_INVALID in r["response"]


@pytest.mark.parametrize("url,body", [
    ("/api/templates/skill-sheet/analyze", {"scan_type": "x", "examples": [{"content": "a"}], "changes": [{}] * 201}),
    ("/api/templates/skill-sheet/refine", {"skill_sheet": "s", "message": "m", "decisions": [{}] * 201}),
    ("/api/templates/skill-sheet/save", {"skill_sheet": "s", "scan_type": "x", "template_name": "n",
                                         "decisions": [{}] * 201}),
])
def test_ledger_lists_are_capped_everywhere(client, auth_headers, url, body):
    assert client.post(url, headers=auth_headers, json=body).status_code == 422


def test_decide_asks_about_a_habit_line_nobody_confirmed(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    cfg = t["template_config"]
    line = 'NEGATIVE "No meniscal extrusion." WHEN [findings: a meniscal tear is reported]'
    r = _put(client, auth_headers, t, {**cfg, "skill_sheet": cfg["skill_sheet"].rstrip("\n") + "\n" + line + "\n"})
    assert r["success"], r
    assert line in _get(client, auth_headers, t["id"])["template_config"]["skill_sheet"]   # kept, not stripped
    d = client.post("/api/templates/skill-sheet/decide", headers=auth_headers, json={"template_id": t["id"]}).json()
    (c,) = [c for c in d["cards"] if c["kind"] == "habit"]
    assert c["key"] == "Knee :: a meniscal tear is reported" and c["note"] == trc.PENDING_HABIT_NOTE
    assert c["selected"] is None and [x["id"] for x in c["choices"]] == ["state", "removed", "edit"]
