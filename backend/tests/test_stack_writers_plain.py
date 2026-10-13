import pytest

from rapid_reports_ai import quick_report_generator as G
from rapid_reports_ai import report_review as RR


@pytest.mark.asyncio
async def test_quick_check_reads_plain_statements(monkeypatch):
    seen = {}

    async def fake_check(report, findings, scan_type, options, **kw):
        seen["check"], seen["record"], seen["decisions"] = findings, kw.get("record_edits"), kw.get("brief_decisions")
        return report, options, {"enabled": True}

    async def fake_describe(findings, history, scan_type):
        seen["describe"] = findings
        return "d"

    class R:
        output = "FINDINGS\nLiver normal."

    async def fake_agent(**kw):
        return R()

    async def no_opts(*a, **k):
        return []

    monkeypatch.setattr(G, "run_quality_check", fake_check)
    monkeypatch.setattr(G, "_describe", fake_describe)
    monkeypatch.setattr(G, "_run_agent_with_model", fake_agent)
    monkeypatch.setattr(G, "_write_options", no_opts)
    monkeypatch.setattr(G, "_get_api_key_for_provider", lambda provider: "k")
    await G.generate_quick_report(skill_sheet="", scan_type="CT", findings="Liver: Normal.", clinical_history="",
                                  stack=True, check_findings="Normal.")
    assert seen == {"check": "Normal.", "describe": "Normal.", "record": True, "decisions": None}


def test_record_edits_records_without_the_engine(monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "off")
    tel = RR._record_edits({}, "A. B.", "A.", [{"type": "removal", "clause": "B."}], force=True)
    assert tel["pre_edit_report"] == "A. B." and tel["applied_edits"] == [{"type": "removal", "clause": "B."}]
    assert RR._record_edits({}, "A. B.", "A.", [], force=False) == {}
