"""Copilot endpoints (spec §5). On with the hybrid stack unless RR_STACK_COPILOT=0 (kill switch). Reviewers
(RR_STACK_REVIEWERS) verify, edit or discard registry entries.

A targeted fetch can outlast a request: /open and /ask run it in a task with its own session and wait a bounded time.
On timeout the request answers "loading" and the task carries on, so the registry still grows and a retry hits it.
No request session is handed to that task (it closes when the request ends).

Requests are capped and client cards validated here (request models), so the internal types stay unconstrained.
Supplements are stripped from every non-reviewer response: the registry is shared, and only reviewers read them."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import weakref
from datetime import datetime, timezone
from typing import Annotated, Any, Coroutine, Literal, Mapping, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy.orm import Session, defer

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

OPEN_TIMEOUT_S = 60.0      # the frontend's /open fetch timeout must be longer (>= 90 s): it waits for this answer
PREVIEW_TIMEOUT_S = 25.0   # branch pick + preview together; on timeout the criteria show with no Apply
ASK_TIMEOUT_S = 45.0
FOREGROUND_CONCURRENCY = 8  # resolves and ask jobs in flight at once, per event loop
STILL_LOADING = "The guideline is still loading; ask again shortly."
_KEY = re.compile(r"^[a-z0-9-]+(@[0-9a-z.]{0,24})?$")
KEY_MAX = 128

_BG: set[asyncio.Task] = set()   # jobs outliving their request (strong refs until done)
_SEMS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
T = TypeVar("T")


def copilot_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("RR_STACK_COPILOT", "1") != "0" and stack_allowed(env)


def _require() -> None:
    if not copilot_allowed():
        raise HTTPException(status_code=404, detail="Not Found")


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _sem() -> asyncio.Semaphore:
    """Per event loop (a semaphore binds to one), as fetch._sem."""
    return _SEMS.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(FOREGROUND_CONCURRENCY))


def _bg_done(task: asyncio.Task) -> None:
    _BG.discard(task)
    if not task.cancelled() and task.exception() is not None:
        e = task.exception()
        logger.warning("[copilot.routes] background %s: %s", type(e).__name__, str(e)[:200])


async def _bounded(job: Coroutine[Any, Any, T], timeout: float) -> tuple[bool, T | None]:
    """(done, result). The job runs as a task the timeout never cancels (shielded): it finishes in the background."""
    task = asyncio.get_running_loop().create_task(job)
    _BG.add(task)
    task.add_done_callback(_bg_done)
    try:
        return True, await asyncio.wait_for(asyncio.shield(task), timeout)
    except asyncio.TimeoutError:
        return False, None


def _public(entry: Entry | None) -> Entry | None:
    """The entry without supplements: they are reviewer material only (spec §2.15)."""
    if entry is None or not entry.content.supplements:
        return entry
    return entry.model_copy(update={"content": entry.content.model_copy(update={"supplements": []})})


# ── request models: caps and client-card validation ─────────────────────────────────────────────────────────────

def _s(n: int):
    return Annotated[str, StringConstraints(max_length=n)]


class PublicationIn(BaseModel):
    title: _s(300) = ""
    body: _s(120) = ""
    year: _s(8) = ""


class CardIn(BaseModel):
    """A card as the client sends it back (Card, capped)."""
    key: _s(KEY_MAX)
    name: _s(120)
    version: _s(24) = ""
    finding_id: _s(40)
    why: _s(300) = ""
    branch: _s(120) = ""
    skeleton: list[_s(120)] = Field(default_factory=list, max_length=12)
    publication: PublicationIn = Field(default_factory=PublicationIn)
    known: bool = False
    status: Literal["draft", "verified", "new"] = "new"

    def card(self) -> Card:
        return Card(**self.model_dump())


class FindingIn(BaseModel):
    id: _s(40)
    text: _s(1000)


class QAIn(BaseModel):
    question: _s(2000)
    answer: _s(2000)


def _check_card(card: CardIn) -> None:
    """400 unless the key is well formed and, when it is not TNM and not already held, is the key the card's own
    name and version make: a client may not plant an arbitrary key in the shared registry."""
    if tnm.is_tnm(card.key):
        return
    if len(card.key) > KEY_MAX or not _KEY.match(card.key):
        raise HTTPException(status_code=400, detail="Bad guideline key")
    if card.key == Reg.make_key(card.name, card.version):
        return
    with SessionLocal() as db:
        held = Reg.by_key(db, card.key) is not None
    if not held:
        raise HTTPException(status_code=400, detail="Guideline key does not match its name and version")


class MatchRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    findings: list[FindingIn] = Field(default_factory=list, max_length=20)


class MatchResult(BaseModel):
    cards: list[Card] = Field(default_factory=list)
    ms: int = 0


class OpenRequest(BaseModel):
    card: CardIn
    findings: str = ""
    clinical_history: str = ""
    answered: dict[str, str] = Field(default_factory=dict)

    @field_validator("answered")
    @classmethod
    def _cap_answered(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 20 or any(len(k) > 60 or len(x) > 200 for k, x in v.items()):
            raise ValueError("answered: at most 20 inputs, ids up to 60 and values up to 200 characters")
        return v


class OpenResult(BaseModel):
    entry: Entry | None = None
    preview: Preview | None = None
    branch: str = ""              # the branch previewed (a branchless card's is chosen here)
    ms: int = 0
    error: str | None = None      # "unavailable" (nothing fetched), "loading" (still fetching), "unknown guideline"


class AskRequest(BaseModel):
    question: _s(1000)
    key: _s(KEY_MAX) | None = None
    card: CardIn | None = None    # the listed card asked on (its key == key): resolved first when the registry lacks it
    finding_id: _s(40) = ""
    scan_type: str = ""
    clinical_history: str = ""
    findings: str = ""
    history: list[QAIn] = Field(default_factory=list, max_length=6)


class RecsRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    findings: str = ""
    conclusion: str = ""
    applied: list[_s(300)] = Field(default_factory=list, max_length=10)


class RegistryUpdate(BaseModel):
    status: Literal["verified", "draft", "discarded"] | None = None
    content: GuidelineContent | None = None   # a whole-content edit; also how a reviewer verifies a supplement


# ── open / preview ──────────────────────────────────────────────────────────────────────────────────────────────

def _default_branch(card: Card, entry: Entry) -> str:
    if card.branch:
        return card.branch
    if entry.content.branch(OVERVIEW):
        return OVERVIEW
    return next((b.name for b in entry.content.checked()), "")


async def _branch_for(card: Card, entry: Entry, findings: str, history: str) -> str:
    """The card's branch; for a branchless card (ask-originated), as ask does: Jev's pick among the checked branches,
    else the Overview when stored, else the first checked branch."""
    if not card.branch and entry.content.checked():
        picked = await M.pick_branch(findings, entry, history)
        if picked:
            return picked
    return _default_branch(card, entry)


async def _branch_and_preview(card: Card, entry: Entry, req: OpenRequest) -> tuple[str, Preview]:
    """Fail open, bounded: on a failure or PREVIEW_TIMEOUT_S the criteria still show, with no Apply. Only the
    branch's real inputs are passed as answered."""
    findings, history = req.findings[:6000], req.clinical_history[:2000]

    async def run() -> tuple[str, Preview]:
        branch = await _branch_for(card, entry, findings, history)
        b = entry.content.branch(branch)
        ids = {i.id for i in b.inputs} if b else set()
        answered = {k: v for k, v in req.answered.items() if k in ids}
        return branch, await preview(entry, branch, findings, history, answered)
    try:
        return await asyncio.wait_for(run(), PREVIEW_TIMEOUT_S)
    except Exception as e:   # TimeoutError included
        logger.warning("[copilot.routes] preview %s: %s", type(e).__name__, str(e)[:200])
        return _default_branch(card, entry), Preview()


