"""The decision ledger (Rules-step spec 2026-10-13-template-rules-step-design): what the radiologist settled about a
template's rules, stored as template_config["decisions"] and applied by code on every save
(template_ledger_apply.apply_ledger, called by template_sheet_save.vet_sheet).

One entry per (kind, key): {"kind", "key", "choice", "by", "at", "source"}.

    kind     key                                             choice
    value    the value's short name                          {"need": "every" | "relevant" | "not_needed"}
    concept  comparison | contrast | sequences | limitation  {"use": bool, "default": str, "when_met": str,
                                                              "condition": str, "dictated": bool}
    fixed    the FIXED line's text                           {"keep": "always" | "dictated" | "remove"}
    normal   normal_key(paragraph, structure) for a NORMAL,  {"text": str}  ("" = removed / left unmentioned)
             negative_key(paragraph, text) for a NEGATIVE

A used concept is written as: FIXED default + RULE WHEN [context: condition] REPLACE default WITH when_met; FIXED
default + SUPPRESS default (no alternative wording: the line is dropped when the dictation contradicts it); or USE
when_met (no default). `condition` is one of the concept's standard conditions, the opposite of the default's state.
"Use whichever is dictated" is {"use": false, "dictated": true}: no line, recorded as its own choice.

source: creation | chat | first_use_review | default (a skipped step's pre-ticked choice; never "confirmed").
by: "radiologist" (a card or a chat turn) or "code" (a default).

This module is the API the Rules-step cards and the chat-edit router both call: set_decision validates and records
one change and returns it (with the old entry whole); undo_change reverses it; ledger_from_changes records a batch of card answers;
describe_change words a change for the radiologist. Keys are matched by match_key (case and spacing ignored; a final
full stop ignored for sentence keys), never by free-text similarity."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, TypedDict

from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

KINDS = ("value", "concept", "fixed", "normal")
SOURCES = ("creation", "chat", "first_use_review", "default")
BY = ("radiologist", "code")
NEEDS = ("every", "relevant", "not_needed")
KEEPS = ("always", "dictated", "remove")
MAX_VALUE_WORDS = 8
_SEP = " :: "


class DecisionError(ValueError):
    """A change code cannot apply as given (unknown kind or concept, malformed key or choice)."""


class Entry(TypedDict):
    kind: str
    key: str
    choice: dict
    by: str
    at: str
    source: str


class Change(TypedDict):
    kind: str
    key: str
    old: Optional[dict]   # the old entry whole (choice, by, at, source); None: a new entry
    new: dict             # the new choice
    source: str
    confirmed: bool       # the old entry was the radiologist's (any source but "default")


@dataclass(frozen=True)
class Concept:
    name: str
    label: str                          # how a card and a chat reply name it
    states: Dict[str, Optional[str]]    # state of a wording -> the standard condition under which it applies (None:
                                        # the usual state, written as the default)
    question: str                       # decision run: does an example report state this concept? (Jev noul)
    roles: Tuple[str, ...]              # home section roles, in preference order

    @property
    def conditions(self) -> Tuple[str, ...]:
        return tuple(c for c in self.states.values() if c)


# The standard study-level concepts. Their condition texts are fixed: apply_ledger finds a concept's lines by them,
# and Generate resolves them per case (template_context_rules). Contrast has a condition for both states, so its
# default is whichever wording is usual in the template's own examples (product decision D1, 2026-10-13); the other
# three have one condition and a base state. Case-agnostic wording only.
CONCEPTS: Dict[str, Concept] = {
    "comparison": Concept(
        "comparison", "Comparison with previous imaging",
        {"none": None, "compared": "the dictation names a previous imaging study for comparison"},
        "The REPORT says whether previous imaging was available or was compared with this study.",
        ("comparison", "technique", "history")),
    "contrast": Concept(
        "contrast", "Contrast",
        {"given": "the dictation states a contrast agent was given",
         "not_given": "the dictation states no contrast agent was given"},
        "The REPORT says whether a contrast agent was given for this study.", ("technique",)),
    "sequences": Concept(
        "sequences", "Parts of the study not performed",
        {"complete": None, "not_performed": "the dictation states that part of the planned acquisition was not performed"},
        "The REPORT lists the acquisitions performed (sequences, series, phases or views), or says the planned "
        "protocol was complete or incomplete.",
        ("technique",)),
    "limitation": Concept(
        "limitation", "Technical limitation",
        {"none": None, "limited": "the dictation states a technical limitation of the study"},
        "The REPORT says whether the image quality was adequate, or comments on a technical limitation of the study "
        "(for example artefact or incomplete coverage).",
        ("technique",)),
}
STANDARD_CONDITIONS = {" ".join(c.lower().split()): name for name, k in CONCEPTS.items() for c in k.conditions}


def concept_of_condition(condition: str) -> Optional[str]:
    """The concept whose standard condition this is (case and spacing ignored), else None."""
    return STANDARD_CONDITIONS.get(" ".join((condition or "").lower().split()))


def _name(s: str) -> str:
    return " ".join((s or "").lower().split())


def name_key(s: str) -> str:
    """The comparison form of a value or structure name (lower case, single spaces)."""
    return _name(s)


def structure_label(structure: str) -> str:
    """A NORMAL's structure label without the quotes the grammar allows (NORMAL ["ROTATOR CUFF"])."""
    s = (structure or "").strip()
    return s[1:-1].strip() if len(s) > 2 and s.startswith('"') and s.endswith('"') else s


