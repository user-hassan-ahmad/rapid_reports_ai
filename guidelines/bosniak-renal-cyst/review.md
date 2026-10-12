# Gate 6: hand read, bosniak-renal-cyst@2019.1

Source: Silverman SG, et al. Radiology 2019;292:475–488, doi:10.1148/radiol.2019182646, read as the PMC open-access
full text (PMC6677285; controller ruling, publisher PDF behind a bot wall). Volume, issue and pages verified on the PMC
page (292(2):475–488). PMC serves Tables 1–4 only as images; they are filed under `sources/` by sha256 and were read
directly:

- `6067941f….jpg`: Table 2, the v2019 classification (CT and MRI columns), the main source.
- `43f824ce….jpg`: Table 3, definitions of terms.
- `dd52490f….jpg`: Table 4, suggested reporting phrases (the management wording).
- `4fb7ca40….jpg`: Table 1, the original classification (context only).

The table notes and footnotes are in the text file, under "Proposed Update…" and "General Points".

## Checklist: band, rules cases, outcomes

**Band `hu_band`** (Table 2 CT column, Table 3 "simple fluid", Bosniak II text):
- `lt_m9` below −9 HU. ✓ Below simple fluid; no class uses it, so it leads to `unclassifiable` (fat suggests another lesion).
- `m9_20` −9 to 20 HU, both edges inclusive. ✓ ("−9 to 20 HU").
- `21_30` over 20 to 30 HU. ✓ The source says "21 to 30 HU" and ">20 HU". The 20–21 gap is closed at >20 (see For Hassan).
- `31_69` over 30 and under 70 HU. ✓ This is the undefined middle band, our cut.
- `ge70` 70 HU or more. ✓ ("≥ 70 HU").

**Rules step `class`.** Highest class wins (Table 2 footnote *). Each case is checked against Table 2:
- 0 → II: too small to characterise, homogeneous, low attenuation. ✓ II type 6.
- 1 → unclassifiable: too small, other. ✓ Undefined in source (For Hassan).
- 2 → IV: an enhancing nodule (acute margins of any size, or obtuse margins ≥4 mm). ✓ Table 2 IV; Table 3 "nodule".
- 3 → III: enhancing, no nodule, and a thick (≥4 mm) wall or septum or irregular thickening (obtuse, ≤3 mm). ✓
- 4 → IIF: enhancing, no III/IV feature, and a 3 mm wall, a 3 mm septum, or ≥4 thin septa. ✓ "Smooth" is guaranteed because any protrusion is a III/IV feature.
- 5 → unclassifiable: IIF–IV structure but enhancement absent or not assessable. ✓ Every IIF–IV feature in Table 2 must enhance. Footnote † sends heterogeneous or nonenhancing complex masses to MRI.
- 6 → unclassifiable: simple structure but ill-defined. ✓ Classes I and II require a well-defined mass.
- 7 → II: few (1–3) thin septa, thin smooth wall; calcification, enhancement and contents are not constrained. ✓ II type 1.
- 8 → I: no septa, uniform contents, no calcification, −9 to 20 HU, on renal mass protocol or portal venous CT. ✓ The technique restriction is our reading (For Hassan).
- 9 → II: same as case 8 on unenhanced-only CT. ✓ II type 4.
- 10 → II: a simple-fluid mass with calcification and no septa. Table 2 does not list this. It is taken from the Bosniak II text ("calcifications of any morphology now are considered a Bosniak II feature"); see For Hassan.
- 11 → II: ≥70 HU, uniform, no septa, on unenhanced CT, or on renal mass protocol CT when enhancement is not absent. ✓ II type 2. Calcification is allowed (For Hassan).
- 12 → II: >20 HU, uniform, non-enhancing, on renal mass protocol CT, calcification allowed. ✓ II type 3.
- 13 → II: 21–30 HU on a single portal venous phase. ✓ II type 5. Calcification is allowed (For Hassan).
- 14 → unclassifiable: the simple-structure, no-septa remainder (heterogeneous contents, or attenuation and technique outside every type). ✓ Footnote †.

