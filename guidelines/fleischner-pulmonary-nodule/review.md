# Gate 6: hand read, fleischner-pulmonary-nodule@2017.1

Read side by side with the PDF page images (Read tool, pages 2–13) and `sources/3088…087f.txt`. Locator pages are
1-based PDF pages; this copy is the online-ahead-of-print version (printed pages 1–16, "Volume 000: Number 0"), so
they do not match the issue pagination 284:228–243.

## Inputs and bands

| item | source | |
|---|---|---|
| `nodule_type` solid / ground-glass / part-solid | p3 Table, parts A and B | ✓ |
| `count` single / multiple | p3 Table rows | ✓ |
| `diameter_mm`, average of long and short axes | p3 Table footnote; p4–5 General Recommendations | ✓ |
| `risk` low / high, solid only | p3 Table (risk rows only in part A); p12 "recommendations for subsolid nodules are independent of customary risk categories" | ✓ |
| band `lt6` <5.5 | p5: "<6 mm corresponds to a rounded measurement of 5 mm or less" | ✓ |
| band `6to8` [5.5, 8.5) | p3 "6–8 mm"; rounded 6, 7, 8 | ✓ |
| band `gt8` ≥8.5 | p3 ">8 mm"; rounded 9 or more | ✓ |
| subsolid "≥6 mm" lists `6to8` and `gt8` | p3 Table part B | ✓ |

## Table rows (24) and outcomes (15)

| outcome | rows | source cell (p3) | |
|---|---|---|---|
| solid_single_lt6_low | solid, single, lt6, low | "No routine follow-up"; comment on suspicious morphology / upper lobe 12-month follow-up (1A) | ✓ |
| solid_single_lt6_high | solid, single, lt6, high | "Optional CT at 12 months"; same comment | ✓ |
| solid_single_6to8_low | solid, single, 6to8, low | "CT at 6–12 months, then consider CT at 18–24 months" | ✓ |
| solid_single_6to8_high | solid, single, 6to8, high | "CT at 6–12 months, then CT at 18–24 months" | ✓ |
| solid_single_gt8 | solid, single, gt8, low + high | "Consider CT at 3 months, PET/CT, or tissue sampling" (identical for both risks) | ✓ |
| solid_multiple_lt6_low | solid, multiple, lt6, low | "No routine follow-up"; comment: most suspicious nodule guides, intervals vary (2A) | ✓ |
| solid_multiple_lt6_high | solid, multiple, lt6, high | "Optional CT at 12 months"; same comment | ✓ |
| solid_multiple_ge6_low | solid, multiple, 6to8 + gt8, low | "CT at 3–6 months, then consider CT at 18–24 months" (both size columns identical) | ✓ |
| solid_multiple_ge6_high | solid, multiple, 6to8 + gt8, high | "CT at 3–6 months, then at 18–24 months" (both identical) | ✓ |
| ggn_single_lt6 | ground-glass, single, lt6 | "No routine follow-up"; comment: suspicious <6 mm consider 2 and 4 years; solid component or growth → consider resection (3A, 4A) | ✓ |
| ggn_single_ge6 | ground-glass, single, 6to8 + gt8 | "CT at 6–12 months to confirm persistence, then CT every 2 years until 5 years" | ✓ |
| psn_single_lt6 | part-solid, single, lt6 | "No routine follow-up"; comment: cannot be defined as part-solid until ≥6 mm, <6 mm usually no follow-up | ✓ |
| psn_single_ge6 | part-solid, single, 6to8 + gt8 | "CT at 3–6 months to confirm persistence. If unchanged and solid component remains <6 mm, annual CT … for 5 years"; comment: solid component ≥6 mm highly suspicious (4A–4C) | ✓ |
| subsolid_multiple_lt6 | ground-glass + part-solid, multiple, lt6 | "CT at 3–6 months. If stable, consider CT at 2 and 4 years"; comment: multiple <6 mm pure GGNs usually benign, consider 2- and 4-year follow-up in selected high-risk patients (5A) | ✓ |
| subsolid_multiple_ge6 | ground-glass + part-solid, multiple, 6to8 + gt8 | "CT at 3–6 months. Subsequent management based on the most suspicious nodule(s)" | ✓ |

