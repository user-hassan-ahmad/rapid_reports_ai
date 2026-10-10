"""Byte-identity pins for the quick path while its engine moves to shared modules
(spec 2026-09-30-template-pipeline-mirror-design §1). Pins outputs AND model inputs (every
stubbed call's arguments, the plan's real prompt, and a hash of each prompt constant that moves).
Regenerate only on an intended change:
UPDATE_GOLDEN=1 uv run pytest tests/test_golden_quick_pipeline.py

Re-pinned 2026-10-01 for PR #5 (L-49, Jev wording v2 + classify-first omission repair): the snapshot was
generated on the PR #5 branch (origin/fix/quick-split-and-classifier) and on this branch from this same
file, and the two are identical.

Re-pinned 2026-10-01 for main PR #6 (dictated negatives never removed) and PR #7 (positive contradictions
review only, repair_report deleted): generated on origin/main (f5e25a2) and on this branch from this same
file; the two are identical."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
from types import SimpleNamespace

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import quick_report_quality as qq

from tests.test_confirmed_negatives import SHEET_C
from tests.test_quick_report_brief import JEV, QWEN, SHEET

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "golden_quick.json"
FINDINGS = "8 mm right subdural haematoma. 3 mm midline shift."
# "No hydrocephalus, no herniation, ..." splits into "No no herniation": a known clauses() quirk,
# pinned deliberately. Fixing it later is an intended change and needs a regeneration.
REPORT = """FINDINGS:
An 8 mm right subdural haematoma. No skull fracture. No hydrocephalus, no herniation, and no intraventricular extension.

IMPRESSION:
Acute right subdural haematoma with 3 mm midline shift.

