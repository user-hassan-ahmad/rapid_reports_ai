"""Negatives classifier (Plan 2 Task 14; memories default-negatives, generation-proposes-review-disposes).

Generation states undictated normals by design; this pass makes them visible and controllable. One Qwen reasoning
call per report labels every generated normal/negative statement `dictated | default | implicated | contradicted`
(prompt: `prompts/negatives.txt`, a verbatim copy of the lab's `negatives_v5.txt`). Code adds the `number` check
(a measurement the dictation and history lack) and removes what it can remove cleanly. Ported from
`scripts/review_labs/negatives_lab.py` and `negatives_bundle.py`.

Entry point (Task 10's engine calls it concurrently with the lanes)::

    async def classify_negatives(inp: ReviewInput, run_id: str) -> tuple[list[ReviewItem], dict]

Items bypass the adjudicator (binding correction 10) and are never merged with lane candidates. Routing:

    label                                   kind            status        cls
    default                                 assumed_normal  open          info    (editor-only, no rail row)
    implicated                              check           open          minor   evidence.check_reason "uncertain"
    dictated + undictated number            check           open          minor   check_reason "number"
    contradicted / number, code-removable   removed         pre_applied   action  edit mode remove (correction 12)
    contradicted, not removable             check           open          action  check_reason "conflict"
    number, not removable                   check           open          minor   check_reason "number"
    dictated                                (no item)

`removed` requires a code-built removal (production's `remove_negative_clause`) for which
`verifier.preapply_failures(..., "removed", ..., code_built=True)` returns []. Nothing classed `dictated` is ever
removed. Keys use the fixed original kind `negative` plus the statement text, so a label that flips between runs
keeps its key.

Positions: removals are applied in item order; each removed item's `edit` is relative to the report just before
it, and `log["report"]` is the report after all of them. Every anchor is on `log["report"]` (`text_hash` set):
a removed item's anchor is zero-width at the removal point (restore = insert `evidence["removed_text"]` there,
latest removal first). Fail-soft: a model failure (validation or transport) leaves every candidate `default`
(assumed normal, never removed), recorded in `log["error"]` / `log["error_kind"]`."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, field_validator

from .. import report_reconcile as rc
from ..enhancement_utils import _run_agent_with_model
from ..report_review import checked_clauses_in_context, remove_negative_clause
from . import verifier
from .items import Edit, ReviewInput, ReviewItem, Span, item_key, text_hash

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
CLS = {"assumed_normal": "info", "uncertain": "minor", "number": "minor", "conflict": "action", "removed": "action"}

_NEG = re.compile(r"\b(no|not|nil|without|normal(ly)?|unremarkable|patent|intact|clear|preserved|maintained|"
                  r"within normal limits|non-?dilated|undilated|no evidence)\b", re.I)
_RECOMMENDATION = re.compile(r"\b(recommend\w*|advis\w*|suggest\w*|referr\w*|refer|follow-?up|"
                             r"for (?:surgical|further|treatment)|correlat\w*)\b", re.I)
_NUM = re.compile(r"(?<![A-Za-z/\d.])\d+(?:\.\d+)?")  # skips T1, C7, L4/5; keeps 4cm
_NUMBER_UNIT = re.compile(r"(?<![A-Za-z/\d.])(\d+(?:\.\d+)?)(\s*(?:mm|cm|ml|mL|%|HU|degrees?))?")


def prompt() -> str:
    return PROMPT_PATH.read_text().strip()


# ── candidates and code checks ───────────────────────────────────────────────

def is_normal_or_negative(clause: str) -> bool:
    return bool(_NEG.search(clause))


def candidates(report: str) -> List[dict]:
    """Every normal/negative clause the check reads (FINDINGS + IMPRESSION), with the sentence before it.
    Recommendation sentences are never candidates ("CT spine without contrast" is not a negative)."""
    return [{"clause": c, "before": b} for c, b in checked_clauses_in_context(report, None).items()
            if is_normal_or_negative(c) and not _RECOMMENDATION.search(c)]


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
            out[i] = {"cls": cls, "pointer": parts[2] if len(parts) > 2 and parts[2] != "-" else "",
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

def route(inp: ReviewInput, run_id: str, cands: List[dict], labels: Dict[int, dict]) -> Tuple[List[ReviewItem], str]:
    """Labelled candidates → items, plus the report after pre-applied removals. Pure code."""
    names = list(inp.artifacts.sections or [])
    dictation, history = inp.artifacts.dictated_findings or "", inp.clinical_history or ""
    doc = inp.artifacts.report
    removed: List[dict] = []
    gone_idx = set()
    for i, c in enumerate(cands, 1):
        cls = (labels.get(i) or {}).get("cls")
        reason = ("contradicted" if cls == "contradicted"
                  else "number" if c["number"] and cls != "dictated" else None)
        if not reason:
            continue
        edit = removal_edit(doc, c["clause"])
        if edit is None or verifier.preapply_failures(doc, edit, "removed", dictation, code_built=True,
                                                      sections=names):
            continue                                  # not removable by code: a check item below
        new = verifier.apply_edit(doc, edit, names)
        if new is None:
            continue
        p, delta = _diff(doc, new)[0], len(doc) - len(new)
        for r in removed:                             # earlier anchors after p shift left
            if r["anchor"] > p:
                r["anchor"] = max(p, r["anchor"] - delta)
        removed.append({"i": i, "reason": reason, "anchor": p, "edit": edit})
        gone_idx.add(i)
        doc = new
    h = text_hash(doc)
    items: Dict[int, ReviewItem] = {}

    def item(c: dict, kind: str, status: str, cls_key: str, anchor: Optional[Span], evidence: dict,
             label: str, edit: Optional[Edit] = None) -> ReviewItem:
        sec = verifier._section_of(doc, anchor.start, names) if anchor else None
        return ReviewItem(key=item_key(LANE, ORIGINAL_KIND, c["clause"]), report_id=inp.report_id, run_id=run_id,
                          lane=LANE, detectors=[DETECTOR], kind=kind, cls=CLS[cls_key],
                          section=sec.upper() if sec else None, anchor=anchor, label=label, edit=edit,
                          evidence=evidence, status=status,
                          verified={"code": True, "preapply_failures": []} if status == "pre_applied" else None)

    for r in removed:
        i = r["i"]
        c, lab = cands[i - 1], labels.get(i) or {}
        pointer = lab.get("pointer", "") if r["reason"] == "contradicted" else \
            undictated_numbers(c["clause"], dictation, history)
        items[i] = item(c, "removed", "pre_applied", "removed", Span(start=r["anchor"], end=r["anchor"], text="",
                                                                       text_hash=h),
                        {"removal_reason": r["reason"], "pointer": pointer, "removed_text": r["edit"].find,
                         "clause": c["clause"], "label": lab.get("cls") or "default"},
                        "Removed: contradicts your dictation" if r["reason"] == "contradicted"
                        else "Removed: number not in your dictation", r["edit"])
    taken: List[Tuple[int, int]] = []
    for i, c in enumerate(cands, 1):
        lab = labels.get(i) or {}
        cls = lab.get("cls") or "default"
        if i in gone_idx or (cls == "dictated" and not c["number"]):
            continue
        span = _locate(doc, c["clause"], taken)
        if span:
            taken.append(span)
        anchor = Span(start=span[0], end=span[1], text=doc[span[0]:span[1]], text_hash=h) if span else None
        base = {"clause": c["clause"], "label": cls}
        if cls == "contradicted":
            items[i] = item(c, "check", "open", "conflict", anchor,
                            {**base, "check_reason": "conflict", "pointer": lab.get("pointer", "")},
                            "Check: conflicts with your dictation")
        elif c["number"]:
            items[i] = item(c, "check", "open", "number", anchor,
                            {**base, "check_reason": "number",
                             "pointer": undictated_numbers(c["clause"], dictation, history)},
                            "Check: number not in your dictation")
        elif cls == "implicated":
            items[i] = item(c, "check", "open", "uncertain", anchor,
                            {**base, "check_reason": "uncertain", "pointer": lab.get("pointer", "")},
                            "Check: a dictated finding points here")
        else:
            items[i] = item(c, "assumed_normal", "open", "assumed_normal", anchor, base, "Assumed normal")
    return [items[i] for i in sorted(items)], doc


async def classify_negatives(inp: ReviewInput, run_id: str) -> Tuple[List[ReviewItem], dict]:
    """The Task 14 entry point: (items, log). Never raises. `log` holds the report after pre-applied removals,
    its hash, candidate/label counts, latency and any model error (fail-soft)."""
    t0 = time.monotonic()
    report = inp.artifacts.report or ""
    dictation, history = inp.artifacts.dictated_findings or "", inp.clinical_history or ""
    cands = [{**c, "number": code_number_flag(c["clause"], dictation, history)} for c in candidates(report)]
    log: dict = {"detector": DETECTOR, "candidates": len(cands), "labelled": 0, "error": None, "error_kind": None,
                 "report": report, "text_hash": text_hash(report), "ms": 0}
    if not cands:
        return [], log
    labels, err, kind = await classify(inp, cands)
    try:
        items, doc = route(inp, run_id, cands, labels)
    except Exception as e:  # noqa: BLE001 - routing never fails the run: no items, report untouched
        logger.warning("review engine: negatives routing failed (%s: %s)", type(e).__name__, str(e)[:200])
        items, doc = [], report
        err, kind = err or f"{type(e).__name__}: {str(e)[:200]}", kind or "routing"
    log.update(labelled=len(labels), error=err, error_kind=kind, report=doc, text_hash=text_hash(doc),
               labels={str(k): v for k, v in labels.items()}, ms=int((time.monotonic() - t0) * 1000))
    return items, log


__all__ = ["Labels", "candidates", "code_number_flag", "undictated_numbers", "parse_labels", "user_message",
           "classify", "removal_edit", "route", "classify_negatives"]
