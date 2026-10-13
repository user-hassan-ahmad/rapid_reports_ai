# Hand read: ese-adrenal-incidentaloma@2023.1

Read side by side with S1: Fassnacht M et al., *European Society of Endocrinology clinical practice guidelines on the
management of adrenal incidentalomas, in collaboration with ENSAT*, Eur J Endocrinol 2023;189(1):G1-G42
(doi 10.1093/ejendo/lvad066, open access, CC BY). It is a 42-page PDF, and the PDF page equals the journal page
(G17 is PDF page 17). I read pp 1-5 (abstract, summary of recommendations, definition), 8-9 (imaging overview),
16-20 (section 5.2, risk of malignancy), 24 (R.3.9, R.4.2), 26-27 (follow-up, bilateral), and 30-32 (young and
elderly patients, extra-adrenal malignancy). Figures 4, 5 and 9 (pp 17, 18, 31) are pictures and were viewed as
images; their text layer is jumbled. Table 4 (p19) reads cleanly as text.

**Pack type.** Tier 1 algorithm: Figure 5 turns unenhanced CT findings into the next imaging or management step.
The biochemical work-up that ESE asks for in every incidentaloma (R.3.1-3.10) is a caveat on each outcome, not an
input, as the task brief directs. Washout is not an input: ESE now uses it only as one of the "additional imaging"
options (Table 4, Figure 5 note 1), not in the primary decision.

**No worked examples.** S1 gives no numeric worked cases (Figure 8 shows bilateral image examples, outside this
pathway). Every golden case is `origin: "ours"`. There is no formula to cross-check.

## Checklist

### Inputs
| input | verdict |
|---|---|
| known_primary_cancer (eligibility, patient, fact) | ✓ p4 §2.1: masses found at staging or follow-up of extra-adrenal malignancy "do not meet the strict definition"; Figure 4 note 1 (p17) and §5.6.3 (p30) give them a separate pathway (Figure 9). See For Hassan 4 |
| not_incidentaloma (eligibility, patient) | ✓ p4 §2.1: an incidentaloma is found on imaging "not performed for a suspected adrenal disease"; masses found on screening in a hereditary syndrome fall "outside the definition". Two clauses in one input (For Hassan 5) |
| size_cm (lesion, cm, max) | ✓ Figure 5 (p18) and R.2.4-2.6 use "tumor size"; p4 §2.1 the 1 cm work-up threshold. S1 never says how size is measured; maximum diameter is used (For Hassan 9) |
| appearance (lesion enum) | ✓ homogeneous / heterogeneous: Figure 5 boxes; definition Table 4 note a p19 ("uniform density or signal intensity throughout"). clearly_benign: Table 4 note a ("masses that have other clear characteristics consistent with benign disease, eg, myelolipoma") with R.5.1 p26. Library option (For Hassan 6) |
| unenhanced_hu (lesion, HU, state not_assessable) | ✓ R.2.2-2.3 p17, Figure 5. not_assessable is the source's own situation: R.2.2 recommends noncontrast CT "if not yet performed". No prerequisite: a first version gated it on homogeneous, but gate 2 then enumerated an impossible homogeneous + not_applicable row. Unprerequisited, the engine still never asks it for a heterogeneous or clearly benign mass, because it cannot change those outcomes |
| age (patient, fact age_years) | ✓ p30 R.6.2.1 and R.6.2.3: "individuals <40 years of age", "adults <40 years" |

### Bands
| step | edges | verdict |
|---|---|---|
| size_band | <1 / 1 to <4 / ≥4 cm | ✓ p4: work-up "only in adrenal masses ≥ 1 cm". Figure 5: "tumor < 4cm", "≥ 4cm" (HU 11-20 column), "> 4cm" (fourth column); R.2.5 text "≥ 4 cm"; R.2.6 "< 4 cm". The text is followed at exactly 4.0 cm (For Hassan 1). No rounding instruction for size |
| hu_band | ≤10 / >10 to ≤20 / >20 HU | ✓ R.2.3 and Table 4 "≤ 10"; Figure 4, note 3 and the R.2.4 reasoning "HU > 10"; R.2.4 "between 11 and 20"; R.2.5-2.6 "> 20". No rounding instruction in S1, so edges sit exactly at 10 and 20 (fixed after the clinical read, C1; For Hassan 2) |
| age_band | <40 / ≥40 | ✓ p30 R.6.2.1 "<40 years". 40 itself is not under 40 |

