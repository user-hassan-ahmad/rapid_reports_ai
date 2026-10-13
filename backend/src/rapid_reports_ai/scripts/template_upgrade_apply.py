"""One-off ship step: write the reviewed grammar sheets to existing templates, soft-delete the listed legacy ones.

Dry run by default (prints and returns what would change, writes nothing; it still vets every sheet through
vet_sheet, which makes paid LLM calls); --apply writes, after a backup JSON of every template it will change (and the
examples and chat turns a delete removes) is saved next to the manifest.

    .venv/bin/python -m rapid_reports_ai.scripts.template_upgrade_apply <manifest.json> [--apply]

manifest.json: {"templates": [{"template_id", "old_sheet_hash", "new_sheet"}], "legacy_ids": [...],
"analyser_version"?: str}; a bare list is read as "templates" alone (nothing deleted). analyser_version, when set,
replaces the carried one on every written sheet. Per template entry:
  skipped-missing   no such template
  skipped-inactive  the template was deleted
  skipped-mode      not a guided (skill_sheet_guided) template
  already-written   its stored sheet is already the vetted new sheet (a re-run)
  skipped-stale     its stored sheet no longer hashes to old_sheet_hash (edited since the pull); re-checked at write
  skipped-refused   the one save function (template_sheet_save.vet_sheet, origin "rebuild") refused the new sheet
  skipped-unchanged the new sheet is the stored one
  written           the vetted sheet is stored the way a sheet save does it (see _write)
  error             the write raised (exception type only) or the pre-upgrade snapshot failed; the rest go on
Then each legacy_ids template still active with no generation_mode (and not a template entry) is soft-deleted
(is_active False, the app's Delete); one that no longer is reports skipped-legacy-changed.

Output names template ids only: never sheet text, template names or user identifiers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_save as tsave
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import Template, TemplateChatTurn, TemplateExample

GUIDED = "skill_sheet_guided"
# A rebuild: an automatic writer's sheet replacing a template's existing one. On an automatic write vet_sheet drops a
# new unit that fails the save-time checks (reported) instead of refusing the whole sheet; a chat origin would refuse.
ORIGIN = "rebuild"


def _find(db, template_id: str, lock: bool = False) -> Optional[Template]:
    """The template, active or not (crud.get_template hides deleted ones, which this script reports apart)."""
    try:
        q = db.query(Template).filter(Template.id == uuid.UUID(str(template_id)))
    except ValueError:
        return None
    return (q.with_for_update().populate_existing() if lock else q).first()


def _is_legacy(t: Optional[Template]) -> bool:
    return t is not None and bool(t.is_active) and not (t.template_config or {}).get("generation_mode")


async def _already_written(current: str, new_sheet: str) -> bool:
    """Whether the stored sheet is what this entry writes: the new sheet itself or its vetted form (a re-run)."""
    if tss.sheet_hash(current) == tss.sheet_hash(new_sheet):
        return True
    try:
        out = await tsave.vet_sheet(new_sheet, origin=ORIGIN, previous="")
    except Exception:  # noqa: BLE001 -- a re-run check only; stale is the safe answer
        return False
    return out.status != "refused" and tss.sheet_hash(current) == tss.sheet_hash(out.sheet)


async def _plan_entry(db, entry: dict, analyser_version: Optional[str] = None) -> dict:
    """What to do with one manifest entry: {"template_id", "action", "reason"?, "dropped_units"?, ...}."""
    from rapid_reports_ai.main import _carry_structure

    tid = str(entry.get("template_id", ""))
    t = _find(db, tid)
    if t is None:
        return {"template_id": tid, "action": "skipped-missing"}
    if not t.is_active:
        return {"template_id": tid, "action": "skipped-inactive"}
    cfg = dict(t.template_config or {})
    if cfg.get("generation_mode") != GUIDED:
        return {"template_id": tid, "action": "skipped-mode"}
    current = cfg.get("skill_sheet") or ""
    if tss.sheet_hash(current) != entry.get("old_sheet_hash"):
        written = await _already_written(current, entry.get("new_sheet") or "")
        return {"template_id": tid, "action": "already-written" if written else "skipped-stale"}
    # The same steps as a sheet save (PUT /api/templates: _carry_structure then _vet_config's guided branch): drop
    # the stored structure, carry analyser_version, vet the sheet, store the vetted sheet + coverage_sections.
    new_cfg = _carry_structure({**cfg, "skill_sheet": entry.get("new_sheet") or ""}, cfg)
    if analyser_version:
        new_cfg["analyser_version"] = analyser_version
    if not new_cfg["skill_sheet"]:
        return {"template_id": tid, "action": "skipped-refused", "reason": tsave.LOST_STRUCTURE}
    out = await tsave.vet_sheet(new_cfg["skill_sheet"], origin=ORIGIN, previous=current)
    if out.status == "refused":
        return {"template_id": tid, "action": "skipped-refused", "reason": out.message or "refused"}
    if out.status == "unchanged":
        return {"template_id": tid, "action": "skipped-unchanged"}
    vetted = {**new_cfg, "skill_sheet": out.sheet, "coverage_sections": out.coverage_sections}
    row = {"template_id": tid, "action": "written", "config": vetted, "old_config": cfg,
           "old_sheet_hash": entry.get("old_sheet_hash"), "dropped_units": len(out.dropped)}
    if out.message:   # the repair reworded a unit: reported, never silent
        row["notice"] = out.message
    return row


def _store_structure(db, template_id: str, config: dict) -> bool:
    """main._queue_structure's grammar branch on this session: parse the stored grammar sheet and store its
    structure (usable or not) unless a current grammar structure of it is already stored."""
    sheet = config.get("skill_sheet") or ""
    if config.get("generation_mode") != GUIDED or not tsg.is_grammar_sheet(sheet) or tss.current_grammar(config):
        return False
    return tss.store_structure(db, template_id, tsg.parse_sheet(sheet).structure)


def _locked_check(db, row: dict) -> Optional[Template]:
    """The template row locked FOR UPDATE if it still holds the planned old sheet; else the row's action is updated
    (already-written or skipped-stale), the lock released and None returned."""
    t = _find(db, row["template_id"], lock=True)
    cfg = (t.template_config or {}) if t is not None else {}
    current = tss.sheet_hash(cfg.get("skill_sheet") or "")
    if t is not None and t.is_active and cfg.get("generation_mode") == GUIDED and current == row["old_sheet_hash"]:
        return t
    db.rollback()
    written = t is not None and t.is_active and current == tss.sheet_hash(row["config"]["skill_sheet"])
    row["action"] = "already-written" if written else "skipped-stale"
    return None


def _try_structure(db, row: dict) -> None:
    """Store the structure of the template's current sheet; a failure leaves the written sheet and is reported."""
    try:
        t = _find(db, row["template_id"])
        row["structure_stored"] = _store_structure(db, row["template_id"], dict(t.template_config or {}))
    except Exception as e:  # noqa: BLE001 -- a re-run stores it (already-written rows retry)
        db.rollback()
        row["structure_stored"], row["reason"] = False, type(e).__name__


