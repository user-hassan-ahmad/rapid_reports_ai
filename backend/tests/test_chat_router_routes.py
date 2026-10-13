"""The chat-edit router wired into the refine endpoint, its undo and card endpoints, and the routing evidence."""
from rapid_reports_ai import template_chat_turns as T
from rapid_reports_ai.database.models import TemplateChatTurn


def _turns(db_session):
    db_session.expire_all()
    return db_session.query(TemplateChatTurn).all()


def test_record_turn_stores_scrubbed_routing(db_session, guided_template):
    T.record_turn(db_session, guided_template.id, "drop width", "Width is no longer required.", True, "a", "b",
                  routing={"route": "router", "tags": {"value": 0.9}, "note": "seen 01/02/2020"})
    (turn,) = _turns(db_session)
    assert turn.routing["route"] == "router" and turn.routing["tags"] == {"value": 0.9}
    assert "01/02/2020" not in turn.routing["note"]


def test_record_turn_caps_large_routing(db_session, guided_template):
    T.record_turn(db_session, guided_template.id, "x", "y", True, "a", "b",
                  routing={"version": "router-1", "route": "router", "blob": "z" * 30000})
    (turn,) = _turns(db_session)
    assert turn.routing == {"truncated": True, "version": "router-1", "route": "router"}


def test_record_turn_without_routing_stores_none(db_session, guided_template):
    T.record_turn(db_session, guided_template.id, "x", "y", True, "a", "b")
    (turn,) = _turns(db_session)
    assert turn.routing is None


def test_the_router_is_off_in_tests_by_default():
    import os
    assert os.environ.get("RR_CHAT_ROUTER") == "0"


import pytest

from rapid_reports_ai import chat_router as R
from rapid_reports_ai import chat_router_propose as P
from rapid_reports_ai import template_sheet_save as S
from tests.template_sheet_fixtures import ROUTER_SHEET

URL = "/api/templates/skill-sheet/refine"


@pytest.fixture
def router_on(monkeypatch):
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def no_refine(self, *a, **k):
        raise AssertionError("the whole-sheet refine must not run on a routed turn")
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", no_refine)


def _turn(**kw):
    base = dict(sheet=ROUTER_SHEET + "\n", ledger=[{"kind": "value", "key": "Width", "choice": {"need": "not_needed"},
                                                     "by": "radiologist", "at": "t", "source": "chat"}],
                applied=True, reply="Width is no longer required.", claim="Width is no longer required.",
                records=[{"type": "ledger", "change": {"kind": "value", "key": "Width"}}], cards=[],
                evidence={"version": "router-1", "route": "router", "tags": {"value": 0.9}})
    return R.Turn(**{**base, **kw})


def test_a_routed_turn_returns_the_router_response_and_records_its_evidence(client, auth_headers, router_on,
                                                                             monkeypatch, guided_template, db_session):
    seen = {}

    async def route(sheet, ledger, instruction, *, context="", rejection=None, last_changes=None):
        seen.update(sheet=sheet, ledger=ledger, instruction=instruction, context=context, rejection=rejection,
                    last_changes=last_changes)
        return _turn()
    monkeypatch.setattr(P, "propose_turn", route)
    r = client.post(URL, headers=auth_headers, json={
        "skill_sheet": ROUTER_SHEET, "message": "drop width", "decisions": [],
        "chat_history": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "Done before."}],
        "rejection_context": {"original_instruction": "o", "rejected_claim": "c"},
        "last_changes": [{"type": "ledger", "claim": "Depth is no longer required."}],
        "template_id": str(guided_template.id)}).json()
    assert r["route"] == "router" and r["applied"] is True and r["skill_sheet"] == ROUTER_SHEET + "\n"
    assert r["unmatched"] == []
    assert r["decisions"][0]["key"] == "Width" and r["changes"][0]["type"] == "ledger"
    assert r["behavioral_claim"] == "Width is no longer required."
    assert seen["context"] == "Done before." and seen["rejection"] == {"original_instruction": "o", "rejected_claim": "c"}
    assert seen["last_changes"] == [{"type": "ledger", "claim": "Depth is no longer required."}]
    (turn,) = _turns(db_session)
    assert turn.routing["route"] == "router" and turn.applied is True


