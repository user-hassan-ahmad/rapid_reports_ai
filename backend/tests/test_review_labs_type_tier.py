"""Pure helpers of the statement-type / certainty-tier wording lab. Synthetic text only, no model calls."""
from rapid_reports_ai.scripts.review_labs import type_tier_lab as TL


def test_type_questions_are_choices_with_the_four_classes():
    for w in TL.TYPE_WORDINGS:
        q = TL.type_question(w, "No ascites.")
        assert q["type"] == "choice" and set(q["criteria"]) == set(TL.TYPES)
        assert '"No ascites."' in q["instructions"]


def test_tier_questions_and_relation():
    q = TL.tier_question(TL.R1.format(c="X."))
    assert q["type"] == "choice" and set(q["criteria"]) == set(TL.TIERS)
    assert TL.relation("probable", "probable") == "same"
    assert TL.relation("possible", "fact") == "upgrade"
    assert TL.relation("probable", "excluded") == "downgrade"


def test_rewrite_keeps_observation_and_finding_wording():
    assert TL.rewrite("Mild sinus mucosal thickening", "retention", "probable", "in keeping with") == \
        "Mild sinus mucosal thickening, in keeping with retention."
    assert TL.rewrite("a lucency in the rib", "a fracture", "possible", "may represent") == \
        "A lucency in the rib, which may represent a fracture."
    assert TL.rewrite("", "subtle subluxation", "fact", "plain") == "Subtle subluxation."
    assert TL.rewrite("", "perforation", "excluded", "no") == "No perforation."
    assert TL.rewrite("", "perforation", "possible", "query") == "Query perforation."


def test_tier_plan_swaps_synonyms_and_never_reuses_the_dictated_word():
    plan = TL.tier_plan("probable", "likely", "Obs")
    same = [p for p in plan if p[0] == "same"]
    assert len(same) == 2 and all(w != "likely" for _, _, w in same)
    assert ("upgrade", "fact", "representing") in plan and ("downgrade", "possible", "possibly") in plan
    plan = TL.tier_plan("possible", "possibly", "")
    assert ("upgrade", "probable", "likely") in plan and ("upgrade", "fact", "plain") in plan
    assert ("downgrade", "excluded", "no") in plan
    assert not [p for p in TL.tier_plan("fact", "plain", "Obs") if p[2] == "plain"]   # never drops the observation
    assert all(p[0] != "downgrade" for p in TL.tier_plan("excluded", "no", ""))


def test_tier_items_label_by_construction():
    items = TL.tier_items([{"sid": "s", "case_key": "b:x", "obs": "Calcified foci in the apex", "finding": "scarring",
                            "dict_tier": "probable", "dict_word": "likely", "neg_finding": "apical scarring"}])
    rels = {i["relation"] for i in items}
    assert rels == {"same", "upgrade", "downgrade"}
    for i in items:
        assert i["relation"] == TL.relation(i["dict_tier"], i["report_tier"])
        assert "scarring" in i["statement"]


def test_choice_of_and_flags():
    ans = {"choice": "probable", "probabilities": {"fact": 0.6, "probable": 0.3, "possible": 0.1, "excluded": 0.0}}
    assert TL.choice_of(ans) == "fact"                      # argmax, not the reported choice
    assert TL.choice_of(None) is None
    assert TL.tier_flag("fact", "probable") is True and TL.tier_flag("probable", "probable") is False
    assert TL.tier_flag(None, "fact") is None
    assert TL.combined(0.7, True) and not TL.combined(0.4, True) and not TL.combined(0.9, False)
    assert TL.averaged(0.8, 0.2) == 0.8


def test_type_metrics_confusion_and_gate():
    pairs = [("normal", "normal"), ("abnormal", "abnormal"), ("mixed", "abnormal"), ("not_a_finding", "normal"),
             ("normal", None)]
    m = TL.type_metrics(pairs)
    assert m["n"] == 5 and abs(m["accuracy"] - 0.4) < 1e-9
    assert abs(m["normal_vs_abnormal_acc"] - 2 / 3) < 1e-9
    assert m["confusion"]["normal"]["none"] == 1 and m["confusion"]["mixed"]["abnormal"] == 1
    assert m["positive_missed"] == 0 and m["positive_false"] == 0      # mixed → abnormal is still "positive"
    assert m["recall"]["mixed"] == 0.0


def test_flag_metrics_and_tier_decisions():
    f = TL.flag_metrics([("same", False), ("same", True), ("upgrade", True), ("downgrade", False)])
    assert f["same_false_alarm"] == 0.5 and f["upgrade_recall"] == 1.0 and f["downgrade_flagged"] == 0.0
    it = {"relation": "upgrade", "category": "upgrade:probable->fact"}
    ch = lambda c: {"probabilities": {c: 0.9}}                         # noqa: E731
    d = TL.tier_decisions(it, {"R1": ch("fact"), "D1": ch("probable"), "D2": ch("fact"),
                               "C1n": {"noul": 0.7}, "C2n": {"noul": 0.6}})
    assert d["tier_R1_D1"] is True and d["tier_R1_D2"] is False
    assert d["C1n"] is True and d["C2n"] is False
    assert d["C1n_and_tierD1"] is True and d["C1n_and_tierD2"] is False
    assert d["avg_C1n_C2n"] is True                                    # ½(0.7 + 0.4) = 0.55


def test_drift_counts_changed_sides():
    r1 = [{"item_id": "a", "answers": {"TA": {"probabilities": {"normal": 0.9}}, "C1n": {"noul": 0.6}}}]
    r2 = [{"item_id": "a", "answers": {"TA": {"probabilities": {"abnormal": 0.9}}, "C1n": {"noul": 0.7}}}]
    d = TL.drift(r1, r2, ["TA", "C1n"])
    assert d["TA"]["changed"] == 1 and d["C1n"]["changed"] == 0


def test_synthetic_stress_set_is_labelled_and_covers_every_class():
    labels = {l for _, l, _ in TL.SYNTHETIC_TYPE}
    assert labels == set(TL.TYPES)
    assert all(c.strip() and cat for c, _, cat in TL.SYNTHETIC_TYPE)
