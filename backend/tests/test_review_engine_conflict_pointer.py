"""Conflict pointer: a conflict card carries the dictated line it conflicts with, quoted, at P >= 0.80."""
import asyncio

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import conflict_pointer as cp
from rapid_reports_ai.review_engine import engine, negatives
from rapid_reports_ai.review_engine.items import ReviewItem, Span

from tests.review_engine_fakes import inp, jev
from tests.test_review_engine_brief_normals import AREPORT, ANCHORS, _ainp
from tests.test_review_engine_engine import _all_default, labels

DICT = "- Small right pleural effusion\n- No pulmonary emboli"
REPORT = "FINDINGS:\nA small right pleural effusion. No contralateral pleural effusion.\n"
CLAUSE = "No contralateral pleural effusion."


def _card(kind="check", reason="Conflicts.", pointer="", status="open", **ev):
    i = REPORT.index(CLAUSE)
    evidence = {"clause": CLAUSE, "pointer": pointer, **ev}
    if kind == "check":
        evidence["check_reason"] = "conflict"
    return ReviewItem(key="k", report_id="r", run_id="u", lane="accuracy", kind=kind, cls="minor", reason=reason,
                      anchor=Span(start=i, end=i + len(CLAUSE), text=CLAUSE), evidence=evidence, status=status)


def _ans(top, p, none=0.0):
    probs = {"d0": 0.0, "d1": 0.0, "none": none}
    probs[top] = p
    return {"choice": top, "probabilities": probs}


def _run(monkeypatch, answer, items, calls=None):
    monkeypatch.setattr(rc, "_jev", jev({"p*": answer}, calls))
    return asyncio.run(cp.annotate(inp(REPORT, DICT), items))


def test_quote_goes_to_evidence_not_reason_at_threshold(monkeypatch):
    it = _card()
    log = _run(monkeypatch, _ans("d0", 0.80, 0.05), [it])
    assert it.reason == "Conflicts."
    assert it.evidence["pointer"] == it.evidence["dictated_quote"] == "Small right pleural effusion"
    assert it.evidence["conflict_pointer"] == {"line": "Small right pleural effusion", "p": 0.80, "p_none": 0.05}
    assert log == {"asked": 1, "quoted": 1, "weak": 0, "error": None}


def test_placeholder_pointer_counts_as_empty(monkeypatch):
    it = _card(pointer="->")
    _run(monkeypatch, _ans("d0", 0.9), [it])
    assert it.evidence["dictated_quote"] == "Small right pleural effusion"


def test_quote_not_shown_below_threshold_but_recorded(monkeypatch):
    it = _card()
    log = _run(monkeypatch, _ans("d0", 0.79, 0.30), [it])
    assert "dictated_quote" not in it.evidence and not it.evidence["pointer"] and it.reason == "Conflicts."
    assert it.evidence["conflict_pointer"]["p"] == 0.79 and it.evidence["conflict_pointer"]["p_none"] == 0.30
    assert log["quoted"] == 0 and log["weak"] == 1


def test_existing_pointer_that_agrees_is_kept_with_no_quote(monkeypatch):
    it = _card(pointer="small right pleural effusion")
    log = _run(monkeypatch, _ans("d0", 0.9), [it])
    assert it.evidence["pointer"] == "small right pleural effusion" and "dictated_quote" not in it.evidence
    assert it.evidence["conflict_pointer"]["agrees"] is True and log["quoted"] == 0


def test_brief_card_with_a_disagreeing_pointer_shows_jevs_line(monkeypatch):
    # live case: the brief's pointer named a weaker finding; Jev's confident line is the real reason
    it = _card(pointer="No pulmonary emboli", source="brief", reason="Stated by the AI as normal, but a check ...")
    log = _run(monkeypatch, _ans("d0", 0.97), [it])
    ev = it.evidence
    assert ev["dictated_quote"] == ev["pointer"] == "Small right pleural effusion"
    assert ev["pointer_prior"] == "No pulmonary emboli"
    assert ev["conflict_pointer"]["agrees"] is False and ev["conflict_pointer"]["overridden"] is True
    assert it.reason == "Stated by the AI as normal, but a check ..." and log["quoted"] == 1


def test_brief_card_reason_naming_the_old_finding_is_made_neutral(monkeypatch):
    # the reason said why it was added (the old pointer); with Jev's quote beside it, it read as two findings
    reason = ("Added by the AI because it bears on your finding: No pulmonary emboli, but a check found it may "
              "contradict your dictation. Remove it, or dismiss to keep it.")
    it = _card(pointer="No pulmonary emboli", source="brief", reason=reason)
    _run(monkeypatch, _ans("d0", 0.97), [it])
    assert "pulmonary emboli" not in it.reason
    assert it.reason == ("Added by the AI, but a check found it may contradict your dictation. Remove it, or "
                         "dismiss to keep it.")
    assert it.evidence["dictated_quote"] == "Small right pleural effusion"


