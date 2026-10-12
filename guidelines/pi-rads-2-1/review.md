# Hand read: pi-rads-2-1@2019.1

## Source

- **S1 (primary):** PI-RADS Prostate Imaging – Reporting and Data System, 2019, Version 2.1. American College of Radiology, with the ESUR and AdMeTech Foundation steering committee. This is the full 76-page ACR document.
  - Filed from the controller's copy, a third-party mirror of the ACR PDF (a Word 2016 export dated 27 March 2019). sha256 `a160ada8…8184d`.
  - The manifest `url` is the ACR's own address. The pack task did not fetch from it, so the mirror copy's sha256 has **not** been compared with ACR's live file (recorded in the manifest `retrieved` field too). Compare it when the ACR file can be fetched.
- **Page numbers** in locators are PDF pages, counted from 1. The printed page number is the PDF page minus 7 (for example, PDF p18 is printed p11).
- **Tables as images:** the assessment tables on p18 (PZ and TZ) and p23 (without adequate DWI, without adequate DCE) do not survive `pdftotext`. I rendered both pages as images and read every cell from them.

## Structure

- **Inputs:**
  - `treated_cancer` (eligibility, patient scope);
  - `zone` (peripheral or transition);
  - `dwi` (1–5, or X as `not_assessable`);
  - `t2w` (1–5 or X). It applies only in the TZ, or when DWI is X.
  - `dce` (positive or negative, or X). It applies only to a PZ lesion with DWI 3, or when DWI is X.
- **Logic:** one `rules` step (`category`) with 23 cases that partition the space.
- **Gate 2** enumerates every combination, each giving exactly one outcome.
- **Result:** `pi-rads-2-1: gates 1-4 pass (pi-rads-2-1@2019.1)`.

## Checklist

### Rules cases (`category`)

