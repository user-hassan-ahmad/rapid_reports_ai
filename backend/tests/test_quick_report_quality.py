"""Post-generation check (spec 2026-09-30-post-generation-check-design): Jev flags, focal Qwen repair."""
from __future__ import annotations

import asyncio

import pytest

from rapid_reports_ai import quick_report_quality as qq

REPORT = """COMPARISON:
None.

TECHNIQUE:
CT abdomen and pelvis with intravenous contrast.

FINDINGS:
A 3 cm hypodense mass in the pancreatic head compresses the distal common bile duct. No superior mesenteric vein encasement, portal vein encasement, or hepatic deposit. No pericolic or paracolic fluid collection.

The spleen is normal in size.

IMPRESSION:
Pancreatic head mass causing biliary obstruction. Urgent hepatobiliary referral recommended.

Dr A Radiologist"""


def test_sections_and_clauses():
    fnd, imp = qq.report_sections(REPORT)
    assert fnd.startswith("A 3 cm hypodense mass") and fnd.endswith("The spleen is normal in size.")
    assert imp.startswith("Pancreatic head mass") and "Dr A" not in imp
    assert qq.clauses(fnd) == [
        "A 3 cm hypodense mass in the pancreatic head compresses the distal common bile duct.",
        "No superior mesenteric vein encasement",
        "No portal vein encasement",
        "No hepatic deposit",
        "No pericolic or paracolic fluid collection.",     # a bare "or" never splits
        "The spleen is normal in size.",
    ]


def test_every_split_item_is_checked_including_normals_and_negatives():
    # Jev wording v2: the conveys question handles shorthand normals; omitted negatives are restored.
    assert qq.dictated_items("appendix fine. no ascites. liver normal, 2cm cyst L kidney") == [
        "appendix fine", "no ascites", "liver normal, 2cm cyst L kidney"]
    assert qq.positive_items is qq.dictated_items          # alias for the eval script


@pytest.mark.asyncio
async def test_omission_question_uses_conveys_wording(monkeypatch):
    asked = {}
    async def fake_jev(state, qs):
        if state.startswith("REPORT:"):
            asked.update(qs)
        return {k: {"noul": 0.9} for k in qs}
    monkeypatch.setattr(qq.qb, "_jev", fake_jev)
    await qq.check("FINDINGS:\nThe appendix is unremarkable.", "appendix fine. 5 mm defect D1", "CT", [])
    omit = [q["instructions"] for k, q in asked.items() if k.startswith("i")]
    assert len(omit) == 2 and all(t.startswith(qq.Q_CONVEYS) for t in omit)
    assert qq.Q_CONVEYS == ("The report itself states everything this statement says, in any wording, abbreviation "
                            "or synonym (not merely implied or inferable): ")


@pytest.mark.asyncio
async def test_omission_flag_threshold_is_040(monkeypatch):
    async def fake_jev(state, qs):
        return {k: {"noul": 0.45 if k == "i0" else 0.35} for k in qs}
    monkeypatch.setattr(qq.qb, "_jev", fake_jev)
    # (a one-letter word before a full stop reads as an initial, so the items end in words)
    r = await qq.check("FINDINGS:\nx.", "item one. item two", "CT", [])
    assert qq.OMIT_FLAG == 0.40
    assert [f.text for f in r.flags if f.kind == "omission"] == ["item two"]


def test_inserted_negative_must_come_from_an_omitted_negative_item():
    assert qq._negative_allowed("No ascites.", ["no ascites"])
    assert not qq._negative_allowed("No free fluid.", ["no ascites", "5 mm defect"])
    assert not qq._negative_allowed("No ascites.", ["ascites small volume"])   # the item itself is not negative
    assert qq._negative_allowed("A 5 mm defect at D1.", ["5 mm defect"])        # no negation: always allowed


