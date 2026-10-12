"""Jev questions of scratchpad v2 (spec 2026-10-11 §4.1, §7.3): the voice command of a final (with its
target region or chip), and whether the dictation already states a chip. Thresholds come from the labs
(scripts/hybrid_stack_eval/labs; spec §10)."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
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


# ── Checklist rows (checklist spec §5, wording lab §10.2) ─────────────────────
REMOVED_MIN = 0.6  # lab 2026-10-11 (40 pairs): 17/20 rewordings caught, 0/20 false
HEDGED_MIN = 0.3   # a region normal the dictation even half-covers or hedges is never assumed


@dataclass(frozen=True)
class RowCheck:
    stated: float
    contra: float
    removed: float


def removed_key(i: int) -> str:
    return f"removed_{i}"


def removed_question(sentence: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": (
        "The STATEMENT says the same thing as one of the REMOVED statements: the same check on the same structure, "
        f"in any wording. STATEMENT: {sentence}")}


async def ask_rows(dictation: str, sentences: list[str], removed: list[str], transport=None) -> list[RowCheck]:
    """Stated, contradicted and (when the radiologist removed anything) the same as a removed sentence, per
    sentence, in one Jev call."""
    if not sentences:
        return []
    qs: dict[str, dict[str, Any]] = {}
    for i, s in enumerate(sentences):
        qs[f"stated_{i}"] = stated_question(s)
        qs[contra_key(i)] = contra_question(s)
        if removed:
            qs[removed_key(i)] = removed_question(s)
    state = f"DICTATION:\n{dictation}"
    if removed:
        state += "\n\nREMOVED BY THE RADIOLOGIST:\n" + "\n".join(f"- {r}" for r in removed)
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    score = lambda k: float((ans.get(k) or {}).get("noul") or 0.0)
    return [RowCheck(score(f"stated_{i}"), score(contra_key(i)), score(removed_key(i))) for i in range(len(sentences))]


def row_fate(c: RowCheck) -> str:
    """A row sentence: 'answered' (the dictation says it), 'contradicted', 'removed' or 'keep' (stays in the row,
    where the radiologist answers it)."""
    if c.removed >= REMOVED_MIN:
        return "removed"
    if c.stated >= STATED_MIN:
        return "answered"
    if c.contra >= CONTRA_MIN:
        return "contradicted"
    return "keep"


def normal_assumed(c: RowCheck) -> bool:
    """A region normal of an abnormal region is assumed only when the dictation neither covers, hedges nor
    contradicts it and the radiologist has not removed it."""
    return c.stated < HEDGED_MIN and c.contra < HEDGED_MIN and c.removed < REMOVED_MIN


# ── Review gates (labs 2026-10-12, scripts/scratchpad_v2_labs.py material | conclusion) ──────────────────────────
MATERIAL_MIN = 0.6  # 40 pairs: material 21/21 at >= 0.95 (5 size/unit corrections included), rewordings all <= 0.57
STALE_MIN = 0.7     # 24 pairs: out of date 13/13 (lowest 0.74), still current 0/11 (highest 0.66)

MATERIAL_QUESTION = (
    "Compared with BEFORE, the AFTER findings add, remove or change an abnormal finding (a new finding, a finding gone, "
    "a different size or measurement, side, extent, character, relationship or complication), rather than only "
    "rewording, reordering, correcting spelling, or writing the same measurement in another format or unit.")
STALE_QUESTION = ("The CONCLUSION needs updating because the FINDINGS now report something important it does not "
                  "reflect.")


async def _noul(state: str, instructions: str, transport=None) -> float:
    r = await jev_post({"model": JEV_MODEL, "state": state,
                        "questions": {"q": {"type": "noul", "instructions": instructions}}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    return float(((r.json().get("answers") or {}).get("q") or {}).get("noul") or 0.0)


async def ask_material(before: list[str], after: list[str], transport=None) -> float:
    """P(the abnormal findings changed in a way that changes what should be checked), not just their wording."""
    state = ("BEFORE:\n" + ("\n".join(f"- {b}" for b in before) or "(none)") + "\n\nAFTER:\n"
             + ("\n".join(f"- {a}" for a in after) or "(none)"))
    return await _noul(state, MATERIAL_QUESTION, transport)


async def ask_stale(conclusion: str, findings: list[str], transport=None) -> float:
    """P(the conclusion no longer reflects something important in the findings)."""
    state = "FINDINGS:\n" + "\n".join(f"- {f}" for f in findings) + f"\n\nCONCLUSION:\n{conclusion}"
    return await _noul(state, STALE_QUESTION, transport)


# ── Unfinished sentences (lab 2026-10-12, scripts/unfinished_lab.py, 18 unfinished / 22 finished, 2 runs) ─────────
# The scratchpad's only unfinished-sentence check (replaces the regex tier there): wording A, unfinished all >= 0.84,
# finished all <= 0.55 (a lone heading 0.51, "hydronephrosis to a … calculus" 0.55). Asked inside the dictation, so a
# sentence that runs into the next statement or heading is seen as such.
UNFINISHED_MIN = 0.7
UNFINISHED_BATCH = 10   # sentences per Jev call; batches run in parallel
UNFINISHED_QUESTION = (
    "SENTENCE stops before its statement is complete: it ends on a word that needs more after it (a verb, preposition, "
    "conjunction or article), a measurement or comparison is left without its value, or it runs straight into another "
    "statement or heading with the first left unfinished. A short deliberate fragment that states a complete finding, "
    "a sweeping remark or a heading on its own is not unfinished. SENTENCE: {s}")


async def ask_unfinished(sentences: list[str], transport=None) -> list[float]:
    """P(unfinished) per sentence, each asked with the whole dictation as its context."""
    if not sentences:
        return []
    state = "DICTATION:\n" + "\n".join(sentences)

    async def batch(start: int, chunk: list[str]) -> list[float]:
        qs = {f"u{start + i}": {"type": "noul", "instructions": UNFINISHED_QUESTION.format(s=s)} for i, s in enumerate(chunk)}
        r = await jev_post({"model": JEV_MODEL, "state": state, "questions": qs},
                           os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S * 2, transport)
        r.raise_for_status()
        a = r.json().get("answers") or {}
        return [float((a.get(f"u{start + i}") or {}).get("noul") or 0.0) for i in range(len(chunk))]

    parts = await asyncio.gather(*(batch(k, sentences[k:k + UNFINISHED_BATCH])
                                   for k in range(0, len(sentences), UNFINISHED_BATCH)))
    return [x for p in parts for x in p]
