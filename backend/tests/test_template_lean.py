"""Lean template path (arm E): today's generator on the stored sheet + post-generation check + Phase 1 as
options only."""
from __future__ import annotations

import asyncio
import time

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai import template_lean as tl

OLD_SHEET = """# Skill Sheet: Example study

## Scan Context
- Modality: CT

## Structural Pattern
- CONCLUSION: `header: "Conclusion:"`
- Coronary Findings: `header: "Coronary Findings:"`

## Per-Section Construction Rules

### [PRIMARY FINDINGS]
- **Normal pattern**: "The primary organ is unremarkable."

## Impression Construction Rules
### Quoted examples
- "Example impression."

## Terminology Rules
- Prefer "lesion".
"""

REPORT = """No previous imaging available for comparison.

A 2 cm lesion of the primary organ. No free fluid.

Coronary Findings: Right-sided dominance.
LMS: Minimal plaque.

Other findings:
Unremarkable.

Conclusion:
1. A 2 cm lesion of the primary organ."""

CASE = {
    "differentials": [
        {"name": "primary lesion", "tier": "triage", "discriminator": "focal mass", "visible": "yes"},
        {"name": "abscess", "tier": "triage", "discriminator": "rim-enhancing collection", "visible": "yes"},
    ],
    "recommendations": [
        {"tag": "REFERRAL", "text": "Urgent referral to the specialty service.", "when": "a focal lesion is reported"},
        {"tag": "IMAGING", "text": "MRI to characterise the abscess.", "when": "a collection is reported"},
    ],
    "placement_units": [
        {"kind": "NEGATIVE", "text": "No ductal dilatation", "key": "primary lesion", "paragraph": "PRIMARY FINDINGS"},
        {"kind": "NEGATIVE", "text": "No gas-containing collection", "key": "abscess", "paragraph": "PRIMARY FINDINGS"},
        {"kind": "IF_PRESENT", "text": "No regional lymphadenopathy", "key": "focal lesion", "paragraph": "PRIMARY FINDINGS"},
        {"kind": "IF_PRESENT", "text": "No vascular invasion", "key": "focal lesion", "paragraph": "PRIMARY FINDINGS"},
        {"kind": "IF_PRESENT", "text": "No perforation", "key": "bowel wall thickening", "paragraph": "PRIMARY FINDINGS"},
    ],
}


def test_report_sections_come_from_the_generated_report_headers():
    secs = tl.report_sections(REPORT, OLD_SHEET)
    got = [(s.name, s.header, s.role) for s in secs]
    assert got[0] == ("FINDINGS", None, "findings")                # text before the first header: implicit
    assert ("CORONARY FINDINGS", "Coronary Findings:", "findings") in got  # inline, declared by the sheet
    assert ("OTHER FINDINGS", "Other findings:", "findings") in got        # standalone header line
    assert ("CONCLUSION", "Conclusion:", "impression") in got
    assert not any(s.header and s.header.startswith("LMS") for s in secs)  # inline label the sheet never declares


def _fakes(monkeypatch, present=None, qwen=None, plan=None):
    calls = {}

    async def fake_jev(state, qs):
        calls.setdefault("jev", []).append(qs)
        sc = {"d0": 0.9, "d1": 0.1, "f0": 3, "f1": 1, "rec0": 0.9, "rec1": 0.1, **(present or {})}
        dflt = lambda k: 0.1 if k.startswith(("dv", "dr")) else None  # noqa: E731 - no device presupposed
        return {k: ({"score": sc[k]} if k.startswith("f") else {"noul": sc.get(k, dflt(k))}) for k in qs}

    async def fake_qwen(state, negs, normals, measurements, **kw):
        calls["qwen"] = list(negs)
        acts = qwen or {}
        return rc.QwenDecisions(negatives=[rc.NegativeDecision(index=i, action=acts.get(n, "keep"),
                                                               dictated_finding="x" if n in acts else "")
                                           for i, n in enumerate(negs)], affected_normals=[], applicable_measurements=[])

    async def fake_plan(scan, hist, items, recs, inclusion_logic=""):
        calls["plan_recs"] = recs
        return plan or rc.ImpressionPlan(recommendations=[rc.RecDecision(index=0, decision="include")],
                                         impression=[0], optional_impression=[])
    monkeypatch.setattr(rc, "_jev", fake_jev)
    monkeypatch.setattr(rc, "_qwen_complete", fake_qwen)
    monkeypatch.setattr(rc, "_plan", fake_plan)
    return calls


