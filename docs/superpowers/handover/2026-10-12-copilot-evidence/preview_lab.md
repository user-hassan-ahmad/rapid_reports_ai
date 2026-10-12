# Preview lab: Fleischner 2017, Bosniak 2019, BTS 2015 (library spec §12.3)

**Gate: FAILED.** The final run made 1 wrong proposal and its p95 latency was 3568 ms. The gate requires zero wrong proposals and a p95 under 2 s. Per the brief, tuning stopped there and the result goes to Hassan.

- Script: `backend/scripts/guidelines/preview_lab.py`. Cases: `backend/scripts/guidelines/preview_lab_cases.json`, 10 per pack.
- Each case goes through `preview_pack` live (Qwen on Cerebras, plus Jev for quotes that are not verbatim). The cases run one at a time against the committed bundle, which includes `e7e2565 data(library): review minors; bundle rebuilt`.
- Before any run, every case's `expect_settled` was evaluated through `engine.evaluate` against the final entries. Each one reproduces its `expect_outcome` and `expect_missing`.
- The lab sets `DATABASE_URL` to in-memory sqlite because it only needs the model keys. Without that, the backend `.env` points the import at Postgres, and `psycopg` is not installed in the venv.
- No requests returned 429.

## Results

| run | wrong proposals | outcome ok | missing ok | settled clean | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| 1 | 0 | 13/30 | 10/30 | 10/30 | 1502 | 3730 |
| 2 (final) | **1** | 29/30 | 30/30 | 29/30 | 1296 | **3568** |

Final run latency by pack, in ms, sorted:
- Fleischner: 430 … 1441, 2934, 3355
- Bosniak: 1052 … 2323, 2437, 3766
- BTS: 876 … 1522, 2651, 3568

7 of 30 cases took more than 2 s. In every slow case except one, all the quotes were verbatim, so Jev was not called. The slowness comes from the Qwen settle call itself, through Cerebras variance or reasoning length, not from verification. Cases with few inputs, such as Fleischner, were also slow at times.

## Run 1 failures and fixes (system errors)

1. **BTS: no case settled.** In 9 of 10 cases Qwen returned `settled` as a JSON string instead of an array. That failed pydantic validation 3 times and raised `UnexpectedModelBehavior`, so nothing was settled. It also added about 2–3 s per case from retries. BTS has 14 inputs, the longest list of the three packs.
   - Fix: a `field_validator(mode="before")` on `RawSettle.settled` now parses JSON text (`pack_preview.py`).
   - Test: `test_settled_list_returned_as_json_text_is_parsed`.
2. **Bosniak: `too_small` never settled.** All 10 cases were therefore missing `too_small`, with no outcome. Radiologists do not dictate "not too small to characterise"; they describe the mass.
   - Fix: the `how_stated` for Bosniak `too_small` now reads: "yes when dictated as 'too small to characterise' …; no when the mass is described by its features (wall, septa, contents or attenuation) rather than called too small". The bundle was rebuilt.
   - Test: `test_bosniak_says_a_described_mass_is_not_too_small`.
3. **BTS `nodule_count` could not be settled from "solitary".** The number guard required a digit in the quote, but the entry's own `how_stated` says "'solitary' is 1". A count may now come from a count word in its quote: single, solitary, sole, one, no other, no further, or two to ten. This applies only when the input's unit is not a measurement unit (mm, cm, mm3, HU, days, weeks, months, years, %). "Seven millimetres" is still dropped.
   - Test: `test_a_count_may_be_dictated_in_words_but_a_measurement_may_not`.

No case expectations were changed between runs.

## Final run failure (gate fail)

**BTS / "distractor: calcified granuloma elsewhere" gave a wrong proposal: `discharge_benign` (the correct outcome is `ct_3m`).**

- Dictation: "6 mm solid nodule in the right lower lobe with no calcification. Separately, a 12 mm densely calcified granuloma in the left upper lobe. No previous imaging."
- Qwen settled the inputs from the granuloma instead of the index nodule:
  - `benign_features` = Yes, from "densely calcified granuloma"
  - `diameter_mm` = 12 mm, from "12 mm densely calcified granuloma"
  - `upper_lobe` = Yes, from "left upper lobe"
- Every quote was verbatim, so Jev was never asked. Each quote does settle its value, but for the wrong lesion. `benign_features` = true wins the first BTS rule on its own, so a wrong outcome was proposed.
- The same distractor pattern passed in Fleischner (adrenal adenoma) and Bosniak (contralateral simple cyst). It fails here because the distractor is itself a nodule of the kind the pack covers, so it is a plausible index lesion.
- The current checks cannot catch this. The verbatim and Jev checks ask whether a quote supports a value, not whether all the quotes are about the same lesion.

Possible directions, not tried because of the two-run limit:
- Make the settle call name the index lesion first and quote only from it.
- Add a one-question Jev check that all settled quotes describe the same lesion.
- Give BTS an explicit "which nodule" input when more than one nodule is dictated.
- Separately, the latency gate needs a decision: a faster settle model or setting, or accept about 3.5 s at p95 for packs.

## Per-pack read (final run)

- **Fleischner 10/10.** All outcomes, missing inputs and settled values were correct, including:
  - cm to mm
  - the 6 mm edge
  - "mean 8 mm" from "9 x 7 mm"
  - "several scattered tiny nodules" read as multiple
  - risk settled from the history
- **Bosniak 10/10** after the `too_small` fix, including:
  - the 20 HU edge
  - the portal-venous-only unassessable protrusion, giving unclassifiable
  - the technique taken from the history (unenhanced CT KUB)
  - the abbreviated "4+ thin enh septa", giving IIF
  - the unstated calcification, asked as missing
- **BTS 9/10.** Correct cases include:
  - Brock to PET-CT with the full history
  - Brock low with negated emphysema and spiculation
  - the 5 mm edge, giving CT at 1 year
  - an interval given in months, correctly left missing because it is not a verbatim day count
  - the missing age
  - the perifissural lymph node, giving a benign discharge
  - pure ground-glass, giving subsolid

The one failure is the distractor case above.

Neither Fleischner nor BTS declares an absent or not-assessable state. For those packs, the "not assessable" case slot was used for a multiple-subsolid cm case (Fleischner) and an interval-in-months case (BTS). Bosniak's not-assessable case uses its `not_enhancing` protrusion option, which covers "cannot be assessed".

Raw outputs (session scratchpad): `preview_lab_85181.json` (run 1) and `preview_lab_96038.json` (run 2).
