"""Review endpoints (spec §10.3), owner-scoped like the existing report endpoints (`get_current_user` +
`get_report(db, id, user_id=…)`). GET and item events work in any mode (the /dev/review-rail page reads shadow runs);
probe, reprepare and rerun need the engine on. No endpoint here writes the report: they read and annotate review
items only.

Correction 13: the events route takes user commands only (engine statuses → 422); reprepare never LLM-rewrites a
negatives item or an accuracy item on a negative (L-47); the GET hides `assumed_normal` rows unless
`?include=normals` (editor decorations use them).

Gate G: engine pre-applied items are never re-judged by the probe or reprepare and never hidden by the GET."""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..database.crud import get_report
from ..database.models import User
from . import adjudicator, brief_normals, engine, negatives, provenance, store, verifier
from .items import ReviewItem, text_hash
from .limits import Detail, ItemIds, ReportText, TextHash

router = APIRouter(prefix="/api/reports", tags=["review"])
NOT_FOUND = {"success": False, "error": "Report not found"}
OFF = {"success": False, "error": "review engine off"}
# Correction 13: what a client may send. pre_applied / addressed / stale / prepared are the engine's and the loop's.
USER_COMMANDS = frozenset({"apply", "edit", "undo", "dismiss", "restore", "view", "ask_chat"})
NORMAL_KIND = "assumed_normal"


class EventBody(BaseModel):
    """Bounded (F2 M2, `limits`): detail ≤ 20 keys and ≤ 4 KB serialised, text_hash ≤ 64 characters."""
    command: str = Field(max_length=32)
    text_hash: Optional[TextHash] = None
    detail: Detail = Field(default_factory=dict)


class ProbeBody(BaseModel):
    text: ReportText
    text_hash: TextHash
    changed_ranges: List[List[int]] = Field(default_factory=list, max_length=1000)


class ReprepareBody(BaseModel):
    item_ids: ItemIds
    text: ReportText
    text_hash: TextHash


class RerunBody(BaseModel):
    text: Optional[ReportText] = None


WORKSPACE_MAX_BYTES = 16_384    # the serialised state; the field limits below already keep it well under this


