"""The way back from template_upgrade_apply (integration spec D17): from its backup JSON, put each converted
template's old config back and undo each legacy soft-delete, re-inserting the examples and chat turns the delete
removed. Dry run by default; --apply writes. The current state of a converted template is snapshotted as a
TemplateVersion before it is replaced (versions are capped at 10; the oldest goes); if the snapshot fails, nothing is
written. Re-runs are no-ops.

Only what the upgrade itself did is undone. A converted template is restored only while it still holds the sheet the
upgrade wrote (checked under a row lock); edited since, it reports skipped-edited-since and keeps the edit. A legacy
template is reactivated only if the backup records the upgrade deleting it (skipped-not-deleted otherwise, or
skipped-unconfirmed when the run stopped before recording it). Each template commits on its own: a run that stops
part-way is finished by running it again.

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

from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import Template, TemplateChatTurn, TemplateExample


def _find(db, template_id: str, lock: bool = False):
    try:
        q = db.query(Template).filter(Template.id == uuid.UUID(str(template_id)))
    except ValueError:
        return None
    return (q.with_for_update().populate_existing() if lock else q).first()


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


def _check(db, tid: str, old_config: dict, written_hash, lock: bool = False):
    """(template, None) if it still holds the sheet the upgrade wrote; else (None, the action to report)."""
    t = _find(db, tid, lock)
    if t is None:
        return None, "skipped-missing"
    if t.template_config == old_config:
        return None, "already-restored"
    if written_hash is None:
        return None, "skipped-unconfirmed"
    if tss.sheet_hash((t.template_config or {}).get("skill_sheet") or "") != written_hash:
        return None, "skipped-edited-since"
    return t, None


def _restore(db, tid: str, old_config: dict, written_hash, apply: bool) -> dict:
    t, action = _check(db, tid, old_config, written_hash)
    if t is None or not apply:
        return {"template_id": tid, "action": action or "would restore"}
    if crud.create_template_version(db, t, skip_if_unchanged=True) is None:   # the converted state stays recoverable
        return {"template_id": tid, "action": "error", "reason": "snapshot failed"}
    t, action = _check(db, tid, old_config, written_hash, lock=True)   # re-checked locked: an edit during the snapshot wins
    if t is None:
        db.rollback()
        return {"template_id": tid, "action": action}
    t.template_config = old_config
    db.commit()
    crud.create_template_version(db, t)
    return {"template_id": tid, "action": "restored"}


def _reactivate(db, tid: str, saved: dict, done, apply: bool) -> dict:
    t = _find(db, tid)
    if t is None:
        return {"template_id": tid, "action": "skipped-missing"}
    if t.is_active:
        return {"template_id": tid, "action": "already-active"}
    if done is None:
        return {"template_id": tid, "action": "skipped-unconfirmed"}
    if done != "soft-deleted":   # the upgrade did not delete it (the radiologist did): it stays deleted
        return {"template_id": tid, "action": "skipped-not-deleted"}
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
            rows.append(_restore(db, tid, old, (data.get("written_sheet_hash") or {}).get(tid), apply))
        except Exception as e:  # noqa: BLE001 -- one template's failure never stops the rest
            db.rollback()
            rows.append({"template_id": tid, "action": "error", "reason": type(e).__name__})
    for tid, saved in (data.get("legacy") or {}).items():
        try:
            rows.append(_reactivate(db, tid, saved, (data.get("done") or {}).get(tid), apply))
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
