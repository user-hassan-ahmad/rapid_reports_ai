# Clinical read: aspects@2000.1

Independent read, 2026-10-12. I read the pack (entry.json, cases.json, review.md, manifest.json, evidence.md) against
the primary source, Barber PA et al., Lancet 2000;355:1670-4 (`sources/61e2…805e.pdf`). I viewed all four article pages
as images, and Table 1 again at 300 dpi. I edited nothing else.

## Verdict

**Not ready as it stands.** Every number the pack quotes matches the source, and the Table 1 inversion is handled
correctly. There are no Critical findings. Six Important findings need fixing first:

- one classification turns the source's statement round;
- the above-7 caveats are missing from the score of 10;
- the rounding puts a non-integer 7.5 on the favourable side of the threshold that decides the outcome;
- a caveat attached to ASPECTS 0 reads as thrombolysis-eligibility advice;
- "14 times the risk" is quoted without its interval;
- the tier choice conflicts with the pack skill's own rule.

## 1. Statistics and facts checked against the source

| pack item | source | result |
|---|---|---|
| 10 points, minus 1 per region; normal CT = 10; 0 = diffuse ischaemia throughout MCA territory | p2 (journal 1671), Procedures | ✓ |
| C, L, IC = 3 points; I + M1-M6 = 7 points; M4-M6 immediately superior to M1-M3, rostral to the basal ganglia | p2, Figure 1 legend and image | ✓ |
| two standard axial cuts (thalamus/basal ganglia; just rostral to the ganglionic structures) | p2, Procedures | ✓ |
| early ischaemic change = focal swelling or parenchymal hypoattenuation; hypoattenuation definition | p2, Procedures | ✓ |
| 156 patients, IV alteplase within 3 h, 10 mm non-contrast CT | p2 Procedures; p3 Results | ✓ |
| anterior circulation only; 23 posterior-circulation patients not analysed | p1/p2 Patients; p3 Results | ✓ |
| threshold of 7 or less vs above 7 "suggested" by "a review of the data" | p2, Statistics | ✓ (wording fair) |
| functional outcome: sensitivity 0.78, specificity 0.96, OR 82 (23-290) | p3, Table 1 and Results | ✓ |
| sICH: sensitivity 0.90, specificity 0.62, OR 14 (1.8-117) in the table; text gives 14 (2-117) | p3, Table 1 and Results | ✓ |
| sICH about 1% above 7 | p4, Discussion | ✓ (1/91 = 1.1%) |
| "do not exclude from thrombolysis"; outcome without treatment unknown; randomised validation needed | p4, Discussion | ✓ |
| kappa for 7 or less vs above 7: 0.39-0.69 without clinical information, 0.71-0.89 with the affected hemisphere | p4, Table 2 (0.69/0.39/0.47; 0.85/0.71/0.89) | ✓ |
| median score 8 (case name) | p3, Results | ✓ |
| region counts: 8-9 = one or two regions, 1-7 = three to nine | arithmetic, 10 minus score | ✓ |
| locators (pages and sections) | all checked | ✓ |

### Table 1 label inversion (For Hassan 1)

Confirmed. The printed ASPECTS rows read "≤7 (n=89)*: 71 independent / 18 dependent or dead; sICH 1 yes / 90 no" and
">7 (n=65): 3 / 62; 9 / 56". Six pieces of evidence show the labels are swapped and the numbers are not:

- The text says 65 patients scored 7 or less and 89 more than 7.
- Figure 2 puts independence at scores 8 to 10 and almost none at 7 or below.
- The footnote "*n=91 for symptomatic haemorrhage analysis" belongs to the larger group: 89 plus the two patients
  without a 3-month Rankin score, neither of whom had sICH. That group is above 7.
- The published statistics only reproduce under the swapped reading:
  - sensitivity for dependence or death is 62/80 = 0.775 (printed 0.78);
  - specificity is 71/74 = 0.959 (printed 0.96);
  - crude OR is (62×71)/(3×18) = 81.5 (printed 82);
  - for sICH, sensitivity is 9/10 = 0.90, specificity 90/146 = 0.616 (printed 0.62), and OR (9×90)/(1×56) = 14.5
    (printed 14).
- The MCA-rule rows carry the same n=89/n=65 labels and asterisk pattern, so they are probably inverted too. The pack
  does not use them.
- Corrected absolute rates: sICH 9/65 (13.8%) at 7 or less and 1/91 (1.1%) above 7. Dependence or death: 62/65 at 7
  or less and 18/89 above 7.

**Agree** with following the text and figure, and with quoting no group counts. One small fix: review.md says
"Table 1's printed rows also show 1 of 91 for the group scoring above 7". The printed label on that row is "≤7", so the
sentence should say "under the corrected labels".

## 2. Bands and outcomes

### Important: "(normal CT)" in the ASPECTS 10 classification turns the source round

