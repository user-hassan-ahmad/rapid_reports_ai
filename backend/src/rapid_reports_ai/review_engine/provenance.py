"""Provenance items (approved by Hassan 2026-10-06): which report text did the radiologist not dictate?

- `ai_generated` (lane accuracy, cls info, detector `provenance`): a report clause in FINDINGS, IMPRESSION or another
  body section that asserts SUBSTANTIVE content no dictated line states: a new finding, inference, diagnosis or
  interpretation. A clause is dictated when it has a confident alignment pair (`lanes.confident`) to a dictated line,
  or when the shared Jev pass's W1n answer (`sup{i}`, "the dictated findings report this finding ... in any wording")
  says so. Connective words, reordering, rephrasing and style changes of a dictated line therefore give no item: a
  reworded restatement is dictated. Partial restatements count as dictated (a confidently paired clause gives no item).
  Clause level only, never sub-clause word spans; adjacent marked clauses of one sentence merge into one span.
  `evidence.form` is "synthesis" (the rail's AI layer: negatives / normals carry "negative" / "normal").
- `recommendation` (lane additions, cls minor, detector `code.recommendation`): a recommendation sentence
  (`jev_pass.recommendation`, minus interpretive "suggests" / "suggestive"; in IMPRESSION also any clause Jev
  types `not_a_finding`, lexicon or not) that no dictated line states, with a
  code-built whole-sentence removal (`Edit(mode="remove")`) checked with `verifier.apply_edit`; never pre-applied.
  A sentence that also holds other parts ("No X identified; referral recommended.") is anchored and removed on its
  recommendation part only (`_rec_target`), or gets no edit when that part cannot be isolated safely; its other
  parts are judged for `ai_generated` like any clause (paired / W1n-supported / normal / owned give no item).

- Synthesis inside a dictation-paired clause (`synthesis_items`, live audit 2): for an accuracy `unsupported` item
  (Jev W1n) the adjudicator suppressed, code proposes the runs of words absent from the whole dictation and one
  Jev choice per run (lab P4 Q3) decides; only runs Jev calls not_stated get an `ai_generated` item. The
  suppressed item stays suppressed. This is the one provenance step with a model call (one batched Jev request).

Never marked: technique / comparison / history sections and signature lines (the alignment's clause splitter skips
them); Jev `not_a_finding` statements; normal / negative statements (the negatives classifier's and the brief's: their
`assumed_normal` / `check` items stay the record, and a mixed clause is judged on its split finding head); any clause
an owned (negatives / brief normals) item already anchors on.

`build_items` is pure code over the alignment and the existing Jev answers: no model call. These kinds are never adjudicated, probed or
reprepared (`PROVENANCE_KINDS`); the frontend decides how to show them."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .. import report_reconcile as rc
from .alignment import Alignment, ReportClause, _role
from .checks import hedge_tag
from .claims import content_words
from .items import Edit, ReviewInput, ReviewItem, Span, item_key, text_hash
from .jev_pass import JevPass, noul, recommendation, recommendation_parts, split_tails
from .lanes import confident
from .negatives import is_normal_or_negative
from .verifier import apply_edit

KIND_AI = "ai_generated"
KIND_REC = "recommendation"
PROVENANCE_KINDS = frozenset({KIND_AI, KIND_REC})
DETECTOR_AI = "provenance"
DETECTOR_REC = "code.recommendation"
MAX_AI_ITEMS = 20            # provisional: a report with more undictated clauses than this is a generation problem
SUPPORTED_DICTATED = 0.5     # Jev W1n ≥ this: the dictation states the clause in some wording (accuracy SUPPORTED_FLAG)

# "Features suggest X" / "suggestive of X" interpret, they do not recommend ("MRI is suggested" still does).
_INTERPRETIVE = re.compile(r"\bsuggest(?:s|ive|ing)?\b(?!\s+(?:that\s+)?(?:further|follow|clinical|correlation|"
                           r"repeat|an?\s+(?:mri|ct|ultrasound|biopsy|review)))", re.I)
_REC_WORDS = re.compile(r"recommend\w*|advis\w*|suggest\w*|referr\w*|refer|follow|up|correlat\w*", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(t: str) -> str:
    return re.sub(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+", "", " ".join((t or "").split())).strip().rstrip(".;,").lower()


def _jev_index(jp: Optional[JevPass], text: str) -> Optional[int]:
    """The shared Jev pass's index for an alignment clause: the same text, else containment (the two splitters
    differ on list markers and negative lists)."""
    if jp is None:
        return None
    t = _norm(text)
    if not t:
        return None
    ns = [_norm(c) for c in jp.clauses]
    hit = next((i for i, n in enumerate(ns) if n == t), None)
    if hit is None:
        hit = next((i for i, n in enumerate(ns) if n and (n in t or t in n) and min(len(n), len(t)) >= 0.6 * max(len(n), len(t))), None)
    return hit


def _jev_type(jp: Optional[JevPass], i: Optional[int]) -> Optional[str]:
    return jp.clause_type(i) if jp is not None and i is not None else None


def is_recommendation(text: str, jev_type: Optional[str] = None, section: Optional[str] = None) -> bool:
    """A recommendation sentence: the shared lexicon, without interpretive "suggests"; a Jev type that says the
    statement is about the patient (abnormal / normal / mixed) overrides the lexicon. In an IMPRESSION section Jev's
    `not_a_finding` alone decides ("Short-interval repeat CT in 24 hours." has no lexicon word): live audit 2 found
    every not_a_finding impression clause to be a recommendation / follow-up. FINDINGS keep the lexicon."""
    if jev_type == "not_a_finding" and section is not None and _role(section) == "impression":
        return True
    if not recommendation(_INTERPRETIVE.sub(" ", text)):
        return False
    return jev_type in (None, "not_a_finding")


def _paired(al: Alignment, c: ReportClause) -> bool:
    return any(p.clause_id == c.id and confident(p) for p in al.pairs)


def _rec_dictated(al: Alignment, c: ReportClause) -> bool:
    """A confident pair, or a dictated recommendation line sharing a content word beyond the recommending words. A
    rewording without either ("Discussed with the referring team." for "Result discussed by phone with Dr Jones") is
    left to the Jev question in `confirm`, never to word overlap with any dictated line."""
    if _paired(al, c):
        return True
    words = {w for w in content_words(c.text) if not _REC_WORDS.fullmatch(w)}
    return any(recommendation(l.text) and words & {w for w in content_words(l.text) if not _REC_WORDS.fullmatch(w)}
               for l in al.lines)


def _supported(jp: Optional[JevPass], i: Optional[int]) -> Optional[float]:
    return noul(jp.support, f"sup{i}") if jp is not None and i is not None else None


def _overlaps(a: Tuple[int, int], spans: List[Tuple[int, int]]) -> bool:
    return any(a[0] < e and s < a[1] for s, e in spans)


def _head_span(report: str, c: ReportClause) -> Optional[Tuple[int, int, str]]:
    """(start, end, head) of a mixed clause's finding head, located in the clause; None when it is not one."""
    sp = split_tails(c.text)
    if not sp:
        return None
    head = sp[0]
    k = report.find(head, c.start, c.end)
    return (k, k + len(head), head) if k >= 0 else None


