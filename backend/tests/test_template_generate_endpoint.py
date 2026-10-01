"""Template endpoints (spec §4): legacy (non skill-sheet) templates are retired —
hidden from lists, generation refused, rows never deleted."""
from __future__ import annotations

from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import Template


def _ids(client, headers, **params):
    body = client.get("/api/templates", headers=headers, params=params).json()
    assert body["success"] is True
    return {t["id"] for t in body["templates"]}


def test_list_hides_legacy_templates(client, auth_headers, legacy_template, guided_template):
    ids = _ids(client, auth_headers)
    assert str(guided_template.id) in ids and str(legacy_template.id) not in ids


def test_list_pagination_counts_only_visible_templates(client, auth_headers, legacy_template, guided_template):
    # The retired row must not consume the page slot of a visible one.
    assert _ids(client, auth_headers, limit=1) == {str(guided_template.id)}


def test_tag_filtered_list_hides_legacy(db_session, test_user, legacy_template, guided_template):
    # The endpoint's `tags` arg is not bound from the query string, so pin the crud tag path directly.
    assert crud.get_templates(db_session, str(test_user.id), tags=["legacy-tag"]) == []
    assert crud.get_templates(db_session, str(test_user.id), tags=["guided-tag"]) == [guided_template]


def test_tags_endpoint_omits_tags_only_on_retired_templates(client, auth_headers, legacy_template, guided_template):
    tags = client.get("/api/templates/tags", headers=auth_headers).json()["tags"]
    assert "guided-tag" in tags and "legacy-tag" not in tags


def test_legacy_template_is_refused(client, auth_headers, legacy_template, db_session):
    r = client.post(f"/api/templates/{legacy_template.id}/generate", json={"user_inputs": {"FINDINGS": "f"}},
                    headers=auth_headers).json()
    assert r["success"] is False
    assert "retired template format" in r["error"] and "skill-sheet" in r["error"]
    # Retired, never deleted.
    assert db_session.get(Template, legacy_template.id) is not None


def test_malformed_and_missing_configs_are_hidden_and_do_not_break_the_list(
        client, auth_headers, db_session, test_user, guided_template):
    bad = [Template(name=f"Bad{i}", template_config=cfg, user_id=test_user.id, tags=[], is_active=True)
           for i, cfg in enumerate([["skill_sheet_guided"], "skill_sheet_guided", None])]
    db_session.add_all(bad)
    db_session.commit()
    assert all(crud.is_retired_template(t) for t in bad)
    assert _ids(client, auth_headers) == {str(guided_template.id)}


# ── Phase 1 at "Set up workspace" (plan 2026-10-01-template-wiring W3) ─────────

import asyncio  # noqa: E402
import pathlib  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rapid_reports_ai import template_lean as tl  # noqa: E402
from rapid_reports_ai import template_pipeline as tp  # noqa: E402
from rapid_reports_ai import template_sheet_grammar as tsg  # noqa: E402
from rapid_reports_ai.database import get_db  # noqa: E402
from rapid_reports_ai.database.models import TemplateCaseSheet  # noqa: E402
from rapid_reports_ai.main import LEGACY_RETIRED, app  # noqa: E402

_FIX = pathlib.Path(__file__).parent / "fixtures" / "template_pipeline"
LEAN = (_FIX / "lean_cmr.md").read_text()
MASTER = (_FIX / "master_cmr.md").read_text()