**Outcomes** (Table 4 phrases, plus the "Bosniak III" and "Bosniak IV" sections and the closing management paragraph):
- `class_i`: benign simple cyst, no follow-up. ✓
- `class_ii`: benign or likely benign, no follow-up. ✓ Table 4 options 1 and 2. Caveat 1 is the "cyst" wording rule (Table 4 footnotes and the General Points text). Caveat 2 is footnote †.
- `class_iif`: most benign, malignant ones indolent; follow-up at 6 and 12 months, then yearly to 5 years. ✓
- `class_iii`: about half malignant (Bosniak III section); consider urology. ✓ The caveat is from the closing paragraph ("class III … unclear").
- `class_iv`: about 90% malignant (Bosniak IV section); consider urology. ✓
- `unclassifiable`: per brief. The MRI advice comes from footnote †. The IIF caveat is from footnote * ("may warrant inclusion into Bosniak IIF").
- The shared caveat on general population and patient factors is from the Table 4 note and the closing paragraph. ✓

## Jev `check` items (gate 5)

Jev scored 29 of 54 facts below 0.5. The locators have no pages, so the script fed the whole text file. The Jev client then kept only 6 of 10 windows, so the tail was never seen: the later sections, the closing management paragraph and the references. The page navigation text took up the early windows. Each item was resolved by my own reading:

- **hu_band, class.case0–14**: the class definitions exist only in the Table 2 image. All were checked against the image above. ✓
- **outcome.class_ii, class_ii.caveat0**: Table 4 image and footnotes *†, plus the General Points text on "cyst" versus "mass". ✓
- **outcome.class_iif / class_iii / class_iv**: Table 4 image. The percentages are from the "Bosniak III" (~50%) and "Bosniak IV" (~90%) sections. ✓
- **class_iif.caveat0, class_iii.caveat1** (the shared caveat): the Table 4 note ("general population and not those with a renal cell carcinoma syndrome") and the closing paragraph ("patient factors … need to be considered"). ✓
- **outcome.unclassifiable**: footnotes * and † under Table 2. ✓ The headline wording is the brief's.
- **sum.5, pit.mri**: these are statements about this entry's scope, not facts from the source. ✓ by construction.
- **def.homog, def.fluid, def.septum**: Table 3 image (Homogeneous, Simple fluid, Septum, Few, Many). ✓

## For Hassan

- **Thickness inputs are enums, not mm numbers.** The source's thin (≤2 mm), minimally thickened (3 mm) and thick (≥4 mm) leave gaps between 2–3 and 3–4 mm. Banding a number would mean inventing edges, so the inputs take the source's three categories. Protrusions are handled the same way (≤3 vs ≥4 mm).
- **HU 20–21 gap**: ">20 HU" (II type 3) and "21 to 30 HU" (II type 5) were both encoded as >20. A value of 20.5 HU counts as 21–30.
- **Class I versus II type 4**: read literally, a homogeneous −9 to 20 HU mass meets both, and the highest class wins. I take II type 4 to mean an unenhanced-only examination. Class I is therefore given on renal mass protocol CT or a single portal venous phase, and II on unenhanced-only CT.
- **Calcification with no septa** (simple fluid, ≥70 HU or 21–30 HU types): Table 2 types 2, 4 and 5 are "homogeneous", which by definition excludes calcification. The text, however, makes calcification of any morphology a II feature, so these masses are class II with calcification allowed. Class I still requires no calcification.
- **One enhancement input** covers the wall, septa and protrusions. A mass with an enhancing thin wall but a non-enhancing 3 mm septum would be called IIF, where the source would advise MRI. Also, II type 3 needs "non-enhancing", so a hyperattenuating (21–69 HU) cyst on renal mass protocol CT with a visibly enhancing thin wall comes out unclassifiable.
- **Enhancement on single-phase CT** is allowed to be "not assessable", because the definition needs a comparison or a measurement. Complex features then lead to unclassifiable rather than IIF–IV.
- **Undefined combinations that lead to `unclassifiable`**:
  - too small to characterise but not homogeneous low attenuation;
  - IIF–IV structure without enhancement;
  - ill-defined but otherwise simple;
  - heterogeneous contents with no septa;
  - attenuation below −9 HU;
  - 31–69 HU on unenhanced or portal venous CT;
  - 21–69 HU on renal mass protocol CT with enhancement present or not assessable (≥70 HU is II type 2).

  The source says a rare undefined mass "may warrant" IIF. This is a caveat only; it is not mapped to IIF.
- **II type 1** (few thin septa) constrains neither attenuation nor contents in the source, so neither does the entry.
- **Issuer**: the source names no author group; it says the Society of Abdominal Radiology endorses the update. The issuer is therefore "Society of Abdominal Radiology (Silverman et al.)".
