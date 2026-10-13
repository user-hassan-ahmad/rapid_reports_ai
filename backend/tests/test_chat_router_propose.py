"""Arm 2 of the head-to-head lab: propose (one Qwen call) -> validate -> verify (Jev) -> apply. Unwired prototype;
models stubbed."""
import json

import httpx
import pytest

from rapid_reports_ai import chat_router as R
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_jev as J
from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import chat_router_propose as P
from rapid_reports_ai import enhancement_utils as eu
from tests.template_sheet_fixtures import ROUTER_SHEET
from tests.test_template_sheet_lab_prompts import CLINICAL


@pytest.fixture(autouse=True)
def no_unit_checks(monkeypatch):
    from rapid_reports_ai import template_sheet_save as S

    async def none(structure, sheet):
        return []
    monkeypatch.setattr(S, "check_units", none)


@pytest.fixture
def stub(monkeypatch):
    """proposal: what the propose call returns; claim_scores: claim -> P(asked); cover / habit: scores."""
    state = {"proposal": P.Proposal(), "claim_scores": {}, "cover": 0.1, "habit": 0.1, "verify_calls": [],
             "requires": {}, "edit_calls": [], "edit_scores": {}}

    async def propose(sheet, ledger, instruction, context="", rejection=None):
        if isinstance(state["proposal"], Exception):
            raise state["proposal"]
        return state["proposal"]

    async def verify(scan, instruction, claims, transport=None):
        state["verify_calls"].append(list(claims))
        return [state["claim_scores"].get(c, 0.9) for c in claims], state["cover"], state["habit"]

    async def requires(lines, transport=None):
        return [state["requires"].get(l, 0.0) for l in lines]
    monkeypatch.setattr(P, "_propose", propose)
    monkeypatch.setattr(P, "verify", verify)
    monkeypatch.setattr(J, "requires", requires)

    async def verify_edits(edits, transport=None):
        state["edit_calls"].append([c for _, _, c in edits])
        return [state["edit_scores"].get(c, 0.9) for _, _, c in edits]
    monkeypatch.setattr(J, "verify_edits", verify_edits)
    return state


def _change(kind, claim, **fields):
    model = {"value": CH.ValueChange, "concept": CH.ConceptChange, "fixed": CH.FixedChange,
             "normal": CH.NormalChange, "layout": CH.LayoutChange, "style": CH.StyleBlock}[kind]
    return P.ProposedChange(kind=kind, claim=claim, **{kind: model(**fields)})


async def test_a_verified_change_is_applied_named_and_undoable(stub):
    stub["proposal"] = P.Proposal(changes=[_change("value", "Width is no longer required.", name="Width",
                                                   to="not_needed")])
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and t.reply == "Width is no longer required."
    assert stub["verify_calls"] == [["Width is no longer required."]]          # the code's claim is verified
    assert t.evidence["route"] == "propose" and t.evidence["claims"] == [
        {"kind": "value", "claim": "Width is no longer required.", "proposed": "Width is no longer required.",
         "score": 0.9, "verified": True}]
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert u.applied and 'LIST_MISSING ["Width" | "Depth"]' in u.sheet
    assert R.response(t).keys() == R.response(u).keys()                        # the router's response shape


async def test_an_unverified_change_becomes_a_card(stub):
    stub["proposal"] = P.Proposal(changes=[
        _change("value", "Width is no longer required.", name="Width", to="not_needed"),
        _change("fixed", "The technique line is removed.", to="remove", line="Axial images were acquired.")])
    stub["claim_scores"] = {'"Axial images were acquired." is no longer printed.': 0.2}
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and "Axial images were acquired." in t.sheet and 'LIST_MISSING ["Depth"]' in t.sheet
    assert [c["ledger_kind"] for c in t.cards] == ["fixed"] and R.CARDS_LINE in t.reply


async def test_a_coverage_yes_adds_an_ask_line(stub):
    stub["proposal"] = P.Proposal(changes=[_change("value", "Width is no longer required.", name="Width",
                                                   to="not_needed")])
    stub["cover"] = 0.7
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width and add a line about the margins")
    assert t.applied and P.PART_NOT_APPLIED in t.reply and t.evidence["coverage"] == 0.7
    stub["cover"] = 0.6                                                        # below C1's 0.65
    t2 = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    assert P.PART_NOT_APPLIED not in t2.reply


