# Gate 6: hand read, fleischner-pulmonary-nodule@2017.1

Read side by side with the PDF page images (Read tool, pages 2–13) and `sources/3088…087f.txt`. Locator pages are
1-based PDF pages; this copy is the online-ahead-of-print version (printed pages 1–16, "Volume 000: Number 0"), so
they do not match the issue pagination 284:228–243.

## Inputs and bands

| item | source | |
|---|---|---|
| `nodule_type` solid / ground-glass / part-solid | p3 Table, parts A and B | ✓ |
| `count` single / multiple | p3 Table rows | ✓ |
| `diameter_mm`, average of long and short axes | p3 Table footnote; p4–5 General Recommendations | ✓ |
| `risk` low / high, solid only | p3 Table (risk rows only in part A); p12 "recommendations for subsolid nodules are independent of customary risk categories" | ✓ |
| band `lt6` <5.5 | p5: "<6 mm corresponds to a rounded measurement of 5 mm or less" | ✓ |
| band `6to8` [5.5, 8.5) | p3 "6–8 mm"; rounded 6, 7, 8 | ✓ |
| band `gt8` ≥8.5 | p3 ">8 mm"; rounded 9 or more | ✓ |
| subsolid "≥6 mm" lists `6to8` and `gt8` | p3 Table part B | ✓ |

## Table rows (24) and outcomes (15)

| outcome | rows | source cell (p3) | |
|---|---|---|---|
| solid_single_lt6_low | solid, single, lt6, low | "No routine follow-up"; comment on suspicious morphology / upper lobe 12-month follow-up (1A) | ✓ |
| solid_single_lt6_high | solid, single, lt6, high | "Optional CT at 12 months"; same comment | ✓ |
| solid_single_6to8_low | solid, single, 6to8, low | "CT at 6–12 months, then consider CT at 18–24 months" | ✓ |
| solid_single_6to8_high | solid, single, 6to8, high | "CT at 6–12 months, then CT at 18–24 months" | ✓ |
| solid_single_gt8 | solid, single, gt8, low + high | "Consider CT at 3 months, PET/CT, or tissue sampling" (identical for both risks) | ✓ |
| solid_multiple_lt6_low | solid, multiple, lt6, low | "No routine follow-up"; comment: most suspicious nodule guides, intervals vary (2A) | ✓ |
| solid_multiple_lt6_high | solid, multiple, lt6, high | "Optional CT at 12 months"; same comment | ✓ |
| solid_multiple_ge6_low | solid, multiple, 6to8 + gt8, low | "CT at 3–6 months, then consider CT at 18–24 months" (both size columns identical) | ✓ |
| solid_multiple_ge6_high | solid, multiple, 6to8 + gt8, high | "CT at 3–6 months, then at 18–24 months" (both identical) | ✓ |
| ggn_single_lt6 | ground-glass, single, lt6 | "No routine follow-up"; comment: suspicious <6 mm consider 2 and 4 years; solid component or growth → consider resection (3A, 4A) | ✓ |
| ggn_single_ge6 | ground-glass, single, 6to8 + gt8 | "CT at 6–12 months to confirm persistence, then CT every 2 years until 5 years" | ✓ |
| psn_single_lt6 | part-solid, single, lt6 | "No routine follow-up"; comment: cannot be defined as part-solid until ≥6 mm, <6 mm usually no follow-up | ✓ |
| psn_single_ge6 | part-solid, single, 6to8 + gt8 | "CT at 3–6 months to confirm persistence. If unchanged and solid component remains <6 mm, annual CT … for 5 years"; comment: solid component ≥6 mm highly suspicious (4A–4C) | ✓ |
| subsolid_multiple_lt6 | ground-glass + part-solid, multiple, lt6 | "CT at 3–6 months. If stable, consider CT at 2 and 4 years"; comment: multiple <6 mm pure GGNs usually benign, consider 2- and 4-year follow-up in selected high-risk patients (5A) | ✓ |
| subsolid_multiple_ge6 | ground-glass + part-solid, multiple, 6to8 + gt8 | "CT at 3–6 months. Subsequent management based on the most suspicious nodule(s)" | ✓ |

Every outcome carries the exclusion caveat: p3 Table note (screening, immunosuppression, known primary cancer) plus
p2 (not for patients under 35). ✓