def _write(db, row: dict) -> None:
    """Re-check the plan under a row lock, snapshot the old state, store the vetted sheet, then its structure."""
    if _locked_check(db, row) is None:
        if row["action"] == "already-written":
            _try_structure(db, row)
        return
    if crud.create_template_version(db, _find(db, row["template_id"]), skip_if_unchanged=True) is None:
        row["action"], row["reason"] = "error", "snapshot failed"  # pre-upgrade state not restorable: no write
        return
    t = _locked_check(db, row)  # the snapshot's commit released the lock
    if t is None:
        if row["action"] == "already-written":
            _try_structure(db, row)
        return
    t.template_config = row["config"]  # as crud.update_template: assign, commit (updated_at), snapshot the new state
    db.commit()
    crud.create_template_version(db, t)
    _try_structure(db, row)


def _soft_delete(db, row: dict) -> None:
    if not _is_legacy(_find(db, row["template_id"], lock=True)):
        db.rollback()
        row["action"] = "skipped-legacy-changed"
    elif not crud.delete_template(db, row["template_id"]):
        row["action"], row["reason"] = "skipped-delete-failed", "delete_template returned False"


def _jsonable(v):
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _rows(db, model, template_id) -> list:
    return [{c.name: _jsonable(getattr(r, c.name)) for c in model.__table__.columns}
            for r in db.query(model).filter(model.template_id == template_id).all()]


