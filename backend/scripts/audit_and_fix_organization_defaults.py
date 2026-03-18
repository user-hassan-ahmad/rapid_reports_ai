#!/usr/bin/env python3
"""
Audit and fix organization defaults for template_based FINDINGS sections.

Targets normal_template sections where follow_template_style is True and
organization is clinical_priority — updates to template_order so template
structure is honoured by default.

Usage:
  # 1. Audit first (read-only)
  PYTHONPATH=src python scripts/audit_and_fix_organization_defaults.py --audit

  # 2. Apply fix
  PYTHONPATH=src python scripts/audit_and_fix_organization_defaults.py --fix

  # Production (Railway): use DATABASE_URL with public URL for local runs.
"""
import argparse
import json
import logging
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy.orm.attributes import flag_modified

from rapid_reports_ai.database.connection import SessionLocal
from rapid_reports_ai.database.models import Template

logger = logging.getLogger(__name__)


def _section_matches(section: dict) -> bool:
    """True if section should be updated (normal_template, follow_template_style, organization=clinical_priority)."""
    if not isinstance(section, dict):
        return False
    if section.get("generation_mode") != "template_based":
        return False
    content_style = section.get("content_style") or "normal_template"
    if content_style != "normal_template":
        return False
    advanced = section.get("advanced") or {}
    if not isinstance(advanced, dict):
        return False
    follow = advanced.get("follow_template_style", True)
    if follow is not True:
        return False
    org = advanced.get("organization", "clinical_priority")
    return org == "clinical_priority"


def audit(db) -> list:
    """Return list of templates with FINDINGS sections to update."""
    to_update = []
    templates = db.query(Template).filter(Template.is_active == True).all()
    for t in templates:
        config = t.template_config or {}
        sections = config.get("sections") or []
        for section in sections:
            if not _section_matches(section):
                continue
            to_update.append({
                "template_id": str(t.id),
                "template_name": t.name,
                "content_style": section.get("content_style") or "normal_template",
                "section_name": section.get("name", "FINDINGS"),
                "previous": "clinical_priority",
                "updated_to": "template_order",
            })
    return to_update


def _verify_persistence(template_ids_updated: list) -> bool:
    """
    Re-query the database after commit to verify changes were persisted.
    Uses a fresh SessionLocal() — not the in-memory object.
    """
    if not template_ids_updated:
        return True
    verify_db = SessionLocal()
    try:
        from uuid import UUID
        for tid_str in template_ids_updated[:3]:  # Check up to 3
            try:
                tid = UUID(tid_str)
            except ValueError:
                continue
            t = verify_db.query(Template).filter(Template.id == tid, Template.is_active == True).first()
            if not t:
                continue
            config = t.template_config or {}
            for section in config.get("sections") or []:
                if not isinstance(section, dict) or section.get("generation_mode") != "template_based":
                    continue
                content_style = section.get("content_style") or "normal_template"
                if content_style != "normal_template":
                    continue
                advanced = section.get("advanced") or {}
                org = advanced.get("organization", "clinical_priority")
                if org != "template_order":
                    logger.error(
                        "Persistence verification failed: template %s section %s still has organization=%s",
                        tid_str,
                        section.get("name"),
                        org,
                    )
                    return False
        return True
    finally:
        verify_db.close()


def fix(db) -> int:
    """Update organization to template_order for matching sections. Returns count updated."""
    templates = db.query(Template).filter(Template.is_active == True).all()
    updated_ids = []
    for t in templates:
        config = t.template_config or {}
        sections = config.get("sections") or []
        changed = False
        for section in sections:
            if not _section_matches(section):
                continue
            section.setdefault("advanced", {})["organization"] = "template_order"
            changed = True
        if changed:
            flag_modified(t, "template_config")
            db.add(t)
            updated_ids.append(str(t.id))
    if updated_ids:
        db.commit()
        if not _verify_persistence(updated_ids):
            print("ERROR: Post-commit verification failed — changes may not have been persisted (check flag_modified)")
            sys.exit(1)
    return len(updated_ids)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Audit and fix organization defaults for normal_template sections")
    parser.add_argument("--audit", action="store_true", help="Run audit only (read-only)")
    parser.add_argument("--fix", action="store_true", help="Apply fix: set organization to template_order")
    args = parser.parse_args()

    if not args.audit and not args.fix:
        parser.print_help()
        sys.exit(1)

    db = SessionLocal()
    try:
        to_update = audit(db)
        print(f"count={len(to_update)}")
        for entry in to_update:
            print(json.dumps(entry, ensure_ascii=True))

        if args.fix:
            updated = fix(db)
            print(f"Updated {updated} template(s).")
            to_update_after = audit(db)
            if to_update_after:
                print("WARNING: Some sections still match after fix.")
                sys.exit(1)
            print("Verification passed: count=0")
    finally:
        db.close()


if __name__ == "__main__":
    main()
