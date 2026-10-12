# Independent clinical read: rcog-ovarian-mass-premenopausal@2011.1

Read-only. I read entry.json, cases.json, review.md and manifest.json side by side with the sources on disk:
- **S1:** GTG 62 (2011). I read the text layer, pp 2-9.
- **S2:** Timmerman 2008. I read the abstract, the methods, Tables 3 and 4, Table 9 with its footnote, and the discussion.

I also checked the sibling pack, rcog-ovarian-mass-postmenopausal, for the 2026-10-13 symptom ruling.

## Verdict

**Not ready.** Every IOTA feature, rule, band edge and outcome matches the sources, and no fact is wrong. There are five Important findings:
- Two are safety and faithfulness points in the extraction rules: M5 when Doppler wasn't done, and M3 with an uncounted number of papillary projections.
- One is the symptomatic route. It should follow Hassan's sibling ruling.
- Two are wording or settling questions to put to Hassan.

There are no Critical findings.

## Findings

### Important

**I1. M5 must not settle false when Doppler was not done (For Hassan 3).** The pack reads an unmentioned feature as absent. That is fine for grey-scale features (M1-M4, B1-B4): each is a visible sign, so Hassan's silence policy ("undictated visible sign = not seen") covers it. It is not fine for colour flow. Without Doppler, flow is not seen at all, and the silence policy says never to apply silence to findings the imaging could not show. S2 used a standard grey-scale and colour Doppler examination for every mass (Methods), so a classification without Doppler is not the validated test.

The two Doppler features fail in different directions:
- **B5 false by default is safe.** It can only remove a B-rule, which moves the result towards no_rule or malignant.
- **M5 false by default is unsafe.** For a mass that is benign through B2, B3 or B4 alone (small solid component, shadowing, smooth multilocular), it can turn IOTA "both" (which leads to gynae-oncology referral) into benign_not_simple ("can be managed within a benign gynaecological service").

For a unilocular cyst (B1), the risk is low. S2's discussion says the very low risk of malignancy in unilocular cysts holds "irrespective of size, wall regularity and vascularization".

Recommendation (Hassan to choose):
- (a) M5 settles unknown when Doppler is not described, except for a simple cyst. B1-only masses stay quiet; B2, B3 and B4 masses ask for Doppler.
- (b) Add a "Doppler not assessed" route. It gives "IOTA simple rules incomplete: colour Doppler needed" and does not give the benign outcome.

Either way, how_stated for m5 must change, and one golden case is needed: a B2 mass with Doppler not described, asserting `needed: [m5_very_strong_flow]` under (a).

A side note on M2. A transvaginal-only scan may not image fluid outside the pouch of Douglas, so reading ascites as absent when it isn't mentioned is weaker on TV-only studies. It matches the sibling ruling, so I accept it, but it belongs in For Hassan 3.

**I2. Collapse the symptomatic route to the sibling pattern (For Hassan 4: disagree).** Hassan's postmenopausal ruling: report text must be true whatever the symptoms; there is one outcome, with "If symptomatic, clinical assessment is advised"; `symptomatic` is never asked. Here, symptomatic is required on every simple-cyst path, and its how_stated demands an explicit statement ("the scan indication alone is not enough"). So nearly every real simple cyst will stall on `needed: symptomatic`. Three outcomes also state "in an asymptomatic premenopausal woman" as fact:
- simple_no_follow_up;
- simple_yearly_us;
- simple_large.

Unlike GTG 34's ≤3 cm rule, GTG 62 §6.1 is explicitly about asymptomatic women (the heading on p7, and the SRU sentence "asymptomatic simple cysts"). The single outcome must therefore keep the condition in its own text, not drop it. Proposed:
- **Remove** the `symptomatic` input and the simple_symptomatic outcome. Route simple cysts by size band only.
- **Under 50 mm:** "Simple ovarian cyst under 50 mm: very likely physiological." Recommendation: "If asymptomatic, generally no follow-up required; such cysts almost always resolve within 3 menstrual cycles. If symptomatic, clinical assessment is advised." p2 §2 supports a symptom-agnostic statement here: simple cysts under 50 mm "usually resolve over 2–3 menstrual cycles without the need for intervention", with no symptom condition.
- **50-70 mm:** "If asymptomatic, yearly ultrasound follow-up. If symptomatic, clinical assessment is advised."
- **Over 70 mm:** "Consider further imaging (MRI) or surgical intervention." This is true either way, so add the clinical-assessment prompt only for consistency.
- **Golden cases:** the two symptomatic cases (40 mm; size not given) need re-pointing.

