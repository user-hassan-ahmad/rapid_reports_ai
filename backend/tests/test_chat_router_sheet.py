"""Which sheet lines are code-owned units and which are prose the style call may edit."""
import pytest

from rapid_reports_ai import chat_router_sheet as sh
from tests.template_sheet_fixtures import ROUTER_SHEET


def test_walk_marks_units_headings_and_paragraphs():
    lines = sh.walk(ROUTER_SHEET)
    normal = next(l for l in lines if l.text.startswith("NORMAL [alpha]"))
    assert normal.keyword == "NORMAL" and normal.paragraph == "Upper" and normal.section == "FINDINGS"
    opening = next(l for l in lines if l.text.startswith("Opening: The paragraph"))
    assert opening.keyword == "" and opening.paragraph == "Upper"
    assert next(l for l in lines if l.text == "## Voice").keyword == "#"


def test_prose_blocks_skip_scan_context_and_blank_runs():
    blocks = sh.prose_blocks(ROUTER_SHEET)
    assert [(b.id, b.heading) for b in blocks] == [
        ("b1", "Voice"), ("b2", "Paragraph: Upper (FINDINGS)"), ("b3", "Paragraph: Impression (IMPRESSION)"),
        ("b4", "Impression Construction")]
    assert blocks[3].text == "Lead with the most important finding.\nKeep it brief."


def test_splice_replaces_a_block_and_keeps_every_unit_line():
    out = sh.splice(ROUTER_SHEET, {"b4": "Lead with the main finding in one sentence."})
    assert "Keep it brief." not in out and "Lead with the main finding in one sentence." in out
    assert sh.units_unchanged(ROUTER_SHEET, out) and out.endswith("\n")


def test_the_guard_catches_a_unit_line_written_into_prose():
    out = sh.splice(ROUTER_SHEET, {"b1": 'Sentences are short.\nNORMAL [alpha] "Alpha is fine."'})
    assert not sh.units_unchanged(ROUTER_SHEET, out)


def test_new_lines_lists_only_lines_that_were_not_there():
    assert sh.new_lines("A.\nB.", "A.\nC.\n\n b. ") == ["C."]


def test_scan_type_paragraphs_and_spans():
    assert sh.scan_type(ROUTER_SHEET) == "Router test"
    assert sh.paragraphs(ROUTER_SHEET) == [("Technique", "TECHNIQUE"), ("Upper", "FINDINGS"), ("Lower", "FINDINGS"),
                                           ("Impression", "IMPRESSION")]
    start, end = sh.paragraph_span(ROUTER_SHEET, "lower")
    assert ROUTER_SHEET.splitlines()[start] == "## Paragraph: Lower (FINDINGS)"
    assert ROUTER_SHEET.splitlines()[end] == "## Paragraph: Impression (IMPRESSION)"
    with pytest.raises(KeyError):
        sh.paragraph_span(ROUTER_SHEET, "nowhere")
    assert sh.quoted('FIXED "No previous imaging available."') == "No previous imaging available."
