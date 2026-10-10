"""Checklist pills derived from the grouping (spec §3.7): a region is ticked when a sentence covers it."""
from __future__ import annotations

from .schemas import Region, pill_regions
from .units import StackUnit


def derived_pills(units: list[StackUnit], regions: list[Region]) -> list[str]:
    covered = {c for u in units for c in u.covers}
    return [name for name in pill_regions(regions) if name in covered]
