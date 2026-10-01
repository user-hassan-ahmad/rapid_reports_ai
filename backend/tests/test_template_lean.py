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
                       brief_text=None, history_supplied=False):
        calls["gen"] = {"sheet": template_config["skill_sheet"], "brief_text": brief_text, "inputs": user_inputs}
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
    assert calls["case"] is CASE and "Example impression." in calls["style"]
    # the check reads the report alone; options are vetted beside it (contradiction + uniqueness)
    assert ("CONCLUSION", "impression") in calls["check"]["sections"] and calls["check"]["options"] == []
    assert any(st.startswith("CONCLUSION:\n1. A 2 cm lesion") for st, _ in calls["gate"])
    # nothing from Phase 1 is written into the report: generator text + check edits + signature only
    assert out["report_content"] == REPORT + "\nCHECKED\n\nDr A" and out["report_generated"] == REPORT
    assert [o["id"] for o in out["options"]] == ["opt0"]
    assert {o["id"]: o["outcome"] for o in out["gate_dropped"]} == {"fn0": "already_in_report", "fn1": "contradicted"}
    assert set(out["lat"]) >= {"generator_s", "options_s", "check_s"} and out["options_late"] is False
    assert out["phase1_used"] is True and out["brief_used"] is False


async def test_late_options_are_dropped_and_never_delay_the_report(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls, options_delay=2.0)
    monkeypatch.setattr(tl, "OPTIONS_GRACE_S", 0.05)
    t0 = time.monotonic()
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.",
                                                 history="?lesion", case=CASE, signature=None)
    assert time.monotonic() - t0 < 0.5
    assert out["options"] == [] and out["options_late"] is True
    assert out["report_content"] == REPORT + "\nCHECKED"


# ── device / prior-procedure guard (Phase 1 options) ─────────────────────────

def test_device_questions_quote_the_option_and_point_the_same_way():
    qs = tl.device_questions(3, "No contrast within the aneurysm sac.")
    assert set(qs) == {"dv3", "dr3"}
    assert '"No contrast within the aneurysm sac."' in qs["dv3"]["instructions"]
    assert qs["dr3"]["instructions"].startswith("The dictated findings or the clinical history report the device")
    assert "mention" in qs["dr3"]["criteria"]["true"] and "Neither" in qs["dr3"]["criteria"]["false"]
    assert "CLINICAL HISTORY: EVAR 2019" in tl.device_state("CT", "EVAR 2019", "AAA.")


def test_device_keep_drops_only_a_presupposed_device_that_is_not_reported():
    ans = {"dv0": {"noul": 0.9}, "dr0": {"noul": 0.1},     # presupposed, not reported -> drop
           "dv1": {"noul": 0.9}, "dr1": {"noul": 0.8},     # presupposed, reported -> keep
           "dv2": {"noul": 0.1}, "dr2": {"noul": 0.05},    # nothing presupposed -> keep
           "dv3": {"noul": 0.9}}                           # unreadable -> drop (conservative)
    assert [tl.device_keep(ans, k) for k in range(4)] == [False, True, True, False]


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
