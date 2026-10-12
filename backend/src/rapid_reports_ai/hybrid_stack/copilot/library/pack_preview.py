"""Preview for a library pack (library spec §4, §12 next slice). The model only settles inputs, each with the shortest
verbatim span that settles it, and only from that input's scope: a lesion input from the card's own finding unit, a
patient input from the clinical history or the whole dictation; with no finding unit, lesion inputs are asked. Code
reads every number and its unit from the whole measurement its quote sits in (the model's number must agree); one
batched Jev call per scope checks every number as stated for its scope, and a lesion number also needs the finding
to hold no other number; each enum or boolean value is checked by Jev against its quote alone (the quote must state it). Every lesion input, of any type, also needs the finding to describe one lesion of
any kind (no multiplicity word, and Jev's one-lesion claim): another lesion's lobe, type or size is never lent to
this one. The radiologist's answers win; the engine evaluates. Every word of the proposal comes from the entry. Any failure leaves
the input asked, never assumed."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from ....enhancement_utils import _run_agent_with_model
from ....report_reconcile import QWEN
from .. import jev as J
from .. import preview as P
from .. import registry as R
from ..types import Branch, Entry as CardEntry, GuidelineContent, Input, Preview, Proposal, Publication, Settled, Source
from . import engine
from . import quantity as Q
from .describe import citation
from .schema import DOES_NOT_APPLY, BandStep, Entry, InputDef, InputValue, RulesStep, conds

logger = logging.getLogger(__name__)

PACK_BRANCH = "Pack"
REFERENCE_BRANCH = "Reference"
TIMEOUT_S = 10.0
ONE_LESION_MIN = 0.8      # Jev ONE_LESION: below it, every lesion input on the card is asked
# one lesion of any kind, never the pack's own noun: a granuloma, scar or cyst beside the nodule is a second lesion
ONE_LESION = "The FINDING describes only one lesion of any kind (nodule, granuloma, mass, cyst, scar or other)"
_STATE_LABEL = {"absent": "Absent", "not_assessable": "Not assessable"}
_LEAD = {"lesion": "The FINDING states", "patient": "The CLINICAL HISTORY or DICTATION state"}
QUOTE_MIN = 0.8           # Jev "The QUOTE states <label>: <value>" on the quote alone: below it, asked
_QUOTE_OF = {"lesion": "a verbatim phrase from a radiology report about one lesion",
             "patient": "a verbatim phrase from a radiology request or report about the patient or the examination"}

SETTLE_SYS = """You settle the inputs of one published radiology classification system for ONE finding. INPUTS lists each open input's id, scope, type and allowed values: use nothing else.
An input's scope decides where it may be settled from:
- [lesion]: the FINDING only, never another lesion in the dictation, even one of the same kind;
- [patient]: the CLINICAL HISTORY or the DICTATION (the patient, the examination or the study as a whole).
For each input its scope states, return one item:
- input: the input's id;
- state: "present" when the value is given; "absent" when the feature is said not to be there and the input lists absent; "not_assessable" when it is said that it cannot be assessed and the input lists not_assessable;
- value: when present, for an enum exactly one of its options, for a boolean true or false, for a number the number as dictated; otherwise null;
- quote: the shortest span, copied verbatim from the FINDING ([lesion]) or from the CLINICAL HISTORY or DICTATION ([patient]), that settles it; a number's quote is the whole measurement as dictated, with its unit.
Leave out every input that is not stated: never settle a value from what is usual or likely, and never invent an input, option or state."""


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
    """A radiologist's choice, as display_options offers it (or a typed number)."""
    s = s.strip()
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
    number must agree with that one reading, or choose between several. A lesion number settles only when its
    finding holds no other number (quantity.alone)."""
    if item.state in _STATE_LABEL:
        return InputValue(state=item.state) if item.state in i.states else None
    if item.state != "present":
        return None
    if i.type == "number":
        x = (Q.pick(Q.readings(item.quote, i.unit, i.dims), _num(item.value), i.unit) if texts is None
             else Q.settle(item.quote, texts, i.unit, i.dims, _num(item.value)))
        if x is not None and texts is not None and i.scope == "lesion" and not Q.alone(texts[0], item.quote, x,
                                                                                       i.unit, i.dims):
            return None              # another number in this finding: which one is meant is asked, never guessed
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
    several = bool(finding) and Q.many(finding, _nouns(e))
    for item in raw.settled:
        i = e.input(item.input)
        q = item.quote.strip()
        if i is None or i.id not in ids or not q or not _in_scope(i, q, finding, findings, history):
            continue
        texts = [finding] if i.scope == "lesion" else [findings, history]
        if i.type != "number" and _modified(q, texts):
            continue                 # "spiculated" from "not spiculated", "solid" from "part-solid": asked
        v = _value(i, item, texts)
        if v is not None and i.scope == "lesion" and several:
            continue                 # the finding names other lesions: which one's value is meant is asked
        if v is not None:
            out[i.id] = (v, Settled(input=i.id, value=_show(e, i, v), quote=q))
    return out, False


async def _jev(claims: list[str], state: str) -> list[float]:
    qs = {f"v{n}": {"type": "noul", "instructions": c} for n, c in enumerate(claims)}
    r = await P.jev_post({"model": P.JEV_MODEL, "state": state, "questions": qs},
                         os.environ.get("OPENROUTER_API_KEY", ""), P.JEV_TIMEOUT_S)
    r.raise_for_status()
    s = J.scores(r.json(), qs)        # malformed raises: an outage, never a low score
    return [s[f"v{n}"] for n in range(len(claims))]


def _nouns(e: Entry) -> list[str]:
    """The pack's lesion nouns, from the finding types it applies to."""
    return [t for t in e.applies_to.finding_type if t.strip()] or ["lesion"]


