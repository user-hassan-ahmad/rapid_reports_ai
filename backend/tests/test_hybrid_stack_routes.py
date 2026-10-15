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
    monkeypatch.delenv("RR_STACK", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_kill_switch_404(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK", "0")
    assert authed.post("/api/canvas/stack/group", json={"scan_type": "", "text": "", "regions": []}).status_code == 404


def test_off_by_the_one_switch():
    assert R.stack_allowed({"RR_STACK": "0"}) is False


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
    monkeypatch.setenv("RR_STACK_SHADOW_RATE", "0.5")          # retired: the shadow is always 0 now (§9.4)
    d = authed.get("/api/settings/status").json()
    assert d["stack"] is True and d["hybrid_stack"] is True and d["hybrid_stack_shadow_rate"] == 0.0


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

    async def assumed(dictation, normals, abnormal, removed, owned, **k):
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
    async def screen(normals, transport=None):   # a reviewer edit passes the Jev screen, not a regex
        return {k: [x for x in v if "prostate" not in x] for k, v in normals.items()}, []
    monkeypatch.setattr(R, "screen_normals", screen)
    assert authed.post(f"/api/canvas/stack/slim-sheets/{s['id']}", json={"region_normals": {
        "Liver": ["No cervical lymphadenopathy", "The prostate is normal."]}}).json() == {"ok": True}
    db_session.refresh(row)
    assert row.region_normals == {"Liver": ["No cervical lymphadenopathy."]}
    assert authed.post(f"/api/canvas/stack/slim-sheets/{s['id']}", json={"status": "discarded"}).json() == {"ok": True}
    db_session.refresh(row)
    assert row.status == "discarded"


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
    assert len(seen["A"]) == 16 == R.MAX_NORMALS_PER_REGION


def test_assumed_ignores_the_retired_dictated_normal_and_touched_fields(authed, monkeypatch):
    got = {}

    async def fake_assumed(dictation, normals, abnormal, removed, owned, **k):
        got.update(removed=removed, owned=owned, kw=set(k))
        from rapid_reports_ai.hybrid_stack.normals import AssumedResult
        return AssumedResult(assumed=normals)

    monkeypatch.setattr(R, "assumed_normals", fake_assumed)
    r = authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"A": ["Normal."]},
                                                       "dictated_normal": ["A"], "touched": ["A"], "removed": ["B."]})
    assert r.status_code == 200 and got["removed"] == ["B."] and got["owned"] == []
    assert not got["kw"] & {"dictated_normal", "touched"}


