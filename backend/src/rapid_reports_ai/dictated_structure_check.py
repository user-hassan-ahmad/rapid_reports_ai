"""A dictated value written against another structure (spec 2026-10-17, dictated fidelity step 3).

Dictated "aortic sinus 4.1 cm", report "aortic root 4.1 cm": the number check passes, the site changed. Each dictated
chain with a unit is paired with the FINDINGS sentences that hold it (`dictated_number_check.pairs`). A pair whose
report sentence contains the dictated sentence (normalised) passes in code; the rest go to Jev in one request (W1
wording, at most MAX_PAIRS, in report order; any beyond are logged `structure_name_unchecked` and give no item). A
pair is a different site when P(yes) < SAME_SITE_MIN; a chain passes when any of its sentences is the same site.
A failing chain is one review flag (severity high: an action card), anchored on its first FINDINGS sentence, with
a replace edit back to the dictated sentence only when that cannot lose or repeat content. Never applied here, never
raises; a Jev error, timeout or partial answer gives no item and logs `structure_name_check_unavailable`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Dict, Iterable, List, Optional

from . import dictated_number_check as dnc

logger = logging.getLogger(__name__)

KIND = "dictated_structure_changed"
FLAG = "RR_DICTATED_STRUCTURES"
SAME_SITE_MIN = 0.7    # P(yes) below this: a different site (lab 2026-10-17 §7)
MAX_PAIRS = 12
TIMEOUT_S = 3.0        # as jev_stack.TIMEOUT_S
LABEL = "Different site from your dictation? Apply puts your sentence back."
LABEL_NO_EDIT = "Different site from your dictation? Check this sentence."


Ask = Callable[[List[dnc.Pair]], Awaitable[List[float]]]


def enabled() -> bool:
    """Off unless RR_DICTATED_STRUCTURES is 1/true/on (read per call)."""
    return os.environ.get(FLAG, "0").strip().lower() in ("1", "true", "on")


def question(key: str) -> dict:
    """The lab wording W1, verbatim."""
    return {"type": "noul", "instructions":
            f"In {key}, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and "
            f"level as the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site "
            f"does not."}


def state(ps: List[dnc.Pair]) -> Dict[str, dict]:
    return {f"pair_{i + 1}": {"dictated": p.dictated, "report": p.report} for i, p in enumerate(ps)}


async def ask_same_site(ps: List[dnc.Pair]) -> List[float]:
    """P(same site) per pair, in order: one Jev request."""
    from .jev_client import JEV_MODEL, jev_post
    qs = {f"pair_{i + 1}": question(f"pair_{i + 1}") for i in range(len(ps))}
    r = await jev_post({"model": JEV_MODEL, "state": state(ps), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out: List[float] = []
    for i in range(len(ps)):
        p = (ans.get(f"pair_{i + 1}") or {}).get("noul")
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise ValueError("jev: incomplete answers")   # a missing answer is never "different site"
        out.append(float(p))
    return out


def code_pass(p: dnc.Pair) -> bool:
    """The report sentence holds the dictated sentence word for word (case, whitespace, punctuation aside)."""
    return dnc.norm(p.dictated) in dnc.norm(p.report)


async def changed_structures(report: Optional[str], sources: Iterable[Optional[str]], removed: Iterable[str] = (),
                             ask: Optional[Ask] = None) -> List[dict]:
    """[{"kind", "severity": "high", "text", "sentence", "dictated_quote", "message", "edit"}], one per dictated
    chain whose every FINDINGS sentence Jev reads as a different site. `sources`: the radiologist's own statements
    (as for the number check); `removed`: the sentences the radiologist removed. Never raises."""
    try:
        report = report or ""
        sources = [s for s in sources if s]
        ps = dnc.pairs(report, sources, removed)
        asked = [p for p in ps if not code_pass(p)]
        if len(asked) > MAX_PAIRS:
            logger.info("structure_name_unchecked: %d pairs over the cap of %d", len(asked) - MAX_PAIRS, MAX_PAIRS)
        asked = asked[:MAX_PAIRS]
        same: Dict[dnc.Pair, Optional[bool]] = {p: (True if code_pass(p) else None) for p in ps}
        if asked:
            try:
                probs = await asyncio.wait_for((ask or ask_same_site)(asked), TIMEOUT_S)
                if len(probs) != len(asked):
                    raise ValueError("jev: answer count mismatch")
            except Exception as e:  # noqa: BLE001 - fail open: no item
                logger.info("structure_name_check_unavailable (%s: %s)", type(e).__name__, str(e)[:200])
                return []
            for p, pr in zip(asked, probs):
                same[p] = pr >= SAME_SITE_MIN
        groups: Dict[tuple, List[dnc.Pair]] = {}
        for p in ps:   # report order: a chain's first pair is its first FINDINGS sentence
            groups.setdefault((p.dictated, p.chain), []).append(p)
        out: List[dict] = []
        for (dictated, chain), gp in groups.items():
            if any(same[p] is not False for p in gp):   # passes if any sentence is the same site; unasked: unknown
                continue
            out.append({"kind": KIND, "severity": "high", "text": chain, "sentence": gp[0].report,
                        "dictated_quote": dictated, "message": LABEL_NO_EDIT, "edit": None})
        return out
    except Exception as e:  # noqa: BLE001 - a flag is never worth a failed report
        logger.info("structure_name_check_unavailable (%s: %s)", type(e).__name__, str(e)[:200])
        return []


__all__ = ["KIND", "FLAG", "SAME_SITE_MIN", "MAX_PAIRS", "TIMEOUT_S", "LABEL", "LABEL_NO_EDIT", "enabled", "question",
           "state", "ask_same_site", "code_pass", "changed_structures"]
