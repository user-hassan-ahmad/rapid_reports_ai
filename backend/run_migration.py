#!/usr/bin/env python3
"""
Simple script to run the database migration
"""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from alembic.config import Config
from alembic import command

def main():
    # Change to backend directory
    os.chdir(os.path.dirname(__file__))
    
    # Create Alembic config
    alembic_cfg = Config("alembic.ini")
    
    # Run upgrade to head
    print("Running database migration...")
    try:
        command.upgrade(alembic_cfg, "head")
        print("✓ Migration completed successfully!")
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

