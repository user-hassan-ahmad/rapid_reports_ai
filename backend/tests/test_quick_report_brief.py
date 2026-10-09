"""Compiled brief: parse -> reconcile (stubbed) -> compile, and the raw-sheet fallback."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import quick_report_generator as qrg
from rapid_reports_ai import report_reconcile

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
       "r0": {"noul": 0.9}, "r1": {"noul": 0.1},                         # condition met (L-49 polarity)
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
            output = report_reconcile._OptionSentences(sentences='["MRI brain is recommended.", "Small right pleural effusion."]')
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


# ── option de-duplication (shared dedupe_options) ───────────────────────────

def test_dedupe_options_uses_the_quick_part_by_part_comparison():
    """Templates de-duplicate their routed options with the same comparison quick applies inline (L-49):
    an option is a duplicate only when every part is already said (stated, dictated or kept before it)."""
    from rapid_reports_ai import report_reconcile as rc
    opts = [{"kind": "finding_negative", "text": "No periaortic haematoma or aortic injury."},   # one part new
            {"kind": "finding_negative", "text": "No periaortic haematoma or free gas."},         # both parts said
            {"kind": "finding_negative", "text": "No free intraperitoneal gas"},                 # dictated
            {"kind": "finding_negative", "text": "No portal venous gas is identified."},
            {"kind": "finding_negative", "text": "No portal venous gas."},                      # an earlier option
            {"kind": "impression", "text": "No free intraperitoneal gas"}]
    kept, dropped = rc.dedupe_options(
        opts, ["No periaortic haematoma is identified."],
        "large collection - perforated. no free intraperitoneal gas. no nodes, aorta normal")
    assert dropped == ["No periaortic haematoma or free gas.", "No free intraperitoneal gas", "No portal venous gas."]
    assert [o["text"] for o in kept] == ["No periaortic haematoma or aortic injury.",
                                         "No portal venous gas is identified.", "No free intraperitoneal gas"]


async def test_option_writer_guard_drops_a_recommendation_sentence_that_names_another_thing():
    from types import SimpleNamespace
    from rapid_reports_ai import report_reconcile as rc
    opts = [{"kind": "recommendation", "text": "REFERRAL: Interventional radiology, urgent"},
            {"kind": "recommendation", "text": "IMAGING: Dedicated MRI of the region"},
            {"kind": "impression", "text": "Small cyst"}]

    async def runner(**kw):
        return SimpleNamespace(output=rc._OptionSentences(sentences=[
            "1. Perforated appendicitis with a 41 mm abscess.", "Dedicated MRI is recommended.", "Small simple cyst."]))
    guarded = await rc.write_options(opts, "f", "CT", model="m", runner=runner, require_service=True)
    assert [o["source"] for o in guarded] == ["IMAGING: Dedicated MRI of the region", "Small cyst"]
    plain = await rc.write_options(opts, "f", "CT", model="m", runner=runner)  # quick: unchanged by default
    assert len(plain) == 3


def _neg(i, action="keep", f=""):
    return qb.NegativeDecision(index=i, action=action, dictated_finding=f)


INCOMPLETE = {
    "missing": [_neg(0, "contradicted", "8 mm right subdural"), _neg(2)],
    "off_by_one": [_neg(1, "contradicted", "8 mm right subdural"), _neg(2, "expected", "3 mm midline shift"), _neg(3)],
    "duplicate": [_neg(0, "contradicted", "8 mm right subdural"), _neg(0), _neg(2)],
    "extra": [_neg(0, "contradicted", "8 mm right subdural"), _neg(1, "expected", "3 mm midline shift"), _neg(2), _neg(3)],
}


def _sequenced_qwen(monkeypatch, answers):
    calls = []
    async def fake_qwen(state, negs, normals, measurements):
        calls.append(negs)
        return qb.QwenDecisions(negatives=answers[len(calls) - 1], affected_normals=[2], applicable_measurements=[0])
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", sorted(INCOMPLETE))
async def test_incomplete_negative_answer_retries_then_raises(monkeypatch, shape):
    _stub(monkeypatch, JEV, QWEN)
    calls = _sequenced_qwen(monkeypatch, [INCOMPLETE[shape], INCOMPLETE[shape]])
    warnings = []
    monkeypatch.setattr(qb.logger, "warning", lambda msg, *a: warnings.append(msg % a))
    with pytest.raises(qb.IncompleteNegativeDecisions):
        await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    assert len(calls) == 2
    assert sum("negative classifier answer incomplete" in w for w in warnings) == 2


@pytest.mark.asyncio
async def test_incomplete_negative_answer_recovers_on_retry(monkeypatch):
    _stub(monkeypatch, JEV, QWEN)
    calls = _sequenced_qwen(monkeypatch, [INCOMPLETE["missing"], QWEN.negatives])
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    assert len(calls) == 2
    assert 'DO NOT ASSERT: "No ventricular compression" — expected consequence of: 3 mm midline shift' in b.text


@pytest.mark.asyncio
async def test_complete_negative_answer_is_used_once_unchanged(monkeypatch):
    _stub(monkeypatch, JEV, QWEN)
    baseline = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    # the order of the decisions does not matter, only that each index appears once
    calls = _sequenced_qwen(monkeypatch, [list(reversed(QWEN.negatives))])
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    assert len(calls) == 1
    assert b.text == baseline.text and b.decisions["negatives"] == baseline.decisions["negatives"]


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", sorted(INCOMPLETE))
async def test_generator_writes_from_raw_sheet_when_negative_answer_stays_incomplete(monkeypatch, shape):
    _stub(monkeypatch, JEV, QWEN)
    calls = _sequenced_qwen(monkeypatch, [INCOMPLETE[shape], INCOMPLETE[shape]])
    seen = {}
    async def fake_run(**kw):
        if kw.get("output_type") is str:
            seen["system"] = kw["system_prompt"]
        from types import SimpleNamespace
        return SimpleNamespace(output="COMPARISON:\nNone.\n\nFINDINGS:\nx.\n\nIMPRESSION:\ny." if kw.get("output_type") is str
                               else SimpleNamespace(description="d"))
    monkeypatch.setattr(qrg, "_run_agent_with_model", fake_run)
    monkeypatch.setattr(qrg, "_get_api_key_for_provider", lambda p, fallback_api_key=None: "k")
    out = await qrg.generate_quick_report(skill_sheet=SHEET, scan_type="CT head non-contrast",
                                          findings="8 mm right subdural, 3 mm midline shift", clinical_history="h")
    assert len(calls) == 2
    assert out["brief_used"] is False
    assert "Conditional Suppression Rules" in seen["system"]          # raw sheet


# ── Jev wording v2 (L-49) ────────────────────────────────────────────────────

def test_finding_questions_are_score_type():
    q = qb.q_finding("Free air")
    assert q["type"] == "score" and len(q["criteria"]) == 4
    assert q["instructions"] == ("How definitely do the dictated findings report this imaging finding as present? "
                                 "Finding: Free air")
    assert q["criteria"][2] == "Raised only as a possibility " + qb.HEDGE


def test_finding_score_reads_level_over_three():
    assert qb.finding_presence({"score": 3.0}) == 1.0
    assert abs(qb.finding_presence({"score": 2.0}) - 0.6667) < 1e-3   # hedged -> offered band
    assert qb.route_finding("keep", qb.finding_presence({"score": 2.0}), "core") == "offered"
    assert qb.route_finding("keep", qb.finding_presence({"score": 3.0}), "core") == "stated"
    assert qb.route_finding("keep", qb.finding_presence({"score": 1.0}), "core") == "dropped"


def test_present_question_names_diagnosis_and_marks_sign_as_example():
    q = qb.present_question("Perforated peptic ulcer — perigastric fluid and free gas *(visible on this technique: yes)*")
    assert q["type"] == "noul"
    assert q["instructions"] == ("The dictated findings name or describe this diagnosis as present or possible in this "
                                 "case: Perforated peptic ulcer. A typical sign (an example only; it need not be "
                                 "dictated): perigastric fluid and free gas")
    assert q["criteria"] == {"true": qb.PRESENT_TRUE, "false": qb.PRESENT_FALSE}


def test_present_question_without_discriminator_has_no_sign_clause():
    q = qb.present_question("Haemorrhage *(imaging-silent)*")
    assert "example only" not in q["instructions"] and q["instructions"].endswith(": Haemorrhage")
    assert q["instructions"] == qb.q_present("Haemorrhage")["instructions"]


@pytest.mark.asyncio
async def test_compile_asks_branch_presence_with_the_named_diagnosis(monkeypatch):
    seen = {}
    _stub(monkeypatch, JEV, QWEN)
    inner = qb._jev
    async def spy(state, questions):
        seen.update(questions)
        return await inner(state, questions)
    monkeypatch.setattr(qb, "_jev", spy)
    await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    assert seen["d0"] == qb.present_question("Acute subdural — crescentic hyperdensity *(visible on this technique: yes)*")
    assert seen["d0"]["instructions"].endswith(": Acute subdural. A typical sign (an example only; it need not be "
                                               "dictated): crescentic hyperdensity")


@pytest.mark.parametrize("met,action", [(0.7, "keep"), (0.3, "removed"), (0.5, "removed")])
@pytest.mark.asyncio
async def test_recommendation_unmet_is_one_minus_met(monkeypatch, met, action):
    seen = {}
    jev = {**JEV, "r0": {"noul": met}, "r1": {"noul": 0.9}}
    _stub(monkeypatch, jev, QWEN)
    inner = qb._jev
    async def spy(state, questions):
        seen.update(questions)
        return await inner(state, questions)
    monkeypatch.setattr(qb, "_jev", spy)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    assert seen["r0"] == {"type": "noul", "instructions": qb.Q_REC_MET + "REFERRAL: Neurosurgery for haemorrhage with mass effect"}
    assert qb.Q_REC_MET == "The dictated findings show the finding or diagnosis this recommendation is for. Recommendation: "
    recs = {r["text"]: r["action"] for r in b.decisions["recommendations"]}
    assert recs["REFERRAL: Neurosurgery for haemorrhage with mass effect"] == action
    assert recs["IMAGING: CTA for large vessel occlusion"] == "keep"          # met 0.9 -> unmet 0.1


def test_jev_upgrade_to_implicated_keeps_pointer_free_of_diagnostics():
    """A default atom upgraded to implicated by Jev "affected" keeps the classifier's pointer (shown to the
    radiologist as the dictated finding in the rail's "Check: may not hold given ..." label); the Jev score is
    recorded in jev_affected and source only, never as pointer text."""
    from types import SimpleNamespace
    atoms = [SimpleNamespace(id="a1"), SimpleNamespace(id="a2")]
    jev = {"na0": {"noul": 0.65}, "na1": {"noul": 0.7}}
    out = qb._atom_labels(atoms, None, ["1 | default | -", "2 | default | small left pleural effusion"],
                          "separate", jev)
    assert out["a1"]["cls"] == "implicated" and out["a1"]["jev_affected"] == 0.65
    assert out["a1"]["source"] == "separate+jev"
    assert out["a1"]["pointer"] == ""
    assert out["a2"]["cls"] == "implicated" and out["a2"]["pointer"] == "small left pleural effusion"


# --- Task 9: four-label negatives scheme behind RR_BRIEF_FULL_LABELS (quick only, default off) ---

_OLD_QWEN_SYS = (
    "You check a radiology skill sheet against the radiologist's dictated findings for one case. Silence in the "
    "dictation never makes a finding present.\n"
    "NEGATIVES: for each numbered negative return 'contradicted' if the dictation reports it as present or reports a "
    "finding of the same kind in the same place; 'expected' if a dictated finding would normally and predictably "
    "cause what it denies (not merely make it possible); otherwise 'keep'. For contradicted and expected, quote the "
    "dictated finding responsible.\n"
    "NORMAL LINES: list the numbers of normal-study statements that a dictated finding contradicts or acts on.\n"
    "MEASUREMENTS: list the numbers of measurement conventions whose finding is present in the dictation.")


def test_quick_sys_is_unchanged_and_full_sys_carries_the_four_labels():
    assert report_reconcile.QWEN_SYS == _OLD_QWEN_SYS   # the template pathway sends it; byte-identical
    for word in ("dictated:", "default:", "implicated:", "contradicted:", "expected:"):
        assert word in report_reconcile.QWEN_SYS_FULL
    assert "Process of exclusion" in report_reconcile.QWEN_SYS_FULL and "NORMAL LINES" in report_reconcile.QWEN_SYS_FULL


def test_negative_decision_accepts_the_full_labels_only_in_the_full_class():
    for a in ("keep", "default", "implicated", "dictated", "contradicted", "expected"):
        assert report_reconcile.NegativeDecisionFull(index=0, action=a).action == a
    with pytest.raises(Exception):
        report_reconcile.NegativeDecision(index=0, action="dictated")


def _neg_enum(model) -> list:
    """The action enum of the negatives in a decisions model's JSON schema (what the model is sent)."""
    defs = model.model_json_schema()["$defs"]
    item = next(v for k, v in defs.items() if k.startswith("NegativeDecision"))
    return sorted(item["properties"]["action"]["enum"])


