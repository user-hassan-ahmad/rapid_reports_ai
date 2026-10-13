"""Did the polish move words onto another finding? One Jev question, asked only when the code
detector (lean_fidelity.moved_into_earlier) fires: new words placed before dictated text, new words
out of spoken order, a side or number shifting between dictated sentences, or a new sentence merged.

Lab 2026-10-12 (24 hand-written pairs, scratchpad_v2_labs.py attach on feat/hybrid-stack):
moved side/location/size/descriptor 12/12 at >= 0.3 (live case 0.63, lowest 0.39); tidying,
joined fragments, joined related findings, spoken corrections and a descriptor naming its own
structure 0/12 (highest 0.16). A flag keeps the span and appends the words as said, so the
threshold leans low; a failure counts as moved.

Whole guard (detector then Jev, 28 pairs incl. 3 swaps with no new words): moved 15/15, same meaning
0/13 flagged (the detector fires on 8 joins; Jev clears them, highest 0.17). Replay of 111 real lean
polishes over 20 dictations: 0 fires. Jev sits near the line on two pairs (live case ~0.55, a moved
"with a distal stone" ~0.39); one earlier run dipped one pair under 0.3.
"""
from __future__ import annotations

import logging
import os

from .jev_client import JEV_MODEL, jev_post

logger = logging.getLogger(__name__)

MOVED_MIN = 0.3
TIMEOUT_S = 3.0
QUESTION = (
    "Compared with SPOKEN, the CLEANED text attaches a side, location, measurement or descriptor to a different "
    "finding than the spoken words do (words moved from where they were said onto another finding), rather than "
    "only tidying, joining fragments of the same sentence, joining related findings without changing what each "
    "one says, or applying a spoken correction.")


async def moved_score(spoken: str, cleaned: str, transport=None) -> float | None:
    """P(the cleaned text moved words onto another finding); None when Jev fails."""
    try:
        r = await jev_post({"model": JEV_MODEL, "state": f"SPOKEN:\n{spoken}\n\nCLEANED:\n{cleaned}",
                            "questions": {"q": {"type": "noul", "instructions": QUESTION}}},
                           os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
        r.raise_for_status()
        return float(((r.json().get("answers") or {}).get("q") or {}).get("noul") or 0.0)
    except Exception as e:
        logger.warning("[polish.attachment] %s: %s", type(e).__name__, str(e)[:200])
        return None
