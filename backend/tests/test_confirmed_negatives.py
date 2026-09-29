"""Policy 1 for confirmed branches (spec 2026-09-29-policy1-confirmed-branch-negatives-design)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_analyser as qa


def test_confirmed_negatives_is_an_opt_in_directive():
    model = "qwen-3.8-27b"
    prod = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES)
    arm_b = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES + ("confirmed_negatives",))
    assert "**If confirmed:**" not in prod
    assert "**If confirmed:**" in arm_b
    assert "(core | contextual)" in arm_b
    assert "confirmed_negatives" not in qa.PRODUCTION_DIRECTIVES


from rapid_reports_ai import quick_report_brief as qb

DIFFS = [
    "Acute subdural — crescentic hyperdensity *(visible on this technique: yes)*",
    "Epidural — biconvex hyperdensity *(visible on this technique: yes)*",
]
IF_CONFIRMED_LINES = [
    "- **If confirmed:** (negatives stated only when the dictation confirms the branch)",
    '  - Acute subdural → "No midline shift" (core)',
    '  - Acute subdural → "No uncal herniation" (contextual)',
    '  - Epidural -> "No skull fracture"',
    '  - Haemorrhagic contusion → "No contrecoup injury" (core)',
]


def test_candidates_parse_branch_negative_and_tag():
    cands, unmatched = qb.parse_confirmed(IF_CONFIRMED_LINES, DIFFS)
    assert [(c.branch, c.text, c.tag, c.diff_index) for c in cands] == [
        ("Acute subdural", "No midline shift", "core", 0),
        ("Acute subdural", "No uncal herniation", "contextual", 0),
        ("Epidural", "No skull fracture", "contextual", 1),   # missing tag -> contextual
    ]
    assert unmatched == 1                                     # no such differential


@pytest.mark.parametrize("label,present,tag,outcome", [
    ("keep", 0.3, "core", "dropped"),                # branch not confirmed
    ("contradicted", 0.95, "core", "dropped"),       # the dictation says otherwise
    ("expected", 0.95, "core", "do_not_assert"),     # the diagnosis causes it
    ("expected", 0.6, "contextual", "do_not_assert"),
    ("keep", 0.95, "core", "stated"),
    ("keep", 0.95, "contextual", "offered"),
    ("keep", 0.6, "core", "offered"),                # branch borderline
])
def test_route_confirmed_rule_c(label, present, tag, outcome):
    assert qb.route_confirmed(label, present, tag) == outcome
