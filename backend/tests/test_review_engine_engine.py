"""Engine orchestration (spec §4, §9, §10.4): align → lanes + negatives → merge → adjudicate → verify → sequenced
pre-apply; flags; failure isolation; Gate D shadow log. Synthetic cases only, no live model calls."""
import asyncio

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.database.models import Report
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, negatives, store
from rapid_reports_ai.review_engine.items import text_hash

from tests.review_engine_fakes import inp, jev, model

REPORT = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst with a thin septation"
J = adj.Judgement(cls="minor", kind="partial", label="Septation missing", reason="r", edit_mode="replace",
                  edit_find="A 14 mm left renal cyst.", edit_replace="A 14 mm left renal cyst with a thin septation.",
                  edit_section="FINDINGS", probe="The FINDINGS section describes the renal cyst's internal structure.")
# Grounded wording: the additions guard refuses content words grounded nowhere, and the option's own sentence is
# not a grounding source (see the report: a brief option naming a new modality loses its one-click edit).
OPT = [{"id": "o1", "kind": "recommendation", "section": "IMPRESSION", "sentence": "Renal cyst follow-up imaging is suggested.",
        "reason": ""}]
ABSENT = adj.Judgement(cls="action", kind="absent", label="Cyst missing", reason="r", edit_mode="insert",
                       edit_after="The liver is normal.", edit_replace="There is also a 14 mm left renal cyst noted.",
                       edit_section="FINDINGS", probe="The FINDINGS section reports the renal cyst.")


def labels(lines):
    """A negatives-classifier stand-in returning fixed label lines."""
    class R:
        pass

    async def fake(**kw):
        r = R()
        r.output = negatives.Labels(labels=lines(kw) if callable(lines) else lines)
        return r
    return fake


def _all_default(kw):
    n = kw["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1].count("\n") + 1
    return [f"{i} | default | - | no" for i in range(1, n + 1)]


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"i0": {"choice": "partial", "probabilities": {"partial": 0.8, "stated": 0.2}},
                                         "addressed": {"noul": 0.9}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(J))
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(_all_default))


