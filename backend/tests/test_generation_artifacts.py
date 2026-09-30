from __future__ import annotations

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.generation_artifacts import GenerationArtifacts


def test_from_candidate_reads_either_pathway_record():
    rec = {"content": "FINDINGS:\nX.\n\nIMPRESSION:\nY.", "options": [{"id": "fn0", "section": "FINDINGS"}],
           "quality_check": {"enabled": True}, "brief": {"text": "t", "decisions": {"rules": []}},
           "sections": ["FINDINGS", "IMPRESSION"]}
    a = GenerationArtifacts.from_candidate(rec, "dictated X")
    assert a.report.startswith("FINDINGS") and a.dictated_findings == "dictated X"
    assert a.sections == ["FINDINGS", "IMPRESSION"] and a.brief == {"decisions": {"rules": []}}
    assert a.options[0]["id"] == "fn0"


def test_option_section_must_be_a_listed_section():
    rec = {"content": "", "options": [{"id": "fn0", "section": "NOPE"}], "sections": ["FINDINGS"]}
    assert GenerationArtifacts.from_candidate(rec, "").options == []


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
