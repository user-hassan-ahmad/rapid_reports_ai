"""The decision run (Rules-step spec, "New flow" step 2): Qwen proposes, code checks every quote, Jev decides."""
import pytest

from rapid_reports_ai import template_decision_run as R
from tests.test_template_sheet_lab_prompts import CLINICAL

EX = ["Findings: LVEF 55%. ECV 28%. No previous imaging.",
      "Findings: LVEF 60%. Compared with CT of 01/01/2020.",
      "Findings: LVEF 50%. ECV 30%. No previous imaging."]


def test_prompt_is_case_agnostic():
    # "contrast" is one of the four standard study-level concepts the spec names (every modality); nothing else
    for word in CLINICAL:
        if word == "contrast":
            continue
        assert word not in R.SYSTEM.lower(), word


def test_user_prompt_numbers_the_reports():
    u = R.user_prompt(["A.", "B."], "<scan>")
    assert "SCAN TYPE: <scan>" in u and "### Report 1\nA." in u and "### Report 2\nB." in u


def test_verified_ignores_case_and_spacing_and_checks_the_cited_report():
    assert R.verified(R.Quote(report=1, text="ecv  28%"), EX)
    assert not R.verified(R.Quote(report=2, text="ECV 28%"), EX)      # not in report 2
    assert not R.verified(R.Quote(report=9, text="LVEF"), EX)
    assert not R.verified(R.Quote(report=1, text="  "), EX)


def test_check_quotes_drops_unverifiable_quotes_and_empty_candidates():
    out = R.RunOutput(
        values=[R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=1, text="LVEF 55%"), R.Quote(report=2, text="LVEF 99%")]),
                R.ValueCandidate(name="Invented", quotes=[R.Quote(report=1, text="never written")]),
                R.ValueCandidate(name='Bad "name"', quotes=[R.Quote(report=1, text="LVEF 55%")])],
        concepts=[R.ConceptWording(concept="comparison", state="none", text="No previous imaging.",
                                   quotes=[R.Quote(report=1, text="No previous imaging.")]),
                  R.ConceptWording(concept="comparison", state="compared", text="Compared with {study}.",
                                   quotes=[R.Quote(report=3, text="Compared with CT")])],
        habits=[R.HabitCandidate(finding="x", habit="y", reports=[1, 3]), R.HabitCandidate(finding="z", habit="w", reports=[2])])
    run = R.check_quotes(out, EX)
    assert [v.name for v in run.values] == ["LVEF"] and len(run.values[0].quotes) == 1
    assert [c.state for c in run.concepts] == ["none"]
    assert [h.finding for h in run.habits] == ["x"]
    assert run.dropped_quotes == 3 and run.ok
    bad = R.RunOutput(concepts=[R.ConceptWording(concept="contrast", state="none", text="x.",
                                                 quotes=[R.Quote(report=1, text="LVEF 55%")])])
    assert R.check_quotes(bad, EX).concepts == []                     # a state the concept does not have
