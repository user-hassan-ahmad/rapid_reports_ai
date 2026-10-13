# Gate 6: hand read, aspects@2000.1 (tier 2 reference card)

Read against the PDF page images (PDF pages 2 and 3) and `sources/61e2fef8…805e.txt` (the text file is named by the PDF's
sha256). Source: Barber PA et al., Lancet 2000;355:1670-4, DOI 10.1016/S0140-6736(00)02237-6, a third-party mirror of the
publisher PDF, retrieved 2026-10-12. Locator pages are 1-based PDF pages: p1 = journal 1670, p2 = 1671 (Figure 1),
p3 = 1672 (Figure 2, Table 1), p4 = 1673 (Table 2, Discussion).

## Pack type

Tier 2 reference card (Hassan's decision; the independent read, `clinical-read.md`, and the skill's rule "grade with no
management attached" agree). No inputs, logic, outcomes or cases. Prognosis lives in reference fields only, bounded by the
study cohort. The first version was tier 1; every fix from the read is applied below.

## Checklist

| item | source | |
|---|---|---|
| sum.1, sum.2, def.regions_*, def.change, def.levels, tab.regions | p2 Procedures and Figure 1 legend | ✓ |
| def.10 without "(normal CT)": a score of 10 means only no change in the ten regions | p2; converse not stated by the source | ✓ read fix |
| def.0, def.8_10, def.0_7: region counts by arithmetic (10 minus score) | p2 "1 point is subtracted ... for each of the defined regions" | ✓ |
| sum.3 / pit.cohort: 156 patients, IV alteplase within 3 h, March 1996 to May 1999, 10 mm non-contrast CT | p2 Procedures; p3 Results | ✓ prominent, read fix |
| sum.4: 7 or less versus above 7 (scores 8 to 10 together) | p3 Statistics/Results; above-7 group includes 10 | ✓ read fix |
| tab.discrimination: sens/spec, OR 82 (23-290), OR 14 (1.8-117) with the events 62/65 vs 18/89, 9/65 vs 1/91 | p3 Table 1 and text, under corrected labels | ✓ read fix |
| pit.ci: OR 14 on 10 events; 1% is 1 of 91; NINDS placebo 0.6% | p4 Discussion; p3 Table 1 | ✓ read fix |
| pit.limit: study limitation only, no directive | p4 Discussion | ✓ read fix |
| pit.anterior incl. pc-ASPECTS not covered | p2 Patients; p3 Results | ✓ |
| pit.threshold, pit.ten, pit.integer, pit.agreement | p2 Statistics; p2; p2; p4 Table 2 | ✓ |

## Gate 5 flags (7 below 0.5), each read against the source

- `sum.3`, `pit.cohort`: facts spread over p2 (patients, slice thickness, CT) and p3 (156, dates); confirmed on both pages.
- `def.8_10`, `def.0_7`, `pit.ten`: derived by arithmetic or as the converse limit; not a single source sentence (see For Hassan 2).
- `tab.regions`: figure legend, confirmed on the page-2 image.
- `pit.ci`: 10 events, 1 of 91, CI and 0.6% are across p3 and p4; confirmed on both.

## For Hassan

1. Table 1's printed row labels are inverted against the text and Figure 2 ("7 (n=89)" is really the above-7 group). The card follows the text and figure; counts and the 1 of 91 are quoted under the corrected labels, as the read verified (statistics reproduce only under the swap). DECISION: confirm quoting the counts.
2. Library addition: the 8-10 and 0-7 definitions and region counts are our arithmetic from the one-point-per-region rule; the source states only the 7-or-less versus above-7 split.
3. Alias: the bare "ASPECTS" alias is kept (Hassan's ruling: "ASPECTS 8" dictations matter more than a pc-ASPECTS collision); the pc-ASPECTS pitfall stays and the matcher's applicability gate decides fit.
4. Integer-only scoring is a pitfall (the source defines no fractional score); the earlier half-up rounding was dropped.
5. The source gives no management for any score; the thrombolysis-exclusion warning is kept only as the study limitation `pit.limit`. Later ASPECTS use (thrombectomy thresholds) is outside this source and not in the card.
