"""Text identity of two sheet-line texts (spec 2026-10-15-stable-line-ids-design, "Wrong matches are worse than lost
answers"; Hassan's decision 7): two texts are the same line only when they are EXACTLY equal after normalising their
representation, nothing else:

1. lookalike characters unified (en/em dash, minus and other dashes -> "-", curly -> straight quotes and apostrophes,
   the multiplication sign -> "x", Unicode spaces -> space);
2. whitespace collapsed (runs become one space, ends trimmed).

Case, punctuation (a final full stop included), spelling and filler words all stay significant: "No effusion." and
"No effusion", "Oedema" and "Edema", "There is no mass." and "No mass." are different lines. No similarity, no
tokeniser, no clinical gates.

Changing LOOKALIKES changes which lines keep their uid: keep the constant tests green."""
from __future__ import annotations

# Lookalike characters -> one form. The only merging step.
LOOKALIKES = {
    "–": "-", "—": "-", "−": "-", "‒": "-", "‐": "-", "‑": "-",
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'",
    "×": "x",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", "　": " ",
}
_LOOKALIKE = str.maketrans(LOOKALIKES)


def rep_key(text: str) -> str:
    """The text with its representation normalised (lookalikes unified, whitespace collapsed); nothing else changed."""
    return " ".join((text or "").translate(_LOOKALIKE).split())

