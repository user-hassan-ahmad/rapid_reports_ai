# Model Migration — Parameter Ledger

**What this is.** A cumulative record of *which parameter affects what*, built experiment by
experiment during the move off Cerebras. Each entry states what was varied, what moved, what
didn't, and how confident we are. Append; don't rewrite history — a contradicted finding stays
with its contradiction recorded, because knowing something was ruled out is worth as much as
knowing it works.

**Why it exists.** The migration touches ~27 role assignments across three retiring Cerebras
models. Tuning that many surfaces by intuition wastes runs. This file is the accumulating map.

**Deadline context.** Cerebras Developer Tier retires **2026-08-17**, removing `zai-glm-4.7`,
`gpt-oss-120b`, and `gemma-4-31b`.

---

## Standing constraints (Groq / Qwen 3.6 27B)

Established from Groq's docs, 2026-08-12. These bound what is tunable at all.

| Constraint | Value | Consequence |
|---|---|---|
| `reasoning_effort` | **binary only**: `none` \| `default` | The `low`/`medium`/`high` scale is GPT-OSS-only. Reasoning is an on/off switch for this model, not a dial. |
| `reasoning_format` | `parsed` \| `raw` \| `hidden` | `parsed` is what we use and it works — no thinking leaked into any of 55 reports measured. |
| Context / max output | 131,072 / **16,384** | Output ceiling is the binding one; a measured generation reached 15,529. |
| Groq parameter name | `max_completion_tokens` | `max_tokens` is the deprecated alias. **Ours is not being applied** — see L-04. |
| Recommended temperature | 0.5–0.7 | Ours is **0.8** on the Groq branch (`template_manager.py:2604`) — out of spec. Groq warns this risks "repetitions or incoherent outputs". |
| System prompts | Groq advises **against** for reasoning models | We put everything in `system_prompt`. Untested. Pulls against prompt caching, which wants a large static prefix. |
| Rate limit | 32,000 OTPM observed, org-level | Killed 4 of 20 cells when 4 Qwen calls ran concurrently. Serialise. Cached tokens don't count toward limits. |
| Model status | **Preview** | "May be discontinued at short notice with limited advance warning." Weaker commitment than the Cerebras notice we're fleeing. |

---

## Ledger

### L-01 · Skill-sheet size → report quality
**Verdict: no effect.** Confidence: moderate (n=5/tier, 1 seed).
Varied sheet structural budget across 5 tiers, from unconstrained down to 2 findings × 1 variant.
Mean rubric v2.2 score stayed within **4.75–4.95** — total spread 0.20 on a 5-point scale.
`dictation_fidelity` held at **5.00 on every tier**. No self-contradiction, no thinking leak.
→ **A much thinner sheet is clinically safe.** Cut it for cost or context if useful.
Contradicts the prior expectation that worked exemplars are load-bearing enough to produce a
sharp cliff when thinned.
*Source: `docs/superpowers/specs/2026-08-12-qwen-sheet-budget-RESULTS.md`*

### L-02 · Skill-sheet size → latency
**Verdict: weak, sub-linear.** Confidence: high.
Sheet **−31%** bought generation **−20%** and analyser −29%. The predicted superlinear
reasoning collapse did **not** occur.
Mechanism: the budgeted sections (style exemplars, impression exemplars, clauses, negatives) are a
*minority* of sheet mass. Scope declaration, clinical lane, structural pattern, companion matrix,
terminology, measurement conventions and suppression rules are unbudgeted and dominate.
→ **Sheet budget is not the latency lever.** At 115 tok/s this moves ~66s → ~52s, against a target
needing ~4×.

### L-03 · Structural budgets → model compliance
**Verdict: exact compliance.** Confidence: high.
**125 of 125 budgeted fields hit**, every tier, every case. Counting findings, variants, exemplars,
clauses and negatives is a reliable control surface for this model.
→ Prefer **countable structural budgets** over word/token targets. Compliance becomes measurable
rather than assumed, and a token cap would truncate mid-section — measuring "how badly does
truncation hurt" while appearing to measure "how little detail suffices".

