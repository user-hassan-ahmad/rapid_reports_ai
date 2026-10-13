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
STYLE_UNVERIFIED = R.STYLE_UNVERIFIED


# ── the proposal: flat lists, one per kind, identifiers REQUIRED (Qwen dropped nested optional sub-objects whose
# identifiers defaulted to ""; 2026-10-13). A change whose identifier is still empty is dropped by code, never
# turned into an empty-target ask. Style has its own list; each style claim names its block.
class PValue(BaseModel):
    name: str
    to: Literal["every", "relevant", "not_needed"]
    claim: str
    sure: bool = True


class PConcept(BaseModel):
    concept: str
    state: Optional[Literal["used", "dictated", "not_used"]] = None
    default: Optional[str] = None
    when_met: Optional[str] = None
    condition: Optional[str] = None
    claim: str
    sure: bool = True


class PFixed(BaseModel):
    to: Literal["always", "dictated", "remove", "reword", "add"]
    line: str          # the current sentence (empty only for "add")
    text: str          # the new wording (reword, add); empty otherwise
    paragraph: str     # where a new sentence goes (add); empty otherwise
    claim: str
    sure: bool = True


class PNormal(BaseModel):
    paragraph: str
    to: Literal["reword", "removed", "add"]
    structure: str     # a NORMAL line's structure, or empty for a negative
    negative: str      # a NEGATIVE line's current text, or empty for a normal
    text: str
    claim: str
    sure: bool = True


class PLayout(BaseModel):
    op: Literal["rename_paragraph", "move_paragraph", "remove_paragraph", "add_paragraph", "rename_section",
                "move_section", "remove_section", "add_section"]
    target: str        # the existing paragraph or section (empty only for add_paragraph / add_section)
    name: str = ""
    section: str = ""
    role: str = ""
    covers: List[str] = []
    before: str = ""
    after: str = ""
    claim: str
    sure: bool = True


class PStyle(BaseModel):
    block: str         # the block id from the OUTLINE
    text: str          # the complete new text of that block
    claim: str         # names the block (its heading or id) and what changed


class Proposal(BaseModel):
    values: List[PValue] = []
    concepts: List[PConcept] = []
    fixed: List[PFixed] = []
    normals: List[PNormal] = []
    layout: List[PLayout] = []
    style: List[PStyle] = []
    question: str = ""


def identified(kind: str, p) -> bool:
    """The change names what it changes (the identifiers its kind needs)."""
    if kind == "value":
        return bool(p.name.strip())
    if kind == "concept":
        return bool(p.concept.strip())
    if kind == "fixed":
        return bool(p.text.strip() and p.paragraph.strip()) if p.to == "add" else bool(p.line.strip())
    if kind == "normal":
        return bool(p.paragraph.strip()) and bool(p.structure.strip() or p.negative.strip()
                                                  or (p.to == "add" and p.text.strip()))
    if kind == "layout":
        if p.op == "add_paragraph":
            return bool(p.name.strip() and p.section.strip())
        return bool(p.name.strip()) if p.op == "add_section" else bool(p.target.strip())
    return bool(p.block.strip() and p.text.strip())


def to_change(kind: str, p):
    """The existing change model for a proposed item (validated by chat_router_changes)."""
    fields = p.model_dump(exclude={"claim"})
    if kind == "style":
        return CH.StyleBlock(id=p.block, text=p.text, claim=p.claim)
    model = {"value": CH.ValueChange, "concept": CH.ConceptChange, "fixed": CH.FixedChange,
             "normal": CH.NormalChange, "layout": CH.LayoutChange}[kind]
    return model(**fields)


CONCEPT_FIELDS = ("state", "default", "when_met")


def concept_fields(p: PConcept) -> List[str]:
    return [f for f in CONCEPT_FIELDS if getattr(p, f) is not None]


def single_field(p: PConcept, field: str) -> PConcept:
    """The concept change narrowed to one field (its condition travels with it)."""
    return PConcept(concept=p.concept, claim=p.claim, sure=p.sure, condition=p.condition, **{field: getattr(p, field)})


LISTS = (("value", "values"), ("concept", "concepts"), ("fixed", "fixed"), ("normal", "normals"),
         ("layout", "layout"), ("style", "style"))


def items(proposal: Proposal) -> Tuple[List[Tuple[str, object]], int]:
    """(kind, item) for every identified change, in a stable order, and the number dropped as unidentified."""
    out, dropped = [], 0
    for kind, attr in LISTS:
        for p in getattr(proposal, attr):
            if identified(kind, p):
                out.append((kind, p))
            else:
                dropped += 1
    return out, dropped


