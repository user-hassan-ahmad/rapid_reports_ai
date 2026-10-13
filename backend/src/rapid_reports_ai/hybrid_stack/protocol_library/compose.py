"""Resolve a picked protocol to its regions and compose its two-layer slim sheet (spec §4): the reviewed base sheet
for (sheet key, contrast class) with the phase sheet's changed normals laid over it, and a Scan Context composed in
code from the entry (phase-sheet scan lines were the noisiest output of the review)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..schemas import OTHER, Region, pill_regions
from .bundle import Bundle, Entry, phase_id
from .match import PHASE_WORDS, agent_words, phase_words

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
    # A region with no normal in the composed sheet is quiet too (2026-10-13): no pill, no assumed normal, still
    # dictatable. Segment and level-group regions are left to their level group; Other findings is never quiet.
    have = _normals(bundle, e, ph)
    grouped = set(kd.level_groups) | {n for v in kd.level_groups.values() for n in v}
    regions = [Region(name=r.name, includes=r.includes,
                      quiet=r.quiet or (r.name != OTHER and not r.level_group and r.name not in grouped
                                        and not have.get(r.name)))
               for r in kd.regions]
    line = e.display_name + (f" ({lat})" if lat else "")
    if ph != e.phases_default:
        line += f" ({phase_words(ph)})"
    return Resolution(entry_id=e.id, display_name=e.display_name, laterality=lat, phases=ph, sheet_key=e.sheet_key,
                      contrast_class=e.contrast_class, regions=regions, quiet=[r.name for r in regions if r.quiet],
                      level_groups=kd.level_groups, scan_type_line=line,
                      sheet_id=f"lib:{e.id}|{phase_id(ph)}|{lat or '-'}|{bundle.version}",
                      schema_key=f"lib:{e.sheet_key}|{e.contrast_class}")


UNENHANCED = {"non_contrast", "cine", "flow", "t1_t2_mapping", "t2star", "calcium_score"}


def effective_agent(e: Entry, phases: list[str]) -> str:
    """The contrast wording follows the picked phase set (re-review 2026-10-13): a set of only unenhanced phases or
    non-contrast sequences is "none" whatever the entry's agent; a contrast phase on an agent-none entry takes the
    modality default; an empty phase set keeps the entry's agent."""
    if not phases:
        return e.agent
    if all(p in UNENHANCED for p in phases):
        return "none"
    if e.agent == "none":
        return "gadolinium" if e.modality.upper() in ("MR", "MRI") else "iv_iodinated"
    return e.agent


def modality_line(e: Entry, phases: list[str]) -> str:
    """e.g. "CT with IV contrast: unenhanced, arterial, portal venous"; "MR with gadolinium: DCE"; "MR without contrast"."""
    agent = effective_agent(e, phases)
    head = f"{e.modality} without contrast" if agent == "none" else f"{e.modality} with {agent_words(agent)}"
    words = phase_words(phases)
    return f"{head}: {words}" if words else head


# What follows "following" in the Technique statement, per effective agent (UK house style, 2026-10-13).
_CT_AGENT = {"iv_iodinated": "intravenous contrast", "gadolinium": "intravenous contrast",
             "gadolinium_hepatobiliary": "intravenous contrast", "oral_only": "oral contrast",
             "iv_and_oral": "intravenous and oral contrast", "intra_articular": "intra-articular contrast",
             "intrathecal": "intrathecal contrast", "rectal_or_luminal": "luminal contrast", "air": "air insufflation"}
_MR_AGENT = {"gadolinium": "intravenous gadolinium", "iv_iodinated": "intravenous gadolinium",
             "gadolinium_hepatobiliary": "intravenous hepatobiliary gadolinium", "oral_only": "oral contrast",
             "iv_and_oral": "intravenous gadolinium and oral contrast", "intra_articular": "intra-articular gadolinium",
             "intrathecal": "intrathecal gadolinium", "rectal_or_luminal": "luminal contrast", "air": "air insufflation"}
# A display name that begins with the procedure rather than the region ("MR Arthrogram hip", "CT Angiogram aorta"):
# kept as written, never "of the arthrogram hip".
_PROCEDURE_FIRST = re.compile(r"(?i)^(?:low\b|dual\b|perfusion\b|cardiac\b|abbreviated\b)|\b(?:angio\w*|\w*gram|\w*graphy|mra|cta|mrcp)\b")
_NAME_TAIL = re.compile(r"(?i)\s+(?:(?:with|without)\s+(?:[\w-]+\s+){0,3}contrast(?:\s*\([^)]*\))?"
                        r"|(?:dual|two|three|triple|four|multi)[\s-]?phase)$")


def _lower_title(words: str) -> str:
    """"Abdomen and Pelvis" -> "abdomen and pelvis"; "T2*" or "MRI" keep their capitals."""
    return " ".join(w if any(c.isupper() for c in w[1:]) else w.lower() for w in words.split())


