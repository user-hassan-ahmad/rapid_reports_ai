# Qwen 3.6 27B — Skill-Sheet Token Budget vs Report Quality

- **Date:** 2026-08-12
- **Status:** Draft for review
- **Scope:** Backend, test-harness only (`backend/src/rapid_reports_ai/scripts/`, `backend/test_cases/`, additive prompt in `backend/src/rapid_reports_ai/quick_report_analyser.py`)
- **Related memory:** `project_analyser_dual_variant`, `project_quality_rubric_v21`, `project_report_integrity_hardening`, `feedback_case_agnostic_prompts`, `feedback_dev_route_guard`

---

## 1. Problem

Cerebras retires its public Developer Tier on **2026-08-17**. That removes `zai-glm-4.7`, `gpt-oss-120b`, and `gemma-4-31b` — roughly 27 role assignments in `MODEL_CONFIG` (`enhancement_utils.py:146`). Qwen 3.6 27B is the leading dense replacement for the two workflows that matter most here: ephemeral skill-sheet generation and skill-sheet-guided report generation.

A bake-off run on 2026-08-12 (5 cases, 2×2 analyser × generator matrix, artefacts in `backend/test_output/BAKEOFF_qwen_vs_glm/` and `BACKFILL_glmA_qwenG/`) established that Qwen is clinically competent on these paths. It also established the blocker:

**Reasoning tokens are 93–95% of every generation.**

| case | visible tokens | reasoning tokens | total out |
|---|---|---|---|
| `ct_thorax_smoker_lung_nodule` | ~343 | ~4,671 | 5,014 |
| `ct_ap_lymphoma_aspergillosis` | ~751 | ~14,778 | 15,529 |

On Groq (~450 tok/s measured) this is tolerable: 11.4s and 33.5s. The intended deployment target is a **privately hosted GPU node at 100–130 tok/s decode**, where the same generations cost **44s and 135s**. The report itself costs 3–7 seconds; the thinking costs 40–130.

Reasoning volume scales **superlinearly with input size**: 2.1× the input tokens (9,770 → 20,696) produced 3.2× the reasoning (4,671 → 14,778). The skill sheet is the dominant input. Therefore sheet size is the control variable for total system latency — and it has never been tested. Every sheet to date has been generated without a length constraint, and quality at reduced sheet size is simply unknown.

## 2. Goals / Non-goals

### Goals
- Measure **report quality as a function of skill-sheet token budget** on the matched Qwen→Qwen pair.
- Produce a **quality-vs-tokens curve** with a visible knee, so an operating point can be chosen from evidence.
- Record input/output/reasoning tokens separately so latency can be modelled against any per-node throughput.
- Leave production behaviour **completely unchanged**.

### Non-goals
- Choosing the production model. This experiment informs that decision; it does not make it.
- Sweeping inference parameters (`reasoning_effort`, `temperature`, `max_completion_tokens`, prompt placement). Those are a **follow-up** experiment, deliberately held constant here so sheet size is not confounded.
- Editing the GLM or Sonnet analyser prompts.
- Any frontend work, any route, any change to `MODEL_CONFIG`.

## 3. Current architecture (verified against working tree)

**Analyser.** `generate_ephemeral_skill_sheet()` (`quick_report_analyser.py:662`) calls `_run_agent_with_model` with `output_type=str`, **no `tools=`** — plain free-text, no schema, no tool calls. System prompt selected by `get_analyser_prompt()` (`quick_report_analyser.py:628`), which routes `startswith("claude")` → `ANALYSER_SYSTEM_PROMPT_SONNET`, **everything else → `ANALYSER_SYSTEM_PROMPT_GLM`**. Qwen therefore currently inherits a prompt reverse-engineered for GLM.

**Generator.** `TemplateManager.generate_report_from_config()` (`template_manager.py:2505`) also uses `output_type=str` with no tools (`:2654`). Per-provider settings at `:2592`; the `groq` branch (`:2604`) sets `temperature 0.8`, `top_p 0.95`, `max_tokens 8000`.

**Groq plumbing.** `_run_agent_with_model` (`enhancement_utils.py:3770`) sets `groq_reasoning_format='parsed'` for models in `GROQ_REASONING_MODELS`, which contains `qwen/qwen3.6-27b`. Confirmed working — no thinking-token leakage in any of the 20 bake-off reports.

