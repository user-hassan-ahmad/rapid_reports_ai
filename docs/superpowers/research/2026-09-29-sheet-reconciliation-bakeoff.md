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

## Serial chaining — a sieve, then gated questions (2026-09-29)

Same 5 cases and labels. Each stage is one Jev call over the items that survived the previous gate; code decides between stages. Three calls cost **0.6–0.9 s** per case against 0.3–0.5 s for one parallel call.

**Negative clauses (sieve → contradicted? → expected consequence?).**

| Set-up | Accuracy |
|---|---|
| Parallel single call | 0.65 |
| Chain, sieve "a dictated finding relates to this negative" | 0.57: contradicted clauses scored *low* on the sieve ("No midline shift" beside a dictated shift: 0.18) and never reached stage 2 |
| **Chain, sieve = the bake-off's "is this statement affected…" wording** | **0.84**; **0.88** when contradicted and expected are merged into the one action they share ("don't assert as written") |
| Qwen reasoning off | 0.88 |

A chain is only as good as its sieve: a stage-1 miss is unrecoverable. Use the proven, highest-recall question as the sieve. Jev also misreads questions that embed a negative sentence inside a claim.

**Differentials (present? → alternative / ruled out / invisible / sign-would-be-dictated).** Chaining barely helped. Among branches not present, only "ruled out" separates removable from open (medians 0.42 vs 0.28). "Establishes an alternative", "invisible on imaging" and "sign would be dictated" score alike on both (0.15/0.18, 0.53/0.52, 0.46/0.39). "Invisible" fired on visible branches (fistula 0.73, SAH 0.63) and blocked removals until replaced by the sheet's own `imaging-silent` tag read in code. Best Jev-only chain under policy 1: 0.95 precision, 0.59 recall.

**Division of labour is what worked.** Jev is strong at whether something is stated in the text and weak at inference about what imaging would show; chaining changes which questions are asked but adds no reasoning. Moving the inference upstream fixes it. Simulated with an analyser-style field per branch, *visible on this technique: yes/no* (my judgement standing in):

> remove ⇔ Jev *not present* (< 0.5) ∧ *visible on this technique* ∧ not `imaging-silent`

→ **policy 1: precision 0.91, recall 0.91** (vs 0.44–0.59 for Jev-only designs). The 3 residual errors are branches with part of their sign dictated (tentorial SAH vs aneurysmal pattern, background atherosclerosis, mosaic perfusion). A Jev "partial sign dictated?" gate fixed one (mosaic 0.89) and cost recall (0.78): not adopted.

**Implications.** (1) The analyser should emit, per differential, its visibility on the declared technique; the imaging-silent tag it already writes. (2) Jev asks only text-matching questions. (3) Code decides. (4) Negative clauses: Jev chain with the proven sieve, or Qwen, is equal at 0.88; Jev is cheaper and returns calibrated scores for thresholds.

## Clause splitting — Jev selection vs Qwen extractive rewrite (2026-09-29)

The durable fix is upstream: the analyser now writes one finding per mandatory negative (`feat/analyser-atomic-negatives`, 291399d; bundled negatives 22/37 → 4/40, and only once the rule was mechanical — no "or", no list). This tests the runtime fallback on the residue: 62 bundled negatives from 17 sheets, hand-split gold (alternatives accepted where either reading is right).

**Jev by selection** — code proposes every separator and every candidate shared opening/closing phrase; Jev answers a yes/no per marked separator (call 1, 81 questions, 0.53 s), then a choice of shared opening and closing words among the candidates (call 2, 116 questions, 0.32 s); code rebuilds each clause from source words only.

| | Exactly right | Notes |
|---|---|---|
| Jev selection, end to end | 23/62 | cannot reword, by construction |
| — stage 1: where to split (yes/no per boundary) | **57/62 (92%)** | misses: splits inside a "to suggest A, B, or C" qualifier; leaves "T1 or T2*" whole |
| — stage 2: shared wording (choice among overlapping spans) | 23/57 (40%) | picks "(none)" for the shared qualifier; picks too-short openings ("No" for "No filling defect in the") |
| **Qwen 3.8 reasoning off, extractive rewrite** | **60/62 (97%)** | 0 words outside the source; misses are a verb that must change ("are" → "is") and one dropped modifier |

**What generalises about Jev.** Strong: independent yes/no judgements about marked text (split points 92%; relevance AUC 0.989; "present" 10/11) and a choice among semantically distinct options (impression variant 5/5). Weak: a choice among near-identical overlapping spans (40%), and inference about what imaging would show. "Code proposes, Jev classifies" carries forward when each candidate is a distinct judgement; for span extraction use Qwen with a code check that every output word appears in the source.

**Decision:** splitting = analyser atomic rule + Qwen extractive fallback with the source-word check.

## Compiled brief end to end — arms A/B/C (2026-09-29)

