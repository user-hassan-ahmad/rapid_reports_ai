"""Preview for a library pack: the draft card (library spec §4, §7.4–§7.7, §12). The model only proposes inputs,
each with the shortest verbatim span that settles it, and only from that input's scope: a lesion input from the card's
own finding unit, a patient input from the clinical history or the whole dictation; with no finding unit, lesion
inputs are asked. Each proposal ends in one of three states (spec §7.5):
- read: code read it with certainty. A number read by code from the whole measurement its quote sits in (the model's
  number must agree), alone in a lesion's finding; or an enum option in its quote's own words with no negation or
  hedge before it. The scope's batched Jev claim must confirm it, a lesion value needs a finding that describes one
  lesion (ONE_LESION), and an attenuation must be stated as unenhanced. Booleans and states are never read;
- pre-filled: any other proposal with a verbatim in-scope quote, shown with its quote and the reason each check
  failed (`WHY_*`);
- asked: nothing proposed, a quote not verbatim in scope, or a number code cannot read (a range, a bound, a fraction,
  an unknown unit, out of range).
The radiologist's answers win; the engine evaluates. Every word of the outcome comes from the entry. The preview
shows the draft outcome "on these values", never an Apply-able proposal; Apply writes only what `calculate` returns
over the values the card shows."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ....enhancement_utils import _run_agent_with_model
from ....report_reconcile import QWEN
from .. import jev as J
from .. import preview as P
from .. import registry as R
from ..types import (Assumption, Branch, Calculation, DecidingAnswer, DecidingInput, DraftValue, Entry as CardEntry,
                     ExclusionReason, GuidelineContent, Input, OutcomeBrief, Preview, Proposal, Publication, Settled,
                     Source)
from . import engine
from . import quantity as Q
from .describe import citation
from .schema import DOES_NOT_APPLY, BandStep, Entry, InputDef, InputValue, RulesStep, conds, preset_value

logger = logging.getLogger(__name__)

PACK_BRANCH = "Pack"
EXAM_CARD = "exam"        # an exam card's finding_id (matcher): only such a card gets its pack's exam_presets
REFERENCE_BRANCH = "Reference"
TIMEOUT_S = 10.0
ONE_LESION_MIN = 0.8      # Jev ONE_LESION: below it, every lesion input on the card is asked
# one lesion of any kind, never the pack's own noun: a granuloma, scar or cyst beside the nodule is a second lesion
ONE_LESION = "The FINDING describes only one lesion of any kind (nodule, granuloma, mass, cyst, scar or other)"
_STATE_LABEL = {"absent": "Absent", "not_assessable": "Not assessable"}
_LEAD = {"lesion": "The FINDING states", "patient": "The CLINICAL HISTORY or DICTATION state"}
CHOICE_MIN = 0.8          # the scope's batched Jev claim for an enum or a boolean: below it, WHY_UNCONFIRMED
NOT_STATED = "Not stated"   # always offered (spec §7.6): clears a value to unknown
# why a drafted value is pre-filled rather than read (spec §7.5); shown with the value
WHY_KIND = "yes/no and absent values are never read"
WHY_NOT_OPTION_WORD = "the quote does not use the option's own words"
WHY_MODIFIED = "a negation or hedge before the quote"
WHY_OTHER_NUMBER = "another number in this finding"
WHY_UNCONFIRMED = "the finding does not clearly state it"
WHY_PHASE = "attenuation not stated as unenhanced"
WHY_SEVERAL = "the finding may describe more than one lesion"
WHY_NO_CHECK = "the check did not run"
WHY_EXAM = "set by the exam"   # an exam preset: the one pre-fill with no quote (spec §5.1, §7.10)
WHY_ASSUMED = "assumed: not stated, so taken as within the guideline's scope"   # an assumed eligibility input
WHY_ASSUMED_ABSENT = "assumed absent: a visible sign the report does not mention"   # silence policy
MAX_DECIDING = 3
DECIDING_CANDIDATES = 3   # the first unknown inputs, in `needed` order, tried as the deciding question
EVAL_CAP = 32             # engine evaluations one preview or Calculate may spend on most_likely, deciding and the like


def _ev_key(given: dict[str, InputValue], assume: bool) -> tuple:
    return (assume, tuple(sorted((k, v.state, repr(v.value), v.band) for k, v in given.items())))


class _Evals:
    """Engine evaluations within one preview or Calculate: memoised by their values and capped at EVAL_CAP (review
    I-3), so the extras (show all, the deciding question, the exclusion reason) never cost a tap more than a few runs.
    Over the cap: None, and the caller leaves that extra out."""

    def __init__(self, e: Entry, cap: int = EVAL_CAP):
        self.e, self.memo, self.left = e, {}, cap

    def __call__(self, given: dict[str, InputValue], assume: bool) -> "engine.Trace | None":
        key = _ev_key(given, assume)
        if key in self.memo:
            return self.memo[key]
        if self.left <= 0:
            return None
        self.left -= 1
        self.memo[key] = engine.evaluate(self.e, given, assume_eligible=assume)
        return self.memo[key]
WHY_WOULD_EXCLUDE = "this pre-filled value would make the guideline not apply: confirm it"   # a scope doubt, any role
SETTLE_SYS = """You settle the inputs of one published radiology classification system for ONE finding. INPUTS lists each open input's id, scope, type and allowed values: use nothing else.
An input's scope decides where it may be settled from:
- [lesion]: the FINDING only, never another lesion in the dictation, even one of the same kind;
- [patient]: the CLINICAL HISTORY or the DICTATION (the patient, the examination or the study as a whole).
For each input its scope states, return one item:
- input: the input's id;
- state: "present" when the value is given; "absent" when the feature is said not to be there and the input lists absent; "not_assessable" when it is said that it cannot be assessed and the input lists not_assessable;
- value: when present, for an enum exactly one of its options, for a boolean true or false, for a number the number as dictated; otherwise null;
- quote: the shortest span, copied verbatim from the FINDING ([lesion]) or from the CLINICAL HISTORY or DICTATION ([patient]), that settles it; a number's quote is the whole measurement as dictated, with its unit.
Leave out every input that is not stated: never settle a value from what is usual or likely, and never invent an input, option or state.
A patient fact (a known cancer, a condition, a treatment) is present only when it is stated as established. A suspected, possible or differential diagnosis, about this lesion or any other, never settles it as present: leave it out."""


class RawItem(BaseModel):
    input: str
    state: str = "present"
    value: str | float | bool | None = None
    quote: str = ""


class RawSettle(BaseModel):
    settled: list[RawItem] = Field(default_factory=list)

    @field_validator("settled", mode="before")
    @classmethod
    def _json_text(cls, v):
        """Qwen sometimes returns the list as JSON text when it is long (BTS, 14 inputs): parse it, not retry."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v


