# Review: cad-rads-2@2022.1

Source S1: Cury RC et al., CAD-RADS 2.0 (2022), *Radiol Cardiothorac Imaging* 2022;4(5):e220183, DOI 10.1148/ryct.220183,
PMC9627235. It was filed as the PMC text extract (`sources/9ca7…d429.txt`) plus the table images `ryct.220183.tbl1-9, tbl11`,
which I viewed with the Read tool. The page has no page numbers, so locators use the section and table. Every table cell
below was checked against the table image, not against the text extract, which holds only the captions.

## Pack type and structure (after the clinical read)

Tier 1 lookup. The source gives management for every category in Table 4 (stable chest pain) and Table 5 (acute chest pain).
Lesion-specific ischaemia management comes from Table 6 (CT-FFR), with Table 7 (CTP) used only for definitions.
One `table` step (`cadrads`) has 106 rows leading to 56 outcomes, keyed on seven inputs:

| input | scope | options / states | prerequisite | source | |
|---|---|---|---|---|---|
| `category` | lesion | 0, 1, 2, 3, 4A, 4B, 5, N | none | Tables 4 and 5, Category column; 3.3.1 (N as a category vs a modifier) | ✓ |
| `presentation` | patient | stable, acute, other | none | Tables 4 and 5 titles; `other` is a library addition (For Hassan 1) | ✓ |
| `e_modifier` | lesion | boolean | category 1-5; stable or acute | 3.3.6; Table 3 (For Hassan 5) | ✓ |
| `plaque_burden` | lesion | P1-P4 | category 1 or 2; stable or acute; E false | Tables 4 and 5 key P only in categories 1 and 2 | ✓ |
| `ischemia` | lesion | positive, negative, borderline; `absent`, `not_assessable` | category 2, 3 or 4A; stable or acute; E false | Tables 4 and 5 (I+ in CAD-RADS 3); Tables 6 and 7; 3.3.5 | ✓ (For Hassan 2-4, 6) |
| `ischemia_test` | lesion | ct_ffr, ctp | category 3 or 4A; I- or I+/- | 3.3.5.1; 3.3.5.2 | ✓ |
| `fixed_defect` | lesion | boolean | stable; category 3 or 4A; I- by CTP | Table 1 footnote a; Table 7, second row | ✓ |

There are no eligibility inputs: the source has no scope or exclusion clause that names a patient fact. Gate 2 passes.

## Outcomes (56), checked against the table images

| outcome | source cell | |
|---|---|---|
| stable_0, acute_0 | T4 / T5 CAD-RADS 0 | ✓ |
| stable_1_p1, \_p2, \_p34 | T4 CAD-RADS 1 by P ("consider" in P1 only) | ✓ |
| stable_2_p12, \_p34; acute_1_p12, \_p34; acute_2_p12, \_p34 | T4 / T5 categories 1 and 2 by P | ✓ |
| stable_2_p12_i, \_p34_i; acute_2_p12_i, \_p34_i | T6/T7 CCTA column (CAD-RADS 2 if proximal and ≥40%); no management given, so they state that and keep the category 2 line | ✓ (For Hassan 6) |
| stable_3, stable_4a, acute_3, acute_4a | T4 / T5 categories 3 and 4A, no ischaemia test or a non-diagnostic one; "should be considered" restored (M-1) | ✓ |
| \*_3_ipos, \*_4a_ipos | T4 / T5 "when modifier I+, consider ICA"; 4A uses T4 footnote e / T11 footnote a ("may be favoured"); the CAD-RADS 3 "other treatments" line restored (M-2) | ✓ |
| stable_3_ineg_defer, stable_4a_ineg_defer | 3.3.5.1 "deferral of ICA would be appropriate" (hedged); T6; 3.3.5.2 for CTP with no defect; T4 footnote d caveat added | ✓ (For Hassan 2) |
| stable_3_ineg_infarct, stable_4a_ineg_infarct | Table 1 footnote a; T7 row 2; no deferral advice, so they state that and keep the T4 line | ✓ (For Hassan 3) |
| acute_3_ineg, acute_4a_ineg | T5 line unchanged; I- carried as a caveat | ✓ (For Hassan 4) |
| \*_iborder_ffr | T6 / 3.3.5.1 borderline guidance, with the gradient as a caveat | ✓ |
| \*_iborder_ctp | T7 / 3.3.5.2 define I+/- but give no management, so they state that and keep the T4 / T5 line | ✓ (For Hassan 3) |
| stable_4b, acute_4b, stable_5, acute_5 | T4 / T5; "should be considered" restored (M-1) | ✓ |
| stable_n, acute_n | T4 "may be needed" / T5 "is needed" | ✓ |
| \*_1_e … \*_5_e (12) | 3.3.6: CAD-RADS, which relates strictly to atherosclerotic disease, may not fully capture the abnormality; the category line moves to a caveat that applies only if plaque is present | ✓ (For Hassan 5) |
| management_not_defined | library addition | ✓ (For Hassan 1) |

Hedges kept: "consider" in stable 1/P1 only, "may be needed" (stable N) vs "is needed" (acute N), "ICA is recommended" (4B),
and "may be favoured" (footnote e).

Caveats checked: footnotes c, d and e of Table 4; footnotes b, c, d and e of Table 5; Table 1 footnote a (prior infarct
coded I-); the Table 6 CT-FFR cut-offs (≤0.75, 0.76-0.80, >0.80, gradient >0.12); section 3.3.4 on HRP (aggressive
prevention in CAD-RADS 1 and 2; admission or observation may be considered in acute chest pain; CAD-RADS 3 with HRP);
section 3.1.1 on occlusion context; section 3.3.1 on the N rule. All ✓.

