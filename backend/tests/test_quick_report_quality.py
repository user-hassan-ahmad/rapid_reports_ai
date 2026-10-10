"""Post-generation check (spec 2026-09-30-post-generation-check-design): Jev flags, focal Qwen repair."""
from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from rapid_reports_ai import report_review as qq

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
    fnd, imp = qq.report_sections(qq.report_body(REPORT))      # the final report: its signature is stripped first
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


def test_regex_fallback_selection_drops_negatives_and_background():
    findings = ("- 3 cm pancreatic head mass\n- CBD dilated to 12 mm\n- No ascites\n"
                "- Liver, spleen, kidneys unremarkable\n- Lung bases clear\n- Nil else")
    assert qq.positive_items(findings) == ["3 cm pancreatic head mass", "CBD dilated to 12 mm"]


def test_selector_questions_are_the_group_f_strings():
    ch = qq.q_select_choice("2cm cyst L kidney")
    assert ch["type"] == "choice"
    assert ch["instructions"] == ('Read only this one dictated line, not the rest of the dictation: "2cm cyst L kidney". '
                                  'What does this line report?')
    assert list(ch["criteria"]) == ["abnormal_finding", "limitation", "normal_or_negative", "protocol_note", "comparison",
                                    "mixed_abnormal_and_normal"]
    t1 = qq.q_select_noul("2cm cyst L kidney")
    assert t1["type"] == "noul"
    assert t1["instructions"] == 'The dictated line "2cm cyst L kidney" itself reports an abnormality or a limitation of the study.'
    assert t1["criteria"]["true"].startswith("The line itself reports something abnormal or present in the patient")
    assert t1["criteria"]["false"].startswith("The line itself only says that structures are normal")


def test_selection_is_the_mean_of_ch2sel_and_t1_at_045():
    ch = lambda a, l, m: {"probabilities": {"abnormal_finding": a, "limitation": l, "normal_or_negative": 1 - a - l - m,
                                            "protocol_note": 0, "comparison": 0, "mixed_abnormal_and_normal": m}}
    assert qq.selected("x", ch(0.3, 0.1, 0.05), {"noul": 0.45}) is True          # (0.45 + 0.45) / 2
    assert qq.selected("x", ch(0.2, 0.1, 0.05), {"noul": 0.5}) is False          # (0.35 + 0.5) / 2
    # unreadable answers fall back to the regex, item by item
    assert qq.selected("2cm cyst L kidney", None, {"noul": 0.9}) is True
    assert qq.selected("appendix fine", {"choice": "x"}, None) is True             # regex has no background word here
    assert qq.selected("liver normal", None, None) is False


def _cls(c, p=0.9):
    """A Jev choice answer for the omission classifier with `c` on top."""
    rest = [k for k in qq._OMIT_CHOICES if k != c]
    probs = {c: p, **{k: (1 - p) / len(rest) for k in rest}}
    return {"choice": c, "confidence": p, "probabilities": probs}


def test_omission_question_is_the_classify_choice():
    q = qq.q_omission("2cm cyst L kidney")
    assert q["type"] == "choice"
    assert q["instructions"] == ('Read only this one dictated line: "2cm cyst L kidney". Find what the report says about '
                                 'the same finding or structure, then choose how the report covers this line.')
    assert list(q["criteria"]) == ["stated", "partial", "absent", "different", "unclear"]
    assert q["criteria"]["absent"].startswith("Nothing in the report is about this line's abnormality")
    assert q["criteria"]["unclear"].startswith("The line is only a heading or a fragment")


@pytest.mark.asyncio
async def test_omission_classifier_rides_the_report_call(monkeypatch):
    asked = {}
    async def fake_jev(state, qs):
        if state.startswith("REPORT:"):
            asked.update(qs)
            return {k: _cls("stated") for k in qs}
        return {k: {"noul": 0.9} for k in qs}
    monkeypatch.setattr(qq.rc, "_jev", fake_jev)
    await qq.check("FINDINGS:\nThe appendix is unremarkable.", "appendix fine. 5 mm defect D1", "CT", [])
    assert asked == {"i0": qq.q_omission("appendix fine"), "i1": qq.q_omission("5 mm defect D1")}


