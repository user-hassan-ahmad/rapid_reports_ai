"""Dictated gate (spec docs/superpowers/specs/2026-10-10-dictated-gate-review-tiers-design.md).

One owner for "is this report clause dictated?": one Jev choice per Jev-pass clause (FINDINGS + IMPRESSION on quick
reports), asked against the RAW dictation (scan type, history as context only, dictated findings). A clause is
dictated only when P(all_stated) >= GATE_MIN; everything else counts as added (default added: a miss costs a tint,
never hides AI text). A tier rule over the gate verdict and the Jev statement type then decides display:
quiet (routine added normal / bolted-on negative, AI toggle), review recommendation, or review synthesis (violet on
the added words).

Lab evidence (scratchpad labs/gate_a, confirm, confirm2, sorter; Jev 1.13, 2 runs): over 24 prod reports the
live system left 54 AI clauses plain against 3-4 for this gate, with 6/75 dictated clauses tinted; the sorter
(tier rule) caught 64-65/70 review items at precision 0.97, ~2.75 highlights per report.

RR_DICTATED_GATE = off (default) | shadow (ask and log, display unchanged) | live (the gate's items replace
provenance's; today's path is the fallback on any gate failure)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .items import ReviewInput

GATE_MIN = 0.7          # P(all_stated) >= this → dictated (lab Q3s: lowest firm-gold dictated clause 0.74-0.80)
CHUNK = 4               # clauses per Jev request (the lab's batch size)
DETECTOR = "dictated_gate"
CHOICES = ("all_stated", "some_details_added", "not_stated")


def mode() -> str:
    v = (os.environ.get("RR_DICTATED_GATE") or "off").strip().lower()
    return v if v in ("off", "shadow", "live") else "off"


def q_gate(clause: str) -> dict:
    """Lab arm Q3s, verbatim (scratchpad labs/gate_a/run_jev.py)."""
    return {"type": "choice", "instructions": (
        f'The report says: "{clause}". Compare every detail in it with the dictated findings: each finding, '
        "structure, side, level, size, descriptor, negated item, diagnosis, cause and recommendation."),
        "criteria": {"all_stated": "Every detail in the statement is stated in the dictated findings, in the same or "
                                   "other words (synonym, abbreviation, expansion or reordering).",
                     "some_details_added": "The dictation states part of it, but the statement adds at least one detail "
                                           "the dictation does not state: a descriptor, an extra negated item, a "
                                           "diagnosis, a cause or an inference.",
                     "not_stated": "The dictation does not state it; it was added by the report writer."}}


def state(inp: ReviewInput) -> str:
    h = (f"CLINICAL HISTORY (context only; it is NOT part of the dictated findings): {inp.clinical_history}\n"
         if inp.clinical_history else "")
    return f"SCAN TYPE: {inp.scan_type}\n{h}DICTATED FINDINGS:\n{inp.artifacts.dictated_findings}"


def questions(clauses: List[str]) -> List[Dict[str, dict]]:
    """One {g{i}: question} dict per request, CHUNK clauses each, i indexing `clauses`."""
    return [{f"g{i}": q_gate(clauses[i]) for i in range(k, min(k + CHUNK, len(clauses)))}
            for k in range(0, len(clauses), CHUNK)]


def p_all_stated(ans: Any) -> Optional[float]:
    """P(all_stated) of a gate answer; a bare choice counts 1 / 0; None when unreadable."""
    if not isinstance(ans, dict):
        return None
    probs = ans.get("probabilities")
    if isinstance(probs, dict) and any(k in probs for k in CHOICES):
        try:
            return float(probs.get("all_stated", 0) or 0)
        except (TypeError, ValueError):
            return None
    ch = ans.get("choice")
    return None if ch not in CHOICES else (1.0 if ch == "all_stated" else 0.0)