**I3. M3 when papillary projections are present but not counted.** how_stated says "false when there are none or fewer than four", and FH3 reads anything not described as false. Take "multiple small papillary projections", each under 7 mm. That gives B2 true and M3 false, so the mass is benign_not_simple. If there are four or more, IOTA gives "both", which leads to referral. Recommendation: when papillary projections are described without a count (or "several" / "multiple"), M3 settles unknown and is asked. Add a golden case.

**I4. How do `pregnant_or_acute` and `premenopausal` settle when nothing is said?** Every outcome except does_not_apply needs pregnant_or_acute = false and premenopausal = true. Both how_stated texts need positive evidence, and reports rarely carry either fact, so most real cases will stall at eligibility. This is the same "facts the radiologist rarely knows" problem as I2. Ask Hassan; don't guess. Suggestions:
- **Pregnancy:** on a pelvic ultrasound, an intrauterine pregnancy is a visible sign, so silence can mean not pregnant.
- **Acute presentation:** take it from the scan indication.
- **Menopausal status:** keep For Hassan 6 (age alone does not settle it, as in the sibling), and accept the friction knowingly.

**I5. benign_not_simple wording for likely-functional cysts (For Hassan 9: agree in part).** A haemorrhagic cyst or corpus luteum is unilocular with internal echoes. That gives B1 true and simple false, so it lands on benign_not_simple: "Can be managed within a benign gynaecological service". In report text, this reads as a prompt for a gynaecology referral for a physiological cyst. The source sentence is S1's aim (p2 §1), and its job is to contrast with gynae-oncology referral. Suggestions:
- Word it as "Benign by IOTA simple rules; gynaecological oncology referral is not indicated on ultrasound grounds", or keep S1's phrase but make the contrast explicit.
- Add S1 p5 §4.3.1 as a caveat: "Repeating ultrasound assessment in the postmenstrual phase may be helpful in cases of doubt".

### Minor

**M1. review.md does not match entry.json on two outcomes' caveats.** For iota_both and iota_unclassified, review.md says "Caveat 1 as above", meaning the CT/MRI caveat. In entry.json, caveat 1 of both outcomes is the germ-cell markers caveat; the CT/MRI caveat exists only on refer_gynae_oncology. Correct review.md, or add the caveat if it was intended.

**M2. does_not_apply overstates S1.** It says the guideline covers "not pregnancy, acute presentations". S1 says it "does not specifically address" them. Suggested: "...does not specifically address pregnancy or acute presentations, and excludes ongoing management of known borderline or malignant tumours."

**M3. M4 and B4 judge 100 mm independently of size_mm.** The extractor can set size_mm = 105 alongside b4 = true. Consider deriving the 100 mm test from size_mm, or adding a consistency check. A missing size reads M4 and B4 as false, which falls to no_rule (specialist ultrasound). That is acceptable.

**M4. "Simple cyst" under 30 mm.** A dominant follicle described as a "simple cyst" would produce "Simple ovarian cyst under 50 mm". The p7 definition of a cyst as more than 30 mm is already caveat 2. Optionally, state the outcome as "simple cyst or follicle". This is cosmetic, not a safety issue.

**M5. The IOTA term definitions are not filed.** The pack uses "solid tumour", "multilocular-solid" and "papillary structure". S2 points to its reference 11 (the IOTA terms and definitions paper) for these. For example, a solid tumour in IOTA terms means at least 80% solid tissue. That threshold is from my own knowledge of the IOTA terms paper, not from either source on disk, so it can't be verified here. File the terms paper if Hassan wants how_stated to define these.

**M6. Edition (For Hassan 11).** The RCOG page (checked 2026-10-12) still lists GTG 62 as "the first edition of this guideline; the second edition of this guideline is currently in development". It is not archived, so `current` is correct. Add that note to the edition or a pitfall.