@pytest.mark.asyncio
async def test_each_class_routes_to_its_own_flag(monkeypatch):
    by_line = {"aa one": "absent", "bb two": "partial", "cc three": "different", "dd four": "stated",
               "ee five": "unclear"}
    async def fake_jev(state, qs):
        if state.startswith("REPORT:"):
            return {k: _cls(next(c for t, c in by_line.items() if f'"{t}"' in q["instructions"])) for k, q in qs.items()}
        return {k: {"noul": 0.05} for k in qs}    # no contradiction; unreadable selector choice -> the regex selects
    monkeypatch.setattr(qq.rc, "_jev", fake_jev)
    r = await qq.check("FINDINGS:\nThe liver is cirrhotic.", "aa one. bb two. cc three. dd four. ee five", "CT", [])
    assert [(f.kind, f.text) for f in r.flags] == [("omission", "aa one"), ("partial", "bb two"), ("differs", "cc three")]
    assert r.flags[0].score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_an_unreadable_classifier_answer_raises_no_flag(monkeypatch):
    async def fake_jev(state, qs):
        return {k: {"noul": 0.05} for k in qs}     # no probabilities: the omission answer is unreadable
    monkeypatch.setattr(qq.rc, "_jev", fake_jev)
    r = await qq.check("FINDINGS:\nx.", "item one. item two", "CT", [])
    assert [f for f in r.flags if f.kind in ("omission", "partial", "differs")] == []


def test_missing_detail_is_the_line_words_the_report_lacks():
    rep = "FINDINGS:\nA 3 mm calculus is seen in the left distal ureter with mild hydronephrosis."
    assert qq.missing_detail("3 mm calculus left distal ureter, HU 254, mild hydronephrosis", rep) == "HU 254"
    assert qq.missing_detail("3 mm calculus left distal ureter", rep) is None


def test_inserted_negative_must_come_from_an_omitted_negative_item():
    assert qq._negative_allowed("No ascites.", ["no ascites"])
    assert not qq._negative_allowed("No free fluid.", ["no ascites", "5 mm defect"])
    assert not qq._negative_allowed("No ascites.", ["ascites small volume"])   # the item itself is not negative
    assert qq._negative_allowed("A 5 mm defect at D1.", ["5 mm defect"])        # no negation: always allowed


FINDINGS = "- 3 cm hypodense mass at the head of the pancreas\n- CBD dilated to 12 mm\n- Intrahepatic duct dilatation\n- No ascites"
OPTIONS = [{"id": "fn0", "kind": "finding_negative", "sentence": "No intrahepatic biliary duct dilatation."},
           {"id": "fn1", "kind": "finding_negative", "sentence": "No splenic vein thrombus."}]


def _stub_jev(monkeypatch, contra: dict, reported: dict, dictated: Optional[dict] = None,
              report_contra: Optional[dict] = None):
    """contra: clause/option text -> score; reported: dictated item -> score; dictated: negative clause ->
    'the dictation itself states it'; report_contra: option text -> 'it would contradict the report'.
    Default 0.05 / 0.95 / 0.05 / 0.05."""
    dictated = dictated or {}
    report_contra = report_contra or {}
    calls = []
    async def fake(state, questions):
        calls.append((state, questions))
        out = {}
        for k, q in questions.items():
            t = q["instructions"]
            if t.startswith(qq.Q_CONTRA):
                out[k] = {"noul": contra.get(t[len(qq.Q_CONTRA):], 0.05)}
            elif t.startswith(qq.Q_OPTION_REPORT):
                out[k] = {"noul": report_contra.get(t[len(qq.Q_OPTION_REPORT):].strip('"'), 0.05)}
            elif t.startswith(qq.Q_DICTATED):
                out[k] = {"noul": dictated.get(t.split('"')[1], 0.05)}
            elif q["type"] == "choice" and k.startswith("i"):
                line = t.split('"')[1]
                out[k] = _cls("absent" if reported.get(line, 0.95) < 0.4 else "stated")
            else:
                out[k] = {"noul": 0.95}
        return out
    monkeypatch.setattr(qq.rc, "_jev", fake)
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
    omit_qs = [q for s, qs in calls if s.startswith("REPORT") for k, q in qs.items() if not k.startswith("ro")]
    assert omit_qs == [qq.q_omission(t) for t in ("3 cm hypodense mass at the head of the pancreas", "CBD dilated to 12 mm",
                                                  "Intrahepatic duct dilatation", "No ascites")]
    assert [(f.kind, f.text) for f in res.flags] == [("contradiction", "No portal vein encasement"),
                                                     ("omission", "CBD dilated to 12 mm")]
    assert res.bad_option_ids == ["fn0"]
    assert res.error is None


