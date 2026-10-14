"""Route tests for POST /api/dictation/check.

Uses the shared SQLite TestClient harness from conftest.py. conftest provides
no auth fixture and no prior test authenticates a protected route, so the
authed_client fixture below is defined locally. It overrides the
get_current_user dependency rather than minting a JWT — the route's behaviour
under test is the integrity check, not token validation.
"""
from __future__ import annotations

import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app


@pytest.fixture
def authed_client(client, db_session):
    """TestClient whose requests resolve to a real persisted user."""
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@nhs.net",
        password_hash="x",
        full_name="Test Radiologist",
        is_active=True,
        is_verified=True,
        is_approved=True,
    )
    db_session.add(user)
    db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_clean_dictation_reports_ok(authed_client):
    r = authed_client.post(
        "/api/dictation/check",
        json={"findings": "- lungs clear\n- no effusion"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["flags"] == []
    assert body["should_gate"] is False


def test_truncated_dictation_reports_a_gating_flag(authed_client):
    r = authed_client.post(
        "/api/dictation/check",
        json={"findings": "There is a new destructive osseous lesion in the"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert len(body["flags"]) == 1
    assert body["flags"][0]["kind"] == "truncation"
    assert body["flags"][0]["message"]
    assert body["should_gate"] is True


def test_empty_findings_is_clean(authed_client):
    r = authed_client.post("/api/dictation/check", json={"findings": ""})
    assert r.status_code == 200
    assert r.json()["flags"] == []


def test_route_requires_authentication(client):
    """Plain `client` — no dependency override, so real JWT validation runs."""
    r = client.post("/api/dictation/check", json={"findings": "anything"})
    assert r.status_code == 401


# --- Tier 2 (semantic) opt-in -----------------------------------------------


def test_semantic_is_off_by_default(authed_client, monkeypatch):
    """The idle path must never spend a model call."""
    called = []
    import rapid_reports_ai.dictation_semantic as ds
    async def _fake_check(*a, **k):
        called.append(1)
        return []

    monkeypatch.setattr(ds, "check_semantic", _fake_check)

    r = authed_client.post(
        "/api/dictation/check", json={"findings": "- lungs are clear."}
    )
    assert r.status_code == 200
    assert called == []


def test_semantic_skipped_when_tier1_already_flagged(authed_client, monkeypatch):
    """A truncated dictation is already gated — don't also pay for tier 2."""
    called = []
    import rapid_reports_ai.dictation_semantic as ds
    async def _fake_check(*a, **k):
        called.append(1)
        return []

    monkeypatch.setattr(ds, "check_semantic", _fake_check)

    r = authed_client.post(
        "/api/dictation/check",
        json={
            "findings": "- There is a lesion in the",
            "include_semantic": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["flags"][0]["kind"] == "truncation"
    assert called == []


def test_semantic_flags_do_not_gate(authed_client, monkeypatch):
    """Model-judged issues advise; they must never block generation."""
    from rapid_reports_ai.dictation_integrity import IntegrityFlag
    import rapid_reports_ai.dictation_semantic as ds

    async def _fake_check(*a, **k):
        return [IntegrityFlag(
            kind="laterality_conflict", severity="medium", excerpt="left ankle",
            message="left vs right", start=0, end=10,
        )]

    monkeypatch.setattr(ds, "check_semantic", _fake_check)

    r = authed_client.post(
        "/api/dictation/check",
        json={"findings": "left ankle is clear.", "include_semantic": True},
    )
    body = r.json()
    assert body["flags"][0]["kind"] == "laterality_conflict"
    assert body["should_gate"] is False


def test_scratchpad_skips_the_regex_tier_and_always_runs_the_model(authed_client, monkeypatch):
    """Unfinished sentences are Jev's in the scratchpad: no regex truncation flag, and tier 2 still runs."""
    called = []
    import rapid_reports_ai.dictation_semantic as ds
    async def _fake_check(*a, **k):
        called.append(1)
        return []

    monkeypatch.setattr(ds, "check_semantic", _fake_check)
    r = authed_client.post("/api/dictation/check",
                           json={"findings": "- There is a lesion in the", "include_semantic": True, "skip_tier1": True})
    assert r.status_code == 200
    assert r.json()["flags"] == [] and called == [1]


def test_a_library_pick_side_reaches_the_check_and_a_side_conflict_blocks(authed_client, monkeypatch):
    """Library sessions send the picked side in the scan type line; the check gets it, and a side flag holds Confirm."""
    import rapid_reports_ai.dictation_semantic as ds
    from rapid_reports_ai.dictation_semantic import SemanticFindings, SemanticIssue
    seen = {}
    findings = "Right knee. Horizontal tear of the medial meniscus."

    async def _fake_analyse(scan_type, clinical_history, text):
        seen.update(scan_type=scan_type, history=clinical_history)
        return SemanticFindings(issues=[SemanticIssue(kind="laterality_conflict", quote="Right knee.",
                                                      message="Left knee picked, right knee dictated: which is it?")])

    monkeypatch.setattr(ds, "_default_analyse", _fake_analyse)
    r = authed_client.post("/api/dictation/check", json={
        "findings": findings, "include_semantic": True, "skip_tier1": True,
        "scan_type": "MRI Knee (left)", "clinical_history": "Medial joint line pain."})
    [flag] = r.json()["flags"]
    assert seen == {"scan_type": "MRI Knee (left)", "history": "Medial joint line pain."}
    assert flag["kind"] == "laterality_conflict" and flag["blocking"] is True
    assert findings[flag["start"]:flag["end"]] == "Right knee."
