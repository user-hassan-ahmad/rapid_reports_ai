"""Negatives classifier (Plan 2 Task 14; memories default-negatives, generation-proposes-review-disposes).

Generation states undictated normals by design; this pass makes them visible and controllable. One Qwen reasoning
call per report labels every generated normal/negative statement `dictated | default | implicated | contradicted`
(prompt: `prompts/negatives.txt`, a verbatim copy of the lab's `negatives_v5.txt`). Code adds the `number` check
(a measurement the dictation and history lack) and removes what it can remove cleanly. Ported from
`scripts/review_labs/negatives_lab.py` and `negatives_bundle.py`.

Entry point (Task 10's engine calls it concurrently with the lanes)::

    async def classify_negatives(inp: ReviewInput, run_id: str, types=None) -> tuple[list[ReviewItem], dict]

Items bypass the adjudicator (binding correction 10) and are never merged with lane candidates. Routing:

    label                                   kind            status        cls
    default                                 assumed_normal  open          info    (editor-only, no rail row)
    implicated                              assumed_normal  open          info    evidence.form "negative" (amber), pointer
    contradicted, code-removable            removed         pre_applied   action  edit mode remove (correction 12)
    contradicted, not removable             check           open          action  check_reason "conflict"
                                                                                  (+ code's one-click removal when
                                                                                  the guards pass; never pre-applied)
    default / implicated / dictated, number check           open          minor   check_reason "number"
      ... the number is a measurement       check           open          action  (no invented numbers)
    dictated                                (no item)

default → evidence.form "normal" (green); unlabelled (model failure) → statement wording (spec 2026-10-09 §3.3).

Candidates are negatives and plain normal statements in any wording (`jev_pass.normal_statement`, shared with the
Accuracy lane's W1n exclusion). Every check item's label states its reason, naming the classifier's pointer (or the
number) when there is one, and `reason` says what to do. Candidates the brief's linked normals already label (`owned`
spans) are not sent to the model; they are routed unlabelled (`classify_negatives`). Assumed-normal and check items
carry `evidence.form` ("negative" | "normal", `jev_pass.statement_form`) for the rail's AI layer.

A number-flagged clause is never removed: the verifier's removal rule refuses any clause holding a number
(`_negative_only`), so only a contradicted plain negative is removed. It is a check item with `check_reason`
"number" (or "conflict" when the classifier also labelled it contradicted). On a model failure every candidate is
unlabelled: number-flagged clauses still become check/number, the rest are assumed normal; nothing is removed.

`removed` requires a code-built removal (production's `remove_negative_clause`) for which
`verifier.preapply_failures(..., "removed", ..., code_built=True)` returns [] and whose text occurs once in the
original report. Nothing classed `dictated` is ever removed. Keys use the fixed original kind `negative` plus the
statement text, so a label that flips between runs keeps its key.

One card per claim: a normal/negative claim in FINDINGS repeated in IMPRESSION (`claim_links`) is one item anchored
on the FINDINGS copy with the IMPRESSION copy in `evidence.also_anchors`; it carries the worse of the two labels
(`evidence.claim_labels` keeps both) and is never removed by code (a removal of one copy would leave the other).

Positions: every anchor is on the ORIGINAL report (`text_hash` = its hash), the text the user sees in shadow; a
removed item's anchor is the removed clause's original span (`evidence["removed_text"]` kept). Removals are applied
in item order; each removed item's `edit` is relative to the report just before it, and `log["report"]` is the
report after all of them. Post-removal positions are kept only in `log["post_removal_anchors"]` ({item id: [start,
end]} on `log["report"]`; a removal is zero-width at its removal point). Items carry a `created` history event
(original hash) and, when removed, a `pre_applied` event (hash of the text it was applied to). Fail-soft: a model
failure (validation or transport) is recorded in `log["error"]` / `log["error_kind"]`."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, field_validator

from .. import report_reconcile as rc
from ..enhancement_utils import _run_agent_with_model
from ..report_review import checked_clauses_in_context, remove_negative_clause, restate
from . import checks, claims, verifier
from .jev_pass import normal_statement, recommendation, recommendation_parts, split_tails, statement_form
from .items import Edit, ReviewInput, ReviewItem, Span, item_key, report_body, text_hash

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "negatives.txt"
MODEL = rc.QWEN
SETTINGS = {"temperature": 0, "max_tokens": 16384, "reasoning_effort": "medium"}
RETRIES = 0                 # retries at T=0 repeat the same output (binding correction 1)
TIMEOUT_S = 90.0
DETECTOR = "negatives.v5"
LANE = "accuracy"           # the normal/negative half of Accuracy
ORIGINAL_KIND = "negative"  # key kind: stable whatever label the classifier gives
CLASSES = ("dictated", "default", "implicated", "contradicted")
CLS = {"assumed_normal": "info", "uncertain": "minor", "number": "minor", "conflict": "action", "removed": "action",
       "measurement": "action"}   # no invented numbers: an undictated measurement is never minor
CHECK_REASONS = ("uncertain", "conflict", "number")
_POINTER_MAX = 60
_WORDY = re.compile(r"[^\W_]")


def pointer_text(pointer: Optional[str]) -> str:
    """A model-written pointer to the dictated finding, or "" for a placeholder with no words ("-", "->", "—"):
    the label prompts' "or -" is sometimes written "->"."""
    p = " ".join((pointer or "").split())
    return p if _WORDY.search(p) else ""


