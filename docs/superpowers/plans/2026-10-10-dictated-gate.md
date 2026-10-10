# Dictated Gate and Review Tiers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Jev question per report clause, asked against the raw dictation, decides "is it dictated?". A tier rule then highlights only review-worthy additions (violet on the added words, recommendations as today) and puts routine additions in the quiet tier, shown only with the AI toggle.

**Rollout shape (Hassan, 2026-10-10):** live shows the NEW tiers in the editor while today's path still runs and is
logged next to it (`today`, per-clause `old`), so the comparison survives without hiding the change. `shadow` stays
available (log only, display unchanged) but the deploy goes straight to `live`.

**Architecture:**
- New module `review_engine/dictated_gate.py`:
  - the question (frozen lab wording Q3s), its state, and answer parsing;
  - `classify` (gate verdict and tier per Jev-pass clause);
  - `apply` (live: builds the items);
  - `shadow_log`.
- The gate questions run as extra parallel requests inside `jev_pass.run`.
- `engine.run_review`:
  - **shadow:** logs the gate next to today's items;
  - **live:** today's `provenance.build_items` + `provenance.confirm` still run; `dictated_gate.apply` then replaces their items (and the negatives / brief AI-layer items it drops) for display, and today's items go into the log as the comparison. Any gate failure leaves today's items shown.
- Frontend: violet becomes always visible, and `ai_generated` items paint their `also_anchors`.

**Tech Stack:** Python 3 (pydantic v2, asyncio, pytest with pytest-asyncio), Jev via `report_reconcile._jev`, SvelteKit + CodeMirror 6 (vitest).

**Spec:** `docs/superpowers/specs/2026-10-10-dictated-gate-review-tiers-design.md`

**Flag default:** the code default for `RR_DICTATED_GATE` is `off`, so existing tests and the Jev request count are unchanged. It is set to `live` on Railway at deploy (Task 10), with Hassan's approval, as for every flag.

**Standing rules for every task:**
- Production report text never goes into the repo (tests use synthetic text).
- Do not touch `backend/reports/` or `backend/research_notes/`.
- Every commit message ends with:

  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Fiz9TX8LW9hcVBeho2LKuV
  ```
- Run backend tests from `backend/` with `.venv/bin/pytest`; frontend tests from `frontend/` with `bun run test -- <file>`.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/src/rapid_reports_ai/review_engine/dictated_gate.py` (create) | mode flag, question/state, answer parsing, clause location, tier rule, word runs, live `apply`, `shadow_log` |
| `backend/src/rapid_reports_ai/review_engine/jev_pass.py` (modify) | `JevPass.gate` / `gate_error`; gate requests in the parallel `gather` |
| `backend/src/rapid_reports_ai/review_engine/negatives.py` (modify) | `amber_hygiene` (no-pointer amber → quiet; overlapping amber collapse) |
| `backend/src/rapid_reports_ai/review_engine/engine.py` (modify) | shadow log, live path + fallback, persist `dictated_gate` and `provenance` in the shadow log |
| `backend/tests/test_review_engine_dictated_gate.py` (create) | unit tests for the module |
| `backend/tests/test_review_engine_engine.py` (modify) | engine shadow / live / fallback tests |
| `backend/tests/test_review_engine_negatives.py` (modify) | `amber_hygiene` tests |
| `backend/scripts/review_labs/dictated_gate_replay.py` (create) | replay dumped reports through `run_review` with the gate in shadow; writes per-clause jsonl |
| `frontend/src/lib/review/editor/theme.ts` (modify) | violet always visible |
| `frontend/src/lib/review/editor/field.ts` (modify) | paint `also_anchors` of `ai_generated` items |
| `frontend/src/lib/review/editor/decorations.ts` (modify) | legend copy |
| `frontend/src/lib/review/editor/field.test.ts`, `decorations.svelte.test.ts` (modify) | tests |
| `docs/model-migration/parameter-ledger.md` (modify) | ledger entry |

---

### Task 1: Gate question, state, flag and answer parsing

**Files:**
- Create: `backend/src/rapid_reports_ai/review_engine/dictated_gate.py`
- Test: `backend/tests/test_review_engine_dictated_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Dictated gate (spec 2026-10-10): one Jev question per report clause against the raw dictation decides whether
the clause is dictated; a tier rule decides what is highlighted. Synthetic cases only, no model calls."""
import pytest

from rapid_reports_ai.review_engine import dictated_gate as dg

from tests.review_engine_fakes import inp


def test_mode_defaults_off_and_reads_env(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_GATE", raising=False)
    assert dg.mode() == "off"
    for v, want in (("shadow", "shadow"), (" LIVE ", "live"), ("off", "off"), ("bogus", "off")):
        monkeypatch.setenv("RR_DICTATED_GATE", v)
        assert dg.mode() == want


def test_question_is_the_frozen_lab_wording():
    q = dg.q_gate("The liver is normal.")
    assert q["type"] == "choice"
    assert q["instructions"].startswith('The report says: "The liver is normal.". Compare every detail in it')
    assert set(q["criteria"]) == {"all_stated", "some_details_added", "not_stated"}


def test_state_labels_history_as_context_only():
    i = inp("FINDINGS:\nX.", "- X", history="Fall.", scan="CT head")
    s = dg.state(i)
    assert s.startswith("SCAN TYPE: CT head\n")
    assert "CLINICAL HISTORY (context only; it is NOT part of the dictated findings): Fall." in s
    assert s.endswith("DICTATED FINDINGS:\n- X")
    assert "CLINICAL HISTORY" not in dg.state(inp("FINDINGS:\nX.", "- X"))


def test_questions_are_batched_four_per_request():
    batches = dg.questions(["a", "b", "c", "d", "e"])
    assert [sorted(b) for b in batches] == [["g0", "g1", "g2", "g3"], ["g4"]]
    assert dg.questions([]) == []


@pytest.mark.parametrize("ans,want", [
    ({"probabilities": {"all_stated": 0.8, "some_details_added": 0.15, "not_stated": 0.05}}, 0.8),
    ({"choice": "all_stated"}, 1.0),
    ({"choice": "not_stated"}, 0.0),
    ({"noul": 0.4}, None),
    (None, None),
    ({"probabilities": {"all_stated": "x"}}, None),
])
def test_p_all_stated(ans, want):
    assert dg.p_all_stated(ans) == want
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py -q`
Expected: FAIL with `ImportError: cannot import name 'dictated_gate'`

- [ ] **Step 3: Write the module**

