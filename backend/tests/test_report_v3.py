"""Guards for the v3 parallel pipeline."""
from __future__ import annotations

import re

from rapid_reports_ai import report_v3_policy as pol


def _flat(text: str) -> str:
    """Prose assertions normalise whitespace; the prompt is hard-wrapped and a
    phrase may straddle a newline. Strings the model must emit *verbatim* are
    asserted against the raw text instead — see the COMPARISON test below."""
    return " ".join(text.split())


def test_policy_core_carries_the_calibrated_lexicon():
    flat = _flat(pol.POLICY_CORE)
    for phrase in ("diagnostic of", "probable", "may represent", "unlikely",
                   "not proof of absence"):
        assert phrase in flat, f"lexicon row missing: {phrase}"
    assert "not fully characterised" in flat       # qualifier preservation, L-30 defect


def test_policy_core_bans_only_hedging_that_defers_without_resolving():
    flat = _flat(pol.POLICY_CORE)
    assert "cannot be excluded" in flat
    assert "clinical correlation recommended" in flat
    # Removed by review: standard NHS usage, and the surveillance requirement is
    # stated positively under COMPARISON rather than as a ban.
    assert "no significant abnormalit" not in flat.lower()
    assert '"stable" for a measurable lesion' not in flat


def test_policy_core_derives_scope_rather_than_listing_forbidden_words():
    """L-28: a blocklist only catches what someone already enumerated, and its
    silence reads as safety. Scope has to be reasoned from what the images
    contain and who is answerable, so the model can judge a case nobody listed."""
    flat = _flat(pol.POLICY_CORE)
    assert "the study contains only what it contains" in flat
    assert "not the clinician answerable for the patient" in flat
    assert "responsibility the reporting radiologist does not" in flat
    # the generative test the principle hands the model
    assert "does it report what the imaging establishes, or decide what someone " \
           "should do about it?" in flat
    assert "Naming the specialty that should review is the first" in flat


def test_policy_core_states_its_own_function_before_any_rule():
    """v1 opened with what the document is for. Rules land differently when the
    reader knows which layer they belong to."""
    flat = _flat(pol.POLICY_CORE)
    assert "This document defines how you write" in flat
    assert "nothing case-specific licenses breaking them" in flat


def test_policy_core_carries_the_v1_principles_that_transfer():
    """Eleven of v1's sixteen sections transfer once the referent changes. The
    first pass stripped content that was merely *phrased* with a sheet
    reference, which is a different thing from being coupled to one."""
    flat = _flat(pol.POLICY_CORE)
    # Data authority — the three-tier qualifier precedence
    assert "the dictated qualifier stands" in flat
    assert "derived only from an explicit threshold supplied with the case" in flat
    assert "never fabricate a threshold" in flat
    # Silence vs fabrication — why normal statements exist at all
    assert 'A radiologist does not dictate "no pleural effusion"' in flat
    assert "never write a meta-statement about what the dictation did not say" in flat.lower()
    # Negatives as a safety surface
    assert "patient safety error, not a style defect" in flat
    # Anti-hedging, restored from v1's Recommendations
    assert "state it and commit" in flat


def test_policy_report_carries_the_composition_rules_that_transfer():
    flat = _flat(pol.POLICY_REPORT)
    # Findings discipline, including the enforceable instances v1 named
    assert "Management inference, differential synthesis and symptom attribution" in flat
    assert '"as described above"' in flat
    assert '"apart from the described finding"' in flat
    # Consolidation
    assert "Do not consolidate across subsystem boundaries" in flat
    assert "Bilateral findings of the same type and severity" in flat
    # Impression as synthesis
    assert "not a sequential restatement of findings" in flat
    assert "State diagnoses, not re-descriptions" in flat
    # Consistency
    assert "never introduces a finding absent from the body" in flat


