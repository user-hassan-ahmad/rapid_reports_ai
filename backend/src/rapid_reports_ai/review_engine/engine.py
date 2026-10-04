"""Review engine orchestration (spec §4, §9, §10.4).

align → code checks → [shared Jev pass → lanes (concurrent, each isolated)] ‖ negatives classifier → merge →
adjudicate → items → verify → sequenced pre-apply → store.

Flags: RR_REVIEW_ENGINE=off (default) | shadow | live; RR_REVIEW_LANES an optional subset of the lanes;
RR_REVIEW_CONCURRENCY (default 1) caps concurrent runs process-wide so shadow never competes with generation for
model quota; RR_REVIEW_SAMPLE (0–1, default 1.0) is the share of saved reports reviewed. No per-user gating.
`live` behaves as `shadow` (warned once) until a live report write exists. In shadow the engine runs in a background
task after the candidate is saved; it writes rows only and NOTHING is applied to the user-visible report: the
pre-apply sequence is computed and recorded in the run's shadow log (Gate D) and in `ReviewResult.report`, never
written back.

One text (I5): every persisted anchor is on the ORIGINAL report (the text the user sees; `text_hash` = its hash).
The would-be final report, the negatives' post-removal report and the negatives' post-removal anchor positions are
kept in the shadow log only, so offsets can be reconstructed for the Gate D / F reads.

Shadow persistence (I6): no item is persisted `pre_applied` while the user-visible report lacks its edit. An item the
sequence would pre-apply is stored `open` (its one-click edit applies to the report the user sees) with
`evidence["would_pre_apply"] = True` and its history event renamed `would_pre_apply`; the shadow log's `pre_apply`
entries (by item id) carry the sequenced detail. `ReviewResult` itself keeps `pre_applied` (what live would do).

Duplicates (I2): a negative clause flagged both by the negatives classifier and by the accuracy lane
(`evidence.negative`) is owned by the negatives classifier when it succeeded: lane items whose original-report span
overlaps a negatives item's span are dropped (listed in `run["deduped"]`). When the classifier failed, the lane path
is the fallback.

Pre-apply (binding corrections 9, 10, 12; spec §9). An item is `pre_applied` only when ALL hold:
- it is pre-apply eligible: a code-built removal from the accuracy lane (`Candidate.pre_apply` + `code_fix`), or a
  coverage `absent` line whose insert the engine builds itself with `verifier.insert_from_line` from the WHOLE
  dictated line (the adjudicator's own text is never pre-applied); the adjudicator agreed (`action`, no error) and,
  for an insert, kept the kind `absent`;
- `verifier.preapply_failures(...) == []` on the original report;
- the verifier passed it (`code` True, not `unconfirmed`);
- it still applies cleanly in sequence: negatives' removals go first (already sequential, `log["report"]`), then the
  lane edits in item order, each re-checked with `preapply_failures` against the text it is actually applied to.
  One that no longer applies falls back to an open one-click item.
Negatives items (Task 14) bypass merge and the adjudicator and are appended as built."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from ..report_review import is_negative
from . import adjudicator, jev_pass, negatives, store, verifier
from .alignment import Alignment, align
from .checks import run_checks
from .items import Candidate, Edit, ReviewInput, ReviewItem, Span, item_key, merge, text_hash
from .lanes import LaneContext, registry

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"
LANE_TIMEOUT_S = 20.0
GATE_D_TIMEOUT_S = 120.0
NEGATIVES_TIMEOUT_S = negatives.TIMEOUT_S + 10.0   # the classifier has its own model timeout; this bounds the rest
OPTIONS_WAIT_S = 90.0          # templated: wait for the background options job before reviewing
LANES = {lane.name: lane for lane in registry()}
_DEFAULT_LANES = "coverage,accuracy,additions"


# ── flags ───────────────────────────────────────────────────────────────────

_LIVE_WARNED = False


def mode() -> str:
    """off | shadow. `live` is accepted but behaves as `shadow` until a live report write exists (I6): nothing may be
    persisted as pre-applied while the user-visible report does not contain the edit."""
    global _LIVE_WARNED
    v = os.environ.get("RR_REVIEW_ENGINE", "off").strip().lower()
    if v == "live":
        if not _LIVE_WARNED:
            _LIVE_WARNED = True
            logger.warning("review engine: RR_REVIEW_ENGINE=live behaves as shadow (no live report write yet)")
        return "shadow"
    return v if v == "shadow" else "off"


def concurrency() -> int:
    try:
        return max(1, int(os.environ.get("RR_REVIEW_CONCURRENCY") or 1))
    except ValueError:
        return 1


def sample_rate() -> float:
    try:
        return min(1.0, max(0.0, float(os.environ.get("RR_REVIEW_SAMPLE") or 1.0)))
    except ValueError:
        return 1.0


def lanes_enabled() -> List[str]:
    raw = os.environ.get("RR_REVIEW_LANES") or _DEFAULT_LANES
    out: List[str] = []
    for x in (p.strip().lower() for p in raw.split(",")):
        if x in LANES and x not in out:
            out.append(x)
    return out


def rail_enabled() -> bool:
    return mode() == "live" and os.environ.get("RR_REVIEW_RAIL", "1").strip() != "0"


class ReviewResult(BaseModel):
    run: dict
    items: List[ReviewItem]
    report: str                 # the report after the pre-apply sequence (shadow: recorded only, never shown)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── items ───────────────────────────────────────────────────────────────────

def _default_label(c: Candidate) -> str:
    if c.evidence.get("sentence"):
        return c.evidence["sentence"][:80]
    text = c.line_text or (c.anchor.text if c.anchor else "")
    return f"{c.kind.replace('_', ' ')}: {text}"[:80]


def _key(first: Candidate, anchor: Optional[Span], line_text: Optional[str]) -> str:
    """Correction 9: the candidate's ORIGINAL kind; anchor text, else the dictated line, else the evidence (never
    the model-written label)."""
    text = anchor.text if anchor is not None and anchor.text else line_text
    if not text:
        text = json.dumps(first.evidence or {}, sort_keys=True, default=str)
    return item_key(first.lane, first.kind, text)


def build_item(inp: ReviewInput, run_id: str, o: adjudicator.Outcome) -> ReviewItem:
    """One adjudicated group → one item (status `open`; `finalise` decides `pre_applied` after verification)."""
    g = o.group
    first = g[0]
    h = text_hash(inp.artifacts.report)
    anchor = next((c.anchor for c in g if c.anchor), None)
    if anchor is not None:
        anchor = anchor.model_copy(update={"text_hash": h})
    line_text = next((c.line_text for c in g if c.line_text and c.lane == "coverage"), None) or \
        next((c.line_text for c in g if c.line_text), None)
    code_fix = next((c for c in g if c.code_fix and c.proposed), None)
    probe = next((c.probe for c in g if c.probe), None)
    if o.error is not None:              # validation / transport failure or overflow (spec §7): minor, no fix
        cls, kind, label, edit = "minor", first.kind, _default_label(first), None
        reason = f"Not reviewed automatically ({o.error[:120]})."
    elif o.judgement is not None:
        j = o.judgement
        cls, kind, label, reason = j.cls, j.kind or first.kind, j.label or _default_label(first), j.reason
        edit = code_fix.proposed if code_fix else adjudicator.to_edit(j)
        probe = j.probe or probe
    else:                                # pre-classed brief option, not judged again
        cls, kind, label, edit = first.preclassed or "minor", first.kind, _default_label(first), first.proposed
        reason = first.evidence.get("reason") or ""
    section = next((c.section for c in g if c.section), None)
    evidence: Dict = {}
    for c in g:
        evidence.update({k: v for k, v in (c.evidence or {}).items() if k not in evidence})
    detectors = sorted({c.detector for c in g})
    return ReviewItem(key=_key(first, anchor, line_text), report_id=inp.report_id, run_id=run_id, lane=first.lane,
                      detectors=detectors, kind=kind, cls=cls, section=section, anchor=anchor,
                      label=label, reason=reason, edit=edit, evidence=evidence or None, probe=probe,
                      citation=next((c.citation for c in g if c.citation), None), source_line=line_text,
                      status="open",
                      history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h,
                                "detail": {"detectors": detectors}}],
                      engine_version=ENGINE_VERSION)


# ── pre-apply planning and sequencing ────────────────────────────────────────

class _Plan(BaseModel):
    item_id: str
    kind: str                          # the kind passed to preapply_failures (the eligible candidate's own kind)
    code_built: bool
    line_text: Optional[str] = None    # the WHOLE dictated line (coverage lane), never model-written text
    line_context: Optional[dict] = None


def _findings_name(sections: List[str]) -> str:
    return next((s for s in sections or [] if s.strip().rstrip(":").strip().lower() == "findings"), "FINDINGS")


def _line_context(al: Optional[Alignment], c: Candidate) -> Optional[dict]:
    if al is None:
        return None
    line = None
    if c.line_id:
        line = next((l for l in al.lines if l.id == c.line_id and l.text == c.line_text), None)
    if line is None:
        line = next((l for l in al.lines if l.text == c.line_text), None)
    return {"block_side": line.block_side, "block_levels": list(line.block_levels)} if line is not None else None


def preapply_failures(report: str, edit: Optional[Edit], plan: _Plan, inp: ReviewInput) -> List[str]:
    """verifier.preapply_failures with the plan's facts."""
    return verifier.preapply_failures(report, edit, plan.kind, inp.artifacts.dictated_findings or "",
                                      code_built=plan.code_built, line_text=plan.line_text,
                                      sections=list(inp.artifacts.sections or []), line_context=plan.line_context)


