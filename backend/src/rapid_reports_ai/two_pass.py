"""Two-pass ASR (lab): check each live Deepgram final against independent hearings of the same
audio, and let Jev choose where they disagree.

Bake-off on four captured sessions (plan 2026-09-29-two-pass-asr): no engine is best
everywhere and their errors are largely independent. gpt-4o-transcribe heard "subsegmental"
and "Tarlov" where Deepgram said "supplemental" and "dial of"; Deepgram batch on the audio
since the last final recovered a phrase the stream dropped. Jev picked the script's reading
in 31/34 disagreements: correct switches at ≥ 0.97, wrong ones at ≤ 0.64 (one turned "No" into
"lumbar"). So: switch only at ≥ SWITCH_MIN_CONF, never on commands, numbers or units, and
never when a negation, side or number would be lost.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

SWITCH_MIN_CONF = 0.90  # PROVISIONAL (lab data: right ≥ 0.97, wrong ≤ 0.64)
SUGGEST_MIN_CONF = 0.60  # below the switch bar: underline the live words, "also heard as …"
CONTEXT_WORDS = 6
RECOVER_MIN_WORDS = 2
RECOVER_MIN_CONF = 0.90
_FORMAT = {"slash", "colon", "new", "paragraph", "line", "comma", "full", "stop", "semicolon", "hyphen"}
_UNITS = {"mm", "cm", "ml", "millimetre", "millimetres", "millimeter", "millimeters",
          "centimetre", "centimetres", "centimeter", "centimeters"}
_GUARDED = re.compile(r"\b(?:no|not|without|absent|negative|left|right|bilateral)\b|\d", re.IGNORECASE)


_UNIT_NORMAL = [(re.compile(r"\bmillimet(?:re|er)s?\b"), "mm"), (re.compile(r"\bcentimet(?:re|er)s?\b"), "cm"),
                (re.compile(r"\bmillilit(?:re|er)s?\b"), "ml")]


def _tok(text: str) -> list[str]:
    """Comparable tokens: lower case, hyphens split, units in one written form (the engines
    write "millimetres", "millimeters" and "mm" for the same word)."""
    t = (text or "").lower().replace("-", " ")
    for pattern, unit in _UNIT_NORMAL:
        t = pattern.sub(unit, t)
    t = re.sub(r"(\d)(mm|cm|ml)\b", r"\1 \2", t)
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", t)


def _live_tokens(words: list[dict]) -> list[tuple[str, str]]:
    """(token, the punctuated word it came from) per token of the live final."""
    out = []
    for w in words:
        for t in _tok(w.get("punctuated_word") or w.get("word", "")):
            out.append((t, w.get("punctuated_word") or w.get("word", "")))
    return out


def _switchable(tokens: list[str]) -> bool:
    return bool(tokens) and not any(t in _FORMAT or t in _UNITS or t[0].isdigit() for t in tokens)


@dataclass(frozen=True)
class Span:
    live: str  # the words as the live stream heard them (plain)
    options: tuple[str, ...]  # other engines' readings, in order, de-duplicated
    left: str  # plain context before and after, from the live final
    right: str


def disagreements(live_words: list[dict], others: dict[str, str]) -> list[Span]:
    live = [t for t, _ in _live_tokens(live_words)]
    found: dict[tuple[int, int], list[str]] = {}
    for text in others.values():
        other = _tok(text)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, live, other, autojunk=False).get_opcodes():
            if tag != "replace":  # insertions/deletions: not a word misheard in place
                continue
            a, b = live[i1:i2], other[j1:j2]
            if not (_switchable(a) and _switchable(b)) or len(a) > 3 or len(b) > 3:
                continue
            reading = " ".join(b)
            if reading not in found.setdefault((i1, i2), []):
                found[(i1, i2)].append(reading)
    return [Span(live=" ".join(live[i1:i2]), options=tuple(opts),
                 left=" ".join(live[max(0, i1 - CONTEXT_WORDS):i1]), right=" ".join(live[i2:i2 + CONTEXT_WORDS]))
            for (i1, i2), opts in sorted(found.items())]


def switch_questions(spans: list[Span]) -> dict[str, dict[str, Any]]:
    """One two-way Jev choice per alternative reading: the passage as heard against it. Three-way
    choices spread Jev's confidence (live: "Tarlov" picked at 0.83 against "tidal" and "tunnel
    of"); the 31/34 experiment was two-way."""
    def passage(words: str, s: Span) -> str:
        return " ".join(x for x in (s.left, words, s.right) if x)
    return {
        f"span_{i}_{k}": {
            "type": "choice",
            "instructions": "Which version of this dictated passage is what the radiologist said, "
                            "judged by clinical sense for this scan and by the surrounding words?",
            "criteria": {"as_heard": passage(s.live, s), "option": passage(o, s)},
        }
        for i, s in enumerate(spans) for k, o in enumerate(s.options)
    }


