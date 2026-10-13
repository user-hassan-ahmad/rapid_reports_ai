# Guideline library, first slice: schema-proof checkpoint

Date: 2026-10-12. Branch `feat/scratchpad-copilot`. Spec gate: "all four systems fit with no special-case attributes".

## 1. Verdict

**Passed.** TNM, Fleischner 2017, Bosniak 2019 and BTS 2015 all fit the one schema. No system needed an attribute that exists for that system alone. Every strain was resolved either by a pack-level workaround (section 2) or by one of two general schema or engine changes made during the slice.

| Change | Triggered by | Why it is general, not a special case |
|---|---|---|
| (a) Engine settles a single possible outcome (`ebd514a`). When partial evaluation is bounded and exactly one outcome remains, that outcome is the result. Preview also refuses to propose text that still holds a placeholder. | Fleischner: solid single >8 mm with risk unknown returned no outcome, because a table step waits for every key. | Any table or rules step can have a key that cannot change the answer. Settled-by-enumeration is exact, not a heuristic. No pack attribute was added. |
| (b) Declared numeric input ranges (`min_value`, `min_inclusive`, `max_value`, `max_inclusive`; numbers only, non-empty). The engine rejects out-of-range values, domains sample only inside the range, a new `_formulas` verify gate samples every derive step over its ranges, and `pow`/`exp` errors become `EvaluationError`. | BTS: a resolved nodule (volume 0) or zero interval crashed with ln(0) or 0 divided by 0. | Any formula over a measurement is exposed to the same crash. A pack-only "resolved" route would have left every future formula open. Ranges are optional and used by BTS only because it is the only formula pack so far. |

## 2. Per system

| | TNM | Fleischner 2017 | Bosniak 2019 | BTS 2015 |
|---|---|---|---|---|
| Step types | (own schema `tnm_schema`) | band, table | band, rules | derive, score (logistic), band, rules |
| Inputs | n/a | 4 | 10 | 14 |
| Rows or rules | 36 sites | 24 table rows | 16 rules cases | 14 pathway cases (11 steps ahead of them) |
| Outcomes | n/a | 15 | 6 | 14 |
| Golden cases | n/a | 27 (1 source) | 44 (8 source) | 38 (1 source) |
| Enumerated (gate 2) | 6,479 reproduced byte for byte against `tnm.proposal` | not recorded in report | 184,320 (cap 200,000) | 138,240 (cap 200,000) |

### Strain points and exact workarounds

| System | Strain | Workaround |
|---|---|---|
| TNM | None. All 36 staged sites pass `check()`. | n/a |
| Fleischner | Source rounds to the nearest millimetre. | Half-up rounding as band edges: `<5.5`, `[5.5, 8.5)`, `>=8.5` (p5: "<6 mm = rounded 5 mm or less"). No `round` operator. |
| Fleischner | Comment cells span rows and differ by row. | Outcomes split by (recommendation, comment) pair: 15 outcomes, "No routine follow-up" appears four times. |
| Fleischner | Subsolid "Multiple" is one shared source row. | GGN and part-solid rows point to the same two outcomes; `risk` is `@not_applicable` for subsolid rows. |
| Fleischner | Single possible outcome not settled. | Engine change (a). Pinned by a golden case (12 mm, risk not stated). |
| Bosniak | Source thickness and protrusion sizes are integer-mm categories with gaps (2 to 3, 3 to 4 mm). | Category enums (<=2 / 3 / >=4 mm) instead of mm numbers, so no edge is invented. |
| Bosniak | Single `enhancement` input conflated wall, septa, protrusion and mass (review I-1). | Enhancement per structure, in the source's own terms (wall, septa, protrusion options each carry it), plus `contents_enhancement` for the mass itself, asked on renal mass protocol CT only. All 15 rules re-derived. |
| Bosniak | 20 to 21 HU gap. | Closed at ">20". |
| Bosniak | Tables 2 to 4 are images. | Rules built from the image tables read by hand; see section 3. |
| Bosniak | Highest class wins. | `none` exclusions in each rules case, so every combination has exactly one outcome. |
| BTS | "Previous imaging?" would be a rule on `prior_study`. Gate 2 enumerates band ids independently of inputs, so `prior_study = true` with every growth band `not_applicable` has no outcome. | Prior imaging is tested as `vdt_band` state `not_applicable`. Opaque to a reader. |
| BTS | Impossible band mixes (for example growth >=25% with negative VDT) must still get one outcome. | Growth rules written as a partition with `none` complements. A maintenance burden; a first-match or "otherwise" construct is a candidate for later. |
| BTS | BTS prints no Brock coefficients. | McWilliams 2013 Table 2, model 2b, filed as a second `primary` source. Checked against an independent Python snippet (engine within 5e-7). |
| BTS | Resolved nodule and zero interval crashed. | Engine change (b). |
| BTS | Caveats have no locator of their own. | The Dec 2015 correction caveat sits under the outcome's S1 locator. Open minor. |

