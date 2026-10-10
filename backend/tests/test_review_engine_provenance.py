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


SIGNED = ("FINDINGS:\nThe appendix is dilated to 11 mm with periappendiceal fat stranding.\n\n"
          "IMPRESSION:\n1. Acute appendicitis.\n\n2. Small volume pelvic free fluid.\n\n"
          "Dr Jane Example\nFRCR, Radiology ST4")
SIG_BLOCK = "Dr Jane Example\nFRCR, Radiology ST4"


@pytest.mark.parametrize("signature", [SIG_BLOCK, None])      # persisted, and the older-report fallback
async def test_signature_untagged_and_every_numbered_impression_item_kept(monkeypatch, signature):
    """Live audit 1 (review fix 1): the engine strips exactly the appended signature, never a later impression
    paragraph; a report from before the signature was persisted drops only an unpunctuated last paragraph."""
    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}
    monkeypatch.setattr(rc, "_jev", jev({"sup*": {"noul": 0.1}}))    # W1n: nothing stated, so every read clause is marked
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)
    monkeypatch.setattr(adj, "adjudicate", lambda inp_, groups: _outcomes(groups))
    i = inp(SIGNED, MIXED_DICT)
    i.artifacts.signature = signature
    res = await engine.run_review(i, RUN)
    marked = " ".join(it.anchor.text for it in res.items if it.anchor)
    assert "Jane Example" not in marked and "FRCR" not in marked
    ai = _texts(res.items, "ai_generated")
    assert "Acute appendicitis." in ai and "Small volume pelvic free fluid." in ai


async def _outcomes(groups):
    return [adj.Outcome(group=g) for g in groups]


def test_report_body_strips_exactly_the_signature():
    from rapid_reports_ai.report_review import report_body
    assert report_body(SIGNED, SIG_BLOCK).endswith("2. Small volume pelvic free fluid.")
    assert report_body(SIGNED, None).endswith("2. Small volume pelvic free fluid.")       # fallback
    assert report_body(SIGNED, "") == SIGNED                                             # known: no signature
    unsigned = SIGNED[:SIGNED.index("\n\nDr Jane")]
    assert report_body(unsigned, None) == unsigned       # punctuated last paragraph: an impression item, kept
    assert report_body(unsigned, "Dr Somebody Else") == unsigned
    al = align(report_body(SIGNED, SIG_BLOCK), MIXED_DICT, "", inp(SIGNED, MIXED_DICT).artifacts.sections)
    texts = [c.text for c in al.clauses]
    assert "Small volume pelvic free fluid." in texts and not any("Jane" in t for t in texts)


def test_the_candidate_record_carries_the_signature_into_the_artifacts():
    from rapid_reports_ai.generation_artifacts import GenerationArtifacts
    rec = {"content": SIGNED, "sections": ["FINDINGS", "IMPRESSION"], "signature": SIG_BLOCK}
    assert GenerationArtifacts.from_candidate(rec, "x").signature == SIG_BLOCK
    assert GenerationArtifacts.from_candidate({"content": SIGNED}, "x").signature is None   # older record


def test_the_finding_part_of_a_mixed_recommendation_sentence_is_ai_generated():
    """Review fix 2: shrinking the recommendation item must not leave the sentence's undictated finding untinted."""
    report = ("FINDINGS:\nThe appendix is dilated to 11 mm with periappendiceal fat stranding.\n\n"
              "IMPRESSION:\nFindings are suspicious for perforation; urgent surgical review recommended.\n")
    items, _ = _run(report, MIXED_DICT)
    assert _texts(items, "ai_generated") == ["Findings are suspicious for perforation"]
    assert _texts(items, "recommendation") == ["urgent surgical review recommended"]


