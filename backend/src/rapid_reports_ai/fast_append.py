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
from .spoken_format import (
    apply_spoken_format,
    ends_with_heading,
    format_heading_lines,
    heading_only,
    level_only,
    resolve_colon,
    starts_paragraph,
)
from .utterance_bundle import BundleDecision

Route = Literal["fast_append", "command", "polish", "skip"]

# Hesitation tokens only, as whole words. Lowercase or capitalised forms, never all caps
# ("ER" is oestrogen receptor); "mm" is never a filler (millimetres).
_FILLER = re.compile(r"(?<![\w'-])(?:[Uu]m+|[Uu]h+m*|[Ee]rm+|[Ee]r|[Aa]h+|[Hh]m+)(?![\w'-]),?")
_TERMINAL = re.compile(r"(?:[.?!][\"')\]]*|\n)$")


def clean_verbatim(text: str) -> str:
    """Deepgram text → scratchpad text: lexicon, spoken punctuation and disc levels,
    fillers out, whitespace tidied. The context-dependent 'colon' is resolved later."""
    s = text or ""
    for pattern, replacement in _FORMATTING_RULES:
        s = pattern.sub(replacement, s)
    s = apply_spoken_format(s)
    s = _FILLER.sub("", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n[ ,.;:]+", "\n", s)  # "New paragraph." → "\n\n." : no stray mark after a break
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


_BARE_COLON = re.compile(r"^[\s,.]*colon[\s,.:]*$", re.IGNORECASE)


def code_route(utterance: str, preceding: str = "") -> "RouteResult | None":
    """Utterances decided by code, Jev never asked. A final that is only a terminal mark
    is a spoken "full stop" the websocket already converted (cleaning would drop it as
    stray punctuation); a bare 'colon' right after a heading or disc level is ':'; a
    heading said on its own is written as one; filler-only finals are skipped. None: ask Jev."""
    m = _BARE_MARK.match(utterance or "")
    if m:
        return RouteResult("command", "punctuation_mark", "", m.group(1), True, False)
    if _BARE_COLON.match(utterance or ""):
        resolved, ambiguous = resolve_colon("colon", preceding)
        if resolved == ":" and not ambiguous:
            return RouteResult("command", "spoken_colon", "", ":", False, False)
        return None
    level = level_only(utterance)
    if level:
        return RouteResult("fast_append", "level", level, "", False, False, starts_paragraph=True, clean_text=level)
    heading = heading_only(utterance)
    if heading:
        return RouteResult("fast_append", "heading", heading, "", True, False, starts_paragraph=True, clean_text=heading)
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
    starts_paragraph: bool = False  # the text opens with a disc level or a heading
    clean_text: str = ""  # the cleaned, resolved utterance: what polish is given too


def route_bundle(
    decision: BundleDecision | BaseException,
    utterance: str,
    asr_min_conf: float | None = None,
    preceding: str = "",
) -> RouteResult:
    text, colon_ambiguous = resolve_colon(clean_verbatim(utterance), preceding)
    text = format_heading_lines(text)
    pre = code_route(utterance, preceding)
    if pre is not None:
        return pre
    if isinstance(decision, BaseException):
        return RouteResult("polish", "jev_error", "", "", True, False, clean_text=text)

    b = FAST_APPEND_BANDS
    t = decision.triage
    confidence = t.confidence if t.confidence is not None else 0.0
    on_silence = decision.standalone >= b["line_close_standalone"]

    def polish(reason: str) -> RouteResult:
        return RouteResult("polish", reason, "", "", True, on_silence, clean_text=text)

    def append(reason: str, body: str, paragraph: bool) -> RouteResult:
        return RouteResult("fast_append", reason, body, "", closes_line(body), on_silence,
                           starts_paragraph=paragraph, clean_text=body)

    def unsafe_to_append() -> str | None:
        if (t.is_correction or 0.0) >= b["append_max_is_correction"]:
            return "correction_signal"
        if asr_min_conf is not None and asr_min_conf < b["append_min_asr_conf"]:
            return "asr_low_confidence"  # a fluent mishearing reads as a confident append
        if colon_ambiguous:
            return "colon_ambiguous"  # organ or punctuation: the context does not say
        return None

    if t.action == "append_new_finding":
        if confidence < b["append_act"]:
            return polish("append_low_confidence")
        if not text.strip():
            return polish("append_no_words")  # a bare command read as an append
        unsafe = unsafe_to_append()
        if unsafe:
            return polish(unsafe)
        return append("append_confident", text, starts_paragraph(text) and not ends_with_heading(preceding))
    if t.action == "formatting_command":
        if confidence < b["command_act"]:
            return polish("command_low_confidence")
        insert = map_formatting(utterance)
        if not insert:
            return polish("command_unmapped")
        if re.search(r"\w", text):
            # command and content in one final ("New paragraph. Conclusion."): the command
            # alone would drop the content. The cleaned text already carries the command.
            unsafe = unsafe_to_append()
            if unsafe:
                return polish(unsafe)
            lead = text.startswith("\n\n")
            body = text.lstrip("\n") if lead else text
            return append("command_with_text", body,
                          lead or (starts_paragraph(body) and not ends_with_heading(preceding)))
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
