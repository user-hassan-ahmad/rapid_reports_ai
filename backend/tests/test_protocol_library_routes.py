import uuid
from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB

FIX = Path(__file__).parent / "fixtures" / "protocol_bundle_fixture.json"


@pytest.fixture
def lib_env(monkeypatch):
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)
    monkeypatch.setenv("RR_PROTOCOL_LIBRARY", "1")
    monkeypatch.setenv("RR_PROTOCOL_LIBRARY_PATH", str(FIX))
    PB.reset_cache()
    yield
    PB.reset_cache()


@pytest.fixture
def authed(client, db_session):
    from rapid_reports_ai.auth import get_current_user
    from rapid_reports_ai.database.models import User
    from rapid_reports_ai.main import app
    u = User(id=uuid.uuid4(), email="lib@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: u
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_search_returns_options(lib_env, authed):
    r = authed.post("/api/canvas/stack/protocols/search", json={"q": "ctap"})
    assert r.status_code == 200
    o = r.json()["options"][0]
    assert o["id"] == "TCAP" and o["protocol_line"] == "IV contrast · portal venous"


def test_search_404_when_library_off(lib_env, authed, monkeypatch):
    monkeypatch.setenv("RR_PROTOCOL_LIBRARY", "0")
    assert authed.post("/api/canvas/stack/protocols/search", json={"q": "ctap"}).status_code == 404


def test_schema_library_branch(lib_env, authed):
    r = authed.post("/api/canvas/stack/schema", json={"scan_type": "ignored", "protocol_id": "TMWS"})
    j = r.json()
    assert r.status_code == 200 and j["source"] == "library" and j["key"] == "lib:mr_spine_t|none"
    assert j["quiet"] == ["L4/5", "L5/S1"] and "L4/5" in j["groups"] and "L4/5" not in j["pills"]
    assert j["protocol"]["scan_type_line"] == "MRI Whole spine"


def test_schema_and_slim_reject_bad_pick(lib_env, authed):
    assert authed.post("/api/canvas/stack/schema", json={"protocol_id": "TCAP", "phases": ["delayed"]}).status_code == 422
    assert authed.post("/api/canvas/stack/slim-sheet", json={"protocol_id": "TMKN"}).status_code == 422


def test_slim_sheet_library_branch(lib_env, authed):
    r = authed.post("/api/canvas/stack/slim-sheet", json={"protocol_id": "TCAPT"})
    j = r.json()
    assert j["status"] == "library" and j["ready"] is True and j["id"].startswith("lib:TCAPT|")
    assert j["region_normals"]["Liver"][1] == "No arterially enhancing focal liver lesion."


def test_slim_markdown_lib_uuid_and_garbage(lib_env, db_session):
    from rapid_reports_ai.quick_report_api import _slim_markdown
    from rapid_reports_ai.database.models import StackSlimSheet
    md = _slim_markdown(db_session, "lib:TCAPT|non_contrast+arterial+portal_venous|-|fixture-1")
    assert "- **Imaged volume:** Diaphragm to symphysis." in md
    assert _slim_markdown(db_session, "lib:NOPE|none|-|x") == ""
    row = StackSlimSheet(id=uuid.uuid4(), family="ct head", contrast="none", prompt_version="slim-5",
                         status="provisional", model="m", scan_type="ct head", markdown="## Old sheet",
                         region_normals={}, not_assessable="")
    db_session.add(row)
    db_session.commit()
    assert _slim_markdown(db_session, str(row.id)) == "## Old sheet"


def test_free_text_schema_unchanged_when_no_protocol(lib_env, authed, monkeypatch):
    from rapid_reports_ai.hybrid_stack import routes as R
    from rapid_reports_ai.hybrid_stack.service import SchemaResult

    async def resolve(scan_type, history, structure, db):
        return SchemaResult(regions=[], groups=[], pills=[], source="family", key=scan_type)
    monkeypatch.setattr(R, "resolve_schema", resolve)
    r = authed.post("/api/canvas/stack/schema", json={"scan_type": "ct head"})
    assert r.json()["source"] == "family" and r.json()["protocol"] is None


def test_not_listed_logs_length_and_hash_never_the_text(lib_env, authed, caplog):
    import hashlib
    import logging
    from rapid_reports_ai.hybrid_stack.protocol_library import routes as LR
    lg = logging.getLogger(LR.__name__)
    was, lg.disabled = lg.disabled, False   # an earlier test's logging config can leave this logger disabled
    try:
        caplog.set_level(logging.INFO, logger=LR.__name__)
        q = "MRI orbits Mrs Smith 12/03"
        assert authed.post("/api/canvas/stack/protocols/not-listed", json={"q": q}).status_code == 200
    finally:
        lg.disabled = was
    msgs = [r.getMessage() for r in caplog.records if r.name == LR.__name__]
    assert any(f"len={len(q)}" in m and hashlib.sha256(q.encode()).hexdigest()[:10] in m for m in msgs)
    assert not any("Smith" in m or "orbits" in m for m in caplog.text.splitlines())


_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Brain (FINDINGS)
COVERS ["brain"]
NORMAL [ventricles] "Fixture ventricles sentence."
"""


def test_template_structure_wins_over_the_library_pick(lib_env, authed, db_session):
    """Contract §8.1: template structure first, then the library pick, then free text — in /schema and /slim-sheet."""
    from rapid_reports_ai.database.models import Template, User
    owner = db_session.query(User).filter(User.email == "lib@nhs.net").one()
    t = Template(name="T", user_id=owner.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _SHEET})
    db_session.add(t)
    db_session.commit()
    pick = {"protocol_id": "TMWS", "template_id": str(t.id), "scan_type": "MRI whole spine"}
    j = authed.post("/api/canvas/stack/schema", json=pick).json()
    assert j["source"] == "template" and j["protocol"] is None and "Brain" in [r["name"] for r in j["regions"]]
    s = authed.post("/api/canvas/stack/slim-sheet", json=pick).json()
    assert s["status"] == "template" and s["region_normals"] == {"Brain": ["Fixture ventricles sentence."]}
    # a bad pick is not even read when the template decides
    bad = {**pick, "protocol_id": "TMKN"}
    assert authed.post("/api/canvas/stack/schema", json=bad).status_code == 200
    assert authed.post("/api/canvas/stack/slim-sheet", json=bad).status_code == 200
