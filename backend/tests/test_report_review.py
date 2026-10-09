"""Section-generic review (spec §4): template headings, implicit sections, protected spans."""
from __future__ import annotations

import pytest

from rapid_reports_ai import brief_anchor as ba
from rapid_reports_ai import report_review as rr


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    """A test that forgets to stub Jev or the repair model fails loudly instead of timing out on the
    network. check() and the repairs swallow exceptions, so calls are recorded and fail at teardown."""
    calls = []

    def unstubbed(name):
        async def call(*a, **k):
            calls.append(name)
            raise AssertionError(f"unstubbed {name} call")
        return call
    monkeypatch.setattr(rr.rc, "_jev", unstubbed("Jev"))
    monkeypatch.setattr(rr, "_run_agent_with_model", unstubbed("model"))
    yield
    assert not calls, f"unstubbed calls: {calls}"


# The omission classifier's answer for a line the report states (L-49 classify-first): no flag.
STATED = {"choice": "stated", "probabilities": {"stated": 0.9, "partial": 0.05, "absent": 0.05}}

SECTIONS = [rr.ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            rr.ReportSection(name="TECHNIQUE", header="TECHNIQUE", role="technique"),
            rr.ReportSection(name="FINDINGS", header=None, role="findings"),
            rr.ReportSection(name="IMPRESSION", header="Impression", role="impression")]
REPORT = """CLINICAL HISTORY
67F. Abdominal pain. ?Appendicitis.

TECHNIQUE
Portal venous phase CT.

The appendix is dilated measuring 11 mm. No pneumoperitoneum. Unremarkable appearances of the spleen.

Impression
Acute appendicitis."""


def test_section_spans_cover_headed_and_implicit_sections():
    spans = {s.name: REPORT[a:b].strip() for s, a, b in rr.section_spans(REPORT, SECTIONS)}
    assert spans["CLINICAL HISTORY"] == "67F. Abdominal pain. ?Appendicitis."
    assert spans["TECHNIQUE"].startswith("Portal venous phase CT.")
    assert spans["IMPRESSION"] == "Acute appendicitis."


def test_implicit_first_section_runs_to_the_first_header():
    secs = [rr.ReportSection(name="FINDINGS", header=None, role="findings"),
            rr.ReportSection(name="CONCLUSION", header="Conclusion:", role="impression")]
    text = "Liver normal. No ascites.\n\nConclusion:\nNormal study."
    spans = {s.name: text[a:b].strip() for s, a, b in rr.section_spans(text, secs)}
    assert spans == {"FINDINGS": "Liver normal. No ascites.", "CONCLUSION": "Normal study."}


def test_checked_clauses_skip_history_technique_and_comparison():
    cls = rr.checked_clauses(REPORT, SECTIONS)
    assert "No pneumoperitoneum." in cls and "Acute appendicitis." in cls
    assert not any("Abdominal pain" in c or "Portal venous" in c for c in cls)


def test_quick_default_is_unchanged():
    quick = "FINDINGS:\nNo ascites, no collection.\n\nIMPRESSION:\nNormal.\n\nDr A"
    fnd, imp = rr.report_sections(quick)
    assert rr.checked_clauses(quick, None) == list(dict.fromkeys(rr.clauses(fnd) + rr.clauses(imp)))


def test_omission_state_drops_the_history_text():
    assert "Abdominal pain" not in rr.without(REPORT, ["67F. Abdominal pain. ?Appendicitis."])


