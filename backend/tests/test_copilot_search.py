import json

import httpx
import tavily

from rapid_reports_ai.hybrid_stack.copilot import fetch as F
from rapid_reports_ai.hybrid_stack.copilot import jev as J

from rapid_reports_ai.hybrid_stack.copilot import search as S
from rapid_reports_ai.hybrid_stack.copilot.types import Chunk, Publication


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

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
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

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert chunks[0].text == "search snippet text"


async def test_gather_dedupes_canonical_duplicates_across_queries(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.9, "content": "s"},
                {"url": "https://pubs.rsna.org/b/", "title": "B dup", "score": 0.8, "content": "s"}]

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q1", "q2"], branch="")
    assert len(chunks) == 1


async def test_gather_skips_excluded_urls(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/known", "title": "Known", "score": 0.9, "content": "s"},
                {"url": "https://pubs.rsna.org/new", "title": "New", "score": 0.8, "content": "s"}]

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        return {}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="", exclude={"https://pubs.rsna.org/known"})
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/new"]


async def test_gather_drops_results_below_the_relevance_floor(monkeypatch):
    async def fake_search(q):
        return [{"url": "https://pubs.rsna.org/weak", "title": "weak", "score": 0.1, "content": "s"},
                {"url": "https://pubs.rsna.org/strong", "title": "strong", "score": 0.9, "content": "s"}]

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
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

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
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

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
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
    assert await S._extract(["https://a"]) is None   # a failure, as opposed to {} for "nothing came back"


def test_one_page_is_one_window_and_six_pages_fit_without_dropping(caplog):
    """4 max-size first-pass pages + 2 retry pages, joined the way fetch joins them: every page is its own window,
    the count stays within WINDOW_CAP, and nothing is cut or dropped."""
    pages = [Chunk(url=f"https://pubs.rsna.org/p{i}", text=chr(ord("a") + i) * S.PAGE_MAX, branch="b") for i in range(6)]
    text = F._text(pages)
    windows = J._windows(text)
    assert len(windows) <= J.WINDOW_CAP
    assert "dropping" not in caplog.text
    joined = "\n\n".join(windows)
    for c in pages:
        assert f"[{c.url}]\n{c.text}" in joined


_GATED = [{"url": "https://pubs.rsna.org/other", "title": "A different guideline", "score": 0.95, "content": "other"},
          {"url": "https://radiopaedia.org/this", "title": "This guideline", "score": 0.4, "content": "this"}]


async def test_relevance_gate_ranks_an_irrelevant_tier_one_below_a_relevant_tier_three(monkeypatch):
    async def fake_search(q):
        return list(_GATED)

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        return {u: "full page text " * 300 for u in urls}
    seen = {}

    async def fake_ask(state, questions, transport=None):
        seen["state"], seen["questions"] = state, questions
        return {"r_0": 0.1, "r_1": 0.9}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    monkeypatch.setattr(J, "_ask", fake_ask)
    chunks, _ = await S.gather(["q"], branch="B", name="Sys", version="2", title="The Paper")
    assert [c.url for c in chunks] == ["https://radiopaedia.org/this", "https://pubs.rsna.org/other"]
    assert seen["questions"]["r_1"]["instructions"] == \
        "Result [1] is about Sys 2 (The Paper), not a different guideline or topic."
    assert "[0] A different guideline — https://pubs.rsna.org/other — other" in seen["state"]
    assert "[1] This guideline — https://radiopaedia.org/this — this" in seen["state"]


async def test_relevance_gate_failure_falls_back_to_tier_and_score(monkeypatch):
    async def fake_search(q):
        return list(_GATED)

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        return {u: "full page text " * 300 for u in urls}

    async def down(state, questions, transport=None):
        raise ValueError("jev response has no answers")
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    monkeypatch.setattr(J, "_ask", down)
    chunks, _ = await S.gather(["q"], branch="B", name="Sys", version="2")
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/other", "https://radiopaedia.org/this"]


async def test_no_name_makes_no_relevance_call(monkeypatch):
    async def fake_search(q):
        return list(_GATED)

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        return {u: "full page text " * 300 for u in urls}

    async def ask(*a, **k):
        raise AssertionError("no Jev call without a name")
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    monkeypatch.setattr(J, "_ask", ask)
    chunks, _ = await S.gather(["q"], branch="B")
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/other", "https://radiopaedia.org/this"]


