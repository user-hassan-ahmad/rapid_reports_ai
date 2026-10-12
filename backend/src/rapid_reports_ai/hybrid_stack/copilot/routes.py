"""Copilot endpoints (spec §5). On with the hybrid stack unless RR_STACK_COPILOT=0 (kill switch). Reviewers
(RR_STACK_REVIEWERS) verify, edit or discard registry entries.

A targeted fetch can outlast a request: /open and /ask run it in a task with its own session and wait a bounded time.
On timeout the request answers "loading" and the task carries on, so the registry still grows and a retry hits it.
The request's own session is never handed to that task (it closes when the request ends)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Awaitable, Literal, Mapping, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import SessionLocal, get_db
from ...database.models import GuidelineRegistry, User
from ..routes import _reviewer, stack_allowed
from . import ask as A
from . import matcher as M
from . import registry as Reg
from . import tnm
from .ask import QA, AskResult, Context, ask
from .fetch import OVERVIEW, resolve_guideline
from .matcher import Finding, match
from .preview import preview
from .recs import RecsResult, suggest
from .types import Card, Entry, GuidelineContent, Preview

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/canvas/stack/guidelines", tags=["stack-copilot"])

OPEN_TIMEOUT_S = 90.0
ASK_TIMEOUT_S = 45.0
STILL_LOADING = "The guideline is still loading; ask again shortly."

_BG: set[asyncio.Task] = set()   # resolves outliving their request (strong refs until done)
T = TypeVar("T")


def copilot_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("RR_STACK_COPILOT", "1") != "0" and stack_allowed(env)


def _require() -> None:
    if not copilot_allowed():
        raise HTTPException(status_code=404, detail="Not Found")


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _bg_done(task: asyncio.Task) -> None:
    _BG.discard(task)
    if not task.cancelled() and task.exception() is not None:
        e = task.exception()
        logger.warning("[copilot.routes] background %s: %s", type(e).__name__, str(e)[:200])


async def _bounded(job: Awaitable[T], timeout: float) -> tuple[bool, T | None]:
    """(done, result). The job runs as a task the timeout never cancels (shielded): it finishes in the background."""
    task = asyncio.get_running_loop().create_task(job)
    _BG.add(task)
    task.add_done_callback(_bg_done)
    try:
        return True, await asyncio.wait_for(asyncio.shield(task), timeout)
    except asyncio.TimeoutError:
        return False, None


class MatchRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    findings: list[Finding] = Field(default_factory=list)


class MatchResult(BaseModel):
    cards: list[Card] = Field(default_factory=list)
    ms: int = 0


class OpenRequest(BaseModel):
    card: Card
    findings: str = ""
    clinical_history: str = ""
    answered: dict[str, str] = Field(default_factory=dict)


class OpenResult(BaseModel):
    entry: Entry | None = None
    preview: Preview | None = None
    branch: str = ""              # the branch previewed (a branchless card's is chosen here)
    ms: int = 0
    error: str | None = None      # "unavailable" (nothing fetched), "loading" (still fetching), "unknown guideline"


class AskRequest(BaseModel):
    question: str
    key: str | None = None
    card: Card | None = None      # the listed card being asked on: resolved first when the registry lacks it
    finding_id: str = ""
    scan_type: str = ""
    clinical_history: str = ""
    findings: str = ""
    history: list[QA] = Field(default_factory=list)


class RecsRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    findings: str = ""
    conclusion: str = ""
    applied: list[str] = Field(default_factory=list)


class RegistryUpdate(BaseModel):
    status: Literal["verified", "draft", "discarded"] | None = None
    content: GuidelineContent | None = None   # a whole-content edit; also how a reviewer verifies a supplement


async def _branch_for(card: Card, entry: Entry, findings: str, history: str) -> str:
    """The card's branch; for a branchless card (ask-originated), as ask does: Jev's pick among the checked branches,
    else the Overview when stored, else the first checked branch."""
    if card.branch:
        return card.branch
    if entry.content.checked():
        picked = await M.pick_branch(findings, entry, history)
        if picked:
            return picked
    if entry.content.branch(OVERVIEW):
        return OVERVIEW
    return next((b.name for b in entry.content.checked()), "")


async def _preview(entry: Entry, branch: str, req: OpenRequest) -> Preview:
    """Fail open: a preview failure still shows the criteria, with no Apply."""
    try:
        return await preview(entry, branch, req.findings[:6000], req.clinical_history[:2000], req.answered)
    except Exception as e:
        logger.warning("[copilot.routes] preview %s: %s", type(e).__name__, str(e)[:200])
        return Preview()


async def _resolve_fresh(card: Card) -> Entry | None:
    with SessionLocal() as db:
        return await resolve_guideline(db, card)


def _offline(key: str) -> Entry | None:
    site = tnm.site_for(key)
    return tnm.entry(site) if site else None


@router.post("/match", response_model=MatchResult)
async def copilot_match(req: MatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    t0 = time.perf_counter()
    cards = await match(db, req.scan_type[:300], req.clinical_history[:2000], req.findings[:20])
    return MatchResult(cards=cards, ms=_ms(t0))


@router.post("/open", response_model=OpenResult)
async def copilot_open(req: OpenRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Resolve the card's guideline (TNM offline; else registry or targeted fetch), then preview it for this case."""
    _require()
    t0 = time.perf_counter()
    if tnm.is_tnm(req.card.key):
        entry = _offline(req.card.key)
    else:
        done, entry = await _bounded(_resolve_fresh(req.card), OPEN_TIMEOUT_S)
        if not done:
            return OpenResult(ms=_ms(t0), error="loading")
    if entry is None:
        return OpenResult(ms=_ms(t0), error="unavailable")
    branch = await _branch_for(req.card, entry, req.findings[:6000], req.clinical_history[:2000])
    return OpenResult(entry=entry, preview=await _preview(entry, branch, req), branch=branch, ms=_ms(t0))


