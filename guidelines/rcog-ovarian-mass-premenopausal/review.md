# Hand read: rcog-ovarian-mass-premenopausal@2011.1

Read side by side with the sources, then revised after the independent read (`clinical-read.md`: 5 Important and 7 Minor findings, all fixed per the controller rulings recorded in For Hassan).

- **S1** is RCOG/BSGE Green-top Guideline No. 62 (November 2011, first edition). It is a 14-page PDF, and the PDF page equals the printed "n of 14" page. I read every page. Its tables are text: Table 1 is on p3 and Table 2 on p6.
- **S2** is Timmerman et al. 2008, *Ultrasound Obstet Gynecol* 31:681-690, the IOTA simple rules paper. It is a Firecrawl text capture with no pages, so it is cited by section and table. I read the abstract, the methods, the results around Tables 3, 4 and 9, and the discussion. Table 9 and its footnote came through complete.

**Why S2 is primary.** GTG 62 §5.2 (p6, grade B) adopts the IOTA simple rules. It reproduces them as Table 2 and attaches management to them:
- p7: any M-rule finding → gynaecological oncology;
- p6 good practice point: not clearly classifiable → specialist gynaecological ultrasound.

The combination rule, the colour scores and the ascites definition exist only in S2 (GTG ref 26). This makes S2 a formally adopted model, as Brock is for BTS.

**Worked examples.** Neither source has one, so all cases are `origin: "ours"`. No formula is involved.

## Checklist

### Inputs
| input | verdict |
|---|---|
| premenopausal (eligibility, patient) | ✓ p2 §1. The false side uses S1's postmenopausal definition (p6 §5.1). It settles true only from a stated LMP, cycle day or menstrual status; otherwise it is asked (I4, provisional) |
| pregnant_or_acute (eligibility, patient) | ✓ p2 §1 ("does not specifically address the acute presentation ... or ... pregnant women"). The acute examples come from p4 §4.1. Pregnancy may settle false when a pelvic ultrasound describes the uterus with no pregnancy; acute presentation settles only from the stated indication (I4, provisional) |
| known_malignancy_or_borderline (eligibility, lesion) | ✓ p2 §1 |
| m1, m2, m3 | ✓ S1 p6 Table 2 and S2 Table 9. Ascites = fluid outside the pouch of Douglas (S2 Table 3 footnote). Grey-scale features that are not mentioned settle absent. M3 is unknown when papillary projections are described without a count (I3) |
| m4_irregular_multilocular_solid, b4_smooth_multilocular | ✓ Table 2. The 100 mm test (M4 ≥100 mm, B4 <100 mm) is now read from size_mm through size_band (M3), so the two can't contradict each other |
| m5, b5 | ✓ S2 Table 9: M5 = colour score 4, B5 = colour score 1. When Doppler is not described both are unknown, except that M5 settles false for a simple cyst (S2 Discussion: the very low risk in unilocular cysts holds "irrespective of size, wall regularity and vascularization"; def.unilocular_risk) (I1) |
| b1, b2, b3 | ✓ Table 2 / Table 9 |
| simple_cyst | ✓ p2 §2 ("thin-walled cysts without internal structures"). Gated on b1 = true |
| size_mm | ✓ p7 §6.1 (<50; 50–70; larger, i.e. more than 70) and p6 Table 2 (<100 / ≥100 mm). Maximum diameter of the mass. Not gated (see Skill friction) |
| ~~symptomatic~~ | Removed (I2) |

### Bands
| step | edges | verdict |
|---|---|---|
| size_band | <50 / 50 to ≤70 / >70 to <100 / ≥100 mm | ✓ p7 §6.1 ("less than 50", "50–70", "more than 70"); p6 Table 2 ("<100 mm", "≥100 mm"). No gaps and no rounding instruction. Tested at 49.9/50, 70/70.1 and 99.9/100 (for both B4 and M4) |

### Rules: `iota`
| case | result | verdict |
|---|---|---|
| 0 | malignant | ✓ S2 Table 9 footnote: one or more M-rules in the absence of a B-rule |
| 1 | benign | ✓ one or more B-rules in the absence of an M-rule |
| 2 | both | ✓ both apply → cannot be classified |
| 3 | no_rule | ✓ no rule applies → cannot be classified |

M4 = irregular multilocular-solid AND size_band ≥100. B4 = smooth multilocular AND size_band <100. The partition is unchanged (any-M × any-B over the same expressions), and Gate 2 confirms it.

