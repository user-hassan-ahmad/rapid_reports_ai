from rapid_reports_ai.scripts.jev_tool_lab.catalogue import CANT_TELL, QuestionSpec
from rapid_reports_ai.scripts.jev_tool_lab.rules import UNSURE, Condition, Rule, band, evaluate, validate_rule


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


def test_band_choice_nan_is_unsure():
    assert band({"probabilities": {"o1": float("nan"), "o2": 0.1}}, "choice") == UNSURE


def test_condition_want_normalised():
    assert Condition(q="q1", want="True", label="x").want == "yes"
    assert Condition(q="q1", want=" No ", label="x").want == "no"
    assert Condition(q="q1", want="O2", label="x").want == "o2"


def test_validate_rule():
    specs = [QuestionSpec(id="q1", type="T2", source="dictation", topic="septa"),
             QuestionSpec(id="q2", type="T4", source="dictation", item="x", options=["a", "b"])]
    assert validate_rule(rule(("q1", "yes", "s"), ("q2", "o2", "t")), specs) is None
    assert validate_rule(rule(("q9", "yes", "s")), specs) == "rule names unknown question q9"
    assert validate_rule(rule(("q2", "o7", "t")), specs) == "bad want 'o7' for q2"
    assert validate_rule(rule(("q1", "o1", "s")), specs) == "bad want 'o1' for q1"
    assert validate_rule(rule(("q1", "maybe", "s")), specs) == "bad want 'maybe' for q1"
    assert validate_rule(Rule(all_of=[]), specs) == "empty rule"
