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
