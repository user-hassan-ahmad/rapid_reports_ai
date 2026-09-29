from __future__ import annotations

import json
import wave

from rapid_reports_ai.lab_audio import LabAudioRecorder, recorder_from_env


def test_audio_and_deepgram_messages_are_saved_with_timing(tmp_path):
    t = [100.0]
    rec = LabAudioRecorder(tmp_path, sample_rate=16000, clock=lambda: t[0], wall_ms=1_700_000_000_000,
                           meta={"keyterms": ["hypodense"]})
    rec.audio(b"\x01\x00" * 16000)  # one second of audio
    t[0] = 101.4
    rec.event({"type": "Results", "is_final": True, "channel": {"alternatives": [{"transcript": "No effusion."}]}})
    paths = rec.close()
    with wave.open(str(paths["wav"])) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getnframes() == 16000
    [ev] = [json.loads(line) for line in paths["events"].read_text().splitlines()]
    assert ev["t"] == 1.4 and ev["audio_s"] == 1.0 and ev["msg"]["is_final"] is True
    meta = json.loads(paths["meta"].read_text())
    assert meta["sample_rate"] == 16000 and meta["started_wall_ms"] == 1_700_000_000_000
    assert meta["keyterms"] == ["hypodense"] and meta["audio_s"] == 1.0


def test_capture_is_off_unless_both_lab_flags_and_pcm(monkeypatch, tmp_path):
    monkeypatch.delenv("RR_LAB_AUDIO_CAPTURE", raising=False)
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    assert recorder_from_env(16000, use_pcm=True, directory=tmp_path) is None
    monkeypatch.setenv("RR_LAB_AUDIO_CAPTURE", "1")
    assert recorder_from_env(16000, use_pcm=False, directory=tmp_path) is None
    monkeypatch.delenv("RR_TRIAGE_DEBUG")
    assert recorder_from_env(16000, use_pcm=True, directory=tmp_path) is None
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    rec = recorder_from_env(16000, use_pcm=True, directory=tmp_path)
    assert rec is not None
    rec.close()


def test_a_failing_disk_never_breaks_dictation(tmp_path):
    rec = LabAudioRecorder(tmp_path, sample_rate=16000)
    rec.close()
    rec.audio(b"\x00\x00")  # after close: ignored, no exception
    rec.event({"type": "Results"})
