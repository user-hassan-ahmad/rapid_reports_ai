# tests/test_quick_report_finalise_review.py
"""Finalise records the review items the radiologist kept (plan Task C5): `review_applied_item_ids` is optional,
stored on the latest review run under `shadow_log["finalise"]` (no migration), and `applied_option_ids` keeps
working alongside it."""
import uuid

import pytest

from rapid_reports_ai import quick_report_api
from rapid_reports_ai.database.models import Report, ReportReviewRun
from rapid_reports_ai.review_engine import store

REPORT = "FINDINGS:\nA 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."


@pytest.fixture(autouse=True)
def _no_versions(monkeypatch):
    """The test schema has no report_versions table: record the selection on the report only."""
    def fake(db, report_id, selected_model, final_report_content, final_edit_diff):
        r = db.get(Report, uuid.UUID(report_id))
        r.final_report_content, r.final_edit_diff = final_report_content, final_edit_diff
        db.commit()
        return r
    monkeypatch.setattr(quick_report_api, "set_quick_report_selection", fake)


def _seed(db_session, test_user, with_run=True):
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               input_data={"variables": {"FINDINGS": "- cyst"}},
               candidate_reports=[{"content": REPORT, "sections": ["FINDINGS", "IMPRESSION"], "options": []}])
    db_session.add(r)
    db_session.commit()
    rid = str(r.id)
    run_id = None
    if with_run:
        run_id = store.create_run(db_session, rid, "live", "0.1.0", "quick")
        store.finish_run(db_session, run_id, {"coverage": "done"}, {}, {}, {}, {"gate_d": {"a": 1}})
    return rid, run_id


def _run(db_session, run_id):
    db_session.expire_all()
    return db_session.get(ReportReviewRun, uuid.UUID(run_id))


def test_finalise_stores_review_applied_item_ids_on_latest_run(client, auth_headers, db_session, test_user):
    rid, run_id = _seed(db_session, test_user)
    res = client.patch(f"/api/quick-report/reports/{rid}/finalise", headers=auth_headers,
                       json={"final_report_content": REPORT + " Edited.", "applied_option_ids": ["opt0"],
                             "review_applied_item_ids": ["i1", "i2"]})
    assert res.json()["success"] is True
    log = _run(db_session, run_id).shadow_log
    assert log["finalise"]["review_applied_item_ids"] == ["i1", "i2"]
    assert log["gate_d"] == {"a": 1}  # other keys kept
    db_session.expire_all()
    report = db_session.get(Report, uuid.UUID(rid))
    assert report.candidate_reports[0]["options_applied"] == ["opt0"]


def test_finalise_without_field_leaves_run_untouched(client, auth_headers, db_session, test_user):
    rid, run_id = _seed(db_session, test_user)
    res = client.patch(f"/api/quick-report/reports/{rid}/finalise", headers=auth_headers,
                       json={"final_report_content": REPORT})
    assert res.json()["success"] is True
    assert "finalise" not in (_run(db_session, run_id).shadow_log or {})


def test_finalise_with_ids_but_no_run_still_succeeds(client, auth_headers, db_session, test_user):
    rid, _ = _seed(db_session, test_user, with_run=False)
    res = client.patch(f"/api/quick-report/reports/{rid}/finalise", headers=auth_headers,
                       json={"final_report_content": REPORT, "review_applied_item_ids": ["i1"]})
    assert res.json()["success"] is True


def test_finalise_caps_review_applied_item_ids(client, auth_headers, db_session, test_user):
    """F2 M2: at most 200 review item ids."""
    rid, _ = _seed(db_session, test_user)
    res = client.patch(f"/api/quick-report/reports/{rid}/finalise", headers=auth_headers,
                       json={"final_report_content": REPORT, "review_applied_item_ids": [str(i) for i in range(201)]})
    assert res.status_code == 422
