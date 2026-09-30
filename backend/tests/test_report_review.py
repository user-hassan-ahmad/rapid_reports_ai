"""Section-generic review (spec §4): template headings, implicit sections, protected spans."""
from __future__ import annotations

import pytest

from rapid_reports_ai import report_review as rr


@pytest.fixture(autouse=True)
def _no_live_jev(monkeypatch):
    """A test that forgets to stub Jev fails loudly instead of timing out on the network."""
    async def unstubbed(*a, **k):
        raise AssertionError("unstubbed Jev call")
    monkeypatch.setattr(rr.rc, "_jev", unstubbed)

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
