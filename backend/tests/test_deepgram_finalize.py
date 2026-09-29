from __future__ import annotations

import pytest

from rapid_reports_ai.deepgram_finalize import FinalizeTrigger, finalize_gap_from_env


def _interim(start, duration, words):
    return {"type": "Results", "is_final": False, "start": start, "duration": duration,
            "channel": {"alternatives": [{"transcript": " ".join(w for w, _ in words),
                                          "words": [{"word": w, "start": e - 0.3, "end": e} for w, e in words]}]}}


def _final(start, duration, words, from_finalize=False):
    m = _interim(start, duration, words)
    m.update(is_final=True, from_finalize=from_finalize)
    return m


def test_fires_once_deepgram_has_heard_the_gap_with_no_new_word():
    t = FinalizeTrigger(gap_s=0.9)
    assert t.observe(_interim(22.0, 3.0, [("measures", 24.6), ("45", 25.0)])) is False  # heard to 25.0
    assert t.observe(_interim(22.0, 3.8, [("measures", 24.6), ("45", 25.0)])) is False  # 0.8 s of silence
    assert t.observe(_interim(22.0, 4.0, [("measures", 24.6), ("45", 25.0)])) is True   # 1.0 s: finalize


def test_does_not_fire_while_words_keep_coming():
    t = FinalizeTrigger(gap_s=0.9)
    assert t.observe(_interim(22.0, 3.0, [("45", 25.0)])) is False
    assert t.observe(_interim(22.0, 4.0, [("45", 25.0), ("millimetres", 25.8)])) is False


def test_fires_once_per_pause_and_rearms_after_new_speech():
    t = FinalizeTrigger(gap_s=0.9)
    t.observe(_interim(22.0, 3.0, [("45", 25.0)]))
    assert t.observe(_interim(22.0, 4.0, [("45", 25.0)])) is True
    assert t.observe(_interim(22.0, 5.0, [("45", 25.0)])) is False  # already asked
    t.observe(_final(22.0, 4.0, [("45", 25.0)], from_finalize=True))
    assert t.observe(_interim(26.0, 1.0, [("Actually", 26.8)])) is False
    assert t.observe(_interim(26.0, 2.0, [("Actually", 26.8)])) is True


def test_nothing_pending_after_a_final_means_no_finalize():
    t = FinalizeTrigger(gap_s=0.9)
    t.observe(_interim(0.0, 2.0, [("No", 1.0)]))
    t.observe(_final(0.0, 2.0, [("No", 1.0)]))
    assert t.observe(_interim(2.0, 3.0, [])) is False  # silence after a final: nothing to flush


def test_ignores_other_messages():
    t = FinalizeTrigger(gap_s=0.9)
    assert t.observe({"type": "UtteranceEnd", "last_word_end": 3.0}) is False
    assert t.observe({"type": "Metadata"}) is False


@pytest.mark.parametrize("value,expected", [(None, None), ("", None), ("0", None), ("0.9", 0.9), ("x", None)])
def test_off_unless_a_positive_gap_is_set(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("DEEPGRAM_FINALIZE_GAP_S", raising=False)
    else:
        monkeypatch.setenv("DEEPGRAM_FINALIZE_GAP_S", value)
    assert finalize_gap_from_env() == expected


# --- audio-level guard: never flush while the speaker is mid-word -------------------------
import math
import struct

from rapid_reports_ai.deepgram_finalize import AudioLevel


def _pcm(db: float, seconds: float, sr: int = 16000) -> bytes:
    amp = int(32767 * 10 ** (db / 20))
    n = int(sr * seconds)
    return struct.pack(f"<{n}h", *[int(amp * math.sin(2 * math.pi * 220 * i / sr)) for i in range(n)])


def test_quiet_after_speech_allows_a_final_and_speech_blocks_it():
    lv = AudioLevel(sample_rate=16000)
    lv.feed(_pcm(-30, 2.0))  # speaking
    assert lv.quiet() is False
    lv.feed(_pcm(-62, 0.5))  # pause
    assert lv.quiet() is True
    lv.feed(_pcm(-35, 0.2))  # "Actually" begins, before Deepgram reports it
    assert lv.quiet() is False


def test_no_speech_heard_yet_counts_as_not_quiet():
    lv = AudioLevel(sample_rate=16000)
    lv.feed(_pcm(-62, 0.5))
    assert lv.quiet() is False  # no reference level yet: do not force anything


def test_a_blocked_finalize_is_retried_on_the_next_interim():
    t = FinalizeTrigger(gap_s=0.9)
    t.observe(_interim(22.0, 3.0, [("45", 25.0)]))
    assert t.observe(_interim(22.0, 4.0, [("45", 25.0)])) is True
    t.retract()  # the audio said the speaker had started again
    assert t.observe(_interim(22.0, 4.5, [("45", 25.0)])) is True