@router.post("/preview", response_model=OpenResult)
async def copilot_preview(req: OpenRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The preview alone (an input answered): registry or TNM only, never a fetch."""
    _require()
    t0 = time.perf_counter()
    if tnm.is_tnm(req.card.key):
        entry = _offline(req.card.key)
    else:
        row = Reg.by_key(db, req.card.key)
        entry = Reg.entry(row) if row is not None else None
        db.rollback()   # nothing pending: release the connection before the model awaits
    if entry is None:
        return OpenResult(ms=_ms(t0), error="unknown guideline")
    branch = await _branch_for(req.card, entry, req.findings[:6000], req.clinical_history[:2000])
    return OpenResult(entry=entry, preview=await _preview(entry, branch, req), branch=branch, ms=_ms(t0))


async def _ask_job(req: AskRequest, key: str | None, ctx: Context, history: list[QA]) -> AskResult:
    """Ask in its own session. A listed card the registry does not hold yet is resolved first (ask answers only on
    held keys)."""
    try:
        with SessionLocal() as db:
            if key and req.card is not None and not tnm.is_tnm(key) and Reg.by_key(db, key) is None:
                await resolve_guideline(db, req.card.model_copy(update={"key": key}))
            return await ask(db, req.question[:1000], key, ctx, history, req.finding_id)
    except Exception as e:   # ask never raises; the session or the pre-resolve might
        logger.warning("[copilot.routes] ask %s: %s", type(e).__name__, str(e)[:200])
        return A._err(key, e)


async def _loading(question: str, key: str | None, ctx: Context, history: list[QA]) -> AskResult:
    """The timeout answer: general knowledge now, flagged loading (the guideline resolves in the background)."""
    answer = STILL_LOADING
    try:
        answer = f"{STILL_LOADING} {A.FROM_GENERAL} {await A._general_answer(question, ctx, history)}".strip()
    except Exception as e:
        logger.info("[copilot.routes] loading answer without general knowledge: %s", type(e).__name__)
    return AskResult(kind="general", key=key, answer=answer, supported=False, loading=True)


@router.post("/ask", response_model=AskResult)
async def copilot_ask(req: AskRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    key = req.key or (req.card.key if req.card else None)
    ctx = Context(scan_type=req.scan_type[:300], history=req.clinical_history[:2000], findings=req.findings[:6000])
    history = req.history[-3:]
    done, res = await _bounded(_ask_job(req, key, ctx, history), ASK_TIMEOUT_S)
    if done and res is not None:
        return res
    return await _loading(req.question[:1000], key, ctx, history)


@router.post("/recommendations", response_model=RecsResult)
async def copilot_recs(req: RecsRequest, user: User = Depends(get_current_user)):
    _require()
    return await suggest(req.scan_type[:300], req.clinical_history[:2000], req.findings[:6000], req.conclusion[:2000],
                         req.applied[:10])


@router.get("/registry")
async def list_registry(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _reviewer(user)
    rows = db.query(GuidelineRegistry).order_by(GuidelineRegistry.status, GuidelineRegistry.updated_at.desc()).all()
    return [{**Reg.entry(r).model_dump(), "chunks": r.chunks or [], "aliases": r.aliases or [],
             "verified_by": r.verified_by, "verified_at": r.verified_at.isoformat() if r.verified_at else None,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in rows]


@router.post("/registry/{key}")
async def update_registry(key: str, upd: RegistryUpdate, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Verify, edit or discard (the next open re-fetches). A content edit replaces the whole content, validated."""
    _reviewer(user)
    row = Reg.by_key(db, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown guideline")
    if upd.status == "discarded":
        db.delete(row)
        db.commit()
        return {"ok": True}
    if upd.content is not None:
        row.content = upd.content.model_dump()
    if upd.status == "verified":
        row.status = "verified"
        row.verified_by = user.email
        row.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif upd.status == "draft":
        row.status = "draft"
        row.verified_by = None
        row.verified_at = None
    db.commit()
    return {"ok": True}