def _bands_for(e: Entry, i: InputDef) -> list:
    """The band labels a number may be answered with: none when the number also feeds a non-band step (a formula),
    which a band answer cannot feed (it would dead-end the card)."""
    users = [s for s in e.logic if i.id in s.refs()]
    if any(not isinstance(s, BandStep) for s in users):
        return []
    return next((s.bands for s in users if isinstance(s, BandStep) and s.ref == i.id), [])


def display_options(e: Entry, i: InputDef) -> list[str]:
    base = i.options if i.type == "enum" else ["Yes", "No"] if i.type == "boolean" else [b.label for b in _bands_for(e, i)]
    return [*base, *(_STATE_LABEL[s] for s in i.states)]


def _show(e: Entry, i: InputDef, v: InputValue) -> str:
    if v.state != "present":
        return _STATE_LABEL.get(v.state, v.state)
    if i.type == "boolean":
        return "Yes" if v.value else "No"
    if i.type == "number":
        if v.band is not None:
            return next((b.label for b in _bands_for(e, i) if b.id == v.band), v.band)
        unit = "" if i.unit == "count" else i.unit
        return f"{float(v.value):g} {unit}".strip()
    return str(v.value)


def _answer(e: Entry, i: InputDef, s: str) -> InputValue | None:
    """A radiologist's choice, as display_options offers it (or a typed number); NOT_STATED is unknown."""
    s = s.strip()
    if s == NOT_STATED:
        return InputValue(state="unknown")
    for st, label in _STATE_LABEL.items():
        if s == label:
            return InputValue(state=st) if st in i.states else None
    if i.type == "enum":
        return InputValue(value=s) if s in i.options else None
    if i.type == "boolean":
        return {"Yes": InputValue(value=True), "No": InputValue(value=False)}.get(s)
    band = next((b for b in _bands_for(e, i) if b.label == s), None)
    if band is not None:
        return InputValue(band=band.id)
    try:
        x = float(s)
    except ValueError:
        xs = Q.readings(s, i.unit)                    # "72 years", "1.2 cm": read as a quote would be
        x = xs[0] if len(xs) == 1 else None
    return InputValue(value=x) if x is not None and i.in_range(x) else None     # out of range: still asked


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _value(i: InputDef, item: RawItem, texts: list[str] | None = None) -> InputValue | None:
    """The model's value if it is a real one: an allowed state, an option, a boolean, or a number read by code from
    the whole measurement its quote sits in within `texts` (the quote alone when no texts are given). The model's own
    number must agree with that one reading, or choose between several. Another number in a lesion's finding no
    longer drops it: it is a reason the value is pre-filled (_read_reasons)."""
    if item.state in _STATE_LABEL:
        return InputValue(state=item.state) if item.state in i.states else None
    if item.state != "present":
        return None
    if i.type == "number":
        x = (Q.pick(Q.readings(item.quote, i.unit, i.dims), _num(item.value), i.unit) if texts is None
             else Q.settle(item.quote, texts, i.unit, i.dims, _num(item.value)))
        return InputValue(value=x) if x is not None and i.in_range(x) else None   # out of range: asked
    if item.value is None:
        return None
    if i.type == "enum":
        m = {R.norm(o): o for o in i.options}
        hit = m.get(R.norm(str(item.value)))
        return InputValue(value=hit) if hit is not None else None
    return InputValue(value=item.value) if isinstance(item.value, bool) else None


def _inputs_text(e: Entry, ids: list[str]) -> str:
    lines = []
    for i in (e.input(k) for k in ids):
        allowed = (" | ".join(i.options) if i.type == "enum" else "true | false" if i.type == "boolean"
                   else f"number in {i.unit or 'the unit dictated'}")
        states = f"; states allowed: {', '.join(i.states)}" if i.states else ""
        hint = f" (dictated as: {i.how_stated})" if i.how_stated else ""
        lines.append(f"- {i.id} [{i.scope}]: {i.label}{hint} [{allowed}{states}]")
    return "\n".join(lines)


def _prompt(e: Entry, ids: list[str], finding: str, findings: str, history: str) -> str:
    """Only the open inputs; the history and the whole dictation only when a patient input is open."""
    s = f"SYSTEM: {e.display}\nINPUTS:\n{_inputs_text(e, ids)}"
    if any(e.input(k).scope == "patient" for k in ids):
        s += f"\n\nCLINICAL HISTORY: {history or 'none given'}\n\nDICTATION:\n{findings}"
    return s + f"\n\nFINDING:\n{finding}" if finding else s


def _in_scope(i: InputDef, quote: str, finding: str, findings: str, history: str) -> bool:
    """A lesion input's quote lies verbatim in the card's own finding; a patient input's in the history or dictation."""
    return P._verbatim(quote, finding, "") if i.scope == "lesion" else P._verbatim(quote, findings, history)


# a negation, a hedge, a hyphen-joined modifier ("part-", "non-", "semi-") or a "?" right before a quoted word changes
# what it says: an enum or boolean quoted without it gives no reading (one word may sit between: "not clearly")
_MODIFIER = re.compile(r"(?:\b(?:no|not|non|nor|neither|without|absent|free\s+of|possibly|probably|likely|questionably"
                       r"|query|equivocal|equivocally|ruled\s+out|cannot\s+exclude)\s+(?:[a-z]+\s+)?"
                       r"|[a-z0-9]-\s*|\?\s*)$", re.I)


def _modified(quote: str, texts: list[str]) -> bool:
    """Any occurrence of the quote in its scope's text has a modifier right before it (_MODIFIER)."""
    words = re.findall(r"[^\W_]+", quote or "")
    if not words:
        return False
    pat = re.compile(r"(?<![^\W_])" + r"[\W_]*".join(re.escape(w) for w in words) + r"(?![^\W_])", re.I)
    return any(_MODIFIER.search(t[:m.start()]) for t in texts if t for m in pat.finditer(t))


