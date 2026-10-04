# Review engine, Slice A (backend): implementation plan (Plan 2 of the review engine)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the review engine backend (alignment, code checks, item contract and storage, the three lanes wired to today's detectors, the adjudicator, the verifier, orchestration and endpoints) and run it in **shadow mode** behind `RR_REVIEW_ENGINE`. The report path stays untouched.

**Architecture:** This is a new package, `rapid_reports_ai/review_engine/`.
- **Code** aligns report clauses with dictated lines and runs deterministic checks.
- **One shared Jev pass** asks today's batched questions (contradiction, selector, classify-first). Coverage and Accuracy read it; Additions turns brief options (and S4 cards, when stored) into candidates behind a Jev "already in report" gate.
- Candidates **merge** by overlapping anchor or shared dictated line.
- **One flat Qwen call per group** judges and writes the fix.
- **Code guards plus one Jev batch** verify the fix.
- Items are **stored** in two new tables.

A background task (the held-set pattern from `template_pipeline.schedule_options`) runs the engine after the candidate is saved. It writes rows with `mode=shadow` and never touches the client.

**Tech Stack:** FastAPI, SQLAlchemy and Alembic (dialect-safe), pydantic v2, pytest with `asyncio_mode=auto`. Jev goes through `report_reconcile._jev`, and Qwen through `enhancement_utils._run_agent_with_model` (Cerebras `qwen-3.8-27b`, reasoning on).

**Spec:** `docs/superpowers/specs/2026-10-02-review-engine-and-rail-design.md` §4–§10 and §14 step 1. §15 was confirmed on 2026-10-03.
**Companion:** Plan 1, `docs/superpowers/plans/2026-10-03-review-engine-gate-labs.md`. Its B1c step needs Tasks 2–3 of this plan, and Task 8 here takes the adjudicator prompt Gate A settles.

---

## Conventions for every task

- Run everything from `backend/`. The tests run with `.venv/bin/python -m pytest <file> -q`.
- **Commit helper.** Define it once per shell. Every commit in this plan uses it, and it writes the two attribution trailers:
  ```bash
  rcommit() { git commit -q -F - <<EOF
  $1

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018p787D9fYjGvCu5x35pwJR
  EOF
  }
  ```
- **No live model calls in unit tests.** Each engine test module monkeypatches `rapid_reports_ai.report_reconcile._jev` and `rapid_reports_ai.review_engine.adjudicator._run_agent_with_model`. The autouse fixture `_no_live_models` (Task 6) fails any test that forgets to.
- Thresholds that a gate will set are **named module constants with a `# provisional: Gate X` comment**. Code never hard-codes them inline.
- Prompts are case-agnostic, with structural examples only.
- **Nothing in this plan changes what the user sees.** `RR_REVIEW_ENGINE` defaults to `off`. Shadow mode only writes rows.

## Binding corrections from Plan 1's wave 0 review (2026-10-03)

The lab copy of the adjudicator and verifier (`scripts/review_labs/judgement.py`, commits e6c6b9a and 17e2b46) was reviewed and fixed before any lab run. Tasks 8 and 9 below were drafted before that review and repeat its bugs. **Where Tasks 8–9 conflict with this section, this section wins.** The implementer ports the lab's tested functions and their tests, `tests/test_review_labs_judgement.py`, adapting only types (`Edit`/`ReviewItem` in place of the lab `Judgement`).

1. **No pydantic-ai output retries for the adjudicator.** `_run_agent_with_model` builds `Agent(..., retries=2)`, so a validation failure costs up to 3 calls (spec §7: retries at T=0 are futile).
   - Task 8 adds a keyword `retries: int = 2` to `enhancement_utils._run_agent_with_model`. The default is unchanged, so no existing caller moves. The adjudicator passes `retries=0`.
   - Test: the adjudicator's call kwargs include `retries=0`, and `_run_agent_with_model` forwards it to `Agent`.
2. **`apply_edit`:**
   - **Remove** splices at the index and tidies only the seam: collapse a double space at the seam, drop a line the removal emptied, strip a leading space at line start or a trailing space before a newline. Never run a whole-report `re.sub`; the draft's Task 9 `re.sub(r"[ \t]{2,}", ...)` is wrong.
   - **Insert** strips the anchor and returns `None` when the anchor ends mid-word. After a heading anchor, the new text goes on the next line. Otherwise it goes after the anchor with exactly one space.
3. **Verifier failure rules:**
   - `addressed` < 0.5 → `code False`, `failed += "not_addressed"`.
   - A Jev exception → `code False`, `failed += "jev_error"`.
   - An edit with no probe → `unconfirmed True`.
   - 0.5 ≤ `addressed` < 0.8 → kept, `unconfirmed True`.
4. **The contradiction check runs on the changed sentence located by position,** with `changed_sentence(report, after, edit)`. It is skipped for `remove` (there is nothing to contradict).
5. **Guards:**
   - `outside_section`: compares `edit.section` with the heading at the edit position, case-insensitively; skipped when the report has no headings.
   - `duplicate`: `_restates` against the target paragraph's sentences. For an insert, every sentence. For a replace or upgrade, the *other* sentences only.
   - Number and side grounding: `bilateral` counts as grounded when the source says "both" or names both sides.
   - **For the additions lane, grounding also accepts the candidate's evidence values** (threshold, timing, grade, criteria, parameter, system, text). Otherwise every guideline-derived number fails.
   - `drops_negation`: also fires when the 2 content words after a negator in `find` reappear in `replace` with no negator before them.
   - The `kind == "contradicted"` exemption from `drops_negation` (draft Task 9) stays.
6. **The candidate render names the kind explicitly:** `Flag kind "partial" (from the coverage check, detector …)`. The prompt says to copy the quoted kind, never a check name. With the bracketed `[coverage/partial]` form, Qwen returned the lane as `kind` in the Gate A smoke.
7. **The `Q_CONVEYS` "conveys" veto must not be imported into the adjudicator or verifier** (spec §7 removed it). `Q_CONVEYS` remains correct for the Additions "already in report" gate (Task 7).
8. **The fallback `Judgement` on failure** carries every field (`reason=""`, all `edit_*` None) plus `error_kind` (`validation` / `transport`) in the run's `errors` log.
9. **Contract additions (Task 1 review, 2026-10-04; already in `items.py`):**
   - `ReviewItem.evidence: Optional[dict]` holds `check_reason` and `pointer` for Task 14. **Task 4's migration adds an `evidence` JSON column** to `report_review_items`, and Task 5's store round-trips it.
   - `Candidate.pre_apply: bool`. **`build_item` (Task 10) maps `pre_apply=True` to `status="pre_applied"`.** Spec §9, decided 2026-10-04:
     - auto-insert verified `absent` coverage items;
     - auto-remove contradicted *generated* negatives;
     - auto-correct a positive contradiction only when the fix restores dictated wording verbatim and is verified.
     
     Nothing the radiologist dictated is ever pre-applied as a removal.
   - **Keys use the candidate's ORIGINAL kind,** never the adjudicator's refined kind, so they stay stable across runs. Task 10's `build_item` passes `first.kind` to `item_key`. When an item has neither anchor nor line text, key on `first.kind` plus the candidate evidence, never on the LLM-written label.
11. **Accuracy-lane Jev questions (ledger L-53, L-55; 2026-10-04).** Task 6's shared Jev pass asks every positive (non-negative) report clause, in the dictation-plus-history state, two noul questions:
    - **W1n** "The dictated findings report this finding, including as a possibility, in any wording. Report statement: "{c}"". If it is < 0.5, raise `unsupported`, detector `jev.supported`.
    - **C1n** "Read only this one report statement: "{c}". It states a finding as more certain or more severe than the dictated findings do, for example a possibility stated as a fact, or a milder grade stated as a worse one." If it is ≥ 0.5, raise `overstated`, detector `jev.certainty`.

    The unsure band 0.4–0.6 on either question goes to the adjudicator, with `evidence.jev_unsure` naming the question. The thresholds are named constants marked `# provisional: Gate F`. Task 3's code `overstated` detector is removed: code owns numbers, dates, priors, modality and size words only.
10. **Task 14 items bypass the adjudicator.** The negatives classifier is the one reasoning call that owns that judgement, so its `ReviewItem`s are built directly. They are not merged with coverage candidates, so a negative's `pre_applied` removal can't be swallowed by a group adjudication.

## File structure