def test_a_supported_finding_part_gets_no_ai_generated_item():
    report = ("FINDINGS:\nThe appendix is dilated to 11 mm with periappendiceal fat stranding.\n\n"
              "IMPRESSION:\nFindings are suspicious for perforation; urgent surgical review recommended.\n")
    part = "Findings are suspicious for perforation"
    jp = JevPass(clauses=[part], types={part: "abnormal"}, support={"sup0": {"noul": 0.9}})
    items, _ = _run(report, MIXED_DICT, jp=jp)
    assert _texts(items, "ai_generated") == []


# ── live audit 2, 1b: an IMPRESSION recommendation with no lexicon word (L1 shape) ──

REPEAT = "Short-interval repeat CT in 24 hours to assess for interval change."
REPEAT_REPORT = ("FINDINGS:\nThe appendix is dilated to 11 mm with periappendiceal fat stranding.\n\n"
                 f"IMPRESSION:\nAcute appendicitis.\n{REPEAT}\n")


def test_impression_not_a_finding_is_a_recommendation_without_lexicon_words():
    assert not provenance.is_recommendation(REPEAT)                       # the lexicon alone misses it
    jp = JevPass(clauses=["Acute appendicitis.", REPEAT],
                 types={"Acute appendicitis.": "abnormal", REPEAT: "not_a_finding"})
    items, log = _run(REPEAT_REPORT, MIXED_DICT, jp=jp)
    r = next(i for i in items if i.kind == "recommendation")
    assert r.anchor.text == REPEAT and r.section == "IMPRESSION"
    assert r.edit is not None and r.edit.mode == "remove" and r.edit.find == REPEAT
    out = verifier.apply_edit(REPEAT_REPORT, r.edit, ["FINDINGS", "IMPRESSION"])
    assert out is not None and "repeat CT" not in out and "Acute appendicitis." in out
    assert log["skipped"]["not_a_finding"] == 0


def test_findings_not_a_finding_without_lexicon_words_stays_skipped():
    report = f"FINDINGS:\nAcute appendicitis.\n{REPEAT}\n\nIMPRESSION:\nAcute appendicitis.\n"
    jp = JevPass(clauses=[REPEAT], types={REPEAT: "not_a_finding"})
    items, log = _run(report, MIXED_DICT, jp=jp)
    assert [i for i in items if i.kind == "recommendation"] == []
    assert REPEAT not in " ".join(_texts(items, "ai_generated"))


def test_without_a_jev_type_the_lexicon_still_decides():
    jp = JevPass(clauses=[], types={})
    items, _ = _run(REPEAT_REPORT, MIXED_DICT, jp=jp)
    assert [i for i in items if i.kind == "recommendation"] == []


def test_dictated_lexicon_free_recommendation_gives_no_item():
    jp = JevPass(clauses=[REPEAT], types={REPEAT: "not_a_finding"})
    items, _ = _run(REPEAT_REPORT, MIXED_DICT + "\n- Short-interval repeat CT in 24 hours to assess for interval change",
                    jp=jp)
    assert [i for i in items if i.kind == "recommendation"] == []


def test_reworded_dictated_communication_is_not_a_removable_recommendation():
    report = "FINDINGS:\nA pancreatic mass.\nIMPRESSION:\nPancreatic mass.\nDiscussed with the referring team."
    talk = "Discussed with the referring team."
    dictation = "- Pancreatic mass\n- Result discussed by phone with Dr Jones, surgical registrar, 14:00 hours, read-back confirmed"
    i = inp(report, dictation)
    al = align(report, dictation, "", i.artifacts.sections)
    c = next(c for c in al.clauses if c.text == talk)
    assert not any(p.clause_id == c.id and provenance.confident(p) for p in al.pairs)    # no confident pair
    jp = JevPass(clauses=["Pancreatic mass.", talk], types={"Pancreatic mass.": "abnormal", talk: "not_a_finding"})
    items, _ = provenance.build_items(i, RUN, al, jp, [])
    assert [it for it in items if it.kind == "recommendation"] == []


# ── live audit 2, 1a: synthesis inside a dictation-paired clause, its unsupported item suppressed (L7 shape) ──
# Code proposes the words absent from the whole dictation; a Jev question (lab P3 D3n shape) decides.