**Analyser Groq branch.** Added 2026-08-12 during the bake-off (`quick_report_analyser.py:712`, currently uncommitted). Without it the analyser sent Cerebras-only `extra_body` toggles *and the Cerebras API key* to Groq. Additive; production analysers are `zai-glm-4.7` and `claude-haiku-4-5-20251001`, so no live path is affected.

**Judge.** `quality_scoring.py` — `RUBRIC_VERSION_V22 = "v2.2"` (`:184`), `DIMENSIONS_V22` = `output_adherence`, `dictation_fidelity`, `normal_fill_appropriateness`, `unwarranted_assertion` (`:186`). All four judge the **report**, not the sheet. `score_report()` (`:441`) needs a DB row, but `_assemble_case()` (`:313`) returns a plain dict — `{pipeline, inputs, skill_sheet, ai_output, final_output}` — so `_case_text_v2()` (`:252`) plus `_default_judge()` (`:360`) can score ad-hoc text with no database. `_default_judge` calls `asyncio.run()` internally and must not be invoked from inside a running loop.

**Existing harness.** `scripts/analyser_test_suite.py` (463 lines) fans cases across analyser variants and generators, writes `case_*.json` + `summary.md` + `metrics.csv`. `--case` is `action="append"` (repeat the flag), `--variants`/`--generators` are `nargs="+"`. This experiment needs per-run token capture and a sheet-budget axis, which that harness has no concept of, so it gets a sibling rather than an extension.

### Confirmed constraints (Groq docs, retrieved 2026-08-12)

- `reasoning_effort` on Qwen 3.6 27B accepts **only `none` and `default`**. `low`/`medium`/`high` are GPT-OSS-only. Not swept here; held at default.
- Qwen 3.6 27B: context 131,072, **max output 16,384**. The measured 15,529-token generation was within 5% of that hard ceiling.
- `max_tokens` is the deprecated alias; Groq's parameter is `max_completion_tokens`. The Groq branch sets `max_tokens: 8000` yet a generation produced 15,529 output tokens — **the cap is not being applied**. Logged as a finding here, fixed in the follow-up experiment, deliberately not fixed now (capping the generator would mask the reasoning-reduction effect this experiment exists to measure).
- Groq recommends `temperature` 0.5–0.7 "to prevent repetitions or incoherent outputs". The Groq branch uses **0.8**. Out of spec; held constant here, swept in the follow-up.
- Groq advises avoiding system prompts for reasoning models. Not acted on here.
- Rate limits are org-level; the observed ceiling is **32,000 OTPM**, which killed 4 of 20 cells in the first bake-off when four Qwen calls ran concurrently. Serialised re-runs passed cleanly.
- Qwen 3.6 27B is a **preview** model on Groq: "may be discontinued at short notice with limited advance warning." Strategic risk, recorded for the migration decision.

## 4. Experiment design

**Fixed:** Qwen analyser → Qwen generator. The same 5 cases from `test_cases/analyser_suite.json`. Fixed `seed`. Generator settings untouched and **uncapped** — its token consumption is the dependent variable.

**Varied:** exactly one thing — the sheet's structural budget.

| tier | findings × variants | impression ex. | clauses | negatives | normal-study path | cuts |
|---|---|---|---|---|---|---|
| T1 | unconstrained (4–6 × 3) | 2–3 | 3–6 | ~6 | full sweep | — (control) |
| T2 | 4 × 3 | 2 | 4 | 4 | full sweep | breadth |
| T3 | 3 × 3 | 2 | 3 | 3 | full sweep | breadth |
| T4 | 3 × 2 | 2 | 3 | 3 | full sweep | depth begins |
| T5 | 2 × 1 | 1 | 2 | 2 | primary system only | depth + scaffold |

The ladder is ordered so **breadth is cut before depth**. Covering 3 findings instead of 6 only costs quality when a case presents an uncovered finding; dropping from 3 severity variants to 1 degrades *every* finding the generator handles. Same token saving, materially different risk. Ordering them this way means the knee's **position** identifies the mechanism, not merely its existence: a cliff at T2–T3 implicates breadth, a cliff at T4–T5 implicates depth or the scaffold.

**T1 carries no structural budget** and establishes the control *for the new Qwen prompt*. It is not the same thing as the bake-off's ~13.6k-char sheets, which were produced by Qwen running the **GLM** prompt. Both matter: T1 is what this experiment measures against, and the bake-off figure is the historical reference for unconstrained Qwen before the prompt changed. If T1 lands far from ~3,400 tokens, the Qwen prompt has itself moved sheet length, and that must be reported separately from the tier effect or it will contaminate the curve.

