#!/usr/bin/env python3
"""
Verify that migrations are working on Railway by checking for the test table.
"""
import os
import sys
from pathlib import Path

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'src'))

from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

load_dotenv()

def main():
    # Get database URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        database_url = "sqlite:///./rapid_reports.db"
    
    # Convert Railway's postgres:// to postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    print("=" * 70)
    print("  MIGRATION VERIFICATION TEST")
    print("=" * 70)
    
    # Detect database type
    if "sqlite" in database_url:
        print("\n📁 Testing: SQLite (Local)")
    elif "postgresql" in database_url:
        print("\n🐘 Testing: PostgreSQL (Railway)")
    
    print("\n1. Checking for migration_test_table...")
    
    try:
        engine = create_engine(database_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'migration_test_table' in tables:
            print("   ✅ FOUND: migration_test_table exists!")
            
            # Read the test data
            with engine.connect() as conn:
                result = conn.execute(text("SELECT * FROM migration_test_table"))
                rows = result.fetchall()
                
                print(f"\n2. Table contains {len(rows)} row(s):")
                for row in rows:
                    print(f"   - ID: {row[0]}")
                    print(f"     Message: {row[1]}")
                    print(f"     Created: {row[2]}")
                    print(f"     Deployment: {row[3]}")
            
            # Check alembic version
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version"))
                version = result.fetchone()[0]
                print(f"\n3. Current migration version: {version}")
                
                if version == '3863316116d1':
                    print("   ✅ Correct version! (test migration)")
                else:
                    print("   ⚠️  Expected: 3863316116d1")
            
            print("\n" + "=" * 70)
            print("🎉 SUCCESS! Migrations are working correctly!")
            print("=" * 70)
            return True
            
        else:
            print("   ❌ NOT FOUND: migration_test_table does not exist")
            print("\nAvailable tables:")
            for table in sorted(tables):
                print(f"   - {table}")
            
            # Check alembic version
            if 'alembic_version' in tables:
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT version_num FROM alembic_version"))
                    version = result.fetchone()[0]
                    print(f"\nCurrent migration version: {version}")
                    print("Expected: 3863316116d1")
            
            print("\n" + "=" * 70)
            print("❌ FAILURE: Test migration not applied")
            print("=" * 70)
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
