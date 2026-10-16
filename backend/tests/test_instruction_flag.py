"""Instruction flag (design 2026-10-15-instruction-flag): an instruction no supported command covers is held for the
radiologist, never written. Off by default; fails open to dictation."""
from __future__ import annotations

import json

import httpx

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.hybrid_stack import jev_stack as J

from tests.test_canvas_bundle_route import BODY, FakeBundle, authed_client, lab  # noqa: F401  (fixtures)


def _parsed(cmd="dictate", conf=0.9, ins=0.0, p_delete=0.0, region=None, chip=None, named=1.0):
    return {"command": cmd, "confidence": conf, "region": region, "chip": chip, "instruction": ins, "p_delete": p_delete,
            "p_named": named}


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


def test_held_decisions_carry_the_pre_hold_fallback():
    assert J.decide_command(_parsed("instruction", ins=0.95))["fallback"] == "dictate"
    # a region-less delete held as an instruction falls back to the delete it was (an open line drops its words)
    d = J.decide_command(_parsed("delete", conf=0.7, ins=0.2, p_delete=0.7))
    assert d["action"] == "instruction" and d["fallback"] == "delete"
    assert "fallback" not in J.decide_command(_parsed("dictate", ins=0.1))


def test_settle_restores_the_pre_hold_decision_when_the_route_does_not_write():
    held = {"action": "instruction", "fallback": "dictate", "region": None, "item": None, "command": "instruction",
            "confidence": 0.9}
    for route in ("skip", "delete", "command"):
        assert J.settle_instruction(held, route)["action"] == "dictate"
    was_delete = {**held, "fallback": "delete", "command": "delete"}
    assert J.settle_instruction(was_delete, "skip")["action"] == "delete"
    for route in ("fast_append", "polish"):
        assert J.settle_instruction(held, route)["action"] == "instruction"
    assert J.settle_instruction(None, "polish") is None
    other = {**held, "action": "delete"}
    assert J.settle_instruction(other, "skip") is other


def test_bundle_restores_a_region_less_delete_when_not_writing():
    # fallback never leaks into the response
    out = J.settle_instruction({"action": "instruction", "fallback": "delete", "region": None}, "command")
    assert out == {"action": "delete", "region": None}


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
    # a clear instruction the bundle routes to polish (it writes text): the hold still applies
    lab(FakeBundle(action="append_new_finding", conf=0.5))

    async def ask(scratchpad, utterance, regions, chips):
        return _parsed("instruction", conf=0.95, ins=0.95)
    monkeypatch.setattr(cr, "ask_command", ask)
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "Make the conclusion a numbered list.",
                                                       "stack_regions": ["Lungs"]}).json()
    assert d["route"] == "polish" and d["stack_command"]["action"] == "instruction"


# ── Hassan's decisions 2026-10-16 (Q10, Q11, Q15) ─────────────────────────────

def test_q10_an_unclear_delete_is_not_held():
    # "Remove the last sentence." / "Get rid of that.": names no section or statement -> today's delete, no card
    d = J.decide_command(_parsed("delete", conf=0.9, ins=0.05, p_delete=0.9, named=0.1))
    assert d == {"action": "delete", "region": None, "chip": None}
    # Jev unsure between delete and instruction, still naming nothing: today's decision
    assert J.decide_command(_parsed("delete", conf=0.5, ins=0.45, p_delete=0.5, named=0.2))["action"] == "dictate"


def test_q10_a_delete_naming_what_to_remove_is_held():
    # P3 "Delete all the other sections.": names what it removes, matches no command -> held
    d = J.decide_command(_parsed("delete", conf=0.5, ins=0.42, p_delete=0.5, named=0.9))
    assert d["action"] == "instruction" and d["fallback"] == "dictate"
    assert J.held_score(_parsed("delete", ins=0.42, p_delete=0.5, named=0.9)) == 0.92
    assert J.held_score(_parsed("delete", ins=0.42, p_delete=0.5, named=0.1)) == 0.42


