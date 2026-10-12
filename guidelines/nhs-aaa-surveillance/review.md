# Review: nhs-aaa-surveillance@2025.1

Read side by side with S1, the GOV.UK HTML page "Abdominal aortic aneurysm screening pathway requirements" (NHS England,
updated 25 September 2025), via its text extraction. The page is page-less, so every locator uses `section`. The
end-to-end pathway figure on the page is an SVG with empty alt text and was not filed; its accessible text-only version
is a separate publication, also not filed. Nothing in this entry rests on the figure.

Pack type: tier 1 algorithm (aortic size and growth → screening result → surveillance interval or referral).

## Checklist

### Inputs
| input | verdict |
|---|---|
| screening_programme (eligibility) | ✓ "AAA screening": the thresholds are the programme's own results |
| sex (eligibility) | ✓ "AAA screening": not routinely offered to women |
| previous_aaa_treatment (eligibility) | ✓ "AAA screening": not routinely offered to anyone already treated for an AAA |
| diameter_cm, state not_assessable | ✓ "AAA screening" (four results by size, in cm); not_assessable = "aorta could not be visualised" (2. Screening test) |
| prior_programme_scan | ✓ "Surveillance" section; gates the growth input so the initial screen never asks for growth |
| growth_12m_cm | ✓ "grown by more than 1cm in 12 months" ("AAA screening"; "Referral"). How growth is measured is not stated (For Hassan) |

### Bands
| step | edges | verdict |
|---|---|---|
| diameter_band | <3.0 / 3.0–<4.5 / 4.5–<5.5 / ≥5.5 cm | ✓ source: "less than 3.0cm", "3.0cm to 4.4cm", "4.5cm to 5.4cm", "5.5cm and larger". The explicit edges at 3.0 and 5.5 follow the wording; the 4.4–4.5 and 5.4–5.5 gaps close at the next range's lower bound (For Hassan, DECISION) |
| growth_band | ≤1.0 / >1.0 cm | ✓ source: "more than 1cm", strict |

### Rules cases (pathway)
| # | result | verdict |
|---|---|---|
| 0 | does_not_apply | ✓ "AAA screening" scope: programme scan, women, treated AAA |
| 1 | non_visualised | ✓ "2. Screening test": aorta not visualised → further invitation; inconclusive scans monitored (AAA-S11). Fires on surveillance scans too, so the recommendation is worded neutrally ("a further programme scan will be offered") and a caveat says the source covers only the initial screen |
| 2 | no_aaa | ✓ "<3.0cm"; "do not need any more scans and will not receive any more invitations" |
| 3 | does_not_fit | library addition: under 3.0 cm on a surveillance scan is not defined; S1 points to the SOP for exit points (For Hassan) |
| 4 | small_surveillance | ✓ "offer yearly surveillance scans to men with small aneurysms"; nurse specialist appointment |
| 5 | medium_surveillance | ✓ "every 3 months to men with medium size aneurysms"; nurse specialist appointment |
| 6 | growth_refer | ✓ "those whose aneurysm has grown by more than 1cm in 12 months … referral to vascular services" ("AAA screening"; "Referral": within one working day; specialist within 2 weeks) |
| 7 | large_refer | ✓ "Men found to have a large aneurysm … referral"; within one working day; specialist within 2 weeks; surgery within 8 weeks for fit men who opt for it (section 4) |

Rules partition: eligibility first (any of the three exclusions → does_not_apply; all three in-scope values are
required for every other case); then the diameter band; growth is read only for small and medium, through
`none: growth_band = gt1`, so a man on his initial screen (growth not_applicable) gets the size outcome and a large
AAA never asks for growth. Gate 2 confirms totality.

### Outcomes
| outcome | verdict |
|---|---|
| does_not_apply | ✓ says the thresholds apply only to programme scans, and keeps "not routinely" for women, men under 65 and treated AAAs |
| non_visualised | ✓ neutral to scan type; caveat on the surveillance case |
| no_aaa | ✓ |
| small_surveillance | ✓; caveat restates the growth referral route (same section) |
| medium_surveillance | ✓; caveat as above |
| growth_refer | ✓; "{diameter_band}" is always small or medium when it fires |
| large_refer | ✓; caveat from section 4 ("treats all men who are fit and opt for surgery within 8 weeks") |
| does_not_fit | library addition, labelled in its caveat |

### Reference
summary sum.1–3, def.surveillance, tab.results (four rows, cell for cell from "AAA screening", "Surveillance" and
"Referral"), pitfalls: ✓ against the same sections.

