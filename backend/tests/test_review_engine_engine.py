"""Engine orchestration (spec §4, §9, §10.4): align → lanes + negatives → merge → adjudicate → verify → sequenced
pre-apply; flags; failure isolation; Gate D shadow log. Synthetic cases only, no live model calls."""
import asyncio

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.database.models import Report
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, negatives, store

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
    async def boom(inp_, run_id):
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
    """Negatives removes "No ascites." first; the coverage insert anchored after it no longer applies → open."""
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
    assert cov.status == "open" and cov.edit is not None
    entry = next(e for e in res.run["pre_apply"] if e["item_id"] == cov.id)
    assert entry["applied"] is False and entry["failed"]
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