def test_flags(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    monkeypatch.delenv("RR_REVIEW_LANES", raising=False)
    assert engine.mode() == "off" and engine.lanes_enabled() == ["coverage", "accuracy", "additions"]
    monkeypatch.setenv("RR_REVIEW_ENGINE", "Shadow")
    assert engine.mode() == "shadow" and not engine.rail_enabled()
    monkeypatch.setenv("RR_REVIEW_ENGINE", "bogus")
    assert engine.mode() == "off"
    monkeypatch.setenv("RR_REVIEW_LANES", "coverage, additions,nope")
    assert engine.lanes_enabled() == ["coverage", "additions"]
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.setenv("RR_REVIEW_RAIL", "0")
    assert not engine.rail_enabled()


async def test_run_review_end_to_end():
    res = await engine.run_review(inp(REPORT, DICT, options=OPT), run_id="00000000-0000-0000-0000-0000000000aa")
    kinds = {(i.lane, i.kind, i.cls) for i in res.items}
    assert ("coverage", "partial", "minor") in kinds and ("additions", "option", "minor") in kinds
    cov = next(i for i in res.items if i.lane == "coverage")
    assert cov.edit and cov.verified["code"] and cov.source_line == DICT[2:] and cov.engine_version == engine.ENGINE_VERSION
    assert cov.status == "open"                       # a partial is never pre-applied
    opt = next(i for i in res.items if i.lane == "additions")
    assert opt.detectors == ["brief.option"] and opt.edit.mode == "insert" and opt.probe.startswith(rc.Q_CONVEYS)
    assert res.run["lanes"] == {"coverage": "done", "accuracy": "done", "additions": "done"}
    assert "total" in res.run["timings_ms"]
    # negatives items are appended directly (never adjudicated): "The liver is normal." → assumed normal
    neg = [i for i in res.items if i.detectors == [negatives.DETECTOR]]
    assert [i.kind for i in neg] == ["assumed_normal"] and res.run["negatives"]["candidates"] == 1
    assert res.report == REPORT and res.run["pre_apply"] == []


async def test_keys_use_original_kind(monkeypatch):
    monkeypatch.setattr(adj, "_run_agent_with_model", model(J.model_copy(update={"kind": "differs"})))
    res = await engine.run_review(inp(REPORT, DICT), run_id="00000000-0000-0000-0000-0000000000a1")
    cov = next(i for i in res.items if i.lane == "coverage")
    assert cov.kind == "differs"
    from rapid_reports_ai.review_engine.items import item_key
    assert cov.key == item_key("coverage", "partial", cov.anchor.text)


async def test_lane_failure_is_isolated(monkeypatch):
    class Slow:
        name = "coverage"

        async def candidates(self, inp_, ctx):
            await asyncio.sleep(1)
            return []
    monkeypatch.setitem(engine.LANES, "coverage", Slow())
    monkeypatch.setattr(engine, "LANE_TIMEOUT_S", 0.01)
    res = await engine.run_review(inp(REPORT, DICT), run_id="00000000-0000-0000-0000-0000000000ab")
    assert res.run["lanes"]["coverage"] == "failed" and res.run["lanes"]["accuracy"] == "done"
    assert "coverage" in res.run["errors"]


async def test_negatives_failure_is_isolated(monkeypatch):
    async def boom(inp_, run_id, types=None):
        raise RuntimeError("down")
    monkeypatch.setattr(negatives, "classify_negatives", boom)
    res = await engine.run_review(inp(REPORT, DICT), run_id="00000000-0000-0000-0000-0000000000a2")
    assert "negatives" in res.run["errors"] and any(i.lane == "coverage" for i in res.items)


async def test_adjudicator_failure_becomes_minor_no_fix(monkeypatch):
    async def bad(**kw):
        raise ValueError("schema")
    monkeypatch.setattr(adj, "_run_agent_with_model", bad)
    res = await engine.run_review(inp(REPORT, DICT), run_id="00000000-0000-0000-0000-0000000000ac")
    cov = next(i for i in res.items if i.lane == "coverage")
    assert cov.cls == "minor" and cov.edit is None and "schema" in cov.reason and cov.status == "open"


# ── pre-apply (corrections 9, 10, 12; spec §9) ──────────────────────────────

ABS_REPORT = "FINDINGS:\nThe liver is normal. No ascites.\nIMPRESSION:\nNo acute abnormality."
ABS_DICT = "- 14 mm left renal cyst\n- Ascites present"


def _absent_jev(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"i0": {"choice": "absent", "probabilities": {"absent": 0.9, "stated": 0.1}},
                                         "addressed": {"noul": 0.9}}))


async def test_absent_is_pre_applied_with_code_built_insert(monkeypatch):
    _absent_jev(monkeypatch)
    monkeypatch.setattr(adj, "_run_agent_with_model", model(ABSENT))
    res = await engine.run_review(inp(ABS_REPORT, ABS_DICT), run_id="00000000-0000-0000-0000-0000000000b1")
    cov = next(i for i in res.items if i.lane == "coverage" and i.kind == "absent")
    assert cov.status == "pre_applied" and cov.cls == "action"
    # the adjudicator's own wording is never pre-applied: code tidies the dictated line only
    assert cov.edit.replace == "14 mm left renal cyst." and cov.edit.after == "No ascites."
    assert cov.verified["preapply_failures"] == []
    assert "No ascites. 14 mm left renal cyst." in res.report
    assert [e["item_id"] for e in res.run["pre_apply"] if e["applied"]] == [cov.id]


async def test_unconfirmed_fix_is_not_pre_applied(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"i0": {"choice": "absent", "probabilities": {"absent": 0.9, "stated": 0.1}},
                                         "addressed": {"noul": 0.7}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(ABSENT))
    res = await engine.run_review(inp(ABS_REPORT, ABS_DICT), run_id="00000000-0000-0000-0000-0000000000b2")
    cov = next(i for i in res.items if i.lane == "coverage" and i.kind == "absent")
    assert cov.status == "open" and cov.edit is not None and res.report == ABS_REPORT


