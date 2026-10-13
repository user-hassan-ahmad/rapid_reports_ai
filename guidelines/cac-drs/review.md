# Review: CAC-DRS (SCCT 2018)

Source: Hecht HS et al., J Cardiovasc Comput Tomogr 2018;12:185-191 (S1). Page numbers are PDF pages (Table 1 is journal p.186 = PDF p.2). Independent read: `clinical-read.md`; fixes below follow the controller's rulings.

## Checklist
| Item | Check |
|---|---|
| Input `agatston` (number, banded 0 / 1-99 / 100-299 / 300 or above), `not_assessable` when no score exists | ✓ 3.1, Table 1a; edges at .5 are the standing round-half-up choice |
| Input `cac_drs` (0-3, dictated category), used when there is no Agatston score | ✓ Table 1, section 3 |
| Rules: score band wins; else the dictated category | ✓ one outcome per category either way |
| Outcome cac_drs_0 to _3: category, risk statement, prompt to document A/V (and N for 1-3), neutral discussion sentence | ✓ Table 1 risk column; no statin or aspirin wording in the outcomes |
| US statin and aspirin wording | ✓ moved to reference table "SCCT 2018 (US) management, for reference only, not UK guidance" |
| Net-benefit hedge kept wherever management is mentioned (outcome caveats, sum.5, US table locator) | ✓ section 2 |
| Vessel modifier N not an input; wording follows 4.2 (additive in MESA, insufficient data to change categories, may influence aggressiveness, should be reported) | ✓ |
| Eligibility inputs | none: the source's scope (all dedicated CAC scans and non-gated non-contrast chest CT, irrespective of indication) has no exclusion; asymptomatic framing is a pitfall (pit.scope) |
| UK note and CAD-RADS line | ✓ pit.uk is a library note with no UK claim beyond "separate UK consensus (planned pack)"; pit.cadrads labelled a library addition |
| Golden cases: 4 source examples, visual, 13 score edges both sides, conflict, three `needed` cases | ✓ |

## Clinical read findings
- I1, I4: done (outcomes carry no management; no aspirin dose or NICE claim anywhere).
- I2: done. I3: pitfall, as the source has no exclusion clause for known CAD (its intro says "irrespective of the indication").
- I5: done; the corrected statement that the visual version applies to non-gated CT is pit.visual and sum.1.
- Minors 6-10 done (N wording, "300 or above (printed '> 300')", CAD-RADS label, prompt to document A/V, duplicate case replaced). Minor 11 (M11): done as the score input.

## Gate 5 (20 below 0.5)
All read against the source and accepted.
- Outcome and rules entries: the recommendation sentence ("Document the scoring system...", "CAC informs a clinician-patient discussion of preventive therapy") is the controller's wording; the checker looks for it on Table 1 (p.2), where it is not printed. The discussion framing is from section 2; the A/V and N documentation prompt is from 4.1 and 4.2 (PDF pp.4 and 6).
- N caveats and "N not used for category 0": section 4.2, PDF p.6, not p.2.
- sum.2, sum.5, def.g3, tbl.bands, pit.gap300: confirmed against sections 2, 3.1 and Table 1 (the "300 or above" wording is ours, from the 3.1 text).
- pit.cadrads and pit.uk: library notes, not source claims.

## For Hassan
- DECISION: both US management lines (statin, statin intensity, aspirin 81 mg) stay out of outcomes and sit only in a reference table labelled not UK guidance (controller ruling I1/I4). Category 0 text is "very low risk" with no statin line.
- DECISION: Agatston edges use round half up at .5 (0.5, 99.5, 299.5), because the source prints integer bands with gaps (100-299, "> 300"). A score of exactly 300 is category 3 per the 3.1 text (300-1000).
- Library addition: an optional Agatston score input. The score wins over a dictated category when both are given. The engine could not combine two either-or inputs with prerequisites without gate-2 combinations that have no outcome, so there is no prerequisite: with nothing dictated both are asked; with only a category dictated the card still asks whether an Agatston score exists (answer not_assessable). Visual-only reports will see that question.
- No eligibility question: the source has no exclusion clause (known CAD or prior MI is not excluded; it frames CAC as ASCVD risk assessment). Revisit if you want a library-added screen.
- Library notes with no source: pit.uk (UK separate consensus, planned pack) and pit.cadrads (CAD-RADS for coronary CTA). Both cite the intro only for where the scope sits.