def _rec_target(report: str, c: ReportClause, sentence: str, names: List[str]
                ) -> Tuple[int, int, Optional[Edit]]:
    """(start, end, remove edit or None) of a recommendation item. A whole recommendation sentence is removed whole.
    A sentence that also holds other parts at ';' (`jev_pass.recommendation_parts`) is anchored on its recommendation
    part(s) only; the removal is offered only when they end the sentence and what stays is the other part(s) closed
    by a '.' ("No X identified; referral recommended." → "No X identified."). Else no edit (never guessed)."""
    parts = recommendation_parts(sentence, is_recommendation)
    if parts is None:
        edit = Edit(mode="remove", find=sentence, section=c.section)
        ok = report.count(sentence) == 1 and apply_edit(report, edit, names) is not None
        return c.sentence_start, c.sentence_end, edit if ok else None
    k = next(i for i, p in enumerate(parts) if p[2])
    j = k
    while j + 1 < len(parts) and parts[j + 1][2]:
        j += 1                                              # the contiguous run of recommendation parts
    start, end = c.sentence_start + parts[k][0], c.sentence_start + parts[j][1]
    find = report[start:end]
    if j != len(parts) - 1 or k == 0 or report.count(find) != 1:
        return start, end, None
    edit = Edit(mode="remove", find=find, section=c.section)
    out = apply_edit(report, edit, names)
    keep = sentence[:parts[k][0]].rstrip().rstrip(";").rstrip() + "."
    if out is None or out[c.sentence_start:c.sentence_start + len(keep)] != keep:
        return start, end, None
    return start, end, edit


