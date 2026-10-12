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
    _locate_flags,
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


# --- pure locating logic (_locate_flags) ------------------------------------


def test_issue_is_located_and_offsets_are_exact():
    issue = SemanticIssue(
        kind="laterality_conflict",
        quote="left ankle mortise",
        message="Findings mention both a right and a left ankle.",
    )
    flags = _locate_flags(FINDINGS, SemanticFindings(issues=[issue]))
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
    flags = _locate_flags(FINDINGS, SemanticFindings(issues=[issue]))
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
    assert _locate_flags(FINDINGS, SemanticFindings(issues=[issue])) == []


def test_last_occurrence_is_used_for_repeated_quotes():
    text = "- left ankle reviewed\n- oedema within the left ankle"
    issue = SemanticIssue(kind="laterality_conflict", quote="left ankle", message="m")
    f = _locate_flags(text, SemanticFindings(issues=[issue]))[0]
    assert text[f.start:f.end] == "left ankle"
    assert f.start == text.rfind("left ankle")


# --- async check_semantic behaviour (injected analyser) ---------------------


async def test_no_issues_returns_empty():
    assert await check_semantic("MRI ankle", "pain", FINDINGS, analyse=_fake([])) == []


async def test_located_flag_via_injected_analyser():
    issue = SemanticIssue(
        kind="laterality_conflict",
        quote="left ankle mortise",
        message="Findings mention both a right and a left ankle.",
    )
    flags = await check_semantic("MRI ankle", "", FINDINGS, analyse=_fake([issue]))
    assert len(flags) == 1
    assert FINDINGS[flags[0].start:flags[0].end] == "left ankle mortise"


async def test_blank_dictation_never_calls_the_model():
    called = []

    def _spy(scan_type, clinical_history, findings):
        called.append(1)
        return SemanticFindings(issues=[])

    assert await check_semantic("MRI ankle", "", "   \n ", analyse=_spy) == []
    assert called == []


async def test_model_failure_is_non_blocking():
    """A provider outage must not strand the radiologist or surface an error."""
    def _boom(scan_type, clinical_history, findings):
        raise RuntimeError("provider down")

    assert await check_semantic("MRI ankle", "", FINDINGS, analyse=_boom) == []


def test_issue_kinds_are_constrained():
    import pytest
    with pytest.raises(Exception):
        SemanticIssue(kind="not_a_real_kind", quote="x", message="m")


# --- the other half of a conflict (rendering both statements) ----------------

def test_other_quote_locates_the_conflicting_statement():
    issue = SemanticIssue(kind="laterality_conflict", quote="left ankle mortise",
                          other_quote="MRI of the right ankle", message="Side differs.")
    [f] = _locate_flags(FINDINGS, SemanticFindings(issues=[issue]))
    assert FINDINGS[f.start:f.end] == "left ankle mortise"
    assert FINDINGS[f.related_start:f.related_end] == "MRI of the right ankle"


def test_a_non_verbatim_other_quote_is_dropped_but_the_flag_kept():
    issue = SemanticIssue(kind="internal_contradiction", quote="left ankle mortise",
                          other_quote="MRI of the RIGHT ankle", message="x")
    [f] = _locate_flags(FINDINGS, SemanticFindings(issues=[issue]))
    assert f.related_start is None and f.related_end is None


def test_other_quote_is_optional():
    issue = SemanticIssue(kind="unit_anomaly", quote="joint effusion", message="x")
    [f] = _locate_flags(FINDINGS, SemanticFindings(issues=[issue]))
    assert f.related_start is None


# --- scratchpad fields: suggestion and blocking (severity stays medium for the banner) ---


def test_conflicts_block_in_the_scratchpad_but_stay_medium():
    issue = SemanticIssue(kind="laterality_conflict", quote="left ankle mortise", message="m")
    f = _locate_flags(FINDINGS, SemanticFindings(issues=[issue]))[0]
    assert f.blocking and f.severity == "medium" and f.suggestion == ""


def test_certain_garble_is_advisory_with_its_suggestion():
    text = "Upstream dilatation of the pancreatic duck."
    issue = SemanticIssue(kind="garbled_phrase", quote="duck", message="m", suggestion="duct", changes_meaning=False)
    f = _locate_flags(text, SemanticFindings(issues=[issue]))[0]
    assert not f.blocking and f.suggestion == "duct"