FINDINGS = "- 3 cm hypodense mass at the head of the pancreas\n- CBD dilated to 12 mm\n- Intrahepatic duct dilatation\n- No ascites"
OPTIONS = [{"id": "fn0", "kind": "finding_negative", "sentence": "No intrahepatic biliary duct dilatation."},
           {"id": "fn1", "kind": "finding_negative", "sentence": "No splenic vein thrombus."}]


def _stub_jev(monkeypatch, contra: dict, reported: dict):
    """contra: clause/option text -> score; reported: dictated item -> score. Default 0.05 / 0.95."""
    calls = []
    async def fake(state, questions):
        calls.append((state, questions))
        out = {}
        for k, q in questions.items():
            t = q["instructions"]
            if t.startswith(qq.Q_CONTRA):
                out[k] = {"noul": contra.get(t[len(qq.Q_CONTRA):], 0.05)}
            else:
                out[k] = {"noul": reported.get(t[len(qq.Q_CONVEYS):], 0.95)}
        return out
    monkeypatch.setattr(qq.qb, "_jev", fake)
    return calls


@pytest.mark.asyncio
async def test_check_asks_two_parallel_calls_and_flags(monkeypatch):
    calls = _stub_jev(monkeypatch, {"No portal vein encasement": 0.8, "No intrahepatic biliary duct dilatation.": 0.86},
                      {"CBD dilated to 12 mm": 0.2})
    res = await qq.check(REPORT, FINDINGS, "CT AP", OPTIONS)
    states = sorted(c[0].split("\n")[0] for c in calls)
    assert states == ["REPORT:", "SCAN TYPE: CT AP"]
    contra_qs = [q["instructions"] for s, qs in calls if s.startswith("SCAN") for q in qs.values()]
    assert qq.Q_CONTRA + "No hepatic deposit" in contra_qs and qq.Q_CONTRA + "No splenic vein thrombus." in contra_qs
    omit_qs = [q["instructions"] for s, qs in calls if s.startswith("REPORT") for q in qs.values()]
    assert omit_qs == [qq.Q_CONVEYS + t for t in ("3 cm hypodense mass at the head of the pancreas", "CBD dilated to 12 mm",
                                                  "Intrahepatic duct dilatation", "No ascites")]
    assert [(f.kind, f.text) for f in res.flags] == [("contradiction", "No portal vein encasement"),
                                                     ("omission", "CBD dilated to 12 mm")]
    assert res.bad_option_ids == ["fn0"]
    assert res.error is None


@pytest.mark.asyncio
async def test_check_failure_returns_no_flags_and_the_reason(monkeypatch):
    async def boom(state, questions):
        raise RuntimeError("jev down")
    monkeypatch.setattr(qq.qb, "_jev", boom)
    res = await qq.check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert res.flags == [] and res.bad_option_ids == [] and "jev down" in res.error


def _stub_repair(monkeypatch, edits, seen=None):
    async def fake(**kw):
        if seen is not None:
            seen.update(kw)
        class R:
            output = qq.RepairEdits(edits=edits)
        return R()
    monkeypatch.setattr(qq, "_run_agent_with_model", fake)


@pytest.mark.asyncio
async def test_repair_applies_only_unique_verbatim_edits(monkeypatch):
    seen = {}
    _stub_repair(monkeypatch, [
        {"find": "No superior mesenteric vein encasement, portal vein encasement, or hepatic deposit.",
         "replace": "No superior mesenteric vein encasement or hepatic deposit."},
        {"find": "compresses the distal common bile duct.",
         "replace": "compresses the distal common bile duct, which is dilated to 12 mm."},
        {"find": "text that is not in the report", "replace": "x"},
        {"find": "No", "replace": "Yes"},                                      # occurs more than once
    ], seen)
    problems = ["The report states 'No portal vein encasement' but the dictation contradicts it.",
                "The dictated finding 'CBD dilated to 12 mm' is missing from the report."]
    res = await qq.repair_report(REPORT, FINDINGS, problems)
    assert "1. The report states" in seen["user_prompt"] and "2. The dictated finding" in seen["user_prompt"]
    assert "portal vein encasement" not in res.report and "dilated to 12 mm" in res.report
    assert res.applied == 2 and res.skipped == 2 and res.error is None