```python
"""Dictated gate (spec docs/superpowers/specs/2026-10-10-dictated-gate-review-tiers-design.md).

One owner for "is this report clause dictated?": one Jev choice per Jev-pass clause (FINDINGS + IMPRESSION on quick
reports), asked against the RAW dictation (scan type, history as context only, dictated findings). A clause is
dictated only when P(all_stated) >= GATE_MIN; everything else counts as added (default added: a miss costs a tint,
never hides AI text). A tier rule over the gate verdict and the Jev statement type then decides display:
quiet (routine added normal / bolted-on negative, AI toggle), review recommendation, or review synthesis (violet on
the added words).

Lab evidence (scratchpad labs/gate_a, confirm, confirm2, sorter; Jev 1.13, 2 runs): over 24 prod reports the
live system left 54 AI clauses plain against 3-4 for this gate, with 6/75 dictated clauses tinted; the sorter
(tier rule) caught 64-65/70 review items at precision 0.97, ~2.75 highlights per report.

RR_DICTATED_GATE = off (default) | shadow (ask and log, display unchanged) | live (the gate's items replace
provenance's; today's path is the fallback on any gate failure)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .items import ReviewInput

GATE_MIN = 0.7          # P(all_stated) >= this → dictated (lab Q3s: lowest firm-gold dictated clause 0.74-0.80)
CHUNK = 4               # clauses per Jev request (the lab's batch size)
DETECTOR = "dictated_gate"
CHOICES = ("all_stated", "some_details_added", "not_stated")


def mode() -> str:
    v = (os.environ.get("RR_DICTATED_GATE") or "off").strip().lower()
    return v if v in ("off", "shadow", "live") else "off"


def q_gate(clause: str) -> dict:
    """Lab arm Q3s, verbatim (scratchpad labs/gate_a/run_jev.py)."""
    return {"type": "choice", "instructions": (
        f'The report says: "{clause}". Compare every detail in it with the dictated findings: each finding, '
        "structure, side, level, size, descriptor, negated item, diagnosis, cause and recommendation."),
        "criteria": {"all_stated": "Every detail in the statement is stated in the dictated findings, in the same or "
                                   "other words (synonym, abbreviation, expansion or reordering).",
                     "some_details_added": "The dictation states part of it, but the statement adds at least one detail "
                                           "the dictation does not state: a descriptor, an extra negated item, a "
                                           "diagnosis, a cause or an inference.",
                     "not_stated": "The dictation does not state it; it was added by the report writer."}}


def state(inp: ReviewInput) -> str:
    h = (f"CLINICAL HISTORY (context only; it is NOT part of the dictated findings): {inp.clinical_history}\n"
         if inp.clinical_history else "")
    return f"SCAN TYPE: {inp.scan_type}\n{h}DICTATED FINDINGS:\n{inp.artifacts.dictated_findings}"


def questions(clauses: List[str]) -> List[Dict[str, dict]]:
    """One {g{i}: question} dict per request, CHUNK clauses each, i indexing `clauses`."""
    return [{f"g{i}": q_gate(clauses[i]) for i in range(k, min(k + CHUNK, len(clauses)))}
            for k in range(0, len(clauses), CHUNK)]


def p_all_stated(ans: Any) -> Optional[float]:
    """P(all_stated) of a gate answer; a bare choice counts 1 / 0; None when unreadable."""
    if not isinstance(ans, dict):
        return None
    probs = ans.get("probabilities")
    if isinstance(probs, dict) and any(k in probs for k in CHOICES):
        try:
            return float(probs.get("all_stated", 0) or 0)
        except (TypeError, ValueError):
            return None
    ch = ans.get("choice")
    return None if ch not in CHOICES else (1.0 if ch == "all_stated" else 0.0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/dictated_gate.py backend/tests/test_review_engine_dictated_gate.py
git commit -m "feat(review): dictated gate question, state and flag (off by default)"
```

---

### Task 2: Gate requests inside the shared Jev pass

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/jev_pass.py` (`JevPass` fields; `run`, the `gather`)
- Test: `backend/tests/test_review_engine_dictated_gate.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import jev_pass

from tests.review_engine_fakes import jev

R = ("FINDINGS:\nThere is a 2 cm mass in the right kidney. The liver is normal. The spleen is normal.\n"
     "IMPRESSION:\nRight renal mass.\n")
D = "- 2 cm right renal mass\n- Liver normal"


@pytest.mark.asyncio
async def test_off_asks_no_gate_questions(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_GATE", raising=False)
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    jp = await jev_pass.run(inp(R, D), R)
    assert not any(k.startswith("g") for _, qs in calls for k in qs)
    assert jp.gate == {} and jp.gate_error is None


@pytest.mark.asyncio
async def test_shadow_asks_every_clause_in_batches_with_the_gate_state(monkeypatch):
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"g*": {"choice": "all_stated"}}, calls=calls))
    jp = await jev_pass.run(inp(R, D), R)
    gate_calls = [(s, qs) for s, qs in calls if any(k.startswith("g") for k in qs)]
    assert all(set(qs) <= {f"g{i}" for i in range(len(jp.clauses))} for _, qs in gate_calls)
    assert sorted(k for _, qs in gate_calls for k in qs) == sorted(f"g{i}" for i in range(len(jp.clauses)))
    assert all(len(qs) <= 4 for _, qs in gate_calls)
    assert all(s.endswith("DICTATED FINDINGS:\n" + D) for s, _ in gate_calls)
    assert set(jp.gate) == {f"g{i}" for i in range(len(jp.clauses))}


@pytest.mark.asyncio
async def test_a_failed_gate_request_sets_gate_error(monkeypatch):
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    base = jev()

    async def flaky(state, qs):
        if any(k.startswith("g") for k in qs):
            raise TimeoutError("slow")
        return await base(state, qs)
    monkeypatch.setattr(rc, "_jev", flaky)
    jp = await jev_pass.run(inp(R, D), R)
    assert jp.gate_error and "TimeoutError" in jp.gate_error
    assert jp.contra_error is None            # the other requests are unaffected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py -q -k "gate_questions or batches or gate_error"`
Expected: FAIL with `AttributeError: 'JevPass' object has no attribute 'gate'`

- [ ] **Step 3: Implement**

In `jev_pass.py`, add the import next to the other relative imports:

```python
from . import dictated_gate
```

Add two fields to `class JevPass(BaseModel)`, after `support_error`:

```python
    gate: Dict[str, Any] = {}              # g{i} (dictated gate, spec 2026-10-10), i indexes `clauses`
    gate_error: Optional[str] = None
```

In `run`, replace the `gather` block and the result loop:

```python
    contra, omit, support = await asyncio.gather(
        ask(f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        ask(f"REPORT:\n{without(report, hidden, sections)}", omit_qs),
        ask(support_state(inp), support_qs), return_exceptions=True)
    out = JevPass(clauses=cls, before=before, items=items, heads=heads)
    for name, res in (("contra", contra), ("omit", omit), ("support", support)):
```

with:

