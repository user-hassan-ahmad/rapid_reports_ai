"""Review endpoints (spec §10.3), owner-scoped like the existing report endpoints (`get_current_user` +
`get_report(db, id, user_id=…)`). GET and item events work in any mode (the /dev/review-rail page reads shadow runs);
probe, reprepare and rerun need the engine on. No endpoint here writes the report: they read and annotate review
items only.

Correction 13: the events route takes user commands only (engine statuses → 422); reprepare never LLM-rewrites a
negatives item or an accuracy item on a negative (L-47); the GET hides `assumed_normal` rows unless
`?include=normals` (editor decorations use them)."""
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
from . import adjudicator, engine, negatives, store, verifier
from .items import ReviewItem

router = APIRouter(prefix="/api/reports", tags=["review"])
NOT_FOUND = {"success": False, "error": "Report not found"}
OFF = {"success": False, "error": "review engine off"}
# Correction 13: what a client may send. pre_applied / addressed / stale / prepared are the engine's and the loop's.
USER_COMMANDS = frozenset({"apply", "edit", "undo", "dismiss", "restore", "view", "ask_chat"})
NORMAL_KIND = "assumed_normal"


class EventBody(BaseModel):
    command: str
    text_hash: Optional[str] = None
    detail: dict = Field(default_factory=dict)


class ProbeBody(BaseModel):
    text: str
    text_hash: str
    changed_ranges: List[List[int]] = Field(default_factory=list)


class ReprepareBody(BaseModel):
    item_ids: List[str]
    text: str
    text_hash: str


class RerunBody(BaseModel):
    text: Optional[str] = None


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
    """L-47: never LLM-repair a flagged negative: the classifier's items and accuracy items on a negative."""
    return negatives.DETECTOR in (it.detectors or []) or \
        (it.lane == "accuracy" and bool((it.evidence or {}).get("negative")))


@router.get("/{report_id}/review")
def get_review(report_id: str, include: Optional[str] = None, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not _owned(db, report_id, current_user):
        return NOT_FOUND
    run = store.latest_run(db, report_id)
    items = store.list_items(db, report_id, run["id"]) if run else []
    if include != "normals":
        items = [i for i in items if i.kind != NORMAL_KIND]
    return {"success": True, "mode": engine.mode(), "rail": engine.rail_enabled(), "run": run,
            "lanes": (run or {}).get("lanes") or {}, "items": [i.model_dump() for i in items]}


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
    open_items = [i for i in store.list_items(db, report_id) if i.status == "open"]
    res = await verifier.probe(inp, open_items, body.text, body.changed_ranges)
    for iid in res["addressed"]:
        store.append_event(db, report_id, iid, "addressed", body.text_hash, actor="loop")
    run = store.latest_run(db, report_id)
    new_items: List[ReviewItem] = []
    for c in (res["contradictions"] if run else []):
        it = engine.build_item(inp, run["id"], adjudicator.Outcome(group=[c]))
        it.cls = "action" if c.code_fix else "minor"
        new_items.append(it)
    if new_items:
        store.save_items(db, new_items)
    return {"success": True, "text_hash": body.text_hash, "addressed": res["addressed"],
            "reprepare": res["reprepare"], "new_items": [i.model_dump() for i in new_items],
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
    kept = [i for i in items if _negative(i)]            # returned unchanged (correction 13)
    todo = [i for i in items if not _negative(i)]
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
