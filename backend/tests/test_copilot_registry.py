import pytest
from sqlalchemy.orm import sessionmaker

from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Chunk, GuidelineContent, Output, Publication, Source


def test_make_key_and_slug():
    assert R.make_key("Fleischner Society", "2017") == "fleischner-society@2017"
    assert R.make_key("Kellgren–Lawrence", "") == "kellgren-lawrence"
    assert R.norm("  Bosniak  (2019) ") == "bosniak 2019"


def _content(state="checked"):
    return GuidelineContent(summary="s", branches=[Branch(name="Solid", state=state,
                            outputs=[Output(when="<6 mm", classification="No follow-up", quote="q")])])


def test_upsert_merges_branches_and_lookup(db_session):
    R.upsert(db_session, key="fleischner@2017", name="Fleischner", version="2017", aliases=["fleischner society"],
             publication=Publication(title="Guidelines for…", body="Fleischner Society", year="2017"),
             content=_content(), sources=[Source(url="https://a", tier=1)], chunks=[])
    sub = GuidelineContent(branches=[Branch(name="Subsolid", state="checked", outputs=[Output(classification="x", quote="q")])])
    R.upsert(db_session, key="fleischner@2017", name="Fleischner", version="2017", aliases=[], publication=None,
             content=sub, sources=[Source(url="https://b", tier=2)], chunks=[])
    e = R.entry(R.by_key(db_session, "fleischner@2017"))
    assert [b.name for b in e.content.branches] == ["Solid", "Subsolid"]
    assert {s.url for s in e.sources} == {"https://a", "https://b"}
    assert e.content.summary == "s"                    # a later upsert with no summary keeps the first
    assert [r.key for r in R.by_alias(db_session, "Fleischner Society")] == ["fleischner@2017"]
    assert [r.key for r in R.by_alias(db_session, "fleischner")] == ["fleischner@2017"]


def test_upsert_never_overwrites_verified_branch(db_session):
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=_content(),
             sources=[], chunks=[])
    R.by_key(db_session, "k@1").status = "verified"
    db_session.commit()
    worse = GuidelineContent(branches=[Branch(name="Solid", state="not_available")])
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=worse,
             sources=[], chunks=[])
    assert R.entry(R.by_key(db_session, "k@1")).content.branch("Solid").state == "checked"


def test_pending_never_replaces_checked(db_session):
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=_content(),
             sources=[], chunks=[])
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="Solid", state="pending")]), sources=[], chunks=[])
    assert R.entry(R.by_key(db_session, "k@1")).content.branch("Solid").state == "checked"


def test_known_list(db_session):
    R.upsert(db_session, key="k@1", name="K", version="1", aliases=[], publication=None, content=_content(),
             sources=[], chunks=[])
    assert R.known(db_session) == [("k@1", "K", "1")]


def test_upsert_survives_a_concurrent_sibling_session(db_engine):
    """Session A loads the row, session B upserts branch X and commits, then session A (still on its earlier
    load) upserts branch Y. Both must survive — A's upsert must not clobber B's commit (lost-update guard)."""
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    a, b, c = Session(), Session(), Session()
    try:
        R.upsert(a, key="conc@1", name="Conc", version="1", aliases=[], publication=None, content=_content(),
                 sources=[], chunks=[])
        a.commit()
        row_a = R.by_key(a, "conc@1")      # A's long-held, soon-to-be-stale load
        assert row_a is not None

        content_x = GuidelineContent(branches=[Branch(name="X", state="checked",
                                     outputs=[Output(classification="x", quote="q")])])
        R.upsert(b, key="conc@1", name="Conc", version="1", aliases=[], publication=None, content=content_x,
                 sources=[], chunks=[])

        content_y = GuidelineContent(branches=[Branch(name="Y", state="checked",
                                     outputs=[Output(classification="y", quote="q")])])
        R.upsert(a, key="conc@1", name="Conc", version="1", aliases=[], publication=None, content=content_y,
                 sources=[], chunks=[])

        names = {bb.name for bb in R.entry(R.by_key(c, "conc@1")).content.branches}
        assert {"Solid", "X", "Y"} <= names
    finally:
        a.close()
        b.close()
        c.close()


def test_upsert_retries_once_after_an_insert_race(db_engine, monkeypatch):
    """Two sessions both see the key as new and insert: the loser's commit hits a primary-key violation. Force
    this deterministically by making this session's existence check miss once, even though the row is already
    really there (inserted by `other` beforehand) — the retry must find it and merge rather than raise."""
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    other = Session()
    R.upsert(other, key="race@1", name="Race", version="1", aliases=[], publication=None, content=_content(),
             sources=[], chunks=[])
    other.close()

    mine = Session()
    real_fresh = R._fresh
    calls = {"n": 0}

    def miss_once(db, key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_fresh(db, key)

    monkeypatch.setattr(R, "_fresh", miss_once)

    sub = GuidelineContent(branches=[Branch(name="Subsolid", state="checked",
                           outputs=[Output(classification="x", quote="q")])])
    row = R.upsert(mine, key="race@1", name="Race", version="1", aliases=[], publication=None, content=sub,
                   sources=[], chunks=[])

    assert calls["n"] == 2
    names = {b.name for b in R.entry(row).content.branches}
    assert names == {"Solid", "Subsolid"}
    mine.close()


def test_make_key_truncates_slug_and_version():
    long_name = "x" * 150
    long_version = "9" * 40
    key = R.make_key(long_name, long_version)
    slug_part, _, version_part = key.partition("@")
    assert len(slug_part) <= 100
    assert len(version_part) <= 24


@pytest.mark.parametrize("bad_key", ["", "@2017"])
def test_upsert_rejects_empty_or_bare_version_keys(db_session, bad_key):
    with pytest.raises(ValueError):
        R.upsert(db_session, key=bad_key, name="K", version="1", aliases=[], publication=None, content=_content(),
                 sources=[], chunks=[])


def test_upsert_dedupes_duplicate_incoming_sources_and_chunks(db_session):
    dupe = Source(url="https://a", tier=1)
    R.upsert(db_session, key="dedupe@1", name="Dedupe", version="1", aliases=[], publication=None,
             content=_content(), sources=[dupe, dupe, Source(url="https://a", tier=2)],
             chunks=[Chunk(url="https://a", text="t"), Chunk(url="https://a", text="t")])
    row = R.by_key(db_session, "dedupe@1")
    assert len(row.sources) == 1
    assert len(row.chunks) == 1


def test_by_alias_matches_a_trailing_version_token(db_session):
    R.upsert(db_session, key="fleischner@2017", name="Fleischner", version="2017", aliases=[], publication=None,
             content=_content(), sources=[], chunks=[])
    assert [r.key for r in R.by_alias(db_session, "Fleischner 2017")] == ["fleischner@2017"]
    assert [r.key for r in R.by_alias(db_session, "Fleischner")] == ["fleischner@2017"]

    R.upsert(db_session, key="bosniak@2019", name="Bosniak", version="2019", aliases=[], publication=None,
             content=_content(), sources=[], chunks=[])
    assert [r.key for r in R.by_alias(db_session, "Bosniak v2019")] == ["bosniak@2019"]

    R.upsert(db_session, key="kellgren-lawrence@1", name="Kellgren Lawrence", version="1", aliases=[],
             publication=None, content=_content(), sources=[], chunks=[])
    assert [r.key for r in R.by_alias(db_session, "Kellgren Lawrence 2nd edition")] == ["kellgren-lawrence@1"]
