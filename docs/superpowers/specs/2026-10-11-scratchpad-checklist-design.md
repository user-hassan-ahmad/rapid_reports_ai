# Scratchpad v2 addendum: the report as the answer to a checklist

Date: 2026-10-11 (revised after the checklist lab) · Branch: `feat/hybrid-stack` (PR #31, unmerged) · Status: agreed

Supersedes in `2026-10-11-scratchpad-v2-design.md`: §4 (check chips) and §4.1, the chip parts of §5 (gate) and §6
(Generate), and the revision block's "chips as assumed statements". Everything else in v2 stands: the one view,
the grouper and its `abnormal` field, the tray, the conclusion and its draft, editing and voice commands, rollout.

Mock-ups (agreed UI and wording; the build uses the app's RadFlow skin):
- method walk-through: https://claude.ai/artifact/8HNp8zrFzE9rBL1hn5kYnY
- scratchpad playback: https://claude.ai/artifact/JNyR6MTAy3SFgRVmMsvzoK

## 1. Why

Default-include made every chip a statement nobody had checked. Two labs (§10) found one failure:

- **Nearly every wrong statement decides something about the finding the radiologist just dictated:**
  - "No perinephric stranding" beside an obstructing stone;
  - "No extension into the iliac arteries" for an aneurysm;
  - "No lobar clot" for segmental emboli;
  - "No phlegmon" in appendicitis.
- **No separate judge catches these reliably.** We tried Jev, the production negatives classifier, a dedicated type
  question, and the writer tagging its own sentences. Each either missed them or flagged nearly everything. The one
  that worked made the writer terse and cut recall by a third.
- **Today's skill-sheet path is no better.** Run against the same dictations, it found as many must-have negatives
  as the live writer (33 vs 35 of 46). It made as many mistakes, and it added about 6 extra statements per report,
  a fifth of them low value.

So **negatives triggered by a finding are asked, never assumed.** Generic normals for untouched regions are assumed,
as the tray already does.

## 2. The model

> The report is the answer to a checklist. The machine writes the questions, the radiologist gives the answers,
> the generator writes the words.

### 2.1 Items

| Kind | Written when | From | Default |
|---|---|---|---|
| **Referral** | At setup, then refreshed with the dictation | The live writer's referral line (§4.1) | **Question open** until answered |
| **Finding** | Live, after abnormal findings | The live writer (§4.1) | **Question open** until answered |
| **Region normal** | When the slim sheet is ready | The slim sheet's region normals (§8) | **Assumed**, unless the dictation covers or contradicts it (§5) |

### 2.2 States

| State | Meaning | Shown as | Reaches the report |
|---|---|---|---|
| **Answered** | The dictation covers it, or the radiologist tapped the answer | Not shown separately (their words are on the pad), or a green row that folds away | The dictated words, or the tapped sentences |
| **Assumed normal** | A generic normal for a region, not contradicted | The region's quiet line, or a dashed tray pill | The sentence, once confirmed at the gate |
| **Question open** | A finding row or a referral row not yet answered | An amber row | Nothing until answered |

### 2.3 Ownership

| Step | Owner |
|---|---|
| Referral and finding items | One whole-case Qwen call (§4.1) |
| Region normals | The slim sheet (§8) |
| Covered or contradicted (per sentence) | Jev, the existing stated/contradicted pair (§5) |
| Answers | The radiologist (dictation or tap) |
| Words | The generator |

## 3. The scratchpad

Top to bottom (as in the playback mock-up):

1. **Live strip:** the words being spoken.
2. **Referral row:** label "Asked in the referral · {question in the history}", the question, its sentences (each
   on its own line with ×), and buttons. For one sentence the button is that sentence ("Appendix normal"); for two
   it is "Both normal". Plus **Dictate**. When answered: green and compact, "✓ Appendix normal".
3. **Abnormal region cards** (v2, unchanged), each holding:
   - the radiologist's lines;
   - **amber finding rows** (at most 2 per region): question, one-line reason, the row's sentences (at most 2, each
     on its own line with ×), then the same buttons and **Dictate**;
   - **quiet line:** "Will also be reported:" then the region's assumed normals in report form, at most 3, then
     "+n more". Each sentence has × to remove it.
4. **Type a finding…** (v2, unchanged).
5. **Tray:** "Normal regions", with two keys, "you said it" (solid) and "assumed" (dashed). Hovering or tapping a
   dashed pill shows its assumed sentences, each with ×.
6. **Conclusion** (v2, unchanged).
7. **Gate bar:** "{n} questions open · {m} assumed normal", and **Confirm**.

### 3.1 Wording rules

- Assumptions are shown as the sentences the report will contain. Never as labels ("normal expected: free gas").
- Answer buttons carry the sentence they add, or "Both normal" with both sentences in view directly above. A tap
  adds only the sentences still listed: × removes a sentence from the row first (it is then never stated and is
  sent as DO NOT ASSERT).
- Two state words only, in copy the radiologist sees: "assumed" and "question open".
- Items the dictation already answers are not shown.

### 3.2 Interactions

- **Answer by voice:**
  - When Jev reads every sentence of a row as stated, the row resolves ("Answered in your dictation") and folds
    away.
  - A row whose sentences the dictation contradicts also folds away. The radiologist has described the opposite,
    in their own words.
- **Answer by tap:** the button adds that row's sentences as answered, attributed to the radiologist
  (`answered_by: "tap"`).
- **Dictate:** puts the caret in "Type a finding…" under that region (v2 §7 rules).
- **Remove an assumed sentence:** ×. It is never stated, and goes to the generator as DO NOT ASSERT.

### 3.3 Why every row sentence has its own ×

The lab's wrong sentences have not gone away; they now sit inside rows. In arm D, 18 of 89 row sentences (20%) were
graded wrong, and 10 of 20 cases held at least one. Many of these are fine to *ask* (whether an aneurysm extends
into the iliacs is a real check) and wrong only when stated unchecked. Others are wrong to ask at all: they
contradict the dictation, deny a typical sign of the dictated diagnosis, or ask for something this scan can't show.

So a tap must assert only what the radiologist has seen in front of them:
- at most 2 sentences per row (the most decisive first);
- each sentence visible above the button, with ×;
- no collapsed "All normal" that hides its sentences.

The re-run lab (plan V2) grades row sentences as "fine to ask" or "wrong to ask". Target: at most 1 row in 10 holds
a wrong-to-ask sentence. Hand reads record the same.

### 3.4 Friction budget

Amber rows are the only interruption. Expected: about 2 per case including the referral row. Caps: 2 finding rows
per region, 4 rows per case including the referral row. Measured in the hand reads (§10.2); if real cases run higher, lower the cap
before release.

### 3.5 Skin

The RadFlow theme as in the current view:
- dark panels, white at low opacity;
- amber for open questions, emerald for answered and assumed, rose for abnormal regions;
- the purple primary button (`btn-primary-subtle`) for Confirm;
- IBM Plex Sans / DM Sans.

The layout and wording follow the mock-up.

## 4. Writing items

### 4.1 The live writer (arm D)

- One Qwen call (Cerebras, reasoning off) over the whole scratchpad.
  - Called once at setup with no dictation, which yields the referral item only.
  - Called again, debounced, whenever the abnormal sentences change.
- Prompt: arm D from the lab, the IntelliPrompts framing trimmed to structural rules:
  - the threshold (implied structure, management-changing, not already assessed);
  - one item per root finding;
  - the modality rule;
  - never deny anything dictated, its expected consequence or a typical sign of a dictated diagnosis;
  - urgency order;
  - the referral line: one separate item for a referral question the dictation does not answer.
- Input: scan type, history, region list, dictation, and the slim sheet's "Not assessable on this scan" list when
  available.
- Output per item: `source_text`, `region`, `question` (≤ 12 words, ends "?"), `rationale` (one line, shown as the
  reason), `negatives` (1–3 report sentences, one absent finding each; code keeps the first 2).
  - An item with empty `source_text` is the referral item.
- The radiologist's removed sentences are in the user prompt ("REMOVED BY THE RADIOLOGIST: never propose these or
  an equivalent").
- Cache: the writer's items by (scan key, history, abnormal sentences, region list, removed). The checks (§5)
  always run on the current dictation.
- Fail open: no items. The scratchpad works as v2 without chips. The referral row is absent.

### 4.2 The chain on every update

1. **Qwen writes the rows** (§4.1).
2. **Qwen splits multi-claim sentences** with the production splitter (`report_reconcile._split_bundled`, as the
   brief uses it today: Qwen decides how many claims a sentence holds, and `_split_keeps_claims` keeps the
   original wording). Parts inherit the row. The Jev wording for this failed its lab (§10.2).
3. **One Jev call checks every row sentence** (§5): already dictated, contradicted, or the same as a removed
   sentence.
4. **Code applies the limits:** exact repeats removed, the first 2 sentences per row, the first 2 finding rows per
   region, at most 4 rows per case including the referral row. All in the writer's urgency order. Rows beyond the
   caps are kept in the gate record as `capped` and offered in the Optional additions panel after Generate.

Code makes no judgement about meaning. Every judgement about wording against the dictation or the radiologist's
choices is a validated Jev question; every judgement needing clinical knowledge is Qwen's.

## 5. The checks (Jev)

One Jev call per update, over every row sentence (and the assumed normals of abnormal regions):

| Question | Wording | Row sentence | Region normal |
|---|---|---|---|
| **stated** | today's `stated_question` | ≥ 0.8 → drops (answered); a row with none left resolves | ≥ 0.8 → hidden (answered) |
| **contradicted** | today's `contra_question` | ≥ 0.7 → drops (the dictation says otherwise) | ≥ 0.3 → hidden, never assumed |
| **removed** | new (§10.2): "The STATEMENT says the same thing as one of the REMOVED statements: the same check on the same structure, in any wording." | ≥ 0.6 → drops | ≥ 0.6 → hidden |

A region normal with stated or contradicted between 0.3 and the removal bars is hidden, never assumed (hedged).

Region normals of untouched regions (tray pills) are checked only against removed sentences.

If the call fails, every region normal of an abnormal region is hidden. Rows stay as written, and removed sentences
are filtered by exact match only.

## 6. The gate

- Confirm needs: no open questions, a conclusion (v2 §5), nothing syncing, no field being edited.
- The gate record (`dictation_stack_logs.gate`) gains:
  - `items`: id, kind, region, question, sentences, state, `answered_by` (`dictation` | `tap`);
  - `assumed`: per region, the confirmed sentences;
  - `removed`;
  - `capped`.

  It replaces `included_chips` and `declined_chips`.

## 7. What Generate receives

Answers only:

```
Pelvic organs: A 5 cm simple-appearing right ovarian cyst. No features of torsion.
  Answered by the radiologist: No features of torsion.          (a tapped row; dictated answers are already above)
  Assumed normal (confirmed by the radiologist): The uterus is normal. The left ovary is normal.
Peritoneum: Small volume of free fluid in the pelvis.
Appendix (answered by the radiologist): The appendix is normal.
Assumed normal (confirmed by the radiologist): Liver: … Spleen: … (the tray regions' sentences)
Conclusion (confirmed by the radiologist): …
DO NOT ASSERT: <removed sentences>
```

- **Quick path:** the brief runs in stack mode on the **slim sheet**. It renders structure, style, terminology,
  measurement and impression conventions, and the confirmed conclusion. It has **no negatives stage** (no mandatory
  or If-present negatives, no `_fallback`, no finding-linked or implicated options).
  - If the slim sheet is missing, use v2's `stack_fallback` on today's sheet.
- **Template path:** the lean path, unchanged, with removed sentences passed as `declined`.
- The generator prompts are unchanged. The post-generation check runs unchanged against the findings block.

## 8. The slim skill sheet

A new analyser output for stack sessions. Today's analyser stays for the non-stack path and the shadow comparison,
untouched. Memory: its prompt exists twice; neither copy changes.

### 8.1 Content

| Section | Source | Used by |
|---|---|---|
| **Scan Context**: modality, imaged volume, contrast, phase, **Not assessable on this scan** | Today's section | Writer (modality rule), generator |
| **Structural Pattern**: sections, sweep order, macro-structure | Today's section | Generator |
| **Region normals** (new): for each region of the scan family's schema (names passed in), 1–6 normal sentences in final report form, one structure each, no measurements | New | Quiet lines, tray, gate, generator |
| **Style Exemplars** (abnormal exemplars only) | Today's section | Generator |
| **Terminology Rules** | Today's section | Generator |
| **Measurement Conventions** | Today's section | Generator |
| **Impression conventions**: opening convention, descriptor propagation | Today's section (exemplars with negative lists dropped) | Generator |
| **Recommendation scope** | Today's section | Options after Generate |

Removed: Clinical Lane, the Companion Matrix (companions, mandatory negatives, If-present, suppressed),
Conditional Suppression Rules, Interpretive Clause Rules.

### 8.2 Keying, model, timing

- Keyed by **(scan-type family, contrast facet)**, decided 2026-10-11:
  - the family is the one the stack already resolves (Jev pick plus reconciler, reviewer-approved);
  - the contrast facet is a Jev choice from a fixed list at setup: none, arterial, portal venous, multiphase,
    delayed, unknown;
  - context words in the scan type ("trauma", "?appendicitis", "staging") do not change the key. They reach the
    writer and the referral row. Add a context facet only if hand reads show normals reading wrong (for example
    trauma's "intact").
- Stored in a new table `stack_slim_sheets` (family, contrast, prompt version, status, markdown, region normals as
  JSON, not_assessable).
- **Review, decided 2026-10-11:**
  - a new sheet is `provisional` and **used immediately**: the radiologist still confirms every assumed sentence;
  - reviewers (`RR_STACK_REVIEWERS`) approve, edit a sentence, or discard and rebuild, on the existing review page;
  - a sheet sentence removed with × in ≥ 30% of ≥ 5 confirmed sessions is flagged to the top of the review page
    (from the gate log's `removed`).
- Generated at workspace setup when no cached sheet exists, in parallel with today's analyser.
- Model: `MODEL_CONFIG["STACK_SLIM_SHEET"]`, defaulting to Qwen on Cerebras at medium reasoning. Since it is cached,
  a slower, stronger model can replace it with no workflow cost.
- Until it is ready:
  - abnormal regions show no quiet line;
  - tray pills have no sentences;
  - Generate uses `stack_fallback`.

### 8.3 Template path

No slim sheet. Region normals come from the template's stored sheet structure (`template_sheet_structure`):
- each paragraph is a region;
- its `Normal` and unconditioned `Negative` statements are the region normals;
- conditioned negatives are not used in this release.

## 9. Retirements (stack sessions only)

- `hybrid_stack/chips.py`, `POST /api/hybrid-stack/chips`, `CHIP_FORM`, the chip states and the chip UI.
- Voice "accept suggestion" becomes "answer the question": the same Jev command, with `target_item` naming a row;
  accepting taps that row's answer.
- The brief's stack-mode negatives handling (`stack_offers`, finding-linked offering) and the `_fallback` reuse.

## 10. Labs

### 10.1 Results (2026-10-11)

Harness: `scripts/checklist_lab.py`. Fixtures: `tests/fixtures/hybrid_stack/checklist_cases.json`, 20 blind cases
(5 where the referral question points away from the finding, 2 where the finding implies things, 2 with no
question). Graded by Sonnet 5.5.

| Arm | Must-haves in report by default → surfaced (of 46) | Wrong statements in report by default | Notes |
|---|---|---|---|
| S: today's skill-sheet path | 33 → 33 | 9–13 | 132 statements, 25 low value |
| D: live writer | 27 → 35 | 9–17 | |
| D + Jev or production classifier | 13–24 → 25–26 | 9–28 | |
| D + a separate type judgement (Qwen or Jev) | 30–35 → 34–35 | 14–20 | |
| D + `implied` field (D1) | worse recall, more bundles | | dropped |
| D with the writer tagging its own sentences (D2) | 15–18 → 22–23 | 0–2 | writer turns terse |
| **D, finding rows asked (this design)** | n/a → 35 | **0 by construction** | ≈ 2 amber rows per case (estimate) |

The grading itself varies: the same sentences graded twice gave D 12 and then 17 wrong. Small differences are noise.

### 10.2 Jev wording lab (before building on the two new questions)

About 40 sentence pairs per question, written blind, with gold labels:
- **removed:** a candidate sentence against a list of removed sentences. Same check reworded (gold yes), a
  different check about the same structure (gold no), an unrelated sentence (gold no).
- **multiple findings:** "No pericolic or pelvic collection" (one check), "No torsion or rupture" (two),
  "No SMA or SMV encasement" (two), "Liver and spleen normal" (two), plain single sentences (one).

Two wordings per question, asked in one call alongside stated and contradicted (as production asks them).

**Result (2026-10-11):**
- **removed:** wording A at 0.6 → 17/20 rewordings caught, 0 of 20 false. Adopted. The misses are near-synonyms
  ("pericolic abscess" against "pericolic fluid collection"); they stay in the row, where the radiologist can ×
  them again.
- **multiple findings:** wording A never fired (all ≤ 0.21). Wording B tracked conjunctions, not claims (at 0.5:
  16/20 caught, 7/20 false). Dropped. The production splitter owns the judgement instead (§4.2).

### 10.2b Review gating and the conclusion (2026-10-12)

After the first end-of-dictation review, a change re-runs the full review only when the abnormal findings changed
materially; everything else (rewording, an inline edit, a typed normal, a polish pass) gets the quiet re-check:
Jev on the rows on screen and the tapped answers (`/recheck`), no writer call, no skeleton. There is no manual
re-check button. The full review keeps the existing rows on screen; the skeleton shows only when there are none.

- **Material change** (`/changed`, `jev_stack.ask_material`, ≥ 0.6, fails to material). The question counts "a
  different size or measurement" as material and only "the same measurement in another format or unit" as a reword
  (an earlier wording said "correcting ... numbers" counted as a reword, which a size correction could hit). Lab, 40
  hand-written pairs incl. 5 size or unit corrections and 3 same-size format edits: material 21/21 at ≥ 0.95,
  rewordings all ≤ 0.57.
- **The conclusion** is greyed until the first findings land, then the AI draft appears; without one, the field
  takes typing or dictation and offers ✨ Draft with AI. On a material change an unedited AI draft is redrawn. A
  conclusion the radiologist owns (edited, typed or dictated) is never overwritten: `/conclusion-check`
  (`ask_stale`, ≥ 0.7, fails quiet) and, if out of date, a quiet note naming the new findings with a suggested
  redraft on click ("Use this" / "Keep mine"). The note never blocks Confirm. Lab, 24 pairs: out of date 13/13
  (lowest 0.74), still current 0/11 (highest 0.66).
- Fixtures: `tests/fixtures/hybrid_stack/material_change_fixture.json`, `conclusion_check_fixture.json`; script
  `scripts/scratchpad_v2_labs.py material | conclusion`. Both fixtures were written by us: watch the live logs.

### 10.2c Dictation checks in the checklist (2026-10-12)

The integrity check (`/api/dictation/check`: tier 1 code rules for an unfinished sentence or a missing dimension;
tier 2 gpt-oss-120b on Cerebras for sides, measurement vs descriptor, contradictions and units) keeps its backend.
In a scratchpad session its yellow banner and its 600 ms polling are retired (the banner's "jump to" link also
pointed at the hidden editor):

- **Placement.** An unfinished sentence is a dashed amber underline on its line ("Unfinished sentence? · Finish it ·
  ✓ As dictated"). A tier 2 flag is an amber row in the card holding its sentence, quoting both statements, with
  Dictate correction (the line opens and the mic starts), Skip and ✓ As dictated. Unplaced flags show up top.
- **One gate.** An unfinished sentence is an open item at Confirm (it replaces "Generate anyway"); tier 2 never blocks.
- **Timing.** The check runs with the review: tier 1 on every review and quiet re-check, tier 2 only on the first
  review and material changes; tier 2 flags stay while their words are still dictated. Answers are keyed by kind and
  quote. A failed check shows nothing new and never holds Confirm.
- **Gate record.** `checks`: each flag seen and how it ended (as_dictated, skip, edited, open).
- **After Generate**, the review rail keeps its items; open rows take the same tinted left edge (amber check, green
  automatic edit, blue option), so a flag looks alike before and after Generate.
- **The clean-up guard** (live clean-up, `fix/polish-attachment`, separate from this PR): new words placed before text
  already dictated, new words out of spoken order, a side or number shifting between dictated sentences, or a new
  sentence merged into a finished one trigger one Jev question (moved a side, location, size or descriptor onto
  another finding?); a move falls back to the words as said. Whole guard on 28 pairs: 15/15 caught (3 swaps with no
  new words included), 0/13 false; replay of 111 real clean-ups: 0 fires.

### 10.3 Before release

Hand reads on the local build:
- one quick case of each kind in the fixture set;
- one template case.

Record amber rows per case, taps, and the generated report. The release gates:
- median amber rows ≤ 2, max ≤ 4;
- no statement in a report that the radiologist did not dictate, tap or confirm.

## 11. Rollout

Unchanged from v2:
- default-on for stack sessions;
- kill switch `RR_HYBRID_STACK=0`;
- opt-out `localStorage rr_hybrid_stack=0`;
- the old path in shadow.

The slim sheet is generated alongside today's analyser, so the shadow comparison keeps both.

## 12. Decisions

Settled in conversation:
- The checklist model.
- **Finding-triggered negatives are asked, never assumed. Region normals are assumed.**
- Referral rows stay open until answered.
- UI order and wording per §3, in the RadFlow skin.
- A new slim sheet for this flow, quick path only.

Defaults taken here (say if any is wrong):
1. At most 2 finding rows per region and 4 rows per case.
2. The slim sheet defaults to Qwen at medium reasoning (cached, so it can be swapped for a stronger model).
3. Tapped answers are attributed to the radiologist.
4. Template conditioned negatives are not used in this release.