def plan_preapply(inp: ReviewInput, o: adjudicator.Outcome, item: ReviewItem,
                  al: Optional[Alignment] = None) -> Optional[_Plan]:
    """Correction 12: is this item pre-apply eligible on the original report? For a coverage `absent` line the
    engine swaps the item's edit for code's insert of the dictated line (only when it qualifies). Never for an
    adjudicator failure, a non-`action` judgement or a pre-classed option."""
    j = o.judgement
    if o.error is not None or j is None or j.cls != "action":
        return None
    report = inp.artifacts.report
    removal = next((c for c in o.group if c.pre_apply and c.code_fix and c.proposed), None)
    if removal is not None:
        plan = _Plan(item_id=item.id, kind=removal.kind, code_built=True)
        return plan if item.edit is not None and not preapply_failures(report, item.edit, plan, inp) else None
    absent = next((c for c in o.group if c.lane == "coverage" and c.kind == "absent" and c.line_text), None)
    if absent is None or j.kind != "absent":
        return None
    names = list(inp.artifacts.sections or [])
    edit = verifier.insert_from_line(report, absent.line_text, _findings_name(names), names)
    plan = _Plan(item_id=item.id, kind="absent", code_built=True, line_text=absent.line_text,
                 line_context=_line_context(al, absent))
    if edit is None or preapply_failures(report, edit, plan, inp):
        return None
    item.edit = edit
    item.section = item.section or edit.section
    return plan


