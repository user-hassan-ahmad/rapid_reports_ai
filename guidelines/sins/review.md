# Review: sins@2010.1 (tier 1 lookup on the dictated total, with the reference card)

Source: Fisher CG et al., Spine 2010;35:E1221-E1229, DOI 10.1097/BRS.0b013e3181e16ae2 (Crossref confirmed title, volume, pages), publisher PDF mirror (filed in this pack's sources/) (sha256 73125e5e...d4133). Locator pages are 1-based PDF pages: p3 = Table 2, p4 = Tables 3-6 and the scoring paragraph, p5 = Table 7 and cases 2-3, p6 = instability definition, p8 = Table 8 and Discussion. Tables 2-7 read from the page images; Table 8 from the text and checked against Tables 2-7.

## Pack type

Tier 1 lookup per Hassan's decision (no calculator): one `sins_total` number input (0 to 18, lesion scope, never computed from components), a band step, a table step to three outcomes. The full reference card is kept. The paper attaches management only to 7 to 18 (surgical consultation); the 0 to 6 outcome has an empty recommendation. Second source S2 (NICE NG234, 2023) is filed as `explanatory` (page-less HTML; section locators) and is cited only in the reference card.

## Checklist

| item | source | |
|---|---|---|
| def.location and tab.components location rows (3/2/1/0 with level lists) | Table 2 p3, Table 8 p8 | ✓ |
| def.pain, pain rows (3/1/0) | Table 3 p4 | ✓ |
| def.bone, bone rows (2/1/0) | Table 4 p4 | ✓ |
| def.alignment, alignment rows (4/2/0) | Table 5 p4 | ✓ |
| def.collapse, collapse rows (3/2/1/0) | Table 6 p4 | ✓ |
| def.posterior, posterolateral rows (3/1/0) | Table 7 p5 | ✓ |
| tab.components equals Table 8 row for row (20 rows) | Table 8 p8 | ✓ |
| tab.bands: 0-6 stability, 7-12 indeterminate (possibly impending) instability, 13-18 instability; 7-18 warrant surgical consultation | scoring paragraph p4 (image read) | ✓ |
| tab.cases arithmetic: case 1 = 14, case 2 = 14, case 3 = 6 | cases p4-p5 | ✓ |
| sum.3, sum.4, pit.multi, pit.notalone, pit.unscored, pit.status | Discussion and Conclusion p8 | ✓ |
| def.instability | p6 Discussion | ✓ |

| logic: band edges 6 and 12 inclusive (0 to 6, 7 to 12, 13 to 18), table to b0_6 / b7_12 / b13_18 | scoring paragraph p4 | ✓ |
| outcomes b0_6, b7_12, b13_18: labels and the 7 to 18 consultation line as the paper words it | p4 | ✓ |
| cases.json: every outcome, edges 6/7 and 12/13, 0 and 18, the paper's cases (14, 14, 6), two `needed` cases | p4-p5 | ✓ |
| sum.5, pit.ng234 against NG234 1.9.1 and 1.9.3 | NG234 section 1.9 | ✓ |

## Gate 5 flags (after rewording, see evidence.md)

Flags on tab.cases, tab.components, pit.min, pit.collapse, pit.status are low because the claims are table cells, a cross-page conflict or absence statements. Each was read against the PDF and page images: tab.components matches Table 8; case sums are correct; the min-of-2 sentence is on p8 verbatim. pit.collapse and pit.status were reworded to stay within the text (collapse: the table and text differ on what scores 0; status: the authors call for more validation, no claim about what the paper omits).

## For Hassan

1. RESOLVED: Hassan chose a dictated-total tier 1 lookup (no calculator); the paper's 7 to 18 consultation line is on the outcomes with the authors' caveats (one component of the work-up; surgery regardless of score with deficit or high-grade cord compression; per-lesion scoring).
2. DECISION (label conflict at 14): the band text calls 13 to 18 "instability"; case 2 (14) is "unstable" but case 1 (14) is read as "indeterminate instability". The pack follows the band text (golden case named accordingly) and flags it at 14 only (pit.band1318, b13_18 caveat). "Quote the number as well as the label" is a library addition.
3. Minimum score: 0 in the scoring paragraph, 2 in the Discussion. Followed the tables (0 possible); listed as pit.min.
4. Table 2 says rigid = S2 to S5, its footnote says S2 to S4. Followed the table; listed as pit.rigid.
5. Collapse of exactly 50% is undefined, and "none of the above" (Table 6) versus "no body involvement" (text) differ for less than 50% involvement without collapse. Listed as pit.collapse; no rule invented.
6. Library additions: the aliases (bare "SINS", "SINS stable/indeterminate/unstable") are how reports name the system. The "Not stated as warranted" cell for 0 to 6 is our reading that the source states consultation only for 7 to 18; the source does not say consultation is not warranted at 0 to 6.
7. The card uses the 2010 paper; NICE NG234 (2023) is cited in the reference card only (sum.5, sum.6, pit.ng234; see 11 to 13). Later SINS validation papers are not included.

## Added with the lookup (second pass)

8. Band edges: scores are whole numbers, so the bands are written as 6 inclusive and 12 inclusive (greater than 6 up to 12; greater than 12) rather than 6.5 and 12.5. A fractional total such as 6.5 would fall in 7 to 12; it cannot be a real SINS.
9. DECISION (no management for 0 to 6): that outcome's recommendation is empty, since the paper gives consultation only for 7 to 18. Say nothing for 0 to 6 rather than "no consultation needed".
10. Gate 5 flags on the outcome caveats (0.07 to 0.38) are library statements: "this card does not compute SINS" is ours, and the "one component, surgery regardless of score with deficit or high-grade compression" caveat is from the Discussion on p8 while the outcome locator is p4. Confirmed against the PDF.
11. NG234 (2023) section 1.9: 1.9.1 "Consider using a validated spinal stability scoring system ... (for example, the Spinal Instability Neoplastic Score) alongside clinical assessment of risk of spinal instability to inform treatment decisions"; 1.9.3 "Only use a scoring system as part of a full clinical assessment ..." It names no score thresholds and no action per band. Its action wording does not belong next to the paper's: the MSCC coordinator contacts (1.3.2 to 1.3.4) are triggered by symptoms and signs, and the spinal-surgeon discussion (1.11.1) is for before an invasive intervention in the MSCC team, none linked to a SINS value. DECISION: NG234 is filed as `explanatory` and cited only in reference (sum.5, pit.ng234), not in outcomes, because the authoring rules say one issuing body per pack and explanatory sources must not shape outcomes. If you want NG234 wording on the outcomes, it needs its own sibling pack or a rule change.
12. Difference from the paper: NG234 is a soft "consider ... alongside clinical assessment" while the paper says 7 to 18 "warrant surgical consultation". The card keeps the paper's wording on the outcomes and states the difference in pit.ng234.
13. NG234 filed as the Recommendations-chapter HTML (nice.org.uk/guidance/ng234/chapter/Recommendations), retrieved 2026-10-12, page-less.

## Read fixes (clinical-read.md)

14. Fixed all 8 findings: For Hassan 1 and 7 and the sources path updated; case-1 caveat removed from b7_12; conflict limited to 14 and the advice labelled a library addition; blastic text-versus-table conflict recorded (pit.blastic; the Bone Lesion Quality text says blastic 1, lytic 2, no mixed; the tables say 0/1/2, tables followed); "upright posture" added to def.pain; pit.ng234 notes NG234 surgery is 'consider' within an MDT plan (1.11.1, 1.11.7); the schema has no integer constraint, so pit.integer records that totals are whole numbers (supersedes item 8's silence); NG234 1.5.10 added as sum.6; case 1 renamed to say it follows the band text.
