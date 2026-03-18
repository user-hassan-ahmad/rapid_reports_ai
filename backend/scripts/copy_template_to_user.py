#!/usr/bin/env python3
"""
Copy a template from one user to another.

Usage:
  # MRI shoulder
  DATABASE_URL="postgresql://..." poetry run python scripts/copy_template_to_user.py --template-id bef97fab-d4ef-4ff6-b2d4-caecea045427

  # CTCA - basic
  DATABASE_URL="postgresql://..." poetry run python scripts/copy_template_to_user.py --template-id b2fffb37-7f66-4a00-bc5a-512528c0d74d

  # Custom user
  poetry run python scripts/copy_template_to_user.py --template-id <ID> --user-id <USER_UUID>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rapid_reports_ai.database.connection import SessionLocal
from rapid_reports_ai.database.crud import get_template, create_template

DEFAULT_USER_ID = "89cbb7cb-1649-4e86-95e3-cba2b2861455"


def main():
    parser = argparse.ArgumentParser(description="Copy a template to a target user account")
    parser.add_argument("--template-id", required=True, help="Source template UUID")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="Target user UUID")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        source = get_template(db, args.template_id, user_id=None)
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
