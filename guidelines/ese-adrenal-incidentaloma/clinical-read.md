# Independent clinical read: ese-adrenal-incidentaloma@2023.1

Reader: fresh agent, read-only. Source: S1, Fassnacht M et al., Eur J Endocrinol 2023;189(1):G1-G42,
doi 10.1093/ejendo/lvad066 (PDF on disk; PDF page = journal page). I read pp 1-4 (abstract, summary of
recommendations, §2.1), 16-20 (§5.2, Table 4), 24, 26, 30-32 (§5.6.2, §5.6.3). I viewed Figures 4 (p17), 5 (p18)
and 9 (p31) as images. Band semantics checked against `schema.py`: a band's `min` defaults to inclusive and its
`max` to exclusive.

**Verdict: not ready.** There is one Critical finding (the HU band edges) and two Important findings (golden cases
that encode the rounding, and the known-malignancy outcome). Size and age edges, the under-40 route and the
clearly-benign route are faithful. Every other outcome keeps the source's recommend/suggest strength except one
clause in `indeterminate_mdt`.

## Findings

### Critical

**C1. HU edges at 10.5 and 20.5 contradict the source's explicit wording.**

S1 never says to round attenuation. Its wording is explicit throughout:
- **≤ 10:** "HU ≤ 10" (R.2.3 p17; Figure 5 column 1; Table 4 "≤ 10 HU"; abstract).
- **> 10:** "If HU > 10: see Figure 5" (Figure 4, p17); "Only necessary in adrenal tumors with HU > 10" (Figure 4
  note 3); "The panel decided to divide the group of tumors with HU > 10 into 3 groups" (R.2.4 reasoning, p19).
- **11-20:** "unenhanced HU between 11 and 20" (R.2.4); "HU 11-20" (R.2.6; Figure 5 columns 2-3).
- **> 20:** "unenhanced HU > 20" (R.2.5, R.2.6; Figure 5 columns 3-4).

So the middle group is "over 10 and up to 20": "11-20" names the integer values of that group, not a rounding rule.
Under the standing ruling, the edges must be:

| band | edge |
|---|---|
| `le10` | `max: 10, max_inclusive: true` |
| middle band | `min: 10, min_inclusive: false, max: 20, max_inclusive: true`; relabel "over 10 to 20 HU" |
| `gt20` | `min: 20, min_inclusive: false` |

What goes wrong today:
- A homogeneous mass of 10.1-10.4 HU gets "No further imaging required". This is false reassurance. The source
  sends any mass over 10 HU to Figure 5 and to metanephrines.
- A mass of 20.1-20.4 HU under 4 cm goes to "additional imaging" instead of MDT discussion.
- A mass of 20.1-20.4 HU at 4 cm or more goes to `indeterminate_mdt` instead of `high_risk`.

Remove "(whole HU; half up)" from the `hu_band` locator, and fix the `tab.fig5` wording to match.

### Important

**I1. Golden cases encode the rounding.**
- "2 cm homogeneous 10.4 HU: rounds to 10, benign" must become `additional_imaging`. Add `age: 60`, or the engine
  will ask for age.
- "3.9 cm homogeneous 20.4 HU, age 55" must become `indeterminate_mdt`, with `hu_band: gt20`.
- Rename the 10.5 HU and 20.5 HU cases. Their outcomes stand, but they no longer "round".
- Add exact-edge cases: 10 HU homogeneous goes to `benign_attenuation`; 20 HU homogeneous, 2 cm, age 60 goes to
  `additional_imaging`.

**I2. The known-malignancy outcome (`does_not_apply`) misstates and trims §5.6.3 and Figure 9.**

Excluding these patients as an eligibility input is faithful: §2.1 p4 says masses found at staging or follow-up "do
not meet the strict definition". The outcome text is not faithful:
- **Classification.** It says the ESE pathway "does not apply". §5.6.3 p30 says "In principle ... the same
  recommendations apply as described above (Figure 9)". It should say that ESE's separate pathway for known
  extra-adrenal malignancy (Figure 9) applies.
