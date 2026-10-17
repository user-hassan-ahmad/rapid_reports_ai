# Structure-name check (dictated fidelity step 3) — design

Date: 2026-10-17. Branch: `feat/structure-name-check` (from integrate/scratchpad-stack 6acb082d).
Decisions: Hassan, Q41–Q46 (2026-10-17). Labs report; Hassan decides.

## 1. Problem

The writer sometimes moves a dictated measurement to a neighbouring structure. P3 case k07: dictated
"aortic sinus 4.1 cm", report "aortic root 4.1 cm". The number check (step 1) passes because 4.1 cm is present;
the writer rules (step 2) forbid renaming but cannot guarantee it. Nothing flags it today. This blocks template
sessions going default-on.

Mission link: "nothing you said is lost or changed" needs three nets: the number survives (step 1), the wording
survives (step 2), and the structure the number belongs to survives (this step).

## 2. Scope (Q41, Q43)

- **In:** every dictated statement that carries a number with a unit, from the radiologist's own sources only:
  `FindingsInput.said_parts` (dictated units, tapped rows; voice answers too, recorded as taps today and kept there
  after declutter) and typed values (`_value_statements`), minus removed sentences. The same source list the number
  check uses (`hybrid_stack/report.py:101-103`). A typed value entered without a unit ("4.1" against a "(cm)" label)
  is unitless and skipped.
- **Report side: FINDINGS only.** Report sentences are taken from the report minus its impression section (heading
  in `report_review.IMPRESSION_HEADINGS`: IMPRESSION, CONCLUSION). The impression is not checked in v1.
- **Same site** = exactly the same structure, site, side and level. Passes: word order and side placement
  ("kidney (left)" → "left kidney"), true synonyms ("aortic sinus" → "sinus of Valsalva"), abbreviations
  ("CBD" → "common bile duct"). Flags: a different site (sinus → root), a broader site (segment 6 → right lobe),
  a narrower site (liver → segment 6), a different side, a different level (L4/5 → L5/S1).
- **Out (v1):** statements without a number or unit (a small lab count only, §7); the impression; the history,
  assumed normals, recommendations, card values. Template and quick paths both (Q45).

## 3. How it works

1. **Pair (code).** `dictated_number_check` gains `pairs(report_findings, sources)`, reusing its extraction, masking
   and unit normalisation (no new matching code). One pair per dictated **chain** ("2.3 x 1.8 cm" is one chain, as
   in `missing_dictated_numbers`), per FINDINGS sentence that holds it: `(dictated_sentence, report_sentence,
   chain_text)`. Sentences come from `template_number_check._sentence` with any leading line label or markdown
   ("AORTA:", "- ", "**Liver:**") stripped. A dictated sentence equal to a removed sentence is dropped. Identical pairs
   are merged.
2. **Pass in code first.** A pair whose report sentence, normalised (case, whitespace, punctuation), contains the
   dictated sentence's normalised text passes without a Jev question.
3. **Judge (Jev).** One request per report. `state` is a dict of numbered pairs (`{"pair_1": {"dictated": ..,
   "report": ..}, ...}`); one `noul` question per pair asks whether the report sentence gives that value for exactly
   the same structure, site, side and level as the dictated sentence (synonyms and rewording allowed). Wording and
   threshold come from the lab (§7). At most 12 pairs per report, in report order; any beyond are not asked and are
   logged as `structure_name_unchecked` (no item). A chain **passes if any** of its FINDINGS sentences is judged the
   same site.
4. **Report.** A chain that fails becomes one item in `quality_check.review`, anchored on its first FINDINGS
   sentence: `{"kind": "dictated_structure_changed", "severity": "high", "text": <chain>, "sentence": <report
   sentence>, "dictated_quote": <dictated sentence>, "message": ..., "edit": {...} | null}`.
   - `severity: high` → `cls: action` in `review_engine/live.check_flag_items`: an open rail card counted in
     "to review" (`ReviewRail.svelte:147`); never blocks Generate or sign (Q42). Flag items join after
     `_would_preapply` (`engine.py:761-770`), so the edit is never applied automatically.
   - The card shows "You dictated: <dictated_quote>" (`ItemCard.svelte:48`). Label (≤80 chars):
     `Different site from your dictation? Apply puts your sentence back.` The rail's button reads **Apply**
     (`ItemCard.svelte:17`); no frontend change.
   - The dedupe key includes the chain, so two failing values in one sentence give two cards.