async def test_check_with_sections_asks_only_checked_clauses(monkeypatch):
    seen = []

    async def fake_jev(state, qs):
        seen.append((state, [q["instructions"] for q in qs.values()]))
        return {k: {"noul": 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    res = await rr.check(REPORT, "11 mm appendix", "CT AP", [], sections=SECTIONS,
                         protected=["67F. Abdominal pain. ?Appendicitis."])
    contra = next(q for s, q in seen if s.startswith("SCAN TYPE"))
    omit_state = next(s for s, q in seen if s.startswith("REPORT"))
    assert not any("Portal venous" in x or "Abdominal pain" in x for x in contra)
    assert "Abdominal pain" not in omit_state and res.error is None


async def test_a_flag_inside_protected_text_is_reported_but_never_edited(monkeypatch):
    fixed = "No evidence of malignancy is excluded by this examination."
    report = REPORT.replace("Acute appendicitis.", f"Acute appendicitis.\n\n{fixed}")

    async def fake_check(*a, **kw):
        assert kw["protected"] == [fixed]
        return rr.CheckResult(flags=[rr.Flag(kind="contradiction", text=fixed, score=0.9)])

    async def no_repair(*a, **kw):
        raise AssertionError("a protected flag reached a repair")
    monkeypatch.setattr(rr, "check", fake_check)
    monkeypatch.setattr(rr, "insert_findings", no_repair)
    out, _, tel = await rr.run_quality_check(report, "x", "CT", [], sections=SECTIONS, protected=[fixed])
    assert out == report and tel["flags"][0]["text"] == fixed and tel["clauses_removed"] == 0


# ── protected text is an invariant by position (review of Task 4) ───────────

FIXED = "No ascites, collection or free air."


def _fake_model(monkeypatch, output):
    class R:
        pass
    r = R()
    r.output = output

    async def fake(**kw):
        return r
    monkeypatch.setattr(rr, "_run_agent_with_model", fake)


def test_a_synthesised_list_clause_never_edits_a_protected_block():
    report = REPORT.replace("Unremarkable appearances of the spleen.", f"Unremarkable appearances of the spleen. {FIXED}")
    assert "No collection or free air" in rr.checked_clauses(report, SECTIONS)
    assert rr.remove_negative_clause(report, "No collection or free air", SECTIONS, [FIXED]) == report
    # unprotected, the same list item is dropped
    out = rr.remove_negative_clause(report, "No collection or free air", SECTIONS)
    assert FIXED not in out and "spleen. No ascites.\n" in out


def test_negative_removal_edits_only_the_checked_span():
    secs = [rr.ReportSection(name="COMPARISON", header="COMPARISON", role="comparison"),
            rr.ReportSection(name="FINDINGS", header="FINDINGS", role="findings")]
    report = "COMPARISON\nPrior CT. No free air.\n\nFINDINGS\nLiver normal. No free air."
    out = rr.remove_negative_clause(report, "No free air", secs)
    assert out == "COMPARISON\nPrior CT. No free air.\n\nFINDINGS\nLiver normal."


def _not_conveyed(monkeypatch):
    """The inserter's Jev duplicate check (L-49): no candidate sentence is already in the report."""
    async def jev(state, qs):
        return {k: {"noul": 0.0} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", jev)


async def test_insertion_anchor_on_a_header_falls_back_to_the_findings_section(monkeypatch):
    _not_conveyed(monkeypatch)
    _fake_model(monkeypatch, rr.Insertions(items=[
        rr.Insertion(after="CLINICAL HISTORY", sentence="Small volume pelvic free fluid.")]))
    res = await rr.insert_findings(REPORT, "x", ["pelvic fluid"], SECTIONS,
                                   ["67F. Abdominal pain. ?Appendicitis."])
    assert "CLINICAL HISTORY Small" not in res.report and res.applied == 1
    assert "Small volume pelvic free fluid. The appendix is dilated" in res.report


async def test_insertion_anchor_in_protected_text_is_not_used(monkeypatch):
    _not_conveyed(monkeypatch)
    _fake_model(monkeypatch, rr.Insertions(items=[
        rr.Insertion(after="Abdominal pain.", sentence="Small volume pelvic free fluid.")]))
    res = await rr.insert_findings(REPORT, "x", ["pelvic fluid"], SECTIONS,
                                   ["67F. Abdominal pain. ?Appendicitis."])
    assert "67F. Abdominal pain. ?Appendicitis." in res.report
    assert "Small volume pelvic free fluid. The appendix is dilated" in res.report


async def test_a_repair_that_changes_protected_text_is_reverted(monkeypatch):
    history = "67F. Abdominal pain. ?Appendicitis."

    async def fake_check(*a, **kw):
        return rr.CheckResult(flags=[rr.Flag(kind="omission", text="pelvic fluid", score=0.1)])

    async def rogue_insert(report, findings, items, **kw):
        return rr.RepairResult(report=report.replace(history, "67F."), applied=1)
    monkeypatch.setattr(rr, "check", fake_check)
    monkeypatch.setattr(rr, "insert_findings", rogue_insert)
    out, _, tel = await rr.run_quality_check(REPORT, "x", "CT", [], sections=SECTIONS, protected=[history])
    assert out == REPORT and tel["error"] == "protected text changed; repair reverted"


# ── section_spans robustness ─────────────────────────────────────────────────

def _spans(text, secs):
    return {s.name: text[a:b].strip() for s, a, b in rr.section_spans(text, secs)}


def test_section_spans_tolerate_crlf():
    spans = _spans(REPORT.replace("\n", "\r\n"), SECTIONS)
    assert spans["CLINICAL HISTORY"] == "67F. Abdominal pain. ?Appendicitis."
    assert spans["TECHNIQUE"] == "Portal venous phase CT."
    assert spans["FINDINGS"].startswith("The appendix is dilated") and spans["IMPRESSION"] == "Acute appendicitis."


def test_section_spans_read_inline_headers():
    text = "Technique: Portal venous phase CT.\n\nThe appendix is dilated.\n\nImpression: Acute appendicitis."
    spans = _spans(text, SECTIONS[1:])
    assert spans == {"TECHNIQUE": "Portal venous phase CT.", "FINDINGS": "The appendix is dilated.",
                     "IMPRESSION": "Acute appendicitis."}


def test_section_spans_split_out_of_order_headers():
    secs = [rr.ReportSection(name="FINDINGS", header="Findings", role="findings"),
            rr.ReportSection(name="IMPRESSION", header="Impression", role="impression")]
    text = "Impression:\nAcute appendicitis.\n\nFindings:\nThe appendix is dilated."
    assert _spans(text, secs) == {"FINDINGS": "The appendix is dilated.", "IMPRESSION": "Acute appendicitis."}


async def test_run_quality_check_normalises_crlf_and_reports_sections(monkeypatch):
    async def fake_jev(state, qs):
        return {k: STATED if k.startswith("i") else {"noul": 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    secs = SECTIONS + [rr.ReportSection(name="RECOMMENDATION", header="Recommendation", role="other")]
    out, _, tel = await rr.run_quality_check(REPORT.replace("\n", "\r\n"), "11 mm appendix", "CT", [],
                                             sections=secs, protected=["67F. Abdominal pain. ?Appendicitis."])
    assert out == REPORT and tel["error"] is None
    assert tel["sections_found"] == ["CLINICAL HISTORY", "TECHNIQUE", "FINDINGS", "IMPRESSION"]
    assert tel["sections_missing"] == ["RECOMMENDATION"] and tel["sections_empty"] == []


def test_without_removes_the_protected_occurrence_only():
    secs = [rr.ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            rr.ReportSection(name="FINDINGS", header="FINDINGS", role="findings")]
    report = "CLINICAL HISTORY\nNo ascites.\n\nFINDINGS\nLiver normal. No ascites."
    assert rr.without(report, ["No ascites."], secs) == "CLINICAL HISTORY\n\n\nFINDINGS\nLiver normal. No ascites."


H3 = [rr.ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
      rr.ReportSection(name="FINDINGS", header="FINDINGS", role="findings"),
      rr.ReportSection(name="IMPRESSION", header="IMPRESSION", role="impression")]


def test_prose_that_starts_like_an_inline_header_is_not_a_header():
    text = "CLINICAL HISTORY\nPain.\n\nFINDINGS\nLiver normal.\nImpression: none from prior.\n\nIMPRESSION\nNormal."
    spans = _spans(text, H3)
    assert spans["FINDINGS"] == "Liver normal.\nImpression: none from prior." and spans["IMPRESSION"] == "Normal."


def test_a_lone_lower_case_header_word_in_the_history_loses_to_the_real_header():
    text = "CLINICAL HISTORY\nfindings\n\nFINDINGS\nNo ascites.\n\nIMPRESSION\nNormal."
    assert _spans(text, H3) == {"CLINICAL HISTORY": "findings", "FINDINGS": "No ascites.", "IMPRESSION": "Normal."}


PRE = [rr.ReportSection(name="TECHNIQUE", header="TECHNIQUE", role="technique"),
       rr.ReportSection(name="FINDINGS", header=None, role="findings"),
       rr.ReportSection(name="IMPRESSION", header="Impression", role="impression")]
NO_BLANK = "TECHNIQUE\nCT.\nNo ascites.\n\nImpression\nNormal."


def test_an_empty_implicit_section_takes_the_preamble_after_its_first_line():
    assert _spans(NO_BLANK, PRE) == {"TECHNIQUE": "CT.", "FINDINGS": "No ascites.", "IMPRESSION": "Normal."}
    assert rr.checked_clauses(NO_BLANK, PRE) == ["No ascites.", "Normal."]


async def test_run_quality_check_reports_empty_implicit_sections(monkeypatch):
    async def fake_jev(state, qs):
        return {k: STATED if k.startswith("i") else {"noul": 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    _, _, tel = await rr.run_quality_check(NO_BLANK, "ascites", "CT", [], sections=PRE)
    assert tel["sections_empty"] == ["FINDINGS"] and tel["clauses"] == 2


async def test_a_template_positive_contradiction_is_review_only(monkeypatch):
    """Main PR #7 (L-49): a flagged positive statement never edits the report, on either path."""
    flag = "The appendix is dilated measuring 11 mm."

    async def fake_check(*a, **kw):
        return rr.CheckResult(flags=[rr.Flag(kind="contradiction", text=flag, score=0.9)])

    async def no_model(*a, **kw):
        raise AssertionError("a positive contradiction reached a model")
    monkeypatch.setattr(rr, "check", fake_check)
    monkeypatch.setattr(rr, "insert_findings", no_model)
    out, _, tel = await rr.run_quality_check(REPORT, "x", "CT", [], sections=SECTIONS)
    assert out == REPORT and tel["review"] == [{"kind": "contradiction", "text": flag, "score": 0.9}]
    assert not hasattr(rr, "repair_report")


async def test_a_template_negative_the_dictation_states_is_never_removed(monkeypatch):
    """Main PR #6 (L-49): the d<i> question, quoted with the sentence before it, keeps a dictated negative."""
    asked = {}

    async def fake_jev(state, qs):
        if state.startswith("REPORT:"):
            return {k: STATED for k in qs}
        asked.update({k: q for k, q in qs.items()})
        return {k: {"noul": 0.8 if k.startswith("d") else 0.9} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    out, _, tel = await rr.run_quality_check(REPORT, "No pneumoperitoneum. 11 mm appendix.", "CT", [],
                                             sections=SECTIONS)
    i = rr.checked_clauses(REPORT, SECTIONS).index("No pneumoperitoneum.")
    assert asked[f"d{i}"] == rr.q_dictated("No pneumoperitoneum.", "The appendix is dilated measuring 11 mm.")
    assert out == REPORT and tel["clauses_removed"] == 0
    assert {"text": "No pneumoperitoneum.", "contradiction": 0.9, "dictated": 0.8} in tel["kept_dictated_negative"]


def test_template_removal_drops_a_list_item_left_empty():
    report = REPORT.replace("Acute appendicitis.", "1. Acute appendicitis.\n2. No other acute abnormality.\nRecommend surgical review.")
    out = rr.remove_negative_clause(report, "No other acute abnormality.", sections=SECTIONS)
    assert out.endswith("Impression\n1. Acute appendicitis.\nRecommend surgical review.")
    # a line with other text keeps its line
    out = rr.remove_negative_clause(REPORT, "No pneumoperitoneum.", sections=SECTIONS)
    assert "11 mm. Unremarkable appearances of the spleen.\n" in out


async def test_extra_report_questions_ride_on_the_report_state_call(monkeypatch):
    seen = []

    async def fake_jev(state, qs):
        seen.append((state, sorted(qs)))
        return {k: {"noul": 0.8} if k == "u0" else STATED if k.startswith("i") else {"noul": 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    extra = {"u0": {"type": "noul", "instructions": rr.rc.Q_CONVEYS + "No free gas."}}
    res = await rr.check(REPORT, "11 mm appendix", "CT AP", [], sections=SECTIONS, extra_report_qs=extra)
    assert len(seen) == 2  # no additional Jev request
    report_call = next(k for s, k in seen if s.startswith("REPORT"))
    assert "u0" in report_call and res.extra_answers == {"u0": 0.8}
    _, _, tel = await rr.run_quality_check(REPORT, "11 mm appendix", "CT AP", [], sections=SECTIONS,
                                           extra_report_qs=extra)
    assert tel["extra_answers"] == {"u0": 0.8}
    _, _, tel = await rr.run_quality_check(REPORT, "11 mm appendix", "CT AP", [], sections=SECTIONS)
    assert "extra_answers" not in tel  # quick's telemetry shape is unchanged


async def test_extra_report_questions_fail_open_with_the_check(monkeypatch):
    async def down(state, qs):
        raise TimeoutError("jev down")
    monkeypatch.setattr(rr.rc, "_jev", down)
    extra = {"u0": {"type": "noul", "instructions": rr.rc.Q_CONVEYS + "No free gas."}}
    res = await rr.check(REPORT, "x", "CT AP", [], sections=SECTIONS, extra_report_qs=extra)
    assert res.error and res.extra_answers == {}


TECH = "Cardiac MRI at 1.5 T, full protocol: cine, mapping and late gadolinium enhancement."
CMR_HISTORY = "58M. Chest pain. ?Perforation."
CMR = f"""CLINICAL HISTORY
{CMR_HISTORY}

TECHNIQUE
{TECH}

Normal biventricular size and function.

Impression
Normal study."""


async def _omission_state(monkeypatch, **kw) -> str:
    seen = []

    async def fake_jev(state, qs):
        seen.append(state)
        return {k: STATED if k.startswith("i") else {"noul": 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    res = await rr.check(CMR, "full protocol\nperforation", "CMR", [], **kw)
    assert res.error is None
    return next(s for s in seen if s.startswith("REPORT"))


async def test_template_omission_state_keeps_the_technique_text(monkeypatch):
    state = await _omission_state(monkeypatch, sections=SECTIONS, protected=[CMR_HISTORY, TECH], history=CMR_HISTORY)
    assert TECH in state


async def test_template_omission_state_never_shows_the_history(monkeypatch):
    state = await _omission_state(monkeypatch, sections=SECTIONS, protected=[CMR_HISTORY, TECH], history=CMR_HISTORY)
    assert "Perforation" not in state and "Chest pain" not in state


async def test_quick_omission_state_is_unchanged(monkeypatch):
    state = await _omission_state(monkeypatch)
    assert state == f"REPORT:\n{CMR}"
    state = await _omission_state(monkeypatch, protected=[CMR_HISTORY, TECH])
    assert state == f"REPORT:\n{rr.without(CMR, [CMR_HISTORY, TECH])}" and TECH not in state


async def test_run_quality_check_passes_the_history_on(monkeypatch):
    seen = []

    async def fake_jev(state, qs):
        seen.append(state)
        return {k: STATED if k.startswith("i") else {"noul": 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    out, _, tel = await rr.run_quality_check(CMR, "full protocol", "CMR", [], sections=SECTIONS,
                                             protected=[CMR_HISTORY, TECH], history=CMR_HISTORY)
    state = next(s for s in seen if s.startswith("REPORT"))
    assert TECH in state and "Perforation" not in state and out == CMR and tel["error"] is None


# ── brief anchors (negatives one owner, Task 6) ─────────────────────────────

QR = ("FINDINGS:\nA small right pleural effusion. No contralateral pleural effusion. No pleural effusion.\n\n"
      "IMPRESSION:\nSmall right effusion.\n")
QDEC = {"negatives": [
    {"text": "No pleural effusion identified", "action": "contradicted", "source": "sheet",
     "dictated_finding": "Small right pleural effusion"},
    {"text": "No contralateral pleural effusion identified", "action": "keep", "source": "finding:Pleural effusion"}]}


def _contra_jev(scores, types=None, restated=0.9):
    """Fake rc._jev: contradiction question c<i> scores by clause text; restated r<i> high (or `restated`); dictated
    d<i> low; statement type t<j> by sentence text (`types`, default "normal")."""
    async def fake(state, qs):
        out = {}
        for k, q in qs.items():
            text = q.get("instructions", "")
            if k.startswith("c"):
                out[k] = {"noul": next((v for t, v in scores.items() if t in text), 0.05)}
            elif k.startswith("t"):
                t = next((v for s, v in (types or {}).items() if s in text), "normal")
                out[k] = {"choice": t, "probabilities": {t: 0.9}} if t else {"noul": 0.5}
            elif k.startswith("r"):
                out[k] = {"noul": restated}
            elif k.startswith("i"):
                out[k] = {"choice": "stated", "probabilities": {"stated": 0.9}}
            else:
                out[k] = {"noul": 0.05}
        return out
    return fake


async def test_a_kept_negative_is_never_removed_and_becomes_a_conflict(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No contralateral pleural effusion": 0.8}))
    report, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [],
                                                brief_decisions=QDEC)
    assert "No contralateral pleural effusion." in report
    reasons = {c["clause"]: c["reason"] for c in tel["brief_conflicts"]}
    assert reasons["No contralateral pleural effusion."] == "brief_kept"
    # the OMIT label anchored on "No pleural effusion." with a contradiction score below OMIT_CARD_MIN: logged only
    assert "No pleural effusion." not in reasons and "No pleural effusion." in report
    assert [c["clause"] for c in tel["anchor_log"]["omit_low"]] == ["No pleural effusion."]


async def test_a_one_signal_omit_above_the_card_threshold_is_a_card_and_stays(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.4}))
    report, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [],
                                                brief_decisions=QDEC)
    assert "No pleural effusion." in report
    assert {c["clause"]: c["reason"] for c in tel["brief_conflicts"]}["No pleural effusion."] == "brief_omitted"


async def test_a_flagged_omit_negative_is_removed_by_the_l47_path(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.9}))
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    report, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [],
                                                brief_decisions=QDEC)
    assert "No pleural effusion." not in report and "No contralateral pleural effusion." in report
    assert {"type": "removal", "clause": "No pleural effusion."} in tel["applied_edits"]
    anchors = {a["ref"]: a for a in tel["anchors"]}
    assert report[anchors["neg:1"]["span"][0]:anchors["neg:1"]["span"][1]] == "contralateral pleural effusion"
    assert tel["anchor_log"]["labels"] == 2


async def test_without_brief_decisions_or_with_the_kill_switch_nothing_changes(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({}))
    _, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [])
    assert "anchors" not in tel
    monkeypatch.setenv("RR_BRIEF_ANCHOR", "0")
    _, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [], brief_decisions=QDEC)
    assert "anchors" not in tel


async def test_the_brief_never_removes_by_default_it_shadow_logs(monkeypatch):
    # contradiction 0.9 but the restated question is low: no L-47 flag, so only the brief's two signals remain
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.9}, restated=0.1))
    report, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [],
                                                brief_decisions=QDEC)
    assert "No pleural effusion." in report
    (w,) = tel["anchor_log"]["would_remove_by_brief"]
    assert (w["clause"], w["score"], w["refs"], w["action"]) == ("No pleural effusion.", 0.9, ["neg:0"], "contradicted")
    assert {c["clause"]: c["reason"] for c in tel["brief_conflicts"]}["No pleural effusion."] == "brief_omitted"
    assert tel["anchor_log"]["removed_by_brief"] == 0


async def test_rr_brief_remove_removes_the_would_removes(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.9}, restated=0.1))
    monkeypatch.setenv("RR_BRIEF_REMOVE", "1")
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    report, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [],
                                                brief_decisions=QDEC)
    assert "No pleural effusion." not in report and "No contralateral pleural effusion." in report
    assert {"type": "removal", "clause": "No pleural effusion."} in tel["applied_edits"]
    assert "No pleural effusion." not in {c["clause"] for c in tel["brief_conflicts"]}
    assert tel["anchor_log"]["removed_by_brief"] == 1
    anchors = {a["ref"]: a for a in tel["anchors"]}
    assert report[anchors["neg:1"]["span"][0]:anchors["neg:1"]["span"][1]] == "contralateral pleural effusion"


