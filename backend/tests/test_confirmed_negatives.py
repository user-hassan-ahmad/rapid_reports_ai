"""Policy 1 for dictated findings (spec 2026-09-29-policy1-confirmed-branch-negatives-design, rev 2)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_analyser as qa


def test_confirmed_negatives_is_an_opt_in_directive():
    model = "qwen-3.8-27b"
    prod = qa.get_analyser_prompt(model, directives=("prune_v1",))
    arm_b = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES)
    assert "**If present:**" not in prod
    assert "**If present:**" in arm_b
    assert "(core | contextual)" in arm_b
    assert qa.PRODUCTION_DIRECTIVES == ("prune_v1", "finding_negatives")     # switched on 2026-09-30 (Hassan)
    assert "never the diagnosis it suggests" in arm_b
    # the management-deciding negative must survive the cap (L-45: pancreas lost SMV/SMA contact 1 in 5)
    assert "At most four negatives per finding" in arm_b
    assert "first the one the next management step depends on most" in arm_b
    # a key is one finding; its extensions are negatives under it (MSCC key "lesion with epidural extension" missed)
    assert 'never two findings joined by "with", "and" or "or"' in arm_b
    # the bullet changes nothing else in the sheet (TECHNIQUE dropped from Sections in 2/33 B sheets)
    assert "the Sections line and every other part of the sheet stay exactly as they would without it" in arm_b
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
async def test_finding_negatives_never_reach_the_impression_plan(monkeypatch):
    # Negatives stay in FINDINGS by default (2026-09-30): the plan is not shown them and cannot carry them.
    _stub_c(monkeypatch, 0.95, [NegativeDecision(index=i, action="keep") for i in range(6)])
    seen = {}
    async def fake_plan(scan_type, history, items, recs):
        seen["items"] = list(items)
        return qb.ImpressionPlan(recommendations=[], impression=[0])
    monkeypatch.setattr(qb, "_plan", fake_plan)
    b = await qb.compile_brief(SHEET_C, "CT head", "10 mm right acute subdural")
    assert seen["items"] == ["10 mm right acute subdural"]
    carry = b.text.split("Carry forward")[1].split("\n")[0]
    assert "No midline shift" not in carry and 'KEEP: "No midline shift"' in b.text


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


FINDINGS_R5 = "10 mm right acute subdural. 12 mm left adrenal nodule"


def _stub_fallback(monkeypatch, carried, fallback):
    _stub_c(monkeypatch, 0.95, [NegativeDecision(index=i, action="keep") for i in range(6)])
    async def fake_plan(scan_type, history, items, recs):
        return qb.ImpressionPlan(recommendations=[], impression=carried)
    monkeypatch.setattr(qb, "_plan", fake_plan)
    monkeypatch.setattr(qb, "_fallback", fallback)


async def _fb_adrenal(state, items, keys):
    assert keys == ["subdural haematoma", "extradural haematoma"]
    return qb.FallbackNegatives(items=[qb.FallbackItem(index=0, covered=True),
                                       qb.FallbackItem(index=1, covered=False,
                                                       negatives=["No adrenal haemorrhage.", "No local invasion"])])


@pytest.mark.asyncio
async def test_unanticipated_carried_finding_gets_offered_negatives(monkeypatch):
    _stub_fallback(monkeypatch, [0, 1], _fb_adrenal)
    b = await qb.compile_brief(SHEET_C, "CT head", FINDINGS_R5)
    fb = [o for o in b.decisions["options"] if o.get("reason") == "unanticipated finding"]
    assert fb == [{"kind": "finding_negative", "section": "FINDINGS", "text": t,
                   "finding": "12 mm left adrenal nodule", "reason": "unanticipated finding"}
                  for t in ("No adrenal haemorrhage", "No local invasion")]
    assert len([o for o in b.decisions["options"] if o["kind"] == "finding_negative"]) <= qb.MAX_FINDING_OPTIONS
    assert "No adrenal haemorrhage" not in b.text                       # never stated
    assert all(n["source"] != "fallback" for n in b.decisions["negatives"])


@pytest.mark.asyncio
async def test_fallback_ignores_findings_the_impression_does_not_carry(monkeypatch):
    _stub_fallback(monkeypatch, [0], _fb_adrenal)
    b = await qb.compile_brief(SHEET_C, "CT head", FINDINGS_R5)
    assert not [o for o in b.decisions["options"] if o.get("reason") == "unanticipated finding"]


@pytest.mark.asyncio
async def test_brief_compiles_when_the_fallback_fails(monkeypatch):
    async def boom(*a):
        raise RuntimeError("down")
    _stub_fallback(monkeypatch, [0, 1], boom)
    b = await qb.compile_brief(SHEET_C, "CT head", FINDINGS_R5)
    assert 'KEEP: "No midline shift"' in b.text
    assert not [o for o in b.decisions["options"] if o.get("reason") == "unanticipated finding"]


@pytest.mark.asyncio
async def test_fallback_shares_the_finding_options_cap(monkeypatch):
    async def many(state, items, keys):
        return qb.FallbackNegatives(items=[qb.FallbackItem(index=1, covered=False,
                                                           negatives=["No a", "No b", "No c"])])
    _stub_fallback(monkeypatch, [0, 1], many)
    b = await qb.compile_brief(SHEET_C, "CT head", FINDINGS_R5)
    assert len([o for o in b.decisions["options"] if o["kind"] == "finding_negative"]) == qb.MAX_FINDING_OPTIONS


@pytest.mark.asyncio
async def test_a_negative_listed_under_two_keys_is_stated_once(monkeypatch):
    sheet = SHEET_C.replace('  - extradural haematoma → "No venous sinus involvement" (core)',
                            '  - extradural haematoma → "No midline shift" (core)')
    _stub_c(monkeypatch, 0.95, [NegativeDecision(index=i, action="keep") for i in range(6)])
    async def both(state, questions):
        return {k: {"noul": 0.95 if k in ("f0", "f1") else 0.1} for k in questions}
    monkeypatch.setattr(qb, "_jev", both)
    b = await qb.compile_brief(sheet, "CT head", "10 mm subdural and 5 mm extradural haematoma")
    assert b.text.count('KEEP: "No midline shift"') == 1
    assert [n["text"] for n in b.decisions["negatives"]].count("No midline shift") == 1


@pytest.mark.asyncio
async def test_passed_through_options_start_with_a_capital(monkeypatch):
    out = await qrg._write_options([{"kind": "finding_negative", "section": "FINDINGS", "text": "no acute infarction",
                                     "finding": "x", "reason": "unanticipated finding"}], "f", "CT")
    assert out[0]["sentence"] == "No acute infarction."


@pytest.mark.asyncio
async def test_fallback_does_not_run_without_an_if_present_list(monkeypatch):
    # Production sheets (directive off) have no If-present list: the brief must behave as before.
    calls = []
    async def spy(state, items, keys):
        calls.append(items)
        return qb.FallbackNegatives(items=[qb.FallbackItem(index=0, covered=False, negatives=["No x"])])
    sheet = SHEET_C.split("- **If present:**")[0] + "\n## Impression Exemplars\n- **Abnormal exemplar:** \"Acute subdural.\"\n"
    _stub_fallback(monkeypatch, [0, 1], spy)
    b = await qb.compile_brief(sheet, "CT head", FINDINGS_R5)
    assert calls == []
    assert not [o for o in b.decisions["options"] if o["kind"] == "finding_negative"]


@pytest.mark.asyncio
async def test_bundled_finding_negatives_are_split_and_keep_their_key_and_tag(monkeypatch):
    sheet = SHEET_C.replace('"No midline shift" (core)', '"No superior mesenteric vein or portal vein encasement" (core)')
    _stub_c(monkeypatch, 0.95, [NegativeDecision(index=i, action="keep") for i in range(8)])
    async def split(negs):
        return [["No superior mesenteric vein encasement", "No portal vein encasement"]
                if n.startswith("No superior mesenteric vein or") else [n] for n in negs]
    monkeypatch.setattr(qb, "_split_bundled", split)
    b = await qb.compile_brief(sheet, "CT head", "10 mm right acute subdural")
    assert 'KEEP: "No superior mesenteric vein encasement" (finding: subdural haematoma)' in b.text
    assert 'KEEP: "No portal vein encasement" (finding: subdural haematoma)' in b.text
    assert "vein or portal" not in b.text


def test_tags_are_read_when_the_analyser_annotates_them():
    # Real Qwen lines (2026-09-30): a core vascular negative read as contextual was only offered.
    lines = ["- **If present:**",
             "  - Pancreatic head mass →",
             '    - "No vascular encasement at the superior mesenteric and portal venous confluence." (core — resectability, gates MDT discussion)',
             '    - "No distant lymphadenopathy." (contextual — staging)',
             '  - Sigmoid wall thickening → "No free intraperitoneal fluid is identified" (generalised peritonitis) (core)']
    assert [(c.key, c.tag) for c in qb.parse_if_present(lines)] == [
        ("Pancreatic head mass", "core"), ("Pancreatic head mass", "contextual"), ("Sigmoid wall thickening", "core")]