5. **Use your sentence (the edit, Q42).** `Edit(mode="replace", find=<report sentence without its label prefix>,
   replace=<dictated sentence, capitalised, full stop>)`, applied and undone by the rail's existing apply/undo
   (`edits.ts:214`, `commands.ts:178-187`). Offered only when replacing the whole sentence cannot lose or repeat
   content — all of:
   - the report sentence and the dictated sentence carry the same set of number chains (no merged value, no split);
   - the report sentence has no more clause joiners ("and", "with", ";", ",") than the dictated sentence (no merged
     number-free statement, e.g. "... 4.1 cm with no aortic regurgitation");
   - `find` occurs exactly once in the report (the rail and verifier require it: `edits.ts:214`, `verifier.py:235`).
   Otherwise the card has no edit; the radiologist edits by hand.
6. **Fails open, small budget.** A Jev error, a timeout (3 s, as `jev_stack.TIMEOUT_S`; lab median ~0.25 s) or a
   partial answer gives no item and logs `structure_name_check_unavailable`. It runs inline after the number check
   and adds at most the timeout to Generate. Never raises; never edits the report itself.

## 4. Switch

`RR_DICTATED_STRUCTURES`, off by default, read per call. Runs only when on, beside the number check in
`hybrid_stack/report.py`. Switched on together with `RR_DICTATED_NUMBERS` when template sessions go default-on.

## 5. Footprint

- New: `backend/src/rapid_reports_ai/dictated_structure_check.py` (pairs → code pass → Jev → items).
- `dictated_number_check.py`: add `pairs()`; `missing_dictated_numbers` unchanged.
- `hybrid_stack/report.py`: one call after the number check.
- `review_engine/live.py`: add the kind to `_FLAG_KINDS` and `_FLAG_LABEL`; pass the entry's `edit` through
  (today every flag item has `edit=None`); key on chain + sentence.
- Frontend: none (an action-class item with an edit is already a card with Apply/Undo; a rail test confirms it).
- Not touched: scratchpad, walkthrough, `findings.py`, `gate_model.py`, copilot cards, writer prompts.

## 6. Coordination

- **D18 notes pipeline** (backend-d6, decided, not built; quick path only): the writer will cite input IDs per
  FINDINGS sentence (`[d3,a1,n7]`). When it lands, the quick path pairs by d-IDs instead of shared numbers, which
  also covers statements without numbers. `pairs()` is the only part that changes; we build no ID scheme of our own.
  Template reports carry no IDs, so number-anchoring stays there.
- **Declutter** (backend-d6): voice answers stay in `said_parts`. No file overlap.
- **Finding facts** (backend-30): no overlap; this check reads FINDINGS sources only.

## 7. Lab (before the plan; private repo `synthetic/structure_name/`)

- ~20 synthetic cases across template and quick, built from P3-style dictations, 2 runs each, plus a hand read.
- Planted swaps: different site (sinus → root), broader (segment 6 → right lobe), narrower (liver → segment 6),
  side (left → right), level (L4/5 → L5/S1). Clean controls: synonyms, abbreviations, side placement, joined
  sentences, label prefixes. Real writer outputs from the dictated-wins / quick-dictated-wins labs are reused as
  further clean cases.
- Arms: **A** Jev pair question (2–3 wordings); **B** a small code word-match baseline (free, one script);
  **C** Qwen judge only if A's false alarms are clearly above ~2% per pair.
- A hand count, from the reused writer outputs only, of renames in statements without numbers (no separate arm).
- Report: per-arm recall on planted swaps, false alarms on clean pairs, latency, how often the edit is offered and
  whether any offered edit would lose or repeat content.

## 8. Tests

Unit tests with a fake Jev: pairing (single; a value in two FINDINGS sentences; a chain paired once; "covers");
the code pass; pass-if-any within FINDINGS; FINDINGS wrong but impression right → item; the 12-pair cap;
threshold; fail-open; edit offered / withheld (find occurs twice; merged number-free clause; reverse split; extra
joiner); label and bullet prefixes stripped; an abbreviation ("approx.") splitting a sentence; removed sentences
excluded; two failing values in one sentence → two items; flag off → nothing. A report-route test with the flag on.
A `check_flag_items` test that the edit and `dictated_quote` reach the item.

## 9. Known limits (v1)

- The impression is not checked.
- Statements without a number or unit are not checked until D18 (quick) or a later template pairing.
- A sentence split by an abbreviation full stop may pair on a fragment; the edit is then withheld by the rules in §3.5
  when the fragment's chains or joiners differ, and the lab counts how often it happens.