async def test_case_options_route_phase1_units_into_options_only(monkeypatch):
    calls = _fakes(monkeypatch, qwen={"No vascular invasion": "contradicted"})
    opts, dec = await tl.case_options(CASE, "A 2 cm lesion of the primary organ.", "CT", "?lesion",
                                      findings_section="FINDINGS", impression_section="CONCLUSION")
    texts = [(o["kind"], o["text"]) for o in opts]
    # If-present for the reported finding (core, clearly present -> offered first); contradicted one dropped
    assert ("finding_negative", "No regional lymphadenopathy") in texts
    assert ("finding_negative", "No vascular invasion") not in texts
    # If-present for a finding not dictated: dropped, never classified
    assert ("finding_negative", "No perforation") not in texts and "No perforation" not in calls["qwen"]
    # targeted exclusion: the branch reported (primary lesion present) omits its negative; the closed branch offers
    assert ("finding_negative", "No ductal dilatation") not in texts
    assert ("finding_negative", "No gas-containing collection") in texts
    # recommendation: trigger dictated -> offered in the impression section; trigger absent -> removed
    assert ("recommendation", "REFERRAL: Urgent referral to the specialty service.") in texts
    assert not any("MRI" in t for _, t in texts)
    assert all(o["section"] == ("CONCLUSION" if o["kind"] != "finding_negative" else "PRIMARY FINDINGS") for o in opts)
    assert sum(o["kind"] == "finding_negative" for o in opts) <= rc.MAX_FINDING_OPTIONS
    assert dec["finding_negatives"] and dec["case_exclusions"] and dec["recommendations"]


async def test_case_options_fail_closed_on_jev_error_and_without_a_case(monkeypatch):
    _fakes(monkeypatch)

    async def down(state, qs):
        raise RuntimeError("jev down")
    monkeypatch.setattr(rc, "_jev", down)
    opts, dec = await tl.case_options(CASE, "A lesion.", "CT", "", findings_section="FINDINGS",
                                      impression_section="CONCLUSION")
    assert not any(o["kind"] in ("finding_negative", "recommendation") for o in opts) and dec.get("error")
    opts, _ = await tl.case_options(None, "A lesion.", "CT", "", findings_section="FINDINGS",
                                    impression_section="CONCLUSION")
    assert not any(o["kind"] in ("finding_negative", "recommendation") for o in opts)


def _gen_fakes(monkeypatch, calls, options_delay=0.0):
    async def fake_gen(self, template_config, user_inputs, user_signature=None, model_override=None,
                       brief_text=None, history_supplied=False, stack=None):
        calls["gen"] = {"sheet": template_config["skill_sheet"], "brief_text": brief_text, "inputs": user_inputs,
                        "stack": stack}
        return {"report_content": REPORT, "model_used": "q", "description": "d", "scan_type": "CT"}

    async def fake_case_options(case, findings, scan_type, history, **kw):
        calls["case"] = case
        await asyncio.sleep(options_delay)
        return ([{"kind": "finding_negative", "section": "FINDINGS", "text": "No regional lymphadenopathy"},
                 {"kind": "finding_negative", "section": "FINDINGS", "text": "No free gas"},
                 {"kind": "recommendation", "section": "CONCLUSION", "text": "REFERRAL: Urgent referral."}], {"x": 1})

    async def fake_write(options, findings, scan_type, **kw):
        calls["style"] = kw.get("style")
        return [{"id": "fn0", "kind": "finding_negative", "section": "FINDINGS", "sentence": "No regional lymphadenopathy."},
                {"id": "fn1", "kind": "finding_negative", "section": "FINDINGS", "sentence": "No free gas."},
                {"id": "opt0", "kind": "recommendation", "section": "CONCLUSION", "sentence": "Urgent referral."}]

    async def fake_check(report, findings, scan, options, sections=None, protected=None, suppressed=None,
                         extra_report_qs=None, history=None):
        calls["check"] = {"sections": [(s.name, s.role) for s in sections], "options": options, "extra": extra_report_qs}
        return report + "\nCHECKED", options, {"enabled": True}

    async def fake_gate(state, qs):
        calls.setdefault("gate", []).append((state, qs))
        if state.startswith("SCAN TYPE"):   # contradiction of each option sentence against the dictation
            return {k: (0.9 if "free gas" in q["instructions"] else 0.1) for k, q in qs.items()}
        if state.startswith("REPORT:"):      # uniqueness against the report
            return {k: (0.95 if "lymphadenopathy" in q["instructions"] else 0.1) for k, q in qs.items()}
        return {}
    monkeypatch.setattr(tl.TemplateManager, "_generate_report_skill_sheet_guided", fake_gen)
    monkeypatch.setattr(tl, "case_options", fake_case_options)
    monkeypatch.setattr(tl, "write_options", fake_write)
    monkeypatch.setattr(tl, "run_quality_check", fake_check)
    monkeypatch.setattr(tl.rc, "gate_scores", fake_gate)


