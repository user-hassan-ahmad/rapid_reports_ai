# Review engine and Review rail: design

**Date:** 2026-10-02 · **Branch:** `feat/review-rail` · **Status:** draft for Hassan's review

**Basis:**
- `docs/superpowers/handover/2026-10-01-rail-inputs-from-pipeline-session.md`, section "Agreed direction (2026-10-02)". It overrides everything earlier in that file.
- `docs/superpowers/handover/2026-09-30-suggestions-panel-handover.md`, section "Brainstorm outcome" and its addenda, for the rail UI, chat edits, the live probe loop, sessions and the command registry. Its edit engine and item sources are superseded by §3–§9 here.
- Memory: `feedback_simplicity_single_unit`, `feedback_review_item_policy`, `feedback_impression_core_tight`, `reference_jev_capability_profile`.

The design is approved. This spec fixes interfaces, contracts and gates; it does not reopen the design.

---

## 1. Why

Two fidelity audits run side by side today:
- the post-generation check (`report_review.check` / `run_quality_check`), now mostly flag-only;
- the parallel audit (`enhancement_utils.run_audit_phase1` / `run_audit_phase2`), whose criteria are LLM judges at temperature 0.8 and flip between runs.

Neither catches fabrication, certainty upgrades or re-attributed measurements. Nothing turns guideline synthesis into an applicable edit. Options live in a separate panel (`OptionalAdditions`).

This spec replaces all of that with **one review engine** (three lanes, one adjudicator, one verifier) feeding **one Review rail** with editor overlays. Every change to the report is proposed, shown and confirmed by the radiologist, apart from the automatic edits whose fate the production audit (Gate D) decides.

## 2. Principles (binding on every section below)

1. **Simple first.** Small, focused upgrades, each earning its place with lab evidence on real data against a baseline. When a fix needs a fix, change the earlier design choice rather than adding a layer.
2. **One reasoning call owns each judgement.** Qwen with reasoning reads the whole case for one item, decides, and writes the fix in the same call. No OR'd questions, no split streams, no stacked gates that bias the same way.
3. **Roles:**
   - **Code:** deterministic checks (numbers, dates, hedges, alignment), applying edits, guards.
   - **Jev:** narrow yes/no or distinct-choice questions on stated text, for detection and fix verification. It never vetoes Qwen's reading.
   - **Qwen:** reading, judgement and writing.
4. **Testing:**
   - Code changes are test-first.
   - Model behaviour is tested with mocked calls in unit tests, plus golden fixtures from labs and a separate live evaluation harness.
   - Every new Jev gate gets its own wording lab first.
   - Real production cases are the base, seeding synthetic cases and stress tests.
   - Small and contained first, growing only when needed.
   - Balanced labels, stability over 2 runs, thresholds in measured gaps, Hassan's hand read as the gate.
5. **Delivery:**
   - The engine ships behind a flag, in **shadow mode in production first**.
   - Every new frontend route ships with `requireDevRoute` from its first commit.
   - Prompts are case-agnostic: structural examples, never single-domain clinical ones.

## 3. Scope

**In scope:**
- The review engine: alignment, the Coverage, Accuracy and Additions lanes, the adjudicator, the verifier, the item contract, storage, endpoints and flags.
- The Review rail: layout, CM6 overlays, item actions, the command registry, the live probe loop, chat edits, sessions and History, and outcome recording.
- Four labs as gates (§11), plus the shadow, probe and pre-launch gates.
- Both pathways, quick and templated, through `GenerationArtifacts`.

**Out of scope, each with its own later spec:** dictate-to-edit, chat threads and search, frozen snapshots.

**Unchanged:** report generation itself, the impression style (`feedback_impression_core_tight`), the brief and its options logic, and the L-49 rule that dictated negatives are never omission-checked or inserted.

## 4. Architecture

```
                      GenerationArtifacts (quick | templated)
                      + clinical history + scan_type
                                    │
                            ┌───────▼────────┐
                            │  Alignment     │  code: report clauses ↔ dictated lines
                            └───┬────────┬───┘
                     forwards   │        │   backwards
                   ┌────────────▼──┐  ┌──▼────────────┐   ┌────────────────────────┐
                   │ Coverage lane │  │ Accuracy lane │   │ Additions lane         │
                   │ code + Jev    │  │ code + Jev    │   │ brief options, S4      │
                   │ (report-state)│  │ (dict-state)  │   │ synthesis, clinical    │
                   └──────┬────────┘  └──────┬────────┘   │ pass → Jev "already    │
                          │                  │            │ in report" gate        │
                          │                  │            └──────────┬─────────────┘
                          └────────┬─────────┘                       │ (streams when S4 lands)
                                   ▼                                 ▼
                         Merge + de-duplicate (code, by overlapping span / dictated line)
                                   │
                         Adjudicator (Qwen, reasoning, one call per item group)
                           → class, kind, label, reason, smallest fix, probe
                                   │
                         Verifier (code guards + Jev addressed/contradiction)
                                   │
                         ReviewItem rows ──► rail + CM6 overlays ──► live probe loop
```

**Timing.**
- **Coverage and Accuracy** run after generation, in the slot today's post-generation check occupies. Their items are ready before the report renders and travel on the SSE `candidate` event.
- **Additions** is non-blocking. Brief options arrive with the candidate. Clinical-pass and S4 items stream into the rail when they land, and the live loop re-verifies them against the current text.
- **In shadow mode** (§10) the whole engine runs in the background after the candidate is saved, and the report path is untouched.

