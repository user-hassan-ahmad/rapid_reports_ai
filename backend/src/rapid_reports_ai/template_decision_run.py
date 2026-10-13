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
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator

from pydantic_ai import PromptedOutput

from . import template_decisions as td

logger = logging.getLogger(__name__)

RUN_VERSION = "decision-run-2026-10-13"
QWEN_TIMEOUT_S = 40.0     # the lab (2026-10-13): 19/132 calls timed out at 25 s
FALLBACK_TIMEOUT_S = 25.0
RUN_TIMEOUT_S = 60.0      # the whole Qwen step, fallback included: the radiologist never waits longer
JEV_TIMEOUT_S = 6.0
MIN_QUOTE_WORDS = 2  # a verified quote has at least this many words, or MIN_QUOTE_CHARS characters, so a short
MIN_QUOTE_CHARS = 6  # fragment ("55%") cannot verify by chance
STATES_MIN = 0.5   # lab-set (scripts/rules_step_lab.py decide): one cut-off for every concept question
# max_tokens: gpt-oss (the fallback) reasons into the same cap. At 6000 its tool-call JSON was cut off on the larger
# sets, the ones Qwen timed out on, and each re-ask was cut off the same way ("Exceeded maximum output retries",
# 16 of 19 fallbacks in the lab). Qwen on Cerebras is already raised to this floor by normalise_model_settings.
SETTINGS = {"temperature": 0.2, "max_tokens": 16384, "reasoning_effort": "low"}

ConceptName = Literal["comparison", "contrast", "sequences", "limitation"]


class Quote(BaseModel):
    report: int   # 1-based example number
    text: str     # copied word for word from that example


# gpt-oss (the fallback) writes quotes as flat strings (lab diagnostics, 2026-10-13): "Report 1: text",
# "text (Report 2)", "[3] text". Each is read as {report, text}; a string with no report number is dropped, never
# guessed.
_QUOTE_FORMS = (
    re.compile(r"^\s*\[?\s*report\s*(?P<n>\d+)\s*\]?\s*[:\-\u2013\u2014]\s*(?P<t>.+?)\s*$", re.I | re.S),
    re.compile(r"^\s*(?P<t>.+?)\s*[\(\[]\s*report\s*(?P<n>\d+)\s*[\)\]]\s*$", re.I | re.S),
    re.compile(r"^\s*\[\s*(?P<n>\d+)\s*\]\s*(?P<t>.+?)\s*$", re.S),
)


def _parse_quote(s: str) -> Optional[dict]:
    for form in _QUOTE_FORMS:
        m = form.match(s)
        if m and m.group("t").strip():
            return {"report": int(m.group("n")), "text": m.group("t").strip()}
    return None


def _read_quotes(v):
    if not isinstance(v, list):
        return v
    out = []
    for q in v:
        if isinstance(q, str):
            q = _parse_quote(q)
            if q is None:
                continue
        out.append(q)
    return out


class ValueCandidate(BaseModel):
    name: str
    quotes: List[Quote] = []

    _quotes = field_validator("quotes", mode="before")(staticmethod(_read_quotes))


class ConceptWording(BaseModel):
    concept: ConceptName
    state: str    # what the wording says (one of the concept's states in template_decisions.CONCEPTS)
    text: str     # the wording as a template line, {slots} for what varies
    quotes: List[Quote] = []

    _quotes = field_validator("quotes", mode="before")(staticmethod(_read_quotes))


class HabitCandidate(BaseModel):
    finding: str
    habit: str
    reports: List[int] = []


class SetupMention(BaseModel):
    concept: ConceptName
    state: str    # the state the setup states (one of the concept's states), or "" when it only mentions it
    quote: str    # copied word for word from the STUDY SETUP


class RunOutput(BaseModel):
    values: List[ValueCandidate] = []
    concepts: List[ConceptWording] = []
    habits: List[HabitCandidate] = []
    setup: List[SetupMention] = []


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

4. SETUP: when a STUDY SETUP is given (the study name, scan type and protocol the radiologist entered), it is authoritative context about every report: it may state a concept's state outright (for example whether a contrast agent is given, which acquisitions are planned, whether comparison is expected) and may support a value. For each concept the STUDY SETUP states, give its state (as in CONCEPTS; empty when it only mentions the concept) and a quote copied word for word from the STUDY SETUP. Never use the STUDY SETUP as a report quote, and never invent a setup quote.

