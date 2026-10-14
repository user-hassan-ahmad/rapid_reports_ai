"""Hybrid stack endpoints (spec §3, §5). On unless the one switch RR_STACK is "0" (integration spec §9.1). Reviewers (RR_STACK_REVIEWERS, comma-separated
emails) approve, edit or reject reconciled families."""
from __future__ import annotations

import json
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..database.crud import get_template
from ..database.models import DictationStackLog, StackSchemaFamily, StackSlimSheet, User
from ..stack_switch import stack_allowed  # noqa: F401 (re-exported)
from ..template_decisions import clean_ledger
from ..template_sheet_structure import generation_stamp, sheet_hash
from .schemas import Region, groups_for, pill_regions
from .items import Item, ItemsResult, Referral, recheck as items_recheck, update as items_update
from .jev_stack import MATERIAL_MIN, STALE_MIN, UNFINISHED_MIN, ask_material, ask_stale, ask_unfinished
from .normals import AssumedResult, assumed as assumed_normals
from .structures import structure_normals
from .sex_screen import screen_normals
from .slim_sheet import clean_sentences, get_or_make as slim_get_or_make
from .template import (template_normal_labels, template_region_normals, template_required_values, template_structure,
                       template_suppressions)
from .values import ValuesResult, smart_fill
from .draft import DraftResult, draft_conclusion
from .habits import template_habits
from .service import GroupResult, SchemaResult, close_update, group_update, resolve_schema
from .units import StackUnit, sentences as split_sentences
from .resolution import TokenError, mint, verify as verify_token
from .gate_model import GateRecord
from .findings import FromUnits

import logging
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/canvas/stack", tags=["hybrid-stack"])

MAX_REGION_TEXT = 4000        # characters of one region's grouped sentences sent to Jev
MAX_NORMALS_PER_REGION = 16   # conversion lab 2026-10-12: 8 silently cut mandatory negatives in long paragraphs


def _require() -> None:
    if not stack_allowed():
        raise HTTPException(status_code=404, detail="Not Found")


class SchemaRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    template_id: str | None = None
    protocol_id: str | None = None          # protocol library pick (spec §3); phases/laterality complete it
    phases: list[str] | None = None
    laterality: str | None = None


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
    template_id: str | None = None                       # its confirmed findings-triggered habits are asked


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
    removed: list[str] = Field(default_factory=list)
    owned: list[str] = Field(default_factory=list)       # the rows' sentences: a row owns its check
    template_id: str | None = None                       # its context rules and normal labels apply
    clinical_history: str = ""                           # a context rule's condition is judged on it too
    region_text: dict[str, str] = Field(default_factory=dict)   # region -> its grouped sentences; missing: nothing
    # The session's context-rule decision, as the first reply returned it (review R5); None: decide it now.
    rules: dict[str, float] | None = None
    confirm: bool = False   # at Confirm: every condition is re-asked with the dictation


class DraftRequest(FromUnits):
    scan_type: str = ""
    clinical_history: str = ""
    findings: str = ""   # built from units + groups when they are sent (FromUnits)


class CloseRequest(BaseModel):
    units: list[StackUnit]
    regions: list[Region]


LOG_COPILOT_MAX = 64 * 1024   # bytes of the Copilot session record, as JSON


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
    template_id: str | None = None  # template sessions: stamped with the sheet that drove them (None: quick)
    copilot: dict | None = None   # Copilot session record (scratchpad copilot spec §5.7)


class SlimRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    template_id: str | None = None
    protocol_id: str | None = None
    phases: list[str] | None = None
    laterality: str | None = None
    # The family and regions are resolved on the server (review 2026-10-12): a shared sheet is never keyed or
    # shaped by what a client sends.
    structure_key: str | None = None   # /schema's signed resolution (D26): when given, the fields above are ignored


class SlimResult(BaseModel):
    id: str | None = None
    region_normals: dict[str, list[str]] = Field(default_factory=dict)
    not_assessable: str = ""
    status: str = ""              # provisional | approved | template | template_unusable | "" (not ready)
    ready: bool = False
    level_groups: dict[str, list[str]] = Field(default_factory=dict)
    required_values: list[str] = Field(default_factory=list)   # template sessions: the LIST_MISSING items (value cluster)
    # template sessions: region -> {structure -> its sentences} for multi-structure paragraphs (the sub-pills); a
    # sentence in no structure stays with its paragraph's own pill
    region_structures: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    structure_key: str | None = None   # free text: the session token re-minted with this sheet's id (D26)