@pytest.mark.asyncio
async def test_an_option_the_report_contradicts_is_dropped(monkeypatch):
    # live b4e8e644: "No perforation of the appendix." offered beside an impression of perforated appendicitis;
    # the dictation-state check missed it (gas -> perforation is an inference). Lab option_contra R2: positives
    # >= 0.92, negatives <= 0.46.
    calls = _stub_jev(monkeypatch, {}, {}, report_contra={"No splenic vein thrombus.": 0.9})
    res = await qq.check(REPORT, FINDINGS, "CT AP", OPTIONS)
    asked = {q["instructions"] for s, qs in calls if s.startswith("REPORT") for k, q in qs.items() if k.startswith("ro")}
    assert asked == {qq.Q_OPTION_REPORT + f'"{o["sentence"]}"' for o in OPTIONS}
    assert res.bad_option_ids == ["fn1"] and res.report_contra_option_ids == ["fn1"]


@pytest.mark.asyncio
async def test_an_option_below_the_report_threshold_is_kept(monkeypatch):
    _stub_jev(monkeypatch, {}, {}, report_contra={"No splenic vein thrombus.": 0.59})
    res = await qq.check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert res.bad_option_ids == [] and res.report_contra_option_ids == []


@pytest.mark.asyncio
async def test_check_failure_returns_no_flags_and_the_reason(monkeypatch):
    async def boom(state, questions):
        raise RuntimeError("jev down")
    monkeypatch.setattr(qq.rc, "_jev", boom)
    res = await qq.check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert res.flags == [] and res.bad_option_ids == [] and "jev down" in res.error


def test_dictated_negative_question_quotes_the_clause_and_the_sentence_before_it():
    q = qq.q_dictated("No canal stenosis at this level.", "Disc bulge at L3/L4.")
    assert q["type"] == "noul"
    assert q["instructions"] == (qq.Q_DICTATED + '"No canal stenosis at this level." (in the report it follows: '
                                 '"Disc bulge at L3/L4.")')
    assert "same level, side and structure" in q["instructions"]
    assert q["criteria"]["true"].startswith("The dictation itself says this finding is absent")
    assert "only for a different level, side" in q["criteria"]["false"]
    assert qq.q_dictated("No ascites.", "")["instructions"] == qq.Q_DICTATED + '"No ascites."'


@pytest.mark.asyncio
async def test_a_dictated_negative_is_kept_whatever_the_contradiction_score(monkeypatch):
    # L-49 addendum (f98a5930): stenosis dictated at another level made Jev read the dictated
    # "No spinal canal stenosis" as contradicted, and the restated gate passed it.
    calls = _stub_jev(monkeypatch, {"No portal vein encasement": 0.9, "No hepatic deposit": 0.9},
                      {}, dictated={"No portal vein encasement": 0.8})
    res = await qq.check(REPORT, FINDINGS, "CT AP", [])
    asked = {q["instructions"].split('"')[1]: q for s, qs in calls if s.startswith("SCAN") for k, q in qs.items()
             if k.startswith("d")}
    assert set(asked) == {"No superior mesenteric vein encasement", "No portal vein encasement", "No hepatic deposit",
                          "No pericolic or paracolic fluid collection."}        # negatives only
    assert asked["No portal vein encasement"] == qq.q_dictated(
        "No portal vein encasement", "A 3 cm hypodense mass in the pancreatic head compresses the distal common bile duct.")
    assert [(f.kind, f.text) for f in res.flags] == [("contradiction", "No hepatic deposit")]
    assert [k.model_dump() for k in res.kept_dictated] == [
        {"text": "No portal vein encasement", "contradiction": 0.9, "dictated": 0.8}]


