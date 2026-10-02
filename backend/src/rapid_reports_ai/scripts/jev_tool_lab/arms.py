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
    decide_latency_s: float = 0.0
    decide_in: int = 0
    decide_out: int = 0
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


def _fail(res: ArmResult, stage: str, e: Exception) -> ArmResult:
    """Record a stage failure on the progressively built result, keeping the usage already spent."""
    res.error = f"{stage}: {type(e).__name__}: {str(e)[:200]}"
    res.latency_s = round(res.latency_s, 6)
    return res


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
    case, out, seen = item.case(), Asked(), set()
    for s in questions[:MAX_QUESTIONS]:
        if s.id in seen:
            out.invalid.append(f"{s.id}: duplicate id")
            continue
        seen.add(s.id)
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
    res = ArmResult(arm="B", item_id=item.id, run=run)
    try:
        plan, u = await qwen_fn(Plan, prompts.author_system(), s1_user(item), False)
    except Exception as e:
        return _fail(res, "plan", e)
    _add_usage(res, u)
    res.plan = plan.model_dump()
    try:
        asked = await _ask(plan.questions, item, jev_fn)
        rule_err = validate_rule(plan.rule, plan.questions)       # review fix: a malformed rule is unsure, never "no"
        outcome, failed = (UNSURE, []) if rule_err else evaluate(plan.rule, asked.banded)
    except Exception as e:
        return _fail(res, "jev", e)
    res.answers, res.banded = asked.answers, asked.banded
    res.invalid = asked.invalid + ([f"rule: {rule_err}"] if rule_err else [])
    res.rule_outcome, res.jev_calls = outcome, asked.calls
    res.latency_s += asked.latency_s
    if outcome == UNSURE:
        res.fallback = True
        res.decision = fallback.decision
        res.latency_s += fallback.latency_s
        res.qwen_in += fallback.qwen_in
        res.qwen_out += fallback.qwen_out
        if fallback.decision is None:
            res.error = f"fallback A failed: {fallback.error}"
    else:
        res.decision = Decision(gradable=outcome == "yes", missing=failed, reason="rule")
    res.latency_s = round(res.latency_s, 6)
    return res


_QUOTE = re.compile(r"\"([^\"]*)\"|\u201c([^\u201d]*)\u201d|(?<!\w)'([^']{2,})'")
_NEG_WORDS = re.compile(r"\b(no|not|without|absent|negative|nil|none)\b", re.I)
_NEG_CLAIM = re.compile(r"\b(is|are|there is|there are)\s+(no|not)\b", re.I)
_INFER = re.compile(r"\b(would|expected|likely|should|typical|typically|suggests?|meets?|criteria|grade|classif\w*|"
                    r"requires?|consistent with|implies?)\b", re.I)
_TWO = re.compile(r"\b(and also|or whether|and whether|as well as|or)\b", re.I)
_REF = re.compile(r"\b(this|that|these|the above)\b", re.I)
_NUMWORD = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twice|half)\b", re.I)


def lint_free(q: FreeQuestion) -> List[str]:
    """Rule breaks in a free-form question (spec §2.1 forbidden list); D's risk measure."""
    text = q.instructions
    quotes = [next(g for g in m.groups() if g is not None) for m in _QUOTE.finditer(text)]
    outside = _QUOTE.sub(" ", text)
    crit = " ".join((q.criteria or {}).values())
    codes = []
    if not quotes and _REF.search(text):
        codes.append("unquoted")
    if any(_NEG_WORDS.search(x) for x in quotes) or _NEG_CLAIM.search(outside):
        codes.append("embedded_negative")
    if any(re.search(r"\d|" + _NUMWORD.pattern, t, re.I) for t in (outside, crit)):
        codes.append("numbers")
    if text.count("?") > 1 or _TWO.search(outside):
        codes.append("two_judgements")
    if _INFER.search(outside):
        codes.append("inference")
    if q.type == "choice" and not q.criteria:
        codes.append("choice_without_options")
    return codes


def validate_free_rule(rule: Rule, questions: List[FreeQuestion]) -> Optional[str]:
    """None if the declared rule is usable against the free-form questions, else a reason."""
    if not rule.all_of:
        return "empty rule"
    by_id = {q.id: q for q in questions}
    for c in rule.all_of:
        q = by_id.get(c.q)
        if q is None:
            return f"rule names unknown question {c.q}"
        if q.type == "noul" and c.want in ("yes", "no"):
            continue
        if q.type == "choice" and c.want in (q.criteria or {}):
            continue
        return f"bad want {c.want!r} for {c.q}"
    return None


def _raw(ans: Any) -> str:
    try:
        if isinstance(ans, dict) and "probabilities" in ans:
            return ", ".join(f"{k} {float(v):.2f}" for k, v in ans["probabilities"].items())
        if isinstance(ans, dict) and "noul" in ans:
            return f"{float(ans['noul']):.2f}"
    except (TypeError, ValueError, AttributeError):
        return "unreadable"
    return "no answer"


def _describe(q: dict) -> str:
    text = q.get("instructions", "")
    if q.get("criteria"):
        text += " Options: " + "; ".join(f"{k} = {v}" for k, v in q["criteria"].items())
    return text


def _evidence(described: List[tuple], answers: Dict[str, Any], banded: Dict[str, str]) -> str:
    return "\n".join(f"{qid} ({desc}): {banded.get(qid, UNSURE)} [raw: {_raw(answers.get(qid))}]"
                     for qid, desc in described) or "(no valid questions)"


