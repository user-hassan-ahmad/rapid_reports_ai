"""One-off ship step: write the reviewed grammar sheets to existing templates and soft-delete the legacy templates.

Dry run by default (prints and returns what would change, writes nothing); --apply writes, after a backup JSON of
every template it will change is saved next to the manifest.

    .venv/bin/python -m rapid_reports_ai.scripts.template_upgrade_apply <manifest.json> [--apply]

manifest.json: [{"template_id", "old_sheet_hash", "new_sheet"}]. Per manifest entry:
  skipped-missing   no such template
  skipped-inactive  the template was deleted
  skipped-mode      not a guided (skill_sheet_guided) template
  skipped-stale     its stored sheet no longer hashes to old_sheet_hash (edited since the pull)
  skipped-refused   the one save function (template_sheet_save.vet_sheet, origin "rebuild") refused the new sheet
  written           the vetted sheet is stored the way a sheet save does it (see _write)
Then every active template with no generation_mode (legacy) is soft-deleted (is_active False, the app's Delete).

Output names template ids only: never sheet text, template names or user identifiers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_save as tsave
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import Template

GUIDED = "skill_sheet_guided"
# A rebuild: an automatic writer's sheet replacing a template's existing one. On an automatic write vet_sheet drops a
# new unit that fails the save-time checks (reported) instead of refusing the whole sheet; a chat origin would refuse.
ORIGIN = "rebuild"


def _find(db, template_id: str) -> Optional[Template]:
    """The template, active or not (crud.get_template hides deleted ones, which this script reports apart)."""
    try:
        return db.query(Template).filter(Template.id == uuid.UUID(str(template_id))).first()
    except ValueError:
        return None


async def _plan_entry(db, entry: dict) -> dict:
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
    if tss.sheet_hash(cfg.get("skill_sheet") or "") != entry.get("old_sheet_hash"):
        return {"template_id": tid, "action": "skipped-stale"}
    # The same steps as a sheet save (PUT /api/templates: _carry_structure then _vet_config's guided branch): drop
    # the stored structure, carry analyser_version, vet the sheet, store the vetted sheet + coverage_sections.
    new_cfg = _carry_structure({**cfg, "skill_sheet": entry.get("new_sheet") or ""}, cfg)
    if not new_cfg["skill_sheet"]:
        return {"template_id": tid, "action": "skipped-refused", "reason": tsave.LOST_STRUCTURE}
    out = await tsave.vet_sheet(new_cfg["skill_sheet"], origin=ORIGIN, previous=cfg.get("skill_sheet") or "")
    if out.status == "refused":
        return {"template_id": tid, "action": "skipped-refused", "reason": out.message or "refused"}
    if out.status == "unchanged":
        return {"template_id": tid, "action": "skipped-unchanged"}
    vetted = {**new_cfg, "skill_sheet": out.sheet, "coverage_sections": out.coverage_sections}
    return {"template_id": tid, "action": "written", "config": vetted, "template": t, "old_config": cfg,
            "dropped_units": len(out.dropped)}


def _store_structure(db, template_id: str, config: dict) -> bool:
    """main._queue_structure's grammar branch on this session: parse the stored grammar sheet and store its
    structure (usable or not) unless a current grammar structure of it is already stored."""
    sheet = config.get("skill_sheet") or ""
    if config.get("generation_mode") != GUIDED or not tsg.is_grammar_sheet(sheet) or tss.current_grammar(config):
        return False
    return tss.store_structure(db, template_id, tsg.parse_sheet(sheet).structure)


def _write(db, row: dict) -> bool:
    t = row["template"]
    crud.create_template_version(db, t, skip_if_unchanged=True)  # the pre-upgrade state, restorable from history
    updated = crud.update_template(db, str(t.id), template_config=row["config"])  # snapshots the new state too
    return _store_structure(db, str(t.id), dict(updated.template_config or {}))


async def _run(manifest_path: Path, apply: bool, db) -> dict:
    manifest = json.loads(manifest_path.read_text())
    rows = [await _plan_entry(db, e) for e in manifest]
    converting = {r["template_id"] for r in rows if r["action"] == "written"}
    legacy = [t for t in db.query(Template).filter(Template.is_active.is_(True)).all()
              if not (t.template_config or {}).get("generation_mode") and str(t.id) not in converting]
    rows += [{"template_id": str(t.id), "action": "soft-deleted", "template": t} for t in legacy]

    backup_path = None
    if apply:
        backup = {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "converted": {}, "legacy": {}}
        for r in rows:
            if r["action"] == "written":
                backup["converted"][r["template_id"]] = r["old_config"]
            elif r["action"] == "soft-deleted":
                t = r["template"]
                backup["legacy"][r["template_id"]] = {"name": t.name, "user_id": str(t.user_id),
                                                      "template_config": t.template_config}
        backup_path = manifest_path.with_name(f"template_upgrade_backup_{int(time.time())}.json")
        backup_path.write_text(json.dumps(backup, indent=1, default=str))
        for r in rows:
            if r["action"] == "written":
                r["structure_stored"] = _write(db, r)
            elif r["action"] == "soft-deleted":
                if not crud.delete_template(db, r["template_id"]):
                    r["action"], r["reason"] = "skipped-delete-failed", "delete_template returned False"

    out = [{k: v for k, v in r.items() if k in ("template_id", "action", "reason", "dropped_units",
                                                   "structure_stored")} for r in rows]
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
