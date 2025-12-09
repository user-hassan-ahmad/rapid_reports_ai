#!/usr/bin/env python3
"""
Test database connection and verify tables exist.
Run this to diagnose database connection issues.
"""
import os
import sys
from pathlib import Path

# Add src to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'src'))

from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv

load_dotenv()

def main():
    print("=" * 60)
    print("Database Connection Diagnostic")
    print("=" * 60)
    
    # Check DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("✗ ERROR: DATABASE_URL not set in environment")
        print("\nPlease set DATABASE_URL environment variable.")
        sys.exit(1)
    
    # Mask password in URL for display
    if '@' in database_url:
        parts = database_url.split('@')
        if len(parts) == 2:
            masked_url = f"{parts[0].split(':')[0]}:***@{parts[1]}"
        else:
            masked_url = database_url
    else:
        masked_url = database_url
    
    print(f"\n✓ DATABASE_URL is set")
    print(f"  URL: {masked_url}")
    
    # Try to create engine and connect
    try:
        print("\nAttempting to connect to database...")
        engine = create_engine(database_url)
        
        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"✓ Successfully connected to database!")
            print(f"  PostgreSQL version: {version.split(',')[0]}")
        
        # Check for tables
        print("\n" + "=" * 60)
        print("Checking for tables...")
        print("=" * 60)
        
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if not tables:
            print("✗ No tables found in database")
            print("\nThis means migrations haven't run yet.")
            print("\nTo fix:")
            print("1. Check Railway deployment logs for migration errors")
            print("2. Verify fix_migration_state.py ran during startup")
            print("3. Manually run: cd backend && poetry run python fix_migration_state.py")
        else:
            print(f"✓ Found {len(tables)} table(s):")
            for table in sorted(tables):
                print(f"  - {table}")
            
            # Check for alembic_version table
            if 'alembic_version' in tables:
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
                    row = result.fetchone()
                    if row:
                        print(f"\n✓ Alembic version: {row[0]}")
                    else:
                        print("\n⚠️  alembic_version table exists but is empty")
            else:
                print("\n⚠️  alembic_version table not found - migrations may not have run")
            
            # Check for expected tables
            expected_tables = ['users', 'reports', 'templates', 'report_versions', 'template_versions']
            missing_tables = [t for t in expected_tables if t not in tables]
            
            if missing_tables:
                print(f"\n⚠️  Missing expected tables: {', '.join(missing_tables)}")
            else:
                print("\n✓ All expected tables are present!")
        
        # Check for validation_status column in reports table
        if 'reports' in tables:
            print("\n" + "=" * 60)
            print("Checking reports table columns...")
            print("=" * 60)
            columns = [col['name'] for col in inspector.get_columns('reports')]
            print(f"Found {len(columns)} column(s) in reports table:")
            for col in sorted(columns):
                marker = "✓" if col == 'validation_status' else " "
                print(f"  {marker} {col}")
            
            if 'validation_status' in columns:
                print("\n✓ validation_status column exists!")
            else:
                print("\n⚠️  validation_status column missing - migrations may not be up to date")
        
    except Exception as e:
        print(f"\n✗ ERROR connecting to database: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Diagnostic complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()