def _new_item(inp: ReviewInput, run_id: str, lane: str, kind: str, cls: str, detector: str, section: str, s: int,
              e: int, label: str, reason: str, evidence: dict, edit: Optional[Edit] = None,
              verified: Optional[dict] = None) -> ReviewItem:
    report = inp.artifacts.report or ""
    h = text_hash(report)
    text = report[s:e]
    return ReviewItem(key=item_key(lane, kind, text), report_id=inp.report_id, run_id=run_id, lane=lane,
                      detectors=[detector], kind=kind, cls=cls, section=section,
                      anchor=Span(start=s, end=e, text=text, text_hash=h), label=label, reason=reason,
                      edit=edit, verified=verified, evidence=evidence, status="open",
                      history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h,
                                "detail": {"detectors": [detector]}}])


def _ai_item(inp: ReviewInput, run_id: str, section: str, s: int, e: int, evidence: dict) -> ReviewItem:
    return _new_item(inp, run_id, "accuracy", KIND_AI, "info", DETECTOR_AI, section, s, e, "AI-generated",
                     "Not in your dictation.", evidence)


def build_items(inp: ReviewInput, run_id: str, al: Alignment, jp: Optional[JevPass],
                owned: List[ReviewItem]) -> Tuple[List[ReviewItem], dict]:
    """(items, log). `owned` = the negatives classifier's and the brief normals' items (their anchors are theirs)."""
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    owned_spans = [(it.anchor.start, it.anchor.end) for it in owned if it.anchor is not None]
    marked: List[Tuple[ReportClause, int, int, dict]] = []      # (clause, start, end, evidence)
    recs: List[Tuple[ReportClause, str]] = []
    rec_seen = set()
    skipped = {"paired": 0, "supported": 0, "normal": 0, "not_a_finding": 0, "owned": 0, "rec_dictated": 0}
    for c in sorted(al.clauses, key=lambda x: x.start):
        i = _jev_index(jp, c.text)
        t = _jev_type(jp, i)
        if is_recommendation(c.text, t, c.section):
            if c.sentence_start in rec_seen:
                continue
            rec_seen.add(c.sentence_start)
            sentence = report[c.sentence_start:c.sentence_end]
            if _rec_dictated(al, c):
                skipped["rec_dictated"] += 1
            else:
                recs.append((c, sentence))
            # its other parts ("Findings suspicious for X; MDT recommended.") are judged like any clause
            for ps, pe, rec in recommendation_parts(sentence, is_recommendation) or []:
                a, b = c.sentence_start + ps, c.sentence_start + pe
                if rec or not (c.start <= a and b <= c.end):
                    continue
                part = report[a:b]
                pi = _jev_index(jp, part)
                pt = _jev_type(jp, pi)
                if pt in ("normal", "not_a_finding") or hedge_tag(part) == "negated" or (
                        pt is None and is_normal_or_negative(part)):
                    skipped["normal"] += 1
                    continue
                if _paired(al, c):
                    skipped["paired"] += 1
                    continue
                sup = _supported(jp, pi)
                if sup is not None and sup >= SUPPORTED_DICTATED:
                    skipped["supported"] += 1
                    continue
                if _overlaps((a, b), owned_spans):
                    skipped["owned"] += 1
                    continue
                marked.append((c, a, b, {"clauses": [c.id], "jev_type": pt, "supported": sup, "form": "synthesis"}))
            continue
        if t == "not_a_finding":
            skipped["not_a_finding"] += 1
            continue
        start, end = c.start, c.end
        if t == "normal" or hedge_tag(c.text) == "negated":
            skipped["normal"] += 1
            continue
        hs = _head_span(report, c) if t in (None, "mixed") else None
        if hs:
            start, end = hs[0], hs[1]
        elif t is None and is_normal_or_negative(c.text):
            skipped["normal"] += 1
            continue
        if _paired(al, c):
            skipped["paired"] += 1
            continue
        sup = _supported(jp, i)
        if sup is not None and sup >= SUPPORTED_DICTATED:
            skipped["supported"] += 1
            continue
        if _overlaps((start, end), owned_spans):
            skipped["owned"] += 1
            continue
        marked.append((c, start, end, {"clauses": [c.id], "jev_type": t, "supported": sup, "form": "synthesis"}))

    merged: List[Tuple[ReportClause, int, int, dict]] = []      # adjacent marked clauses of one sentence → one span
    for c, s, e, ev in marked:
        if merged and merged[-1][0].sentence_start == c.sentence_start:
            pc, ps, pe, pev = merged[-1]
            merged[-1] = (pc, min(ps, s), max(pe, e), {**pev, "clauses": pev["clauses"] + ev["clauses"]})
        else:
            merged.append((c, s, e, ev))
    capped = max(0, len(merged) - MAX_AI_ITEMS)
    merged = merged[:MAX_AI_ITEMS]

    def item(lane: str, kind: str, cls: str, detector: str, c: ReportClause, s: int, e: int, label: str,
             reason: str, evidence: dict, edit: Optional[Edit] = None, verified: Optional[dict] = None) -> ReviewItem:
        return _new_item(inp, run_id, lane, kind, cls, detector, c.section, s, e, label, reason, evidence, edit,
                         verified)

    items = [_ai_item(inp, run_id, c.section, s, e, ev) for c, s, e, ev in merged]
    unplaced = 0
    for c, sentence in recs:
        s, e, edit = _rec_target(report, c, sentence, names)
        ok = edit is not None
        if not ok:
            unplaced += 1
        items.append(item("additions", KIND_REC, "minor", DETECTOR_REC, c, s, e,
                          "Recommendation not dictated", "Added by the report writer; remove it if not wanted.",
                          {"sentence": sentence}, edit,
                          {"code": ok, "failed": [] if ok else ["not_placeable"], "addressed": None, "contra": None,
                           "unconfirmed": True}))
    log = {"ai_generated": len(merged), "recommendation": len(recs), "capped": capped, "unplaced": unplaced,
           "skipped": skipped}
    return items, log