def technique_statement(e: Entry, phases: list[str], laterality: str | None = None) -> str:
    """One sentence in UK house style (2026-10-13): the generator writes TECHNIQUE from this, never from a guess.
    MR: "Multiplanar multisequence MRI of the left knee[ following intravenous gadolinium]." (the agent clause only
    when the effective agent has contrast; no sequence list). CT: "CT head without intravenous contrast." or "CT
    abdomen and pelvis following intravenous contrast: arterial and portal venous phases." The region is the display
    name minus its modality and its contrast / phase-count words, plus the laterality; a display name that begins
    with the procedure ("MR Arthrogram hip", "CT Angiogram aorta") is kept as written, the laterality in brackets."""
    mr = e.modality.upper() in ("MR", "MRI")
    name = _NAME_TAIL.sub("", e.display_name.strip())
    rest = re.sub(r"(?i)^(?:ct|mri|mr)\s+", "", name)
    side = f"{laterality} " if laterality else ""
    if rest != name and rest and not _PROCEDURE_FIRST.search(rest):
        region = f"{side}{_lower_title(rest)}"
        subject = f"Multiplanar multisequence MRI of the {region}" if mr else f"CT {region}"
    else:
        named = _lower_title(name) + (f" ({laterality})" if laterality else "")
        subject = f"Multiplanar multisequence {named}" if mr else named
    agent = effective_agent(e, phases)
    if mr:
        return f"{subject} following {_MR_AGENT.get(agent, 'intravenous gadolinium')}." if agent != "none" \
            else f"{subject}."
    if agent == "none":
        return f"{subject} without intravenous contrast."
    words = [PHASE_WORDS.get(p, p.replace("_", " ")) for p in phases]
    listed = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""
    when = f": {listed} phase{'s' if len(words) > 1 else ''}" if listed else ""
    return f"{subject} following {_CT_AGENT.get(agent, 'intravenous contrast')}{when}."


# The consultant's headings (2026-10-13): the impression is headed CONCLUSION. The review engine and the
# post-generation check read CONCLUSION as the impression (report_review.IMPRESSION_HEADINGS).
STANDARD_SECTIONS = "Comparison; Technique; Limitations (only when applicable); Findings; Conclusion"
CONCLUSION_RULE = "CONCLUSION never restates the modality, region or technique; it opens with the finding."
SECTION_RULES = (
    "COMPARISON comes first: carry a prior study if one is dictated; acknowledge comparison generically when the "
    "findings use comparison language (new, stable, unchanged, increased, resolved and the like); otherwise state "
    "that no prior imaging is available for comparison. TECHNIQUE is the protocol description only: modality, "
    "region, contrast and phases or sequences, written from the Technique statement in Scan Context, with no "
    "assessment or limitation wording. LIMITATIONS appears only when the radiologist dictates a limitation or a "
    "genuine study-specific degradation is stated; it is never the not-assessable list. " + CONCLUSION_RULE +
    " Never a clinical history section.")
_STRUCTURAL = re.compile(r"^##\s+Structural Pattern\s*$([\s\S]*?)(?=^##\s|\Z)", re.M | re.I)
_SECTIONS_BULLET = re.compile(r"^\s*-\s+\*\*Sections:\*\*.*$\n?", re.M | re.I)
_RULES_BULLET = re.compile(r"^\s*-\s+\*\*Section rules:\*\*.*$\n?", re.M | re.I)
_SWEEP_BULLET = re.compile(r"^\s*-\s+\*\*Sweep order:\*\*.*$\n?", re.M | re.I)


def sweep_order(regions: list[Region]) -> str:
    """The key's regions in region-list order, minus "Other findings" and quiet regions: the scratchpad's pills."""
    return " → ".join(pill_regions(regions))


def _standard_sections(md: str, regions: list[Region]) -> str:
    """The Structural Pattern's section list, section rules and sweep order are composed in code for every library
    sheet, as the Scan Context is: 177 of 185 base sheets said "Findings, Impression", so reports lost COMPARISON and
    TECHNIQUE; the sweep order follows the key's region list."""
    head = f"- **Sections:** {STANDARD_SECTIONS}\n- **Section rules:** {SECTION_RULES}\n"
    if sweep := sweep_order(regions):
        head += f"- **Sweep order:** {sweep}\n"
    m = _STRUCTURAL.search(md)
    if not m:
        return md.rstrip("\n") + f"\n\n## Structural Pattern\n{head}"
    body = _SWEEP_BULLET.sub("", _RULES_BULLET.sub("", _SECTIONS_BULLET.sub("", m.group(1)))).lstrip("\n")
    return md[:m.start()] + f"## Structural Pattern\n{head}{body}" + md[m.end():]


_SCAN_CONTEXT = re.compile(r"^##\s+Scan Context\s*$[\s\S]*?(?=^##\s|\Z)", re.M | re.I)


def _normals(bundle: Bundle, e: Entry, phases: list[str]) -> dict[str, list[str]]:
    """The base sheet's region normals with the phase sheet's changes laid over (an empty change removes one)."""
    normals = {r: list(v) for r, v in bundle.base_sheets[f"{e.sheet_key}|{e.contrast_class}"].region_normals.items()}
    for r, v in bundle.phase_sheets[f"{e.id}|{phase_id(phases)}"].changed_normals.items():
        if v:
            normals[r] = list(v)
        else:
            normals.pop(r, None)
    return normals


def compose_sheet(bundle: Bundle, res: Resolution) -> ComposedSheet:
    e = bundle.entry(res.entry_id)
    base = bundle.base_sheets[f"{res.sheet_key}|{res.contrast_class}"]
    phase = bundle.phase_sheets[f"{res.entry_id}|{phase_id(res.phases)}"]
    normals = _normals(bundle, e, res.phases)
    for q in res.quiet:
        normals.pop(q, None)
    # One source for every phase set, default included: the reviewed phase sheet; the entry's list only if it is empty.
    na = phase.scan_context.get("not assessable on this scan", "") or "; ".join(e.not_assessable)
    ctx = (f"## Scan Context\n- **Modality:** {modality_line(e, res.phases)}\n"
           f"- **Technique statement:** {technique_statement(e, res.phases, res.laterality)}\n"
           f"- **Imaged volume:** {e.coverage}\n- **Not assessable on this scan:** {na or 'none stated'}\n\n")
    md = _SCAN_CONTEXT.sub(lambda _m: ctx, base.markdown, count=1) if _SCAN_CONTEXT.search(base.markdown) \
        else ctx + base.markdown
    md = _standard_sections(md, res.regions)
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