The source says "A normal CT scan has an ASPECTS value of 10". The converse does not hold. A score of 10 means only that
none of the ten MCA regions shows early ischaemic change. The scan may still show:

- haemorrhage;
- an old infarct;
- ACA or posterior-circulation ischaemia;
- a hyperdense MCA sign.

Reword it to: "ASPECTS 10: no early ischaemic change in any of the ten scored MCA regions." Drop "(normal CT)". The golden
case name "Normal CT scores 10" is the right way round and can stay.

### Important: the 1% sICH line is on 8-9 but not 10 (For Hassan 5: disagree)

The source gives the 1% figure, and the threshold itself, for the whole above-7 group, and 10 is in that group. Leaving
both caveats off 10 creates an asymmetry the source does not support. A reader may infer either that 10 carries no
haemorrhage risk or that the risk at 10 is unknown.

Put the same above-7 caveats on 10:

- the sICH rate of about 1% in the cohort;
- the threshold chosen from a review of the data;
- the cohort caveat.

The alternative is to remove them from both. The pack should not claim that 10 does better than 8-9 (Figure 2 suggests
it, but the source gives no tabulated figure).

### Important: rounding non-integer scores half up (For Hassan 2: disagree)

ASPECTS is an integer by construction. A dictated "7.5" is not a valid score. It is a slip, an uncertainty between 7
and 8, or a transcription error, and 7 versus 8 is exactly where the pack's prognosis changes. Rounding half up silently
puts it on the favourable side, carrying the 1% sICH caveat.

The TRAPS rule on half-up edges applies when the source tells you to round. This source does not. Accept whole points
only, and send a non-integer to `needed` (ask) instead of banding it.

The edges at 0.5 and 9.5 are lower stakes but follow the same logic. Six golden cases (0.4, 0.5, 7.4, 7.5, 9.4, 9.5) would
change to `needed`.

### The 8-9 and 1-7 groupings (For Hassan 4: agree)

- The split at 7 is the source's.
- Separating out 0 and 10 is definitional: the source defines both scores.
- Grouping 8 with 9, and 1 with 7, adds no claim beyond "above 7" and "7 or less", as long as the classification
  text stays region-count and threshold only. It does now.
- Figure 2 supports where the threshold sits: 7 looks like 6 (about 5% independent), not like 8 (about 73%). Those
  figures are read off the bars, so do not quote them.
- Not subdividing 1-7 is right.

### Important: "about 14 times the risk"

The figure 14 is an odds ratio from 10 sICH events in total. Its 95% CI is 1.8 to 117 (2 to 117 in the text). The
crude risk ratio is 13.8% / 1.1%, which is about 12.5. The authors' Discussion does use the phrase "14 times that of
patients with a score greater than 7", so the wording is sourced. Without the interval, though, it overstates how
precise the estimate is.

Either:

- quote "odds ratio 14 (95% CI 1.8-117; 10 haemorrhages in total)"; or
- give the absolute rates, about 14% (9/65) versus about 1% (1/91).

The same applies to `sum.3` only if it gains a number.

### Minor: the 1% line drops its source context

The Discussion qualifies the 1% figure as "slightly higher than ... placebo in the NINDS trial (0.6%)", and it rests on
1 event in 91. As written ("about 1%" in treated patients), the caveat reads as reassurance. Add "(1 of 91 patients)".

## 3. Could any caveat be read as thrombolysis or thrombectomy eligibility advice?

### Important: the "do not exclude" caveat is attached to ASPECTS 0

The caveat "The authors state this must not be read as a reason to exclude patients scoring 7 or less from
thrombolysis" sits on `aspects_1_7` and `aspects_0`. It is faithful to the Discussion, but it is eligibility advice in
negative form. The brief's premise, that the source gives no eligibility advice, is therefore not quite true: the source
gives this one negative statement. It also speculates in the Discussion that a high score outside the time window
"might be considered for thrombolytic therapy". The pack rightly leaves that out.

Attached to ASPECTS 0, the caveat goes beyond the cohort. Four patients were withheld from treatment because their
early changes were "too extensive", so whole-territory change was screened out of the treated group. And in current
UK practice, extensive established hypoattenuation is commonly treated as a contraindication.

A card line under "ASPECTS 0" saying it "must not be read as a reason to exclude ... from thrombolysis" can be read as
support for thrombolysing a whole-MCA-territory infarct.

Recommendation:

- Remove the caveat from the outcomes.
- Keep it as the `pit.exclusion` reference pitfall, where it reads as a statement about the study.
- If an outcome caveat is wanted, reword it to the study limitation with no directive: "The study could not show how
  these patients would have fared without treatment; the authors called for randomised validation."

### Minor: a cohort caveat on every outcome (For Hassan 8: agree, with an addition)