**M7. The `needed` cases for M-features can't be reached in practice.** The case "Simple 30 mm cyst, M-features not stated" is a valid engine test. Under FH3's extraction rule, though, an M-feature is never left unknown. If I1(a) or I3 is adopted, add cases that reflect the real unknowns (Doppler not done; papillary projections not counted).

## Checks that passed

- **Eligibility.** All three inputs match p2 §1. Postmenopausal uses S1's own definition (p6 §5.1).
- **IOTA features.** M1-M5 and B1-B5 match S1 Table 2 (p6) and S2 Table 9 cell for cell. M5 is colour score 4 and B5 is colour score 1 (S2 Table 9). Ascites is fluid outside the pouch of Douglas (S2 Table 3 footnote). The B2 limit is under 7 mm; the M4 and B4 limits are 100 mm or more, and under 100 mm.
- **iota rules.** All four results quote S2's footnote verbatim in meaning, and they form a correct partition.
- **Pathway.**
  - Any M-feature leads to gynae-oncology referral (p7, verbatim).
  - "Not clearly classifiable" leads to specialist ultrasound (p6, good practice point).
  - The simple-cyst rows follow p7 §6.1 (grade C), including "generally", "very likely physiological", "almost always resolve within 3 menstrual cycles" and "should be considered for".
- **Size bands.** The bands are under 50, 50 to 70 inclusive, and over 70. S1 gives explicit wording ("less than 50 mm", "50–70 mm", "more than 70 mm"), with no rounding instruction, so there is correctly no half-up edge. The golden cases test 49.9/50 and 70/70.1.
- **Caveats.** These all match their source pages:
  - LDH, AFP and hCG under 40 (p4, grade C);
  - CT and MRI not routine (p5);
  - CA-125 not needed for a simple cyst, and over 200 leads to discussion (p4);
  - persist or enlarge "may warrant" surgery (p7 §6.2);
  - laparoscopy preferred, and laparotomy for large solid masses (p8);
  - the SRU rationale and the cyst over 30 mm (p7).
- **Reference.** Every field matches its page: sum.1-4, the definitions (RMI U and M scoring), Tables 1 and 2, and the pitfalls (CA-125 50% in early disease; 20% of borderline tumours appear simple; 10% non-ovarian; no single feature).
- **Golden cases.** I traced all 25 by hand, and each reaches the asserted outcome and steps. "Simple unilocular cyst with ascites" gives iota "both" and the referral, which matches S1's literal "any of the M-rules".

## For Hassan items

1. **IOTA as primary. Agree.** GTG 62 §5.2 adopts the rules (grade B), and the combination rule exists only in S2 Table 9.
2. **M- and B-features together: refer and specialist ultrasound. Agree.** This is not only a library routing. S1 p7 reads literally: "an ovarian mass with *any* of the M-rules ultrasound findings should be referred". The p6 good practice point adds specialist ultrasound. The caveat could say that the referral is S1's literal text.
3. **Unmentioned features are false. Agree for grey-scale features; disagree for Doppler.** See I1: M5 must not default false when Doppler wasn't done, at least for B2, B3 and B4 masses. M3 with an uncounted number of projections must be asked (I3).
4. **Symptomatic simple cysts get their own outcome. Disagree.** Adopt the sibling pattern: size-band outcomes that carry "if asymptomatic … ; if symptomatic, clinical assessment is advised", and drop the input (I2).
5. **Eligibility exclusions. Agree,** with the wording fix in M2 and the settling question in I4.
6. **Age alone doesn't settle premenopausal. Agree.** This is consistent with the sibling. Note the friction (I4).
7. **Size edges. Agree.** The source wording is explicit and has no rounding instruction.
8. **CA-125 and germ cell markers as caveats only. Agree.**
9. **benign_not_simple wording. Agree in part.** Rephrase it, or make the contrast with gynae-oncology referral explicit, and add the postmenstrual-repeat caveat (I5).
10. **RMI not encoded. Agree.** S1 gives no premenopausal action threshold.
11. **Edition. Agree with `current`.** RCOG says the second edition is in development (M6).
