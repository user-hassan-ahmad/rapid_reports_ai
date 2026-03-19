#!/usr/bin/env python3
"""
Copy a template from one user to another.

Usage:
  # By template ID
  DATABASE_URL="postgresql://..." poetry run python scripts/copy_template_to_user.py --template-id bef97fab-d4ef-4ff6-b2d4-caecea045427 --user-id 951d8d13-20f7-4c5e-9508-34583a34f4d8

  # By name (from source user)
  poetry run python scripts/copy_template_to_user.py --name "CTCA - basic (structured)" --source-user-id 89cbb7cb-1649-4e86-95e3-cba2b2861455 --user-id 951d8d13-20f7-4c5e-9508-34583a34f4d8
"""
import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rapid_reports_ai.database.connection import SessionLocal
from rapid_reports_ai.database.crud import get_template, create_template
from rapid_reports_ai.database.models import Template

DEFAULT_USER_ID = "89cbb7cb-1649-4e86-95e3-cba2b2861455"


def main():
    parser = argparse.ArgumentParser(description="Copy a template to a target user account")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--template-id", help="Source template UUID")
    g.add_argument("--name", help="Source template name (requires --source-user-id)")
    parser.add_argument("--source-user-id", help="Source user UUID (required when using --name)")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="Target user UUID")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.template_id:
            source = get_template(db, args.template_id, user_id=None)
        else:
            if not args.source_user_id:
                print("--source-user-id required when using --name")
                sys.exit(1)
            try:
                su = uuid.UUID(args.source_user_id)
            except ValueError:
                print("Invalid --source-user-id")
                sys.exit(1)
            source = db.query(Template).filter(
                Template.user_id == su,
                Template.name == args.name,
                Template.is_active == True,
            ).first()
        if not source:
            print("Source template not found")
            sys.exit(1)
        new_template = create_template(
            db=db,
            name=source.name,
            user_id=args.user_id,
            template_config=source.template_config,
            description=source.description,
            tags=source.tags,
            is_pinned=source.is_pinned,
        )
        print(f"Created template '{new_template.name}' (id={new_template.id}) for user {args.user_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
