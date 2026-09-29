# Policy 1 for confirmed branches — negatives that follow a confirmed diagnosis

**Status:** design approved in conversation 2026-09-29, not built · **Ledger:** L-45 (to open)
**Depends on:** compiled brief (bd938a0), policy 1 (`docs/superpowers/research/2026-09-29-sheet-reconciliation-bakeoff.md`)
**Sub-project 1 of 2.** Sub-project 2 (a side panel of optional items grouped by report
section) gets its own spec once this payload shape is settled. See "Hand-off to the UI spec".

## Problem

Prod report `064ff6f1` (CT AP with contrast, history "jaundice"; dictated 3 cm pancreatic head
mass, distal CBD compressed to 12 mm, intra- and extrahepatic duct dilatation). The report
named the mass and the obstruction but said nothing about the features that decide
resectability: SMA / SMV / portal vein / coeliac contact, peripancreatic extension. The QA
audit flagged exactly this (`characterisation_gap`, severity critical).

Under policy 1 the report should have said it. By reporting convention, a finding whose
imaging sign is visible on this technique but was not dictated was not seen. Vessel contact is
visible on contrast CT and was not dictated. So the report should have stated those
negatives, as it already did for "No focal hepatic lesion" and "No porta hepatis
lymphadenopathy" (both correct under policy 1).

## Root cause

Policy 1 is implemented for one thing only: **closing differential branches.** Nothing handles
the next step, when the dictation *confirms* a branch.

1. **The sheet is written before anything is dictated.** Its mandatory negatives answer the
   clinical question as asked. None of them is a negative that only matters once a diagnosis
   is confirmed. The analyser prompt forbids that kind: "each bears on a specific differential
   … one per differential the imaging meaningfully bears on".
2. **The staging features exist only as descriptors of what is present:** In-scope companions,
   one Measurement convention, exemplars.
3. **The brief removes the carriers.** It always drops In-scope companions
   (`DROP_TOP_BULLETS`). The measurement convention survives only when Qwen marks it
   applicable, which varies between runs.
4. **The generator can't bridge the gap.** Missing Data Handling licenses undictated
   negatives only when the sheet lists them. A descriptor with no listed negative falls under
   the no-fabrication rule, so the generator says nothing, and nothing records that a
   required item was left out.

Recompiling the brief locally from the stored sheet and dictation confirms it. Jev marks
"Pancreatic head mass (adenocarcinoma)" **present**, and the branch is closed correctly. After
that no staging negative exists anywhere in the brief.

## Decisions (2026-09-29)

1. **Stated by default.** A confirmed-branch negative that is not ambiguous is stated in FINDINGS
   like any KEEP mandatory negative.
2. **Ambiguous means offered (rule C).** A negative is stated only if **both** of these hold:
   - the branch is **clearly** confirmed (Jev `present` ≥ high cut-off);
   - the analyser tagged the negative **core**.

   Otherwise it is offered as an optional item. The two tests cover different doubts: whether
   the diagnosis is confirmed, and whether the negative is standard practice.
3. **The impression stays a synthesis.** Confirmed-branch negatives belong in FINDINGS. One
   reaches the impression only when the impression plan judges it changes interpretation.
   They never form a list of negatives there.
4. **Optionals are their own tier,** separate from the impression/recommendation options, and
   tagged with the report section they would go into.
5. **Dictated findings outside the sheet's differentials** are still always reported (the
   dictation is the source of truth; `input_fidelity` audits it). They get no confirmed-branch
   negatives, because no branch exists for them. Out of scope; noted, not built.

## Who decides what

No new model calls. Each question goes to whoever is good at it (see the bake-off doc and
`reference_jev_capability_profile`).

| Question | Decided by | Basis |
|---|---|---|
| Does the dictation confirm this branch, and how clearly? | **Jev**, `present` score (existing parallel call) | Text matching; 10/11, no false positives in the bake-off; calibrated score gives the band |
| Is this negative *core* or *contextual*? | **Analyser**, at sheet time | Clinical judgement about practice; written during dictation, no runtime cost |
| Against this dictation: keep, contradicted, or expected consequence? | **Qwen**, reasoning off (existing negatives call) | "Expected" needs clinical reasoning; Qwen 0.88 vs Jev 0.65 (Jev over-calls it) |
| Stated, offered, or dropped? | **Code** | Rules below |