async def test_adjudicator_minor_is_not_pre_applied(monkeypatch):
    _absent_jev(monkeypatch)
    monkeypatch.setattr(adj, "_run_agent_with_model", model(ABSENT.model_copy(update={"cls": "minor"})))
    res = await engine.run_review(inp(ABS_REPORT, ABS_DICT), run_id="00000000-0000-0000-0000-0000000000b3")
    cov = next(i for i in res.items if i.lane == "coverage" and i.kind == "absent")
    assert cov.status == "open"
    assert cov.edit.replace == ABSENT.edit_replace       # one-click: the adjudicator's fix, not code's


async def test_negatives_removal_first_then_stale_insert_falls_back_to_open(monkeypatch):
    """Negatives removes "No ascites." first; the coverage insert anchored after it no longer applies → stays open
    (the finding is still absent) but loses its edit: never a one-click action that cannot apply."""
    _absent_jev(monkeypatch)
    monkeypatch.setattr(adj, "_run_agent_with_model", model(ABSENT))

    def lab(kw):
        lines = kw["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1].splitlines()
        return [f"{i} | {'contradicted | Ascites present' if 'ascites' in l else 'default | -'} | no"
                for i, l in enumerate(lines, 1)]
    monkeypatch.setattr(negatives, "_run_agent_with_model", labels(lab))
    res = await engine.run_review(inp(ABS_REPORT, ABS_DICT), run_id="00000000-0000-0000-0000-0000000000b4")
    removed = next(i for i in res.items if i.kind == "removed")
    assert removed.status == "pre_applied"
    cov = next(i for i in res.items if i.lane == "coverage" and i.kind == "absent")
    assert cov.status == "open" and cov.edit is None and cov.history[-1]["event"] == "overtaken"
    entry = next(e for e in res.run["pre_apply"] if e["item_id"] == cov.id)
    assert entry["applied"] is False and entry["failed"] and entry["overtaken"] and entry["edit"]
    assert "No ascites" not in res.report and "renal cyst" not in res.report
    assert res.run["pre_apply"][0]["source"] == "negatives"


async def test_gate_d_log_records_option_a_and_b(monkeypatch):
    pre = REPORT.replace(" A 14 mm left renal cyst.", "")
    qc = {"flags": [{"kind": "omission", "text": "14 mm left renal cyst with a thin septation", "score": 0.1}],
          "kept_dictated_negative": []}
    monkeypatch.setattr(adj, "_run_agent_with_model", model(ABSENT))
    log = await engine.gate_d_log(inp(REPORT, DICT, quality_check=qc, pre_edit=pre))
    assert log["edits"][0]["type"] == "insertion" and log["edits"][0]["option_a_pre_apply"] is True
    assert log["edits"][0]["option_b"] == "one-click action"
    assert log["edits"][0]["code_edit"]["replace"] == "14 mm left renal cyst with a thin septation."


async def test_run_and_store(monkeypatch, db_session, test_user):
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               input_data={"variables": {"FINDINGS": DICT, "SCAN_TYPE": "CT abdomen", "CLINICAL_HISTORY": ""}},
               candidate_reports=[{"content": REPORT, "sections": ["FINDINGS", "IMPRESSION"], "options": OPT,
                                   "quality_check": {"flags": []}}])
    db_session.add(r)
    db_session.commit()

    async def same_thread(fn, *a, **k):
        return fn(*a, **k)
    monkeypatch.setattr(engine, "_with_session", lambda fn, *a, **k: fn(db_session, *a, **k))
    monkeypatch.setattr(engine.asyncio, "to_thread", same_thread)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    run_id = await engine.run_and_store(str(r.id))
    assert store.latest_run(db_session, str(r.id))["id"] == run_id
    assert {i.lane for i in store.list_items(db_session, str(r.id))} >= {"coverage", "additions"}
    assert db_session.get(Report, r.id).report_content == REPORT     # shadow never touches the report


