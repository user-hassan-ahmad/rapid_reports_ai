"""Generate reads the session resolution token (D26), never re-resolves from the request."""
from pathlib import Path

from rapid_reports_ai.hybrid_stack import resolution as RS
from tests.test_stack_generate_endpoint import _body, _events, authed, fakes, user  # noqa: F401

FIX = Path(__file__).parent / "fixtures" / "protocol_bundle_fixture.json"


def test_quick_generate_reads_the_sheet_from_the_token(authed, fakes, monkeypatch):
    from rapid_reports_ai.hybrid_stack import report as SR
    monkeypatch.setattr(SR, "_slim_markdown", lambda db, sid: f"SHEET:{sid}")
    key = RS.mint({"src": "free", "scan": "CT abdomen", "sk": "k", "sid": "s-1"})
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(structure_key=key)))
    assert events[0][0] == "candidate" and fakes["quick"]["stack_sheet"] == "SHEET:s-1"


def test_quick_generate_stamps_the_token(authed, db_session, fakes):
    import uuid
    from rapid_reports_ai.database.models import Report
    key = RS.mint({"src": "free", "scan": "CT abdomen", "sk": "k", "sid": None})
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(structure_key=key)))
    row = db_session.get(Report, uuid.UUID(events[1][1]["report_id"]))
    assert row.generation_stamp == {"path": "stack", "structure_key": key}


def test_generate_template_changed_mid_session(authed, db_session, user, fakes):
    from rapid_reports_ai.database.models import Template
    t = Template(name="T", template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": "## FINDINGS\nnew"},
                 user_id=user.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    key = RS.mint({"src": "template", "tid": str(t.id), "sh": "old-hash"})
    events = _events(authed.post("/api/canvas/stack/generate",
                                 json=_body(kind="template", template_id=str(t.id), structure_key=key)))
    assert events == [("error", {"message": "The template changed. Set up the workspace again."})]


def test_template_token_for_another_user_refused(authed, db_session, fakes):
    import uuid
    from rapid_reports_ai.database.models import Template, User
    other = User(id=uuid.uuid4(), email="o@nhs.net", password_hash="x", full_name="O",
                 is_active=True, is_verified=True, is_approved=True)
    db_session.add(other)
    t = Template(name="T", template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": "x"},
                 user_id=other.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    key = RS.mint({"src": "template", "tid": str(t.id), "sh": "h"})
    events = _events(authed.post("/api/canvas/stack/generate",
                                 json=_body(kind="template", template_id=str(t.id), structure_key=key)))
    assert events == [("error", {"message": "Template not found."})]


def test_token_for_another_template_or_kind_refused(authed, db_session, user, fakes):
    import uuid
    tpl = RS.mint({"src": "template", "tid": str(uuid.uuid4()), "sh": "h"})
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(structure_key=tpl)))   # quick + template key
    assert events == [("error", {"message": "Set up the workspace again."})]
    events = _events(authed.post("/api/canvas/stack/generate",
                                 json=_body(kind="template", template_id=str(uuid.uuid4()), structure_key=tpl)))
    assert events == [("error", {"message": "Set up the workspace again."})]


def test_library_update_mid_session_stops_generate(authed, fakes, monkeypatch):
    from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB
    monkeypatch.setenv("RR_PROTOCOL_LIBRARY", "1")
    monkeypatch.setenv("RR_PROTOCOL_LIBRARY_PATH", str(FIX))
    PB.reset_cache()
    try:
        key = RS.mint({"src": "library", "eid": "TCAPT", "ph": [], "lat": None, "bv": "old", "sid": "lib:x"})
        events = _events(authed.post("/api/canvas/stack/generate", json=_body(structure_key=key)))
    finally:
        PB.reset_cache()
    assert events == [("error", {"message": "The protocol library was updated. Set up the workspace again."})]
    assert "quick" not in fakes


def test_forged_key_is_an_error_event(authed, fakes):
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(structure_key="x.y")))
    assert events == [("error", {"message": "Set up the workspace again."})]
