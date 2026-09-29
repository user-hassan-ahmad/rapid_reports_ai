"""Force a Deepgram final at a pause, instead of waiting for Deepgram's own endpointing.

Lab capture (2026-09-29): of ten pauses of 0.95–2.1 s, Deepgram ended a final at five; one
final held 17 s of speech across two 2-second pauses, so nothing could go solid for up to
15 s although the words had arrived as interims within about a second. The audio level in
the pauses did not explain which ones it cut.

Deepgram's interims report how far into the audio it has heard (start + duration) and the
words it found. Once it has heard gap_s past the last word with no new word, the backend
sends {"type": "Finalize"} and Deepgram returns everything pending as a final (from_finalize).
Timing from what Deepgram has *heard*, not from our clock, avoids cutting mid-sentence while
the next interim is still on its way. Lab only: DEEPGRAM_FINALIZE_GAP_S (e.g. 0.9); provisional.
"""
from __future__ import annotations

import math
import os
from collections import deque
from typing import Any


class FinalizeTrigger:
    def __init__(self, gap_s: float) -> None:
        self.gap_s = gap_s
        self.last_word_end: float | None = None  # end of the newest word not yet in a final
        self.asked_for: float | None = None  # last_word_end a Finalize was already sent for

    def observe(self, msg: dict[str, Any]) -> bool:
        """Feed every Deepgram message; True when a Finalize should be sent now."""
        if msg.get("type") != "Results":
            return False
        alt = ((msg.get("channel") or {}).get("alternatives") or [{}])[0]
        words = alt.get("words") or []
        if msg.get("is_final"):
            self.last_word_end = None  # everything so far is final
            self.asked_for = None
            return False
        if words:
            self.last_word_end = max(w.get("end", 0.0) for w in words)
        if self.last_word_end is None or self.asked_for == self.last_word_end:
            return False
        heard_until = float(msg.get("start", 0.0)) + float(msg.get("duration", 0.0))
        if heard_until - self.last_word_end >= self.gap_s:
            self.asked_for = self.last_word_end
            return True
        return False


    def retract(self) -> None:
        """The Finalize was not sent (the audio says speech has resumed): ask again next time."""
        self.asked_for = None


class AudioLevel:
    """Is the speaker quiet right now? Deepgram reports a word about a second after it is
    said, so the trigger alone fired as "Actually" began (lab 2026-09-29: the flush cut the
    word and Deepgram returned nothing for 9 s; the phrase was lost). The audio itself is
    immediate: every 50 ms frame of the last recent_s must sit quiet_db below the speaker's
    level. The loudest frame, not the average: 0.1 s of onset averaged with 0.2 s of silence
    passed as quiet, and another "Actually" was dropped.
    """

    FRAME_S = 0.05

    def __init__(self, sample_rate: int, recent_s: float = 0.3, quiet_db: float = 18.0) -> None:
        # 18 dB: in the captured session pauses sat 22–33 dB below speech and the onset of the
        # lost "Actually" 12 dB below; a held flush costs a little delay, a bad one loses words.
        self.sample_rate = sample_rate
        self.quiet_db = quiet_db
        self._frame = max(1, int(sample_rate * self.FRAME_S))
        self._frames: deque[float] = deque(maxlen=max(1, round(recent_s / self.FRAME_S)))
        self._pending: list[int] = []  # samples not yet a whole frame
        self.speech_db: float | None = None  # peak-following reference, decays slowly

    def feed(self, pcm: bytes) -> None:
        n = len(pcm) // 2
        if not n:
            return
        self._pending.extend(memoryview(pcm)[: n * 2].cast("h"))
        while len(self._pending) >= self._frame:
            frame, self._pending = self._pending[: self._frame], self._pending[self._frame:]
            db = _db(sum(x * x for x in frame) / len(frame))
            self._frames.append(db)
            if self.speech_db is None or db > self.speech_db:
                self.speech_db = db
            else:  # decay ~1 dB/s so a loud cough does not set the bar for the whole session
                self.speech_db -= self.FRAME_S

    def recent_db(self) -> float:
        return max(self._frames) if self._frames else -120.0

    def quiet(self) -> bool:
        if self.speech_db is None or self.speech_db < -55:  # no speech heard yet
            return False
        return self.recent_db() <= self.speech_db - self.quiet_db


def _db(mean_square: float) -> float:
    return 20 * math.log10(max(math.sqrt(mean_square), 1.0) / 32768)


def finalize_gap_from_env() -> float | None:
    try:
        gap = float(os.environ.get("DEEPGRAM_FINALIZE_GAP_S") or 0)
    except ValueError:
        return None
    return gap if gap > 0 else None
