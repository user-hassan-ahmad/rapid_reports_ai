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
             "requires": {}, "edit_calls": [], "edit_scores": {}, "contexts": [], "cover_calls": []}

    async def propose(sheet, ledger, instruction, context="", rejection=None):
        if isinstance(state["proposal"], Exception):
            raise state["proposal"]
        return state["proposal"]

    async def verify(scan, instruction, claims, context="", cover=None, transport=None):
        state["verify_calls"].append(list(claims))
        state["contexts"].append(context)
        state["cover_calls"].append(cover)
        return [state["claim_scores"].get(c, 0.9) for c in claims], (state["cover"] if cover is not None else None)

    async def screen(scan, instruction, context="", transport=None):
        return {"habit": state["habit"], "undo": state.get("undo", 0.0), "misfit": state.get("misfit", 0.0)}

    async def requires(lines, transport=None):
        return [state["requires"].get(l, 0.0) for l in lines]
    monkeypatch.setattr(P, "_propose", propose)
    monkeypatch.setattr(P, "verify", verify)
    monkeypatch.setattr(P, "screen", screen)
    monkeypatch.setattr(J, "requires", requires)

    async def verify_edits(edits, transport=None):
        state["edit_calls"].append([c for _, _, c in edits])
        return [state["edit_scores"].get(c, 0.9) for _, _, c in edits]
    monkeypatch.setattr(J, "verify_edits", verify_edits)
    return state


_DEFAULTS = {"fixed": {"line": "", "text": "", "paragraph": ""}, "normal": {"structure": "", "negative": "", "text": ""},
             "layout": {"target": ""}}
_MODEL = {"value": "PValue", "concept": "PConcept", "fixed": "PFixed", "normal": "PNormal", "layout": "PLayout",
          "style": "PStyle"}
_LIST = dict(P.LISTS)


def _change(kind, claim, **fields):
    if kind == "style":
        fields = {"block": fields.pop("id"), **fields}
    return kind, getattr(P, _MODEL[kind])(claim=claim, **{**_DEFAULTS.get(kind, {}), **fields})


def _proposal(*changes, question=""):
    lists = {}
    for kind, item in changes:
        lists.setdefault(_LIST[kind], []).append(item)
    return P.Proposal(question=question, **lists)


