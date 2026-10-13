# Gate 6: hand read, bta-thyroid-u-grading@2014.1

Read side by side with the PDF page images (Read tool, PDF pages 28–31) and `sources/43e9…727c.txt`. Locator pages
are 1-based PDF pages of the Wiley supplement (136 pages). Journal page = PDF page − 14 in Chapter 4: journal p14 = PDF
p28, p15 = p29, p16 = p30 (Fig. 4.1), p17 = p31 (Fig. 4.2, Table 4.3).

## Pack type

Tier 1, one dictated `u_grade` enum → `table` → outcome. The source's action is keyed by grade (4.3 i: U1–U2 no FNAC
unless statistically high risk; 4.3 ii: U3–U5 US-guided FNAC; Fig. 4.2 branches on "U1-2" and "U3-5"). Fig. 4.1 is a
pictorial compilation of signs, not a feature-to-grade algorithm, so it lives in `reference.tables` (see For Hassan 1).

## Input

| item | source | |
|---|---|---|
| `u_grade` U1–U5 | p30 Fig. 4.1 (U1 Normal, U2 Benign, U3 Indeterminate/Equivocal, U4 Suspicious, U5 Malignant) | ✓ |
| `how_stated`: the U score of this nodule; the report also records the most suspicious nodule's score | p29 4.4 ii "the score for the most suspicious nodule should be recorded" (a reporting rule, not a management collapse) | ✓ |
| no `absent` / `not_assessable` states | the source recognises neither | ✓ |
| no eligibility inputs | scope text (p8 adult focus; p15 no lymphoma or thyroid metastases) does not exclude patients from the U classification; carried as `pit.scope` | ✓ (For Hassan 7) |

## Table rows (5) and outcomes (5)

| outcome | row | source | |
|---|---|---|---|
| u1_normal | U1 | p30 Fig. 4.1 "U1. Normal"; p28 4.3 i (U1–U2 reassuring, FNAC not required unless statistically high risk, Ch 3.7) (2++, B); p29 4.5 i (benign: discharge, routine US follow-up not recommended); p31 Fig. 4.2 "Benign appearance (U1-2) → No follow-up required"; p31 4.6 i | ✓ |
| u2_benign | U2 | p30 Fig. 4.1 U2; same recommendations as U1 | ✓ |
| u3_indeterminate | U3 | p30 Fig. 4.1 U3; p28–29 4.3 ii "equivocal, indeterminate or suspicious of malignancy (U3–U5), an US guided FNAC should follow" (2++, B) | ✓ |
| u4_suspicious | U4 | p30 Fig. 4.1 U4; 4.3 ii; p29 4.4 iv "When a malignancy is suspected a full assessment of the remainder of the neck for associated lymph node metastases is mandatory" | ✓ |
| u5_malignant | U5 | p30 Fig. 4.1 U5; 4.3 ii; 4.4 iv | ✓ |

## Caveats

| caveat | outcomes | source | |
|---|---|---|---|
| clinical features of higher malignancy probability | u1, u2 | p25 3.7 list: age <20 or >60, firmness, rapid growth, fixation, vocal cord paralysis, regional lymphadenopathy, neck irradiation, family history (4.3 i points to Ch 3.7) | ✓ |
| discharge only when asymptomatic, no clinical suspicion | u1, u2 | p29 4.5 i | ✓ |
| pregnancy: U3 FNAC may be deferred until after delivery by preference | u3 | p75 14.1 iii (2+, C) | ✓ |
| Thy1 or Thy2 cytology → repeat FNAC | u3, u4 | p29 4.5 iii (suspicious US + Thy1 → repeat US-guided FNAC), 4.5 iv (Thy2 + indeterminate or suspicious US → repeat FNAC) | ✓ |
| Thy1 → repeat FNAC; Thy2 → review clinical and US suspicion, if high repeat US-guided FNAC or MDT discussion | u5 | p31 Fig. 4.2 (U3-5 branch: Thy1 → "Repeat FNAC"; Thy2 → "Review clinical and US level of suspicion" → high → "Repeat US guided FNAC or MDT discussion"); p29 4.5 iii | ✓ (fixed after the independent read; For Hassan 5) |
| abnormal neck node → FNAC | u4, u5 | p29 4.3 iii (2++, B) | ✓ |
| nodule <1 cm: extrathyroidal extension, nodes and clinical risk inform FNAC; otherwise clinician and MDT judgement, avoid overtreating microPTC | u4, u5 | p28 4.3 text | ✓ (For Hassan 4) |

## Reference

