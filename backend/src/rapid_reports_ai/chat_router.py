"""The chat-edit router (spec 2026-10-13-chat-edit-router-design). A chat instruction that changes a template's
rules is applied by code through the decision ledger, the way a card tap is; a change of style is applied by a
lightweight call that can only touch prose. No model rewrites the whole sheet.

route_turn: Jev tags -> one targeted call per tagged kind (parallel; a kind in the unsure band is decided by its
call and marked route "llm_unsure", decision D-R2) -> code validates each structured change -> applied (style first,
then layout and unit edits, then ledger writes; plan decision 8), carded or asked -> the save function (origin
"chat"), which applies the ledger last -> the reply, one line per applied change. A failed tag call raises Fallback
and the endpoint runs today's whole-sheet refine (the fallback stays until the lab and live data say otherwise)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import chat_router_calls as C
from . import chat_router_changes as CH
from . import chat_router_edits as E
from . import chat_router_jev as J
from . import chat_router_layout as lay
from . import chat_router_ledger as L
from . import chat_router_sheet as sh
from . import chat_router_views as V

logger = logging.getLogger(__name__)

ROUTER_VERSION = "router-1"
UNSURE_ROUTE = "llm_unsure"
WORK_KINDS = ("value", "concept", "fixed", "normal", "layout", "style")
KIND_LABEL = CH.KIND_LABEL
CARDS_LINE = "I wasn't sure about part of that: choose below."
UNMATCHED_LINE = ("Some decisions no longer match a line in the template; they will be asked again at the next "
                  "review.")
STYLE_TOUCHED_RULES = ("The style change also touched the template's rules, so I left it out. Could you say it as "
                       "a change of wording only?")
REQUIRES_FAILED = "I couldn't check that wording change just now, so I left it out. Please try again."


class Fallback(Exception):
    """The tag call failed: the endpoint runs today's whole-sheet refine for this turn."""


