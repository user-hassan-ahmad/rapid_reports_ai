import pytest

from rapid_reports_ai.hybrid_stack.copilot import ask as A
from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Card, Chunk, GuidelineContent, Output, Source

CTX = A.Context(scan_type="CT chest", history="", findings="7 mm solid nodule.")


@pytest.fixture(autouse=True)
def _clean():
    M.clear_cache()
    yield
    M.clear_cache()


def _seed(db):
    R.upsert(db, key="fleischner@2017", name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="Solid", state="checked",
                                                       outputs=[Output(classification="c", quote="q")])]),
             sources=[], chunks=[Chunk(url="https://a", text="perifissural nodules need no follow-up")])


async def test_card_scope_answered_from_material(db_session, monkeypatch):
    _seed(db_session)

    async def answers(material, q, transport=None):
        assert "perifissural" in material
        return 0.9

    async def grounded(question, material, ctx, history):
        return "No follow-up for typical perifissural nodules."
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "Does a perifissural shape change this?", "fleischner@2017", CTX, [])
    assert res.kind == "card" and res.key == "fleischner@2017" and "perifissural" in res.answer and not res.searched
    assert res.supported and res.error is None


async def test_card_scope_gap_searches_and_adds_supplement(db_session, monkeypatch):
    _seed(db_session)
    scores = iter([0.1, 0.9])

    async def answers(material, q, transport=None):
        return next(scores)

    async def phrase(question, name, version):
        return "Fleischner 2017 calcified nodule"

    seen = {}

    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
        seen.update(queries=queries, exclude=exclude, name=name, version=version)
        return [Chunk(url="https://b", text="benign calcification needs no follow-up")], [Source(url="https://b")]

    async def grounded(question, material, ctx, history):
        assert "benign calcification" in material
        return "Benign calcification needs no follow-up."
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "Does calcification matter?", "fleischner@2017", CTX, [])
    assert res.searched and res.supported
    assert seen == {"queries": ["Fleischner 2017 calcified nodule"], "exclude": {"https://a"},
                    "name": "Fleischner", "version": "2017"}
    e = R.entry(R.by_key(db_session, "fleischner@2017"))
    assert e.content.supplements[0].question == "Does calcification matter?"
    assert e.content.supplements[0].url == "https://b"
    assert e.content.branch("Solid").state == "checked"   # a supplement never touches the branches
    assert res.entry.content.supplements[0].answer == "Benign calcification needs no follow-up."


async def test_card_scope_gap_unanswered_says_so(db_session, monkeypatch):
    _seed(db_session)

    async def answers(material, q, transport=None):
        return 0.1

    async def phrase(question, name, version):
        return "x"

    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
        return [], []

    async def general(question, ctx, history):
        return "General answer."
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A, "_general_answer", general)
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert not res.supported and res.searched and res.answer.startswith(A.NOT_IN_GUIDELINE)
    assert R.entry(R.by_key(db_session, "fleischner@2017")).content.supplements == []


async def test_card_scope_case_text_never_reaches_search(db_session, monkeypatch):
    _seed(db_session)

    async def answers(material, q, transport=None):
        return 0.1

    async def phrase(question, name, version):
        return "Fleischner 7 mm nodule left lower lobe"

    seen = {}

    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
        seen["q"] = queries
        return [], []

    async def general(question, ctx, history):
        return "G."
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A, "_general_answer", general)
    await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert seen["q"] == ["Fleischner 2017"]


async def test_jev_outage_fails_safe(db_session, monkeypatch):
    _seed(db_session)

    async def answers(material, q, transport=None):
        raise ValueError("jev response has no answers")
    monkeypatch.setattr(A.J, "answers", answers)
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert res.error == "ValueError" and res.answer == "" and not res.supported and res.key == "fleischner@2017"


async def test_unknown_key_is_an_error_not_a_crash(db_session):
    res = await A.ask(db_session, "q?", "nothing@1", CTX, [])
    assert res.error and res.kind == "card"