def overtaken(it: ReviewItem, doc: str, fails: List[str]) -> None:
    """A lane edit an earlier pre-applied edit overtook. A removal: its text is already gone → `stale`, no edit. Any
    other edit (an insert anchored on removed text): the finding still needs the radiologist, so the item stays
    open, but its edit no longer applies to the sequenced report and is dropped (never a one-click action)."""
    if it.edit is not None and it.edit.mode == "remove":
        it.status = "stale"
    it.edit = None
    it.history.append({"at": _now(), "event": "stale" if it.status == "stale" else "overtaken", "actor": "engine",
                       "text_hash": text_hash(doc), "detail": {"failed": fails}})


def finalise(inp: ReviewInput, items: List[ReviewItem], plans: Dict[str, _Plan], neg_log: Optional[dict],
             neg_items: List[ReviewItem]) -> Tuple[str, List[dict]]:
    """Sequence the pre-applied edits (negatives' removals first, then lane edits in item order), re-checking each
    lane edit against the text it would actually be applied to. Returns (final text, pre-apply log). A lane edit an
    earlier edit has overtaken (`no_longer_applies` / `anchor_not_unique` on the sequenced text, though it passed
    on the original) loses its edit, never an open one-click action (`overtaken`)."""
    names = list(inp.artifacts.sections or [])
    doc = (neg_log or {}).get("report") or inp.artifacts.report
    log: List[dict] = []
    for it in neg_items:
        if it.status == "pre_applied":
            log.append({"source": "negatives", "item_id": it.id, "kind": it.kind, "applied": True, "failed": [],
                        "edit": it.edit.model_dump() if it.edit else None,
                        "removed_text": (it.evidence or {}).get("removed_text")})
    for it in items:
        plan = plans.get(it.id)
        if plan is None:
            continue
        v = it.verified or {}
        entry = {"source": "lanes", "item_id": it.id, "lane": it.lane, "kind": plan.kind,
                 "edit": it.edit.model_dump() if it.edit else None, "applied": False, "failed": []}
        if it.edit is None or not v.get("code") or v.get("unconfirmed"):
            entry["failed"] = ["verifier"] + list(v.get("failed") or []) + (["unconfirmed"] if v.get("unconfirmed")
                                                                            else [])
            log.append(entry)
            continue
        fails = preapply_failures(doc, it.edit, plan, inp)
        new = verifier.apply_edit(doc, it.edit, names) if not fails else None
        if not fails and new is None:
            fails = ["no_longer_applies"]
        v["preapply_failures"] = fails
        it.verified = v
        if fails:
            entry["failed"] = fails
            if doc != inp.artifacts.report and {"no_longer_applies", "anchor_not_unique"} & set(fails):
                overtaken(it, doc, fails)
                entry["stale" if it.status == "stale" else "overtaken"] = True
        else:
            it.status = "pre_applied"
            it.history.append({"at": _now(), "event": "pre_applied", "actor": "engine", "text_hash": text_hash(doc),
                               "detail": {"kind": plan.kind}})
            entry.update(applied=True, before_hash=text_hash(doc), after_hash=text_hash(new))
            doc = new
        log.append(entry)
    return doc, log