@pytest.mark.asyncio
async def test_an_unreadable_dictated_answer_keeps_the_negative(monkeypatch):
    async def fake(state, qs):
        if state.startswith("REPORT:"):
            return {k: _cls("stated") for k in qs}
        return {k: {"noul": 0.9} for k in qs if not k.startswith("d")}      # no d<i> answers
    monkeypatch.setattr(qq.rc, "_jev", fake)
    res = await qq.check(REPORT, FINDINGS, "CT AP", [])
    assert [f for f in res.flags if f.kind == "contradiction" and qq.is_negative(f.text)] == []
    assert {"text": "No portal vein encasement", "contradiction": 0.9, "dictated": None} in [
        k.model_dump() for k in res.kept_dictated]


@pytest.mark.asyncio
async def test_kept_dictated_negatives_stay_in_the_report_and_the_telemetry(monkeypatch):
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(kept_dictated=[qq.KeptNegative(text="No portal vein encasement", contradiction=0.9,
                                                             dictated=0.8)])
    async def must_not_run(*a, **k):
        raise AssertionError("no repair")
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "insert_findings", must_not_run)
    report, _, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", [])
    assert report == REPORT and tel["clauses_removed"] == 0
    assert tel["kept_dictated_negative"] == [{"text": "No portal vein encasement", "contradiction": 0.9, "dictated": 0.8}]


@pytest.mark.asyncio
async def test_insert_failure_returns_the_report_unchanged(monkeypatch):
    async def boom(**kw):
        raise asyncio.TimeoutError
    monkeypatch.setattr(qq, "_run_agent_with_model", boom)
    res = await qq.insert_findings(REPORT, FINDINGS, ["anything"])
    assert res.report == REPORT and res.applied == 0 and res.error


@pytest.mark.asyncio
async def test_run_quality_check_repairs_on_report_flags_and_drops_bad_options(monkeypatch):
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="contradiction", text="No portal vein encasement", score=0.8),
                                     qq.Flag(kind="omission", text="CBD dilated to 12 mm", score=0.2)],
                              bad_option_ids=["fn0"], n_clauses=9, n_items=3,
                              sentence_type={"No portal vein encasement": "normal"})
    seen = {}
    async def fake_insert(report, findings, items):
        seen["items"] = items
        return qq.RepairResult(report=report, applied=1, skipped=1)
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "insert_findings", fake_insert)
    report, options, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", OPTIONS)
    assert seen["items"] == ["CBD dilated to 12 mm"]
    assert "portal vein encasement" not in report                     # removed in code
    assert [o["id"] for o in options] == ["fn1"]
    assert tel["edits_applied"] == 1 and tel["edits_skipped"] == 1 and tel["options_dropped"] == ["fn0"]
    assert [f["kind"] for f in tel["flags"]] == ["contradiction", "omission"] and tel["error"] is None


@pytest.mark.asyncio
async def test_partial_and_differs_lines_are_recorded_for_review_never_inserted(monkeypatch):
    rep = "FINDINGS:\nA 3 mm calculus is seen in the left distal ureter.\n\nIMPRESSION:\nUreteric calculus."
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="partial", text="3 mm calculus left distal ureter, HU 254", score=0.8),
                                     qq.Flag(kind="differs", text="5 mm calculus left distal ureter", score=0.7)])
    async def must_not_run(*a, **k):
        raise AssertionError("nothing to insert or correct")
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "insert_findings", must_not_run)
    out, _, tel = await qq.run_quality_check(rep, "x", "CT KUB", [])
    assert out == rep and tel["repair_ms"] is None
    assert tel["review"] == [{"kind": "partial", "line": "3 mm calculus left distal ureter, HU 254", "missing_detail": "HU 254"},
                             {"kind": "differs", "line": "5 mm calculus left distal ureter"}]


