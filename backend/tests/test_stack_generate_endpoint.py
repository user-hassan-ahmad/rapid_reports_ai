import json
import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import Report, Template, User
from rapid_reports_ai.hybrid_stack import report as SR
from rapid_reports_ai.hybrid_stack import resolution as RS
from rapid_reports_ai.hybrid_stack.gate_model import findings_hash
from rapid_reports_ai.hybrid_stack.units import StackUnit
from rapid_reports_ai.main import app
from rapid_reports_ai.template_sheet_structure import sheet_hash

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
            "gate": gate, "structure_key": RS.mint({"src": "free", "scan": "CT abdomen", "sk": "k", "sid": None}),
            **over}


def _template_key(t) -> str:
    return RS.mint({"src": "template", "tid": str(t.id), "sh": sheet_hash(t.template_config["skill_sheet"])})


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
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(kind="template", template_id=str(t.id), structure_key=_template_key(t))))
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
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(kind="template", template_id=str(t.id), structure_key=_template_key(t))))
    assert events[0][1]["description"] == "from plain" and seen["describe"] == "Liver normal.\nNormal study."
    assert "DO NOT ASSERT" not in seen["describe"]


def test_a_save_failure_streams_no_candidate(authed, fakes, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(SR, "create_report", broken)
    events = _events(authed.post("/api/canvas/stack/generate", json=_body()))
    assert events == [("error", {"message": "The report couldn't be saved. Please try again."})]


def test_reconcile_reads_only_dictation_and_taps(authed, db_session, monkeypatch):
    seen = {}

    async def reconcile(removed, said):
        seen["said"] = said
        return list(removed), []

    async def quick(**kw):
        return {"report_content": "FINDINGS\nLiver normal.", "description": "d", "model_used": "m",
                "quality_check": {"enabled": True, "review": []}}

    async def guard(report, removed, plain):
        return report, [], []

    monkeypatch.setattr(SR, "reconcile", reconcile)
    monkeypatch.setattr(SR, "generate_quick_report", quick)
    monkeypatch.setattr(SR, "guard", guard)
    monkeypatch.setattr(SR, "schedule_review", lambda rid: None)
    body = _body()
    body["gate"]["assumed"] = {"Kidneys": ["The ureters are not dilated."]}
    _events(authed.post("/api/canvas/stack/generate", json=body))
    assert seen["said"] == "Liver normal."


def test_candidate_carries_the_confirmed_normals_minus_removed(authed, db_session, fakes):
    body = _body()
    body["gate"]["assumed"] = {"Liver": ["Normal size.", "No ascites."], "Spleen": ["Spleen normal."]}
    events = _events(authed.post("/api/canvas/stack/generate", json=body))
    assert events[0][1]["assumed_confirmed"] == ["Normal size.", "Spleen normal."]


NUM_UNITS = [{**UNITS[0], "text": "Node 14 mm short axis.", "abnormal": True},
             {**UNITS[0], "id": 2, "text": "Liver normal."}]   # SYNTHETIC


def _num_body(**over):
    units = [StackUnit.model_validate(u) for u in NUM_UNITS]
    gate = {"conclusion_text": "Node 22 mm.", "removed": [], "units_hash": "k", "findings_hash": findings_hash(units),
            "values": [{"item": "LVEF", "value": "55%", "state": "entered"}]}
    return _body(units=NUM_UNITS, gate=gate, history="Prior node 30 mm.", **over)


def _flags(events):
    return [i for i in events[0][1]["quality_check"]["review"] if i.get("kind") == "dictated_number_missing"]


@pytest.mark.parametrize("on", [True, False])
def test_quick_flags_a_dictated_number_the_report_dropped(authed, fakes, monkeypatch, on):
    if on:
        monkeypatch.setenv("RR_DICTATED_NUMBERS", "1")
    else:
        monkeypatch.delenv("RR_DICTATED_NUMBERS", raising=False)
    flags = _flags(_events(authed.post("/api/canvas/stack/generate", json=_num_body())))
    if not on:
        assert flags == []
        return
    # dictated 14 mm and the typed LVEF 55% are missing; the history (30) and the conclusion (22) are never sources
    assert [(f["text"], f["severity"]) for f in flags] == [("14 mm", "high"), ("55%", "high")]
    assert flags[0]["sentence"] == "Node 14 mm short axis."


def test_template_flags_a_dictated_number_the_report_dropped(authed, db_session, user, monkeypatch):
    monkeypatch.setenv("RR_DICTATED_NUMBERS", "1")

    async def lean(**kw):
        return {"report_content": "FINDINGS\nNode 14 mm short axis. Liver normal.", "description": "d",
                "model_used": "m", "quality_check": {"enabled": True, "review": []}, "sections": ["FINDINGS"]}

    async def describe(findings, history, scan_type):
        return "d"

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
    events = _events(authed.post("/api/canvas/stack/generate",
                                 json=_num_body(kind="template", template_id=str(t.id), structure_key=_template_key(t))))
    assert [f["text"] for f in _flags(events)] == ["55%"]   # 14 mm is written; the typed value is not


def test_template_generate_hands_the_writer_each_filled_values_sentence_and_region(authed, db_session, user,
                                                                                 monkeypatch):
    """P3 2026-10-15 (SYNTHETIC): a value the gate filled reaches Generate with the dictated sentence it was read
    from and that sentence's region, so code can write it back if the writer drops it."""
    seen = {}
    units = [{**UNITS[0], "id": 1, "text": "Liver span 17 cm.", "group": "Liver"},
             {**UNITS[0], "id": 2, "text": "Spleen normal.", "group": "Spleen"}]

    async def lean(**kw):
        seen["stack"] = kw["stack"]
        return {"report_content": "FINDINGS\nSpleen normal.", "description": "d", "model_used": "m",
                "quality_check": {"enabled": True, "review": []}, "sections": ["FINDINGS"]}

    async def reconcile(removed, plain):
        return list(removed), []

    async def guard(report, removed, plain):
        return report, [], []

    async def describe(findings, history, scan_type):
        return "d"

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
    body = _body(kind="template", template_id=str(t.id), structure_key=_template_key(t), units=units,
                 groups=["Liver", "Spleen"])
    body["gate"]["findings_hash"] = findings_hash([StackUnit.model_validate(u) for u in units])
    body["gate"]["values"] = [
        {"item": "Liver span", "state": "filled", "value": "17 cm", "quote": "Liver span 17 cm."},
        {"item": "Spleen length", "state": "picked", "value": "11 cm", "quote": "Spleen 11 cm"},
        {"item": "Portal vein", "state": "filled", "value": None, "quote": None, "kept": True},
        {"item": "CBD", "state": "na", "value": None, "quote": None}]
    events = _events(authed.post("/api/canvas/stack/generate", json=body))
    assert events[0][0] == "candidate"
    assert seen["stack"]["values_na"] == ["CBD"]
    assert seen["stack"]["values_filled"] == ["Liver span", "Spleen length", "Portal vein"]
    # a quote no dictated unit holds is dropped (flag only); a chip without one has no entry
    assert seen["stack"]["values_quotes"] == {"Liver span": {"quote": "Liver span 17 cm.",
                                                             "sentence": "Liver span 17 cm.", "region": "Liver"}}


SITE_UNITS = [{**UNITS[0], "text": "Aortic sinus 4.1 cm.", "abnormal": True}]   # SYNTHETIC


@pytest.mark.parametrize("on", [True, False])
def test_quick_flags_a_dictated_value_moved_to_another_structure(authed, fakes, monkeypatch, on):
    from rapid_reports_ai import dictated_structure_check as dsc

    async def quick(**kw):
        return {"report_content": "FINDINGS\nAortic root 4.1 cm.\n\nIMPRESSION\nAortic sinus 4.1 cm.",
                "description": "d", "scan_type": "CT", "model_used": "m",
                "quality_check": {"enabled": True, "review": []}, "signature": ""}

    async def ask(ps):
        return [0.1 for _ in ps]
    monkeypatch.setattr(SR, "generate_quick_report", quick)
    monkeypatch.setattr(dsc, "ask_same_site", ask)
    if on:
        monkeypatch.setenv("RR_DICTATED_STRUCTURES", "1")
    else:
        monkeypatch.delenv("RR_DICTATED_STRUCTURES", raising=False)
    units = [StackUnit.model_validate(u) for u in SITE_UNITS]
    gate = {"conclusion_text": "Dilated aortic sinus.", "removed": [], "units_hash": "k",
            "findings_hash": findings_hash(units)}
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(units=SITE_UNITS, gate=gate)))
    flags = [i for i in events[0][1]["quality_check"]["review"] if i.get("kind") == "dictated_structure_changed"]
    if not on:
        assert flags == []
        return
    assert [(f["text"], f["sentence"], f["dictated_quote"], f["severity"]) for f in flags] == [
        ("4.1 cm", "Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", "high")]
    assert flags[0]["edit"] == {"mode": "replace", "find": "Aortic root 4.1 cm.", "replace": "Aortic sinus 4.1 cm."}
