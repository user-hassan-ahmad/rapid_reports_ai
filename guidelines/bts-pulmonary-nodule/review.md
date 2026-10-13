# Gate 6 hand read: bts-pulmonary-nodule@2015.1

Read side by side with S1 (BTS 2015 supplement, PDF pages 7-11, 13, 22, 26-27, 57; Figures 1 and 2 viewed as images,
because they are pictures and absent from the pdftotext layer), S2 (McWilliams 2013 Table 2, model 2b) and A1 (BTS
correction, December 2015).

**Brock check method.** No online Brock/PanCan calculator could be driven from this session (the BTS and Brock
University calculators are interactive pages or spreadsheets, and the keyless web tools cannot submit forms). The golden
`brock` values were computed by a separate short Python snippet written straight from S2 Table 2 model 2b (not the
engine): logit = -6.7892 + 0.0287(age-62) + 0.6011 female + 0.2961 family history + 0.2953 emphysema
- 5.3854((d/10)^-0.5 - 1.58113883) - 0.1276 nonsolid + 0.3770 part-solid + 0.6581 upper lobe - 0.0824(count-4)
+ 0.7729 spiculation. The engine matches every value to 1e-6. The model's coefficients were read from the PMC author
manuscript of S2 (BTS prints no coefficients; its Appendix 1 only links to its online calculators).

**BTS worked example (p ii16, PDF p22).** "A non-spiculated 4 mm upper lobe nodule in a 70-year-old smoking woman has
a malignant probability of 0.3% (Brock)". Nodule count, family history and emphysema are not stated, so the value
cannot be checked exactly: with no family history or emphysema, the model gives 0.63% for a solitary nodule, 0.50% for
4 nodules and 0.30% for 10. The case is kept as a source case on its outcome only (under 5 mm: discharge).

## Checklist

### Bands
| step | edges | verdict |
|---|---|---|
| diameter_band | <5 / 5-<6 / 6-<8 / >=8 mm | ✓ Fig 1 (<5 discharge, <8 surveillance, else Brock), Fig 2 (5-6 mm vs >=6 mm), text p8 ("≥5 to <6 mm", "≥6 mm") |
| brock_band | <10% / >=10% | ✓ Fig 1 ("<10%", "≥10%"). Text p9 says PET-CT for ">10%": at exactly 10% the figure and text differ; figure followed (For Hassan) |
| interval_band | <365 / >=365 days | ✓ "1 year" (Fig 2, p8 text). 365-day edge is our reading of "1 year" (For Hassan) |
| change_band | <25% / >=25% | ✓ p8 "Use a ≥25% volume change to define significant growth", "stability (<25% change in volume)" |
| vdt_band | <0 / 0-400 / >400-600 / >600 days | ✓ Fig 2 ("VDT ≤400 days", "400-600", ">600"). Text p8 says "<400" for work-up: at exactly 400 days figure followed (For Hassan). Negative band is shrinkage |

### Derive and score steps
| step | verdict |
|---|---|
| size_term | ✓ S2 footnote: (size/10)^-0.5 - 1.58113883 (the PDF parse garbled the minus into an exponent; the PMC HTML and the 4 mm centring, 0.4^-0.5 = 1.5811, confirm subtraction) |
| age_term | ✓ S2: age - 62 |
| count_term | ✓ S2: count - 4 |
| volume_change_pct | ✓ (current/baseline - 1) x 100; the 25% rule (S1 p8) needs it. Added beyond the brief (For Hassan) |
| vdt_days | ✓ standard exponential VDT, ln2 x t / ln(V2/V1). S1 does not print the formula; Appendix 1 (p57) only points to the BTS VDT calculator (For Hassan) |
| brock | ✓ all ten coefficients and the intercept against S2 Table 2 model 2b ("full, with spiculation", which S1 p7 names) |

