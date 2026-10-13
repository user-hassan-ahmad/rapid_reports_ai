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
- concept_duplicates: a FIXED line, a template NEGATIVE or a non-standard context rule's sentence the ledger does not
  own that Jev says states a decided concept again ("may be stated twice"). A NEGATIVE's card acts on the NEGATIVE
  (its normal-kind ledger key), never as a fixed entry.
- sheet_checks: all of the above plus the ledger entries that could not be matched (cards at the next review).
Every Jev question is case-agnostic (structural wording only)."""
from __future__ import annotations

import logging
import os
from typing import List, Optional, Set

from . import template_decisions as td
from . import template_ledger_apply as tla
from . import template_rules_cards as trc
from . import template_sheet_grammar as tsg
from . import template_sheet_structure as tss
from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

TIMEOUT_S = 6.0
FIXED_MIN = 0.5   # lab-set (scripts/rules_step_lab.py fixed)
FIXED_QUESTION = ("This SENTENCE is printed in every report of this scan type. It could be false for a different "
                  "patient having this scan: {s}")


def _clean(sheet: str) -> Optional[tss.SheetStructure]:
    if not tsg.is_grammar_sheet(sheet or ""):
        return None
    res = tsg.parse_sheet(sheet, mode="template")
    return None if res.errors else res.structure


def fixed_candidates(st: tss.SheetStructure, ledger: List[dict]) -> List[str]:
    """FIXED texts printed for every patient and not yet decided. Only the ledger's own lines are left out (a decided
    concept's wordings, a decided fixed line); the default of an undecided concept is checked like any other line,
    so a default with the wrong polarity still shows up."""
    owned = td.concept_texts(ledger) | {norm_key(e["key"]) for e in ledger if e["kind"] == "fixed"}
    out, seen = [], set()
    for f in st.fixed_blocks:
        k = norm_key(f.text)
        if k in owned or k in seen:
            continue
        seen.add(k)
        out.append(f.text)
    return out


def _targeted(st: tss.SheetStructure) -> Set[str]:
    return {norm_key(r.target) for r in st.rules if r.condition_source == "context" and r.target}


async def _jev_scores(texts: List[str], transport=None) -> List[float]:
    from .jev_client import JEV_MODEL, jev_post
    qs = {f"f{i}": {"type": "noul", "instructions": FIXED_QUESTION.format(s=t)} for i, t in enumerate(texts)}
    r = await jev_post({"model": JEV_MODEL, "state": "Statements from a radiology report template.", "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out = []
    for i in range(len(texts)):
        v = (ans.get(f"f{i}") or {}).get("noul")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("jev: incomplete answers")
        out.append(float(v))
    return out


async def fixed_flags(st: tss.SheetStructure, ledger: List[dict], transport=None) -> List[str]:
    """The FIXED lines to show as "Always printed" cards. Raises when Jev fails (the caller shows no such cards)."""
    texts = fixed_candidates(st, ledger)
    targeted = _targeted(st)   # roadmap §4(a): the default-plus-context-rule pattern is legal for the backstop
    backstop = [t for t in texts if tsg._ABSENCE_START.match(t) and norm_key(t) not in targeted]
    rest = [t for t in texts if t not in backstop]
    scores = await _jev_scores(rest, transport) if rest else []
    flagged = set(backstop) | {t for t, s in zip(rest, scores) if s >= FIXED_MIN}
    return [t for t in texts if t in flagged]


DUP_MIN = 0.5   # lab-set (scripts/rules_step_lab.py dups)


def duplicate_candidates(st: tss.SheetStructure, ledger: List[dict]) -> List[dict]:
    """Lines the ledger does not own that a decided concept could also be stating: FIXED lines, the template's
    unconditional NEGATIVE lines, and the sentences of context USE / REPLACE rules whose condition is not a standard
    one. Each as {"text", "ledger_kind", "key"}: the ledger item a card on it records."""
    owned = td.concept_texts(ledger)
    paras = {p.id: p.name for p in st.paragraphs}
    found = [(f.text, "fixed", f.text) for f in st.fixed_blocks]
    found += [(n.text, "normal", td.negative_key(paras[n.paragraph], n.text)) for n in st.negatives
              if n.paragraph in paras and n.origin == "template" and not n.condition]
    found += [(r.then_text, "fixed", r.then_text) for r in st.rules if r.condition_source == "context"
              and r.then_text and not td.concept_of_condition(r.condition)]
    out: List[dict] = []
    seen: Set[str] = set()
    for text, kind, key in found:
        k = norm_key(text)
        if k not in owned and k not in seen:
            seen.add(k)
            out.append({"text": text, "ledger_kind": kind, "key": key})
    return out


async def concept_duplicates(st: tss.SheetStructure, ledger: List[dict], transport=None) -> List[dict]:
    """Style cards for a line that may state a decided concept a second time (Jev: the concept's own question over
    each line the ledger does not own). Raises when Jev fails."""
    from .jev_client import JEV_MODEL, jev_post
    decided = [e["key"] for e in ledger if e["kind"] == "concept" and e["key"] in td.CONCEPTS]
    lines = duplicate_candidates(st, ledger)
    if not decided or not lines:
        return []
    pairs = [(c, x) for c in decided for x in lines]
    qs = {f"d{i}": {"type": "noul", "instructions": f"{td.CONCEPTS[c].question} REPORT: {x['text']}"}
          for i, (c, x) in enumerate(pairs)}
    r = await jev_post({"model": JEV_MODEL, "state": "Each question quotes one REPORT sentence from a template.",
                        "questions": qs}, os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out, seen = [], set()
    for i, (c, x) in enumerate(pairs):
        v = (ans.get(f"d{i}") or {}).get("noul")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("jev: incomplete answers")
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
        have = {td._name(n.structure) for n in st.normals if n.paragraph == p.id}
        out += [trc.uncovered_card(p.name, c) for c in p.covers if td._name(c) not in have]
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
    res = tla.apply_ledger(sheet, ledger)
    out["stale_quotes"] = res.stale_quotes
    out["unmatched_cards"] = trc.unmatched_cards(res.unmatched)   # the same cards /decide shows at review
    out["normal_report"] = normal_report(sheet, st)
    out["uncovered_cards"] = uncovered(st)
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