def _quote(pointer: str) -> str:
    p = " ".join((pointer or "").split())
    return f"“{p[:_POINTER_MAX - 1]}…”" if len(p) > _POINTER_MAX else f"“{p}”"


def check_text(reason: str, pointer: str) -> Tuple[str, str]:
    """(label, reason) for a check item: the label states why it is a check, naming the dictated finding (or the
    number) when there is one; the reason says what to do."""
    pointer = pointer_text(pointer)
    q = _quote(pointer) if pointer else ""
    if reason == "conflict":
        return ((f"Check: conflicts with {q}" if q else "Check: conflicts with your dictation"),
                (f"Your dictation reports {q}, which this generated statement contradicts. Remove or correct it."
                 if q else "Your dictation contradicts this generated statement. Remove or correct it."))
    if reason == "number":
        return ((f"Check: {q} is not in your dictation" if q else "Check: number not in your dictation"),
                (f"The measurement {q} is in neither your dictation nor the history. Confirm or remove it."
                 if q else "This number is in neither your dictation nor the history. Confirm or remove it."))
    return ((f"Check: may not hold given {q}" if q else "Check: a dictated finding may affect this"),
            (f"Your dictation reports {q}; this generated normal may not hold. Confirm or remove it."
             if q else "A dictated finding may bear on this generated normal. Confirm or remove it."))

AMBER = "Bears on your finding"


def ai_layer(cls: Optional[str], pointer: str = "", finding: str = "", clause: str = "") -> Tuple[str, str, str]:
    """(label, reason, evidence.form) for a generated statement that stays in the report (spec 2026-10-09 §3.3).
    Implicated, and a negative the brief chose for a dictated finding, are amber ("negative"): in the report, worth a
    glance, no rail card. Default is green ("normal"). No label (the classifier failed) falls back to the wording."""
    if cls == "implicated":
        return AMBER, check_text("uncertain", pointer)[1], "negative"
    if finding:
        return AMBER, f"Added by the AI because it bears on your finding: {finding}. Keep it or remove it.", "negative"
    if cls in ("default", "keep"):
        return "Assumed normal", "", "normal"
    return "Assumed normal", "", statement_form(clause)


_NEG = re.compile(r"\b(no|not|nil|without|normal(ly)?|unremarkable|patent|intact|clear|preserved|maintained|"
                  r"within normal limits|non-?dilated|undilated|no evidence)\b", re.I)
_NUM = re.compile(r"(?<![A-Za-z/\d.])\d+(?:\.\d+)?")  # skips T1, C7, L4/5; keeps 4cm
_NUMBER_UNIT = re.compile(r"(?<![A-Za-z/\d.])(\d+(?:\.\d+)?)(\s*(?:mm|cm|ml|mL|%|HU|degrees?))?")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt() -> str:
    return PROMPT_PATH.read_text().strip()


# ── candidates and code checks ───────────────────────────────────────────────

def is_normal_or_negative(clause: str) -> bool:
    """A negative, or a normal statement in any wording the Accuracy lane leaves to this classifier
    (`jev_pass.normal_statement`: "maintains continuity", "is smooth", ...)."""
    return bool(_NEG.search(clause)) or normal_statement(clause)


