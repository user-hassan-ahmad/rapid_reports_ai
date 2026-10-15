import asyncio
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import DictationStackLog, User
from rapid_reports_ai.hybrid_stack.copilot import ask as A
from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot import registry as Reg
from rapid_reports_ai.hybrid_stack.copilot import routes as CR
from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.ask import AskResult
from rapid_reports_ai.hybrid_stack.copilot.recs import RecsResult
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Card, GuidelineContent, Input, Preview, Supplement
from rapid_reports_ai.main import app

pytestmark = pytest.mark.usefixtures("web_fetch_on")   # these tests exercise the web path


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
    monkeypatch.delenv("RR_STACK", raising=False)
    monkeypatch.delenv("RR_STACK_COPILOT", raising=False)
    monkeypatch.setattr(CR, "SessionLocal", sessionmaker(bind=db_engine, autoflush=False, autocommit=False))


@pytest.fixture
def authed(client, user, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _seed(db, key="k@1", branches=None, supplements=None):
    Reg.upsert(db, key=key, name="K", version="1", aliases=[], publication=None,
               content=GuidelineContent(branches=branches or [Branch(name="B", state="checked",
                                                                     inputs=[Input(id="risk", question="Risk")])],
                                        supplements=supplements or []), sources=[], chunks=[])


async def _drain():
    await asyncio.gather(*list(CR._BG), return_exceptions=True)


def test_kill_switch(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK_COPILOT", "0")
    assert authed.post("/api/canvas/stack/guidelines/match", json={"findings": []}).status_code == 404
    assert authed.post("/api/canvas/stack/guidelines/ask", json={"question": "q"}).status_code == 404
    # the UI tells "Copilot off" from an unknown route's 404 by this detail
    assert authed.post("/api/canvas/stack/guidelines/match", json={"findings": []}).json()["detail"] == "copilot_off"
    assert CR.copilot_allowed() is False


def test_off_with_the_stack(monkeypatch):
    assert CR.copilot_allowed({"RR_DICTATION_V2": "1"}) is True
    assert CR.copilot_allowed({"RR_DICTATION_V2": "1", "RR_STACK": "0"}) is False


def test_status_flag(authed, monkeypatch):
    assert authed.get("/api/settings/status").json()["stack_copilot"] is True
    monkeypatch.setenv("RR_STACK_COPILOT", "0")
    assert authed.get("/api/settings/status").json()["stack_copilot"] is False


def test_match_route(authed, monkeypatch):
    seen = {}

    async def fake(db, scan_type, history, findings, dictation=""):
        assert scan_type == "CT" and history == "h"
        seen["dictation"] = dictation
        return [Card(key="k@1", name="K", version="1", finding_id=findings[0].id, branch="B")]

    async def other(*a, **k):
        raise AssertionError("/match must not run the other-guidelines path")
    monkeypatch.setattr(CR, "match", fake)
    monkeypatch.setattr(CR, "match_other", other)
    d = authed.post("/api/canvas/stack/guidelines/match",
                    json={"scan_type": "CT", "clinical_history": "h", "findings": [{"id": "u1", "text": "x"}]}).json()
    assert d["cards"][0]["key"] == "k@1" and d["cards"][0]["finding_id"] == "u1"
    assert seen["dictation"] == "x"   # no dictation sent: the joined finding texts
    authed.post("/api/canvas/stack/guidelines/match",
                json={"scan_type": "CT", "clinical_history": "h", "findings": [{"id": "u1", "text": "x"}],
                      "dictation": "x. Rest normal."})
    assert seen["dictation"] == "x. Rest normal."


def test_match_other_route_calls_the_old_path_without_prewarm(authed, monkeypatch):
    async def other(db, scan_type, history, findings):
        assert scan_type == "CT" and history == "h"
        return [Card(key="k@1", name="K", version="1", finding_id=findings[0].id, branch="B")]

    async def lib_match(*a, **k):
        raise AssertionError("/match/other must not run the library path")

    def no_prewarm(*a, **k):
        raise AssertionError("/match/other does not prewarm")
    monkeypatch.setattr(CR, "match_other", other)
    monkeypatch.setattr(CR, "match", lib_match)
    monkeypatch.setattr(CR, "_prewarm", no_prewarm)
    d = authed.post("/api/canvas/stack/guidelines/match/other",
                    json={"scan_type": "CT", "clinical_history": "h", "findings": [{"id": "u1", "text": "x"}]}).json()
    assert [(c["key"], c["finding_id"]) for c in d["cards"]] == [("k@1", "u1")]


def test_match_other_route_is_gated_by_the_flag(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK_COPILOT", "0")
    assert authed.post("/api/canvas/stack/guidelines/match/other", json={"findings": []}).status_code == 404


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
        "findings": "x", "clinical_history": "", "answered": {"risk": "High", "bogus": "x"}}).json()
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
        "card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1"}, "findings": "x"}).json()
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
        "card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1", "branch": "B"}, "findings": "x"}).json()
    assert d["entry"]["key"] == "k@1" and d["preview"] == {"settled": [], "draft": [], "draft_outcome": None, "assumptions": [], "assumed_eligible": False, "exclusion_reason": None, "most_likely": None, "deciding_input": None, "deciding": [], "candidates": [], "scope_doubt": [], "missing": [], "waiting": [], "proposal": None, "possible": [], "bounded": True, "asks": [], "trace": None, "degraded": False,
                                                              "state": "applies", "exclusion": None}


