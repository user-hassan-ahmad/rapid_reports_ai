#!/usr/bin/env python3
"""
Delete all templates and template_versions before schema migration.
This ensures clean migration to new template_config structure.
"""
import sys
import os
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'src'))

from rapid_reports_ai.database.connection import SessionLocal
from rapid_reports_ai.database.models import Template, TemplateVersion
from dotenv import load_dotenv

load_dotenv()

def main():
    print("=" * 60)
    print("Deleting all templates and template versions...")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        # Count templates before deletion
        template_count = db.query(Template).count()
        version_count = db.query(TemplateVersion).count()
        
        print(f"\nFound:")
        print(f"  - {template_count} template(s)")
        print(f"  - {version_count} template version(s)")
        
        if template_count == 0 and version_count == 0:
            print("\n✓ No templates to delete. Database is already clean.")
            return
        
        # Delete template versions first (due to foreign key constraint)
        print("\nDeleting template versions...")
        deleted_versions = db.query(TemplateVersion).delete()
        db.commit()
        print(f"✓ Deleted {deleted_versions} template version(s)")
        
        # Delete templates
        print("Deleting templates...")
        deleted_templates = db.query(Template).delete()
        db.commit()
        print(f"✓ Deleted {deleted_templates} template(s)")
        
        print("\n" + "=" * 60)
        print("✓ All templates deleted successfully!")
        print("=" * 60)
        
    except Exception as e:
        print("=" * 60)
        print(f"✗ Deletion failed: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

