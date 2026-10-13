"""Structured changes from the router's targeted calls and their validation by code (spec Flow 2 and "Uncertain or
rejected changes become cards"; plan decisions 3-6). validate() turns one change into a Verdict:
  ledger  apply through the ledger (value, concept, fixed keep, normal reword/remove)
  edit    apply a code edit (layout, FIXED reword/add, NORMAL/NEGATIVE add); `choice` set = also a decision
  card    nothing applied; a prefilled card (the Rules step's card for ledger kinds, else a proposal card)
  ask     nothing applied; `reason` is the question in the reply
  reject  nothing applied; `reason` says why
New wording passes only when the instruction holds it word for word or the sheet already prints it; a {slot} must
be {study}, {date} or one the sheet already uses."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import List, Literal, Optional

from pydantic import BaseModel

from . import chat_router_edits as E
from . import chat_router_ledger as L
from . import chat_router_sheet as sh
from .hybrid_stack.template import norm_key


# ── what the targeted calls return ──────────────────────────────────────────────────────────────────────────────
class ValueChange(BaseModel):
    name: str
    to: Literal["every", "relevant", "not_needed"]
    sure: bool = True


class ConceptChange(BaseModel):
    concept: str
    state: Optional[Literal["used", "dictated", "not_used"]] = None
    default: Optional[str] = None
    when_met: Optional[str] = None
    condition: Optional[str] = None   # the state (from CURRENT) in which when_met applies; null keeps the current one
    sure: bool = True


class FixedChange(BaseModel):
    to: Literal["always", "dictated", "remove", "reword", "add"]
    line: str = ""
    text: str = ""
    paragraph: str = ""
    sure: bool = True


class NormalChange(BaseModel):
    paragraph: str
    to: Literal["reword", "removed", "add"]
    structure: str = ""
    negative: str = ""
    text: str = ""
    sure: bool = True


class LayoutChange(BaseModel):
    op: Literal["rename_paragraph", "move_paragraph", "remove_paragraph", "add_paragraph", "rename_section",
                "move_section", "remove_section", "add_section"]
    target: str = ""
    name: str = ""
    section: str = ""
    role: str = ""
    covers: List[str] = []
    before: str = ""
    after: str = ""
    sure: bool = True


class ValueOut(BaseModel):
    changes: List[ValueChange] = []
    question: str = ""


class ConceptOut(BaseModel):
    changes: List[ConceptChange] = []
    question: str = ""


class FixedOut(BaseModel):
    changes: List[FixedChange] = []
    question: str = ""


class NormalOut(BaseModel):
    changes: List[NormalChange] = []
    question: str = ""


class LayoutOut(BaseModel):
    changes: List[LayoutChange] = []
    question: str = ""


class StyleBlock(BaseModel):
    id: str
    text: str


class StyleOut(BaseModel):
    blocks: List[StyleBlock] = []
    summary: str = ""
    question: str = ""


OUTPUTS = {"value": ValueOut, "concept": ConceptOut, "fixed": FixedOut, "normal": NormalOut, "layout": LayoutOut,
           "style": StyleOut}


# ── verdicts ────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Verdict:
    kind: str
    action: str                     # ledger | edit | card | ask | reject
    key: str = ""
    choice: Optional[dict] = None
    op: Optional[dict] = None
    card: Optional[dict] = None
    claim: str = ""                 # the reply line once applied
    reason: str = ""                # ask / reject
    invented: bool = False          # the call said sure, but its wording is neither in the instruction nor the sheet
    change: Optional[dict] = None   # the structured change as the call returned it (evidence)
    route: str = ""                 # "llm_unsure": its kind was tagged in the unsure band (decision D-R2)
    detail: str = ""                # the internal reason for a reject (evidence only, never a reply)


@dataclass
class Ctx:
    sheet: str
    ledger: List[dict]
    instruction: str                # the wording new text must come from (instruction + a rejected original)
    confirmed: bool = False         # a tapped card: the wording and sureness checks are skipped


_SLOT = re.compile(r"\{[^{}\n]*\}")
STANDARD_SLOTS = frozenset({"{study}", "{date}"})
KIND_LABEL = {"value": "the required values", "concept": "the study-level statements",
              "fixed": "the sentences printed in every report", "normal": "the normal findings",
              "layout": "the sections and paragraphs", "style": "the style"}
REJECT = "I couldn't apply the change to {label} as asked. Could you say it another way?"


def _plain(s: str) -> str:
    return " ".join(re.sub(r"[\"“”‘’']", "", s or "").lower().split()).rstrip(".")


def in_instruction(text: str, instruction: str) -> bool:
    """The instruction holds `text` word for word (case, spacing, quote marks and a final full stop ignored)."""
    t = _plain(text)
    return bool(t) and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", _plain(instruction)) is not None


def in_sheet(text: str, sheet: str) -> bool:
    return any(l.keyword and norm_key(sh.quoted(l.text)) == norm_key(text) for l in sh.walk(sheet) if text)


def bad_slots(text: str, sheet: str) -> List[str]:
    allowed = STANDARD_SLOTS | set(_SLOT.findall(sheet or ""))
    return [s for s in _SLOT.findall(text or "") if s not in allowed]


_NEED_CLAIM = {"every": "{name} is now required in every report.",
               "relevant": "{name} is now stated only when relevant.",
               "not_needed": "{name} is no longer required."}
_KEEP_CLAIM = {"always": 'Every report now prints "{key}".', "dictated": '"{key}" is now printed only when dictated.',
               "remove": '"{key}" is no longer printed.'}


def claim_for(kind: str, key: str, choice: dict) -> str:
    """The reply line for a ledger write (also used for a tapped card)."""
    if kind == "value":
        return _NEED_CLAIM[choice["need"]].format(name=key)
    if kind == "fixed":
        return _KEEP_CLAIM[choice["keep"]].format(key=key)
    if kind == "concept":
        label = L.CONCEPTS.get(key, key)
        state, d, w, _ = L.concept_state(choice)
        if state == "not_used":
            return f"{label}: no longer stated."
        if state == "dictated":
            return f"{label}: reports now use whichever wording is dictated."
        if d and w:
            return f'{label}: reports now say "{d}", or "{w}" when it applies.'
        return f'{label}: reports now say "{d or w}".'
    para, label = L.normal_label(key)
    text = choice.get("text", "")
    return (f'{para}: the normal line for {label} now reads "{text}".' if text
            else f"{para}: {label} is no longer stated when normal.")


def proposal_card(v: Verdict) -> dict:
    """A one-tap card for a change with no ledger card (plan decision 5); Apply sends `apply` back unchanged."""
    apply = {"kind": v.kind, "key": v.key, "choice": v.choice, "op": v.op, "claim": v.claim}
    pid = hashlib.sha1(json.dumps(apply, sort_keys=True).encode()).hexdigest()[:10]
    return {"id": f"proposal:{pid}", "kind": "proposal", "title": f"Make this change? {v.claim}", "apply": apply}


def to_card(v: Verdict) -> Verdict:
    """The verdict as a card (never applied): the ledger's card for a ledger write, else a proposal card."""
    if v.action not in ("ledger", "edit"):
        return v
    c = (L.card(v.kind, v.key, v.choice) if v.action == "ledger" else None) or proposal_card(v)
    return replace(v, action="card", card=c)


