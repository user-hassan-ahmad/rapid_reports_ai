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
- **Report side: FINDINGS only.** Report sentences are taken from the report minus its impression section: a line
  that is a heading: IMPRESSION or CONCLUSION, any case, alone on its line or followed by a colon ("Conclusion: ...",
  "IMPRESSION"); "Impression of mild thickening" is not a heading. The section ends at the next heading line (an
  all-caps line, or words and a colon at a line start) or the end of the report. The impression is not checked in v1.
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
   chain_text)`. Sentences come from this check's own splitter (`dictated_number_check.sentence_spans`, used by this
   check only: `template_number_check._sentence` and the number checks are unchanged, so the flag off is zero
   change): no split after approx., e.g., i.e., vs., cf., etc., or inside a decimal; a single letter before a full
   stop does end a sentence ("Stanford type A.", "segment I.", "Hepatitis B."). The report sentence is kept as
   written, any line label included ("RIGHT KIDNEY: cyst 2 cm."): Jev and the code pass see it whole. A leading line
   label or markdown ("AORTA:", "- ", "**Liver:**") is stripped from the dictated sentence, and from the report
   sentence only to form the edit's `find` (§3.5). A value-only fragment — no word besides the value, its unit and a
   measure name also in the dictated sentence ("LVEF 45%.") — is joined to the sentence before it. A dictated sentence equal to a removed sentence is dropped. Identical pairs
   are merged. Each dictated source may carry the scratchpad region it was said under (end review 2026-10-17):
   `findings_block` builds `Statements.said_regions`, parallel to `said_parts` (a placed unit or part: its group;
   a tapped row: its region; Technique, General, unplaced units and typed values: none), and the report route
   passes `(region, text)` sources; the pair carries `region` ("" when none). `said_parts` itself is unchanged.
2. **Pass in code first.** A pair whose report sentence, normalised (case, whitespace, punctuation), contains the
   dictated sentence's normalised text passes without a Jev question — and, when the dictated sentence has a
   region, only if the report sentence also holds every word of that region (else it goes to Jev: "Cyst 2 cm."
   under Right kidney vs "Left kidney: cyst 2 cm." is asked).
3. **Judge (Jev).** One request per report. `state` is a dict of numbered pairs (`{"pair_1": {"dictated": ..,
   "dictated_region": .. ("" when none), "report": ..}, ...}`); one `noul` question per pair, wording W1 from the
   lab, verbatim, plus one region sentence (end review 2026-10-17); the text is
   `dictated_structure_check.QUESTION` (`{key}` = the pair key), for the lab to import:
   "In pair_N, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and level as
   the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site does not. The
   DICTATED sentence was said under the region named in dictated_region; read it as about that region when it names
   no structure itself."
   A pair fails when P(yes) < 0.7 (`SAME_SITE_MIN`, lab §7). At most 12 pairs per report, in report order; any beyond are not asked and are
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
5. **Use your sentence (the edit, Q42).** `Edit(mode="replace", find=<report sentence without its line label>,
   replace=<dictated sentence, capitalised, full stop>)`, applied and undone by the rail's existing apply/undo
   (`edits.ts:214`, `commands.ts:178-187`). Offered only when replacing the whole sentence cannot lose or repeat
   content — all of:
   - `find` is a single sentence (a value-only fragment joined to the sentence before it never gets an edit);
   - the stripped line label holds no content word that the dictated sentence lacks ("RIGHT KIDNEY:" above a
     left-kidney value withholds the edit; side words are not exempt here);
   - the report sentence and the dictated sentence carry the same set of number chains (no merged value, no split);
   - the report sentence and the dictated sentence have the same number of clause joiners: more in the report is a
     merged number-free statement ("... 4.1 cm with no aortic regurgitation"); more in the dictation is a clause the
     writer split into another sentence, which Apply would repeat (lab v4). Joiners: and, with, without, but, whereas, which, while,
     although, except, otherwise, ";", ",", "(", ")", " - ", "—";
   - the report sentence has at most 2 content words (not a stopword; levels never count) that the dictated sentence
     lacks (`NEW_WORDS_MAX`, a backstop: "The left kidney contains a 2 cm cyst." vs "Cyst 2 cm." withholds). Side
     words count here unless the dictated sentence names a side itself, in which case the side is the correction;
   - the report sentence holds no content word (not a stopword) that appears in another dictated statement of the
     same report but not in this pair's dictated sentence (the writer merged that statement in, e.g. "simple" from
     "The cyst is simple.") or in a confirmed assumed normal (`gate.assumed` minus removed: read by this guard only,
     never paired); side words (left, right, bilateral, bilaterally) are exempt, since they are what the check
     corrects; vertebral and disc levels ("L4/5") hold digits and are never content words;
   - when the dictated sentence was said under a region, every content word of that region is in the dictated
     sentence ("Cyst 2 cm." under Left kidney withholds: Apply would drop the structure; "Left kidney cyst 2 cm."
     keeps it). A region word of 4 or more letters also counts as present when a dictated word shares its first 4
     letters, case aside ("Aortic sinus 4.1 cm." under Aorta keeps the edit; "Renal cyst 2 cm." under Kidneys does
     not); a shorter region word must match exactly. No region: no change (lab v3, 2026-10-17). A line label
     stripped from the dictated sentence ("Liver and Biliary:") counts as a region here (edit only; Jev's
     dictated_region is unchanged);
   - `find` occurs exactly once in the report (the rail and verifier require it: `edits.ts:214`, `verifier.py:235`).
   Otherwise the card has no edit; the radiologist edits by hand. The replace is the dictated sentence as said, never
   prefixed with its region; the backstop and the label rule withhold an edit that would lose the region.
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

## 7. Lab (done 2026-10-17; private repo `synthetic/structure_name/`, `results.md`, `results_v2.md`)

155 pairs (26 synthetic reports across CT/MR/US plus real writer outputs from the dictated-wins labs): 30 planted
swaps, 123 clean, hand-labelled before any run; 2 runs; Jev 1.13.

| arm | swaps caught /30 | clean false alarms /123 |
|---|---|---|
| **W1, P(yes) < 0.7, with the splitter fixes** | **28** | **0** (both runs) |
| W1, < 0.5 | 27 | 0 |
| W1, < 0.8 | 28–29 | 2–3 |
| other wordings W2/W3, < 0.5 | 19–22 | 0 |
| code word match (B) | 20 | 11 (8.7%) |

- Caught every time: side, level, broader, narrower; aortic sinus → root caught at 0.7.
- Missed: CBD → common hepatic duct (P 0.84), pancreatic head → pancreatic mass (P 0.78). Qwen not run; a narrow
  Qwen second look would cover the 12% of pairs with P 0.5–0.9 (Hassan Q48: not in v1).
- Latency median 0.24 s, p90 0.29 s; run agreement 98.5–100%; the code pass clears 15% of pairs.
- Edits offered on 25/30 swaps, none unsafe on hand check. The merged-content guard withheld 4 genuine side swaps
  before the side/level exemption (§3.5); the plan's test covers the exemption.
- Number-free renames in real writer outputs: 0 of 70 statements.

## 8. Tests

Unit tests with a fake Jev: pairing (single; a value in two FINDINGS sentences; a chain paired once; "covers");
the code pass; pass-if-any within FINDINGS; FINDINGS wrong but impression right → item; the 12-pair cap;
threshold; fail-open; edit offered / withheld (find occurs twice; merged number-free clause; reverse split; extra
joiner); label and bullet prefixes stripped; an abbreviation ("approx.") splitting a sentence; removed sentences
excluded; two failing values in one sentence → two items; flag off → nothing. A report-route test with the flag on.
A `check_flag_items` test that the edit and `dictated_quote` reach the item.

## 9. Known limits (v1)

- The impression is not checked.
- Close-neighbour renames Jev reads as the same site (CBD → common hepatic duct, pancreatic head → pancreatic mass)
  slip through; revisit only if real reports show them (Q48).
- Statements without a number or unit are not checked until D18 (quick) or a later template pairing.
- The edit guards are word lists, not meaning: a merged clause with no joiner and at most 2 new words can still be
  replaced (e.g. a one-word qualifier); the radiologist sees the dictated sentence on the card before Apply.
- A region-less dictated sentence that the report holds word for word passes in code even if the report placed it
  under another label; regioned sentences are checked against the region's words.
- A sentence split by an abbreviation full stop may pair on a fragment; the edit is then withheld by the rules in §3.5
  when the fragment's chains or joiners differ, and the lab counts how often it happens.
