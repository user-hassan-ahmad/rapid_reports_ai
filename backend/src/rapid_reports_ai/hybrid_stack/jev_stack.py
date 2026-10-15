"""Jev questions of scratchpad v2 (spec 2026-10-11 §4.1, §7.3): the voice command of a final (with its
target region or chip), and whether the dictation already states a chip. Thresholds come from the labs
(scripts/hybrid_stack_eval/labs; spec §10)."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

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

# Instruction flag (design 2026-10-15-instruction-flag): asked in the same call, only when RR_STACK_INSTRUCTION_FLAG is
# on. An instruction no other option covers is held for the radiologist, never written and never obeyed.
INSTRUCTION = "instruction"
INSTRUCTION_CRITERION = (
    "An instruction to the software that is not report content: it asks for the report or scratchpad to be changed, "
    "cleared, restarted, reorganised, reformatted, rewritten or navigated, or for something said to be moved or made "
    "into another part of the report (such as the conclusion or impression), in a way none of the other options "
    "covers; or it is speech not meant for the report (talking to the software or to someone else). A sentence that "
    "records what was done, found, compared, communicated or advised (technique, a comparison, a reference to another "
    "report, who was told, a recommendation to the referrer) is report content.")
INSTRUCTION_MIN = 0.85  # lab 2026-10-15 (120 synthetic, 2 runs): 0/120 report sentences held (highest 0.81), 57/60 instructions held; Hassan picks the bar, the flag stays off until then


WRITING_ROUTES = ("fast_append", "polish")   # bundle routes that write the words as report text


def settle_instruction(stack: dict | None, bundle_route: str) -> dict | None:
    """A held instruction is flagged only when the bundle would write the words (fast_append, or polish, which also
    takes fillers and "remove the last sentence"): a delete, skip or formatting command route stands, unflagged."""
    if stack and stack.get("action") == INSTRUCTION and bundle_route not in WRITING_ROUTES:
        return {**stack, "action": "dictate"}
    return stack


def instruction_on() -> bool:
    return os.environ.get("RR_STACK_INSTRUCTION_FLAG", "").strip().lower() in ("1", "true", "on")


def command_question(instruction: bool = False) -> dict[str, Any]:
    if not instruction:
        return COMMAND_QUESTION
    return {**COMMAND_QUESTION, "criteria": {**COMMAND_QUESTION["criteria"], INSTRUCTION: INSTRUCTION_CRITERION}}


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


def command_questions(regions: list[str], chips: list[str], instruction: bool = False) -> dict[str, dict[str, Any]]:
    qs: dict[str, dict[str, Any]] = {"command": command_question(instruction)}
    if regions:
        qs["target_region"] = region_question(regions)
    if chips:
        qs["target_chip"] = chip_question(chips)
    return qs


def command_state(scratchpad: str, utterance: str, chips: list[str]) -> str:
    sug = "\n".join(f"- {c}" for c in chips) or "(none)"
    return f"SCRATCHPAD:\n{scratchpad}\n\nSUGGESTIONS:\n{sug}\n\nLATEST UTTERANCE:\n{utterance}"


def option_p(a: dict, option: str) -> float:
    """P(option) of a choice answer: its probability when Jev sends them, else the confidence of that choice, else 0."""
    probs = a.get("probabilities")
    if isinstance(probs, dict) and option in probs:
        return float(probs.get(option) or 0.0)
    return float(a.get("confidence") or 0.0) if a.get("choice") == option else 0.0


def parse_command(answers: dict, chips: list[str], instruction: bool = False) -> dict:
    a = answers.get("command") or {}
    out = {"command": a.get("choice"), "confidence": float(a.get("confidence") or 0.0), "region": None, "chip": None}
    if instruction:
        out[INSTRUCTION] = option_p(a, INSTRUCTION)
        out["p_delete"] = option_p(a, "delete")
    r = answers.get("target_region")
    if r and r.get("choice") not in (None, NONE):
        out["region"] = r["choice"]
    c = answers.get("target_chip")
    if c and isinstance(c.get("choice"), str) and c["choice"].startswith("chip_"):
        i = int(c["choice"].split("_")[1])
        out["chip"] = chips[i] if i < len(chips) else None
    return out


async def ask_command(scratchpad: str, utterance: str, regions: list[str], chips: list[str],
                      transport=None, instruction: bool | None = None) -> dict:
    """`instruction`: ask the instruction option too (default: RR_STACK_INSTRUCTION_FLAG); the parsed answer then
    carries its score under "instruction"."""
    ins = instruction_on() if instruction is None else instruction
    r = await jev_post({"model": JEV_MODEL, "state": command_state(scratchpad, utterance, chips),
                        "questions": command_questions(regions, chips, ins)},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    return parse_command(r.json().get("answers") or {}, chips, ins)


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


def held_score(parsed: dict) -> float:
    """P(an instruction the scratchpad will not carry out): P(instruction) + P(delete). The scratchpad acts on a
    delete only when it names a region; any other removal ("delete all the other sections") would otherwise be
    written as dictation (P3). Lab 2026-10-15: those removals split between delete and instruction."""
    return float(parsed.get(INSTRUCTION) or 0.0) + float(parsed.get("p_delete") or 0.0)


def decide_command(parsed: dict, instruction_min: float | None = None) -> dict:
    """The action of a final (spec v2 §7.3, lab §10.1). Accept: Jev reads an accept command and names a visible
    chip (a correction naming a chip is dictation: its words must never be replaced). Delete: at COMMAND_DELETE_MIN, with the named region if any. Instruction
    (only when the flag asked it): `held_score` at INSTRUCTION_MIN, held for the radiologist; the route still
    lets the bundle's own delete, skip or command win (`settle_instruction`). Everything else,
    correct included, is dictation (today's write path already handles corrections)."""
    cmd, conf = parsed.get("command"), float(parsed.get("confidence") or 0.0)
    if parsed.get("chip") and cmd == "accept_suggestion":
        return {"action": "accept", "region": None, "chip": parsed["chip"]}
    asked = INSTRUCTION in parsed   # the instruction flag asked the option
    delete = cmd == "delete" and conf >= COMMAND_DELETE_MIN
    if delete and (parsed.get("region") or not asked):
        return {"action": "delete", "region": parsed.get("region"), "chip": None}
    if asked and held_score(parsed) >= (INSTRUCTION_MIN if instruction_min is None else instruction_min):
        return {"action": INSTRUCTION, "region": None, "chip": None}
    if delete:   # no region: the bundle's own route decides (the last thing said)
        return {"action": "delete", "region": None, "chip": None}
    return {"action": "dictate", "region": None, "chip": None}


# ── Checklist rows (checklist spec §5, wording lab §10.2) ─────────────────────
REMOVED_MIN = 0.6  # lab 2026-10-11 (40 pairs): 17/20 rewordings caught, 0/20 false


@dataclass(frozen=True)
class RowCheck:
    stated: float
    contra: float
    removed: float
    hedge: float = 0.0   # P(the region's own dictation hedges or limits its assessment); 0 when not asked


def removed_key(i: int) -> str:
    return f"removed_{i}"


HEDGE_KEY = "hedge"


def hedge_question(region: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": (
        "The DICTATION expresses doubt, uncertainty or a limitation of assessment about this structure or region, or "
        "a structure within it: a qualified or tentative statement (a qualifier such as probably, likely, possibly, "
        "grossly, appears or no obvious), a finding that may not be real, or a structure "
        "not seen, partly seen or not fully assessed. A plain or collective statement that it is normal, or a "
        f"definite finding, is not doubt. REGION: {region}")}