| File | Responsibility |
|---|---|
| `src/rapid_reports_ai/review_engine/__init__.py` | package marker |
| `review_engine/items.py` | `Span`, `Edit`, `ReviewInput`, `Candidate`, `ReviewItem`, `item_key`, `text_hash`, `merge` |
| `review_engine/alignment.py` | `DictLine`, `ReportClause`, `Pair`, `Alignment`, `align()`, `section_models()`, `side_of`, `level_of`, `numbers`, `words` |
| `review_engine/checks.py` | `hedge_tag`, `modality`, `run_checks()` (unsupported numbers/dates/priors, overstated, misattributed, inconsistent, laterality) |
| `review_engine/store.py` | runs, items and events persistence (sync, takes a `Session`) |
| `review_engine/jev_pass.py` | the one shared batched Jev pass (today's `check()` questions, raw answers kept) |
| `review_engine/lanes/__init__.py` | `Lane`, `LaneContext`, lane registry |
| `review_engine/lanes/coverage.py` | classify-first per selected line → `absent` / `partial` / `differs`; unsure → `coverage_check`; laterality from checks |
| `review_engine/lanes/accuracy.py` | Jev contradictions (negative: code removal edit; positive: adjudicator); unsure band; code checks |
| `review_engine/lanes/additions.py` | brief options (pre-classed `minor`), the upgrade case, S4 mapping, `in_report_gate` |
| `review_engine/adjudicator.py` | flat `Judgement`, prompt, one call per group, cap 8 concurrent / 20 groups, `reprepare` |
| `review_engine/prompts/adjudicator.txt` | the adjudicator prompt (Gate A's settled text) |
| `review_engine/verifier.py` | `apply_edit`, code guards, one Jev batch per verification, `probe()` for the live loop |
| `review_engine/engine.py` | flags, `run_review`, `build_item`, Gate D shadow log, `load_input`, `schedule_review` |
| `review_engine/api.py` | `/api/reports/{id}/review…` endpoints (an `APIRouter` mounted in `main.py`) |
| `src/rapid_reports_ai/database/models.py` | `ReportReviewRun`, `ReportReviewItem`, `ReportChatMessage`, `Report.workspace_state` (deferred) |
| `migrations/versions/20261003120000_add_review_engine_tables.py` | the Alembic migration |
| `src/rapid_reports_ai/report_review.py` | one addition: `tel["pre_edit_report"]` when the engine is not `off` (Gate D shadow log) |
| `src/rapid_reports_ai/quick_report_api.py`, `src/rapid_reports_ai/main.py` | `schedule_review(report_id)` after the candidate is saved; mount the router |
| `src/rapid_reports_ai/scripts/review_engine_eval.py` | live evaluation harness and shadow-read page |
| `tests/test_review_engine_*.py` | one test module per unit; `tests/conftest.py` gains the new tables and `test_review_engine_shadow` in `_QUALITY_MODULES` |

**Why an `APIRouter` and not inline `@app` endpoints:** `main.py` is about 5,900 lines. The quick and admin endpoints already live in their own routers, mounted with `app.include_router`. The endpoints here follow that pattern and keep the same owner scoping (`get_current_user` + `get_report(db, id, user_id=…)`).

## Execution and parallelism

Each task is one subagent. That subagent writes the failing test, implements, runs its own module's tests plus `tests/test_report_review.py`, and commits. After each wave a reviewer subagent reads the wave's diffs against this plan and the spec, the full suite runs, and only then does the next wave start.

| Wave | Tasks (parallel within a wave) | Needs |
|---|---|---|
| 1 | **1** items | — |
| 2 | **2** alignment · **4** migration + models · **8** adjudicator | 1 |
| 3 | **3** checks · **5** store · **9** verifier | 2 (for 3, 9) · 4 (for 5) |
| 4 | **6** lanes + Jev pass | 1, 2, 3 |
| 5 | **7** "already in report" gate | 6 |
| 6 | **10** engine | 5–9 |
| 7 | **11** shadow wiring · **12** endpoints | 10 |
| 8 | **13** eval harness, shadow read, production checklist | 11, 12 |

- Tasks 2 and 3 unblock Plan 1's Gate B1c.
- Task 8 starts with the lab prompt. Its last step swaps in Gate A's revised text verbatim whenever Gate A lands, and nothing downstream depends on the wording.
- Subagents in one wave touch disjoint files. The only shared files are `tests/conftest.py` (Task 4; Task 10 touches it later) and `main.py` (Tasks 11 and 12 edit different regions). Wave 7 subagents must rebase on each other before committing.

---

### Task 1: `items.py`, the item contract and merge

**Files:**
- Create: `src/rapid_reports_ai/review_engine/__init__.py` (empty)
- Create: `src/rapid_reports_ai/review_engine/items.py`
- Test: `tests/test_review_engine_items.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_items.py
"""Review engine item contract and merge (spec §6.1, §7, §10.1)."""
from rapid_reports_ai.generation_artifacts import GenerationArtifacts
from rapid_reports_ai.review_engine.items import (Candidate, Edit, ReviewInput, ReviewItem, Span, item_key, merge,
                                                  text_hash)


def C(kind="partial", lane="coverage", anchor=None, line_id=None, detector="d"):
    span = Span(start=anchor[0], end=anchor[1], text="x") if anchor else None
    return Candidate(lane=lane, kind=kind, anchor=span, line_id=line_id, detector=detector)


def test_item_key_is_stable_and_normalised():
    assert item_key("coverage", "partial", "A  cyst.") == item_key("coverage", "partial", "a cyst.")
    assert item_key("coverage", "partial", "a cyst") != item_key("accuracy", "partial", "a cyst")
    assert len(item_key("a", "b", "c")) == 16


def test_text_hash():
    assert text_hash("abc") == text_hash("abc") and len(text_hash("abc")) == 16 and text_hash("abc") != text_hash("abd")


def test_merge_by_overlapping_anchor_and_shared_line():
    a = C(anchor=(0, 10))
    b = C(anchor=(5, 15), lane="accuracy", kind="unsupported", detector="code.numbers")
    c = C(line_id="d3")
    d = C(line_id="d3", kind="laterality", detector="code.laterality")
    e = C(anchor=(20, 30))
    groups = merge([a, b, c, d, e])
    assert [len(g) for g in groups] == [2, 2, 1]
    assert groups[0][0] is a and groups[1][0] is c and groups[2][0] is e


def test_merge_is_transitive():
    a, b, c = C(anchor=(0, 5)), C(anchor=(4, 9), line_id="d1"), C(line_id="d1")
    assert len(merge([a, b, c])) == 1


def test_touching_spans_do_not_merge():
    assert len(merge([C(anchor=(0, 5)), C(anchor=(5, 9))])) == 2


def test_review_item_defaults():
    it = ReviewItem(key="k", report_id="r", run_id="u", lane="coverage", kind="partial", cls="minor")
    assert it.status == "open" and it.history == [] and len(it.id) == 36 and it.edit is None


def test_edit_insert_without_anchor_means_append():
    e = Edit(mode="insert", replace="x", section="IMPRESSION")
    assert e.after is None


def test_review_input_shape():
    art = GenerationArtifacts(report="R", dictated_findings="D", sections=["FINDINGS"], options=[])
    inp = ReviewInput(report_id="r1", pathway="quick", artifacts=art, clinical_history="", scan_type="CT")
    assert inp.synthesis is None and inp.pre_edit_report is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_items.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.review_engine'`.

- [ ] **Step 3: Write `items.py`**

```python
# src/rapid_reports_ai/review_engine/items.py
"""Review engine item contract (spec §5.1, §6.1, §10.1) and the merge step (spec §7)."""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..generation_artifacts import GenerationArtifacts

LaneName = Literal["coverage", "accuracy", "additions"]
ItemLane = Literal["coverage", "accuracy", "additions", "chat"]
Cls = Literal["action", "minor", "info", "suppress"]
Status = Literal["open", "pre_applied", "applied", "dismissed", "addressed", "stale"]


class Span(BaseModel):
    start: int
    end: int
    text: str
    text_hash: Optional[str] = None      # hash of the report the span was made on


class Edit(BaseModel):
    mode: Literal["replace", "insert", "upgrade", "remove"]
    find: Optional[str] = None           # verbatim, occurs once (replace / upgrade / remove)
    replace: Optional[str] = None
    after: Optional[str] = None          # insert: verbatim anchor sentence; None = append to the end of `section`
    section: Optional[str] = None


class ReviewInput(BaseModel):
    report_id: str
    pathway: Literal["quick", "templated"]
    artifacts: GenerationArtifacts       # report, dictated_findings, sections, options, brief, quality_check
    clinical_history: str = ""
    scan_type: str = ""
    study_title: Optional[str] = None    # bounds laterality
    synthesis: Optional[dict] = None     # {"guidelines": [S4 cards]} when stored
    pre_edit_report: Optional[str] = None  # the report before today's automatic edits (Gate D shadow log)


class Candidate(BaseModel):
    lane: LaneName
    kind: str
    section: Optional[str] = None
    anchor: Optional[Span] = None
    line_id: Optional[str] = None        # dictated line id ("d3"), for coverage items
    line_text: Optional[str] = None
    evidence: dict = Field(default_factory=dict)
    proposed: Optional[Edit] = None      # only producers that already write (brief options, code removal)
    preclassed: Optional[Literal["minor"]] = None
    code_fix: bool = False               # the proposed edit is code's (a contradicted negative): Qwen never rewrites it
    probe: Optional[str] = None          # producers that know their probe (brief options: "already in report")
    citation: Optional[dict] = None
    detector: str                        # e.g. "jev.classify_first", "code.numbers"


class ReviewItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    report_id: str
    run_id: str
    lane: ItemLane
    detectors: List[str] = Field(default_factory=list)
    kind: str
    cls: Cls
    section: Optional[str] = None
    anchor: Optional[Span] = None
    label: str = ""
    reason: str = ""
    edit: Optional[Edit] = None
    verified: Optional[dict] = None
    probe: Optional[str] = None
    citation: Optional[dict] = None
    source_line: Optional[str] = None
    status: Status = "open"
    history: List[dict] = Field(default_factory=list)
    engine_version: str = ""


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def item_key(lane: str, kind: str, text: Optional[str]) -> str:
    """Stable across runs: the same lane, kind and anchor (or dictated line) text give the same key."""
    return hashlib.sha1(f"{lane}|{kind}|{_norm(text)}".encode()).hexdigest()[:16]


def _overlap(a: Optional[Span], b: Optional[Span]) -> bool:
    return a is not None and b is not None and a.start < b.end and b.start < a.end


def merge(cands: List[Candidate]) -> List[List[Candidate]]:
    """Group candidates whose anchors overlap or that share a dictated line (transitively). Groups keep
    first-seen order, and members keep input order."""
    parent = list(range(len(cands)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, b = cands[i], cands[j]
            if _overlap(a.anchor, b.anchor) or (a.line_id is not None and a.line_id == b.line_id):
                ri, rj = root(i), root(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
    groups: Dict[int, List[Candidate]] = {}
    for i, c in enumerate(cands):
        groups.setdefault(root(i), []).append(c)
    return list(groups.values())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_review_engine_items.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/review_engine/__init__.py src/rapid_reports_ai/review_engine/items.py tests/test_review_engine_items.py
rcommit "feat(review-engine): item contract (Span, Edit, Candidate, ReviewItem, ReviewInput) and merge"
```

---

### Task 2: `alignment.py`, report clauses ↔ dictated lines (pure code)

**Files:**
- Create: `src/rapid_reports_ai/review_engine/alignment.py`
- Test: `tests/test_review_engine_alignment.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_alignment.py
"""Alignment (spec §5.2): pure code, ambiguity kept."""
from rapid_reports_ai.review_engine.alignment import align, level_of, numbers, section_models, side_of

REPORT = ("FINDINGS:\nThe liver is normal. A 14 mm cyst is present in the left kidney. No free fluid.\n"
          "Right leg:\nNo deep vein thrombosis.\n\nIMPRESSION:\nLeft renal cyst.")
DICT = "- Liver normal\n- 14 mm left renal cyst\n- No DVT right leg\n- Spleen enlarged 15 cm"


def test_helpers():
    assert side_of("left and right kidneys") == "bilateral" and side_of("Left kidney") == "left" and side_of("x") is None
    assert level_of("Disc bulge at l4/5.") == "L4/5" and level_of("segment 7 lesion") == "SEGMENT 7"
    assert numbers("A 1.4 cm lesion and 12 mm node, 5x4 mm, at L4") == {"14mm", "12mm", "5", "4mm"}
    assert [s.role for s in section_models(["FINDINGS", "IMPRESSION", "TECHNIQUE", "Clinical history"])] == \
        ["findings", "impression", "technique", "history"]


def test_lines_and_clauses_with_offsets():
    al = align(REPORT, DICT, "", ["FINDINGS", "IMPRESSION"])
    assert [l.text for l in al.lines][:2] == ["Liver normal", "14 mm left renal cyst"]
    assert al.lines[1].side == "left" and al.lines[2].negative
    c = next(c for c in al.clauses if "14 mm" in c.text)
    assert c.section == "FINDINGS" and REPORT[c.start:c.end] == c.text


def test_pairs_many_to_many_and_unmatched():
    al = align(REPORT, DICT, "", ["FINDINGS", "IMPRESSION"])
    paired = [al.clause(p.clause_id).text for p in al.pairs if p.line_id == "d1"]
    assert any("14 mm" in t for t in paired) and any(t.startswith("Left renal cyst") for t in paired)
    assert "d3" in al.unmatched_lines
    assert all(0 < p.score <= 1 for p in al.pairs)


def test_subheading_side():
    al = align("FINDINGS:\nLeft side:\nThe kidney is normal. A 14 mm renal cyst.\n", "- 14 mm renal cyst", "", ["FINDINGS"])
    c = next(c for c in al.clauses if c.text.startswith("A 14 mm"))
    assert c.side is None and c.subheading_side == "left"


def test_level_mismatch_never_pairs():
    al = align("FINDINGS:\nDisc bulge at L4/5. Normal disc at L3/4.\n", "- Disc bulge L3/4", "", ["FINDINGS"])
    assert all(al.clause(p.clause_id).level != "L4/5" for p in al.pairs if p.line_id == "d0")


def test_history_lines_are_a_second_source_not_targets():
    al = align(REPORT, DICT, "Known left renal cyst", ["FINDINGS", "IMPRESSION"])
    assert al.history and al.history[0].id == "h0" and al.history[0].background
    assert all(p.line_id.startswith("d") for p in al.pairs)


def test_background_flag_by_index():
    al = align(REPORT, DICT, "", ["FINDINGS", "IMPRESSION"], background={0})
    assert al.lines[0].background and not al.lines[1].background


def test_no_sections_falls_back_to_whole_report():
    al = align("A 5 mm nodule.", "- 5 mm nodule", "", [])
    assert al.clauses and al.pairs
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_alignment.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `alignment.py`**

```python
# src/rapid_reports_ai/review_engine/alignment.py
"""Alignment: report clauses ↔ dictated lines (spec §5.2). Pure code. Ambiguity is kept: every pair above
the floor is returned, and Jev is never asked to choose between overlapping spans."""
from __future__ import annotations

import re
from typing import List, Literal, Optional, Set, Tuple

from pydantic import BaseModel

from .. import report_reconcile as rc
from ..report_review import ReportSection, _sentence_positions, clauses_in_context, dictated_items, section_spans

PAIR_FLOOR = 0.34   # provisional: Gate B1 (≥ 95% of clauses correctly paired or correctly unmatched)

Side = Literal["left", "right", "bilateral"]


class DictLine(BaseModel):
    id: str
    text: str
    side: Optional[Side] = None
    level: Optional[str] = None
    negative: bool = False
    background: bool = False             # the omission selector says not reportable (L-49), or a history line


class ReportClause(BaseModel):
    id: str
    text: str
    section: str
    start: int                           # offsets of the clause's sentence in the report
    end: int
    side: Optional[Side] = None
    level: Optional[str] = None
    negative: bool = False
    subheading_side: Optional[Side] = None


class Pair(BaseModel):
    line_id: str
    clause_id: str
    score: float
    how: Literal["exact", "lexical", "number", "anatomy"]


class Alignment(BaseModel):
    lines: List[DictLine]
    clauses: List[ReportClause]
    pairs: List[Pair]
    unmatched_lines: List[str]
    unmatched_clauses: List[str]
    history: List[DictLine] = []         # clinical history: a second source for Accuracy, never a coverage target

    def clause(self, cid: str) -> ReportClause:
        return next(c for c in self.clauses if c.id == cid)

    def line(self, lid: str) -> DictLine:
        return next(l for l in self.lines if l.id == lid)

    def paired_clauses(self, line_id: str) -> List[ReportClause]:
        ids = [p.clause_id for p in sorted(self.pairs, key=lambda p: -p.score) if p.line_id == line_id]
        return [self.clause(i) for i in ids]

    def paired_lines(self, clause_id: str) -> List[DictLine]:
        ids = [p.line_id for p in sorted(self.pairs, key=lambda p: -p.score) if p.clause_id == clause_id]
        return [self.line(i) for i in ids]


# ── small text helpers (shared with checks.py) ──────────────────────────────

_ROLE_WORDS = (("impression", "impression"), ("conclusion", "impression"), ("summary", "impression"),
               ("comment", "impression"), ("opinion", "impression"), ("history", "history"),
               ("indication", "history"), ("technique", "technique"), ("protocol", "technique"),
               ("comparison", "comparison"))
_SKIP_ROLES = {"history", "technique", "comparison"}


def section_models(sections: List[str]) -> List[ReportSection]:
    """Generic headings → ReportSection with a role guessed from the heading's words."""
    out = []
    for h in sections:
        low = h.lower()
        role = next((r for w, r in _ROLE_WORDS if w in low), "findings")
        out.append(ReportSection(name=h, header=h, role=role))
    return out


_SIDE_RE = re.compile(r"\b(left|right|bilateral(?:ly)?|both)\b", re.I)


def side_of(text: Optional[str]) -> Optional[Side]:
    found = {m.lower() for m in _SIDE_RE.findall(text or "")}
    if not found:
        return None
    if found & {"bilateral", "bilaterally", "both"} or {"left", "right"} <= found:
        return "bilateral"
    return "left" if "left" in found else "right"


_LEVEL_RE = re.compile(r"\b([CTLS]\d{1,2}(?:\s*[/-]\s*[CTLS]?\d{1,2})?|segment\s+(?:[1-8]|[ivx]{1,4})[ab]?"
                       r"|(?:upper|middle|lower)\s+lobe)\b", re.I)


def level_of(text: Optional[str]) -> Optional[str]:
    m = _LEVEL_RE.search(text or "")
    return re.sub(r"\s+", " ", m.group(1)).upper() if m else None


_NUM_RE = re.compile(r"(?<![A-WYZa-wyz\d.])(\d+(?:\.\d+)?)\s*(mm|cm|ml|hu|%)?(?![A-WYZa-wyz])", re.I)   # "x" allowed: 5x4 mm


def numbers(text: Optional[str]) -> Set[str]:
    """Numbers with their unit, cm normalised to mm ("1.4 cm" → "14mm"); vertebral-level digits are skipped."""
    out = set()
    for val, unit in _NUM_RE.findall(text or ""):
        v, u = float(val), (unit or "").lower()
        if u == "cm":
            v, u = v * 10, "mm"
        out.add(f"{round(v, 3):g}{u}")
    return out


_STOP = {"the", "and", "with", "are", "is", "of", "in", "at", "to", "an", "or", "seen", "noted", "there", "this",
         "that", "which", "also", "present", "identified", "demonstrated", "measures", "measuring", "measure",
         "appears", "appear", "within", "from", "for", "has", "have", "been", "was", "were", "its", "into", "on",
         "by", "as", "be", "no", "not", "any"}
ANATOMY = frozenset({
    "brain", "skull", "orbit", "sinus", "sinuses", "neck", "thyroid", "larynx", "pharynx", "trachea", "lung", "lungs",
    "lobe", "pleura", "pleural", "mediastinum", "mediastinal", "heart", "pericardium", "pericardial", "aorta",
    "aortic", "artery", "arteries", "vein", "veins", "liver", "hepatic", "gallbladder", "biliary", "bile", "duct",
    "cbd", "pancreas", "pancreatic", "spleen", "splenic", "kidney", "kidneys", "renal", "adrenal", "ureter",
    "bladder", "prostate", "uterus", "ovary", "ovaries", "bowel", "colon", "rectum", "stomach", "duodenum",
    "appendix", "peritoneum", "peritoneal", "lymph", "nodes", "node", "spine", "vertebra", "vertebral", "disc",
    "cord", "canal", "foramen", "rib", "ribs", "pelvis", "hip", "femur", "knee", "ankle", "foot", "shoulder",
    "elbow", "wrist", "hand", "carpal", "joint", "tendon", "ligament", "muscle", "bone", "breast", "axilla",
    "testis", "scrotum", "soft", "tissue", "tissues", "leg", "arm",
})


def words(text: Optional[str]) -> Set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP}


def score_pair(line: str, clause: str) -> Tuple[float, str]:
    a, b = line.lower().strip(" ."), clause.lower().strip(" .")
    if a == b:
        return 1.0, "exact"
    wa, wb = words(line), words(clause)
    lex = len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0
    num = bool(numbers(line) & numbers(clause))
    anat = bool(wa & wb & ANATOMY)
    score = min(1.0, lex + (0.3 if num else 0.0) + (0.2 if anat else 0.0))
    how = "lexical" if lex >= PAIR_FLOOR else ("number" if num else ("anatomy" if anat else "lexical"))
    return round(score, 3), how


# ── clauses and lines ────────────────────────────────────────────────────────

_NEG_LINE = re.compile(r"^\s*(no|nil|without|there is no|there are no)\b", re.I)
_SUBHEAD = re.compile(r"^[ \t]*(left|right)\b[^:\n]{0,40}:", re.I | re.M)


def report_clauses(report: str, sections: List[str]) -> List[ReportClause]:
    spans = section_spans(report, section_models(sections)) if sections else []
    if not spans:
        spans = [(ReportSection(name="Report", role="findings"), 0, len(report))]
    out: List[ReportClause] = []
    for sec, a, b in spans:
        if sec.role in _SKIP_ROLES:
            continue
        subs = [(m.start(), side_of(m.group(1))) for m in _SUBHEAD.finditer(report, a, b)]
        for s, i, j in _sentence_positions(report, a, b):
            sub = next((sd for p, sd in reversed(subs) if p <= i), None)
            for c, _ in clauses_in_context(s):
                out.append(ReportClause(id=f"r{len(out)}", text=c, section=sec.name, start=i, end=j, side=side_of(c),
                                        level=level_of(c), negative=bool(_NEG_LINE.match(c)), subheading_side=sub))
    return out


def _lines(texts: List[str], prefix: str, background: Set[int], all_background: bool = False) -> List[DictLine]:
    return [DictLine(id=f"{prefix}{i}", text=t, side=side_of(t), level=level_of(t), negative=bool(_NEG_LINE.match(t)),
                     background=all_background or i in background) for i, t in enumerate(texts)]


def align(report: str, dictation: str, history: str, sections: List[str],
          background: Optional[Set[int]] = None) -> Alignment:
    lines = _lines(dictated_items(dictation), "d", background or set())
    hist = _lines(rc.split_findings(history or ""), "h", set(), all_background=True)
    clauses = report_clauses(report, sections)
    pairs: List[Pair] = []
    for l in lines:
        for c in clauses:
            if l.level and c.level and l.level != c.level:
                continue                     # a different level never pairs
            sc, how = score_pair(l.text, c.text)
            if sc >= PAIR_FLOOR:
                pairs.append(Pair(line_id=l.id, clause_id=c.id, score=sc, how=how))
    pl, pc = {p.line_id for p in pairs}, {p.clause_id for p in pairs}
    return Alignment(lines=lines, clauses=clauses, pairs=pairs, history=hist,
                     unmatched_lines=[l.id for l in lines if l.id not in pl],
                     unmatched_clauses=[c.id for c in clauses if c.id not in pc])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_review_engine_alignment.py -q`
Expected: 8 passed. If `test_pairs_many_to_many_and_unmatched` fails on a score, print `al.pairs` and check `_STOP` / `ANATOMY` before touching `PAIR_FLOOR`. The floor is Gate B1's to set.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/review_engine/alignment.py tests/test_review_engine_alignment.py
rcommit "feat(review-engine): alignment of report clauses to dictated lines (pure code, ambiguity kept)"
```

---

### Task 3: `checks.py`, the Accuracy code checks and laterality

**Files:**
- Create: `src/rapid_reports_ai/review_engine/checks.py`
- Test: `tests/test_review_engine_checks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_checks.py
"""Code checks (spec §6.2 laterality, §6.3 unsupported / overstated / misattributed / inconsistent)."""
import pytest

from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.checks import hedge_tag, modality, run_checks


def run(report, dictation, scan="CT abdomen", history="", title=None):
    al = align(report, dictation, history, ["FINDINGS", "IMPRESSION"])
    return run_checks(report, dictation, history, scan, al, study_title=title)


def kinds(cs):
    return sorted((c.kind, c.detector) for c in cs)


def test_unsupported_number():
    cs = [c for c in run("FINDINGS:\nThe CBD measures 6 mm.\nIMPRESSION:\nNormal.", "- CBD not dilated")
          if c.kind == "unsupported"]
    assert cs and cs[0].detector == "code.numbers" and cs[0].evidence["numbers"] == ["6mm"]
    assert cs[0].lane == "accuracy" and cs[0].anchor.text == "The CBD measures 6 mm."


def test_number_from_history_or_other_unit_is_supported():
    assert not run("FINDINGS:\nThe CBD measures 6 mm.\n", "- CBD", history="Known 6 mm CBD")
    assert not [c for c in run("FINDINGS:\nA 1.4 cm renal cyst.\n", "- 14 mm renal cyst") if c.kind == "unsupported"]


def test_unsupported_prior_and_date():
    cs = run("FINDINGS:\nThe nodule is stable compared with the prior CT of 03/02/2025.\n", "- Lung nodule")
    assert ("unsupported", "code.prior") in kinds(cs) and ("unsupported", "code.dates") in kinds(cs)


def test_prior_is_fine_when_dictated():
    cs = run("FINDINGS:\nThe nodule is stable compared with the prior CT.\n", "- Lung nodule stable since prior CT")
    assert ("unsupported", "code.prior") not in kinds(cs)


@pytest.mark.parametrize("clause,tag", [
    ("No effusion.", "negated"), ("Appendicitis cannot be excluded.", "possible"), ("Possible small effusion.", "possible"),
    ("Likely a cyst.", "probable"), ("Findings in keeping with cholecystitis.", "probable"), ("Acute appendicitis.", "definite"),
])
def test_hedge_tag(clause, tag):
    assert hedge_tag(clause) == tag


def test_overstated():
    cs = [c for c in run("FINDINGS:\nSmall left pleural effusion.\n", "- Possible small left effusion") if c.kind == "overstated"]
    assert cs and cs[0].evidence == {"dictated": "possible", "report": "definite"} and cs[0].detector == "code.hedge"


def test_misattributed():
    cs = run("FINDINGS:\nThe liver contains a lesion. The spleen measures 12 mm.\n", "- Liver lesion 12 mm\n- Spleen normal")
    mis = [c for c in cs if c.kind == "misattributed"]
    assert mis and mis[0].anchor.text == "The spleen measures 12 mm." and mis[0].evidence["number"] == "12mm"


def test_modality_vocabulary():
    assert modality("CT abdomen pelvis") == "CT" and modality("MRI knee") == "MR" and modality("US thyroid") == "US"
    cs = run("FINDINGS:\nThe lesion shows high T2-weighted signal.\n", "- lesion")
    assert ("inconsistent", "code.modality") in kinds(cs)
    assert ("inconsistent", "code.modality") not in kinds(run("FINDINGS:\nHigh signal lesion.\n", "- high signal lesion"))


def test_size_word():
    assert ("inconsistent", "code.size_word") in kinds(run("FINDINGS:\nA small 45 mm mass.\n", "- 45 mm mass"))
    assert ("inconsistent", "code.size_word") in kinds(run("FINDINGS:\nA large 4 mm nodule.\n", "- 4 mm nodule"))
    assert ("inconsistent", "code.size_word") not in kinds(run("FINDINGS:\nA small 4 mm nodule.\n", "- 4 mm nodule"))


def test_laterality_unbounded_and_bounded():
    rep, d = "FINDINGS:\nA 14 mm renal cyst.\n", "- Left renal cyst 14 mm"
    lat = [c for c in run(rep, d) if c.kind == "laterality"]
    assert lat and lat[0].lane == "coverage" and lat[0].line_id == "d0" and lat[0].evidence == {"side": "left"}
    assert not [c for c in run(rep, d, title="CT Kidney Left") if c.kind == "laterality"]
    rep2 = "FINDINGS:\nLeft side:\nThe kidney is normal. A 14 mm renal cyst.\n"
    assert not [c for c in run(rep2, d) if c.kind == "laterality"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_checks.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `checks.py`**

```python
# src/rapid_reports_ai/review_engine/checks.py
"""Deterministic checks (spec §6.2 laterality, §6.3 accuracy). Every lexicon here is provisional until
Gate B1 measures it on the 41 audit-comparison reports; a missed phrasing is a recall gap, never a false fix,
because every hit still goes to the adjudicator."""
from __future__ import annotations

import re
from typing import List, Literal, Optional

from .alignment import ANATOMY, Alignment, ReportClause, numbers, side_of, words
from .items import Candidate, Span

# ── hedges (provisional: Gate B1) ───────────────────────────────────────────
_NOT_EXCLUDED = re.compile(r"\b(?:can ?not|not) be (?:excluded|ruled out)\b|\bnot excluded\b", re.I)
_NEGATED = re.compile(r"^\s*(?:no|nil|without|there is no|there are no)\b|\b(?:not seen|absent|negative for)\b", re.I)
_POSSIBLE = re.compile(r"\b(?:possible|possibly|may|might|could|query|questionable|equivocal|suspicious for|"
                       r"indeterminate)\b|\?", re.I)
_PROBABLE = re.compile(r"\b(?:likely|probable|probably|suggestive of|suggests|consistent with|in keeping with|"
                       r"compatible with|favou?red|presumed)\b", re.I)
_RANK = {"possible": 1, "probable": 2, "definite": 3}

Hedge = Literal["negated", "possible", "probable", "definite"]


def hedge_tag(clause: str) -> Hedge:
    if _NOT_EXCLUDED.search(clause):
        return "possible"
    if _NEGATED.search(clause):
        return "negated"
    if _POSSIBLE.search(clause):
        return "possible"
    if _PROBABLE.search(clause):
        return "probable"
    return "definite"


# ── dates and priors (provisional: Gate B1) ─────────────────────────────────
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE = re.compile(rf"\b\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{2,4}}\b"
                   rf"|\b{_MONTH}\s+\d{{4}}\b", re.I)
_PRIOR = re.compile(r"\b(?:compared (?:with|to)|comparison|prior|previous(?:ly)?|interval(?:ly)?|since the|unchanged|"
                    r"new since|stable (?:in|since|compared))\b", re.I)
_LIST_MARK = re.compile(r"^\s*\d+[.)]\s+")
_LEVEL_TOKENS = re.compile(r"\b(?:[CTLS]\d{1,2}(?:\s*[/-]\s*[CTLS]?\d{1,2})?|segment\s+\d[ab]?)\b", re.I)

# ── modality vocabulary (provisional: Gate B1, arm 1) ───────────────────────
_VOCAB = {
    "MR": re.compile(r"\b(?:(?i:signal|stir|flair|diffusion restriction|restricted diffusion|gadolinium|susceptibility)"
                     r"|T[12][- ]?weighted|T[12] (?:hyper|hypo)intens\w*|ADC)\b"),
    "CT": re.compile(r"\b(?:attenuation|hounsfield|HU|hyperdense|hypodense|isodense)\b", re.I),
    "US": re.compile(r"\b(?:echogenic\w*|hypoechoic|hyperechoic|anechoic|isoechoic|posterior acoustic)\b", re.I),
}
_SMALL = re.compile(r"\b(?:small|tiny|minute)\b", re.I)
_SUBCM = re.compile(r"\bsubcentimet(?:re|er)\b", re.I)
_LARGE = re.compile(r"\b(?:large|huge|massive|bulky)\b", re.I)
SMALL_MAX_MM = 30.0     # provisional: Gate B1
LARGE_MIN_MM = 10.0     # provisional: Gate B1


def modality(scan: Optional[str]) -> Optional[str]:
    s = scan or ""
    if re.search(r"\bMRI?\b|magnetic", s, re.I):
        return "MR"
    if re.search(r"\bCT\b|computed tom", s, re.I):
        return "CT"
    if re.search(r"\bUS\b|ultrasound|sonograph|doppler", s, re.I):
        return "US"
    if re.search(r"\bX-?ray\b|radiograph|\bXR\b", s, re.I):
        return "XR"
    return None


def _span(report: str, c: ReportClause) -> Span:
    return Span(start=c.start, end=c.end, text=report[c.start:c.end])


def _cand(report: str, c: ReportClause, kind: str, detector: str, evidence: dict, lane: str = "accuracy",
          line_id: Optional[str] = None, line_text: Optional[str] = None) -> Candidate:
    return Candidate(lane=lane, kind=kind, section=c.section, anchor=_span(report, c), line_id=line_id,
                     line_text=line_text, evidence=evidence, detector=detector)


def _max_mm(text: str) -> Optional[float]:
    mm = [float(n[:-2]) for n in numbers(text) if n.endswith("mm")]
    return max(mm) if mm else None


def run_checks(report: str, dictation: str, history: str, scan: str, al: Alignment,
               study_title: Optional[str] = None) -> List[Candidate]:
    source = f"{dictation}\n{history}"
    src_nums = numbers(_LEVEL_TOKENS.sub(" ", _DATE.sub(" ", source)))
    src_dates = {d.lower() for d in _DATE.findall(source)}
    src_prior = bool(_PRIOR.search(source))
    mod = modality(scan)
    out: List[Candidate] = []
    seen = set()

    def add(c: Candidate) -> None:
        key = (c.kind, c.detector, c.anchor.start if c.anchor else None, c.line_id)
        if key not in seen:
            seen.add(key)
            out.append(c)

    for c in al.clauses:
        text = _LIST_MARK.sub("", c.text)
        # unsupported: numbers, dates, prior-study references with no match in dictation or history
        dates = [d for d in _DATE.findall(text) if d.lower() not in src_dates]
        nums = sorted(numbers(_LEVEL_TOKENS.sub(" ", _DATE.sub(" ", text))) - src_nums)
        if nums:
            add(_cand(report, c, "unsupported", "code.numbers", {"numbers": nums}))
        if dates:
            add(_cand(report, c, "unsupported", "code.dates", {"dates": dates}))
        if _PRIOR.search(text) and not src_prior:
            add(_cand(report, c, "unsupported", "code.prior", {"phrase": _PRIOR.search(text).group(0)}))
        # overstated: report certainty above every paired dictated line's
        tag = hedge_tag(text)
        lines = al.paired_lines(c.id)
        if tag in _RANK and lines:
            ltags = [hedge_tag(l.text) for l in lines]
            if all(t in _RANK for t in ltags) and _RANK[tag] > max(_RANK[t] for t in ltags):
                add(_cand(report, c, "overstated", "code.hedge", {"dictated": ltags[0], "report": tag}))
        # misattributed: a dictated measurement attached to a different structure
        paired_ids = {l.id for l in lines}
        for n in sorted(x for x in numbers(text) if x.endswith("mm")):
            owners = [l for l in al.lines if n in numbers(l.text)]
            if not owners or any(o.id in paired_ids for o in owners):
                continue
            o = owners[0]
            if words(o.text) & ANATOMY and not (words(o.text) & words(text) & ANATOMY):
                add(_cand(report, c, "misattributed", "code.measurement", {"number": n, "source_line": o.text},
                          line_id=o.id, line_text=o.text))
        # inconsistent: another modality's vocabulary (not dictated), size word against measurement
        if mod in _VOCAB:
            for other, pat in _VOCAB.items():
                m = pat.search(text) if other != mod else None
                if m and not pat.search(dictation):
                    add(_cand(report, c, "inconsistent", "code.modality", {"word": m.group(0), "modality": mod}))
        mm = _max_mm(text)
        if mm is not None and ((_SMALL.search(text) and mm >= SMALL_MAX_MM) or (_SUBCM.search(text) and mm >= 10)
                               or (_LARGE.search(text) and mm < LARGE_MIN_MM)):
            add(_cand(report, c, "inconsistent", "code.size_word", {"max_mm": mm}))

    # laterality (coverage lane): a dictated side missing from every paired clause, nothing bounding it
    if side_of(study_title) not in ("left", "right"):
        for l in al.lines:
            if l.side not in ("left", "right") or l.negative or l.background:
                continue
            cs = al.paired_clauses(l.id)
            if not cs or any(c.side in (l.side, "bilateral") or c.subheading_side == l.side for c in cs):
                continue
            if any(c.side and c.side != l.side for c in cs):
                continue                         # the other side is stated: classify-first's `differs`
            add(_cand(report, cs[0], "laterality", "code.laterality", {"side": l.side}, lane="coverage",
                      line_id=l.id, line_text=l.text))
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_review_engine_checks.py -q`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/review_engine/checks.py tests/test_review_engine_checks.py
rcommit "feat(review-engine): code checks (unsupported, overstated, misattributed, inconsistent, laterality)"
```

---

### Task 4: the migration and ORM models

The new tables are only queried by engine code (off by default). `Report.workspace_state` is mapped as **`deferred`**, so ordinary `Report` queries never select it, and a deploy that lands before the production migration cannot break report loading.

**Files:**
- Create: `migrations/versions/20261003120000_add_review_engine_tables.py`
- Modify: `src/rapid_reports_ai/database/models.py` (after `class Report`)
- Modify: `tests/conftest.py:42-50` (`_TEST_TABLES`)
- Test: `tests/test_review_engine_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_migration.py
"""Review engine storage (spec §10.2): migration on SQLite, ORM models in the test DB."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

MIG = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20261003120000_add_review_engine_tables.py"


def _load():
    spec = importlib.util.spec_from_file_location("mig_review_engine", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_chain_and_upgrade_on_sqlite():
    mod = _load()
    assert mod.revision == "20261003120000" and mod.down_revision == "20261001120000"
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("create table users (id varchar(36) primary key)"))
        conn.execute(sa.text("create table reports (id varchar(36) primary key)"))
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
        insp = sa.inspect(conn)
        assert {"report_review_runs", "report_review_items", "report_chat_messages"} <= set(insp.get_table_names())
        assert "workspace_state" in {c["name"] for c in insp.get_columns("reports")}
        assert {"ix_report_review_items_report_id", "ix_report_review_items_run_id"} <= \
            {i["name"] for i in insp.get_indexes("report_review_items")}
        with Operations.context(MigrationContext.configure(conn)):
            mod.downgrade()
        assert "report_review_items" not in sa.inspect(conn).get_table_names()


def test_orm_models_round_trip(db_session, test_user):
    from rapid_reports_ai.database.models import Report, ReportReviewItem, ReportReviewRun
    r = Report(report_type="quick", model_used="m", report_content="FINDINGS:\nx", user_id=test_user.id)
    db_session.add(r)
    db_session.commit()
    run = ReportReviewRun(report_id=r.id, mode="shadow", engine_version="0.1.0", pathway="quick", lanes={"coverage": "done"})
    db_session.add(run)
    db_session.commit()
    it = ReportReviewItem(report_id=r.id, run_id=run.id, key="k", lane="coverage", detectors=["jev"], kind="partial",
                          cls="minor", label="l", reason="r", status="open", history=[], engine_version="0.1.0")
    db_session.add(it)
    db_session.commit()
    assert db_session.query(ReportReviewItem).filter_by(run_id=run.id).one().kind == "partial"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_migration.py -q`
Expected: FAIL (`FileNotFoundError` for the migration; `ImportError` for the models).

- [ ] **Step 3: Write the migration**

```python
# migrations/versions/20261003120000_add_review_engine_tables.py
"""add review engine tables (runs, items, chat messages) and reports.workspace_state

Revision ID: 20261003120000
Revises: 20261001120000
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261003120000"
down_revision: Union[str, Sequence[str], None] = "20261001120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB if is_postgres else sa.JSON
    op.create_table(
        "report_review_runs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("report_id", uuid_type, nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("pathway", sa.String(length=16), nullable=False),
        sa.Column("lanes", json_type(), nullable=True),
        sa.Column("timings_ms", json_type(), nullable=True),
        sa.Column("cost", json_type(), nullable=True),
        sa.Column("errors", json_type(), nullable=True),
        sa.Column("shadow_log", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_review_runs_report_id", "report_review_runs", ["report_id"], unique=False)
    op.create_table(
        "report_review_items",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("report_id", uuid_type, nullable=False),
        sa.Column("run_id", uuid_type, nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("lane", sa.String(length=16), nullable=False),
        sa.Column("detectors", json_type(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("cls", sa.String(length=16), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column("anchor", json_type(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("edit", json_type(), nullable=True),
        sa.Column("verified", json_type(), nullable=True),
        sa.Column("probe", sa.Text(), nullable=True),
        sa.Column("citation", json_type(), nullable=True),
        sa.Column("source_line", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("history", json_type(), nullable=True),
        sa.Column("engine_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["report_review_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_review_items_report_id", "report_review_items", ["report_id"], unique=False)
    op.create_index("ix_report_review_items_run_id", "report_review_items", ["run_id"], unique=False)
    op.create_table(
        "report_chat_messages",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("report_id", uuid_type, nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("edits", json_type(), nullable=True),
        sa.Column("applied_item_ids", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_chat_messages_report_id", "report_chat_messages", ["report_id"], unique=False)
    op.add_column("reports", sa.Column("workspace_state", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "workspace_state")
    op.drop_index("ix_report_chat_messages_report_id", table_name="report_chat_messages")
    op.drop_table("report_chat_messages")
    op.drop_index("ix_report_review_items_run_id", table_name="report_review_items")
    op.drop_index("ix_report_review_items_report_id", table_name="report_review_items")
    op.drop_table("report_review_items")
    op.drop_index("ix_report_review_runs_report_id", table_name="report_review_runs")
    op.drop_table("report_review_runs")
```

- [ ] **Step 4: Add the ORM models in `models.py`**

Add `from sqlalchemy.orm import deferred` to the imports. In `class Report`, after `final_edit_diff`:

```python
    # Review rail workspace (spec §10.2): rail tab, expanded items, last text_hash. Deferred so ordinary report
    # queries never select it (safe if a deploy lands before the migration).
    workspace_state = deferred(Column(JSONBType(), nullable=True))
```

After `class Report` (before `ReportVersion`):

```python
def _now():
    return datetime.now(timezone.utc)


class ReportReviewRun(Base):
    """One review-engine run over a report (spec §10.2)."""
    __tablename__ = "report_review_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(16), nullable=False)               # shadow | live
    engine_version = Column(String(32), nullable=False)
    pathway = Column(String(16), nullable=False)            # quick | templated
    lanes = Column(JSONBType(), nullable=True)              # {lane: done | failed | skipped}
    timings_ms = Column(JSONBType(), nullable=True)
    cost = Column(JSONBType(), nullable=True)
    errors = Column(JSONBType(), nullable=True)
    shadow_log = Column(JSONBType(), nullable=True)         # Gate D: what options A / B would have done
    created_at = Column(DateTime, default=_now, nullable=False)


class ReportReviewItem(Base):
    """One review item (the ReviewItem contract, spec §10.1)."""
    __tablename__ = "report_review_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("report_review_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(32), nullable=False)
    lane = Column(String(16), nullable=False)
    detectors = Column(JSONBType(), nullable=True)
    kind = Column(String(32), nullable=False)
    cls = Column(String(16), nullable=False)
    section = Column(String(200), nullable=True)
    anchor = Column(JSONBType(), nullable=True)
    label = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    edit = Column(JSONBType(), nullable=True)
    verified = Column(JSONBType(), nullable=True)
    probe = Column(Text, nullable=True)
    citation = Column(JSONBType(), nullable=True)
    source_line = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="open")
    history = Column(JSONBType(), nullable=True)
    engine_version = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class ReportChatMessage(Base):
    """A rail chat message (spec §10.2; used from Slice D)."""
    __tablename__ = "report_chat_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    edits = Column(JSONBType(), nullable=True)
    applied_item_ids = Column(JSONBType(), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
```

- [ ] **Step 5: Add the tables to `tests/conftest.py`**

Extend the models import at the top of `tests/conftest.py` with `ReportReviewRun, ReportReviewItem, ReportChatMessage`, and append them to `_TEST_TABLES`:

```python
_TEST_TABLES = [
    User.__table__,
    PasswordResetToken.__table__,
    Template.__table__,
    EphemeralSkillSheet.__table__,
    Report.__table__,
    ReportQualityScore.__table__,
    TemplateCaseSheet.__table__,
    ReportReviewRun.__table__,
    ReportReviewItem.__table__,
    ReportChatMessage.__table__,
]
```

- [ ] **Step 6: Run the tests to verify they pass, plus the existing suite that loads reports**

Run: `.venv/bin/python -m pytest tests/test_review_engine_migration.py tests/test_migration_approval_gate.py tests/test_report_path_split.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add migrations/versions/20261003120000_add_review_engine_tables.py src/rapid_reports_ai/database/models.py tests/conftest.py tests/test_review_engine_migration.py
rcommit "feat(review-engine): review runs/items/chat tables, deferred reports.workspace_state, migration"
```

---

### Task 5: `store.py`, persistence and item events

**Files:**
- Create: `src/rapid_reports_ai/review_engine/store.py`
- Test: `tests/test_review_engine_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_store.py
"""Review engine storage (spec §10.2) and item events (spec §10.3)."""
import pytest

from rapid_reports_ai.database.models import Report
from rapid_reports_ai.review_engine import store
from rapid_reports_ai.review_engine.items import Edit, ReviewItem, Span


def _report(db, user):
    r = Report(report_type="quick", model_used="m", report_content="FINDINGS:\nx", user_id=user.id,
               candidate_reports=[{"content": "FINDINGS:\nx"}])
    db.add(r)
    db.commit()
    return str(r.id)


def _item(rid, run_id, cls="minor", kind="partial"):
    return ReviewItem(key=f"k-{kind}-{cls}", report_id=rid, run_id=run_id, lane="coverage", detectors=["jev"], kind=kind,
                      cls=cls, anchor=Span(start=0, end=3, text="abc"), edit=Edit(mode="replace", find="a", replace="b"),
                      history=[{"event": "created", "actor": "engine"}], engine_version="0.1.0")


def test_run_and_items_round_trip(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.save_items(db_session, [_item(rid, run_id), _item(rid, run_id, cls="suppress", kind="differs")])
    store.finish_run(db_session, run_id, lanes={"coverage": "done"}, timings_ms={"total": 5}, cost={}, errors={})
    run = store.latest_run(db_session, rid)
    assert run["id"] == run_id and run["lanes"] == {"coverage": "done"} and run["mode"] == "shadow"
    shown = store.list_items(db_session, rid)
    assert [i.kind for i in shown] == ["partial"] and shown[0].edit.find == "a" and shown[0].anchor.text == "abc"
    assert len(store.list_items(db_session, rid, include_suppressed=True)) == 2


def test_latest_run_only(db_session, test_user):
    rid = _report(db_session, test_user)
    old = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.save_items(db_session, [_item(rid, old)])
    new = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    store.save_items(db_session, [_item(rid, new, kind="absent")])
    assert [i.kind for i in store.list_items(db_session, rid)] == ["absent"]


def test_append_event_sets_status_and_history(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = _item(rid, run_id)
    store.save_items(db_session, [it])
    out = store.append_event(db_session, rid, it.id, "apply", text_hash="h1", detail={"x": 1})
    assert out.status == "applied" and out.history[-1]["event"] == "apply" and out.history[-1]["text_hash"] == "h1"
    out = store.append_event(db_session, rid, it.id, "view")
    assert out.status == "applied" and len(out.history) == 3


def test_unknown_command_and_wrong_report(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = _item(rid, run_id)
    store.save_items(db_session, [it])
    with pytest.raises(ValueError):
        store.append_event(db_session, rid, it.id, "explode")
    other = _report(db_session, test_user)
    assert store.append_event(db_session, other, it.id, "apply") is None


def test_update_item(db_session, test_user):
    rid = _report(db_session, test_user)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = _item(rid, run_id)
    store.save_items(db_session, [it])
    it.label, it.cls = "new label", "action"
    store.update_item(db_session, it)
    assert store.get_item(db_session, rid, it.id).label == "new label"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_store.py -q`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `store.py`**

```python
# src/rapid_reports_ai/review_engine/store.py
"""Persistence for review runs and items (spec §10.2). Sync functions that take a Session; the engine calls them in
a worker thread with a session of its own, the endpoints with the request's session."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..database.models import ReportReviewItem, ReportReviewRun
from .items import ReviewItem

# command → new status (None: history only). Spec §12.3 commands plus the engine's and the loop's own events.
COMMAND_STATUS = {
    "apply": "applied", "edit": "applied", "undo": "open", "dismiss": "dismissed", "restore": "open",
    "addressed": "addressed", "stale": "stale", "pre_applied": "pre_applied",
    "prepared": None, "view": None, "ask_chat": None,
}
_ITEM_FIELDS = ("key", "lane", "detectors", "kind", "cls", "section", "label", "reason", "probe", "citation",
                "source_line", "status", "history", "engine_version")


def _u(x) -> uuid.UUID:
    return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_run(db: Session, report_id: str, mode: str, engine_version: str, pathway: str) -> str:
    run = ReportReviewRun(report_id=_u(report_id), mode=mode, engine_version=engine_version, pathway=pathway,
                          lanes={}, timings_ms={}, cost={}, errors={})
    db.add(run)
    db.commit()
    return str(run.id)


def finish_run(db: Session, run_id: str, lanes: dict, timings_ms: dict, cost: dict, errors: dict,
               shadow_log: Optional[dict] = None) -> None:
    run = db.get(ReportReviewRun, _u(run_id))
    if run is None:
        return
    run.lanes, run.timings_ms, run.cost, run.errors, run.shadow_log = lanes, timings_ms, cost, errors, shadow_log
    db.commit()


def _row(item: ReviewItem) -> ReportReviewItem:
    d = item.model_dump()
    return ReportReviewItem(id=_u(item.id), report_id=_u(item.report_id), run_id=_u(item.run_id),
                            anchor=d["anchor"], edit=d["edit"], verified=d["verified"],
                            **{k: d[k] for k in _ITEM_FIELDS})


def _model(row: ReportReviewItem) -> ReviewItem:
    return ReviewItem(id=str(row.id), report_id=str(row.report_id), run_id=str(row.run_id), anchor=row.anchor,
                      edit=row.edit, verified=row.verified, detectors=row.detectors or [], history=row.history or [],
                      label=row.label or "", reason=row.reason or "", engine_version=row.engine_version or "",
                      **{k: getattr(row, k) for k in ("key", "lane", "kind", "cls", "section", "probe", "citation",
                                                       "source_line", "status")})


def save_items(db: Session, items: List[ReviewItem]) -> None:
    db.add_all([_row(i) for i in items])
    db.commit()


def latest_run(db: Session, report_id: str) -> Optional[dict]:
    run = (db.query(ReportReviewRun).filter(ReportReviewRun.report_id == _u(report_id))
           .order_by(ReportReviewRun.created_at.desc()).first())
    if run is None:
        return None
    return {"id": str(run.id), "mode": run.mode, "engine_version": run.engine_version, "pathway": run.pathway,
            "lanes": run.lanes or {}, "timings_ms": run.timings_ms or {}, "cost": run.cost or {},
            "errors": run.errors or {}, "created_at": run.created_at.isoformat() if run.created_at else None}


def list_items(db: Session, report_id: str, run_id: Optional[str] = None,
               include_suppressed: bool = False) -> List[ReviewItem]:
    if run_id is None:
        run = latest_run(db, report_id)
        if run is None:
            return []
        run_id = run["id"]
    q = db.query(ReportReviewItem).filter(ReportReviewItem.report_id == _u(report_id),
                                          ReportReviewItem.run_id == _u(run_id))
    if not include_suppressed:
        q = q.filter(ReportReviewItem.cls != "suppress")
    return [_model(r) for r in q.order_by(ReportReviewItem.created_at, ReportReviewItem.key).all()]


def get_item(db: Session, report_id: str, item_id: str) -> Optional[ReviewItem]:
    row = db.get(ReportReviewItem, _u(item_id))
    return _model(row) if row is not None and row.report_id == _u(report_id) else None


def append_event(db: Session, report_id: str, item_id: str, command: str, text_hash: Optional[str] = None,
                 detail: Optional[dict] = None, actor: str = "user") -> Optional[ReviewItem]:
    if command not in COMMAND_STATUS:
        raise ValueError(f"unknown review command: {command}")
    row = db.get(ReportReviewItem, _u(item_id))
    if row is None or row.report_id != _u(report_id):
        return None
    row.history = list(row.history or []) + [{"at": _now().isoformat(), "event": command, "actor": actor,
                                              "text_hash": text_hash, "detail": detail or {}}]
    flag_modified(row, "history")
    if COMMAND_STATUS[command]:
        row.status = COMMAND_STATUS[command]
    db.commit()
    return _model(row)


def update_item(db: Session, item: ReviewItem) -> None:
    """Overwrite an item's judged fields after re-prepare or verification."""
    row = db.get(ReportReviewItem, _u(item.id))
    if row is None:
        return
    d = item.model_dump()
    for k in ("cls", "kind", "label", "reason", "probe", "status", "section"):
        setattr(row, k, d[k])
    row.edit, row.verified, row.anchor = d["edit"], d["verified"], d["anchor"]
    row.history = d["history"]
    flag_modified(row, "history")
    db.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_review_engine_store.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/review_engine/store.py tests/test_review_engine_store.py
rcommit "feat(review-engine): store for runs, items and item events"
```

---

### Task 6: the shared Jev pass and the three lanes

The coverage and accuracy lanes read **one** batched Jev pass. It asks exactly today's `check()` questions and keeps the raw answers, so unsure answers can be routed (§6.5) instead of dropped. In shadow mode this repeats `check()`'s two requests; in live mode it replaces them.

**Files:**
- Create: `src/rapid_reports_ai/review_engine/jev_pass.py`
- Create: `src/rapid_reports_ai/review_engine/lanes/__init__.py`, `lanes/coverage.py`, `lanes/accuracy.py`, `lanes/additions.py`
- Create: `tests/review_engine_fakes.py` (shared fakes for engine tests)
- Test: `tests/test_review_engine_lanes.py`

- [ ] **Step 1: Write the shared fakes and the failing test**

```python
# tests/review_engine_fakes.py
"""Shared fakes for review-engine tests: Jev answers by question-id prefix, a stub Qwen, input builders."""
from rapid_reports_ai.generation_artifacts import GenerationArtifacts
from rapid_reports_ai.report_review import quick_section_names
from rapid_reports_ai.review_engine.items import ReviewInput

SEL_ABNORMAL = {"choice": "abnormal_finding", "probabilities": {
    "abnormal_finding": 0.9, "limitation": 0.0, "normal_or_negative": 0.1, "protocol_note": 0.0, "comparison": 0.0,
    "mixed_abnormal_and_normal": 0.0}}
STATED = {"choice": "stated", "probabilities": {"stated": 0.9, "partial": 0.05, "absent": 0.05}}


def jev(over=None, calls=None):
    """An async rc._jev stand-in. `over` maps a question id (or a prefix ending in '*') to an answer."""
    over = over or {}

    def answer(k):
        if k in over:
            return over[k]
        for pat, v in over.items():
            if pat.endswith("*") and k.startswith(pat[:-1]):
                return v
        if k.startswith("sel"):
            return SEL_ABNORMAL
        if k.startswith("lt"):
            return {"noul": 0.9}
        if k.startswith("i"):
            return STATED
        return {"noul": 0.1}

    async def fake(state, qs):
        if calls is not None:
            calls.append((state, dict(qs)))
        return {k: answer(k) for k in qs}
    return fake


def model(output, calls=None):
    """An async _run_agent_with_model stand-in returning `output` (or output(kwargs) if callable)."""
    class R:
        pass

    async def fake(**kw):
        if calls is not None:
            calls.append(kw)
        r = R()
        r.output = output(kw) if callable(output) else output
        return r
    return fake


def inp(report, dictation, options=None, quality_check=None, pathway="quick", synthesis=None, history="",
        scan="CT abdomen", title=None, pre_edit=None):
    art = GenerationArtifacts(report=report, dictated_findings=dictation, sections=quick_section_names(report),
                              options=options or [], brief=None, quality_check=quality_check)
    return ReviewInput(report_id="00000000-0000-0000-0000-000000000001", pathway=pathway, artifacts=art,
                       clinical_history=history, scan_type=scan, study_title=title, synthesis=synthesis,
                       pre_edit_report=pre_edit)
```

```python
# tests/test_review_engine_lanes.py
"""Lanes (spec §6): coverage, accuracy and additions over the shared Jev pass, with unsure routing (§6.5)."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.report_review import checked_clauses
from rapid_reports_ai.review_engine import jev_pass
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.checks import run_checks
from rapid_reports_ai.review_engine.lanes import LaneContext
from rapid_reports_ai.review_engine.lanes.accuracy import AccuracyLane
from rapid_reports_ai.review_engine.lanes.additions import AdditionsLane, brief_candidates, s4_candidates
from rapid_reports_ai.review_engine.lanes.coverage import CoverageLane

from review_engine_fakes import inp, jev

REPORT = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst. No free fluid.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst with a thin septation\n- Liver normal"
SEL_NORMAL = {"choice": "normal_or_negative", "probabilities": {"abnormal_finding": 0.05, "limitation": 0.0,
              "normal_or_negative": 0.9, "protocol_note": 0.05, "comparison": 0.0, "mixed_abnormal_and_normal": 0.0}}


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("unstubbed Jev call")
    monkeypatch.setattr(rc, "_jev", boom)


async def ctx_for(monkeypatch, i, over=None):
    monkeypatch.setattr(rc, "_jev", jev(over))
    a = i.artifacts
    al = align(a.report, a.dictated_findings, i.clinical_history, a.sections)
    jp = await jev_pass.run(i, a.report)
    return LaneContext(alignment=al, jev=jp, checks=run_checks(a.report, a.dictated_findings, "", i.scan_type, al))


async def test_jev_pass_asks_todays_questions(monkeypatch):
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    jp = await jev_pass.run(inp(REPORT, DICT), REPORT)
    states = {s.split(":")[0]: qs for s, qs in calls}
    assert {"c0", "sel0", "lt0"} <= set(states["SCAN TYPE"]) and "i0" in states["REPORT"]
    assert jp.items == ["14 mm left renal cyst with a thin septation", "Liver normal"] and not jp.contra_error


async def test_coverage_partial_with_missing_detail(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"sel1": SEL_NORMAL, "lt1": {"noul": 0.1},
                                        "i0": {"choice": "partial", "probabilities": {"partial": 0.8, "stated": 0.2}}})
    cs = await CoverageLane().candidates(i, ctx)
    assert [(c.kind, c.line_id) for c in cs] == [("partial", "d0")]
    assert cs[0].evidence["missing_detail"] == "thin septation" and cs[0].anchor and cs[0].detector == "jev.classify_first"


async def test_coverage_unsure_names_question_not_leaning(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"sel1": SEL_NORMAL, "lt1": {"noul": 0.1},
                                        "i0": {"choice": "stated", "probabilities": {"stated": 0.5, "partial": 0.45}}})
    cs = await CoverageLane().candidates(i, ctx)
    assert cs[0].kind == "coverage_check" and cs[0].evidence == {"jev_unsure": {"question": "classify_first"}}


async def test_coverage_skips_dictated_negatives_and_unclear(monkeypatch):
    i = inp(REPORT, "- No free fluid\n- Heading:")
    ctx = await ctx_for(monkeypatch, i, {"i*": {"choice": "unclear", "probabilities": {"unclear": 0.9}}})
    assert await CoverageLane().candidates(i, ctx) == []


async def test_accuracy_negative_contradiction_gets_code_removal(monkeypatch):
    i = inp(REPORT, "- Free fluid in the pelvis\n- 14 mm left renal cyst")
    k = checked_clauses(REPORT, None).index("No free fluid.")      # the Jev pass's own clause order
    ctx = await ctx_for(monkeypatch, i, {f"c{k}": {"noul": 0.8}, f"r{k}": {"noul": 0.9}, f"d{k}": {"noul": 0.1}})
    cs = [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "contradicted"]
    e = cs[0].proposed
    assert cs and cs[0].code_fix and "No free fluid." in e.find and "No free fluid" not in (e.replace or "")
    assert "A 14 mm left renal cyst." in (e.replace or "")     # the rest of the line is kept


async def test_accuracy_keeps_a_dictated_negative(monkeypatch):
    i = inp(REPORT, "- No free fluid\n- 14 mm left renal cyst")
    k = checked_clauses(REPORT, None).index("No free fluid.")
    ctx = await ctx_for(monkeypatch, i, {f"c{k}": {"noul": 0.8}, f"r{k}": {"noul": 0.9}, f"d{k}": {"noul": 0.9}})
    assert not [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "contradicted"]


async def test_accuracy_positive_and_unsure(monkeypatch):
    i = inp(REPORT, DICT)
    ctx = await ctx_for(monkeypatch, i, {"c1": {"noul": 0.7}, "c0": {"noul": 0.5}})
    cs = [c for c in await AccuracyLane().candidates(i, ctx) if c.kind == "contradicted"]
    pos = [c for c in cs if not c.evidence.get("jev_unsure")]
    uns = [c for c in cs if c.evidence.get("jev_unsure")]
    assert pos and pos[0].proposed is None and not pos[0].code_fix
    assert uns and uns[0].evidence == {"jev_unsure": {"question": "contradiction"}}


async def test_accuracy_forwards_code_checks(monkeypatch):
    rep = "FINDINGS:\nThe CBD measures 6 mm.\nIMPRESSION:\nNormal."
    i = inp(rep, "- CBD not dilated")
    ctx = await ctx_for(monkeypatch, i)
    assert ("unsupported", "code.numbers") in [(c.kind, c.detector) for c in await AccuracyLane().candidates(i, ctx)]


def test_brief_options_preclassed_minor_with_probe():
    i = inp(REPORT, DICT, options=[{"id": "o1", "kind": "recommendation", "section": "IMPRESSION",
                                    "sentence": "Follow-up ultrasound is suggested.", "reason": "r"}])
    al = align(REPORT, DICT, "", i.artifacts.sections)
    c = brief_candidates(i, al)[0]
    assert c.preclassed == "minor" and c.probe.startswith(rc.Q_CONVEYS) and c.detector == "brief.option"
    assert c.proposed.mode == "insert" and c.proposed.after is None and c.proposed.section == "IMPRESSION"


def test_finding_negative_on_normal_structure_goes_to_adjudicator():
    i = inp(REPORT, DICT, options=[{"id": "o2", "kind": "finding_negative", "section": "FINDINGS",
                                    "sentence": "No focal liver lesion.", "reason": ""}])
    al = align(REPORT, DICT, "", i.artifacts.sections)
    c = brief_candidates(i, al)[0]
    assert c.preclassed is None and c.evidence["upgrade_target"] == "The liver is normal." and c.anchor


def test_s4_mapping():
    assert s4_candidates(None) == []
    card = {"finding_number": 1, "finding": "renal cyst", "finding_short_label": "Renal cyst",
            "classifications": [{"system": "Bosniak 2019", "grade": "II", "criteria": "c"}],
            "thresholds": [], "follow_up_actions": [{"modality": "US", "timing": "6 months", "indication": "i"}],
            "differentials": [], "imaging_flags": [], "sources": [{"url": "u", "title": "t"}]}
    cs = s4_candidates({"guidelines": [card]})
    assert [c.kind for c in cs] == ["grade", "follow_up"] and cs[0].citation == {"card": 1, "source": "u", "label": "t"}
    assert "criteria" not in cs[0].evidence
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_lanes.py -q`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `jev_pass.py`**

```python
# src/rapid_reports_ai/review_engine/jev_pass.py
"""The one shared Jev pass (spec §6.2–§6.3): today's check() questions, two batched requests in parallel, raw answers
kept so the lanes can route unsure answers (§6.5) instead of dropping them."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .. import report_reconcile as rc
from ..report_review import (JEV_TIMEOUT_S, Q_CONTRA, checked_clauses_in_context, dictated_items, q_dictated,
                             q_omission, q_restated, q_select_choice, q_select_noul, restate, without)
from .alignment import section_models
from .items import ReviewInput

logger = logging.getLogger(__name__)


class JevPass(BaseModel):
    clauses: List[str] = []
    before: Dict[str, str] = {}
    items: List[str] = []
    contra: Dict[str, Any] = {}
    omit: Dict[str, Any] = {}
    contra_error: Optional[str] = None
    omit_error: Optional[str] = None


def sections_for(inp: ReviewInput):
    return section_models(inp.artifacts.sections) if inp.pathway == "templated" else None


async def run(inp: ReviewInput, report: str) -> JevPass:
    sections = sections_for(inp)
    findings = inp.artifacts.dictated_findings
    before = checked_clauses_in_context(report, sections)
    cls = list(before)
    items = dictated_items(findings)
    contra_qs = {f"c{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, t in enumerate(cls)}
    restated = {i: restate(t) for i, t in enumerate(cls)}
    contra_qs.update({f"r{i}": q_restated(r) for i, r in restated.items() if r})
    contra_qs.update({f"d{i}": q_dictated(cls[i], before[cls[i]]) for i, r in restated.items() if r})
    contra_qs.update({f"sel{i}": q_select_choice(t) for i, t in enumerate(items)})
    contra_qs.update({f"lt{i}": q_select_noul(t) for i, t in enumerate(items)})
    omit_qs = {f"i{i}": q_omission(t) for i, t in enumerate(items)}
    hidden = ([inp.clinical_history] if inp.clinical_history else []) if sections is not None else []

    async def ask(state: str, qs: dict):
        return await asyncio.wait_for(rc._jev(state, qs), JEV_TIMEOUT_S) if qs else {}

    contra, omit = await asyncio.gather(
        ask(f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        ask(f"REPORT:\n{without(report, hidden, sections)}", omit_qs), return_exceptions=True)
    out = JevPass(clauses=cls, before=before, items=items)
    for name, res in (("contra", contra), ("omit", omit)):
        if isinstance(res, BaseException):
            setattr(out, f"{name}_error", f"{type(res).__name__}: {str(res)[:200]}")
            logger.warning("review engine: Jev %s request failed (%s)", name, type(res).__name__)
        else:
            setattr(out, name, res or {})
    return out


def noul(answers: Dict[str, Any], key: str) -> Optional[float]:
    try:
        return float(answers[key]["noul"])
    except Exception:
        return None
```

- [ ] **Step 4: Write `lanes/__init__.py`**

```python
# src/rapid_reports_ai/review_engine/lanes/__init__.py
"""Lanes (spec §6.1). Each lane turns the shared context into candidates; each is independently switchable."""
from __future__ import annotations

from typing import List, Optional, Protocol

from pydantic import BaseModel, ConfigDict

from ..alignment import Alignment
from ..items import Candidate, ReviewInput
from ..jev_pass import JevPass


class LaneContext(BaseModel):
    """What every lane reads: the alignment, the shared Jev pass (None when no Jev lane runs) and the code checks.
    Spec §6.1's `candidates(inp, al)` gains the shared pass so the batched Jev requests are made once."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    alignment: Alignment
    jev: Optional[JevPass] = None
    checks: List[Candidate] = []


class Lane(Protocol):
    name: str

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]: ...
```

- [ ] **Step 5: Write `lanes/coverage.py`**

```python
# src/rapid_reports_ai/review_engine/lanes/coverage.py
"""Coverage lane (spec §6.2): is everything dictated carried, as dictated? Classify-first per selected line
(L-49); dictated negatives never checked; unsure answers routed to the adjudicator (§6.5)."""
from __future__ import annotations

import re
from typing import List

from ...report_review import missing_detail, omission_class, selected
from ..items import Candidate, ReviewInput, Span
from . import LaneContext

OMIT_CONFIDENT = 0.6   # provisional: Gate A wording read sets the unsure band (§6.5)
_KIND = {"absent": "absent", "partial": "partial", "different": "differs"}
_DICT_NEG = re.compile(r"^\s*(no|nil|without)\b", re.I)


class CoverageLane:
    name = "coverage"

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]:
        out: List[Candidate] = []
        jp, report = ctx.jev, inp.artifacts.report
        if jp is not None and jp.omit_error is None:
            sel = jp.contra if jp.contra_error is None else {}
            for i, t in enumerate(jp.items):
                if _DICT_NEG.match(t) or not selected(t, sel.get(f"sel{i}"), sel.get(f"lt{i}")):
                    continue
                kind, p = omission_class(jp.omit.get(f"i{i}"))
                if kind is None or kind == "unclear" or (kind == "stated" and p >= OMIT_CONFIDENT):
                    continue
                line_id = f"d{i}"
                cs = ctx.alignment.paired_clauses(line_id)
                c = cs[0] if cs else None
                anchor = Span(start=c.start, end=c.end, text=report[c.start:c.end]) if c else None
                common = dict(lane="coverage", section=c.section if c else None, anchor=anchor, line_id=line_id,
                              line_text=t, detector="jev.classify_first")
                if p < OMIT_CONFIDENT:
                    out.append(Candidate(kind="coverage_check", evidence={"jev_unsure": {"question": "classify_first"}},
                                         **common))
                    continue
                ev = {}
                if kind == "partial":
                    md = missing_detail(t, report)
                    if md:
                        ev["missing_detail"] = md
                out.append(Candidate(kind=_KIND[kind], evidence=ev, **common))
        out += [c for c in ctx.checks if c.lane == "coverage"]
        return out
```

- [ ] **Step 6: Write `lanes/accuracy.py`**

```python
# src/rapid_reports_ai/review_engine/lanes/accuracy.py
"""Accuracy lane (spec §6.3): is everything in the report supported and consistent? Jev contradiction per clause
(today's wording) plus the code checks. A contradicted negative gets code removal (never an LLM rewrite, L-47);
a positive one goes to the adjudicator."""
from __future__ import annotations

from typing import List, Optional

from ...report_review import CONTRA_FLAG, DICTATED_KEEP, RESTATED_FLAG, remove_negative_clause, restate
from ..items import Candidate, Edit, ReviewInput, Span
from ..jev_pass import noul, sections_for
from . import LaneContext

CONTRA_UNSURE_LO = 0.4   # provisional: the unsure band below CONTRA_FLAG (§6.5), set in a wording read


def edit_from_diff(old: str, new: str) -> Optional[Edit]:
    """The line-level edit that turns `old` into `new` (a code removal), as a verbatim find/replace."""
    if old == new:
        return None
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new)) - p and old[-1 - s] == new[-1 - s]:
        s += 1
    a = old.rfind("\n", 0, p) + 1
    nl = old.find("\n", len(old) - s)
    b = len(old) if nl < 0 else nl
    find = old[a:b]
    replace = new[a:len(new) - (len(old) - b)]
    return Edit(mode="remove" if not replace.strip() else "replace", find=find, replace=replace or None)


def _span(ctx: LaneContext, report: str, clause: str) -> Optional[Span]:
    c = next((c for c in ctx.alignment.clauses if c.text == clause), None)
    return Span(start=c.start, end=c.end, text=report[c.start:c.end]) if c else None


def _section(ctx: LaneContext, clause: str) -> Optional[str]:
    c = next((c for c in ctx.alignment.clauses if c.text == clause), None)
    return c.section if c else None


class AccuracyLane:
    name = "accuracy"

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]:
        out: List[Candidate] = []
        jp, report = ctx.jev, inp.artifacts.report
        if jp is not None and jp.contra_error is None:
            for i, t in enumerate(jp.clauses):
                c = noul(jp.contra, f"c{i}")
                if c is None or c < CONTRA_UNSURE_LO:
                    continue
                common = dict(lane="accuracy", kind="contradicted", section=_section(ctx, t), anchor=_span(ctx, report, t),
                              detector="jev.contradiction")
                if c < CONTRA_FLAG:
                    out.append(Candidate(evidence={"jev_unsure": {"question": "contradiction"}}, **common))
                    continue
                if restate(t):
                    if (noul(jp.contra, f"r{i}") or 0.0) < RESTATED_FLAG:
                        continue
                    d = noul(jp.contra, f"d{i}")
                    if d is None or d >= DICTATED_KEEP:
                        continue                  # the dictation itself states this negative (L-49)
                    new = remove_negative_clause(report, t, sections=sections_for(inp)) if inp.pathway == "templated" \
                        else remove_negative_clause(report, t)
                    out.append(Candidate(evidence={"negative": True, "score": c}, proposed=edit_from_diff(report, new),
                                         code_fix=True, **common))
                else:
                    out.append(Candidate(evidence={"negative": False, "score": c}, **common))
        out += [c for c in ctx.checks if c.lane == "accuracy"]
        return out
```

- [ ] **Step 7: Write `lanes/additions.py` (the gate is added in Task 7)**

```python
# src/rapid_reports_ai/review_engine/lanes/additions.py
"""Additions lane (spec §6.4): producers, then one Jev gate (Task 7). Brief options arrive pre-classed `minor`
with their sentence (not judged again, Principle 2); a finding_negative on a structure the report already calls
normal goes to the adjudicator for an `upgrade`. S4 synthesis cards map in code; the clinical pass joins after Gate C."""
from __future__ import annotations

import re
from typing import List, Optional

from ... import report_reconcile as rc
from ..alignment import ANATOMY, Alignment, ReportClause, words
from ..items import Candidate, Edit, ReviewInput, Span
from . import LaneContext

_NORMAL = re.compile(r"\b(normal|unremarkable)\b", re.I)


def _normal_clause_for(sentence: str, al: Alignment) -> Optional[ReportClause]:
    anat = words(sentence) & ANATOMY
    for c in al.clauses:
        if anat and _NORMAL.search(c.text) and not c.negative and anat & words(c.text):
            return c
    return None


def brief_candidates(inp: ReviewInput, al: Alignment) -> List[Candidate]:
    out = []
    for o in inp.artifacts.options:
        s = (o.get("sentence") or "").strip()
        if not s:
            continue
        sub = o.get("kind") or "impression"
        section = o.get("section") or "IMPRESSION"
        ev = {"sub_kind": sub, "option_id": o.get("id"), "sentence": s, "reason": o.get("reason") or ""}
        target = _normal_clause_for(s, al) if sub == "finding_negative" else None
        if target is not None:
            out.append(Candidate(lane="additions", kind="option", section=target.section,
                                 anchor=Span(start=target.start, end=target.end,
                                             text=inp.artifacts.report[target.start:target.end]),
                                 evidence={**ev, "upgrade_target": target.text}, probe=rc.Q_CONVEYS + s,
                                 detector="brief.option"))
        else:
            out.append(Candidate(lane="additions", kind="option", section=section, evidence=ev,
                                 proposed=Edit(mode="insert", replace=s, after=None, section=section),
                                 preclassed="minor", probe=rc.Q_CONVEYS + s, detector="brief.option"))
    return out


def _s4(card: dict, kind: str, detector: str, evidence: dict) -> Candidate:
    src = (card.get("sources") or [{}])[0]
    return Candidate(lane="additions", kind=kind, line_text=card.get("finding_short_label") or card.get("finding"),
                     evidence={"finding": card.get("finding"), **{k: v for k, v in evidence.items() if v}},
                     citation={"card": card.get("finding_number"), "source": src.get("url"), "label": src.get("title")},
                     detector=detector)


def s4_candidates(synthesis: Optional[dict], with_criteria: bool = False) -> List[Candidate]:
    """S4 cards → candidates (same mapping as the Gate C lab, scripts/review_labs/additions_map.py)."""
    out: List[Candidate] = []
    for card in (synthesis or {}).get("guidelines") or []:
        for c in card.get("classifications") or []:
            ev = {"system": c.get("system"), "grade": c.get("grade")}
            if with_criteria:
                ev["criteria"] = c.get("criteria")
            out.append(_s4(card, "grade", "s4.classification", ev))
        for t in card.get("thresholds") or []:
            out.append(_s4(card, "threshold", "s4.threshold", {"parameter": t.get("parameter"),
                                                              "threshold": t.get("threshold"),
                                                              "significance": t.get("significance")}))
        for i, f in enumerate(card.get("follow_up_actions") or []):
            out.append(_s4(card, "follow_up" if i == 0 else "option", "s4.follow_up",
                           {"modality": f.get("modality"), "timing": f.get("timing"), "indication": f.get("indication")}))
        for d in card.get("differentials") or []:
            out.append(_s4(card, "option", "s4.differential", {"text": d.get("diagnosis")}))
        for fl in card.get("imaging_flags") or []:
            out.append(_s4(card, "option", "s4.imaging_flag", {"text": fl if isinstance(fl, str) else str(fl)}))
    return out


class AdditionsLane:
    name = "additions"

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]:
        return brief_candidates(inp, ctx.alignment) + s4_candidates(inp.synthesis)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_engine_lanes.py -q`
Expected: 12 passed. The Jev pass numbers clauses in `checked_clauses(report, None)` order. In `test_accuracy_positive_and_unsure`, index 1 is "A 14 mm left renal cyst." (positive) and index 0 is "The liver is normal." (positive, unsure at 0.5). A code removal of one clause on a multi-clause line arrives as a line-level `replace` that keeps the rest of the line. `verifier.guard_failures` exempts `kind == "contradicted"` from `drops_negation` for exactly this case (Task 9).

- [ ] **Step 9: Commit**

```bash
git add src/rapid_reports_ai/review_engine/jev_pass.py src/rapid_reports_ai/review_engine/lanes tests/review_engine_fakes.py tests/test_review_engine_lanes.py
rcommit "feat(review-engine): shared Jev pass and coverage/accuracy/additions lanes with unsure routing"
```

---

### Task 7: the Jev "already in report" gate for Additions

**Files:**
- Modify: `src/rapid_reports_ai/review_engine/lanes/additions.py`
- Test: `tests/test_review_engine_in_report_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_in_report_gate.py
"""The Additions "already in report" gate (spec §6.4, §6.5): drop stated, keep unsure for the adjudicator."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.lanes import LaneContext
from rapid_reports_ai.review_engine.lanes.additions import AdditionsLane, brief_candidates, in_report_gate

from review_engine_fakes import inp, jev

REPORT = "FINDINGS:\nThe liver is normal.\nIMPRESSION:\nNo acute finding."
OPTS = [{"id": f"o{k}", "kind": "impression", "section": "IMPRESSION", "sentence": s, "reason": ""}
        for k, s in enumerate(["Sentence A.", "Sentence B.", "Sentence C."])]


def _cands():
    i = inp(REPORT, "- x", options=OPTS)
    return i, brief_candidates(i, align(REPORT, "- x", "", i.artifacts.sections))


async def test_gate_drops_stated_and_routes_unsure(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"g0": {"noul": 0.9}, "g1": {"noul": 0.3}, "g2": {"noul": 0.05}}))
    i, cs = _cands()
    out = await in_report_gate(REPORT, cs)
    assert [c.evidence["option_id"] for c in out] == ["o1", "o2"]
    assert out[0].preclassed is None and out[0].evidence["jev_unsure"] == {"question": "already_in_report"}
    assert out[1].preclassed == "minor" and "jev_unsure" not in out[1].evidence


async def test_gate_fails_open(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(rc, "_jev", boom)
    i, cs = _cands()
    assert len(await in_report_gate(REPORT, cs)) == 3


async def test_lane_applies_gate(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"g*": {"noul": 0.9}}))
    i, _ = _cands()
    ctx = LaneContext(alignment=align(REPORT, "- x", "", i.artifacts.sections))
    assert await AdditionsLane().candidates(i, ctx) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_in_report_gate.py -q`
Expected: FAIL (`ImportError: in_report_gate`).

- [ ] **Step 3: Add the gate to `lanes/additions.py`**

Add these imports, and keep the existing ones:

```python
import asyncio
import logging

from ...report_review import JEV_TIMEOUT_S

logger = logging.getLogger(__name__)

IN_REPORT_DROP = 0.5        # provisional: Gate C ("already in report" wording read)
IN_REPORT_UNSURE_LO = 0.25  # provisional: Gate C


def candidate_text(c: Candidate) -> str:
    ev = c.evidence
    if ev.get("sentence"):
        return ev["sentence"]
    if c.kind == "grade":
        return f"a {ev.get('system')} category for the {c.line_text}"
    if c.kind == "threshold":
        return f"the {ev.get('parameter')} threshold {ev.get('threshold')} for the {c.line_text}"
    if ev.get("modality"):
        return f"{ev.get('modality')} follow-up {ev.get('timing') or ''} for the {c.line_text}".replace("  ", " ")
    return f"{ev.get('text')} (for the {c.line_text})"


async def in_report_gate(report: str, cands: List[Candidate]) -> List[Candidate]:
    """One report-state Jev call (L-49 uniqueness wording: *states*, not merely implies). Stated → dropped; unsure →
    kept with evidence.jev_unsure and no pre-class, so the adjudicator reads it (§6.5); Jev failure → all kept."""
    qs = {f"g{k}": {"type": "noul", "instructions": rc.Q_CONVEYS + candidate_text(c)} for k, c in enumerate(cands)}
    if not qs:
        return []
    try:
        ans = await asyncio.wait_for(rc._jev(f"REPORT:\n{report}", qs), JEV_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - fail open: the adjudicator and verifier still run
        logger.warning("review engine: in-report gate failed (%s)", type(e).__name__)
        return list(cands)
    out = []
    for k, c in enumerate(cands):
        try:
            p = float(ans[f"g{k}"]["noul"])
        except Exception:
            out.append(c)
            continue
        if p >= IN_REPORT_DROP:
            continue
        if p >= IN_REPORT_UNSURE_LO:
            c = c.model_copy(update={"preclassed": None,
                                     "evidence": {**c.evidence, "jev_unsure": {"question": "already_in_report"}}})
        out.append(c)
    return out
```

Change `AdditionsLane.candidates` to apply the gate:

```python
    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]:
        return await in_report_gate(inp.artifacts.report, brief_candidates(inp, ctx.alignment) + s4_candidates(inp.synthesis))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_engine_in_report_gate.py tests/test_review_engine_lanes.py -q`
Expected: all pass. The lanes test's `s4`/`brief` tests call the producers directly, so they are unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/review_engine/lanes/additions.py tests/test_review_engine_in_report_gate.py
rcommit "feat(review-engine): Additions 'already in report' Jev gate with unsure routing"
```

---

### Task 8: `adjudicator.py`, one flat Qwen call per group

The field names match Plan 1's lab `judgement.Judgement` exactly, so Gate A's golden outputs replay against this model.

**Files:**
- Create: `src/rapid_reports_ai/review_engine/adjudicator.py`
- Create: `src/rapid_reports_ai/review_engine/prompts/adjudicator.txt`
- Test: `tests/test_review_engine_adjudicator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_adjudicator.py
"""Adjudicator (spec §7): flat Judgement, one call per group, caps, failure → minor/no fix, brief-option rules."""
import asyncio

import pytest

from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine.items import Candidate, Edit, ReviewItem

from review_engine_fakes import inp, model

J = dict(cls="action", kind="partial", label="Size missing", reason="r", edit_mode="replace", edit_find="a cyst",
         edit_replace="a 14 mm cyst", edit_after=None, edit_section="FINDINGS", probe="The FINDINGS section states the size.")


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    async def boom(**kw):
        raise AssertionError("unstubbed model call")
    monkeypatch.setattr(adj, "_run_agent_with_model", boom)


def C(kind="partial", preclassed=None, detector="jev.classify_first", unsure=False):
    return Candidate(lane="coverage", kind=kind, preclassed=preclassed, detector=detector, line_text="line",
                     evidence={"jev_unsure": {"question": "classify_first"}} if unsure else {})


def test_judgement_is_flat_and_prompt_present():
    assert all(f.annotation not in (dict, list) for f in adj.Judgement.model_fields.values())
    p = adj.prompt()
    assert "Uncertain means minor" in p and "When in doubt, suppress" not in p


def test_needs_judgement():
    assert adj.needs_judgement([C()])
    assert not adj.needs_judgement([C(preclassed="minor", detector="brief.option")])
    assert adj.needs_judgement([C(preclassed="minor", detector="brief.option", unsure=True)])


async def test_adjudicate_calls_per_group_and_skips_preclassed(monkeypatch):
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(**J), calls))
    out = await adj.adjudicate(inp("FINDINGS:\nA cyst.", "- 14 mm cyst"),
                               [[C()], [C(preclassed="minor", detector="brief.option")]])
    assert len(calls) == 1 and out[0].judgement.cls == "action" and out[1].judgement is None and out[1].error is None
    assert calls[0]["model_settings"]["reasoning_effort"] == "medium" and "DICTATION" in calls[0]["user_prompt"]


