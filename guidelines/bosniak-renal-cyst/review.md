# Gate 6: hand read, bosniak-renal-cyst@2019.1

## Source

- **Article:** Silverman SG, et al. Radiology 2019;292(2):475–488, doi:10.1148/radiol.2019182646.
- **Text read:** the PMC open-access full text (PMC6677285). This follows a controller ruling, because the publisher PDF is behind a bot wall. Volume, issue and pages were checked on the PMC page.
- **Tables:** PMC serves Tables 1–4 only as images. I read the images directly and filed them under `sources/` by sha256:
  - `6067941f….jpg` is Table 2, the v2019 classification and the main source;
  - `43f824ce….jpg` is Table 3, the definitions of terms;
  - `dd52490f….jpg` is Table 4, the reporting phrases that hold the management wording;
  - `4fb7ca40….jpg` is Table 1, the original classification.
- **Manifest:** the manifest schema allows one `file` and one `text_file` per source and forbids extra fields, so the images are listed here instead (review M-6).
- **Footnotes and table notes** are in the text file.

## Revision 2: review fix I-1

Enhancement is now modelled per structure, following the source's own terms:

- the wall counts as an "enhancing wall";
- septa count as "enhancing septa";
- a nodule and irregular thickening are both "enhancing convex protrusions";
- II type 3 is a "non-enhancing mass", so the mass's own enhancement is asked about separately.

To keep gate 2 under the 200,000 cap without raising it, enhancement is folded into each structure's enum:

- **`wall`:** thin; minimally thickened, enhancing or not; thick, enhancing or not.
- **`septa`:** none; few thin; many thin, enhancing or not; minimally thickened, enhancing or not; thick, enhancing or not.
- **`protrusion`:** none; irregular thickening (enhancing); nodule (enhancing); not enhancing.
- **`contents_enhancement`:** present or absent. Its prerequisite is renal mass protocol CT.

"Not enhancing" also covers "not assessable". Both lead to the same outcome: no class, with MRI advised.

Enhancing features count only on renal mass protocol CT. Table 3 defines enhancement as a comparison of unenhanced and enhanced images, or as a measurement (review M-2).

Gate 2 enumerates 184,320 combinations. MAX_VERIFY is unchanged.

## Checklist: band, rules cases, outcomes

**Band `hu_band`.** Sources: Table 2 CT column, Table 3 "simple fluid", and the Bosniak II text.

- `lt_m9` (below −9 HU) ✓. No class uses it.
- `m9_20` (−9 to 20 HU, both edges inclusive) ✓.
- `21_30` (over 20 to 30 HU) ✓. The source says both "21 to 30" and ">20"; I closed the gap at >20.
- `31_69` (over 30 and under 70 HU) ✓. This is the undefined middle; the cut is ours.
- `ge70` (70 HU or more) ✓.

**Rules step `class`.** The highest class wins (Table 2 footnote *). "RMP" below means renal mass protocol CT.

| Case | Result | Rule | Check |
|---|---|---|---|
| 0 | II | Too small to characterise, and homogeneous low attenuation. | ✓ II type 6 |
| 1 | unclassifiable | Too small, other. | ✓ undefined in the source |
| 2 | IV | Nodule on RMP: an enhancing protrusion, acute of any size or obtuse ≥4 mm. | ✓ Table 3 |
| 3 | III | RMP, no nodule, and one of: irregular thickening (enhancing, obtuse, ≤3 mm), a thick enhancing wall, a thick enhancing septum. | ✓ |
| 4 | IIF | RMP, no III or IV feature, and one of: a 3 mm enhancing wall, a 3 mm enhancing septum, many thin enhancing septa. | ✓ Text: "walls or septa of a Bosniak IIF cystic mass must enhance" |
| 5 | unclassifiable | Complex structure (any protrusion, a wall that is not thin, or septa beyond few thin) with no qualifying enhancing feature. This includes non-enhancing features and single-phase CT. | ✓ Footnote † sends these to MRI |
| 6 | unclassifiable | Simple structure but ill-defined. | ✓ I and II require well-defined |
| 7 | II | Few (1–3) thin septa. Calcification, contents and HU are free. | ✓ II type 1 |
| 8 | I | No septa; uniform contents; no calcification; −9 to 20 HU; the mass does not enhance when on RMP. Technique is RMP, portal venous or other contrast-enhanced. | ✓ Table 3: simple fluid holds at noncontrast or contrast-enhanced CT |
| 9 | II | The same, on unenhanced-only CT. | ✓ II type 4 |
| 10 | II | Simple fluid with calcification and no septa. | Not in Table 2. From the Bosniak II text: "calcifications of any morphology now are considered a Bosniak II feature" |
| 11 | II | ≥70 HU on unenhanced-only CT. On RMP, ≥70 HU is covered by case 12. | ✓ II type 2 |
| 12 | II | >20 HU, uniform, the mass does not enhance, RMP, calcification of any type. A thin enhancing wall no longer blocks this (I-1). | ✓ II type 3 |
| 13 | II | 21–30 HU on a single portal venous phase. | ✓ II type 5 |
| 14 | unclassifiable | The no-septa simple-structure remainder: heterogeneous contents; HU and technique outside every type; or the mass enhances on RMP (a cystic mass is <25% enhancing tissue, and II type 3 requires a non-enhancing mass). | ✓ |

