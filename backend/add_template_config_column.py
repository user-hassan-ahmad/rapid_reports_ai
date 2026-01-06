#!/usr/bin/env python3
"""
Simple script to add template_config column to templates and template_versions tables.
This works for both SQLite and PostgreSQL.
"""
import sys
import os
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'src'))

from rapid_reports_ai.database.connection import engine, SessionLocal
from sqlalchemy import text, inspect

def main():
    print("=" * 60)
    print("Adding template_config column to templates tables...")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        # Check if column already exists
        inspector = inspect(engine)
        templates_columns = [col['name'] for col in inspector.get_columns('templates')]
        
        if 'template_config' in templates_columns:
            print("✓ template_config column already exists in templates table")
        else:
            print("Adding template_config column to templates table...")
            db.execute(text("ALTER TABLE templates ADD COLUMN template_config TEXT"))
            db.commit()
            print("✓ Added template_config column to templates table")
        
        # Check template_versions table
        template_versions_columns = [col['name'] for col in inspector.get_columns('template_versions')]
        
        if 'template_config' in template_versions_columns:
            print("✓ template_config column already exists in template_versions table")
        else:
            print("Adding template_config column to template_versions table...")
            db.execute(text("ALTER TABLE template_versions ADD COLUMN template_config TEXT"))
            db.commit()
            print("✓ Added template_config column to template_versions table")
        
        print("=" * 60)
        print("✓ Migration completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print("=" * 60)
        print(f"✗ Migration failed: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

