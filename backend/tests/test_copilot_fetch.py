import asyncio

import pytest

from rapid_reports_ai.hybrid_stack.copilot import fetch as F
from rapid_reports_ai.hybrid_stack.copilot import jev as J
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot import search as S
from rapid_reports_ai.hybrid_stack.copilot.types import (Branch, Card, Chunk, GuidelineContent, Input, Output,
                                                         Publication, Source)

_REAL_SPAWN = F._spawn_fill
_REAL_COVERAGE = F.J.coverage

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

    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
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

    async def empty(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
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

    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
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


def test_claim_is_a_sentence_with_context_and_no_empty_fragments():
    o = Output(when="<6 mm", classification="Category 2", recommendation="No follow-up", quote="q")
    assert F._claim(CARD, "Solid", o) == "In Fleischner 2017, for Solid: when <6 mm; Category 2; recommendation: No follow-up"
    o2 = Output(when="", classification="", recommendation="CT at 3 months", quote="q")
    assert F._claim(CARD, F.OVERVIEW, o2) == "In Fleischner 2017: recommendation: CT at 3 months"
    assert "→" not in F._claim(CARD, "Solid", Output(when="x", quote="q"))


async def test_coverage_names_the_guideline(db_session, monkeypatch):
    _stub(monkeypatch)
    asked = []

    async def coverage(source, branches, transport=None):
        asked.extend(branches)
        return {b: 0.9 for b in branches}
    monkeypatch.setattr(F.J, "coverage", coverage)
    await F.resolve_guideline(db_session, CARD)
    await F.resolve_guideline(db_session, CARD.model_copy(update={"key": "other@1", "branch": ""}))
    assert asked == ["Fleischner 2017: Solid", "Fleischner 2017"]


async def test_not_available_branch_stores_no_structure(db_session, monkeypatch):
    _stub(monkeypatch, evidence=0.1)
    b = (await F.resolve_guideline(db_session, CARD)).content.branch("Solid")
    assert b.state == "not_available" and b.rule == "" and b.inputs == [] and b.outputs == []


async def test_rule_jev_scored_low_is_blanked(db_session, monkeypatch):
    """The rule rides in the same evidence() batch as the outputs; a low Jev score on the rule claim blanks it
    without touching the outputs' own scores."""
    st = F.Structured(branch=_branch("Solid").model_copy(update={"rule": "follow up at 12 months"}))
    _stub(monkeypatch, structured=st)

    async def evidence_(source, claims, transport=None):
        return [0.1 if "rule:" in c else 1.0 for _, c in claims]
    monkeypatch.setattr(F.J, "evidence", evidence_)
    b = (await F.resolve_guideline(db_session, CARD)).content.branch("Solid")
    assert b.rule == "" and b.outputs   # outputs still kept; only the rule was dropped


async def test_rule_jev_scored_high_is_kept(db_session, monkeypatch):
    st = F.Structured(branch=_branch("Solid").model_copy(update={"rule": "routine follow-up not needed"}))
    _stub(monkeypatch, structured=st)   # default evidence=1.0 covers the rule claim too
    b = (await F.resolve_guideline(db_session, CARD)).content.branch("Solid")
    assert b.rule == "routine follow-up not needed" and b.fetched_at


async def test_rule_claim_is_batched_with_output_claims_in_one_call(db_session, monkeypatch):
    seen = []

    async def evidence_(source, claims, transport=None):
        seen.append(claims)
        return [1.0 for _ in claims]
    _stub(monkeypatch)
    monkeypatch.setattr(F.J, "evidence", evidence_)
    await F.resolve_guideline(db_session, CARD)
    assert len(seen) == 1 and len(seen[0]) == 2   # one output claim + one rule claim, one call
    assert seen[0][-1][1] == "In Fleischner 2017, for Solid: rule: r"


async def test_exact_signals_logged_not_used_to_approve(db_session, monkeypatch, caplog):
    import logging
    _stub(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="rapid_reports_ai.hybrid_stack.copilot.fetch"):
        await F.resolve_guideline(db_session, CARD)
    assert any("exact=" in r.getMessage() for r in caplog.records)


def _seed_not_available(db, days_ago):
    at = (F._now() - F.timedelta(days=days_ago)).isoformat(timespec="seconds")
    R.upsert(db, key=CARD.key, name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="Solid", state="not_available", fetched_at=at)]),
             sources=[], chunks=[])


async def test_fresh_not_available_is_served_without_search(db_session, monkeypatch):
    _seed_not_available(db_session, 1)
    calls = _stub(monkeypatch)
    assert (await F.resolve_guideline(db_session, CARD)).content.branch("Solid").state == "not_available"
    assert calls["gather"] == []