## Golden cases (69)

- 8 source-origin cases: examples i, iv, v, vi, vii and viii (4A/I+/E) in 3.3.6, and the Figure 4 and 5 legends. The source gives no presentation for any of them, so the presentation is ours. Each case name says so: only the category, P, I and E mapping is verified against the source (M-4).
- One case for every other outcome.
- The P edges: stable 1, P1 | P2 | P3-P4; acute 1, P2 | P3; stable 2, P2 | P3.
- `not_assessable` ischaemia; acute I- with CT-FFR and with CTP (no deferral, `fixed_defect` not asked); `other` presentation.
- Five `needed` cases: presentation, plaque_burden, ischemia, ischemia_test and e_modifier.

## Gate 5 flags (300 of 363 below 0.5)

All of them are expected. The management lives in the images of Tables 4, 5, 6, 7 and 11, which the text extract holds as captions only, and gate 5 caps its text windows. I resolved every flag by reading the table images and sections 3.3.4-3.3.6 myself:

| flags | resolution |
|---|---|
| `cadrads.row0`-`row105` | each row's outcome is confirmed above, cell by cell |
| `outcome.*`, `outcome.*.caveatN` | table footnotes (image only) confirmed on the images; section 3.3.1, 3.3.4, 3.3.5 and 3.3.6 text confirmed in the extract. The acute CAD-RADS 2 troponin caveat now cites Table 11 (M-3) |
| `reference.*` below 0.5 | sections 3.3-3.3.6 and the footnotes of Tables 4 and 5, confirmed. `def.i` now includes peri-infarct ischaemia (M-5) and scores 0.90 |

## Compaction for Ask (material 46,152 → 40,398 characters; cap raised to 48,000 by controller ruling)

The outcome ids, the logic and the golden cases are unchanged.

- **Kept:** every outcome caveat, 185 in all. Caveats travel into the Apply proposal, so none moved to `reference`; an earlier attempt that moved them was reverted. A few were shortened without changing their meaning: the acute CAD-RADS 5 "other treatments" line, the Table 11 troponin line, the `management_not_defined` note, and "Outpatient follow-up is for" became "Follow-up is for". `tests/test_library_cad_rads_caveats.py` pins the caveat count per outcome and the conditions the clinical read required.
- **Fallback outcomes** (borderline CTP; I- from a fixed infarct; CAD-RADS 2 with an I result): they state the "no source management" sentence, then the category line once, in short form.
- **Repeated phrases** were shortened with their hedges kept:
  - "other treatments, including … should be considered" became "anti-anginal therapy (and revascularisation options) should be considered";
  - "Preventive management, including aggressive preventive pharmacotherapy" became "Aggressive preventive pharmacotherapy";
  - in classifications, "CT ischaemia test positive (I+)" became "I+".
- **Locators and hints:** outcome locators are grouped, and the exact cell is in the checklist above. The `how_stated` hints are shorter, with the same meaning.

## For Hassan

1. **DECISION**: `presentation` has a third option, `other`, which leads to `management_not_defined`. Tables 4 and 5 cover stable and acute chest pain only. This is a library addition. The reader agreed.
2. **DECISION (I-2)**: ICA deferral applies only to stable chest pain, and only after CT-FFR I- or CTP I- with no perfusion defect. It is hedged as the text has it ("deferral of ICA would be appropriate; optimise medical therapy") and carries the Table 4 footnote d caveat on persistent symptoms.
3. **DECISION (I-1, I-2)**: Two results get no Table 6 advice: a borderline CTP result (I+/-), and an I- coded for a fixed infarct. Their outcomes state that CAD-RADS 2.0 gives no such management, and fall back to the category's Table 4/5 line.
4. **DECISION (I-3)**: Acute chest pain never gets the deferral line. The acute I- outcomes keep the Table 5 line, and the negative test is a caveat.
5. **DECISION (I-4)**: A new `e_modifier` boolean is asked for categories 1-5. When it is true, the recommendation leads with the source's E statement (3.3.6: CAD-RADS, strictly atherosclerotic, may not fully capture the abnormality). The category's atherosclerotic line becomes a caveat that applies only if plaque is present, and P and I are not used. The controller's wording "may require disease-specific management and/or subspecialty referral" is not in the filed source (text extract or table images), so it is not used.
6. **DECISION (I-5)**: I is now asked for CAD-RADS 2. Tables 6 and 7 give no management row for category 2, so the outcome states that and keeps the category 2 line by P.
7. **DECISION**: HRP is not an input. Acute CAD-RADS 2 keeps the source's conditional inside the recommendation, and the 3.3.4 guidance is carried as caveats. The reader agreed.
8. **DECISION**: A non-diagnostic CT-FFR or CTP (`not_assessable`) gives the same outcome as no ischaemia test. The reader agreed.
9. The fallback outcomes now give the category line in short form (see Compaction); the full line is on the category's own outcome.
10. Table versus text: 4B is "≥70%" and "≥50%" in the tables but ">70%" and "at least greater than 50%" in 3.1.1. I followed the tables. No effect, because the category is dictated.
11. Example vi gives CT-FFR "<0.75" for I+; Table 6 gives ≤0.75. No effect.
12. `category` is lesion-scoped, as the brief says, although CAD-RADS is per patient. The `how_stated` field guards against inferring it from a percentage.
13. Source completeness: the Table 10 image (stable suggested text) is not in sources2, and the pack does not need it. Table 11 (acute) matches Table 5 except that it adds the troponin line to CAD-RADS 2 (M-3).
