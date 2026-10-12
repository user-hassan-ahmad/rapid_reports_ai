# Gate 6 hand read: rcog-ovarian-mass-postmenopausal@2016.1

Read side by side with S1, RCOG Green-top Guideline No. 34 (July 2016, minor update December 2025; 32-page PDF, where
the PDF page equals the printed "n of 31" page). I read every page that carries the pathway: pp 1-8, 10-23. The clinical
algorithm (p6, repeated as Appendix II on p30) was viewed as an image. It is a picture, and its pdftotext layer drops
the "≥" in "RMI I ≥ 200". Both copies of the algorithm are identical.

**RMI check method.** Every golden `rmi` value was computed by a separate snippet written straight from S1 5.1.1, not
by the engine. The snippet counts the features, maps the count to U (0 to 0, 1 to 1, 2-5 to 3) and multiplies
U x 3 x CA125. The engine matches every value. RCOG publishes no calculator and no worked example, so every case is
`origin: "ours"`.

**Pathway structure.** RMI I is a product, and the schema's `score` step is only linear or logistic. The pathway is
therefore built in four steps: a linear `score` that counts the U features, a `band` that turns the count into U, a
linear `score` that gives U as 0/1/3, and a `derive` that multiplies U x 3 x CA125. Gate 2 enumerates `u_band`
separately from the inputs that produce it, so the rules never read `u_band`. They restate "any U feature present"
from the inputs themselves. With no U feature, RMI is 0 whatever the CA125. So the no-feature routes never read
`rmi_band`, and they don't ask for CA125 unless the route itself needs it.

## Checklist

