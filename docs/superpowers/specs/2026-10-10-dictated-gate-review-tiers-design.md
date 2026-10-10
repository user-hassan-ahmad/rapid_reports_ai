# Dictated gate and review tiers

**Date:** 2026-10-10 · **Status:** design agreed, plan not written · **Path:** quick report (templated follows the same engine, §8)
**Follows:** negatives one owner (PR #16, L-59), live audits r1–r5, labs `gate_a`, `confirm`, `confirm2`, `sorter`, `amber`, `amber_fix` (scratchpad)

## 1. Problem

The review rail tints AI-written text so the radiologist can see it. Plain text is supposed to mean "you dictated this". Three rounds of live audits found the same failure each time: **AI text left plain, so it reads as dictated.**

Five components each decide "is this span dictated?", each with its own signal and its own leak:

| Component | Signal | Leak seen live |
|---|---|---|
| `provenance.build_items` skip chain | Jev W1n `sup ≥ 0.5`, alignment pair score, normal/negation lexicon | added descriptors inside a supported clause ("crescentic", "traumatic") |
| `provenance.confirm` / `synthesis_items` | Jev stated/synonym/not_stated on word runs, only for adjudicator-suppressed clauses | anything the adjudicator did not suppress |
| `provenance._rec_dictated` + `confirm` rec drop | pair score, word overlap, Jev Q3 | an impression recommendation clause with no item at all |
| `negatives` classifier `dictated` class | Qwen label | "liver normal echotexture" taken to dictate "no focal lesion"; "without RV strain" inferred from a dictated ratio |
| Brief full labels `dictated` | Qwen label before generation | "left ovary normal" taken to dictate "no contralateral adnexal mass" |

The system also tints only what it **positively** identifies as an addition, so every miss is a plain-text leak. That is the dangerous direction: a wrong tint costs a glance; a missing tint hides AI text.

A second problem appeared once detection was fixed in the lab: **tinting all AI text is noise.** About 80% of clauses in a generated report contain AI text. The radiologist needs the additions that change meaning, not every assumed normal.

## 2. Rule

1. **One owner for "is it dictated?":** a single Jev question per clause, asked against the raw dictation (not the brief or any internal artefact). Default is *added*: a clause is dictated only when Jev confirms every detail.
2. **Detection and display are separate decisions.** The gate finds additions; a tier rule decides which ones are highlighted.
3. **Highlight only what needs review** (Hassan, 2026-10-10):
   - **Review tier (always visible):** a detail added inside a dictated sentence (descriptor, inference, certainty, side), an added diagnosis or interpretation, an added recommendation. Plus the existing amber "bears on your finding" negatives and conflict cards.
   - **Quiet tier (behind the AI toggle):** added routine normals and negatives, including a negative bolted onto a dictated sentence ("liver normal echotexture *with no focal lesion*").
   - **Plain:** dictated.

## 3. Lab evidence (scratchpad `labs/gate_a/`, Jev 1.13, 2 runs per arm)

24 prod reports (17 dictations; 7 generated twice), 359 FINDINGS/IMPRESSION clauses, peer-read gold.

| | AI text left plain | Dictated clauses tinted |
|---|---|---|
| Live system (any item anchor ≥ 50% of the clause) | 54 | 0 |
| **Gate Q3s @ 0.7** | **3–4** | **6 / 75** |
| Lexical diff alone | 2 | 23 / 75 |

- Fresh-case confirmation (N1–N5, M1–M5) ran with arms frozen and gold written before any Jev call. The margin held on N; on M three entailed negatives ("seminal vesicles normal" restated as "no seminal vesicle invasion") scored 0.40–0.53. They are tinted (false tint, harmless in the quiet tier, §4.2).
- **Sorter** (gate, then production `q_type`, then the negation rule in §4.2): 70 gold review items. End-to-end recall 64–65/70, precision 0.97, mean 2.75 highlighted items per report (max 4). The live system left 41 of the 70 plain.
- **Visible share:** added words only ≈ 14% of report text (whole clauses would be 27.5%); with today's amber and cards ≈ 26% (max 44%).
- **Known misses:** definitional descriptors scoring ≥ 0.7 ("intraluminal", "ischaemic", a phase descriptor); one clinically meaningful ("fluid" → "fluid *collection*"). Inferences worded as normals ("CBD not dilated" from a dictated calibre) go quiet by the type rule.
- **Rejected:** the lexical diff as a gate or backstop (synonyms tinted; a hand-grown synonym list overfitted and opened a blind spot); the stated/synonym question (blind to added descriptors); a tighter classifier prompt for amber (precision 0.53 → 0.55, lost 4 good items).

## 4. Design

### 4.1 The gate

New module `review_engine/dictated_gate.py`.

- **Clauses:** the Jev pass clauses (`report_review.checked_clauses_in_context`: FINDINGS + IMPRESSION on quick reports). Using the same clause list keeps the gate and `q_type` aligned by index, and `q_type` comes free from the existing `omit` request (`typ{i}`).
- **State:** scan type; clinical history, labelled as context and *not* dictated findings; the dictated findings verbatim.
- **Question** (frozen lab wording, `Q3s`), one key per clause, batched 4 clauses per request, at most 8 requests in flight:
  > The report says: "{clause}". Compare every detail in it with the dictated findings: each finding, structure, side, level, size, descriptor, negated item, diagnosis, cause and recommendation.
  >
  > - **all_stated:** Every detail in the statement is stated in the dictated findings, in the same or other words (synonym, abbreviation, expansion or reordering).
  > - **some_details_added:** The dictation states part of it, but the statement adds at least one detail the dictation does not state: a descriptor, an extra negated item, a diagnosis, a cause or an inference.
  > - **not_stated:** The dictation does not state it; it was added by the report writer.
- **Verdict:** dictated iff P(all_stated) ≥ `GATE_MIN = 0.7`. Anything else counts as added.
- **Placement:** a fourth request inside `jev_pass`'s `asyncio.gather`, under the same 6 s `wait_for`. Wall-clock cost is about zero (lab median 0.29 s per call; about 4 calls per report).

### 4.2 Tier rule

For each clause the gate calls added:

1. `q_type == "normal"` → **quiet**.
2. Else, if `q_type` is `abnormal` or `mixed` and every content word new to the dictation follows a negator (no / without / nor / not) in the clause → **quiet**. This is a bolted-on negative on a dictated finding. The type condition keeps negated recommendations ("no urgent referral is indicated", typed `not_a_finding`) out of this rule.
3. Else, if `provenance.is_recommendation(clause, q_type, section)` → **review: recommendation item** (inline marker plus section checkbox, unchanged, §5).
4. Else → **review: synthesis item** (`ai_generated`, form `synthesis`) on the added words (§4.3).

Rules 2–4 are code over the gate's verdict and the validated `q_type`. They decide display, never provenance, so their failures misplace a tint rather than hide AI text. The exception is rule 2 sending a review item to quiet; in the lab it lost none (v1 vs v2 recall equal).

### 4.3 Word-level span

`added_runs(clause, dictation)`: contiguous runs of content words absent from the dictation. It uses light lemmatising (plural, -ed, -ing), a stopword list, number and unit normalising, and a fixed abbreviation map (lobe codes and common acronyms). It reuses `provenance._proposed_runs` where possible.

- The runs are the anchors of the synthesis item. One item per clause; extra runs go in `also_anchors`. The frontend paints only the primary anchor today (§5), so the item anchor is the first run and §5 adds painting of `also_anchors`.
- **No runs found** (an addition built only from dictated words, such as a changed relation) → the whole clause is the anchor.
- This step only places a highlight inside a clause the gate already marked. It never decides provenance, so a gap here costs highlight precision, not a leak. **No synonym list is added**; that is the overfitting the lab rejected.

### 4.4 What the gate replaces

Behind `RR_DICTATED_GATE=live` (§7), the gate is the only source of "dictated":

| Today | With the gate |
|---|---|
| `provenance.build_items` skip chain (W1n sup, pair score, lexicon normal) | gate verdict; skip chain deleted at stage 3 |
| `provenance.confirm` / `synthesis_items` / `_proposed_runs` on suppressed items | replaced by §4.2 rule 4 + §4.3 |
| `_rec_dictated` and the confirm rec drop | gate verdict on the recommendation clause |
| Negatives classifier `dictated` suppressing an item | gate decides. Classifier `dictated` + gate added → quiet item (`assumed_normal`, form `normal`). The classifier keeps `default` / `implicated` / `contradicted` |
| Brief full-label `dictated` suppressing an item | gate decides the same way. Brief anchors still own selection, amber for finding-linked negatives, conflict cards and the removal veto |

**Unchanged:** contradiction checks and removals (L-46/47, L-59 removal guard), conflict and measurement cards, accuracy-lane cards from the adjudicator (only its `suppress` outcome stops feeding provenance), amber salience.

If the gate calls a clause **dictated**, any quiet or amber AI-layer item on that clause is dropped: it is the radiologist's own text. Conflict cards stay.

### 4.5 Amber hygiene (two code fixes)

- An amber item with an empty pointer becomes quiet (form `normal`); it has no finding to bear on. Lab: 2.4 → 2.0 amber items per report, with 1 of 30 good items lost.
- Amber items on the same clause collapse to one.

Amber precision itself (about half, by a strict reader; Hassan's boundary counts close differentials as bearing) belongs to spec 2, linked prose for negatives.

## 5. Frontend

- **Synthesis (violet) becomes always visible**, like amber: move `.rv-form-synthesis` out of the `[data-rv-emph~="ai"]` scope in `theme.ts`. The AI toggle then shows only the quiet tier (green).
- **Recommendations:** no change. They keep the teal underline in the text plus a checkbox in the section's "Recommendations & suggestions" block (`decorations.ts`, `commands.ts`). The gate only changes which recommendations get an item. They stay in `EDITOR_ONLY` so the rail does not duplicate them.
- **`also_anchors`:** paint every anchor of an item, not just the primary one (`field.ts` mark builder).
- **Legend copy** (`decorations.ts` `AI_BREAKDOWN`):
  - violet "Added by the AI: check it";
  - green "Assumed normal (shown with AI toggle)";
  - amber unchanged.

## 6. Failure handling

- **Gate request fails or times out:**
  - stages 1–2: the old provenance path runs for that report;
  - stage 3: one retry, then the run records `dictated_gate.failed` and the rail shows one line: "AI additions could not be marked on this report."
- **A clause cannot be located in the report text:** no item, logged as `unplaced`.
- **The gate never edits or removes text.**

## 7. Rollout

`RR_DICTATED_GATE` = `off` | `shadow` | `live`. The default is `shadow` once merged.

1. **Shadow:** the gate runs and logs; items and display are unchanged. The shadow log gets key `dictated_gate`, with per clause:
   - clause index, section;
   - `p_all_stated`, `q_type`;
   - verdict, tier;
   - added runs;
   - which old component tinted it.

   Persist the existing `run["provenance"]` log in the same dict; today it is never copied.
2. **Live:** gate items and tiers replace §4.4's decisions; the old code stays as the failure fallback.
3. **Cleanup:** delete the replaced code once live has run cleanly (§9).

## 8. Templated path

The engine is pathway-agnostic. Templated reports use the same gate over `checked_clauses_in_context`'s templated sections. No templated-specific work is planned; parity follows the review rail switch-on for templates.

## 9. Success criteria

Measured on a shadow replay of the 24 lab reports through the repo code, plus 5 fresh prod reports:

- review-tier recall ≥ 90% end to end; precision ≥ 0.9;
- ≤ 4 review highlights per report on average; highlighted words ≤ 20% of report text;
- dictated clauses wrongly in the review tier ≤ 1 per 10 reports;
- review run p50 latency grows by ≤ 1 s;
- 0 changes to removals and contradiction cards versus the current engine on the same inputs.

**Live → cleanup:** hand-read of ≥ 10 live reports with no review-tier leak of a meaningful addition.

## 10. Tests

- Unit tests:
  - the tier rule (each branch);
  - `added_runs` (lemmas, numbers, abbreviations, no-run fallback);
  - gate verdict parsing and threshold;
  - fallback on failure.
- Gate/classifier/brief disagreement: gate added + classifier dictated → quiet item; gate dictated → AI-layer items dropped, cards kept.
- Fixtures are synthetic, written for the tests. Prod report text stays in the scratchpad.
- Replay script `scripts/review_labs/dictated_gate_replay.py` reads a local dump directory, so the §9 replay runs without prod text in the repo.

## 11. Out of scope

- **Linked prose for negatives** (spec 2): amber becomes "the brief chose it for a finding", which may retire classifier `implicated`.
- **Inferences from dictated numbers worded as normals.**
- **Definitional descriptors below the gate's resolution.** Watch "collection"-type escalations on the dashboard.
- **Recommendation urgency check** (U3c, lab-ready).
- **Embellishment re-lab** (E1n).
- **Generation-side changes:** no embellishment, recommendations only with a dictated trigger.

## 12. Ledger

Next free ledger ID (L-60 onward, after the PR #12–#15 backfill), recording:
- `GATE_MIN` 0.7;
- the frozen Q3s wording;
- tier rule v2;
- the lab files.
