"""Compiled brief: parse -> reconcile (stubbed) -> compile, and the raw-sheet fallback."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import quick_report_generator as qrg

SHEET = '''# Skill Sheet: CT head non-contrast — query haemorrhage

## Scan Context
- **Modality:** CT head, non-contrast
- **Out of scope:** Vessel lumen (requires CTA)
- **Modality non-assessables:** Early ischaemia within 3 hours

## Clinical Lane
- **Question:** Rule out haemorrhage
- **Differentials in scope:**
  - **Triage:** Haemorrhage vs ischaemia
  - **Aetiology (if haemorrhage confirmed):**
    - Acute subdural — crescentic hyperdensity *(visible on this technique: yes)*
    - Epidural — biconvex hyperdensity *(visible on this technique: yes)*
    - Vascular malformation — needs angiography *(visible on this technique: no — requires CTA)*
    - Coagulopathy *(imaging-silent — requires clinical/laboratory correlation)*

## Structural Pattern
- **Sections:** COMPARISON, TECHNIQUE, FINDINGS, IMPRESSION
- **Normal-study path:** "The ventricles are normal in size. The orbits are clear. No midline shift."

## Companion Matrix
- **In-scope companions:** mass effect, herniation
- **Mandatory negatives:** (one line each, one finding each)
  - "No subdural collection" (excludes subdural)
  - "No ventricular compression" (mass effect)
  - "No skull fracture" (trauma)
- **Out-of-scope suppressed:** CTA

## Style Exemplars
- **Subdural** Abnormal: "An 8 mm subdural."
- **Infarct** Abnormal: "MCA territory infarct."

## Conditional Suppression Rules
- IF multiple negatives fire THEN consolidate.

## Measurement Conventions
- **Subdural thickness:** mm
- **Infarct volume:** ml

## Impression Exemplars
- **Opening convention:** Index finding first
- **Normal exemplar:** "No haemorrhage."
- **Abnormal exemplar:** "Acute subdural."
- **Complicated exemplar:** "Subdural with herniation."
- **Recommendation scope:**
  - REFERRAL: Neurosurgery for haemorrhage with mass effect
  - IMAGING: CTA for large vessel occlusion
'''


def _stub(monkeypatch, jev: dict, qwen: qb.QwenDecisions, plan: qb.ImpressionPlan | None = None):
    async def fake_jev(state, questions):
        missing = set(questions) - set(jev)
        assert not missing, missing
        return jev
    async def fake_qwen(state, negs, normals, measurements):
        return qwen
    async def no_split(negs):
        return [[n] for n in negs]
    monkeypatch.setattr(qb, "_jev", fake_jev)
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    async def fake_plan(scan_type, history, items, recs):
        if plan is None:
            raise RuntimeError("no plan in this test")
        return plan
    monkeypatch.setattr(qb, "_split_bundled", no_split)
    monkeypatch.setattr(qb, "_plan", fake_plan)
    async def no_fallback(state, items, keys):
        return None
    monkeypatch.setattr(qb, "_fallback", no_fallback)


JEV = {"n0": {"noul": 0.9}, "n1": {"noul": 0.1}, "n2": {"noul": 0.8},        # ventricles, orbits, midline
       "d0": {"noul": 0.9}, "d1": {"noul": 0.1}, "d2": {"noul": 0.1}, "d3": {"noul": 0.1},
       "r0": {"noul": 0.1}, "r1": {"noul": 0.9},
       "s0": {"noul": 0.9}, "s1": {"noul": 0.1},
       "imp": {"choice": "v1"}}
QWEN = qb.QwenDecisions(
    negatives=[qb.NegativeDecision(index=0, action="contradicted", dictated_finding="8 mm right subdural"),
               qb.NegativeDecision(index=1, action="expected", dictated_finding="3 mm midline shift"),
               qb.NegativeDecision(index=2, action="keep")],
    affected_normals=[2], applicable_measurements=[0])


@pytest.mark.asyncio
async def test_compile_labels_removes_and_keeps(monkeypatch):
    _stub(monkeypatch, JEV, QWEN)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    t = b.text
    assert 'OMIT: "No subdural collection" — the dictation reports: 8 mm right subdural' in t
    assert 'DO NOT ASSERT: "No ventricular compression" — expected consequence of: 3 mm midline shift' in t
    assert 'KEEP: "No skull fracture" (trauma)' in t
    # normals: orbits kept; ventricles (Jev only) and midline (Jev and Qwen) -> do not assert, never deleted
    assert '**Normal-study path:** "The orbits are clear."' in t
    flagged = t.split("Do not assert as normal")[1].split("\n")[0]
    assert '"The ventricles are normal in size."' in flagged and '"No midline shift."' in flagged
    # differentials, policy 1: epidural (visible, not present) removed; malformation (not visible)
    # and coagulopathy (imaging-silent) kept; subdural (present) kept
    assert "Epidural" not in t and "Vascular malformation" in t and "Coagulopathy" in t and "Acute subdural" in t
    # recommendations, exemplars, measurements
    assert "Neurosurgery" in t and "CTA for large vessel occlusion" not in t
    assert "Abnormal exemplar" in t and "Normal exemplar" not in t and "Complicated exemplar" not in t
    assert "An 8 mm subdural" in t and "MCA territory infarct" not in t
    assert "Subdural thickness" in t and "Infarct volume" not in t
    # lean removals
    for gone in ("Out of scope", "Modality non-assessables", "In-scope companions", "Out-of-scope suppressed",
                 "Conditional Suppression Rules"):
        assert gone not in t, gone
    assert b.decisions["impression_variant"].startswith("Abnormal")


@pytest.mark.asyncio
async def test_generator_falls_back_to_raw_sheet_when_the_brief_fails(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("jev down")
    seen = {}
    async def fake_run(**kw):
        if kw.get("output_type") is str:
            seen["system"] = kw["system_prompt"]
        from types import SimpleNamespace
        return SimpleNamespace(output="COMPARISON:\nNone.\n\nFINDINGS:\nx.\n\nIMPRESSION:\ny." if kw.get("output_type") is str
                               else SimpleNamespace(description="d"))
    monkeypatch.setattr(qrg, "compile_brief", boom)
    monkeypatch.setattr(qrg, "_run_agent_with_model", fake_run)
    monkeypatch.setattr(qrg, "_get_api_key_for_provider", lambda p, fallback_api_key=None: "k")
    out = await qrg.generate_quick_report(skill_sheet=SHEET, scan_type="CT head", findings="f", clinical_history="h")
    assert out["brief_used"] is False
    assert "Conditional Suppression Rules" in seen["system"]          # raw sheet
    assert "A canonical line from the skill sheet is a proposal" in seen["system"]   # full principle 12


def test_measurement_pattern_catches_values_not_anatomical_labels():
    for s in ["Sinuses of Valsalva 32 mm.", "Minimum calibre 8mm.", "Ejection fraction 60%.", "Area 510 mm².",
              "The aorta measures 2.2 cm.", "Angle 15 degrees."]:
        assert qb._MEASUREMENT.search(s), s
    for s in ["No abnormality at C1–C2.", "The conus terminates at T12/L1.", "Segment VI is clear.",
              "Raphe at 12 o'clock.", "The L4/5 disc is normal."]:
        assert not qb._MEASUREMENT.search(s), s


@pytest.mark.asyncio
async def test_plan_routes_recommendations_and_writes_the_impression_plan(monkeypatch):
    findings = "8 mm right subdural. 3 mm midline shift. Age-related involutional change."
    plan = qb.ImpressionPlan(
        recommendations=[qb.RecDecision(index=0, decision="optional", reason="either way"),
                         qb.RecDecision(index=1, decision="include")],
        impression=[0, 1], findings_only=[2])

    _stub(monkeypatch, JEV, QWEN, plan)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", findings, "fall on anticoagulation")
    t = b.text
    # Jev's unmet condition wins over Qwen's include; an optional recommendation is offered, not written
    assert "  - IMAGING: CTA" not in t and "Neurosurgery" not in t.split("## Impression Plan")[0]
    assert b.decisions["options"] == [{"kind": "recommendation", "text": "REFERRAL: Neurosurgery for haemorrhage with mass effect",
                                       "reason": "either way"}]
    plan_block = t.split("## Impression Plan")[1]
    assert '"8 mm right subdural" "3 mm midline shift"' in plan_block
    assert 'Findings only (not in the impression):** "Age-related involutional change"' in plan_block


def test_split_findings_numbers_bullets_lines_and_sentences():
    assert qb.split_findings("- A mass. B node\n- No effusion") == ["A mass", "B node", "No effusion"]


@pytest.mark.parametrize("dictation, expected", [
    # radiologists dictate in lower case: every sentence is its own finding
    ("large volume free gas. gas and fluid around D1. no nodes, aorta normal.",
     ["large volume free gas", "gas and fluid around D1", "no nodes, aorta normal"]),
    # mixed case, measurements with decimals stay whole
    ("3.5 cm mass in segment 7. cbd 6.2 mm. No ascites.",
     ["3.5 cm mass in segment 7", "cbd 6.2 mm", "No ascites"]),
    # abbreviations and initials never end a sentence
    ("collection, e.g. abscess vs. haematoma. approx. 4 cm. discussed with Dr. Smith. reviewed by J. Bloggs",
     ["collection, e.g. abscess vs. haematoma", "approx. 4 cm", "discussed with Dr. Smith", "reviewed by J. Bloggs"]),
    ("small effusion, i.e. reactive. cf. prior CT stable", ["small effusion, i.e. reactive", "cf. prior CT stable"]),
    ("no. of lesions unchanged. no. 3 node enlarged. ascites: no. liver normal",
     ["no. of lesions unchanged", "no. 3 node enlarged", "ascites: no", "liver normal"]),
    # bullets, newlines and slashes still split, and lower-case sentences within them
    ("- free fluid. no collection\n- spleen normal / kidneys normal",
     ["free fluid", "no collection", "spleen normal", "kidneys normal"]),
    # closing bracket or percent before the full stop
    ("stenosis 70%. occluded ICA (left). patent vertebrals", ["stenosis 70%", "occluded ICA (left)", "patent vertebrals"]),
])
def test_split_findings_splits_lower_case_sentences(dictation, expected):
    assert qb.split_findings(dictation) == expected


@pytest.mark.asyncio
async def test_removed_investigations_are_named_and_referrals_removed_silently(monkeypatch):
    plan = qb.ImpressionPlan(recommendations=[
        qb.RecDecision(index=0, decision="exclude", exclude_reason="routine_workup", reason="receiving team"),
        qb.RecDecision(index=1, decision="exclude", exclude_reason="routine_workup", reason="source search")],
        impression=[0])
    _stub(monkeypatch, JEV, QWEN, plan)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural", "fall")
    # a referral is removed silently; an investigation excluded as routine workup is named
    assert "Neurosurgery" not in b.text.split("## Impression Plan")[0]
    assert 'Do not recommend' in b.text and '"CTA for large vessel occlusion"' in b.text
    # an investigation excluded because its condition is unmet is removed silently
    plan.recommendations[1].exclude_reason = "condition_unmet"
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural", "fall")
    assert "Do not recommend" not in b.text and "CTA for large vessel occlusion" not in b.text


@pytest.mark.asyncio
async def test_option_sentences_pair_with_their_items_and_fail_to_empty(monkeypatch):
    opts = [{"kind": "recommendation", "text": "IMAGING: MRI brain", "reason": "either way"},
            {"kind": "impression", "text": "Small right pleural effusion", "reason": ""}]

    async def fake_run(**kw):
        class R:
            output = qrg._OptionSentences(sentences='["MRI brain is recommended.", "Small right pleural effusion."]')
        return R()
    monkeypatch.setattr(qrg, "_run_agent_with_model", fake_run)
    out = await qrg._write_options(opts, "findings", "CT")
    assert [o["id"] for o in out] == ["opt0", "opt1"]
    assert out[0]["sentence"] == "MRI brain is recommended." and out[0]["source"] == "IMAGING: MRI brain"

    async def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(qrg, "_run_agent_with_model", boom)
    assert await qrg._write_options(opts, "findings", "CT") == []
    assert await qrg._write_options([], "findings", "CT") == []
