# backend/tests/test_jev_tool_lab_arms.py
from rapid_reports_ai.scripts.jev_tool_lab import prompts
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import S1Item, s1_user

ITEM = S1Item(id="s1-t", origin="synthetic", scan_type="CT abdomen",
              dictation="Left renal lesion 3 cm with a thin wall and two thin septa. No enhancement.",
              finding="Left renal lesion 3 cm with a thin wall and two thin septa.", system="Bosniak 2019",
              gradable=True)


def test_s1_user_carries_case_finding_and_system():
    u = s1_user(ITEM)
    assert "DICTATED FINDINGS:\nLeft renal lesion" in u
    assert "FINDING: Left renal lesion 3 cm" in u
    assert "CLASSIFICATION SYSTEM: Bosniak 2019" in u
    assert u.endswith("AVAILABLE TEXTS: the dictation only (there is no report and no clinical history).")


def test_s1_judgement_states_scope_and_literal_rules():
    from rapid_reports_ai.scripts.jev_tool_lab.scenarios import JUDGEMENT_S1
    assert "core category" in JUDGEMENT_S1 and "modifiers" in JUDGEMENT_S1 and "eligibility" in JUDGEMENT_S1
    assert "literally" in JUDGEMENT_S1 and "convention" in JUDGEMENT_S1


def test_author_prompt_lists_catalogue_and_forbids_inference():
    p = prompts.author_system()
    for t in ("T1", "T2", "T3", "T4", "T5", "T6"):
        assert t in p
    assert "Never ask what imaging would show" in p
    assert "before seeing any answer" in p
    assert not any(w in p.lower() for w in ("lesion", "enhancement", "wall"))
    assert "must not contain negation words" in p


def test_free_prompt_has_no_catalogue():
    p = prompts.free_author_system()
    assert "T2" not in p and "noul" in p


def test_decide_prompt_treats_answers_as_evidence():
    assert "evidence" in prompts.decide_system() and "not as verdicts" in prompts.decide_system()


from rapid_reports_ai.scripts.jev_tool_lab.arms import (ArmResult, FreeQuestion, Plan, arm_a, arm_b, lint_free)
from rapid_reports_ai.scripts.jev_tool_lab.calls import Usage
from rapid_reports_ai.scripts.jev_tool_lab.catalogue import QuestionSpec
from rapid_reports_ai.scripts.jev_tool_lab.rules import Condition, Rule
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import Decision


def fake_qwen(outputs):
    """Returns queued outputs in order; records calls."""
    calls = []
    async def fn(output_type, system, user, reasoning):
        calls.append({"type": output_type.__name__, "reasoning": reasoning, "user": user})
        return outputs.pop(0), Usage(input_tokens=100, output_tokens=50, latency_s=1.0)
    fn.calls = calls
    return fn


def fake_jev(answers):
    seen = []
    async def fn(by_state):
        seen.append(by_state)
        qids = [q for qs in by_state.values() for q in qs]
        return {q: answers[q] for q in qids if q in answers}, len(by_state), 0.4
    fn.seen = seen
    return fn


PLAN = Plan(questions=[QuestionSpec(id="q1", type="T2", source="dictation", topic="wall thickness of the lesion"),
                       QuestionSpec(id="q2", type="T2", source="dictation", topic="septa of the lesion"),
                       QuestionSpec(id="q3", type="T2", source="dictation", topic="enhancement of the lesion")],
            rule=Rule(all_of=[Condition(q="q1", want="yes", label="wall"),
                              Condition(q="q2", want="yes", label="septa"),
                              Condition(q="q3", want="yes", label="enhancement")]))


async def test_arm_a_and_a0():
    q = fake_qwen([Decision(gradable=True, reason="r"), Decision(gradable=False, missing=["x"])])
    a = await arm_a(ITEM, run=1, qwen_fn=q)
    a0 = await arm_a(ITEM, run=1, reasoning=False, qwen_fn=q)
    assert (a.arm, a.decision.gradable, a.latency_s, a.qwen_in) == ("A", True, 1.0, 100)
    assert (a0.arm, a0.decision.gradable) == ("A0", False)
    assert [c["reasoning"] for c in q.calls] == [True, False]


async def test_arm_b_rule_decides_without_second_qwen_call():
    q = fake_qwen([PLAN])
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.95}, "q3": {"noul": 0.05}})
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=True), latency_s=9.0)
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=q, jev_fn=j)
    assert b.decision == Decision(gradable=False, missing=["enhancement"], reason="rule")
    assert b.rule_outcome == "no" and not b.fallback
    assert len(q.calls) == 1 and q.calls[0]["reasoning"] is False
    assert b.latency_s == 1.4 and b.jev_calls == 1