@pytest.mark.asyncio
async def test_only_absent_lines_reach_the_inserter(monkeypatch):
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="partial", text="bb two", score=0.8),
                                     qq.Flag(kind="omission", text="aa one", score=0.9)])
    seen = {}
    async def fake_insert(report, findings, items):
        seen["items"] = items
        return qq.RepairResult(report=report)
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "insert_findings", fake_insert)
    await qq.run_quality_check(REPORT, FINDINGS, "CT", [])
    assert seen["items"] == ["aa one"]


@pytest.mark.asyncio
async def test_no_report_flags_means_no_repair_call(monkeypatch):
    async def clean(report, findings, scan_type, options):
        return qq.CheckResult(bad_option_ids=["fn0"])
    async def must_not_run(*a):
        raise AssertionError("repair called without a report flag")
    monkeypatch.setattr(qq, "check", clean)
    monkeypatch.setattr(qq, "insert_findings", must_not_run)
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
    async def fake_quality(report, findings, scan_type, options, brief_decisions="unset"):
        seen["report"] = report
        seen["brief_decisions"] = brief_decisions
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
    assert seen["brief_decisions"] is None          # no brief compiled: the check runs without anchors


def test_negative_clauses_are_removed_in_code_never_inverted():
    rep = ("FINDINGS:\nNo subfalcine or transtentorial herniation, intraventricular haemorrhage, or acute ischaemic "
           "change identified. No focal mass-like colonic wall thickening is identified. The liver is normal.\n\n"
           "IMPRESSION:\nHaemorrhage.")
    out = qq.remove_negative_clause(rep, "No subfalcine or transtentorial herniation")
    assert "No intraventricular haemorrhage or acute ischaemic change identified." in out
    out = qq.remove_negative_clause(out, "No focal mass-like colonic wall thickening is identified.")
    assert "mass-like" not in out and "The liver is normal." in out
    assert qq.remove_negative_clause(out, "text not present") == out


@pytest.mark.asyncio
async def test_a_flagged_positive_statement_is_never_edited_only_reviewed(monkeypatch):
    # Template retest 42281: the generator corrected the dictated slip "LMP 872" to "LMS=872"; Jev read the
    # correction as a contradiction and the Qwen rewrite copied the slip back. A positive flag is flag-only.
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="contradiction", text="Pancreatic head mass causing biliary obstruction.", score=0.8)])
    async def must_not_run(*a, **k):
        raise AssertionError("a positive flag never edits the report")
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "insert_findings", must_not_run)
    monkeypatch.setattr(qq, "_run_agent_with_model", must_not_run)
    report, _, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", [])
    assert report == REPORT and tel["repair_ms"] is None and tel["edits_applied"] == 0
    assert tel["review"] == [{"kind": "contradiction", "text": "Pancreatic head mass causing biliary obstruction.", "score": 0.8}]
    assert not hasattr(qq, "repair_report")


@pytest.mark.asyncio
async def test_run_quality_check_routes_each_flag(monkeypatch):
    # Negative: removed in code. Positive: review only. Absent line: inserted. Partial: review only.
    async def fake_check(report, findings, scan_type, options):
        return qq.CheckResult(flags=[qq.Flag(kind="contradiction", text="No portal vein encasement", score=0.8),
                                     qq.Flag(kind="contradiction", text="Pancreatic head mass causing biliary obstruction.", score=0.7),
                                     qq.Flag(kind="omission", text="CBD dilated to 12 mm", score=0.2),
                                     qq.Flag(kind="partial", text="Intrahepatic duct dilatation 6 mm", score=0.8)],
                              sentence_type={"No portal vein encasement": "normal"})
    calls = []
    async def fake_insert(report, findings, items):
        calls.append(items)
        return qq.RepairResult(report=report.replace("distal common bile duct.", "distal common bile duct, dilated to 12 mm."), applied=1)
    monkeypatch.setattr(qq, "check", fake_check)
    monkeypatch.setattr(qq, "insert_findings", fake_insert)
    report, _, tel = await qq.run_quality_check(REPORT, FINDINGS, "CT AP", [])
    assert calls == [["CBD dilated to 12 mm"]]
    assert "portal vein encasement" not in report and "No superior mesenteric vein encasement or hepatic deposit." in report
    assert "dilated to 12 mm." in report and "Pancreatic head mass causing biliary obstruction." in report
    assert tel["clauses_removed"] == 1 and tel["edits_applied"] == 1
    assert [r["kind"] for r in tel["review"]] == ["partial", "contradiction"]
    assert tel["review"][1] == {"kind": "contradiction", "text": "Pancreatic head mass causing biliary obstruction.", "score": 0.7}


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
            elif t.startswith(qq.Q_DICTATED):
                out[k] = {"noul": 0.05}
            else:
                out[k] = {"noul": 0.95}
        return out
    monkeypatch.setattr(qq.rc, "_jev", fake)
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
    monkeypatch.setattr(qq.rc, "_jev", fake_jev)