**New modules** (backend, `src/rapid_reports_ai/review_engine/`):

| Module | Owns |
|---|---|
| `alignment.py` | `align()`, pure code |
| `checks.py` | the code checks (numbers, dates and priors, `hedge_tag`, modality vocabulary, size words, laterality bounds) |
| `lanes/coverage.py`, `lanes/accuracy.py`, `lanes/additions.py` | one `Lane` each |
| `adjudicator.py` | the Qwen call, prompt and output model |
| `verifier.py` | code guards and Jev verification |
| `items.py` | `Candidate`, `ReviewItem`, merge and de-duplication |
| `engine.py` | orchestration, flags, run logging |
| `store.py` | persistence |

These modules reuse `report_review.py` (clauses, section spans, protected spans, `edit_allowed`, the Jev questions) and `jev_client.py`. Nothing moves out of `report_review.py`; the old `check()` path stays live until rollout (§13).

## 5. Inputs and alignment

### 5.1 Engine input

```python
class ReviewInput(BaseModel):
    report_id: str
    pathway: Literal["quick", "templated"]
    artifacts: GenerationArtifacts        # report, dictated_findings, sections, options, brief, quality_check
    clinical_history: str
    scan_type: str
    study_title: str | None               # bounds laterality
    synthesis: dict | None = None         # enhancement_json S4 cards, when available
```

### 5.2 Alignment interface (code)

```python
class DictLine(BaseModel):
    id: str; text: str
    side: Literal["left", "right", "bilateral"] | None
    level: str | None                     # vertebral / segment / lobe tag where present
    negative: bool                        # dictated negative
    background: bool                      # the omission selector says not reportable (L-49 selector)

class ReportClause(BaseModel):
    id: str; text: str; section: str      # generic heading from artifacts.sections
    start: int; end: int                  # offsets in artifacts.report
    side: str | None; level: str | None
    negative: bool
    subheading_side: str | None           # side bounded by a containing subheading ("Left leg:")

class Pair(BaseModel):
    line_id: str; clause_id: str; score: float
    how: Literal["exact", "lexical", "number", "anatomy"]

class Alignment(BaseModel):
    lines: list[DictLine]; clauses: list[ReportClause]
    pairs: list[Pair]                     # many-to-many; ambiguity is kept, never forced to one
    unmatched_lines: list[str]; unmatched_clauses: list[str]

def align(report: str, dictation: str, history: str, sections: list[str]) -> Alignment: ...
```

**Rules:**
- **Pure code.** Splitting reuses `report_review.clauses_in_context`, `dictated_items` and `section_spans`.
- **Scoring:** content-word overlap, shared numbers with units, and a shared anatomy term.
- **Ambiguity is kept.** Jev is weak at choosing between overlapping spans (40% in the capability profile), so it is never asked to pick the best pair. Lanes read every pair above the floor.
- **Background:** clinical history lines are a second source for Accuracy (numbers, priors), never a coverage target (L-36: history is never emitted).

## 6. Lanes

### 6.1 Common interface

```python
class Candidate(BaseModel):
    lane: Literal["coverage", "accuracy", "additions"]
    kind: str                             # see the lane tables
    section: str | None
    anchor: Span | None                   # report span (start, end, text)
    line_id: str | None                   # dictated line, for coverage items
    evidence: dict                        # code-check details, Jev scores, guideline card ref
    proposed: Edit | None = None          # only producers that already write (brief options)
    preclassed: Literal["minor"] | None = None
    detector: str                         # e.g. "jev.classify_first", "code.numbers"

class Lane(Protocol):
    name: str
    async def candidates(self, inp: ReviewInput, al: Alignment) -> list[Candidate]: ...
```

Every lane is independently switchable (`RR_REVIEW_LANES`, §10). A lane enters live mode only after its gate passes (§11).

### 6.2 Coverage lane: is everything dictated carried, as dictated?