def test_negatives_card_with_a_disagreeing_pointer_is_rebuilt_on_jevs_line(monkeypatch):
    label, reason = negatives.check_text("conflict", "No pulmonary emboli")
    it = _card(pointer="No pulmonary emboli", reason=reason)
    it.label = label
    _run(monkeypatch, _ans("d0", 0.95), [it])
    assert "pulmonary emboli" not in it.reason and "pulmonary emboli" not in it.label
    assert "Small right pleural effusion" in it.reason
    assert "dictated_quote" not in it.evidence        # the rebuilt reason already quotes it: no second quote
    assert it.evidence["pointer"] == "Small right pleural effusion"
    assert it.evidence["pointer_prior"] == "No pulmonary emboli"


def test_disagreeing_pointer_below_threshold_is_left_alone(monkeypatch):
    it = _card(pointer="No pulmonary emboli", source="brief")
    _run(monkeypatch, _ans("d0", 0.79), [it])
    assert it.evidence["pointer"] == "No pulmonary emboli" and "dictated_quote" not in it.evidence
    assert "pointer_prior" not in it.evidence


def test_quotes_in_the_clause_are_replaced():
    assert 'say "x"' not in cp.q_pointer('say "x"', ["a"])["instructions"]
    assert "say ”x”" in cp.q_pointer('say "x"', ["a"])["instructions"]


def test_none_top_answer_gives_no_quote(monkeypatch):
    it = _card()
    log = _run(monkeypatch, _ans("d0", 0.3, 0.95), [it])
    assert it.reason == "Conflicts." and "dictated_quote" not in it.evidence
    assert it.evidence["conflict_pointer"]["line"] is None and it.evidence["conflict_pointer"]["p_none"] == 0.95
    assert log["quoted"] == 0 and log["weak"] == 1


def test_contradicted_card_uses_the_clause_and_one_batched_call(monkeypatch):
    calls = []
    a, b = _card(kind="contradicted"), _card(kind="check")
    ignored = [_card(status="dismissed"), _card(check_reason="uncertain")]
    ignored[1].evidence["check_reason"] = "uncertain"
    log = _run(monkeypatch, _ans("d1", 0.9), [a, b] + ignored, calls)
    assert len(calls) == 1 and set(calls[0][1]) == {"p0", "p1"} and log["asked"] == 2 and log["quoted"] == 2
    q = calls[0][1]["p0"]
    assert CLAUSE in q["instructions"] and q["criteria"]["d1"] == "No pulmonary emboli" and "none" in q["criteria"]
    assert a.evidence["dictated_quote"] == "No pulmonary emboli" and "dictated_quote" not in ignored[0].evidence


def test_jev_exception_leaves_items_unchanged(monkeypatch):
    async def boom(state, qs):
        raise RuntimeError("down")
    monkeypatch.setattr(rc, "_jev", boom)
    it = _card()
    before = it.model_dump()
    log = asyncio.run(cp.annotate(inp(REPORT, DICT), [it]))
    assert it.model_dump() == before and log["error"].startswith("RuntimeError") and log["quoted"] == 0


def test_no_call_without_cards_or_lines(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    assert asyncio.run(cp.annotate(inp(REPORT, DICT), [_card(status="applied")]))["asked"] == 0
    assert asyncio.run(cp.annotate(inp(REPORT, ""), [_card()]))["asked"] == 0
    assert calls == []


@pytest.mark.asyncio
async def test_engine_run_attaches_the_quote_to_a_brief_conflict_card(monkeypatch):
    qc = {"anchors": ANCHORS, "brief_conflicts": [
        {"clause": "No contralateral pleural effusion.", "refs": ["neg:1"], "reason": "brief_kept", "score": 0.8,
         "source": "finding:Pleural effusion", "pointer": ""}]}
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"p0": _ans("d0", 0.9)}, calls))
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(_all_default))
    res = await engine.run_review(_ainp(qc), run_id="00000000-0000-0000-0000-0000000000f1")
    card = next(i for i in res.items if i.kind == "check" and (i.evidence or {}).get("check_reason") == "conflict")
    assert card.evidence["dictated_quote"] == "Small right pleural effusion"
    assert res.run["conflict_pointer"]["quoted"] == 1 and "conflict_pointer_ms" in res.run["timings_ms"]