async def test_lean_generation_is_todays_generator_then_check_then_vetted_options(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.",
                                                 history="?lesion", case=CASE, signature="Dr A")
    assert calls["gen"]["sheet"] == OLD_SHEET and calls["gen"]["brief_text"] is None
    # the check reads the report alone
    assert ("CONCLUSION", "impression") in calls["check"]["sections"] and calls["check"]["options"] == []
    # nothing from Phase 1 is written into the report: generator text + check edits + signature only
    assert out["report_content"] == REPORT + "\nCHECKED\n\nDr A" and out["report_generated"] == REPORT
    assert out["options"] == [] and out["options_pending"] is True and out["brief_used"] is False
    assert set(out["lat"]) >= {"generator_s", "check_s", "generate_s"}
    # options finish in the job: vetted against the dictation (contradiction) and the report (uniqueness)
    res = await out["options_job"]
    assert calls["case"] is CASE and "Example impression." in calls["style"]
    assert any(st.startswith("CONCLUSION:\n1. A 2 cm lesion") for st, _ in calls["gate"])
    assert [o["id"] for o in res["options"]] == ["opt0"]
    assert {o["id"]: o["outcome"] for o in res["gate_dropped"]} == {"fn0": "already_in_report", "fn1": "contradicted"}
    assert set(res["lat"]) >= {"options_s", "vet_s", "options_ready_s"} and res["phase1_used"] is True
    assert "options_s" not in out["lat"]   # the report's latencies are never touched by the job


async def test_generate_returns_before_the_options_finish(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls, options_delay=2.0)
    t0 = time.monotonic()
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.",
                                                 history="?lesion", case=CASE, signature=None)
    assert time.monotonic() - t0 < 0.5
    assert out["report_content"] == REPORT + "\nCHECKED" and out["options"] == []
    assert not out["options_job"].done()   # still routing: the report did not wait
    res = await out["options_job"]
    assert [o["id"] for o in res["options"]] == ["opt0"]


async def test_case_may_be_resolved_in_the_options_job(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)

    async def resolve():
        return CASE
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.",
                                                 history="?lesion", case=resolve, signature=None)
    assert (await out["options_job"])["phase1_used"] is True and calls["case"] is CASE


# ── device / prior-procedure guard (Phase 1 options) ─────────────────────────

def test_device_questions_quote_the_option_and_point_the_same_way():
    qs = tl.device_questions(3, "No contrast within the aneurysm sac.")
    assert set(qs) == {"dv3", "dr3"}
    assert '"No contrast within the aneurysm sac."' in qs["dv3"]["instructions"]
    assert qs["dv3"]["instructions"].startswith("This negative only makes sense for a patient who has a device or "
                                                "has had a prior procedure or treatment")
    assert "radiotherapy field" in qs["dv3"]["criteria"]["true"]
    assert "can only occur after it" in qs["dv3"]["criteria"]["true"]
    assert "never had a device, procedure or treatment" in qs["dv3"]["criteria"]["false"]
    assert qs["dr3"]["instructions"].startswith("The dictated findings or the clinical history report the same device, "
                                                "prior procedure or treatment")
    assert "mention" in qs["dr3"]["criteria"]["true"] and "Neither" in qs["dr3"]["criteria"]["false"]
    assert "a different kind of device, procedure or treatment does not count" in qs["dr3"]["criteria"]["false"]
    assert "CLINICAL HISTORY: EVAR 2019" in tl.device_state("CT", "EVAR 2019", "AAA.")


