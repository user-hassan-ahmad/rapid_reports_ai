import json
import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import Report, Template, User
from rapid_reports_ai.hybrid_stack import report as SR
from rapid_reports_ai.hybrid_stack.gate_model import findings_hash
from rapid_reports_ai.hybrid_stack.units import StackUnit
from rapid_reports_ai.main import app

UNITS = [{"id": 1, "text": "Liver normal.", "group": "Liver", "structure": None, "attach_to": None, "parts": None,
          "covers": [], "abnormal": False, "pinned": False, "heading": False}]   # SYNTHETIC


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def authed(client, user, monkeypatch):
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_STACK", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def fakes(monkeypatch):
    seen = {}

    async def quick(**kw):
        seen["quick"] = kw
        return {"report_content": "FINDINGS\nLiver normal. No ascites.", "description": "d", "scan_type": "CT",
                "model_used": "m", "quality_check": {"enabled": True, "review": []}, "signature": ""}

    async def guard(report, removed, plain):
        seen["guard"] = (removed, plain)
        return report.replace(" No ascites.", ""), [{"type": "removal", "clause": "No ascites."}], []

    async def reconcile(removed, plain):
        return list(removed), []

    monkeypatch.setattr(SR, "generate_quick_report", quick)
    monkeypatch.setattr(SR, "guard", guard)
    monkeypatch.setattr(SR, "reconcile", reconcile)
    monkeypatch.setattr(SR, "schedule_review", lambda rid: seen.setdefault("review", rid))
    return seen


def _events(resp):
    out = []
    for block in resp.text.replace("\r\n", "\n").split("\n\n"):
        ev = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in ev:
            out.append((ev["event"], json.loads(ev["data"])))
    return out


def _body(**over):
    gate = {"conclusion_text": "Normal study.", "removed": ["No ascites."], "units_hash": "k",
            "findings_hash": findings_hash([StackUnit.model_validate(u) for u in UNITS])}
    return {"kind": "quick", "scan_type": "CT abdomen", "history": "pain", "units": UNITS, "groups": ["Liver"],
            "gate": gate, **over}


def test_quick_stack_generate_saves_plain_findings_and_records_edits(authed, db_session, fakes):
    events = _events(authed.post("/api/canvas/stack/generate", json=_body()))
    assert [e for e, _ in events] == ["candidate", "done"]
    cand, done = events[0][1], events[1][1]
    assert "No ascites." not in cand["content"]
    assert cand["quality_check"]["applied_edits"] == [{"type": "removal", "clause": "No ascites."}]
    assert fakes["quick"]["check_findings"] == "Liver normal.\nNormal study."
    assert "DO NOT ASSERT" in fakes["quick"]["findings"]
    row = db_session.get(Report, uuid.UUID(done["report_id"]))
    assert row.generation_mode == "stack" and row.report_type == "auto"
    assert row.input_data["variables"]["FINDINGS"] == "Liver normal.\nNormal study."
    assert row.candidate_reports[0]["removed"] == ["No ascites."]
    assert row.candidate_reports[0]["options_status"] == "skipped"
    assert row.generation_stamp["path"] == "stack"
    assert fakes["review"] == done["report_id"]


def test_generate_rejects_a_findings_hash_mismatch(authed, fakes):
    body = _body()
    body["gate"]["findings_hash"] = "0:0"
    events = _events(authed.post("/api/canvas/stack/generate", json=body))
    assert events == [("error", {"message": "The scratchpad changed after Confirm. Confirm again."})]
    assert "quick" not in fakes


def test_template_generate_refuses_another_users_template(authed, db_session, fakes):
    other = User(id=uuid.uuid4(), email="o@nhs.net", password_hash="x", full_name="O",
                 is_active=True, is_verified=True, is_approved=True)
    db_session.add(other)
    t = Template(name="T", template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": "## FINDINGS\nx"},
                 user_id=other.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(kind="template", template_id=str(t.id))))
    assert events == [("error", {"message": "Template not found."})]


def test_stack_off_is_404(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK", "0")
    assert authed.post("/api/canvas/stack/generate", json=_body()).status_code == 404


def test_exact_redictation_of_a_removed_sentence_reaches_the_report(authed, db_session, monkeypatch):
    from rapid_reports_ai.hybrid_stack import removed_guard as RG
    seen = {}

    async def boom(*a, **k):
        raise RuntimeError("jev down")

    async def quick(**kw):
        seen.update(kw)
        return {"report_content": "FINDINGS\nLiver normal. No ascites.", "description": "d", "model_used": "m",
                "quality_check": {"enabled": True, "review": []}}

    monkeypatch.setattr(RG, "ask_rows", boom)
    monkeypatch.setattr(SR, "generate_quick_report", quick)
    monkeypatch.setattr(SR, "schedule_review", lambda rid: None)
    units = UNITS + [{**UNITS[0], "id": 2, "text": "No ascites.", "group": "Peritoneum"}]
    body = _body(units=units, groups=["Liver", "Peritoneum"])
    body["gate"]["findings_hash"] = findings_hash([StackUnit.model_validate(u) for u in units])
    events = _events(authed.post("/api/canvas/stack/generate", json=body))
    assert [e for e, _ in events] == ["candidate", "done"]
    assert "DO NOT ASSERT" not in seen["findings"] and "No ascites." in seen["check_findings"]
    assert "No ascites." in events[0][1]["content"] and events[0][1]["removed"] == []


def test_template_description_reads_plain_statements(authed, db_session, user, monkeypatch):
    seen = {}

    async def lean(**kw):
        return {"report_content": "FINDINGS\nLiver normal.", "description": "from the block", "model_used": "m",
                "quality_check": {"enabled": True, "review": []}, "sections": ["FINDINGS"]}

    async def describe(findings, history, scan_type):
        seen["describe"] = findings
        return "from plain"

    async def reconcile(removed, plain):
        return list(removed), []

    async def guard(report, removed, plain):
        return report, [], []

    monkeypatch.setattr(SR, "generate_template_report_lean", lean)
    monkeypatch.setattr(SR, "_describe", describe)
    monkeypatch.setattr(SR, "reconcile", reconcile)
    monkeypatch.setattr(SR, "guard", guard)
    monkeypatch.setattr(SR, "template_structure", lambda cfg: object())
    monkeypatch.setattr(SR, "schedule_review", lambda rid: None)
    t = Template(name="T", template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": "## FINDINGS\nx"},
                 user_id=user.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(kind="template", template_id=str(t.id))))
    assert events[0][1]["description"] == "from plain" and seen["describe"] == "Liver normal.\nNormal study."
    assert "DO NOT ASSERT" not in seen["describe"]


def test_a_save_failure_streams_no_candidate(authed, fakes, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(SR, "create_report", broken)
    events = _events(authed.post("/api/canvas/stack/generate", json=_body()))
    assert events == [("error", {"message": "The report couldn't be saved. Please try again."})]
