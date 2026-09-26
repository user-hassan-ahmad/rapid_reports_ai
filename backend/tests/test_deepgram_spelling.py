from __future__ import annotations

from rapid_reports_ai.deepgram_spelling import UK_SPELLING, restore_sentence_case, uk_spelling_params


def test_find_terms_are_lowercase_single_words_and_actually_change():
    # Deepgram: the find term must be lowercase; the replacement is inserted as written
    for us, uk in UK_SPELLING.items():
        assert us == us.lower() and " " not in us and us != uk


def test_within_deepgrams_suggested_limit():
    assert 20 <= len(UK_SPELLING) <= 200


def test_hemi_prefix_words_are_never_touched():
    # hemidiaphragm, hemithorax: 'hemi' is half, not blood, and stays in UK spelling
    assert not any(us.startswith("hemi") for us in UK_SPELLING)


def test_params_are_repeated_replace_pairs():
    p = uk_spelling_params()
    assert p.startswith("replace=") and "&replace=" in p
    assert "replace=hematoma:haematoma" in p.split("&")
    assert p.count("replace=") == len(UK_SPELLING)


def test_restore_sentence_case_after_terminal_punctuation():
    # Deepgram's replace drops the capital a sentence-initial word had
    s = "There is an acute haematoma. haematoma measures 9 mm? oedema is mild! calibre normal."
    assert restore_sentence_case(s) == (
        "There is an acute haematoma. Haematoma measures 9 mm? Oedema is mild! Calibre normal."
    )


def test_restore_sentence_case_leaves_mid_sentence_and_other_words_alone():
    assert restore_sentence_case("with haematoma. the liver is normal") == "with haematoma. the liver is normal"
    assert restore_sentence_case("haematoma at the start of a final") == "haematoma at the start of a final"