- **Recommendation.** "Manage per the clinical context" is a library addition and is not labelled as one.
- **Caveat.** It drops strengths. R.6.3.2 "recommend" (no further specific adrenal *imaging* follow-up; the word
  "imaging" is lost) and R.6.3.4 "suggest" (FDG-PET/CT, resection or biopsy) are both missing.
- **Missing branch.** The caveat omits R.6.3.4's other branch: "In all other patients, we recommend imaging
  follow-up at the same interval as imaging for the primary malignancy". It also omits:
  - Figure 9's benign-branch question (relevant hormone excess?);
  - R.6.3.3 (strong FDG uptake suggests metastasis; with moderate or no uptake, at least unenhanced CT is
    recommended);
  - Figure 9 note 1 (life expectancy).

These masses are common on staging CT, so this outcome will fire often.

### Minor

**M1. One `indeterminate_mdt` clause loses its strength.** "If still indeterminate and not operated, noncontrast CT
or MRI in 6-12 months" reads as part of "Suggest". R.2.6 says "we recommend interval imaging in 6-12 months". The
source is itself inconsistent: R.5.2 p26 says "we suggest one repeat". Say "ESE recommends (R.2.6)" and note the
R.5.2 wording.

**M2. Under-40 urgency is missing from three outcomes.** R.6.2.1 ("We recommend urgent assessment of an adrenal
mass ... <40 years") applies to any adrenal mass, not only indeterminate ones. `benign_attenuation`,
`benign_other` and `needs_unenhanced_ct` carry no urgency caveat for under-40s. The §5.6.2 reasoning also prefers
MRI in young patients generally, whereas the `needs_unenhanced_ct` caveat names only children, adolescents and
pregnant women; that is faithful to the R.6.2.2 text.

**M3. Unlabelled library addition in `benign_other`.** Caveat 0, "a firm benign diagnosis is needed to use this
route", is the library's own condition and is not labelled as one. Figure 4 ("Non-functioning, benign lesion (e.g.
adenoma, (myelo-)lipoma) → No further investigation") is a stronger anchor for this route than Table 4 note a.
Cite it.

**M4. Metanephrines conflict not recorded.** The abstract says every patient needs metanephrines. Figure 4 note 3
and R.3.9 limit them to HU > 10 or features not typical of adenoma. The pack follows Figure 4 and R.3.9, which is
right, but the conflict is not in For Hassan.

**M5. MRI-only characterisation goes to `needs_unenhanced_ct`.** A homogeneous mass characterised only on
chemical-shift MRI routes to "unenhanced CT recommended". This is faithful to R.2.2, and the caveat carries the R.2.3
reasoning (an expert MDT may accept unambiguous chemical-shift MRI). But `applies_to` lists MRI, so add this to For
Hassan as a known consequence.

## Size, age and other band edges (correct)
- **Size:** "≥ 1 cm" (§2.1 p4); "< 4 cm" (R.2.4, R.2.6, Figure 5 columns 2-3); "≥ 4 cm" (R.2.5, R.2.6, Figure 5
  column 3). Figure 5 column 4 and the abstract say "> 4 cm". The bands `lt1` [<1), `1to4` [1, 4) and `ge4` [≥4)
  match the text. The text explicitly fills exactly 4.0 cm (R.2.5 ≥ 4 cm).
- **Age:** "<40 years" (R.6.2.1, R.6.2.3). `lt40` / `ge40` is correct.

## Rules and routes
- **Partition.** Cases 0-8 check out against Figure 5 and R.2.3-2.6.
- **Heterogeneous masses.** They are routed by size alone. Table 4 note a says nonhomogeneous lesions should not go
  to MRI or washout, and Figure 5 needs no HU for them.
- **Under-40 route.** Faithful. R.6.2.1 is "recommend" (urgent assessment) and R.6.2.3 is "suggest" (resection if
  indeterminate on imaging); both strengths are kept. Figure 5 column 4 stays `high_risk` with an urgency caveat,
  and Figure 4 note 2 supports that. The conditional wording ("if the mass is indeterminate on imaging") is right
  for column-2 masses, where additional imaging could still settle the question.
- **Clearly-benign route.** Faithful in substance. R.5.1 says "We recommend against further imaging during
  follow-up ... clear benign features" (strength kept). Table 4 note a and Figure 4 support it.
- **Known-malignancy exclusion.** The eligibility input is faithful. The outcome text is not (see I2).

## Strength check by outcome
| outcome | verdict |
|---|---|
| `below_threshold` | No graded recommendation in §2.1; the wording is faithful. |
| `benign_attenuation` | Kept (R.2.3, R.3.2, R.3.10, R.4.2 "recommend against"). |
| `benign_other` | Kept (R.5.1). |
| `needs_unenhanced_ct` | Kept (R.2.2 recommend, R.6.2.2 suggest). |
| `additional_imaging` | Kept (R.2.4 suggest; "alternatively ... could be performed"; R.1.1 recommend). |
| `indeterminate_mdt` | Suggest kept; the R.2.6 "recommend interval imaging" clause is lost (M1). |
| `high_risk` | Kept (R.2.5 suggest MDT, suggest staging, "recommended" follow-up; R.2.8 suggest). |
| `young_indeterminate` | Kept. |
| `does_not_apply` | Lost (I2). |

## Golden cases
Twenty of 22 are correct under the source as written. Two are wrong under exact edges: 10.4 HU and 3.9 cm / 20.4 HU
(I1). The `needed` cases (age only; both eligibility inputs; appearance plus attenuation) are right. Suggested
additions:
- exact 10 HU and 20 HU (I1);
- 3 cm heterogeneous with an unenhanced HU of 5, age 60, which should go to `indeterminate_mdt` (heterogeneity wins
  over attenuation).

## For Hassan verdicts
1. **4 cm edge. Agree.** The text (R.2.5 "≥ 4 cm") fills the figure's gap. Figure 5 column 3 itself uses "≥ 4 cm"
   for HU 11-20, so 4.0 cm counting as "4 cm or more" is consistent across the figure.
2. **HU rounding. Disagree.** The source's wording is explicit (≤ 10, > 10, 11-20, > 20) and it gives no rounding
   instruction. The edges sit exactly at 10 (inclusive below) and 20 (inclusive below). 10.4 HU is over 10 and is
   not benign. See C1.
3. **Under 1 cm. Agree.** §2.1: work-up "only in adrenal masses ≥ 1 cm, unless clinical signs and symptoms
   suggestive of adrenal hormone excess"; the outcome keeps the exception.
4. **Known malignancy to `does_not_apply`. Agree with the exclusion; disagree with the outcome text.** See I2.
   A sibling Figure 9 pack is worth doing, since staging CT is common.
5. **Combined eligibility input. Agree.** §2.1 excludes both scenarios in the same way.
6. **`clearly_benign`. Agree.** R.5.1, Table 4 note a, and Figure 4's "(myelo-)lipoma → No further investigation"
   support it. Label the caveat-0 condition as a library addition (M3).
7. **Under 40. Agree.** R.6.2.3 replaces Figure 5 columns 2-3, and column 4 stays high risk. Add R.6.2.1 urgency
   to the benign outcomes for under-40s (M2). Pregnancy as a caveat only is acceptable.
8. **No unenhanced CT. Agree.** Heterogeneous masses need no HU in Figure 5. MRI-only cases fall to
   `needs_unenhanced_ct` (M5).
9. **Maximum diameter. Agree.** R.5.2 measures growth in maximum diameter.
10. **Growth as caveat only. Agree.** The wording matches R.5.2 (">20% in maximum diameter (in addition to at least
    a 5 mm increase)", suggest).
