"""Unit tests for the quality scoring engine (no external DB; judge mocked)."""
from rapid_reports_ai.quality_scoring import (
    compute_edit_burden,
    JudgeScore,
    DIMENSIONS,
)


def test_quality_judge_resolves_to_a_provider():
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, _get_model_provider
    model = MODEL_CONFIG["QUALITY_JUDGE"]
    assert _get_model_provider(model) == "anthropic"


def test_dimensions_are_the_three_rubric_columns():
    assert DIMENSIONS == ("sheet_fit", "output_adherence", "input_faithfulness")


def test_judge_score_enforces_1_to_5():
    import pytest
    JudgeScore(score=5, rationale="ok")
    with pytest.raises(Exception):
        JudgeScore(score=6, rationale="too high")


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
