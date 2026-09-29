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

import os
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


def finalize_gap_from_env() -> float | None:
    try:
        gap = float(os.environ.get("DEEPGRAM_FINALIZE_GAP_S") or 0)
    except ValueError:
        return None
    return gap if gap > 0 else None
