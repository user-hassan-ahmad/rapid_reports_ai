"""Shared post-generation check: Jev flags contradictions and omissions, focal repairs fix them.
Used by both pathways (spec 2026-09-30-template-pipeline-mirror-design §4).

Spec docs/superpowers/specs/2026-09-30-post-generation-check-design.md; probe ledger L-46.

    units   -> report clauses, option sentences, every dictated item (code); a Jev selector
               keeps omission flags only on abnormal / limitation / mixed lines
    check   -> two Jev calls in parallel: contradiction (dictation state), and a classifier per
               dictated line (report state): stated / partial / absent / different / unclear
    repair  -> only absent lines are inserted (one Qwen call, code places each sentence); partial
               and different lines go to the telemetry for review and never edit the report; a
               flagged negative is removed in code unless the dictation itself states it; a flagged
               positive statement is review only (a Qwen rewrite copied dictation slips over the
               generator's corrections, L-49)
Flagged options are dropped, never repaired. Nothing here raises: on any failure the report and
options ship as generated, with the reason in the telemetry.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import asdict
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from . import brief_anchor
from . import report_reconcile as rc
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
# A report negative the dictation itself states is never removed, whatever the contradiction score (L-49 addendum,
# f98a5930: stenosis dictated at L4/L5 made Jev read the dictated "No spinal canal stenosis" at L3/L4 as contradicted).
# Scope-aware: the clause is quoted with the report sentence before it, so "at this level" resolves. Probe
# (scratchpad dictneg/): 24 items x 2 repeats, 0 wrong; stated >= 0.57, not stated <= 0.10.
Q_DICTATED = "The dictated findings themselves state this negative, in any wording, for the same level, side and structure: "
_DICTATED_TRUE = ("The dictation itself says this finding is absent, or the structure is normal in this respect, at the "
                  "level, side or structure the statement refers to. Count any wording, synonym or equivalent term for "
                  "the same finding or structure. When the statement refers to no particular level, side or structure, a "
                  "dictated absence of this finding counts. Use the report text it follows only to tell which level, side "
                  "or structure it refers to.")
_DICTATED_FALSE = ("The dictation does not say this finding is absent there: it reports the finding as present or possible "
                   "there, says nothing about it, or states its absence only for a different level, side, vertebra or "
                   "structure.")
DICTATED_KEEP = 0.5


def q_dictated(clause: str, before: str) -> dict:
    ctx = f' (in the report it follows: "{before}")' if before else ""
    return {"type": "noul", "instructions": f'{Q_DICTATED}"{clause}"{ctx}',
            "criteria": {"true": _DICTATED_TRUE, "false": _DICTATED_FALSE}}


CONTRA_FLAG = 0.6   # L-46: 31/31 genuine contradictions >= 0.5, 29/31 >= 0.7
RESTATED_FLAG = 0.5  # a report negative is removed only when the finding it denies is dictated (L-47)
# "Is this new sentence already in the report?" (Jev wording v2, group A S2, L-49): the inserter's duplicate guard.
# One wording, shared with the option uniqueness gate (report_reconcile); the thresholds differ per use.
Q_CONVEYS = rc.Q_CONVEYS
INSERT_DUP = 0.25   # L-49: an inserted sentence is skipped at >= 0.25 (conveyed >= 0.32, new <= 0.14)

# Omission classifier (classify-first, L-49): the yes/no "is every detail stated?" flagged lines whose finding was
# already reported with one detail missing, and the inserter then wrote the whole line again (16 duplicates in 56)
# or copied a line the report states differently (conflicts). One choice per line, in the same report-state call:
# only "absent" is inserted. Probe arm A3: 0 unsafe (partial / different / stated chosen as absent) on DEV and
# HOLDOUT in both repeats, 179 items (scratchpad classify_probe/). "unclear" catches headings and garbled fragments.
_OMIT_CHOICES = {
    "stated": "The report already says everything in this line, possibly in other words, abbreviations or synonyms, "
              "or spread over more than one sentence.",
    "partial": "The report already reports this line's abnormality, but without one or more of the line's details "
               "(a measurement, density value, side, level, grade, descriptor, extent, or a normal or negative that "
               "the line adds).",
    "absent": "Nothing in the report is about this line's abnormality: the report neither reports it nor says anything "
              "about that structure that would cover it.",
    "different": "The report says something about the same structure that disagrees with the line: a different "
                 "severity, grade, size or measurement, the other side or another level, or normal or absent where "
                 "the line reports an abnormality.",
    "unclear": "The line is only a heading or a fragment, or its words make no sense as a finding, so there is nothing "
               "clear to compare.",
}
_OMIT_KIND = {"absent": "omission", "partial": "partial", "different": "differs"}   # stated / unclear: no flag


def q_omission(item: str) -> dict:
    return {"type": "choice",
            "instructions": f'Read only this one dictated line: "{item}". Find what the report says about the same '
                            "finding or structure, then choose how the report covers this line.",
            "criteria": _OMIT_CHOICES}


def omission_class(ans) -> Tuple[Optional[str], float]:
    """The most probable class and its probability; (None, 0) when the answer is unreadable (no flag)."""
    try:
        probs = {k: float(v) for k, v in ans["probabilities"].items() if k in _OMIT_CHOICES}
        best = max(probs, key=probs.get)
        return best, probs[best]
    except Exception:
        return None, 0.0


_DETAIL_STOP = {"the", "and", "with", "are", "is", "of", "in", "at", "to", "a", "an", "or", "seen", "noted", "there",
                "this", "that", "which", "also", "likely", "measuring", "measures", "demonstrates"}


def missing_detail(line: str, report: str) -> Optional[str]:
    """A hint for the review rail: the line's numbers and words that appear nowhere in the report, in order."""
    have = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", report.lower()))
    out: List[str] = []
    for tok in re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", line):
        low = tok.lower()
        if low in have or low in _DETAIL_STOP or (low.isalpha() and len(low) < 2) or tok in out:
            continue
        out.append(tok)
    return " ".join(out) or None
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


