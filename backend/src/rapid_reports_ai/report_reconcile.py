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
PRESENT = 0.5   # the one Jev yes cut-off: present, condition met / unmet, statement affected
PRESENT_LOW = PRESENT
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


def route_differential(present: float, visible: str) -> str:
    """Policy 1 for a differential branch: "present" when Jev finds a dictated finding showing it;
    otherwise silence closes it ("closed", removed) only when this study would show it (visible "yes");
    a branch not visible on this technique ("no") or imaging-silent ("silent") stays "open"."""
    if present >= PRESENT:
        return "present"
    return "closed" if visible == "yes" else "open"


def route_recommendation(unmet: float, decision: Optional["RecDecision"], *, tag: str = "",
                         room: bool = True) -> str:
    """A candidate recommendation: Jev's unmet condition removes it; of the rest, the impression plan
    includes (or, with no plan decision, keeps), offers ("optional", while there is room for another
    option) or excludes. A removed IMAGING / TISSUE candidate the plan excluded as routine workup of a
    diagnosis already made is "do_not_recommend": named as barred, since the generator refills such a
    test from its priors and a prohibition holds."""
    if unmet >= PRESENT:
        action = "removed"
    elif decision is None or decision.decision == "include":
        action = "keep"
    elif decision.decision == "optional" and room:
        action = "optional"
    else:
        action = "removed"
    if action == "removed" and decision and decision.exclude_reason == "routine_workup" \
            and f"{tag.strip().rstrip(':').strip().upper()}:" in _BAR_KINDS:
        return "do_not_recommend"
    return action


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
        if _split_keeps_claims(negs[i], parts):
            out[i] = [p.strip().rstrip(".") for p in parts]
    return out


_NEGATION = frozenset({"no", "not", "without", "nil", "none", "never"})


def _split_keeps_claims(original: str, parts: List[str]) -> bool:
    """A split is used only when every part is a non-empty claim made of the original's words and keeps
    a negation word the original had: "No A or B" -> "No A", "B" would turn a negative into an assertion."""
    neg = _words(original) & _NEGATION
    return bool(parts) and all(
        p and p.strip(" .") and _words(p) <= _words(original) and (not neg or _words(p) & neg) for p in parts)


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


_CLAIM_NEG = re.compile(r"^(?:there\s+(?:is|are)\s+no|no|without)\s+", re.I)
_CLAIM_TAIL = re.compile(r"(?:\s+(?:is|are|was|were))?(?:\s+(?:identified|seen|present|demonstrated|noted|evident))?$")


def _claim_parts(negative: str) -> List[str]:
    """Comparison keys of a negative's single claims: 'No A, B or C is identified.' -> ['a', 'b', 'c']. The
    split on ',' / ' or ' is for comparison only (a bundled option is never rewritten)."""
    body = re.sub(r"\s+", " ", negative.strip().lower()).rstrip(" .;")
    m = _CLAIM_NEG.match(body)
    if not m:
        return []
    body = _CLAIM_TAIL.sub("", body[m.end():])
    parts = re.split(r",\s*(?:or\s+|and\s+)?(?:no\s+)?|\s+or\s+(?:no\s+)?|\s+and\s+no\s+", body)
    return [_CLAIM_TAIL.sub("", p.strip()) for p in parts if p.strip()]


def _dictated_negative_claims(findings: str) -> set:
    """Claims the dictation states absent. Sentences split on '.', ';', newlines and ' - ' whatever the case;
    within a sentence every comma part from the first negated one on is a claim ('no nodes, aorta normal')."""
    out: set = set()
    for sent in re.split(r"[.;\n]+|\s-\s", findings or ""):
        negated = False
        for frag in re.split(r",\s*", sent):
            frag = frag.strip()
            if _CLAIM_NEG.match(frag):
                negated = True
                out.update(_claim_parts(frag))
            elif negated and frag:
                out.update(_claim_parts("No " + frag))
    return out


def dedupe_options(options: List[dict], stated_negatives: List[str], findings: str) -> tuple:
    """Finding-linked option negatives (kind 'finding_negative', incl. the fallback's) without the ones that
    restate a negative the brief already states (KEEP) or a negative the dictation states. An option is dropped
    when any of its claims, compared part by part, matches. Returns (kept options, dropped option texts)."""
    taken = {p for n in stated_negatives for p in _claim_parts(n)} | _dictated_negative_claims(findings)
    kept, dropped = [], []
    for o in options:
        if o.get("kind") == "finding_negative" and taken & set(_claim_parts(o.get("text", ""))):
            dropped.append(o.get("text", ""))
        else:
            kept.append(o)
    return kept, dropped


# Words whose full stop never ends a dictated sentence. "no." is only an abbreviation before a
# number or "of" ("no. 3 node", "no. of lesions"); "ascites: no. liver normal" is two findings.
_ABBREVIATIONS = {"e.g", "eg", "i.e", "ie", "vs", "approx", "cf", "dr", "mr", "mrs", "ms", "prof", "st", "fig", "ca", "c.f"}
_NO_ABBREVIATION = re.compile(r"(?i)\s*(?:\d|of\b)")


