"""rr_dictation_v2: the dictation package, allowed by RR_DICTATION_V2 and requested per connection."""
from __future__ import annotations

from rapid_reports_ai.dictation_v2 import PACKAGE, socket_settings, v2_allowed

PROD = {}  # production today: no lab or package env
LAB = {"RR_TRIAGE_DEBUG": "1", "DEEPGRAM_DICTATION": "0", "DEEPGRAM_UK_SPELLING": "1",
       "DEEPGRAM_SPOKEN_FORMAT": "1", "DEEPGRAM_CASE_KEYTERMS": "1", "DEEPGRAM_FINALIZE_GAP_S": "0.9", "RR_TWO_PASS": "1"}


def test_allowed_by_the_kill_switch_or_the_lab():
    assert v2_allowed(PROD) is False
    assert v2_allowed({"RR_DICTATION_V2": "1"}) is True
    assert v2_allowed({"RR_TRIAGE_DEBUG": "1"}) is True


def test_production_without_the_flag_is_unchanged():
    s = socket_settings({}, PROD)
    assert (s.v2, s.dictation, s.uk_spelling, s.spoken_format, s.case_keyterms, s.finalize_gap_s, s.two_pass, s.asr_fields) == \
        (False, True, False, False, False, None, False, False)


def test_a_flagged_client_is_ignored_unless_the_server_allows_it():
    assert socket_settings({"v2": "1"}, PROD).v2 is False


def test_a_flagged_client_on_an_allowing_server_gets_the_whole_package():
    s = socket_settings({"v2": "1"}, {"RR_DICTATION_V2": "1"})
    assert s.v2 is True
    assert (s.dictation, s.uk_spelling, s.spoken_format, s.case_keyterms, s.finalize_gap_s, s.two_pass, s.asr_fields) == \
        (PACKAGE["dictation"], True, True, True, 0.9, True, True)
    assert PACKAGE["dictation"] is False  # Deepgram dictation mode off: "colon" is an organ


def test_other_connections_on_an_allowing_server_stay_as_production():
    s = socket_settings({}, {"RR_DICTATION_V2": "1"})
    assert s.v2 is False and s.two_pass is False and s.dictation is True


def test_the_lab_env_still_drives_the_lab():
    s = socket_settings({}, LAB)
    assert (s.dictation, s.uk_spelling, s.finalize_gap_s, s.two_pass, s.asr_fields) == (False, True, 0.9, True, True)


# --- the package's endpoints and pill choice -------------------------------------------------
import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app


@pytest.fixture
def authed_client(client, db_session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
                is_active=True, is_verified=True, is_approved=True)
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


CALLS = [  # requests each answered by code, no model: they only prove the endpoint is open
    ("/api/canvas/bundle", {"scan_type": "CT", "committed": "", "active": "No effusion.", "open_line": "",
                            "latest_utterance": "Scratch that.", "checklist": []}),
    ("/api/canvas/polish-span", {"scan_type": "CT", "context": "", "span": "No effusion.", "new": "Scratch that."}),
]


@pytest.mark.parametrize("path,body", CALLS)
def test_package_endpoints_are_closed_in_production_without_the_switch(authed_client, monkeypatch, path, body):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.delenv("RR_DICTATION_V2", raising=False)
    assert authed_client.post(path, json=body).status_code == 404


@pytest.mark.parametrize("path,body", CALLS)
def test_package_endpoints_open_with_the_switch(authed_client, monkeypatch, path, body):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    assert authed_client.post(path, json=body).status_code == 200


def test_keyterms_open_with_the_switch(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    async def fake(*a, output_type, **k):
        return output_type(terms=["hypodense"])
    monkeypatch.setattr(cr, "_run_canvas_with_fallback", fake)
    r = authed_client.post("/api/canvas/keyterms", json={"scan_type": f"CT {uuid.uuid4()}", "clinical_history": "", "sections": []})
    assert r.status_code == 200 and r.json()["terms"] == ["hypodense"]


def test_a_package_client_gets_jev_pills_only_where_allowed(authed_client, monkeypatch):
    seen = []

    async def fake_safe(name, request):
        seen.append(name)
        from rapid_reports_ai.section_coverage import CoverageDecision
        return CoverageDecision(name, {"LUNGS": 1.0}, ["LUNGS"], 10)
    monkeypatch.setattr(cr, "_coverage_safe", fake_safe)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    body = {"scratchpad_content": "Lungs clear.", "checklist_sections": ["LUNGS"], "scan_type": "CT",
            "parts": "coverage", "coverage_candidate": "jev"}
    monkeypatch.delenv("RR_DICTATION_V2", raising=False)
    authed_client.post("/api/canvas/review", json=body)
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    authed_client.post("/api/canvas/review", json=body)
    assert seen == ["qwen", "jev"]


def test_the_package_switch_warms_the_jev_connection(monkeypatch):
    from rapid_reports_ai.jev_client import warmup_wanted
    for k in ("RR_TRIAGE_DEBUG", "RR_TRIAGE_SHADOW", "RR_COVERAGE_CANDIDATE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_DICTATION_V2", raising=False)
    assert warmup_wanted() is False
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    assert warmup_wanted() is True


def test_the_status_endpoint_tells_the_browser_whether_the_package_is_allowed(authed_client, monkeypatch):
    # the browser runs the package only when the server allows it, so RR_DICTATION_V2 is a clean
    # kill switch: unset, every browser is back on today's dictation (not a package failing open)
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.delenv("RR_DICTATION_V2", raising=False)
    assert authed_client.get("/api/settings/status").json()["dictation_v2"] is False
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    assert authed_client.get("/api/settings/status").json()["dictation_v2"] is True
