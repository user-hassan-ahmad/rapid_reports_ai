#!/usr/bin/env python3
"""
Simple script to run the database migration
"""
import sys
import os
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'src'))

from alembic.config import Config
from alembic import command

def main():
    # Change to backend directory (where alembic.ini is located)
    backend_dir = script_dir
    os.chdir(str(backend_dir))
    
    print(f"Current working directory: {os.getcwd()}")
    print(f"Looking for alembic.ini at: {backend_dir / 'alembic.ini'}")
    
    # Verify alembic.ini exists
    alembic_ini_path = backend_dir / "alembic.ini"
    if not alembic_ini_path.exists():
        print(f"✗ ERROR: alembic.ini not found at {alembic_ini_path}")
        print(f"Contents of {backend_dir}: {list(backend_dir.iterdir())}")
        sys.exit(1)
    
    # Check DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("⚠️  WARNING: DATABASE_URL not set, migrations may fail")
    else:
        # Mask password in URL for logging
        masked_url = database_url.split('@')[-1] if '@' in database_url else database_url
        print(f"Database URL: ...@{masked_url}")
    
    # Create Alembic config
    alembic_cfg = Config(str(alembic_ini_path))
    
    # Run upgrade to head
    print("=" * 60)
    print("Running database migrations...")
    print("=" * 60)
    try:
        command.upgrade(alembic_cfg, "head")
        print("=" * 60)
        print("✓ Migration completed successfully!")
        print("=" * 60)
    except Exception as e:
        print("=" * 60)
        print(f"✗ Migration failed: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