def removed_question(sentence: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": (
        "The STATEMENT says the same thing as one of the REMOVED statements: the same check on the same structure, "
        f"in any wording. STATEMENT: {sentence}")}


async def ask_rows(dictation: str, sentences: list[str], removed: list[str], transport=None, *,
                   stated: bool = True, contra: bool = True, hedge: str | None = None) -> list[RowCheck]:
    """Stated, contradicted and (when the radiologist removed anything) the same as a removed sentence, per
    sentence, in one Jev call. `stated=False` / `contra=False` leave that question out (its score is 0): the
    assumed normals ask coverage on a region's own text and contradiction on the whole dictation (Task A3b).
    `hedge` (a region name): the same call also asks, once, whether the dictation hedges that region; every
    returned check carries the answer (0 when not asked)."""
    if not sentences:
        return []
    qs: dict[str, dict[str, Any]] = {}
    if hedge is not None:
        qs[HEDGE_KEY] = hedge_question(hedge)
    for i, s in enumerate(sentences):
        if stated:
            qs[f"stated_{i}"] = stated_question(s)
        if contra:
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
    score = lambda k: float((ans.get(k) or {}).get("noul") or 0.0) if k in qs else 0.0   # an unasked part: 0
    h = score(HEDGE_KEY)
    return [RowCheck(score(f"stated_{i}"), score(contra_key(i)), score(removed_key(i)), h) for i in range(len(sentences))]


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