# ── run ─────────────────────────────────────────────────────────────────────

async def _negatives(inp: ReviewInput, run_id: str) -> Tuple[List[ReviewItem], Optional[dict], Optional[str]]:
    try:
        items, log = await asyncio.wait_for(negatives.classify_negatives(inp, run_id), NEGATIVES_TIMEOUT_S)
        return items, log, None
    except Exception as e:  # noqa: BLE001 - negatives never fail the run (timeouts included)
        logger.warning("review engine: negatives failed (%s)", type(e).__name__)
        return [], None, f"{type(e).__name__}: {str(e)[:200]}"


def _neg_summary(log: Optional[dict]) -> Optional[dict]:
    return {k: v for k, v in log.items() if k not in ("report", "post_removal_anchors")} if log else None


def _overlaps(a: Span, spans: List[Tuple[int, int]]) -> bool:
    return any(a.start < e and s < a.end for s, e in spans)


def _dedupe(items: List[ReviewItem], group_of: Dict[str, List[Candidate]], neg_items: List[ReviewItem]
            ) -> Tuple[List[ReviewItem], List[ReviewItem]]:
    """(kept, dropped): lane items on a negative (`evidence.negative`) whose original-report span overlaps a
    negatives item's span. Both anchors are on the original report."""
    spans = [(n.anchor.start, n.anchor.end) for n in neg_items
             if n.anchor is not None and n.anchor.end > n.anchor.start]
    kept, dropped = [], []
    for it in items:
        g = group_of.get(it.id) or []
        a = it.anchor or next((c.anchor for c in g if c.anchor), None)
        dup = a is not None and any((c.evidence or {}).get("negative") for c in g) and _overlaps(a, spans)
        (dropped if dup else kept).append(it)
    return kept, dropped


