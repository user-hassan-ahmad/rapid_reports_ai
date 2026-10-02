# Lab: Qwen authors Jev questions to reach its judgement

**Date:** 2026-10-02 · **Branch:** `feat/review-rail` · **Status:** draft for Hassan's review
**Runs before:** the review engine spec (`2026-10-02-review-engine-and-rail-design.md`), which is paused until this lab reports.

## 1. Question

Can Qwen hand the *reading* part of a judgement to Jev, much as an agent calls a tool? Jev would be the System 1, Qwen the System 2. Qwen breaks a judgement into narrow questions about what the text states, Jev answers them, and the decision follows from the answers.

If that works, it should:
- **cut latency and cost,** because reasoning is 93–95% of Qwen's generation time (memory `project_qwen_migration`);
- **make the outcome deterministic,** because typed answers plus a fixed decision rule give the same result every time, with an audit trail;
- **raise accuracy** on stated-text facts Qwen misreads. In round 2 it missed a right-then-left section structure and attached "irregular margins" to the liver contour instead of the lesions.

**Prior evidence:**
- Our Jev research covers only the reverse: Jev gating an LLM's tool calls (field research P-07, P-17).
- The one precedent is the 2026-09-30 probe spike. Qwen, with reasoning off, wrote section-scoped coverage questions; Jev caught 42 of 44 resolutions with 1 false hit. That worked because the question **form was constrained**.

This lab tests whether the same constraint generalises.

## 2. The central constraint: Qwen writes only inside Jev's proven question types

Wording decides Jev's accuracy:
- production wording scored 0.83 against 0.99 for the criteria form;
- neutral "Statement: X" questions came out inverted (AUC 0.003);
- unquoted items were answered about the whole dictation.

Qwen would repeat every one of those mistakes if it wrote freely. So it does not write questions. It **picks a question type from a closed catalogue and fills its slots**, and code renders the Jev JSON from lab-proven wording.

### 2.1 The catalogue (what Jev is strong at)

Each type comes from a measured result in `reference_jev_capability_profile`, the wording suite or ledger L-46/L-49. Code owns the wording; Qwen supplies only the slots.

| ID | Type | Jev form | Slots Qwen fills | Rendered wording (code-owned; follows proven rules) | Evidence |
|---|---|---|---|---|---|
| **T1** | **Stated in source:** is this quoted item stated in a named text? | noul, true/false criteria | `item` (verbatim quote), `source` (dictation / report / history), `section?` | `Read only this one {kind}: "{item}". The {source} (or its {section} section) states this, in any wording (synonym, abbreviation, a more specific form, or spread over several sentences), including as a possibility; not merely implied.` + synonym legend | criteria form 0.99, quote rule (group F), "including as a possibility", "not merely implied" |
| **T2** | **Topic covered:** does a report section, or the dictation, say anything about a topic? | noul | `source` (report / dictation), `section` (report only), `topic` (general terms, no polarity) | report: `Does the {section} section of the report say whether there is {topic}?` · dictation: `The dictated findings themselves say something about this topic, whatever they say about it: {topic}` + true/false criteria | report form: probe spike 44/44, 1/392 false. **Dictation form is new: in the wording mini-check (§5, phase 1)** |
| **T3** | **Contradiction:** does the source contradict this quoted clause? | noul | `clause` (verbatim quote) | today's `Q_CONTRA` wording | 31/31 caught, 4/127 false (L-46) |
| **T4** | **Distinct choice:** which of 2–5 clearly different options holds for a quoted item? | choice; code appends the exit option `can't tell` | `item` (verbatim), `options` (each a short, mutually exclusive description) | `Read only this one {kind}: "{item}". Choose …` + options + exit | impression variant 5/5; classify-first 0 unsafe on 179 |
| **T5** | **Property of the quoted text itself:** a property of the quoted words only (e.g. "reports an abnormality", "is hedged", "names a side") | noul | `item` (verbatim), `property` (from a fixed list, starting with the one proven property, `abnormal`; more join only after a mini-check) | `The {kind} "{item}" itself {property}.` | selector noul AUC ≈ 1.0 (group F) |
| **T6** | **Same thing?** do two quoted spans refer to the same structure or finding? | noul | `a`, `b` (both verbatim) | `"{a}" and "{b}" describe the same structure or finding.` | **new: needs a wording mini-check (§5, phase 1)** |

**Forbidden question types** (where Jev is weak). Code rejects any slot set that drifts into them:

