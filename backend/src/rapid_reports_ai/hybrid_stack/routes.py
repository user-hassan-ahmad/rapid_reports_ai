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
from ..database.models import DictationStackLog, StackSchemaFamily, Template, User
from ..dictation_v2 import v2_allowed
from ..template_sheet_structure import fresh
from .schemas import Region
from .chips import ChipsResult, suggest
from .draft import DraftResult, draft_conclusion
from .service import GroupResult, SchemaResult, close_update, group_update, resolve_schema
from .units import StackUnit

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
    chips: list[str] = Field(default_factory=list)  # visible chips, re-asked against the dictation (v2 §4)


class ChipsRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    region: str
    sentences: list[str]
    dictation: str = ""


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
    return await group_update(req.scan_type, req.text, req.regions, req.previous, req.chips)


@router.post("/chips", response_model=ChipsResult)
async def stack_chips(req: ChipsRequest, user: User = Depends(get_current_user)):
    _require()
    return await suggest(req.scan_type, req.clinical_history, req.region, req.sentences[:12], req.dictation)


@router.post("/draft", response_model=DraftResult)
async def stack_draft(req: DraftRequest, user: User = Depends(get_current_user)):
    _require()
    return await draft_conclusion(req.scan_type, req.clinical_history, req.findings)


@router.post("/close", response_model=GroupResult)
async def stack_close(req: CloseRequest, user: User = Depends(get_current_user)):
    _require()
    return await close_update(req.units, req.regions)


@router.post("/log")
async def stack_log(req: LogRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    row = db.query(DictationStackLog).filter_by(user_id=user.id, session_id=req.session_id).first()
    if row is None:
        row = DictationStackLog(user_id=user.id, session_id=req.session_id)
        db.add(row)
    for k, v in req.model_dump().items():
        if k == "session_id" or (k in ("gate", "report_id") and v is None):
            continue  # a later log without a gate or report id never erases one already recorded
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
