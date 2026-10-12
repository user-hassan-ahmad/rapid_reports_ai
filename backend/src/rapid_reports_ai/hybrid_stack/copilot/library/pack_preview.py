"""Preview for a library pack (library spec §4). The model only settles inputs, each with the shortest verbatim span
that settles it; code checks every value (a real option, an allowed state, a number present in its quote) and every
quote (verbatim, else Jev); the radiologist's answers win; the engine evaluates. Every word of the proposal comes
from the entry: no model-written line, no output index."""
from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel, Field

from ....enhancement_utils import _run_agent_with_model
from ....report_reconcile import QWEN
from .. import preview as P
from .. import registry as R
from ..types import Branch, Entry as CardEntry, GuidelineContent, Input, Preview, Proposal, Publication, Settled, Source
from . import engine
from .schema import BandStep, Entry, InputDef, InputValue

logger = logging.getLogger(__name__)

PACK_BRANCH = "Pack"
TIMEOUT_S = 10.0
_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(cms?\b|centimet\w*|mm\b|millimet\w*)?", re.I)
_STATE_LABEL = {"absent": "Absent", "not_assessable": "Not assessable"}

SETTLE_SYS = """You settle the inputs of one published radiology classification system from a radiologist's dictation. INPUTS lists each input's id, type and allowed values: use nothing else.
For each input the FINDINGS or CLINICAL HISTORY state, return one item:
- input: the input's id;
- state: "present" when the dictation gives its value; "absent" when the dictation says the feature is not there and the input lists absent; "not_assessable" when the dictation says it cannot be assessed and the input lists not_assessable;
- value: when present, for an enum exactly one of its options, for a boolean true or false, for a number the number in the input's unit (centimetres converted to millimetres when the unit is mm); otherwise null;
- quote: the shortest span, copied verbatim from the FINDINGS or CLINICAL HISTORY, that settles it.
Leave out every input the dictation does not state: never settle a value from what is usual or likely, and never invent an input, option or state."""


class RawItem(BaseModel):
    input: str
    state: str = "present"
    value: str | float | bool | None = None
    quote: str = ""


class RawSettle(BaseModel):
    settled: list[RawItem] = Field(default_factory=list)


def _bands_for(e: Entry, i: InputDef) -> list:
    return next((s.bands for s in e.logic if isinstance(s, BandStep) and s.ref == i.id), [])


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
        return f"{float(v.value):g} {i.unit}".strip()
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
        return InputValue(value=float(s))
    except ValueError:
        return None


def _value(i: InputDef, item: RawItem) -> InputValue | None:
    """The model's value if it is a real one: an option, a boolean, an allowed state, or a number that appears in its
    quote (or is ten times one, when the quote is in cm and the unit mm)."""
    if item.state in _STATE_LABEL:
        return InputValue(state=item.state) if item.state in i.states else None
    if item.state != "present" or item.value is None:
        return None
    if i.type == "enum":
        m = {R.norm(o): o for o in i.options}
        hit = m.get(R.norm(str(item.value)))
        return InputValue(value=hit) if hit is not None else None
    if i.type == "boolean":
        return InputValue(value=item.value) if isinstance(item.value, bool) else None
    try:
        x = float(item.value)
    except (TypeError, ValueError):
        return None
    ok = False
    for m in _NUM_UNIT.finditer(item.quote):
        n, u = float(m.group(1)), (m.group(2) or "").lower()
        if u.startswith("c"):
            cands = [n * 10] if i.unit == "mm" else [n]
        else:
            cands = [n]
        ok = ok or any(abs(x - c) < 1e-6 for c in cands)
    return InputValue(value=x) if ok else None


def _inputs_text(e: Entry) -> str:
    lines = []
    for i in e.inputs:
        allowed = (" | ".join(i.options) if i.type == "enum" else "true | false" if i.type == "boolean"
                   else f"number in {i.unit or 'the unit dictated'}")
        states = f"; states allowed: {', '.join(i.states)}" if i.states else ""
        hint = f" (dictated as: {i.how_stated})" if i.how_stated else ""
        lines.append(f"- {i.id}: {i.label}{hint} [{allowed}{states}]")
    return "\n".join(lines)


async def _call(system: str, prompt: str) -> RawSettle:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawSettle, system_prompt=system, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def preview_pack(e: Entry, findings: str, history: str, answered: dict[str, str]) -> Preview:
    given: dict[str, InputValue] = {}
    for k, s in answered.items():
        i = e.input(k)
        v = _answer(e, i, s) if i is not None else None
        if v is not None:
            given[k] = v
    model: dict[str, tuple[InputValue, Settled]] = {}
    prompt = (f"SYSTEM: {e.display}\nINPUTS:\n{_inputs_text(e)}\n\nANSWERED BY THE RADIOLOGIST: "
              f"{', '.join(given) or 'none'}\n\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n{findings}")
    try:
        raw = await _call(SETTLE_SYS, prompt)
        for item in raw.settled:
            i = e.input(item.input)
            if i is None or i.id in given or not item.quote.strip():
                continue
            v = _value(i, item)
            if v is not None:
                model[i.id] = (v, Settled(input=i.id, value=_show(e, i, v), quote=item.quote.strip()))
    except Exception as ex:
        logger.warning("[library.preview] settle %s: %s", type(ex).__name__, str(ex)[:200])
    confirmed = await P.confirm_quotes({k: s for k, (_, s) in model.items()}, findings, history) if model else set()
    # a number is never confirmed by Jev alone: its quote must be verbatim in the dictation
    confirmed = {k for k in confirmed if e.input(k).type != "number" or P._verbatim(model[k][1].quote, findings, history)}
    given.update({k: v for k, (v, _) in model.items() if k in confirmed})
    try:
        t = engine.evaluate(e, given)
    except (engine.EvaluationError, ValueError) as ex:
        logger.error("[library.preview] %s cannot be evaluated: %s", e.key, ex)
        return Preview()
    order = [i.id for i in e.inputs]
    settled = [Settled(input=k, value=_show(e, e.input(k), given[k]),
                       quote=model[k][1].quote if k in model and k in confirmed else "")
               for k in order if k in given]
    possible = [engine.PH.sub("…", engine.render(e, t, e.outcome(o).classification)) for o in t.possible]
    proposal = None
    if t.outcome is not None:
        o = e.outcome(t.outcome)
        cls = engine.render(e, t, o.classification)
        proposal = Proposal(classification=f"{e.display} · {cls}", line=f"{e.display}: {cls}.",
                            recommendation=engine.render(e, t, o.recommendation))
    return Preview(settled=settled, missing=t.needed, proposal=proposal, possible=possible,
                   trace=t.model_dump(mode="json") if t.outcome is not None else None)


def as_entry(e: Entry, sources: list[dict]) -> CardEntry:
    """The pack in the card's existing Entry shape, so the open/preview response contract is unchanged."""
    primary = next((s for s in sources if s.get("role") == "primary"), {})
    return CardEntry(
        key=e.key, name=e.display, version=e.edition, status="verified",
        publication=Publication(title=primary.get("title", ""), body=e.issuer, year=e.edition),
        content=GuidelineContent(
            applies_to=", ".join(e.applies_to.finding_type), summary=" ".join(t.text for t in e.reference.summary),
            branches=[Branch(name=PACK_BRANCH, state="checked", inputs=[
                Input(id=i.id, question=i.label, options=display_options(e, i), settled_by=i.how_stated)
                for i in e.inputs])]),
        sources=[Source(url=s.get("url", ""), title=s.get("title", ""), tier=1) for s in sources
                 if s.get("role") in ("primary", "amendment")])
