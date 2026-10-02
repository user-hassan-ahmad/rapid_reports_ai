# backend/src/rapid_reports_ai/scripts/jev_tool_lab/arms.py
"""The five arms (spec §3). Every arm returns an ArmResult and never raises; Qwen and Jev are parameters so the
unit tests run on fakes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from . import calls, prompts
from .catalogue import MAX_QUESTIONS, QuestionSpec, question_source, render, state_for, validate
from .rules import UNSURE, Rule, band, evaluate, validate_rule
from .scenarios import Decision, S1Item, s1_user


class Plan(BaseModel):
    questions: List[QuestionSpec]
    rule: Rule


class FreeQuestion(BaseModel):
    id: str
    type: Literal["noul", "choice"]
    instructions: str
    criteria: Optional[Dict[str, str]] = None


class FreePlan(BaseModel):
    questions: List[FreeQuestion]
    rule: Rule


class ArmResult(BaseModel):
    arm: str
    item_id: str
    run: int
    decision: Optional[Decision] = None
    latency_s: float = 0.0
    qwen_in: int = 0
    qwen_out: int = 0
    jev_calls: int = 0
    plan: Optional[dict] = None
    answers: Optional[dict] = None
    banded: Optional[dict] = None
    invalid: List[str] = []
    lint: List[str] = []
    rule_outcome: Optional[str] = None
    fallback: bool = False
    error: Optional[str] = None


def _err(arm: str, item: S1Item, run: int, e: Exception) -> ArmResult:
    return ArmResult(arm=arm, item_id=item.id, run=run, error=f"{type(e).__name__}: {str(e)[:200]}")


def _add_usage(res: ArmResult, u) -> None:
    res.latency_s += u.latency_s
    res.qwen_in += u.input_tokens
    res.qwen_out += u.output_tokens


@dataclass
class Asked:
    valid: List[QuestionSpec] = field(default_factory=list)
    invalid: List[str] = field(default_factory=list)
    answers: Dict[str, Any] = field(default_factory=dict)
    banded: Dict[str, str] = field(default_factory=dict)
    calls: int = 0
    latency_s: float = 0.0


async def _ask(questions: List[QuestionSpec], item: S1Item, jev_fn) -> Asked:
    case, out = item.case(), Asked()
    for s in questions[:MAX_QUESTIONS]:
        err = validate(s, case)
        if err:
            out.invalid.append(f"{s.id}: {err}")
        else:
            out.valid.append(s)
    out.invalid += [f"{s.id}: over the cap" for s in questions[MAX_QUESTIONS:]]
    by_state: Dict[str, Dict[str, dict]] = {}
    types: Dict[str, str] = {}
    for s in out.valid:
        q = render(s)
        types[s.id] = q["type"]
        by_state.setdefault(state_for(case, question_source(s)), {})[s.id] = q
    if by_state:
        out.answers, out.calls, out.latency_s = await jev_fn(by_state)
    out.banded = {qid: band(out.answers.get(qid), t) for qid, t in types.items()}
    return out


async def arm_a(item: S1Item, *, run: int, reasoning: bool = True, qwen_fn=calls.qwen) -> ArmResult:
    name = "A" if reasoning else "A0"
    try:
        dec, u = await qwen_fn(Decision, prompts.baseline_system(), s1_user(item), reasoning)
        res = ArmResult(arm=name, item_id=item.id, run=run, decision=dec)
        _add_usage(res, u)
        return res
    except Exception as e:
        return _err(name, item, run, e)


async def arm_b(item: S1Item, *, run: int, fallback: ArmResult, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    try:
        plan, u = await qwen_fn(Plan, prompts.author_system(), s1_user(item), False)
        asked = await _ask(plan.questions, item, jev_fn)
        rule_err = validate_rule(plan.rule, plan.questions)       # review fix: a malformed rule is unsure, never "no"
        outcome, failed = (UNSURE, []) if rule_err else evaluate(plan.rule, asked.banded)
        res = ArmResult(arm="B", item_id=item.id, run=run, plan=plan.model_dump(), answers=asked.answers,
                        banded=asked.banded, invalid=asked.invalid + ([f"rule: {rule_err}"] if rule_err else []),
                        rule_outcome=outcome, jev_calls=asked.calls,
                        latency_s=asked.latency_s)
        _add_usage(res, u)
        if outcome == UNSURE:
            res.fallback = True
            res.decision = fallback.decision
            res.latency_s += fallback.latency_s
            res.qwen_in += fallback.qwen_in
            res.qwen_out += fallback.qwen_out
        else:
            res.decision = Decision(gradable=outcome == "yes", missing=failed, reason="rule")
        res.latency_s = round(res.latency_s, 6)
        return res
    except Exception as e:
        return _err("B", item, run, e)


_QUOTE = re.compile(r'"([^"]+)"')
_NEG_WORDS = re.compile(r"\b(no|not|without|absent|negative|nil|none)\b", re.I)
_INFER = re.compile(r"\b(would|expected|likely|should|typical|typically|suggests?)\b", re.I)
_TWO = re.compile(r"\b(and also|or whether|and whether|as well as)\b", re.I)


def lint_free(q: FreeQuestion) -> List[str]:
    """Rule breaks in a free-form question (spec §2.1 forbidden list); D's risk measure."""
    text = q.instructions
    quotes = _QUOTE.findall(text)
    outside = _QUOTE.sub(" ", text)
    codes = []
    if not quotes:
        codes.append("unquoted")
    if any(_NEG_WORDS.search(x) for x in quotes):
        codes.append("embedded_negative")
    if re.search(r"\d", text):
        codes.append("numbers")
    if text.count("?") > 1 or _TWO.search(outside):
        codes.append("two_judgements")
    if _INFER.search(outside):
        codes.append("inference")
    if q.type == "choice" and not q.criteria:
        codes.append("choice_without_options")
    return codes


