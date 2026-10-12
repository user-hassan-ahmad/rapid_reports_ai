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


def test_tier_ranking():
    assert S.tier("https://pubs.rsna.org/doi/10.1148/radiol.2017161659") == 1
    assert S.tier("https://www.rcr.ac.uk/x") == 1
    assert S.tier("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/") == 2
    assert S.tier("https://radiopaedia.org/articles/x") == 3
    ranked = S.rank([{"url": "https://radiopaedia.org/a", "score": 0.9}, {"url": "https://pubs.rsna.org/b", "score": 0.5},
                     {"url": "https://pmc.ncbi.nlm.nih.gov/c", "score": 0.7}])
    assert [r["url"] for r in ranked] == ["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c", "https://radiopaedia.org/a"]


async def test_gather_dedupes_and_extracts_top_two(monkeypatch):
    calls = {"search": [], "extract": []}

    async def fake_search(q):
        calls["search"].append(q)
        return [{"url": "https://pubs.rsna.org/b", "title": "B", "score": 0.5, "content": "s"},
                {"url": "https://radiopaedia.org/a", "title": "A", "score": 0.9, "content": "s"},
                {"url": "https://pmc.ncbi.nlm.nih.gov/c", "title": "C", "score": 0.7, "content": "s"}]

    async def fake_extract(urls):
        calls["extract"].append(urls)
        return {u: f"text of {u}" for u in urls}
    monkeypatch.setattr(S, "_search", fake_search)
    monkeypatch.setattr(S, "_extract", fake_extract)
    chunks, sources = await S.gather(["q1", "q2"], branch="Solid")
    assert calls["extract"] == [["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c"]]
    assert [c.url for c in chunks] == ["https://pubs.rsna.org/b", "https://pmc.ncbi.nlm.nih.gov/c"]
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
