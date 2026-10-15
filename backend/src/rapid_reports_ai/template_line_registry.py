"""The line registry (spec 2026-10-15-stable-line-ids-design): a stable uid per line-bound sheet unit, kept beside the
sheet in template_config["line_registry"] and re-bound by code on every persisted save (template_sheet_save.
persist_sheet). Pure code, no model call. The sheet text is never changed.

A uid names a slot, not a string. Identity per kind (all must match):
    section    normalised name
    paragraph  section uid + normalised name; or (a rename) section uid + the same non-empty COVERS set, the two
               names passing the clinical gates
    normal     section uid + paragraph uid + structure (its text is tracked by text_hash, not identity); across a
               paragraph rename (the COVERS rule) its text must also be exact or cosmetic (decision 5)
    negative   section uid + paragraph uid + condition + condition_source + kind + origin + text
    fixed      section uid + paragraph uid + text
    rule       section uid + paragraph uid + effect + condition + condition_source + target + anchor + position +
               then_text + else_text + items + question
Text fields match exactly (norm_key) or cosmetically (template_line_match); nothing else. TERM, COVERS and IF_PRESENT
lines get no uid.

rebind(registry, structure, carried) pairs the new parse's units with the previous registry's, kind by kind,
parents first: carried units (lines apply_ledger rewrote) keep their uid; then exact identity, then cosmetic identity
against live units; then exact identity against gone units (revival). Pairs are 1:1: a unit with two candidates, or a
candidate claimed twice, pairs with nothing (`ambiguous`, new uids). Deterministic, uid minting included.

uids_for(structure, registry) maps a parse's units to their uids by exact identity against live units (read time);
match(structure, registry) is the pairing rebind would make, without minting (apply_ledger's uid-first resolution)."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import template_line_match as tlm
from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

REGISTRY_VERSION = 1
KINDS = ("section", "paragraph", "normal", "negative", "fixed", "rule")
LINE_KINDS = ("normal", "negative", "fixed", "rule")
PREFIX = {"section": "s_", "paragraph": "p_", "normal": "n_", "negative": "g_", "fixed": "f_", "rule": "r_"}

# Identity fields after the parents, and how each is compared: "plain" (as is), "name" (case and spacing), "text"
# (norm_key exactly, or cosmetically), "items" (a list of texts, each as "text", in order).
_FIELDS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "section": (("name", "name"),),
    "paragraph": (("name", "name"),),
    "normal": (("structure", "name"),),
    "negative": (("condition", "text"), ("condition_source", "plain"), ("kind", "plain"), ("origin", "plain"),
                 ("text", "text")),
    "fixed": (("text", "text"),),
    "rule": (("effect", "plain"), ("condition", "text"), ("condition_source", "plain"), ("target", "text"),
             ("anchor", "text"), ("position", "plain"), ("then_text", "text"), ("else_text", "text"),
             ("items", "items"), ("question", "text")),
}
_PARENTS = {"section": (), "paragraph": ("section",), "normal": ("section", "paragraph"),
            "negative": ("section", "paragraph"), "fixed": ("section", "paragraph"), "rule": ("section", "paragraph")}


@dataclass(frozen=True)
class Unit:
    """One line-bound unit of a parse. `ref` is the parse's own id ("S:<NAME>" for a section, else p0 / m0 / n0 / f0 /
    r0); `raw` the sheet line ("" for a section or paragraph); `section` / `paragraph` the parse's parent refs."""
    ref: str
    kind: str
    raw: str
    text: str
    fields: tuple        # ((name, value), ...) in _FIELDS order; lists as tuples
    section: str = ""    # parent section ref ("S:<NAME>"), "" for a section
    paragraph: str = ""  # parent paragraph ref, "" when none
    covers: tuple = ()   # a paragraph's COVERS


def _structure_label(s: str) -> str:
    s = (s or "").strip()
    return s[1:-1].strip() if len(s) > 2 and s.startswith('"') and s.endswith('"') else s