async def test_open_timeout_keeps_the_fetch_going(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "OPEN_TIMEOUT_S", 0.05)

    async def resolve(db, card):
        await asyncio.sleep(0.2)
        _seed(db)
        return Reg.entry(Reg.by_key(db, "k@1"))
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    req = CR.OpenRequest(card=CR.CardIn(key="k@1", name="K", version="1", finding_id="u1", branch="B"), findings="x")
    out = await CR.copilot_open(req, user)
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

    async def fake(db, question, key, ctx, history, finding_id="", abandoned=None):
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

    async def fake(db, question, key, ctx, history, finding_id="", abandoned=None):
        order.append(("ask", Reg.by_key(db, key) is not None))
        return AskResult(kind="card", key=key, answer="a")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "ask", fake)
    card = {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1"}
    authed.post("/api/canvas/stack/guidelines/ask", json={"question": "why", "key": "k@1", "card": card})
    assert order == [("resolve", "k@1"), ("ask", True)]
    order.clear()
    authed.post("/api/canvas/stack/guidelines/ask", json={"question": "why", "key": "k@1", "card": card})
    assert order == [("ask", True)]   # a held key is asked directly


async def test_ask_timeout_answers_generally_and_keeps_resolving(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "ASK_TIMEOUT_S", 0.05)
    done = []

    async def fake(db, question, key, ctx, history, finding_id="", abandoned=None):
        await asyncio.sleep(0.2)
        _seed(db)
        done.append(True)
        return AskResult(kind="card", key="k@1", answer="late")

    async def general(question, ctx, history):
        return "Usually so."
    monkeypatch.setattr(CR, "ask", fake)
    monkeypatch.setattr(A, "_general_answer", general)
    out = await CR.copilot_ask(CR.AskRequest(question="why"), user)
    assert out.kind == "general" and out.loading and not out.supported
    assert out.answer == f"{CR.STILL_LOADING} {A.FROM_GENERAL} Usually so."
    await _drain()
    assert done == [True] and Reg.by_key(db_session, "k@1") is not None


async def test_ask_timeout_general_failure_still_says_loading(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "ASK_TIMEOUT_S", 0.01)

    async def fake(db, question, key, ctx, history, finding_id="", abandoned=None):
        await asyncio.sleep(0.05)
        return AskResult(kind="general", answer="late")

    async def general(question, ctx, history):
        raise TimeoutError
    monkeypatch.setattr(CR, "ask", fake)
    monkeypatch.setattr(A, "_general_answer", general)
    out = await CR.copilot_ask(CR.AskRequest(question="why", key="k@1"), user)
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


def _stub_preview(monkeypatch):
    async def prev(entry, branch, findings, history, answered):
        return Preview()
    monkeypatch.setattr(CR, "preview", prev)


def test_supplements_never_leave_for_non_reviewers(authed, db_session, monkeypatch):
    monkeypatch.setenv("RR_STACK_REVIEWERS", "rad@nhs.net")
    _seed(db_session, supplements=[Supplement(question="phrase", url="https://s")])

    async def resolve(db, card):
        return Reg.entry(Reg.by_key(db, "k@1"))

    async def fake(db, question, key, ctx, history, finding_id="", abandoned=None):
        return AskResult(kind="card", key=key, answer="a", entry=Reg.entry(Reg.by_key(db, key)))
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "ask", fake)
    _stub_preview(monkeypatch)
    card = {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1", "branch": "B"}
    for path in ("open", "preview"):
        d = authed.post(f"/api/canvas/stack/guidelines/{path}", json={"card": card, "findings": "x"}).json()
        assert d["entry"]["content"]["supplements"] == []
    d = authed.post("/api/canvas/stack/guidelines/ask", json={"question": "q", "key": "k@1"}).json()
    assert d["entry"]["content"]["supplements"] == []
    listed = authed.get("/api/canvas/stack/guidelines/registry").json()[0]
    assert listed["content"]["supplements"][0]["question"] == "phrase" and "chunks" not in listed
    one = authed.get("/api/canvas/stack/guidelines/registry/k@1").json()
    assert one["chunks"] == [] and one["content"]["supplements"][0]["url"] == "https://s"
    assert authed.get("/api/canvas/stack/guidelines/registry/nope@1").status_code == 404


def test_ask_ignores_a_card_for_another_key(authed, monkeypatch):
    async def resolve(db, card):
        raise AssertionError("never resolved")

    async def fake(db, question, key, ctx, history, finding_id="", abandoned=None):
        return AskResult(kind="general", key=key, answer="a")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(CR, "ask", fake)
    card = {"key": "other@1", "name": "Other", "version": "1", "finding_id": "u1"}
    for body in ({"question": "q", "key": "k@1", "card": card}, {"question": "q", "card": card}):
        assert authed.post("/api/canvas/stack/guidelines/ask", json=body).json()["answer"] == "a"


@pytest.mark.parametrize("card,code", [
    ({"key": "K@1", "name": "K", "version": "1"}, 400),                       # not a slug
    ({"key": "k@1/../x", "name": "K", "version": "1"}, 400),
    ({"key": "anything@1", "name": "K", "version": "1"}, 400),                # not its name's key, not held
    ({"key": "k@1", "name": "K" * 121, "version": "1"}, 422),
    ({"key": "k@1", "name": "K", "version": "1" * 25}, 422),
    ({"key": "k@1", "name": "K", "version": "1", "skeleton": ["s"] * 13}, 422),
    ({"key": "k@1", "name": "K", "version": "1", "why": "w" * 301}, 422),
    ({"key": "k@1", "name": "K", "version": "1", "publication": {"title": "t" * 301}}, 422),
    ({"key": "k@1", "name": "K", "version": "1", "publication": {"year": "123456789"}}, 422),
])
def test_open_validates_the_client_card(authed, monkeypatch, card, code):
    async def resolve(db, card):
        raise AssertionError("never resolved")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    r = authed.post("/api/canvas/stack/guidelines/open", json={"card": {"finding_id": "u1", **card}, "findings": "x"})
    assert r.status_code == code


def test_open_accepts_a_held_key_and_tnm(authed, db_session, monkeypatch):
    _seed(db_session, key="held@2")   # held under a key its name would not make: still openable

    async def resolve(db, card):
        return Reg.entry(Reg.by_key(db, card.key))
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    _stub_preview(monkeypatch)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "held@2", "name": "Something else", "finding_id": "u1"}, "findings": "x"}).json()
    assert d["entry"]["key"] == "held@2"