@pytest.fixture
def mirror_template(db_session, test_user):
    """A skill_sheet_guided template holding a lean grammar sheet and its fresh grammar structure."""
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": LEAN, "scan_type": "CMR",
           "sheet_structure": tsg.parse_sheet(LEAN).structure.model_dump(mode="json")}
    t = Template(name="Lean CMR", template_config=cfg, user_id=test_user.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


class Phase1Stub:
    """tp.run_phase1 stand-in: counts calls; held running while `hold` is set; raises when `fail`."""

    def __init__(self):
        self.calls, self.hold, self.fail = [], None, False

    async def __call__(self, sheet, scan_type, history):
        self.calls.append(history)
        if self.hold is not None:
            await self.hold.wait()
        if self.fail:
            raise RuntimeError("model call failed: boom")
        return {"master_sheet": MASTER, "case_result": {"usable": True}, "model": "m", "latency_ms": 10,
                "prompt_version": "p"}


@pytest.fixture
def phase1(monkeypatch, db_engine):
    stub = Phase1Stub()
    monkeypatch.setattr(tp, "run_phase1", stub)
    monkeypatch.setattr(tp, "_session", sessionmaker(bind=db_engine, autoflush=False, autocommit=False))
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    yield stub
    tp._PHASE1_TASKS.clear()


@pytest.fixture
def aclient(db_session):
    def _db():
        yield db_session
    app.dependency_overrides[get_db] = _db
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


async def _prepare(aclient, headers, template, history="?HCM family screening"):
    r = await aclient.post(f"/api/templates/{template.id}/prepare", headers=headers,
                           json={"clinical_history": history, "scan_type": "CMR"})
    return r.json()


async def _drain():
    await asyncio.gather(*list(tp._PHASE1_TASKS.values()), return_exceptions=True)


async def test_prepare_with_the_flag_off_is_skipped(aclient, auth_headers, mirror_template, phase1, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "0")
    assert await _prepare(aclient, auth_headers, mirror_template) == {"success": True, "status": "skipped"}
    await _drain()
    assert phase1.calls == []


async def test_prepare_runs_phase1_on_an_old_sheet_without_a_grammar_structure(aclient, auth_headers,
                                                                               guided_template, phase1):
    """Lean path: Phase 1 serves options only, so any stored skill_sheet_guided sheet is prepared."""
    assert (await _prepare(aclient, auth_headers, guided_template))["status"] == "running"
    await _drain()
    assert phase1.calls == ["?HCM family screening"]


async def test_prepare_runs_phase1_once_per_case(aclient, auth_headers, mirror_template, phase1, db_session):
    phase1.hold = asyncio.Event()
    assert (await _prepare(aclient, auth_headers, mirror_template))["status"] == "running"
    assert (await _prepare(aclient, auth_headers, mirror_template))["status"] == "running"  # in flight
    phase1.hold.set()
    await _drain()
    assert (await _prepare(aclient, auth_headers, mirror_template))["status"] == "ready"
    assert phase1.calls == ["?HCM family screening"]
    row = db_session.query(TemplateCaseSheet).one()
    db_session.refresh(row)
    assert row.status == "ready" and row.master_sheet == MASTER and not tp._PHASE1_TASKS


async def test_a_different_history_starts_a_new_phase1(aclient, auth_headers, mirror_template, phase1):
    await _prepare(aclient, auth_headers, mirror_template, "history one")
    await _drain()
    assert (await _prepare(aclient, auth_headers, mirror_template, "history two"))["status"] == "running"
    await _drain()
    assert phase1.calls == ["history one", "history two"]


async def test_resolve_master_awaits_an_in_flight_phase1(aclient, auth_headers, mirror_template, phase1, db_session,
                                                         test_user):
    phase1.hold = asyncio.Event()
    await _prepare(aclient, auth_headers, mirror_template)
    pending = asyncio.ensure_future(tp.resolve_master(db_session, test_user, mirror_template, LEAN, "CMR",
                                                      "?HCM family screening"))
    await asyncio.sleep(0.05)
    assert not pending.done()  # waiting on the held task
    phase1.hold.set()
    assert await pending == (MASTER, "awaited")
    assert phase1.calls == ["?HCM family screening"]
    # the next generate of the same case reads the stored row
    assert await tp.resolve_master(db_session, test_user, mirror_template, LEAN, "CMR",
                                   "?HCM family screening") == (MASTER, "cached")


async def test_resolve_master_without_prepare_runs_inline(db_session, test_user, mirror_template, phase1):
    assert await tp.resolve_master(db_session, test_user, mirror_template, LEAN, "CMR", "h") == (MASTER, "inline")
    assert phase1.calls == ["h"] and not tp._PHASE1_TASKS
    assert db_session.query(TemplateCaseSheet).one().status == "ready"


async def test_phase1_failure_marks_the_row_failed_and_resolves_to_none(aclient, auth_headers, mirror_template,
                                                                        phase1, db_session, test_user):
    phase1.fail = True
    await _prepare(aclient, auth_headers, mirror_template)
    await _drain()
    row = db_session.query(TemplateCaseSheet).one()
    db_session.refresh(row)
    assert row.status == "failed" and "boom" in row.error
    assert await tp.resolve_master(db_session, test_user, mirror_template, LEAN, "CMR",
                                   "?HCM family screening") == (None, "failed")
    assert len(phase1.calls) == 1


async def test_resolve_master_times_out_to_failed(db_session, test_user, mirror_template, phase1, monkeypatch):
    monkeypatch.setattr(tp, "PHASE1_AWAIT_S", 0.05)
    phase1.hold = asyncio.Event()
    assert await tp.resolve_master(db_session, test_user, mirror_template, LEAN, "CMR", "h") == (None, "failed")
    task = next(iter(tp._PHASE1_TASKS.values()))
    assert not task.cancelled()  # the timeout does not cancel the job: it still persists for the next generate
    phase1.hold.set()
    await _drain()
    assert await tp.resolve_master(db_session, test_user, mirror_template, LEAN, "CMR", "h") == (MASTER, "cached")


async def test_prepare_refuses_a_legacy_template(aclient, auth_headers, legacy_template, phase1):
    assert await _prepare(aclient, auth_headers, legacy_template) == {"success": False, "error": LEGACY_RETIRED}
    assert phase1.calls == []


# ── Generate runs the mirror behind RR_TEMPLATE_MIRROR (plan 2026-10-01-template-wiring W4) ──

from rapid_reports_ai.database.models import Report  # noqa: E402
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402

CASE = {"usable": True, "placement_units": [{"kind": "IF_PRESENT", "text": "No LGE", "key": "x", "paragraph": "F"}]}
MIRROR_OUT = {"report_content": "Findings:\nThe left ventricle is normal in size and function.\n\nConclusion:\n"
                                "1. Normal cardiac MRI.\n\nDr T", "model_used": "qwen-x",
              "description": "Normal CMR", "scan_type": "CMR", "brief_used": True, "brief_text": "BRIEF",
              "brief_decisions": {"options": []}, "options": [], "options_pending": True,
              "gate_dropped": [], "case_decisions": None,
              "quality_check": {"enabled": True, "review": [{"kind": "partial", "line": "LV normal."}]},
              "history_inserted": True, "phase1_used": False,
              "sections": ["CLINICAL DETAILS", "FINDINGS", "CONCLUSION"], "lat": {"generator_s": 1.2},
              "jev_calls": {}}
OPTION = {"id": "fn0", "kind": "finding_negative", "section": "FINDINGS", "sentence": "No LGE."}


@pytest.fixture
def stubs(monkeypatch, db_engine):
    seen = {"mirror": [], "current": [], "resolve": [], "heavy": [], "hold": None, "fail": False, "case": None}

    async def fake_lean(**kw):
        seen["mirror"].append(kw)

        async def job():   # the options job: Phase 1 resolved, routed, written, vetted (after the report)
            if seen["hold"] is not None:
                await seen["hold"].wait()
            if seen["fail"]:
                raise RuntimeError("option writer down")
            case = kw["case"]
            seen["case"] = await case() if callable(case) else case
            return {"options": [dict(OPTION)], "gate_dropped": [{"id": "x", "outcome": "contradicted"}],
                    "options_raw": [], "case_decisions": {"capped": []}, "phase1_used": True,
                    "lat": {"options_s": 0.4, "options_ready_s": 3.0}}
        return {**MIRROR_OUT, "options_job": asyncio.ensure_future(job())}

    async def fake_heavy(**kw):
        seen["heavy"].append(kw)
        return dict(MIRROR_OUT)

    async def fake_resolve(db, user, template, sheet, scan_type, history):
        seen["resolve"].append(history)
        return CASE, "cached"

    async def fake_current(self, template_config, user_inputs, user_signature=None, **kw):
        seen["current"].append(user_inputs)
        return {"report_content": "CURRENT REPORT: the left ventricle is normal in size and function.",
                "description": "Normal CMR", "scan_type": "CMR", "model_used": "m"}

    monkeypatch.setattr(tl, "generate_template_report_lean", fake_lean)
    monkeypatch.setattr(tp, "generate_template_report", fake_heavy)   # parked: never called
    monkeypatch.setattr(tp, "resolve_case", fake_resolve)
    monkeypatch.setattr(TemplateManager, "generate_report_from_config", fake_current)
    monkeypatch.setattr("rapid_reports_ai.main._schedule_prefetch_task", lambda **kw: None)
    monkeypatch.setattr(tp, "_session", sessionmaker(bind=db_engine, autoflush=False, autocommit=False))
    return seen


async def _drain_options():
    await asyncio.gather(*list(tp._OPTION_TASKS), return_exceptions=True)


async def _generate(aclient, headers, template, pipeline=None):
    body = {"user_inputs": {"FINDINGS": "LV normal. No LGE.", "CLINICAL_HISTORY": "?HCM"}}
    if pipeline:
        body["pipeline"] = pipeline
    return (await aclient.post(f"/api/templates/{template.id}/generate", headers=headers, json=body)).json()


async def test_flag_on_runs_the_mirror_and_persists_artifacts(aclient, auth_headers, mirror_template, stubs,
                                                              db_session, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    r = await _generate(aclient, auth_headers, mirror_template)
    assert r["success"] and r["pipeline"] == "mirror" and not stubs["current"] and not stubs["heavy"]
    kw = stubs["mirror"][0]
    assert kw["sheet"] == LEAN and kw["history"] == "?HCM"
    assert kw["findings"] == "LV normal. No LGE." and kw["scan_type"] == "CMR"
    assert r["artifacts"]["sections"] == MIRROR_OUT["sections"] and r["options_pending"] is True
    await _drain_options()
    assert stubs["case"] == CASE   # Phase 1 resolved inside the background job
    saved = db_session.get(Report, __import__("uuid").UUID(r["report_id"]))
    db_session.refresh(saved)
    cand = saved.candidate_reports[0]
    assert cand["options"][0]["id"] == "fn0" and cand["phase1_source"] == "cached" and cand["sections"]
    assert cand["case_decisions"] == {"capped": []} and cand["gate_dropped"][0]["outcome"] == "contradicted"
    assert cand["options_status"] == "ready" and cand["options_pending"] is False
    assert cand["lat"]["generator_s"] == 1.2 and cand["lat"]["options_ready_s"] == 3.0
    assert saved.report_content == MIRROR_OUT["report_content"] and saved.report_type == "templated"


async def test_generate_returns_before_the_options_finish_and_persists_them_later(
        aclient, auth_headers, mirror_template, stubs, db_session, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    stubs["hold"] = asyncio.Event()
    r = await asyncio.wait_for(_generate(aclient, auth_headers, mirror_template), 2.0)   # never waits for options
    assert r["success"] and r["options_pending"] is True and r["response"] == MIRROR_OUT["report_content"]
    rid = r["report_id"]
    saved = db_session.get(Report, __import__("uuid").UUID(rid))
    assert saved.candidate_reports[0]["options"] == [] and saved.candidate_reports[0]["options_status"] == "pending"
    poll = (await aclient.get(f"/api/reports/{rid}/options", headers=auth_headers)).json()
    assert poll["status"] == "pending" and poll["options_pending"] is True and poll["options"] == []
    stubs["hold"].set()
    await _drain_options()
    db_session.expire_all()
    poll = (await aclient.get(f"/api/reports/{rid}/options", headers=auth_headers)).json()
    assert poll["status"] == "ready" and [o["id"] for o in poll["options"]] == ["fn0"]
    assert poll["review"] == [{"kind": "partial", "line": "LV normal."}] and poll["phase1_source"] == "cached"
    assert poll["artifacts"]["options"][0]["id"] == "fn0"


async def test_an_options_failure_leaves_the_report_untouched(aclient, auth_headers, mirror_template, stubs,
                                                             db_session, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    stubs["fail"] = True
    stubs["hold"] = asyncio.Event()   # fail only after the report is saved and read back
    warned = []
    monkeypatch.setattr(tp.logger, "warning", lambda msg, *a: warned.append(msg % a))
    r = await _generate(aclient, auth_headers, mirror_template)
    assert r["success"] and r["pipeline"] == "mirror" and r["response"] == MIRROR_OUT["report_content"]
    saved = db_session.get(Report, __import__("uuid").UUID(r["report_id"]))
    before = (saved.report_content, saved.candidate_reports[0]["content"], saved.model_used)
    stubs["hold"].set()
    await _drain_options()
    assert any("option writer down" in w for w in warned)   # logged
    db_session.expire_all()
    saved = db_session.get(Report, __import__("uuid").UUID(r["report_id"]))
    assert (saved.report_content, saved.candidate_reports[0]["content"], saved.model_used) == before
    assert saved.candidate_reports[0]["options"] == [] and saved.candidate_reports[0]["options_status"] == "failed"
    poll = (await aclient.get(f"/api/reports/{r['report_id']}/options", headers=auth_headers)).json()
    assert poll["status"] == "failed" and poll["options"] == []


async def test_flag_off_runs_todays_path(aclient, auth_headers, mirror_template, stubs, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "0")
    r = await _generate(aclient, auth_headers, mirror_template)
    assert r["success"] and r["pipeline"] == "current" and r["artifacts"] is None
    assert stubs["current"] and not stubs["mirror"] and not stubs["resolve"] and r["response"].startswith("CURRENT REPORT")


async def test_flag_on_with_an_old_sheet_runs_the_lean_path(aclient, auth_headers, guided_template, stubs,
                                                            monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    r = await _generate(aclient, auth_headers, guided_template)   # no grammar structure: the lean path still runs
    assert r["pipeline"] == "mirror" and not stubs["current"] and stubs["mirror"][0]["sheet"].startswith("## FINDINGS")


async def test_allowlisted_user_can_choose_current(aclient, auth_headers, mirror_template, stubs, monkeypatch,
                                                   test_user):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    monkeypatch.setenv("RR_PIPELINE_OVERRIDE_USERS", test_user.email)
    r = await _generate(aclient, auth_headers, mirror_template, pipeline="current")
    assert r["pipeline"] == "current" and stubs["current"] and not stubs["mirror"]


async def test_mirror_response_keeps_the_shape_the_frontend_reads(aclient, auth_headers, mirror_template, stubs,
                                                                  monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    r = await _generate(aclient, auth_headers, mirror_template)
    assert r["response"] == MIRROR_OUT["report_content"] and isinstance(r["model"], str) and r["model"]
    assert r["report_id"] and r["template_id"] == str(mirror_template.id) and r["scan_type"] == "CMR"
    assert r["applicable_guidelines"] == []


async def test_a_mirror_failure_falls_back_to_todays_path(aclient, auth_headers, mirror_template, stubs, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")

    async def broken(**kw):
        raise RuntimeError("provider down")
    monkeypatch.setattr(tl, "generate_template_report_lean", broken)
    r = await _generate(aclient, auth_headers, mirror_template)
    assert r["success"] and r["pipeline"] == "current" and r["artifacts"] is None and stubs["current"]


async def test_prepare_runs_phase1_on_the_templates_scan_type(aclient, auth_headers, mirror_template, phase1,
                                                              monkeypatch):
    seen = []

    async def p1(sheet, scan_type, history):
        seen.append(scan_type)
        return {"master_sheet": MASTER, "case_result": {}, "model": "m", "latency_ms": 1, "prompt_version": "p"}
    monkeypatch.setattr(tp, "run_phase1", p1)
    r = await aclient.post(f"/api/templates/{mirror_template.id}/prepare", headers=auth_headers,
                           json={"clinical_history": "h", "scan_type": "something else"})
    assert r.json()["status"] == "running"
    await _drain()
    assert seen == ["CMR"]  # generate reads the template's scan type, so Phase 1 must too