async def test_tnm_key_answers_from_offline_material_without_search(db_session, monkeypatch):
    site = tnm.sites()[0]
    key = tnm.key_for(site)

    async def gather(*a, **k):
        raise AssertionError("TNM never searches")

    async def answers(material, q, transport=None):
        raise AssertionError("TNM is not gated")

    async def grounded(question, material, ctx, history):
        assert material == tnm.material(site)
        return "Staged by T, N and M."
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "How is it staged?", key, CTX, [])
    assert res.answer == "Staged by T, N and M." and res.entry.key == key and not res.searched


def test_safe_phrase_drops_case_text():
    assert A._safe_phrase("Fleischner 2017 calcified nodule", "Fleischner", "2017") == "Fleischner 2017 calcified nodule"
    assert A._safe_phrase("Fleischner 7 mm nodule left lower lobe", "Fleischner", "2017") == "Fleischner 2017"
    assert A._safe_phrase("Bosniak 2019 cyst in a 60 year old male", "Bosniak", "2019") == "Bosniak 2019"
    assert A._safe_phrase("", "Bosniak", "2019") == "Bosniak 2019"


async def test_no_scope_general(db_session, monkeypatch):
    async def route(question, ctx, history):
        return A.RawRoute(guideline="", version="", answer="Up to about 10 mm.")
    monkeypatch.setattr(A, "_route", route)
    res = await A.ask(db_session, "Normal CBD post-cholecystectomy?", None, CTX, [])
    assert res.kind == "general" and res.answer == "Up to about 10 mm." and res.card is None


async def test_no_scope_guideline_resolves_card(db_session, monkeypatch):
    _seed(db_session)

    async def route(question, ctx, history):
        return A.RawRoute(guideline="Fleischner", version="2017", answer="")

    async def resolve(db, card):
        return R.entry(R.by_key(db, card.key))

    async def answers(material, q, transport=None):
        return 0.9

    async def grounded(question, material, ctx, history):
        return "Answer."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "resolve_guideline", resolve)
    monkeypatch.setattr(A.J, "answers", answers)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "How do I follow up this nodule?", None, CTX, [], finding_id="u1")
    assert res.kind == "card" and res.card.key == "fleischner@2017" and res.card.finding_id == "u1"
    assert res.card.known and res.answer == "Answer."


async def test_no_scope_guideline_unresolved_falls_back_to_general(db_session, monkeypatch):
    async def route(question, ctx, history):
        return A.RawRoute(guideline="Some System", version="1", answer="")

    async def resolve(db, card):
        return None

    async def general(question, ctx, history):
        return "General."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "resolve_guideline", resolve)
    monkeypatch.setattr(A, "_general_answer", general)
    res = await A.ask(db_session, "q?", None, CTX, [])
    assert res.kind == "general" and res.answer == "General." and not res.supported and res.card is None


async def test_route_failure_fails_safe(db_session, monkeypatch):
    async def route(question, ctx, history):
        raise TimeoutError()
    monkeypatch.setattr(A, "_route", route)
    res = await A.ask(db_session, "q?", None, CTX, [])
    assert res.kind == "general" and res.error == "TimeoutError"


async def test_no_scope_tnm_route_gates_the_site(db_session, monkeypatch):
    async def route(question, ctx, history):
        return A.RawRoute(guideline="TNM", version="9", site="Lung", answer="")

    async def tnm_gate(finding, site, history=""):
        assert "lung mass" in finding
        return 0.9

    async def grounded(question, material, ctx, history):
        return "T2a."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    monkeypatch.setattr(A, "_grounded", grounded)
    ctx = A.Context(scan_type="CT chest", findings="4 cm lung mass.")
    res = await A.ask(db_session, "What T stage is this?", None, ctx, [], finding_id="u2")
    assert res.card.key == "tnm-lung@9" and res.card.finding_id == "u2" and res.answer == "T2a."
