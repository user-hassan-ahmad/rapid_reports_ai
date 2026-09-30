# Post-generation check — Jev flags, focal Qwen repair

**Status:** approved in conversation 2026-09-30 · **Ledger:** L-46 (probe), L-47 (evaluation)
**Scope:** the quick-report path. Code-based checks are deferred. Everything else stays with the
existing parallel Phase 1/2 audit.

## Why

A report should ship right the first time. The L-46 probe showed Jev reliably answers two
text-matching questions about a finished report, fast enough (about 0.3 s per call) to run on
every report:

| Check | Jev question | Probe |
|---|---|---|
| **Contradiction:** a report clause denies something dictated | *The dictated findings state something that this report statement denies or contradicts. Statement: …* (state = dictation) | 31/31 caught; 4/127 false flags (2 were clause-splitter artefacts) |
| **Omission:** a positive dictated finding is missing from the report | *The report states this dictated finding, in any wording: …* (state = report) | 24/24 caught; the 3 misses were dictated negatives or background, which are excluded |

## Design

New module `quick_report_quality.py`, called from `generate_quick_report` once the report and
options exist:

1. **Units**
   - **Clauses:** FINDINGS and IMPRESSION sentences. A negative list ("No A, B, or C") splits
     at commas into "No A" / "No B" / "No C". A bare "or" never splits, so "No pericolic or
     paracolic fluid collection" stays whole; the L-46 artefact came from splitting there.
   - **Option sentences:** every offered option.
   - **Dictated items:** `split_findings(findings)`, minus negative or background items (items
     starting "No"/"Nil", or containing "unremarkable", "normal", "intact", "clear").
2. **Jev:** two calls in parallel, each with a 6 s timeout:
   - dictation state: one contradiction question per clause and per option;
   - report state: one omission question per positive dictated item.
3. **Flags**
   - **Contradiction:** score ≥ 0.6 (the probe caught every genuine contradiction at 0.5, and
     29/31 at 0.7).
   - **Omission:** score < 0.5.
4. **Repair.** When a report clause is flagged or an item omitted, **one focal Qwen call**
   (reasoning none, temperature 0, 8 s timeout) is sent the report, the dictation and the
   numbered problems. It returns `edits: [{find, replace}]`:
   - `find` is a verbatim substring of the report;
   - `replace` is the corrected text: the clause removed or corrected, or an omitted finding
     appended to the sentence where it belongs.

   Code applies an edit only when `find` occurs exactly once. Any other edit is skipped and
   logged. There is no second check, to keep latency down.
5. **Options:** a flagged option is **dropped**, never repaired. This makes the
   finding-negatives fallback safe.
6. **Never blocks.** A Jev or repair failure or timeout ships the original report and options,
   and records why.
7. **Telemetry:** the candidate gains `quality_check`:
   `{clauses, items, flags: [{kind, text, score}], edits_applied, edits_skipped, options_dropped, jev_ms, repair_ms, error}`.
   It is persisted with `candidate_reports`.
8. **Kill switch:** env `RR_QUALITY_CHECK=0` turns it off. Default on.

**Latency:** about 0.3–0.6 s on every report (two parallel Jev calls), plus about 0.5–1.5 s
only when something is flagged.

### Shared repair function (for Fix with AI)

`repair_report(report, findings, problems) -> RepairResult` takes plain problem descriptions
and returns verbatim find→replace edits, independent of their source. The audit's Fix with AI
will call the same function with a criterion's rationale and highlighted spans (next spec: a
direct Apply/Undo toggle in place of the chat round trip).

## Evaluation (L-47)

1. **Offline, on what exists:** run the check and repair on the 32 L-45 rerun reports plus the
   4 known contradicting options. Read every flag and every edit by hand. Measure flags that
   are real, edits that are correct, edits that damage correct text, the options dropped, and
   latency.
2. **Synthetic errors:** the L-46 contradiction flips and deleted findings, injected into those
   reports. The repair must remove or restore them.

**Pass bar:**
- no correct statement removed or changed wrongly in the clean reports;
- ≥ 90% of injected errors repaired;
- median added latency ≤ 0.8 s.
