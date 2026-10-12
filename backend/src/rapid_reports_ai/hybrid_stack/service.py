"""Hybrid stack service: the region list for a session, and one grouping update (spec §3)."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel, Field

from ..database.models import StackSchemaFamily
from ..template_sheet_structure import SheetStructure
from .family import choose_family
from .gate import closing_check, conclusion_gate
from .grouper import apply_placements, place
from .pills import derived_pills
from .reconciler import reconcile
from .schemas import GENERIC_FAMILY, Region, family_keys, family_regions, groups_for, pill_regions, scan_key
from .template import template_regions
from .units import StackUnit, match_units

logger = logging.getLogger(__name__)
RECONCILE_TIMEOUT_S = 10.0


class SchemaResult(BaseModel):
    regions: list[Region]
    groups: list[str]
    pills: list[str]
    source: str            # template | approved | reconciled | family | generic
    family: str | None = None
    key: str
    provisional: bool = False


class GroupResult(BaseModel):
    units: list[StackUnit]
    new_ids: list[int]
    pills: list[str]
    gate: list[dict] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    timings_ms: dict[str, int] = Field(default_factory=dict)
    model: str | None = None  # the grouper endpoint that answered (None: no call, or all failed)
    error: str | None = None


def _result(regions: list[Region], source: str, key: str, family: str | None = None,
            provisional: bool = False) -> SchemaResult:
    return SchemaResult(regions=regions, groups=groups_for(regions), pills=pill_regions(regions), source=source,
                        family=family, key=key, provisional=provisional)


async def _jev_family(scan_type: str, history: str) -> str:
    try:
        choice, _ = await choose_family(scan_type, history)
    except Exception as e:  # fail open to the generic family
        logger.warning("[stack.family] %s: %s", type(e).__name__, e)
        return GENERIC_FAMILY
    return choice if choice in family_keys() else GENERIC_FAMILY  # "none" -> generic


async def resolve_schema(scan_type: str, history: str, structure: SheetStructure | None, db) -> SchemaResult:
    """Template structure > cached family (approved or provisional) > reconciler (once, cached) >
    Jev family (on reconciler failure or a rejected cache entry; never cached)."""
    key = scan_key(scan_type)
    if structure is not None:
        return _result(template_regions(structure), "template", key)
    row = db.get(StackSchemaFamily, key) if db is not None else None
    if row is not None and row.status in ("approved", "provisional"):
        regions = [Region(**r) for r in row.regions]
        return _result(regions, "approved" if row.status == "approved" else "reconciled", key,
                       provisional=row.status == "provisional")
    if row is not None:  # rejected: the Jev family, no new reconciliation
        fam = await _jev_family(scan_type, history)
        return _result(family_regions(fam), "family" if fam != GENERIC_FAMILY else "generic", key, family=fam)
    try:
        rec = await asyncio.wait_for(reconcile(scan_type, history), RECONCILE_TIMEOUT_S)
    except Exception as e:
        logger.warning("[stack.reconcile] %s: %s; Jev family", type(e).__name__, e)
        fam = await _jev_family(scan_type, history)
        return _result(family_regions(fam), "family" if fam != GENERIC_FAMILY else "generic", key, family=fam)
    status = "provisional"  # every reconciler result is reviewed, a kept family included (spec §3.3)
    if db is not None:
        db.merge(StackSchemaFamily(key=key, scan_type=scan_type, regions=[r.model_dump() for r in rec.regions],
                                   source=f"reconciler:family:{rec.family}" if rec.family else "reconciler:composed",
                                   status=status))
        db.commit()
    logger.info("[stack.reconcile] key=%r status=%s log=%s", key, status, rec.log)
    return _result(rec.regions, "reconciled", key, family=rec.family, provisional=True)


async def group_update(scan_type: str, text: str, regions: list[Region],
                       previous: list[StackUnit]) -> GroupResult:
    units, new_ids = match_units(text, previous)
    timings: dict[str, int] = {}
    problems: list[str] = []
    gate_log: list[dict] = []
    error, model = None, None
    if new_ids:
        t0 = time.perf_counter()
        placements, model, error = await place(scan_type, regions, units, new_ids)
        timings["grouper"] = int((time.perf_counter() - t0) * 1000)
        if placements:
            problems = apply_placements(units, placements, new_ids, groups_for(regions))
            t1 = time.perf_counter()
            gate_log = await conclusion_gate(units, new_ids)
            timings["gate"] = int((time.perf_counter() - t1) * 1000)
    return GroupResult(units=units, new_ids=new_ids, pills=derived_pills(units, regions), gate=gate_log,
                       problems=problems, timings_ms=timings, model=model, error=error)


async def close_update(units: list[StackUnit], regions: list[Region]) -> GroupResult:
    log = await closing_check(units)
    return GroupResult(units=units, new_ids=[], pills=derived_pills(units, regions), gate=[log] if log else [])
