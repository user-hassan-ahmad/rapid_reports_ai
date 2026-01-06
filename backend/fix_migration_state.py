#!/usr/bin/env python3
"""
Fix Alembic migration state when database is out of sync.
This script checks the database state and stamps it to the correct revision.
"""
import sys
import os
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'src'))

from alembic.config import Config
from alembic import command
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv

load_dotenv()

def check_alembic_version(engine):
    """Check current Alembic version in database."""
    with engine.connect() as conn:
        # Check if alembic_version table exists
        inspector = inspect(engine)
        if 'alembic_version' not in inspector.get_table_names():
            return None
        
        # Get current version
        result = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.fetchone()
        return row[0] if row else None

def check_column_exists(engine, table_name, column_name):
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def check_table_exists(engine, table_name):
    """Check if a table exists."""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def main():
    # Get database URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("✗ ERROR: DATABASE_URL not set")
        sys.exit(1)
    
    # Create engine
    engine = create_engine(database_url)
    
    print("=" * 60)
    print("Checking database migration state...")
    print("=" * 60)
    
    # Check current Alembic version
    current_version = check_alembic_version(engine)
    print(f"Current Alembic version in DB: {current_version or 'None (not initialized)'}")
    
    if current_version:
        print("✓ Database already has Alembic version tracked")
        # Check if we're already at head to avoid unnecessary upgrade
        os.chdir(script_dir)
        alembic_cfg = Config("alembic.ini")
        from alembic.script import ScriptDirectory
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()
        
        if current_version == head_revision:
            print(f"✓ Database already at head revision ({head_revision}), no migration needed")
            return
        else:
            print(f"Current version: {current_version}, Head: {head_revision}")
            print("Running migration upgrade to head...")
            command.upgrade(alembic_cfg, "head")
            print("✓ Migration completed!")
            return
    
    # No version tracked - need to determine correct starting point
    print("\nNo Alembic version found. Checking database state...")
    
    # Check for key columns/tables to determine migration state
    has_signature = check_column_exists(engine, 'users', 'signature')
    has_settings = check_column_exists(engine, 'users', 'settings')
    has_reports = check_table_exists(engine, 'reports')
    has_validation_status = check_column_exists(engine, 'reports', 'validation_status') if has_reports else False
    
    print(f"  - users.signature column: {'✓ exists' if has_signature else '✗ missing'}")
    print(f"  - users.settings column: {'✓ exists' if has_settings else '✗ missing'}")
    print(f"  - reports table: {'✓ exists' if has_reports else '✗ missing'}")
    if has_reports:
        print(f"  - reports.validation_status column: {'✓ exists' if has_validation_status else '✗ missing'}")
    
    # Determine target revision based on what exists
    has_template_config = check_column_exists(engine, 'templates', 'template_config') if check_table_exists(engine, 'templates') else False
    has_writing_style_presets = check_table_exists(engine, 'writing_style_presets')
    
    if has_writing_style_presets:
        # Database has writing_style_presets table, check if it's the latest
        target_revision = 'a1b2c3d4e5f6'  # writing_style_presets migration
        print(f"\n✓ Database has writing_style_presets table")
    elif has_template_config:
        # Database has template_config, check if it's the latest
        target_revision = '20260103094159'  # template_config migration
        print(f"\n✓ Database has template_config column")
    elif has_validation_status:
        # Database is up to date with validation_status but missing template_config
        target_revision = 'e315d7dc70b'  # validation_status migration
        print(f"\n✓ Database has validation_status but missing template_config")
    elif has_reports:
        # Reports table exists but no validation_status
        target_revision = 'f123456789ab'  # Before validation_status
        print(f"\n⚠️  Database missing validation_status column")
    elif has_settings:
        # User settings exist but no reports
        target_revision = '9b13771bba66'  # After user_settings
        print(f"\n⚠️  Database missing reports table")
    elif has_signature:
        # Signature exists but nothing else
        target_revision = 'be6c2732a3d1'  # After signature
        print(f"\n⚠️  Database only has signature column")
    else:
        # Empty database
        target_revision = None
        print(f"\n⚠️  Database appears empty")
    
    if target_revision:
        print(f"\nStamping database to revision: {target_revision}")
        os.chdir(script_dir)
        alembic_cfg = Config("alembic.ini")
        command.stamp(alembic_cfg, target_revision)
        print(f"✓ Database stamped to {target_revision}")
        
        # Check if we need to upgrade further
        from alembic.script import ScriptDirectory
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()
        
        if target_revision == head_revision:
            print(f"✓ Database already at head revision ({head_revision}), no upgrade needed")
        else:
            print(f"\nRunning upgrade from {target_revision} to {head_revision}...")
            command.upgrade(alembic_cfg, "head")
            print("✓ Migration completed!")
    else:
        print("\nRunning full migration from scratch...")
        os.chdir(script_dir)
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        print("✓ Migration completed!")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

