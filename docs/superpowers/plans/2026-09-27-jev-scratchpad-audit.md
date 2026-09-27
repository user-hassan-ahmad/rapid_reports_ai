# Plan — Jev for the scratchpad audit, tier 2 (lab first, 2026-09-27)

**Why:** tier 2 of the dictation integrity check (`dictation_semantic.py`) is a model call on the STRUCTURE_VALIDATOR slot. It fires 2.5 s after the scratchpad settles and must quote spans verbatim. The user asked for Jev here: near-instant, like the section pills.

**Shape (pattern A, as the word fixer):** code proposes candidates, each tied to exact offsets; Jev answers one noul per candidate in one call; a flag uses the candidate's own offsets (verbatim by construction). Tier 1 (regex, gating) is unchanged. Tier 2 stays advisory (`medium`), precision first.

## Candidates (code, `audit_candidates.py`)

- **Pair:** two statements sharing a finding or structure word, where one is negated and the other asserted, or both carry a measurement. Jev: "both can be true of the same patient at the same time".
- **Side:** a statement with left/right, when the same structure appears elsewhere with the other side, or the history names a side. Jev: "the side agrees with the rest of the scratchpad and the clinical history".
- **Measure:** a statement with a measurement. Jev: "each measurement is plausible in size and unit for what it describes, and agrees with the statement's own size words".
- Capped (pairs 12, total 24); the wording is structural, never single-domain examples.

## Bands (provisional, `jev_questions.AUDIT_BANDS`, QSET bump)

Flag at noul ≤ 0.20 (≥ 0.80 that it is a problem). Unsure (0.20–0.50) escalates to today's model tier; with the lab flag, both run and agreement is logged (scores and counts only, never text).

## Tasks (TDD, one commit each)

1. Labelled fixture `tests/fixtures/audit_cases.jsonl` (clean and planted issues, several scan types) plus an offline eval script: catches, false flags, latency. Baseline: today's model tier.
2. `audit_candidates.py`: statements with offsets, anchors, polarity, side, measurements → candidates. Tests.
3. Audit questions and bands; `JevAudit` (one call, fails open to the model tier). Tests.
4. `/api/dictation/check`: `RR_AUDIT_CANDIDATE=jev` (lab) → Jev first, escalation, comparison log. Tests.
5. Lab frontend: tier 2 rides the 600 ms tier-1 call when Jev decides (no 2.5 s wait).
6. Eval Jev against the baseline; docs.
