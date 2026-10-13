"""One-tap decision cards (Rules-step spec, "Cards"): one shape for the Rules step, the Style step and the chat-edit
router's uncertain changes. A card names a ledger item (ledger_kind, key) and offers choices, each carrying the
ledger choice it records (None: the radiologist writes the wording). Answering a card is set_decision on its item.

Card: {"id", "kind", "step", "title", "evidence": [{"reports": [..], "quote": str | None}], "ledger_kind", "key",
       "choices": [{"id", "label", "choice": dict | None}], "selected": choice id | None, "rank", "wording"?}

Phase 1 holds the card shapes and card_for_change (template_ledger_apply.reconcile_chat returns them); the decision
run's build_cards joins them in Phase 2."""
from __future__ import annotations

from typing import List, Optional

from . import template_decisions as td

_RANK = {"disagree": 0, "value": 1, "concept": 2, "fixed": 3, "normal": 4, "uncovered": 5}


def _choice(cid: str, label: str, choice: Optional[dict]) -> dict:
    return {"id": cid, "label": label, "choice": choice}


def value_card(name: str, evidence: List[dict], selected: Optional[str] = None, step: str = "rules") -> dict:
    return {"id": f"value:{td._name(name)}", "kind": "value", "step": step, "title": name, "evidence": evidence,
            "ledger_kind": "value", "key": name,
            "choices": [_choice("every", "Every report", {"need": "every"}),
                        _choice("relevant", "Only when relevant", {"need": "relevant"}),
                        _choice("not_needed", "Not needed", {"need": "not_needed"})],
            "selected": selected, "rank": _RANK["value"]}


def concept_card(concept: str, default: str, when_met: str, evidence: List[dict], condition: str = "",
                 step: str = "rules") -> dict:
    """Study-level wording. Never pre-ticked (product decision D1): the radiologist always sees which wording is
    printed and when the other replaces it (`condition`)."""
    return {"id": f"concept:{concept}", "kind": "concept", "step": step, "title": td.CONCEPTS[concept].label,
            "evidence": evidence, "ledger_kind": "concept", "key": concept,
            "wording": {"default": default, "when_met": when_met, "condition": condition},
            "choices": [_choice("keep", "Keep", {"use": True, "default": default, "when_met": when_met,
                                                 "condition": condition, "dictated": False}),
                        _choice("edit", "Edit wording", None),
                        _choice("not_used", "Not used", {"use": False, "default": "", "when_met": "", "condition": "",
                                                         "dictated": False})],
            "selected": None, "rank": _RANK["concept"]}


def fixed_card(text: str, step: str = "style", selected: Optional[str] = None) -> dict:
    return {"id": f"fixed:{td.match_key('fixed', text)}", "kind": "fixed", "step": step, "title": text,
            "evidence": [], "ledger_kind": "fixed", "key": text,
            "choices": [_choice("always", "Always the same", {"keep": "always"}),
                        _choice("dictated", "Only when dictated", {"keep": "dictated"}),
                        _choice("remove", "Remove", {"keep": "remove"})],
            "selected": selected, "rank": _RANK["fixed"]}


def normal_card(key: str, text: str, step: str = "style") -> dict:
    para, label, neg = td.split_normal_key(key)
    return {"id": f"normal:{td.match_key('normal', key)}", "kind": "normal", "step": step,
            "title": para if neg else f"{para}: {label}", "evidence": [], "ledger_kind": "normal", "key": key,
            "wording": {"text": text},
            "choices": [_choice("keep", "Keep", {"text": text}), _choice("edit", "Edit wording", None),
                        _choice("remove", "Remove", {"text": ""})],
            "selected": None, "rank": _RANK["normal"]}


def card_for_change(kind: str, key: str, proposed: dict) -> dict:
    """The one-tap card for a change code could not apply as given (the chat-edit router's uncertain or rejected
    parts), prefilled with the proposed wording and not pre-selected. DecisionError on an invalid proposal."""
    key, proposed = td.validate(kind, key, proposed)
    if kind == "value":
        return value_card(key, [], step="chat")
    if kind == "concept":
        return concept_card(key, proposed.get("default", ""), proposed.get("when_met", ""), [],
                            proposed.get("condition", ""), step="chat")
    if kind == "fixed":
        return fixed_card(key, step="chat")
    return normal_card(key, proposed.get("text", ""), step="chat")