async def test_arm_b_falls_back_to_a_when_unsure():
    q = fake_qwen([PLAN])
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.5}, "q3": {"noul": 0.9}})
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=True), latency_s=9.0,
                   qwen_in=1000, qwen_out=500)
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=q, jev_fn=j)
    assert b.fallback and b.decision.gradable is True and b.rule_outcome == "unsure"
    assert b.latency_s == 1.4 + 9.0 and b.qwen_in == 1100


async def test_arm_b_drops_invalid_questions():
    bad = Plan(questions=[QuestionSpec(id="q1", type="T2", source="dictation", topic="no enhancement")],
               rule=Rule(all_of=[Condition(q="q1", want="yes", label="enhancement")]))
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=False), latency_s=2.0)
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=fake_qwen([bad]), jev_fn=fake_jev({}))
    assert b.invalid == ["q1: topic carries a negation"]
    assert b.fallback and b.jev_calls == 0


async def test_arm_b_malformed_rule_falls_back():
    bad = Plan(questions=PLAN.questions, rule=Rule(all_of=[Condition(q="q1", want="o1", label="wall")]))
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=True), latency_s=2.0)
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.9}, "q3": {"noul": 0.9}})
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=fake_qwen([bad]), jev_fn=j)
    assert b.fallback and b.rule_outcome == "unsure"
    assert b.invalid == ["rule: bad want 'o1' for q1"]


async def test_arm_errors_are_recorded_not_raised():
    async def boom(*a, **k):
        raise RuntimeError("down")
    a = await arm_a(ITEM, run=1, qwen_fn=boom)
    assert a.decision is None and a.error.startswith("RuntimeError")


def test_lint_free():
    ok = FreeQuestion(id="q1", type="noul",
                      instructions='The dictated findings describe the "septa" of the lesion in some way.')
    assert lint_free(ok) == []
    # a plain topic question without a quote is fine; an unquoted reference to an item is not
    assert lint_free(FreeQuestion(id="q2", type="noul", instructions="Is the wall thin?")) == []
    assert "unquoted" in lint_free(FreeQuestion(id="q2", type="noul", instructions="Is this lesion thin?"))
    assert "embedded_negative" in lint_free(FreeQuestion(id="q3", type="noul", instructions='"No enhancement" is stated.'))
    assert "embedded_negative" in lint_free(FreeQuestion(id="q3", type="noul", instructions="There is no wall."))
    assert "numbers" in lint_free(FreeQuestion(id="q4", type="noul", instructions='"septa" are over 2 mm.'))
    assert "numbers" in lint_free(FreeQuestion(id="q4", type="noul", instructions='"septa" are present twice.'))
    assert "numbers" in lint_free(FreeQuestion(id="q4", type="noul", instructions='Are "septa" described?',
                                               criteria={"true": "over 2 mm", "false": "other"}))
    assert "numbers" not in lint_free(FreeQuestion(id="q4", type="noul", instructions='Does "left 3 cm lesion" appear?'))
    assert "two_judgements" in lint_free(FreeQuestion(id="q5", type="noul", instructions='Is "wall" thin? Is it smooth?'))
    assert "two_judgements" in lint_free(FreeQuestion(id="q5", type="noul",
                                                      instructions="Is the wall thin or is it smooth?"))
    assert "two_judgements" not in lint_free(FreeQuestion(id="q5", type="noul", instructions="Is the wall thin or thick?"))
    assert "inference" in lint_free(FreeQuestion(id="q6", type="noul", instructions='The "lesion" would enhance.'))
    assert "inference" in lint_free(FreeQuestion(id="q6", type="noul",
                                                 instructions='Does "left renal lesion" meet Bosniak IIF criteria?'))
    assert "choice_without_options" in lint_free(FreeQuestion(id="q7", type="choice", instructions='Pick "wall".'))
    # quote styles
    assert "embedded_negative" in lint_free(FreeQuestion(id="q8", type="noul", instructions="Is “no enhancement” stated?"))
    assert "embedded_negative" in lint_free(FreeQuestion(id="q8", type="noul", instructions="Is 'no enhancement' stated?"))


from rapid_reports_ai.scripts.jev_tool_lab.arms import FreePlan, arm_c, arm_d


