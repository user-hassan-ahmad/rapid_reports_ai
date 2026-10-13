"""The runtime web path (registry cards, targeted fetch, gap search) is behind RR_COPILOT_WEB_FETCH, default off
(library spec §2.9, §5). With it off, the Copilot offers library packs and TNM only; a pack is never resolved,
fetched or stored through the registry, whatever the flag, and Ask on a pack answers from the pack alone."""
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.hybrid_stack.copilot import ask as A
from rapid_reports_ai.hybrid_stack.copilot import fetch as F
from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot import routes as CR
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Card, GuidelineContent, Input
from rapid_reports_ai.main import app

CTX = A.Context(scan_type="CT chest", history="", findings="7 mm solid nodule.")
SOURCES = [{"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY", "edition": "2020",
            "url": "https://example.org/toy"}]


@pytest.fixture(autouse=True)
def _off(monkeypatch):
    monkeypatch.delenv("RR_COPILOT_WEB_FETCH", raising=False)
    M.clear_cache()
    yield
    M.clear_cache()


@pytest.fixture
def toy_lib(monkeypatch, toy):
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": SOURCES}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    return lib


def _no_web(monkeypatch, *mods):
    async def boom(*a, **k):
        raise AssertionError("no web path with the flag off")
    for m in mods:
        if hasattr(m, "resolve_guideline"):
            monkeypatch.setattr(m, "resolve_guideline", boom)
    monkeypatch.setattr(F, "_fetch_branch", boom)
    monkeypatch.setattr(A.S, "gather", boom)
    monkeypatch.setattr(A, "_search_phrase", boom)


def _seed(db, key="other@1"):
    R.upsert(db, key=key, name="Other", version="1", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="B", state="checked",
                                                       inputs=[Input(id="risk", question="Risk")])]),
             sources=[], chunks=[])


def test_the_flag_defaults_off():
    assert R.web_fetch_on({}) is False
    assert R.web_fetch_on({"RR_COPILOT_WEB_FETCH": "1"}) is True
    assert R.web_fetch_on({"RR_COPILOT_WEB_FETCH": "0"}) is False


async def test_matcher_offers_no_registry_or_new_key_card_outside_the_library(db_session, monkeypatch, caplog):
    _seed(db_session, key="other@1")
    seen = {}

    async def call(prompt):
        seen["prompt"] = prompt
        return M.RawMatch(findings=[M.RawFinding(id="u1", systems=[
            M.RawSystem(name="Other", version="1"), M.RawSystem(name="Brand New Score", version="3")])])
    monkeypatch.setattr(M, "_call", call)
    caplog.set_level("INFO")
    cards = await M.match_other(db_session, "CT", "", [M.Finding(id="u1", text="a finding")])
    assert cards == []
    assert "other@1" not in seen["prompt"]                     # registry rows are not offered as known systems
    assert "Brand New Score" in caplog.text                     # the name is logged as demand


async def test_card_for_outside_the_library_is_none(db_session):
    _seed(db_session, key="other@1")
    assert await M.card_for(db_session, "Other", "1", "q", "x", gate=False) is None


async def test_ask_on_a_pack_card_answers_from_the_pack_only(db_session, monkeypatch, toy_lib):
    _no_web(monkeypatch, A)

    async def best(*a, **k):
        raise AssertionError("no Jev gap check on a pack")
    seen = {}

    async def grounded(question, material, ctx, history):
        seen["material"] = material
        return "From the pack."
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "When is PET-CT advised?", "toy-nodule@1.0", CTX, [])
    assert res.error is None and res.answer == "From the pack." and res.supported and not res.searched
    assert res.entry.key == "toy-nodule@1.0"
    m = seen["material"]
    assert "PET-CT" in m and "A toy guideline for tests." in m and "Toy guideline" in m and "p. 3" in m
    assert R.by_key(db_session, "toy-nodule@1.0") is None       # nothing stored under the pack key