def switch_allowed(live: str, replacement: str, confidence: float) -> bool:
    if confidence < SWITCH_MIN_CONF:
        return False
    kept = {m.group(0).lower() for m in _GUARDED.finditer(replacement)}
    return all(m.group(0).lower() in kept for m in _GUARDED.finditer(live))


def recovered_prefix(live_words: list[dict], batch_words: list[dict], other_text: str | None = None) -> str | None:
    """Words the batch pass heard before the live final's first word: speech the stream dropped
    (lab: a phrase lost at a forced final). A confident run of ≥ 2 words; a single word only
    when the independent engine (other_text) heard it too (lab: "Actually," dropped after a
    flush that went out just before the word became audible)."""
    live = [t for t, _ in _live_tokens(live_words)]
    batch = [(t, w) for w in batch_words for t in _tok(w.get("punctuated_word") or w.get("word", ""))]
    tokens = [t for t, _ in batch]
    # The live final is the latest speech: find where it starts in the batch text from the END
    # (a repeated phrase would otherwise match its first, dropped, occurrence).
    lead = None
    for start in range(len(tokens) - len(live), -1, -1):
        if difflib.SequenceMatcher(None, tokens[start:start + len(live)], live, autojunk=False).ratio() >= 0.8:
            lead = start
            break
    if lead is None:
        return None
    if lead == 0:
        return None
    if lead < RECOVER_MIN_WORDS:
        other = _tok(other_text or "")
        if other[:lead] != tokens[:lead] or other[lead:lead + 2] != live[:2]:
            return None
    seen, words = set(), []
    for _, w in batch[:lead]:
        if id(w) not in seen:
            seen.add(id(w))
            words.append(w)
    if min(w.get("confidence", 0.0) for w in words) < RECOVER_MIN_CONF:
        return None
    return " ".join(w.get("punctuated_word") or w.get("word", "") for w in words)


# --- orchestration (lab, RR_TWO_PASS=1) -------------------------------------------------------

import asyncio
import io
import logging
import json
import os
import time
import wave
from typing import Awaitable, Callable

import numpy as np

logger = logging.getLogger(__name__)
CLIP_TAIL_S = 0.3
ENGINE_TIMEOUT_S = 4.0