async def test_failure_and_overflow_become_errors(monkeypatch):
    async def bad(**kw):
        raise ValueError("validation")
    monkeypatch.setattr(adj, "_run_agent_with_model", bad)
    monkeypatch.setattr(adj, "GROUP_CAP", 2)
    out = await adj.adjudicate(inp("FINDINGS:\nA.", "- a"), [[C()], [C()], [C()]])
    assert [o.error.split(":")[0] for o in out] == ["ValueError", "ValueError", "overflow"]


async def test_concurrency_cap(monkeypatch):
    live, peak = 0, 0

    async def slow(**kw):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1

        class R:
            output = adj.Judgement(**J)
        return R()
    monkeypatch.setattr(adj, "_run_agent_with_model", slow)
    await adj.adjudicate(inp("FINDINGS:\nA.", "- a"), [[C()] for _ in range(12)])
    assert peak <= adj.CONCURRENCY


def test_cap_brief_never_raises_a_brief_option():
    j = adj.cap_brief(adj.Judgement(**J), [C(detector="brief.option")])
    assert j.cls == "minor"
    assert adj.cap_brief(adj.Judgement(**J), [C()]).cls == "action"


def test_to_edit():
    assert adj.to_edit(adj.Judgement(**{**J, "edit_mode": "none"})) is None
    e = adj.to_edit(adj.Judgement(**{**J, "edit_after": ""}))
    assert e == Edit(mode="replace", find="a cyst", replace="a 14 mm cyst", after=None, section="FINDINGS")


