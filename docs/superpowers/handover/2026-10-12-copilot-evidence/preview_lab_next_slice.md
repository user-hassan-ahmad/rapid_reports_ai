# Preview lab, next slice (the gate for Apply)

**Gate: FAILED.**
- **Latency failed.** The cache MISS p95 is 4264 ms, and the gate is under 2000 ms.
- **Correctness passed by the lab's metric.** There were 0 wrong proposals.
- **The hand read found one wrong settled value.** In BTS case 36, "two lesions in one sentence", `upper_lobe` settled as Yes from the other lesion's "left upper lobe". The card reached no outcome only because other inputs were still asked, so the metric did not catch it. See "Wrong values" below.

There was one run. Run 1 had no wrong proposal and no system error, so the brief allows no run 2. Nothing was tuned.

- **Branch:** feat/scratchpad-copilot. The run was on HEAD ea542d8 plus this commit's lab files.
- **Raw output:** `preview_lab_50259.json` in the session scratchpad (`/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/10e9e5c6-f67c-49c0-8e81-edffd2532c71/scratchpad/`).
- **Command:** `cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/preview_lab.py <scratchpad>`.
- **Expectations:** `--check` gave "41 cases checked, 0 disagree" before run 1. No expectation changed after the model output was seen.

## Results

| Run | Wrong proposals | Wrong settled (metric) | Unasked | Outcome ok | State ok | Missing ok | Asked instead | Degraded | MISS p50 / p95 | HIT p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 2 (display only, see below) | 12 | 35/41 | 28/41 | 34/41 | 17 | 0 | 1609 / **4264 ms** | 0 / 0 ms |

- **HIT:** every second call was served from the preview cache in under 1 ms; the maximum was 0 ms. Opening a card whose preview /match already started costs nothing.
- **MISS:** the latency the radiologist sees when a card opens before its prewarm has finished.

### What the columns mean

- **Wrong settled (metric).** Both are `nodule_count`, shown as `"1"` where the case expects `"1 count"`, quoted from "Solitary nodule." and "Solitary". The value is right. The case text used the old display string, and the engine now shows a count without its unit. The cases are #23 and #27. This is not a wrong value.
- **Unasked.** An input the case expected to settle was asked instead, and the case did not list it in `accept_missing`. Each one is an extra ask, never a wrong value. The list is below.
- **State ok 28/41.** Every state mismatch is a check_first state caused by an eligibility input that was asked when the case allowed it to settle. These are BTS `proven_malignant` (10 cases), Fleischner `exclusion` and `age`, and Bosniak `mimic`. No card showed "applies" when eligibility was unknown, and no card showed "does_not_apply" wrongly.

### MISS latency per pack (ms, sorted)

| Pack | MISS ms |
|---|---|
| bosniak-renal-cyst | 1286, 1351, 1433, 1450, 1458, 1609, 1985, 2110, 2174, 2177, 2193 |
| bts-pulmonary-nodule | 1269, 1457, 1784, 1902, 2215, 2299, 2307, 2405, 2527, 2737, 2849, 3747, 5819, 6510 |
| fleischner-pulmonary-nodule | 786, 838, 856, 864, 954, 1036, 1041, 1100, 1212, 1265, 1430, 1547, 1572, 2052, 3122, 4264 |

**Slowest cases:**
- BTS "RML 4mm SN": 6510 ms.
- BTS "intrapulmonary lymph node": 5819 ms.
- Fleischner "scattered tiny nodules": 4264 ms.
- BTS "two lesions in one sentence": 3747 ms.
- Fleischner "RUL PSN": 3122 ms.

BTS has a median of about 2.3 s. Its settle prompt is the largest: 17 inputs, with a lesion batch and a patient batch sent to Jev.

## Friction: asks per card

Asks are the inputs in `missing`, eligibility included.

| | Value |
|---|---|
| Mean asks per card | **4.02** |
| Median | 2 |
| Cards with at most 2 asks | **24/41 (58.5%)** |
| Cards with an eligibility ask (check_first) | 15/41 |

**Distribution (asks: cards):**

| Asks | Cards |
|---|---|
| 0 | 8 |
| 1 | 9 |
| 2 | 7 |
| 3 | 3 |
| 4 | 1 |
| 7 | 1 |
| 8 | 4 |
| 9 | 1 |
| 10 | 2 |
| 12 | 4 |
| 13 | 1 |

**Per pack:**

| Pack | Mean | Asks per card |
|---|---|---|
| Fleischner | **0.88** | 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 3, 3 |
| Bosniak | **3.55** | 1, 1, 1, 2, 2, 2, 2, 3, 8, 8, 9 |
| BTS | **8.00** | 0, 2, 2, 4, 7, 8, 8, 10, 10, 12, 12, 12, 12, 13 |

Fleischner cards stay quick. BTS cards do not.

