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
| Context / max output | 131,072 / **16,384** | The output ceiling; our generator cap now sits at it. |
| Our generator cap | `GROQ_GENERATOR_MAX_TOKENS = 16384` | **Was 8,000, which truncated reports** when reasoning ran long (L-04, L-05). Raised 2026-08-12; truncation eliminated (L-10). Observed peak since: 7,852 tokens. |
| Groq parameter name | `max_completion_tokens` | `max_tokens` is the deprecated alias; worth tidying, not a live bug. |
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
> **CORRECTED 2026-08-12 — the original verdict below was wrong.**

~~**Verdict: not applied.**~~ An instrumented call recorded 15,529 output tokens against a
configured `max_tokens: 8000`, which was read as the cap being ignored.

**Corrected verdict: the cap IS applied per call.** Confidence: high.
`result.usage()` **accumulates across pydantic-ai retries** (`retries=2` in
`_run_agent_with_model`). The 15,529 figure was one capped 8,000-token attempt plus a 7,529-token
retry, not a single uncapped call. Confirmed by the reasoning matrix: the only two runs with
`finish_reason == "length"` reported **exactly 16,000 and 24,000** output tokens — 2.00× and 3.00×
the cap — while all 18 other runs sat at non-round fractions below it.
→ **Never read `usage()` as single-call output** on a path with retries enabled.
→ `max_tokens` vs `max_completion_tokens` is still worth tidying, but it is not a live bug.

### L-05 · Intermittent generator truncation — **SOLVED**
**Verdict: reasoning exhausts the 8,000-token cap.** Confidence: high.
Reports stopped mid-sentence inside FINDINGS, never reaching IMPRESSION (3/25 in the sheet-budget
sweep, 2/20 in the reasoning matrix). Caught by the structural gate; the **judge caught none** — a
truncated report reads as fluent for as long as it lasts.

Mechanism: long reasoning consumes the whole `max_tokens: 8000` budget → visible output is cut →
`finish_reason == "length"` → pydantic-ai retries → still truncated → truncated content returned.
This is why visible length varied (656–1,561 chars): the leftover budget depends on how long the
reasoning ran. It also explains why a re-run completed — reasoning length is stochastic, so the
same input sometimes fits.

**Both truncations occurred in reasoning-ON cells. With generator reasoning off, output is
257–613 tokens — 3–8% of the cap — and truncation is structurally impossible** (5/5 gate pass in
both reasoning-off cells).
→ Two independent fixes: raise `max_tokens` toward the model's 16,384 ceiling, and/or disable
generator reasoning. The first is free and should happen regardless.

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

### L-09 · Reasoning on/off, per stage → quality and latency
**Verdict: the two stages are opposite.** Confidence: moderate (n=4–5/cell, 1 seed).
2×2, analyser × generator, all other parameters and prompts identical.

| cell | analyser | generator | **quality** | analyser | generator | gen tokens | gate |
|---|---|---|---|---|---|---|---|
| `on_on` control | on | on | 4.94 | 20.1s | 13.3s | 6,094 | 4/5 |
| `off_on` | **off** | on | **5.00** | **7.9s** | 15.7s | 7,291 | 4/5 |
| `off_off` | off | off | 4.80 | 7.5s | **1.8s** | **370** | 5/5 |
| `on_off` | on | **off** | **4.45** | 21.4s | 1.9s | 420 | 5/5 |

**Analyser reasoning is free to remove.** Turning it off cost nothing measurable (5.00 vs 4.94)
and cut the analyser from 20.1s to **7.9s** — a 2.5× saving on the stage whose latency is already
hidden behind dictation. Sheet shrank only slightly (13,748 → 12,758 chars).

**Generator reasoning is load-bearing.** Removing it cost quality in both cells that did so, and
the damage is specific: `output_adherence` 4.75 → **4.00** and `normal_fill_appropriateness`
5.00 → **4.40** in `on_off`. Those are exactly the behaviours the sheet's structural rules and
normal-fill discipline are meant to drive — the generator's reasoning is what applies them.

**The stages interact.** With generator reasoning off, the reasoning-*on* analyser's denser sheet
(15,217 ch) scored **worse** (4.45) than the reasoning-off analyser's leaner one (12,418 ch → 4.80).
Echoes the original bake-off finding that matched pairs beat cross-pairings: a thin generator
cannot exploit a dense sheet.

→ Prior expectation — "analyser reasoning worth keeping, generator's worth dropping" — was
**exactly inverted**.
→ Self-hosted at 115 tok/s: generator reasoning on ≈ **53s**, off ≈ **3.2s**.
*Caveat: `on_on` and `off_on` are n=4, each having lost its hardest case to truncation, which
flatters both. `off_on`'s 5.00 in particular excludes the lymphoma case.*

