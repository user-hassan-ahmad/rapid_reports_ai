"""Post-generation check: Jev flags contradictions and omissions, one focal Qwen call repairs them.

Spec docs/superpowers/specs/2026-09-30-post-generation-check-design.md; probe ledger L-46.

    units   -> report clauses, option sentences, every dictated item (code); a Jev selector
               keeps omission flags only on abnormal / limitation / mixed lines
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

from . import quick_report_brief as qb
from .enhancement_utils import _run_agent_with_model

logger = logging.getLogger(__name__)

Q_CONTRA = "The dictated findings state something that this report statement denies or contradicts. Statement: "
Q_RESTATED = "The dictated findings report this finding, including as a possibility: "


def q_restated(finding: str) -> dict:
    """Removal confirmation for a flagged report negative (Jev wording v2, group B S1, L-49): a finding
    dictated only as a possibility still confirms the removal."""
    return {"type": "noul", "instructions": Q_RESTATED + finding,
            "criteria": {"true": "This same finding is reported, in any wording (synonym, abbreviation, or a more specific "
                                 "form of it), as present or possible.",
                         "false": "It is not mentioned, is stated as absent or normal, or the dictation reports a different "
                                  "finding that only shares some words with it (a different qualifier such as size, "
                                  "severity, pattern, chronicity or location)."}}
CONTRA_FLAG = 0.6   # L-46: 31/31 genuine contradictions >= 0.5, 29/31 >= 0.7
RESTATED_FLAG = 0.5  # a report negative is removed only when the finding it denies is dictated (L-47)
# One wording for "is it already in the report?" (Jev wording v2, group A S2, L-49). Thresholds differ per use.
Q_CONVEYS = ("The report itself states everything this statement says, in any wording, abbreviation or synonym "
             "(not merely implied or inferable): ")
OMIT_FLAG = 0.40    # L-49: omission flagged below 0.40 (stated >= 0.51, omitted <= 0.31)
INSERT_DUP = 0.25   # L-49: an inserted sentence is skipped at >= 0.25 (conveyed >= 0.32, new <= 0.14)
JEV_TIMEOUT_S = 6.0
REPAIR_TIMEOUT_S = 8.0
REPAIR_MODEL = qb.QWEN

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


def dictated_items(findings: str) -> List[str]:
    """Every dictated item; each is asked the conveys question, and the selector decides which flags count."""
    return qb.split_findings(findings)


_BACKGROUND = re.compile(r"^\s*(no|nil)\b|\b(unremarkable|normal|intact|clear)\b", re.I)


def positive_items(findings: str) -> List[str]:
    """The regex selection (L-46): negatives and background lines are not checked for omission. Now the
    fallback when the Jev selector cannot answer for an item."""
    return [t for t in dictated_items(findings) if not _BACKGROUND.search(t)]


# Omission selector (Jev wording v2, group F, L-49): only lines that report an abnormality, a study
# limitation, or both alongside normals are checked. Dictated negatives and normals are never
# omission-checked or inserted: split from their line they lose their scope (side, level, structure)
# and a restored one reads as a global denial (L-49 re-score: 15 contradicting insertions).
_SEL_LT = ("The line itself reports something abnormal or present in the patient (a lesion, abnormal measurement, device or line "
           "position, post-operative change or interval change), or a problem with the study (artefact, degraded or non-diagnostic "
           "images, incomplete coverage, a structure not seen or not assessed), even alongside normal findings or technique details.")
_SEL_LF = ("The line itself only says that structures are normal or findings are absent, only says how the study was performed "
           "(protocol, sequences, views, phases, contrast, dose, adequate quality), or only names the prior study used for comparison.")
_SEL_CHOICES = {
    "abnormal_finding": "The line reports something abnormal or present in the patient (a lesion, abnormal measurement, device or line position, post-operative change or interval change)",
    "limitation": "The line reports a problem with the study: artefact, degraded or non-diagnostic images, incomplete coverage, or a structure not seen or not assessed",
    "normal_or_negative": "The line only says that structures are normal or that findings are absent",
    "protocol_note": "The line only says how the study was performed (protocol, sequences, views, phases, contrast, dose) or that image quality was adequate",
    "comparison": "The line only names the prior study used for comparison, or says none is available",
    "mixed_abnormal_and_normal": "The line reports something abnormal, or a study problem, alongside normal findings or technique details",
}
_SEL_KEEP = ("abnormal_finding", "limitation", "mixed_abnormal_and_normal")
SELECT_FLAG = 0.45   # mean(CH2sel, T1): 0 unsafe / 0 over on DEV, HOLDOUT and stress, both runs


def q_select_choice(item: str) -> dict:
    return {"type": "choice",
            "instructions": "Read only this one dictated line, not the rest of the dictation: " + f'"{item}". What does this line report?',
            "criteria": _SEL_CHOICES}


def q_select_noul(item: str) -> dict:
    return {"type": "noul",
            "instructions": f'The dictated line "{item}" itself reports an abnormality or a limitation of the study.',
            "criteria": {"true": _SEL_LT, "false": _SEL_LF}}


def selection_score(ch, t1) -> Optional[float]:
    """mean(P(abnormal) + P(limitation) + P(mixed), T1); None when either answer is unreadable."""
    try:
        ch2 = sum(float(ch["probabilities"][k]) for k in _SEL_KEEP)
        return (ch2 + float(t1["noul"])) / 2
    except Exception:
        return None


def selected(item: str, ch, t1) -> bool:
    sc = selection_score(ch, t1)
    return not _BACKGROUND.search(item) if sc is None else sc >= SELECT_FLAG


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
    n_selected: int = 0
    selector: Optional[str] = None   # "jev" | "regex" | "mixed" (regex where Jev's answer was unreadable)
    error: Optional[str] = None


async def check(report: str, findings: str, scan_type: str, options: List[dict]) -> CheckResult:
    """Two Jev calls in parallel: every report clause and option against the dictation (plus the
    omission selector per dictated item), every dictated item against the report. An omission flag
    counts only on a selected item; a failed dictation call selects by the regex (L-46)."""
    fnd, imp = report_sections(report)
    cls = list(dict.fromkeys(clauses(fnd) + clauses(imp)))
    opts = [(o["id"], o["sentence"]) for o in options if o.get("sentence")]
    items = dictated_items(findings)
    contra_qs = {f"c{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, t in enumerate(cls)}
    contra_qs.update({f"o{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, (_, t) in enumerate(opts)})
    # A report negative is removed only if the finding it denies is itself dictated: Jev over-flags
    # negatives that share words with a dictated finding (L-47: 'No irregular asymmetric wall
    # thickening' beside dictated segmental wall thickening). Same call, no added latency.
    restated = {i: restate(t) for i, t in enumerate(cls)}
    contra_qs.update({f"r{i}": q_restated(r) for i, r in restated.items() if r})
    # The omission selector rides the same dictation-state call (no added latency).
    contra_qs.update({f"sel{i}": q_select_choice(t) for i, t in enumerate(items)})
    contra_qs.update({f"lt{i}": q_select_noul(t) for i, t in enumerate(items)})
    omit_qs = {f"i{i}": {"type": "noul", "instructions": Q_CONVEYS + t} for i, t in enumerate(items)}

    async def ask(state, qs):
        return await qb._jev(state, qs) if qs else {}
    async def timed(state, qs):
        return await asyncio.wait_for(ask(state, qs), JEV_TIMEOUT_S)
    contra, omit = await asyncio.gather(
        timed(f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        timed(f"REPORT:\n{report}", omit_qs), return_exceptions=True)
    err = next((e for e in (contra, omit) if isinstance(e, BaseException)), None)
    error = f"{type(err).__name__}: {str(err)[:200]}" if err else None
    if err:
        logger.warning("quality check: Jev failed (%s: %s)", type(err).__name__, str(err)[:200])
    if isinstance(omit, BaseException):   # never blocks the report
        return CheckResult(n_clauses=len(cls), n_items=len(items), error=error)

    score = lambda ans, k: float(ans[k]["noul"])
    flags, bad = [], []
    if not isinstance(contra, BaseException):
        flags = [Flag(kind="contradiction", text=t, score=score(contra, f"c{i}"))
                 for i, t in enumerate(cls) if score(contra, f"c{i}") >= CONTRA_FLAG
                 and (not restated[i] or score(contra, f"r{i}") >= RESTATED_FLAG)]
        bad = [oid for i, (oid, _) in enumerate(opts) if score(contra, f"o{i}") >= CONTRA_FLAG]
    sel_ans = {} if isinstance(contra, BaseException) else contra
    scores = [selection_score(sel_ans.get(f"sel{i}"), sel_ans.get(f"lt{i}")) for i in range(len(items))]
    chosen = [selected(t, sel_ans.get(f"sel{i}"), sel_ans.get(f"lt{i}")) for i, t in enumerate(items)]
    readable = sum(s is not None for s in scores)
    selector = "jev" if readable == len(items) else ("regex" if readable == 0 else "mixed")
    flags += [Flag(kind="omission", text=t, score=score(omit, f"i{i}"))
              for i, t in enumerate(items) if chosen[i] and score(omit, f"i{i}") < OMIT_FLAG]
    return CheckResult(flags=flags, bad_option_ids=bad, n_clauses=len(cls), n_items=len(items),
                       n_selected=sum(chosen), selector=selector, error=error)


# ── repair ───────────────────────────────────────────────────────────────────

class Edit(BaseModel):
    find: str
    replace: str


class RepairEdits(BaseModel):
    edits: List[Edit]
    @field_validator("edits", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return qb._unstring(v)


class RepairResult(BaseModel):
    report: str
    applied: int = 0
    skipped: int = 0
    error: Optional[str] = None
    dup_check: Optional[str] = None   # insert_findings: "jev" | "words" (Jev failed)


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


def edit_allowed(e: Edit, insert_only: bool) -> bool:
    """A repair never turns a negated statement into an assertion (L-47: a flagged negative was
    'corrected' into the malignant finding it denied), and an insertion never rewrites text."""
    if not e.find or e.find == e.replace:
        return False
    if _NEGATION.search(e.find) and not _NEGATION.search(e.replace):
        return False
    return not insert_only or e.find in e.replace


async def repair_report(report: str, findings: str, problems: List[str], insert_only: bool = False) -> RepairResult:
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
        if edit_allowed(e, insert_only) and out.count(e.find) == 1:
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
        return qb._unstring(v)


INSERT_SYS = (
    "A radiology report left out some dictated findings. For each numbered omitted finding write one sentence stating "
    "it in the report's own voice, using only what was dictated, and choose the report sentence it should follow: "
    "copy that sentence exactly into 'after'. Return JSON {\"items\": [{\"after\": ..., \"sentence\": ...}]}.")


_FILLER = {"incidental", "noted", "identified", "seen", "present", "demonstrated", "there", "which", "with",
           "that", "this", "also", "further", "additional", "note"}


def _content_words(t: str) -> set:
    return set(re.findall(r"[a-z]{4,}", t.lower())) - _FILLER


def _negative_allowed(sentence: str, items: List[str]) -> bool:
    """An inserted sentence may carry negation only when it restores an omitted dictated negative:
    some omitted item with negation shares a content word with it (L-49). A negative is never
    invented beside an omitted positive finding."""
    if not _NEGATION.search(sentence):
        return True
    w = _content_words(sentence)
    return any(_NEGATION.search(t) and w & _content_words(t) for t in items)


def _restates(new: str, existing: str) -> bool:
    """`new` says nothing `existing` does not: nearly all its words, and every number, are there."""
    words = lambda t: set(re.findall(r"[a-z]{4,}", t.lower())) - _FILLER
    w = words(new)
    nums = set(re.findall(r"\d+(?:\.\d+)?", new))
    return bool(w) and len(w & words(existing)) >= 0.8 * len(w) \
        and nums <= set(re.findall(r"\d+(?:\.\d+)?", existing))


async def insert_findings(report: str, findings: str, items: List[str]) -> RepairResult:
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
    cands = []
    for it in r.output.items:
        sent = it.sentence.strip()
        if not sent or not _negative_allowed(sent, items):
            skipped += 1
            continue
        cands.append((it, sent if sent.endswith(".") else sent + "."))
    # Already stated in other words (L-47: a reworded finding was re-inserted). Jev judges meaning
    # (L-49); on any Jev failure, word overlap decides exactly as before.
    conveyed, dup_check = None, None
    if cands:
        try:
            ans = await asyncio.wait_for(qb._jev(f"REPORT:\n{report}", {
                f"d{i}": {"type": "noul", "instructions": Q_CONVEYS + s} for i, (_, s) in enumerate(cands)}), JEV_TIMEOUT_S)
            conveyed = [float(ans[f"d{i}"]["noul"]) >= INSERT_DUP for i in range(len(cands))]
            dup_check = "jev"
        except Exception as e:
            logger.warning("insert duplicate check: Jev failed (%s: %s)", type(e).__name__, str(e)[:200])
            dup_check = "words"
    added: List[str] = []
    for i, (it, sent) in enumerate(cands):
        dup = (conveyed[i] or any(_restates(sent, x) for x in added)) if conveyed is not None \
            else any(_restates(sent, x) for x in _sentences(out))
        if dup:
            skipped += 1
            continue
        if it.after and out.count(it.after) == 1:
            out = out.replace(it.after, f"{it.after} {sent}", 1)
        else:
            fnd, _ = report_sections(out)
            first = _sentences(fnd)[0] if fnd else None
            if not first or out.count(first) != 1:
                skipped += 1
                continue
            out = out.replace(first, f"{sent} {first}", 1)
        applied += 1
        added.append(sent)
    return RepairResult(report=out, applied=applied, skipped=skipped, dup_check=dup_check)


# ── deterministic removal of a flagged negative ─────────────────────────────

_NEG_LIST = re.compile(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", re.I)


def is_negative(clause: str) -> bool:
    return bool(_NEG_LIST.match(clause.strip()))


def remove_negative_clause(report: str, clause: str) -> str:
    """Take one flagged negative out of the report without asserting anything: a whole negative
    sentence is deleted; one item of a negative list is dropped from the list. No LLM, so a false
    flag can only lose a negative, never create a finding."""
    target = clause.strip().rstrip(".")
    fnd, imp = report_sections(report)
    for s in _sentences(fnd) + _sentences(imp):
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


async def run_quality_check(report: str, findings: str, scan_type: str,
                            options: List[dict]) -> Tuple[str, List[dict], dict]:
    """Check, then repair only when a report clause or item is flagged. Returns the report, the
    options with flagged ones dropped, and telemetry. Never raises."""
    if not enabled():
        return report, options, {"enabled": False}
    t0 = time.time()
    tel: dict = {"enabled": True, "flags": [], "clauses_removed": 0, "edits_applied": 0, "edits_skipped": 0, "options_dropped": [],
                 "clauses": 0, "items": 0, "jev_ms": None, "repair_ms": None, "error": None}
    try:
        res = await check(report, findings, scan_type, options)
        tel.update(flags=[f.model_dump() for f in res.flags], clauses=res.n_clauses, items=res.n_items,
                   items_selected=res.n_selected, selector=res.selector,
                   jev_ms=int((time.time() - t0) * 1000), error=res.error, options_dropped=res.bad_option_ids)
        options = [o for o in options if o.get("id") not in set(res.bad_option_ids)]
        # A flagged negative is removed in code; a flagged positive statement is corrected, and an
        # omitted finding inserted, by Qwen under edit_allowed (L-47).
        removed = 0
        for f in res.flags:
            if f.kind == "contradiction" and is_negative(f.text):
                new = remove_negative_clause(report, f.text)
                removed += new != report
                report = new
        tel["clauses_removed"] = removed
        fix = [_problem(f) for f in res.flags if f.kind == "contradiction" and not is_negative(f.text)]
        if fix or any(f.kind == "omission" for f in res.flags):
            t1 = time.time()
            omitted = [f.text for f in res.flags if f.kind == "omission"]
            calls = ([repair_report(report, findings, fix)] if fix else []) + \
                    ([insert_findings(report, findings, omitted)] if omitted else [])
            reps = await asyncio.gather(*calls)
            base, report = report, reps[0].report
            for rep in reps[1:]:   # both were made from the same base: replay the second's changes
                for old_s, new_s in _diff_edits(base, rep.report):
                    if report.count(old_s) == 1:
                        report = report.replace(old_s, new_s)
            tel.update(edits_applied=sum(r.applied for r in reps), edits_skipped=sum(r.skipped for r in reps),
                       dup_check=next((r.dup_check for r in reps if r.dup_check), None),
                       repair_ms=int((time.time() - t1) * 1000),
                       error=next((r.error for r in reps if r.error), None) or tel["error"])
    except Exception as e:  # never blocks the report
        logger.warning("quality check failed (%s: %s)", type(e).__name__, str(e)[:200])
        tel["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return report, options, tel
