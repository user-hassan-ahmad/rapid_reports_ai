"""Rename, move, remove and add a paragraph or a section (spec Flow 2, layout; plan decision 7)."""
import pytest

from rapid_reports_ai import chat_router_edits as E
from rapid_reports_ai import chat_router_layout as lay
from rapid_reports_ai import chat_router_sheet as sh
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import ROUTER_SHEET


def _undo(sheet, inverse):
    for op in reversed(inverse):
        sheet, _ = E.apply_op(sheet, op)
    return sheet


def _order(sheet):
    st = tsg.parse_sheet(sheet, mode="template").structure
    return [s.name for s in sorted(st.sections, key=lambda s: s.order)]


def test_rename_paragraph_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "rename_paragraph", "paragraph": "upper", "to": "Top"})
    assert "## Paragraph: Top (FINDINGS)" in out and _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "rename_paragraph", "paragraph": "Upper", "to": "Lower"})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "rename_paragraph", "paragraph": "Upper", "to": "Bad (name)"})


def test_move_paragraph_within_its_section_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "move_paragraph", "paragraph": "Lower", "before": "Upper"})
    assert [n for n, _ in sh.paragraphs(out)] == ["Technique", "Lower", "Upper", "Impression"]
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "move_paragraph", "paragraph": "Lower", "before": "Technique"})


def test_remove_paragraph_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "remove_paragraph", "paragraph": "Lower"})
    assert "Gamma is normal." not in out and _undo(out, inv) == ROUTER_SHEET


def test_add_paragraph_needs_covers_in_findings_and_undoes():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "add_paragraph", "name": "Middle", "section": "Findings",
                                         "covers": ["delta"]})
    assert [n for n, _ in sh.paragraphs(out)] == ["Technique", "Upper", "Lower", "Middle", "Impression"]
    assert 'COVERS ["delta"]' in out and _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "add_paragraph", "name": "Middle", "section": "FINDINGS", "covers": []})


def test_rename_section_by_name_or_printed_heading_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "rename_section", "section": "Findings:", "header": "Results:"})
    assert 'SECTION FINDINGS | header: "Results:" | role: findings' in out and _undo(out, inv) == ROUTER_SHEET


def test_move_section_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "move_section", "section": "technique", "after": "findings"})
    assert _order(out) == ["FINDINGS", "TECHNIQUE", "IMPRESSION"] and _undo(out, inv) == ROUTER_SHEET


def test_remove_section_takes_its_paragraphs_and_undoes():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "remove_section", "section": "Technique"})
    assert "SECTION TECHNIQUE" not in out and "Axial images were acquired." not in out
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "remove_section", "section": "IMPRESSION"})


def test_add_section_with_its_paragraph_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "add_section", "name": "Comparison", "header": "Comparison:",
                                         "role": "comparison", "after": "Technique"})
    assert _order(out) == ["TECHNIQUE", "COMPARISON", "FINDINGS", "IMPRESSION"]
    assert [n for n, _ in sh.paragraphs(out)][:2] == ["Technique", "Comparison"]
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "add_section", "name": "Other", "header": "", "role": "nonsense"})


def test_section_name_resolves_a_printed_heading():
    assert lay.section_name(ROUTER_SHEET, "Impression:") == "IMPRESSION"