def _jev_down(monkeypatch):
    import httpx
    async def boom(state, qs):
        raise httpx.ReadTimeout("jev timeout")
    monkeypatch.setattr(qq.rc, "_jev", boom)


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
            if k.startswith("t"):      # statement type of the negative's sentence: a removal needs "normal"
                out[k] = {"choice": "normal", "probabilities": {"normal": 0.9}}
                continue
            out[k] = {"noul": 0.8 if t == qq.Q_CONTRA + "No pneumothorax." else
                              0.6 if t == qq.q_restated("pneumothorax")["instructions"] else
                              0.9 if t.startswith(qq.Q_CONVEYS) else 0.05}
        return out
    monkeypatch.setattr(qq.rc, "_jev", fake)
    report = "FINDINGS:\nNo pneumothorax. The lungs are clear.\n\nIMPRESSION:\nNo acute abnormality."
    out, _, tel = await qq.run_quality_check(report, "?pneumothorax", "CXR", [])
    assert any(q == qq.q_restated("pneumothorax") for q in asked.values())
    assert qq.RESTATED_FLAG == 0.5
    assert "No pneumothorax" not in out and "The lungs are clear." in out and tel["clauses_removed"] == 1


# ── omission selector (Jev wording v2, group F): only abnormal / limitation / mixed lines ──

def _selector_jev(monkeypatch, selected_items, omitted, fail_dictation=False, seen=None):
    """Selector answers from the dictation-state call; every item scored omitted (0.1) when in `omitted`."""
    async def fake(state, qs):
        if seen is not None:
            seen.append((state, qs))
        if state.startswith("SCAN TYPE"):
            if fail_dictation:
                raise RuntimeError("jev down")
            out = {}
            for k, q in qs.items():
                t = q["instructions"]
                if k.startswith("sel"):
                    hit = any(f'"{x}"' in t for x in selected_items)
                    out[k] = {"choice": "abnormal_finding" if hit else "normal_or_negative",
                              "probabilities": {"abnormal_finding": 0.9 if hit else 0.02, "limitation": 0.0,
                                                "normal_or_negative": 0.1 if hit else 0.98, "protocol_note": 0.0,
                                                "comparison": 0.0, "mixed_abnormal_and_normal": 0.0}}
                elif k.startswith("lt"):
                    out[k] = {"noul": 0.9 if any(f'"{x}"' in t for x in selected_items) else 0.05}
                else:
                    out[k] = {"noul": 0.05}
            return out
        return {k: _cls("absent" if any(f'"{x}"' in q["instructions"] for x in omitted) else "stated") for k, q in qs.items()}
    monkeypatch.setattr(qq.rc, "_jev", fake)


@pytest.mark.asyncio
async def test_unselected_normal_and_negative_omission_flags_are_ignored(monkeypatch):
    _selector_jev(monkeypatch, selected_items=["2cm cyst L kidney"],
                  omitted=["appendix fine", "no calculi or hydro", "2cm cyst L kidney"])
    r = await qq.check("FINDINGS:\nx.", "appendix fine. no calculi or hydro. 2cm cyst L kidney", "CT", [])
    assert [f.text for f in r.flags if f.kind == "omission"] == ["2cm cyst L kidney"]
    assert r.selector == "jev" and r.n_items == 3


