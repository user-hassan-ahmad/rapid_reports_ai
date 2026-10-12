import pytest

from rapid_reports_ai.hybrid_stack.copilot import ask as A
from rapid_reports_ai.hybrid_stack.copilot import matcher as M
from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot import registry as R
from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.types import (Branch, Chunk, GuidelineContent, Output, Source,
                                                         Supplement)

pytestmark = pytest.mark.usefixtures("web_fetch_on")   # these tests exercise the web path

CTX = A.Context(scan_type="CT chest", history="", findings="7 mm solid nodule.")


@pytest.fixture(autouse=True)
def _clean():
    M.clear_cache()
    yield
    M.clear_cache()


def _seed(db, chunks=None, supplements=()):
    R.upsert(db, key="fleischner@2017", name="Fleischner", version="2017", aliases=[], publication=None,
             content=GuidelineContent(summary="Pulmonary nodule management.",
                                      branches=[Branch(name="Solid", state="checked", rule="by size and risk",
                                                       outputs=[Output(classification="c", quote="q")])],
                                      supplements=list(supplements)),
             sources=[], chunks=chunks if chunks is not None else
             [Chunk(url="https://a", text="perifissural nodules need no follow-up")])


def _best(*scores):
    it = iter(scores)
    seen = []

    async def answers_best(material, q, about="", transport=None):
        seen.append((material, about))
        return next(it), material
    return answers_best, seen


def _gather(chunks, seen=None):
    async def gather(queries, branch, focus="", exclude=None, name="", version="", title="", top=None):
        if seen is not None:
            seen.update(queries=queries, exclude=exclude, name=name, version=version, top=top)
        return chunks, [Source(url=c.url) for c in chunks]
    return gather


async def _phrase_fixed(question, name, version):
    return "Fleischner 2017 calcified nodule"


async def test_card_scope_answered_from_material(db_session, monkeypatch):
    _seed(db_session)
    best, seen = _best(0.9)

    async def grounded(question, material, ctx, history):
        assert "perifissural" in material and "by size and risk" in material
        return "No follow-up for typical perifissural nodules."
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "Does a perifissural shape change this?", "fleischner@2017", CTX, [])
    assert res.kind == "card" and res.key == "fleischner@2017" and "perifissural" in res.answer and not res.searched
    assert res.supported and res.error is None and seen[0][1] == ""


async def test_supplement_answers_are_never_material(db_session, monkeypatch):
    _seed(db_session, supplements=[Supplement(question="old q", answer="MODEL WRITTEN ANSWER", url="https://s")])
    best, seen = _best(0.9)

    async def grounded(question, material, ctx, history):
        assert "MODEL WRITTEN ANSWER" not in material
        return "A."
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_grounded", grounded)
    await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert "MODEL WRITTEN ANSWER" not in seen[0][0]


async def test_answer_in_a_later_window_is_grounded_on_that_window(db_session, monkeypatch):
    _seed(db_session, chunks=[Chunk(url="https://a", text="filler " * 40), Chunk(url="https://b", text="needle answer")])
    monkeypatch.setattr(A.J, "STATE_MAX", 200)

    class _Resp:
        def __init__(self, body):
            self._b = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._b

    async def post(payload, key, timeout, transport=None):
        return _Resp({"answers": {"q": {"noul": 0.9 if "needle" in payload["state"] else 0.1}}})
    got = {}

    async def grounded(question, material, ctx, history):
        got["m"] = material
        return "A."
    monkeypatch.setattr(A.J, "jev_post", post)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert res.supported and "needle answer" in got["m"] and "filler" not in got["m"]
    assert len(got["m"]) <= 200


