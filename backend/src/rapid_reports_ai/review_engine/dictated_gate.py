"""Dictated gate (spec docs/superpowers/specs/2026-10-10-dictated-gate-review-tiers-design.md).

One owner for "is this report clause dictated?": one Jev choice per alignment unit (the distinct outermost real report spans:
FINDINGS + IMPRESSION on quick reports), asked against the RAW dictation (scan type, history as context only, dictated findings). A clause is
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

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .alignment import Alignment, ReportClause
from .claims import content_words
from .items import ReviewInput

logger = logging.getLogger(__name__)

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


REWORDED_MIN = 0.7      # log-only: P(restates_with_change) a later tier rule would use (lab reworded_neg, thin margin)


def q_reworded(clause: str) -> dict:
    """Lab gate_a/reworded_neg wording, verbatim. Log-only (spec 2026-10-10 follow-up): does a normal / negative
    statement restate a dictated one with a changed qualifier, scope or side? 4/218 such clauses in the lab."""
    return {"type": "choice", "instructions": (
        f'The report says: "{clause}". This is a normal or negative statement. How does it relate to what the '
        "dictated findings say?"),
        "criteria": {
            "restates_with_change": "It restates something the dictation says about the same structure or finding, "
                                    "but changes or adds a qualifier, scope or side.",
            "adds_separate_items": "It states normal or negative findings about structures or items the dictation "
                                   "does not mention, possibly listed alongside a dictated one.",
            "same_meaning": "It restates the dictation without changing its meaning."}}


def questions(texts: List[str], dictation: str = "") -> List[Dict[str, dict]]:
    """One dict per request, CHUNK clauses each, i indexing `texts` (the alignment's report clauses): g{i} the gate
    question and t{i} the production statement-type question (asked in the gate's state; the sorter lab saw 0 type
    flips against a dictation-findings state). r{i} (log-only, `q_reworded`) only for a clause sharing a content
    word with the dictation: a cost filter, never a decision."""
    from .jev_pass import q_type              # jev_pass imports this module
    words = dictated_words(dictation) if dictation else set()
    out = []
    for k in range(0, len(texts), CHUNK):
        qs: Dict[str, dict] = {}
        for i in range(k, min(k + CHUNK, len(texts))):
            qs[f"g{i}"] = q_gate(texts[i])
            qs[f"t{i}"] = q_type(texts[i])
            if words & content_words(texts[i]):
                qs[f"r{i}"] = q_reworded(texts[i])
        out.append(qs)
    return out


def _p_choice(ans: Any, key: str) -> Optional[float]:
    """P(key) of a Jev choice answer; None when absent or unreadable."""
    probs = ans.get("probabilities") if isinstance(ans, dict) else None
    try:
        return float(probs[key]) if isinstance(probs, dict) and key in probs else None
    except (TypeError, ValueError):
        return None


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
    quiet_span: Optional[Tuple[int, int]] = None   # quiet by the bolted-on-negative rule: the negation only
    reworded: Optional[float] = None   # log-only P(restates_with_change); never changes the tier


def dictated_words(dictation: str) -> set:
    words = set(content_words(dictation))
    for w in re.findall(r"[A-Za-z]+", dictation or ""):
        if w.lower() in ABBREV:
            words |= content_words(ABBREV[w.lower()])
    return words


_CONTRAST = re.compile(r"[;:]|\b(?:but|however|although|whereas|while)\b", re.I)


def _negator_start(body: str, s: int, e: int, runs: List[Tuple[int, int]]) -> Optional[int]:
    """Start of the negator governing the first added run, when EVERY added run is a negative bolted onto a dictated
    finding; else None. A run's negator is the last one before it in the clause, and it governs the run only when no
    ';' ':' or contrast word ("but", "however", ...) sits between the negator and the END OF ITS SENTENCE (a clause split out of a comma list ends before the "but"; a synonym-folded added word such as
    "new nodule" is no run, so the contrast has to be read past the run)."""
    first = None
    for a, _ in runs:
        ns = [m for m in _NEGATOR.finditer(body, s, a)]
        if not ns or _CONTRAST.search(body, ns[-1].end(), e):
            return None
        first = ns[-1].start() if first is None else first
    return first


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


def units(al: Alignment) -> List[Tuple[int, int, ReportClause]]:
    """The gate's units: the distinct (start, end) spans of the alignment's clauses, sorted by start, each with the
    first clause holding that span (section, sentence offsets, recommendation placement). The unit text is the REAL
    report text report[start:end]: split-out list items and "No but ..." tails are synthetic clause texts that share
    their sentence's span, so they collapse into one unit. Only the OUTERMOST of nested spans is kept (the lab validated whole sentences; a nested head could be called
    dictated while its sentence is added); a drop is logged."""
    seen: Dict[Tuple[int, int], ReportClause] = {}
    for c in sorted(al.clauses, key=lambda c: (c.start, c.end)):
        seen.setdefault((c.start, c.end), c)
    spans = sorted(seen.items())
    out = []
    for (s, e), c in spans:
        if any(s2 <= s and e <= e2 and (s2, e2) != (s, e) for (s2, e2), _ in spans):
            logger.info("dictated gate: nested unit span (%d, %d) dropped for its outer span", s, e)
        else:
            out.append((s, e, c))
    return out


def classify(inp: ReviewInput, body: str, al: Alignment, jp) -> List[GateClause]:
    """One GateClause per unit (sorted by start), in the order the gate was asked. Pure code over
    the answers already in `jp`; ValueError when `jp` was asked about other clauses (the engine falls back)."""
    from .jev_pass import clause_type_of
    from .provenance import _proposed_runs, is_recommendation     # provenance imports jev_pass, which imports us
    clauses = units(al)
    if [body[s:e] for s, e, _ in clauses] != list(jp.gate_texts):
        raise ValueError("gate was asked about different clauses than the alignment holds")
    words = dictated_words(inp.artifacts.dictated_findings)
    out: List[GateClause] = []
    for i, (us, ue, c) in enumerate(clauses):
        q = clause_type_of(jp.gate.get(f"t{i}"))
        p = p_all_stated(jp.gate.get(f"g{i}"))
        text = body[us:ue]
        runs = _proposed_runs(body, us, ue, words)
        rec = is_recommendation(text, q, c.section)
        ns = _negator_start(body, us, max(ue, c.sentence_end), runs)
        tier = tier_of(p, q, rec, ns is not None)
        # quiet because of a bolted-on negative (not a normal statement): the finding is dictated, so only the
        # negation ("without cavitation") is quiet, never the whole clause
        span = (ns, runs[-1][1]) if tier == "quiet" and q != "normal" and ns is not None else None
        out.append(GateClause(i=i, text=text, start=us, end=ue, section=c.section, p=p, q_type=q,
                              tier=tier, runs=runs, aclause=c, quiet_span=span,
                              reworded=_p_choice(jp.gate.get(f"r{i}"), "restates_with_change")))
    return out


AI_LAYER = ("assumed_normal", "ai_generated")


def _ai_layer(it) -> bool:
    return it.kind in AI_LAYER and it.cls == "info" and it.anchor is not None


def _overlaps(it, s: int, e: int) -> bool:
    return it.anchor is not None and it.anchor.start < e and s < it.anchor.end


def _clause_log(g: GateClause) -> dict:
    return {"i": g.i, "section": g.section, "start": g.start, "end": g.end, "p": g.p, "q_type": g.q_type,
            "tier": g.tier, "runs": [list(r) for r in g.runs], "reworded": g.reworded}


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
            qs, qe = g.quiet_span or (g.start, g.end)
            if not any(_overlaps(it, g.start, g.end) for it in existing):
                prov.append(_new_item(inp, run_id, "accuracy", "assumed_normal", "info", DETECTOR, g.section or "",
                                      qs, qe, "Assumed normal", "",
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
