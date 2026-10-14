"""Template gap flags (review_engine/template_gaps.py), built from the CTCA guided grammar sheet."""
from pathlib import Path

import pytest

from rapid_reports_ai.review_engine import template_gaps as tg
from rapid_reports_ai.review_engine.template_text import template_inputs
from tests.review_engine_fakes import inp

RUN = "00000000-0000-0000-0000-0000000000f1"
CFG = {"generation_mode": "skill_sheet_guided",
       "skill_sheet": (Path(__file__).parent / "fixtures" / "template_pipeline" / "ctca.md").read_text()}

CAC = ("Prospective ECG-gated coronary calcium scoring was performed initially using a Siemens Dual Source Flash "
       "multidetector scanner.")
AXIAL = ("Axial cross sections of the heart were acquired with the patient in the supine position upon inspiratory "
         "breath hold.")
NORMALS = ["LMS: Normal.", "LAD: Normal proximal, mid and distal LAD.", "LCx: Normal proximal and distal LCx.",
           "RCA: Normal proximal, mid and distal RCA."]
REPORT = f"""Coronary calcium scoring:
{CAC} The Agatston score is 0.

CTCA Procedure:
Prospective ECG gated coronary CT angiography was performed using a Siemens Dual Source Flash multidetector scanner. \
{AXIAL} A separate workstation was used for 3D reformation of the dataset.
Medication given: GTN 800 mcg.
Scan quality: Good
Average HR: 58 bpm.
Total radiation dose: 210.5 mGycm.

Coronary Findings:
Right coronary dominance with normal coronary artery origins.
{chr(10).join(NORMALS)}

Other findings:
Normal appearance of the cardiac chambers. No left atrial appendage thrombus. No suspicious parenchymal nodules. \
No mediastinal or hilar lymph enlargement. No pleural or pericardial effusion. Normal calibre aortic root and \
pulmonary trunk. Normal upper abdominal viscera. No aggressive osseous lesion.

Conclusion:
The Agatston score is 0 with no evidence of coronary artery disease.
"""
DICT = "Calcium score 0. GTN 800. Good quality. HR 58. DLP 210.5. Right dominant. Normal coronaries."


def _inp(report=REPORT, assumed=NORMALS, removed=(), template=True):
    i = inp(report, DICT, pathway="templated" if template else "quick")
    if not template:
        return i
    texts, st = template_inputs(CFG)
    assert st is not None
    return i.model_copy(update={"template_text": texts, "template_structure": st, "assumed_normals": list(assumed),
                                "removed": list(removed)})


def _flags(i):
    items, log = tg.gap_items(i, RUN)
    return [(it.kind, it.evidence["text"]) for it in items], log, items


def test_the_clean_ctca_report_has_no_gap():
    flags, log, _ = _flags(_inp())
    assert flags == []
    assert log["error"] is None and all(log[k] == 0 for k in tg.KINDS)


def test_quick_reports_are_untouched():
    assert tg.gap_items(_inp(template=False), RUN) == ([], None)


@pytest.mark.parametrize("old,new,want", [
    ("Average HR: 58 bpm.", "Average HR:  bpm.", ("template_slot_empty", "Average HR")),
    ("Average HR: 58 bpm.", "Average HR: {rate} bpm.", ("template_slot_empty", "{rate}")),
    ("Scan quality: Good", "Scan quality:", ("template_slot_empty", "Scan quality")),
])
def test_an_empty_slot_or_a_left_placeholder_is_flagged(old, new, want):
    flags, log, items = _flags(_inp(REPORT.replace(old, new)))
    assert flags == [want]
    assert items[0].anchor is not None and items[0].cls == "info" and items[0].edit is None
    assert items[0].label.startswith("Template field left empty")


def test_a_missing_fixed_sentence_is_flagged_sentence_by_sentence():
    flags, _, _ = _flags(_inp(REPORT.replace(AXIAL + " ", "")))
    assert flags == [("fixed_text_missing", AXIAL)]


def test_a_fixed_line_replaced_by_its_rule_is_not_flagged_but_a_dropped_one_is():
    replaced = REPORT.replace(CAC, "Coronary calcium scoring was not performed due to patient age.")
    assert _flags(_inp(replaced))[0] == []
    flags, _, _ = _flags(_inp(REPORT.replace(CAC + " ", "")))
    assert flags == [("fixed_text_missing", CAC)]


def test_a_fixed_sentence_the_radiologist_removed_is_not_flagged():
    assert _flags(_inp(REPORT.replace(AXIAL + " ", ""), removed=[AXIAL]))[0] == []


def test_a_dropped_confirmed_normal_is_flagged_unless_removed():
    lcx = NORMALS[2]
    report = REPORT.replace(lcx + "\n", "")
    assert _flags(_inp(report))[0] == [("assumed_normal_missing", lcx)]
    assert _flags(_inp(report, assumed=[n for n in NORMALS if n != lcx]))[0] == []


def test_a_lost_heading_is_flagged_only_when_its_paragraph_has_content():
    flags, _, items = _flags(_inp(REPORT.replace("Other findings:\n", "")))
    assert flags == [("heading_missing", "Other findings:")]
    assert items[0].anchor is not None
    start = REPORT.index("Coronary Findings:")
    gone = REPORT[:start] + REPORT[REPORT.index("Other findings:"):]        # the whole paragraph omitted
    assert _flags(_inp(gone, assumed=[]))[0] == []


