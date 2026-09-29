# Sheet reconciliation bake-off (X-06 extension) — 2026-09-29

**Question.** Before generation, can a fast classifier tell, for each clinical item in the skill sheet, whether the dictated findings affect it? *Affected* means a dictated finding contradicts the item, or acts on the structure it describes (displaces, compresses, obstructs, drains into, extends to, involves it, or is a finding of the same kind in that structure), so the item cannot be written as it stands. For a mandatory negative that means **rescope**; for a normal-study line it means **unsupported normal**.

**Why.** Prod walkthrough case 1: the generator asserted "the lateral and third ventricles are normal" beside dictated aqueduct and fourth-ventricle effacement. The trace shows the generator does not check the sheet item by item inside its reasoning. See the X-01 note in `plans/2026-09-26-jev-work-order.md`.

## Set-up

- **Cases:** 11 ledger cases with known collisions (`varied_10`, `broad_suite`, `integrity_regression`, `stress_targeted`). Case 1 uses the actual faulty production sheet; the rest use sheets from the production analyser (Qwen 3.8, Cerebras, medium, prune_v1).
- **Items:** 188, extracted in code (mandatory negatives from the Companion Matrix; normal-study path split into sentences). 66 mandatory negatives, 122 normal lines.
- **Labels:** by hand (single annotator, not a radiologist): 74 affected, 99 unaffected, 15 ambiguous (excluded from scoring). **Needs radiologist review before any threshold is trusted.**
- **Methods, one call per case:** Jev 1.13 (one noul per item); Qwen 3.8 on Cerebras, reasoning off (returns affected item numbers); lexical baseline (item anatomy words found in a positive, non-negated dictated finding).
- Data and per-item scores: `backend/test_cases/sheet_reconcile_labelled.json`. Script: `backend/src/rapid_reports_ai/scripts/sheet_reconcile_bakeoff.py`.

## Results (173 scored items)

| Method | Precision | Recall | F1 | FP | FN | Median latency |
|---|---|---|---|---|---|---|
| **Jev @0.50** | 0.88 | **0.96** | 0.92 | 10 | 3 | 0.30 s |
| Jev @0.61 (best F1, chosen in-sample) | 0.92 | 0.95 | 0.93 | 6 | 4 | 0.30 s |
| Qwen 3.8 reasoning off | 0.93 | 0.93 | 0.93 | 5 | 5 | 0.30 s |
| Lexical baseline | 0.55 | 0.81 | 0.66 | 49 | 14 | — |
| **Jev @0.50 AND Qwen** | **1.00** | 0.93 | — | **0** | 5 | 0.30 s (parallel) |
| Jev @0.50 OR Qwen | 0.83 | 0.96 | — | 15 | 3 | |

Jev AUC 0.989. Jev and Qwen agree on 90 % of items. By type (Jev @0.61 / Qwen): mandatory negatives F1 0.91 / 0.89; normal lines F1 0.94 / 0.95.

**The target failures are caught.** "Ventricles normal" beside a dictated obstructing or mass-effect finding: Jev 4/4 (0.78–0.93), Qwen 3/4. ct_tap's pneumatosis negative beside dictated duodenal mural gas: both. The vessel-sign inversion stays *unaffected* (Jev 0.35), as designed: this is a relevance check, not a correctness check.

## Error pattern

- **Jev false positives:** catch-all lines ("No osseous or soft-tissue abnormality"), and anatomical adjacency without involvement (uterus and ovaries beside pelvic fluid; thoracic spine in a scan with an L1 fracture).
- **Misses shared by both:** consequences one inference step away. Pubic rami fractures → "no pelvic ring disruption"; tonsillar descent → "upper cervical canal unremarkable"; intrathoracic hiatus hernia → "mediastinum normal". Jev's misses sit at 0.43–0.50, just under threshold.

## Design implications

1. **Label with Jev at ~0.5, recall first.** A missed item is a possible contradiction in the report; a false label costs a rescope or a contingent normal, which principle 12 already treats as cheap.
2. **Remove a normal outright only when Jev and Qwen both flag it.** That tier had zero false positives here; everything else is passed to the generator as a labelled fact, not deleted.
3. **Next measurement:** generator A/B on these cases, with labelled sheet vs raw sheet. Measure contradiction and unsupported-normal rate, must-appear retention, and latency (+~0.3 s, in parallel with nothing else on the path).

Caveats: small set, single non-radiologist annotator, thresholds chosen on the same data (use the @0.50 row as the fair estimate).

## Generator A/B — does the reconciled sheet help, and can reasoning go? (2026-09-29)

Same 11 cases and sheets, production generator path, 2 runs per arm (66 reports). **A** raw sheet, reasoning medium (production). **B** reconciled sheet (Jev ≥0.5 → RESCOPE / affected-normal list; Jev AND Qwen → normal line removed), medium. **C** reconciled sheet, reasoning off. Every report read in full by one reviewer (not blinded), counting serious errors: a contradiction of a dictated finding, a normal asserted for a structure a dictated finding acts on, a fabricated detail, or history asserted as a finding on this study. The automated gpt-oss checker missed two of the ventricles errors, so it was not used for scoring.

