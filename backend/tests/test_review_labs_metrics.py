import os  # noqa: F401
import pytest  # noqa: F401

from rapid_reports_ai.scripts.review_labs import metrics as M


def test_gate_a_metrics():
    labels = {"a": {"verdict": "action", "material": True}, "b": {"verdict": "action"},
              "c": {"verdict": "suppress"}, "d": {"verdict": "minor"}}
    run1 = {"a": "action", "b": "minor", "c": "action", "d": "minor"}
    run2 = {"a": "action", "b": "suppress", "c": "action", "d": "minor"}
    report_of = {"a": "r1", "b": "r1", "c": "r2", "d": "r2"}
    m = M.gate_a([run1, run2], labels, report_of)
    assert m["action_recall"] == 1.0                      # a, b shown in run 1
    assert m["material_missed"] == []
    assert m["action_precision"] == 0.5                   # a right, c wrong
    assert m["minor_per_report_median"] == 1.0
    assert m["class_change_share"] == 0.25                # b changed
    assert m["crossed_shown_hidden"] == ["b"]
    assert M.gate_a_pass(m) == {"recall": True, "material": True, "precision": False, "noise": True, "stability": False}


def test_binary_and_bands():
    rows = [(True, True), (True, False), (False, False), (False, True)]
    b = M.binary(rows)
    assert b == {"n_pos": 2, "n_neg": 2, "recall": 0.5, "false_alarm": 0.5}
    probs, labels = [0.9, 0.6, 0.1, 0.65], [True, True, False, False]
    e = M.errors_by_band(probs, labels, lo=0.3, hi=0.7)
    assert e["yes"] == {"n": 1, "errors": 0} and e["unsure"] == {"n": 2, "errors": 1} and e["no"] == {"n": 1, "errors": 0}


def test_gate_a_missing_ids_and_run2_gap():
    labels = {"a": {"verdict": "action"}}
    with pytest.raises(ValueError):
        M.gate_a([{"a": "action", "b": "minor"}], labels, {"a": "r1"})
    m = M.gate_a([{"a": "action", "b": "minor"}, {"a": "action"}], labels, {"a": "r1", "b": "r1"})
    assert m["n_missing_run2"] == 1
