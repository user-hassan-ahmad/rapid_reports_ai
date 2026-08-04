"""Deterministic integrity checks on raw dictation, run before generation.

Detection only — this module never rewrites the dictation. A pass that
"repairs" a truncation reproduces the failure it exists to prevent: the
generator smoothing an incomplete statement into a confident, complete-looking
report. Flags are surfaced to the radiologist, who decides.

Precision is deliberately favoured over recall. Radiologists dictate in
unpunctuated fragments and bullet lists; a check that fires on every missing
full stop is noise and will be ignored, which is worse than no check. Only a
trailing function word — one that cannot legitimately end a clinical
statement — raises a flag.

These are cheap regex/token rules with no LLM call, so they can run on every
keystroke-idle without cost. Semantic checks (laterality contradiction,
measurement/descriptor mismatch) belong in a separate LLM-backed pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Words that cannot legitimately end a dictated clinical statement. A dictation
# ending here is mid-clause, whatever the punctuation suggests.
_DANGLING_TAIL = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "with",
        "from", "into", "by", "for", "is", "are", "was", "were", "no", "there",
        "within", "without", "measuring", "showing", "demonstrating",
        "which", "that", "than", "but", "between", "adjacent", "overlying",
    }
)

_TERMINAL_PUNCTUATION = ".!?:;"

# "46 x", "4 ×" — a measurement whose next dimension never arrived.
_DANGLING_MEASUREMENT = re.compile(r"\d+\s*(?:x|×)\s*$", re.IGNORECASE)

_TRAILING_NON_WORD = re.compile(r"[^\w-]+$")

_EXCERPT_CHARS = 60


@dataclass(frozen=True)
class IntegrityFlag:
    """One detected problem. ``kind`` drives UI treatment, ``severity``
    drives whether generation is gated."""

    kind: str  # "truncation" | "dangling_measurement"
    severity: str  # "high" | "medium"
    excerpt: str
    message: str


def _last_content_line(text: str) -> str:
    """The last line with any content — trailing blank lines must not mask a
    truncation on the line above."""
    for line in reversed(text.strip().splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def check_dictation(text: str | None) -> list[IntegrityFlag]:
    """Return integrity flags for a dictation. An empty list means clean.

    Only the final content line is examined: truncation is an end-of-input
    phenomenon. Mid-text fragments are normal dictation style, not defects.
    """
    if not text or not text.strip():
        return []

    line = _last_content_line(text)
    if not line:
        return []

    if _DANGLING_MEASUREMENT.search(line):
        return [
            IntegrityFlag(
                kind="dangling_measurement",
                severity="high",
                excerpt=line[-_EXCERPT_CHARS:],
                message=(
                    "This measurement looks incomplete — a dimension may be "
                    "missing. Confirm before generating."
                ),
            )
        ]

    if line[-1] in _TERMINAL_PUNCTUATION:
        return []

    tokens = line.split()
    if not tokens:
        return []

    last_word = _TRAILING_NON_WORD.sub("", tokens[-1]).lower()
    if last_word in _DANGLING_TAIL:
        return [
            IntegrityFlag(
                kind="truncation",
                severity="high",
                excerpt=line[-_EXCERPT_CHARS:],
                message=(
                    f'The dictation appears to end mid-sentence ("…{last_word}"). '
                    "Generating from an incomplete statement can produce a "
                    "confident report with a missing detail. Confirm or complete "
                    "the dictation."
                ),
            )
        ]

    return []
