"""Every sheet write structures a grammar sheet on save; the LLM extractor is lab-only (owner decision
2026-10-01); an unchanged sheet keeps its structure; client structures are always stripped (spec §2)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from rapid_reports_ai import main
from rapid_reports_ai.database import crud
from rapid_reports_ai import template_sheet_grammar as tsg
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


def test_client_structure_is_dropped_and_stored_wins_when_sheet_unchanged():
    forged = {"sheet_hash": tss.sheet_hash("S2"), "usable": True}
    assert "sheet_structure" not in main._carry_structure({"skill_sheet": "S2", "sheet_structure": forged}, {})
    old = {"skill_sheet": "S", "sheet_structure": {"sheet_hash": "stored"}}
    new = {"skill_sheet": "S", "sheet_structure": {"sheet_hash": "client"}}
    assert main._carry_structure(new, old)["sheet_structure"] == {"sheet_hash": "stored"}
    assert "sheet_structure" not in main._carry_structure(None, old)


GRAMMAR = """# CT
## Report Structure
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION IMPRESSION | header: "Impression" | role: impression

## Paragraph: Organ (FINDINGS)
COVERS ["organ"]
NEGATIVE "No focal lesion."
"""


@pytest.fixture
def lab_calls(monkeypatch):
    """Record extractor scheduling and grammar stores; fail loudly if the extractor itself runs."""
    calls = {"scheduled": [], "stored": []}
    monkeypatch.setattr(tss, "schedule_structure", lambda tid, sheet: calls["scheduled"].append((tid, sheet)))
    monkeypatch.setattr(tss, "store_parsed", lambda tid, s: calls["stored"].append((tid, s)) or True)

    async def no_extractor(*a, **k):
        raise AssertionError("structure_sheet must not run")

    monkeypatch.setattr(tss, "structure_sheet", no_extractor)
    monkeypatch.delenv("RR_SHEET_EXTRACTOR", raising=False)
    return calls


def test_non_grammar_sheet_schedules_nothing_by_default(lab_calls):
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    main._queue_structure("t2", {"generation_mode": "legacy"})
    assert lab_calls == {"scheduled": [], "stored": []}


@pytest.mark.parametrize("flag", ["1", "true", "on", "ON"])
def test_extractor_is_scheduled_only_when_the_lab_flag_is_on(lab_calls, monkeypatch, flag):
    monkeypatch.setenv("RR_SHEET_EXTRACTOR", flag)
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    main._queue_structure("t2", {"generation_mode": "legacy"})
    assert lab_calls["scheduled"] == [("t1", "S")] and lab_calls["stored"] == []


@pytest.mark.parametrize("flag", ["", "0", "false", "off", "yes"])
def test_extractor_flag_defaults_off(lab_calls, monkeypatch, flag):
    monkeypatch.setenv("RR_SHEET_EXTRACTOR", flag)
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    assert lab_calls["scheduled"] == []


def test_grammar_sheet_is_parsed_and_stored_on_save_without_the_extractor(lab_calls, monkeypatch):
    monkeypatch.setenv("RR_SHEET_EXTRACTOR", "1")  # even with the lab flag on, a grammar sheet is parsed
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": GRAMMAR})
    assert lab_calls["scheduled"] == []
    ((tid, s),) = lab_calls["stored"]
    assert tid == "t1" and s.source == "grammar" and s.usable and s.sheet_hash == tss.sheet_hash(GRAMMAR)
    assert s.lint_errors == []


def test_unusable_grammar_sheet_is_stored_with_its_lint_errors(lab_calls):
    bad = GRAMMAR + "\n## Paragraph: X (FINDINGS)\nCOVERS [\"x\"]\nNo collection when the organ is normal.\n"
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": bad})
    ((_, s),) = lab_calls["stored"]
    assert s.source == "grammar" and not s.usable
    assert [(e.text, e.reason) for e in s.lint_errors] == [("No collection when the organ is normal.",
                                                            tsg.CONDITIONAL_NEGATIVE)]
    assert s.lint_warnings == [] and s.grammar_mode == "template"


def test_save_path_parses_in_template_mode(lab_calls):
    findings_rule = GRAMMAR + 'RULE WHEN [findings: a focal lesion of the organ is reported] SUPPRESS "No focal lesion."\n'
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": findings_rule})
    ((_, s),) = lab_calls["stored"]
    assert not s.usable and [e.reason for e in s.lint_errors] == [tsg.NOT_LEAN]


def test_grammar_sheet_with_a_current_grammar_structure_is_not_reparsed(lab_calls):
    s = tsg.parse_sheet(GRAMMAR).structure
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": GRAMMAR, "sheet_structure": s.model_dump(mode="json")}
    main._queue_structure("t1", cfg)
    assert lab_calls["stored"] == []
    # an extracted structure of the same grammar sheet is replaced by the parse
    main._queue_structure("t1", {**cfg, "sheet_structure": {**cfg["sheet_structure"], "source": "extracted"}})
    assert len(lab_calls["stored"]) == 1


def test_grammar_store_failure_never_fails_the_write(lab_calls, monkeypatch):
    def boom(tid, s):
        raise RuntimeError("db down")

    warnings = []
    monkeypatch.setattr(tss, "store_parsed", boom)
    monkeypatch.setattr(main.logger, "warning", lambda *a, **k: warnings.append(a))
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": GRAMMAR})
    assert len(warnings) == 1 and warnings[0][1] == "t1"


def test_grammar_sheet_store_writes_the_template_row(db_session, db_engine, test_user, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from rapid_reports_ai.database.models import Template
    tpl = Template(name="g", template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": GRAMMAR},
                   user_id=test_user.id, tags=[], is_active=True)
    db_session.add(tpl)
    db_session.commit()
    monkeypatch.setattr(tss, "SessionLocal", sessionmaker(bind=db_engine, autoflush=False, autocommit=False))
    main._queue_structure(str(tpl.id), dict(tpl.template_config))
    db_session.expire_all()
    cfg = db_session.get(Template, tpl.id).template_config
    got = tss.fresh(cfg)
    assert got is not None and got.source == "grammar"


def test_legacy_or_empty_templates_never_schedule(monkeypatch):
    calls = []
    monkeypatch.setenv("RR_SHEET_EXTRACTOR", "1")
    monkeypatch.setattr(tss, "schedule_structure", lambda tid, sheet: calls.append((tid, sheet)))
    main._queue_structure("a", {"generation_mode": "skill_sheet", "skill_sheet": "S"})
    main._queue_structure("b", {"sections": [], "skill_sheet": "S"})
    main._queue_structure("c", None)
    main._queue_structure("d", {"generation_mode": "skill_sheet_guided", "skill_sheet": ""})
    assert calls == []


def test_queue_skips_when_structure_is_current(monkeypatch):
    calls = []
    monkeypatch.setenv("RR_SHEET_EXTRACTOR", "1")
    monkeypatch.setattr(tss, "schedule_structure", lambda tid, sheet: calls.append((tid, sheet)))
    monkeypatch.setattr(tss, "needs_restructure", lambda config: False)
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    assert calls == []


def test_queue_never_raises(monkeypatch):
    def boom(tid, sheet):
        raise RuntimeError("x")

    warnings = []
    monkeypatch.setenv("RR_SHEET_EXTRACTOR", "1")
    monkeypatch.setattr(tss, "schedule_structure", boom)
    monkeypatch.setattr(main.logger, "warning", lambda *a, **k: warnings.append(a))
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    assert len(warnings) == 1 and warnings[0][1] == "t1"


# ── endpoint wiring ────────────────────────────────────────────────────────────

_USER = SimpleNamespace(id="u1")
_FORGED = {"sheet_hash": "forged", "usable": True}


class _Tpl(SimpleNamespace):
    def to_dict(self):
        return {"id": str(self.id), "template_config": self.template_config}


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_queue_structure", lambda tid, cfg: calls.append((tid, cfg)))
    return calls


async def test_create_endpoint_strips_client_structure_and_queues(monkeypatch, queued):
    written = {}

    def fake_create(db, **kw):
        written.update(kw)
        return _Tpl(id="new1", template_config=kw["template_config"])

    monkeypatch.setattr(main, "create_template", fake_create)
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "S", "sheet_structure": _FORGED}
    r = await main.create_template_endpoint(main.TemplateCreate(name="n", template_config=cfg), _USER, None)
    assert r["success"]
    assert "sheet_structure" not in written["template_config"]
    assert queued == [("new1", written["template_config"])]


async def test_update_endpoint_drops_client_structure_carries_stored_and_queues(monkeypatch, queued):
    stored = {"skill_sheet": "S", "generation_mode": "skill_sheet_guided", "sheet_structure": {"sheet_hash": "stored"}}
    written = {}
    monkeypatch.setattr(main, "get_template", lambda db, tid, user_id=None: _Tpl(id=tid, template_config=stored))

    def fake_update(db, **kw):
        written.update(kw)
        return _Tpl(id=kw["template_id"], template_config=kw["template_config"])

    monkeypatch.setattr(main, "update_template", fake_update)
    same = {"generation_mode": "skill_sheet_guided", "skill_sheet": "S", "sheet_structure": _FORGED}
    await main.update_template_endpoint("t9", main.TemplateUpdate(template_config=same), _USER, None)
    assert written["template_config"]["sheet_structure"] == {"sheet_hash": "stored"}
    assert queued == [("t9", written["template_config"])]

    queued.clear()
    changed = {"generation_mode": "skill_sheet_guided", "skill_sheet": "S2", "sheet_structure": _FORGED}
    await main.update_template_endpoint("t9", main.TemplateUpdate(template_config=changed), _USER, None)
    assert "sheet_structure" not in written["template_config"]
    assert queued == [("t9", written["template_config"])]


def _restore(monkeypatch, current: dict, snapshot: dict):
    tpl = _Tpl(id="t5", name="n", description=None, tags=[], template_config=current)
    ver = SimpleNamespace(template_id="t5", name="n", description=None, tags=[], template_config=snapshot)
    monkeypatch.setattr(crud, "get_template", lambda db, tid, user_id=None: tpl)
    monkeypatch.setattr(crud, "get_template_version", lambda db, vid, user_id=None: ver)
    monkeypatch.setattr(crud, "create_template_version", lambda db, t, skip_if_unchanged=False: None)
    db = SimpleNamespace(commit=lambda: None, refresh=lambda t: None)
    monkeypatch.setattr(main, "restore_template_version", lambda **kw: crud.restore_template_version(db, **{
        k: v for k, v in kw.items() if k != "db"}))
    return tpl


async def test_restore_endpoint_carries_current_structure_for_same_sheet(monkeypatch, queued):
    current = {"generation_mode": "skill_sheet_guided", "skill_sheet": "S", "sheet_structure": {"sheet_hash": "cur"}}
    snapshot = {"generation_mode": "skill_sheet_guided", "skill_sheet": "S", "sheet_structure": {"sheet_hash": "old"}}
    tpl = _restore(monkeypatch, current, snapshot)
    r = await main.restore_template_version_endpoint("t5", "v1", _USER, None)
    assert r["success"]
    assert tpl.template_config["sheet_structure"] == {"sheet_hash": "cur"}
    assert queued == [("t5", tpl.template_config)]


async def test_restore_endpoint_strips_snapshot_structure_for_other_sheet(monkeypatch, queued):
    current = {"generation_mode": "skill_sheet_guided", "skill_sheet": "S", "sheet_structure": {"sheet_hash": "cur"}}
    snapshot = {"generation_mode": "skill_sheet_guided", "skill_sheet": "OLD", "sheet_structure": _FORGED}
    tpl = _restore(monkeypatch, current, snapshot)
    await main.restore_template_version_endpoint("t5", "v1", _USER, None)
    assert "sheet_structure" not in tpl.template_config
    assert tpl.template_config["skill_sheet"] == "OLD"
    assert queued == [("t5", tpl.template_config)]


async def test_skill_sheet_save_endpoint_queues_new_template(monkeypatch, queued):
    written = {}

    async def fake_cov(self, sheet, key):
        return ["A"]

    monkeypatch.setattr(main.TemplateManager, "extract_coverage_sections", fake_cov)
    monkeypatch.setattr(main, "get_system_api_key", lambda *a: "k")

    def fake_create(db, **kw):
        written.update(kw)
        return _Tpl(id="s1", template_config=kw["template_config"])

    monkeypatch.setattr(main, "create_template", fake_create)
    req = main.SkillSheetSaveRequest(skill_sheet="S", scan_type="CT", template_name="T")
    r = await main.skill_sheet_save_endpoint(req, _USER, None)
    assert r == {"success": True, "template_id": "s1"}
    assert "sheet_structure" not in written["template_config"]
    assert queued == [("s1", written["template_config"])]
    assert written["template_config"]["generation_mode"] == "skill_sheet_guided"
