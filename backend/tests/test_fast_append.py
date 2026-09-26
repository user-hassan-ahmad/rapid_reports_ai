from __future__ import annotations

import pytest

from rapid_reports_ai.dictation_triage import TriageDecision, TriageError
from rapid_reports_ai.fast_append import RouteResult, clean_verbatim, closes_line, route_bundle
from rapid_reports_ai.jev_questions import FAST_APPEND_BANDS
from rapid_reports_ai.utterance_bundle import BundleDecision


# --- clean_verbatim ---------------------------------------------------------------

@pytest.mark.parametrize("raw, clean", [
    ("No pleural effusion.", "No pleural effusion."),
    ("um no pleural effusion", "no pleural effusion"),
    ("There is, uh, a 5 mm nodule", "There is, a 5 mm nodule"),
    ("erm the liver er is normal", "the liver is normal"),
    ("Hmm. Ah, okay", "okay"),
    ("ER positive mass", "ER positive mass"),  # oestrogen receptor, not a filler
    ("5 mm and 3 mm", "5 mm and 3 mm"),  # millimetres, not a filler
    ("no effusion new line", "no effusion\n"),
    ("no effusion new paragraph", "no effusion\n\n"),
    ("no effusion full stop", "no effusion."),
    ("no effusion. full stop", "no effusion."),
    ("no effusion<\\n>", "no effusion\n"),
    ("  spaced   out  ", "spaced out"),
    ("um uh", ""),
])
def test_clean_verbatim(raw, clean):
    assert clean_verbatim(raw) == clean


def test_clean_verbatim_leaves_other_words_alone():
    s = "Umbilical hernia, erythema, ahead of the uterus"
    assert clean_verbatim(s) == s


@pytest.mark.parametrize("text, closed", [
    ("No effusion.", True),
    ("Is there a nodule?", True),
    ("no effusion\n", True),
    ("there is a", False),
    ("5 mm", False),
    ('"quoted."', True),
    ("", False),
])
def test_closes_line(text, closed):
    assert closes_line(text) is closed


# --- route_bundle -------------------------------------------------------------------

def _bundle(action="append_new_finding", confidence=0.97, is_correction=0.05, standalone=0.8):
    return BundleDecision(
        triage=TriageDecision(
            candidate="jev", action=action, confidence=confidence,
            probabilities={action: confidence}, is_correction=is_correction,
            needs_committed_edit=0.1, latency_ms=250, input_tokens=900, cost_usd=3e-5,
        ),
        standalone=standalone, coverage={}, latency_ms=250, n_questions=4, input_tokens=900, cost_usd=3e-5,
    )


def test_confident_append_fast_appends_the_cleaned_text():
    r = route_bundle(_bundle(), "um no pleural effusion.")
    assert r == RouteResult(route="fast_append", reason="append_confident", text="no pleural effusion.",
                            insert="", closes_line=True, close_on_silence=True)


def test_append_below_the_band_goes_to_polish():
    r = route_bundle(_bundle(confidence=FAST_APPEND_BANDS["append_act"] - 0.01), "no effusion")
    assert (r.route, r.reason) == ("polish", "append_low_confidence")


def test_append_with_a_correction_signal_goes_to_polish():
    r = route_bundle(_bundle(is_correction=FAST_APPEND_BANDS["append_max_is_correction"]), "no effusion")
    assert (r.route, r.reason) == ("polish", "correction_signal")


@pytest.mark.parametrize("action", [
    "correct_previous_finding", "restate_existing_finding", "delete_previous_utterance", "ignore_noise",
])
def test_non_append_actions_go_to_polish(action):
    r = route_bundle(_bundle(action=action, confidence=0.99), "actually make that 6 mm")
    assert (r.route, r.reason) == ("polish", f"action:{action}")


def test_confident_command_with_a_lexicon_mapping_is_deterministic():
    r = route_bundle(_bundle(action="formatting_command", confidence=0.95), "new paragraph")
    assert (r.route, r.reason, r.insert, r.text) == ("command", "command_lexicon", "\n\n", "")
    assert r.closes_line is True


def test_full_stop_command_closes_the_line():
    r = route_bundle(_bundle(action="formatting_command", confidence=0.95), "full stop")
    assert (r.route, r.insert, r.closes_line) == ("command", ".", True)


def test_command_without_a_lexicon_mapping_goes_to_polish():
    r = route_bundle(_bundle(action="formatting_command", confidence=0.99), "bold that")
    assert (r.route, r.reason) == ("polish", "command_unmapped")


def test_command_below_its_band_goes_to_polish():
    r = route_bundle(_bundle(action="formatting_command", confidence=FAST_APPEND_BANDS["command_act"] - 0.01),
                     "new line")
    assert (r.route, r.reason) == ("polish", "command_low_confidence")


def test_any_jev_error_fails_open_to_polish():
    r = route_bundle(TriageError("jev bundle http 502"), "no effusion")
    assert (r.route, r.reason) == ("polish", "jev_error")


def test_filler_only_is_skipped_before_any_decision():
    r = route_bundle(_bundle(), "um, uh")
    assert (r.route, r.reason, r.text) == ("skip", "empty_after_clean", "")


def test_open_line_closes_on_silence_only_when_standalone_reaches_tau():
    tau = FAST_APPEND_BANDS["line_close_standalone"]
    assert route_bundle(_bundle(standalone=tau), "there is a nodule").close_on_silence is True
    assert route_bundle(_bundle(standalone=tau - 0.01), "there is a").close_on_silence is False


