# Negatives: One Owner per Judgement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every brief label (mandatory and finding-linked negatives, linked-normal atoms, dictated negatives) is tied to the clause the generator wrote. The post-gen check and the review engine then defer to that label instead of re-judging it. "Implicated" becomes an amber AI-layer tint instead of a rail card.

**Architecture:**
- A new pure-code-plus-Jev module `brief_anchor.py` runs inside the post-gen check (`report_review.run_quality_check`) beside the existing Jev contradiction call:
  - pass 1: a code term match, longest term first;
  - pass 2: a Jev "does this sentence say X?" link for leftovers.
- Its anchors drive two rules:
  - a contradiction on a brief-kept clause becomes a conflict card, never a removal;
  - an OMIT clause is removed only with two signals.
- Anchors persist in `quality_check.anchors`. The review engine (`brief_normals`) builds items from them, and the negatives classifier skips every anchored span.
- The brief's mandatory-negatives labeller moves to the full label scheme behind `RR_BRIEF_FULL_LABELS`, gated by a lab.

**Tech Stack:**
- Python 3.12, pydantic, pytest (asyncio_mode=auto), Jev via `report_reconcile._jev`, Qwen via `_run_agent_with_model`;
- SvelteKit + CodeMirror 6 + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-10-09-negatives-one-owner-design.md`
**Branch:** `feat/negatives-one-owner` (already created off `main`; the spec commits are on it).

**Conventions for every task:**
- Run backend tests from `backend/`: `.venv/bin/pytest <path> -q`.
- Run frontend tests from `frontend/`: `npx vitest run <path>`.
- Production text (reports, dictations) never goes into the repo. Lab outputs go to `$RR_LAB_OUT` (the scratchpad), and repo fixtures are synthetic.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not change the generator prompt or the negatives classifier prompt (`review_engine/prompts/negatives.txt`).

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `backend/src/rapid_reports_ai/brief_anchor.py` | create | Labels, units, pass 1 term match, pass 2 Jev link, relocation, the Q2/Q3 rules, the anchor log, the kill switch |
| `backend/src/rapid_reports_ai/report_review.py` | modify | `CheckResult.contra` scores; `run_quality_check(brief_decisions=...)` applies the rules and persists anchors |
| `backend/src/rapid_reports_ai/quick_report_generator.py` | modify | Pass `brief.decisions` into the check |
| `backend/src/rapid_reports_ai/review_engine/negatives.py` | modify | `ai_layer()` label→(label, reason, form); `route()` maps implicated to amber `assumed_normal` |
| `backend/src/rapid_reports_ai/review_engine/brief_normals.py` | modify | Items and conflict cards from `quality_check.anchors`; `owned_spans()`; legacy path kept for old reports |
| `backend/src/rapid_reports_ai/review_engine/engine.py` | modify | `owned` from `brief_normals.owned_spans` |
| `backend/src/rapid_reports_ai/report_reconcile.py` | modify | `QWEN_SYS_FULL`, the wider `NegativeDecision.action`, `_qwen(full=...)` |
| `backend/src/rapid_reports_ai/quick_report_brief.py` | modify | `RR_BRIEF_FULL_LABELS`; compile `DICTATED` / implicated `KEEP` lines; stated finding negatives keep their label |
| `backend/src/rapid_reports_ai/scripts/review_labs/anchor_link_lab.py` | create | Wording lab for the pass 2 question |
| `backend/src/rapid_reports_ai/scripts/review_labs/fixtures/anchor_link_pairs.json` | create | Synthetic (label, sentence, gold) pairs incl. traps |
| `backend/src/rapid_reports_ai/scripts/review_labs/brief_labels_lab.py` | create | Old vs full brief labeller on stored + synthetic cases |
| `backend/src/rapid_reports_ai/scripts/review_labs/fixtures/brief_labels_cases.json` | create | Synthetic cases with gold labels |
| `backend/src/rapid_reports_ai/scripts/review_labs/anchor_replay.py` | create | Code-only stage: anchors + rules on the stored cases |
| `backend/tests/test_brief_anchor.py` | create | Unit tests for `brief_anchor` |
| `backend/tests/test_report_review.py` | modify | The check with anchors |
| `backend/tests/test_review_engine_brief_normals.py` | modify | Items from anchors, conflict cards, owned spans |
| `backend/tests/test_review_engine_negatives.py` | modify | Implicated → amber `assumed_normal` |
| `backend/tests/test_quick_report_brief.py` | modify | Full-label compile |
| `frontend/src/lib/review/editor/decorations.ts` | modify | Amber mark label shows the pointer |
| `frontend/src/lib/review/editor/field.ts` | modify | `AI_BREAKDOWN` amber entry relabelled |
| `docs/model-migration/parameter-ledger.md` | modify | Ledger entry |

---

### Task 1: `brief_anchor` labels and key terms

**Files:**
- Create: `backend/src/rapid_reports_ai/brief_anchor.py`
- Test: `backend/tests/test_brief_anchor.py`

- [ ] **Step 1: Write the failing tests**

```python
"""brief_anchor (spec 2026-10-09-negatives-one-owner-design §3.1): brief labels tied to the clauses the generator
wrote. Synthetic cases only, no live model calls."""
import pytest

from rapid_reports_ai import brief_anchor as ba


@pytest.mark.parametrize("text,term", [
    ("No mediastinal invasion identified", "mediastinal invasion"),
    ("No osseous lesion identified in the visualised thoracic skeleton", "osseous lesion"),
    ("No definite chest wall invasion by the right upper lobe mass", "chest wall invasion"),
    ("No contralateral pleural nodularity on CT thorax", "contralateral pleural nodularity"),
    ("There is no free fluid.", "free fluid"),
    ("The mass abuts the oblique fissure with no definite chest wall involvement", "chest wall involvement"),
    ("No pulmonary emboli", "pulmonary emboli"),
    ("No retropulsion at T7", "retropulsion at T7"),               # a level is part of the claim
    ("No fracture in the left distal radius", "fracture in the left distal radius"),   # so is a side
])
def test_key_term_strips_boilerplate(text, term):
    assert ba.key_term(text) == term


DECISIONS = {
    "negatives": [
        {"text": "No pleural effusion identified", "action": "contradicted", "source": "sheet",
         "dictated_finding": "Small right pleural effusion"},
        {"text": "No contralateral pleural effusion identified", "action": "keep",
         "source": "finding:Pleural effusion", "dictated_finding": ""},
    ],
    "normals": [
        {"linked": True, "pid": "P1", "rendered": "No mediastinal lymphadenopathy.", "atoms": [
            {"id": "N1", "term": "Mediastinal lymphadenopathy", "text": "No mediastinal lymphadenopathy.",
             "label": "implicated", "action": "implicated", "pointer": "right hilar nodes 14 mm"}]},
        {"text": "The bones are unremarkable.", "action": "keep"},          # not linked: no label
    ],
    "dictated_negatives": ["No pulmonary emboli"],
}


def test_brief_labels_flattens_every_source_with_stable_refs():
    labs = ba.brief_labels(DECISIONS)
    assert [(l.ref, l.term, l.action, l.source) for l in labs] == [
        ("neg:0", "pleural effusion", "contradicted", "sheet"),
        ("neg:1", "contralateral pleural effusion", "keep", "finding:Pleural effusion"),
        ("atom:P1:N1", "Mediastinal lymphadenopathy", "implicated", "atom"),
        ("dict:0", "pulmonary emboli", "dictated", "dictated"),
    ]
    assert labs[0].pointer == "Small right pleural effusion"
    assert labs[1].pointer == "Pleural effusion"          # a finding-linked negative points at its finding
    assert labs[2].pointer == "right hilar nodes 14 mm"


def test_brief_labels_empty_without_decisions():
    assert ba.brief_labels(None) == [] and ba.brief_labels({}) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: FAIL with `ImportError: cannot import name 'brief_anchor'`

- [ ] **Step 3: Write the module with labels and key terms**

```python
"""Brief labels → the words the generator wrote (spec docs/superpowers/specs/2026-10-09-negatives-one-owner-design.md
§3.1). One owner per judgement: the brief selected and labelled every negative and linked normal before the report was
written; this finds where each one landed so the post-gen check and the review engine defer to that label instead of
re-judging it.

    brief_labels(decisions)          every brief label (mandatory / finding-linked negatives, linked-normal atoms,
                                     dictated negatives) with a stable ref and a key term
    units(report)                    the normal / negative statements of FINDINGS + IMPRESSION, with positions
    match_terms(report, labels, us)  pass 1, code: a label's key term in exactly one unit, longest term first
    link(labels, us)                 pass 2, Jev: "does this sentence say X?" for the labels pass 1 left
    anchor(report, decisions)        both passes; never raises
    relocate(anchors, report)        anchors re-found on the report after the check's own edits
    brief_rules(...)                 spec Q2 / Q3: protect brief-kept clauses, remove OMIT clauses on two signals
    anchor_log(anchors, rules)       counts, unanchored labels, brief errors (logged, never surfaced: spec Q4)

An unanchored label is not an error: the generator dropped or merged it."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from . import linked_normals as ln
from . import report_reconcile as rc

logger = logging.getLogger(__name__)

KEEP = frozenset({"keep", "default", "implicated", "dictated"})
OMIT = frozenset({"contradicted", "expected", "do_not_assert"})

_LEAD = re.compile(r"^\s*(?:no|nil|without|there\s+(?:is|are|was|were)\s+no)\s+", re.I)
_INNER = re.compile(r"\b(?:no|without)\s+(?=\S)", re.I)
_HEDGE = re.compile(r"^(?:definite|definitive|evidence\s+of|any|significant|obvious)\s+", re.I)
_VERB_TAIL = re.compile(r"\s+(?:(?:is|are|was|were)\s+)?(?:identified|seen|present|demonstrated|noted|detected)\b.*$",
                        re.I)
_PLACE_TAIL = re.compile(r"\s+(?:by|on|in|at|within|from|involving)\s+(?:the\s+)?\S.*$", re.I)
# A trailing place phrase is boilerplate ("in the visualised thoracic skeleton") unless it carries a side or a level
# ("at T7", "in the left kidney"): then it is part of the claim and stays in the term.
_QUALIFIER = re.compile(r"\b(?:left|right|bilateral|contralateral|ipsilateral|[CTLS]\d{1,2}(?:/\d)?|segment\s+\w+)\b",
                        re.I)


@dataclass
class Label:
    ref: str
    text: str
    term: str
    action: str
    source: str            # "sheet" | "finding:<key>" | "atom" | "dictated"
    pointer: str = ""


def enabled() -> bool:
    """Kill switch: RR_BRIEF_ANCHOR=0 skips anchoring end to end (today's behaviour)."""
    return os.environ.get("RR_BRIEF_ANCHOR", "1").strip().lower() not in ("0", "false", "off")


def key_term(text: str) -> str:
    """The denied phrase without its boilerplate: "No osseous lesion identified in the visualised thoracic skeleton"
    → "osseous lesion"; "... with no definite chest wall involvement" → "chest wall involvement"."""
    t = (text or "").strip().rstrip(".")
    if _LEAD.match(t):
        t = _LEAD.sub("", t)
    else:
        found = list(_INNER.finditer(t))
        if not found:
            return ""
        t = t[found[-1].end():]
    t = _HEDGE.sub("", t)
    t = _VERB_TAIL.sub("", t)
    m = _PLACE_TAIL.search(t)
    if m and not _QUALIFIER.search(m.group(0)):
        t = t[:m.start()]
    return t.strip(" ,;")


def _pointer(p) -> str:
    p = str(p or "").strip()
    return "" if p in ("-", "->", "—", "none") else p


def brief_labels(decisions: Optional[dict]) -> List[Label]:
    d = decisions or {}
    out: List[Label] = []
    for i, n in enumerate(d.get("negatives") or []):
        term = key_term(n.get("text") or "")
        if not term:
            continue
        src = n.get("source") or "sheet"
        finding = src.split(":", 1)[1] if src.startswith("finding:") else ""
        out.append(Label(f"neg:{i}", n["text"], term, n.get("action") or "keep", src,
                         _pointer(n.get("dictated_finding")) or finding))
    for u in d.get("normals") or []:
        if not isinstance(u, dict) or not u.get("linked"):
            continue
        for a in u.get("atoms") or []:
            if a.get("term"):
                out.append(Label(f"atom:{u.get('pid')}:{a.get('id')}", a.get("text") or a["term"], a["term"],
                                 a.get("action") or "keep", "atom", _pointer(a.get("pointer"))))
    for i, t in enumerate(d.get("dictated_negatives") or []):
        term = key_term(t)
        if term:
            out.append(Label(f"dict:{i}", t, term, "dictated", "dictated"))
    return out
```

