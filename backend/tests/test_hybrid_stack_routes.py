import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import DictationStackLog, StackSchemaFamily, User
from rapid_reports_ai.hybrid_stack import routes as R
from rapid_reports_ai.hybrid_stack import service as S
from rapid_reports_ai.hybrid_stack.schemas import Region
from rapid_reports_ai.main import app


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
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_kill_switch_404(authed, monkeypatch):
    monkeypatch.setenv("RR_HYBRID_STACK", "0")
    assert authed.post("/api/canvas/stack/group", json={"scan_type": "", "text": "", "regions": []}).status_code == 404


def test_off_without_dictation_package(authed, monkeypatch):
    monkeypatch.delenv("RR_DICTATION_V2", raising=False)
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert R.stack_allowed() is False


def test_group_route(authed, monkeypatch):
    async def fake(scan_type, text, regions, previous):
        return S.GroupResult(units=[], new_ids=[], pills=["Liver"])
    monkeypatch.setattr(R, "group_update", fake)
    d = authed.post("/api/canvas/stack/group", json={"scan_type": "CT", "text": "x",
                                                     "regions": [{"name": "Liver", "includes": "l"}]}).json()
    assert d["pills"] == ["Liver"]


def test_schema_route_quick(authed, monkeypatch):
    async def fake(scan_type, history, structure, db):
        assert structure is None
        return S._result([Region(name="Liver", includes="l")], "family", "ct", family="abdomen_pelvis")
    monkeypatch.setattr(R, "resolve_schema", fake)
    d = authed.post("/api/canvas/stack/schema", json={"scan_type": "CT", "clinical_history": ""}).json()
    assert d["groups"] == ["Technique", "Liver", "General", "Conclusion"] and d["pills"] == ["Liver"]


def test_log_upserts_by_session(authed, db_session):
    body = {"session_id": "s1", "scan_type": "CT", "schema_key": "ct", "schema_source": "family",
            "provisional": False, "units": [], "pills_derived": ["Liver"], "pills_jev": [], "sections": [],
            "structured_text": "", "manual_moves": 0, "latency_ms": {}}
    assert authed.post("/api/canvas/stack/log", json=body).json() == {"ok": True}
    assert authed.post("/api/canvas/stack/log", json={**body, "manual_moves": 2}).json() == {"ok": True}
    rows = db_session.query(DictationStackLog).filter_by(session_id="s1").all()
    assert len(rows) == 1 and rows[0].manual_moves == 2


def test_reviewer_endpoints(authed, db_session, monkeypatch):
    db_session.add(StackSchemaFamily(key="mri ankle", scan_type="MRI ankle", regions=[{"name": "T", "includes": "t"}],
                                     source="reconciler:composed", status="provisional"))
    db_session.commit()
    monkeypatch.setenv("RR_STACK_REVIEWERS", "someone@else.net")
    assert authed.get("/api/canvas/stack/families").status_code == 403
    monkeypatch.setenv("RR_STACK_REVIEWERS", "Rad@NHS.net")
    rows = authed.get("/api/canvas/stack/families?status=provisional").json()
    assert rows[0]["key"] == "mri ankle"
    upd = authed.post("/api/canvas/stack/families/mri ankle", json={"status": "approved",
                                                                    "regions": [{"name": "Tendons", "includes": "x"}]})
    assert upd.status_code == 200
    row = db_session.get(StackSchemaFamily, "mri ankle")
    db_session.refresh(row)
    assert row.status == "approved" and row.regions[0]["name"] == "Tendons" and row.source == "admin"


