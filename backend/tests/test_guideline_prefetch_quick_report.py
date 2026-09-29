"""Guideline retrieval for quick reports (prod 2026-09-29: 6 of 8 quick reports had no guidelines).

Three faults compounded: the quick-report path never scheduled the background prefetch, so
/enhance always ran S1 inline; S1 ran on Qwen, which cannot emit the nested structured output
(0/5 on both providers, gpt-oss 5/5); and S1's timeout fallback raised instead of returning an
empty output.
"""
import asyncio
import hashlib

import pytest

from rapid_reports_ai import guideline_prefetch as gp
from rapid_reports_ai.enhancement_utils import MODEL_CONFIG


def test_prefetch_runs_on_the_structured_output_model():
    # S1 fills a nested schema (guideline objects, query plan): the gpt-oss lane, like the audit.
    assert MODEL_CONFIG["GUIDELINE_PREFETCH"] == MODEL_CONFIG["AUDIT_ANALYZER"]


def test_s1_timeout_returns_an_empty_output_without_a_pipeline_failure(monkeypatch, caplog):
    # The timeout branch built PrefetchOutput without prefetch_id; the outer handler caught the
    # ValidationError, so prod logged a misleading "[PREFETCH] FAILED" traceback on every timeout.
    async def _times_out(*a, **k):
        raise asyncio.TimeoutError

    monkeypatch.setattr(gp, "_stage_glm_extract", _times_out)
    out = asyncio.run(gp.run_prefetch_pipeline(
        findings="A mass.", scan_type="CT", clinical_history="", prefetch_id="pid-1", user_id="u1"))
    assert out.prefetch_id == "pid-1"
    assert out.consolidated_findings == [] and out.applicable_guidelines == []
    assert "[PREFETCH] FAILED" not in caplog.text


def test_quick_report_schedules_the_prefetch_enhance_will_look_up(monkeypatch):
    from rapid_reports_ai import main
    from rapid_reports_ai.quick_report_api import schedule_guideline_prefetch

    calls = []
    monkeypatch.setattr(main, "_schedule_prefetch_task", lambda **kw: calls.append(kw))
    schedule_guideline_prefetch(user_id="u1", findings="  A mass.\n", scan_type="CT AP", clinical_history="jaundice")

    # /enhance hashes the stored FINDINGS (stripped) with the user id; it must find this run.
    enhance_hash = hashlib.sha256("u1:A mass.".encode()).hexdigest()[:16]
    assert len(calls) == 1
    assert calls[0]["findings_hash"] == enhance_hash
    assert main.PREFETCH_INDEX[enhance_hash] == calls[0]["prefetch_id"]
    assert calls[0]["findings"] == "A mass." and calls[0]["scan_type"] == "CT AP"
    main.PREFETCH_INDEX.pop(enhance_hash, None)


def test_quick_report_generate_calls_the_scheduler():
    import inspect
    from rapid_reports_ai import quick_report_api

    assert "schedule_guideline_prefetch(" in inspect.getsource(quick_report_api.generate)