```python
    gate_batches = dictated_gate.questions(cls) if dictated_gate.mode() != "off" else []
    gate_state = dictated_gate.state(inp)
    contra, omit, support, *gate = await asyncio.gather(
        ask(f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        ask(f"REPORT:\n{without(report, hidden, sections)}", omit_qs),
        ask(support_state(inp), support_qs),
        *(ask(gate_state, qs) for qs in gate_batches), return_exceptions=True)
    out = JevPass(clauses=cls, before=before, items=items, heads=heads)
    for res in gate:                       # any failed batch fails the gate: the engine falls back as a whole
        if isinstance(res, BaseException):
            out.gate_error = f"{type(res).__name__}: {str(res)[:200]}"
            logger.warning("review engine: Jev gate request failed (%s)", type(res).__name__)
        else:
            out.gate.update(res or {})
    for name, res in (("contra", contra), ("omit", omit), ("support", support)):
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py tests/test_review_engine_engine.py tests/test_review_engine_lanes.py -q`
Expected: PASS (gate off by default, so the existing tests are unchanged)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/jev_pass.py backend/tests/test_review_engine_dictated_gate.py
git commit -m "feat(review): dictated gate questions run in parallel inside the shared Jev pass"
```

---

### Task 3: Clause location, word runs and the tier rule (`classify`)

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/dictated_gate.py`
- Test: `backend/tests/test_review_engine_dictated_gate.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.jev_pass import JevPass


def _jp(clauses, p, types):
    """A JevPass with gate answers p[i] and statement types types[i] for clauses[i]."""
    jp = JevPass(clauses=clauses)
    jp.gate = {f"g{i}": {"probabilities": {"all_stated": v, "some_details_added": 1 - v, "not_stated": 0.0}}
               for i, v in enumerate(p) if v is not None}
    jp.types = {c: t for c, t in zip(clauses, types) if t}
    return jp


def _classify(report, dictation, clauses, p, types):
    i = inp(report, dictation)
    al = align(report, dictation, "", i.artifacts.sections)
    return dg.classify(i, report, al, _jp(clauses, p, types))


RPT = ("FINDINGS:\nAn 11 mm crescentic subdural haematoma over the left convexity. The liver is normal. "
       "Left ovary normal with no contralateral adnexal mass.\n"
       "IMPRESSION:\nAcute subdural haematoma. Repeat CT head in 6 hours is recommended.\n")
DIC = "- 11 mm left convexity subdural haematoma\n- Left ovary normal"
CL = ["An 11 mm crescentic subdural haematoma over the left convexity.", "The liver is normal.",
      "Left ovary normal with no contralateral adnexal mass.", "Acute subdural haematoma.",
      "Repeat CT head in 6 hours is recommended."]


def test_tiers():
    g = _classify(RPT, DIC, CL, [0.3, 0.1, 0.4, 0.75, 0.0],
                  ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"])
    assert [x.tier for x in g] == ["synth", "quiet", "quiet", "dictated", "rec"]
    assert all(x.start is not None and RPT[x.start:x.end] == x.text for x in g)
    assert [x.section for x in g][:1] == ["FINDINGS"] and g[4].section == "IMPRESSION"


def test_synth_runs_are_the_added_words():
    g = _classify(RPT, DIC, CL, [0.3, 0.9, 0.9, 0.9, 0.9], ["abnormal"] * 5)
    assert [RPT[s:e] for s, e in g[0].runs] == ["crescentic"]


def test_unreadable_answer_is_unknown_and_threshold_is_inclusive():
    g = _classify(RPT, DIC, CL, [None, 0.7, 0.69, 0.9, 0.9], ["abnormal", "normal", "normal", "abnormal", None])
    assert [x.tier for x in g][:3] == ["unknown", "dictated", "quiet"]


def test_a_negated_recommendation_is_review_not_quiet():
    r = "IMPRESSION:\nFunctional cyst; no urgent surgical referral is indicated.\n"
    c = ["no urgent surgical referral is indicated."]
    g = _classify(r, "- Right ovarian simple cyst 28 mm", c, [0.1], ["not_a_finding"])
    assert g[0].tier == "rec"


def test_a_clause_not_found_in_the_report_is_unplaced():
    g = _classify(RPT, DIC, ["Not in this report."], [0.1], ["abnormal"])
    assert g[0].start is None and g[0].tier == "synth"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py -q -k "tiers or runs or unknown or negated or unplaced"`
Expected: FAIL with `AttributeError: module ... has no attribute 'classify'`

- [ ] **Step 3: Implement** (append to `dictated_gate.py`; add imports at the top)

```python
import re
from dataclasses import dataclass, field
from typing import Tuple

from .alignment import Alignment, ReportClause
from .claims import content_words
```

