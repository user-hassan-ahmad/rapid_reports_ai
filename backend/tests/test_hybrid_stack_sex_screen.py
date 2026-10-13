import json

import httpx

from rapid_reports_ai.hybrid_stack import sex_screen as X


def _jev(scores):
    def handler(req):
        s = json.loads(req.content)["state"].removeprefix("SENTENCE: ")
        return httpx.Response(200, json={"answers": {"q": {"noul": scores.get(s, 0.02)}}})
    return httpx.MockTransport(handler)


async def test_drops_flags_and_keeps(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    t = _jev({"The prostate is normal.": 0.95, "No hydrocele.": 0.6})
    r = await X.screen(["Cervical lordosis is preserved.", "The prostate is normal.", "No hydrocele."], transport=t)
    assert r.kept == ["Cervical lordosis is preserved.", "No hydrocele."]
    assert r.dropped == ["The prostate is normal."] and r.flagged == ["No hydrocele."]


async def test_jev_failure_uses_backstop_without_cervical(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    t = httpx.MockTransport(lambda req: httpx.Response(500))
    r = await X.screen(["No cervical lymphadenopathy.", "The uterus is normal."], transport=t)
    assert r.kept == ["No cervical lymphadenopathy."] and r.dropped == ["The uterus is normal."]


async def test_screen_normals_removes_empty_regions(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    t = _jev({"The ovaries are normal.": 0.97})
    kept, flagged = await X.screen_normals({"Pelvic organs": ["The ovaries are normal."], "Bladder": ["Normal."]}, t)
    assert kept == {"Bladder": ["Normal."]} and flagged == []


def test_clean_sentences_no_longer_screens_sex_terms():
    from rapid_reports_ai.hybrid_stack.slim_sheet import clean_sentences
    assert clean_sentences(["No cervical lymphadenopathy", "The prostate is normal."]) == [
        "No cervical lymphadenopathy.", "The prostate is normal."]


async def test_malformed_200_reply_uses_backstop(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    bodies = {"The uterus is normal.": {"answers": {}},
              "The prostate is normal.": {"answers": {"q": {"noul": "high"}}},
              "No cervical lymphadenopathy.": {"answers": {"q": {}}},
              "The ovaries are normal.": {}}

    def handler(req):
        return httpx.Response(200, json=bodies[json.loads(req.content)["state"].removeprefix("SENTENCE: ")])
    r = await X.screen(list(bodies), transport=httpx.MockTransport(handler))
    assert r.dropped == ["The uterus is normal.", "The prostate is normal.", "The ovaries are normal."]
    assert r.kept == ["No cervical lymphadenopathy."] and r.flagged == []