| Kind | Detector | Notes |
|---|---|---|
| `absent` | Jev report-state call, classify-first per selected dictated line (today's call) | pre-apply only if Gate D says so (§9) |
| `partial` | same call; code `missing_detail` names the lost descriptor | a lost normal-variant descriptor counts |
| `differs` | same call | dictation is the truth; "out of scope" is never a valid drop |
| `laterality` | code: a side in the line is missing from every paired clause, and neither `study_title` nor `subheading_side` bounds it | |
| `slip` | never detected directly; the adjudicator re-kinds a `differs` whose report wording correctly fixes a speech-recognition error | always `info` |

**Selection:**
- the L-49 omission selector (`selection_score` ≥ 0.45);
- dictated negatives and background lines are excluded (L-49).

**Exit options (§6.5):**
- **`can't tell`, new, under test in Gate A:** "the report's coverage of this line can't be judged from the text", routed as unsure.
- **`unclear`, unchanged:** a heading or garbled fragment. It still raises no flag.
- **A `stated` answer below the confident band** is also unsure. Today it is silently dropped.

**Gate A** governs this lane's precision and recall (§11).

### 6.3 Accuracy lane: is everything in the report supported and consistent?

| Kind | Detector | Default fix |
|---|---|---|
| `contradicted` (negative) | Jev dictation-state call, contradiction (today's Q_CONTRA wording, holds per the wording suite) | code removal (`remove_negative_clause`), pre-applied or one-click per Gate D |
| `contradicted` (positive) | same | adjudicator proposes; always one-click, never automatic (PR #7) |
| `unsupported` | **code first:** a number, date or prior-study reference with no match in dictation or history. **Then Jev:** a scoped "is this positive finding stated" per unmatched positive clause, **only after its wording lab passes** (Gate B2) | adjudicator: remove or restore the dictated wording |
| `overstated` | code `hedge_tag` on paired clauses: report certainty above the dictated level | restore the dictated hedge |
| `misattributed` | code: a measurement found in the source but paired with a line about a different structure | move it back |
| `inconsistent` | code: modality vocabulary (e.g. "signal" on CT), size word against measurement | adjudicator proposes |

**`hedge_tag(clause) -> Literal["negated", "possible", "probable", "definite"]`** is new code, built from a small lexicon fixed in Gate B.

**Starting point.** v1 `inconsistent` is code-only. An LLM anatomy-consistency check (from `anatomical_accuracy`, 4/7 useful) is added only if Gate B shows the code misses those cases. The naive "undictated abnormal finding" Jev question measured 5/32 with 49 false alarms (L-46), which is why code runs first and the scoped question needs its own lab.

### 6.4 Additions lane: what would a consultant add?

This lane has no detector. It has producers, then one Jev gate.

| Producer | Candidate kinds | Arrives |
|---|---|---|
| Brief / Phase 1 options (`artifacts.options`) | `option` (sub-kinds `impression`, `recommendation`, `finding_negative`) | with the candidate |
| S4 synthesis mapping (code, from `enhancement_json`) | `grade` (classification gradable from dictated features), `characterise` ("can't grade: X not described"), `threshold`, `follow_up` (an upgrade of the existing recommendation line), `option` (further actions, differentials, imaging flags, low salience) | when S4 lands |
| One clinical pass (Qwen, reasoning; characterisation and safety only; replaces about 8 audit criterion passes) | `characterise`, `safety` (critical steps only, e.g. anticoagulant reversal, MSCC MRI within 24 h), `urgency` (banner tier) | in the background after generate |

**Gate:** the Jev "already in report" gate (L-49 uniqueness wording: *states*, not merely implies) drops candidates already stated.

**Safety rules,** enforced by the adjudicator prompt and checked in code where possible:
1. **Grounding.** No grade or threshold is inferred from undictated features. Code checks that every number in a `threshold`/`grade` fix appears in the source.
2. **Radiology remit only.** No management.
3. **One recommendation line in the core.** A `follow_up` edits the existing line (an `upgrade` edit); extra recommendations stay `option`.
4. **Citations.** Every guideline-derived item carries a citation chip to its Guidelines-tab card.

**Pre-classed options.** Brief options were already judged and written by one reasoning call (the brief), so they arrive `preclassed="minor"` with their sentence as `proposed`. They are not judged again (Principle 2). They pass through de-duplication, the "already in report" gate and the verifier. The one exception is a `finding_negative` whose structure the report already calls normal. It goes to the adjudicator for an `upgrade` edit that rewrites that sentence (handover addendum 2026-10-01).

**Grade and characterise items: evidence from the gradability lab** (ledger L-50, spec `2026-10-02-qwen-authored-jev-questions-lab-design.md`). Qwen judged "is this finding gradable with system X from the dictation?" on 100 labelled items:
- **One call wins.** Single-pass Qwen with reasoning on scored balanced accuracy 0.82. Listing the inputs first (one call or two) and Jev-as-tool did not beat it.
- **The dominant failure is over-demanding.** Every method marks gradable findings "can't grade" because it requires inputs the system doesn't need: a false-alarm rate of 0.16 for the single call, and 0.25–0.27 for checklists.
- **Overcalls from silence persist** on multi-part systems: CAD-RADS with vessels unmentioned is read as normal.

What this means for the engine:
1. **One adjudicator call, unchanged.** It has no enumeration or checklist step and no Jev tool round.
2. **The labelling rules go into the adjudicator prompt** for grade and characterise items, written structurally:
   - **core category only:** ignore modifiers and eligibility unless they change the category;
   - **literal:** an input counts only if stated;
   - **standard meaning:** read descriptors by their standard meaning, and a criterion counts as described when its ordinarily dictated features are covered.
3. **`characterise` ("can't grade: X not described") ships as `minor` at most,** never `action`. It is promoted only if Gate C measures its false "can't grade" rate at ≤ 10%.
4. **Untested lead: supply the criteria.** Pass the guideline synthesis's `criteria` text for that classification into the adjudicator call, rather than relying on Qwen's recall. It is tested in Gate C as an arm (with vs without criteria), and adopted only if it lowers false "can't grade" without raising overcalls.
5. **Reusable test set:** `backend/test_cases/jev_tool_lab/s1_phase3.json` holds 100 labelled gradability items, 50/50, in 8 difficulty categories. It is Gate C's seed set for grade items.

**Urgency** renders as the rail banner, not a row. Its tiers are tightened in Gate C. This replaces `clinical_flagging`.

**Gate C** governs this lane.

### 6.5 Jev confidence routing: unsure answers go to a stronger reader

Every Jev detection question has three bands: confident yes, confident no, and **unsure**. An unsure answer is never treated as a verdict. It is escalated so a stronger reader settles it. This is the vendor's confidence-routing pattern (field research F-05).

**What counts as unsure:**
- a **Choice** that picks its exit option (`can't tell`, "none of these"), following F-06 and P-11;
- a **Choice** with a narrow gap between its top two options (F-02, D-07);
- a **noul** in its middle band.

The band edges for each question are set in that question's wording lab (§11), in the measured gap. They are not guessed.

**Escalation, in order of simplicity:**
1. **Qwen, the default.** The unsure item becomes a candidate with `evidence.jev_unsure = {question, band}` and goes to the adjudicator. Qwen reads the whole case and makes the call in its single call for that item (Principle 2).
   - The adjudicator sees *which* question was unsure, not Jev's leaning, so it reads fresh.
   - If Qwen decides there is nothing to fix, the item is `suppress`. That is a judgement, not a default.
   - No new machinery: this only stops unsure answers from being dropped.
2. **Targeted Jev follow-ups, an upgrade that must earn its place.** For a **named confusion pair** (e.g. classify-first `partial` ↔ `different`: "does the report give a different size, side or grade for this structure?"), narrow follow-up questions are asked **in the same call** as the main question (speculative fan-out, F-04). Code reads them only when the main answer is unsure.
   - A follow-up must be a different angle on the item, never a rewording of it. Rewordings correlate 0.94–0.999 and never helped (wording suite).
   - A follow-up that settles the item confidently replaces escalation for that item. If it is still unsure, the item goes to Qwen.
   - Follow-ups are added per confusion pair, only where their lab shows they settle unsure items at least as accurately as Qwen does.
   - **Lowest priority (L-50).** In the gradability lab, Jev's answers didn't measurably improve Qwen's judgement (C vs its no-Jev control: 1/1 and 1/0). Build escalation to Qwen first; consider follow-ups only if a wording lab shows a confusion pair Qwen also gets wrong.

**Validated Jev wordings available** (L-50, `backend/src/rapid_reports_ai/scripts/jev_tool_lab/catalogue.py`; AUC 1.0, margins ≥ 0.71, on synthetic items):
- **T2-dictation w1:** "does the dictation say anything about {topic}", including finding-scoped topics with a neighbour carrying the attribute.
- **T6 w2:** "are these two quoted spans the same structure or finding, same side and level".
- **Candidate uses:** T6 for cross-lane de-duplication when spans don't overlap, and T2-dictation for coverage checks. Each still needs its own run on real data before it becomes a gate.

**Where the rule applies:**

| Question | Unsure → |
|---|---|
| Coverage classify-first (§6.2) | adjudicator |
| Accuracy contradiction (§6.3) | adjudicator |
| Accuracy "is this positive finding stated" (Gate B2) | adjudicator; asked as a Choice of `stated` / `not stated` / `can't tell` |
| Additions "already in report" (§6.4) | the candidate is kept and goes to the adjudicator, even a pre-classed brief option |
| Verifier `addressed` (§8) | the fix is kept but marked **unconfirmed** (see §8). Qwen is not asked to grade its own fix. |
| Live probe loop (§12.4) | the 0.5–0.8 band re-prepares the item: the same rule, already in the design |

**Why this is not stacked gating:**
- Confident answers are acted on as before.
- Only the unsure pile moves, and it moves to a *different* reader, not to another gate biased the same way.
- **Precondition:** escalation only helps if Jev's mistakes fall in the unsure band. A confidently wrong answer never reaches it, and a miss at that first stage can't be recovered (capability profile). Each wording lab measures this (§11), and a question whose errors are mostly confident gets a better wording, not an escalation route.

## 7. Adjudicator

**Merge first (code).** Candidates are grouped when their anchors overlap, or when they share a `line_id`. A group keeps every detector name (`detectors[]`), so the rail can show the lanes as badges.

**One call per group:** Qwen 3.8 27b (Cerebras), reasoning on. Calls run concurrently, capped at 8 per report. Above 20 groups, the overflow becomes `minor` with no fix, and the overflow is logged.

**Input:** the full dictation, the history, the report, the group's candidates with their evidence, and the paired clauses.

```python
class Judgement(BaseModel):               # FLAT on purpose (L-50): Qwen string-encodes nested objects/lists
    cls: Literal["action", "minor", "info", "suppress"]
    kind: str                             # may refine, e.g. differs → slip
    label: str                            # ≤ 80 chars, rail row text
    reason: str                           # one sentence, shown on expand
    edit_mode: Literal["none", "replace", "insert", "upgrade", "remove"]   # "none" when no change is right
    edit_find: str | None                 # verbatim, must occur exactly once (replace/upgrade/remove)
    edit_replace: str | None
    edit_after: str | None                # verbatim anchor sentence for insert
    edit_section: str | None
    probe: str | None                     # topic-coverage question, section-scoped, general terms

# Code builds the internal Edit (mode, find, replace, after, section) from the edit_* fields.
```

**Structured-output rules (L-50):**
- **Flat schemas:** no nested objects in any Qwen output model.
- **Decode string-encoded fields:** any list field gets a `before` validator that decodes a JSON-encoded string.
- **Retries at temperature 0 are futile,** because they repeat the identical output. On a validation failure, the item becomes `minor` with no fix, and the failure is logged.

**Prompt.** Short and principle-based. It carries:
- the review-item policy (missing detail flagged unless absorbed, dictation is truth, bounded laterality, slips are info, genuine contradictions only, undictated sensible recommendations are a feature, "no change" → no action card);
- the impression-core rule;
- the no-fabrication and radiology-remit rules;
- the smallest-fix rule: never rewrite a whole line when part of it is stated, and never copy a slip from the raw dictation;
- the probe rule: "whether the topic is covered, scoped to its section, in general terms, not the edit's wording".

Examples are structural. The lab's `prompt_v3.txt` is the starting text.

**Class rules:**
- `action`: a real problem with a fix the radiologist should see.
- **`minor`: the uncertain tier.** Shown low-salience with the fix ready. **Uncertain → minor, not suppress.**
- `info`: an audit-trail tag (slips).
- `suppress`: clear noise only. Stored, not shown.

**Explicitly removed from v3** (the causes of its recall loss):
- the "when in doubt suppress" wording;
- the run-flip → suppress rule (stability is measured in labs, not enforced at run time);
- the Jev "conveys" veto.

## 8. Verifier

The verifier checks the **fix**, never the reading. A failed check removes the edit; the item keeps its class and shows "Ask in chat" and Dismiss.

**Code guards:**
1. `find` or `after` occurs exactly once in the current text.
2. `edit_allowed`: never drops a negation (L-47), and stays inside protected-span rules.
3. Grounding: every number and laterality word in `replace` appears in the dictation or history.
4. The edit stays inside the item's section.
5. No duplicate: `_restates` against the target paragraph.

**Jev checks:** one batched call over all items, run on each item's post-edit text.
- `addressed`: the item's probe on the edited text is ≥ 0.8.
- `contradiction`: the changed clauses against the dictation are < 0.6, using today's thresholds. These are confirmed or re-set in the Gate E lab.

**Unsure `addressed`** (middle band, §6.5):
- The fix is kept and marked `unconfirmed`. The rail shows it with "check this fix", and Apply still works.
- Re-asking Qwen would only have it grade its own fix, so the upgrade path is a targeted Jev follow-up for that item kind, if one earns its place.

**Results** are stored as `verified = {code: bool, addressed: float, contra: float, unconfirmed: bool}`.

## 9. Automatic edits: open, decided by Gate D

Today two edits are applied before render:
- code removal of a contradicted negative (never one the dictation itself states, PR #6);
- insertion of a dictated finding classed `absent` (11/148 correct in the production re-score).

**This spec does not decide their fate.** Gate D (§11) chooses between:

| Option | Behaviour |
|---|---|
| **A: keep, routed and visible** | Pre-apply only when the item is a verified, `absent`-class `action` with no slip on the same line (for insertions), or a code-verified contradicted negative (for removals). The item is stored as `status: pre_applied` and shown in the rail and overlay as "added from your dictation · undo" / "removed: contradicted by your dictation · undo". |
| **B: move to one click** | Both become ordinary `action` items. Nothing changes the report before render. |

The two edits may be decided separately. Until Gate D decides, live behaviour is today's (the engine is in shadow), and the shadow log records what each option would have done.

## 10. Item contract, storage, endpoints, flags

### 10.1 `ReviewItem`, the contract the frontend reads

```python
class ReviewItem(BaseModel):
    id: str                               # uuid
    key: str                              # stable: hash(lane, kind, anchor text or line text)
    report_id: str; run_id: str
    lane: Literal["coverage", "accuracy", "additions", "chat"]
    detectors: list[str]
    kind: str
    cls: Literal["action", "minor", "info", "suppress"]
    section: str | None                   # generic heading; None → unanchored group
    anchor: Span | None                   # {start, end, text}; text_hash of the report it was made on
    label: str; reason: str
    edit: Edit | None
    verified: dict | None
    probe: str | None
    citation: dict | None                 # {card_id, source, label}
    source_line: str | None               # the dictated line, for the popover
    status: Literal["open", "pre_applied", "applied", "dismissed", "addressed", "stale"]
    history: list[dict]                   # [{at, event, actor: user|engine|loop, text_hash, detail}]
    engine_version: str
```

### 10.2 Storage (Alembic migration, test-first)

| Table / column | Contents |
|---|---|
| `report_review_runs` | `id, report_id, mode (shadow|live), engine_version, pathway, lanes, timings_ms jsonb, cost jsonb, errors jsonb, created_at` |
| `report_review_items` | the `ReviewItem` columns; `history` jsonb; indexes `(report_id)` and `(run_id)` |
| `report_chat_messages` | `id, report_id, role, content, edits jsonb, applied_item_ids, created_at` |
| `reports.workspace_state` | jsonb: rail tab, expanded items, last `text_hash` |

**Still written** for existing analytics:
- `candidate_reports[0].options_applied`;
- `report_audit_criteria.resolution_method`, while the audit exists.

**Metabase:** a view `v_review_item_events` unnests `history`, for per-kind outcome rates (applied, dismissed, addressed, stale).

### 10.3 Endpoints

| Endpoint | Purpose |
|---|---|
| SSE `candidate` event, field `review` | Coverage and Accuracy items (live mode) |
| `GET /api/reports/{id}/review` | `{run, lanes: {name: status}, items[]}`; the rail polls it until every lane is `done` (as the options endpoint does today) |
| `POST /api/reports/{id}/review/items/{item_id}/events` | `{command, text_hash, detail}` → appends history and sets status |
| `POST /api/reports/{id}/review/probe` | `{text, text_hash, changed_ranges}` → one Jev call: each open item's probe plus contradiction on the changed clauses |
| `POST /api/reports/{id}/review/reprepare` | `{item_ids, text, text_hash}` → one adjudicator call per item, run in parallel (Principle 2; replaces the brainstorm's single batched call) |
| `POST /api/reports/{id}/review/rerun` | manual "Re-review" (replaces Re-audit) |
| chat endpoint (existing) | reply gains `edits[]` (§12.5) |

Every endpoint is owner-scoped like the existing report endpoints.

### 10.4 Flags

| Flag | Values | Default |
|---|---|---|
| `RR_REVIEW_ENGINE` (Railway env) | `off`, `shadow`, `live` | `off`; `shadow` in production after slice A |
| `RR_REVIEW_LANES` | comma list | `coverage,accuracy,additions`; a lane joins `live` only once its gate passes |
| `RR_REVIEW_RAIL` (Railway env) | `0` = kill switch | unset; the rail shows for everyone once the engine is `live` |

There is **no per-user gating**. The engine and rail go live for all users at once. The global flags only give the shadow stage and a kill switch.

**Behaviour by mode:**
- **Shadow:** the engine runs in a background task after the candidate is saved. It writes `report_review_runs` and `report_review_items` with `mode=shadow`, and nothing is sent to the client. `run_quality_check` is untouched.
- **Live:** the engine replaces `run_quality_check` in both pathways.
- **Failure handling:** a lane failure or timeout never blocks the report. That lane's status is `failed`, and the rail shows "Review incomplete".

## 11. Gates

Every gate is a lab or read on real production data, with labels balanced across classes, 2 runs for stability, and **Hassan's hand read as the deciding vote**. The thresholds below are the bar to clear. Where a lab's data shows a natural gap, the threshold is set in that gap and recorded in the ledger.

Data stays in the scratchpad (standing production-read permission). Repo fixtures are **synthetic cases seeded from production**, never raw production text.

**Every Jev wording lab** (B2, the new `can't tell` option in A, the "already in report" Choice in C, and E) reports these alongside accuracy, to set the confidence routing of §6.5:
1. **With vs without an exit option.** The wording suite showed a spare option can absorb probability from the class we care about. The exit option stays only if recall holds.
2. **Where the errors fall:** the share of Jev's errors in the unsure band against the confident bands. The band edges are set in the measured gap.
3. **Calibration:** Brier score, ECE and a reliability table (field research D-03, never run before).
4. **The unsure pile:** its size per report, and how Qwen's adjudication does on it, against Hassan's labels.
5. **Targeted follow-ups:** where a confusion pair dominates the unsure pile, whether same-call follow-ups settle it at least as accurately as Qwen.

**Lab method (lessons from L-50):**
- **20-item pilots are directional only.** Decide go / no-go on paired counts against the baseline. In L-50 a pilot's 0.97 fell to below baseline at 100 items.
- **Adoption needs ≥ 100 balanced items with difficulty-category tags,** and per-category results. The run-2 stability check can use a stratified subset (40 items, 5 per category).
- **Labelling rules go into the shared prompt before labelling.** A rule added between runs confounds comparisons; record it if it happens.
- **Smoke-test 2 items on every arm before each live run.** Both L-50 structured-output failures were caught this way.
- **Latency:** p90 measured at 4 concurrent calls includes provider queueing (stalls of about 64 s), so measure latency sequentially when it gates a decision.
- **Calibration needs hard or real items.** Clean synthetic wording items produced no unsure answers, so the escalation bands of §6.5 must be set on real data.

### Gate A: Coverage recall
*Data:* the 50 v3 cards. Hassan labels the 23 disputed cards (2, 3, 4, 5, 6, 7, 9, 24, 25, 28, 31, 33, 35, 38, 39, 40, 42, 43, 44, 47, 48, 49) plus #18 (the data question). Then every Jev flag in the source reports (~72) is adjudicated, not a sample.

*Change under test:* adjudicator v4, with the minor tier, no veto, no flip rule and the uncertain → minor wording.

*Balance:* if Hassan's labels hold fewer than 10 `action` labels, add synthetic cases seeded from the disputed material losses (descriptor drop, size change, differential order, missed lesion, scope word "all").

*Pass:*
- **Recall:** every Hassan-labelled material loss (the ~6 named in `feedback_review_item_policy`) is shown, as `action` or `minor`; ≥ 90% of all Hassan `action` labels are shown.
- **Precision:** ≥ 85% of `action`-class items are `action` by Hassan's label (v3 baseline: 7/7).
- **Noise:** `minor` holds no more than 2 shown items per report on median.
- **Stability:** across 2 runs, ≤ 10% of items change class, and no item moves between shown (`action`/`minor`) and hidden (`suppress`).

### Gate B: Accuracy (alignment, code checks, grounding)
*Data:* the 41 production reports from the audit comparison, including the four fabrication cases (599d7c97, 16cb806c and the rest listed in the pipeline session's `audit_compare/compare.json`). The kinds seen are an invented finding (hiatus hernia), an invented prior study, an invented measurement ("CBD 6 mm") and certainty upgrades.

**B1, code (alignment plus checks):**
- Alignment is hand-checked on 10 reports: ≥ 95% of report clauses correctly paired or correctly unmatched.
- Code catches every fabricated number, prior study and certainty upgrade in the fabrication cases. An invented finding with no number (the hiatus hernia type) is B2's job, not code's.
- False alarms: ≤ 1 per report on mean across the 41, after hand read.
- The `inconsistent` checks catch the audit's useful anatomical_accuracy cases that are modality or size-word errors.

**B2, the Jev wording lab for "is this positive finding stated":**
- *Baseline:* L-46 naive wording, 5/32 with 49 false alarms.
- *Data:* ≥ 30 unsupported positive clauses (production fabrications plus synthetic ones seeded from them) and ≥ 30 stated clauses, including hedged and paraphrased ones.
- *Candidates:* at least 3 wordings, following the wording-suite rules (quote the clause; "including as a possibility"; criteria pointing the same way as the instruction). Each is tried as a noul and as a Choice of `stated` / `not stated` / `can't tell`. The hypothesis is that the L-46 false alarms land in `can't tell` and reach Qwen, instead of being flagged.
- *Recall and false alarms* are counted after escalation: an item answered `can't tell` counts as caught or flagged according to what the adjudicator decides.
- *Pass:* recall ≥ 90%, false alarm ≤ 5% on stated clauses, with a margin wide enough to survive repeat drift (0.2).
- *If it fails:* `unsupported` ships code-only, and the Jev question stays out.

### Gate C: Additions (guideline prototype and clinical pass)
*Data:* stored `enhancement_json` synthesis for the same 41 reports. Candidates go through mapping → "already in report" gate → adjudicator, and are rendered as cards for Hassan to read.

*Pass:*
- **Hard:** zero grade or threshold inferred from an undictated feature; zero management outside radiology remit; zero items that add a second recommendation line to the core.
- ≥ 80% of `action`-class guideline items judged correct and useful by Hassan.
- The clinical pass surfaces the known safety-critical misses from the audit comparison, with less noise than the audit's recommendations criterion (4/20 useful).
- Urgency tiers are agreed against the audit's 16/22 useful banners, with no more false banners than today.
- **Grade items (L-50):** on `s1_phase3.json` plus the production cases, report false "can't grade" (baseline 0.16) and overcalls from silence. `characterise` stays `minor` unless false "can't grade" is ≤ 10%.
- **Criteria-supply arm:** the adjudicator with vs without the synthesis `criteria` text. Adopt it if false "can't grade" drops with no rise in overcalls (paired counts at ≥ 100 items).

### Gate D: production audit of the automatic edits (read-only)
*Data:* every quick report since L-49 (2026-10-01) with an automatic edit in `quality_check`. If fewer than 20 edits exist, extend back to L-47 (2026-09-30), or replay the current code on earlier reports.

*Read:* each edit is hand-classed correct / redundant / harmful. Harmful means invented, duplicated, incoherent, or a whole-line rewrite. Then the same reports are re-scored with the edits routed through the shadow adjudicator and verifier.

*Decision rule, per edit type:*
- **Option A** if, routed through the engine, it is ≥ 95% correct with zero harmful.
- **Option B** otherwise.

Hassan confirms the decision. It is recorded in the ledger.

### Gate E: probe loop (rebuilt spike)
Rebuild the 2026-09-30 probe spike on the items produced by Gates A–C (the scripts were not kept).

*Pass:*
- ≥ 95% of resolutions caught at 0.8;
- ≤ 1% false "addressed";
- every opposite-polarity false hit caught by contradiction at 0.6;
- adjudicator-written probes tested in the same run.

### Gate F: shadow read
At least 3 days of production shadow output, across both pathways where templated traffic exists. Hassan hand-reads 20 reports.

*Pass:*
- lane failures or timeouts ≤ 1%;
- Coverage plus Accuracy p90 wall-clock ≤ today's `run_quality_check` p90 + 3 s;
- the Gate A–C bars hold on the shadow sample.

### Gate G: before going live
The evaluation from the brainstorm: de42a105, one templated report and about 8 others, hand-read. Then a live check in Chrome on both sides (memory `reference_prod_smoke_testing`; the tab must be visible).

### Dependencies
- Gates A–D run in parallel and need no engine code.
- Each lane may join `live` once its gate passes.
- Gate E precedes the live loop going live.
- Gates F and G precede `live`, which switches the engine and rail on for everyone.

## 12. The rail

This section carries over the brainstorm outcome unchanged except where noted.

### 12.1 Layout
- The rail is always open beside the editor in `ReportResponseViewer`. Below about 1100 px it collapses to a strip showing the open count and opens as an overlay.
- Tabs: **Review** and **Guidelines**. Guidelines content moves across as it is.
- The narrow/dual/tri layout modes go away.
- **Urgency** is a banner at the top of the rail.
- **Grouping:** items are grouped by report section (generic headings from `artifacts.sections`), with an "Unanchored" group at the end. Each row shows its lane badge(s).
- **Rendering by class:**
  - `action`: a card;
  - `minor`: a compact, low-salience row with the fix ready;
  - `info`: a subtle tag;
  - `pre_applied`: "added from your dictation · undo" (only under Gate D option A).
- No score. Passes and dismissed items fold into "▸ N other checks passed".

### 12.2 Editor overlays (CM6)
- Every anchored item gets an underline coloured by kind group (coverage / accuracy / additions) and a gutter marker. `minor` uses a dotted underline; `info` has no underline, only a gutter tag.
- Clicking an overlay opens a popover with the edit as a diff, plus Apply / Edit / Dismiss. Edit opens the replacement for in-place adjustment, then runs the verifier code guards.
- **Sync:** the rail and overlays share one store, so applying or dismissing in either view updates the other.
- **Anchors** map through edits with CM6 `mapPos`. A lost anchor → `stale`.
- **Reuse:** `lib/dictation-lab/pendingMarks.ts`, `ghostText.ts`, `IntelliPromptsMargin.svelte`.

### 12.3 Item actions and the command registry
Every rail action is a named command in a registry (`lib/review/commands.ts`): `apply`, `undo`, `edit`, `dismiss`, `apply_all(lane|kind)`, `ask_chat`, `rerun`, `finalise`, `open_item`, `next_item`.

- Commands are pure: state plus arguments → `TextEdit` plus events.
- Each command posts an item event.
- **Undo** reverts only if the applied `replace` is still present verbatim.

This leaves room for the later dictate-to-edit controller.

### 12.4 Live probe loop
Triggers: a command, a chat edit, or about 1.5 s after typing stops.

1. **One Jev call** (`/review/probe`) runs each open item's probe, plus contradiction on the changed clauses.
2. **Addressed:** probe ≥ 0.8 → `addressed`.
3. **Contradiction:** ≥ 0.6 on a changed clause → a new `accuracy/contradicted` item. If it is a negative, its fix is code-only removal.
4. **Re-prepare:** code checks anchors and locality. Affected items (anchor lost, paragraph touched, probe in 0.5–0.8) show "updating…" and are re-prepared through `/review/reprepare`, one adjudicator call per item.
5. **Staleness:** every answer carries `text_hash`, and out-of-date answers are discarded.

The full engine never re-runs automatically; Re-review is manual. Thresholds are confirmed in Gate E.

### 12.5 Chat edits
- Sending a message switches the rail to the thread, with a strip reading "← Review · N open". "⤢ Expand" widens the rail.
- **Reply shape:** prose plus an optional `edits[]` (`{section, find, replace}`), not a whole-report proposal.
- **Checks:** each edit goes through the verifier.
- **Context:** the request includes the open items, so chat doesn't duplicate them.
- **Applied edits** become `lane: chat` items linked to their message. Unapplied ones stay in the thread.
- **Fallback:** items with no verified fix show "Ask in chat", which pre-fills the item.

### 12.6 Sessions and History
- **Sessions** are live and continuous. History reopens the full viewer and rail from saved data (items, chat, `workspace_state`), with nothing re-run.
- **Recording:** every outcome is an item history event, exposed through `v_review_item_events`.
- **Finalise** still writes `options_applied`.

### 12.7 Routes and flags
- The rail renders for every user when `GET /review` reports `mode: live` and `RR_REVIEW_RAIL` ≠ 0. In `off` or `shadow` mode, and when the kill switch is set, today's UI is unchanged. The frontend therefore merges dark and lights up when the backend goes live.
- **`/dev/review-rail`** renders saved shadow runs against their reports, for the Gate F read and rail development. It ships with `+page.ts` `requireDevRoute()` from its first commit, as does any lab or labelling page.

## 13. Testing

| Layer | How |
|---|---|
| Alignment, code checks, merge, verifier guards, storage, endpoints | test-first pytest; synthetic fixtures seeded from production cases |
| Lanes and adjudicator | unit tests with mocked Jev and Qwen calls (shape, routing, failure paths, overflow cap); golden fixtures from Gates A–C replayed against mocks |
| Model behaviour | the separate live evaluation harness (`scripts/review_engine_eval.py`), reusing outputs and writing to the scratchpad with pid in filenames (memory `feedback_eval_economy`); 2 runs maximum |
| Frontend logic and commands | vitest; `impressionOptions.test.ts` grows to FINDINGS anchoring and `upgrade` |
| Rail and overlays | vitest-browser (Chromium 1194) |
| End to end | Gate G in Chrome |

Tests start with one case per kind and grow only where a gate exposes a weakness. Each weakness gets a targeted stress set seeded from the production case that showed it.

## 14. Build sequence

0. **Labs:** Gates A–D, in parallel.
1. **Slice A, engine (backend, TDD):**
   - alignment, checks, item contract, migration, `store.py`, endpoints;
   - lanes as interfaces with the existing detectors wired in;
   - adjudicator v4 and verifier;
   - `RR_REVIEW_ENGINE=shadow` in production.
   Lanes switch on as their gates pass.
2. **Slice B:** frontend item store, the command registry, edit application (FINDINGS anchoring, `upgrade`).
3. **Slice C:** the rail and overlays, hidden until the engine is `live`, plus `/dev/review-rail` guarded.
4. **Slice D:** chat edits.
5. **Slice E:** sessions and History, the Metabase view.
6. **Gates E, F and G.** Then `RR_REVIEW_ENGINE=live`: the engine and rail go on for everyone.
7. **Retire:** `AuditBanner`, the audit criteria endpoints from the UI path, `OptionalAdditions`, the `ReportEnhancementSidebar` drawer and `run_quality_check`'s flag-only output. Then turn on `RR_TEMPLATE_MIRROR`.

Slices B–E can start once §10.1 is fixed. They develop against shadow runs through `/dev/review-rail`.

## 15. Points for Hassan's review

These are interpretations made while writing the spec. Each follows the principles, but none was spelled out in the agreed direction:

1. **Brief options are not re-adjudicated** (§6.4). The brief already judged and wrote them, so they arrive as `minor` and only pass de-duplication, the "already in report" gate and the verifier. The exception is the `upgrade` case.
2. **Re-prepare uses one call per item, in parallel** (§10.3, §12.4), rather than the brainstorm's single batched call. This follows Principle 2.
3. **No runtime stability rule.** Stability is a lab metric (Gates A and F), never a run-time flip → suppress rule.
4. **v1 `inconsistent` is code-only.** An LLM anatomy check joins only if Gate B shows the need.
5. **Gate thresholds** are the proposed bar. They move into measured gaps once each lab runs.
6. **Jev confidence routing** (§6.5), added at Hassan's request (2026-10-02). Unsure answers go to the adjudicator by default. Targeted same-call Jev follow-ups are an upgrade for named confusion pairs, each needing lab evidence. The verifier marks an unsure fix `unconfirmed` rather than asking Qwen to grade its own fix.
7. **Gradability lab folded in** (L-50, 2026-10-03): one adjudicator call stays; `characterise` capped at `minor`; flat Qwen schemas; the criteria-supply lead goes into Gate C; Jev follow-ups demoted.
