#!/usr/bin/env python3
"""
Run Alembic migrations for Railway deployment.
This script handles database migrations and ensures the database is up to date.
"""
import sys
import os
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'src'))

from alembic.config import Config
from alembic import command
from dotenv import load_dotenv

load_dotenv()

def main():
    # Get database URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("✗ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Railway and some other platforms use 'postgres://' but SQLAlchemy 1.4+ requires 'postgresql://'
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        # Update the environment variable for alembic to use
        os.environ["DATABASE_URL"] = database_url
    
    print("=" * 60)
    print("Running Alembic Migrations")
    print("=" * 60)
    print(f"Database: {database_url.split('@')[1] if '@' in database_url else 'local'}")
    print()
    
    # Change to backend directory where alembic.ini is located
    os.chdir(script_dir)
    
    # Create Alembic config
    alembic_cfg = Config("alembic.ini")
    
    # Run migrations
    try:
        print("Upgrading database to head revision...")
        command.upgrade(alembic_cfg, "head")
        print()
        print("✓ Migrations completed successfully!")
        print("=" * 60)
    except Exception as e:
        print()
        print(f"✗ Migration failed: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

