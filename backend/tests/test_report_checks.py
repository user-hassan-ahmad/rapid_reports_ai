"""Version-agnostic report defect checks."""
from __future__ import annotations

from rapid_reports_ai.scripts.sheet_budget import report_checks as rc

REPORT = """COMPARISON:
CT abdomen 12/02/2026.

TECHNIQUE:
CT thorax, abdomen and pelvis, portal venous phase.

FINDINGS:
The left adrenal shows nodular thickening measuring 24 mm.
The liver is unremarkable.

IMPRESSION:
Left adrenal nodule; endocrine review recommended.
"""


def test_sections_splits_on_uppercase_colon_headers():
    s = rc.sections(REPORT)
    assert set(s) == {"COMPARISON", "TECHNIQUE", "FINDINGS", "IMPRESSION"}
    assert s["TECHNIQUE"] == "CT thorax, abdomen and pelvis, portal venous phase."
    assert "nodular thickening" in s["FINDINGS"]
    assert "endocrine review" in s["IMPRESSION"]


def test_sections_ignores_uppercase_words_inside_prose():
    """A header is uppercase, colon-terminated and alone on its line — that is
    the format contract. Anything else is prose and must not split the report,
    or a sentence mentioning CT or MRI silently truncates the section."""
    s = rc.sections("FINDINGS:\nThe CT shows no MRI correlate.\n")
    assert set(s) == {"FINDINGS"}


def test_sections_survives_a_malformed_report():
    """The checks run on generator output, including output that broke the
    format contract. A splitter that raises would take the whole gate with it,
    and a malformed report is exactly when the gate matters most."""
    assert rc.sections("") == {}
    assert rc.sections("No headers at all, just prose.") == {}
    # content on the header line violates the contract, so it is not a header
    assert rc.sections("FINDINGS: normal study.") == {}
    # a header with an empty body still exists, and reads as empty
    assert rc.sections("FINDINGS:\n") == {"FINDINGS": ""}


def test_sections_tolerates_trailing_whitespace_after_the_colon():
    """Models emit trailing spaces. That is not a contract violation worth
    losing a section over — layout_ok covers the real layout question."""
    s = rc.sections("FINDINGS:   \nNormal.\n\nIMPRESSION:\t\nNormal study.\n")
    assert set(s) == {"FINDINGS", "IMPRESSION"}
    assert s["IMPRESSION"] == "Normal study."


def test_compartment_blocks_stay_inside_findings():
    """Found by running the splitter over 223 real reports: ten render
    compartment blocks as headers. Promoting those to top-level sections leaves
    FINDINGS holding only the text before the first compartment, so every
    closure check compares the impression against a near-empty body and flags
    every multi-region report. Silent corruption of exactly the kind the ledger
    method note warns about."""
    report = (
        "COMPARISON:\nNone available.\n\n"
        "TECHNIQUE:\nCT head, neck, chest, abdomen and pelvis.\n\n"
        "FINDINGS:\n"
        "HEAD:\nNo intracranial haemorrhage.\n\n"
        "CHEST:\nNo pneumothorax. The lungs are clear.\n\n"
        "ABDOMEN:\nThe liver measures 18 cm.\n\n"
        "IMPRESSION:\nNo acute traumatic injury.\n"
    )
    s = rc.sections(report)
    assert set(s) == {"COMPARISON", "TECHNIQUE", "FINDINGS", "IMPRESSION"}
    # every compartment's content is reachable through FINDINGS
    for token in ("intracranial haemorrhage", "pneumothorax", "18 cm"):
        assert token in s["FINDINGS"], token


def test_layout_ok_fails_loudly_on_malformed_headers():
    """Two real failure modes, from 19 reports in the corpus — 17 in V2_FULL and
    2 in V2SMOKE, every one of them a v2-cell run and none from v1:

      15 emit `COMPARISON` with no colon at all
       4 emit `COMPARISON: None available.` — content on the header line

    Both break the format contract, which forbids content on the header line
    explicitly. sections() correctly recovers nothing from either. But a caller
    reading that as 'no defects' is L-28's silence-reads-as-safety one layer
    down, so the empty case gets its own signal. Note gate.py's
    REQUIRED_SECTIONS is a substring test and passes both forms.
    """
    colonless = (
        "COMPARISON\nNone available.\n\n"
        "TECHNIQUE\nNon-contrast CT head.\n\n"
        "FINDINGS\nNormal.\n\n"
        "IMPRESSION\nNormal study.\n"
    )
    inline = (
        "COMPARISON: None available.\n\n"
        "TECHNIQUE: Non-contrast CT head.\n\n"
        "FINDINGS: Normal.\n\n"
        "IMPRESSION: Normal study.\n"
    )
    for malformed in (colonless, inline):
        assert rc.sections(malformed) == {}
        assert rc.layout_ok(malformed) is False
    assert rc.layout_ok(REPORT) is True
