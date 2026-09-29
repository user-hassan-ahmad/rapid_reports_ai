from __future__ import annotations

from rapid_reports_ai.scripts.asr_bakeoff import critical_mask, normalise, oracle, score


def test_normalise_makes_engines_comparable():
    assert normalise("The para-aortic node measures 23mm, previously 31 millimetres.") == \
        ["the", "para", "aortic", "node", "measures", "23", "mm", "previously", "31", "mm"]
    assert normalise("14 centimeters") == ["14", "cm"]


def test_critical_words_are_numbers_units_sides_negations_and_clinical_terms():
    ref = normalise("No left pleural effusion measuring 9 mm in the lung.")
    crit = critical_mask(ref)
    assert [w for w, c in zip(ref, crit) if c] == ["no", "left", "pleural", "effusion", "9", "mm", "lung"]


def test_score_counts_errors_and_critical_errors():
    ref = normalise("The node measures 23 mm on the left.")
    hyp = normalise("The node measures 33 mm on the right side.")
    s = score(ref, hyp)
    assert s["critical_errors"] == 2  # 23 → 33, left → right
    assert s["insertions"] == 1 and s["critical_inserted"] == 0
    assert round(s["wer"], 2) == round(3 / 8, 2)


def test_a_hallucinated_number_is_a_critical_insertion():
    s = score(normalise("No effusion."), normalise("No effusion 5 mm."))
    assert s["critical_inserted"] == 2 and s["critical_errors"] == 0


def test_oracle_counts_where_two_engines_agree_and_who_is_right_when_they_do_not():
    ref = normalise("No left pleural effusion measuring 9 mm")
    a = normalise("No left pleural effusion measuring 5 mm")
    b = normalise("No right pleural effusion measuring 9 mm")
    o = oracle(ref, a, b)
    assert o["both_right"] == 4 and o["only_a"] == 1 and o["only_b"] == 1 and o["both_wrong"] == 0
