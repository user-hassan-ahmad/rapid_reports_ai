"""Template brief (spec 2026-09-30-template-pipeline-mirror §3, grammar addendum 2026-10-01): the stored
sheet reconciled with one dictation through the shared engine and rewritten IN PLACE.

Every unit line the structure covers is rewritten where it sits (its label line or lines) or removed;
every other line (prose, the radiologist's voice, SECTION / FIXED / TERM units) passes through verbatim.
IF_PRESENT is off for templates: the structure's if_present is never read and its unit lines are removed
(stored, unused in v1). Finding-linked negatives come only from the shared fallback, offered, never stated.

Reconcile, in parallel:
- Jev, findings state (scan type + dictated findings): findings-sourced rule conditions, conditional
  negatives, affected normals (NORMAL and stated-normal lines), and one question per LIST_MISSING item.
- Jev, context state (the findings state plus the clinical history): history/context-sourced rule
  conditions and conditional negatives only. History is read here, never written.
- Qwen classifier: each distinct sheet negative -> keep / contradicted / expected; second opinion on
  affected normals.
- Impression plan, with the sheet's "## Impression Construction" prose as the reporter's inclusion logic.
- Fallback for dictated findings (no If-present keys, so every item is unanticipated): offered only.

Any exception from Jev or Qwen propagates: the caller generates down the raw path. The plan and fallback
fail soft (no plan section, no options), as in quick.

Jev keys: r<i> rule condition, r<i>i<j> LIST_MISSING item, c<k> conditional negative, m<i> NORMAL,
s<k> stated-normal negative (k indexes structure.negatives, i structure.rules / structure.normals).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

from . import report_reconcile as rc
from .report_review import positive_items
from .template_sheet_structure import SheetStructure, _covers, _key

logger = logging.getLogger(__name__)

Q_CONDITION = "This statement is true for this case: "
Q_STATED = "The dictated findings state "
MET = 0.5

_IF_PRESENT_LINE = re.compile(r"^\s*(?:-\s+)?IF_PRESENT\b")
_H2 = re.compile(r"^#{1,2}\s")
_PARAGRAPH_HEADING = re.compile(r"^##\s+Paragraph:.*\(([^()]*)\)\s*$", re.I)


def _section_body(sheet: str, title: str) -> str:
    """Prose of a '## <title>' block, up to the next '# ' or '## ' heading ('### ' stays inside)."""
    out: List[str] = []
    inside = False
    for ln in sheet.splitlines():
        if _H2.match(ln):
            if inside:
                break
            inside = ln.lstrip("#").strip().lower() == title.lower()
            continue
        if inside:
            out.append(ln)
    return "\n".join(out).strip()


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _q(t: str) -> str:
    """A negative quoted with exactly one trailing full stop."""
    return t.strip().rstrip(".") + "."


class _Lines:
    """The sheet's lines, each unit claiming its own line. Units of one kind are listed in sheet order,
    so identical unit lines in two paragraphs are claimed in turn, not both mapped to the first."""

    def __init__(self, sheet: str):
        self.lines = sheet.splitlines()
        self.claimed: Dict[str, set] = {}
        self.edits: Dict[int, List[str]] = {}

    def locate(self, kind: str, source_line) -> Optional[int]:
        if not isinstance(source_line, str):
            return None
        taken = self.claimed.setdefault(kind, set())
        for exact in (True, False):
            for i, ln in enumerate(self.lines):
                if i not in taken and (ln == source_line if exact else _covers(source_line, ln)):
                    taken.add(i)
                    return i
        return None

    def put(self, i: Optional[int], new: List[str]) -> None:
        """Replace line i with the label lines (appended when two units share a line; [] deletes it)."""
        if i is None:
            return
        self.edits.setdefault(i, []).extend(_indent(self.lines[i]) + x for x in new)

    def drop_paragraphs(self, sections: set) -> None:
        """Delete every '## Paragraph: <name> (<SECTION>)' block of these sections, heading to the next
        '# '/'## ' heading, except lines that carry a label (a rule written there)."""
        if not sections:
            return
        dropping = False
        for i, ln in enumerate(self.lines):
            if _H2.match(ln):
                m = _PARAGRAPH_HEADING.match(ln)
                dropping = bool(m) and re.sub(r"\s+", " ", m.group(1)).strip().upper() in sections
            if dropping and not self.edits.get(i):
                self.edits[i] = []

    def render(self) -> str:
        out: List[str] = []
        for i, ln in enumerate(self.lines):
            if i in self.edits:
                out.extend(self.edits[i])
            elif not _IF_PRESENT_LINE.match(ln):
                out.append(ln)
        return "\n".join(out)


async def compile_template_brief(sheet: str, s: SheetStructure, scan_type: str, findings: str,
                                 clinical_history: str = "") -> rc.Brief:
    """The brief for one case. Raises on an unusable structure or a Jev/Qwen failure (raw path)."""
    if not s.usable:
        raise ValueError("template brief needs a usable sheet structure")
    t0 = time.monotonic()
    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    ctx_state = f"{state}\nCLINICAL HISTORY:\n{clinical_history or '(not given)'}"
    items = rc.split_findings(findings)
    findings_section = next((x.name for x in s.sections if x.role == "findings"), "FINDINGS")
    imp_section = next((x.name for x in s.sections if x.role == "impression"), "IMPRESSION")
    ctx_sources = ("history", "context")

    negs = [(k, n) for k, n in enumerate(s.negatives) if n.kind == "negative"]
    stated_normals = [(k, n) for k, n in enumerate(s.negatives) if n.kind == "stated_normal"]

    # ── questions ────────────────────────────────────────────────────────────
    q_f: Dict[str, dict] = {}
    q_c: Dict[str, dict] = {}
    for i, r in enumerate(s.rules):
        if r.effect == "list_missing":  # always evaluated: one question per item, findings state
            for j, item in enumerate(r.items):
                q_f[f"r{i}i{j}"] = {"type": "noul", "instructions": Q_STATED + item}
            continue
        (q_c if r.condition_source in ctx_sources else q_f)[f"r{i}"] = {
            "type": "noul", "instructions": Q_CONDITION + r.condition}
    for k, n in negs:
        if n.condition:
            (q_c if n.condition_source in ctx_sources else q_f)[f"c{k}"] = {
                "type": "noul", "instructions": Q_CONDITION + n.condition}
    for i, n in enumerate(s.normals):
        q_f[f"m{i}"] = {"type": "noul", "instructions": rc.Q_AFFECTED + n.text}
    for k, n in stated_normals:
        q_f[f"s{k}"] = {"type": "noul", "instructions": rc.Q_AFFECTED + n.text}

    # Each distinct negative is classified once, so every copy carries the same label.
    distinct: List[str] = []
    for _, n in negs:
        if _key(n.text) not in {_key(t) for t in distinct}:
            distinct.append(n.text.strip().rstrip("."))
    split = await rc._split_bundled(distinct)
    flat: List[Tuple[int, str]] = [(d, part) for d, parts in enumerate(split) for part in parts]
    normal_texts = [n.text for n in s.normals] + [n.text for _, n in stated_normals]

    async def plan_or_none():
        try:
            return await rc._plan(scan_type, clinical_history, items, [],
                                  inclusion_logic=_section_body(sheet, "Impression Construction"))
        except Exception as e:  # the brief still compiles, without an Impression Plan
            logger.warning("template impression plan failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    async def fallback_or_none():
        try:
            return await rc._fallback(state, items, []) if items else None
        except Exception as e:  # the brief still compiles; dictated findings just get no options
            logger.warning("template finding-negatives fallback failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    jev_f, jev_c, qw, plan, fb = await asyncio.gather(
        rc._jev(state, q_f) if q_f else asyncio.sleep(0, {}),
        rc._jev(ctx_state, q_c) if q_c else asyncio.sleep(0, {}),
        rc._qwen(state, [p for _, p in flat], normal_texts, []),
        plan_or_none(), fallback_or_none())

    def score(k: str) -> float:
        ans = jev_c if k in q_c else jev_f
        try:
            return float(ans[k]["noul"])
        except (KeyError, TypeError, ValueError):
            return 0.0

    qneg = {d.index: d for d in qw.negatives}
    q_affected = set(qw.affected_normals)
    para_name = {p.id: p.name for p in s.paragraphs}
    L = _Lines(sheet)
    decisions: dict = {"rules": [], "negatives": [], "normals": [], "missing": [], "finding_negatives": [],
                       "options": [], "impression_plan": None}

    # ── rules: decide first; suppressions act on other units ────────────────
    met_rule: Dict[int, bool] = {}
    rule_score: Dict[int, float] = {}
    for i, r in enumerate(s.rules):
        if r.effect != "list_missing":
            rule_score[i] = score(f"r{i}")
            met_rule[i] = rule_score[i] >= MET
    omitted_sections = {r.target for i, r in enumerate(s.rules)
                        if r.effect == "suppress_section" and met_rule.get(i)}
    para_suppressed: Dict[str, str] = {}  # paragraph id -> the statement that suppresses its negatives
    targeted: Dict[str, List[tuple]] = {}  # target key -> [(statement, instead text)]
    for i, r in enumerate(s.rules):
        if not met_rule.get(i) or r.section in omitted_sections:
            continue
        if r.effect == "suppress_paragraph_negatives" and r.paragraph:
            para_suppressed.setdefault(r.paragraph, r.condition)
        elif r.effect in ("suppress", "replace") and r.target:
            targeted.setdefault(_key(r.target), []).append(
                (r.condition, r.then_text if r.effect == "replace" else ""))
    unit_keys = {_key(n.text) for n in s.negatives} | {_key(n.text) for n in s.normals}

    def omit_lines(text: str, quote) -> List[str]:
        out: List[str] = []
        for statement, instead in targeted.get(_key(text), []):
            out.append(f'- OMIT: "{quote(text)}" — {statement}')
            if instead:
                out.append(f'- INSTEAD: "{instead}"')
        return out

    for i, r in enumerate(s.rules):
        line = L.locate("rule", r.source_lines[0]) if r.source_lines else None
        for extra in r.source_lines[1:]:
            L.put(L.locate("rule", extra), [])
        entry = {"id": r.id, "effect": r.effect, "condition": r.condition, "source": r.condition_source}
        if r.section in omitted_sections and not (r.effect == "suppress_section" and r.target == r.section):
            L.put(line, [])
            decisions["rules"].append({**entry, "met": met_rule.get(i), "score": round(rule_score.get(i, 0.0), 3),
                                       "action": "section_omitted"})
            continue
        if r.effect == "list_missing":
            missing = [item for j, item in enumerate(r.items) if score(f"r{i}i{j}") < MET]
            where = "end" if r.position == "end" else "top"
            L.put(line, [f"- MISSING (list at {where}): " + ", ".join(missing)] if missing else [])
            decisions["missing"].append({"id": r.id, "items": r.items, "missing": missing, "position": where})
            decisions["rules"].append({**entry, "met": bool(missing), "score": None,
                                       "action": "listed" if missing else "removed"})
            continue
        met = met_rule[i]
        new: List[str] = []
        if met:
            if r.effect in ("suppress", "replace"):
                # The OMIT (and INSTEAD) sit where the target is when it is a unit; else on the rule's line.
                if _key(r.target) not in unit_keys:
                    new.append(f'- OMIT: "{r.target}" — {r.condition}')
                    if r.effect == "replace" and r.then_text:
                        new.append(f'- INSTEAD: "{r.then_text}"')
            elif r.effect == "append":
                new.append(f'- APPLY: "{r.then_text}"')
            elif r.effect == "use":
                new.append(f'- USE: "{r.then_text}"')
            elif r.effect == "insert_before":
                new.append(f'- INSERT: "{r.then_text}" BEFORE "{r.anchor}"')
            elif r.effect == "suppress_paragraph_negatives":
                new.append("- DESCRIBE FROM DICTATION: this paragraph's normal wording does not apply")
            elif r.effect == "suppress_section":
                new.append(f"- OMIT SECTION: {r.target} — {r.condition}")
            elif r.effect == "suppress_headers":
                new.append(f"- NO PARAGRAPH HEADERS — {r.condition}")
            elif r.effect == "order":
                new.append(f"- PLACE THIS PARAGRAPH {(r.position or 'first').upper()} — {r.condition}")
        L.put(line, new)
        decisions["rules"].append({**entry, "met": met, "score": round(rule_score[i], 3),
                                   "action": "applied" if met else "removed"})

    # ── negatives ───────────────────────────────────────────────────────────
    for k, n in negs:
        line = L.locate("negative", n.source_lines[0]) if n.source_lines else None
        for extra in n.source_lines[1:]:
            L.put(L.locate("negative", extra), [])
        d_idx = next(d for d, t in enumerate(distinct) if _key(t) == _key(n.text))
        parts = [(j, part) for j, (d, part) in enumerate(flat) if d == d_idx]
        entry = {"id": n.id, "text": n.text, "paragraph": para_name.get(n.paragraph, "")}
        if n.section in omitted_sections:
            L.put(line, [])
            decisions["negatives"].append({**entry, "action": "section_omitted", "lines": []})
            continue
        # A met SUPPRESS / REPLACE of this negative wins over its own condition: the OMIT and the
        # INSTEAD the rule prescribes are stated whether or not the negative would have been.
        new = omit_lines(n.text, _q)
        if not new and n.condition and score(f"c{k}") < MET:
            L.put(line, [])
            decisions["negatives"].append({**entry, "action": "removed", "condition": n.condition,
                                           "score": round(score(f"c{k}"), 3), "lines": []})
            continue
        if new:
            action = "rule_omitted"
        elif n.paragraph in para_suppressed:
            new = [f'- OMIT: "{_q(part)}" — {para_suppressed[n.paragraph]}' for _, part in parts]
            action = "paragraph_suppressed"
        else:
            for j, part in parts:
                d = qneg.get(j)
                if d and d.action == "contradicted":
                    new.append(f'- OMIT: "{_q(part)}" — the dictation reports: {d.dictated_finding}')
                elif d and d.action == "expected":
                    new.append(f'- DO NOT ASSERT: "{_q(part)}" — expected consequence of: {d.dictated_finding}')
                else:
                    new.append(f'- KEEP: "{_q(part)}"')
            action = "labelled"
        L.put(line, new)
        decisions["negatives"].append({**entry, "action": action, "lines": new})

    # ── normals: kept verbatim, or never asserted (never deleted) ────────────
    def normal(line: Optional[int], nid: str, text: str, structure: str, section: str, paragraph: str,
               jev_key: str, q_index: int, extra: dict) -> None:
        entry = {"id": nid, "structure": structure, **extra}
        if section in omitted_sections:
            L.put(line, [])
            decisions["normals"].append({**entry, "action": "section_omitted"})
            return
        new = omit_lines(text, lambda t: t)
        if new:
            action = "rule_omitted"
        elif paragraph in para_suppressed:  # SUPPRESS NEGATIVES: the paragraph is described from the dictation
            new, action = [f'- DO NOT ASSERT AS NORMAL [{structure}]: "{text}"'], "suppressed_by_rule"
        else:
            flagged = score(jev_key) >= MET or q_index in q_affected
            label = "DO NOT ASSERT AS NORMAL" if flagged else "KEEP NORMAL"
            new, action = [f'- {label} [{structure}]: "{text}"'], ("do_not_assert" if flagged else "keep")
        L.put(line, new)
        decisions["normals"].append({**entry, "score": round(score(jev_key), 3),
                                     "qwen_affected": q_index in q_affected, "action": action})

    for i, n in enumerate(s.normals):
        normal(L.locate("normal", n.source_line), n.id, n.text, n.structure, n.section, n.paragraph,
               f"m{i}", i, {})
    for pos, (k, n) in enumerate(stated_normals):
        line = L.locate("negative", n.source_lines[0]) if n.source_lines else None
        for extra in n.source_lines[1:]:
            L.put(L.locate("negative", extra), [])
        normal(line, n.id, n.text, para_name.get(n.paragraph) or n.section, n.section, n.paragraph,
               f"s{k}", len(s.normals) + pos, {"kind": "stated_normal"})

    # An omitted section's paragraph shells (heading and prose) go too; the OMIT SECTION line stays.
    L.drop_paragraphs(omitted_sections)

    text = L.render()

    # Normal-study impression: dropped when anything positive is dictated.
    if positive_items(findings):
        text = re.sub(r"^###\s+Normal study (?:impression|conclusion)\s*\n.*?(?=^#|\Z)", "", text,
                      flags=re.M | re.S | re.I)

    # ── impression plan and options ─────────────────────────────────────────
    if plan and items:
        pick = lambda idx: [items[i] for i in dict.fromkeys(idx) if 0 <= i < len(items)]
        carry, only = pick(plan.impression), pick(plan.findings_only)
        opt = [t for t in pick(plan.optional_impression) if t not in carry][:rc.MAX_OPTIONS]
        decisions["options"].extend({"kind": "impression", "section": imp_section, "text": t, "reason": ""}
                                    for t in opt)
        decisions["impression_plan"] = {"carry": carry, "findings_only": only, "optional": opt}
        plan_lines = []
        if carry:
            plan_lines.append("- **Carry forward (the impression addresses each):** " + " ".join(f'"{t}"' for t in carry))
        if only:
            plan_lines.append("- **Findings only (not in the impression):** " + " ".join(f'"{t}"' for t in only))
        if plan_lines:
            text += "\n\n## Impression Plan\n" + "\n".join(plan_lines)

    # Finding-linked negatives: the shared fallback's, for carried findings; offered, never stated.
    if plan and fb:
        seen: set = set()
        n_offered = 0
        for it in fb.items:
            if it.covered or it.index not in plan.impression or not (0 <= it.index < len(items)):
                continue
            for neg in it.negatives[:3]:
                neg = neg.strip().rstrip(".")
                if neg and neg not in seen and n_offered < rc.MAX_FINDING_OPTIONS:
                    seen.add(neg)
                    n_offered += 1
                    decisions["options"].append({"kind": "finding_negative", "section": findings_section, "text": neg,
                                                 "finding": items[it.index], "reason": "unanticipated finding"})
                    decisions["finding_negatives"].append({"finding": items[it.index], "text": neg,
                                                           "outcome": "offered", "source": "fallback"})

    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return rc.Brief(text=text, decisions=decisions, reconcile_ms=int((time.monotonic() - t0) * 1000))
