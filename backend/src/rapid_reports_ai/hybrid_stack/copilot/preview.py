"""The preview (spec §5.4): one checked branch applied to this case. Never stored. A proposal exists only when every
required input is settled, and every number in it must come from the branch, the entry's identity or the findings
(the numeric guard): a threshold the entry does not hold never reaches a card."""
from __future__ import annotations

import asyncio
import logging
import re

from ...enhancement_utils import _run_agent_with_model
from ...report_reconcile import QWEN
from . import tnm
from .types import Branch, Entry, Preview, Proposal, Settled

logger = logging.getLogger(__name__)

TIMEOUT_S = 10.0
_NUM = re.compile(r"\d+(?:\.\d+)?")

PREVIEW_SYS = """You apply one branch of a published radiology classification system or guideline to a radiologist's dictated finding. ENTRY gives the branch's inputs, decision rule and outputs: use nothing else for criteria, thresholds, categories or recommendations.
1. settled: each ENTRY input that the FINDINGS or CLINICAL HISTORY already answer, with value = exactly one of that input's options and quote = the shortest verbatim span that settles it. Inputs listed under ANSWERED are settled by the radiologist: use them as given.
2. missing: the ids of the inputs the decision still needs that nothing settles (an input the decision does not need for this finding is neither settled nor missing).
3. proposal: only when missing is empty, otherwise null:
   - classification: "<system> <version>" followed by the ENTRY output's category label when it has one
   - line: one report sentence stating the classification for this finding (name the system and version; no recommendation, no interval)
   - recommendation: the ENTRY output's recommendation worded for this finding, "" when the output has none
An axis or input the FINDINGS say cannot be assessed on this scan is settled with its X option (TX, NX, MX) when the input offers one.
Never invent an input, option, category, threshold or interval the ENTRY does not contain."""


def _entry_text(e: Entry, b: Branch) -> str:
    ins = "\n".join(f"- {i.id}: {i.question} [{' | '.join(i.options)}]" for i in b.inputs)
    outs = "\n".join(f"- when {o.when}: {o.classification} | {o.recommendation}" for o in b.outputs)
    return f"SYSTEM: {e.name} {e.version}\nBRANCH: {b.name}\nINPUTS:\n{ins or '(none)'}\nRULE: {b.rule}\nOUTPUTS:\n{outs}"


def numbers_ok(p: Proposal, e: Entry, b: Branch, findings: str) -> bool:
    allowed_text = " ".join([e.name, e.version, b.rule, findings,
                             *(f"{o.when} {o.classification} {o.recommendation}" for o in b.outputs),
                             *(" ".join(i.options) for i in b.inputs)])
    allowed = set(_NUM.findall(allowed_text))
    return all(n in allowed for n in _NUM.findall(f"{p.classification} {p.line} {p.recommendation}"))


def validate(raw: Preview, b: Branch, answered: dict[str, str]) -> Preview:
    """Keep only settled values that are real options of real inputs; the radiologist's answers win; a proposal
    stands only when nothing required is missing."""
    opts = {i.id: i.options for i in b.inputs}
    settled = {s.input: s for s in raw.settled if s.input in opts and s.value in opts[s.input]}
    for k, v in answered.items():
        if k in opts and v in opts[k]:
            settled[k] = Settled(input=k, value=v, quote="")
    missing = [m for m in dict.fromkeys(raw.missing) if m in opts and m not in settled]
    return Preview(settled=list(settled.values()), missing=missing, proposal=raw.proposal if not missing else None)


def _self_settled(e: Entry, b: Branch) -> dict[str, str]:
    """TNM inputs with one option (a pT-only site's clinical TX) answer themselves: never asked, never missing.
    TNM only: elsewhere a one-option input is more likely a structuring slip than a settled fact."""
    return {i.id: i.options[0] for i in b.inputs if len(i.options) == 1} if tnm.is_tnm(e.key) else {}


async def _call(prompt: str) -> Preview:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=Preview, system_prompt=PREVIEW_SYS, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def preview(e: Entry, branch: str, findings: str, history: str, answered: dict[str, str]) -> Preview:
    b = e.content.branch(branch)
    if b is None or b.state != "checked":
        return Preview()
    answered = {**_self_settled(e, b), **answered}
    answered_txt = "\n".join(f"- {k}: {v}" for k, v in answered.items()) or "(none)"
    prompt = (f"ENTRY:\n{_entry_text(e, b)}\n\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n{findings}"
              f"\n\nANSWERED:\n{answered_txt}")
    try:
        raw = await _call(prompt)
    except Exception as ex:
        logger.warning("[copilot.preview] %s: %s", type(ex).__name__, str(ex)[:200])
        return Preview(missing=[i.id for i in b.inputs if i.id not in answered])
    out = validate(raw, b, answered)
    if tnm.is_tnm(e.key):   # TNM: the model only settles axes; code assembles the proposal (and any stage)
        site = tnm.site_for(e.key)
        prop = tnm.proposal(site, {s.input: s.value for s in out.settled}) if site and not out.missing else None
        return out.model_copy(update={"proposal": prop})
    if out.proposal is not None and not numbers_ok(out.proposal, e, b, findings):
        logger.info("[copilot.preview] proposal dropped by the numeric guard (%s)", e.key)
        out = out.model_copy(update={"proposal": None})
    return out