async def run_review(inp: ReviewInput, run_id: str) -> ReviewResult:
    t0 = time.monotonic()
    timings: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    a = inp.artifacts
    names = lanes_enabled()
    neg_task = asyncio.create_task(_negatives(inp, run_id)) if "accuracy" in names else None
    try:
        al = align(a.report, a.dictated_findings, inp.clinical_history, a.sections)
        checks = run_checks(a.report, a.dictated_findings, inp.clinical_history, inp.scan_type, al, inp.study_title)
        jp = None
        if {"coverage", "accuracy"} & set(names):
            t = time.monotonic()
            try:
                jp = await jev_pass.run(inp, a.report)
            except Exception as e:  # noqa: BLE001 - lanes then run on code checks only
                errors["jev"] = f"{type(e).__name__}: {str(e)[:200]}"
            timings["jev_ms"] = int((time.monotonic() - t) * 1000)
            for k in ("contra_error", "omit_error", "support_error"):
                if jp is not None and getattr(jp, k, None):
                    errors[f"jev_{k}"] = getattr(jp, k)
        ctx = LaneContext(alignment=al, jev=jp, checks=checks)

        async def one(name: str):
            return await asyncio.wait_for(LANES[name].candidates(inp, ctx), LANE_TIMEOUT_S)
        t = time.monotonic()
        results = await asyncio.gather(*(one(n) for n in names), return_exceptions=True)
        timings["lanes_ms"] = int((time.monotonic() - t) * 1000)
        lanes = {n: "skipped" for n in LANES}
        cands: List[Candidate] = []
        for n, r in zip(names, results):
            if isinstance(r, BaseException):
                lanes[n] = "failed"
                errors[n] = f"{type(r).__name__}: {str(r)[:200]}"
                logger.warning("review engine: lane %s failed (%s)", n, type(r).__name__)
            else:
                lanes[n] = "done"
                cands += r
        t = time.monotonic()
        groups = merge(cands)
        outcomes = await adjudicator.adjudicate(inp, groups)
        timings["adjudicator_ms"] = int((time.monotonic() - t) * 1000)
        items: List[ReviewItem] = []
        plans: Dict[str, _Plan] = {}
        group_of: Dict[str, List[Candidate]] = {}
        for o in outcomes:
            it = build_item(inp, run_id, o)
            p = plan_preapply(inp, o, it, al)
            if p is not None:
                plans[it.id] = p
            group_of[it.id] = o.group
            items.append(it)
        t = time.monotonic()
        await verifier.verify(inp, [i for i in items if i.cls != "suppress"], groups=group_of)
        timings["verifier_ms"] = int((time.monotonic() - t) * 1000)
    except BaseException:
        if neg_task is not None:
            neg_task.cancel()
        raise
    neg_items: List[ReviewItem] = []
    neg_log = None
    if neg_task is not None:
        t = time.monotonic()
        neg_items, neg_log, neg_err = await neg_task
        timings["negatives_wait_ms"] = int((time.monotonic() - t) * 1000)
        if neg_err or (neg_log or {}).get("error"):
            errors["negatives"] = neg_err or neg_log["error"]
        for it in neg_items:
            it.engine_version = ENGINE_VERSION
    deduped: List[dict] = []
    if neg_task is not None and "negatives" not in errors:      # the classifier owns negatives; else lane fallback
        items, dropped = _dedupe(items, group_of, neg_items)
        for it in dropped:
            plans.pop(it.id, None)
            deduped.append({"key": it.key, "kind": it.kind, "anchor": it.anchor.model_dump() if it.anchor else None})
    report, pre_log = finalise(inp, items, plans, neg_log, neg_items)
    items += neg_items                   # correction 10: never merged or adjudicated
    timings["total"] = int((time.monotonic() - t0) * 1000)
    errors.update({f"adjudicator_{k}": o.error for k, o in enumerate(outcomes) if o.error})
    run = {"lanes": lanes, "timings_ms": timings, "errors": errors,
           "cost": {"groups": len(outcomes), "adjudicated": sum(1 for o in outcomes if o.judgement or o.error),
                    "candidates": len(cands), "negatives_calls": 1 if neg_log and neg_log.get("candidates") else 0},
           "pre_apply": pre_log, "negatives": _neg_summary(neg_log), "deduped": deduped,
           "negatives_report": (neg_log or {}).get("report"),
           "negatives_post_removal_anchors": (neg_log or {}).get("post_removal_anchors") or {}}
    return ReviewResult(run=run, items=items, report=report)


