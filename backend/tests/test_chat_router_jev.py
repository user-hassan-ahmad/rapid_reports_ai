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
    assert all(J.QUESTIONS[k]["type"] == "noul" and J.QUESTIONS[k]["instructions"].startswith("Does the INSTRUCTION")
               for k in ("value", "concept", "fixed", "normal", "layout", "style"))
    assert (J.TAG_MIN, J.REQUIRES_MIN) == (0.5, 0.5)


def test_the_wording_lab_arms_are_used_word_for_word():
    """fixed_B, misfit_B, value_A and requires_A from the wording lab (2026-10-13, synthetic/chat_router/wording_lab.py)."""
    assert J.QUESTIONS["fixed"] == {"type": "noul", "instructions": (
        "Does the INSTRUCTION ask to change, add or remove one of the report's standing boilerplate sentences "
        "(text printed word for word in every report whatever the findings), rather than a finding, a normal "
        "statement, a value, the comparison or contrast wording, or the style?")}
    assert J.QUESTIONS["misfit"] == {"type": "noul", "instructions": (
        "Is the INSTRUCTION clearly unrelated to reports of this SCAN TYPE: asking for content this scan "
        "cannot show, from another body region, modality or kind of document? A request to add, require or "
        "mention something this scan could plausibly assess is not unrelated.")}
    assert J.QUESTIONS["value"] == {
        "type": "noul", "instructions": "Does the INSTRUCTION ask to change which measured values every report must state?",
        "criteria": {"true": "Yes: it adds, removes or changes a required measurement or numeric value (a size, volume, "
                             "fraction, score, grade or level) that every report must give, or says one is needed only "
                             "when relevant.",
                     "false": "No: it asks to always mention a finding, structure or normal statement, sets a habit "
                              "triggered by a finding (when X is present, always say Y), or is about wording, layout or "
                              "style."}}
    assert J.REQUIRES == {
        "type": "noul",
        "instructions": "Does this LINE require the report to state something that the report could otherwise leave out?",
        "criteria": {"true": "Yes: it makes a finding, structure, value, comparison or statement mandatory in every "
                             "report, or in every report of a kind.",
                     "false": "No: it only governs the order, format, units, precision, sentence length, tone or "
                              "phrasing of what is reported."}}


async def test_the_tag_call_sends_each_question_spec_as_is():
    seen = []
    t = _transport(lambda body: {k: {"noul": 0.1} for k in body["questions"]}, seen)
    await J.tag("x", "", transport=t)
    assert seen[0]["questions"]["value"] == J.QUESTIONS["value"]   # criteria included
    assert seen[0]["state"].startswith("SCAN TYPE: not given\n\nINSTRUCTION:\nx")


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
    assert len(seen) == 2 and seen[0]["questions"]["q"] == J.REQUIRES
    assert await J.requires([], transport=t) == []