async def test_a_verified_change_is_applied_named_and_undoable(stub):
    stub["proposal"] = _proposal(*[_change("value", "Width is no longer required.", name="Width",
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
    stub["proposal"] = _proposal(*[
        _change("value", "Width is no longer required.", name="Width", to="not_needed"),
        _change("fixed", "The technique line is removed.", to="remove", line="Axial images were acquired.")])
    stub["claim_scores"] = {'"Axial images were acquired." is no longer printed.': 0.2}
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and "Axial images were acquired." in t.sheet and 'LIST_MISSING ["Depth"]' in t.sheet
    assert [c["ledger_kind"] for c in t.cards] == ["fixed"] and R.CARDS_LINE in t.reply


async def test_a_coverage_yes_adds_an_ask_line(stub):
    stub["proposal"] = _proposal(*[_change("value", "Width is no longer required.", name="Width",
                                                   to="not_needed")])
    stub["cover"] = 0.7
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width and add a line about the margins")
    assert t.applied and P.PART_NOT_APPLIED in t.reply and t.evidence["coverage"] == 0.7
    stub["cover"] = 0.6                                                        # below C1's 0.65
    t2 = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    assert P.PART_NOT_APPLIED not in t2.reply


async def test_validation_runs_first_invented_wording_is_a_card_even_if_verified(stub):
    stub["proposal"] = _proposal(*[_change("normal", "The alpha normal line is reworded.", paragraph="Upper",
                                                   structure="alpha", to="reword", text="Alpha looks fine.")])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the alpha normal friendlier")
    assert not t.applied and t.cards[0]["ledger_kind"] == "normal" and stub["verify_calls"] == [[]]
    assert t.evidence["changes"][0]["invented"] is True


async def test_the_habit_guard_drops_value_normal_and_fixed_changes(stub):
    stub["proposal"] = _proposal(*[_change("normal", "A collection negative is added.", paragraph="Upper",
                                                   negative="No collection.", to="add", text="No collection.")])
    stub["habit"] = 0.9
    t = await P.propose_turn(ROUTER_SHEET, [], "with diverticulitis always comment on collection")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.cards[0]["kind"] == "habit"
    assert t.evidence["habit"]["condition"] == "diverticulitis"


async def test_a_style_block_is_verified_and_the_prose_deletion_check_applies(stub):
    new = "Lead with the main finding in one sentence."
    stub["proposal"] = _proposal(*[_change("style", "The Impression Construction guidance is shorter.", id="b4", text=new)])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert t.applied and new in t.sheet and stub["verify_calls"] == [["The Impression Construction guidance is shorter."]]
    stub["proposal"] = _proposal(*[
        _change("value", "Width is no longer required.", name="Width", to="not_needed"),
        _change("style", 'In Impression Construction, the line "Keep it brief." is removed.', id="b4", text="Lead with the most important finding.")])
    stub["claim_scores"] = {'In Impression Construction, the line "Keep it brief." is removed.': 0.1}
    t2 = await P.propose_turn(ROUTER_SHEET, [], "drop Width")
    assert "Keep it brief." in t2.sheet and 'LIST_MISSING ["Depth"]' in t2.sheet
    assert t2.cards[0]["title"].endswith('In Impression Construction, the line "Keep it brief." is removed.')


async def test_an_unverified_style_block_is_not_applied(stub):
    stub["proposal"] = _proposal(*[_change("style", "The Impression Construction guidance is shorter.", id="b4",
                                                   text="Lead with the main finding in one sentence.")])
    stub["claim_scores"] = {"The Impression Construction guidance is shorter.": 0.1}
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.cards[0]["apply"]["op"]["op"] == "style_block"


async def test_arm_2_refuses_a_vague_style_claim_whatever_jev_says(stub):
    stub["proposal"] = _proposal(*[_change("style", "Style updated.", id="b4",
                                                   text="Lead with the main finding in one sentence.")])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert not t.applied and "Keep it brief." in t.sheet and R.STYLE_UNVERIFIED.format(claim="Style updated.") in t.reply


async def test_arm_2_verifies_style_claims_once(stub, monkeypatch):
    calls = []

    async def verify_claims(*a, **k):
        calls.append(a)
        return []
    monkeypatch.setattr(J, "verify_claims", verify_claims)
    stub["proposal"] = _proposal(*[_change("style", "The Impression Construction guidance is shorter.", id="b4",
                                                   text="Lead with the main finding in one sentence.")])
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert t.applied and calls == []           # its own verify call already asked V1 for the block's claim


async def test_a_failed_proposal_falls_back(stub):
    stub["proposal"] = TimeoutError()
    with pytest.raises(R.Fallback):
        await P.propose_turn(ROUTER_SHEET, [], "drop width")


async def test_changes_per_proposal_are_capped(stub):
    names = [f"Size {i}" for i in range(14)]
    stub["proposal"] = _proposal(*[_change("value", f"{n} is required in every report.", name=n, to="every")
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


async def test_verify_asks_v1_per_claim_and_c1_on_the_changes_state():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.8} for k in body["questions"]}})
    t = httpx.MockTransport(handler)
    scores, cover = await P.verify("CT", "drop width", ["Width is no longer required."],
                                   cover=["Width is no longer required.", "Asked: which section?"], transport=t)
    assert scores == [0.8] and cover == 0.8 and len(seen) == 2
    claims_call = next(b for b in seen if "c0" in b["questions"])
    assert claims_call["questions"] == {"c0": {"type": "noul", "instructions":
                                               'Does the INSTRUCTION ask for this change: "Width is no longer required."?'}}
    assert claims_call["state"] == "SCAN TYPE: CT\n\nINSTRUCTION:\ndrop width"
    cover_call = next(b for b in seen if "C1" in b["questions"])
    assert cover_call["questions"]["C1"] == {"type": "noul", "instructions":
                                             "Does the INSTRUCTION ask for anything that is not covered by the CHANGES listed?"}
    assert cover_call["state"].endswith("\n\nCHANGES:\n- Width is no longer required.\n- Asked: which section?")
    seen.clear()
    assert await P.verify("CT", "x", [], cover=None, transport=t) == ([], None) and seen == []


async def test_screen_asks_the_habit_and_undo_questions_in_one_call():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.3} for k in body["questions"]}})
    out = await P.screen("CT", "put it back", context="PREVIOUS REPLY (context only):\nX",
                         transport=httpx.MockTransport(handler))
    assert out == {"habit": 0.3, "undo": 0.3, "misfit": 0.3} and len(seen) == 1
    assert seen[0]["questions"]["misfit"] == J.QUESTIONS["misfit"]                # misfit_B, as the wording lab chose
    assert seen[0]["questions"]["habit"] == J.QUESTIONS["habit"]
    assert seen[0]["questions"]["undo"] == {"type": "noul",
                                            "instructions": "The INSTRUCTION asks to undo the previous change."}
    assert "PREVIOUS REPLY (context only):\nX" in seen[0]["state"]