async def test_ask_routed_to_a_pack_never_resolves_and_answers_from_the_pack(db_session, monkeypatch, toy_lib):
    _no_web(monkeypatch, A)

    async def route(question, ctx, history, known=""):
        assert "Toy 2020" in known
        return A.RawRoute(guideline="Toy Nodule", version="2020")

    async def grounded(question, material, ctx, history):
        return "Pack answer."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "How is this followed up under Toy?", None, CTX, [], finding_id="u1")
    assert res.card.key == "toy-nodule@1.0" and res.card.branch == "Pack" and res.answer == "Pack answer."


async def test_ask_routed_outside_the_library_is_a_general_answer(db_session, monkeypatch):
    _seed(db_session, key="other@1")
    _no_web(monkeypatch, A)

    async def route(question, ctx, history, known=""):
        assert "Other" not in known
        return A.RawRoute(guideline="Other", version="1")

    async def general(question, ctx, history):
        return "G."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "_general_answer", general)
    res = await A.ask(db_session, "Other?", None, CTX, [])
    assert res.kind == "general" and res.answer == "G." and res.card is None


async def test_ask_on_a_registry_key_with_the_flag_off_is_unknown(db_session, monkeypatch):
    _seed(db_session, key="other@1")
    _no_web(monkeypatch, A)
    res = await A.ask(db_session, "q?", "other@1", CTX, [])
    assert res.error == "unknown guideline" and not res.supported


def test_upsert_refuses_a_library_key(db_session, toy_lib):
    with pytest.raises(ValueError, match="library"):
        R.upsert(db_session, key="toy-nodule@1.0", name="Toy", version="2020", aliases=[], publication=None,
                 content=GuidelineContent(), sources=[], chunks=[])


async def test_resolve_guideline_refuses_library_keys_and_is_off_by_default(db_session, monkeypatch, toy_lib):
    async def boom(*a, **k):
        raise AssertionError("never fetched")
    monkeypatch.setattr(F, "_fetch_branch", boom)
    pack = Card(key="toy-nodule@1.0", name="Toy 2020", version="2020", finding_id="u1", branch="Pack")
    other = Card(key="other@1", name="Other", version="1", finding_id="u1", branch="B")
    assert await F.resolve_guideline(db_session, other) is None
    monkeypatch.setenv("RR_COPILOT_WEB_FETCH", "1")
    assert await F.resolve_guideline(db_session, pack) is None


# ── routes ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def authed(client, db_session, db_engine, monkeypatch):
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)
    monkeypatch.delenv("RR_STACK_COPILOT", raising=False)
    monkeypatch.setattr(CR, "SessionLocal", sessionmaker(bind=db_engine, autoflush=False, autocommit=False))
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T", is_active=True,
             is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: u
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_open_and_preview_outside_the_library_never_resolve(authed, db_session, monkeypatch):
    _seed(db_session, key="other@1")
    _no_web(monkeypatch, CR)
    card = {"key": "other@1", "name": "Other", "version": "1", "finding_id": "u1", "branch": "B"}
    d = authed.post("/api/canvas/stack/guidelines/open", json={"card": card, "findings": "x"}).json()
    assert d["error"] == "unavailable" and d["entry"] is None
    d = authed.post("/api/canvas/stack/guidelines/preview", json={"card": card, "findings": "x"}).json()
    assert d["error"] == "unknown guideline" and d["entry"] is None


def test_ask_job_on_a_pack_card_never_resolves_even_with_the_flag_on(authed, monkeypatch, toy_lib):
    monkeypatch.setenv("RR_COPILOT_WEB_FETCH", "1")
    _no_web(monkeypatch, CR, A)

    async def grounded(question, material, ctx, history):
        return "Pack answer."
    monkeypatch.setattr(A, "_grounded", grounded)
    card = {"key": "toy-nodule@1.0", "name": "Toy 2020", "version": "2020", "finding_id": "u1", "branch": "Pack"}
    d = authed.post("/api/canvas/stack/guidelines/ask",
                    json={"question": "q?", "key": "toy-nodule@1.0", "card": card}).json()
    assert d["answer"] == "Pack answer." and d["error"] is None
