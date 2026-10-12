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
                "https://ersjournals.com/x", "https://esgar.org/x", "https://www.myesr.org/x", "https://thyroid.org/x",
                "https://www.ese-hormones.org/x", "https://british-thyroid-association.org/x"):
        assert S.tier(url) == 1, url


def test_tier_rejects_lookalike_subdomains_and_suffixes():
    assert S.tier("https://evilrcr.ac.uk/x") == 3
    assert S.tier("https://rcr.ac.uk.evil.com/x") == 3


def test_abstract_pages_demoted_to_tier_four():
    assert S.tier("https://pubmed.ncbi.nlm.nih.gov/12345/") == 4
    assert S.tier("https://academic.oup.com/jcem/article/1/2/3/abstract") == 4
    assert S.tier("https://onlinelibrary.wiley.com/doi/abs/10.1111/x") == 4
    assert S.tier("https://scholars.duke.edu/person/x") == 4
    assert S.tier("https://www.researchgate.net/publication/123") == 4
    # PMC / Europe PMC full text is not an abstract page and keeps tier 2, even though pubmed shares its domain
    assert S.tier("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/") == 2
    assert S.tier("https://europepmc.org/article/MED/1") == 2


def test_on_topic_matches_full_name_or_its_first_two_tokens():
    bta_u = {"title": "BTA U classification of thyroid nodules", "content": "", "url": "https://x.org/a"}
    assert S.on_topic(bta_u, "BTA U classification")
    short_form = {"title": "The BTA U system explained", "content": "", "url": "https://x.org/a"}
    assert S.on_topic(short_form, "BTA U classification")   # first two tokens accepted for a 3+ token name
    orads = {"title": "O-RADS US risk stratification", "content": "", "url": "https://x.org/a"}
    assert S.on_topic(orads, "O-RADS US")
    unrelated = {"title": "Unrelated thyroid nodule paper", "content": "no mention here", "url": "https://x.org/a"}
    assert not S.on_topic(unrelated, "BTA U classification")


def test_rank_demotes_off_topic_tier_one_below_on_topic_tier_three():
    off_topic_tier1 = {"url": "https://acr.org/unrelated", "title": "Unrelated ATA thyroid paper",
                        "content": "nothing about BTA here", "score": 0.9}
    on_topic_tier3 = {"url": "https://radiopaedia.org/bta-u", "title": "BTA U classification overview",
                       "content": "BTA U classification", "score": 0.4}
    ranked = S.rank([off_topic_tier1, on_topic_tier3], "BTA U classification")
    assert [r["url"] for r in ranked] == ["https://radiopaedia.org/bta-u", "https://acr.org/unrelated"]


def test_rank_without_name_skips_the_on_topic_check():
    off_topic_tier1 = {"url": "https://acr.org/unrelated", "title": "Unrelated ATA thyroid paper",
                        "content": "nothing about BTA here", "score": 0.9}
    on_topic_tier3 = {"url": "https://radiopaedia.org/bta-u", "title": "BTA U classification overview",
                       "content": "BTA U classification", "score": 0.4}
    ranked = S.rank([on_topic_tier3, off_topic_tier1])
    assert [r["url"] for r in ranked] == ["https://acr.org/unrelated", "https://radiopaedia.org/bta-u"]


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


async def test_gather_dedupes_and_extracts_top_four(monkeypatch):
    calls = {"search": [], "extract": []}

    async def fake_search(q):
        calls["search"].append(q)
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.5, "content": "s"},
                {"url": "https://radiopaedia.org/a", "title": "A", "score": 0.9, "content": "s"},
                {"url": "https://pmc.ncbi.nlm.nih.gov/c", "title": "C", "score": 0.7, "content": "s"},
                {"url": "https://acr.org/d", "title": "D", "score": 0.6, "content": "s"},
                {"url": "https://esur.org/e", "title": "E", "score": 0.55, "content": "s"}]

    async def fake_extract(urls):
        calls["extract"].append(urls)
        return {u: f"text of {u}" * 300 for u in urls}   # well over MIN_EXTRACT_CHARS
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, sources = await S.gather(["q1", "q2"], branch="Solid")
    assert len(calls["extract"]) == 1 and len(calls["extract"][0]) == S.TOP_URLS == 4
    assert [c.url for c in chunks] == ["https://acr.org/d", "https://esur.org/e", "https://pubs.rsna.org/b",
                                        "https://pmc.ncbi.nlm.nih.gov/c"]
    assert chunks[0].branch == "Solid" and sources[0].tier == 1


async def test_gather_falls_back_to_search_content_when_extract_fails(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://x.org/a", "title": "A", "score": 0.5, "content": "search snippet text"}]

    async def fake_extract(urls):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert chunks[0].text == "search snippet text"


async def test_gather_dedupes_canonical_duplicates_across_queries(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.9, "content": "s"},
                {"url": "https://pubs.rsna.org/b/", "title": "B dup", "score": 0.8, "content": "s"}]

    async def fake_extract(urls):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q1", "q2"], branch="")
    assert len(chunks) == 1


async def test_gather_skips_excluded_urls(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/known", "title": "Known", "score": 0.9, "content": "s"},
                {"url": "https://pubs.rsna.org/new", "title": "New", "score": 0.8, "content": "s"}]

    async def fake_extract(urls):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="", exclude={"https://pubs.rsna.org/known"})
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/new"]