_RULED_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Brain (FINDINGS)
COVERS ["brain"]
NEGATIVE "No other interval changes compared with the previous MRI."
NORMAL [ventricles] "Unremarkable."
RULE WHEN [context: no previous study is available] SUPPRESS "No other interval changes compared with the previous MRI."
"""


def test_assumed_applies_the_templates_context_rules_and_labels(authed, monkeypatch, db_session, user):
    from rapid_reports_ai.database.models import Template
    from rapid_reports_ai.hybrid_stack.normals import AssumedResult
    t = Template(name="T", user_id=user.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _RULED_SHEET})
    db_session.add(t)
    db_session.commit()
    seen = {}

    async def fake_assumed(dictation, normals, *a, **k):
        seen.update(k)
        return AssumedResult(assumed={r: [] for r in normals})

    monkeypatch.setattr(R, "assumed_normals", fake_assumed)
    r = authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"Brain": ["Unremarkable."]},
                                                       "template_id": str(t.id), "clinical_history": "Headache."})
    assert r.status_code == 200
    assert seen["suppressions"] == [("no previous study is available",
                                     "No other interval changes compared with the previous MRI.")]
    assert seen["labels"] == {"Unremarkable.": "ventricles"} and seen["clinical_history"] == "Headache."
    assert seen["rules"] is None and seen["confirm"] is False   # the first refresh decides the session's rules
    assert seen["scan_type"] == ""   # this template stores no scan type
    assert seen["sides"] is False   # "Which side?" is quick only (side brief 2026-10-14)
    t.template_config = {**t.template_config, "scan_type": "MRI brain with contrast"}
    db_session.commit()
    authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"Brain": ["Unremarkable."]},
                                                   "template_id": str(t.id)})
    assert seen["scan_type"] == "MRI brain with contrast"
    authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"Brain": ["Unremarkable."]}})
    assert seen["suppressions"] == [] and seen["labels"] == {} and seen["sides"] is True
    authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"Brain": ["Unremarkable."]},
                                                   "template_id": str(t.id), "confirm": True,
                                                   "rules": {"no previous study is available": 0.9}})
    assert seen["rules"] == {"no previous study is available": 0.9} and seen["confirm"] is True


def test_assumed_passes_the_region_text_capped(authed, monkeypatch):
    from rapid_reports_ai.hybrid_stack.normals import AssumedResult
    seen = {}

    async def fake_assumed(dictation, normals, *a, **k):
        seen.update(k)
        return AssumedResult(assumed={r: [] for r in normals})

    monkeypatch.setattr(R, "assumed_normals", fake_assumed)
    texts = {f"R{i}": "No pneumothorax. " * 400 for i in range(50)}
    r = authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"R0": ["Normal."]},
                                                       "region_text": texts})
    assert r.status_code == 200
    assert len(seen["region_text"]) == 40 and all(len(t) <= R.MAX_REGION_TEXT for t in seen["region_text"].values())
    authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"R0": ["Normal."]}})
    assert seen["region_text"] == {}     # no region text: nothing grouped covers anything (compat removed, §9.4)
    authed.post("/api/canvas/stack/assumed", json={"dictation": "x", "region_normals": {"R0": ["Normal."]},
                                                   "region_text": {}})
    assert seen["region_text"] == {}     # sent but empty: nothing grouped in a region covers anything


def test_log_stamps_the_template_sheet(authed, db_session, user):
    from rapid_reports_ai.database.models import Template
    from rapid_reports_ai.template_sheet_structure import sheet_hash
    t = Template(name="T", template_config={"skill_sheet": "## FINDINGS\nx", "analyser_version": "a1"},
                 user_id=user.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    r = authed.post("/api/canvas/stack/log", json={"session_id": "s1", "template_id": str(t.id)})
    assert r.status_code == 200
    row = db_session.query(DictationStackLog).filter_by(session_id="s1").one()
    assert row.template_id == str(t.id) and row.stamp["sheet_hash"] == sheet_hash("## FINDINGS\nx")
    assert row.stamp["path"] == "scratchpad" and row.stamp["analyser_version"] == "a1"


def test_log_with_an_unknown_template_stores_no_stamp(authed, db_session):
    r = authed.post("/api/canvas/stack/log", json={"session_id": "s2", "template_id": str(uuid.uuid4())})
    assert r.json() == {"ok": True}
    row = db_session.query(DictationStackLog).filter_by(session_id="s2").one()
    assert row.template_id is None and row.stamp is None


def _template(db_session, owner_id, sheet="## FINDINGS\nx"):
    from rapid_reports_ai.database.models import Template
    t = Template(name="T", template_config={"skill_sheet": sheet}, user_id=owner_id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    return t


def test_log_stores_no_stamp_for_another_users_template(authed, db_session):
    other = User(id=uuid.uuid4(), email="other@nhs.net", password_hash="x", full_name="O",
                 is_active=True, is_verified=True, is_approved=True)
    db_session.add(other)
    db_session.commit()
    t = _template(db_session, other.id)
    assert authed.post("/api/canvas/stack/log", json={"session_id": "s3", "template_id": str(t.id)}).json() == {"ok": True}
    row = db_session.query(DictationStackLog).filter_by(session_id="s3").one()
    assert row.template_id is None and row.stamp is None


def test_log_still_writes_the_row_when_stamping_raises(authed, db_session, user, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("stamp down")
    monkeypatch.setattr(R, "generation_stamp", boom)
    t = _template(db_session, user.id)
    r = authed.post("/api/canvas/stack/log", json={"session_id": "s4", "template_id": str(t.id), "manual_moves": 3})
    assert r.json() == {"ok": True}
    row = db_session.query(DictationStackLog).filter_by(session_id="s4").one()
    assert row.manual_moves == 3 and row.stamp is None and row.template_id is None


def test_log_stamp_is_pinned_to_the_sheet_the_session_started_with(authed, db_session, user):
    from rapid_reports_ai.template_sheet_structure import sheet_hash
    t = _template(db_session, user.id, sheet="first")
    authed.post("/api/canvas/stack/log", json={"session_id": "s5", "template_id": str(t.id)})
    t.template_config = {"skill_sheet": "second"}
    db_session.commit()
    authed.post("/api/canvas/stack/log", json={"session_id": "s5", "template_id": str(t.id)})
    db_session.expire_all()
    row = db_session.query(DictationStackLog).filter_by(session_id="s5").one()
    assert row.stamp["sheet_hash"] == sheet_hash("first")


_HABIT_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Upper (FINDINGS)
COVERS ["alpha"]
NORMAL [alpha] "Alpha is normal."
RULE WHEN [findings: an alpha abnormality is reported] ASK "Extension beyond alpha?" YES "The abnormality extends beyond alpha." NO "No extension beyond alpha."
"""