**Outcomes.** Sources: Table 4 phrases, the "Bosniak III" and "Bosniak IV" sections, and the closing management paragraph.

- **`class_i`:** no follow-up ✓.
- **`class_ii`:** benign or likely benign, no follow-up ✓.
  - Caveat 1 is the "cyst" wording rule from the Table 4 footnotes.
  - Caveat 2 is footnote †. It now includes heterogeneous contents, which covers type 1 masses (review item 7).
- **`class_iif`:** follow-up at 6 and 12 months, then yearly to 5 years ✓.
- **`class_iii`:** about half malignant; consider urology ✓.
- **`class_iv`:** about 90% malignant; consider urology ✓.
- **`unclassifiable`:**
  - the headline is the brief's;
  - the recommendation is now "dedicated renal mass protocol CT or MRI" (review M-5), from footnote †;
  - the caveats are footnote * (such a mass may warrant IIF) and the Table 3 definitions of enhancement and of a cystic mass.

## Golden cases (43)

- **Source cases (8):** the text example (few thick enhancing septa is III) and Figs 1–3.
- **Fig 4:** this is an MRI example, so it is now an "ours" case with CT inputs (M-3).
- **Single-phase cases:** these no longer carry an enhancement value (M-3).
- **Added for I-1:**
  - non-enhancing protrusion with a thin wall → unclassifiable, not IV;
  - non-enhancing thick septum → unclassifiable, not III;
  - many non-enhancing thin septa → unclassifiable, not IIF;
  - non-enhancing 3 mm septum → unclassifiable;
  - RMP 45 HU with a non-enhancing mass → II (it was unclassifiable before);
  - RMP 45 HU and RMP 10 HU with an enhancing mass → unclassifiable.
- **Added for M-2:**
  - nodule on portal venous only → unclassifiable;
  - 3 mm wall on unenhanced only → unclassifiable.
- **Added for M-1:** other contrast-only CT gives I at 15 HU and unclassifiable at 25 HU, so II type 5 is not reached.
- **"Needed" cases:** HU, mass enhancement, and septa.

## Jev `check` items (gate 5)

Jev scored 27 of 54 facts below 0.5. Because the locators are page-less, the script feeds the whole text file. The Jev client then keeps only 6 of 10 windows, and the early windows are mostly PMC navigation. Each item was resolved by reading the source:

- **hu_band and class.case0–14:** the class definitions exist only in the Table 2 and 3 images; checked against them as above ✓.
- **outcome.class_ii and class_ii.caveat0:** Table 4 and its footnotes, plus the General Points text ✓.
- **outcome.class_iif, class_iii and class_iv:** Table 4, plus the Bosniak III section (~50%) and the Bosniak IV section (~90%) ✓.
- **outcome.unclassifiable:** footnotes * and † ✓.
- **sum.5 and pit.mri:** these describe the entry's own scope ✓.
- **def.homog, def.fluid and def.septum:** Table 3 ✓.

## Review minors

| Item | Response |
|---|---|
| M-1 | Done: the fourth technique option `other_contrast_only` allows class I but not II type 5. |
| M-2 | Done: enhancing features count only on RMP. |
| M-3 | Done. |
| M-4 | Done: how_stated now says which septum or protrusion to give, and how to measure (perpendicular, summed on both sides, excluding the septum). |
| M-5 | Done. |
| M-6 | Not possible in the schema; the images are listed here instead. |
| Bundle rebuild and drift test | For the controller; the bundle was not rebuilt, per instruction. |

## For Hassan

1. **Thickness and protrusion inputs use the source's categories** (≤2 / 3 / ≥4 mm), combined with enhancement, rather than mm numbers. The source leaves 2–3 mm and 3–4 mm undefined.
2. **The 20–21 HU gap is closed at >20.**
3. **Class I versus II type 4:** II type 4 is taken to mean unenhanced-only CT. Class I is given on RMP, portal venous or other contrast-enhanced CT.
4. **Calcification without septa is class II,** following the text: calcification of any type is a II feature. II types 2, 4 and 5 therefore allow calcification; class I does not.
5. **"Not enhancing" and "not assessable" are merged** in the wall, septa and protrusion options, to stay under the gate cap. Both lead to unclassifiable with MRI advised.
6. **One septa value per mass,** taken from the highest-class enhancing septum. A mix such as a non-enhancing thick septum alongside enhancing thin septa is reported by the enhancing one.
7. **On RMP, a mass that itself enhances is unclassifiable,** because the source does not count it as a cystic mass. This holds even at ≥70 HU. On unenhanced-only CT, ≥70 HU stays II type 2 as the source says.
8. **These undefined combinations go to unclassifiable:**
   - too small to characterise, but not homogeneous low attenuation;
   - complex structure without an enhancing feature on RMP, or on any single-phase CT;
   - ill-defined but otherwise simple;
   - heterogeneous contents with no septa;
   - below −9 HU;
   - 31–69 HU on unenhanced CT;
   - over 30 HU on portal venous CT;
   - over 20 HU on other contrast-only CT;
   - an enhancing mass on RMP.

   The source's "may warrant IIF" is kept as a caveat only, not mapped to IIF.
9. **II type 1 (few thin septa) leaves attenuation and contents free,** as the source does.
10. **Issuer** is "Society of Abdominal Radiology (Silverman et al.)", the society the source names as endorsing the update.
