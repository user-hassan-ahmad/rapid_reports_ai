# Scratchpad v2 addendum: the report as the answer to a checklist

Date: 2026-10-11 · Branch: `feat/hybrid-stack` (PR #31, unmerged) · Status: agreed in conversation, spec for review

Supersedes in `2026-10-11-scratchpad-v2-design.md`: §4 (check chips) and §4.1, the chip parts of §5 (gate) and §6
(Generate), and the revision block's "chips as assumed statements". Everything else in v2 stands: the one view,
the grouper and its `abnormal` field, the tray, the conclusion and its draft, editing and voice commands, rollout.

Mock-ups (agreed UI and wording):
- method walk-through: https://claude.ai/artifact/8HNp8zrFzE9rBL1hn5kYnY
- scratchpad playback: https://claude.ai/artifact/JNyR6MTAy3SFgRVmMsvzoK

## 1. Why

Default-include turned every chip into a statement the radiologist had not checked. Labs on 16 blind cases
(§10.1) showed two failures with one cause:

- **Leaks:** a wrong included chip is stated in the report.
  - Most of these deny something the dictated finding implies (no sonographic Murphy sign in cholecystitis; the
    thecal sac not compressed beside a disc extrusion; no pleural invasion when the mass "abuts" the pleura).
  - Nothing downstream catches them, because the findings block marks them as confirmed.
- **Gaps:** chips only follow abnormal findings. When the referral asks about a region with no finding
  ("?appendicitis" with an ovarian cyst), the report can stay silent on the question asked.

The skill sheet cannot fix either: it is written before dictation, so it guesses findings.

## 2. The model

> The report is the answer to a checklist. The machine writes the questions, one judge decides the expected
> answer, the radiologist gives the answers, the generator writes the words.

### 2.1 Items

Every item is a question about the scan. It carries the sentence that answers it when normal.

| Source | Written when | From | Example |
|---|---|---|---|
| **Referral** | Setup, before dictation | Scan type and clinical history | "Appendix: normal or inflamed?" → "The appendix is normal." |
| **Finding** | Live, after each abnormal finding | The dictation (whole case) | "Ovarian torsion?" → "No features of torsion." |
| **Survey** | Setup | The region schema, and the slim sheet's normal sentences | Region "Peritoneum" → "No free fluid." |

Timing decides the source: whatever is knowable from scan type and history is prepared before dictation; whatever
a finding sets off is written live. Neither side guesses at what the other knows.

### 2.2 States

Exactly one per item, recomputed whenever the dictation changes:

| State | Meaning | Shown as | Reaches the report |
|---|---|---|---|
| **Answered** | The dictation covers it, either way | Not shown separately: the radiologist's own words are on the pad | The dictated words |
| **Assumed normal** | Routine check; nothing in the dictation suggests otherwise | The answering sentence, in the region's quiet line or as a dashed tray pill | The sentence, once confirmed at the gate |
| **Question open** | The finding implies it or leaves it open, or it is a referral item | An amber row with answer-shaped buttons | Only the radiologist's answer |

Rule by source: **referral items are always "question open" unless answered.** That rule is not a judgement.

### 2.3 Ownership (one owner per judgement)

| Step | Owner |
|---|---|
| Referral items | One small call at setup (§4.1) |
| Finding items | One whole-case Qwen call, live (§4.2) |
| Survey items and their sentences | The region schema plus the slim sheet (§8) |
| Expected answer per item | One judge (§5) |
| Answers | The radiologist |
| Words | The generator |

## 3. The scratchpad

Order, top to bottom (as in the playback mock-up):

1. **Live strip:** the words being spoken.
2. **Referral row:** label "Asked in the referral · {question from the history}". The amber question has
   answer-shaped buttons, for example **Appendix normal** and **Dictate**. When answered it turns green and
   compact: "✓ Appendix normal".
3. **Abnormal region cards** (v2 §2, unchanged), each with:
   - the radiologist's lines;
   - amber rows for that region's open questions: question, a one-line reason, and buttons **{answering
     sentence}** and **Dictate**;
   - one quiet line: "Will also be reported:" followed by the assumed sentences, in report form.
4. **Type a finding…** (v2, unchanged).
5. **Tray:** "Normal regions", with two keys: "you said it" (solid) and "assumed" (dashed).
6. **Conclusion** (v2 §5, unchanged).
7. **Gate bar:** "{n} questions open · {m} assumed normal" and **Confirm**.