### Inputs
| input | verdict |
|---|---|
| postmenopausal (eligibility, patient) | ✓ p7 §1 and the title: the guideline is for postmenopausal women. S1 defines no age for menopause, so age alone doesn't settle it (For Hassan) |
| malignancy_confirmed (eligibility, lesion) | ✓ p7 §1: "The management of confirmed ovarian malignancy is outside the remit of this guideline" |
| morphology | ✓ p12 §4.4.1: five simple-cyst features; complex = complete septation, solid nodules, papillary projections. The two RMI features (multilocular, solid areas) are crossed into one enum, so the inputs can't contradict each other. Papillary projections count as solid areas (For Hassan) |
| bilateral, ascites, metastases | ✓ p16 §5.1.1: RMI U features. `bilateral` leaves out a contralateral simple cyst ≤3 cm (p7: not clinically significant; For Hassan 12). Whether a small amount of pelvic free fluid counts as ascites is open (For Hassan 14). Patient-scoped so they settle from the whole dictation (a contralateral cyst or ascites is usually not inside the card's own finding) |
| size_cm | ✓ p19 §6.1.1 and the p6 algorithm: "3 cm or less", "> 3 cm and ≤ 5 cm", "> 5 cm". Maximum diameter |
| symptomatic | ✓ p19 §6.1.1 ("If a woman is symptomatic, further surgical evaluation is necessary") and the p6 ANY box. Narrowed after the read (I2): symptoms attributed to the cyst, or the p9 symptoms when persistent or frequent. The scan indication alone is not enough (For Hassan 13) |
| ca125 | ✓ p16 §5.1.1: iu/ml (how_stated accepts U/ml and kU/L, the same unit), "between zero and hundreds or even thousands". Range ≥ 0 |

### Bands
| step | edges | verdict |
|---|---|---|
| u_band | count <1 / 1 to <2 / ≥2 | ✓ p16: U = 0 (score 0), 1 (score 1), 3 (score 2-5). Counts are integers, so the edges are exact |
| rmi_band | <200 / ≥200 | ✓ p6 algorithm image ("RMI I < 200", "RMI I ≥ 200"); text p4, p16, p21 ("greater than or equal to 200"). Figure and text agree |
| size_band | ≤3 / >3 to ≤5 / >5 cm | ✓ p19 §6.1.1 ("3 cm or less", "more than 3 cm but less than or equal to 5 cm"); p6 figure ("> 3 cm and ≤ 5 cm", "> 5 cm"). No rounding instruction in S1 |
| ca125_band | ≤35 normal / >35 raised | ✓ cut-off p10 §4.3.1 ("A routinely used cut-off value of 35 iu/ml"). Which side 35 falls on is not stated (For Hassan) |

### Score and derive steps
| step | verdict |
|---|---|
| feature_count | ✓ p16: 1 point each for multilocular cysts, solid areas, metastases, ascites, bilateral lesions. multilocular_solid scores 2 (multilocular + solid areas) |
| u_score | ✓ p16: U = 0 / 1 / 3 |
| rmi | ✓ p16: RMI = U x M x CA125 with M = 3 for every postmenopausal woman ("all will be allocated the same score of 3") |

### Rules cases (`pathway`)
| case | outcome | verdict |
|---|---|---|
| 0 | does_not_apply | ✓ p7 §1: not postmenopausal, or confirmed ovarian malignancy |
| 1 | no_follow_up | ✓ p19 §6.1.1 and the p4 summary (Dec 2025): "Asymptomatic, simple, unilateral, unilocular ovarian cysts of 3 cm or less ... do not require follow-up"; the p6 box. Ascites and metastases are excluded (library addition, For Hassan). CA125 is not needed |
| 2 | ct_mdt | ✓ p4, p16 §5.1 (grade B): "CT of the abdomen and pelvis ... RMI I score greater than or equal to 200, with onward referral to a gynaecological oncology multidisciplinary team"; the p6 figure. Also fires for ascites or metastases whatever the RMI: p4 and p14 §4.4.3.1 (grade B), CT and MDT when ultrasound findings suggest malignancy; p21 §6.1.2.3 (For Hassan 3) |
| 3 | consider_surgery | ✓ p6 figure. No ascites or metastases; RMI I < 200 (or no U feature); not the ≤3 cm symptomatic simple cyst of case 4; "Cysts with ANY of the following features: symptomatic, non-simple features, > 5 cm, multilocular, bilateral", then "Consider surgery salpingo-oophorectomy (usually bilateral)" |
| 4 | surgical_evaluation | ✓ p19 §6.1.1 (good practice point): "If a woman is symptomatic, further surgical evaluation is necessary". Used for a symptomatic woman with a simple, unilateral cyst ≤3 cm, instead of "consider salpingo-oophorectomy" (For Hassan 13) |
| 5 | conservative | ✓ p19 §6.1.1 (grade D): "> 3 cm but ≤ 5 cm in the presence of normal serum CA125 ... managed conservatively, with a repeat evaluation in 4–6 months"; the p6 ALL box |
| 6 | surgery_raised_ca125 | ✓ p20 §6.1.2: "Women who do not fit the criteria for conservative management should be offered surgical treatment ... as determined by the RMI". This is the text's normal-CA125 condition; the figure omits it (For Hassan) |

Partition: for an eligible woman, ascites or metastases give case 2. Without them, a U feature (complex morphology or
bilateral) puts the ANY box in force, so RMI ≥200 gives case 2 and RMI <200 gives case 3. With no U feature, RMI is 0.
The ANY box gives case 3, except a symptomatic woman with a simple cyst ≤3 cm, who gets case 4. Otherwise the cyst is
simple, unilateral, asymptomatic and ≤5 cm, and goes to case 1 (≤3 cm) or to case 5 or 6 by CA125. Gate 2 confirms
one outcome per combination. The former `does_not_fit` outcome was removed when ascites and metastases moved to
case 2.

### Outcomes
| outcome | verdict |
|---|---|
| no_follow_up | ✓ "do not require follow-up" (text), "do not require routine follow-up" (figure). Caveat 0: p7 §2 ("clinically inconsequential ... at the discretion of the reporting clinician whether or not to describe them") ✓. Caveat 1 labelled as a library addition ✓ |
| ct_mdt | ✓ p16 and p14. Caveat 0 (new) labels the ascites/metastases routing. The other caveats: p6 figure (MDT high likelihood → full staging laparotomy by a gynaecological oncologist; low likelihood → pelvic clearance by a suitably trained gynaecologist) and p22 §6.3 ✓. Caveat 1: p16-17 (threshold 250 used by some centres) ✓. Caveat 2: p17 ("benign conditions may cause elevation of the RMI score and early malignancy may not") ✓ |
| consider_surgery | ✓ p6 figure. The laparoscopic sentence moved out of the recommendation into caveat 0, with S1's own exception (p20 §6.1.2.2 grade B; p14 §4.4.3.1), after the read (I1). Caveat 1: p19 ("Clinicians should discuss the pros and cons of conservative versus surgical management ... RMI I less than 200") ✓. Caveat 2: p15 §4.4.3.2 (MRI second-line when ultrasound is inconclusive, grade B) ✓. Caveat 3: p19 ("repeat imaging often is safer than immediate operative intervention") ✓ |
| surgical_evaluation | ✓ p19 wording ("further surgical evaluation is necessary"). Caveat 0: p7 §2 (≤3 cm simple cysts clinically inconsequential) ✓. Caveat 1: p9 and the I2 reading of symptomatic ✓ |
| conservative | ✓ p19 and p6. "Consider" is kept from the figure ("Consider conservative management"); "can be managed conservatively" in the text. Caveat 0: p6 figure branches (resolve → discharge; persistent unchanged → repeat in another 4-6 months → individualise treatment after discussion with the woman; change in features → consider intervention) ✓. Caveat 1: p19 ✓. Caveat 2: library reading of "normal", labelled ✓ |
| surgery_raised_ca125 | ✓ p20 §6.1.2. Caveat 0: arithmetic from p16 (U = 0 makes RMI 0) and p19's normal-CA125 condition ✓. Caveat 1 (added, M3): p19, discuss the pros and cons of conservative versus surgical management at RMI I <200 ✓. Caveat 2: p10 §4.3.1 (benign causes: PID, fibroids, endometriosis, acute cyst events, peritoneal irritation; "should not be used in isolation") ✓. Caveat 3: the figure-versus-text point (For Hassan) ✓ |
| does_not_apply | ✓ p7 §1 |

### Reference
| field | verdict |
|---|---|
| sum.1-4 | ✓ p6 figure, p16 §5.1, p19 §6.1.1, p6 ANY box with p20. sum.2 keeps S1's hedge ("may manage", p5 and p22, M1); sum.4 says "suitable", not "often" (p5 and p20, M2) |
| def.simple, def.complex | ✓ p12 §4.4.1 (benign in 95-99%) |
| def.rmi, tab.u | ✓ p16 §5.1.1, cell for cell |
| def.ca125 | ✓ p10 §4.3.1 (35 iu/ml; about 20 iu/ml in healthy postmenopausal women; a normal value does not exclude cancer) |
| tab.rmi_risk | ✓ p17: <25 → <3%, 25-250 → ~20%, >250 → ~75% ("based on historical validation data") |
| tab.iota | ✓ p18 Table 1, five rows, cell for cell |
| pitfalls | ✓ scope p7; CT-first p8 §4.1; cross-sectional p14 §4.4.3 and p15; threshold p17; IOTA p17 §5.2 and p18 §5.2.1; Doppler p13 §4.4.2 |

## Gate 5 flags

After the fixes, 57 facts were scored and 50 fell below 0.5 (the first run, before the read, had 55 and 47). I read each one against the source. None needed a correction. They fall
into three groups:

1. **Formula and logic steps** (feature_count 0.03, u_score 0.05, u_band 0.48, rmi 0.30, pathway cases 0, 1, 2, 4
   and 6). Jev scores a rendered model ("1 × morphology is multilocular") against prose. Each one is confirmed on p16
   §5.1.1, p19 §6.1.1, p20 §6.1.2 or p7 §1, as the checklist above shows. Case 4 is the labelled library addition.
2. **Caveats whose fact sits on another page than the outcome's locator**. The window shows only the outcome's page,
   so these score low:
   - ct_mdt caveat 0: p14 and p16 (library routing, labelled). Caveat 1: pp 6 and 22.
   - consider_surgery caveat 0: p20 and p14. Caveat 2: p15. Caveat 3: p19.
   - surgical_evaluation caveats 0 and 1: p7 and p9.
   - surgery_raised_ca125 caveat 1: p19.
   - no_follow_up caveat 0: p7.
   - conservative caveat 0: p6 figure.
   - surgery_raised_ca125 caveat 1: p10.

   Each is confirmed at the page given in the checklist. Library-addition caveats (no_follow_up 1, ct_mdt 0,
   conservative 2, surgery_raised_ca125 0 and 3) say what the library did, not what the source says, so they cannot
   score high.
3. **Paraphrases of text rows and reference fields**, scoring 0.15-0.49:
   - outcomes no_follow_up, ct_mdt, conservative, surgical_evaluation, surgery_raised_ca125 and does_not_apply;
   - size_band and ca125_band;
   - sum.2, sum.3, def.*, tab.*, pit.*.

   Each was re-read against its locator page and holds. The wording is ours by design, and the hedges are kept
   ("consider", "reasonable to discharge", "often safer").

## For Hassan

1. **DECISION: normal CA125 is ≤35 iu/ml.** S1 gives 35 iu/ml as "a routinely used cut-off" (p10). It doesn't say
   which side 35 falls on, and it also mentions 30 and about 20 iu/ml. This decides conservative management versus
   surgery for a simple 3-5 cm cyst.
2. **DECISION: the text's normal-CA125 condition is followed, not the figure.** The algorithm's ALL box (p6) lists
   the conservative criteria without CA125. The text (p4 and p19) requires normal CA125. A simple, unilateral cyst
   has U = 0, so its RMI is 0 whatever the CA125, and the figure alone would send a simple 4 cm cyst with CA125 500
   to conservative management. Here the figure omits a condition rather than drawing an edge differently, so the
   standing "follow the figure" rule was not applied. Such a cyst goes to `surgery_raised_ca125` (p20 §6.1.2:
   "Women who do not fit the criteria for conservative management should be offered surgical treatment").
3. **DECISION (independent read I1, controller ruling): ascites or metastases always go to CT abdomen and pelvis
   with gynaecological oncology MDT referral, whatever the RMI I.** S1 sends suspected malignancy from "the clinical
   picture, ultrasonographic findings and tumour markers" to CT and MDT (p4 and p14, grade B). It also says that
   suspicion from CT findings or clinical assessment requires laparotomy and staging (p21, grade D). So
   `consider_surgery` never offers laparoscopy when these are present, and its laparoscopic sentence is now a caveat
   carrying S1's exception. This replaces the earlier `does_not_fit` route.
4. **DECISION: papillary projections count as "solid areas" for the U score.** S1's RMI lists "solid areas" (p16).
   Its complex-cyst definition lists solid nodules and papillary projections separately (p12).
5. **DECISION: the ≤3 cm no-follow-up route requires an asymptomatic woman.** The text (p4 and p19) and the p1
   update note ("asymptomatic, simple, unilateral, unilocular cysts of 3 cm or less") say so; the 2025 figure note
   doesn't. A symptomatic woman goes to `surgical_evaluation` (For Hassan 13).
6. An incomplete septum makes a cyst `unilocular_non_simple`: not simple, because S1 requires no septations, and not
   multilocular, because multilocular needs complete septation. S1 p12 notes that IOTA counts this as unilocular.
7. IOTA is not encoded. GTG 34 offers it only as "an alternative for those experienced in this technique" (p17), and
   its algorithm is RMI-based. Its Table 1 is a reference table, and the IOTA paper is not cited.
8. The surveillance branch is summarised in the `conservative` caveats rather than modelled as inputs: repeat at
   4-6 months, then resolve, unchanged or changed. There is no prior-scan input.
9. Menopausal status is never inferred from age alone, because S1 gives no age definition.
10. Version `2016.1` carries edition "2016 (minor update December 2025)". The update changed the ≤3 cm rule.
11. `topic` is `ovarian-mass`. The controller should align this with Task 12's pack.
12. **DECISION (independent read I3, controller ruling): `bilateral` leaves out a contralateral simple, unilocular
    cyst ≤3 cm.** S1 doesn't define "bilateral lesions" for the RMI. p7 says these small cysts are not clinically
    significant. Counting them would add a U point (for example, RMI 69 becomes 207) and would take a simple 4 cm cyst
    off conservative management.
13. **DECISION (independent read I2, controller ruling): `symptomatic` means symptoms attributed to the cyst, or the
    p9 symptoms when persistent or frequent. The scan indication alone is not enough.** A symptomatic woman with a
    simple, unilateral cyst ≤3 cm gets S1's own p19 wording, "further surgical evaluation is necessary"
    (`surgical_evaluation`), not "consider salpingo-oophorectomy".
14. **Decided by Hassan 2026-10-13: a small amount of pelvic free fluid is NOT ascites.** Ascites counts only when the dictation says "ascites" or describes more than a small amount of free fluid. This is now in the `ascites` how_stated, and a golden case checks it. The original question was: S1 doesn't say (independent read M5). The
    `ascites` how_stated is left as "ascites is reported". Ascites now routes to CT and MDT, so a library reading that
    excludes small physiological free fluid would change what reaches a report.

## Independent read (clinical-read.md) and fixes

There were no Critical findings. I1-I3 were fixed per the controller's rulings (For Hassan 3, 12 and 13). The
Minor findings were fixed as follows:
- M1 and M2: the sum.2 and sum.4 hedges.
- M3: a surgery_raised_ca125 caveat.
- M4: kU/L in the ca125 how_stated.
- M5: no source support, so it is For Hassan 14.
- M6: new golden cases (a ≤3 cm simple cyst with ascites, metastases alone, and multilocular_solid alone giving
  U 3), plus I1 and I2 cases.
- M7: "after discussion with the woman".
- M8: the p1 citation in For Hassan 5.

Golden cases are now 26, after the ascites ruling case.