def _read_manifest(path: Path) -> tuple:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data, [], None
    legacy_ids = [str(i) for i in data.get("legacy_ids") or []]
    return data.get("templates") or [], legacy_ids, data.get("analyser_version")


async def _run(manifest_path: Path, apply: bool, db) -> dict:
    entries, legacy_ids, analyser_version = _read_manifest(manifest_path)
    rows = [await _plan_entry(db, e, analyser_version) for e in entries]
    listed = {r["template_id"] for r in rows}
    for lid in dict.fromkeys(legacy_ids):
        if lid in listed:
            continue
        t = _find(db, lid)
        rows.append({"template_id": lid, "action": "soft-deleted" if _is_legacy(t) else "skipped-legacy-changed"})

    backup_path = None
    if apply:
        backup = {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "converted": {}, "legacy": {}}
        for r in rows:
            if r["action"] == "written":
                backup["converted"][r["template_id"]] = r["old_config"]
            elif r["action"] == "soft-deleted":
                t = _find(db, r["template_id"])
                backup["legacy"][r["template_id"]] = {
                    "name": t.name, "user_id": str(t.user_id), "template_config": t.template_config,
                    "examples": _rows(db, TemplateExample, t.id), "chat_turns": _rows(db, TemplateChatTurn, t.id)}
        backup_path = manifest_path.with_name(f"template_upgrade_backup_{int(time.time())}.json")
        backup_path.write_text(json.dumps(backup, indent=1, default=str))
        for r in rows:
            if r["action"] not in ("written", "soft-deleted", "already-written"):
                continue
            try:
                {"written": _write, "soft-deleted": _soft_delete, "already-written": _try_structure}[r["action"]](db, r)
            except Exception as e:  # noqa: BLE001 -- one template's failure never stops the rest
                db.rollback()
                r["action"], r["reason"] = "error", type(e).__name__
                r.pop("structure_stored", None)

    out = [{k: v for k, v in r.items() if k in ("template_id", "action", "reason", "dropped_units",
                                                   "notice", "structure_stored")} for r in rows]
    totals: dict = {}
    for r in out:
        totals[r["action"]] = totals.get(r["action"], 0) + 1
    prefix = "" if apply else "would be "
    for r in out:
        extra = ""
        if r.get("reason"):
            extra += f"  reason: {r['reason']}"
        if r.get("dropped_units"):
            extra += f"  dropped units: {r['dropped_units']}"
        if r.get("notice"):
            extra += f"  notice: {r['notice']}"
        if "structure_stored" in r:
            extra += f"  structure stored: {r['structure_stored']}"
        action = prefix + r["action"] if r["action"] in ("written", "soft-deleted") else r["action"]
        print(f"  {action:<24} {r['template_id']}{extra}")
    print("totals:", ", ".join(f"{k} {v}" for k, v in sorted(totals.items())) or "none")
    print(f"backup: {backup_path}" if apply else "dry run: nothing written")
    return {"apply": apply, "templates": out, "totals": totals, "backup": str(backup_path) if backup_path else None}


def main(manifest_path, apply: bool = False, db=None) -> dict:
    """Plan (and with apply=True, perform) the upgrade. Uses its own session from the app's DB config when db is None."""
    own = db is None
    if own:
        from rapid_reports_ai.database.connection import SessionLocal
        db = SessionLocal()
    try:
        return asyncio.run(_run(Path(manifest_path), apply, db))
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("manifest")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    a = ap.parse_args()
    main(a.manifest, apply=a.apply)
