# Independent clinical read, bta-thyroid-u-grading@2014.1

Reader: independent agent, read-only, 2026-10-12. Source: S1 on disk (`sources/43e9…727c.pdf` and `.txt`). I viewed
PDF p30 (Fig. 4.1) and p31 (Fig. 4.2) as images; I re-rendered Fig. 4.2 at 250 dpi to trace each arrow. I read
p25 (Ch 3.7), p28–31 (Ch 4), p8 and p15 (scope), p75 (14.1) and p78 (Ch 15) in the text file. Every page number
below is a 1-based PDF page, matching the pack's locators.

## Verdict

**One Important finding is open, so the pack is not ready to ship.** The grade table, all five outcomes and
almost all of the reference content match the source. The open finding is For Hassan 5: Fig. 4.2 does not send
Thy2 cytology to repeat FNAC, so the reason review.md gives for the U5 caveat is wrong. The U5 caveat also leaves
out the MDT discussion that Fig. 4.2 offers as the alternative. The other findings are Minor.

## Findings

| # | Severity | Field | Finding | Suggested fix |
|---|---|---|---|---|
| 1 | Important | `u5_malignant.caveats[2]`; review.md caveat row and For Hassan 5 | Fig. 4.2 (p31) only sends **Thy1** to "Repeat FNAC". **Thy2** goes to "Review clinical and US level of suspicion". From there, low suspicion leads to "No follow-up required", and high suspicion leads to "Repeat US guided FNAC **or MDT discussion**". review.md says Fig. 4.2 has "Thy2 → repeat FNAC" in the U3–5 branch, which is wrong. The text rule (4.5 iv, p29) covers Thy2 with "indeterminate or suspicious" US features, so it supports U3 and U4 directly. For U5 the support is inference: a U5 nodule is at least suspicious, Fig. 4.2's high-suspicion branch applies, and 4.4 v sends discordance to the MDT. So the U5 caveat may say repeat FNAC, but only with the MDT alternative next to it. | U5 caveat: "Non-diagnostic (Thy1) cytology: repeat FNAC. Benign (Thy2) cytology despite a malignant appearance: repeat ultrasound-guided FNAC or discussion at the MDT." Correct the Fig. 4.2 description in review.md (caveat table and For Hassan 5). |
| 2 | Minor | `inputs.u_grade.how_stated` | The input has `scope: "lesion"`, but the hint says "in a multinodular thyroid, the score of the most suspicious nodule". 4.4 ii is a rule about what the report records. It does not say that only the most suspicious nodule matters for management. As worded, the hint could collapse a second U3+ nodule into one card. | "The U score of this nodule. (In a multinodular thyroid the report must also record the score of the most suspicious nodule.)" Or keep the hint and grade each nodule. |
| 3 | Minor | `reference.definitions.def.solid_cystic` | The pack says taller-than-wide or irregular overall shape is a "specific sign" of malignancy, like the solid-portion signs. The source (p28) only says the overall shape is "also relevant … as a predictor of malignancy", so the pack strengthens the source's hedge. | "…are specific signs of malignancy; a taller-than-wide or irregular overall shape also predicts malignancy." |
| 4 | Minor | cases.json names | "U3 (homogeneous hyperechoic nodule with halo)" leaves out "markedly" and "solid", so it does not separate U3(a) from U2(a) (iso- or mildly hyperechoic with halo). "U5 (solid hypoechoic nodule with microcalcification)" leaves out U5(a)'s lobulated or irregular outline. The names are only labels, but they teach the wrong boundary. | "markedly hyperechoic, homogeneous, solid nodule with halo"; "solid hypoechoic irregular nodule with microcalcification". |
| 5 | Minor | `reference.pitfalls.pit.ct` | This is correct, but it does not name the suspicious CT findings that the source lists (extracapsular extension, tracheal invasion, suspicious lymphadenopathy, p31 4.6 ii). The radiologist reading CT needs exactly those. | Add the three findings in brackets. |
| 6 | Minor | `reference.pitfalls.pit.scope` | This is correct. It could add Ch 15 i (p78), "general principles of management are similar" in children, so that the pitfall does not read as "do not use in children". | Optional. |

No Critical findings.

## Check of entry.json against the source

**Input.** `u_grade` U1–U5 matches the Fig. 4.1 labels (p30): U1 Normal, U2 Benign, U3 Indeterminate/Equivocal,
U4 Suspicious, U5 Malignant. The source has no absent or not-assessable states, so leaving them out is correct.
Finding 2 covers the hint.

**Table.** The five rows map one to one onto the five outcomes. There are no band edges.

**Outcomes.**
- **U1 and U2:** "Reassuring; FNAC not required unless … statistically high clinical risk" matches 4.3 i (p28, 2++ B)
  and keeps its hedge. "No routine US follow-up" matches 4.5 i (p29) and Fig. 4.2 "Benign (U1-2) → No follow-up
  required". The clinical-feature caveat matches the Ch 3.7 list (p25) word for word in substance; all eight
  features are present. The discharge caveat matches 4.5 i, including its condition (asymptomatic and no clinical
  suspicion).
