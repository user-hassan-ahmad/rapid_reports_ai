from __future__ import annotations

from rapid_reports_ai.case_keyterms import filter_keyterms, keyterms_for_socket, merge_with_core
from rapid_reports_ai.deepgram_config import CORE_KEYTERMS, keyterm_tokens


def test_filter_drops_common_words_long_phrases_duplicates_and_punctuation():
    raw = ["adrenal glands", "Adrenal glands", "normal", "the liver", "hypodense", "subsegmental emboli.",
           "a very long four word phrase", "  paratracheal  ", "", "left", "Bosniak", "LI-RADS"]
    assert filter_keyterms(raw) == ["adrenal glands", "liver", "hypodense", "subsegmental emboli", "paratracheal",
                                    "Bosniak", "LI-RADS"]


def test_filter_caps_the_number_of_terms():
    assert len(filter_keyterms([f"term{i}x" for i in range(80)], cap=50)) == 50


def test_merge_puts_case_terms_first_then_core_within_the_token_budget():
    case = ["adrenal glands", "hypodense"]
    merged = merge_with_core(case, CORE_KEYTERMS, budget=60)
    assert merged[:2] == case
    assert keyterm_tokens(merged) <= 60
    assert len(set(merged)) == len(merged)


def test_merge_never_exceeds_deepgrams_limit():
    big = [f"alpha{i} beta{i} gamma{i}" for i in range(200)]
    assert keyterm_tokens(merge_with_core(big, CORE_KEYTERMS)) < 500


def test_socket_uses_case_terms_only_when_enabled():
    assert keyterms_for_socket(["hypodense", "normal"], enabled=False) is None  # core list, as before
    terms = keyterms_for_socket(["hypodense", "normal"], enabled=True)
    assert terms[0] == "hypodense" and "normal" not in terms and "spiculated" in terms
    assert keyterms_for_socket([], enabled=True) is None


def test_the_socket_list_stays_within_deepgrams_advised_50_terms():
    terms = keyterms_for_socket([f"term{i}x" for i in range(45)], enabled=True)
    assert len(terms) == 50 and terms[:45] == [f"term{i}x" for i in range(45)]


def test_the_prompt_asks_for_descriptors_and_likely_findings():
    from rapid_reports_ai.case_keyterms import KEYTERM_SYSTEM_PROMPT
    assert "descriptors" in KEYTERM_SYSTEM_PROMPT and "likely findings" in KEYTERM_SYSTEM_PROMPT
