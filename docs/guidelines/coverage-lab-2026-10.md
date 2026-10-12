# Coverage lab results and authoring order (October 2026)

Task 15 step 5 of the guideline library plan. Counts and system names only; no dictation text appears in this file.

## 1. Method and limits

- Corpus: production `reports` dictations from the last 180 days, 393 reports from 7 users.
- Sentence split: each report was split into sentences (4,931 by the lab's count; the hand-read CSV holds 4,941 rows). The hybrid stack's grouped units do not exist in production yet, so sentences stand in for them. A matcher fed grouped units may behave differently.
- Matcher: the unchanged production matcher (gpt-oss). It ran on 333 cases. 60 cases failed on Cerebras rate limits after one retry and contributed no systems. Two runs maximum.
- Duplicates: the same dictation recurs across several cases (re-runs and edits). De-duplication keeps the first case for each identical FINDINGS text: 322 unique texts from 393 cases (71 repeat cases dropped). Raw and de-duplicated counts are both given. The de-duplicated figures are the ones used for ranking.
- Hand read: single annotator (Claude), no second reader and no inter-rater agreement. Judgements follow the review item policy; boundary calls were not adjudicated by a radiologist.
- Scan-type mix is skewed (see section 4), and the corpus reflects only 7 users.

## 2. Results

| Measure | Raw | De-duplicated |
|---|---|---|
| Rows with a system named | 543 | 389 |
| Judged correct | 303 | 209 |
| Precision (correct / named) | 55.8% | 53.7% |
| Distinct sentences with a correct system | 298 | 204 |
| Canonical systems with at least one correct mention | 47 | 47 |

- Recall estimate (raw): 16 of 300 sampled no-system sentences (seed 7) should have had a system, giving about 201 missed sentences across 3,773 no-system sentences. Recall is roughly 298 / (298 + 201) = 59.7%. The sample is small (16 positives), so the interval is wide. A de-duplicated recall was not recomputed because the sample was drawn from the raw pool.
- Precision is low mainly because of confident wrong namings (240 wrong rows), which is why the negative-control gate below matters more than recall.

### Ranked canonical systems (correct mentions)

Ranked by de-duplicated count, ties broken by raw count; order within the single-mention tail is arbitrary.

| # | Canonical system | Correct, raw | Correct, de-duplicated | Cumulative % (de-duplicated, 209 total) |
|---|---|---|---|---|
| 1 | Agatston calcium score | 51 | 38 | 18.2% |
| 2 | CAD-RADS 2.0 | 89 | 33 | 34.0% |
| 3 | Outerbridge | 23 | 17 | 42.1% |
| 4 | Bosniak 2019 | 21 | 15 | 49.3% |
| 5 | Lund-Mackay | 16 | 12 | 55.0% |
| 6 | AO Spine thoracolumbar | 13 | 11 | 60.3% |
| 7 | Fleischner 2017 | 9 | 9 | 64.6% |
| 8 | TNM | 10 | 7 | 67.9% |
| 9 | Stoller meniscal grade | 7 | 7 | 71.3% |
| 10 | SINS | 5 | 5 | 73.7% |
| 11 | Goh SSc-ILD staging | 4 | 4 | 75.6% |
| 12 | TASC II | 4 | 4 | 77.5% |
| 13 | BTS 2015 nodule | 3 | 3 | 78.9% |
| 14 | Aortic valve calcium score | 3 | 2 | 79.9% |
| 15 | AHA 17-segment model | 2 | 2 | 80.9% |
| 16 | Balthazar CTSI | 2 | 2 | 81.8% |
| 17 | Eaton-Littler | 2 | 2 | 82.8% |
| 18 | Hepple OCL | 2 | 2 | 83.7% |
| 19 | PI-RADS 2.1 | 2 | 2 | 84.7% |
| 20 | Patte | 2 | 2 | 85.6% |
| 21 | RECIST 1.1 | 2 | 2 | 86.6% |
| 22 | Revised Atlanta 2012 | 2 | 2 | 87.6% |
| 23 | Schizas stenosis grade | 2 | 2 | 88.5% |
| 24 | Adrenal incidentaloma (ESE 2023) | 2 | 1 | 89.0% |
| 25 | Genant vertebral fracture | 2 | 1 | 89.5% |
| 26 | IOTA Simple Rules | 2 | 1 | 90.0% |
| 27 | AO/OTA fracture | 1 | 1 | 90.4% |
| 28 | Alpha angle (cam FAI) | 1 | 1 | 90.9% |
| 29 | BSE LV function grading | 1 | 1 | 91.4% |
| 30 | DeOrio-Cofield RC tear size | 1 | 1 | 91.9% |
| 31 | ESC HCM criteria | 1 | 1 | 92.3% |
| 32 | Ellman partial RC tear | 1 | 1 | 92.8% |
| 33 | Fazekas | 1 | 1 | 93.3% |
| 34 | Fredericson stress injury grade | 1 | 1 | 93.8% |
| 35 | Fukuoka IPMN | 1 | 1 | 94.3% |
| 36 | Goutallier | 1 | 1 | 94.7% |
| 37 | ICRS cartilage/OCD | 1 | 1 | 95.2% |
| 38 | LI-RADS | 1 | 1 | 95.7% |
| 39 | Lake Louise 2018 | 1 | 1 | 96.2% |
| 40 | MESA CAC percentile | 1 | 1 | 96.7% |
| 41 | Meyerding | 1 | 1 | 97.1% |
| 42 | NASCET | 1 | 1 | 97.6% |
| 43 | Neer proximal humerus | 1 | 1 | 98.1% |
| 44 | RENAL nephrometry | 1 | 1 | 98.6% |
| 45 | RV/LV ratio | 1 | 1 | 99.0% |
| 46 | Samilson-Prieto | 1 | 1 | 99.5% |
| 47 | Stanford dissection | 1 | 1 | 100.0% |

N to reach 90% of correct mentions: 27 of 47 de-duplicated (cumulative 89.95% at 26, 90.4% at 27); 22 of 47 on the raw counts.

## 3. Gate results

### 90% coverage gate

- Raw counts: N = 22 of 47 systems reach 90% of correct mentions. De-duplicated: N = 27 of 47.
- Interpretation: N is the authoring scope needed to cover 90% of what these users actually had a correct guideline for. The gate is met in the sense that coverage is concentrated: roughly half the systems seen carry 90% of the value, so authoring the top 22 to 27 systems (fewer than the 47 seen, and a fraction of the 107 in the catalogue) is enough for a first release. It is not a statement that 90% of all dictated findings are covered; recall is about 60%. The tail of 20 or so single-mention systems is not worth authoring up front.
- Caveat: this scope is driven by seven users and a cardiac-heavy mix, so the top of the list will shift with a wider user base.

### Negative-control gate: FAILED

- 100-row sample of wrong namings: 98 were sentences where no system should apply, and 2 had a different system that does apply.
- Apply-able false cards in the sample: 9 (Bosniak 2019 x4, Fleischner 2017 x3, TNM x2).
- Across all 240 wrong namings: 17 Apply-able false cards (Bosniak 2019 x8, Fleischner 2017 x6, TNM x2, BTS 2015 nodule x1).
- Typical causes: Bosniak named for hepatic cysts; Fleischner named for metastases in a cancer patient, tree-in-bud and a calcified granuloma; TNM named for an indeterminate tonsil and a bone lesion on follow-up.
- Mitigation in progress: a Jev applicability gate for pack cards.
- Mitigation result: pending

## 4. Authoring order

Rank is our usage first (de-duplicated correct mentions), then catalogue frequency (high, medium, low) for systems never seen. Columns: tier_candidate, uk_body and verified come from `catalogue.json`. "Pack exists" is yes only for Fleischner 2017, Bosniak 2019 and BTS 2015.

| # | System seen | De-dup. | Raw | Catalogue entry | tier_candidate | uk_body | verified | Pack exists |
|---|---|---|---|---|---|---|---|---|
| 1 | Agatston calcium score | 38 | 51 | cac-drs-2018 (loose match) | 2 | no | yes | no |
| 2 | CAD-RADS 2.0 | 33 | 89 | cad-rads-2 | 1 | no | no | no |
| 3 | Outerbridge | 17 | 23 | outerbridge | 1 | no | yes | no |
| 4 | Bosniak 2019 | 15 | 21 | bosniak-2019 | 1 | no | yes | yes |
| 5 | Lund-Mackay | 12 | 16 | sinus-lund-mackay | 1 | no | no | no |
| 6 | AO Spine thoracolumbar | 11 | 13 | not in catalogue | - | - | - | no |
| 7 | Fleischner 2017 | 9 | 9 | fleischner-2017 | 1 | no | yes | yes |
| 8 | TNM | 7 | 10 | tnm-9 | 2 | no | no | no |
| 9 | Stoller meniscal grade | 7 | 7 | not in catalogue | - | - | - | no |
| 10 | SINS | 5 | 5 | not in catalogue | - | - | - | no |
| 11 | Goh SSc-ILD staging | 4 | 4 | not in catalogue | - | - | - | no |
| 12 | TASC II | 4 | 4 | not in catalogue | - | - | - | no |
| 13 | BTS 2015 nodule | 3 | 3 | bts-pulmonary-nodules | 1 | yes | yes | yes |
| 14 | Aortic valve calcium score | 2 | 3 | not in catalogue | - | - | - | no |
| 15 | AHA 17-segment model | 2 | 2 | not in catalogue | - | - | - | no |
| 16 | Balthazar CTSI | 2 | 2 | balthazar-ctsi | 1 | no | yes | no |
| 17 | Eaton-Littler | 2 | 2 | not in catalogue | - | - | - | no |
| 18 | Hepple OCL | 2 | 2 | not in catalogue | - | - | - | no |
| 19 | PI-RADS 2.1 | 2 | 2 | pi-rads-v2-1 | 1 | no | yes | no |
| 20 | Patte | 2 | 2 | not in catalogue | - | - | - | no |
| 21 | RECIST 1.1 | 2 | 2 | recist-1-1 | 1 | no | yes | no |
| 22 | Revised Atlanta 2012 | 2 | 2 | revised-atlanta | 1 | no | yes | no |
| 23 | Schizas stenosis grade | 2 | 2 | lumbar-stenosis | 1 | no | yes | no |
| 24 | Adrenal incidentaloma (ESE 2023) | 1 | 2 | ese-adrenal-2023 | 1 | no | yes | no |
| 25 | Genant vertebral fracture | 1 | 2 | not in catalogue | - | - | - | no |

Notes:

- "(loose match)" means the catalogue entry only partly covers the system seen: Agatston is a score inside CAC-DRS; IOTA Simple Rules is not O-RADS US; MESA percentile maps to CAC-DRS.
- "not in catalogue" rows are listed in section 5. They rank on usage but cannot be authored until a catalogue entry (with a verified source) is added.
- Systems never seen (88 catalogue entries: 46 high, 34 medium, 8 low frequency) follow after rank 25, ordered high, medium, low, then tier. The unseen high-frequency tier-1 entries are: acr-adnexal-2013, acr-adrenal-2017, acr-pancreas-cyst-2017, acr-renal-2018, acr-thyroid-2015, acr-vascular-2013, aspects, bi-rads-5th, bta-thyroid-us, bts-pleural-disease, ecr-pancreatic-cystic-neoplasms-2018, garden-hip, hinchey-diverticulitis, kl-grade, lung-rads-2022, modic, nhs-lung-screening, nice-ng232-head-injury, o-rads-us, pfirrmann, rcog-gtg-postmenopausal, rcog-gtg62-premenopausal-ovarian, salter-harris, sru-ovarian-cyst, ti-rads-2017, tirads-eu, ukhsa-aaa-programme-guidance, ukhsa-breast-assessment-guidance, ukhsa-breast-image-reading, weber-ao.
- Scan-type mix bias: cardiac CT dominates (coronary CT angiogram 57 cases, TAVI CT 23, cardiac MRI 26), so CAD-RADS and Agatston lead largely because of one or two heavy users. The rest is CT abdomen/pelvis (66), MSK MRI (49) and other CT (32). Breast, obstetric, ultrasound (9 cases) and radiograph (4) work is almost absent, so breast, thyroid, obstetric and fracture-classification catalogue entries are under-observed here, not unwanted. All figures reflect 7 users.

## 5. Systems seen in practice but missing from the catalogue

Matched loosely by name against the 107-system catalogue; correct-mention counts (raw) in brackets, 0 meaning seen only as a miss.

AO Spine thoracolumbar (13), Stoller meniscal grade (7), SINS (5), Goh SSc-ILD staging (4), TASC II (4), Aortic valve calcium score (3), Eaton-Littler (2), Patte (2), AHA 17-segment model (2), Genant vertebral fracture (2), Hepple OCL (2), Alpha angle for cam FAI (1), Stanford dissection (1), DeOrio-Cofield RC tear size (1), Samilson-Prieto (1), Ellman partial RC tear (1), NASCET (1), BSE LV function grading (1), RENAL nephrometry (1), ICRS cartilage/OCD (1), Neer proximal humerus (1), Fredericson stress injury grade (1), ESC HCM criteria (1), Lake Louise 2018 (1), Bilsky ESCC (0).

Only loosely covered: Fukuoka IPMN (catalogue has the European 2018 pancreatic cyst guideline), IOTA Simple Rules (O-RADS US), Schizas (lumbar stenosis entry), MESA percentile (CAC-DRS).

Named but judged wrong and not catalogue candidates (research-only or misapplied): AAST EGS appendicitis grade, Qanadli index, Marshall and Rotterdam CT, ICH score, MOAKS, WORMS and BML scoring, RAMRIS, Sharp/van der Heijde, RUST, Goddard, TICI, EHS hernia, ILO, Snyder SLAP, Tokyo Guidelines.
