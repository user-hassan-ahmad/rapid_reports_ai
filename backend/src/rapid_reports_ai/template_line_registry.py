"""The line registry (spec 2026-10-15-stable-line-ids-design): a stable uid per line-bound sheet unit, kept beside the
sheet in template_config["line_registry"] and re-bound by code on every persisted save (template_sheet_save.
persist_sheet). Pure code, no model call. The sheet text is never changed.

A uid names a slot, not a string. Identity per kind (all must match):
    section    normalised name
    paragraph  section uid + normalised name; or (a rename) section uid + the same non-empty COVERS set
    normal     section uid + paragraph uid + structure (its text is tracked by text_hash, not identity); across a
               paragraph rename (the COVERS rule) its text must also be exactly equal (decision 5)
    negative   section uid + paragraph uid + condition + condition_source + kind + origin + text
    fixed      section uid + paragraph uid + text
    rule       section uid + paragraph uid + effect + condition + condition_source + target + anchor + position +
               then_text + else_text + items + question
Every text and name compares EXACTLY after representation-only normalising (template_line_match.rep_key: lookalike
characters unified, whitespace collapsed); case, punctuation, spelling and filler words stay significant (decision 7).
TERM, COVERS and IF_PRESENT lines get no uid.

rebind(registry, structure, carried) pairs the new parse's units with the previous registry's, kind by kind,
parents first: carried units (lines apply_ledger rewrote) keep their uid; then exact identity against live units (a
paragraph also by the COVERS rename rule, reported as exact); then exact identity against gone units (revival). Pairs are 1:1: a unit with two candidates, or a
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

logger = logging.getLogger(__name__)

REGISTRY_VERSION = 1
KINDS = ("section", "paragraph", "normal", "negative", "fixed", "rule")
LINE_KINDS = ("normal", "negative", "fixed", "rule")
PREFIX = {"section": "s_", "paragraph": "p_", "normal": "n_", "negative": "g_", "fixed": "f_", "rule": "r_"}

# Identity fields after the parents, and how each is compared: "plain" (as is), "text" (tlm.rep_key, exactly), "items"
# (a list of texts, each as "text", in order).
_FIELDS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "section": (("name", "text"),),
    "paragraph": (("name", "text"),),
    "normal": (("structure", "text"),),
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
            key.append(tuple(tlm.rep_key(x) for x in v or []))
        elif how == "text":
            key.append(tlm.rep_key(v or ""))
        else:
            key.append(v or "")
    return (kind, *key)


def _rename(kind: str, ident: dict) -> Optional[tuple]:
    """A paragraph's rename identity (decision 5): section uid + the same non-empty COVERS set, the name ignored.
    None for every other kind, and for a paragraph without COVERS."""
    if kind != "paragraph":
        return None
    covers = frozenset(tlm.rep_key(c) for c in ident.get("covers") or [])
    return (kind, ident.get("section", ""), covers) if covers else None


def _mint(kind: str, ident: dict, taken: set, salt: str = "") -> str:
    """A new uid: kind prefix + 6 base32 characters of sha256(salt | kind | identity | n), deterministic given the
    registry's salt (spec gap 3)."""
    n = 0
    while True:
        digest = hashlib.sha256(f"{salt}|{kind}|{json.dumps(ident, sort_keys=True)}|{n}".encode()).digest()
        uid = PREFIX[kind] + base64.b32encode(digest).decode().lower()[:6]
        if uid not in taken:
            return uid
        n += 1


def _parents_match(u: Unit, assigned: Dict[str, str], prev_identity: dict) -> bool:
    """A carried line keeps its uid only in the same section and paragraph it had: never moved to an identical line
    elsewhere (spec gap 13)."""
    ident = _identity(u, assigned)
    return all(ident.get(p, "") == prev_identity.get(p, "") for p in _PARENTS[u.kind])


def _pair(new: List[Tuple[Unit, dict]], pool: Dict[str, dict], keyfn) -> Tuple[Dict[str, str], List[str], set]:
    """One tier: {unit ref: uid} for 1:1 pairs, the refs of new units with competing candidates (ambiguous), and the
    uids those competed for (they pair with nothing after this tier). keyfn(kind, identity, text)."""
    by_key: Dict[tuple, List[str]] = {}
    for uid, e in pool.items():
        k = keyfn(e["kind"], e["identity"], e.get("text", ""))
        if k is not None:
            by_key.setdefault(k, []).append(uid)
    cands = {}
    for u, ident in new:
        k = keyfn(u.kind, ident, u.text)
        if k is not None and by_key.get(k):
            cands[u.ref] = by_key[k]
    claims: Dict[str, int] = {}
    for c in cands.values():
        for uid in c:
            claims[uid] = claims.get(uid, 0) + 1
    paired, ambiguous, burnt = {}, [], set()
    for ref, c in cands.items():
        if len(c) == 1 and claims[c[0]] == 1:
            paired[ref] = c[0]
        else:
            ambiguous.append(ref)
            burnt.update(c)
    return paired, ambiguous, burnt