async def test_gather_passes_name_into_the_on_topic_ranking(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://acr.org/unrelated", "title": "Unrelated ATA thyroid paper",
                  "content": "nothing about BTA here" * 300, "score": 0.9},
                {"url": "https://radiopaedia.org/bta-u", "title": "BTA U classification overview",
                 "content": "BTA U classification" * 300, "score": 0.4}]

    async def fake_extract(urls):
        return {u: f"full text of {u}" * 300 for u in urls}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="Solid", name="BTA U classification")
    assert [c.url for c in chunks] == ["https://radiopaedia.org/bta-u", "https://acr.org/unrelated"]


async def test_gather_with_no_name_does_not_demote_off_topic_results(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://acr.org/unrelated", "title": "Unrelated ATA thyroid paper",
                  "content": "nothing about BTA here" * 300, "score": 0.9},
                {"url": "https://radiopaedia.org/bta-u", "title": "BTA U classification overview",
                 "content": "BTA U classification" * 300, "score": 0.4}]

    async def fake_extract(urls):
        return {u: f"full text of {u}" * 300 for u in urls}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="Solid")   # name="" -> on-topic check skipped
    assert [c.url for c in chunks] == ["https://acr.org/unrelated", "https://radiopaedia.org/bta-u"]


async def test_gather_drops_results_below_the_relevance_floor(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/weak", "title": "weak", "score": 0.1, "content": "s"},
                {"url": "https://pubs.rsna.org/strong", "title": "strong", "score": 0.9, "content": "s"}]

    async def fake_extract(urls):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/strong"]


async def test_gather_calls_extract_without_query_and_caps_each_page(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.9, "content": "s"}]
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    captured = {}

    class FakeClient:
        def __init__(self, key):
            pass

        async def extract(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": [{"url": "https://pubs.rsna.org/b", "raw_content": "x" * (S.PAGE_MAX + 5000)}]}
    monkeypatch.setattr(tavily, "AsyncTavilyClient", FakeClient)
    chunks, _ = await S.gather(["q"], branch="")
    assert "query" not in captured["kwargs"] and "chunks_per_source" not in captured["kwargs"]
    assert captured["kwargs"]["extract_depth"] == "advanced"
    assert len(chunks[0].text) == S.PAGE_MAX


_FIVE_TIER1 = [{"url": "https://pubs.rsna.org/a", "title": "a", "score": 0.95, "content": "snippet a"},
               {"url": "https://acr.org/b", "title": "b", "score": 0.9, "content": "snippet b"},
               {"url": "https://esur.org/c", "title": "c", "score": 0.85, "content": "snippet c"},   # the "short" one
               {"url": "https://ajronline.org/d", "title": "d", "score": 0.8, "content": "snippet d"},
               {"url": "https://bir.org.uk/e", "title": "e", "score": 0.7, "content": "snippet e"}]   # refill candidate


async def test_gather_refills_a_short_extract_with_the_next_candidate(monkeypatch):
    async def fake_search(q):
        return list(_FIVE_TIER1)
    monkeypatch.setattr(S, "_search", fake_search)
    calls = []

    async def fake_extract(urls):
        calls.append(urls)
        full = "full page text " * 300
        if len(urls) == 4:   # the first round: top 4, with esur.org/c coming back short
            return {u: ("too short" if u == "https://esur.org/c" else full) for u in urls}
        return {u: full for u in urls}   # the one-URL refill round
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert len(calls) == 2 and calls[1] == ["https://bir.org.uk/e"]   # refilled with the next ranked candidate
    urls = [c.url for c in chunks]
    assert "https://bir.org.uk/e" in urls and "https://esur.org/c" not in urls and len(urls) == 4


async def test_gather_keeps_the_short_page_and_its_snippet_when_the_replacement_also_fails(monkeypatch):
    async def fake_search(q):
        return list(_FIVE_TIER1)
    monkeypatch.setattr(S, "_search", fake_search)

    async def fake_extract(urls):
        full = "full page text " * 300
        if len(urls) == 4:
            return {u: ("too short" if u == "https://esur.org/c" else full) for u in urls}
        return {}   # the refill round also fails
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    urls = [c.url for c in chunks]
    assert "https://esur.org/c" in urls and "https://bir.org.uk/e" not in urls
    assert next(c for c in chunks if c.url == "https://esur.org/c").text == "snippet c"


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


async def test_extract_sends_no_query_or_chunks_per_source_and_caps_at_page_max(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    captured = {}

    class FakeClient:
        def __init__(self, key):
            pass

        async def extract(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": [{"url": "https://a", "raw_content": "x" * (S.PAGE_MAX + 1000)}]}
    monkeypatch.setattr(tavily, "AsyncTavilyClient", FakeClient)
    out = await S._extract(["https://a"])
    assert "query" not in captured["kwargs"] and "chunks_per_source" not in captured["kwargs"]
    assert captured["kwargs"]["extract_depth"] == "advanced"
    assert captured["kwargs"]["timeout"] == S.EXTRACT_TIMEOUT_S
    assert len(out["https://a"]) == S.PAGE_MAX


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