def _sentences(line: str) -> List[str]:
    """Split on a full stop followed by whitespace, whatever the case of the next word: radiologists
    dictate in lower case. Decimals ("3.5 cm") have no space after the stop and never split;
    abbreviations and initials ("J. Bloggs") do not end a sentence."""
    out, start = [], 0
    for m in re.finditer(r"\.\s+", line):
        word = re.search(r"[\w.]*$", line[start:m.start()]).group(0).lower().strip(".")
        if word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
            continue
        if word == "no" and _NO_ABBREVIATION.match(line, m.end()):
            continue
        out.append(line[start:m.start()])
        start = m.end()
    out.append(line[start:])
    return out


def split_findings(findings: str) -> List[str]:
    """Dictated findings as numbered items: bullets, lines and sentences."""
    parts = []
    for line in re.split(r"\n+|\s/\s|(?:^|\s)-\s(?=[A-Za-z0-9])", findings):
        line = line.strip(" -\t")
        for s in _sentences(line):
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
                        style: str = "", impression_section: str = "IMPRESSION",
                        require_service: bool = False) -> List[dict]:
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
    if require_service:  # templated pathway: a recommendation sentence must name what it recommends
        bad = [w for w in written if w["kind"] == "recommendation" and not names_service(w["sentence"], w["source"])]
        for w in bad:
            logger.warning("option writer: recommendation %r written as %r; dropped", w["source"], w["sentence"][:120])
        written = [w for w in written if w not in bad]
    return written + passed


_GENERIC_REC = frozenset(("referral", "refer", "review", "urgent", "urgently", "emergency", "routine", "soon",
                          "recommended", "recommend", "suggested", "consider", "team", "service", "the", "a", "an",
                          "to", "of", "for", "and", "with", "is", "be", "further", "clinical", "acute"))


def names_service(sentence: str, recommendation: str) -> bool:
    """The written sentence shares a service / test word (4-letter stem) with the recommendation text (its 'TAG:'
    prefix and generic referral and urgency words ignored). Without such a word to check, it passes."""
    body = re.sub(r"^[A-Z]+:\s*", "", recommendation)
    stems = lambda t: {w[:4] for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in _GENERIC_REC and len(w) > 1}  # noqa: E731
    want = stems(body)
    return not want or bool(want & stems(sentence))


Q_ALREADY = "The report already states or implies this, in any wording: "
_IMPRESSION_KINDS = ("impression", "recommendation")


def gate_questions(options: List[dict]) -> dict:
    """The uniqueness questions, by state: {"report": {...}, "impression": {...}}, keys u<option index>. A
    finding_negative is asked of the whole report (so its questions can ride on the post-generation check's
    report-state request); an impression or recommendation item of the conclusion only (a finding may sit in
    the findings yet stay optional for the conclusion)."""
    qs: dict = {"report": {}, "impression": {}}
    for i, o in enumerate(options):
        text = (o.get("sentence") or o.get("text") or "").strip()
        if text:
            qs["impression" if o.get("kind") in _IMPRESSION_KINDS else "report"][f"u{i}"] = {
                "type": "noul", "instructions": Q_ALREADY + text}
    return qs


async def gate_scores(state: str, qs: dict) -> dict:
    """{key: yes score} for one state; {} when nothing is asked or Jev fails (fail-open)."""
    if not qs:
        return {}
    try:
        answers = await asyncio.wait_for(_jev(state, qs), JEV_TIMEOUT_S)
        return {k: float(answers[k]["noul"]) for k in qs}
    except Exception as e:  # consistency is guaranteed upstream; uniqueness is best effort
        logger.warning("option gate: Jev failed (%s: %s); options kept", type(e).__name__, str(e)[:200])
        return {}


def gate_apply(options: List[dict], scores: dict) -> tuple:
    """(kept, dropped): an option whose yes score is >= PRESENT is dropped with outcome 'already_in_report';
    an option without a score (not asked, or Jev failed) is kept."""
    kept, dropped = [], []
    for i, o in enumerate(options):
        sc = scores.get(f"u{i}")
        if sc is not None and sc >= PRESENT:
            dropped.append({**o, "outcome": "already_in_report", "score": round(sc, 3)})
        else:
            kept.append(o)
    return kept, dropped


async def gate_options(options: List[dict], report_text: str, impression_text: str) -> tuple:
    """Uniqueness gate on its own (both scopes asked here, in parallel). A caller that runs the
    post-generation check passes gate_questions(...)["report"] to it as extra_report_qs instead, asks only
    the impression scope with gate_scores, and merges both into gate_apply."""
    qs = gate_questions(options)
    rep, imp = await asyncio.gather(gate_scores(f"REPORT:\n{report_text}", qs["report"]),
                                    gate_scores(f"CONCLUSION:\n{impression_text}", qs["impression"]))
    return gate_apply(options, {**rep, **imp})


@dataclass
class Brief:
    text: str
    decisions: dict
    reconcile_ms: int