### 3.1 Wording rules

- Show assumptions as the sentences the report will contain. Never as labels ("normal expected: free gas").
- An answer button carries the exact sentence a tap adds.
- Two state words only, in copy the radiologist sees: "assumed" and "question open".
- Items already answered by the dictation are not shown. The radiologist's words already say it.
- A quiet line shows at most 3 sentences, then "+n more" (expands in place).

### 3.2 Interactions

- **Answering by voice:** dictation that answers an open question resolves it. The row turns green ("Answered in
  your dictation") and folds away. No tap.
- **Answering by tap:** the answer button adds its sentence as an answered item, attributed to the radiologist
  (gate record `answered_by: "tap"`).
- **Removing an assumed sentence:** × on a quiet-line sentence (or tap a dashed pill, then ×). It is never stated
  and goes to the generator as DO NOT ASSERT (today's declined-chip path).
- **Dictate:** puts the caret in "Type a finding…" under that region (v2 §7 rules).

### 3.3 Friction budget

Amber rows are the only interruption. Target: median ≤ 2 open questions per case including the referral row,
max ≤ 4. The judge enforces this (§5.2). If it can't, the design fails the lab (§10).

## 4. Writing items

### 4.1 Referral items (setup)

- One call when the workspace is set up, beside today's analyser call: input scan type and clinical history;
  output 0–3 items.
- Each item: `region`, `question`, `answer_if_normal`, `why`.
- Scope: the diagnosis the history asks about, and any complication of it that changes management. An
  alternative diagnosis only when the history itself raises it. Nothing this scan type cannot show.
- No question in the history (for example "staging", "follow-up") → no referral items.
- Cached by (scan key, normalised history). Qwen on Cerebras, reasoning low (it runs off the critical path).
- **Lab question:** this call against D's referral line (§10, arm D-ref). If D's line matches on recall,
  referral items come from the live call and this call is dropped.

### 4.2 Finding items (live): arm D

- One Qwen call over the whole scratchpad, debounced on placed abnormal units (replaces per-region `/chips`).
- Input: scan type, history, region list, the dictation, the referral items, and the slim sheet's
  "Not assessable on this scan" list (§8).
- Prompt: the IntelliPrompts framing (what does this finding make a consultant check on this scan), trimmed to
  structural rules:
  - the threshold;
  - one item per root finding;
  - the modality rule;
  - urgency order;
  - plus D's referral line, if §10 keeps it.
- Output per item, in decoding order (the order makes the model write what it must not deny first):

```
source_text   verbatim trigger, 3–6 words ("" for a referral-gap item)
region        from REGIONS
implied       what the finding already implies or leaves open: its signs, its effect on neighbours, any extent the
              radiologist hedged ("abuts")
question      ≤ 12 words, ends with "?"
why           one line, shown under an amber row
answers       1–3 sentences, final report form, one absent finding each; never denies anything in `implied`
```

- Schema rules: `answers` has at least one entry; code splits any "or" bundle with the existing splitter, or
  drops the bundle.
- Cache: Qwen's items by (scan key, history, abnormal sentences); the judge always runs against the current
  dictation (as chips today).

### 4.3 Survey items

- Regions come from the schema library and the family reconciler, as now.
- Each region's assumed sentences come from the slim sheet (§8.1), keyed by region name.
- A region the radiologist dictated is answered; otherwise it is assumed normal.
- An abnormal region's quiet line lists:
  - its finding items in the assumed state;
  - then the region's remaining normal sentences that the dictation does not cover (judged the same way, §5).

## 5. The expected-answer judgement

### 5.1 Question

Per item: given the dictation, is it answered, normal to assume, or open? This one judgement replaces the chip
states (`gone` / `optional` / `included`) and the brief's negatives classifier for stack sessions.

Candidate owners, decided by the lab (§10):

| Candidate | How |
|---|---|
| **J1** Jev (today's pair) | stated ≥ 0.8 → answered. Contradicted ≥ 0.7 → **open**: the dictation says otherwise, so the radiologist words it. Else assumed. |
| **J2** The production negatives classifier | `QWEN_SYS_FULL`, run on the item sentences: `dictated` → answered; `contradicted`, `expected` or `implicated` → open; `keep` or `default` → assumed. |
| **J3** J1 plus the writer's `implied` field | An answer the writer itself flags against `implied` → open. |

The memory rule applies: Jev detects and verifies, Qwen judges and writes. J2 is the existing Qwen judge with the
label that targets the leak type; J1 is cheap. J3 tests whether constraining the writer is enough on its own.

### 5.2 Fail-safe rules (code)

- An item whose judgement fails or times out is **not assumed**: it becomes open if it is the region's most
  urgent item, otherwise it is dropped (not stated).
- **Friction cap:** at most 2 open finding questions per region, chosen by the writer's urgency order. Any other
  item judged open is dropped (not stated), never assumed. A dropped item shows in the Optional additions panel
  after Generate.
- Referral items are exempt from the cap.

## 6. The gate

- Confirm needs: no open questions, a conclusion (v2 §5), nothing syncing, no field being edited.
- The gate record (`dictation_stack_logs.gate`) gains:
  - `items`: id, source, region, question, state, answer, `answered_by` (`dictation` | `tap`);
  - `assumed`: the confirmed assumed sentences;
  - `removed`: assumed sentences removed with ×;
  - `dropped`: items judged open but capped.

  It replaces `included_chips` and `declined_chips`.

## 7. What Generate receives

The findings block (v2 §6 shape), answers only:

```
Pelvic organs: A 5 cm simple-appearing right ovarian cyst. No features of torsion. Both ovaries enhance symmetrically.
  Assumed normal (confirmed by the radiologist): Left ovary and uterus normal.
Peritoneum: Small volume of free fluid in the pelvis.
  Assumed normal (confirmed by the radiologist): No free gas. No pelvic collection.
Appendix (answered by the radiologist): The appendix is normal.
Assumed normal (confirmed by the radiologist): pancreas, spleen, bowel, vessels and nodes, bones.
Conclusion (confirmed by the radiologist): …
DO NOT ASSERT: <removed sentences>
```

- Tapped answers are written as answered by the radiologist.
- The generator prompts are unchanged: fluent phrasing, no new claims (v2 decision).
- In stack sessions the brief runs on the slim sheet (§8): structure, style, measurements, terminology, the
  confirmed conclusion. **It no longer has a negatives stage:**
  - no mandatory negatives;
  - no If-present negatives;
  - no `_fallback`;
  - no finding-linked or implicated options.

  The checklist is the negatives stage.
- The post-generation check runs unchanged against the findings block.

## 8. The slim skill sheet

A new, separate analyser output for stack sessions. Today's analyser and its sheet stay for the non-stack path and
the shadow comparison, untouched (memory: today's prompt exists twice; neither copy changes).

### 8.1 Content

Structure and style only. No clinical knowledge about findings. Built from today's sections:

| Section | Kept, changed or new | Used by |
|---|---|---|
| **Scan Context** | Kept: modality, imaged volume, contrast, phase. Its "Modality non-assessables" becomes **Not assessable on this scan**. | Finding-item writer (modality rule); generator |
| **Structural Pattern** | Kept: sections, sweep order, macro-structure | Generator |
| **Region normals** | **New.** For each region in the scan family's schema (names passed in): 1–6 assumed sentences in final report form, one structure each, no measurements. Replaces the Normal-study path prose for stack sessions. | Survey items, quiet lines, tray, generator |
| **Style Exemplars** | Kept; normal-study exemplars dropped (the region normals cover them) | Generator |
| **Terminology Rules** | Kept | Generator |
| **Measurement Conventions** | Kept | Generator |
| **Impression conventions** | Kept: opening convention, descriptor propagation. Dropped: exemplars carrying negative lists. | Generator (phrasing the confirmed conclusion) |
| **Recommendation scope** | Kept | Options after Generate |
| Clinical Lane, Companion Matrix (in-scope companions, mandatory negatives, If present, out-of-scope suppressed), Conditional Suppression Rules, Interpretive Clause Rules | **Removed** | Replaced by referral items, finding items and the judge |

### 8.2 Keying, cost, timing

- The slim sheet depends on the **scan type only** (and the family's region list). Clinical history moves to the
  referral items (§4.1).
- Cached by scan key across cases and users, so speed doesn't matter: a slower, stronger model is acceptable (the
  goal from the v2 session). The first case of a new scan type waits on it; the scratchpad still works meanwhile:
  - quiet lines fall back to finding-item sentences only;
  - the tray works without sentences;
  - Generate falls back to v2's `stack_fallback` on today's sheet.
- Versioned like today's analyser (`analyser_prompt_version`) and stored in the ephemeral sheet table with a
  `variant` marking it slim.

### 8.3 Template path

Template sheets are already structural: paragraph grammar with per-paragraph NEGATIVE lines.

- Regions are the template's paragraphs (v2, unchanged).
- Region normals are the paragraph's NEGATIVE and normal lines, parsed with `template_sheet_structure`.
  - A line with a condition on a finding ("if X reported") is a finding-linked sentence. It becomes a candidate
    item for the judge, never assumed by default.
- Referral and finding items: same calls as quick.
- No new sheet is generated for templates. The slim-sheet work is quick-path only.

## 9. Retirements (stack sessions only; the non-stack path is unchanged)

- `hybrid_stack/chips.py`, `/api/hybrid-stack/chips`, `CHIP_FORM`, chip states.
  - The Jev `ask_checks` pair survives only if J1 or J3 wins.
- Voice "accept suggestion" becomes "answer the question" (same Jev command, target_chip → target_item).
- The brief's stack-mode negatives handling (`stack_offers`, finding-linked offering) and `_fallback` use.
- The generic chip prompt reuse of `report_reconcile._fallback`.

## 10. Labs (before building)

All on the chip-lab harness (move `chiplab/` into `scripts/hybrid_stack_eval/checklist_lab.py`, fixtures into
`tests/fixtures/hybrid_stack/checklist_cases.json`). Blind gold, Sonnet 5.5 judge plus a hand read of every leak.

**Cases:** the 16 existing, plus 4 new: 2 more where the finding implies something (the leak type), 2 with no
question in the history (staging, follow-up). One run per arm (eval economy); a second only for a close call.

| Arm | What |
|---|---|
| **D** | Baseline, as run in §10.1 |
| **D1** | D with the `implied` field and `answers` (§4.2 schema) |
| **D1+J1 / D1+J2 / D1+J3** | The judge candidates (§5.1) applied to D1's items |
| **D1-ref** | D1 without the referral line, plus the setup referral call (§4.1) |
| **S** | Today's production path: generate today's sheet for each case, compile the brief, take what it states and offers. This is the direct sheet comparison. |

**Metrics:**
- **Recall:** must-haves present as assumed or open items.
- **Leaks:** wrong assumed sentences (the judge's "wrong", hand-checked). This is the number that matters most.
- **Friction:** open questions per case (median and max).
- **Speed:** finding-item latency (p50); referral-call latency.

**Gates to build:**
- recall ≥ S on must-haves;
- leaks ≤ 1 across all cases;
- friction median ≤ 2, max ≤ 4;
- finding items p50 ≤ 1.5 s.

If S beats every D arm on recall, the slim sheet keeps a referral checklist section written by the analyser, and
§4.1's call is not built.

### 10.1 Results so far (chip lab, 2026-10-11)

16 cases (5 where the referral question points away from the finding), 37 must-haves, Sonnet judge:

| Arm | Must-haves | Wrong | Low value |
|---|---|---|---|
| A: shipped chips | 22 (59%) | 2 | 5 |
| B: whole case | 23 (62%) | 3 | 3 |
| C: B + question card | 22 (59%) | 3 | 10 |
| D: B + referral line | 29 (78%) | 8 | 2 |

D's wrong chips:
- 4 deny or limit what the finding implies;
- 1 is not assessable on the scan;
- 2 extend a dictated finding into areas nobody commented on;
- 1 is redundant.

Under this model, the first and third types become open questions or are dropped. The second is the modality rule.

## 11. Rollout

- Unchanged from v2: default-on for stack sessions, kill switch `RR_HYBRID_STACK=0`, opt-out
  `localStorage rr_hybrid_stack=0`, the old path in shadow.
- The slim sheet is generated alongside today's analyser at setup, so the shadow comparison keeps both.

## 12. Decisions

Settled in conversation:
- The checklist model, the three states, referral items always open unless answered.
- The UI order and wording in §3 (playback mock-up v2).
- A new slim sheet for this flow (§8).

Defaults taken here (say if any is wrong):
1. Friction cap of 2 open finding questions per region; anything else judged open is dropped, never assumed (§5.2).
2. The slim sheet is quick-path only; templates reuse their own structural sheets (§8.3).
3. A slower, stronger model for the slim sheet, since it is cached by scan type (model chosen in the lab).
4. Tapped answers are attributed to the radiologist in the findings block and gate record.