def test_schedule_review_is_noop_when_off(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    assert engine.schedule_review("00000000-0000-0000-0000-000000000001") is None


def test_input_from_parts():
    i = engine.input_from_parts("00000000-0000-0000-0000-000000000001", "templated",
                                {"variables": {"FINDINGS": "- a", "CLINICAL_HISTORY": "h"}, "extracted_scan_type": "MRI knee"},
                                {"content": "FINDINGS:\nA.", "sections": ["FINDINGS"],
                                 "quality_check": {"pre_edit_report": "FINDINGS:\nB."}},
                                {"guidelines": [{"finding": "x"}]})
    assert i.pathway == "templated" and i.scan_type == "MRI knee" and i.clinical_history == "h"
    assert i.synthesis == {"guidelines": [{"finding": "x"}]} and i.pre_edit_report == "FINDINGS:\nB."
    assert engine.input_from_parts("x", "quick", {}, {"content": "", "error": "boom"}, None) is None


# ── integration review fixes (I1, I2, I5, I6, I7, M3) ───────────────────────

DUP_REPORT = "FINDINGS:\nThe liver is normal. No ascites. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
DUP_DICT = "- 14 mm left renal cyst\n- Small volume ascites"


def _ascites_contradicted(kw):
    lines = kw["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1].splitlines()
    return [f"{i} | {'contradicted | ascites' if 'ascites' in l.lower() else 'default | -'} | no"
            for i, l in enumerate(lines, 1)]


def _dup_stubs(monkeypatch, negatives_ok=True):
    """The accuracy lane (jev.contradiction, negative) and the negatives classifier both flag "No ascites."."""
    from rapid_reports_ai.report_review import checked_clauses_in_context
    cls = list(checked_clauses_in_context(DUP_REPORT, None))
    k = cls.index(next(c for c in cls if "ascites" in c.lower()))
    monkeypatch.setattr(rc, "_jev", jev({f"c{k}": {"noul": 0.95}, f"r{k}": {"noul": 0.95}, f"d{k}": {"noul": 0.05},
                                         "addressed": {"noul": 0.95}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="action", kind="contradicted", label="Ascites negative contradicts", reason="r", edit_mode="none",
        probe="The FINDINGS section does not deny ascites.")))
    if negatives_ok:
        monkeypatch.setattr(negatives, "_run_agent_with_model", labels(_ascites_contradicted))
    else:
        async def boom(**kw):
            raise RuntimeError("qwen down")
        monkeypatch.setattr(negatives, "_run_agent_with_model", boom)


def _ascites_items(items):
    return [i for i in items if "ascites" in ((i.anchor.text if i.anchor else "") + str(i.evidence)).lower()]


async def test_negative_flagged_by_both_yields_one_item(monkeypatch):
    _dup_stubs(monkeypatch)
    res = await engine.run_review(inp(DUP_REPORT, DUP_DICT), run_id="00000000-0000-0000-0000-0000000000c1")
    asc = _ascites_items(res.items)
    assert [(i.detectors, i.kind, i.status) for i in asc] == [([negatives.DETECTOR], "removed", "pre_applied")]
    assert not any(e["source"] == "lanes" for e in res.run["pre_apply"])
    assert "No ascites" not in res.report


async def test_lane_negative_kept_when_negatives_failed(monkeypatch):
    _dup_stubs(monkeypatch, negatives_ok=False)
    res = await engine.run_review(inp(DUP_REPORT, DUP_DICT), run_id="00000000-0000-0000-0000-0000000000c2")
    asc = [i for i in _ascites_items(res.items) if "jev.contradiction" in i.detectors]
    assert len(asc) == 1 and asc[0].kind == "contradicted" and "negatives" in res.run["errors"]


def test_lane_edit_lost_to_earlier_removal_is_stale():
    i_ = inp(DUP_REPORT, DUP_DICT)
    from rapid_reports_ai.review_engine.items import Edit, ReviewItem
    it = ReviewItem(key="k", report_id=i_.report_id, run_id="00000000-0000-0000-0000-0000000000c3", lane="accuracy",
                    kind="contradicted", cls="action", edit=Edit(mode="remove", find="No ascites."),
                    verified={"code": True, "failed": [], "unconfirmed": False})
    plan = engine._Plan(item_id=it.id, kind="contradicted", code_built=True)
    after = DUP_REPORT.replace(" No ascites.", "")
    doc, log = engine.finalise(i_, [it], {it.id: plan}, {"report": after}, [])
    assert doc == after and it.status == "stale" and it.edit is None
    assert log[0]["applied"] is False and log[0]["failed"]


async def test_negatives_items_anchor_on_original_report(monkeypatch):
    _dup_stubs(monkeypatch)
    res = await engine.run_review(inp(DUP_REPORT, DUP_DICT), run_id="00000000-0000-0000-0000-0000000000c4")
    h = text_hash(DUP_REPORT)
    for i in res.items:
        if i.anchor is not None:
            assert i.anchor.text_hash == h and DUP_REPORT[i.anchor.start:i.anchor.end] == i.anchor.text
    rem = next(i for i in res.items if i.kind == "removed")
    assert rem.anchor.text == "No ascites." and rem.evidence["removed_text"] == "No ascites."


async def test_negatives_items_carry_history_version_and_verified_shape(monkeypatch):
    _dup_stubs(monkeypatch)
    res = await engine.run_review(inp(DUP_REPORT, DUP_DICT), run_id="00000000-0000-0000-0000-0000000000c5")
    neg = [i for i in res.items if i.detectors == [negatives.DETECTOR]]
    assert neg
    for i in neg:
        assert i.engine_version == engine.ENGINE_VERSION
        assert i.history[0]["event"] == "created" and i.history[0]["text_hash"] == text_hash(DUP_REPORT)
    rem = next(i for i in neg if i.kind == "removed")
    assert [e["event"] for e in rem.history] == ["created", "pre_applied"] and rem.history[1]["text_hash"]
    assert set(rem.verified) >= {"code", "failed", "addressed", "contra", "unconfirmed", "preapply_failures"}


def _stored_report(db_session, test_user, monkeypatch, report=REPORT, dictation=DICT, qc=None):
    r = Report(report_type="quick", model_used="m", report_content=report, user_id=test_user.id,
               input_data={"variables": {"FINDINGS": dictation, "SCAN_TYPE": "CT abdomen", "CLINICAL_HISTORY": ""}},
               candidate_reports=[{"content": report, "sections": ["FINDINGS", "IMPRESSION"],
                                   "quality_check": qc or {"flags": []}}])
    db_session.add(r)
    db_session.commit()

    async def same_thread(fn, *a, **k):
        return fn(*a, **k)
    monkeypatch.setattr(engine, "_with_session", lambda fn, *a, **k: fn(db_session, *a, **k))
    monkeypatch.setattr(engine.asyncio, "to_thread", same_thread)
    return str(r.id)


def _run_row(db_session, run_id):
    from rapid_reports_ai.database.models import ReportReviewRun
    import uuid as _uuid
    return db_session.get(ReportReviewRun, _uuid.UUID(run_id))


async def test_gate_d_failure_keeps_items(monkeypatch, db_session, test_user):
    rid = _stored_report(db_session, test_user, monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")

    async def broken(inp_):
        raise RuntimeError("gate d broke")
    monkeypatch.setattr(engine, "gate_d_log", broken)
    run_id = await engine.run_and_store(rid)
    assert store.list_items(db_session, rid)
    assert "gate d broke" in _run_row(db_session, run_id).shadow_log["gate_d"]["error"]


async def test_gate_d_timeout_keeps_items(monkeypatch, db_session, test_user):
    rid = _stored_report(db_session, test_user, monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(engine, "GATE_D_TIMEOUT_S", 0.01)

    async def slow(inp_):
        await asyncio.sleep(1)
    monkeypatch.setattr(engine, "gate_d_log", slow)
    run_id = await engine.run_and_store(rid)
    assert store.list_items(db_session, rid)
    assert "Timeout" in _run_row(db_session, run_id).shadow_log["gate_d"]["error"]


async def test_shadow_persists_no_pre_applied_and_logs_texts(monkeypatch, db_session, test_user):
    _dup_stubs(monkeypatch)
    rid = _stored_report(db_session, test_user, monkeypatch, DUP_REPORT, DUP_DICT)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    run_id = await engine.run_and_store(rid)
    items = store.list_items(db_session, rid, include_suppressed=True)
    assert items and not any(i.status == "pre_applied" for i in items)
    rem = next(i for i in items if i.kind == "removed")
    assert rem.status == "open" and rem.evidence["would_pre_apply"] is True and rem.edit.find == "No ascites."
    assert "pre_applied" not in [e["event"] for e in rem.history] and rem.history[-1]["event"] == "would_pre_apply"
    assert all(i.anchor.text_hash == text_hash(DUP_REPORT) for i in items if i.anchor)
    log = _run_row(db_session, run_id).shadow_log
    assert "No ascites" not in log["final_report"] and "No ascites" not in log["negatives_report"]
    assert log["negatives_post_removal_anchors"][rem.id] == [31, 31]
    assert db_session.get(Report, _uuid(rid)).report_content == DUP_REPORT


def _uuid(x):
    import uuid as _u
    return _u.UUID(x)


async def test_runs_limited_by_concurrency(monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.delenv("RR_REVIEW_CONCURRENCY", raising=False)
    monkeypatch.setattr(engine, "_SEM", None)
    active, peak = 0, 0

    async def fake_load(report_id, text=None):
        return inp(REPORT, DICT)

    async def fake_run(inp_, run_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return engine.ReviewResult(run={"lanes": {}, "timings_ms": {}, "cost": {}, "errors": {}, "pre_apply": [],
                                        "negatives": None}, items=[], report=REPORT)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(engine, "load_input", fake_load)
    monkeypatch.setattr(engine, "run_review", fake_run)
    monkeypatch.setattr(engine, "gate_d_log", noop)

    async def same_thread(fn, *a, **k):
        return "00000000-0000-0000-0000-0000000000d1" if fn is engine._with_session and a[0] is store.create_run else None
    monkeypatch.setattr(engine.asyncio, "to_thread", same_thread)
    await asyncio.gather(*(engine.run_and_store(f"00000000-0000-0000-0000-00000000000{k}") for k in range(3)))
    assert peak == 1
    monkeypatch.setenv("RR_REVIEW_CONCURRENCY", "3")
    monkeypatch.setattr(engine, "_SEM", None)
    peak = 0
    await asyncio.gather(*(engine.run_and_store(f"00000000-0000-0000-0000-00000000000{k}") for k in range(3)))
    assert peak == 3


async def test_schedule_review_sampling(monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    seen = []

    async def fake(report_id, text=None):
        seen.append(report_id)
    monkeypatch.setattr(engine, "run_and_store", fake)
    monkeypatch.setenv("RR_REVIEW_SAMPLE", "0")
    assert engine.schedule_review("00000000-0000-0000-0000-000000000001") is None
    monkeypatch.setenv("RR_REVIEW_SAMPLE", "1.0")
    t = engine.schedule_review("00000000-0000-0000-0000-000000000002")
    await t
    monkeypatch.setenv("RR_REVIEW_SAMPLE", "bogus")          # unreadable → default 1.0
    await engine.schedule_review("00000000-0000-0000-0000-000000000003")
    assert seen == ["00000000-0000-0000-0000-000000000002", "00000000-0000-0000-0000-000000000003"]