`key_term` for "No pulmonary emboli": `_LEAD` matches and nothing trails, so it returns "pulmonary emboli". "There is no free fluid." gives "free fluid".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/brief_anchor.py backend/tests/test_brief_anchor.py
git commit -m "feat(brief-anchor): brief labels and key terms

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Units and pass 1 (code term match)

**Files:**
- Modify: `backend/src/rapid_reports_ai/brief_anchor.py`
- Test: `backend/tests/test_brief_anchor.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
# A synthetic thorax report mirroring the worked case's shapes (spec §1).
REPORT = (
    "FINDINGS:\n"
    "A 3 cm spiculated mass in the right upper lobe abuts the fissure with no definite chest wall involvement and no "
    "mediastinal invasion. A small right pleural effusion accompanies the mass. The right hilar nodes measure up to "
    "1.4 cm; no contralateral hilar lymphadenopathy or vascular encasement.\n\n"
    "No paratracheal, subcarinal or para-aortic lymphadenopathy. The great vessels are patent with no pulmonary "
    "emboli.\n\n"
    "No contralateral pleural effusion or pleural thickening. The liver is unremarkable with no hepatic lesion.\n\n"
    "IMPRESSION:\n"
    "Right upper lobe malignancy with ipsilateral hilar nodes and a small effusion.\n")

DEC = {
    "negatives": [
        {"text": "No pleural effusion identified", "action": "contradicted", "source": "sheet",
         "dictated_finding": "Small right pleural effusion"},
        {"text": "No contralateral pleural effusion identified", "action": "keep",
         "source": "finding:Pleural effusion"},
        {"text": "No pleural thickening identified", "action": "keep", "source": "finding:Pleural effusion"},
        {"text": "No mediastinal invasion identified", "action": "keep", "source": "finding:Lung mass"},
        {"text": "No contralateral hilar lymphadenopathy identified", "action": "keep",
         "source": "finding:Hilar lymphadenopathy"},
        {"text": "No hepatic lesion identified", "action": "keep", "source": "sheet"},
        {"text": "No ascites identified", "action": "keep", "source": "sheet"},          # never written
    ],
    "normals": [
        {"linked": True, "pid": "P1", "atoms": [
            {"id": "N1", "term": "Hilar lymphadenopathy", "text": "No hilar lymphadenopathy.",
             "action": "do_not_assert"},
            {"id": "N2", "term": "Mediastinal lymphadenopathy", "text": "No mediastinal lymphadenopathy.",
             "action": "implicated", "pointer": "right hilar nodes 1.4 cm"}]},
        {"linked": True, "pid": "P2", "atoms": [
            {"id": "N3", "term": "Liver", "text": "The liver is unremarkable.", "action": "keep"}]},
    ],
    "dictated_negatives": ["No pulmonary emboli"],
}


def _by_ref(anchors):
    return {a.ref: a for a in anchors}


def test_units_are_normal_sentences_and_negative_tails_never_positive_heads():
    texts = [u.text for u in ba.units(REPORT)]
    assert "A small right pleural effusion accompanies the mass." not in texts
    assert any(t.startswith("contralateral hilar lymphadenopathy") for t in texts)     # tail of a finding sentence
    assert "No contralateral pleural effusion or pleural thickening." in texts
    for u in ba.units(REPORT):
        assert REPORT[u.start:u.end] == u.text


def test_pass_one_longest_term_wins_and_the_shorter_omit_is_shadowed():
    got, left = ba.match_terms(REPORT, ba.brief_labels(DEC), ba.units(REPORT))
    keep = got["neg:1"]
    assert keep.how == "term" and keep.span_text.lower() == "contralateral pleural effusion"
    omit = got["neg:0"]                       # its only hit sits inside "contralateral pleural effusion"
    assert omit.how == "none" and omit.shadowed_by == "neg:1"
    assert got["neg:2"].how == "term" and got["neg:5"].how == "term" and got["atom:P2:N3"].how == "term"
    assert got["neg:4"].span_text.lower() == "contralateral hilar lymphadenopathy"
    assert got["atom:P1:N1"].shadowed_by == "neg:4"     # "hilar lymphadenopathy" lives inside the kept negative
    assert got["dict:0"].how == "term"
    assert {l.ref for l in left} == {"neg:6", "atom:P1:N2"}    # never written / reworded: pass 2's job


def test_two_labels_with_disjoint_terms_share_one_sentence():
    got, _ = ba.match_terms(REPORT, ba.brief_labels(DEC), ba.units(REPORT))
    assert got["neg:5"].unit == got["atom:P2:N3"].unit == "The liver is unremarkable with no hepatic lesion."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.brief_anchor' has no attribute 'units'`

- [ ] **Step 3: Implement units and pass 1** (add to `brief_anchor.py` after `brief_labels`)

```python
_NORMAL = re.compile(r"\b(?:no|not|nil|without|normal(?:ly)?|unremarkable|patent|intact|clear|preserved|"
                     r"maintained|non-?dilated|undilated)\b", re.I)


@dataclass
class Unit:
    text: str
    start: int
    end: int


@dataclass
class Anchor:
    ref: str
    action: str
    source: str
    pointer: str = ""
    how: str = "none"                 # "term" | "jev" | "none" | "removed" (its clause was edited out)
    span: Optional[List[int]] = None  # the label's words (term) or the whole unit (jev)
    span_text: str = ""
    unit: str = ""                    # the statement the span sits in
    offset: int = 0                   # span start minus unit start (relocation)
    p: Optional[float] = None         # pass 2 probability
    shadowed_by: Optional[str] = None # its only hit is held by this (longer or dictated) label


def units(report: str) -> List[Unit]:
    """Normal / negative statements of FINDINGS + IMPRESSION: a whole normal sentence, or the negative / normal tails
    of a finding sentence ("The nodes measure 14 mm; no contralateral lymphadenopathy" → the tail). Positive heads are
    never units."""
    from .report_review import _sentence_positions, report_sections
    from .review_engine.jev_pass import split_tails   # lazy: review_engine imports report_review
    out: List[Unit] = []
    for sec in report_sections(report):
        a = report.find(sec) if sec else -1
        if a < 0:
            continue
        for s, i, j in _sentence_positions(report, a, a + len(sec)):
            sp = split_tails(s)
            if sp:
                for tail in sp[1]:
                    words = _LEAD.sub("", tail).rstrip(".")
                    k = s.find(words)
                    if words and k >= 0:
                        out.append(Unit(words, i + k, i + k + len(words)))
            elif _NORMAL.search(s):
                out.append(Unit(s, i, j))
    return out


def _rank(lab: Label) -> Tuple[int, int]:
    """Longest term first; among equal terms a dictated label, then a kept one, then an OMIT one."""
    return (-len(lab.term), 0 if lab.action == "dictated" else (1 if lab.action in KEEP else 2))


def _anchor(lab: Label, **kw) -> Anchor:
    return Anchor(lab.ref, lab.action, lab.source, lab.pointer, **kw)


def match_terms(report: str, labels: List[Label], us: List[Unit]) -> Tuple[Dict[str, Anchor], List[Label]]:
    """Pass 1 → ({ref: Anchor}, labels for pass 2). A label anchors when its term occurs in exactly one unit at a
    position no earlier-ranked label holds. A label whose every hit is held is shadowed (merged into the holder);
    no hit, or several free hits, goes to pass 2."""
    taken: List[Tuple[int, int, str]] = []
    got: Dict[str, Anchor] = {}
    left: List[Label] = []
    for lab in sorted(labels, key=_rank):
        free: List[Tuple[int, int, Unit]] = []
        held: Optional[str] = None
        for u in us:
            pos = 0
            while (m := ln.term_span(u.text, lab.term, pos)) is not None:
                s, e = u.start + m[0], u.start + m[1]
                owner = next((r for a, b, r in taken if a < e and s < b), None)
                if owner is None:
                    free.append((s, e, u))
                elif held is None:
                    held = owner
                pos = m[1]
        if len(free) == 1:
            s, e, u = free[0]
            taken.append((s, e, lab.ref))
            got[lab.ref] = _anchor(lab, how="term", span=[s, e], span_text=report[s:e], unit=u.text,
                                   offset=s - u.start)
        elif not free and held is not None:
            got[lab.ref] = _anchor(lab, how="none", shadowed_by=held)
        else:
            left.append(lab)
    return got, left
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: PASS. If `test_units_...` fails on the tail text, print `ba.units(REPORT)` and adjust only the tail-locating code. `split_tails` returns tails as "No <words>" or the normal part verbatim.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/brief_anchor.py backend/tests/test_brief_anchor.py
git commit -m "feat(brief-anchor): statement units and pass 1 term match

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Pass 2 (Jev link), `anchor()`, `relocate()`

**Files:**
- Modify: `backend/src/rapid_reports_ai/brief_anchor.py`
- Test: `backend/tests/test_brief_anchor.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
def _jev_says(yes):
    """Fake rc._jev: P=0.95 when (sentence contains key, label text contains value) for any pair in `yes`."""
    calls = []

    async def fake(state, qs):
        calls.append((state, qs))
        out = {}
        for k, q in qs.items():
            hit = any(s in state and t in q["instructions"] for s, t in yes)
            out[k] = {"noul": 0.95 if hit else 0.05}
        return out
    fake.calls = calls
    return fake


async def test_pass_two_links_a_reworded_atom_to_its_sentence():
    fake = _jev_says([("paratracheal", "mediastinal lymphadenopathy")])
    anchors = _by_ref(await ba.anchor(REPORT, DEC, jev=fake))
    a = anchors["atom:P1:N2"]
    assert a.how == "jev" and a.unit.startswith("No paratracheal") and a.p == 0.95
    assert anchors["neg:6"].how == "none"                      # "ascites" shares no word with any unit: not asked
    asked = {q["instructions"] for _, qs in fake.calls for q in qs.values()}
    assert not any("ascites" in q for q in asked)


async def test_pass_two_needs_one_clear_winner():
    fake = _jev_says([("paratracheal", "mediastinal"), ("contralateral hilar", "mediastinal")])
    anchors = _by_ref(await ba.anchor(REPORT, DEC, jev=fake))
    assert anchors["atom:P1:N2"].how == "none"                 # two sentences at P >= LINK_MIN: ambiguous


async def test_a_jev_failure_leaves_pass_two_labels_unanchored():
    async def boom(state, qs):
        raise RuntimeError("jev down")
    anchors = _by_ref(await ba.anchor(REPORT, DEC, jev=boom))
    assert anchors["atom:P1:N2"].how == "none" and anchors["neg:1"].how == "term"


def test_relocate_follows_an_earlier_removal_and_marks_a_removed_clause():
    got, _ = ba.match_terms(REPORT, ba.brief_labels(DEC), ba.units(REPORT))
    anchors = list(got.values())
    edited = REPORT.replace("The great vessels are patent with no pulmonary emboli.", "")
    moved = _by_ref(ba.relocate(anchors, edited))
    a = moved["neg:5"]
    assert edited[a.span[0]:a.span[1]] == a.span_text == "hepatic lesion"
    assert moved["dict:0"].how == "removed" and moved["dict:0"].span is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'anchor'`

- [ ] **Step 3: Implement** (add to `brief_anchor.py`)

```python
LINK_MIN = 0.80        # pass 2 acceptance; Task 4's wording lab confirms or moves it
LINK_TIMEOUT_S = 4.0
LINK_WORDING = 'Read only this sentence. It says, in any wording: "{t}".'


def q_says(lab: Label) -> dict:
    return {"type": "noul", "instructions": LINK_WORDING.format(t=lab.text.strip().rstrip(".")),
            "criteria": {"true": "the sentence says it", "false": "the sentence does not say it"}}


def _words(s: str) -> set:
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