# a suspicion is never a known cancer (Hassan 2026-10-13: "suspicious for RCC" about another lesion pre-filled "known
# primary cancer: yes"): the backstop to the settle prompt's rule, for the shared fact alone
_HEDGE = re.compile(r"\b(?:suspicious|suspected|suspect|suspicion|possible|possibly|probable|probably|likely|query"
                    r"|queried|equivocal|indeterminate|concerning|worrying|differential|cannot\s+be\s+excluded"
                    r"|not\s+excluded)\b|\?", re.I)


_SENTENCE_END = re.compile(r"(?<!\d)\.(?!\d)|[;\n]")      # never inside a decimal ("3.5 cm")


def _hedged_cancer(i: InputDef, v: InputValue, quote: str, texts: list[str] | None = None) -> bool:
    """A "known primary cancer: yes" hedged by its quote or by the words before the quote in its sentence ("suspicious
    for RCC" quoted as "RCC", "?primary"): dropped, so the input is asked. A hedge after the quote is about something
    else ("Breast ca ?liver mets": the cancer is stated, the metastases are not), so it is not read (review I-d)."""
    if i.fact != "known_primary_cancer" or v.value is not True:
        return False
    if _HEDGE.search(quote):
        return True
    for t in texts or []:
        low, q = (t or "").lower(), quote.lower()          # quotes pass a case-insensitive verbatim check (M8)
        n = low.find(q)
        while n >= 0:
            start = max((m.end() for m in _SENTENCE_END.finditer(t, 0, n)), default=0)
            if _HEDGE.search(t[start:n]):
                return True
            n = low.find(q, n + 1)
    return False


async def _call(system: str, prompt: str) -> RawSettle:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawSettle, system_prompt=system, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


def _cites(xs: list[dict]) -> list[dict]:
    """Non-empty citations, first occurrence kept."""
    out = []
    for c in xs:
        if c and c not in out:
            out.append(c)
    return out


def _fired(e: Entry, t: engine.Trace, sources: list[dict]) -> list[dict]:
    """The proposal's citations: the steps the result was reached through (for a rules step, the case that fired and
    only the refs it tests), from the result back, then the outcome's own locator. Each names its step."""
    st = {s.id: s for s in t.steps}
    out, todo, seen = [], [e.result], set()
    while todo:
        k = todo.pop(0)
        if k in seen or k not in st or st[k].state != "present":
            continue
        seen.add(k)
        s, step = st[k], e.step(k)
        refs = [c.ref for c in conds(step.cases[int(s.fired)].when)] \
            if isinstance(step, RulesStep) and s.fired.isdigit() else s.uses
        out.append(s)
        todo += refs
    o = e.outcome(t.outcome)
    return _cites([{**c, "step": s.id} for s in out if (c := citation(s.locator, sources))]
                  + ([{**c, "step": "outcome"}] if (c := citation(o.locator, sources)) else []))


def _reads(e: Entry, input_id: str, sources: list[dict]) -> list[dict]:
    """Citations of the steps that read this input: a rules step's cases that test it, any other step's locator."""
    locs = []
    for s in e.logic:
        if isinstance(s, RulesStep):
            locs += [c.locator for c in s.cases if any(x.ref == input_id for x in conds(c.when))]
        elif input_id in s.refs():
            locs.append(s.locator)
    return _cites([citation(x, sources) for x in locs])


def _asks(e: Entry, t: engine.Trace, sources: list[dict], needed: list[str]) -> list[dict]:
    """One ask per missing input, in `needed` order: what it is, how it is answered, which outcomes it decides
    between, and where."""
    out = []
    for k in needed:
        i = e.input(k)
        decides = [{"outcome": o, "classification": engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)),
                    "citation": citation(e.outcome(o).locator, sources)} for o in t.decides.get(k, t.possible)]
        out.append({"input": k, "label": i.label, "role": i.role, "scope": i.scope, "fact": i.fact or "",
                    "definition": {"text": i.how_stated, "citation": citation(i.locator, sources)},
                    "options": display_options(e, i), "decides_between": decides, "citations": _reads(e, k, sources)})
    return out


def _given(e: Entry, answered: dict[str, str], patient: dict[str, str] | None = None) -> dict[str, InputValue]:
    """The radiologist's answers on this card, then the case's shared patient answers for inputs carrying that fact
    (one answer fills every card; a card's own answer wins). A value the entry cannot take is ignored: still asked."""
    out: dict[str, InputValue] = {}
    for k, s in answered.items():
        i = e.input(k)
        v = _answer(e, i, s) if i is not None else None
        if v is not None:
            out[k] = v
    for i in e.inputs:
        s = (patient or {}).get(i.fact) if i.fact else None
        if s is not None and i.id not in out:
            v = _answer(e, i, s)
            if v is not None:
                out[i.id] = v
    return out


async def _settle(e: Entry, given: dict[str, InputValue], finding: str, findings: str,
                  history: str) -> tuple[dict[str, tuple[InputValue, Settled]], bool]:
    """(the model's real values for the open inputs whose quotes lie in their scope, whether the call failed). With
    no finding unit, lesion inputs are not offered: they are asked."""
    ids = [i.id for i in e.inputs if i.id not in given and (finding or i.scope != "lesion")]
    if not ids:
        return {}, False
    try:
        raw = await _call(SETTLE_SYS, _prompt(e, ids, finding, findings, history))
    except Exception as ex:
        logger.warning("[library.preview] settle %s: %s", type(ex).__name__, str(ex)[:200])
        return {}, True
    out: dict[str, tuple[InputValue, Settled]] = {}
    for item in raw.settled:
        i = e.input(item.input)
        q = item.quote.strip()
        if i is None or i.id not in ids or not q or not _in_scope(i, q, finding, findings, history):
            continue
        v = _value(i, item, _texts(i, finding, findings, history))
        if v is not None and _hedged_cancer(i, v, q, _texts(i, finding, findings, history)):
            continue                 # a suspicion, about this lesion or another, is never a known cancer: asked
        if v is not None:
            out[i.id] = (v, Settled(input=i.id, value=_show(e, i, v), quote=q))
    return out, False


