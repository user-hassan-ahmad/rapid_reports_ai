import pytest

from rapid_reports_ai.scripts.jev_tool_lab.arms import ArmResult
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import Decision, S1Item
from rapid_reports_ai.scripts.jev_tool_lab.score import (auc, balanced_accuracy, brier, ece, mcnemar_exact, paired,
                                                         percentile, summarise)


def item(i, gradable):
    return S1Item(id=f"i{i}", origin="synthetic", scan_type="CT", dictation="d", finding="d", system="S",
                  gradable=gradable)


ITEMS = {f"i{i}": item(i, i < 2) for i in range(4)}      # i0,i1 gradable; i2,i3 not


def res(arm, i, run, g, **kw):
    return ArmResult(arm=arm, item_id=f"i{i}", run=run, decision=Decision(gradable=g), **kw)


def test_balanced_accuracy_and_percentile():
    assert balanced_accuracy([(True, True), (True, False), (False, False), (False, False)]) == 0.75
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
    assert percentile([], 0.5) is None


def test_calibration_metrics():
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert ece([0.9, 0.9, 0.1, 0.1], [True, True, False, False], bins=5) == pytest.approx(0.1)
    assert auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert auc([0.5, 0.5], [True, False]) == 0.5


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(0.0625)


def test_paired_gains_and_losses():
    a = [res("A", 0, 1, True), res("A", 1, 1, False), res("A", 2, 1, False), res("A", 3, 1, True)]
    b = [res("B", 0, 1, True), res("B", 1, 1, True), res("B", 2, 1, True), res("B", 3, 1, False)]
    assert paired(b, a, ITEMS, run=1) == {"gains": 2, "losses": 1}   # gains i1, i3; loss i2


def test_summarise_core_fields():
    rows = [res("A", i, r, ITEMS[f"i{i}"].gradable, latency_s=10.0, qwen_in=100) for i in range(4) for r in (1, 2)]
    rows += [res("B", i, 1, True, latency_s=2.0, rule_outcome="yes", plan={"questions": [{}, {}]},
                 invalid=["q1: x"] if i == 0 else []) for i in range(4)]
    rows.append(res("C", 0, 1, False, rule_outcome="yes"))
    rows.append(res("Cb", 0, 1, True))
    s = summarise(rows, ITEMS)
    assert s["A"]["bal_acc"] == 1.0 and s["A"]["stability"] == 1.0 and s["A"]["p90_latency_s"] == 10.0
    assert s["B"]["bal_acc"] == 0.5 and s["B"]["invalid_share"] == pytest.approx(1 / 8)
    assert (s["B"]["vs_A"]["run1"]["gains"], s["B"]["vs_A"]["run1"]["losses"]) == (0, 2)
    assert s["C"]["overrule_share"] == 1.0 and s["C"]["overrule_right_share"] == 0.0
    assert s["C"]["vs_Cb"]["run1"] == {"gains": 0, "losses": 1}


def test_summarise_excludes_rule_entries_and_reports_ratios():
    rows = [res("A", i, 1, ITEMS[f"i{i}"].gradable, latency_s=10.0, qwen_in=1000, qwen_out=500, requests=1)
            for i in range(4)]
    rows += [res("B", i, 1, ITEMS[f"i{i}"].gradable, latency_s=2.0, qwen_in=200, qwen_out=100, requests=2,
                 plan={"questions": [{}, {}]}, invalid=["q1: x", "rule: bad want 'o1' for q1"] if i == 0 else [])
             for i in range(4)]
    rows += [res("D", 0, 1, True, plan={"questions": [{}, {}]}, lint=["q1: unquoted", "q1: numbers", "rule: empty rule"])]
    s = summarise(rows, ITEMS)
    assert s["B"]["invalid_share"] == pytest.approx(1 / 8)           # the rule entry is not an invalid question
    assert s["B"]["rule_invalid_share"] == 0.25                        # 1 of 4 plans had a malformed rule
    assert s["D"]["lint_share"] == 0.5                                 # q1 only; "rule" is not a question id
    assert s["A"]["mean_requests"] == 1 and s["B"]["mean_requests"] == 2
    assert s["B"]["p90_latency_vs_A"] == 0.2 and s["B"]["tokens_vs_A"] == 0.2