async def test_validation_runs_first_invented_wording_is_a_card_even_if_verified(stub):
    stub["proposal"] = P.Proposal(changes=[_change("normal", "The alpha normal line is reworded.", paragraph="Upper",
                                                   structure="alpha", to="reword", text="Alpha looks fine.")])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the alpha normal friendlier")
    assert not t.applied and t.cards[0]["ledger_kind"] == "normal" and stub["verify_calls"] == [[]]
    assert t.evidence["changes"][0]["invented"] is True


async def test_the_habit_guard_drops_value_normal_and_fixed_changes(stub):
    stub["proposal"] = P.Proposal(changes=[_change("normal", "A collection negative is added.", paragraph="Upper",
                                                   negative="No collection.", to="add", text="No collection.")])
    stub["habit"] = 0.9
    t = await P.propose_turn(ROUTER_SHEET, [], "with diverticulitis always comment on collection")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.cards[0]["kind"] == "habit"
    assert t.evidence["habit"]["condition"] == "diverticulitis"


async def test_a_style_block_is_verified_and_the_prose_deletion_check_applies(stub):
    new = "Lead with the main finding in one sentence."
    stub["proposal"] = P.Proposal(changes=[_change("style", "The Impression Construction guidance is shorter.", id="b4", text=new)])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert t.applied and new in t.sheet and stub["verify_calls"] == [["The Impression Construction guidance is shorter."]]
    stub["proposal"] = P.Proposal(changes=[
        _change("value", "Width is no longer required.", name="Width", to="not_needed"),
        _change("style", 'In Impression Construction, the line "Keep it brief." is removed.', id="b4", text="Lead with the most important finding.")])
    stub["claim_scores"] = {'In Impression Construction, the line "Keep it brief." is removed.': 0.1}
    t2 = await P.propose_turn(ROUTER_SHEET, [], "drop Width")
    assert "Keep it brief." in t2.sheet and 'LIST_MISSING ["Depth"]' in t2.sheet
    assert R.STYLE_UNVERIFIED.format(claim='In Impression Construction, the line "Keep it brief." is removed.') in t2.reply


async def test_an_unverified_style_block_is_not_applied(stub):
    stub["proposal"] = P.Proposal(changes=[_change("style", "The Impression Construction guidance is shorter.", id="b4",
                                                   text="Lead with the main finding in one sentence.")])
    stub["claim_scores"] = {"The Impression Construction guidance is shorter.": 0.1}
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert not t.applied and t.sheet == ROUTER_SHEET and "I wasn't sure you asked for this" in t.reply


async def test_arm_2_refuses_a_vague_style_claim_whatever_jev_says(stub):
    stub["proposal"] = P.Proposal(changes=[_change("style", "Style updated.", id="b4",
                                                   text="Lead with the main finding in one sentence.")])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert not t.applied and "Keep it brief." in t.sheet and R.STYLE_UNVERIFIED.format(claim="Style updated.") in t.reply


async def test_arm_2_verifies_style_claims_once(stub, monkeypatch):
    calls = []

    async def verify_claims(*a, **k):
        calls.append(a)
        return []
    monkeypatch.setattr(J, "verify_claims", verify_claims)
    stub["proposal"] = P.Proposal(changes=[_change("style", "The Impression Construction guidance is shorter.", id="b4",
                                                   text="Lead with the main finding in one sentence.")])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert t.applied and calls == []           # its own verify call already asked V1 for the block's claim


async def test_a_failed_proposal_falls_back(stub):
    stub["proposal"] = TimeoutError()
    with pytest.raises(R.Fallback):
        await P.propose_turn(ROUTER_SHEET, [], "drop width")


async def test_changes_per_proposal_are_capped(stub):
    names = [f"Size {i}" for i in range(14)]
    stub["proposal"] = P.Proposal(changes=[_change("value", f"{n} is required in every report.", name=n, to="every")
                                           for n in names])
    t = await P.propose_turn(ROUTER_SHEET, [], "always give " + ", ".join(names))
    assert len(t.evidence["claims"]) == P.MAX_CHANGES == 10 and t.evidence["truncated"] == 4