### Golden cases
29 cases, all `ours` (the source has no worked examples). Every outcome reached; diameter edges 2.95/2.99 vs 3.0,
4.49/4.5 and 5.49/5.5, and growth 1.0 vs 1.01/1.04, tested both sides; a non-visualised surveillance scan is covered;
five cases assert `needed` (diameter, growth, prior scan, sex, programme scan). The prior-scan-unknown case needs both `prior_programme_scan` and `growth_12m_cm`, which is the
engine asking the prerequisite and the value it gates together.

## Gate 5 flags

| field | Jev | resolution |
|---|---|---|
| growth_band | 0.25 | confirmed: "grown by more than 1cm in 12 months" appears twice in S1 ("AAA screening"; "Referral") |
| pathway.case0 / outcome.does_not_apply | 0.19 / 0.24 | confirmed: "Screening is not routinely offered to … men under the age of 65, women, anyone who has already been treated for an AAA" |
| pathway.case1 | 0.47 | confirmed: "men whose aorta could not be visualised … will receive a further invitation for screening"; the neutral wording is ours (M-1) |
| pathway.case2 | 0.41 | confirmed: "no AAA found (less than 3.0cm)"; "do not need any more scans and will not receive any more invitations" |
| pathway.case3 / outcome.does_not_fit (+caveat) | 0.14 / 0.10 / 0.34 | expected: a library addition the source does not state; labelled and in For Hassan |
| pathway.case6 | 0.26 | confirmed: the "{diameter_band}" placeholder renders as an ellipsis; facts are in "AAA screening" and "Referral" |
| small/medium caveat0 | 0.34 / 0.34 | confirmed: growth of more than 1 cm in 12 months → referral applies to men under surveillance ("AAA screening"; "Referral") |
| def.surveillance | 0.47 | confirmed: "scanning men with aneurysms between 3cm to 5.4cm to check if their AAAs are getting bigger" |
| pit.plane | 0.33 | confirmed: S1 names only the clinical guidance; the "larger of two diameters" sentence is our `dims` choice (For Hassan) |
| tab.results | n/a | table not scored by gate 5; checked cell for cell against "AAA screening", "Surveillance", "Referral" |
| pit.programme_only | 0.40 | confirmed: programme scope in "AAA screening"; "AAAs found outside the programme" is our reading that the thresholds are the programme's own (covered by the screening_programme input) |

## Independent read and fixes

The read (`clinical-read.md`) had 0 Critical, 2 Important and 4 Minor findings, all fixed:
- I-1: growth edge now strict >1.0 cm (was ≥1.05).
- I-2: diameter edges now 3.0 / 4.5 / 5.5 cm per the source's wording (were 2.95 / 4.45 / 5.45 half up).
- M-1: non_visualised wording neutral to scan type, with a caveat; surveillance case added.
- M-2: does_not_apply now says the thresholds apply only to programme scans.
- M-3: sum.3 prefixed "In the programme", table titled as the programme's, generic alias "aaa surveillance" dropped.
- M-4: `dims: "max"` kept and stated in pit.plane and For Hassan.
- Gap: programme-scan-unknown `needed` case added.

## For Hassan

- DECISION: band edges follow the source's wording: <3.0 / 3.0–<4.5 / 4.5–<5.5 / ≥5.5 cm and growth >1.0 cm. S1 gives no rounding rule, so no half-up. The 4.4–4.5 and 5.4–5.5 gaps are closed by reading each range's lower bound (4.5 and 5.5), so 4.49 cm is small and 5.49 cm is medium.
- DECISION: a surveillance scan measuring under 3.0 cm goes to an explicit "does not fit" outcome (manage per the programme SOP), a library addition; the pathway requirements give no rule and point to the SOP for exit points.
- DECISION: how "grown by more than 1 cm in 12 months" is measured (against the scan 12 months earlier, versus a rate over another interval) is not stated; the input asks for the 12-month increase in cm.
- Eligibility uses three of the source's four scope facts (programme scan, sex, prior AAA treatment); "men under 65" is left out to keep to three inputs and because men under 65 are not invited, so a programme scan already implies the age.
- The measurement plane (inner-to-inner versus outer-to-outer, anteroposterior) is set by the AAA screening clinical guidance, which is not filed; `how_stated` and pit.plane say only that the programme's recorded diameter is used.
- DECISION: if two diameters are dictated, the larger is used (`dims: "max"`); S1 does not say. Stated in pit.plane.
- DECISION: a non-visualised surveillance scan reaches `non_visualised` with neutral wording ("a further programme scan will be offered"); S1 describes only the non-visualised initial screen.
- Not filed: the page's end-to-end pathway figure (SVG) and its accessible text version, the AAA screening standard operating procedure, and the clinical guidance. If any of these define rounding, growth measurement or the under-3.0-cm-on-surveillance route, the three decisions above should follow them.