from rapid_reports_ai.scripts.jev_tool_lab import wording_check as wc


async def test_wording_check_runs_and_reports():
    items = [wc.CheckItem(id="t1", kind="T2d", dictation="Thin septa.", topic="septa of the lesion", label=True),
             wc.CheckItem(id="t2", kind="T2d", dictation="Thin septa.", topic="calcification", label=False),
             wc.CheckItem(id="s1", kind="T6", dictation="Left cyst. Right cyst.", a="Left cyst", b="Right cyst",
                          label=False)]
    async def fake_jev(by_state):
        ans = {}
        for qs in by_state.values():
            for qid in qs:
                ans[qid] = {"noul": 0.9 if qid.startswith("t1") else 0.1}
        return ans, len(by_state), 0.1
    rows = await wc.run(items, wordings=("w1", "w2"), repeats=2, jev_fn=fake_jev)
    assert len(rows) == 3 * 2 * 2
    rep = wc.report(rows)
    t2 = rep["T2d|w1"]
    assert t2["auc"] == 1.0 and t2["confident_errors"] == 0 and t2["unsure_share"] == 0.0 and t2["max_drift"] == 0.0
    assert rep["T6|w1"]["n"] == 1


def test_wording_report_groups_are_split_out():
    rows = [{"id": i, "kind": "T2d", "wording": "w1", "repeat": 1, "p": p, "label": y}
            for i, p, y in (("a", 0.9, True), ("b", 0.1, False), ("s1", 0.9, False), ("s2", 0.9, True))]
    rep = wc.report(rows, groups={"scoped": {"s1", "s2"}})
    assert rep["T2d|w1"]["n"] == 2 and rep["T2d|w1"]["confident_errors"] == 0      # main set excludes the group
    assert rep["T2d|w1|scoped"]["n"] == 2 and rep["T2d|w1|scoped"]["confident_errors"] == 1


import json as _json
from pathlib import Path as _Path

from rapid_reports_ai.scripts.jev_tool_lab.catalogue import Case, QuestionSpec, validate

_FIX = _Path(__file__).resolve().parents[1] / "test_cases" / "jev_tool_lab"


def test_wording_fixture_shape():
    items = [wc.CheckItem(**x) for x in _json.loads((_FIX / "wording_check.json").read_text())]
    for kind, n in (("T2d", 28), ("T6", 20)):            # T2d includes 8 finding-scoped items (peer review)
        k = [i for i in items if i.kind == kind]
        assert len(k) == n and sum(i.label for i in k) == n // 2
    for i in items:
        spec = (QuestionSpec(id=i.id, type="T2", source="dictation", topic=i.topic) if i.kind == "T2d"
                else QuestionSpec(id=i.id, type="T6", source="dictation", a=i.a, b=i.b))
        assert validate(spec, Case(dictation=i.dictation)) is None, i.id


def test_s1_fixture_shape():
    items = [S1Item(**x) for x in _json.loads((_FIX / "s1_pilot.json").read_text())]
    assert len(items) == 20 and sum(i.gradable for i in items) == 10
    assert len({i.system for i in items}) >= 5 and len({i.scan_type for i in items}) >= 4
    for i in items:
        assert i.finding in i.dictation, i.id
        assert i.gradable == (not i.missing), i.id


def test_group_id_files_name_real_items():
    ids = {x["id"] for x in _json.loads((_FIX / "wording_check.json").read_text())}
    scoped = _json.loads((_FIX / "scoped_ids.json").read_text())
    side = _json.loads((_FIX / "context_side_ids.json").read_text())
    assert scoped == [f"t2d-{n}" for n in range(21, 29)] and set(scoped) <= ids
    assert set(side) <= ids and side
