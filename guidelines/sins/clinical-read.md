# Clinical read: sins@2010.1 (tier 1 lookup on the dictated total, with reference card)

Independent read against the filed sources: S1 Fisher CG et al., Spine 2010;35:E1221-E1229 (sources/73125e5e….pdf and .txt; PDF pages 3, 4, 5 and 8 viewed as page images, covering Tables 1-7, the scoring paragraph, cases 1-3 and Table 8 by text) and S2 NICE NG234 Recommendations chapter (sources/7a6b8806….txt). Read-only; nothing in the pack was edited.

## Verdict

Clinically faithful. No Critical findings. Every component score, level list, band edge, the band labels and the "7 to 18 warrant surgical consultation" line match the source, and the lookup cannot reach a wrong band for any whole-number total from 0 to 18. One Important finding: review.md's For Hassan list is partly stale and contradicts the shipped pack. The Minor findings are about wording and where caveats sit; none changes an outcome.

## Logic and outcomes

| item | result |
|---|---|
| input `sins_total` (number, 0-18, lesion scope, never computed) | Matches "minimum score is 0 and maximum is 18" (p4, E1224). Lesion scope matches "scores be assigned separately" (p8, E1228). |
| band b0_6 (≤ 6) | Matches "Scores of 0 to 6 denote 'stability'" (p4). |
| band b7_12 (> 6, ≤ 12) | Matches "7 to 12 denote 'indeterminate (possibly impending) instability'" (p4). |
| band b13_18 (> 12) | Matches "13 to 18 denote 'instability'" (p4). |
| table step | One row per band, no default row, complete. |
| outcome b0_6 | Classification correct. Leaving the recommendation empty is faithful: the source gives no management for 0-6. |
| outcome b7_12, b13_18 recommendation | "Patients with SINS 7 to 18 warrant surgical consultation" is verbatim in meaning, and the hedge is kept. |
| caveat "one component ... deficit or high-grade cord compression indicate surgery regardless of score" | Faithful to p8: "If a patient has neurologic deficit or high-grade spinal cord compression without deficit, surgery is certainly indicated regardless of the SINS score." See finding 6. |

## Reference card

| item | result |
|---|---|
| def.location, Table 2 rows | Match the Table 2 image (Occiput-C2, C7-T2, T11-L1, L5-S1 = 3; C3-C6, L2-L4 = 2; T3-T10 = 1; S2-S5 = 0). |
| def.pain, pain rows | Match Table 3 image. The text adds "upright posture" to mechanical pain (finding 5). |
| def.bone, bone rows | Match Table 4 image (lytic 2, mixed 1, blastic 0). The text conflicts with the table (finding 4). |
| def.alignment, alignment rows | Match Table 5 image and footnote (4/2/0; prior imaging or upright versus supine). |
| def.collapse, collapse rows | Match Table 6 image (>50% collapse 3, <50% collapse 2, no collapse with >50% involved 1, none of the above 0). |
| def.posterior, posterolateral rows | Match Table 7 image (bilateral 3, unilateral 1, none 0; facet, pedicle or CV joint fracture or replacement). |
| tab.components | All 20 rows equal Table 8. |
| tab.bands | Correct. The "Not stated as warranted" cell for 0-6 is worded carefully and is accurate. |
| tab.cases | Component sums correct: case 1 = 1+3+2+2+3+3 = 14, case 2 = 3+3+2+4+1+1 = 14, case 3 = 1+1+2+0+1+1 = 6. The readings are as printed (case 1 "deemed as indeterminate instability", case 2 "unstable situation", case 3 "suggesting a stable lesion" and "not based on spinal stability alone"). |
| def.instability | Matches the SOSG definition (p6, E1226). |
| sum.1-sum.4 | Agree with p4 and p8. |
| sum.5, pit.ng234 | Agree with NG234 1.9.1 ("Consider using a validated spinal stability scoring system with good evidence of accuracy (for example, the Spinal Instability Neoplastic Score) alongside clinical assessment ...") and 1.9.3. The filed chapter has no SINS thresholds. |
| pit.min | Verbatim: "a minimum score of 2 and a maximum score of 18" (p8), against "minimum score is 0" (p4). |
| pit.multi, pit.notalone, pit.unscored, pit.status | Agree with p8 Discussion and Conclusion. |
| pit.collapse | Correct. The text gives 0 only for "no vertebral body involvement"; the table gives 0 for "none of the above"; exactly 50% is undefined. |
| pit.rigid | Correct (Table 2 and Table 8 say S2-S5; the Table 2 footnote says S2-S4). |
| pit.alignment | Correct. |
| Locators | Page numbers check out (Table 2 p3; Tables 3-6 and the scoring paragraph p4; Table 7 and cases 1-3 p5; definition p6; Table 8, Discussion and Conclusion p8). |

## Golden cases