### Rules cases (`pathway`)
| case | outcome | verdict |
|---|---|---|
| 0 | does_not_apply | ✓ p4 §2.1 (either exclusion true) |
| 1 | below_threshold | ✓ p4 §2.1: "reasonable to perform additional diagnostic work-up only in adrenal masses ≥ 1 cm, unless clinical signs and symptoms suggestive of adrenal hormone excess are present". Applied whatever the appearance (For Hassan 3) |
| 2 | benign_attenuation | ✓ Figure 5 box 1 "Any size and homogenous and HU ≤ 10" → "No further imaging required"; R.2.3 p17 (strong, ⊕⊕⊕○) |
| 3 | benign_other | ✓ R.5.1 p26: no further imaging for "an adrenal lesion with clear benign features on imaging studies"; Table 4 note a |
| 4 | needs_unenhanced_ct | ✓ R.2.2 p17: noncontrast CT "as the first imaging modality if not yet performed" |
| 5 | young_indeterminate | ✓ R.6.2.1 (urgent assessment under 40) and R.6.2.3 (surgical resection if indeterminate on imaging), p30. Fires for Figure 5 columns 2 and 3 in a patient under 40; column 4 stays high_risk (For Hassan 7) |
| 6 | additional_imaging | ✓ Figure 5 box 2 "Homogenous and HU 11-20 and tumor < 4cm" → "Additional imaging (or interval imaging in 12 months)"; R.2.4 p19 |
| 7 | indeterminate_mdt | ✓ Figure 5 box 3 (HU 11-20 and ≥4 cm; HU > 20 and < 4 cm; heterogeneous < 4 cm) → "Discuss in MDT meeting and consider proceeding swiftly to additional imaging (or immediate surgery)", follow-up "Interval imaging in 6-12 months"; R.2.6 p19 |
| 8 | high_risk | ✓ R.2.5 p19 ("≥ 4 cm and heterogeneous or has unenhanced HU > 20"); Figure 5 box 4 → "Discuss in MDT meeting and consider proceeding swiftly to surgery" (or further imaging, esp. FDG-PET/CT), follow-up if no surgery 6-12 months |

Partition: an exclusion gives case 0. Otherwise under 1 cm gives case 1. From 1 cm up, a clearly benign mass gives
case 3. A homogeneous mass gives case 2 at ≤10 HU and case 4 with no unenhanced CT. The remaining masses fall into
Figure 5's columns 2-4: column 4 (≥4 cm with >20 HU or heterogeneous) is case 8 at any age. Columns 2 and 3 are
case 5 under 40, and case 6 or 7 from 40. Gate 2 confirms exactly one outcome per combination.

