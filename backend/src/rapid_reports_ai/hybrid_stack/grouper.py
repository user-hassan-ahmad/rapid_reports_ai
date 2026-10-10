"""The grouper: one Qwen call returns labels for new sentences; code applies them (spec §3.4, §3.5)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import CONCLUSION, GENERAL, TECHNIQUE
from .units import PartOut, StackUnit


class Part(BaseModel):
    text: str
    group: str


class Placement(BaseModel):
    id: int
    group: str
    structure: str | None = None
    attach_to: int | None = None
    parts: list[Part] = Field(default_factory=list)
    covers: list[str] = Field(default_factory=list)


class GrouperOut(BaseModel):
    placements: list[Placement]


def _norm(name: str | None, groups: list[str]) -> str | None:
    key = (name or "").strip().lower()
    return next((g for g in groups if g.lower() == key), None)


def valid_parts(sentence: str, parts: list[Part]) -> bool:
    """Parts are exact pieces of the sentence that together cover all of it, in order (only
    whitespace between them): nothing the radiologist said can fall between two parts."""
    pos = 0
    for p in parts:
        if not p.text.strip():
            return False
        i = sentence.find(p.text, pos)
        if i < 0 or sentence[pos:i].strip():
            return False
        pos = i + len(p.text)
    return len(parts) >= 2 and not sentence[pos:].strip()


def apply_placements(units: list[StackUnit], placements: list[Placement], new_ids: list[int],
                     groups: list[str]) -> list[str]:
    """Write the grouper's labels onto the new units, enforcing the invariants. Placements for
    any other unit (placed earlier, or pinned) are ignored. Returns the problems for the log."""
    problems: list[str] = []
    by_id = {u.id: u for u in units}
    wanted = {p.id: p for p in placements if p.id in new_ids}
    non_regions = {TECHNIQUE, GENERAL, CONCLUSION}
    for i in new_ids:
        u, p = by_id[i], wanted.get(i)
        if u.pinned:
            continue
        if p is None:
            u.group, u.attach_to, u.parts = GENERAL, None, None
            problems.append(f"[{i}] no placement")
            continue
        g = _norm(p.group, groups)
        if g is None:
            problems.append(f"[{i}] unknown group {p.group!r}")
            g = GENERAL
        att = p.attach_to if p.attach_to in by_id and p.attach_to < i else None
        if p.attach_to is not None and att is None:
            problems.append(f"[{i}] bad attach_to {p.attach_to}")
        parts = None
        if p.parts:
            part_groups = [_norm(x.group, groups) or GENERAL for x in p.parts]
            if valid_parts(u.text, p.parts) and len(set(part_groups)) > 1:
                parts = [PartOut(text=x.text, group=pg) for x, pg in zip(p.parts, part_groups)]
            else:
                problems.append(f"[{i}] rejected parts")
        covers = [c for c in (_norm(x, groups) for x in p.covers) if c and c not in non_regions]
        u.group = by_id[att].group if att is not None else g
        u.attach_to, u.parts, u.structure, u.covers = att, parts, (p.structure or None), list(dict.fromkeys(covers))
    return problems