async def test_reprepare_lowers_but_never_raises_brief(monkeypatch):
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(**J)))
    it = ReviewItem(key="k", report_id="r", run_id="u", lane="additions", detectors=["brief.option"], kind="option",
                    cls="minor", source_line="Sentence.")
    o = await adj.reprepare(inp("FINDINGS:\nA cyst.", "- a"), it)
    assert o.judgement.cls == "minor"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_adjudicator.py -q`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Create the prompt file**

Copy Plan 1's lab prompt verbatim:

Run: `mkdir -p src/rapid_reports_ai/review_engine/prompts && cp src/rapid_reports_ai/scripts/review_labs/prompts/adjudicator_v4.txt src/rapid_reports_ai/review_engine/prompts/adjudicator.txt`

If Plan 1 Task 0.3 has not landed yet, write the file with the exact `adjudicator_v4.txt` text from Plan 1, Task 0.3 Step 3. **Gate A owns this text.** When Gate A revises it, replace this file verbatim with the revised `adjudicator_v4.txt` and commit `chore(review-engine): adopt Gate A adjudicator prompt (L-5x)`.

- [ ] **Step 4: Write `adjudicator.py`**

```python
# src/rapid_reports_ai/review_engine/adjudicator.py
"""Adjudicator (spec §7): Qwen 3.8 27b with reasoning reads the whole case for one candidate group, decides class
and kind, and writes the smallest fix, in one call. Flat schema on purpose (L-50). Retries at temperature 0 repeat
the same output, so a failure becomes `minor` with no fix and is logged."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

from .. import report_reconcile as rc
from ..enhancement_utils import _run_agent_with_model
from .items import Candidate, Edit, ReviewInput, ReviewItem

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "adjudicator.txt"
MODEL = rc.QWEN
SETTINGS = {"temperature": 0, "max_tokens": 16384, "reasoning_effort": "medium"}
CONCURRENCY = 8     # spec §7: at most 8 concurrent calls per report
GROUP_CAP = 20      # spec §7: above 20 groups the overflow is minor with no fix
ADJ_TIMEOUT_S = 90.0


class Judgement(BaseModel):            # FLAT on purpose (L-50); any future list field decodes a JSON string
    cls: Literal["action", "minor", "info", "suppress"]
    kind: str
    label: str
    reason: str
    edit_mode: Literal["none", "replace", "insert", "upgrade", "remove"]
    edit_find: Optional[str] = None
    edit_replace: Optional[str] = None
    edit_after: Optional[str] = None
    edit_section: Optional[str] = None
    probe: Optional[str] = None


class Outcome(BaseModel):
    group: List[Candidate]
    judgement: Optional[Judgement] = None
    error: Optional[str] = None


def prompt() -> str:
    return PROMPT_PATH.read_text().strip()


KIND_TEXT = {
    "partial": "The report seems to cover this dictated line but leave out part of it.",
    "absent": "The report seems not to cover this dictated line at all.",
    "differs": "The report seems to say something different from this dictated line.",
    "coverage_check": "Whether the report carries this dictated line, as dictated, is unclear.",
    "laterality": "A side in this dictated line seems missing from the report.",
    "contradicted": "The dictation seems to contradict this report statement.",
    "unsupported": "This report statement seems not to be supported by the dictation or history.",
    "overstated": "This report statement seems more certain than the dictation.",
    "misattributed": "A measurement seems attached to a different structure than dictated.",
    "inconsistent": "This report statement seems internally inconsistent (modality wording or size word).",
    "grade": "A guideline classification may be assignable for this finding.",
    "characterise": "A guideline classification may need an input that is not described.",
    "threshold": "A guideline threshold may apply to this finding.",
    "follow_up": "The guideline may change the existing recommendation.",
    "option": "A point the radiologist may want to add.",
}


def render_candidate(c: Candidate) -> str:
    """One candidate as prompt text. An unsure Jev answer is named, never its leaning (§6.5)."""
    out = [f"- [{c.lane}/{c.kind}, detector {c.detector}] {KIND_TEXT.get(c.kind, '')}"]
    if c.line_text and c.lane == "coverage":
        out.append(f'  Dictated line: "{c.line_text}"')
    elif c.line_text:
        out.append(f'  Finding: "{c.line_text}"')
    if c.anchor:
        out.append(f'  Report statement: "{c.anchor.text}"')
    ev = c.evidence or {}
    if ev.get("jev_unsure"):
        out.append(f"  The detector question {ev['jev_unsure'].get('question')} was unsure here; read it fresh.")
    if ev.get("upgrade_target"):
        out.append(f'  Proposed sentence: "{ev.get("sentence")}". The report already covers this structure; '
                   "rewrite that sentence (edit_mode upgrade) rather than adding a second one.")
    elif ev.get("sentence"):
        out.append(f'  Proposed sentence: "{ev["sentence"]}"')
    for k in ("missing_detail", "numbers", "dates", "phrase", "dictated", "report", "number", "source_line", "word",
              "system", "grade", "parameter", "threshold", "significance", "modality", "timing", "indication", "text",
              "criteria"):
        if ev.get(k) not in (None, "", []):
            out.append(f"  {k}: {ev[k]}")
    return "\n".join(out)


def user_message(inp: ReviewInput, group: List[Candidate], report: Optional[str] = None) -> str:
    return ("FLAGS (one group, same place in the report):\n" + "\n".join(render_candidate(c) for c in group) +
            f"\n\nSTUDY TITLE: {inp.study_title or inp.scan_type}\n\nCLINICAL HISTORY:\n{inp.clinical_history or '(none)'}"
            f"\n\nDICTATION:\n{inp.artifacts.dictated_findings}\n\nREPORT:\n{report or inp.artifacts.report}")


def needs_judgement(group: List[Candidate]) -> bool:
    """Pre-classed brief options are not judged again (Principle 2), unless the gate was unsure about one."""
    return not all(c.preclassed and not (c.evidence or {}).get("jev_unsure") for c in group)


def _is_brief(group: List[Candidate]) -> bool:
    return any(c.detector == "brief.option" for c in group)


def cap_brief(j: Judgement, group: List[Candidate]) -> Judgement:
    """A brief option may be lowered (to suppress) but never raised to action (spec §6.4, confirmed 2026-10-03)."""
    return j.model_copy(update={"cls": "minor"}) if _is_brief(group) and j.cls == "action" else j


def to_edit(j: Judgement) -> Optional[Edit]:
    if j.edit_mode == "none":
        return None
    return Edit(mode=j.edit_mode, find=j.edit_find or None, replace=j.edit_replace or None,
                after=j.edit_after or None, section=j.edit_section or None)


async def judge(inp: ReviewInput, group: List[Candidate], report: Optional[str] = None) -> Outcome:
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=MODEL, output_type=Judgement, system_prompt=prompt(),
            user_prompt=user_message(inp, group, report), api_key="", model_settings=dict(SETTINGS)), ADJ_TIMEOUT_S)
        return Outcome(group=group, judgement=cap_brief(r.output, group))
    except Exception as e:  # noqa: BLE001 - one failed group never fails the run
        logger.warning("review engine: adjudicator failed (%s: %s)", type(e).__name__, str(e)[:200])
        return Outcome(group=group, error=f"{type(e).__name__}: {str(e)[:200]}")


async def adjudicate(inp: ReviewInput, groups: List[List[Candidate]]) -> List[Outcome]:
    sem = asyncio.Semaphore(CONCURRENCY)
    judged = [i for i, g in enumerate(groups) if needs_judgement(g)]
    overflow = set(judged[GROUP_CAP:])
    if overflow:
        logger.warning("review engine: %d group(s) over the cap of %d → minor, no fix", len(overflow), GROUP_CAP)

    async def one(i: int, g: List[Candidate]) -> Outcome:
        if i in overflow:
            return Outcome(group=g, error="overflow: over the group cap")
        if i not in judged:
            return Outcome(group=g)
        async with sem:
            return await judge(inp, g)
    return list(await asyncio.gather(*(one(i, g) for i, g in enumerate(groups))))


async def reprepare(inp: ReviewInput, item: ReviewItem, report: Optional[str] = None) -> Outcome:
    """One call for one item against the current text (spec §10.3, §12.4)."""
    lane = item.lane if item.lane != "chat" else "accuracy"
    cand = Candidate(lane=lane, kind=item.kind, section=item.section, anchor=item.anchor, line_text=item.source_line,
                     evidence={"previous_label": item.label}, detector=(item.detectors or ["reprepare"])[0])
    return await judge(inp, [cand], report)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_review_engine_adjudicator.py -q`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/review_engine/adjudicator.py src/rapid_reports_ai/review_engine/prompts/adjudicator.txt tests/test_review_engine_adjudicator.py
rcommit "feat(review-engine): adjudicator (flat Judgement, per-group call, caps, brief-option rules, reprepare)"
```

---

### Task 9: `verifier.py`, code guards, one Jev batch, and the probe loop

**Files:**
- Create: `src/rapid_reports_ai/review_engine/verifier.py`
- Test: `tests/test_review_engine_verifier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_verifier.py
"""Verifier (spec §8) and probe (spec §12.4): the fix is checked, never the reading."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import verifier as V
from rapid_reports_ai.review_engine.items import Edit, ReviewItem, Span

