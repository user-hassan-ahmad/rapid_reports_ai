"""Provenance items (approved 2026-10-06): `ai_generated` marks a report clause that asserts substantive content no
dictated line states (no confident alignment pair, and Jev W1n does not call it stated); `recommendation` marks an
undictated recommendation sentence with a code-built whole-sentence removal. Pure code over the alignment and the
shared Jev pass's existing answers; synthetic cases only, no model calls."""
import pytest

from rapid_reports_ai.review_engine import api, engine, negatives, provenance, verifier
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.items import ReviewItem, Span, text_hash
from rapid_reports_ai.review_engine.jev_pass import JevPass

from tests.review_engine_fakes import inp, jev, model

RUN = "00000000-0000-0000-0000-0000000000f1"

TECH = "CT abdomen and pelvis with intravenous contrast in the portal venous phase."
SIG = "Dr A Smith, Consultant Radiologist, GMC 0000000"
MASS = "There is a 3.2 cm hypoenhancing mass in the pancreatic head."
SMV = "The mass abuts the SMV over less than 180 degrees."
CBD = "The common bile duct is dilated, measuring 12 mm."
NORMAL = "The liver, spleen and kidneys are unremarkable."
OBSTR = "Appearances are in keeping with biliary obstruction."
SUGGEST = "Features suggest borderline resectable disease."
REC = "MDT discussion and staging CT chest are recommended."
REPORT = (f"TECHNIQUE:\n{TECH}\nCOMPARISON:\nNone available.\n"
          f"FINDINGS:\n{MASS} {SMV} {CBD} {NORMAL} No ascites.\n"
          f"IMPRESSION:\n1. Pancreatic head mass with biliary dilatation.\n2. {OBSTR}\n3. {SUGGEST}\n4. {REC}\n"
          f"{SIG}")
DICT = ("- 3.2 cm hypoenhancing pancreatic head mass\n- Abuts the SMV over less than 180 degrees\n- CBD dilated 12 mm\n"
        "- No ascites")


def _run(report=REPORT, dictation=DICT, jp=None, owned=()):
    i = inp(report, dictation)
    al = align(report, dictation, "", i.artifacts.sections)
    return provenance.build_items(i, RUN, al, jp, list(owned))


def _texts(items, kind):
    return [it.anchor.text for it in items if it.kind == kind]


def test_inference_sentence_in_impression_is_ai_generated():
    items, _ = _run()
    ai = _texts(items, "ai_generated")
    assert OBSTR in ai and SUGGEST in ai
    it = next(i for i in items if i.anchor.text == OBSTR)
    assert (it.lane, it.cls, it.detectors, it.section) == ("accuracy", "info", ["provenance"], "IMPRESSION")
    assert REPORT[it.anchor.start:it.anchor.end] == OBSTR and it.anchor.text_hash == text_hash(REPORT)
    assert it.edit is None and it.status == "open"
    assert all(i.evidence["form"] == "synthesis" for i in items if i.kind == "ai_generated")


def test_faithful_and_reworded_restatements_give_no_item():
    items, _ = _run()
    ai = " ".join(_texts(items, "ai_generated"))
    for s in (MASS, SMV, CBD, "Pancreatic head mass with biliary dilatation."):
        assert s not in ai


def test_connectives_added_to_a_dictated_line_are_not_ai_generated():
    report = "FINDINGS:\nThe mass abuts the SMV over less than 180 degrees.\nIMPRESSION:\nPancreatic mass."
    items, _ = _run(report, "- Pancreatic mass\n- Abuts the SMV over less than 180 degrees")
    assert items == []