@pytest.mark.parametrize("path,body", [
    ("open", {"card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1"},
              "answered": {f"i{n}": "v" for n in range(21)}}),
    ("open", {"card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1"}, "answered": {"i": "v" * 201}}),
    ("open", {"card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1"}, "answered": {"i" * 61: "v"}}),
    ("open", {"card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "f" * 41}}),
    ("ask", {"question": "q" * 1001}),
    ("ask", {"question": "q", "history": [{"question": "q", "answer": "a"}] * 7}),
    ("ask", {"question": "q", "history": [{"question": "q" * 2001, "answer": "a"}]}),
    ("match", {"findings": [{"id": "u", "text": "t" * 1001}]}),
    ("match", {"findings": [{"id": "u" * 41, "text": "t"}]}),
    ("match", {"findings": [{"id": f"u{n}", "text": "t"} for n in range(21)]}),
    ("recommendations", {"applied": ["a"] * 11}),
    ("recommendations", {"applied": ["a" * 301]}),
])
def test_request_caps_reject(authed, path, body):
    assert authed.post(f"/api/canvas/stack/guidelines/{path}", json=body).status_code == 422


async def test_preview_is_bounded_and_fails_open(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "PREVIEW_TIMEOUT_S", 0.05)
    _seed(db_session, branches=[Branch(name="Overview", state="checked"), Branch(name="B", state="checked")])

    async def pick(finding, entry, history=""):
        await asyncio.sleep(1)
    monkeypatch.setattr(CR.M, "pick_branch", pick)
    req = CR.OpenRequest(card=CR.CardIn(key="k@1", name="K", version="1", finding_id="q"), findings="x")
    out = await CR.copilot_preview(req, user, db_session)
    assert out.branch == "Overview" and out.preview == Preview() and out.entry.key == "k@1"


async def test_ask_timeout_abandons_the_rest_of_the_job(db_session, user, monkeypatch):
    monkeypatch.setattr(CR, "ASK_TIMEOUT_S", 0.05)
    seen = []

    async def fake(db, question, key, ctx, history, finding_id="", abandoned=None):
        await asyncio.sleep(0.2)
        seen.append(abandoned.is_set())
        return AskResult(kind="card", key=key, answer="late")

    async def general(question, ctx, history):
        return "G."
    monkeypatch.setattr(CR, "ask", fake)
    monkeypatch.setattr(A, "_general_answer", general)
    out = await CR.copilot_ask(CR.AskRequest(question="q", key="k@1"), user)
    assert out.loading and out.kind == "card"   # a scoped ask stays filed under its card
    await _drain()
    assert seen == [True]


def test_open_resolve_crash_fails_open(authed, monkeypatch):
    async def resolve(db, card):
        raise RuntimeError("boom")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1"}, "findings": "x"}).json()
    assert d["error"] == "unavailable"


def test_log_rejects_an_oversized_copilot_record(authed):
    big = {"threads": ["x" * 70000]}
    assert authed.post("/api/canvas/stack/log", json={"session_id": "s9", "copilot": big}).status_code == 413