### Why BTS asks so much

Two rules drive it, and both come from the current packs.

1. **`prior_study` is lesion-scoped.** "No previous imaging" is nearly always its own sentence, outside the nodule's finding unit, so `prior_study` is always asked. While it is unknown, the engine also needs `resolved`, `growth`, `prior_volume_mm3`, `current_volume_mm3` and `interval_days`. One unstated sentence becomes six asks.
2. **`proven_malignant` is rarely stated.** It was asked in 11 of the 14 BTS cards (the under-18 card did not need it). The two that settled it are noted under "Wrong values".

I recomputed the BTS asks with the engine alone, with no model call, using the run's settled values:

| BTS asks scenario | Mean asks per card |
|---|---|
| As run | 8.0 |
| If `prior_study` were known | 2.6 |
| If `prior_study` and `proven_malignant` were known | 1.9 |

The engine lists every input that could still matter, including the follow-up inputs behind an unanswered parent. Showing only the parent until it is answered would cut BTS asks without changing any rule. This is a question for Hassan, not something this lab changed.

### Why Bosniak asks so much

`hu` is asked whenever the size is dictated in the same finding, which is almost always. The rule is "a lesion number settles only when the finding holds no other number", and the size counts as another number.
- When the outcome does not depend on HU (classes II and IIF here), the ask disappears.
- When it does (class I), the card stops one ask short of a proposal.

The two 8-ask cards are #14 and #19. In both, Qwen did not settle the lesion's enum inputs.

## Wrong values (hand read of every settled value)

**One wrong value, BTS #36, "two lesions in one sentence".**
- **Finding:** "6 mm solid nodule with no calcification in the right lower lobe and a 12 mm densely calcified granuloma in the left upper lobe."
- **Wrong value:** `upper_lobe` was settled as **Yes**, quoted from "left upper lobe". That is the granuloma's lobe; the index nodule is in the right lower lobe.
- **Confirmed by Jev:** the claim is checked against the whole finding unit, which does mention an upper lobe.
- **Second error in the same card:** `nodule_type` "solid" was quoted from "densely calcified granuloma". The value is right by coincidence, but it was read from the wrong lesion.
- **Why no wrong proposal showed:** the card stayed at 13 asks with no outcome. If the radiologist answered the rest, the Brock score would include the upper-lobe term wrongly.
- **Why the lab missed it:** `upper_lobe` is not in the brief's `expect_settled` for this case, so the metric did not score it.

This is the per-finding scope failing on a finding that holds two lesions (Jev was asked whether the finding states "upper lobe: Yes", and it does, of the granuloma):
- The one-lesion rule protects numbers only.
- Enum and yes/no lesion inputs are still read from whichever lesion the quote comes from.

**Weak-basis settles.** The values are right, but the quotes do not support them.
- **BTS `proven_malignant` = No:**
  - #29 quotes "typical of an intrapulmonary lymph node".
  - #30 quotes "15 mm pure ground-glass opacity in the LUL".
  - The pack defines false as "described as new, indeterminate or not yet sampled", and neither quote says that.
- **Bosniak `too_small` = no:**
  - #13 quotes "a single thin (1 mm) septum and a fleck of calcification".
  - #16 quotes "thick (5 mm) enhancing septum".
  - #18 quotes "thin wall, 4+ thin enh septa".
  - #20 quotes "homogeneous, 45 HU unenhanced".
  - Every lesion was ≥ 2.5 cm, so the values are right, but the quote is not the size.
- **Fleischner `count` = single:**
  - #33 quotes "The lungs are otherwise clear".
  - #32 quotes the nodule sentence.
  - Both are defensible.

## Unasked and asked-instead cases

Every case below has its settled quotes in the raw JSON.

| # | Case | Asked, though the case expected it to settle |
|---|---|---|
| 13 | Bosniak "single thin septum" | `wall`, `contents_enhancement` ("Uniform contents of 12 HU, non-enhancing") |
| 14 | Bosniak "portal venous only" | `too_small`, `protrusion` (the not-enhancing protrusion), plus six more lesion enums |
| 16 | Bosniak "distractor" | `protrusion` ("no nodules") |
| 18 | Bosniak "abbreviation heavy" | `septa` ("4+ thin enh septa"), `protrusion` ("no nod") |
| 19 | Bosniak "mural nodule" | `too_small` (4.5 cm) |
| 20 | Bosniak "hyperdense" | `wall` ("imperceptible wall") |
| 23, 25, 27 | BTS | `spiculation` ("smooth margin", "lobulated margin") |
| 28 | BTS "RML 4mm SN" | `benign_features` ("no calc.") |
| 40 | Fleischner "shared age: source card" | `age`: "Age 72." gives no reading, because `quantity.readings("Age 72", "years")` returns []. A bare number is not read for a years input. This is a deterministic code gap. |
| 41 | BTS "shared age: second card" | `age` (see below) |