async def test_card_scope_gap_searches_and_adds_a_draft_supplement(db_session, monkeypatch):
    _seed(db_session)
    best, seen_best = _best(0.1, 0.9)
    seen = {}

    async def grounded(question, material, ctx, history):
        assert "benign calcification" in material
        return "Benign calcification needs no follow-up."
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_search_phrase", _phrase_fixed)
    monkeypatch.setattr(A.S, "gather", _gather([Chunk(url="https://b", text="benign calcification needs no follow-up")], seen))
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "Does calcification matter?", "fleischner@2017", CTX, [])
    assert res.searched and res.supported
    # "calcified" is not in the entry's vocabulary, so only "nodule" survives
    assert seen == {"queries": ["Fleischner 2017 nodule"], "exclude": {"https://a"}, "name": "Fleischner",
                    "version": "2017", "top": A.GAP_URLS} and A.GAP_URLS == 2
    assert seen_best[1][1] == "Fleischner 2017"   # the gap gate is scoped to the guideline
    sup = R.entry(R.by_key(db_session, "fleischner@2017")).content.supplements[0]
    # case-free: the search phrase and the url, never the question or the answer
    assert (sup.question, sup.answer, sup.url, sup.quote, sup.verified) == ("Fleischner 2017 nodule", "", "https://b", "",
                                                                            False)
    assert R.entry(R.by_key(db_session, "fleischner@2017")).content.branch("Solid").state == "checked"
    assert res.answer == "Benign calcification needs no follow-up."


async def test_supplement_store_failure_still_answers(db_session, monkeypatch):
    _seed(db_session)
    best, _ = _best(0.1, 0.9)

    async def grounded(question, material, ctx, history):
        return "Grounded."

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_search_phrase", _phrase_fixed)
    monkeypatch.setattr(A.S, "gather", _gather([Chunk(url="https://b", text="t")]))
    monkeypatch.setattr(A, "_grounded", grounded)
    monkeypatch.setattr(A.R, "upsert", boom)
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert res.answer == "Grounded." and res.supported and res.error is None


async def test_card_scope_gap_unanswered_says_so(db_session, monkeypatch):
    _seed(db_session)
    best, _ = _best(0.1)

    async def phrase(question, name, version):
        return "x"

    async def general(question, ctx, history):
        return "General answer."
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", _gather([]))
    monkeypatch.setattr(A, "_general_answer", general)
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert not res.supported and res.searched
    assert res.answer == f"{A.NOT_IN_GUIDELINE} From general knowledge: General answer."
    assert R.entry(R.by_key(db_session, "fleischner@2017")).content.supplements == []


async def test_card_scope_case_text_never_reaches_search(db_session, monkeypatch):
    _seed(db_session)
    best, _ = _best(0.1)
    seen = {}

    async def phrase(question, name, version):
        return "Fleischner 7 mm nodule left lower lobe"

    async def general(question, ctx, history):
        return "G."
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", _gather([], seen))
    monkeypatch.setattr(A, "_general_answer", general)
    await A.ask(db_session, "q?", "fleischner@2017", CTX, [])
    assert seen["queries"] == ["Fleischner 2017 nodule"]
    assert "mm" not in seen["queries"][0] and "left" not in seen["queries"][0]


async def test_jev_outage_fails_safe(db_session, monkeypatch):
    _seed(db_session)

    async def best(material, q, about="", transport=None):
        raise ValueError("jev response has no answers")
    monkeypatch.setattr(A.J, "answers_best", best)
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

    async def best(*a, **k):
        raise AssertionError("TNM is not gated")

    async def grounded(question, material, ctx, history):
        assert material == tnm.material(site)[:A.J.STATE_MAX]
        return "Staged by T, N and M."
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "How is it staged?", key, CTX, [])
    assert res.answer == "Staged by T, N and M." and res.entry.key == key and not res.searched


