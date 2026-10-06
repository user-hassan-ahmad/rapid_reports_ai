"""The background review engine NEVER rewrites the report (spec §10.4: automatic edits happen only before render, in
the post-generation check). In live and shadow alike a run stores items only: no report write, no new version. The
post-gen check's applied edits are stored as `pre_applied` items; the engine's own would-be pre-applied edits stay
open one-click items. RR_REVIEW_RAIL=0 hides the rail. Synthetic cases only, no live model calls."""
import uuid

import pytest

from rapid_reports_ai.database.models import Report, ReportReviewRun, ReportVersion
from rapid_reports_ai.review_engine import engine, store
from rapid_reports_ai.review_engine.items import text_hash

import tests.test_review_engine_engine as te

REPORT, DICT = te.DUP_REPORT, te.DUP_DICT
# The report as generated, before the post-gen check inserted the cyst sentence (the check's own telemetry).
PRE = REPORT.replace(" A 14 mm left renal cyst.", "")
QC = {"flags": [], "pre_edit_report": PRE,
      "applied_edits": [{"type": "insertion", "sentence": "A 14 mm left renal cyst."}]}


@pytest.fixture
def versions(db_session):
    ReportVersion.__table__.create(bind=db_session.get_bind(), checkfirst=True)


def _stored(db_session, test_user, monkeypatch):
    from rapid_reports_ai.database.crud import create_report_version
    rid = te._stored_report(db_session, test_user, monkeypatch, REPORT, DICT, qc=QC)
    create_report_version(db_session, report=db_session.get(Report, uuid.UUID(rid)), notes="Initial generation")
    return rid


def _versions(db_session, rid):
    return db_session.query(ReportVersion).filter(ReportVersion.report_id == uuid.UUID(rid)).all()


def _run(db_session, run_id):
    return db_session.get(ReportReviewRun, uuid.UUID(run_id))


def test_flags(monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    assert engine.mode() == "live" and engine.rail_enabled()
    monkeypatch.setenv("RR_REVIEW_RAIL", "0")
    assert engine.mode() == "live" and not engine.rail_enabled()
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    assert engine.mode() == "shadow" and not engine.rail_enabled()
    assert not hasattr(engine, "write_mode") and not hasattr(store, "write_live")


@pytest.mark.parametrize("mode,rail", [("live", None), ("live", "0"), ("shadow", None)])
async def test_engine_never_writes_the_report(monkeypatch, db_session, test_user, versions, mode, rail):
    te._dup_stubs(monkeypatch)
    rid = _stored(db_session, test_user, monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", mode)
    if rail is None:
        monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    else:
        monkeypatch.setenv("RR_REVIEW_RAIL", rail)
    run_id = await engine.run_and_store(rid)
    assert db_session.get(Report, uuid.UUID(rid)).report_content == REPORT and len(_versions(db_session, rid)) == 1
    run = _run(db_session, run_id)
    assert run.mode == mode and "live_write" not in (run.shadow_log or {})
    items = store.list_items(db_session, rid, include_suppressed=True)
    # the post-gen check's insertion: a fact, pre_applied, anchored on the text the user sees
    ins = [i for i in items if i.status == "pre_applied"]
    assert [(i.kind, i.detectors) for i in ins] == [("absent", ["post_check.insert"])]
    a = ins[0].anchor
    assert REPORT[a.start:a.end] == "A 14 mm left renal cyst." and a.text_hash == text_hash(REPORT)
    # the engine's own code-built removal applies nothing: an open one-click action with its edit
    rem = next(i for i in items if i.kind == "removed")
    assert rem.status == "open" and rem.cls == "action" and rem.edit.find == "No ascites."
    assert "pre_applied" not in [e["event"] for e in rem.history]


def test_get_review_mode_and_kill_switch(client, auth_headers, db_session, test_user, monkeypatch):
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               candidate_reports=[{"content": REPORT}])
    db_session.add(r)
    db_session.commit()
    run_id = store.create_run(db_session, str(r.id), "live", "0.1.0", "quick")
    store.finish_run(db_session, run_id, {"accuracy": "done"}, {}, {}, {}, {})
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    body = client.get(f"/api/reports/{r.id}/review", headers=auth_headers).json()
    assert body["mode"] == "live" and body["rail"] is True and body["run"]["mode"] == "live"
    assert "live_write" not in body["run"]
    monkeypatch.setenv("RR_REVIEW_RAIL", "0")
    assert client.get(f"/api/reports/{r.id}/review", headers=auth_headers).json()["rail"] is False