def clauses_in_context(text: str) -> List[Tuple[str, str]]:
    """(clause, the sentence before the clause's sentence, or ""): the context tells which level, side
    or structure a clause such as 'No stenosis at this level' refers to."""
    out: List[Tuple[str, str]] = []
    prev = ""
    for s in _sentences(text):
        m = re.match(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", s, re.I)
        parts = [p.strip() for p in re.split(r",\s*(?:or\s+|and\s+)?", m.group(2)) if p.strip()] if m else []
        out.extend((f"No {p}", prev) for p in parts) if len(parts) > 1 else out.append((s, prev))
        prev = s
    return out


def clauses(text: str) -> List[str]:
    """Sentences, with a negative list split at its commas into one clause per finding. A bare
    'or' never splits: 'No pericolic or paracolic fluid collection' is one finding (L-46)."""
    return [c for c, _ in clauses_in_context(text)]


_RESTATE = re.compile(r"^(?:No|There is no|There are no|Without)\s+(.*?)(?:\s+(?:is|are|was|were))?(?:\s+(?:identified|seen|present|demonstrated|noted))?\.?$", re.I)


def restate(clause: str) -> Optional[str]:
    """The finding a negative clause denies ('No X is identified.' -> 'X'); None for a positive."""
    m = _RESTATE.match(clause.strip())
    return m.group(1).strip() if m else None


def dictated_items(findings: str) -> List[str]:
    """Every dictated item; each is asked the conveys question, and the selector decides which flags count."""
    return rc.split_findings(findings)


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


def header_names(report: str) -> List[str]:
    """Ordered section headings of a quick report (FINDINGS:, IMPRESSION:, …)."""
    return [m.group(1) for m in _HEADER.finditer(report)]


QUICK_TOP_LEVEL = ("CLINICAL HISTORY", "COMPARISON", "TECHNIQUE", "FINDINGS", "IMPRESSION", "LIMITATIONS",
                   "CONCLUSION")


def quick_section_names(report: str) -> List[str]:
    """Top-level headings of a quick report, in order. Region sub-headings under a REGIONS
    macro-structure (e.g. a body-region label inside FINDINGS) are not sections."""
    return [h for h in header_names(report) if h in QUICK_TOP_LEVEL]


class ReportSection(BaseModel):
    name: str
    header: Optional[str] = None      # as written in reports; None = implicit (no header line)
    role: str = "other"               # history|technique|comparison|findings|impression|other


CHECKED_ROLES = {"findings", "impression", "other"}


def _header_candidates(report: str, header: str) -> List[Tuple[int, int, int]]:
    """Every place `header` could start a section, as (tier, header start, content start). Tier 0/1:
    the header alone on its line ('Impression', 'Impression:'), exact case / any case; tier 2/3: an
    inline header ('Impression: text', content after the colon), exact case / any case. Tolerates
    CRLF line ends."""
    h = re.escape(header.strip().rstrip(":").strip())
    alone = rf"^[ \t]*{h}[ \t]*:?[ \t]*\r?$"
    inline = rf"^[ \t]*{h}[ \t]*:[ \t]*(?=[^\s])"
    out = []
    for base, pat in ((0, alone), (2, inline)):
        exact = re.compile(pat, re.M)
        for m in re.compile(pat, re.M | re.I).finditer(report):
            out.append((base + (0 if exact.match(report, m.start()) else 1), m.start(), m.end()))
    return out


_PREAMBLE_ROLES = {"technique", "comparison", "history"}


def _section_layout(report: str, sections: List[ReportSection]
                    ) -> Tuple[List[Tuple[ReportSection, int, int]], List[str]]:
    """section_spans, plus the names of checked implicit sections that came out empty."""
    # Header choice, deterministic: sections are taken in sheet order; each tries the candidate tiers
    # in turn (standalone before inline, exact case before any case) and within a tier takes the
    # first unclaimed candidate after the previously placed header, else the first unclaimed one
    # anywhere. So a standalone header always beats prose that merely starts 'Impression: ...', a
    # lone lower-case word in the history loses to the real header, and a section written out of
    # sheet order is still found.
    headed: dict = {}                 # sheet index -> (header start, content start)
    claimed: set = set()
    last = -1
    for i, sec in enumerate(sections):
        if not sec.header:
            continue
        cands = _header_candidates(report, sec.header)
        pick = None
        for tier in range(4):
            tc = sorted((st, en) for t, st, en in cands if t == tier and st not in claimed)
            pick = next(((st, en) for st, en in tc if st > last), tc[0] if tc else None)
            if pick:
                break
        if pick:
            headed[i] = pick
            claimed.add(pick[0])
            last = pick[0]
    after: dict = {}                  # headed sheet index (or -1 = top) -> implicit sections after it
    for i, sec in enumerate(sections):
        if not sec.header:
            anchor = next((j for j in range(i - 1, -1, -1) if j in headed), -1)
            after.setdefault(anchor, []).append(sec)
    order: List[Tuple[ReportSection, Optional[int], Optional[int]]] = \
        [(sec, None, None) for sec in after.get(-1, [])]
    for i in sorted(headed, key=lambda j: headed[j][0]):
        order.append((sections[i], *headed[i]))
        order += [(sec, None, None) for sec in after.get(i, [])]
    header_starts = sorted(h for h, _ in headed.values())
    out: List[List] = []
    empty: List[str] = []
    prev_end = 0
    for idx, (sec, h, c) in enumerate(order):
        start = c if c is not None else prev_end
        nxt = next((x for x in header_starts if x >= start and (h is None or x > h)), len(report))
        if c is not None and idx + 1 < len(order) and order[idx + 1][1] is None:
            body = re.search(r"\S", report[start:nxt])
            brk = re.search(r"\n[ \t]*\r?\n", report[start + body.start():nxt]) if body else None
            if brk:
                nxt = start + body.start() + brk.start()
        if c is None and sec.role in CHECKED_ROLES and not report[start:nxt].strip():
            empty.append(sec.name)
            # No blank line after a short preamble section ('TECHNIQUE\nCT.\nNo ascites.'): its
            # first line is the preamble, the rest belongs to this implicit section.
            prev = out[-1] if out else None
            if prev and prev[0].header and prev[0].role in _PREAMBLE_ROLES:
                body = re.search(r"\S", report[prev[1]:prev[2]])
                nl = report.find("\n", prev[1] + body.start(), prev[2]) if body else -1
                if nl >= 0 and report[nl:prev[2]].strip():
                    prev[2], start = nl, nl
        out.append([sec, start, nxt])
        prev_end = nxt
    return [(s_, a_, b_) for s_, a_, b_ in out], empty


def section_spans(report: str, sections: List[ReportSection]) -> List[Tuple[ReportSection, int, int]]:
    """(section, start, end) for each section found, in report order. Headers are chosen as in
    _section_layout: standalone header lines before inline 'Header: text', exact case before any
    case, sheet order kept where the report allows, else the first free occurrence anywhere (so
    out-of-order sections still split). A headed section starts where its content starts (after
    the header line, or after an inline header's colon) and ends at the next header, or, when the
    next section is implicit, at its first paragraph break. An implicit section follows its nearest
    found headed predecessor in sheet order (or sits at the top) and runs to the next header; if it
    comes out empty after a history/technique/comparison section, that section keeps only its first
    line and the rest is the implicit section's."""
    return _section_layout(report, sections)[0]


def _checked_spans(report: str, sections: List[ReportSection]) -> List[Tuple[int, int]]:
    return [(a, b) for s, a, b in section_spans(report, sections) if s.role in CHECKED_ROLES]


def _checked_texts(report: str, sections: Optional[List[ReportSection]]) -> List[str]:
    """The report text the check reads: FINDINGS + IMPRESSION (quick), or every section whose role
    carries dictated content (templates)."""
    if sections is None:
        return list(report_sections(report))
    return [report[a:b].strip() for a, b in _checked_spans(report, sections)]


def checked_clauses(report: str, sections: Optional[List[ReportSection]]) -> List[str]:
    """Clauses the contradiction check reads. Quick (no sections): FINDINGS + IMPRESSION as before.
    Templates: every section whose role carries dictated content."""
    return list(checked_clauses_in_context(report, sections))


def checked_clauses_in_context(report: str, sections: Optional[List[ReportSection]]) -> dict:
    """{clause: the sentence before it} for the checked clauses, in order (first occurrence wins)."""
    before: dict = {}
    for t in _checked_texts(report, sections):
        for c, b in clauses_in_context(t):
            before.setdefault(c, b)
    return before


# ── protected text: an invariant by position ────────────────────────────────

def _occurrences(text: str, needle: str) -> List[Tuple[int, int]]:
    out, i = [], text.find(needle) if needle else -1
    while i >= 0:
        out.append((i, i + len(needle)))
        i = text.find(needle, i + 1)
    return out


def protected_spans(report: str, protected: Optional[List[str]]) -> List[Tuple[int, int]]:
    """Every occurrence of every protected string (history section, fixed blocks), as positions."""
    return [sp for p in protected or [] for sp in _occurrences(report, p)]


def _overlaps(a: int, b: int, spans: List[Tuple[int, int]]) -> bool:
    return any(a < pe and ps < b for ps, pe in spans)


def _inside(a: int, b: int, spans: List[Tuple[int, int]]) -> bool:
    return any(ps <= a and b <= pe for ps, pe in spans)


def without(report: str, protected: List[str], sections: Optional[List[ReportSection]] = None) -> str:
    """The report with protected text (history section, fixed blocks) removed: one occurrence of
    each protected string, by position — the first outside the checked sections when sections are
    given, else the first. A duplicate elsewhere (a dictated sentence that matches) is kept."""
    for p in protected:
        occ = _occurrences(report, p)
        if not occ:
            continue
        a, b = occ[0]
        if sections is not None:
            checked = _checked_spans(report, sections)
            a, b = next(((x, y) for x, y in occ if not _inside(x, y, checked)), occ[0])
        report = report[:a] + report[b:]
    return report


def _term(t: str) -> "re.Pattern[str]":
    return re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.I)