def test_device_keep_drops_only_a_presupposed_device_that_is_not_reported():
    ans = {"dv0": {"noul": 0.9}, "dr0": {"noul": 0.1},     # presupposed, not reported -> drop
           "dv1": {"noul": 0.9}, "dr1": {"noul": 0.8},     # presupposed, reported -> keep
           "dv2": {"noul": 0.1}, "dr2": {"noul": 0.05},    # nothing presupposed -> keep
           "dv3": {"noul": 0.9}}                           # unreadable -> drop (conservative)
    assert [tl.device_keep(ans, k) for k in range(4)] == [False, True, True, False]


def test_device_keep_thresholds_are_asymmetric():
    assert (tl.DEVICE_PRESUPPOSES, tl.DEVICE_REPORTED) == (0.4, 0.6)
    k = lambda dv, dr: tl.device_keep({"dv0": {"noul": dv}, "dr0": {"noul": dr}}, 0)  # noqa: E731
    assert k(0.4, 0.59) is False      # presupposes at 0.4, reported below 0.6 -> drop
    assert k(0.39, 0.0) is True       # below 0.4 does not presuppose -> keep
    assert k(0.9, 0.6) is True        # reported at 0.6 -> keep
    assert k(0.9, 0.55) is False      # 0.55 is not enough to count as reported -> drop


async def test_case_options_drop_a_device_negative_the_case_does_not_report(monkeypatch):
    case = {**CASE, "placement_units": CASE["placement_units"] + [
        {"kind": "NEGATIVE", "text": "No contrast within the aneurysm sac", "key": "endoleak", "paragraph": "PRIMARY FINDINGS"}]}
    seen = {}

    async def device_jev(state, qs):
        if any(k.startswith("dv") for k in qs):
            seen["state"] = state
            return {k: {"noul": 0.9 if (k.startswith("dv") and "aneurysm sac" in qs[k]["instructions"]) else 0.1}
                    for k in qs}
        return await base(state, qs)
    _fakes(monkeypatch)
    base = rc._jev
    monkeypatch.setattr(rc, "_jev", device_jev)
    opts, dec = await tl.case_options(case, "A 2 cm lesion of the primary organ.", "CT", "?lesion",
                                      findings_section="FINDINGS", impression_section="CONCLUSION")
    assert "CLINICAL HISTORY: ?lesion" in seen["state"]
    assert not any("aneurysm sac" in o["text"] for o in opts)
    assert any(o["text"] == "No gas-containing collection" for o in opts)   # nothing presupposed: kept
    assert {"text": "No contrast within the aneurysm sac", "differential": "endoleak",
            "outcome": "device_not_reported"} in dec["case_exclusions"]


# ── option cap ───────────────────────────────────────────────────────────────

def test_cap_options_keeps_three_finding_negatives_and_five_in_all_by_usefulness():
    fn = lambda t, o: {"kind": "finding_negative", "text": t, "origin": o}  # noqa: E731
    opts = [fn("x1", "exclusion"), fn("i1", "if_present"), fn("x2", "exclusion"), fn("i2", "if_present"),
            {"kind": "impression", "text": "imp1"}, {"kind": "recommendation", "text": "rec1"},
            {"kind": "impression", "text": "imp2"}, {"kind": "recommendation", "text": "rec2"}]
    kept, capped = tl.cap_options(opts)
    assert [o["text"] for o in kept] == ["i1", "i2", "x1", "rec1", "rec2"]
    assert [o["text"] for o in capped] == ["x2", "imp1", "imp2"]
    assert tl.cap_options(opts[:2]) == (opts[1:2] + opts[:1], [])