async def _decide(item: S1Item, described: List[tuple], answers, banded, qwen_fn, blank: bool = False):
    if blank:
        ev = "\n".join(f"{qid} ({desc}): not asked" for qid, desc in described) or "(no valid questions)"
    else:
        ev = _evidence(described, answers, banded)
    user = f"{s1_user(item)}\n\nCLASSIFIER ANSWERS:\n{ev}"
    return await qwen_fn(Decision, prompts.decide_system(), user, True)


def _store_decide(res: ArmResult, u) -> None:
    res.decide_latency_s, res.decide_in, res.decide_out = u.latency_s, u.input_tokens, u.output_tokens


async def arm_c(item: S1Item, *, run: int, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    res = ArmResult(arm="C", item_id=item.id, run=run)
    try:
        plan, u1 = await qwen_fn(Plan, prompts.author_system(), s1_user(item), True)
    except Exception as e:
        return _fail(res, "plan", e)
    _add_usage(res, u1)
    res.plan = plan.model_dump()
    try:
        asked = await _ask(plan.questions, item, jev_fn)
        rule_err = validate_rule(plan.rule, plan.questions)
        outcome = UNSURE if rule_err else evaluate(plan.rule, asked.banded)[0]
    except Exception as e:
        return _fail(res, "jev", e)
    res.answers, res.banded = asked.answers, asked.banded
    res.invalid = asked.invalid + ([f"rule: {rule_err}"] if rule_err else [])
    res.rule_outcome, res.jev_calls = outcome, asked.calls
    res.latency_s += asked.latency_s
    try:
        described = [(s.id, _describe(render(s))) for s in asked.valid]
        dec, u2 = await _decide(item, described, asked.answers, asked.banded, qwen_fn)
    except Exception as e:
        return _fail(res, "decide", e)
    res.decision = dec
    _add_usage(res, u2)
    _store_decide(res, u2)
    res.latency_s = round(res.latency_s, 6)
    return res


async def arm_cb(item: S1Item, *, run: int, c_result: ArmResult, qwen_fn=calls.qwen) -> ArmResult:
    """C-blank control: C's own plan, the decide turn with every answer shown as 'not asked'."""
    res = ArmResult(arm="Cb", item_id=item.id, run=run)
    if c_result.plan is None or c_result.error:
        res.error = "no C plan"
        return res
    try:
        plan = Plan.model_validate(c_result.plan)
        ids, seen, described = set(c_result.banded or {}), set(), []
        for s in plan.questions:
            if s.id in ids and s.id not in seen:
                seen.add(s.id)
                described.append((s.id, _describe(render(s))))
    except Exception as e:
        return _fail(res, "plan", e)
    res.plan = c_result.plan
    res.latency_s = c_result.latency_s - c_result.decide_latency_s
    res.qwen_in = c_result.qwen_in - c_result.decide_in
    res.qwen_out = c_result.qwen_out - c_result.decide_out
    try:
        dec, u = await _decide(item, described, {}, {}, qwen_fn, blank=True)
    except Exception as e:
        return _fail(res, "decide", e)
    res.decision = dec
    _add_usage(res, u)
    _store_decide(res, u)
    res.latency_s = round(res.latency_s, 6)
    return res


async def arm_d(item: S1Item, *, run: int, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    res = ArmResult(arm="D", item_id=item.id, run=run)
    try:
        plan, u1 = await qwen_fn(FreePlan, prompts.free_author_system(), s1_user(item), True)
    except Exception as e:
        return _fail(res, "plan", e)
    _add_usage(res, u1)
    res.plan = plan.model_dump()
    try:
        kept, lint, seen = [], [], set()
        for q in plan.questions[:MAX_QUESTIONS]:
            if q.id in seen:
                lint.append(f"{q.id}: duplicate id")
                continue
            seen.add(q.id)
            kept.append(q)
        lint += [f"{q.id}: over the cap" for q in plan.questions[MAX_QUESTIONS:]]
        lint += [f"{q.id}: {code}" for q in kept for code in lint_free(q)]
        for q in kept:
            if q.type == "noul" and q.criteria and set(q.criteria) != {"true", "false"}:
                lint.append(f"{q.id}: bad_criteria_keys")
        send = [q for q in kept if not (q.type == "choice" and not q.criteria)]
        def crit(q):
            return q.criteria if q.type == "choice" or set(q.criteria or {}) == {"true", "false"} else None
        jq = {q.id: {"type": q.type, "instructions": q.instructions, **({"criteria": crit(q)} if crit(q) else {})}
              for q in send}
        answers, n, jlat = (await jev_fn({state_for(item.case(), "dictation"): jq})) if jq else ({}, 0, 0.0)
        banded = {q.id: band(answers.get(q.id), q.type) for q in send}
        rule_err = validate_free_rule(plan.rule, kept)
        if rule_err:
            lint.append(f"rule: {rule_err}")
        outcome = UNSURE if rule_err else evaluate(plan.rule, banded)[0]
    except Exception as e:
        return _fail(res, "jev", e)
    res.answers, res.banded, res.lint, res.rule_outcome = answers, banded, lint, outcome
    res.jev_calls = n
    res.latency_s += jlat
    try:
        dec, u2 = await _decide(item, [(q.id, _describe(jq[q.id])) for q in send], answers, banded, qwen_fn)
    except Exception as e:
        return _fail(res, "decide", e)
    res.decision = dec
    _add_usage(res, u2)
    _store_decide(res, u2)
    res.latency_s = round(res.latency_s, 6)
    return res
