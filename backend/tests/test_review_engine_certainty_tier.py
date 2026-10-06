"""Overstated trigger = certainty tiers (hybrid rule, validated 2026-10-04 on real wording): report tier from code
(`checks.hedge_tag`) above the Jev dictation tier (`dt{i}`, 4 tiers + not_stated), OR both fact and C1n ≥ 0.5. Never C1n
alone. On a Jev support failure (or no usable dt answer): the report tier vs the aligned dictated line's hedge_tag, code
only. Synthetic cases only, no live model calls."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import jev_pass
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.checks import run_checks
from rapid_reports_ai.review_engine.lanes import LaneContext
from rapid_reports_ai.review_engine.lanes.accuracy import AccuracyLane, overstated_rule

from tests.review_engine_fakes import inp, jev

DICT = "- 14 mm left renal cyst, likely simple\n- Liver normal"


def tier(choice):
    return {"type": "choice", "choice": choice,
            "probabilities": {c: (1.0 if c == choice else 0.0) for c in jev_pass.DICT_TIERS}}


def test_overstated_rule():
    assert overstated_rule("fact", "probable", 0.1) == "tier"
    assert overstated_rule("probable", "probable", 0.95) is None          # synonym swap: never C1n
    assert overstated_rule("possible", "probable", 0.9) is None           # a downgrade
    assert overstated_rule("fact", "fact", 0.6) == "fact_c1n"
    assert overstated_rule("fact", "fact", 0.4) is None
    assert overstated_rule("fact", "not_stated", 0.99) is None            # W1n's territory
    assert overstated_rule("fact", None, 0.99) is None


def test_report_tier_and_dictation_tier_parsing():
    assert jev_pass.report_tier("A cyst, likely simple.") == "probable"
    assert jev_pass.report_tier("Thickening, worrisome for malignancy.") == "probable"
    assert jev_pass.report_tier("A simple cyst.") == "fact"
    assert jev_pass.dictation_tier_of(tier("not_stated")) == "not_stated"
    assert jev_pass.dictation_tier_of(tier("possible")) == "possible"
    assert jev_pass.dictation_tier_of({"noul": 0.4}) is None


async def test_dt_asked_on_the_support_request(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    report = "FINDINGS:\nA 14 mm left renal cyst.\nIMPRESSION:\nRenal cyst."
    await jev_pass.run(inp(report, DICT), report)
    support = next(qs for s, qs in calls if "CLINICAL HISTORY:" in s)
    q = support["dt0"]
    assert q["type"] == "choice" and set(q["criteria"]) == set(jev_pass.DICT_TIERS)
    assert '"A 14 mm left renal cyst."' in q["instructions"] and "cer0" in support
    assert len(calls) == 3


async def _over(monkeypatch, report, answers, fake=None):
    monkeypatch.setattr(rc, "_jev", fake or jev(answers))
    i = inp(report, DICT)
    a = i.artifacts
    al = align(a.report, a.dictated_findings, "", a.sections)
    jp = await jev_pass.run(i, a.report)
    ctx = LaneContext(alignment=al, jev=jp, checks=run_checks(a.report, a.dictated_findings, "", i.scan_type, al))
    return [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "overstated"]


R_FACT = "FINDINGS:\nA 14 mm left renal cyst, which is simple.\nIMPRESSION:\nSimple renal cyst."
R_SAME = "FINDINGS:\nA 14 mm left renal cyst, in keeping with a simple cyst.\nIMPRESSION:\nRenal cyst."


async def test_synonym_swap_is_never_flagged_whatever_c1n(monkeypatch):
    got = await _over(monkeypatch, R_SAME, {"cer*": {"noul": 0.95}, "dt*": tier("probable")})
    assert [c.anchor.text for c in got if "in keeping" in c.anchor.text] == []


async def test_hedge_dropped_is_flagged_by_tier(monkeypatch):
    got = await _over(monkeypatch, R_FACT, {"cer*": {"noul": 0.1}, "dt*": tier("probable")})
    c = next(c for c in got if c.anchor.text.startswith("A 14 mm"))
    assert c.detector == "jev.certainty" and c.evidence["rule"] == "tier"
    assert c.evidence["report_tier"] == "fact" and c.evidence["dictation_tier"] == "probable"


async def test_fact_fact_needs_c1n(monkeypatch):
    assert await _over(monkeypatch, R_FACT, {"cer*": {"noul": 0.3}, "dt*": tier("fact")}) == []
    got = await _over(monkeypatch, R_FACT, {"cer*": {"noul": 0.8}, "dt*": tier("fact")})
    assert got and all(c.evidence["rule"] == "fact_c1n" for c in got)


async def test_not_stated_is_never_overstated(monkeypatch):
    assert await _over(monkeypatch, R_FACT, {"cer*": {"noul": 0.99}, "dt*": tier("not_stated")}) == []


async def test_support_failure_falls_back_to_code_tiers_never_c1n(monkeypatch):
    base = jev()

    async def fake(state, qs):
        if "CLINICAL HISTORY:" in state:
            raise RuntimeError("down")
        return await base(state, qs)
    got = await _over(monkeypatch, R_FACT, {}, fake)
    c = next(c for c in got if c.anchor.text.startswith("A 14 mm"))
    assert c.detector == "code.certainty_tier" and c.evidence["rule"] == "code_tier"
    assert c.evidence["dictation_tier"] == "probable"
    assert await _over(monkeypatch, R_SAME, {}, fake) == []


async def test_unparseable_dt_answer_uses_the_code_comparison(monkeypatch):
    got = await _over(monkeypatch, R_SAME, {"cer*": {"noul": 0.99}, "dt*": {"noul": 0.5}})
    assert got == []


def test_decided_tier_defaults():
    """Decided 2026-10-04: "suspicious for" / "suspicion of" sit at the probable tier; FACT_C1N_FLAG stays 0.5."""
    from rapid_reports_ai.review_engine.lanes import accuracy
    assert jev_pass.report_tier("Mass, suspicious for malignancy.") == "probable"
    assert jev_pass.report_tier("Appearances raise suspicion of malignancy.") == "probable"
    assert jev_pass.report_tier("High suspicion for a neoplasm.") == "probable"
    assert jev_pass.report_tier("No suspicion of malignancy.") == "excluded"
    assert accuracy.FACT_C1N_FLAG == 0.5
