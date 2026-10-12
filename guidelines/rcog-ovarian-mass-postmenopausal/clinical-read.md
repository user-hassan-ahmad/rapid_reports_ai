# Independent clinical read: rcog-ovarian-mass-postmenopausal@2016.1

Reviewer: independent agent, read-only (skill step 8). Source: S1, RCOG Green-top Guideline No. 34 (July 2016,
minor update December 2025), text layer plus the p6 clinical algorithm viewed as an image.
Pages read: 1-22. Files read: entry.json, cases.json, review.md, manifest.json.

## Verdict

**Not ready to ship.** There are no Critical findings and 3 Important findings. The RMI I arithmetic, the
thresholds, the size and CA125 bands, the follow-up intervals and the scope all match S1. The Important findings are
about routing and how inputs are stated. In each one, a recommendation that reaches the report goes past what S1
says. All three are judgement calls that review.md leaves out.

## What I checked and found correct

- **RMI I** (p16 §5.1.1; p6 box). 1 point each for multilocular cysts, solid areas, metastases, ascites and bilateral
  lesions. U = 0 / 1 / 3 for scores 0 / 1 / 2-5, and M = 3 for all postmenopausal women. RMI = U x 3 x CA125 (iu/ml).
  The `feature_count` coefficients are correct; `multilocular_solid` = 2 is right, since it carries two RMI features.
  The `u_band` edges are correct under the engine's defaults (min inclusive, max exclusive), and so is the
  `u_score` mapping.
- **Threshold 200.** The figure image shows "RMI I ≥ 200" (an underlined >), and the text on p4, p16 and p21 says
  "greater than or equal to 200". `lt200` / `ge200` with 200 inclusive above is correct. The 250 alternative is
  correctly a caveat or pitfall only (p16-17).
- **Size bands** ≤3 / >3 to ≤5 / >5 cm: correct (p19, p6). S1 gives no rounding instruction.
- **CA125 35 iu/ml** cut-off (p10): correct. ≤35 counts as normal (see For Hassan 1).
- **Follow-up.** Repeat CA125 and TVS ± TAS at 4-6 months. Discharge is reasonable after 1 year if the cyst is
  unchanged or smaller with normal CA125, considering the woman's wishes and surgical fitness (p19, p6). The figure's
  branches are correct.
- **Eligibility** (p7 §1): postmenopausal, and not confirmed ovarian malignancy. These are S1's own scope text, and
  no criteria are invented.
- **Rules partition**: I traced it by hand and it agrees with review.md. Each eligible combination reaches exactly one
  case.
- **Outcomes** ct_mdt, conservative, no_follow_up, does_not_fit and does_not_apply are faithful, and their hedges
  ("consider", "reasonable", "often safer") are kept.
- **Reference**: def.*, tab.u, tab.rmi_risk (p17), tab.iota (p18 Table 1), pit.ct_first (p8), pit.cross_sectional,
  pit.doppler, pit.iota (p18: "should be referred to a gynaecological oncology service") and pit.threshold all
  match S1.
- **Golden cases**: I recomputed every RMI independently: 0, 199.8, 200.1, 200, 900, 180, 60, 240 and 90. All are
  correct. Every outcome is reached. The size edges (3.0/3.1, 5.0/5.1), the CA125 edge (35/35.1), the RMI edge
  (199.8/200/200.1) and the U edges (counts 0/1/2) are tested on both sides. There are two `needed` cases.

## Findings

### Important

**I1. `consider_surgery` says laparoscopy is suitable even when imaging or markers suggest malignancy.** The
recommendation reads "laparoscopic management is suitable at RMI I under 200". It fires for every RMI <200 route,
including these:
- metastases = true with a complex cyst and low CA125. For example, solid areas plus metastases with CA125 20 gives
  U 3 and RMI 180;
- ascites with solid areas (the golden case "solid areas and ascites, CA125 20");
- a U = 0 non-simple or >5 cm cyst with a very high CA125. Here RMI is 0 whatever the CA125.

S1 p21 §6.1.2.3 (grade D, also p5) says: "All ovarian cysts that are suspicious of malignancy … as indicated by a RMI
I ≥ 200, **CT findings, clinical assessment** or findings at laparoscopy, require a full laparotomy and staging
procedure." S1 p4 and p14 §4.4.3.1 (grade B) say: if malignancy is suspected "from the clinical picture,
ultrasonographic findings and tumour markers", arrange CT abdomen and pelvis and refer to the gynaecological oncology
MDT. So for a woman with imaged metastases, the pack recommends laparoscopy against S1's own laparotomy and MDT text.
Caveat 2 of consider_surgery doesn't undo a positive "laparoscopic is suitable" in the recommendation line.

The pack is also inconsistent with For Hassan 3. There, ascites or metastases close the simple routes, but they
don't close the laparoscopic line on the complex routes.

Suggested fix (DECISION for Hassan):
- route metastases = true at RMI I <200 to an explicit outcome, along the lines of "RMI I under 200, but imaging
  shows metastatic disease: S1 advises CT and gynaecological oncology MDT referral when malignancy is suspected";
- in all cases, move the laparoscopic sentence out of the recommendation and into a caveat that says "when nothing
  else suggests malignancy".