async def link(labels: List[Label], us: List[Unit], jev=None) -> Dict[str, Anchor]:
    """Pass 2 → {ref: Anchor}: one Jev request per unit (the state is the sentence alone), asking each label that
    shares a content word with it. A label anchors to the unit Jev scores at P >= LINK_MIN when no other unit does."""
    jev = jev or rc._jev
    asks: Dict[int, Dict[str, dict]] = {}
    for k, lab in enumerate(labels):
        w = _words(lab.term)
        for n, u in enumerate(us):
            if w & _words(u.text):
                asks.setdefault(n, {})[f"l{k}"] = q_says(lab)
    if not asks:
        return {}

    async def one(n: int):
        return n, await asyncio.wait_for(jev(us[n].text, asks[n]), LINK_TIMEOUT_S)
    results = await asyncio.gather(*(one(n) for n in asks), return_exceptions=True)
    scores: Dict[int, List[Tuple[float, int]]] = {}
    for r in results:
        if isinstance(r, BaseException):
            logger.warning("brief anchor: Jev link failed (%s: %s)", type(r).__name__, str(r)[:200])
            continue
        n, ans = r
        for qk in asks[n]:
            try:
                p = float(ans[qk]["noul"])
            except (KeyError, TypeError, ValueError):
                continue
            scores.setdefault(int(qk[1:]), []).append((p, n))
    out: Dict[str, Anchor] = {}
    for k, ps in scores.items():
        ps.sort(reverse=True)
        if ps[0][0] >= LINK_MIN and (len(ps) == 1 or ps[1][0] < LINK_MIN):
            lab, u = labels[k], us[ps[0][1]]
            out[lab.ref] = _anchor(lab, how="jev", span=[u.start, u.end], span_text=u.text, unit=u.text, offset=0,
                                   p=round(ps[0][0], 3))
    return out


async def anchor(report: str, decisions: Optional[dict], jev=None) -> List[Anchor]:
    """Both passes, one Anchor per brief label in label order. Never raises."""
    try:
        labels = brief_labels(decisions)
        if not labels:
            return []
        us = units(report)
        got, left = match_terms(report, labels, us)
        if left:
            got.update(await link(left, us, jev))
        return [got.get(l.ref) or _anchor(l) for l in labels]
    except Exception as e:  # noqa: BLE001 - anchoring never blocks the report
        logger.warning("brief anchor failed (%s: %s)", type(e).__name__, str(e)[:200])
        return []


def relocate(anchors: List[Anchor], report: str) -> List[Anchor]:
    """The anchors re-found on `report` (the check's edits shift positions): the unit text, then the span inside it.
    A unit no longer in the report is "removed"."""
    out: List[Anchor] = []
    for a in anchors:
        if a.how not in ("term", "jev"):
            out.append(a)
            continue
        i = report.find(a.unit)
        k = i + a.offset
        if i < 0 or report[k:k + len(a.span_text)] != a.span_text:
            out.append(Anchor(**{**asdict(a), "how": "removed", "span": None}))
        else:
            out.append(Anchor(**{**asdict(a), "span": [k, k + len(a.span_text)]}))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/brief_anchor.py backend/tests/test_brief_anchor.py
git commit -m "feat(brief-anchor): pass 2 Jev link, anchor(), relocate()

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Wording lab for the pass 2 question (GATE)

This gates pass 2. If the gate fails, set `LINK_MIN = 1.01` in `brief_anchor.py`. Pass 2 then never anchors, which is safe (spec §4). Record the result either way.

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/fixtures/anchor_link_pairs.json`
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/anchor_link_lab.py`

- [ ] **Step 1: Write the synthetic pairs fixture** (gold `true` = the sentence says the label; `trap` = an overlap the gate must never link)

```json
[
 {"id": "t01", "label": "No mediastinal lymphadenopathy", "sentence": "No paratracheal, subcarinal or para-aortic lymphadenopathy.", "gold": true},
 {"id": "t02", "label": "No pleural effusion", "sentence": "No contralateral pleural effusion or pleural thickening.", "gold": false, "trap": "contralateral"},
 {"id": "t03", "label": "No contralateral pleural effusion", "sentence": "No contralateral pleural effusion or pleural thickening.", "gold": true},
 {"id": "t04", "label": "No hilar lymphadenopathy", "sentence": "No contralateral hilar lymphadenopathy or vascular encasement.", "gold": false, "trap": "contralateral"},
 {"id": "t05", "label": "No chest wall invasion", "sentence": "The mass abuts the fissure with no definite chest wall involvement.", "gold": true},
 {"id": "t06", "label": "The adrenal glands are unremarkable", "sentence": "The spleen, pancreas, right adrenal and kidneys are unremarkable.", "gold": false, "trap": "side"},
 {"id": "t07", "label": "The right adrenal gland is unremarkable", "sentence": "The spleen, pancreas, right adrenal and kidneys are unremarkable.", "gold": true},
 {"id": "t08", "label": "No pulmonary nodule", "sentence": "No additional pulmonary nodule.", "gold": false, "trap": "additional"},
 {"id": "t09", "label": "No additional pulmonary nodule", "sentence": "No further pulmonary nodules are seen.", "gold": true},
 {"id": "t10", "label": "No hepatic lesion", "sentence": "The liver is unremarkable with no focal lesion.", "gold": true},
 {"id": "t11", "label": "No biliary dilatation", "sentence": "The intrahepatic and extrahepatic bile ducts are not dilated.", "gold": true},
 {"id": "t12", "label": "No intrahepatic biliary dilatation", "sentence": "The common bile duct is not dilated.", "gold": false, "trap": "level"},
 {"id": "t13", "label": "No free fluid", "sentence": "There is no ascites.", "gold": true},
 {"id": "t14", "label": "No pericardial effusion", "sentence": "The heart and pericardium are unremarkable.", "gold": true},
 {"id": "t15", "label": "No pericardial invasion", "sentence": "The heart and pericardium are unremarkable.", "gold": false, "trap": "different finding"},
 {"id": "t16", "label": "No hydronephrosis", "sentence": "The kidneys are unremarkable with no hydronephrosis.", "gold": true},
 {"id": "t17", "label": "No left hydronephrosis", "sentence": "There is no right hydronephrosis.", "gold": false, "trap": "side"},
 {"id": "t18", "label": "No midline shift", "sentence": "There is no mass effect or midline shift.", "gold": true},
 {"id": "t19", "label": "No hydrocephalus", "sentence": "The ventricles are normal in size.", "gold": true},
 {"id": "t20", "label": "No intraventricular extension", "sentence": "The ventricles are normal in size.", "gold": false, "trap": "different finding"},
 {"id": "t21", "label": "No fracture", "sentence": "No acute fracture of the distal radius.", "gold": false, "trap": "narrower"},
 {"id": "t22", "label": "No fracture of the distal radius", "sentence": "No acute fracture of the distal radius.", "gold": true},
 {"id": "t23", "label": "No joint effusion", "sentence": "The cruciate ligaments are intact.", "gold": false},
 {"id": "t24", "label": "No cord compression", "sentence": "The spinal cord is normal in calibre and signal.", "gold": true},
 {"id": "t25", "label": "No retropulsion at T7", "sentence": "No retropulsion at T8.", "gold": false, "trap": "level"},
 {"id": "t26", "label": "No pneumothorax", "sentence": "The lungs are clear with no pneumothorax.", "gold": true},
 {"id": "t27", "label": "No vascular encasement", "sentence": "No contralateral hilar lymphadenopathy or vascular encasement.", "gold": true},
 {"id": "t28", "label": "No peripancreatic lymphadenopathy", "sentence": "No upper abdominal lymphadenopathy.", "gold": false, "trap": "broader"},
 {"id": "t29", "label": "No SMA encasement", "sentence": "The superior mesenteric artery is not involved.", "gold": true},
 {"id": "t30", "label": "No portal vein thrombosis", "sentence": "The portal and splenic veins are patent.", "gold": true}
]
```

- [ ] **Step 2: Write the lab script**

```python
"""Pass 2 wording lab (spec 2026-10-09 §5.1): does Jev tell whether one report sentence says a brief label?

    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab build      # adds stored-case pairs (scratchpad)
    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab run --runs 2
    python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab score --results <jsonl> [--min 0.8]

Gate: accuracy >= 95% at --min, and 0 trap pairs at or above --min. Production text stays under $RR_LAB_OUT/anchor_link/."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rapid_reports_ai import brief_anchor as ba
from rapid_reports_ai import report_reconcile as rc

from . import common

FIXTURE = Path(__file__).parent / "fixtures" / "anchor_link_pairs.json"
ARMS = {
    "S1": ba.LINK_WORDING,
    "S2": 'Read only this sentence. It states that "{t}" holds, for the same structure, side and level, in any wording.',
}


def pairs() -> list:
    out = common.read_json(FIXTURE)
    extra = common.lab_out("anchor_link") / "stored_pairs.json"
    return out + (common.read_json(extra) if extra.exists() else [])


def build() -> None:
    """Stored cases: pass 1 on each saved report; every label pass 1 left × each unit sharing a content word becomes a
    pair with gold null. Label gold by peer read in the JSON (true / false, trap where it applies)."""
    rows = common.metabase(
        "select id, candidate_reports->0->>'content' as report, candidate_reports->0->'brief'->'decisions' as d "
        "from reports where candidate_reports->0->'brief'->'decisions' is not null "
        "and created_at > now() - interval '30 days'")
    out = []
    for r in rows:
        d = r["d"] if isinstance(r["d"], dict) else json.loads(r["d"])
        us = ba.units(r["report"])
        _, left = ba.match_terms(r["report"], ba.brief_labels(d), us)
        for lab in left:
            for u in us:
                if ba._words(lab.term) & ba._words(u.text):
                    out.append({"id": f"{r['id'][:8]}:{lab.ref}:{u.start}", "label": lab.text, "sentence": u.text,
                                "gold": None})
    common.write_json(common.lab_out("anchor_link") / "stored_pairs.json", out)
    print(f"{len(out)} stored pairs; label gold before `run`")


async def _one(arm: str, p: dict) -> dict:
    q = {"type": "noul", "instructions": ARMS[arm].format(t=p["label"].rstrip(".")),
         "criteria": {"true": "the sentence says it", "false": "the sentence does not say it"}}
    ans = await rc._jev(p["sentence"], {"q": q})
    return {"id": p["id"], "arm": arm, "p": float(ans["q"]["noul"])}


async def run(runs: int) -> Path:
    common.load_env()
    todo = [p for p in pairs() if p.get("gold") is not None]
    out = common.out_file("anchor_link", "results", "jsonl")
    with open(out, "w") as f:
        for k in range(runs):
            for arm in ARMS:
                for p in todo:                    # one at a time: Jev only, cheap
                    f.write(json.dumps({**await _one(arm, p), "run": k}) + "\n")
    print(out)
    return out


def score(results: str, lo: float) -> None:
    gold = {p["id"]: p for p in pairs()}
    by: dict = {}
    for r in common.read_jsonl(results):
        by.setdefault(r["arm"], []).append(r)
    for arm, rs in by.items():
        ok = sum((r["p"] >= lo) == gold[r["id"]]["gold"] for r in rs)
        traps = [r["id"] for r in rs if gold[r["id"]].get("trap") and r["p"] >= lo]
        print(f"{arm}: accuracy {ok}/{len(rs)} = {ok / len(rs):.1%}; trap links {len(traps)} {sorted(set(traps))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "score"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--results")
    ap.add_argument("--min", type=float, default=ba.LINK_MIN)
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "run":
        asyncio.run(run(a.runs))
    else:
        score(a.results, a.min)
```

- [ ] **Step 3: Build stored pairs, peer-read gold, run, score**