def normal_key(paragraph: str, structure: str) -> str:
    return f"{paragraph.strip()}{_SEP}{structure_label(structure)}"


def negative_key(paragraph: str, text: str) -> str:
    return f'{paragraph.strip()}{_SEP}"{text.strip()}"'


def split_normal_key(key: str) -> Tuple[str, str, bool]:
    """(paragraph, structure or negative text, is_negative)."""
    para, sep, label = (key or "").partition(_SEP)
    label = label.strip()
    if not sep or not para.strip() or not label:
        raise DecisionError(f"normal key {key!r}: '<paragraph> :: <structure>' or '<paragraph> :: \"<text>\"'")
    if len(label) > 2 and label.startswith('"') and label.endswith('"'):
        return para.strip(), label[1:-1].strip(), True
    return para.strip(), label, False


def match_key(kind: str, key: str) -> str:
    if kind == "normal":
        para, label, neg = split_normal_key(key)
        return f"{_name(para)}{_SEP}" + (f'"{norm_key(label)}"' if neg else _name(label))
    if kind == "fixed":
        return norm_key(key)
    return _name(key)


_ACRONYM_START = re.compile(r"[a-z]+[A-Z]")   # a lowercase-led word that holds a capital ("eGFR", "pH" is not)


def is_sentence(text: str) -> bool:
    """A full sentence, the shape a wording that replaces a line or prints on its own (REPLACE ... WITH, USE) must
    have, since a fragment would print mid-sentence. The rule:
    - it starts with a capital letter, a {slot}, a digit ("3 phases were acquired."), or a lowercase-led word that
      holds a capital (an acronym such as "eGFR ...");
    - it ends with "." or ":". A wording that ends on a bare slot ("... of {date}") or with no full stop is a
      fragment.
    Only the edges are checked; the words between them are the radiologist's."""
    t = (text or "").strip()
    if not t or t[-1] not in ".:":
        return False
    return t[0].isupper() or t[0] == "{" or t[0].isdigit() or bool(_ACRONYM_START.match(t))


def fragment_wording(entry: dict) -> Optional[str]:
    """The wording of a stored used concept whose replacement / printed wording is not a full sentence (kept in the
    ledger, never applied as a rule: apply_ledger writes no line for it and returns it as unmatched, a review card)."""
    choice = (entry or {}).get("choice") or {}
    if entry.get("kind") != "concept" or not choice.get("use"):
        return None
    when_met = choice.get("when_met") or ""
    return when_met if when_met and not is_sentence(when_met) else None


def _text(v, what: str, allow_slots: bool = True) -> str:
    if not isinstance(v, str):
        raise DecisionError(f"{what}: text expected")
    t = " ".join(v.split())
    if '"' in t or "“" in t or "”" in t:
        raise DecisionError(f"{what}: no double quotes")
    if not allow_slots and ("{" in t or "}" in t):
        raise DecisionError(f"{what}: no value to fill in")
    return t


