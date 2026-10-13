"""Code edits of one unit line (decision 6), each lint-guarded, each with an inverse that restores the sheet."""
import pytest

from rapid_reports_ai import chat_router_edits as E
from tests.template_sheet_fixtures import ROUTER_SHEET


def _undo(sheet, inverse):
    for op in reversed(inverse):
        sheet, _ = E.apply_op(sheet, op)
    return sheet


def test_fixed_reword_changes_one_line_and_undoes():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "fixed_reword", "line": "axial images were acquired",
                                         "text": "Axial and coronal images were acquired."})
    assert 'FIXED "Axial and coronal images were acquired."' in out and 'FIXED "Axial images' not in out
    assert _undo(out, inv) == ROUTER_SHEET


def test_fixed_add_goes_after_the_paragraphs_last_unit():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "technique",
                                         "text": "Images were reviewed in three planes."})
    lines = out.splitlines()
    assert lines[lines.index('FIXED "No previous imaging available."') + 1] == 'FIXED "Images were reviewed in three planes."'
    assert _undo(out, inv) == ROUTER_SHEET


def test_fixed_add_refuses_a_duplicate_and_an_unknown_paragraph():
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "Technique", "text": "No previous imaging available"})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "Nowhere", "text": "A sentence."})


def test_normal_add_extends_covers_and_undoes_in_order():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "normal_add", "paragraph": "Lower", "structure": "delta",
                                         "text": "Delta is normal."})
    assert 'COVERS ["gamma" | "delta"]' in out and 'NORMAL [delta] "Delta is normal."' in out
    assert _undo(out, inv) == ROUTER_SHEET
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "normal_add", "paragraph": "Lower", "structure": "gamma", "text": "x."})


def test_negative_add_and_undo():
    out, inv = E.apply_op(ROUTER_SHEET, {"op": "negative_add", "paragraph": "Upper", "text": "No beta collection."})
    assert 'NEGATIVE "No beta collection."' in out
    assert _undo(out, inv) == ROUTER_SHEET


def test_wording_with_quotes_or_slots_is_refused():
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "paragraph": "Technique", "text": 'Say "this".'})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "negative_add", "paragraph": "Upper", "text": "No {x}."})


def test_the_guard_refuses_an_edit_that_adds_a_lint_error():
    with pytest.raises(E.EditError):
        E.guarded(ROUTER_SHEET, ROUTER_SHEET + 'NORMAL [x] "unclosed\n')


def test_unknown_ops_and_bad_arguments_are_edit_errors():
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "rewrite_everything"})
    with pytest.raises(E.EditError):
        E.apply_op(ROUTER_SHEET, {"op": "fixed_add", "nonsense": 1})