HEDGE_MIN = 0.5  # lab 2026-10-13 (30 region texts, 2 runs): hedges 11/12 >= 0.82, plain normals <= 0.06, findings <= 0.22


def normal_fate(c: RowCheck) -> str:
    """A region normal: 'removed', 'covered' (the dictation states it), 'contradicted', 'flagged' (its region's
    dictation hedges or limits the assessment, or the dictation may contradict it: kept, highlighted for the
    radiologist to confirm or remove) or 'assumed'. Only the bars drop a normal; Jev being unsure never does
    (review R1). A half-band stated score no longer flags on its own: it cannot tell a paraphrase of a dictated
    normal from a hedge (live 2026-10-13: "Liver normal." stated 0.52), so the region's hedge question does."""
    if c.removed >= REMOVED_MIN:
        return "removed"
    if c.stated >= STATED_MIN:
        return "covered"
    if c.contra >= CONTRA_MIN:
        return "contradicted"
    return "flagged" if c.hedge >= HEDGE_MIN or c.contra >= OPTIONAL_MIN else "assumed"


# ── Paired normals: which side is the finding on? (side brief 2026-10-14, hybrid_stack.sides) ─────────────────────
# Asked for every pair in a region the dictation touches, NOT gated on contradiction: side lab run 1 (34 cases) showed
# Jev, rightly, does not read a side-less finding as contradicting a sided negative for certain: it dropped one side
# (8 cases) or neither (4: a side-less "Small pneumothorax." kept both sides' negatives). A choice (bilateral fix,
# 2026-10-14): "both" lets code drop the side contradiction missed ("Both kidneys contain cysts" dropped one side).
SIDE_CHOICES = ("none", "right", "left", "both", "no_side")
# Re-review N7: P(no_side) must reach this to ask (the round-1 bar, restored); below it both normals are flagged amber.
# Side lab runs 3-4: every no_side answer >= 0.66 except a neighbour over-ask (a10 ureter, 0.57), which this removes.
SIDE_MIN = 0.6
SIDE_QUESTION = {
    "instructions": ("Does the DICTATION report an abnormal finding for the paired check these two STATEMENTS make (one "
                     "statement for the right side, one for the left), and on which side? Only a finding for this check "
                     "counts: a finding on a neighbouring structure, or the side given for a different finding, does "
                     "not. STATEMENTS: {right} / {left}"),
    "criteria": {
        "none": ("No finding for this check: the dictation reports no abnormal finding for it (it is not mentioned, it "
                 "is only said to be normal or absent, or the findings concern other structures or checks)."),
        "right": ("Right side: the finding for this check is said to be on the right, in its own sentence or an earlier "
                  "sentence about the same finding, or at a location that exists on the right only."),
        "left": ("Left side: the finding for this check is said to be on the left, in its own sentence or an earlier "
                 "sentence about the same finding, or at a location that exists on the left only."),
        "both": "Both sides: the finding for this check is said to be bilateral or on both sides, or is given for each side.",
        "no_side": "Side not given: a finding for this check is reported but no side is given for it anywhere in the dictation.",
    },
}


SIDE_BATCH = 15   # pairs per Jev call (as normals.BATCH); batches run in parallel, so a sheet's 20 pairs never time out