@pytest.mark.asyncio
async def test_repair_failure_returns_the_report_unchanged(monkeypatch):
    async def boom(**kw):
        raise asyncio.TimeoutError
    monkeypatch.setattr(qq, "_run_agent_with_model", boom)
    res = await qq.repair_report(REPORT, FINDINGS, ["anything"])
    assert res.report == REPORT and res.applied == 0 and res.error


@pytest.mark.asyncio
async def test_run_quality_check_repairs_on_report_flags_and_drops_bad_options(monkeypatch):
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="contradiction", text="No portal vein encasement", score=0.8),
                                     qq.Flag(kind="omission", text="CBD dilated to 12 mm", score=0.2)],
                              bad_option_ids=["fn0"], n_clauses=9, n_items=3)
    seen = {}
    async def fake_insert(report, findings, items):
        seen["items"] = items
        return qq.RepairResult(report=report, applied=1, skipped=1)
    async def no_repair(*a, **k):
        raise AssertionError("no positive contradiction to correct")
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "repair_report", no_repair)
    monkeypatch.setattr(qq, "insert_findings", fake_insert)
    report, options, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert seen["items"] == ["CBD dilated to 12 mm"]
    assert "portal vein encasement" not in report                     # removed in code
    assert [o["id"] for o in options] == ["fn1"]
    assert tel["edits_applied"] == 1 and tel["edits_skipped"] == 1 and tel["options_dropped"] == ["fn0"]
    assert [f["kind"] for f in tel["flags"]] == ["contradiction", "omission"] and tel["error"] is None


@pytest.mark.asyncio
async def test_no_report_flags_means_no_repair_call(monkeypatch):
    async def clean(report, findings, scan_type, options):
        return qq.CheckResult(bad_option_ids=["fn0"])
    async def must_not_run(*a):
        raise AssertionError("repair called without a report flag")
    monkeypatch.setattr(qq, "check", clean)
    monkeypatch.setattr(qq, "repair_report", must_not_run)
    report, options, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert report == REPORT and [o["id"] for o in options] == ["fn1"] and tel["repair_ms"] is None


@pytest.mark.asyncio
async def test_kill_switch_and_never_raising(monkeypatch):
    monkeypatch.setenv("RR_QUALITY_CHECK", "0")
    report, options, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert report == REPORT and options == OPTIONS and tel == {"enabled": False}
    monkeypatch.delenv("RR_QUALITY_CHECK")
    async def boom(*a):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(qq, "check", boom)
    report, options, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert report == REPORT and options == OPTIONS and "unexpected" in tel["error"]


@pytest.mark.asyncio
async def test_generator_runs_the_check_before_the_signature_and_reports_it(monkeypatch):
    from rapid_reports_ai import quick_report_generator as qrg
    async def no_brief(*a, **k):
        raise RuntimeError("no brief in this test")
    async def fake_run(**kw):
        from types import SimpleNamespace
        return SimpleNamespace(output=REPORT.split("\n\nDr ")[0] if kw.get("output_type") is str
                               else SimpleNamespace(description="d"))
    seen = {}
    async def fake_quality(report, findings, scan_type, options):
        seen["report"] = report
        return report.replace("The spleen", "The SPLEEN"), options, {"enabled": True, "edits_applied": 1}
    monkeypatch.setattr(qrg, "compile_brief", no_brief)
    monkeypatch.setattr(qrg, "_run_agent_with_model", fake_run)
    monkeypatch.setattr(qrg, "_get_api_key_for_provider", lambda p, fallback_api_key=None: "k")
    monkeypatch.setattr(qrg, "run_quality_check", fake_quality)
    out = await qrg.generate_quick_report(skill_sheet="S", scan_type="CT", findings="f", clinical_history="h",
                                          user_signature="Dr Sig")
    assert "Dr Sig" not in seen["report"]
    assert "The SPLEEN" in out["report_content"] and out["report_content"].endswith("Dr Sig")
    assert out["quality_check"] == {"enabled": True, "edits_applied": 1}


