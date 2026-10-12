"""Preview for a library pack (library spec §4, §12 next slice). The model only settles inputs, each with the shortest
verbatim span that settles it, and only from that input's scope: a lesion input from the card's own finding unit, a
patient input from the clinical history or the whole dictation; with no finding unit, lesion inputs are asked. Code
reads every number and its unit from the whole measurement its quote sits in (the model's number must agree); one
batched Jev call per scope checks every value, numbers included, as stated; the radiologist's answers win; the engine
evaluates. Every word of the proposal comes from the entry. Any failure leaves
the input asked, never assumed."""
from __future__ import annotations

import asyncio
import json
import logging
import os

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
_STATE_LABEL = {"absent": "Absent", "not_assessable": "Not assessable"}
_LEAD = {"lesion": "The FINDING states", "patient": "The CLINICAL HISTORY or DICTATION state"}

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
    number must agree with that one reading, or choose between several."""
    if item.state in _STATE_LABEL:
        return InputValue(state=item.state) if item.state in i.states else None
    if item.state != "present":
        return None
    if i.type == "number":
        if texts is not None and i.scope == "lesion" and Q.several(texts[0], i.unit, i.dims):
            return None              # several measurements in this finding: which one is meant is asked, never guessed
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
        v = _value(i, item, [finding] if i.scope == "lesion" else [findings, history])
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


async def _confirm(e: Entry, pending: dict[str, InputValue], finding: str, findings: str,
                   history: str) -> tuple[set[str], bool]:
    """(confirmed ids, whether a Jev call failed). One batched Jev call per scope, run together: "The FINDING states
    <label>: <value>" with the finding unit alone as state (lesion), or the same of the history and the dictation
    (patient). Below SETTLED_MIN, or a failed call, leaves the input asked."""
    states = {"lesion": f"FINDING:\n{finding}",
              "patient": f"CLINICAL HISTORY:\n{history or 'none given'}\n\nDICTATION:\n{findings}"}

    async def one(scope: str) -> tuple[set[str], bool]:
        ids = [k for k in pending if e.input(k).scope == scope]
        if not ids:
            return set(), False
        claims = [f"{_LEAD[scope]} {e.input(k).label}: {_show(e, e.input(k), pending[k]).replace('_', ' ')}"
                  for k in ids]
        try:
            got = await _jev(claims, states[scope])
        except Exception as ex:
            logger.info("[library.preview] value check failed (%s): %d value(s) asked", type(ex).__name__, len(ids))
            return set(), True
        return {k for k, s in zip(ids, got) if s >= P.SETTLED_MIN}, False

    (a, fa), (b, fb) = await asyncio.gather(one("lesion"), one("patient"))
    return a | b, fa or fb


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


async def preview_pack(e: Entry, findings: str, history: str, answered: dict[str, str],
                       sources: list[dict] | None = None, finding: str = "",
                       patient: dict[str, str] | None = None) -> Preview:
    sources = sources or []
    finding = finding.strip()
    given = _given(e, answered, patient)
    # no finding unit: lesion inputs are never read from the whole dictation (another lesion's values); they are asked
    no_unit = not finding and any(i.scope == "lesion" and i.id not in given for i in e.inputs)
    if no_unit:
        logger.info("[library.preview] %s: no finding unit; lesion inputs asked", e.key)
    model, degraded = await _settle(e, given, finding, findings, history)
    # every value, numbers included (read by code from the quote), is put to Jev as stated for its scope: this
    # catches a number of the wrong time point or the wrong role ("was 5 mm, now 9 mm"; swapped volumes)
    pending = {k: v for k, (v, _) in model.items()}
    confirmed, jev_failed = await _confirm(e, pending, finding, findings, history) if pending else (set(), False)
    keep = [k for k in model if k in confirmed]
    given.update({k: model[k][0] for k in keep})
    try:
        t = engine.evaluate(e, given)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.preview] %s cannot be evaluated: %s", e.key, ex)
        return failed(e)
    return _build(e, t, given, {k: model[k][1].quote for k in keep}, sources, degraded or jev_failed or no_unit)


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
