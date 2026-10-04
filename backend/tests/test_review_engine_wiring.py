"""Shadow wiring (spec §10.4): scheduled after the candidate is saved, never on the report path, off by default.

Behavioural checks on the quick path: with RR_REVIEW_ENGINE unset nothing is scheduled; in shadow the SSE stream and
the saved report are byte-identical to the off run, the review runs in the background, and neither a slow, a
failing nor an unschedulable review can delay or break the request. No live model or network calls."""
import asyncio
import inspect
import sys
import time
import types
import uuid

import pytest

from rapid_reports_ai import main as main_mod
from rapid_reports_ai import quick_report_api
from rapid_reports_ai.review_engine import engine


@pytest.fixture(autouse=True)
def _clear_tasks():
    engine._REVIEW_TASKS.clear()
    yield
    for t in list(engine._REVIEW_TASKS):
        try:
            t.cancel()
        except RuntimeError:   # its loop already closed
            pass
    engine._REVIEW_TASKS.clear()


# ── schedule_review ─────────────────────────────────────────────────────────

def test_schedule_review_off_by_default(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    assert engine.schedule_review("r1") is None
    assert not engine._REVIEW_TASKS


async def test_schedule_review_in_shadow(monkeypatch):
    seen = []

    async def fake(report_id, text=None):
        seen.append(report_id)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setenv("RR_REVIEW_SAMPLE", "1")
    monkeypatch.setattr(engine, "run_and_store", fake)
    t = engine.schedule_review("r1")
    await t
    assert seen == ["r1"] and t not in engine._REVIEW_TASKS


# ── source wiring ───────────────────────────────────────────────────────────

def test_quick_path_schedules_after_save():
    src = inspect.getsource(quick_report_api)
    save = src.index("report_row = create_quick_report_with_candidates(")
    sched = src.index("schedule_review(str(report_row.id))")
    done = src.index('"done",', save)
    assert save < sched < done
    assert "review engine not scheduled" in src[sched - 300: sched + 300]


def test_templated_path_schedules_after_save():
    src = inspect.getsource(main_mod.generate_report_from_template)
    opts = src.index("tp.schedule_options(")
    sched = src.index("review_engine_schedule(report_id)")
    assert src.index("create_report(") < opts < sched
    region = src[opts:sched + 300]
    assert "if report_id and mirror_candidate is not None:" in region
    assert "try:" in region and "review engine not scheduled" in region


def test_main_does_not_import_the_engine_at_module_level():
    """The wiring imports lazily, so the app's import never pays for the engine."""
    top = inspect.getsource(main_mod).split("\ndef ", 1)[0]
    assert "review_engine.engine" not in top


# ── quick path behaviour ────────────────────────────────────────────────────

_SAVED = []
_DB = object()


def _install_fakes(monkeypatch):
    _SAVED.clear()
    sheet = types.SimpleNamespace(id=uuid.UUID(int=7), skill_sheet_markdown="# sheet", scan_type="CT",
                                  clinical_history="hx")
    report_id = uuid.UUID(int=42)

    async def fake_gen(**kw):
        return {"model": "m", "content": "FINDINGS:\nNormal.", "latency_ms": 5, "run_id": kw["run_id"],
                "generated_at": "2026-10-04T00:00:00+00:00", "error": None, "description": "CT"}

    def fake_save(**kw):
        _SAVED.append(kw)
        return types.SimpleNamespace(id=report_id)

    monkeypatch.setattr(quick_report_api, "get_system_api_key", lambda *a, **k: "")
    monkeypatch.setattr(quick_report_api, "get_ephemeral_skill_sheet", lambda db, sid, user_id=None: sheet)
    monkeypatch.setattr(quick_report_api, "schedule_guideline_prefetch", lambda *a, **k: None)
    monkeypatch.setattr(quick_report_api, "_run_one_generator", fake_gen)
    monkeypatch.setattr(quick_report_api, "create_quick_report_with_candidates", fake_save)
    monkeypatch.setattr(quick_report_api, "new_run_id", lambda: "run-fixed")


async def _stream(monkeypatch):
    _install_fakes(monkeypatch)
    user = types.SimpleNamespace(id=uuid.UUID(int=1), signature=None)
    req = quick_report_api.GenerateRequest(findings="Liver normal.", sheet_id=str(uuid.UUID(int=7)))
    resp = await quick_report_api.generate(req, current_user=user, db=_DB)
    events = [e async for e in resp.body_iterator]
    return events, [dict(s) for s in _SAVED]


async def test_off_schedules_nothing(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    called = []

    async def fake_run(report_id, text=None):
        called.append(report_id)
    monkeypatch.setattr(engine, "run_and_store", fake_run)
    events, saved = await _stream(monkeypatch)
    assert [e["event"] for e in events] == ["candidate", "done"]
    await asyncio.sleep(0)
    assert called == [] and not engine._REVIEW_TASKS


async def test_shadow_stream_and_saved_report_identical_and_not_delayed(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    off_events, off_saved = await _stream(monkeypatch)

    started, release = asyncio.Event(), asyncio.Event()
    called = []

    async def slow_run(report_id, text=None):
        called.append(report_id)
        started.set()
        await release.wait()          # a review that would take forever
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setenv("RR_REVIEW_SAMPLE", "1")
    monkeypatch.setattr(engine, "run_and_store", slow_run)
    t0 = time.monotonic()
    shadow_events, shadow_saved = await _stream(monkeypatch)
    assert time.monotonic() - t0 < 1.0
    assert shadow_events == off_events          # byte-identical SSE payloads
    assert shadow_saved == off_saved            # the saved report is unchanged
    assert len(engine._REVIEW_TASKS) == 1        # running in the background, after the stream finished
    await asyncio.wait_for(started.wait(), 1.0)
    assert called == [str(uuid.UUID(int=42))]
    release.set()
    await asyncio.gather(*list(engine._REVIEW_TASKS))
    assert not engine._REVIEW_TASKS


async def test_shadow_engine_failure_never_reaches_the_request(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    off_events, off_saved = await _stream(monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setenv("RR_REVIEW_SAMPLE", "1")

    # the real run_and_store, with the engine blowing up inside: logged, never raised
    async def boom(report_id, text=None):
        raise RuntimeError("engine exploded")
    monkeypatch.setattr(engine, "load_input", boom)
    events, saved = await _stream(monkeypatch)
    assert events == off_events and saved == off_saved
    results = await asyncio.gather(*list(engine._REVIEW_TASKS))
    assert results == [None]


def _capture_warnings(monkeypatch):
    """Count logger.warning calls directly: the full suite reconfigures logging, so caplog is order-dependent."""
    import rapid_reports_ai.quick_report_api as qra
    warned = []
    monkeypatch.setattr(qra.logger, "warning", lambda msg, *a, **k: warned.append(msg % a if a else msg))
    return warned


async def test_shadow_scheduling_failure_is_logged_not_raised(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    off_events, off_saved = await _stream(monkeypatch)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")

    def broken(report_id, text=None):
        raise RuntimeError("cannot schedule")
    monkeypatch.setattr(engine, "schedule_review", broken)
    warned = _capture_warnings(monkeypatch)
    events, saved = await _stream(monkeypatch)
    assert events == off_events and saved == off_saved
    assert any("review engine not scheduled" in m for m in warned)


async def test_shadow_engine_import_failure_is_logged_not_raised(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    off_events, off_saved = await _stream(monkeypatch)
    monkeypatch.setitem(sys.modules, "rapid_reports_ai.review_engine.engine", None)   # import raises ImportError
    warned = _capture_warnings(monkeypatch)
    events, saved = await _stream(monkeypatch)
    assert events == off_events and saved == off_saved
    assert any("review engine not scheduled" in m for m in warned)
