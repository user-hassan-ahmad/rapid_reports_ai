"""The spoken-command lexicon (new paragraph, new line, full stop …) used by fast_append.

It mirrors main.process_dictation_transcript plus the spoken forms the lab feeder types.
(The lab-only triage router that acted on a decision without the live model was retired
on 2026-09-29; decision-first routing lives in fast_append.)
"""
from __future__ import annotations

import re
_FORMATTING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\\n\\n>"), "\n\n"),
    (re.compile(r"<\\n>"), "\n"),
    (re.compile(r"\bnew\s+paragraph\b", re.IGNORECASE), "\n\n"),
    (re.compile(r"\bnew\s+line\b", re.IGNORECASE), "\n"),
    (re.compile(r"\bfull\s*stop\b", re.IGNORECASE), "."),
)


def map_formatting(utterance: str) -> str:
    """Return only the characters a formatting utterance stands for ('' if none)."""
    out: list[str] = []
    for pattern, replacement in _FORMATTING_RULES:
        for _ in pattern.findall(utterance or ""):
            out.append(replacement)
    return "".join(out)
