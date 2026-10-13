"""The chat-edit router (spec 2026-10-13-chat-edit-router-design). A chat instruction that changes a template's
rules is applied by code through the decision ledger, the way a card tap is; a change of style is applied by a
lightweight call that can only touch prose. No model rewrites the whole sheet.

route_turn: Jev tags -> one targeted call per kind tagged >= TAG_MIN (parallel; no tag at the threshold: today's
refine, Hassan 2026-10-13) -> code validates each structured change -> applied (style first,
then layout and unit edits, then ledger writes; plan decision 8), carded or asked -> the save function (origin
"chat"), which applies the ledger last -> the reply, one line per applied change. A failed tag call raises Fallback
and the endpoint runs today's whole-sheet refine (the fallback stays until the lab and live data say otherwise)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
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
from . import template_sheet_grammar as tsg

logger = logging.getLogger(__name__)

ROUTER_VERSION = "router-1"
# cost caps (review of Tasks 6-11): every truncation is logged and recorded in the evidence
MAX_REQUIRES_LINES = 8     # new prose lines asked "does this require the report to state something?" per turn
MAX_REROUTES = 3           # flagged lines sent back through the rule route per turn (in parallel)
MAX_CHANGES_PER_CALL = 10  # structured changes used from one targeted call
TURN_TIMEOUT_S = 45.0      # one turn's model work; past it, what is done is applied and the rest is asked again
WORK_KINDS = ("value", "concept", "fixed", "normal", "layout", "style")
KIND_LABEL = CH.KIND_LABEL
CARDS_LINE = "I wasn't sure about part of that: choose below."
UNMATCHED_LINE = ("Some decisions no longer match a line in the template; they will be asked again at the next "
                  "review.")
HABIT_KINDS = ("value", "normal", "fixed")   # never written for a finding-triggered habit (until item 5)
HABIT_LINE = ("That reads as a habit for when a particular finding is present. I've saved it to set up later; nothing "
              "in the template changed for it.")
HABIT_DROPPED = ("I didn't change the {label} part; it reads as a habit for when a particular finding is present, "
                 "so it is saved to set up later.")
HABIT_ASK = ("That reads as a habit for when a particular finding is present. Which finding should it apply to? I've "
             "saved it to set up later; nothing in the template changed for it.")
_HABIT_LEAD = re.compile(r"^\s*(?:with|when|whenever|if|in)\s+(?P<cond>[^,;]+?)\s*[,;]?\s+(?P<rest>(?:always|please|"
                         r"then|also|mention|comment|say|state|add|ask|report|describe|note)\b.*)$", re.I)
_HABIT_TAIL = re.compile(r"^(?P<rest>.+?)\s*,?\s+(?:when(?:ever)?|if)\s+(?P<cond>.+?)\s*$", re.I)
_HABIT_MID = re.compile(r"^\s*(?:when(?:ever)?|if)\s+(?P<cond>.+?)\s+(?P<rest>(?:say|mention|comment|state|add|ask|"
                        r"report|describe|note)\b.*)$", re.I)
STYLE_UNVERIFIED = "I wasn't sure you asked for this, so I left it out: {claim}"
STYLE_EDIT_MISMATCH = "I left out a wording change that went further than it said: {claim}"
_LABEL_WORD = re.compile(r"[a-z][a-z0-9]{3,}")


def block_label(block: sh.Block) -> str:
    """How a claim names a prose block: its paragraph's name, else its heading."""
    ph = tsg.paragraph_heading(block.heading)
    return ph[0] if ph else block.heading


def _names(label: str, claim: str) -> bool:
    return bool(label) and re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", claim) is not None