### L-10 · Raising the generator cap 8000 → 16384 — **truncation eliminated**
**Verdict: fixed.** Confidence: high.
Re-ran both reasoning-ON cells (10 runs) after the change. **`finish_reason == "stop"` on all 10**;
zero `length`. Both previously-truncating cases completed and scored **5.00**:

| | before (cap 8,000) | after (cap 16,384) |
|---|---|---|
| `on_on` / ct_tap | 2,247 ch, `length`, excluded | **2,731 ch, `stop`, 5.00** |
| `off_on` / ct_ap_lymphoma | 1,725 ch, `length`, excluded | **2,793 ch, `stop`, 5.00** |

Peak single-call generator output is now 7,852 tokens — comfortably inside the new cap, so the
old 8,000 was marginal rather than generous.
→ `template_manager.GROQ_GENERATOR_MAX_TOKENS`, guarded by bounds tests.
→ Both recovered cases scoring 5.00 **removes the exclusion bias** that flattered L-09's
reasoning-ON cells. The comparison below is now clean at n=5.

### L-11 · Gate false positive on negated clauses — **fixed**
**Verdict: detector bug, not a model defect.** Confidence: high.
"No pleural effusion **is present**" contains the positive pattern `effusion is present`, so a
single clean negative sentence tripped both halves of a contradiction pair and wrongly excluded a
run from scoring.
Fix: a positive assertion inside an already-negated clause does not count, and the negation must
sit in a *different sentence* from the positive finding. Re-validated across the full 85-report
corpus: 7 flagged, all genuine (5 truncations, 1 real contradiction, 1 missing section), false
positive gone.
→ Lesson: an integrity detector needs its own regression corpus. This one was silently
over-firing and would have biased every subsequent quality comparison downward.

### L-12 · Analyser vs generator reasoning — clean result at n=5
**Verdict: analyser reasoning is free to remove; generator reasoning is load-bearing.**
Confidence: moderate-high (n=5/cell, 1 seed, post-fix).

| cell | analyser | generator | quality | analyser | generator | gen tokens |
|---|---|---|---|---|---|---|
| `off_on` | **off** | on | **5.00** | **7.9s** | 15.7s | 7,196 |
| `on_on` control | on | on | 4.90 | 20.1s | 14.3s | 6,264 |
| `off_off` | off | off | 4.80 | 7.5s | **1.8s** | **370** |
| `on_off` | on | off | 4.45 | 21.4s | 1.9s | 420 |

`off_on` is a **clean sweep — 5.00 on all four dimensions, all five cases**. Turning analyser
reasoning off cost nothing and saved 12 seconds on a stage whose latency is already hidden behind
dictation.
Removing *generator* reasoning costs `output_adherence` (4.80 → 4.00 in `on_off`) and
`normal_fill_appropriateness` (5.00 → 4.40) — the behaviours that apply the sheet's structural
rules.
→ **Recommended operating point on Groq: analyser reasoning OFF, generator reasoning ON.**
→ **Unresolved for self-hosted:** generator reasoning is ~7,200 tokens ≈ **63s at 115 tok/s**.
Turning it off gives ~3.2s but costs ~0.2–0.55 quality. That trade is the open decision.

### L-13 · Radiologist review — `off_on` preferred, omissions were editorial
**Verdict: sign-off grade.** Confidence: high (consultant radiologist, 5 cases, direct review).
A consultant radiologist reviewed all five cases side by side — dictation, three configurations,
aligned by section. Verdict on **`off_on` (analyser reasoning OFF, generator reasoning ON)**:

> "consistently much better reports than either of the variants. Specifically the linguistic style
> and the prioritisation method being used are far more sophisticated and the impression summary is
> much more clinically integrated and concise… I would be quite happy to sign those off."

On the omissions flagged in L-12's analysis: **"a lot of the omissions that have been made are for
those findings that are borderline incidental or insignificant, especially within the context of
what's being presented."**

→ **Reverses the concern raised in prior analysis.** What looked like dropped findings is
editorial discrimination — deciding which incidentals earn a place given the clinical question.
GLM's completeness is not automatically superior; it is less selective.

### L-14 · Do NOT build a dictation-completeness metric
**Verdict: rejected before implementation.** Confidence: high.
Naive recall of dictated findings was about to be added to the gate, on the reasoning that neither
gate nor judge caught the `off_on` omissions. **L-13 shows that metric would have been actively
harmful**: it scores omission as failure regardless of clinical significance, so optimising against
it drives the generator toward verbose, undiscriminating reports — the opposite of the behaviour a
consultant values.

