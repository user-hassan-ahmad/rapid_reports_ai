"""/stack/schema mints the session resolution token; /stack/slim-sheet reads it, never the request (D26, §8.1)."""
import uuid
from pathlib import Path

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import Template, User
from rapid_reports_ai.hybrid_stack import resolution as RS
from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB
from rapid_reports_ai.main import app

FIX = Path(__file__).parent / "fixtures" / "protocol_bundle_fixture.json"

_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Brain (FINDINGS)
COVERS ["brain"]
NORMAL [ventricles] "Fixture ventricles sentence."
"""


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def authed(client, user, monkeypatch):
    monkeypatch.delenv("RR_STACK", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def lib_env(monkeypatch):
    monkeypatch.setenv("RR_PROTOCOL_LIBRARY", "1")
    monkeypatch.setenv("RR_PROTOCOL_LIBRARY_PATH", str(FIX))
    PB.reset_cache()
    yield
    PB.reset_cache()


def test_schema_mints_a_template_token(authed, db_session, user):
    from rapid_reports_ai.template_sheet_structure import sheet_hash
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": _SHEET}
    t = Template(name="T", user_id=user.id, is_active=True, tags=[], template_config=cfg)
    db_session.add(t)
    db_session.commit()
    r = authed.post("/api/canvas/stack/schema", json={"scan_type": "CT", "template_id": str(t.id)})
    assert r.json()["source"] == "template"
    tok = RS.verify(r.json()["structure_key"])
    assert tok == {"v": 1, "src": "template", "tid": str(t.id), "sh": sheet_hash(cfg["skill_sheet"])}


def test_slim_sheet_reads_a_template_token(authed, db_session, user):
    t = Template(name="T", user_id=user.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _SHEET})
    db_session.add(t)
    db_session.commit()
    key = authed.post("/api/canvas/stack/schema", json={"template_id": str(t.id)}).json()["structure_key"]
    s = authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": "MR", "structure_key": key}).json()
    assert s["status"] == "template" and s["region_normals"] == {"Brain": ["Fixture ventricles sentence."]}


def test_schema_mints_a_library_token_and_slim_reads_it(lib_env, authed):
    j = authed.post("/api/canvas/stack/schema", json={"protocol_id": "TCAPT"}).json()
    tok = RS.verify(j["structure_key"])
    b = PB.get_bundle()
    assert tok["src"] == "library" and tok["eid"] == "TCAPT" and tok["bv"] == b.version
    assert tok["sid"].startswith("lib:TCAPT|")
    # the request's pick is ignored when a token is given
    s = authed.post("/api/canvas/stack/slim-sheet", json={"protocol_id": "TMKN", "structure_key": j["structure_key"]})
    assert s.status_code == 200 and s.json()["status"] == "library" and s.json()["id"] == tok["sid"]


def test_slim_sheet_reads_the_token_not_the_request(authed, monkeypatch):
    from rapid_reports_ai.hybrid_stack import routes as R
    seen = {}

    async def fake_resolve(scan, history, structure, db):
        return R.SchemaResult(regions=[R.Region(name="Liver", includes="")], groups=["Liver"], pills=["Liver"],
                              source="generic", key="ct-abdo")

    class Row:
        id, region_normals, not_assessable, status = "s-1", {"Liver": ["Normal."]}, "", "provisional"

    async def fake_slim(db, scan, key, regions):
        seen["scan"], seen["key"] = scan, key
        return Row()

    monkeypatch.setattr(R, "resolve_schema", fake_resolve)
    monkeypatch.setattr(R, "slim_get_or_make", fake_slim)
    key = authed.post("/api/canvas/stack/schema", json={"scan_type": "CT abdomen"}).json()["structure_key"]
    assert RS.verify(key) == {"v": 1, "src": "free", "scan": "CT abdomen", "sk": "ct-abdo", "sid": None}
    r = authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": "MR brain", "structure_key": key}).json()
    assert seen == {"scan": "CT abdomen", "key": "ct-abdo"}
    assert RS.verify(r["structure_key"])["sid"] == "s-1"


def test_slim_sheet_refuses_a_forged_key(authed):
    r = authed.post("/api/canvas/stack/slim-sheet", json={"structure_key": "x.y"})
    assert r.status_code == 400 and r.json()["detail"] == "Set up the workspace again."
