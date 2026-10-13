# Clinical read: nhs-aaa-surveillance@2025.1

Independent read-only review (guideline-pack skill, step 8). Read against S1 on disk: the GOV.UK page "Abdominal aortic
aneurysm screening pathway requirements" (NHS England, updated 25 September 2025). I read the text extract in full and
checked the HTML for anything the extract dropped. The two match; the HTML has no rounding rule, no mm values and no
measurement plane. Also checked: the engine's band semantics (`schema.py`: min inclusive and max exclusive by default),
the card lookup (`matcher.py` uses `lib.find(name)` on display, system and aliases), and the house rules in
`AUTHORING-RULES.md` and `TRAPS.md`.

## Verdict

**Not ready to ship: 2 Important, 4 Minor, 0 Critical.** The pathway logic, intervals, referral timings and eligibility
are faithful to S1. The two Important findings are both band edges. Each places the edge on the wrong side of an
explicit word in the source ("less than 3.0cm", "5.5cm and larger", "more than 1cm"). The growth edge errs towards
missed referral. The fix is small: change three numbers and four golden cases.

## Findings

### I-1 (Important): the growth edge at 1.05 cm contradicts "more than 1cm" and errs towards missed referral

S1 says twice that men "whose aneurysm has grown by more than 1cm in 12 months" are referred ("AAA screening";
"3. Referral"). That is a strict `> 1.0`. The pack bands `gt1` as `>= 1.05`, so recorded growth of 1.01 to 1.04 cm gives
`small_surveillance` or `medium_surveillance` when the source says refer. The golden case "growth edge: 1.04 cm …
small_surveillance" encodes the miss.

- TRAPS.md licenses half-up edges only "when the source says 'round to the nearest millimetre'". S1 has no rounding
  rule anywhere, and AUTHORING-RULES says edge sides are "copied from the source's own wording (<, ≤, ≥, 'to')".
- Growth is a difference of two measurements, which the settle model may compute (for example 4.15 to 5.18 cm). Values
  between 1.00 and 1.05 can occur, especially from mm or two-decimal dictation.
- The direction is unsafe: these are men the programme would refer within one working day.

**Fix:** `growth_band` with `le1` = `max 1.0, max_inclusive true` and `gt1` = `min 1.0, min_inclusive false`. Change the
case at 1.04 cm to `growth_refer` (rename it) and keep the 1.0 cm case as `medium_surveillance`. Replace the 1.05 cm
case with 1.01 cm, giving `growth_refer`.

### I-2 (Important): the diameter edges at 2.95 and 5.45 cm contradict explicit source wording

S1 gives two explicit boundaries, "no AAA found (less than 3.0cm)" and "large AAA (5.5cm and larger)". Half-up
rounding breaks both:

- **2.95 to 2.99 cm** is "less than 3.0cm" in the source, but the pack calls it a small AAA. The card prints
  "Small AAA (3.0 to 4.4 cm)" for a 2.96 cm aorta and enters the man into yearly surveillance, when the programme would
  discharge him.
- **5.45 to 5.49 cm** is not "5.5cm and larger", but the card prints "Large AAA (5.5 cm or larger)" and triggers a
  one-working-day vascular referral.

Both errors fall on the over-treatment side, so no man is missed. They are still false class labels in a report, and
they break the house rules for the same reasons as I-1. The only true gaps in S1 are 4.4 to 4.5 cm and 5.4 to 5.5 cm.
The 3.0 cm edge has no gap at all.

**Fix (recommended):** read each range's lower bound as written. That gives `lt3 < 3.0`, `small [3.0, 4.5)`,
`medium [4.5, 5.5)` and `large >= 5.5`. This rule honours both explicit statements and closes the two gaps by treating
"3.0 to 4.4" as a range recorded to the nearest 0.1 cm, which matches the programme's 30–44 / 45–54 / ≥55 mm. It agrees
with half-up on every value recorded to 0.1 cm or whole mm; the two rules differ only on sub-millimetre values. Change
the edge cases to 2.99 → `no_aaa`, 3.0 → `small_surveillance`, 4.49 → `small_surveillance`, 4.5 → `medium_surveillance`,
5.49 → `medium_surveillance` and 5.5 → `large_refer`.

**Acceptable alternative:** keep half-up at 4.45 only, since that edge sits in a genuine gap and erring to 3-monthly
scans there is a defensible DECISION. The edges at 3.0 and 5.5 must still follow the text.

### M-1 (Minor): `non_visualised` also fires on a surveillance scan, with initial-screen wording