Branch `feat/compiled-brief` (0f4e9a4). Fresh sheets from the atomic-negative + visibility-tag analyser for the 11 labelled cases; 2 runs per arm, 66 reports, judged by reading each one.

- **A** raw sheet, split quick-report generator, Qwen 3.8 medium.
- **B** compiled brief (Jev + Qwen reconciliation, labels, pruning), same generator, medium.
- **C** compiled brief, reasoning off.

| Arm | Median total | Serious errors (reports) | Other |
|---|---|---|---|
| A | 5.9s | 12/22 | — |
| B | 6.6s (reconcile 0.47s) | 2/22 | brief used 22/22 |
| C | 1.2s | 4/22 | 4 gate fails (missing section) + several reports silently drop COMPARISON |

Serious = contradicts a dictated finding, asserts normal for a structure the findings act on, or fabricates a management-relevant fact. Undictated "No pulmonary embolism" on the ct_tap case (A0, A1, B0, B1) is scored separately below, not in the count.

- **A:** brainstem "unremarkable" beside tonsillar herniation (×2); ventricles "normal" beside an SDH with shift (×4 across the two SDH cases); portal vein "uninvolved" in pancreatic staging (×2, not dictated, resectability-critical); "no pelvic haemorrhage" with pubic rami fractures (×2); "no flail segment" with two segmental adjacent ribs (×1); neural foramina "unremarkable" at a level with paraspinal extension (×1).
- **B:** "borderline resectable" alongside suspected liver metastases (B0, a staging interpretation); "ventricular system unremarkable" in clean_ct_head (B0).
- **C:** ventricles "normal" in the SDH case in both runs, which ignores the do-not-assert label; "no pelvic ring fracture" alongside pubic rami fractures (C0); a 5 mm nodule followed up "in three months" (C1). C also fabricates signal characteristics and duct findings more often.

Findings:

1. **The brief works at medium.** Serious errors fell from 12/22 to 2/22 for +0.7s. In both head cases the labels removed exactly the normals that A asserted, and the pancreatic vessel line removed the portal-vein claim.
2. **Removing a line is weaker than labelling it.** In clean_ct_head both reconcilers removed the ventricles line, and B0 still wrote "ventricular system unremarkable" from its own priors. In the matched SDH case the same line was labelled DO NOT ASSERT and B was clean in both runs. An affected normal should become an explicit prohibition, not a deletion.
3. **Reasoning off is not viable yet.** C is 5× faster, but it drops sections, ignores labels (4/4 in the SDH case) and makes arithmetic and interval errors. The reasoning is doing the label-following.
4. **Undictated PE negative:** "No pulmonary embolism" on a portal-venous-phase CT TAP. The sheet lists PE only as an in-scope companion, which the brief drops, so in B it comes from the generator's priors. B1 escalated it to "PE excluded" in the impression. This needs a rule about which negatives a technique can support; it is not a brief defect.
5. **Recommendation scope:** the Doppler recommendation after PE and the MRI-spine/brain staging recommendations appear in every arm. This is unchanged and a separate policy question.