def test_settings_status_carries_the_flags(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK_SHADOW_RATE", "0.5")
    d = authed.get("/api/settings/status").json()
    assert d["hybrid_stack"] is True and d["hybrid_stack_shadow_rate"] == 0.5


def test_log_keeps_gate_and_report_id(authed, db_session):
    body = {"session_id": "s2", "units": [{"id": 0}], "manual_moves": 3, "gate": {"conclusion_text": "Diverticulitis."}}
    assert authed.post("/api/canvas/stack/log", json=body).json() == {"ok": True}
    assert authed.post("/api/canvas/stack/log", json={"session_id": "s2", "report_id": "r1"}).json() == {"ok": True}
    row = db_session.query(DictationStackLog).filter_by(session_id="s2").one()
    db_session.refresh(row)
    assert row.gate == {"conclusion_text": "Diverticulitis."} and row.report_id == "r1"
    assert row.units == [{"id": 0}] and row.manual_moves == 3


def test_items_assumed_and_draft_routes(authed, monkeypatch):
    from rapid_reports_ai.hybrid_stack.draft import DraftResult
    from rapid_reports_ai.hybrid_stack.items import Item, ItemsResult
    from rapid_reports_ai.hybrid_stack.normals import AssumedResult

    async def items(scan_type, history, regions, dictation, abnormal, not_assessable, removed, tapped, referrals, review):
        assert regions == ["Bowel"] and abnormal == ["Diverticulitis."] and removed == ["No fistula."]
        return ItemsResult(items=[Item(id="a", kind="finding", region="Bowel", question="Abscess?",
                                       sentences=["No pericolic abscess."])])

    async def assumed(dictation, normals, abnormal, dictated_normal, removed, owned, touched):
        assert normals == {"Liver": ["The liver is normal."]}
        return AssumedResult(assumed=normals)

    async def draft(scan_type, history, findings):
        return DraftResult(text="Acute diverticulitis.")
    monkeypatch.setattr(R, "items_update", items)
    monkeypatch.setattr(R, "assumed_normals", assumed)
    monkeypatch.setattr(R, "draft_conclusion", draft)
    d = authed.post("/api/canvas/stack/items", json={"regions": ["Bowel"], "dictation": "Diverticulitis.",
                                                     "abnormal": ["Diverticulitis."], "removed": ["No fistula."]}).json()
    assert d["items"][0]["sentences"] == ["No pericolic abscess."] and d["items"][0]["answered"] is False
    d = authed.post("/api/canvas/stack/assumed", json={"region_normals": {"Liver": ["The liver is normal."]}}).json()
    assert d["assumed"] == {"Liver": ["The liver is normal."]}
    assert authed.post("/api/canvas/stack/draft", json={"findings": "x"}).json()["text"] == "Acute diverticulitis."


def test_slim_sheet_route_and_review(authed, monkeypatch, db_session, user):
    from rapid_reports_ai.database.models import DictationStackLog, StackSlimSheet
    row = StackSlimSheet(family="abdomen_pelvis", contrast="portal_venous", prompt_version="slim-1", status="provisional",
                         markdown="x", region_normals={"Liver": ["The liver is normal."]}, not_assessable="Doppler flow")
    db_session.add(row)
    db_session.commit()

    async def gom(db, scan_type, family, regions):
        assert family == "abdomen_pelvis" and regions[0].name == "Liver"   # resolved on the server
        return row

    async def resolve(scan_type, history, structure, db):
        return S.SchemaResult(regions=[Region(name="Liver", includes="l")], groups=[], pills=[], source="approved",
                              family=None, key="abdomen_pelvis", provisional=False)
    monkeypatch.setattr(R, "slim_get_or_make", gom)
    monkeypatch.setattr(R, "resolve_schema", resolve)
    d = authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": "CT AP", "family_key": "ignored",
                                                          "regions": [{"name": "Injected", "includes": "x"}]}).json()
    assert d["ready"] and d["region_normals"] == {"Liver": ["The liver is normal."]} and d["not_assessable"] == "Doppler flow"
    assert authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": ""}).json()["ready"] is False

    # review: forbidden without the reviewer list; flag after 5 sessions with >= 30% removing a sentence
    assert authed.get("/api/canvas/stack/slim-sheets").status_code == 403
    import uuid
    for k in range(5):
        db_session.add(DictationStackLog(user_id=uuid.uuid4(), session_id=f"s{k}", schema_key="abdomen_pelvis",
                                         gate={"removed": ["the liver is normal"] if k < 2 else []}))
    db_session.commit()
    monkeypatch.setenv("RR_STACK_REVIEWERS", user.email)
    [s] = authed.get("/api/canvas/stack/slim-sheets").json()
    assert s["flagged"] == 1 and s["removal"]["The liver is normal."] == {"sessions": 5, "removed": 2, "flag": True}
    assert authed.post(f"/api/canvas/stack/slim-sheets/{s['id']}", json={"status": "discarded"}).json() == {"ok": True}
    db_session.refresh(row)
    assert row.status == "discarded"


def test_debug_route_only_with_the_flag(authed, monkeypatch):
    monkeypatch.delenv("RR_STACK_DEBUG", raising=False)
    assert authed.post("/api/canvas/stack/debug", json={"kind": "x"}).status_code == 404
    monkeypatch.setenv("RR_STACK_DEBUG", "1")
    assert authed.post("/api/canvas/stack/debug", json={"kind": "x"}).json() == {"ok": True}