def test_items_passes_the_templates_confirmed_habits_only(authed, monkeypatch, db_session, user):
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai.database.models import Template
    from rapid_reports_ai.hybrid_stack.items import ItemsResult
    led, _ = td.set_decision([], "habit", "Upper :: an alpha abnormality is reported",
                             {"mode": "ask", "question": "Extension beyond alpha?",
                              "yes": "The abnormality extends beyond alpha.", "no": "No extension beyond alpha."},
                             source="creation", at="t")
    t = Template(name="T", user_id=user.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _HABIT_SHEET, "decisions": led})
    unconfirmed = Template(name="U", user_id=user.id, is_active=True, tags=[],
                           template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _HABIT_SHEET})
    db_session.add_all([t, unconfirmed])
    db_session.commit()
    seen = {}

    async def items(*a, **k):
        seen.clear()
        seen.update(k)
        return ItemsResult(items=[])
    monkeypatch.setattr(R, "items_update", items)
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x", "template_id": str(t.id)})
    assert [(h.region, h.mode, h.question) for h in seen["habits"]] == [("Upper", "ask", "Extension beyond alpha?")]
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x"})
    assert "habits" not in seen
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x", "template_id": str(uuid.uuid4())})
    assert "habits" not in seen
    # Hassan H3: the same line with no confirmed entry is inactive
    authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x", "template_id": str(unconfirmed.id)})
    assert "habits" not in seen


def test_items_with_a_database_error_on_the_template_gives_generic_rows(authed, monkeypatch):
    from rapid_reports_ai.hybrid_stack.items import ItemsResult
    seen = {}

    def broken(*a, **k):
        raise RuntimeError("db down")

    async def items(*a, **k):
        seen.update(k, called=True)
        return ItemsResult(items=[])
    monkeypatch.setattr(R, "get_template", broken)
    monkeypatch.setattr(R, "items_update", items)
    r = authed.post("/api/canvas/stack/items", json={"regions": ["Upper"], "dictation": "x", "template_id": str(uuid.uuid4())})
    assert r.status_code == 200 and seen.get("called") and "habits" not in seen


_VALUES_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
"""


def _values_template(db_session, user):
    from rapid_reports_ai.database.models import Template
    t = Template(name="CMR", user_id=user.id, is_active=True, tags=[],
                 template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": _VALUES_SHEET})
    db_session.add(t)
    db_session.commit()
    return t


def test_slim_sheet_carries_the_templates_required_values(authed, db_session, user):
    t = _values_template(db_session, user)
    d = authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": "CMR", "template_id": str(t.id)}).json()
    assert d["status"] == "template" and d["required_values"] == ["LVEF", "LV mass index", "RVEF"]


def test_values_route_fills_the_templates_items_read_on_the_server(authed, monkeypatch, db_session, user):
    from rapid_reports_ai.hybrid_stack.values import ValueFill, ValuesResult
    t = _values_template(db_session, user)
    seen = {}

    async def fake(dictation, items):
        seen.update(dictation=dictation, items=items)
        return ValuesResult(values=[ValueFill(item="LVEF", state="filled", value="45%", quote="LVEF 45%.", score=0.9),
                                    ValueFill(item="LV mass index"), ValueFill(item="RVEF")])
    monkeypatch.setattr(R, "smart_fill", fake)
    d = authed.post("/api/canvas/stack/values", json={"dictation": "LVEF 45%.", "template_id": str(t.id)}).json()
    assert seen == {"dictation": "LVEF 45%.", "items": ["LVEF", "LV mass index", "RVEF"]}
    assert d["values"][0] == {"item": "LVEF", "state": "filled", "value": "45%", "quote": "LVEF 45%.", "score": 0.9,
                              "picks": []}
    assert [v["state"] for v in d["values"][1:]] == ["open", "open"] and d["error"] is None


def test_values_route_without_a_usable_template_has_no_items(authed, monkeypatch):
    seen = {}

    async def fake(dictation, items):
        seen["items"] = items
        from rapid_reports_ai.hybrid_stack.values import ValuesResult
        return ValuesResult()
    monkeypatch.setattr(R, "smart_fill", fake)
    assert authed.post("/api/canvas/stack/values", json={"dictation": "x"}).json()["values"] == []
    assert seen["items"] == []
    other = authed.post("/api/canvas/stack/values", json={"dictation": "x", "template_id": str(uuid.uuid4())})
    assert other.status_code == 200 and seen["items"] == []   # unknown / another user's template: nothing asked


def test_slim_sheet_carries_the_templates_structure_split(authed, monkeypatch, db_session, user):
    from rapid_reports_ai.hybrid_stack import routes as stack_routes
    seen = []

    async def fake(st, transport=None):
        seen.append(st.sheet_hash)
        return {"Left ventricle": {"Wall": ["Normal wall."]}}
    monkeypatch.setattr(stack_routes, "structure_normals", fake)
    t = _values_template(db_session, user)
    d = authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": "CMR", "template_id": str(t.id)}).json()
    assert d["region_structures"] == {"Left ventricle": {"Wall": ["Normal wall."]}} and len(seen) == 1
    # quick sessions never carry it
    assert authed.post("/api/canvas/stack/slim-sheet", json={"scan_type": ""}).json()["region_structures"] == {}