# ── item 5: C1 lists what is already handled, and is skipped when nothing is left to cover ──────────────────────
async def test_c1_lists_cards_asks_and_the_parked_habit(stub):
    stub["habit"] = 0.9
    stub["claim_scores"] = {'"Axial images were acquired." is no longer printed.': 0.2}
    stub["proposal"] = _proposal(
        _change("fixed", "The technique line is removed.", to="remove", line="Axial images were acquired."),
        _change("normal", "A collection negative is added.", paragraph="Upper", negative="No collection.", to="add",
                text="No collection."),
        _change("normal", "Nowhere is reworded.", paragraph="Nowhere", structure="x", to="reword", text="X."))
    await P.propose_turn(ROUTER_SHEET, [], "with a collection say no collection; drop the technique line")
    (cover,) = stub["cover_calls"]
    assert '"Axial images were acquired." is no longer printed.' in cover
    assert any(c.startswith("Saved as a habit to set up:") for c in cover)
    assert any(c.startswith("Asked: ") for c in cover)


async def test_a_question_only_turn_skips_c1(stub):
    stub["proposal"] = _proposal(question="Which section did you mean?")
    stub["cover"] = 0.9
    t = await P.propose_turn(ROUTER_SHEET, [], "fix the thing")
    assert stub["cover_calls"] == [None] and P.PART_NOT_APPLIED not in t.reply and "Which section" in t.reply


async def test_a_complete_turn_shows_no_coverage_line(stub):
    stub["proposal"] = _proposal(_change("value", "Width is no longer required.", name="Width", to="not_needed"))
    stub["cover"] = 0.2
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    assert t.reply == "Width is no longer required." and stub["cover_calls"] == [["Width is no longer required."]]


async def test_arm_2_with_the_habit_guard_does_not_reroute_a_flagged_line(stub, monkeypatch):
    from rapid_reports_ai import chat_router_calls as C

    async def no_call(*a, **k):
        raise AssertionError("no re-route call under the habit guard")
    monkeypatch.setattr(C, "call_kind", no_call)
    hidden = "Always comment on a collection."
    stub["proposal"] = _proposal(*[_change("style", "The Impression Construction guidance is shorter.", id="b4",
                                                   text=f"Lead with the main finding.\n{hidden}")])
    stub["habit"], stub["requires"] = 0.9, {hidden: 0.9}
    t = await P.propose_turn(ROUTER_SHEET, [], "with a collection always comment on it; shorter impression")
    assert hidden not in t.sheet and [c["kind"] for c in t.cards] == ["habit"]


