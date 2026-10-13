"""One-tap decision cards (Rules-step spec, "Cards"): one shape for the Rules step, the Style step and the chat-edit
router's uncertain changes. A card names a ledger item (ledger_kind, key) and offers choices, each carrying the
ledger choice it records (None: the radiologist writes the wording). Answering a card is set_decision on its item.

Card: {"id", "kind", "step", "title", "evidence": [{"reports": [..], "quote": str | None}], "ledger_kind", "key",
       "choices": [{"id", "label", "choice": dict | None}], "selected": choice id | None, "rank", "wording"?}

build_cards(run, n_examples) -> {"cards", "more", "kept", "defaults"}: exceptions only, ranked (examples disagree,
then uncertain values, then concept wording); at most MAX_CARDS open, the rest in "more"; items every example agrees
on fold into "kept" (pre-ticked); nothing seen in fewer than every example is pre-ticked; "defaults" are the
pre-ticked choices, recorded with source "default" when the step is skipped or the kept items are left alone.
Only values every example states are kept; a study-level concept is always a card (D1)."""
from __future__ import annotations

from typing import Dict, List, Optional

from . import template_decisions as td
from .template_decision_run import DecisionRun

MAX_CARDS = 8
MAJORITY_MIN = 2   # a concept with no base state (contrast) takes the usual state from the examples only when at least
                   # this many state it and more than state the other; otherwise the card asks (after the lab, 2026-10-13)
_USUAL = {"contrast": ("Is contrast usually given for this scan?",
                       {"given": "Usually given", "not_given": "Usually not given"})}
_RANK = {"disagree": 0, "value": 1, "concept": 2, "fixed": 3, "normal": 4, "uncovered": 5}


def _reports(nums) -> str:
    nums = sorted(set(nums))
    return ("report " if len(nums) == 1 else "reports ") + ", ".join(str(n) for n in nums)


def evidence_line(e: dict) -> str:
    """"reports 1, 2, 4: 'ECV 28%'" or "report 3: not stated" (never percentages)."""
    return f"{_reports(e['reports'])}: " + (f"'{e['quote']}'" if e.get("quote") else "not stated")


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


def disagree_card(concept: str, options: List[dict], other: str, role: str, evidence: List[dict],
                  condition: str) -> dict:
    """options: [{"text", "reports"}] for one side; `other` the single wording of the other side ("" if none).
    "Use whichever is dictated" is its own choice ({"use": false, "dictated": true}), not "not used"."""
    choices = []
    for k, o in enumerate(options):
        default, when_met = (o["text"], other) if role == "default" else (other, o["text"])
        choices.append(_choice(f"w{k}", f"Use \u201c{o['text']}\u201d",
                               {"use": True, "default": default, "when_met": when_met, "condition": condition,
                                "dictated": False}))
    choices.append(_choice("dictated", "Use whichever is dictated",
                           {"use": False, "default": "", "when_met": "", "condition": "", "dictated": True}))
    return {"id": f"disagree:{concept}", "kind": "disagree", "step": "rules",
            "title": f"Your examples word {td.CONCEPTS[concept].label.lower()} differently", "evidence": evidence,
            "ledger_kind": "concept", "key": concept, "choices": choices, "selected": None, "rank": _RANK["disagree"]}


def usual_card(concept: str, wordings: Dict[str, str], evidence: List[dict]) -> dict:
    """A concept with no base state whose examples show no clear majority: which state is usual? Each choice makes
    that state's wording the default and the other state's wording the replacement under the other state's
    condition. Never pre-ticked."""
    c = td.CONCEPTS[concept]
    title, labels = _USUAL.get(concept, (f"Which is usual: {c.label.lower()}?", {}))
    choices = []
    for state in c.states:
        other = next(s for s in c.states if s != state)
        choices.append(_choice(f"usual:{state}", labels.get(state, f"Usually {state.replace('_', ' ')}"),
                               {"use": True, "default": wordings.get(state, ""), "when_met": wordings.get(other, ""),
                                "condition": c.states[other], "dictated": False}))
    choices += [_choice("edit", "Edit wording", None),
                _choice("not_used", "Not used", {"use": False, "default": "", "when_met": "", "condition": "",
                                                 "dictated": False})]
    return {"id": f"concept:{concept}", "kind": "concept", "step": "rules", "title": title, "evidence": evidence,
            "ledger_kind": "concept", "key": concept, "usual": dict(wordings), "choices": choices, "selected": None,
            "rank": _RANK["concept"]}


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


def uncovered_card(paragraph: str, structure: str) -> dict:
    key = td.normal_key(paragraph, structure)
    return {"id": f"uncovered:{td.match_key('normal', key)}", "kind": "uncovered", "step": "style",
            "title": f"{paragraph}: {structure}", "evidence": [], "ledger_kind": "normal", "key": key,
            "choices": [_choice("add", "Add wording", None), _choice("leave", "Leave unmentioned", {"text": ""})],
            "selected": None, "rank": _RANK["uncovered"]}


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


def defaults_of(cards: List[dict]) -> List[dict]:
    """The pre-ticked choice of each card, as a change [{kind, key, choice}]."""
    out = []
    for c in cards:
        ch = next((x["choice"] for x in c["choices"] if x["id"] == c.get("selected")), None)
        if ch is not None:
            out.append({"kind": c["ledger_kind"], "key": c["key"], "choice": ch})
    return out


