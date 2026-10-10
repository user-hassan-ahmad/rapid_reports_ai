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
    return f"SCAN TYPE: {inp.scan_type}\n{h}DICTATED FINDINGS:\n{inp.artifacts.dictated_findings or ''}"


def questions(texts: List[str]) -> List[Dict[str, dict]]:
    """One dict per request, CHUNK clauses each, i indexing `texts` (the alignment's report clauses): g{i} the gate
    question and t{i} the production statement-type question (asked in the gate's state; the sorter lab saw 0 type
    flips against a dictation-findings state)."""
    from .jev_pass import q_type              # jev_pass imports this module
    out = []
    for k in range(0, len(texts), CHUNK):
        qs: Dict[str, dict] = {}
        for i in range(k, min(k + CHUNK, len(texts))):
            qs[f"g{i}"] = q_gate(texts[i])
            qs[f"t{i}"] = q_type(texts[i])
        out.append(qs)
    return out


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
    """One GateClause per alignment report clause (sorted by start), in the order the gate was asked. Pure code over
    the answers already in `jp`; ValueError when `jp` was asked about other clauses (the engine falls back)."""
    from .jev_pass import clause_type_of
    from .provenance import _proposed_runs, is_recommendation     # provenance imports jev_pass, which imports us
    clauses = sorted(al.clauses, key=lambda c: c.start)
    if [c.text for c in clauses] != list(jp.gate_texts):
        raise ValueError("gate was asked about different clauses than the alignment holds")
    words = dictated_words(inp.artifacts.dictated_findings)
    out: List[GateClause] = []
    for i, c in enumerate(clauses):
        q = clause_type_of(jp.gate.get(f"t{i}"))
        p = p_all_stated(jp.gate.get(f"g{i}"))
        runs = _proposed_runs(body, c.start, c.end, words)
        rec = is_recommendation(c.text, q, c.section)
        out.append(GateClause(i=i, text=c.text, start=c.start, end=c.end, section=c.section, p=p, q_type=q,
                              tier=tier_of(p, q, rec, _negated_only(body, c.start, runs)),
                              runs=runs, aclause=c))
    return out


AI_LAYER = ("assumed_normal", "ai_generated")


def _ai_layer(it) -> bool:
    return it.kind in AI_LAYER and it.cls == "info" and it.anchor is not None


def _overlaps(it, s: int, e: int) -> bool:
    return it.anchor is not None and it.anchor.start < e and s < it.anchor.end


def _clause_log(g: GateClause) -> dict:
    return {"i": g.i, "section": g.section, "start": g.start, "end": g.end, "p": g.p, "q_type": g.q_type,
            "tier": g.tier, "runs": [list(r) for r in g.runs]}


def apply(inp: ReviewInput, run_id: str, al: Alignment, gate: List[GateClause], neg_items: list, brief_items: list):
    """Live (spec §4.4): (provenance items, negatives items, brief items, log). Inputs are not mutated.
    - dictated clause: AI-layer items (assumed_normal / ai_generated, cls info) that touch no added clause are dropped;
      cards (check, removed, ...) stay;
    - quiet clause with no AI-layer item on it: a quiet `assumed_normal` item (form normal);
    - synth clause: one `ai_generated` item on the added-word runs (first run the anchor, the rest `also_anchors`;
      no run → the whole clause);
    - rec clause: one `recommendation` item per sentence, placed and given its removal by provenance's code."""
    from .items import text_hash
    from .provenance import (DETECTOR_REC, KIND_REC, MAX_AI_ITEMS, _ai_item, _new_item, _rec_target)
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    placed = [g for g in gate if g.start is not None]
    added = [(g.start, g.end) for g in placed if g.tier in ("quiet", "rec", "synth")]
    dictated = [(g.start, g.end) for g in placed if g.tier == "dictated"]

    def keep(it) -> bool:
        if not _ai_layer(it):
            return True
        on_dictated = any(_overlaps(it, s, e) for s, e in dictated)
        return not on_dictated or any(_overlaps(it, s, e) for s, e in added)

    neg = [it for it in neg_items if keep(it)]
    brief = [it for it in brief_items if keep(it)]
    dropped = [it.key for it in list(neg_items) + list(brief_items) if not keep(it)]
    existing = [it for it in neg + brief if _ai_layer(it)]
    prov: list = []
    synth, rec_seen, unplaced, capped = 0, set(), sum(1 for g in gate if g.start is None), 0
    for g in placed:
        if g.tier == "quiet":
            if not any(_overlaps(it, g.start, g.end) for it in existing):
                prov.append(_new_item(inp, run_id, "accuracy", "assumed_normal", "info", DETECTOR, g.section or "",
                                      g.start, g.end, "Assumed normal", "",
                                      {"form": "normal", "source": DETECTOR, "p": g.p, "q_type": g.q_type}))
        elif g.tier == "synth":
            if synth >= MAX_AI_ITEMS:
                capped += 1
                continue
            runs = g.runs or [(g.start, g.end)]
            also = [{"start": a, "end": b, "text": report[a:b], "text_hash": h} for a, b in runs[1:]]
            prov.append(_ai_item(inp, run_id, g.section or "", runs[0][0], runs[0][1],
                                 {"form": "synthesis", "source": DETECTOR, "p": g.p, "q_type": g.q_type,
                                  **({"also_anchors": also} if also else {})}))
            synth += 1
        elif g.tier == "rec":
            c = g.aclause
            if c is None or c.sentence_start in rec_seen:
                unplaced += c is None
                continue
            rec_seen.add(c.sentence_start)
            sentence = report[c.sentence_start:c.sentence_end]
            s, e, edit = _rec_target(report, c, sentence, names)
            ok = edit is not None
            prov.append(_new_item(inp, run_id, "additions", KIND_REC, "minor", DETECTOR_REC, c.section, s, e,
                                  "Recommendation not dictated", "Added by the report writer; remove it if not wanted.",
                                  {"sentence": sentence, "source": DETECTOR, "p": g.p}, edit,
                                  {"code": ok, "failed": [] if ok else ["not_placeable"], "addressed": None,
                                   "contra": None, "unconfirmed": True}))
    log = {"mode": "live", "clauses": [_clause_log(g) for g in gate], "dropped": dropped,
           "quiet": sum(1 for it in prov if it.kind == "assumed_normal"), "synthesis": synth,
           "recommendation": len(rec_seen), "capped": capped, "unplaced": unplaced}
    return prov, neg, brief, log


def shadow_log(gate: List[GateClause], items: list) -> dict:
    """Shadow (spec §7): the gate's verdict and tier per clause next to what today's items tint on it."""
    clauses, counts, plain, tinted = [], {}, 0, 0
    for g in gate:
        d = _clause_log(g)
        old = sorted({f"{it.kind}:{(it.evidence or {}).get('form', '')}" for it in items
                      if g.start is not None and _ai_layer(it) and _overlaps(it, g.start, g.end)}
                     | {it.kind for it in items if g.start is not None and it.kind == "recommendation"
                        and _overlaps(it, g.start, g.end)})
        d["old"] = old
        clauses.append(d)
        counts[g.tier] = counts.get(g.tier, 0) + 1
        plain += g.tier in ("quiet", "rec", "synth") and not old
        tinted += g.tier == "dictated" and bool(old)
    return {"mode": "shadow", "clauses": clauses, "counts": counts, "added_plain_today": plain,
            "dictated_tinted_today": tinted}
