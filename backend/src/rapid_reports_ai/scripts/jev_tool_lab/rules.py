"""Jev answer bands and Qwen's declared decision rule (spec §2.3, §3 arm B).

Bands are fixed with a wide margin, never tuned on the pilot: repeat drift is up to 0.2 (wording suite)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .catalogue import CANT_TELL

UNSURE = "unsure"
NOUL_HI = 0.7
NOUL_LO = 0.3
CHOICE_MARGIN = 0.2


class Condition(BaseModel):
    q: str        # question id
    want: str     # "yes" / "no" for a noul; an option key ("o1", ...) for a choice
    label: str    # what the condition checks, in a few words; becomes the missing-input text


class Rule(BaseModel):
    all_of: List[Condition]


def _p_yes(ans: Any) -> Optional[float]:
    try:
        return float(ans["noul"] if isinstance(ans, dict) else ans)
    except Exception:
        return None


def band(ans: Any, jev_type: str) -> str:
    """'yes' / 'no' for a noul, the chosen option key for a choice, or UNSURE."""
    if jev_type == "choice":
        try:
            probs = {k: float(v) for k, v in ans["probabilities"].items()}
        except Exception:
            return UNSURE
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked or ranked[0][0] == CANT_TELL:
            return UNSURE
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < CHOICE_MARGIN:
            return UNSURE
        return ranked[0][0]
    p = _p_yes(ans)
    if p is None:
        return UNSURE
    if p >= NOUL_HI:
        return "yes"
    if p <= NOUL_LO:
        return "no"
    return UNSURE


def evaluate(rule: Rule, banded: Dict[str, str]) -> Tuple[str, List[str]]:
    """('yes', []) when every condition holds; ('no', failed labels) when any condition definitely fails;
    (UNSURE, []) otherwise, including an empty rule or a condition on a dropped question."""
    if not rule.all_of:
        return UNSURE, []
    failed, unsure = [], False
    for c in rule.all_of:
        got = banded.get(c.q, UNSURE)
        if got == UNSURE:
            unsure = True
        elif got != c.want:
            failed.append(c.label)
    if failed:
        return "no", failed
    return (UNSURE, []) if unsure else ("yes", [])
