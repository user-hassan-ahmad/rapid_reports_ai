"""Scoring helpers of the end-to-end templated lab (no model calls)."""
from rapid_reports_ai.scripts import template_e2e_lab as lab

SECTIONS = [{"name": "CLINICAL DETAILS", "header": "CLINICAL DETAILS:", "role": "history"},
            {"name": "FINDINGS", "header": "FINDINGS:", "role": "findings"},
            {"name": "CONCLUSION", "header": "CONCLUSION:", "role": "impression"}]
REPORT = ("CLINICAL DETAILS:\n58M. Sudden pain after regular ibuprofen use. ?Perforation.\n\nFINDINGS:\n"
          "Moderate free fluid in the upper abdomen, with no organised collection. The kidneys are unremarkable "
          "with no hydronephrosis.\n\nCONCLUSION:\n1. Perforation.\nKEEP: something")


def test_negation_must_govern_the_finding():
    assert lab.asserted_parts("No free fluid or collection.", REPORT)[0]["part"] == "collection"
    assert len(lab.asserted_parts("No free fluid or collection.", REPORT)) == 1  # free fluid is positive here
    assert lab.asserted_parts("no hydronephrosis", REPORT)
    assert not lab.asserted_parts("No free intraperitoneal gas.", REPORT)


def test_sections_and_history_exclusion():
    parts = lab.split_sections(REPORT, SECTIONS)
    assert parts["CLINICAL DETAILS"].startswith("58M") and "Moderate free fluid" in parts["FINDINGS"]
    body = lab.without_history(REPORT, SECTIONS)
    assert "ibuprofen" not in body
    assert lab.history_leaks("58M. Sudden pain after regular ibuprofen use.", "free fluid", body) == []
    leak = lab.history_leaks("58M. regular ibuprofen use", "x", body + " Known regular ibuprofen use. 58M")
    assert "regular ibuprofen use" in leak and any("age/sex" in x for x in leak)


def test_label_leaks_ignore_headers():
    leaks = lab.label_leaks(REPORT, SECTIONS)
    assert len(leaks) == 1 and leaks[0].startswith("KEEP")


def test_present_containment():
    assert lab.present("Free intraperitoneal gas as described above.", "Free intraperitoneal gas as described above.") == 1.0
    assert lab.present("Recommend urgent surgical review.", REPORT) < 0.6


def test_reuse_sheets_falls_back_to_sheet_files(tmp_path):
    d = tmp_path / "set_a"
    d.mkdir()
    (d / "lean_sheet.md").write_text("# Skill Sheet\n")
    (d / "baseline_sheet.md").write_text("")  # a failed baseline: rebuilt, never reused
    got = lab.reused_sheets(tmp_path, "set_a")
    assert got["lean"]["sheet"] == "# Skill Sheet\n" and "baseline" not in got
    assert lab.reused_sheets(None, "set_a") == {} and lab.reused_sheets(tmp_path, "missing") == {}


async def test_baseline_retries_once_only_on_no_json(monkeypatch):
    from rapid_reports_ai import template_manager as tm
    calls = []

    async def flaky(self, examples, scan_type, api_key=""):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("No JSON object found in model response. Raw: ...")
        return {"skill_sheet": "SHEET"}
    monkeypatch.setattr(tm.TemplateManager, "analyze_examples_to_skill_sheet", flaky)
    got = await lab.baseline_sheet([{"content": "x"}], "CT")
    assert got["sheet"] == "SHEET" and len(got["failed_attempts"]) == 1 and len(calls) == 2

    calls.clear()

    async def broken(self, examples, scan_type, api_key=""):
        calls.append(1)
        raise RuntimeError("provider down")
    monkeypatch.setattr(tm.TemplateManager, "analyze_examples_to_skill_sheet", broken)
    got = await lab.baseline_sheet([{"content": "x"}], "CT")
    assert got["sheet"] == "" and len(calls) == 1  # any other failure: no retry


def test_stated_negatives_are_classified_and_flagged_beside_a_dictated_positive():
    findings = "moderate free fluid upper abdo and pelvis, no organised collection. no nodes"
    negs = lab.negative_clauses(REPORT + "\nNo pericolic fluid. No lymphadenopathy.", SECTIONS)
    assert "No pericolic fluid." in negs and not any("ibuprofen" in c for c in negs)
    srcs = {"case negative (Phase 1)": ["No pericolic fluid."], "template sweep negative": ["No lymphadenopathy."]}
    assert lab.classify_negative("No pericolic fluid.", findings, srcs) == "case negative (Phase 1)"
    assert lab.classify_negative("No organised collection.", findings, srcs) == "dictated"
    assert lab.beside_positive("No pericolic fluid.", findings)  # fluid / dictated free fluid
    assert not lab.beside_positive("No lymphadenopathy.", findings)
