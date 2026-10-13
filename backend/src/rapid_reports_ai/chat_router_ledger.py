"""The chat-edit router's one door to the Rules step (spec 2026-10-13-chat-edit-router-design, Flow 2 and 5).

Router modules call the decision ledger, its one-tap cards and the save function only through this module, never
template_decisions / template_ledger_apply / template_rules_cards / template_sheet_save directly, so a rename or a
shape change there is one edit here (verified against feat/rules-step 68493ba9). Ledger kinds: value, concept,
fixed, normal; layout and style have none. Only concept_choice / concept_state / condition_for know the concept
choice shape."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import template_decisions as td
from . import template_ledger_apply as tla
from . import template_rules_cards as trc
from . import template_sheet_grammar as tsg
from . import template_sheet_save as tsave
from .hybrid_stack.template import norm_key

LEDGER_KINDS: Tuple[str, ...] = tuple(td.KINDS)
NEEDS: Tuple[str, ...] = tuple(td.NEEDS)
KEEPS: Tuple[str, ...] = tuple(td.KEEPS)
ROUTES: Tuple[str, ...] = tuple(td.ROUTES)
CONCEPTS: Dict[str, str] = {name: c.label for name, c in td.CONCEPTS.items()}
CONCEPT_STATES = ("used", "dictated", "not_used")


class Rejected(ValueError):
    """Code cannot apply this change as given. Its text is internal (evidence only), never a reply."""


@dataclass
class Saved:
    status: str                 # the save function's status: "saved" | "unchanged" | "refused"
    sheet: str
    ledger: List[dict]
    message: str = ""           # an adjustment notice or the refusal reason (written for the radiologist)
    ledger_changes: List[dict] = field(default_factory=list)   # confirmed items a sheet change moved
    cards: List[dict] = field(default_factory=list)            # whole items a rewrite removed unasked: kept, asked
    unmatched: List[dict] = field(default_factory=list)        # decided items the sheet no longer has


def _n(s: str) -> str:
    return td.name_key(s)


def structure(sheet: str):
    return tsg.parse_sheet(sheet or "", mode="template").structure


def clean(entries) -> List[dict]:
    return td.clean_ledger(entries or [])


def normal_key(paragraph: str, structure_name: str) -> str:
    return td.normal_key(paragraph, structure_name)


def negative_key(paragraph: str, text: str) -> str:
    return td.negative_key(paragraph, text)


def normal_label(key: str) -> Tuple[str, str]:
    """(paragraph, structure or negative text) of a normal key."""
    try:
        para, label, _ = td.split_normal_key(key)
    except td.DecisionError as e:
        raise Rejected(str(e)) from e
    return para, label


def check(kind: str, key: str, choice: dict) -> Tuple[str, dict]:
    """(key, choice) in the ledger's canonical form; Rejected when code cannot apply it."""
    try:
        return td.validate(kind, key, choice)
    except td.DecisionError as e:
        raise Rejected(str(e)) from e


# ── concepts ────────────────────────────────────────────────────────────────────────────────────────────────────
def concept_states(name: str) -> Dict[str, Optional[str]]:
    """state name -> the standard condition under which that state's wording applies (None: the usual state)."""
    return dict(td.CONCEPTS[name].states)


def condition_for(name: str, given: str) -> str:
    """The standard condition named by `given` (a state name such as "compared" / "not_given", or the condition
    text itself); "" when it names none."""
    g = _n(given)
    states = td.CONCEPTS[name].states
    if g in states:
        return states[g] or ""
    return next((c for c in td.CONCEPTS[name].conditions if _n(c) == g), "")


def concept_choice(state: str, default: str, when_met: str, condition: str = "") -> dict:
    """The ledger choice for a concept in one of CONCEPT_STATES. "dictated" is use False + dictated True with the
    wording blanked (the ledger's form)."""
    if state == "dictated":
        return {"use": False, "dictated": True, "default": "", "when_met": "", "condition": ""}
    if state == "not_used":
        return {"use": False, "dictated": False, "default": "", "when_met": "", "condition": ""}
    return {"use": True, "dictated": False, "default": default or "", "when_met": when_met or "",
            "condition": condition or ""}


def concept_state(choice: Optional[dict]) -> Tuple[str, str, str, str]:
    """(state, default wording, wording when its condition is met, condition) of a concept choice."""
    c = choice or {}
    if c.get("dictated"):
        return "dictated", "", "", ""
    if not c.get("use"):
        return "not_used", "", "", ""
    return "used", c.get("default", "") or "", c.get("when_met", "") or "", c.get("condition", "") or ""


def usual_question(name: str) -> str:
    """The Rules step's own question for a concept with no base state whose usual state is unknown (contrast)."""
    return trc.usual_question(name)


def concept_owner(sheet: str, ledger: List[dict], text: str) -> Optional[str]:
    """The concept whose wording `text` is: decided in the ledger, or the target / wording of a rule carrying a
    standard condition in the sheet. Such a line is the concept's, never a FIXED decision's."""
    k = norm_key(text or "")
    if not k:
        return None
    for e in ledger or []:
        if e.get("kind") == "concept":
            ch = e.get("choice") or {}
            if k in {norm_key(ch.get("default", "")), norm_key(ch.get("when_met", ""))} - {""}:
                return e["key"]
    for r in structure(sheet).rules:
        name = td.concept_of_condition(r.condition) if r.condition_source == "context" else None
        if name and k in {norm_key(r.target or ""), norm_key(r.then_text or "")} - {""}:
            return name
    return None


