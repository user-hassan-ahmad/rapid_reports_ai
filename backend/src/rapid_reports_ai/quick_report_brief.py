"""Compiled brief: the analyser's skill sheet, reconciled with this dictation, reduced to what applies.

The sheet is written from scan type and clinical history before anything is found. The brief is
what the generator reads instead: the same markdown shape, with each clinical item checked
against the dictated findings and labelled or removed.

    parse  -> the sheet's sections and bullets (code)
    reconcile -> one Jev call and one Qwen reasoning-off call, in parallel (~0.3-0.7 s)
    compile   -> the brief text, plus a log of every decision (code)

Who decides what (docs/superpowers/research/2026-09-29-sheet-reconciliation-bakeoff.md):
  Jev   normal lines (affected), differentials (present), recommendations (condition unmet),
        style exemplars (match a dictated finding), impression variant (choice)
  Qwen  mandatory negatives (contradicted / expected consequence / keep, with the dictated
        finding), normal lines (second opinion), measurement conventions (finding dictated)
  code  policy 1 for differentials (not present AND visible on this technique AND not
        imaging-silent -> removed); a normal line either flags is listed as "do not assert",
        never deleted (a deleted line leaves a gap the generator refills from its priors;
        an explicit prohibition holds); bundled negatives are split by Qwen with a check
        that every word comes from the source.

Removed outright (lean): Conditional Suppression Rules (generic; replaced by per-item labels),
Out of scope, Modality non-assessables, In-scope companions, Out-of-scope suppressed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Literal, Optional

import httpx
from pydantic import BaseModel, field_validator

from .enhancement_utils import _run_agent_with_model

logger = logging.getLogger(__name__)

JEV_URL = "https://openrouter.ai/api/v1/systemone"
JEV_MODEL = "typesafe/jev-1.13"
QWEN = "qwen-3.8-27b"
JEV_TIMEOUT_S = 6.0
QWEN_TIMEOUT_S = 10.0

DROP_TOP_BULLETS = {"Out of scope", "Modality non-assessables", "In-scope companions", "Out-of-scope suppressed",
                    "If present"}
DROP_SECTIONS = {"Conditional Suppression Rules"}

# ── parse ────────────────────────────────────────────────────────────────────

_TOP = re.compile(r"^- \*\*([^*]+?):?\*\*:?\s*(.*)$")


@dataclass
class Bullet:
    label: str          # "" for an unlabelled bullet
    lines: List[str]    # the bullet line and its indented children, verbatim


@dataclass
class Section:
    heading: str        # "" for text before the first "## "
    preamble: List[str] = field(default_factory=list)   # non-bullet lines before the first bullet
    bullets: List[Bullet] = field(default_factory=list)


def parse_sheet(sheet: str) -> List[Section]:
    sections: List[Section] = [Section("")]
    for line in sheet.splitlines():
        if line.startswith("## "):
            sections.append(Section(line[3:].strip()))
            continue
        sec = sections[-1]
        if line.startswith("- "):
            m = _TOP.match(line)
            sec.bullets.append(Bullet(m.group(1).strip() if m else "", [line]))
        elif sec.bullets and (line.startswith((" ", "\t")) or not line.strip()):
            sec.bullets[-1].lines.append(line)
        elif sec.bullets:
            sec.bullets[-1].lines.append(line)
        else:
            sec.preamble.append(line)
    return sections


def render(sections: List[Section]) -> str:
    out: List[str] = []
    for s in sections:
        if s.heading:
            out.append(f"## {s.heading}")
        out.extend(s.preamble)
        for b in s.bullets:
            out.extend(b.lines)
        if s.heading:
            out.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def _section(sections: List[Section], name: str) -> Optional[Section]:
    return next((s for s in sections if s.heading == name), None)


def _bullet(section: Optional[Section], label: str) -> Optional[Bullet]:
    return next((b for b in section.bullets if b.label.startswith(label)), None) if section else None


# ── items ────────────────────────────────────────────────────────────────────

def _quoted(text: str) -> List[str]:
    return re.findall(r'"([^"]+)"', text)


def _is_bundled(neg: str) -> bool:
    return bool(re.search(r",|\bor\b", re.split(r"\s+to suggest\s", neg)[0]))


_DIFF = re.compile(r"^\s+- (?!\*\*)(.+)$")


def differential_lines(sections: List[Section]) -> List[str]:
    b = _bullet(_section(sections, "Clinical Lane"), "Differentials in scope")
    if not b:
        return []
    return [m.group(1) for line in b.lines[1:] if (m := _DIFF.match(line)) and len(m.group(1)) > 3]


def _normal_sentences(bullet: Optional[Bullet]) -> List[str]:
    if not bullet:
        return []
    text = " ".join(_quoted(" ".join(bullet.lines))) or re.sub(r"^- \*\*[^*]+\*\*:?\s*", "", " ".join(bullet.lines))
    return [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", text) if len(s.strip()) > 3]


def _impression_variants(section: Optional[Section]) -> List[Bullet]:
    if not section:
        return []
    return [b for b in section.bullets if re.match(r"(Normal|Abnormal|Complicated)\b.*exemplar", b.label)]


def _recommendations(section: Optional[Section]) -> List[str]:
    b = _bullet(section, "Recommendation scope")
    if not b:
        return []
    out = []
    for line in b.lines[1:]:
        m = re.match(r"^\s+- ([A-Z]+):\s*(.*)$", line)
        if m:
            out.extend(f"{m.group(1)}: {p.strip()}" for p in re.split(r";\s*", m.group(2)) if len(p.strip()) > 3)
    return out


# Policy 1 for dictated findings: a finding Jev finds reported brings the negatives the analyser
# listed for it. Cut-offs on Jev's score; PRESENT_HIGH sits in the measured gap between clear
# (0.86-0.99) and hedged (<=0.72) reports (ledger L-45).
PRESENT_LOW = 0.5
PRESENT_HIGH = 0.8
MAX_FINDING_OPTIONS = 4
_CONFIRMED = re.compile(r'^\s+-\s+(.+?)\s*(?:→|->)\s*"([^"]+)"\s*(?:\((core|contextual)\))?')
# The analyser also nests: the key on its own line, its negatives as sub-bullets.
_CONFIRMED_BRANCH = re.compile(r'^\s+-\s+([^"]+?)\s*(?:→|->)\s*$')
_CONFIRMED_NEG = re.compile(r'^\s+-\s+"([^"]+)"\s*(?:\((core|contextual)\))?')


HEDGE = "(?, possible, query, cannot exclude, versus, no definite, equivocal)"


# If-present finding presence (Jev wording v2, group B, L-49): a graded score read as level / 3, so
# absent 0, unmentioned 0.33, possible 0.67, present 1.0 against the route_finding cut-offs.
def q_finding(key: str) -> dict:
    return {"type": "score",
            "instructions": "How definitely do the dictated findings report this imaging finding as present? Finding: " + key,
            "criteria": ["Stated as absent or normal",
                         "Not mentioned, or only a different finding is reported",
                         "Raised only as a possibility " + HEDGE,
                         "Reported as present, in any wording or size"]}


def finding_presence(a: dict) -> float:
    return float(a["score"]) / 3


@dataclass
class FindingNegative:
    key: str
    text: str
    tag: str   # "core" | "contextual"


def _tag(line: str) -> str:
    """The tag after the quoted negative, however the analyser annotates it: '(core)',
    '(core — resectability)', '(peritonitis) (core)'. Unreadable means contextual (offered)."""
    m = re.search(r"\b(core|contextual)\b", line.rsplit('"', 1)[-1])
    return m.group(1) if m else "contextual"


def parse_if_present(lines: List[str]) -> List[FindingNegative]:
    """The If-present bullet as (finding key, negative, tag), one-line or nested shape."""
    out: List[FindingNegative] = []
    key = None
    for line in lines[1:]:
        if m := _CONFIRMED.match(line):
            out.append(FindingNegative(m.group(1).strip(), m.group(2).strip().rstrip("."), _tag(line)))
        elif m := _CONFIRMED_BRANCH.match(line):
            key = m.group(1).strip()
        elif (m := _CONFIRMED_NEG.match(line)) and key:
            out.append(FindingNegative(key, m.group(1).strip().rstrip("."), _tag(line)))
    return out


def distinct_keys(cands: List[FindingNegative]) -> List[str]:
    return list(dict.fromkeys(c.key for c in cands))


def route_finding(label: str, present: float, tag: str) -> str:
    """Rule C: stated only when the finding is clearly reported and the negative is core."""
    if present < PRESENT_LOW or label == "contradicted":
        return "dropped"
    if label == "expected":
        return "do_not_assert"
    if present >= PRESENT_HIGH and tag == "core":
        return "stated"
    return "offered"


# Offered negatives never repeat a negative the brief states or the dictation already makes.
# Comparison only (nothing is rewritten): lower-cased content words of each " or "/comma part,
# negation and filler removed. Two parts match when their words are equal, or when one holds
# all of the other's and the smaller has at least two words ("no free gas" covers "No free
# intraperitoneal gas"; a one-word "no change" never swallows "No acute ischaemic change").
_NEG_FILLER = {"no", "not", "without", "nor", "any", "is", "are", "was", "were", "be", "there", "the", "a", "an",
               "of", "seen", "identified", "evident", "demonstrated", "present", "noted", "visible", "detected",
               "evidence", "to", "suggest", "and"}
_NEG_START = re.compile(r"(?i)\b(?:no|not|without|nor)\b")


def _claim_parts(text: str) -> List[frozenset]:
    parts = re.split(r",|;|\s+or\s+|\s+and\s+", text.lower())
    out = []
    for p in parts:
        words = frozenset(w for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", p) if w not in _NEG_FILLER)
        if words:
            out.append(words)
    return out


def _part_matches(a: frozenset, b: frozenset) -> bool:
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return a == b or (len(small) >= 2 and small <= big)


def dictated_negatives(items: List[str]) -> List[str]:
    """Negated clauses in the dictation: "no nodes, aorta normal" -> "no nodes"."""
    return [c.strip() for t in items for c in re.split(r",|;", t) if _NEG_START.search(c)]


def duplicates_negative(option: str, negatives: List[str]) -> bool:
    """True when every part of the offered negative is already said by one of the negatives."""
    have = [p for n in negatives for p in _claim_parts(n)]
    parts = _claim_parts(option)
    return bool(parts) and all(any(_part_matches(p, h) for h in have) for p in parts)


_MEASUREMENT =re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|°|(?:mm|cm|ml|mL|cc|HU|mmHg|m/s|degrees?)(?![A-Za-z]))")


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


class IncompleteNegativeDecisions(RuntimeError):
    """The classifier did not answer every negative exactly once."""


async def _qwen_complete(state: str, negs: List[str], normals: List[str], measurements: List[str]) -> QwenDecisions:
    """A negative without a decision would default to KEEP, so a contradicted negative could be
    stated. The answer must cover indices 0..n-1 exactly once (no missing, extra, duplicate or
    off-by-one); one retry, then raise so the report is written from the raw sheet."""
    expected = list(range(len(negs)))
    for attempt in (1, 2):
        qw = await _qwen(state, negs, normals, measurements)
        got = sorted(d.index for d in qw.negatives)
        if got == expected:
            return qw
        logger.warning("negative classifier answer incomplete (attempt %d/2): sent %d negatives, got indices %s",
                       attempt, len(negs), got)
    raise IncompleteNegativeDecisions(f"sent {len(negs)} negatives, got indices {got}")


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


async def _plan(scan_type: str, clinical_history: str, items: List[str], recs: List[str]) -> ImpressionPlan:
    user = (f"SCAN TYPE: {scan_type}\nCLINICAL QUESTION (context only): {clinical_history or '(not given)'}\n\n"
            "DICTATED FINDINGS:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items))
            + "\n\nCANDIDATE RECOMMENDATIONS:\n" + ("\n".join(f"{i}. {t}" for i, t in enumerate(recs)) or "(none)"))
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=ImpressionPlan, system_prompt=PLAN_SYS,
        user_prompt=user, api_key="",
        model_settings={"temperature": 0, "max_tokens": 8000, "reasoning_effort": "low"}), PLAN_TIMEOUT_S)
    return r.output


# ── compile ──────────────────────────────────────────────────────────────────

@dataclass
class Brief:
    text: str
    decisions: dict
    reconcile_ms: int


async def compile_brief(sheet: str, scan_type: str, findings: str, clinical_history: str = "") -> Brief:
    t0 = time.time()
    secs = parse_sheet(sheet)
    lane, struct = _section(secs, "Clinical Lane"), _section(secs, "Structural Pattern")
    matrix, style = _section(secs, "Companion Matrix"), _section(secs, "Style Exemplars")
    meas, imp, ctx = _section(secs, "Measurement Conventions"), _section(secs, "Impression Exemplars"), _section(secs, "Scan Context")

    neg_bullet = _bullet(matrix, "Mandatory negatives")
    raw_negs = [n.strip().rstrip(".") for n in _quoted(" ".join(neg_bullet.lines))] if neg_bullet else []
    targets = {n: (re.search(r'"' + re.escape(n) + r'\.?"\s*\(([^)]*)\)', " ".join(neg_bullet.lines)) or [None, ""])[1]
               for n in raw_negs} if neg_bullet else {}
    fb = _bullet(matrix, "If present")
    raw_cands = parse_if_present(fb.lines) if fb else []
    # One split call covers mandatory and finding-linked negatives: the analyser bundles both.
    split = await _split_bundled(raw_negs + [c.text for c in raw_cands])
    negs = [(c, targets.get(parent, "")) for parent, parts in zip(raw_negs, split) for c in parts]
    cands = [FindingNegative(c.key, part, c.tag) for c, parts in zip(raw_cands, split[len(raw_negs):]) for part in parts]
    normal_bullet = _bullet(struct, "Normal-study path")
    # A normal line that states a measurement asserts a value nobody dictated whenever the
    # dictation is silent about it, so it never reaches the generator.
    measured = [t for t in _normal_sentences(normal_bullet) if _MEASUREMENT.search(t)]
    normals = [t for t in _normal_sentences(normal_bullet) if not _MEASUREMENT.search(t)]
    diffs = differential_lines(secs)
    keys = distinct_keys(cands)
    recs = _recommendations(imp)
    styles = style.bullets if style else []
    variants = _impression_variants(imp)
    measurements = meas.bullets if meas else []

    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    qs = {}
    qs.update({f"n{k}": {"type": "noul", "instructions": Q_AFFECTED + t} for k, t in enumerate(normals)})
    qs.update({f"d{k}": {"type": "noul", "instructions": Q_PRESENT + t} for k, t in enumerate(diffs)})
    qs.update({f"r{k}": {"type": "noul", "instructions": Q_REC_UNMET + t} for k, t in enumerate(recs)})
    qs.update({f"f{i}": q_finding(k) for i, k in enumerate(keys)})
    qs.update({f"s{k}": {"type": "noul", "instructions": Q_STYLE_MATCH + " ".join(b.lines)} for k, b in enumerate(styles)})
    if len(variants) > 1:
        qs["imp"] = {"type": "choice", "instructions": "Which impression exemplar best matches the shape of this case's findings (severity, number of findings, complications)?",
                     "criteria": {f"v{k}": " ".join(b.lines)[:400] for k, b in enumerate(variants)}}
    items = split_findings(findings)

    async def plan_or_none():
        try:
            return await _plan(scan_type, clinical_history, items, recs)
        except Exception as e:  # the brief still compiles; recommendations fall back to Jev alone
            logger.warning("impression plan failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None
    async def fallback_or_none():
        try:
            # Only sheets written with the finding_negatives directive carry an If-present list;
            # without one the brief behaves exactly as before (no extra call, no options).
            return await _fallback(state, items, keys) if items and fb else None
        except Exception as e:  # the brief still compiles; unanticipated findings just get no options
            logger.warning("finding-negatives fallback failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None
    jev, qw, plan, fb_out = await asyncio.gather(
        _jev(state, qs) if qs else asyncio.sleep(0, {}),
        _qwen_complete(state, [n for n, _ in negs] + [c.text for c in cands], normals, [" ".join(b.lines) for b in measurements]),
        plan_or_none(), fallback_or_none())
    score = lambda k: float(jev[k]["noul"])

    decisions: dict = {"negatives": [], "normals": [], "differentials": [], "recommendations": [], "style": [], "measurements": [],
                       "impression_variant": None, "impression_plan": None, "options": [],
                       "finding_negatives": []}

    # Mandatory negatives: one line each, with its action and the dictated finding.
    qneg = {d.index: d for d in qw.negatives}
    neg_lines = [neg_bullet.lines[0].split("**Mandatory negatives:**")[0] + "**Mandatory negatives:** (reconciled with this dictation; one finding each)"] if neg_bullet else []
    for k, (text, target) in enumerate(negs):
        d = qneg.get(k)
        action = d.action if d else "keep"
        why = f" ({target})" if target else ""
        if action == "contradicted":
            neg_lines.append(f'  - OMIT: "{text}" — the dictation reports: {d.dictated_finding}')
        elif action == "expected":
            neg_lines.append(f'  - DO NOT ASSERT: "{text}" — expected consequence of: {d.dictated_finding}')
        else:
            neg_lines.append(f'  - KEEP: "{text}"{why}')
        decisions["negatives"].append({"text": text, "action": action, "dictated_finding": d.dictated_finding if d else "",
                                       "source": "sheet"})

    # Finding-linked negatives (policy 1): stated as KEEP, labelled DO NOT ASSERT, or offered.
    stated: List[str] = []
    n_offered = 0
    pending: list = []
    handled = {n for n, _ in negs}   # a negative listed under two keys, or already mandatory, is routed once
    for j, c in enumerate(cands):
        if c.text in handled:
            continue
        handled.add(c.text)
        d = qneg.get(len(negs) + j)
        label = d.action if d else "keep"
        p = finding_presence(jev[f"f{keys.index(c.key)}"])
        outcome = route_finding(label, p, c.tag)
        record = {"finding": c.key, "text": c.text, "tag": c.tag, "qwen": label, "present": round(p, 3), "outcome": outcome}
        decisions["finding_negatives"].append(record)
        if outcome == "offered":   # decided once every stated negative is known
            pending.append((c, p, record))
        if outcome == "stated":
            stated.append(c.text)
            neg_lines.append(f'  - KEEP: "{c.text}" (finding: {c.key})')
            decisions["negatives"].append({"text": c.text, "action": "keep", "dictated_finding": "",
                                           "source": f"finding:{c.key}"})
        elif outcome == "do_not_assert":
            neg_lines.append(f'  - DO NOT ASSERT: "{c.text}" — expected consequence of: {d.dictated_finding}')
    # An offered negative the brief already states (KEEP) or the dictation already makes is a
    # duplicate, never an option.
    said = [n["text"] for n in decisions["negatives"] if n["action"] == "keep"] + dictated_negatives(items)
    for c, p, record in pending:
        if duplicates_negative(c.text, said):
            record["outcome"] = "duplicate"
        elif n_offered >= MAX_FINDING_OPTIONS:
            record["outcome"] = "dropped"
        else:
            n_offered += 1
            said.append(c.text)
            decisions["options"].append({"kind": "finding_negative", "section": "FINDINGS", "text": c.text,
                                         "finding": c.key,
                                         "reason": "contextual" if p >= PRESENT_HIGH else f"finding borderline (p={p:.2f})"})
    if neg_bullet:
        neg_bullet.lines = neg_lines
    elif matrix and neg_lines:
        matrix.bullets.insert(0, Bullet("Mandatory negatives",
                                        ["- **Mandatory negatives:** (reconciled with this dictation; one finding each)"] + neg_lines))

    # Normal-study path: unaffected lines verbatim; a line either model flags is listed as not
    # assertable. Never deleted: a missing line is refilled from priors, a prohibition holds.
    if normal_bullet:
        decisions["normals"].extend({"text": t, "action": "removed_measurement"} for t in measured)
        keep, flagged = [], []
        qaff = set(qw.affected_normals)
        for k, t in enumerate(normals):
            if score(f"n{k}") >= 0.5 or k in qaff:
                flagged.append(t); decisions["normals"].append({"text": t, "action": "do_not_assert"})
            else:
                keep.append(t); decisions["normals"].append({"text": t, "action": "keep"})
        lines = [f'- **Normal-study path:** "{" ".join(keep)}"' if keep else "- **Normal-study path:** (every line is affected by this dictation)"]
        if flagged:
            lines.append("- **Do not assert as normal (a dictated finding acts on these):** " + " ".join(f'"{t}"' for t in flagged))
        normal_bullet.lines = lines

    # Differentials, policy 1: silence closes a branch only when this study would show it.
    if diffs and lane:
        removed = set()
        for k, t in enumerate(diffs):
            present = score(f"d{k}") >= 0.5
            silent = "imaging-silent" in t
            visible = "visible on this technique: yes" in t
            action = "present" if present else ("removed" if (visible and not silent) else "open")
            if action == "removed":
                removed.add(t)
            decisions["differentials"].append({"text": t, "action": action})
        b = _bullet(lane, "Differentials in scope")
        b.lines = [line for line in b.lines if not ((m := _DIFF.match(line)) and m.group(1) in removed)]

    # Recommendations: Jev removes those whose condition is unmet; of the rest, Qwen's plan
    # includes, excludes, or leaves to the reporter (offered below the report, not written).
    rb = _bullet(imp, "Recommendation scope")
    pdec = {d.index: d for d in plan.recommendations} if plan else {}
    if rb:
        kept, barred = [], []
        for k, t in enumerate(recs):
            d = pdec.get(k)
            if score(f"r{k}") >= 0.5:
                action = "removed"
            elif d is None or d.decision == "include":
                action = "keep"
            elif d.decision == "optional" and len(decisions["options"]) < MAX_OPTIONS:
                action = "optional"
                decisions["options"].append({"kind": "recommendation", "text": t, "reason": d.reason})
            else:
                action = "removed"
            if action == "removed" and d and d.exclude_reason == "routine_workup" and t.startswith(_BAR_KINDS):
                barred.append(re.sub(r"^[A-Z]+:\s*", "", t))
            decisions["recommendations"].append({"text": t, "action": action, "reason": d.reason if d else ""})
            if action == "keep":
                kept.append(f"  - {t}")
        # An investigation excluded as routine workup of a diagnosis already made is named, not
        # just deleted: the generator refills such a test from its priors, a prohibition holds.
        # Everything else is removed silently — naming a referral quoted a duplicate's staging
        # words into the brief, and naming unmet-condition tests suppressed legitimate variants
        # (follow-up imaging for an unresolved opacity).
        rb.lines = [rb.lines[0]] + kept
        if barred:
            rb.lines.append("- **Do not recommend (this study has answered it, or it falls to the receiving team):** "
                            + " ".join(f'"{t}"' for t in barred))

    # Impression plan: what the impression must carry, and what stays in FINDINGS.
    if plan and items:
        pick = lambda idx: [items[i] for i in dict.fromkeys(idx) if 0 <= i < len(items)]
        carry, only = pick(plan.impression), pick(plan.findings_only)
        # Optional findings are left unlisted: the generator places them as it would without a
        # plan (listing them as findings-only dropped findings the impression needed).
        opt = [t for t in pick(plan.optional_impression) if t not in carry]
        room = MAX_OPTIONS - len(decisions["options"])
        decisions["options"].extend({"kind": "impression", "text": t, "reason": ""} for t in opt[:room])
        decisions["impression_plan"] = {"carry": carry, "findings_only": only, "optional": opt[:room]}
        plan_lines = []
        if carry:
            plan_lines.append("- **Carry forward (the impression addresses each):** " + " ".join(f'"{t}"' for t in carry))
        if only:
            plan_lines.append("- **Findings only (not in the impression):** " + " ".join(f'"{t}"' for t in only))
        if plan_lines:
            secs.append(Section("Impression Plan", bullets=[Bullet("Impression plan", plan_lines)]))

    # Unanticipated carried findings: offered negatives from the fallback, never stated.
    if plan and fb_out:
        seen = {c.text for c in cands}
        for it in fb_out.items:
            if it.covered or it.index not in plan.impression or not (0 <= it.index < len(items)):
                continue
            for neg in it.negatives[:3]:
                neg = neg.strip().rstrip(".")
                if not neg or neg in seen or n_offered >= MAX_FINDING_OPTIONS:
                    continue
                if duplicates_negative(neg, said):
                    decisions["finding_negatives"].append({"finding": items[it.index], "text": neg, "tag": "fallback",
                                                           "qwen": "n/a", "present": None, "outcome": "duplicate"})
                    continue
                seen.add(neg)
                said.append(neg)
                n_offered += 1
                decisions["options"].append({"kind": "finding_negative", "section": "FINDINGS", "text": neg,
                                             "finding": items[it.index], "reason": "unanticipated finding"})
                decisions["finding_negatives"].append({"finding": items[it.index], "text": neg, "tag": "fallback",
                                                       "qwen": "n/a", "present": None, "outcome": "offered"})

    # Impression exemplars: only the variant matching this case's shape.
    if variants and imp:
        chosen = int(jev["imp"]["choice"][1:]) if "imp" in jev else 0
        decisions["impression_variant"] = variants[chosen].label
        imp.bullets = [b for b in imp.bullets if b not in variants or b is variants[chosen]]

    # Style exemplars: only those modelling a dictated kind of finding.
    if style:
        keep_styles = []
        for k, b in enumerate(styles):
            m = score(f"s{k}") >= 0.5
            decisions["style"].append({"label": b.label or b.lines[0][:60], "action": "keep" if m else "removed"})
            if m:
                keep_styles.append(b)
        style.bullets = keep_styles

    # Measurement conventions: only for dictated findings.
    if meas:
        app = set(qw.applicable_measurements)
        for k, b in enumerate(measurements):
            decisions["measurements"].append({"label": b.label, "action": "keep" if k in app else "removed"})
        meas.bullets = [b for k, b in enumerate(measurements) if k in app]

    # Lean removals.
    for s in secs:
        s.bullets = [b for b in s.bullets if b.label not in DROP_TOP_BULLETS]
    secs = [s for s in secs if s.heading not in DROP_SECTIONS and (s.heading == "" or s.bullets or any(l.strip() for l in s.preamble))]

    return Brief(text=render(secs), decisions=decisions, reconcile_ms=int((time.time() - t0) * 1000))
