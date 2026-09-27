"""Coverage candidate selection and lab trace on POST /api/canvas/review.
Both candidates and IntelliPrompts are faked; wiring is under test."""
from __future__ import annotations

import json
import logging
import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.jev_questions import QSET_VERSION
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_triage import TriageError
from rapid_reports_ai.main import app
from rapid_reports_ai.section_coverage import CoverageDecision

SECTIONS = ["LUNGS", "PLEURA", "MEDIASTINUM"]
BASE = {
    "scratchpad_content": "- no pleural effusion",
    "checklist_sections": SECTIONS,
    "scan_type": "CT chest",
    "clinical_history": "",
    "mode": "clean",
}


@pytest.fixture
def authed_client(client, db_session):
    user = User(
        id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
        is_active=True, is_verified=True, is_approved=True,
    )
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class FakeJev:
    def __init__(self):
        self.calls = 0
        self.raise_ = False

    async def classify(self, scratchpad, sections, scan_type):
        self.calls += 1
        if self.raise_:
            raise TriageError("boom")
        scores = {"LUNGS": 0.2, "PLEURA": 0.95, "MEDIASTINUM": 0.6}
        return CoverageDecision("jev", scores, ["PLEURA", "MEDIASTINUM"], 300, 400, 1e-05)


@pytest.fixture
def fakes(monkeypatch):
    jev = FakeJev()
    qwen_calls: list[int] = []
    qwen_state = {"raise": False}

    async def fake_qwen(scratchpad, sections, scan_type):
        qwen_calls.append(1)
        if qwen_state["raise"]:
            raise RuntimeError("model down")
        return CoverageDecision(
            "qwen", {"LUNGS": 0.0, "PLEURA": 1.0, "MEDIASTINUM": 0.0}, ["PLEURA"], 900, raw=["PLEURA"]
        )

    async def fake_prompts(request):
        return []

    monkeypatch.setattr(cr, "get_jev_coverage", lambda: jev)
    monkeypatch.setattr(cr, "qwen_coverage", fake_qwen)
    monkeypatch.setattr(cr, "_intelliprompts", fake_prompts)
    return jev, qwen_calls, qwen_state


def _post(client, **extra):
    return client.post("/api/canvas/review", json={**BASE, **extra})


def test_default_is_qwen_no_jev_call(authed_client, fakes, monkeypatch):
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    jev, qwen_calls, _ = fakes
    body = _post(authed_client).json()
    assert body["covered_sections"] == ["PLEURA"]
    assert body["coverage_scores"] == {"LUNGS": 0.0, "PLEURA": 1.0, "MEDIASTINUM": 0.0}
    assert body.get("coverage") is None
    assert jev.calls == 0 and len(qwen_calls) == 1


def test_jev_selected(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_COVERAGE_CANDIDATE", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, qwen_calls, _ = fakes
    body = _post(authed_client).json()
    assert body["covered_sections"] == ["PLEURA", "MEDIASTINUM"]
    assert body["coverage_scores"]["PLEURA"] == 0.95
    assert jev.calls == 1 and qwen_calls == []


def test_jev_selected_without_key_falls_back_to_qwen(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_COVERAGE_CANDIDATE", "jev")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    jev, qwen_calls, _ = fakes
    body = _post(authed_client).json()
    assert body["covered_sections"] == ["PLEURA"] and jev.calls == 0


def test_selected_failure_with_no_other_candidate_degrades_to_empty(authed_client, fakes, monkeypatch):
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    _, _, qwen_state = fakes
    qwen_state["raise"] = True
    r = _post(authed_client)
    assert r.status_code == 200
    assert r.json()["covered_sections"] == [] and r.json()["coverage_scores"] is None


def test_debug_runs_both_and_attaches_trace(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    jev, qwen_calls, _ = fakes
    body = _post(authed_client, coverage_debug=True).json()
    assert body["covered_sections"] == ["PLEURA"]  # qwen still selected
    t = body["coverage"]
    assert t["selected"] == "qwen"
    assert t["jev"]["scores"]["PLEURA"] == 0.95 and t["jev"]["latency_ms"] == 300
    assert t["qwen"]["covered"] == ["PLEURA"] and t["qwen"]["raw"] == ["PLEURA"]
    assert jev.calls == 1 and len(qwen_calls) == 1


def test_debug_selected_failure_uses_other_candidate(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("RR_COVERAGE_CANDIDATE", "jev")
    jev, _, _ = fakes
    jev.raise_ = True
    body = _post(authed_client, coverage_debug=True).json()
    assert body["covered_sections"] == ["PLEURA"]
    assert body["coverage"]["jev"]["error"] == "TriageError"


def test_debug_field_ignored_without_flag(authed_client, fakes, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    jev, _, _ = fakes
    body = _post(authed_client, coverage_debug=True).json()
    assert body.get("coverage") is None and jev.calls == 0


def _coverage_lines(caplog):
    return [json.loads(m.getMessage().split(" ", 1)[1]) for m in caplog.records
            if m.getMessage().startswith("[canvas.coverage.decision]")]


def test_jev_decision_logged_with_qset_and_scores(authed_client, fakes, monkeypatch, caplog):
    monkeypatch.setenv("RR_COVERAGE_CANDIDATE", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.canvas_routes")
    _post(authed_client)
    lines = _coverage_lines(caplog)
    assert len(lines) == 1
    assert lines[0] == {"event": "canvas.coverage.decision", "qset": QSET_VERSION, "selected": "jev",
                        "jev": {"LUNGS": 0.2, "PLEURA": 0.95, "MEDIASTINUM": 0.6}, "qwen": None,
                        "latency_ms": {"jev": 300, "qwen": None}, "errors": {"jev": None, "qwen": None}}


def test_default_qwen_logs_no_jev_decision(authed_client, fakes, monkeypatch, caplog):
    monkeypatch.delenv("RR_COVERAGE_CANDIDATE", raising=False)
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.canvas_routes")
    _post(authed_client)
    assert _coverage_lines(caplog) == []


def test_debug_trace_carries_qset(authed_client, fakes, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    body = _post(authed_client, coverage_debug=True).json()
    assert body["coverage"]["qset"] == QSET_VERSION


def test_coverage_only_review_does_not_wait_for_intelliprompts(authed_client, fakes, monkeypatch):
    # The section pills waited for IntelliPrompts (35–137 s on its fallback, lab 2026-09-27).
    called = []

    async def slow_prompts(request):
        called.append(1)
        return [cr.IntelliPrompt(question="q?", source_text="")]

    monkeypatch.setattr(cr, "_intelliprompts", slow_prompts)
    d = _post(authed_client, parts="coverage").json()
    assert d["covered_sections"] == ["PLEURA"] and d["prompts"] == [] and called == []


def test_prompts_only_review_runs_no_coverage(authed_client, fakes, monkeypatch):
    jev, qwen_calls, _ = fakes

    async def prompts(request):
        return [cr.IntelliPrompt(question="Liver lesion characterised?", source_text="")]

    monkeypatch.setattr(cr, "_intelliprompts", prompts)
    d = _post(authed_client, parts="prompts").json()
    assert [p["question"] for p in d["prompts"]] == ["Liver lesion characterised?"]
    assert d["covered_sections"] == [] and qwen_calls == [] and jev.calls == 0


def test_review_without_parts_runs_both_as_before(authed_client, fakes):
    d = _post(authed_client).json()
    assert d["covered_sections"] == ["PLEURA"]
