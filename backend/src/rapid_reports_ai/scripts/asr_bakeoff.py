"""ASR bake-off on captured lab sessions: per-utterance clips (cut as the live system would,
since the previous final) through several engines, scored against the script that was read.

    PYTHONPATH=src python -m rapid_reports_ai.scripts.asr_bakeoff <session-dir>=<reference.txt> ...

Critical words — numbers, units, sides, negations and clinical terms — are scored apart:
a wrong one changes the report. `oracle` counts, for two engines, where they agree and who
is right where they do not (the ceiling for an ensemble that asks Jev to choose).
"""
from __future__ import annotations

import asyncio
import difflib
import io
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv

_UNITS = [(re.compile(r"\b(millimet(?:re|er)s?)\b"), "mm"), (re.compile(r"\b(centimet(?:re|er)s?)\b"), "cm")]
_NUM_UNIT = re.compile(r"(\d)(mm|cm)\b")
_SIDES = {"left", "right", "bilateral"}
_NEGATIONS = {"no", "not", "without", "absent", "negative"}
_STOP = set("""the and with that this there than from have been into over under which were their also
measures measuring measure previously actually make correction paragraph colon prior study smaller
side sided seen noted""".split())


def normalise(text: str) -> list[str]:
    t = (text or "").lower().replace("-", " ")
    for pattern, unit in _UNITS:
        t = pattern.sub(unit, t)
    t = _NUM_UNIT.sub(r"\1 \2", t)
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", t)


def _critical(w: str) -> bool:
    return (w[0].isdigit() or w in ("mm", "cm") or w in _SIDES or w in _NEGATIONS
            or (len(w) >= 4 and w not in _STOP and w.isalpha()))


def critical_mask(tokens: list[str]) -> list[bool]:
    return [_critical(w) for w in tokens]


def score(ref: list[str], hyp: list[str]) -> dict:
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    crit = critical_mask(ref)
    s = d = i = crit_err = crit_ins = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        n_ref, n_hyp = i2 - i1, j2 - j1
        crit_err += sum(crit[i1:i2])
        if tag == "replace":
            s += min(n_ref, n_hyp)
            d += max(0, n_ref - n_hyp)
            i += max(0, n_hyp - n_ref)
            crit_ins += sum(_critical(w) for w in hyp[j1 + n_ref:j2]) if n_hyp > n_ref else 0
        elif tag == "delete":
            d += n_ref
        elif tag == "insert":
            i += n_hyp
            crit_ins += sum(_critical(w) for w in hyp[j1:j2])
    n = max(1, len(ref))
    return {"wer": (s + d + i) / n, "substitutions": s, "deletions": d, "insertions": i,
            "critical_errors": crit_err, "critical_inserted": crit_ins, "critical_total": sum(crit)}