def test_negative_clauses_are_removed_in_code_never_inverted():
    rep = ("FINDINGS:\nNo subfalcine or transtentorial herniation, intraventricular haemorrhage, or acute ischaemic "
           "change identified. No focal mass-like colonic wall thickening is identified. The liver is normal.\n\n"
           "IMPRESSION:\nHaemorrhage.")
    out = qq.remove_negative_clause(rep, "No subfalcine or transtentorial herniation")
    assert "No intraventricular haemorrhage or acute ischaemic change identified." in out
    out = qq.remove_negative_clause(out, "No focal mass-like colonic wall thickening is identified.")
    assert "mass-like" not in out and "The liver is normal." in out
    assert qq.remove_negative_clause(out, "text not present") == out


def test_edits_that_drop_a_negation_or_rewrite_on_insert_only_are_rejected():
    assert not qq.edit_allowed(qq.Edit(find="No focal mass-like colonic wall thickening is identified.",
                                       replace="Focal mass-like colonic wall thickening is identified."), insert_only=False)
    assert qq.edit_allowed(qq.Edit(find="mass with encasement of the SMV", replace="mass abutting the SMV"), insert_only=False)
    assert not qq.edit_allowed(qq.Edit(find="focal active arterial extravasation", replace="focal active arterial blush"),
                               insert_only=True)
    assert qq.edit_allowed(qq.Edit(find="compresses the duct.", replace="compresses the duct. The CBD measures 12 mm."),
                           insert_only=True)


@pytest.mark.asyncio
async def test_run_quality_check_routes_each_flag_to_its_safe_repair(monkeypatch):
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="contradiction", text="No portal vein encasement", score=0.8),
                                     qq.Flag(kind="contradiction", text="Pancreatic head mass causing biliary obstruction.", score=0.8),
                                     qq.Flag(kind="omission", text="CBD dilated to 12 mm", score=0.2)])
    calls = []
    async def fake_repair(report, findings, problems, insert_only=False):
        calls.append(("correct", problems))
        return qq.RepairResult(report=report, applied=0, skipped=0)
    async def fake_insert(report, findings, items):
        calls.append(("insert", items))
        return qq.RepairResult(report=report, applied=0, skipped=0)
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "repair_report", fake_repair)
    monkeypatch.setattr(qq, "insert_findings", fake_insert)
    report, _, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", [])
    assert "portal vein encasement" not in report and "No superior mesenteric vein encasement or hepatic deposit." in report
    assert calls == [("correct", ['The report states "Pancreatic head mass causing biliary obstruction.", which the dictated findings contradict.']),
                     ("insert", ["CBD dilated to 12 mm"])]
    assert tel["clauses_removed"] == 1


@pytest.mark.asyncio
async def test_a_correction_and_an_insertion_both_land(monkeypatch):
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="contradiction", text="Pancreatic head mass causing biliary obstruction.", score=0.8),
                                     qq.Flag(kind="omission", text="CBD dilated to 12 mm", score=0.2)])
    async def fake_insert(report, findings, items):
        return qq.RepairResult(report=report.replace("distal common bile duct.", "distal common bile duct, dilated to 12 mm."), applied=1)
    async def fake_repair(report, findings, problems, insert_only=False):
        return qq.RepairResult(report=report.replace("causing biliary obstruction", "compressing the distal bile duct"), applied=1)
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "repair_report", fake_repair)
    monkeypatch.setattr(qq, "insert_findings", fake_insert)
    report, _, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", [])
    assert "dilated to 12 mm" in report and "compressing the distal bile duct" in report and tel["edits_applied"] == 2


