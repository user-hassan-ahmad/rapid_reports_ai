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
import os
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
from . import linked_normals as _ln
from . import normal_groups as _ng
from . import report_reconcile as _rc

logger = logging.getLogger(__name__)


_VISIBILITY_TAG = re.compile(r"\s*\*\([^)]*\)\*")


def present_question(line: str) -> dict:
    """A quick differential line is '<name> — <discriminator> *(visible …)*'."""
    name, _, disc = _VISIBILITY_TAG.sub("", line).partition(" — ")
    return q_present(name.strip(), disc.strip())


async def _qwen_complete(state: str, negs: List[str], normals: List[str], measurements: List[str],
                         linked: Optional[tuple] = None) -> QwenDecisions:
    """report_reconcile._qwen_complete through this module's _qwen and logger (tests patch both here).
    linked: the linked-normal atoms folded into the same call (RR_GROUPED_NORMALS, fold labeller)."""
    kw = {**({"linked": linked} if linked is not None else {}), **({"full": True} if full_labels() else {})}
    ask = (lambda *a: _qwen(*a, **kw)) if kw else _qwen
    return await _rc._qwen_complete(state, negs, normals, measurements, ask=ask, log=logger)


LABEL_TIMEOUT_S = 15.0


def full_labels() -> bool:
    """RR_BRIEF_FULL_LABELS=1: the brief's negatives use the four-label scheme (spec 2026-10-09 §3.0). Off until the
    brief labeller lab passes (plan Task 10)."""
    return os.environ.get("RR_BRIEF_FULL_LABELS", "0").strip().lower() in ("1", "true", "on")


SAID = ("keep", "default", "implicated", "dictated")


def _atom_labels(atoms: list, qw, sep_labels: Optional[List[str]], mode: Optional[str], jev: dict) -> dict:
    """atom id -> {cls, pointer, source, jev_affected}. The classifier's label where it gave one, a default
    upgraded to implicated when Jev "affected" >= 0.5 (both judges must clear an atom for it to be grouped
    as plain normal); no label -> Jev "affected" alone (the production per-line question): affected ->
    contradicted (not asserted), else default."""
    lines = sep_labels if mode == "separate" else getattr(qw, "normal_labels", None)
    got = _ln.parse_labels(lines or [], len(atoms))
    out = {}
    for i, a in enumerate(atoms):
        try:
            p = round(float(jev[f"na{i}"]["noul"]), 3)
        except (KeyError, TypeError, ValueError):
            p = None
        if i + 1 in got:
            out[a.id] = {**got[i + 1], "source": mode, "jev_affected": p}
            # Plausible doubt is implicated: a default the Jev "affected" question flags is upgraded
            # (kept in the report, its own sentence, highlighted), never asserted as plain normal.
            if out[a.id]["cls"] == "default" and p is not None and p >= 0.5:
                out[a.id].update(cls="implicated", source=f"{mode}+jev")  # score lives in jev_affected; pointer is UI text
            continue
        aff = p is not None and p >= 0.5
        out[a.id] = {"cls": "contradicted" if aff else "default", "pointer": "", "source": "jev_affected",
                     "jev_affected": p}
    return out


