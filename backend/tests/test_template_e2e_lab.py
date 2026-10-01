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


def test_first_with_picks_the_dir_holding_the_set(tmp_path):
    (tmp_path / "b" / "set_x").mkdir(parents=True)
    assert lab.first_with(f"{tmp_path / 'a'},{tmp_path / 'b'}", "set_x") == tmp_path / "b"
    assert lab.first_with("", "set_x") is None


async def test_jev_counter_records_requests_made_inside_a_counted_run(monkeypatch):
    import asyncio

    calls = []

    async def fake(state, qs):
        calls.append(state)
        return {}
    monkeypatch.setattr(lab.rc, "_jev", fake)
    lab.install_jev_counter()
    lab.install_jev_counter()  # idempotent: one wrapper

    async def run():
        log = []
        lab._JEV_LOG.set(log)
        await asyncio.gather(lab.rc._jev("a", {"x": 1, "y": 2}), lab.rc._jev("b", {"z": 3}))
        return log
    assert await run() == [2, 1]
    await lab.rc._jev("outside", {"x": 1})  # outside a counted run: forwarded, not recorded
    assert calls == ["a", "b", "outside"]


def _saved_run(tmp_path, set_name="set_a", did="set_a-d1"):
    d = tmp_path / "run1" / set_name
    d.mkdir(parents=True)
    rec = {"id": did, "new": {"lat": {"phase1_s": 12.3}, "master_sheet": "# Master\n\n## Case Deliberation\nQUESTION \"q\"\n",
                              "phase1": {"usable": True, "errors": [], "model": "m", "question": "q",
                                         "differentials": [{"name": "A", "tier": "triage", "visible": "yes"}],
                                         "recommendations": [], "placements": [], "placement_paragraphs": [],
                                         "rejected": [], "raw": "## Case Deliberation\nQUESTION \"q\"\n"}}}
    (d / f"{did}.json").write_text(__import__("json").dumps(rec))
    return tmp_path / "run1"


async def test_reuse_phase1_loads_saved_output_and_skips_the_call(tmp_path, monkeypatch):
    run = _saved_run(tmp_path)

    async def boom(*a, **k):
        raise AssertionError("Phase 1 must not be called when its output is reused")
    monkeypatch.setattr(lab.ca, "deliberate", boom)
    saved = lab.saved_phase1(f"{tmp_path / 'nope'},{run}", "set_a", "set_a-d1")
    assert saved and saved["reused_from"].endswith("set_a-d1.json")
    got = await lab.run_phase1("# Skill Sheet\n", {"id": "set_a-d1", "scan_type": "CMR", "clinical_history": "h"}, saved)
    assert got["master_sheet"].startswith("# Master") and got["phase1"]["question"] == "q"
    assert got["phase1"]["reused_from"] == saved["reused_from"] and got["phase1_s"] == 12.3


async def test_reuse_phase1_runs_phase1_when_nothing_saved(tmp_path, monkeypatch):
    run = _saved_run(tmp_path)
    calls = []

    async def fake(sheet, summary, scan_type, history):
        calls.append(history)
        return lab.ca.CaseResult(errors=["x"], raw="r", ms=1000)
    monkeypatch.setattr(lab.ca, "deliberate", fake)
    monkeypatch.setattr(lab.ca, "summarise_template", lambda s: {})
    assert lab.saved_phase1(str(run), "set_a", "set_a-d9") is None
    got = await lab.run_phase1("# Skill Sheet\n", {"id": "set_a-d9", "scan_type": "CMR", "clinical_history": "h"},
                               None, reuse_requested=True)
    assert calls == ["h"] and got["phase1"]["reuse_missing"] is True and got["master_sheet"] == "# Skill Sheet\n"
    assert got["phase1"]["raw"] == "r" and "units_block" in got["phase1"]


def test_phase1_repeat_markdown_lists_each_run_side_by_side():
    runs = [{"differentials": [{"name": "HCM", "tier": "triage", "visible": "yes"}],
             "recommendations": [{"tag": "REFERRAL", "text": "Refer", "when": "LVH"}],
             "placement_units": [{"kind": "NEGATIVE", "text": "No RV thinning", "key": "ACM", "paragraph": "RV"},
                                 {"kind": "IF_PRESENT", "text": "No apical aneurysm", "key": "LVH", "paragraph": "LV"}]},
            {"differentials": [{"name": "DCM", "tier": "secondary", "visible": "no"}], "recommendations": [],
             "placement_units": []}]
    md = lab.render_phase1_repeat([{"set": "s", "id": "s-d1", "runs": runs}])
    assert "s-d1" in md and "HCM (triage, visible yes)" in md and "DCM (secondary, visible no)" in md
    assert "No RV thinning" in md and "No apical aneurysm" in md and "Refer" in md
    assert "run 1" in md and "run 2" in md
