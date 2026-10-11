import json

import httpx

from rapid_reports_ai.hybrid_stack import jev_stack as J


def test_decide_accept_needs_a_named_chip_and_a_non_dictate_command():
    assert J.decide_command({"command": "correct", "confidence": 0.3, "region": None, "chip": "No free gas."}) == {
        "action": "accept", "region": None, "chip": "No free gas."}
    assert J.decide_command({"command": "dictate", "confidence": 0.9, "region": None, "chip": "No free gas."})["action"] == "dictate"
    assert J.decide_command({"command": "accept_suggestion", "confidence": 0.9, "region": None, "chip": None})["action"] == "dictate"


def test_decide_delete_at_threshold_keeps_the_region():
    d = J.decide_command({"command": "delete", "confidence": 0.6, "region": "Liver", "chip": None})
    assert d == {"action": "delete", "region": "Liver", "chip": None}
    assert J.decide_command({"command": "delete", "confidence": 0.59, "region": "Liver", "chip": None})["action"] == "dictate"


def test_decide_correct_and_send_to_region_are_dictation():
    for c in ("correct", "send_to_region", None):
        assert J.decide_command({"command": c, "confidence": 1.0, "region": "Liver", "chip": None})["action"] == "dictate"


async def test_ask_command_payload_and_parse(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {
            "command": {"choice": "accept_suggestion", "confidence": 0.8},
            "target_region": {"choice": "none"}, "target_chip": {"choice": "chip_1"}}})
    out = await J.ask_command("The liver is normal.", "Accept no ascites.", ["Liver", "Peritoneum"],
                              ["No free gas.", "No ascites."], transport=httpx.MockTransport(handler))
    assert set(seen["questions"]) == {"command", "target_region", "target_chip"}
    assert "LATEST UTTERANCE:\nAccept no ascites." in seen["state"]
    assert out == {"command": "accept_suggestion", "confidence": 0.8, "region": None, "chip": "No ascites."}


async def test_ask_stated_returns_one_score_per_chip(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def handler(req):
        body = json.loads(req.content)
        assert list(body["questions"]) == ["chip_0", "chip_1"]
        return httpx.Response(200, json={"answers": {"chip_0": {"noul": 0.9}, "chip_1": {"noul": 0.1}}})
    assert await J.ask_stated("No free gas.", ["No free gas.", "No ascites."],
                              transport=httpx.MockTransport(handler)) == [0.9, 0.1]
    assert await J.ask_stated("x", []) == []
