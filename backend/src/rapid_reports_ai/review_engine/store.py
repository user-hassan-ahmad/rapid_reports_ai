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


def latest_run(db: Session, report_id: str) -> Optional[dict]:
    run = (db.query(ReportReviewRun).filter(ReportReviewRun.report_id == _u(report_id))
           .order_by(ReportReviewRun.created_at.desc()).first())
    if run is None:
        return None
    return {"id": str(run.id), "mode": run.mode, "engine_version": run.engine_version, "pathway": run.pathway,
            "lanes": run.lanes or {}, "timings_ms": run.timings_ms or {}, "cost": run.cost or {},
            "errors": run.errors or {}, "created_at": run.created_at.isoformat() if run.created_at else None}


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
    if COMMAND_STATUS[command]:
        row.status = COMMAND_STATUS[command]
    db.commit()
    return _model(row)


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