def _raw(ans: Any) -> str:
    if isinstance(ans, dict) and "probabilities" in ans:
        return ", ".join(f"{k} {float(v):.2f}" for k, v in ans["probabilities"].items())
    if isinstance(ans, dict) and "noul" in ans:
        return f"{float(ans['noul']):.2f}"
    return "no answer"


def _evidence(described: List[tuple], answers: Dict[str, Any], banded: Dict[str, str]) -> str:
    return "\n".join(f"{qid} ({desc}): {banded.get(qid, UNSURE)} [raw: {_raw(answers.get(qid))}]"
                     for qid, desc in described) or "(no valid questions)"


async def _decide(item: S1Item, described: List[tuple], answers, banded, qwen_fn):
    user = f"{s1_user(item)}\n\nCLASSIFIER ANSWERS:\n{_evidence(described, answers, banded)}"
    return await qwen_fn(Decision, prompts.decide_system(), user, True)


async def arm_c(item: S1Item, *, run: int, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    try:
        plan, u1 = await qwen_fn(Plan, prompts.author_system(), s1_user(item), True)
        asked = await _ask(plan.questions, item, jev_fn)
        rule_err = validate_rule(plan.rule, plan.questions)
        outcome = UNSURE if rule_err else evaluate(plan.rule, asked.banded)[0]
        described = [(s.id, render(s)["instructions"]) for s in asked.valid]
        dec, u2 = await _decide(item, described, asked.answers, asked.banded, qwen_fn)
        res = ArmResult(arm="C", item_id=item.id, run=run, decision=dec, plan=plan.model_dump(), answers=asked.answers,
                        banded=asked.banded, invalid=asked.invalid + ([f"rule: {rule_err}"] if rule_err else []),
                        rule_outcome=outcome, jev_calls=asked.calls,
                        latency_s=asked.latency_s)
        _add_usage(res, u1)
        _add_usage(res, u2)
        res.latency_s = round(res.latency_s, 6)
        return res
    except Exception as e:
        return _err("C", item, run, e)


async def arm_d(item: S1Item, *, run: int, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    try:
        plan, u1 = await qwen_fn(FreePlan, prompts.free_author_system(), s1_user(item), True)
        qs = plan.questions[:MAX_QUESTIONS]
        lint = [f"{q.id}: {code}" for q in qs for code in lint_free(q)]
        send = [q for q in qs if not (q.type == "choice" and not q.criteria)]
        jq = {q.id: {"type": q.type, "instructions": q.instructions, **({"criteria": q.criteria} if q.criteria else {})}
              for q in send}
        answers, n, jlat = (await jev_fn({state_for(item.case(), "dictation"): jq})) if jq else ({}, 0, 0.0)
        banded = {q.id: band(answers.get(q.id), q.type) for q in send}
        outcome, _ = evaluate(plan.rule, banded)
        dec, u2 = await _decide(item, [(q.id, q.instructions) for q in send], answers, banded, qwen_fn)
        res = ArmResult(arm="D", item_id=item.id, run=run, decision=dec, plan=plan.model_dump(), answers=answers,
                        banded=banded, lint=lint, rule_outcome=outcome, jev_calls=n, latency_s=jlat)
        _add_usage(res, u1)
        _add_usage(res, u2)
        res.latency_s = round(res.latency_s, 6)
        return res
    except Exception as e:
        return _err("D", item, run, e)
