"""Template brief (spec 2026-09-30-template-pipeline-mirror §3, grammar addendum 2026-10-01): the stored
sheet reconciled with one dictation through the shared engine and rewritten IN PLACE.

Every unit line the structure covers is rewritten where it sits (its label line or lines) or removed;
every other line (prose, the radiologist's voice, SECTION / FIXED / TERM units) passes through verbatim.
IF_PRESENT is off for templates: the structure's if_present is never read and its unit lines are removed
(stored, unused in v1). Finding-linked negatives come only from the shared fallback, offered, never stated.

Reconcile, in parallel:
- Jev, findings state (scan type + dictated findings): findings-sourced rule conditions, conditional
  negatives, affected normals (NORMAL and stated-normal lines), and one question per LIST_MISSING item.
- Jev, history state (scan type + clinical history, no findings): history-sourced conditions; context
  state (the history state plus the sheet's Scan Context / technique paragraphs, no findings):
  context-sourced conditions. History is read here, never written.
- Qwen classifier: each distinct sheet negative -> keep / contradicted / expected; second opinion on
  affected normals.
- Impression plan, with the sheet's "## Impression Construction" prose as the reporter's inclusion logic.
- Fallback for dictated findings (no If-present keys, so every item is unanticipated): offered only.

Fails closed (raises; the caller generates down the raw path): an unusable structure, a unit line that
cannot be found in the sheet, any Jev or Qwen error, a Jev answer missing or non-numeric for any key asked,
and Qwen negative decisions that do not cover exactly the negatives sent. The plan and fallback fail soft
(no plan section, no options), as in quick.

Scope. A paragraph RULE's SUPPRESS / REPLACE acts on units of its own paragraph only; a Report-wide RULE
acts on units of its section. SUPPRESS NEGATIVES acts on its paragraph and on same-text Report-wide
negatives of that paragraph's section. SUPPRESS_SECTION removes the section's paragraphs (units, headings
and prose) and the Report-wide units tagged "| section: <that section>"; untagged Report-wide units stay.

Jev keys: r<i> rule condition, r<i>i<j> LIST_MISSING item, c<k> conditional negative, m<i> NORMAL,
s<k> stated-normal negative (k indexes structure.negatives, i structure.rules / structure.normals);
master sheets also d<k> differential present, f<i> If-present finding reported, rec<k> recommendation
condition unmet (k indexes structure.differentials / structure.recommendations, i the distinct findings).

Master sheets (Phase-1 case units, spec 2026-10-01-template-two-phase "Phase 2 brief additions"), routed by
quick's shared clinical routing in report_reconcile:
- DIFFERENTIAL: rc.route_differential (policy 1) -> ADDRESS (present) / removed (closed by silence) / OPEN
  (not visible on this technique, or imaging-silent: defer), rewritten in the "## Case Deliberation" block,
  which the brief marks as reasoning input, never report text; QUESTION -> CLINICAL QUESTION.
- NEGATIVE … TARGETS (case): classified with the template negatives (same Qwen call, same exact-index
  check); OMIT when its targeted differential is present; DO NOT ASSERT when that differential is not
  VISIBLE yes (lint blocks it; defence). One label per claim, safer wins (OMIT > DO NOT ASSERT > KEEP),
  logged in decisions["conflicts"]: the same claim (exact key) anywhere is OMIT when a case negative omits
  it, whatever became of that case negative; and for each present VISIBLE yes differential Jev reads every template
  negative / normal in scope (x<k>_<unit id>, findings state, alongside the classifier) for a statement
  denying it -> negative OMIT, normal DO NOT ASSERT AS NORMAL. Case-driven OMITs name no differential.
- IF_PRESENT (case): Jev finding reported + rc.route_finding -> KEEP on its own line (stated) / offered
  option (its paragraph's section) / DO NOT ASSERT / dropped; offers capped at MAX_FINDING_OPTIONS; a
  negative already handled (a sheet negative or an earlier If-present) is routed once, as in quick.
- RECOMMEND: rc.route_recommendation (Jev condition unmet + the impression plan) -> RECOMMEND / offered
  option (the impression section) / removed / DO NOT RECOMMEND (routine workup of an investigation),
  written in "## Recommendations (reconciled with this dictation)" before the Impression Plan, never in
  the reasoning block. A failed plan call offers IMAGING / TISSUE, never writes them.
COVERS lines are metadata (what a paragraph reports), not generator guidance: never in the brief.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from . import report_reconcile as rc
from .report_review import positive_items
from .template_sheet_structure import SheetStructure, _covers, _key

logger = logging.getLogger(__name__)

Q_CONDITION = "This statement is true for this case: "
Q_STATED = "The dictated findings state "
MET = rc.PRESENT

_IF_PRESENT_LINE = re.compile(r"^\s*(?:-\s+)?IF_PRESENT\b")
_H2 = re.compile(r"^#{1,2}\s")
_PARAGRAPH_HEADING = re.compile(r"^##\s+Paragraph:.*\(([^()]*)\)\s*$", re.I)
_SECTION_TAG = re.compile(r"\|\s*section:[^\"]*$")  # a Report-wide unit's explicit "| section: <NAME>"
_NORMAL_STUDY = re.compile(r"^###\s+Normal\s+study\s+(?:impression|conclusion)\s*:?\s*\n.*?(?=^#|\Z)",
                           re.M | re.S | re.I)
STATED = ("KEEP", "KEEP NORMAL")  # labels under which a unit's text is written in the report
_COVERS_LINE = re.compile(r"^\s*(?:-\s+)?COVERS\s*\[")
_CASE_HEADING = re.compile(r"^##\s+case\s+deliberation\s*$", re.I)
_CASE_KEYWORD = re.compile(r"^\s*(?:-\s+)?(QUESTION|DIFFERENTIAL|RECOMMEND)\b")

# Phase-2 case labels (pending owner sign-off with the TEMPLATE_SHEET_HEADER_BRIEF package).
CASE_HEADING = "## Case Deliberation (reconciled with this dictation)"
CASE_NOTE = ("Reasoning input only: the CLINICAL QUESTION, ADDRESS and OPEN lines guide your reasoning; never "
             "write them into the report.")
RECOMMENDATIONS_HEADING = "## Recommendations (reconciled with this dictation)"
CLINICAL_QUESTION = "- CLINICAL QUESTION: {question}"
ADDRESS = "- ADDRESS: {name} — the dictation reports it"
OPEN = "- OPEN: {name} — {discriminator}; {defer}"
OPEN_DEFER = {"no": "not assessable on this study: defer", "silent": "imaging-silent: defer"}
RECOMMEND = "- RECOMMEND: {text}"
DO_NOT_RECOMMEND = "- DO NOT RECOMMEND: {text}"
# A case-driven OMIT names no differential: the label sits in a findings paragraph the generator writes from.
CASE_OMIT_REASON = "a dictated finding makes this negative inapplicable"
NOT_VISIBLE_REASON = "this study cannot show what it would exclude"
Q_DENIES = "This report statement denies or excludes the following: {name} — {discriminator}. Statement: {text}"
_UNIT_LINE = re.compile(r"^\s*(?:-\s+)?(SECTION|NORMAL|NEGATIVE|FIXED|TERM|IF_PRESENT|RULE|COVERS|QUESTION|DIFFERENTIAL|"
                        r"RECOMMEND)\b")
# Denial questions per Jev call. Measured 2026-10-01 (synthetic statements, real Jev): one call of 20 / 40 /
# 80 / 160 questions p95 0.33 / 0.32 / 0.33 / 0.35 s; 4 parallel calls of 40 p95 0.49 s, of 80 p95 1.01 s.
# 80 is the largest size in the specified grid with p95 well under 3 s and headroom to JEV_TIMEOUT_S.
X_CHUNK = 80
X_BUDGET_WARN = 160  # above this, warn (never cap: every unit in scope is asked)
_WHEN = re.compile(r"\bWHEN\s*\[[^\]]*\]")


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


def _technique_text(sheet: str, s: SheetStructure) -> str:
    """The sheet's protocol text for context conditions: its "## Scan Context" block and the paragraphs of
    technique-role sections, prose and FIXED text only. Unit lines (a RULE, its WHEN condition, NEGATIVE,
    NORMAL …) never enter it, so no condition is judged against its own wording; never the findings."""
    technique = {x.name.upper() for x in s.sections if x.role == "technique"}
    out: List[str] = []
    inside = False
    for ln in sheet.splitlines():
        if _H2.match(ln):
            m = _PARAGRAPH_HEADING.match(ln)
            inside = (bool(m) and re.sub(r"\s+", " ", m.group(1)).strip().upper() in technique) \
                or ln.lstrip("#").strip().lower() == "scan context"
            continue
        if not inside or not ln.strip():
            continue
        unit = _UNIT_LINE.match(ln)
        if unit:
            if unit.group(1) == "FIXED":
                out.extend(re.findall(r'"([^"]+)"', ln))
            continue
        prose = _WHEN.sub("", ln).strip()
        if prose:
            out.append(prose)
    return "\n".join(out)


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

    def find(self, kind: str, pred) -> Optional[int]:
        """The first unclaimed line of this kind satisfying pred (units the structure holds no line for)."""
        taken = self.claimed.setdefault(kind, set())
        for i, ln in enumerate(self.lines):
            if i not in taken and pred(ln):
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
            elif not _IF_PRESENT_LINE.match(ln) and not _COVERS_LINE.match(ln):
                out.append(ln)
        return "\n".join(out)




@dataclass
class _Unit:
    """A NEGATIVE, stated-normal NEGATIVE or NORMAL unit, located on its sheet line."""
    kind: str  # "negative" | "stated_normal" | "normal"
    id: str
    text: str
    structure: str  # normals: the bracketed structure; stated normals: the paragraph name or section
    section: str
    paragraph: str  # paragraph id; "" = Report-wide
    explicit: bool  # a Report-wide unit tagged "| section: <NAME>"
    line: int
    extra_lines: List[int]
    jev_key: str  # c<k> conditional negative (None when unconditional), s<k> stated normal, m<i> normal
    condition: Optional[str] = None
    condition_source: str = "findings"
    origin: str = "template"  # "case": a Phase-1 unit of a master sheet
    targets: str = ""  # a case negative: the DIFFERENTIAL it helps exclude
    finding: str = ""  # an If-present unit: its finding
    tag: str = ""  # an If-present unit: core | contextual


def _explicit(source_line) -> bool:
    return isinstance(source_line, str) and bool(_SECTION_TAG.search(source_line))


def _target_in_bundle(target: str, bundle: str) -> bool:
    """An unsplit bundled negative ("No A or B") carrying the target claim ("No B")."""
    claim = rc._words(target) - rc._NEGATION
    return bool(claim) and rc._is_bundled(bundle) and claim <= rc._words(bundle)


def _scores(answers, asked: Dict[str, dict]) -> Dict[str, float]:
    """Jev's answer for every key asked, as a number; a missing or non-numeric answer fails the brief."""
    out: Dict[str, float] = {}
    for k in asked:
        v = answers.get(k) if isinstance(answers, dict) else None
        p = v.get("noul") if isinstance(v, dict) else None
        try:
            if isinstance(p, bool) or p is None:
                raise TypeError
            out[k] = float(p)
        except (TypeError, ValueError):
            raise ValueError(f"Jev answer for {k!r} is missing or non-numeric: {v!r}") from None
        if not math.isfinite(out[k]):
            raise ValueError(f"Jev answer for {k!r} is not finite")
    return out


