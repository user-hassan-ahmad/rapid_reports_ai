"""Shared post-generation check: Jev flags contradictions and omissions, focal repairs fix them.
Used by both pathways (spec 2026-09-30-template-pipeline-mirror-design §4).

Spec docs/superpowers/specs/2026-09-30-post-generation-check-design.md; probe ledger L-46.

    units   -> report clauses, option sentences, positive dictated items (code)
    check   -> two Jev calls in parallel: contradiction (dictation state), omission (report state)
    repair  -> one Qwen call returns verbatim find/replace edits; code applies each only when its
               find occurs exactly once
Flagged options are dropped, never repaired. Nothing here raises: on any failure the report and
options ship as generated, with the reason in the telemetry.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import List, Optional, Tuple

from pydantic import BaseModel, field_validator

from . import report_reconcile as rc
from .enhancement_utils import _run_agent_with_model

logger = logging.getLogger(__name__)

Q_CONTRA = "The dictated findings state something that this report statement denies or contradicts. Statement: "
Q_OMIT = "The report states this dictated finding, in any wording: "
Q_RESTATED = "The dictated findings report this finding: "
CONTRA_FLAG = 0.6   # L-46: 31/31 genuine contradictions >= 0.5, 29/31 >= 0.7
RESTATED_FLAG = 0.5  # a report negative is removed only when the finding it denies is dictated (L-47)
OMIT_FLAG = 0.5     # L-46: 24/24 deleted findings < 0.5
JEV_TIMEOUT_S = 6.0
REPAIR_TIMEOUT_S = 8.0
REPAIR_MODEL = rc.QWEN

# ── units ────────────────────────────────────────────────────────────────────

_HEADER = re.compile(r"^([A-Z][A-Z /&()-]{2,}):\s*$", re.M)


def report_sections(report: str) -> Tuple[str, str]:
    """FINDINGS and IMPRESSION text; the impression stops at the signature's blank line."""
    parts, marks = {}, list(_HEADER.finditer(report))
    for m, nxt in zip(marks, marks[1:] + [None]):
        parts[m.group(1)] = report[m.end():nxt.start() if nxt else len(report)].strip()
    imp = re.split(r"\n\s*\n", parts.get("IMPRESSION", ""), maxsplit=1)[0].strip()
    return parts.get("FINDINGS", ""), imp


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", text) if len(s.strip()) > 3]