Rules case 1 does not check `prior_programme_scan`. S1 mentions the non-visualised aorta only for the screening test:
men "will receive a further invitation for screening", tracked by AAA-S11 "non-visualised initial screens". A man
already under surveillance whose aorta is not seen would not be "invited for AAA screening" again. S1 does not cover
that case.

**Fix:** either add `prior_programme_scan = false` to case 1 and send the surveillance case to `does_not_fit` (SOP), or
reword the recommendation to "A repeat programme scan will be offered", which is neutral to the scan type.

### M-2 (Minor): the `does_not_apply` text gives the wrong reason for the commonest out-of-programme case

When the case fires because `screening_programme = false`, for example an incidental AAA on CT in a 72-year-old man,
the classification reads "the programme screens men from 65 and does not routinely screen women or anyone already
treated". None of that is why it does not apply.

**Suggested wording:** "NHS AAA screening programme thresholds apply only to programme scans; the programme does not
routinely screen women, men under 65 or anyone already treated for an AAA." Keep "Manage per the clinical context."
That wording is right because it does not import the programme's intervals or referral timings. The non-programme
pathway is different: NICE NG156 refers all AAAs of 3.0 cm or more to vascular services, with different timings. NG156
is not a source here, so the card should not name it.

### M-3 (Minor): scope leaks in the reference text and one alias

These are the parts of the card that could read as general vascular-referral guidance on an incidental CT. Before an
eligibility outcome is reached, only the reference block, the aliases and the `applies_to` field are visible.

- `sum.3` is unqualified: "Small aneurysms get yearly surveillance scans … large aneurysms … are offered referral to
  vascular services." Shown alone on a CT card, it reads as general practice. Prefix it with "In the programme," or
  "Programme results:".
- `tab.results` is titled "AAA screening results", which is fine, but its "Next step" column reads as universal.
  "Referral to vascular services within one working day" is a programme timing. Consider a table title such as
  "NHS AAA screening programme: results and next step".
- The alias `"aaa surveillance"` is generic. Hospital vascular-lab surveillance of an incidentally found AAA is also
  "AAA surveillance", so the alias invites `lib.find` to pick this card outside the programme. Drop it, or keep only
  `"nhs aaa surveillance"`.
- What is already right: `applies_to.modality ["US"]` and `context ["screening"]`, the `screening_programme` gate as
  the first rule, `pit.programme_only`, and `def.surveillance` ("repeat programme scans"). Together these do keep the
  outcomes programme-only.

### M-4 (Minor): `dims: "max"` on `diameter_cm` is an unsourced choice

If a measurement is dictated as "AP 4.2 x TR 4.8 cm", the engine takes 4.8. S1 states no plane, and `how_stated`
says to "use the programme's own recorded diameter", which is a single figure, so the two instructions conflict. Taking
the maximum is the conservative choice and rarely matters on a programme scan. Either drop `dims` or add "(if two
diameters are given, the larger is used)" to `pit.plane` and For Hassan.

## Line-by-line check against S1

### Inputs

| input | verdict |
|---|---|
| screening_programme (eligibility) | ✓ The thresholds are defined only as "AAA screening results"; self-referred men over 65 are in-programme and correctly count as true. `how_stated` excludes incidental and diagnostic imaging. Good. |
| sex (eligibility) | ✓ "not routinely offered to … women" |
| previous_aaa_treatment (eligibility) | ✓ "anyone who has already been treated for an AAA"; mentioning EVAR or an open graft in `how_stated` is helpful |
| diameter_cm, `not_assessable` | ✓ The four size results; `not_assessable` maps to "aorta could not be visualised". See M-4 on `dims`. |
| prior_programme_scan | ✓ It is a structural input; it gates growth correctly |
| growth_12m_cm | ✓ "grown by more than 1cm in 12 months"; the example (4.1 to 5.3 cm = 1.2 cm) is correct |

### Bands

| step | verdict |
|---|---|
| diameter_band | ✗ at 2.95 and 5.45 (I-2); 4.45 is defensible as a gap decision |
| growth_band | ✗ at 1.05 (I-1) |

### Rules

Read against S1, cases 0 to 7 partition the space correctly. Eligibility is tested first and needs all three in-scope
values for every other case. Growth is read only for small and medium aneurysms (through `none`), so a large AAA never
asks for growth, and the initial screen never asks for it either. Small or medium with growth over 1 cm → growth_refer
matches "those whose aneurysm has grown by more than 1cm in 12 months". Under 3.0 cm on the initial screen → no_aaa
matches "do not need any more scans and will not receive any more invitations". Case 1: see M-1.

