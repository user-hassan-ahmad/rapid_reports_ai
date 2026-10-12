# Review: ao-spine-thoracolumbar@2013.1 (tier 2 reference card)

Source: Vaccaro AR et al. Spine 2013;38(23):2028-2037, DOI 10.1097/BRS.0b013e3182a8a381. Filed copy is a mirror of the publisher PDF with a ResearchGate cover page (sha256 6e9b8905...0b10b). Locator pages are 1-based PDF pages: p1 = cover, p2 = journal 2028, p4 = 2030 (classification starts), p8 = 2034 (Table 1, N3 to M2), p10 = 2036 (conclusion). Text file is plain `pdftotext` (not `-layout`; the layout text interleaves the two columns). Figures are schematic drawings; the algorithm appendix and CT images are supplemental online content and not filed.

## Pack type
Tier 2 reference card: a classification with no management or prognosis per grade (the paper says the Spine Injury Score is yet to be defined and no absolute surgical recommendation can be given). No inputs, logic, outcomes or cases.

## Checklist

| item | source | |
|---|---|---|
| def.A, A0 to A4, tab.morph rows A0-A4 (endplates involved, posterior wall) | p4-5, Type A text and Figures 3-7 legends | ✓ |
| def.B, B1 to B3, tab.morph rows B1-B3 | p6-7 | ✓ |
| def.C, tab.morph row C (no subtypes) | p7 | ✓ |
| def.coding: A and B1 by vertebral level; B2, B3, C by motion segment | p4 | ✓ |
| def.multi: multilevel listing | p4-5 | ✓ |
| def.N0 to N4, NX and tab.neuro (N4 = ASIA A) | p7-8 | ✓ |
| def.M1, def.M2 and tab.mod | p8 | ✓ |
| tab.kappa: A0 1.0, A1 0.59, A2 0.50, A3 0.45, A4 0.58, A 0.72, B1 0.65, B2 0.34, B3 0.41, B 0.58, C 0.70 (n(%) column omitted: raters' estimated distribution, not part of the classification) | p8 Table 1 | ✓ |
| sum.1 to sum.5, pit.* | p4, p8, p9, p10 as located | ✓ |

## Gate 5 flags (7 below 0.5), each read against the source

sum.1 (0.28): composite of the opening list of 3 parameters (p4) and the N and M definitions (p7-8); confirmed. tab.morph (0.48) and tab.kappa (0.46): table cells re-read against the page text and Table 1; confirmed. pit.mri (0.42): kappa 0.34/0.41 on p8 and p9, PLC/MRI unreliability on p9, B1 vs B2 distinction on p10; confirmed. pit.nomgmt (0.29): composite of Conclusion p10 and the Spine Injury Score paragraph p8; confirmed. pit.validation (0.42), pit.sep (0.44, Figure 9 legend p6 and Type C text p7), pit.hinge (0.44, p7 plus ankylosed-spine discussion p10): confirmed. No corrections.

## For Hassan

1. Library note: the card carries the 2013 consensus paper only. Later AO Spine updates or the supplemental algorithm are not in the filed source and are not stated. Reports using "AO type A3" and similar are covered; reports using sub-modifiers beyond M1, M2 are not.
2. Table 1's estimated case-count column (n and %) was left out; only the kappa column is carried. Say if you want it.
3. Aliases (AOSpine, AO classification, "AO type A fracture" and similar) are library additions of how reports name the system; "TLICS" and "Magerl" are deliberately not aliases (different systems).
4. `applies_to.region` is `spine` (the library's existing vocabulary has no thoracolumbar value); the thoracolumbar scope is carried by `finding_type` and a pitfall. DECISION: confirm `spine` is acceptable for matching.
5. The source gives no treatment rule or score per grade; none is added. The authors' attributed expectations (M1, ankylosed-spine extension injuries, type C; p10) are carried as attributed statements in sum.4 and pit.nomgmt.
6. Independent read (clinical-read.md) fixes applied: no-treatment wording narrowed and authors' expectations added; display labelled as the 2013 consensus paper (status field left as the library convention); M1 qualifier 'seems stable from a bony standpoint'; A1 canal intact and A3 spinal canal; pit.sep split B versus C; modality XR added; kappa table title notes type A subtype kappas are single-vertebra cases only. Gate 5 re-run.