@pytest.mark.asyncio
async def test_selector_questions_ride_the_dictation_state_call(monkeypatch):
    seen = []
    _selector_jev(monkeypatch, ["2cm cyst L kidney"], [], seen=seen)
    await qq.check("FINDINGS:\nx.", "appendix fine. 2cm cyst L kidney", "CT", [])
    by_state = {s.split("\n")[0]: qs for s, qs in seen}
    dict_qs = by_state["SCAN TYPE: CT"]
    assert dict_qs["sel1"] == qq.q_select_choice("2cm cyst L kidney") and dict_qs["lt0"] == qq.q_select_noul("appendix fine")
    assert sorted(by_state["REPORT:"]) == ["i0", "i1"]                    # classifier asked for every item, in parallel
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_selector_failure_falls_back_to_the_regex(monkeypatch):
    _selector_jev(monkeypatch, ["2cm cyst L kidney"], omitted=["liver normal", "2cm cyst L kidney", "no ascites"],
                  fail_dictation=True)
    r = await qq.check("FINDINGS:\nx.", "liver normal. no ascites. 2cm cyst L kidney", "CT", [])
    assert [f.text for f in r.flags if f.kind == "omission"] == ["2cm cyst L kidney"]
    assert r.selector == "regex" and "jev down" in r.error


# ── inserter rewrite (classify-first, L-49): only the abnormal part, report terms, slips corrected ──

def test_insert_prompt_rules():
    p = qq.INSERT_SYS
    assert "Write only what the line reports as abnormal or present" in p
    assert "Never write a sentence that only says structures are normal" in p
    assert "Use the report's own terms" in p
    assert "never guess a finding" in p
    assert "Never state anything that differs from what the report already says" in p
    assert '"sentence": ""' in p


@pytest.mark.asyncio
async def test_inserter_user_prompt_lists_the_lines_left_out(monkeypatch):
    seen = {}
    async def fake(**kw):
        seen.update(kw)
        from types import SimpleNamespace
        return SimpleNamespace(output=qq.Insertions(items=[]))
    monkeypatch.setattr(qq, "_run_agent_with_model", fake)
    await qq.insert_findings("FINDINGS:\nx.", "d", ["aa one"])
    assert "LINES LEFT OUT OF THE REPORT:\n1. aa one" in seen["user_prompt"]
    assert seen["model_settings"]["reasoning_effort"] == "none"


def test_normal_only_sentences_are_recognised():
    assert qq._only_normal("The midfoot joints are unremarkable.")
    assert qq._only_normal("Within the limits of the study, no abnormality is seen in the upper aerodigestive tract.")
    assert qq._only_normal("The partially imaged femoral heads appear normal.")
    assert not qq._only_normal("A 2 cm cyst is present in the right kidney, which is otherwise normal.")
    assert not qq._only_normal("There is an abnormal signal in the cord.")
    assert not qq._only_normal("Mild degenerative changes are noted in the spine.")


@pytest.mark.asyncio
async def test_inserter_drops_a_normal_only_sentence(monkeypatch):
    _insertions(monkeypatch, "The midfoot joints are unremarkable.", "A 5 mm defect at D1.")
    _jev_scores(monkeypatch, 0.05)
    r = await qq.insert_findings("FINDINGS:\nThe appendix is unremarkable.", "x", ["midfoot fine, defect", "5 mm defect D1"])
    assert "midfoot" not in r.report and "5 mm defect" in r.report and r.applied == 1 and r.skipped == 1


def test_post_generation_check_reads_every_paragraph_of_a_numbered_impression():
    """No signature is appended yet when the check runs: no cut (live audit 1 review fix 1)."""
    report = ("FINDINGS:\nThe appendix is dilated.\n\nIMPRESSION:\n1. Acute appendicitis.\n\n"
              "2. No pelvic collection.\n\n3. Small volume free fluid.")
    _, imp = qq.report_sections(report)
    assert "3. Small volume free fluid." in imp
    clauses = qq.checked_clauses(report, None)
    assert any("No pelvic collection" in c for c in clauses) and any("Small volume free fluid" in c for c in clauses)