CYST_DICT = "- Left renal cyst 15 mm\n- Liver normal"
CYST_REPORT = ("FINDINGS:\nLeft renal cyst 15 mm. The liver is normal.\n\n"
               "IMPRESSION:\nLeft renal cyst 15 mm, in keeping with a simple Bosniak I cyst.\n")
CYST_CLAUSE = "Left renal cyst 15 mm, in keeping with a simple Bosniak I cyst."
NOT_DICTATED = {"syn*": {"choice": "not_stated", "probabilities": {"stated": 0.05, "synonym_or_equivalent": 0.1, "not_stated": 0.85}}}
DICTATED = {"syn*": {"choice": "stated", "probabilities": {"stated": 0.6, "synonym_or_equivalent": 0.3, "not_stated": 0.1}}}
SYNONYM = {"syn*": {"choice": "synonym_or_equivalent", "probabilities": {"stated": 0.1, "synonym_or_equivalent": 0.7, "not_stated": 0.2}}}


def _unsupported(report, clause, cls="suppress", detectors=("jev.supported",), also=()):
    s = report.rindex(clause)
    ev = {"also_anchors": [{"start": report.rindex(t), "end": report.rindex(t) + len(t), "text": t} for t in also]}
    return ReviewItem(key="u", report_id="r", run_id=RUN, lane="accuracy", kind="unsupported", cls=cls,
                      section="IMPRESSION", detectors=list(detectors), evidence=ev,
                      anchor=Span(start=s, end=s + len(clause), text=clause, text_hash=text_hash(report)))


async def _synthesis(monkeypatch, report, dictation, lane_items, answers=NOT_DICTATED, existing=(), jp=None,
                     calls=None):
    monkeypatch.setattr(rc, "_jev", answers if callable(answers) else jev(answers, calls))
    i = inp(report, dictation)
    al = align(report, dictation, "", i.artifacts.sections)
    return await provenance.synthesis_items(i, RUN, al, jp, list(lane_items), list(existing), [])


async def test_suppressed_unsupported_marks_only_the_undictated_words(monkeypatch):
    calls = []
    items, log = await _synthesis(monkeypatch, CYST_REPORT, CYST_DICT, [_unsupported(CYST_REPORT, CYST_CLAUSE)],
                                  calls=calls)
    assert _texts(items, "ai_generated") == ["simple Bosniak"]
    it = items[0]
    assert (it.lane, it.cls, it.detectors, it.section) == ("accuracy", "info", ["provenance"], "IMPRESSION")
    assert CYST_REPORT[it.anchor.start:it.anchor.end] == it.anchor.text
    assert it.evidence["form"] == "synthesis" and it.evidence["from"] == "unsupported_suppressed"
    assert log["synthesis"] == 1 and len(calls) == 1                     # one batched request per report
    state, qs = calls[0]
    assert "DICTATED FINDINGS:\n" + CYST_DICT in state
    q = next(iter(qs.values()))
    assert q["type"] == "choice" and set(q["criteria"]) == {"stated", "synonym_or_equivalent", "not_stated"}
    assert q["instructions"] == (f'The report says: "{CYST_CLAUSE}". Consider only this one phrase from it: '
                                 '"simple Bosniak". Is it in the dictated findings?')


async def test_periovulatory_shape_is_marked(monkeypatch):
    dictation = "- Right ovarian simple cyst 28 mm\n- Uterus normal"
    clause = "Right ovarian simple cyst 28 mm, in keeping with a functional periovulatory finding."
    report = f"FINDINGS:\nRight ovarian simple cyst 28 mm. Uterus normal.\n\nIMPRESSION:\n{clause}\n"
    items, _ = await _synthesis(monkeypatch, report, dictation, [_unsupported(report, clause)])
    assert _texts(items, "ai_generated") == ["functional periovulatory"]