def candidates(report: str, types: Optional[Dict[str, str]] = None) -> List[dict]:
    """Every normal/negative clause the check reads (FINDINGS + IMPRESSION), with the sentence before it.
    Recommendation sentences are never candidates ("CT spine without contrast" is not a negative); a sentence holding
    a recommendation part and other parts at ';' (`jev_pass.recommendation_parts`) contributes its other parts.

    `types` (clause text → the Jev statement type, `jev_pass`): a normal clause is a candidate whole; an abnormal or
    mixed clause contributes only the negative / normal tails code can split off and locate (`split_tails`), else
    nothing (it is routed as abnormal); not_a_finding contributes nothing. A plain negative ("No X") and an untyped
    clause follow today's lexicon."""
    out: List[dict] = []
    for c, b in checked_clauses_in_context(report, None).items():
        if recommendation(c):
            # a recommendation beside other parts ("No X identified; referral recommended."): the other parts are
            # still statements, read on their own when code can locate them
            for s, e, rec in recommendation_parts(c) or []:
                part = c[s:e]
                if not rec and _locate(report, part, []) is not None:
                    out.extend(_clause_candidates(report, part, b, types))
            continue
        out.extend(_clause_candidates(report, c, b, types))
    return out


def _clause_candidates(report: str, c: str, b: str, types: Optional[Dict[str, str]]) -> List[dict]:
    """One non-recommendation clause's candidates (see `candidates`)."""
    t = (types or {}).get(c)
    if t is None or restate(c) is not None:
        return [{"clause": c, "before": b}] if is_normal_or_negative(c) else []
    if t == "normal":
        return [{"clause": c, "before": b}]
    if t in ("abnormal", "mixed"):
        sp = split_tails(c)
        return [{"clause": tail, "before": b} for tail in (sp[1] if sp else [])
                if not recommendation(tail) and _locate(report, tail, []) is not None]
    return []


def candidate_spans(report: str, types: Optional[Dict[str, str]] = None) -> List[Tuple[int, int]]:
    """Original-report spans of every clause the classifier will read: pure code, known before its model call."""
    taken: List[Tuple[int, int]] = []
    for c in candidates(report, types):
        span = _locate(report, c["clause"], taken)
        if span:
            taken.append(span)
    return taken


def code_number_flag(clause: str, dictation: str, history: str) -> bool:
    return bool(set(_NUM.findall(clause)) - set(_NUM.findall(f"{dictation}\n{history}")))


def undictated_numbers(clause: str, dictation: str, history: str) -> str:
    """The measurement(s) in a clause that the dictation and history do not contain, e.g. "12 mm"."""
    have = {m.group(1) for m in _NUMBER_UNIT.finditer(f"{dictation}\n{history}")}
    return ", ".join(m.group(0).strip() for m in _NUMBER_UNIT.finditer(clause) if m.group(1) not in have)


# ── model output ─────────────────────────────────────────────────────────────

