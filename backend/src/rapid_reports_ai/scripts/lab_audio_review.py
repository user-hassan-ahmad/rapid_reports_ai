"""Review a captured lab session: what was said (batch re-transcription of the saved audio),
what the live stream sent and when, the pauses, and where the stream cut its finals.

    PYTHONPATH=src python -m rapid_reports_ai.scripts.lab_audio_review [session-dir] [--export lab-session.json]

With no directory, the newest session in backend/.lab_audio/ is used. The batch pass uses
the same model, language, formatting and keyterms as the stream (Deepgram prerecorded,
which hears the whole recording). --export lines up the lab's decisions (route, timings).

Plan: capture in lab_audio.py (RR_LAB_AUDIO_CAPTURE=1).
"""
from __future__ import annotations

import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from rapid_reports_ai.deepgram_spelling import UK_SPELLING
from rapid_reports_ai.lab_audio import LAB_AUDIO_DIR


def _alt(msg: dict) -> dict:
    return ((msg.get("channel") or {}).get("alternatives") or [{}])[0]


def stream_finals(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        m = e["msg"]
        if m.get("type") != "Results" or not m.get("is_final"):
            continue
        a = _alt(m)
        words = a.get("words") or []
        if not (a.get("transcript") or "").strip():
            continue
        end = words[-1]["end"] if words else m.get("start", 0) + m.get("duration", 0)
        out.append({
            "text": a.get("transcript", ""), "speech_final": bool(m.get("speech_final")), "words": words,
            "speech_start": words[0]["start"] if words else m.get("start"),
            "speech_end": end,
            "arrived_after_speech_s": round(e["t"] - end, 2),
            "min_conf": min((w.get("confidence", 1.0) for w in words), default=None),
        })
    return out


def pauses(words: list[dict], min_gap: float = 0.3) -> list[dict]:
    return [{"after": a.get("punctuated_word", a["word"]), "at": a["end"], "gap": round(b["start"] - a["end"], 2)}
            for a, b in zip(words, words[1:]) if b["start"] - a["end"] >= min_gap]


def window_words(words: list[dict], start: float, end: float) -> list[dict]:
    return [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]


def assign_words(finals: list[dict], words: list[dict]) -> list[list[dict]]:
    """Each said word goes to the final whose span (widened to halfway into the gaps around
    it) holds the word's midpoint: live and batch timings differ by a few hundred ms."""
    bounds = []
    for i, f in enumerate(finals):
        lo = (finals[i - 1]["speech_end"] + f["speech_start"]) / 2 if i else float("-inf")
        hi = (f["speech_end"] + finals[i + 1]["speech_start"]) / 2 if i + 1 < len(finals) else float("inf")
        bounds.append((lo, hi))
    groups: list[list[dict]] = [[] for _ in finals]
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        for i, (lo, hi) in enumerate(bounds):
            if lo <= mid < hi:
                groups[i].append(w)
                break
    return groups


def is_cut(pause: dict, finals: list[dict], tolerance: float = 0.5) -> bool:
    """The stream ended a final at this pause (within the timing slack between the passes)."""
    return any(abs(f["speech_end"] - pause["at"]) <= tolerance for f in finals)


def _norm(w: dict) -> str:
    return "".join(ch for ch in w.get("word", "").lower() if ch.isalnum())


def word_diff(stream: list[dict], batch: list[dict]) -> list[tuple[str, str]]:
    a, b = [_norm(w) for w in stream], [_norm(w) for w in batch]
    return [(" ".join(a[i1:i2]), " ".join(b[j1:j2]))
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal"]


def batch_transcribe(wav: Path, keyterms: list[str] | None, uk_spelling: bool = False) -> list[dict]:
    params: list[tuple[str, str]] = [("model", "nova-3-medical"), ("language", "en-GB"), ("smart_format", "true"),
                                     ("numerals", "true"), ("measurements", "true"), ("mip_opt_out", "true")]
    params += [("keyterm", k) for k in (keyterms or [])]
    if uk_spelling:  # the stream's British spelling, so spelling is not reported as a difference
        params += [("replace", f"{us}:{uk}") for us, uk in UK_SPELLING.items()]
    r = httpx.post("https://api.deepgram.com/v1/listen", params=params, content=wav.read_bytes(), timeout=120,
                   headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": "audio/wav"})
    r.raise_for_status()
    return r.json()["results"]["channels"][0]["alternatives"][0]["words"]  # batch: no "channel" wrapper


def _latest() -> Path:
    sessions = sorted(LAB_AUDIO_DIR.glob("session-*"))
    if not sessions:
        sys.exit(f"no captured sessions in {LAB_AUDIO_DIR} (start the backend with RR_LAB_AUDIO_CAPTURE=1)")
    return sessions[-1]


def main(argv: list[str]) -> None:
    load_dotenv(".env")
    export = argv[argv.index("--export") + 1] if "--export" in argv else None
    positional = [a for a in argv if not a.startswith("--") and a != export]
    d = Path(positional[0]) if positional else _latest()
    meta = json.loads((d / "meta.json").read_text())
    events = [json.loads(line) for line in (d / "deepgram.jsonl").read_text().splitlines() if line.strip()]
    finals = stream_finals(events)
    batch = batch_transcribe(d / "audio.wav", meta.get("keyterms"), bool(meta.get("uk_spelling")))
    decisions: list[dict[str, Any]] = []
    if export:
        decisions = json.loads(Path(export).read_text()).get("decisions", [])

    interims = sum(1 for e in events if e["msg"].get("type") == "Results" and not e["msg"].get("is_final"))
    print(f"session {d.name}: {meta.get('audio_s')} s audio, {len(finals)} finals, {interims} interim updates, "
          f"keyterms {len(meta.get('keyterms') or [])}")
    print("\nSAID (batch re-transcription of the saved audio):\n  " + " ".join(w.get("punctuated_word", w["word"]) for w in batch))

    di = 0
    total_diff = 0
    print("\nSTREAM, final by final:")
    groups = assign_words(finals, batch)
    for i, f in enumerate(finals, 1):
        diff = word_diff(f["words"], groups[i - 1])
        total_diff += len(diff)
        dec = ""
        while di < len(decisions) and decisions[di].get("utterance_len") not in (len(f["text"]), None):
            di += 1
        if di < len(decisions) and decisions[di].get("utterance_len") == len(f["text"]):
            r = decisions[di]
            dec = f"  → {r['route']} ({(r.get('reason') or '')[:40]}), solid {r.get('final_to_solid_ms')} ms"
            di += 1
        print(f"\n [{i}] {f['speech_start']:.1f}–{f['speech_end']:.1f}s  {f['speech_end'] - f['speech_start']:.1f}s of speech, "
              f"{len(f['text'])} chars, arrived {f['arrived_after_speech_s']} s after speech ended"
              f"{' (speech_final)' if f['speech_final'] else ''}, lowest word conf {f['min_conf']}{dec}")
        print(f"     stream: {f['text']}")
        if diff:
            print("     heard differently: " + "; ".join(f"'{a}' → '{b}'" if a and b else (f"missing '{b}'" if b else f"extra '{a}'") for a, b in diff))

    print("\nPAUSES ≥ 0.4 s in what was said (✂ = the stream ended a final there):")
    for p in pauses(batch, 0.4):
        print(f"  {p['at']:.1f}s  {p['gap']:.2f}s after '{p['after']}'{'  ✂' if is_cut(p, finals) else ''}")

    lags = sorted(f["arrived_after_speech_s"] for f in finals)
    sizes = sorted(len(f["text"]) for f in finals)
    if lags:
        print(f"\nSUMMARY: {total_diff} places the stream heard differently from the batch pass; finals arrived "
              f"p50 {lags[len(lags) // 2]} s / max {lags[-1]} s after speech ended; final size p50 {sizes[len(sizes) // 2]} "
              f"/ max {sizes[-1]} chars")


if __name__ == "__main__":
    main(sys.argv[1:])