async def test_jev_says_dictated_synonym_gets_no_mark(monkeypatch):
    report = ("FINDINGS:\nLeft renal cyst 15 mm. The liver is normal.\n\n"
              "IMPRESSION:\nLeft renal cyst 15 mm.\n")
    dictation = "- Left kidney cyst 15 mm\n- Liver normal"
    items, _ = await _synthesis(monkeypatch, report, dictation, [_unsupported(report, "Left renal cyst 15 mm.")],
                                answers=SYNONYM)
    assert items == []


async def test_clause_merging_two_dictated_lines_gets_no_mark(monkeypatch):
    dictation = "- Left renal cyst 15 mm\n- Gallstones\n- Liver normal"
    clause = "Left renal cyst 15 mm and gallstones."
    report = f"FINDINGS:\nLeft renal cyst 15 mm. Gallstones. The liver is normal.\n\nIMPRESSION:\n{clause}\n"
    calls = []
    items, _ = await _synthesis(monkeypatch, report, dictation, [_unsupported(report, clause)], calls=calls)
    assert items == [] and calls == []                                    # nothing proposed, nothing asked


async def test_technique_anchor_gets_no_mark(monkeypatch):
    tech = "CT abdomen with intravenous contrast in the portal venous phase."
    report = f"TECHNIQUE:\n{tech}\nFINDINGS:\nLeft renal cyst 15 mm.\n\nIMPRESSION:\nLeft renal cyst.\n"
    items, _ = await _synthesis(monkeypatch, report, CYST_DICT, [_unsupported(report, tech)])
    assert items == []


async def test_unpaired_suppressed_clause_gets_no_mark(monkeypatch):
    report = ("FINDINGS:\nLeft renal cyst 15 mm. The liver is normal.\n\n"
              "IMPRESSION:\nLeft renal cyst. Benign hepatic steatosis pattern excluded clinically.\n")
    clause = "Benign hepatic steatosis pattern excluded clinically."
    items, _ = await _synthesis(monkeypatch, report, CYST_DICT, [_unsupported(report, clause)])
    assert items == []


async def test_dictated_no_between_added_runs_is_never_painted(monkeypatch):
    dictation = "- Left renal cyst 15 mm, no enhancement\n- Liver normal"
    clause = "Left renal cyst 15 mm, benign septated, no enhancement, Bosniak category."
    report = f"FINDINGS:\nLeft renal cyst 15 mm, no enhancement. The liver is normal.\n\nIMPRESSION:\n{clause}\n"
    items, _ = await _synthesis(monkeypatch, report, dictation, [_unsupported(report, clause)])
    marked = _texts(items, "ai_generated")
    assert marked and not any(" no " in f" {m} " or "enhancement" in m for m in marked)


async def test_also_anchors_are_proposed_too(monkeypatch):
    finding = "Left renal cyst 15 mm."
    items, _ = await _synthesis(monkeypatch, CYST_REPORT, CYST_DICT,
                                [_unsupported(CYST_REPORT, finding, also=(CYST_CLAUSE,))])
    assert _texts(items, "ai_generated") == ["simple Bosniak"]


async def test_jev_failure_gives_no_mark(monkeypatch):
    async def boom(state, qs):
        raise RuntimeError("down")
    items, log = await _synthesis(monkeypatch, CYST_REPORT, CYST_DICT, [_unsupported(CYST_REPORT, CYST_CLAUSE)],
                                  answers=boom)
    assert items == [] and log["error"]
    items, _ = await _synthesis(monkeypatch, CYST_REPORT, CYST_DICT, [_unsupported(CYST_REPORT, CYST_CLAUSE)],
                                answers={"syn*": {"bad": 1}})                     # unreadable answer
    assert items == []


async def test_only_suppressed_jev_supported_items_and_finding_types_are_proposed(monkeypatch):
    for it in (_unsupported(CYST_REPORT, CYST_CLAUSE, cls="minor"),
               _unsupported(CYST_REPORT, CYST_CLAUSE, detectors=("code.numbers",))):
        assert (await _synthesis(monkeypatch, CYST_REPORT, CYST_DICT, [it]))[0] == []
    jp = JevPass(clauses=[CYST_CLAUSE], types={CYST_CLAUSE: "normal"})
    assert (await _synthesis(monkeypatch, CYST_REPORT, CYST_DICT, [_unsupported(CYST_REPORT, CYST_CLAUSE)],
                             jp=jp))[0] == []