# ── reading and writing ─────────────────────────────────────────────────────────────────────────────────────────
def current(sheet: str, kind: str, key: str) -> Optional[dict]:
    """The choice the sheet expresses now for (kind, key); None when a normal's paragraph is gone."""
    try:
        return tla.observe(structure(sheet), kind, key)
    except (td.DecisionError, KeyError, StopIteration) as e:
        raise Rejected(str(e)) from e


def entry(ledger: List[dict], kind: str, key: str) -> Optional[dict]:
    try:
        return td.find(ledger or [], kind, key)
    except td.DecisionError:
        return None


def listed_values(sheet: str) -> List[str]:
    return [x for r in structure(sheet).rules if r.effect == "list_missing" for x in r.items]


def seed_values(ledger: List[dict], sheet: str) -> List[dict]:
    """Before the first value decision, the values the sheet lists now become default entries: once the ledger has
    any value entry it owns the whole list, so a single chat change must not empty it."""
    out = list(ledger or [])
    if any(e.get("kind") == "value" for e in out):
        return out
    for name in listed_values(sheet):
        try:
            out, _ = td.set_decision(out, "value", name, {"need": "every"}, source="default", by="code")
        except td.DecisionError:
            continue
    return out


def values(sheet: str, ledger: List[dict]) -> List[Tuple[str, str]]:
    """(name, need) of every value: the ledger's entries, or the sheet's list when the ledger has none."""
    return [(e["key"], e["choice"]["need"]) for e in seed_values(ledger, sheet) if e["kind"] == "value"]


def set_choice(ledger: List[dict], kind: str, key: str, choice: dict,
               route: Optional[str] = None) -> Tuple[List[dict], Optional[dict]]:
    """One chat decision (source "chat", by the radiologist); `route` marks how it was reached (ROUTES). Returns the
    ledger and the change, or None when the choice was already so."""
    if route is not None and route not in ROUTES:
        raise Rejected(f"unknown route {route!r}")
    try:
        out, change = td.set_decision(list(ledger or []), kind, key, choice, source="chat")
    except td.DecisionError as e:
        raise Rejected(str(e)) from e
    if route:
        e = td.find(out, kind, key)
        out = [{**x, "route": route} if x is e else x for x in out]
    return out, (dict(change) if change else None)


def undo(ledger: List[dict], change: dict) -> List[dict]:
    """Reverse one change this router made (td.undo_change), only while its entry still holds it: a later turn's
    change is never undone."""
    e = entry(ledger, change["kind"], change["key"])
    if e is None or e.get("choice") != change.get("new"):
        return list(ledger or [])
    return td.undo_change(list(ledger), change)


def rekey_fixed(ledger: List[dict], old: str, new: str) -> Tuple[List[dict], Optional[dict]]:
    """A decided FIXED line follows its rewording (td.rekey_decision); (ledger, None) when it is not decided."""
    if entry(ledger, "fixed", old) is None:
        return list(ledger or []), None
    try:
        out, change = td.rekey_decision(list(ledger), "fixed", old, new, source="chat")
    except td.DecisionError as e:
        raise Rejected(str(e)) from e
    return out, dict(change)


def restore(ledger: List[dict], e: dict) -> List[dict]:
    """A dropped entry put back (undo of a removed paragraph). Client-sent, so validated first."""
    if not isinstance(e, dict):
        raise Rejected("entry: object expected")
    check(e.get("kind", ""), e.get("key", ""), e.get("choice") or {})
    if entry(ledger, e["kind"], e["key"]) is not None:
        return list(ledger or [])
    return [*(ledger or []), *clean([e])]


def note(change: Optional[dict]) -> str:
    """"This changes something you confirmed: …" for a confirmed item, else ""."""
    return td.describe_change(change) if change else ""


def card(kind: str, key: str, proposed: dict) -> Optional[dict]:
    """The Rules step's one-tap card for this proposal, or None when code cannot make one."""
    try:
        return trc.card_for_change(kind, key, proposed)
    except td.DecisionError:
        return None


def paragraph_entries(ledger: List[dict], paragraph: str) -> List[dict]:
    out = []
    for e in ledger or []:
        if e.get("kind") != "normal":
            continue
        try:
            para, _, _ = td.split_normal_key(e["key"])
        except td.DecisionError:
            continue
        if _n(para) == _n(paragraph):
            out.append(e)
    return out


def rekey_paragraph(ledger: List[dict], old: str, new: str) -> List[dict]:
    moved = paragraph_entries(ledger, old)
    out = []
    for e in ledger or []:
        if any(e is m for m in moved):
            _, label, neg = td.split_normal_key(e["key"])
            e = {**e, "key": td.negative_key(new, label) if neg else td.normal_key(new, label)}
        out.append(e)
    return out


async def save(sheet: str, previous: str, ledger: List[dict]) -> Saved:
    """The save function (origin "chat"), which applies the ledger last."""
    v = await tsave.vet_sheet(sheet, origin="chat", previous=previous, ledger=list(ledger or []))
    return Saved(v.status, v.sheet, list(v.ledger), v.message or "", [dict(c) for c in v.ledger_changes],
                 list(v.ledger_cards or []), list(v.ledger_unmatched or []))
