"""Live mode (RR_REVIEW_ENGINE=live, rail on): the pre-applied edits are written once to the report as a new current
ReportVersion; the pre-edit text is kept for undo; items persist pre_applied with anchors on the written text; the
RR_REVIEW_RAIL=0 kill switch and a report changed meanwhile leave the report untouched (shadow persistence).
Synthetic cases only, no live model calls."""
import uuid

import pytest

from rapid_reports_ai.database.models import Report, ReportReviewRun, ReportVersion
from rapid_reports_ai.review_engine import engine, live, store
from rapid_reports_ai.review_engine.items import Edit, ReviewItem, Span, text_hash

import tests.test_review_engine_engine as te

REPORT, DICT = te.DUP_REPORT, te.DUP_DICT


@pytest.fixture
def versions(db_session):
    ReportVersion.__table__.create(bind=db_session.get_bind(), checkfirst=True)


def _stored(db_session, test_user, monkeypatch):
    from rapid_reports_ai.database.crud import create_report_version
    rid = te._stored_report(db_session, test_user, monkeypatch, REPORT, DICT)
    create_report_version(db_session, report=db_session.get(Report, uuid.UUID(rid)), notes="Initial generation")
    return rid


def _versions(db_session, rid):
    return (db_session.query(ReportVersion).filter(ReportVersion.report_id == uuid.UUID(rid))
            .order_by(ReportVersion.version_number).all())


def _run(db_session, run_id):
    return db_session.get(ReportReviewRun, uuid.UUID(run_id))


