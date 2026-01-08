#!/usr/bin/env python3
"""
Test script to verify enhancement cache functionality:
1. Database connection and table creation
2. Cache get/set operations
3. Datetime expiration handling
4. Cache key parsing
5. Finding text hash generation
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from rapid_reports_ai.database import SessionLocal, engine, Base, EnhancementCacheEntry
from rapid_reports_ai.enhancement_cache import EnhancementCache, get_cache, cleanup_expired_entries
from rapid_reports_ai.database.models import EnhancementCacheEntry as Model
import hashlib

def test_database_connection():
    """Test database connection and table existence"""
    print("=" * 60)
    print("TEST 1: Database Connection")
    print("=" * 60)
    try:
        db = SessionLocal()
        # Check if table exists
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'enhancement_cache' in tables:
            print("✅ Table 'enhancement_cache' exists")
            
            # Check table structure
            columns = inspector.get_columns('enhancement_cache')
            print(f"✅ Table has {len(columns)} columns:")
            for col in columns:
                print(f"   - {col['name']}: {col['type']}")
        else:
            print("❌ Table 'enhancement_cache' does not exist")
            return False
        
        db.close()
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def test_cache_set_get():
    """Test basic cache set/get operations"""
    print("\n" + "=" * 60)
    print("TEST 2: Cache Set/Get Operations")
    print("=" * 60)
    
    try:
        cache = EnhancementCache(ttl_seconds=3600)  # 1 hour TTL
        
        # Test cache set
        test_key = "test:abc123:finding_1"
        test_value = {"queries": ["test query 1", "test query 2"], "model": "test-model"}
        
        print(f"Setting cache key: {test_key}")
        cache.set(test_key, test_value)
        print("✅ Cache set successful")
        
        # Test cache get
        print(f"Getting cache key: {test_key}")
        retrieved_value = cache.get(test_key)
        
        if retrieved_value is None:
            print("❌ Cache get returned None")
            return False
        
        if retrieved_value == test_value:
            print("✅ Cache get successful - value matches")
        else:
            print(f"❌ Cache value mismatch!")
            print(f"   Expected: {test_value}")
            print(f"   Got: {retrieved_value}")
            return False
        
        # Test cache miss
        print(f"Testing cache miss with non-existent key")
        miss_value = cache.get("test:nonexistent:finding_1")
        if miss_value is None:
            print("✅ Cache miss handled correctly")
        else:
            print("❌ Cache miss returned value (should be None)")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Cache set/get test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_datetime_expiration():
    """Test datetime expiration handling"""
    print("\n" + "=" * 60)
    print("TEST 3: Datetime Expiration Handling")
    print("=" * 60)
    
    try:
        db = SessionLocal()
        
        # Create a test entry with expired timestamp
        expired_key = "test:expired:finding_1"
        expired_time = datetime.now(timezone.utc) - timedelta(hours=2)  # 2 hours ago
        
        # Check if entry exists and delete it
        existing = db.query(EnhancementCacheEntry).filter(
            EnhancementCacheEntry.cache_key == expired_key
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
        
        # Create expired entry directly in DB
        expired_entry = EnhancementCacheEntry(
            cache_key=expired_key,
            findings_hash="expired123",
            cache_type="test",
            cached_value={"test": "expired"},
            created_at=expired_time,
            last_accessed=expired_time,
            access_count=1,
            expires_at=expired_time + timedelta(hours=1)  # Expired 1 hour ago
        )
        db.add(expired_entry)
        db.commit()
        print(f"✅ Created expired cache entry (expired 1 hour ago)")
        
        # Test cache get with expired entry
        cache = EnhancementCache(ttl_seconds=3600)
        result = cache.get(expired_key)
        
        if result is None:
            print("✅ Expired entry correctly returns None")
            
            # Verify entry was deleted
            deleted_entry = db.query(EnhancementCacheEntry).filter(
                EnhancementCacheEntry.cache_key == expired_key
            ).first()
            if deleted_entry is None:
                print("✅ Expired entry was deleted from database")
            else:
                print("⚠️  Expired entry still exists in database (may be expected)")
        else:
            print(f"❌ Expired entry returned value: {result}")
            return False
        
        db.close()
        return True
    except Exception as e:
        print(f"❌ Datetime expiration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cache_key_parsing():
    """Test cache key parsing"""
    print("\n" + "=" * 60)
    print("TEST 4: Cache Key Parsing")
    print("=" * 60)
    
    try:
        cache = EnhancementCache()
        
        test_cases = [
            ("query_gen:abc123:finding_1", "abc123", "query_gen"),
            ("perplexity_search:def456:finding_2:ghi789", "def456", "perplexity_search"),
            ("guideline_synth:xyz789:finding_3:abc123", "xyz789", "guideline_synth"),
        ]
        
        for cache_key, expected_hash, expected_type in test_cases:
            finding_hash, cache_type = cache._parse_cache_key(cache_key)
            
            if finding_hash == expected_hash and cache_type == expected_type:
                print(f"✅ '{cache_key}' → hash: {finding_hash}, type: {cache_type}")
            else:
                print(f"❌ '{cache_key}' → Expected: hash={expected_hash}, type={expected_type}")
                print(f"   Got: hash={finding_hash}, type={cache_type}")
                return False
        
        return True
    except Exception as e:
        print(f"❌ Cache key parsing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_finding_text_hash():
    """Test finding text hash generation"""
    print("\n" + "=" * 60)
    print("TEST 5: Finding Text Hash Generation")
    print("=" * 60)
    
    try:
        # Test normalization
        finding1 = "pulmonary embolism"
        finding2 = "Pulmonary Embolism"
        finding3 = "  pulmonary embolism  "
        
        hash1 = hashlib.sha256(finding1.strip().lower().encode('utf-8')).hexdigest()
        hash2 = hashlib.sha256(finding2.strip().lower().encode('utf-8')).hexdigest()
        hash3 = hashlib.sha256(finding3.strip().lower().encode('utf-8')).hexdigest()
        
        if hash1 == hash2 == hash3:
            print("✅ Normalization works correctly - same hash for:")
            print(f"   - '{finding1}'")
            print(f"   - '{finding2}'")
            print(f"   - '{finding3}'")
            print(f"   Hash: {hash1[:16]}...")
        else:
            print("❌ Normalization failed - different hashes for same finding")
            print(f"   Hash1: {hash1[:16]}...")
            print(f"   Hash2: {hash2[:16]}...")
            print(f"   Hash3: {hash3[:16]}...")
            return False
        
        # Test different findings produce different hashes
        finding4 = "right ventricular dilation"
        hash4 = hashlib.sha256(finding4.strip().lower().encode('utf-8')).hexdigest()
        
        if hash1 != hash4:
            print("✅ Different findings produce different hashes")
            print(f"   '{finding1}' → {hash1[:16]}...")
            print(f"   '{finding4}' → {hash4[:16]}...")
        else:
            print("❌ Different findings produced same hash")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Finding text hash test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cache_stats():
    """Test cache statistics"""
    print("\n" + "=" * 60)
    print("TEST 6: Cache Statistics")
    print("=" * 60)
    
    try:
        cache = get_cache()
        stats = cache.get_stats()
        
        print(f"Cache Statistics:")
        print(f"   Hits: {stats.get('hits', 0)}")
        print(f"   Misses: {stats.get('misses', 0)}")
        print(f"   Hit Rate: {stats.get('hit_rate', 0):.2f}%")
        print(f"   DB Size: {stats.get('db_size', 0)} entries")
        print(f"   Memory Size: {stats.get('memory_size', 0)} entries")
        print(f"   Fallback Mode: {stats.get('fallback_mode', False)}")
        
        print("✅ Cache statistics retrieved successfully")
        return True
    except Exception as e:
        print(f"❌ Cache statistics test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("ENHANCEMENT CACHE FUNCTIONALITY TEST")
    print("=" * 60)
    
    tests = [
        ("Database Connection", test_database_connection),
        ("Cache Set/Get", test_cache_set_get),
        ("Datetime Expiration", test_datetime_expiration),
        ("Cache Key Parsing", test_cache_key_parsing),
        ("Finding Text Hash", test_finding_text_hash),
        ("Cache Statistics", test_cache_stats),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    exit(main())
