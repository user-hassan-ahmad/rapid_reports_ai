from rapid_reports_ai.quality_scoring import zero_edit_rate


def test_zero_edit_rate_ignores_none_and_rounds():
    # 4 comparable (2 zero-edit) → 0.5; the None is excluded
    assert zero_edit_rate([0.0, 0.0, 0.2, None, 0.5]) == 0.5


def test_zero_edit_rate_all_none_is_none():
    assert zero_edit_rate([None, None]) is None


def test_zero_edit_rate_empty_is_none():
    assert zero_edit_rate([]) is None