@pytest.mark.parametrize("linked", [None, ("\nLINKED", "LINKED BLOCK")])
@pytest.mark.parametrize("full", [False, True])
async def test_qwen_sends_todays_schema_unless_full(monkeypatch, linked, full):
    seen = {}

    async def fake_run(**kw):
        seen.update(kw)
        class R:
            output = None
        return R()
    monkeypatch.setattr(report_reconcile, "_run_agent_with_model", fake_run)
    await report_reconcile._qwen("STATE", ["No x"], [], [], linked=linked, full=full)
    rc = report_reconcile
    if full:
        assert seen["output_type"] is (rc.QwenDecisionsFullLinked if linked else rc.QwenDecisionsFull)
        assert seen["system_prompt"].startswith(rc.QWEN_SYS_FULL)
        assert _neg_enum(seen["output_type"]) == sorted(
            ["keep", "default", "implicated", "dictated", "contradicted", "expected"])
    else:
        assert seen["output_type"] is (rc.QwenDecisionsLinked if linked else rc.QwenDecisions)
        assert seen["system_prompt"] == (rc.QWEN_SYS + linked[0] if linked else rc.QWEN_SYS)
        assert _neg_enum(seen["output_type"]) == ["contradicted", "expected", "keep"]


async def test_template_call_sends_the_three_label_schema(monkeypatch):
    """template_brief calls rc._qwen(state, negs, normals, []) positionally, never with full."""
    seen = {}

    async def fake_run(**kw):
        seen.update(kw)
        class R:
            output = None
        return R()
    monkeypatch.setattr(report_reconcile, "_run_agent_with_model", fake_run)
    monkeypatch.setenv("RR_BRIEF_FULL_LABELS", "1")   # the quick flag never reaches the template call
    await report_reconcile._qwen("STATE", ["No x"], ["Normal y."], [])
    assert seen["output_type"] is report_reconcile.QwenDecisions
    assert seen["system_prompt"] == _OLD_QWEN_SYS
    assert _neg_enum(seen["output_type"]) == ["contradicted", "expected", "keep"]