One sentence counts for one concept only: never give the same sentence as the quote or wording of two concepts. Quote the shortest span that states the concept or the value, never a whole paragraph.

Copy quotes exactly; never paraphrase or invent one. If nothing fits a list, return it empty."""


SETUP_NAME_MAX = 200
SETUP_SCAN_MAX = 200
SETUP_PROTOCOL_MAX = 2000


@dataclass
class StudySetup:
    """What the radiologist entered when setting the template up: the study name, scan type and protocol notes (or
    a saved template's description). It often states contrast, the protocol or comparison outright, so the decision
    run reads it first (Hassan, 2026-10-13)."""
    name: str = ""
    scan_type: str = ""
    protocol: str = ""

    @property
    def text(self) -> str:
        rows = [("Study name", self.name), ("Scan type", self.scan_type), ("Protocol", self.protocol)]
        return "\n".join(f"{k}: {v}" for k, v in rows if v)


def study_setup(name: Optional[str], scan_type: Optional[str], protocol: Optional[str]) -> StudySetup:
    """The setup fields, stripped and truncated to their caps (never refused: it is context, not input)."""
    def clip(s, cap):
        return (s or "").strip()[:cap].strip()
    return StudySetup(clip(name, SETUP_NAME_MAX), clip(scan_type, SETUP_SCAN_MAX), clip(protocol, SETUP_PROTOCOL_MAX))


def user_prompt(examples: List[str], scan_type: str, setup_text: str = "") -> str:
    parts = ([f"STUDY SETUP (authoritative context from the radiologist, true of every report):\n{setup_text}"]
             if setup_text else [f"SCAN TYPE: {scan_type}"])
    for i, ex in enumerate(examples, 1):
        parts.append(f"### Report {i}\n{ex.strip()}")
    return "\n\n".join(parts)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def verified(q: Quote, examples: List[str]) -> bool:
    """The quote appears in the example it cites (case and spacing ignored) and is long enough to mean something:
    at least MIN_QUOTE_WORDS words or MIN_QUOTE_CHARS characters."""
    text = _norm(q.text)
    if not 1 <= q.report <= len(examples) or not text:
        return False
    if len(text.split()) < MIN_QUOTE_WORDS and len(text) < MIN_QUOTE_CHARS:
        return False
    return text in _norm(examples[q.report - 1])


_SLOT = re.compile(r"\{[^{}]*\}")


def _wording_matches(text: str, quotes: List[Quote], examples: List[str]) -> bool:
    """The wording, with each {slot} as a wildcard, appears in one of the examples its quotes cite. Wording with no
    literal words (slots only) never matches: as a pattern it would match anything."""
    parts = _SLOT.split(_norm(text))
    if not any(re.search(r"\w", x) for x in parts):
        return False
    pattern = re.compile(".+?".join(re.escape(x) for x in parts))
    return any(pattern.search(_norm(examples[q.report - 1])) for q in quotes)


@dataclass
class DecisionRun:
    ok: bool
    values: List[ValueCandidate] = field(default_factory=list)
    concepts: List[ConceptWording] = field(default_factory=list)
    habits: List[HabitCandidate] = field(default_factory=list)
    states: Optional[Dict[str, List[int]]] = None   # concept -> example numbers Jev says state it; None: Jev failed
    setup: Dict[str, dict] = field(default_factory=dict)  # concept the study setup states -> {"state", "quote"}
    dropped_quotes: int = 0
    ms: int = 0
    error: str = ""


def check_quotes(out: RunOutput, examples: List[str]) -> DecisionRun:
    """Keep only verified quotes; drop a candidate left with none, a value name code could not store, and a habit
    seen in fewer than two examples. Value candidates with one name (td._name) are merged, so no two cards share an
    id. A concept wording that matches none of its quotes' examples (slots as wildcards) is replaced by its first
    verified quote, so an invented wording never reaches a card."""
    dropped = 0
    values: List[ValueCandidate] = []
    by_name: Dict[str, ValueCandidate] = {}
    concepts = []
    for v in out.values:
        ok = [q for q in v.quotes if verified(q, examples)]
        dropped += len(v.quotes) - len(ok)
        name = " ".join(v.name.split())
        if not (ok and name and len(name.split()) <= td.MAX_VALUE_WORDS and not any(c in name for c in '"|[]{}')):
            continue
        same = by_name.get(td._name(name))
        if same is None:
            by_name[td._name(name)] = same = ValueCandidate(name=name, quotes=[])
            values.append(same)
        have = {(q.report, _norm(q.text)) for q in same.quotes}
        for q in ok:
            if (q.report, _norm(q.text)) not in have:
                have.add((q.report, _norm(q.text)))
                same.quotes.append(q)
    for c in out.concepts:
        ok = [q for q in c.quotes if verified(q, examples)]
        dropped += len(c.quotes) - len(ok)
        if not (ok and c.text.strip() and c.state in td.CONCEPTS[c.concept].states):
            continue
        text = " ".join(c.text.split())
        if not _wording_matches(text, ok, examples):
            text = " ".join(ok[0].text.split())
            if "{" in text or "}" in text:     # a quote's braces would read as slots
                continue
        if '"' not in text:
            concepts.append(ConceptWording(concept=c.concept, state=c.state, text=text, quotes=ok))
    habits = [h for h in out.habits if len({r for r in h.reports if 1 <= r <= len(examples)}) >= 2]
    return DecisionRun(ok=True, values=values, concepts=concepts, habits=habits, dropped_quotes=dropped)


async def _qwen(examples: List[str], scan_type: str, setup_text: str = "") -> RunOutput:
    """The decision call on the analyser's model (Qwen); one retry on gpt-oss (another provider) if it fails."""
    from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model

    prompt = user_prompt(examples, scan_type, setup_text)

    deadline = time.monotonic() + RUN_TIMEOUT_S

    async def call(model: str, timeout: float, output_type=RunOutput) -> RunOutput:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=model, output_type=output_type, system_prompt=SYSTEM, user_prompt=prompt, api_key="",
            model_settings=dict(SETTINGS)), timeout)
        return r.output

    try:
        return await call(MODEL_CONFIG["SKILL_SHEET_ANALYZER"], QWEN_TIMEOUT_S)
    except Exception as e:
        logger.warning("[decision-run] qwen %s: %s; fallback %s", type(e).__name__, str(e)[:200],
                       MODEL_CONFIG["STACK_REVIEW_FALLBACK"])
        left = deadline - time.monotonic()
        if left <= 1:
            raise
        # gpt-oss gets prompted output (the JSON in its text, as Sonnet does in enhancement_utils._output_type_for):
        # with tool output it re-asked by calling a tool named "json", not final_result, until retries ran out
        # (lab diagnostics, 2026-10-13). Qwen keeps tool output, which it produces reliably.
        return await call(MODEL_CONFIG["STACK_REVIEW_FALLBACK"], min(FALLBACK_TIMEOUT_S, left),
                          PromptedOutput(RunOutput))