async def gate_d_log(inp: ReviewInput) -> Optional[dict]:
    """What options A and B (spec §9) would have done with today's automatic edits, judged on the pre-edit report.
    Option A is the engine's own pre-apply rule (code-built edit, adjudicator `action`, preapply_failures == [],
    verified and confirmed); option B is the one-click item the radiologist would see."""
    qc = inp.artifacts.quality_check or {}
    pre = inp.pre_edit_report
    if not pre:
        return None
    a = inp.artifacts
    names = list(a.sections or [])
    kept = {k.get("text") for k in qc.get("kept_dictated_negative") or []}
    pre_inp = inp.model_copy(update={"artifacts": a.model_copy(update={"report": pre})})
    try:
        al = align(pre, a.dictated_findings, inp.clinical_history, names)
    except Exception:  # noqa: BLE001 - only the line context is lost
        al = None
    entries = []
    for f in qc.get("flags") or []:
        text = f.get("text") or ""
        if f.get("kind") == "omission":
            cand = Candidate(lane="coverage", kind="absent", line_text=text, detector="jev.classify_first")
            etype = "insertion"
        elif f.get("kind") == "contradiction" and is_negative(text) and text not in kept:
            i = pre.find(text)
            anchor = Span(start=i, end=i + len(text), text=text) if i >= 0 else None
            fix = verifier._negative_fix(pre, i, i + len(text), text, names) if i >= 0 else None
            cand = Candidate(lane="accuracy", kind="contradicted", anchor=anchor,
                             evidence={"negative": True, "clause": text}, proposed=fix, code_fix=fix is not None,
                             pre_apply=fix is not None, detector="jev.contradiction")
            etype = "removal"
        else:
            continue
        o = await adjudicator.judge(pre_inp, [cand])
        item = build_item(pre_inp, "gate-d", o)
        plan = plan_preapply(pre_inp, o, item, al)
        if item.cls != "suppress":
            await verifier.verify(pre_inp, [item], groups={item.id: [cand]})
        v = item.verified or {}
        fails = preapply_failures(pre, item.edit, plan, pre_inp) if plan and item.edit else ["not_eligible"]
        ok = bool(plan and item.edit is not None and v.get("code") and not v.get("unconfirmed") and not fails)
        entries.append({"type": etype, "text": text, "cls": item.cls, "kind": item.kind,
                        "edit_mode": item.edit.mode if item.edit else None, "verified": item.verified,
                        "code_edit": item.edit.model_dump() if plan and item.edit else None,
                        "preapply_failures": fails, "option_a_pre_apply": ok,
                        "option_b": "one-click action" if item.cls == "action" else item.cls})
    return {"edits": entries}


# ── loading and scheduling ──────────────────────────────────────────────────

def input_from_parts(report_id: str, report_type: str, input_data: Optional[dict], cand: Optional[dict],
                     enhancement_json: Optional[dict]) -> Optional[ReviewInput]:
    from ..generation_artifacts import GenerationArtifacts
    cand = cand or {}
    if cand.get("error") or not cand.get("content"):
        return None
    data = input_data or {}
    v = data.get("variables") or {}
    findings = v.get("FINDINGS") or ""
    guidelines = (enhancement_json or {}).get("guidelines")
    return ReviewInput(report_id=report_id, pathway="templated" if report_type == "templated" else "quick",
                       artifacts=GenerationArtifacts.from_candidate(cand, findings),
                       clinical_history=v.get("CLINICAL_HISTORY") or "",
                       scan_type=v.get("SCAN_TYPE") or data.get("extracted_scan_type") or "",
                       study_title=v.get("SCAN_TYPE") or data.get("extracted_scan_type"),
                       synthesis={"guidelines": guidelines} if guidelines else None,
                       pre_edit_report=(cand.get("quality_check") or {}).get("pre_edit_report"))


def _session():
    from ..database.connection import SessionLocal
    return SessionLocal()


def _with_session(fn, *a, **k):
    db = _session()
    try:
        return fn(db, *a, **k)
    finally:
        db.close()


def _load_row(db, report_id: str):
    import uuid as _uuid

    from ..database.models import Report
    row = db.get(Report, _uuid.UUID(str(report_id)))
    if row is None:
        return None
    cand = (row.candidate_reports or [None])[0] or {}
    return {"report_type": row.report_type, "input_data": row.input_data, "cand": dict(cand),
            "enhancement_json": row.enhancement_json}


async def load_input(report_id: str, text: Optional[str] = None) -> Optional[ReviewInput]:
    deadline = time.monotonic() + OPTIONS_WAIT_S
    while True:
        row = await asyncio.to_thread(_with_session, _load_row, report_id)
        if row is None:
            return None
        if row["cand"].get("options_status") != "pending" or time.monotonic() > deadline:
            break
        await asyncio.sleep(3)
    cand = row["cand"]
    if text is not None:
        cand = {**cand, "content": text}
    return input_from_parts(report_id, row["report_type"], row["input_data"], cand, row["enhancement_json"])


_SEM: Optional[Tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]] = None