@pytest.mark.asyncio
async def test_full_labels_compile_dictated_and_implicated_lines(monkeypatch):
    monkeypatch.setenv("RR_BRIEF_FULL_LABELS", "1")
    _stub(monkeypatch, JEV, QWEN)
    seen = {}

    async def fake_qwen(state, negs, normals, measurements, linked=None, full=False):
        seen["full"] = full
        acts = ["dictated", "implicated", "default"]
        return report_reconcile.QwenDecisionsFull(negatives=[report_reconcile.NegativeDecisionFull(index=i, action=acts[i % 3],
                                                               dictated_finding="8 mm right subdural" if i % 3 == 1 else "")
                                           for i in range(len(negs))],
                                affected_normals=[], applicable_measurements=[])
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, no subdural collection on the left")
    assert seen["full"] is True
    assert '  - DICTATED: "No subdural collection"' in b.text
    assert '"No ventricular compression" (mass effect) (implicated by: 8 mm right subdural)' in b.text
    assert 'KEEP: "No skull fracture" (trauma)' in b.text
    acts = [n["action"] for n in b.decisions["negatives"] if n["source"] == "sheet"]
    assert acts == ["dictated", "implicated", "default"]


@pytest.mark.asyncio
async def test_flag_off_sends_the_old_request(monkeypatch):
    monkeypatch.delenv("RR_BRIEF_FULL_LABELS", raising=False)
    _stub(monkeypatch, JEV, QWEN)   # fake_qwen has the old signature: passing full would raise TypeError
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural, 3 mm midline shift")
    assert "DICTATED:" not in b.text and "implicated by" not in b.text


