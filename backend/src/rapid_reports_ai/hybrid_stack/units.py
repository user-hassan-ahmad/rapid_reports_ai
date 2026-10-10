"""Sentence units of the verbatim scratchpad and sticky matching (spec §3.2, §3.5)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..spoken_format import heading_only

_SPLIT = re.compile(r"(?<=[.?!])\s+(?=\S)|\n+")


def sentences(text: str) -> list[str]:
    """Break at . ? ! followed by whitespace (decimals stay whole) and at line breaks."""
    return [s.strip() for s in _SPLIT.split(text or "") if s.strip()]


class PartOut(BaseModel):
    text: str
    group: str


class StackUnit(BaseModel):
    id: int
    text: str
    group: str | None = None
    structure: str | None = None
    attach_to: int | None = None
    parts: list[PartOut] | None = None
    covers: list[str] = Field(default_factory=list)
    pinned: bool = False  # moved by the radiologist: never changed by the server
    heading: bool = False  # only a heading cue ("Conclusion."): hidden in the view


def match_units(text: str, previous: list[StackUnit]) -> tuple[list[StackUnit], list[int]]:
    """Units for `text`. A sentence whose exact text was in `previous` keeps its placement (sticky).
    Ids are positions in the new list; links are remapped; a link to a sentence that no longer
    exists, or that would point forwards, is cut. Returns (units, ids of new sentences)."""
    pool: dict[str, list[StackUnit]] = {}
    for u in previous:
        pool.setdefault(u.text, []).append(u)
    old_to_new: dict[int, int] = {}
    units: list[StackUnit] = []
    new_ids: list[int] = []
    for i, s in enumerate(sentences(text)):
        if pool.get(s):
            old = pool[s].pop(0)
            old_to_new[old.id] = i
            units.append(old.model_copy(update={"id": i}))
        else:
            units.append(StackUnit(id=i, text=s, heading=heading_only(s) is not None))
            new_ids.append(i)
    for u in units:
        if u.attach_to is not None:
            target = old_to_new.get(u.attach_to)
            u.attach_to = target if target is not None and target < u.id else None
    return units, new_ids