def test_rank_puts_irrelevant_results_after_tier_four():
    results = [{"url": "https://acr.org/off", "score": 0.9}, {"url": "https://pubmed.ncbi.nlm.nih.gov/1/", "score": 0.1}]
    ranked = S.rank(results, {"https://acr.org/off": 0.2, "https://pubmed.ncbi.nlm.nih.gov/1/": 0.8})
    assert [r["url"] for r in ranked] == ["https://pubmed.ncbi.nlm.nih.gov/1/", "https://acr.org/off"]


async def test_no_refill_when_the_first_extract_failed(monkeypatch):
    async def fake_search(q):
        return list(_FIVE_TIER1)
    calls = []

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        calls.append(urls)
        return None   # Tavily down
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    assert len(calls) == 1 and [c.text for c in chunks] == ["snippet a", "snippet b", "snippet c", "snippet d"]


async def test_refill_uses_the_shorter_timeout(monkeypatch):
    async def fake_search(q):
        return list(_FIVE_TIER1)
    timeouts = []

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        timeouts.append(timeout)
        full = "full page text " * 300
        return {u: ("short" if u == "https://esur.org/c" else full) for u in urls}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    await S.gather(["q"], branch="")
    assert timeouts == [S.EXTRACT_TIMEOUT_S, S.REFILL_TIMEOUT_S] and S.REFILL_TIMEOUT_S == 25


async def test_refill_rejects_a_replacement_no_better_than_the_short_page(monkeypatch):
    async def fake_search(q):
        return list(_FIVE_TIER1)
    short_c = "c" * 900

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        full = "full page text " * 300
        if len(urls) == 4:
            return {u: (short_c if u == "https://esur.org/c" else full) for u in urls}
        return {u: "e" * 500 for u in urls}   # shorter than MIN_EXTRACT_CHARS and than c's extract
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    by = {c.url: c.text for c in chunks}
    assert "https://bir.org.uk/e" not in by and by["https://esur.org/c"] == short_c   # extract longer than snippet


async def test_refill_takes_a_replacement_longer_than_the_short_page(monkeypatch):
    async def fake_search(q):
        return list(_FIVE_TIER1)

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        full = "full page text " * 300
        if len(urls) == 4:
            return {u: ("c" * 300 if u == "https://esur.org/c" else full) for u in urls}
        return {u: "e" * 800 for u in urls}   # under MIN_EXTRACT_CHARS but longer than c's extract
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="")
    urls = [c.url for c in chunks]
    assert "https://bir.org.uk/e" in urls and "https://esur.org/c" not in urls


async def test_gather_top_limits_the_pages_read(monkeypatch):
    calls = []

    async def fake_search(q):
        return [{"url": f"https://acr.org/{i}", "title": "T", "score": 0.9 - i / 10, "content": "s"} for i in range(5)]

    async def fake_extract(urls, timeout=S.EXTRACT_TIMEOUT_S):
        calls.append(urls)
        return {u: "x" * S.MIN_EXTRACT_CHARS for u in urls}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, _ = await S.gather(["q"], branch="", top=2)
    assert calls == [["https://acr.org/0", "https://acr.org/1"]] and len(chunks) == 2


def test_safe_identity_drops_measurements_and_case_words_keeps_version():
    assert S.safe_identity("Management of 2 cm left adrenal nodule", "2017") == ("Management of adrenal nodule", "2017")
    assert S.safe_identity("Fleischner", "2017") == ("Fleischner", "2017")
    assert S.safe_identity("Guideline for 45 year-old female smoker", "v2.1") == ("Guideline for", "v2.1")
    assert S.safe_identity("a b c d e f g h i j", "") == ("a b c d e f g h", "")
    assert S.safe_identity("Bosniak", "2019") == ("Bosniak", "2019")


def test_query_builders_go_through_safe_identity():
    for q in S.first_pass_queries("Management of 2 cm left adrenal nodule", "", Publication(), "Adenoma") + \
            [S.branch_query("Management of 2 cm left adrenal nodule", "", "Adenoma")]:
        assert "2 cm" not in q and "left" not in q.split() and "adrenal nodule" in q


def test_first_pass_scrubs_the_publication_title_keeps_year_and_version_digits():
    pub = Publication(title="Management of 2 cm left adrenal nodule in a 45 year-old female: 2017 white paper v2",
                      year="2017")
    q = S.first_pass_queries("ACR", "2017", pub, "")[0]
    assert q == '"Management of adrenal nodule in a 2017 white paper v2" 2017'
    long_title = Publication(title="One two three four five six seven eight nine ten eleven 2019", year="2019")
    assert S.first_pass_queries("X", "", long_title, "")[0] == f'"{long_title.title}" 2019'   # no word cap on a title