def wav16k(pcm: bytes, sample_rate: int) -> bytes:
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
    if sample_rate != 16000 and sample_rate % 16000 == 0:  # average, then decimate
        k = sample_rate // 16000
        samples = samples[: len(samples) // k * k].reshape(-1, k).mean(axis=1).astype(np.int16)
        sample_rate = 16000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


class TwoPass:
    """Per websocket session: buffer the audio sent to Deepgram; for each live final, hear the
    audio since the previous final again (Deepgram batch + gpt-4o-transcribe, in parallel), and
    let Jev choose where the readings differ. Never delays the live final; fails open."""

    def __init__(self, sample_rate: int, *, scan_type: str = "",
                 batch: Callable[[bytes], Awaitable[tuple[str, list]]] | None = None,
                 gpt: Callable[[bytes], Awaitable[str]] | None = None,
                 jev: Callable[[dict], Awaitable[dict]] | None = None) -> None:
        self.sample_rate = sample_rate
        self.scan_type = scan_type
        self._batch, self._gpt, self._jev = batch, gpt, jev
        self._buf = bytearray()
        self._buf_start_s = 0.0  # audio time of self._buf[0]
        self._prev_end_s = 0.0

    def feed(self, pcm: bytes) -> None:
        self._buf.extend(pcm)

    def _clip(self, start_s: float, end_s: float) -> bytes:
        bps = 2 * self.sample_rate
        a = max(0, int((start_s - self._buf_start_s) * self.sample_rate)) * 2
        b = max(a, int((end_s - self._buf_start_s) * self.sample_rate)) * 2
        clip = bytes(self._buf[a:b])
        keep = a  # audio before this clip is never needed again
        del self._buf[:keep]
        self._buf_start_s += keep / bps
        return wav16k(clip, self.sample_rate)

    async def revise(self, final_seq: int, alternative: dict) -> dict:
        t0 = time.perf_counter()
        words = alternative.get("words") or []
        end = (words[-1]["end"] if words else self._prev_end_s) + CLIP_TAIL_S
        clip = self._clip(self._prev_end_s, end)
        self._prev_end_s = end
        errors: list[str] = []

        async def guarded(name, fn):
            if fn is None:
                return None
            try:
                return await asyncio.wait_for(fn(clip), ENGINE_TIMEOUT_S)
            except Exception as e:  # fail open: the live final stands
                errors.append(name)
                logger.warning("[two_pass] %s failed: %s", name, type(e).__name__)
                return None

        batch, gpt_text = await asyncio.gather(guarded("batch", self._batch), guarded("gpt", self._gpt))
        others = {}
        if batch:
            others["batch"] = batch[0]
        if gpt_text:
            others["gpt"] = gpt_text
        spans = disagreements(words, others)
        recovered = recovered_prefix(words, batch[1], gpt_text) if batch else None
        switches, suggestions = [], []
        if spans and self._jev:
            body = {"state": {"scan_type": self.scan_type, "dictation": alternative.get("transcript", "")},
                    "questions": switch_questions(spans)}
            try:
                answers = await asyncio.wait_for(self._jev(body), ENGINE_TIMEOUT_S)
            except Exception as e:
                errors.append("jev")
                logger.warning("[two_pass] jev failed: %s", type(e).__name__)
                answers = {}
            for i, s in enumerate(spans):
                preferred = []  # alternatives Jev picked over the live words, with confidence
                for k, reading in enumerate(s.options):
                    a = answers.get(f"span_{i}_{k}") or {}
                    if a.get("choice") == "option":
                        preferred.append((float(a.get("confidence") or 0.0), reading))
                if not preferred:
                    continue
                conf, reading = max(preferred)  # the reading Jev prefers most confidently
                item = {"from": s.live, "to": reading, "confidence": round(conf, 2)}
                if switch_allowed(s.live, reading, conf):
                    switches.append(item)
                elif conf >= SUGGEST_MIN_CONF and switch_allowed(s.live, reading, 1.0):  # short on confidence only
                    suggestions.append(item)
        rev = {"final_seq": final_seq, "switches": switches, "suggestions": suggestions, "recovered": recovered,
               "spans": len(spans),
               "errors": errors, "ms": int((time.perf_counter() - t0) * 1000)}
        logger.info("[two_pass] %s", json.dumps({"final_seq": final_seq, "spans": len(spans), "switches": len(switches),
                                                 "suggestions": len(suggestions),
                                                 "recovered_words": len((recovered or "").split()), "errors": errors,
                                                 "ms": rev["ms"]}))
        return rev


def two_pass_from_env(sample_rate: int, keyterms: list[str] | None, scan_type: str) -> tuple[TwoPass, Any] | None:
    """(TwoPass, http client to close) with the real engines, or None unless RR_TWO_PASS=1 and
    RR_TRIAGE_DEBUG=1 (lab). gpt-4o-transcribe is skipped without OPENAI_API_KEY."""
    if not (os.environ.get("RR_TWO_PASS") == "1" and os.environ.get("RR_TRIAGE_DEBUG") == "1"):
        return None
    import httpx
    from .deepgram_spelling import UK_SPELLING
    from .dictation_triage import JEV_MODEL
    from .jev_client import jev_post

    dg_key, oai_key, jev_key = (os.environ.get(k, "") for k in ("DEEPGRAM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"))
    client = httpx.AsyncClient(timeout=ENGINE_TIMEOUT_S)
    terms = list(keyterms or [])
    dg_params = [("model", "nova-3-medical"), ("language", "en-GB"), ("smart_format", "true"), ("numerals", "true"),
                 ("measurements", "true"), ("mip_opt_out", "true")] + [("keyterm", k) for k in terms] \
        + [("replace", f"{a}:{b}") for a, b in UK_SPELLING.items()]
    prompt = "Radiology dictation. " + ", ".join(terms)[:700]  # as in the bake-off

    async def batch(wav: bytes):
        r = await client.post("https://api.deepgram.com/v1/listen", params=dg_params, content=wav,
                              headers={"Authorization": f"Token {dg_key}", "Content-Type": "audio/wav"})
        r.raise_for_status()
        alt = r.json()["results"]["channels"][0]["alternatives"][0]
        return alt.get("transcript", ""), alt.get("words") or []

    async def gpt(wav: bytes):
        r = await client.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {oai_key}"},
                              files={"file": ("clip.wav", wav, "audio/wav")},
                              data={"model": "gpt-4o-transcribe", "language": "en", "prompt": prompt,
                                    "response_format": "json", "temperature": "0"})
        r.raise_for_status()
        return r.json().get("text", "")

    async def jev(body: dict):
        r = await jev_post({"model": JEV_MODEL, **body}, jev_key, ENGINE_TIMEOUT_S, None)
        r.raise_for_status()
        return r.json().get("answers") or {}

    tp = TwoPass(sample_rate, scan_type=scan_type, batch=batch if dg_key else None,
                 gpt=gpt if oai_key else None, jev=jev if jev_key else None)
    return tp, client
