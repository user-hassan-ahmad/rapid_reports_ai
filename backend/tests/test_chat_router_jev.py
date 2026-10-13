"""The router's Jev questions (spec Flow 1 and 3)."""
import json

import httpx
import pytest

from rapid_reports_ai import chat_router_jev as J


def _transport(answers, seen):
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": answers(body)})
    return httpx.MockTransport(handler)


def test_the_seven_questions_are_the_specs():
    assert J.KINDS == ("value", "concept", "fixed", "normal", "layout", "style", "misfit")
    assert all(J.QUESTIONS[k].startswith("Does the INSTRUCTION ask") for k in J.KINDS)
    assert "values every report must state" in J.QUESTIONS["value"]
    assert "does not belong in a report of this scan type" in J.QUESTIONS["misfit"]
    assert (J.TAG_UNSURE, J.TAG_MIN, J.REQUIRES_MIN) == (0.35, 0.5, 0.5)


async def test_tag_asks_all_kinds_in_one_call_with_the_scan_type_and_context():
    seen = []
    scores = {k: 0.1 * i for i, k in enumerate(J.KINDS)}
    t = _transport(lambda body: {k: {"noul": scores[k]} for k in body["questions"]}, seen)
    out = await J.tag("drop width and keep it short", "Router test", context="Done.", transport=t)
    assert out == scores and len(seen) == 1
    assert "SCAN TYPE: Router test" in seen[0]["state"] and "drop width" in seen[0]["state"]
    assert "PREVIOUS REPLY" in seen[0]["state"]
    assert all(q["type"] == "noul" for q in seen[0]["questions"].values())


async def test_tag_raises_on_incomplete_answers():
    t = _transport(lambda body: {"value": {"noul": 0.9}}, [])
    with pytest.raises(ValueError):
        await J.tag("x", "", transport=t)


async def test_requires_asks_one_call_per_line_in_order():
    seen = []
    t = _transport(lambda body: {"q": {"noul": 0.9 if "Always" in body["state"] else 0.1}}, seen)
    assert await J.requires(["Keep it brief.", "Always state the size."], transport=t) == [0.1, 0.9]
    assert len(seen) == 2 and seen[0]["questions"]["q"]["instructions"] == J.REQUIRES
    assert await J.requires([], transport=t) == []