def specific_claim(claim: str, block: sh.Block, blocks=()) -> bool:
    """A style claim is specific when it names the block it changes - a structural check, run before any Jev call
    ("the wording is changed" names nothing). In order of preference: the exact block id; the block's full label
    (paragraph name, else heading), unless the claim names another block whose longer label contains it; a 4+
    letter word of the label that no other block's label has. Matches are bounded on both sides, so two blocks that
    share a word never satisfy each other."""
    c = (claim or "").lower()
    if not c.strip():
        return False
    if _names(block.id.lower(), c):
        return True
    label = block_label(block).lower()
    others = [block_label(o).lower() for o in blocks if o.id != block.id]
    if _names(label, c):
        return not any(label in o and o != label and _names(o, c) for o in others)
    shared = {w for o in others for w in _LABEL_WORD.findall(o)}
    return any(_names(w, c) for w in _LABEL_WORD.findall(label) if w not in shared)
CAPPED_LINE = "That wording change was long, so I applied the first part only. Please ask for the rest separately."
STYLE_TIMEOUT = "I couldn't finish the wording change just now, so I left it out. Please try that part again."
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
    return {"kind": v.kind, "action": v.action, "key": v.key, "op": (v.op or {}).get("op"),
            "invented": v.invented, "reason": (v.reason or "")[:200], "detail": (v.detail or "")[:300]}


def _ask_reply(scan: str, misfit: bool) -> str:
    s = f"{scan} " if scan else ""
    if misfit:
        return f"That doesn't look like part of a {s}report. What should these reports do differently?"
    return f"I'm not sure what to change in these {s}reports. What should they do differently?"


def _park_habit(instruction: str, score: float) -> Tuple[dict, str, dict]:
    """(parked-habit card, reply line, evidence) for a finding-triggered habit. The condition is read by a simple
    pattern ("with X, always Y" / "Y when X"); without one the reply asks which finding. Nothing is written: the
    instruction is kept in the turn's evidence (routing) for item 5 to set up."""
    text = " ".join((instruction or "").split()).rstrip(".")
    m = _HABIT_LEAD.match(text) or _HABIT_MID.match(text) or _HABIT_TAIL.match(text)
    cond, rest = (m.group("cond").strip(), m.group("rest").strip()) if m else ("", text)
    title = f"Saved as a habit to set up: when {cond}, {rest}" if cond else f"Saved as a habit to set up: {text}"
    card = {"id": "habit:" + hashlib.sha1(text.encode()).hexdigest()[:10], "kind": "habit", "title": title,
            "instruction": instruction}
    logger.info("[chat-router] habit parked (score %.2f, condition found: %s)", score, bool(cond))
    return card, (HABIT_LINE if cond else HABIT_ASK), {"score": round(score, 3), "condition": cond,
                                                      "parked": instruction}


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
        try:
            if v.action == "edit":
                before = sheet
                sheet, inverse = E.apply_op(sheet, v.op)
                rec = {"type": "edit", "kind": v.kind, "op": v.op, "inverse": inverse, "claim": v.claim}
                ledger, rec, moved = _ledger_for_edit(ledger, before, v.op, rec)
                records.append(rec)
                if moved:
                    records.append({"type": "ledger", "change": moved, "claim": ""})
                    notes.append(L.note(moved))
                if v.choice is not None:            # a new unit line is also a decision
                    ledger, change = L.set_choice(ledger, v.kind, v.key, v.choice)
                    if change:
                        records.append({"type": "ledger", "change": change, "claim": ""})
                claims.append(v.claim)
                continue
            if v.kind == "value" and not seeded:
                ledger, seeded = L.seed_values(ledger, sheet), True
            ledger, change = L.set_choice(ledger, v.kind, v.key, v.choice)
            if change is None:
                problems.append(f"Already the case: {v.claim}")
                continue
            records.append({"type": "ledger", "change": change, "claim": v.claim})
            claims.append(v.claim)
            notes.append(L.note(change))
        except (E.EditError, L.Rejected) as e:   # the reason is internal: evidence only (decision 15)
            problems.append(f"I couldn't make this change: {v.claim.rstrip('.')}.")
            detail.append(f"{v.kind}: {str(e)[:200]}")
    return sheet, ledger, records, claims, [n for n in notes if n], problems, detail