async def test_arm_c_second_turn_sees_answers_and_records_overrule_basis():
    q = fake_qwen([PLAN, Decision(gradable=True, reason="septa described as 'two thin septa'")])
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.2}, "q3": {"noul": 0.9}})
    c = await arm_c(ITEM, run=1, qwen_fn=q, jev_fn=j)
    assert [x["type"] for x in q.calls] == ["Plan", "Decision"]
    assert all(x["reasoning"] for x in q.calls)
    second = q.calls[1]["user"]
    assert "CLASSIFIER ANSWERS:" in second and "q2" in second and "no" in second
    assert c.rule_outcome == "no" and c.decision.gradable is True       # Qwen overruled the rule
    assert c.latency_s == 2.4 and c.qwen_in == 200


async def test_arm_d_sends_free_questions_and_lints():
    free = FreePlan(questions=[FreeQuestion(id="q1", type="noul", instructions="Is this lesion thin?"),
                               FreeQuestion(id="q2", type="choice", instructions='Pick "septa".')],
                    rule=Rule(all_of=[Condition(q="q1", want="yes", label="wall")]))
    q = fake_qwen([free, Decision(gradable=False, missing=["wall"])])
    j = fake_jev({"q1": {"noul": 0.1}})
    d = await arm_d(ITEM, run=1, qwen_fn=q, jev_fn=j)
    assert d.arm == "D" and d.decision.gradable is False
    assert "q1: unquoted" in d.lint and "q2: choice_without_options" in d.lint
    sent = [qid for qs in j.seen[0].values() for qid in qs]
    assert sent == ["q1"]                                                # the option-less choice is not sent


# ---- review fixes ----
from rapid_reports_ai.scripts.jev_tool_lab.catalogue import render as _render
from rapid_reports_ai.scripts.jev_tool_lab.arms import FreeQuestion as _FQ
from rapid_reports_ai.scripts.jev_tool_lab.rules import validate_rule as _vr
import inspect

import httpx
import pytest

from rapid_reports_ai.scripts.jev_tool_lab import calls
from rapid_reports_ai.scripts.jev_tool_lab.arms import _raw, arm_cb, validate_free_rule


def test_calls_has_no_stdout_redirect_and_tracks_requests():
    src = inspect.getsource(calls)
    assert "redirect_stdout" not in src and "contextlib" not in src
    assert "16384" in src
    assert Usage().requests == 0


async def test_jev_without_answers_key_raises(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(calls.httpx, "AsyncClient",
                        lambda *a, **k: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"x": 1}))))
    with pytest.raises(RuntimeError, match="jev: no answers in response"):
        await calls.jev({"state": {"q1": {"type": "noul", "instructions": "x"}}})


async def test_arm_b_errored_fallback_is_an_error():
    q = fake_qwen([PLAN])
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.5}, "q3": {"noul": 0.9}})
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, error="RuntimeError: down")
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=q, jev_fn=j)
    assert b.fallback and b.decision is None and b.error == "fallback A failed: RuntimeError: down"


async def test_duplicate_ids_dropped_in_b():
    dup = Plan(questions=[PLAN.questions[0],
                          QuestionSpec(id="q1", type="T2", source="dictation", topic="septa of the lesion")],
               rule=Rule(all_of=[Condition(q="q1", want="yes", label="wall")]))
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=True))
    j = fake_jev({"q1": {"noul": 0.9}})
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=fake_qwen([dup]), jev_fn=j)
    assert "q1: duplicate id" in b.invalid
    assert sum(len(qs) for qs in j.seen[0].values()) == 1
    assert "wall" in str(j.seen[0])


T4PLAN = Plan(questions=[QuestionSpec(id="q1", type="T4", source="dictation", item="Left renal lesion 3 cm",
                                      options=["a cystic lesion", "a solid lesion"])],
              rule=Rule(all_of=[Condition(q="q1", want="o1", label="kind")]))


async def test_arm_c_evidence_explains_options():
    q = fake_qwen([T4PLAN, Decision(gradable=True)])
    j = fake_jev({"q1": {"probabilities": {"o1": 0.8, "o2": 0.1, "cant_tell": 0.1}}})
    await arm_c(ITEM, run=1, qwen_fn=q, jev_fn=j)
    user = q.calls[1]["user"]
    assert " Options: " in user and "o1 = a cystic lesion; o2 = a solid lesion" in user