MIXED = "FINDINGS:\nNo pleural effusion with mild atelectasis. The liver is normal.\n\nIMPRESSION:\nAtelectasis.\n"


@pytest.mark.parametrize("answer", ["mixed", "abnormal", None])
async def test_an_l47_removal_needs_a_normal_sentence(monkeypatch, answer):
    """The pre-existing L-47 risk: a flagged "No X with <finding>" must never delete the finding with it."""
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.9},
                                                   types={"mild atelectasis": answer}))
    report, _, tel = await rr.run_quality_check(MIXED, "Pleural effusion. Mild atelectasis", "CT chest", [])
    assert report == MIXED
    assert tel["removal_blocked"] == [{"clause": "No pleural effusion with mild atelectasis.", "why": "sentence_type"}]
    (card,) = tel["brief_conflicts"]
    assert card["reason"] == "removal_blocked" and card["clause"] == "No pleural effusion with mild atelectasis."
    assert "anchors" not in tel


async def test_an_l47_removal_needs_a_normal_sentence_on_the_template_path_too(monkeypatch):
    rep = ("CLINICAL HISTORY\nCough.\n\nTECHNIQUE\nCT.\n\nNo pleural effusion with mild atelectasis.\n\n"
           "Impression\nAtelectasis.\n")
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.9}, types={"mild atelectasis": "mixed"}))
    out, _, tel = await rr.run_quality_check(rep, "Pleural effusion. Mild atelectasis", "CT chest", [],
                                             sections=SECTIONS, protected=["Cough."])
    assert "No pleural effusion with mild atelectasis." in out
    assert tel["removal_blocked"][0]["why"] == "sentence_type"