| Forbidden | Why | Where it goes instead |
|---|---|---|
| What imaging *would* show, what is *expected*, clinical knowledge (does this meet grade 3?) | no signal on inference (capability profile) | Qwen reasons it; Jev checks only that the *inputs* are stated |
| Choosing between overlapping or near-identical spans | 40% accuracy | T6 pairwise, or Qwen |
| A claim with an embedded negative ("There is no ascites" as the thing to verify) | polarity failures (42/392 false) | T2 topic + T3 contradiction |
| Numbers, dates, counting, comparing sizes | F-08: these stay in code | code checks |
| Extracting or writing text | F-15: Jev points, it can't extract | Qwen or code |
| Two judgements in one question ("X or Y", "X and also Y") | one judgement per question (F-06) | two questions |
| An unquoted reference to "this finding" against a whole text | answers about the whole text (group F) | quote the item |

### 2.2 Slot validation (code, test-first)

- **Quotes:** `item`, `clause`, `a` and `b` must be verbatim substrings of their named source, so the quote is real.
- **`topic`:** 1–6 words, no negation words, no digits.
- **`options`:** 2–5 entries, each ≤ 25 words. No option may be a negation of another. Code appends `can't tell`.
- **`property`:** must come from the fixed T5 list.
- **Count:** at most 8 questions per item.
- **Failures:** a question that fails validation is dropped and logged. If an item has no valid questions, it falls back to the baseline arm, and that counts against the arm.

### 2.3 The authoring prompt (draft, case-agnostic)

Qwen gets:
- the full case;
- the judgement to make (for example "is this classification gradable from what was dictated?");
- the catalogue as **the only question types it may use**, each with one structural example (not a clinical one);
- these rules:
  - ask about what a text **states**, never what imaging would show or what is likely;
  - quote exactly;
  - one judgement per question;
  - for coverage, ask about the **topic in general terms**, not about the claim or its wording;
  - leave numbers, dates and comparisons to code (say "code: compare X with Y", and the harness runs it);
  - ask the fewest questions that settle the judgement.

**Arm B only:** Qwen must also **declare the decision rule before seeing any answer**, as a small table over its questions. For example: `gradable = all(Q1..Q3 true)`; `missing = [inputs whose Q is false]`; any `can't tell` or middle-band answer → `unsure`.

## 3. Arms

| Arm | Flow | Qwen calls | What it isolates |
|---|---|---|---|
| **A, baseline** | Qwen, reasoning **on**, decides alone (adjudicator-style prompt) | 1 | the reference |
| **A0** | Qwen, reasoning **off**, decides alone | 1 | whether any gain in B is Jev's contribution or just "reasoning off" |
| **B, deterministic** | Qwen, reasoning **off**, picks templates, fills slots and declares the rule → Jev (one call) → **code** applies the rule. `unsure` → falls back to A for that item | 1 (+A on unsure items) | speed, cost and determinism |
| **C, tool round** | Qwen, reasoning **on**, plans templated questions → Jev → the same Qwen conversation continues and decides, treating the answers as evidence, not verdicts | 2 turns | accuracy lift from Jev evidence |
| **Cb, C-blank control** | C's own plan, but the decide turn sees every answer as "not asked" | 1 (reuses C's plan) | how much of C's gain comes from listing the inputs rather than from Jev's answers (added after code review, 2026-10-02) |
| **D, free-form** | as C, but Qwen writes its own Jev questions (no catalogue) | 2 turns | the cost of dropping the catalogue; measures the wording risk |

**Running rules:**
- C is run as two turns rather than native tool calling. The decide turn is a fresh call that sees the case, the questions and the answers, but not the plan's reasoning, so C's token count is slightly lower than a true continued conversation. The write-up notes this.
- Qwen is qwen-3.8-27b on Cerebras, through `normalise_model_settings`, with `max_tokens` + `extra_body` for reasoning settings (memory `reference_pydantic_ai_settings_shape`).
- Jev is pinned at jev-1.13.

## 4. Scenarios

Each scenario is one judgement with a label per item. Start with S1, and add the rest only if S1 is informative.

| # | Judgement | Why it suits the method | Label |
|---|---|---|---|
| **S1, pilot** | **Grade grounding:** given a finding and a classification system (from the guideline synthesis), is it gradable from what was dictated, and if not, which inputs are missing? | Qwen knows what inputs the system needs (System 2); whether each is stated is a pure T1 question (System 1); the decision is a rule | by construction for synthetic; Hassan for production |
| S2 | **Partial vs absorbed:** is a dictated detail lost, or absorbed by rewording? | the v3 recall failure lives here | Hassan's Gate A labels |
| S3 | **Contradiction vs compaction:** e.g. "remaining X unremarkable" after the abnormalities are described | T3 plus T6 on the abnormal structure | by construction + Hassan |
| S4 | **Unsupported finding:** is a positive report clause stated in the dictation? | L-46's weak spot (5/32, 49 false alarms) | fabrication cases + synthetic |
| S5 | **Laterality bounded:** is the side fixed by the title or a subheading? | T5 + T1 | by construction |