Run, from `backend/`, with `RR_LAB_OUT` pointing at the session scratchpad:
```bash
.venv/bin/python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab build
# edit $RR_LAB_OUT/anchor_link/stored_pairs.json: set gold true/false (and trap) for every pair by peer read
.venv/bin/python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab run --runs 2
.venv/bin/python -m rapid_reports_ai.scripts.review_labs.anchor_link_lab score --results <printed path>
```
Expected: one accuracy line and one trap line per arm.
- **Gate:** the best arm has accuracy ≥95% and 0 trap links at a threshold between 0.6 and 0.9. Try `--min 0.7`, `0.8` and `0.9`.
- **If the gate passes:** set `LINK_WORDING` (to S2's wording, if S2 wins) and `LINK_MIN` in `brief_anchor.py`, then re-run `tests/test_brief_anchor.py`.
- **If no arm passes:** set `LINK_MIN = 1.01`.

- [ ] **Step 4: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/review_labs/anchor_link_lab.py \
        backend/src/rapid_reports_ai/scripts/review_labs/fixtures/anchor_link_pairs.json \
        backend/src/rapid_reports_ai/brief_anchor.py
git commit -m "lab(brief-anchor): pass 2 wording lab; LINK_MIN=<value> (<arm>: <accuracy>, <traps> trap links)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The Q2/Q3 rules and the anchor log

**Files:**
- Modify: `backend/src/rapid_reports_ai/brief_anchor.py`
- Test: `backend/tests/test_brief_anchor.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
R2 = ("FINDINGS:\nA small right pleural effusion. No contralateral pleural effusion. No pleural effusion. "
      "There is no ascites.\n\nIMPRESSION:\nSmall right effusion.\n")


def _a(ref, action, text, how="term", source="sheet", pointer=""):
    i = R2.index(text)
    return ba.Anchor(ref, action, source, pointer, how, [i, i + len(text)], text, text)


def test_a_contradiction_on_a_kept_clause_is_protected_and_carded():
    anchors = [_a("neg:1", "keep", "contralateral pleural effusion", source="finding:Pleural effusion")]
    rules = ba.brief_rules(R2, anchors, {"No contralateral pleural effusion.": 0.7},
                           flagged=["No contralateral pleural effusion."], review_contra=[])
    assert rules["protect"] == ["No contralateral pleural effusion."] and rules["remove"] == []
    (c,) = rules["conflicts"]
    assert c["reason"] == "brief_kept" and c["refs"] == ["neg:1"] and c["source"] == "finding:Pleural effusion"


def test_an_omit_clause_is_removed_only_with_two_signals():
    i = R2.index("No pleural effusion.") + 3
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "Small right pleural effusion", "term",
                     [i, i + len("pleural effusion")], "pleural effusion", "No pleural effusion.")
    sure = ba.brief_rules(R2, [omit], {"No pleural effusion.": 0.9}, flagged=[], review_contra=[])
    assert sure["remove"] == ["No pleural effusion."] and sure["conflicts"] == []
    weak = ba.brief_rules(R2, [omit], {"No pleural effusion.": 0.3}, flagged=[], review_contra=[])
    assert weak["remove"] == [] and weak["conflicts"][0]["reason"] == "brief_omitted"


def test_dictated_beats_omit_no_removal_no_card_logged_as_brief_error():
    anchors = [_a("dict:0", "dictated", "ascites"),
               ba.Anchor("neg:3", "contradicted", "sheet", "", "none", shadowed_by="dict:0")]
    rules = ba.brief_rules(R2, anchors, {"There is no ascites.": 0.9}, flagged=[], review_contra=[])
    assert rules == {"protect": [], "remove": [], "conflicts": []}
    log = ba.anchor_log(anchors, rules)
    assert log["brief_errors"] == [{"ref": "neg:3", "shadowed_by": "dict:0"}]


def test_anchor_log_counts_and_lists_unanchored():
    anchors = [_a("neg:1", "keep", "contralateral pleural effusion"),
               ba.Anchor("neg:6", "keep", "sheet"),
               ba.Anchor("atom:P1:N2", "implicated", "atom", how="jev", span=[0, 1], span_text="F", unit="F")]
    log = ba.anchor_log(anchors, {"protect": [], "remove": [], "conflicts": []})
    assert (log["labels"], log["by_term"], log["by_jev"]) == (3, 1, 1)
    assert log["unanchored"] == [{"ref": "neg:6", "source": "sheet", "action": "keep"}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: FAIL with `AttributeError: ... no attribute 'brief_rules'`

- [ ] **Step 3: Implement** (add to `brief_anchor.py`)

```python
CONTRA_MIN = 0.6     # the post-gen check's CONTRA_FLAG (L-46)
_NEG_CLAUSE = re.compile(r"^(?:No|There is no|There are no|Without)\s+", re.I)


def _clause_span(report: str, clause: str) -> Optional[Tuple[int, int]]:
    c = clause.strip().rstrip(".")
    i = report.find(c) if c else -1
    return (i, i + len(c)) if i >= 0 else None


def brief_rules(report: str, anchors: List[Anchor], contra: Dict[str, float], flagged: List[str],
                review_contra: List[str]) -> dict:
    """Spec §3.2 → {"protect": clauses never removed, "remove": OMIT clauses to remove, "conflicts": cards}.
    `contra`: Jev's contradiction score per checked clause; `flagged`: negative clauses the check would remove;
    `review_contra`: positive / normal clauses it flagged for review."""
    live = [a for a in anchors if a.how in ("term", "jev") and a.span]

    def holders(clause: str) -> List[Anchor]:
        cs = _clause_span(report, clause)
        return [a for a in live if cs and a.span[0] < cs[1] and cs[0] < a.span[1]]

    protect: List[str] = []
    remove: List[str] = []
    conflicts: List[dict] = []
    for clause in list(dict.fromkeys(flagged + review_contra)):
        keep = [a for a in holders(clause) if a.action in KEEP and a.action != "dictated"]
        if keep or any(a.action == "dictated" for a in holders(clause)):
            protect.append(clause)
        if keep:      # Q2: a brief-kept clause Jev doubts is a card, never a removal
            conflicts.append({"clause": clause, "refs": [a.ref for a in keep], "reason": "brief_kept",
                              "score": round(contra.get(clause, 0.0), 3), "source": keep[0].source,
                              "pointer": next((a.pointer for a in keep if a.pointer), "")})
    for clause, score in contra.items():
        hs = holders(clause)
        omit = [a for a in hs if a.action in OMIT]
        if clause in protect or not omit or any(a.action == "dictated" for a in hs):
            continue  # dictated beats OMIT: no removal, no card (logged by anchor_log via shadowing)
        if score >= CONTRA_MIN and not any(a.action in KEEP for a in hs) and _NEG_CLAUSE.match(clause.strip()):
            remove.append(clause)                                     # Q3: two signals
        else:
            conflicts.append({"clause": clause, "refs": [a.ref for a in omit], "reason": "brief_omitted",
                              "score": round(score, 3), "source": omit[0].source, "action": omit[0].action,
                              "pointer": omit[0].pointer})
    return {"protect": protect, "remove": remove, "conflicts": conflicts}


def anchor_log(anchors: List[Anchor], rules: dict) -> dict:
    """quality_check.anchor_log: what anchored how, what did not (spec Q4: logged, never surfaced), brief errors
    (an OMIT label whose words a dictated label holds, e.g. a dictated "No ascites" the brief called contradicted)."""
    dictated = {a.ref for a in anchors if a.action == "dictated"}
    return {"labels": len(anchors),
            "by_term": sum(a.how == "term" for a in anchors),
            "by_jev": sum(a.how == "jev" for a in anchors),
            "removed": sum(a.how == "removed" for a in anchors),
            "unanchored": [{"ref": a.ref, "source": a.source, "action": a.action}
                           for a in anchors if a.how == "none" and not a.shadowed_by],
            "shadowed": [{"ref": a.ref, "shadowed_by": a.shadowed_by} for a in anchors if a.shadowed_by],
            "brief_errors": [{"ref": a.ref, "shadowed_by": a.shadowed_by} for a in anchors
                             if a.shadowed_by in dictated and a.action in OMIT],
            "protected": len(rules.get("protect") or []), "removed_by_brief": len(rules.get("remove") or []),
            "conflicts": len(rules.get("conflicts") or [])}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_brief_anchor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/brief_anchor.py backend/tests/test_brief_anchor.py
git commit -m "feat(brief-anchor): Q2/Q3 rules (kept → card, OMIT → two signals, dictated beats OMIT) and anchor log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The post-gen check uses the anchors

**Files:**
- Modify: `backend/src/rapid_reports_ai/report_review.py` (`CheckResult`, `check()`, `run_quality_check()`)
- Modify: `backend/src/rapid_reports_ai/quick_report_generator.py:154`
- Test: `backend/tests/test_report_review.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_report_review.py`)

```python
from rapid_reports_ai import brief_anchor as ba

QR = ("FINDINGS:\nA small right pleural effusion. No contralateral pleural effusion. No pleural effusion.\n\n"
      "IMPRESSION:\nSmall right effusion.\n")
QDEC = {"negatives": [
    {"text": "No pleural effusion identified", "action": "contradicted", "source": "sheet",
     "dictated_finding": "Small right pleural effusion"},
    {"text": "No contralateral pleural effusion identified", "action": "keep", "source": "finding:Pleural effusion"}]}


def _contra_jev(scores):
    """Fake rc._jev: contradiction question c<i> scores by clause text; restated r<i> high; dictated d<i> low."""
    async def fake(state, qs):
        out = {}
        for k, q in qs.items():
            text = q.get("instructions", "")
            if k.startswith("c"):
                out[k] = {"noul": next((v for t, v in scores.items() if t in text), 0.05)}
            elif k.startswith("r"):
                out[k] = {"noul": 0.9}
            elif k.startswith("i"):
                out[k] = {"choice": "stated", "probabilities": {"stated": 0.9}}
            else:
                out[k] = {"noul": 0.05}
        return out
    return fake


async def test_a_kept_negative_is_never_removed_and_becomes_a_conflict(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No contralateral pleural effusion": 0.8}))
    report, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [],
                                                brief_decisions=QDEC)
    assert "No contralateral pleural effusion." in report
    assert [c["reason"] for c in tel["brief_conflicts"]] == ["brief_kept"]


async def test_an_omit_negative_with_jev_agreeing_is_removed_before_render(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({"No pleural effusion": 0.9}))
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    report, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [],
                                                brief_decisions=QDEC)
    assert "No pleural effusion." not in report and "No contralateral pleural effusion." in report
    assert {"type": "removal", "clause": "No pleural effusion."} in tel["applied_edits"]
    anchors = {a["ref"]: a for a in tel["anchors"]}
    assert report[anchors["neg:1"]["span"][0]:anchors["neg:1"]["span"][1]] == "contralateral pleural effusion"
    assert tel["anchor_log"]["labels"] == 2


async def test_without_brief_decisions_or_with_the_kill_switch_nothing_changes(monkeypatch):
    monkeypatch.setattr(rr.rc, "_jev", _contra_jev({}))
    _, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [])
    assert "anchors" not in tel
    monkeypatch.setenv("RR_BRIEF_ANCHOR", "0")
    _, _, tel = await rr.run_quality_check(QR, "Small right pleural effusion", "CT chest", [], brief_decisions=QDEC)
    assert "anchors" not in tel
```

In `QR`, "No pleural effusion." is the only hit for the OMIT label's term outside the longer "contralateral pleural effusion". So pass 1 anchors both labels, and the OMIT clause is removed with two signals.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_report_review.py -q -k "kept_negative or omit_negative or kill_switch"`
Expected: FAIL with `TypeError: run_quality_check() got an unexpected keyword argument 'brief_decisions'`

- [ ] **Step 3: Add contradiction scores to `CheckResult` and `check()`**

In `class CheckResult`, after `extra_answers`, add:

```python
    # Jev's contradiction score per checked clause (brief_anchor's OMIT rule needs it for clauses that raised no flag).
    # Excluded from dumps.
    contra: dict = Field(default_factory=dict, exclude=True)
```

In `check()`, replace the final `return CheckResult(...)` with:

```python
    contra_scores = {} if isinstance(contra, BaseException) else {
        t: s for i, t in enumerate(cls) if (s := maybe(contra, f"c{i}")) is not None}
    return CheckResult(flags=flags, kept_dictated=kept, bad_option_ids=bad, n_clauses=len(cls), n_items=len(items),
                       n_selected=sum(chosen), selector=selector, error=error,
                       extra_answers={k: score(omit, k) for k in (extra_report_qs or {})}, contra=contra_scores)
```

- [ ] **Step 4: Wire the anchors into `run_quality_check()`**

1. Add `brief_decisions: Optional[dict] = None` as the last parameter. Add this docstring line: "`brief_decisions` (quick): the brief's labels are anchored on the report (`brief_anchor`); a brief-kept clause is never removed (a conflict card instead) and an OMIT clause is removed on two signals."

2. Replace the `res = await check(...)` statement with:

```python
        check_call = check(report, findings, scan_type, options,
                           **_given(sections=sections, protected=protected, extra_report_qs=extra_report_qs,
                                    history=history))
        anchors = []
        if brief_decisions is not None and sections is None:
            from . import brief_anchor
            if brief_anchor.enabled():
                res, anchors = await asyncio.gather(check_call, brief_anchor.anchor(report, brief_decisions))
            else:
                res = await check_call
        else:
            res = await check_call
```

3. Directly after `tel["review"] += [...]` (the contradiction review entries), add:

```python
        rules = None
        if anchors:
            rules = brief_anchor.brief_rules(
                report, anchors, res.contra,
                flagged=[f.text for f in res.flags if f.kind == "contradiction" and is_negative(f.text)],
                review_contra=[r["text"] for r in tel["review"] if r["kind"] == "contradiction"])
```

4. In the removal loop, change the condition `if f.kind == "contradiction" and is_negative(f.text):` to:

```python
            if f.kind == "contradiction" and is_negative(f.text) and not (rules and f.text in rules["protect"]):
```

5. After the loop and before `tel["clauses_removed"] = removed`, add:

```python
        if rules:
            for clause in rules["remove"]:
                if any(r["clause"] == clause for r in removals):
                    continue
                new = remove_negative_clause(report, clause)
                if new != report:
                    removed += 1
                    removals.append({"type": "removal", "clause": clause})
                    report = new
                else:      # code cannot remove it cleanly: a card instead
                    rules["conflicts"].append({"clause": clause, "refs": [], "reason": "brief_omitted",
                                               "score": round(res.contra.get(clause, 0.0), 3), "source": "",
                                               "pointer": ""})
```

6. Before the `# Gate D shadow log` comment (after the protected-text guard), add:

```python
    if anchors:
        from . import brief_anchor
        from dataclasses import asdict
        moved = brief_anchor.relocate(anchors, report)
        tel["anchors"] = [asdict(a) for a in moved]
        tel["brief_conflicts"] = (rules or {}).get("conflicts") or []
        tel["anchor_log"] = brief_anchor.anchor_log(moved, rules or {})
```

Declare `anchors: list = []` and `rules = None` at the top of the function, before `try:`, so they exist when `check()` raises. Change the first `anchors = []` inside the `try` to a plain reassignment.

- [ ] **Step 5: Pass the brief from the quick generator**

In `quick_report_generator.py`, replace:

```python
    report, options, quality = await run_quality_check(report, findings, scan_type, options)
```

with:

```python
    report, options, quality = await run_quality_check(report, findings, scan_type, options,
                                                       brief_decisions=brief.decisions if brief else None)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest tests/test_report_review.py tests/test_brief_anchor.py -q`
Expected: PASS (all existing `test_report_review.py` tests still pass: no brief → unchanged path)

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/report_review.py backend/src/rapid_reports_ai/quick_report_generator.py \
        backend/tests/test_report_review.py
git commit -m "feat(post-check): anchor brief labels; kept clauses never removed, OMIT removed on two signals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: One mapping from label to AI-layer item (implicated → amber)

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/negatives.py` (new `ai_layer`, `route()` branches, module docstring table)
- Test: `backend/tests/test_review_engine_negatives.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from rapid_reports_ai.review_engine import negatives as ng


def test_ai_layer_maps_labels_to_one_amber_category():
    assert ng.ai_layer("implicated", pointer="CBD 12 mm")[2] == "negative"
    assert ng.ai_layer("default", finding="Lung mass")[2] == "negative"      # chosen for a dictated finding
    assert ng.ai_layer("default", clause="No hepatic lesion.")[2] == "normal"
    assert ng.ai_layer(None, clause="No hepatic lesion.")[2] == "negative"   # no label: the wording decides
    assert ng.ai_layer("implicated", pointer="CBD 12 mm")[0] == "Bears on your finding"


def test_an_implicated_statement_is_an_amber_assumed_normal_not_a_check_card():
    report = "FINDINGS:\nPancreatic head mass. No pancreatic duct dilatation.\n\nIMPRESSION:\nMass.\n"
    i = inp(report, "- Pancreatic head mass")
    cands = [{"clause": "No pancreatic duct dilatation.", "before": "Pancreatic head mass.", "number": False}]
    items, _, _ = ng.route(i, "r1", cands, {1: {"cls": "implicated", "pointer": "Pancreatic head mass",
                                               "number": False}})
    (it,) = items
    assert it.kind == "assumed_normal" and it.evidence["form"] == "negative"
    assert it.evidence["pointer"] == "Pancreatic head mass" and it.label == "Bears on your finding"
```

(`inp` is already imported in this test module from `tests.review_engine_fakes`. If it is not, add `from tests.review_engine_fakes import inp`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_review_engine_negatives.py -q -k "ai_layer or amber"`
Expected: FAIL with `AttributeError: ... has no attribute 'ai_layer'`

- [ ] **Step 3: Implement**

Add after `check_text` in `negatives.py`:

```python
AMBER = "Bears on your finding"


def ai_layer(cls: Optional[str], pointer: str = "", finding: str = "", clause: str = "") -> Tuple[str, str, str]:
    """(label, reason, evidence.form) for a generated statement that stays in the report (spec 2026-10-09 §3.3).
    Implicated, and a negative the brief chose for a dictated finding, are amber ("negative"): in the report, worth a
    glance, no rail card. Default is green ("normal"). No label (the classifier failed) falls back to the wording."""
    if cls == "implicated":
        return AMBER, check_text("uncertain", pointer)[1], "negative"
    if finding:
        return AMBER, f"A pertinent negative for {finding}, added by the AI. Keep it or remove it.", "negative"
    if cls in ("default", "keep"):
        return "Assumed normal", "", "normal"
    return "Assumed normal", "", statement_form(clause)
```

In `route()`, replace the two final branches:

```python
        elif cls == "implicated":
            label, why = check_text("uncertain", given)
            items[i] = item(c, "check", "open", "uncertain", anchor,
                            {**base, "check_reason": "uncertain", "pointer": given}, label, reason=why)
        else:
            items[i] = item(c, "assumed_normal", "open", "assumed_normal", anchor, base, "Assumed normal")
```

with:

```python
        else:                                         # default / implicated: the AI layer, never a rail card
            label, why, form = ai_layer(lab.get("cls"), given, clause=c["clause"])
            items[i] = item(c, "assumed_normal", "open", "assumed_normal", anchor,
                            {**base, "form": form, **({"pointer": given} if cls == "implicated" else {})},
                            label, reason=why)
```

In the module docstring's routing table, replace the `implicated` row with:
`implicated                              assumed_normal  open          info    evidence.form "negative" (amber), pointer`
Add the line: `default → evidence.form "normal" (green); unlabelled (model failure) → statement wording (spec 2026-10-09 §3.3)`.

- [ ] **Step 4: Update the existing tests that expect implicated → check/uncertain**

Run: `grep -n "uncertain" tests/test_review_engine_negatives.py tests/test_review_engine_*.py`

Every assertion that a classifier-`implicated` statement becomes `kind == "check"` with `check_reason == "uncertain"` now expects `kind == "assumed_normal"`, `evidence["form"] == "negative"` and the pointer. Leave conflict and number assertions untouched.

- [ ] **Step 5: Run the review-engine tests**

Run: `.venv/bin/pytest tests/ -q -k "review_engine"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/negatives.py backend/tests/
git commit -m "feat(review-engine): implicated is an amber AI-layer statement, not a check card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Brief items, conflict cards and owned spans from the anchors

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/brief_normals.py`
- Modify: `backend/src/rapid_reports_ai/review_engine/engine.py` (the `owned` computation in `run_review`)
- Test: `backend/tests/test_review_engine_brief_normals.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
AREPORT = ("FINDINGS:\nA small right pleural effusion. No contralateral pleural effusion. "
           "The liver is unremarkable. No paratracheal or subcarinal lymphadenopathy. No pulmonary emboli.\n\n"
           "IMPRESSION:\nSmall right effusion.\n")


def _anc(ref, action, source, text, how="term", pointer="", unit=None):
    i = AREPORT.index(text)
    return {"ref": ref, "action": action, "source": source, "pointer": pointer, "how": how,
            "span": [i, i + len(text)], "span_text": text, "unit": unit or text, "offset": 0}


ANCHORS = [
    _anc("neg:1", "keep", "finding:Pleural effusion", "contralateral pleural effusion", pointer="Pleural effusion"),
    _anc("atom:P2:N3", "keep", "atom", "liver"),
    _anc("atom:P1:N2", "implicated", "atom", "No paratracheal or subcarinal lymphadenopathy.", how="jev",
         pointer="right hilar nodes"),
    _anc("dict:0", "dictated", "dictated", "pulmonary emboli"),
    {"ref": "neg:6", "action": "keep", "source": "sheet", "pointer": "", "how": "none", "span": None,
     "span_text": "", "unit": "", "offset": 0},
]


def _ainp(qc):
    i = inp(AREPORT, "- Small right pleural effusion\n- No pulmonary emboli", quality_check=qc)
    return i.model_copy(update={"artifacts": i.artifacts.model_copy(update={"brief": {"decisions": {}}})})


def test_items_come_from_anchors_with_tint_by_origin():
    items = {i.evidence["ref"]: i for i in bn.build_items(_ainp({"anchors": ANCHORS}), RUN)}
    assert set(items) == {"neg:1", "atom:P2:N3", "atom:P1:N2"}         # dictated: no item; unanchored: none
    assert items["neg:1"].evidence["form"] == "negative" and items["neg:1"].evidence["pointer"] == "Pleural effusion"
    assert items["atom:P2:N3"].evidence["form"] == "normal" and items["atom:P2:N3"].kind == "assumed_normal"
    assert items["atom:P1:N2"].evidence["form"] == "negative" and items["atom:P1:N2"].kind == "assumed_normal"
    for it in items.values():
        assert AREPORT[it.anchor.start:it.anchor.end] == it.anchor.text


def test_a_brief_conflict_is_a_check_card_and_replaces_the_tint_on_its_clause():
    qc = {"anchors": ANCHORS, "brief_conflicts": [
        {"clause": "No contralateral pleural effusion.", "refs": ["neg:1"], "reason": "brief_kept", "score": 0.8,
         "source": "finding:Pleural effusion", "pointer": "Pleural effusion"}]}
    items = bn.build_items(_ainp(qc), RUN)
    cards = [i for i in items if i.kind == "check"]
    assert len(cards) == 1 and cards[0].evidence["check_reason"] == "conflict"
    assert cards[0].evidence["brief_reason"] == "brief_kept"
    assert not any(i.kind == "assumed_normal" and i.evidence.get("ref") == "neg:1" for i in items)


def test_owned_spans_cover_every_anchor_including_dictated():
    spans = bn.owned_spans(_ainp({"anchors": ANCHORS}))
    texts = {AREPORT[a:b] for a, b in spans}
    assert "pulmonary emboli" in texts and "liver" in texts and len(spans) == 4


def test_old_reports_without_anchors_use_the_legacy_path():
    assert bn.owned_spans(_inp()) is None
    assert {i.evidence["term"] for i in bn.build_items(_inp(), RUN)}     # legacy items still built
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_review_engine_brief_normals.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'owned_spans'`

- [ ] **Step 3: Implement in `brief_normals.py`**

Add these imports:

```python
from .items import ReviewInput, ReviewItem, Span, item_key, text_hash   # (already imported)
```

Add the new functions above `build_items`:

```python
NEG_KIND = "brief_negative"
CONFLICT_KIND = "brief_conflict"


def anchors_of(inp: ReviewInput) -> Optional[List[dict]]:
    """quality_check.anchors (brief_anchor), or None for a report generated before anchoring shipped."""
    a = (inp.artifacts.quality_check or {}).get("anchors")
    return a if isinstance(a, list) else None


def _span_on(report: str, a: dict) -> Optional[Tuple[int, int]]:
    sp, t = a.get("span"), a.get("span_text") or ""
    if sp and t and report[sp[0]:sp[1]] == t:
        return sp[0], sp[1]
    i = report.find(a.get("unit") or "\0")
    k = i + int(a.get("offset") or 0)
    if i >= 0 and t and report[k:k + len(t)] == t:
        return k, k + len(t)
    return None


def owned_spans(inp: ReviewInput) -> Optional[List[Tuple[int, int]]]:
    """Every anchored brief label's span on the final report: the classifier never re-reads these (spec §3.3).
    None without anchors (the engine then uses the legacy brief items' anchors)."""
    anchors = anchors_of(inp)
    if anchors is None:
        return None
    report = inp.artifacts.report or ""
    return [sp for a in anchors if a.get("how") in ("term", "jev") and (sp := _span_on(report, a))]


def _conflict_text(c: dict) -> Tuple[str, str]:
    finding = str(c.get("source") or "").split(":", 1)[1] if str(c.get("source") or "").startswith("finding:") else ""
    if c.get("reason") == "brief_kept":
        what = f"Kept as a pertinent negative for {finding}" if finding else "Stated by the AI as normal"
        return ("Check: may conflict with your dictation",
                f"{what}, but a check found it may contradict your dictation. Remove it, or dismiss to keep it.")
    p = negatives.pointer_text(c.get("pointer"))
    return ("Check: advised against stating this",
            (f"Your dictation reports “{p}”, so this was not meant to be stated. Remove it, or dismiss to keep it."
             if p else "The brief advised against stating this. Remove it, or dismiss to keep it."))


def _from_anchors(inp: ReviewInput, run_id: str, anchors: List[dict]) -> List[ReviewItem]:
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    out: List[ReviewItem] = []

    def make(key_text, kind, cls, span, label, reason, evidence, edit=None, verified=None, original=NEG_KIND):
        anchor = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h) if span else None
        sec = verifier._section_of(report, span[0], names) if span else None
        return ReviewItem(key=item_key(LANE, original, key_text), report_id=inp.report_id, run_id=run_id, lane=LANE,
                          detectors=[DETECTOR], kind=kind, cls=cls, section=sec.upper() if sec else None,
                          anchor=anchor, label=label, reason=reason, evidence=evidence, edit=edit, verified=verified,
                          status="open", history=[{"at": _now(), "event": "created", "actor": "engine",
                                                   "text_hash": h, "detail": {"detectors": [DETECTOR]}}])

    taken: List[Tuple[int, int]] = []
    for c in (inp.artifacts.quality_check or {}).get("brief_conflicts") or []:
        clause = (c.get("clause") or "").strip().rstrip(".")
        i = report.find(clause) if clause else -1
        span = (i, i + len(clause)) if i >= 0 else None
        anchor = Span(start=span[0], end=span[1], text=clause, text_hash=h) if span else None
        fix, verified = negatives._conflict_fix(inp, report, anchor, c.get("clause") or "", names)
        label, reason = _conflict_text(c)
        out.append(make(clause, "check", negatives.CLS["conflict"], span, label, reason,
                        {"source": "brief", "check_reason": "conflict", "brief_reason": c.get("reason"),
                         "refs": c.get("refs") or [], "score": c.get("score"),
                         "pointer": negatives.pointer_text(c.get("pointer"))},
                        edit=fix, verified=verified, original=CONFLICT_KIND))
        if span:
            taken.append(span)
    for a in anchors:
        if a.get("how") not in ("term", "jev") or a.get("action") not in ("keep", "default", "implicated"):
            continue      # dictated: your own words; OMIT: removed, or a conflict card above
        span = _span_on(report, a)
        if span and any(x < span[1] and span[0] < y for x, y in taken):
            continue      # one card per clause: the conflict card stands
        src = str(a.get("source") or "")
        finding = src.split(":", 1)[1] if src.startswith("finding:") else ""
        cls = "implicated" if a.get("action") == "implicated" else "default"
        label, reason, form = negatives.ai_layer(cls, a.get("pointer") or "", finding,
                                                 report[span[0]:span[1]] if span else "")
        ev = {"source": "brief", "ref": a.get("ref"), "label": cls, "how": a.get("how"), "form": form,
              **({"pointer": a.get("pointer") or finding} if (cls == "implicated" or finding) else {})}
        out.append(make(a.get("ref") or a.get("span_text") or "", "assumed_normal", negatives.CLS["assumed_normal"],
                        span, label, reason, ev))
    return out
```

At the top of `build_items`, add:

```python
    anchors = anchors_of(inp)
    if anchors is not None:
        return _from_anchors(inp, run_id, anchors)
```

In the legacy path inside `build_items`, replace the `if atom["action"] == "implicated":` block's item fields with the AI-layer mapping, so old reports render the same way:

```python
        if atom["action"] == "implicated":
            pointer = negatives.pointer_text(atom.get("pointer"))   # a stored "->" is the labeller's "none"
            label, reason, form = negatives.ai_layer("implicated", pointer)
            kind, cls = "assumed_normal", negatives.CLS["assumed_normal"]
            evidence = {**base, "form": form, "pointer": pointer, "included": True,
                        **({"jev_affected": atom["jev_affected"]} if atom.get("jev_affected") is not None else {})}
```

Update the module docstring's table: implicated → `assumed_normal`, `info`, `evidence.form "negative"` (amber). Add a paragraph: "With `quality_check.anchors` (brief_anchor, spec 2026-10-09) items come from the anchors instead: every anchored kept / implicated label (atoms AND brief negatives), conflict cards from `quality_check.brief_conflicts`, and `owned_spans` for the classifier. Reports without anchors use the legacy atom anchoring below." Add `"owned_spans", "anchors_of"` to `__all__`.

- [ ] **Step 4: Use `owned_spans` in the engine**

In `engine.py` `run_review`, replace:

```python
            owned = [(b.anchor.start, b.anchor.end) for b in brief_items
                     if b.anchor is not None and b.anchor.end > b.anchor.start]
```

with:

```python
            owned = brief_normals.owned_spans(inp)           # every anchored brief label (spec 2026-10-09 §3.3)
            if owned is None:                                # a report from before anchoring: the legacy atom items
                owned = [(b.anchor.start, b.anchor.end) for b in brief_items
                         if b.anchor is not None and b.anchor.end > b.anchor.start]
```

- [ ] **Step 5: Update the legacy tests that expect implicated → check**

Run: `grep -n "check\b\|uncertain" tests/test_review_engine_brief_normals.py`

The implicated atom ("intrahepatic biliary tree") now yields `kind == "assumed_normal"`, `evidence["form"] == "negative"` and `evidence["pointer"] == "CBD 12 mm"`. Update those assertions only.

- [ ] **Step 6: Run the review-engine tests**

Run: `.venv/bin/pytest tests/ -q -k "review_engine or brief_anchor or report_review"`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/brief_normals.py backend/src/rapid_reports_ai/review_engine/engine.py \
        backend/tests/test_review_engine_brief_normals.py
git commit -m "feat(review-engine): brief items, conflict cards and owned spans from quality_check.anchors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Brief labeller full scheme (behind `RR_BRIEF_FULL_LABELS`, default off)

**Files:**
- Modify: `backend/src/rapid_reports_ai/report_reconcile.py` (`QWEN_SYS` parts, `QWEN_SYS_FULL`, `NegativeDecision`, `_qwen`)
- Modify: `backend/src/rapid_reports_ai/quick_report_brief.py` (`_qwen_complete` wrapper, negatives compile, finding-linked record, `said`)
- Test: `backend/tests/test_quick_report_brief.py`