Dr A"""
LIST_REPORT = "FINDINGS:\nNo ascites, collection or free air.\n\nIMPRESSION:\nNormal."
FINDINGS_C = "10 mm right acute subdural. 12 mm left adrenal nodule"

BRIEF_PROMPTS = ("Q_AFFECTED", "HEDGE", "PRESENT_TRUE", "PRESENT_FALSE", "Q_REC_MET", "Q_STYLE_MATCH",
                 "QWEN_SYS", "PLAN_SYS", "FALLBACK_SYS")
QUALITY_PROMPTS = ("Q_CONTRA", "Q_RESTATED", "Q_CONVEYS", "INSERT_SYS", "Q_DICTATED")
# Question builders (L-49): each pinned by the question it builds for a fixed input.
BRIEF_QUESTIONS = {"q_finding": "free air", "q_present": "Perforation",
                   "present_question": "Perforated ulcer — free gas *(visible on this technique: yes)*"}
QUALITY_QUESTIONS = {"q_restated": "free air", "q_omission": "free air", "q_select_choice": "free air",
                     "q_select_noul": "free air"}

_REAL_PLAN = qb._plan   # captured before any test patches it


def _engine():
    """The module whose _run_agent_with_model _plan calls: the brief today, report_reconcile once
    Task 2 moves the reconcile engine there. The switch lets one golden span the move."""
    try:
        import rapid_reports_ai.report_reconcile as rc
        return rc
    except ModuleNotFoundError as e:
        if e.name != "rapid_reports_ai.report_reconcile":
            raise
        return qb


def _sha(s) -> str:
    s = s if isinstance(s, str) else json.dumps(s, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _review_engine():
    """The module whose _run_agent_with_model insert_findings calls: report_review on the shared engine,
    quick_report_quality before it."""
    try:
        import rapid_reports_ai.report_review as rr
        return rr
    except ModuleNotFoundError as e:
        if e.name != "rapid_reports_ai.report_review":
            raise
        return qq


def _recorder(log: dict, name: str, result):
    """An async stub that logs its arguments under `name` and returns `result(*args)`."""
    async def fn(*args, **kw):
        log.setdefault(name, []).append(list(args) + ([kw] if kw else []))   # kw: e.g. the brief's full=True
        return result(*args)
    return fn


def _raise(msg):
    def f(*_):
        raise RuntimeError(msg)
    return f


def _stub_brief(monkeypatch, jev: dict, qwen: qb.QwenDecisions, plan=None, fallback=None) -> dict:
    """Stub every model call compile_brief makes with a recorder; returns the call log."""
    log: dict = {}
    monkeypatch.setattr(qb, "_jev", _recorder(log, "_jev", lambda state, qs: jev))
    monkeypatch.setattr(qb, "_qwen", _recorder(log, "_qwen", lambda *a: qwen))
    monkeypatch.setattr(qb, "_split_bundled", _recorder(log, "_split_bundled", lambda negs: [[n] for n in negs]))
    monkeypatch.setattr(qb, "_plan", _recorder(log, "_plan", (lambda *a: plan) if plan else _raise("no plan")))
    monkeypatch.setattr(qb, "_fallback", _recorder(log, "_fallback", lambda *a: fallback))
    return log


async def _brief(monkeypatch, sheet, findings, jev, qwen, plan=None, fallback=None) -> dict:
    log = _stub_brief(monkeypatch, jev, qwen, plan, fallback)
    b = await qb.compile_brief(sheet, "CT head", findings, "fall")
    return {"text": b.text, "decisions": b.decisions, "calls": log}


async def _briefs(monkeypatch) -> dict:
    # Plan present: REFERRAL included, IMAGING excluded as routine workup (the barred line),
    # one finding carried and one offered as an optional impression item.
    planned = qb.ImpressionPlan(
        recommendations=[qb.RecDecision(index=0, decision="include", reason="mass effect"),
                         qb.RecDecision(index=1, decision="exclude", exclude_reason="routine_workup",
                                        reason="diagnosis made")],
        impression=[0], optional_impression=[1])
    # Finding negatives (L-45): subdural clearly reported, so core negatives are stated and the
    # contextual one offered; extradural absent, so dropped. The adrenal item is carried by the
    # plan and uncovered, so the fallback offers its negatives.
    jev_c = {"n0": {"noul": 0.1}, "f0": {"score": 2.85}, "f1": {"score": 0.3}}   # graded presence x 3 (L-49)
    qwen_c = qb.QwenDecisions(negatives=[qb.NegativeDecision(index=i, action="keep") for i in range(6)],
                              affected_normals=[], applicable_measurements=[])
    fallback_c = qb.FallbackNegatives(items=[
        qb.FallbackItem(index=0, covered=True),
        qb.FallbackItem(index=1, covered=False, negatives=["No adrenal haemorrhage.", "No local invasion",
                                                           "No midline shift is identified"])])   # a duplicate
    return {
        "no_plan": await _brief(monkeypatch, SHEET, FINDINGS, JEV, QWEN),
        # r1 met (L-49 polarity): the IMAGING candidate reaches the plan, which bars it.
        "planned": await _brief(monkeypatch, SHEET, FINDINGS, {**JEV, "r1": {"noul": 0.9}}, QWEN, planned),
        "finding_negatives": await _brief(monkeypatch, SHEET_C, FINDINGS_C, jev_c, qwen_c,
                                          qb.ImpressionPlan(recommendations=[], impression=[0, 1]), fallback_c),
    }


async def _plan_prompt(monkeypatch) -> dict:
    """The real _plan, with only the model call replaced: pins its system/user prompt and settings."""
    seen: dict = {}
    canned = qb.ImpressionPlan(recommendations=[qb.RecDecision(index=0, decision="include")], impression=[0])

    async def fake_run(**kw):
        seen.update(kw)
        return SimpleNamespace(output=canned)
    monkeypatch.setattr(_engine(), "_run_agent_with_model", fake_run)
    out = await _REAL_PLAN("CT head", "fall", ["a", "b"], ["REFERRAL: x"])
    given = {"system_prompt": seen["system_prompt"], "user_prompt": seen["user_prompt"],
             "model_settings": seen["model_settings"], "model_name": seen["model_name"],
             "output_type": seen["output_type"].__name__, "output": out.model_dump()}
    await _REAL_PLAN("CT head", "", ["a"], [])   # empty history and no recs: the '(not given)' path
    return {**given, "user_prompt_no_history": seen["user_prompt"]}


async def _check(monkeypatch) -> dict:
    # c1/r1: a contradiction whose denied finding is dictated (flagged). c2/r2: a contradiction
    # whose denied finding is not dictated (suppressed by the restated gate). o0: a bad option.
    # Omission (L-49): both items selected by Jev; i0 stated (no flag), i1 partial (review only).
    scores = {"c1": 0.9, "r1": 0.9, "c2": 0.9, "r2": 0.1, "o0": 0.9, "lt0": 0.9, "lt1": 0.8}
    choices = {"sel0": {"abnormal_finding": 0.9, "normal_or_negative": 0.1},
               "sel1": {"abnormal_finding": 0.6, "mixed_abnormal_and_normal": 0.1, "normal_or_negative": 0.3},
               "i0": {"stated": 0.8, "partial": 0.2}, "i1": {"stated": 0.1, "partial": 0.7, "absent": 0.2}}
    log: dict = {}
    # check() calls _jev through the brief module today and through report_review (rc) after Task 3.
    target = qq.rc if hasattr(qq, "rc") else qq.qb
    monkeypatch.setattr(target, "_jev", _recorder(
        log, "_jev", lambda state, qs: {k: {"probabilities": choices[k]} if k in choices else {"noul": scores.get(k, 0.1)}
                                        for k in qs}))
    options = [{"id": "opt-a", "sentence": "No hydrocephalus."}, {"id": "opt-b"}]
    res = await qq.check(REPORT, FINDINGS, "CT head", options)
    return {"result": res.model_dump(), "calls": log}


async def _insert(monkeypatch) -> dict:
    """insert_findings (L-49): the normal-only and invented-negative sentences are skipped in code, Jev's
    duplicate check skips the conveyed one, the rest is placed after its anchor."""
    log: dict = {}
    target = qq.rc if hasattr(qq, "rc") else qq.qb
    monkeypatch.setattr(target, "_jev", _recorder(
        log, "_jev", lambda state, qs: {k: {"noul": 0.6 if k == "d1" else 0.05} for k in qs}))
    items = ["3 mm midline shift", "small left frontal contusion", "ventricles normal"]
    out = qq.Insertions(items=[
        qq.Insertion(after="An 8 mm right subdural haematoma.", sentence="There is 3 mm of midline shift"),
        qq.Insertion(after="An 8 mm right subdural haematoma.", sentence="Midline shift of 3 mm."),
        qq.Insertion(after="No skull fracture.", sentence="The ventricles are normal in size."),
        qq.Insertion(after="No skull fracture.", sentence="Small left frontal contusion without haemorrhage."),
        qq.Insertion(after="nowhere", sentence="Small left frontal contusion.")])

    async def fake_run(**kw):
        log.setdefault("model", []).append({k: kw[k] for k in ("system_prompt", "user_prompt", "model_settings")})
        return SimpleNamespace(output=out)
    monkeypatch.setattr(_review_engine(), "_run_agent_with_model", fake_run)
    res = await qq.insert_findings(REPORT, FINDINGS, items)
    return {"result": res.model_dump(), "calls": log}


async def _snapshot(monkeypatch) -> dict:
    fnd, imp = qq.report_sections(REPORT)
    return {"prompt_hashes": {**{f"qb.{n}": _sha(getattr(qb, n)) for n in BRIEF_PROMPTS},
                              **{f"qq.{n}": _sha(getattr(qq, n)) for n in QUALITY_PROMPTS},
                              **{f"qb.{n}()": _sha(getattr(qb, n)(a)) for n, a in BRIEF_QUESTIONS.items()},
                              **{f"qq.{n}()": _sha(getattr(qq, n)(a)) for n, a in QUALITY_QUESTIONS.items()}},
            "plan_prompt": await _plan_prompt(monkeypatch),
            "briefs": await _briefs(monkeypatch),
            "check": await _check(monkeypatch),
            "insert": await _insert(monkeypatch),
            "clauses": qq.clauses(fnd) + qq.clauses(imp),
            "removed_sentence": qq.remove_negative_clause(REPORT, "No skull fracture"),
            "removed_list": qq.remove_negative_clause(LIST_REPORT, "No ascites")}


async def test_quick_pipeline_matches_golden(monkeypatch):
    snap = json.loads(json.dumps(await _snapshot(monkeypatch)))
    assert snap["removed_sentence"] != REPORT, "sentence removal was a no-op"
    assert snap["removed_list"] != LIST_REPORT, "list-item removal was a no-op"
    fn = snap["briefs"]["finding_negatives"]["decisions"]["finding_negatives"]
    assert {"stated", "offered"} <= {c["outcome"] for c in fn}, "finding-negative branches not exercised"
    assert any(c["tag"] == "fallback" for c in fn), "fallback branch not exercised"
    assert snap["briefs"]["planned"]["decisions"]["impression_plan"], "plan branch not exercised"
    assert snap["check"]["result"]["bad_option_ids"] == ["opt-a"]
    assert [f["kind"] for f in snap["check"]["result"]["flags"]][-1:] == ["partial"], "classifier branch not exercised"
    assert any(c["outcome"] == "duplicate" for c in fn), "duplicate branch not exercised"
    assert snap["insert"]["result"]["applied"] >= 1 and snap["insert"]["result"]["dup_check"] == "jev"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    assert snap == json.loads(GOLDEN.read_text())