async def ask_sides(dictation: str, pairs: list[tuple[str, str]], transport=None) -> list[tuple[str, dict[str, float]]]:
    """(choice, its probabilities) per (right, left) pair: none | right | left | both | no_side. SIDE_BATCH pairs per
    call, calls in parallel (one round trip); any failed call fails the whole answer."""
    if not pairs:
        return []
    key = os.environ.get("OPENROUTER_API_KEY", "")

    async def batch(start: int, chunk: list[tuple[str, str]]) -> list[tuple[str, dict[str, float]]]:
        qs = {f"side_{start + i}": {"type": "choice", "instructions": SIDE_QUESTION["instructions"].format(right=r, left=l),
                                    "criteria": SIDE_QUESTION["criteria"]} for i, (r, l) in enumerate(chunk)}
        r = await jev_post({"model": JEV_MODEL, "state": f"DICTATION:\n{dictation}", "questions": qs}, key, TIMEOUT_S,
                           transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out: list[tuple[str, dict[str, float]]] = []
        for i in range(len(chunk)):
            # a missing or unknown answer fails the question (side_failed), never read as an answer
            a = ans.get(f"side_{start + i}") or {}
            if a.get("choice") not in SIDE_CHOICES:
                raise ValueError("jev: incomplete answers")
            probs = a.get("probabilities") if isinstance(a.get("probabilities"), dict) else {}
            out.append((a["choice"], {k: round(float(probs.get(k) or 0.0), 3) for k in SIDE_CHOICES}))
        return out

    parts = await asyncio.gather(*(batch(k, pairs[k:k + SIDE_BATCH]) for k in range(0, len(pairs), SIDE_BATCH)))
    return [x for p in parts for x in p]


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


# ── Assumed normals: context rules (conversion lab 2026-10-12) ─────────────────────────
CONDITION_MIN = 0.5   # = template_brief.MET: one cut-off for every rule condition; silence is not met


async def ask_conditions(state: str, conditions: list[str], transport=None) -> list[float]:
    """Is each context condition stated for this case (history or dictation)? One Jev call; the question is
    template_brief.q_condition (Jev wording suite 2026-10-01), so a rule fires here exactly as it does at Generate."""
    if not conditions:
        return []
    from ..template_brief import q_condition
    qs = {f"cond_{i}": q_condition(c) for i, c in enumerate(conditions)}
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return [float((ans.get(f"cond_{i}") or {}).get("noul") or 0.0) for i in range(len(conditions))]


# ── Required values: the value cluster (requirements spec 2026-10-12 part 1) ──────────
# Per LIST_MISSING item, "stated?" (noul, value_<i>) and "which clause gives its value?" (choice over the dictation's
# clauses that hold a number, where_<i>). Code reads the number (hybrid_stack.values); Jev never does.
VALUE_UNQUOTED_MIN = STATED_MIN   # 0.8: an item no number maps to, stated -> the "stated?" chip, on the strict bar
NUMBER_BATCH = 10                 # numbers per number -> item call; batches run in parallel
VALUE_BATCH = 4                 # items per Jev call; batches run in parallel (12 items -> 3 calls)


def value_key(i: int) -> str:
    return f"value_{i}"


def where_key(i: int) -> str:
    return f"where_{i}"


def value_stated_question(item: str) -> dict[str, Any]:
    """Does the dictation state this required value? The brief's LIST_MISSING question (template_brief.q_stated)."""
    from ..template_brief import q_stated
    return q_stated(item)


def value_where_question(item: str, clauses: list[str]) -> dict[str, Any]:
    crit: dict[str, str] = {f"s_{k}": c for k, c in enumerate(clauses)}
    crit[NONE] = "No SENTENCE gives this item's value."
    return {"type": "choice", "instructions": f"Which SENTENCE of the DICTATION gives the value of this item: {item}",
            "criteria": crit}


async def ask_values(dictation: str, items: list[str], clauses: list[str], transport=None,
                     stated: Callable[[str], dict[str, Any]] = value_stated_question
                     ) -> list[tuple[float, Optional[int], Optional[list[float]]]]:
    """(P stated, index into `clauses` of the clause that gives its value or None, the where-choice's probability per
    clause or None when Jev sent none) per item, in order. Items go in parallel calls of VALUE_BATCH (one call when
    there are no clauses); keys keep the item's global index. The clause question is asked only when there are clauses. `stated`: the wording (the lab
    passes its arms)."""
    if not items:
        return []
    key = os.environ.get("OPENROUTER_API_KEY", "")

    async def batch(start: int, chunk: list[str]) -> list[tuple[float, Optional[int], Optional[list[float]]]]:
        qs: dict[str, dict[str, Any]] = {}
        for j, item in enumerate(chunk):
            qs[value_key(start + j)] = stated(item)
            if clauses:
                qs[where_key(start + j)] = value_where_question(item, clauses)
        r = await jev_post({"model": JEV_MODEL, "state": f"DICTATION:\n{dictation}", "questions": qs},
                           key, TIMEOUT_S * 2, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out: list[tuple[float, Optional[int], Optional[list[float]]]] = []
        for j in range(len(chunk)):
            p = float((ans.get(value_key(start + j)) or {}).get("noul") or 0.0)
            w = ans.get(where_key(start + j)) or {}
            c = w.get("choice")
            k = int(c[2:]) if isinstance(c, str) and c.startswith("s_") and c[2:].isdigit() else None
            probs = w.get("probabilities")
            scores = [float(probs.get(f"s_{i}") or 0.0) for i in range(len(clauses))] if isinstance(probs, dict) else None
            out.append((p, k if k is not None and k < len(clauses) else None, scores))
        return out

    # Without clauses the questions are small: one call (no parallel batches whose slowest would set the fill's time)
    size = VALUE_BATCH if clauses else max(len(items), 1)
    parts = await asyncio.gather(*(batch(k, items[k:k + size]) for k in range(0, len(items), size)))
    return [x for p in parts for x in p]


def number_item_question(number: str, marked: str, items: list[str]) -> dict[str, Any]:
    """Number -> item (Decision 11, the second lab's arm N1, wording verbatim): which required value does this number
    give? `marked` is its sentence with the number marked [[ ]]."""
    crit: dict[str, str] = {f"item_{i}": it for i, it in enumerate(items)}
    crit[NONE] = "None of these required values: the number gives something else."
    return {"type": "choice",
            "instructions": (f"Which required value does the number {number} in this sentence give? The number is "
                             f"marked [[ ]] in the SENTENCE. SENTENCE: {marked}"),
            "criteria": crit}


async def ask_number_items(dictation: str, mentions: list[tuple[str, str]], items: list[str],
                           transport=None) -> list[tuple[Optional[int], float, Optional[list[float]]]]:
    """(index into `items` the number gives, or None; Jev's confidence; P(each item) or None when Jev sent no
    probabilities) per (number, marked sentence), in order. One choice per number, NUMBER_BATCH per call, calls in
    parallel."""
    if not mentions:
        return []
    if not items:
        return [(None, 0.0, None)] * len(mentions)
    key = os.environ.get("OPENROUTER_API_KEY", "")

    async def batch(start: int, chunk: list[tuple[str, str]]) -> list[tuple[Optional[int], float, Optional[list[float]]]]:
        qs = {f"n_{start + j}": number_item_question(n, m, items) for j, (n, m) in enumerate(chunk)}
        r = await jev_post({"model": JEV_MODEL, "state": f"DICTATION:\n{dictation}", "questions": qs},
                           key, TIMEOUT_S * 2, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out: list[tuple[Optional[int], float, Optional[list[float]]]] = []
        for j in range(len(chunk)):
            a = ans.get(f"n_{start + j}") or {}
            c = a.get("choice")
            i = int(c[5:]) if isinstance(c, str) and c.startswith("item_") and c[5:].isdigit() else None
            probs = a.get("probabilities")
            p_items = [float(probs.get(f"item_{x}") or 0.0) for x in range(len(items))] if isinstance(probs, dict) else None
            out.append((i if i is not None and i < len(items) else None, float(a.get("confidence") or 0.0), p_items))
        return out

    parts = await asyncio.gather(*(batch(k, mentions[k:k + NUMBER_BATCH])
                                   for k in range(0, len(mentions), NUMBER_BATCH)))
    return [x for p in parts for x in p]


# Post-generation backstop (value cluster): does the generated REPORT state each value whose chip was filled? A "no"
# is listed as not provided and flagged by code (template_required_values.backstop). Recall-oriented.
BACKSTOP_MIN = 0.5   # provisional; the value cluster lab reports backstop recall on planted missing values


async def ask_report_values(report: str, items: list[str], transport=None,
                            stated: Callable[[str], dict[str, Any]] = value_stated_question) -> list[float]:
    """P(the report states the item) per item, in order; parallel calls of VALUE_BATCH."""
    if not items:
        return []
    key = os.environ.get("OPENROUTER_API_KEY", "")

    async def batch(start: int, chunk: list[str]) -> list[float]:
        qs = {value_key(start + j): stated(item) for j, item in enumerate(chunk)}
        r = await jev_post({"model": JEV_MODEL, "state": f"REPORT:\n{report}", "questions": qs},
                           key, TIMEOUT_S * 2, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out: list[float] = []
        for j in range(len(chunk)):
            # a missing or malformed answer is never "not stated": that would list a value the report gives
            p = (ans.get(value_key(start + j)) or {}).get("noul")
            if isinstance(p, bool) or not isinstance(p, (int, float)):
                raise ValueError("jev: incomplete answers")
            out.append(float(p))
        return out

    parts = await asyncio.gather(*(batch(k, items[k:k + VALUE_BATCH]) for k in range(0, len(items), VALUE_BATCH)))
    return [x for p in parts for x in p]
