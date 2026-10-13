"""The chat-edit router's Jev questions (spec Flow 1 and 3): one call tags a whole instruction with a yes/no per
kind of change (no splitting: a mixed instruction is several yeses); one call per new prose line asks whether a
style edit hid a rule. Thresholds are lab-set constants (scripts/chat_router_lab.py; Hassan sets them)."""
from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Tuple

from .jev_client import JEV_MODEL, jev_post

TIMEOUT_S = 4.0
TAG_MIN = 0.5        # only a kind at or above routes (Hassan 2026-10-13: no unsure band; supersedes D-R2)
REQUIRES_MIN = 0.5   # a new prose line at or above is a rule in disguise

KINDS = ("value", "concept", "fixed", "normal", "layout", "style", "misfit")


def _q(instructions: str, true: str = "", false: str = "") -> dict:
    q = {"type": "noul", "instructions": instructions}
    if true or false:
        q["criteria"] = {"true": true, "false": false}
    return q


# fixed, misfit and value are the wording-lab winners (2026-10-13: fixed_B, misfit_B, value_A in
# rr-template-conversion-private/synthetic/chat_router/wording_lab.py), word for word; the rest are the spec's.
QUESTIONS: Dict[str, dict] = {
    "value": _q("Does the INSTRUCTION ask to change which measured values every report must state?",
                "Yes: it adds, removes or changes a required measurement or numeric value (a size, volume, fraction, "
                "score, grade or level) that every report must give, or says one is needed only when relevant.",
                "No: it asks to always mention a finding, structure or normal statement, sets a habit triggered by "
                "a finding (when X is present, always say Y), or is about wording, layout or style."),
    "concept": _q("Does the INSTRUCTION ask to change how comparison / prior imaging, contrast, sequences not acquired "
                  "or a technical limitation is worded?"),
    "fixed": _q("Does the INSTRUCTION ask to change, add or remove one of the report's standing boilerplate sentences "
                "(text printed word for word in every report whatever the findings), rather than a finding, a normal "
                "statement, a value, the comparison or contrast wording, or the style?"),
    "normal": _q("Does the INSTRUCTION ask to change how a normal finding for a region is worded, or whether it is "
                 "stated?"),
    "layout": _q("Does the INSTRUCTION ask to add, remove, rename or reorder a section or paragraph?"),
    "style": _q("Does the INSTRUCTION ask to change style, tone, length or phrasing?"),
    "misfit": _q("Is the INSTRUCTION clearly unrelated to reports of this SCAN TYPE: asking for content this scan "
                 "cannot show, from another body region, modality or kind of document? A request to add, require or "
                 "mention something this scan could plausibly assess is not unrelated."),
}
# Habit guard until item 5 (findings-triggered rows): a rule that applies only when a finding is present must not be
# written as a normal, negative, value or always-printed line. Asked in the same tag call.
GUARDS = ("habit",)
QUESTIONS["habit"] = _q("The INSTRUCTION asks for something to be stated or asked only when a particular finding is "
                        "present.")
HABIT_MIN = 0.5

# V1 from the verify lab (2026-10-13, synthetic/chat_router/verify_lab.py): "did the instruction ask for this change?"
CLAIM_MIN = 0.5


def v1(claim: str) -> dict:
    return {"type": "noul", "instructions": f'Does the INSTRUCTION ask for this change: "{claim}"?'}

# requires_A from the same lab (req_A), word for word
REQUIRES: dict = _q("Does this LINE require the report to state something that the report could otherwise leave out?",
                    "Yes: it makes a finding, structure, value, comparison or statement mandatory in every report, or "
                    "in every report of a kind.",
                    "No: it only governs the order, format, units, precision, sentence length, tone or phrasing of "
                    "what is reported.")


def _score(answers: dict, key: str) -> float:
    v = (answers.get(key) or {}).get("noul")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("jev: incomplete answers")
    return float(v)


async def tag(instruction: str, scan_type: str = "", context: str = "", transport=None) -> Dict[str, float]:
    """P(yes) per kind in KINDS and per guard in GUARDS, one Jev call. Raises on any failure (the caller falls back)."""
    state = f"SCAN TYPE: {scan_type or 'not given'}\n\nINSTRUCTION:\n{(instruction or '').strip()}"
    if (context or "").strip():
        state += f"\n\nPREVIOUS REPLY (context only):\n{context.strip()}"
    r = await jev_post({"model": JEV_MODEL, "state": state,
                        "questions": {k: dict(QUESTIONS[k]) for k in KINDS + GUARDS}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    answers = r.json().get("answers") or {}
    return {k: _score(answers, k) for k in KINDS + GUARDS}


async def verify_claims(scan_type: str, instruction: str, claims: List[str], transport=None) -> List[float]:
    """V1 score per claim, all in ONE call on the instruction's state (as the verify lab asked it). Raises on
    failure; no call for no claims."""
    if not claims:
        return []
    state = f"SCAN TYPE: {scan_type or 'not given'}\n\nINSTRUCTION:\n{(instruction or '').strip()}"
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": {f"c{i}": v1(c) for i, c in enumerate(claims)}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    answers = r.json().get("answers") or {}
    return [_score(answers, f"c{i}") for i in range(len(claims))]


EDIT_MIN = 0.5
EDIT_CRITERIA = {"true": "every removed, added or reworded line is covered by the claim",
                 "false": "a line was removed, added or its meaning changed beyond the claim"}


def edit_question(n: int, claim: str) -> dict:
    return {"type": "noul", "instructions": f"For BLOCK {n}: Does the change from OLD to NEW consist only of what "
                                            f'this claim describes: "{claim}"?', "criteria": dict(EDIT_CRITERIA)}


async def verify_edits(edits: List[Tuple[str, str, str]], transport=None) -> List[float]:
    """Per (old block text, new block text, claim): does the edit consist only of what the claim describes? All blocks
    in ONE call (the state lists each block's OLD and NEW lines). Raises on failure; no call for no blocks."""
    if not edits:
        return []
    state = "\n\n".join(f"BLOCK {i + 1}\nOLD:\n{old.strip()}\nNEW:\n{new.strip()}" for i, (old, new, _) in enumerate(edits))
    r = await jev_post({"model": JEV_MODEL, "state": state,
                        "questions": {f"e{i}": edit_question(i + 1, c) for i, (_, _, c) in enumerate(edits)}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    answers = r.json().get("answers") or {}
    return [_score(answers, f"e{i}") for i in range(len(edits))]


async def requires(lines: List[str], transport=None) -> List[float]:
    """P(the line requires the report to state something), one Jev call per line, in order. Raises on failure."""
    async def one(line: str) -> float:
        r = await jev_post({"model": JEV_MODEL, "state": f"LINE:\n{line}",
                            "questions": {"q": dict(REQUIRES)}},
                           os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
        r.raise_for_status()
        return _score(r.json().get("answers") or {}, "q")
    if not lines:
        return []
    return list(await asyncio.gather(*(one(l) for l in lines)))