def _texts(i: InputDef, finding: str, findings: str, history: str) -> list[str]:
    """The texts an input's quote may come from: its finding (lesion), else the dictation and the history."""
    return [finding] if i.scope == "lesion" else [findings, history]


def _words(s: str) -> list[str]:
    return R.norm(s.replace("_", " ")).split()


def _has_option_words(option: str, quote: str) -> bool:
    """The option's own words appear in the quote, in order, as whole tokens."""
    w, q = _words(option), _words(quote)
    return bool(w) and any(q[n:n + len(w)] == w for n in range(len(q) - len(w) + 1))


def _nouns(e: Entry) -> list[str]:
    """The pack's lesion nouns, from the finding types it applies to."""
    return [t for t in e.applies_to.finding_type if t.strip()] or ["lesion"]


def _read_reasons(e: Entry, i: InputDef, v: InputValue, quote: str, texts: list[str]) -> list[str]:
    """Why code cannot read this value with certainty (spec §7.5); empty when it can, before the Jev checks."""
    present = v.state == "present"
    out = [] if present and i.type != "boolean" else [WHY_KIND]
    if present and i.type == "enum" and not _has_option_words(str(v.value), quote):
        out.append(WHY_NOT_OPTION_WORD)
    if i.type != "number" and _modified(quote, texts):
        out.append(WHY_MODIFIED)
    if (present and i.type == "number" and i.scope == "lesion"
            and not Q.alone(texts[0], quote, float(v.value), i.unit, i.dims)):
        out.append(WHY_OTHER_NUMBER)
    if i.scope == "lesion" and Q.many(texts[0], _nouns(e)):    # a multiplicity word: never read on Jev alone
        out.append(WHY_SEVERAL)
    return out


async def _jev(claims: list[str], state: str) -> list[float]:
    qs = {f"v{n}": {"type": "noul", "instructions": c} for n, c in enumerate(claims)}
    r = await P.jev_post({"model": P.JEV_MODEL, "state": state, "questions": qs},
                         os.environ.get("OPENROUTER_API_KEY", ""), P.JEV_TIMEOUT_S)
    r.raise_for_status()
    s = J.scores(r.json(), qs)        # malformed raises: an outage, never a low score
    return [s[f"v{n}"] for n in range(len(claims))]


UNENHANCED_MIN = 0.8      # Jev _phase_claim below it: the attenuation is asked (review M2)


def _phase_claim(shown: str) -> str:
    """An attenuation settles only when the finding states it was measured unenhanced: a post-contrast value, or one
    with no phase in a two-phase study, may not be the value the input means."""
    return f"The FINDING states that {shown} was measured on an unenhanced (non-contrast) series"


async def _confirm(e: Entry, pending: dict[str, tuple[InputValue, str]], finding: str, findings: str,
                   history: str) -> tuple[dict[str, list[str]], bool]:
    """(input -> the reasons it is not read, empty when confirmed; whether a Jev call failed). Both scopes together:
    - per scope, one batched call: "The FINDING states <label>: <value>" with the finding unit alone as state
      (lesion), or the same of the history and the dictation (patient). A number needs SETTLED_MIN, an enum or a
      boolean CHOICE_MIN; below it, WHY_UNCONFIRMED. An attenuation adds the phase claim (WHY_PHASE). The lesion batch
      also carries ONE_LESION whenever any lesion input is pending: below ONE_LESION_MIN every lesion input gets
      WHY_SEVERAL.
    A failed call gives each of its inputs WHY_NO_CHECK (the lesion batch: every lesion input). Nothing is dropped:
    every reason only makes the value pre-filled rather than read (spec §7.5)."""
    states = {"lesion": f"FINDING:\n{finding}",
              "patient": f"CLINICAL HISTORY:\n{history or 'none given'}\n\nDICTATION:\n{findings}"}
    why: dict[str, list[str]] = {k: [] for k in pending}

    def add(k: str, reason: str) -> None:
        if reason not in why[k]:
            why[k].append(reason)

    async def batch(scope: str) -> bool:
        """Whether the call failed."""
        ids = [k for k in pending if e.input(k).scope == scope]
        if not ids:
            return False
        one_lesion = scope == "lesion"
        claims = [f"{_LEAD[scope]} {e.input(k).label}: {_show(e, e.input(k), pending[k][0]).replace('_', ' ')}"
                  for k in ids]
        # an attenuation not stated as unenhanced may be an enhanced value, not the one the input means
        hu = [k for k in ids if scope == "lesion" and e.input(k).type == "number"
              and Q.FAMILY.get(Q.canon(e.input(k).unit)) == "attenuation"]
        claims += [_phase_claim(_show(e, e.input(k), pending[k][0])) for k in hu]
        if one_lesion:                 # one lesion or several is a question of meaning: Jev, in the same batch
            claims.append(ONE_LESION)
        try:
            got = await _jev(claims, states[scope])
        except Exception as ex:
            logger.info("[library.preview] %s value check failed (%s)", scope, type(ex).__name__)
            for k in ids:
                add(k, WHY_NO_CHECK)
            return True
        for k, sc in zip(ids, got):
            if sc < (P.SETTLED_MIN if e.input(k).type == "number" else CHOICE_MIN):
                add(k, WHY_UNCONFIRMED)
        for k, sc in zip(hu, got[len(ids):len(ids) + len(hu)]):
            if sc < UNENHANCED_MIN:
                add(k, WHY_PHASE)
        if one_lesion and got[-1] < ONE_LESION_MIN:
            logger.info("[library.preview] %s: finding may not be one lesion (%.2f); lesion values pre-filled",
                        e.key, got[-1])
            for k in ids:
                add(k, WHY_SEVERAL)
        return False

    fails = await asyncio.gather(batch("lesion"), batch("patient"))
    return why, any(fails)


