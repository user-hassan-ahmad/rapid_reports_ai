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
  check uses (`hybrid_stack/report.py:101-103`).
- **Same site** = exactly the same structure, site, side and level. Passes: word order and side placement
  ("kidney (left)" → "left kidney"), true synonyms ("aortic sinus" → "sinus of Valsalva"), abbreviations
  ("CBD" → "common bile duct"). Flags: a different site (sinus → root), a broader site (segment 6 → right lobe),
  a narrower site (liver → segment 6), a different side, a different level (L4/5 → L5/S1).
- **Out (v1):** statements without a number (a lab arm only, §7); unitless numbers (too ambiguous to pair);
  the history, assumed normals, recommendations, card values. Template and quick paths both (Q45).

## 3. How it works

1. **Pair (code).** `dictated_number_check` gains `pairs(report, sources)`: for each dictated chain with a unit that
   the report holds, return `(dictated_sentence, report_sentence, value_text)`, reusing its existing extraction,
   masking and unit normalisation (no new matching code). A dictated value held in more than one report sentence
   yields one pair per report sentence; identical pairs are merged.
2. **Judge (Jev).** One request per report; one `noul` question per pair, asking whether the report sentence gives
   the value for exactly the same structure, site, side and level as the dictated sentence (synonyms and rewording
   allowed). Exact wording and the threshold come from the lab (§7). A dictated value **passes if any** of its
   report sentences is judged the same site.
3. **Report.** A failed value becomes one item in `quality_check.review`:
   `{"kind": "dictated_structure_changed", "severity": "high", "text": <value>, "sentence": <report sentence>,
   "dictated": <dictated sentence>, "message": ..., "edit": {...} | None}`.
   - `severity: high` → `cls: action` in `review_engine/live.check_flag_items`: an open rail card that counts toward
     "to review"; never blocks Generate or sign (Q42).
   - Label (≤80 chars): `Different site from your dictation? You said: "<dictated sentence>"` (truncated).
   - **Use your sentence** (Q42): `Edit(mode="replace", find=<report sentence>, replace=<dictated sentence,
     capitalised, full stop>)`, applied and undone through the rail's existing apply/undo. Offered only when the
     report sentence is safe to replace whole: it pairs with exactly one dictated sentence and every number in it
     comes from that dictated sentence. Otherwise the card has no edit (the radiologist edits by hand), so a joined
     sentence never loses its other content.
4. **Fails open.** A Jev error, timeout (6 s, as `structure_mentions`) or partial answer gives no item and logs
   `structure_name_check_unavailable`. Never raises; never edits the report itself.

## 4. Switch

`RR_DICTATED_STRUCTURES`, off by default, read per call. Runs only when on, beside the number check in
`hybrid_stack/report.py`. Switched on together with `RR_DICTATED_NUMBERS` when template sessions go default-on.

## 5. Footprint

- New: `backend/src/rapid_reports_ai/dictated_structure_check.py` (pairs → Jev → items).
- `dictated_number_check.py`: add `pairs()`; `missing_dictated_numbers` unchanged.
- `hybrid_stack/report.py`: one call after the number check.
- `review_engine/live.py`: add the kind to `_FLAG_KINDS` and `_FLAG_LABEL`; pass the entry's `edit` through
  (today every flag item has `edit=None`).
- Frontend: none expected (an action-class item with an edit is already a rail card with apply/undo); the plan
  confirms with a rail test.
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
  sentences. Real writer outputs from the dictated-wins / quick-dictated-wins labs are reused as further clean cases.
- Arms: **A** Jev pair question (2–3 wordings); **B** code word-match baseline (anatomy words + side + level);
  **C** Qwen judge only if A's false alarms are clearly above ~2% per pair.
- Side arm: statements without numbers, paired by hand, to measure how often renames happen there.
- Report: per-arm recall on planted swaps, false alarms on clean pairs, latency, how often the edit is offered.

## 8. Tests

Unit tests with a fake Jev: pairing (single, repeated value, "covers", joined sentence), pass-if-any, threshold,
fail-open, edit offered / withheld, removed sentences excluded, flag off → nothing. A report-route test with the
flag on. A `check_flag_items` test that the edit reaches the item.

## 9. Known limits (v1)

- A rename only in the impression is not flagged when FINDINGS states the right site (pass-if-any).
- Statements without a number or unit are not checked until D18 (quick) or a later template pairing.