async def test_arm_2_names_the_parts_the_habit_guard_drops(stub):
    stub["proposal"] = _proposal(*[
        _change("normal", "A collection negative is added.", paragraph="Upper", negative="No collection.", to="add",
                text="No collection."),
        _change("style", "The Impression Construction guidance is shorter.", id="b4", text="Lead with the main finding.")])
    stub["habit"] = 0.9
    t = await P.propose_turn(ROUTER_SHEET, [], "with a collection say no collection, and a shorter impression")
    assert t.applied and R.HABIT_DROPPED.format(label=R.KIND_LABEL["normal"]) in t.reply



async def test_arm_2_checks_the_claim_against_the_edit(stub):
    claim = "In Impression Construction: sentences are shorter."
    stub["proposal"] = _proposal(*[_change("style", claim, id="b4", text="Lead with the key finding.")])
    stub["edit_scores"] = {claim: 0.1}
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert not t.applied and stub["edit_calls"] == [[claim]] and R.STYLE_EDIT_MISMATCH.format(claim=claim) in t.reply


# ── items 1 and 8: a flat schema with required identifiers; style in its own list ───────────────────────────────
def test_identifiers_are_required_in_the_schema_and_style_has_its_own_list():
    req = {name: set(getattr(P, name).model_json_schema().get("required", [])) for name in
           ("PValue", "PConcept", "PFixed", "PNormal", "PLayout", "PStyle")}
    assert {"name", "to", "claim"} <= req["PValue"] and {"concept", "claim"} <= req["PConcept"]
    assert {"to", "line", "text", "paragraph", "claim"} <= req["PFixed"]
    assert {"paragraph", "to", "structure", "negative", "text", "claim"} <= req["PNormal"]
    assert {"op", "target", "claim"} <= req["PLayout"] and {"block", "text", "claim"} <= req["PStyle"]
    assert set(P.Proposal.model_fields) == {"values", "concepts", "fixed", "normals", "layout", "style", "question"}


async def test_a_change_missing_its_identifier_is_dropped_not_asked(stub):
    stub["proposal"] = _proposal(
        _change("fixed", "A line is removed.", to="remove", line=""),
        _change("normal", "A normal is reworded.", paragraph="", structure="alpha", to="reword", text="Alpha is fine."),
        _change("layout", "A paragraph is renamed.", op="rename_paragraph", target="", name="Top"),
        _change("value", "Width is no longer required.", name="Width", to="not_needed"))
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and t.reply == "Width is no longer required." and not t.cards
    assert t.evidence["unidentified"] == 3 and stub["verify_calls"] == [["Width is no longer required."]]



# ── item 2: the chat context reaches V1 and C1 ─────────────────────────────────────────────────────────────────
def test_chat_context_names_the_last_reply_and_the_last_applied_changes():
    ctx = P.chat_context("Width is no longer required.", [{"type": "ledger", "claim": "Width is no longer required."},
                                                           {"type": "ledger", "claim": ""}])
    assert ctx == ("PREVIOUS REPLY (context only):\nWidth is no longer required.\n\n"
                   "LAST APPLIED CHANGES (context only):\n- Width is no longer required.")
    assert P.chat_context("", None) == ""


async def test_propose_turn_passes_the_context_to_verify(stub):
    stub["proposal"] = _proposal(_change("value", "Depth is no longer required.", name="Depth", to="not_needed"))
    await P.propose_turn(ROUTER_SHEET, [], "and depth too", context="Width is no longer required.",
                         last_changes=[{"type": "ledger", "claim": "Width is no longer required."}])
    assert "LAST APPLIED CHANGES (context only):\n- Width is no longer required." in stub["contexts"][0]


async def test_v1_and_c1_both_carry_the_context():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.8} for k in body["questions"]}})
    await P.verify("CT", "and depth too", ["Depth is no longer required."], context="PREVIOUS REPLY (context only):\nX",
                   cover=["Depth is no longer required."], transport=httpx.MockTransport(handler))
    assert all("PREVIOUS REPLY (context only):\nX" in b["state"] for b in seen) and len(seen) == 2