Golden cases: 26 (1 source, 25 ours); every outcome reached; edges 5.4/5.5 and 8.4/8.5 tested on solid and subsolid
rows; 4 cases assert `needed`. The only worked example usable as a case is Figure 14 (p11: multiple subsolid nodules
incl. a 10-mm ground-glass nodule, "initial follow-up would be appropriate in 3–6 months"). Figures 1, 2 and 5 state
"no follow-up" for benign or perifissural nodules, which sit outside the table (carried as pitfalls). Figures 9, 10,
12 illustrate follow-up course, not a table lookup.

## Jev `check` items (16 of 85 below 0.5)

| field | resolution |
|---|---|
| reference.def.size | ✓ p4–5: average of long and short axes on the same image showing the greatest dimensions; nearest whole millimetre; <6 mm = rounded 5 mm or less. Text spans the p4/p5 column break. |
| reference.pit.volume | ✓ p5: 100 and 250 mm³ used for volumetry instead of 6 and 8 mm. "Not supported here" is our product note. |
| management.row4 | ✓ p3 part A, single, low risk, >8 mm. Low score is table layout in pdftotext. |
| management.row14, 16, 17, 21, 22, 23 | ✓ p3 part B, checked on the page image. Jev cannot see that "≥6 mm" covers both our `6to8` and `gt8` bands, nor that the "Multiple" subsolid row is shared by ground-glass and part-solid. |
| outcome.subsolid_multiple_lt6 | ✓ p3 part B, Multiple, <6 mm, verbatim in substance. |
| reference.def.highrisk_factors | ✓ p12 (high-risk factors; 30 pack-years and quitting within 15 years as the NLST threshold, "indicative of high-risk status in patients with solid nodules"). Wording tightened after the Jev run to follow the source ("quitting within the past 15 years"); evidence.md shows the earlier wording. |
| reference.def.subsolid | ✓ p10–11: components still visible on mediastinal (soft-tissue) window with a sharp filter are solid. |
| reference.pit.mixed | Boundary: the table has no mixed row; p7 says a larger or more suspicious nodule should guide management. Our sentence states only that. See For Hassan. |
| reference.pit.benign | ✓ p4 Figures 1–2 (hamartoma, calcified granuloma: no further CT follow-up); recommendations are for noncalcified nodules (p5, p7). |
| reference.pit.thick | ✓ p4: after a thick-section first scan, consider a short-term thin-section follow-up as the baseline. |
| reference.pit.partsolid | ✓ p10 (solid component ≥6 mm: 3–6 month CT; solid component >8 mm, growing solid part or suspicious morphology: PET/CT, biopsy or resection, 4C). "Table size is the whole nodule" is our reading; see For Hassan. |

## For Hassan

1. **Exclusions are pitfalls plus a caveat on every outcome, not inputs** (as the brief asked): screening, age under 35,
   immunocompromise, known primary cancer are never asked on the card, so the pack will answer for an excluded patient
   and rely on the caveat.
2. **Outcomes split where the table's comments differ.** "No routine follow-up" is four outcomes (solid single low,
   solid multiple low, single GGN, single part-solid) and "Optional CT at 12 months" two, because each row carries a
   different comment. 15 outcomes, not one per distinct recommendation string.
3. **The solid single <6 mm comment sits on the low-risk row too.** The table's comment cell spans both single rows
   and speaks of "patients at high risk"; we carry it on both outcomes as the table does.
4. **Part-solid size is taken as the whole nodule; the solid component is not an input.** The ≥6 mm solid-component
   condition is a caveat on `psn_single_ge6`, and the >8 mm solid-component escalation (4C) is a pitfall. Make solid
   component size an input if the card should branch on it.
5. **Mixed solid and subsolid multiple nodules have no table row.** The radiologist picks the type of the most
   suspicious nodule.
6. **Rounding half up:** 5.5 mm falls in 6–8 mm and 8.5 mm in >8 mm. The source says only "nearest millimetre".
7. **Engine behaviour seen:** a solid single >8 mm nodule with risk unknown returns no outcome (`possible` =
   [solid_single_gt8], `needed` = []), because a table step waits for every key. The host should treat a single
   possible outcome as settled, or the engine could. Not changed here.
8. **Source copy:** the RSNA publisher PDF from a third-party mirror, and it is the online-ahead-of-print version
   (pages 1–16), not the issue-paginated 284:228–243. Substance should be identical; worth swapping for the issue PDF
   if you have institutional access.
9. **Figure 14 as the source case:** its most suspicious lesion is a part-solid nodule of unstated size, so the case
   uses the stated 10-mm ground-glass nodule; the outcome is the same for either type.