- **U3:** "Ultrasound-guided FNAC" matches 4.3 ii (p28–29, 2++ B). The pregnancy caveat matches 14.1 iii (p75,
  2+ C): deferral is limited to U3 and depends on the patient's preference, which is correct. The repeat-FNAC
  caveat is supported for Thy1 by Fig. 4.2 and for Thy2 by 4.5 iv ("indeterminate or suspicious").
- **U4:** FNAC matches 4.3 ii. Neck assessment matches 4.4 iv (p29, GPP, "mandatory" when malignancy is suspected).
  The abnormal-node caveat matches 4.3 iii (p29, 2++ B). The <1 cm caveat paraphrases the 4.3 text (p28) faithfully,
  including "supported by the MDT" and the microPTC rationale. The repeat-FNAC caveat matches 4.5 iii and iv.
- **U5:** the same as U4, except for repeat FNAC (finding 1).

**Reference.**
- I checked tab.u_classification cell by cell against the Fig. 4.1 box image (p30). All letters (a)–(f) are present.
  "(markedly)", "cf thyroid", "cf strap muscle", "(? Papillary)" and "(? Medullary)" are preserved. The FNAC column
  is correctly drawn from 4.3 i and ii.
- tab.features matches all 12 bullets of Table 4.1 (p29), with the group headings kept.
- tab.report_features matches all 13 rows of Table 4.3 (p31). The Classification row correctly leaves out U1, as the
  source does.
- sum.1–3, def.nodule, def.taller_than_wide, def.spongiform, pit.summation, pit.size, pit.discordance (p30 4.4 v,
  4 C), pit.pet (p31 4.6 iii, 1++ A) and pit.nodes are all correct.
- Locator pages are all correct: p25 Ch 3.7, p28 4.3, p29 Table 4.1 / 4.4 / 4.5, p30 Fig. 4.1 / 4.4 v, p31 Fig. 4.2
  / Table 4.3 / 4.6, p75 14.1, p78 Ch 15, p8 and p15 scope.

## Golden cases

The pack has seven cases, all of them ours. There is one per grade and each reaches its own outcome. Two cases have
no grade (one omitted, one explicitly `unknown`) and both ask for `u_grade`. With a single enum the coverage is
complete. The source has no worked examples to add. The only issue is the descriptive names (finding 4).

## For Hassan verdicts

1. **Agree.** The Fig. 4.1 caption calls it a "graphic compilation of the signs", and 4.2 i says the signs are
   "used in summation". The signs overlap across grades (vascularity in U2(f), U3(c) and U5(c); hypoechogenicity in
   U3(b), U4(a) and U5(a)), and the source gives no precedence. Deriving the grade from features would mean
   inventing a rule.
2. **Agree.** 4.3 i only lifts the reassurance for a patient at high risk. It names no alternative action, so an
   asked input would gate nothing. A caveat is the honest form.
3. **Agree.** 4.4 iv applies "when a malignancy is suspected". U3 is equivocal. 4.3 ii does group U3 with U4–U5
   for FNAC, but the neck-assessment rule is specifically about suspected malignancy. The abnormal-node rule
   (pit.nodes) still applies at any grade.
4. **Agree.** The 4.3 text frames this as small nodules "suspicious for thyroid malignancy", found because US is
   sensitive for papillary carcinoma. That describes U4–U5 morphology, not an equivocal U3.
5. **Disagree with the stated reasoning; keep the caveat in a corrected form** (finding 1). Fig. 4.2 applies repeat
   FNAC to the whole U3–5 branch only for Thy1. For Thy2, the figure routes through the review of clinical and US
   suspicion to "repeat US-guided FNAC or MDT discussion". The U5 caveat should name both options, and review.md
   should describe the figure correctly.
6. **Agree.** 4.3 i explicitly says "(U1–U2)" and Fig. 4.2 says "(U1-2)". The fact that 4.4 i and Table 4.3 list
   only U2–U5 shows that U1 is rarely given to a nodule, not that U1 is excluded. Giving U1 the same management as
   U2 is faithful to the source.
7. **Agree.** The scope statements (p8 adult focus; p8 and p15 no lymphoma or thyroid metastases) describe what the
   document covers, not criteria for using the U classification. Ch 15 i says paediatric principles are similar.
   Carrying this as a pitfall is right (finding 6 is an optional addition).

## Wording and hedges

All outcome, caveat and reference text is paraphrased into the pack's own words. Short near-verbatim pieces
(def.nodule, "statistically high risk", the Fig. 4.1 sign strings) are definitional or tabulated facts, which is
acceptable. The source's hedges are kept: "unless … statistically high risk", "may be deferred … patient's
preference", "in the majority of cases" (rendered as "usually"), "inform whether FNAC is pursued", and "clinician
and MDT judgement". There are two exceptions. def.solid_cystic strengthens a hedge (finding 3). The U5 caveat drops
the "or MDT discussion" alternative (finding 1).