def test_a_failed_tag_call_falls_back_to_the_whole_sheet_refine(client, auth_headers, monkeypatch, guided_template,
                                                                db_session):
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def route(*a, **k):
        raise R.Fallback("TimeoutError")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": skill_sheet, "response": "Done.", "behavioral_claim": "c"}

    async def vet(sheet, origin, previous="", ledger=None):
        return S.VetOutcome("saved", sheet, "")
    monkeypatch.setattr(P, "propose_turn", route)
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "drop width",
                                                     "template_id": str(guided_template.id)}).json()
    assert r["success"] and "route" not in r and r["response"] == "Done."
    (turn,) = _turns(db_session)
    assert turn.routing == {"version": R.ROUTER_VERSION, "route": "refine", "fallback": "TimeoutError"}


def test_the_kill_switch_and_a_non_grammar_sheet_take_todays_path(client, auth_headers, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def route(*a, **k):
        raise AssertionError("not routed")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": skill_sheet, "response": "Done.", "behavioral_claim": ""}

    async def vet(sheet, origin, previous="", ledger=None):
        return S.VetOutcome("unchanged", previous, "")
    monkeypatch.setattr(P, "propose_turn", route)
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    monkeypatch.setattr(S, "vet_sheet", vet)
    monkeypatch.setenv("RR_CHAT_ROUTER", "0")
    assert client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "m"}).json()["success"]
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    assert client.post(URL, headers=auth_headers, json={"skill_sheet": "## FINDINGS\nfree text",
                                                        "message": "m"}).json()["success"]


def test_undo_endpoint_reverses_signed_records_and_records_the_turn(client, auth_headers, monkeypatch, guided_template,
                                                                    db_session, test_user):
    seen = {}

    async def undo(sheet, ledger, records):
        seen.update(sheet=sheet, ledger=ledger, records=records)
        return _turn(reply="Undone: Width is no longer required.", records=[], evidence={"route": "undo"})
    monkeypatch.setattr(R, "undo_turn", undo)
    records = [{"type": "ledger"}]
    r = client.post(URL + "/undo", headers=auth_headers, json={
        "skill_sheet": ROUTER_SHEET, "decisions": [], "changes": records,
        "changes_sig": R.sign_records(records, str(test_user.id), "HASH"), "result_hash": "HASH"}).json()
    assert r["success"] and r["response"].startswith("Undone") and seen["records"] == records


def test_undo_refuses_tampered_or_unsigned_records(client, auth_headers, monkeypatch, test_user):
    async def undo(*a, **k):
        raise AssertionError("tampered records must not reach undo_turn")
    monkeypatch.setattr(R, "undo_turn", undo)
    sig = R.sign_records([{"type": "ledger", "claim": "a"}], str(test_user.id), "HASH")
    for body in ({"changes": [{"type": "ledger", "claim": "b"}], "changes_sig": sig, "result_hash": "HASH"},
                 {"changes": [{"type": "ledger", "claim": "a"}], "changes_sig": sig, "result_hash": "OTHER"},
                 {"changes": [{"type": "ledger"}]}):
        r = client.post(URL + "/undo", headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, **body}).json()
        assert r["success"] is False and r["error"] == "That change can't be undone here."


def test_undo_with_a_template_uses_the_stored_records_not_the_clients(client, auth_headers, monkeypatch,
                                                                     guided_template, db_session):
    stored = [{"type": "ledger", "change": {"kind": "value", "key": "Width"}, "claim": "Width is no longer required."}]
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def hybrid(*a, **k):
        return _turn(records=stored)
    monkeypatch.setattr(P, "propose_turn", hybrid)
    first = client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "drop width",
                                                         "template_id": str(guided_template.id)}).json()
    assert first["turn_id"] and first["changes_sig"]
    seen = {}

    async def undo(sheet, ledger, records):
        seen["records"] = records
        return _turn(reply="Undone.", records=[], evidence={"route": "undo"})
    monkeypatch.setattr(R, "undo_turn", undo)
    r = client.post(URL + "/undo", headers=auth_headers, json={
        "skill_sheet": ROUTER_SHEET, "changes": [{"type": "ledger", "change": {"kind": "value", "key": "Depth"}}],
        "template_id": str(guided_template.id), "turn_id": first["turn_id"]}).json()
    assert r["success"] and seen["records"] == stored
    turns = _turns(db_session)
    assert any(t.instruction == "[undo] 1 change(s)" and t.routing.get("route") == "undo" for t in turns)


