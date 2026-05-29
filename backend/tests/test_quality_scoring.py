"""Unit tests for the quality scoring engine (no external DB; judge mocked)."""
from rapid_reports_ai.quality_scoring import compute_edit_burden


def test_edit_burden_zero_when_identical():
    assert compute_edit_burden("LUNGS: clear.", "LUNGS: clear.") == 0.0


def test_edit_burden_one_when_no_overlap():
    assert compute_edit_burden("aaaa", "bbbb") == 1.0


def test_edit_burden_none_when_no_final():
    assert compute_edit_burden("anything", None) is None
    assert compute_edit_burden("anything", "") is None


def test_edit_burden_partial_between_0_and_1():
    v = compute_edit_burden("the quick brown fox", "the slow brown fox")
    assert v is not None
    assert 0.0 < v < 1.0