def test_a_standalone_impression_word_without_colon_is_a_header():
    secs = tl.report_sections("No free fluid.\n\nImpression\n\nA 2 cm lesion.", "")
    assert [(s.name, s.header, s.role) for s in secs] == [("FINDINGS", None, "findings"),
                                                          ("IMPRESSION", "Impression", "impression")]
    # an ordinary short sentence line is not a header
    assert len(tl.report_sections("No free fluid.\nNormal spleen\n\nConclusion:\nX.", "")) == 2


def test_option_section_prefers_the_phase1_paragraph_then_a_findings_named_section():
    secs = tl.report_sections(REPORT, OLD_SHEET)
    assert tl.option_section({"kind": "finding_negative", "section": "Other findings"}, secs) == "OTHER FINDINGS"
    # unknown paragraph: a findings section whose name says FINDINGS, before an earlier generic one
    secs2 = tl.report_sections("Calcium scoring:\nX.\n\nCoronary Findings:\nY.\n\nConclusion:\nZ.", "")
    assert tl.option_section({"kind": "finding_negative", "section": "PRIMARY"}, secs2) == "CORONARY FINDINGS"
    assert tl.option_section({"kind": "recommendation", "section": "IMPRESSION"}, secs2) == "CONCLUSION"


def test_option_section_matches_a_paragraph_by_shared_words_before_the_implicit_preface():
    secs = tl.report_sections("No previous study.\n\nHead and C-spine:\nX.\n\nCAP:\nY.\n\nConclusion:\nZ.", "")
    assert tl.option_section({"kind": "finding_negative", "section": "CHEST (within CAP or separate)"}, secs) == "CAP"
    assert tl.option_section({"kind": "finding_negative", "section": "Unrelated"}, secs) == "HEAD AND C-SPINE"


async def test_undictated_numbers_are_review_flags_and_never_edit_the_report(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    report = ("Findings:\nA 2 cm lesion of the primary organ, within the first 4.5 hours. Fazekas grade 2.\n\n"
              "Conclusion:\n1. A 2 cm lesion of the primary organ.")

    async def gen(self, template_config, user_inputs, user_signature=None, model_override=None,
                  brief_text=None, history_supplied=False, stack=None):
        return {"report_content": report, "model_used": "q", "description": "d", "scan_type": "CT"}
    monkeypatch.setattr(tl.TemplateManager, "_generate_report_skill_sheet_guided", gen)
    out = await tl.generate_template_report_lean(
        sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.", history="?lesion", case=None,
        signature="Dr A", stack={"conclusion": "Lesion. Fazekas grade 2 change.", "declined": []})
    assert out["options_job"] is None   # a scratchpad session runs no options job
    review = out["quality_check"]["review"]
    assert [r["text"] for r in review if r["kind"] == "undictated_number"] == ["4.5 hours"]
    assert out["report_content"] == report + "\nCHECKED\n\nDr A"   # flagged, never edited


async def test_with_the_check_off_the_flags_do_not_pretend_the_check_ran(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)

    async def gen(self, template_config, user_inputs, user_signature=None, model_override=None,
                  brief_text=None, history_supplied=False, stack=None):
        return {"report_content": "Findings:\nGrade 3 injury.", "model_used": "q", "description": "d", "scan_type": "CT"}

    async def off(report, findings, scan, options, **kw):
        return report, options, {"enabled": False}
    monkeypatch.setattr(tl.TemplateManager, "_generate_report_skill_sheet_guided", gen)
    monkeypatch.setattr(tl, "run_quality_check", off)
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="Injury.", history="",
                                                 case=None, signature=None)
    out["options_job"].cancel()
    assert out["quality_check"] == {"enabled": False,
                                    "review": [{"kind": "undictated_number", "text": "Grade 3",
                                                "sentence": "Grade 3 injury."}]}
    monkeypatch.setattr(tl, "run_quality_check", lambda *a, **k: _none(a[0], a[3]))
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="Injury.", history="",
                                                 case=None, signature=None)
    out["options_job"].cancel()
    assert out["quality_check"]["enabled"] is False and len(out["quality_check"]["review"]) == 1


async def _none(report, options):
    return report, options, None


