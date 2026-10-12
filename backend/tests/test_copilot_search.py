import tavily

from rapid_reports_ai.hybrid_stack.copilot import search as S
from rapid_reports_ai.hybrid_stack.copilot.types import Publication


def test_queries_use_identity_only():
    pub = Publication(title="Guidelines for Management of Incidental Pulmonary Nodules", body="Fleischner Society", year="2017")
    q = S.first_pass_queries("Fleischner", "2017", pub, "Subsolid · part-solid · ≥ 6 mm")
    assert q == ['"Guidelines for Management of Incidental Pulmonary Nodules" 2017',
                 "Fleischner 2017 Subsolid part-solid ≥ 6 mm criteria recommendations"]
    assert S.branch_query("Fleischner", "2017", "Solid · single") == "Fleischner 2017 Solid single recommendations"


def test_first_pass_without_publication_falls_back_to_name():
    q = S.first_pass_queries("Bosniak", "2019", Publication(), "")
    assert q == ["Bosniak 2019 classification", "Bosniak 2019 criteria recommendations"]


def test_first_pass_strips_quotes_from_the_publication_title():
    pub = Publication(title='Guidelines for "Incidental" Nodules', year="2017")
    q = S.first_pass_queries("Fleischner", "2017", pub, "Solid")
    assert q[0] == '"Guidelines for Incidental Nodules" 2017'


def test_tier_ranking():
    assert S.tier("https://pubs.rsna.org/doi/10.1148/radiol.2017161659") == 1
    assert S.tier("https://www.rcr.ac.uk/x") == 1
    assert S.tier("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/") == 2
    assert S.tier("https://europepmc.org/article/x") == 2
    assert S.tier("https://radiopaedia.org/articles/x") == 3
    ranked = S.rank([{"url": "https://radiopaedia.org/a", "score": 0.9}, {"url": "https://pubs.rsna.org/b", "score": 0.5},
                     {"url": "https://pmc.ncbi.nlm.nih.gov/c", "score": 0.7}])
    assert [r["url"] for r in ranked] == ["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c", "https://radiopaedia.org/a"]


def test_tier_additions():
    for url in ("https://jacr.org/x", "https://clinicalradiologyonline.net/x", "https://www.springeropen.com/x",
                "https://ersjournals.com/x", "https://esgar.org/x", "https://www.myesr.org/x", "https://thyroid.org/x"):
        assert S.tier(url) == 1, url


def test_tier_rejects_lookalike_subdomains_and_suffixes():
    assert S.tier("https://evilrcr.ac.uk/x") == 3
    assert S.tier("https://rcr.ac.uk.evil.com/x") == 3


def test_rank_is_stable_for_ties():
    results = [{"url": "https://radiopaedia.org/a", "score": 0.5}, {"url": "https://radiopaedia.org/b", "score": 0.5}]
    assert [r["url"] for r in S.rank(results)] == ["https://radiopaedia.org/a", "https://radiopaedia.org/b"]


def test_above_floor_drops_low_scores_but_never_empties():
    results = [{"url": "https://a", "score": 0.9}, {"url": "https://b", "score": 0.1}]
    assert [r["url"] for r in S._above_floor(results)] == ["https://a"]
    all_low = [{"url": "https://a", "score": 0.1}, {"url": "https://b", "score": 0.2}]
    assert S._above_floor(all_low) == all_low


def test_canon_dedupe_key_folds_old_ncbi_path_and_ignores_scheme_fragment_slash():
    a = S._canon("http://WWW.NCBI.NLM.NIH.GOV/pmc/articles/PMC123/#section")
    b = S._canon("https://pmc.ncbi.nlm.nih.gov/articles/PMC123")
    assert a == b == "pmc.ncbi.nlm.nih.gov/articles/PMC123"


async def test_gather_dedupes_and_extracts_top_two(monkeypatch):
    calls = {"search": [], "extract": []}

    async def fake_search(q):
        calls["search"].append(q)
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.5, "content": "s"},
                {"url": "https://radiopaedia.org/a", "title": "A", "score": 0.9, "content": "s"},
                {"url": "https://pmc.ncbi.nlm.nih.gov/c", "title": "C", "score": 0.7, "content": "s"}]

    async def fake_extract(urls, query=S.EXTRACT_FOCUS):
        calls["extract"].append((urls, query))
        return {u: f"text of {u}" for u in urls}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, sources = await S.gather(["q1", "q2"], branch="Solid")
    assert calls["extract"] == [(["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c"], S.EXTRACT_FOCUS)]
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c"]
    assert chunks[0].branch == "Solid" and sources[0].tier == 1