def _semaphore() -> asyncio.Semaphore:
    """The process-wide cap on concurrent runs (one per event loop)."""
    global _SEM
    loop = asyncio.get_running_loop()
    if _SEM is None or _SEM[0] is not loop:
        _SEM = (loop, asyncio.Semaphore(concurrency()))
    return _SEM[1]


def shadow_items(items: List[ReviewItem]) -> List[ReviewItem]:
    """I6: what may be persisted while nothing is written to the user-visible report. An item the sequence would
    pre-apply is stored `open` with `evidence["would_pre_apply"]` and its `pre_applied` history event renamed."""
    for it in items:
        if it.status == "pre_applied":
            it.status = "open"
            it.evidence = {**(it.evidence or {}), "would_pre_apply": True}
            it.history = [{**e, "event": "would_pre_apply"} if e.get("event") == "pre_applied" else e
                          for e in it.history]
    return items


async def _gate_d(inp: ReviewInput) -> Optional[dict]:
    try:
        return await asyncio.wait_for(gate_d_log(inp), GATE_D_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - Gate D never costs the run its items
        logger.warning("review engine: gate D log failed (%s)", type(e).__name__)
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


async def run_and_store(report_id: str, text: Optional[str] = None) -> Optional[str]:
    """Run the engine over a saved report and store the run and its items. Never raises, never writes the report
    (in shadow the pre-apply sequence is only recorded in the shadow log). At most `concurrency()` runs at once."""
    try:
        inp = await load_input(report_id, text)
        if inp is None:
            return None
        async with _semaphore():
            return await _run_and_store(inp, report_id)
    except Exception as e:  # noqa: BLE001 - the engine never affects the report path
        logger.warning("review engine failed for %s (%s: %s)", report_id, type(e).__name__, str(e)[:200])
        return None


async def _run_and_store(inp: ReviewInput, report_id: str) -> str:
    m = mode()
    run_id = await asyncio.to_thread(_with_session, store.create_run, report_id, m, ENGINE_VERSION, inp.pathway)
    try:
        res = await run_review(inp, run_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("review engine run failed for %s (%s: %s)", report_id, type(e).__name__, str(e)[:200])
        await asyncio.to_thread(_with_session, store.finish_run, run_id, {}, {}, {},
                                {"engine": f"{type(e).__name__}: {str(e)[:200]}"})
        return run_id
    gate_d = await _gate_d(inp) if m == "shadow" else None
    errors = dict(res.run["errors"])
    if gate_d and gate_d.get("error"):
        errors["gate_d"] = gate_d["error"]
    shadow = {"gate_d": gate_d, "pre_apply": res.run["pre_apply"], "negatives": res.run["negatives"],
              "deduped": res.run["deduped"], "report_hash": text_hash(inp.artifacts.report),
              "pre_applied_hash": text_hash(res.report), "final_report": res.report,
              "negatives_report": res.run["negatives_report"],
              "negatives_post_removal_anchors": res.run["negatives_post_removal_anchors"]}
    await asyncio.to_thread(_with_session, store.save_items, shadow_items(res.items))
    await asyncio.to_thread(_with_session, store.finish_run, run_id, res.run["lanes"], res.run["timings_ms"],
                            res.run["cost"], errors, shadow)
    return run_id


_REVIEW_TASKS: "set[asyncio.Task]" = set()


def schedule_review(report_id: Optional[str], text: Optional[str] = None) -> Optional["asyncio.Task"]:
    """Fire-and-forget review of a saved report (held so it is not garbage-collected mid-flight). No-op when off or
    when the report falls outside the RR_REVIEW_SAMPLE share."""
    if mode() == "off" or not report_id:
        return None
    rate = sample_rate()
    if rate < 1.0 and random.random() >= rate:
        return None
    task = asyncio.create_task(run_and_store(str(report_id), text))
    _REVIEW_TASKS.add(task)
    task.add_done_callback(_REVIEW_TASKS.discard)
    return task


__all__ = ["ENGINE_VERSION", "LANES", "mode", "concurrency", "sample_rate", "lanes_enabled", "rail_enabled",
           "ReviewResult", "build_item", "shadow_items",
           "plan_preapply", "preapply_failures", "finalise", "run_review", "gate_d_log", "input_from_parts",
           "load_input", "run_and_store", "schedule_review"]