## Design

### 1. Analyser — opt-in directive `confirmed_negatives`

It ships as a `DIRECTIVES` entry, so production stays byte-identical until you sign it off (v1
subtraction rule). Being appended text, it reaches both prompt families without editing either
base prompt.

The sheet gains one Companion Matrix bullet:

```
- **If confirmed:** (negatives stated only when the dictation confirms the branch)
  - <differential name exactly as in Differentials in scope> → "<negative in report form>" (core | contextual)
```

The directive, drafted to be case-agnostic (structural form, no clinical example):

> **If confirmed.** For each differential tagged *visible on this technique: yes* whose
> confirmation would change management through its extent, spread or complications, list the
> negatives a consultant states once that diagnosis is made: the absence of each extension,
> spread or complication this technique shows and the next management step depends on. Name
> the differential exactly as it appears in Differentials in scope. One finding per negative,
> with no "or" and no list, in final report form. Tag each **core** when any consultant states
> it once the diagnosis is made, or **contextual** when stating it depends on the case or on
> local practice. At most three per differential and twelve in total. Do not repeat a
> mandatory negative. Do not write a negative for something the confirmed diagnosis is
> expected to cause.

### 2. Brief — classify each candidate as stated, offered or dropped

In `compile_brief`:

1. **Parse** the If-confirmed lines as `(branch, negative, tag)`. Match `branch` to a
   differential line by the text before " — ". Drop unmatched lines and count them in
   `decisions["confirmed_negatives_unmatched"]`. A missing tag counts as `contextual`.
2. **Check against the dictation.** Every candidate goes through the existing Qwen negatives
   call alongside the mandatory negatives: same call, same parallel step, no added latency.
3. **Route**, once Jev and Qwen have returned:

| Qwen label | Jev `present` | Tag | Outcome |
|---|---|---|---|
| any | < low cut-off (0.5) | any | dropped (branch not confirmed) |
| contradicted | ≥ low | any | dropped (the dictation says otherwise) |
| expected | ≥ low | any | **DO NOT ASSERT** in the brief (never offered) |
| keep | ≥ high cut-off | core | **stated**: joins Mandatory negatives as KEEP |
| keep | ≥ high cut-off | contextual | **offered** |
| keep | low ≤ p < high | any | **offered** |

4. **Stated negatives** join Mandatory negatives annotated `(confirmed: <branch>)`. The
   generator already handles KEEP negatives, so nothing changes there. One reaches
   **Carry forward** only through the impression plan (see 3), never by default.
5. **Offered negatives** go into `decisions["options"]` as
   `{"kind": "confirmed_negative", "section": "FINDINGS", "text": <negative>, "branch": <branch>, "reason": "<why offered>"}`.
   The reason is either "contextual" or "branch borderline (p=…)". They have their own cap
   (`MAX_CONFIRMED_OPTIONS = 4`), separate from the existing `MAX_OPTIONS = 3` for
   impression and recommendation options.
6. **Remove** the If-confirmed bullet from the brief (add it to `DROP_TOP_BULLETS`).
7. **Log** `decisions["negatives"][*].source = "sheet" | "confirmed:<branch>"` and
   `decisions["confirmed_negatives"]` with every candidate's `(qwen_label, jev_p, tag, outcome)`.

**Cut-offs.** The low cut-off stays at the validated 0.5. The high cut-off is **untested**:
calibrate it on `test_cases/sheet_reconcile_labelled.json` before the evaluation. If Jev's
`present` scores don't separate clearly confirmed from borderline branches there, fall back to
the single 0.5 cut-off and let the core/contextual tag alone decide what is offered. Record
the chosen value in the ledger.

### 3. Impression — no new rule

The impression plan (Qwen, reasoning low) already sorts numbered items into carry / optional /
findings-only. It runs in the same parallel step as Jev and Qwen, so it cannot wait to learn
which negatives will be stated. Instead:

- The plan sees **every** confirmed-branch candidate in a separate numbered list
  (`CANDIDATE NEGATIVES — apply only if their diagnosis is confirmed`) and returns
  `carry_negatives: List[int]`.
- One sentence in `PLAN_SYS`: *a negative is carried only when it changes the interpretation
  of a carried finding; never carry a negative for any other reason.*