Every outcome carries the exclusion caveat: p3 Table note (screening, immunosuppression, known primary cancer) plus
p2 (not for patients under 35). ✓

Golden cases: 27 (1 source, 26 ours); every outcome reached; edges 5.4/5.5 and 8.4/8.5 tested on solid and subsolid
rows; 4 cases assert `needed`; 1 case pins For Hassan 7 (solid single 12 mm, risk not stated → `solid_single_gt8`). The only worked example usable as a case is Figure 14 (p11: multiple subsolid nodules
incl. a 10-mm ground-glass nodule, "initial follow-up would be appropriate in 3–6 months"). Figures 1, 2 and 5 state
"no follow-up" for benign or perifissural nodules, which sit outside the table (carried as pitfalls). Figures 9, 10,
12 illustrate follow-up course, not a table lookup.

## Integration minors (review of Task 8)

- Minor 1: `def.subsolid` locator page 11 → 10 (p10 carries the mediastinal-window definition). Done.
- Minor 3: gate 5 re-run on the shipped text; evidence.md is current (15 of 85 below 0.5; `def.highrisk_factors` and
  `def.subsolid` now pass, `management.row5` newly flagged and resolved below).
- Minor 6: golden case "solid single 12 mm, risk not stated → solid_single_gt8" added.
- Minors 2, 4, 5 and 7 were not in the integration scope and are left open.

## Jev `check` items (15 of 85 below 0.5, re-run at integration)

| field | resolution |
|---|---|
| reference.def.size | ✓ p4–5: average of long and short axes on the same image showing the greatest dimensions; nearest whole millimetre; <6 mm = rounded 5 mm or less. Text spans the p4/p5 column break. |
| reference.pit.volume | ✓ p5: 100 and 250 mm³ used for volumetry instead of 6 and 8 mm. "Not supported here" is our product note. |
| management.row4, row5 | ✓ p3 part A, single, low and high risk, >8 mm (one shared recommendation). Low score is table layout in pdftotext. |
| management.row14, 16, 17, 21, 22, 23 | ✓ p3 part B, checked on the page image. Jev cannot see that "≥6 mm" covers both our `6to8` and `gt8` bands, nor that the "Multiple" subsolid row is shared by ground-glass and part-solid. |
| outcome.subsolid_multiple_lt6 | ✓ p3 part B, Multiple, <6 mm, verbatim in substance. |
| reference.def.highrisk_factors | ✓ p12 (high-risk factors; 30 pack-years and quitting within 15 years as the NLST threshold, "indicative of high-risk status in patients with solid nodules"). Wording tightened after the first Jev run to follow the source ("quitting within the past 15 years"); evidence.md re-run at integration on the shipped text, now 0.53 (no longer flagged). |
| reference.def.subsolid | ✓ p10: components still visible on mediastinal (soft-tissue) window with a sharp filter are solid. Locator corrected 11 → 10 at integration (review minor 1); re-run score 0.50 (no longer flagged). |
| reference.pit.mixed | Boundary: the table has no mixed row; p7 says a larger or more suspicious nodule should guide management. Our sentence states only that. See For Hassan. |
| reference.pit.benign | ✓ p4 Figures 1–2 (hamartoma, calcified granuloma: no further CT follow-up); recommendations are for noncalcified nodules (p5, p7). |
| reference.pit.thick | ✓ p4: after a thick-section first scan, consider a short-term thin-section follow-up as the baseline. |
| reference.pit.partsolid | ✓ p10 (solid component ≥6 mm: 3–6 month CT; solid component >8 mm, growing solid part or suspicious morphology: PET/CT, biopsy or resection, 4C). "Table size is the whole nodule" is our reading; see For Hassan. |

## For Hassan

