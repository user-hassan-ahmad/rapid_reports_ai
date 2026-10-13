import json
from pathlib import Path

import httpx
import pytest

from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB
from rapid_reports_ai.hybrid_stack.protocol_library import match as M

FIX = Path(__file__).parent / "fixtures" / "protocol_bundle_fixture.json"


@pytest.fixture
def b():
    return PB.load_bundle(FIX)


def test_protocol_line(b):
    assert M.protocol_line(b.entry("TCTH")) == "No contrast"
    assert M.protocol_line(b.entry("TCAPT")) == "IV contrast · unenhanced, arterial, portal venous"
    assert M.protocol_line(b.entry("TCAP"), ["arterial", "portal_venous"]) == "IV contrast · arterial, portal venous"
    assert M.protocol_line(b.entry("TMBR")) == "Gadolinium · DCE"


def test_local_search_abbreviation_partial_misspelling(b):
    assert M.local_search(b, "ctap")[0][1].id == "TCAP"
    assert M.local_search(b, "cth")[0][1].id == "TCTH"
    assert M.local_search(b, "mri kn")[0][1].id == "TMKN"
    assert M.local_search(b, "mri lt knee")[0][1].id == "TMKN"   # laterality words ignored
    assert M.local_search(b, "mri whol spine")[0][1].id == "TMWS"  # one-edit typo


def test_local_search_empty_and_long(b):
    assert M.local_search(b, "") == []
    assert M.local_search(b, "   ") == []
    assert len(M.local_search(b, "x" * 5000)) <= 10


def _jev(choice, conf):
    def handler(req):
        body = json.loads(req.content)
        assert "pick" in body["questions"]
        crit = body["questions"]["pick"]["criteria"]
        assert "none" in crit and "also typed as" in next(iter(crit.values()))
        return httpx.Response(200, json={"answers": {"pick": {"choice": choice, "confidence": conf}}})
    return httpx.MockTransport(handler)


async def test_search_promotes_confident_jev_pick(b, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    r = await M.search(b, "ct ap", rerank_on=True, transport=_jev("TCAPT", 0.95))
    assert r.options[0].id == "TCAPT" and r.promoted == "TCAPT"


async def test_search_keeps_local_order_below_floor(b, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    r = await M.search(b, "ct ap", rerank_on=True, transport=_jev("TCAPT", 0.6))
    assert r.options[0].id == "TCAP" and r.promoted is None


async def test_search_confident_none_sets_hint_keeps_options(b, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    r = await M.search(b, "us abdo", rerank_on=True, transport=_jev("none", 0.97))
    assert r.not_listed_hint is True and r.options


async def test_search_jev_failure_falls_back_to_local(b, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    t = httpx.MockTransport(lambda req: httpx.Response(500))
    r = await M.search(b, "ct ap", rerank_on=True, transport=t)
    assert r.options[0].id == "TCAP" and r.promoted is None and r.not_listed_hint is False


async def test_options_carry_variants(b):
    r = await M.search(b, "ctap")
    o = next(o for o in r.options if o.id == "TCAP")
    assert [v.phases for v in o.variants] == [["portal_venous"], ["arterial", "portal_venous"]]
    assert o.variants[0].default is True