def test_jev_stated_rewording_is_dictated():
    """A rewording the alignment cannot pair is still dictated when Jev W1n says the dictation states it."""
    report = "FINDINGS:\nA pancreatic mass.\nIMPRESSION:\nFindings are consistent with pancreatic adenocarcinoma."
    dictation = "- Pancreatic mass, likely cancer"
    imp = "Findings are consistent with pancreatic adenocarcinoma."
    i = inp(report, dictation)
    al = align(report, dictation, "", i.artifacts.sections)
    unpaired = [c for c in al.clauses if c.text == imp and not any(p.clause_id == c.id for p in al.pairs)]
    jp = JevPass(clauses=["A pancreatic mass.", imp], types={imp: "abnormal"}, support={"sup1": {"noul": 0.9}})
    assert unpaired                      # the alignment alone cannot pair the rewording
    items, _ = provenance.build_items(i, RUN, al, jp, [])
    assert items == []
    items, _ = provenance.build_items(i, RUN, al, None, [])   # without the Jev answer the same clause is marked
    assert _texts(items, "ai_generated") == [imp]


def test_recommendation_sentence_gets_a_working_remove_edit():
    items, _ = _run()
    recs = [i for i in items if i.kind == "recommendation"]
    assert len(recs) == 1
    r = recs[0]
    assert (r.lane, r.cls, r.detectors, r.section) == ("additions", "minor", ["code.recommendation"], "IMPRESSION")
    assert r.edit.mode == "remove" and r.edit.find == REC and r.edit.section == "IMPRESSION"
    assert r.status == "open" and r.verified["code"] is True
    out = verifier.apply_edit(REPORT, r.edit, ["TECHNIQUE", "COMPARISON", "FINDINGS", "IMPRESSION"])
    assert out is not None and REC not in out and "4." not in out and SIG in out
    assert REC not in _texts(items, "ai_generated")


def test_interpretive_suggest_is_not_a_recommendation():
    items, _ = _run()
    assert SUGGEST not in [i.edit.find for i in items if i.kind == "recommendation"]


def test_dictated_recommendation_gives_no_item():
    items, _ = _run(dictation=DICT + "\n- Recommend MDT discussion and staging CT chest")
    assert [i for i in items if i.kind == "recommendation"] == []


def test_technique_comparison_signature_and_normals_give_nothing():
    items, _ = _run()
    marked = " ".join(i.anchor.text for i in items)
    for s in (TECH, "None available", "Dr A Smith", NORMAL, "No ascites"):
        assert s not in marked


def test_not_a_finding_type_is_skipped():
    report = "FINDINGS:\nA pancreatic mass.\nIMPRESSION:\nPancreatic mass.\nDiscussed with the referring team."
    talk = "Discussed with the referring team."
    i = inp(report, "- Pancreatic mass")
    al = align(report, "- Pancreatic mass", "", i.artifacts.sections)
    jp = JevPass(clauses=[talk], types={talk: "not_a_finding"})
    items, _ = provenance.build_items(i, RUN, al, jp, [])
    assert talk not in " ".join(_texts(items, "ai_generated"))


def test_no_duplicate_with_brief_normals_or_negatives_items():
    obstr = REPORT.index(OBSTR)
    owned = ReviewItem(key="k", report_id="r", run_id=RUN, lane="accuracy", kind="check", cls="minor",
                       anchor=Span(start=obstr, end=obstr + len(OBSTR), text=OBSTR), detectors=["negatives.v5"])
    items, _ = _run(owned=[owned])
    assert OBSTR not in _texts(items, "ai_generated")


def test_adjacent_clauses_in_one_sentence_merge_into_one_span():
    report = "FINDINGS:\nPancreatic mass.\nIMPRESSION:\nPancreatic mass. Peritoneal deposits and liver metastases.\n"
    i = inp(report, "- Pancreatic mass")
    al = align(report, "- Pancreatic mass", "", i.artifacts.sections)
    sent = "Peritoneal deposits and liver metastases."
    s0 = report.index(sent)
    c = next(c for c in al.clauses if c.text == sent)
    a = c.model_copy(update={"id": "x1", "text": "Peritoneal deposits", "start": s0, "end": s0 + 19})
    b = c.model_copy(update={"id": "x2", "text": "liver metastases.", "start": s0 + 24, "end": s0 + len(sent)})
    al = al.model_copy(update={"clauses": [x for x in al.clauses if x.id != c.id] + [a, b]})
    items, _ = provenance.build_items(i, RUN, al, None, [])
    assert _texts(items, "ai_generated") == [sent]
    assert items[0].evidence["clauses"] == ["x1", "x2"]