def test_policy_excludes_only_what_is_genuinely_sheet_coupled():
    """The five v1 sections that do not transfer, and why. Guards against a
    later pass quietly reinstating them along with the rest."""
    combined = _flat(pol.POLICY_CORE + pol.POLICY_REPORT)
    # Skill Sheet Internals — names header:/Structural Pattern
    assert "header:" not in combined
    # Conditional Style Application — CLINICAL HISTORY section formatting
    assert "61M" not in combined and "CLINICAL HISTORY" not in combined
    # Terminology Enforcement — no preferred/suppressed pairs exist in a v3 sheet
    assert "suppressed term" not in combined
    # Parameter Placeholders and Fixed Blocks — neither construct survives
    assert "placeholder" not in combined
    # And the one clause deliberately NOT restored: it contradicts the authority
    # rule and is a plausible mechanism for L-30's qualifier stripping.
    assert "interpret and reframe" not in combined


def test_policy_report_carries_the_incidental_threshold():
    """L-13: omitted incidentals were editorial discrimination, not defects.
    L-15 named inclusion/exclusion as the open lever, so the one explicit test
    v1 had for it must not be lost in the migration."""
    flat = _flat(pol.POLICY_REPORT)
    assert "requires an action, carries malignant potential" in flat
    assert "crosses a threshold" in flat
    assert "editorial judgement, not an omission" in flat


def test_policy_report_carries_sections_and_comparison_branches():
    flat = _flat(pol.POLICY_REPORT)
    assert "COMPARISON, TECHNIQUE, FINDINGS, IMPRESSION" in flat
    assert "on its own line, terminated by a colon" in flat
    assert "never inventing a scan type or a date" in flat

    # These two are emitted verbatim into reports, so they must sit unbroken in
    # the prompt — asserted against the raw text, not the normalised form.
    assert "No prior imaging available for comparison." in pol.POLICY_REPORT
    assert "Comparison made to previous imaging." in pol.POLICY_REPORT


def test_comparison_holds_no_measurements_and_interval_change_lives_in_findings():
    """Caught in review: the surveillance rule sat under COMPARISON and read as
    though measurements belonged there. COMPARISON names the prior study and its
    date; the numbers belong beside the lesion they describe."""
    flat = _flat(pol.POLICY_REPORT)
    assert "no findings, no measurements, no interval commentary" in flat
    assert "the numbers go in FINDINGS beside the lesion they describe" in flat
    assert 'never "stable" on its own' in flat


def test_banned_patterns_are_compiled_and_named():
    assert pol.BANNED_PATTERNS, "banned list must not be empty"
    for name, rx in pol.BANNED_PATTERNS:
        assert isinstance(name, str) and name
        assert isinstance(rx, re.Pattern)


def test_policy_names_no_sheet_fields():
    """The property the whole design rests on.

    GLOBAL_STYLE_GUIDE and QUICK_REPORT_HARDENING_PREAMBLE name v1 sheet fields
    directly, which is why a v2 sheet could never be dropped into the existing
    scaffolding and why v2 had to go self-contained. The v3 policy layer must
    stay grammar-agnostic or the same trap closes again.
    """
    combined = pol.POLICY_CORE + pol.POLICY_REPORT

    # Multi-word field names are unambiguous, so match them case-insensitively.
    for phrase in ("style exemplar", "impression exemplar", "canonical line",
                   "mandatory negative", "fixed block", "skill sheet",
                   "conditional suppression", "structural pattern"):
        assert phrase not in combined.lower(), (
            f"policy names a sheet field: {phrase!r} — the layer must stay "
            f"sheet-agnostic so the grammar can change beneath it"
        )

    # Field tokens are ALL CAPS in the grammar, so match case-sensitively and on
    # word boundaries. A substring test would fire on ordinary prose — "expected"
    # contains "expect", "bearing on the question" contains "bearing".
    for token in ("T-NEG", "T-IND", "OBLIGATIONS", "EXPECT", "BEARING",
                  "VERDICT", "FLOW", "SUPPRESS-IF-HISTORY", "UNASSESSABLE-IF"):
        assert not re.search(rf"\b{re.escape(token)}\b", combined), (
            f"policy names a sheet field: {token!r} — the layer must stay "
            f"sheet-agnostic so the grammar can change beneath it"
        )