```python
# Common radiology abbreviations in a dictation, expanded so the report's spelled-out words are not "new" words.
# Fixed list: it only shapes WHERE a highlight falls inside a clause the gate already called added; never grow it
# by example (spec §4.3; the lab's hand-grown synonym trim overfitted).
ABBREV = {"rll": "right lower lobe", "rul": "right upper lobe", "rml": "right middle lobe", "lll": "left lower lobe",
          "lul": "left upper lobe", "gb": "gallbladder", "cbd": "common bile duct", "vuj": "vesicoureteric junction",
          "uvj": "ureterovesical junction", "rv": "right ventricle", "lv": "left ventricle",
          "sdh": "subdural haematoma", "sah": "subarachnoid haemorrhage", "ich": "intracranial haemorrhage",
          "pe": "pulmonary embolism", "ivc": "inferior vena cava", "smv": "superior mesenteric vein",
          "sma": "superior mesenteric artery", "pv": "portal vein", "pod": "pouch of douglas"}
_NEGATOR = re.compile(r"\b(?:no|not|without|nor)\b", re.I)


@dataclass
class GateClause:
    i: int
    text: str
    start: Optional[int]          # report offsets; None when the clause is not found in the report
    end: Optional[int]
    section: Optional[str]
    p: Optional[float]            # P(all_stated); None when unreadable
    q_type: Optional[str]
    tier: str                     # dictated | quiet | rec | synth | unknown
    runs: List[Tuple[int, int]] = field(default_factory=list)   # report spans of words absent from the dictation
    aclause: Optional[ReportClause] = None                      # the alignment clause holding `start`


def dictated_words(dictation: str) -> set:
    words = set(content_words(dictation))
    for w in re.findall(r"[A-Za-z]+", dictation or ""):
        if w.lower() in ABBREV:
            words |= content_words(ABBREV[w.lower()])
    return words


def _locate(body: str, clauses: List[str]) -> List[Optional[Tuple[int, int]]]:
    out, cur = [], 0
    for t in clauses:
        k = body.find(t, cur)
        if k < 0:
            k = body.find(t)
        if k < 0:
            out.append(None)
            continue
        out.append((k, k + len(t)))
        cur = k + len(t)
    return out


def _negated_only(body: str, s: int, runs: List[Tuple[int, int]]) -> bool:
    """Every added run follows a negator earlier in the same clause: a negative bolted onto a dictated finding."""
    return bool(runs) and all(_NEGATOR.search(body[s:a]) for a, _ in runs)


def tier_of(p: Optional[float], q_type: Optional[str], is_rec: bool, negated_only: bool) -> str:
    """Spec §4.2. Display only: provenance is the gate's (p)."""
    if p is None:
        return "unknown"
    if p >= GATE_MIN:
        return "dictated"
    if q_type == "normal":
        return "quiet"
    if is_rec:
        return "rec"
    if q_type in ("abnormal", "mixed") and negated_only:
        return "quiet"
    return "synth"


def classify(inp: ReviewInput, body: str, al: Alignment, jp) -> List[GateClause]:
    """One GateClause per Jev-pass clause, in order. Pure code over the gate answers already in `jp`."""
    from .provenance import _proposed_runs, is_recommendation     # provenance imports jev_pass, which imports us
    words = dictated_words(inp.artifacts.dictated_findings)
    out: List[GateClause] = []
    for i, (t, at) in enumerate(zip(jp.clauses, _locate(body, jp.clauses))):
        q = jp.clause_type(i)
        p = p_all_stated(jp.gate.get(f"g{i}"))
        s, e = at if at else (None, None)
        ac = next((c for c in al.clauses if s is not None and c.start <= s < c.end), None) if at else None
        section = ac.section if ac else None
        runs = _proposed_runs(body, s, e, words) if at else []
        rec = is_recommendation(t, q, section)
        out.append(GateClause(i=i, text=t, start=s, end=e, section=section, p=p, q_type=q,
                              tier=tier_of(p, q, rec, _negated_only(body, s, runs) if at else False),
                              runs=runs, aclause=ac))
    return out
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py -q`
Expected: PASS. If `test_tiers` fails only on `section` because `al.clauses` does not cover a clause, print `[ (c.start, c.end, c.section) for c in al.clauses ]` and fix `_locate`/the containment test. Do not weaken the tier assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/dictated_gate.py backend/tests/test_review_engine_dictated_gate.py
git commit -m "feat(review): dictated gate classify: clause location, added-word runs, tier rule"
```

---

### Task 4: Live items (`apply`) and the shadow log

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/dictated_gate.py`
- Test: `backend/tests/test_review_engine_dictated_gate.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from rapid_reports_ai.review_engine.items import ReviewItem, Span, text_hash

RUN = "00000000-0000-0000-0000-0000000000f1"


def _item(kind, report, text, form=None, cls="info", pointer=None):
    s = report.index(text)
    ev = {} if form is None else {"form": form}
    if pointer is not None:
        ev["pointer"] = pointer
    return ReviewItem(key=f"k-{kind}-{s}", report_id="00000000-0000-0000-0000-000000000001", run_id=RUN,
                      lane="accuracy", detectors=["t"], kind=kind, cls=cls, section="FINDINGS",
                      anchor=Span(start=s, end=s + len(text), text=text, text_hash=text_hash(report)),
                      label="", reason="", evidence=ev, status="open", history=[])


def _apply(p, types, neg=(), brief=()):
    i = inp(RPT, DIC)
    al = align(RPT, DIC, "", i.artifacts.sections)
    g = dg.classify(i, RPT, al, _jp(CL, p, types))
    return dg.apply(i, RUN, al, g, list(neg), list(brief))


def test_live_builds_synthesis_on_the_added_words_and_a_recommendation():
    prov, neg, brief, log = _apply([0.3, 0.9, 0.9, 0.9, 0.0], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"])
    syn = [it for it in prov if it.kind == "ai_generated"]
    rec = [it for it in prov if it.kind == "recommendation"]
    assert [it.anchor.text for it in syn] == ["crescentic"]
    assert syn[0].evidence["form"] == "synthesis" and syn[0].evidence["source"] == "dictated_gate"
    assert [it.anchor.text for it in rec] == ["Repeat CT head in 6 hours is recommended."]
    assert rec[0].edit is not None
    assert log["synthesis"] == 1 and log["recommendation"] == 1


def test_live_quiet_clause_without_an_item_gets_a_quiet_one_and_dictated_drops_ai_layer_items():
    green = _item("assumed_normal", RPT, "The liver is normal.", form="normal")
    prov, neg, brief, log = _apply([0.9, 0.9, 0.2, 0.9, 0.9], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"],
                                   neg=[green])
    assert neg == []                                     # gate says dictated: the radiologist's own text
    quiet = [it for it in prov if it.kind == "assumed_normal"]
    assert [it.anchor.text for it in quiet] == ["Left ovary normal with no contralateral adnexal mass."]
    assert quiet[0].evidence["form"] == "normal"
    assert log["dropped"] == [green.key]


def test_live_keeps_check_cards_on_dictated_clauses():
    card = _item("check", RPT, "The liver is normal.", cls="action")
    _, neg, _, _ = _apply([0.9] * 5, ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"], neg=[card])
    assert neg == [card]


def test_live_quiet_clause_already_covered_adds_nothing():
    amber = _item("assumed_normal", RPT, "The liver is normal.", form="negative", pointer="x")
    prov, neg, _, _ = _apply([0.9, 0.1, 0.9, 0.9, 0.9], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"],
                             neg=[amber])
    assert neg == [amber] and [it for it in prov if it.kind == "assumed_normal"] == []


def test_apply_does_not_mutate_its_inputs():
    green = _item("assumed_normal", RPT, "The liver is normal.", form="normal")
    neg = [green]
    i = inp(RPT, DIC)
    al = align(RPT, DIC, "", i.artifacts.sections)
    g = dg.classify(i, RPT, al, _jp(CL, [0.9] * 5, ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"]))
    dg.apply(i, RUN, al, g, neg, [])
    assert neg == [green]


def test_shadow_log_records_tiers_and_what_tinted_each_clause_today():
    green = _item("assumed_normal", RPT, "The liver is normal.", form="normal")
    i = inp(RPT, DIC)
    al = align(RPT, DIC, "", i.artifacts.sections)
    g = dg.classify(i, RPT, al, _jp(CL, [0.3, 0.9, 0.2, 0.9, 0.0], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"]))
    log = dg.shadow_log(g, [green])
    assert log["mode"] == "shadow"
    assert [c["tier"] for c in log["clauses"]] == ["synth", "dictated", "quiet", "dictated", "rec"]
    assert log["clauses"][1]["old"] == ["assumed_normal:normal"]
    assert log["counts"] == {"synth": 1, "dictated": 2, "quiet": 1, "rec": 1}
    assert log["added_plain_today"] == 3                 # synth, quiet and rec clauses with no item today
    assert log["dictated_tinted_today"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py -q -k "live or shadow_log or mutate"`
Expected: FAIL with `AttributeError: module ... has no attribute 'apply'`

- [ ] **Step 3: Implement** (append to `dictated_gate.py`)