class WorkspaceBody(BaseModel):
    """The rail's per-report workspace (spec §10.2, plan Task E1). Strict: unknown keys are rejected."""
    model_config = ConfigDict(extra="forbid")
    tab: str = Field(pattern=r"^[a-z_]{1,32}$")
    expanded_ids: List[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = \
        Field(default_factory=list, max_length=200)
    density: Literal["full", "quiet", "hidden"] = "quiet"
    last_text_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{16}$")


def _owned(db: Session, report_id: str, user: User):
    return get_report(db, report_id, user_id=str(user.id))


def _input(report, text: str):
    cand = (report.candidate_reports or [None])[0] or {}
    return engine.input_from_parts(str(report.id), report.report_type, report.input_data, {**cand, "content": text},
                                   report.enhancement_json)


def _negative(it: ReviewItem) -> bool:
    """L-47: never LLM-repair a flagged negative: the classifier's items, the brief's linked normals and accuracy
    items on a negative."""
    return bool({negatives.DETECTOR, brief_normals.DETECTOR} & set(it.detectors or [])) or \
        (it.lane == "accuracy" and bool((it.evidence or {}).get("negative")))


def _provenance(it: ReviewItem) -> bool:
    """Provenance marks (ai_generated / recommendation) are never probed or reprepared: they are not judgements."""
    return it.kind in provenance.PROVENANCE_KINDS


def _engine_pre_applied(it: ReviewItem) -> bool:
    """Gate G decision: an item the engine or the post-gen check pre-applied (a non-user `pre_applied` event, or a
    post_check.* detector) is the record of an automatic edit. The probe and reprepare never re-judge it and the GET
    never hides it, whatever the user has since done with it (undo, restore, Discard)."""
    return any(str(d).startswith("post_check.") for d in (it.detectors or [])) or \
        any(isinstance(h, dict) and h.get("event") == "pre_applied" and h.get("actor") != "user"
            for h in (it.history or []))


def _norm_clause(s: Optional[str]) -> str:
    return " ".join((s or "").lower().split()).rstrip(" .;,")


def _claimed_texts(items: List[ReviewItem]) -> List[str]:
    """Clauses an item already speaks for: a removal or contradiction item (pre_applied, open or stale, or dismissed:
    the radiologist kept the clause, F2 M4) and any live item the user restored. The probe adds no second
    "contradicted" card for them (Gate G note E). Restore and the probe are posted together, so the removal may
    still read pre_applied here: its kind alone claims the clause."""
    out = []
    for it in items:
        removal = it.kind in verifier.REMOVAL_KINDS
        if it.status not in ("open", "pre_applied", "stale") and not (
                (removal or (it.edit and it.edit.mode == "remove")) and it.status == "dismissed"):
            continue
        restored = any(isinstance(h, dict) and h.get("event") in ("restore", "undo") for h in it.history or [])
        # a non-applied removal card (open, stale or dismissed) still speaks for its clause: Apply then Undo
        # re-opens it, and the undo probe must not add a second card for the re-inserted text
        removal_edit = bool(it.edit and it.edit.mode == "remove")
        if not removal and not restored and not removal_edit:
            continue
        ev = it.evidence or {}
        for t in (ev.get("removed_text"), ev.get("clause"), it.anchor.text if it.anchor else None,
                  it.edit.find if it.edit else None):
            if _norm_clause(t):
                out.append(_norm_clause(t))
    return out


def _text_back(it: ReviewItem, text: str) -> bool:
    """The item's anchored or find text is in `text` (again): the loop's fix for it may have been undone."""
    return any(t and t in text for t in ((it.anchor.text if it.anchor else None), (it.edit.find if it.edit else None)))


def _covered(clause: str, texts: List[str]) -> bool:
    c = _norm_clause(clause)
    def near(a: str, b: str) -> bool:             # one inside the other and most of it: never a bare word
        short, long_ = sorted((a, b), key=len)
        return short in long_ and len(short) >= 0.6 * len(long_)
    return bool(c) and any(near(c, t) for t in texts)


@router.get("/{report_id}/review")
def get_review(report_id: str, include: Optional[str] = None, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not _owned(db, report_id, current_user):
        return NOT_FOUND
    run = store.latest_run(db, report_id)
    items = store.list_items(db, report_id, run["id"], include_suppressed=True) if run else []
    items = [i for i in items if i.cls != "suppress" or _engine_pre_applied(i)]
    if include != "normals":
        items = [i for i in items if i.kind != NORMAL_KIND]
    return {"success": True, "mode": engine.mode(), "rail": engine.rail_enabled(), "run": run,
            "running": store.run_in_progress(db, report_id), "lanes": (run or {}).get("lanes") or {}, "items": [i.model_dump() for i in items]}


@router.post("/{report_id}/review/items/{item_id}/events")
def post_event(report_id: str, item_id: str, body: EventBody, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not _owned(db, report_id, current_user):
        return NOT_FOUND
    if body.command not in USER_COMMANDS:
        return JSONResponse(status_code=422,
                            content={"success": False, "error": f"command not allowed: {body.command}"})
    try:
        item = store.append_event(db, report_id, item_id, body.command, body.text_hash, body.detail, actor="user")
    except ValueError as e:
        return JSONResponse(status_code=422, content={"success": False, "error": str(e)})
    return {"success": True, "item": item.model_dump()} if item else {"success": False, "error": "Item not found"}


@router.post("/{report_id}/review/probe")
async def post_probe(report_id: str, body: ProbeBody, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if engine.mode() == "off":
        return OFF
    report = _owned(db, report_id, current_user)
    if not report:
        return NOT_FOUND
    inp = _input(report, body.text)
    if inp is None:
        return {"success": False, "error": "no candidate"}
    all_items = store.list_items(db, report_id)
    open_items = [i for i in all_items if i.status == "open" and not _engine_pre_applied(i) and not _provenance(i)]
    back = [i for i in all_items if i.status == "addressed" and not _engine_pre_applied(i) and not _provenance(i)
            and _text_back(i, body.text)]
    res = await verifier.probe(inp, open_items + back, body.text, body.changed_ranges)
    back_ids = {i.id for i in back}
    scores = res.get("scores") or {}
    # an addressed item whose text is back (the fix was undone) re-opens only on an answered, failing probe
    reopened = [i.id for i in back if scores.get(i.id) is not None and scores[i.id] < verifier.ADDRESSED_OK]
    addressed = [x for x in res["addressed"] if x not in back_ids]
    reprepare = [x for x in res["reprepare"] if x not in back_ids or x in reopened]
    claimed = _claimed_texts(all_items)
    if body.text_hash != text_hash(body.text):      # record only for the text that was judged
        addressed, reopened = [], []
    for iid in addressed:
        store.append_event(db, report_id, iid, "addressed", body.text_hash, actor="loop")
    for iid in reopened:
        store.append_event(db, report_id, iid, "reopened", body.text_hash, actor="loop")
    run = store.latest_run(db, report_id)
    new_items: List[ReviewItem] = []
    for c in (res["contradictions"] if run else []):
        if _covered((c.evidence or {}).get("clause") or (c.anchor.text if c.anchor else ""), claimed):
            continue
        it = engine.build_item(inp, run["id"], adjudicator.Outcome(group=[c]))
        it.cls = "action" if c.code_fix else "minor"
        new_items.append(it)
    if new_items:
        store.save_items(db, new_items)
    return {"success": True, "text_hash": body.text_hash, "addressed": addressed, "reopened": reopened,
            "reprepare": reprepare, "new_items": [i.model_dump() for i in new_items],
            "error": res.get("error")}


@router.post("/{report_id}/review/reprepare")
async def post_reprepare(report_id: str, body: ReprepareBody, current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    if engine.mode() == "off":
        return OFF
    report = _owned(db, report_id, current_user)
    if not report:
        return NOT_FOUND
    inp = _input(report, body.text)
    if inp is None:
        return {"success": False, "error": "no candidate"}
    items = [i for i in (store.get_item(db, report_id, x) for x in body.item_ids) if i is not None]
    frozen = lambda i: _negative(i) or _engine_pre_applied(i) or _provenance(i)    # noqa: E731
    kept = [i for i in items if frozen(i)]               # returned unchanged (correction 13; Gate G pre-applied)
    todo = [i for i in items if not frozen(i)]
    outcomes = await asyncio.gather(*(adjudicator.reprepare(inp, it, body.text) for it in todo))
    for it, o in zip(todo, outcomes):
        if o.judgement is not None and o.error is None:
            j = o.judgement
            it.cls, it.kind, it.label, it.reason = j.cls, j.kind or it.kind, j.label or it.label, j.reason
            it.edit, it.probe = adjudicator.to_edit(j), j.probe or it.probe
            it.verified = None
    await verifier.verify(inp, [i for i in todo if i.cls != "suppress"], body.text)
    out = []
    for it, o in zip(todo, outcomes):
        store.update_item(db, it)
        out.append(store.append_event(db, report_id, it.id, "prepared", body.text_hash,
                                      {"error": o.error} if o.error else {}, actor="engine"))
    out += kept
    return {"success": True, "text_hash": body.text_hash, "items": [i.model_dump() for i in out if i]}


@router.post("/{report_id}/review/rerun")
async def post_rerun(report_id: str, body: RerunBody, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if engine.mode() == "off":
        return OFF
    if not _owned(db, report_id, current_user):
        return NOT_FOUND
    engine.schedule_review(report_id, body.text)
    return {"success": True, "status": "running"}


@router.get("/{report_id}/workspace")
def get_workspace(report_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = _owned(db, report_id, current_user)
    if not report:
        return NOT_FOUND
    return {"success": True, "workspace": report.workspace_state}


@router.put("/{report_id}/workspace")
def put_workspace(report_id: str, body: WorkspaceBody, current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    report = _owned(db, report_id, current_user)
    if not report:
        return NOT_FOUND
    state = body.model_dump()
    if len(json.dumps(state)) > WORKSPACE_MAX_BYTES:
        return JSONResponse(status_code=413, content={"success": False, "error": "workspace too large"})
    report.workspace_state = state
    db.commit()
    return {"success": True, "workspace": state}


__all__ = ["router", "USER_COMMANDS"]