**S1 labelling rules (Hassan, 2026-10-02):** these are part of the shared judgement prompt, so every arm and every label uses them.
- **Scope:** grade means the system's **core category**. Optional modifiers and eligibility criteria are ignored unless they change that category.
- **Literal reading:** an input counts only if it is stated, never inferred from radiological convention. For example, an unqualified "nodule" is not assumed solid.

**Fixture design from the peer review (2026-10-02):**
- **Finding-scoped T2d items:** the wording check includes topics tied to one finding while a neighbour carries the same attribute. This is S1's nearest-finding trap, and Jev's known overlapping-span weakness.
- **Separate scoring:** T6 items whose side lives only in a line prefix are scored separately.
- **No ceiling:** the S1 set is hardened by category, blind to model results, so baseline A doesn't score at the ceiling.

## 5. Data and procedure

**Data:**
- Production cases are the base:
  - the 50 v3 cards and Hassan's labels;
  - the 41 audit-comparison reports;
  - stored `enhancement_json` synthesis for S1.
- Production data stays in the scratchpad (standing production-read permission).
- **Synthetic cases are seeded from production:** the same structure, varied across modalities and body regions so the lab stays case-agnostic, with the label fixed by construction (e.g. delete a dictated descriptor → partial).
- Synthetic fixtures may go to `backend/test_cases/`. Raw production text never does.
- **Balance:** every scenario has ≥ 10 items per class. A pilot starts at 20 items.
- **Stress sets:** each weakness found gets a targeted stress set seeded from the case that showed it.

**Phases:**
0. **Harness (code, test-first):**
   - `scripts/jev_tool_lab/catalogue.py`: templates, renderer and slot validator;
   - `run_lab.py`: arms, Jev batching, rule evaluator;
   - `score.py`.
   Unit tests cover rendering, every validation rule, the rule evaluator and fallback, with Jev and Qwen mocked.
