"""derive_action is the shadow-mode ground truth. It is a heuristic, so it is pinned
by tables rather than trusted."""
from __future__ import annotations

import pytest

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS
from rapid_reports_ai.dictation_triage_labels import AGREEMENT_MAP, agrees, derive_action

A = "- 6 mm nodule right upper lobe\n- no pleural effusion"


@pytest.mark.parametrize(
    "before, after, edits, expected",
    [
        (A, A, [], "noop"),
        (A, A + "\n", [], "noop"),  # trailing blank line
        (A, "- 6 MM  nodule right upper lobe\n- no pleural effusion", [], "noop"),  # case + spacing
        ("- no pleural effusion\n- 6 mm nodule right upper lobe", A, [], "noop"),  # reordered
        (A, A + "\n- no pneumothorax", [], "append"),
        ("", "- lungs clear", [], "append"),
        (A, "- 6 mm nodule right upper lobe", [], "delete"),
        (A, "", [], "delete"),
        (A, "- 6 mm nodule left upper lobe\n- no pleural effusion", [], "correct"),
        (A, "- 6 mm nodule right upper lobe\n- small pleural effusion", [], "correct"),
        (A, A, [("- 12 mm lesion", "- 14 mm lesion")], "committed_edit"),
        (A, A + "\n- x", [("a", "b")], "committed_edit"),  # edits win over append
    ],
)
def test_derive_action_table(before, after, edits, expected):
    assert derive_action(before, after, edits) == expected


def test_agreement_map_covers_every_action():
    assert set(AGREEMENT_MAP) == set(TRIAGE_ACTIONS)
    for v in AGREEMENT_MAP.values():
        assert v  # non-empty


@pytest.mark.parametrize(
    "action, derived, expected",
    [
        ("append_new_finding", "append", True),
        ("append_new_finding", "correct", False),
        ("correct_previous_finding", "committed_edit", True),
        ("restate_existing_finding", "noop", True),
        ("formatting_command", "append", True),
        ("ignore_noise", "delete", False),
    ],
)
def test_agrees(action, derived, expected):
    assert agrees(action, derived) is expected
