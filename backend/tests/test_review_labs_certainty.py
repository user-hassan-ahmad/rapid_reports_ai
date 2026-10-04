from rapid_reports_ai.scripts.review_labs import certainty_lab as CL


def test_questions_and_polarity():
    assert CL.question("C1n", "X.")["type"] == "noul" and CL.question("C3c", "X.")["type"] == "choice"
    assert set(CL.question("C3c", "X.")["criteria"]) == {"same", "more", "less", "cant_tell"}
    assert CL.p_overstated("C1n", {"noul": 0.8}) == 0.8
    assert abs(CL.p_overstated("C2n", {"noul": 0.8}) - 0.2) < 1e-9
    assert CL.p_overstated("C3c", {"choice": "more", "probabilities": {"more": 0.7, "same": 0.3}}) == 0.7


def test_score_counts_overstated_recall():
    rows = [{"item_id": "a", "run": 1, "arm": "C1n", "label": "more", "category": "real", "answer": {"noul": 0.9}},
            {"item_id": "b", "run": 1, "arm": "C1n", "label": "same", "category": "same", "answer": {"noul": 0.1}}]
    s = CL.score(rows, 0.3, 0.7)["C1n"]
    assert s["at_0.5"] == {"n_pos": 1, "n_neg": 1, "recall": 1.0, "false_alarm": 0.0}
