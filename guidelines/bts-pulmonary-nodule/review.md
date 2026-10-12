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

## Jev check items (evidence.md: 36 of 77 below 0.5)

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