_TOKEN = re.compile(r"[A-Za-z]+|\d+(?:\.\d+)?")
# never painted, and never bridged when merging two runs: a dictated negation or hedge belongs to the dictation
_GUARD = re.compile(r"^(?:no|not|without|nil|none|absent|negative|free|excluded|exclude|cannot|likely|possible|possibly|"
                    r"probable|probably|consistent|compatible|keeping|suggest\w*|suspicious|suspected|query|may|might|"
                    r"could|favour\w*|favor\w*)$", re.I)
# Lab P4 (scratchpad labs/audit_jev/lab4.py, arm Q3, 2 runs): 0 dictated items flagged at any threshold <= 0.71
# (the noul wording Q1 scored a dictated "No ICH" phrase 0.15), 16/17 added phrases caught in both runs.
SYNTH_DICTATED = 0.5         # P(stated) + P(synonym_or_equivalent) below this → not dictated → marked
SYNTH_CHOICES = ("stated", "synonym_or_equivalent", "not_stated")


def q_synthesis(clause: str, item: str) -> dict:
    """Lab P4 arm Q3, verbatim."""
    return {"type": "choice", "instructions": (
        f'The report says: "{clause}". Consider only this one phrase from it: "{item}". '
        "Is it in the dictated findings?"),
        "criteria": {"stated": "The dictation states it in the same words.",
                     "synonym_or_equivalent": "The dictation states it in other words: a synonym, an abbreviation or "
                                              "its expansion, or an equivalent term for the same thing.",
                     "not_stated": "The dictation does not state it; it was added by the report writer."}}