def _outcome_text(e: Entry, t: engine.Trace, sources: list[dict], outcome_id: str | None = None) -> Proposal | None:
    """The reached outcome as the entry words it, or None when its text still cites an unknown input. `outcome_id`:
    an input's exclusion_outcome worded in place of does_not_apply (spec §7.12 item 1), cited by its own locator and
    the input's (the guideline text behind that exclusion), not by the generic scope clause."""
    o = e.outcome(outcome_id or t.outcome)
    cls, rec = engine.render(e, t, o.classification), engine.render(e, t, o.recommendation)
    caveats = [engine.render(e, t, c) for c in o.caveats]
    if any(engine.PH.search(x) for x in (cls, rec, *caveats)):
        logger.info("[library.preview] %s: outcome %s cites an input still unknown; no proposal", e.key, o.id)
        return None
    if outcome_id:
        i = next((x for x in e.inputs if x.exclusion_outcome == outcome_id), None)
        cites = _cites([{**c, "step": "outcome"} if (c := citation(o.locator, sources)) else {},
                        {**c, "step": i.id} if i is not None and (c := citation(i.locator, sources)) else {}])
    else:
        cites = _fired(e, t, sources)
    return Proposal(classification=f"{e.display} · {cls}", line=f"{e.display}: {cls}.", recommendation=rec,
                    caveats=caveats, citations=cites, normal=o.normal, headline=o.headline or "",
                    action=o.action or "", category=o.category or "")


@dataclass
class Drafted:
    """One value the dictation drafts for a card (spec §7.5): its quote is verbatim in scope; `read` when code read it
    with certainty and every check passed, else `prefilled` with the reason each check failed."""
    value: InputValue
    quote: str
    tier: Literal["read", "prefilled"]
    why: list[str] = field(default_factory=list)


def _draft_value(e: Entry, i: InputDef, t: engine.Trace, state: str, g: InputValue | None,
                 d: Drafted | None, by: str = "") -> DraftValue:
    """One input as the card shows it. A drafted value carries its quote (and, pre-filled, its reasons) only while it
    is shown as drafted; an answer or an edit has no quote."""
    shown = state not in ("asked", "not_applicable") and g is not None and g.state != "unknown"
    drafted = state in ("read", "prefilled")
    return DraftValue(input=i.id, label=i.label, role=i.role, scope=i.scope, fact=i.fact or "", state=state,
                      value=_show(e, i, g) if shown else "", quote=d.quote if drafted and d is not None else "",
                      why=([WHY_ASSUMED] if state == "assumed" else
                           (list(d.why) if d is not None else [WHY_EXAM] if by else []) if state == "prefilled" else []),
                      by=by if drafted else "", needed=i.id in t.needed, waiting=i.id in t.waiting,
                      options=[*display_options(e, i), NOT_STATED])


def _known(given: dict[str, InputValue]) -> dict[str, InputValue]:
    """The values the engine sees: NOT_STATED (unknown) is left out, as an input never given."""
    return {k: v for k, v in given.items() if v.state != "unknown"}


def _possible(e: Entry, t: engine.Trace) -> list[str]:
    return [engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)) for o in t.possible]


def _build(e: Entry, t: engine.Trace, given: dict[str, InputValue], quotes: dict[str, str], sources: list[dict],
           degraded: bool, preset: frozenset[str] = frozenset(), draft: list[DraftValue] | None = None,
           doubt: list[str] | None = None, signs: dict[str, InputValue] | None = None,
           possible: list[str] | None = None, likely: tuple | None = None,
           reason: ExclusionReason | None = None, assumed: list[Assumption] | None = None) -> Preview:
    """The card (spec §7.4): eligibility asks first; the state worked out in code; the reached outcome is a draft
    "on these values" (never a proposal, so never Applied); a does_not_apply outcome is shown as an exclusion."""
    elig = [i.id for i in e.inputs if i.role == "eligibility"]
    needed = list(t.needed)                       # engine order (spec §7.4): eligibility, parents, the rest
    settled = [Settled(input=k, value=_show(e, e.input(k), given[k]), quote=quotes.get(k, ""),
                       fact=e.input(k).fact or "", by="exam" if k in preset else "")
               for k in (i.id for i in e.inputs) if k in given and given[k].state != "unknown"]
    text = _outcome_text(e, t, sources) if t.outcome is not None else None
    if t.outcome == DOES_NOT_APPLY:
        state, draft_outcome, exclusion = "does_not_apply", None, _exclusion_text(e, t, sources, reason, text)
        logger.info("[library.preview] %s does not apply (eligibility given: %s)", e.key,
                    ", ".join(k for k in elig if k in given) or "none")
    else:          # check_first stays honest: an assumed or still-unknown eligibility input (the UI's warning)
        state = "check_first" if t.assumed or doubt or set(elig) & set(needed) else "applies"
        draft_outcome, exclusion = text, None
    elig_assumed = [a for a in (assumed or []) if a.kind == "eligibility"]
    most_likely, deciding_input, deciding = likely or (None, None, [])
    if possible is None:
        possible = _possible(e, t)
    return Preview(settled=settled, draft=draft or [], draft_outcome=draft_outcome, missing=needed, proposal=None,
                   assumptions=list(assumed or []), assumed_eligible=bool(elig_assumed), scope_doubt=list(doubt or []),
                   most_likely=most_likely, deciding_input=deciding_input, deciding=deciding,
                   exclusion_reason=reason if t.outcome == DOES_NOT_APPLY else None,
                   exclusion=exclusion, state=state, possible=possible, bounded=t.bounded,
                   asks=_asks(e, t, sources, needed), waiting=list(t.waiting),
                   trace=t.model_dump(mode="json") if t.outcome is not None else None, degraded=degraded)


def failed(e: Entry) -> Preview:
    """A preview that never ran (an error or a timeout): nothing settled; eligibility, if the pack has any, was never
    assessed, so the card is check_first rather than applies."""
    return Preview(degraded=True,
                   state="check_first" if any(i.role == "eligibility" for i in e.inputs) else "applies")


@dataclass
class Settlement:
    """What the dictation drafts for one card, read once per (dictation, finding, history) and never again: the
    preview cache holds it, and each answer re-runs only the engine over it (`finish`), so a drafted value cannot
    change between answers."""
    values: dict[str, Drafted] = field(default_factory=dict)   # input -> its drafted value
    failed: bool = False       # the model or a Jev check failed (a Jev failure pre-fills; a model failure drafts
                               # nothing); cached all the same, and a fresh /open may retry it once
    no_unit: bool = False      # no finding unit: every lesion input is asked (deterministic, so cached)