def test_card_endpoint_applies_through_the_router(client, auth_headers, monkeypatch):
    seen = {}

    async def answer(sheet, ledger, a):
        seen["answer"] = a
        return _turn(evidence={"route": "card"})
    monkeypatch.setattr(R, "answer_card", answer)
    r = client.post(URL + "/card", headers=auth_headers, json={
        "skill_sheet": ROUTER_SHEET, "decisions": [],
        "answer": {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}}}).json()
    assert r["success"] and r["decisions"][0]["key"] == "Width"
    assert seen["answer"] == {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}}


def test_undo_and_card_fail_soft(client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(R, "undo_turn", boom)
    monkeypatch.setattr(R, "answer_card", boom)
    assert client.post(URL + "/undo", headers=auth_headers,
                       json={"skill_sheet": "s", "changes": []}).json()["success"] is False
    assert client.post(URL + "/card", headers=auth_headers,
                       json={"skill_sheet": "s", "answer": {}}).json()["success"] is False


def test_any_router_exception_falls_back_to_todays_refine(client, auth_headers, monkeypatch, guided_template,
                                                          db_session):
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def route(*a, **k):
        raise KeyError("a router bug")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": skill_sheet, "response": "Done.", "behavioral_claim": "c"}

    async def vet(sheet, origin, previous="", ledger=None):
        return S.VetOutcome("saved", sheet, "")
    monkeypatch.setattr(P, "propose_turn", route)
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "drop width",
                                                     "template_id": str(guided_template.id)}).json()
    assert r["success"] and r["response"] == "Done." and "route" not in r
    (turn,) = _turns(db_session)
    assert turn.routing["fallback"] == "KeyError" and turn.routing["route"] == "refine"



def test_the_old_tag_then_route_path_is_not_called_by_the_endpoint(client, auth_headers, monkeypatch):
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def old(*a, **k):
        raise AssertionError("route_turn is retired (kept for the lab only)")

    async def hybrid(*a, **k):
        return _turn()
    monkeypatch.setattr(R, "route_turn", old)
    monkeypatch.setattr(P, "propose_turn", hybrid)
    assert client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "m"}).json()["route"] == "router"



def test_scrubbed_records_are_not_stored_and_undo_uses_the_signed_copy(client, auth_headers, monkeypatch,
                                                                        guided_template, db_session):
    dated = [{"type": "edit", "kind": "layout", "claim": "x", "op": {"op": "remove_paragraph", "paragraph": "Lower"},
              "inverse": [{"op": "insert_block", "lines": ["## Paragraph: Lower (FINDINGS)", "Seen on 01/02/2020."],
                           "before_heading": None}]}]
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def hybrid(*a, **k):
        return _turn(records=dated)
    monkeypatch.setattr(P, "propose_turn", hybrid)
    first = client.post(URL, headers=auth_headers, json={"skill_sheet": ROUTER_SHEET, "message": "remove lower",
                                                         "template_id": str(guided_template.id)}).json()
    (turn,) = _turns(db_session)
    assert "records" not in turn.routing and turn.routing["records_scrubbed"] is True
    seen = {}

    async def undo(sheet, ledger, records):
        seen["records"] = records
        return _turn(reply="Undone.", records=[], evidence={"route": "undo"})
    monkeypatch.setattr(R, "undo_turn", undo)
    r = client.post(URL + "/undo", headers=auth_headers, json={
        "skill_sheet": first["skill_sheet"], "changes": first["changes"], "changes_sig": first["changes_sig"],
        "result_hash": first["result_hash"], "template_id": str(guided_template.id), "turn_id": first["turn_id"]}).json()
    assert r["success"] and seen["records"] == dated                 # the exact, unscrubbed client copy
