import asyncio

import pytest

from rapid_reports_ai.hybrid_stack.copilot import fetch as F
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import (Branch, Card, Chunk, GuidelineContent, Input, Output,
                                                         Publication, Source)

_REAL_SPAWN = F._spawn_fill

CARD = Card(key="fleischner@2017", name="Fleischner", version="2017", finding_id="u1",
            branch="Solid", skeleton=["Solid", "Subsolid"], publication=Publication(title="T", year="2017"))


@pytest.fixture(autouse=True)
def _fresh_module_state():
    """Locks bind to the loop they first contend on; each test has its own loop, so start every test clean."""
    F._LOCKS.clear()
    F._FILLING.clear()
    yield
    F._LOCKS.clear()
    F._FILLING.clear()


def _branch(name, quote="no routine follow-up"):
    return Branch(name=name, inputs=[Input(id="risk", question="Risk", options=["Low", "High"])], rule="r",
                  outputs=[Output(when="<6 mm", classification="None", recommendation="No routine follow-up", quote=quote)])


def _stub(monkeypatch, cover=0.9, evidence=1.0, structured=None):
    calls = {"gather": [], "structure": []}

    async def gather(queries, branch, focus="", exclude=None):
        calls["gather"].append((queries, branch))
        return [Chunk(url="https://pubs.rsna.org/x", text="… No routine follow-up …", branch=branch)], \
               [Source(url="https://pubs.rsna.org/x", tier=1)]

    async def coverage(source, branches, transport=None):
        return {b: cover for b in branches}

    async def evidence_(source, claims, transport=None):
        return [evidence for _ in claims]

    async def structure(name, version, branch, text):
        calls["structure"].append(branch)
        return structured or F.Structured(summary="sum", applies_to="nodules", aliases=["fleischner society"],
                                          branch=_branch(branch))
    monkeypatch.setattr(F.S, "gather", gather)
    monkeypatch.setattr(F.J, "coverage", coverage)
    monkeypatch.setattr(F.J, "evidence", evidence_)
    monkeypatch.setattr(F, "_structure", structure)
    monkeypatch.setattr(F, "_spawn_fill", lambda *a, **k: None)
    return calls


async def test_first_pass_saves_checked_branch(db_session, monkeypatch):
    calls = _stub(monkeypatch)
    entry = await F.resolve_guideline(db_session, CARD)
    assert entry is not None and entry.content.branch("Solid").state == "checked"
    assert calls["gather"][0][0] == ['"T" 2017', "Fleischner 2017 Solid criteria recommendations"]
    assert entry.status == "draft" and entry.sources[0].tier == 1


async def test_registry_hit_makes_no_search(db_session, monkeypatch):
    R.upsert(db_session, key=CARD.key, name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[_branch("Solid").model_copy(update={"state": "checked"})]),
             sources=[], chunks=[])
    calls = _stub(monkeypatch)
    await F.resolve_guideline(db_session, CARD)
    assert calls["gather"] == []


async def test_low_coverage_runs_one_branch_query_then_not_available(db_session, monkeypatch):
    calls = _stub(monkeypatch, cover=0.2)
    entry = await F.resolve_guideline(db_session, CARD)
    assert len(calls["gather"]) == 2 and calls["gather"][1][0] == ["Fleischner 2017 Solid recommendations"]
    assert entry.content.branch("Solid").state == "not_available" and calls["structure"] == []


async def test_unsupported_outputs_are_dropped(db_session, monkeypatch):
    _stub(monkeypatch, evidence=0.1)
    entry = await F.resolve_guideline(db_session, CARD)
    assert entry.content.branch("Solid").state == "not_available"


async def test_no_results_returns_none_and_stores_nothing(db_session, monkeypatch):
    _stub(monkeypatch)

    async def empty(queries, branch, focus="", exclude=None):
        return [], []
    monkeypatch.setattr(F.S, "gather", empty)
    assert await F.resolve_guideline(db_session, CARD) is None
    assert R.by_key(db_session, CARD.key) is None


async def test_concurrent_resolves_share_one_fetch(db_session, monkeypatch):
    calls = _stub(monkeypatch)
    await asyncio.gather(F.resolve_guideline(db_session, CARD), F.resolve_guideline(db_session, CARD))
    assert len(calls["gather"]) == 1