UNENHANCED_MIN = 0.8      # Jev _phase_claim below it: the attenuation is asked (review M2)


def _phase_claim(shown: str) -> str:
    """An attenuation settles only when the finding states it was measured unenhanced: a post-contrast value, or one
    with no phase in a two-phase study, may not be the value the input means."""
    return f"The FINDING states that {shown} was measured on an unenhanced (non-contrast) series"


def _quote_state(i: InputDef, quote: str) -> str:
    """The quote alone as evidence, with the input's definition beside it (not part of it): the value must be in the
    quote's own words, never in the rest of the finding or in what is usual."""
    return (f"QUOTE ({_QUOTE_OF[i.scope]}; the only evidence):\n{quote}\n\n"
            f"DEFINITION of {i.label}: {i.how_stated or i.label}\n\n"
            "A value is stated only when the QUOTE's own words give it; a value that is merely not contradicted, "
            "usual or assumed is not stated.")


def _quote_claim(e: Entry, i: InputDef, v: InputValue) -> str:
    return f"The QUOTE states {i.label}: {_show(e, i, v).replace('_', ' ')}"


async def _confirm(e: Entry, pending: dict[str, tuple[InputValue, str]], finding: str, findings: str,
                   history: str) -> tuple[set[str], bool]:
    """(confirmed ids, whether a Jev call failed). Run together:
    - per scope, one batched call: "The FINDING states <label>: <value>" with the finding unit alone as state
      (lesion), or the same of the history and the dictation (patient). A number needs SETTLED_MIN, an enum or a
      boolean QUOTE_MIN. The lesion batch also carries ONE_LESION whenever any lesion input is pending: below
      ONE_LESION_MIN every lesion input is asked;
    - per enum or boolean value, one more call on its QUOTE alone: "The QUOTE states <label>: <value>"; QUOTE_MIN.
      An enum or boolean settles only when both claims pass: the quote must state it, and the finding must too
      (a quote stripped of its context, "spiculated" from "not spiculated", fails the second).
    A failed call leaves its inputs asked (the lesion batch: every lesion input)."""
    states = {"lesion": f"FINDING:\n{finding}",
              "patient": f"CLINICAL HISTORY:\n{history or 'none given'}\n\nDICTATION:\n{findings}"}

    async def batch(scope: str) -> tuple[set[str], bool, bool]:
        """(confirmed ids, one lesion, failed)"""
        ids = [k for k in pending if e.input(k).scope == scope]
        one_lesion = scope == "lesion" and bool(ids)
        if not ids:
            return set(), True, False
        claims = [f"{_LEAD[scope]} {e.input(k).label}: {_show(e, e.input(k), pending[k][0]).replace('_', ' ')}"
                  for k in ids]
        # an attenuation not stated as unenhanced may be an enhanced value, not the one the input means: asked
        hu = [k for k in ids if scope == "lesion" and e.input(k).type == "number"
              and Q.FAMILY.get(Q.canon(e.input(k).unit)) == "attenuation"]
        claims += [_phase_claim(_show(e, e.input(k), pending[k][0])) for k in hu]
        if one_lesion:                 # one lesion or several is a question of meaning: Jev, in the same batch
            claims.append(ONE_LESION)
        try:
            got = await _jev(claims, states[scope])
        except Exception as ex:
            logger.info("[library.preview] %s value check failed (%s)", scope, type(ex).__name__)
            return set(), False, True
        if one_lesion and got[-1] < ONE_LESION_MIN:
            logger.info("[library.preview] %s: finding not one lesion (%.2f); lesion inputs asked", e.key, got[-1])
        phased = {k for k, s in zip(hu, got[len(ids):]) if s < UNENHANCED_MIN}
        bar = {k: P.SETTLED_MIN if e.input(k).type == "number" else QUOTE_MIN for k in ids}
        return ({k for k, s in zip(ids, got) if s >= bar[k]} - phased,
                not one_lesion or got[-1] >= ONE_LESION_MIN, False)

    async def quote(k: str) -> tuple[str, float | None]:
        i = e.input(k)
        v, q = pending[k]
        try:
            return k, (await _jev([_quote_claim(e, i, v)], _quote_state(i, q)))[0]
        except Exception as ex:
            logger.info("[library.preview] quote check failed (%s)", type(ex).__name__)
            return k, None

    choices = [k for k in pending if e.input(k).type != "number"]
    (a, one, fa), (b, _, fb), *qs = await asyncio.gather(batch("lesion"), batch("patient"),
                                                        *(quote(k) for k in choices))
    quoted = {k for k, s in qs if s is not None and s >= QUOTE_MIN}
    ok = {k for k in a | b if e.input(k).type == "number" or k in quoted}
    if not one or fa:
        ok = {k for k in ok if e.input(k).scope != "lesion"}
    return ok, fa or fb or any(s is None for _, s in qs)