def _ask(kind: str, reason: str) -> Verdict:
    return Verdict(kind, "ask", reason=reason)


def _gate(v: Verdict, texts: List[str], sure: bool, ctx: Ctx) -> Verdict:
    if ctx.confirmed:
        return v
    for t in texts:
        bad = bad_slots(t, ctx.sheet)
        if bad:
            return Verdict(v.kind, "reject", key=v.key,
                           reason=f'"{t}" uses {", ".join(bad)}, which this template cannot fill.')
    new = [t for t in texts if t and not in_instruction(t, ctx.instruction) and not in_sheet(t, ctx.sheet)]
    if not new and sure:
        return v
    return replace(to_card(v), invented=bool(new) and sure)


def _para(sheet: str, name: str) -> Optional[str]:
    return next((n for n, _ in sh.paragraphs(sheet) if sh.norm(n) == sh.norm(name)), None)


# ── one validator per kind ──────────────────────────────────────────────────────────────────────────────────────
def _value(c: ValueChange, ctx: Ctx) -> Verdict:
    known = {sh.norm(n): n for n, _ in L.values(ctx.sheet, ctx.ledger)}
    name = known.get(sh.norm(c.name))
    texts: List[str] = []
    if name is None:
        if c.to == "not_needed":
            return _ask("value", f'"{c.name}" is not one of the values reports must state.')
        name = " ".join(c.name.split())
        texts = [name]
    key, choice = L.check("value", name, {"need": c.to})
    return _gate(Verdict("value", "ledger", key=key, choice=choice, claim=claim_for("value", key, choice)),
                 texts, c.sure, ctx)


