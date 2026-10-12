from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, GuidelineContent, Output, Publication, Source


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