### Rules: `pathway`
| case | outcome | verdict |
|---|---|---|
| 0 | does_not_apply | ✓ p2 §1 |
| 1 | refer_gynae_oncology | ✓ p7 ("any of the M-rules ... should be referred to a gynaecological oncological service") |
| 2 | iota_both | ✓ p7 literal any-M referral plus the p6 good practice point; the caveat now says the referral is S1's literal text |
| 3 | iota_unclassified | ✓ p6 good practice point |
| 4 | simple_lt50 | ✓ p7 §6.1 (grade C), routed by size only (I2) |
| 5 | simple_50_70 | ✓ p7 §6.1 (grade C) |
| 6 | simple_gt70 | ✓ p7 §6.1 (grade C); bands gt70_lt100 and ge100 |
| 7 | benign_not_simple | ✓ p2 §1 with §6 pp7-9; reworded (I5) |

### Outcomes
| outcome | verdict |
|---|---|
| refer_gynae_oncology | ✓ p7. Caveat 0: germ cell markers under 40 (p4 §4.2, grade C) ✓. Caveat 1: CT and MRI not routine but have a place for complex lesions (p5 §4.3.2) ✓ |
| iota_both | ✓ Caveat 0: the routing, now stating that the any-M referral is S1's literal text ✓. Caveat 1: germ cell markers (p4) ✓ |
| iota_unclassified | ✓ p6. Caveat 0: onward gynae-oncology MDT referral if malignancy is a possibility (p5 §4.3.2) ✓. Caveat 1: germ cell markers (p4) ✓ (M1: this outcome has no CT/MRI caveat; the review now matches the entry) |
| simple_lt50 | ✓ p7 "generally do not require follow-up", "very likely physiological", "almost always resolve within 3 menstrual cycles". It now reads "If asymptomatic, …; if symptomatic, clinical assessment is advised". Caveat 0 labels the library wording ✓. Caveat 1: CA-125 not needed (p4) ✓. Caveat 2: persist or enlarge "may warrant surgical management" (p7 §6.2) ✓. Caveat 3: the >30 mm cyst definition (p7), so a smaller simple structure may not count as a cyst (M4) ✓ |
| simple_50_70 | ✓ p7 "yearly ultrasound follow-up", same pattern. Caveats: the library-wording label, CA-125 (p4), persistence (p7) ✓ |
| simple_gt70 | ✓ p7 "should be considered for ... MRI or surgical intervention", same pattern. Caveats: the library-wording label, the SRU rationale (p7), laparoscopy preferred and size controversial (p8 §6.4) ✓ |
| benign_not_simple | Reworded (I5): "Gynaecological oncology referral is not indicated on ultrasound grounds; any management needed sits within benign gynaecological care", which is S1's benign-service versus oncology contrast (p2 §1). Caveat 0: §6.2 persistence and dermoid growth ✓. Caveat 1: germ cell markers ✓. Caveat 2: CA-125 >200 → discussion with a gynaecological oncologist, with benign causes and "interpreted cautiously" (p4) ✓. Caveat 3: laparoscopy, and laparotomy for large solid masses (p8) ✓. Caveat 4 (new): repeat the scan after menstruation in cases of doubt (p5 §4.3.1) ✓ |
| does_not_apply | ✓ p2 §1, now "does not specifically address pregnancy or acute presentations, and excludes ongoing management of known borderline or malignant ovarian tumours" (M2) |

### Reference
| field | verdict |
|---|---|
| sum.1-4 | ✓ p4-5 §4.3; p5 §5; p6-7 §5.2; p7 §6.1 (sum.4 keeps "asymptomatic") |
| def.simple, def.cyst, def.postmenopausal, def.rmi | ✓ p2 §2; p7; p6 §5.1 |
| def.iota_classes, def.iota_flow, def.iota_ascites | ✓ S2 Table 9 and footnote; S2 Table 3 footnote |
| def.unilocular_risk (new) | ✓ S2 Discussion ("very low risk of malignancy associated with unilocular adnexal cysts ... irrespective of size, wall regularity and vascularization") |
| tab.iota | ✓ S1 p6 Table 2, cell for cell |
| tab.adnexal | ✓ S1 p3 Table 1, cell for cell |
| pitfalls | ✓ p2 §1; p4 §4.2; p3 §2; p2 §2 and Table 1; pp5-6 §5.1; p5 §4.3.1 |

