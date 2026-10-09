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

### Second problem: "implicated" and pertinent negatives are the same thing, labelled two ways

The implicated definition (default-negatives policy, 2026-10-03) is the local consequence or extension of a dictated finding: the structure itself, its neighbours, its levels. Every finding-linked pertinent negative ("no mediastinal invasion" beside a lung mass) fits that definition by construction. Silence policy 1 licenses stating it; the default-negatives policy says to highlight it. Both lead to the same treatment: in the report, highlighted.

Today that one judgement is expressed two ways. The classifier and the atoms produce an implicated `check` card. Brief finding-linked negatives produce nothing. Trace 2 is the result.

The brief's mandatory-negatives labeller also has no implicated or dictated tier, only keep / contradicted / expected:
- **pancreas de42a105:** "No pancreatic ductal dilatation" beside a head mass, "No calculus in the CBD" beside an obstructed duct, and peripancreatic and porta hepatis node negatives are all labelled keep. They show as routine green normals, like "the spleen is unremarkable".
- **pancreas 29882bd7:** dictated "no SMA involvement" was labelled keep, so it would be tinted "AI-added". Dictated "No ascites" was labelled **contradicted**, because the labeller had no dictated option and was forced into a wrong choice. It is harmless today only because the generator copies the dictation anyway.

## 2. Rule

One owner per judgement:

- **Selection** (should it be said) → the brief.
- **Verification** (does the written clause contradict the dictation) → Jev, in the post-gen check.
- **Classification** (dictated / default / implicated, as shown to the reader) → whoever created the statement: the brief for its labels, the review classifier only for statements no brief label anchors to.

**Implicated stays an internal label but is no longer its own UI card.** In both labellers it remains the doubt buffer, which keeps false contradictions at 0 (Jev negatives lab). In the UI, implicated statements and finding-linked pertinent negatives become one amber category: "AI-added negative bearing on your finding: in the report, worth a glance". The amber mark and its hover reason are the check. The rail keeps only conflicts, contradictions and number errors.

**The brief's mandatory-negatives labeller moves to the full scheme** used by atoms and the classifier: dictated / default / implicated / contradicted, plus expected (§3.0). Every brief negative and atom then carries the same label set.

The generator, the Jev contradiction question and the classifier prompt are unchanged.

## 3. Components

### 3.0 Brief mandatory-negatives labeller (`report_reconcile.py`, `quick_report_brief.py`)

- `NegativeDecision.action` becomes `dictated | default | implicated | contradicted | expected`. Each label's definition is taken word for word from the classifier and atom prompts (`review_engine/prompts/negatives.txt`, `linked_normals.py`), so all three labellers apply one definition. Expected keeps its current meaning: a dictated finding would normally and predictably cause what the negative denies.
- Compiled brief text:
  - dictated → `DICTATED` (the generator writes the dictation as usual; no extra instruction);
  - default → `KEEP`;
  - implicated → `KEEP (implicated by: <finding>)`;
  - contradicted → `OMIT`;
  - expected → `DO NOT ASSERT` (unchanged).
- Rendering follows the default-negatives policy: implicated is included by default, exactly like default. Only the review layer's salience differs.
- Finding-linked negatives keep their own routing (`route_finding`: stated / do_not_assert / offered / dropped). Their stated ones take the label from this call when the call covers them, and are otherwise treated as implicated.
- This is a prompt change to the call that does selection, so it is gated by a lab (§5.0).

### 3.1 `brief_anchor` (new, `backend/src/rapid_reports_ai/brief_anchor.py`)

Runs once per report inside the post-gen check, before render.

**Input**
- Final report text, split by the existing `report_review.clauses_in_context` (FINDINGS + IMPRESSION; recommendations excluded).
- Brief labels, flattened into one list. Each label carries a stable `ref`:
  - `neg:<i>`: `decisions["negatives"][i]`, with `action` dictated / default / implicated / contradicted / expected (§3.0) and `source` sheet / finding:<key>;
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