def validate(kind: str, key: str, choice: dict, strict: bool = True) -> Tuple[str, dict]:
    """(key, choice) in canonical form; DecisionError when code cannot apply it. `strict` False (stored entries,
    clean_ledger) lets a concept wording that is not a full sentence through, so it can be asked about again
    (fragment_wording); a new choice is always strict."""
    if kind not in KINDS:
        raise DecisionError(f"unknown kind {kind!r}")
    if not isinstance(choice, dict):
        raise DecisionError("choice: object expected")
    key = " ".join((key or "").split())
    if kind == "value":
        if not key or len(key.split()) > MAX_VALUE_WORDS or any(c in key for c in '"|[]{}'):
            raise DecisionError(f"value name {key!r}: a short plain name")
        if choice.get("need") not in NEEDS:
            raise DecisionError(f"value need: one of {NEEDS}")
        return key, {"need": choice["need"]}
    if kind == "concept":
        if key not in CONCEPTS:
            raise DecisionError(f"unknown concept {key!r}")
        use = choice.get("use")
        if not isinstance(use, bool):
            raise DecisionError("concept use: true or false")
        if not use:
            return key, {"use": False, "default": "", "when_met": "", "condition": "",
                         "dictated": bool(choice.get("dictated"))}
        default = _text(choice.get("default", ""), "concept default")
        when_met = _text(choice.get("when_met", ""), "concept wording")
        if not (default or when_met):
            raise DecisionError("concept: a used concept needs wording")
        if strict and when_met and not is_sentence(when_met):
            raise DecisionError("concept wording: a full sentence (a capital or a {slot} first, '.' or ':' last)")
        if default and when_met and norm_key(default) == norm_key(when_met):
            raise DecisionError("concept: the two wordings are the same")
        conds = CONCEPTS[key].conditions
        given = " ".join((choice.get("condition") or "").lower().split())
        if not given and len(conds) == 1:
            condition = conds[0]
        else:
            condition = next((c for c in conds if c == given), "")
            if not condition:
                raise DecisionError(f"concept {key}: condition must be one of {conds}")
        return key, {"use": True, "default": default, "when_met": when_met, "condition": condition, "dictated": False}
    if kind == "fixed":
        key = _text(key, "fixed line")
        if not key:
            raise DecisionError("fixed line: text expected")
        if choice.get("keep") not in KEEPS:
            raise DecisionError(f"fixed keep: one of {KEEPS}")
        return key, {"keep": choice["keep"]}
    split_normal_key(key)
    return key, {"text": _text(choice.get("text", ""), "normal wording", allow_slots=False)}