def test_safe_phrase_keeps_only_guideline_vocabulary_and_drops_case_text():
    assert A._safe_phrase("Fleischner 2017 calcified nodule", "Fleischner", "2017") == "Fleischner 2017 calcified nodule"
    assert A._safe_phrase("Fleischner 7 mm nodule left lower lobe", "Fleischner", "2017") == \
        "Fleischner 2017 nodule lower lobe"
    assert A._safe_phrase("Bosniak 2019 cyst in a 60 year old male", "Bosniak", "2019") == "Bosniak 2019 cyst in a"
    assert A._safe_phrase("", "Bosniak", "2019") == "Bosniak 2019"
    vocab = {"patient", "risk", "high", "nodule"}
    assert A._safe_phrase("Fleischner high risk patient nodule", "Fleischner", "2017", vocab) == \
        "Fleischner 2017 high risk patient nodule"
    assert A._safe_phrase("Fleischner eight millimetre nodule calcified", "Fleischner", "2017", vocab) == \
        "Fleischner 2017 nodule"
    assert A._safe_phrase("calcified", "Fleischner", "2017", vocab) == "Fleischner 2017"
    assert A._safe_phrase("Fleischner 2017 unseen words", "Fleischner", "2017", vocab) == "Fleischner 2017"


def test_vocab_reads_the_whole_entry():
    e = R.Entry(key="k", name="Fleischner", version="2017",
                content=GuidelineContent(summary="Risk of malignancy", branches=[
                    Branch(name="Solid", rule="patient factors", outputs=[Output(when="low", recommendation="CT")])]))
    v = A._vocab(e, [Chunk(url="u", text="perifissural")])
    assert {"risk", "patient", "solid", "low", "ct", "perifissural", "fleischner"} <= v


async def test_no_scope_general(db_session, monkeypatch):
    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="", version="", answer="Up to about 10 mm.")
    monkeypatch.setattr(A, "_route", route)
    res = await A.ask(db_session, "Normal CBD post-cholecystectomy?", None, CTX, [])
    assert res.kind == "general" and res.answer == "Up to about 10 mm." and res.card is None


async def test_route_prompt_lists_known_guidelines(db_session, monkeypatch):
    _seed(db_session)
    got = {}

    class _R:
        output = A.RawRoute(guideline="", answer="x")

    async def run(**kw):
        got.update(kw)
        return _R()
    monkeypatch.setattr(A, "_run_agent_with_model", run)
    await A.ask(db_session, "q?", None, CTX, [])
    assert "KNOWN GUIDELINES (name version):\n- Fleischner 2017" in got["user_prompt"]
    assert "reuse the listed name and version exactly" in got["system_prompt"]
    assert "TNM SITES:" in got["user_prompt"]


async def test_no_scope_guideline_resolves_an_openable_card(db_session, monkeypatch):
    _seed(db_session)

    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="Fleischner", version="2017", answer="")

    async def resolve(db, card):
        return R.entry(R.by_key(db, card.key))

    async def pick(finding, entry, history=""):
        assert "nodule" in finding
        return "Solid"

    async def grounded(question, material, ctx, history):
        return "Answer."
    best, _ = _best(0.9)
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "resolve_guideline", resolve)
    monkeypatch.setattr(A.M, "pick_branch", pick)
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "How do I follow up this nodule?", None, CTX, [], finding_id="u1")
    assert res.kind == "card" and res.card.key == "fleischner@2017" and res.card.finding_id == "u1"
    assert res.card.known and res.answer == "Answer."
    assert res.card.branch == "Solid" and res.card.skeleton == ["Solid"]

    async def call(system, prompt):
        return P.RawPreview(output=1, line="Fleischner 2017: c.")
    monkeypatch.setattr(P, "_call", call)
    pv = await P.preview(res.entry, res.card.branch, CTX.findings, "", {})
    assert pv.proposal is not None and pv.proposal.classification == "Fleischner 2017 · c"


async def test_no_scope_card_falls_back_to_overview(db_session, monkeypatch):
    R.upsert(db_session, key="bosniak@2019", name="Bosniak", version="2019", aliases=[], publication=None,
             content=GuidelineContent(branches=[Branch(name="Overview", state="checked")]), sources=[],
             chunks=[Chunk(url="https://a", text="t")])

    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="Bosniak", version="2019")

    async def resolve(db, card):
        return R.entry(R.by_key(db, card.key))

    async def pick(finding, entry, history=""):
        return None

    async def grounded(question, material, ctx, history):
        return "A."
    best, _ = _best(0.9)
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "resolve_guideline", resolve)
    monkeypatch.setattr(A.M, "pick_branch", pick)
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "q?", None, CTX, [])
    assert res.card.branch == A.OVERVIEW


