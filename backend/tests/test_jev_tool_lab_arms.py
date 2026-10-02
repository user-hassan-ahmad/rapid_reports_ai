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


def test_author_prompt_lists_catalogue_and_forbids_inference():
    p = prompts.author_system()
    for t in ("T1", "T2", "T3", "T4", "T5", "T6"):
        assert t in p
    assert "Never ask what imaging would show" in p
    assert "before seeing any answer" in p


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
    assert "unquoted" in lint_free(FreeQuestion(id="q2", type="noul", instructions="Is the wall thin?"))
    assert "embedded_negative" in lint_free(FreeQuestion(id="q3", type="noul", instructions='"No enhancement" is stated.'))
    assert "numbers" in lint_free(FreeQuestion(id="q4", type="noul", instructions='"septa" are over 2 mm.'))
    assert "two_judgements" in lint_free(FreeQuestion(id="q5", type="noul", instructions='Is "wall" thin? Is it smooth?'))
    assert "inference" in lint_free(FreeQuestion(id="q6", type="noul", instructions='The "lesion" would enhance.'))
    assert "choice_without_options" in lint_free(FreeQuestion(id="q7", type="choice", instructions='Pick "wall".'))


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
    free = FreePlan(questions=[FreeQuestion(id="q1", type="noul", instructions="Is the wall thin?"),
                               FreeQuestion(id="q2", type="choice", instructions='Pick "septa".')],
                    rule=Rule(all_of=[Condition(q="q1", want="yes", label="wall")]))
    q = fake_qwen([free, Decision(gradable=False, missing=["wall"])])
    j = fake_jev({"q1": {"noul": 0.1}})
    d = await arm_d(ITEM, run=1, qwen_fn=q, jev_fn=j)
    assert d.arm == "D" and d.decision.gradable is False
    assert "q1: unquoted" in d.lint and "q2: choice_without_options" in d.lint
    sent = [qid for qs in j.seen[0].values() for qid in qs]
    assert sent == ["q1"]                                                # the option-less choice is not sent