def find(ledger: List[Entry], kind: str, key: str) -> Optional[Entry]:
    k = match_key(kind, key)
    return next((e for e in ledger or [] if e.get("kind") == kind and match_key(kind, e["key"]) == k), None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_decision(ledger: List[Entry], kind: str, key: str, choice: dict, *, source: str,
                 by: str = "radiologist", at: Optional[str] = None) -> Tuple[List[Entry], Optional[Change]]:
    """The ledger with (kind, key) set to `choice`, and the change (None when the choice is unchanged; a
    re-confirmation still updates source, by and at). Never mutates `ledger`. DecisionError when invalid."""
    if source not in SOURCES:
        raise DecisionError(f"unknown source {source!r}")
    if by not in BY:
        raise DecisionError(f"unknown by {by!r}")
    key, choice = validate(kind, key, choice)
    if kind == "fixed" and norm_key(key) in concept_texts(ledger):
        raise DecisionError("this line belongs to a study-level wording; change it there")
    old = find(ledger, kind, key)
    entry: Entry = {"kind": kind, "key": old["key"] if old else key, "choice": choice, "by": by,
                    "at": at or _now(), "source": source}
    out = [entry if e is old else e for e in ledger] if old else [*(ledger or []), entry]
    if old and old["choice"] == choice:
        return out, None
    return out, Change(kind=kind, key=entry["key"], old=dict(old) if old else None, new=choice, source=source,
                       confirmed=bool(old) and old.get("source") != "default")


def concept_texts(ledger: List[Entry]) -> set:
    """norm_key of every wording a decided concept owns (its lines are the concept's, never a fixed entry's)."""
    return {norm_key(t) for e in ledger or [] if e.get("kind") == "concept"
            for t in ((e.get("choice") or {}).get("default", ""), (e.get("choice") or {}).get("when_met", "")) if t}


def rekey_decision(ledger: List[Entry], kind: str, key: str, new_key: str, *, source: str,
                   by: str = "radiologist", at: Optional[str] = None) -> Tuple[List[Entry], Change]:
    """The entry (kind, key) moved to `new_key` with its choice kept (a reworded line), and the change (its old
    entry carries the old key). Never mutates `ledger`. DecisionError when invalid."""
    if source not in SOURCES:
        raise DecisionError(f"unknown source {source!r}")
    if by not in BY:
        raise DecisionError(f"unknown by {by!r}")
    old = find(ledger, kind, key)
    if old is None or find(ledger, kind, new_key) is not None:
        raise DecisionError(f"{kind} {key!r}: nothing to move, or {new_key!r} is already decided")
    new_key, choice = validate(kind, new_key, old["choice"])
    if kind == "fixed" and norm_key(new_key) in concept_texts(ledger):
        raise DecisionError("this line belongs to a study-level wording; change it there")
    entry: Entry = {"kind": kind, "key": new_key, "choice": choice, "by": by, "at": at or _now(), "source": source}
    return ([entry if e is old else e for e in ledger],
            Change(kind=kind, key=new_key, old=dict(old), new=choice, source=source,
                   confirmed=old.get("source") != "default"))


def remove_decision(ledger: List[Entry], kind: str, key: str) -> List[Entry]:
    """The ledger without (kind, key)."""
    old = find(ledger, kind, key)
    return [e for e in ledger if e is not old]


def undo_change(ledger: List[Entry], change: Change) -> List[Entry]:
    """Reverse one change (a rejected router change): the old entry back whole (choice, by, at, source), or the entry
    removed when the change added it."""
    if change["old"] is None:
        return remove_decision(ledger, change["kind"], change["key"])
    cur = find(ledger, change["kind"], change["key"])
    if cur is None:
        return [*ledger, dict(change["old"])]
    return [dict(change["old"]) if e is cur else e for e in ledger]


FORGET = {"forget": True}   # a card answer that removes the ledger entry (an unmatched entry's "Forget this decision")


def ledger_from_changes(changes: List[dict], base: Optional[List[Entry]] = None,
                        source: str = "creation") -> Tuple[List[Entry], List[str]]:
    """Record card answers [{"kind", "key", "choice", "source"?}] on `base`. A change with source "default" is
    recorded as by "code"; a change whose choice is FORGET removes the entry. Returns (ledger, one message per change
    code could not apply; those are skipped)."""
    ledger: List[Entry] = list(base or [])
    errors: List[str] = []
    for c in changes or []:
        src = c.get("source") or source
        if c.get("choice") == FORGET:
            ledger = remove_decision(ledger, c.get("kind", ""), c.get("key", ""))
            continue
        try:
            ledger, _ = set_decision(ledger, c.get("kind", ""), c.get("key", ""), c.get("choice") or {},
                                     source=src, by="code" if src == "default" else "radiologist")
        except DecisionError as e:
            errors.append(f"{c.get('kind')} {c.get('key')!r}: {e}")
    if errors:
        logger.warning("[ledger] %d change(s) not recorded: %s", len(errors), errors[:5])
    return ledger, errors


_NEED = {"every": "every report", "relevant": "only when relevant", "not_needed": "not needed"}
_KEEP = {"always": "always printed", "dictated": "only when dictated", "remove": "removed"}


def item_label(kind: str, key: str) -> str:
    if kind == "concept":
        return CONCEPTS[key].label if key in CONCEPTS else key
    if kind == "fixed":
        return f'"{key}"'
    if kind == "normal":
        para, label, neg = split_normal_key(key)
        return f'{para}: "{label}"' if neg else f"{para}: {label}"
    return key


def state_label(kind: str, choice: Optional[dict]) -> str:
    if choice is None:
        return "not set"
    if kind == "value":
        return _NEED.get(choice.get("need"), "not set")
    if kind == "fixed":
        return _KEEP.get(choice.get("keep"), "not set")
    if kind == "concept":
        if not choice.get("use"):
            return "whichever is dictated" if choice.get("dictated") else "not used"
        return f'"{choice.get("default") or choice.get("when_met")}"'
    return f'"{choice.get("text")}"' if choice.get("text") else "removed"


def describe_change(change: Change) -> str:
    """The reply line for a change to a confirmed item; "" for a new or default item."""
    if not change.get("confirmed"):
        return ""
    k = change["kind"]
    old_key = change["old"].get("key", change["key"])
    if match_key(k, old_key) != match_key(k, change["key"]):   # a reworded line (rekey_decision)
        return f"This changes something you confirmed: {item_label(k, old_key)} → {item_label(k, change['key'])}."
    return (f"This changes something you confirmed: {item_label(k, change['key'])} "
            f"{state_label(k, change['old']['choice'])} → {state_label(k, change['new'])}.")


def clean_ledger(entries) -> List[Entry]:
    """Stored or client-sent entries, re-validated: an entry code cannot apply is dropped (logged), never guessed. An
    unknown source or by becomes "default" / "code" (never counted as the radiologist's confirmation)."""
    out: List[Entry] = []
    for e in entries or []:
        try:
            if not isinstance(e, dict):
                raise DecisionError("entry: object expected")
            key, choice = validate(e.get("kind", ""), e.get("key", ""), e.get("choice") or {}, strict=False)
        except DecisionError as err:
            logger.warning("[ledger] stored entry dropped: %s", err)
            continue
        out.append({"kind": e["kind"], "key": key, "choice": choice,
                    "by": e.get("by") if e.get("by") in BY else "code", "at": str(e.get("at") or ""),
                    "source": e.get("source") if e.get("source") in SOURCES else "default"})
    return out