async def test_no_scope_guideline_unresolved_falls_back_to_general(db_session, monkeypatch):
    async def route(question, ctx, history, known=""):
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


async def test_case_text_in_a_routed_name_never_reaches_search(db_session, monkeypatch):
    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="Management of 2 cm left adrenal nodule", version="")
    queries = []

    async def search(q):
        queries.append(q)
        return []

    async def general(question, ctx, history):
        return "G."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A.S, "_search", search)
    monkeypatch.setattr(A, "_general_answer", general)
    res = await A.ask(db_session, "What next for this adrenal nodule?", None, CTX, [])
    assert res.answer == "G." and queries
    assert all("2 cm" not in q and "left" not in q.lower().split() for q in queries)


async def test_route_failure_fails_safe(db_session, monkeypatch):
    async def route(question, ctx, history, known=""):
        raise TimeoutError()
    monkeypatch.setattr(A, "_route", route)
    res = await A.ask(db_session, "q?", None, CTX, [])
    assert res.kind == "general" and res.error == "TimeoutError"


async def test_no_scope_tnm_route_gates_the_site(db_session, monkeypatch):
    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="TNM", version="9", site="Lung", answer="")

    async def tnm_gate(finding, site, history=""):
        raise AssertionError("an explicit staging question skips the case gate")

    async def grounded(question, material, ctx, history):
        return "T2a."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(M, "_tnm_gate", tnm_gate)
    monkeypatch.setattr(A, "_grounded", grounded)
    ctx = A.Context(scan_type="CT chest", findings="Normal study.")
    res = await A.ask(db_session, "How is a lung primary T-staged?", None, ctx, [], finding_id="u2")
    assert res.card.key == "tnm-lung@9" and res.card.finding_id == "u2" and res.answer == "T2a."
    assert res.card.branch == "Staging"


async def test_named_tnm_variant_routes_offline(db_session, monkeypatch):
    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="UICC TNM 9th edition", version="9th edition", site="Lung")

    async def gather(*a, **k):
        raise AssertionError("TNM is never fetched from the web")

    async def grounded(question, material, ctx, history):
        return "S."
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A.S, "gather", gather)
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "Stage?", None, CTX, [])
    assert res.card.key == "tnm-lung@9" and res.error is None and res.answer == "S."


async def test_stored_supplement_carries_no_case_text(db_session, monkeypatch):
    _seed(db_session)
    best, _ = _best(0.1, 0.9)

    async def phrase(question, name, version):
        return "Fleischner 7 mm nodule left lower lobe smoker"

    async def grounded(question, material, ctx, history):
        return "In this 64 year old smoker the 7 mm left nodule needs CT at 6-12 months."
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_search_phrase", phrase)
    monkeypatch.setattr(A.S, "gather", _gather([Chunk(url="https://b", text="nodule follow-up")]))
    monkeypatch.setattr(A, "_grounded", grounded)
    q = "My 64 year old smoker has a 7 mm left lower lobe nodule: when to rescan?"
    await A.ask(db_session, q, "fleischner@2017", CTX, [])
    sup = R.entry(R.by_key(db_session, "fleischner@2017")).content.supplements[0]
    assert sup.answer == "" and sup.question == "Fleischner 2017 nodule"
    for case in ("64", "7 mm", "left", "smoker", "rescan"):
        assert case not in sup.model_dump_json()


async def test_route_releases_the_connection_before_the_model(db_session, monkeypatch):
    _seed(db_session)
    seen = []

    async def route(question, ctx, history, known=""):
        seen.append((db_session.in_transaction(), known))
        return A.RawRoute(guideline="", answer="a")
    monkeypatch.setattr(A, "_route", route)
    await A.ask(db_session, "q?", None, CTX, [])
    assert seen == [(False, "- Fleischner 2017")]


async def test_abandoned_in_card_stops_before_jev(db_session, monkeypatch):
    import asyncio
    _seed(db_session)

    async def best(*a, **k):
        raise AssertionError("no Jev after abandon")
    monkeypatch.setattr(A.J, "answers_best", best)
    ev = asyncio.Event()
    ev.set()
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [], abandoned=ev)
    assert res.loading and res.answer == "" and R.entry(R.by_key(db_session, "fleischner@2017")).content.supplements == []


