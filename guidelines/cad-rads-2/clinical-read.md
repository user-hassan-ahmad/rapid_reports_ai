# Clinical read: cad-rads-2@2022.1

Independent read, done read-only against S1 (Cury RC et al, CAD-RADS 2.0, 2022). I used only the text extract
(`sources/9ca7…d429.txt`) and the table images tbl1, tbl2, tbl4, tbl5, tbl6, tbl7 and tbl11, which I viewed directly.
I did not open any HTML file.

## Verdict

**Not ready.** There are no Critical findings and 5 Important ones. The table structure is sound: all 52 rows, the
prerequisites and the 34 outcome mappings are correct. Every classification line and every management line for the
plain categories (no I modifier) matches Tables 4 and 5. The problems sit in four places:

- the I modifier outcomes (For Hassan item 2);
- modifier E, which the pack does not handle;
- CAD-RADS 2 with an I modifier, which the pack does not handle;
- some dropped hedges, which are minor.

## What I checked

### Table rows (52)

- **Stable (22 rows):** 0; 1 × P1-P4; 2 × P1-P4; 3 × 5 I states; 4A × 5 I states; 4B; 5; N.
- **Acute (22 rows):** the same shape.
- **Other (8 rows):** one row per category.

The prerequisites are right. P is asked only for categories 1 and 2: Tables 4 and 5 key their management on P only in
those rows, and the text says "P is not required for CAD-RADS 0". I is asked only for categories 3 and 4A: Tables 6 and 7
name "CAD-RADS 3 or 4A". All rows are ✓. Gap: CAD-RADS 2 with an I modifier is never asked for (finding I-5).

### Outcomes (34) against Tables 4, 5, 6 and 11

**Category lines.** Every classification line matches the category, the stenosis range and the interpretation cell. This
includes the Table 4 footnote b wording ("plaque with no stenosis"), the 4B definition (≥50% left main or ≥70% in three
vessels) and the ACS likelihood wording in Table 5. ✓

**Management, no I modifier.** These are ✓ cell for cell:

- stable 0, 1 by P, 2 by P, 3, 4A, 4B, 5 and N;
- acute 0, 1 by P, 2 by P, 3, 4A, 4B, 5 and N.

The key distinctions are kept:

- "consider" appears only in stable 1/P1;
- stable N says "may be needed", but acute N says "is needed";
- 4B says "ICA is recommended";
- acute 5 has the expedited ICA line with footnote e.

**I+ outcomes.** Stable 3 and acute 3 with I+ use the "When modifier I+, consider ICA" lines of Tables 4 and 5 ✓.
The 4A with I+ outcomes use "may be favoured" from Table 4 footnote e and Table 11 footnote a, which agrees with section
3.1.1 ("may favor the use of ICA … if revascularization is being considered") ✓. Both I+ outcomes for category 3 drop
the line "other treatments … should be considered" (finding M-2).

**I- and I+/- outcomes.** These are taken from Table 6, which is the CT-FFR table (findings I-1 to I-3).

### Caveats

These all match the source:

- the footnotes of Tables 4, 5 and 11;
- Table 1 footnote a (prior infarct coded I-);
- the Table 6 cut-offs (≤0.75; 0.76-0.80; >0.80; trans-lesional gradient >0.12);
- section 3.3.4 on HRP (admission or observation "may be considered"; aggressive prevention in CAD-RADS 1 and 2;
  CAD-RADS 3 with HRP, excluding left main);
- section 3.3.1 on the N rule;
- section 3.1.1 on occlusion context.

The only exception is the Tn+ caveat in acute CAD-RADS 2 (finding M-3).

### Reference

These match Table 1, Table 2 and the text:

- the stenosis grades;
- the P scales (CAC 1-100, 101-300, 301-999, >1000; SIS ≤2, 3-4, 5-7, ≥8);
- the coding order N, HRP, I, S, G, E;
- the HRP features;
- the N, graft, stent, E and multivessel pitfalls.

`def.i` leaves out peri-infarct ischaemia, which Table 7 codes as I+ (finding M-5).

### Golden cases (45)

All of the expected outcomes follow the table. The source examples map correctly:

| Source example | Expected outcome |
|---|---|
| vi (3/P3/I+) | stable_3_ipos |
| vii (4A/P2/I-, CTP) | stable_4a_ineg |
| v (4A/P3/N) | stable_4a, with the trailing N correctly read as a modifier |
| i (N/P2/S) | stable_n |
| iv (2/P4/G) | acute_2_p34 |
| Fig 4 (2/P2) | stable_2_p12 |
| Fig 5 (1/P3) | stable_1_p34 |

