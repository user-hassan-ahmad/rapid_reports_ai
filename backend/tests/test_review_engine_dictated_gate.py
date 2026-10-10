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


from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import jev_pass

from tests.review_engine_fakes import jev

R = ("FINDINGS:\nThere is a 2 cm mass in the right kidney. The liver is normal. The spleen is normal.\n"
     "IMPRESSION:\nRight renal mass.\n")
D = "- 2 cm right renal mass\n- Liver normal"


@pytest.mark.asyncio
async def test_off_asks_no_gate_questions(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_GATE", raising=False)
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    jp = await jev_pass.run(inp(R, D), R)
    assert not any(k.startswith("g") for _, qs in calls for k in qs)
    assert jp.gate == {} and jp.gate_error is None


@pytest.mark.asyncio
async def test_shadow_asks_every_clause_in_batches_with_the_gate_state(monkeypatch):
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"g*": {"choice": "all_stated"}}, calls=calls))
    jp = await jev_pass.run(inp(R, D), R)
    gate_calls = [(s, qs) for s, qs in calls if any(k.startswith("g") for k in qs)]
    assert all(set(qs) <= {f"g{i}" for i in range(len(jp.clauses))} for _, qs in gate_calls)
    assert sorted(k for _, qs in gate_calls for k in qs) == sorted(f"g{i}" for i in range(len(jp.clauses)))
    assert all(len(qs) <= 4 for _, qs in gate_calls)
    assert all(s.endswith("DICTATED FINDINGS:\n" + D) for s, _ in gate_calls)
    assert set(jp.gate) == {f"g{i}" for i in range(len(jp.clauses))}


@pytest.mark.asyncio
async def test_a_failed_gate_request_sets_gate_error(monkeypatch):
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    base = jev()

    async def flaky(state, qs):
        if any(k.startswith("g") for k in qs):
            raise TimeoutError("slow")
        return await base(state, qs)
    monkeypatch.setattr(rc, "_jev", flaky)
    jp = await jev_pass.run(inp(R, D), R)
    assert jp.gate_error and "TimeoutError" in jp.gate_error
    assert jp.contra_error is None            # the other requests are unaffected