| # | Condition | Result | Source | Check |
|---|---|---|---|---|
| 0 | treated prostate cancer | does_not_apply | p31 ("a setting in which current PI-RADS assessment criteria do not apply"); p10 (treatment-naive glands) | ✓ |
| 1 | DWI X and DCE X | staging_only | p23 ("If both DWI and DCE are inadequate or absent, assessment should be limited to staging for determination of EPE") | ✓ |
| 2 | T2W X (where T2W is used), not case 1 | not_categorised | p22 (X per component); no table without T2W | ✓ library addition, For Hassan. A PZ lesion with adequate DWI ignores T2W X: a library extension (the PZ table's "Any" is footnoted 1–5) |
| 3 | PZ, DWI 1 | 1 | p18 PZ table | ✓ |
| 4 | PZ, DWI 2 | 2 | p18 PZ table | ✓ |
| 5 | PZ, DWI 3, DCE − | 3 | p18 PZ table | ✓ |
| 6 | PZ, DWI 3, DCE + | 4 | p18 PZ table; p17 text | ✓ |
| 7 | PZ, DWI 3, DCE X | 3 | p23 ("PZ: Determined by DWI Assessment Category"); p31 (bpMRI: DWI 3 "will not be upgraded") | ✓ |
| 8 | PZ, DWI 4 | 4 | p18 PZ table | ✓ |
| 9 | PZ, DWI 5 | 5 | p18 PZ table | ✓ |
| 10 | TZ, DWI 1–5, T2W 1 | 1 | p18 TZ table | ✓ |
| 11 | TZ, DWI ≤3, T2W 2 | 2 | p18 TZ table; p21 (no upgrade on DWI 3) | ✓ |
| 12 | TZ, DWI ≥4, T2W 2 | 3 | p18 TZ table; Figure 12 (p71) | ✓ text says ">4": For Hassan |
| 13 | TZ, DWI ≤4, T2W 3 | 3 | p18 TZ table | ✓ |
| 14 | TZ, DWI 5, T2W 3 | 4 | p18 TZ table | ✓ |
| 15 | TZ, DWI 1–5, T2W 4 | 4 | p18 TZ table; p21 caveat | ✓ |
| 16 | TZ, DWI 1–5, T2W 5 | 5 | p18 TZ table | ✓ |
| 17 | DWI X, DCE ±, T2W 1 | 1 | p23 no-DWI table | ✓ |
| 18 | DWI X, DCE ±, T2W 2 | 2 | p23 no-DWI table | ✓ |
| 19 | DWI X, DCE −, T2W 3 | 3 | p23 no-DWI table | ✓ |
| 20 | DWI X, DCE +, T2W 3 | 4 | p23 no-DWI table | ✓ |
| 21 | DWI X, DCE ±, T2W 4 | 4 | p23 no-DWI table | ✓ |
| 22 | DWI X, DCE ±, T2W 5 | 5 | p23 no-DWI table | ✓ |

- **TZ without adequate DCE:** the p23 table is the TZ table with DCE set to X. Since `dce` is `not_applicable` on every TZ path where DWI is adequate, no extra case is needed. A golden case checks it.
- **The no-DWI table** is headed "Peripheral Zone (PZ) and Transition Zone (TZ)", so cases 17–22 do not read `zone`.

### Outcomes

| Outcome | Wording checked against | Check |
|---|---|---|
| pirads_1 … pirads_5 | p17: the categories and their likelihood phrases, word for word in meaning. Recommendations come from p17: "biopsy should be considered for PI-RADS 4 or 5, but not for PI-RADS 1 or 2 … PI-RADS v2.1 does not include recommendations for management"; for category 3, "biopsy may or may not be appropriate, depending on factors other than mpMRI alone" | ✓ |
| caveat: MRI findings only | p17 | ✓ |
| caveat: state the DWI limitation | p22 ("it should be clearly acknowledged in the exam report") | ✓ |
| caveat: PZ DWI 3 without DCE stays 3 | p31 | ✓ |
| caveat: extruded BPH nodule is category 2 | p28 | ✓ |
| staging_only | p23 | ✓ |
| not_categorised | p22, plus the library addition, labelled in its caveat | ✓ |
| does_not_apply | p31, p10. Recommendation is now non-management wording ("No PI-RADS category; v2.1 criteria do not apply to suspected recurrence after treatment."), per review Minor 2 | ✓ |

### Reference

- **Tables:** every cell of the p17 categories, the p18 PZ and TZ tables, the p23 no-DWI and no-DCE tables, the p25 T2W tables, the p27 DWI table and the p29 DCE table. Each was read against the page image or the text.
- **Wording:** the descriptors are our wording. Cut-offs (<1.5 cm, ≥1.5 cm) and hedges are kept.
- **Definitions and pitfalls:** each was checked against its cited page.

### Golden cases

- **Source cases (22):**
  - Figures 7–12 (p66–71). The Figure 7, 8 and 9 central zone and AFMS examples name no zone, so each is run on both tables; both give the source's category.
  - Appendix I lesions 1 and 2 (p35).
  - The p21 caveat examples (PZ DWI 4 + T2W 2 is 4; TZ T2W 4 + DWI 2 is 4).
  - The p21 no-upgrade statements (TZ T2W 1 or 2 with DWI 3).
  - The p31 bpMRI statements (PZ DWI 3 not upgraded; TZ unchanged without DCE).
  - Figure 14 (p73), the TZ scoring schematic: T2W 1 is 1; T2W 2 with DWI 1, 2 or 3 is 2; T2W 2 with DWI 4 or 5 is 3 (added after review Important 1).
- **Ours (24):**
  - every remaining PZ, TZ and no-DWI row;
  - staging_only, not_categorised (two routes) and does_not_apply;
  - three `needed` cases: `dce`, `t2w` and `treated_cancer`.
- **Coverage:** every outcome is reached. There are no number inputs, so there are no bands.

## Gate 5 flags (20) and their resolution

- **category.case7, case17–22 (p23, 0.13–0.29):** the p23 tables are image-only in the text layer (`pdftotext` scrambles them). I confirmed every cell from the rendered page image. Correct as written.
- **category.case12 (p18, 0.38):** the same cause, on the p18 TZ table image. Confirmed from the image: T2W 2 with DWI ≥4 is 3.
- **category.case2 and outcome.not_categorised (p22, 0.19 and 0.39):** expected, because this outcome is a library addition. The source defines X for every component (p22) but gives no table for a T2W X. It is labelled as an addition and listed below.
- **outcome.pirads_\*.caveat\* (p17, 0.02–0.05):** the caveats inherit the outcome's p17 locator, but their facts come from other pages:
  - the DWI limitation from p22;
  - the bpMRI no-upgrade from p31;
  - the extruded BPH nodule from p28.

  I confirmed each on its own page. Caveats have no locator field of their own.
- **reference.sum.2 (p17, 0.47):** the statement spans p17 (the DCE role) and p21 (the dominant sequence by zone). The section names both. Correct.
- **reference.pit.bph (p20, 0.20):** "even if they restrict or enhance" comes from p22, which the locator names. Correct.

## For Hassan

- **DECISION: TZ upgrade edge.** The p20 text says an atypical TZ nodule (T2W 2) is upgraded to 3 with "a DWI score of >4". The p18 table, the p23 table and Figure 12 (T2W 2 with DWI 4 gives 3) all say ≥4. I followed the table: DWI 4 or 5 upgrades it.
- **DECISION: T2W X.** When T2W is inadequate where it is needed (any TZ lesion, or any lesion whose DWI is also X), the pack gives "does not fit a PI-RADS v2.1 category". This is a library addition. A PZ lesion with adequate DWI ignores T2W X. That is a **library extension**: the PZ table's "Any" is footnoted "1–5", so it does not strictly cover X.
- **DECISION: DWI and DCE both X.** This always gives "staging only", even for T2W 1, 4 or 5, where the no-DWI table reads "Any" for DCE. I followed the explicit p23 sentence. As a result, DCE is asked whenever DWI is X.
- **DECISION: extruded BPH.** p28 says an encapsulated, circumscribed, round PZ or CZ nodule "should be category 2". I kept this as a caveat on categories 3–5 and as a pitfall, not as an input, so that every PZ card does not have to ask it. If such a nodule is dictated with DWI 3–5, the card shows the DWI-driven category alongside the caveat.
- **DECISION: eligibility.** There is one input: prostate cancer already treated, with suspected recurrence (p10, p31). These stay eligible:
  - "Progression during surveillance", which p10 says PI-RADS "does not address", is a pitfall only, because p31 recommends mpMRI for men on active surveillance.
  - Prior BPH or TURP treatment and 5-alpha reductase or hormonal drugs, which p31 lists for mpMRI, not as an exclusion.
  - **Source tension:** p31 item 3 lists "TRUS/TURP/BPH therapy, radiotherapy, focal therapy or embolization" and "drug/hormonal therapies" as conditions to evaluate with mpMRI "for disease detection and localization", while p10 and p31 also say PI-RADS criteria do not apply to recurrence after therapy. The pack resolves this by gating on treated prostate cancer **and** an MRI for recurrence; radiotherapy for another pelvic cancer, or focal therapy followed by a detection MRI that is not for recurrence, stays eligible. "Hormonal therapy for cancer" was dropped from `treated_cancer.how_stated` (review Minor 1), since p31 groups hormonal therapies with interventions to evaluate, not with exclusions.
- **DECISION: recommendation text.** The source gives no management, but it does say biopsy "should be considered for PI-RADS 4 or 5, but not for PI-RADS 1 or 2", and "may or may not be appropriate" for 3 (p17). The recommendations carry exactly that, together with the "no management recommendation" disclaimer. Nothing else is added.
- **Zone for the central zone and the AFMS.** The source scores an AFMS lesion with the criteria of the zone it appears to arise from (p21). It says nothing equivalent for the CZ, apart from noting that most CZ cancers arise in the PZ or TZ. The `zone` how_stated applies the same rule to the CZ.
- **The printed csPCa definition** reads "Gleason score > 7 (including 3+4 …)", which contradicts itself. It is kept as printed in a reference definition only, and no logic reads it.

## Revision 2: independent read fixes (clinical-read.md)

- **Important 1:** Figure 14 (p73) added as six source golden cases. Logic is unchanged.
- **Minor 1:** p31 interventions tension stated in For Hassan; "hormonal therapy for cancer" dropped from `treated_cancer.how_stated`.
- **Minor 2:** the does_not_apply recommendation now reads "No PI-RADS category; v2.1 criteria do not apply to suspected recurrence after treatment."
- **Minor 3:** ignoring T2W X for a PZ lesion with adequate DWI is now called a library extension.
- **Minor 4:** the TZ-without-DCE case is now `origin: "source"` (p31).
- **Minor 5:** the manifest and this file record that the mirror's sha256 has not been compared with ACR's live PDF.
- Gates 1–4 pass; gate 5 re-run: the same 20 flags, resolved as above (case0 and does_not_apply now score 0.95 and 0.91).
