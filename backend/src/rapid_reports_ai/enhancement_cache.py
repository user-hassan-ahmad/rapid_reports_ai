"""
Enhancement Pipeline Cache Module
Caches expensive LLM queries and API calls based on content hash (findings/clinical history).
Settings changes don't invalidate cache - only content changes do.
"""
import hashlib
import json
import time
from typing import Any, Optional, Dict, List, Callable
from functools import wraps
from datetime import datetime, timedelta


class EnhancementCache:
    """
    Content-based cache for enhancement pipeline.
    Caches based on findings/clinical history hash, not settings.
    """
    
    def __init__(self, ttl_seconds: Optional[int] = None):
        """
        Initialize cache.
        
        Args:
            ttl_seconds: Time-to-live for cache entries in seconds. None = no expiry.
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.ttl_seconds = ttl_seconds
        self.hits = 0
        self.misses = 0
    
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
    
    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """Check if cache entry has expired."""
        if self.ttl_seconds is None:
            return False
        created_at = entry.get('created_at')
        if created_at is None:
            return True
        age = time.time() - created_at
        return age > self.ttl_seconds
    
    def get(self, cache_key: str) -> Optional[Any]:
        """
        Get cached value.
        
        Args:
            cache_key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        if cache_key not in self._cache:
            self.misses += 1
            return None
        
        entry = self._cache[cache_key]
        
        # Check expiry
        if self._is_expired(entry):
            del self._cache[cache_key]
            self.misses += 1
            return None
        
        self.hits += 1
        return entry['value']
    
    def set(self, cache_key: str, value: Any) -> None:
        """
        Set cached value.
        
        Args:
            cache_key: Cache key
            value: Value to cache
        """
        self._cache[cache_key] = {
            'value': value,
            'created_at': time.time()
        }
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self.hits = 0
        self.misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0.0
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'size': len(self._cache)
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
    """Get global cache instance."""
    global _global_cache
    if _global_cache is None:
        # Default TTL: 24 hours (can be configured via env var)
        import os
        ttl = os.getenv('ENHANCEMENT_CACHE_TTL_SECONDS')
        ttl_seconds = int(ttl) if ttl else 86400  # 24 hours default
        _global_cache = EnhancementCache(ttl_seconds=ttl_seconds)
    return _global_cache


def clear_cache() -> None:
    """Clear global cache."""
    get_cache().clear()


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