SHEET_F = '''# Skill Sheet: CT head — head injury

## Structural Pattern
- **Normal-study path:** "The orbits are clear."

## Companion Matrix
- **Mandatory negatives:** (one line each, one finding each)
  - "No skull fracture" (trauma)
- **If present:** (negatives stated only when the dictation reports the finding)
  - subdural haematoma → "No midline shift" (core)
  - subdural haematoma → "No uncal herniation" (contextual)

## Impression Exemplars
- **Abnormal exemplar:** "Acute subdural."
'''


def _stub_f(monkeypatch, subdural_present: float, negs_out):
    async def fake_jev(state, questions):
        out = {k: {"score": 0.3} if k.startswith("f") else {"noul": 0.1} for k in questions}
        out["f0"] = {"score": subdural_present * 3}
        return out
    async def fake_qwen(state, negs, normals, measurements, linked=None, full=False):
        cls_q, cls_n = ((report_reconcile.QwenDecisionsFull, report_reconcile.NegativeDecisionFull) if full
                        else (qb.QwenDecisions, qb.NegativeDecision))
        return cls_q(negatives=[cls_n(index=i, action=a, dictated_finding=f) for i, (a, f) in enumerate(negs_out)],
                     affected_normals=[], applicable_measurements=[])
    async def no_split(negs):
        return [[n] for n in negs]
    async def boom(*a):
        raise RuntimeError("not in this test")
    monkeypatch.setattr(qb, "_jev", fake_jev)
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    monkeypatch.setattr(qb, "_split_bundled", no_split)
    monkeypatch.setattr(qb, "_plan", boom)
    monkeypatch.setattr(qb, "_fallback", boom, raising=False)