# ── the model calls (stubbed transports / agent) ─────────────────────────────────────────────────────────────────
def test_the_propose_prompt_is_case_agnostic_and_asks_for_specific_claims():
    low = P.SYSTEM.lower()
    for word in CLINICAL:
        assert word not in low, word
    assert "claim" in low and "specific" in low and "block id" in low


async def test_propose_uses_qwen_then_gpt_oss_with_prompted_output(monkeypatch):
    from pydantic_ai import PromptedOutput
    seen = []

    async def run(model_name, output_type, system_prompt, user_prompt, api_key, model_settings):
        seen.append((model_name, output_type, user_prompt))
        if len(seen) == 1:
            raise TimeoutError()
        return type("R", (), {"output": output_type.outputs()})()
    monkeypatch.setattr(eu, "_run_agent_with_model", run)
    out = await P._propose(ROUTER_SHEET, [], "drop width")
    assert isinstance(out, P.Proposal) and seen[0][1] is P.Proposal and isinstance(seen[1][1], PromptedOutput)
    assert "INSTRUCTION:\ndrop width" in seen[0][2] and "VALUES:" in seen[0][2] and "PROSE BLOCKS:" in seen[0][2]


async def test_verify_asks_v1_per_claim_with_habit_and_c1_on_the_changes_state():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.8} for k in body["questions"]}})
    t = httpx.MockTransport(handler)
    scores, cover, habit = await P.verify("CT", "drop width", ["Width is no longer required."], transport=t)
    assert scores == [0.8] and cover == 0.8 and habit == 0.8 and len(seen) == 2
    claims_call = next(b for b in seen if "c0" in b["questions"])
    assert claims_call["questions"]["c0"] == {"type": "noul", "instructions":
                                              'Does the INSTRUCTION ask for this change: "Width is no longer required."?'}
    assert claims_call["questions"]["habit"] == J.QUESTIONS["habit"]
    assert claims_call["state"] == "SCAN TYPE: CT\n\nINSTRUCTION:\ndrop width"
    cover_call = next(b for b in seen if "C1" in b["questions"])
    assert cover_call["questions"]["C1"] == {"type": "noul", "instructions":
                                             "Does the INSTRUCTION ask for anything that is not covered by the CHANGES listed?"}
    assert cover_call["state"].endswith("\n\nCHANGES:\n- Width is no longer required.")


async def test_arm_2_with_the_habit_guard_does_not_reroute_a_flagged_line(stub, monkeypatch):
    from rapid_reports_ai import chat_router_calls as C

    async def no_call(*a, **k):
        raise AssertionError("no re-route call under the habit guard")
    monkeypatch.setattr(C, "call_kind", no_call)
    hidden = "Always comment on a collection."
    stub["proposal"] = P.Proposal(changes=[_change("style", "The Impression Construction guidance is shorter.", id="b4",
                                                   text=f"Lead with the main finding.\n{hidden}")])
    stub["habit"], stub["requires"] = 0.9, {hidden: 0.9}
    t = await P.propose_turn(ROUTER_SHEET, [], "with a collection always comment on it; shorter impression")
    assert hidden not in t.sheet and [c["kind"] for c in t.cards] == ["habit"]


async def test_arm_2_names_the_parts_the_habit_guard_drops(stub):
    stub["proposal"] = P.Proposal(changes=[
        _change("normal", "A collection negative is added.", paragraph="Upper", negative="No collection.", to="add",
                text="No collection."),
        _change("style", "The Impression Construction guidance is shorter.", id="b4", text="Lead with the main finding.")])
    stub["habit"] = 0.9
    t = await P.propose_turn(ROUTER_SHEET, [], "with a collection say no collection, and a shorter impression")
    assert t.applied and R.HABIT_DROPPED.format(label=R.KIND_LABEL["normal"]) in t.reply



async def test_arm_2_checks_the_claim_against_the_edit(stub):
    claim = "In Impression Construction: sentences are shorter."
    stub["proposal"] = P.Proposal(changes=[_change("style", claim, id="b4", text="Lead with the key finding.")])
    stub["edit_scores"] = {claim: 0.1}
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert not t.applied and stub["edit_calls"] == [[claim]] and R.STYLE_EDIT_MISMATCH.format(claim=claim) in t.reply