class SlimUpdate(BaseModel):
    status: Literal["approved", "provisional", "discarded"] | None = None
    region_normals: dict[str, list[str]] | None = None


class FamilyUpdate(BaseModel):
    status: Literal["approved", "rejected", "provisional"]
    regions: list[Region] | None = None


def _library_pick(protocol_id, phases, laterality):
    """The resolved pick, or None when the request is free text or the library is off. A bad pick is a 422."""
    from .protocol_library.bundle import get_bundle, library_allowed
    from .protocol_library.compose import PickError, resolve
    if not protocol_id or not library_allowed():
        return None, None
    b = get_bundle()
    try:
        return b, resolve(b, protocol_id, phases, laterality)
    except PickError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/schema", response_model=SchemaResult)
async def stack_schema(req: SchemaRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    # Resolution order (integration contract §8.1): template structure, else the library pick, else free text.
    # The resolution is minted into structure_key (D26): /slim-sheet and Generate read it, never re-resolve.
    if req.template_id:
        t = get_template(db, req.template_id, str(user.id))   # the string id as a UUID, owner only
        if t is None:
            raise HTTPException(status_code=404, detail="Template not found.")
        structure = template_structure(t.template_config)
        if structure is None:   # D15: refused, never a free-text session that Generate would then refuse
            raise HTTPException(status_code=422,
                                detail="This template can't be used with the scratchpad. Create a fresh one.")
        res = await resolve_schema(req.scan_type, req.clinical_history, structure, db)
        res.structure_key = mint({"src": "template", "tid": str(t.id),
                                  "sh": sheet_hash((t.template_config or {}).get("skill_sheet", "") or "")})
        return res
    b, pick = _library_pick(req.protocol_id, req.phases, req.laterality)
    if pick is not None:
        return SchemaResult(regions=pick.regions, groups=groups_for(pick.regions), pills=pill_regions(pick.regions),
                            source="library", key=pick.schema_key, quiet=pick.quiet,
                            protocol={"id": pick.entry_id, "display_name": pick.display_name,
                                      "scan_type_line": pick.scan_type_line, "phases": pick.phases,
                                      "laterality": pick.laterality},
                            structure_key=mint({"src": "library", "eid": pick.entry_id, "ph": pick.phases,
                                                "lat": pick.laterality, "bv": b.version, "sid": pick.sheet_id}))
    res = await resolve_schema(req.scan_type, req.clinical_history, None, db)
    res.structure_key = mint({"src": "free", "scan": req.scan_type[:300], "sk": res.key, "sid": None})
    return res


@router.post("/group", response_model=GroupResult)
async def stack_group(req: GroupRequest, user: User = Depends(get_current_user)):
    _require()
    return await group_update(req.scan_type, req.text, req.regions, req.previous)


@router.post("/items", response_model=ItemsResult)
async def stack_items(req: ItemsRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    extra = {}
    if req.template_id:
        try:
            t = get_template(db, req.template_id, str(user.id))   # the string id as a UUID, owner only
            st = template_structure(t.template_config) if t is not None else None
            # only habits the radiologist confirmed are asked (Hassan H3: a line with no entry is inactive)
            habits = template_habits(st, clean_ledger((t.template_config or {}).get("decisions"))) if st is not None else []
        except Exception as e:  # noqa: BLE001 -- fail-soft: no template rows, generic rows as usual
            logger.warning("[stack.items] template %s habits not read: %s: %s", req.template_id, type(e).__name__,
                           str(e)[:200])
            habits = []
        if habits:
            extra["habits"] = habits
    return await items_update(req.scan_type, req.clinical_history, req.regions[:40], req.dictation,
                              req.abnormal[:40], req.not_assessable[:2000], req.removed[:50], req.tapped[:20],
                              req.referrals[:2] if req.referrals is not None else None, req.review, **extra)


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


class UnfinishedRequest(BaseModel):
    text: str = ""


@router.post("/unfinished")
async def stack_unfinished(req: UnfinishedRequest, user: User = Depends(get_current_user)):
    """Unfinished sentences, judged by Jev (the scratchpad's only check for them): flags in the shape of
    /api/dictation/check (kind truncation, severity high, offsets into `text`). Fails open: no flags."""
    _require()
    text = req.text[:20000]
    found, at = [], 0
    for s in split_sentences(text)[:80]:
        k = text.find(s, at)
        if k < 0:
            continue
        found.append((s, k))
        at = k + len(s)
    try:
        scores = await ask_unfinished([s for s, _ in found])
    except Exception as e:
        logger.warning("[stack.unfinished] %s: %s", type(e).__name__, str(e)[:200])
        return {"flags": []}
    return {"flags": [{"kind": "truncation", "severity": "high", "excerpt": s, "message": "The sentence stops before it is finished.",
                       "start": k, "end": k + len(s), "blocking": True, "score": round(p, 3)}
                      for (s, k), p in zip(found, scores) if p >= UNFINISHED_MIN]}


@router.post("/assumed", response_model=AssumedResult)
async def stack_assumed(req: AssumedRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    normals = {r: s[:MAX_NORMALS_PER_REGION] for r, s in list(req.region_normals.items())[:40]}
    owned = list(dict.fromkeys(o for o in req.owned if o.strip()))[:100]   # the client sends current rows first
    suppressions: list[tuple[str, str]] = []
    labels: dict[str, str] = {}
    scan_type = ""
    if req.template_id:
        t = get_template(db, req.template_id, str(user.id))   # the string id as a UUID, owner only
        st = template_structure(t.template_config) if t is not None else None
        if st is not None:
            suppressions, labels = template_suppressions(st), template_normal_labels(st)
        if t is not None and isinstance(t.template_config, dict):
            scan_type = str(t.template_config.get("scan_type") or "")[:300]
    # Seam 21: every context-rule decision is condition_state's, on the template's scan type; `rules` is the
    # session's cached answer on the history and `confirm` re-decides every condition with the dictation.
    return await assumed_normals(req.dictation, normals, req.abnormal, req.removed[:50], owned,
                                 suppressions=suppressions,
                                 clinical_history=req.clinical_history[:2000], labels=labels,
                                 region_text={r: t[:MAX_REGION_TEXT] for r, t in list(req.region_text.items())[:40]},
                                 rules=None if req.rules is None else dict(list(req.rules.items())[:100]),
                                 confirm=req.confirm, scan_type=scan_type,
                                 sides=not req.template_id)   # "Which side?": quick only (side brief 2026-10-14)



class ValuesRequest(BaseModel):
    dictation: str = ""
    template_id: str | None = None   # the items are read from the template on the server, never sent by the client


@router.post("/values", response_model=ValuesResult)
async def stack_values(req: ValuesRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The value cluster's smart fill (requirements spec 2026-10-12 part 1): the template's required values, each
    filled from the dictation (Jev says stated and where; code reads the number) or open. Never errors: a Jev
    failure leaves every value open."""
    _require()
    items: list[str] = []
    if req.template_id:
        t = get_template(db, req.template_id, str(user.id))   # the string id as a UUID, owner only
        st = template_structure(t.template_config) if t is not None else None
        if st is not None:
            items = template_required_values(st)
    return await smart_fill(req.dictation[:20000], items)


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
    if req.copilot is not None and len(json.dumps(req.copilot, ensure_ascii=False).encode()) > LOG_COPILOT_MAX:
        raise HTTPException(status_code=413, detail="Copilot record too large")
    row = db.query(DictationStackLog).filter_by(user_id=user.id, session_id=req.session_id).first()
    if row is None:
        row = DictationStackLog(user_id=user.id, session_id=req.session_id)
        db.add(row)
    for k, v in req.model_dump(exclude_unset=True).items():
        if k in ("session_id", "template_id") or (k in ("gate", "report_id", "copilot") and v is None):
            continue  # a partial log (the report id alone) changes only what it sends; a gate is never erased
        setattr(row, k, v)
    if req.template_id and row.stamp is None:   # pinned to the sheet the session started with
        try:
            t = get_template(db, req.template_id, str(user.id))   # owner only; an unknown template stamps nothing
            stamp = generation_stamp(str(t.id), t.template_config, "scratchpad") if t is not None else None
            if stamp is not None:
                row.template_id, row.stamp = str(t.id), stamp
        except Exception as e:  # noqa: BLE001 -- the stamp is evidence; the log row always lands
            logger.warning("stack log %s: stamp failed: %s", req.session_id, e)
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
    tok = None
    if req.structure_key:   # the session resolution (D26): the request's scan type, template and pick are ignored
        try:
            tok = verify_token(req.structure_key)
        except TokenError:
            raise HTTPException(status_code=400, detail="Set up the workspace again.")
        if tok["src"] == "template":
            req = req.model_copy(update={"template_id": tok["tid"], "protocol_id": None})
        elif tok["src"] == "library":
            req = req.model_copy(update={"template_id": None, "protocol_id": tok["eid"], "phases": tok["ph"],
                                         "laterality": tok["lat"]})
        else:
            req = req.model_copy(update={"template_id": None, "protocol_id": None, "scan_type": tok["scan"]})
    # The same order as /schema (contract §8.1): template structure, else the library pick, else free text.
    if req.template_id:
        t = get_template(db, req.template_id, str(user.id))   # the string id as a UUID, owner only
        st = template_structure(t.template_config) if t is not None else None
        if st is None:   # Generate takes today's template path; the scratchpad says so
            return SlimResult(status="template_unusable")
        return SlimResult(region_normals=template_region_normals(st), required_values=template_required_values(st),
                          region_structures=await structure_normals(st), status="template", ready=True)
    b, pick = _library_pick(req.protocol_id, req.phases, req.laterality)
    if pick is not None:
        from .protocol_library.compose import compose_sheet
        s = compose_sheet(b, pick)
        return SlimResult(id=s.id, region_normals=s.region_normals, not_assessable=s.not_assessable,
                          status="library", ready=True, level_groups=s.level_groups)
    if not req.scan_type.strip():
        return SlimResult()
    schema = await resolve_schema(req.scan_type[:300], req.clinical_history[:2000], None, db)
    if not schema.regions:
        return SlimResult()
    row = await slim_get_or_make(db, req.scan_type[:300], schema.key, schema.regions)
    if row is None:
        return SlimResult()
    return SlimResult(id=str(row.id), region_normals=row.region_normals or {}, not_assessable=row.not_assessable or "",
                      status=row.status, ready=True,
                      structure_key=mint({**tok, "sid": str(row.id)}) if tok is not None else None)


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
        cleaned = {k: kept for k, v in upd.region_normals.items() if (kept := clean_sentences(v))}
        row.region_normals, flagged = await screen_normals(cleaned)
        if flagged:
            logger.info("[stack.slim] %d sex-specific borderline sentence(s) kept for review: %r", len(flagged), flagged[:5])
    db.commit()
    return {"ok": True}


from .protocol_library.routes import router as _protocols_router  # noqa: E402
router.include_router(_protocols_router)


class StackGenerateRequest(BaseModel):
    """One Generate for quick and template stack sessions (integration spec §5)."""
    kind: Literal["quick", "template"]
    template_id: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)   # template inputs other than FINDINGS
    scan_type: str = ""
    history: str = ""
    structure_key: str   # /schema's signed session resolution (D26): the template, library entry or slim sheet
    units: list[StackUnit]
    groups: list[str]
    gate: GateRecord


@router.post("/generate")
async def stack_generate(req: StackGenerateRequest, current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    _require()
    from sse_starlette.sse import EventSourceResponse
    from . import report as SR

    async def stream():
        try:
            async for ev in SR.run(req, current_user, db):
                yield {"event": ev["event"], "data": json.dumps(ev["payload"])}
        except SR.StackError as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
        except Exception:  # noqa: BLE001 -- never a silent fallback to the old flow
            logger.exception("[stack.generate] failed")
            yield {"event": "error", "data": json.dumps({"message": "Report generation failed. Please try again."})}

    return EventSourceResponse(stream())
