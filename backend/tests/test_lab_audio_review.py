from __future__ import annotations

from rapid_reports_ai.scripts.lab_audio_review import pauses, stream_finals, window_words, word_diff


def _w(word, start, end, conf=0.99):
    return {"word": word.lower(), "punctuated_word": word, "start": start, "end": end, "confidence": conf}


EVENTS = [
    {"t": 0.8, "audio_s": 1.0, "msg": {"type": "Results", "is_final": False, "start": 0.0, "duration": 0.8,
                                       "channel": {"alternatives": [{"transcript": "No", "words": [_w("No", 0.1, 0.3)]}]}}},
    {"t": 2.6, "audio_s": 2.7, "msg": {"type": "Results", "is_final": True, "speech_final": True, "start": 0.0, "duration": 2.2,
                                       "channel": {"alternatives": [{"transcript": "No hydrodense lesion.",
                                                                     "words": [_w("No", 0.1, 0.3), _w("hydrodense", 0.4, 1.1, 0.6), _w("lesion.", 1.2, 1.9)]}]}}},
]


def test_finals_carry_their_words_timing_and_how_late_they_arrived():
    [f] = stream_finals(EVENTS)
    assert f["text"] == "No hydrodense lesion." and f["speech_final"] is True
    assert f["speech_start"] == 0.1 and f["speech_end"] == 1.9
    assert f["arrived_after_speech_s"] == 0.7  # 2.6 s clock − 1.9 s end of speech
    assert f["min_conf"] == 0.6


def test_pauses_between_words():
    words = [_w("No", 0.1, 0.3), _w("effusion.", 0.4, 1.0), _w("Small", 1.9, 2.1)]
    assert pauses(words, min_gap=0.5) == [{"after": "effusion.", "at": 1.0, "gap": 0.9}]


def test_window_and_diff_show_what_the_stream_got_wrong():
    batch = [_w("No", 0.1, 0.3), _w("hypodense", 0.4, 1.1), _w("lesion.", 1.2, 1.9), _w("Small", 2.5, 2.8)]
    stream = stream_finals(EVENTS)[0]["words"]
    assert [w["punctuated_word"] for w in window_words(batch, 0.0, 2.0)] == ["No", "hypodense", "lesion."]
    assert word_diff(stream, window_words(batch, 0.0, 2.0)) == [("hydrodense", "hypodense")]


def test_each_said_word_goes_to_the_final_nearest_it_even_when_timings_differ():
    from rapid_reports_ai.scripts.lab_audio_review import assign_words
    finals = [{"speech_start": 0.0, "speech_end": 4.7}, {"speech_start": 5.8, "speech_end": 8.6}]
    batch = [_w("No", 3.8, 4.1), _w("effusion.", 4.2, 5.0), _w("There", 5.9, 6.1)]  # batch ends 0.3 s later
    groups = assign_words(finals, batch)
    assert [[w["punctuated_word"] for w in g] for g in groups] == [["No", "effusion."], ["There"]]


def test_a_pause_counts_as_a_cut_when_a_final_ends_near_it():
    from rapid_reports_ai.scripts.lab_audio_review import is_cut
    assert is_cut({"at": 5.0, "gap": 0.64}, [{"speech_end": 4.7}]) is True
    assert is_cut({"at": 3.0, "gap": 0.64}, [{"speech_end": 4.7}]) is False