Next: turn affected-normal removals into DO NOT ASSERT (keep deletion only for normals of structures outside the scan's anatomy), then re-run B on the two head cases before shipping.

## Lean prompt — rule trim and exemplar diet (2026-09-29)

Baseline **B′** = compiled brief with affected normals always DO NOT ASSERT (51d3e5f). **D** = B′ + lean pass: dead rules removed, duplicates kept once, history-as-checklist rewritten to history-as-focus, "clinical correlation" limited to a named specialty or test, consolidation defined on the sheet's sweep steps. **F** = D with Style and Impression Exemplars stripped from the brief and exemplar references removed from hardening principles 1 and 5. 11 cases × 2 runs each, every report read.

| Arm | Serious errors | Notes |
|---|---|---|
| B′ | 2/22 | head cases 4/4 clean (vs B's "ventricular system unremarkable"); trauma "no flail segment", "no pelvic haemorrhage" despite its DO NOT ASSERT label; undictated "No PE" 2/2 |
| **D** | **0/22** | undictated "No PE" gone (0/2); prompt −2.7k chars (system 28.0k→25.9k, user 3.4k→2.8k) |
| F | 4/22 | history leak into the impression (lactate), mosaic attenuation called infarction, "borderline resectable" beside liver metastases, SMV-only encasement called locally advanced |

F also drifts in scope and voice without exemplars: treatment recommendations (decompressive surgery, embolectomy, CSF diversion, anticoagulation reversal), undictated inferences ("contained perforation", "spinal instability", guideline thresholds), and impressions that restate findings across several paragraphs. **Exemplars anchor impression scope and voice; keep them (Jev-pruned).** D is adopted (03cea37 on feat/compiled-brief).

Operational note: at 6 concurrent reports, 3/44 reconciliations hit the Qwen/Jev timeout and fell back to the raw sheet (safe, but loses the brief). Production concurrency is lower, but the fallback rate should be logged once live.

## Longer set — lean (D) vs lean + recommendation-scope fix (G) (2026-09-29)

26 cases (the 11 + 15 from analyser/broad/denovo suites), 2 runs each; D reuses its 22 runs on the original 11. Branches `feat/qr-lean` (03cea37) and `feat/qr-lean-fixes` (e304f21: "further imaging only when this study raises a question it cannot answer; not routine workup of a diagnosis already made"). 82 new reports, all with the brief, all read.

| | D | G |
|---|---|---|
| Serious errors, 22 clean-input cases | 1/44 (TAVI: aortic root, ostial and iliofemoral measurements invented) | 0/44 |
| Target of the fix: PE → leg Doppler, MSCC → MRI brain | — | still present 4/4 |

- **The fix did not work.** Both recommendations come from the sheet's Recommendation scope, which Jev keeps (condition met) and the generator follows. A generator rule does not override a sheet line it has been told takes precedence. The fix belongs in the brief: a Jev question per recommendation ("routine next step of a diagnosis already made?") or code that drops that class.
- The 1 vs 0 difference is a single event and not evidence for G. Its cause is structural, though: the TAVI sheet's **Normal-study path and exemplars carry numbers** ("Sinuses of Valsalva 32 mm, sinotubular junction 30 mm, coronary ostia 12/14 mm", "minimum calibre 8 mm"), and D0 rendered the normal path verbatim as instructed. A normal line with a measurement is a fabricated measurement whenever the dictation is silent. Fix in code at brief compile: a normal-study sentence containing a number + unit is never KEEP (drop, or DO NOT ASSERT).
- **Input-defect cases (4) fail in both arms and are not scored:** laterality conflict (silently corrected to right, or "left talar dome" kept in a right-ankle report), "tiny" 4.2 cm calculus reproduced as "tiny 42 mm", contradictory free fluid resolved without comment, truncated dictation filled with "spinal canal patent at all levels" (G 2/2, D 0/2). These are upstream integrity-check territory; the generator does not flag them.
- Seen in both arms, minor: bare "clinical correlation" still appears (4 reports, often echoing the dictation), laboratory-test and treatment suggestions (galactomannan, anticoagulation reversal), ultrasound reports drop TECHNIQUE (4/4 missing_section).

**Decision input:** ship `feat/qr-lean`; rework the recommendation-scope fix at the brief level before merging `feat/qr-lean-fixes`.

## Impression plan + three-way recommendations (feat/qr-lean-carry, 2026-09-29)

Qwen (reasoning low, parallel with Jev) plans the impression: per recommendation include / exclude / optional (+ exclude category), and which numbered dictated findings the impression must carry or keep in FINDINGS. Jev keeps condition-met; code routes. Optional items go to a reporter panel (not yet built).

**Classifier.** Tuned set (26 cases, hand labels): recommendations 0.98 (first wording 0.88: "routine next step" swallowed referrals until rules were split by kind), impression must-carry missed 4/112. **Held-out** (9 new cases written before any output): recommendations 87/90, must-carry missed 0/33. Optional recommendations landed exactly on the items labelled "either" by hand.

**End to end** — each fix exposed the next failure:

| Iteration | Change | Outcome |
|---|---|---|
| C | plan + removal | MRI-brain gone; leg Doppler re-added from priors 2/2; optional findings forced to findings-only dropped the AAA growth and left "no other calculi" beside unmentioned stones |
| C2/C3 | name removed recs; optional findings unlisted | Doppler gone, AAA back; naming a duplicate referral quoted "borderline resectable or locally advanced" into the brief → pancreatic mis-staging 2/2; narrowed naming to IMAGING/TISSUE → clean |
| F (70 reports) | — | no serious errors; but naming unmet-condition investigations suppressed follow-up imaging for pneumonia in a smoker 2/2; a kept surgical referral was not written 2/2 |
| G | name only `routine_workup` exclusions; checklist requires listed recs | surgical referral back 2/2; pneumonia follow-up 1/2; MRI brain flipped to include 2/2 |

**Insights.**
1. Deleting an item leaves a gap the generator refills from priors (ventricles, Doppler, CT for occult malignancy); naming it holds.
2. Naming primes: quoted conditions carry their vocabulary into the brief. Name only what the generator is known to re-add, in minimal wording.
3. The plan is a floor, never a ceiling — forbidding placement of ambiguous findings caused omissions and a contradiction.
4. Borderline recommendations flip with small prompt changes even at temperature 0 (MRI brain: exclude → optional → include). They are the reporter-choice tier, not a classifier accuracy problem.
5. Qwen returns nested object arrays as JSON strings in tool calls; parse before validation (was a retry → timeout path).

**Status:** `feat/qr-lean` merged to main (afc45c3). `feat/qr-lean-carry` (5738fe4) better than lean on Doppler, AAA carry, pancreatic staging and "No PE"; equal on MRI brain; weaker on pneumonia follow-up (1/2 vs 2/2). Hold until the options panel exists, so borderline items have a home.
