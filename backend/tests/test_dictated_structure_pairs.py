"""Structure-name check pairing (spec 2026-10-17 §3.1): dictated chain -> FINDINGS sentences. SYNTHETIC."""
import pytest

from rapid_reports_ai.dictated_number_check import Pair, findings_only, pairs, sentence_spans, strip_prefix


def P(report, *sources, removed=()):
    return [(p.dictated, p.report, p.chain) for p in pairs(report, list(sources), removed)]


def S(text):
    return [text[s:e].strip() for s, e in sentence_spans(text)]


# --- sentences (this check's own splitter) ---

def test_an_abbreviation_or_a_decimal_does_not_end_a_sentence():
    assert S("Cyst approx. 4 cm in segment 6, e.g. simple. Duct 6.5 mm vs. 5 mm before. Spleen 11 cm.") == [
        "Cyst approx. 4 cm in segment 6, e.g. simple.", "Duct 6.5 mm vs. 5 mm before.", "Spleen 11 cm."]


@pytest.mark.parametrize("text, first", [
    ("Stanford type A. Aortic root 4.1 cm.", "Stanford type A."),
    ("Cyst in segment I. Spleen 11 cm.", "Cyst in segment I."),
    ("Bosniak category I. Cyst 2 cm.", "Bosniak category I."),
    ("History of hepatitis B. Liver 15 cm.", "History of hepatitis B."),
])
def test_a_single_letter_before_a_full_stop_ends_the_sentence(text, first):
    assert S(text)[0] == first and len(S(text)) == 2


def test_label_and_bullet_prefixes_are_stripped_unless_nothing_else_is_left():
    assert strip_prefix("AORTA: Aortic sinus 4.1 cm.") == "Aortic sinus 4.1 cm."
    assert strip_prefix("- Right kidney 11 cm.") == "Right kidney 11 cm."
    assert strip_prefix("**Liver:** Segment 6 cyst 2 cm.") == "Segment 6 cyst 2 cm."
    assert strip_prefix("LVEF: 45%.") == "LVEF: 45%."


# --- the impression cut ---

def test_the_impression_is_cut_from_its_heading_line():
    report = "FINDINGS\nAortic root 4.1 cm.\n\nConclusion: aortic sinus 4.1 cm.\n"
    assert findings_only(report) == "FINDINGS\nAortic root 4.1 cm.\n\n"
    assert findings_only("FINDINGS\nA 2 cm.\n**IMPRESSION**\nB 2 cm.") == "FINDINGS\nA 2 cm.\n"
    assert findings_only("FINDINGS\nA 2 cm.") == "FINDINGS\nA 2 cm."


def test_the_impression_ends_at_the_next_heading_line():
    assert findings_only("FINDINGS\nA 2 cm.\nIMPRESSION\nB 2 cm.\nCOMPARISON\nC 2 cm.") == \
        "FINDINGS\nA 2 cm.\nCOMPARISON\nC 2 cm."
    assert findings_only("FINDINGS\nA 2 cm.\nImpression: B 2 cm.\nComparison: C 2 cm.") == \
        "FINDINGS\nA 2 cm.\nComparison: C 2 cm."


def test_a_sentence_starting_with_the_word_impression_is_not_a_heading():
    report = "FINDINGS\nImpression of mild thickening 4 mm.\nSpleen 11 cm."
    assert findings_only(report) == report


# --- pairs ---

def test_a_single_pair_keeps_the_report_line_label():
    assert P("FINDINGS\nAORTA: Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.") == [
        ("Aortic sinus 4.1 cm.", "AORTA: Aortic root 4.1 cm.", "4.1 cm")]


def test_a_value_in_two_findings_sentences_gives_two_pairs_and_the_impression_none():
    report = "FINDINGS\nThe right kidney is 11 cm. Renal length 11 cm on the right.\n\nIMPRESSION\nRight kidney 11 cm."
    assert [r for _, r, _ in P(report, "Right kidney 11 cm.")] == ["The right kidney is 11 cm.",
                                                                   "Renal length 11 cm on the right."]


def test_a_chain_is_paired_once_and_needs_all_its_values():
    assert P("Cyst 2.3 x 1.8 cm in segment 6.", "Segment 6 cyst 2.3 x 1.8 cm.") == [
        ("Segment 6 cyst 2.3 x 1.8 cm.", "Cyst 2.3 x 1.8 cm in segment 6.", "2.3 x 1.8 cm")]
    assert P("Cyst 2.3 cm. Node 1.8 cm.", "Segment 6 cyst 2.3 x 1.8 cm.") == []


def test_one_report_value_said_to_cover_both_pairs_with_each_dictated_value():
    got = P("Both kidneys measure 11 cm.", "Right kidney 11 cm. Left kidney 11 cm.")
    assert got == [("Right kidney 11 cm.", "Both kidneys measure 11 cm.", "11 cm"),
                   ("Left kidney 11 cm.", "Both kidneys measure 11 cm.", "11 cm")]


def test_identical_pairs_from_two_sources_are_one():
    assert len(pairs("Spleen 13 cm.", ["Spleen 13 cm.", "Spleen 13 cm."])) == 1


def test_a_removed_sentence_and_a_unitless_value_are_not_paired():
    assert P("Spleen 13 cm. Ratio 0.4.", "Spleen 13 cm.", "Ratio 0.4.", removed=["spleen 13 cm"]) == []


def test_a_value_only_fragment_is_joined_to_the_sentence_before_it():
    got = P("The left ventricle is mildly impaired. LVEF 45%.", "Left ventricle mildly impaired, LVEF 45%.")
    assert got == [("Left ventricle mildly impaired, LVEF 45%.",
                    "The left ventricle is mildly impaired. LVEF 45%.", "45%")]


def test_pairs_come_in_report_order():
    got = pairs("Spleen 13 cm. Liver 18 cm.", ["Liver 18 cm.", "Spleen 13 cm."])
    assert [p.chain for p in got] == ["13 cm", "18 cm"]
    assert isinstance(got[0], Pair)


def test_never_raises_on_empty_input():
    assert pairs(None, [None, ""]) == []
