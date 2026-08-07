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
    drives whether generation is gated.

    ``start``/``end`` are character offsets into the text exactly as supplied,
    so the editor can decorate the offending span directly. They are offsets
    rather than a text span (the pattern the report audit uses) because the
    token at fault is usually a common function word — locating "the" by
    string search would decorate the first one in the document, not the one
    that is actually dangling.
    """

    kind: str  # "truncation" | "dangling_measurement"
    severity: str  # "high" | "medium"
    excerpt: str
    message: str
    start: int
    end: int


def _last_content_line(text: str) -> tuple[str, int]:
    """The last line with any content, and its start offset in ``text``.

    Trailing blank lines must not mask a truncation on the line above. The
    offset is returned against the original string — not a stripped copy — so
    the caller can hand editor-ready positions to the frontend.
    """
    result = ("", 0)
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            result = (stripped, offset + (len(line) - len(line.lstrip())))
        offset += len(line)
    return result


def check_dictation(text: str | None) -> list[IntegrityFlag]:
    """Return integrity flags for a dictation. An empty list means clean.

    Only the final content line is examined: truncation is an end-of-input
    phenomenon. Mid-text fragments are normal dictation style, not defects.
    """
    if not text or not text.strip():
        return []

    line, line_start = _last_content_line(text)
    if not line:
        return []

    measurement = _DANGLING_MEASUREMENT.search(line)
    if measurement:
        return [
            IntegrityFlag(
                kind="dangling_measurement",
                severity="high",
                excerpt=line[-_EXCERPT_CHARS:],
                message=(
                    "This measurement looks incomplete — a dimension may be "
                    "missing. Confirm before generating."
                ),
                start=line_start + measurement.start(),
                end=line_start + measurement.end(),
            )
        ]

    if line[-1] in _TERMINAL_PUNCTUATION:
        return []

    tokens = line.split()
    if not tokens:
        return []

    raw_last = tokens[-1]
    last_word = _TRAILING_NON_WORD.sub("", raw_last).lower()
    if last_word in _DANGLING_TAIL:
        # ``line`` is stripped, so it ends with raw_last — the dangling token
        # sits flush against the end of the line.
        end = line_start + len(line)
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
                start=end - len(raw_last),
                end=end,
            )
        ]

    return []
