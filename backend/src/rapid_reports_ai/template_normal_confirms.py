"""The normals confirm record (spec 2026-10-15-stable-line-ids-design, decision 5): the radiologist confirms a
template's assumed normals in small groups beside their sentences, and each confirm is recorded in
template_config["normal_confirms"] ({group id: record}), written only by POST /api/templates/{id}/normal-confirms
from the stored sheet and registry (never from the client, never by code on its own). Pure code here.

Groups (one definition): in a findings section, one group per paragraph (the scratchpad's regions,
hybrid_stack.template.paragraph_regions) and one for the section's units outside any paragraph; every other section is
one group. A group with more than MAX_GROUP attestable units is split into consecutive chunks of at most MAX_GROUP in
document order ("<uid>#1", "#2", …). Inserting or removing a normal shifts later chunks, so they go stale and are
confirmed again (accepted). Attestable units: the group's NORMAL lines and its unconditional template NEGATIVE lines.

State: valid (the group's current attestable units are exactly the record's, each with the same text_hash, and its
paragraph or section still has the recorded name), stale (anything else: a unit added, removed or gone; ANY unit's
text_hash changed, including a normal reworded in place that kept its slot uid (a normal's identity holds no text, so
this check is the safety net); or a paragraph or section rename (group_name), even when every sentence carried over:
a confirm given in one context never silently covers another; or a RULE that suppresses, replaces or is anchored on
one of the group's units, or suppresses its section, added, removed or changed (rules_hash, end review M5)), missing
(no record). A stale confirm is asked again and never counts. The confirm UI is offered only
once the template is saved: there are no creation-time confirms."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import template_line_match as tlm
from . import template_line_registry as tlr
from .hybrid_stack.template import norm_key, paragraph_regions

logger = logging.getLogger(__name__)

MAX_GROUP = 8
VALID, STALE, MISSING = "valid", "stale", "missing"


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    units: Tuple[str, ...]   # uids, in document order
    name: str = ""           # the paragraph's or section's name (group_name): a rename makes a confirm stale
    rules: str = ""          # rules_hash of the rules acting on the group ("" when none): any change makes it stale


def attestable(st) -> List[str]:
    """Parse refs of the attestable units: every NORMAL, and every NEGATIVE with no condition from the template."""
    return [n.id for n in st.normals] + [n.id for n in st.negatives
                                         if not n.condition and n.origin == "template" and n.kind == "negative"]


def _positions(sheet: str, st) -> Dict[str, int]:
    """Parse ref -> sheet line index of each line-bound unit (the k-th identical line is the k-th occurrence)."""
    lines = (sheet or "").split("\n")
    taken: set = set()
    out: Dict[str, int] = {}
    for u in tlr.units(st):
        if u.kind not in tlr.LINE_KINDS:
            continue
        i = next((k for k, ln in enumerate(lines) if k not in taken and ln == u.raw), None)
        if i is not None:
            taken.add(i)
            out[u.ref] = i
    return out


_ON_TEXT = ("suppress", "replace", "insert_before")


def rules_hash(st, refs: List[str], section: str, paragraph: str) -> str:
    """A hash over the RULE lines that can change what the group's units print (end review M5): a rule that
    suppresses or replaces one of the units' text, or is anchored on it (norm_key, the generator's own matching);
    SUPPRESS NEGATIVES in the group's paragraph; SUPPRESS_SECTION of its section. "" when there are none, so adding,
    removing or changing any of them makes the confirm stale while an unrelated rule never does."""
    by_ref = {u.ref: u for u in tlr.units(st)}
    texts = {norm_key(by_ref[r].text) for r in refs if r in by_ref}
    hit = []
    for r in st.rules:
        on_text = r.effect in _ON_TEXT and (norm_key(r.target) in texts or (r.anchor and norm_key(r.anchor) in texts))
        on_para = r.effect == "suppress_paragraph_negatives" and paragraph and r.paragraph == paragraph
        on_section = r.effect == "suppress_section" and tlm.rep_key(r.target) == tlm.rep_key(section)
        if on_text or on_para or on_section:
            hit.append(tlm.rep_key(str(r.source_lines[0]) if r.source_lines else r.id))
    return tlr.text_hash("\n".join(sorted(hit))) if hit else ""


def group_name(name: str) -> str:
    """A paragraph's or section's name as a confirm record stores it: tlm.rep_key (lookalikes and spacing only; any
    other change, case included, is a rename and makes the confirm stale, decision 7)."""
    return tlm.rep_key(name)


def groups(st, sheet: str, registry) -> List[Group]:
    """The confirm groups of a parsed sheet, in section order (module doc). A group whose parent or any unit has no
    uid in `registry` is left out (logged): it cannot be recorded."""
    uids = tlr.uids_for(st, registry)
    pos = _positions(sheet, st)
    by_ref = {u.ref: u for u in tlr.units(st)}
    att = sorted((r for r in attestable(st) if r in pos), key=lambda r: pos[r])
    regions = paragraph_regions(st)
    out: List[Group] = []
    for sec in sorted(st.sections, key=lambda s: s.order):
        mine = [r for r in att if by_ref[r].section == f"S:{sec.name}"]
        buckets: List[Tuple[str, str, str, List[str]]] = []   # (parent ref, label, name, unit refs)
        if sec.role == "findings":
            for p in (p for p in st.paragraphs if p.section == sec.name):
                buckets.append((p.id, f"{sec.name.title()} › {regions.get(p.id, p.name)}", p.name,
                                [r for r in mine if by_ref[r].paragraph == p.id]))
            buckets.append((f"S:{sec.name}", sec.name.title(), sec.name,
                            [r for r in mine if not by_ref[r].paragraph]))
        else:
            buckets.append((f"S:{sec.name}", sec.name.title(), sec.name, mine))
        for parent, label, raw_name, refs in buckets:
            if not refs:
                continue
            para = parent if not parent.startswith("S:") else ""
            if parent not in uids or any(r not in uids for r in refs):
                logger.info("[confirms] group %s left out: a unit has no uid", label)
                continue
            members = tuple(uids[r] for r in refs)
            name = group_name(raw_name)
            if len(members) <= MAX_GROUP:
                out.append(Group(uids[parent], label, members, name, rules_hash(st, refs, sec.name, para)))
                continue
            chunks = [refs[k:k + MAX_GROUP] for k in range(0, len(refs), MAX_GROUP)]
            out += [Group(f"{uids[parent]}#{n}", f"{label} ({n}/{len(chunks)})", tuple(uids[r] for r in c), name,
                          rules_hash(st, c, sec.name, para))
                    for n, c in enumerate(chunks, 1)]
    return out


def record(group: Group, registry, *, sheet_rev: int, sheet_hash: str, user_id: str,
           now: Optional[str] = None) -> dict:
    """The confirm record of one group, its units' text_hash read from the stored registry. A unit the registry
    cannot vouch for (absent or malformed) is left out, so the record is never valid (confirm_state)."""
    return {"group": group.id, "label": group.label, "units": _hashes(group, registry),
            "sheet_rev": sheet_rev, "sheet_hash": sheet_hash, "group_name": group.name, "rules": group.rules,
            "user_id": user_id,
            "at": now or datetime.now(timezone.utc).isoformat(timespec="seconds")}


def confirm_state(group: Optional[Group], rec: Optional[dict], registry) -> str:
    """valid / stale / missing for one group (module doc). `group` None: the group no longer exists (stale when a
    record names it). The same attestable predicate is used when confirming and when checking."""
    if not isinstance(rec, dict):
        return MISSING
    if group is None or rec.get("group_name") != group.name:   # a renamed paragraph or section (decision 5)
        return STALE
    if (rec.get("rules") or "") != group.rules:   # a rule acting on the group added, removed or changed (M5)
        return STALE
    now = _hashes(group, registry)
    return VALID if len(now) == len(group.units) and rec.get("units") == now else STALE


def _hashes(group: Group, registry) -> Dict[str, str]:
    """{uid: text_hash} of the group's units that are live and well formed in `registry` (tlr.load drops the rest)."""
    units = tlr.load(registry)["units"]
    return {u: units[u]["text_hash"] for u in group.units if units.get(u, {}).get("status") == "live"}


def confirm_states(st, sheet: str, registry, confirms) -> Dict[str, str]:
    """{group id: state} for every current group, and stale for every recorded group that no longer exists."""
    confirms = confirms if isinstance(confirms, dict) else {}
    current = {g.id: g for g in groups(st, sheet, registry)}
    out = {gid: confirm_state(g, confirms.get(gid), registry) for gid, g in current.items()}
    out.update({gid: STALE for gid in confirms if gid not in current})
    return out