@pytest.mark.parametrize("present", [0.95, 0.6])
def test_dictated_label_routes_to_stated(present):
    assert qb.route_finding("dictated", present, "contextual") == "stated"
    assert qb.route_finding("implicated", 0.6, "core") == qb.route_finding("keep", 0.6, "core")


@pytest.mark.asyncio
async def test_dictated_finding_negative_is_stated_as_dictated_never_offered(monkeypatch):
    monkeypatch.setenv("RR_BRIEF_FULL_LABELS", "1")
    _stub_f(monkeypatch, 0.95, [("default", ""), ("implicated", "10 mm subdural"),
                                ("dictated", "no uncal herniation")])
    b = await qb.compile_brief(SHEET_F, "CT head", "10 mm right acute subdural. No uncal herniation.")
    assert '  - DICTATED: "No uncal herniation" — state it as the dictation does' in b.text
    assert 'KEEP: "No midline shift" (finding: subdural haematoma)' in b.text   # implicated routes like keep
    assert not [o for o in b.decisions["options"] if o["kind"] == "finding_negative"]
    routes = {c["text"]: c["outcome"] for c in b.decisions["finding_negatives"]}
    assert routes["No uncal herniation"] == "stated"
    rec = {n["text"]: n for n in b.decisions["negatives"]}
    assert rec["No uncal herniation"]["action"] == "dictated"
    assert rec["No midline shift"]["action"] == "implicated"
    assert rec["No midline shift"]["dictated_finding"] == "10 mm subdural"


@pytest.mark.asyncio
async def test_flag_off_stated_finding_negative_records_no_dictated_finding(monkeypatch):
    monkeypatch.delenv("RR_BRIEF_FULL_LABELS", raising=False)
    _stub_f(monkeypatch, 0.95, [("keep", ""), ("keep", "10 mm subdural"), ("keep", "")])
    b = await qb.compile_brief(SHEET_F, "CT head", "10 mm right acute subdural.")
    rec = {n["text"]: n for n in b.decisions["negatives"]}
    assert rec["No midline shift"]["action"] == "keep" and rec["No midline shift"]["dictated_finding"] == ""


def test_full_sys_keeps_the_classifier_definitions():
    s = report_reconcile.QWEN_SYS_FULL
    for phrase in ("or reports a finding of the same kind in the same place",
                   "A dictated normal or negative statement about a region or organ covers each structure within it",
                   "(a broader or narrower name for the same thing)",
                   'a hedge such as "largely", "probably", "no evidence of" dropped',
                   "When a negative combines several parts, classify by its most serious part."):
        assert phrase in s, phrase
    # the brief has no history: the history clause and the "could itself be what the clinical question asks
    # about" clause stay out; the guard that the clinical question alone never implicates stays in
    assert "Step 1" not in s and "history" not in s.lower() and "asks about" not in s
    assert "The clinical question on its own" in s