def clauses(text: str) -> List[str]:
    """Sentences, with a negative list split at its commas into one clause per finding. A bare
    'or' never splits: 'No pericolic or paracolic fluid collection' is one finding (L-46)."""
    out: List[str] = []
    for s in _sentences(text):
        m = re.match(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", s, re.I)
        parts = [p.strip() for p in re.split(r",\s*(?:or\s+|and\s+)?", m.group(2)) if p.strip()] if m else []
        out.extend(f"No {p}" for p in parts) if len(parts) > 1 else out.append(s)
    return out


_RESTATE = re.compile(r"^(?:No|There is no|There are no|Without)\s+(.*?)(?:\s+(?:is|are|was|were))?(?:\s+(?:identified|seen|present|demonstrated|noted))?\.?$", re.I)


def restate(clause: str) -> Optional[str]:
    """The finding a negative clause denies ('No X is identified.' -> 'X'); None for a positive."""
    m = _RESTATE.match(clause.strip())
    return m.group(1).strip() if m else None


_BACKGROUND = re.compile(r"^\s*(no|nil)\b|\b(unremarkable|normal|intact|clear)\b", re.I)


def positive_items(findings: str) -> List[str]:
    """Dictated positive findings; negatives and background lines are not checked for omission (L-46)."""
    return [t for t in rc.split_findings(findings) if not _BACKGROUND.search(t)]


def header_names(report: str) -> List[str]:
    """Ordered section headings of a quick report (FINDINGS:, IMPRESSION:, …)."""
    return [m.group(1) for m in _HEADER.finditer(report)]


class ReportSection(BaseModel):
    name: str
    header: Optional[str] = None      # as written in reports; None = implicit (no header line)
    role: str = "other"               # history|technique|comparison|findings|impression|other


CHECKED_ROLES = {"findings", "impression", "other"}


def section_spans(report: str, sections: List[ReportSection]) -> List[Tuple[ReportSection, int, int]]:
    """(section, start, end) for each section found, in sheet order. A headed section starts after
    its header line and ends at the next header found, or, when the next section is implicit, at
    its first paragraph break; an implicit section covers the text from the previous section's end
    (or the top) to the next header."""
    found: List[Tuple[ReportSection, Optional[int], Optional[int]]] = []
    pos = 0
    for sec in sections:
        if sec.header:
            pat = re.compile(rf"^[ \t]*{re.escape(sec.header.strip().rstrip(':'))}[ \t]*:?[ \t]*$", re.M | re.I)
            m = pat.search(report, pos)
            if not m:
                continue
            found.append((sec, m.start(), m.end()))
            pos = m.end()
        else:
            found.append((sec, None, None))
    header_starts = sorted(h for _, h, _ in found if h is not None)
    out: List[Tuple[ReportSection, int, int]] = []
    prev_end = 0
    for idx, (sec, h, c) in enumerate(found):
        start = c if c is not None else prev_end
        nxt = next((x for x in header_starts if x >= start and (h is None or x > h)), len(report))
        if c is not None and idx + 1 < len(found) and found[idx + 1][1] is None:
            body = re.search(r"\S", report[start:nxt])
            brk = re.search(r"\n[ \t]*\n", report[start + body.start():nxt]) if body else None
            if brk:
                nxt = start + body.start() + brk.start()
        out.append((sec, start, nxt))
        prev_end = nxt
    return out


def _checked_texts(report: str, sections: Optional[List[ReportSection]]) -> List[str]:
    """The report text the check reads: FINDINGS + IMPRESSION (quick), or every section whose role
    carries dictated content (templates)."""
    if sections is None:
        return list(report_sections(report))
    return [report[a:b].strip() for s, a, b in section_spans(report, sections) if s.role in CHECKED_ROLES]


def checked_clauses(report: str, sections: Optional[List[ReportSection]]) -> List[str]:
    """Clauses the contradiction check reads. Quick (no sections): FINDINGS + IMPRESSION as before.
    Templates: every section whose role carries dictated content."""
    return list(dict.fromkeys(c for t in _checked_texts(report, sections) for c in clauses(t)))


def without(report: str, protected: List[str]) -> str:
    """The report with protected text (history section, fixed blocks) removed."""
    for p in protected:
        if p:
            report = report.replace(p, "")
    return report


def _in_protected(text: str, protected: Optional[List[str]]) -> bool:
    return any(p and text in p for p in protected or [])


def _has_term(text: str, terms: Optional[List[str]]) -> bool:
    return any(t and re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in terms or [])


# ── check ────────────────────────────────────────────────────────────────────

class Flag(BaseModel):
    kind: str          # "contradiction" | "omission"
    text: str          # the report clause, or the dictated item missing from the report
    score: float


class CheckResult(BaseModel):
    flags: List[Flag] = []
    bad_option_ids: List[str] = []
    n_clauses: int = 0
    n_items: int = 0
    error: Optional[str] = None


async def check(report: str, findings: str, scan_type: str, options: List[dict],
                sections: Optional[List[ReportSection]] = None, protected: Optional[List[str]] = None) -> CheckResult:
    """Two Jev calls in parallel: every checked report clause and option against the dictation,
    every positive dictated item against the report (protected text removed)."""
    cls = checked_clauses(report, sections)
    opts = [(o["id"], o["sentence"]) for o in options if o.get("sentence")]
    items = positive_items(findings)
    contra_qs = {f"c{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, t in enumerate(cls)}
    contra_qs.update({f"o{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, (_, t) in enumerate(opts)})
    # A report negative is removed only if the finding it denies is itself dictated: Jev over-flags
    # negatives that share words with a dictated finding (L-47: 'No irregular asymmetric wall
    # thickening' beside dictated segmental wall thickening). Same call, no added latency.
    restated = {i: restate(t) for i, t in enumerate(cls)}
    contra_qs.update({f"r{i}": {"type": "noul", "instructions": Q_RESTATED + r} for i, r in restated.items() if r})
    omit_qs = {f"i{i}": {"type": "noul", "instructions": Q_OMIT + t} for i, t in enumerate(items)}

    async def ask(state, qs):
        return await rc._jev(state, qs) if qs else {}
    try:
        contra, omit = await asyncio.wait_for(asyncio.gather(
            ask(f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
            ask(f"REPORT:\n{without(report, protected or [])}", omit_qs)), JEV_TIMEOUT_S)
    except Exception as e:  # never blocks the report
        logger.warning("quality check: Jev failed (%s: %s)", type(e).__name__, str(e)[:200])
        return CheckResult(n_clauses=len(cls), n_items=len(items), error=f"{type(e).__name__}: {str(e)[:200]}")

    score = lambda ans, k: float(ans[k]["noul"])
    flags = [Flag(kind="contradiction", text=t, score=score(contra, f"c{i}"))
             for i, t in enumerate(cls) if score(contra, f"c{i}") >= CONTRA_FLAG
             and (not restated[i] or score(contra, f"r{i}") >= RESTATED_FLAG)]
    flags += [Flag(kind="omission", text=t, score=score(omit, f"i{i}"))
              for i, t in enumerate(items) if score(omit, f"i{i}") < OMIT_FLAG]
    bad = [oid for i, (oid, _) in enumerate(opts) if score(contra, f"o{i}") >= CONTRA_FLAG]
    return CheckResult(flags=flags, bad_option_ids=bad, n_clauses=len(cls), n_items=len(items))


# ── repair ───────────────────────────────────────────────────────────────────

class Edit(BaseModel):
    find: str
    replace: str


class RepairEdits(BaseModel):
    edits: List[Edit]
    @field_validator("edits", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return rc._unstring(v)


class RepairResult(BaseModel):
    report: str
    applied: int = 0
    skipped: int = 0
    error: Optional[str] = None


REPAIR_SYS = (
    "You correct specific problems in a radiology report. The dictated findings are the source of truth. For each "
    "numbered problem return one edit: 'find' is text copied exactly, character for character, from the report (the "
    "clause or sentence at fault, or the sentence an omitted finding belongs beside), and 'replace' is that text "
    "corrected. Remove or correct a statement the dictation contradicts; add an omitted dictated finding in the "
    "report's own voice where it belongs. Change nothing else, keep British English, and add nothing that was not "
    "dictated. Return JSON {\"edits\": [{\"find\": ..., \"replace\": ...}]}.")


_NEGATION = re.compile(r"\b(no|not|without|nor|absent|negative for)\b", re.I)
INSERT_ONLY_SYS = (" Each problem is an omitted finding: 'replace' must contain 'find' unchanged, with the omitted "
                   "finding added to it.")


def edit_allowed(e: Edit, insert_only: bool, protected: Optional[List[str]] = None,
                 suppressed: Optional[List[str]] = None) -> bool:
    """A repair never turns a negated statement into an assertion (L-47: a flagged negative was
    'corrected' into the malignant finding it denied), an insertion never rewrites text, protected
    text (history section, fixed blocks) is never edited, and a repair never introduces a term the
    sheet suppresses."""
    if not e.find or e.find == e.replace:
        return False
    if _NEGATION.search(e.find) and not _NEGATION.search(e.replace):
        return False
    if any(p and (e.find in p or p in e.find) for p in protected or []):
        return False
    for term in suppressed or []:
        pat = re.compile(rf"\b{re.escape(term)}\b", re.I)
        if term and pat.search(e.replace) and not pat.search(e.find):
            return False
    return not insert_only or e.find in e.replace


async def repair_report(report: str, findings: str, problems: List[str], insert_only: bool = False,
                        protected: Optional[List[str]] = None, suppressed: Optional[List[str]] = None) -> RepairResult:
    """One focal Qwen call; each returned edit is applied only when allowed and its find occurs
    exactly once. Shared by the post-generation check and (next) the audit's Fix with AI."""
    user = (f"DICTATED FINDINGS:\n{findings}\n\nREPORT:\n{report}\n\nPROBLEMS:\n"
            + "\n".join(f"{i}. {p}" for i, p in enumerate(problems, 1)))
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=REPAIR_MODEL, output_type=RepairEdits,
            system_prompt=REPAIR_SYS + (INSERT_ONLY_SYS if insert_only else ""), user_prompt=user, api_key="",
            model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "none"}), REPAIR_TIMEOUT_S)
    except Exception as e:  # never blocks the report
        logger.warning("quality repair failed (%s: %s)", type(e).__name__, str(e)[:200])
        return RepairResult(report=report, error=f"{type(e).__name__}: {str(e)[:200]}")
    out, applied, skipped = report, 0, 0
    for e in r.output.edits:
        if edit_allowed(e, insert_only, protected, suppressed) and out.count(e.find) == 1:
            out, applied = out.replace(e.find, e.replace), applied + 1
        else:
            skipped += 1
    return RepairResult(report=out, applied=applied, skipped=skipped)


# ── omitted findings: Qwen writes the sentence, code inserts it ──────────────

class Insertion(BaseModel):
    after: str       # an existing report sentence, copied exactly
    sentence: str    # the omitted finding, one sentence in the report's voice


class Insertions(BaseModel):
    items: List[Insertion]
    @field_validator("items", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return rc._unstring(v)


INSERT_SYS = (
    "A radiology report left out some dictated findings. For each numbered omitted finding write one sentence stating "
    "it in the report's own voice, using only what was dictated, and choose the report sentence it should follow: "
    "copy that sentence exactly into 'after'. Return JSON {\"items\": [{\"after\": ..., \"sentence\": ...}]}.")


_FILLER = {"incidental", "noted", "identified", "seen", "present", "demonstrated", "there", "which", "with",
           "that", "this", "also", "further", "additional", "note"}


def _restates(new: str, existing: str) -> bool:
    """`new` says nothing `existing` does not: nearly all its words, and every number, are there."""
    words = lambda t: set(re.findall(r"[a-z]{4,}", t.lower())) - _FILLER
    w = words(new)
    nums = set(re.findall(r"\d+(?:\.\d+)?", new))
    return bool(w) and len(w & words(existing)) >= 0.8 * len(w) \
        and nums <= set(re.findall(r"\d+(?:\.\d+)?", existing))


async def insert_findings(report: str, findings: str, items: List[str],
                          sections: Optional[List[ReportSection]] = None, protected: Optional[List[str]] = None,
                          suppressed: Optional[List[str]] = None) -> RepairResult:
    """Insertion by construction: the report's existing text is never rewritten (L-47: asked for
    insert-only edits, Qwen rewrote the neighbouring sentence). An anchor that is not found places
    the sentence first in FINDINGS, where the primary finding belongs."""
    user = (f"DICTATED FINDINGS:\n{findings}\n\nREPORT:\n{report}\n\nOMITTED FINDINGS:\n"
            + "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1)))
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=REPAIR_MODEL, output_type=Insertions, system_prompt=INSERT_SYS, user_prompt=user, api_key="",
            model_settings={"temperature": 0, "max_tokens": 2000, "reasoning_effort": "none"}), REPAIR_TIMEOUT_S)
    except Exception as e:  # never blocks the report
        logger.warning("quality insert failed (%s: %s)", type(e).__name__, str(e)[:200])
        return RepairResult(report=report, error=f"{type(e).__name__}: {str(e)[:200]}")
    out, applied, skipped = report, 0, 0
    for it in r.output.items:
        sent = it.sentence.strip()
        if not sent or _NEGATION.search(sent) and not any(_NEGATION.search(t) for t in items):
            skipped += 1
            continue
        if _has_term(sent, suppressed):
            skipped += 1   # the sheet suppresses this wording
            continue
        sent = sent if sent.endswith(".") else sent + "."
        if any(_restates(sent, x) for x in _sentences(out)):
            skipped += 1   # already stated in other words (L-47: a reworded finding was re-inserted)
            continue
        if it.after and out.count(it.after) == 1 and not _in_protected(it.after, protected):
            out = out.replace(it.after, f"{it.after} {sent}", 1)
        else:
            fnd = next((out[a:b].strip() for s, a, b in section_spans(out, sections) if s.role == "findings"), "") \
                if sections else report_sections(out)[0]
            first = _sentences(fnd)[0] if fnd else None
            if not first or out.count(first) != 1:
                skipped += 1
                continue
            out = out.replace(first, f"{sent} {first}", 1)
        applied += 1
    return RepairResult(report=out, applied=applied, skipped=skipped)


# ── deterministic removal of a flagged negative ─────────────────────────────

_NEG_LIST = re.compile(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", re.I)


def is_negative(clause: str) -> bool:
    return bool(_NEG_LIST.match(clause.strip()))


def remove_negative_clause(report: str, clause: str, sections: Optional[List[ReportSection]] = None) -> str:
    """Take one flagged negative out of the report without asserting anything: a whole negative
    sentence is deleted; one item of a negative list is dropped from the list. No LLM, so a false
    flag can only lose a negative, never create a finding."""
    target = clause.strip().rstrip(".")
    for s in [x for t in _checked_texts(report, sections) for x in _sentences(t)]:
        if s.rstrip(".") == target:
            return re.sub(r"[ \t]*" + re.escape(s) + r"[ \t]*", " ", report, count=1).replace(" \n", "\n")
        m = _NEG_LIST.match(s)
        if not m:
            continue
        parts = [p.strip() for p in re.split(r",\s*(?:or\s+|and\s+)?", m.group(2)) if p.strip()]
        if len(parts) < 2 or target not in (f"No {p}" for p in parts):
            continue
        rest = [p for p in parts if f"No {p}" != target]
        conj = "and" if re.search(r",\s*and\s+", m.group(2)) else "or"
        body = rest[0] if len(rest) == 1 else (f"{rest[0]} {conj} {rest[1]}" if len(rest) == 2
                                                  else ", ".join(rest[:-1]) + f", {conj} {rest[-1]}")
        return report.replace(s, f"{m.group(1)} {body}.", 1)
    return report


# ── orchestration ────────────────────────────────────────────────────────────

def enabled() -> bool:
    """Kill switch: RR_QUALITY_CHECK=0 ships reports exactly as generated."""
    return os.environ.get("RR_QUALITY_CHECK", "1").strip() not in ("0", "false", "off")


def _diff_edits(before: str, after: str) -> List[Tuple[str, str]]:
    """The changed spans between two versions, as (old, new) pairs with a little context."""
    import difflib
    sm = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        lo = max(0, i1 - 40)
        out.append((before[lo:i2], before[lo:i1] + after[j1:j2]))
    return out


def _problem(f: Flag) -> str:
    if f.kind == "contradiction":
        return f'The report states "{f.text}", which the dictated findings contradict.'
    return f'The dictated finding "{f.text}" is missing from the report.'


async def run_quality_check(report: str, findings: str, scan_type: str, options: List[dict],
                            sections: Optional[List[ReportSection]] = None, protected: Optional[List[str]] = None,
                            suppressed: Optional[List[str]] = None) -> Tuple[str, List[dict], dict]:
    """Check, then repair only when a report clause or item is flagged. Returns the report, the
    options with flagged ones dropped, and telemetry. Never raises. `sections` makes the check
    section-generic (templates); `protected` text is never checked for omission or edited; a repair
    never introduces a `suppressed` term. All default to the quick behaviour."""
    if not enabled():
        return report, options, {"enabled": False}
    t0 = time.time()
    tel: dict = {"enabled": True, "flags": [], "clauses_removed": 0, "edits_applied": 0, "edits_skipped": 0, "options_dropped": [],
                 "clauses": 0, "items": 0, "jev_ms": None, "repair_ms": None, "error": None}
    try:
        # The template-only arguments are passed only when set, so the quick call is unchanged.
        opt = lambda **kw: {k: v for k, v in kw.items() if v is not None}
        res = await check(report, findings, scan_type, options, **opt(sections=sections, protected=protected))
        tel.update(flags=[f.model_dump() for f in res.flags], clauses=res.n_clauses, items=res.n_items,
                   jev_ms=int((time.time() - t0) * 1000), error=res.error, options_dropped=res.bad_option_ids)
        options = [o for o in options if o.get("id") not in set(res.bad_option_ids)]
        # A flagged negative is removed in code; a flagged positive statement is corrected, and an
        # omitted finding inserted, by Qwen under edit_allowed (L-47).
        # A contradiction inside protected text stays in tel["flags"] for the rail but is never edited.
        editable = [f for f in res.flags
                    if not (f.kind == "contradiction" and _in_protected(f.text.rstrip("."), protected))]
        removed = 0
        for f in editable:
            if f.kind == "contradiction" and is_negative(f.text):
                new = remove_negative_clause(report, f.text, **opt(sections=sections))
                removed += new != report
                report = new
        tel["clauses_removed"] = removed
        fix = [_problem(f) for f in editable if f.kind == "contradiction" and not is_negative(f.text)]
        if fix or any(f.kind == "omission" for f in editable):
            t1 = time.time()
            omitted = [f.text for f in editable if f.kind == "omission"]
            calls = ([repair_report(report, findings, fix, **opt(protected=protected, suppressed=suppressed))]
                     if fix else []) + \
                    ([insert_findings(report, findings, omitted,
                                      **opt(sections=sections, protected=protected, suppressed=suppressed))]
                     if omitted else [])
            reps = await asyncio.gather(*calls)
            base, report = report, reps[0].report
            for rep in reps[1:]:   # both were made from the same base: replay the second's changes
                for old_s, new_s in _diff_edits(base, rep.report):
                    if report.count(old_s) == 1:
                        report = report.replace(old_s, new_s)
            tel.update(edits_applied=sum(r.applied for r in reps), edits_skipped=sum(r.skipped for r in reps),
                       repair_ms=int((time.time() - t1) * 1000),
                       error=next((r.error for r in reps if r.error), None) or tel["error"])
    except Exception as e:  # never blocks the report
        logger.warning("quality check failed (%s: %s)", type(e).__name__, str(e)[:200])
        tel["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return report, options, tel
