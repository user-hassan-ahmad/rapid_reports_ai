"""Shared reconcile engine: the pathway-neutral half of the compiled brief.

Both report pathways (quick, templated) reconcile a skill sheet with one dictation through these
calls; each keeps its own extractor, compiler and prompts (spec
2026-09-30-template-pipeline-mirror-design §1). Moved verbatim from quick_report_brief.py.

    Jev   yes/no on stated text (conditions, affected normals, findings present)
    Qwen  negatives: contradicted / expected / keep; bundled split; impression plan; fallback
    code  routing (route_finding), caps, labels
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Literal, Optional

import httpx
from pydantic import BaseModel, field_validator

from .enhancement_utils import _run_agent_with_model

logger = logging.getLogger(__name__)

JEV_URL = "https://openrouter.ai/api/v1/systemone"
JEV_MODEL = "typesafe/jev-1.13"
QWEN = "qwen-3.8-27b"
JEV_TIMEOUT_S = 6.0
QWEN_TIMEOUT_S = 10.0


def _quoted(text: str) -> List[str]:
    return re.findall(r'"([^"]+)"', text)


def _is_bundled(neg: str) -> bool:
    return bool(re.search(r",|\bor\b", re.split(r"\s+to suggest\s", neg)[0]))


# Policy 1 for dictated findings: a finding Jev finds reported brings the negatives the analyser
# listed for it. Cut-offs on Jev's score; PRESENT_HIGH sits in the measured gap between clear
# (0.86-0.99) and hedged (<=0.72) reports (ledger L-45).
PRESENT_LOW = 0.5
PRESENT_HIGH = 0.8
MAX_FINDING_OPTIONS = 4


Q_FINDING = "The dictated findings report this imaging finding, in any wording or size: "


@dataclass
class FindingNegative:
    key: str
    text: str
    tag: str   # "core" | "contextual"


def route_finding(label: str, present: float, tag: str) -> str:
    """Rule C: stated only when the finding is clearly reported and the negative is core."""
    if present < PRESENT_LOW or label == "contradicted":
        return "dropped"
    if label == "expected":
        return "do_not_assert"
    if present >= PRESENT_HIGH and tag == "core":
        return "stated"
    return "offered"


_MEASUREMENT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|°|(?:mm|cm|ml|mL|cc|HU|mmHg|m/s|degrees?)(?![A-Za-z]))")


# ── reconcile ────────────────────────────────────────────────────────────────

Q_AFFECTED = ("Is this statement from a report template affected by the dictated findings? Affected means a dictated "
              "finding contradicts it, or acts on the structure it describes (displaces, compresses, obstructs, drains "
              "into, extends to, involves it, or is a finding of the same kind in that structure), so it cannot be "
              "written as it stands. Statement: ")
Q_PRESENT = "A dictated finding shows that this diagnosis or branch is present in this case. Branch: "
Q_REC_UNMET = ("The condition for this recommendation is not met by the dictated findings, or it belongs to a "
               "diagnosis the findings rule out. Recommendation: ")
Q_STYLE_MATCH = "This example report sentence describes the same kind of finding as one that is dictated in this case. Example: "


class NegativeDecision(BaseModel):
    index: int
    action: Literal["keep", "contradicted", "expected"]
    dictated_finding: str = ""


def _unstring(v):
    """Qwen sometimes returns a nested list as a JSON string inside the tool call."""
    return json.loads(v) if isinstance(v, str) else v


class QwenDecisions(BaseModel):
    negatives: List[NegativeDecision]
    affected_normals: List[int]
    applicable_measurements: List[int]
    @field_validator("negatives", "affected_normals", "applicable_measurements", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return _unstring(v)


class Split(BaseModel):
    negatives: List[List[str]]
    @field_validator("negatives", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return _unstring(v)


class RecDecision(BaseModel):
    index: int
    decision: Literal["include", "exclude", "optional"]
    exclude_reason: Optional[Literal["condition_unmet", "routine_workup", "not_radiology", "duplicate"]] = None
    reason: str = ""


class ImpressionPlan(BaseModel):
    recommendations: List[RecDecision]
    impression: List[int]
    optional_impression: List[int] = []
    findings_only: List[int] = []
    @field_validator("recommendations", "impression", "optional_impression", "findings_only", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return _unstring(v)


# Clinical judgement about what the impression carries is Qwen's (reasoning low); Jev keeps to
# whether a recommendation's condition is met; code routes include / exclude / optional.
PLAN_SYS = """You plan the impression of a radiology report before it is written. You see the scan type, the clinical question, the dictated findings (numbered) and candidate recommendations (numbered). Return JSON only.