def _has_term(text: str, terms: Optional[List[str]]) -> bool:
    return any(t and _term(t).search(text) for t in terms or [])


def _given(**kw) -> dict:
    """The keyword arguments that are set: template-only arguments are passed on only when given,
    so every quick call keeps its exact shape."""
    return {k: v for k, v in kw.items() if v is not None}


# ── check ────────────────────────────────────────────────────────────────────

class Flag(BaseModel):
    kind: str          # "contradiction" | "omission" (absent: inserted) | "partial" | "differs" (review only)
    text: str          # the report clause, or the dictated item missing from the report
    score: float


class KeptNegative(BaseModel):
    """A flagged report negative kept because the dictation itself states it (or Jev could not say)."""
    text: str
    contradiction: float
    dictated: Optional[float]   # None: unreadable answer, kept as the conservative choice


class CheckResult(BaseModel):
    flags: List[Flag] = []
    kept_dictated: List[KeptNegative] = []
    bad_option_ids: List[str] = []
    n_clauses: int = 0
    n_items: int = 0
    n_selected: int = 0
    selector: Optional[str] = None   # "jev" | "regex" | "mixed" (regex where Jev's answer was unreadable)
    error: Optional[str] = None
    # Answers to extra_report_qs, asked inside the report-state call (template gate). Excluded from dumps so
    # quick's serialised CheckResult is unchanged.
    extra_answers: dict = Field(default_factory=dict, exclude=True)
    # Jev's contradiction score per checked clause (brief_anchor's OMIT rule needs it for clauses that raised no flag).
    # Excluded from dumps.
    contra: dict = Field(default_factory=dict, exclude=True)
    # Jev's statement type (abnormal / normal / mixed / not_a_finding, None if unreadable) of the sentence(s) holding
    # each negative clause: a removal needs "normal" (`_safe_to_remove`). Excluded from dumps.
    sentence_type: dict = Field(default_factory=dict, exclude=True)


