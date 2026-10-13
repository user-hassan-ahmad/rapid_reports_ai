# Independent clinical read: pi-rads-2-1@2019.1

Reader: fresh agent, read-only (step 8 of the guideline-pack skill). This file is the only thing written.
Source: S1, ACR PI-RADS v2.1 (2019), on disk. I viewed these pages as images: p18 (PZ and TZ tables), p23 (without adequate DWI, without adequate DCE), p72 and p73 (Figures 13 and 14). I read the text of p10, p17, p19–22, p25, p27–31, p34–35 and p66–73. Page numbers are PDF pages.

## Verdict

**Sound. No Critical findings. One Important finding**, which is golden-case coverage, not logic. Every rules case, outcome, table cell and caveat matches the source. The recommendations add no management that the source doesn't give. Fix the Important finding and the For Hassan wording (Minor 1 and 3), then re-check.

## Inputs

| Input | Check |
|---|---|
| `treated_cancer` (eligibility) | ✓ p10 ("does not address … suspected recurrent prostate cancer following therapy") and p31 ("local recurrence following prior treatment, a setting in which current PI-RADS assessment criteria do not apply"). The how_stated gates it on "MRI looks for recurrence", which is right. Including "hormonal therapy for cancer" is a library reading; see Minor 1. |
| `zone` | ✓ The AFMS rule is from p21. Applying it to the CZ is an extension (see For Hassan). |
| `dwi` 1–5 / X | ✓ p27 table; X from p22. |
| `t2w` 1–5 / X, prerequisite TZ or DWI X | ✓ The PZ table makes T2W irrelevant when DWI is adequate. The TZ table and the no-DWI table both need it. |
| `dce` +/−/X, prerequisite (PZ and DWI 3) or DWI X | ✓ DCE changes the category only for PZ DWI 3 (p18) and for T2W 3 in the no-DWI table (p23). TZ DCE is "Any" everywhere, and p31 says the "TZ assessment remains unchanged" without DCE. Asking DCE for every DWI X lesion is needed only because of the staging-only rule, which is consistent. |
| DCE how_stated (+ / − definitions) | ✓ p28–29 and the p29 table, including BPH and extruded-BPH enhancement as negative. |

## Rules cases (all 23)

I checked every case against the p18 and p23 images. I also enumerated the space by hand: treated false; PZ with DWI 1, 2, 4, 5; PZ DWI 3 with DCE + / − / X; TZ with DWI 1–5 × T2W 1–5 and X; DWI X × DCE ± × T2W 1–5 and X; DWI X with DCE X. Each combination gives exactly one case.

| # | Condition → result | Source | Check |
|---|---|---|---|
| 0 | treated → does_not_apply | p31, p10 | ✓ |
| 1 | DWI X and DCE X → staging_only | p23 sentence under the no-DCE table | ✓ (For Hassan, agree) |
| 2 | T2W X where used, not case 1 → not_categorised | silent; p22 defines X | ✓ library addition, labelled |
| 3 / 4 | PZ DWI 1 → 1; DWI 2 → 2 | p18 PZ | ✓ |
| 5 / 6 | PZ DWI 3, DCE − → 3; DCE + → 4 | p18 PZ; p17 | ✓ |
| 7 | PZ DWI 3, DCE X → 3 | p23 "PZ: Determined by DWI Assessment Category"; p31 "will not be upgraded" | ✓ |
| 8 / 9 | PZ DWI 4 → 4; DWI 5 → 5 | p18 PZ | ✓ |
| 10 | TZ T2W 1, any DWI → 1 | p18 TZ | ✓ |
| 11 / 12 | TZ T2W 2: DWI ≤3 → 2; DWI ≥4 → 3 | p18 TZ (≤3 / ≥4); p23; Fig 12; Fig 14 caption "DWI score 4 or 5 … is scored a 3" | ✓ (p20 ">4" is a typo; see For Hassan) |
| 13 / 14 | TZ T2W 3: DWI ≤4 → 3; DWI 5 → 4 | p18 TZ | ✓ |
| 15 / 16 | TZ T2W 4 → 4; T2W 5 → 5 | p18 TZ; p21 caveat | ✓ |
| 17–22 | DWI X: T2W 1 → 1; 2 → 2; 3 with DCE − → 3; 3 with DCE + → 4; 4 → 4; 5 → 5 | p23 no-DWI table, headed "PZ and TZ" | ✓ cell for cell |

