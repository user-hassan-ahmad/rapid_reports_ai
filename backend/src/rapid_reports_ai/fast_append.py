"""Verbatim fast-append and the band router (rev 2 §3.1–3.2, work-order step 5). Lab only.

The default operation writes a Deepgram final onto the open line as spoken: Deepgram's
punctuation, our command lexicon, hesitation tokens removed. No model. The band router
decides from one Jev bundle whether that cheap operation is safe; anything it is not sure
of, and any Jev failure, goes to today's polish (fail open). Thresholds live in
jev_questions.FAST_APPEND_BANDS; time and punctuation are decided here, never by Jev.

Spec: docs/superpowers/specs/2026-09-24-decision-first-dictation-design.md §3.1, §3.2
Plan: docs/superpowers/plans/2026-09-26-live-lab-fast-append.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .dictation_triage_router import _FORMATTING_RULES, map_formatting
from .jev_questions import FAST_APPEND_BANDS
from .utterance_bundle import BundleDecision

Route = Literal["fast_append", "command", "polish", "skip"]

# Hesitation tokens only, as whole words. Lowercase or capitalised forms, never all caps
# ("ER" is oestrogen receptor); "mm" is never a filler (millimetres).
_FILLER = re.compile(r"(?<![\w'-])(?:[Uu]m+|[Uu]h+m*|[Ee]rm+|[Ee]r|[Aa]h+|[Hh]m+)(?![\w'-]),?")
_TERMINAL = re.compile(r"(?:[.?!][\"')\]]*|\n)$")


def clean_verbatim(text: str) -> str:
    """Deepgram text → scratchpad text: lexicon, fillers out, whitespace tidied."""
    s = text or ""
    for pattern, replacement in _FORMATTING_RULES:
        s = pattern.sub(replacement, s)
    s = _FILLER.sub("", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r" +([.,;:?!])", r"\1", s)
    s = re.sub(r",+([.?!])", r"\1", s)
    s = re.sub(r"([.?!])\.+", r"\1", s)
    s = re.sub(r",{2,}", ",", s)
    s = re.sub(r"^[ ,.;:]+", "", s)
    return s.strip(" \t")


def closes_line(text: str) -> bool:
    """Terminal punctuation (Deepgram is sure of these) or a lexicon newline."""
    return bool(_TERMINAL.search((text or "").rstrip(" \t")))


def is_filler_only(utterance: str) -> bool:
    """Nothing left after cleaning and no command in it: skipped by code, Jev not asked."""
    return not clean_verbatim(utterance).strip() and not map_formatting(utterance)


# Deepgram punctuates "Full stop." itself, so the websocket's conversion arrives as "..".
_BARE_MARK = re.compile(r"^\s*([.?!])[.?!\s]*$")


def code_route(utterance: str) -> "RouteResult | None":
    """Utterances decided by code, Jev never asked. A final that is only a terminal mark
    is a spoken "full stop" the websocket already converted (cleaning would drop it as
    stray punctuation); filler-only finals are skipped. None: ask Jev."""
    m = _BARE_MARK.match(utterance or "")
    if m:
        return RouteResult("command", "punctuation_mark", "", m.group(1), True, False)
    if is_filler_only(utterance):
        return RouteResult("skip", "empty_after_clean", "", "", False, False)
    return None


@dataclass(frozen=True)
class RouteResult:
    route: Route
    reason: str
    text: str  # cleaned verbatim text (fast_append); "" otherwise
    insert: str  # characters a command stands for (command); "" otherwise
    closes_line: bool
    close_on_silence: bool  # standalone ≥ τ: the open line may close at the silence milestone


def route_bundle(
    decision: BundleDecision | BaseException, utterance: str, asr_min_conf: float | None = None
) -> RouteResult:
    text = clean_verbatim(utterance)
    pre = code_route(utterance)
    if pre is not None:
        return pre
    if isinstance(decision, BaseException):
        return RouteResult("polish", "jev_error", "", "", True, False)

    b = FAST_APPEND_BANDS
    t = decision.triage
    confidence = t.confidence if t.confidence is not None else 0.0
    on_silence = decision.standalone >= b["line_close_standalone"]

    def polish(reason: str) -> RouteResult:
        return RouteResult("polish", reason, "", "", True, on_silence)

    if t.action == "append_new_finding":
        if confidence < b["append_act"]:
            return polish("append_low_confidence")
        if (t.is_correction or 0.0) >= b["append_max_is_correction"]:
            return polish("correction_signal")
        if not text.strip():
            return polish("append_no_words")  # a bare command read as an append
        if asr_min_conf is not None and asr_min_conf < b["append_min_asr_conf"]:
            return polish("asr_low_confidence")  # a fluent mishearing reads as a confident append
        return RouteResult("fast_append", "append_confident", text, "", closes_line(text), on_silence)
    if t.action == "formatting_command":
        if confidence < b["command_act"]:
            return polish("command_low_confidence")
        insert = map_formatting(utterance)
        if not insert:
            return polish("command_unmapped")
        return RouteResult("command", "command_lexicon", "", insert, True, on_silence)
    return polish(f"action:{t.action}")


def asr_confidence(alternative: dict) -> dict | None:
    """Deepgram's confidence for one final, as numbers only (never the words): the
    alternative's score and each word's, in order. Rev 2 plans word confidence as the
    ASR gate; step 5 only records it so step 7 can test whether it separates misheard
    fragments from clean ones. None when Deepgram sent no word scores."""
    words = alternative.get("words") if isinstance(alternative, dict) else None
    if not isinstance(words, list):
        return None
    confs = [round(float(w["confidence"]), 4) for w in words
             if isinstance(w, dict) and isinstance(w.get("confidence"), (int, float))]
    if not confs:
        return None
    conf = alternative.get("confidence")
    return {
        "asr_conf": round(float(conf), 4) if isinstance(conf, (int, float)) else None,
        "asr_word_confs": confs,
        "asr_min_conf": min(confs),
    }