from review_engine_fakes import inp, jev

REPORT = "FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst."
SECTIONS = ["FINDINGS", "IMPRESSION"]


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("unstubbed Jev call")
    monkeypatch.setattr(rc, "_jev", boom)


def item(edit, kind="partial", probe="The FINDINGS section states the size of the kidney lesion.", section="FINDINGS"):
    return ReviewItem(key="k", report_id="r", run_id="u", lane="coverage", kind=kind, cls="action", edit=edit,
                      probe=probe, section=section, anchor=Span(start=0, end=1, text="x"))


def test_apply_edit_modes():
    assert "a 14 mm cyst" in V.apply_edit(REPORT, Edit(mode="replace", find="a cyst", replace="a 14 mm cyst"), SECTIONS)
    assert "liver" not in V.apply_edit(REPORT, Edit(mode="remove", find="The liver is normal."), SECTIONS)
    out = V.apply_edit(REPORT, Edit(mode="insert", after="The liver is normal.", replace="The spleen is normal."), SECTIONS)
    assert "The liver is normal. The spleen is normal. There is" in out
    out = V.apply_edit(REPORT, Edit(mode="insert", replace="Follow-up is suggested.", section="IMPRESSION"), SECTIONS)
    assert out.endswith("Left renal cyst. Follow-up is suggested.")
    assert V.apply_edit("normal normal", Edit(mode="replace", find="normal", replace="x"), []) is None