| field | source | |
|---|---|---|
| sum.1 | p28 4.2 ii (U1–U5 recommended, 2+, C); Fig. 4.1 caption p30 | ✓ |
| sum.2 | p28 4.3 i–ii | ✓ |
| sum.3 | p29 4.4 ii–iii | ✓ |
| def.nodule | p28 Ch 4 opening sentence | ✓ |
| def.taller_than_wide | p29 Table 4.1 | ✓ |
| def.spongiform | p29 Table 4.1 | ✓ |
| def.solid_cystic | p28 4.3 text (solid-portion signs "specific"; overall shape "also relevant … as a predictor", hedge kept) | ✓ |
| tab.u_classification | p30 Fig. 4.1 box, every sign (a)–(f) cell for cell; FNAC column from 4.3 i–ii | ✓ |
| tab.features | p29 Table 4.1, all 12 bullets (benign 5, papillary/medullary 5, follicular 2) | ✓ |
| tab.report_features | p31 Table 4.3, all 13 rows | ✓ |
| pit.summation | p28 4.2 ("No single US feature is diagnostic"), 4.2 i (2++, B), 4.1 ii (GPP) | ✓ |
| pit.size | p28 Ch 4 introduction and 4.3 | ✓ |
| pit.discordance | p30 4.4 v (4, C) | ✓ |
| pit.scope | p15 1 Introduction (lymphoma, metastases); p8 front matter (adult focus); p78 Ch 15 intro and i (principles similar; nodules more likely malignant, lower surgical threshold) | ✓ |
| pit.ct | p31 4.6 ii (4, D), with the three suspicious CT findings named | ✓ |
| pit.pet | p31 4.6 iii (1++, A) | ✓ |
| pit.nodes | p29 4.3 iii | ✓ |

## Golden cases

No worked examples in the source. Seven of ours: one per grade (each outcome reached), and two with `u_grade` unknown
(omitted; explicitly `unknown`) asserting `needed: ["u_grade"]`. No numbers, so no band edges.

## Gate 5 flags (24 below 0.5, re-run after the read's fixes)

Gate 5 reads only the locator's first page; most of these facts span several pages or live in figures.

| field | Jev | resolution |
|---|---|---|
| grade.row0–row4, outcome.u1–u5 | 0.18–0.49 | Confirmed by own reading: the grade names are in Fig. 4.1 (p30, figure text) and the actions in 4.3 i–ii (p28–29) and 4.4 iv (p29); the cited page holds only 4.3. |
| u1.caveat0, u2.caveat0 (risk features) | 0.05 | Confirmed: p25 Ch 3.7 list, outside the outcome's first-page locator. |
| u3.caveat0 (pregnancy) | 0.03 | Confirmed: p75 14.1 iii, outside the outcome's first-page locator. |
| u4.caveat1, u5.caveat1 (<1 cm) | 0.47, 0.44 | Confirmed: p28 4.3 text. |
| u5.caveat2 (repeat FNAC) | 0.30 | Confirmed: p29 4.5 iii and p31 Fig. 4.2 arrows (image), re-traced by the independent read. |
| sum.1 | 0.43 | Confirmed: p28 4.2 ii and p30 Fig. 4.1 caption. |
| def.nodule | 0.37 | Confirmed: p28 first sentence of Ch 4, near-verbatim. |
| pit.size | 0.44 | Confirmed: p28 "correlates poorly"; 4.3 "does not support size as a reliable indicator". |
| def.taller_than_wide | 0.49 | Confirmed: p29 Table 4.1. |
| def.spongiform | 0.43 | Confirmed: p29 Table 4.1 first bullet. |
| tab.features | 0.31 | Confirmed row by row against p29 Table 4.1. |
| tab.u_classification | 0.15 | Confirmed cell by cell against the p30 Fig. 4.1 box (viewed as image). |
| pit.scope | 0.09 | Confirmed: p15 (lymphoma, metastases), p8 (adult focus), p78 (children); the window holds only p15. |

## For Hassan

1. DECISION: the card takes the dictated U grade rather than deriving it from features. Fig. 4.1 is a "graphic compilation" of signs used "in summation" (4.2 i), and its signs overlap across grades (U3(c) mixed/central vascularity vs U5(c) intranodular vascularity; U3(b) ?hypoechoic vs U4(a) solid hypoechoic), so any feature-to-grade rule would invent precedence. Fig. 4.1 is shown in full in the reference.
2. DECISION: the U1–U2 "unless the patient has a statistically high risk of malignancy" exception sits in the recommendation text, with the Ch 3.7 features as a caveat, rather than as an asked high-risk input; the source lifts the reassurance but names no action for high-risk U1–U2.
3. DECISION: "Assess the rest of the neck for nodal metastases" is in the U4 and U5 recommendations (4.4 iv: mandatory "when a malignancy is suspected"), not U3.
4. The <1 cm caveat (4.3 text: "nodules that are suspicious for thyroid malignancy") is on U4 and U5 only, not U3.
5. U5 after FNAC: 4.5 iii–iv name "suspicious" or "indeterminate or suspicious" US features, so U3 and U4 carry "repeat FNAC" for Thy1 or Thy2. For U5 the pack follows Fig. 4.2: Thy1 → repeat FNAC; Thy2 → review of clinical and US suspicion, and if high, repeat US-guided FNAC or MDT discussion. (Corrected after the independent read, which found the first draft misread the figure's Thy2 arrow.)
6. U1 is an outcome although 4.4 i lists only U2–U5 as nodule categories; Fig. 4.1 and 4.3 i include U1, with the same management as U2.
7. No eligibility inputs: the scope text (adult focus, no thyroid lymphoma or metastases) does not exclude anyone from the U classification, and Ch 15 says paediatric principles are similar; both stay as a pitfall.

## Independent read

`clinical-read.md`: no Critical; 1 Important (U5 repeat-FNAC caveat and the Fig. 4.2 description) and 5 Minor (how_stated, def.solid_cystic hedge, case names, pit.ct findings, pit.scope Ch 15 i). All six fixed; verdicts agree with For Hassan 1–4, 6, 7, and 5 is corrected as above.