async def _reroute(lines: List[str], ctx: CH.Ctx) -> List[CH.Verdict]:
    """A prose line that requires the report to state something goes back through the rule route (normal, fixed);
    its wording is the model's, so it is always a card. No rule kind fits: the reply asks (spec Flow 3)."""
    def ask(line: str) -> CH.Verdict:
        return CH.Verdict("style", "ask", reason=f'I left out "{line}": it reads as something every report must '
                                                 "state. Which part of the report should state it?")

    async def one(line: str) -> CH.Verdict:
        instr = f'Every report should state: "{line}"'
        res = await asyncio.gather(*(C.call_kind(k, instr, V.view(k, ctx.sheet, ctx.ledger)) for k in ("normal", "fixed")),
                                   return_exceptions=True)
        found = [CH.to_card(CH.validate(k, c, ctx)) for k, r in zip(("normal", "fixed"), res)
                 if not isinstance(r, BaseException) for c in r.changes[:MAX_CHANGES_PER_CALL]]
        found = [v for v in found if v.action == "card"]
        return found[0] if found else ask(line)

    head, rest = lines[:MAX_REROUTES], lines[MAX_REROUTES:]
    if rest:
        logger.info("[chat-router] reroutes capped: %d of %d lines asked without a call", len(rest), len(lines))
    return list(await asyncio.gather(*(one(l) for l in head))) + [ask(l) for l in rest]