**I2. "Symptomatic" is stated too broadly, and a symptomatic woman with a ≤3 cm simple cyst gets "consider
salpingo-oophorectomy".** The `symptomatic` how_stated counts any "pelvic or abdominal pain, persistent distension or
bloating, early satiety, urinary urgency or frequency". In radiology, the scan's indication is very often "abdominal
pain", so this input will often settle true. The ANY box then sends even a 2 cm simple cyst to "Consider surgery:
salpingo-oophorectomy". Three things in S1 point the other way:
- p7 §2 (Dec 2025): simple unilocular lesions ≤3 cm are "clinically inconsequential", and cystic lesions "should only
  be reported as ovarian cysts, and considered significant, if they are more than 3 cm";
- p19 says symptoms trigger "further surgical **evaluation**" (a good practice point), not surgery;
- p9 gives weight to the ovarian-cancer symptoms only when they are "experienced persistently or on a frequent
  basis".

Suggested fixes:
- tighten how_stated to "symptoms attributed to the cyst or adnexa, or persistent or frequent symptoms of the p9
  type; the scan indication alone is not enough";
- make the ≤3 cm simple + symptomatic route a For Hassan DECISION. One option is a caveat on consider_surgery for
  ≤3 cm simple cysts quoting p7 and p19 ("surgical evaluation").

I agree that no_follow_up needs an asymptomatic woman (For Hassan 5). The problem is where the symptomatic case lands.

**I3. `bilateral` counts any contralateral cyst, including the ≤3 cm simple lesions that S1 says are not
significant.** The how_stated sets "true when both ovaries have a cyst or mass". S1 doesn't define "bilateral
lesions" for the RMI. But p7 says ≤3 cm simple lesions should not be considered significant ovarian cysts. As
written, a contralateral 1.5 cm simple cyst:
- takes a 4 cm simple cyst with normal CA125 off conservative management and onto consider_surgery, via the bilateral
  criterion in the ANY box;
- adds a U point, which can cross the threshold. For example, a 4 cm multilocular cyst with a contralateral 2 cm
  simple cyst and CA125 23 gives U 3, RMI 207, and CT/MDT. Without the small cyst it would be RMI 69.

This is a judgement call that changes what reaches the report, and it is missing from For Hassan. Suggested reading:
a contralateral lesion counts as bilateral unless it is a simple unilocular cyst ≤3 cm. Label this a library
addition.

### Minor

- **M1.** sum.2 says "Under 200: low risk, managed by a general gynaecologist". S1 hedges this: "might manage"
  (p5, p22 §6.3) and "may be managed" (p22 §6.2). Restore the hedge.
- **M2.** sum.4 says "often laparoscopic". S1 says "suitable for laparoscopic management" (p5, p20); "often" is not
  in S1.
- **M3.** surgery_raised_ca125 has no caveat for p19: "Clinicians should discuss the pros and cons of conservative
  versus surgical management in women at low risk of malignancy (RMI I less than 200)". This woman's RMI is 0. The
  caveat fits here more than anywhere else in the pack.
- **M4.** The ca125 how_stated should also accept kU/L, which is how most UK laboratories report CA125.
- **M5.** The ascites how_stated doesn't say whether a small amount of pelvic free fluid counts. That fluid is common
  and is not ascites. S1 is silent, so state the library reading and list it in For Hassan.
- **M6.** Golden-case gaps (none is an error):
  - no does_not_fit case from the ≤3 cm band;
  - no metastases-only does_not_fit case;
  - no case where a single input (multilocular_solid alone) gives a count of 2 and U = 3.
- **M7.** conservative caveat 0, "then individualise", drops the figure's "after discussion with the woman".
- **M8.** review.md could cite the p1 update note, which itself says "**asymptomatic**, simple, unilateral,
  unilocular cysts of 3 cm or less". That strengthens For Hassan 5.

## Verdicts on For Hassan

1. **Normal CA125 is ≤35 iu/ml. Agree.** 35 iu/ml is the upper reference limit (99th centile, p10), so 35 itself is
   normal by convention. 30 and 20 iu/ml appear only as evidence context, not as recommendations.
2. **Follow the text's normal-CA125 condition, not the figure. Agree.** The p4 and p19 recommendation (grade D) is
   explicit. The figure measures CA125 upstream and repeats it at follow-up, so it omits the condition rather than
   contradicting it. p20 §6.1.2 then gives "offer surgical treatment" for women who don't meet the criteria. See M3
   for the missing discuss-pros-and-cons caveat.
3. **Ascites or metastases close the simple-cyst routes. Agree.** At RMI <200 an explicit does_not_fit is better than
   forcing a route. Apply the same reasoning to the complex routes (I1).
4. **Papillary projections count as solid areas. Agree.** In Jacobs' RMI, "solid areas" covers solid tissue in the
   cyst, papillary projections included. S1 p12 groups them as "lesions with solid elements".
5. **The ≤3 cm no-follow-up route needs an asymptomatic woman. Agree.** The p1 update note says "asymptomatic"
   too. Where the symptomatic case goes instead is the open issue (I2).
6. **An incomplete septum makes a cyst unilocular_non_simple. Agree.** S1's simple definition needs "absence of
   septations" (p12), and "multilocular" means complete septation.
7. **IOTA is not encoded. Agree.** S1 adopts the RMI pathway and offers IOTA only "for those experienced in this
   technique" (p17).
8. **Surveillance branches are summarised in caveats. Agree.** They are faithful to the p6 figure.
9. **Menopausal status is not inferred from age. Agree.** S1 gives no definition. Expect more "postmenopausal?"
   questions on sparse dictations.
10. **Version 2016.1 with the Dec 2025 edition label. Agree.** The p1 note lists exactly the p4, p6/p30 and p7
    changes to the ≤3 cm rule.
11. **topic alignment.** This has no clinical bearing. Agree to align it.
