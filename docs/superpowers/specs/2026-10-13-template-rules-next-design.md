# Template rules: what changes next — design note

Date: 2026-10-13. Status: direction agreed with Hassan; post-merge work (after `feat/template-stack` ships).
Principle for every piece: **Jev decides, code applies, the generator only writes what is already decided.**
Builds on: `2026-10-12-template-pipeline-design.md`, `2026-10-12-template-requirements-design.md` (value cluster,
required statements; not built). Flow diagram: https://claude.ai/artifact/9yLtQVb75ja2ktEzxMo4Db (private).

## Build order

### 1. Context rules resolved by Jev before generation
- Today: on the scratchpad path Jev judges a context RULE only when it hides an assumed normal
  (`hybrid_stack/template.py:template_suppressions`); every other rule (the comparison swap, protocol variants) is
  passed as raw rule text in `template_stack.stack_brief` and the generator interprets it. Seen 2026-10-13: "No
  comparison made with previous study dated 02/12/2025." (both branches merged, 1/11 prior cases, messy dictation);
  `{date}` printed unfilled on today's path for a vague prior.
- Change: extract only the rule-resolution step of the parked `template_brief.py` (not the module: no in-place
  rewrite, no negatives classifier, no impression plan, no fail-closed-to-raw on any error). Per case, Jev judges
  each context condition once (history + protocol text + dictation, MET 0.5, silence is not met), reusing the
  scratchpad's suppression answers so checklist and report agree. Code applies REPLACE / SUPPRESS / USE to the
  FIXED lines and removes the rule lines from the stack brief. Slot fallback: a replacement whose slots the
  dictation cannot fill uses a slot-free variant (or code strips the unfilled slot); no `{slot}` ever reaches a
  report. Same resolver on the straight-dictation path.
- Measure: the 23 prior/no-prior e2e cases in the private folder (`final/E2E_PRIOR.md`), before and after.

### 2. Value cluster (requirements spec part 1, unchanged)
- Today: `LIST_MISSING` values never reach the scratchpad; a missed value surfaces after Generate as
  "[MISSING DATA: …]" / "Values not provided".
- Change: as specified — chips at the top, Jev "does the dictation state <item>?", code reads the number, filled /
  entered / N/A / open, Confirm blocks until resolved, N/A produces the "Values not provided" line.
  Open question 1 of that spec is answered: every template now has a grammar sheet.

### 3. Findings-triggered rows (one mechanism, three sources)
- Today: findings-conditioned habits are banned as rules and live only as prose exemplars; Jev never checks them,
  the scratchpad never asks them. Requirements spec part 2 (required statements, `NEGATIVE … WHEN [findings: …]`)
  and the guideline draft cards are separate designs for the same shape.
- Change: one row type triggered by a findings condition Jev judges on the dictation, rendering either a
  statement to confirm/remove (required statement) or a question to answer (habit, e.g. fracture → joint
  extension). Syntax reuses findings conditions, e.g. `RULE WHEN [findings: a fracture is reported] ASK "…"`;
  effects never write text unasked. Template rows take precedence inside the existing caps (2/region, 4 total),
  pushing generic Qwen rows behind "N more checks"; no extra room. Main source: refine chat; the writer proposes one
  only with evidence in >= 2 examples. Settle the overlap with guideline cards (one row, two sources, no double ask).
- Lab first: hand-written triggers on 5 templates, Jev trigger accuracy on prod dictations, rows per session.

### 4. FIXED-line check at save
- Today: "a statement that could be false for another patient is never FIXED" is prompt-only; the writer still
  wrote "No previous CMR available." / "No contrast." as FIXED.
- Change, in the save function: (a) code flags an absence-worded FIXED line ("No …", "There is no …", "without")
  that no context rule targets — the standard default-plus-rule pattern stays legal; (b) one Jev yes/no per FIXED
  line the write adds or changes: "Could this sentence be false for a different patient having this scan?". A flag
  goes to the repair step (→ NEGATIVE, or default + context rule), never a silent drop, and is reported with the
  "reworded" notice. No regex for temporal or patient-variable meaning.

### 5. Writer improvements (then re-run the writer lab on the 11 templates with >= 3 examples)
- Standard study-level concepts built into the grammar as defaults the writer fills with the radiologist's wording:
  comparison / prior imaging (the 2026-10-13 pattern: FIXED default + one REPLACE rule with a fixed condition),
  contrast phase, sequences not acquired, technical limitation.
- Likely required values proposed at creation for the radiologist to confirm (feeds the value cluster), not only
  values present in every example.
- Resolve the prompt's slot conflict (line 50 "slot every varying value" vs line 80 "no slot in a NORMAL": say
  where the measured part goes).
- Temperature 0.8 → lab 0.3–0.5 (variance: duplicate normals, multi-structure NORMAL, dropped comparison line).