The TZ upgrade edges are correct: T2W 2 with DWI 3 gives 2 and with DWI 4 gives 3; T2W 3 with DWI 4 gives 3 and with DWI 5 gives 4. The TZ no-DCE table (p23) is the p18 TZ table with DCE set to X, so no separate case is needed.

## Outcomes and caveats

| Item | Check |
|---|---|
| pirads_1–5 classifications | ✓ p17 likelihood phrases. |
| pirads_1/2 recommendations ("should not be considered … gives no management") | ✓ p17: "biopsy should be considered for PI-RADS 4 or 5, but not for PI-RADS 1 or 2, PI-RADS v2.1 does not include recommendations for management". |
| pirads_3 recommendation | ✓ p17: "biopsy may or may not be appropriate, depending on factors other than mpMRI alone". |
| pirads_4/5 recommendations | ✓ p17. "Clinical factors and local practice" paraphrases "laboratory/clinical history and local preferences, expertise and standards of care". |
| Caveat: MRI findings only | ✓ p17. |
| Caveat: state the DWI limitation | ✓ p22. It is conditional ("if DWI was inadequate"), so it is harmless on every category. |
| Caveat: PZ DWI 3 without DCE stays 3 | ✓ p31. |
| Caveat: extruded BPH should be category 2 | ✓ p28 word for word ("in the PZ or CZ … even if hypointense on ADC … should be category 2"). |
| staging_only | ✓ p23. "State the limitation" comes from p22 (DWI is X here). The repeat-DWI caveat is from p22 and keeps "if the cause of failure can be remedied". |
| not_categorised | ✓ Labelled as a library addition. Its recommendation is reporting only, not management. |
| does_not_apply | Classification ✓ (p31). The recommendation "Manage per the clinical context." is not from the source; see Minor 2. |

**Management check:** no outcome states management beyond the p17 biopsy sentence and its disclaimer. Biopsy wording keeps the source's hedges ("should be considered", "may or may not"). The only unsourced line is the bland does_not_apply text (Minor 2).

## Reference block

- Every table cell (p17, p18, p23, p25, p27, p29) matches.
- Definitions (csPCa as printed, DCE +/−, "markedly", X, index lesion) match p17, p19, p22, p28 and p29.
- Pitfalls match p10, p20–22 and p28.
- sum.2 says DCE "matters only" for the PZ DWI 3 upgrade or DWI X. That is right for categorisation. p30 also gives DCE a role in prioritising the index lesion, but nothing reads that.

## Golden cases

- All 41 cases give the stated outcome under the rules above (checked by hand).
- Source examples present: Figures 7–12 (p66–71; captions checked; the zone-less CZ and AFMS figures are run on both tables), Appendix I lesions 1 (TZ 5/5/+ → 5) and 2 (PZ T2 4, DWI 3, DCE + → 4; p35, verified), the p21 caveat examples, the p21 no-upgrade statements and the p31 bpMRI statement.
- **Missing source example: Figure 14 (p73).** It is a worked TZ scoring schematic with four panels: T2 1 → 1; T2 2 with DWI 1–2 → 2; T2 2 with DWI 3 → 2; T2 2 with DWI 4/5 → 3. None is cited as a Figure 14 case. TZ T2W 2 with DWI 1 or 2 is not tested at all. See Important 1.
- Figure 13 (p72) gives T2W scores only and no overall category, so it is correctly not a case. Figures 1–6 illustrate single-sequence scores only (no overall category), so they are also correctly not cases.
- "TZ T2W 3 DWI 5 without DCE is still 4" is marked `ours`, but p31 states it ("TZ assessment remains unchanged"). Minor 4.
- The three `needed` cases are sensible.

## For Hassan: verdicts