def decode_json_list(v: Any) -> List[Any]:
    """Qwen string-encodes list fields (L-50): accept a list, a JSON-encoded list, or one plain string."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if not s:
        return []
    if s.startswith('"') or s.startswith("["):
        try:
            out = json.loads(s)
            if isinstance(out, str):
                return [out]
            if isinstance(out, list):
                return out
        except json.JSONDecodeError:
            pass
    return [s]


class Labels(BaseModel):     # FLAT on purpose (L-50)
    labels: List[str]

    @field_validator("labels", mode="before")
    @classmethod
    def _decode(cls, v):
        return [str(x) for x in decode_json_list(v)]


def parse_labels(lines: List[str], n: int) -> Dict[int, dict]:
    """'<n> | <class> | <pointer or -> | <number yes/no>' → {n: {...}}; unknown classes and out-of-range n dropped."""
    out = {}
    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        i, cls = int(parts[0]), parts[1].lower()
        if 1 <= i <= n and cls in CLASSES:
            out[i] = {"cls": cls, "pointer": pointer_text(parts[2]) if len(parts) > 2 else "",
                      "number": len(parts) > 3 and parts[3].lower().startswith("y")}
    return out


def user_message(inp: ReviewInput, cands: List[dict]) -> str:
    listing = "\n".join(f"{i}. {c['clause']}" for i, c in enumerate(cands, 1))
    return (f"STUDY TITLE: {inp.study_title or inp.scan_type}\n\nCLINICAL HISTORY:\n{inp.clinical_history or '(none)'}"
            f"\n\nDICTATION:\n{inp.artifacts.dictated_findings}\n\nREPORT:\n{inp.artifacts.report}"
            f"\n\nSTATEMENTS TO CLASSIFY:\n{listing}")


def _error_kind(e: BaseException) -> str:
    name = type(e).__name__
    return "validation" if any(t in name for t in ("Validation", "UnexpectedModelBehavior")) else "transport"


async def classify(inp: ReviewInput, cands: List[dict]) -> Tuple[Dict[int, dict], Optional[str], Optional[str]]:
    """(labels by 1-based index, error, error_kind). Never raises: a failure returns no labels (all default)."""
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=MODEL, output_type=Labels, system_prompt=prompt(), user_prompt=user_message(inp, cands),
            api_key="", model_settings=dict(SETTINGS), retries=RETRIES), TIMEOUT_S)
        return parse_labels(r.output.labels, len(cands)), None, None
    except Exception as e:  # noqa: BLE001 - fail-soft: every candidate stays assumed normal
        logger.warning("review engine: negatives classifier failed (%s: %s)", type(e).__name__, str(e)[:200])
        return {}, f"{type(e).__name__}: {str(e)[:200]}", _error_kind(e)


# ── code removal ─────────────────────────────────────────────────────────────

def _diff(before: str, after: str) -> Tuple[int, str]:
    """(position, removed text) when `after` is `before` with one contiguous run deleted."""
    p = 0
    while p < len(after) and before[p] == after[p]:
        p += 1
    s = 0
    while s < len(after) - p and before[-1 - s] == after[-1 - s]:
        s += 1
    return p, before[p:len(before) - s]


def removal_edit(doc: str, clause: str) -> Optional[Edit]:
    """Code's removal of one negative clause from `doc`, built by production's `remove_negative_clause`: a
    `remove` Edit of exactly the deleted text, or None when the removal is not a single clean deletion of text
    that occurs once."""
    new = remove_negative_clause(doc, clause)
    if new == doc:
        return None
    p, gone = _diff(doc, new)
    if doc[:p] + doc[p + len(gone):] != new:
        return None                                   # not a pure deletion (e.g. a list re-joined)
    find = gone.strip()
    if not find or doc.count(find) != 1:
        return None
    return Edit(mode="remove", find=find)


def _locate(report: str, clause: str, taken: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
    """Span of a classified clause in the report: the clause itself, or, for an item split out of a negative list
    ("No X" from "No A, X or B"), the item's own words."""
    c = clause.strip().rstrip(".")
    needles = [c]
    m = re.match(r"^(?:No|There is no|There are no|Without)\s+(.+)$", c, re.I)
    if m:
        needles.append(m.group(1))
    for needle in needles:
        start = 0
        while (i := report.find(needle, start)) >= 0:
            span = (i, i + len(needle))
            if not any(a < span[1] and span[0] < b for a, b in taken):
                return span
            start = i + 1
    return None


# ── routing ──────────────────────────────────────────────────────────────────

def _conflict_fix(inp: ReviewInput, report: str, anchor: Optional[Span], clause: str, names: List[str]
                  ) -> Tuple[Optional[Edit], Optional[dict]]:
    """A contradicted statement code could not pre-apply: code's removal of it (verifier `_negative_fix`, never an
    LLM rewrite, L-47) as a one-click edit when the code guards pass. Never pre-applied: no probe confirms it."""
    if anchor is None:
        return None, None
    fix = verifier._negative_fix(report, anchor.start, anchor.end, clause, names)
    if fix is None:
        return None, None
    fails = verifier.guard_failures(report, fix, "contradicted", inp.artifacts.dictated_findings or "",
                                    inp.clinical_history or "", sections=names, target=clause)
    if fails:
        return None, None
    return fix, {"code": True, "failed": [], "addressed": None, "contra": None, "unconfirmed": True}


def _to_original(p: int, gaps: List[Tuple[int, int]], end: bool = False) -> int:
    """A position on the post-removal text → the original report (`gaps`: removed original intervals, sorted and
    disjoint). An `end` position stays before a gap that starts exactly there."""
    o = p
    for s, e in gaps:
        if s < o or (s == o and not end):
            o += e - s
        else:
            break
    return o