def test_validate_free_rule():
    from rapid_reports_ai.scripts.jev_tool_lab.arms import FreeQuestion as FQ
    qs = [FQ(id="q1", type="noul", instructions='x "a"'),
          FQ(id="q2", type="choice", instructions='y "b"', criteria={"o1": "p", "o2": "r"})]
    def r(*c): return Rule(all_of=[Condition(q=a, want=b, label="l") for a, b in c])
    assert validate_free_rule(r(("q1", "yes"), ("q2", "o2")), qs) is None
    assert validate_free_rule(r(("q9", "yes")), qs) == "rule names unknown question q9"
    assert validate_free_rule(Rule(all_of=[]), qs) == "empty rule"
    assert validate_free_rule(r(("q1", "o1")), qs) == "bad want 'o1' for q1"
    assert validate_free_rule(r(("q2", "yes")), qs) == "bad want 'yes' for q2"


async def test_arm_d_validates_rule_dedups_caps_and_checks_criteria_keys():
    qs = [FreeQuestion(id="q1", type="noul", instructions='Is "wall" described?',
                       criteria={"yes": "a", "no": "b"}),
          FreeQuestion(id="q1", type="noul", instructions='Is "septa" described?')]
    qs += [FreeQuestion(id=f"x{i}", type="noul", instructions=f'Is "t{i}" described?') for i in range(8)]
    free = FreePlan(questions=qs, rule=Rule(all_of=[Condition(q="q1", want="o1", label="wall")]))
    q = fake_qwen([free, Decision(gradable=False)])
    j = fake_jev({})
    d = await arm_d(ITEM, run=1, qwen_fn=q, jev_fn=j)
    assert "q1: duplicate id" in d.lint and "q1: bad_criteria_keys" in d.lint
    assert any(x.endswith("over the cap") for x in d.lint)
    assert "rule: bad want 'o1' for q1" in d.lint and d.rule_outcome == "unsure"
    sent = {qid: v for qs_ in j.seen[0].values() for qid, v in qs_.items()}
    assert "criteria" not in sent["q1"] and len(sent) == 7


async def test_arm_c_stores_decide_usage():
    c = await arm_c(ITEM, run=1, qwen_fn=fake_qwen([PLAN, Decision(gradable=True)]),
                    jev_fn=fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.9}, "q3": {"noul": 0.9}}))
    assert (c.decide_latency_s, c.decide_in, c.decide_out) == (1.0, 100, 50)


async def test_arm_cb_blank_control():
    q = fake_qwen([PLAN, Decision(gradable=True)])
    c = await arm_c(ITEM, run=1, qwen_fn=q,
                    jev_fn=fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.9}, "q3": {"noul": 0.9}}))
    q2 = fake_qwen([Decision(gradable=False, missing=["x"])])
    cb = await arm_cb(ITEM, run=1, c_result=c, qwen_fn=q2)
    assert len(q2.calls) == 1 and q2.calls[0]["reasoning"] is True
    user = q2.calls[0]["user"]
    assert "not asked" in user and "raw:" not in user and "0.9" not in user
    assert cb.arm == "Cb" and cb.decision.gradable is False
    assert cb.latency_s == c.plan_latency_s + 1.0 and cb.qwen_in == 200


async def test_arm_cb_without_plan_errors():
    cb = await arm_cb(ITEM, run=1, c_result=ArmResult(arm="C", item_id=ITEM.id, run=1, error="plan: x"),
                      qwen_fn=fake_qwen([]))
    assert cb.error == "no C plan"


async def test_stage_prefixed_errors_keep_usage():
    async def jev_boom(by_state):
        raise RuntimeError("jev down")
    b = await arm_b(ITEM, run=1, fallback=ArmResult(arm="A", item_id=ITEM.id, run=1),
                    qwen_fn=fake_qwen([PLAN]), jev_fn=jev_boom)
    assert b.error.startswith("jev: RuntimeError") and b.qwen_in == 100
    async def qboom(*a, **k):
        raise RuntimeError("q down")
    c = await arm_c(ITEM, run=1, qwen_fn=qboom, jev_fn=fake_jev({}))
    assert c.error.startswith("plan: RuntimeError")
    n = {"i": 0}
    async def second_boom(output_type, system, user, reasoning):
        n["i"] += 1
        if n["i"] == 1:
            return PLAN, Usage(input_tokens=7, output_tokens=3, latency_s=1.0)
        raise RuntimeError("decide down")
    c = await arm_c(ITEM, run=1, qwen_fn=second_boom,
                    jev_fn=fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.9}, "q3": {"noul": 0.9}}))
    assert c.error.startswith("decide: RuntimeError") and c.qwen_in == 7


