from __future__ import annotations

from rapid_reports_ai.scripts.audit_eval import load_cases, score_case

CASE = {"id": "x", "findings": "No pleural effusion. Small left pleural effusion.",
        "issues": [{"kind": "internal_contradiction", "quote": "Small left pleural effusion."}]}


def test_a_flag_overlapping_the_quoted_statement_is_a_catch():
    r = score_case(CASE, [{"start": 21, "end": 49, "kind": "internal_contradiction"}])
    assert r["caught"] == 1 and r["stray"] == 0


def test_a_flag_elsewhere_is_stray_and_the_issue_missed():
    r = score_case(CASE, [{"start": 0, "end": 20, "kind": "internal_contradiction"}])
    assert r["caught"] == 0 and r["stray"] == 1


def test_the_fixture_quotes_are_verbatim_and_clean_cases_exist():
    cases = load_cases()
    assert all(i["quote"] in c["findings"] for c in cases for i in c["issues"])
    assert sum(1 for c in cases if not c["issues"]) >= 10


def test_a_conflict_marked_on_its_other_half_still_counts():
    # both halves are marked in the editor, so either overlapping the planted statement is a catch
    r = score_case(CASE, [{"start": 0, "end": 20, "kind": "internal_contradiction", "related_start": 21, "related_end": 49}])
    assert r["caught"] == 1 and r["stray"] == 0
