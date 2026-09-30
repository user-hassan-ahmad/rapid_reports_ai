from __future__ import annotations

import pytest

from rapid_reports_ai import template_history as th
from rapid_reports_ai.report_review import ReportSection

SECTIONS = [ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            ReportSection(name="FINDINGS", header=None, role="findings"),
            ReportSection(name="IMPRESSION", header="Impression", role="impression")]
HISTORY = "67 year old female with right iliac fossa pain, raised CRP. Query appendicitis."


def test_provenance_accepts_a_terse_restatement():
    assert th.grounded("67F. Right iliac fossa pain. Raised CRP. ?Appendicitis.", HISTORY)


def test_provenance_rejects_added_facts():
    assert not th.grounded("67F. Right iliac fossa pain. Raised CRP. Previous appendicectomy.", HISTORY)
    assert not th.grounded("72F. Right iliac fossa pain.", HISTORY)


@pytest.mark.parametrize("text,history", [
    ("67F. Pain RIF. ?Appendicitis.", "67 yo F, pain RIF ?appendicitis"),
    ("54M. Chest pain. ?PE.", "54-year-old man, chest pain, query PE"),
    ("71F. History of bowel cancer. Weight loss. ?Recurrence.", "71 year old lady. Hx bowel cancer, weight loss ?recurrence"),
    ("45M. Post-op day 3. Fever. ?Collection.", "45M post-op day 3 with fever, ?collection"),
    ("60F. No trauma. Back pain.", "60 year old woman, back pain, no trauma"),
])
def test_provenance_accepts_realistic_restatements(text, history):
    assert th.grounded(text, history)


@pytest.mark.parametrize("text,history", [
    # a two-letter acronym is still a fact
    ("54M. Chest pain. ?PE. AF.", "54-year-old man, chest pain, query PE"),
    # a number glued to an age unit is still a number
    ("72yo F. Pain RIF.", "67 yo F, pain RIF"),
    # sex needs a matching word in the input
    ("67M. Pain RIF.", "67 year old female, pain RIF"),
    ("67F. Pain RIF.", "67 year old, pain RIF"),
    # an added negation inverts a fact
    ("60F. No back pain.", "60 year old woman, back pain"),
    # a query must not become a known/past fact
    ("71F. Known malignancy.", "71 year old woman ?malignancy"),
    ("71F. Previous malignancy.", "71 year old woman ?malignancy"),
])
def test_provenance_rejects_subtle_additions(text, history):
    assert not th.grounded(text, history)


def test_insert_puts_the_section_first_when_findings_are_implicit():
    report = "The appendix is dilated.\n\nImpression\nAppendicitis."
    out = th.insert_history(report, "67F. ?Appendicitis.", SECTIONS)
    assert out.startswith("CLINICAL HISTORY\n67F. ?Appendicitis.\n\nThe appendix is dilated.")


def test_insert_goes_before_the_next_present_header():
    secs = [ReportSection(name="TECHNIQUE", header="TECHNIQUE", role="technique"), SECTIONS[0],
            ReportSection(name="FINDINGS", header="FINDINGS", role="findings")]
    report = "TECHNIQUE\nCT.\n\nFINDINGS\nX."
    assert th.insert_history(report, "67F.", secs) == "TECHNIQUE\nCT.\n\nCLINICAL HISTORY\n67F.\n\nFINDINGS\nX."


def _fake_agent(text):
    class R:
        class output:
            pass
    R.output.text = text

    async def fake(**kw):
        return R
    return fake


async def test_write_history_returns_none_when_ungrounded(monkeypatch):
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent("67F. Previous appendicectomy."))
    assert await th.write_history(HISTORY) is None


async def test_write_history_returns_grounded_text(monkeypatch):
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent(" 67F. Right iliac fossa pain. ?Appendicitis. "))
    assert await th.write_history(HISTORY) == "67F. Right iliac fossa pain. ?Appendicitis."


async def test_write_history_omits_on_failure_or_empty(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(th, "_run_agent_with_model", boom)
    assert await th.write_history(HISTORY) is None
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent("  "))
    assert await th.write_history(HISTORY) is None
    assert await th.write_history("   ") is None
