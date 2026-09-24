from __future__ import annotations

from rapid_reports_ai.scripts.triage_summary import Record, summarise


def _rec(candidate, expected, action, conf=None, lat=100, hard=False, err=None, ic=None, eic=None):
    return Record(
        id=f"{expected}-{action}", candidate=candidate, expected_action=expected, action=action,
        confidence=conf, latency_ms=lat, cost_usd=0.00002 if candidate == "jev" else None, hard=hard, error=err,
        is_correction=ic, expected_is_correction=eic, needs_committed_edit=None, expected_needs_committed_edit=None,
    )


def test_summarise_accuracy_latency_and_buckets():
    records = [
        _rec("jev", "ignore_noise", "ignore_noise", 0.99, 200),
        _rec("jev", "ignore_noise", "append_new_finding", 0.6, 300),
        _rec("jev", "append_new_finding", "append_new_finding", 0.97, 250, hard=True),
        _rec("jev", "append_new_finding", None, None, 0, err="TriageError"),
        _rec("qwen", "ignore_noise", "ignore_noise", None, 700),
        _rec("qwen", "ignore_noise", "ignore_noise", None, 900),
    ]
    s = summarise(records)

    jev = s["jev"]
    assert jev["n"] == 4 and jev["errors"] == 1
    assert jev["accuracy"] == 2 / 3  # errors excluded from accuracy
    assert jev["per_action"]["ignore_noise"]["recall"] == 0.5
    assert jev["per_action"]["append_new_finding"]["precision"] == 0.5
    assert jev["confusion"]["ignore_noise"]["append_new_finding"] == 1
    assert jev["latency_p50_ms"] == 250 and jev["latency_p95_ms"] == 300
    assert jev["cost_usd"] == 0.00008
    assert jev["hard"]["n"] == 1 and jev["hard"]["accuracy"] == 1.0
    assert jev["confidence_buckets"][">=0.95"] == {"n": 2, "accuracy": 1.0, "coverage": 2 / 3}
    assert jev["confidence_buckets"]["0.5-0.8"] == {"n": 1, "accuracy": 0.0, "coverage": 1 / 3}

    qwen = s["qwen"]
    assert qwen["accuracy"] == 1.0 and "confidence_buckets" not in qwen
    assert qwen["latency_p50_ms"] == 800


def test_summarise_aux_signals_at_half():
    records = [
        _rec("jev", "correct_previous_finding", "correct_previous_finding", 0.9, ic=0.8, eic=True),
        _rec("jev", "append_new_finding", "append_new_finding", 0.9, ic=0.6, eic=False),
    ]
    assert summarise(records)["jev"]["is_correction_accuracy"] == 0.5
