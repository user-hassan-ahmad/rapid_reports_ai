"""Section-generic review (spec §4): template headings, implicit sections, protected spans."""
from __future__ import annotations

import pytest

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


def test_edit_guard_rejects_protected_spans_and_suppressed_terms():
    history = "67F. Abdominal pain. ?Appendicitis."
    assert not rr.edit_allowed(rr.Edit(find="Abdominal pain.", replace="Pain."), False, protected=[history])
    assert not rr.edit_allowed(rr.Edit(find="The spleen is unremarkable.", replace="The spleen is normal."),
                               False, suppressed=["normal"])
    assert rr.edit_allowed(rr.Edit(find="The appendix is dilated.", replace="The appendix is dilated to 11 mm."),
                           False, protected=[history], suppressed=["normal"])


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
    monkeypatch.setattr(rr, "repair_report", no_repair)
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


def test_edit_guard_rejects_partial_overlap_with_protected_text():
    history = "67F. Abdominal pain. ?Appendicitis."
    e = rr.Edit(find="?Appendicitis.\n\nTECHNIQUE", replace="?Appendicitis.\n\nMETHOD")
    assert not rr.edit_allowed(e, False, protected=[history])
    assert not rr.edit_allowed(e, False, protected=[history], report=REPORT)
    assert rr.edit_allowed(rr.Edit(find="Portal venous phase CT.", replace="Portal venous phase CT abdomen."),
                           False, protected=[history], report=REPORT)


def test_suppressed_terms_with_non_word_edges():
    assert not rr.edit_allowed(rr.Edit(find="Ascites.", replace="Ascites +ve."), False, suppressed=["+ve"])
    assert rr.edit_allowed(rr.Edit(find="Ascites.", replace="Ascites, moderate."), False, suppressed=["+ve"])


async def test_insertion_anchor_on_a_header_falls_back_to_the_findings_section(monkeypatch):
    _fake_model(monkeypatch, rr.Insertions(items=[
        rr.Insertion(after="CLINICAL HISTORY", sentence="Small volume pelvic free fluid.")]))
    res = await rr.insert_findings(REPORT, "x", ["pelvic fluid"], SECTIONS,
                                   ["67F. Abdominal pain. ?Appendicitis."])
    assert "CLINICAL HISTORY Small" not in res.report and res.applied == 1
    assert "Small volume pelvic free fluid. The appendix is dilated" in res.report


async def test_insertion_anchor_in_protected_text_is_not_used(monkeypatch):
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
        return {k: {"noul": 0.9 if k.startswith("i") else 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    secs = SECTIONS + [rr.ReportSection(name="RECOMMENDATION", header="Recommendation", role="other")]
    out, _, tel = await rr.run_quality_check(REPORT.replace("\n", "\r\n"), "11 mm appendix", "CT", [],
                                             sections=secs, protected=["67F. Abdominal pain. ?Appendicitis."])
    assert out == REPORT and tel["error"] is None
    assert tel["sections_found"] == ["CLINICAL HISTORY", "TECHNIQUE", "FINDINGS", "IMPRESSION"]
    assert tel["sections_missing"] == ["RECOMMENDATION"]


def test_without_removes_the_protected_occurrence_only():
    secs = [rr.ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            rr.ReportSection(name="FINDINGS", header="FINDINGS", role="findings")]
    report = "CLINICAL HISTORY\nNo ascites.\n\nFINDINGS\nLiver normal. No ascites."
    assert rr.without(report, ["No ascites."], secs) == "CLINICAL HISTORY\n\n\nFINDINGS\nLiver normal. No ascites."