async def test_stack_session_runs_no_options_job(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    routed = {"n": 0}

    async def counting_case_options(*a, **k):
        routed["n"] += 1
        return [], {}
    monkeypatch.setattr(tl, "case_options", counting_case_options)
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.",
                                                 history="?lesion", case=CASE, signature="Dr A",
                                                 stack={"conclusion": "C.", "declined": []})
    await asyncio.sleep(0)
    assert routed["n"] == 0
    assert out["report_content"].startswith(REPORT)
    assert out["options_job"] is None and out["options_pending"] is False


async def test_stack_session_never_resolves_the_case(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    resolved = {"n": 0}

    async def case():
        resolved["n"] += 1
        return CASE
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.",
                                                 history="?lesion", case=case, signature="Dr A",
                                                 stack={"conclusion": "C.", "declined": []})
    await asyncio.sleep(0)
    assert resolved["n"] == 0 and out["options_job"] is None


async def test_fallback_options_use_the_parsed_section_names_and_terms(monkeypatch):
    from tests.template_sheet_fixtures import GOOD
    sheet = (GOOD.replace("SECTION FINDINGS", "SECTION REPORT").replace("SECTION IMPRESSION", "SECTION OPINION")
             .replace("(FINDINGS)", "(REPORT)") + 'TERM PREFER "lesion"\nTERM AVOID "mass"\n')
    calls = {}
    _gen_fakes(monkeypatch, calls)
    seen = {}

    async def spy(case, findings, scan_type, history, **kw):
        seen.update(kw)
        return [], {}
    monkeypatch.setattr(tl, "case_options", spy)
    out = await tl.generate_template_report_lean(sheet=sheet, scan_type="CT", findings="x", history="h",
                                                 case=CASE, signature=None)
    await out["options_job"]
    assert seen["findings_section"] == "REPORT" and seen["impression_section"] == "OPINION"
    assert 'TERM PREFER "lesion"' in seen["inclusion_logic"] and 'TERM AVOID "mass"' in seen["inclusion_logic"]


async def test_legacy_sheet_keeps_literal_section_names(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    seen = {}

    async def spy(case, findings, scan_type, history, **kw):
        seen.update(kw)
        return [], {}
    monkeypatch.setattr(tl, "case_options", spy)
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="x", history="h",
                                                 case=CASE, signature=None)
    await out["options_job"]
    assert seen["findings_section"] == "FINDINGS" and seen["impression_section"] == "IMPRESSION"


from rapid_reports_ai import template_context_rules as cr
from rapid_reports_ai import template_pipeline as tp

RULED = '''## Report Structure
SECTION COMPARISON | header: "Comparison:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
FIXED "No previous imaging available for comparison." | section: COMPARISON
RULE WHEN [context: the dictation names a previous imaging study for comparison] REPLACE "No previous imaging available for comparison." WITH "Comparison made with previous {study} dated {date}." | section: COMPARISON

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
'''


def _met(score):
    async def ask(state, conditions):
        return [score for _ in conditions]
    return ask


async def test_both_paths_give_the_generator_the_resolved_sheet_and_record_it(monkeypatch):
    for stack in (None, {"conclusion": "Normal.", "declined": []}):
        calls = {}
        _gen_fakes(monkeypatch, calls)
        monkeypatch.setattr(cr, "ask_conditions", _met(0.9))
        out = await tl.generate_template_report_lean(sheet=RULED, scan_type="CT", findings="Compared with CT 02/12/2025.",
                                                     history="", case=CASE, signature=None, stack=stack)
        sent = calls["gen"]["sheet"]
        assert "RULE WHEN" not in sent and "No previous imaging available" not in sent
        assert 'FIXED "Comparison made with previous {study} dated {date}."' in sent
        assert sent.rstrip().endswith('- "Comparison made with previous {study} dated {date}."')
        assert out["context_rules"]["rules"][0]["outcome"] == "applied" and "rules_s" in out["lat"]
        if out.get("options_job") is not None:
            await out["options_job"]