async def check(report: str, findings: str, scan_type: str, options: List[dict],
                sections: Optional[List[ReportSection]] = None, protected: Optional[List[str]] = None,
                extra_report_qs: Optional[dict] = None, history: Optional[str] = None) -> CheckResult:
    """Two Jev calls in parallel: every checked report clause and option against the dictation (plus the
    omission selector per dictated item), every dictated item classified against the report (protected text
    removed). A line flag counts only on a selected item; a failed dictation call selects by the regex (L-46).
    A failed report call, or an unreadable answer, raises no line flag: nothing is inserted. Templates
    (`sections`) that pass `history` (the verbatim history, also in `protected`) remove only that from the
    omission state: FIXED / technique text stays visible, so a dictated protocol note it states is not missing."""
    before = checked_clauses_in_context(report, sections)
    cls = list(before)
    opts = [(o["id"], o["sentence"]) for o in options if o.get("sentence")]
    items = dictated_items(findings)
    contra_qs = {f"c{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, t in enumerate(cls)}
    contra_qs.update({f"o{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, (_, t) in enumerate(opts)})
    # A report negative is removed only if the finding it denies is itself dictated: Jev over-flags
    # negatives that share words with a dictated finding (L-47: 'No irregular asymmetric wall
    # thickening' beside dictated segmental wall thickening). Same call, no added latency.
    restated = {i: restate(t) for i, t in enumerate(cls)}
    contra_qs.update({f"r{i}": q_restated(r) for i, r in restated.items() if r})
    # ...and never when the dictation itself states the negative (L-49 addendum). Same call.
    contra_qs.update({f"d{i}": q_dictated(cls[i], before[cls[i]]) for i, r in restated.items() if r})
    # ...and only when the whole sentence holding it is a normal statement (Jev's lab-validated statement type):
    # "No effusion with mild atelectasis." is mixed, and removing it would take the finding with it. Same call.
    from .review_engine.jev_pass import clause_type_of, q_type   # lazy: jev_pass imports this module
    # Every negative clause that could be removed; the sentence asked is exactly the one a removal would edit.
    sent_of = {t: [x[0] for x in _removal_targets(report, t, sections, protected)] for t in cls if is_negative(t)}
    sents = {x: j for j, x in enumerate(dict.fromkeys(x for ss in sent_of.values() for x in ss))}
    contra_qs.update({f"t{j}": q_type(x) for x, j in sents.items()})
    # The omission selector rides the same dictation-state call (no added latency).
    contra_qs.update({f"sel{i}": q_select_choice(t) for i, t in enumerate(items)})
    contra_qs.update({f"lt{i}": q_select_noul(t) for i, t in enumerate(items)})
    omit_qs = {f"i{i}": q_omission(t) for i, t in enumerate(items)}
    omit_qs.update(extra_report_qs or {})  # another caller's report-state questions, same request

    hidden = protected or []
    if sections is not None and history is not None:
        hidden = [history] if history else []

    async def ask(state, qs):
        return await rc._jev(state, qs) if qs else {}
    async def timed(state, qs):
        return await asyncio.wait_for(ask(state, qs), JEV_TIMEOUT_S)
    contra, omit = await asyncio.gather(
        timed(f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        timed(f"REPORT:\n{without(report, hidden, sections)}", omit_qs), return_exceptions=True)
    err = next((e for e in (contra, omit) if isinstance(e, BaseException)), None)
    error = f"{type(err).__name__}: {str(err)[:200]}" if err else None
    if err:
        logger.warning("quality check: Jev failed (%s: %s)", type(err).__name__, str(err)[:200])
    if isinstance(omit, BaseException):   # never blocks the report
        return CheckResult(n_clauses=len(cls), n_items=len(items), error=error)

    score = lambda ans, k: float(ans[k]["noul"])
    def maybe(ans, k):
        try:
            return score(ans, k)
        except Exception:
            return None
    flags, bad, kept = [], [], []
    if not isinstance(contra, BaseException):
        for i, t in enumerate(cls):
            c = score(contra, f"c{i}")
            if c < CONTRA_FLAG or (restated[i] and score(contra, f"r{i}") < RESTATED_FLAG):
                continue
            d = maybe(contra, f"d{i}") if restated[i] else 0.0
            if d is None or d >= DICTATED_KEEP:
                kept.append(KeptNegative(text=t, contradiction=c, dictated=d))
            else:
                flags.append(Flag(kind="contradiction", text=t, score=c))
        bad = [oid for i, (oid, _) in enumerate(opts) if score(contra, f"o{i}") >= CONTRA_FLAG]
    sel_ans = {} if isinstance(contra, BaseException) else contra
    scores = [selection_score(sel_ans.get(f"sel{i}"), sel_ans.get(f"lt{i}")) for i in range(len(items))]
    chosen = [selected(t, sel_ans.get(f"sel{i}"), sel_ans.get(f"lt{i}")) for i, t in enumerate(items)]
    readable = sum(s is not None for s in scores)
    selector = "jev" if readable == len(items) else ("regex" if readable == 0 else "mixed")
    for i, t in enumerate(items):
        kind, p = omission_class(omit.get(f"i{i}"))
        if chosen[i] and kind in _OMIT_KIND:
            flags.append(Flag(kind=_OMIT_KIND[kind], text=t, score=p))
    contra_scores = {} if isinstance(contra, BaseException) else {
        t: s for i, t in enumerate(cls) if (s := maybe(contra, f"c{i}")) is not None}
    type_ans = {} if isinstance(contra, BaseException) else contra
    sentence_type = {c: _all_normal([clause_type_of(type_ans.get(f"t{sents[x]}")) for x in ss])
                     for c, ss in sent_of.items()}
    return CheckResult(flags=flags, kept_dictated=kept, bad_option_ids=bad, n_clauses=len(cls), n_items=len(items),
                       n_selected=sum(chosen), selector=selector, error=error,
                       extra_answers={k: score(omit, k) for k in (extra_report_qs or {})}, contra=contra_scores,
                       sentence_type=sentence_type)


# ── edits ────────────────────────────────────────────────────────────────────

class RepairResult(BaseModel):
    report: str
    applied: int = 0
    skipped: int = 0
    error: Optional[str] = None
    dup_check: Optional[str] = None   # insert_findings: "jev" | "words" (Jev failed)
    # insert_findings: the sentences inserted, verbatim as they stand in the report. Excluded from dumps so the
    # serialised RepairResult (golden pipeline records) is unchanged.
    added: List[str] = Field(default_factory=list, exclude=True)


_NEGATION = re.compile(r"\b(no|not|without|nor|absent|negative for)\b", re.I)


# ── omitted findings: Qwen writes the sentence, code inserts it ──────────────

def _sentence_positions(report: str, a: int, b: int) -> List[Tuple[str, int, int]]:
    """The sentences of report[a:b], each with its position in the report."""
    out, cur = [], a
    for s in _sentences(report[a:b].strip()):
        i = report.find(s, cur, b)
        if i >= 0:
            out.append((s, i, i + len(s)))
            cur = i + len(s)
    return out


def _anchor_ok(report: str, after: str, sections: Optional[List[ReportSection]],
               pspans: List[Tuple[int, int]]) -> bool:
    """An insertion anchor (occurring once) never overlaps protected text and, for templates, lies
    wholly inside a checked section's content, so never on a header line."""
    i = report.find(after)
    j = i + len(after)
    if _overlaps(i, j, pspans):
        return False
    return sections is None or _inside(i, j, _checked_spans(report, sections))


class Insertion(BaseModel):
    after: str       # an existing report sentence, copied exactly
    sentence: str    # the omitted finding, one sentence in the report's voice


class Insertions(BaseModel):
    items: List[Insertion]
    @field_validator("items", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return rc._unstring(v)


# Classify-first rewrite (L-49): the old two-sentence prompt copied dictation slips, wrote normals from mixed
# lines and restated lines the report gives differently. Lab: 39/39 sentences correct on 42 absent lines (real and
# synthetic, 11 with slips), 0 typo / normal / conflict / duplicate; reasoning low wandered onto lines it was not
# given and timed out, so reasoning stays off (median 0.6 s).
INSERT_SYS = (
    "A radiology report left out some dictated lines. For each numbered line, write at most one sentence to add to "
    "the report, following these rules.\n"
    "1. Write only what the line reports as abnormal or present (a finding, device, post-operative change or "
    "artefact) that the report does not already state. Leave out every normal or negative part of the line, and "
    "anything the report already says.\n"
    "2. Never write a sentence that only says structures are normal, unremarkable or without abnormality, or that "
    "findings are absent. A caveat about the study (such as the limits of the technique) is not a finding. A line with "
    "nothing abnormal left gets an empty sentence.\n"
    "3. Use the report's own terms for that structure, in the report's voice and British English.\n"
    "4. The dictation is speech-recognised. Where a word makes no sense in context and one similar-sounding word is "
    "plainly meant, write that word instead of copying it. If no single word is plainly meant, or the meaning of the "
    "line is not clear, return an empty sentence for it; never guess a finding.\n"
    "5. Never state anything that differs from what the report already says about that structure (presence, "
    "severity, size, side, level or measurement). If the line disagrees with the report, return an empty sentence.\n"
    "6. Add nothing that was not dictated.\n"
    "7. In 'after', copy exactly, character for character, the report sentence about the same region or structure "
    "that the new sentence should follow.\n"
    "Return JSON {\"items\": [{\"after\": ..., \"sentence\": ...}]}, one entry per numbered line, in order, with "
    "\"sentence\": \"\" when nothing should be added.")


_FILLER = {"incidental", "noted", "identified", "seen", "present", "demonstrated", "there", "which", "with",
           "that", "this", "also", "further", "additional", "note"}


def _content_words(t: str) -> set:
    return set(re.findall(r"[a-z]{4,}", t.lower())) - _FILLER


_NORMAL_CLAUSE = re.compile(r"\b(unremarkable|normal(?:ly)?|no\b|not\b|without|within (?:normal )?limits|clear|intact)\b|"
                            r"^\s*within the limits", re.I)


def _only_normal(sentence: str) -> bool:
    """Every clause says something is normal or absent, or is a caveat about the study: a sentence the
    inserter must never add (the classify-first prompt forbids it; this is the code backstop)."""
    parts = [p for p in re.split(r",|;|\b(?:and|with|which|but|while)\b", sentence) if p.strip(" .")]
    return bool(parts) and all(_NORMAL_CLAUSE.search(p) for p in parts)


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


async def insert_findings(report: str, findings: str, items: List[str],
                          sections: Optional[List[ReportSection]] = None, protected: Optional[List[str]] = None,
                          suppressed: Optional[List[str]] = None) -> RepairResult:
    """Insertion by construction: the report's existing text is never rewritten (L-47: asked for
    insert-only edits, Qwen rewrote the neighbouring sentence). An anchor that is not found places
    the sentence first in FINDINGS, where the primary finding belongs. With `sections` (templates) an
    anchor must lie wholly inside a checked section's content, never on a header or in protected
    text; the fallback is the first sentence of the findings-role section."""
    user = (f"DICTATED FINDINGS:\n{findings}\n\nREPORT:\n{report}\n\nLINES LEFT OUT OF THE REPORT:\n"
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
        if not sent or _only_normal(sent) or not _negative_allowed(sent, items):
            skipped += 1
            continue
        if _has_term(sent, suppressed):
            skipped += 1   # the sheet suppresses this wording
            continue
        cands.append((it, sent if sent.endswith(".") else sent + "."))
    # Already stated in other words (L-47: a reworded finding was re-inserted). Jev judges meaning
    # (L-49); on any Jev failure, word overlap decides exactly as before.
    conveyed, dup_check = None, None
    if cands:
        try:
            ans = await asyncio.wait_for(rc._jev(f"REPORT:\n{report}", {
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
        pspans = protected_spans(out, protected)
        if it.after and out.count(it.after) == 1 and _anchor_ok(out, it.after, sections, pspans):
            out = out.replace(it.after, f"{it.after} {sent}", 1)
        elif sections is not None:
            span = next(((a, b) for s, a, b in section_spans(out, sections) if s.role == "findings"), None)
            firsts = _sentence_positions(out, *span) if span else []
            if not firsts or _overlaps(firsts[0][1], firsts[0][2], pspans):
                skipped += 1
                continue
            i = firsts[0][1]
            out = out[:i] + f"{sent} " + out[i:]
        else:
            fnd, _ = report_sections(out)
            first = _sentences(fnd)[0] if fnd else None
            if not first or out.count(first) != 1 or _overlaps(out.find(first), out.find(first) + len(first), pspans):
                skipped += 1
                continue
            out = out.replace(first, f"{sent} {first}", 1)
        applied += 1
        added.append(sent)
    return RepairResult(report=out, applied=applied, skipped=skipped, dup_check=dup_check, added=added)


# ── deterministic removal of a flagged negative ─────────────────────────────

_NEG_LIST = re.compile(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", re.I)


def _regions(report: str, sections: Optional[List[ReportSection]]) -> List[Tuple[int, int]]:
    """Where automatic removals may happen, as positions: the checked sections (templates) or FINDINGS + IMPRESSION,
    each located after its own header (an IMPRESSION identical to text in FINDINGS is still the IMPRESSION)."""
    if sections is not None:
        return _checked_spans(report, sections)
    marks = {m.group(1): m.end() for m in _HEADER.finditer(report)}
    out: List[Tuple[int, int]] = []
    for name, t in zip(("FINDINGS", "IMPRESSION"), report_sections(report)):
        if t and name in marks and (i := report.find(t, marks[name])) >= 0:
            out.append((i, i + len(t)))
    return out


Target = Tuple[str, int, int, str]     # (sentence, start, end, "sentence" | "item")


def _removal_targets(report: str, clause: str, sections: Optional[List[ReportSection]] = None,
                     protected: Optional[List[str]] = None) -> List[Target]:
    """Every place a removal of `clause` could edit, in report order: a sentence (the one splitter,
    `_sentence_positions`) that IS the clause, or a negative list holding it as an item; only inside the removal
    regions and never in a sentence overlapping protected text."""
    target = clause.strip().rstrip(".")
    pspans = protected_spans(report, protected)
    out: List[Target] = []
    for a, b in _regions(report, sections):
        for s, i, j in _sentence_positions(report, a, b):
            if _overlaps(i, j, pspans):
                continue
            if s.rstrip(".") == target:
                out.append((s, i, j, "sentence"))
            elif _drop_item(s, target) is not None:
                out.append((s, i, j, "item"))
    return out


def _remove_at(report: str, clause: str, t: Target) -> str:
    """Remove at exactly the target: delete the sentence at (i, j), or drop the item from exactly that sentence."""
    s, i, j, mode = t
    if mode == "item":
        new = _drop_item(s, clause.strip().rstrip("."))
        return report[:i] + new + report[j:] if new else report
    lo, hi = i, j
    while lo > 0 and report[lo - 1] in " \t":
        lo -= 1
    while hi < len(report) and report[hi] in " \t":
        hi += 1
    left, right = report[:lo], report[hi:]
    sep = "" if not left or left.endswith("\n") or not right or right.startswith("\n") else " "
    # A line left empty, or a numbered or bulleted item left holding only its marker, loses its line too.
    start = left.rfind("\n") + 1
    end = right.find("\n")
    line = left[start:] + (right if end < 0 else right[:end])
    if not line.strip() or _EMPTY_ITEM.match(line):
        return left[:start] + ("" if end < 0 else right[end + 1:])
    return left + sep + right


def _all_normal(types: List[Optional[str]]) -> Optional[str]:
    """One type for a clause written in several sentences: "normal" only if every one is; None if any is unread."""
    if not types or any(t is None for t in types):
        return None
    return next((t for t in types if t != "normal"), "normal")


def _item_span(report: str, t: Target, clause: str) -> Tuple[int, int]:
    """The words of a negative-list item inside its sentence (the whole sentence if they cannot be found)."""
    s, i, j, _ = t
    m = re.search(r"\b" + re.escape(clause.strip().rstrip(".")[3:]) + r"\b", report[i:j])
    return (i + m.start(), i + m.end()) if m else (i, j)


def _safe_to_remove(report: str, clause: str, sentence_type: Optional[str], anchors: list,
                    sections: Optional[List[ReportSection]] = None,
                    protected: Optional[List[str]] = None) -> Tuple[Optional[Target], Optional[str]]:
    """The last-step invariant before EVERY automatic removal -> (the exact target it approves, None) or (None, why).
    A target is a whole sentence or negative-list item (`_removal_targets`, the same places `_remove_at` edits); the
    clause's sentences must be a normal statement (Jev, asked of exactly those sentences); the approved sentence holds
    no ';' (a backstop); and no brief KEEP or dictated anchor (or a KEEP shadowed by one) overlaps the approved span.
    No anchors (templates, no brief) makes the last condition vacuous. The first target passing every check is
    approved; one that fails is never edited."""
    cands = _removal_targets(report, clause, sections, protected)
    if not cands:
        return None, "not_whole"
    if sentence_type != "normal":
        return None, "sentence_type"
    live = [x for x in anchors if getattr(x, "span", None) and brief_anchor.anchored(x)]
    why: Optional[str] = None
    for t in cands:
        if ";" in t[0]:
            why = why or "semicolon"
            continue
        a, b = (t[1], t[2]) if t[3] == "sentence" else _item_span(report, t, clause)
        held = [x for x in live if x.span[0] < b and a < x.span[1]]
        refs = {x.ref for x in held}
        shadow = [x for x in anchors if x.shadowed_by in refs and x.action in brief_anchor.KEEP]
        if any(x.action in brief_anchor.KEEP for x in held + shadow):
            why = why or "brief_anchor"
            continue
        return t, None
    return None, why


def _brief_remove_enabled() -> bool:
    """RR_BRIEF_REMOVE=1: the brief's would-be removals (anchor_log.would_remove_by_brief) are applied, under
    `_safe_to_remove`. Default off: the brief vetoes, never removes."""
    return os.environ.get("RR_BRIEF_REMOVE", "0").strip().lower() in ("1", "true", "on")


def is_negative(clause: str) -> bool:
    return bool(_NEG_LIST.match(clause.strip()))


def _drop_item(s: str, target: str) -> Optional[str]:
    """Sentence `s` with the negative-list item `target` dropped; None when `s` is not a negative
    list holding it."""
    m = _NEG_LIST.match(s)
    if not m:
        return None
    parts = [p.strip() for p in re.split(r",\s*(?:or\s+|and\s+)?", m.group(2)) if p.strip()]
    if len(parts) < 2 or target not in (f"No {p}" for p in parts):
        return None
    rest = [p for p in parts if f"No {p}" != target]
    conj = "and" if re.search(r",\s*and\s+", m.group(2)) else "or"
    body = rest[0] if len(rest) == 1 else (f"{rest[0]} {conj} {rest[1]}" if len(rest) == 2
                                              else ", ".join(rest[:-1]) + f", {conj} {rest[-1]}")
    return f"{m.group(1)} {body}."


_EMPTY_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*\u2022])\s*$")


def remove_negative_clause(report: str, clause: str, sections: Optional[List[ReportSection]] = None,
                           protected: Optional[List[str]] = None) -> str:
    """Take one flagged negative out of the report without asserting anything: a whole negative
    sentence is deleted; one item of a negative list is dropped from the list. No LLM, so a false
    flag can only lose a negative, never create a finding. With `sections` or `protected`
    (templates) the edit is made by position, only inside a checked section and never in a sentence
    that overlaps protected text."""
    t = _removal_targets(report, clause, sections, protected)
    return _remove_at(report, clause, t[0]) if t else report


# ── orchestration ────────────────────────────────────────────────────────────

def enabled() -> bool:
    """Kill switch: RR_QUALITY_CHECK=0 ships reports exactly as generated."""
    return os.environ.get("RR_QUALITY_CHECK", "1").strip() not in ("0", "false", "off")


async def run_quality_check(report: str, findings: str, scan_type: str, options: List[dict],
                            sections: Optional[List[ReportSection]] = None, protected: Optional[List[str]] = None,
                            suppressed: Optional[List[str]] = None,
                            extra_report_qs: Optional[dict] = None,
                            history: Optional[str] = None,
                            brief_decisions: Optional[dict] = None) -> Tuple[str, List[dict], dict]:
    """Check, then edit only for a flagged negative (removed) or an absent line (inserted). Returns the report, the
    options with flagged ones dropped, and telemetry. Never raises. `sections` makes the check
    section-generic (templates); `protected` text is never checked for omission or edited; an insertion
    never introduces a `suppressed` term; `history` (templates) is the protected text hidden from the
    omission check, the rest stays visible there. All default to the quick behaviour. The template path works
    on the report with CRLF normalised to LF and returns it with LF line endings; protected text is an invariant: if a repair ever
    changes it, the repairs are reverted. `brief_decisions` (quick): the brief's labels are anchored on the report
    (`brief_anchor`); a brief-kept clause is never removed (a conflict card instead) and an OMIT clause is removed on
    two signals."""
    if not enabled():
        return report, options, {"enabled": False}
    t0 = time.time()
    tel: dict = {"enabled": True, "flags": [], "clauses_removed": 0, "edits_applied": 0, "edits_skipped": 0, "options_dropped": [],
                 "clauses": 0, "items": 0, "kept_dictated_negative": [], "jev_ms": None, "repair_ms": None, "error": None, "review": []}
    if sections is not None:
        report = report.replace("\r\n", "\n")
        protected = [p.replace("\r\n", "\n") for p in protected] if protected is not None else None
        history = history.replace("\r\n", "\n") if history is not None else None
        found, tel["sections_empty"] = _section_layout(report, sections)
        tel["sections_found"] = [s.name for s, _, _ in found]
        tel["sections_missing"] = [s.name for s in sections if s.header and not any(s is f for f, _, _ in found)]
    original = pre_repair = report
    removals: List[dict] = []
    insertions: List[dict] = []
    anchors: list = []
    rules = None
    cards: List[dict] = []
    blocked: List[dict] = []
    try:
        check_call = check(report, findings, scan_type, options,
                           **_given(sections=sections, protected=protected, extra_report_qs=extra_report_qs,
                                    history=history))
        if brief_decisions is not None and sections is None and brief_anchor.enabled():
            res, anchors = await asyncio.gather(check_call, brief_anchor.anchor(report, brief_decisions),
                                                return_exceptions=True)
            if isinstance(res, BaseException):
                raise res
            if isinstance(anchors, BaseException):     # anchoring never blocks the check
                logger.warning("brief anchor failed (%s: %s)", type(anchors).__name__, str(anchors)[:200])
                anchors = []
        else:
            res = await check_call
        if extra_report_qs is not None:
            tel["extra_answers"] = res.extra_answers
        tel.update(flags=[f.model_dump() for f in res.flags], clauses=res.n_clauses, items=res.n_items,
                   items_selected=res.n_selected, selector=res.selector,
                   jev_ms=int((time.time() - t0) * 1000), error=res.error, options_dropped=res.bad_option_ids,
                   kept_dictated_negative=[k.model_dump() for k in res.kept_dictated])
        options = [o for o in options if o.get("id") not in set(res.bad_option_ids)]
        # A partial or different line, and a flagged positive statement, never edit the report: they are
        # offered for review (the rail). A positive flag is often the generator correcting a dictation slip
        # (template retest 42281: "LMS=872" for dictated "LMP 872"); the Qwen rewrite copied the slip back (L-49).
        tel["review"] = [{"kind": "partial", "line": f.text, "missing_detail": missing_detail(f.text, report)}
                         if f.kind == "partial" else {"kind": "differs", "line": f.text}
                         for f in res.flags if f.kind in ("partial", "differs")]
        tel["review"] += [{"kind": "contradiction", "text": f.text, "score": f.score}
                          for f in res.flags if f.kind == "contradiction" and not is_negative(f.text)]
        if anchors:
            rules = brief_anchor.brief_rules(
                report, anchors, res.contra,
                flagged=[f.text for f in res.flags if f.kind == "contradiction" and is_negative(f.text)],
                review_contra=[r["text"] for r in tel["review"] if r["kind"] == "contradiction"],
                sentence_type=res.sentence_type)
            rules["removed"] = []
        if rules:
            cards = rules["conflicts"]

        def safe(clause: str) -> Optional[Target]:
            """`_safe_to_remove` on the current report (anchors moved with the edits so far); a block is logged
            and carded (one card per clause: an existing brief card becomes the removal_blocked card)."""
            here = brief_anchor.relocate(anchors, report) if anchors else []
            target, why = _safe_to_remove(report, clause, res.sentence_type.get(clause), here,
                                          **_given(sections=sections, protected=protected))
            if target is not None:
                return target
            blocked.append({"clause": clause, "why": why})
            card = next((c for c in cards if c["clause"] == clause), None)
            if card is not None:
                card.update(reason="removal_blocked", why=why)
            else:
                sc = res.contra.get(clause)
                cards.append({"clause": clause, "refs": [], "reason": "removal_blocked",
                              "score": None if sc is None else round(sc, 3), "source": "", "pointer": "", "why": why})
            return None
        # A flagged negative is removed in code (L-47); an omitted finding is inserted by construction.
        # A contradiction inside protected text stays in tel["flags"] for the rail but is never edited: a
        # clause found only inside protected text is not removed; one also written elsewhere still is.
        editable = [f for f in res.flags if not (f.kind == "contradiction" and _only_protected(report, f.text, protected))]
        removed = 0
        for f in editable:
            if f.kind == "contradiction" and is_negative(f.text) and not (rules and f.text in rules["protect"]) \
                    and (target := safe(f.text)) is not None:
                new = _remove_at(report, f.text, target)      # exactly the span the guard approved
                if new != report:
                    removed += 1
                    removals.append({"type": "removal", "clause": f.text})
                report = new
        if rules and _brief_remove_enabled():
            for w in rules["would_remove"]:
                clause = w["clause"]
                if any(r["clause"] == clause for r in removals) or (target := safe(clause)) is None:
                    continue
                new = _remove_at(report, clause, target)
                if new != report:      # removed: its brief_omitted card goes (the pre-applied item shows it)
                    removed += 1
                    removals.append({"type": "removal", "clause": clause})
                    rules["removed"].append(clause)
                    cards[:] = [c for c in cards if c["clause"] != clause]
                    report = new
        tel["clauses_removed"] = removed
        pre_repair = report
        omitted = [f.text for f in editable if f.kind == "omission"]
        if omitted:
            t1 = time.time()
            rep = await insert_findings(report, findings, omitted,
                                        **_given(sections=sections, protected=protected, suppressed=suppressed))
            report = rep.report
            insertions = [{"type": "insertion", "sentence": s} for s in rep.added]
            tel.update(edits_applied=rep.applied, edits_skipped=rep.skipped, dup_check=rep.dup_check,
                       repair_ms=int((time.time() - t1) * 1000), error=rep.error or tel["error"])
    except Exception as e:  # never blocks the report
        logger.warning("quality check failed (%s: %s)", type(e).__name__, str(e)[:200])
        tel["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    if protected and not _protected_intact(original, report, protected):
        report = pre_repair if _protected_intact(original, pre_repair, protected) else original
        insertions = []
        removals = removals if report == pre_repair else []
        tel["error"] = "protected text changed; repair reverted"
    if anchors:
        moved = brief_anchor.relocate(anchors, report)
        tel["anchors"] = [asdict(a) for a in moved]
        tel["anchor_log"] = brief_anchor.anchor_log(moved, rules or {})
    if anchors or cards:
        tel["brief_conflicts"] = cards
    if blocked:
        tel["removal_blocked"] = blocked
    # Gate D shadow log (review engine spec §9): the report before today's automatic edits, kept only while the
    # review engine runs (shadow or live) and only when an edit was applied. `applied_edits` (removals in order, then
    # insertions) lets the engine show each edit as a pre-applied item on the final text (spec §10.4).
    if os.environ.get("RR_REVIEW_ENGINE", "off").strip().lower() in ("shadow", "live") and report != original:
        tel["pre_edit_report"] = original
        tel["applied_edits"] = removals + insertions
    return report, options, tel


def _only_protected(report: str, clause: str, protected: Optional[List[str]]) -> bool:
    """The clause occurs in the report, and every occurrence lies wholly inside protected text."""
    occ = _occurrences(report, clause.strip().rstrip("."))
    spans = protected_spans(report, protected)
    return bool(occ and spans) and all(_inside(a, b, spans) for a, b in occ)


def _protected_intact(before: str, after: str, protected: List[str]) -> bool:
    """Every protected string occurs at least as often after the check as before it."""
    return all(after.count(p) >= before.count(p) for p in protected if p)