**What #40 and #41 mean for the shared-answer test.** Because the source card did not settle age, the second card received an empty patient map. The live shared-answer path across cards was therefore not exercised in this run. The engine-only `--check` exercises it, and case #38 shows the tap route: age from the patient map reached the card as "60 years".

**Asked instead (accepted):**

| Input | Count |
|---|---|
| BTS `proven_malignant` | ×11 |
| BTS `nodule_count` ("No other … nodules") | ×2 |
| BTS `benign_features` (#36) | ×1 |
| Fleischner `count` (#34) | ×1 |
| Fleischner `exclusion` (#32, "Known metastatic breast cancer; restaging CT.") | ×1 |
| Bosniak `mimic` (#39, "in keeping with a renal abscess") | ×1 |

Two eligibility exclusions stated in the dictation were asked rather than settled: #32 (known cancer) and #39 (renal abscess). Both cards are check_first, never applies. No wrong value came of it, but the exclusion was not shown.

## Case expectations changed from the brief (Step 4, and the binding rules of 2026-10-13)

**How the cases were set up:**
- **Expectations from the engine.** All `expect_missing`, `expect_outcome` and `expect_state` values were taken from the current engine and packs with `--check` before run 1.
- **Finding units.**
  - A finding is the sentence or sentences describing the index lesion itself, including its calcification or its HU sentence.
  - It never includes a study-level sentence ("No previous imaging", "No other nodules"), the background lung, or another lesion.
  - The brief's 11 new cases keep its exact text.
- **Inputs in `accept_missing` with a value in `expect_settled`:** BTS `proven_malignant` = No in every BTS case. No dictation mentions a biopsy, so "No" is true but rarely stated.

**What changed, by rule:**
- **A lesion number settles only for a finding that describes one lesion.** I checked this with `quantity.alone` and `quantity.many` on every case. Each number that rule always blocks was dropped from `expect_settled` and moved to `expect_missing`:
  - Fleischner `diameter_mm` in #4 ("Two … nodules: 1.5 cm … and 6 mm"), #7 ("Two … the larger 5 mm … the other 3 mm"), #8 ("7mm PSN, solid component 3mm"), #10 ("Several scattered … largest 4 mm") and #34 ("7 mm … and a 4 mm calcified granuloma"). The expected outcome becomes null in each. In the brief, #34 was `solid_single_6to8_high` with `diameter_mm` in `accept_missing`.
  - Bosniak `hu` in #11, #12, #13, #15, #17, #18 and #20. The size in the same finding is another number. #13 (class_ii) and #18 (class_iif) keep their outcome, because it does not depend on HU. The others become null.
  - BTS `diameter_mm` and both volumes in #24, and `diameter_mm` in #36.
- **BTS `prior_study` is lesion-scoped.** "No previous imaging / no prior CT" sits outside the finding, so `prior_study` was dropped from `expect_settled` in #21, #22, #23, #25, #26, #27, #36, #38 and #41. With it unknown, the engine adds `resolved`, `growth`, the volumes and `interval_days`, and for the Brock path `sex`, `family_history`, `emphysema`, `nodule_count` and `spiculation`. The outcomes become null: pet_ct, ct_1yr, brock_low, ct_3m (×3).
- **The BTS pack now needs `prior_study` and `resolved` for every outcome**, discharge included. The outcomes of #28 (discharge_small), #29 (discharge_benign) and #30 (subsolid) therefore become null.
- **Bosniak #16 and #19 now need `contents_enhancement`.** The outcomes class_iii and class_iv become null. This comes from the engine; the pack was not touched.
- **Unknown eligibility.** BTS #25, "unstated: age", is check_first with `age` first, as the brief says.
- **`nodule_count` from "No other … nodules"** is in `accept_missing` in #21 and #25, as the brief says.

**What this does to the lab.** The changes cut the lab's power. Only 14 of the 41 cases expect a non-null outcome, and only 8 reached one. A wrong proposal can only show on a card that reaches an outcome, and that is how case #36's wrong `upper_lobe` passed the metric.

## For Hassan

1. **Latency fails the gate.** The MISS p95 is 4.3 s, and BTS reaches 6.5 s. The cache hides this only when the prewarm from /match has finished before the card is opened.
2. **One wrong lesion value: BTS `upper_lobe`, read from the other lesion in a two-lesion finding.** The one-lesion guard covers numbers only. Enum and yes/no lesion inputs on a finding with several lesions need the same guard, or a Jev claim that ties the quote to the index lesion.
3. **Friction.** BTS averages 8 asks per card, and the main cause is `prior_study` being lesion-scoped while its sentence is study-level. Bosniak HU is asked whenever the size is in the same finding.
4. **"Age 72" is not read as an age.** A bare number is not read for a years input.