- **Dictated beats OMIT.** When a dictated label (`dict:<i>`, or `action` dictated) anchors to a clause, any OMIT / DO NOT ASSERT label on the same clause is ignored: no removal, no card. It is logged in `run.lanes["anchor"].brief_errors` (example: 29882bd7's dictated "No ascites" labelled contradicted). A dictated negative is never removed (PR #6 / L-49).
- **Anchored KEEP clause flagged as a contradiction** (any label with `action` dictated / default / implicated, or atom keep / implicated): never auto-removed. Emit a review flag `{kind: "brief_conflict", clause, ref, score}`. The review engine turns it into a `check` item, cls "conflict", with a one-click code remove edit; dismiss means keep.
  - *Example:* "No contralateral pleural effusion" (brief KEEP) beside a dictated "small right pleural effusion". Today the removal gate (contradiction ≥0.6, restated ≥0.5, dictated <0.5) would remove it. Under this design it stays, and a conflict card appears.
- **Anchored OMIT / DO NOT ASSERT clause** (`action` contradicted / expected, atom do_not_assert): auto-remove before render only when both hold:
  1. no KEEP-type label anchors to the same clause; and
  2. Jev's contradiction score on the clause is ≥ 0.6.
  The removal is code-only, via the existing `remove_negative_clause`, recorded in `applied_edits` and surfaced as a `pre_applied` `removed` item with undo. With only one of the two signals, emit a `brief_conflict` flag instead.
- **Unanchored clauses:** today's logic, unchanged. These are the generator's own statements.

### 3.3 Review engine

- `engine.py` reads `quality_check.anchors` from the stored candidate.
- **Anchored clauses:** items come from the brief label. Their spans join `owned`, and the classifier never sees them.
- **Label → item, one mapping for brief labels and classifier labels:**

  | Label | Item | `evidence.form` (tint) |
  |---|---|---|
  | dictated | none | none |
  | default | `assumed_normal` | `normal` (green) |
  | implicated | `assumed_normal`, with `evidence.pointer` (the finding) and a plain reason | `negative` (amber) |
  | finding-linked negative (`source: finding:<key>`), stated | `assumed_normal`, with pointer and reason | `negative` (amber) |
  | contradicted | §3.2 rules (removal or conflict card) | — |

  Implicated no longer produces a `check` / "uncertain" card. The same mapping applies to the classifier's own implicated verdicts on unanchored clauses.
- **Clauses nobody anchored:** the classifier's label decides the tint. Today's `statement_form` shape rule is only the fallback when no label exists.
- **Classifier:** receives only clauses that no anchor covers. The undictated-number check still runs on every clause.
- **Unanchored labels:** logged in `run.lanes["anchor"] = {anchored, by_term, by_jev, unanchored: [{ref, source, action}]}`. No rail item.
- **Reports with no `anchors`** (generated before this ships): fall back to today's `brief_normals` path.

### 3.4 Frontend

Every output uses existing item kinds: `assumed_normal`, `check` (conflict, with a remove edit), and `removed` / `pre_applied`. `field.ts` already reads `evidence.form`.

One thing to check in the plan: an amber `assumed_normal` mark must show its reason on hover ("Implicated by: enlarged right hilar nodes" / "Pertinent negative for: Lung mass"). If the mark popover does not yet render `evidence.pointer` / the reason for `assumed_normal`, add it. That is the only possible frontend change. The legend's amber entry is relabelled "Bears on your finding".

## 4. Failure handling

| Condition | Behaviour |
|---|---|
| Jev error or timeout in pass 2 | Term anchors stand; the rest are unanchored and judged as today |
| No `decisions` (brief failed) | No anchors; today's behaviour |
| Old report without `anchors` | Engine uses today's `brief_normals` anchoring |
| `RR_GROUPED_NORMALS` off | Negatives and dictated labels still anchor; no atoms |
| Kill switch `RR_BRIEF_ANCHOR=0` | Anchoring skipped end to end; today's behaviour |

## 5. Evaluation (eval-economy protocol)

### 5.0 Brief labeller lab (gate before §3.0 ships)
- About 30 cases: the cached sheets and dictations of the stored Oct 1–6 cases, plus synthetic cases across at least four domains (abdomen, thorax, neuro, MSK). Repo fixtures stay synthetic.
- The traps:
  - a dictated negative in sheet wording ("No ascites");
  - a dictated negative in other wording ("no SMA involvement" vs "No encasement of the SMA");
  - local extension (implicated) vs distant site (default under process of exclusion);
  - an expected consequence vs a merely plausible one.
- Compare against the stored baseline labels and Claude peer-read gold labels; Hassan spot-checks only the boundary items.
- **Gate:**
  - contradicted recall is no lower than baseline (selection must not regress);
  - dictated recognised ≥95%;
  - 0 dictated negatives labelled contradicted;
  - implicated vs default within the policy on the peer read.
- On a miss, ship §3.1–§3.4 with today's labeller. Brief negatives then map keep → default and finding-linked → amber.

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
  - trace 2: no card, amber on "no contralateral hilar lymphadenopathy";
  - trace 3: amber (implicated) on the station clause, not green;
  - trace 4: at most one dismissible conflict card and no removal.
- On 29882bd7: "No ascites" and "No encasement of the SMA" labelled dictated, so no tint and no card.
- On de42a105: pancreatic duct, CBD calculus and peripancreatic negatives amber; hepatic negatives green.
- Rail cards per report: only conflicts, contradictions and number errors. No "uncertain" cards.
- 0 brief-anchored clauses re-labelled by the classifier.
- 0 false auto-removals.
- Classifier statement count down ≥50% vs baseline, with negatives wait reduced accordingly.
- Unanchored rate reported per source (the baseline for gap 1, lost dictated negatives).

## 6. Out of scope
- Templated path (review rail is quick-path only).
- A rail card for unanchored labels. Revisit once §5 gives the unanchored precision.
- Hover pointer "for: <finding>" on pertinent negatives.
- Changes to the generator prompt, the classifier prompt, or brief prompts other than the mandatory-negatives labeller (§3.0).
- Linked prose for negatives (handover step 3). It builds on these anchors.

## 7. Ledger
Record under the next free L-number (L-59+ may first be taken by the PRs #12–#15 backfill) when the plan lands, with the lab result and the success-bar numbers.