### Golden cases
There are 26 cases, and every one of the 8 outcomes and 4 `iota` results is reached. The edges at 50, 70 and 100 mm (B4 and M4) are tested on both sides. Five cases assert `needed`, and these are the real unknowns (M7):
- size for a simple cyst;
- M5 for a B2 mass with Doppler not described (B5 can't change the result there, so only M5 is asked);
- M3 for uncounted papillary projections;
- size for a smooth multilocular cyst;
- premenopausal not stated.

The old "M-features not stated" case was dropped, because under the extraction rule it can't happen.

## Gate 5 flags (36 of 62 below 0.5)

No flag found a fact error.

- **The fact comes from another page than the locator's.** Gate 5 reads only the page in the outcome's locator, so these flag by construction. I checked each against the page named in its locator text.
  - Caveats: refer_gynae_oncology 0-1 (p4, p5); iota_both 1 (p4); simple_lt50 1, simple_50_70 1 and simple_50_70 2 (p4, p7 §6.2); simple_gt70 caveat 2 (p8); benign_not_simple 1-4 (p4, p8, p5); iota_unclassified 1 (p4).
  - size_band (0.06): the 100 mm edges are on p6 (Table 2), while the locator page is p7.
- **S2 has no pages.** iota.case0-3, def.iota_classes, def.iota_flow, def.iota_ascites and def.unilocular_risk score 0.03-0.11. Each was confirmed against the capture: the Table 9 footnote, the Table 3 footnote and the Discussion.
- **Library wording, labelled.** These are:
  - the "If asymptomatic … if symptomatic …" outcomes (simple_lt50, simple_50_70, simple_gt70) and their caveat 0;
  - iota_both and its caveat 0;
  - benign_not_simple's reworded recommendation.
- **Rule strings diluted by the eligibility conditions.** pathway.case1-7 each match their quoted S1 sentence in the rules table above.

## For Hassan

1. **IOTA as primary.** GTG 62 §5.2 (grade B) adopts the rules (Table 2) and attaches management to them. The combination rule, the colour scores and the ascites definition come from Timmerman 2008 (GTG ref 26), filed as S2 `primary` from a Firecrawl text capture. The reader agreed.
2. **DECISION: M- and B-features together.** The pack refers to gynaecological oncology (S1 p7 literally says any M-rule) and also advises specialist ultrasound (p6, not clearly classifiable). The reader agreed.
3. **DECISION (controller ruling, I1, I3): unmentioned features.**
   - Grey-scale features that are not mentioned settle absent, including ascites. The reader noted this is weaker on transvaginal-only scans.
   - When Doppler is not described, M5 and B5 are unknown and are asked, except that M5 settles false for a simple cyst (S2 Discussion on unilocular cysts).
   - Papillary projections described without a count leave M3 unknown, so it is asked.
4. **DECISION (controller ruling, I2, following Hassan's postmenopausal ruling): symptoms are not asked.** The `symptomatic` input and the simple_symptomatic outcome are gone. Each size band reads "If asymptomatic, <§6.1 action>; if symptomatic, clinical assessment is advised". "Asymptomatic" stays because §6.1 covers asymptomatic women only.
5. **DECISION: eligibility.** "Does not specifically address" pregnancy or acute presentation is treated as does_not_apply. These two are one chip; known malignancy or borderline tumour is a second. The outcome text now uses S1's own phrase (M2).
6. **DECISION, provisional, for Hassan to confirm (controller ruling, I4): how eligibility settles.**
   - "Not pregnant" may settle when a pelvic ultrasound describes the uterus without a pregnancy.
   - "Acute presentation" settles only from the stated indication.
   - "Premenopausal" stays a question unless an LMP, a cycle day or menstrual status is stated; age alone does not settle it.
7. **Size edges.** <50 / 50-70 / >70 mm, with 50 and 70 in the middle band. The IOTA 100 mm test is now taken from size_mm (<100 for B4, ≥100 for M4; M3 fix). No rounding is needed.
8. **CA-125 and germ cell markers are caveats, not logic.** S1 says CA-125 is not needed for simple cysts. The reader agreed.
9. **DECISION (controller ruling, I5): benign_not_simple.** The recommendation now reads "Gynaecological oncology referral is not indicated on ultrasound grounds; any management needed sits within benign gynaecological care". This is a contrast with oncology referral, not a prompt to refer to gynaecology. The p5 repeat-after-menstruation caveat was added.
10. **RMI is not encoded.** S1 sets no premenopausal action threshold. The reader agreed.
11. **Edition.** This is the 2011 first edition. RCOG's page (checked 2026-10-12, per the reader) lists a second edition as in development and does not archive this one, so the status stays `current`. The note is in `edition` (M6).
12. **The IOTA terms paper is not filed (M5).** This is Timmerman 2000, GTG ref 51 and S2 ref 11. The pack's how_stated uses only the rule wording, so it isn't needed now. File it only if Hassan wants how_stated to carry the IOTA definitions (e.g. what makes a tumour "solid").

## Skill friction
- **Band overrides and prerequisites.** Gate 2 enumerates band ids unconditionally, whatever the prerequisites of the number behind them. A band over a gated number therefore forces rules for impossible combinations, so size_mm is ungated. TRAPS.md doesn't mention this.
- **One locator per outcome.** Gate 5 reads only that page, so caveats from other pages always flag and lose their own locator. Per-caveat locators would fix both.
- **Page-less sources.** Gate 5 scores near-verbatim paraphrases from a source with no pages at about 0.05.
