from __future__ import annotations

import pytest

from rapid_reports_ai.scripts.bakeoff_baselines import (
    baseline_boundary,
    baseline_coverage,
    baseline_triage,
    is_command,
)


@pytest.mark.parametrize("utt,expected", [
    ("Scratch that", "delete_previous_utterance"),
    ("remove the last sentence", "delete_previous_utterance"),
    ("new paragraph", "formatting_command"),
    ("next line please", "formatting_command"),
    ("full stop", "formatting_command"),
    ("actually the right side", "correct_previous_finding"),
    ("make that twelve millimetres", "correct_previous_finding"),
    ("severe not mild", "correct_previous_finding"),
    ("um er okay", "ignore_noise"),
    ("hang on a second", "ignore_noise"),
    ("small left pleural effusion", "append_new_finding"),
    ("the spleen is normal", "restate_existing_finding"),
])
def test_triage(utt, expected):
    assert baseline_triage("", "- spleen normal", utt) == expected


def test_triage_restate_uses_committed_too():
    assert baseline_triage("- 4 mm renal calculus", "", "renal calculus 4 mm") == "restate_existing_finding"
    assert baseline_triage("", "", "renal calculus 4 mm") == "append_new_finding"


@pytest.mark.parametrize("buffered,chunk,expected", [
    ("", "delete that", "command"),
    ("", "generate report", "command"),
    ("", "switch to verbatim mode", "command"),
    ("", "the", "continues"),
    ("there is a lesion", "in the", "continues"),
    ("", "measuring", "continues"),
    ("", "the pancreas is normal", "complete"),
    ("a cyst", "in the left kidney", "complete"),
])
def test_boundary(buffered, chunk, expected):
    assert baseline_boundary(buffered, chunk) == expected


def test_is_command_ignores_findings_that_mention_words():
    assert is_command("new line") and not is_command("new lesion in the liver")


def test_coverage_forms_bare_mentions_and_no_collectives():
    sections = ["LIVER", "KIDNEYS", "SPLEEN", "PANCREAS"]
    pad = "Hepatic steatosis.\nRenal cyst on the left.\n- Spleen\nThe solid organs are otherwise normal."
    assert baseline_coverage(pad, sections) == {"LIVER": 1.0, "KIDNEYS": 1.0, "SPLEEN": 0.0, "PANCREAS": 0.0}
    assert baseline_coverage("", ["LIVER"]) == {"LIVER": 0.0}