async def test_gather_falls_back_to_search_content_when_extract_fails(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://x.org/a", "title": "A", "score": 0.5, "content": "search snippet text"}]

    async def fake_extract(urls, query=S.EXTRACT_FOCUS):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert chunks[0].text == "search snippet text"


async def test_gather_dedupes_canonical_duplicates_across_queries(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.9, "content": "s"},
                {"url": "https://pubs.rsna.org/b/", "title": "B dup", "score": 0.8, "content": "s"}]

    async def fake_extract(urls, query=S.EXTRACT_FOCUS):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q1", "q2"], branch="")
    assert len(chunks) == 1


async def test_gather_skips_excluded_urls(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/known", "title": "Known", "score": 0.9, "content": "s"},
                {"url": "https://pubs.rsna.org/new", "title": "New", "score": 0.8, "content": "s"}]

    async def fake_extract(urls, query=S.EXTRACT_FOCUS):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="", exclude={"https://pubs.rsna.org/known"})
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/new"]


async def test_gather_passes_focus_into_the_extract_query(monkeypatch):
    seen = {}

    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.9, "content": "s"}]

    async def fake_extract(urls, query=S.EXTRACT_FOCUS):
        seen["query"] = query
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    await S.gather(["q"], branch="Solid", focus="Solid")
    assert seen["query"] == f"Solid: {S.EXTRACT_FOCUS}"


async def test_gather_drops_results_below_the_relevance_floor(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/weak", "title": "weak", "score": 0.1, "content": "s"},
                {"url": "https://pubs.rsna.org/strong", "title": "strong", "score": 0.9, "content": "s"}]

    async def fake_extract(urls, query=S.EXTRACT_FOCUS):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/strong"]


async def test_extract_treats_a_geo_block_page_as_failed(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")

    class FakeClient:
        def __init__(self, key):
            pass

        async def extract(self, **kwargs):
            return {"results": [
                {"url": "https://a", "raw_content": "This content is only available to eligible users within the UK."},
                {"url": "https://b", "raw_content": "Real guideline text about follow-up."},
            ]}
    monkeypatch.setattr(tavily, "AsyncTavilyClient", FakeClient)
    out = await S._extract(["https://a", "https://b"])
    assert out == {"https://b": "Real guideline text about follow-up."}


async def test_search_sends_the_query_and_normalizes_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    captured = {}

    class FakeClient:
        def __init__(self, key):
            captured["key"] = key

        async def search(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": [{"url": "https://a", "title": "A", "score": 0.5, "content": "c"}]}
    monkeypatch.setattr(tavily, "AsyncTavilyClient", FakeClient)
    out = await S._search("fleischner 2017")
    assert captured["key"] == "k"
    assert captured["kwargs"]["query"] == "fleischner 2017"
    assert out[0]["url"] == "https://a"


async def test_search_without_key_makes_no_call(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert await S._search("q") == []


async def test_search_exception_returns_empty(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")

    class FakeClient:
        def __init__(self, key):
            pass

        async def search(self, **kwargs):
            raise RuntimeError("boom")
    monkeypatch.setattr(tavily, "AsyncTavilyClient", FakeClient)
    assert await S._search("q") == []


async def test_extract_sends_the_focus_query_and_timeout(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    captured = {}

    class FakeClient:
        def __init__(self, key):
            pass

        async def extract(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": [{"url": "https://a", "raw_content": "text"}]}
    monkeypatch.setattr(tavily, "AsyncTavilyClient", FakeClient)
    out = await S._extract(["https://a"], "Solid: categories, criteria")
    assert captured["kwargs"]["query"] == "Solid: categories, criteria"
    assert captured["kwargs"]["timeout"] == S.EXTRACT_TIMEOUT_S
    assert out == {"https://a": "text"}


async def test_extract_without_urls_or_key_makes_no_call(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    assert await S._extract([]) == {}
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert await S._extract(["https://a"]) == {}


async def test_extract_exception_returns_empty(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")

    class FakeClient:
        def __init__(self, key):
            pass

        async def extract(self, **kwargs):
            raise RuntimeError("boom")
    monkeypatch.setattr(tavily, "AsyncTavilyClient", FakeClient)
    assert await S._extract(["https://a"]) == {}
