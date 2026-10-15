# Reading lab, 2026-10-15 (aggregates only)

Question: can Jev, picking among options code narrows, make more plainly dictated values *read* without reading
silence, inference or the wrong number? Script `reading_lab.py`, synthetic cases `reading_lab_cases.json`; real cases
from the 148-card real-lab run (labels: independent Opus subagent, `stated` per value). Two runs per arm; counts are
runs. Results and recommendations only: Hassan decides.

## Size of the prize (148 real cards, 422 drafted values, 45 read today)
- yes/no: 272 drafted, all ticks (blanket rule). 94 already pass today's Jev claim with no other blocker.
  Of those 94: 82 stated and right, **12 not stated** (a "No" from silence, e.g. treated cancer, proven malignant).
- sizes: 12 blocked by "another number"; only 1 is a prior size. The others are lesion parts (solid component,
  papillary projection) or a second lesion. 5 have no other blocker.

## yes/no (73 cases: all 12 silent passes, all 7 wrong values, 32 stated, 10 silent, 12 synthetic traps)
| arm | read right (of 78 stated runs) | read wrong |
|---|---|---|
| today's claim, noul >= 0.8 | 52 | 23 (21 are silence) |
| four-way choice >= 0.8 | 33 | 2 (both one case where the label is wrong: "No previous for comparison" is in the dictation) |
| four-way choice >= 0.9 | 32 | 0 |
| three-way choice >= 0.8 | 44 | 6 |

Synthetic traps, four-way: "No change since the prior CT" → stated yes (0.92); "previously 6 mm" → implied (prior CT
not read); "?previous malignancy" → implied; silence → not mentioned (1.00). No trap read wrongly.

Where four-way and the labels disagree on stated values, the four-way is stricter. It calls entailed values "implied":
"right lower lobe" → upper lobe: No; "simple cyst" → M4 solid: No; "day 18 of cycle" → postmenopausal: No. Whether
those count as read is a policy question, not a Jev error.

## sizes (12 real + 12 synthetic, choice among code-collected measurements)
- Current size: **0 wrong picks** in both wordings at every bar. It picks the lesion over its solid component, duct,
  projection or prior; it picks "none" for two lesions. Real: all values where the second number was the only blocker
  become read (the rest also have a "several lesions" blocker).
- Prior size: 0 wrong; wording 2 at 0.6 finds all 10 priors. At 0.8 it misses "two priors" (0.79).

## comparison date (9 synthetic: stray referral, DOB, other study, future date, several priors)
- Wording 2 (names what is *not* the comparison date): 14 right, 4 right "none", **0 wrong** at 0.6 and 0.8.
- Wording 1: 2 wrong (picked the older of two compared studies).

## Recommendations
1. yes/no: four-way choice at 0.9 replaces the blanket rule; only "stated" in the drafted direction is read.
   +32/78 stated values read, 0 silence read. Hassan to decide whether entailed values count as stated (it would add
   about 15 more, and needs its own wording lab).
2. sizes: current-size pick, wording 2, at 0.8, replaces the "another number" veto when Jev's pick equals the draft.
   Prior-size pick (wording 2, 0.8) feeds growth worked out by code.
3. dates: comparison-date pick, wording 2, at 0.8.
Caveats: small n (73/24/9); bars from one day's two runs; no real date cases.
