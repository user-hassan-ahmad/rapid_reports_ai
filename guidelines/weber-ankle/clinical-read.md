# Clinical read: weber-ankle@2018.1 (independent)

Reader: Claude, independent of the pack author. Read-only. Checked against `sources/8e3e...29d1.txt` (journal pages
S65-S69, PDF pp 68-72; Appendix S168-S169, PDF pp 171-172) and the page image of PDF p70 (S67). Page mapping
(PDF = journal + 3) confirmed.

## Verdict

Pass with minor fixes. Every type, group, subgroup, qualification letter and pitfall matches the source. No management
or Weber equivalence is written as a card fact. Two points need action before shipping: the aliases carry an implied
Weber equivalence that the card never disclaims (Important), and two definitions add gloss the source does not give
(Minor).

## Field-by-field check

| field | result |
|---|---|
| tab.types (44A/B/C, names, location) | Match. Source overview calls 44C "suprasyndesmotic fibula fracture"; the 44C heading says "injury". Card uses "fracture" in the table and "injury" in def.44c; both are source wording. |
| tab.groups (9) | All nine match the group headings (44A1-3 p68-69; 44B1-3 p70-71; 44C1-3 p71-72). |
| tab.subgroups (27) | All 27 captions match. 44B2.2 and 44B3.3 wording matches. |
| Qualifications | Match. 44A: none (no asterisk). 44B1, 44B2.1, 44B2.2, 44B3: n, o, u. 44B2.3: r, s, u (confirmed on the image). 44C1, 44C2: t, u. 44C3: p, q, r, s. |
| def.qualifications | Match the foot note ("lower-case letter within rounded brackets ... asterisk ... more than one ... separated by a comma"). |
| pit.isolated_medial | Match (Appendix S169: 43B1.2 or 43B2.2; with a lateral-side injury it is 44). |
| pit.posterior_margin | Match (43B1.1 or 43B2.1). |
| pit.fibula_code | Match (Fibula intro S168 and Appendix S169). The "4F" code is stated in the source. |
| sum.1, sum.2, sum.3 | Supported. sum.3 (absence of management or prognosis) is true of pp 68-72. The u/t "syndesmosis unstable/stable" qualifier is a descriptor, not management. |

## Findings

1. Important. Aliases imply a Weber equivalence the source never states. "Weber A/B/C", "Danis-Weber" and the id
   `weber-ankle` mean a report line "Weber B" surfaces a card headed 44B. The source never uses "Weber" or "Danis-Weber".
   The two systems are close but not identical. Weber/Danis-Weber is a fibular-level system; 44A includes a lateral
   collateral ligament rupture with no fibular fracture, and 44C is limited to diaphyseal or proximal fibula injury.
   The card itself says nothing, so a user may read "Weber B = 44B". Fix: add a card-level line stating that this is
   AO/OTA 2018 and that the compendium does not state a correspondence to Weber, or show that line when matched by a
   Weber alias.
2. Minor. def.44b says the fibular fracture "crosses the level of the syndesmosis". The source gives only the word
   "transsyndesmotic". Same for "lies below" (44A) and "lies above" (44C). These are glosses of the prefix, accurate but
   not stated. review.md For Hassan 2 already concedes this for the whole definition set; the glosses should be labelled
   as the pack's paraphrase or trimmed to the titles.
3. Minor. def.44b says "with or without a fracture of the posterolateral rim". The source only describes 44B3 as having
   it with a medial injury; 44B1 and 44B2 do not state "without". The card text also leaves open a Volkmann fragment
   with no medial injury, which the source does not provide a group for. Reword to match the 44B1/B2/B3 headings.
4. Minor. Locators for tab.groups and tab.subgroups give p69 only; the tables span PDF pp 68-72. Use a range.
5. Minor. manifest.json scopes S1 to "pp S65-S69", but pit.* cite the Appendix S168-S169. Add the appendix pages to
   the source scope.
6. Minor. `applies_to.modality` is XR only, yet several subgroups are not plain-film diagnoses (ligament ruptures
   44A1.1, 44A2.1, 44A3.1, 44B2.1, 44B3.1, 44C*.1; the t/u syndesmosis qualifiers). The source gives no imaging method, so the
   card is right not to say how; the XR scope is the brief's choice. Worth a one-line note that the card lists codes, not
   what plain film can show.
7. Minor. Generic aliases "malleolar fracture classification" and "ankle fracture classification" will collide if a
   Lauge-Hansen or other ankle pack is added later. Consider dropping them or checking at that point.

## For Hassan items in review.md

1. Weber equivalence decision: agree with not writing an equivalence as a card fact and with needing the Danis (1949)
   or Weber (1972) source before doing so. Disagree that the aliases alone settle it: they carry an implied claim to
   the reader. See finding 1. Under standing rule (ask for blocked sources) this is a source Hassan would need to
   supply.
2. Definitions paraphrase titles: agree, with the added point that some paraphrase adds meaning (findings 2 and 3).
3. Qualifications listed, figures not reproduced: agree. Letters and captions are complete and correct.
4. XR only: agree it follows the brief; see finding 6 for the caveat that the source is not modality-specific and some
   subgroups are not plain-film calls.