def rebind(registry, st, carried: Optional[Dict[str, str]] = None, *,
           now: Optional[str] = None) -> Tuple[dict, dict]:
    """(new registry, report) for the parse `st` against the previous registry (module doc). `carried`: {uid: the raw
    line apply_ledger rewrote that unit to}. report = {exact, carried, revived, new, gone, ambiguous}, each a
    list of uids (a paragraph kept by the COVERS rename rule counts as exact). Never mutates its inputs."""
    reg, report, _ = _bind(registry, st, carried, now)
    return reg, report


def _bind(registry, st, carried, now):
    reg = load(registry)
    reg.setdefault("salt", secrets.token_hex(4))   # minted once per registry; uids differ across templates
    prev = reg["units"]
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {k: [] for k in ("exact", "carried", "revived", "new", "gone", "ambiguous")}
    assigned: Dict[str, str] = {}   # unit ref -> uid
    used: set = set()
    all_units = units(st)
    renamed: set = set()   # paragraph uids kept by the COVERS rename rule (spec decision 5)

    def exact_key(k: str, ident: dict, text: str) -> tuple:
        """Across a paragraph rename a normal also needs its own text (decision 5, option c)."""
        base = _exact(k, ident)
        return (*base, tlm.rep_key(text)) if k == "normal" and ident.get("paragraph") in renamed else base

    for kind in KINDS:
        todo = [u for u in all_units if u.kind == kind]
        live = {uid: e for uid, e in prev.items() if e["kind"] == kind and e.get("status") == "live"}
        gone = {uid: e for uid, e in prev.items() if e["kind"] == kind and e.get("status") != "live"}

        def take(u: Unit, uid: str, ident: dict, how: str) -> None:
            assigned[u.ref] = uid
            used.add(uid)
            prev[uid] = {**prev[uid], "kind": kind, "identity": ident, "text": u.text, "text_hash": text_hash(u.text),
                         "status": "live"}
            report[how].append(uid)

        if kind in LINE_KINDS:
            for uid, raw in sorted((carried or {}).items()):
                if uid not in live or uid in used or not uid.startswith(PREFIX[kind]):
                    continue
                hits = [u for u in todo if u.ref not in assigned and u.raw == raw
                        and _parents_match(u, assigned, prev[uid]["identity"])]
                if len(hits) == 1:
                    take(hits[0], uid, _identity(hits[0], assigned), "carried")
        excluded: set = set()
        tiers = (("exact", live, exact_key), ("exact", live, lambda k, i, t: _rename(k, i)),
                 ("revived", gone, exact_key))
        for tier, (how, pool, keyfn) in enumerate(tiers):
            rest = [(u, _identity(u, assigned)) for u in todo if u.ref not in assigned and u.ref not in excluded]
            avail = {uid: e for uid, e in pool.items() if uid not in used}
            paired, ambiguous, burnt = _pair(rest, avail, keyfn)
            for u, ident in rest:
                if u.ref in paired:
                    take(u, paired[u.ref], ident, how)
                    if tier == 1:
                        renamed.add(paired[u.ref])
            excluded.update(ambiguous)
            used.update(burnt)   # a uid two new units competed for pairs with nothing
        for u in todo:
            if u.ref in assigned:
                continue
            ident = _identity(u, assigned)
            uid = _mint(kind, ident, set(prev) | used, reg["salt"])
            prev[uid] = {"kind": kind, "identity": ident, "text": u.text, "text_hash": text_hash(u.text),
                         "status": "live", "minted": now}
            assigned[u.ref] = uid
            used.add(uid)
            report["ambiguous" if u.ref in excluded else "new"].append(uid)
        for uid in live:
            if uid not in assigned.values():
                prev[uid] = {**prev[uid], "status": "gone"}
                report["gone"].append(uid)
    return reg, report, assigned


def summary(report: dict) -> str:
    """The rebind report as one log fragment: "exact=9 carried=1 …"."""
    return " ".join(f"{k}={len(v)}" for k, v in report.items())

def uids_for(st, registry) -> Dict[str, str]:
    """{unit ref: uid} for the parse's units that match a live registry unit by exact identity, parents first, 1:1
    (a unit with two candidates gets none). Pure; never mints. Consumers call it at read time: uids are never stored
    on the cached sheet_structure."""
    reg = load(registry)
    out: Dict[str, str] = {}
    for kind in KINDS:
        live = {uid: e for uid, e in reg["units"].items() if e["kind"] == kind and e.get("status") == "live"}
        todo = [(u, _identity(u, out)) for u in units(st) if u.kind == kind]
        paired, _, _ = _pair(todo, live, lambda k, i, t: _exact(k, i))
        out.update(paired)
    return out


def match(st, registry) -> Dict[str, str]:
    """{unit ref: uid} for the units rebind would pair with a live unit of `registry` (exact identity, a paragraph
    rename included), without minting or storing anything: apply_ledger's uid-first resolution (spec gap 1).
    Gone units are never matched here (a gone uid falls back to key matching)."""
    _, report, assigned = _bind(registry, st, None, "")
    kept = set(report["exact"])
    return {ref: uid for ref, uid in assigned.items() if uid in kept}
