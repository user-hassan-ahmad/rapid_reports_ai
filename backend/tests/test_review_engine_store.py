"""Review engine storage (spec §10.2) and item events (spec §10.3)."""
import pytest

from rapid_reports_ai.database.models import Report
from rapid_reports_ai.review_engine import store
from rapid_reports_ai.review_engine.items import Edit, ReviewItem, Span


def _report(db, user):
    r = Report(report_type="quick", model_used="m", report_content="FINDINGS:\nx", user_id=user.id,
               candidate_reports=[{"content": "FINDINGS:\nx"}])
    db.add(r)
    db.commit()
    return str(r.id)


def _item(rid, run_id, cls="minor", kind="partial"):
    return ReviewItem(key=f"k-{kind}-{cls}", report_id=rid, run_id=run_id, lane="coverage", detectors=["jev"], kind=kind,
                      cls=cls, anchor=Span(start=0, end=3, text="abc"), edit=Edit(mode="replace", find="a", replace="b"),
                      history=[{"event": "created", "actor": "engine"}], engine_version="0.1.0")


def test_run_and_items_round_trip(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.save_items(db_session, [_item(rid, run_id), _item(rid, run_id, cls="suppress", kind="differs")])
    store.finish_run(db_session, run_id, lanes={"coverage": "done"}, timings_ms={"total": 5}, cost={}, errors={})
    run = store.latest_run(db_session, rid)
    assert run["id"] == run_id and run["lanes"] == {"coverage": "done"} and run["mode"] == "shadow"
    shown = store.list_items(db_session, rid)
    assert [i.kind for i in shown] == ["partial"] and shown[0].edit.find == "a" and shown[0].anchor.text == "abc"
    assert len(store.list_items(db_session, rid, include_suppressed=True)) == 2


def test_evidence_round_trips(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = _item(rid, run_id)
    it.evidence = {"check_reason": "uncertain", "pointer": "line d3"}
    store.save_items(db_session, [it])
    assert store.get_item(db_session, rid, it.id).evidence == {"check_reason": "uncertain", "pointer": "line d3"}
    it.evidence = {"check_reason": "number", "pointer": "p"}
    store.update_item(db_session, it)
    assert store.get_item(db_session, rid, it.id).evidence == {"check_reason": "number", "pointer": "p"}
    bare = _item(rid, run_id, kind="absent")
    store.save_items(db_session, [bare])
    assert store.get_item(db_session, rid, bare.id).evidence is None


def test_latest_run_only(db_session, test_user):
    rid = _report(db_session, test_user)
    old = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.save_items(db_session, [_item(rid, old)])
    new = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.save_items(db_session, [_item(rid, new, kind="absent")])
    assert [i.kind for i in store.list_items(db_session, rid)] == ["absent"]


def test_append_event_sets_status_and_history(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = _item(rid, run_id)
    store.save_items(db_session, [it])
    out = store.append_event(db_session, rid, it.id, "apply", text_hash="h1", detail={"x": 1})
    assert out.status == "applied" and out.history[-1]["event"] == "apply" and out.history[-1]["text_hash"] == "h1"
    out = store.append_event(db_session, rid, it.id, "view")
    assert out.status == "applied" and len(out.history) == 3


def test_unknown_command_and_wrong_report(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = _item(rid, run_id)
    store.save_items(db_session, [it])
    with pytest.raises(ValueError):
        store.append_event(db_session, rid, it.id, "explode")
    other = _report(db_session, test_user)
    assert store.append_event(db_session, other, it.id, "apply") is None


def test_update_item(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = _item(rid, run_id)
    store.save_items(db_session, [it])
    it.label, it.cls = "new label", "action"
    store.update_item(db_session, it)
    assert store.get_item(db_session, rid, it.id).label == "new label"


def test_latest_run_prefers_finished(db_session, test_user):
    rid = _report(db_session, test_user)
    done = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.save_items(db_session, [_item(rid, done)])
    store.finish_run(db_session, done, lanes={"coverage": "done"}, timings_ms={"total": 5}, cost={}, errors={})
    store.create_run(db_session, rid, "shadow", "0.1.0", "quick")        # newer, still running
    assert store.latest_run(db_session, rid)["id"] == done
    assert [i.kind for i in store.list_items(db_session, rid)] == ["partial"]
    failed = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.finish_run(db_session, failed, {}, {}, {}, {"engine": "RuntimeError: x"})   # a failed run is finished too
    assert store.latest_run(db_session, rid)["id"] == failed


def test_latest_run_falls_back_to_unfinished(db_session, test_user):
    rid = _report(db_session, test_user)
    run = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    assert store.latest_run(db_session, rid)["id"] == run
