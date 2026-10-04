"""Phase 3 arms (spec "Phase 3"): list the inputs, then decide. E1 = one structured call (reasoning off / on),
E2 = plan call + decide call with no Jev (the pilot's Cb, stand-alone)."""
import io

from rapid_reports_ai.scripts.jev_tool_lab import prompts, run_lab
from rapid_reports_ai.scripts.jev_tool_lab.arms import ArmResult, Plan, arm_e1, arm_e2
from rapid_reports_ai.scripts.jev_tool_lab.calls import Usage
from rapid_reports_ai.scripts.jev_tool_lab.catalogue import QuestionSpec
from rapid_reports_ai.scripts.jev_tool_lab.rules import Condition
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import Checklist, Decision, InputCheck, S1Item
from rapid_reports_ai.scripts.jev_tool_lab.score import summarise

ITEM = S1Item(id="s1-t", origin="synthetic", scan_type="CT abdomen",
              dictation="Left renal lesion 3 cm with a thin wall and two thin septa. No enhancement.",
              finding="Left renal lesion 3 cm with a thin wall and two thin septa.", system="Bosniak 2019",
              gradable=True)


def fake_qwen(outputs):
    calls = []
    async def fn(output_type, system, user, reasoning):
        calls.append({"type": output_type.__name__, "reasoning": reasoning, "user": user, "system": system})
        return outputs.pop(0), Usage(input_tokens=100, output_tokens=50, latency_s=1.0, requests=1)
    fn.calls = calls
    return fn


CHECK = Checklist(inputs=[InputCheck(input="wall", stated=True, quote="thin wall"),
                          InputCheck(input="enhancement", stated=True, quote="No enhancement")],
                  gradable=True, reason="all stated")


def test_checklist_decodes_string_encoded_lists():
    """Qwen sometimes JSON-encodes a nested list as a string (pilot, 2026-10-02)."""
    c = Checklist.model_validate({"inputs": '[{"input": "wall", "stated": true, "quote": "thin wall"}]',
                                  "gradable": False, "missing": '["enhancement"]'})
    assert c.inputs[0].stated is True and c.missing == ["enhancement"]


def test_checklist_prompt_is_a_checklist_and_case_agnostic():
    from rapid_reports_ai.scripts.jev_tool_lab.scenarios import JUDGEMENT_S1
    p = prompts.checklist_system()
    assert "every input" in p and "quote" in p and "only if every listed input is stated" in p
    own = p.split(JUDGEMENT_S1)[1].lower()           # the shared judgement is checked in its own test
    for word in ("lesion", "enhancement", "nodule", "wall"):
        assert word not in own


async def test_arm_e1_off_and_on():
    q = fake_qwen([CHECK, CHECK])
    off = await arm_e1(ITEM, run=1, reasoning=False, qwen_fn=q)
    on = await arm_e1(ITEM, run=1, reasoning=True, qwen_fn=q)
    assert (off.arm, on.arm) == ("E1off", "E1on")
    assert [c["reasoning"] for c in q.calls] == [False, True]
    assert all(c["type"] == "Checklist" for c in q.calls)
    assert off.decision == Decision(gradable=True, missing=[], reason="all stated")
    assert off.checklist[1] == {"input": "enhancement", "stated": True, "quote": "No enhancement"}
    assert (off.latency_s, off.qwen_in, off.requests, off.jev_calls) == (1.0, 100, 1, 0)


async def test_arm_e1_error_is_staged():
    async def boom(*a, **k):
        raise RuntimeError("down")
    r = await arm_e1(ITEM, run=1, reasoning=False, qwen_fn=boom)
    assert r.decision is None and r.error.startswith("checklist: RuntimeError")


