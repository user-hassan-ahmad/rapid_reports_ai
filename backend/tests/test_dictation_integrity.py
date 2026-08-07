"""Unit tests for the deterministic dictation integrity checks.

Pure function, no I/O. The corpus cases below are real:
- the truncation case is report 56f501c1 (CT lumbar, metastatic workup,
  quality_core 2.33) whose dictation ended '...osseous lesion in the'
- the benign-fragment cases are drawn from reports that scored 5.0 and must
  NOT flag, or the feature becomes noise.
"""
from __future__ import annotations

from rapid_reports_ai.dictation_integrity import IntegrityFlag, check_dictation


def test_clean_dictation_returns_no_flags():
    text = "- lungs are clear\n- no pleural effusion"
    assert check_dictation(text) == []


def test_truncation_mid_clause_is_flagged():
    """The real 56f501c1 failure: dictation cut off after a preposition."""
    text = (
        "- Comparison made to previous study dated 23/01/2026\n"
        "- There is a new destructive expansile osseous lesion in the"
    )
    flags = check_dictation(text)
    assert len(flags) == 1
    assert flags[0].kind == "truncation"
    assert flags[0].severity == "high"


def test_truncation_after_measuring_is_flagged():
    flags = check_dictation("There is a lesion measuring")
    assert len(flags) == 1
    assert flags[0].kind == "truncation"


def test_dangling_measurement_is_flagged():
    flags = check_dictation("Large high-density focus measuring up to 46 x")
    assert len(flags) == 1
    assert flags[0].kind == "dangling_measurement"
    assert flags[0].severity == "high"


def test_complete_measurement_is_not_flagged():
    text = "Focus measuring up to 46 x 36 mm axially and 29 mm CC"
    assert check_dictation(text) == []


def test_terminal_punctuation_suppresses_the_flag():
    """The TAVI 5.0 case contained the fragment 'The left lung.' — benign,
    because it terminates. Must not flag."""
    assert check_dictation("The left lung.") == []


def test_bullet_fragments_without_punctuation_do_not_flag():
    """Radiologists dictate in unpunctuated fragments. Precision matters more
    than recall here — a noisy check gets ignored."""
    text = (
        "- acute subdural haematoma along the right cerebral convexity\n"
        "- no skull vault fracture\n"
        "- age-related involutional change"
    )
    assert check_dictation(text) == []


def test_empty_and_whitespace_are_clean():
    assert check_dictation("") == []
    assert check_dictation("   \n  \n ") == []
    assert check_dictation(None) == []


def test_trailing_blank_lines_do_not_mask_truncation():
    flags = check_dictation("There is a mass in the\n\n   \n")
    assert len(flags) == 1
    assert flags[0].kind == "truncation"


def test_flag_carries_an_excerpt_for_the_ui():
    flags = check_dictation("There is a new destructive lesion in the")
    assert flags[0].excerpt
    assert flags[0].excerpt in "There is a new destructive lesion in the"


def test_flag_is_immutable():
    import pytest
    flag = IntegrityFlag(kind="truncation", severity="high", excerpt="x",
                         message="y", start=0, end=1)
    with pytest.raises(Exception):
        flag.kind = "other"


# --- Offsets ---------------------------------------------------------------
# The offsets are what let the editor decorate the exact dangling token rather
# than making the radiologist hunt for it. They must index the text EXACTLY as
# supplied, so slicing the original string by [start:end] returns the token.


def test_offsets_select_the_dangling_word():
    text = "- There is a new destructive expansile osseous lesion in the"
    flag = check_dictation(text)[0]
    assert text[flag.start:flag.end] == "the"


def test_offsets_are_correct_on_a_later_line():
    """Multi-line: offsets must account for every preceding line."""
    text = (
        "- Comparison made to previous study dated 23/01/2026\n"
        "- There is a new destructive expansile osseous lesion in the"
    )
    flag = check_dictation(text)[0]
    assert text[flag.start:flag.end] == "the"


def test_offsets_point_at_the_last_occurrence_not_the_first():
    """The whole reason for offsets over text-search: 'the' appears earlier."""
    text = "- the liver is normal\n- there is a mass in the"
    flag = check_dictation(text)[0]
    assert text[flag.start:flag.end] == "the"
    assert flag.start > text.index("the")  # not the first "the"


def test_offsets_survive_leading_whitespace_and_blank_lines():
    text = "\n\n   - there is a mass in the\n\n   \n"
    flag = check_dictation(text)[0]
    assert text[flag.start:flag.end] == "the"


def test_offsets_select_the_dangling_measurement():
    text = "Large high-density focus measuring up to 46 x"
    flag = check_dictation(text)[0]
    assert text[flag.start:flag.end].strip() == "46 x"
