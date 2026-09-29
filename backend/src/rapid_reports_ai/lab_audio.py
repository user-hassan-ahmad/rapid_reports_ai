"""Lab-only capture of a dictation session: the exact audio sent to Deepgram (WAV) and every
Deepgram message (interim and final, with word timings), so a session can be reviewed as
said → heard → written. scripts/lab_audio_review.py re-transcribes the WAV and lines it up.

Off unless RR_LAB_AUDIO_CAPTURE=1 and RR_TRIAGE_DEBUG=1, PCM audio only. Files stay on this
machine in backend/.lab_audio/ (git-ignored); nothing is uploaded or logged elsewhere. Any
write failure is swallowed: capture must never break dictation.
"""
from __future__ import annotations

import json
import logging
import os
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

LAB_AUDIO_DIR = Path(__file__).resolve().parents[2] / ".lab_audio"


class LabAudioRecorder:
    def __init__(self, directory: Path, sample_rate: int, *, clock: Callable[[], float] = time.monotonic,
                 wall_ms: int | None = None, meta: dict[str, Any] | None = None) -> None:
        self.sample_rate = sample_rate
        self._clock = clock
        self._t0 = clock()
        self._bytes = 0
        self._closed = False
        wall = wall_ms if wall_ms is not None else int(time.time() * 1000)
        stamp = datetime.fromtimestamp(wall / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        base = Path(directory) / f"session-{stamp}"
        self.dir, n = base, 1
        while True:  # two sessions in the same second must not share (and corrupt) a folder
            try:
                self.dir.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                n += 1
                self.dir = base.with_name(f"{base.name}-{n}")
        self.paths = {"wav": self.dir / "audio.wav", "events": self.dir / "deepgram.jsonl", "meta": self.dir / "meta.json"}
        self._meta = {"sample_rate": sample_rate, "started_wall_ms": wall, **(meta or {})}
        self._wav = wave.open(str(self.paths["wav"]), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)
        self._events = self.paths["events"].open("w")

    def _audio_s(self) -> float:
        return round(self._bytes / (2 * self.sample_rate), 3)

    def audio(self, chunk: bytes) -> None:
        if self._closed:
            return
        try:
            self._wav.writeframes(chunk)
            self._bytes += len(chunk)
        except Exception as e:  # never break dictation
            logger.warning("[lab_audio] audio write failed: %s", e)

    def event(self, msg: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            t = round(self._clock() - self._t0, 3)
            self._events.write(json.dumps({"t": t, "audio_s": self._audio_s(), "msg": msg}) + "\n")
        except Exception as e:
            logger.warning("[lab_audio] event write failed: %s", e)

    def close(self) -> dict[str, Path]:
        if not self._closed:
            self._closed = True
            try:
                self._wav.close()
                self._events.close()
                self.paths["meta"].write_text(json.dumps({**self._meta, "audio_s": self._audio_s()}, indent=1))
            except Exception as e:
                logger.warning("[lab_audio] close failed: %s", e)
        return self.paths


def recorder_from_env(sample_rate: int, use_pcm: bool, directory: Path = LAB_AUDIO_DIR,
                      meta: dict[str, Any] | None = None) -> LabAudioRecorder | None:
    if not (os.environ.get("RR_LAB_AUDIO_CAPTURE") == "1" and os.environ.get("RR_TRIAGE_DEBUG") == "1" and use_pcm):
        return None
    try:
        return LabAudioRecorder(directory, sample_rate, meta=meta)
    except Exception as e:
        logger.warning("[lab_audio] could not start: %s", e)
        return None
