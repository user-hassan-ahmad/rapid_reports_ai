"""Arm 2 of the chat-router head-to-head lab: propose, verify, apply. A PROTOTYPE, NOT WIRED: no endpoint calls it;
the lab (scripts/chat_router_lab.py, stage "arms") runs it beside arm 1 (chat_router.route_turn).

  propose   ONE Qwen call (gpt-oss retry with prompted output) over a compact outline of the sheet (the same views the
            targeted calls see, all of them) and the instruction; it returns typed changes using the existing change
            models (value, concept, fixed, normal, layout; style as edited prose blocks by id), each with a specific
            plain-sentence claim.
  validate  the existing validators and gates (wording source, slots, check_proposal, unit guards, the prose deletion
            check, the rule-in-disguise check on style), plus the habit guard.
  verify    Jev: per applicable change, V1 "Does the INSTRUCTION ask for this change: "<claim>"?" (with the habit
            guard in the same call), and C1 "anything not covered by the CHANGES listed?" (verify lab 2026-10-13,
            synthetic/chat_router/verify_lab.py). The claim verified is the code's own claim for the validated
            change (what would actually be applied); the model's claim is kept in the evidence.
  apply     a verified change (>= VERIFY_MIN) through the existing ledger / edit ops (D-R1: named, undoable); an
            unverified one becomes a card (style: an ask line); a coverage yes (>= COVER_MIN) adds an ask line.
Returns a chat_router.Turn, so the response shape is the router's."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel
from pydantic_ai import PromptedOutput

from . import chat_router as R
from . import chat_router_changes as CH
from . import chat_router_jev as J
from . import chat_router_ledger as L
from . import chat_router_sheet as sh
from . import chat_router_views as V
from .jev_client import JEV_MODEL, jev_post

logger = logging.getLogger(__name__)

PROPOSE_VERSION = "propose-1"
PROPOSE_TIMEOUT_S = 25.0
FALLBACK_TIMEOUT_S = 25.0
VERIFY_TIMEOUT_S = 6.0
VERIFY_MIN = 0.5    # V1 (verify lab)
COVER_MIN = 0.65    # C1 (verify lab)
MAX_CHANGES = 10
SETTINGS = {"temperature": 0, "max_tokens": 6000, "reasoning_effort": "low"}
PART_NOT_APPLIED = "Part of your message wasn't applied: could you say what else you wanted changed?"
STYLE_UNVERIFIED = "I wasn't sure you asked for this, so I left it out: {claim}"


class ProposedChange(BaseModel):
    kind: Literal["value", "concept", "fixed", "normal", "layout", "style"]
    claim: str                                   # one specific plain sentence: what reports will do differently
    value: Optional[CH.ValueChange] = None
    concept: Optional[CH.ConceptChange] = None
    fixed: Optional[CH.FixedChange] = None
    normal: Optional[CH.NormalChange] = None
    layout: Optional[CH.LayoutChange] = None
    style: Optional[CH.StyleBlock] = None        # a prose block by id, with its complete new text


class Proposal(BaseModel):
    changes: List[ProposedChange] = []
    question: str = ""


SYSTEM = (
    "You turn a radiologist's chat INSTRUCTION into changes to their report template. The radiologist never sees the "
    "template; code validates and applies your changes, and checks each claim against the INSTRUCTION.\n"
    "You get the template as an OUTLINE: the values every report must state, the study-level statements, the "
    "sentences printed in every report, the normal findings by paragraph, the sections and paragraphs, and the prose "
    "blocks (each with a block id).\n"
    "Return only the changes the INSTRUCTION asks for, nothing it does not ask for. Each change has a kind and the "
    "matching field:\n"
    '- value: {"name", "to": "every" | "relevant" | "not_needed"}\n'
    '- concept: {"concept" (its key from the OUTLINE), "state", "default", "when_met", "condition"} (null keeps a '
    "field)\n"
    '- fixed: {"to": "always" | "dictated" | "remove" | "reword" | "add", "line", "text", "paragraph"}\n'
    '- normal: {"paragraph", "structure" or "negative", "to": "reword" | "removed" | "add", "text"}\n'
    '- layout: {"op", "target", "name", "section", "role", "covers", "before", "after"}\n'
    '- style: {"id" (the block id), "text" (the complete new text of that prose block)}; only for style, tone, length '
    "or phrasing, never to make reports state something.\n"
    "Use only names shown in the OUTLINE, copied exactly. Copy new wording exactly as the INSTRUCTION gives it; if "
    "it does not give the exact wording, write your best wording and set sure to false.\n"
    'Each change has a "claim": one specific plain sentence naming the item and what changes, in report terms (for '
    'example "<value name> is no longer required." or "The <paragraph> paragraph is renamed to <new name>."), never '
    'a vague one such as "the wording changes".\n'
    'If you cannot tell what the INSTRUCTION asks, return no changes and one short question in "question".')


def outline(sheet: str, ledger: List[dict]) -> str:
    return "\n\n".join(V.view(k, sheet, ledger) for k in ("value", "concept", "fixed", "normal", "layout", "style"))


def user_prompt(sheet: str, ledger: List[dict], instruction: str, context: str = "",
                rejection: Optional[dict] = None) -> str:
    s = f"INSTRUCTION:\n{(instruction or '').strip()}\n\nOUTLINE:\n{outline(sheet, ledger)}"
    if (context or "").strip():
        s += f"\n\nYOUR PREVIOUS REPLY (context only):\n{context.strip()}"
    if rejection:
        s += ("\n\nTHE RADIOLOGIST REJECTED THE LAST CHANGE.\n"
              f'They had asked: "{(rejection.get("original_instruction") or "").strip()}"\n'
              f'The change made was: "{(rejection.get("rejected_claim") or "").strip()}"\n'
              "Treat the INSTRUCTION as their clarification of that request.")
    return s


async def _propose(sheet: str, ledger: List[dict], instruction: str, context: str = "",
                   rejection: Optional[dict] = None) -> Proposal:
    """The one propose call: Qwen with tool output; gpt-oss with prompted output if it fails (as 3da534e7)."""
    from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model
    prompt = user_prompt(sheet, ledger, instruction, context, rejection)

    async def call(model: str, timeout: float, output_type=Proposal) -> Proposal:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=model, output_type=output_type, system_prompt=SYSTEM, user_prompt=prompt, api_key="",
            model_settings=dict(SETTINGS)), timeout)
        return r.output

    try:
        return await call(MODEL_CONFIG["SKILL_SHEET_REFINER"], PROPOSE_TIMEOUT_S)
    except Exception as e:
        logger.warning("[chat-router.propose] %s: %s; fallback %s", type(e).__name__, str(e)[:200],
                       MODEL_CONFIG["STACK_REVIEW_FALLBACK"])
        return await call(MODEL_CONFIG["STACK_REVIEW_FALLBACK"], FALLBACK_TIMEOUT_S, PromptedOutput(Proposal))


def _v1(claim: str) -> dict:
    return {"type": "noul", "instructions": f'Does the INSTRUCTION ask for this change: "{claim}"?'}


C1 = {"type": "noul", "instructions": "Does the INSTRUCTION ask for anything that is not covered by the CHANGES listed?"}


async def verify(scan_type: str, instruction: str, claims: List[str],
                 transport=None) -> Tuple[List[float], float, float]:
    """(V1 score per claim, C1 coverage score, habit-guard score). Two Jev calls in parallel: the claims and the habit
    guard on the instruction's state, and C1 on the state with the CHANGES listed (each as the verify lab asked it).
    Raises on failure."""
    base = f"SCAN TYPE: {scan_type or 'not given'}\n\nINSTRUCTION:\n{(instruction or '').strip()}"
    key = os.environ.get("OPENROUTER_API_KEY", "")
    qs = {f"c{i}": _v1(c) for i, c in enumerate(claims)}
    qs["habit"] = dict(J.QUESTIONS["habit"])
    cover_state = base + "\n\nCHANGES:\n" + "\n".join(f"- {c}" for c in claims)

    async def post(state: str, questions: dict) -> dict:
        r = await jev_post({"model": JEV_MODEL, "state": state, "questions": questions}, key, VERIFY_TIMEOUT_S,
                           transport)
        r.raise_for_status()
        return r.json().get("answers") or {}

    a, b = await asyncio.gather(post(base, qs), post(cover_state, {"C1": dict(C1)}))
    return ([J._score(a, f"c{i}") for i in range(len(claims))], J._score(b, "C1"), J._score(a, "habit"))


def _changes(p: ProposedChange):
    return getattr(p, p.kind)


async def propose_turn(sheet: str, ledger: List[dict], instruction: str, *, context: str = "",
                       rejection: Optional[dict] = None) -> R.Turn:
    t0 = time.monotonic()
    scan = sh.scan_type(sheet)
    ledger = L.clean(ledger)
    try:
        proposal = await _propose(sheet, ledger, instruction, context, rejection)
    except Exception as e:
        logger.warning("[chat-router.propose] propose failed: %s", type(e).__name__)
        raise R.Fallback(f"propose_{type(e).__name__}") from e
    changes = [c for c in proposal.changes if _changes(c) is not None]
    truncated = max(0, len(changes) - MAX_CHANGES)
    changes = changes[:MAX_CHANGES]
    wording = instruction + ("\n" + (rejection.get("original_instruction") or "") if rejection else "")
    ctx = CH.Ctx(sheet, ledger, wording)

    # validate: the existing gates, per change (style blocks go through the router's own style path)
    pairs: List[Tuple[ProposedChange, CH.Verdict]] = []
    style_blocks = [c for c in changes if c.kind == "style"]
    for c in changes:
        if c.kind == "style":
            continue
        v = CH.validate(c.kind, _changes(c), ctx)
        if v.action == "edit" and v.op:   # client-shaped re-check: forward ops only, slots, a dry run
            checked = CH.check_proposal(CH.proposal_card(v)["apply"], sheet)
            if checked.action == "reject":
                v = checked
        pairs.append((c, v))
    applicable = [(c, v) for c, v in pairs if v.action in ("ledger", "edit")]
    claims = [v.claim or c.claim for c, v in applicable] + [c.claim for c in style_blocks]
    try:
        scores, cover, habit = await verify(scan, instruction, claims)
    except Exception as e:
        logger.warning("[chat-router.propose] verify failed: %s", type(e).__name__)
        raise R.Fallback(f"verify_{type(e).__name__}") from e
    by_claim = dict(zip(range(len(claims)), scores))

    ev = {"version": PROPOSE_VERSION, "route": "propose", "proposed": len(proposal.changes), "truncated": truncated,
          "coverage": round(cover, 3), "claims": []}
    habit_card, habit_line = None, ""
    if habit >= J.HABIT_MIN:
        habit_card, habit_line, ev["habit"] = R._park_habit(instruction, habit)

    verdicts: List[CH.Verdict] = [v for _, v in pairs if v.action not in ("ledger", "edit")]
    for i, (c, v) in enumerate(applicable):
        ok = by_claim[i] >= VERIFY_MIN
        ev["claims"].append({"kind": v.kind, "claim": v.claim or c.claim, "proposed": c.claim,
                             "score": round(by_claim[i], 3), "verified": ok})
        if habit_card and v.kind in R.HABIT_KINDS:
            continue                                   # parked: never written as a rule line (until item 5)
        verdicts.append(v if ok else CH.to_card(v))

    asks: List[str] = []
    verified_blocks = []
    for j, c in enumerate(style_blocks):
        s = by_claim[len(applicable) + j]
        ev["claims"].append({"kind": "style", "claim": c.claim, "proposed": c.claim, "score": round(s, 3),
                             "verified": s >= VERIFY_MIN})
        if s >= VERIFY_MIN:
            verified_blocks.append(c.style)
        else:
            asks.append(STYLE_UNVERIFIED.format(claim=c.claim))
    styled, style_rec, style_lines, style_ev = sheet, None, [], {}
    if verified_blocks:
        out = CH.StyleOut(blocks=verified_blocks, summary=" ".join(c.claim for c in style_blocks
                                                                   if c.style in verified_blocks))
        styled, style_rec, style_lines, extra, style_ev = await R._style(sheet, out, ctx)
        verdicts += extra
    if cover >= COVER_MIN:
        asks.append(PART_NOT_APPLIED)
    if (proposal.question or "").strip():
        asks.append(proposal.question.strip())

    new_sheet, new_ledger, records, claims_out, notes, problems, detail = R._apply(
        styled, ledger, [v for v in verdicts if v.action in ("ledger", "edit")])
    if style_rec:
        records.insert(0, style_rec)
        claims_out.insert(0, style_rec["claim"])
    cards = ([habit_card] if habit_card else []) + [v.card for v in verdicts if v.action == "card" and v.card]
    if habit_line:
        asks.append(habit_line)
    asks += [v.reason for v in verdicts if v.action in ("ask", "reject") and v.reason]
    style_ev.pop("truncated", None)
    ev.update(changes=[R._ev(v) for _, v in pairs] + [R._ev(v) for v in verdicts if v.kind == "style"],
              cards=len(cards), problems=detail, **style_ev)

    def tail(cards_: List[dict]) -> List[str]:
        return ([R.CARDS_LINE] if cards_ else []) + asks + style_lines + problems

    if not records:
        ev.update(applied=0, ms=R._ms(t0))
        return R.Turn(sheet, ledger, False, "\n".join(tail(cards)) or "No change was needed.", cards=cards,
                      evidence=ev)
    saved = await L.save(new_sheet, sheet, new_ledger)
    if saved.status == "refused":
        ev.update(applied=0, refused=True, ms=R._ms(t0))
        return R.Turn(sheet, ledger, False, saved.message, cards=cards, refused=True, evidence=ev)
    cards += saved.cards
    if saved.sheet == sheet and saved.ledger == ledger:
        ev.update(applied=0, ms=R._ms(t0))
        return R.Turn(sheet, ledger, False, "\n".join(tail(cards)) or "No change was needed.", cards=cards,
                      evidence=ev)
    notes += [n for n in (L.note(c) for c in saved.ledger_changes) if n]
    lines = claims_out + notes + tail(cards) + ([R.UNMATCHED_LINE] if saved.unmatched else []) + (
        [saved.message] if saved.message else [])
    ev.update(applied=len(records), unmatched=len(saved.unmatched), ms=R._ms(t0))
    return R.Turn(saved.sheet, saved.ledger, True, "\n".join(lines), claim=" ".join(claims_out), records=records,
                  cards=cards, notice=saved.message, unmatched=saved.unmatched, evidence=ev)