# A prior study is asymmetric (lab fix round item 3): "Yes" settles only from the nodule's own finding, as any lesion
# input; "No" never from the model, only from the whole dictation, when Jev finds it states there is no previous
# imaging of the examined region, finds no previous imaging mentioned at all, and no word says one may exist elsewhere.
NO_PRIOR_INPUT = "prior_study"
NO_PRIOR_MIN = 0.8
PRIOR_MENTIONED_MAX = 0.5
PRIOR_MENTIONED = "The CLINICAL HISTORY or DICTATION mentions any previous imaging that exists or was performed"
# the history alone: any earlier imaging of the patient (a CT abdomen that showed the nodule) may be the prior study
# (live: "previous imaging" alone scored a CT abdomen that showed the nodule 0.27-0.33; naming the kinds 0.96)
HISTORY_MENTIONED = ("The CLINICAL HISTORY mentions a scan, X-ray or other imaging of this patient, of any date or "
                     "body part")
# a history or dictation that follows a known finding implies a previous study, whatever else is said: asked
_FOLLOW_UP = re.compile(r"\b(?:known|follow[\s-]?up|surveillance|interval)\b", re.I)
# a word saying a previous study may exist elsewhere or later ("available" is the common UK form: "none available
# on PACS at the time of reporting"): asked
_ELSEWHERE = re.compile(r"\b(?:requested|awaited|awaiting|pending|to\s+follow|available|unavailable|pacs|iep"
                        r"|another\s+trust|other\s+hospital|outside|external)\b", re.I)
