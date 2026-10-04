import os

import pytest

from rapid_reports_ai.scripts.review_labs import clinical_pass as CP


def test_clinical_pass_decodes_string_lists_and_splits_items():
    out = CP.ClinicalPass(characterise='["Lesion :: enhancement not described"]', safety=[],
                          inconsistencies="Signal on CT :: MRI wording in a CT report",
                          urgency="routine", urgency_reason="")
    assert out.characterise == ["Lesion :: enhancement not described"]
    assert CP.split_item(out.inconsistencies[0]) == ("Signal on CT", "MRI wording in a CT report")
    assert CP.split_item("no separator") == ("", "no separator")


def test_clinical_pass_unsupported_decodes_string_list():
    out = CP.ClinicalPass(unsupported='["Compared with the prior study :: no prior study dictated"]',
                          urgency="routine")
    assert out.unsupported == ["Compared with the prior study :: no prior study dictated"]
    assert CP.ClinicalPass(urgency="routine").unsupported == []


def test_clinical_prompt_versions_load():
    assert CP.CLINICAL_PROMPT_VERSION == "clinical_pass_v1_1"
    new, old = CP.prompt(), CP.prompt("clinical_pass_v1")
    assert "unsupported" in new and "unsupported" not in old
    assert "Base the tier only on the findings as reported" in new


def test_clinical_run_uses_version():
    import asyncio

    class U:
        def model_dump(self):
            return {}

    seen = []

    async def fake(model, system, user, reasoning):
        seen.append(system)
        return CP.ClinicalPass(urgency="routine"), U()

    asyncio.run(CP.run({"report": "x"}, qwen_fn=fake))
    asyncio.run(CP.run({"report": "x"}, qwen_fn=fake, version="clinical_pass_v1"))
    assert seen == [CP.prompt(), CP.prompt("clinical_pass_v1")]