def units(st) -> List[Unit]:
    """Every line-bound unit of a parsed sheet, parents first, each kind in parse order."""
    out: List[Unit] = []
    for s in sorted(st.sections, key=lambda x: x.order):
        out.append(Unit(f"S:{s.name}", "section", "", s.name, (("name", s.name),)))
    for p in st.paragraphs:
        out.append(Unit(p.id, "paragraph", "", p.name, (("name", p.name),), section=f"S:{p.section}",
                        covers=tuple(p.covers)))
    for n in st.normals:
        out.append(Unit(n.id, "normal", str(n.source_line), n.text, (("structure", _structure_label(n.structure)),),
                        section=f"S:{n.section}", paragraph=n.paragraph))
    for n in st.negatives:
        out.append(Unit(n.id, "negative", str(n.source_lines[0]) if n.source_lines else "", n.text,
                        (("condition", n.condition or ""),
                         ("condition_source", n.condition_source if n.condition else ""),
                         ("kind", n.kind), ("origin", n.origin), ("text", n.text)),
                        section=f"S:{n.section}", paragraph=n.paragraph))
    for f in st.fixed_blocks:
        out.append(Unit(f.id, "fixed", f.source_line, f.text, (("text", f.text),), section=f"S:{f.section}",
                        paragraph=f.paragraph))
    for r in st.rules:
        raw = str(r.source_lines[0]) if r.source_lines else ""
        out.append(Unit(r.id, "rule", raw, raw.strip(),
                        (("effect", r.effect), ("condition", r.condition), ("condition_source", r.condition_source),
                         ("target", r.target), ("anchor", r.anchor), ("position", r.position or ""),
                         ("then_text", r.then_text), ("else_text", r.else_text), ("items", tuple(r.items)),
                         ("question", r.question)),
                        section=f"S:{r.section}", paragraph=r.paragraph))
    return out


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode()).hexdigest()


def empty() -> dict:
    return {"v": REGISTRY_VERSION, "units": {}}


_SALT = re.compile(r"[0-9a-f]{8}")


def load(raw) -> dict:
    """A stored registry (a deep copy, its salt kept), or an empty one when absent or unreadable (never raises)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("units"), dict):
        return empty()
    good = {u: e for u, e in raw["units"].items()
            if isinstance(u, str) and isinstance(e, dict) and e.get("kind") in KINDS
            and isinstance(e.get("identity"), dict) and u.startswith(PREFIX[e["kind"]])}
    out = {"v": REGISTRY_VERSION, "units": copy.deepcopy(good)}
    if isinstance(raw.get("salt"), str) and _SALT.fullmatch(raw["salt"]):
        out["salt"] = raw["salt"]
    return out


def _identity(u: Unit, parents: Dict[str, str]) -> dict:
    """The identity stored for a unit: its parents' uids (from `parents`, unit ref -> uid) and its own fields."""
    ident = {p: parents.get(getattr(u, p), "") if getattr(u, p) else "" for p in _PARENTS[u.kind]}
    for name, value in u.fields:
        ident[name] = list(value) if isinstance(value, tuple) else value
    if u.kind == "paragraph":
        ident["covers"] = list(u.covers)
    return ident


def _exact(kind: str, ident: dict) -> tuple:
    key = [ident.get(p, "") for p in _PARENTS[kind]]
    for name, how in _FIELDS[kind]:
        v = ident.get(name)
        if how == "items":
            key.append(tuple(norm_key(x) for x in v or []))
        elif how == "text":
            key.append(norm_key(v or ""))
        elif how == "name":
            key.append(" ".join((v or "").lower().split()))
        else:
            key.append(v or "")
    return (kind, *key)


def _cosmetic(kind: str, ident: dict) -> Optional[tuple]:
    """The cosmetic identity; None when the kind has none (a section, a normal: identity holds no text)."""
    if kind == "paragraph":
        covers = frozenset(" ".join(c.lower().split()) for c in ident.get("covers") or [])
        return (kind, ident.get("section", ""), covers, tlm.gates(ident.get("name", ""))) if covers else None
    if not any(how in ("text", "items") for _, how in _FIELDS[kind]):
        return None
    key = [ident.get(p, "") for p in _PARENTS[kind]]
    for name, how in _FIELDS[kind]:
        v = ident.get(name)
        if how == "items":
            key.append(tuple(tlm.cosmetic_key(x) for x in v or []))
        elif how == "text":
            key.append(tlm.cosmetic_key(v or ""))
        elif how == "name":
            key.append(" ".join((v or "").lower().split()))
        else:
            key.append(v or "")
    return (kind, *key)
