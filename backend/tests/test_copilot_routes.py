import asyncio
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import DictationStackLog, User
from rapid_reports_ai.hybrid_stack.copilot import ask as A
from rapid_reports_ai.hybrid_stack.copilot import registry as Reg
from rapid_reports_ai.hybrid_stack.copilot import routes as CR
from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.ask import AskResult
from rapid_reports_ai.hybrid_stack.copilot.recs import RecsResult
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Card, GuidelineContent, Preview, Supplement
from rapid_reports_ai.main import app


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T", is_active=True,
             is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture(autouse=True)
def fresh_sessions(db_engine, monkeypatch):
    """The routes' own sessions (resolve and ask run in them) open on the test engine; the Copilot is on."""
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)
    monkeypatch.delenv("RR_STACK_COPILOT", raising=False)
    monkeypatch.setattr(CR, "SessionLocal", sessionmaker(bind=db_engine, autoflush=False, autocommit=False))


@pytest.fixture
def authed(client, user, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _seed(db, key="k@1", branches=None, supplements=None):
    Reg.upsert(db, key=key, name="K", version="1", aliases=[], publication=None,
               content=GuidelineContent(branches=branches or [Branch(name="B", state="checked")],
                                        supplements=supplements or []), sources=[], chunks=[])


async def _drain():
    await asyncio.gather(*list(CR._BG), return_exceptions=True)


def test_kill_switch(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK_COPILOT", "0")
    assert authed.post("/api/canvas/stack/guidelines/match", json={"findings": []}).status_code == 404
    assert authed.post("/api/canvas/stack/guidelines/ask", json={"question": "q"}).status_code == 404
    assert CR.copilot_allowed() is False


def test_off_with_the_stack(monkeypatch):
    assert CR.copilot_allowed({"RR_DICTATION_V2": "1"}) is True
    assert CR.copilot_allowed({"RR_DICTATION_V2": "1", "RR_HYBRID_STACK": "0"}) is False


def test_status_flag(authed, monkeypatch):
    assert authed.get("/api/settings/status").json()["stack_copilot"] is True
    monkeypatch.setenv("RR_STACK_COPILOT", "0")
    assert authed.get("/api/settings/status").json()["stack_copilot"] is False


def test_match_route(authed, monkeypatch):
    async def fake(db, scan_type, history, findings):
        assert scan_type == "CT" and history == "h"
        return [Card(key="k@1", name="K", version="1", finding_id=findings[0].id, branch="B")]
    monkeypatch.setattr(CR, "match", fake)
    d = authed.post("/api/canvas/stack/guidelines/match",
                    json={"scan_type": "CT", "clinical_history": "h", "findings": [{"id": "u1", "text": "x"}]}).json()
    assert d["cards"][0]["key"] == "k@1" and d["cards"][0]["finding_id"] == "u1"


def test_open_route_returns_entry_and_preview(authed, monkeypatch):
    seen = {}

    async def resolve(db, card):
        _seed(db)
        return Reg.entry(Reg.by_key(db, "k@1"))

    async def prev(entry, branch, findings, history, answered):
        seen.update(branch=branch, answered=answered)
        return Preview(missing=["risk"])
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "preview", prev)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1", "branch": "B"},
        "findings": "x", "clinical_history": "", "answered": {"risk": "High"}}).json()
    assert d["entry"]["key"] == "k@1" and d["preview"]["missing"] == ["risk"] and d["error"] is None
    assert d["branch"] == "B" and seen == {"branch": "B", "answered": {"risk": "High"}}


@pytest.mark.parametrize("picked,want", [(None, "Overview"), ("B", "B")])
def test_open_branchless_card(authed, db_session, monkeypatch, picked, want):
    _seed(db_session, branches=[Branch(name="B", state="checked"), Branch(name="Overview", state="checked")])

    async def resolve(db, card):
        return Reg.entry(Reg.by_key(db, "k@1"))

    async def pick(finding, entry, history=""):
        return picked

    async def prev(entry, branch, findings, history, answered):
        return Preview()
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR.M, "pick_branch", pick)
    monkeypatch.setattr(CR, "preview", prev)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "finding_id": "q"}, "findings": "x"}).json()
    assert d["branch"] == want


def test_open_branchless_card_falls_back_to_a_checked_branch(authed, db_session, monkeypatch):
    _seed(db_session, branches=[Branch(name="A", state="not_available"), Branch(name="B", state="checked")])

    async def resolve(db, card):
        return Reg.entry(Reg.by_key(db, "k@1"))

    async def pick(finding, entry, history=""):
        return None

    async def prev(entry, branch, findings, history, answered):
        return Preview()
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR.M, "pick_branch", pick)
    monkeypatch.setattr(CR, "preview", prev)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "finding_id": "q"}, "findings": "x"}).json()
    assert d["branch"] == "B"


