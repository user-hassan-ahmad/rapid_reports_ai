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
