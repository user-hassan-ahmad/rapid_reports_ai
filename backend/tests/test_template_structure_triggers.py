"""Every sheet write queues a restructure; an unchanged sheet keeps its structure (spec §2)."""
from __future__ import annotations

from rapid_reports_ai import main
from rapid_reports_ai import template_sheet_structure as tss


def test_carry_structure_keeps_a_fresh_structure_the_client_dropped():
    old = {"skill_sheet": "S", "sheet_structure": {"sheet_hash": tss.sheet_hash("S")}}
    assert main._carry_structure({"skill_sheet": "S"}, old)["sheet_structure"] == old["sheet_structure"]
    assert "sheet_structure" not in main._carry_structure({"skill_sheet": "S2"}, old)


def test_carry_structure_never_carries_onto_a_changed_or_missing_sheet():
    old = {"skill_sheet": "S", "sheet_structure": {"sheet_hash": tss.sheet_hash("S")}}
    assert "sheet_structure" not in main._carry_structure({"skill_sheet": "S "}, old)
    assert "sheet_structure" not in main._carry_structure({"generation_mode": "legacy"}, old)
    assert "sheet_structure" not in main._carry_structure({"skill_sheet": "S"}, None)
    assert "sheet_structure" not in main._carry_structure({"skill_sheet": "S"}, {"skill_sheet": "S"})


def test_carry_structure_does_not_override_what_the_client_sent():
    old = {"skill_sheet": "S", "sheet_structure": {"sheet_hash": "old"}}
    new = {"skill_sheet": "S", "sheet_structure": {"sheet_hash": "client"}}
    assert main._carry_structure(new, old)["sheet_structure"] == {"sheet_hash": "client"}


def test_save_and_update_schedule_structuring(monkeypatch):
    calls = []
    monkeypatch.setattr(tss, "schedule_structure", lambda tid, sheet: calls.append((tid, sheet)))
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    main._queue_structure("t2", {"generation_mode": "legacy"})
    assert calls == [("t1", "S")]


def test_legacy_or_empty_templates_never_schedule(monkeypatch):
    calls = []
    monkeypatch.setattr(tss, "schedule_structure", lambda tid, sheet: calls.append((tid, sheet)))
    main._queue_structure("a", {"generation_mode": "skill_sheet", "skill_sheet": "S"})
    main._queue_structure("b", {"sections": [], "skill_sheet": "S"})
    main._queue_structure("c", None)
    main._queue_structure("d", {"generation_mode": "skill_sheet_guided", "skill_sheet": ""})
    assert calls == []


def test_queue_skips_when_structure_is_current(monkeypatch):
    calls = []
    monkeypatch.setattr(tss, "schedule_structure", lambda tid, sheet: calls.append((tid, sheet)))
    monkeypatch.setattr(tss, "needs_restructure", lambda config: False)
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    assert calls == []


def test_queue_never_raises(monkeypatch):
    def boom(tid, sheet):
        raise RuntimeError("x")

    monkeypatch.setattr(tss, "schedule_structure", boom)
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
