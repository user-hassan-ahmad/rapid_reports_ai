"""Policy 1 for confirmed branches (spec 2026-09-29-policy1-confirmed-branch-negatives-design)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_analyser as qa


def test_confirmed_negatives_is_an_opt_in_directive():
    model = "qwen-3.8-27b"
    prod = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES)
    arm_b = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES + ("confirmed_negatives",))
    assert "**If confirmed:**" not in prod
    assert "**If confirmed:**" in arm_b
    assert "(core | contextual)" in arm_b
    assert "confirmed_negatives" not in qa.PRODUCTION_DIRECTIVES


from rapid_reports_ai import quick_report_brief as qb

DIFFS = [
    "Acute subdural — crescentic hyperdensity *(visible on this technique: yes)*",
    "Epidural — biconvex hyperdensity *(visible on this technique: yes)*",
]
IF_CONFIRMED_LINES = [
    "- **If confirmed:** (negatives stated only when the dictation confirms the branch)",
    '  - Acute subdural → "No midline shift" (core)',
    '  - Acute subdural → "No uncal herniation" (contextual)',
    '  - Epidural -> "No skull fracture"',
    '  - Haemorrhagic contusion → "No contrecoup injury" (core)',
]


def test_candidates_parse_branch_negative_and_tag():
    cands, unmatched = qb.parse_confirmed(IF_CONFIRMED_LINES, DIFFS)
    assert [(c.branch, c.text, c.tag, c.diff_index) for c in cands] == [
        ("Acute subdural", "No midline shift", "core", 0),
        ("Acute subdural", "No uncal herniation", "contextual", 0),
        ("Epidural", "No skull fracture", "contextual", 1),   # missing tag -> contextual
    ]
    assert unmatched == 1                                     # no such differential


@pytest.mark.parametrize("label,present,tag,outcome", [
    ("keep", 0.3, "core", "dropped"),                # branch not confirmed
    ("contradicted", 0.95, "core", "dropped"),       # the dictation says otherwise
    ("expected", 0.95, "core", "do_not_assert"),     # the diagnosis causes it
    ("expected", 0.6, "contextual", "do_not_assert"),
    ("keep", 0.95, "core", "stated"),
    ("keep", 0.95, "contextual", "offered"),
    ("keep", 0.6, "core", "offered"),                # branch borderline
])
def test_route_confirmed_rule_c(label, present, tag, outcome):
    assert qb.route_confirmed(label, present, tag) == outcome


from rapid_reports_ai.quick_report_brief import NegativeDecision, QwenDecisions

SHEET_C = '''# Skill Sheet: CT head — head injury

## Clinical Lane
- **Question:** Intracranial injury?
- **Differentials in scope:**
  - **Aetiology (if haemorrhage confirmed):**
    - Acute subdural — crescentic hyperdensity *(visible on this technique: yes)*
    - Epidural — biconvex hyperdensity *(visible on this technique: yes)*

## Structural Pattern
- **Normal-study path:** "The orbits are clear."

## Companion Matrix
- **Mandatory negatives:** (one line each, one finding each)
  - "No skull fracture" (trauma)
- **If confirmed:** (negatives stated only when the dictation confirms the branch)
  - Acute subdural → "No midline shift" (core)
  - Acute subdural → "No uncal herniation" (contextual)
  - Acute subdural → "No effacement of the basal cisterns" (core)
  - Acute subdural → "No subfalcine herniation" (core)
  - Epidural → "No venous sinus involvement" (core)

## Impression Exemplars
- **Abnormal exemplar:** "Acute subdural."
'''


def _stub_c(monkeypatch, subdural_present: float, qwen_negs):
    async def fake_jev(state, questions):
        out = {k: {"noul": 0.1} for k in questions}
        out["d0"] = {"noul": subdural_present}
        return out
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
    return fake_qwen


@pytest.mark.asyncio
async def test_confirmed_branch_negatives_are_stated_offered_or_labelled(monkeypatch):
    # candidates follow the one mandatory negative in Qwen's list: indices 1..5
    fq = _stub_c(monkeypatch, 0.95, [
        NegativeDecision(index=0, action="keep"),
        NegativeDecision(index=1, action="keep"),                      # core -> stated
        NegativeDecision(index=2, action="keep"),                      # contextual -> offered
        NegativeDecision(index=3, action="expected", dictated_finding="10 mm subdural"),
        NegativeDecision(index=4, action="contradicted", dictated_finding="subfalcine herniation"),
        NegativeDecision(index=5, action="keep"),                      # epidural branch not present
    ])
    b = await qb.compile_brief(SHEET_C, "CT head", "10 mm right acute subdural. Subfalcine herniation.")
    t = b.text
    assert fq.negs[1:] == ["No midline shift", "No uncal herniation", "No effacement of the basal cisterns",
                           "No subfalcine herniation", "No venous sinus involvement"]
    assert 'KEEP: "No midline shift" (confirmed: Acute subdural)' in t
    assert 'DO NOT ASSERT: "No effacement of the basal cisterns" — expected consequence of: 10 mm subdural' in t
    assert "No subfalcine herniation" not in t and "No venous sinus involvement" not in t
    assert "No uncal herniation" not in t                              # offered, not in the brief
    assert "If confirmed" not in t
    opts = [o for o in b.decisions["options"] if o["kind"] == "confirmed_negative"]
    assert opts == [{"kind": "confirmed_negative", "section": "FINDINGS", "text": "No uncal herniation",
                     "branch": "Acute subdural", "reason": "contextual"}]
    routes = {c["text"]: c["outcome"] for c in b.decisions["confirmed_negatives"]}
    assert routes == {"No midline shift": "stated", "No uncal herniation": "offered",
                      "No effacement of the basal cisterns": "do_not_assert",
                      "No subfalcine herniation": "dropped", "No venous sinus involvement": "dropped"}
    sources = {n["text"]: n["source"] for n in b.decisions["negatives"]}
    assert sources["No skull fracture"] == "sheet" and sources["No midline shift"] == "confirmed:Acute subdural"


@pytest.mark.asyncio
async def test_borderline_branch_offers_its_core_negatives_with_a_reason(monkeypatch):
    _stub_c(monkeypatch, 0.6, [NegativeDecision(index=i, action="keep") for i in range(6)])
    b = await qb.compile_brief(SHEET_C, "CT head", "Possible thin right subdural.")
    offered = [o for o in b.decisions["options"] if o["kind"] == "confirmed_negative"]
    assert len(offered) == qb.MAX_CONFIRMED_OPTIONS                     # 4 of the 4 subdural candidates
    assert offered[0]["reason"] == "branch borderline (p=0.60)"
    assert "(confirmed:" not in b.text


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
async def test_options_carry_a_section_and_confirmed_negatives_skip_the_writer(monkeypatch):
    calls = []
    async def fake_run(**kw):
        calls.append(kw["user_prompt"])
        class R:
            output = qrg._OptionSentences(sentences=["MRI brain is recommended."])
        return R()
    monkeypatch.setattr(qrg, "_run_agent_with_model", fake_run)
    opts = [{"kind": "recommendation", "text": "IMAGING: MRI brain", "reason": "either way"},
            {"kind": "confirmed_negative", "section": "FINDINGS", "text": "No uncal herniation",
             "branch": "Acute subdural", "reason": "contextual"}]
    out = await qrg._write_options(opts, "findings", "CT")
    assert "No uncal herniation" not in calls[0]
    assert out[0] == {"id": "opt0", "kind": "recommendation", "section": "IMPRESSION",
                      "sentence": "MRI brain is recommended.", "reason": "either way", "source": "IMAGING: MRI brain"}
    assert out[1] == {"id": "cn0", "kind": "confirmed_negative", "section": "FINDINGS",
                      "sentence": "No uncal herniation.", "reason": "contextual",
                      "source": "No uncal herniation", "branch": "Acute subdural"}


@pytest.mark.asyncio
async def test_confirmed_negatives_survive_when_the_writer_fails(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(qrg, "_run_agent_with_model", boom)
    opts = [{"kind": "impression", "text": "Small effusion", "reason": ""},
            {"kind": "confirmed_negative", "section": "FINDINGS", "text": "No uncal herniation",
             "branch": "Acute subdural", "reason": "contextual"}]
    out = await qrg._write_options(opts, "findings", "CT")
    assert [o["id"] for o in out] == ["cn0"]