| | Reports with a serious error | Fabrication / history leak | Generator median (p90) | Output tokens |
|---|---|---|---|---|
| A raw, medium | **12 / 22** | 0 | 6.8 s (8.1) | 9,186 |
| B reconciled, medium | **5 / 22** | 0 | 7.2 s (9.0) | 9,448 |
| C reconciled, off | **9 / 22** | 3 | **0.6 s** (0.8) | 382 |

- **B fixed what A got wrong:** the rescoped malignancy negative beside dictated sigmoid thickening (A 2/2 flat, B 0/2), "heart normal" beside RV dilatation, "no pneumatosis" beside duodenal mural gas, intrahepatic ducts "not dilated" beside a double-duct sign. No new failure mode.
- **B's residual errors** are almost all one pattern: a multi-part negative ("No midline shift or ventricular compression") marked RESCOPE, where the generator drops the dictated part and keeps the rest ("no ventricular compression" beside a 3 mm shift). Items should be split into single clauses in code before classification. Also "no pelvic ring disruption" beside pubic rami fractures, which both classifiers missed.
- **C is 11× faster and worse than B:** it invents detail ("apical" pneumothorax, splenic laceration "upper pole", "colon distended"), asserts history as a finding (prior-ultrasound "fatty liver" → "steatosis" on this CT, 2/2), states flat negatives the reconciliation had marked, and writes thinner impressions (missed referrals, dropped fractures). Consistent with L-31: labels remove the need to *find* conflicts, not the need to *reason* while writing.
- Not reached by any arm: "upper cervical canal unremarkable" beside 5 mm tonsillar descent; "obstructive hydrocephalus" asserted when only its signs were dictated (over-inference, all arms).

**Decision input:** ship reconciliation (B) in front of the medium generator. Reasoning off needs the compiled brief (stage 3: verbatim normals, findings mapped to sections), which targets exactly C's failure classes.

Data: `backend/test_cases/sheet_reconcile_arms_runs.json`. Script: `backend/src/rapid_reports_ai/scripts/sheet_reconcile_arms.py`.

## Applicability pruning — multiple Jev questions per item (2026-09-29)

Can the sheet be cut down to what applies to this case, not just labelled? 5 cases (cerebellar haemorrhage, SDH, CTPA, diverticulitis, ct_tap), 210 items of 7 types, hand-labelled (5 ambiguous excluded). One Jev call per case asks 1–3 questions per item in parallel (60–109 questions per call, **0.31–0.49 s**, one 1.19 s outlier); Qwen 3.8 reasoning off returns one action per item (~0.6 s). Mandatory negatives were first split into single claims by Qwen (reasoning off), since a comma-and-or splitter garbles shared phrasing ("No filling defect in the SMA, celiac trunk, or IMV").

| Item type | Best method | Result |
|---|---|---|
| Recommendation | Jev, one question ("condition unmet or belongs to a ruled-out diagnosis") | **13/13 removals, 0 wrong** |
| Impression variant | Jev **choice** over the three exemplars | **5/5** (confidence 0.91–1.0); Qwen 5/5 |
| Style exemplar | Jev "matches a dictated finding?" < 0.5 | recall 1.00, 2 wrong removals (Qwen identical) |
| Differential branch | Jev settled ≥ 0.6 and present < 0.5 | precision 0.79, recall 0.55 under strict labels (see below) |
| Negative clause (contradicted / expected / keep) | **Qwen** | Qwen 0.88 accuracy vs Jev 0.65 (Jev over-calls "expected") |
| Measurement convention | **Qwen** | Jev 3 wrong removals of 7; Qwen 1 |
| Suppression rule | none | All 34 are generic writing rules, none case-conditional: remove from the generator input in the lean pass, not per case |

**Multi-question gating did not help where the questions are not independent.** For differentials, "nothing in the findings bears on it" scored as high on settled branches (median 0.62) as on open ones (0.72), so requiring it to be low cut recall to 0.10. The "present" question is strong (10/11, no false positives) and belongs in the gate; the "silent" question does not.

**The remaining differential "errors" are a policy question.** All six are branches whose imaging sign the dictation does not mention (aneurysmal SAH, haemorrhagic transformation, distant abscess, fistula, SMA embolus). Labelled open under "silence never closes a branch"; both models read silence as excluded. By reporting convention a finding with a visible sign that is not dictated was not seen, the same logic that licenses normal-fill. Branch text is reasoning scaffolding; the pertinent negative that answers the question is kept separately. Under a "silence closes a branch whose imaging sign would have been dictated; never an imaging-silent one" policy, 4–5 of the 6 become correct.
