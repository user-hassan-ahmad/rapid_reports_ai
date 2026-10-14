# Template rules: what changes next — design note

Date: 2026-10-13. Status: direction agreed with Hassan; post-merge work (after `feat/template-stack` ships).
Principle for every piece: **Jev decides, code applies, the generator only writes what is already decided.**
Builds on: `2026-10-12-template-pipeline-design.md`, `2026-10-12-template-requirements-design.md` (value cluster,
required statements; not built). Flow diagram: https://claude.ai/artifact/9yLtQVb75ja2ktEzxMo4Db (private).

## Roadmap (updated 2026-10-13, after the Rules-step and router brainstorm)

Each item gets its own fresh session: spec → plan → build, with labs on synthetic data seeded from production.

| # | Item | Spec | Why this position |
|---|---|---|---|
| 1 | Context rules resolved by Jev before generation | **needs a spec** (outline below, §1) | small, self-contained; fixes the merged-branch comparison line and unfilled `{date}` seen 2026-10-13; the 23 prior/no-prior e2e cases test it |
| 2 | Value cluster in the scratchpad | `2026-10-12-template-requirements-design.md` part 1 | fully specified, no grammar change; the Rules step's required-value cards feed it |
| 3 | Rules step at template creation (decision run → cards → writer; decision ledger) | `2026-10-13-template-rules-step-design.md` | absorbs the writer improvements (§5) and the creation-time half of the FIXED check (§4); its ledger operations are what item 4 calls |
| 4 | Chat-to-edit router | `2026-10-13-chat-edit-router-design.md` | needs item 3's ledger operations and cards |
| 5 | Findings-triggered rows (required statements, habit questions, guideline cards) | **needs a spec** (outline below, §3) | needs a lab first, and a decision on the overlap with the guideline draft cards; the Rules step records habit candidates for it |

Still open, not yet placed: the save-time FIXED check on non-creation saves (rebuilds, the upgrade script) — §4
(a) and (b) — fits with item 3 or 4; the remaining writer items in §5 (slot-conflict wording, temperature lab) run
inside item 3's lab.

## Detail per item (as first written; numbering differs from the roadmap above)

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
