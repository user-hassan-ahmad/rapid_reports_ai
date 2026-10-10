"""Dictated gate (spec 2026-10-10): one Jev question per report clause against the raw dictation decides whether
the clause is dictated; a tier rule decides what is highlighted. Synthetic cases only, no model calls."""
import pytest

from rapid_reports_ai.review_engine import dictated_gate as dg

from tests.review_engine_fakes import inp


def test_mode_defaults_off_and_reads_env(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_GATE", raising=False)
    assert dg.mode() == "off"
    for v, want in (("shadow", "shadow"), (" LIVE ", "live"), ("off", "off"), ("bogus", "off")):
        monkeypatch.setenv("RR_DICTATED_GATE", v)
        assert dg.mode() == want


def test_question_is_the_frozen_lab_wording():
    q = dg.q_gate("The liver is normal.")
    assert q["type"] == "choice"
    assert q["instructions"].startswith('The report says: "The liver is normal.". Compare every detail in it')
    assert set(q["criteria"]) == {"all_stated", "some_details_added", "not_stated"}


def test_state_labels_history_as_context_only():
    i = inp("FINDINGS:\nX.", "- X", history="Fall.", scan="CT head")
    s = dg.state(i)
    assert s.startswith("SCAN TYPE: CT head\n")
    assert "CLINICAL HISTORY (context only; it is NOT part of the dictated findings): Fall." in s
    assert s.endswith("DICTATED FINDINGS:\n- X")
    assert "CLINICAL HISTORY" not in dg.state(inp("FINDINGS:\nX.", "- X"))


def test_questions_are_batched_four_per_request():
    batches = dg.questions(["a", "b", "c", "d", "e"])
    assert [sorted(b) for b in batches] == [["g0", "g1", "g2", "g3"], ["g4"]]
    assert dg.questions([]) == []


@pytest.mark.parametrize("ans,want", [
    ({"probabilities": {"all_stated": 0.8, "some_details_added": 0.15, "not_stated": 0.05}}, 0.8),
    ({"choice": "all_stated"}, 1.0),
    ({"choice": "not_stated"}, 0.0),
    ({"noul": 0.4}, None),
    (None, None),
    ({"probabilities": {"all_stated": "x"}}, None),
])
def test_p_all_stated(ans, want):
    assert dg.p_all_stated(ans) == want
