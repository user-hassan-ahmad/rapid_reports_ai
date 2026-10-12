import json

import httpx

from rapid_reports_ai.hybrid_stack.family import NONE, choose_family


async def test_offers_families_plus_none_and_returns_choice(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"family": {"choice": "knee", "confidence": 0.97}}})
    choice, conf = await choose_family("MRI right knee", "", transport=httpx.MockTransport(handler))
    crit = seen[0]["questions"]["family"]["criteria"]
    assert (choice, conf) == ("knee", 0.97)
    assert NONE in crit and "generic" not in crit and "abdomen_pelvis" in crit
