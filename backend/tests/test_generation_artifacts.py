from __future__ import annotations

import logging

from rapid_reports_ai import quick_report_api as qra
from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai import report_review as rr
from rapid_reports_ai.generation_artifacts import GenerationArtifacts


def test_from_candidate_reads_either_pathway_record():
    rec = {"content": "FINDINGS:\nX.\n\nIMPRESSION:\nY.", "options": [{"id": "fn0", "section": "FINDINGS"}],
           "quality_check": {"enabled": True}, "brief": {"text": "t", "decisions": {"rules": []}},
           "sections": ["FINDINGS", "IMPRESSION"]}
    a = GenerationArtifacts.from_candidate(rec, "dictated X")
    assert a.report.startswith("FINDINGS") and a.dictated_findings == "dictated X"
    assert a.sections == ["FINDINGS", "IMPRESSION"] and a.brief == {"decisions": {"rules": []}}
    assert a.options[0]["id"] == "fn0"


def test_option_with_unlisted_section_is_kept_and_marked(caplog):
    rec = {"content": "", "options": [{"id": "fn0", "section": "NOPE"}, {"id": "fn1", "section": "FINDINGS"}],
           "sections": ["FINDINGS"]}
    with caplog.at_level(logging.WARNING):
        a = GenerationArtifacts.from_candidate(rec, "")
    assert [(o["id"], o["section_known"]) for o in a.options] == [("fn0", False), ("fn1", True)]
    assert "NOPE" in caplog.text and "1 option" in caplog.text


def test_no_sections_keeps_every_option_unanchored():
    a = GenerationArtifacts.from_candidate({"content": "", "options": [{"id": "fn0", "section": "FINDINGS"}]}, "")
    assert a.sections == [] and a.options[0]["section_known"] is False


def test_brief_without_decisions_is_none():
    assert GenerationArtifacts.from_candidate({"content": "", "brief": {"text": "t"}}, "").brief is None
    assert GenerationArtifacts.from_candidate({"content": "", "brief": None}, "").brief is None


def test_quick_sections_are_top_level_only():
    report = ("FINDINGS:\n\nHEAD AND NECK:\nNormal.\n\nCHEST:\nNormal.\n\nABDOMEN AND PELVIS:\nNormal.\n\n"
              "IMPRESSION:\nNo acute abnormality.")
    assert "CHEST" in rr.header_names(report)
    assert rr.quick_section_names(report) == ["FINDINGS", "IMPRESSION"]


async def test_quick_candidate_record_meets_the_contract(monkeypatch):
    """Producer -> contract: the record quick_report_api builds, with options from the shared
    writer, anchors every option to a listed section."""
    class R:
        class output:
            sentences = ["Small right pleural effusion."]

    async def runner(**kw):
        return R
    options = await rc.write_options(
        [{"kind": "impression", "text": "small right pleural effusion"},
         {"kind": "finding_negative", "section": "FINDINGS", "text": "no pneumothorax", "finding": "effusion"}],
        "small right pleural effusion", "CT chest", model="m", runner=runner)
    report = ("FINDINGS:\n\nCHEST:\nSmall right pleural effusion. No pneumothorax.\n\n"
              "IMPRESSION:\nSmall right pleural effusion.")

    async def fake_generate(**kw):
        return {"report_content": report, "description": "d", "brief_options": options,
                "quality_check": {"enabled": True}, "brief_used": True, "brief_text": "t",
                "brief_decisions": {"rules": []}}
    monkeypatch.setattr(qra, "generate_quick_report", fake_generate)
    monkeypatch.setattr(qra, "log_generator_run", lambda **kw: None)
    rec = await qra._run_one_generator(skill_sheet_markdown="s", findings="small right pleural effusion",
                                       model_name="m", run_id="r", scan_type="CT chest", clinical_history="")
    assert rec["error"] is None
    a = GenerationArtifacts.from_candidate(rec, "small right pleural effusion")
    assert a.sections == ["FINDINGS", "IMPRESSION"]
    assert len(a.options) == 2 and all(o["section_known"] for o in a.options)
    assert a.brief == {"decisions": {"rules": []}}


async def test_write_options_uses_style_and_impression_section():
    seen = {}

    class R:
        class output:
            sentences = ["Written."]

    async def runner(**kw):
        seen.update(kw)
        return R
    opts = [{"kind": "impression", "text": "3 cm mass"},
            {"kind": "finding_negative", "section": "Solid organs", "text": "no liver lesion", "finding": "mass"}]
    out = await rc.write_options(opts, "f", "CT", model="m", runner=runner,
                                 style="Quoted: \"Uncomplicated appendicitis.\"", impression_section="CONCLUSION")
    assert out[0] == {"id": "opt0", "kind": "impression", "section": "CONCLUSION", "sentence": "Written.",
                      "reason": "", "source": "3 cm mass"}
    assert out[1]["section"] == "Solid organs" and out[1]["sentence"] == "No liver lesion."
    assert "Uncomplicated appendicitis" in seen["user_prompt"]
