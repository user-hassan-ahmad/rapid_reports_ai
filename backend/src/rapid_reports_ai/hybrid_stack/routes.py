"""Hybrid stack endpoints (spec §3, §5). On when the dictation package is allowed and the kill
switch RR_HYBRID_STACK is not "0" (default on). Reviewers (RR_STACK_REVIEWERS, comma-separated
emails) approve, edit or reject reconciled families."""
from __future__ import annotations

import os
from typing import Literal, Mapping

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..database.models import DictationStackLog, StackSchemaFamily, StackSlimSheet, Template, User
from ..dictation_v2 import v2_allowed
from ..template_sheet_structure import fresh
from .schemas import Region
from .items import Item, ItemsResult, Referral, recheck as items_recheck, update as items_update
from .jev_stack import MATERIAL_MIN, STALE_MIN, ask_material, ask_stale
from .normals import AssumedResult, assumed as assumed_normals
from .slim_sheet import clean_sentences, get_or_make as slim_get_or_make
from .template import template_region_normals
from .draft import DraftResult, draft_conclusion
from .service import GroupResult, SchemaResult, close_update, group_update, resolve_schema
from .units import StackUnit

import logging
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/canvas/stack", tags=["hybrid-stack"])


def stack_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("RR_HYBRID_STACK", "1") != "0" and v2_allowed(env)


def shadow_rate(env: Mapping[str, str] = os.environ) -> float:
    """Share of sessions that also build the old Structured text once, at session end (shadow)."""
    try:
        return min(1.0, max(0.0, float(env.get("RR_STACK_SHADOW_RATE", "0.25"))))
    except ValueError:
        return 0.25


def _require() -> None:
    if not stack_allowed():
        raise HTTPException(status_code=404, detail="Not Found")


class SchemaRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    template_id: str | None = None


class GroupRequest(BaseModel):
    scan_type: str = ""
    text: str = ""
    regions: list[Region]
    previous: list[StackUnit] = Field(default_factory=list)


class ItemsRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    regions: list[str] = Field(default_factory=list)
    dictation: str = ""
    abnormal: list[str] = Field(default_factory=list)   # the abnormal sentences: the writer's cache key
    not_assessable: str = ""
    removed: list[str] = Field(default_factory=list)    # sentences the radiologist removed: never offered again
    tapped: list[str] = Field(default_factory=list)     # sentences answered with a tap: re-checked for contradiction
    referrals: list[Referral] | None = None              # the session's fixed referral rows (None: first call)
    review: bool = False                                 # the end-of-dictation review (reasoning low)


class RecheckRequest(BaseModel):
    dictation: str = ""
    rows: list[Item] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    tapped: list[str] = Field(default_factory=list)


class ChangedRequest(BaseModel):
    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)


class StaleRequest(BaseModel):
    conclusion: str = ""
    findings: list[str] = Field(default_factory=list)


class AssumedRequest(BaseModel):
    dictation: str = ""
    region_normals: dict[str, list[str]] = Field(default_factory=dict)
    abnormal: list[str] = Field(default_factory=list)
    dictated_normal: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    owned: list[str] = Field(default_factory=list)       # the rows' sentences: a row owns its check
    touched: list[str] = Field(default_factory=list)     # regions those rows (and removals) concern


class DraftRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    findings: str


class CloseRequest(BaseModel):
    units: list[StackUnit]
    regions: list[Region]


class LogRequest(BaseModel):
    session_id: str
    scan_type: str | None = None
    schema_key: str | None = None
    schema_source: str | None = None
    provisional: bool = False
    units: list[dict] = Field(default_factory=list)
    pills_derived: list[str] = Field(default_factory=list)
    pills_jev: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    structured_text: str = ""
    manual_moves: int = 0
    latency_ms: dict = Field(default_factory=dict)
    gate: dict | None = None      # v2 §5: the confirmed record (None: not confirmed)
    report_id: str | None = None  # v2: set once Generate returns
    copilot: dict | None = None   # Copilot session record (scratchpad copilot spec §5.7)


class SlimRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    template_id: str | None = None
    # The family and regions are resolved on the server (review 2026-10-12): a shared sheet is never keyed or
    # shaped by what a client sends.


class SlimResult(BaseModel):
    id: str | None = None
    region_normals: dict[str, list[str]] = Field(default_factory=dict)
    not_assessable: str = ""
    status: str = ""              # provisional | approved | template | "" (not ready)
    ready: bool = False


class SlimUpdate(BaseModel):
    status: Literal["approved", "provisional", "discarded"] | None = None
    region_normals: dict[str, list[str]] | None = None