1. **Wording mini-check** for the two new wordings, T2 on the dictation and T6, with ~20 balanced items each, 2 candidate wordings and 2 repeats. The rest reuse proven wordings.
2. **Pilot:** S1, 20 items, arms A, A0, B and C, 2 runs. D runs once, as a risk measure. The pilot is directional (§7.1). **Stop and read with Hassan.**
3. **Expand:** only on a pilot go (§7.1). S1 grows to ≥ 100 items for the adoption bars (§7.2). Then S2 and S4 (where the engine's recall and false-alarm pain is), then S3 and S5.

**Eval economy** (memory `feedback_eval_economy`): reuse outputs across arms where the inputs match (A's run feeds B's fallback), 2 runs maximum, pid in output filenames, data in the scratchpad.

## 6. Metrics

| Metric | Per arm and scenario |
|---|---|
| Accuracy | balanced accuracy, recall on the flag class, false-alarm rate, against labels |
| Speed | p50 and p90 end-to-end latency per item |
| Cost | Qwen input/output/reasoning tokens + Jev calls, in $ per 100 items |
| Stability | identical decisions across 2 runs (B should be near 100% when Qwen's question plan is stable) |
| Question quality | share of slot sets passing validation; questions per item; for D, share breaking a §2.1 rule (by lint plus a hand read of 20) |
| Routing | B: share of items going `unsure` → fallback. C: how often Qwen overrules Jev, and whether each overrule was right |
| Jev calibration | Brier and ECE per template on this data (field research D-03) |

## 7. Pass criteria (per scenario)

**Sample size decides which bars apply.** At 20 items each item is worth 5 points, so percentage bars like "within 2 points" can't be read from the pilot, and one item could flip a verdict. The pilot uses **counts on paired items**. The percentage bars apply only to the expansion run.

**Paired counts.** Every arm is compared with A item by item. Per run, against the label:
- **gains:** items the arm gets right and A gets wrong;
- **losses:** items A gets right and the arm gets wrong.

Latency, cost and stability are continuous or per-run measures, so they are readable at 20 items.

### 7.1 Pilot (20 items): go / no-go to expand

| Arm | Go if, in both runs… |
|---|---|
| **B** | losses ≤ 1, **and** p90 latency or cost ≤ 70% of A, **and** B's own run-to-run agreement ≥ A's |
| **C** | gains ≥ 3, with losses ≤ 1, **and** against Cb, gains > losses (so the lift is Jev's, not the enumeration's) |
| **D** | informative only |

The pilot also yields its main product: **a hand read, with Hassan, of every item where the arms disagree,** and why. A go means "expand to measure properly", not "adopt".

### 7.2 Expansion (≥ 100 items per scenario, balanced): adopt or not

At least 100 items per scenario, balanced, with production items as the seed and synthetic variants filling the classes.

| Arm | Adopted for that scenario's item kind in the review engine if… |
|---|---|
| **B** | balanced accuracy ≥ A − 2 points, **and** p90 latency or cost ≤ 70% of A, **and** stability ≥ A |
| **C** | balanced accuracy ≥ A + 5 points, or it fixes a named Qwen misread class (gains ≥ 5 in that class, losses ≤ 1 elsewhere), with p90 latency ≤ A + 1.5 s |
| **D** | informative only. If D ≈ C, the catalogue was not the lever (an unexpected result worth a note) |

**Rules for every decision:**
- **Significance:** gains and losses are reported with an exact McNemar test, as a guide, not a gate.
- **Credit to Jev:** A0 must be clearly below B (more losses against A than B has) for B's gain to be credited to Jev.
- **Negative result:** if neither B nor C passes, it goes in the ledger, and the engine keeps the single-call adjudicator.
- **Hand read:** Hassan reads the disagreements between arms before any adoption.

## 8. What happens with the result

The review engine spec resumes either way. The lab feeds it in three places:
- **The adjudicator (§7 of the engine spec):** a passing arm becomes the adjudication method for the item kinds it won, through the existing `evidence` hook. The interface doesn't change.
- **Additions grounding (§6.4):** if S1 passes in arm B, "never infer a grade from undictated features" becomes a deterministic check rather than a prompt rule.
- **The catalogue** becomes the standing reference for every new Jev question, whether Qwen writes it or we do. Its forbidden list is checked in code.

## 9. Risks

- **Qwen over-asks or asks the wrong question.** Mitigated by the 8-question cap, the validator, and measuring questions per item.
- **Jev drift between repeats** (up to 0.2). Bands are fixed with a wide margin, not tuned on the pilot.
- **Back-door veto.** In C, Qwen might simply defer to Jev. Measured by the overrule rate and how often overrules were right.
- **Rule rigidity in B.** Some judgements may not reduce to a rule. These should show up as a high `unsure` share, which is itself a finding.
- **Synthetic overfit.** Production cases anchor every scenario, and the stress sets come from production failures.

## 10. Cost

- **Jev:** negligible ($0.042/M input).
- **Qwen:** the pilot is about 20 items × (A, A0, B, C×2 turns) × 2 runs + D once ≈ 220 calls.
- **Full run:** each scenario at ≥ 100 items is about 5× the pilot, about 1,100 Qwen calls, if every scenario proceeds.

## Results: phase 1 (wording mini-check, 2026-10-02)

**Setup:** jev-1.13, 48 synthetic items (labels reviewed by Hassan), 2 wordings × 2 repeats, giving 192 answers with none missing. Bands fixed at 0.3 / 0.7.

| Group | Wording | n | AUC | Brier | ECE | Confident errors | Unsure | Max drift | Gap (min true − max false) |
|---|---|---|---|---|---|---|---|---|---|
| T2d main | **w1** | 20 | 1.00 | 0.004 | 0.042 | 0 | 0% | 0.03 | 0.76 |
| T2d main | w2 | 20 | 1.00 | 0.008 | 0.067 | 0 | 0% | 0.01 | 0.81 |
| T2d finding-scoped | **w1** | 8 | 1.00 | 0.007 | 0.065 | 0 | 0% | 0.01 | 0.80 |
| T2d finding-scoped | w2 | 8 | 1.00 | 0.016 | 0.099 | 0 | 0% | 0.01 | 0.75 |
| T6 main | w1 | 18 | 1.00 | 0.003 | 0.034 | 0 | 0% | 0.03 | 0.71 |
| T6 main | **w2** | 18 | 1.00 | 0.002 | 0.035 | 0 | 0% | 0.04 | 0.76 |
| T6 context-side | w1 / w2 | 2 | n/a | 0.001 / 0.001 | | 0 | 0% | 0.00 | |

**Chosen:** T2d **w1**, T6 **w2** (lower Brier; w2's weakest true T6 is 0.93 against w1's 0.78). `DEFAULT_WORDING` is updated to match.

**Closest calls,** all correct:
- t2d-09, hilar vs mediastinal nodes (0.19–0.22);
- t2d-27, density of an unqualified nodule (0.15);
- t6-17 under w1 (0.78–0.81).

**Reading:**
- Both new wordings pass with wide margins, including the finding-scoped trap items. Topic coverage tied to one finding (with a neighbour carrying the attribute) did **not** show the overlapping-span weakness on these items.
- **Caveat 1:** the items are synthetic and cleanly written. The margins on real dictations will be narrower, and the S1 pilot's arm B is where that shows.
- **Caveat 2:** with no unsure answers and no errors, this run can't test calibration or the escalation band. That needs harder or real items (field research D-03 is still open).

**Side effect:** with T6 on w2, the free-form lint flagged its "these two quoted texts" as a number word. The calibration test caught it, and the lint now ignores that meta-phrase but still flags counts (e.g. "two septa").

## Pilot smoke-test changes (2026-10-02, before the pilot run)

- **Flat plan rule.** Qwen JSON-encoded the nested `rule: {all_of: [...]}` object as a string in every B/C/D plan, and the temperature-0 retries were identical, so all planning calls failed. A flat `rule: [conditions]` validated 9/9 live calls (reasoning on and off, and D). Same lesson as before: nested structured-output failures are schema-shape problems.
- **Topic cap raised from 6 to 8 words.** The 6-word cap (an unmeasured choice) rejected good topics that name their finding, e.g. "focal echogenic foci of right upper pole nodule". **Caveat:** the Jev wording check covered topics of up to 6 words only.

## Results: phase 2 (S1 pilot, 2026-10-02): directional, pending Hassan's read

**Setup:** 20 items, 2 runs (D once), 220 results, 5 errors.

| | A | A0 | B | C | Cb | D |
|---|---|---|---|---|---|---|
| Balanced accuracy | 0.80 | 0.85 | 0.83 | 0.97 | 0.95 | 0.80 |
| Gains / losses vs A, run 1 · run 2 | n/a | 2/1 · 2/1 | 2/1 · 2/1 | 3/0 · 4/0 | 4/1 · 4/1 | 1/1 |
| Stability | 1.00 | 1.00 | 1.00 | 0.95 | 1.00 | n/a |
| p50 latency | 1.05 s | 0.39 s | 0.72 s | 4.5 s | 3.6 s | 3.0 s |
| Tokens vs A | n/a | 0.42× | 1.30× | 4.07× | 3.86× | 2.85× |

**§7.1 verdicts:**
- **B: no-go.** Losses ≤ 1 passes, but cost fails: p90 latency is 1.26× A and tokens 1.30× A, against a bar of ≤ 0.7×.
- **C: no-go on credit to Jev.** It gained over A in both runs (3/0 and 4/0), but against Cb it was 1/1 in run 1 and 1/0 in run 2. The bar requires gains > losses in both runs.

**Main findings:**
1. **Listing the inputs is the lever, not Jev.** A and A0 fail both production-style overcall traps (s1-08 CAD-RADS with only the RCA described, s1-13 O-RADS where the colour score belongs to the neighbouring cyst) in both runs. Every arm that first plans the system's inputs (B, C, Cb) gets both right.
2. **C and Cb differ only on s1-01 and s1-18,** and both of those labels are now disputed (see below).
3. **B's errors are plan-knowledge errors made with reasoning off,** which Jev and the rule then carry out faithfully. B asked about lung-cancer risk for a subsolid Fleischner nodule, and about age and sex for CAC-DRS. Jev answered both correctly.
4. **Reasoning didn't help one-shot judging:** A0 (0.85) ≥ A (0.80), at a third of the latency.

**Label disputes the models raised** (Hassan to rule):
- **s1-01:** "echogenicity lower than surrounding thyroid" doesn't literally exclude very hypoechoic (less than the strap muscles).
- **s1-18:** segmental-vessel involvement is unstated, and that decides AAST III vs IV.

**Caveats:**
- **C's latency is unreliable:** four C calls took about 64 s, probably provider queueing or rate limiting at 4 concurrent calls.
- **B plan failures:** 2 of 20 B plans failed because Qwen (reasoning off) JSON-encoded the `questions` array as a string. That is the same class as the rule-object failure.
- **Sample size:** n = 20 synthetic items, so all of this is directional.