# ── item 3: one claim per field ────────────────────────────────────────────────────────────────────────────────
NO_PRIOR, COMPARED = "No previous imaging available.", "Compared with the {study} of {date}."


async def test_a_two_field_concept_change_is_verified_field_by_field(stub):
    instr = f'say "{NO_PRIOR}" usually and "{COMPARED}" when there is a prior'
    stub["proposal"] = _proposal(_change("concept", "Comparison wording set.", concept="comparison",
                                         default=NO_PRIOR, when_met=COMPARED))
    t = await P.propose_turn(ROUTER_SHEET, [], instr)
    d_claim = CH.concept_field_claim("comparison", "default", NO_PRIOR)
    w_claim = CH.concept_field_claim("comparison", "when_met", COMPARED)
    assert stub["verify_calls"] == [[d_claim, w_claim]]
    assert L.concept_state(L.entry(t.ledger, "concept", "comparison")["choice"])[:3] == ("used", NO_PRIOR, COMPARED)


async def test_only_the_verified_field_is_applied_and_the_rest_is_carded(stub):
    instr = f'say "{NO_PRIOR}" usually and "{COMPARED}" when there is a prior'
    stub["proposal"] = _proposal(_change("concept", "Comparison wording set.", concept="comparison",
                                         default=NO_PRIOR, when_met=COMPARED))
    stub["claim_scores"] = {CH.concept_field_claim("comparison", "when_met", COMPARED): 0.1}
    t = await P.propose_turn(ROUTER_SHEET, [], instr)
    assert L.concept_state(L.entry(t.ledger, "concept", "comparison")["choice"])[:3] == ("used", NO_PRIOR, "")
    card = next(c for c in t.cards if c.get("ledger_kind") == "concept")
    assert card["wording"]["when_met"] == COMPARED                    # prefilled with the whole proposal


def test_field_claims_are_specific():
    assert CH.concept_field_claim("comparison", "default", NO_PRIOR) == (
        f'{L.CONCEPTS["comparison"]}: the usual wording is now "{NO_PRIOR}".')
    assert CH.concept_field_claim("comparison", "when_met", "") == (
        f'{L.CONCEPTS["comparison"]}: the wording for when it applies is removed.')
    assert CH.concept_field_claim("comparison", "state", "not_used") == f'{L.CONCEPTS["comparison"]}: no longer stated.'


# ── item 4: the habit guard blocks only what becomes unconditional ──────────────────────────────────────────────
def test_the_habit_guard_blocks_only_new_unconditional_content():
    blocks = lambda kind, **f: P.habit_blocks(kind, _change(kind, "c", **f)[1])
    assert blocks("normal", paragraph="Upper", negative="No collection.", to="add", text="No collection.")
    assert blocks("normal", paragraph="Upper", structure="delta", to="add", text="Delta is normal.")
    assert blocks("fixed", to="add", paragraph="Technique", text="A line.")
    assert blocks("fixed", to="always", line="Axial images were acquired.")
    assert blocks("value", name="Width", to="every")
    assert not blocks("normal", paragraph="Upper", structure="alpha", to="reword", text="Alpha is fine.")
    assert not blocks("normal", paragraph="Upper", negative="No beta abnormality.", to="removed")
    assert not blocks("fixed", to="remove", line="Axial images were acquired.")
    assert not blocks("fixed", to="dictated", line="Axial images were acquired.")
    assert not blocks("value", name="Width", to="relevant")
    assert not blocks("concept", concept="comparison", when_met="Compared with the {study} of {date}.")


async def test_with_the_habit_guard_a_rewording_still_applies(stub):
    stub["habit"] = 0.9
    stub["proposal"] = _proposal(
        _change("normal", "Upper: the alpha normal reads Alpha is fine.", paragraph="Upper", structure="alpha",
                to="reword", text="Alpha is fine."),
        _change("value", "Width must be stated in every report.", name="Width", to="every"))
    t = await P.propose_turn(ROUTER_SHEET, [], "when there is a mass say Alpha is fine. and always give the width")
    assert t.applied and "Alpha is fine." in t.sheet and t.cards[0]["kind"] == "habit"
    assert t.evidence["habit_dropped"] == ["value"]