def test_gap_flags_are_capped_and_counted():
    report = REPORT
    for n in NORMALS:
        report = report.replace(n + "\n", "")
    report = report.replace(AXIAL + " ", "").replace("Average HR: 58 bpm.", "Average HR:  bpm.")
    report = report.replace("Other findings:\n", "").replace("Coronary Findings:\n", "")
    flags, log, _ = _flags(_inp(report))
    assert len(flags) == tg.MAX_GAPS
    assert log["assumed_normal_missing"] == 4 and log["fixed_text_missing"] == 1 and log["template_slot_empty"] == 1
    assert log["capped"] == sum(log[k] for k in tg.KINDS) - tg.MAX_GAPS


def test_malformed_structure_fails_open():
    i = _inp().model_copy(update={"template_structure": {"rules": "x", "fixed_blocks": [1, None]}})
    items, log = tg.gap_items(i, RUN)
    assert items == []


@pytest.mark.asyncio
async def test_run_review_carries_gap_flags_and_their_log(monkeypatch):
    from rapid_reports_ai import report_reconcile as rc
    from rapid_reports_ai.review_engine import adjudicator as adj
    from rapid_reports_ai.review_engine import engine, negatives
    from tests.review_engine_fakes import jev

    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}

    async def judge(inp_, groups):
        return [adj.Outcome(group=g) for g in groups]
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)
    monkeypatch.setattr(adj, "adjudicate", judge)
    res = await engine.run_review(_inp(REPORT.replace(AXIAL + " ", "")), RUN)
    gaps = [i for i in res.items if i.kind in tg.KINDS]
    assert [(i.kind, i.evidence["text"]) for i in gaps] == [("fixed_text_missing", AXIAL)]
    assert gaps[0].status == "open" and res.run["template_gaps"]["fixed_text_missing"] == 1
    quick = await engine.run_review(_inp(template=False), RUN)
    assert quick.run["template_gaps"] is None and not [i for i in quick.items if i.kind in tg.KINDS]


# ── review fixes (probes from the independent review of c3985057) ──────────

def _raw(report, st=None, texts=(), assumed=()):
    from rapid_reports_ai.generation_artifacts import GenerationArtifacts
    from rapid_reports_ai.review_engine.items import ReviewInput
    base = {"sections": [{"name": "findings", "role": "findings", "order": 0}], "paragraphs": [], "rules": [],
            "fixed_blocks": [], "normals": [], "negatives": []}
    base.update(st or {})
    i = ReviewInput(report_id="r", pathway="templated", artifacts=GenerationArtifacts.from_candidate({"content": report}, ""),
                    template_text=list(texts), template_structure=base, assumed_normals=list(assumed))
    return [(k, t) for k, t, _ in tg.gaps(i)]


def _fixed(text, *rules):
    return {"fixed_blocks": [{"id": "f", "section": "findings", "text": text}],
            "rules": [{"id": f"r{k}", "section": "findings", "condition": "c", "source_lines": [], "target": "",
                       "then_text": "", **r} for k, r in enumerate(rules)]}


@pytest.mark.parametrize("report,text", [
    ("Scan quality:\nGood diagnostic quality.\n", "Scan quality: {quality}"),
    ("Medication given:\nMetoprolol 5 mg IV.\n", "Medication given: {medication}."),
])
def test_a_trailing_slot_value_on_the_next_line_is_not_empty(report, text):
    assert _raw(report, texts=[text]) == []


def test_a_trailing_slot_followed_by_a_heading_or_the_end_is_still_empty():
    assert _raw("Scan quality:\nCoronary Findings:\nLAD normal.\n", texts=["Scan quality: {quality}"]) == [
        ("template_slot_empty", "Scan quality")]
    assert _raw("Scan quality:\n\n", texts=["Scan quality: {quality}"]) == [("template_slot_empty", "Scan quality")]


FIX = "Axial images were acquired. A separate workstation was used for 3D reformation."
SECOND = "A separate workstation was used for 3D reformation."


def test_a_rule_on_one_sentence_of_a_fixed_block_settles_that_sentence():
    rep = {"effect": "replace", "target": SECOND, "then_text": "Reformats were not performed."}
    assert _raw("Axial images were acquired. Reformats were not performed.", _fixed(FIX, rep)) == []
    assert _raw("Axial images were acquired.", _fixed(FIX, {"effect": "suppress", "target": SECOND})) == []
    assert _raw("Axial images were acquired.", _fixed(FIX, rep)) == [("fixed_text_missing", SECOND)]


@pytest.mark.parametrize("report,fixed,then", [
    ("Contrast given: 80 ml Omnipaque.", "No contrast was administered.", "{contrast details}."),
    ("Calcium scoring was not performed due to patient refusal. See note. The scan was repeated.",
     "Calcium scoring was performed on the Flash scanner.",
     "Calcium scoring was not performed due to {reason}. The scan was repeated."),
])
def test_a_replacement_that_cannot_be_matched_is_unknowable(report, fixed, then):
    assert _raw(report, _fixed(fixed, {"effect": "replace", "target": fixed, "then_text": then})) == []


def test_a_merged_normal_is_not_missing_but_a_dropped_one_is():
    assert _raw("No pleural or pericardial effusion.", assumed=["No pleural effusion.", "No pericardial effusion."]) == []
    assert _raw("No pleural effusion.", assumed=["No pleural effusion.", "No pericardial effusion."]) == [
        ("assumed_normal_missing", "No pericardial effusion.")]


@pytest.mark.asyncio
async def test_a_changed_sheet_gives_no_gap_flag_and_no_note():
    from rapid_reports_ai.review_engine import structure_mentions as sm
    i = _inp(REPORT.replace(AXIAL + " ", "")).model_copy(update={"template_sheet_changed": True})
    assert tg.gap_items(i, RUN) == ([], {"sheet_changed": True})

    async def ask(report, names):
        raise AssertionError("never asked")
    assert await sm.mention_items(i, RUN, ask=ask) == ([], {"sheet_changed": True})