def _correct_positions(ref: list[str], hyp: list[str]) -> set[int]:
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    return {k for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal" for k in range(i1, i2)}


def oracle(ref: list[str], a: list[str], b: list[str], critical_only: bool = True) -> dict:
    ca, cb = _correct_positions(ref, a), _correct_positions(ref, b)
    idx = [k for k, c in enumerate(critical_mask(ref)) if c or not critical_only]
    return {"both_right": sum(k in ca and k in cb for k in idx), "only_a": sum(k in ca and k not in cb for k in idx),
            "only_b": sum(k in cb and k not in ca for k in idx), "both_wrong": sum(k not in ca and k not in cb for k in idx)}


# --- engines -------------------------------------------------------------------------------

def _wav16k(pcm: np.ndarray, sr: int) -> bytes:
    if sr % 16000 == 0 and sr != 16000:  # average then decimate (a crude low-pass)
        k = sr // 16000
        pcm = pcm[: len(pcm) // k * k].reshape(-1, k).mean(axis=1).astype(np.int16)
        sr = 16000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr), w.writeframes(pcm.tobytes())
    return buf.getvalue()


async def _deepgram(c: httpx.AsyncClient, wav: bytes, keyterms: list[str]) -> str:
    from rapid_reports_ai.deepgram_spelling import UK_SPELLING
    params = [("model", "nova-3-medical"), ("language", "en-GB"), ("smart_format", "true"), ("numerals", "true"),
              ("measurements", "true"), ("mip_opt_out", "true")] + [("keyterm", k) for k in keyterms] \
             + [("replace", f"{a}:{b}") for a, b in UK_SPELLING.items()]
    r = await c.post("https://api.deepgram.com/v1/listen", params=params, content=wav,
                     headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": "audio/wav"})
    r.raise_for_status()
    return r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


async def _openai_style(c: httpx.AsyncClient, url: str, key: str, model: str, wav: bytes, prompt: str) -> str:
    r = await c.post(url, headers={"Authorization": f"Bearer {key}"},
                     files={"file": ("clip.wav", wav, "audio/wav")},
                     data={"model": model, "language": "en", "prompt": prompt, "response_format": "json", "temperature": "0"})
    r.raise_for_status()
    return r.json().get("text", "")


def engines(keyterms: list[str]) -> dict:
    prompt = "Radiology dictation. " + ", ".join(keyterms)[:700]
    groq = ("https://api.groq.com/openai/v1/audio/transcriptions", os.environ.get("GROQ_API_KEY", ""))
    oai = ("https://api.openai.com/v1/audio/transcriptions", os.environ.get("OPENAI_API_KEY", ""))
    return {
        "deepgram-batch": lambda c, w: _deepgram(c, w, keyterms),
        "whisper-v3-turbo (groq)": lambda c, w: _openai_style(c, *groq, "whisper-large-v3-turbo", w, prompt),
        "whisper-v3 (groq)": lambda c, w: _openai_style(c, *groq, "whisper-large-v3", w, prompt),
        "gpt-4o-transcribe": lambda c, w: _openai_style(c, *oai, "gpt-4o-transcribe", w, prompt),
        "gpt-4o-mini-transcribe": lambda c, w: _openai_style(c, *oai, "gpt-4o-mini-transcribe", w, prompt),
    }


async def run_session(d: Path, reference: str) -> dict:
    from rapid_reports_ai.scripts.lab_audio_review import stream_finals
    meta = json.loads((d / "meta.json").read_text())
    events = [json.loads(l) for l in (d / "deepgram.jsonl").read_text().splitlines() if l.strip()]
    finals = stream_finals(events)
    with wave.open(str(d / "audio.wav")) as w:
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    clips, prev = [], 0.0
    for f in finals:  # since the previous final: speech the stream dropped is inside
        end = f["speech_end"] + 0.3
        clips.append(_wav16k(pcm[int(prev * sr):int(end * sr)], sr))
        prev = end
    eng = engines(meta.get("keyterms") or [])
    out = {"live (deepgram stream)": {"text": " ".join(f["text"] for f in finals), "ms": []}}
    async with httpx.AsyncClient(timeout=60) as c:
        for name in eng:
            out[name] = {"text": [], "ms": [], "errors": 0}
        for clip in clips:
            async def one(name):
                t0 = time.perf_counter()
                try:
                    txt = await eng[name](c, clip)
                except Exception as e:
                    out[name]["errors"] += 1
                    txt = ""
                    print(f"   {name}: {type(e).__name__} {str(e)[:120]}", file=sys.stderr)
                return name, txt, int((time.perf_counter() - t0) * 1000)
            for name, txt, ms in await asyncio.gather(*(one(n) for n in eng)):
                out[name]["text"].append(txt.strip())
                out[name]["ms"].append(ms)
    for name in eng:
        out[name]["text"] = " ".join(t for t in out[name]["text"] if t)
    ref = normalise(reference)
    for name, r in out.items():
        r["score"] = score(ref, normalise(r["text"]))
    return out


def main(argv: list[str]) -> None:
    load_dotenv(".env")
    results = {}
    out_json = argv[argv.index("--json") + 1] if "--json" in argv else None
    for arg in argv:
        if arg.startswith("--") or arg == out_json:
            continue
        d, ref_path = arg.split("=", 1)
        reference = Path(ref_path).read_text()
        res = asyncio.run(run_session(Path(d), reference))
        results[d] = {"reference": reference, "engines": res}
        print(f"\n== {Path(d).name} ({len(normalise(reference))} words)")
        for name, r in res.items():
            s, ms = r["score"], sorted(r["ms"])
            lat = f"p50 {ms[len(ms)//2]} ms, max {ms[-1]} ms" if ms else "streamed"
            print(f"  {name:26s} WER {s['wer']:.3f}  critical wrong {s['critical_errors']}/{s['critical_total']}"
                  f"  critical inserted {s['critical_inserted']}  latency {lat}")
    if out_json:
        Path(out_json).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
