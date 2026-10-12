import json

import httpx

from rapid_reports_ai.hybrid_stack.copilot import jev as J


def _jev(scores: dict[str, float], seen: dict):
    def handler(req):
        body = json.loads(req.content)
        seen.update(body)
        return httpx.Response(200, json={"answers": {k: {"noul": scores.get(k, 0.0)} for k in body["questions"]}})
    return httpx.MockTransport(handler)


async def test_coverage_one_call_one_question_per_branch(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    out = await J.coverage("chunk text", ["Solid", "Subsolid"], transport=_jev({"b_0": 0.9, "b_1": 0.2}, seen))
    assert out == {"Solid": 0.9, "Subsolid": 0.2}
    assert "Subsolid" in seen["questions"]["b_1"]["instructions"] and seen["state"].startswith("SOURCE:")


def test_exact_quote_normalises_whitespace_and_case():
    assert J.quote_in("Nodules  <6 mm:\nNo routine follow-up", "nodules <6 mm: no ROUTINE follow-up")
    assert not J.quote_in("Nodules <6 mm", "Nodules <8 mm")
    assert not J.quote_in("x", "")


async def test_evidence_skips_jev_for_exact_quotes(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    claims = [("No routine follow-up", "exact"), ("CT at 3 months", "reworded claim")]
    scores = await J.evidence("SOURCE … No routine follow-up …", claims, transport=_jev({"c_1": 0.85}, seen))
    assert scores == [1.0, 0.85]
    assert list(seen["questions"]) == ["c_1"]


async def test_evidence_without_jev_need_makes_no_call():
    assert await J.evidence("abc", [("abc", "abc")]) == [1.0]


async def test_answers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    assert await J.answers("material", "Does X change it?", transport=_jev({"q": 0.75}, seen)) == 0.75


def test_state_is_capped():
    assert len(J._state("x" * 50000)) <= J.STATE_MAX + 20
