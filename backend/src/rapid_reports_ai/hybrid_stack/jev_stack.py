"""Jev questions of scratchpad v2 (spec 2026-10-11 §4.1, §7.3): the voice command of a final (with its
target region or chip), and whether the dictation already states a chip. Thresholds come from the labs
(scripts/hybrid_stack_eval/labs; spec §10)."""
from __future__ import annotations

import os
from typing import Any

from ..jev_client import JEV_MODEL, jev_post

TIMEOUT_S = 3.0
NONE = "none"
COMMANDS = ("dictate", "correct", "delete", "send_to_region", "accept_suggestion")

COMMAND_QUESTION: dict[str, Any] = {
    "type": "choice",
    "instructions": ("The radiologist is dictating into a report scratchpad. What does the LATEST UTTERANCE ask the "
                     "scratchpad to do?"),
    "criteria": {
        "dictate": ("Write it down: it is report content (a finding, measurement, normality statement, negative, "
                    "comparison, conclusion or recommendation), including content that names a structure or region "
                    "or uses a word such as delete or accept as part of the content."),
        "correct": ("Revise something the radiologist has just said: it replaces a value, side, level or descriptor "
                    "already dictated (for example introduced by actually, sorry, correction or make that)."),
        "delete": ("Remove text: it asks to remove the last thing said, or a named line or sentence, and adds no "
                   "content of its own."),
        "send_to_region": ("Route content: it names the region the following content belongs to (for the X, under X, "
                           "put this in X), usually followed by that content."),
        "accept_suggestion": "Accept a suggestion: it asks to accept, add or include one of the SUGGESTIONS shown.",
    },
}


def region_question(regions: list[str]) -> dict[str, Any]:
    crit = {r: f"It names this region, or a structure that belongs to it: {r}." for r in regions}
    crit[NONE] = "It names no region."
    return {"type": "choice", "instructions": "Which region does the LATEST UTTERANCE name or route its content to?",
            "criteria": crit}


def chip_key(i: int) -> str:
    return f"chip_{i}"


def chip_question(chips: list[str]) -> dict[str, Any]:
    crit = {chip_key(i): c for i, c in enumerate(chips)}
    crit[NONE] = "It asks to accept none of the suggestions."
    return {"type": "choice", "instructions": "Which of the SUGGESTIONS does the LATEST UTTERANCE ask to accept?",
            "criteria": crit}


def stated_question(chip: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": (
        "The DICTATION already states this, or states something that makes it redundant (the same structure and "
        f"the same finding, at the same or stronger certainty): {chip}")}


def command_questions(regions: list[str], chips: list[str]) -> dict[str, dict[str, Any]]:
    qs: dict[str, dict[str, Any]] = {"command": COMMAND_QUESTION}
    if regions:
        qs["target_region"] = region_question(regions)
    if chips:
        qs["target_chip"] = chip_question(chips)
    return qs


def command_state(scratchpad: str, utterance: str, chips: list[str]) -> str:
    sug = "\n".join(f"- {c}" for c in chips) or "(none)"
    return f"SCRATCHPAD:\n{scratchpad}\n\nSUGGESTIONS:\n{sug}\n\nLATEST UTTERANCE:\n{utterance}"


def parse_command(answers: dict, chips: list[str]) -> dict:
    a = answers.get("command") or {}
    out = {"command": a.get("choice"), "confidence": float(a.get("confidence") or 0.0), "region": None, "chip": None}
    r = answers.get("target_region")
    if r and r.get("choice") not in (None, NONE):
        out["region"] = r["choice"]
    c = answers.get("target_chip")
    if c and isinstance(c.get("choice"), str) and c["choice"].startswith("chip_"):
        i = int(c["choice"].split("_")[1])
        out["chip"] = chips[i] if i < len(chips) else None
    return out


async def ask_command(scratchpad: str, utterance: str, regions: list[str], chips: list[str],
                      transport=None) -> dict:
    r = await jev_post({"model": JEV_MODEL, "state": command_state(scratchpad, utterance, chips),
                        "questions": command_questions(regions, chips)},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    return parse_command(r.json().get("answers") or {}, chips)


def contra_key(i: int) -> str:
    return f"contra_{i}"


def contra_question(chip: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": (
        "The DICTATION reports, or strongly suggests, the opposite of this statement for the same structure, so "
        f"stating it would contradict the dictation: {chip}")}


async def ask_checks(dictation: str, chips: list[str], transport=None) -> list[tuple[float, float]]:
    """(P already stated, P contradicted) per chip, in one Jev call."""
    if not chips:
        return []
    qs: dict[str, dict[str, Any]] = {}
    for i, c in enumerate(chips):
        qs[chip_key(i)] = stated_question(c)
        qs[contra_key(i)] = contra_question(c)
    r = await jev_post({"model": JEV_MODEL, "state": f"DICTATION:\n{dictation}", "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return [(float((ans.get(chip_key(i)) or {}).get("noul") or 0.0), float((ans.get(contra_key(i)) or {}).get("noul") or 0.0))
            for i in range(len(chips))]


async def ask_stated(dictation: str, chips: list[str], transport=None) -> list[float]:
    """P(already stated) per chip, in order."""
    if not chips:
        return []
    r = await jev_post({"model": JEV_MODEL, "state": f"DICTATION:\n{dictation}",
                        "questions": {chip_key(i): stated_question(c) for i, c in enumerate(chips)}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return [float((ans.get(chip_key(i)) or {}).get("noul") or 0.0) for i in range(len(chips))]


COMMAND_DELETE_MIN = 0.6  # lab 2026-10-11: no dictation read as delete; a named delete only selects
STATED_MIN = 0.8  # lab 2026-10-11 (64 pairs): 0 false "stated", recall 24/30
CONTRA_MIN = 0.7  # lab 2026-10-11: 4/4 contradicted, 0 others (asked with STATED in one call)
OPTIONAL_MIN = 0.3  # stated or contra at/above this, below the removal bars: hedged or partial -> opt-in


def chip_state(stated: float, contra: float) -> str:
    """'gone' (already stated or contradicted), 'optional' (the dictation hedges or half-covers it: the
    radiologist opts in) or 'included' (in the report unless removed; confirmed at the gate). Spec v2 §4."""
    if stated >= STATED_MIN or contra >= CONTRA_MIN:
        return "gone"
    if stated >= OPTIONAL_MIN or contra >= OPTIONAL_MIN:
        return "optional"
    return "included"


def decide_command(parsed: dict) -> dict:
    """The action of a final (spec v2 §7.3, lab §10.1). Accept: Jev reads an accept command and names a visible
    chip (a correction naming a chip is dictation: its words must never be replaced). Delete: at COMMAND_DELETE_MIN, with the named region if any. Everything else,
    correct included, is dictation (today's write path already handles corrections)."""
    cmd, conf = parsed.get("command"), float(parsed.get("confidence") or 0.0)
    if parsed.get("chip") and cmd == "accept_suggestion":
        return {"action": "accept", "region": None, "chip": parsed["chip"]}
    if cmd == "delete" and conf >= COMMAND_DELETE_MIN:
        return {"action": "delete", "region": parsed.get("region"), "chip": None}
    return {"action": "dictate", "region": None, "chip": None}