async def test_stale_not_available_is_fetched_again(db_session, monkeypatch):
    _seed_not_available(db_session, F.NOT_AVAILABLE_RETRY_DAYS + 1)
    calls = _stub(monkeypatch)
    assert (await F.resolve_guideline(db_session, CARD)).content.branch("Solid").state == "checked"
    assert len(calls["gather"]) == 1


def test_to_fill_includes_stale_not_available():
    old = (F._now() - F.timedelta(days=30)).isoformat()
    new = F._now().isoformat()
    content = GuidelineContent(branches=[Branch(name="Solid", state="not_available", fetched_at=old),
                                         Branch(name="Subsolid", state="not_available", fetched_at=new)])
    assert F.to_fill(["Solid", "Subsolid"], content) == ["Solid"]


async def test_cancelled_fill_releases_claims(monkeypatch):
    _stub(monkeypatch)
    _REAL_SPAWN(CARD, GuidelineContent())
    assert F._FILLING == {"fleischner@2017|Solid", "fleischner@2017|Subsolid"}
    (task,) = list(F._TASKS)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert F._FILLING == set() and F._TASKS == set()


async def test_branches_of_one_key_fetch_concurrently(db_session, monkeypatch):
    _stub(monkeypatch)
    entered, release = [], asyncio.Event()

    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
        entered.append(branch)
        await release.wait()
        return [Chunk(url="https://pubs.rsna.org/x", text="… No routine follow-up …", branch=branch)], \
               [Source(url="https://pubs.rsna.org/x", tier=1)]
    monkeypatch.setattr(F.S, "gather", gather)
    runs = [asyncio.create_task(F.resolve_guideline(db_session, CARD.model_copy(update={"branch": b})))
            for b in ("Solid", "Subsolid")]
    for _ in range(20):
        await asyncio.sleep(0)
    assert sorted(entered) == ["Solid", "Subsolid"]        # both in flight before either finishes
    release.set()
    await asyncio.gather(*runs)
    entry = R.entry(R.by_key(db_session, CARD.key))
    assert sorted(b.name for b in entry.content.checked()) == ["Solid", "Subsolid"]


async def test_open_of_a_branch_being_filled_waits_then_rereads(db_session, monkeypatch):
    calls = _stub(monkeypatch)
    lock = F._lock(CARD.key, "Solid")
    await lock.acquire()                                    # the background fill holds the branch
    run = asyncio.create_task(F.resolve_guideline(db_session, CARD))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not run.done()
    R.upsert(db_session, key=CARD.key, name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[_branch("Solid").model_copy(update={"state": "checked"})]),
             sources=[], chunks=[])                         # what the fill saved
    lock.release()
    entry = await run
    assert entry.content.branch("Solid").state == "checked" and calls["gather"] == []


def test_locks_are_per_event_loop():
    async def get():
        return F._lock("k", "b")
    assert asyncio.run(get()) is not asyncio.run(get())


def test_source_text_capped_on_chunk_boundaries(monkeypatch):
    monkeypatch.setattr(F.J, "SOURCE_MAX", 100)
    a, b = Chunk(url="u1", text="a" * 40), Chunk(url="u2", text="b" * 80)
    assert F._text([a, b]) == "[u1]\n" + "a" * 40
    assert len(F._text([b, a])) == 85 and len(F._text([Chunk(url="u", text="c" * 500)])) == 100


async def test_malformed_jev_answer_is_an_outage_not_a_low_score(db_session, monkeypatch):
    """A 200 with no answers raises (after one retry): nothing is stored, the branch is not marked not_available."""
    _stub(monkeypatch)
    monkeypatch.setattr(F.J, "coverage", _REAL_COVERAGE)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    class _Bad:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "upstream"}

    async def post(payload, key, timeout, transport=None):
        return _Bad()
    monkeypatch.setattr(F.J, "jev_post", post)
    assert await F.resolve_guideline(db_session, CARD) is None
    assert R.by_key(db_session, CARD.key) is None


async def test_coverage_retry_reads_two_new_pages(db_session, monkeypatch):
    _stub(monkeypatch)
    covers = iter([0.2, 0.9])
    calls = []

    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
        calls.append((exclude, top))
        url = f"https://pubs.rsna.org/{len(calls)}"
        return [Chunk(url=url, text="… No routine follow-up …", branch=branch)], [Source(url=url, tier=1)]

    async def coverage(source, branches, transport=None):
        return {b: next(covers) for b in branches}
    monkeypatch.setattr(F.S, "gather", gather)
    monkeypatch.setattr(F.J, "coverage", coverage)
    entry = await F.resolve_guideline(db_session, CARD)
    assert calls == [(None, None), ({"https://pubs.rsna.org/1"}, F.RETRY_URLS)]
    assert F.RETRY_URLS == 2 and S.TOP_URLS + F.RETRY_URLS <= J.WINDOW_CAP
    assert entry.content.branch("Solid").state == "checked"
