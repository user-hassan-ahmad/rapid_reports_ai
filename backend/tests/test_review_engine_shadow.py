"""run_quality_check records the pre-edit report for the Gate D shadow log only when the engine is not off."""
import pytest

from rapid_reports_ai import report_review as rr


@pytest.fixture
def stubbed(monkeypatch):
    async def fake_check(report, findings, scan_type, options, **kw):
        return rr.CheckResult(flags=[rr.Flag(kind="omission", text="Small left effusion", score=0.1)], n_items=1)

    async def fake_insert(report, findings, items, **kw):
        return rr.RepairResult(report=report + " Small left effusion.", applied=1)
    monkeypatch.setattr(rr, "check", fake_check)
    monkeypatch.setattr(rr, "insert_findings", fake_insert)


async def test_pre_edit_report_recorded_in_shadow(monkeypatch, stubbed):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    report, _, tel = await rr.run_quality_check("FINDINGS:\nNormal.", "- Small left effusion", "CT", [])
    assert tel["pre_edit_report"] == "FINDINGS:\nNormal." and report.endswith("Small left effusion.")


async def test_pre_edit_report_absent_when_off(monkeypatch, stubbed):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    _, _, tel = await rr.run_quality_check("FINDINGS:\nNormal.", "- Small left effusion", "CT", [])
    assert "pre_edit_report" not in tel