_PRIOR_WORD = re.compile(r"\b(?:prior|prev|previous|previously|comparison|compared|earlier|old)\b", re.I)
_SENTENCE = re.compile(r"[^.;\n]+(?:\.(?=\d)[^.;\n]*)*")


def _no_prior_claim(e: Entry) -> str:
    region = " or ".join(e.applies_to.region) or "region examined"
    return f"The DICTATION states there is no previous imaging that includes the {region}"


async def _no_prior(e: Entry, findings: str, history: str) -> tuple[str | None, bool]:
    """(the dictation's sentence that settles "no previous imaging", or None; whether the Jev call failed). Jev sees
    the clinical history as well: "No" settles only when neither it nor the dictation mentions previous imaging, the
    history alone mentions none (HISTORY_MENTIONED), and no follow-up word is in either."""
    i = e.input(NO_PRIOR_INPUT)
    if i is None or i.type != "boolean" or _ELSEWHERE.search(f"{findings}\n{history}") or _FOLLOW_UP.search(f"{findings}\n{history}"):
        return None, False
    quote = next((m.group(0).strip() for m in _SENTENCE.finditer(findings or "") if _PRIOR_WORD.search(m.group(0))),
                 None)
    if quote is None:
        return None, False
    modality = " or ".join(e.applies_to.modality) or "imaging"
    try:
        no, mentioned, in_history = await _jev([_no_prior_claim(e), PRIOR_MENTIONED, HISTORY_MENTIONED],
                                   f"CLINICAL HISTORY:\n{history or 'none given'}\n\n"
                                   f"DICTATION (a {modality} report; any previous imaging would be listed here):\n"
                                   f"{findings}")
    except Exception as ex:
        logger.info("[library.preview] prior check failed (%s)", type(ex).__name__)
        return None, True
    ok = no >= NO_PRIOR_MIN and mentioned < PRIOR_MENTIONED_MAX and in_history < PRIOR_MENTIONED_MAX
    return (quote if ok else None), False


def _outcome_text(e: Entry, t: engine.Trace, sources: list[dict]) -> Proposal | None:
    """The reached outcome as the entry words it, or None when its text still cites an unknown input."""
    o = e.outcome(t.outcome)
    cls, rec = engine.render(e, t, o.classification), engine.render(e, t, o.recommendation)
    caveats = [engine.render(e, t, c) for c in o.caveats]
    if any(engine.PH.search(x) for x in (cls, rec, *caveats)):
        logger.info("[library.preview] %s: outcome %s cites an input still unknown; no proposal", e.key, o.id)
        return None
    return Proposal(classification=f"{e.display} · {cls}", line=f"{e.display}: {cls}.", recommendation=rec,
                    caveats=caveats, citations=_fired(e, t, sources))


def _build(e: Entry, t: engine.Trace, given: dict[str, InputValue], quotes: dict[str, str], sources: list[dict],
           degraded: bool) -> Preview:
    """The card (spec §7.4): eligibility asks first; the state worked out in code; a does_not_apply outcome is shown as
    an exclusion, never as a proposal, so it can never be Applied."""
    elig = [i.id for i in e.inputs if i.role == "eligibility"]
    order = elig + [i.id for i in e.inputs if i.role != "eligibility"]
    needed = sorted(t.needed, key=order.index)
    settled = [Settled(input=k, value=_show(e, e.input(k), given[k]), quote=quotes.get(k, ""),
                       fact=e.input(k).fact or "") for k in (i.id for i in e.inputs) if k in given]
    possible = [engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)) for o in t.possible]
    text = _outcome_text(e, t, sources) if t.outcome is not None else None
    if t.outcome == DOES_NOT_APPLY:
        state, proposal, exclusion = "does_not_apply", None, text
        logger.info("[library.preview] %s does not apply (eligibility given: %s)", e.key,
                    ", ".join(k for k in elig if k in given) or "none")
    else:
        state = "check_first" if set(elig) & set(needed) else "applies"
        proposal, exclusion = text, None
    return Preview(settled=settled, missing=needed, proposal=proposal, exclusion=exclusion, state=state,
                   possible=possible, bounded=t.bounded, asks=_asks(e, t, sources, needed),
                   trace=t.model_dump(mode="json") if t.outcome is not None else None, degraded=degraded)