- Edges tested on both sides (6/7, 12/13), plus the extremes 0 and 18, and two `needed` cases (absent, explicitly unknown). Every outcome is reached. This meets step 4.
- Paper cases: 14 → b13_18 (twice) and 6 → b0_6 follow the band text. For case 1 this is deliberately against the paper's own reading (finding 3).
- There is no out-of-range case (for example 19 or -1). This is optional if the gate enforces `min_value`/`max_value`.

## Findings

1. **Important.** review.md For Hassan is partly stale. Item 1 says "The card is built tier 2 as asked" and asks whether to make it tier 1, but the pack is already a tier 1 lookup. Item 7 says the NG234 wording is "not in the card", but sum.5 and pit.ng234 carry it. Hassan decides from this list, so remove or rewrite items 1 and 7 to match the pack. The note "publisher PDF mirror in sources3/sins" should name the real path, `sources/`.
2. **Minor.** The b7_12 outcome's third caveat ("case 1 (SINS 14) ... label for 13 and 14 is not consistent") concerns totals of 13 and above, so it is noise on a 7-12 card. Move it to b13_18 or pit.band1318 only.
3. **Minor.** pit.band1318 and the b13_18 caveat say "13 and 14" and tell the radiologist to "state the number rather than relying on the label". The source shows the conflict only at 14 (case 1), and the advice is ours, not the paper's. Say "at 14 (case 1)" and label the advice a library addition per AUTHORING-RULES. The paper case 1 golden case could note in its name that it asserts the band text over the paper's reading.
4. **Minor.** There is an unrecorded text-versus-table conflict. The Bone Lesion Quality text (p4) says blastic (sclerotic) lesions score 1 and lytic 2, with no mixed category; Tables 4 and 8 give blastic 0, mixed 1, lytic 2. The pack correctly follows the tables, but the conflict belongs in a pitfall and For Hassan, per TRAPS "figure versus text".
5. **Minor.** def.pain omits "upright posture" from the mechanical pain text ("pain with movement, upright posture, or loading of the spine"). Add it for fidelity.
6. **Minor.** "Surgery is indicated regardless of score" with neurological deficit or high-grade cord compression is the 2010 paper's position ("certainly indicated"). NG234 frames decompression or stabilisation as "consider" (1.11.7) within an MDT plan (1.11.1). The caveat is attributed to the authors, which is acceptable. Suggest pit.ng234 note this difference too, so it is not read as current UK practice.
7. **Minor.** Fractional totals (for example 6.5) silently band into 7-12 (For Hassan 8). Harmless in practice. If the schema supports an integer constraint, use it; otherwise accept and keep item 8.
8. **Minor.** NG234 filed under role `explanatory` is a slight stretch of the role ("reviews and explainers"), and sum.5/pit.ng234 put another issuer's recommendation inside a single-issuer pack. This is acceptable because it shapes reference text only and NG234 has no SINS logic to make a sibling pack from. NG234 1.5.10 (multiplanar CT to assess spinal stability) could be a useful extra reference line for radiologists. It is optional.

## For Hassan verdicts

1. Tier 1 decision: **stale.** The pack is already tier 1, with the required caveats (one component, surgery regardless with deficit or cord compression, per lesion) present on every outcome. Rewrite or drop the item (finding 1).
2. 13-14 label conflict: **agree** with following the band text (it is the paper's definitional statement; case 1's wording is an inconsistency in an illustration) and flagging it. **Disagree** with extending it to 13, and with the unlabelled "state the number" advice on the b13_18 outcome (finding 3).
3. Minimum 0 versus 2: **agree.** The tables allow 0 for every component.
4. Rigid S2-S5 versus S2-S4: **agree.** Table 2 and Table 8 both say S2-S5.
5. Collapse at exactly 50% and "none of the above": **agree.** Nothing is invented and the pitfall is accurate.
6. Aliases and the "Not stated as warranted" cell: **agree.** The cell is accurate and does not claim consultation is unnecessary.
7. 2010 paper only / NG234 not in card: **stale** in its second half (finding 1). The first half (no later validation papers) is fine.
8. Whole-number band edges: **agree** (finding 7 is optional hardening).
9. DECISION, empty recommendation for 0-6: **agree.** The paper attaches no management to 0-6, and writing "no consultation needed" would overstate it. Case 3 (SINS 6, still worked up for surgery) shows why. The b0_6 caveats already say SINS is not a decision rule.
10. Gate 5 flags on caveats: **agree.** The p8 caveat is confirmed against the PDF. Consider adding the p8 locator for that caveat if the schema allows per-caveat locators.
11. DECISION, NG234 role (explanatory, reference only, not on outcomes): **agree.** NG234 attaches no action to any SINS value. Its actions (MSCC coordinator 1.3.2-1.3.4, MDT plan 1.11.1) are triggered by symptoms, signs or an intended intervention, so putting them on a band outcome would invent a link. Verified against the filed text.
12. Soft NG234 "consider" versus the paper's "warrant": **agree** with keeping the paper's wording on outcomes and stating the difference in pit.ng234.
13. NG234 filing details: **agree**, page-less, with section locators.
