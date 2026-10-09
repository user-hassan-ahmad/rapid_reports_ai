# Negatives: one owner per judgement

**Date:** 2026-10-09 · **Status:** design agreed, plan not written · **Path:** quick report only
**Follows:** review rail handover 2026-10-09, plan step 2 ("one owner for negatives")

## 1. Problem

A negative statement in a quick report ("no mediastinal invasion", "the liver is unremarkable") is judged up to three times:

| Stage | Model | Judgement it makes |
|---|---|---|
| Brief (`quick_report_brief.py`, `linked_normals.py`) | Qwen, before generation | Should this be said? (keep / contradicted / expected; atoms: dictated / default / implicated / contradicted) |
| Post-gen check (`report_review.run_quality_check`) | Jev, on the written clause | Does this clause contradict the dictation? |
| Review classifier (`review_engine/negatives.py`) | Qwen, ~5.5–7.6 s | Is this statement dictated, default, implicated or contradicted? |

The brief's labels reach later stages only for linked-normal atoms, and only when the atom's rendered sentence or term is found verbatim in the report (`review_engine/brief_normals.py`). Mandatory and finding-linked negatives (`decisions["negatives"]`, `decisions["finding_negatives"]`) are stored with the report but no later stage reads them. The post-gen check receives no brief input at all.

### Worked case (prod d3d1e0a5, CT thorax, 2026-10-06)

1. **Selection works.** The brief marked the sheet negatives "No pleural effusion", "No adrenal abnormality" and "No contralateral pulmonary nodule" as contradicted. None reached the report. Both dictated negatives survived.
2. **The classifier overrules the brief, wrongly.** The brief kept "No contralateral hilar lymphadenopathy or vascular encasement" as the finding-linked negative for the dictated right hilar nodes. The classifier re-judged it from scratch as *implicated*, and the rail showed a false "may not hold given enlarged right hilar lymph nodes" card.
3. **The brief's doubt is lost after rewording.** The brief labelled atom "Mediastinal lymphadenopathy" *implicated*. The generator expanded it into "No paratracheal, subcarinal, prevascular, aortopulmonary or para-aortic lymphadenopathy", so the anchor failed: the brief's check card had no anchor. The classifier then labelled all four clauses *default* (assumed normal). A real staging doubt was downgraded silently.
4. **Verification runs blind.** The brief marked "Adrenals" do-not-assert, and the generator wrote "…right adrenal… unremarkable". Jev flagged the sentence as a contradiction (0.87) without knowing it was the brief's deliberate rewrite.
5. **Cost.** The review took 9.7 s in total, of which 7.6 s was the negatives classifier.

Root cause of 2–4: there is no reliable link from a brief label to the words the generator wrote.

## 2. Rule

One owner per judgement:

- **Selection** (should it be said) → the brief.
- **Verification** (does the written clause contradict the dictation) → Jev, in the post-gen check.
- **Classification** (dictated / default / implicated, as shown to the reader) → whoever created the statement: the brief for its labels, the review classifier only for statements no brief label anchors to.

The brief's prompts and labels, the generator, the Jev contradiction question and the classifier prompt are unchanged. This design adds an anchoring step and changes how the later stages consume its output.

## 3. Components

### 3.1 `brief_anchor` (new, `backend/src/rapid_reports_ai/brief_anchor.py`)

Runs once per report inside the post-gen check, before render.

**Input**
- Final report text, split by the existing `report_review.clauses_in_context` (FINDINGS + IMPRESSION; recommendations excluded).
- Brief labels, flattened into one list. Each label carries a stable `ref`:
  - `neg:<i>`: `decisions["negatives"][i]`, with `action` keep / contradicted / expected and `source` sheet / finding:<key>;
  - `atom:<pid>:<atom id>`: linked-normal atoms from `decisions["normals"]`, with `action` keep / implicated / do_not_assert / dictated;
  - `dict:<i>`: `decisions["dictated_negatives"][i]`.

**Pass 1, code term match**
- Derive each label's key term. For an atom, use `atom.term`. For a negative, use the denied phrase with "No"/"identified" boilerplate stripped, e.g. "mediastinal invasion".
- A label anchors to a clause when the term occurs inside a negative or normal clause of the same section.
- A match counts only if exactly one label claims that clause span. When two or more labels claim overlapping spans, all of them fall through to pass 2. Example: OMIT "No pleural effusion" and KEEP "No contralateral pleural effusion" both match "No contralateral pleural effusion or pleural thickening".

**Pass 2, Jev link (misses and overlaps only)**
- For each label still unanchored, ask Jev whether each remaining negative/normal clause in the section "expresses" the label (same shape as the lab-passed D1/A1 atom↔prose link). Accept the highest-probability clause at P ≥ threshold set by the wording lab (§5.1). Within one overlap group, more specific wording wins: a label whose qualifier ("contralateral", "right", "additional") appears in the clause beats one without it. If still ambiguous, every label in the group stays unanchored.
- All Jev calls run in parallel, alongside the existing contradiction batch.

**Output**
`anchors: [{ref, source, action, clause_id, span, how: "term" | "jev" | "none", p}]`, persisted to `candidate_reports[0].quality_check.anchors`.

