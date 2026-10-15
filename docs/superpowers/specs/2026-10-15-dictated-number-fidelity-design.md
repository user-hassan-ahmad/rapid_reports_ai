# Dictated number fidelity (Generate, step 1): design

Date: 2026-10-15. Track: dictation fidelity in Generate. Status: design for the step-1 code check; ships behind a flag (default OFF).

## Problem

The P3 end-to-end replay (2026-10-15) showed the template writer dropping dictated numbers on number-heavy sheets
(cardiac MR stress: adenosine dose, heart rate and blood pressure response). The briefs were identical before and
after, so the drop is writer behaviour. Nothing checks that dictated numbers survive. `template_number_check.undictated_numbers`
checks the reverse direction (numbers in the report that nobody dictated).

## What counts as a dictated number

- **Sources**: the radiologist's own statements only: dictated units and tapped rows (`Statements.said_parts`) and typed
  values (`gate.values` with state `entered`), minus any sentence the radiologist removed. Not the clinical history
  (L-36: history is never emitted in the report), not assumed region normals (template wording), not the confirmed
  conclusion (often drafted; its numbers repeat the findings).
- **Tokens**: digit numbers only: integers, decimals including a leading-dot decimal (`.14`), ranges (`50-69%`,
  `50 to 69%`), slashes (`120/80 mmHg`), dimensions (`5 x 3 mm`, `5 by 3 mm`). A unit after the last number of a
  chain applies to every number in it. Each value in a chain is checked on its own.
- **Spoken numbers** are already digits: Deepgram runs with `numerals=true` ("segment seven" -> "segment 7"). Number
  words in the dictation ("two lesions") are ignored in v1: a count reworded is not a dropped measurement, and "one"
  is too often not a number.
- **Not numbers** (masked as in `template_number_check`): identifiers (T2, L4/5, b1000, S1), dates, clock times,
  list markers.

## How a number is matched in the report

A dictated value is **present** when the report holds a number token with the same numeric value
(`float` equality: `0.14` = `.14` = `0.140`; `1.5` != `15`; `5` != `.5`) and a compatible unit:

- dictated with a unit -> the report token has the same normalised unit (a number word followed by that unit
  counts: "three minutes" holds "3 minutes"). A bare report number never satisfies a dictated unit: "segment 4"
  does not hold "4 minutes" (tightened 2026-10-15, Hassan Q1, after the lab's coincidental-match misses);
- dictated without a unit -> any report token with that value (the writer may add a unit: "LVEF 55" -> "55%").
- A unitless dictated value up to 20 also matches its number word in the report ("2 lesions" -> "two lesions").

**One-to-one (unit-bearing values).** Each report occurrence of a (value, unit) satisfies one dictated occurrence:
"4 mm and 4 mm" or "4 x 4 mm" needs two "4 mm" in the report, and "12 mm, previously 12 mm" with one "12 mm" in the
report flags the second. Repeat rule: counting is per source (one dictated unit, tapped row or typed value), and each
source is matched afresh against the whole report, so the same value restated across sources (dictation plus a tapped
row, or the finding plus the impression line) is one fact, not two. Unitless dictated values keep presence matching
and use up nothing.

Unit spellings are normalised (millimetre/mm, ml/mL/cc, mGy·cm / mGycm / mGy.cm / mGy cm, bpm / beats per minute,
mmHg, mcg/kg/min / micrograms/kg/min, ml/m2 / ml/m², g/m2, ms, HU, %, s, mg, ...). **No unit conversion**: dictated
"5 mm" reported as "0.5 cm" is a miss. Why conservative: a converted or re-unitised value is a change the radiologist
should see; unit conversion in code would also hide a real 5 mm -> 5 cm error. The lab measures how often this costs
precision.

Matching is anywhere in the report, not sentence-aligned. This trades a little recall (a dropped "72 bpm" is missed
when another "72 bpm" appears elsewhere) for simplicity and precision. Lab re-score after the Q1 tightening, same
stored outputs: precision 4/4, recall 4/5 (was 2/2, 2/5); the one miss is a prior "12 mm" whose value the report
restates in a summary line.

This is a mechanical question (is this value written?), so code is the right owner (feedback: code for mechanics,
Jev for meaning). If the lab shows matching needs judgement (paraphrased values), a Jev/Qwen step goes after the code
pre-filter, never instead of it.

## Where it runs

`hybrid_stack/report.py` step 5, beside the quick `undictated_numbers` call, after the removed guard, for **both**
kinds (quick and template), on the final report text. One pure function in a new module
`dictated_number_check.py`: `missing_dictated_numbers(report, sources) -> list[dict]`. Flag:
`RR_DICTATED_NUMBERS=1` (default off), read per call like the other `RR_*` switches.

## What happens on a miss

v1: a **high** review item per missing number, in the existing `quality_check.review` flag shape:
`{"kind": "dictated_number_missing", "text": "<value + unit as dictated>", "sentence": "<dictated sentence>",
"severity": "high", "message": "Dictated number not in the report: <text>"}`. `review_engine.live.check_flag_items`
turns it into an open action item on the rail (no edit, no anchor since the sentence is the dictation's). No
auto-repair.

**Repair option for Hassan (not built):** a pre-render repair that re-inserts the dictated sentence (or asks the writer
to restate the value) would surface as a `pre_applied` item, per the pre-apply-before-render rule. It is held back
because writing a number into a clinical report is the highest-risk edit we could automate: the value must land in the
right sentence beside the right structure, and a wrong placement is worse than a visible flag.
