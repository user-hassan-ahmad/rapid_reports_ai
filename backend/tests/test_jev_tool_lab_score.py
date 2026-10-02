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
