"""The preview (spec §5.4): one checked branch applied to this case. Never stored. The model chooses, code copies:
the model settles inputs from the findings and picks one numbered output; the classification and recommendation are
copied verbatim from that output, so a threshold or interval the entry does not hold never reaches a card. What is
missing is computed in code, and every value the model settled has its quote checked against the dictation: code
confirms a quote that appears verbatim (flattened), Jev checks the rest (an input neither confirms is asked, never
assumed). The one model-written string, the report line, keeps a numeric guard; a line that fails it (or is empty)
is replaced by a code-built one, so a proposal copied from the entry is never dropped for its wording."""
from __future__ import annotations

import asyncio
import logging
import os
import re

from pydantic import BaseModel, Field

from ...enhancement_utils import _run_agent_with_model
from ...jev_client import JEV_MODEL, jev_post
from ...report_reconcile import QWEN
from . import jev as J
from . import registry as R
from . import tnm
from .types import Branch, Entry, Preview, Proposal, Settled

logger = logging.getLogger(__name__)

TIMEOUT_S = 10.0
JEV_TIMEOUT_S = 4.0
SETTLED_MIN = 0.6   # provisional: Jev "the FINDINGS or CLINICAL HISTORY state this: <the model's quote>"; set by
                    # the Task 13 lab. Jev verifies the evidence (stated text); the quote -> option mapping stays Qwen's
_NUM = re.compile(r"\d+(?:\.\d+)?")
_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
          "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "twenty-one",
          "twenty-two", "twenty-three", "twenty-four"]
_WORD_RE = re.compile(r"\b(" + "|".join(sorted((w for w in _WORDS[1:]), key=len, reverse=True)) + r")\b", re.I)

PREVIEW_SYS = """You apply one branch of a published radiology classification system or guideline to a radiologist's dictated finding. ENTRY gives the branch's inputs, decision rule and numbered outputs: use nothing else for criteria, thresholds or categories.
1. settled: each ENTRY input whose answer the FINDINGS or CLINICAL HISTORY state, with value = exactly one of that input's options and quote = the shortest span, copied verbatim from the FINDINGS or CLINICAL HISTORY, that settles it. Every settled value needs such a span: a value with no span that settles it is left unsettled, never settled from what is usual or likely. Inputs listed under ANSWERED are settled by the radiologist: use them as given.
2. not_needed: the ids of the inputs the decision does not need for this finding, given what is settled.
3. output: the number of the one OUTPUTS row that applies, only when every input the decision needs is settled; otherwise null.
4. line: when output is set, one report sentence stating the classification for this finding: name the system and version, and the row's category when it has one; no recommendation and no interval. "" when output is null.
Never invent an input, option, category, threshold or interval the ENTRY does not contain."""

TNM_NOTE = """
TNM: an axis the FINDINGS say cannot be assessed on this scan is settled with its X option (TX, NX, MX), and its quote is the span stating that it cannot be assessed. An axis the FINDINGS do not mention is left unsettled, never X. The stage is computed elsewhere: leave output null and line ""."""


class RawPreview(BaseModel):
    """What the model returns: choices only. Code builds the Preview from it."""
    settled: list[Settled] = Field(default_factory=list)
    not_needed: list[str] = Field(default_factory=list)
    output: int | None = None
    line: str = ""


def _entry_text(e: Entry, b: Branch) -> str:
    ins = "\n".join(f"- {i.id}: {i.question} [{' | '.join(i.options)}]" for i in b.inputs)
    outs = "\n".join(f"{n}. when {o.when}: {o.classification} | {o.recommendation}"
                     for n, o in enumerate(b.outputs, 1))
    return f"SYSTEM: {e.name} {e.version}\nBRANCH: {b.name}\nINPUTS:\n{ins or '(none)'}\nRULE: {b.rule}\nOUTPUTS:\n{outs}"


def _numbers(s: str) -> set[str]:
    s = _WORD_RE.sub(lambda m: str(_WORDS.index(m.group(1).lower())), s or "")
    return set(_NUM.findall(s))


