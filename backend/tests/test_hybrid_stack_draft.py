import json

import httpx

from rapid_reports_ai.hybrid_stack import draft as D


def test_clean_strips_headings_bullets_and_reasoning():
    assert D.clean("<think>x</think>\nImpression:\n- Acute sigmoid diverticulitis.") == "Acute sigmoid diverticulitis."
    assert D.clean('"No acute abnormality."') == "No acute abnormality."


async def test_draft_sends_findings_and_returns_text(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Acute sigmoid diverticulitis."}}]})
    out = await D.draft_conclusion("CT AP", "LIF pain", "Bowel: Sigmoid wall thickening.", transport=httpx.MockTransport(handler))
    assert out.text == "Acute sigmoid diverticulitis." and out.error is None
    assert seen["reasoning_effort"] == "low" and "Sigmoid wall thickening." in seen["messages"][1]["content"]


async def test_draft_fails_open():
    assert (await D.draft_conclusion("CT", "", "  ")).error == "no findings"

    def handler(req):
        return httpx.Response(500)
    out = await D.draft_conclusion("CT", "", "x", transport=httpx.MockTransport(handler))
    assert out.text == "" and out.error
