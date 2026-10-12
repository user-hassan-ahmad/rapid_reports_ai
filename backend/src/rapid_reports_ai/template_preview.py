"""Preview a template sheet as the scratchpad would report a dictation (template pipeline spec, block 3): group
the dictation, assume the template's normals, build the findings block as the scratchpad does, and generate on the
template stack path. Used by the creator's preview and the labs.

The block functions are ports of frontend/src/lib/hybrid-stack/regionState.ts (effectiveItems, regionStates,
findingsText, buildFindingsBlock) and items.ts (assumedFrom); the frontend is the reference. A preview has no
checklist rows, so no answered rows or "Answered by the radiologist" lines; every assumed normal counts as
confirmed. Units are duck-typed (StackUnit or anything with text/group/heading, optionally abnormal/parts/covers)."""
from __future__ import annotations

from typing import Optional

from .hybrid_stack.schemas import CONCLUSION, GENERAL, OTHER, TECHNIQUE
from .template_sheet_grammar import parse_sheet

ASSUMED = "Assumed normal (confirmed by the radiologist):"
_FIXED = {TECHNIQUE, GENERAL, CONCLUSION}


def _norm(s: str) -> str:
    """items.ts norm: case, spacing and a final full stop ignored."""
    s = s.strip().lower()
    return " ".join((s[:-1] if s.endswith(".") else s).split())


def _parts(u) -> list:
    return list(getattr(u, "parts", None) or [])


def _items(units) -> list[tuple[object, str, str, bool]]:
    """effectiveItems: (unit, text, group, abnormal). A split unit gives its parts; headings and unplaced units
    give nothing."""
    out = []
    for u in units:
        if getattr(u, "heading", False) or u.group is None:
            continue
        ps = _parts(u)
        if len(ps) > 1:
            out += [(u, p.text, p.group, bool(getattr(p, "abnormal", False))) for p in ps]
        else:
            out.append((u, u.text, u.group, bool(getattr(u, "abnormal", False))))
    return out


def region_states(units, pill_regions: list[str]) -> tuple[list[str], list[str], list[str]]:
    """regionStates: (abnormal, dictated normal, untouched) region names, each in pill order."""
    items = _items(units)
    abnormal = [r for r in pill_regions if any(g == r and ab for _, _, g, ab in items)]

    def said_normal(r: str) -> bool:
        return (any(g == r and not ab for _, _, g, ab in items)
                or any(not getattr(u, "heading", False) and not getattr(u, "abnormal", False)
                       and r in (getattr(u, "covers", None) or []) for u in units))

    rest = [r for r in pill_regions if r not in abnormal]
    return abnormal, [r for r in rest if said_normal(r)], [r for r in rest if not said_normal(r)]


def confirmed_assumed(assumed: dict, abnormal: list[str], untouched: list[str], removed: list[str]) -> dict:
    """assumedFrom: the assumed normals of the abnormal then the untouched regions, minus removed sentences."""
    gone = {_norm(x) for x in removed}
    out = {}
    for r in [*abnormal, *untouched]:
        kept = [x for x in assumed.get(r) or [] if _norm(x) not in gone]
        if kept:
            out[r] = kept
    return out


def conclusion_text(units) -> str:
    return " ".join(u.text for u in units if u.group == CONCLUSION and not getattr(u, "heading", False))