### Shrink mechanism

Sheets shrink via **countable structural budgets** — never via `max_completion_tokens`, and never via a word or token target.

A token cap truncates mid-section: it would measure "how badly does truncation hurt" while appearing to measure "how little detail is sufficient". A *word* target fails more subtly — models cannot count their own tokens, so compliance is loose, and a model pushed toward a word count tends to rush its ending, producing a sheet that looks structurally intact but is thin exactly where the budget ran out. That is truncation in disguise, and it is the specific artefact this experiment must not produce.

Structural budgets avoid both. The sheet is already explicitly combinatorial — `quick_report_analyser.py:422` asks for "three severity-graded variants per finding… cover the 4–6 findings most likely", `:590` repeats it, and Phases 4, 5 and 7 similarly quantify mandatory negatives, interpretive clauses ("typical scan type emits 3–6"), and impression exemplars ("2–3 complete illustrative impressions"). Those integers are the dials. Every tier therefore yields a complete, coherent sheet that simply covers less, and compliance is **verifiable by counting the output** rather than assumed.

Structural counts are the knob; **achieved** sheet size remains the x-axis, since the model will not hit budgets exactly.

### Why the cliff may be sharp

The prompt states that worked examples carry the behaviour, not the prose around them (`quick_report_analyser.py:176` within the Phase 7 block):

> "the exemplars must visibly demonstrate every move the 'Clinical history must-appear' section enumerates. Exemplars are the generator's imitation target… **The prose section without exemplars is decorative; the exemplars are load-bearing.**"

And on the normal-study path (Phase 3): *"A one-line 'no abnormality identified' is insufficient even on focused scans — the worked example teaches the generator the consolidation pattern."*

So the sheet's token mass is mostly worked examples, and worked examples are precisely what transmits behaviour to the generator. This predicts a **sharp** quality cliff rather than a gentle slope, and it predicts the first casualties: must-appear propagation (`dictation_fidelity`) and the consolidation/normal-fill pattern (`normal_fill_appropriateness`).

### Measured per run

Achieved sheet chars/tokens; generator input, reasoning, and visible tokens; analyser and generator latency; structural gate results; v2.2 judge scores across all four dimensions.

### Two-stage scoring

1. **Gate (free, every run):** self-contradiction scan, missing section, thinking-leak markers, truncation. The contradiction scan is the pair-based detector built during the bake-off — it caught the one real failure (`ct_thorax_smoker_lung_nodule`, GLM sheet → Qwen generator: asserted 14 mm hilar lymphadenopathy *and* "No mediastinal or hilar lymphadenopathy").
2. **Judge (v2.2 Sonnet, gate survivors only):** four dimensions, wrapped in `asyncio.to_thread` to avoid nesting event loops.

Gate failures are excluded from the quality curve but reported with their failure reason — a tier that fails structurally is a result, not a gap.

### Sample size

25 pairs on the first pass (5 tiers × 5 cases, single seed). Seed repeats are added only at the two or three tiers bracketing the knee, once the knee is visible. n=5 per tier is thin; per-dimension spread is reported alongside means so a ranking gap can be judged against its own noise.

## 5. Components

**`backend/test_cases/qwen_sheet_budget.json`** — tier definitions. Each entry:

```
{id, findings, variants_per_finding, impression_exemplars,
 interpretive_clauses, mandatory_negatives, normal_study_path, directive}
```

The integer fields are both the budget rendered into `directive` (the text spliced into the analyser prompt) and the **expected counts the compliance check asserts against the produced sheet**. T1 sets every field to `null` and carries an empty directive. Editing the sweep means editing JSON.

**`backend/src/rapid_reports_ai/scripts/sheet_budget_suite.py`** — the harness. Stages: run (serialised, with backoff for 429s) → gate → judge survivors → emit. Depends on `generate_ephemeral_skill_sheet`, `_run_one_generator`, and the `quality_scoring` internals named above.

**`ANALYSER_SYSTEM_PROMPT_QWEN`** in `quick_report_analyser.py` — a Qwen variant carrying a `{{BUDGET_DIRECTIVE}}` placeholder, plus a `qwen` branch in `get_analyser_prompt()`. Additive: GLM and Sonnet prompts untouched, production analysers unaffected. Per `feedback_case_agnostic_prompts`, the budget is expressed structurally (findings covered, variants per finding, clause and negative counts) and never with single-domain clinical examples — which the structural mechanism makes natural, since counts are inherently domain-neutral.

