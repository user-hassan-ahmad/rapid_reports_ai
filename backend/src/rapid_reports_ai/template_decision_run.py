"""The decision run (Rules-step spec, "New flow" step 2): from the pasted example reports alone, list what needs the
radiologist before the sheet is written. One Qwen call (low temperature, structured output, one job) proposes
candidate required values and the wording of the standard study-level concepts (each wording with the state it states,
never which one is usual: code counts that), each with quotes from the examples;
in parallel Jev answers, per example and per concept, whether the report states it. Code checks every quote against
the example it cites (a candidate left with no verified quote is dropped) and the card builder
(template_rules_cards) turns the result into cards. Jev decides which examples state a concept; Qwen only proposes
wording; code applies.

Fail-soft: a failed or slow Qwen call gives no run (`ok` False, the writer infers rules as today); a failed Jev call
gives `states` None (no study-level cards; value cards still shown)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from . import template_decisions as td

logger = logging.getLogger(__name__)

RUN_VERSION = "decision-run-2026-10-13"
QWEN_TIMEOUT_S = 25.0
FALLBACK_TIMEOUT_S = 25.0
JEV_TIMEOUT_S = 6.0
STATES_MIN = 0.5   # lab-set (scripts/rules_step_lab.py decide): one cut-off for every concept question
SETTINGS = {"temperature": 0.2, "max_tokens": 6000, "reasoning_effort": "low"}

ConceptName = Literal["comparison", "contrast", "sequences", "limitation"]


class Quote(BaseModel):
    report: int   # 1-based example number
    text: str     # copied word for word from that example


class ValueCandidate(BaseModel):
    name: str
    quotes: List[Quote] = []


class ConceptWording(BaseModel):
    concept: ConceptName
    state: str    # what the wording says (one of the concept's states in template_decisions.CONCEPTS)
    text: str     # the wording as a template line, {slots} for what varies
    quotes: List[Quote] = []


class HabitCandidate(BaseModel):
    finding: str
    habit: str
    reports: List[int] = []


class RunOutput(BaseModel):
    values: List[ValueCandidate] = []
    concepts: List[ConceptWording] = []
    habits: List[HabitCandidate] = []


SYSTEM = """You read a radiologist's example reports for one scan type and list the decisions a report template needs from them. You never write the template.

List three things, each grounded in quotes copied word for word from the examples (a quote is a short span of one report, exactly as written there, with the report's number).

1. VALUES: measured or graded values the reports state, each by a short plain name (a few words, no number or unit in the name). One entry per distinct value, with one quote from every report that states it. A value stated in only some reports is still listed. Never list a finding, a diagnosis or a structure that is only described.

2. CONCEPTS: how the reports word four study-level circumstances, when they word them at all, each wording with its state:
- comparison: state "none" (no previous imaging available or compared) or "compared" (a previous study is compared);
- contrast: state "given" (a contrast agent was given) or "not_given" (no contrast agent was given);
- sequences: state "complete" (everything planned was performed) or "not_performed" (a sequence, phase or view was not performed);
- limitation: state "none" (no limitation stated) or "limited" (a technical limitation is stated).
The state says what the wording states, never how often it is used: do not decide which wording is the usual one. Write the wording as a template line: copied from the reports, with the varying parts (dates, study names, the part not performed, the limitation) replaced by a named slot in curly braces such as {date}. Give the quotes it comes from. Different wordings with the same state are separate entries. Leave out a concept that no report words.

3. HABITS: a statement the radiologist adds only when a particular finding is present (the finding, and what they always add), seen in at least two reports. Give the report numbers.

Copy quotes exactly; never paraphrase or invent one. If nothing fits a list, return it empty."""


def user_prompt(examples: List[str], scan_type: str) -> str:
    parts = [f"SCAN TYPE: {scan_type}"]
    for i, ex in enumerate(examples, 1):
        parts.append(f"### Report {i}\n{ex.strip()}")
    return "\n\n".join(parts)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def verified(q: Quote, examples: List[str]) -> bool:
    """The quote appears in the example it cites (case and spacing ignored)."""
    if not 1 <= q.report <= len(examples) or not q.text.strip():
        return False
    return _norm(q.text) in _norm(examples[q.report - 1])


@dataclass
class DecisionRun:
    ok: bool
    values: List[ValueCandidate] = field(default_factory=list)
    concepts: List[ConceptWording] = field(default_factory=list)
    habits: List[HabitCandidate] = field(default_factory=list)
    states: Optional[Dict[str, List[int]]] = None   # concept -> example numbers Jev says state it; None: Jev failed
    dropped_quotes: int = 0
    ms: int = 0
    error: str = ""


def check_quotes(out: RunOutput, examples: List[str]) -> DecisionRun:
    """Keep only verified quotes; drop a candidate left with none, a value name code could not store, and a habit
    seen in fewer than two examples."""
    dropped = 0
    values, concepts = [], []
    for v in out.values:
        ok = [q for q in v.quotes if verified(q, examples)]
        dropped += len(v.quotes) - len(ok)
        name = " ".join(v.name.split())
        if ok and name and len(name.split()) <= td.MAX_VALUE_WORDS and not any(c in name for c in '"|[]{}'):
            values.append(ValueCandidate(name=name, quotes=ok))
    for c in out.concepts:
        ok = [q for q in c.quotes if verified(q, examples)]
        dropped += len(c.quotes) - len(ok)
        if ok and c.text.strip() and '"' not in c.text and c.state in td.CONCEPTS[c.concept].states:
            concepts.append(ConceptWording(concept=c.concept, state=c.state, text=" ".join(c.text.split()), quotes=ok))
    habits = [h for h in out.habits if len({r for r in h.reports if 1 <= r <= len(examples)}) >= 2]
    return DecisionRun(ok=True, values=values, concepts=concepts, habits=habits, dropped_quotes=dropped)