1. **Exclusions are pitfalls plus a caveat on every outcome, not inputs** (as the brief asked): screening, age under 35,
   immunocompromise, known primary cancer are never asked on the card, so the pack will answer for an excluded patient
   and rely on the caveat. **Superseded by Hassan's verdict A (F1), fix wave 2:** now a patient-scope input (see below).
2. **Outcomes split where the table's comments differ.** "No routine follow-up" is four outcomes (solid single low,
   solid multiple low, single GGN, single part-solid) and "Optional CT at 12 months" two, because each row carries a
   different comment. 15 outcomes, not one per distinct recommendation string.
3. **The solid single <6 mm comment sits on the low-risk row too.** The table's comment cell spans both single rows
   and speaks of "patients at high risk"; we carry it on both outcomes as the table does.
4. **Part-solid size is taken as the whole nodule; the solid component is not an input.** The ≥6 mm solid-component
   condition is a caveat on `psn_single_ge6`, and the >8 mm solid-component escalation (4C) is a pitfall. Make solid
   component size an input if the card should branch on it.
5. **Mixed solid and subsolid multiple nodules have no table row.** The radiologist picks the type of the most
   suspicious nodule.
6. **Rounding half up:** 5.5 mm falls in 6–8 mm and 8.5 mm in >8 mm. The source says only "nearest millimetre".
   **Decided by Hassan (F6, 2026-10-12): keep half-up rounding.**
7. **Engine behaviour seen:** a solid single >8 mm nodule with risk unknown returns no outcome (`possible` =
   [solid_single_gt8], `needed` = []), because a table step waits for every key. The host should treat a single
   possible outcome as settled, or the engine could. **Resolved:** the engine now settles a single possible outcome
   (ebd514a); a golden case pins it (review minor 6).
8. **Source copy:** the RSNA publisher PDF from a third-party mirror, and it is the online-ahead-of-print version
   (pages 1–16), not the issue-paginated 284:228–243. Substance should be identical; worth swapping for the issue PDF
   if you have institutional access.
9. **Figure 14 as the source case:** its most suspicious lesion is a part-solid nodule of unstated size, so the case
   uses the stated 10-mm ground-glass nodule; the outcome is the same for either type.

## Fix wave 2 (2026-10-12): Hassan's verdicts

