from rapid_reports_ai.scripts.jev_tool_lab.catalogue import CANT_TELL
from rapid_reports_ai.scripts.jev_tool_lab.rules import UNSURE, Condition, Rule, band, evaluate


def test_band_noul():
    assert band({"noul": 0.92}, "noul") == "yes"
    assert band({"noul": 0.7}, "noul") == "yes"
    assert band({"noul": 0.1}, "noul") == "no"
    assert band({"noul": 0.5}, "noul") == UNSURE
    assert band(0.95, "noul") == "yes"          # some responses carry a bare float
    assert band(None, "noul") == UNSURE


def test_band_choice():
    assert band({"probabilities": {"o1": 0.8, "o2": 0.15, CANT_TELL: 0.05}}, "choice") == "o1"
    assert band({"probabilities": {"o1": 0.45, "o2": 0.4, CANT_TELL: 0.15}}, "choice") == UNSURE   # margin < 0.2
    assert band({"probabilities": {"o1": 0.2, "o2": 0.1, CANT_TELL: 0.7}}, "choice") == UNSURE
    assert band({}, "choice") == UNSURE


def rule(*conds):
    return Rule(all_of=[Condition(q=q, want=w, label=l) for q, w, l in conds])


def test_evaluate_all_hold():
    r = rule(("q1", "yes", "wall"), ("q2", "yes", "septa"))
    assert evaluate(r, {"q1": "yes", "q2": "yes"}) == ("yes", [])


def test_evaluate_definite_failure_beats_unsure():
    r = rule(("q1", "yes", "wall"), ("q2", "yes", "enhancement"))
    assert evaluate(r, {"q1": UNSURE, "q2": "no"}) == ("no", ["enhancement"])


def test_evaluate_unsure_without_failure():
    r = rule(("q1", "yes", "wall"), ("q2", "yes", "enhancement"))
    assert evaluate(r, {"q1": UNSURE, "q2": "yes"}) == (UNSURE, [])


def test_evaluate_missing_question_is_unsure_and_empty_rule_is_unsure():
    assert evaluate(rule(("q9", "yes", "x")), {}) == (UNSURE, [])
    assert evaluate(Rule(all_of=[]), {"q1": "yes"}) == (UNSURE, [])


def test_evaluate_choice_condition():
    assert evaluate(rule(("q1", "o2", "thick septa")), {"q1": "o2"}) == ("yes", [])
    assert evaluate(rule(("q1", "o2", "thick septa")), {"q1": "o1"}) == ("no", ["thick septa"])