@dataclass
class Turn:
    sheet: str
    ledger: List[dict]
    applied: bool                 # the saved sheet or the ledger differs from the turn's input (decision 14)
    reply: str
    claim: str = ""
    records: List[dict] = field(default_factory=list)   # what undo_turn reverses
    cards: List[dict] = field(default_factory=list)
    notice: str = ""
    refused: bool = False
    unmatched: List[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _ev(v: CH.Verdict) -> dict:
    return {"kind": v.kind, "action": v.action, "key": v.key, "op": (v.op or {}).get("op"), "route": v.route,
            "invented": v.invented, "reason": (v.reason or "")[:200], "detail": (v.detail or "")[:300]}


def _ask_reply(scan: str, misfit: bool) -> str:
    s = f"{scan} " if scan else ""
    if misfit:
        return f"That doesn't look like part of a {s}report. What should these reports do differently?"
    return f"I'm not sure what to change in these {s}reports. What should they do differently?"


def _ledger_for_edit(ledger: List[dict], before: str, op: dict, rec: dict,
                     undoing: bool = False) -> Tuple[List[dict], dict, Optional[dict]]:
    """Ledger keys follow a code edit: a paragraph rename rekeys its normals; a removal drops them (kept on the record
    for undo); a FIXED rewording moves its decided entry (td.rekey_decision), returned as a change so undo reverses it
    through the ledger (so `undoing` skips it). (ledger, record, change or None)."""
    name = op.get("op")
    change = None
    if name == "rename_paragraph":
        ledger = L.rekey_paragraph(ledger, op["paragraph"], op["to"])
    elif name in ("remove_paragraph", "remove_section"):
        if name == "remove_paragraph":
            paras = [op["paragraph"]]
        else:
            sec = lay.section_name(before, op["section"])
            paras = [n for n, s in sh.paragraphs(before) if sh.norm(s) == sh.norm(sec)]
        dropped = [e for p in paras for e in L.paragraph_entries(ledger, p)]
        ledger = [e for e in ledger if not any(e is d for d in dropped)]
        rec["dropped"] = list(rec.get("dropped") or []) + dropped
    elif name == "fixed_reword" and not undoing:
        ledger, change = L.rekey_fixed(ledger, op["line"], op["text"])
    return ledger, rec, change


def _apply(sheet: str, ledger: List[dict], verdicts: List[CH.Verdict]):
    """Layout edits, then unit edits, then ledger writes. (sheet, ledger, records, claims, notes, problems, detail)."""
    records: List[dict] = []
    claims: List[str] = []
    notes: List[str] = []
    problems: List[str] = []
    detail: List[str] = []
    seeded = False

    def rank(v: CH.Verdict) -> int:
        return 0 if (v.action == "edit" and v.kind == "layout") else 1 if v.action == "edit" else 2

    for v in sorted(verdicts, key=rank):
        route = v.route or None
        try:
            if v.action == "edit":
                before = sheet
                sheet, inverse = E.apply_op(sheet, v.op)
                rec = {"type": "edit", "kind": v.kind, "op": v.op, "inverse": inverse, "claim": v.claim,
                       "route": v.route}
                ledger, rec, moved = _ledger_for_edit(ledger, before, v.op, rec)
                records.append(rec)
                if moved:
                    records.append({"type": "ledger", "change": moved, "claim": "", "route": v.route})
                    notes.append(L.note(moved))
                if v.choice is not None:            # a new unit line is also a decision
                    ledger, change = L.set_choice(ledger, v.kind, v.key, v.choice, route=route)
                    if change:
                        records.append({"type": "ledger", "change": change, "claim": "", "route": v.route})
                claims.append(v.claim)
                continue
            if v.kind == "value" and not seeded:
                ledger, seeded = L.seed_values(ledger, sheet), True
            ledger, change = L.set_choice(ledger, v.kind, v.key, v.choice, route=route)
            if change is None:
                problems.append(f"Already the case: {v.claim}")
                continue
            records.append({"type": "ledger", "change": change, "claim": v.claim, "route": v.route})
            claims.append(v.claim)
            notes.append(L.note(change))
        except (E.EditError, L.Rejected) as e:   # the reason is internal: evidence only (decision 15)
            problems.append(f"I couldn't make this change: {v.claim.rstrip('.')}.")
            detail.append(f"{v.kind}: {str(e)[:200]}")
    return sheet, ledger, records, claims, [n for n in notes if n], problems, detail


async def _reroute(lines: List[str], ctx: CH.Ctx) -> List[CH.Verdict]:
    """A prose line that requires the report to state something goes back through the rule route (normal, fixed);
    its wording is the model's, so it is always a card. No rule kind fits: the reply asks (spec Flow 3)."""
    out: List[CH.Verdict] = []
    for line in lines:
        instr = f'Every report should state: "{line}"'
        res = await asyncio.gather(*(C.call_kind(k, instr, V.view(k, ctx.sheet, ctx.ledger)) for k in ("normal", "fixed")),
                                   return_exceptions=True)
        found = [CH.to_card(CH.validate(k, c, ctx)) for k, r in zip(("normal", "fixed"), res)
                 if not isinstance(r, BaseException) for c in r.changes]
        found = [v for v in found if v.action == "card"]
        out.append(found[0] if found else CH.Verdict(
            "style", "ask", reason=f'I left out "{line}": it reads as something every report must state. Which part '
                                   "of the report should state it?"))
    return out


async def _style(sheet: str, out: CH.StyleOut, ctx: CH.Ctx):
    """(sheet, style record or None, reply lines, extra verdicts, evidence) for a style output: unit lines must be
    untouched; each new prose line is asked whether it requires the report to state something, and a yes is left out
    of the edit and re-routed."""
    blocks = {b.id: b for b in sh.prose_blocks(sheet)}
    edits = {b.id: b.text.strip("\n") for b in out.blocks
             if b.id in blocks and b.text.strip("\n") != blocks[b.id].text}
    if not edits:
        return sheet, None, [], [], {}
    if not sh.units_unchanged(sheet, sh.splice(sheet, edits)):
        return sheet, None, [STYLE_TOUCHED_RULES], [], {"style": "unit_line_changed"}
    new = [l for b, t in edits.items() for l in sh.new_lines(blocks[b].text, t)]
    try:
        scores = await J.requires(new)
    except Exception as e:
        logger.warning("[chat-router] requires check failed: %s", type(e).__name__)
        return sheet, None, [REQUIRES_FAILED], [], {"style": "requires_failed"}
    flagged = [l for l, s in zip(new, scores) if s >= J.REQUIRES_MIN]
    ev = {"style": "applied", "disguise": [{"line": l[:200], "score": round(s, 3)} for l, s in zip(new, scores)]}
    if flagged:
        fl = {sh.norm(x) for x in flagged}
        edits = {b: "\n".join(x for x in t.splitlines() if sh.norm(x) not in fl) for b, t in edits.items()}
        # a block left empty keeps its old prose (the radiologist did not ask to delete it)
        edits = {b: t for b, t in edits.items() if t.strip() and t.strip("\n") != blocks[b].text}
    rerouted = await _reroute(flagged, ctx)
    if not edits:
        return sheet, None, [], rerouted, {**ev, "style": "all_rerouted"}
    rec = {"type": "style", "blocks": [{"before": blocks[b].text, "after": edits[b]} for b in edits],
           "claim": out.summary.strip() or "The wording guidance is updated."}
    return sh.splice(sheet, edits), rec, [], rerouted, ev


async def route_turn(sheet: str, ledger: List[dict], instruction: str, *, context: str = "",
                     rejection: Optional[dict] = None) -> Turn:
    t0 = time.monotonic()
    scan = sh.scan_type(sheet)
    try:
        tags = await J.tag(instruction, scan, context)
    except Exception as e:
        logger.warning("[chat-router] tag call failed: %s: %s", type(e).__name__, str(e)[:200])
        raise Fallback(type(e).__name__) from e
    ledger = L.clean(ledger)
    yes = [k for k in WORK_KINDS if tags[k] >= J.TAG_MIN]
    unsure = [k for k in WORK_KINDS if J.TAG_UNSURE <= tags[k] < J.TAG_MIN]
    ev = {"version": ROUTER_VERSION, "route": "router", "tags": {k: round(v, 3) for k, v in tags.items()},
          "yes": yes, "unsure": unsure}
    misfit = tags["misfit"] >= J.TAG_MIN
    if misfit or not (yes or unsure):
        ev.update(route="ask", applied=0, ms=_ms(t0))
        return Turn(sheet, ledger, False, _ask_reply(scan, misfit), evidence=ev)

    wording = instruction + ("\n" + (rejection.get("original_instruction") or "") if rejection else "")
    ctx = CH.Ctx(sheet, ledger, wording)
    kinds = yes + unsure
    results = await asyncio.gather(*(C.call_kind(k, instruction, V.view(k, sheet, ledger), context, rejection)
                                     for k in kinds), return_exceptions=True)
    verdicts: List[CH.Verdict] = []
    asks: List[str] = []
    failed: List[str] = []
    style_out, style_route = None, ""
    for k, res in zip(kinds, results):
        if isinstance(res, BaseException):
            logger.warning("[chat-router] %s call failed: %s", k, type(res).__name__)
            failed.append(k)
            continue
        if (res.question or "").strip():
            asks.append(res.question.strip())
        route = UNSURE_ROUTE if k in unsure else ""
        if k == "style":
            style_out, style_route = res, route
            continue
        for c in res.changes:
            v = CH.validate(k, c, ctx)
            v.route = route
            verdicts.append(v)

    styled, style_rec, style_lines, style_ev = sheet, None, [], {}
    if style_out is not None and style_out.blocks:
        styled, style_rec, style_lines, extra, style_ev = await _style(sheet, style_out, ctx)
        if style_rec:
            style_rec["route"] = style_route
        verdicts += extra

    new_sheet, new_ledger, records, claims, notes, problems, detail = _apply(
        styled, ledger, [v for v in verdicts if v.action in ("ledger", "edit")])
    if style_rec:
        records.insert(0, style_rec)
        claims.insert(0, style_rec["claim"])
    cards = [v.card for v in verdicts if v.action == "card" and v.card]
    asks += [v.reason for v in verdicts if v.action in ("ask", "reject") and v.reason]
    fails = [f"I couldn't change {KIND_LABEL[k]} just now; please try that part again." for k in failed]
    ev.update(changes=[_ev(v) for v in verdicts], cards=len(cards), failed=failed, problems=detail, **style_ev)

    def tail(cards_: List[dict]) -> List[str]:
        return ([CARDS_LINE] if cards_ else []) + asks + style_lines + problems + fails

    if not records:
        ev.update(applied=0, ms=_ms(t0))
        return Turn(sheet, ledger, False, "\n".join(tail(cards)) or "No change was needed.", cards=cards, evidence=ev)

    saved = await L.save(new_sheet, sheet, new_ledger)
    if saved.status == "refused":
        ev.update(applied=0, refused=True, ms=_ms(t0))
        return Turn(sheet, ledger, False, saved.message, cards=cards, refused=True, evidence=ev)
    cards += saved.cards
    if saved.sheet == sheet and saved.ledger == ledger:      # nothing actually changed (decision 14)
        ev.update(applied=0, ms=_ms(t0))
        return Turn(sheet, ledger, False, "\n".join(tail(cards)) or "No change was needed.", cards=cards,
                    evidence=ev)
    notes += [n for n in (L.note(c) for c in saved.ledger_changes) if n]
    lines = claims + notes + tail(cards) + ([UNMATCHED_LINE] if saved.unmatched else []) + (
        [saved.message] if saved.message else [])
    ev.update(applied=len(records), unmatched=len(saved.unmatched), ms=_ms(t0))
    logger.info("[chat-router] yes=%s unsure=%s applied=%d cards=%d failed=%s ms=%d", yes, unsure, len(records),
                len(cards), failed, ev["ms"])
    return Turn(saved.sheet, saved.ledger, True, "\n".join(lines), claim=" ".join(claims), records=records,
                cards=cards, notice=saved.message, unmatched=saved.unmatched, evidence=ev)