**Replaces** the sentence/term anchoring inside `review_engine/brief_normals.py`. `brief_normals` keeps building items, but takes its spans from `anchors`.

### 3.2 Post-gen check (`report_review.py`)

`run_quality_check` gains an optional `brief_decisions` argument (passed from `quick_report_generator.py`). Jev still asks `Q_CONTRA` of every clause. After anchoring:

- **Anchored KEEP clause flagged as a contradiction** (any label with `action` keep, `dictated`, or atom keep / implicated): never auto-removed. Emit a review flag `{kind: "brief_conflict", clause, ref, score}`. The review engine turns it into a `check` item, cls "conflict", with a one-click code remove edit; dismiss means keep.
  - *Example:* "No contralateral pleural effusion" (brief KEEP) beside a dictated "small right pleural effusion". Today the removal gate (contradiction ≥0.6, restated ≥0.5, dictated <0.5) would remove it. Under this design it stays, and a conflict card appears.
- **Anchored OMIT / DO NOT ASSERT clause** (`action` contradicted / expected, atom do_not_assert): auto-remove before render only when both hold:
  1. no KEEP-type label anchors to the same clause; and
  2. Jev's contradiction score on the clause is ≥ 0.6.
  The removal is code-only, via the existing `remove_negative_clause`, recorded in `applied_edits` and surfaced as a `pre_applied` `removed` item with undo. With only one of the two signals, emit a `brief_conflict` flag instead.
- **Unanchored clauses:** today's logic, unchanged. These are the generator's own statements.

### 3.3 Review engine

- `engine.py` reads `quality_check.anchors` from the stored candidate.
- **Anchored clauses:** items come from the brief label. KEEP / default → `assumed_normal`; implicated → `check` (uncertain); dictated → no item. Their spans join `owned`, and the classifier never sees them.
- **Classifier:** receives only clauses that no anchor covers. The undictated-number check still runs on every clause.
- **`evidence.form` by origin** on anchored items:
  - `source: finding:<key>` → `negative` (amber, "pertinent negative chosen for a finding");
  - sheet negatives and normal atoms → `normal` (green);
  - dictated → no tint.
  Clauses nobody anchored keep today's `statement_form` fallback.
- **Unanchored labels:** logged in `run.lanes["anchor"] = {anchored, by_term, by_jev, unanchored: [{ref, source, action}]}`. No rail item.
- **Reports with no `anchors`** (generated before this ships): fall back to today's `brief_normals` path.

### 3.4 Frontend

No change. Every output uses existing item kinds: `assumed_normal`, `check` (uncertain / conflict, with a remove edit), and `removed` / `pre_applied`. `field.ts` already reads `evidence.form`.

## 4. Failure handling

| Condition | Behaviour |
|---|---|
| Jev error or timeout in pass 2 | Term anchors stand; the rest are unanchored and judged as today |
| No `decisions` (brief failed) | No anchors; today's behaviour |
| Old report without `anchors` | Engine uses today's `brief_normals` anchoring |
| `RR_GROUPED_NORMALS` off | Negatives and dictated labels still anchor; no atoms |
| Kill switch `RR_BRIEF_ANCHOR=0` | Anchoring skipped end to end; today's behaviour |

## 5. Evaluation (eval-economy protocol)

### 5.1 Wording lab: Jev link question (gate before pass 2 ships)
- About 60 (label, clause) pairs: synthetic, plus clauses lifted from cached cases (text kept in the scratchpad).
- Include the trap set:
  - contralateral vs ipsilateral;
  - additional vs index lesion;
  - a station list vs "mediastinal lymphadenopathy";
  - a negative merged into a dictated clause ("no definite chest wall involvement" vs "no chest wall invasion");
  - a do-not-assert organ rewritten to the unaffected side ("right adrenal").
- **Gate:** ≥95% accuracy and 0 cross-claims in the trap set. On a miss, ship pass 1 only. Pass-2 labels then stay unanchored, which is safe (§4).

### 5.2 Code-only stage
Run `brief_anchor` on the stored Oct 1–6 cases (8 with brief decisions) with no regeneration. Hand-read the anchor table: every anchor correct, overlap groups resolved or left unanchored.

### 5.3 One end-to-end run
About 6 targeted cases, including d3d1e0a5 and a pancreas case, against the stored baseline.

### Success bar
- On d3d1e0a5:
  - trace 2 produces no card;
  - trace 3's implicated check is anchored on the station clause;
  - trace 4 produces at most one dismissible conflict card and no removal.
- 0 brief-anchored clauses re-labelled by the classifier.
- 0 false auto-removals.
- Classifier statement count down ≥50% vs baseline, with negatives wait reduced accordingly.
- Unanchored rate reported per source (the baseline for gap 1, lost dictated negatives).

## 6. Out of scope
- Templated path (review rail is quick-path only).
- A rail card for unanchored labels. Revisit once §5 gives the unanchored precision.
- Hover pointer "for: <finding>" on pertinent negatives.
- Changes to brief prompts, generator prompts or the classifier prompt.
- Linked prose for negatives (handover step 3). It builds on these anchors.

## 7. Ledger
Record under the next free L-number (L-59+ may first be taken by the PRs #12–#15 backfill) when the plan lands, with the lab result and the success-bar numbers.