The "needed" cases are coherent.

Two gaps:

- Source example viii (4A/I+/E) is missing (finding I-4).
- The presentation is assumed for every source case, so only the category and P mapping of these cases is verified
  against the source (finding M-4).

## Findings

### Important

**I-1. A borderline CTP result (I+/-) gets advice that only applies to CT-FFR.** This affects stable_3_iborder,
stable_4a_iborder, acute_3_iborder and acute_4a_iborder.

The recommendation says to consider ICA "according to symptoms, lesion location and trans-lesional CT-FFR gradient
(>0.12)". The borderline guidance in Table 6, and its fuller text in section 3.3.5.1 ("delta CT-FFR … measured as the
pressure loss from 1 to 2 cm proximal to 1-2 cm distal"), is specific to CT-FFR. Table 7 and section 3.3.5.2 define
I+/- for CTP ("borderline or inconclusive") but give it no management. After CTP, the gradient clause is meaningless.

Fix: split I+/- by test, or word the line so it holds after either test. Drop the gradient from the recommendation and
keep it as a caveat that applies to CT-FFR only. Mark the CTP case as a library decision.

**I-2. "Defer invasive angiography and optimise medical therapy" overstates the source for CTP I-.** This affects
stable_3_ineg, stable_4a_ineg, acute_3_ineg and acute_4a_ineg.

The line copies the imperative cell of Table 6, which covers CT-FFR. The text hedges even for CT-FFR: "deferral of ICA
*would be appropriate*" (section 3.3.5.1). For CTP, the source says only that a negative CTP allows "the exclusion of
myocardial ischemia … avoiding additional downstream testing" (section 3.3.5.2). That loosely supports deferral when no
ischaemia is shown.