def line_numbers_ok(line: str, e: Entry, b: Branch, findings: str) -> bool:
    """Every number in the model-written line (number words included) comes from the entry or the findings."""
    allowed = _numbers(" ".join([e.name, e.version, b.rule, findings,
                                 *(f"{o.when} {o.classification} {o.recommendation}" for o in b.outputs),
                                 *(" ".join(i.options) for i in b.inputs)]))
    return _numbers(line) <= allowed


def _self_settled(e: Entry, b: Branch) -> dict[str, str]:
    """TNM inputs with one option (a pT-only site's clinical TX) answer themselves: never asked, never missing.
    TNM only: elsewhere a one-option input is more likely a structuring slip than a settled fact."""
    return {i.id: i.options[0] for i in b.inputs if len(i.options) == 1} if tnm.is_tnm(e.key) else {}


def _required(e: Entry, b: Branch) -> list[str]:
    """TNM: the site's axes, plus histology where the stage table varies by it. Others: every input."""
    if tnm.is_tnm(e.key):
        ids = {i.id for i in b.inputs}
        return [i for i in ["T", "N", "M", "histology"] if i in ids]
    return [i.id for i in b.inputs]


def _state(findings: str, history: str) -> str:
    return f"CLINICAL HISTORY:\n{history or 'none given'}\n\nFINDINGS:\n{findings}"


