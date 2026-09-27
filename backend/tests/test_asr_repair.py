from __future__ import annotations

import pytest

from rapid_reports_ai.asr_repair import apply_fix, build_lexicon, candidates, content_words, phonetic_key

CAP = ["LUNGS", "LIVER", "SPLEEN", "PANCREAS", "ADRENAL GLANDS", "KIDNEYS", "BOWEL", "LYMPH NODES"]


def test_content_words_skip_function_words_numbers_and_units():
    words = [w for w, _, _ in content_words("There is a 14 mm nodule in the right upper lobe, measuring 5 millimetres.")]
    assert words == ["nodule", "right", "upper", "lobe"]  # 'measuring' is a verb, not a finding


def test_content_words_are_capped():
    assert len(content_words(" ".join(f"word{i}x" for i in range(30)).replace("0", "a"), cap=12)) == 12


def test_phonetic_key_groups_sound_alikes():
    assert phonetic_key("scold") == phonetic_key("skold")
    assert phonetic_key("skull") == phonetic_key("scull")


def _best(utterance, flagged, checklist=CAP):
    cs = candidates(utterance, flagged, build_lexicon(checklist))
    return [(c.heard.lower(), c.replacement.lower()) for c in cs]


@pytest.mark.parametrize("utterance, flagged, heard, replacement", [
    # Jev flags the neighbour ('glands' scored lowest); the fix is to 'renal'
    ("The renal glands are also normal.", "glands", "renal", "adrenal"),
    ("The common bowel duct measures 15 millimetres.", "bowel", "bowel", "bile"),
    ("No varospinal soft tissue abnormality.", "varospinal", "varospinal", "paraspinal"),
    ("There is a left paracetamol disc extrusion.", "paracetamol", "paracetamol", "paracentral"),
    ("No scold vault fractures are identified.", "scold", "scold", "skull"),
    ("Further, supplemental emboli are seen in the lingula.", "supplemental", "supplemental", "subsegmental"),
    ("in keeping with chronic smooth vessel ischaemic change.", "smooth", "smooth", "small"),
])
def test_candidates_include_the_true_word(utterance, flagged, heard, replacement):
    assert (heard, replacement) in _best(utterance, flagged)


def test_no_candidate_is_a_mere_inflection_of_the_heard_word():
    for heard, repl in _best("The kidneys are normal.", "kidneys"):
        assert repl.rstrip("s") != heard.rstrip("s")


def test_apply_fix_keeps_capitals_and_the_rest_of_the_sentence():
    cs = candidates("The renal glands are also normal.", "glands", build_lexicon(CAP))
    c = next(c for c in cs if c.replacement.lower() == "adrenal")
    assert apply_fix("The renal glands are also normal.", c) == "The adrenal glands are also normal."
    cs = candidates("Varospinal soft tissues are normal.", "Varospinal", build_lexicon(CAP))
    c = next(c for c in cs if c.replacement.lower() == "paraspinal")
    assert apply_fix("Varospinal soft tissues are normal.", c) == "Paraspinal soft tissues are normal."


def test_windows_never_swallow_a_function_word():
    for heard, repl in _best("The renal glands are also normal.", "glands"):
        assert heard.split()[0] not in ("the", "are") and heard.split()[-1] not in ("the", "are")


def test_a_candidate_never_just_deletes_a_heard_word():
    L = build_lexicon(["LIVER"])
    for u, f in [("The liver contains a 14 millimetre high lesion.", "high"),
                 ("Incidental hypodense marginal in the thyroid.", "marginal")]:
        for c in candidates(u, f, L):
            assert not set(c.replacement.lower().split()) < set(c.heard.lower().split())


def test_a_merged_negation_is_offered():
    # 'There is no pleural effusion' came out as 'There is nipple effusion'
    assert ("nipple", "no pleural") in _best("There is nipple effusion.", "nipple", ["LUNGS", "PLEURA"])


def test_a_fix_never_reduces_the_number_of_words():
    L = build_lexicon(["LUNGS", "PLEURA", "ADRENAL GLANDS"])
    for u, f in [("The common bowel duct measures 15 mm.", "bowel"), ("No varospinal soft tissue abnormality.", "varospinal"),
                 ("Further, supplemental emboli are seen.", "supplemental"), ("The liver contains a 14 millimetre high lesion.", "high")]:
        for c in candidates(u, f, L):
            assert len(c.replacement.split()) >= len(c.heard.split()), (c.heard, c.replacement)


def test_a_fix_never_doubles_a_neighbouring_word():
    from rapid_reports_ai.asr_repair import apply_fix
    u = "The common bowel duct measures 15 mm."
    for c in candidates(u, "bowel", build_lexicon([])):
        fixed = apply_fix(u, c).lower().split()
        assert all(a != b for a, b in zip(fixed, fixed[1:])), apply_fix(u, c)
