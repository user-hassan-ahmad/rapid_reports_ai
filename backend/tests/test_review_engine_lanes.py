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
    # clauses: 0 "The liver is normal." (normal), 1 cyst (positive), 2 "No free fluid." (negative), 3 impression.
    # Asked of every non-negative clause; the type gate (JevPass.keeps) decides which answers count.
    assert set(qs) == {f"{k}{n}" for k in ("sup", "cer", "dt") for n in (0, 1, 3)}
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


def _tier(choice):
    return {"type": "choice", "choice": choice,
            "probabilities": {c: (1.0 if c == choice else 0.0) for c in jev_pass.DICT_TIERS}}


async def test_accuracy_overstated_by_tier_or_fact_c1n_never_c1n_alone(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"cer1": {"noul": 0.1}, "dt1": _tier("probable"),     # fact > probable
                                        "cer3": {"noul": 0.8}, "dt3": _tier("fact")})         # fact = fact, C1n
    cs = [c for c in await AccuracyLane().candidates(i, ctx) if c.detector == "jev.certainty"]
    assert [(c.kind, c.evidence["rule"]) for c in cs] == [("overstated", "tier"), ("overstated", "fact_c1n")]
    ctx = await ctx_for(monkeypatch, i, {"cer*": {"noul": 0.95}, "dt*": _tier("not_stated")})
    assert not [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "overstated"]


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


# ── finding-negative options placed in context (after the sentence of their finding) ──
PANC = ("FINDINGS:\nThe liver is normal. There is a 32 mm hypoattenuating mass in the pancreatic head abutting the SMV. "
        "The pancreatic duct is dilated. The spleen is normal.\n\nThe kidneys are normal.\nIMPRESSION:\n"
        "Pancreatic head mass.")


def _fn(text, finding):
    return {"id": "fn0", "kind": "finding_negative", "section": "FINDINGS", "sentence": text, "finding": finding}


def test_finding_negative_lands_after_its_finding_sentence():
    i = inp(PANC, "- pancreatic head mass abutting SMV",
            options=[_fn("No splenic vein thrombosis.", "pancreatic head mass/SMV")])
    c = brief_candidates(i, align(PANC, "", "", i.artifacts.sections))[0]
    want = "There is a 32 mm hypoattenuating mass in the pancreatic head abutting the SMV."
    assert c.proposed.after == want and c.preclassed == "minor"
    out = apply_edit(PANC, c.proposed, i.artifacts.sections)
    assert want + " No splenic vein thrombosis. The pancreatic duct is dilated." in out
    from rapid_reports_ai.review_engine.verifier import guard_failures
    assert guard_failures(PANC, c.proposed, "option", "", "", additions=True, sections=i.artifacts.sections,
                          item_section="FINDINGS", extra_source="No splenic vein thrombosis.",
                          option_sentence="No splenic vein thrombosis.") == []


def test_finding_negative_without_confident_match_goes_to_section_end():
    i = inp(PANC, "", options=[_fn("No ascites.", "Peritoneal deposit")])
    c = brief_candidates(i, align(PANC, "", "", i.artifacts.sections))[0]
    assert c.proposed.after is None and c.proposed.section == "FINDINGS"


def test_finding_negative_with_ambiguous_match_goes_to_section_end():
    rep = ("FINDINGS:\nA pancreatic head mass measures 30 mm. A second pancreatic head mass measures 12 mm.\n"
           "IMPRESSION:\nPancreatic masses.")
    i = inp(rep, "", options=[_fn("No splenic vein thrombosis.", "Pancreatic head mass")])
    c = brief_candidates(i, align(rep, "", "", i.artifacts.sections))[0]
    assert c.proposed.after is None


def test_finding_negative_never_anchors_outside_its_section():
    i = inp(PANC, "", options=[_fn("No splenic vein thrombosis.", "Pancreatic head mass")])
    i.artifacts.report = PANC.replace("There is a 32 mm hypoattenuating mass in the pancreatic head abutting the SMV. ",
                                      "")
    c = brief_candidates(i, align(i.artifacts.report, "", "", i.artifacts.sections))[0]
    assert c.proposed.after is None             # the IMPRESSION "Pancreatic head mass." is not a FINDINGS anchor


# The brief's finding key is the skill sheet's category label ("Vascular involvement"), often sharing < 2 stems with
# any report sentence (prod 2026-10-06: every finding_negative option fell to the FINDINGS end). The option's own
# words then place it, with the same threshold and uniqueness rules. Synthetic equivalent of that report:
REN = ("FINDINGS:\nThe left kidney contains a 4.1 cm enhancing mass, likely renal cell carcinoma. The mass abuts the "
       "left renal vein over a short segment. No encasement of the left renal vein or inferior vena cava, and no "
       "involvement of the adrenal gland. No lymphadenopathy. The liver is unremarkable.\n\n"
       "The spleen is unremarkable.\nIMPRESSION:\nLeft renal mass.")
