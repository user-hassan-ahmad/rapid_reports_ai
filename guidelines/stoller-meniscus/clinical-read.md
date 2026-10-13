# Clinical read: stoller-meniscus@1987.1 (independent)

Source checked: Stoller DW et al., Radiology 1987;163:731-735, all five PDF pages read as images (p1 = journal 731 ... p5 = 735). Read-only; no card files changed.

## Verdict

Accurate. No Critical findings. Every grade definition, stage definition, both tables, the 100% concordance figures and all pitfalls match the source, and locators are correct. Two Important items concern framing and completeness (below). Fix those before merge; the rest is Minor.

## Verified against the source

- def.g1-g3: match p731-732 (grade 1 punctate foci not contiguous with an articular surface, capsular margin excluded; grade 2 linear intrameniscal without surface extension; grade 3 extends to at least one articular surface). Sagittal best, coronal corroborating: correct.
- def.s0-s3 and tab.grades: match p732 (11 stage 1, 16 stage 2, 8 stage 3, each 100% to the same MR grade; "one normal and three abnormal stages").
- tab.table1: matches p733 exactly, including the footnote (five posteromedial, one posterolateral). Column sums 11/16/8 correct. Text on p732 (six of eight stage 3 in the medial posterior horn) agrees.
- sum.3, pit.nomgmt: the authors' only forward statement is that patients with posterior-horn grade 2 signal "would be expected to experience tears that may be of prognostic importance". Correctly framed as expectation.
- pit.arthro: the 6% false-positive rate is from reference 22 (Crues et al., "first 44 cases (forthcoming)"), confirmed on p735. Attribution correct.
- pit.undergrade, pit.fray, pit.bucket: match p734 wording. pit.mimic: match p734 (transverse ligament, popliteus tendon sheath).
- sum.4, pit.scope: 12 menisci (six medial, six lateral), age 50 to 89, 1.5 T, spin echo 800/25, contiguous 5 mm sagittal: correct.

## Findings

1. Important. pit.grade3 and For Hassan item 2 frame the two intrasubstance stage 3 segments as grade 3 despite not reaching the surface. The source (p732) adds that these two "did show mucinous degeneration contiguous with the tear and articular surface". So the grade 3 signal was plausibly explained by degeneration reaching the surface, and there is no clean contradiction with def.g3. The card omits this clause, which makes the discrepancy look larger than the paper does. Add it to pit.grade3 and soften item 2.
2. Important. sum.2 and tab.grades present "100%" without its limits. The paper has 35 abnormal segments from 12 menisci (segments from one meniscus are not independent), a blind read by two radiologists and two pathologists, no inter-observer statistic, no sensitivity or specificity, and the single stage 0 segment's MR grade is not reported. A reader could take 100% as diagnostic accuracy. Add one pitfall or a clause stating what the figure is (histology correlation of graded segments, ex vivo, small n).
3. Minor. pit.scope says "younger or acutely injured knees are not addressed". That is true by omission but it is the card author's inference, not paper text, and it is not listed in For Hassan item 4. List it or trim it.
4. Minor. sum.4 "8 autopsies and 4 above-knee amputations": the paper states four amputations and "12 autopsies and amputations" in the abstract; 8 is arithmetic. Fine, but not stated.
5. Minor. pit.mimic omits that the transverse-ligament pseudotear was seen in about 30% of clinical knee MR studies (p734, ref 24) and that it is the anterior horn of the lateral meniscus. High-yield for a reporting prompt; consider adding.
6. Minor. pit.bucket omits Figure 9's point that a bucket-handle tear shows grade 3 signal in both anterior and posterior horns. Optional.
7. Minor. pit.nomgmt says "no management", which is right, but the Discussion does say presurgical MR would help find degeneration or intrasubstance tears the arthroscopist may miss, and that this is "clinically significant". Consider one clause so the card is not read as the paper having no clinical-use claim.
8. Minor. The card does not say that stage 1 and 2 changes are not visible at arthroscopy (p733) while stage 3 can be missed there. This is a useful, in-source qualifier for the grade 1 to 2 versus 3 distinction.

## For Hassan items

1. Agree. No "grade 0" and no management is the correct reading of the source; reports saying either should find nothing in the card. Accept as is.
2. Partly disagree with the framing (see finding 1). Keep both def.g3 and pit.grade3, but state that the intrasubstance cases had degeneration contiguous with the surface. This is a clarification, not a choice between two statements.
3. Agree to keep. The attribution to reference 22 is exact and the figure is clinically useful. Keep it explicitly labelled as quoted, not measured here.
4. Agree with the disclosure, with one addition. "Not graded here" and the generic aliases are reasonable library additions. Also disclose the pit.scope inference (finding 3). Bare "Stoller" is safe; "meniscal signal grade" is generic enough that it should only match with a knee or meniscus context (the applies_to filter handles this).
5. Agree. Correct arithmetic (35 of 36, one implied stage 0). Leave it out of the entry as the card does; the paper does not state it.
