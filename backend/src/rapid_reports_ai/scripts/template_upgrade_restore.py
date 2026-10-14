"""The way back from template_upgrade_apply (integration spec D17): from its backup JSON, put each converted
template's old config back and undo each legacy soft-delete, re-inserting the examples and chat turns the delete
removed. Dry run by default; --apply writes. The current state of a converted template is snapshotted as a
TemplateVersion before it is replaced (versions are capped at 10; the oldest goes). Re-runs are no-ops.

    .venv/bin/python -m rapid_reports_ai.scripts.template_upgrade_restore <template_upgrade_backup_*.json> [--apply]

Output names template ids only: never sheet text, template names or user identifiers.
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime

from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import Template, TemplateChatTurn, TemplateExample


def _find(db, template_id: str):
    try:
        return db.get(Template, uuid.UUID(template_id))
    except ValueError:
        return None


def _row(model, data: dict):
    """A backup row (JSON-safe) back into a model instance: UUID and DateTime columns parsed."""
    kw = {}
    for c in model.__table__.columns:
        if c.name not in data:
            continue
        v = data[c.name]
        if v is not None and isinstance(c.type, DateTime):
            v = datetime.fromisoformat(v)
        elif v is not None and c.name in ("id", "template_id", "user_id") and isinstance(v, str):
            v = uuid.UUID(v)
        kw[c.name] = v
    return model(**kw)


def _restore(db, tid: str, old_config: dict, apply: bool) -> dict:
    t = _find(db, tid)
    if t is None:
        return {"template_id": tid, "action": "skipped-missing"}
    if t.template_config == old_config:
        return {"template_id": tid, "action": "already-restored"}
    if not apply:
        return {"template_id": tid, "action": "would restore"}
    crud.create_template_version(db, t, skip_if_unchanged=True)   # the converted state stays recoverable
    t = _find(db, tid)
    t.template_config = old_config
    db.commit()
    crud.create_template_version(db, t)
    return {"template_id": tid, "action": "restored"}


def _reactivate(db, tid: str, saved: dict, apply: bool) -> dict:
    t = _find(db, tid)
    if t is None:
        return {"template_id": tid, "action": "skipped-missing"}
    if t.is_active:
        return {"template_id": tid, "action": "already-active"}
    if not apply:
        return {"template_id": tid, "action": "would reactivate"}
    t.is_active = True
    n = 0
    for model, key in ((TemplateExample, "examples"), (TemplateChatTurn, "chat_turns")):
        for data in saved.get(key) or []:
            if db.get(model, uuid.UUID(str(data["id"]))) is None:
                db.add(_row(model, data))
                n += 1
    db.commit()
    return {"template_id": tid, "action": "reactivated", "rows_restored": n}


def run(backup_path: Path, apply: bool, db) -> dict:
    data = json.loads(Path(backup_path).read_text())
    rows = []
    for tid, old in (data.get("converted") or {}).items():
        try:
            rows.append(_restore(db, tid, old, apply))
        except Exception as e:  # noqa: BLE001 -- one template's failure never stops the rest
            db.rollback()
            rows.append({"template_id": tid, "action": "error", "reason": type(e).__name__})
    for tid, saved in (data.get("legacy") or {}).items():
        try:
            rows.append(_reactivate(db, tid, saved, apply))
        except Exception as e:  # noqa: BLE001
            db.rollback()
            rows.append({"template_id": tid, "action": "error", "reason": type(e).__name__})
    totals: dict = {}
    for r in rows:
        totals[r["action"]] = totals.get(r["action"], 0) + 1
        print(f"{r['template_id']}  {r['action']}" + (f"  reason: {r['reason']}" if r.get("reason") else ""))
    print("totals:", totals)
    return {"templates": rows, "totals": totals}


def main(backup_path, apply: bool = False, db=None) -> dict:
    own = db is None
    if own:
        from rapid_reports_ai.database.connection import SessionLocal
        db = SessionLocal()
    try:
        return run(Path(backup_path), apply, db)
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("backup")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    a = ap.parse_args()
    main(a.backup, apply=a.apply)