async def test_arm_e2_plans_then_decides_blank_without_jev():
    plan = Plan(questions=[QuestionSpec(id="q1", type="T2", source="dictation", topic="wall of the lesion"),
                           QuestionSpec(id="q2", type="T2", source="dictation", topic="no enhancement")],
                rule=[Condition(q="q1", want="yes", label="wall")])
    q = fake_qwen([plan, Decision(gradable=True, reason="r")])
    r = await arm_e2(ITEM, run=1, qwen_fn=q)
    assert r.arm == "E2" and r.decision.gradable is True and r.jev_calls == 0
    assert [(c["type"], c["reasoning"]) for c in q.calls] == [("Plan", True), ("Decision", True)]
    second = q.calls[1]["user"]
    assert "q1" in second and "not asked" in second and "q2" not in second.split("CLASSIFIER ANSWERS:")[1]
    assert r.invalid == ["q2: topic carries a negation"]
    assert (r.latency_s, r.qwen_in, r.requests) == (2.0, 200, 2)


def test_score_reports_checklist_consistency_and_quote_grounding():
    items = {ITEM.id: ITEM}
    good = ArmResult(arm="E1off", item_id=ITEM.id, run=1, decision=Decision(gradable=True),
                     checklist=[{"input": "wall", "stated": True, "quote": "thin wall"},
                                {"input": "enh", "stated": True, "quote": "No enhancement"}])
    bad = ArmResult(arm="E1off", item_id=ITEM.id, run=2, decision=Decision(gradable=True),
                    checklist=[{"input": "wall", "stated": False, "quote": ""},
                               {"input": "enh", "stated": True, "quote": "contrast washout"}])
    s = summarise([good, bad], items)["E1off"]
    assert s["checklist_consistent"] == 0.5          # run 2 says gradable with an unstated input
    assert s["quote_grounded"] == 2 / 3              # 3 stated inputs, 2 quotes found in the dictation


async def test_run_lab_runs_e_arms(monkeypatch):
    log = []
    def mk(name):
        async def fn(item, *, run, **kw):
            arm = name if name != "E1" else ("E1on" if kw["reasoning"] else "E1off")
            log.append(arm)
            return ArmResult(arm=arm, item_id=item.id, run=run, decision=Decision(gradable=True))
        return fn
    monkeypatch.setattr(run_lab, "arm_a", mk("A"))
    monkeypatch.setattr(run_lab, "arm_e1", mk("E1"))
    monkeypatch.setattr(run_lab, "arm_e2", mk("E2"))
    out = io.StringIO()
    await run_lab.run_lab([ITEM], ["A", "E1off", "E1on", "E2"], runs=1, d_runs=0, out=out, reuse={})
    assert sorted(log) == ["A", "E1off", "E1on", "E2"]


def test_score_reports_accuracy_per_category():
    def it(i, g, cat):
        return S1Item(id=f"c{i}", origin="synthetic", scan_type="CT", dictation="d", finding="d", system="S",
                      gradable=g, missing=[] if g else ["x"], category=cat)
    items = {x.id: x for x in (it(1, False, "silence-overcall"), it(2, False, "silence-overcall"), it(3, True, "complete-plain"))}
    rows = [ArmResult(arm="A", item_id=i, run=1, decision=Decision(gradable=g))
            for i, g in (("c1", True), ("c2", False), ("c3", True))]
    s = summarise(rows, items)["A"]
    assert s["by_category"] == {"complete-plain": {"n": 1, "correct": 1}, "silence-overcall": {"n": 2, "correct": 1}}


async def test_run_lab_restricts_later_runs_to_a_subset(monkeypatch):
    seen = []
    async def fake(item, *, run, **kw):
        seen.append((item.id, run))
        return ArmResult(arm="A", item_id=item.id, run=run, decision=Decision(gradable=True))
    monkeypatch.setattr(run_lab, "arm_a", fake)
    other = ITEM.model_copy(update={"id": "s1-u"})
    await run_lab.run_lab([ITEM, other], ["A"], runs=2, d_runs=0, out=io.StringIO(), reuse={},
                          later_run_ids={"s1-u"})
    assert sorted(seen) == [("s1-t", 1), ("s1-u", 1), ("s1-u", 2)]
