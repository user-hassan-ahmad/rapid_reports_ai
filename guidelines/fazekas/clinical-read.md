# Clinical read: fazekas@1987.1 (tier 2 reference card)

Independent read against the publisher PDF (Fazekas F et al., AJR 1987;149:351-356), pages viewed as images (journal pp352-355). Read-only; no card files changed.

## Verdict

Accurate and faithful to the paper; nothing clinically wrong and nothing imported from outside it. Approve after one Important change (item 1: name the single-grade gap inside the card) and a few Minor wording fixes.

## Checked against the source

- Grade definitions: all 8 match the Methods sentence on p352 ("0 = absence, 1 = caps or pencil-thin lining, 2 = smooth halo, 3 = irregular PVH extending into the deep white matter"; DWMH "0 = absence, 1 = punctate foci, 2 = beginning confluence of foci, 3 = large confluent areas"). No millimetre thresholds or other modern additions. Correct.
- def.sep and pit.nocombined: the paper rates PVH and DWMH separately and Table 1 lists two grades per case; no sum or single grade appears anywhere. Correct.
- Table 2 (p353): every cell matches (PVH 0-1: 8/6/1; 2: 0/6/0; 3: 1/0/3; DWMH 0: 4/5/0; 1: 2/3/1; 2: 3/4/1; 3: 0/0/2). Column totals 9/12/4. I also recounted Table 1 per-case grades and reproduced every Table 2 count, including the split of PVH 0 vs 1.
- pit.age: all 7 cases with PVH 0 in Table 1 are under 70 (52 to 68). Correct. The paper also says PVH and DWMH were seen more often in older subjects but not predictable from age; the card keeps the second half only (fair).
- pit.grade3: DWMH 3 only in cases 13 and 14 (MID); PVH 3 in 13, 14, 15 (MID) plus control 24 (83, hypertension). All have hypertension. Correct. The "should rule against pure Alzheimer disease" sentence is the authors' (p354), attached to "extensive deep white matter changes".
- pit.punctate: "of no value in distinguishing AD from controls" (p355) and "about 60% of all subjects had some foci of DWMH" (p353; Table 2 gives 16/25 = 64% for grade 1 or more). Correct. "Unrelated to vascular risk factors" is the authors' statement.
- pit.halo, pit.small (mean ages 69/70/68; over-80 experience too limited), sum.2, sum.3, sum.4 (1.5 T GE, spin-echo, sagittal/axial/coronal, neuroradiologist blinded): all correct.
- evidence.md: 24 facts, 17 below 0.5; I count 17 flagged. Consistent. Low scores are from the scrambled scan, not from errors.

## Findings

1. Important. Single dictated "Fazekas grade": the card never says the paper cannot resolve it. The gap is only in review.md (reviewer-facing), not in entry.json. See "Item 1" below.
2. Minor. pit.scope says the scales were "devised for" T2 spin-echo in dementia research. The paper says "a modification of suggested rating scales [5, 6] was used" (p352), so the authors did not devise them. It also acquired both T1 and T2 sequences and never states which sequence was graded. Reword to "applied by the authors, modified from earlier scales [5, 6], to spin-echo MR in dementia research". The same T2 inference sits in sum.1 ("T2-weighted hyperintense signal").
3. Minor. pit.nocombined: "report both grades, not a sum" is library advice, not paper content. The paper only shows two separate ratings. Keep the first sentence as source; mark the second as library guidance or drop it.
4. Minor. pit.grade3 locator lists journal pp354-355 but the control case (83-year-old) is on p353 and in Table 1/2. Add p3 to the locator. The "rule against pure AD" attribution to PVH grade 3 as well as DWMH is slightly broader than the authors' sentence; name that it concerns extensive deep white-matter change.
5. Minor. review.md item 1 says "total or combined 0 to 3". A sum of two 0-3 ratings is 0-6; "0 to 3" would be a worse-of-two. Fix the note so the gap is stated precisely.
6. Minor. Aliases "Fazekas score" and the generic "white matter hyperintensity scale" can pull this card for combined scores or other scales (Scheltens, Wahlund/ARWMC). Bare "Fazekas" is fine only if the gap is stated (finding 1).

## For Hassan items

1. Single grade: agree it is a real, correct decision not to define "Fazekas 2" alone, but disagree that recording it in review.md is enough. See below.
2. PVH 0 and 1 merged: agree, it mirrors Table 2. Note Table 1 holds per-case grades and splitting is derivable (controls 5 and 3; Alzheimer 2 and 4; MID 0 and 1), so merging is a choice, not a limit of the source. Splitting adds a computed table not printed in the paper, so keep merged.
3. No management added: agree. The paper gives none, and pit.nomanagement states it.
4. Aliases: agree they are library additions, with the caveats in finding 6.

## Item 1: mapping a single "Fazekas grade"

The paper cannot supply a mapping. It defines two independent 0-3 ratings, reports them side by side per case, and gives no single or overall grade, no rule such as "worse of the two", and no sum. So the card must not say "Fazekas N means PVH N" or "means the higher of the two". It should name the gap in entry.json (as an absence claim, like pit.scope), for example a pitfall:

"A bare 'Fazekas grade N' is ambiguous. The paper defines only PVH 0-3 and DWMH 0-3 as separate ratings and gives no rule for a single overall grade (not the higher of the two, not a sum). A single number cannot be assigned to PVH or DWMH from this source; both grades are needed, or the dictator must say which scale the number refers to."

Where the dictation names the region ("periventricular Fazekas 2", "deep Fazekas 1"), the mapping to PVH or DWMH is direct and sourced. Outside the source (do not put in the card): in common practice a single number is often the worse of the two, or an overall 0-3 or summed 0-6 grade, and local convention varies. That variation is exactly why the card should flag the ambiguity and prompt the radiologist to state both, rather than guess.