async def _jev_settled(findings: str, history: str, quotes: list[str]) -> dict[str, float]:
    """One batched call: per quoted span, does the dictation state it. Jev checks the evidence (stated text, its
    strength), not the inference from it to an option (Qwen's judgement, read against the entry's rule)."""
    qs = {f"s{n}": {"type": "noul", "instructions": f"The FINDINGS or CLINICAL HISTORY state this: {q}"}
          for n, q in enumerate(quotes)}
    r = await jev_post({"model": JEV_MODEL, "state": _state(findings, history), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
    r.raise_for_status()
    return J.scores(r.json(), qs)   # malformed raises: an outage, never a low score


def _verbatim(quote: str, findings: str, history: str) -> bool:
    """A deterministic fact, not a judgement: the quote, flattened as jev._flat does (case, whitespace, punctuation
    runs), appears as whole tokens in the flattened findings or history. No minimum token count (a settling span is
    often one word); at least 2 characters."""
    q = J._flat(quote)
    return len(q) >= 2 and any(f" {q} " in f" {J._flat(t)} " for t in (findings, history) if t)


async def _check(model: dict[str, Settled], b: Branch, findings: str, history: str) -> set[str]:
    """The model-settled inputs whose quoted evidence is confirmed: by code when the quote is verbatim in the
    dictation, else by Jev. No quote, no confirmation; a Jev failure confirms none of the quotes it was asked about
    (ask, never assume)."""
    ids = [i for i, s in model.items() if s.quote.strip()]
    confirmed = {i for i in ids if _verbatim(model[i].quote, findings, history)}
    ask = [i for i in ids if i not in confirmed]
    if not ask:
        return confirmed
    try:
        scores = await _jev_settled(findings, history, [model[i].quote.strip() for i in ask])
    except Exception as ex:
        logger.info("[copilot.preview] settled check failed (%s): %d unconfirmed model value(s) asked",
                    type(ex).__name__, len(ask))
        return confirmed
    return confirmed | {i for n, i in enumerate(ask) if scores.get(f"s{n}", 0.0) >= SETTLED_MIN}


def validate(raw: RawPreview, e: Entry, b: Branch, answered: dict[str, str], confirmed: set[str] | None = None
             ) -> tuple[Preview, bool, dict[str, str]]:
    """Settled = the radiologist's answers (and self-settled TNM inputs) + model values that are real options and
    whose quotes were confirmed (`confirmed`; None = no check). Missing = required − settled − not_needed; a rejected
    or unconfirmed model value is always missing. Returns the Preview without a proposal, whether a model value
    (a real option) disagreed with a radiologist's answer, and the given values that survived filtering."""
    opts = {i.id: i.options for i in b.inputs}
    given = {k: v for k, v in {**_self_settled(e, b), **answered}.items() if k in opts and v in opts[k]}
    nopts = {k: {R.norm(o) for o in v} for k, v in opts.items()}
    disagree = any(s.input in given and R.norm(s.value) in nopts[s.input] and R.norm(s.value) != R.norm(given[s.input])
                   for s in raw.settled)
    model = {s.input: s for s in raw.settled if s.input in opts and s.input not in given and s.value in opts[s.input]}
    forced = {s.input for s in raw.settled if s.input in opts and s.input not in given} - set(model)   # bad values
    if confirmed is not None:
        forced |= set(model) - confirmed
        model = {k: v for k, v in model.items() if k in confirmed}
    settled = {**{k: Settled(input=k, value=v, quote="") for k, v in given.items()}, **model}
    skip = set() if tnm.is_tnm(e.key) else set(raw.not_needed)
    missing = [i for i in _required(e, b) if i not in settled and (i not in skip or i in forced)]
    order = [i.id for i in b.inputs]
    return Preview(settled=sorted(settled.values(), key=lambda s: order.index(s.input)), missing=missing), disagree, given


def _proposal(raw: RawPreview, e: Entry, b: Branch, findings: str) -> Proposal | None:
    """Code copies the chosen output: classification and recommendation verbatim; only the line is model text."""
    if raw.output is None or not 1 <= raw.output <= len(b.outputs):
        return None
    o = b.outputs[raw.output - 1]
    ident = f"{e.name} {e.version}".strip()
    classification = f"{ident} · {o.classification}".strip(" ·") if o.classification else ident
    line = (raw.line or "").strip()
    if not line or not line_numbers_ok(line, e, b, findings):
        logger.info("[copilot.preview] model line %s; code-built line used (%s)",
                    "empty" if not line else "failed the numeric guard", e.key)
        line = f"{ident}: {o.classification}." if o.classification else f"{ident} applies."   # report style, no middle dot
    return Proposal(classification=classification, line=line, recommendation=o.recommendation)


async def _call(system: str, prompt: str) -> RawPreview:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawPreview, system_prompt=system, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def preview(e: Entry, branch: str, findings: str, history: str, answered: dict[str, str]) -> Preview:
    b = e.content.branch(branch)
    if b is None or b.state != "checked":
        return Preview()
    is_tnm = tnm.is_tnm(e.key)
    if not is_tnm and not b.outputs:
        logger.info("[copilot.preview] checked branch has no outputs (%s/%s)", e.key, branch)
    given = {**_self_settled(e, b), **answered}
    answered_txt = "\n".join(f"- {k}: {v}" for k, v in given.items()) or "(none)"
    prompt = (f"ENTRY:\n{_entry_text(e, b)}\n\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n{findings}"
              f"\n\nANSWERED:\n{answered_txt}")
    try:
        raw = await _call(PREVIEW_SYS + (TNM_NOTE if is_tnm else ""), prompt)
    except Exception as ex:
        logger.warning("[copilot.preview] %s: %s", type(ex).__name__, str(ex)[:200])
        return validate(RawPreview(), e, b, answered)[0]
    unchecked, _, valid_given = validate(raw, e, b, answered)
    model = {s.input: s for s in unchecked.settled if s.input not in valid_given}
    confirmed = await _check(model, b, findings, history)
    out, disagree, _ = validate(raw, e, b, answered, confirmed)
    if out.missing:
        return out
    if is_tnm:   # the model only settles axes; code assembles the proposal (and any stage)
        site = tnm.site_for(e.key)
        prop = tnm.proposal(site, {s.input: s.value for s in out.settled}) if site else None
        return out.model_copy(update={"proposal": prop})
    if disagree:
        logger.info("[copilot.preview] a model value contradicts the radiologist's answer (%s)", e.key)
        return out
    if raw.output is None:
        logger.info("[copilot.preview] nothing missing but the model chose no output (%s)", e.key)
    return out.model_copy(update={"proposal": _proposal(raw, e, b, findings)})
