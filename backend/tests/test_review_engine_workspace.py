"""Review rail workspace state (spec §10.2, plan Task E1): `reports.workspace_state` holds the rail tab, expanded
items, density and the last text_hash. GET/PUT are owner-scoped like the other review endpoints; the PUT validates
the shape and caps the size."""
import uuid

import pytest

from rapid_reports_ai.database.models import Report, User

STATE = {"tab": "review", "expanded_ids": ["a1", "b2"], "density": "quiet", "last_text_hash": "47597f087ff5d076"}


@pytest.fixture
def rid(db_session, test_user):
    r = Report(report_type="quick", model_used="m", report_content="FINDINGS:\nx", user_id=test_user.id)
    db_session.add(r)
    db_session.commit()
    return str(r.id)


def _other_headers(db_session):
    from rapid_reports_ai.auth import create_access_token
    other = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="O", is_active=True,
                 is_verified=True, is_approved=True)
    db_session.add(other)
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': str(other.id)})}"}


def test_report_maps_workspace_state(db_session, rid):
    r = db_session.get(Report, uuid.UUID(rid))
    assert r.workspace_state is None
    r.workspace_state = STATE
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Report, uuid.UUID(rid)).workspace_state == STATE


def test_get_empty_workspace(client, auth_headers, rid):
    body = client.get(f"/api/reports/{rid}/workspace", headers=auth_headers).json()
    assert body == {"success": True, "workspace": None}


def test_put_then_get_round_trip(client, auth_headers, rid):
    body = client.put(f"/api/reports/{rid}/workspace", json=STATE, headers=auth_headers).json()
    assert body == {"success": True, "workspace": STATE}
    got = client.get(f"/api/reports/{rid}/workspace", headers=auth_headers).json()
    assert got == {"success": True, "workspace": STATE}


def test_put_defaults_and_nullable_hash(client, auth_headers, rid):
    body = client.put(f"/api/reports/{rid}/workspace", json={"tab": "guidelines"}, headers=auth_headers).json()
    assert body["workspace"] == {"tab": "guidelines", "expanded_ids": [], "density": "quiet", "last_text_hash": None}


@pytest.mark.parametrize("bad", [
    {"tab": "Review Tab!"},                                   # tab is a short lowercase token
    {"tab": "review", "density": "loud"},                     # density is full / quiet / hidden
    {"tab": "review", "last_text_hash": "xyz"},               # 16 hex chars
    {"tab": "review", "expanded_ids": "a1"},                  # a list
    {"tab": "review", "expanded_ids": ["x" * 65]},            # each id short
    {"tab": "review", "extra": 1},                            # no unknown keys
    {"expanded_ids": []},                                     # tab required
])
def test_put_rejects_bad_shape(client, auth_headers, rid, bad):
    res = client.put(f"/api/reports/{rid}/workspace", json=bad, headers=auth_headers)
    assert res.status_code == 422
    assert client.get(f"/api/reports/{rid}/workspace", headers=auth_headers).json()["workspace"] is None


def test_put_caps_expanded_ids(client, auth_headers, rid):
    res = client.put(f"/api/reports/{rid}/workspace", json={"tab": "review", "expanded_ids": [str(i) for i in range(201)]},
                     headers=auth_headers)
    assert res.status_code == 422


def test_workspace_owner_scoped(client, db_session, rid):
    h = _other_headers(db_session)
    assert client.get(f"/api/reports/{rid}/workspace", headers=h).json() == {"success": False,
                                                                            "error": "Report not found"}
    assert client.put(f"/api/reports/{rid}/workspace", json=STATE, headers=h).json()["success"] is False
    assert db_session.get(Report, uuid.UUID(rid)).workspace_state is None


def test_workspace_unknown_report(client, auth_headers):
    body = client.get(f"/api/reports/{uuid.uuid4()}/workspace", headers=auth_headers).json()
    assert body["success"] is False