async def _label_atoms(scan_type: str, clinical_history: str, findings: str, atoms: list) -> List[str]:
    """The negatives classifier on the linked-normal atoms, as its own reasoning-low call (separate labeller)."""
    r = await asyncio.wait_for(_rc._run_agent_with_model(
        model_name=QWEN, output_type=_ln.AtomLabels, system_prompt=_ln.SEPARATE_SYS,
        user_prompt=_ln.separate_user(scan_type, clinical_history, findings, atoms), api_key="",
        model_settings={"temperature": 0, "max_tokens": 8000, "reasoning_effort": "low"}), LABEL_TIMEOUT_S)
    return r.output.labels


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
    if _ng.enabled():   # the path written as sub-bullets, one sentence each
        text = re.sub(r"(?:^|\s)-\s+(?=[A-Z])", " ", text).strip()
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
    # Linked normals: atoms + prose naming them, detected by the field's format (a sheet written with
    # RR_GROUPED_NORMALS on stays linked if the flag is off now). Lines in neither form, or a field with
    # no atom at all (every ordinary sheet), take today's per-line path below.
    linked = _ln.parse_linked(normal_bullet.lines) if normal_bullet else None
    lines_in = [e for e in linked.entries if isinstance(e, str)] if linked else _normal_sentences(normal_bullet)
    measured = [t for t in lines_in if _MEASUREMENT.search(t)]
    normals = [t for t in lines_in if not _MEASUREMENT.search(t)]
    atoms_all: list = []
    if linked:
        for u in linked.units:
            measured += [a.text for a in u.atoms if _MEASUREMENT.search(a.text)]
            u.atoms = [a for a in u.atoms if not _MEASUREMENT.search(a.text)]
        linked.entries = [e for e in linked.entries if not (isinstance(e, _ln.Unit) and not e.atoms)]
        atoms_all = linked.atoms
    diffs = differential_lines(secs)
    keys = distinct_keys(cands)
    recs = _recommendations(imp)
    styles = style.bullets if style else []
    variants = _impression_variants(imp)
    measurements = meas.bullets if meas else []

    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    qs = {}
    qs.update({f"n{k}": {"type": "noul", "instructions": Q_AFFECTED + t} for k, t in enumerate(normals)})
    # Linked atoms: Jev "affected" is asked only as the fallback for an atom the classifier leaves unlabelled.
    qs.update({f"na{i}": {"type": "noul", "instructions": Q_AFFECTED + a.text} for i, a in enumerate(atoms_all)})
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
    mode = _ln.labeller() if atoms_all else None
    fold = (_ln.FOLD_SYS, _ln.statements_block(atoms_all, clinical_history)) if mode == "fold" else None
    timing: dict = {}

    async def timed(name, coro):
        t = time.time()
        try:
            return await coro
        finally:
            timing[name] = int((time.time() - t) * 1000)

    async def labels_or_none():
        if mode != "separate":
            return None
        try:
            return await _label_atoms(scan_type, clinical_history, findings, atoms_all)
        except Exception as e:  # unlabelled atoms fall back to Jev "affected"
            logger.warning("linked-normal labeller failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    link_units = [u for u in (linked.units if linked else []) if not _ln.code_check(u)]

    async def link_or_none(u):
        try:
            return await _jev(u.prose, _ln.link_questions(u))
        except Exception as e:  # the code check decides alone
            logger.warning("linked-normal link check failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    async def links():
        return await asyncio.gather(*(link_or_none(u) for u in link_units))

    jev, qw, plan, fb_out, sep_labels, link_answers = await asyncio.gather(
        timed("jev", _jev(state, qs)) if qs else asyncio.sleep(0, {}),
        timed("qwen", _qwen_complete(state, [n for n, _ in negs] + [c.text for c in cands], normals,
                                     [" ".join(b.lines) for b in measurements], linked=fold)),
        plan_or_none(), fallback_or_none(), timed("labeller", labels_or_none()), timed("links", links()))
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
        elif action == "dictated":
            neg_lines.append(f'  - DICTATED: "{text}" — state it as the dictation does')
        elif action == "implicated" and d.dictated_finding:
            neg_lines.append(f'  - KEEP: "{text}"{why} (implicated by: {d.dictated_finding})')
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
            decisions["negatives"].append({"text": c.text, "action": label if label in SAID else "keep",
                                           "dictated_finding": d.dictated_finding if d else "",
                                           "source": f"finding:{c.key}"})
        elif outcome == "do_not_assert":
            neg_lines.append(f'  - DO NOT ASSERT: "{c.text}" — expected consequence of: {d.dictated_finding}')
    # An offered negative the brief already states (KEEP) or the dictation already makes is a
    # duplicate, never an option.
    said = [n["text"] for n in decisions["negatives"] if n["action"] in SAID] + dictated_negatives(items)
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
        dneg = dictated_negatives(items)
        offset = 0
        legacy = [{"text": t, "action": "do_not_assert" if (score(f"n{k}") >= 0.5 or k in qaff) else "keep"}
                  for k, t in enumerate(normals)]
        entries = linked.entries if linked else normals
        if linked:
            labels = _atom_labels(atoms_all, qw, sep_labels, mode, jev)
            positives = _ng.positive_findings(items)
            verdicts = dict(zip(map(id, link_units), link_answers))
            link_log = []
        li = iter(legacy)
        for e in entries:
            if isinstance(e, str):
                if _MEASUREMENT.search(e):
                    continue
                d = next(li)
                decisions["normals"].append(d)
                if d["action"] == "keep":
                    keep.append(e); offset += len(e) + 1
                else:
                    flagged.append(e)
                continue
            v = _ln.link_verdict(e, verdicts.get(id(e)))
            link_log.append({"pid": e.pid, **v})
            r = _ln.render_unit(e, labels, v["ok"], dneg, positives)
            link_log[-1]["mode"] = r.mode
            flagged.extend(r.flagged)
            decisions["normals"].append({
                "text": e.prose, "pid": e.pid, "linked": True, "link": v, "mode": r.mode,
                "action": "keep" if r.text else "do_not_assert", "rendered": r.text,
                "offset": offset if r.text else None,
                "atoms": [{**a, "path_span": [offset + a["span"][0], offset + a["span"][1]] if a["span"] else None}
                          for a in r.atoms]})
            if r.text:
                keep.append(r.text)
                offset += len(r.text) + 1
        if linked:
            decisions["linked"] = {"labeller": mode, "timing_ms": timing, "n_atoms": len(atoms_all),
                                   "notes": getattr(qw, "normal_notes", "") if mode == "fold" else "",
                                   "n_units": len(linked.units), "n_loose": len(normals),
                                   "link_failed": sum(1 for x in link_log if not x["ok"]),
                                   "multi_predicate": sum(1 for x in link_log if "multi-predicate" in x["code"]),
                                   "subtract_fallback": sum(1 for x in link_log if x["ok"] and x["mode"] == "atoms"),
                                   "upgrades": [f"{a.id} {a.term} ({labels[a.id]['jev_affected']})" for a in atoms_all
                                                if labels[a.id]["source"].endswith("+jev")]}
        lines = [f'- **Normal-study path:** "{" ".join(keep)}"' if keep else "- **Normal-study path:** (every line is affected by this dictation)"]
        if flagged:
            lines.append("- **Do not assert as normal (a dictated finding acts on these):** " + " ".join(f'"{t}"' for t in flagged))
        if linked and dneg:
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