async def settle_pack(e: Entry, findings: str, history: str, finding: str = "") -> Settlement:
    """Every input the dictation drafts, whatever the radiologist has answered (answers win in `finish`)."""
    finding = finding.strip()
    # no finding unit: lesion inputs are never read from the whole dictation (another lesion's values); they are asked
    no_unit = not finding and any(i.scope == "lesion" for i in e.inputs)
    if no_unit:
        logger.info("[library.preview] %s: no finding unit; lesion inputs asked", e.key)
    model, degraded = await _settle(e, {}, finding, findings, history)
    # every number (read by code from the quote) is put to Jev as stated for its scope: this catches a number of the
    # wrong time point or role ("was 5 mm, now 9 mm"; swapped volumes); every enum or boolean, as stated by its quote
    pending = {k: (v, st.quote) for k, (v, st) in model.items()}
    reasons, jev_failed = await _confirm(e, pending, finding, findings, history) if pending else ({}, False)
    values: dict[str, Drafted] = {}
    for k, (v, q) in pending.items():
        i = e.input(k)
        why = _read_reasons(e, i, v, q, _texts(i, finding, findings, history))
        why += [r for r in reasons.get(k, []) if r not in why]
        values[k] = Drafted(v, q, "prefilled" if why else "read", why)
    return Settlement(values=values, failed=degraded or jev_failed, no_unit=no_unit)


def exam_presets(e: Entry, finding_id: str) -> dict[str, str]:
    """The pack's exam presets when the card is its exam card; a finding card never gets them."""
    return dict(e.exam_presets) if finding_id == EXAM_CARD and "exam" in e.trigger else {}


def preset_values(e: Entry, presets: dict[str, str] | None) -> dict[str, InputValue]:
    """The presets as engine values (the entry's validator already refused any the input cannot take)."""
    out = {}
    for k, x in (presets or {}).items():
        i = e.input(k)
        v = preset_value(i, x) if i is not None else None
        if v is not None:
            out[k] = v
    return out


def finish(e: Entry, s: Settlement, answered: dict[str, str], patient: dict[str, str] | None = None,
           sources: list[dict] | None = None, presets: dict[str, str] | None = None) -> Preview:
    """The card from a settlement and the radiologist's answers, by the engine alone: no model, no Jev. An answer
    (the card's own, then the shared patient one; NOT_STATED included) overrides the drafted value for that input,
    and a drafted (quoted) value overrides an exam preset. A preset is the one pre-fill without a quote: it is shown
    pre-filled, set by the exam (spec §5.1, §7.10), never applied unseen. Presets are applied here, not in the
    settlement, so a cached settlement shared with a finding card never carries them."""
    answers = _given(e, answered, patient)
    given, quotes = dict(answers), {}
    for k, d in s.values.items():
        if k not in given:
            given[k], quotes[k] = d.value, d.quote
    preset = set()
    for k, v in preset_values(e, presets).items():
        if k not in given:
            given[k] = v
            preset.add(k)
    # silence policy: an unstated visible sign is assumed absent (shown "assumed", never read; a stated value wins)
    # an explicit "Not stated" is the radiologist's: the sign is then asked, never re-assumed (review M-2)
    # nobody looked when the settle model failed (nothing drafted), and no lesion value is read without a finding
    # unit: then the signs are asked, never assumed (final review I3)
    unread = s.failed and not s.values
    signs = {i.id: i.absent_value() for i in e.inputs
             if i.visible_sign and i.id not in _known(given) and i.id not in answers
             and not unread and not (s.no_unit and i.scope == "lesion")}
    drafted = {**given, **signs}
    try:      # the draft never leads with eligibility: an unknown one is assumed in scope, visibly (Hassan 2026-10-13)
        t = engine.evaluate(e, _known(drafted), assume_eligible=True)
        t, doubt = _no_prefilled_exclusion(e, t, s, answers, drafted)
        # "show all": every outcome still possible without the sign assumptions
        # the extras weigh the same values the draft was computed on: the scope doubt left out (final review I1)
        base = {k: v for k, v in _known(drafted).items() if k not in doubt}
        ev = _Evals(e)
        ev.memo[_ev_key(base, True)] = t
        rest = {k: v for k, v in _known(given).items() if k not in doubt}
        shown = ev(rest, True) if signs and t.bounded else None    # unbounded: t.possible already is all
        possible = _possible(e, shown or t)
        likely = _likely(e, t, base, sources or [], assume=True, ev=ev)
        reason = _exclusion_reason(e, t, base, ev)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.preview] %s cannot be evaluated: %s", e.key, ex)
        return failed(e)
    draft = []
    for i in e.inputs:
        d, a = s.values.get(i.id), answers.get(i.id)
        is_answered = a is not None and a.state != "unknown"
        g = given.get(i.id)
        if t.inputs[i.id].state == "not_applicable" and i.id not in t.assumed:
            st = "not_applicable"
        elif is_answered:
            st = "answered"
        elif a is None and d is not None:
            st = d.tier
        elif a is None and i.id in preset:
            st = "prefilled"
        elif i.id in signs:
            st, g = "assumed", signs[i.id]
        elif i.id in t.assumed:
            st, g = "assumed", t.assumed[i.id]
        else:
            st = "asked"
        dv = _draft_value(e, i, t, st, g, d if a is None else None, "exam" if i.id in preset else "")
        if st == "assumed" and i.id in signs:
            dv.why = [WHY_ASSUMED_ABSENT]
        if i.id in doubt:
            dv.why.append(WHY_WOULD_EXCLUDE)
        draft.append(dv)
    assumed = []
    if t.outcome != DOES_NOT_APPLY:
        for dv in draft:
            if dv.state == "assumed" and dv.input not in doubt:
                dv.decisive = _decisive(e, t, base, dv.input, signs.get(dv.input) or t.assumed[dv.input], ev, True)
                assumed.append(Assumption(input=dv.input, label=dv.label, value=dv.value, decisive=dv.decisive,
                                          kind="sign" if dv.input in signs else "eligibility"))
    return _build(e, t, given, quotes, sources or [], s.failed or s.no_unit, frozenset(preset), draft, doubt, signs,
                  possible, likely, reason, assumed)


def _decisive(e: Entry, t: engine.Trace, base: dict[str, InputValue], k: str, cur: InputValue, ev: "_Evals",
              assume: bool) -> bool | None:
    """Whether flipping this one assumed value to any other answer changes the outcome (so it must be confirmed at
    Apply; a non-decisive assumption needs no confirmation). None when not weighed: an unbounded result, or over the
    evaluation cap."""
    if not t.bounded:
        return None
    i = e.input(k)
    for label in display_options(e, i):
        v = _answer(e, i, label)
        if v is None or _same_shown(e, i, v, cur):
            continue
        r = ev({**base, k: v}, assume)
        if r is None:
            return None
        if r.outcome != t.outcome:
            return True
    return False