### L-04 · `max_tokens` on the Groq generator path
**Verdict: not applied.** Confidence: high.
`template_manager.py:2604` sets `max_tokens: 8000`; an instrumented call on that exact path
recorded **15,529 output tokens**. Groq's parameter is `max_completion_tokens`.
→ The generator runs effectively uncapped. Fix before drawing any conclusion that depends on
output length.

### L-05 · Intermittent generator truncation
**Verdict: real, unexplained, ~12%.** Confidence: moderate (3/25).
Three reports stopped mid-sentence inside FINDINGS, never reaching IMPRESSION. Not tier-related
(1 at T1, 2 at T5). Caught by the structural gate; the **judge caught none** — a truncated report
reads as fluent for as long as it lasts.
**Token-ceiling hypothesis tested and rejected**: re-running the worst failure produced a complete
report at 6,105 output tokens, 37% of the 16,384 ceiling.
→ Two separate facts hold: the cap isn't applied (L-04) *and* something intermittent truncates.
Next diagnostic step is capturing `finish_reason` per generation — not recorded today.

### L-06 · Judge inputs must carry the dictation
**Verdict: causal, large.** Confidence: high.
`quality_scoring._format_input_data` emits three labelled lines including `Dictated findings:`.
Omitting the dictation scored a known-good report **3/5 on `dictation_fidelity` and 4/5 on
`output_adherence`**; with it included the same report scored **5/5/5/5**.
→ Any ad-hoc judge call must go through `sheet_budget.judge.format_inputs`. A missing dictation
depresses two of four dimensions uniformly while looking entirely plausible.

### L-07 · `reasoning_effort: none` → latency
**Verdict: enormous.** Confidence: high (probe + smoke, quality pending).
`extra_body: {"reasoning_effort": "none"}` **is accepted** on Groq for this model —
`GroqModelSettings` has no such field, so it must go through `extra_body`, and it works.

| | reasoning default | reasoning off |
|---|---|---|
| Isolated probe | 750 tok / 3.0s | **38 tok / 0.2s** |
| Analyser (real case) | ~17–24s | **7.0s** |
| Generator (real case) | ~13–17s, ~5,000 tok | **1.6s, 291 tok** |

The generator drops from ~14s to **1.6s** — and the sheet is still full-length (12,239 chars) and
the report normal-length (1,245 chars), so this is not truncation. `finish_reason == "stop"` on
both calls.
→ At 115 tok/s self-hosted, 291 output tokens is **~2.5s**. This lever alone appears to solve the
latency problem that L-02 could not touch. **Quality is the open question**, not speed.

### L-08 · `finish_reason` is reachable
**Verdict: available.** Confidence: high.
`result.all_messages()[-1].finish_reason` on pydantic-ai's `ModelResponse` (also
`provider_details["finish_reason"]`). The sheet-budget runner did not capture it; the reasoning
matrix does.
→ This is the L-05 truncation diagnostic. `"length"` confirms a cap; anything else rules it out.

---

## Open questions, in priority order

1. **What causes the intermittent truncation?** (L-05) Clinical-safety issue, independent of model
   or host. Capture `finish_reason`.
2. **`reasoning_effort: none` → quality and latency.** Reasoning is 93–95% of every generation, so
   this is the largest available lever. Binary for this model.
3. **Generator reasoning scaffolds** (`PRE_WRITING_ANALYSIS`, `VERIFICATION_CHECKLIST`) — sent to
   every non-Anthropic model. Removing them is the other half of the reasoning question.
4. **`temperature` 0.8 → 0.6.** Out of Groq's recommended range; the one incoherence failure we
   have is the failure mode Groq's warning names.
5. **Prompt placement** (system vs user message). Groq advises against system prompts for
   reasoning models. Genuine unknown; interacts with prompt caching.

---

## Method notes worth reusing

- **Validate parsers against real model output, not fixtures.** Doing so caught two bugs that would
  have silently corrupted results: a negatives miscount (the model emits them inline *or* as an
  indented sub-list) and L-06.
- **Write predictions down before the run.** Three of four predictions in the sheet-budget spec were
  contradicted; having them on record made that the finding rather than a quiet reinterpretation.
- **Gate before judging.** Free structural checks (contradiction, missing section, thinking leak,
  truncation) catch what the LLM judge does not, and keep judge spend off already-broken runs.
- **Serialise everything against Groq.** Concurrency at this org's OTPM limit loses cells.