```python
AI_LAYER = ("assumed_normal", "ai_generated")


def _ai_layer(it) -> bool:
    return it.kind in AI_LAYER and it.cls == "info" and it.anchor is not None


def _overlaps(it, s: int, e: int) -> bool:
    return it.anchor is not None and it.anchor.start < e and s < it.anchor.end


def _clause_log(g: GateClause) -> dict:
    return {"i": g.i, "section": g.section, "start": g.start, "end": g.end, "p": g.p, "q_type": g.q_type,
            "tier": g.tier, "runs": [list(r) for r in g.runs]}


def apply(inp: ReviewInput, run_id: str, al: Alignment, gate: List[GateClause], neg_items: list, brief_items: list):
    """Live (spec §4.4): (provenance items, negatives items, brief items, log). Inputs are not mutated.
    - dictated clause: AI-layer items (assumed_normal / ai_generated, cls info) that touch no added clause are dropped;
      cards (check, removed, ...) stay;
    - quiet clause with no AI-layer item on it: a quiet `assumed_normal` item (form normal);
    - synth clause: one `ai_generated` item on the added-word runs (first run the anchor, the rest `also_anchors`;
      no run → the whole clause);
    - rec clause: one `recommendation` item per sentence, placed and given its removal by provenance's code."""
    from .items import text_hash
    from .provenance import (DETECTOR_REC, KIND_REC, MAX_AI_ITEMS, _ai_item, _new_item, _rec_target)
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    placed = [g for g in gate if g.start is not None]
    added = [(g.start, g.end) for g in placed if g.tier in ("quiet", "rec", "synth")]
    dictated = [(g.start, g.end) for g in placed if g.tier == "dictated"]

    def keep(it) -> bool:
        if not _ai_layer(it):
            return True
        on_dictated = any(_overlaps(it, s, e) for s, e in dictated)
        return not on_dictated or any(_overlaps(it, s, e) for s, e in added)

    neg = [it for it in neg_items if keep(it)]
    brief = [it for it in brief_items if keep(it)]
    dropped = [it.key for it in list(neg_items) + list(brief_items) if not keep(it)]
    existing = [it for it in neg + brief if _ai_layer(it)]
    prov: list = []
    synth, rec_seen, unplaced, capped = 0, set(), sum(1 for g in gate if g.start is None), 0
    for g in placed:
        if g.tier == "quiet":
            if not any(_overlaps(it, g.start, g.end) for it in existing):
                prov.append(_new_item(inp, run_id, "accuracy", "assumed_normal", "info", DETECTOR, g.section or "",
                                      g.start, g.end, "Assumed normal", "",
                                      {"form": "normal", "source": DETECTOR, "p": g.p, "q_type": g.q_type}))
        elif g.tier == "synth":
            if synth >= MAX_AI_ITEMS:
                capped += 1
                continue
            runs = g.runs or [(g.start, g.end)]
            also = [{"start": a, "end": b, "text": report[a:b], "text_hash": h} for a, b in runs[1:]]
            prov.append(_ai_item(inp, run_id, g.section or "", runs[0][0], runs[0][1],
                                 {"form": "synthesis", "source": DETECTOR, "p": g.p, "q_type": g.q_type,
                                  **({"also_anchors": also} if also else {})}))
            synth += 1
        elif g.tier == "rec":
            c = g.aclause
            if c is None or c.sentence_start in rec_seen:
                unplaced += c is None
                continue
            rec_seen.add(c.sentence_start)
            sentence = report[c.sentence_start:c.sentence_end]
            s, e, edit = _rec_target(report, c, sentence, names)
            ok = edit is not None
            prov.append(_new_item(inp, run_id, "additions", KIND_REC, "minor", DETECTOR_REC, c.section, s, e,
                                  "Recommendation not dictated", "Added by the report writer; remove it if not wanted.",
                                  {"sentence": sentence, "source": DETECTOR, "p": g.p}, edit,
                                  {"code": ok, "failed": [] if ok else ["not_placeable"], "addressed": None,
                                   "contra": None, "unconfirmed": True}))
    log = {"mode": "live", "clauses": [_clause_log(g) for g in gate], "dropped": dropped,
           "quiet": sum(1 for it in prov if it.kind == "assumed_normal"), "synthesis": synth,
           "recommendation": len(rec_seen), "capped": capped, "unplaced": unplaced}
    return prov, neg, brief, log


def shadow_log(gate: List[GateClause], items: list) -> dict:
    """Shadow (spec §7): the gate's verdict and tier per clause next to what today's items tint on it."""
    clauses, counts, plain, tinted = [], {}, 0, 0
    for g in gate:
        d = _clause_log(g)
        old = sorted({f"{it.kind}:{(it.evidence or {}).get('form', '')}" for it in items
                      if g.start is not None and _ai_layer(it) and _overlaps(it, g.start, g.end)}
                     | {it.kind for it in items if g.start is not None and it.kind == "recommendation"
                        and _overlaps(it, g.start, g.end)})
        d["old"] = old
        clauses.append(d)
        counts[g.tier] = counts.get(g.tier, 0) + 1
        plain += g.tier in ("quiet", "rec", "synth") and not old
        tinted += g.tier == "dictated" and bool(old)
    return {"mode": "shadow", "clauses": clauses, "counts": counts, "added_plain_today": plain,
            "dictated_tinted_today": tinted}
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_dictated_gate.py -q`
Expected: PASS. If `test_live_builds_synthesis…` gets `rec[0].edit is None`, check `_rec_target` on the fixture (a whole sentence that occurs once, so the removal must apply); fix the fixture text, not the assertion.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/dictated_gate.py backend/tests/test_review_engine_dictated_gate.py
git commit -m "feat(review): dictated gate live items (synthesis runs, quiet, recommendations) and shadow log"
```

---

### Task 5: Amber hygiene

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/negatives.py` (add after `ai_layer`)
- Test: `backend/tests/test_review_engine_negatives.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from rapid_reports_ai.review_engine.items import ReviewItem, Span


def _amber(key, s, e, pointer, text="No hydronephrosis."):
    return ReviewItem(key=key, report_id="00000000-0000-0000-0000-000000000001",
                      run_id="00000000-0000-0000-0000-0000000000f1", lane="accuracy", detectors=["negatives.v5"],
                      kind="assumed_normal", cls="info", section="FINDINGS",
                      anchor=Span(start=s, end=e, text=text, text_hash="h"), label=negatives.AMBER,
                      reason="r", evidence={"form": "negative", "pointer": pointer}, status="open", history=[])


def test_amber_without_a_pointer_goes_quiet():
    neg, brief, log = negatives.amber_hygiene([_amber("a", 0, 18, "")], [_amber("b", 30, 48, "—")])
    assert [it.evidence["form"] for it in neg + brief] == ["normal", "normal"]
    assert [it.label for it in neg + brief] == ["Assumed normal", "Assumed normal"]
    assert log == {"no_pointer": 2, "duplicate": 0}


def test_overlapping_amber_collapses_to_the_first():
    neg, brief, log = negatives.amber_hygiene([_amber("a", 0, 18, "stone")], [_amber("b", 5, 18, "stone")])
    assert [it.key for it in neg] == ["a"] and brief == []
    assert log == {"no_pointer": 0, "duplicate": 1}


def test_other_items_pass_through():
    green = _amber("g", 0, 18, "x").model_copy(update={"evidence": {"form": "normal"}})
    neg, brief, log = negatives.amber_hygiene([green], [])
    assert neg == [green] and log == {"no_pointer": 0, "duplicate": 0}
```