async def ask_states(examples: List[str], transport=None) -> Dict[str, List[int]]:
    """concept -> example numbers whose report states it (Jev noul >= STATES_MIN). One Jev call per example (the four
    questions together), in parallel. Raises on any Jev failure."""
    from .jev_client import JEV_MODEL, jev_post

    names = list(td.CONCEPTS)

    async def one(text: str) -> List[float]:
        qs = {f"c{i}": {"type": "noul", "instructions": td.CONCEPTS[n].question} for i, n in enumerate(names)}
        r = await jev_post({"model": JEV_MODEL, "state": f"REPORT:\n{text}", "questions": qs},
                           os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out = []
        for i in range(len(names)):
            v = (ans.get(f"c{i}") or {}).get("noul")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError("jev: incomplete answers")
            out.append(float(v))
        return out

    scores = await asyncio.gather(*(one(t) for t in examples))
    return {n: [k + 1 for k, s in enumerate(scores) if s[i] >= STATES_MIN] for i, n in enumerate(names)}


def _setup_question(text: str) -> str:
    return text.replace("The REPORT", "The STUDY SETUP").replace("this report", "this study setup")


def _condition_statement(condition: str) -> str:
    return "The STUDY SETUP" + condition[len("the dictation"):] + "." if condition.startswith("the dictation") \
        else condition


async def ask_setup(text: str, transport=None) -> Dict[str, Optional[str]]:
    """concept -> state for each concept the STUDY SETUP states (Jev noul >= STATES_MIN). The four concept questions
    (worded for the setup) and, for contrast, its two conditions as statements: one met and the other not sets the
    state; otherwise the state is None (stated, no state). Raises on any Jev failure."""
    from .jev_client import JEV_MODEL, jev_post

    names = list(td.CONCEPTS)
    qs = {f"c{i}": {"type": "noul", "instructions": _setup_question(td.CONCEPTS[n].question)}
          for i, n in enumerate(names)}
    sides = td.CONCEPTS["contrast"].states
    for state, cond in sides.items():
        qs[state] = {"type": "noul", "instructions": _condition_statement(cond)}
    r = await jev_post({"model": JEV_MODEL, "state": f"STUDY SETUP:\n{text}", "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    score = {}
    for k in qs:
        v = (ans.get(k) or {}).get("noul")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("jev: incomplete answers")
        score[k] = float(v)
    out: Dict[str, Optional[str]] = {}
    for i, n in enumerate(names):
        met = [s for s in sides if score[s] >= STATES_MIN] if n == "contrast" else []
        if score[f"c{i}"] >= STATES_MIN or met:
            out[n] = met[0] if len(met) == 1 else None
    return out


def _setup_evidence(states: Dict[str, Optional[str]], mentions: List[SetupMention], text: str) -> Dict[str, dict]:
    """Jev decides what the setup states; Qwen's quote is kept only when it is in the setup text (code checks it),
    and for a stated state only when it quotes that state."""
    out = {}
    for name, state in states.items():
        quote = next((" ".join(m.quote.split()) for m in mentions
                      if m.concept == name and (state is None or m.state == state)
                      and m.quote.strip() and _norm(m.quote) in _norm(text)), None)
        out[name] = {"state": state, "quote": quote}
    return out


async def run_decisions(examples: List[str], scan_type: str, setup: Optional[StudySetup] = None) -> DecisionRun:
    """The decision run for these examples (and the study setup, read first when given). Never raises. With no
    setup, or an empty one, the run is as before the setup was added."""
    t0 = time.monotonic()
    setup_text = setup.text if setup else ""

    async def no_setup():
        return {}
    qwen, jev, from_setup = await asyncio.gather(
        asyncio.wait_for(_qwen(examples, scan_type, setup_text), RUN_TIMEOUT_S), ask_states(examples),
        ask_setup(setup_text) if setup_text else no_setup(), return_exceptions=True)
    ms = int((time.monotonic() - t0) * 1000)
    if isinstance(qwen, BaseException):
        logger.warning("[decision-run] failed: %s: %s", type(qwen).__name__, str(qwen)[:200])
        return DecisionRun(ok=False, ms=ms, error=type(qwen).__name__)
    run = check_quotes(qwen, examples)
    run.ms = ms
    if isinstance(jev, BaseException):
        logger.warning("[decision-run] jev failed: %s", type(jev).__name__)
    else:
        run.states = jev
    if isinstance(from_setup, BaseException):   # fail-soft: a silent setup
        logger.warning("[decision-run] jev setup failed: %s", type(from_setup).__name__)
    elif from_setup:
        run.setup = _setup_evidence(from_setup, qwen.setup, setup_text)
    logger.info("[decision-run] values=%d concepts=%d habits=%d dropped_quotes=%d jev=%s ms=%d", len(run.values),
                len(run.concepts), len(run.habits), run.dropped_quotes, run.states is not None, ms)
    return run


def evidence(run: DecisionRun, built: Optional[dict] = None) -> dict:
    """The record stored with the template (template_config["rules_step"]): counts, timings, hidden habit candidates
    for the findings-triggered rows lab. No example text."""
    out = {"version": RUN_VERSION, "ok": run.ok, "ms": run.ms, "error": run.error, "values": len(run.values),
           "concepts": len(run.concepts), "dropped_quotes": run.dropped_quotes, "jev": run.states is not None,
           "habits": [h.model_dump() for h in run.habits], "setup": sorted(run.setup)}
    if built:
        out.update(cards=len(built["cards"]), more=len(built["more"]), kept=len(built["kept"]))
    return out


def stamp_review(db, template_id, record: dict) -> bool:
    """Mark a saved template's first-use review as run (template_config["rules_step"]), so the paid run is not
    repeated on the next open, even when the panel is closed without saving. Never overwrites a record; never
    raises (the review is evidence, not a reason to fail)."""
    import uuid
    from sqlalchemy.orm.attributes import flag_modified
    from .database.models import Template
    try:
        tpl = (db.query(Template).filter(Template.id == uuid.UUID(str(template_id))).with_for_update().first())
        if tpl is None or (tpl.template_config or {}).get("rules_step"):
            db.rollback()
            return False
        tpl.template_config = {**(tpl.template_config or {}), "rules_step": {**record, "first_use": True}}
        flag_modified(tpl, "template_config")
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning("[decision-run] review not stamped for %s: %s", template_id, type(e).__name__)
        return False