- Code keeps a `carry_negatives` placement only for negatives routed **stated**. Placements
  for offered or dropped candidates are discarded. Stated negatives the plan does not carry
  stay in FINDINGS.

Nothing else changes. The generator's impression rules (principle 3, descriptor propagation)
already govern the wording.

### 4. Options payload — written once, placed by the UI

Offered negatives are already in final report form, so they skip the `_write_options` LLM
call: `sentence = text`. Every option in the payload gains `section`:
`"IMPRESSION"` for the existing kinds, `"FINDINGS"` for `confirmed_negative`. The existing
panel only understands impression options. Until sub-project 2 ships, the frontend **filters
out** `confirmed_negative` rather than inserting a FINDINGS sentence into the impression.
Offered negatives are still recorded in `decisions`, so the evaluation can measure them before
any UI exists.

### 5. Persist the brief

Store `brief.text` and `brief.decisions` on `candidate_reports[0]` as `brief`. That makes a
case like `064ff6f1` traceable from prod data instead of by recompiling, and it's needed to
measure this change in prod.

### Not changing

- The mandatory-negative contract, the Normal-study path, and differential closure (policy 1
  stays as it is).
- The generator prompts, unless the evaluation shows stated KEEP negatives being dropped. Only
  then is the no-fabrication rule narrowed, at the rule itself ("descriptor" means a positive
  feature), not through a new rule layered on top.

## Evaluation

The method follows the ledger rules: one variable per cell, three runs, predictions written
first. Two arms: A = production directives, B = production + `confirmed_negatives`.

**Basket**
- **Silent-staging (new, 6 cases across ≥4 domains):** the prod jaundice case verbatim. Plus
  five cases from `varied_10.json` with extent descriptors removed from the findings, spread
  across chest, neuro, abdomen and MSK.
- **Regression:** `varied_10.json` as is (extent already dictated) and
  `integrity_regression.json`.
- **Control:** two cases where no branch is confirmed. B must add nothing.

**Predictions (written before any run)**

| Measure | A | B |
|---|---|---|
| Silent-staging: at least one confirmed-branch negative stated in FINDINGS | ~0/6 | ≥5/6 |
| Any report negative contradicting the dictation | 0 | 0 |
| An expected-consequence negative appearing anywhere | n/a | 0 |
| Impression: confirmed negatives carried (by hand: does each change the interpretation?) | n/a | only those that change it; median ≤1 per case |
| Offered confirmed negatives per case (median) | 0 | 1–2 |
| Control cases: new negatives or options | 0 | 0 |
| Regression: gate, four sections, no tags, no history | 20/20 | 20/20 |
| Analyser latency (median) | baseline | within +1.5 s (sheet adds ≤12 lines) |
| Brief reconcile latency | baseline | unchanged (same calls) |

Also re-run `/enhance` on B's reports: the audit's `characterisation_gap` flag should clear on
the silent-staging cases.

**Unit tests (TDD, before the brief code):**
- parsing `(branch, negative, tag)`; a missing tag counts as contextual;
- each row of the routing table;
- unmatched branch dropped and counted;
- the raw bullet never rendered;
- offered negatives have kind `confirmed_negative`, section FINDINGS, their own cap, and no
  `_write_options` call;
- the existing options gain `section: "IMPRESSION"`;
- decisions record the source and route;
- the brief is persisted on the candidate.

## Risks

- **Asserting staging from silence.** This is intended under policy 1 and correctable by the
  radiologist, like normal-fill. Rule C keeps it to clearly confirmed diagnoses and standard
  negatives; everything else is offered.
- **The core/contextual tag drifts between analyser runs.** Measure how often it agrees across
  the three runs. If it is unstable, that negative flips between stated and offered from run
  to run, which is a softer failure than a wrong statement.
- **Naming primes.** Stated negatives name structures (vessels). If the generator starts
  inventing *positive* descriptors for them, the fabrication check in the evaluation catches
  it.

## Hand-off to the UI spec (sub-project 2)

This spec fixes the payload: every option carries `id`, `kind`, `section`, `sentence`,
`reason`, and `branch` where one applies. The UI spec designs a side panel that groups options
by `section`, is easy to scan, and toggles each item in place. It also decides where a FINDINGS
option goes in the text: next to the confirmed finding's paragraph, or at the end of FINDINGS.
Until then, `confirmed_negative` options are measured, not shown.