def _value_cards(run: DecisionRun, n: int) -> List[dict]:
    out = []
    for v in run.values:
        reports = sorted({q.report for q in v.quotes})
        ev = [{"reports": reports, "quote": v.quotes[0].text}]
        missing = [k for k in range(1, n + 1) if k not in reports]
        if missing:
            ev.append({"reports": missing, "quote": None})
        out.append(value_card(v.name, ev, selected=None if missing else "every"))
    return out


def _concept_cards(run: DecisionRun, n: int) -> List[dict]:
    """One card per concept the examples word (never folded into "kept"). The default is the base state's wording
    (no previous study, everything performed, no limitation); for contrast, whose two states both have a condition,
    it is the state the examples use most (D1) when that is a clear majority (MAJORITY_MIN reports and more than the
    other state), and the condition stored is the opposite state's. Without a clear majority the card asks which
    state is usual (usual_card)."""
    if run.states is None:
        return []
    out = []
    for name, c in td.CONCEPTS.items():
        by_state: Dict[str, List[dict]] = {s: [] for s in c.states}
        seen: Dict[str, dict] = {}
        for w in run.concepts:
            if w.concept != name:
                continue
            k = f"{w.state}:{td.match_key('fixed', w.text)}"
            if k in seen:
                seen[k]["reports"] = sorted(set(seen[k]["reports"]) | {q.report for q in w.quotes})
                continue
            seen[k] = {"text": w.text, "reports": sorted({q.report for q in w.quotes}), "quote": w.quotes[0].text}
            by_state[w.state].append(seen[k])
        if not any(by_state.values()):
            continue
        quoted = {r for ws in by_state.values() for w in ws for r in w["reports"]}
        stating = set(run.states.get(name) or []) | quoted     # a verified quote counts even when Jev missed it
        base = next((s for s, cond in c.states.items() if cond is None), None)
        silent = [k for k in range(1, n + 1) if k not in stating]
        if base is None:
            counts = {s: len({r for w in ws for r in w["reports"]}) for s, ws in by_state.items()}
            top = max(c.states, key=lambda s: counts[s])
            if counts[top] >= MAJORITY_MIN and all(counts[top] > v for s, v in counts.items() if s != top):
                base = top
            else:
                ev = [{"reports": w["reports"], "quote": w["quote"]} for ws in by_state.values() for w in ws]
                if silent:
                    ev.append({"reports": silent, "quote": None})
                wordings = {s: max(ws, key=lambda w: len(w["reports"]))["text"] for s, ws in by_state.items() if ws}
                out.append(usual_card(name, wordings, ev))
                continue
        other = next(s for s in c.states if s != base)
        condition = c.states[other]
        ev = [{"reports": w["reports"], "quote": w["quote"]} for w in [*by_state[base], *by_state[other]]]
        if silent:
            ev.append({"reports": silent, "quote": None})
        split = next((s for s in (base, other) if len(by_state[s]) > 1), None)
        if split:
            rest = by_state[other if split == base else base]
            out.append(disagree_card(name, by_state[split], rest[0]["text"] if len(rest) == 1 else "",
                                     "default" if split == base else "when_met", ev, condition))
            continue
        default = by_state[base][0]["text"] if by_state[base] else ""
        when_met = by_state[other][0]["text"] if by_state[other] else ""
        out.append(concept_card(name, default, when_met, ev, condition))
    return out


def build_cards(run: DecisionRun, n_examples: int) -> dict:
    if not run.ok:
        return {"cards": [], "more": [], "kept": [], "defaults": []}
    every = [*_value_cards(run, n_examples), *_concept_cards(run, n_examples)]
    kept = [c for c in every if c["selected"] is not None]
    open_ = sorted((c for c in every if c["selected"] is None),
                   key=lambda c: (c["rank"], -_stated_in(c)))
    # a value seen in only one report waits under "More" (after the lab, 2026-10-13), never in the main cards
    single = [c for c in open_ if c["kind"] == "value" and _stated_in(c) <= 1 and n_examples > 1]
    main = [c for c in open_ if c not in single]
    return {"cards": main[:MAX_CARDS], "more": [*main[MAX_CARDS:], *single], "kept": kept,
            "defaults": defaults_of(kept)}


def _stated_in(card: dict) -> int:
    return sum(len(e["reports"]) for e in card["evidence"] if e.get("quote"))


def current_value_cards(sheet: str, ledger: List[dict]) -> List[dict]:
    """The Required-values rows for a stored template (the refine panel): every LIST_MISSING item (selected as the
    ledger says, else "every") and every value the ledger records as only-when-relevant or not needed."""
    from . import template_sheet_grammar as tsg
    if not tsg.is_grammar_sheet(sheet or ""):
        return []
    st = tsg.parse_sheet(sheet, mode="template").structure
    out, seen = [], set()
    for name in [x for r in st.rules if r.effect == "list_missing" for x in r.items]:
        if td._name(name) in seen:
            continue
        e = td.find(ledger, "value", name)
        out.append(value_card(name, [], selected=e["choice"]["need"] if e else "every", step="review"))
        seen.add(td._name(name))
    for e in ledger or []:
        if e.get("kind") == "value" and td._name(e["key"]) not in seen:
            out.append(value_card(e["key"], [], selected=e["choice"]["need"], step="review"))
            seen.add(td._name(e["key"]))
    return out