def _add_gap(gaps: List[Tuple[int, int]], s: int, e: int) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for a, b in sorted(gaps + [(s, e)]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


_SEVERITY = {"dictated": 0, "default": 1, "implicated": 2, "contradicted": 3}


def claim_links(report: str, cands: List[dict], names: List[str]) -> Dict[int, int]:
    """{1-based candidate index: its partner}: a normal/negative claim stated in FINDINGS and repeated in
    IMPRESSION (`claims.same_claim`, conservative, one-to-one). Pure code, on the original report."""
    taken: List[Tuple[int, int]] = []
    entries = []
    for c in cands:
        span = _locate(report, c["clause"], taken)
        if span:
            taken.append(span)
        sec = verifier._section_of(report, span[0], names) if span else None
        entries.append((sec, c["clause"], ORIGINAL_KIND))
    out: Dict[int, int] = {}
    for f, m in claims.link_pairs(entries, negative=True):
        out[f + 1], out[m + 1] = m + 1, f + 1
    return out


def route(inp: ReviewInput, run_id: str, cands: List[dict], labels: Dict[int, dict]
          ) -> Tuple[List[ReviewItem], str, Dict[str, List[int]]]:
    """Labelled candidates → (items anchored on the original report, the report after pre-applied removals,
    post-removal anchor positions by item id). Pure code."""
    names = list(inp.artifacts.sections or [])
    dictation, history = inp.artifacts.dictated_findings or "", inp.clinical_history or ""
    report = inp.artifacts.report
    doc = report
    removed: List[dict] = []
    gone_idx = set()
    gaps: List[Tuple[int, int]] = []
    partner = claim_links(report, cands, names)       # one claim in FINDINGS and IMPRESSION: one verdict
    for i, c in enumerate(cands, 1):
        if (labels.get(i) or {}).get("cls") != "contradicted" or i in partner:
            continue                                  # numbers are never removable (see the module docstring)
        edit = removal_edit(doc, c["clause"])
        if edit is None or report.count(edit.find) != 1 or verifier.preapply_failures(
                doc, edit, "removed", dictation, code_built=True, sections=names):
            continue                                  # not removable by code: a check item below
        new = verifier.apply_edit(doc, edit, names)
        if new is None:
            continue
        p, gone = _diff(doc, new)
        k = gone.find(edit.find)
        o_start = _to_original(p + k, gaps)
        o_end = _to_original(p + k + len(edit.find), gaps, end=True)
        for r in removed:                             # earlier post-removal points after p shift left
            if r["post"] > p:
                r["post"] = max(p, r["post"] - len(gone))
        removed.append({"i": i, "post": p, "orig": (o_start, o_end), "edit": edit, "before_hash": text_hash(doc)})
        gaps = _add_gap(gaps, _to_original(p, gaps), _to_original(p + len(gone), gaps, end=True))
        gone_idx.add(i)
        doc = new
    h = text_hash(report)
    items: Dict[int, ReviewItem] = {}
    post: Dict[int, List[int]] = {}

    def item(c: dict, kind: str, status: str, cls_key: str, anchor: Optional[Span], evidence: dict,
             label: str, edit: Optional[Edit] = None, applied_hash: Optional[str] = None, reason: str = "",
             verified: Optional[dict] = None) -> ReviewItem:
        sec = verifier._section_of(report, anchor.start, names) if anchor else None
        history = [{"at": _now(), "event": "created", "actor": "engine", "text_hash": h,
                    "detail": {"detectors": [DETECTOR]}}]
        if status == "pre_applied":
            history.append({"at": _now(), "event": "pre_applied", "actor": "engine", "text_hash": applied_hash,
                            "detail": {"kind": kind}})
        return ReviewItem(key=item_key(LANE, ORIGINAL_KIND, c["clause"]), report_id=inp.report_id, run_id=run_id,
                          lane=LANE, detectors=[DETECTOR], kind=kind, cls=CLS[cls_key],
                          section=sec.upper() if sec else None, anchor=anchor, label=label, reason=reason,
                          edit=edit, evidence=evidence, status=status, history=history,
                          verified={"code": True, "failed": [], "addressed": None, "contra": None,
                                    "unconfirmed": False, "preapply_failures": []} if status == "pre_applied"
                          else verified)

    for r in removed:
        i = r["i"]
        c, lab = cands[i - 1], labels.get(i) or {}
        s0, e0 = r["orig"]
        items[i] = item(c, "removed", "pre_applied", "removed",
                        Span(start=s0, end=e0, text=report[s0:e0], text_hash=h),
                        {"removal_reason": "contradicted", "pointer": lab.get("pointer", ""),
                         "removed_text": r["edit"].find, "clause": c["clause"], "label": lab.get("cls") or "default"},
                        "Removed: contradicts your dictation", r["edit"], r["before_hash"],
                        reason=check_text("conflict", lab.get("pointer", ""))[1].replace(
                            "Remove or correct it.", "It was removed; restore it if it is right."))
        post[i] = [r["post"], r["post"]]
    taken: List[Tuple[int, int]] = [r["orig"] for r in removed]
    taken_post: List[Tuple[int, int]] = []
    secondary_span: Dict[int, Span] = {}
    for i, c in enumerate(cands, 1):
        lab = labels.get(i) or {}
        cls = lab.get("cls") or "default"
        group = [i, partner[i]] if partner.get(i, 0) > i else None
        if group:                                     # the FINDINGS copy carries the group's worst verdict
            lab = max((labels.get(k) or {} for k in group),
                      key=lambda x: _SEVERITY.get(x.get("cls") or "default", 1))
            cls = lab.get("cls") or "default"
            c = {**c, "number": any(cands[k - 1]["number"] for k in group)}
        is_secondary = 0 < partner.get(i, 0) < i
        if i in gone_idx or (cls == "dictated" and not c["number"] and not is_secondary):
            continue
        span = _locate(report, c["clause"], taken)
        if span:
            taken.append(span)
        if is_secondary:                              # the IMPRESSION copy: an also-anchor of the FINDINGS item
            if span:
                secondary_span[i] = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h)
            continue
        pspan = _locate(doc, c["clause"], taken_post)
        if pspan:
            taken_post.append(pspan)
            post[i] = list(pspan)
        anchor = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h) if span else None
        base = {"clause": c["clause"], "label": cls, "form": statement_form(c["clause"])}
        if group:
            base["claim_labels"] = [(labels.get(k) or {}).get("cls") or "default" for k in group]
        given = lab.get("pointer", "")                # the classifier's pointer to the dictated finding, if any
        if cls == "contradicted":
            label, why = check_text("conflict", given)
            # a grouped claim has two copies: code's one-click removal of one would leave the other
            fix, verified = (None, None) if group else _conflict_fix(inp, report, anchor, c["clause"], names)
            items[i] = item(c, "check", "open", "conflict", anchor,
                            {**base, "check_reason": "conflict", "pointer": given}, label, edit=fix, reason=why,
                            verified=verified)
        elif c["number"]:
            nums = undictated_numbers(" ".join(cands[k - 1]["clause"] for k in group) if group else c["clause"],
                                      dictation, history)
            label, why = check_text("number", nums)
            measured = [n for n in checks.undictated_numbers(c["clause"], dictation, history)
                        if checks.is_measurement(n)]
            items[i] = item(c, "check", "open", "measurement" if measured else "number", anchor,
                            {**base, "check_reason": "number", "pointer": nums,
                             **({"dictated_pointer": given} if given else {})}, label, reason=why)
        else:                                         # default / implicated: the AI layer, never a rail card
            label, why, form = ai_layer(lab.get("cls"), given, clause=c["clause"])
            items[i] = item(c, "assumed_normal", "open", "assumed_normal", anchor,
                            {**base, "form": form, **({"pointer": given} if cls == "implicated" else {})},
                            label, reason=why)
    for i, sp in secondary_span.items():
        it = items.get(partner[i])
        if it is not None:
            it.evidence = {**(it.evidence or {}), "also_anchors": [sp.model_dump()]}
    return ([items[i] for i in sorted(items)], doc,
            {items[i].id: post[i] for i in sorted(items) if i in post})