def p_dictated(ans) -> Optional[float]:
    """P(stated) + P(synonym_or_equivalent) of a Q3 choice answer; a bare choice counts 1 / 0; None when unreadable."""
    if not isinstance(ans, dict):
        return None
    probs = ans.get("probabilities")
    if isinstance(probs, dict) and any(k in probs for k in SYNTH_CHOICES):
        try:
            return float(probs.get("stated", 0) or 0) + float(probs.get("synonym_or_equivalent", 0) or 0)
        except (TypeError, ValueError):
            return None
    ch = ans.get("choice")
    return None if ch not in SYNTH_CHOICES else (0.0 if ch == "not_stated" else 1.0)


def synthesis_state(inp: ReviewInput) -> str:
    h = f"CLINICAL HISTORY: {inp.clinical_history}\n" if inp.clinical_history else ""
    return f"SCAN TYPE: {inp.scan_type}\n{h}DICTATED FINDINGS:\n{inp.artifacts.dictated_findings}"


def _proposed_runs(report: str, s: int, e: int, dictated: set) -> List[Tuple[int, int]]:
    """Report spans (inside [s, e)) of contiguous content words absent from the WHOLE dictation (folded). Two runs
    merge only across a gap of stopwords holding no negation / hedge word (`_GUARD`): a dictated word is never
    inside a span."""
    toks = [(m.start() + s, m.end() + s, m.group()) for m in _TOKEN.finditer(report[s:e])]
    absent = [bool(content_words(t[2])) and not (content_words(t[2]) & dictated) for t in toks]
    runs: List[List[int]] = []
    for k, a in enumerate(absent):
        if not a:
            continue
        if runs:
            gap = toks[runs[-1][1] + 1:k]
            if all(not content_words(t[2]) and not _GUARD.match(t[2]) for t in gap):
                runs[-1][1] = k
                continue
        runs.append([k, k])
    return [(toks[i][0], toks[j][1]) for i, j in runs]


