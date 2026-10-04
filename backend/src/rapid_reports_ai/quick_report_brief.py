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

The Jev/Qwen calls and routing now live in report_reconcile (shared with the templated pathway).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .report_reconcile import (  # noqa: F401 — re-exported; tests patch these names on this module
    JEV_MODEL, JEV_TIMEOUT_S, JEV_URL, MAX_FINDING_OPTIONS, MAX_OPTIONS, PLAN_SYS, PLAN_TIMEOUT_S,
    PRESENT_HIGH, PRESENT_LOW, PRESENT_FALSE, PRESENT_TRUE, HEDGE, Q_AFFECTED, Q_REC_MET, Q_STYLE_MATCH, QWEN,
    QWEN_SYS, QWEN_TIMEOUT_S, FALLBACK_SYS, FALLBACK_TIMEOUT_S, _BAR_KINDS, _MEASUREMENT, Brief,
    FallbackItem, FallbackNegatives, FindingNegative, ImpressionPlan, IncompleteNegativeDecisions,
    NegativeDecision, QwenDecisions, RecDecision, Split, _fallback, _is_bundled, _jev, _plan, _quoted, _qwen,
    _sentences, _split_bundled, _unstring, _words, dictated_negatives, duplicates_negative, finding_presence,
    q_finding, q_present, route_finding, split_findings,
)
from . import normal_groups as _ng
from . import report_reconcile as _rc

logger = logging.getLogger(__name__)


_VISIBILITY_TAG = re.compile(r"\s*\*\([^)]*\)\*")


def present_question(line: str) -> dict:
    """A quick differential line is '<name> — <discriminator> *(visible …)*'."""
    name, _, disc = _VISIBILITY_TAG.sub("", line).partition(" — ")
    return q_present(name.strip(), disc.strip())


async def _qwen_complete(state: str, negs: List[str], normals: List[str], measurements: List[str]) -> QwenDecisions:
    """report_reconcile._qwen_complete through this module's _qwen and logger (tests patch both here)."""
    return await _rc._qwen_complete(state, negs, normals, measurements, ask=_qwen, log=logger)


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


_CONFIRMED = re.compile(r'^\s+-\s+(.+?)\s*(?:→|->)\s*"([^"]+)"\s*(?:\((core|contextual)\))?')
# The analyser also nests: the key on its own line, its negatives as sub-bullets.
_CONFIRMED_BRANCH = re.compile(r'^\s+-\s+([^"]+?)\s*(?:→|->)\s*$')
_CONFIRMED_NEG = re.compile(r'^\s+-\s+"([^"]+)"\s*(?:\((core|contextual)\))?')


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


# ── compile ──────────────────────────────────────────────────────────────────

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

    # Grouped normals (opt-in): a sentence listing structures is decided structure by structure
    # (and tail negative by tail negative), then rendered by subtraction; anything else is one line.
    grouped = [(_ng.parse_grouped(t) if _ng.enabled() else None) for t in normals]
    grouped = [g if g and len(g.structures) + len(g.tail) > 1 else None for g in grouped]
    normal_texts: List[str] = []      # what Qwen numbers: a line, or each atom of a grouped line
    normal_qidx: dict = {}            # (k, j) -> index in normal_texts; j None for a whole line

    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    qs = {}
    for k, t in enumerate(normals):
        if grouped[k] is None:
            normal_qidx[(k, None)] = len(normal_texts)
            normal_texts.append(t)
            qs[f"n{k}"] = {"type": "noul", "instructions": Q_AFFECTED + t}
            continue
        for j, (_, line) in enumerate(grouped[k].atoms()):
            normal_qidx[(k, j)] = len(normal_texts)
            normal_texts.append(line)
            qs[f"n{k}a{j}"] = {"type": "noul", "instructions": Q_AFFECTED + line}
    qs.update({f"d{k}": present_question(t) for k, t in enumerate(diffs)})
    qs.update({f"r{k}": {"type": "noul", "instructions": Q_REC_MET + t} for k, t in enumerate(recs)})
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
        _qwen_complete(state, [n for n, _ in negs] + [c.text for c in cands], normal_texts, [" ".join(b.lines) for b in measurements]),
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
        affected = lambda k, j=None: score(f"n{k}" if j is None else f"n{k}a{j}") >= 0.5 or normal_qidx[(k, j)] in qaff
        said_items = dictated_negatives(items) + items
        offset = 0
        for k, t in enumerate(normals):
            g = grouped[k]
            if g is None:
                if affected(k):
                    flagged.append(t); decisions["normals"].append({"text": t, "action": "do_not_assert"})
                else:
                    keep.append(t); decisions["normals"].append({"text": t, "action": "keep"})
                    offset += len(t) + 1
                continue
            atoms = g.atoms()
            keep_flags = [not affected(k, j) for j in range(len(atoms))]
            flagged.extend(line for (_, line), kf in zip(atoms, keep_flags) if not kf)
            names = g.structures + g.tail
            # A kept structure or tail negative the dictation also speaks to: one line per atom, so a
            # grouped sentence never reads as covering what the radiologist dictated.
            overlap = _ng.dictated_overlap([n for n, kf in zip(names, keep_flags) if kf], said_items)
            r = _ng.per_structure(g, keep_flags) if overlap else _ng.subtract(g, keep_flags)
            if overlap and r.mode == "per_structure":
                r.mode = "per_structure_dictated"
            decisions["normals"].append({
                "text": t, "action": "keep" if r.text else "do_not_assert", "grouped": True, "mode": r.mode,
                "rendered": r.text, "offset": offset if r.text else None, "dictated_overlap": overlap,
                "atoms": [{"name": n, "kind": kind, "line": line, "action": "keep" if kf else "do_not_assert",
                           "span": list(sp) if sp else None}
                          for n, (kind, line), kf, sp in zip(names, atoms, keep_flags, r.spans)]})
            if r.text:
                keep.append(r.text)
                offset += len(r.text) + 1
        lines = [f'- **Normal-study path:** "{" ".join(keep)}"' if keep else "- **Normal-study path:** (every line is affected by this dictation)"]
        if flagged:
            lines.append("- **Do not assert as normal (a dictated finding acts on these):** " + " ".join(f'"{t}"' for t in flagged))
        dneg = dictated_negatives(items) if any(grouped) else []
        if dneg:
            # Guard: a grouped normal sentence must never stand in for a negative the radiologist dictated.
            lines.append("- **Dictated negatives (state each as dictated):** " + " ".join(f'"{t}"' for t in dneg))
            decisions["dictated_negatives"] = dneg
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
            if 1 - score(f"r{k}") >= 0.5:      # condition unmet
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