# Coordinated items of a statement ("No A, B or C", "The A, B and C are unremarkable"): split at ',' / 'or' / 'and',
# never at "and is / are / has ..." (a second predicate of the same item, `jev_pass._TURN`'s structure).
_COORD = re.compile(r"\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+(?!(?:is|are|was|were|has|have)\b)", re.I)


def covered(text: str, start: int, spans: List[Tuple[int, int]]) -> bool:
    """Do `spans` (report positions) own the statement `text` (at report position `start`)? The coordination gate,
    pure mechanics: split it into its coordinated items (`_COORD`); it is owned only when EVERY item overlaps a span.
    "No uncal or tonsillar herniation" with only "tonsillar herniation" owned: not owned; "No significant
    lymphadenopathy" owned on "lymphadenopathy": owned (one item)."""
    bounds, pos = [], 0
    for m in _COORD.finditer(text):
        bounds.append((pos, m.start()))
        pos = m.end()
    bounds.append((pos, len(text)))
    items = [(start + a, start + b) for a, b in bounds if text[a:b].strip()]
    return bool(items) and all(any(s < e2 and s2 < e for s2, e2 in spans) for s, e in items)


def owned_indices(report: str, cands: List[dict], owned: List[Tuple[int, int]]) -> List[int]:
    """1-based indices of the candidates whose original-report span the `owned` spans (the brief's labels,
    `brief_normals.owned_spans`) cover (`covered`): the brief already labelled them, so the model does not re-read
    them. A candidate the brief owns only in part ("tonsillar herniation" of "No uncal or tonsillar herniation") is
    read: its other statements have no other owner."""
    taken: List[Tuple[int, int]] = []
    out = []
    for i, c in enumerate(cands, 1):
        span = _locate(report, c["clause"], taken)
        if span:
            taken.append(span)
            if covered(report[span[0]:span[1]], span[0], owned):
                out.append(i)
    return out


