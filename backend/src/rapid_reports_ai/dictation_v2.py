"""The dictation package in production: `rr_dictation_v2` (plan 2026-09-29-dictation-v2-release).

The lab found the package; this is its production switch. The server allows it
(RR_DICTATION_V2=1, the kill switch; the lab's RR_TRIAGE_DEBUG also allows it) and a client
asks for it per connection (`v2=1` on the websocket; the package's endpoints are simply
available). Everyone else gets production dictation exactly as before. Audio capture is never
part of the package (lab_audio: lab only).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

# What the last lab sessions ran (2026-09-29).
PACKAGE = {
    "dictation": False,  # Deepgram dictation mode off: "colon" is an organ; commands are ours
    "uk_spelling": True,
    "spoken_format": True,
    "case_keyterms": True,
    "finalize_gap_s": 0.9,  # forced finals, with the audio guard (deepgram_finalize)
    "two_pass": True,  # Deepgram batch + gpt-4o-transcribe, Jev as referee (two_pass)
    "asr_fields": True,  # word confidences to the client (the ASR gate)
}


def v2_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("RR_DICTATION_V2") == "1" or env.get("RR_TRIAGE_DEBUG") == "1"


@dataclass(frozen=True)
class SocketSettings:
    v2: bool
    dictation: bool
    uk_spelling: bool
    spoken_format: bool
    case_keyterms: bool
    finalize_gap_s: float | None
    two_pass: bool
    asr_fields: bool


def socket_settings(query: Mapping[str, str], env: Mapping[str, str] = os.environ) -> SocketSettings:
    """Per websocket: the package for a client that asks on a server that allows it; otherwise
    the env as before (production defaults, or the lab's own flags)."""
    if query.get("v2") == "1" and v2_allowed(env):
        return SocketSettings(v2=True, **PACKAGE)
    lab = env.get("RR_TRIAGE_DEBUG") == "1"
    try:
        gap = float(env.get("DEEPGRAM_FINALIZE_GAP_S") or 0) if lab else 0.0
    except ValueError:
        gap = 0.0
    return SocketSettings(
        v2=False,
        dictation=env.get("DEEPGRAM_DICTATION", "1") != "0",
        uk_spelling=env.get("DEEPGRAM_UK_SPELLING") == "1",
        spoken_format=env.get("DEEPGRAM_SPOKEN_FORMAT") == "1",
        case_keyterms=env.get("DEEPGRAM_CASE_KEYTERMS") == "1",
        finalize_gap_s=gap if gap > 0 else None,
        two_pass=lab and env.get("RR_TWO_PASS") == "1",
        asr_fields=lab,
    )