def test_items_are_capped(monkeypatch):
    monkeypatch.setattr(provenance, "MAX_AI_ITEMS", 2)
    items, log = _run()
    assert len([i for i in items if i.kind == "ai_generated"]) <= 2
    assert log["ai_generated"] <= 2


@pytest.mark.asyncio
async def test_run_review_returns_provenance_items_never_adjudicated(monkeypatch):
    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)
    seen = []

    async def judge(inp_, groups):
        seen.extend(c.kind for g in groups for c in g)
        return [adj.Outcome(group=g) for g in groups]
    monkeypatch.setattr(adj, "adjudicate", judge)
    res = await engine.run_review(inp(REPORT, DICT), RUN)
    kinds = [i.kind for i in res.items]
    assert "recommendation" in kinds
    assert not ({"ai_generated", "recommendation"} & set(seen))
    rec = next(i for i in res.items if i.kind == "recommendation")
    assert rec.cls == "minor" and rec.edit is not None and rec.status == "open"
    assert "provenance" in res.run


def test_api_keeps_provenance_out_of_probe_and_reprepare():
    ai = ReviewItem(key="k", report_id="r", run_id=RUN, lane="accuracy", kind="ai_generated", cls="info")
    rec = ReviewItem(key="k2", report_id="r", run_id=RUN, lane="additions", kind="recommendation", cls="minor")
    assert api._provenance(ai) and api._provenance(rec)


# ── live audit 1: a recommendation beside other parts of one sentence (L3 shape) ──

MIXED_REPORT = ("FINDINGS:\nThe appendix is dilated to 11 mm with periappendiceal fat stranding.\n\n"
                "IMPRESSION:\nAcute appendicitis. No perforation or pelvic abscess identified; urgent surgical review "
                "recommended.\n")
MIXED_DICT = "- Dilated appendix 11 mm with fat stranding"


def test_mixed_recommendation_sentence_anchors_and_removes_only_the_recommendation():
    items, _ = _run(MIXED_REPORT, MIXED_DICT)
    recs = [i for i in items if i.kind == "recommendation"]
    assert len(recs) == 1
    r = recs[0]
    assert r.anchor.text == "urgent surgical review recommended"
    assert MIXED_REPORT[r.anchor.start:r.anchor.end] == r.anchor.text
    assert r.edit is not None and r.edit.mode == "remove" and r.verified["code"] is True
    out = verifier.apply_edit(MIXED_REPORT, r.edit, ["FINDINGS", "IMPRESSION"])
    assert out is not None
    assert "Acute appendicitis. No perforation or pelvic abscess identified.\n" in out
    assert "recommended" not in out


def test_mixed_recommendation_sentence_that_cannot_be_isolated_gets_no_remove_edit():
    report = MIXED_REPORT.replace("No perforation or pelvic abscess identified; urgent surgical review recommended.",
                                  "Urgent surgical review recommended; no perforation or pelvic abscess identified.")
    items, _ = _run(report, MIXED_DICT)
    r = next(i for i in items if i.kind == "recommendation")
    assert r.anchor.text == "Urgent surgical review recommended"
    assert r.edit is None and r.verified["code"] is False


def test_the_signature_block_after_the_impression_is_never_ai_generated():
    """Live audit 1: the user's signature appended after the impression's paragraph break is not report content."""
    report = ("FINDINGS:\nThe appendix is dilated to 11 mm with periappendiceal fat stranding.\n\n"
              "IMPRESSION:\nAcute appendicitis.\n\nDr Jane Example\nFRCR, Radiology ST4\n")
    items, _ = _run(report, MIXED_DICT)
    marked = " ".join(i.anchor.text for i in items)
    assert "Jane Example" not in marked and "FRCR" not in marked
    assert "Acute appendicitis." in _texts(items, "ai_generated")   # the impression itself is still read
    al = align(report, MIXED_DICT, "", inp(report, MIXED_DICT).artifacts.sections)
    assert not any("Example" in c.text or "FRCR" in c.text for c in al.clauses)
