# Review: lund-mackay@1993.1 (tier 2 reference card)

Source: Lund VJ, Mackay IS, Staging in rhinosinusitus, Rhinology 1993;31:183-184 (PMID 8140385; no DOI), journal archive free download, sources3/lund-mackay (sha256 27e87d20...f38444). Locators are 1-based PDF pages: p1 = journal p183 (text), p2 = journal p184 (Table 1 and Discussion). Table 1 was read from the page image: it is a data-entry form, so the grading table is built from the form's radiological block plus the text on p183.

## Pack type

Tier 2 reference card. The paper gives a scoring system (0 to 24, 0 to 12 per side) with no bands and no management for any score, so there is no grade-to-management mapping for a tier 1 pack. No inputs, logic, outcomes or cases.

## Checklist

| item | source | |
|---|---|---|
| sinus groups graded 0/1/2 (maxillary, anterior ethmoid, posterior ethmoid, sphenoid, frontal) | text p1, Table 1 p2 | ✓ |
| OMC 0 or 2 | text p1, Table 1 p2 | ✓ |
| total 0 to 24, per side 0 to 12 | text p1 | ✓ (5 groups x 2 + OMC 2 = 12 per side, consistent) |
| tab.grading rows, per side | Table 1 p2 | ✓ |
| tab.variants six variants, recorded 1/0, not scored | text p1, Table 1 p2 | ✓ |
| sum.4, pit.partial, pit.secretion, pit.evidence | p1 paragraph 3, Discussion p2 | ✓ |
| pit.notscored (variants, surgical 0-14, symptoms, endoscopy not in staging) | p1, p2 | ✓ |
| pit.scope (non-neoplastic) | Introduction p1 | ✓ |
| pit.nobands, sum.3 second sentence | absence statement; whole paper read | ✓ |

## Gate 5 flags

Two facts scored below 0.5: def.sides (0.10) and tab.grading (0.43). Both are drawn from Table 1, a form image whose R/L columns and item list are not in the text layer; checked against page-2.png (R and L columns present, six radiological items, OMC (0 or 2), TOTAL). Confirmed. pit.scope and pit.notscored were reworded after a first pass to stay within the text.

## For Hassan

1. DECISION: the paper gives no severity bands or management, so the card carries none. Clinical cut-offs sometimes quoted for this score (for example a score above a threshold meaning surgery or medical failure) come from later papers and are not in this card. Say if you want a later-source companion pack.
2. The paper does not call itself "Lund-Mackay"; that name is how reports and the field refer to it. The aliases and display name are library additions.
3. Ethmoids appear in Table 1 as two groups (anterior, posterior) but the text says "each sinus group"; the card follows the table (five groups, max 10 plus OMC 2 = 12 per side).
4. Library addition: the source's "Total" line in Table 1 is blank, so the "Total" row meanings in tab.grading restate the p1 text.

## Clinical read fixes (clinical-read.md)

- Important 1: added pit.undefined (silent on absent/hypoplastic sinus, partial vs total, OMC obstruction, post-operative anatomy); no convention added.
- Important 2: removed aliases "CT sinus score", "sinus CT score", "LMS".
- Minors 3-8: variants wording de-doubled; "Library note" tag on pit.nobands; pit.scope now "was not developed for tumours"; pit.evidence states inter-observer correlation only; pit.notscored marks the symptom/surgical exclusion as inference; pit.omc says the group list comes from Table 1.
- Gate 5 re-run after the wording changes; remaining low scores are the Table 1 form facts already explained above.
