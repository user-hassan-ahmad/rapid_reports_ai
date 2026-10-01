"""template_case_sheets: Phase 1 output persisted per (user, template, sheet hash, history hash)."""
from __future__ import annotations

from rapid_reports_ai.database import crud


def test_case_sheet_roundtrip(db_session, test_user, guided_template):
    row = crud.create_case_sheet(db_session, user_id=str(test_user.id), template_id=str(guided_template.id),
                                 sheet_hash="s1", history_hash="h1", clinical_history="?perforation")
    assert row.status == "running"
    crud.finish_case_sheet(db_session, row.id, master_sheet="## Case Deliberation\n…", case_result={"units": []},
                           model="q", latency_ms=12000, prompt_version="p1")
    got = crud.get_case_sheet(db_session, str(test_user.id), str(guided_template.id), "s1", "h1")
    assert got.status == "ready" and got.master_sheet.startswith("## Case Deliberation")
    assert got.case_result == {"units": []} and got.latency_ms == 12000 and got.model == "q"


def test_failed_case_sheet_is_not_returned_as_ready(db_session, test_user, guided_template):
    row = crud.create_case_sheet(db_session, user_id=str(test_user.id), template_id=str(guided_template.id),
                                 sheet_hash="s1", history_hash="h2", clinical_history="x")
    crud.fail_case_sheet(db_session, row.id, error="boom")
    got = crud.get_case_sheet(db_session, str(test_user.id), str(guided_template.id), "s1", "h2")
    assert got.status == "failed" and got.error == "boom"


def test_create_resets_a_failed_row_to_running(db_session, test_user, guided_template):
    uid, tid = str(test_user.id), str(guided_template.id)
    row = crud.create_case_sheet(db_session, user_id=uid, template_id=tid, sheet_hash="s1", history_hash="h3",
                                 clinical_history="x")
    crud.fail_case_sheet(db_session, row.id, error="boom")
    again = crud.create_case_sheet(db_session, user_id=uid, template_id=tid, sheet_hash="s1", history_hash="h3",
                                   clinical_history="x")
    assert again.id == row.id and again.status == "running" and again.error is None


def test_get_missing_case_sheet_is_none(db_session, test_user, guided_template):
    assert crud.get_case_sheet(db_session, str(test_user.id), str(guided_template.id), "s9", "h9") is None


def test_concurrent_insert_of_the_same_case_returns_the_winning_row(db_session, test_user, guided_template,
                                                                    monkeypatch):
    """Another process inserted the same key between our lookup and our insert: the unique index refuses
    ours and the row that won is returned."""
    uid, tid = str(test_user.id), str(guided_template.id)
    winner = crud.create_case_sheet(db_session, user_id=uid, template_id=tid, sheet_hash="s1", history_hash="hr",
                                    clinical_history="x")
    real, first = crud.get_case_sheet, [True]

    def miss_once(*a, **k):
        if first[0]:
            first[0] = False
            return None
        return real(*a, **k)
    monkeypatch.setattr(crud, "get_case_sheet", miss_once)
    got = crud.create_case_sheet(db_session, user_id=uid, template_id=tid, sheet_hash="s1", history_hash="hr",
                                 clinical_history="x")
    assert got.id == winner.id and got.status == "running"
