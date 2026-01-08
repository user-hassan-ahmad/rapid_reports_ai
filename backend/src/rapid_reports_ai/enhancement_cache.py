"""
Enhancement Pipeline Cache Module
Caches expensive LLM queries and API calls based on content hash (findings/clinical history).
Settings changes don't invalidate cache - only content changes do.
"""
import hashlib
import json
import time
import logging
from typing import Any, Optional, Dict, List, Callable
from functools import wraps
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, func as sa_func
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class EnhancementCache:
    """
    Content-based cache for enhancement pipeline.
    Caches based on findings/clinical history hash, not settings.
    Uses PostgreSQL/SQLite database for persistent storage.
    """
    
    def __init__(self, ttl_seconds: Optional[int] = None, db_session: Optional[Session] = None):
        """
        Initialize cache.
        
        Args:
            ttl_seconds: Time-to-live for cache entries in seconds. None = no expiry.
            db_session: Optional database session. If None, creates new session per operation.
        """
        self._cache: Dict[str, Dict[str, Any]] = {}  # Fallback in-memory cache
        self.ttl_seconds = ttl_seconds or 86400  # Default 24 hours
        self.hits = 0
        self.misses = 0
        self._db_session = db_session
        self._use_db = True  # Flag to enable/disable DB usage
        self._fallback_mode = False  # Track if we're in fallback mode
    
    def _get_db_session(self) -> Optional[Session]:
        """Get database session, creating one if needed."""
        if not self._use_db:
            return None
        
        if self._db_session is not None:
            return self._db_session
        
        try:
            from .database import SessionLocal
            return SessionLocal()
        except Exception as e:
            logger.warning(f"Failed to create database session: {e}")
            self._fallback_mode = True
            return None
    
    def _parse_cache_key(self, cache_key: str) -> tuple[str, str]:
        """
        Parse cache key to extract findings_hash and cache_type.
        
        Cache key format: "{cache_type}:{findings_hash}:finding_{idx}[:additional_hash]"
        Examples:
        - "query_gen:abc123:finding_1"
        - "perplexity_search:abc123:finding_1:def456"
        - "guideline_validation:abc123:finding_1:def456"
        
        Returns:
            Tuple of (findings_hash, cache_type)
        """
        try:
            parts = cache_key.split(':')
            if len(parts) < 2:
                return ('', 'unknown')
            
            cache_type = parts[0]
            findings_hash = ''
            
            # Look for "finding_" pattern to identify where findings_hash ends
            finding_idx = -1
            for i, part in enumerate(parts):
                if part.startswith('finding_'):
                    finding_idx = i
                    break
            
            if finding_idx > 0:
                # findings_hash is the part right before "finding_"
                findings_hash = parts[finding_idx - 1]
            elif len(parts) >= 2:
                # Fallback: second part might be findings_hash
                # But be careful - it could be a hash without "finding_" pattern
                # Check if it looks like a hash (hex string, 32-64 chars)
                potential_hash = parts[1]
                if len(potential_hash) >= 32 and all(c in '0123456789abcdef' for c in potential_hash.lower()):
                    findings_hash = potential_hash
            
            # Limit findings_hash to 64 chars (database column limit)
            findings_hash = findings_hash[:64] if findings_hash else ''
            
            return (findings_hash, cache_type)
        except Exception as e:
            logger.warning(f"Failed to parse cache key '{cache_key}': {e}")
            return ('', 'unknown')
    
    def _hash_content(self, *args: Any, **kwargs: Any) -> str:
        """
        Generate hash from content (excluding settings).
        
        Args:
            *args: Positional arguments to hash
            **kwargs: Keyword arguments to hash
            
        Returns:
            Hex digest of hash
        """
        # Serialize arguments to JSON string for hashing
        # Sort keys for consistency
        content = {
            'args': args,
            'kwargs': kwargs
        }
        content_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(content_str.encode('utf-8')).hexdigest()
    
    def get(self, cache_key: str) -> Optional[Any]:
        """
        Get cached value from database.
        
        Args:
            cache_key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        db = self._get_db_session()
        own_session = db is not None and self._db_session is None
        
        try:
            if db is not None:
                from .database.models import EnhancementCacheEntry
                
                # Query database
                entry = db.query(EnhancementCacheEntry).filter(
                    EnhancementCacheEntry.cache_key == cache_key
                ).first()
                
                if entry is None:
                    self.misses += 1
                    if own_session:
                        db.close()
                    return None
                
                # Check expiration
                now = datetime.now(timezone.utc)
                if entry.expires_at < now:
                    # Expired - delete and return None
                    db.delete(entry)
                    db.commit()
                    self.misses += 1
                    if own_session:
                        db.close()
                    return None
                
                # Update access tracking
                entry.last_accessed = now
                entry.access_count += 1
                db.commit()
                
                self.hits += 1
                value = entry.cached_value
                if own_session:
                    db.close()
                return value
            else:
                # Fallback to in-memory cache
                if cache_key not in self._cache:
                    self.misses += 1
                    return None
                
                entry = self._cache[cache_key]
                
                # Check expiry (for in-memory)
                if self.ttl_seconds is not None:
                    created_at = entry.get('created_at')
                    if created_at is not None:
                        age = time.time() - created_at
                        if age > self.ttl_seconds:
                            del self._cache[cache_key]
                            self.misses += 1
                            return None
                
                self.hits += 1
                return entry['value']
                
        except Exception as e:
            logger.error(f"Error getting cache entry '{cache_key}': {e}", exc_info=True)
            self._fallback_mode = True
            
            # Fallback to in-memory cache
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                if self.ttl_seconds is not None:
                    created_at = entry.get('created_at')
                    if created_at is not None:
                        age = time.time() - created_at
                        if age > self.ttl_seconds:
                            del self._cache[cache_key]
                            self.misses += 1
                            return None
                self.hits += 1
                return entry['value']
            
            self.misses += 1
            if own_session and db:
                try:
                    db.rollback()
                    db.close()
                except:
                    pass
            return None
    
    def set(self, cache_key: str, value: Any) -> None:
        """
        Set cached value in database.
        
        Args:
            cache_key: Cache key
            value: Value to cache
        """
        db = self._get_db_session()
        own_session = db is not None and self._db_session is None
        
        try:
            if db is not None:
                from .database.models import EnhancementCacheEntry
                
                # Parse cache key to extract findings_hash and cache_type
                findings_hash, cache_type = self._parse_cache_key(cache_key)
                
                # Calculate expiration time
                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(seconds=self.ttl_seconds) if self.ttl_seconds else now + timedelta(days=365)
                
                # Check if entry exists
                entry = db.query(EnhancementCacheEntry).filter(
                    EnhancementCacheEntry.cache_key == cache_key
                ).first()
                
                if entry:
                    # Update existing entry
                    entry.cached_value = value
                    entry.last_accessed = now
                    entry.expires_at = expires_at
                    # Don't reset access_count on update
                else:
                    # Create new entry
                    entry = EnhancementCacheEntry(
                        cache_key=cache_key,
                        findings_hash=findings_hash,
                        cache_type=cache_type,
                        cached_value=value,
                        created_at=now,
                        last_accessed=now,
                        access_count=1,
                        expires_at=expires_at
                    )
                    db.add(entry)
                
                db.commit()
                if own_session:
                    db.close()
            else:
                # Fallback to in-memory cache
                self._cache[cache_key] = {
                    'value': value,
                    'created_at': time.time()
                }
                
        except Exception as e:
            logger.error(f"Error setting cache entry '{cache_key}': {e}", exc_info=True)
            self._fallback_mode = True
            
            # Fallback to in-memory cache
            try:
                self._cache[cache_key] = {
                    'value': value,
                    'created_at': time.time()
                }
            except:
                pass
            
            if own_session and db:
                try:
                    db.rollback()
                    db.close()
                except:
                    pass
    
    def clear(self) -> None:
        """Clear all cache entries from database and memory."""
        db = self._get_db_session()
        own_session = db is not None and self._db_session is None
        
        try:
            if db is not None:
                from .database.models import EnhancementCacheEntry
                db.query(EnhancementCacheEntry).delete()
                db.commit()
                if own_session:
                    db.close()
        except Exception as e:
            logger.error(f"Error clearing cache: {e}", exc_info=True)
            if own_session and db:
                try:
                    db.rollback()
                    db.close()
                except:
                    pass
        
        # Also clear in-memory fallback
        self._cache.clear()
        self.hits = 0
        self.misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics from database."""
        db = self._get_db_session()
        own_session = db is not None and self._db_session is None
        
        db_size = 0
        db_hits = 0
        
        try:
            if db is not None:
                from .database.models import EnhancementCacheEntry
                db_size = db.query(EnhancementCacheEntry).count()
                # Sum access_count - 1 for each entry (first access created it)
                db_hits = db.query(
                    sa_func.sum(EnhancementCacheEntry.access_count - 1)
                ).scalar() or 0
                if own_session:
                    db.close()
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}", exc_info=True)
            if own_session and db:
                try:
                    db.rollback()
                    db.close()
                except:
                    pass
        
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0.0
        
        return {
            'hits': self.hits + db_hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'size': db_size + len(self._cache),
            'db_size': db_size,
            'memory_size': len(self._cache),
            'fallback_mode': self._fallback_mode
        }
    
    def generate_cache_key(self, prefix: str, *args: Any, **kwargs: Any) -> str:
        """
        Generate cache key with prefix.
        
        Args:
            prefix: Key prefix (e.g., 'query_gen', 'perplexity_search')
            *args: Positional arguments to hash
            **kwargs: Keyword arguments to hash
            
        Returns:
            Cache key string
        """
        content_hash = self._hash_content(*args, **kwargs)
        return f"{prefix}:{content_hash}"


