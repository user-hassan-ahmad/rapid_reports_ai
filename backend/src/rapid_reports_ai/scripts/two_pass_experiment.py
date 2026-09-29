"""Two-pass ASR experiment on a captured lab session (lab_audio): re-transcribe each live final's audio
clip with Deepgram batch; compare latency, accuracy (vs the whole-recording batch reference)
and confidence with the live final.

    PYTHONPATH=src python -m rapid_reports_ai.scripts.two_pass_experiment <session-dir> [--since-last]

--since-last clips everything since the previous final ended (recovers speech the stream
dropped); default clips each final's own words. Needs batch_words.json (lab_audio_review).
Result 2026-09-29: own-words p50 137 ms, 1 word recovered, noisier confidence on short clips;
since-last p50 211 ms, recovered a phrase the stream lost after a Finalize, 3/18 below the
gate vs 6/18 live."""
import io, json, os, sys, time, wave, httpx
from pathlib import Path
from dotenv import load_dotenv; load_dotenv(".env")
from rapid_reports_ai.deepgram_spelling import UK_SPELLING
from rapid_reports_ai.fast_append import asr_confidence
from rapid_reports_ai.scripts.lab_audio_review import stream_finals, assign_words, word_diff

d = Path(sys.argv[1]); meta = json.loads((d / "meta.json").read_text())
ev = [json.loads(l) for l in (d / "deepgram.jsonl").read_text().splitlines() if l.strip()]
ref = json.loads((d / "batch_words.json").read_text())
w = wave.open(str(d / "audio.wav")); sr = w.getframerate(); pcm = w.readframes(w.getnframes())
params = [("model", "nova-3-medical"), ("language", "en-GB"), ("smart_format", "true"), ("numerals", "true"),
          ("measurements", "true"), ("mip_opt_out", "true")] + [("keyterm", k) for k in meta.get("keyterms") or []] \
         + [("replace", f"{a}:{b}") for a, b in UK_SPELLING.items()]
client = httpx.Client(timeout=30, headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": "audio/wav"})
client.post("https://api.deepgram.com/v1/listen", params=params[:2], content=b"")  # warm the connection

def clip(a, b):
    a, b = max(0, int(a * sr)), min(len(pcm) // 2, int(b * sr))
    buf = io.BytesIO(); o = wave.open(buf, "wb"); o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
    o.writeframes(pcm[a * 2:b * 2]); o.close(); return buf.getvalue()

finals = stream_finals(ev); groups = assign_words(finals, ref)
rows = []; prev_end = 0.0; since_last = "--since-last" in sys.argv
for f, g in zip(finals, groups):
    body = clip(prev_end if since_last else f["speech_start"] - 0.3, f["speech_end"] + 0.3)
    prev_end = f["speech_end"] + 0.3
    t0 = time.perf_counter()
    r = client.post("https://api.deepgram.com/v1/listen", params=params, content=body)
    ms = int((time.perf_counter() - t0) * 1000)
    alt = r.json()["results"]["channels"][0]["alternatives"][0]
    live_c = asr_confidence({"words": f["words"]}); two_c = asr_confidence(alt) or {"asr_min_conf": None}
    rows.append({"live": f["text"], "two": alt["transcript"], "ms": ms,
                 "live_err": len(word_diff(f["words"], g)), "two_err": len(word_diff(alt.get("words") or [], g)),
                 "live_min": live_c["asr_min_conf"], "two_min": two_c["asr_min_conf"], "secs": round(f["speech_end"] - f["speech_start"], 1)})
for r in rows:
    flag = "" if r["live_err"] == r["two_err"] else ("  ← two-pass better" if r["two_err"] < r["live_err"] else "  ← two-pass WORSE")
    print(f"{r['secs']:4.1f}s audio  {r['ms']:4d} ms  errors live {r['live_err']} / two-pass {r['two_err']}  min conf {r['live_min']:.2f} → {r['two_min'] if r['two_min'] is None else round(r['two_min'],2)}{flag}")
    if r["live"].strip() != r["two"].strip(): print(f"      live: {r['live']!r}\n      two : {r['two']!r}")
ms = sorted(r["ms"] for r in rows)
print(f"\nlatency p50 {ms[len(ms)//2]} ms, max {ms[-1]} ms; errors vs reference: live {sum(r['live_err'] for r in rows)}, two-pass {sum(r['two_err'] for r in rows)}; "
      f"below the 0.80 gate: live {sum(r['live_min'] < 0.8 for r in rows)}/{len(rows)}, two-pass {sum((r['two_min'] or 0) < 0.8 for r in rows)}/{len(rows)}")