def test_flags(monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    assert engine.mode() == "live" and engine.rail_enabled() and engine.write_mode() == "live"
    monkeypatch.setenv("RR_REVIEW_RAIL", "0")
    assert engine.mode() == "live" and not engine.rail_enabled() and engine.write_mode() == "shadow"
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    assert engine.write_mode() == "shadow" and not engine.rail_enabled()
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    assert engine.write_mode() == "off"


async def test_shadow_unchanged(monkeypatch, db_session, test_user, versions):
    te._dup_stubs(monkeypatch)
    rid = _stored(db_session, test_user, monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    run_id = await engine.run_and_store(rid)
    assert db_session.get(Report, uuid.UUID(rid)).report_content == REPORT and len(_versions(db_session, rid)) == 1
    assert _run(db_session, run_id).mode == "shadow" and "live_write" not in _run(db_session, run_id).shadow_log
    assert not any(i.status == "pre_applied" for i in store.list_items(db_session, rid, include_suppressed=True))


async def test_live_writes_once_with_undo_and_rebased_anchors(monkeypatch, db_session, test_user, versions):
    te._dup_stubs(monkeypatch)
    rid = _stored(db_session, test_user, monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    run_id = await engine.run_and_store(rid)
    final = db_session.get(Report, uuid.UUID(rid)).report_content
    assert "No ascites" not in final and final != REPORT
    v = _versions(db_session, rid)
    assert [x.version_number for x in v] == [1, 2] and v[1].is_current and not v[0].is_current
    assert v[0].report_content == REPORT and v[1].report_content == final        # pre-edit text kept (undo)
    assert v[1].notes == store.LIVE_NOTES and v[1].actions_applied[0]["kind"] == "removed"
    lw = _run(db_session, run_id).shadow_log["live_write"]
    assert lw["applied"] and lw["pre_edit_report"] == REPORT and lw["previous_version_id"] == str(v[0].id)
    assert lw["version_id"] == str(v[1].id) and lw["after_hash"] == text_hash(final)
    assert _run(db_session, run_id).mode == "live"
    items = store.list_items(db_session, rid, include_suppressed=True)
    rem = next(i for i in items if i.kind == "removed")
    assert rem.status == "pre_applied" and "would_pre_apply" not in (rem.evidence or {})
    assert rem.anchor.start == rem.anchor.end and rem.anchor.text_hash == text_hash(final)
    assert rem.evidence["original_anchor"]["text"] == "No ascites."
    u = rem.evidence["undo"]
    assert final[:u["final_span"][0]] + u["original_text"] + final[u["final_span"][1]:] == REPORT
    for i in items:
        if i.anchor is not None and i.anchor.end > i.anchor.start:
            assert i.anchor.text_hash == text_hash(final) and final[i.anchor.start:i.anchor.end] == i.anchor.text
    # A second run (e.g. a rerun on the generation record) reviews text the report no longer holds: no write.
    run2 = await engine.run_and_store(rid)
    assert len(_versions(db_session, rid)) == 2 and db_session.get(Report, uuid.UUID(rid)).report_content == final
    assert _run(db_session, run2).shadow_log["live_write"] == {
        "applied": False, "reason": "report_changed", "before_hash": text_hash(REPORT), "after_hash": text_hash(final)}
    assert not any(i.status == "pre_applied" for i in store.list_items(db_session, rid, run2, include_suppressed=True))


async def test_kill_switch_leaves_the_report_alone(monkeypatch, db_session, test_user, versions):
    te._dup_stubs(monkeypatch)
    rid = _stored(db_session, test_user, monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.setenv("RR_REVIEW_RAIL", "0")
    run_id = await engine.run_and_store(rid)
    assert db_session.get(Report, uuid.UUID(rid)).report_content == REPORT and len(_versions(db_session, rid)) == 1
    assert _run(db_session, run_id).mode == "shadow"
    items = store.list_items(db_session, rid, include_suppressed=True)
    assert not any(i.status == "pre_applied" for i in items)
    assert next(i for i in items if i.kind == "removed").evidence["would_pre_apply"] is True


async def test_live_never_overwrites_a_user_edit(monkeypatch, db_session, test_user, versions):
    te._dup_stubs(monkeypatch)
    rid = _stored(db_session, test_user, monkeypatch)
    row = db_session.get(Report, uuid.UUID(rid))
    row.report_content = REPORT + "\nEdited by the radiologist."
    db_session.commit()
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    run_id = await engine.run_and_store(rid)
    assert db_session.get(Report, uuid.UUID(rid)).report_content.endswith("Edited by the radiologist.")
    assert _run(db_session, run_id).shadow_log["live_write"]["reason"] == "report_changed"
    assert not any(i.status == "pre_applied" for i in store.list_items(db_session, rid, include_suppressed=True))


def test_get_review_reports_live_and_the_write(client, auth_headers, db_session, test_user, monkeypatch):
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               candidate_reports=[{"content": REPORT}])
    db_session.add(r)
    db_session.commit()
    run_id = store.create_run(db_session, str(r.id), "live", "0.1.0", "quick")
    store.finish_run(db_session, run_id, {"accuracy": "done"}, {}, {}, {},
                     {"live_write": {"applied": True, "version_id": "v", "pre_edit_report": REPORT}})
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.delenv("RR_REVIEW_RAIL", raising=False)
    body = client.get(f"/api/reports/{r.id}/review", headers=auth_headers).json()
    assert body["mode"] == "live" and body["rail"] is True and body["run"]["mode"] == "live"
    assert body["run"]["live_write"] == {"applied": True, "version_id": "v"}       # the pre-edit text stays in the log
    monkeypatch.setenv("RR_REVIEW_RAIL", "0")
    assert client.get(f"/api/reports/{r.id}/review", headers=auth_headers).json()["rail"] is False


def test_rebase_insert_and_unmappable_anchor():
    orig = "FINDINGS:\nNo ascites. The liver is normal.\nIMPRESSION:\nNormal."
    final = "FINDINGS:\nNo ascites. 14 mm left renal cyst. The liver is normal.\nIMPRESSION:\nNormal."
    ins = ReviewItem(key="a", report_id="r", run_id="x", lane="coverage", kind="absent", cls="action",
                     status="pre_applied", edit=Edit(mode="insert", after="No ascites.",
                                                     replace="14 mm left renal cyst."))
    s = orig.index("The liver is normal.")
    moved = ReviewItem(key="b", report_id="r", run_id="x", lane="accuracy", kind="assumed_normal", cls="info",
                       anchor=Span(start=s, end=s + 20, text="The liver is normal."))
    gone = ReviewItem(key="c", report_id="r", run_id="x", lane="accuracy", kind="check", cls="minor",
                      anchor=Span(start=0, end=5, text="XXXXX"))
    live.rebase_items([ins, moved, gone], orig, final)
    assert final[ins.anchor.start:ins.anchor.end] == "14 mm left renal cyst."
    u = ins.evidence["undo"]
    assert final[:u["final_span"][0]] + u["original_text"] + final[u["final_span"][1]:] == orig
    assert final[moved.anchor.start:moved.anchor.end] == "The liver is normal." and moved.anchor.start > s
    assert gone.anchor is None and gone.evidence["original_anchor"]["text"] == "XXXXX"


def test_rebase_undo_carries_context_and_final_text():
    """The frontend never guesses where a pre-applied edit sits: undo carries the written text of the span and 16
    characters each side, so the edit can be re-found by context once the report has changed."""
    orig = "FINDINGS:\nNo ascites. The liver is normal.\nIMPRESSION:\nNormal."
    final = "FINDINGS:\nNo ascites. 14 mm left renal cyst. The liver is normal.\nIMPRESSION:\nNormal."
    ins = ReviewItem(key="a", report_id="r", run_id="x", lane="coverage", kind="absent", cls="action",
                     status="pre_applied", edit=Edit(mode="insert", after="No ascites.",
                                                     replace="14 mm left renal cyst."))
    live.rebase_items([ins], orig, final)
    u = ins.evidence["undo"]
    j1, j2 = u["final_span"]
    assert u["final_text"] == final[j1:j2]
    assert u["left"] == final[max(0, j1 - 16):j1] and len(u["left"]) == 16
    assert u["right"] == final[j2:j2 + 16] and len(u["right"]) == 16
    assert final.count(u["left"] + u["final_text"] + u["right"]) == 1
    # a removal: zero-width in the written text, context still unique
    rem = ReviewItem(key="b", report_id="r", run_id="x", lane="accuracy", kind="removed", cls="action",
                     status="pre_applied", anchor=Span(start=10, end=22, text="No ascites. "),
                     edit=Edit(mode="remove", find="No ascites."))
    live.rebase_items([rem], orig, orig[:10] + orig[22:])
    u = rem.evidence["undo"]
    assert u["final_text"] == "" and u["left"] == "FINDINGS:\n" and u["right"] == "The liver is nor"
