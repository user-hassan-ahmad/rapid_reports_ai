"""Library endpoints (spec §3): search on every keystroke (rerank after a pause) and the "not listed" log."""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...auth import get_current_user
from ...database.models import User
from .bundle import get_bundle, library_allowed
from .match import SearchResult, search

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/protocols")


class SearchRequest(BaseModel):
    q: str = ""
    rerank: bool = False


class NotListedRequest(BaseModel):
    q: str = ""


def _bundle():
    if not library_allowed():
        raise HTTPException(status_code=404, detail="Not found")
    return get_bundle()


@router.post("/search", response_model=SearchResult)
async def protocols_search(req: SearchRequest, user: User = Depends(get_current_user)):
    return await search(_bundle(), req.q[:200], rerank_on=req.rerank)


@router.post("/not-listed")
async def protocols_not_listed(req: NotListedRequest, user: User = Depends(get_current_user)):
    _bundle()
    q = req.q[:200]  # never log typed text (it can carry patient detail): length and a short hash only
    logger.info("[protocol_library] not listed: len=%d sha=%s", len(q), hashlib.sha256(q.encode()).hexdigest()[:10])
    return {"ok": True}