def _concept_now(name: str, ctx: Ctx):
    e = L.entry(ctx.ledger, "concept", name)
    return L.concept_state(e["choice"] if e else L.current(ctx.sheet, "concept", name))


def _concept(c: ConceptChange, ctx: Ctx) -> Verdict:
    if c.concept not in L.CONCEPTS:
        return _ask("concept", "I can change these study-level statements: " + ", ".join(L.CONCEPTS.values())
                    + ". Which did you mean?")
    state0, d0, w0, cond0 = _concept_now(c.concept, ctx)
    d = d0 if c.default is None else c.default.strip()
    w = w0 if c.when_met is None else c.when_met.strip()
    state = c.state or ("used" if (c.default or c.when_met) else state0)
    cond = L.condition_for(c.concept, c.condition) if c.condition else cond0   # carried forward
    conditions = [x for x in L.concept_states(c.concept).values() if x]
    if state == "used" and not cond and len(conditions) > 1:
        return _ask("concept", L.usual_question(c.concept))   # the Rules step's own question
    key, choice = L.check("concept", c.concept, L.concept_choice(state, d, w, cond))
    texts = [t for t, old in ((c.default, d0), (c.when_met, w0)) if t and norm_key(t) != norm_key(old)]
    return _gate(Verdict("concept", "ledger", key=key, choice=choice, claim=claim_for("concept", key, choice)),
                 texts, c.sure, ctx)


def _fixed_as_concept(c: FixedChange, owner: str, line: str, ctx: Ctx) -> ConceptChange:
    """A FIXED edit on a line a concept owns, as the concept change it means (plan decision 6)."""
    _, d0, w0, _ = _concept_now(owner, ctx)
    is_default = norm_key(line) == norm_key(d0)
    field_ = "default" if is_default else "when_met"
    if c.to == "reword":
        return ConceptChange(concept=owner, sure=c.sure, **{field_: c.text})
    if c.to == "dictated":
        return ConceptChange(concept=owner, state="dictated", sure=c.sure)
    if c.to == "remove":
        if w0 if is_default else d0:     # the concept keeps its other wording
            return ConceptChange(concept=owner, sure=c.sure, **{field_: ""})
        return ConceptChange(concept=owner, state="not_used", sure=c.sure)
    return ConceptChange(concept=owner, sure=c.sure)   # "always": the concept keeps its wording as it is


def _fixed(c: FixedChange, ctx: Ctx) -> Verdict:
    lines = [sh.quoted(l.text) for l in sh.walk(ctx.sheet) if l.keyword == "FIXED"]
    match = next((t for t in lines if c.line and norm_key(t) == norm_key(c.line)), None)
    if c.to == "add":
        if match or any(norm_key(t) == norm_key(c.text) for t in lines) or L.concept_owner(
                ctx.sheet, ctx.ledger, c.text):
            return _ask("fixed", f'"{c.text or c.line}" is already printed in every report.')
        para = _para(ctx.sheet, c.paragraph)
        if para is None:
            return _ask("fixed", f'Which part of the report should "{c.text}" go in?')
        key, choice = L.check("fixed", c.text, {"keep": "always"})
        v = Verdict("fixed", "edit", key=key, choice=choice, op={"op": "fixed_add", "paragraph": para, "text": key},
                    claim=f'Every report now prints "{key}" in {para}.')
        return _gate(v, [key], c.sure, ctx)
    if match is None:
        return _ask("fixed", f'I couldn\'t find "{c.line}" among the sentences printed in every report.')
    owner = L.concept_owner(ctx.sheet, ctx.ledger, match)
    if owner:
        return _concept(_fixed_as_concept(c, owner, match, ctx), ctx)
    if c.to == "reword":
        key, _ = L.check("fixed", c.text, {"keep": "always"})
        L.rekey_fixed(ctx.ledger, match, key)          # a clash with a decided line is a reject now, not later
        v = Verdict("fixed", "edit", key=key, op={"op": "fixed_reword", "line": match, "text": key},
                    claim=f'"{match}" now reads "{key}".')
        return _gate(v, [key], c.sure, ctx)
    key, choice = L.check("fixed", match, {"keep": c.to})
    return _gate(Verdict("fixed", "ledger", key=key, choice=choice, claim=claim_for("fixed", key, choice)),
                 [], c.sure, ctx)