### Rules cases (pathway)
| # | result | verdict |
|---|---|---|
| 0 | discharge_benign | ✓ Fig 1 first box; p7 benign calcification, fat, typical perifissural/subpleural |
| 1 | subsolid | ✓ p8 SSN recommendations, Fig 3; outside this entry's scope by design |
| 2 | discharge_small | ✓ Fig 1, p7 "<5 mm ... Grade C"; A1 caveat added |
| 3 | ct_1yr | ✓ Fig 2 "5-6 mm diameter → CT 1 year after baseline"; p8 text |
| 4 | ct_3m | ✓ Fig 1 "<8 mm → CT surveillance (algorithm 2)"; Fig 2 ">=6 mm → CT 3 months"; p8 "repeat CT at 3 months and 1 year" |
| 5 | brock_low | ✓ Fig 1 "<10% → CT surveillance (algorithm 2)"; >=8 mm so Fig 2's 3-month arm |
| 6 | pet_ct | ✓ Fig 1, p9 Grade B (PET-CT above local detection threshold, then Herder) |
| 7 | growth_workup | ✓ Fig 2 "VDT ≤400 or clear evidence of growth → further work up"; p8; requires the 25% change (p8; NELSON, PDF p26) |
| 8 | continue_slow_growth | ✓ Fig 2: at the 3-month scan, "No" → CT 1 year after baseline |
| 9 | continue_no_growth | ✓ same branch; includes shrinkage before 1 year |
| 10 | vdt_400_600 | ✓ Fig 2, p8 "Consider ongoing yearly surveillance or biopsy ... 400-600 days" |
| 11 | vdt_gt600 | ✓ Fig 2 ("only if based on volumetry"), p8 (fitness and age) |
| 12 | stable_discharge | ✓ Fig 2 "Stable on basis of volumetry → Discharge"; p8 |
| 13 | smaller_discharge | judgement: BTS has no shrinkage step; p26 groups "stable, shrunken or resolved" nodules with a low cancer probability (For Hassan) |

Rule order follows Fig 1: benign → <5 mm → previous imaging (algorithm 2) → <8 mm → Brock. "Previous imaging" is read
from the VDT band's state (not_applicable exactly when there is no prior CT), so the enumeration gate stays total.

### Outcomes
All 14 outcomes ✓ against the rows above. Wording is ours, under 25 words each. Caveats checked: benign (larger
intrapulmonary nodes, p7) ✓; subsolid (<5 mm SSN no follow-up, p8) ✓; discharge_small (A1 correction; 80 mm3, p7) ✓;
"unfit for any treatment → discharge" (Fig 1) ✓; brock_low young-patient PET-CT (Fig 1 footnote $) ✓; extrapulmonary
primary (p8) ✓; 2D diameters → 2 years (p8, Fig 2) ✓; discharge only on volumetry (Fig 2) ✓.

## Jev check items (evidence.md, rerun after fix round 1: 38 of 79 below 0.5)

All resolved by hand; no fact was wrong. Causes:
- **Figure-only facts** (Figures 1 and 2 are images with no text layer): brock_band, interval_band, vdt_band,
  pathway cases 3, 6, 8, 9, outcomes ct_1yr, continue_slow_growth, continue_no_growth, the "unfit" caveats
  (ct_1yr, ct_3m, brock_low, pet_ct), brock_low young-patient caveat, vdt_gt600 volumetry caveat, pit.unfit,
  pit.herder, sum.2. Each checked against the figure images on PDF pages 8 and 9. ✓
- **Formula steps** (Jev cannot match an equation to prose): size_term, age_term, count_term, brock, def.brock
  (against S2 Table 2), volume_change_pct, vdt_days, def.vdt (standard VDT formula, not printed by BTS). ✓
- **Caveat from another source under an S1 locator**: discharge_small caveat 0 is from A1 (correction); outcome
  caveats carry no locator of their own, so it sits under the outcome's S1 locator. A1 is cited by pit.cancer (0.84).
  discharge_small caveat 1 (80 mm3) is on p7, outside the p8 window. ✓
- **Synthesis across pages**: pit.multiple (p8 "largest nodule"; count in Brock is our note), pit.vdt (p8 software
  variation, our "use the same one"), pit.volumetric and pit.brock (p7). ✓
- **Our judgement**: pathway case 13 and smaller_discharge (shrinkage; see For Hassan). Accepted as flagged.
- **Fix round 1 additions**: pit.2d (Figure 2's 2D-diameter arm, an image) ✓; pit.resolved (p26 discusses resolving
  nodules; "no route here" is a statement about this entry) ✓. sum.4 flagged this run only (Jev variance; it
  restates Figure 2) ✓.

## Fix round 1: input ranges
Declared valid ranges (the engine refuses values outside them, so pack preview asks instead):
diameter_mm > 0; prior_volume_mm3, current_volume_mm3, interval_days > 0; nodule_count >= 1; age 18-110.
The age minimum cites S1 p13 (children under 18 not covered); the 110 maximum is our plausibility bound, not sourced.
The verify range check samples every derive step across these ranges: none fails. Equal volumes give an infinite VDT
(band "over 600 days") with 0% change, so stable or CT at 1 year (two new golden cases). A resolved nodule (volume 0)
is refused as a value and the volume is asked.

