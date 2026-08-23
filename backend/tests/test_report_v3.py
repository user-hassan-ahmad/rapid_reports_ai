"""Guards for the v3 parallel pipeline."""
from __future__ import annotations

import re

from rapid_reports_ai import report_v3_policy as pol


def _flat(text: str) -> str:
    """Prose assertions normalise whitespace; the prompt is hard-wrapped and a
    phrase may straddle a newline. Strings the model must emit *verbatim* are
    asserted against the raw text instead — see the COMPARISON test below."""
    return " ".join(text.split())


def test_policy_core_carries_lexicon_and_banned_prose():
    flat = _flat(pol.POLICY_CORE)
    for phrase in ("diagnostic of", "probable", "may represent", "unlikely",
                   "not proof of absence"):
        assert phrase in flat, f"lexicon row missing: {phrase}"
    assert "not fully characterised" in flat       # qualifier preservation, L-30 defect
    assert "cannot be excluded" in flat
    assert "no significant abnormality" in flat
    assert "physiotherapy" in flat                 # management trespass, L-24


def test_policy_report_carries_sections_and_comparison_branches():
    flat = _flat(pol.POLICY_REPORT)
    assert "COMPARISON, TECHNIQUE, FINDINGS, IMPRESSION" in flat
    assert "on its own line, terminated by a colon" in flat
    assert "never inventing a scan type or a date" in flat

    # These two are emitted verbatim into reports, so they must sit unbroken in
    # the prompt — asserted against the raw text, not the normalised form.
    assert "No prior imaging available for comparison." in pol.POLICY_REPORT
    assert "Comparison made to previous imaging." in pol.POLICY_REPORT


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
    for field in ("style exemplar", "impression exemplar", "canonical line",
                  "mandatory negative", "fixed block", "skill sheet",
                  "T-NEG", "T-IND", "OBLIGATION", "EXPECT", "BEARING",
                  "VERDICT", "FLOW"):
        assert field.lower() not in combined.lower(), (
            f"policy names a sheet field: {field!r} — the layer must stay "
            f"sheet-agnostic so the grammar can change beneath it"
        )