- [ ] **Step 1: Write the failing tests** (append; reuse the module's existing fakes for `_qwen` / `_jev`. Read the top of `tests/test_quick_report_brief.py` and follow its pattern for building a brief with patched `_qwen`)

```python
from rapid_reports_ai import report_reconcile as rc


def test_quick_sys_is_unchanged_and_full_sys_carries_the_four_labels():
    assert "'contradicted' if the dictation reports it as present" in rc.QWEN_SYS
    for word in ("dictated:", "default:", "implicated:", "contradicted:", "expected:"):
        assert word in rc.QWEN_SYS_FULL
    assert "Process of exclusion" in rc.QWEN_SYS_FULL and "NORMAL LINES" in rc.QWEN_SYS_FULL


def test_negative_decision_accepts_the_full_labels():
    for a in ("keep", "default", "implicated", "dictated", "contradicted", "expected"):
        assert rc.NegativeDecision(index=0, action=a).action == a


async def test_full_labels_compile_dictated_and_implicated_lines(monkeypatch):
    monkeypatch.setenv("RR_BRIEF_FULL_LABELS", "1")
    seen = {}

    async def fake_qwen(state, negs, normals, measurements, linked=None, full=False):
        seen["full"] = full
        acts = ["dictated", "implicated", "default"]
        return rc.QwenDecisions(negatives=[rc.NegativeDecision(index=i, action=acts[i % 3],
                                                               dictated_finding="head mass" if i % 3 == 1 else "")
                                           for i in range(len(negs))],
                                affected_normals=[], applicable_measurements=[])
    monkeypatch.setattr(qrb, "_qwen", fake_qwen)
    brief = await build_brief_for_test(monkeypatch, negatives=["No ascites", "No pancreatic duct dilatation",
                                                               "No hepatic mass"])
    assert seen["full"] is True
    assert '  - DICTATED: "No ascites"' in brief.text
    assert '"No pancreatic duct dilatation" (implicated by: head mass)' in brief.text
    acts = [n["action"] for n in brief.decisions["negatives"] if n["source"] == "sheet"]
    assert acts == ["dictated", "implicated", "default"]
```

`build_brief_for_test` stands for the test module's existing helper that builds a quick brief from a sheet with mandatory negatives. Use that helper under its real name; read the file's fixtures first. If there is none, copy the setup of the nearest existing test that asserts `OMIT:` lines and pass the three negatives through it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_quick_report_brief.py -q -k "full"`
Expected: FAIL with `AttributeError: module ... has no attribute 'QWEN_SYS_FULL'`

- [ ] **Step 3: Implement in `report_reconcile.py`**

Replace the `QWEN_SYS = (...)` literal with parts. The new `QWEN_SYS` is byte-identical to the old one:

```python
_SYS_HEAD = ("You check a radiology skill sheet against the radiologist's dictated findings for one case. Silence in "
             "the dictation never makes a finding present.\n")
_SYS_NEG = ("NEGATIVES: for each numbered negative return 'contradicted' if the dictation reports it as present or "
            "reports a finding of the same kind in the same place; 'expected' if a dictated finding would normally and "
            "predictably cause what it denies (not merely make it possible); otherwise 'keep'. For contradicted and "
            "expected, quote the dictated finding responsible.\n")
_SYS_REST = ("NORMAL LINES: list the numbers of normal-study statements that a dictated finding contradicts or acts on.\n"
             "MEASUREMENTS: list the numbers of measurement conventions whose finding is present in the dictation.")
QWEN_SYS = _SYS_HEAD + _SYS_NEG + _SYS_REST

# The negatives classifier's four labels (review_engine/prompts/negatives.txt, "your Step 1 notes" read as "the dictated
# findings"), plus expected (spec 2026-10-09 §3.0). Quick only, behind RR_BRIEF_FULL_LABELS.
_SYS_NEG_FULL = (
    "NEGATIVES: classify each numbered negative against the dictation. Process of exclusion: the radiologist dictates "
    "which structures are abnormal, and every structure, organ or site not named as abnormal is normal by default. This "
    "holds for distant sites even in metastatic or spreading disease, and for the rest of an organ when only part of it "
    "is diseased. Only local consequences of a dictated finding can make a negative implicated.\n"
    "- dictated: the dictation itself states this normal or negative, for the same structure, side and level, at the "
    "same certainty, in any wording. A dictated negative restated with a synonym or an equivalent term is still "
    "dictated. A negative that widens a dictated negative to more structures or levels, or states it more firmly than "
    "dictated, is NOT dictated.\n"
    "- default: not dictated, and nothing in the dictated findings points towards the abnormality it denies.\n"
    "- implicated: not dictated, and something in the dictated findings points towards what it denies: a local "
    "consequence, complication, extension, cause or associated finding of a dictated finding; the same structure, level "
    "or compartment as dictated disease; or a dictated limitation covering it. The clinical question on its own, or the "
    "possibility of distant spread, never makes a negative implicated.\n"
    "- contradicted: the dictation states the opposite, or reports disease in the very thing the negative denies.\n"
    "- expected: a dictated finding would normally and predictably cause what it denies (not merely make it possible).\n"
    "When in doubt between default and implicated, choose implicated. For implicated, contradicted and expected, quote "
    "the dictated finding responsible.\n")
QWEN_SYS_FULL = _SYS_HEAD + _SYS_NEG_FULL + _SYS_REST
```

Change `NegativeDecision.action` to:

```python
    action: Literal["keep", "default", "implicated", "dictated", "contradicted", "expected"]
```

Change `_qwen` to take `full: bool = False`, and pick the system prompt from it:

```python
async def _qwen(state: str, negs: List[str], normals: List[str], measurements: List[str],
                linked: Optional[tuple] = None, full: bool = False) -> QwenDecisions:
    """linked: (system addition, statements block), the linked-normal atoms folded into this call. None
    (always, unless RR_GROUPED_NORMALS is on) sends exactly the request it always has. full: the four-label
    negatives scheme (QWEN_SYS_FULL, quick behind RR_BRIEF_FULL_LABELS)."""
    def block(title, items):
        return f"{title}:\n" + ("\n".join(f"{k}. {t}" for k, t in enumerate(items)) or "(none)")
    user = f"{state}\n\n{block('NEGATIVES', negs)}\n\n{block('NORMAL LINES', normals)}\n\n{block('MEASUREMENTS', measurements)}"
    base = QWEN_SYS_FULL if full else QWEN_SYS
    out_type, sys_prompt, max_tokens = QwenDecisions, base, 4000
    if linked:
        out_type, sys_prompt, max_tokens = QwenDecisionsLinked, base + linked[0], 8000
        user += "\n\n" + linked[1]
```

(The rest of `_qwen` is unchanged.) The template path never passes `full`, so it sends exactly what it sends today. Its code reads only `contradicted` / `expected`; anything else is KEEP.

- [ ] **Step 4: Implement in `quick_report_brief.py`**

Add after `LABEL_TIMEOUT_S`:

```python
def full_labels() -> bool:
    """RR_BRIEF_FULL_LABELS=1: the brief's negatives use the four-label scheme (spec 2026-10-09 §3.0). Off until the
    brief labeller lab passes (plan Task 10)."""
    return os.environ.get("RR_BRIEF_FULL_LABELS", "0").strip().lower() in ("1", "true", "on")


SAID = ("keep", "default", "implicated", "dictated")
```

(Add `import os` at the top if it is not imported.)

Replace the `_qwen_complete` wrapper body:

```python
    kw = {**({"linked": linked} if linked is not None else {}), **({"full": True} if full_labels() else {})}
    ask = (lambda *a: _qwen(*a, **kw)) if kw else _qwen
    return await _rc._qwen_complete(state, negs, normals, measurements, ask=ask, log=logger)
```

In the mandatory-negatives loop, replace the `if/elif/else` that appends `neg_lines` with:

```python
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
```

In the finding-linked `if outcome == "stated":` branch, record the label:

```python
            decisions["negatives"].append({"text": c.text, "action": label if label in SAID else "keep",
                                           "dictated_finding": d.dictated_finding if d else "",
                                           "source": f"finding:{c.key}"})
```

Replace the `said = [...]` line with:

```python
    said = [n["text"] for n in decisions["negatives"] if n["action"] in SAID] + dictated_negatives(items)
```

- [ ] **Step 5: Run the brief and template tests**

Run: `.venv/bin/pytest tests/test_quick_report_brief.py tests/ -q -k "brief or template or reconcile"`
Expected: PASS (flag off by default, so existing expectations hold)

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/report_reconcile.py backend/src/rapid_reports_ai/quick_report_brief.py \
        backend/tests/test_quick_report_brief.py
git commit -m "feat(brief): four-label negatives scheme behind RR_BRIEF_FULL_LABELS (quick only, default off)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Brief labeller lab (GATE for turning `RR_BRIEF_FULL_LABELS` on)

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/fixtures/brief_labels_cases.json`
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/brief_labels_lab.py`

- [ ] **Step 1: Write the synthetic cases** (four domains plus the traps; `gold` per negative)

```json
[
 {"id": "s01", "scan": "CT abdomen and pelvis with contrast", "dictation": "3 cm pancreatic head mass. CBD 13 mm with intrahepatic duct dilatation. No ascites.",
  "negatives": [["No ascites", "dictated"], ["No pancreatic ductal dilatation", "implicated"], ["No calculus in the common bile duct", "implicated"], ["No hepatic mass", "default"], ["No extrahepatic biliary dilatation", "contradicted"], ["No splenomegaly", "default"]]},
 {"id": "s02", "scan": "CT abdomen and pelvis with contrast", "dictation": "Hypoenhancing pancreatic head mass abutting the SMV, no SMA involvement. Two small indeterminate liver lesions.",
  "negatives": [["No encasement of the superior mesenteric artery", "dictated"], ["No hepatic metastases", "contradicted"], ["No peritoneal deposits", "default"], ["No peripancreatic lymphadenopathy", "implicated"]]},
 {"id": "s03", "scan": "CT thorax with contrast", "dictation": "2.8 cm spiculated right upper lobe mass. Enlarged right hilar nodes 14 mm. Small right pleural effusion. No pulmonary emboli.",
  "negatives": [["No pleural effusion", "contradicted"], ["No pulmonary embolus", "dictated"], ["No mediastinal lymphadenopathy", "implicated"], ["No osseous lesion", "default"], ["No pericardial effusion", "default"]]},
 {"id": "s04", "scan": "CT thorax with contrast", "dictation": "Right lower lobe consolidation with air bronchograms.",
  "negatives": [["No parapneumonic effusion", "implicated"], ["No cavitation", "implicated"], ["No pneumothorax", "default"], ["No consolidation", "contradicted"]]},
 {"id": "s05", "scan": "CT head without contrast", "dictation": "Large right cerebellar haemorrhage with effacement of the fourth ventricle.",
  "negatives": [["No hydrocephalus", "implicated"], ["No tonsillar herniation", "implicated"], ["No supratentorial haemorrhage", "default"], ["No haemorrhage", "contradicted"], ["No skull fracture", "default"]]},
 {"id": "s06", "scan": "MRI brain with contrast", "dictation": "Ring-enhancing left frontal lesion with surrounding vasogenic oedema. No midline shift.",
  "negatives": [["No midline shift", "dictated"], ["No intraventricular extension", "implicated"], ["No hydrocephalus", "default"], ["No other enhancing lesion", "default"]]},
 {"id": "s07", "scan": "MRI thoracic spine", "dictation": "Pathological collapse of T7 with epidural tumour compressing the cord.",
  "negatives": [["No cord compression", "contradicted"], ["No retropulsion at T7", "implicated"], ["No other vertebral metastases", "default"], ["No cord signal change", "implicated"]]},
 {"id": "s08", "scan": "MRI right knee", "dictation": "Complete ACL tear. Moderate joint effusion. Medial meniscus intact.",
  "negatives": [["No medial meniscal tear", "dictated"], ["No joint effusion", "contradicted"], ["No bone bruise", "implicated"], ["No PCL tear", "default"]]},
 {"id": "s09", "scan": "X-ray left wrist", "dictation": "Minimally displaced fracture of the distal radius.",
  "negatives": [["No intra-articular extension", "implicated"], ["No scaphoid fracture", "default"], ["No fracture", "contradicted"], ["No dislocation", "default"]]},
 {"id": "s10", "scan": "CT abdomen and pelvis with contrast", "dictation": "Dilated appendix 11 mm with periappendiceal fat stranding. Probable appendicolith.",
  "negatives": [["No periappendiceal collection", "implicated"], ["No free air", "implicated"], ["No hydronephrosis", "default"], ["No appendicolith", "contradicted"]]},
 {"id": "s11", "scan": "Ultrasound abdomen", "dictation": "Gallstones with gallbladder wall thickening 5 mm. CBD 4 mm.",
  "negatives": [["No pericholecystic fluid", "implicated"], ["No biliary dilatation", "dictated"], ["No gallstones", "contradicted"], ["No liver lesion", "default"]]},
 {"id": "s12", "scan": "CT angiogram aorta", "dictation": "Infrarenal abdominal aortic aneurysm 6.2 cm. No retroperitoneal haematoma.",
  "negatives": [["No retroperitoneal haematoma", "dictated"], ["No iliac artery aneurysm", "implicated"], ["No aortic dissection", "default"], ["No renal infarct", "default"]]}
]
```

- [ ] **Step 2: Write the lab script**

```python
"""Brief labeller lab (spec 2026-10-09 §5.0): today's keep / contradicted / expected labeller vs the four-label scheme,
on stored cases (gold by peer read, in $RR_LAB_OUT/brief_labels/) and synthetic cases (fixtures/brief_labels_cases.json).

    python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab build    # stored cases → stored_cases.json (gold null)
    python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab run --runs 2
    python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab score --results <jsonl>

Gate: contradicted recall (full) >= contradicted recall (today); dictated recognised >= 95%; 0 dictated labelled
contradicted; implicated vs default reported for the peer read. Production text stays under $RR_LAB_OUT."""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from rapid_reports_ai import report_reconcile as rc

from . import common

FIXTURE = Path(__file__).parent / "fixtures" / "brief_labels_cases.json"
OLD_TO_FULL = {"keep": "default"}   # today's labeller has no dictated / implicated: keep counts as default


def cases() -> list:
    out = common.read_json(FIXTURE)
    extra = common.lab_out("brief_labels") / "stored_cases.json"
    return out + (common.read_json(extra) if extra.exists() else [])


def build() -> None:
    rows = common.metabase(
        "select id, input_data->'variables'->>'FINDINGS' as dictation, "
        "coalesce(input_data->'variables'->>'SCAN_TYPE', input_data->>'extracted_scan_type') as scan, "
        "candidate_reports->0->'brief'->'decisions'->'negatives' as negs from reports "
        "where candidate_reports->0->'brief'->'decisions'->'negatives' is not null "
        "and created_at > now() - interval '30 days'")
    out = []
    for r in rows:
        negs = r["negs"] if isinstance(r["negs"], list) else json.loads(r["negs"])
        out.append({"id": r["id"][:8], "scan": r["scan"], "dictation": r["dictation"],
                    "negatives": [[n["text"], None] for n in negs]})
    common.write_json(common.lab_out("brief_labels") / "stored_cases.json", out)
    print(f"{len(out)} stored cases; set gold per negative by peer read before `run`")


async def run(runs: int) -> Path:
    common.load_env()
    out = common.out_file("brief_labels", "results", "jsonl")
    with open(out, "w") as f:
        for k in range(runs):
            for c in cases():
                if any(g is None for _, g in c["negatives"]):
                    continue
                state = f"SCAN TYPE: {c['scan']}\nDICTATED FINDINGS:\n{c['dictation']}"
                negs = [t for t, _ in c["negatives"]]
                for arm, full in (("today", False), ("full", True)):
                    qw = await rc._qwen(state, negs, [], [], full=full)
                    got = {d.index: d.action for d in qw.negatives}
                    for i, (t, g) in enumerate(c["negatives"]):
                        f.write(json.dumps({"case": c["id"], "arm": arm, "run": k, "i": i, "gold": g,
                                            "got": got.get(i)}) + "\n")
    print(out)
    return out


def score(results: str) -> None:
    rows = common.read_jsonl(results)
    for arm in ("today", "full"):
        rs = [r for r in rows if r["arm"] == arm]
        got = lambda r: OLD_TO_FULL.get(r["got"], r["got"]) if arm == "today" else r["got"]
        contra = [r for r in rs if r["gold"] == "contradicted"]
        dic = [r for r in rs if r["gold"] == "dictated"]
        imp = [r for r in rs if r["gold"] in ("implicated", "default")]
        print(f"{arm}: contradicted recall {sum(got(r) == 'contradicted' for r in contra)}/{len(contra)}; "
              f"dictated recognised {sum(got(r) == 'dictated' for r in dic)}/{len(dic)}; "
              f"dictated→contradicted {sum(got(r) == 'contradicted' for r in dic)}; "
              f"implicated/default agreement {sum(got(r) == r['gold'] for r in imp)}/{len(imp)}; "
              f"confusion {Counter((r['gold'], got(r)) for r in rs if got(r) != r['gold']).most_common(6)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "score"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--results")
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "run":
        asyncio.run(run(a.runs))
    else:
        score(a.results)
```

- [ ] **Step 3: Build stored cases, peer-read gold, run, score**

```bash
.venv/bin/python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab build
# set gold for every stored negative in $RR_LAB_OUT/brief_labels/stored_cases.json (Claude peer read; Hassan spot-checks boundary items only)
.venv/bin/python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab run --runs 2
.venv/bin/python -m rapid_reports_ai.scripts.review_labs.brief_labels_lab score --results <printed path>
```

**Gate (all four must hold):**
- full contradicted recall ≥ today's;
- dictated recognised ≥95%;
- dictated→contradicted = 0;
- implicated/default agreement acceptable on the peer read (spot-check the disagreements).

- **If the gate passes:** change the `full_labels()` default to `"1"`. Do not set the Railway flag: Hassan approves flags.
- **If it fails:** leave the default at `"0"` and record why.

- [ ] **Step 4: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/review_labs/brief_labels_lab.py \
        backend/src/rapid_reports_ai/scripts/review_labs/fixtures/brief_labels_cases.json \
        backend/src/rapid_reports_ai/quick_report_brief.py
git commit -m "lab(brief): four-label negatives lab — <today vs full numbers>; RR_BRIEF_FULL_LABELS default <0|1>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Frontend amber label

**Files:**
- Modify: `frontend/src/lib/review/editor/decorations.ts` (`markLabel`, exported)
- Modify: `frontend/src/lib/review/editor/field.ts` (`AI_BREAKDOWN`)
- Test: `frontend/src/lib/review/editor/decorations.svelte.test.ts`

- [ ] **Step 1: Write the failing test** (append)

```ts
import { markLabel } from './decorations';

describe('amber AI-layer label', () => {
	it('names the dictated finding an amber statement bears on', () => {
		const m = {
			id: 'x', kind: 'assumed_normal', cls: 'info', lane: 'accuracy', mark: 'rv-normal',
			form: 'negative', pointer: 'right hilar nodes 14 mm', from: 0, to: 5, text: 'No X.'
		} as const;
		expect(markLabel(m as never)).toBe('Bears on your finding · “right hilar nodes 14 mm” (AI-generated)');
	});
	it('leaves a green normal unchanged', () => {
		const m = { id: 'y', kind: 'assumed_normal', cls: 'info', lane: 'accuracy', mark: 'rv-normal',
			form: 'normal', from: 0, to: 5, text: 'Liver.' } as const;
		expect(markLabel(m as never)).toBe('Normals (AI-generated)');
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/lib/review/editor/decorations.svelte.test.ts`
Expected: FAIL (`markLabel` is not exported)

- [ ] **Step 3: Implement**

In `field.ts` `AI_BREAKDOWN`, replace the negative entry with:

```ts
	{ form: 'negative', label: 'Bears on your finding', title: 'Negatives the AI added that bear on a dictated finding: in the report, worth a glance' },
```

In `decorations.ts`, export `markLabel` and append the pointer for amber marks:

```ts
export function markLabel(m: LiveMark): string {
	const meaning = MARK_MEANING[m.mark];
	let t: string = m.form ? AI_BREAKDOWN.find((b) => b.form === m.form)!.label : LABELS[meaning];
	if (m.mark === 'rv-check') t += ` · ${checkReason({ check_reason: m.reason }).line}`;
	if (m.form === 'negative' && m.pointer) t += ` · “${m.pointer}”`;
	return AI_LAYER_MARKS.has(m.mark) ? `${t} (AI-generated)` : `${t} · hover for actions`;
}
```

- [ ] **Step 4: Update text assertions on the old label**

Run: `grep -rn "Pertinent negatives" frontend/src`. Update each test expectation to "Bears on your finding".

- [ ] **Step 5: Run the review frontend tests**

Run: `npx vitest run src/lib/review`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/review/editor/decorations.ts frontend/src/lib/review/editor/field.ts frontend/src/lib/review
git commit -m "feat(review-ui): amber AI-layer marks name the finding they bear on

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Cross-domain pass 1 tests and code-only stage on the stored cases

7 of the 8 stored cases are the same pancreatic head mass. So the replay alone tests one disease's vocabulary. Step 0 adds synthetic cases from other domains for the traps the spec names: sides, levels, "additional", narrower and broader names. They are deterministic pass 1 tests, so they need no model.

**Files:**
- Create: `backend/tests/test_brief_anchor_domains.py`
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/anchor_replay.py`

- [ ] **Step 0: Cross-domain pass 1 tests** (write, run, fix at the root if any fail, commit)

```python
"""brief_anchor pass 1 across domains (the stored replay cases are nearly all pancreas): sides, levels, "additional",
a contradicted generic label beside a kept specific one. Synthetic, deterministic, no model."""
import pytest

from rapid_reports_ai import brief_anchor as ba


def neg(text, action, source="sheet"):
    return {"text": text, "action": action, "source": source}


CASES = [
    ("neuro",
     "FINDINGS:\nA large right cerebellar haemorrhage effaces the fourth ventricle. The lateral ventricles are mildly "
     "prominent. No supratentorial haemorrhage. No skull fracture.\n\nIMPRESSION:\nCerebellar haemorrhage.\n",
     [neg("No supratentorial haemorrhage identified", "keep"), neg("No haemorrhage identified", "contradicted"),
      neg("No hydrocephalus identified", "implicated"), neg("No skull fracture identified", "keep")],
     {"neg:0": "term", "neg:1": "shadowed", "neg:2": "left", "neg:3": "term"}),
    ("renal sides",
     "FINDINGS:\nModerate left hydronephrosis to an obstructing 6 mm left ureteric calculus. No right hydronephrosis. "
     "The bladder is unremarkable.\n\nIMPRESSION:\nObstructing left ureteric calculus.\n",
     [neg("No right hydronephrosis identified", "keep", "finding:Hydronephrosis"),
      neg("No hydronephrosis identified", "contradicted")],
     {"neg:0": "term", "neg:1": "shadowed"}),
    ("chest additional",
     "FINDINGS:\nA 9 mm solid nodule in the right lower lobe. No additional pulmonary nodule. The airways are clear."
     "\n\nIMPRESSION:\nIndeterminate right lower lobe nodule.\n",
     [neg("No additional pulmonary nodule identified", "keep", "finding:Pulmonary nodule"),
      neg("No pulmonary nodule identified", "contradicted")],
     {"neg:0": "term", "neg:1": "shadowed"}),
    ("spine levels",
     "FINDINGS:\nPathological collapse of T7 with retropulsion and cord compression. No retropulsion at T8. "
     "\n\nIMPRESSION:\nT7 pathological collapse with cord compression.\n",
     [neg("No retropulsion at T7", "contradicted"), neg("No retropulsion at T8", "keep")],
     {"neg:0": "left", "neg:1": "term"}),          # T7 must never anchor on the T8 sentence
    ("msk",
     "FINDINGS:\nComplete tear of the anterior cruciate ligament. Moderate joint effusion. The posterior cruciate "
     "ligament is intact.\n\nIMPRESSION:\nComplete ACL tear.\n",
     [neg("No joint effusion identified", "contradicted"), neg("No PCL tear identified", "keep")],
     {"neg:0": "left", "neg:1": "left"}),          # a positive sentence is never a unit; PCL is pass 2's job
]


@pytest.mark.parametrize("name,report,negs,expect", CASES, ids=[c[0] for c in CASES])
def test_pass_one_across_domains(name, report, negs, expect):
    got, left = ba.match_terms(report, ba.brief_labels({"negatives": negs}), ba.units(report))
    left_refs = {l.ref for l in left}
    for ref, want in expect.items():
        if want == "left":
            assert ref in left_refs, (name, ref)
        elif want == "shadowed":
            assert got[ref].how == "none" and got[ref].shadowed_by, (name, ref)
        else:
            assert got[ref].how == "term" and report[got[ref].span[0]:got[ref].span[1]] == got[ref].span_text
```

Run: `.venv/bin/pytest tests/test_brief_anchor_domains.py -q`
Expected: PASS. A failure is a pass 1 defect (key term, units or ranking). Fix it in `brief_anchor.py`, never by editing the expectation.

```bash
git add backend/tests/test_brief_anchor_domains.py backend/src/rapid_reports_ai/brief_anchor.py
git commit -m "test(brief-anchor): pass 1 across neuro, renal, chest, spine and MSK traps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 1: Write the replay script**

```python
"""Code-only stage (spec 2026-10-09 §5.2): brief_anchor on every stored report with brief decisions, no regeneration.
Pass 2 runs live (Jev, cheap); the contradiction scores are not re-asked, so the rules use the stored flags only.

    python -m rapid_reports_ai.scripts.review_labs.anchor_replay [--days 30]

Writes $RR_LAB_OUT/anchor_replay/<id8>.json per case and prints one table row per label."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from rapid_reports_ai import brief_anchor as ba

from . import common


async def main(days: int) -> None:
    common.load_env()
    rows = common.metabase(
        "select id, candidate_reports->0->>'content' as report, candidate_reports->0->'brief'->'decisions' as d, "
        "candidate_reports->0->'quality_check' as qc from reports "
        f"where candidate_reports->0->'brief'->'decisions' is not null and created_at > now() - interval '{days} days'")
    for r in rows:
        d = r["d"] if isinstance(r["d"], dict) else json.loads(r["d"])
        anchors = await ba.anchor(r["report"], d)
        log = ba.anchor_log(anchors, {})
        common.write_json(common.lab_out("anchor_replay") / f"{r['id'][:8]}.json",
                          {"anchors": [asdict(a) for a in anchors], "log": log})
        print(f"\n== {r['id'][:8]}  labels {log['labels']}  term {log['by_term']}  jev {log['by_jev']}  "
              f"unanchored {len(log['unanchored'])}  brief_errors {log['brief_errors']}")
        for a in anchors:
            print(f"  {a.ref:14} {a.action:13} {a.how:5} {a.span_text[:60]!r}  {a.shadowed_by or ''}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    asyncio.run(main(ap.parse_args().days))
```

- [ ] **Step 2: Run it and hand-read the table**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.anchor_replay`

Read every row. The pass bar:
- every `term` / `jev` anchor sits on the clause that expresses its label;
- every overlap group is resolved by containment or left unanchored;
- d3d1e0a5: "contralateral hilar lymphadenopathy" anchored by term; atom "Mediastinal lymphadenopathy" anchored by jev on the station sentence; atom "Hilar lymphadenopathy" shadowed;
- 29882bd7: the sheet "No ascites" (contradicted) shadowed by the dictated negative and listed in `brief_errors`.

Fix any wrong anchor at its root (key term, units or ranking) with a new unit test reproducing it in synthetic form, then re-run.

- [ ] **Step 3: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/review_labs/anchor_replay.py
git commit -m "lab(brief-anchor): code-only replay on stored cases

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: End-to-end run, full suites, ledger, PR

- [ ] **Step 1: Full test suites**

Run: `cd backend && .venv/bin/pytest -q` and `cd frontend && npx vitest run`
Expected:
- all pass, except the pre-existing failures recorded on main before this branch (compare with `git stash; pytest` on main if a failure looks unrelated);
- `npx svelte-check` reports no new errors in the files touched.

- [ ] **Step 2: One end-to-end run on ~6 targeted cases** (against the stored baseline; eval-economy protocol)

Start the backend locally. Regenerate the dictations of d3d1e0a5, 29882bd7, de42a105 and three of the Sept 29 cases (spine, cerebellar, appendix) through the quick endpoint, then let the review run. Add two synthetic dictations outside the stored domains: the renal-sides and MSK dictations from `tests/test_brief_anchor_domains.py`. That gives two cases from the pancreas family and six from other domains.

For each, record in `$RR_LAB_OUT/e2e/`:
- `quality_check.anchor_log`;
- `brief_conflicts`;
- review items by kind and form;
- `timings_ms.negatives_wait_ms`;
- the classifier's `classified` count.

Check the spec §5 success bar:
- trace 2: no card, amber;
- trace 3: amber on the station sentence;
- trace 4: at most one conflict card and no removal;
- 29882bd7: "No ascites" and "No encasement of the SMA" untinted (needs `RR_BRIEF_FULL_LABELS=1` for this run);
- de42a105: duct, CBD calculus and peripancreatic negatives amber, hepatic green;
- no "uncertain" cards;
- 0 false auto-removals;
- classifier statements down ≥50% vs the stored baseline (16 → ≤8 on d3d1e0a5).

- [ ] **Step 3: Ledger entry**

Append to `docs/model-migration/parameter-ledger.md` under the next free L-number:
- the decision (one owner per judgement, `brief_anchor`, the rules, implicated → amber, the four-label scheme flag);
- the two lab results;
- the code-only stage counts;
- the e2e success-bar numbers;
- the flags: `RR_BRIEF_ANCHOR` (default on), `RR_BRIEF_FULL_LABELS` (default per Task 10).

- [ ] **Step 4: Commit, push, open the PR** (Hassan approves the merge and any Railway flag)

```bash
git add docs/model-migration/parameter-ledger.md
git commit -m "docs(ledger): L-<n> negatives one owner per judgement

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin feat/negatives-one-owner
gh pr create --title "Negatives: one owner per judgement (brief anchors, conflict cards, implicated → amber)" --body "$(cat <<'EOF'
## Summary
- `brief_anchor`: every brief label (negatives, linked-normal atoms, dictated negatives) tied to the clause the generator wrote — code term match, Jev link for leftovers.
- Post-gen check: a brief-kept clause Jev doubts is a conflict card, never a removal; an OMIT clause is removed only with two signals; dictated beats OMIT.
- Review engine: items and conflict cards from the anchors; the negatives classifier skips every anchored span; implicated is an amber AI-layer statement, not a check card; tint by origin.
- Brief labeller: four-label scheme behind `RR_BRIEF_FULL_LABELS`.

Spec: docs/superpowers/specs/2026-10-09-negatives-one-owner-design.md · Plan: docs/superpowers/plans/2026-10-09-negatives-one-owner.md

## Test plan
- [ ] backend + frontend suites
- [ ] wording lab gate (Task 4) and brief labeller gate (Task 10) results in the ledger
- [ ] code-only replay hand-read (Task 12)
- [ ] e2e success bar on 6 cases (Task 13)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes (resolved while writing)

- **Spec §3.1 overlaps:** the spec sends overlap groups to Jev, but the plan resolves containment overlaps in code (longest term first; an OMIT label whose words a longer label holds is shadowed). This is deterministic and handles the pleural-effusion trap without a model call. Only labels with no hit or several free hits go to pass 2. The spec has been updated to match.
- **Spec §3.3 logging:** unanchored labels are logged in `quality_check.anchor_log`, which is persisted with the candidate, not in `run.lanes`. The spec has been updated to match.
- **Spec §5.0 size:** the lab uses the stored cases plus 12 synthetic cases (about 20), not about 30, following the eval-economy rule. The spec has been updated to match.