def test_open_tnm_is_offline(authed, monkeypatch):
    site = tnm.sites()[0]

    async def resolve(db, card):
        raise AssertionError("TNM is never resolved")

    async def prev(entry, branch, findings, history, answered):
        return Preview(missing=["T"])
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "preview", prev)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": tnm.key_for(site), "name": "TNM", "finding_id": "u1"}, "findings": "x"}).json()
    assert d["entry"]["key"] == tnm.key_for(site) and d["branch"] == "Staging" and d["preview"]["missing"] == ["T"]


def test_open_route_fetch_failure(authed, monkeypatch):
    async def resolve(db, card):
        return None
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "finding_id": "u1"}, "findings": "x"}).json()
    assert d["entry"] is None and d["error"] == "unavailable"


def test_open_preview_failure_still_returns_the_entry(authed, monkeypatch):
    async def resolve(db, card):
        _seed(db)
        return Reg.entry(Reg.by_key(db, "k@1"))

    async def prev(entry, branch, findings, history, answered):
        raise RuntimeError("boom")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "preview", prev)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "finding_id": "u1", "branch": "B"}, "findings": "x"}).json()
    assert d["entry"]["key"] == "k@1" and d["preview"] == {"settled": [], "missing": [], "proposal": None}


async def test_open_timeout_keeps_the_fetch_going(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "OPEN_TIMEOUT_S", 0.05)

    async def resolve(db, card):
        await asyncio.sleep(0.2)
        _seed(db)
        return Reg.entry(Reg.by_key(db, "k@1"))
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    req = CR.OpenRequest(card=Card(key="k@1", name="K", finding_id="u1", branch="B"), findings="x")
    out = await CR.copilot_open(req, user, db_session)
    assert out.entry is None and out.error == "loading"
    await _drain()
    assert Reg.by_key(db_session, "k@1") is not None   # the fetch finished in its own session


def test_preview_is_registry_only(authed, db_session, monkeypatch):
    async def resolve(db, card):
        raise AssertionError("preview never fetches")

    async def prev(entry, branch, findings, history, answered):
        return Preview(missing=[branch])
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "preview", prev)
    body = {"card": {"key": "k@1", "name": "K", "finding_id": "u1", "branch": "B"}, "findings": "x"}
    assert authed.post("/api/canvas/stack/guidelines/preview", json=body).json()["error"] == "unknown guideline"
    _seed(db_session)
    d = authed.post("/api/canvas/stack/guidelines/preview", json=body).json()
    assert d["entry"]["key"] == "k@1" and d["preview"]["missing"] == ["B"] and d["error"] is None
    site = tnm.sites()[0]
    body = {"card": {"key": tnm.key_for(site), "name": "TNM", "finding_id": "u1", "branch": "Staging"}, "findings": "x"}
    assert authed.post("/api/canvas/stack/guidelines/preview", json=body).json()["preview"]["missing"] == ["Staging"]


def test_ask_route(authed, monkeypatch):
    seen = {}

    async def fake(db, question, key, ctx, history, finding_id=""):
        seen.update(question=question, key=key, findings=ctx.findings, n=len(history), finding_id=finding_id)
        return AskResult(kind="card", key=key, answer="a")
    monkeypatch.setattr(CR, "ask", fake)
    hist = [{"question": f"q{i}", "answer": "a"} for i in range(5)]
    d = authed.post("/api/canvas/stack/guidelines/ask", json={
        "question": "why", "key": "k@1", "finding_id": "u1", "findings": "f", "history": hist}).json()
    assert d["answer"] == "a" and d["loading"] is False
    assert seen == {"question": "why", "key": "k@1", "findings": "f", "n": 3, "finding_id": "u1"}


def test_ask_on_an_unresolved_listed_card_resolves_it_first(authed, db_session, monkeypatch):
    order = []

    async def resolve(db, card):
        order.append(("resolve", card.key))
        _seed(db)
        return Reg.entry(Reg.by_key(db, "k@1"))

    async def fake(db, question, key, ctx, history, finding_id=""):
        order.append(("ask", Reg.by_key(db, key) is not None))
        return AskResult(kind="card", key=key, answer="a")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "ask", fake)
    card = {"key": "k@1", "name": "K", "finding_id": "u1"}
    authed.post("/api/canvas/stack/guidelines/ask", json={"question": "why", "key": "k@1", "card": card})
    assert order == [("resolve", "k@1"), ("ask", True)]
    order.clear()
    authed.post("/api/canvas/stack/guidelines/ask", json={"question": "why", "key": "k@1", "card": card})
    assert order == [("ask", True)]   # a held key is asked directly