def _exclusion_reason(e: Entry, t: engine.Trace, known: dict[str, InputValue],
                      ev: "_Evals | None" = None) -> ExclusionReason | None:
    """does_not_apply: the one value whose removal alone lifts the exclusion (the engine's own result over the other
    values no longer does_not_apply), shown so the card can say why instead of listing every criterion. None when no
    single value is behind it (several exclude, or none alone)."""
    if t.outcome != DOES_NOT_APPLY:
        return None
    ev = ev or _Evals(e)
    lifts = []
    for k, v in known.items():
        if v.state == "unknown" or e.input(k) is None:
            continue
        r = ev({x: y for x, y in known.items() if x != k}, False)
        if r is None:                                   # over the cap: not attributable
            return None
        if r.outcome != DOES_NOT_APPLY:
            lifts.append(k)
    if len(lifts) != 1:
        return None
    i = e.input(lifts[0])
    return ExclusionReason(input=i.id, label=i.label, value=_show(e, i, known[i.id]), outcome=i.exclusion_outcome)


def _exclusion_text(e: Entry, t: engine.Trace, sources: list[dict], reason: ExclusionReason | None,
                    generic: Proposal | None) -> Proposal | None:
    """does_not_apply as the card words it: the exclusion reason's own outcome when its input names one (spec §7.12
    item 1: "Outside the Fleischner table: interval growth"), else the generic does_not_apply text."""
    if reason is None or reason.outcome is None:
        return generic
    return _outcome_text(e, t, sources, reason.outcome) or generic


def _brief(e: Entry, t: engine.Trace, oid: str) -> OutcomeBrief:
    o = e.outcome(oid)
    head = o.headline or engine.PH.sub("…", engine.render(e, t, o.classification))
    return OutcomeBrief(headline=head, action=o.action or "", category=o.category or "")


def _likely(e: Entry, t: engine.Trace, base: dict[str, InputValue], sources: list[dict], assume: bool,
            ev: "_Evals | None" = None):
    """(most_likely, deciding_input, deciding). The reached outcome (not an exclusion), in short. While several
    outcomes remain: of the first DECIDING_CANDIDATES unknown inputs the radiologist can pick an answer for, the one
    whose answers settle the most different outcomes (then the widest `decides`, then `needed` order), with each
    answer's outcome under the same assumptions, answers that lead to the same outcome grouped, at most MAX_DECIDING.
    Engine only: no model, no Jev."""
    if t.outcome is not None:
        return (_brief(e, t, t.outcome) if t.outcome != DOES_NOT_APPLY else None), None, []
    if len(t.possible) < 2 or not t.needed or not t.bounded:   # unbounded: too costly to weigh (review I-3)
        return None, None, []
    ev = ev or _Evals(e)
    pickable = [k for k in t.needed if display_options(e, e.input(k))][:DECIDING_CANDIDATES]
    if not pickable:
        return None, None, []

    def answers(k: str) -> dict[str | None, list[str]]:
        i, groups = e.input(k), {}
        for label in display_options(e, i):
            v = _answer(e, i, label)
            if v is not None:
                r = ev({**base, k: v}, assume)
                groups.setdefault(r.outcome if r is not None else None, []).append(label)
        return groups
    scored = []
    for n, k in enumerate(pickable):     # the most outcomes settled by one answer; then the widest decides; then order
        g = answers(k)
        scored.append(((len([o for o in g if o is not None]), len(t.decides.get(k, t.possible)), -n), k, g))
    score, k, groups = max(scored, key=lambda x: x[0])
    if score[0] == 0:                    # no single answer settles an outcome: there is no deciding question yet
        return None, None, []
    i = e.input(k)
    deciding = []
    for oid, labels in list(groups.items())[:MAX_DECIDING]:
        if oid is None:
            deciding.append(DecidingAnswer(answer=" / ".join(labels), headline="Needs more answers"))
        else:
            b = _brief(e, t, oid)
            deciding.append(DecidingAnswer(answer=" / ".join(labels), headline=b.headline, category=b.category))
    return None, DecidingInput(input=k, label=i.label), deciding


def _no_prefilled_exclusion(e: Entry, t: engine.Trace, s: Settlement, answers: dict[str, InputValue],
                            given: dict[str, InputValue]) -> tuple[engine.Trace, list[str]]:
    """Nothing is excluded on a guess (Hassan 2026-10-13): only a read, answered or stated value may give
    does_not_apply. When the draft excludes and pre-filled values are behind it, of any role (an eligibility value, or
    a clinical one such as a pre-filled diameter over 3 cm), the ones whose removal lifts the exclusion are the scope
    doubt: the draft is recomputed over every other value (the remaining pre-filled values stay in it), they are shown
    pre-filled with WHY_WOULD_EXCLUDE, and the card stays check_first. Calculate takes such a value as sent once the
    radiologist confirms it."""
    if t.outcome != DOES_NOT_APPLY:
        return t, []
    pre = [k for k, d in s.values.items() if d.tier == "prefilled" and k not in answers and e.input(k) is not None]
    if not pre:
        return t, []
    known = _known(given)

    def without(ks) -> engine.Trace:
        return engine.evaluate(e, {k: v for k, v in known.items() if k not in ks}, assume_eligible=True)
    if without(pre).outcome == DOES_NOT_APPLY:        # excluded anyway, by a read, answered or stated value
        return t, []
    doubt = [k for k in pre if without([k]).outcome != DOES_NOT_APPLY]          # removing it alone lifts it
    if not doubt:                                      # several together: each that alone excludes, else them all
        rest = {k: v for k, v in known.items() if k not in pre}
        doubt = [k for k in pre
                 if engine.evaluate(e, {**rest, k: known[k]}, assume_eligible=True).outcome == DOES_NOT_APPLY] or pre
    t2 = without(doubt)
    if t2.outcome == DOES_NOT_APPLY:
        doubt, t2 = pre, without(pre)
    logger.info("[library.preview] %s: a pre-filled value would exclude; drafted in scope", e.key)
    return t2, doubt