async def test_a_slot_left_in_the_generated_report_is_removed_and_counted(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)

    async def gen(self, template_config, user_inputs, stack=None, **kw):
        return {"report_content": "Comparison: Comparison made with previous CT dated {date}.\n\nFindings: Normal.",
                "model_used": "q", "description": "d", "scan_type": "CT"}
    monkeypatch.setattr(tl.TemplateManager, "_generate_report_skill_sheet_guided", gen)
    monkeypatch.setattr(cr, "ask_conditions", _met(0.9))
    out = await tl.generate_template_report_lean(sheet=RULED, scan_type="CT", findings="Previous CT.", history="",
                                                 case=None, signature=None, stack={"conclusion": "", "declined": []})
    assert "{date}" not in out["report_content"] and "{date}" not in out["report_generated"]
    assert out["context_rules"]["slot_leaks"] == 1


async def test_the_stack_brief_of_the_resolved_sheet_has_the_decision_not_the_rule():
    from rapid_reports_ai.template_stack import stack_brief
    res = await cr.resolve_context_rules(RULED, "", "Compared with CT 02/12/2025.", ask=_met(0.9), stack=True)
    brief = stack_brief(res.sheet + "\n\n" + cr.decided_block(res.decided), "", ())
    assert "RULE WHEN [context: the dictation names" not in brief
    assert "## Decided for This Case" in brief


def test_candidate_record_carries_context_rules():
    rec = tp.candidate_record({"report_content": "x", "context_rules": {"asked": 1}}, 10)
    assert rec["context_rules"] == {"asked": 1}


async def test_a_raising_sheet_headers_never_breaks_generate(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    monkeypatch.setattr(cr, "ask_conditions", _met(0.9))

    def boom(sheet):
        raise RuntimeError("x")
    monkeypatch.setattr(tl, "sheet_headers", boom)
    out = await tl.generate_template_report_lean(sheet=RULED, scan_type="CT", findings="Previous CT.", history="",
                                                 case=CASE, signature=None, stack=None)
    assert out["report_content"]
    if out.get("options_job") is not None:
        await out["options_job"]


async def test_sections_and_number_check_read_the_stored_sheet_not_the_resolved_one(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    monkeypatch.setattr(cr, "ask_conditions", _met(0.9))
    seen = {}
    real_rs, real_un = tl.report_sections, tl.undictated_numbers

    def rs(report, sheet=""):
        seen["sections"] = sheet
        return real_rs(report, sheet)

    def un(final, srcs, sheet):
        seen["numbers"] = sheet
        return real_un(final, srcs, sheet)
    monkeypatch.setattr(tl, "report_sections", rs)
    monkeypatch.setattr(tl, "undictated_numbers", un)
    out = await tl.generate_template_report_lean(sheet=RULED, scan_type="CT", findings="Compared with CT 02/12/2025.",
                                                 history="", case=CASE, signature=None, stack=None)
    assert "RULE WHEN" not in calls["gen"]["sheet"]
    assert seen.get("sections") == RULED and seen.get("numbers") == RULED
    if out.get("options_job") is not None:
        await out["options_job"]


VALUES = '''## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
'''


def _values_gen(monkeypatch, calls, report):
    async def gen(self, template_config, user_inputs, user_signature=None, model_override=None, brief_text=None,
                  history_supplied=False, stack=None):
        calls["gen"] = {"sheet": template_config["skill_sheet"], "stack": stack}
        return {"report_content": report, "model_used": "q", "description": "d", "scan_type": "CMR"}
    monkeypatch.setattr(tl.TemplateManager, "_generate_report_skill_sheet_guided", gen)


async def test_a_stack_session_with_values_has_code_write_the_literal_na_line(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nValues not provided: LVEF, RVEF.\nNormal LV.\n\nConclusion:\nNormal.")
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%.", history="",
                                                 case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": ["RVEF"]})
    assert "LIST_MISSING" not in calls["gen"]["sheet"]
    assert calls["gen"]["stack"]["values_decided"] is True
    assert "Findings:\nValues not provided: RVEF.\nNormal LV." in out["report_content"]
    assert "LVEF, RVEF" not in out["report_content"]
    assert out["required_values"]["stripped"] == 1 and out["required_values"]["lists"][0]["na"] == ["RVEF"]


async def test_a_filled_value_the_report_lacks_is_listed_and_flagged(monkeypatch):
    from rapid_reports_ai import template_required_values as trv
    calls, seen = {}, {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.\n\nConclusion:\nNormal.")

    async def ask(report, items):
        seen.update(report=report, items=items)
        return [0.1, 0.9]
    monkeypatch.setattr(trv, "ask_report_values", ask)
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%. RVEF 50%.",
                                                 history="", case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": [],
                                                        "values_filled": ["LVEF", "RVEF"]})
    assert seen["items"] == ["LVEF", "RVEF"] and seen["report"].startswith("Findings:\nNormal LV.")
    assert "Findings:\nValues not provided: LVEF.\nNormal LV." in out["report_content"]
    assert {"kind": "value_missing", "text": "LVEF", "message": "Required value LVEF not found in the report"} \
        in out["quality_check"]["review"]
    assert out["required_values"]["backstop"] == {"asked": 2, "missing": ["LVEF"], "error": None}


async def test_a_backstop_failure_leaves_the_report_and_flags_only_that_it_could_not_check(monkeypatch):
    from rapid_reports_ai import template_required_values as trv
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.\n\nConclusion:\nNormal.")

    async def boom(report, items):
        raise RuntimeError("jev down")
    monkeypatch.setattr(trv, "ask_report_values", boom)
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%.", history="",
                                                 case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": [],
                                                        "values_filled": ["LVEF"]})
    assert "Values not provided" not in out["report_content"]
    assert not any(f.get("kind") == "value_missing" for f in (out["quality_check"] or {}).get("review") or [])
    assert out["required_values"]["backstop"]["error"].startswith("RuntimeError")
    assert [f["kind"] for f in out["quality_check"]["review"] if f.get("kind", "").startswith("value_")] \
        == ["value_check_unavailable"]