async def test_save_failure_returns_none_without_raising(db_session, monkeypatch):
    _stub(monkeypatch)

    def boom(*a, **k):
        raise ValueError("invalid guideline key")
    monkeypatch.setattr(F.R, "upsert", boom)
    assert await F.resolve_guideline(db_session, CARD) is None


async def test_save_failure_returns_existing_entry(db_session, monkeypatch):
    R.upsert(db_session, key=CARD.key, name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[_branch("Subsolid").model_copy(update={"state": "checked"})]),
             sources=[], chunks=[])
    _stub(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(F.R, "upsert", boom)
    entry = await F.resolve_guideline(db_session, CARD)
    assert entry is not None and entry.content.branch("Subsolid").state == "checked"
    assert entry.content.branch("Solid") is None


def test_pending_branches_listed_for_fill():
    content = GuidelineContent(branches=[_branch("Solid").model_copy(update={"state": "checked"})])
    assert F.to_fill(["Solid", "Subsolid"], content) == ["Subsolid"]


async def test_spawn_fill_saves_other_branches_in_own_session(db_session, db_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    calls = _stub(monkeypatch)
    monkeypatch.setattr(F, "_spawn_fill", _REAL_SPAWN)   # _stub disabled it
    monkeypatch.setattr(F, "SessionLocal", sessionmaker(bind=db_engine, autoflush=False, autocommit=False))
    await F.resolve_guideline(db_session, CARD)
    assert F._FILLING == {"fleischner@2017|Subsolid"}          # claimed before the task runs
    await asyncio.gather(*list(F._TASKS))
    assert F._FILLING == set() and calls["structure"] == ["Solid", "Subsolid"]
    db_session.expire_all()
    entry = R.entry(R.by_key(db_session, CARD.key))
    assert [b.name for b in entry.content.checked()] == ["Solid", "Subsolid"]



async def test_tnm_key_served_offline_without_search(db_session, monkeypatch):
    from rapid_reports_ai.hybrid_stack.copilot import tnm
    calls = _stub(monkeypatch)
    card = CARD.model_copy(update={"key": tnm.key_for("Lung"), "branch": "Staging", "skeleton": ["Staging"]})
    entry = await F.resolve_guideline(db_session, card)
    assert entry.status == "verified" and entry.name == "TNM Lung" and calls["gather"] == []
    assert R.by_key(db_session, card.key) is None
    assert await F.resolve_guideline(db_session, card.model_copy(update={"key": "tnm-nowhere@9"})) is None


async def test_no_transaction_held_while_fetching(db_session, monkeypatch):
    # A row whose Solid branch is pending: the request reads it, then must release the connection before the fetch.
    R.upsert(db_session, key=CARD.key, name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="Solid")]), sources=[], chunks=[])
    R.by_key(db_session, CARD.key)
    assert db_session.in_transaction()
    _stub(monkeypatch)
    seen = []

    async def gather(queries, branch, focus="", exclude=None):
        seen.append(db_session.in_transaction())
        return [Chunk(url="https://pubs.rsna.org/x", text="… No routine follow-up …", branch=branch)], \
               [Source(url="https://pubs.rsna.org/x", tier=1)]
    monkeypatch.setattr(F.S, "gather", gather)
    entry = await F.resolve_guideline(db_session, CARD)
    assert seen == [False] and entry.content.branch("Solid").state == "checked"


async def test_branchless_card_stores_overview_and_searches_by_identity(db_session, monkeypatch):
    calls = _stub(monkeypatch)
    entry = await F.resolve_guideline(db_session, CARD.model_copy(update={"branch": "", "skeleton": []}))
    assert [b.name for b in entry.content.branches] == [F.OVERVIEW]
    assert entry.content.branch(F.OVERVIEW).state == "checked"
    queries = calls["gather"][0][0]
    assert queries == ['"T" 2017', "Fleischner 2017 criteria recommendations"]
    assert not any("overview" in q.lower() for q in queries)
    assert calls["structure"] == ["the guideline as a whole"]