(If `test_review_engine_negatives.py` does not already import `negatives`, add `from rapid_reports_ai.review_engine import negatives` at the top.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_negatives.py -q -k amber`
Expected: FAIL with `AttributeError: ... has no attribute 'amber_hygiene'`

- [ ] **Step 3: Implement** (in `negatives.py`, after `ai_layer`)

```python
def amber_hygiene(neg_items: list, brief_items: list):
    """(negatives items, brief items, log). Spec 2026-10-10 §4.5, live gate only: an amber ("bears on your
    finding") item with no pointer has no finding to bear on → quiet (form normal); amber items whose anchors
    overlap collapse to the first (negatives before brief). Inputs are not mutated."""
    log = {"no_pointer": 0, "duplicate": 0}
    kept_spans: list = []

    def fix(items: list) -> list:
        out = []
        for it in items:
            ev = it.evidence or {}
            if it.kind != "assumed_normal" or ev.get("form") != "negative" or it.anchor is None:
                out.append(it)
                continue
            if not pointer_text(ev.get("pointer")):
                log["no_pointer"] += 1
                out.append(it.model_copy(update={"label": "Assumed normal", "reason": "",
                                                 "evidence": {**ev, "form": "normal", "amber": "no_pointer"}}))
                continue
            s, e = it.anchor.start, it.anchor.end
            if any(s < b and a < e for a, b in kept_spans):
                log["duplicate"] += 1
                continue
            kept_spans.append((s, e))
            out.append(it)
        return out

    neg = fix(list(neg_items))
    brief = fix(list(brief_items))
    return neg, brief, log
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_negatives.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/negatives.py backend/tests/test_review_engine_negatives.py
git commit -m "feat(review): amber hygiene: no-pointer amber goes quiet, overlapping amber collapses"
```

---

### Task 6: Engine wiring: shadow, live, fallback, persisted logs

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/engine.py` (`run_review`: Jev error keys; the provenance block; the `run` dict. `_run_and_store`: the `shadow` dict)
- Test: `backend/tests/test_review_engine_engine.py`

- [ ] **Step 1: Write the failing tests** (append; reuse the file's `_stubs` fixture pattern; read `test_run_review_end_to_end` first and copy its setup)

```python
from rapid_reports_ai.review_engine import dictated_gate

GREPORT = ("FINDINGS:\nThere is a 2 cm crescentic mass in the right kidney. The liver is normal.\n"
           "IMPRESSION:\nRight renal mass. Urology referral is recommended.\n")
GDICT = "- 2 cm right renal mass"


def _gate_jev(monkeypatch, p_by_text):
    """Gate answers by clause text (substring match); everything else from the default fake."""
    base = jev()

    async def fake(state, qs):
        out = await base(state, qs)
        for k, q in qs.items():
            if k.startswith("g") and k[1:].isdigit():
                p = next((v for t, v in p_by_text.items() if t in q["instructions"]), 0.9)
                out[k] = {"probabilities": {"all_stated": p, "some_details_added": 1 - p, "not_stated": 0.0}}
        return out
    monkeypatch.setattr(rc, "_jev", fake)


@pytest.mark.asyncio
async def test_shadow_logs_the_gate_and_leaves_items_as_today(monkeypatch, _stubs):
    monkeypatch.setenv("RR_DICTATED_GATE", "off")
    _gate_jev(monkeypatch, {"crescentic": 0.2})
    off = await engine.run_review(inp(GREPORT, GDICT), "00000000-0000-0000-0000-0000000000a1")
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    sh = await engine.run_review(inp(GREPORT, GDICT), "00000000-0000-0000-0000-0000000000a1")
    assert sorted(i.key for i in sh.items) == sorted(i.key for i in off.items)
    assert off.run.get("dictated_gate") is None
    log = sh.run["dictated_gate"]
    assert log["mode"] == "shadow" and any(c["tier"] == "synth" for c in log["clauses"])


@pytest.mark.asyncio
async def test_live_replaces_provenance_items(monkeypatch, _stubs):
    monkeypatch.setenv("RR_DICTATED_GATE", "live")
    _gate_jev(monkeypatch, {"crescentic": 0.2, "Urology": 0.0})
    res = await engine.run_review(inp(GREPORT, GDICT), "00000000-0000-0000-0000-0000000000a1")
    syn = [i for i in res.items if i.kind == "ai_generated"]
    assert [i.anchor.text for i in syn] == ["crescentic"]
    assert all((i.evidence or {}).get("source") == "dictated_gate" for i in syn)
    log = res.run["dictated_gate"]
    assert log["mode"] == "live" and "amber_hygiene" in log
    assert "today" in log and "today_items" in log and all("old" in c for c in log["clauses"])


@pytest.mark.asyncio
async def test_live_falls_back_to_today_when_the_gate_fails(monkeypatch, _stubs):
    monkeypatch.setenv("RR_DICTATED_GATE", "live")
    base = jev()

    async def flaky(state, qs):
        if any(k.startswith("g") and k[1:].isdigit() for k in qs):
            raise TimeoutError("slow")
        return await base(state, qs)
    monkeypatch.setattr(rc, "_jev", flaky)
    res = await engine.run_review(inp(GREPORT, GDICT), "00000000-0000-0000-0000-0000000000a1")
    assert "dictated_gate" in res.run["errors"] or "jev_gate_error" in res.run["errors"]
    assert res.run.get("dictated_gate") is None
    assert not any((i.evidence or {}).get("source") == "dictated_gate" for i in res.items)
```

If the file's stub fixture is not named `_stubs` or is not a fixture, read the top of `test_review_engine_engine.py` (lines 1–70) and adapt the three tests to the same setup `test_run_review_end_to_end` uses. Keep every assertion.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_engine.py -q -k "shadow_logs or live_replaces or falls_back"`
Expected: FAIL (`KeyError: 'dictated_gate'` or an assertion on the missing log)

- [ ] **Step 3: Implement**

In `engine.py`, add the import next to the other review-engine imports:

```python
from . import dictated_gate
```

In `run_review`, change the Jev error key loop:

```python
            for k in ("contra_error", "omit_error", "support_error"):
```

to:

```python
            for k in ("contra_error", "omit_error", "support_error", "gate_error"):
```

Keep the existing provenance block (`provenance.build_items` and `provenance.confirm`) exactly as it is: today's
path always runs first and becomes the comparison. Directly AFTER that block (just before `for it in
surface_gate(`), insert:

```python
    gate_log: Optional[dict] = None
    gm = dictated_gate.mode()
    if gm != "off" and jp is not None and jp.gate and not jp.gate_error:
        try:                             # the dictated gate (spec 2026-10-10): pure code over the Jev pass answers
            gate_clauses = dictated_gate.classify(inp, body, al, jp)
            today = dictated_gate.shadow_log(gate_clauses, neg_items + brief_items + prov)   # what today tints
            gate_log = today
            if gm == "live":             # the gate's items are shown; today's stay in the log for comparison
                g_prov, g_neg, g_brief, live_log = dictated_gate.apply(inp, run_id, al, gate_clauses, neg_items,
                                                                       brief_items)
                g_neg, g_brief, live_log["amber_hygiene"] = negatives.amber_hygiene(g_neg, g_brief)
                for it in g_prov:
                    it.engine_version = ENGINE_VERSION
                if bridge:
                    g_prov, _ = live.dedupe(g_prov, bridge)
                live_log["today"] = {k: today[k] for k in ("counts", "added_plain_today", "dictated_tinted_today")}
                live_log["today_items"] = [{"kind": it.kind, "form": (it.evidence or {}).get("form"),
                                            "anchor": it.anchor.model_dump() if it.anchor else None}
                                           for it in prov]
                prov, neg_items, brief_items, gate_log = g_prov, g_neg, g_brief, live_log
        except Exception as e:  # noqa: BLE001 - never fails the run: today's items stand
            errors["dictated_gate"] = f"{type(e).__name__}: {str(e)[:200]}"
            gate_log = None
```

Each clause entry in the live log keeps its own `old` field: `apply` must copy it from `today`. Add, inside the
`if gm == "live":` branch before `prov, neg_items, ...`:

```python
                for c, t in zip(live_log["clauses"], today["clauses"]):
                    c["old"] = t["old"]
```

In the `run = {...}` dict, after `"provenance": prov_log,` add:

```python
           "dictated_gate": gate_log,
```

In `_run_and_store`, add two keys to the `shadow` dict (after `"negatives_post_removal_anchors": ...`):

```python
              "provenance": res.run.get("provenance"),
              "dictated_gate": res.run.get("dictated_gate"),
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/test_review_engine_engine.py tests/test_review_engine_dictated_gate.py tests/test_review_engine_provenance.py -q`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/pytest -q -x -p no:cacheprovider 2>&1 | tail -5`
Expected: all pass. Record the count in the commit body.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/engine.py backend/tests/test_review_engine_engine.py
git commit -m "feat(review): wire the dictated gate: shadow log, live items with fallback, persisted logs"
```

---

### Task 7: Frontend: violet always visible, painted `also_anchors`, legend copy

**Files:**
- Modify: `frontend/src/lib/review/editor/theme.ts:162-170`
- Modify: `frontend/src/lib/review/editor/field.ts` (the mark loop, at `marks.push({ ...metaOf(it), from: at.from, ...})`)
- Modify: `frontend/src/lib/review/editor/decorations.ts` (`LEGEND_TITLE.ai`, `AI_BREAKDOWN`)
- Test: `frontend/src/lib/review/editor/field.test.ts`, `frontend/src/lib/review/editor/decorations.svelte.test.ts`

- [ ] **Step 1: Write the failing tests**

In `field.test.ts`, inside `describe('review field (generalised to review items)', ...)`, add:

```ts
	it('an ai_generated item paints its also_anchors too; other kinds paint only their anchor', () => {
		const D = 'An 11 mm crescentic subdural with acute traumatic shift.';
		const at = (t: string) => ({ start: D.indexOf(t), end: D.indexOf(t) + t.length, text: t });
		const s = createReviewState(
			D,
			[
				item({ id: 's1', kind: 'ai_generated', cls: 'info', anchor: at('crescentic'), evidence: { form: 'synthesis', also_anchors: [at('traumatic')] } }),
				item({ id: 'c1', kind: 'check', cls: 'minor', anchor: at('acute'), evidence: { also_anchors: [at('shift')] } })
			],
			[history()]
		);
		const marks = reviewItems(s).marks.map((m) => [m.id, D.slice(m.from, m.to)]);
		expect(marks).toEqual([
			['s1', 'crescentic'],
			['c1', 'acute'],
			['s1', 'traumatic']
		]);
	});
```

(Use the same `createReviewState` / `reviewItems` / `history` / `item` helpers the file already imports. If marks carry the item id under another field name, read `MarkMeta` in `field.ts` and use that field.)

In `decorations.svelte.test.ts`, in the test `'the AI-generated layer is on by default: …'`, change the toggled-off loop and the amber note:

```ts
		view.dispatch({ effects: setEmphasis.of([]) });
		for (const id of ['g1']) {
			expect(cs(id).backgroundColor, id).toBe(NONE);
			expect(cs(id).textDecorationLine, id).toBe('none');
		}
		// amber (negative) and violet (synthesis) ignore the toggle: always shown
		expect(cs('c1').backgroundColor).not.toBe(NONE);
		expect(cs('s1').backgroundColor).not.toBe(NONE);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bun run test -- src/lib/review/editor/field.test.ts src/lib/review/editor/decorations.svelte.test.ts`
Expected: FAIL (the `also_anchors` test gets only the primary marks; the violet test sees `NONE` when the toggle is off)

- [ ] **Step 3: Implement**

`theme.ts`, replace:

```ts
	'&[data-rv-emph~="ai"] .rv-form-synthesis': { backgroundColor: 'var(--rv-tint-synthesis)' },
```

with:

```ts
	'.rv-form-synthesis': { backgroundColor: 'var(--rv-tint-synthesis)' }, // violet ignores the toggle (review tier)
```

Also update the comment above the block to read "…a very light tint by category: normals green (only with the toggle); negatives bearing on a finding amber and synthesis violet, always shown; no underline".

`field.ts`, replace:

```ts
		marks.push({ ...metaOf(it), from: at.from, to: at.to, text: doc.slice(at.from, at.to) });
	}
```

with:

```ts
		marks.push({ ...metaOf(it), from: at.from, to: at.to, text: doc.slice(at.from, at.to) });
		if (it.kind === 'ai_generated') {
			// the dictated gate marks every added-word run of a clause: the rest ride in also_anchors
			for (const a of it.evidence?.also_anchors ?? []) {
				const more = locate(doc, { ...it, anchor: a });
				if (more && more.to > more.from) marks.push({ ...metaOf(it), from: more.from, to: more.to, text: doc.slice(more.from, more.to) });
			}
		}
	}
```

(`drawn.sort((a, b) => a.from - b.from)` below already orders them. If the test's expected order differs because the sort puts `traumatic` before `shift`, keep the sort and fix the expected array to document order.)

`decorations.ts`:

```ts
	ai: 'Text not from your dictation. Always shown: violet, details or conclusions the AI added (check them), and amber, negatives bearing on your finding. Green normals the AI assumed show with this toggle',
```

and in `AI_BREAKDOWN`:

```ts
	{ form: 'normal', label: 'Normals', title: 'Normal findings you did not dictate, stated by the AI (shown with the toggle)' },
	{ form: 'negative', label: 'Bears on your finding', title: 'Negatives the AI added that bear on a dictated finding: in the report, worth a glance (always shown)' },
	{ form: 'synthesis', label: 'Added by the AI', title: 'Details, conclusions or interpretation not in your dictation: check them (always shown)' }
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && bun run test -- src/lib/review`
Expected: PASS. If a test asserts the old legend strings, update its expected text to the new copy.

- [ ] **Step 5: Type check**

Run: `cd frontend && bun run check 2>&1 | tail -3`
Expected: 0 errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/review/editor/theme.ts frontend/src/lib/review/editor/field.ts frontend/src/lib/review/editor/decorations.ts frontend/src/lib/review/editor/field.test.ts frontend/src/lib/review/editor/decorations.svelte.test.ts
git commit -m "feat(rail): violet review tint always shown; paint every added-word run; legend copy"
```

---

### Task 8: Replay script for the shadow check

**Files:**
- Create: `backend/scripts/review_labs/dictated_gate_replay.py`

- [ ] **Step 1: Write the script**

```python
"""Replay dumped prod reports through `engine.run_review` with the dictated gate in shadow, writing one jsonl row per
gate clause. Prod text never enters the repo: point --dumps at a scratchpad directory of dumps
({"rep": {"id", "inp", "report_content", "cr"}}, as the live-audit dump scripts write) and --out at the scratchpad.

    cd backend && PYTHONPATH=src RR_DICTATED_GATE=shadow .venv/bin/python scripts/review_labs/dictated_gate_replay.py \
        --dumps <dir> [<dir> ...] --out <file.jsonl>
"""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path


async def one(path: Path, fh) -> None:
    from rapid_reports_ai.review_engine import engine
    d = json.loads(path.read_text())
    rep = d["rep"]
    inp_ = engine.input_from_parts(rep["id"], "quick", json.loads(rep["inp"] or "{}"),
                                   json.loads(rep["cr"] or "{}") if isinstance(rep["cr"], str) else rep["cr"], None)
    if inp_ is None:
        print(f"{path}: no candidate, skipped")
        return
    inp_.artifacts.report = rep["report_content"]
    t = time.monotonic()
    res = await engine.run_review(inp_, "00000000-0000-0000-0000-0000000000ee")
    ms = int((time.monotonic() - t) * 1000)
    log = res.run.get("dictated_gate") or {}
    key = f"{path.parent.name}-{path.stem}"
    for c in log.get("clauses", []):
        s, e = c.get("start"), c.get("end")
        fh.write(json.dumps({"report": key, **c, "text": rep["report_content"][s:e] if s is not None else None,
                             "ms": ms, "jev_ms": res.run["timings_ms"].get("jev_ms")}) + "\n")
    print(f"{key}: {log.get('counts')} plain_today={log.get('added_plain_today')} ms={ms} "
          f"errors={sorted(res.run['errors'])}")


async def main(dirs, out):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    assert os.environ.get("RR_DICTATED_GATE") in ("shadow", "live"), "run with RR_DICTATED_GATE=shadow or live"
    with open(out, "w") as fh:
        for d in dirs:
            for p in sorted(Path(d).glob("*.json")):
                if p.stem in ("cases", "ids"):
                    continue
                await one(p, fh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dumps", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    asyncio.run(main(a.dumps, a.out))
```

- [ ] **Step 2: Smoke-run it on one dump directory**

Run (the dump dirs live in the session scratchpad; ask the controller for the path):
`cd backend && PYTHONPATH=src RR_DICTATED_GATE=shadow .venv/bin/python scripts/review_labs/dictated_gate_replay.py --dumps <SP>/live_audit/r4 --out <SP>/labs/gate_a/replay/r4.jsonl`
Expected: 5 lines like `r4-N1: {'synth': 2, 'quiet': 9, 'dictated': 3, 'rec': 1} plain_today=… ms=…`, no `dictated_gate` in the errors. If `input_from_parts` returns None because `cr` lacks `content`, set `cr = {"content": rep["report_content"]}`. The field name comes from `GenerationArtifacts.from_candidate`, so read it.

- [ ] **Step 3: Commit** (the script only; never the output)

```bash
git add backend/scripts/review_labs/dictated_gate_replay.py
git commit -m "chore(review-labs): dictated gate shadow replay over local report dumps"
```

---

### Task 9: Ledger entry

**Files:**
- Modify: `docs/model-migration/parameter-ledger.md`

- [ ] **Step 1: Find the next free ID**

Run: `grep -o "L-[0-9]*" docs/model-migration/parameter-ledger.md | sort -t- -k2 -n | tail -1`
Use the next number, unless the PR #12–#15 backfill (L-60 onwards) is still unwritten. In that case take the first number after the range those four entries need, and say so in the entry.

- [ ] **Step 2: Append the entry** (same table/section format as the L-59 entry; read it first)

The content, adapted to the format:
- **Change:** a dictated gate, one Jev choice (Q3s, frozen wording in `review_engine/dictated_gate.py`) per Jev-pass clause against the raw dictation, plus the tier rule (spec §4.2).
- **Parameter:** `GATE_MIN = 0.7`; `CHUNK = 4`; flag `RR_DICTATED_GATE` off/shadow/live.
- **Evidence:** labs `gate_a`, `confirm`, `confirm2`, `sorter`, `amber`, `amber_fix` (scratchpad, 2026-10-10).
  - Over 24 reports, AI text left plain falls from 54 (live) to 3–4, with 6/75 dictated clauses tinted.
  - Review recall is 64–65/70, at precision 0.97, with ~2.75 highlights per report.
  - Rejected: the lexical-diff backstop and the tighter amber prompt.
- **Status:** shadow pending.

- [ ] **Step 3: Commit**

```bash
git add docs/model-migration/parameter-ledger.md
git commit -m "docs(ledger): dictated gate GATE_MIN 0.7 and tier rule"
```

---

### Task 10: PR, deploy in shadow, shadow check, then live (controller, with Hassan)

This task is run by the controller session, not an implementer subagent. Each external action needs Hassan's go-ahead in the conversation.

- [ ] **Step 1:** Run the full backend and frontend suites once more, then push the branch and open a PR. The body ends with the 🤖 line and the session link.
- [ ] **Step 2:** After Hassan approves the merge, merge and confirm the Railway deploy:
  - `curl -s -o /dev/null -w "%{http_code}" -A 'Mozilla/5.0' <root>` returns 200;
  - `POST /api/dictation/check` returns 401.
- [ ] **Step 3:** With Hassan's approval, set `RR_DICTATED_GATE=live` on Railway (new tiers shown; today's path logged as `today`).
- [ ] **Step 4:** Replay the 24 lab reports (scratchpad `live_audit/r2…r5`) with Task 8's script (`RR_DICTATED_GATE=live` locally works too: the log carries both).
  - Score against the scratchpad gold (`labs/gate_a/*/gold.jsonl`, sorter relabel) on spec §9:
    - review recall ≥ 90%; precision ≥ 0.9;
    - mean ≤ 4 review highlights per report; highlighted words ≤ 20% of text;
    - dictated clauses in the review tier ≤ 1 per 10 reports;
    - p50 review time up by ≤ 1 s.
  - Generate 5 fresh prod reports through the Chrome session and hand-read their `dictated_gate` shadow logs.
  - Confirm 0 changes to removals and contradiction cards against the same reports with the gate off.
- [ ] **Step 5:** Report the numbers to Hassan with the editor view of the fresh cases. If a criterion fails, set the flag back to `shadow` (log only) with his approval while it is fixed.
- [ ] **Step 6:** Update the handover memory and ledger status.
  - Cleanup is a later PR: deleting the replaced provenance code, and the stage-3 one-line failure notice. It needs ≥ 10 hand-read live reports first.