from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP

TOY_SOURCES = [{"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY", "edition": "2020",
                "url": "https://example.org/toy"}]


@pytest.fixture
def toy_lib(monkeypatch, toy):
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def resolve(db, card):
        raise AssertionError("a pack is never fetched")

    async def call(system, prompt):
        return PP.RawSettle(settled=[PP.RawItem(input="kind", value="solid", quote="solid"),
                                     PP.RawItem(input="size", value=7, quote="7 mm")])
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(PP, "_call", call)

    class _JevResp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    async def jev(payload, key, timeout, transport=None):
        return _JevResp({"answers": {k: {"noul": 0.9} for k in payload["questions"]}})
    monkeypatch.setattr(P, "jev_post", jev)
    return lib


PACK_CARD = {"key": "toy-nodule@1.0", "name": "Toy 2020", "version": "2020", "finding_id": "u1", "branch": "Pack"}


def test_open_a_library_pack(authed, toy_lib):
    d = authed.post("/api/canvas/stack/guidelines/open", json={      # the card carries its own finding from /match
        "card": {**PACK_CARD, "finding": "7 mm solid nodule."}, "findings": "7 mm solid nodule.",
        "answered": {"risk": "high"}}).json()
    assert d["error"] is None and d["entry"]["key"] == "toy-nodule@1.0" and d["branch"] == "Pack"
    assert d["preview"]["draft_outcome"]["recommendation"] == "CT at 6 months"
    assert d["entry"]["sources"][0]["url"] == "https://example.org/toy"


def test_preview_a_library_pack(authed, toy_lib):
    d = authed.post("/api/canvas/stack/guidelines/preview", json={
        "card": PACK_CARD, "finding": "7 mm solid nodule.", "findings": "7 mm solid nodule.", "answered": {}}).json()
    assert d["preview"]["missing"] == ["risk"] and len(d["preview"]["possible"]) == 2


def test_open_settles_lesion_inputs_from_the_cards_own_finding(authed, toy_lib, monkeypatch):
    async def call(system, prompt):
        return PP.RawSettle(settled=[PP.RawItem(input="kind", value="solid", quote="solid"),
                                     PP.RawItem(input="size", value=12, quote="12 mm granuloma")])
    monkeypatch.setattr(PP, "_call", call)
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "finding": "7 mm solid nodule.", "findings": "7 mm solid nodule. 12 mm granuloma.",
        "answered": {}}).json()
    assert "size" in d["preview"]["missing"] and d["preview"]["settled"][0]["input"] == "kind"


def test_open_passes_the_patient_map_and_rejects_unknown_facts(authed, toy_lib, monkeypatch):
    seen = {}

    def fake_finish(e, s, answered, patient=None, sources=None, presets=None):
        seen["patient"] = patient
        return Preview()
    monkeypatch.setattr(CR, "finish", fake_finish)
    ok = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "findings": "x", "patient": {"age_years": "60"}})
    assert ok.status_code == 200 and seen["patient"] == {"age_years": "60"}
    bad = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "findings": "x", "patient": {"shoe_size": "9"}})
    assert bad.status_code == 422