def test_a_bare_command_read_as_append_fails_open():
    r = route_bundle(_bundle(action="append_new_finding", confidence=0.95), "full stop")
    assert (r.route, r.reason) == ("polish", "append_no_words")


# --- Deepgram word confidence (numbers only, never the words) -------------------------

from rapid_reports_ai.fast_append import asr_confidence  # noqa: E402


def test_asr_confidence_is_numbers_only():
    alt = {"transcript": "5 cm intraperitoneal bleed", "confidence": 0.91,
           "words": [{"word": "5", "confidence": 0.99}, {"word": "cm", "confidence": 0.98},
                     {"word": "intraperitoneal", "confidence": 0.612345}, {"word": "bleed", "confidence": 0.97}]}
    c = asr_confidence(alt)
    assert c == {"asr_conf": 0.91, "asr_word_confs": [0.99, 0.98, 0.6123, 0.97], "asr_min_conf": 0.6123}
    assert "intraperitoneal" not in repr(c)


@pytest.mark.parametrize("alt", [{}, {"words": []}, {"words": [{"word": "x"}]}, {"words": "bad"}])
def test_asr_confidence_without_word_scores_is_none(alt):
    assert asr_confidence(alt) is None


# --- a bare terminal mark (the websocket turns a spoken "full stop" into ".") ---------

from rapid_reports_ai.fast_append import code_route  # noqa: E402


@pytest.mark.parametrize("utt, mark", [(".", "."), (" . ", "."), ("?", "?"), ("!", "!"), ("..", "."), (". .", ".")])  # ".." = Deepgram's stop + ours
def test_a_bare_terminal_mark_is_a_command_decided_by_code(utt, mark):
    r = code_route(utt)
    assert (r.route, r.reason, r.insert, r.closes_line) == ("command", "punctuation_mark", mark, True)


def test_filler_only_is_also_decided_by_code():
    assert code_route("um, uh").route == "skip"


@pytest.mark.parametrize("utt", ["No effusion.", "new line", "full stop"])
def test_everything_else_goes_to_jev(utt):
    assert code_route(utt) is None


# --- Deepgram word-confidence gate on fast-append (QSET 2026-09-26.3) ------------------

def test_a_low_confidence_word_sends_a_confident_append_to_polish():
    # three real reports: every misheard word in a fast-appended line ("vas effect",
    # "smooth vessel", "scold vault") had its lowest word below 0.70
    r = route_bundle(_bundle(), "mild vas effect", asr_min_conf=0.66)
    assert (r.route, r.reason) == ("polish", "asr_low_confidence")


def test_at_the_gate_it_still_fast_appends():
    r = route_bundle(_bundle(), "mild mass effect", asr_min_conf=FAST_APPEND_BANDS["append_min_asr_conf"])
    assert r.route == "fast_append"


def test_without_deepgram_confidence_the_gate_does_not_apply():
    assert route_bundle(_bundle(), "mild mass effect").route == "fast_append"  # feeder / no word scores


def test_the_gate_does_not_touch_commands():
    r = route_bundle(_bundle(action="formatting_command", confidence=0.95), "new paragraph", asr_min_conf=0.3)
    assert r.route == "command"


# --- spoken formatting in the fast path -----------------------------------------------

def test_spine_levels_and_spoken_punctuation_are_cleaned():
    r = route_bundle(_bundle(), "L3 slash four There is mild disc desiccation comma no stenosis.")
    assert (r.route, r.text) == ("fast_append", "L3/4 There is mild disc desiccation, no stenosis.")


def test_a_heading_colon_becomes_punctuation():
    r = route_bundle(_bundle(), "Conclusion, colon, acute appendicitis")
    assert (r.route, r.text) == ("fast_append", "Conclusion: acute appendicitis")


def test_the_organ_colon_stays():
    r = route_bundle(_bundle(), "The sigmoid colon is unremarkable.")
    assert (r.route, r.text) == ("fast_append", "The sigmoid colon is unremarkable.")


def test_an_ambiguous_colon_fails_open_to_polish():
    r = route_bundle(_bundle(), "Colon, mild diffuse thickening", preceding="The appendix is normal.")
    assert (r.route, r.reason) == ("polish", "colon_ambiguous")


def test_a_bare_colon_after_a_level_is_a_command_decided_by_code():
    r = code_route("colon", preceding="Normal marrow.\n\nL5/S1")
    assert (r.route, r.reason, r.insert) == ("command", "spoken_colon", ":")


def test_a_bare_colon_without_a_heading_before_it_goes_to_jev():
    assert code_route("Colon.", preceding="The appendix is normal.") is None


@pytest.mark.parametrize("utt", ["Conclusion.", "Conclusion, colon,", "impression"])
def test_a_heading_on_its_own_is_written_by_code(utt):
    r = code_route(utt)
    assert (r.route, r.reason, r.text[-1]) == ("fast_append", "heading", ":")
    assert r.closes_line is True


# --- structure: disc levels and headings open a paragraph ------------------------------

def test_a_disc_level_opens_a_paragraph():
    assert route_bundle(_bundle(), "L4-five there is a broad based disc bulge").starts_paragraph is True


def test_a_heading_opens_a_paragraph():
    assert route_bundle(_bundle(), "Conclusion, colon, acute appendicitis").starts_paragraph is True
    assert code_route("Conclusion.").starts_paragraph is True


def test_an_ordinary_finding_does_not():
    assert route_bundle(_bundle(), "The conus terminates at L1 with normal signal.").starts_paragraph is False