def _check_qwen(qw: rc.QwenDecisions, n_negs: int, n_normals: int) -> None:
    idx = [d.index for d in qw.negatives]
    if len(idx) != n_negs or set(idx) != set(range(n_negs)):
        raise ValueError(f"Qwen negative decisions {sorted(idx)} do not cover exactly 0..{n_negs - 1}")
    if any(not 0 <= i < n_normals for i in qw.affected_normals):
        raise ValueError(f"Qwen affected normals {qw.affected_normals} outside 0..{n_normals - 1}")


def _pick(items: List[str], idx: List[int]) -> List[str]:
    return [items[i] for i in dict.fromkeys(idx) if 0 <= i < len(items)]


async def compile_template_brief(sheet: str, s: SheetStructure, scan_type: str, findings: str,
                                 clinical_history: str = "") -> rc.Brief:
    """The brief for one case. Raises when it cannot be trusted (see the module docstring): raw path."""
    if not s.usable:
        raise ValueError("template brief needs a usable sheet structure")
    t0 = time.monotonic()
    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    # History and context conditions are judged WITHOUT the dictated findings, so a condition mislabelled
    # history/context cannot be met by what the findings say. Context adds the sheet's protocol text.
    hist_state = f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY:\n{clinical_history or '(not given)'}"
    technique = _technique_text(sheet, s)
    ctx_state = hist_state + (f"\nPROTOCOL / TECHNIQUE:\n{technique}" if technique else "")
    items = rc.split_findings(findings)
    findings_section = next((x.name for x in s.sections if x.role == "findings"), "FINDINGS")
    imp_section = next((x.name for x in s.sections if x.role == "impression"), "IMPRESSION")
    para_name = {p.id: p.name for p in s.paragraphs}
    para_section = {p.id: p.section for p in s.paragraphs}

    # ── locate every unit on its own line (fail closed) ──────────────────────
    L = _Lines(sheet)

    def where(kind: str, refs: list, what: str) -> Tuple[int, List[int]]:
        found = [L.locate(kind, r) for r in refs]
        if not found or any(i is None for i in found):
            raise ValueError(f"template brief cannot locate {what} in the sheet")
        return found[0], found[1:]

    units: List[_Unit] = []
    for k, n in enumerate(s.negatives):
        line, extra = where("negative", list(n.source_lines), f"negative {n.id}")
        stated_normal = n.kind == "stated_normal"
        units.append(_Unit(kind=n.kind, id=n.id, text=n.text, section=n.section, paragraph=n.paragraph,
                           structure=(para_name.get(n.paragraph) or n.section) if stated_normal else "",
                           explicit=not n.paragraph and _explicit(n.source_lines[0]), line=line, extra_lines=extra,
                           jev_key=f"s{k}" if stated_normal else (f"c{k}" if n.condition else ""),
                           condition=None if stated_normal else n.condition, condition_source=n.condition_source,
                           origin=n.origin, targets=n.targets))
    for i, n in enumerate(s.normals):
        line, extra = where("normal", [n.source_line], f"normal {n.id}")
        units.append(_Unit(kind="normal", id=n.id, text=n.text, structure=n.structure, section=n.section,
                           paragraph=n.paragraph, explicit=not n.paragraph and _explicit(n.source_line),
                           line=line, extra_lines=extra, jev_key=f"m{i}"))
    rule_lines = [where("rule", list(r.source_lines), f"rule {r.id}") for r in s.rules]
    negatives = [u for u in units if u.kind == "negative"]
    normals = [u for u in units if u.kind != "negative"]

    # Case If-present units (the structure keeps no source line for them: found by finding and text).
    # Template-origin IF_PRESENT stays off (v1 sheets): never read, its lines removed.
    ifp_units: List[_Unit] = []
    for ip in s.if_present:
        if ip.origin != "case":
            continue
        for neg in ip.negatives:
            anchor = re.compile(r"IF_PRESENT\s*\[\s*" + re.escape(ip.finding) + r"\s*\]\s*\"" + re.escape(neg.text) + '"')
            line = L.find("if_present", lambda ln, anchor=anchor: bool(_IF_PRESENT_LINE.match(ln))
                          and bool(anchor.search(ln)))
            if line is None:
                raise ValueError(f"template brief cannot locate IF_PRESENT [{ip.finding}] in the sheet")
            ifp_units.append(_Unit(kind="if_present", id=f"ip{len(ifp_units)}", text=neg.text, structure="",
                                   section=ip.section, paragraph=ip.paragraph, explicit=False, line=line,
                                   extra_lines=[], jev_key="", origin="case", finding=ip.finding, tag=neg.tag))
    fkeys = list(dict.fromkeys(u.finding for u in ifp_units))

    # The Case Deliberation block's lines, in sheet order (the parser read them in this order).
    case_head: Optional[int] = None
    case_lines: Dict[str, List[int]] = {"QUESTION": [], "DIFFERENTIAL": [], "RECOMMEND": []}
    if s.question or s.differentials or s.recommendations:
        inside = False
        for i, ln in enumerate(L.lines):
            if _H2.match(ln):
                inside = bool(_CASE_HEADING.match(ln.strip()))
                if inside:
                    case_head = i
                continue
            m = _CASE_KEYWORD.match(ln) if inside else None
            if m:
                case_lines[m.group(1)].append(i)
        if case_head is None or len(case_lines["QUESTION"]) != (1 if s.question else 0) \
                or len(case_lines["DIFFERENTIAL"]) != len(s.differentials) \
                or len(case_lines["RECOMMEND"]) != len(s.recommendations) \
                or any(d.name not in L.lines[i] for d, i in zip(s.differentials, case_lines["DIFFERENTIAL"])) \
                or any(r.text not in L.lines[i] for r, i in zip(s.recommendations, case_lines["RECOMMEND"])):
            raise ValueError("template brief cannot locate the Case Deliberation units in the sheet")
    rec_text = [f"{r.tag}: {r.text} (when {r.condition})" for r in s.recommendations]

    # ── questions ────────────────────────────────────────────────────────────
    q_f: Dict[str, dict] = {}
    q_h: Dict[str, dict] = {}
    q_c: Dict[str, dict] = {}

    def bucket(source: str) -> Dict[str, dict]:
        return q_h if source == "history" else q_c if source == "context" else q_f
    for i, r in enumerate(s.rules):
        if r.effect == "list_missing":  # always evaluated: one question per item, findings state
            for j, item in enumerate(r.items):
                q_f[f"r{i}i{j}"] = {"type": "noul", "instructions": Q_STATED + item}
            continue
        bucket(r.condition_source)[f"r{i}"] = {
            "type": "noul", "instructions": Q_CONDITION + r.condition}
    for u in negatives:
        if u.condition:
            bucket(u.condition_source)[u.jev_key] = {
                "type": "noul", "instructions": Q_CONDITION + u.condition}
    for u in normals:
        q_f[u.jev_key] = {"type": "noul", "instructions": rc.Q_AFFECTED + u.text}
    for k, d in enumerate(s.differentials):
        q_f[f"d{k}"] = {"type": "noul", "instructions": f"{rc.Q_PRESENT}{d.name} — {d.discriminator}"}
    for i, f in enumerate(fkeys):
        q_f[f"f{i}"] = {"type": "noul", "instructions": rc.Q_FINDING + f}
    for k, t in enumerate(rec_text):
        q_f[f"rec{k}"] = {"type": "noul", "instructions": rc.Q_REC_UNMET + t}

    # One split call covers the sheet negatives and the case If-present negatives, as in quick.
    distinct: List[str] = []
    for u in negatives + ifp_units:
        if _key(u.text) not in {_key(t) for t in distinct}:
            distinct.append(u.text.strip().rstrip("."))

    async def plan_or_none():
        try:
            return await rc._plan(scan_type, clinical_history, items, rec_text,
                                  inclusion_logic=_section_body(sheet, "Impression Construction"))
        except Exception as e:  # the brief still compiles, without an Impression Plan
            logger.warning("template impression plan failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    async def fallback_or_none():
        try:
            return await rc._fallback(state, items, fkeys) if items else None
        except Exception as e:  # the brief still compiles; dictated findings just get no options
            logger.warning("template finding-negatives fallback failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    # Jev and the split first (Qwen is sent only the negatives that survive them); plan and fallback
    # run alongside throughout.
    plan_t = asyncio.ensure_future(plan_or_none())
    fb_t = asyncio.ensure_future(fallback_or_none())
    try:
        jev_f, jev_h, jev_c, split = await asyncio.gather(
            rc._jev(state, q_f) if q_f else asyncio.sleep(0, {}),
            rc._jev(hist_state, q_h) if q_h else asyncio.sleep(0, {}),
            rc._jev(ctx_state, q_c) if q_c else asyncio.sleep(0, {}),
            rc._split_bundled(distinct) if distinct else asyncio.sleep(0, []))
        sc = {**_scores(jev_f, q_f), **_scores(jev_h, q_h), **_scores(jev_c, q_c)}
        if len(split) != len(distinct):
            raise ValueError("negative split does not cover every negative")
        parts_of = {_key(t): [p for p in parts if p.strip()] or [t] for t, parts in zip(distinct, split)}

        # ── rules: met, and the sections they omit ───────────────────────────
        met = {i: sc[f"r{i}"] >= MET for i, r in enumerate(s.rules) if r.effect != "list_missing"}
        omitted = {r.target for i, r in enumerate(s.rules) if r.effect == "suppress_section" and met[i]}

        def unit_omitted(u: _Unit) -> bool:
            return u.section in omitted and (bool(u.paragraph) or u.explicit)

        def rule_omitted(i: int) -> bool:
            r = s.rules[i]
            if r.effect == "suppress_section" and r.target == r.section:
                return False
            return r.section in omitted and (bool(r.paragraph) or _explicit(r.source_lines[0]))

        def in_scope(r, u: _Unit) -> bool:
            return u.paragraph == r.paragraph if r.paragraph else u.section == r.section

        targeting = [i for i, r in enumerate(s.rules)
                     if r.effect in ("suppress", "replace") and r.target and met[i] and not rule_omitted(i)]
        para_suppressed = {r.paragraph: r.condition for i, r in enumerate(s.rules)
                           if r.effect == "suppress_paragraph_negatives" and r.paragraph and met[i]
                           and not rule_omitted(i)}
        suppressed_keys = {(para_section.get(u.paragraph), _key(u.text)): para_suppressed[u.paragraph]
                           for u in negatives if u.paragraph in para_suppressed and not unit_omitted(u)}
        target_hits: Dict[int, str] = {}  # rule -> "live" (a target unit renders its OMIT) | "omitted"

        def forced_parts(u: _Unit, parts: List[str]) -> Dict[int, int]:
            """part index -> the met SUPPRESS / REPLACE rule (in scope) that omits it."""
            out: Dict[int, int] = {}
            for i in targeting:
                r = s.rules[i]
                if not in_scope(r, u):
                    continue
                tk = _key(r.target)
                if tk == _key(u.text) or (u.kind == "negative" and len(parts) == 1 and _target_in_bundle(r.target, u.text)):
                    hit = list(range(len(parts)))
                else:
                    hit = [j for j, p in enumerate(parts) if _key(p) == tk] if u.kind == "negative" else []
                for j in hit:
                    out.setdefault(j, i)
                if hit:
                    target_hits[i] = "omitted" if unit_omitted(u) and target_hits.get(i) != "live" else "live"
            return out

        # ── differentials (policy 1, shared routing) ─────────────────────────
        diff_route = {d.name: rc.route_differential(sc[f"d{k}"], d.visible) for k, d in enumerate(s.differentials)}
        diff_visible = {d.name: d.visible for d in s.differentials}

        # ── plan each negative; collect what the classifier must judge ──────
        plans: Dict[str, dict] = {}
        to_classify: List[str] = []
        for u in negatives:
            parts = parts_of[_key(u.text)]
            forced = forced_parts(u, parts)
            p = {"parts": parts, "forced": forced, "status": "labelled"}
            if unit_omitted(u):
                p["status"] = "section_omitted"
            elif u.origin == "case" and diff_route.get(u.targets) == "present":
                p["status"] = "differential_present"  # the branch it helps exclude is reported: OMIT
            elif u.origin == "case" and diff_visible.get(u.targets) != "yes":
                p["status"] = "target_not_visible"  # lint blocks it; defence: silence cannot exclude it
            elif u.condition and sc[u.jev_key] < MET and not forced:
                p["status"] = "removed"
            elif u.paragraph in para_suppressed:
                p["status"] = "paragraph_suppressed"
                p["why"] = para_suppressed[u.paragraph]
            elif not u.paragraph and (u.section, _key(u.text)) in suppressed_keys:
                p["status"] = "paragraph_suppressed"
                p["why"] = suppressed_keys[(u.section, _key(u.text))]
            else:
                skip_unforced = bool(u.condition) and sc[u.jev_key] < MET  # unmet: only forced parts render
                for j, part in enumerate(parts):
                    if j not in forced and not skip_unforced and _key(part) not in {_key(x) for x in to_classify}:
                        to_classify.append(part)
                p["skip_unforced"] = skip_unforced
            plans[u.id] = p
        # A claim a case negative omits because its differential is reported: OMIT wherever it appears, whatever
        # became of that case negative itself (an omitted section still reports the differential).
        case_omit = {_key(part): u.targets for u in negatives
                     if u.origin == "case" and diff_route.get(u.targets) == "present"
                     for part in parts_of[_key(u.text)]}

        # ── case If-present: routed once each, after the sheet negatives (quick's "handled once") ──
        handled = {_key(part) for u in negatives
                   if plans[u.id]["status"] not in ("removed", "section_omitted") and not plans[u.id].get("skip_unforced")
                   for part in plans[u.id]["parts"]}
        cands: List[Tuple[_Unit, str, float]] = []  # (If-present unit, negative part, finding score)
        ifp_omitted: List[Tuple[_Unit, str]] = []
        ifp_case_omit: List[Tuple[_Unit, str]] = []
        for u in ifp_units:
            for part in parts_of[_key(u.text)]:
                if unit_omitted(u):
                    ifp_omitted.append((u, part))
                    continue
                if _key(part) in handled:
                    continue
                handled.add(_key(part))
                if _key(part) in case_omit:  # checked before route_finding: never stated nor offered
                    ifp_case_omit.append((u, part))
                    continue
                pf = sc[f"f{fkeys.index(u.finding)}"]
                cands.append((u, part, pf))
                if pf >= rc.PRESENT_LOW and _key(part) not in {_key(x) for x in to_classify}:
                    to_classify.append(part)  # an unreported finding drops its negatives whatever the label
        normal_plans: Dict[str, dict] = {}
        normals_sent: List[_Unit] = []
        for u in normals:
            forced = forced_parts(u, [u.text])
            if unit_omitted(u):
                status = "section_omitted"
            elif forced:
                status = "rule_omitted"
            elif u.paragraph in para_suppressed:
                status = "suppressed_by_rule"
            else:
                status = "judged"
                normals_sent.append(u)
            normal_plans[u.id] = {"status": status, "forced": forced}

        # Same claim, other wording: for each PRESENT differential, Jev reads every unit that could state its
        # absence in a findings-role section that is written (template negatives and normals, case negatives
        # targeting another differential, case If-present negatives of a reported finding) for a statement
        # that denies it. Asked alongside the classifier, in parallel chunks of X_CHUNK.
        # Known quality limit (R4): a NORMAL listing several structures is marked as a whole (DO NOT ASSERT AS
        # NORMAL) when one clause denies the differential; its other structures lose their normal wording.
        q_x: Dict[str, dict] = {}
        x_of: Dict[str, Tuple[_Unit, str]] = {}  # Jev key -> (unit, differential name)
        findings_sections = {x.name for x in s.sections if x.role == "findings"}
        reported_ifp = list({u.id: u for u, _, pf in cands if pf >= MET}.values())
        for k, d in enumerate(s.differentials):
            # Only a branch this study can show (VISIBLE yes) has an imaging discriminator a report statement
            # could deny; a present no/silent branch is never asked (e2e lab 2026-10-01).
            if diff_route[d.name] != "present" or d.visible != "yes":
                continue
            for u in negatives + normals + reported_ifp:
                if u.section not in findings_sections or unit_omitted(u):
                    continue
                if u.kind == "negative" and u.origin == "case" and (
                        u.targets == d.name or plans[u.id]["status"] == "differential_present"):
                    continue  # its own differential, or already OMIT
                key = f"x{k}_{u.id}"
                q_x[key] = {"type": "noul", "instructions": Q_DENIES.format(
                    name=d.name, discriminator=d.discriminator, text=u.text)}
                x_of[key] = (u, d.name)
        if len(q_x) > X_BUDGET_WARN:
            logger.warning("template brief: %d denial questions (> %d); asked in %d chunks", len(q_x),
                           X_BUDGET_WARN, -(-len(q_x) // X_CHUNK))

        async def qwen_or_empty():
            if to_classify or normals_sent:
                return await rc._qwen(state, to_classify, [u.text for u in normals_sent], [])
            return rc.QwenDecisions(negatives=[], affected_normals=[], applicable_measurements=[])

        keys_x = list(q_x)
        chunks = [{k: q_x[k] for k in keys_x[i:i + X_CHUNK]} for i in range(0, len(keys_x), X_CHUNK)]
        qw, *jev_x = await asyncio.gather(qwen_or_empty(), *(rc._jev(state, c) for c in chunks))
        _check_qwen(qw, len(to_classify), len(normals_sent))
        sx: Dict[str, float] = {}
        for c, answers in zip(chunks, jev_x):  # every chunk answered in full, or the brief fails
            sx.update(_scores(answers, c))
        denied: Dict[str, str] = {}  # unit id -> the present differential it denies
        for key, (u, name) in x_of.items():
            if sx[key] >= MET:
                denied.setdefault(u.id, name)
        plan, fb = await plan_t, await fb_t
    finally:
        for t in (plan_t, fb_t):
            if not t.done():
                t.cancel()

    qneg = {_key(to_classify[d.index]): d for d in qw.negatives}
    q_affected = {normals_sent[i].id for i in qw.affected_normals}
    decisions: dict = {"rules": [], "negatives": [], "normals": [], "missing": [], "finding_negatives": [],
                       "options": [], "conflicts": [], "impression_plan": None,
                       "question": s.question, "differentials": [], "recommendations": []}
    labels: List[Tuple[_Unit, str, str]] = []  # (unit, text key, label) for anchors and conflicts
    instead_done: Set[int] = set()

    def omit(text: str, i: int) -> List[str]:
        r = s.rules[i]
        out = [f'- OMIT: "{text}" — {r.condition}']
        if r.effect == "replace" and r.then_text and i not in instead_done:
            instead_done.add(i)
            out.append(f'- INSTEAD: "{r.then_text}"')
        return out

    # ── negatives ────────────────────────────────────────────────────────────
    for u in negatives:
        p = plans[u.id]
        for x in u.extra_lines:
            L.put(x, [])
        entry = {"id": u.id, "text": u.text, "paragraph": para_name.get(u.paragraph, ""), "origin": u.origin,
                 **({"targets": u.targets} if u.origin == "case" else {})}
        new: List[str] = []
        if p["status"] in ("section_omitted", "removed"):
            labels.extend((u, _key(part), "REMOVED") for part in p["parts"])
            extra = {"condition": u.condition, "score": round(sc[u.jev_key], 3)} if p["status"] == "removed" else {}
            L.put(u.line, [])
            decisions["negatives"].append({**entry, "action": p["status"], **extra, "lines": []})
            continue
        if p["status"] == "paragraph_suppressed":
            for part in p["parts"]:
                new.append(f'- OMIT: "{_q(part)}" — {p["why"]}')
                labels.append((u, _key(part), "RULE OMIT"))
            action = "paragraph_suppressed"
        elif p["status"] == "differential_present":
            for part in p["parts"]:
                new.append(f'- OMIT: "{_q(part)}" — {CASE_OMIT_REASON}')
                labels.append((u, _key(part), "OMIT"))
            action = "differential_present"
        elif p["status"] == "target_not_visible":
            for part in p["parts"]:
                if u.id in denied:  # it denies a present differential: the safer OMIT wins
                    new.append(f'- OMIT: "{_q(part)}" — {CASE_OMIT_REASON}')
                    labels.append((u, _key(part), "OMIT"))
                    decisions["conflicts"].append({
                        "text": _q(part), "winner": "OMIT", "differential": denied[u.id],
                        "source": "jev_denies_present_differential",
                        "labels": [{"origin": "case", "id": u.id, "label": "DO NOT ASSERT"},
                                   {"origin": "case", "label": "OMIT", "targets": denied[u.id]}]})
                else:
                    new.append(f'- DO NOT ASSERT: "{_q(part)}" — {NOT_VISIBLE_REASON}')
                    labels.append((u, _key(part), "DO NOT ASSERT"))
            action = "target_not_visible"
        else:
            for j, part in enumerate(p["parts"]):
                if j in p["forced"]:
                    new.extend(omit(_q(part), p["forced"][j]))
                    labels.append((u, _key(part), "RULE OMIT"))
                    continue
                if p["skip_unforced"]:
                    labels.append((u, _key(part), "REMOVED"))
                    continue
                d = qneg[_key(part)]
                if d.action != "contradicted" and (_key(part) in case_omit or u.id in denied):
                    # One label per claim, safer wins: the claim a case negative omits (same text), or a
                    # statement Jev reads as denying a present differential (other wording).
                    exact = _key(part) in case_omit
                    name = case_omit[_key(part)] if exact else denied[u.id]
                    lost = "DO NOT ASSERT" if d.action == "expected" else "KEEP"
                    decisions["conflicts"].append({
                        "text": _q(part), "winner": "OMIT", "differential": name,
                        "source": "case_negative_same_claim" if exact else "jev_denies_present_differential",
                        "labels": [{"origin": u.origin, "id": u.id, "label": lost},
                                   {"origin": "case", "label": "OMIT", "targets": name}]})
                    new.append(f'- OMIT: "{_q(part)}" — {CASE_OMIT_REASON}')
                    labels.append((u, _key(part), "OMIT"))
                elif d.action == "contradicted":
                    new.append(f'- OMIT: "{_q(part)}" — the dictation reports: {d.dictated_finding}')
                    labels.append((u, _key(part), "OMIT"))
                elif d.action == "expected":
                    new.append(f'- DO NOT ASSERT: "{_q(part)}" — expected consequence of: {d.dictated_finding}')
                    labels.append((u, _key(part), "DO NOT ASSERT"))
                else:
                    new.append(f'- KEEP: "{_q(part)}"')
                    labels.append((u, _key(part), "KEEP"))
            action = "rule_omitted" if p["forced"] and len(p["forced"]) == len(p["parts"]) else "labelled"
        L.put(u.line, new)
        decisions["negatives"].append({**entry, "action": action, "lines": new})

    # ── normals: kept verbatim, or never asserted (never deleted) ────────────
    for u in normals:
        p = normal_plans[u.id]
        for x in u.extra_lines:
            L.put(x, [])
        entry = {"id": u.id, "structure": u.structure, **({"kind": "stated_normal"} if u.kind == "stated_normal" else {})}
        status = p["status"]
        if status == "section_omitted":
            L.put(u.line, [])
            labels.append((u, _key(u.text), "REMOVED"))
            decisions["normals"].append({**entry, "action": status})
            continue
        if status == "rule_omitted":
            new = omit(u.text, p["forced"][0])
            label = "RULE OMIT"
        elif status == "suppressed_by_rule":  # SUPPRESS NEGATIVES: the paragraph is described from the dictation
            new, label = [f'- DO NOT ASSERT AS NORMAL [{u.structure}]: "{u.text}"'], "DO NOT ASSERT AS NORMAL"
        else:
            flagged = sc[u.jev_key] >= MET or u.id in q_affected
            if not flagged and u.id in denied:  # it states the absence of a present differential
                flagged = True
                decisions["conflicts"].append({
                    "text": u.text, "winner": "DO NOT ASSERT AS NORMAL", "differential": denied[u.id],
                    "source": "jev_denies_present_differential",
                    "labels": [{"origin": "template", "id": u.id, "label": "KEEP NORMAL"},
                               {"origin": "case", "label": "DO NOT ASSERT AS NORMAL", "targets": denied[u.id]}]})
            label = "DO NOT ASSERT AS NORMAL" if flagged else "KEEP NORMAL"
            new, status = [f'- {label} [{u.structure}]: "{u.text}"'], ("do_not_assert" if flagged else "keep")
        labels.append((u, _key(u.text), label))
        L.put(u.line, new)
        decisions["normals"].append({**entry, "score": round(sc[u.jev_key], 3), "qwen_affected": u.id in q_affected,
                                     "action": status})

    # ── case If-present (L-45 rule C, shared route_finding) ─────────────────
    n_offered = 0
    for u, part in ifp_omitted:
        decisions["finding_negatives"].append({"finding": u.finding, "text": part, "tag": u.tag, "qwen": "n/a",
                                               "present": None, "outcome": "section_omitted", "source": "case"})
    for u, part in ifp_case_omit:  # the claim a case negative omits (its differential is reported)
        L.put(u.line, [f'- OMIT: "{_q(part)}" — {CASE_OMIT_REASON}'])
        labels.append((u, _key(part), "OMIT"))
        decisions["finding_negatives"].append({"finding": u.finding, "text": part, "tag": u.tag, "qwen": "n/a",
                                               "present": None, "outcome": "differential_present",
                                               "source": "case", "differential": case_omit[_key(part)]})
    for u, part, pf in cands:
        if u.id in denied:  # checked before route_finding: it denies a present differential
            L.put(u.line, [f'- OMIT: "{_q(part)}" — {CASE_OMIT_REASON}'])
            labels.append((u, _key(part), "OMIT"))
            decisions["finding_negatives"].append({"finding": u.finding, "text": part, "tag": u.tag, "qwen": "n/a",
                                                   "present": round(pf, 3), "outcome": "denies_present_differential",
                                                   "source": "case", "differential": denied[u.id]})
            continue
        d = qneg.get(_key(part)) if pf >= rc.PRESENT_LOW else None
        label = d.action if d else "keep"
        outcome = rc.route_finding(label, pf, u.tag)
        if outcome == "offered":
            if n_offered >= rc.MAX_FINDING_OPTIONS:
                outcome = "dropped"
            else:
                n_offered += 1
                decisions["options"].append({
                    "kind": "finding_negative", "section": u.section, "paragraph": para_name.get(u.paragraph, ""),
                    "text": part, "finding": u.finding,
                    "reason": "contextual" if pf >= rc.PRESENT_HIGH else f"finding borderline (p={pf:.2f})"})
        decisions["finding_negatives"].append({"finding": u.finding, "text": part, "tag": u.tag, "qwen": label,
                                               "present": round(pf, 3), "outcome": outcome, "source": "case"})
        if outcome == "stated":
            L.put(u.line, [f'- KEEP: "{_q(part)}" (finding: {u.finding})'])
            labels.append((u, _key(part), "KEEP"))
        elif outcome == "do_not_assert":
            L.put(u.line, [f'- DO NOT ASSERT: "{_q(part)}" — expected consequence of: {d.dictated_finding}'])
            labels.append((u, _key(part), "DO NOT ASSERT"))
        # offered and dropped: the IF_PRESENT line is removed (render drops unedited IF_PRESENT lines)

    # ── Case Deliberation: question, differentials, recommendations ─────────
    rec_lines: List[str] = []
    if case_head is not None:
        L.put(case_head, [CASE_HEADING, CASE_NOTE])
        for i in case_lines["QUESTION"]:
            L.put(i, [CLINICAL_QUESTION.format(question=s.question)])
        for k, (d, i) in enumerate(zip(s.differentials, case_lines["DIFFERENTIAL"])):
            route = diff_route[d.name]
            if route == "present":
                L.put(i, [ADDRESS.format(name=d.name)])
            elif route == "open":
                L.put(i, [OPEN.format(name=d.name, discriminator=d.discriminator, defer=OPEN_DEFER[d.visible])])
            else:
                L.put(i, [])  # closed by silence: this study would show it
            decisions["differentials"].append({"id": d.id, "name": d.name, "tier": d.tier, "visible": d.visible,
                                               "present": round(sc[f"d{k}"], 3), "action": route})
        # Recommendations leave the reasoning block: kept / barred ones go to their own block before the
        # Impression Plan (report-bound guidance). With no plan (the call failed) an investigation is only
        # offered, never written; referral, MDT and correlation keep quick's Jev-alone behaviour.
        pdec = {d.index: d for d in plan.recommendations} if plan else {}
        for k, (r, i) in enumerate(zip(s.recommendations, case_lines["RECOMMEND"])):
            d = pdec.get(k)
            if plan is None and f"{r.tag}:" in rc._BAR_KINDS:
                d = rc.RecDecision(index=k, decision="optional", reason="impression plan unavailable")
            route = rc.route_recommendation(sc[f"rec{k}"], d, tag=r.tag,
                                            room=len(decisions["options"]) < rc.MAX_OPTIONS)
            L.put(i, [])
            if route == "keep":
                rec_lines.append(RECOMMEND.format(text=r.text))
            elif route == "do_not_recommend":
                rec_lines.append(DO_NOT_RECOMMEND.format(text=r.text))
            else:
                if route == "optional":
                    decisions["options"].append({"kind": "recommendation", "section": imp_section,
                                                 "text": f"{r.tag}: {r.text}", "reason": d.reason})
            decisions["recommendations"].append({"id": r.id, "tag": r.tag, "text": r.text, "action": route,
                                                 "unmet": round(sc[f"rec{k}"], 3), "reason": d.reason if d else ""})

    # ── rules ────────────────────────────────────────────────────────────────
    for i, r in enumerate(s.rules):
        line, extra = rule_lines[i]
        for x in extra:
            L.put(x, [])
        entry = {"id": r.id, "effect": r.effect, "condition": r.condition, "source": r.condition_source}
        if rule_omitted(i):
            L.put(line, [])
            decisions["rules"].append({**entry, "met": met.get(i), "score": round(sc.get(f"r{i}", 0.0), 3),
                                       "action": "section_omitted"})
            continue
        if r.effect == "list_missing":
            missing = [item for j, item in enumerate(r.items) if sc[f"r{i}i{j}"] < MET]
            pos = "end" if r.position == "end" else "top"
            L.put(line, [f"- MISSING (list at {pos}): " + ", ".join(missing)] if missing else [])
            decisions["missing"].append({"id": r.id, "items": r.items, "missing": missing, "position": pos})
            decisions["rules"].append({**entry, "met": bool(missing), "score": None,
                                       "action": "listed" if missing else "removed"})
            continue
        new: List[str] = []
        action = "applied" if met[i] else "removed"
        if met[i]:
            if r.effect in ("suppress", "replace"):
                hit = target_hits.get(i)
                if hit is None:  # the target is no unit in scope: the OMIT sits on the rule's line
                    new = omit(r.target, i)
                elif hit == "omitted":
                    action = "target_omitted"
                    logger.info("template brief: rule %s dropped, its target is only in an omitted section", r.id)
            elif r.effect == "append":
                new = [f'- APPLY: "{r.then_text}"']
            elif r.effect == "use":
                new = [f'- USE: "{r.then_text}"']
            elif r.effect == "insert_before":
                anchors = [lab for u, k, lab in labels if in_scope(r, u) and k == _key(r.anchor)]
                if anchors and not any(lab in STATED for lab in anchors):
                    action = "anchor_removed"
                    logger.info("template brief: rule %s dropped, its anchor is not stated", r.id)
                else:
                    new = [f'- INSERT: "{r.then_text}" BEFORE "{r.anchor}"']
            elif r.effect == "suppress_paragraph_negatives":
                new = ["- DESCRIBE FROM DICTATION: this paragraph's normal wording does not apply"]
            elif r.effect == "suppress_section":
                new = [f"- OMIT SECTION: {r.target} — {r.condition}"]
            elif r.effect == "suppress_headers":
                new = [f"- NO PARAGRAPH HEADERS — {r.condition}"]
            elif r.effect == "order":
                new = [f"- PLACE THIS PARAGRAPH {(r.position or 'first').upper()} — {r.condition}"]
        L.put(line, new)
        decisions["rules"].append({**entry, "met": met[i], "score": round(sc[f"r{i}"], 3), "action": action})

    # Same text omitted by a rule in one place and kept in another: allowed (scope), but made visible.
    def place(u: _Unit) -> str:
        return para_name.get(u.paragraph) or f"Report-wide ({u.section})"

    by_key: Dict[str, List[Tuple[_Unit, str]]] = {}
    for u, k, lab in labels:
        by_key.setdefault(k, []).append((u, lab))
    for k, seen in by_key.items():
        omitted_in = [u for u, lab in seen if lab == "RULE OMIT"]
        kept_in = [u for u, lab in seen if lab in STATED]
        if omitted_in and kept_in:
            decisions["conflicts"].append({"text": omitted_in[0].text if _key(omitted_in[0].text) == k else k,
                                           "omitted_in": [place(u) for u in omitted_in],
                                           "kept_in": [place(u) for u in kept_in]})

    # An omitted section's paragraph shells (heading and prose) go too; the OMIT SECTION line stays.
    L.drop_paragraphs(omitted)
    text = L.render()

    # Normal-study impression: dropped when anything positive is dictated.
    if positive_items(findings):
        text = _NORMAL_STUDY.sub("", text)
    if rec_lines:
        text = text.rstrip() + "\n\n" + RECOMMENDATIONS_HEADING + "\n" + "\n".join(rec_lines)

    # ── impression plan and options ─────────────────────────────────────────
    if plan and items:
        carry, only = _pick(items, plan.impression), _pick(items, plan.findings_only)
        room = max(0, rc.MAX_OPTIONS - len(decisions["options"]))
        opt = [t for t in _pick(items, plan.optional_impression) if t not in carry][:room]
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
        seen_neg = {_key(part) for _, part, _ in cands}
        for it in fb.items:
            if it.covered or it.index not in plan.impression or not (0 <= it.index < len(items)):
                continue
            for neg in it.negatives[:3]:
                neg = neg.strip().rstrip(".")
                if neg and _key(neg) not in seen_neg and n_offered < rc.MAX_FINDING_OPTIONS:
                    seen_neg.add(_key(neg))
                    n_offered += 1
                    decisions["options"].append({"kind": "finding_negative", "section": findings_section, "text": neg,
                                                 "finding": items[it.index], "reason": "unanticipated finding"})
                    decisions["finding_negatives"].append({"finding": items[it.index], "text": neg,
                                                           "outcome": "offered", "source": "fallback"})

    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return rc.Brief(text=text, decisions=decisions, reconcile_ms=int((time.monotonic() - t0) * 1000))
