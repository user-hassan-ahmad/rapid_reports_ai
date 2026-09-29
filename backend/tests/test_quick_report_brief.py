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


def _stub(monkeypatch, jev: dict, qwen: qb.QwenDecisions):
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
    monkeypatch.setattr(qb, "_split_bundled", no_split)


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
