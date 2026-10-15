"""Instruction flag (design 2026-10-15-instruction-flag): an instruction no supported command covers is held for the
radiologist, never written. Off by default; fails open to dictation."""
from __future__ import annotations

import json

import httpx

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.hybrid_stack import jev_stack as J

from tests.test_canvas_bundle_route import BODY, FakeBundle, authed_client, lab  # noqa: F401  (fixtures)


def _parsed(cmd="dictate", conf=0.9, ins=0.0, p_delete=0.0, region=None, chip=None):
    return {"command": cmd, "confidence": conf, "region": region, "chip": chip, "instruction": ins, "p_delete": p_delete}


def test_the_question_is_unchanged_when_the_flag_is_off():
    assert J.command_question(False) is J.COMMAND_QUESTION
    assert J.INSTRUCTION not in J.COMMAND_QUESTION["criteria"]
    on = J.command_question(True)["criteria"]
    assert list(on)[:-1] == list(J.COMMAND_QUESTION["criteria"]) and on[J.INSTRUCTION] == J.INSTRUCTION_CRITERION


def test_flag_reads_the_environment(monkeypatch):
    monkeypatch.delenv("RR_STACK_INSTRUCTION_FLAG", raising=False)
    assert not J.instruction_on()
    for v in ("1", "true", "on"):
        monkeypatch.setenv("RR_STACK_INSTRUCTION_FLAG", v)
        assert J.instruction_on()
    monkeypatch.setenv("RR_STACK_INSTRUCTION_FLAG", "0")
    assert not J.instruction_on()


async def test_ask_command_asks_the_option_in_the_same_call_only_when_on(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"command": {
            "choice": "delete", "confidence": 0.5,
            "probabilities": {"delete": 0.5, "instruction": 0.42, "dictate": 0.08}}}})
    t = httpx.MockTransport(handler)
    monkeypatch.setenv("RR_STACK_INSTRUCTION_FLAG", "1")
    on = await J.ask_command("Liver normal.", "Delete all the other sections.", [], [], transport=t)
    assert J.INSTRUCTION in seen[0]["questions"]["command"]["criteria"] and len(seen) == 1
    assert on["instruction"] == 0.42 and on["p_delete"] == 0.5
    monkeypatch.delenv("RR_STACK_INSTRUCTION_FLAG")
    off = await J.ask_command("Liver normal.", "Delete all the other sections.", [], [], transport=t)
    assert J.INSTRUCTION not in seen[1]["questions"]["command"]["criteria"]
    assert off == {"command": "delete", "confidence": 0.5, "region": None, "chip": None}


def test_option_p_falls_back_to_the_choice_confidence():
    assert J.option_p({"choice": "instruction", "confidence": 0.9}, J.INSTRUCTION) == 0.9
    assert J.option_p({"choice": "dictate", "confidence": 0.9}, J.INSTRUCTION) == 0.0


def test_held_at_the_bar_on_instruction_plus_an_unactionable_delete():
    bar = J.INSTRUCTION_MIN
    assert J.decide_command(_parsed("instruction", ins=bar))["action"] == "instruction"
    assert J.decide_command(_parsed("instruction", ins=bar - 0.01))["action"] == "dictate"
    # P3: "Delete all the other sections." splits between delete (no region) and instruction
    assert J.decide_command(_parsed("delete", conf=0.5, ins=0.42, p_delete=0.5))["action"] == "instruction"


def test_supported_commands_still_win():
    # a delete that names a region is carried out, whatever the instruction score
    d = J.decide_command(_parsed("delete", conf=0.9, ins=0.05, p_delete=0.9, region="Liver"))
    assert d == {"action": "delete", "region": "Liver", "chip": None}
    a = J.decide_command(_parsed("accept_suggestion", conf=0.5, ins=0.9, chip="No free gas."))
    assert a["action"] == "accept"
    # below the bar a region-less delete stays a delete (the bundle's own route decides), as today
    assert J.decide_command(_parsed("delete", conf=0.7, ins=0.0, p_delete=0.7))["action"] == "delete"


def test_flag_off_decisions_are_todays():
    assert J.decide_command({"command": "delete", "confidence": 0.9, "region": None, "chip": None}) == {
        "action": "delete", "region": None, "chip": None}
    assert J.decide_command({"command": "instruction", "confidence": 1.0, "region": None, "chip": None})["action"] == "dictate"


def test_settle_lets_the_bundle_route_win_when_it_does_not_write():
    held = {"action": "instruction", "region": None, "item": None, "command": "instruction", "confidence": 0.9}
    for route in ("skip", "delete", "command"):
        assert J.settle_instruction(held, route)["action"] == "dictate"
    for route in ("fast_append", "polish"):
        assert J.settle_instruction(held, route)["action"] == "instruction"
    assert J.settle_instruction(None, "polish") is None
    other = {**held, "action": "delete"}
    assert J.settle_instruction(other, "skip") is other


def test_bundle_returns_a_held_instruction(authed_client, lab, monkeypatch):  # noqa: F811
    lab(FakeBundle())

    async def ask(scratchpad, utterance, regions, chips):
        return _parsed("instruction", conf=0.88, ins=0.88, p_delete=0.06)
    monkeypatch.setattr(cr, "ask_command", ask)
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "Delete all the other sections.",
                                                       "stack_regions": ["Lungs"]}).json()
    assert d["route"] == "fast_append"
    assert d["stack_command"] == {"action": "instruction", "region": None, "item": None, "command": "instruction",
                                  "confidence": 0.88, "instruction": 0.94}


def test_a_polished_final_is_still_held(authed_client, lab, monkeypatch):  # noqa: F811
    # the bundle routes fillers and "scratch that"-like finals to polish, which writes text: the hold still applies
    lab(FakeBundle(action="ignore_noise"))

    async def ask(scratchpad, utterance, regions, chips):
        return _parsed("instruction", conf=0.95, ins=0.95)
    monkeypatch.setattr(cr, "ask_command", ask)
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "Hmm, where was I.",
                                                       "stack_regions": ["Lungs"]}).json()
    assert d["route"] == "polish" and d["stack_command"]["action"] == "instruction"
