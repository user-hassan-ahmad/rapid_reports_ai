#!/usr/bin/env python3
"""
Audit and fix template_content / style_templates drift for FINDINGS sections.

Usage:
  # 1. Audit first (read-only)
  PYTHONPATH=src python scripts/audit_and_fix_template_drift.py --audit

  # 2. Standard direction (template_content authoritative)
  PYTHONPATH=src python scripts/audit_and_fix_template_drift.py --fix --ids CTCA_ID CTPA_ID TRAUMA_ID

  # 3. Reverse direction (style_templates authoritative — for style_len > template_len cases)
  PYTHONPATH=src python scripts/audit_and_fix_template_drift.py --fix-reverse --ids ANKLE_ID KNEE_ID SHOULDER_ID

  # 4. Verify
  PYTHONPATH=src python scripts/audit_and_fix_template_drift.py --audit
  # Expected: drift_count=0

  # Production (Railway): railway link (select Postgres), then same commands with railway run.

  # Suggested run sequence for production (6 drifted templates):
  #   1. Final audit — capture baseline, confirm review_note on ankle/knee/shoulder
  #   2. Standard direction: --fix --ids <CTCA_ID> <CTPA_ID> <TRAUMA_ID>
  #   3. Reverse direction: --fix-reverse --ids <ANKLE_ID> <KNEE_ID> <SHOULDER_ID>
  #   4. Verification audit: --audit (expected drift_count=0)
  #   5. Manual editor check + trivial save on each MSK template
  #   6. Final audit post-save (confirms save normalisation persists correctly)

  # Verification step after MSK reverse fix: open each template in editor, confirm full content
  # (e.g. bone marrow signal, labrum, bicipital groove, neurovascular in shoulder), make trivial
  # edit and save to exercise save normalisation.
"""
import argparse
import json
import logging
import os
import sys
import uuid

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy.orm.attributes import flag_modified

from rapid_reports_ai.database.connection import SessionLocal
from rapid_reports_ai.database.models import Template

logger = logging.getLogger(__name__)


def _normalize_section(section: dict) -> bool:
    """Normalize style_templates[content_style] = template_content. Returns True if changed."""
    if not isinstance(section, dict):
        return False
    if section.get("generation_mode") != "template_based":
        return False
    content_style = section.get("content_style")
    if not content_style:
        return False
    template_content = section.get("template_content", "")
    style_templates = section.get("style_templates")
    if style_templates is None:
        style_templates = {}
    if not isinstance(style_templates, dict):
        style_templates = {}
    style_body = style_templates.get(content_style, "")
    if style_body == template_content:
        return False
    style_templates = dict(style_templates)
    style_templates[content_style] = template_content
    section["style_templates"] = style_templates
    return True


def audit(db) -> list:
    """Return list of drifted or inconsistent templates."""
    drifted = []
    templates = db.query(Template).filter(Template.is_active == True).all()
    for t in templates:
        config = t.template_config or {}
        sections = config.get("sections") or []
        for section in sections:
            if not isinstance(section, dict):
                continue
            if section.get("generation_mode") != "template_based":
                continue
            content_style = section.get("content_style") or "normal_template"
            template_content = section.get("template_content") or ""
            style_templates = section.get("style_templates") or {}
            style_body = style_templates.get(content_style, "") if isinstance(style_templates, dict) else ""
            template_len = len(template_content)
            style_len = len(style_body)

            # Case 1: Both non-empty but differ — classic drift
            if style_body and template_content != style_body:
                entry = {
                    "template_id": str(t.id),
                    "template_name": t.name,
                    "section_name": section.get("name", "FINDINGS"),
                    "content_style": content_style,
                    "template_len": template_len,
                    "style_len": style_len,
                }
                if style_len > template_len * 1.2:
                    entry["review_note"] = (
                        "style_len > template_len by >20% — consider --fix-reverse; style may be authoritative"
                    )
                drifted.append(entry)

            # Case 2: template_content non-empty but style_templates entry missing
            elif template_content and not style_body:
                drifted.append(
                    {
                        "template_id": str(t.id),
                        "template_name": t.name,
                        "section_name": section.get("name", "FINDINGS"),
                        "content_style": content_style,
                        "template_len": template_len,
                        "style_len": 0,
                        "issue": "style_templates entry missing entirely",
                    }
                )
    return drifted


def _parse_template_ids(ids: list) -> list:
    """Parse template IDs to UUIDs. Returns empty list on invalid input."""
    if not ids:
        return []
    result = []
    for i in ids:
        try:
            result.append(uuid.UUID(i))
        except ValueError:
            logger.warning("Invalid template ID '%s', skipping", i)
    return result