### Outcomes

| outcome | verdict |
|---|---|
| does_not_apply | ✓ It keeps "not routinely". See M-2 on the stated reason. |
| non_visualised | ✓ for the initial screen; see M-1 |
| no_aaa | ✓ |
| small_surveillance | ✓ "offer yearly surveillance scans to men with small aneurysms"; the nurse specialist appointment is "all screen detected men" ✓ |
| medium_surveillance | ✓ "every 3 months to men with medium size aneurysms" ✓ |
| growth_refer | ✓ "within one working day"; "vascular specialist within 2 weeks of his scan" ✓. "Offer referral" matches "offered a referral". |
| large_refer | ✓ The same timings. The caveat "fit men who opt for surgery … within 8 weeks of the scan" is from section 4 ✓ |
| does_not_fit | ✓ It is labelled as a library addition, with a correct locator to the SOP sentence |

### Reference

`sum.1`, `sum.2`, `def.surveillance` and `pit.*` are faithful. For `sum.3` and `tab.results`, see M-3. `pit.programme_only`
lists "men under 65", which correctly carries the fourth scope fact that the inputs leave out.

## Golden cases

There are 27 cases. They reach every outcome, and the expected results match the logic as written. Against the source:

- **Change under I-1:** "growth edge: 1.04 cm … small_surveillance" should be `growth_refer`, and the 1.05 cm case
  becomes redundant (use 1.01 cm).
- **Change under I-2:** "2.95 cm … small AAA" should be `no_aaa`, and "5.45 cm … large" should be `medium_surveillance`.
  If the 4.45 decision changes too, so does "4.45 cm … medium".
- The remaining cases are correct: the typical values, the eligibility exits, growth exactly 1.0 cm (no referral, which
  is correct for "more than"), shrinkage, a large AAA without growth, the surveillance case under 3.0 cm, and all four
  `needed` cases.
- **Gap:** no case covers a non-visualised aorta on a surveillance scan (relevant to M-1), or a man with
  `screening_programme` unknown, which would show that the gate is asked first.

## For Hassan items

1. **Half-up band edges (DECISION): disagree in part.** Half-up is reasonable only for the two genuine gaps (4.4 to 4.5
   and 5.4 to 5.5 cm). S1 has no rounding rule, so TRAPS' half-up licence does not apply. Extending half-up to 3.0 and
   5.5 overrides "less than 3.0cm" and "5.5cm and larger", and extending it to growth overrides "more than 1cm" in the
   unsafe direction. Use 3.0 / 4.5 / 5.5 (lower bound as written) and `> 1.0`; see I-1 and I-2.
2. **Under 3.0 cm on surveillance → `does_not_fit` (DECISION): agree.** This is the right call and follows
   AUTHORING-RULES ("never to the nearest class"). The dangerous alternative, falling through to `no_aaa` ("no further
   scans or invitations"), would discharge a man with a known aneurysm on one low reading, and the pack avoids it. S1
   does point to the SOP for exit points, and "Manage per the AAA screening standard operating procedure" is correctly
   neutral and invents no rescan or discharge rule. Keep the caveat labelling it a library addition.
3. **Growth measured as the 12-month increase (DECISION): agree.** It is the plain reading of "grown by more than 1cm in
   12 months". The input asks for the 12-month increase rather than annualising shorter intervals, which avoids
   inflating noise from 3-monthly medium scans. Revisit if the SOP defines it differently.
4. **"Men under 65" left out as an eligibility input: agree.** The 3-input cap in AUTHORING-RULES forces a choice, and
   age is the one that `screening_programme` makes redundant: men under 65 are not invited, so a programme scan implies
   the age. The real out-of-scope case, a man under 65 with an incidental AAA on CT, already exits through
   `screening_programme = false`. Dropping age also avoids a wrong exclusion: the programme's year-of-65 invitation means
   a man can be 64 at his scan, so an `age < 65` input could exclude a genuine programme scan. The fact is still carried
   in `pit.programme_only`; add it to the `does_not_apply` wording as well (M-2).
5. **Measurement plane not stated: agree.** S1 is silent, so the pack correctly does not assert one. Resolve the
   conflict with `dims: "max"` (M-4).
6. **Unfiled SOP, clinical guidance and pathway figure: agree.** Nothing in the entry rests on the figure. If Hassan can
   supply the AAA screening SOP, it is the source that settles item 2 (exit points) and possibly the rounding question.