# Global cache instance (can be replaced with Redis for multi-process/multi-server)
_global_cache: Optional[EnhancementCache] = None


def get_cache() -> EnhancementCache:
    """Get global cache instance (DB-backed)."""
    global _global_cache
    if _global_cache is None:
        # Default TTL: 24 hours (can be configured via env var)
        import os
        ttl = os.getenv('ENHANCEMENT_CACHE_TTL_SECONDS')
        ttl_seconds = int(ttl) if ttl else 86400  # 24 hours default
        # Create DB-backed cache (no session passed, will create per operation)
        _global_cache = EnhancementCache(ttl_seconds=ttl_seconds, db_session=None)
    return _global_cache


def clear_cache() -> None:
    """Clear global cache."""
    get_cache().clear()


def cleanup_expired_entries(db: Optional[Session] = None) -> int:
    """
    Delete expired cache entries from database.
    
    Args:
        db: Optional database session. If None, creates new session.
    
    Returns:
        Number of entries deleted
    """
    from .database.models import EnhancementCacheEntry
    from .database import SessionLocal
    
    own_session = db is None
    if db is None:
        db = SessionLocal()
    
    try:
        now = datetime.now(timezone.utc)
        deleted_count = db.query(EnhancementCacheEntry).filter(
            EnhancementCacheEntry.expires_at < now
        ).delete()
        db.commit()
        logger.info(f"Cleaned up {deleted_count} expired cache entries")
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired cache entries: {e}", exc_info=True)
        db.rollback()
        return 0
    finally:
        if own_session:
            db.close()