def test_changed_recheck_and_conclusion_check_routes(authed, monkeypatch):
    from rapid_reports_ai.hybrid_stack.items import ItemsResult

    async def material(before, after):
        return 0.97 if "abscess" in after[-1] else 0.1
    async def stale(conclusion, findings):
        return 0.9 if "Uncomplicated" in conclusion else 0.2
    async def recheck(dictation, rows, removed, tapped):
        assert rows[0].question == "Abscess?"
        return ItemsResult(items=[], capped=[])
    monkeypatch.setattr(R, "ask_material", material)
    monkeypatch.setattr(R, "ask_stale", stale)
    monkeypatch.setattr(R, "items_recheck", recheck)
    same = authed.post("/api/canvas/stack/changed", json={"before": ["A."], "after": ["A. "]}).json()
    assert same == {"material": False, "score": 0.0}                      # identical: Jev not asked
    assert authed.post("/api/canvas/stack/changed", json={"before": ["Diverticulitis."], "after": ["Diverticulitis with abscess."]}).json()["material"] is True
    assert authed.post("/api/canvas/stack/changed", json={"before": ["Diverticulitis."], "after": ["Acute diverticulitis."]}).json()["material"] is False
    assert authed.post("/api/canvas/stack/conclusion-check", json={"conclusion": "Uncomplicated diverticulitis.", "findings": ["x"]}).json()["stale"] is True
    row = {"id": "a", "kind": "finding", "region": "Bowel", "question": "Abscess?", "sentences": ["No abscess."]}
    assert authed.post("/api/canvas/stack/recheck", json={"dictation": "x", "rows": [row]}).json()["items"] == []


async def test_post_chat_moves_a_cerebras_rate_limit_to_the_same_model_on_groq(monkeypatch):
    import httpx
    from rapid_reports_ai.hybrid_stack.http import post_chat
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        body = _j.loads(req.content)
        seen.append((req.url.host, body["model"], body.get("reasoning_effort"), body.get("max_tokens")))
        if "cerebras" in req.url.host:
            return httpx.Response(429, json={"message": "high traffic"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    r = await post_chat({"model": "qwen-3.8-27b", "reasoning_effort": "medium", "max_tokens": 64000, "messages": []},
                        5.0, httpx.MockTransport(handler))
    assert r.status_code == 200
    assert seen == [("api.cerebras.ai", "qwen-3.8-27b", "medium", 64000), ("api.groq.com", "qwen/qwen3.8-27b", "default", 16384)]


def test_unfinished_route_flags_what_jev_scores_unfinished_with_offsets(authed, monkeypatch):
    seen = {}

    async def fake(sentences):
        seen["s"] = sentences
        return [0.05 if s.endswith(".") else 0.95 for s in sentences]
    monkeypatch.setattr(R, "ask_unfinished", fake)
    text = "Normal appendix. The terminal ileum is\nConclusion: acute appendicitis."
    d = authed.post("/api/canvas/stack/unfinished", json={"text": text}).json()
    assert seen["s"] == ["Normal appendix.", "The terminal ileum is", "Conclusion: acute appendicitis."]
    [f] = d["flags"]
    assert text[f["start"]:f["end"]] == "The terminal ileum is"
    assert f["kind"] == "truncation" and f["severity"] == "high" and f["blocking"] is True


def test_unfinished_route_fails_open(authed, monkeypatch):
    async def boom(sentences):
        raise RuntimeError("jev down")
    monkeypatch.setattr(R, "ask_unfinished", boom)
    assert authed.post("/api/canvas/stack/unfinished", json={"text": "The kidneys are"}).json() == {"flags": []}


def test_slim_sheet_for_a_template_without_a_usable_structure_says_so(authed, db_session, user):
    from rapid_reports_ai.database.models import Template
    t = Template(name="T", user_id=user.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": "## FINDINGS\nx"})
    db_session.add(t)
    db_session.commit()
    d = authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": "CT", "template_id": str(t.id)}).json()
    assert d["status"] == "template_unusable" and not d["ready"] and d["region_normals"] == {}


def test_assumed_checks_up_to_sixteen_normals_per_region(authed, monkeypatch):
    seen = {}

    async def fake_assumed(dictation, normals, *a, **k):
        seen.update(normals)
        from rapid_reports_ai.hybrid_stack.normals import AssumedResult
        return AssumedResult(assumed={r: [] for r in normals})

    monkeypatch.setattr(R, "assumed_normals", fake_assumed)
    sentences = [f"Normal {i}." for i in range(20)]
    r = authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"A": sentences}})
    assert r.status_code == 200
    assert len(seen["A"]) == 16