def test_raw_is_robust():
    assert _raw({"noul": "abc"}) == "unreadable"
    assert _raw({"probabilities": {"o1": None}}) == "unreadable"
    assert _raw({"noul": 0.5}) == "0.50"


def test_catalogue_wordings_lint_clean():
    specs = [QuestionSpec(id="q", type="T1", source="dictation", item="Left renal lesion 3 cm"),
             QuestionSpec(id="q", type="T2", source="dictation", topic="wall thickness of the lesion"),
             QuestionSpec(id="q", type="T2", source="report", section="Findings", topic="renal lesion"),
             QuestionSpec(id="q", type="T3", clause="No renal lesion is seen"),
             QuestionSpec(id="q", type="T4", source="dictation", item="Left renal lesion 3 cm",
                          options=["a cystic lesion", "a solid lesion"]),
             QuestionSpec(id="q", type="T5", source="dictation", item="Left renal lesion 3 cm", property="abnormal"),
             QuestionSpec(id="q", type="T6", source="dictation", a="Left renal lesion", b="Left renal cyst")]
    for sp in specs:
        r = _render(sp)
        q = _FQ(id="q", type=r["type"], instructions=r["instructions"], criteria=r.get("criteria"))
        assert lint_free(q) == [], (sp.type, sp.source, lint_free(q))


def test_lint_free_flags_the_grade_asked_directly():
    q = _FQ(id="q", type="noul", instructions="Is the lesion Bosniak IIF?")
    assert "inference" in lint_free(q, system="Bosniak 2019")
    assert "inference" not in lint_free(q)
    assert "inference" not in lint_free(_FQ(id="q", type="noul", instructions='Does "Bosniak IIF" appear?'),
                                        system="Bosniak 2019")


def test_lint_free_unquoted_and_number_words():
    assert "unquoted" in lint_free(_FQ(id="q", type="noul", instructions="Is the above described?"))
    assert "unquoted" not in lint_free(_FQ(id="q", type="noul", instructions="Is that thin?"))
    assert "numbers" not in lint_free(_FQ(id="q", type="noul", instructions="Is only one side described, or half?"))
    assert "numbers" in lint_free(_FQ(id="q", type="noul", instructions="Are there three septa described?"))


def test_validate_rule_first_duplicate_wins():
    specs = [QuestionSpec(id="q1", type="T4", source="dictation", item="Left renal lesion 3 cm",
                          options=["a", "b"]),
             QuestionSpec(id="q1", type="T2", source="dictation", topic="septa")]
    assert _vr(Rule(all_of=[Condition(q="q1", want="o2", label="k")]), specs) is None
    assert _vr(Rule(all_of=[Condition(q="q1", want="yes", label="k")]), specs) == "bad want 'yes' for q1"


async def test_arm_d_passes_the_system_to_lint():
    free = FreePlan(questions=[FreeQuestion(id="q1", type="noul", instructions="Is the lesion Bosniak IIF?")],
                    rule=Rule(all_of=[Condition(q="q1", want="yes", label="g")]))
    d = await arm_d(ITEM, run=1, qwen_fn=fake_qwen([free, Decision(gradable=False)]), jev_fn=fake_jev({}))
    assert "q1: inference" in d.lint


async def test_requests_summed_and_cb_cost_is_plan_turn_plus_own_decide():
    async def qfn(output_type, system, user, reasoning):
        out = PLAN if output_type is Plan else Decision(gradable=True)
        return out, Usage(input_tokens=10, output_tokens=5, latency_s=2.0, requests=3)
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.9}, "q3": {"noul": 0.9}})
    c = await arm_c(ITEM, run=1, qwen_fn=qfn, jev_fn=j)
    assert c.requests == 6 and (c.plan_latency_s, c.plan_in, c.plan_out) == (2.0, 10, 5)
    cb = await arm_cb(ITEM, run=1, c_result=c, qwen_fn=qfn)
    assert (cb.latency_s, cb.qwen_in, cb.qwen_out, cb.requests) == (4.0, 20, 10, 3)
    # C that failed at decide still has a plan and answers: Cb runs
    broken = c.model_copy(update={"error": "decide: x", "decision": None})
    assert (await arm_cb(ITEM, run=1, c_result=broken, qwen_fn=qfn)).error is None


def test_decide_prompt_mentions_not_asked():
    assert 'yes / no / unsure (or "not asked")' in prompts.decide_system()