async def test_nothing_na_gives_no_list_and_no_line(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.\n\nConclusion:\nNormal.")
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%. RVEF 50%.",
                                                 history="", case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": []})
    assert "LIST_MISSING" not in calls["gen"]["sheet"] and calls["gen"]["stack"]["values_decided"] is True
    assert "Values not provided" not in out["report_content"]


async def test_values_not_applied_leave_the_sheet_and_the_generator_as_today(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.")
    legacy = "## FINDINGS\nLVEF: {value}\n"
    out = await tl.generate_template_report_lean(sheet=legacy, scan_type="CMR", findings="LV normal.", history="",
                                                 case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": ["RVEF"]})
    assert calls["gen"]["sheet"] == legacy and calls["gen"]["stack"]["values_decided"] is False
    assert out["required_values"]["skipped"] == "parse" and "Values not provided" not in out["report_content"]


async def test_a_stack_session_without_values_leaves_the_list_as_today(monkeypatch):
    for stack in ({"conclusion": "", "declined": []}, None):
        calls = {}
        _gen_fakes(monkeypatch, calls)
        out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LVEF 45%.", history="",
                                                     case=CASE, signature=None, stack=stack)
        assert 'LIST_MISSING ["LVEF" | "RVEF"] AT TOP' in calls["gen"]["sheet"]
        assert "values_decided" not in (calls["gen"]["stack"] or {}) and "required_values" not in out
        if out.get("options_job") is not None:
            await out["options_job"]


def test_candidate_record_carries_required_values():
    rec = tp.candidate_record({"report_content": "x", "required_values": {"lists": []}}, 10)
    assert rec["required_values"] == {"lists": []}


async def test_a_write_failure_is_recorded(monkeypatch):
    from rapid_reports_ai import template_required_values as trv
    calls = {}
    _gen_fakes(monkeypatch, calls)
    _values_gen(monkeypatch, calls, "Findings:\nNormal LV.\n\nConclusion:\nNormal.")

    def boom(items):
        raise RuntimeError("line down")
    monkeypatch.setattr(trv, "missing_line", boom)
    out = await tl.generate_template_report_lean(sheet=VALUES, scan_type="CMR", findings="LV normal.", history="",
                                                 case=None, signature=None,
                                                 stack={"conclusion": "", "declined": [], "values_na": ["RVEF"]})
    assert out["required_values"]["write_error"].startswith("RuntimeError")
    assert "Values not provided" not in out["report_content"]