def cache_result(cache_key_prefix: str, key_func: Optional[Callable] = None):
    """
    Decorator to cache function results based on content hash.
    
    Args:
        cache_key_prefix: Prefix for cache keys (e.g., 'query_gen')
        key_func: Optional function to extract cache key arguments from function args/kwargs.
                  If None, uses all args/kwargs.
    
    Example:
        @cache_result('query_gen', key_func=lambda finding, **kwargs: (finding,))
        async def generate_queries(finding: str, api_key: str):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache = get_cache()
            
            # Extract key arguments
            if key_func:
                key_args = key_func(*args, **kwargs)
                if isinstance(key_args, tuple):
                    cache_key = cache.generate_cache_key(cache_key_prefix, *key_args)
                else:
                    cache_key = cache.generate_cache_key(cache_key_prefix, key_args)
            else:
                # Use all arguments
                cache_key = cache.generate_cache_key(cache_key_prefix, *args, **kwargs)
            
            # Check cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                print(f"[CACHE HIT] {cache_key_prefix}: Using cached result")
                return cached_value
            
            # Cache miss - execute function
            print(f"[CACHE MISS] {cache_key_prefix}: Executing function")
            result = await func(*args, **kwargs)
            
            # Store in cache
            cache.set(cache_key, result)
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache = get_cache()
            
            # Extract key arguments
            if key_func:
                key_args = key_func(*args, **kwargs)
                if isinstance(key_args, tuple):
                    cache_key = cache.generate_cache_key(cache_key_prefix, *key_args)
                else:
                    cache_key = cache.generate_cache_key(cache_key_prefix, key_args)
            else:
                # Use all arguments
                cache_key = cache.generate_cache_key(cache_key_prefix, *args, **kwargs)
            
            # Check cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                print(f"[CACHE HIT] {cache_key_prefix}: Using cached result")
                return cached_value
            
            # Cache miss - execute function
            print(f"[CACHE MISS] {cache_key_prefix}: Executing function")
            result = func(*args, **kwargs)
            
            # Store in cache
            cache.set(cache_key, result)
            return result
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def generate_content_hash(user_inputs: Dict[str, str]) -> str:
    """
    Generate content hash from user inputs (findings, clinical history).
    Excludes settings from hash - only hashes actual content.
    
    Args:
        user_inputs: Dict with 'FINDINGS', 'CLINICAL_HISTORY', etc.
        
    Returns:
        Hex digest of content hash
    """
    # Extract only content fields (not settings)
    content_fields = {
        'findings': user_inputs.get('FINDINGS', ''),
        'clinical_history': user_inputs.get('CLINICAL_HISTORY', '')
    }
    
    # Sort keys for consistency
    content_str = json.dumps(content_fields, sort_keys=True, default=str)
    return hashlib.sha256(content_str.encode('utf-8')).hexdigest()


def generate_finding_hash(finding: str) -> str:
    """
    Generate hash for a single finding string.
    
    Args:
        finding: Finding text
        
    Returns:
        Hex digest of finding hash
    """
    return hashlib.sha256(finding.encode('utf-8')).hexdigest()


def generate_query_hash(queries: List[str]) -> str:
    """
    Generate hash for a list of search queries.
    
    Args:
        queries: List of query strings
        
    Returns:
        Hex digest of queries hash
    """
    # Sort queries for consistency
    sorted_queries = sorted(queries)
    queries_str = json.dumps(sorted_queries, sort_keys=True)
    return hashlib.sha256(queries_str.encode('utf-8')).hexdigest()


def generate_search_results_hash(search_results: List[Dict]) -> str:
    """
    Generate hash for search results.
    Uses URL + title + snippet for hashing (actual content, not metadata).
    
    Args:
        search_results: List of search result dicts
        
    Returns:
        Hex digest of search results hash
    """
    # Extract content fields for hashing
    content_list = []
    for result in search_results:
        content = {
            'url': result.get('url', ''),
            'title': result.get('title', ''),
            'snippet': result.get('snippet', '')
        }
        content_list.append(content)
    
    # Sort by URL for consistency
    content_list.sort(key=lambda x: x['url'])
    content_str = json.dumps(content_list, sort_keys=True)
    return hashlib.sha256(content_str.encode('utf-8')).hexdigest()