async def _style(sheet: str, out: CH.StyleOut, ctx: CH.Ctx, *, scan: str = "", verified: bool = False,
                 habit: bool = False):
    """(sheet, style record or None, reply lines, extra verdicts, evidence) for a style output: unit lines must be
    untouched; each changed block's claim is verified against the instruction (Jev V1, Hassan 2026-10-13: replaces
    the content-word overlap check) and a block whose claim fails is not applied; each new prose line is asked
    whether it requires the report to state something, and a yes is left out of the edit and re-routed.
    `verified`: the caller already asked V1 for these claims (arm 2). `habit`: the habit guard fired, so a flagged
    line is left out and NOT re-routed (it must not become a normal or fixed card; Hassan 2026-10-13)."""
    blocks = {b.id: b for b in sh.prose_blocks(sheet)}
    edits = {b.id: b.text.strip("\n") for b in out.blocks
             if b.id in blocks and b.text.strip("\n") != blocks[b.id].text}
    if not edits:
        return sheet, None, [], [], {}
    try:   # unit lines untouched, and no new grammar error (a miscased unit-like line such as Normal [x] "...")
        if not sh.units_unchanged(sheet, sh.splice(sheet, edits)):
            raise E.EditError("unit line changed")
        E.guarded(sheet, sh.splice(sheet, edits))
    except E.EditError:
        return sheet, None, [STYLE_TOUCHED_RULES], [], {"style": "unit_line_changed"}
    new = [l for b, t in edits.items() for l in sh.new_lines(blocks[b].text, t)]
    over = new[MAX_REQUIRES_LINES:]           # unchecked lines are never applied: left out like a flagged line
    new = new[:MAX_REQUIRES_LINES]
    if over:
        logger.info("[chat-router] requires capped: %d new prose lines left out", len(over))
    by_id = {b.id: b for b in out.blocks}
    claims = {b: (by_id[b].claim or out.summary or "").strip() for b in edits}
    vague = [b for b in edits if not specific_claim(claims[b], blocks[b], blocks.values())] if not verified else []
    asked = [b for b in edits if b not in vague] if not verified else []

    checked = [b for b in edits if b not in vague]   # the claim against the edit itself (OLD -> NEW), both arms

    async def none():
        return []
    try:   # the line questions, the block claims (one call) and the edit checks (one call), together
        scores, claim_scores, edit_scores = await asyncio.gather(
            J.requires(new),
            J.verify_claims(scan, ctx.instruction, [claims[b] for b in asked]) if asked else none(),
            J.verify_edits([(blocks[b].text, edits[b], claims[b]) for b in checked]) if checked else none())
    except Exception as e:
        logger.warning("[chat-router] style checks failed: %s", type(e).__name__)
        return sheet, None, [REQUIRES_FAILED], [], {"style": "requires_failed"}
    claim_of, edit_of = dict(zip(asked, claim_scores)), dict(zip(checked, edit_scores))
    style_claims = []
    for b in edits:
        claim_ok = verified or claim_of.get(b, 0.0) >= J.CLAIM_MIN
        edit_ok = edit_of.get(b, 0.0) >= J.EDIT_MIN
        style_claims.append({"block": b, "claim": claims[b],
                             "score": round(claim_of[b], 3) if b in claim_of else None,
                             "edit_score": round(edit_of[b], 3) if b in edit_of else None,
                             "verified": b not in vague and claim_ok and edit_ok,
                             **({"vague": True} if b in vague else {})})
    refused = [c for c in style_claims if not c["verified"]]
    claim_lines = [(STYLE_EDIT_MISMATCH if (c["edit_score"] is not None and c["edit_score"] < J.EDIT_MIN
                                            and (c["score"] is None or c["score"] >= J.CLAIM_MIN))
                    else STYLE_UNVERIFIED).format(claim=c["claim"] or "a change of wording") for c in refused]
    edits = {b: t for b, t in edits.items() if b not in {c["block"] for c in refused}}
    flagged = [l for l, s in zip(new, scores) if s >= J.REQUIRES_MIN]
    ev = {"style": "applied", "disguise": [{"line": l[:200], "score": round(s, 3)} for l, s in zip(new, scores)],
          "truncated": {"requires": len(over), "reroutes": max(0, len(flagged) - MAX_REROUTES)}}
    ev["style_claims"] = style_claims
    lines_out = ([CAPPED_LINE] if over else []) + claim_lines
    if flagged or over:
        fl = {sh.norm(x) for x in flagged + over}
        edits = {b: "\n".join(x for x in t.splitlines() if sh.norm(x) not in fl) for b, t in edits.items()}
        # a block left empty keeps its old prose (the radiologist did not ask to delete it)
        edits = {b: t for b, t in edits.items() if t.strip() and t.strip("\n") != blocks[b].text}
    rerouted = await _reroute(flagged, ctx) if flagged and not habit else []
    if not edits:
        return sheet, None, lines_out, rerouted, {**ev, "style": "all_rerouted"}
    rec = {"type": "style", "blocks": [{"before": blocks[b].text, "after": edits[b]} for b in edits],
           "claim": out.summary.strip() or "The wording guidance is updated."}
    return sh.splice(sheet, edits), rec, lines_out, rerouted, ev


