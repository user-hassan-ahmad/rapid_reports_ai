"""Conclusion boundary (spec §3.6): a Jev choice decides whether a sentence after the conclusion
has begun is part of it. Also the uncued closing line, asked once when dictation stops."""
from __future__ import annotations

import asyncio
import os

from ..jev_client import JEV_MODEL, jev_post
from .schemas import CONCLUSION, GENERAL
from .units import StackUnit

MIN_CONF = 0.6  # lab fixture (65 sentences): both wrong answers were below 0.6
TIMEOUT_S = 10.0

BOUNDARY_QUESTION = {
    "type": "choice",
    "instructions": ("The radiologist has already begun their conclusion in the dictation. Decide what the "
                     "SENTENCE does."),
    "criteria": {
        "summary": ("It belongs to the conclusion: it summarises, restates or interprets findings already "
                    "given, states a diagnosis, differential, staging or response, or makes a recommendation "
                    "or communication note."),
        "images": ("It returns to describing the images: it reports an observation, measurement or detail "
                   "that the dictation has not already given, as a finding."),
    },
}
# The uncued closing line has no conclusion yet; the question's premise changes, the options do not.
CLOSING_QUESTION = {**BOUNDARY_QUESTION, "instructions": (
    "The radiologist has finished dictating and gave no conclusion cue. Decide what the final SENTENCE does.")}


def _state(before: list[str], sentence: str) -> str:
    return "DICTATION SO FAR:\n" + " ".join(before) + "\n\nSENTENCE:\n" + sentence


async def ask(before: list[str], sentence: str, question: dict = BOUNDARY_QUESTION,
              transport=None) -> tuple[str, float]:
    r = await jev_post({"model": JEV_MODEL, "state": _state(before, sentence), "questions": {"boundary": question}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    a = r.json()["answers"]["boundary"]
    return a["choice"], float(a.get("confidence") or 0.0)


def _decide(u: StackUnit, choice: str, conf: float) -> None:
    if conf < MIN_CONF:
        return
    if choice == "summary" and u.group != CONCLUSION:
        u.group, u.attach_to, u.parts = CONCLUSION, None, None
    elif choice == "images" and u.group == CONCLUSION:
        u.group, u.attach_to, u.parts = GENERAL, None, None  # no anatomical label to hand: logged


async def conclusion_gate(units: list[StackUnit], new_ids: list[int], transport=None) -> list[dict]:
    """For each new, unpinned, non-heading sentence after a Conclusion sentence: Jev decides at
    >= MIN_CONF; otherwise the grouper's placement stands. Fails open. Returns the log."""
    asks, started = [], False
    for k, u in enumerate(units):
        if u.id in new_ids and started and not u.heading and not u.pinned:
            asks.append((k, u))
        if u.group == CONCLUSION:
            started = True

    async def one(k: int, u: StackUnit):
        try:
            return u, *(await ask([x.text for x in units[:k]], u.text, transport=transport))
        except Exception as e:
            return u, f"error {type(e).__name__}", 0.0
    log = []
    for u, choice, conf in await asyncio.gather(*(one(k, u) for k, u in asks)):
        before = u.group
        _decide(u, choice, conf)
        log.append({"id": u.id, "choice": choice, "conf": round(conf, 2), "from": before, "to": u.group})
    return log


async def closing_check(units: list[StackUnit], transport=None) -> dict | None:
    """When dictation stops with no Conclusion: ask about the last sentence once (spec §3.6)."""
    if not units or any(u.group == CONCLUSION for u in units):
        return None
    last = units[-1]
    if last.pinned or last.heading:
        return None
    try:
        choice, conf = await ask([u.text for u in units[:-1]], last.text, CLOSING_QUESTION, transport)
    except Exception as e:
        return {"id": last.id, "choice": f"error {type(e).__name__}", "conf": 0.0, "from": last.group, "to": last.group}
    before = last.group
    if choice == "summary":  # an uncued line only ever moves into Conclusion, never out
        _decide(last, choice, conf)
    return {"id": last.id, "choice": choice, "conf": round(conf, 2), "from": before, "to": last.group}
