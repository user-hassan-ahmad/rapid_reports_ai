# Qwen Sheet-Budget Experiment — Results

- **Date:** 2026-08-12
- **Spec:** `2026-08-12-qwen-sheet-budget-experiment-design.md`
- **Plan:** `../plans/2026-08-12-qwen-sheet-budget-harness.md`
- **Artifact:** https://claude.ai/code/artifact/6abab95e-d911-4a0c-a927-d06ea26f2c56
- **Raw:** `backend/test_output/FULL_budget/` (gitignored — regenerate with
  `poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner`)

25 runs, 5 tiers × 5 cases, matched Qwen 3.6 27B analyser → generator, rubric v2.2 Sonnet judge. 0 errors.

---

## 1. Results against the spec's stated expectations

The spec recorded four predictions in §9 so the data could contradict them. Three did.

| # | Prediction | Outcome |
|---|---|---|
| 1 | Breadth cuts near-free; cliff at **T4** where variants drop 3→2 | **Contradicted.** No cliff anywhere. T4 scored 4.95, the joint-highest tier. |
| 2 | Generator reasoning falls **faster** than sheet size (superlinear) | **Contradicted.** Sheet −31%, generation time only −20%. Sub-linear. |
| 3 | `dictation_fidelity` and `normal_fill_appropriateness` degrade first | **Contradicted.** Both held at 5.00 on every tier. The only movement was in `output_adherence` and `unwarranted_assertion`, and it was noise-scale. |
| 4 | T5 fails the gate on a broad-coverage case (`ct_tap`) | **Confirmed**, but for the wrong reason — truncation, not loss of the sweep template. |

## 2. Confirmed: structural budgets are honoured exactly

**125 of 125 budgeted fields hit, across every tier and case.** Zero misses. Counting findings, variants, exemplars, clauses and negatives is a reliable control surface for this model — the abort gate in the plan (switch to hard section ablation if T2 missed) was never needed.

This also validates the mechanism choice over a word/token budget: compliance was *measurable*, not assumed.

## 3. Quality is flat across the whole ladder

| Tier | Budget | Sheet | Mean | adherence | fidelity | normal-fill | unwarranted | n |
|---|---|---|---|---|---|---|---|---|
| T1 control | unconstrained | 13,197 | 4.75 | 4.50 | 5.00 | 4.75 | 4.75 | 4 |
| T2 breadth | 4 × 3 | 12,596 | 4.90 | 4.80 | 5.00 | 5.00 | 4.80 | 5 |
| T3 breadth | 3 × 3 | 11,743 | 4.95 | 5.00 | 5.00 | 5.00 | 4.80 | 5 |
| T4 depth | 3 × 2 | 10,951 | 4.95 | 4.80 | 5.00 | 5.00 | 5.00 | 5 |
| T5 depth+scaffold | 2 × 1 | 9,145 | 4.83 | 4.67 | 5.00 | 5.00 | 4.67 | 3 |

Total spread is 0.20 on a 5-point scale, well inside what n=5 can resolve. **A much thinner sheet is clinically safe**: across 22 completed reports there was no self-contradiction, no thinking leak, and no measurable quality loss down to 2 findings × 1 variant.

The spec's reasoning for expecting a sharp cliff — that the prompt calls exemplars "load-bearing" and the prose "decorative" — did not hold at these budgets. Either the generator needs fewer worked examples than the prompt assumes, or the unbudgeted prose carries more than the prompt credits it with.

## 4. The sheet did not shrink enough to matter

| | T1 | T5 | Δ |
|---|---|---|---|
| Sheet chars | 13,197 | 9,145 | −31% |
| Analyser | 23.6s | 16.8s | −29% |
| **Generate** | **16.9s** | **13.5s** | **−20%** |

T5 is an aggressive budget yet cut the sheet by under a third, because the budgeted sections are a minority of its mass. Scope declaration, clinical lane, structural pattern, companion matrix, terminology, measurement conventions and suppression rules are all unbudgeted and together dominate.

Rescaled to the 100–130 tok/s self-hosted band, T5 generation is ~47–61s against ~59–76s for the control. **Sheet budget is not the latency lever.**

## 5. Unplanned finding: intermittent truncation (12%)

Three of 25 reports stopped mid-sentence inside FINDINGS, before reaching IMPRESSION — one at T1, two at T5. Caught by the structural gate, not the judge.

| Run | Report | Cut at |
|---|---|---|
| T1 · ct_ap_lymphoma_aspergillosis | 1,561 ch | "…mural oedema with free fluid tracking along the mesenter" |
| T5 · ct_tap_acute_abdomen_gda_bleed | 1,410 ch | "…transverse diameter, increased from 3.8 cm on the prior" |
| T5 · ct_thorax_smoker_lung_nodule | 656 ch | "…malignant pleural involvement. The heart and great vessels" |

**Hypothesis tested and rejected.** A token ceiling was the obvious explanation, since `max_tokens: 8000` demonstrably is not reaching Groq (an earlier instrumented call on this path recorded 15,529 output tokens). But re-running the worst failure produced a complete report at **6,105 output tokens — 37% of the model's 16,384 ceiling**.

So two separate facts hold: the configured cap is not applied, *and* something intermittent truncates generations. The second is unexplained and not tier-related.

## 6. Recommended next steps, in order

1. **Chase the truncation.** A 12% rate of reports silently ending before the impression is a clinical-safety issue independent of model or host. Start by capturing `finish_reason` per generation — the runner does not record it today.
2. **Run the deferred parameter experiment.** `reasoning_effort: none` (Groq supports it for this model as a binary) and moving the reasoning scaffolds out of the generator prompt. On this evidence they matter far more than sheet size. Also fix `max_tokens` → `max_completion_tokens` and bring `temperature` from 0.8 into Groq's recommended 0.5–0.7.
3. **If sheet size is cut, cut it for cost or context, not speed** — and go after the unbudgeted prose sections, since the budgeted ones are already exhausted.

## 7. Limitations

- **n=5 per tier, one seed, no repeats.** The flatness claim is sound; the tier ranking inside it is not.
- **T5's mean rests on 3 runs**, its two hardest cases having been excluded by the gate. That biases T5 upward — its score is *better* than the tier deserves, which strengthens rather than weakens the "no cliff" reading, but should not be read as T5 being safe.
- **Sheet tokens are estimated** at 4 chars/token, not measured.
- **Self-hosted latency is a linear rescale** from Groq's measured rate, assuming reasoning volume is unchanged on different hardware. A floor, not a forecast.
- **Groq's Qwen 3.6 27B is a preview model** — "may be discontinued at short notice". Token counts and quality scores transfer to another host; wall-clock latencies do not.
