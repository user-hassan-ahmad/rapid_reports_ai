"""Spec §10.2, §12.6 (Plan 3 fix batch): the rail chat thread persists in `report_chat_messages`.

A successful chat turn saves the user message and the assistant reply (prose + verified/failed edits) and returns
their ids. `GET /api/reports/{id}/chat` returns the thread in order; `POST .../chat/{message_id}/applied` records
Apply / Undo of one edit in `applied_item_ids` (and keeps the apply detail on the edit, so Undo works after a
reload). Both are owner-scoped. A failed turn saves nothing."""
import json
import uuid

from rapid_reports_ai.database.models import ReportChatMessage
from tests.test_chat_edits import BAD_NUMBER, GOOD, _FakeGroq, _reply, _tool_call, chat_env  # noqa: F401
from tests.test_review_engine_api import _other_headers


def _turn(client, auth_headers, report_id, message="add the septation"):
    _FakeGroq.reply = _reply("Added the septation.", [_tool_call({
        "actions": [{"title": "Add septation", "details": "Add the thin septation."}],
        "edits_json": json.dumps([GOOD, BAD_NUMBER]),
    })])
    return client.post(f"/api/reports/{report_id}/chat", json={"message": message}, headers=auth_headers).json()


def test_a_turn_saves_both_messages_and_returns_their_ids(client, auth_headers, chat_env, db_session):
    body = _turn(client, auth_headers, chat_env)
    assert body["success"] is True
    rows = db_session.query(ReportChatMessage).filter_by(report_id=uuid.UUID(chat_env)).all()
    by_id = {str(r.id): r for r in rows}
    assert set(by_id) == {body["user_message_id"], body["message_id"]}
    user, assistant = by_id[body["user_message_id"]], by_id[body["message_id"]]
    assert (user.role, user.content) == ("user", "add the septation")
    assert assistant.role == "assistant" and assistant.content == body["response"]
    assert assistant.edits == body["edits"] and assistant.edits[1]["verified"] is False
    assert assistant.applied_item_ids == []


def test_get_thread_in_order(client, auth_headers, chat_env):
    first = _turn(client, auth_headers, chat_env, "one")
    _FakeGroq.reply = _reply("Bosniak II.")
    second = client.post(f"/api/reports/{chat_env}/chat", json={"message": "two"}, headers=auth_headers).json()
    body = client.get(f"/api/reports/{chat_env}/chat", headers=auth_headers).json()
    assert body["success"] is True
    msgs = body["messages"]
    assert [m["id"] for m in msgs] == [first["user_message_id"], first["message_id"],
                                        second["user_message_id"], second["message_id"]]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[1]["edits"][0]["verified"] is True and msgs[3]["edits"] == []
    assert msgs[1]["applied_item_ids"] == []


def test_a_failed_turn_saves_nothing(client, auth_headers, chat_env, db_session, monkeypatch):
    from rapid_reports_ai import main
    monkeypatch.setattr(main, "get_system_api_key", lambda *a, **k: None)
    body = client.post(f"/api/reports/{chat_env}/chat", json={"message": "m"}, headers=auth_headers).json()
    assert body["success"] is False
    assert db_session.query(ReportChatMessage).count() == 0


def test_applied_then_undone(client, auth_headers, chat_env):
    turn = _turn(client, auth_headers, chat_env)
    mid = turn["message_id"]
    item_id = f"chat:{mid}:0"
    detail = {"from": 30, "insert": GOOD["replace"], "removed": GOOD["find"], "left": "normal. ", "right": "\n"}
    r = client.post(f"/api/reports/{chat_env}/chat/{mid}/applied",
                    json={"edit_index": 0, "item_id": item_id, "applied": True, "detail": detail},
                    headers=auth_headers).json()
    assert r == {"success": True, "applied_item_ids": [item_id]}
    msg = client.get(f"/api/reports/{chat_env}/chat", headers=auth_headers).json()["messages"][1]
    assert msg["applied_item_ids"] == [item_id] and msg["edits"][0]["applied_detail"] == detail
    # applying twice keeps one id
    client.post(f"/api/reports/{chat_env}/chat/{mid}/applied",
                json={"edit_index": 0, "item_id": item_id, "applied": True}, headers=auth_headers)
    r = client.post(f"/api/reports/{chat_env}/chat/{mid}/applied",
                    json={"edit_index": 0, "item_id": item_id, "applied": False}, headers=auth_headers).json()
    assert r == {"success": True, "applied_item_ids": []}
    msg = client.get(f"/api/reports/{chat_env}/chat", headers=auth_headers).json()["messages"][1]
    assert msg["applied_item_ids"] == [] and "applied_detail" not in msg["edits"][0]


def test_applied_rejects_bad_targets(client, auth_headers, chat_env):
    turn = _turn(client, auth_headers, chat_env)
    url = f"/api/reports/{chat_env}/chat/{{}}/applied"
    ok = {"edit_index": 0, "item_id": "chat:x:0", "applied": True}
    assert client.post(url.format(turn["message_id"]), json={**ok, "edit_index": 5},
                       headers=auth_headers).status_code == 422
    assert client.post(url.format(turn["user_message_id"]), json=ok, headers=auth_headers).status_code == 422
    missing = client.post(url.format(uuid.uuid4()), json=ok, headers=auth_headers).json()
    assert missing["success"] is False
    assert client.post(url.format("not-a-uuid"), json=ok, headers=auth_headers).json()["success"] is False


def test_owner_scoped(client, auth_headers, chat_env, db_session):
    turn = _turn(client, auth_headers, chat_env)
    other = _other_headers(db_session)
    assert client.get(f"/api/reports/{chat_env}/chat", headers=other).json() == \
        {"success": False, "error": "Report not found"}
    r = client.post(f"/api/reports/{chat_env}/chat/{turn['message_id']}/applied",
                    json={"edit_index": 0, "item_id": "chat:x:0", "applied": True}, headers=other).json()
    assert r["success"] is False
    msg = client.get(f"/api/reports/{chat_env}/chat", headers=auth_headers).json()["messages"][1]
    assert msg["applied_item_ids"] == []


def test_applied_without_position_detail_keeps_no_empty_detail(client, auth_headers, chat_env):
    """A Discard re-apply posts {via: discard} only: no apply detail is stored (the rebuild falls back to the edit)."""
    mid = _turn(client, auth_headers, chat_env)["message_id"]
    client.post(f"/api/reports/{chat_env}/chat/{mid}/applied",
                json={"edit_index": 0, "item_id": f"chat:{mid}:0", "applied": True, "detail": {"via": "discard"}},
                headers=auth_headers)
    msg = client.get(f"/api/reports/{chat_env}/chat", headers=auth_headers).json()["messages"][1]
    assert msg["applied_item_ids"] == [f"chat:{mid}:0"] and "applied_detail" not in msg["edits"][0]