async def test_a_semicolon_sentence_is_never_removed(monkeypatch):
    rep = "FINDINGS:\nNo pleural effusion; no pneumothorax.\n\nIMPRESSION:\nNormal.\n"
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.9}))
    out, _, tel = await rr.run_quality_check(rep, "Pleural effusion", "CT chest", [])
    assert out == rep and tel["removal_blocked"][0]["why"] == "semicolon"


def test_safe_to_remove_invariant():
    rep = "FINDINGS:\nNo ascites. Mass with no ascites nearby.\n- No effusion\nNo effusion, collection, or air.\n"
    assert rr._safe_to_remove(rep, "No ascites.", "normal", []) is None
    assert rr._safe_to_remove(rep, "No effusion", "normal", []) is None                # a list item
    assert rr._safe_to_remove(rep, "No collection", "normal", []) is None              # a negative-list item
    assert rr._safe_to_remove(rep, "no ascites nearby", "normal", []) == "not_whole"
    assert rr._safe_to_remove(rep, "No ascites.", "mixed", []) == "sentence_type"
    assert rr._safe_to_remove(rep, "No ascites.", None, []) == "sentence_type"
    i = rep.index("ascites")
    keep = ba.Anchor("neg:0", "keep", "sheet", "", "term", [i, i + 7], "ascites", "No ascites.")
    assert rr._safe_to_remove(rep, "No ascites.", "normal", [keep]) == "brief_anchor"
    dic = ba.Anchor("dict:0", "dictated", "dictated", "", "term", [i, i + 7], "ascites", "No ascites.")
    assert rr._safe_to_remove(rep, "No ascites.", "normal", [dic]) == "brief_anchor"
    omit = ba.Anchor("neg:1", "contradicted", "sheet", "", "term", [i, i + 7], "ascites", "No ascites.")
    assert rr._safe_to_remove(rep, "No ascites.", "normal", [omit]) is None
    shadow = ba.Anchor("neg:2", "keep", "sheet", "", "none", shadowed_by="neg:1")
    assert rr._safe_to_remove(rep, "No ascites.", "normal", [omit, shadow]) == "brief_anchor"


async def test_check_asks_the_statement_type_of_each_negative_clause_sentence(monkeypatch):
    seen = {}

    async def fake(state, qs):
        seen.update({k: q for k, q in qs.items() if k.startswith("t")})
        return await _contra_jev({}, types={"mild atelectasis": "mixed"})(state, qs)
    monkeypatch.setattr(rr.rc, "_jev", fake)
    res = await rr.check(MIXED, "x", "CT", [])
    assert res.sentence_type == {"No pleural effusion with mild atelectasis.": "mixed"}
    assert [q["type"] for q in seen.values()] == ["choice"]
    assert "sentence_type" not in res.model_dump() and "contra" not in res.model_dump()
