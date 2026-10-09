"""Brief labels → the words the generator wrote (spec docs/superpowers/specs/2026-10-09-negatives-one-owner-design.md
§3.1). One owner per judgement: the brief selected and labelled every negative and linked normal before the report was
written; this finds where each one landed so the post-gen check and the review engine defer to that label instead of
re-judging it.

    brief_labels(decisions)          every brief label (mandatory / finding-linked negatives, linked-normal atoms,
                                     dictated negatives) with a stable ref and a key term
    units(report)                    the normal / negative statements of FINDINGS + IMPRESSION, with positions, the
                                     sentence each sits in and the sentence before it (context for Jev)
    match_terms(report, labels, us)  code PROPOSES: a label's key term in exactly one free unit (longest term first,
                                     "proposed"), or shadowed when every hit is held by a higher-ranked label
    candidates(...)                  every label's candidate units: its term-hit units, else units sharing a word
    link(labels, us, cands)          Jev CONFIRMS: "does the last sentence say X?" with the previous sentence as
                                     context, one request per sentence; a label anchors on the one sentence >= LINK_MIN
    anchored(a)                      how in ANCHORED ("term+jev", "jev"): the one test of "anchored"
    anchor(report, decisions)        both steps; never raises. Nothing anchors without Jev
    relocate(anchors, report)        anchors re-found on the report after the check's own edits
    brief_rules(...)                 spec Q2 / Q3: protect brief-kept clauses; OMIT clauses on two signals are
                                     shadow-logged and carded (the brief vetoes, never removes)
    anchor_log(anchors, rules)       counts, unanchored labels, brief errors (logged, never surfaced: spec Q4)

An unanchored label is not an error: the generator dropped or merged it."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from . import linked_normals as ln
from . import report_reconcile as rc

logger = logging.getLogger(__name__)

KEEP = frozenset({"keep", "default", "implicated", "dictated"})
OMIT = frozenset({"contradicted", "expected", "do_not_assert"})

_LEAD = re.compile(r"^\s*(?:no|nil|without|there\s+(?:is|are|was|were)\s+no)\s+", re.I)
_INNER = re.compile(r"\b(?:no|without)\s+(?=\S)", re.I)
_HEDGE = re.compile(r"^(?:definite|definitive|evidence\s+of|any|significant|obvious)\s+", re.I)
_VERB_TAIL = re.compile(r"\s+(?:(?:is|are|was|were)\s+)?(?:identified|seen|present|demonstrated|noted|detected)\b.*$",
                        re.I)
_PLACE_TAIL = re.compile(r"\s+(?:by|on|in|at|within|from|involving)\s+(?:the\s+)?\S.*$", re.I)
# A trailing place phrase is boilerplate ("in the visualised thoracic skeleton") unless it carries a side or a level
# ("at T7", "in the left kidney"): then it is part of the claim and stays in the term. "by ..." names the cause
# ("invasion by the right upper lobe mass"), never part of the claim, so it always goes.
_QUALIFIER = re.compile(r"\b(?:left|right|bilateral|contralateral|ipsilateral|[CTLS]\d{1,2}(?:/\d)?|segment\s+\w+)\b",
                        re.I)


@dataclass
class Label:
    ref: str
    text: str
    term: str
    action: str
    source: str            # "sheet" | "finding:<key>" | "atom" | "dictated"
    pointer: str = ""


def enabled() -> bool:
    """Kill switch: RR_BRIEF_ANCHOR=0 skips anchoring end to end (today's behaviour)."""
    return os.environ.get("RR_BRIEF_ANCHOR", "1").strip().lower() not in ("0", "false", "off")


def key_term(text: str) -> str:
    """The denied phrase without its boilerplate: "No osseous lesion identified in the visualised thoracic skeleton"
    → "osseous lesion"; "... with no definite chest wall involvement" → "chest wall involvement". It only proposes
    candidate units: a dropped place ("in the common bile duct") is Jev's to check, in context."""
    t = (text or "").strip().rstrip(".")
    if _LEAD.match(t):
        t = _LEAD.sub("", t)
    else:
        found = list(_INNER.finditer(t))
        if not found:
            return ""
        t = t[found[-1].end():]
    t = _HEDGE.sub("", t)
    t = _VERB_TAIL.sub("", t)
    m = _PLACE_TAIL.search(t)
    if m and (m.group(0).split()[0].lower() == "by" or not _QUALIFIER.search(m.group(0))):
        t = t[:m.start()]
    return t.strip(" ,;")


def _pointer(p) -> str:
    p = str(p or "").strip()
    return "" if p in ("-", "->", "—", "none") else p


def brief_labels(decisions: Optional[dict]) -> List[Label]:
    d = decisions or {}
    out: List[Label] = []
    for i, n in enumerate(d.get("negatives") or []):
        term = key_term(n.get("text") or "")
        if not term:
            continue
        src = n.get("source") or "sheet"
        finding = src.split(":", 1)[1] if src.startswith("finding:") else ""
        out.append(Label(f"neg:{i}", n["text"], term, n.get("action") or "keep", src,
                         _pointer(n.get("dictated_finding")) or finding))
    for u in d.get("normals") or []:
        if not isinstance(u, dict) or not u.get("linked"):
            continue
        for a in u.get("atoms") or []:
            if a.get("term") and u.get("pid") and a.get("id"):     # a ref needs both, or labels collide
                out.append(Label(f"atom:{u.get('pid')}:{a.get('id')}", a.get("text") or a["term"], a["term"],
                                 a.get("action") or "keep", "atom", _pointer(a.get("pointer"))))
    for i, t in enumerate(d.get("dictated_negatives") or []):
        term = key_term(t)
        if term:
            out.append(Label(f"dict:{i}", t, term, "dictated", "dictated"))
    return out


_NORMAL = re.compile(r"\b(?:no|not|nil|without|normal(?:ly)?|unremarkable|patent|intact|clear|preserved|"
                     r"maintained|non-?dilated|undilated)\b", re.I)


@dataclass
class Unit:
    text: str
    start: int
    end: int
    sentence: str = ""     # the report sentence the unit sits in
    prev: str = ""         # the sentence before it in the same section ("" for the first)
    sstart: int = -1       # the sentence's start: units of one sentence share one Jev answer


@dataclass
class Anchor:
    ref: str
    action: str
    source: str
    pointer: str = ""
    how: str = "none"                 # "term+jev" (a term hit Jev confirmed) | "jev" (a unit Jev picked) | "none" |
    #                                   "removed" (its clause was edited out) | "proposed" (match_terms only)
    span: Optional[List[int]] = None  # the label's words (term+jev) or the whole unit (jev)
    span_text: str = ""
    unit: str = ""                    # the statement the span sits in
    offset: int = 0                   # span start minus unit start (relocation)
    p: Optional[float] = None         # Jev's probability that the sentence says the label
    shadowed_by: Optional[str] = None # its only hit is held by this (longer or dictated) label
    dupes: int = 0                    # units with this unit's text when anchored (0 = unknown); relocate() checks it


ANCHORED = frozenset({"term+jev", "jev"})   # both confirmed by Jev: code only proposes


def anchored(a) -> bool:
    """Whether an anchor (an `Anchor` or its persisted dict) sits on the report: the one test every consumer uses."""
    return (a.get("how") if isinstance(a, dict) else getattr(a, "how", None)) in ANCHORED


_HEDGED = re.compile(r"\b(?:not\s+excluded|cannot\s+be\s+excluded|not\s+ruled\s+out|no\s+(?:interval\s+)?change\s+in|"
                     r"no\s+interval\s+change|not\s+entirely\s+excluded|cannot\s+be\s+ruled\s+out)\b", re.I)


_TAIL_NEG = re.compile(r"\b(?:no|nil|without)\s+$", re.I)    # the negator split_tails replaced with "No "
_THERE = re.compile(r"^\s*(?:there\s+(?:is|are|was|were)\s*)?$", re.I)
_TURN_TO_FINDING = re.compile(r",\s*with\b|\s+with\s+an?\b|\s+and\s+an?\b|\s+but\b|,\s*while\b", re.I)


def _is_normal(s: str) -> bool:
    return bool(_NORMAL.search(s)) and not _HEDGED.search(s)


def units(report: str) -> List[Unit]:
    """Normal / negative statements of FINDINGS + IMPRESSION: a whole normal sentence, or the negative / normal tails
    of a finding sentence ("The nodes measure 14 mm; no contralateral lymphadenopathy" → the tail). Positive heads and
    positive ';' parts are never units; hedged non-negatives ("not excluded") are not normal."""
    from .report_review import _sentence_positions, report_sections
    from .review_engine.jev_pass import split_tails   # lazy: review_engine imports report_review
    out: List[Unit] = []
    base = 0
    for sec in report_sections(report):
        a = report.find(sec, base) if sec else -1
        if a < 0:
            continue
        base = a + len(sec)
        prev = ""
        for s, i, j in _sentence_positions(report, a, a + len(sec)):
            ctx = {"sentence": s, "prev": prev, "sstart": i}
            prev = s
            sp = split_tails(s)
            if sp:
                k0 = s.find(sp[0])
                cursor = k0 + len(sp[0]) if k0 >= 0 else 0
                for tail in sp[1]:
                    words = _LEAD.sub("", tail).rstrip(".")
                    k = s.find(words, cursor) if words else -1
                    if k >= 0 and not _HEDGED.search(words):
                        # the unit keeps its negator ("no SMA involvement", not "SMA involvement"): pass 2 shows Jev
                        # the unit alone, and a tail without its "no" reads as a positive finding
                        neg = _TAIL_NEG.search(s, cursor, k)
                        k0 = neg.start() if neg else k
                        cursor = k + len(words)
                        # a tail can run on into a finding ("no chest wall invasion, with ... pleural effusion"):
                        # keep only the part before the turn, and only while it is still a negative / normal
                        k1 = k + len(words)
                        turn = _TURN_TO_FINDING.search(s, k, k1)
                        if turn:
                            k1 = turn.start()
                            if not _is_normal(s[k0:k1]):
                                continue
                        out.append(Unit(s[k0:k1], i + k0, i + k1, **ctx))
            else:
                # a whole sentence: split at ';' and at a turn to a finding, keep only the parts that are still
                # negative / normal ("... no lymphadenopathy, but a 6 mm nodule ..." never anchors on the nodule)
                cuts = [0]
                for m in re.finditer(r";|" + _TURN_TO_FINDING.pattern, s, re.I):
                    cuts += [m.start(), m.end()]
                cuts.append(len(s))
                whole = len(cuts) == 2
                for a0, b0 in zip(cuts[0::2], cuts[1::2]):
                    part = s[a0:b0]
                    t = part if whole else part.strip(" ,;")
                    if not t or not _is_normal(t):
                        continue
                    k = a0 + (0 if whole else part.find(t))
                    # a positive head ("Nodule in the left lobe with no X") is not part of the statement
                    m = re.search(r"\b(?:no|nil|without)\b", t, re.I)
                    if m and m.start() > 0 and not _is_normal(t[:m.start()]) \
                            and not _THERE.match(t[:m.start()]):
                        k, t = k + m.start(), t[m.start():]
                    out.append(Unit(t, i + k, i + k + len(t), **ctx))
    return out


def _rank(lab: Label) -> Tuple[int, int]:
    """Longest term first; among equal terms a dictated label, then a kept one, then an OMIT one."""
    return (-len(lab.term), 0 if lab.action == "dictated" else (1 if lab.action in KEEP else 2))


def _anchor(lab: Label, **kw) -> Anchor:
    return Anchor(lab.ref, lab.action, lab.source, lab.pointer, **kw)


def match_terms(report: str, labels: List[Label], us: List[Unit]) -> Tuple[Dict[str, Anchor], List[Label]]:
    """Code proposes → ({ref: Anchor}, the other labels). A label whose term occurs in exactly one unit at a position
    no earlier-ranked label holds is "proposed" there (holding the position); one whose every hit is held is
    shadowed (merged into the holder, never asked). No hit, or several free hits: the other labels. Nothing here is
    anchored: `link` confirms every proposal with Jev."""
    taken: List[Tuple[int, int, str]] = []
    got: Dict[str, Anchor] = {}
    left: List[Label] = []
    for lab in sorted(labels, key=_rank):
        free: List[Tuple[int, int, Unit]] = []
        held: Optional[str] = None
        for u in us:
            pos = 0
            while (m := ln.term_span(u.text, lab.term, pos)) is not None:
                s, e = u.start + m[0], u.start + m[1]
                owner = next((r for a, b, r in taken if a < e and s < b), None)
                if owner is None:
                    free.append((s, e, u))
                elif held is None:
                    held = owner
                pos = m[1]
        if len(free) == 1:
            s, e, u = free[0]
            taken.append((s, e, lab.ref))
            got[lab.ref] = _anchor(lab, how="proposed", span=[s, e], span_text=report[s:e], unit=u.text,
                                   offset=s - u.start, dupes=sum(x.text == u.text for x in us))
        elif not free and held is not None:
            got[lab.ref] = _anchor(lab, how="none", shadowed_by=held)
        else:
            left.append(lab)
    return got, left


# Link acceptance, anchor_link_lab 2026-10-10 (40 synthetic + 152 stored pairs, 2 runs, every proposal now asked):
# C1 (context) at 0.80: 0 wrong links in both runs, recall 105 / 108 of 138, highest gold-false score 0.70, and every
# context case (tails, "within the duct", "within it") linked. S1 at 0.85 recalled 109 / 138 with 0 wrong links but
# its nearest wrong link scored 0.82 (t21) against Jev's run-to-run drift of up to 0.06: no margin (as in Task 4).
LINK_MIN = 0.80
LINK_TIMEOUT_S = 4.0
LINK_WORDING_S1 = 'Read only this sentence. It says, in any wording: "{t}".'     # lab comparison only
LINK_WORDING = ('Read the LAST sentence below; any earlier sentence only shows what it refers to. '
                'It says, in any wording: "{t}".')
_CRITERIA = {"true": "the sentence says it", "false": "the sentence does not say it"}


def q_says(lab: Label) -> dict:
    """The no-context question (S1): the lab's baseline, not used to anchor."""
    return {"type": "noul", "instructions": LINK_WORDING_S1.format(t=lab.text.strip().rstrip(".")),
            "criteria": _CRITERIA}


def q_link(lab: Label) -> dict:
    return {"type": "noul", "instructions": LINK_WORDING.format(t=lab.text.strip().rstrip(".")),
            "criteria": _CRITERIA}


def link_state(u: Unit) -> str:
    """What Jev reads for a unit: the previous sentence (context) and the unit's own sentence, last."""
    return f"{u.prev}\n{u.sentence}".strip() if u.sentence else u.text


def _words(s: str) -> set:
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


Cand = Tuple[int, Optional[Tuple[int, int]]]    # (unit index, the term span in it, or None: the whole unit)


def candidates(report: str, labels: List[Label], us: List[Unit], got: Dict[str, Anchor]) -> Dict[str, List[Cand]]:
    """Every label's candidate units for Jev: a proposal's own unit; else every unit its term hits (the span when it
    hits once there); else every unit sharing a content word. Shadowed labels are never asked."""
    out: Dict[str, List[Cand]] = {}
    for lab in labels:
        a = got.get(lab.ref)
        if a is not None and a.how == "none":
            continue                                   # shadowed
        if a is not None and a.how == "proposed":
            n = next((n for n, u in enumerate(us) if u.start <= a.span[0] and a.span[1] <= u.end), None)
            out[lab.ref] = [] if n is None else [(n, (a.span[0], a.span[1]))]
            continue
        hits: List[Cand] = []
        for n, u in enumerate(us):
            spans, pos = [], 0
            while (m := ln.term_span(u.text, lab.term, pos)) is not None:
                spans.append((u.start + m[0], u.start + m[1]))
                pos = m[1]
            if spans:
                hits.append((n, spans[0] if len(spans) == 1 else None))
        if not hits:
            w = _words(lab.term)
            hits = [(n, None) for n, u in enumerate(us) if w & _words(u.text)]
        out[lab.ref] = hits
    return out


async def link(labels: List[Label], us: List[Unit], cands: Dict[str, List[Cand]], jev=None) -> Dict[str, Anchor]:
    """Jev confirms → {ref: Anchor} for the labels that anchor. One request per sentence (the state is the previous
    sentence and the unit's sentence: `link_state`), asking each label that has a candidate unit in it. A label
    anchors when Jev scores exactly one sentence at P >= LINK_MIN, on the one candidate unit there (its term span when
    it has one: "term+jev", else the whole unit: "jev"); two candidate units of that sentence with no single term
    hit are ambiguous. Any unanswered candidate (failure, timeout, unreadable) leaves the label unanchored."""
    jev = jev or rc._jev
    by_lab = {lab.ref: (k, lab) for k, lab in enumerate(labels)}
    asks: Dict[str, Dict[str, dict]] = {}
    for ref, cs in cands.items():
        if ref not in by_lab:
            continue
        k, lab = by_lab[ref]
        for n, _ in cs:
            asks.setdefault(link_state(us[n]), {})[f"l{k}"] = q_link(lab)
    if not asks:
        return {}

    async def one(state: str):
        return await asyncio.wait_for(jev(state, asks[state]), LINK_TIMEOUT_S)
    states = list(asks)
    results = await asyncio.gather(*(one(st) for st in states), return_exceptions=True)
    answers: Dict[Tuple[str, str], Optional[float]] = {}
    for st, r in zip(states, results):
        if isinstance(r, BaseException):
            logger.warning("brief anchor: Jev link failed (%s: %s)", type(r).__name__, str(r)[:200])
            r = {}
        for qk in asks[st]:
            try:
                answers[(st, qk)] = float(r[qk]["noul"])
            except (KeyError, TypeError, ValueError):
                answers[(st, qk)] = None
    out: Dict[str, Anchor] = {}
    for ref, cs in cands.items():
        if ref not in by_lab or not cs:
            continue
        k, lab = by_lab[ref]
        ps = [(answers.get((link_state(us[n]), f"l{k}")), n, sp) for n, sp in cs]
        if any(p is None for p, _, _ in ps):
            continue                                   # an unanswered candidate: "only this one" can't be trusted
        win = [(p, n, sp) for p, n, sp in ps if p >= LINK_MIN]
        if len({us[n].sstart for _, n, _ in win}) != 1:
            continue                                   # none, or several sentences: ambiguous
        termed = [w for w in win if w[2]]
        pick = termed[0] if len(termed) == 1 else (win[0] if len(win) == 1 else None)
        if pick is None:
            continue
        p, n, sp = pick
        u = us[n]
        s, e = sp if sp else (u.start, u.end)
        out[ref] = _anchor(lab, how="term+jev" if sp else "jev", span=[s, e],
                           span_text=u.text[s - u.start:e - u.start],
                           unit=u.text, offset=s - u.start, p=round(p, 3), dupes=sum(x.text == u.text for x in us))
    return out


async def anchor(report: str, decisions: Optional[dict], jev=None) -> List[Anchor]:
    """Code proposes, Jev confirms: one Anchor per brief label in label order. Never raises."""
    try:
        labels = brief_labels(decisions)
        if not labels:
            return []
        us = units(report)
        got, _ = match_terms(report, labels, us)
        cands = candidates(report, labels, us, got)
        linked = await link(labels, us, cands, jev) if cands else {}
        out: Dict[str, Anchor] = {}
        for lab in labels:
            a = linked.get(lab.ref) or got.get(lab.ref)
            out[lab.ref] = a if a is not None and (anchored(a) or a.shadowed_by) else _anchor(lab)
        # a label shadowed by a proposal Jev did not confirm was never merged into anything: unanchored
        for ref, a in list(out.items()):
            if a.shadowed_by and not anchored(out.get(a.shadowed_by)):
                out[ref] = _anchor(next(l for l in labels if l.ref == ref))
        return [out[l.ref] for l in labels]
    except Exception as e:  # noqa: BLE001 - anchoring never blocks the report
        logger.warning("brief anchor failed (%s: %s)", type(e).__name__, str(e)[:200])
        return []


def relocate_one(a, report: str, us: Optional[List[Unit]] = None) -> Optional[Tuple[int, int]]:
    """One anchor (an `Anchor` or its persisted dict) re-found on `report`: only among the report's current units with
    the anchor's unit text (the nearest to the old position if several), then the span inside it. None when no such
    unit holds the span text, or the number of identical units changed (`dupes`): never onto text that is not a unit.
    The one relocation rule (`relocate`, and the review engine's `brief_normals`)."""
    get = a.get if isinstance(a, dict) else (lambda k, d=None: getattr(a, k, d))
    span, offset, text = get("span"), int(get("offset") or 0), get("span_text") or ""
    unit, dupes = get("unit") or "", int(get("dupes") or 0)
    if not text or not unit:
        return None
    old = (span[0] - offset) if span else 0
    same = [u for u in (units(report) if us is None else us) if u.text == unit]
    # the number of identical units changed (one was edited out): which one is ours is unknowable
    if not same or dupes not in (0, len(same)):
        return None
    u = min(same, key=lambda x: abs(x.start - old))
    k = u.start + offset
    return (k, k + len(text)) if report[k:k + len(text)] == text else None


def relocate(anchors: List[Anchor], report: str) -> List[Anchor]:
    """The anchors re-found on `report` (the check's edits shift positions) by `relocate_one`. No such unit means the
    clause is "removed"."""
    us = units(report)
    out: List[Anchor] = []
    for a in anchors:
        if not anchored(a):
            out.append(a)
            continue
        sp = relocate_one(a, report, us)
        if sp is None:
            out.append(Anchor(**{**asdict(a), "how": "removed", "span": None}))
        else:
            out.append(Anchor(**{**asdict(a), "span": [sp[0], sp[1]]}))
    return out


CONTRA_MIN = 0.6     # the post-gen check's CONTRA_FLAG (L-46)
OMIT_CARD_MIN = 0.3  # an OMIT / split card below this contradiction score is only logged (anchor_log.omit_low)


def _clause_spans(report: str, clause: str) -> List[Tuple[int, int]]:
    """Every occurrence of the clause (minus its final ".") that is a whole sentence or list item."""
    c = clause.strip().rstrip(".")
    out: List[Tuple[int, int]] = []
    i = report.find(c) if c else -1
    while i >= 0:
        before = report[:i].rstrip(" \t")
        rest = report[i + len(c):]
        starts = before == "" or before[-1] in "\n.!?-*\u2022"
        r = rest.lstrip(" \t")
        ends = r == "" or r[0] == "\n" or (rest[:1] == "." and (rest[1:2] == "" or rest[1:2].isspace()))
        if starts and ends:
            out.append((i, i + len(c)))
        i = report.find(c, i + 1)
    return out


def brief_rules(report: str, anchors: List[Anchor], contra: Dict[str, float], flagged: List[str],
                review_contra: List[str], sentence_type: Optional[Dict[str, Optional[str]]] = None) -> dict:
    """Spec §3.2 -> {"protect": clauses never removed, "would_remove": OMIT clauses the brief would remove,
    "conflicts": cards, "omit_low": OMIT / split cards below OMIT_CARD_MIN, logged only}. The brief vetoes, it never
    removes: "would_remove" is a shadow log (the check removes them only under RR_BRIEF_REMOVE=1, behind its own
    last-step invariant). `contra`: Jev's contradiction score per checked clause; `flagged`: negative clauses the
    check would remove; `review_contra`: positive / normal clauses it flagged for review; `sentence_type`: Jev's
    statement type of the sentence holding each clause. A clause's holders are the anchors overlapping ANY
    whole-sentence occurrence of it (FINDINGS and IMPRESSION both); a KEEP or dictated holder at any occurrence
    blocks removal."""
    live = [a for a in anchors if anchored(a) and a.span]
    by_ref = {a.ref: a for a in anchors}
    types = sentence_type or {}

    def holders(clause: str) -> Tuple[List[Anchor], List[Anchor]]:
        """(direct holders, KEEP-type labels shadowed by a direct holder that is not itself dictated)."""
        spans = _clause_spans(report, clause)
        held = [a for a in live if any(a.span[0] < e and s < a.span[1] for s, e in spans)]
        refs = {a.ref for a in held}
        shadow = [a for a in anchors if a.shadowed_by in refs and a.action in KEEP and a not in held
                  and by_ref[a.shadowed_by].action != "dictated"]
        return held, shadow

    protect: List[str] = []
    would: List[dict] = []
    conflicts: List[dict] = []
    low: List[dict] = []
    flag = list(dict.fromkeys(flagged + review_contra))
    for clause in list(dict.fromkeys(flag + list(contra))):
        held, shadow = holders(clause)
        keep = [a for a in held + shadow if a.action in KEEP and a.action != "dictated"]
        dictated = any(a.action == "dictated" for a in held + shadow)
        omit = [a for a in held if a.action in OMIT]
        score = contra.get(clause)
        if clause in flag:
            if keep or dictated:
                protect.append(clause)
            if keep:      # Q2: a brief-kept clause Jev doubts is a card, never a removal
                conflicts.append({"clause": clause, "refs": [a.ref for a in keep], "reason": "brief_kept",
                                  "score": None if score is None else round(score, 3), "source": keep[0].source,
                                  "pointer": next((a.pointer for a in keep if a.pointer), "")})
            continue
        if score is None or not omit or dictated:
            continue  # dictated beats OMIT: no removal, no card (logged by anchor_log via shadowing)
        c = clause.strip().rstrip(".")
        whole = all(c in (a.unit or "") for a in omit)       # the OMIT unit covers the whole clause
        refs = [a.ref for a in omit + keep]
        card = {"clause": clause, "refs": refs, "reason": "brief_split" if keep else "brief_omitted",
                "score": round(score, 3), "source": (keep or omit)[0].source, "action": omit[0].action,
                "pointer": next((a.pointer for a in omit + keep if a.pointer), "")}
        if score >= CONTRA_MIN and not keep and whole and types.get(clause) == "normal":
            would.append({"clause": clause, "score": round(score, 3), "refs": refs, "action": omit[0].action})
            conflicts.append(card)                                    # Q3: two signals, shadow-logged and carded
        elif score >= OMIT_CARD_MIN:
            conflicts.append(card)
        else:
            low.append(card)
    return {"protect": protect, "would_remove": would, "conflicts": conflicts, "omit_low": low}


def anchor_log(anchors: List[Anchor], rules: dict) -> dict:
    """quality_check.anchor_log: what anchored how, what did not (spec Q4: logged, never surfaced), brief errors
    (an OMIT label whose words a dictated label holds, e.g. a dictated "No ascites" the brief called contradicted)."""
    dictated = {a.ref for a in anchors if a.action == "dictated"}
    return {"labels": len(anchors),
            "by_term_jev": sum(a.how == "term+jev" for a in anchors),
            "by_jev": sum(a.how == "jev" for a in anchors),
            "removed": sum(a.how == "removed" for a in anchors),
            "unanchored": [{"ref": a.ref, "source": a.source, "action": a.action}
                           for a in anchors if a.how == "none" and not a.shadowed_by],
            "shadowed": [{"ref": a.ref, "shadowed_by": a.shadowed_by} for a in anchors if a.shadowed_by],
            "brief_errors": [{"ref": a.ref, "shadowed_by": a.shadowed_by} for a in anchors
                             if a.shadowed_by in dictated and a.action in OMIT],
            "protected": len(rules.get("protect") or []), "removed_by_brief": len(rules.get("removed") or []),
            "would_remove_by_brief": list(rules.get("would_remove") or []),
            "omit_low": list(rules.get("omit_low") or []),
            "conflicts": len(rules.get("conflicts") or [])}
