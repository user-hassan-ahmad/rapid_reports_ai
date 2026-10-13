"""Sheet checks after the build, shown on the Style step as report behaviour (Rules-step spec, step 5, cards
"Always printed" and "Your normal report"); roadmap §4's creation-time FIXED check.

- fixed_flags: a FIXED line is printed in every report. Each one not covered by a context rule and not already
  decided is asked of Jev ("could this be false for a different patient having this scan?"); an absence-worded line
  ("No …", "There is no …", "Without …") is flagged by code as a tiny backstop. Flags become "Always printed" cards;
  nothing is ever dropped silently.
- normal_report: the all-normal report built by code from the NORMAL / NEGATIVE lines in section order, each sentence
  tagged with its ledger key (tap to edit or remove).
- uncovered: structures a findings paragraph COVERS with no NORMAL ("mentioned in your examples but no normal
  sentence": Add wording / Leave unmentioned).
- concept_duplicates: a FIXED line or a template NEGATIVE the ledger does not own (and no non-standard context rule
  makes conditional) that Jev says states a decided concept again ("may be stated twice"). A NEGATIVE's card acts on the NEGATIVE
  (its normal-kind ledger key), never as a fixed entry.
- sheet_checks: all of the above plus the ledger entries that could not be matched (cards at the next review).
Every Jev question is case-agnostic (structural wording only)."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import List, Optional, Set

from . import template_decisions as td
from . import template_ledger_apply as tla
from . import template_rules_cards as trc
from . import template_sheet_grammar as tsg
from . import template_sheet_structure as tss
from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

TIMEOUT_S = 6.0
FIXED_MIN = 0.5   # FIXED-question lab 2026-10-13 (fixed_lab/scored_wording.json): precision 0.93, recall 0.97 at 0.5
# The criteria noul won the lab (AUC 0.96 with the pre-filters below, against 0.67 for the earlier plain question).
# The request is the lab's exact shape (fixed_lab/wording_round.py, arm B): the sentence follows "SENTENCE:" in the
# instructions, and the state is FIXED_STATE.
FIXED_STATE = "Statements from a radiology report template."
FIXED_INSTRUCTIONS = ("Could this SENTENCE from a radiology report template differ between patients having this same "
                      "scan?")
FIXED_CRITERIA = {
    "true": "The sentence reports something that can differ between patients having this same scan: a finding, a "
            "measurement, whether something was given or achieved, the patient's condition or cooperation, a "
            "limitation.",
    "false": "The sentence describes the standard protocol, equipment, technique, reporting workflow, sign-off or a "
             "fill-in field that is the same for every patient."}

# Structural pre-filters, applied before Jev (never judgements of meaning): a line with a {slot} is filled per case,
# and a sign-off line is the reporter's, so neither is an "Always printed" card. The grammar has no sign-off section
# role, so sign-off is this tiny anchored backstop pattern; keep it small.
_SLOT = re.compile(r"\{[^{}]+\}")
_SIGN_OFF = re.compile(r"^\s*(?:reported\s+by|reporting\s+radiologist|dr\b|frcr\b|gmc\b|signed\s+(?:by|off)\b|electronically\s+signed)", re.I)


def q_fixed(text: str) -> dict:
    """The FIXED-line question for one sentence (shaped like template_brief.q_condition)."""
    return {"type": "noul", "instructions": f"{FIXED_INSTRUCTIONS} SENTENCE: {text}", "criteria": dict(FIXED_CRITERIA)}


def _prefiltered(text: str) -> bool:
    return bool(_SLOT.search(text) or _SIGN_OFF.match(text))


def _clean(sheet: str) -> Optional[tss.SheetStructure]:
    if not tsg.is_grammar_sheet(sheet or ""):
        return None
    res = tsg.parse_sheet(sheet, mode="template")
    return None if res.errors else res.structure


def fixed_candidates(st: tss.SheetStructure, ledger: List[dict]) -> List[str]:
    """FIXED texts printed for every patient and not yet decided. Only the ledger's own lines are left out (a decided
    concept's wordings, a decided fixed line); the default of an undecided concept is checked like any other line,
    so a default with the wrong polarity still shows up (a standard concept's default keeps its candidacy although its
    standard rule targets it). A FIXED line a non-standard context rule targets is conditional: item 1's resolver
    decides it per case at Generate, so it is not "always printed" and not a candidate."""
    owned = (td.concept_texts(ledger) | {norm_key(e["key"]) for e in ledger if e["kind"] == "fixed"}
             | _conditional(st))
    out, seen = [], set()
    for f in st.fixed_blocks:
        k = norm_key(f.text)
        if k in owned or k in seen:
            continue
        seen.add(k)
        out.append(f.text)
    return out


def _conditional(st: tss.SheetStructure) -> Set[str]:
    """The lines a context rule outside the standard concepts targets (REPLACE / SUPPRESS) or prints (USE /
    REPLACE WITH): resolved per case, never printed for every patient."""
    out: Set[str] = set()
    for r in st.rules:
        if r.condition_source == "context" and not td.concept_of_condition(r.condition):
            out |= {norm_key(t) for t in (r.target, r.then_text) if t}
    return out


def _targeted(st: tss.SheetStructure) -> Set[str]:
    return {norm_key(r.target) for r in st.rules if r.condition_source == "context" and r.target}


JEV_BATCH = 10   # questions per Jev call (as the FIXED-question lab); larger sets go as parallel calls


async def _noul_batched(instructions: List, state: str, transport=None, what: str = "jev") -> List[float]:
    """One noul score per question (an instruction string, or a question dict), JEV_BATCH questions per call, the
    calls in parallel. Raises on any failure (a timeout is logged first)."""
    from .jev_client import JEV_MODEL, jev_post

    async def one(chunk: List[str]) -> List[float]:
        qs = {f"q{i}": t if isinstance(t, dict) else {"type": "noul", "instructions": t}
              for i, t in enumerate(chunk)}
        r = await jev_post({"model": JEV_MODEL, "state": state, "questions": qs},
                           os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        out = []
        for i in range(len(chunk)):
            v = (ans.get(f"q{i}") or {}).get("noul")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError("jev: incomplete answers")
            out.append(float(v))
        return out

    chunks = [instructions[i:i + JEV_BATCH] for i in range(0, len(instructions), JEV_BATCH)]
    try:
        parts = await asyncio.gather(*(one(c) for c in chunks))
    except Exception as e:
        if "timeout" in type(e).__name__.lower():
            logger.warning("[sheet-checks] %s: Jev timed out (%d questions in %d calls)", what, len(instructions),
                           len(chunks))
        raise
    return [s for p in parts for s in p]


async def _jev_scores(texts: List[str], transport=None) -> List[float]:
    return await _noul_batched([q_fixed(t) for t in texts],
                               FIXED_STATE, transport, what="fixed")


async def fixed_flags(st: tss.SheetStructure, ledger: List[dict], transport=None) -> List[str]:
    """The FIXED lines to show as "Always printed" cards. Raises when Jev fails (the caller shows no such cards)."""
    texts = [t for t in fixed_candidates(st, ledger) if not _prefiltered(t)]
    targeted = _targeted(st)   # roadmap §4(a): the default-plus-context-rule pattern is legal for the backstop
    backstop = [t for t in texts if tsg.absence_worded(t) and norm_key(t) not in targeted]
    rest = [t for t in texts if t not in backstop]
    scores = await _jev_scores(rest, transport) if rest else []
    flagged = set(backstop) | {t for t, s in zip(rest, scores) if s >= FIXED_MIN}
    return [t for t in texts if t in flagged]


DUP_MIN = 0.5   # lab-set (scripts/rules_step_lab.py dups)
DUP_MAX_QUESTIONS = 120   # (decided concept, line) pairs asked per check; the rest are logged as truncated


def duplicate_candidates(st: tss.SheetStructure, ledger: List[dict]) -> List[dict]:
    """Lines the ledger does not own that a decided concept could also be stating in every report: FIXED lines and
    the template's unconditional NEGATIVE lines. A line a non-standard context rule targets or prints is conditional
    (resolved per case) and is left out. Each as {"text", "ledger_kind", "key"}: the ledger item a card records."""
    owned = td.concept_texts(ledger) | _conditional(st)   # (decided lines are skipped below, by their ledger key)
    paras = {p.id: p.name for p in st.paragraphs}
    found = [(f.text, "fixed", f.text) for f in st.fixed_blocks]
    found += [(n.text, "normal", td.negative_key(paras[n.paragraph], n.text)) for n in st.negatives
              if n.paragraph in paras and n.origin == "template" and not n.condition]
    out: List[dict] = []
    seen: Set[str] = set()
    for text, kind, key in found:
        k = norm_key(text)
        if k in owned or k in seen or td.find(ledger, kind, key) is not None:   # an answered card stays answered
            continue
        seen.add(k)
        out.append({"text": text, "ledger_kind": kind, "key": key})
    return out


async def concept_duplicates(st: tss.SheetStructure, ledger: List[dict], transport=None) -> List[dict]:
    """Style cards for a line that may state a decided concept a second time (Jev: the concept's own question over
    each line the ledger does not own). Raises when Jev fails."""
    decided = [e["key"] for e in ledger if e["kind"] == "concept" and e["key"] in td.CONCEPTS]
    lines = duplicate_candidates(st, ledger)
    if not decided or not lines:
        return []
    pairs = [(c, x) for c in decided for x in lines]
    if len(pairs) > DUP_MAX_QUESTIONS:
        logger.info("[sheet-checks] duplicates: %d questions truncated to %d", len(pairs), DUP_MAX_QUESTIONS)
        pairs = pairs[:DUP_MAX_QUESTIONS]
    scores = await _noul_batched([f"{td.CONCEPTS[c].question} REPORT: {x['text']}" for c, x in pairs],
                                 "Each question quotes one REPORT sentence from a template.", transport,
                                 what="duplicates")
    out, seen = [], set()
    for (c, x), v in zip(pairs, scores):
        if v >= DUP_MIN and x["key"] not in seen:
            seen.add(x["key"])
            out.append(trc.duplicate_card(x["text"], td.CONCEPTS[c].label, x["ledger_kind"], x["key"]))
    return out


def _line_order(sheet: str, raws: List[str]) -> List[int]:
    lines = sheet.split("\n")
    taken: Set[int] = set()
    out = []
    for raw in raws:
        i = next((k for k, ln in enumerate(lines) if k not in taken and ln == raw), len(lines))
        taken.add(i)
        out.append(i)
    return out


def normal_report(sheet: str, st: tss.SheetStructure) -> List[dict]:
    """[{"section", "header", "sentences": [{"key", "text", "kind", "paragraph"}]}] for every non-impression section
    with NORMAL / NEGATIVE lines, in section order; sentences in sheet order."""
    paras = {p.id: p.name for p in st.paragraphs}
    units = []
    for n in st.normals:
        if n.paragraph:
            units.append((n.source_line, n.section, {"key": td.normal_key(paras[n.paragraph], n.structure),
                                                     "text": n.text, "kind": "normal", "paragraph": paras[n.paragraph]}))
    for n in st.negatives:
        if n.paragraph and n.origin == "template" and not n.condition:
            units.append((n.source_lines[0], n.section, {"key": td.negative_key(paras[n.paragraph], n.text),
                                                         "text": n.text, "kind": "negative",
                                                         "paragraph": paras[n.paragraph]}))
    order = _line_order(sheet, [u[0] for u in units])
    units = [u for _, u in sorted(zip(order, units), key=lambda x: x[0])]
    out = []
    for s in sorted(st.sections, key=lambda s: s.order):
        if s.role == "impression":
            continue
        sentences = [u[2] for u in units if u[1] == s.name]
        if sentences:
            out.append({"section": s.name, "header": s.header or s.name.title(), "sentences": sentences})
    return out


def uncovered(st: tss.SheetStructure) -> List[dict]:
    """Cards for structures a findings paragraph COVERS with no NORMAL line."""
    findings = {s.name for s in st.sections if s.role == "findings"}
    out = []
    for p in st.paragraphs:
        if p.section not in findings:
            continue
        have = {td.name_key(n.structure) for n in st.normals if n.paragraph == p.id}
        out += [trc.uncovered_card(p.name, c) for c in p.covers if td.name_key(c) not in have]
    return out


async def sheet_checks(sheet: str, ledger: List[dict], transport=None) -> dict:
    """Everything the Style step shows. Fail-soft per part: a part that fails is empty and named in "errors"."""
    out = {"fixed_cards": [], "duplicate_cards": [], "normal_report": [], "uncovered_cards": [], "unmatched_cards": [],
           "stale_quotes": [], "errors": []}
    st = _clean(sheet)
    if st is None:
        out["errors"].append("parse")
        return out
    ledger = td.clean_ledger(ledger)
    try:
        res = tla.apply_ledger(sheet, ledger)
        out["stale_quotes"] = res.stale_quotes
        out["unmatched_cards"] = trc.unmatched_cards(res.unmatched)   # the same cards /decide shows at review
    except Exception as e:
        logger.warning("[sheet-checks] ledger check failed: %s", type(e).__name__)
        out["errors"].append("ledger")
    for name, part in (("normal_report", lambda: normal_report(sheet, st)), ("uncovered_cards", lambda: uncovered(st))):
        try:
            out[name] = part()
        except Exception as e:
            logger.warning("[sheet-checks] %s failed: %s", name, type(e).__name__)
            out["errors"].append(name)
    try:
        out["duplicate_cards"] = await concept_duplicates(st, ledger, transport)
    except Exception as e:
        logger.warning("[sheet-checks] duplicate check failed: %s", type(e).__name__)
        out["errors"].append("duplicates")
    dup = {td.match_key("fixed", c["title"]) for c in out["duplicate_cards"]}   # one card per line
    try:
        out["fixed_cards"] = [trc.fixed_card(t) for t in await fixed_flags(st, ledger, transport)
                              if td.match_key("fixed", t) not in dup]
    except Exception as e:
        logger.warning("[sheet-checks] fixed check failed: %s", type(e).__name__)
        out["errors"].append("fixed")
    return out
