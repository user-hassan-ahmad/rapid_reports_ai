import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.hybrid_stack.copilot import conclusion_check as CC
from rapid_reports_ai.main import app

URL = "/api/canvas/stack/guidelines/conclusion_check"


class _Resp:
    def __init__(self, body):
        self._b = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._b


def _body(choice, conf=0.9):
    return {"answers": {"rec": {"choice": choice, "confidence": conf}}}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    CC.clear_cache()
    monkeypatch.delenv("RR_STACK_COPILOT", raising=False)
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)


@pytest.fixture
def authed(client, db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T", is_active=True,
             is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: u
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _mock(monkeypatch, fn):
    calls = []

    async def fake(payload, key, timeout, *a, **k):
        calls.append(payload)
        return await fn(payload)

    monkeypatch.setattr(CC, "jev_post", fake)
    return calls


def _req(authed, cards, conclusion="Follow-up in 6 months."):
    return authed.post(URL, json={"conclusion": conclusion, "cards": cards})


def test_maps_each_option(authed, monkeypatch):
    async def fn(p):
        f = p["state"].split("FINDING:\n")[1]
        return _Resp(_body({"a": "c0", "b": "c1", "c": "c2", "d": "c3"}[f]))
    calls = _mock(monkeypatch, fn)
    r = _req(authed, [{"key": k, "finding": k} for k in "abcd"])
    assert r.status_code == 200
    assert r.json()["results"] == {"a": "none", "b": "surveillance", "c": "workup", "d": "refer"}
    q = calls[0]["questions"]["rec"]
    assert q["instructions"] == "What does the CONCLUSION recommend for the FINDING?"
    assert q["criteria"]["c3"] == "Referral to a specialist team or multidisciplinary meeting for the FINDING."
    assert calls[0]["state"] == "CONCLUSION:\nFollow-up in 6 months.\n\nFINDING:\na"


def test_low_confidence_null(authed, monkeypatch):
    async def fn(p):
        return _Resp(_body("c1", 0.59))
    _mock(monkeypatch, fn)
    assert _req(authed, [{"key": "a", "finding": "x"}]).json()["results"] == {"a": None}


def test_error_is_null_and_not_cached(authed, monkeypatch):
    state = {"fail": True}

    async def fn(p):
        if state["fail"]:
            raise TimeoutError()
        return _Resp(_body("c2"))
    calls = _mock(monkeypatch, fn)
    cards = [{"key": "a", "finding": "x"}]
    assert _req(authed, cards).json()["results"] == {"a": None}
    state["fail"] = False
    assert _req(authed, cards).json()["results"] == {"a": "workup"}
    assert _req(authed, cards).json()["results"] == {"a": "workup"}
    assert len(calls) == 2   # the failure was not cached; the success was


def test_unoffered_choice_null(authed, monkeypatch):
    async def fn(p):
        return _Resp(_body("zz"))
    _mock(monkeypatch, fn)
    assert _req(authed, [{"key": "a", "finding": "x"}]).json()["results"] == {"a": None}


def test_empty_conclusion_no_call(authed, monkeypatch):
    async def fn(p):
        raise AssertionError("no call")
    calls = _mock(monkeypatch, fn)
    r = _req(authed, [{"key": "a", "finding": "x"}], conclusion="  ")
    assert r.json()["results"] == {"a": None} and not calls


def test_too_many_cards_422(authed):
    assert _req(authed, [{"key": str(i), "finding": "x"} for i in range(11)]).status_code == 422


def test_auth_required(client):
    app.dependency_overrides.pop(get_current_user, None)
    assert client.post(URL, json={"conclusion": "c", "cards": []}).status_code in (401, 403)