async def _resolve_fresh(card: Card) -> Entry | None:
    """Fail open: any failure (session, resolve) is logged and reads as nothing fetched."""
    try:
        async with _sem():
            with SessionLocal() as db:
                return await resolve_guideline(db, card)
    except Exception as e:
        logger.warning("[copilot.routes] resolve %s %s: %s", card.key, type(e).__name__, str(e)[:200])
        return None


def _offline(key: str) -> Entry | None:
    site = tnm.site_for(key)
    return tnm.entry(site) if site else None


@router.post("/match", response_model=MatchResult)
async def copilot_match(req: MatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    t0 = time.perf_counter()
    findings = [Finding(id=f.id, text=f.text) for f in req.findings]
    cards = await match(db, req.scan_type[:300], req.clinical_history[:2000], findings)
    return MatchResult(cards=cards, ms=_ms(t0))


@router.post("/open", response_model=OpenResult)
async def copilot_open(req: OpenRequest, user: User = Depends(get_current_user)):
    """Resolve the card's guideline (TNM offline; else registry or targeted fetch), then preview it for this case."""
    _require()
    _check_card(req.card)
    t0 = time.perf_counter()
    card = req.card.card()
    if tnm.is_tnm(card.key):
        entry = _offline(card.key)
    else:
        done, entry = await _bounded(_resolve_fresh(card), OPEN_TIMEOUT_S)
        if not done:
            return OpenResult(ms=_ms(t0), error="loading")
    if entry is None:
        return OpenResult(ms=_ms(t0), error="unavailable")
    branch, prev = await _branch_and_preview(card, entry, req)
    return OpenResult(entry=_public(entry), preview=prev, branch=branch, ms=_ms(t0))


@router.post("/preview", response_model=OpenResult)
async def copilot_preview(req: OpenRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The preview alone (an input answered): registry or TNM only, never a fetch."""
    _require()
    t0 = time.perf_counter()
    card = req.card.card()
    if tnm.is_tnm(card.key):
        entry = _offline(card.key)
    else:
        row = Reg.by_key(db, card.key)
        entry = Reg.entry(row) if row is not None else None
        db.rollback()   # nothing pending: release the connection before the model awaits
    if entry is None:
        return OpenResult(ms=_ms(t0), error="unknown guideline")
    branch, prev = await _branch_and_preview(card, entry, req)
    return OpenResult(entry=_public(entry), preview=prev, branch=branch, ms=_ms(t0))


# ── ask ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def _ask_job(req: AskRequest, ctx: Context, history: list[QA], abandoned: asyncio.Event) -> AskResult:
    """Ask in its own session. The listed card asked on (its key is the ask's key), when the registry does not hold it
    yet, is resolved first: ask answers only on held keys."""
    key = req.key
    card = req.card.card() if req.card is not None and req.card.key == key else None
    try:
        async with _sem():
            with SessionLocal() as db:
                if card is not None and not tnm.is_tnm(card.key) and Reg.by_key(db, card.key) is None:
                    await resolve_guideline(db, card)
                return await ask(db, req.question, key, ctx, history, req.finding_id, abandoned)
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
    return AskResult(kind="card" if key else "general", key=key, answer=answer, supported=False, loading=True)


@router.post("/ask", response_model=AskResult)
async def copilot_ask(req: AskRequest, user: User = Depends(get_current_user)):
    _require()
    if req.card is not None and req.card.key == req.key:
        _check_card(req.card)
    ctx = Context(scan_type=req.scan_type[:300], history=req.clinical_history[:2000], findings=req.findings[:6000])
    history = [QA(question=h.question, answer=h.answer) for h in req.history[-3:]]
    abandoned = asyncio.Event()
    done, res = await _bounded(_ask_job(req, ctx, history, abandoned), ASK_TIMEOUT_S)
    if done and res is not None:
        return res.model_copy(update={"entry": _public(res.entry)})
    abandoned.set()   # the job finishes its resolve (the registry grows) and stops there
    return await _loading(req.question, req.key, ctx, history)


@router.post("/recommendations", response_model=RecsResult)
async def copilot_recs(req: RecsRequest, user: User = Depends(get_current_user)):
    _require()
    return await suggest(req.scan_type[:300], req.clinical_history[:2000], req.findings[:6000], req.conclusion[:2000],
                         list(req.applied))


# ── reviewer ────────────────────────────────────────────────────────────────────────────────────────────────────

def _review_row(r: GuidelineRegistry, chunks: bool) -> dict:
    out = {**Reg.entry(r).model_dump(), "aliases": r.aliases or [], "verified_by": r.verified_by,
           "verified_at": r.verified_at.isoformat() if r.verified_at else None,
           "updated_at": r.updated_at.isoformat() if r.updated_at else None}
    if chunks:
        out["chunks"] = r.chunks or []
    return out


@router.get("/registry")
async def list_registry(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every entry, supplements included, without chunks (GET /registry/{key} has them)."""
    _reviewer(user)
    rows = (db.query(GuidelineRegistry).options(defer(GuidelineRegistry.chunks))
            .order_by(GuidelineRegistry.status, GuidelineRegistry.updated_at.desc()).all())
    return [_review_row(r, chunks=False) for r in rows]


@router.get("/registry/{key}")
async def get_registry(key: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _reviewer(user)
    row = Reg.by_key(db, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown guideline")
    return _review_row(row, chunks=True)


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
