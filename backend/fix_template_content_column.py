#!/usr/bin/env python3
"""
Fix template_content column issue - drop it since we're using template_config now
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
    print("Fixing template_content column...")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        
        # Check templates table
        templates_columns = [col['name'] for col in inspector.get_columns('templates')]
        
        if 'template_content' in templates_columns:
            print("Dropping template_content column from templates table...")
            db.execute(text("ALTER TABLE templates DROP COLUMN template_content"))
            db.commit()
            print("✓ Dropped template_content column from templates table")
        else:
            print("✓ template_content column does not exist in templates table")
        
        # Check template_versions table
        template_versions_columns = [col['name'] for col in inspector.get_columns('template_versions')]
        
        if 'template_content' in template_versions_columns:
            print("Dropping template_content column from template_versions table...")
            db.execute(text("ALTER TABLE template_versions DROP COLUMN template_content"))
            db.commit()
            print("✓ Dropped template_content column from template_versions table")
        else:
            print("✓ template_content column does not exist in template_versions table")
        
        print("=" * 60)
        print("✓ Fix completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print("=" * 60)
        print(f"✗ Fix failed: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