async def test_ask_timeout_answers_generally_and_keeps_resolving(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "ASK_TIMEOUT_S", 0.05)
    done = []

    async def fake(db, question, key, ctx, history, finding_id=""):
        await asyncio.sleep(0.2)
        _seed(db)
        done.append(True)
        return AskResult(kind="card", key="k@1", answer="late")

    async def general(question, ctx, history):
        return "Usually so."
    monkeypatch.setattr(CR, "ask", fake)
    monkeypatch.setattr(A, "_general_answer", general)
    out = await CR.copilot_ask(CR.AskRequest(question="why"), user, db_session)
    assert out.kind == "general" and out.loading and not out.supported
    assert out.answer == f"{CR.STILL_LOADING} {A.FROM_GENERAL} Usually so."
    await _drain()
    assert done == [True] and Reg.by_key(db_session, "k@1") is not None


async def test_ask_timeout_general_failure_still_says_loading(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "ASK_TIMEOUT_S", 0.01)

    async def fake(db, question, key, ctx, history, finding_id=""):
        await asyncio.sleep(0.05)
        return AskResult(kind="general", answer="late")

    async def general(question, ctx, history):
        raise TimeoutError
    monkeypatch.setattr(CR, "ask", fake)
    monkeypatch.setattr(A, "_general_answer", general)
    out = await CR.copilot_ask(CR.AskRequest(question="why", key="k@1"), user, db_session)
    assert out.loading and out.answer == CR.STILL_LOADING and out.key == "k@1"
    await _drain()


def test_recommendations_route(authed, monkeypatch):
    async def fake(scan_type, history, findings, conclusion, applied):
        return RecsResult(items=[f"{conclusion}|{applied[0]}"])
    monkeypatch.setattr(CR, "suggest", fake)
    d = authed.post("/api/canvas/stack/guidelines/recommendations",
                    json={"conclusion": "c", "applied": ["x"]}).json()
    assert d["items"] == ["c|x"]


def test_registry_review_routes_need_reviewer(authed, db_session, monkeypatch):
    monkeypatch.setenv("RR_STACK_REVIEWERS", "someone@else")
    assert authed.get("/api/canvas/stack/guidelines/registry").status_code == 403
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json={"status": "verified"}).status_code == 403
    monkeypatch.setenv("RR_STACK_REVIEWERS", "rad@nhs.net")
    _seed(db_session)
    assert authed.get("/api/canvas/stack/guidelines/registry").json()[0]["key"] == "k@1"
    assert authed.post("/api/canvas/stack/guidelines/registry/nope@1", json={"status": "verified"}).status_code == 404
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json={"status": "verified"}).json() == {"ok": True}
    row = Reg.by_key(db_session, "k@1")
    db_session.refresh(row)
    assert row.status == "verified" and row.verified_by == "rad@nhs.net" and row.verified_at is not None
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json={"status": "draft"}).json() == {"ok": True}
    db_session.refresh(row)
    assert row.status == "draft" and row.verified_by is None
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json={"status": "discarded"}).json() == {"ok": True}
    db_session.expire_all()
    assert Reg.by_key(db_session, "k@1") is None


def test_registry_content_edit_verifies_a_supplement(authed, db_session, monkeypatch):
    monkeypatch.setenv("RR_STACK_REVIEWERS", "rad@nhs.net")
    _seed(db_session, supplements=[Supplement(question="q", answer="a", url="u")])
    entry = authed.get("/api/canvas/stack/guidelines/registry").json()[0]
    content = entry["content"]
    content["supplements"][0]["verified"] = True
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json={"content": content}).json() == {"ok": True}
    db_session.expire_all()
    assert Reg.entry(Reg.by_key(db_session, "k@1")).content.supplements[0].verified is True
    bad = {"content": {"branches": [{"name": "B", "state": "nonsense"}]}}
    assert authed.post("/api/canvas/stack/guidelines/registry/k@1", json=bad).status_code == 422


def test_log_accepts_copilot(authed, db_session):
    authed.post("/api/canvas/stack/log", json={"session_id": "s1", "copilot": {"applied": ["k@1"]}})
    authed.post("/api/canvas/stack/log", json={"session_id": "s1", "copilot": None, "report_id": "r"})
    row = db_session.query(DictationStackLog).filter_by(session_id="s1").first()
    db_session.refresh(row)
    assert row.copilot == {"applied": ["k@1"]} and row.report_id == "r"