class FamilyUpdate(BaseModel):
    status: Literal["approved", "rejected", "provisional"]
    regions: list[Region] | None = None


@router.post("/schema", response_model=SchemaResult)
async def stack_schema(req: SchemaRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    structure = None
    if req.template_id:
        t = db.query(Template).filter(Template.id == req.template_id, Template.user_id == user.id).first()
        structure = fresh(t.template_config or {}) if t is not None else None
    return await resolve_schema(req.scan_type, req.clinical_history, structure, db)


@router.post("/group", response_model=GroupResult)
async def stack_group(req: GroupRequest, user: User = Depends(get_current_user)):
    _require()
    return await group_update(req.scan_type, req.text, req.regions, req.previous)


@router.post("/items", response_model=ItemsResult)
async def stack_items(req: ItemsRequest, user: User = Depends(get_current_user)):
    _require()
    return await items_update(req.scan_type, req.clinical_history, req.regions[:40], req.dictation,
                              req.abnormal[:40], req.not_assessable[:2000], req.removed[:50], req.tapped[:20],
                              req.referrals[:2] if req.referrals is not None else None, req.review)


@router.post("/recheck", response_model=ItemsResult)
async def stack_recheck(req: RecheckRequest, user: User = Depends(get_current_user)):
    _require()
    return await items_recheck(req.dictation, req.rows[:12], req.removed[:50], req.tapped[:20])


@router.post("/changed")
async def stack_changed(req: ChangedRequest, user: User = Depends(get_current_user)):
    """Whether the abnormal findings changed materially since the last review (Jev; fails to material, so a failure
    re-runs the review rather than skipping it)."""
    _require()
    if [" ".join(b.split()) for b in req.before] == [" ".join(a.split()) for a in req.after]:
        return {"material": False, "score": 0.0}
    try:
        score = await ask_material(req.before[:40], req.after[:40])
    except Exception as e:
        logger.warning("[stack.changed] %s: %s", type(e).__name__, str(e)[:200])
        return {"material": True, "score": None}
    return {"material": score >= MATERIAL_MIN, "score": round(score, 3)}


@router.post("/conclusion-check")
async def stack_conclusion_check(req: StaleRequest, user: User = Depends(get_current_user)):
    """Whether a radiologist's own conclusion no longer reflects the findings (Jev). Fails quiet: no note."""
    _require()
    if not req.conclusion.strip() or not req.findings:
        return {"stale": False, "score": 0.0}
    try:
        score = await ask_stale(req.conclusion[:2000], req.findings[:60])
    except Exception as e:
        logger.warning("[stack.conclusion-check] %s: %s", type(e).__name__, str(e)[:200])
        return {"stale": False, "score": None}
    return {"stale": score >= STALE_MIN, "score": round(score, 3)}


@router.post("/assumed", response_model=AssumedResult)
async def stack_assumed(req: AssumedRequest, user: User = Depends(get_current_user)):
    _require()
    normals = {r: s[:8] for r, s in list(req.region_normals.items())[:40]}
    owned = list(dict.fromkeys(o for o in req.owned if o.strip()))[:100]   # the client sends current rows first
    return await assumed_normals(req.dictation, normals, req.abnormal, req.dictated_normal, req.removed[:50],
                                 owned, req.touched[:40])


@router.post("/draft", response_model=DraftResult)
async def stack_draft(req: DraftRequest, user: User = Depends(get_current_user)):
    _require()
    return await draft_conclusion(req.scan_type, req.clinical_history, req.findings)


@router.post("/close", response_model=GroupResult)
async def stack_close(req: CloseRequest, user: User = Depends(get_current_user)):
    _require()
    return await close_update(req.units, req.regions)


@router.post("/debug")
async def stack_debug(payload: dict, user: User = Depends(get_current_user)):
    """Local debugging only (RR_STACK_DEBUG=1): a frontend snapshot written to the server log, never stored."""
    _require()
    if os.environ.get("RR_STACK_DEBUG") != "1":
        raise HTTPException(status_code=404, detail="Not Found")
    import json
    logger.warning("[stack.debug] %s", json.dumps(payload, ensure_ascii=False)[:12000])
    return {"ok": True}


@router.post("/log")
async def stack_log(req: LogRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    row = db.query(DictationStackLog).filter_by(user_id=user.id, session_id=req.session_id).first()
    if row is None:
        row = DictationStackLog(user_id=user.id, session_id=req.session_id)
        db.add(row)
    for k, v in req.model_dump(exclude_unset=True).items():
        if k == "session_id" or (k in ("gate", "report_id", "copilot") and v is None):
            continue  # a partial log (the report id alone) changes only what it sends; a gate is never erased
        setattr(row, k, v)
    db.commit()
    return {"ok": True}


def _reviewer(user: User) -> None:
    allowed = {e.strip().lower() for e in os.environ.get("RR_STACK_REVIEWERS", "").split(",") if e.strip()}
    if (user.email or "").lower() not in allowed:
        raise HTTPException(status_code=403, detail="Not a reviewer")


@router.get("/families")
async def list_families(status: str | None = None, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _reviewer(user)
    q = db.query(StackSchemaFamily)
    if status:
        q = q.filter(StackSchemaFamily.status == status)
    return [{"key": r.key, "scan_type": r.scan_type, "regions": r.regions, "source": r.source, "status": r.status,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in q.order_by(StackSchemaFamily.updated_at.desc()).all()]


@router.post("/families/{key}")
async def update_family(key: str, upd: FamilyUpdate, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _reviewer(user)
    row = db.get(StackSchemaFamily, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown family")
    row.status = upd.status
    if upd.regions is not None:
        row.regions = [r.model_dump() for r in upd.regions]
        row.source = "admin"
    db.commit()
    return {"ok": True}


@router.post("/slim-sheet", response_model=SlimResult)
async def stack_slim_sheet(req: SlimRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The region normals and the "not assessable" list for this session (checklist spec §8). Template sessions
    read their own structure; quick sessions get the shared slim sheet (made on first use). Never errors: not
    ready means no quiet lines yet."""
    _require()
    if req.template_id:
        t = db.query(Template).filter(Template.id == req.template_id, Template.user_id == user.id).first()
        st = fresh(t.template_config or {}) if t is not None else None
        if st is None:
            return SlimResult()
        return SlimResult(region_normals=template_region_normals(st), status="template", ready=True)
    if not req.scan_type.strip():
        return SlimResult()
    schema = await resolve_schema(req.scan_type[:300], req.clinical_history[:2000], None, db)
    if not schema.regions:
        return SlimResult()
    row = await slim_get_or_make(db, req.scan_type[:300], schema.key, schema.regions)
    if row is None:
        return SlimResult()
    return SlimResult(id=str(row.id), region_normals=row.region_normals or {}, not_assessable=row.not_assessable or "",
                      status=row.status, ready=True)


def _removal_rates(db: Session, family: str, normals: dict[str, list[str]]) -> dict[str, dict]:
    """Per sheet sentence: confirmed sessions of this family, and how many removed it (the review flag)."""
    gates = [r.gate for r in db.query(DictationStackLog).filter(DictationStackLog.schema_key == family,
                                                               DictationStackLog.gate.isnot(None)).all()]
    norm = lambda x: " ".join(str(x).lower().strip().rstrip(".").split())
    removed = [{norm(x) for x in (g or {}).get("removed", [])} for g in gates]
    out = {}
    for sentences in normals.values():
        for sen in sentences:
            n = sum(1 for rs in removed if norm(sen) in rs)
            out[sen] = {"sessions": len(gates), "removed": n,
                        "flag": len(gates) >= 5 and n / max(1, len(gates)) >= 0.3}
    return out


@router.get("/slim-sheets")
async def list_slim_sheets(status: str | None = None, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    _reviewer(user)
    q = db.query(StackSlimSheet).filter(StackSlimSheet.status != "discarded")
    if status:
        q = q.filter(StackSlimSheet.status == status)
    rows = q.order_by(StackSlimSheet.updated_at.desc()).all()
    out = []
    for r in rows:
        rates = _removal_rates(db, r.family, r.region_normals or {})
        out.append({"id": str(r.id), "family": r.family, "contrast": r.contrast, "status": r.status,
                    "scan_type": r.scan_type, "model": r.model, "prompt_version": r.prompt_version,
                    "region_normals": r.region_normals, "not_assessable": r.not_assessable, "markdown": r.markdown,
                    "removal": rates, "flagged": sum(1 for v in rates.values() if v["flag"]),
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None})
    return sorted(out, key=lambda x: -x["flagged"])


@router.post("/slim-sheets/{sheet_id}")
async def update_slim_sheet(sheet_id: str, upd: SlimUpdate, user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Approve, edit sentences, or discard (the next session of that family rebuilds it)."""
    _reviewer(user)
    import uuid
    try:
        row = db.get(StackSlimSheet, uuid.UUID(sheet_id))
    except ValueError:
        row = None
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown sheet")
    if upd.status:
        row.status = upd.status
    if upd.region_normals is not None:
        row.region_normals = {k: kept for k, v in upd.region_normals.items() if (kept := clean_sentences(v))}
    db.commit()
    return {"ok": True}