def _normal(c: NormalChange, ctx: Ctx) -> Verdict:
    para = _para(ctx.sheet, c.paragraph)
    if para is None:
        return _ask("normal", f"I couldn't find the {c.paragraph} part of the report.")
    if c.to == "add":
        text = " ".join((c.text or c.negative).split())
        if c.structure and not c.negative:
            key = L.normal_key(para, c.structure)
            if (L.current(ctx.sheet, "normal", key) or {}).get("text"):
                return _ask("normal", f"{para} already has a normal line for {c.structure}.")
            op = {"op": "normal_add", "paragraph": para, "structure": " ".join(c.structure.split()), "text": text}
        else:
            key = L.negative_key(para, text)
            op = {"op": "negative_add", "paragraph": para, "text": text}
        key, choice = L.check("normal", key, {"text": text})
        v = Verdict("normal", "edit", key=key, choice=choice, op=op, claim=f'{para}: reports now state "{text}".')
        return _gate(v, [text], c.sure, ctx)
    if c.negative:
        key = L.negative_key(para, c.negative)
    elif c.structure:
        key = L.normal_key(para, c.structure)
    else:
        return _ask("normal", f"Which normal line in {para} did you mean?")
    if not (L.current(ctx.sheet, "normal", key) or {}).get("text"):
        return _ask("normal", f"{para} has no normal line for {c.negative or c.structure}.")
    text = "" if c.to == "removed" else " ".join(c.text.split())
    key, choice = L.check("normal", key, {"text": text})
    return _gate(Verdict("normal", "ledger", key=key, choice=choice, claim=claim_for("normal", key, choice)),
                 [text] if text else [], c.sure, ctx)


_LAYOUT_CLAIM = {
    "rename_paragraph": "The {target} paragraph is now called {name}.",
    "move_paragraph": "The {target} paragraph now comes {where}.",
    "remove_paragraph": "The {target} paragraph is removed.",
    "add_paragraph": "A new {name} paragraph is added.",
    "rename_section": 'The {target} section heading now reads "{name}".',
    "move_section": "The {target} section now comes {where}.",
    "remove_section": "The {target} section is removed.",
    "add_section": "A new {name} section is added.",
}


def layout_op(c: LayoutChange) -> dict:
    o = c.op
    if o == "rename_paragraph":
        return {"op": o, "paragraph": c.target, "to": c.name}
    if o == "move_paragraph":
        return {"op": o, "paragraph": c.target, "before": c.before, "after": c.after}
    if o == "remove_paragraph":
        return {"op": o, "paragraph": c.target}
    if o == "add_paragraph":
        return {"op": o, "name": c.name, "section": c.section, "covers": list(c.covers), "after": c.after}
    if o == "rename_section":
        return {"op": o, "section": c.target, "header": c.name}
    if o == "move_section":
        return {"op": o, "section": c.target, "before": c.before, "after": c.after}
    if o == "remove_section":
        return {"op": o, "section": c.target}
    return {"op": "add_section", "name": c.name, "header": c.name, "role": c.role, "after": c.after,
            "covers": list(c.covers)}


def _layout(c: LayoutChange, ctx: Ctx) -> Verdict:
    op = layout_op(c)
    try:
        E.apply_op(ctx.sheet, op)            # dry run: the target exists and the result is lint-clean
    except E.EditError as e:
        return _ask("layout", f"I couldn't change the layout that way: {e}.")
    where = f"before {c.before}" if c.before else f"after {c.after}"
    claim = _LAYOUT_CLAIM[c.op].format(target=c.target, name=c.name, where=where)
    texts = [c.name] if c.op in ("rename_paragraph", "add_paragraph", "rename_section", "add_section") else []
    if c.op in ("add_paragraph", "add_section"):
        texts += list(c.covers)
    return _gate(Verdict("layout", "edit", op=op, claim=claim), texts, c.sure, ctx)


_VALIDATORS = {"value": _value, "concept": _concept, "fixed": _fixed, "normal": _normal, "layout": _layout}


def validate(kind: str, change: BaseModel, ctx: Ctx) -> Verdict:
    try:
        v = _VALIDATORS[kind](change, ctx)
    except L.Rejected as e:   # internal text goes to the evidence only (plan decision 15)
        v = Verdict(kind, "reject", reason=REJECT.format(label=KIND_LABEL[kind]), detail=str(e)[:300])
    v.change = {"kind": kind, **change.model_dump()}
    return v


def parse_change(kind: str, data: dict) -> BaseModel:
    """A stored or re-routed change dict back into its model (kind key dropped)."""
    model = {"value": ValueChange, "concept": ConceptChange, "fixed": FixedChange, "normal": NormalChange,
             "layout": LayoutChange}[kind]
    return model(**{k: v for k, v in (data or {}).items() if k != "kind"})