async def route_turn(sheet: str, ledger: List[dict], instruction: str, *, context: str = "",
                     rejection: Optional[dict] = None) -> Turn:
    # The turn deadline starts here, before the tag call: tag + targeted calls (+ the style check) are bounded by
    # TURN_TIMEOUT_S together. The save that follows is outside it; its unit checks have their own timeout.
    t0 = time.monotonic()
    scan = sh.scan_type(sheet)
    try:
        tags = await asyncio.wait_for(J.tag(instruction, scan, context), timeout=TURN_TIMEOUT_S)
    except Exception as e:
        logger.warning("[chat-router] tag call failed: %s: %s", type(e).__name__, str(e)[:200])
        raise Fallback(type(e).__name__) from e
    ledger = L.clean(ledger)
    yes = [k for k in WORK_KINDS if tags[k] >= J.TAG_MIN]
    ev = {"version": ROUTER_VERSION, "route": "router", "tags": {k: round(v, 3) for k, v in tags.items()},
          "yes": yes}
    if tags["misfit"] >= J.TAG_MIN:      # a misfit blocks the turn (misfit_B wording, >= 0.5)
        ev.update(route="ask", applied=0, ms=_ms(t0))
        return Turn(sheet, ledger, False, _ask_reply(scan, True), evidence=ev)
    habit_card, habit_line = None, ""
    if tags.get("habit", 0.0) >= J.HABIT_MIN:   # parked, never written as a rule line (until item 5)
        habit_card, habit_line, ev["habit"] = _park_habit(instruction, tags["habit"])
        dropped = [k for k in yes if k in HABIT_KINDS]
        ev["habit_dropped"] = dropped
        habit_line = "\n".join([habit_line] + [HABIT_DROPPED.format(label=KIND_LABEL[k]) for k in dropped])
        yes = [k for k in yes if k not in HABIT_KINDS]
        if not yes:
            ev.update(applied=0, ms=_ms(t0))
            return Turn(sheet, ledger, False, habit_line, cards=[habit_card], evidence=ev)
    if not yes:   # nothing tagged at the threshold: today's whole-sheet refine for now (Hassan 2026-10-13)
        raise Fallback("no_tag")

    wording = instruction + ("\n" + (rejection.get("original_instruction") or "") if rejection else "")
    ctx = CH.Ctx(sheet, ledger, wording)
    kinds = yes
    deadline = t0 + TURN_TIMEOUT_S
    tasks = {k: asyncio.ensure_future(C.call_kind(k, instruction, V.view(k, sheet, ledger), context, rejection))
             for k in kinds}
    _, pending = await asyncio.wait(list(tasks.values()), timeout=max(0.0, deadline - time.monotonic()))
    timed_out = [k for k, t in tasks.items() if t in pending]
    for k in timed_out:     # fail soft: those parts are asked again, the rest is applied
        tasks[k].cancel()
    if timed_out:
        logger.warning("[chat-router] turn deadline: %s not done", timed_out)
    results = [None if k in timed_out else (tasks[k].exception() or tasks[k].result()) for k in kinds]
    verdicts: List[CH.Verdict] = []
    asks: List[str] = []
    failed: List[str] = list(timed_out)
    truncated_changes = {}
    style_out = None
    for k, res in zip(kinds, results):
        if res is None:
            continue
        if isinstance(res, BaseException):
            logger.warning("[chat-router] %s call failed: %s", k, type(res).__name__)
            failed.append(k)
            continue
        if (res.question or "").strip():
            asks.append(res.question.strip())
        if k == "style":
            style_out = res
            continue
        if len(res.changes) > MAX_CHANGES_PER_CALL:
            truncated_changes[k] = len(res.changes) - MAX_CHANGES_PER_CALL
            logger.info("[chat-router] %s changes capped: %d dropped", k, truncated_changes[k])
        for c in res.changes[:MAX_CHANGES_PER_CALL]:
            v = CH.validate(k, c, ctx)
            verdicts.append(v)

    styled, style_rec, style_lines, style_ev = sheet, None, [], {}
    if style_out is not None and style_out.blocks:
        try:
            styled, style_rec, style_lines, extra, style_ev = await asyncio.wait_for(
                _style(sheet, style_out, ctx, scan=scan, habit=bool(habit_card)),
                timeout=max(0.01, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            logger.warning("[chat-router] turn deadline: the style check did not finish")
            style_lines, extra, style_ev = [STYLE_TIMEOUT], [], {"style": "timed_out"}
            timed_out.append("style")
        verdicts += extra

    new_sheet, new_ledger, records, claims, notes, problems, detail = _apply(
        styled, ledger, [v for v in verdicts if v.action in ("ledger", "edit")])
    if style_rec:
        records.insert(0, style_rec)
        claims.insert(0, style_rec["claim"])
    cards = ([habit_card] if habit_card else []) + [v.card for v in verdicts if v.action == "card" and v.card]
    if habit_line:
        asks.append(habit_line)
    asks += [v.reason for v in verdicts if v.action in ("ask", "reject") and v.reason]
    fails = [f"I couldn't change {KIND_LABEL[k]} just now; please try that part again." for k in failed]
    truncated = {"changes": truncated_changes, **(style_ev.pop("truncated", None) or {})}
    ev.update(changes=[_ev(v) for v in verdicts], cards=len(cards), failed=failed, problems=detail,
              timed_out=timed_out, truncated=truncated, **style_ev)

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
    logger.info("[chat-router] yes=%s applied=%d cards=%d failed=%s ms=%d", yes, len(records),
                len(cards), failed, ev["ms"])
    return Turn(saved.sheet, saved.ledger, True, "\n".join(lines), claim=" ".join(claims), records=records,
                cards=cards, notice=saved.message, unmatched=saved.unmatched, evidence=ev)


CARD_REJECTED = "I couldn't apply that choice. Could you tell me in the chat what you want instead?"


def enabled() -> bool:
    """The kill switch (plan decision 1, D-R3): off unless RR_CHAT_ROUTER=1 and a Jev key is set; off sends every
    turn down today's path."""
    return os.environ.get("RR_CHAT_ROUTER", "0") == "1" and bool(os.environ.get("OPENROUTER_API_KEY"))


def response(turn: Turn) -> dict:
    """The /skill-sheet/refine (and /undo, /card) response for a router turn."""
    out = {"success": True, "skill_sheet": turn.sheet, "response": turn.reply,
           "behavioral_claim": turn.claim if turn.applied else "", "applied": turn.applied, "route": "router",
           "changes": turn.records, "cards": turn.cards, "decisions": turn.ledger, "unmatched": turn.unmatched}
    if turn.notice:
        out["notice"] = turn.notice
    return out


async def undo_turn(sheet: str, ledger: List[dict], records: List[dict]) -> Turn:
    """Reverse a turn's records, newest first (plan decision 10): a ledger write only while its entry still holds
    the turn's value; a code edit by its inverse ops; a style block only while its edited text is still there.
    Anything a later turn changed is left alone and counted as skipped."""
    t0 = time.monotonic()
    original = L.clean(ledger)
    led, cur = list(original), sheet
    undone: List[str] = []
    skipped = 0
    for rec in reversed(records or []):
        try:
            kind = rec.get("type")
            if kind == "ledger":
                before = led
                led = L.undo(led, rec["change"])
                if led == before:
                    skipped += 1
                    continue
            elif kind == "edit":
                for inv in reversed(rec.get("inverse") or []):
                    prev = cur
                    cur, _ = E.apply_op(cur, inv)
                    led, _, _ = _ledger_for_edit(led, prev, inv, {}, undoing=True)
                for e in rec.get("dropped") or []:   # client-sent: validated before it goes back (L.restore)
                    try:
                        led = L.restore(led, e)
                    except L.Rejected as err:
                        logger.info("[chat-router] undo refused a dropped entry: %s", err)
            elif kind == "style":
                hit = False
                for b in rec.get("blocks") or []:
                    if b.get("after") and b["after"] in cur:
                        candidate = cur.replace(b["after"], b["before"], 1)
                        if not sh.units_unchanged(cur, candidate):   # a client-sent record cannot write a unit line
                            logger.info("[chat-router] style undo refused: it would change a unit line")
                            continue
                        cur, hit = candidate, True
                if not hit:
                    skipped += 1
                    continue
            else:
                continue
            if rec.get("claim"):
                undone.append(rec["claim"])
        except (E.EditError, L.Rejected, KeyError) as e:
            logger.info("[chat-router] undo skipped a %s record: %s", rec.get("type"), e)
            skipped += 1
    ev = {"version": ROUTER_VERSION, "route": "undo", "records": len(records or []), "skipped": skipped}
    if cur == sheet and led == original:
        ev["ms"] = _ms(t0)
        return Turn(sheet, original, False, "Nothing to undo: it has changed since.", evidence=ev)
    saved = await L.save(cur, sheet, led)
    ev["ms"] = _ms(t0)
    if saved.status == "refused":
        return Turn(sheet, original, False, saved.message, refused=True, evidence={**ev, "refused": True})
    reply = "\n".join(f"Undone: {c}" for c in undone) or "Undone."
    if skipped:
        reply += "\nPart of it had changed since, so I left that part as it is."
    return Turn(saved.sheet, saved.ledger, True, reply, notice=saved.message, unmatched=saved.unmatched, evidence=ev)


async def answer_card(sheet: str, ledger: List[dict], answer: dict) -> Turn:
    """Apply a tapped card (plan decision 11): {"kind", "key", "choice"} for a ledger card, or {"proposal": <the
    card's apply>} for a proposal card. Written as source "chat"; the wording check is skipped (the radiologist
    chose it); code still validates and the save function still vets."""
    t0 = time.monotonic()
    ledger = L.clean(ledger)
    answer = answer or {}
    p = answer.get("proposal")
    if not p and answer.get("choice") == L.FORGET:   # "Forget this decision" (an unmatched entry's card)
        return await _forget(sheet, ledger, answer.get("kind", ""), answer.get("key", ""), t0)
    if p:
        v = CH.check_proposal(p, sheet)   # client-sent: forward ops only, allowed slots, a dry run (review fix)
        if v.action == "reject":
            return Turn(sheet, ledger, False, CARD_REJECTED,
                        evidence={"version": ROUTER_VERSION, "route": "card", "detail": v.detail})
    else:
        try:
            key, choice = L.check((answer or {}).get("kind", ""), (answer or {}).get("key", ""),
                                  (answer or {}).get("choice") or {})
        except L.Rejected as e:   # internal text stays in the evidence (decision 15)
            return Turn(sheet, ledger, False, CARD_REJECTED,
                        evidence={"version": ROUTER_VERSION, "route": "card", "detail": str(e)[:300]})
        v = CH.Verdict(answer["kind"], "ledger", key=key, choice=choice, claim=CH.claim_for(answer["kind"], key, choice))
    new_sheet, new_ledger, records, claims, notes, problems, detail = _apply(sheet, ledger, [v])
    ev = {"version": ROUTER_VERSION, "route": "card", "kind": v.kind, "proposal": bool(p), "applied": len(records),
          "detail": "; ".join(detail)}
    if not records:
        ev["ms"] = _ms(t0)
        return Turn(sheet, ledger, False, "\n".join(problems) or "No change was needed.", evidence=ev)
    saved = await L.save(new_sheet, sheet, new_ledger)
    ev["ms"] = _ms(t0)
    if saved.status == "refused":
        return Turn(sheet, ledger, False, saved.message, refused=True, evidence={**ev, "refused": True})
    notes += [n for n in (L.note(c) for c in saved.ledger_changes) if n]
    if saved.sheet == sheet and saved.ledger == ledger:
        return Turn(sheet, ledger, False, "No change was needed.", evidence=ev)
    return Turn(saved.sheet, saved.ledger, True, "\n".join(claims + notes + ([UNMATCHED_LINE] if saved.unmatched else [])
                                                              + ([saved.message] if saved.message else [])),
                claim=" ".join(claims), records=records, cards=saved.cards, notice=saved.message,
                unmatched=saved.unmatched, evidence=ev)


async def _forget(sheet: str, ledger: List[dict], kind: str, key: str, t0: float) -> Turn:
    led, change = L.forget(ledger, kind, key)
    ev = {"version": ROUTER_VERSION, "route": "card", "kind": kind, "forget": True, "applied": int(bool(change))}
    if change is None:
        ev["ms"] = _ms(t0)
        return Turn(sheet, ledger, False, "No change was needed.", evidence=ev)
    claim = f"Forgot this decision: {change['key']}."
    saved = await L.save(sheet, sheet, led)
    ev["ms"] = _ms(t0)
    if saved.status == "refused":
        return Turn(sheet, ledger, False, saved.message, refused=True, evidence={**ev, "refused": True})
    return Turn(saved.sheet, saved.ledger, True, claim, claim=claim,
                records=[{"type": "ledger", "change": change, "claim": claim}],
                notice=saved.message, unmatched=saved.unmatched, evidence=ev)