async def confirm(inp: ReviewInput, run_id: str, al: Alignment, jp: Optional[JevPass], lane_items: List[ReviewItem],
                  prov: List[ReviewItem], owned: List[ReviewItem]) -> Tuple[List[ReviewItem], dict]:
    """(provenance items, log): `build_items`' items after one batched Jev request (dictation as state, the lab P4 Q3
    choice, `q_synthesis`) that decides two things:
    - recommendations: a `recommendation` item whose sentence no dictated line pairs with or restates as a
      recommendation (`_rec_dictated`) is asked about its anchored recommendation text; dictated (P(stated) +
      P(synonym_or_equivalent) >= SYNTH_DICTATED) drops the item. A failed or unreadable answer keeps it: a removable
      item is the safe direction.
    - synthesis: violet marks for synthesis inside a dictation-paired clause whose accuracy `unsupported` item
      (Jev W1n, `jev.supported`) the adjudicator suppressed. A suppression is NOT proof the content is undictated
      (the adjudicator also suppresses "present in other words"), so code only proposes: each anchor (and
      `also_anchors` copy) that lies on report clauses (never technique / comparison / history), has a confident
      pair, and is not Jev-typed normal / not_a_finding; its runs of content words absent from the whole dictation
      (`_proposed_runs`), minus spans provenance already marked or owned items anchor. A run is marked only when
      P(stated) + P(synonym_or_equivalent) < SYNTH_DICTATED; a failed request or unreadable answer marks nothing.
      The suppressed item stays as it is."""
    report = inp.artifacts.report or ""
    taken = [(it.anchor.start, it.anchor.end) for it in list(prov) + list(owned) if it.anchor is not None]
    dictated = set().union(*(content_words(l.text) for l in al.lines)) if al.lines else set()
    props: List[Tuple[int, int, str, str, str]] = []           # (start, end, clause text, section, item key)
    recs = [it for it in prov if it.kind == KIND_REC and it.anchor is not None]
    log = {"suppressed_unsupported": 0, "proposed": 0, "synthesis": 0, "rec_asked": len(recs), "rec_dictated_jev": 0,
           "error": None}
    for it in lane_items:
        if (it.kind != "unsupported" or it.cls != "suppress" or "jev.supported" not in (it.detectors or [])
                or it.anchor is None):
            continue
        log["suppressed_unsupported"] += 1
        anchors = [(it.anchor.start, it.anchor.end, it.anchor.text)] + [
            (a.get("start"), a.get("end"), a.get("text")) for a in (it.evidence or {}).get("also_anchors") or []
            if isinstance(a, dict)]                          # a linked FINDINGS / IMPRESSION group: every copy
        for s, e, text in anchors:
            if not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e <= len(report)) or report[s:e] != text:
                continue
            clauses = [c for c in al.clauses if c.start < e and s < c.end]
            if not clauses or not any(_paired(al, c) for c in clauses):
                continue
            if any(_jev_type(jp, _jev_index(jp, c.text)) in ("normal", "not_a_finding") for c in clauses):
                continue
            for a, b in _proposed_runs(report, s, e, dictated):
                if _overlaps((a, b), taken):
                    continue
                taken.append((a, b))
                props.append((a, b, text, clauses[0].section, it.key))
    log["proposed"] = len(props)
    if not props and not recs:
        return list(prov), log
    qs = {f"syn{k}": q_synthesis(clause, report[a:b]) for k, (a, b, clause, _, _) in enumerate(props)}
    qs.update({f"rec{k}": q_synthesis((it.evidence or {}).get("sentence") or it.anchor.text, it.anchor.text)
               for k, it in enumerate(recs)})
    try:
        ans = await rc._jev(synthesis_state(inp), qs) or {}
    except Exception as e:  # noqa: BLE001 - no answer: recommendations stay, nothing is marked
        log["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return list(prov), log
    drop = set()
    for k, it in enumerate(recs):
        p = p_dictated(ans.get(f"rec{k}"))
        if p is not None and p >= SYNTH_DICTATED:
            drop.add(id(it))
    log["rec_dictated_jev"] = len(drop)
    out = [it for it in prov if id(it) not in drop]
    for k, (a, b, _, section, key) in enumerate(props):
        p = p_dictated(ans.get(f"syn{k}"))
        if p is None or p >= SYNTH_DICTATED:
            continue
        out.append(_ai_item(inp, run_id, section, a, b, {"form": "synthesis", "from": "unsupported_suppressed",
                                                         "item_key": key, "dictated": p}))
        log["synthesis"] += 1
    return out, log


async def synthesis_items(inp: ReviewInput, run_id: str, al: Alignment, jp: Optional[JevPass],
                          lane_items: List[ReviewItem], existing: List[ReviewItem], owned: List[ReviewItem]
                          ) -> Tuple[List[ReviewItem], dict]:
    """The synthesis marks `confirm` adds (see there), alone."""
    out, log = await confirm(inp, run_id, al, jp, lane_items, existing, owned)
    return [it for it in out if (it.evidence or {}).get("from") == "unsupported_suppressed"], log


__all__ = ["KIND_AI", "KIND_REC", "PROVENANCE_KINDS", "DETECTOR_AI", "DETECTOR_REC", "is_recommendation",
           "build_items", "confirm", "synthesis_items"]