**Outputs** in `backend/test_output/<timestamp>/`: `runs.json` (full per-run record), `curve.csv` (achieved tokens × judge score × latency), and a published **artifact** plotting judge score against achieved sheet tokens, overlaid with generator reasoning tokens and projected latency at 100/115/130 tok/s.

## 6. Error handling

- **429 (OTPM):** exponential backoff and retry, up to 3 attempts. Full serialisation is the primary defence; the bake-off showed serialised runs pass cleanly where concurrent ones do not.
- **Analyser or generator exception:** recorded as a failed run with its error, tier continues. One dead case must not void a tier.
- **Judge failure:** `_default_judge` already retries 3× with backoff and a 60s timeout. On exhaustion the run keeps its gate result and carries a null judge score.
- **Truncation:** if a sheet ends without terminal punctuation it is flagged. A tier where the directive itself induces truncation is a spoiled tier and is reported as such rather than scored.

## 7. Testing

Unit tests in `backend/tests/test_sheet_budget_suite.py`:

- tier config loads and validates (T1's fields are `null` and its directive empty; T2–T5 are populated; every budgeted integer is non-increasing down the ladder)
- `{{BUDGET_DIRECTIVE}}` substitution produces a prompt containing the directive and no residual placeholder — including the T1 case, where an empty directive must leave no placeholder and no dangling heading behind
- the compliance counter extracts exemplar, clause, and negative counts from a fixture sheet and matches hand-counted values
- `get_analyser_prompt()` returns the Qwen prompt for `qwen/*`, and **still** returns GLM's for `zai-glm-4.7` and Sonnet's for `claude-*` (regression guard on the production paths)
- the gate flags a known-contradictory report fixture and passes a known-clean one
- the ad-hoc judge adapter builds a `case` dict matching `_assemble_case`'s keys exactly

The harness is a script, not a route, so `feedback_dev_route_guard` does not apply — nothing becomes URL-reachable.

## 8. Risks

- **n=5 per tier is thin.** Mitigated by reporting spread, and by adding seeds at the knee rather than trusting a single point.
- **The analyser may not honour structural budgets.** If achieved counts cluster regardless of tier, the tiers aren't separable and the experiment cannot run as designed. The compliance counter detects this directly — unlike a word target, a missed exemplar count is unambiguous. **Check after T2 completes, not after all 25 runs**: if T2 produces 6 findings when asked for 4, stop and change the mechanism rather than spending the remaining wall time. Fallback is hard section ablation — removing whole sheet sections rather than trusting the model to count.
- **Compliance may be partial rather than binary** — the model honours the findings count but not the variant count, say. The counter records each budgeted quantity separately so partial compliance is visible per-field instead of collapsing into one pass/fail.
- **Judge noise may exceed tier differences** at the shallow end of the curve, making the knee unresolvable without more samples.
- **Groq preview status** means the measurement platform may disappear. Token counts and quality scores transfer to another host; wall-clock latencies do not.

## 9. Expected findings

Recorded in advance so the data can contradict them:

1. **Breadth cuts are close to free; depth cuts are not.** T2 and T3 hold quality near baseline. The cliff appears at **T4**, where variants-per-finding drops from 3 to 2 — because per the prompt's own account the exemplars are load-bearing, so thinning them degrades every finding rather than only uncovered ones.
2. Generator reasoning falls **faster** than sheet size, per the superlinear relationship measured in the bake-off (2.1× input → 3.2× reasoning). This is the effect that makes the exercise worthwhile; without it, shrinking the sheet buys only the sheet's own tokens.
3. `dictation_fidelity` and `normal_fill_appropriateness` degrade first — must-appear propagation and the consolidation pattern are both taught by worked examples. `output_adherence` degrades most gracefully, since section structure is carried by prose that survives every tier.
4. T5 fails the structural gate outright on at least one broad-coverage case (`ct_tap_acute_abdomen_gda_bleed`), because cutting the normal-study path to primary-system-only removes the per-system sweep template that broad scans depend on.

If (1) and (3) both hold, the operating point is **T3** and the actionable finding is that breadth, not depth, is the safe economy.
