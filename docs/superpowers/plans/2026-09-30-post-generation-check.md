# Post-Generation Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Every quick report is checked by Jev for contradictions and omissions, and repaired by
one focal Qwen call before it ships.

**Architecture:** A new module `backend/src/rapid_reports_ai/quick_report_quality.py` holds pure
unit extraction, a Jev check (two parallel calls), `repair_report` (Qwen find→replace edits
applied deterministically) and `run_quality_check` (orchestration, never raises). It is called
at the end of `generate_quick_report`, and its telemetry is persisted on the candidate.

**Spec:** `docs/superpowers/specs/2026-09-30-post-generation-check-design.md`

**Branch:** `feat/post-generation-check`, from `feat/confirmed-negatives`.

---

### Task 1: Units (pure)

**Files:** create `quick_report_quality.py`, `tests/test_quick_report_quality.py`

The tests cover the following. `report_sections(report)` returns the FINDINGS and IMPRESSION
text. `clauses(text)`:
- splits sentences;
- splits a negative list at commas and at ", or" / ", and";
- does **not** split at a bare "or": "No pericolic or paracolic fluid collection" stays whole.

`positive_items(findings)` keeps dictated items, dropping those that start with "No"/"Nil" or
contain unremarkable / normal / intact / clear.

### Task 2: Jev check

The tests stub `qb._jev`:
- two calls, one on the dictation state and one on the report state;
- contradiction questions for every clause and every option sentence;
- omission questions for the positive items.

Flags are produced at contradiction ≥ `CONTRA_FLAG` (0.6) and omission < `OMIT_FLAG` (0.5). When
Jev raises, the result is `error` with no flags.

### Task 3: `repair_report`

The tests stub `_run_agent_with_model`, which returns `RepairEdits(edits=[{find, replace}])`:
- an edit is applied only when `find` occurs exactly once;
- unmatched and ambiguous edits are skipped and counted;
- the problems are numbered in the prompt;
- a timeout or exception returns the report unchanged, with an error.

### Task 4: Orchestration, wiring and kill switch

`run_quality_check(report, findings, scan_type, options)` returns
`(report, options, telemetry)`:
- it repairs only when a report clause or item is flagged;
- flagged options are dropped;
- `RR_QUALITY_CHECK=0` makes it a no-op.

In `generate_quick_report`:
- call it after the report and options, **before** the signature is appended;
- add `quality_check` to the result.

In `quick_report_api._run_one_generator`, add `"quality_check"` to the candidate. The tests
cover the no-op switch, option dropping, repair on a flag, and never raising.

### Task 5: Offline evaluation (L-47)

`scripts/quality_check_eval.py`:
- load the 32 L-45 rerun reports (`test_output/confirmed_negatives/20260929T234805_*`);
- run `run_quality_check` on each **clean** report and on a **perturbed** copy (one dictated
  item negated and inserted, or one dictated-finding sentence deleted);
- save the flags, edits and before/after text.

Read everything by hand, fill in L-47 against the spec's pass bar, and commit.