def failed(e: Entry) -> Preview:
    """A preview that never ran (an error or a timeout): nothing settled; eligibility, if the pack has any, was never
    assessed, so the card is check_first rather than applies."""
    return Preview(degraded=True,
                   state="check_first" if any(i.role == "eligibility" for i in e.inputs) else "applies")


@dataclass
class Settlement:
    """What the dictation settles for one card, read once per (dictation, finding, history) and never again: the
    preview cache holds it, and each answer re-runs only the engine over it (`finish`), so a settled value cannot
    change between answers."""
    values: dict[str, tuple[InputValue, str]] = field(default_factory=dict)   # input -> (value, quote)
    failed: bool = False       # the model or a Jev check failed: inputs it could have settled are asked; cached all
                               # the same (answers never settle again), and a fresh /open may retry it once
    no_unit: bool = False      # no finding unit: every lesion input is asked (deterministic, so cached)


async def settle_pack(e: Entry, findings: str, history: str, finding: str = "") -> Settlement:
    """Every input the dictation settles, whatever the radiologist has answered (answers win in `finish`)."""
    finding = finding.strip()
    # no finding unit: lesion inputs are never read from the whole dictation (another lesion's values); they are asked
    no_unit = not finding and any(i.scope == "lesion" for i in e.inputs)
    if no_unit:
        logger.info("[library.preview] %s: no finding unit; lesion inputs asked", e.key)
    (model, degraded), (no_prior, prior_failed) = await asyncio.gather(
        _settle(e, {}, finding, findings, history), _no_prior(e, findings, history))
    if degraded:
        no_prior = None                      # no model: no "the finding says yes" cross-check, so never a lone "No"
    if NO_PRIOR_INPUT in model and model[NO_PRIOR_INPUT][0].value is not True:
        del model[NO_PRIOR_INPUT]            # "No" (or a state) never from the model: only from the whole dictation
    # every number (read by code from the quote) is put to Jev as stated for its scope: this catches a number of the
    # wrong time point or role ("was 5 mm, now 9 mm"; swapped volumes); every enum or boolean, as stated by its quote
    pending = {k: (v, st.quote) for k, (v, st) in model.items()}
    confirmed, jev_failed = await _confirm(e, pending, finding, findings, history) if pending else (set(), False)
    values = {k: pending[k] for k in model if k in confirmed}
    if no_prior is not None and NO_PRIOR_INPUT in values:
        del values[NO_PRIOR_INPUT]           # the finding says yes, the dictation no: asked
    elif no_prior is not None and NO_PRIOR_INPUT not in model:
        values[NO_PRIOR_INPUT] = (InputValue(value=False), no_prior)
    return Settlement(values=values, failed=degraded or jev_failed or prior_failed, no_unit=no_unit)


def finish(e: Entry, s: Settlement, answered: dict[str, str], patient: dict[str, str] | None = None,
           sources: list[dict] | None = None) -> Preview:
    """The card from a settlement and the radiologist's answers, by the engine alone: no model, no Jev. An answer
    (the card's own, then the shared patient one) overrides the settled value for that input."""
    given = _given(e, answered, patient)
    quotes = {}
    for k, (v, q) in s.values.items():
        if k not in given:
            given[k], quotes[k] = v, q
    try:
        t = engine.evaluate(e, given)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.preview] %s cannot be evaluated: %s", e.key, ex)
        return failed(e)
    return _build(e, t, given, quotes, sources or [], s.failed or s.no_unit)


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