def findings_text(units, groups: list[str], extra: Optional[dict] = None) -> str:
    """findingsText: Technique first; each region with its own sentences and `extra` lines; other labelled groups;
    a sentence spanning regions whole under its joined label; General; unplaced sentences as said."""
    extra = extra or {}
    spanning = [u for u in units if not getattr(u, "heading", False) and u.group is not None and len(_parts(u)) > 1]
    span_ids = {id(u) for u in spanning}
    items = [i for i in _items(units) if id(i[0]) not in span_ids]
    lines: list[str] = []
    tech = [t for _, t, g, _ in items if g == TECHNIQUE]
    if tech:
        lines += [" ".join(tech), ""]
    for g in groups:
        if g in _FIXED:
            continue
        own = [t for _, t, ig, _ in items if ig == g]
        more = extra.get(g) or []
        if own or more:
            lines.append(f"{g}: {' '.join(own + more)}")
    for g in dict.fromkeys(ig for _, _, ig, _ in items):
        if g not in groups and g not in _FIXED:
            lines.append(f"{g}: {' '.join(t for _, t, ig, _ in items if ig == g)}")
    for u in spanning:
        spans = list(dict.fromkeys(p.group for p in _parts(u)))
        ordered = [g for g in groups if g in spans] + [g for g in spans if g not in groups]
        lines.append(f"{' · '.join(ordered)}: {u.text}")
    lines += [t for _, t, g, _ in items if g == GENERAL]
    lines += [u.text for u in units if u.group is None and not getattr(u, "heading", False)]
    return "\n".join(lines).strip()


def findings_block(units, regions, kept: dict, conclusion: str, declined: list) -> str:
    """buildFindingsBlock without checklist rows: a dictated region carries its assumed normals inline, the
    undictated regions' normals go to one tray line, then the confirmed conclusion and DO NOT ASSERT."""
    groups = [TECHNIQUE, *(r.name for r in regions), GENERAL, CONCLUSION]
    dictated = {g for _, _, g, _ in _items(units)}
    extra: dict[str, list[str]] = {}
    tray: list[str] = []
    for r, sentences in kept.items():
        if not sentences:
            continue
        if r in dictated:
            extra.setdefault(r, []).append(f"{ASSUMED} {' '.join(sentences)}")
        else:
            tray.append(f"{r}: {' '.join(sentences)}")
    parts = [findings_text(units, groups, extra)]
    if tray:
        parts.append(f"{ASSUMED} {' '.join(tray)}")
    if conclusion.strip():
        parts.append(f"Conclusion (confirmed by the radiologist): {conclusion.strip()}")
    if declined:
        parts.append(f"DO NOT ASSERT (removed by the radiologist): {' '.join(declined)}")
    return "\n\n".join(p for p in parts if p)


async def preview_report(sheet: str, scan_type: str, history: str, dictation: str, conclusion: str = "",
                         declined: Optional[list] = None) -> dict:
    """The report the scratchpad would produce for this dictation with this sheet. `conclusion` empty: the
    dictated conclusion (the scratchpad's default before a draft); `declined`: sentences the radiologist removed."""
    from .hybrid_stack import normals as normals_mod
    from .hybrid_stack import service
    from .hybrid_stack.routes import MAX_NORMALS_PER_REGION
    from .hybrid_stack.template import (template_normal_labels, template_region_normals, template_regions,
                                        template_suppressions)
    from . import template_manager
    declined = list(declined or [])
    st = parse_sheet(sheet, mode="template").structure
    if not st.usable:
        return {"usable": False}
    regions = template_regions(st)
    normals = {r: s[:MAX_NORMALS_PER_REGION] for r, s in template_region_normals(st).items()}
    g = await service.group_update(scan_type, dictation, regions, [])
    abnormal, dictated_normal, untouched = region_states(g.units, [r.name for r in regions if r.name != OTHER])
    a = await normals_mod.assumed(dictation, normals, abnormal, dictated_normal, declined,
                                  suppressions=template_suppressions(st), clinical_history=history,
                                  labels=template_normal_labels(st))
    kept = confirmed_assumed(a.assumed, abnormal, untouched, declined)
    conclusion = conclusion.strip() or conclusion_text(g.units)
    block = findings_block(g.units, regions, kept, conclusion, declined)
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": scan_type}
    gen = await template_manager.TemplateManager().generate_report_from_config(
        cfg, {"FINDINGS": block, "CLINICAL_HISTORY": history}, None,
        stack={"conclusion": conclusion, "declined": declined})
    return {"usable": True, "regions": [r.name for r in regions], "assumed": kept, "dropped": a.dropped,
            "assumed_error": a.error, "grouper_error": getattr(g, "error", None), "findings_block": block,
            "report_content": gen["report_content"], "model_used": gen.get("model_used")}
