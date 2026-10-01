"""Uniqueness gate: an offered option the generated report already states (or, for impression and
recommendation items, the conclusion already states) is dropped. One Jev pass, fail-open."""
from __future__ import annotations

import pytest

from rapid_reports_ai import report_reconcile as rc

REPORT = ("FINDINGS:\nNo free intraperitoneal gas. Small pelvic free fluid.\n\n"
          "CONCLUSION:\n1. Perforated appendicitis with abscess.\n2. No free intraperitoneal gas.")
IMPRESSION = "1. Perforated appendicitis with abscess.\n2. No free intraperitoneal gas."
OPTS = [{"id": "fn0", "kind": "finding_negative", "sentence": "No free intraperitoneal gas."},
        {"id": "fn1", "kind": "finding_negative", "sentence": "No psoas collection."},
        {"id": "opt0", "kind": "impression", "sentence": "No free intraperitoneal gas."},
        {"id": "opt1", "kind": "impression", "sentence": "Small pelvic free fluid."},
        {"id": "opt2", "kind": "recommendation", "sentence": "Urgent surgical review."}]


def stub(monkeypatch, scores, calls=None, fail=False):
    async def fake_jev(state, qs):
        if calls is not None:
            calls.append((state, dict(qs)))
        if fail:
            raise TimeoutError("jev down")
        out = {}
        for k, q in qs.items():
            text = q["instructions"].split(": ", 1)[1]
            scope = "impression" if state.startswith("CONCLUSION") else "report"
            out[k] = {"noul": scores.get((scope, text), 0.1)}
        return out
    monkeypatch.setattr(rc, "_jev", fake_jev)


async def test_a_restating_finding_option_drops_and_a_new_one_stays(monkeypatch):
    stub(monkeypatch, {("report", "No free intraperitoneal gas."): 0.93})
    kept, dropped = await rc.gate_options(OPTS[:2], REPORT, IMPRESSION)
    assert [o["id"] for o in kept] == ["fn1"]
    assert dropped == [{**OPTS[0], "outcome": "already_in_report", "score": 0.93}]


async def test_impression_options_are_checked_against_the_conclusion_only(monkeypatch):
    calls = []
    # in the findings (whole report) but not in the conclusion: stays; already in the conclusion: drops
    stub(monkeypatch, {("impression", "No free intraperitoneal gas."): 0.9,
                       ("report", "Small pelvic free fluid."): 0.95}, calls)
    kept, dropped = await rc.gate_options(OPTS[2:], REPORT, IMPRESSION)
    assert [o["id"] for o in kept] == ["opt1", "opt2"] and [d["id"] for d in dropped] == ["opt0"]
    (state, qs), = calls
    assert state == "CONCLUSION:\n" + IMPRESSION and len(qs) == 3


async def test_finding_options_are_checked_against_the_whole_report(monkeypatch):
    calls = []
    stub(monkeypatch, {}, calls)
    await rc.gate_options(OPTS[:2], REPORT, IMPRESSION)
    (state, qs), = calls
    assert state == "REPORT:\n" + REPORT and len(qs) == 2
    assert all(q["instructions"].startswith(rc.Q_ALREADY) for q in qs.values())


async def test_jev_failure_keeps_every_option(monkeypatch):
    stub(monkeypatch, {}, fail=True)
    kept, dropped = await rc.gate_options(OPTS, REPORT, IMPRESSION)
    assert kept == OPTS and dropped == []


@pytest.mark.parametrize("score,drops", [(0.49, False), (0.5, True)])
async def test_threshold_is_present(monkeypatch, score, drops):
    stub(monkeypatch, {("report", "No psoas collection."): score})
    kept, dropped = await rc.gate_options([OPTS[1]], REPORT, IMPRESSION)
    assert bool(dropped) == drops and bool(kept) != drops


async def test_no_options_no_call(monkeypatch):
    calls = []
    stub(monkeypatch, {}, calls)
    assert await rc.gate_options([], REPORT, IMPRESSION) == ([], [])
    assert calls == []