def _calc_assumed(e: Entry, t: engine.Trace, known: dict[str, InputValue], given: dict[str, InputValue],
                  used: list[DraftValue], ev: "_Evals") -> list[Assumption]:
    """Calculate's assumed values (sent back unchanged from an assumption), each weighed as in the preview, over the
    evaluated values (the scope doubt left out)."""
    out = []
    for v in used:
        if v.state != "assumed":
            continue
        rest = {k: x for k, x in known.items() if k != v.input}
        v.decisive = _decisive(e, t, rest, v.input, given[v.input], ev, False)
        out.append(Assumption(input=v.input, label=v.label, value=v.value, decisive=v.decisive,
                              kind="eligibility" if e.input(v.input).role == "eligibility" else "sign"))
    return out


def _same_shown(e: Entry, i: InputDef, v: InputValue | None, g: InputValue) -> bool:
    """The two values show alike on the card."""
    return v is not None and _show(e, i, v) == _show(e, i, g)


def calculate(e: Entry, s: Settlement, values: dict[str, str], patient: dict[str, str] | None,
              sources: list[dict], bundle: str, presets: dict[str, str] | None = None,
              answered: dict[str, str] | None = None) -> Calculation:
    """Spec §7.7: the engine over exactly the values the card shows; an input not sent is unknown, never taken from
    the settlement, a preset or a shared answer. No model, no Jev. The card's own preview (finish over the same
    settlement, answers and presets) labels each value, so Calculate sees exactly the assumptions and scope doubts the
    card showed (final review C1, I2):
    - a value equal to its draft keeps the draft's state (a preset's: pre-filled, by the exam); one equal to the shared
      patient answer is answered; one the preview showed assumed, sent back unchanged and not answered, stays assumed;
      any other is edited (answered when nothing was drafted);
    - a pre-filled value the preview held as a scope doubt, sent back unchanged and not answered (confirmed), is left
      out of the evaluation and returned in scope_doubt: it never becomes a silent exclusion."""
    answered = answered or {}
    given = _given(e, values)                         # NOT_STATED -> unknown
    try:
        card = finish(e, s, answered, patient, sources, presets)
        shown = {d.input: d for d in card.draft}
        doubt = [k for k in card.scope_doubt if k not in answered and k in given and k in s.values
                 and _same_shown(e, e.input(k), s.values[k].value, given[k])]
        known = {k: v for k, v in _known(given).items() if k not in doubt}
        t = engine.evaluate(e, known)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.calculate] %s cannot be evaluated: %s", e.key, ex)
        return Calculation(pack=e.key, bundle=bundle)
    pre = preset_values(e, presets)
    shared = _given(e, {}, patient)
    used = []
    for i in e.inputs:
        d, g = s.values.get(i.id), given.get(i.id)
        p, sv = pre.get(i.id), shown.get(i.id)
        by = ""
        if t.inputs[i.id].state == "not_applicable":
            st = "not_applicable"
        elif g is None or g.state == "unknown":
            st = "asked"
        elif _same_shown(e, i, shared.get(i.id), g):
            st = "answered"
        elif d is not None and _same_shown(e, i, d.value, g):
            st = d.tier
        elif d is None and _same_shown(e, i, p, g):
            st, by = "prefilled", "exam"
        elif (sv is not None and sv.state == "assumed" and i.id not in answered
              and sv.value == _show(e, i, g)):
            st = "assumed"                  # sent back unchanged; an explicit answer is answered (review M-3)
        else:
            st = "edited" if d is not None or p is not None else "answered"
        dv = _draft_value(e, i, t, st, g, d if st in ("read", "prefilled") else None, by)
        if i.id in doubt:
            dv.why.append(WHY_WOULD_EXCLUDE)
        used.append(dv)
    text = _outcome_text(e, t, sources) if t.outcome is not None else None
    excluded = t.outcome == DOES_NOT_APPLY
    reason = None
    if excluded:              # the exclusion's own wording needs its one value (spec §7.12 item 1); else generic
        try:
            reason = _exclusion_reason(e, t, known, _Evals(e))
        except (engine.EvaluationError, ValueError) as ex:
            logger.error("[library.calculate] %s exclusion reason failed: %s", e.key, ex)
        text = _exclusion_text(e, t, sources, reason, text)
    out = Calculation(outcome=t.outcome, result=None if excluded else text, exclusion=text if excluded else None,
                      possible=_possible(e, t), needed=list(t.needed), values=used, scope_doubt=doubt,
                      trace=t.model_dump(mode="json") if t.outcome is not None else None, pack=e.key, bundle=bundle)
    try:                                              # the extras fail open: the bare Calculation stands (M2)
        ev = _Evals(e)
        out.most_likely, out.deciding_input, out.deciding = _likely(e, t, known, sources, assume=False, ev=ev)
        out.assumptions = _calc_assumed(e, t, known, given, used, ev)
        out.exclusion_reason = reason
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.calculate] %s extras failed: %s", e.key, ex)
    return out


async def preview_pack(e: Entry, findings: str, history: str, answered: dict[str, str],
                       sources: list[dict] | None = None, finding: str = "",
                       patient: dict[str, str] | None = None) -> Preview:
    return finish(e, await settle_pack(e, findings, history, finding), answered, patient, sources)


def as_entry(e: Entry, sources: list[dict]) -> CardEntry:
    """The pack in the card's existing Entry shape, so the open/preview response contract is unchanged."""
    primary = next((s for s in sources if s.get("role") == "primary"), {})
    return CardEntry(
        key=e.key, name=e.display, version=e.edition, status="verified",
        publication=Publication(title=primary.get("title", ""), body=e.issuer, year=e.edition),
        content=GuidelineContent(
            applies_to=", ".join(e.applies_to.finding_type), summary=" ".join(t.text for t in e.reference.summary),
            branches=[Branch(name=PACK_BRANCH if e.tier == 1 else REFERENCE_BRANCH, state="checked", inputs=[
                Input(id=i.id, question=i.label, options=display_options(e, i), settled_by=i.how_stated)
                for i in e.inputs])]),
        sources=[Source(url=s.get("url", ""), title=s.get("title", ""), tier=1) for s in sources
                 if s.get("role") in ("primary", "amendment")])