Keeping thrombectomy selection out of scope is right; S1 does not cover it. In 2026, though, ASPECTS is read mainly in
a thrombectomy context. The sensitivity and specificity for dependence or death in `aspects_1_7` comes from IV
alteplase alone (1996-99), so it should not be carried over to patients scoring 3 to 7 who are considered for
thrombectomy.

The sourced cohort facts (IV alteplase within 3 h, March 1996 to May 1999, 156 patients) are in `pit.cohort` only. Put
a short form of them on every outcome that carries a prognosis: "Figures are from 156 patients treated with IV alteplase
alone within 3 h, 1996-99." That keeps the prognosis bounded without the pack saying anything about thrombectomy.

None of the other caveats reads as eligibility advice.

## 4. Pack type: tier 1 or a tier 2 card (For Hassan 6: disagree)

The pack skill's table (SKILL.md, step 1) says: "is a grade with no management attached → **tier 2 reference card**".
The kellgren-lawrence pack was filed as tier 2 under that "standing ruling" (no management or prognosis). The aspects
pack has prognosis but no management, and every outcome has an empty recommendation. So it fits tier 2 more naturally.

Practically, Apply would add a classification that restates the dictated number ("ASPECTS 8 to 9: early ischaemic change
in one or two of the ten scored MCA regions"). The radiologist has already dictated the score, so that adds little.
Meanwhile the outcome caveats travel with the card. Those caveats are prognosis from a 2000 single-cohort study and,
as written, a thrombolysis statement, and they are exactly the content that should stay read-only reference.

As a tier 2 card, all the high-value content keeps its locators and serves the reading pane and Ask:

- the region map;
- the definitions;
- the discrimination table;
- the pitfalls.

The pack can become tier 1 later, with no rewrite, if a UK source (for example a NICE or RCR thrombectomy pathway)
attaches management to score bands.

If Hassan keeps tier 1, the minimum is:

- outcomes reduced to a descriptive classification;
- prognosis kept in caveats with its interval (section 2);
- the "do not exclude" line out of the outcomes (section 3).

## 5. Eligibility and does_not_apply

- **Scope clause: correct.** Anterior circulation is the only scope clause, and it is sourced (For Hassan 3: agree).
  Treating the alteplase cohort and non-contrast CT as caveats rather than exclusions is right.
- **Minor: empty recommendation on `does_not_apply`.** The spec (section 3.6: "its recommendation says to manage on
  clinical context") and every other pack with a `does_not_apply` outcome use "Manage per the clinical context." Here
  it is empty.
- **Minor: asking for the circulation.** When "ASPECTS n" is dictated, the circulation question is almost always
  redundant, because the score is MCA-only by construction. Inference may be acceptable here.
- **Minor: alias collision.** The alias "ASPECTS" could match a dictated "pc-ASPECTS", which is a different
  posterior-circulation score not covered by S1. Routing that to `does_not_apply` is the right result. Make sure the
  matching does not apply the MCA bands to it.

## 6. Golden cases

All 17 cases match the current logic:

- 10 and 0 are labelled origin "source";
- the integer edges at 0, 1, 7, 8, 9 and 10 are correct;
- the posterior-circulation cases and the three `needed` cases behave as intended.

Changes needed:

- **Minor:** if the integer-only fix in section 2 is adopted, the six half-point cases become `needed`.
- **Minor:** add an out-of-range case (11 or -1), which should be rejected or asked, if the validator does not
  already cover min and max.

## 7. For Hassan, item by item

| # | item | view | why |
|---|---|---|---|
| 1 | Table 1 labels inverted | Agree | Counts, the footnote, Figure 2 and recomputed statistics all confirm it; fix the "1 of 91" wording in review.md |
| 2 | Half-up rounding at 0.5 / 7.5 / 9.5 | Disagree | Non-integer ASPECTS is invalid; 7.5 straddles the one decisive threshold; ask instead |
| 3 | Anterior circulation is the only scope clause | Agree | Sourced; the cohort belongs in caveats. Put a cohort caveat on every prognostic outcome |
| 4 | 8-9 and 1-7 grouping | Agree | Adds no claim beyond the source's split, provided classifications stay descriptive |
| 5 | 1% line under 8-9 only | Disagree | 10 is in the above-7 group; repeat the above-7 caveats under 10 |
| 6 | Tier 1 with empty recommendations | Disagree | SKILL.md routes "grade with no management" to tier 2 (kellgren-lawrence precedent); Apply adds nothing the dictation lacks |
| 7 | Mirror source | Agree | Layout and text match the publisher's. Minor slips: review.md names the text file "61e2…a5b9" (actual "…805e"); manifest `retrieved` is 2026-10-13, a day after today |
| 8 | Later ASPECTS use out of scope | Agree | Right; add the sourced cohort caveat so alteplase-era prognosis is not read in a thrombectomy context |