@pytest.mark.asyncio
async def test_omitted_findings_are_inserted_by_code_after_an_anchor(monkeypatch):
    async def fake(**kw):
        class R:
            output = qq.Insertions(items=[
                {"after": "compresses the distal common bile duct.", "sentence": "The common bile duct is dilated to 12 mm."},
                {"after": "a sentence that is not there", "sentence": "Intrahepatic ducts are dilated."},
                {"after": "The spleen is normal in size.", "sentence": ""}])
        return R()
    monkeypatch.setattr(qq, "_run_agent_with_model", fake)
    _jev_scores(monkeypatch, 0.05)
    res = await qq.insert_findings(REPORT, FINDINGS, ["CBD dilated to 12 mm", "Intrahepatic duct dilatation", "x"])
    fnd, _ = qq.report_sections(res.report)
    assert "compresses the distal common bile duct. The common bile duct is dilated to 12 mm." in fnd
    assert fnd.startswith("Intrahepatic ducts are dilated. A 3 cm")        # unknown anchor: first in FINDINGS
    assert res.applied == 2 and res.skipped == 1
    assert REPORT.replace(" ", "") in res.report.replace(" ", "").replace("Thecommonbileductisdilatedto12mm.", "").replace("Intrahepaticductsaredilated.", "")


def test_restatement_turns_a_negative_into_the_finding_it_denies():
    assert qq.restate("No irregular asymmetric wall thickening with loss of pericolonic fat planes is identified.") == \
        "irregular asymmetric wall thickening with loss of pericolonic fat planes"
    assert qq.restate("There is no portal vein encasement") == "portal vein encasement"
    assert qq.restate("No hepatic deposit identified.") == "hepatic deposit"


@pytest.mark.asyncio
async def test_a_negative_is_flagged_only_when_its_restatement_is_dictated(monkeypatch):
    async def fake(state, questions):
        out = {}
        for k, q in questions.items():
            t = q["instructions"]
            if t.startswith(qq.Q_CONTRA):
                out[k] = {"noul": 0.8 if "encasement" in t or "hepatic deposit" in t else 0.05}
            elif q.get("criteria") and t.startswith(qq.Q_RESTATED):
                out[k] = {"noul": 0.9 if "portal vein" in t else 0.1}
            else:
                out[k] = {"noul": 0.95}
        return out
    monkeypatch.setattr(qq.qb, "_jev", fake)
    res = await qq.check(REPORT, FINDINGS, "CT AP", [])
    assert [f.text for f in res.flags] == ["No portal vein encasement"]   # SMV and hepatic deposit not confirmed


@pytest.mark.asyncio
async def test_an_insertion_that_repeats_a_report_sentence_is_skipped(monkeypatch):
    async def fake(**kw):
        class R:
            output = qq.Insertions(items=[{"after": "The spleen is normal in size.",
                                           "sentence": "A 3 cm hypodense mass in the pancreatic head compresses the common bile duct."}])
        return R()
    monkeypatch.setattr(qq, "_run_agent_with_model", fake)
    _jev_down(monkeypatch)                                   # the word-overlap fallback
    res = await qq.insert_findings(REPORT, FINDINGS, ["3 cm hypodense mass at the head of the pancreas"])
    assert res.report == REPORT and res.applied == 0 and res.skipped == 1


def test_restates_ignores_filler_words():
    assert qq._restates("An incidental 5 mm right upper lobe pulmonary nodule is noted.",
                        "A 5 mm right upper lobe pulmonary nodule is present.")
    assert not qq._restates("The common bile duct is dilated to 12 mm.",
                            "A mass compresses the distal common bile duct.")


# ── inserter duplicate guard: Jev, word overlap as the fallback (L-49) ──────

def _jev_scores(monkeypatch, score, seen=None):
    async def fake_jev(state, qs):
        if seen is not None:
            seen.append((state, qs))
        return {k: {"noul": score(qs[k]["instructions"]) if callable(score) else score} for k in qs}
    monkeypatch.setattr(qq.qb, "_jev", fake_jev)


