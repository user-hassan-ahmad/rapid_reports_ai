"""Brief labels → the words the generator wrote (spec docs/superpowers/specs/2026-10-09-negatives-one-owner-design.md
§3.1). One owner per judgement: the brief selected and labelled every negative and linked normal before the report was
written; this finds where each one landed so the post-gen check and the review engine defer to that label instead of
re-judging it.

    brief_labels(decisions)          every brief label (mandatory / finding-linked negatives, linked-normal atoms,
                                     dictated negatives) with a stable ref, a key term, and whether a place phrase
                                     was dropped from it (`stripped`: its pass 1 hit needs Jev confirmation)
    units(report)                    the normal / negative statements of FINDINGS + IMPRESSION, with positions
    match_terms(report, labels, us)  pass 1, code: a label's key term in exactly one unit, longest term first
    link(labels, us, confirm)        pass 2, Jev: "does this sentence say X?" for the labels pass 1 left, and the
                                     same question for place-stripped pass 1 hits (one request per unit)
    anchored(a)                      how in ANCHORED ("term", "jev", "term+jev"): the one test of "anchored"
    anchor(report, decisions)        both passes; never raises
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
_PLACE_WORD = re.compile(r"\b(?:in|on|at|within|from|involving)\b", re.I)
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
    stripped: bool = False # key_term dropped a place phrase: a pass 1 hit is provisional until Jev confirms it


def enabled() -> bool:
    """Kill switch: RR_BRIEF_ANCHOR=0 skips anchoring end to end (today's behaviour)."""
    return os.environ.get("RR_BRIEF_ANCHOR", "1").strip().lower() not in ("0", "false", "off")


def key_term(text: str) -> str:
    """The denied phrase without its boilerplate: "No osseous lesion identified in the visualised thoracic skeleton"
    → "osseous lesion"; "... with no definite chest wall involvement" → "chest wall involvement"."""
    return key_term_info(text)[0]


def key_term_info(text: str) -> Tuple[str, bool]:
    """(key_term, stripped): stripped when a place phrase ("in the common bile duct") was dropped, so the bare term
    ("calculus") can name the same words in another organ's sentence. "by ..." (the cause) is not a place."""
    t = (text or "").strip().rstrip(".")
    if _LEAD.match(t):
        t = _LEAD.sub("", t)
    else:
        found = list(_INNER.finditer(t))
        if not found:
            return "", False
        t = t[found[-1].end():]
    t = _HEDGE.sub("", t)
    v = _VERB_TAIL.search(t)
    stripped = bool(v and _PLACE_WORD.search(v.group(0)))
    t = t[:v.start()] if v else t
    m = _PLACE_TAIL.search(t)
    if m and (m.group(0).split()[0].lower() == "by" or not _QUALIFIER.search(m.group(0))):
        stripped = stripped or m.group(0).split()[0].lower() != "by"
        t = t[:m.start()]
    return t.strip(" ,;"), stripped


def _pointer(p) -> str:
    p = str(p or "").strip()
    return "" if p in ("-", "->", "—", "none") else p


def brief_labels(decisions: Optional[dict]) -> List[Label]:
    d = decisions or {}
    out: List[Label] = []
    for i, n in enumerate(d.get("negatives") or []):
        term, stripped = key_term_info(n.get("text") or "")
        if not term:
            continue
        src = n.get("source") or "sheet"
        finding = src.split(":", 1)[1] if src.startswith("finding:") else ""
        out.append(Label(f"neg:{i}", n["text"], term, n.get("action") or "keep", src,
                         _pointer(n.get("dictated_finding")) or finding, stripped))
    for u in d.get("normals") or []:
        if not isinstance(u, dict) or not u.get("linked"):
            continue
        for a in u.get("atoms") or []:
            if a.get("term") and u.get("pid") and a.get("id"):     # a ref needs both, or labels collide
                out.append(Label(f"atom:{u.get('pid')}:{a.get('id')}", a.get("text") or a["term"], a["term"],
                                 a.get("action") or "keep", "atom", _pointer(a.get("pointer"))))
    for i, t in enumerate(d.get("dictated_negatives") or []):
        term, stripped = key_term_info(t)
        if term:
            out.append(Label(f"dict:{i}", t, term, "dictated", "dictated", "", stripped))
    return out


_NORMAL = re.compile(r"\b(?:no|not|nil|without|normal(?:ly)?|unremarkable|patent|intact|clear|preserved|"
                     r"maintained|non-?dilated|undilated)\b", re.I)


@dataclass
class Unit:
    text: str
    start: int
    end: int


@dataclass
class Anchor:
    ref: str
    action: str
    source: str
    pointer: str = ""
    how: str = "none"                 # "term" | "jev" | "term+jev" | "none" | "removed" (its clause was edited out)
    span: Optional[List[int]] = None  # the label's words (term) or the whole unit (jev)
    span_text: str = ""
    unit: str = ""                    # the statement the span sits in
    offset: int = 0                   # span start minus unit start (relocation)
    p: Optional[float] = None         # pass 2 probability
    shadowed_by: Optional[str] = None # its only hit is held by this (longer or dictated) label
    dupes: int = 0                    # units with this unit's text when anchored (0 = unknown); relocate() checks it


ANCHORED = frozenset({"term", "jev", "term+jev"})   # "term+jev": a place-stripped pass 1 hit Jev confirmed


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
        for s, i, j in _sentence_positions(report, a, a + len(sec)):
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
                        out.append(Unit(s[k0:k1], i + k0, i + k1))
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
                    out.append(Unit(t, i + k, i + k + len(t)))
    return out


def _rank(lab: Label) -> Tuple[int, int]:
    """Longest term first; among equal terms a dictated label, then a kept one, then an OMIT one."""
    return (-len(lab.term), 0 if lab.action == "dictated" else (1 if lab.action in KEEP else 2))


def _anchor(lab: Label, **kw) -> Anchor:
    return Anchor(lab.ref, lab.action, lab.source, lab.pointer, **kw)


def match_terms(report: str, labels: List[Label], us: List[Unit]) -> Tuple[Dict[str, Anchor], List[Label]]:
    """Pass 1 → ({ref: Anchor}, labels for pass 2). A label anchors when its term occurs in exactly one unit at a
    position no earlier-ranked label holds. A label whose every hit is held is shadowed (merged into the holder);
    no hit, or several free hits, goes to pass 2. A `stripped` label's hit is returned as "term" but is provisional:
    `anchor` confirms it with Jev (pass 1 alone is the raw code result)."""
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
            got[lab.ref] = _anchor(lab, how="term", span=[s, e], span_text=report[s:e], unit=u.text,
                                   offset=s - u.start, dupes=sum(x.text == u.text for x in us))
        elif not free and held is not None:
            got[lab.ref] = _anchor(lab, how="none", shadowed_by=held)
        else:
            left.append(lab)
    return got, left


# Pass 2 acceptance, Task 4 wording lab (S1): 0 wrong links at 0.90 in both runs; recall 53/90 (run 1, two passes,
# before tails kept their negator) and 28/45 (run 2). The only wrong link (t21) scored 0.83 / 0.82 and Jev drifts
# up to 0.06 between runs, so 0.85 had no margin.
LINK_MIN = 0.90
LINK_TIMEOUT_S = 4.0
LINK_WORDING = 'Read only this sentence. It says, in any wording: "{t}".'


def q_says(lab: Label) -> dict:
    return {"type": "noul", "instructions": LINK_WORDING.format(t=lab.text.strip().rstrip(".")),
            "criteria": {"true": "the sentence says it", "false": "the sentence does not say it"}}


def _words(s: str) -> set:
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


async def link(labels: List[Label], us: List[Unit], jev=None,
               confirm: Optional[List[Tuple[Label, Anchor]]] = None) -> Dict[str, Anchor]:
    """Pass 2 → {ref: Anchor}: one Jev request per unit (the state is the sentence alone), asking each label that
    shares a content word with it. A label anchors to the unit Jev scores at P >= LINK_MIN when no other unit does.
    `confirm`: place-stripped pass 1 hits, asked the same question of their own unit in the same request; confirmed
    → "term+jev" on the pass 1 span, otherwise (no, or no answer) unanchored, never moved to another unit."""
    jev = jev or rc._jev
    asks: Dict[int, Dict[str, dict]] = {}
    for k, lab in enumerate(labels):
        w = _words(lab.term)
        for n, u in enumerate(us):
            if w & _words(u.text):
                asks.setdefault(n, {})[f"l{k}"] = q_says(lab)
    confirm = list(confirm or [])
    where: Dict[int, int] = {}
    for c, (lab, a) in enumerate(confirm):
        n = next((n for n, u in enumerate(us) if a.span and u.start <= a.span[0] and a.span[1] <= u.end), None)
        if n is not None:
            where[c] = n
            asks.setdefault(n, {})[f"c{c}"] = q_says(lab)
    out: Dict[str, Anchor] = {lab.ref: _anchor(lab) for lab, _ in confirm}   # unconfirmed: unanchored
    if not asks:
        return out

    async def one(n: int):
        return n, await asyncio.wait_for(jev(us[n].text, asks[n]), LINK_TIMEOUT_S)
    units_asked = list(asks)
    results = await asyncio.gather(*(one(n) for n in units_asked), return_exceptions=True)
    scores: Dict[int, List[Tuple[float, int]]] = {}
    unsure: set = set()        # labels with an unanswered question: "no other unit is a match" can't be trusted
    for n, r in zip(units_asked, results):
        if isinstance(r, BaseException):
            logger.warning("brief anchor: Jev link failed (%s: %s)", type(r).__name__, str(r)[:200])
            unsure.update(int(qk[1:]) for qk in asks[n] if qk[0] == "l")
            continue
        ans = r[1]
        for qk in asks[n]:
            try:
                p = float(ans[qk]["noul"])
            except (KeyError, TypeError, ValueError):
                if qk[0] == "l":
                    unsure.add(int(qk[1:]))
                continue
            if qk[0] == "c":
                if p >= LINK_MIN:
                    lab, a = confirm[int(qk[1:])]
                    out[lab.ref] = Anchor(**{**asdict(a), "how": "term+jev", "p": round(p, 3)})
                continue
            scores.setdefault(int(qk[1:]), []).append((p, n))
    for k, ps in scores.items():
        if k in unsure:
            continue
        ps.sort(reverse=True)
        if ps[0][0] >= LINK_MIN and (len(ps) == 1 or ps[1][0] < LINK_MIN):
            lab, u = labels[k], us[ps[0][1]]
            out[lab.ref] = _anchor(lab, how="jev", span=[u.start, u.end], span_text=u.text, unit=u.text, offset=0,
                                   p=round(ps[0][0], 3), dupes=sum(x.text == u.text for x in us))
    return out


async def anchor(report: str, decisions: Optional[dict], jev=None) -> List[Anchor]:
    """Both passes, one Anchor per brief label in label order. Never raises."""
    try:
        labels = brief_labels(decisions)
        if not labels:
            return []
        us = units(report)
        got, left = match_terms(report, labels, us)
        prov = [(l, got[l.ref]) for l in labels if l.stripped and l.ref in got and got[l.ref].how == "term"]
        if left or prov:
            got.update(await link(left, us, jev, confirm=prov))
        # a label shadowed by a place-stripped hit Jev did not confirm was never merged into anything: unanchored
        lost = {l.ref for l, _ in prov if not anchored(got[l.ref])}
        for ref, a in list(got.items()):
            if a.shadowed_by in lost:
                got[ref] = Anchor(**{**asdict(a), "shadowed_by": None})
        return [got.get(l.ref) or _anchor(l) for l in labels]
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
            "by_term": sum(a.how == "term" for a in anchors),
            "by_jev": sum(a.how == "jev" for a in anchors),
            "by_term_jev": sum(a.how == "term+jev" for a in anchors),
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