# ── item 6: unverified or failed structured changes become prefilled cards ──────────────────────────────────────
async def test_an_unverified_style_block_becomes_a_card_that_applies_and_undoes(stub):
    new = "Lead with the main finding in one sentence."
    claim = "The Impression Construction guidance is shorter."
    stub["proposal"] = _proposal(_change("style", claim, id="b4", text=new))
    stub["claim_scores"] = {claim: 0.1}
    t = await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert not t.applied and t.sheet == ROUTER_SHEET
    (card,) = t.cards
    assert card["kind"] == "proposal" and card["apply"]["op"]["op"] == "style_block" and card["title"].endswith(claim)
    a = await R.answer_card(ROUTER_SHEET, [], {"proposal": card["apply"]})
    assert a.applied and new in a.sheet and "Keep it brief." not in a.sheet
    u = await R.undo_turn(a.sheet, a.ledger, a.records)
    assert u.sheet == ROUTER_SHEET


async def test_a_concept_change_code_cannot_store_becomes_a_prefilled_card(stub):
    stub["proposal"] = _proposal(_change("concept", "Comparison wording set.", concept="comparison",
                                         when_met="compared with the prior"))     # not a full sentence
    t = await P.propose_turn(ROUTER_SHEET, [], "say compared with the prior when there is one")
    (card,) = t.cards
    assert card["ledger_kind"] == "concept" and card["wording"]["when_met"] == "compared with the prior"
    assert CH.REJECT.format(label=CH.KIND_LABEL["concept"]) not in t.reply


def test_style_block_op_checks_the_block_is_unchanged():
    from rapid_reports_ai import chat_router_edits as E
    op = {"op": "style_block", "block": "b4", "text": "Shorter.", "expect": "Lead with the most important finding.\nKeep it brief."}
    out, inv = E.apply_op(ROUTER_SHEET, op)
    assert "Shorter." in out and E.apply_op(out, inv[0])[0] == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {**op, "expect": "Something else."})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {**op, "text": 'NORMAL [alpha] "x"'})
    assert "style_block" in E.FORWARD_OPS


# ── item 7: "undo that" reverses the last turn's records, never the proposer ────────────────────────────────────
async def test_an_undo_instruction_reverses_the_last_turn_without_proposing(stub):
    stub["proposal"] = _proposal(_change("value", "Width is no longer required.", name="Width", to="not_needed"))
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width")
    stub["undo"] = 0.9
    stub["proposal"] = RuntimeError("the proposer must not run")
    u = await P.propose_turn(t.sheet, t.ledger, "put it back", last_changes=t.records)
    assert u.applied and 'LIST_MISSING ["Width" | "Depth"]' in u.sheet and u.evidence["route"] == "undo"
    assert u.reply.startswith("Undone: Width is no longer required.")


async def test_an_undo_with_nothing_to_undo_says_so(stub):
    stub["undo"] = 0.9
    stub["proposal"] = RuntimeError("the proposer must not run")
    t = await P.propose_turn(ROUTER_SHEET, [], "revert")
    assert not t.applied and t.reply == P.NOTHING_TO_UNDO and t.evidence["route"] == "undo"


async def test_below_the_threshold_the_proposer_runs(stub):
    stub["undo"] = 0.3
    stub["proposal"] = _proposal(_change("value", "Width is no longer required.", name="Width", to="not_needed"))
    t = await P.propose_turn(ROUTER_SHEET, [], "drop width", last_changes=[{"type": "ledger", "claim": "x"}])
    assert t.applied and t.evidence["route"] == "propose"



