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
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .alignment import Alignment, ReportClause
from .claims import content_words
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


# Common radiology abbreviations in a dictation, expanded so the report's spelled-out words are not "new" words.
# Fixed list: it only shapes WHERE a highlight falls inside a clause the gate already called added; never grow it
# by example (spec §4.3; the lab's hand-grown synonym trim overfitted).
ABBREV = {"rll": "right lower lobe", "rul": "right upper lobe", "rml": "right middle lobe", "lll": "left lower lobe",
          "lul": "left upper lobe", "gb": "gallbladder", "cbd": "common bile duct", "vuj": "vesicoureteric junction",
          "uvj": "ureterovesical junction", "rv": "right ventricle", "lv": "left ventricle",
          "sdh": "subdural haematoma", "sah": "subarachnoid haemorrhage", "ich": "intracranial haemorrhage",
          "pe": "pulmonary embolism", "ivc": "inferior vena cava", "smv": "superior mesenteric vein",
          "sma": "superior mesenteric artery", "pv": "portal vein", "pod": "pouch of douglas"}
_NEGATOR = re.compile(r"\b(?:no|not|without|nor)\b", re.I)


@dataclass
class GateClause:
    i: int
    text: str
    start: Optional[int]          # report offsets; None when the clause is not found in the report
    end: Optional[int]
    section: Optional[str]
    p: Optional[float]            # P(all_stated); None when unreadable
    q_type: Optional[str]
    tier: str                     # dictated | quiet | rec | synth | unknown
    runs: List[Tuple[int, int]] = field(default_factory=list)   # report spans of words absent from the dictation
    aclause: Optional[ReportClause] = None                      # the alignment clause holding `start`


def dictated_words(dictation: str) -> set:
    words = set(content_words(dictation))
    for w in re.findall(r"[A-Za-z]+", dictation or ""):
        if w.lower() in ABBREV:
            words |= content_words(ABBREV[w.lower()])
    return words


def _locate(body: str, clauses: List[str]) -> List[Optional[Tuple[int, int]]]:
    out, cur = [], 0
    for t in clauses:
        k = body.find(t, cur)
        if k < 0:
            k = body.find(t)
        if k < 0:
            out.append(None)
            continue
        out.append((k, k + len(t)))
        cur = k + len(t)
    return out


def _negated_only(body: str, s: int, runs: List[Tuple[int, int]]) -> bool:
    """Every added run follows a negator earlier in the same clause: a negative bolted onto a dictated finding."""
    return bool(runs) and all(_NEGATOR.search(body[s:a]) for a, _ in runs)


def tier_of(p: Optional[float], q_type: Optional[str], is_rec: bool, negated_only: bool) -> str:
    """Spec §4.2. Display only: provenance is the gate's (p)."""
    if p is None:
        return "unknown"
    if p >= GATE_MIN:
        return "dictated"
    if q_type == "normal":
        return "quiet"
    if is_rec:
        return "rec"
    if q_type in ("abnormal", "mixed") and negated_only:
        return "quiet"
    return "synth"


def classify(inp: ReviewInput, body: str, al: Alignment, jp) -> List[GateClause]:
    """One GateClause per Jev-pass clause, in order. Pure code over the gate answers already in `jp`."""
    from .provenance import _proposed_runs, is_recommendation     # provenance imports jev_pass, which imports us
    words = dictated_words(inp.artifacts.dictated_findings)
    out: List[GateClause] = []
    for i, (t, at) in enumerate(zip(jp.clauses, _locate(body, jp.clauses))):
        q = jp.clause_type(i)
        p = p_all_stated(jp.gate.get(f"g{i}"))
        s, e = at if at else (None, None)
        ac = next((c for c in al.clauses if s is not None and c.start <= s < c.end), None) if at else None
        section = ac.section if ac else None
        runs = _proposed_runs(body, s, e, words) if at else []
        rec = is_recommendation(t, q, section)
        out.append(GateClause(i=i, text=t, start=s, end=e, section=section, p=p, q_type=q,
                              tier=tier_of(p, q, rec, _negated_only(body, s, runs) if at else False),
                              runs=runs, aclause=ac))
    return out