def test_q10_bare_scratch_that_is_undo_and_never_asked(authed_client, lab, monkeypatch):  # noqa: F811
    lab(FakeBundle())
    asked = []

    async def ask(scratchpad, utterance, regions, chips):
        asked.append(utterance)
        return _parsed("instruction", conf=0.95, ins=0.95)
    monkeypatch.setattr(cr, "ask_command", ask)
    for said in ("Scratch that.", "Delete that."):
        d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": said,
                                                           "stack_regions": ["Lungs"]}).json()
        assert d["route"] == "delete" and d["stack_command"] is None
    assert asked == []


async def test_q10_the_named_question_is_asked_in_the_same_call_only_when_on(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"command": {"choice": "delete", "confidence": 0.9},
                                                     J.NAMED_KEY: {"noul": 0.2}}})
    t = httpx.MockTransport(handler)
    on = await J.ask_command("Liver normal.", "Remove the last sentence.", [], [], transport=t, instruction=True)
    assert len(seen) == 1 and J.NAMED_KEY in seen[0]["questions"] and on["p_named"] == 0.2
    await J.ask_command("Liver normal.", "Remove the last sentence.", [], [], transport=t, instruction=False)
    assert J.NAMED_KEY not in seen[1]["questions"]


def test_q11_a_filler_or_aside_is_not_held(authed_client, lab, monkeypatch):  # noqa: F811
    # the bundle reads it as noise: the polish cleans it, as today; never a card
    lab(FakeBundle(action="ignore_noise"))

    async def ask(scratchpad, utterance, regions, chips):
        return _parsed("instruction", conf=0.95, ins=0.95)
    monkeypatch.setattr(cr, "ask_command", ask)
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "Hang on, the phone's ringing.",
                                                       "stack_regions": ["Lungs"]}).json()
    assert d["route"] == "polish" and d["stack_command"]["action"] == "dictate"


def test_q11_the_option_does_not_cover_talk_not_meant_for_the_report():
    c = J.INSTRUCTION_CRITERION
    assert "speech not meant for the report (talking to the software or to someone else)" not in c
    assert "not this option" in c


def test_q15_a_tidy_up_command_is_never_held(authed_client, lab, monkeypatch):  # noqa: F811
    # "New paragraph" the bundle is unsure of goes to the polish, which handles it as today
    lab(FakeBundle(action="formatting_command", conf=0.5))

    async def ask(scratchpad, utterance, regions, chips):
        return _parsed("instruction", conf=0.9, ins=0.9)
    monkeypatch.setattr(cr, "ask_command", ask)
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "New paragraph please.",
                                                       "stack_regions": ["Lungs"]}).json()
    assert d["route"] == "polish" and d["stack_command"]["action"] == "dictate"


def test_q15_settle_never_holds_what_the_polish_handles():
    held = {"action": "instruction", "fallback": "dictate", "region": None}
    assert J.settle_instruction(held, "polish", True)["action"] == "dictate"
    assert J.settle_instruction(held, "polish", False)["action"] == "instruction"
    assert J.polish_handles("ignore_noise", "Hang on, the phone's ringing.")
    assert J.polish_handles("formatting_command", "New paragraph.") and J.polish_handles("formatting_command", "Full stop.")
    assert not J.polish_handles("append_new_finding", "New paragraph.")
    assert not J.polish_handles(None, "Hmm.")   # Jev error: the hold stands


def test_q15_an_instruction_the_lexicon_does_not_know_is_still_held(authed_client, lab, monkeypatch):  # noqa: F811
    # lab 2026-10-16: the triage reads P3 as a formatting command; the lexicon has no such command, so it is held
    lab(FakeBundle(action="formatting_command", conf=0.6))
    assert not J.polish_handles("formatting_command", "Delete all the other sections.")

    async def ask(scratchpad, utterance, regions, chips):
        return _parsed("delete", conf=0.5, ins=0.42, p_delete=0.5, named=0.9)
    monkeypatch.setattr(cr, "ask_command", ask)
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "Delete all the other sections.",
                                                       "stack_regions": ["Lungs"]}).json()
    assert d["route"] == "polish" and d["stack_command"]["action"] == "instruction"