async def classify_negatives(inp: ReviewInput, run_id: str, types: Optional[Dict[str, str]] = None,
                             owned: Optional[List[Tuple[int, int]]] = None) -> Tuple[List[ReviewItem], dict]:
    """The Task 14 entry point: (items, log). Never raises. `log` holds the report after pre-applied removals,
    its hash, candidate/label counts, latency and any model error (fail-soft).

    `owned`: original-report spans the brief already owns (`brief_normals.owned_spans`: its own item, deliberately
    none for dictated / OMIT, or a conflict card). Candidates on them are not sent to the model (latency: the call's
    reasoning grows with the statement list) and are routed as `dictated`: no item, while code's number check still
    applies (an undictated number keeps its number card). In a claim group an owned copy has dictated severity, so it
    never raises the group's verdict (e2e 29882bd7: an owned dictated "No ascites" was tinted green)."""
    t0 = time.monotonic()
    report = inp.artifacts.report or ""
    dictation, history = inp.artifacts.dictated_findings or "", inp.clinical_history or ""
    body = report_body(inp)                           # never the signature block (a prefix: same positions)
    listed = candidates(body, types) if types else candidates(body)
    cands = [{**c, "number": code_number_flag(c["clause"], dictation, history)} for c in listed]
    skip = set(owned_indices(report, cands, owned)) if owned else set()
    asked = [i for i in range(1, len(cands) + 1) if i not in skip]
    log: dict = {"detector": DETECTOR, "candidates": len(cands), "owned_by_brief": len(skip),
                 "classified": len(asked), "labelled": 0, "error": None, "error_kind": None,
                 "report": report, "text_hash": text_hash(report), "post_removal_anchors": {}, "ms": 0}
    if not cands:
        return [], log
    if asked:
        got, err, kind = await classify(inp, [cands[i - 1] for i in asked])
        labels = {asked[k - 1]: v for k, v in got.items()}
    else:
        labels, err, kind = {}, None, None
    routed = {**labels, **{i: {"cls": "dictated", "pointer": "", "owned": True} for i in skip}}
    try:
        items, doc, post = route(inp, run_id, cands, routed)
    except Exception as e:  # noqa: BLE001 - routing never fails the run: no items, report untouched
        logger.warning("review engine: negatives routing failed (%s: %s)", type(e).__name__, str(e)[:200])
        items, doc, post = [], report, {}
        err, kind = err or f"{type(e).__name__}: {str(e)[:200]}", kind or "routing"
    log.update(labelled=len(labels), error=err, error_kind=kind, report=doc, text_hash=text_hash(doc),
               labels={str(k): v for k, v in labels.items()}, post_removal_anchors=post,
               ms=int((time.monotonic() - t0) * 1000))
    return items, log


__all__ = ["Labels", "candidates", "candidate_spans", "code_number_flag", "undictated_numbers", "parse_labels", "user_message",
           "classify", "removal_edit", "route", "covered", "owned_indices", "classify_negatives"]