### Outcomes
| outcome | verdict |
|---|---|
| below_threshold | ✓ p4. Caveat 0: "arbitrary work-up threshold of 1 cm" ✓. Caveat 1 labels the routing as the library's reading ✓ |
| benign_attenuation | ✓ R.2.3, Figure 5; "whatever its size": R.2.3 reasoning p18 (4 cm cut-off removed) and the abstract. Caveat 0: R.3.1-3.2 (DST), R.3.10 (ARR with hypertension or unexplained hypokalaemia) ✓. Caveat 1: Figure 4 note 3 (metanephrines "only necessary in adrenal tumors with HU > 10") and R.3.9 p24 ✓. Caveat 2: R.4.2 p24 ✓. Caveat 3: §5.6.2 reasoning p30 ("we would consider 1 follow-up imaging after 12 months also for a presumably benign adrenal mass in very young patients"), hedge kept ✓. Caveat 4 (added after the read, M2): R.6.2.1 urgent assessment under 40 or in pregnancy; the same caveat was added to benign_other and needs_unenhanced_ct ✓ |
| benign_other | ✓ R.5.1; Figure 4 p17 ("Non-functioning, benign lesion (e.g. adenoma, (myelo-)lipoma) → No further investigation"). Caveat 0: Table 4 note a and Figure 4; the firm-diagnosis condition is labelled as a library addition (M3) ✓. Caveat 1: R.3.1-3.2 ✓. Caveat 2: R.4.2 reasoning p24 ("considering surgery for alleviation of symptoms of mass effect (eg, large myelolipoma with progressively increasing size)", after MDT) ✓ |
| needs_unenhanced_ct | ✓ R.2.2, "homogeneous and lipid-rich and therefore benign". Caveat 0: §2.3 p8 ("Standard contrast-enhanced CT is usually not helpful") ✓. Caveat 1: R.6.2.2 p30, and R.2.3 reasoning p18 (CSI MRI first choice only where CT is less desirable; unambiguous CSI may be judged sufficient by an expert MDT) ✓. Caveat 2: R.3.2 ✓ |
| additional_imaging | ✓ R.2.4 ("we suggest an immediate additional imaging ... Alternatively, interval imaging in 12 months by noncontrast CT (or MRI)"). Tests from Figure 5 note 1. "Low likelihood": R.2.4 reasoning (>90% benign) and Table 4 note c. Caveat 0: R.2.4's own condition, and metanephrines per R.3.9 / Figure 4 note 3 ✓. Caveat 1: reasoning p19 ("If these imaging results are suggestive of a benign lesion, no further imaging is required") and note 1 ✓. Caveat 2: R.1.1 p16 ✓. Caveat 3: R.6.2.1-6.2.3 ✓ |
| indeterminate_mdt | ✓ R.2.6 and Figure 5 box 3. The interval-imaging clause now says "ESE recommends" (R.2.6), after the read (M1); R.5.2 says "suggest" (For Hassan 11). Caveat 0: reasoning p19 ("risk of malignancy in this subgroup still rather small, but higher as in tumors < 4 cm and HU 10-20") ✓. Caveat 1: Figure 5 note 2 ("biopsy could be considered") ✓. Caveat 2: R.3.9 ✓. Caveat 3: R.5.2 p26 (">20% in maximum diameter (in addition to at least a 5 mm increase)") ✓. Caveat 4: R.6.2 ✓ |
| high_risk | ✓ R.2.5 ("In most cases, immediate surgery will be the management of choice, but in some patients, additional imaging might be an option"; staging "including at least thoracic CT and/or FDG-PET/CT"). Caveat 0: R.2.5 ✓. Caveat 1: reasoning p19 ("could be as high as 50%"), hedge kept ✓. Caveat 2: R.3.9 and R.2.8 p20 ✓. Caveat 3: R.6.2.1 and Figure 4 note 2 ✓. Caveat 4: the 4 cm conflict (For Hassan 1) ✓ |
| young_indeterminate | ✓ R.6.2.1 ("recommend urgent assessment ... because of a higher likelihood of malignancy as well as clinically significant hormone excess"), R.6.2.3 ("suggest surgical resection if an adrenal mass is indeterminate on imaging"). Caveat 0: reasoning p30 ✓. Caveat 1: R.6.2.2 ✓. Caveat 2: R.1.1, R.3.9 ✓ |
| does_not_apply | ✓ p4 §2.1 for the exclusion. Reworded after the read (I2): the classification says that with known malignancy ESE's Figure 9 pathway applies (§5.6.3 p30: "In principle ... the same recommendations apply"). "Manage per the clinical context" is labelled as a library addition. Caveats restore Figure 9 note 1 (life expectancy); R.6.3.2 (recommend, no further specific adrenal imaging follow-up) with Fig 9's hormone-excess branch (individualised treatment); R.6.3.3; and R.6.3.1 with both branches of R.6.3.4 (suggest PET/resection/biopsy; otherwise recommend follow-up at the primary malignancy's interval) ✓ |

### Reference
| field | verdict |
|---|---|
| sum.1-sum.4 | ✓ R.2.2; abstract p1; R.3.1-3.3, R.3.9, R.3.10 pp 2-3; R.5.2 |
| def.incidentaloma, def.homogeneous, def.washout | ✓ p4 §2.1; Table 4 note a; p9 §2.3 (both formulas copied as printed) |
| tab.4 | ✓ Table 4 cell for cell (four methods, criteria, strength of evidence) |
| tab.fig5 | ✓ Figure 5 box for box, including its "> 4cm" wording. "None stated" in the follow-up column is ours: the figure has no follow-up box under columns 1 and 2 |
| pitfalls | ✓ scope (§2.1); biopsy (R.2.7 p20, R.6.3.5 p32); heterogeneous masses not for MRI or washout (Table 4 note a); washout 58% caution (note f); bilateral and contralateral (R.6.1.1 p27, R.2.1 reasoning p17); FDG (note d, R.2.5 reasoning p20) |

## Gate 5 flags

66 facts, 29 below 0.5. Gate 5 scores each fact against the first page of its locator. Most caveats here cite several
recommendations on other pages (hormonal work-up, pregnancy, growth), so low scores are expected. Each flag was read
against the source:

| field | resolution |
|---|---|
| size_band (0.13), tab.fig5 | Figure 5 is an image; its text layer is jumbled. Confirmed by viewing p18 |
| age_band (0.36), pathway.case5 (0.43) | R.6.2.1 / R.6.2.3 p30: "<40 years of age" ✓ |
| pathway.case0, outcome.does_not_apply, caveat0 | p4 §2.1 and Figure 9 p31 / R.6.3 pp 30-32 ✓ (paraphrase across pages) |
| below_threshold caveat0, caveat1 | caveat0 ✓ p4 ("arbitrary work-up threshold of 1 cm"); caveat1 is our labelled reading |
| pathway.case3, benign_other caveats 0-2 | R.5.1 p26; Table 4 note a p19; R.3.2 p2; R.4.2 reasoning p24 ✓ |
| benign_attenuation caveats 1-3 | Figure 4 note 3 p17; R.4.2 p24; §5.6.2 reasoning p30 ✓ |
| needs_unenhanced_ct caveats 0-2 | §2.3 p8; R.6.2.2 p30 and R.2.3 reasoning p18; R.3.2 ✓ |
| additional_imaging caveats 0, 3 | R.2.4 p19 with R.3.9 p24; R.6.2.1-6.2.3 p30 ✓ |
| indeterminate_mdt caveats 2-4 | R.3.9 p24; R.5.2 p26; R.6.2 p30 ✓ |
| high_risk caveats 2-4 | R.3.9, R.2.8 p20; R.6.2.1 p30 and Figure 4 note 2 p17; 4 cm conflict p18/p19 ✓ |
| young_indeterminate caveat2 | R.1.1 p16; R.3.9 p24 ✓ |
| pit.biopsy (0.18) | R.2.7 p20 ("unless there is a history of extra-adrenal malignancy (see R.6.3.5)"); three criteria R.6.3.5 p32 ✓ |

**Re-run after the clinical-read fixes:** 72 facts, 31 below 0.5. The new flags are the reworded does_not_apply (classification 0.15, case0 0.16, caveat 3 0.25: §5.6.3 and Figure 9 are spread over pp 30-32 and the figure is an image) and the added R.6.2.1 urgency caveats (p30, cited from outcomes located elsewhere). Each was read against the source ✓.

No flag needed a correction of fact. On the first gate 5 run I reworded four items for fidelity: the young outcome
now says "indeterminate" (it covers heterogeneous masses too), the high-risk and indeterminate recommendations keep
R.2.5's "in some patients" and R.2.6's "usually preferred", and the pregnancy caveats now keep the source's
recommend/suggest strengths.

## For Hassan

1. **DECISION: the 4 cm edge for masses over 20 HU or heterogeneous.** Figure 5 (and the abstract) put the high-risk column at "> 4 cm" and the indeterminate column at "< 4 cm", leaving exactly 4.0 cm undefined. The text gives the edge: R.2.5 "≥ 4 cm", R.2.6 "< 4 cm". The figure-wins rule has no answer to follow here, so I used the text: 4.0 cm is high risk. The alternative is a "does not fit" outcome at exactly 4.0 cm.
2. **HU edges (controller ruling: explicit source wording wins; half-up only when the source says to round).** Edges sit exactly at 10 and 20: ≤10 benign, >10 to ≤20, >20 (R.2.3 "≤ 10", Figure 4 "HU > 10", R.2.5 "> 20"). 10.4 HU is not benign. Golden cases at 10, 10.4, 10.5, 20, 20.4 and 20.5 HU.
3. **DECISION: under 1 cm.** Every nodule under 1 cm goes to "below threshold", whatever its appearance or attenuation (§2.1: work-up only from 1 cm unless there are clinical signs of hormone excess). So a 9 mm heterogeneous nodule is not sent to the MDT.
4. **DECISION: known extra-adrenal malignancy goes to does_not_apply.** ESE says that "in principle" the same recommendations apply, but such masses fall outside the strict definition and get their own pathway (Figure 9). I didn't encode Figure 9; its gist is a caveat on does_not_apply. It could become a sibling pack.
5. **Combined eligibility.** "Imaging for suspected adrenal disease" and "hereditary-syndrome screening" are one input, because §2.1 excludes both the same way. That keeps it to two eligibility chips.
6. **DECISION: the `clearly_benign` option** (e.g. myelolipoma with macroscopic fat) goes to "no further imaging". It comes from Table 4 note a and R.5.1, not from a Figure 5 box. Without it, Figure 5 would send a large heterogeneous myelolipoma to surgery. how_stated requires a specific benign diagnosis made on imaging.
7. **DECISION: under 40.** For Figure 5 columns 2 and 3, a patient under 40 gets R.6.2.1/R.6.2.3 (urgent assessment; resection if indeterminate) instead of the figure's box. Column 4 keeps its outcome, with an urgency caveat. This means age is asked for any indeterminate mass. Pregnancy (the same R.6.2 rules) is a caveat, not an input, to avoid a chip on every case.
8. **No unenhanced CT.** A homogeneous mass with no unenhanced phase goes to "unenhanced CT recommended" (R.2.2). A heterogeneous mass is routed by size alone, as Figure 5 does, even without an unenhanced phase.
9. **Size is the maximum diameter.** ESE doesn't say how "tumor size" is measured; R.5.2 uses maximum diameter for growth.
10. **Growth on follow-up (R.5.2: over 20% and at least 5 mm, suggest resection)** is a caveat and a summary line, not an input. It could be added later as a prior-size input.
11. **R.2.6 versus R.5.2 strength.** R.2.6 "recommends" interval imaging in 6-12 months for a still-indeterminate mass that is not operated on; R.5.2 "suggests" one repeat noncontrast CT or MRI. The outcome follows R.2.6, the recommendation that defines this group.
12. **Metanephrines conflict.** The abstract says every patient needs metanephrines; Figure 4 note 3 and R.3.9 limit them to HU > 10 or features not typical of adenoma. The pack follows Figure 4 and R.3.9 (benign_attenuation caveat: needed only over 10 HU).
13. **DECISION: MRI-only cases.** A homogeneous mass characterised only on chemical-shift MRI has no unenhanced HU, so it goes to "unenhanced CT recommended" (R.2.2), although `applies_to` lists MRI. The caveat carries R.2.3's reasoning that an expert MDT may accept unambiguous chemical-shift MRI.
