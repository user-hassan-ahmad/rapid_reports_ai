"""
Firecrawl (https://firecrawl.dev) — scrape, crawl, map, and cloud browser sessions.

Requires FIRECRAWL_API_KEY in the environment (or pass api_key explicitly).
Used by agentic flows that need URL → markdown / structured content or remote browser control.
"""

from __future__ import annotations

import os
from typing import Any, Optional


def get_firecrawl_api_key(explicit: Optional[str] = None) -> Optional[str]:
    return explicit or os.environ.get("FIRECRAWL_API_KEY")


def firecrawl_configured(explicit: Optional[str] = None) -> bool:
    return bool(get_firecrawl_api_key(explicit))


def get_firecrawl(api_key: Optional[str] = None) -> Any:
    """Sync Firecrawl client. Raises ValueError if no API key."""
    from firecrawl import Firecrawl

    key = get_firecrawl_api_key(api_key)
    if not key:
        raise ValueError(
            "Firecrawl API key missing: set FIRECRAWL_API_KEY or pass api_key="
        )
    return Firecrawl(api_key=key)


def get_async_firecrawl(api_key: Optional[str] = None) -> Any:
    """Async client for non-blocking scrape/crawl/search in FastAPI agents."""
    from firecrawl import AsyncFirecrawl

    key = get_firecrawl_api_key(api_key)
    if not key:
        raise ValueError(
            "Firecrawl API key missing: set FIRECRAWL_API_KEY or pass api_key="
        )
    return AsyncFirecrawl(api_key=key)


def get_firecrawl_optional(api_key: Optional[str] = None) -> Optional[Any]:
    """Return a sync client or None if unconfigured (for optional features)."""
    if not firecrawl_configured(api_key):
        return None
    return get_firecrawl(api_key=api_key)