def test_guards():
    g = lambda e, kind="partial", d="cyst left kidney": V.guard_failures(REPORT, e, kind, d, "", SECTIONS, "FINDINGS")
    assert g(Edit(mode="replace", find="a cyst", replace="a 14 mm cyst")) == ["ungrounded_number"]
    assert g(Edit(mode="replace", find="a cyst", replace="a 14 mm cyst"), d="14 mm cyst left kidney") == []
    assert "ungrounded_side" in g(Edit(mode="replace", find="the left kidney", replace="the right kidney"))
    assert "remove_not_allowed" in g(Edit(mode="remove", find="The liver is normal."))
    assert g(Edit(mode="remove", find="The liver is normal."), kind="contradicted") == []
    assert "outside_section" in g(Edit(mode="replace", find="Left renal cyst.", replace="Left renal cyst, 14 mm."),
                                  d="14 mm left renal cyst")
    assert "duplicate" in g(Edit(mode="insert", replace="There is a cyst in the left kidney.", section="FINDINGS"))
    rep = "FINDINGS:\nNo free fluid. The liver is normal."
    assert "drops_negation" in V.guard_failures(rep, Edit(mode="replace", find="No free fluid.", replace="Free fluid."),
                                                "differs", "free fluid", "", ["FINDINGS"], "FINDINGS")


async def test_verify_addressed_unconfirmed_and_contradiction(monkeypatch):
    i = inp(REPORT, "- 14 mm cyst left kidney")
    ok = item(Edit(mode="replace", find="a cyst", replace="a 14 mm cyst"))
    unsure = item(Edit(mode="replace", find="Left renal cyst.", replace="Left renal cyst, 14 mm."), section="IMPRESSION")
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": 0.1}, "x1": {"noul": 0.1}, "a": {"noul": 0.9}}))
    await V.verify(i, [ok])
    assert ok.verified == {"code": True, "failed": [], "addressed": 0.9, "contra": 0.1, "unconfirmed": False}
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": 0.1}, "a": {"noul": 0.6}}))
    await V.verify(i, [unsure])
    assert unsure.verified["unconfirmed"] and unsure.edit is not None
    bad = item(Edit(mode="replace", find="a cyst", replace="a 14 mm cyst"))
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": 0.8}, "a": {"noul": 0.9}}))
    await V.verify(i, [bad])
    assert not bad.verified["code"] and "fix_contradicts_dictation" in bad.verified["failed"] and bad.edit is None


async def test_failed_guard_removes_edit_keeps_class(monkeypatch):
    it = item(Edit(mode="replace", find="pancreas", replace="x"))
    await V.verify(inp(REPORT, "- a"), [it])
    assert it.edit is None and it.cls == "action" and it.verified["failed"] == ["anchor_not_unique"]


async def test_probe(monkeypatch):
    i = inp(REPORT, "- 14 mm cyst left kidney\n- Free fluid")
    a = item(Edit(mode="replace", find="a cyst", replace="a 14 mm cyst"))
    a.anchor = Span(start=0, end=6, text="a cyst")
    b = item(None, probe="The FINDINGS section states the liver.")
    b.anchor = Span(start=0, end=6, text="The liver is normal.")
    c = item(None, probe="p3")
    c.anchor = Span(start=0, end=6, text="gone text")
    new = REPORT.replace("a cyst", "a 14 mm cyst") + " No free fluid."
    start = new.index("No free fluid.")
    monkeypatch.setattr(rc, "_jev", jev({"p0": {"noul": 0.9}, "p1": {"noul": 0.6}, "p2": {"noul": 0.1},
                                         "x0": {"noul": 0.8}}))
    res = await V.probe(i, [a, b, c], new, [[start, len(new)]])
    assert res["addressed"] == [a.id] and set(res["reprepare"]) == {b.id, c.id}
    assert res["contradictions"] and res["contradictions"][0].kind == "contradicted"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_verifier.py -q`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `verifier.py`**

```python
# src/rapid_reports_ai/review_engine/verifier.py
"""Verifier (spec §8): code guards, then one Jev batch on each fix's post-edit text. A failed check removes the
edit and keeps the item's class. An unsure `addressed` keeps the fix and marks it unconfirmed (§6.5). Also the live
probe loop's one-shot check (spec §12.4)."""
from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Optional, Tuple

from .. import report_reconcile as rc
from ..report_review import CONTRA_FLAG, JEV_TIMEOUT_S, Q_CONTRA, _NEGATION, _restates, is_negative, section_spans
from .alignment import align, numbers, section_models
from .items import Candidate, Edit, ReviewInput, ReviewItem, Span

ADDRESSED_OK = 0.8   # spec §8; confirmed or re-set in Gate E
UNSURE_LO = 0.5      # §6.5 / §12.4: 0.5–0.8 is the unsure band
_SIDE = re.compile(r"\b(left|right|bilateral)\b", re.I)


def section_bounds(report: str, sections: List[str], name: Optional[str]) -> Optional[Tuple[int, int]]:
    if not name or not sections:
        return None
    for sec, a, b in section_spans(report, section_models(sections)):
        if sec.name.lower() == name.lower():
            return a, b
    return None


def _once(text: str, needle: Optional[str]) -> bool:
    return bool(needle) and text.count(needle) == 1


def apply_edit(report: str, edit: Edit, sections: List[str]) -> Optional[str]:
    if edit.mode in ("replace", "upgrade") and _once(report, edit.find) and edit.replace is not None:
        return report.replace(edit.find, edit.replace, 1)
    if edit.mode == "remove" and _once(report, edit.find):
        return re.sub(r"[ \t]{2,}", " ", report.replace(edit.find, "", 1)).replace(" \n", "\n")
    if edit.mode == "insert" and edit.replace:
        if edit.after:
            if not _once(report, edit.after):
                return None
            i = report.index(edit.after) + len(edit.after)
            return report[:i] + " " + edit.replace.strip() + report[i:]
        b = section_bounds(report, sections, edit.section)
        if b is None:
            return None
        a, e = b
        body = report[a:e].rstrip()
        pos = a + len(body)
        return report[:pos] + " " + edit.replace.strip() + report[pos:]
    return None


def _edit_pos(report: str, edit: Edit) -> Optional[int]:
    needle = edit.find or edit.after
    return report.find(needle) if needle and needle in report else None


def guard_failures(report: str, edit: Edit, kind: str, dictation: str, history: str, sections: List[str],
                   item_section: Optional[str]) -> List[str]:
    if apply_edit(report, edit, sections) is None:
        return ["anchor_not_unique"]
    fails = []
    source = f"{dictation}\n{history}"
    new, old = edit.replace or "", edit.find or ""
    if numbers(new) - numbers(old) - numbers(source):
        fails.append("ungrounded_number")
    added = {s.lower() for s in _SIDE.findall(new)} - {s.lower() for s in _SIDE.findall(old)}
    if added - {s.lower() for s in _SIDE.findall(source)}:
        fails.append("ungrounded_side")
    # L-47: an edit never drops a negation, except the sanctioned code removal of a contradicted negative
    # (a negative-list item dropped from its line arrives as a line-level replace).
    if edit.mode in ("replace", "upgrade") and kind != "contradicted" and \
            len(_NEGATION.findall(old)) > len(_NEGATION.findall(new)):
        fails.append("drops_negation")
    if edit.mode == "remove" and kind != "contradicted":
        fails.append("remove_not_allowed")
    bounds = section_bounds(report, sections, item_section)
    pos = _edit_pos(report, edit)
    if bounds and pos is not None and not (bounds[0] <= pos < bounds[1]):
        fails.append("outside_section")
    if edit.mode == "insert":
        target = section_bounds(report, sections, edit.section or item_section)
        text = report[target[0]:target[1]] if target else report
        if _restates(edit.replace or "", text):
            fails.append("duplicate")
    return fails


def _changed_text(after: str, edit: Edit) -> str:
    key = (edit.replace or "").strip()
    if not key:
        return ""
    for s in re.split(r"(?<=[.;])\s+|\n+", after):
        if key[:40] in s:
            return s.strip()
    return key


async def _ask(state: str, qs: dict) -> dict:
    return await asyncio.wait_for(rc._jev(state, qs), JEV_TIMEOUT_S) if qs else {}


def _dict_state(inp: ReviewInput) -> str:
    return f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{inp.artifacts.dictated_findings}"


def _f(ans, k) -> Optional[float]:
    try:
        return float(ans[k]["noul"])
    except Exception:
        return None


async def verify(inp: ReviewInput, items: List[ReviewItem], report: Optional[str] = None) -> None:
    """Sets item.verified = {code, failed, addressed, contra, unconfirmed}; removes edits that fail."""
    report = report or inp.artifacts.report
    sections = inp.artifacts.sections
    todo: List[Tuple[ReviewItem, str]] = []
    for it in items:
        if it.edit is None:
            continue
        fails = guard_failures(report, it.edit, it.kind, inp.artifacts.dictated_findings, inp.clinical_history,
                               sections, it.section)
        it.verified = {"code": not fails, "failed": fails, "addressed": None, "contra": None, "unconfirmed": False}
        if fails:
            it.edit = None
        else:
            todo.append((it, apply_edit(report, it.edit, sections)))
    if not todo:
        return
    contra_qs = {f"x{k}": {"type": "noul", "instructions": Q_CONTRA + _changed_text(after, it.edit)}
                 for k, (it, after) in enumerate(todo) if _changed_text(after, it.edit)}
    probe_jobs = [_ask(f"REPORT:\n{after}", {"a": {"type": "noul", "instructions": it.probe}}) if it.probe else None
                  for it, after in todo]
    results = await asyncio.gather(_ask(_dict_state(inp), contra_qs),
                                   *[j for j in probe_jobs if j is not None], return_exceptions=True)
    contra = results[0] if not isinstance(results[0], BaseException) else {}
    probes = iter(results[1:])
    for k, (it, _) in enumerate(todo):
        v = it.verified
        if isinstance(results[0], BaseException):
            v["jev_error"] = type(results[0]).__name__
        v["contra"] = _f(contra, f"x{k}")
        if it.probe:
            ans = next(probes)
            v["addressed"] = None if isinstance(ans, BaseException) else _f(ans, "a")
            if v["addressed"] is not None:
                v["unconfirmed"] = UNSURE_LO <= v["addressed"] < ADDRESSED_OK
        if v["contra"] is not None and v["contra"] >= CONTRA_FLAG:
            v["code"] = False
            v["failed"].append("fix_contradicts_dictation")
            it.edit = None


async def probe(inp: ReviewInput, items: List[ReviewItem], text: str, changed_ranges: List[List[int]]) -> Dict:
    """One check of the current text (spec §12.4): each open item's probe, plus contradiction on the changed clauses.
    Returns item ids addressed (≥ 0.8) and to re-prepare (0.5–0.8, or anchor lost), plus new contradiction candidates."""
    probe_qs = {f"p{k}": {"type": "noul", "instructions": it.probe} for k, it in enumerate(items) if it.probe}
    al = align(text, inp.artifacts.dictated_findings, inp.clinical_history, inp.artifacts.sections)
    changed = [c for c in al.clauses
               if any(c.start < b and a < c.end for a, b in changed_ranges)] if changed_ranges else []
    contra_qs = {f"x{k}": {"type": "noul", "instructions": Q_CONTRA + c.text} for k, c in enumerate(changed)}
    pa, ca = await asyncio.gather(_ask(f"REPORT:\n{text}", probe_qs), _ask(_dict_state(inp), contra_qs),
                                  return_exceptions=True)
    pa = {} if isinstance(pa, BaseException) else pa
    ca = {} if isinstance(ca, BaseException) else ca
    addressed, reprepare = [], []
    for k, it in enumerate(items):
        p = _f(pa, f"p{k}")
        if p is not None and p >= ADDRESSED_OK:
            addressed.append(it.id)
        elif (p is not None and p >= UNSURE_LO) or (it.anchor and it.anchor.text not in text):
            reprepare.append(it.id)
    contradictions = []
    for k, c in enumerate(changed):
        s = _f(ca, f"x{k}")
        if s is not None and s >= CONTRA_FLAG:
            neg = is_negative(c.text)
            contradictions.append(Candidate(
                lane="accuracy", kind="contradicted", section=c.section,
                anchor=Span(start=c.start, end=c.end, text=text[c.start:c.end]),
                evidence={"negative": neg, "score": s}, code_fix=neg,
                proposed=Edit(mode="remove", find=text[c.start:c.end]) if neg else None, detector="loop.contradiction"))
    return {"addressed": addressed, "reprepare": reprepare, "contradictions": contradictions}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_review_engine_verifier.py -q`
Expected: 5 passed. The guard tests assume `section_spans` places "Left renal cyst." in IMPRESSION and the cyst sentence in FINDINGS. If a guard returns an unexpected extra failure, print it and fix the guard, not the test's intent.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/review_engine/verifier.py tests/test_review_engine_verifier.py
rcommit "feat(review-engine): verifier (code guards, Jev addressed/contradiction, unconfirmed) and probe check"
```

---

### Task 10: `engine.py`, orchestration, flags and the Gate D shadow log

**Files:**
- Create: `src/rapid_reports_ai/review_engine/engine.py`
- Modify: `src/rapid_reports_ai/report_review.py` (`run_quality_check`: record `pre_edit_report` when the engine is not `off`)
- Modify: `tests/conftest.py:110-111` (`_QUALITY_MODULES` gains `"test_review_engine_shadow"`)
- Test: `tests/test_review_engine_engine.py`, `tests/test_review_engine_shadow.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_engine_engine.py
"""Engine orchestration (spec §4, §10.4): align → lanes → merge → adjudicate → verify; flags; failure isolation."""
import asyncio

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.database.models import Report
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, store

from review_engine_fakes import inp, jev, model

REPORT = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst with a thin septation"
J = adj.Judgement(cls="minor", kind="partial", label="Septation missing", reason="r", edit_mode="replace",
                  edit_find="A 14 mm left renal cyst.", edit_replace="A 14 mm left renal cyst with a thin septation.",
                  edit_section="FINDINGS", probe="The FINDINGS section describes the renal cyst's internal structure.")
OPT = [{"id": "o1", "kind": "recommendation", "section": "IMPRESSION", "sentence": "Ultrasound follow-up is suggested.",
        "reason": ""}]


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev({"i0": {"choice": "partial", "probabilities": {"partial": 0.8, "stated": 0.2}},
                                         "g0": {"noul": 0.05}, "a": {"noul": 0.9}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(J))


def test_flags(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    assert engine.mode() == "off"
    monkeypatch.setenv("RR_REVIEW_ENGINE", "Shadow")
    assert engine.mode() == "shadow" and not engine.rail_enabled()
    monkeypatch.setenv("RR_REVIEW_ENGINE", "bogus")
    assert engine.mode() == "off"
    monkeypatch.setenv("RR_REVIEW_LANES", "coverage, additions,nope")
    assert engine.lanes_enabled() == ["coverage", "additions"]
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.setenv("RR_REVIEW_RAIL", "0")
    assert not engine.rail_enabled()


async def test_run_review_end_to_end():
    res = await engine.run_review(inp(REPORT, DICT, options=OPT), run_id="00000000-0000-0000-0000-0000000000aa")
    kinds = {(i.lane, i.kind, i.cls) for i in res.items}
    assert ("coverage", "partial", "minor") in kinds and ("additions", "option", "minor") in kinds
    cov = next(i for i in res.items if i.lane == "coverage")
    assert cov.edit and cov.verified["code"] and cov.source_line == DICT[2:] and cov.engine_version == engine.ENGINE_VERSION
    opt = next(i for i in res.items if i.lane == "additions")
    assert opt.detectors == ["brief.option"] and opt.edit.mode == "insert" and opt.probe.startswith(rc.Q_CONVEYS)
    assert res.run["lanes"] == {"coverage": "done", "accuracy": "done", "additions": "done"}
    assert "total" in res.run["timings_ms"]


async def test_lane_failure_is_isolated(monkeypatch):
    class Slow:
        name = "coverage"

        async def candidates(self, inp_, ctx):
            await asyncio.sleep(1)
            return []
    monkeypatch.setitem(engine.LANES, "coverage", Slow())
    monkeypatch.setattr(engine, "LANE_TIMEOUT_S", 0.01)
    res = await engine.run_review(inp(REPORT, DICT), run_id="00000000-0000-0000-0000-0000000000ab")
    assert res.run["lanes"]["coverage"] == "failed" and res.run["lanes"]["accuracy"] == "done"
    assert "coverage" in res.run["errors"]


async def test_adjudicator_failure_becomes_minor_no_fix(monkeypatch):
    async def bad(**kw):
        raise ValueError("schema")
    monkeypatch.setattr(adj, "_run_agent_with_model", bad)
    res = await engine.run_review(inp(REPORT, DICT), run_id="00000000-0000-0000-0000-0000000000ac")
    cov = next(i for i in res.items if i.lane == "coverage")
    assert cov.cls == "minor" and cov.edit is None and "schema" in cov.reason


async def test_gate_d_log_records_option_a_and_b(monkeypatch):
    pre = REPORT.replace(" A 14 mm left renal cyst.", "")
    qc = {"flags": [{"kind": "omission", "text": "14 mm left renal cyst with a thin septation", "score": 0.1}],
          "kept_dictated_negative": []}
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="action", kind="absent", label="Cyst missing", reason="r", edit_mode="insert",
        edit_after="The liver is normal.", edit_replace="A 14 mm left renal cyst with a thin septation.",
        edit_section="FINDINGS", probe="The FINDINGS section reports the renal cyst.")))
    log = await engine.gate_d_log(inp(REPORT, DICT, quality_check=qc, pre_edit=pre))
    assert log["edits"][0]["type"] == "insertion" and log["edits"][0]["option_a_pre_apply"] is True
    assert log["edits"][0]["option_b"] == "one-click action"


async def test_run_and_store(monkeypatch, db_session, test_user):
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               input_data={"variables": {"FINDINGS": DICT, "SCAN_TYPE": "CT abdomen", "CLINICAL_HISTORY": ""}},
               candidate_reports=[{"content": REPORT, "sections": ["FINDINGS", "IMPRESSION"], "options": OPT,
                                   "quality_check": {"flags": []}}])
    db_session.add(r)
    db_session.commit()
    monkeypatch.setattr(engine, "_with_session", lambda fn, *a, **k: fn(db_session, *a, **k))
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    run_id = await engine.run_and_store(str(r.id))
    assert store.latest_run(db_session, str(r.id))["id"] == run_id
    assert {i.lane for i in store.list_items(db_session, str(r.id))} >= {"coverage", "additions"}


def test_input_from_parts():
    i = engine.input_from_parts("00000000-0000-0000-0000-000000000001", "templated",
                                {"variables": {"FINDINGS": "- a", "CLINICAL_HISTORY": "h"}, "extracted_scan_type": "MRI knee"},
                                {"content": "FINDINGS:\nA.", "sections": ["FINDINGS"],
                                 "quality_check": {"pre_edit_report": "FINDINGS:\nB."}},
                                {"guidelines": [{"finding": "x"}]})
    assert i.pathway == "templated" and i.scan_type == "MRI knee" and i.clinical_history == "h"
    assert i.synthesis == {"guidelines": [{"finding": "x"}]} and i.pre_edit_report == "FINDINGS:\nB."
    assert engine.input_from_parts("x", "quick", {}, {"content": "", "error": "boom"}, None) is None
```

```python
# tests/test_review_engine_shadow.py
"""run_quality_check records the pre-edit report for the Gate D shadow log only when the engine is not off."""
import pytest

from rapid_reports_ai import report_review as rr


@pytest.fixture
def stubbed(monkeypatch):
    async def fake_check(report, findings, scan_type, options, **kw):
        return rr.CheckResult(flags=[rr.Flag(kind="omission", text="Small left effusion", score=0.1)], n_items=1)

    async def fake_insert(report, findings, items, **kw):
        return rr.RepairResult(report=report + " Small left effusion.", applied=1)
    monkeypatch.setattr(rr, "check", fake_check)
    monkeypatch.setattr(rr, "insert_findings", fake_insert)


async def test_pre_edit_report_recorded_in_shadow(monkeypatch, stubbed):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    report, _, tel = await rr.run_quality_check("FINDINGS:\nNormal.", "- Small left effusion", "CT", [])
    assert tel["pre_edit_report"] == "FINDINGS:\nNormal." and report.endswith("Small left effusion.")


async def test_pre_edit_report_absent_when_off(monkeypatch, stubbed):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    _, _, tel = await rr.run_quality_check("FINDINGS:\nNormal.", "- Small left effusion", "CT", [])
    assert "pre_edit_report" not in tel
```

- [ ] **Step 2: Add `test_review_engine_shadow` to `_QUALITY_MODULES`**

```python
_QUALITY_MODULES = ("test_quick_report_quality", "test_report_review", "test_template_pipeline",
                    "test_golden_quick_pipeline", "test_review_engine_shadow")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_review_engine_engine.py tests/test_review_engine_shadow.py -q`