REN_VASC = ("No encasement of the left renal vein or inferior vena cava, and no involvement of the adrenal gland.")


@pytest.mark.parametrize("sentence", ["No inferior vena cava thrombosis.", "No renal vein tumour thrombus."])
def test_category_key_falls_back_to_the_options_own_words(sentence):
    i = inp(REN, "- 4.1 cm renal mass abutting the renal vein", options=[_fn(sentence, "Vascular involvement")])
    c = brief_candidates(i, align(REN, "", "", i.artifacts.sections))[0]
    assert c.proposed.after == REN_VASC
    out = apply_edit(REN, c.proposed, i.artifacts.sections)
    assert f"{REN_VASC} {sentence} No lymphadenopathy." in out


def test_option_words_fallback_keeps_the_uniqueness_rule():
    # "renal vein" is in two sentences equally (2 stems each): no unique sentence → section end
    i = inp(REN, "", options=[_fn("No left renal vein thrombosis.", "Tumour extent")])
    c = brief_candidates(i, align(REN, "", "", i.artifacts.sections))[0]
    assert c.proposed.after is None and c.proposed.section == "FINDINGS"


def test_finding_key_match_wins_over_option_words():
    i = inp(PANC, "", options=[_fn("No duct dilatation.", "pancreatic head mass/SMV")])
    c = brief_candidates(i, align(PANC, "", "", i.artifacts.sections))[0]
    assert c.proposed.after == "There is a 32 mm hypoattenuating mass in the pancreatic head abutting the SMV."


def test_recommendation_option_keeps_section_end_even_with_finding():
    i = inp(PANC, "", options=[{"id": "o1", "kind": "recommendation", "section": "IMPRESSION",
                                "sentence": "MDT discussion is suggested.", "finding": "pancreatic head mass"}])
    c = brief_candidates(i, align(PANC, "", "", i.artifacts.sections))[0]
    assert c.proposed.after is None and c.proposed.section == "IMPRESSION"


# ── S4 classification / guideline items placed inline (after the finding's sentence) ──
def _s4_item(edit_section, edit_after=None, finding="Pancreatic head mass"):
    from rapid_reports_ai.review_engine import adjudicator as adj
    from rapid_reports_ai.review_engine import engine
    syn = {"guidelines": [{"finding": finding, "finding_number": 1,
                           "classifications": [{"system": "NCCN", "grade": "borderline resectable"}]}]}
    c = s4_candidates(syn)[0]
    j = adj.Judgement(cls="minor", kind="grade", label="Resectability", reason="r", edit_mode="insert",
                      edit_replace="NCCN: borderline resectable.", edit_after=edit_after, edit_section=edit_section)
    i = inp(PANC, "", synthesis=syn)
    return i, engine.build_item(i, "00000000-0000-0000-0000-0000000000a1", adj.Outcome(group=[c], judgement=j))


def test_s4_grade_insert_lands_after_its_finding_sentence():
    i, it = _s4_item("FINDINGS", edit_after="The kidneys are normal.")
    want = "There is a 32 mm hypoattenuating mass in the pancreatic head abutting the SMV."
    assert it.edit.after == want and it.edit.section == "FINDINGS"
    out = apply_edit(PANC, it.edit, i.artifacts.sections)
    assert want + " NCCN: borderline resectable. The pancreatic duct is dilated." in out


def test_s4_grade_insert_without_confident_match_goes_to_section_end():
    _, it = _s4_item("FINDINGS", edit_after="The kidneys are normal.", finding="Peritoneal deposit")
    assert it.edit.after is None and it.edit.section == "FINDINGS"


def test_s4_grade_insert_in_impression_keeps_section_end():
    _, it = _s4_item("IMPRESSION", edit_after="Pancreatic head mass.")
    assert it.edit.after is None and it.edit.section == "IMPRESSION"


def test_brief_option_items_are_not_reanchored():
    from rapid_reports_ai.review_engine import adjudicator as adj
    from rapid_reports_ai.review_engine import engine
    i = inp(PANC, "", options=[{"id": "o1", "kind": "impression", "section": "FINDINGS",
                                "sentence": "No ascites.", "finding": "pancreatic head mass"}])
    c = brief_candidates(i, align(PANC, "", "", i.artifacts.sections))[0]
    it = engine.build_item(i, "00000000-0000-0000-0000-0000000000a2", adj.Outcome(group=[c]))
    assert it.edit.after is None