## For Hassan

1. **Brock coefficients come from McWilliams 2013 (S2), added as a second `primary` source.** BTS adopts the model
   (full, with spiculation) but prints no coefficients. S2 was filed as a text extract of Table 2 (PMC blocks scripted
   PDF downloads); please drop the PDF in `sources/` if you want the original kept.
2. **BTS correction (Dec 2015) filed as amendment A1** (text extract; the BMJ site blocks scripted download). It makes
   follow-up of <5 mm nodules in previous or active cancer a matter of clinical judgement. Encoded as a caveat and a
   pitfall, not as an input; an input `cancer_history` would let the pack withhold "no follow-up" in that group.
3. **10% Brock edge**: Figure 1 says ≥10% → PET-CT; the text says >10%. Followed the figure.
4. **400-day VDT edge**: Figure 2 says ≤400 → work-up; the text says <400. Followed the figure.
5. **"1 year" = 365 days** from baseline. A 1-year scan done at 350 days counts as "before 1 year" (CT again at 1
   year). A tolerance (e.g. 330 days) would be a local choice the source does not give.
6. **Added `volume_change_pct` and `change_band`** (not in the brief's sketch): BTS defines significant growth as ≥25%
   volume change, so a 20% rise at 3 months (VDT ~346 days) is not growth. Work-up needs both ≥25% and VDT ≤400.
7. **Shrinkage**: BTS has no explicit step. Before 1 year it follows the algorithm's "no" branch (CT at 1 year); at 1
   year or more it is discharged like a stable nodule (outcome `smaller_discharge`, with a caveat saying so).
8. **Not asked**: fitness for treatment (Fig 1 discharges the unfit) is a caveat, not an input. Volumetric size
   thresholds (80/300 mm3) are a pitfall; size steps use diameter only.
9. **`benign_features` is an input**, so the pack asks for it whenever it is not dictated (Fig 1's first box).
10. **BTS worked example** (0.3% Brock) cannot be reproduced without nodule count, family history and emphysema
    (0.30% if 10 nodules and neither); kept as a source case on outcome only.
11. **"Clear evidence of growth"** (Fig 2) is not encoded apart from VDT: ≥25% growth with VDT over 400 days before
    1 year goes to CT at 1 year, not work-up. Reason: at 1 year every ≥25% growth with VDT over 400 days falls in
    the 400-600 or >600 arms, so "clear growth" cannot simply mean ≥25%. A radiologist's visual "clear growth" call
    is not an input.
12. **(Done in fix wave 2, T12.) No growth route without volumetry**: with diameters only, the pack asks for volumes; Fig 2's 2D arm (CT at 2
    years) is a caveat and pitfall only. UK practice often lacks volumetry.
13. **Lingula**: S2 compares the upper lobes with the rest and never mentions the lingula; how_stated says to treat it
    as left upper lobe (anatomical, our call).
14. **(Done in fix wave 2, T14.) Resolved nodule**: no route (volume 0 is refused, the volume is asked). A boolean `resolved` input leading to
    discharge would be the fuller shape (reviewer suggestion); BTS p26 supports a low risk but gives no step.
15. **Age range 18-110**: 18 from the guideline's scope; 110 is a plausibility bound of ours.

## Fix wave 2 (2026-10-12): Hassan's verdicts T12 and T14

Read again side by side with S1 p8 (Summary of recommendations, imaging follow-up) and Figure 2 (PDF page 9, viewed
as an image).

- **T12, the diameter (2D) route.** What the source states: Figure 2 starts from "baseline volumetric analysis (or
  diameter measurement if volumetry not available/technically possible)"; at 3 months, "VDT ≤400 days or clear
  evidence of growth?" yes → further work-up, no → CT 1 year after baseline; at 1 year, "stable on basis of 2D
  non-automated diameter value" → CT 2 years after baseline → "VDT assessment and manage as per VDT categories at 1
  year. Discharge if stable"; p8: "If two-dimensional diameter measurements are used to assess growth, follow-up with
  CT for a total of 2 years" (Grade D). The source gives **no diameter growth threshold**.
  Encoded: a new input `growth` (prerequisite: prior CT, not resolved) with options `volumetry`, `diameter_stable`,
  `diameter_clear_growth`, `diameter_indeterminate` (one input, not method plus change, to keep the enumeration under
  its cap); the volumes now require `growth = volumetry`. The interval band gains a 2-year edge (under 1 year; 1 to
  under 2 years; 2 years or more); the volumetric cases read "1 year or more" as the last two bands. New cases:
  clear growth → `growth_workup_2d` (any interval); stable before 1 year → `continue_no_growth` (CT at 1 year);
  stable at 1 to under 2 years → `ct_2yr_2d`; stable at 2 years or more → `stable_2d_discharge`; any other diameter
  change (small or equivocal increase, or a decrease) → `volumetry_advised`, an explicit library routing labelled in
  its caveat as not a BTS step. The no-prior cases (ct_1yr, ct_3m, Brock) now also require "growth not by diameter",
  and the 2D cases require the VDT band to be not applicable, so the cases stay exclusive under the gate's band
  overrides.
