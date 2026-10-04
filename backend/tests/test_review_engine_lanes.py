"""Lanes (spec §6): coverage, accuracy and additions over the shared Jev pass, with unsure routing (§6.5)."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.report_review import checked_clauses
from rapid_reports_ai.review_engine import jev_pass
from rapid_reports_ai.review_engine.alignment import Pair, align
from rapid_reports_ai.review_engine.checks import run_checks
from rapid_reports_ai.review_engine.lanes import LaneContext, confident, registry
from rapid_reports_ai.review_engine.lanes.accuracy import AccuracyLane
from rapid_reports_ai.review_engine.lanes.additions import AdditionsLane, brief_candidates, s4_candidates
from rapid_reports_ai.review_engine.lanes.coverage import CoverageLane
from rapid_reports_ai.review_engine.verifier import apply_edit

from tests.review_engine_fakes import inp, jev

REPORT = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst. No free fluid.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst with a thin septation\n- Liver normal"
SEL_NORMAL = {"choice": "normal_or_negative", "probabilities": {"abnormal_finding": 0.05, "limitation": 0.0,
              "normal_or_negative": 0.9, "protocol_note": 0.05, "comparison": 0.0, "mixed_abnormal_and_normal": 0.0}}


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("unstubbed Jev call")
    monkeypatch.setattr(rc, "_jev", boom)


async def ctx_for(monkeypatch, i, over=None):
    monkeypatch.setattr(rc, "_jev", jev(over))
    a = i.artifacts
    al = align(a.report, a.dictated_findings, i.clinical_history, a.sections)
    jp = await jev_pass.run(i, a.report)
    return LaneContext(alignment=al, jev=jp, checks=run_checks(a.report, a.dictated_findings, "", i.scan_type, al))


def _state_key(s: str) -> str:
    return "HISTORY" if "\nCLINICAL HISTORY:" in s else s.split(":")[0]


async def test_jev_pass_asks_todays_questions(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    jp = await jev_pass.run(inp(REPORT, DICT, history="Flank pain."), REPORT)
    states = {_state_key(s): qs for s, qs in calls}
    assert {"c0", "sel0", "lt0"} <= set(states["SCAN TYPE"]) and "i0" in states["REPORT"]
    assert not any(k.startswith(("sup", "cer")) for k in states["SCAN TYPE"])     # today's request unchanged
    assert jp.items == ["14 mm left renal cyst with a thin septation", "Liver normal"] and not jp.contra_error


async def test_jev_pass_asks_w1n_c1n_of_positive_clauses_with_history(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    await jev_pass.run(inp(REPORT, DICT, history="Flank pain."), REPORT)
    state, qs = next((s, q) for s, q in calls if _state_key(s) == "HISTORY")
    assert "CLINICAL HISTORY: Flank pain." in state and "DICTATED FINDINGS:\n- 14 mm" in state
    # clauses: 0 "The liver is normal." (normal), 1 cyst (positive), 2 "No free fluid." (negative), 3 impression
    assert set(qs) == {"sup1", "cer1", "sup3", "cer3"}
    assert qs["sup1"]["instructions"].startswith("The dictated findings report this finding, including as a possibility")
    assert qs["cer1"]["instructions"].startswith('Read only this one report statement: "A 14 mm left renal cyst."')


async def test_coverage_partial_with_missing_detail(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"sel1": SEL_NORMAL, "lt1": {"noul": 0.1},
                                        "i0": {"choice": "partial", "probabilities": {"partial": 0.8, "stated": 0.2}}})
    cs = await CoverageLane().candidates(i, ctx)
    assert [(c.kind, c.line_id) for c in cs] == [("partial", "d0")]
    assert cs[0].evidence["missing_detail"] == "thin septation" and cs[0].anchor and cs[0].detector == "jev.classify_first"


async def test_coverage_unsure_names_question_not_leaning(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"sel1": SEL_NORMAL, "lt1": {"noul": 0.1},
                                        "i0": {"choice": "stated", "probabilities": {"stated": 0.5, "partial": 0.45}}})
    cs = await CoverageLane().candidates(i, ctx)
    assert cs[0].kind == "coverage_check" and cs[0].evidence == {"jev_unsure": {"question": "classify_first"}}


async def test_coverage_skips_dictated_negatives_and_unclear(monkeypatch):
    i = inp(REPORT, "- No free fluid\n- Heading:")
    ctx = await ctx_for(monkeypatch, i, {"i*": {"choice": "unclear", "probabilities": {"unclear": 0.9}}})
    assert await CoverageLane().candidates(i, ctx) == []


def test_only_confident_pairs_anchor():
    assert confident(Pair(line_id="d0", clause_id="c0", score=0.35, how="number"))
    assert not confident(Pair(line_id="d0", clause_id="c0", score=0.35, how="lexical"))
    assert not confident(Pair(line_id="d0", clause_id="c0", score=0.9, how="level_conflict"))


async def test_accuracy_negative_contradiction_gets_code_removal(monkeypatch):
    i = inp(REPORT, "- Free fluid in the pelvis\n- 14 mm left renal cyst")
    k = checked_clauses(REPORT, None).index("No free fluid.")      # the Jev pass's own clause order
    ctx = await ctx_for(monkeypatch, i, {f"c{k}": {"noul": 0.8}, f"r{k}": {"noul": 0.9}, f"d{k}": {"noul": 0.1}})
    cs = [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "contradicted"]
    e = cs[0].proposed
    # code's fix (verifier._negative_fix): a whole-sentence remove, so it can qualify for pre-apply (correction 12)
    assert cs[0].code_fix and cs[0].pre_apply and e.mode == "remove" and e.find == "No free fluid."
    after = apply_edit(REPORT, e)
    assert "No free fluid" not in after and "A 14 mm left renal cyst." in after   # the rest of the line is kept


async def test_accuracy_negative_list_item_gets_code_replace(monkeypatch):
    rep = "FINDINGS:\nNo free fluid, lymphadenopathy or ascites. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
    i = inp(rep, "- Free fluid in the pelvis\n- 14 mm left renal cyst")
    k = checked_clauses(rep, None).index("No free fluid")
    ctx = await ctx_for(monkeypatch, i, {f"c{k}": {"noul": 0.8}, f"r{k}": {"noul": 0.9}, f"d{k}": {"noul": 0.1}})
    c = next(c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "contradicted")
    assert c.code_fix and c.proposed.mode == "replace" and "free fluid" not in c.proposed.replace.lower()
    assert "lymphadenopathy" in c.proposed.replace and "ascites" in c.proposed.replace


async def test_accuracy_keeps_a_dictated_negative(monkeypatch):
    i = inp(REPORT, "- No free fluid\n- 14 mm left renal cyst")
    k = checked_clauses(REPORT, None).index("No free fluid.")
    ctx = await ctx_for(monkeypatch, i, {f"c{k}": {"noul": 0.8}, f"r{k}": {"noul": 0.9}, f"d{k}": {"noul": 0.9}})
    assert not [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "contradicted"]


async def test_accuracy_positive_and_unsure(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"c1": {"noul": 0.7}, "c0": {"noul": 0.5}})
    cs = [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "contradicted"]
    pos = [c for c in cs if not c.evidence.get("jev_unsure")]
    uns = [c for c in cs if c.evidence.get("jev_unsure")]
    assert pos and pos[0].proposed is None and not pos[0].code_fix and not pos[0].pre_apply
    assert uns and uns[0].evidence == {"jev_unsure": {"question": "contradiction"}}


async def test_accuracy_w1n_unsupported_and_unsure(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"sup1": {"noul": 0.2}, "sup3": {"noul": 0.45}})
    cs = [c for c in await AccuracyLane().candidates(i, ctx) if c.detector == "jev.supported"]
    assert [(c.kind, c.anchor.text) for c in cs] == [("unsupported", "A 14 mm left renal cyst."),
                                                      ("unsupported", "Left renal cyst.")]
    assert cs[0].evidence["score"] == 0.2 and cs[1].evidence == {"jev_unsure": {"question": "supported"}}
    assert all(c.proposed is None and not c.pre_apply for c in cs)


async def test_accuracy_c1n_overstated_and_unsure(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"cer1": {"noul": 0.8}, "cer3": {"noul": 0.42}})
    cs = [c for c in await AccuracyLane().candidates(i, ctx) if c.detector == "jev.certainty"]
    assert [c.kind for c in cs] == ["overstated", "overstated"]
    assert cs[0].evidence["score"] == 0.8 and cs[1].evidence == {"jev_unsure": {"question": "certainty"}}


async def test_accuracy_quiet_when_supported_and_not_overstated(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"sup*": {"noul": 0.9}, "cer*": {"noul": 0.1}})
    assert not [c for c in await AccuracyLane().candidates(i, ctx) if c.detector.startswith("jev.")]


async def test_accuracy_support_request_failure_drops_only_w1n_c1n(monkeypatch):
    i = inp(REPORT, DICT)

    async def fake(state, qs):
        if "\nCLINICAL HISTORY:" in state:
            raise TimeoutError("slow")
        return await jev({"c1": {"noul": 0.7}})(state, qs)
    monkeypatch.setattr(rc, "_jev", fake)
    a = i.artifacts
    al = align(a.report, a.dictated_findings, "", a.sections)
    jp = await jev_pass.run(i, a.report)
    assert jp.support_error and not jp.contra_error
    cs = await AccuracyLane().candidates(i, LaneContext(alignment=al, jev=jp))
    assert [c.detector for c in cs] == ["jev.contradiction"]


async def test_accuracy_forwards_code_checks(monkeypatch):
    rep = "FINDINGS:\nThe CBD measures 6 mm.\nIMPRESSION:\nNormal."
    i = inp(rep, "- CBD not dilated")
    ctx = await ctx_for(monkeypatch, i)
    assert ("unsupported", "code.numbers") in [(c.kind, c.detector) for c in await AccuracyLane().candidates(i, ctx)]


def test_registry_has_three_lanes():
    assert [l.name for l in registry()] == ["coverage", "accuracy", "additions"]


def test_brief_options_preclassed_minor_with_probe():
    i = inp(REPORT, DICT, options=[{"id": "o1", "kind": "recommendation", "section": "IMPRESSION",
                                    "sentence": "Follow-up ultrasound is suggested.", "reason": "r"}])
    al = align(REPORT, DICT, "", i.artifacts.sections)
    c = brief_candidates(i, al)[0]
    assert c.preclassed == "minor" and c.probe.startswith(rc.Q_CONVEYS) and c.detector == "brief.option"
    assert c.proposed.mode == "insert" and c.proposed.after is None and c.proposed.section == "IMPRESSION"


def test_finding_negative_on_normal_structure_goes_to_adjudicator():
    i = inp(REPORT, DICT, options=[{"id": "o2", "kind": "finding_negative", "section": "FINDINGS",
                                    "sentence": "No focal liver lesion.", "reason": ""}])
    al = align(REPORT, DICT, "", i.artifacts.sections)
    c = brief_candidates(i, al)[0]
    assert c.preclassed is None and c.evidence["upgrade_target"] == "The liver is normal." and c.anchor


async def test_additions_lane_combines_producers():
    i = inp(REPORT, DICT, options=[{"id": "o1", "kind": "recommendation", "section": "IMPRESSION",
                                    "sentence": "Follow-up ultrasound is suggested.", "reason": "r"}])
    al = align(REPORT, DICT, "", i.artifacts.sections)
    cs = await AdditionsLane().candidates(i, LaneContext(alignment=al))
    assert [c.detector for c in cs] == ["brief.option"]


def test_s4_mapping():
    assert s4_candidates(None) == []
    card = {"finding_number": 1, "finding": "renal cyst", "finding_short_label": "Renal cyst",
            "classifications": [{"system": "Bosniak 2019", "grade": "II", "criteria": "c"}],
            "thresholds": [], "follow_up_actions": [{"modality": "US", "timing": "6 months", "indication": "i"}],
            "differentials": [], "imaging_flags": [], "sources": [{"url": "u", "title": "t"}]}
    cs = s4_candidates({"guidelines": [card]})
    assert [c.kind for c in cs] == ["grade", "follow_up"] and cs[0].citation == {"card": 1, "source": "u", "label": "t"}
    assert "criteria" not in cs[0].evidence