def test_ambiguous_garble_blocks_and_drops_any_suggestion():
    text = "The duct is dilated with a distal storm."
    issue = SemanticIssue(kind="garbled_phrase", quote="storm", message="m", suggestion="stricture", changes_meaning=True)
    f = _locate_flags(text, SemanticFindings(issues=[issue]))[0]
    assert f.blocking and f.suggestion == ""


def test_garble_with_no_suggestion_blocks():
    text = "A tiny non-2 mm calculus."
    issue = SemanticIssue(kind="garbled_phrase", quote="calculus", message="m", changes_meaning=False)
    assert _locate_flags(text, SemanticFindings(issues=[issue]))[0].blocking


def test_garble_on_a_number_or_side_always_blocks():
    text = "A tiny non-2 mm calculus in the left kidny."
    for quote in ("non-2 mm", "left kidny"):
        issue = SemanticIssue(kind="garbled_phrase", quote=quote, message="m", suggestion="x", changes_meaning=False)
        assert _locate_flags(text, SemanticFindings(issues=[issue]))[0].blocking


def test_type_alias_and_missing_message_are_accepted():
    issue = SemanticIssue.model_validate({"type": "garbled_phrase", "quote": "duck", "suggestion": "duct"})
    assert issue.kind == "garbled_phrase" and issue.message == ""


def test_a_garble_on_a_number_never_carries_a_suggestion():
    text = "Non 4 mm calculus in the right kidney."
    issue = SemanticIssue(kind="garbled_phrase", quote="Non 4 mm calculus", message="m", suggestion="No 4 mm calculus",
                          changes_meaning=False)
    f = _locate_flags(text, SemanticFindings(issues=[issue]))[0]
    assert f.blocking and f.suggestion == ""


def test_message_is_required_in_the_schema_but_tolerated_when_missing():
    assert "message" in SemanticIssue.model_json_schema()["required"]
    assert SemanticIssue.model_validate({"kind": "garbled_phrase", "quote": "x"}).message == ""


def test_a_conflict_suggestion_corrects_the_statement_the_dictation_outvotes():
    text = "A 4 mm calculus in the right kidney. No right hydronephrosis. Conclusion: incidental left renal calculus."
    issue = SemanticIssue(kind="laterality_conflict", quote="incidental left renal calculus.", other_quote="A 4 mm calculus in the right kidney.",
                          message="m", suggestion="incidental right renal calculus", suggestion_for="quote")
    f = _locate_flags(text, SemanticFindings(issues=[issue]), "Right flank pain.")[0]
    assert f.suggestion == "incidental right renal calculus." and f.suggestion_for == "quote" and f.blocking


def test_a_one_against_one_conflict_gets_no_suggestion():
    text = "Small left pleural effusion. Conclusion: small right pleural effusion."
    issue = SemanticIssue(kind="laterality_conflict", quote="small right pleural effusion.", other_quote="Small left pleural effusion.",
                          message="m", suggestion="small left pleural effusion.", suggestion_for="quote")
    assert _locate_flags(text, SemanticFindings(issues=[issue]), "Breathless.")[0].suggestion == ""


def test_a_conflict_suggestion_never_brings_a_new_value():
    text = "The spleen measures 14 cm. Conclusion: splenomegaly."
    issue = SemanticIssue(kind="measurement_mismatch", quote="The spleen measures 14 cm.", message="m",
                          suggestion="The spleen measures 16 cm.", suggestion_for="quote")
    assert _locate_flags(text, SemanticFindings(issues=[issue]))[0].suggestion == ""


def test_the_other_statement_can_be_the_one_corrected():
    text = "Moderate hydronephrosis of the left kidney. The left ureter is dilated. Conclusion: right hydronephrosis."
    issue = SemanticIssue(kind="laterality_conflict", quote="Conclusion: right hydronephrosis.", other_quote="Moderate hydronephrosis of the left kidney.",
                          message="m", suggestion="Conclusion: left hydronephrosis.", suggestion_for="quote")
    f = _locate_flags(text, SemanticFindings(issues=[issue]))[0]
    assert f.suggestion == "Conclusion: left hydronephrosis."
    flipped = SemanticIssue(kind="laterality_conflict", quote="Conclusion: right hydronephrosis.", other_quote="Moderate hydronephrosis of the left kidney.",
                            message="m", suggestion="Moderate hydronephrosis of the right kidney.", suggestion_for="other_quote")
    assert _locate_flags(text, SemanticFindings(issues=[flipped]))[0].suggestion == ""   # left is outvoted 2:1 the other way