- **T14, resolved.** New boolean input `resolved` (prerequisite: prior CT) → outcome `resolved` ("Previously seen
  nodule has resolved on this CT; no further nodule follow-up"), its caveat labelling it a library addition, not BTS
  text (p26 evidence review: low cancer probability for resolved or shrunken nodules). Every other case requires "not
  resolved". `how_stated` makes a described nodule `resolved = false`, so the model settles it from the description.
  pit.resolved and pit.2d rewritten to match.
- **Engine change behind T12:** a formula step blocked by both an unknown and a not-applicable input now takes
  not_applicable (it can never compute), so a 2D case with the interval unknown still reaches its outcome.
- **Gate change behind T12:** the enumeration leaves out inputs that reach the result only through a band step (the
  band is overridden with each id anyway): Brock's sex, family history, emphysema, upper lobe and spiculation.
- Golden cases: earlier prior-CT cases state `resolved: false, growth: volumetry`; the source worked example states
  `resolved: false` (the nodule is described); "7 mm, prior imaging not stated" now needs prior_study, resolved,
  growth, both volumes and the interval; 12 new cases cover every 2D arm, both interval edges (365, 729, 730 days),
  resolved, and needed lists. Gates 1-4 pass.
- Gate 5 re-run (evidence.md): the new Figure 2 facts score low as before (image-only); volumetry_advised 0.43 and
  case 0.57; resolved items low (a library addition, labelled). Each checked by hand against Figure 2 and p8/p26.

## Next slice (2026-10-13): eligibility input (spec §3.6)

Scope clause read in the source: S1 p13, "Groups not covered": "A. Children (younger than 18) with pulmonary nodules"
(and "Groups covered": "A. Adults (≥18 years)").

| Item | Check |
|---|---|
| input `age` now eligibility (patient scope, fact `age_years`); `min_value` 18 → 0; max 110 kept; locator moved from S2 Table 2 (Brock age) to S1 p13 "Groups not covered" | ✓ (see For Hassan) |
| input `sex`: fact `sex` (options female, male) | ✓ |
| band `age_band`: `lt18` under 18 (max 18, exclusive), `ge18` 18 or over (min 18, inclusive): "younger than 18" / "≥18 years" | ✓ |
| `pathway` case 0 (new): `age_band` lt18 → does_not_apply, S1 p13 | ✓ |
| `pathway` earlier cases: each now also requires `age_band` ge18 | ✓ |
| outcome `does_not_apply` (new): "BTS 2015 does not apply: the guidelines do not cover patients under 18" → "Manage per the clinical context.", S1 p13 | ✓ |

Golden cases: earlier cases that gave no age now state `age: 65` (those giving an age, or asking for it, are
unchanged); three new cases: age 17 → does_not_apply; age 18 → discharge_benign; age not stated → needed [age]. Gates
1-4 pass.

Gate 5 re-run (evidence.md): age_band 0.60, pathway.case0 0.57, outcome.does_not_apply 0.53 (none flagged; confirmed
by reading p13). Newly flagged: pathway.case5, pathway.case19, reference.sum.4, all unchanged facts (Jev variance; six
earlier flags cleared the same way), checked by hand as before. age_term 0.05 as before (the coefficient sits in the
S2 table image).

Fix round 2 (independent clinical read, finding 1). Clause read in the source: S1 p13, "Groups not covered": "B.
Adults where the nodule in question has been pathologically shown to represent lung cancer or a pulmonary metastasis
from another cancer".

| Item | Check |
|---|---|
| input `proven_malignant` (new): boolean, lesion scope, eligibility, no shared fact; true only on histology or cytology of this nodule; a known cancer elsewhere or a suspected malignancy does not make it true; locator S1 p13 Groups not covered B | ✓ |
| `pathway` case 0: `age_band` lt18 or `proven_malignant` true → does_not_apply (either settles it alone); locator S1 p13 Groups not covered A and B | ✓ |
| `pathway` cases 1-20: each now also requires `proven_malignant` false | ✓ |
| outcome `does_not_apply`: classification names both exclusions; locator as case 0 | ✓ |
| `pit.scope` kept (it already named B) | ✓ |

Gate 2 now enumerates 184,320 combinations (was 92,160), under the 400,000 cap. Golden cases: every earlier case
that reaches an outcome or asks for inputs now states `proven_malignant: false`; four new cases: proven metastasis
(otherwise a full Brock description) → does_not_apply; proven lung cancer with nothing else stated → does_not_apply;
not proven → discharge_benign; not stated → needed [proven_malignant]. Gates 1-4 pass.

Gate 5 re-run (evidence.md): pathway.case0 0.73, outcome.does_not_apply 0.67 (inputs are not scored). Newly flagged:
pathway.case20 0.46 and outcome.volumetry_advised.caveat0 0.47, both unchanged Figure 2 facts (image-only, Jev
variance); pathway.case16 cleared. Checked by hand as before.

**For Hassan (eligibility)**
- DECISION: the `age` minimum drops from 18 to 0, so an under-18 age is accepted and excludes the card (it was
  refused and asked before).
- The `age` input now cites the scope clause; the Brock age coefficient stays cited by the `age_term` step (S2).
- DECISION (fix round 2): "Groups not covered" B (a nodule already proven on histology or cytology to be lung cancer
  or a metastasis) is now a lesion-scoped eligibility input, `proven_malignant`, leading to does_not_apply. It is
  settled only from this nodule's own finding and is otherwise asked, so most BTS cards now ask it as well as age.
  Previous-or-active cancer stays a caveat and pitfall (decision T2): the guideline covers adults with current or
  previous malignancy (Groups covered C and D), so a known cancer elsewhere never makes `proven_malignant` true.
- DECISION (fix round 1): `prior_study` and `interval_days` are lesion-scoped (per nodule), so they are asked unless
  the nodule's own finding states the earlier CT and its interval; a comparison stated for another lesion never
  settles them.

Independent clinical read (skill step 8): PENDING, dispatched by the controller.

## Size scope (2026-10-13, live Chrome test: a 3.8 cm mass showed "applies")

Source: S1 PDF p11, Table 1. A pulmonary nodule is a "focal, rounded opacity ≤3 cm diameter"; part-solid nodules
and pGGNs are likewise "≤3 cm". The reference card already said so (`def.nodule`, `pit.scope`), but the logic did not
exclude a larger opacity.

Checklist:
- band `mass_band` on `diameter_mm`: `le30` = ≤ 30 mm (max inclusive); `gt30` = > 30 mm. Locator: p11, Table 1. ✓
- pathway: a new does_not_apply case, all(age ≥18, not proven malignant, not resolved, `mass_band` gt30), with the
  Table 1 locator. It cannot overlap the first does_not_apply case (age ≥18 and not proven malignant) or `resolved`. ✓
- every other case except `resolved` now also needs `mass_band` le30. A resolved nodule has no current size, so
  `resolved` never needs one. ✓
- does_not_apply outcome text adds "or an opacity over 3 cm (a mass, not a nodule)". ✓
- golden cases: 30 mm → pet_ct (edge, still a nodule); 30.5 mm → does_not_apply; 38 mm solid and 38 mm part-solid →
  does_not_apply; 38 mm with eligibility and prior imaging unknown → needed [age, proven_malignant, prior_study]. ✓
- engine: `_non_excluding` now accepts an eligibility value when no does_not_apply case holds (`is not True`), so
  an exclusion that also reads a still-unknown clinical input (this size) does not block the in-scope eligibility
  value. No other pack has such a case today, so nothing else changes.
- gates 1–4 pass (`check_pack.py`). The gate 5 Jev evidence and the clinical read are done by the controller and
  reviewer.

**For Hassan**
- DECISION: the cut-off follows the source: "≤3 cm" is a nodule, so 30 mm still applies and only over 30 mm is a
  mass. The live-test request said "≥ 30 mm".
- DECISION: the size is now needed for every outcome except `resolved`. A card with clear benign features but no
  stated size used to settle at discharge_benign; it now asks the diameter. With the diameter unknown, the Brock
  formula is unbounded, so its inputs are asked as well, until the diameter is known.