async def test_no_double_mark_when_provenance_already_marked_the_span(monkeypatch):
    s = CYST_REPORT.rindex(CYST_CLAUSE)
    prior = ReviewItem(key="p", report_id="r", run_id=RUN, lane="accuracy", kind="ai_generated", cls="info",
                       anchor=Span(start=s, end=s + len(CYST_CLAUSE), text=CYST_CLAUSE), detectors=["provenance"])
    items, _ = await _synthesis(monkeypatch, CYST_REPORT, CYST_DICT, [_unsupported(CYST_REPORT, CYST_CLAUSE)],
                                existing=[prior])
    assert items == []


@pytest.mark.asyncio
async def test_run_review_tints_the_synthesis_of_a_suppressed_unsupported_item(monkeypatch):
    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}
    monkeypatch.setattr(rc, "_jev", jev({"sup*": {"noul": 0.1}, **NOT_DICTATED}))
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)

    async def judge(inp_, groups):
        return [adj.Outcome(group=g, judgement=adj.Judgement(
            cls="suppress", kind=g[0].kind, label="x", reason="standard synthesis", edit_mode="none")) for g in groups]
    monkeypatch.setattr(adj, "adjudicate", judge)
    res = await engine.run_review(inp(CYST_REPORT, CYST_DICT), RUN)
    sup = [i for i in res.items if i.kind == "unsupported"]
    assert sup and all(i.cls == "suppress" for i in sup)                 # the suppressed item stays suppressed
    assert "simple Bosniak" in _texts(res.items, "ai_generated")
    assert res.run["provenance"]["synthesis"] >= 1


@pytest.mark.asyncio
async def test_run_review_keeps_provenance_when_synthesis_fails(monkeypatch):
    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)
    monkeypatch.setattr(adj, "adjudicate", lambda inp_, groups: _outcomes(groups))

    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(provenance, "synthesis_items", boom)
    res = await engine.run_review(inp(REPORT, DICT), RUN)
    assert "recommendation" in [i.kind for i in res.items] and "synthesis" in res.run["errors"]


async def test_negated_clause_trap_a_dictated_negative_noun_is_never_marked(monkeypatch):
    """Lab P4: the noul wording scored "intracranial haemorrhage" 0.15 against a dictated "No ICH"; Q3 calls it a
    synonym, so the noun of a dictated negative is never painted."""
    dictation = "- Left subdural haematoma 8 mm\n- No ICH"
    clause = "Left subdural haematoma 8 mm, with no intracranial haemorrhage elsewhere."
    report = f"FINDINGS:\nLeft subdural haematoma 8 mm.\n\nIMPRESSION:\n{clause}\n"
    calls = []
    items, log = await _synthesis(monkeypatch, report, dictation, [_unsupported(report, clause)], answers=SYNONYM,
                                  calls=calls)
    assert log["proposed"] >= 1 and items == []
    asked = [q["instructions"] for q in calls[0][1].values()]
    assert any('"intracranial haemorrhage' in q for q in asked) and not any('"no ' in q for q in asked)


def test_choice_answer_parsing():
    p = provenance.p_dictated
    assert p({"probabilities": {"stated": 0.2, "synonym_or_equivalent": 0.25, "not_stated": 0.55}}) == pytest.approx(0.45)
    assert p({"probabilities": {"stated": "0.3", "synonym_or_equivalent": 0.3, "not_stated": 0.4}}) == pytest.approx(0.6)
    assert p({"choice": "not_stated"}) == 0.0 and p({"choice": "synonym_or_equivalent"}) == 1.0
    for bad in (None, {}, {"noul": 0.1}, {"choice": "maybe"}, {"probabilities": {"stated": "x"}}):
        assert p(bad) is None
