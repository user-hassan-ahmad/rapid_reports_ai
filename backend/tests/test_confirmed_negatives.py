"""Policy 1 for dictated findings (spec 2026-09-29-policy1-confirmed-branch-negatives-design, rev 2)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_analyser as qa


def test_confirmed_negatives_is_an_opt_in_directive():
    model = "qwen-3.8-27b"
    prod = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES)
    arm_b = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES + ("finding_negatives",))
    assert "**If present:**" not in prod
    assert "**If present:**" in arm_b
    assert "(core | contextual)" in arm_b
    assert "finding_negatives" not in qa.PRODUCTION_DIRECTIVES
    assert "never the diagnosis it suggests" in arm_b
    assert "confirmed_negatives" not in qa.DIRECTIVES


from rapid_reports_ai import quick_report_brief as qb

@pytest.mark.parametrize("label,present,tag,outcome", [
    ("keep", 0.3, "core", "dropped"),                # finding not reported
    ("contradicted", 0.95, "core", "dropped"),       # the dictation says otherwise
    ("expected", 0.95, "core", "do_not_assert"),     # the finding causes it
    ("expected", 0.6, "contextual", "do_not_assert"),
    ("keep", 0.95, "core", "stated"),
    ("keep", 0.95, "contextual", "offered"),
    ("keep", 0.6, "core", "offered"),                # finding borderline
])
def test_route_finding_rule_c(label, present, tag, outcome):
    assert qb.route_finding(label, present, tag) == outcome


from rapid_reports_ai.quick_report_brief import NegativeDecision, QwenDecisions

SHEET_C = '''# Skill Sheet: CT head — head injury

## Structural Pattern
- **Normal-study path:** "The orbits are clear."

## Companion Matrix
- **Mandatory negatives:** (one line each, one finding each)
  - "No skull fracture" (trauma)
- **If present:** (negatives stated only when the dictation reports the finding)
  - subdural haematoma → "No midline shift" (core)
  - subdural haematoma → "No uncal herniation" (contextual)
  - subdural haematoma → "No effacement of the basal cisterns" (core)
  - subdural haematoma → "No subfalcine herniation" (core)
  - extradural haematoma → "No venous sinus involvement" (core)

## Impression Exemplars
- **Abnormal exemplar:** "Acute subdural."
'''


def _stub_c(monkeypatch, subdural_present: float, qwen_negs):
    async def fake_jev(state, questions):
        fake_jev.questions = questions
        out = {k: {"noul": 0.1} for k in questions}
        out["f0"] = {"noul": subdural_present}
        return out
    async def no_fallback(*a):
        raise RuntimeError("no fallback in this test")
    monkeypatch.setattr(qb, "_fallback", no_fallback, raising=False)
    async def fake_qwen(state, negs, normals, measurements):
        fake_qwen.negs = negs
        return QwenDecisions(negatives=qwen_negs, affected_normals=[], applicable_measurements=[])
    async def no_split(negs):
        return [[n] for n in negs]
    async def no_plan(*a):
        raise RuntimeError("no plan")
    monkeypatch.setattr(qb, "_jev", fake_jev)
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    monkeypatch.setattr(qb, "_split_bundled", no_split)
    monkeypatch.setattr(qb, "_plan", no_plan)
    fake_qwen.jev = fake_jev
    return fake_qwen


@pytest.mark.asyncio
async def test_finding_negatives_are_stated_offered_or_labelled(monkeypatch):
    # candidates follow the one mandatory negative in Qwen's list: indices 1..5
    fq = _stub_c(monkeypatch, 0.95, [
        NegativeDecision(index=0, action="keep"),
        NegativeDecision(index=1, action="keep"),                      # core -> stated
        NegativeDecision(index=2, action="keep"),                      # contextual -> offered
        NegativeDecision(index=3, action="expected", dictated_finding="10 mm subdural"),
        NegativeDecision(index=4, action="contradicted", dictated_finding="subfalcine herniation"),
        NegativeDecision(index=5, action="keep"),                      # extradural not reported
    ])
    b = await qb.compile_brief(SHEET_C, "CT head", "10 mm right acute subdural. Subfalcine herniation.")
    t = b.text
    assert fq.negs[1:] == ["No midline shift", "No uncal herniation", "No effacement of the basal cisterns",
                           "No subfalcine herniation", "No venous sinus involvement"]
    assert 'KEEP: "No midline shift" (finding: subdural haematoma)' in t
    assert 'DO NOT ASSERT: "No effacement of the basal cisterns" — expected consequence of: 10 mm subdural' in t
    assert "No subfalcine herniation" not in t and "No venous sinus involvement" not in t
    assert "No uncal herniation" not in t                              # offered, not in the brief
    assert "If present" not in t
    opts = [o for o in b.decisions["options"] if o["kind"] == "finding_negative"]
    assert opts == [{"kind": "finding_negative", "section": "FINDINGS", "text": "No uncal herniation",
                     "finding": "subdural haematoma", "reason": "contextual"}]
    routes = {c["text"]: c["outcome"] for c in b.decisions["finding_negatives"]}
    assert routes == {"No midline shift": "stated", "No uncal herniation": "offered",
                      "No effacement of the basal cisterns": "do_not_assert",
                      "No subfalcine herniation": "dropped", "No venous sinus involvement": "dropped"}
    jq = {k: v["instructions"] for k, v in fq.jev.questions.items() if k.startswith("f")}
    assert jq == {"f0": qb.Q_FINDING + "subdural haematoma", "f1": qb.Q_FINDING + "extradural haematoma"}
    sources = {n["text"]: n["source"] for n in b.decisions["negatives"]}
    assert sources["No skull fracture"] == "sheet" and sources["No midline shift"] == "finding:subdural haematoma"


@pytest.mark.asyncio
async def test_borderline_finding_offers_its_core_negatives_with_a_reason(monkeypatch):
    _stub_c(monkeypatch, 0.6, [NegativeDecision(index=i, action="keep") for i in range(6)])
    b = await qb.compile_brief(SHEET_C, "CT head", "Possible thin right subdural.")
    offered = [o for o in b.decisions["options"] if o["kind"] == "finding_negative"]
    assert len(offered) == qb.MAX_FINDING_OPTIONS                       # 4 of the 4 subdural candidates
    assert offered[0]["reason"] == "finding borderline (p=0.60)"
    assert "(finding:" not in b.text


@pytest.mark.asyncio
async def test_plan_carries_only_stated_negatives_it_chose(monkeypatch):
    _stub_c(monkeypatch, 0.95, [NegativeDecision(index=i, action="keep") for i in range(6)])
    seen = {}
    async def fake_plan(scan_type, history, items, recs, cand_negs=()):
        seen["cands"] = list(cand_negs)
        # 0 = "No midline shift" (stated), 1 = "No uncal herniation" (offered): only 0 may be carried
        return qb.ImpressionPlan(recommendations=[], impression=[0], carry_negatives=[0, 1])
    monkeypatch.setattr(qb, "_plan", fake_plan)
    b = await qb.compile_brief(SHEET_C, "CT head", "10 mm right acute subdural")
    assert seen["cands"][:2] == ["No midline shift", "No uncal herniation"]
    carry = b.text.split("Carry forward")[1].split("\n")[0]
    assert '"No midline shift"' in carry and "No uncal herniation" not in carry
    assert b.decisions["impression_plan"]["carry_negatives"] == ["No midline shift"]


def test_plan_prompt_keeps_negatives_out_of_the_impression_by_default():
    assert "carry_negatives" in qb.PLAN_SYS
    assert "changes the interpretation of a carried finding" in qb.PLAN_SYS


from rapid_reports_ai import quick_report_generator as qrg


@pytest.mark.asyncio
async def test_options_carry_a_section_and_finding_negatives_skip_the_writer(monkeypatch):
    calls = []
    async def fake_run(**kw):
        calls.append(kw["user_prompt"])
        class R:
            output = qrg._OptionSentences(sentences=["MRI brain is recommended."])
        return R()
    monkeypatch.setattr(qrg, "_run_agent_with_model", fake_run)
    opts = [{"kind": "recommendation", "text": "IMAGING: MRI brain", "reason": "either way"},
            {"kind": "finding_negative", "section": "FINDINGS", "text": "No uncal herniation",
             "finding": "subdural haematoma", "reason": "contextual"}]
    out = await qrg._write_options(opts, "findings", "CT")
    assert "No uncal herniation" not in calls[0]
    assert out[0] == {"id": "opt0", "kind": "recommendation", "section": "IMPRESSION",
                      "sentence": "MRI brain is recommended.", "reason": "either way", "source": "IMAGING: MRI brain"}
    assert out[1] == {"id": "fn0", "kind": "finding_negative", "section": "FINDINGS",
                      "sentence": "No uncal herniation.", "reason": "contextual",
                      "source": "No uncal herniation", "finding": "subdural haematoma"}


@pytest.mark.asyncio
async def test_finding_negatives_survive_when_the_writer_fails(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(qrg, "_run_agent_with_model", boom)
    opts = [{"kind": "impression", "text": "Small effusion", "reason": ""},
            {"kind": "finding_negative", "section": "FINDINGS", "text": "No uncal herniation",
             "finding": "subdural haematoma", "reason": "contextual"}]
    out = await qrg._write_options(opts, "findings", "CT")
    assert [o["id"] for o in out] == ["fn0"]


@pytest.mark.asyncio
async def test_candidate_persists_the_brief(monkeypatch):
    from rapid_reports_ai import quick_report_api as api

    async def fake_generate(**kw):
        return {"report_content": "R", "description": "d", "brief_used": True,
                "brief_text": "BRIEF", "brief_decisions": {"negatives": []}, "brief_options": []}
    monkeypatch.setattr(api, "generate_quick_report", fake_generate)
    monkeypatch.setattr(api, "log_generator_run", lambda **kw: None)
    cand = await api._run_one_generator(skill_sheet_markdown="S", findings="F", model_name="m", run_id="r",
                                        scan_type="CT", clinical_history="h")
    assert cand["brief"] == {"text": "BRIEF", "decisions": {"negatives": []}}


def test_if_present_parses_keys_in_both_shapes():
    lines = ["- **If present:** (negatives stated only when the dictation reports the finding)",
             '  - pancreatic head mass → "No superior mesenteric vein contact." (core)',
             '  - pancreatic head mass -> "No peritoneal deposit"',
             "  - spiculated lung nodule →",
             '    - "No chest wall invasion." (core)']
    cands = qb.parse_if_present(lines)
    assert [(c.key, c.text, c.tag) for c in cands] == [
        ("pancreatic head mass", "No superior mesenteric vein contact", "core"),
        ("pancreatic head mass", "No peritoneal deposit", "contextual"),
        ("spiculated lung nodule", "No chest wall invasion", "core"),
    ]
    assert qb.distinct_keys(cands) == ["pancreatic head mass", "spiculated lung nodule"]
