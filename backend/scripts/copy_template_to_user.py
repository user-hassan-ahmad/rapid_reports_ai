#!/usr/bin/env python3
"""
Copy a template from one user to another.

Usage:
  railway link   # Select Postgres
  railway run PYTHONPATH=src python scripts/copy_template_to_user.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rapid_reports_ai.database.connection import SessionLocal
from rapid_reports_ai.database.crud import get_template, create_template

SOURCE_TEMPLATE_ID = "bef97fab-d4ef-4ff6-b2d4-caecea045427"
TARGET_USER_ID = "89cbb7cb-1649-4e86-95e3-cba2b2861455"

db = SessionLocal()
try:
    source = get_template(db, SOURCE_TEMPLATE_ID, user_id=None)
    if not source:
        print("Source template not found")
        sys.exit(1)
    new_template = create_template(
        db=db,
        name=source.name,
        user_id=TARGET_USER_ID,
        template_config=source.template_config,
        description=source.description,
        tags=source.tags,
        is_pinned=source.is_pinned,
    )
    print(f"Created template '{new_template.name}' (id={new_template.id}) for user {TARGET_USER_ID}")
finally:
    db.close()
