"""Unit tests for the semantic (LLM-backed) dictation checks.

The analyser is injected, so these run with no model call and no network. What
they pin down is the contract around the model, which is where the risk lives:
a language model will happily invent a span that isn't in the text, and a
hallucinated highlight pointing at the wrong words is worse than no highlight.
"""
from __future__ import annotations

from rapid_reports_ai.dictation_semantic import (
    SemanticIssue,
    SemanticFindings,
    check_semantic,
)


def _fake(issues):
    """Build an injectable analyser returning a fixed set of issues."""
    def _analyse(scan_type, clinical_history, findings):
        return SemanticFindings(issues=issues)
    return _analyse


FINDINGS = (
    "- MRI of the right ankle demonstrates a joint effusion.\n"
    "- There is oedema within the left ankle mortise."
)


def test_no_issues_returns_empty():
    assert check_semantic("MRI ankle", "pain", FINDINGS, analyse=_fake([])) == []


def test_issue_is_located_and_offsets_are_exact():
    issue = SemanticIssue(
        kind="laterality_conflict",
        quote="left ankle mortise",
        message="Findings mention both a right and a left ankle.",
    )
    flags = check_semantic("MRI ankle", "right ankle pain", FINDINGS, analyse=_fake([issue]))
    assert len(flags) == 1
    f = flags[0]
    assert FINDINGS[f.start:f.end] == "left ankle mortise"
    assert f.kind == "laterality_conflict"


def test_semantic_issues_are_advisory_not_gating():
    """Deterministic checks gate; model-judged ones only advise.

    A false positive from the model must never block a radiologist from
    generating — it should draw the eye and nothing more.
    """
    issue = SemanticIssue(kind="laterality_conflict", quote="left ankle mortise", message="m")
    flags = check_semantic("MRI ankle", "", FINDINGS, analyse=_fake([issue]))
    assert flags[0].severity == "medium"
    assert not any(f.severity == "high" for f in flags)


def test_hallucinated_span_is_dropped():
    """If the quote isn't verbatim in the dictation we cannot place it, so the
    flag is discarded rather than highlighting an approximate location."""
    issue = SemanticIssue(
        kind="internal_contradiction",
        quote="the spleen is enlarged",   # never appears in FINDINGS
        message="m",
    )
    assert check_semantic("MRI ankle", "", FINDINGS, analyse=_fake([issue])) == []


def test_last_occurrence_is_used_for_repeated_quotes():
    text = "- left ankle reviewed\n- oedema within the left ankle"
    issue = SemanticIssue(kind="laterality_conflict", quote="left ankle", message="m")
    f = check_semantic("MRI ankle", "", text, analyse=_fake([issue]))[0]
    assert text[f.start:f.end] == "left ankle"
    assert f.start == text.rfind("left ankle")


def test_blank_dictation_never_calls_the_model():
    called = []

    def _spy(scan_type, clinical_history, findings):
        called.append(1)
        return SemanticFindings(issues=[])

    assert check_semantic("MRI ankle", "", "   \n ", analyse=_spy) == []
    assert called == []


def test_model_failure_is_non_blocking():
    """A provider outage must not strand the radiologist or surface an error."""
    def _boom(scan_type, clinical_history, findings):
        raise RuntimeError("provider down")

    assert check_semantic("MRI ankle", "", FINDINGS, analyse=_boom) == []


def test_issue_kinds_are_constrained():
    import pytest
    with pytest.raises(Exception):
        SemanticIssue(kind="not_a_real_kind", quote="x", message="m")
