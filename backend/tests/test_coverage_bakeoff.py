from rapid_reports_ai.scripts.coverage_bakeoff import Row, score


def test_score_per_section_and_exact_set():
    rows = [
        Row("a", "jev", ["L", "P", "M"], ["L", "P"], {"L": 0.9, "P": 0.8, "M": 0.1}, 300, None, False, "direct-subject", None),
        Row("b", "jev", ["L", "P", "M"], ["L"], {"L": 0.3, "P": 0.9, "M": 0.1}, 400, None, True, "bare-mention", None),
        Row("c", "jev", ["L"], ["L"], None, 0, None, False, "direct-subject", "TriageError"),
    ]
    s = score(rows)["jev"]
    assert s["n"] == 3 and s["errors"] == 1
    # sections: a: L tp, P tp, M tn; b: L fn, P fp, M tn  => tp=2 fp=1 fn=1
    assert s["precision"] == 2 / 3 and s["recall"] == 2 / 3
    assert s["exact_set_accuracy"] == 0.5
    assert s["by_rule"]["bare-mention"]["exact"] == 0.0
    assert s["hard"]["exact"] == 0.0
    assert s["latency_p50_ms"] == 350
    # confidences 0.5+|p-0.5|: a: 0.9,0.8,0.9  b: 0.7,0.9,0.9 -> none >=0.95; five in 0.8-0.95; one in 0.5-0.8
    assert s["buckets"][">=0.95"]["n"] == 0
    assert s["buckets"]["0.8-0.95"]["n"] == 5
    assert s["buckets"]["0.5-0.8"]["n"] == 1


def test_score_carries_rates():
    rows = [
        Row("a", "jev", ["L", "P", "M"], ["L", "P"], {"L": 0.9, "P": 0.8, "M": 0.1}, 300, None, False, "direct-subject", None),
        Row("b", "jev", ["L", "P", "M"], ["L"], {"L": 0.3, "P": 0.9, "M": 0.1}, 400, None, True, "bare-mention", None),
    ]
    s = score(rows)["jev"]
    assert (s["precision_rate"]["k"], s["precision_rate"]["n"]) == (2, 3)
    assert (s["recall_rate"]["k"], s["recall_rate"]["n"]) == (2, 3)
    assert (s["exact_rate"]["k"], s["exact_rate"]["n"]) == (1, 2)
    assert len(s["latency_p95_ci_ms"]) == 2


def test_code_row_is_the_baseline():
    from rapid_reports_ai.scripts.coverage_bakeoff import code_row
    case = {"id": "x", "scan_type": "CT", "checklist": ["LIVER", "SPLEEN"], "scratchpad": "Hepatic cyst.",
            "expected_covered": ["LIVER"], "rule": "direct-modifier", "hard": False}
    r = code_row(case)
    assert r.candidate == "code" and r.scores == {"LIVER": 1.0, "SPLEEN": 0.0} and r.error is None
    assert score([r])["code"]["exact_set_accuracy"] == 1.0