def _verify_persistence(template_ids_updated: list) -> bool:
    """
    Re-query one updated template from DB to verify changes were persisted.
    SQLAlchemy does not detect in-place JSON mutations without flag_modified;
    this catches the silent failure where commit() succeeds but nothing is written.
    """
    if not template_ids_updated:
        return True
    verify_db = SessionLocal()
    try:
        tid = template_ids_updated[0]
        t = verify_db.query(Template).filter(Template.id == tid, Template.is_active == True).first()
        if not t:
            logger.warning("Could not re-query template %s for verification", tid)
            return True  # Don't fail on missing template
        config = t.template_config or {}
        for section in config.get("sections") or []:
            if not isinstance(section, dict) or section.get("generation_mode") != "template_based":
                continue
            content_style = section.get("content_style") or "normal_template"
            tc = section.get("template_content", "")
            st = section.get("style_templates") or {}
            sb = st.get(content_style, "") if isinstance(st, dict) else ""
            if tc != sb:
                logger.error(
                    "Persistence verification failed: template %s section %s still has template_content != style_templates[%s]",
                    tid,
                    section.get("name"),
                    content_style,
                )
                return False
        return True
    finally:
        verify_db.close()


def fix(db, template_ids: list = None) -> int:
    """Normalize drifted templates (template_content -> style_templates). Returns count updated."""
    query = db.query(Template).filter(Template.is_active == True)
    if template_ids:
        parsed = _parse_template_ids(template_ids)
        if parsed:
            query = query.filter(Template.id.in_(parsed))
    templates = query.all()
    updated_ids = []
    for t in templates:
        config = t.template_config or {}
        sections = config.get("sections") or []
        changed = False
        for section in sections:
            if _normalize_section(section):
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


def fix_reverse(db, template_ids: list = None) -> int:
    """
    For cases where style_templates[content_style] is authoritative.
    Copies style body into template_content, then syncs style_templates to match.
    """
    query = db.query(Template).filter(Template.is_active == True)
    if template_ids:
        parsed = _parse_template_ids(template_ids)
        if parsed:
            query = query.filter(Template.id.in_(parsed))
    templates = query.all()
    updated_ids = []
    for t in templates:
        config = t.template_config or {}
        sections = config.get("sections") or []
        changed = False
        for section in sections:
            if not isinstance(section, dict):
                continue
            if section.get("generation_mode") != "template_based":
                continue
            content_style = section.get("content_style") or "normal_template"
            style_templates = section.get("style_templates") or {}
            if not isinstance(style_templates, dict):
                style_templates = {}
            style_body = style_templates.get(content_style, "")
            if not style_body:
                logger.warning(
                    "No style body found for %s/%s — skipping",
                    str(t.id),
                    section.get("name", "FINDINGS"),
                )
                continue
            if section.get("template_content") != style_body:
                section["template_content"] = style_body
                style_templates = dict(style_templates)
                style_templates[content_style] = style_body
                section["style_templates"] = style_templates
                changed = True
                logger.info(
                    "Reverse fix applied: %s/%s — template_content updated from style_templates[%s] (%d chars)",
                    str(t.id),
                    section.get("name", "FINDINGS"),
                    content_style,
                    len(style_body),
                )
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
    parser = argparse.ArgumentParser(description="Audit and fix template drift")
    parser.add_argument("--audit", action="store_true", help="Run audit only (read-only)")
    parser.add_argument("--fix", action="store_true", help="Fix drifted templates (template_content -> style_templates)")
    parser.add_argument(
        "--fix-reverse",
        action="store_true",
        help="Fix reverse (style_templates -> template_content; for style_len > template_len cases)",
    )
    parser.add_argument("--ids", nargs="*", default=[], help="Template UUIDs to target (optional; when omitted, all drifted)")
    args = parser.parse_args()

    if not args.audit and not args.fix and not args.fix_reverse:
        parser.print_help()
        sys.exit(1)

    db = SessionLocal()
    try:
        drifted = audit(db)
        print(f"drift_count={len(drifted)}")
        for d in drifted:
            print(json.dumps(d, ensure_ascii=True))

        if args.fix:
            if not drifted:
                print("No drift to fix.")
                return
            review_flagged = [d for d in drifted if d.get("review_note")]
            if review_flagged:
                print(f"WARNING: {len(review_flagged)} template(s) have style_len > template_len by >20%. Review before proceeding.")
                for d in review_flagged:
                    print(f"  - {d['template_name']} ({d['content_style']})")
            updated = fix(db, args.ids if args.ids else None)
            print(f"Updated {updated} template(s).")
            drifted_after = audit(db)
            print(f"drift_count after fix={len(drifted_after)}")
            if drifted_after:
                print("WARNING: Drift still present after fix.")
                sys.exit(1)
            print("Verification passed: drift_count=0")

        elif args.fix_reverse:
            if not args.ids:
                print("ERROR: --fix-reverse requires --ids for safety (to avoid overwriting standard-direction templates)")
                sys.exit(1)
            updated = fix_reverse(db, args.ids)
            print(f"Updated {updated} template(s).")
            drifted_after = audit(db)
            print(f"drift_count after fix-reverse={len(drifted_after)}")
            if drifted_after:
                print("WARNING: Drift still present after fix-reverse.")
                sys.exit(1)
            print("Verification passed: drift_count=0")
    finally:
        db.close()


if __name__ == "__main__":
    main()