def test_only_an_exam_card_gets_its_packs_exam_presets(authed, monkeypatch):
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "guidelines" / "nhs-aaa-surveillance" / "entry.json"
    import json as _json
    both = {**_json.loads(src.read_text()), "trigger": ["exam", "finding"]}     # a toy: both triggers, with presets
    lib = L.Library({"version": "v1", "entries": {"nhs-aaa-surveillance@2025.1": {"entry": both,
                                                                                   "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def fake_settle(e, findings, history, finding=""):
        return PP.Settlement(values={"diameter_cm": PP.Drafted(PP.InputValue(value=2.4), "Aorta 2.4 cm", "read")})
    monkeypatch.setattr(CR, "settle_pack", fake_settle)
    dictation = "Aorta 2.4 cm."
    card = {"key": "nhs-aaa-surveillance@2025.1", "name": "NHS AAA Screening 2025", "version": "2025",
            "branch": "Pack", "finding": dictation}
    exam = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": {**card, "finding_id": "exam"}, "findings": dictation}).json()["preview"]
    assert {s["input"]: s["by"] for s in exam["settled"]} == {
        "screening_programme": "exam", "sex": "exam", "previous_aaa_treatment": "exam", "diameter_cm": ""}
    assert exam["missing"] == ["prior_programme_scan"]
    found = authed.post("/api/canvas/stack/guidelines/preview", json={
        "card": {**card, "finding_id": "u1"}, "findings": dictation}).json()["preview"]
    assert [s["input"] for s in found["settled"]] == ["diameter_cm"] and found["state"] == "check_first"


async def test_match_starts_pack_previews_and_open_reuses_them(db_session, user, monkeypatch, toy):
    from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    card = Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id="u1", branch="Pack")

    async def fake_match(db, scan, history, findings, dictation=""):
        return [card]
    calls = []

    async def fake_settle(e, findings, history, finding=""):
        calls.append((finding, findings))
        return PP.Settlement(values={"kind": PP.Drafted(PP.InputValue(value="solid"), "solid", "read"),
                                     "size": PP.Drafted(PP.InputValue(value=7.0), "7 mm", "read")})
    monkeypatch.setattr(CR, "match", fake_match)
    monkeypatch.setattr(CR, "settle_pack", fake_settle)
    dictation = "7 mm solid nodule. Liver normal."
    await CR.copilot_match(CR.MatchRequest(scan_type="CT", findings=[CR.FindingIn(id="u1", text="7 mm solid nodule.")],
                                           dictation=dictation, patient={"age_years": "60"}),
                           user=user, db=db_session)
    await asyncio.gather(*list(PC._RUNNING))
    out = await CR.copilot_open(CR.OpenRequest(card=CR.CardIn(**PACK_CARD), finding="7 mm solid nodule.",
                                               findings=dictation, patient={"age_years": "60"}), user=user)
    assert out.preview.missing == ["risk"]
    assert calls == [("7 mm solid nodule.", dictation)]                         # computed once, at match time
    again = await CR.copilot_preview(CR.OpenRequest(card=CR.CardIn(**PACK_CARD), finding="7 mm solid nodule.",
                                                    findings=dictation, answered={"risk": "low"},
                                                    patient={"age_years": "60"}), user=user, db=db_session)
    assert again.preview.missing == [] and again.preview.draft_outcome.recommendation == "CT at 12 months"
    assert len(calls) == 1                                                       # an answer re-runs the engine only
    assert [(x.input, x.value) for x in again.preview.settled][:2] == [("kind", "solid"), ("size", "7 mm")]


def test_a_reference_card_opens_read_only_and_is_never_fetched(authed, monkeypatch, toy_reference):
    lib = L.Library({"version": "v1", "entries": {"toy-grade@1.0": {"entry": toy_reference, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def resolve(db, card):
        raise AssertionError("never fetched")

    async def call(system, prompt):
        raise AssertionError("a reference card is never previewed")
    monkeypatch.setattr(CR, "resolve_guideline", resolve)
    monkeypatch.setattr(PP, "_call", call)
    card = {"key": "toy-grade@1.0", "name": "Toy grade 2020", "version": "2020", "finding_id": "u1",
            "branch": "Reference"}
    for path in ("open", "preview"):
        d = authed.post(f"/api/canvas/stack/guidelines/{path}", json={"card": card, "findings": "grade 2."}).json()
        assert d["error"] is None and d["preview"] is None and d["branch"] == "Reference"
        assert d["entry"]["content"]["branches"][0]["name"] == "Reference"
        assert d["reference"]["tables"][0]["rows"][1] == ["2", "partial-thickness defect"]
        assert d["reference"]["tables"][0]["citation"]["page"] == 2


def test_a_pack_open_carries_its_reference_fields(authed, toy_lib):
    d = authed.post("/api/canvas/stack/guidelines/open", json={"card": PACK_CARD, "findings": "7 mm solid nodule."}).json()
    assert d["reference"]["summary"][0]["id"] == "sum.1"


def test_a_pack_open_with_no_finding_asks_lesion_inputs_and_says_degraded(authed, toy_lib):
    d = authed.post("/api/canvas/stack/guidelines/open", json={
        "card": PACK_CARD, "findings": "7 mm solid nodule.", "answered": {"risk": "high"}}).json()
    assert d["preview"]["draft_outcome"] is None and "kind" in d["preview"]["missing"] and d["preview"]["degraded"] is True


def test_a_failed_pack_preview_is_check_first_when_the_pack_has_eligibility(authed, monkeypatch, toy):
    from tests.test_library_verify import _eligible_toy
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": _eligible_toy(toy),
                                                                      "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(CR, "settle_pack", boom)
    d = authed.post("/api/canvas/stack/guidelines/open", json={"card": PACK_CARD, "findings": "x"}).json()
    assert d["preview"]["state"] == "check_first" and d["preview"]["degraded"] is True


def test_a_failed_pack_preview_applies_when_the_pack_has_no_eligibility(authed, toy_lib, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(CR, "settle_pack", boom)
    d = authed.post("/api/canvas/stack/guidelines/open", json={"card": PACK_CARD, "findings": "x"}).json()
    assert d["preview"]["state"] == "applies" and d["preview"]["degraded"] is True


async def test_match_fails_open_when_the_library_cannot_be_read(db_session, user, monkeypatch):
    card = Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id="u1", branch="Pack")

    async def fake_match(db, scan, history, findings, dictation=""):
        return [card]

    def broken():
        raise RuntimeError("bundle unreadable")
    monkeypatch.setattr(CR, "match", fake_match)
    monkeypatch.setattr(L, "get", broken)
    out = await CR.copilot_match(CR.MatchRequest(scan_type="CT", findings=[CR.FindingIn(id="u1", text="7 mm.")]),
                                 user=user, db=db_session)
    assert [c.key for c in out.cards] == ["toy-nodule@1.0"]


def test_prewarm_skips_over_the_cap(monkeypatch, toy):
    from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    monkeypatch.setattr(PC, "PREWARM_MAX", 1)

    async def go():
        async def slow(*a, **k):
            await asyncio.sleep(0.05)
            return PP.Settlement()
        monkeypatch.setattr(CR, "settle_pack", slow)
        cards = [Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id=f"u{n}", branch="Pack")
                 for n in range(3)]
        req = CR.MatchRequest(findings=[CR.FindingIn(id=f"u{n}", text=f"{n + 5} mm nodule.") for n in range(3)])
        n = CR._prewarm(req, cards)
        await asyncio.gather(*list(PC._RUNNING))
        return n
    assert asyncio.run(go()) == 1


def test_a_pack_preview_timeout_says_degraded(authed, toy_lib, monkeypatch):
    monkeypatch.setattr(CR, "PREVIEW_TIMEOUT_S", 0.01)

    async def slow(*a, **k):
        await asyncio.sleep(1)
        return PP.Settlement()
    monkeypatch.setattr(CR, "settle_pack", slow)
    d = authed.post("/api/canvas/stack/guidelines/open", json={"card": PACK_CARD, "findings": "x"}).json()
    assert d["preview"]["degraded"] is True and d["preview"]["state"] == "applies"


async def test_an_answer_after_open_calls_neither_the_model_nor_jev(db_session, user, toy_lib, monkeypatch):
    """Lab fix round item 5: /open reads the dictation once; /preview with answers re-runs only the engine."""
    body = {"card": CR.CardIn(**PACK_CARD), "finding": "7 mm solid nodule.", "findings": "7 mm solid nodule.",
            "clinical_history": "Smoker."}
    first = (await CR.copilot_open(CR.OpenRequest(**body), user=user)).preview

    async def no_call(*a, **k):
        raise AssertionError("an answer never calls the model or Jev")
    monkeypatch.setattr(PP, "_call", no_call)
    monkeypatch.setattr(P, "jev_post", no_call)
    for answered in ({"risk": "low"}, {"risk": "high"}):
        d = (await CR.copilot_preview(CR.OpenRequest(**body, answered=answered), user=user, db=db_session)).preview
        assert d.degraded is False and d.proposal is None and d.draft_outcome is not None
        assert [x for x in d.settled if x.input != "risk"] == first.settled


@pytest.mark.parametrize("failure", ["model", "jev"])
async def test_after_a_failed_settle_answers_make_no_model_call(db_session, user, toy_lib, monkeypatch, failure):
    """Review I3: a failed settlement is cached; answers re-run only the engine over whatever settled. A fresh
    /open retries it once."""
    calls = []

    async def call(system, prompt):
        calls.append("model")
        if failure == "model":
            raise TimeoutError("slow")
        return PP.RawSettle(settled=[PP.RawItem(input="kind", value="solid", quote="solid")])

    async def jev(payload, key, timeout, transport=None):
        calls.append("jev")
        raise TimeoutError("jev slow")
    monkeypatch.setattr(PP, "_call", call)
    if failure == "jev":
        monkeypatch.setattr(P, "jev_post", jev)
    body = {"card": CR.CardIn(**PACK_CARD), "finding": "7 mm solid nodule.", "findings": "7 mm solid nodule."}
    first = (await CR.copilot_open(CR.OpenRequest(**body), user=user)).preview
    assert first.degraded is True and calls
    n = len(calls)
    for answered in ({"risk": "low"}, {"risk": "high"}, {"risk": "high", "kind": "solid"}):
        d = (await CR.copilot_preview(CR.OpenRequest(**body, answered=answered), user=user, db=db_session)).preview
        assert d.degraded is True
    assert len(calls) == n                                              # no model or Jev call on any answer
    await CR.copilot_open(CR.OpenRequest(**body), user=user)            # a fresh open retries once
    m = len(calls)
    assert m > n
    await CR.copilot_open(CR.OpenRequest(**body), user=user)
    await CR.copilot_preview(CR.OpenRequest(**body, answered={"risk": "low"}), user=user, db=db_session)
    assert len(calls) == m                                              # and then the result is kept


def test_a_long_exam_card_from_match_opens_and_is_asked_about(authed, toy_lib, toy, monkeypatch):
    """An exam card carries the whole dictation as its finding: /open and /ask accept it past 1000 chars."""
    import copy

    from rapid_reports_ai.hybrid_stack.copilot import library_match as LM
    from rapid_reports_ai.hybrid_stack.copilot import matcher as M
    M.clear_cache()
    d = copy.deepcopy(toy)
    d.update(trigger=["exam"], exam="a toy study")
    lib = L.Library({"version": "v2", "entries": {"toy-nodule@1.0": {"entry": d, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    class _R:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    async def jev(payload, key, timeout, transport=None):
        qs = payload["questions"]
        if "modality" in qs:
            return _R({"answers": {"modality": {"choice": "CT", "confidence": 0.9}, "x_0": {"noul": 0.95}}})
        return _R({"answers": {"tnm": {"noul": 0.0}, "site": {"choice": "none", "confidence": 0.9}}})
    monkeypatch.setattr(LM, "jev_post", jev)
    dictation = "7 mm solid nodule. " + "Liver normal. " * 120
    assert len(dictation) > 1000
    cards = authed.post("/api/canvas/stack/guidelines/match", json={
        "scan_type": "CT", "findings": [{"id": "u1", "text": "7 mm solid nodule."}], "dictation": dictation}).json()["cards"]
    assert [(c["key"], c["finding_id"]) for c in cards] == [("toy-nodule@1.0", "exam")]
    card = cards[0]
    assert card["finding"] == dictation
    r = authed.post("/api/canvas/stack/guidelines/open", json={"card": card, "finding": card["finding"],
                                                                "findings": dictation})
    assert r.status_code == 200 and r.json()["entry"]["key"] == "toy-nodule@1.0"

    async def fake_ask(db, question, key, ctx, history, finding_id="", abandoned=None):
        return AskResult(kind="card", key=key, answer="a")
    monkeypatch.setattr(CR, "ask", fake_ask)
    r = authed.post("/api/canvas/stack/guidelines/ask", json={"question": "why", "key": card["key"], "card": card,
                                                               "findings": dictation})
    assert r.status_code == 200
    M.clear_cache()


def test_a_needs_modality_card_opens_read_only_and_is_never_settled(authed, toy_lib, monkeypatch):
    async def settle(*a, **k):
        raise AssertionError("a card that needs another modality is never settled")
    monkeypatch.setattr(CR, "settle_pack", settle)
    card = {**PACK_CARD, "finding": "7 mm solid nodule.", "needs_modality": "US"}
    for path in ("open", "preview"):
        d = authed.post(f"/api/canvas/stack/guidelines/{path}", json={
            "card": card, "findings": "7 mm solid nodule.", "answered": {"risk": "high"}}).json()
        assert d["error"] is None and d["preview"] is None and d["needs_modality"] == "US"
        assert d["branch"] == "Pack" and d["entry"]["key"] == "toy-nodule@1.0"
        assert d["reference"]["summary"][0]["id"] == "sum.1"


def test_prewarm_skips_a_needs_modality_card(monkeypatch, toy):
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def settle(*a, **k):
        raise AssertionError("never prewarmed")
    monkeypatch.setattr(CR, "settle_pack", settle)
    card = Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id="u1", branch="Pack",
                needs_modality="US")
    req = CR.MatchRequest(findings=[CR.FindingIn(id="u1", text="7 mm nodule.")])
    assert CR._prewarm(req, [card]) == 0


def test_prewarm_starts_the_tier_1_siblings_too(monkeypatch, toy):
    sib = {**toy, "id": "toy-sib", "display": "Sib 2021"}
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES},
                                                   "toy-sib@1.0": {"entry": sib, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    started = []

    async def settle(e, *a, **k):
        started.append(e.key)
        return PP.Settlement()
    monkeypatch.setattr(CR, "settle_pack", settle)

    async def go():
        from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
        card = Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id="u1", branch="Pack",
                    siblings=["toy-sib@1.0", "gone@9"])
        n = CR._prewarm(CR.MatchRequest(findings=[CR.FindingIn(id="u1", text="7 mm nodule.")]), [card])
        await asyncio.gather(*list(PC._RUNNING))
        return n
    assert asyncio.run(go()) == 2 and sorted(started) == ["toy-nodule@1.0", "toy-sib@1.0"]


def test_pack_cards_carry_their_siblings_display_names(toy):
    from rapid_reports_ai.hybrid_stack.copilot import matcher as MM
    sib = {**toy, "id": "toy-sib", "display": "Sib 2021"}
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES},
                                                   "toy-sib@1.0": {"entry": sib, "sources": TOY_SOURCES}}})
    c = MM._pack_card(lib, lib.lookup("toy-nodule@1.0"), "u1", "7 mm nodule.")
    assert c.siblings == ["toy-sib@1.0"] and c.sibling_names == ["Sib 2021"]


def test_prewarm_starts_every_primary_before_any_sibling(monkeypatch, toy):
    from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
    sib = {**toy, "id": "toy-sib", "display": "Sib 2021"}
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": TOY_SOURCES},
                                                   "toy-sib@1.0": {"entry": sib, "sources": TOY_SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    monkeypatch.setattr(PC, "PREWARM_MAX", 2)
    started = []

    async def go():
        async def slow(e, *a, **k):
            started.append(e.key)
            await asyncio.sleep(0.05)
            return PP.Settlement()
        monkeypatch.setattr(CR, "settle_pack", slow)
        cards = [Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id=f"u{n}", branch="Pack",
                      siblings=["toy-sib@1.0"]) for n in range(2)]
        req = CR.MatchRequest(findings=[CR.FindingIn(id=f"u{n}", text=f"{n + 5} mm nodule.") for n in range(2)])
        n = CR._prewarm(req, cards)
        await asyncio.gather(*list(PC._RUNNING))
        return n
    assert asyncio.run(go()) == 2 and started == ["toy-nodule@1.0", "toy-nodule@1.0"]   # both primaries, no sibling


# ── Calculate (spec §7.7, §7.10): the engine over exactly the values the card shows; never a model or Jev call ──────

def _calc_settle(calls):
    async def settle(e, findings, history, finding=""):
        calls.append(finding)
        return PP.Settlement(values={"kind": PP.Drafted(PP.InputValue(value="solid"), "solid", "read"),
                                     "size": PP.Drafted(PP.InputValue(value=7.0), "7 mm", "read"),
                                     "risk": PP.Drafted(PP.InputValue(value="high"), "smoker", "prefilled",
                                                        [PP.WHY_NOT_OPTION_WORD])})
    return settle


async def test_calculate_uses_the_values_sent_and_the_cached_settlement_only_labels_them(user, toy_lib, monkeypatch):
    calls = []
    monkeypatch.setattr(CR, "settle_pack", _calc_settle(calls))
    body = {"card": CR.CardIn(**PACK_CARD), "finding": "7 mm solid nodule.", "findings": "7 mm solid nodule.",
            "clinical_history": "Smoker."}
    opened = (await CR.copilot_open(CR.OpenRequest(**body), user=user)).preview
    assert opened.proposal is None and opened.draft_outcome.recommendation == "CT at 6 months" and calls == ["7 mm solid nodule."]

    async def no_call(*a, **k):
        raise AssertionError("Calculate never calls the model or Jev")
    monkeypatch.setattr(CR, "settle_pack", no_call)
    monkeypatch.setattr(PP, "_call", no_call)
    monkeypatch.setattr(P, "jev_post", no_call)
    part = await CR.copilot_calculate(CR.CalculateRequest(**body, values={"kind": "solid", "size": "7 mm"}), user=user)
    assert part.error is None and part.calculation.result is None and part.calculation.needed == ["risk"]
    full = await CR.copilot_calculate(CR.CalculateRequest(**body, values={"kind": "solid", "size": "7 mm",
                                                                            "risk": "high"}), user=user)
    c = full.calculation
    assert c.result.recommendation == "CT at 6 months" and c.outcome == "ct6" and c.bundle == "v1"
    assert c.pack == "toy-nodule@1.0" and {v.input: v.state for v in c.values} == {
        "kind": "read", "size": "read", "risk": "prefilled", "margin": "asked"}


async def test_calculate_on_a_cold_cache_starts_no_settle_and_labels_the_values_answered(user, toy_lib, monkeypatch):
    async def no_call(*a, **k):
        raise AssertionError("Calculate never starts a settle")
    monkeypatch.setattr(CR, "settle_pack", no_call)
    req = CR.CalculateRequest(card=CR.CardIn(**PACK_CARD), finding="7 mm solid nodule.", findings="7 mm solid nodule.",
                              values={"kind": "solid", "size": "7 mm", "risk": "low"})
    c = (await CR.copilot_calculate(req, user=user)).calculation
    assert c.outcome == "ct12" and {v.input: v.state for v in c.values if v.input != "margin"} == dict.fromkeys(
        ("kind", "size", "risk"), "answered")


def test_calculate_refuses_a_needs_modality_card_and_a_non_pack(authed, toy_lib, monkeypatch):
    async def settle(*a, **k):
        raise AssertionError("never settled")
    monkeypatch.setattr(CR, "settle_pack", settle)
    url = "/api/canvas/stack/guidelines/calculate"
    d = authed.post(url, json={"card": {**PACK_CARD, "needs_modality": "US"}, "values": {"kind": "solid"}}).json()
    assert d["calculation"] is None and d["error"] == "needs modality"
    d = authed.post(url, json={"card": {**PACK_CARD, "key": "k@1"}, "values": {}}).json()
    assert d["calculation"] is None and d["error"] == "not a pack"
    bad = authed.post(url, json={"card": PACK_CARD, "values": {f"i{n}": "x" for n in range(41)}})
    assert bad.status_code == 422


async def test_calculate_never_waits_on_a_settle_still_running(user, toy_lib, monkeypatch):
    from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return PP.Settlement()
    finding = "7 mm solid nodule."
    PC.start(PC.key("toy-nodule@1.0", finding, finding, ""), slow, prewarm=True)
    req = CR.CalculateRequest(card=CR.CardIn(**PACK_CARD), finding=finding, findings=finding,
                              values={"kind": "solid", "size": "7 mm", "risk": "low"})
    c = (await asyncio.wait_for(CR.copilot_calculate(req, user=user), 1.0)).calculation
    assert c.outcome == "ct12" and {v.input: v.state for v in c.values}["kind"] == "answered"
    gate.set()
    await asyncio.gather(*list(PC._RUNNING))