1. **TZ upgrade edge (≥4, not >4): agree.** The p18 and p23 tables, the Figure 12 worked case and the Figure 14 caption ("DWI score 4 or 5") all give ≥4. The p20 ">4" with "(i.e., with markedly restricted diffusion)" describes DWI 4, so it is a typo for ≥4.
2. **T2W X → not_categorised: agree.** The source gives no table without T2W, and an explicit "does not fit" is better than guessing. One correction to the wording: the PZ table's "Any" for T2W carries the footnote "Any indicates 1–5". So ignoring T2W X in a PZ lesion with adequate DWI is a (sensible) extension, not "as the PZ table does". Say so (Minor 3).
3. **DWI X and DCE X → staging only, even for T2W 1/4/5: agree.** The p23 sentence is explicit and unconditional, and it sits after both tables. Following it over the "Any" cell is the safer reading.
4. **Extruded BPH as caveat, not input: agree.** p28 frames it as a DWI caveat, and a radiologist who recognises an extruded BPH nodule will dictate low scores. Residual risk: if someone dictates "encapsulated round PZ nodule, DWI 4", the card shows PI-RADS 4. The caveat wording ("should be category 2") already says the category is wrong in that case, which is enough.
5. **Eligibility (one input; surveillance and BPH or drug therapy stay eligible): agree with the logic, but the For Hassan line misreports p31.** p31 item 3 lists "TRUS/TURP/BPH therapy, radiotherapy, focal therapy or embolization" and "drug/hormonal therapies" as conditions to evaluate with mpMRI "for disease detection and localization". The line mentions only BPH/TURP and the drugs. This is a real tension in the source: radiotherapy and focal therapy appear there, while p10 and p31 also say PI-RADS criteria do not apply to recurrence after therapy. The pack resolves it correctly: the gate is "treated prostate cancer **and** MRI for recurrence" (radiotherapy for another pelvic cancer stays eligible). The tension should still be stated. Separately, "hormonal therapy for cancer" in the how_stated is our addition; p31 groups hormonal therapies with interventions to be evaluated, not with exclusions. Minor 1.
6. **Recommendation text: agree.** It is faithful to p17 and adds nothing (see the management check above). The exception is does_not_apply, which this item doesn't cover (Minor 2).
7. **CZ zone rule: agree.** p21 says most CZ cancers arise in the adjacent PZ or TZ, so using the zone of origin is the natural extension of the AFMS rule. Figures 7 and 8 give the same category on both tables, so no source example conflicts.
8. **csPCa "> 7" kept as printed: agree.** No logic reads it.

## Findings

### Critical
None.

### Important
1. **Figure 14 (p73) worked examples are missing from cases.json.** The skill requires every worked example in the source as an `origin: "source"` case. Add four cases: TZ T2W 1 → 1; T2W 2 + DWI 1 (or 2) → 2; T2W 2 + DWI 3 → 2; T2W 2 + DWI 4 and DWI 5 → 3. This also closes a coverage gap, because TZ T2W 2 with DWI 1 or 2 is currently untested. Logic is unaffected.

### Minor
1. The For Hassan eligibility line omits that p31 item 3 lists radiotherapy, focal therapy and embolization (and hormonal therapies) among interventions to evaluate with mpMRI. State the tension with p10 and p31 and how the pack resolves it. Flag "hormonal therapy for cancer" in `treated_cancer.how_stated` as a library reading, or drop it.
2. The does_not_apply recommendation "Manage per the clinical context." is not in the source. Prefer wording without management, eg "No PI-RADS category; v2.1 criteria do not apply to suspected recurrence after treatment."
3. In For Hassan item 2 and the review checklist, ignoring T2W X for a PZ lesion with adequate DWI is described as following the PZ table. The table's "Any" is footnoted "1–5", so this is an extension and should be called one.
4. The case "TZ T2W 3 DWI 5 without DCE is still 4" restates p31 ("TZ assessment remains unchanged"). Mark it `origin: "source"`.
5. Provenance: S1 is a third-party mirror, and its sha256 has not been compared with the ACR's live PDF. The content I read is the genuine v2.1 text, but record the comparison when the ACR file can be fetched.
