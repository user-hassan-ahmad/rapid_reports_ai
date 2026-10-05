"""Persistence for review runs and items (spec §10.2). Sync functions that take a Session; the engine calls them in
a worker thread with a session of its own, the endpoints with the request's session."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..database.models import ReportReviewItem, ReportReviewRun
from .items import ReviewItem

# command → new status (None: history only). Spec §12.3 commands plus the engine's and the loop's own events.
COMMAND_STATUS = {
    "apply": "applied", "edit": "applied", "undo": "open", "dismiss": "dismissed", "restore": "open",
    "addressed": "addressed", "stale": "stale", "pre_applied": "pre_applied",
    "prepared": None, "view": None, "ask_chat": None,
}
_ITEM_FIELDS = ("key", "lane", "detectors", "kind", "cls", "section", "label", "reason", "probe", "citation",
                "source_line", "evidence", "status", "history", "engine_version")


def _u(x) -> uuid.UUID:
    return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_run(db: Session, report_id: str, mode: str, engine_version: str, pathway: str) -> str:
    run = ReportReviewRun(report_id=_u(report_id), mode=mode, engine_version=engine_version, pathway=pathway,
                          lanes={}, timings_ms={}, cost={}, errors={})
    db.add(run)
    db.commit()
    return str(run.id)


def finish_run(db: Session, run_id: str, lanes: dict, timings_ms: dict, cost: dict, errors: dict,
               shadow_log: Optional[dict] = None) -> None:
    run = db.get(ReportReviewRun, _u(run_id))
    if run is None:
        return
    run.lanes, run.timings_ms, run.cost, run.errors, run.shadow_log = lanes, timings_ms, cost, errors, shadow_log
    db.commit()


def _row(item: ReviewItem) -> ReportReviewItem:
    d = item.model_dump()
    return ReportReviewItem(id=_u(item.id), report_id=_u(item.report_id), run_id=_u(item.run_id),
                            anchor=d["anchor"], edit=d["edit"], verified=d["verified"],
                            **{k: d[k] for k in _ITEM_FIELDS})


def _model(row: ReportReviewItem) -> ReviewItem:
    return ReviewItem(id=str(row.id), report_id=str(row.report_id), run_id=str(row.run_id), anchor=row.anchor,
                      edit=row.edit, verified=row.verified, detectors=row.detectors or [], history=row.history or [],
                      label=row.label or "", reason=row.reason or "", engine_version=row.engine_version or "",
                      **{k: getattr(row, k) for k in ("key", "lane", "kind", "cls", "section", "probe", "citation",
                                                       "source_line", "evidence", "status")})


def save_items(db: Session, items: List[ReviewItem]) -> None:
    db.add_all([_row(i) for i in items])
    db.commit()


def _finished(run: ReportReviewRun) -> bool:
    """`finish_run` always writes lane states, or an error on an engine failure; `create_run` leaves both empty."""
    return bool(run.lanes) or bool(run.errors)


def latest_run(db: Session, report_id: str, scan: int = 20) -> Optional[dict]:
    """The newest FINISHED run (a still-running newer run must not hide the last complete one), else the newest."""
    runs = (db.query(ReportReviewRun).filter(ReportReviewRun.report_id == _u(report_id))
            .order_by(ReportReviewRun.created_at.desc()).limit(scan).all())
    if not runs:
        return None
    run = next((r for r in runs if _finished(r)), runs[0])
    return {"id": str(run.id), "mode": run.mode, "engine_version": run.engine_version, "pathway": run.pathway,
            "lanes": run.lanes or {}, "timings_ms": run.timings_ms or {}, "cost": run.cost or {},
            "errors": run.errors or {}, "created_at": run.created_at.isoformat() if run.created_at else None}


def record_finalise(db: Session, report_id: str, applied_item_ids: List[str]) -> Optional[str]:
    """Store the review items the radiologist kept at finalise (applied, plus pre-applied not undone) on the latest
    run, under `shadow_log["finalise"] = {"review_applied_item_ids": [...], "at": iso}` (a keyed run log; no
    migration). Other shadow_log keys are kept. Returns the run id, or None when the report has no run."""
    run = latest_run(db, report_id)
    if run is None:
        return None
    row = db.get(ReportReviewRun, _u(run["id"]))
    row.shadow_log = {**(row.shadow_log or {}),
                      "finalise": {"review_applied_item_ids": list(applied_item_ids), "at": _now().isoformat()}}
    flag_modified(row, "shadow_log")
    db.commit()
    return run["id"]


def list_items(db: Session, report_id: str, run_id: Optional[str] = None,
               include_suppressed: bool = False) -> List[ReviewItem]:
    if run_id is None:
        run = latest_run(db, report_id)
        if run is None:
            return []
        run_id = run["id"]
    q = db.query(ReportReviewItem).filter(ReportReviewItem.report_id == _u(report_id),
                                          ReportReviewItem.run_id == _u(run_id))
    if not include_suppressed:
        q = q.filter(ReportReviewItem.cls != "suppress")
    return [_model(r) for r in q.order_by(ReportReviewItem.created_at, ReportReviewItem.key).all()]


def get_item(db: Session, report_id: str, item_id: str) -> Optional[ReviewItem]:
    row = db.get(ReportReviewItem, _u(item_id))
    return _model(row) if row is not None and row.report_id == _u(report_id) else None


def append_event(db: Session, report_id: str, item_id: str, command: str, text_hash: Optional[str] = None,
                 detail: Optional[dict] = None, actor: str = "user") -> Optional[ReviewItem]:
    if command not in COMMAND_STATUS:
        raise ValueError(f"unknown review command: {command}")
    row = db.get(ReportReviewItem, _u(item_id))
    if row is None or row.report_id != _u(report_id):
        return None
    row.history = list(row.history or []) + [{"at": _now().isoformat(), "event": command, "actor": actor,
                                              "text_hash": text_hash, "detail": detail or {}}]
    flag_modified(row, "history")
    status = COMMAND_STATUS[command]
    if _reinstates_pre_apply(command, detail, row.history):
        status = "pre_applied"
    if status:
        row.status = status
    db.commit()
    return _model(row)


def _reinstates_pre_apply(command: str, detail: Optional[dict], history: Optional[list]) -> bool:
    """Discard (Plan 3 fix batch): after the user undid or restored a pre-applied item, Discard puts the saved text
    back, which holds the engine's write. The client posts `apply` with {via: discard, reinstate: pre_applied}; the
    item goes back to `pre_applied` only when the engine itself pre-applied it (a non-user `pre_applied` event), so a
    client can never mint an engine status (correction 13). Otherwise it is a plain apply."""
    d = detail or {}
    if command != "apply" or d.get("via") != "discard" or d.get("reinstate") != "pre_applied":
        return False
    return any(isinstance(h, dict) and h.get("event") == "pre_applied" and h.get("actor") != "user"
               for h in (history or []))


def update_item(db: Session, item: ReviewItem) -> None:
    """Overwrite an item's judged fields after re-prepare or verification."""
    row = db.get(ReportReviewItem, _u(item.id))
    if row is None:
        return
    d = item.model_dump()
    for k in ("cls", "kind", "label", "reason", "probe", "status", "section"):
        setattr(row, k, d[k])
    row.edit, row.verified, row.anchor, row.evidence = d["edit"], d["verified"], d["anchor"], d["evidence"]
    row.history = d["history"]
    for k in ("edit", "verified", "anchor", "evidence", "history"):
        flag_modified(row, k)
    db.commit()