async def test_abandoned_no_card_returns_right_after_resolve(db_session, monkeypatch):
    import asyncio
    _seed(db_session)
    ev = asyncio.Event()
    calls = []

    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="Fleischner", version="2017")

    async def resolve(db, card):
        calls.append("resolve")
        ev.set()   # the route timed out while this ran
        return R.entry(R.by_key(db, card.key))

    async def nope(*a, **k):
        raise AssertionError("nothing after resolve")
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "resolve_guideline", resolve)
    monkeypatch.setattr(A.M, "pick_branch", nope)
    monkeypatch.setattr(A.J, "answers_best", nope)
    res = await A.ask(db_session, "q?", None, CTX, [], abandoned=ev)
    assert calls == ["resolve"] and res.loading and res.answer == ""


async def test_abandoned_after_gate_skips_the_gap_search(db_session, monkeypatch):
    import asyncio
    _seed(db_session)
    ev = asyncio.Event()

    async def best(material, q, about="", transport=None):
        ev.set()
        return 0.1, material

    async def nope(*a, **k):
        raise AssertionError("no gap search after abandon")
    monkeypatch.setattr(A.J, "answers_best", best)
    monkeypatch.setattr(A, "_search_phrase", nope)
    res = await A.ask(db_session, "q?", "fleischner@2017", CTX, [], abandoned=ev)
    assert res.loading


async def test_explicit_pack_question_skips_the_applicability_gate_background_match_keeps_it(db_session, monkeypatch, toy):
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
    lib = L.Library({"version": "v1", "entries": {"toy-nodule@1.0": {"entry": toy, "sources": []}}})
    monkeypatch.setattr(L, "get", lambda: lib)

    async def route(question, ctx, history, known=""):
        return A.RawRoute(guideline="Toy Nodule", version="2020", answer="")

    async def resolve(db, card):
        raise AssertionError("a library pack is never resolved")

    async def grounded(question, material, ctx, history):
        return "From the pack."
    calls = []

    async def pack_gate(finding, pack, history=""):
        calls.append(pack.key)
        return 0.0   # the gate would refuse this finding
    monkeypatch.setattr(A, "_route", route)
    monkeypatch.setattr(A, "resolve_guideline", resolve)
    monkeypatch.setattr(A, "_grounded", grounded)
    monkeypatch.setattr(M, "_pack_gate", pack_gate)
    res = await A.ask(db_session, "How is this followed up under Toy?", None, CTX, [], finding_id="u1")
    assert res.card.key == "toy-nodule@1.0" and res.card.finding_id == "u1" and calls == []
    assert res.answer == "From the pack."

    async def call(prompt):   # the background matcher still gates the same pack
        return M.RawMatch(findings=[M.RawFinding(id="u1", systems=[M.RawSystem(name="Toy Nodule", version="2020")])])
    monkeypatch.setattr(M, "_call", call)
    assert await M.match(db_session, "CT", "", [M.Finding(id="u1", text="7 mm solid nodule.")]) == []
    assert calls == ["toy-nodule@1.0"]


async def test_ask_on_a_reference_card_is_grounded_in_its_fields(db_session, monkeypatch, toy_reference):
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L
    lib = L.Library({"version": "v1", "entries": {"toy-grade@1.0": {"entry": toy_reference, "sources": []}}})
    monkeypatch.setattr(L, "get", lambda: lib)
    seen = {}

    async def grounded(question, material, ctx, history):
        seen["material"] = material
        return "Grade 2 is a partial-thickness defect."
    monkeypatch.setattr(A, "_grounded", grounded)
    res = await A.ask(db_session, "what is grade 2?", "toy-grade@1.0", A.Context(), [])
    assert res.answer == "Grade 2 is a partial-thickness defect." and "Grade table" in seen["material"]
    assert res.entry.content.branches[0].name == "Reference"
