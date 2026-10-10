import json

import httpx

from rapid_reports_ai.hybrid_stack import reconciler as R
from rapid_reports_ai.hybrid_stack.schemas import OTHER


def _llm(content: dict, seen: list | None = None):
    def handler(req):
        if seen is not None:
            seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})
    return httpx.MockTransport(handler)


async def test_keeps_a_family_as_is(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    seen = []
    res = await R.reconcile("MRI right knee", "", transport=_llm({"family": "knee"}, seen))
    assert res.family == "knee" and res.regions[-1].name == OTHER
    body = seen[0]
    assert body["reasoning_effort"] == "medium" and body["response_format"] == {"type": "json_object"}
    assert "Title Case" in body["messages"][1]["content"]


async def test_composes_reuses_and_validates(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    out = {"regions": [{"key": "biceps"}, {"key": "nope"}, {"name": "Syndesmosis", "includes": "tibiofibular ligaments"},
                       {"name": "Incidental Findings", "includes": "x"}, {"name": "syndesmosis", "includes": "dup"},
                       {"key": "other"}]}
    res = await R.reconcile("MRI ankle", "", transport=_llm(out))
    names = [r.name for r in res.regions]
    assert names == ["Biceps", "Syndesmosis", OTHER]
    assert res.family is None and res.log["new"] == ["Syndesmosis"] and len(res.log["dropped"]) == 4


async def test_new_regions_are_capped(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    out = {"regions": [{"name": f"Region {i}", "includes": "x"} for i in range(12)]}
    res = await R.reconcile("MRI x", "", transport=_llm(out))
    assert len(res.regions) == R.MAX_NEW_REGIONS + 1