Both BTS workarounds were rated "strains, not none" by the reviewer. Neither needed a pack-specific attribute.

## 3. Gate 5 (Jev evidence)

| Pack | Facts | Below 0.5 | How resolved |
|---|---|---|---|
| Fleischner | 85 | 15 (after integration re-run) | All read against the page images in review.md. Most are table rows where ">=6 mm" spans two of our bands, the shared subsolid row, or pdftotext layout artefacts. Two real boundary items (mixed multiple, part-solid "whole nodule"). |
| Bosniak | 55 | 28 | Same table-only facts as the first run: class definitions that exist only in the Table 2 and 3 images, Table 4 management wording, and two scope statements. Only new item after integration (`class.case8`) resolved by checklist row 8. |
| BTS | 79 | 38 | Figure-only facts, formula steps (no printed formula to score against), a caveat from the amendment under an S1 locator, cross-page synthesis, one judgement call. No fact found wrong. |

**Limitations of the Jev gate on this source mix.**
- **Image-only tables.** Bosniak Tables 1 to 4 are images on the open-access page; Fleischner Table and BTS Figures 1 and 2 are figures. Jev scores text only, so low scores on these are expected and are resolved by hand read, not by Jev.
- **Page-less HTML source (Bosniak).** The primary is the PMC full-text HTML, so locators are section or table, not page. `jev_evidence.py` then feeds the whole text file, the Jev client keeps only 6 of 10 windows, and the early windows are mostly PMC navigation text. Later sections, including the management paragraph, were never scored. The gate is weak for Bosniak; the hand read in review.md carries it.
- BTS formula steps score near zero by construction (0.05 to 0.23): the source prints no formula text to match.

## 4. Independent clinical reviews

| Pack | Result | Findings |
|---|---|---|
| Fleischner | Approved, clean | Every row, caveat, hedge word, band edge and case checked against the page images. Seven minors only (locator slips, stale evidence file, optional caveats, a pinning case). Reviewer agreed with all nine For-Hassan items. |
| Bosniak | Needs fixes, then clean after fix round | **I-1:** the single enhancement input misclassified defined masses (over-calls to IV, III or IIF; type 3 cysts with an enhancing wall sent to unclassifiable). Fixed by per-structure enhancement. Re-review: no Critical or Important. Three minors (N-1 to N-3) applied in integration. |
| BTS | Approved with one fix, then clean | **I-1:** a resolved nodule (volume 0) or zero interval raised `ln of 0.0` / `0/0` at runtime. Fixed by engine change (b), with new tests, golden cases and pitfalls. Re-review: no Critical or Important. |

## 5. For Hassan: boundary items

Marked **DECISION** where it is a judgement call needing your decision; otherwise it is an encoding note the reviewers agreed with.

### Fleischner 2017
| # | Item | |
|---|---|---|
| F1 | Exclusions (screening, age <35, immunocompromise, known primary cancer) are a pitfall and a caveat on every outcome, not inputs, so the card will answer for an excluded patient. | **DECISION** (known primary cancer is common on staging CT) |
| F2 | Outcomes split where table comments differ (15 outcomes). | note |
| F3 | The solid single <6 mm high-risk comment is carried on the low-risk row too, as the table prints it. | note |
| F4 | Part-solid size is the whole nodule; solid component is not an input (caveat and pitfall for 4B/4C). | **DECISION** (make it an input if the card should branch) |
| F5 | Mixed solid and subsolid multiples: the type of the most suspicious nodule is used (no table row). | **DECISION** |
| F6 | Rounding half up: 5.5 mm is 6 to 8 mm, 8.5 mm is >8 mm. Source says only "nearest millimetre". | **DECISION** (8 x 9 averages to 8.5, so this edge is common) |
| F7 | Single possible outcome with risk unknown. | resolved in engine, pinned by a case |
| F8 | Source is the online-ahead-of-print mirror, not the issue-paginated copy. | provenance, swap when available |
| F9 | Figure 14 case uses the stated 10 mm GGN (the part-solid lesion has no size). | note |

