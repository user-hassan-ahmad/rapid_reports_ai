# Gate 6: hand read, salter-harris@1963.1

Read side by side with the PDF page images (Read tool, PDF pages 15-18 and 20-22) and `sources/57a9...4eee.txt` (OCR, which
is noisy: every quote below was checked against the page images). Locator pages are 1-based PDF pages of the 36-page scan;
journal page = PDF page + 586 (PDF 15 = JBJS 45-A p.601). Page-less lecture, so `section` carries the journal page.

## Pack type

Tier 1 lookup: one dictated `sh_type` enum (I to V) -> `table` -> outcome. The paper gives a prognosis and reduction
account for every type, so it is not a tier 2 card. No management is invented: each recommendation is the paper's own
reduction or treatment line, with the paper's growth prognosis. The paper is an instructional lecture from 1963 on the
growing skeleton and describes five types only.

## Input

| item | source | |
|---|---|---|
| `sh_type` I, II, III, IV, V | PDF 15-21, Classification of Epiphyseal-Plate Injuries, Types I-V | ✓ |
| no `absent` / `not_assessable` states | the paper recognises neither | ✓ |
| no eligibility inputs | the paper has no scope or exclusion clause that names a patient fact; carried as `pit.scope` (For Hassan 2) | ✓ |

## Table rows (5) and outcomes (5)

| outcome | source | |
|---|---|---|
| sh1_separation | PDF 15-16 (j601-602): complete separation, no fracture, growing cells stay with the epiphysis; reduction not difficult; prognosis excellent unless epiphysis entirely covered by cartilage (upper femur), blood supply then frequently damaged | ✓ |
| sh2_fracture_separation | PDF 16-17 (j602-603): line along plate then out through metaphysis, Thurston Holland sign; reduction relatively easy to obtain and maintain; prognosis excellent if circulation intact "as it nearly always is" | ✓ |
| sh3_partial_epiphysis | PDF 18 (j604): intra-articular, joint surface to weak zone of plate then along the plate to its periphery; accurate reduction essential for the joint surface, open operation may be necessary; prognosis good if blood supply to the separated portion intact | ✓ |
| sh4_through_plate | PDF 18-20 (j604-606): intra-articular, through epiphysis, full plate thickness and part of metaphysis; perfect reduction essential, open reduction always necessary unless undisplaced; bad prognosis unless plate completely realigned (PDF 22, j608-609) | ✓ |
| sh5_crush | PDF 20-22 (j606-608): very severe crushing force through the epiphysis to one area of the plate; weight-bearing avoided three weeks in the hope of preventing the almost inevitable premature cessation; prognosis decidedly poor, worst | ✓ |

## Caveats

| caveat | outcomes | source | |
|---|---|---|---|
| shearing or avulsion force; birth injury, early childhood, pathological separations | I | PDF 15-16 | ✓ |
| wide displacement uncommon, periosteum usually intact | I | PDF 16 | ✓ |
| entirely cartilage-covered epiphysis: blood supply frequently damaged, premature closure | I | PDF 16 | ✓ |
| commonest type, usually over ten years old; periosteum torn on convex side | II | PDF 16-17 | ✓ |
| blood supply particularly vulnerable in head of femur and head of radius | II, III | PDF 22 (j608) | ✓ |
| uncommon, usually upper or lower tibial epiphysis, intra-articular shearing force | III | PDF 18 | ✓ |
| commonest example lateral condyle of humerus | IV | PDF 19 (j605) | ✓ |
| bone union across the plate gives local premature cessation if not accurately realigned | IV | PDF 20 (j606) | ✓ |
| uncommon, one-plane joints (ankle, knee), severe abduction or adduction injury | V | PDF 20-21 | ✓ |
| little displacement, first radiograph gives little indication, may be dismissed as a sprain | V | PDF 21 | ✓ |

## Gate 5 flags

The remaining flags are all page-span artefacts: gate 5 reads only the cited page, and the fact sits on the adjacent page.
Confirmed by own reading.

| flag | resolution |
|---|---|
| `type.row1`-`row4` (0.04-0.22) | The row text combines the type definition with its treatment line, which sit on neighbouring pages (e.g. Type II: line on PDF 16-17, prognosis PDF 17). Each clause confirmed on the page images. |
| `reference.tbl.types`, `reference.tbl.management`, `reference.def.factors`, `reference.pit.estimate`, `reference.pit.five` | Summaries that span PDF 15-22 (types) and 22-26 (factors, treatment principles); every cell checked against the page images. |
| `sh2.caveat1`, `sh3.caveat1` | "Blood supply particularly vulnerable in the head of the femur and the head of the radius" is on PDF 22 (j608), the Factors in Prognosis paragraph; the outcome locator names the definition page. Correct as read. |

## For Hassan

1. The paper has types I to V only (the Rang type VI is not in this source and is not in the pack); a fracture the radiologist cannot place in I to V gets no outcome, so the card asks for a type rather than guessing.
2. No eligibility input: the paper gives no age bound or other exclusion clause. The pack applies to physeal fractures dictated with a type; use in a skeletally mature patient is not addressed by the source.
3. (SUPERSEDED by Hassan's decision, see Revision) the recommendation line stated the 1963 orthopaedic management (reduction route, three weeks non-weight-bearing for type V) because that is the only management the paper gives; it is a surgical lecture, not an imaging-follow-up recommendation. Confirm you want these lines to reach a radiology report, or reduce each recommendation to the prognosis half.
4. The paper's prognosis words ("excellent", "good", "bad", "decidedly poor") are kept as the paper states them; it gives no percentage per type (only about 10 per cent significant growth disturbance overall, held in the reference summary).
5. `applies_to.region` (shoulder, elbow, wrist, hand, hip, knee, ankle) is a library choice drawn from the sites the paper discusses; the paper covers the extremities generally and states no list.
6. The DOI `10.2106/00004623-196345030-00019` was checked against Crossref (JBJS Am 45(3):587-622).

## Revision after the independent read (clinical-read.md) and Hassan's decision

- Recommendation is now the 1963 growth prognosis only, hedges kept (conditional phrasing for III, IV). The 1963 treatment lines
  are in `reference.tbl.management`, titled "for reference only and not for the report"; the six-month bilateral radiograph
  follow-up is in `reference.def.followup`, attributed to the paper, not in any recommendation. I1, I2 resolved.
- Every outcome carries three added caveats: (a) currency, "1963 prognosis; site-specific risk may differ" with no later source
  cited (DECISION taken by Hassan; no modern source is on disk); (b) scope, growing physes only, traction apophyses such as
  the medial epicondyle excluded (PDF 1, j587); (c) age at injury modifies the prognosis (PDF 22-23, j609). I3, I4, I5 resolved.
- M1 (III wording) gone with the treatment text; M2 delayed reduction added to the IV row; M3 Type V caveat added (lower tibia
  commonest site, varus force, nature may not be suspected until closure; PDF 31, j617); M5 retrieved date set to 2026-10-12;
  M8 modality now XR, CT, MRI (library choice, listed here as an addition); M4, M6, M7 noted, no change.
- I6: the engine rejects values outside the enum ("VI", "III/IV"), so golden cases cannot assert them; an unsettled dictation
  falls to the existing "not stated" and "unknown" cases, which assert `needed: [sh_type]`. Arabic numerals are a settle-model
  matter (`how_stated` says Roman or Arabic) and cannot be tested by a golden case.
- Gate 5 after revision: the added common caveats score low because they cite library or other-page facts; each checked by
  own reading against the pages named above.