Expected: FAIL (`ImportError: engine`; `KeyError: 'pre_edit_report'`).

- [ ] **Step 4: Record `pre_edit_report` in `run_quality_check`**

In `src/rapid_reports_ai/report_review.py`, at the end of `run_quality_check`, just before `return report, options, tel`:

```python
    # Gate D shadow log (review engine spec §9): the report before today's automatic edits, kept only while the
    # review engine runs (shadow or live) and only when an edit was applied.
    if os.environ.get("RR_REVIEW_ENGINE", "off").strip().lower() in ("shadow", "live") and report != original:
        tel["pre_edit_report"] = original
```

- [ ] **Step 5: Write `engine.py`**

```python
# src/rapid_reports_ai/review_engine/engine.py
"""Review engine orchestration (spec §4, §10.4): align → shared Jev pass → lanes (concurrent, each isolated) →
merge → adjudicate → verify → store. RR_REVIEW_ENGINE=off|shadow|live; in shadow the engine runs in a background
task after the candidate is saved and nothing reaches the client."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel

from ..report_review import is_negative
from . import adjudicator, jev_pass, store, verifier
from .alignment import align
from .checks import run_checks
from .items import Candidate, ReviewInput, ReviewItem, Span, item_key, merge, text_hash
from .lanes import LaneContext
from .lanes.accuracy import AccuracyLane
from .lanes.additions import AdditionsLane
from .lanes.coverage import CoverageLane

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"
LANE_TIMEOUT_S = 20.0
OPTIONS_WAIT_S = 90.0          # templated: wait for the background options job before reviewing
LANES = {"coverage": CoverageLane(), "accuracy": AccuracyLane(), "additions": AdditionsLane()}


def mode() -> str:
    v = os.environ.get("RR_REVIEW_ENGINE", "off").strip().lower()
    return v if v in ("off", "shadow", "live") else "off"


def lanes_enabled() -> List[str]:
    raw = os.environ.get("RR_REVIEW_LANES", "coverage,accuracy,additions")
    return [x.strip() for x in raw.split(",") if x.strip() in LANES]


def rail_enabled() -> bool:
    return mode() == "live" and os.environ.get("RR_REVIEW_RAIL", "1").strip() != "0"


class ReviewResult(BaseModel):
    run: dict
    items: List[ReviewItem]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_label(c: Candidate) -> str:
    if c.evidence.get("sentence"):
        return c.evidence["sentence"][:80]
    text = c.line_text or (c.anchor.text if c.anchor else "")
    return f"{c.kind.replace('_', ' ')}: {text}"[:80]


def build_item(inp: ReviewInput, run_id: str, o: adjudicator.Outcome) -> ReviewItem:
    g = o.group
    first = g[0]
    h = text_hash(inp.artifacts.report)
    anchor = next((c.anchor for c in g if c.anchor), None)
    if anchor is not None:
        anchor = anchor.model_copy(update={"text_hash": h})
    line_text = next((c.line_text for c in g if c.line_text and c.lane == "coverage"), None) or \
        next((c.line_text for c in g if c.line_text), None)
    code_fix = next((c for c in g if c.code_fix and c.proposed), None)
    probe = next((c.probe for c in g if c.probe), None)
    if o.judgement is not None:
        j = o.judgement
        cls, kind, label, reason = j.cls, j.kind or first.kind, j.label, j.reason
        edit = code_fix.proposed if code_fix else adjudicator.to_edit(j)
        probe = j.probe or probe
    elif o.error is not None:            # validation failure or overflow (spec §7)
        cls, kind, label, edit = "minor", first.kind, _default_label(first), None
        reason = f"Not reviewed automatically ({o.error[:120]})."
    else:                                # pre-classed brief option, not judged again
        cls, kind, label, edit = first.preclassed or "minor", first.kind, _default_label(first), first.proposed
        reason = first.evidence.get("reason") or ""
    section = next((c.section for c in g if c.section), None)
    return ReviewItem(key=item_key(first.lane, kind, anchor.text if anchor else (line_text or label)),
                      report_id=inp.report_id, run_id=run_id, lane=first.lane,
                      detectors=sorted({c.detector for c in g}), kind=kind, cls=cls, section=section, anchor=anchor,
                      label=label, reason=reason, edit=edit, probe=probe,
                      citation=next((c.citation for c in g if c.citation), None), source_line=line_text,
                      history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h,
                                "detail": {"detectors": sorted({c.detector for c in g})}}],
                      engine_version=ENGINE_VERSION)


async def run_review(inp: ReviewInput, run_id: str) -> ReviewResult:
    t0 = time.monotonic()
    timings: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    a = inp.artifacts
    al = align(a.report, a.dictated_findings, inp.clinical_history, a.sections)
    checks = run_checks(a.report, a.dictated_findings, inp.clinical_history, inp.scan_type, al, inp.study_title)
    names = lanes_enabled()
    jp = None
    if {"coverage", "accuracy"} & set(names):
        t = time.monotonic()
        jp = await jev_pass.run(inp, a.report)
        timings["jev_ms"] = int((time.monotonic() - t) * 1000)
        for k in ("contra_error", "omit_error"):
            if getattr(jp, k):
                errors[f"jev_{k}"] = getattr(jp, k)
    ctx = LaneContext(alignment=al, jev=jp, checks=checks)

    async def one(name: str):
        return await asyncio.wait_for(LANES[name].candidates(inp, ctx), LANE_TIMEOUT_S)
    t = time.monotonic()
    results = await asyncio.gather(*(one(n) for n in names), return_exceptions=True)
    timings["lanes_ms"] = int((time.monotonic() - t) * 1000)
    lanes = {n: "skipped" for n in LANES}
    cands: List[Candidate] = []
    for n, r in zip(names, results):
        if isinstance(r, BaseException):
            lanes[n] = "failed"
            errors[n] = f"{type(r).__name__}: {str(r)[:200]}"
            logger.warning("review engine: lane %s failed (%s)", n, type(r).__name__)
        else:
            lanes[n] = "done"
            cands += r
    t = time.monotonic()
    outcomes = await adjudicator.adjudicate(inp, merge(cands))
    timings["adjudicator_ms"] = int((time.monotonic() - t) * 1000)
    items = [build_item(inp, run_id, o) for o in outcomes]
    t = time.monotonic()
    await verifier.verify(inp, [i for i in items if i.cls != "suppress"])
    timings["verifier_ms"] = int((time.monotonic() - t) * 1000)
    timings["total"] = int((time.monotonic() - t0) * 1000)
    errors.update({f"adjudicator_{k}": o.error for k, o in enumerate(outcomes) if o.error})
    run = {"lanes": lanes, "timings_ms": timings, "errors": errors,
           "cost": {"groups": len(outcomes), "adjudicated": sum(1 for o in outcomes if o.judgement or o.error),
                    "candidates": len(cands)}}
    return ReviewResult(run=run, items=items)


async def gate_d_log(inp: ReviewInput) -> Optional[dict]:
    """What options A and B (spec §9) would have done with today's automatic edits, judged on the pre-edit report."""
    qc = inp.artifacts.quality_check or {}
    pre = inp.pre_edit_report
    if not pre:
        return None
    kept = {k.get("text") for k in qc.get("kept_dictated_negative") or []}
    pre_inp = inp.model_copy(update={"artifacts": inp.artifacts.model_copy(update={"report": pre})})
    entries = []
    for f in qc.get("flags") or []:
        if f.get("kind") == "omission":
            cand = Candidate(lane="coverage", kind="absent", line_text=f["text"], detector="jev.classify_first")
            etype = "insertion"
        elif f.get("kind") == "contradiction" and is_negative(f["text"]) and f["text"] not in kept:
            i = pre.find(f["text"])
            anchor = Span(start=i, end=i + len(f["text"]), text=f["text"]) if i >= 0 else None
            cand = Candidate(lane="accuracy", kind="contradicted", anchor=anchor, evidence={"negative": True},
                             detector="jev.contradiction")
            etype = "removal"
        else:
            continue
        o = await adjudicator.judge(pre_inp, [cand])
        item = build_item(pre_inp, "gate-d", o)
        if item.cls != "suppress":
            await verifier.verify(pre_inp, [item])
        v = item.verified or {}
        ok = item.cls == "action" and item.edit is not None and v.get("code") and not v.get("unconfirmed")
        ok = bool(ok and ((etype == "insertion" and item.kind == "absent" and item.edit.mode == "insert")
                          or (etype == "removal" and item.edit.mode == "remove")))
        entries.append({"type": etype, "text": f["text"], "cls": item.cls, "kind": item.kind,
                        "edit_mode": item.edit.mode if item.edit else None, "verified": item.verified,
                        "option_a_pre_apply": ok, "option_b": "one-click action" if item.cls == "action" else item.cls})
    return {"edits": entries}


# ── loading and scheduling ──────────────────────────────────────────────────

def input_from_parts(report_id: str, report_type: str, input_data: Optional[dict], cand: Optional[dict],
                     enhancement_json: Optional[dict]) -> Optional[ReviewInput]:
    from ..generation_artifacts import GenerationArtifacts
    cand = cand or {}
    if cand.get("error") or not cand.get("content"):
        return None
    data = input_data or {}
    v = data.get("variables") or {}
    findings = v.get("FINDINGS") or ""
    guidelines = (enhancement_json or {}).get("guidelines")
    return ReviewInput(report_id=report_id, pathway="templated" if report_type == "templated" else "quick",
                       artifacts=GenerationArtifacts.from_candidate(cand, findings),
                       clinical_history=v.get("CLINICAL_HISTORY") or "",
                       scan_type=v.get("SCAN_TYPE") or data.get("extracted_scan_type") or "",
                       study_title=v.get("SCAN_TYPE") or data.get("extracted_scan_type"),
                       synthesis={"guidelines": guidelines} if guidelines else None,
                       pre_edit_report=(cand.get("quality_check") or {}).get("pre_edit_report"))


def _session():
    from ..database.connection import SessionLocal
    return SessionLocal()


def _with_session(fn, *a, **k):
    db = _session()
    try:
        return fn(db, *a, **k)
    finally:
        db.close()


def _load_row(db, report_id: str):
    import uuid as _uuid

    from ..database.models import Report
    row = db.get(Report, _uuid.UUID(str(report_id)))
    if row is None:
        return None
    cand = (row.candidate_reports or [None])[0] or {}
    return {"report_type": row.report_type, "input_data": row.input_data, "cand": dict(cand),
            "enhancement_json": row.enhancement_json}


async def load_input(report_id: str, text: Optional[str] = None) -> Optional[ReviewInput]:
    deadline = time.monotonic() + OPTIONS_WAIT_S
    while True:
        row = await asyncio.to_thread(_with_session, _load_row, report_id)
        if row is None:
            return None
        if row["cand"].get("options_status") != "pending" or time.monotonic() > deadline:
            break
        await asyncio.sleep(3)
    cand = row["cand"]
    if text is not None:
        cand = {**cand, "content": text}
    return input_from_parts(report_id, row["report_type"], row["input_data"], cand, row["enhancement_json"])


async def run_and_store(report_id: str, text: Optional[str] = None) -> Optional[str]:
    """Run the engine over a saved report and store the run and its items. Never raises."""
    try:
        inp = await load_input(report_id, text)
        if inp is None:
            return None
        m = mode()
        run_id = await asyncio.to_thread(_with_session, store.create_run, report_id, m, ENGINE_VERSION, inp.pathway)
        try:
            res = await run_review(inp, run_id)
            shadow = await gate_d_log(inp) if m == "shadow" else None
        except Exception as e:  # noqa: BLE001
            logger.warning("review engine run failed for %s (%s: %s)", report_id, type(e).__name__, str(e)[:200])
            await asyncio.to_thread(_with_session, store.finish_run, run_id, {}, {}, {},
                                    {"engine": f"{type(e).__name__}: {str(e)[:200]}"})
            return run_id
        await asyncio.to_thread(_with_session, store.save_items, res.items)
        await asyncio.to_thread(_with_session, store.finish_run, run_id, res.run["lanes"], res.run["timings_ms"],
                                res.run["cost"], res.run["errors"], shadow)
        return run_id
    except Exception as e:  # noqa: BLE001 - the engine never affects the report path
        logger.warning("review engine failed for %s (%s: %s)", report_id, type(e).__name__, str(e)[:200])
        return None


_REVIEW_TASKS: "set[asyncio.Task]" = set()


def schedule_review(report_id: Optional[str], text: Optional[str] = None) -> Optional["asyncio.Task"]:
    """Fire-and-forget review of a saved report (held so it is not garbage-collected mid-flight). No-op when off."""
    if mode() == "off" or not report_id:
        return None
    task = asyncio.create_task(run_and_store(str(report_id), text))
    _REVIEW_TASKS.add(task)
    task.add_done_callback(_REVIEW_TASKS.discard)
    return task
```

- [ ] **Step 5b: Fix the shadow-log call order**

`run_and_store` must compute the shadow log **only** in shadow mode. The code above already does this (`shadow = await gate_d_log(inp) if m == "shadow" else None`). Don't move it into `run_review`, whose result the live path will later return synchronously.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_engine_engine.py tests/test_review_engine_shadow.py tests/test_report_review.py -q`
Expected: all pass. `test_report_review.py` must stay green, because the new `run_quality_check` lines change nothing when `RR_REVIEW_ENGINE` is unset.

- [ ] **Step 7: Commit**

```bash
git add src/rapid_reports_ai/review_engine/engine.py src/rapid_reports_ai/report_review.py tests/conftest.py tests/test_review_engine_engine.py tests/test_review_engine_shadow.py
rcommit "feat(review-engine): orchestration, flags, failure isolation, Gate D shadow log, background scheduling"
```

---

### Task 11: shadow wiring after the candidate is saved

**Files:**
- Modify: `src/rapid_reports_ai/quick_report_api.py` (after `create_quick_report_with_candidates(...)`, before the `done` event)
- Modify: `src/rapid_reports_ai/main.py` (templated generate, after `tp.schedule_options(...)`)
- Test: `tests/test_review_engine_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_wiring.py
"""Shadow wiring (spec §10.4): scheduled after the candidate is saved, never on the report path, off by default."""
import asyncio
import inspect

from rapid_reports_ai import main as main_mod
from rapid_reports_ai import quick_report_api
from rapid_reports_ai.review_engine import engine


def test_schedule_review_off_by_default(monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    assert engine.schedule_review("r1") is None


async def test_schedule_review_in_shadow(monkeypatch):
    seen = []

    async def fake(report_id, text=None):
        seen.append(report_id)
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(engine, "run_and_store", fake)
    t = engine.schedule_review("r1")
    await t
    assert seen == ["r1"] and t not in engine._REVIEW_TASKS


def test_quick_path_schedules_after_save():
    src = inspect.getsource(quick_report_api)
    save = src.index("report_row = create_quick_report_with_candidates(")
    sched = src.index("schedule_review(str(report_row.id))")
    done = src.index('"done",', save)
    assert save < sched < done
    assert "review engine not scheduled" in src[sched - 300: sched + 300]


def test_templated_path_schedules_after_save():
    src = inspect.getsource(main_mod.generate_report_from_template)
    assert src.index("tp.schedule_options(") < src.index("review_engine_schedule(report_id)")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_wiring.py -q`
Expected: the two wiring tests FAIL (`ValueError: substring not found`). The schedule tests pass.

- [ ] **Step 3: Wire the quick path**

In `quick_report_api.py`, add this right after the `report_row = create_quick_report_with_candidates(...)` call and before the `logger.info("[SSE] yielding done event ...")`:

```python
            # Review engine (spec §10.4): shadow runs in the background on the saved candidate; the report path and
            # the client are untouched. Off unless RR_REVIEW_ENGINE is set.
            try:
                from .review_engine.engine import schedule_review
                schedule_review(str(report_row.id))
            except Exception as e:  # the review engine never touches the report path
                logger.warning("review engine not scheduled (%s: %s)", type(e).__name__, e)
```

- [ ] **Step 4: Wire the templated path**

In `main.py`, add to the imports block near `from . import template_pipeline as tp`:

```python
from .review_engine.engine import schedule_review as review_engine_schedule
```

In `generate_report_from_template`, directly after the `tp.schedule_options(report_id, options_job, ...)` block:

```python
        # Review engine (spec §10.4): background review of the saved candidate; it waits for the options job itself.
        if report_id and mirror_candidate is not None:
            try:
                review_engine_schedule(report_id)
            except Exception as e:  # never affects the report
                logger.warning("review engine not scheduled (%s: %s)", type(e).__name__, e)
```

- [ ] **Step 5: Run the tests to verify they pass, plus the generate-path suites**

Run: `.venv/bin/python -m pytest tests/test_review_engine_wiring.py tests/test_report_path_split.py tests/test_golden_quick_pipeline.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/quick_report_api.py src/rapid_reports_ai/main.py tests/test_review_engine_wiring.py
rcommit "feat(review-engine): schedule shadow review after the quick and templated candidates are saved"
```

---

### Task 12: the endpoints

**Files:**
- Create: `src/rapid_reports_ai/review_engine/api.py`
- Modify: `src/rapid_reports_ai/main.py` (mount the router next to `quick_report_router`)
- Test: `tests/test_review_engine_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_engine_api.py
"""Review endpoints (spec §10.3): owner-scoped; probe/reprepare/rerun need the engine on."""
import uuid

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.database.models import Report, User
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, store
from rapid_reports_ai.review_engine.items import Edit, ReviewItem, Span

from review_engine_fakes import jev, model

REPORT = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst with a thin septation"


@pytest.fixture
def seeded(db_session, test_user):
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               input_data={"variables": {"FINDINGS": DICT, "SCAN_TYPE": "CT abdomen"}},
               candidate_reports=[{"content": REPORT, "sections": ["FINDINGS", "IMPRESSION"], "options": []}])
    db_session.add(r)
    db_session.commit()
    rid = str(r.id)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = ReviewItem(key="k1", report_id=rid, run_id=run_id, lane="coverage", detectors=["jev.classify_first"],
                    kind="partial", cls="minor", section="FINDINGS", label="Septation missing",
                    anchor=Span(start=0, end=10, text="A 14 mm left renal cyst."),
                    edit=Edit(mode="replace", find="A 14 mm left renal cyst.",
                              replace="A 14 mm left renal cyst with a thin septation."),
                    probe="The FINDINGS section describes the cyst's septation.", source_line=DICT[2:])
    store.save_items(db_session, [it])
    return rid, it


def test_get_review(client, auth_headers, seeded, monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    rid, it = seeded
    body = client.get(f"/api/reports/{rid}/review", headers=auth_headers).json()
    assert body["success"] and body["mode"] == "shadow" and body["rail"] is False
    assert [i["id"] for i in body["items"]] == [it.id] and body["run"]["mode"] == "shadow"


def test_get_review_owner_scoped(client, seeded, db_session):
    from rapid_reports_ai.auth import create_access_token
    other = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="O", is_active=True,
                 is_verified=True, is_approved=True)
    db_session.add(other)
    db_session.commit()
    h = {"Authorization": f"Bearer {create_access_token({'sub': str(other.id)})}"}
    rid, _ = seeded
    assert client.get(f"/api/reports/{rid}/review", headers=h).json() == {"success": False, "error": "Report not found"}


def test_item_event(client, auth_headers, seeded):
    rid, it = seeded
    r = client.post(f"/api/reports/{rid}/review/items/{it.id}/events", headers=auth_headers,
                    json={"command": "apply", "text_hash": "h", "detail": {}}).json()
    assert r["success"] and r["item"]["status"] == "applied"
    bad = client.post(f"/api/reports/{rid}/review/items/{it.id}/events", headers=auth_headers,
                      json={"command": "explode"}).json()
    assert not bad["success"]


def test_probe_requires_engine(client, auth_headers, seeded, monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    rid, _ = seeded
    r = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers,
                    json={"text": REPORT, "text_hash": "h", "changed_ranges": []}).json()
    assert r == {"success": False, "error": "review engine off"}


def test_probe_marks_addressed(client, auth_headers, seeded, monkeypatch, db_session):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"p0": {"noul": 0.9}}))
    rid, it = seeded
    r = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers,
                    json={"text": REPORT, "text_hash": "h2", "changed_ranges": []}).json()
    assert r["success"] and r["addressed"] == [it.id] and r["text_hash"] == "h2"
    assert store.get_item(db_session, rid, it.id).status == "addressed"


def test_reprepare(client, auth_headers, seeded, monkeypatch, db_session):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"a": {"noul": 0.9}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="minor", kind="partial", label="New label", reason="r", edit_mode="none")))
    rid, it = seeded
    r = client.post(f"/api/reports/{rid}/review/reprepare", headers=auth_headers,
                    json={"item_ids": [it.id], "text": REPORT, "text_hash": "h3"}).json()
    assert r["success"] and r["items"][0]["label"] == "New label"
    got = store.get_item(db_session, rid, it.id)
    assert got.label == "New label" and got.history[-1]["event"] == "prepared"


def test_rerun_schedules(client, auth_headers, seeded, monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    seen = []
    monkeypatch.setattr(engine, "schedule_review", lambda rid, text=None: seen.append((rid, text)))
    rid, _ = seeded
    r = client.post(f"/api/reports/{rid}/review/rerun", headers=auth_headers, json={"text": "X"}).json()
    assert r == {"success": True, "status": "running"} and seen == [(rid, "X")]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_api.py -q`