SYSTEM = (
    "You turn a radiologist's chat INSTRUCTION into changes to their report template. The radiologist never sees the "
    "template; code validates and applies your changes, and checks each claim against the INSTRUCTION.\n"
    "You get the template as an OUTLINE: the values every report must state, the study-level statements, the "
    "sentences printed in every report, the normal findings by paragraph, the sections and paragraphs, and the prose "
    "blocks (each with a block id).\n"
    "Return only the changes the INSTRUCTION asks for, nothing it does not ask for, each in its own list. Every field "
    "that names a target is required: copy it exactly from the OUTLINE.\n"
    '- values: {"name", "to": "every" | "relevant" | "not_needed", "claim"}\n'
    '- concepts: {"concept" (its key from the OUTLINE), "state", "default", "when_met", "condition", "claim"} (null '
    "keeps a field)\n"
    '- fixed: {"to": "always" | "dictated" | "remove" | "reword" | "add", "line" (the current sentence; empty only '
    'for add), "text" (the new wording for reword or add), "paragraph" (for add), "claim"}\n'
    '- normals: {"paragraph", "to": "reword" | "removed" | "add", "structure" (a normal line\'s structure) or '
    '"negative" (a negative line\'s current text), "text", "claim"}\n'
    '- layout: {"op", "target" (the existing paragraph or section; empty only when adding one), "name", "section", '
    '"role", "covers", "before", "after", "claim"}\n'
    '- style: {"block" (the block id), "text" (the complete new text of that prose block), "claim"}: only for style, '
    "tone, length or phrasing, never to make reports state something; change only what the INSTRUCTION asks for.\n"
    "Copy new wording exactly as the INSTRUCTION gives it; if it does not give the exact wording, write your best "
    "wording and set sure to false.\n"
    'Each change has a "claim": one specific plain sentence naming the item and what changes, in report terms (for '
    'example "<value name> is no longer required." or "In <block heading>: sentences are shorter."), never a vague '
    'one such as "the wording changes". A style claim names its block\'s heading.\n'
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


_v1 = J.v1


C1 = {"type": "noul", "instructions": "Does the INSTRUCTION ask for anything that is not covered by the CHANGES listed?"}


def chat_context(context: str = "", last_changes: Optional[List[dict]] = None) -> str:
    """The chat context V1 and C1 read (as route_turn gives the tags): the last assistant reply and the claims of the
    last turn's applied changes."""
    parts = []
    if (context or "").strip():
        parts.append(f"PREVIOUS REPLY (context only):\n{context.strip()}")
    claims = [r.get("claim") for r in (last_changes or []) if isinstance(r, dict) and r.get("claim")]
    if claims:
        parts.append("LAST APPLIED CHANGES (context only):\n" + "\n".join(f"- {c}" for c in claims))
    return "\n\n".join(parts)


async def verify(scan_type: str, instruction: str, claims: List[str], context: str = "",
                 transport=None) -> Tuple[List[float], float, float]:
    """(V1 score per claim, C1 coverage score, habit-guard score). Two Jev calls in parallel: the claims and the habit
    guard on the instruction's state, and C1 on the state with the CHANGES listed (each as the verify lab asked it).
    Raises on failure."""
    base = f"SCAN TYPE: {scan_type or 'not given'}\n\nINSTRUCTION:\n{(instruction or '').strip()}"
    if context:
        base += f"\n\n{context}"
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


async def propose_turn(sheet: str, ledger: List[dict], instruction: str, *, context: str = "",
                       rejection: Optional[dict] = None, last_changes: Optional[List[dict]] = None) -> R.Turn:
    t0 = time.monotonic()
    scan = sh.scan_type(sheet)
    ledger = L.clean(ledger)
    try:
        proposal = await _propose(sheet, ledger, instruction, context, rejection)
    except Exception as e:
        logger.warning("[chat-router.propose] propose failed: %s", type(e).__name__)
        raise R.Fallback(f"propose_{type(e).__name__}") from e
    changes, unidentified = items(proposal)
    truncated = max(0, len(changes) - MAX_CHANGES)
    changes = changes[:MAX_CHANGES]
    wording = instruction + ("\n" + (rejection.get("original_instruction") or "") if rejection else "")
    ctx = CH.Ctx(sheet, ledger, wording)

    # validate: the existing gates, per change (style blocks go through the router's own style path)
    pairs: List[Tuple[object, CH.Verdict]] = []
    group_of: dict = {}            # id(split item) -> the original multi-field concept change (one claim per field)
    style_blocks = [p for k, p in changes if k == "style"]
    blocks_by_id = {b.id: b for b in sh.prose_blocks(sheet)}
    expanded = []
    for kind, c in changes:
        if kind == "concept" and len(concept_fields(c)) > 1:
            for f in concept_fields(c):
                one = single_field(c, f)
                group_of[id(one)] = (c, f)
                expanded.append((kind, one))
        else:
            expanded.append((kind, c))
    for kind, c in expanded:
        if kind == "style":
            continue
        v = CH.validate(kind, to_change(kind, c), ctx)
        if id(c) in group_of and v.action in ("ledger", "edit"):
            orig, f = group_of[id(c)]
            v.claim = CH.concept_field_claim(orig.concept, f, getattr(orig, f))
        if v.action == "edit" and v.op:   # client-shaped re-check: forward ops only, slots, a dry run
            checked = CH.check_proposal(CH.proposal_card(v)["apply"], sheet)
            if checked.action == "reject":
                v = checked
        pairs.append((c, v))
    applicable = [(c, v) for c, v in pairs if v.action in ("ledger", "edit")]
    claims = [v.claim or c.claim for c, v in applicable] + [c.claim for c in style_blocks]
    try:
        scores, cover, habit = await verify(scan, instruction, claims, context=chat_context(context, last_changes))
    except Exception as e:
        logger.warning("[chat-router.propose] verify failed: %s", type(e).__name__)
        raise R.Fallback(f"verify_{type(e).__name__}") from e
    by_claim = dict(zip(range(len(claims)), scores))

    ev = {"version": PROPOSE_VERSION, "route": "propose", "proposed": len(changes) + unidentified,
          "unidentified": unidentified, "truncated": truncated,
          "coverage": round(cover, 3), "claims": []}
    habit_card, habit_line = None, ""
    if habit >= J.HABIT_MIN:
        habit_card, habit_line, ev["habit"] = R._park_habit(instruction, habit)

    verdicts: List[CH.Verdict] = [v for _, v in pairs if v.action not in ("ledger", "edit")]
    dropped: List[str] = []
    groups: dict = {}              # id(original concept change) -> (original, {field: verified})
    for i, (c, v) in enumerate(applicable):
        ok = by_claim[i] >= VERIFY_MIN
        ev["claims"].append({"kind": v.kind, "claim": v.claim or c.claim, "proposed": c.claim,
                             "score": round(by_claim[i], 3), "verified": ok})
        if id(c) in group_of:
            orig, f = group_of[id(c)]
            groups.setdefault(id(orig), (orig, {}))[1][f] = ok
            continue
        if habit_card and v.kind in R.HABIT_KINDS:
            dropped.append(v.kind)                     # parked: never written as a rule line (until item 5)
            continue
        verdicts.append(v if ok else CH.to_card(v))
    for orig, oks in groups.values():   # apply only the verified fields; card the whole proposal for the rest
        good = [f for f in CONCEPT_FIELDS if oks.get(f)]
        if good:
            merged = PConcept(concept=orig.concept, claim=orig.claim, sure=orig.sure, condition=orig.condition,
                              **{f: getattr(orig, f) for f in good})
            mv = CH.validate("concept", to_change("concept", merged), CH.Ctx(sheet, ledger, wording, confirmed=True))
            if mv.action == "ledger":
                mv.claim = " ".join(CH.concept_field_claim(orig.concept, f, getattr(orig, f)) for f in good)
            verdicts.append(mv)
        if len(good) < len(oks):
            full = CH.validate("concept", to_change("concept", orig), CH.Ctx(sheet, ledger, wording, confirmed=True))
            verdicts.append(CH.to_card(full) if full.action == "ledger" else full)

    asks: List[str] = []
    verified_blocks = []
    for j, c in enumerate(style_blocks):
        s = by_claim[len(applicable) + j]
        if c.block not in blocks_by_id or not R.specific_claim(c.claim, blocks_by_id[c.block],
                                                               blocks_by_id.values()):
            s = 0.0                                    # a claim that names no block: unverified, whatever Jev said
        ev["claims"].append({"kind": "style", "claim": c.claim, "proposed": c.claim, "score": round(s, 3),
                             "verified": s >= VERIFY_MIN})
        if s >= VERIFY_MIN:
            verified_blocks.append(to_change("style", c))
        else:
            asks.append(STYLE_UNVERIFIED.format(claim=c.claim))
    styled, style_rec, style_lines, style_ev = sheet, None, [], {}
    if verified_blocks:
        out = CH.StyleOut(blocks=verified_blocks, summary=" ".join(b.claim for b in verified_blocks))
        styled, style_rec, style_lines, extra, style_ev = await R._style(sheet, out, ctx, scan=scan, verified=True,
                                                                         habit=bool(habit_card))
        verdicts += extra
    dropped = list(dict.fromkeys(dropped))
    if dropped:   # name what the habit guard left out (never silent)
        ev["habit_dropped"] = dropped
        habit_line = "\n".join([habit_line] + [R.HABIT_DROPPED.format(label=R.KIND_LABEL[k]) for k in dropped])
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