# ── misfit in the screen call (misfit_B, 0.5) ───────────────────────────────────────────────────────────────────
async def test_a_misfit_asks_the_scan_type_question_and_proposes_nothing(stub):
    stub["misfit"] = 0.8
    stub["proposal"] = RuntimeError("the proposer must not run")
    t = await P.propose_turn(ROUTER_SHEET, [], "add the weather forecast")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.reply == P.MISFIT_REPLY.format(scan="Router test")
    assert t.reply.startswith("That doesn't look like part of a Router test report") and "did you mean" in t.reply
    assert t.evidence["route"] == "misfit" and t.evidence["screen"] == {"habit": 0.1, "undo": 0.0, "misfit": 0.8}


async def test_a_plausible_always_mention_request_is_proposed(stub):
    stub["misfit"] = 0.2
    stub["proposal"] = _proposal(_change("normal", "Upper: alpha now reads Alpha is fine.", paragraph="Upper",
                                         structure="alpha", to="reword", text="Alpha is fine."))
    t = await P.propose_turn(ROUTER_SHEET, [], "always mention the ECV; say Alpha is fine.")
    assert t.evidence["route"] == "propose" and t.evidence["screen"]["misfit"] == 0.2


# ── review: a style card is offered (and applied on the tap) only after the edit and requires checks ────────────
CARD_CLAIM = "The Impression Construction guidance is shorter."


async def _unverified_style(stub, text="Lead with the main finding in one sentence."):
    stub["proposal"] = _proposal(_change("style", CARD_CLAIM, id="b4", text=text))
    stub["claim_scores"] = {CARD_CLAIM: 0.1}
    return await P.propose_turn(ROUTER_SHEET, [], "make the impression more concise")


async def test_no_style_card_when_the_edit_goes_beyond_its_claim(stub):
    stub["edit_scores"] = {CARD_CLAIM: 0.2}
    t = await _unverified_style(stub)
    assert not t.cards and R.STYLE_UNVERIFIED.format(claim=CARD_CLAIM) in t.reply


async def test_no_style_card_when_the_edit_adds_a_rule(stub):
    hidden = "Always state the alpha size."
    stub["requires"] = {hidden: 0.9}
    t = await _unverified_style(stub, text=f"Lead with the main finding.\n{hidden}")
    assert not t.cards and R.STYLE_UNVERIFIED.format(claim=CARD_CLAIM) in t.reply


async def test_no_style_card_at_all_when_the_habit_guard_fired(stub):
    stub["habit"] = 0.9
    t = await _unverified_style(stub)
    assert [c["kind"] for c in t.cards] == ["habit"]


async def test_the_tap_rechecks_the_style_card_against_the_current_sheet(stub):
    t = await _unverified_style(stub)
    (card,) = t.cards
    stub["edit_scores"] = {CARD_CLAIM: 0.2}                     # the same checks, run again on the tap
    a = await R.answer_card(ROUTER_SHEET, [], {"proposal": card["apply"]})
    assert not a.applied and a.sheet == ROUTER_SHEET and a.reply == R.CARD_REJECTED
    stub["edit_scores"], stub["requires"] = {}, {"Lead with the main finding in one sentence.": 0.9}
    a2 = await R.answer_card(ROUTER_SHEET, [], {"proposal": card["apply"]})
    assert not a2.applied
    stub["requires"] = {}
    a3 = await R.answer_card(ROUTER_SHEET, [], {"proposal": card["apply"]})
    assert a3.applied


async def test_cards_are_deduped_by_concept(stub):
    instr = "set the comparison wording"
    stub["proposal"] = _proposal(
        _change("concept", "Comparison wording set.", concept="comparison", default=NO_PRIOR, when_met=COMPARED),
        _change("concept", "Comparison when-met.", concept="comparison", when_met="compared with the prior"))
    stub["claim_scores"] = {CH.concept_field_claim("comparison", "when_met", COMPARED): 0.1,
                            CH.concept_field_claim("comparison", "default", NO_PRIOR): 0.1}
    t = await P.propose_turn(ROUTER_SHEET, [], instr)
    concept_cards = [c for c in t.cards if c.get("ledger_kind") == "concept"]
    assert len(concept_cards) == 1
