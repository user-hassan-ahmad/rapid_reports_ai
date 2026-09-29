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
from pydantic import BaseModel

from .enhancement_utils import _run_agent_with_model

logger = logging.getLogger(__name__)

JEV_URL = "https://openrouter.ai/api/v1/systemone"
JEV_MODEL = "typesafe/jev-1.13"
QWEN = "qwen-3.8-27b"
JEV_TIMEOUT_S = 6.0
QWEN_TIMEOUT_S = 10.0

DROP_TOP_BULLETS = {"Out of scope", "Modality non-assessables", "In-scope companions", "Out-of-scope suppressed"}
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


class QwenDecisions(BaseModel):
    negatives: List[NegativeDecision]
    affected_normals: List[int]
    applicable_measurements: List[int]


class Split(BaseModel):
    negatives: List[List[str]]


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


# ── compile ──────────────────────────────────────────────────────────────────

@dataclass
class Brief:
    text: str
    decisions: dict
    reconcile_ms: int


async def compile_brief(sheet: str, scan_type: str, findings: str) -> Brief:
    t0 = time.time()
    secs = parse_sheet(sheet)
    lane, struct = _section(secs, "Clinical Lane"), _section(secs, "Structural Pattern")
    matrix, style = _section(secs, "Companion Matrix"), _section(secs, "Style Exemplars")
    meas, imp, ctx = _section(secs, "Measurement Conventions"), _section(secs, "Impression Exemplars"), _section(secs, "Scan Context")

    neg_bullet = _bullet(matrix, "Mandatory negatives")
    raw_negs = [n.strip().rstrip(".") for n in _quoted(" ".join(neg_bullet.lines))] if neg_bullet else []
    targets = {n: (re.search(r'"' + re.escape(n) + r'\.?"\s*\(([^)]*)\)', " ".join(neg_bullet.lines)) or [None, ""])[1]
               for n in raw_negs} if neg_bullet else {}
    split = await _split_bundled(raw_negs)
    negs = [(c, targets.get(parent, "")) for parent, parts in zip(raw_negs, split) for c in parts]
    normal_bullet = _bullet(struct, "Normal-study path")
    # A normal line that states a measurement asserts a value nobody dictated whenever the
    # dictation is silent about it, so it never reaches the generator.
    measured = [t for t in _normal_sentences(normal_bullet) if _MEASUREMENT.search(t)]
    normals = [t for t in _normal_sentences(normal_bullet) if not _MEASUREMENT.search(t)]
    diffs = differential_lines(secs)
    recs = _recommendations(imp)
    styles = style.bullets if style else []
    variants = _impression_variants(imp)
    measurements = meas.bullets if meas else []

    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    qs = {}
    qs.update({f"n{k}": {"type": "noul", "instructions": Q_AFFECTED + t} for k, t in enumerate(normals)})
    qs.update({f"d{k}": {"type": "noul", "instructions": Q_PRESENT + t} for k, t in enumerate(diffs)})
    qs.update({f"r{k}": {"type": "noul", "instructions": Q_REC_UNMET + t} for k, t in enumerate(recs)})
    qs.update({f"s{k}": {"type": "noul", "instructions": Q_STYLE_MATCH + " ".join(b.lines)} for k, b in enumerate(styles)})
    if len(variants) > 1:
        qs["imp"] = {"type": "choice", "instructions": "Which impression exemplar best matches the shape of this case's findings (severity, number of findings, complications)?",
                     "criteria": {f"v{k}": " ".join(b.lines)[:400] for k, b in enumerate(variants)}}
    jev, qw = await asyncio.gather(_jev(state, qs) if qs else asyncio.sleep(0, {}),
                                   _qwen(state, [n for n, _ in negs], normals, [" ".join(b.lines) for b in measurements]))
    score = lambda k: float(jev[k]["noul"])

    decisions: dict = {"negatives": [], "normals": [], "differentials": [], "recommendations": [], "style": [], "measurements": [], "impression_variant": None}

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
        decisions["negatives"].append({"text": text, "action": action, "dictated_finding": d.dictated_finding if d else ""})
    if neg_bullet:
        neg_bullet.lines = neg_lines

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

    # Recommendations: keep only those whose condition the findings meet or leave open.
    rb = _bullet(imp, "Recommendation scope")
    if rb:
        kept = []
        for k, t in enumerate(recs):
            unmet = score(f"r{k}") >= 0.5
            decisions["recommendations"].append({"text": t, "action": "removed" if unmet else "keep"})
            if not unmet:
                kept.append(f"  - {t}")
        rb.lines = [rb.lines[0]] + kept

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
