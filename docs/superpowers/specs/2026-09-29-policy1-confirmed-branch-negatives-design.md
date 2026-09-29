# Policy 1 for confirmed branches — negatives that follow a confirmed diagnosis

**Status:** design, not built · **Date:** 2026-09-29 · **Ledger:** L-45 (to open)
**Depends on:** compiled brief (bd938a0), policy 1 (`docs/superpowers/research/2026-09-29-sheet-reconciliation-bakeoff.md`)

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
   clinical question as asked ("jaundice": no dilatation, no pancreatic lesion, no CBD
   calculus, no nodes, no hepatic lesion, no ascites, veins patent). None of them is a negative
   that only matters once a diagnosis is confirmed. The analyser prompt forbids that kind:
   "each bears on a specific differential … one per differential the imaging meaningfully
   bears on".
2. **The staging features exist only as descriptors of what is present:** In-scope companions
   ("Vascular relationship — degree of contact with SMA, SMV, portal vein, coeliac axis"), a
   Measurement convention ("required for any peripancreatic mass"), exemplars.
3. **The brief removes the carriers.** `quick_report_brief.py` always drops In-scope companions
   (`DROP_TOP_BULLETS`). The measurement convention survives only when Qwen marks it
   applicable, which varies between runs.
4. **The generator can't bridge the gap.** "Missing Data Handling" does license undictated
   negatives, but only those the sheet lists. A descriptor with no listed negative falls under
   the no-fabrication rule. So the generator's only honest move is silence, and nothing
   records that a required item was left out.

Recompiling the brief locally from the stored sheet and dictation confirms it. Jev marks
"Pancreatic head mass (adenocarcinoma)" **present**, and the branch is closed correctly. After
that no staging negative exists anywhere in the brief.

## Design

Same division of labour as policy 1: **the analyser does the inference, Jev matches text, code
decides.**

### 1. Analyser — new opt-in directive `confirmed_negatives`

It ships as a `DIRECTIVES` entry, so production stays byte-identical until you sign it off (v1
subtraction rule). The directive text is appended, so it reaches both prompt families (the
Anthropic and open-weights copies) without editing either base prompt.

The sheet gains one Companion Matrix bullet:

```
- **If confirmed:** (negatives stated only when the dictation confirms the branch)
  - <differential name exactly as written in Differentials in scope> → "<negative in report form>"
```

The directive, drafted to be case-agnostic (structural form only, no clinical example):

> **If confirmed.** For each differential tagged *visible on this technique: yes* whose
> confirmation would change management through its extent, spread or complications, list the
> negatives a consultant states once that diagnosis is made: the absence of each extension,
> spread or complication this technique shows and the next management step depends on. Name
> the differential exactly as it appears in Differentials in scope. One finding per negative,
> with no "or" and no list, in final report form. At most three per differential and twelve in
> total. Do not repeat a mandatory negative. Do not write a negative for something the
> confirmed diagnosis is expected to cause.

### 2. Brief — promote the negatives of confirmed branches

In `compile_brief`:

- Parse **If confirmed** lines as `(branch_name, negative)` pairs. Match `branch_name` to a
  differential line by the text before " — ". Drop unmatched pairs and count them in
  `decisions["confirmed_negatives_unmatched"]`.
- Send **every** candidate through the existing Qwen negative check, in the same parallel call
  as the mandatory negatives. This adds no latency and no extra call.
- After Jev returns, code promotes a pair only when its branch scored `present`. A promoted
  negative joins **Mandatory negatives** with its Qwen label (KEEP / OMIT / DO NOT ASSERT),
  annotated `(confirmed: <branch>)`. Negatives for branches that weren't confirmed never reach
  the generator.
- Add `If confirmed` to `DROP_TOP_BULLETS`, so the raw list never reaches the generator.
- Log `decisions["negatives"][*].source = "sheet" | "confirmed:<branch>"`.

### 3. Generator — no change unless the evaluation shows one is needed

A KEEP negative is already licensed by Missing Data Handling and checked by "Every KEEP
negative is present". Only if promoted KEEP negatives are dropped in the evaluation does the
fabrication rule get narrowed, at the rule itself ("descriptor" means a positive feature), not
through a new rule layered on top.

### Not changing

- The mandatory-negative contract, the Normal-study path, and differential closure (policy 1
  stays as it is).
- Findings that aren't a differential branch (for example an incidental dictated lesion). Out
  of scope here; see open questions.

### Also add: persist the brief

`brief.text` and `brief.decisions` currently live only in memory. Store them on
`candidate_reports[0]` as `brief_decisions` (text included). That makes a case like this one
traceable from prod data instead of by recompiling. It's small, and it's needed to measure
this change in prod.

## Evaluation

The method follows the ledger rules: one variable per cell, three runs, predictions written
first. Two arms: A = production directives, B = production + `confirmed_negatives`.

**Basket**
- **Silent-staging (new, 6 cases across ≥4 domains):** the prod jaundice case verbatim. Plus
  five cases from `varied_10.json` with extent descriptors removed from the findings, spread
  across chest, neuro, abdomen and MSK (for example spiculated lung nodule without chest wall,
  pleura or node statements; cerebellar haemorrhage without ventricle or brainstem
  statements; diverticulitis without gas or collection statements).
- **Regression:** `varied_10.json` as is (extent already dictated) and
  `integrity_regression.json`.
- **Normal / unconfirmed control:** two cases where no branch is present. B must produce
  nothing new.

**Predictions (written before any run)**

| Measure | A | B |
|---|---|---|
| Silent-staging: confirmed-branch negatives stated in the report | ~0/6 | ≥5/6 |
| Any report negative contradicting the dictation | 0 | 0 |
| Promoted negative for an expected consequence (should be DO NOT ASSERT) that appears in the report | n/a | 0 |
| Control cases: new negatives | 0 | 0 |
| Regression: gate, four sections, no tags, no history | 20/20 | 20/20 |
| Analyser latency (median) | baseline | within +1.5 s (sheet adds ≤12 lines) |
| Brief reconcile latency | baseline | unchanged (same Qwen call) |

Also re-run `/enhance` on B's reports. The audit's `characterisation_gap` flag should clear on
the silent-staging cases.

**Unit tests (TDD, before the brief code):** parsing If-confirmed pairs; promotion only when the
branch is present; unmatched branch dropped and counted; the raw bullet never rendered; a Qwen
`expected` label becomes DO NOT ASSERT; decisions record the source.

## Risks

- **Asserting staging from silence.** This is intended under policy 1 and correctable by the
  radiologist, like normal-fill. But it touches resectability, where a wrong negative costs
  more than a wrong normal line. See open question 1.
- **Promotion depends on Jev `present`.** The bake-off measured 10/11 with no false positives;
  a miss leaves today's behaviour in place, not a wrong one.
- **Naming primes.** Promoted negatives name structures (vessels). If the generator starts
  inventing *positive* descriptors for them, the fabrication check in the evaluation catches
  it.

## Open questions for you

1. **Assert or offer?** Arm B states the confirmed-branch negatives as KEEP. The alternative,
   arm C, puts them in the Optional additions panel as reporter choices. That is safer for
   resectability, but it departs from policy 1. Run C as a third arm, or decide now?
2. Should confirmed-branch negatives go into the impression (following the descriptor
   propagation rule: vascular status "propagates"), or is that left to the impression plan?
3. Do non-branch dictated findings (an incidental lesion) also need policy-1 negatives later?
