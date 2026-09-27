from __future__ import annotations

import pytest

from rapid_reports_ai.spoken_format import (
    apply_spoken_format,
    heading_only,
    resolve_colon,
    starts_paragraph,
)


# --- unambiguous spoken punctuation ------------------------------------------------------

@pytest.mark.parametrize("spoken, written", [
    ("benign and slash or degenerative", "benign and/or degenerative"),
    ("mild comma diffuse thickening", "mild, diffuse thickening"),
    ("no effusion semicolon no consolidation", "no effusion; no consolidation"),
    ("well hyphen defined margins", "well-defined margins"),
    ("the lesion open bracket arrow close bracket enhances", "the lesion (arrow) enhances"),
    ("is this new question mark", "is this new?"),
    ("Comma, then text", ", then text"),  # Deepgram's own comma after a spoken one is not doubled
])
def test_unambiguous_spoken_punctuation(spoken, written):
    assert apply_spoken_format(spoken) == written


def test_words_that_merely_contain_the_punctuation_words_are_untouched():
    s = "slashed tyres, commas, the semicolonic sign, hyphenated names"
    assert apply_spoken_format(s) == s


# --- spine levels -------------------------------------------------------------------------

@pytest.mark.parametrize("spoken, written", [
    ("L3 slash four There is mild disc desiccation", "L3/4 There is mild disc desiccation"),
    ("L3four", "L3/4"),            # Deepgram's formatter drops 'slash' and glues the number on
    ("L4five there is a bulge", "L4/5 there is a bulge"),
    ("L4-five there is a broad disc", "L4/5 there is a broad disc"),
    ("L4-5", "L4/5"),
    ("L4 slash 5", "L4/5"),
    ("C5 slash six", "C5/6"),
    ("T11-12", "T11/12"),
    ("L5 S1", "L5/S1"),
    ("L5-S1 left", "L5/S1 left"),
    ("C7 T1", "C7/T1"),
    ("T12 slash L1", "T12/L1"),
    ("l5 s1", "L5/S1"),
])
def test_spine_levels(spoken, written):
    assert apply_spoken_format(spoken) == written


@pytest.mark.parametrize("s", [
    "The conus terminates at L1 with normal signal.",
    "fractures of T4-6",           # a range, not a disc level: not adjacent
    "L4 5 mm disc bulge",          # bare space + number: could be a measurement
    "L3 and L4 vertebral bodies",
    "L5 S2 segment",               # not a junction
])
def test_spine_lookalikes_are_untouched(s):
    assert apply_spoken_format(s) == s


# --- colon: punctuation or organ, from context -------------------------------------------

@pytest.mark.parametrize("text, preceding, resolved", [
    ("Conclusion colon acute appendicitis", "", "Conclusion: acute appendicitis"),
    ("Conclusion, colon, acute appendicitis", "", "Conclusion: acute appendicitis"),
    ("L5/S1 colon there is a left paracentral extrusion", "", "L5/S1: there is a left paracentral extrusion"),
    ("Impression colon", "", "Impression:"),
    ("colon there is mild desiccation", "Normal marrow.\n\nL3/4", ": there is mild desiccation"),
    ("The sigmoid colon is unremarkable", "", "The sigmoid colon is unremarkable"),
    ("thickening of the transverse colon.", "", "thickening of the transverse colon."),
    ("colon wall is thickened", "The appendix is normal. The", "colon wall is thickened"),
])
def test_resolve_colon(text, preceding, resolved):
    out, ambiguous = resolve_colon(text, preceding)
    assert (out, ambiguous) == (resolved, False)


def test_a_colon_with_no_telling_context_is_ambiguous():
    out, ambiguous = resolve_colon("Colon, mild diffuse thickening", "The appendix is normal.")
    assert ambiguous is True and out == "Colon, mild diffuse thickening"


# --- structure: what starts a paragraph ---------------------------------------------------

@pytest.mark.parametrize("text", [
    "L3/4 There is mild disc desiccation", "L5/S1: left paracentral extrusion", "Conclusion: acute appendicitis",
    "Impression.", "Findings:",
])
def test_disc_levels_and_headings_start_a_paragraph(text):
    assert starts_paragraph(text) is True


@pytest.mark.parametrize("text", [
    "The conus terminates at L1.", "L1 vertebral body is normal", "Conclusions were discussed", "left S1 nerve root",
])
def test_other_text_does_not(text):
    assert starts_paragraph(text) is False


@pytest.mark.parametrize("text, heading", [
    ("Conclusion.", "Conclusion:"), ("conclusion", "Conclusion:"), ("Impression:", "Impression:"),
    ("Conclusion, colon,", "Conclusion:"), ("Findings", "Findings:"),
])
def test_heading_only_utterances(text, heading):
    assert heading_only(text) == heading


def test_not_heading_only():
    assert heading_only("Conclusion: acute appendicitis") is None
    assert heading_only("The findings are") is None


def test_apply_spoken_format_is_idempotent():
    # it runs at the websocket and again in cleaning
    for s in ["L3 slash four and slash or", "L5 S1, mild comma diffuse", "open bracket x close bracket"]:
        once = apply_spoken_format(s)
        assert apply_spoken_format(once) == once


@pytest.mark.parametrize("text, cased", [
    ("L4/5 there is a broad based disc bulge", "L4/5 There is a broad based disc bulge"),
    ("L5/S1: left paracentral extrusion", "L5/S1: Left paracentral extrusion"),
    ("Conclusion: acute appendicitis", "Conclusion: Acute appendicitis"),
    ("L3/4 mild desiccation", "L3/4 Mild desiccation"),
    ("The conus terminates at L1 with normal signal.", "The conus terminates at L1 with normal signal."),
    ("L4/5 5 mm bulge", "L4/5 5 mm bulge"),
])
def test_capital_after_a_leading_level_or_heading(text, cased):
    from rapid_reports_ai.spoken_format import capitalise_after_label
    assert capitalise_after_label(text) == cased