### Bosniak 2019
| # | Item | |
|---|---|---|
| B1 | Thickness and protrusion are category enums (<=2 / 3 / >=4 mm) because the source leaves 2 to 4 mm undefined. | **DECISION** |
| B2 | 20 to 21 HU gap closed at >20. | **DECISION** |
| B3 | Class I versus II type 4: II type 4 is unenhanced-only CT; class I on renal mass protocol, portal venous or other contrast CT. | **DECISION** |
| B4 | Calcification without septa is class II (II types 2, 4, 5 allow it; class I does not). | **DECISION** |
| B5 | "Not enhancing" and "not assessable" merged for wall, septa and protrusion (both go to MRI via footnote †). Done to stay under the gate cap. | **DECISION** |
| B6 | One septa value per mass, from the highest-class enhancing septum; a non-enhancing thick septum alongside enhancing thin ones is reported as the enhancing one, with the class II caveat pointing to MRI. | **DECISION** |
| B7 | On renal mass protocol CT, a mass that itself enhances is unclassifiable (not a cystic mass), on every path including II type 1 and at >=70 HU. | **DECISION** |
| B8 | Undefined combinations go to unclassifiable (too small but not homogeneous low; complex without enhancing feature; ill-defined; heterogeneous without septa; <-9 HU; 31 to 69 HU unenhanced; >30 HU portal venous; >20 HU other contrast; enhancing mass on RMP). "May warrant IIF" kept as a caveat only. | **DECISION** |
| B9 | II type 1 (few thin septa) leaves attenuation and contents free, as the source does. | note |
| B10 | Issuer shown as "Society of Abdominal Radiology (Silverman et al.)". | note |

### BTS 2015
| # | Item | |
|---|---|---|
| T1 | Brock coefficients from McWilliams 2013 as a second primary source. | provenance |
| T2 | Dec 2015 correction: <5 mm in previous or active cancer is clinical judgement. Caveat and pitfall, not an input (`cancer_history` would let the pack withhold "no follow-up"). | **DECISION** |
| T3 | 10% Brock edge: figure (>=10%) followed over text (>10%). | **DECISION** |
| T4 | 400-day VDT edge: figure (<=400) followed over text (<400). | **DECISION** |
| T5 | "1 year" = 365 days, no tolerance for early scans. | **DECISION** |
| T6 | Added `volume_change_pct` and a >=25% `change_band`; work-up needs both >=25% and VDT <=400. | **DECISION** |
| T7 | Shrinkage: no BTS step; before 1 year CT at 1 year, at 1 year or more discharge (`smaller_discharge`). | **DECISION** |
| T8 | Fitness for treatment and volumetric size thresholds (80/300 mm3) are not inputs. | note |
| T9 | `benign_features` is a required input (Fig 1's first box). | note |
| T10 | BTS worked example (0.3%) not reproducible without count, family history, emphysema; kept on outcome only. | note |
| T11 | "Clear evidence of growth" is not encoded apart from VDT. | **DECISION** |
| T12 | No growth route without volumetry; 2D arm (CT at 2 years) is a caveat and pitfall only. UK practice often lacks volumetry. | **DECISION** |
| T13 | Lingula treated as left upper lobe for the Brock upper-lobe term (our call). | **DECISION** |
| T14 | Resolved nodule has no route (volume 0 refused, volume asked); a `resolved` input leading to discharge is the fuller shape. | **DECISION** |
| T15 | Age range 18 to 110: 18 from scope, 110 is our plausibility bound. | **DECISION** |

## 6. Open items

**Source files needing manual filing**
- McWilliams 2013 NEJM PDF (BTS S2): only a text extract of Table 2 is filed; PMC blocks scripted download.
- BTS Dec 2015 correction PDF (Thorax 2015;70:1188, A1): text extract only; BMJ blocks scripted download.
- Bosniak publisher PDF: primary is the PMC HTML plus text and Table 1 to 4 images; the PDF is behind a bot wall. Table images are listed in review.md because the manifest schema forbids extra file fields.
- Fleischner: swap the ahead-of-print mirror for the issue PDF (284:228 to 243) and update the sha.

**Deferred minors that matter clinically**
- Fleischner: `pit.partsolid` locator should read pp. 9 to 10; GGN <6 mm caveat not carried onto part-solid <6 mm; a dominant >8 mm nodule among multiples should name the solitary >8 mm pathway (Rec 2); Figure 14 case should use type part-solid.
- BTS: out-of-range age or a resolved nodule leaves the card asking for a value the radiologist cannot give (needs a "resolved" or "out of scope" route); `_formulas` skips derive-on-derive; partial evaluation over-asks unbounded numbers when any formula input is unknown.
- Bosniak: partial evaluation on a domain this size may hit `MAX_COMBOS` (50k) at request time; watch latency in the preview lab.
- Engine: settled partial cases count as reaching an outcome in `_golden`; unbounded fallback over-asks.
- Pack gate: Fleischner recall under the applicability gate is 3/9 (`PACK_GATE_MIN` 0.7); false passes 0/15.
