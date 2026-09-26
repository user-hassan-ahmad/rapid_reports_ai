from __future__ import annotations

import pytest

from rapid_reports_ai.scripts.calibration_report import calibration_block, hard_choice, hard_noul, verdict


def test_hard_labels():
    assert hard_choice("b") == {"b": 1.0}
    assert hard_noul(0.7) == 1.0 and hard_noul(0.2) == 0.0 and hard_noul(True) == 1.0


def test_choice_block_accuracy_brier_ece():
    labels = ["a", "a", "b", "b"]
    jev = [{"a": 0.9, "b": 0.1}, {"a": 0.8, "b": 0.2}, {"a": 0.3, "b": 0.7}, {"a": 0.6, "b": 0.4}]
    hard = [hard_choice("a"), hard_choice("a"), hard_choice("b"), hard_choice("a")]
    s, text = calibration_block("action", "choice", {"jev": (jev, labels), "qwen": (hard, labels)})
    j, q = s["candidates"]["jev"], s["candidates"]["qwen"]
    assert j["accuracy"]["k"] == 3 and q["accuracy"]["k"] == 3
    # multiclass Brier: 0.02, 0.08, 0.18, 0.72 -> 0.25 ; hard: 0,0,0,2 -> 0.5
    assert j["brier"] == pytest.approx(0.25) and q["brier"] == pytest.approx(0.5)
    # top-label ECE, hard: every confidence 1.0, 3/4 right -> 0.25
    assert q["ece"] == pytest.approx(0.25)
    assert len(j["brier_ci"]) == 2 and len(j["reliability"]) == 10
    d = s["vs_jev"]["qwen"]
    assert d["brier_diff"] == pytest.approx(0.25)  # other - jev: positive = jev lower
    assert "action" in text and "jev" in text and "qwen" in text and "Brier" in text


def test_noul_block_with_groups():
    ys = [1, 0, 1, 0, 1, 0]
    p = [0.9, 0.1, 0.8, 0.3, 0.6, 0.4]
    s, _ = calibration_block("coverage", "noul", {"jev": (p, ys), "qwen": ([hard_noul(x) for x in p], ys)},
                             groups=["c1", "c1", "c2", "c2", "c3", "c3"])
    assert s["candidates"]["jev"]["n"] == 6 and s["candidates"]["jev"]["accuracy"]["k"] == 6
    assert s["candidates"]["qwen"]["brier"] == 0.0 and s["candidates"]["jev"]["brier"] > 0


def test_block_rejects_misaligned_candidates():
    with pytest.raises(ValueError):
        calibration_block("q", "noul", {"jev": ([0.5], [1]), "qwen": ([0.5, 0.5], [1, 0])})


def test_verdict_rule():
    # other - jev intervals; positive = jev lower (better)
    assert verdict({"brier_diff_ci": [0.01, 0.2], "ece_diff_ci": [-0.05, 0.1]}) == "jev better"
    assert verdict({"brier_diff_ci": [0.01, 0.2], "ece_diff_ci": [-0.2, -0.01]}) == "mixed"
    assert verdict({"brier_diff_ci": [-0.2, -0.01], "ece_diff_ci": [-0.1, 0.1]}) == "other better"
    assert verdict({"brier_diff_ci": [-0.05, 0.05], "ece_diff_ci": [-0.1, 0.1]}) == "not shown"
