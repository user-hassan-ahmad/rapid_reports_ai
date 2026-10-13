# Clinical read: cac-drs@2018.1

Reader: independent Claude read against the S1 text (Hecht 2018, Table 1a/1b, sections 1-9). Read-only; no pack file edited. UK guidance points (NICE, BSCI) are from my own knowledge, not on disk, and need Hassan's confirmation before any pack cites them.

## Verdict
Faithful transcription of Tables 1a/1b: all four rows, risk labels, statin intensities, aspirin 81 mg and the category 0 hedge match the source. Fit for the library as a reference card with changes. Not ready to feed recommendation text into a UK report as it stands.

## Verified against the source
- Table 1a/1b rows 0-3 and risk labels: exact. Category 0 "generally" (1a) vs none (1b), and the FH asterisk on both: kept correctly; using the hedged form for both is the safe choice.
- Agatston 300-1000 and above 1000 merged because management is the same (3.1): correct.
- Visual: not for gated CAC scans (3.2): correct. N: 1-4, "should be reported", not used for grade 0 (4.2): correct. Aortic, valve, mitral annular and pericardial calcification are reported separately (6): correct. Per-patient (abstract): correct. A/V/N examples (5): correct.
- Golden cases 1-4 match source examples i-iv. Case 5 (V3/N4) matches. Cases 6 and 7 are duplicates of each other.

## Findings
1. Important. Outcome text carries US-only management (statin intensity, aspirin 81 mg) and the per-outcome caveat does not say it is US. "SCCT consensus's, for the clinician to apply" is a pack addition (Jev 0.51) and does not warn a UK user. The US flag exists only in a pitfall.
2. Important. The source frames CAC as informing a clinician-patient discussion of net benefit ("likely to benefit", "may be more likely to benefit", section 2). The outcomes state flat directives with no hedge. Add a caveat: recommendations are for discussion in asymptomatic primary-prevention patients, not an instruction.
3. Important. Scope drops "asymptomatic". The source premise is ASCVD risk assessment in asymptomatic patients. A patient with known CAD, prior MI or stent is not what the management column addresses. pit.scope should say so.
4. Important. Aspirin and UK practice (from my knowledge, confirm): NICE does not recommend aspirin for primary prevention, and the UK low dose is 75 mg. Aspirin 81 mg should not reach a UK report as advice.
5. Important. pit.uk is a library claim ("usually follow the 2020 BSCI/BSCCT/BSTI consensus") with no source on disk (Jev 0.29), yet its locator points to S1 section 8. The locator implies source support it does not have. Note also that S1 itself applies to non-gated chest CT (introduction), so CAC-DRS V is not inapplicable there. Get the BSCI/BSCCT/BSTI citation from Hassan and make it a second source, or reword pit.uk as an unreferenced note.
6. Minor. N caveat says N "does not change the category". The source says "insufficient data to change risk categories", and that N is additive in MESA "particularly in the CAC range of 1-300". sum.3's "does not change ... the stated management but may influence" reads as self-contradictory. Use the source's hedge.
7. Minor. Classification strings say "Agatston above 300" while the source text puts 300 in category 3 (300-1000). Write "300 or above (printed '> 300')". The gap pitfall itself is correct.
8. Minor. pit.scope's "Contrast-enhanced CCTA uses CAD-RADS, not this system" is not in S1. The source mentions CAD-RADS only as a sibling system. True, but unsourced; label it as a library addition.
9. Minor. No outcome tells the reporter to document the scoring system letter (A or V, 4.1). Add to caveats.
10. Minor. Cases 6 and 7 are the same test; replace one with a raw-score dictation ("Agatston 450" with no category) to document what the pack does, or a dictated "A2/N3" digit-extraction case.
11. Minor. The pack takes the category digit only. A radiologist more often dictates the raw score, so the pack will ask for a category the user may not have said. See For Hassan 3.

## For Hassan items
1. Score of exactly 300: agree. Section 3.1 gives 300-1000 as its own band, so 300 is category 3. Pitfall-only is right while no band is in logic.
2. Category 0 hedge: agree. Keep "generally" (the safe form); the caveat records the difference.
3. Category digit only, no score input: partly disagree. I would add an optional Agatston score input that derives the category. It matches how scores are dictated. Derive 0, 1-99, 100-299, >=300, and ask when the value is non-integer between 299 and 300 or the category is dictated and conflicts with the score. Visual scores stay as dictated digits. Not blocking.
4. UK pitfall: agree it is needed. It needs a citation (finding 5).
5. Whether UK reports surface aspirin 81 mg: my view is no, see below.

## US statin/aspirin wording in a UK report
Do not let the aspirin 81 mg line, or the statin intensities as an instruction, enter report text. A UK radiologist reports the CAC-DRS category, the A or V scoring letter, N for categories 1-3, and the risk statement (very low through moderately to severely increased). Management belongs to the referring clinician under local practice (NICE, QRISK, shared decision-making).

How to do it:
- Keep the Table 1 wording in the reference panel only, labelled "SCCT 2018, US practice; not UK guidance; aspirin dose and indication differ in the UK".
- Do not auto-insert the recommendation field into the report. If a recommendation sentence is wanted, make it neutral: "Suggest cardiovascular risk assessment and consideration of preventive therapy in line with local guidance."
- Add a pack-level region tag (US wording) so the library can suppress `recommendation` for UK users by default, with the risk statement still shown.
- Category 0 "statin generally not recommended" is also US. Soften it to "very low risk" in UK text.
