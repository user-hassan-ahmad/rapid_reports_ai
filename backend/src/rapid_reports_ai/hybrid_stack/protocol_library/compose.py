"""Resolve a picked protocol to its regions and compose its two-layer slim sheet (spec §4): the reviewed base sheet
for (sheet key, contrast class) with the phase sheet's changed normals laid over it, and a Scan Context composed in
code from the entry (phase-sheet scan lines were the noisiest output of the review)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..schemas import Region
from .bundle import Bundle, Entry, phase_id
from .match import agent_words, phase_words

LATERALITY = ("left", "right", "bilateral")


class PickError(ValueError):
    pass


class Resolution(BaseModel):
    entry_id: str
    display_name: str
    laterality: str | None = None
    phases: list[str]
    sheet_key: str
    contrast_class: str
    regions: list[Region]
    quiet: list[str] = Field(default_factory=list)
    level_groups: dict[str, list[str]] = Field(default_factory=dict)
    scan_type_line: str
    sheet_id: str
    schema_key: str


class ComposedSheet(BaseModel):
    id: str
    markdown: str
    region_normals: dict[str, list[str]] = Field(default_factory=dict)
    not_assessable: str = ""
    level_groups: dict[str, list[str]] = Field(default_factory=dict)


def resolve(bundle: Bundle, entry_id: str, phases: list[str] | None, laterality: str | None) -> Resolution:
    e = bundle.entry(entry_id or "")
    if e is None:
        raise PickError(f"unknown protocol {entry_id!r}")
    ph = e.phases_default if phases is None else list(phases)
    if ph not in e.phase_sets():
        raise PickError(f"{entry_id}: phases {ph} are not offered for this protocol")
    lat = (laterality or "").strip().lower() or None
    if e.laterality == "required" and lat not in LATERALITY:
        raise PickError(f"{entry_id}: laterality is required (left, right or bilateral)")
    if e.laterality != "required" and lat is not None:
        raise PickError(f"{entry_id}: laterality is not used for this protocol")
    kd = bundle.keys[e.sheet_key]
    regions = [Region(name=r.name, includes=r.includes, quiet=r.quiet) for r in kd.regions]
    line = e.display_name + (f" ({lat})" if lat else "")
    if ph != e.phases_default:
        line += f" ({phase_words(ph)})"
    return Resolution(entry_id=e.id, display_name=e.display_name, laterality=lat, phases=ph, sheet_key=e.sheet_key,
                      contrast_class=e.contrast_class, regions=regions, quiet=[r.name for r in regions if r.quiet],
                      level_groups=kd.level_groups, scan_type_line=line,
                      sheet_id=f"lib:{e.id}|{phase_id(ph)}|{lat or '-'}|{bundle.version}",
                      schema_key=f"lib:{e.sheet_key}|{e.contrast_class}")


def modality_line(e: Entry, phases: list[str]) -> str:
    """e.g. "CT with IV contrast: unenhanced, arterial, portal venous"; "MR with gadolinium: DCE"; "MR without contrast"."""
    head = f"{e.modality} without contrast" if e.agent == "none" else f"{e.modality} with {agent_words(e.agent)}"
    words = phase_words(phases)
    return f"{head}: {words}" if words else head


_SCAN_CONTEXT = re.compile(r"^##\s+Scan Context\s*$[\s\S]*?(?=^##\s|\Z)", re.M | re.I)


def compose_sheet(bundle: Bundle, res: Resolution) -> ComposedSheet:
    e = bundle.entry(res.entry_id)
    base = bundle.base_sheets[f"{res.sheet_key}|{res.contrast_class}"]
    phase = bundle.phase_sheets[f"{res.entry_id}|{phase_id(res.phases)}"]
    normals = {r: list(v) for r, v in base.region_normals.items()}
    for r, v in phase.changed_normals.items():
        if v:
            normals[r] = list(v)
        else:
            normals.pop(r, None)
    for q in res.quiet:
        normals.pop(q, None)
    # One source for every phase set, default included: the reviewed phase sheet; the entry's list only if it is empty.
    na = phase.scan_context.get("not assessable on this scan", "") or "; ".join(e.not_assessable)
    ctx = (f"## Scan Context\n- **Modality:** {modality_line(e, res.phases)}\n"
           f"- **Imaged volume:** {e.coverage}\n- **Not assessable on this scan:** {na or 'none stated'}\n\n")
    md = _SCAN_CONTEXT.sub(lambda _m: ctx, base.markdown, count=1) if _SCAN_CONTEXT.search(base.markdown) \
        else ctx + base.markdown
    return ComposedSheet(id=res.sheet_id, markdown=md, region_normals=normals, not_assessable=na,
                         level_groups=res.level_groups)


def sheet_from_id(bundle: Bundle, sheet_id: str) -> ComposedSheet | None:
    parts = (sheet_id or "").removeprefix("lib:").split("|")
    if not sheet_id.startswith("lib:") or len(parts) != 4:
        return None
    entry_id, pid, lat, _version = parts
    e = bundle.entry(entry_id)
    if e is None:
        return None
    phases = next((ph for ph in e.phase_sets() if phase_id(ph) == pid), None)
    if phases is None:
        return None
    try:
        return compose_sheet(bundle, resolve(bundle, entry_id, phases, None if lat == "-" else lat))
    except PickError:
        return None