→ Completeness against dictation is **not** a quality proxy for this task. Selectivity is a skill,
not a defect.
→ The generalisable lesson: an automatable metric that is easy to compute and intuitively
appealing can still encode the wrong objective. Where clinical judgement is the target, the
measurement needs a clinician in the loop — the rubric judge and the structural gate catch
mechanical faults (truncation, contradiction, leakage), not editorial quality.
→ Corollary: the two prior analyses that leaned on omission counts should be read as *descriptive*,
not evaluative.

### L-15 · Next lever is inclusion/exclusion policy, not architecture
**Status: open, radiologist-directed.**
> "Perhaps with further prompting tweaks we could get the generation to be a bit sharper in terms
> of various inclusions and exclusions."

The remaining quality work is defining *which* incidentals earn a place in FINDINGS and which earn
a line in the IMPRESSION with an action attached. That is a prompt/skill-sheet question, and it
needs the radiologist to mark specific calls right or wrong — the judge cannot supply this.

### L-16 · Why the adrenal was dropped — **the sheet, not the generator**
**Verdict: analyser reasoning OFF produces a shallower anatomical sweep, and findings in the
missing stations fall through the floor.** Confidence: high (reasoning trace + sheet diff, n=1 case
traced end to end, corroborated by the cell-level pattern).

The radiologist confirmed the 2.4 cm nodular left adrenal *should* have been reported. Tracing it:

**1. The generator planned to include it.** Its reasoning (off_on / ct_tap, 27,935 chars) contains,
in the Impression Plan: *"Secondary: Incidental AAA growth (3.8 to 4.6cm), chronic pancreatitis,
**adrenal nodule**, renal cysts, hiatus hernia, cholelithiasis."* It was never revisited.

**2. Carry-through tracks how often an item is revisited**, across that trace:

| item | mentions in reasoning | in report |
|---|---|---|
| cholelithiasis | 5 | yes |
| renal cysts | 1 | yes |
| adrenal nodule | 1 | **no** |
| hiatus hernia | 1 | **no** |
| faecal loading / encephalomalacia | 0 | **no** |

**3. The sheet gave it nowhere to go.** The `off_on` sheet's sweep is
`Mesenteric vasculature → Bowel → Mesentery → Aorta/branches → Solid organs → Peritoneum → Pelvis
→ Thorax`, and its solid-organ station is defined as **"pancreas, liver, spleen, kidneys"** —
adrenals absent, and absent again from that station's canonical default-normal line. The sheet also
states P1 does NOT include *"solid organ incidentalomas"* — excluding them from the primary
paragraph **without providing a destination**. There is no terminal incidental-findings station.

**4. Analyser reasoning ON fixes it.** The `on_on` sheet for the same case sweeps
`… → upper abdominal solid organs → **retroperitoneum and systemic vasculature** → pelvis …`. That
retroperitoneum station is where adrenals live, and the `on_on` report duly contains the adrenal
nodule, the hiatus hernia and the faecal loading.

→ **Partially reverses L-12/L-13.** Analyser reasoning off is *not* free: it costs anatomical sweep
completeness. The rubric missed this because no dimension measures whether the sweep enumerates all
in-scope stations.
→ **It is prompt-fixable**, and independently fixable two ways: (a) restore analyser reasoning —
20.1s vs 7.9s, and that latency hides behind dictation anyway; (b) require the sweep to enumerate
in-scope stations exhaustively and add a terminal incidental-findings station so items excluded
from P1 have a destination. Do both.
→ **Do NOT read this as an argument for turning generator reasoning off.** The generator's
reasoning is what identified the incidental in the first place; `off_off` included it by
transcribing more literally, not by judgement.
→ Open: the radiologist preferred `off_on`'s prose style. `on_on` shares its generator config, so
the style should survive — but `on_on` has not yet been reviewed. Added as a fourth column for
review.

---

## Open questions, in priority order

1. ~~What causes the intermittent truncation?~~ **Answered — L-05.** Reasoning exhausts the 8k cap.
2. ~~`reasoning_effort: none` → quality and latency.~~ **Answered — L-07, L-09.**
3. **Raise `max_tokens` toward 16,384 and re-measure.** Free fix; removes the truncation failure
   mode without touching reasoning. Do this before any further quality comparison, since two cells
   above lost their hardest case to it.
4. **Can generator reasoning be kept but bounded?** L-09 says it is load-bearing for
   `output_adherence` and `normal_fill_appropriateness`, but it costs ~50s at self-hosted rates.
   Is there a middle setting — scaffold removal, a shorter thinking budget — that keeps the
   discipline without the tokens? This is now the central question.
5. **Generator reasoning scaffolds** (`PRE_WRITING_ANALYSIS`, `VERIFICATION_CHECKLIST`) — sent to
   every non-Anthropic model. The most likely lever for (4).
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
