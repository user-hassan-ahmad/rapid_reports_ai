"""Byte-identity pins for the quick path while its engine moves to shared modules
(spec 2026-09-30-template-pipeline-mirror-design §1). Pins outputs AND model inputs (every
stubbed call's arguments, the plan's real prompt, and a hash of each prompt constant that moves).
Regenerate only on an intended change:
UPDATE_GOLDEN=1 uv run pytest tests/test_golden_quick_pipeline.py"""
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

BRIEF_PROMPTS = ("Q_AFFECTED", "Q_PRESENT", "Q_REC_UNMET", "Q_STYLE_MATCH", "Q_FINDING",
                 "QWEN_SYS", "PLAN_SYS", "FALLBACK_SYS")
QUALITY_PROMPTS = ("Q_CONTRA", "Q_OMIT", "Q_RESTATED", "REPAIR_SYS", "INSERT_SYS", "INSERT_ONLY_SYS")

_REAL_PLAN = qb._plan   # captured before any test patches it


def _engine():
    """The module whose _run_agent_with_model _plan calls: the brief today, report_reconcile once
    Task 2 moves the reconcile engine there. The switch lets one golden span the move."""
    try:
        from rapid_reports_ai import report_reconcile as rc
        return rc
    except ImportError:
        return qb


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _recorder(log: dict, name: str, result):
    """An async stub that logs its arguments under `name` and returns `result(*args)`."""
    async def fn(*args):
        log.setdefault(name, []).append(list(args))
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
    jev_c = {"n0": {"noul": 0.1}, "f0": {"noul": 0.95}, "f1": {"noul": 0.1}}
    qwen_c = qb.QwenDecisions(negatives=[qb.NegativeDecision(index=i, action="keep") for i in range(6)],
                              affected_normals=[], applicable_measurements=[])
    fallback_c = qb.FallbackNegatives(items=[
        qb.FallbackItem(index=0, covered=True),
        qb.FallbackItem(index=1, covered=False, negatives=["No adrenal haemorrhage.", "No local invasion"])])
    return {
        "no_plan": await _brief(monkeypatch, SHEET, FINDINGS, JEV, QWEN),
        "planned": await _brief(monkeypatch, SHEET, FINDINGS, {**JEV, "r1": {"noul": 0.1}}, QWEN, planned),
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
    return {"system_prompt": seen["system_prompt"], "user_prompt": seen["user_prompt"],
            "model_settings": seen["model_settings"], "model_name": seen["model_name"],
            "output_type": seen["output_type"].__name__, "output": out.model_dump()}


async def _check(monkeypatch) -> dict:
    # c1/r1: a contradiction whose denied finding is dictated (flagged). c2/r2: a contradiction
    # whose denied finding is not dictated (suppressed by the restated gate). o0: a bad option.
    scores = {"c1": 0.9, "r1": 0.9, "c2": 0.9, "r2": 0.1, "o0": 0.9}
    log: dict = {}
    # check() calls _jev through the brief module today and through report_review (rc) after Task 3.
    target = qq.rc if hasattr(qq, "rc") else qq.qb
    monkeypatch.setattr(target, "_jev", _recorder(
        log, "_jev", lambda state, qs: {k: {"noul": scores.get(k, 0.1)} for k in qs}))
    options = [{"id": "opt-a", "sentence": "No hydrocephalus."}, {"id": "opt-b"}]
    res = await qq.check(REPORT, FINDINGS, "CT head", options)
    return {"result": res.model_dump(), "calls": log}


async def _snapshot(monkeypatch) -> dict:
    fnd, imp = qq.report_sections(REPORT)
    return {"prompt_hashes": {**{f"qb.{n}": _sha(getattr(qb, n)) for n in BRIEF_PROMPTS},
                              **{f"qq.{n}": _sha(getattr(qq, n)) for n in QUALITY_PROMPTS}},
            "plan_prompt": await _plan_prompt(monkeypatch),
            "briefs": await _briefs(monkeypatch),
            "check": await _check(monkeypatch),
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
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    assert snap == json.loads(GOLDEN.read_text())