recommendations — decide every candidate by its kind; a candidate whose condition the dictated findings do not meet is always exclude.
- REFERRAL and MDT: routing a finding to the team that must act on it, at the urgency the findings warrant, is the radiologist's job even when the diagnosis is already made. include when the condition is met; exclude only when an included candidate already covers it.
- IMAGING and TISSUE: include only when it answers a question this study raises but cannot answer itself, and the answer would change management. exclude routine workup of a diagnosis this study has already made — looking for its cause, source or spread when the receiving team manages it the same way regardless.
- CORRELATION: include only retrieving prior imaging to compare against; exclude laboratory tests, clinical monitoring, treatment decisions and bare clinical correlation.
Use optional only when a reasonable consultant could go either way on this case. For every exclude, set exclude_reason: condition_unmet (the findings do not meet its condition), routine_workup (routine workup of a diagnosis this study has already made), not_radiology (laboratory tests, monitoring, treatment, bare correlation) or duplicate. Give a one-line reason.

impression — the numbers of the findings the impression must carry: the finding(s) that answer the clinical question, findings that change management or urgency, and, only when no dictated positive finding answers the clinical question, the one negative that does. Never carry more than one negative.
optional_impression — findings with a management consequence that a reasonable consultant could either carry or leave in FINDINGS. Never use it for normal structures, devices or negatives.
findings_only — findings that stay in FINDINGS: incidental or background findings needing no action, devices and procedure notes, normal structures the question did not ask about.
A finding may be in none of the lists when either placement is acceptable. Never place a number in two lists."""

PLAN_TIMEOUT_S = 10.0
MAX_OPTIONS = 3
_BAR_KINDS = ("IMAGING:", "TISSUE:")


QWEN_SYS = (
    "You check a radiology skill sheet against the radiologist's dictated findings for one case. Silence in the "
    "dictation never makes a finding present.\n"
    "NEGATIVES: for each numbered negative return 'contradicted' if the dictation reports it as present or reports a "
    "finding of the same kind in the same place; 'expected' if a dictated finding would normally and predictably "
    "cause what it denies (not merely make it possible); otherwise 'keep'. For contradicted and expected, quote the "
    "dictated finding responsible.\n"
    "NORMAL LINES: list the numbers of normal-study statements that a dictated finding contradicts or acts on.\n"
    "MEASUREMENTS: list the numbers of measurement conventions whose finding is present in the dictation.")


def _words(s: str) -> set:
    return set(re.findall(r"[\w*'-]+", s.lower()))


async def _split_bundled(negs: List[str]) -> List[List[str]]:
    """Split bundled negatives into single claims; keep the original where the split adds words."""
    bundled = [i for i, n in enumerate(negs) if _is_bundled(n)]
    if not bundled:
        return [[n] for n in negs]
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=Split,
        system_prompt=("Rewrite each radiology negative statement as a list of single-claim sentences, one claim each, "
                       "keeping the wording and any shared qualifier attached to every claim it applies to. Return one "
                       "list per input statement, in order."),
        user_prompt="\n".join(f"{k + 1}. {negs[i]}" for k, i in enumerate(bundled)), api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "none"}), QWEN_TIMEOUT_S)
    out = [[n] for n in negs]
    for i, parts in zip(bundled, r.output.negatives):
        if parts and all(_words(p) <= _words(negs[i]) for p in parts):
            out[i] = [p.strip().rstrip(".") for p in parts]
    return out


async def _jev(state: str, questions: dict) -> dict:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    async with httpx.AsyncClient() as client:
        r = await client.post(JEV_URL, headers={"Authorization": f"Bearer {key}"},
                              json={"model": JEV_MODEL, "state": state, "questions": questions}, timeout=JEV_TIMEOUT_S)
    r.raise_for_status()
    return r.json().get("answers") or r.json()


async def _qwen(state: str, negs: List[str], normals: List[str], measurements: List[str]) -> QwenDecisions:
    def block(title, items):
        return f"{title}:\n" + ("\n".join(f"{k}. {t}" for k, t in enumerate(items)) or "(none)")
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=QwenDecisions, system_prompt=QWEN_SYS,
        user_prompt=f"{state}\n\n{block('NEGATIVES', negs)}\n\n{block('NORMAL LINES', normals)}\n\n{block('MEASUREMENTS', measurements)}",
        api_key="", model_settings={"temperature": 0, "max_tokens": 4000, "reasoning_effort": "none"}), QWEN_TIMEOUT_S)
    return r.output


class FallbackItem(BaseModel):
    index: int
    covered: bool
    negatives: List[str] = []


class FallbackNegatives(BaseModel):
    items: List[FallbackItem]
    @field_validator("items", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return _unstring(v)


# A dictated finding the sheet did not anticipate has no If-present key. Qwen judges coverage
# (Jev scores keys, not dictated items) and writes negatives for the uncovered; written at
# reasoning off, these are only ever offered, never stated.
FALLBACK_SYS = (
    "You check whether each dictated radiology finding is covered by a prepared list of finding types, and write "
    "pertinent negatives only for findings that are not. For each numbered dictated finding return covered=true "
    "when one of the FINDING TYPES describes the same kind of finding in the same place; otherwise covered=false "
    "and up to three negatives a consultant states once that finding is reported: the absence of each extension, "
    "spread or complication this technique shows and the next management step depends on. One finding per "
    "negative, no 'or', no list, final report form. Never deny anything dictated or its expected consequence.")
FALLBACK_TIMEOUT_S = 6.0


async def _fallback(state: str, items: List[str], keys: List[str]) -> FallbackNegatives:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=FallbackNegatives, system_prompt=FALLBACK_SYS,
        user_prompt=(f"{state}\n\nNUMBERED DICTATED FINDINGS:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items))
                     + "\n\nFINDING TYPES:\n" + ("\n".join(f"- {k}" for k in keys) or "(none)")),
        api_key="", model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "none"}), FALLBACK_TIMEOUT_S)
    return r.output


def split_findings(findings: str) -> List[str]:
    """Dictated findings as numbered items: bullets, lines and sentences."""
    parts = []
    for line in re.split(r"\n+|\s/\s|(?:^|\s)-\s(?=[A-Za-z0-9])", findings):
        line = line.strip(" -\t")
        for s in re.split(r"(?<=[a-z0-9%)])\.\s+(?=[A-Z0-9])", line):
            s = s.strip().rstrip(".")
            if len(s) > 3:
                parts.append(s)
    return parts


async def _plan(scan_type: str, clinical_history: str, items: List[str], recs: List[str],
                inclusion_logic: str = "") -> ImpressionPlan:
    user = (f"SCAN TYPE: {scan_type}\nCLINICAL QUESTION (context only): {clinical_history or '(not given)'}\n\n"
            "DICTATED FINDINGS:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items))
            + "\n\nCANDIDATE RECOMMENDATIONS:\n" + ("\n".join(f"{i}. {t}" for i, t in enumerate(recs)) or "(none)"))
    if inclusion_logic:
        user += "\n\nTHE REPORTER'S OWN INCLUSION PREFERENCES (follow them where they apply):\n" + inclusion_logic
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=ImpressionPlan, system_prompt=PLAN_SYS,
        user_prompt=user, api_key="",
        model_settings={"temperature": 0, "max_tokens": 8000, "reasoning_effort": "low"}), PLAN_TIMEOUT_S)
    return r.output


class _OptionSentences(BaseModel):
    sentences: List[str]

    @field_validator("sentences", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return json.loads(v) if isinstance(v, str) else v


OPTION_SYS = ("Write one sentence for the IMPRESSION of a radiology report for each numbered item, in order. "
              "A 'recommendation' item becomes a recommendation sentence naming the test or service and, where "
              "the item gives one, its urgency; drop any condition in brackets once it is met. An 'impression' "
              "item becomes a compressed statement of that dictated finding. Use only facts in the item and the "
              "findings. British English, consultant voice, no preamble. Return JSON {\"sentences\": [...]}.")


async def write_options(options: List[dict], findings: str, scan_type: str, *, model: str,
                        runner: Callable[..., Awaitable[Any]],
                        style: str = "", impression_section: str = "IMPRESSION") -> List[dict]:
    """Reporter-choice items. Impression and recommendation items get one sentence each from a
    writer call beside the generator; finding-linked negatives are already in report form and
    pass through. On a writer failure only the written items are lost. `runner` is the caller's
    _run_agent_with_model (so each pathway's tests patch their own module); `style` carries a
    template sheet's impression examples and terminology."""
    direct = [o for o in options if o["kind"] == "finding_negative"]
    to_write = [o for o in options if o["kind"] != "finding_negative"]
    passed = [{"id": f"fn{i}", "kind": o["kind"], "section": o.get("section", "FINDINGS"),
               "sentence": o["text"][:1].upper() + o["text"][1:].rstrip(".") + ".", "reason": o.get("reason", ""), "source": o["text"],
               "finding": o.get("finding", "")}
              for i, o in enumerate(direct)]
    if not to_write:
        return passed
    try:
        items = "\n".join(f"{i}. [{o['kind']}] {o['text']}" for i, o in enumerate(to_write))
        user = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}\n\nITEMS:\n{items}"
        if style:
            user += f"\n\nWRITE IN THIS REPORTER'S STYLE:\n{style}"
        r = await asyncio.wait_for(runner(
            model_name=model, output_type=_OptionSentences, system_prompt=OPTION_SYS, user_prompt=user,
            api_key="", model_settings={"temperature": 0.2, "max_tokens": 2000, "reasoning_effort": "none"}), 10.0)
        sentences = r.output.sentences
    except Exception as e:
        logger.warning("option sentences failed (%s: %s); no written options offered", type(e).__name__, str(e)[:200])
        return passed
    written = [{"id": f"opt{i}", "kind": o["kind"], "section": impression_section, "sentence": s.strip(),
                "reason": o.get("reason", ""), "source": o["text"]}
               for i, (o, s) in enumerate(zip(to_write, sentences)) if s and s.strip()]
    return written + passed


@dataclass
class Brief:
    text: str
    decisions: dict
    reconcile_ms: int