- **F1, exclusion input.** New boolean input `exclusion` (first input, patient scope): "any Fleischner exclusion (lung
  cancer screening, age under 35, immunocompromised, known primary cancer)". `how_stated` tells the model to settle it
  from the clinical history when the history states it, and to leave it unset otherwise. Locator: S1 p2, Implications
  for Patient Care (the under-35, immunocompromised and cancer exclusions; screening follows Lung-RADS). A new result
  step `applies` (rules) reads it: `exclusion = yes` gives the new outcome `does_not_apply` ("Fleischner 2017 does not
  apply ... manage per the clinical context"; locator S1 p3 table note); `exclusion = no` passes the table's outcome
  through unchanged (one case per table result, each citing the table). The generic exclusion caveat is removed from
  the 15 table outcomes, since the input now carries it.
  Consequence: a card asks the exclusion question whenever the history does not state it (it changes the outcome).
- **F6.** Half-up rounding kept, decided by Hassan.
- Golden cases: every earlier case now states `exclusion: false`; three new cases (exclusion alone → does_not_apply;
  exclusion with a full solid description → does_not_apply; exclusion not stated → needed [exclusion]). Gates 1-4 pass.
- Gate 5 re-run (evidence.md): applies.case0 0.81, outcome.does_not_apply 0.84; the pass-through cases restate table
  rows (checked by hand against the table, p3). 13 items below 0.5, all earlier items or pass-through restatements.

## Next slice (2026-10-13): eligibility inputs (spec §3.6)

Scope clauses read in the source: S1 p2, "Implications for Patient Care" ("These guidelines do not apply to patients
younger than 35 years, immunocompromised patients, or patients with cancer"; the body text on the same page: lung
cancer is rare "in children and adults younger than 35 years", so the guidelines "are not appropriate for such
patients"); S1 p3, the table note (not for lung cancer screening, immunosuppression or known primary cancer).

| Item | Check |
|---|---|
| input `age` (eligibility, patient scope, fact `age_years`, number in years, 0-110), locator S1 p2 | ✓ |
| input `exclusion` now eligibility, patient scope; label and `how_stated` narrowed to screening, immunocompromise or known primary cancer (age moved to `age`); locator S1 p2 unchanged | ✓ |
| band `age_band`: `lt35` under 35 (max 35, exclusive), `ge35` 35 or over (min 35, inclusive): "younger than 35 years" | ✓ |
| `applies` case 0: `exclusion` true or `age_band` lt35 → does_not_apply (locator S1 p3 table note, unchanged) | ✓ (see For Hassan) |
| `applies` cases 1-15: each now also requires `age_band` ge35 | ✓ |
| outcome `does_not_apply`: unchanged (it already names age under 35) | ✓ |

Golden cases: every earlier case now states `age: 60`; four new cases: age 34 → does_not_apply; age 35 →
solid_single_6to8_low; age not stated → needed [age]; exclusion true with age not stated → does_not_apply. Gates 1-4
pass.

Gate 5 re-run (evidence.md): age_band 0.85, applies.case0 0.86, outcome.does_not_apply 0.83. Newly flagged:
applies.case12 and management.row20, both unchanged table restatements that passed last run (Jev run-to-run variance),
checked by hand against the table, p3. reference.pit.volume cleared.

Fix round 2 (independent clinical read, findings 3, 4, 5, 7). Clauses read in the source: S1 p2 body ("in these
patients, treatment should be based on the specific clinical situation"; for young patients "management decisions
should be made on a case-by-case basis, and the physician should recognize that infectious causes are more likely than
cancer and that use of serial CT should be minimized"; "known primary cancers who are at risk for metastases";
"immunocompromised patients who are at risk for infection") and p2 "Implications for Patient Care".

| Item | Check |
|---|---|
| `applies` case 0 and outcome `does_not_apply`: locator moved from the p3 table note (which does not name age) to S1 p2 "Implications for Patient Care", which names under-35, immunocompromised and cancer, with screening sent to Lung-RADS in the next bullet | ✓ |
| outcome `does_not_apply`: new caveat "Under 35: decide case by case; infection is more likely than cancer, so keep serial CT to a minimum." (our words, p2) | ✓ |
| input `exclusion`: label and `how_stated` now use the source's qualifiers ("immunocompromised and at risk for infection", "known primary cancer and at risk for metastases"); the invented examples (transplant, chemotherapy, HIV) are dropped | ✓ |

Golden cases: one new case, age 34 with `exclusion` not stated → does_not_apply (age settles it without asking the
exclusion). Gates 1-4 pass.

Gate 5 re-run (evidence.md): applies.case0 0.87, outcome.does_not_apply 0.86, the new caveat 0.93. Newly flagged:
reference.pit.volume 0.49, management.row5 0.45 and outcome.subsolid_multiple_lt6 0.45, all unchanged facts that passed
before (Jev run-to-run variance), checked by hand against the table, p3; management.row20 cleared.

**For Hassan (eligibility)**
- DECISION: age is split out of the combined exclusion into its own `age` input (shared fact `age_years`), so one age
  answer serves the Fleischner and BTS cards; `exclusion` now covers screening, immunocompromise and known primary
  cancer only.
- The single does_not_apply case (exclusion or under 35) cites p2 "Implications for Patient Care", which names all
  four exclusions (fix round 2; it cited the p3 table note, which does not name age). One case keeps "excluded
  whatever the other input says" working in both directions.
- The does_not_apply outcome now carries the source's advice for under-35s as a caveat (case by case, infection more
  likely than cancer, minimal serial CT, p2). The Figure 7 note on short-term follow-up for infection in
  immunocompromised patients is not added.
- Age 35 exactly is in scope ("younger than 35" is excluded).
- Most dictations state neither age nor exclusions, so most Fleischner cards open as check_first until answered.

Independent clinical read (skill step 8): PENDING, dispatched by the controller.