Expected: FAIL (404s: the routes don't exist).

- [ ] **Step 3: Write `api.py`**

```python
# src/rapid_reports_ai/review_engine/api.py
"""Review endpoints (spec §10.3), owner-scoped like the existing report endpoints. GET works in any mode (the
/dev/review-rail page reads shadow runs); probe, reprepare and rerun need the engine on."""
from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..database.crud import get_report
from ..database.models import User
from . import adjudicator, engine, store, verifier
from .items import ReviewItem

router = APIRouter(prefix="/api/reports", tags=["review"])
NOT_FOUND = {"success": False, "error": "Report not found"}
OFF = {"success": False, "error": "review engine off"}


class EventBody(BaseModel):
    command: str
    text_hash: Optional[str] = None
    detail: dict = Field(default_factory=dict)


class ProbeBody(BaseModel):
    text: str
    text_hash: str
    changed_ranges: List[List[int]] = Field(default_factory=list)


class ReprepareBody(BaseModel):
    item_ids: List[str]
    text: str
    text_hash: str


class RerunBody(BaseModel):
    text: Optional[str] = None


def _input(report, text: str):
    cand = (report.candidate_reports or [None])[0] or {}
    return engine.input_from_parts(str(report.id), report.report_type, report.input_data, {**cand, "content": text},
                                   report.enhancement_json)


@router.get("/{report_id}/review")
def get_review(report_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = get_report(db, report_id, user_id=str(current_user.id))
    if not report:
        return NOT_FOUND
    run = store.latest_run(db, report_id)
    items = store.list_items(db, report_id) if run else []
    return {"success": True, "mode": engine.mode(), "rail": engine.rail_enabled(), "run": run,
            "lanes": (run or {}).get("lanes") or {}, "items": [i.model_dump() for i in items]}


@router.post("/{report_id}/review/items/{item_id}/events")
def post_event(report_id: str, item_id: str, body: EventBody, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not get_report(db, report_id, user_id=str(current_user.id)):
        return NOT_FOUND
    try:
        item = store.append_event(db, report_id, item_id, body.command, body.text_hash, body.detail, actor="user")
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "item": item.model_dump()} if item else {"success": False, "error": "Item not found"}


@router.post("/{report_id}/review/probe")
async def post_probe(report_id: str, body: ProbeBody, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if engine.mode() == "off":
        return OFF
    report = get_report(db, report_id, user_id=str(current_user.id))
    if not report:
        return NOT_FOUND
    inp = _input(report, body.text)
    if inp is None:
        return {"success": False, "error": "no candidate"}
    open_items = [i for i in store.list_items(db, report_id) if i.status == "open"]
    res = await verifier.probe(inp, open_items, body.text, body.changed_ranges)
    for iid in res["addressed"]:
        store.append_event(db, report_id, iid, "addressed", body.text_hash, actor="loop")
    run = store.latest_run(db, report_id)
    new_items: List[ReviewItem] = []
    for c in res["contradictions"]:
        o = adjudicator.Outcome(group=[c])
        it = engine.build_item(inp, run["id"], o)
        it.cls = "action" if c.code_fix else "minor"
        new_items.append(it)
    if new_items:
        store.save_items(db, new_items)
    return {"success": True, "text_hash": body.text_hash, "addressed": res["addressed"],
            "reprepare": res["reprepare"], "new_items": [i.model_dump() for i in new_items]}


@router.post("/{report_id}/review/reprepare")
async def post_reprepare(report_id: str, body: ReprepareBody, current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    if engine.mode() == "off":
        return OFF
    report = get_report(db, report_id, user_id=str(current_user.id))
    if not report:
        return NOT_FOUND
    inp = _input(report, body.text)
    items = [i for i in (store.get_item(db, report_id, x) for x in body.item_ids) if i is not None]
    outcomes = await asyncio.gather(*(adjudicator.reprepare(inp, it, body.text) for it in items))
    for it, o in zip(items, outcomes):
        if o.judgement is not None:
            j = o.judgement
            it.cls, it.kind, it.label, it.reason = j.cls, j.kind or it.kind, j.label, j.reason
            it.edit, it.probe = adjudicator.to_edit(j), j.probe or it.probe
    await verifier.verify(inp, [i for i in items if i.cls != "suppress"], body.text)
    out = []
    for it, o in zip(items, outcomes):
        store.update_item(db, it)
        out.append(store.append_event(db, report_id, it.id, "prepared", body.text_hash,
                                      {"error": o.error} if o.error else {}, actor="engine"))
    return {"success": True, "text_hash": body.text_hash, "items": [i.model_dump() for i in out if i]}


@router.post("/{report_id}/review/rerun")
def post_rerun(report_id: str, body: RerunBody, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if engine.mode() == "off":
        return OFF
    if not get_report(db, report_id, user_id=str(current_user.id)):
        return NOT_FOUND
    engine.schedule_review(report_id, body.text)
    return {"success": True, "status": "running"}
```

- [ ] **Step 4: Mount the router in `main.py`**

Directly after `app.include_router(quick_report_router)`:

```python
# Review engine endpoints (/api/reports/{id}/review…), spec 2026-10-02 §10.3.
from .review_engine.api import router as review_router
app.include_router(review_router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_engine_api.py -q`
Expected: 8 passed. If `get_db` is not exported from `..database`, import it from `..database.connection` (which is where `main.py`'s import resolves).

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/review_engine/api.py src/rapid_reports_ai/main.py tests/test_review_engine_api.py
rcommit "feat(review-engine): review endpoints (get, item events, probe, reprepare, rerun), owner-scoped"
```

---

### Task 13: the live evaluation harness, the shadow read, and shadow in production

**Files:**
- Create: `src/rapid_reports_ai/scripts/review_engine_eval.py`
- Test: `tests/test_review_engine_eval.py`

- [ ] **Step 1: Write the failing test (the pure helpers only)**

```python
# tests/test_review_engine_eval.py
"""Eval harness helpers: output paths in the scratchpad, reuse of earlier outputs, the 2-run cap."""
import json
import os

import pytest

from rapid_reports_ai.scripts import review_engine_eval as E


def test_out_path_requires_scratch_and_has_pid(monkeypatch, tmp_path):
    monkeypatch.delenv("RR_LAB_OUT", raising=False)
    with pytest.raises(SystemExit):
        E.out_path("eval")
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    p = E.out_path("eval")
    assert p.parent == tmp_path / "review_eval" and str(os.getpid()) in p.name


def test_done_ids_reads_previous_outputs(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(json.dumps({"report_id": "r1", "run": 1}) + "\n" + json.dumps({"report_id": "r2", "run": 1}) + "\n")
    assert E.done_ids([f], run=1) == {"r1", "r2"} and E.done_ids([f], run=2) == set()


def test_runs_capped():
    assert E.cap_runs(5) == 2 and E.cap_runs(1) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_engine_eval.py -q`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `review_engine_eval.py`**

```python
# src/rapid_reports_ai/scripts/review_engine_eval.py
"""Live evaluation harness for the review engine (spec §13), and the Gate F shadow read.

    # run the engine on recent production quick reports (no storage), 2 runs max, outputs reused:
    RR_LAB_OUT=<scratchpad> .venv/bin/python -m rapid_reports_ai.scripts.review_engine_eval run --limit 20 --runs 2
    # hand-read page over stored shadow items (Gate F):
    RR_LAB_OUT=<scratchpad> .venv/bin/python -m rapid_reports_ai.scripts.review_engine_eval shadow-page --days 3

Production text stays in RR_LAB_OUT (Hassan's standing read permission); nothing is written to production."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Iterable, List, Optional, Set

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[3]
MAX_RUNS = 2


def cap_runs(n: int) -> int:
    return max(1, min(n, MAX_RUNS))


def out_path(stem: str, ext: str = "jsonl") -> Path:
    root = os.environ.get("RR_LAB_OUT")
    if not root:
        raise SystemExit("set RR_LAB_OUT to a scratchpad directory")
    d = Path(root) / "review_eval"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{stem}_{os.getpid()}.{ext}"


def done_ids(files: Iterable[Path], run: int) -> Set[str]:
    out = set()
    for f in files:
        for line in Path(f).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("run") == run:
                    out.add(r["report_id"])
    return out


SQL_RECENT = """select id::text as id, report_type, input_data, candidate_reports->0 as cand, enhancement_json
from reports where candidate_reports is not null and created_at >= now() - interval '{days} days'
and coalesce(candidate_reports->0->>'error', '') = '' order by created_at desc limit {limit}"""

SQL_SHADOW = """select i.id::text as id, i.report_id::text as report_id, i.lane, i.kind, i.cls, i.label, i.reason,
       i.edit, i.verified, i.source_line, i.anchor, r.report_type,
       r.candidate_reports->0->>'content' as content, r.input_data
from report_review_items i join report_review_runs u on u.id = i.run_id join reports r on r.id = i.report_id
where u.mode = 'shadow' and u.created_at >= now() - interval '{days} days' order by i.report_id, i.created_at"""


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def _run(rows: List[dict], runs: int, reuse: List[Path]) -> Path:
    from rapid_reports_ai.review_engine import engine
    out = out_path("eval")
    sem = asyncio.Semaphore(4)
    with open(out, "w") as fh:
        for run in range(1, runs + 1):
            skip = done_ids(reuse, run)

            async def one(r):
                if r["id"] in skip:
                    return None
                inp = engine.input_from_parts(r["id"], r["report_type"], _j(r["input_data"]), _j(r["cand"]),
                                              _j(r["enhancement_json"]))
                if inp is None:
                    return None
                async with sem:
                    res = await engine.run_review(inp, run_id=f"eval-{run}")
                return {"report_id": r["id"], "run": run, "run_meta": res.run,
                        "items": [i.model_dump() for i in res.items]}
            for row in await asyncio.gather(*(one(r) for r in rows)):
                if row:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out


def cmd_run(args) -> None:
    load_dotenv(BACKEND / ".env")
    from rapid_reports_ai.scripts.review_labs.common import metabase
    cache = out_path("cases", "json").with_name("cases.json")
    if cache.exists() and not args.refresh:
        rows = json.loads(cache.read_text())
    else:
        rows = metabase(SQL_RECENT.format(days=args.days, limit=args.limit))
        cache.write_text(json.dumps(rows, ensure_ascii=False))
    print(asyncio.run(_run(rows[: args.limit], cap_runs(args.runs), [Path(p) for p in args.reuse])))


def cmd_shadow_page(args) -> None:
    load_dotenv(BACKEND / ".env")
    from rapid_reports_ai.scripts.review_labs import label_page
    from rapid_reports_ai.scripts.review_labs.common import metabase
    rows = metabase(SQL_SHADOW.format(days=args.days))
    cards = []
    for r in rows:
        edit, ver = _j(r["edit"]), _j(r["verified"])
        cards.append({"id": r["id"], "title": f"{r['report_id'][:8]} · {r['lane']}/{r['kind']} → {r['cls']}",
                      "meta": r["report_type"],
                      "blocks": [{"label": "Label / reason", "text": f"{r['label']}\n{r['reason'] or ''}"},
                                 {"label": "Fix", "text": json.dumps(edit) + "\nverified: " + json.dumps(ver)},
                                 {"label": "Dictated line", "text": r["source_line"] or ""},
                                 {"label": "Report", "text": r["content"] or "", "collapsed": True},
                                 {"label": "Dictation", "text": ((_j(r["input_data"]) or {}).get("variables") or {})
                                  .get("FINDINGS", ""), "collapsed": True}], "hidden": []})
    fields = [{"key": "verdict", "label": "Correct class", "type": "choice",
               "options": ["action", "minor", "info", "suppress"], "required": True},
              {"key": "fix_ok", "label": "Fix right", "type": "choice", "options": ["yes", "no", "n/a"]},
              {"key": "note", "type": "text", "label": "Note"}]
    p = out_path("shadow_read", "html")
    label_page.write_page(p, "Gate F · shadow read", "gateF-shadow-v1", cards, fields)
    print(p, len(cards))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int, default=20)
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--runs", type=int, default=1)
    r.add_argument("--reuse", nargs="*", default=[])
    r.add_argument("--refresh", action="store_true")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("shadow-page")
    s.add_argument("--days", type=int, default=3)
    s.set_defaults(fn=cmd_shadow_page)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass, then the full suite**

Run: `.venv/bin/python -m pytest tests/test_review_engine_eval.py -q && .venv/bin/python -m pytest -q`
Expected: the eval tests pass. The full suite shows no new failures against `main` (compare with `git stash; pytest -q; git stash pop` if anything unrelated fails).

- [ ] **Step 5: Smoke-test 2 reports live, then one 20-report run**

Run: `RR_LAB_OUT=<scratchpad> .venv/bin/python -m rapid_reports_ai.scripts.review_engine_eval run --limit 2 --runs 1`
Expected: a jsonl with 2 rows. Each has `run_meta.lanes` all `done`, no `adjudicator_*` errors, and a `timings_ms.total`. Fix any structured-output failure before the next step (L-50 method).

Run: `... review_engine_eval run --limit 20 --runs 2 --reuse <the smoke jsonl>`
Read 5 reports' items by hand, and note the lane timings (p90 of `jev_ms + lanes_ms + adjudicator_ms + verifier_ms`).

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_engine_eval.py tests/test_review_engine_eval.py
rcommit "feat(review-engine): live evaluation harness and Gate F shadow-read page"
```

- [ ] **Step 7: Shadow in production (outward actions; each needs Hassan's explicit go-ahead)**

1. **Merge.** Open a PR from `feat/review-rail` and merge it after review. `RR_REVIEW_ENGINE` stays unset, so production behaviour is unchanged.
2. **Migration.** Hassan runs, or approves running, `migrations/versions/20261003120000_add_review_engine_tables.py` against production through the project's usual route (`run_migrations.py`, `alembic upgrade head` with the production `DATABASE_URL`).
   Verify via Metabase `/api/dataset`: `select count(*) from report_review_runs` returns 0 rows without error.
3. **Switch shadow on.** Hassan approves setting the Railway env `RR_REVIEW_ENGINE=shadow`. Leave `RR_REVIEW_LANES` unset (all lanes in shadow).
4. **Verify by data, not deploy state** (memory `reference_railway_deploy_architecture`). After the next production report, check `select mode, lanes, timings_ms, errors, created_at from report_review_runs order by created_at desc limit 5` through Metabase. Expect `mode='shadow'` and lanes `done`. Then confirm through the Chrome session (memory `reference_prod_smoke_testing`) that the report UI is unchanged.
5. **Ledger.** Add the next free L-number, "Review engine shadow on", with the engine version, date and the first day's failure rate and p90.

---

### Task 14: the negatives classifier (generated normals → assumed normal / check / removed)

**Why:** this is the policy agreed 2026-10-03/04 (memories `default-negatives`, `generation-proposes-review-disposes`):
- generation states undictated normals by design;
- the review layer makes them visible and controllable.

This task ports the lab version, which was validated on 119 gold-labelled statements and an end-to-end prototype, into the engine. Run it in wave 6 alongside Task 10, after Tasks 1, 5 and 9.

**Port from the lab** (tested code and prompt; adapt types only):
- `scripts/review_labs/negatives_lab.py`: `candidates()`, which skips recommendation sentences; `code_number_flag()`; `parse_labels()`; the `Labels` flat schema.
- `scripts/review_labs/prompts/negatives_v5.txt`, as `review_engine/prompts/negatives.txt`.
- `scripts/review_labs/negatives_bundle.py`: span location, code removal with anchors, `_undictated_numbers()`, and the check reasons `uncertain` / `conflict` / `number`.

**Files:**
- Create `review_engine/negatives.py` and `tests/test_review_engine_negatives.py`.
- Modify `review_engine/engine.py` to call it after generation, concurrently with the other lanes.

**Behaviour:**
1. **One Qwen reasoning call per report.** The input is the dictation, history and report plus the numbered candidates. The output is one label per candidate: `dictated | default | implicated | contradicted`, with a pointer.
   - Flat schema, no output retries, and a validation failure leaves every candidate `default`, logged. This is fail-soft: it shows as assumed normal, never as removed.
2. **Code checks:**
   - `number`: the candidate has a measurement not in the dictation or history;
   - recommendation sentences are excluded from the candidates.
3. **Routing to `ReviewItem`s.** Use `lane="accuracy"` (the normal/negative half of Accuracy: report statements judged against the dictation), `detectors=["negatives.v5"]`, and set `kind` and `status` as follows:

   | Label | `kind` | `status` | Rail row? |
   |---|---|---|---|
   | `default` | `assumed_normal` | `open` | No (editor-only, Quiet styling) |
   | `implicated` | `check` | `open` | Yes, with `evidence.check_reason` (`uncertain`, `conflict` or `number`) and the pointer |
   | `contradicted` (or `number` on a non-dictated clause) that code can remove | `removed` | `pre_applied` | Yes, with an `edit` of mode `remove` and the removed text kept for restore |
   | `contradicted` that code cannot remove | `check` | `open` | Yes, with reason `conflict` |
   | `dictated` | none | | No item |

4. **Hard rules:**
   - Never auto-remove a statement the classifier calls `dictated`. A number inside a dictated sentence becomes a `check` (reason `number`).
   - Auto-removal applies only to generated negatives. This is the f85aa670 lesson and PR #6.
5. **The copy and export invariant for the frontend** (Slices B/C, recorded here so the contract carries it): the CM6 document is the report. `removed` and `option` items are widgets, never document text. The prototype's `lib/review/negatives-proto/state.ts` is the reference implementation, with 15 vitest tests.

**Acceptance:**
- **Unit tests:**
  - routing per label;
  - a number in a dictated sentence becomes `check`, never removed;
  - a validation failure is fail-soft;
  - recommendations are excluded;
  - removal anchors stay valid after several removals;
  - number detection handles glued units ("4cm") and ignores level and sequence names (T1, C7, L4/5).
- **Live evaluation** (Task 13 harness):
  - the lab's 119-statement gold set (`gold_final.json`, in the scratchpad; synthetic seeds only in the repo): no false contradictions, which is the bar for auto-removal;
  - a fresh 10-report end-to-end set, hand-read by Hassan through `/dev/negatives-proto`.
- **Latency:** 3–9 s per report in the lab, running concurrently with the other lanes, so it adds nothing to the critical path in shadow mode.

**Out of scope here:** a separate certainty output for the "firmer than you dictated" check reason (a hedge dropped). That needs its own classifier field and is deferred.

---

## Self-review notes

- **Spec coverage:**

  | Spec | Where it is covered |
  |---|---|
  | §4 modules | `alignment`, `checks`, `lanes/*`, `adjudicator`, `verifier`, `items`, `engine`, `store`, plus `jev_pass` and `api`. These two are additions: the shared Jev request, and the endpoints |
  | §5.1 `ReviewInput` | Task 1, plus `pre_edit_report` for Gate D |
  | §5.2 alignment | Task 2: pure code, many-to-many, background, history as a second source |
  | §6.1 | `Candidate`, `Lane`, `RR_REVIEW_LANES` |
  | §6.2 | classify-first, selector, negatives excluded, unsure routed, laterality |
  | §6.3 | contradiction (negative: code removal; positive: adjudicator), unsupported, overstated + `hedge_tag`, misattributed, inconsistent |
  | §6.4 | brief options pre-classed with the "already in report" probe, the upgrade case, S4 mapping, the gate |
  | §6.5 | unsure → adjudicator with the question name only; verifier `unconfirmed` |
  | §7 | flat `Judgement`, one call per group, cap 8 / 20, failure → minor, no veto, no flip rule, prompt from Gate A |
  | §8 | guards 1–5, `addressed`, `contra`, `unconfirmed` |
  | §9 | the shadow log records options A and B per edit |
  | §10.1 | `ReviewItem` |
  | §10.2 | tables + `workspace_state`. The Metabase view `v_review_item_events` belongs to Slice E, as the spec's §14 says |
  | §10.3 | endpoints. The SSE `review` field is live-mode only and arrives with live, after Gates F and G |
  | §10.4 | flags, shadow behaviour, failure handling |

- **Clinical pass:** this is deliberately not in Slice A. Gate C decides its shape (§6.4, §11). `s4_candidates` and the lane interface are ready for it.
- **Type consistency with Plan 1:** `Judgement` fields are identical to `scripts/review_labs/judgement.py`; kind names match the lab's `_KIND_TEXT`, plus `coverage_check`; the guard names (`anchor_not_unique`, `ungrounded_number`, `ungrounded_side`, `drops_negation`, `remove_not_allowed`, `fix_contradicts_dictation`) match.
- **Known deviations from the spec text:**
  - Spec §6.1's `candidates(inp, al)` takes a `LaneContext`, so the batched Jev requests are made once.
  - The endpoints live in an `APIRouter` mounted in `main.py`, not as inline `@app` handlers.
  - `Report.workspace_state` is `deferred`, for deploy safety.