def _jev_down(monkeypatch):
    import httpx
    async def boom(state, qs):
        raise httpx.ReadTimeout("jev timeout")
    monkeypatch.setattr(qq.qb, "_jev", boom)


def _insertions(monkeypatch, *sentences):
    from types import SimpleNamespace
    async def fake_run(**kw):
        return SimpleNamespace(output=qq.Insertions(items=[qq.Insertion(after="", sentence=t) for t in sentences]))
    monkeypatch.setattr(qq, "_run_agent_with_model", fake_run)


@pytest.mark.asyncio
async def test_inserter_skips_sentence_jev_says_is_conveyed(monkeypatch):
    _insertions(monkeypatch, "The appendix is fine.")
    seen = []
    _jev_scores(monkeypatch, 0.9, seen)
    r = await qq.insert_findings("FINDINGS:\nThe appendix is unremarkable.", "appendix fine", ["appendix fine"])
    assert r.applied == 0 and r.skipped == 1 and "fine" not in r.report and r.dup_check == "jev"
    (state, qs), = seen
    assert state == "REPORT:\nFINDINGS:\nThe appendix is unremarkable."
    assert [q["instructions"] for q in qs.values()] == [qq.Q_CONVEYS + "The appendix is fine."]


@pytest.mark.asyncio
async def test_inserter_dup_threshold_is_025(monkeypatch):
    _insertions(monkeypatch, "Small bowel loops are normal.", "A 5 mm defect at D1.")
    _jev_scores(monkeypatch, lambda t: 0.25 if "bowel" in t else 0.2)
    r = await qq.insert_findings("FINDINGS:\nThe appendix is unremarkable.", "x", ["small bowel normal", "5 mm defect D1"])
    assert qq.INSERT_DUP == 0.25
    assert r.applied == 1 and r.skipped == 1 and "5 mm defect" in r.report and "bowel" not in r.report


@pytest.mark.asyncio
async def test_inserter_falls_back_to_word_overlap_when_jev_fails(monkeypatch):
    _insertions(monkeypatch, "The appendix is unremarkable.", "5 mm defect at D1.")
    _jev_down(monkeypatch)
    r = await qq.insert_findings("FINDINGS:\nThe appendix is unremarkable.", "appendix fine. 5 mm defect D1",
                                 ["appendix fine", "5 mm defect D1"])
    assert r.applied == 1 and r.skipped == 1 and r.dup_check == "words"
    assert r.report == "FINDINGS:\n5 mm defect at D1. The appendix is unremarkable."


def test_restated_question_counts_a_finding_raised_as_a_possibility():
    q = qq.q_restated("pneumothorax")
    assert q["type"] == "noul"
    assert q["instructions"] == "The dictated findings report this finding, including as a possibility: pneumothorax"
    assert q["criteria"]["true"].startswith("This same finding is reported") and "as present or possible" in q["criteria"]["true"]
    assert "a different qualifier such as size" in q["criteria"]["false"]


@pytest.mark.asyncio
async def test_a_report_negative_contradicting_a_hedged_dictated_finding_is_removed(monkeypatch):
    asked = {}
    async def fake(state, questions):
        asked.update(questions)
        out = {}
        for k, q in questions.items():
            t = q["instructions"]
            out[k] = {"noul": 0.8 if t == qq.Q_CONTRA + "No pneumothorax." else
                              0.6 if t == qq.q_restated("pneumothorax")["instructions"] else
                              0.9 if t.startswith(qq.Q_CONVEYS) else 0.05}
        return out
    monkeypatch.setattr(qq.qb, "_jev", fake)
    report = "FINDINGS:\nNo pneumothorax. The lungs are clear.\n\nIMPRESSION:\nNo acute abnormality."
    out, _, tel = await qq.run_quality_check(report, "?pneumothorax", "CXR", [])
    assert any(q == qq.q_restated("pneumothorax") for q in asked.values())
    assert qq.RESTATED_FLAG == 0.5
    assert "No pneumothorax" not in out and "The lungs are clear." in out and tel["clauses_removed"] == 1