But CTP I- also covers a prior fixed infarct with no ischaemia (Table 1 footnote a; Table 7, second row). For that
patient, the source gives no advice to defer ICA, and the pack would print an unqualified "defer" over an infarcted
territory. These outcomes also leave out the Table 4 footnote d caveat ("functional imaging or ICA should be considered
… if persistent symptoms despite adequate medical therapy"), which still applies.

Fix:
- Hedge the line ("deferral of ICA would be appropriate; optimise medical therapy").
- Add a caveat that an I- coded for a fixed infarct is not, by itself, grounds for deferral.
- Restore the footnote d caveat.

**I-3. In acute chest pain, "admission" and "defer invasive angiography" appear together.** This affects acute_3_ineg
and acute_4a_ineg.

Table 6 is a stable-style physiology table, and nothing in the source applies its deferral to acute chest pain. For
acute 4A, Table 5 says "ACS likely; hospital admission; consider ICA or functional assessment". Whether to do ICA in
suspected ACS depends on troponin, ECG and symptoms, not on lesion-specific physiology. A flat "defer invasive
angiography" in a patient admitted as ACS likely is the most consequential overstatement in the pack.

Fix: in the acute outcomes, keep the Table 5 investigation line and carry the I- result as a caveat ("negative lesion
physiology; the source's deferral guidance (Table 6) is not specific to acute chest pain"). Raise this as a DECISION in
For Hassan.

**I-4. Modifier E is not handled.** The source codes non-atherosclerotic narrowing with a numeric category plus E (eg
"CAD-RADS 3/E" in section 3.3.6, and example viii "4A/I+/E"). It says E "may require disease-specific management
considerations and/or subspecialty referral" (section 3.3.6 and the line under Table 7).

The pack routes these cases to the atherosclerotic outcomes. An anomalous left main with no plaque (example viii)
would therefore get "aggressive risk factor modification and preventive pharmacotherapy" and the 4A plus I+ ICA line.
The only mention of E is `pit.e`; there is no outcome caveat, no For Hassan item and no golden case.

Fix, either of:
- add an `exception` input or state that leads to an "E: disease-specific management or subspecialty referral" outcome;
- at minimum, add a caveat on every outcome for categories 1-5, add example viii as a golden case, and add a For Hassan
  item.

**I-5. CAD-RADS 2 with an I modifier is not handled.** Tables 6 and 7 (CCTA column) and section 3.3.4 allow CT-FFR or
CTP in CAD-RADS 2 when the lesion is proximal with a stenosis of 40% or more, including with HRP. A report coded 2/P2/I+
reaches stable_2_p12, which says "No further cardiac investigation", and that contradicts a positive physiology result.
The source gives no management for 2 with an I modifier. The pack is silent on it and so is For Hassan.

Fix: ask for I in CAD-RADS 2 as well, and either route I+ to a "management not defined by the source; positive lesion
physiology reported" outcome, or add a caveat. Add a For Hassan item either way.

### Minor

**M-1. The hedge "should be considered" is dropped from several outcomes.** Tables 4 and 5 say other treatments,
including anti-anginal therapy and revascularisation options, "should be considered per guideline directed care". Some
outcomes print the line without that hedge:

| outcome | as printed |
|---|---|
| acute_3 | "other treatments … per guideline-directed care" |
| acute_4a | "anti-anginal therapy and revascularisation options per guideline-directed care" |
| acute_4a_ipos | "revascularisation options per guideline-directed care" |
| acute_4b | "anti-anginal therapy and revascularisation options per guideline-directed care" |
| stable_4a_ipos | "other treatments per guideline-directed care" |

The stable outcomes for 3, 4A, 4B and 5 keep "consider".

**M-2. Two I+ outcomes drop a line.** stable_3_ipos and acute_3_ipos leave out "other treatments (including
anti-anginal therapy) should be considered per guideline directed care". In Tables 4 and 5, that line applies to every
plaque grade (P1-P4) of CAD-RADS 3, whatever the I modifier.

**M-3. The Tn+ caveat in acute CAD-RADS 2 has the wrong source.** acute_2_p12 and acute_2_p34 carry "If troponin is
positive, consider other sources of raised troponin (Table 9)". Table 5 row 2 does not say this; Table 11 row 2 does.
The caveat also sits next to the Table 5 instruction "Tn(+) … consider hospital admission", which points the other way.

Fix: cite Table 11. Review.md also says "Table 11 (acute) agrees with Table 5", which is not exact on this line.

**M-4. Presentation is assumed in the source-origin cases.** It is assumed for all seven, and for example iv, a LIMA-graft
patient, "acute" is an arbitrary choice. Only the category and P mapping is verified by the source. Say so in the case
names or origin, so that these cases are not read as source-verified management.

**M-5. `def.i` leaves out peri-infarct ischaemia.** Table 7 and section 3.3.5.2 code it as I+ (a stress defect larger
than the rest defect). It is worth adding, because it reads close to the "fixed infarct = I-" caveat.

## For Hassan items

1. **`other` presentation leads to management_not_defined. Agree.** Tables 4 and 5 are titled for stable and acute chest
   pain only, and the text (Introduction and section 3.1) frames management in those two settings. Nothing supports
   applying a chest-pain row to, for example, pre-TAVI CCTA.

2. **Table 6 (CT-FFR) advice applied to CTP. Disagree in part.**
   - CT-FFR I-: acceptable, but hedge it to the text's "deferral would be appropriate".
   - CTP I- with no perfusion defect: defensible from section 3.3.5.2 ("avoiding additional downstream testing").
   - CTP I- for a fixed infarct: not supported (I-2).
   - CTP I+/-: the CT-FFR gradient advice does not transfer (I-1).
   - Acute I-: the deferral is not supported for acute chest pain (I-3).
   - 4A with I+ "may be favoured": correct and correctly hedged.

   Each of the three unsupported cases should become its own DECISION line.

3. **HRP is not an input, and the acute 2 conditional is kept inline. Agree.** This mirrors the "if … consider admission"
   wording of Table 5 and Table 11, and the HRP caveats in section 3.3.4 are carried faithfully. One caveat: HRP is
   also one of the footnote e triggers that may favour ICA in 4A, and that is correctly carried as a caveat only.

4. **A non-diagnostic CT-FFR or CTP is treated as no test. Agree.** Section 3.3.5.1 allows N on CT-FFR or CTP, and the
   no-I outcomes ("consider functional assessment" or "consider ICA or functional assessment") are the right fallback.

5. **The 4B threshold differs between tables and text (≥50% / ≥70% versus ">50%" / ">70%"). Agree** with following the
   tables. The category is dictated, so the outputs do not change.

6. **Example vi says "<0.75", Table 6 says "≤0.75". Agree.** There is no effect.

7. **`category` is lesion-scoped. Agree**, with the `how_stated` guard. The I modifier has the same per-patient versus
   per-lesion tension: in multivessel disease the ischaemic lesion may not be the most severe, which `pit.multivessel`
   covers.

8. **Table 10 is missing. Agree** that the pack does not need it, because Table 4 is complete for the stable rows.
   Qualifier: Table 11 does not exactly agree with Table 5 (M-3).
