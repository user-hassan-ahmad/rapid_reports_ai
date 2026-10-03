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
