"""The Additions "already in report" gate (spec §6.4, §6.5): drop stated, keep unsure for the adjudicator."""
from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.lanes import LaneContext
from rapid_reports_ai.review_engine.lanes.additions import AdditionsLane, brief_candidates, in_report_gate

from tests.review_engine_fakes import inp, jev

REPORT = "FINDINGS:\nThe liver is normal.\nIMPRESSION:\nNo acute finding."
OPTS = [{"id": f"o{k}", "kind": "impression", "section": "IMPRESSION", "sentence": s, "reason": ""}
        for k, s in enumerate(["Sentence A.", "Sentence B.", "Sentence C."])]


def _cands():
    i = inp(REPORT, "- x", options=OPTS)
    return i, brief_candidates(i, align(REPORT, "- x", "", i.artifacts.sections))


async def test_gate_drops_stated_and_routes_unsure(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"g0": {"noul": 0.9}, "g1": {"noul": 0.3}, "g2": {"noul": 0.05}}, calls))
    i, cs = _cands()
    out = await in_report_gate(REPORT, cs)
    assert [c.evidence["option_id"] for c in out] == ["o1", "o2"]
    assert out[0].preclassed is None and out[0].evidence["jev_unsure"] == {"question": "already_in_report"}
    assert out[1].preclassed == "minor" and "jev_unsure" not in out[1].evidence
    (state, qs), = calls
    assert state.startswith("REPORT:\n") and qs["g0"]["instructions"] == rc.Q_CONVEYS + "Sentence A."


async def test_gate_fails_open(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(rc, "_jev", boom)
    i, cs = _cands()
    assert len(await in_report_gate(REPORT, cs)) == 3


async def test_gate_empty_makes_no_call(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    assert await in_report_gate(REPORT, []) == [] and calls == []


async def test_lane_applies_gate(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"g*": {"noul": 0.9}}))
    i, _ = _cands()
    ctx = LaneContext(alignment=align(REPORT, "- x", "", i.artifacts.sections))
    assert await AdditionsLane().candidates(i, ctx) == []
