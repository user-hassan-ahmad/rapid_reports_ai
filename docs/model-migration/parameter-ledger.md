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

### L-17 · What analyser reasoning actually buys in the sheet
**Verdict: two specifiable things, not diffuse quality.** Confidence: high (5 cases, structural diff).

Structurally the two sheet variants are near-identical: same 10 sections, same sweep-station count
(7.8 vs 7.8), same style exemplars, clauses, negatives and impression exemplars. The only gross
difference is **+27% length** (14,743 vs 11,632 chars), and it is not evenly spread:

| section | ON | OFF | delta |
|---|---|---|---|
| **Conditional Suppression Rules** | 1,917 | 577 | **+232%** |
| Impression Exemplars | 2,238 | 1,713 | +31% |
| Interpretive Clause Rules | 874 | 662 | +32% |
| Companion Matrix | 1,227 | 974 | +26% |
| *(everything else)* | — | — | +5% to +14% |

**Difference 1 — suppression rules are general vs case-keyed.** Reasoning-off writes mechanical
anti-duplication rules bound to this case's findings (*"IF AAA is confirmed in P1, THEN do not
repeat aortic details"*). Reasoning-on writes transferable principles (*"IF the index finding is
named with its descriptor in P1, the sweep paragraph for that region names the structure only"*).

**Difference 2 — the defeasibility clause is dropped.** Reasoning-off states normal-fill as an
unconditional rule: *"IF dictation is silent about a system, THEN render the canonical
default-normal line."* Reasoning-on carries the qualifier: *"…Silence is not omission — it is the
default rendering. **This rule is defeasible: if a dictated positive implicates the structure as a
companion, the canonical line is dropped or rendered contingently.**"*

That missing qualifier is the report-integrity hardening (see `project_report_integrity_hardening`)
and it is the direct mechanism behind the contradictions observed in Qwen output — "No pneumatosis
intestinalis" alongside dictated mural gas, "the mesentery is unremarkable with no stranding or
fluid" alongside large-volume haemoperitoneum.

**Difference 3 — sweep granularity.** Reasoning-on splits coarse stations and adds terminal
catch-alls (*"…upper abdominal solid organs → retroperitoneum and systemic vasculature → …"*,
*"…bones/soft tissues → secondary visible regions"*). Reasoning-off collapses to *"Solid organs →
Peritoneum → Pelvis → Thorax"* and stops. This is L-16's mechanism, now shown to be one instance of
a general terseness rather than a one-off.

→ **All three are specifiable directives, not emergent judgement.** Given L-03 (125/125 compliance
on structural directives), encoding them and keeping analyser reasoning OFF is a high-confidence
bet — the analyser would be *copying* stated rules rather than deriving them, which suits a
non-reasoning model.
→ Payoff if it works: analyser 20.1s → 7.9s **and** a 27% shorter sheet, which shrinks generator
input and therefore generator reasoning. The savings compound.

### L-18 · Encoding L-17's directives — one worked, one did not
**Verdict: structural directives comply; prose-qualifier directives do not.** Confidence: high
(2 cells x 5 cases, against 2 collected baselines).

| config | analyser | sheet | apparent drops (5 cases) | defeasible clause | known contradiction |
|---|---|---|---|---|---|
| analyser ON (reference) | 22.3s | 14,822 | 1 | **5/5** | clean |
| analyser OFF (the problem) | 7.1s | 11,639 | **6** | 0/5 | **present** |
| **ENC directives** | **8.6s** | **15,772** | **0** | 1/5 | **present** |
| ENC directives + floor | 8.4s | 14,395 | 1 | 3/5 | **present** |

**The sweep directive worked completely.** Apparent drops fall 6 → **0**, better than analyser
reasoning ON (1), and it generalises: every case is clean, not just the one that failed. The sheet
also comes out *larger* than the reasoning-ON sheet (15,772 vs 14,822) at reasoning-OFF speed —
8.6s against 22.3s, a **2.6x saving on the analyser**.

**The defeasibility directive did not.** Stated outright, it appears in only **4 of 10** encoded
sheets against 5/5 with reasoning on. (`enc_a` and `enc_ag` share an analyser configuration — the
floor rule touches only the generator — so their 1/5 vs 3/5 split is sampling noise, and the honest
figure is 40% compliance with high variance.) The material consequence: the mural-gas /
"no pneumatosis intestinalis" contradiction **persists in every reasoning-off variant, encoded or
not**, while analyser reasoning ON is clean on all five cases.

→ **Refines L-03.** Countable structural requirements get ~100% compliance; a requirement to
include a specific *qualifying clause in prose* gets ~40%. The distinction is what can be counted,
not how important it is.
→ **The generator floor rule is not needed.** `enc_a` (directives only) had 0 drops against
`enc_ag`'s 1. No evidence it helps; prefer the smaller change and leave the production generator
prompt untouched.
→ **Not yet a clean substitute for analyser reasoning.** Encoding buys completeness and speed but
not contradiction safety. Analyser reasoning ON remains the only configuration clean on both.

### L-19 · Next lever — restate defeasibility as a countable requirement
**Status: open, directly implied by L-18.**
Prose directives comply at ~40%; countable ones at ~100%. So convert the requirement rather than
repeat it more loudly: instead of "state that the normal-fill rule is defeasible", require that
**every canonical default-normal line be paired with an explicit suppression condition naming when
it is dropped**. That is a countable pairing (N lines → N conditions), verifiable by the compliance
counter, and it encodes the same semantics.
If that lands, reasoning-off becomes viable on both axes. If it does not, keep analyser reasoning
ON — at 22.3s it hides behind dictation anyway, and the 14s is cheap next to a normal that
contradicts a dictated positive.

### L-20 · Countable defeasibility — complied perfectly, did not fix the contradiction
**Verdict: the form works; it was aimed at the wrong category.** Confidence: high on compliance,
low on the contradiction (n=1–2 per case).

**Compliance, again, is near-perfect.** Every canonical default-normal line carried its own
`SUPPRESS IF:` clause in **6 of 6 draws**, matching a *variable* target exactly each time —
9, 4, 6, 5 and 7 lines respectively. Against ~40% for the same requirement stated as prose. The
countable-form principle (L-03, L-18) is now confirmed twice on independent requirements.

**But the contradiction is not reliably fixed**, and the variance check is the important result:

| draw | config | paired | contradiction |
|---|---|---|---|
| 1 (smoke) | enc_cnt / ct_tap | yes | **present** |
| 2 (full) | enc_cnt / ct_tap | yes | clean |

Same configuration, opposite outcome. **One clean run is not a fix.**

**Why it could not have worked.** The contradicting line — *"No pneumatosis intestinalis or portal
venous gas to suggest bowel necrosis"* — is a **mandatory negative**, not a canonical
default-normal line. The base analyser prompt states outright: *"This defeasibility governs
canonical default-normal lines **only** — mandatory negatives are never suppressed by it, since
they answer the clinical question rather than fill silence."* The pairing was applied faithfully to
the category that was never the problem.

The prompt does address the case elsewhere — *"Where a mandatory negative concerns a region a
dictated positive implicates, state it with the precision the evidence supports — never by
omitting it"* — i.e. **narrow it**, neither drop nor blanket-assert. A reasoning-ON analyser
resolves that tension; reasoning-OFF applies the "never suppressed" rule literally.

**Unexpected bonus: it is now the fastest configuration**, not the slowest as the smoke run implied.

| config | sheet | analyser | generator | gen tokens | drops | contradiction |
|---|---|---|---|---|---|---|
| analyser ON | 14,822 | 22.3s | 14.3s | 6,264 | 1 | clean 5/5 |
| analyser OFF | 11,639 | 7.1s | 15.7s | 7,196 | 6 | present |
| ENC directives | 15,772 | 8.6s | 17.6s | 6,075 | 0 | present |
| **ENC + countable** | 14,289 | **7.7s** | **13.4s** | **5,694** | **0** | 1 of 2 draws |

End-to-end **21.1s against 36.6s** for analyser-reasoning-ON, with the lowest generator token count
of any config and gate 5/5. The smoke run's 26.0s / 9,723 tokens was an outlier, not the trend.

→ **Next test is the same principle aimed at mandatory negatives**: each must carry a countable
narrowing condition naming the dictated finding class that forces it to be restated with precision.
→ **Blocked on a clinical input**: what should that negative say when duodenal mural gas is
dictated? The exemplar the rule points at has to be the radiologist's phrasing, not invented.

### L-21 · Mandatory-negative rescoping — the operation the radiologist named
**Verdict: encodes cleanly, reduces the rate, not yet proven to eliminate.** Confidence: high on
compliance, low on the rate (n=2–4 per config).

Consultant radiologist on the correct operation: state the positive specifically
("duodenal mural gas"), then cover the rest with a **sweeping statement scoped to the remainder**
("the remaining duodenum is unremarkable") — not a negated restatement of the descriptor.

Encoded as a countable pairing, each mandatory negative carrying a `REMAINDER:` form. The analyser
complied fully and produced exactly the right phrasing unprompted by example:

> `"No pneumatosis intestinalis or portal venous gas." — REMAINDER: "The remainder of the bowel wall is unremarkable."`

It also wrote the application rule into Conditional Suppression Rules by itself:
`IF [dictation reports a positive for a mandatory negative class] THEN [replace the mandatory
negative with its REMAINDER form]`.

**Contradiction rate on ct_tap, every draw pooled:**

| config | contradicted | draws | rate |
|---|---|---|---|
| analyser reasoning ON | 0 | 2 | 0% |
| analyser OFF (baseline) | 1 | 2 | 50% |
| + integrity directives | 1 | 1 | 100% |
| + countable defeasibility | 1 | 2 | 50% |
| **+ negative rescoping (sheet only)** | 1 | 4 | **25%** |
| **+ rescoping + generator rule** | 0 | 3 | **0%** |

→ **The generator ignores conditional rules the sheet gives it.** In the first rescoping draw the
sheet carried the REMAINDER form *and* the explicit IF/THEN rule, and the generator emitted the
negative **and** the remainder. That is a new failure class: everything upstream complied and the
generator did not apply it. Stating the substitution generator-side is what the last row adds.
→ **Do not read 0/3 as a fix.** `enc_rsc` also went 0/3 in the same run and is 1/4 pooled; the two
cannot be separated at these counts. Only analyser reasoning ON is clean on every draw, and that is
2 draws.
→ Fourth confirmation of the countable-form principle.

### L-22 · gpt-oss-120b via OpenRouter — the Cerebras escape is like-for-like
**Verdict: available, cheaper, and verified working.** Confidence: high.
Roughly 14 role assignments sit on `gpt-oss-120b`, several tool-call-heavy — the capability class
this programme had never tested. OpenRouter serves the **same weights** across **20 providers**,
**16 advertising `tools` + `tool_choice` + `structured_outputs`**.

| | in $/M | out $/M | max out |
|---|---|---|---|
| Cerebras (dying) | 0.35 | 0.75 | 40,960 |
| CoreWeave | **0.03** | **0.17** | 131,072 |
| DeepInfra | 0.04 | 0.17 | 131,072 |
| Groq | 0.15 | 0.60 | 65,536 |

Verified end-to-end through the existing plumbing — `openrouter` provider, base_url and key
resolution were already implemented, only the `MODEL_PROVIDERS` entry was missing:
- **structured output + `reasoning_effort: medium`** → returned a valid typed object, 159 tokens
- **tool calling** → tool invoked with the right argument, result used in the answer

→ **Same model, different provider: no prompt re-tuning, no capability re-validation.** This
collapses the largest scope risk — ~14 roles migrate by repointing rather than by replacement, and
at roughly a tenth of the Cerebras token price on the cheapest providers.
→ Consider pinning provider order via OpenRouter's `provider` routing rather than accepting the
default route, since max output tokens and throughput vary widely across the 20.

### L-23 · DECISION — analyser reasoning ON; reasoning-off tuning dropped
**Verdict: settled by radiologist review.** Confidence: high.
Across five unseen cases (2 MRI, cardiac, spine, contradiction trap) the radiologist judged
reasoning ON "far far better". The four-layer encoded stack chasing a reasoning-off equivalent is
**abandoned**. Retained in code as opt-in directives with everything defaulting off, so the
production prompt path is unchanged.

Superseded by this: L-17 (what reasoning buys), L-18/L-19/L-20/L-21 (encoding attempts). They stay
recorded — the compliance findings inside them (countable ~100% vs prose ~40%) generalise well
beyond this decision and were reused immediately in L-24.

### L-24 · Recommendation scope — management trespass and US nomenclature
**Verdict: prompt-drift between the two analyser copies, plus rule-to-field distance.**
Confidence: high (deterministic, reproduced and fixed).

Two defects the radiologist identified: recommendations trespassing into clinical management
("Conservative management with immobilisation recommended" on a ligament injury), and non-UK
referral nomenclature ("Structural heart team review", guideline hooks citing ACC/AHA).

**Aetiology, pinned:**

1. **The language originates in the sheet, not the generator.** In the ankle sheet "conservative"
   appears 4×, "immobilis" 4×, "physiotherapy" 1×; in the report, once each or not at all. The
   generator is already filtering — the analyser is the source.
2. **The GLM prompt had lost a constraint the Sonnet prompt kept.** Sonnet's field template read
   *"Out of scope: procedural technique, hardware, treatment protocol, drug specifics"*; the GLM
   template — the one Qwen uses — read only *"<multi-modal, clinical-context-specific list of
   workup modalities and referrals>"*. Exactly the drift `project_report_integrity_hardening`
   warns about.
3. **Rule-to-field distance.** The governing rules sit at **2.6% and 3.1%** of the prompt; the
   field is filled at **71.9% and 99.0%** — a ~28,000-character gap. The ankle sheet stated the
   prohibition and violated it *inside the same field*: recall without application, the signature
   of a prose rule far from its point of use.
4. **The exemplars then carry it**, and the prompt declares exemplars the generator's imitation
   target.

**Fix — closed tag set at point-of-use, in both prompts.** Every Recommendation scope entry must
carry `IMAGING:` / `REFERRAL:` / `MDT:` / `TISSUE:` / `CORRELATION:`; anything untaggable is
outside radiological remit. UK NHS service names required; guideline hooks prefer UK bodies.
Countable, so `compliance.recommendation_scope()` can assert it.

**Measured before → after:**

| | out-of-remit terms | tagged entries | impression |
|---|---|---|---|
| MRI ankle | 5 → **2** | 0 → **2** | "Conservative management with immobilisation" → **"Orthopaedic review"** |
| CT TAVI | 2 → **1** | 0 → **3** | "Structural heart team review" → **"Cardiothoracic surgery and interventional cardiology MDT review"** |
| guideline hooks | — | — | `ACC/AHA/ESC` → **`NICE … EAPCI/ESC`** |

→ Residual terms live in `Clinical Lane` and `Interpretive Clause Rules` and **do not reach the
report**. One exception worth closing: `protection strategy` persists in the *Abnormal impression
exemplar's descriptive body*. The new rule constrains the exemplar's recommendation clause only;
the imitation vector is the whole exemplar.
→ Remit wording taken from the radiologist: clarify diagnostic uncertainty, guide probabilistic
evaluation from the imaging, direct further radiological investigation for doubtful elements.

### L-25 · Hosting — Groq is 5x faster, and cannot follow the vendor's own spec
**Verdict: speed and durability are now a binary choice.** Confidence: high.

Measured on identical prompts, generator call only:

| | analyser | **generator (spinner)** | end-to-end |
|---|---|---|---|
| Groq | ~20s | **13.1s** | ~33s |
| OpenRouter / CoreWeave (~90 tok/s) | 83.7s | **65.9s** | ~150s |

Report length was unchanged (1,864 vs 1,881 chars) — CoreWeave is slower, not worse. The linear
rescale used earlier is validated: 65.9s at 90 tok/s predicts 51.6s at 115, within 3% of the
earlier projection. At the 100–130 tok/s self-hosted band the spinner is **46–60s** against GLM's
9.2s today.

**Two OpenRouter traps.** Default routing chose Phala at **15 tok/s** — a 513s analyser call, 30x
slower than Groq. And provider choice changes *output*, not just speed: Phala produced a 33,703-char
sheet against CoreWeave's 13,337 on identical input. Pin the provider; never accept the default.

**Groq cannot follow Qwen's published recommendations** (model card, `Qwen/Qwen3.6-27B`):

| parameter | Qwen recommends | we send | |
|---|---|---|---|
| `temperature` | 0.6 (thinking, precise) | **0.8** | out of spec on Qwen *and* Groq's own 0.5–0.7 |
| `top_k` | **20** | **never set** | **no such field on Groq; API does not expose it** |
| output length | **32,768** | 16,384 | Groq's hard ceiling is half the recommendation |

→ Groq buys 5x speed at the cost of three vendor-recommended settings, two of them structurally
unreachable there.

### L-26 · Generator reasoning cannot be bounded
**Verdict: no lever works.** Confidence: high (2 cases, CoreWeave).

| lever | TAVI reasoning | ct_tap reasoning |
|---|---|---|
| baseline | 8,313 | 6,153 |
| `reasoning.effort: low` | 5,080 (−39%) | 5,543 (−10%) |
| `reasoning.max_tokens: 2000` | **5,943** | **7,108** |
| scaffolds removed (−89% of user prompt) | 7,142 (−14%) | **7,323 (+19%)** |

**The reasoning budget is silently ignored** — 2,000 requested, 5,943 and 7,108 delivered, the
second above baseline. OpenRouter accepts the parameter and the provider does not honour it.

**Removing `PRE_WRITING_ANALYSIS` + `VERIFICATION_CHECKLIST` does not reduce reasoning**, and
raised it 19% on the complex case while shortening the report 20%. The scaffolds do not *cause*
the thinking, they *organise* it; without them the model derives its own approach, which costs
more and drops content the checklist enforces. All 8 runs passed the gate.

→ Best available is `effort: low`, at −10% to −39%, inconsistent, still 4–6x GLM's current 9.2s.
→ Reasoning ON is what the radiologist wants and its cost **cannot be bounded away**. The
deployment choice is Groq's speed or self-hosted durability, not both.

### L-27 · Temperature and message-role — neither moves the contradiction
**Verdict: both are noise. The defect is ~55% and unfixed.** Confidence: high on the rate,
high on the null result.

2x2 on Groq, generator only, sheet held fixed, 4 draws per cell:

| cell | temperature | message roles | contradiction |
|---|---|---|---|
| A *(current)* | 0.8 | system + user | 3/4 |
| B | 0.6 | system + user | 2/4 |
| C | 0.8 | user-only | 1/4 |
| D | 0.6 | user-only | 3/4 |

Pooled by lever: temperature 0.8 → 4/8, temperature 0.6 → **5/8** (worse). System+user → 5/8,
user-only → 4/8. At n=4 against a true rate near 55%, every cell is within binomial noise —
nothing here is separable.

→ **Qwen's temperature recommendation does not help**, despite 0.8 sitting outside both Qwen's
0.6 and Groq's 0.5–0.7 guidance. Keep 0.8 or move to 0.6 on principle, but not for this.
→ **Groq's "avoid system prompts" guidance does not help** either, at least on this failure.
→ **Pooled Groq rate on ct_tap: 11 contradictions in 20 draws — ~55%.** Earlier text claiming
Groq showed 0/2 while CoreWeave showed 62% was undersampling; the provider-difference inference
drawn from it does not hold. Phala's 2.5x sheet-length difference stands; the failure-rate
difference does not.

### L-28 · The structural gate never covered this contradiction
**Verdict: detector gap, now closed.** Confidence: high.
Every one of the 16 draws above reported `gate=pass` while the ad-hoc analysis regex flagged 9.
`gate.py` carried six contradiction pairs — lymphadenopathy, nodule, haemorrhage, effusion,
consolidation, free fluid/gas — and **none for pneumatosis**. The one failure mode this programme
spent the most effort on was invisible to the production-grade detector for the entire session;
it was only ever caught by throwaway regexes written inline for analysis.

Pair added, with the negated-clause guard preventing "No pneumatosis intestinalis" from counting
as its own positive. Re-validated across **206 reports** collected this session: 20 flagged,
concentrated on `ct_tap` (12) as expected.

→ The general lesson is worse than the specific bug: a hand-written pair list only finds modes
someone already thought of, and its silence reads as safety. Any contradiction class nobody
encoded has been invisible in **every** rate reported in this ledger.
→ The semantic screen (L-?, `contradiction.py`) exists precisely to cover unencoded modes and
should run alongside the gate, not instead of it.

### L-29 · Cerebras roadmap intel; Gemma reasoning discovered, then mooted
**Status: acted on 2026-08-15.** Per Cerebras (via Hassan): **gemma-4-31b retires end of
August 2026**, and **Qwen 3.8 arrives on Cerebras soon**.

Actioned immediately: the three canvas primaries (PROCESS, COVERAGE, INTELLIPROMPTS) moved
gemma → `qwen/qwen3.6-27b` with a provider-aware settings adapter at the canvas funnel — the
Cerebras form (`max_completion_tokens`, top-level `reasoning_effort`) breaks on Groq, which is the
guideline_prefetch lesson applied *before* the incident this time. Live probe of the repointed
process path: structured output OK at **0.5s**.

Recorded for later, though mooted for production by the retirement: Gemma 4 31B **is** a reasoning
model — on Cerebras it defaults **off**, and engages only via `extra_body: {reasoning_effort: …}`
(top-level is silently ignored; third occurrence of the accepted-but-not-honoured pattern).
Reasoning-on cost ~0.6s extra at Cerebras speed. Every Gemma result in this ledger was
non-reasoning mode.

→ **When Qwen 3.8 lands on Cerebras**: validate v2 on it with one command
(`v2_run --model <id>`), check the reasoning default with the probe above, and if quality holds it
collapses the speed/quality trade — Qwen-family reasoning at Cerebras throughput. That is the
configuration this entire programme has been looking for.

### L-30 · YAML sheet encoding — no token win, no reasoning win, slight quality risk

**Verdict: re-encoding the sheet is not a lever; the migration is dead.** Confidence: high on
tokens (deterministic), moderate on quality (n=3/arm, 1 case).

A/B on `ct_tap_acute_abdomen_gda_bleed`: one fresh analyser sheet, transcoded markdown → YAML
deterministically (word-bag verified, 0.0% content loss), generator run 3× per arm interleaved,
params untouched. Runner: `scripts/sheet_budget/sheet_encoding_ab.py`; artifacts:
`test_output/ENCODING_AB_20260822T012941/`.

| | markdown | yaml |
|---|---|---|
| sheet chars | 14,597 | 14,438 (−1.1%) |
| generator input tokens | 10,488 | **10,472 (−16 tok)** |
| generator output tokens (mean) | 7,755 | 8,134 (+4.9%, inside spread) |
| generator latency (median) | ~19.0s | ~19.9s |
| judge v2.2 (all dims) | 5.00 | 5.00 |
| manual defect read (mean) | 4.4 | 4.1 |

- The −1.1% char delta collapsed to **−16 input tokens**: markdown's `- **Key:**` syntax tokenizes
  as cheaply as YAML's indentation+quoting. "Compression" via re-encoding does not exist for this
  sheet; only content abbreviation would compress, which is an information change, not a format one.
- Output tokens confirm **L-26 exactly**: reasoning is set by the clinical task, not input bytes.
- Manual line-by-line scoring found defects in both arms the judge missed entirely (see below).
  Worst single defect was in the YAML arm: dictated "hypodensities … not fully characterised"
  reported as "renal cysts" in the impression. Anecdote at n=3: all three YAML runs normal-filled
  "liver unremarkable" over a known prior fatty liver (defeasibility miss); two of three markdown
  runs correctly stayed silent — possibly the YAML `canonical_default_normal_lines` list being
  applied more literally than the same lines in prose. Not established; do not act on it alone.

**Judge saturation is the second finding.** Rubric v2.2 scored 24/24 dimensions at 5.00 across six
reports that contained, per manual read: one silently dropped dictated finding (background
atherosclerosis, md#2), one must-appear violation (previous stroke absent from impression, md#3),
one characterisation overcall (renal "cysts", yaml#2), and repeated stripping of "not fully
characterised" qualifiers. At ceiling the judge cannot discriminate between arms of *any*
experiment. Before the next quality-sensitive comparison, either harden the rubric anchors or add
a defect-checklist pass (dropped-finding sweep, qualifier preservation, must-appear audit) to the
gate, where it is free and deterministic.

### L-31 · off_off under the hardened prompts — fast, cheap, unshippable; the sheet layer held, the generator layer did not

**Verdict: off_off remains dead; L-23 confirmed under current prompts. But the analyser-off half
now survives.** Confidence: high on the failure mode (deterministic gate, 3/3), moderate on the
rest (n=3, 1 case).

Re-test motivated by the prompt hardening shipped after the reasoning matrix (L-19/L-20/L-21,
L-24). `reasoning_matrix --cell off_off --case ct_tap_acute_abdomen_gda_bleed` ×3, judged against
the same-day on_on baseline in `test_output/ENCODING_AB_20260822T012941/` (markdown arm).

- **Speed/cost is everything L-07 promised**: ~10–12s end-to-end (vs ~37–42s), generator output
  546–826 tokens (vs 6,900–8,700).
- **Gate hard-failed 3/3 on self-contradiction**: every run asserted "No pneumatosis intestinalis"
  alongside dictated duodenal mural gas. The on_on traces show the reasoning generator deliberating
  per-negative and suppressing contradicted ones. **Conditional negative suppression is a
  reasoning-executed behaviour** — stating the rule in the sheet (countable, point-of-use) does not
  make a non-reasoning generator execute the conditional. Same class: "No active contrast
  extravasation … apart from the identified gastroduodenal arterial bleed" (run 2).
- **Must-appears collapsed 3/3** (run 1 impression carried zero of five clinical-context items);
  run 3 silently dropped four dictated findings; "haemodynamic instability/compromise" asserted
  twice without dictation support; one L-24-class trespass ("endocrine evaluation recommended").
- **The hardened sheet layer held**: all three analyser-off sheets contained the adrenal / renal /
  atherosclerosis canaries, and every report kept the adrenal with its qualifier — the exact L-16
  failure mode, now absent at the sheet level.

→ Generator reasoning is load-bearing and stays ON (L-23 stands). The now-open question is
**off_on under current prompts**: L-13's radiologist actually preferred off_on prose, it was
killed only by the sheet dropping stations (L-16), and this run shows the hardened sheets no
longer drop stations. Worth ×3 on the same case before touching the analyser default.

### L-32 · off_on under the hardened prompts — closest cell yet; both residual gaps live in the off-sheet

**Verdict: not a config flip, but the gap is now two nameable sheet behaviours.** Confidence:
moderate (n=3, 1 case, evening Groq load).

`reasoning_matrix --cell off_on` ×3 on ct_tap, scored manually against the same-day on_on
baseline (manual 4.4) and off_off (manual 3.4). **off_on ≈ 4.1.**

- **Finding coverage was the best of any cell measured today: 7/7 canaries ×3 runs, zero drops**;
  renal qualifier 3/3, AAA growth in the impression 3/3 (on_on managed 1/3). L-16's
  sheet-shallowness failure is absent under the hardened prompts.
- **The reasoning generator's conditional suppression handled 3 of 4 planted collisions every
  run** — suppressed the extravasation negative, rescoped "no free fluid or air" to "no free
  intraperitoneal air", stripped "pleural effusion" from a PE negative. The one that slipped is a
  terminological subtype, not a lexical overlap: mural gas ≡ pneumatosis intestinalis. Two runs
  emitted a defensible "apart from the focal duodenal mural gas …" carve-out (the gate flags this
  — arguably gate bluntness); one emitted the negative flat (true contradiction).
- **Root cause is upstream**: the reasoning-ON analyser wrote "No *pneumoperitoneum* …", leaving
  room for the mural gas its clinical question makes likely; the off analyser writes textbook
  negatives blind to collision risk ("pneumatosis", "no free fluid" in a bleed question, "no
  pleural effusion"). Anticipatory negative-scoping is an analyser-reasoning behaviour.
- **Must-appear erosion persists**: stroke 0/3, AF 1/3, lactate 2/3 (L-17's case-keyed-vs-generic
  difference).
- Economics: analyser 22s→~8.5s, analyser tokens −60%; generator tokens unchanged (~8.3k — same
  clinical work off a shallower sheet). Net ~30s e2e vs ~37–42s; ~−29% total output tokens.

→ Next cell if pursued: enc-style **analyser OFF + two new directives** — (a) collision-scoped
mandatory negatives (prefer the discriminating subset; never a negative whose class the clinical
question makes likely), (b) hardened impression must-appear mandate — then ×3 on ct_tap, and only
on a clean result widen to the 5-case suite. L-18 applies: directives are a coin-flip until run.
Also worth fixing regardless: the gate should accept explicitly scoped negatives ("apart from X,
no Y") instead of flagging them as self-contradiction.

---

### L-33 · Qwen 3.8 27B on Cerebras — reasoning is graded, speed gain is eaten by reasoning volume, 16k cap truncates

**Verdict: the configuration L-29 waited for is live, but on_on is not faster end to end; the
lever it does give is a real effort dial.** Confidence: high on the probe, moderate on the runs
(n=3, 1 case, judge v2.2 secondary).

**Probe** (`qwen-3.8-27b`, short clinical prompt, cap 4000): reasoning defaults **ON** (1,305
reasoning tokens with no parameter). `reasoning_effort` is **graded**, not binary — `none` 0 /
`low` 655 / default 1,305 / `high` 3,339 reasoning tokens — and is honoured **top-level as well
as in `extra_body`**; `disable_reasoning: true` also works. `chat_template_kwargs` is rejected
(400). Reasoning returns in a separate `reasoning` field, never in `<think>` tags. Throughput
~1,800 tok/s. Caps of 32,768 / 65,536 / 131,072 all accepted.

**on_on ×3 on ct_tap** (`reasoning_matrix --model qwen-3.8-27b --max-tokens 65536`,
`test_output/reasoning_q38_cerebras_on_on_cap64k_20260924T123153/`):

| run | sheet | analyser | generator | e2e | gate | judge |
|---|---|---|---|---|---|---|
| 1 | 21,693 ch | 16.8s / 30,616 tok | 28.5s / 36,898 tok | 45.3s | pass | 4.50 |
| 2 | 26,487 ch | 17.6s / 34,813 tok | 14.1s / 19,586 tok | 31.7s | **fail** self_contradiction "No pneumatosis" | — |
| 3 | 24,460 ch | 22.1s / 38,462 tok | 25.0s / 32,615 tok | 47.2s | pass | 5.00 |

- **Not faster.** Qwen 3.8 reasons 5–6× longer than 3.6 on Groq (analyser 30–38k output tokens vs
  5–8k; generator 20–37k vs 6–8k). At Cerebras throughput that nets out to 32–47s e2e, the same
  band as the Groq 3.6 on_on baseline (37–42s). The graded `reasoning_effort` (L-26 said it could
  not be bounded — that was OpenRouter/Groq; Cerebras honours it) is the untested lever.
- **The 16k production cap truncates the analyser.** First batch at production settings
  (`reasoning_q38_cerebras_on_on_20260924T122549/`): 2/3 sheets cut mid-sentence after the
  Companion Matrix, 5 of 10 sections, `finish_reason == "length"`. pydantic-ai retries on empty
  content, so `usage()` summed 2–3 attempts (32,000 / 38,113 tokens). **Judge scored both
  truncated sheets 5.00.** Cerebras branch of analyser and generator settings needs a raised cap
  before this model is production-adjacent.
- **Analyser infers non-contrast from the bare scan-type string** ("CT thorax abdomen pelvis") in
  3/6 sheets, and builds mandatory negatives around it. The generator follows the dictation, but
  one 16k-batch report was judged 1.50 for "contradicting" the sheet. Either carry the phase in
  the scan-type input or forbid the inference in the analyser prompt.
- **Sheets doubled** to 21–26k chars (vs 11–15k on 3.6). Coverage held: adrenal / hiatus /
  atherosclerosis / renal / faecal loading in 3/3 reports.
- **L-31/L-32 carve-out recurs**: "No pneumatosis or portal venous gas … elsewhere" beside
  dictated duodenal mural gas; gate reads the scoped negative as a contradiction (same bluntness).
- **All 6 reports emitted a LIMITATIONS section** (v1 generator tolerates it; v3 spec does not).
  Run 3 closed with "pulmonary embolism cannot be excluded … urgent CTPA is recommended" —
  banned construction plus out-of-remit recommendation on a bleed question.

→ Harness: `reasoning_matrix` now takes `--model`, `--runs`, `--max-tokens`; `qwen-3.8-27b`
registered in `MODEL_PROVIDERS` as cerebras.
→ Next: (1) `reasoning_effort: low` on both stages ×3 — if quality holds, that is the compromise
cell this programme wants; (2) raise the Cerebras cap in production settings; (3) fix the
scan-type / contrast inference before any cross-model comparison.

---

### L-34 · `reasoning_effort` on Cerebras is graded and defaults to HIGH — medium halves the cost; arm C (POLICY + v2) at medium is the fastest passing cell

**Verdict: the compromise cell exists.** Confidence: moderate (n=3/cell, 1 case, no judge; gate,
sheet contract, section splitter and canaries only).

Cerebras docs (`/capabilities/reasoning`): `qwen-3.8-27b` **defaults to `high`**; accepts
`none | low | medium | high`; reasoning tokens count toward `max_completion_tokens`; reasoning
is returned separately (`message.reasoning`). So every L-33 run was at the most expensive effort.
Probe on a short clinical prompt: low 607–655 / medium 554 / high 3,339–7,123 reasoning tokens.

Five cells on ct_tap, cap 65,536, reasoning on both stages, mean of 3
(`test_output/POLICY_RUN_q38_{high,medium,low}/`, `reasoning_q38_cerebras_on_on_medium/`):

| cell | sheet ch | report ch | analyser | generator | **e2e** | A out tok | G out tok | gate |
|---|---|---|---|---|---|---|---|---|
| v1 · high (default) | 24,213 | 3,745 | 18.8s | 22.6s | **41.4s** | 34,630 | 29,700 | 2/3 |
| v1 · medium | 33,813 | 4,227 | 14.8s | 10.5s | **25.4s** | 20,639 | 14,492 | 3/3 |
| arm C · high | 8,571 | 3,081 | 17.7s | 15.7s | **33.4s** | 20,561 | 21,477 | 3/3 |
| arm C · medium | 8,872 | 3,278 | 8.1s | 8.5s | **16.6s** | 12,762 | 10,774 | 2/3 |
| arm C · low | 7,247 | 2,960 | 8.2s | 8.5s | **16.7s** | 11,459 | 10,892 | 2/3 |

Arm C = `POLICY + ANALYSER_V2` / `POLICY + GENERATOR_V2`, system prompts byte-identical per
stage, per-case content in the user message (plan Task 8 arm C; the v3 analyser prompt of Task 9
does not exist yet). New runner `scripts/sheet_budget/policy_run.py`; `reasoning_matrix` gained
`--effort`.

- **Medium halves reasoning on both stacks; low adds nothing over medium** on this case.
- **Arm C at medium: 16.6s e2e, coverage canaries intact** (adrenal / atherosclerosis / renal /
  faecal 9/9 across arm C, hiatus 7/9), four-section layout 9/9 with compartment sub-headings.
- **The arm C gate failure (run 2 at medium and at low) is a real contradiction**: "The small
  bowel shows normal wall enhancement and calibre with no pneumatosis" beside dictated duodenal
  mural gas. Duodenum is small bowel. L-31's conditional-negative failure survives POLICY at
  reduced effort; at high effort arm C passed 3/3.
- **v1 at medium passed 3/3** but sheets grew to 32–37k chars and reports carry LIMITATIONS
  (and once CORRELATION) sections and history-restating impressions.
- **v2 notation leaks**: literal `TERMINAL:` sub-heading in 5/9 arm C reports.
- **`validate_sheet_v2` fails 8/9 arm C sheets on `stray_prose`** — quoted T-NEG text inside
  SUPPRESS-IF-HISTORY lines, i.e. the grammar quoting itself. Instrument bluntness; fix the
  validator before using the contract as a gate.
- **Must-appear history erosion in arm C**: lactate 1/9, apixaban 0/9 in reports (v1: nearly all).
  POLICY does not require them; L-13's radiologist preferred less restating. Policy decision.
- One banned construction ("cannot be excluded") in arm C high run 1; none at medium/low.

→ Candidate operating point: **arm C at medium**, once (a) the small-bowel/duodenum negative is
handled (rescoping directive or an OBLIGATION-level rule), (b) `TERMINAL` leakage is closed,
(c) the sheet validator stops flagging its own quoting. Then widen to the 5-case suite and put a
radiologist on it — the judge was not run and the gate is lexical.
→ Production Cerebras settings branch must set `reasoning_effort` explicitly (default is high)
and raise `max_tokens` well above 16,000 before Qwen 3.8 goes near a live route.

---

### L-35 · v1 by subtraction (`prune_v1` directive) — sheet −40%, gate 3/3, the reasoning layer survives; two new leaks

**Verdict: the compromise cell is v1 pruned at medium effort, and it holds.** Confidence: moderate
(n=3, 1 case, no judge; gate + section splitter + canaries + manual read). Spec:
`docs/superpowers/specs/2026-09-24-v1-subtraction-design.md`.

Why this cell exists: a side-by-side read of v1 vs arm C on the same dictation (page tab
"Analysis") traced v1's quality to six instruction-level mechanisms v2/v3 deleted — causal index
paragraph (P1), differential-targeted atomic mandatory negatives, history modifiers with
management implications, the hardening preamble's synthesis epistemics, impression exemplars
carrying must-appear hooks, and "do not copy input phrasing verbatim". Decision: discard the v2
grammar and the v3 four-purpose sheet; rebuild by subtraction from v1.

`prune_v1` (opt-in, `quick_report_analyser.DIRECTIVES`, production path unchanged) cuts
Interpretive Clause Rules, two of three exemplar tiers, the Canonical default-normal list
(Normal-study path is the single source), caps Measurement/Out-of-scope/non-assessables at 3,
and adds two rules: never infer contrast/phase ("Contrast: per dictation"); never pre-assert a
history finding in a canonical line.

`reasoning_matrix --model qwen-3.8-27b --cell on_on --effort medium --directive prune_v1
--max-tokens 65536 --runs 3 --no-judge`, ct_tap
(`test_output/reasoning_q38_cerebras_on_on_medium_prune/`) vs L-34's v1 medium:

| | sheet ch | report ch | analyser | generator | e2e | A out | G out | gate |
|---|---|---|---|---|---|---|---|---|
| v1 · medium | 33,813 | 4,227 | 14.8s | 10.5s | 25.4s | 20,639 | 14,492 | 3/3 |
| **v1 · medium · prune_v1** | **20,206** | 3,410 | 12.2s | 9.0s | **21.2s** | 18,490 | 12,464 | **3/3** |

Predictions: sheet −35–50% → **−40% ✓**; analyser −20–30% → −18% (≈); gate 3/3 → ✓; impression
engagement unchanged → mostly ✓ (see below); "Contrast: per dictation" 3/3 → ✓.

- **Directive compliance**: Interpretive Clause Rules absent 3/3, canonical list absent 3/3,
  contrast line "Per dictation" 3/3, TECHNIQUE correct from dictation 3/3. L-03 holds again.
- **Shared defects moved**: "no mesenteric fat stranding" beside dictated stranding — gone 3/3
  (was 1/1 in both v1 and arm C reads). Steatosis asserted from the prior — 1/3 clean (was
  3/3 asserted); run 2's sheet still carried it in the Normal-study path, run 3's generator
  inferred it with a clean sheet → **needs a generator-side rule too** (cell 2).
- **Report quality (manual read, run 1)**: index paragraph opens with the bleed and carries the
  targeted negatives ("No filling defect in the SMA, IMA, SMV or IMV to suggest mesenteric
  vascular occlusion", "No free intraperitoneal air to suggest bowel perforation"); numbered
  impression engages all three questions, reconciles lactate and Hb, names apixaban, refers to
  IR and vascular, defers renal/adrenal characterisation. Equivalent to the unpruned v1 read.
- **Two regressions to watch (n=3, could be noise)**: run 1 dropped the colon/faecal-loading
  station (0/3 drops in the unpruned cells today) — plausibly the canonical list was doing
  coverage work the Normal-study path alone does not; and no pruned impression recommended
  general surgical review for the duodenal pneumatosis, where the unpruned v1 medium cell did
  2/3 (the pruned run-1 match is "vascular surgical review", not general surgery).
- **New leak**: `REFERRAL:` / `CORRELATION:` tags rendered inline in the impression 3/3 and as
  section headers 2/3 (unpruned v1 leaked CORRELATION 1/3). The Recommendation-scope tag set
  and the exemplars that carry it are the source; the exemplar should demonstrate prose.

→ Cell 2 (generator side, one variable): hardening preamble trimmed of global-guide duplicates
+ "a prior's finding is not a current finding" + tags render as prose. Cell 3: sheet to user
message. Then 5-case suite, then radiologist read.

---

### L-36 · History out of the report, tags out of the report — 24 surgical instruction edits, validated 3/3

**Verdict: both leaks closed at source; no regression on the pruned cell.** Confidence: moderate
(n=3, 1 case, no judge). Decision by Hassan: a radiology report states what the imaging
establishes; clinical history is reasoning input that shapes phrasing and confidence and is
never emitted.

**Root cause was instruction, not drift.** v1 carried a "Clinical history must-appear" hook
list in the analyser (Phase 7 + Output Format, both variants), a rule that exemplars MUST
visibly demonstrate every hook, an exemplar skeleton with "[, in the context of <must-appear
hooks>]", a Phase 2 line that modifiers must be "reflected in the impression", and on the
generator side PRE_WRITING_ANALYSIS step 3 ("these must be reflected in the impression") and a
VERIFICATION line to match. The tag leak came from the Recommendation-scope tag set being
mandated inside the impression exemplars ("must be drawn from this tag set"), so the exemplar
showed `REFERRAL:` literally and the generator reproduced it.

**Edits (all on branch `skill-sheet-v3`, `git diff` is the audit):**

| # | file · site | change |
|---|---|---|
| E1 | analyser Phase 1 (×2 variants) | contrast stated only where the scan-type name states it; never inferred from absence; else "per dictation" |
| E2 | analyser Output Format · Contrast | placeholder text to match E1 |
| E3 | analyser Phase 2 · modifiers | "when the modifier must be reflected in the impression" → "how it changes what the impression asserts and at what confidence. The history is reasoning input: the report never restates it." |
| E4 | analyser Phase 7 · CRITICAL exemplar rule | replaced by "Exemplars carry no clinical history" |
| E5 | analyser Phase 7 · abnormal exemplar bullet | hooks clause removed |
| E6 | analyser Phase 7 · must-appear paragraph (×2) | replaced by "Clinical history is never emitted" (concordance stated against the imaging, never by restating the presentation) |
| E7 | analyser Output Format · must-appear line (×2) | removed |
| E8 | analyser Phase 8 self-check | "exemplars demonstrate must-appear" → "exemplars carry no clinical history" |
| E9–E11 | analyser Output Format · exemplar skeleton | "in the context of <hooks>" slot and hook-integration sentence removed; normal exemplar names no history item |
| E12 | analyser Phase 7 · tag set intro (×2) | tags are sheet notation; a recommendation renders as prose |
| E13 | analyser Phase 7 · exemplar recommendation clause (×2) | "rendered as prose without the tag label" |
| E14 | analyser Output Format · Recommendation scope (×2) | "Tags are sheet notation: they never appear in exemplars or in the report" |
| E15 | analyser Phase 3 · Normal-study path (×2) | a canonical line never asserts a finding the history or a prior study reports |
| G1 | global guide · Output Structure | history "never reproduced — not as a section, and not as content in any section" |
| G2 | global guide · Skill Sheet Internals | recommendation tags are classification labels, never a labelled line or a section |
| G3 | global guide · Missing Data Handling | a history/prior finding is not a finding on this study; asserted only where dictated |
| G4 | PRE_WRITING_ANALYSIS step 3 | "must be reflected in the impression" → change interpretation/confidence/urgency; history never written |
| G5 | VERIFICATION_CHECKLIST | history-restatement line replaced; tag-label line added |
| GT | gate.py | new `tag_leak` check on `IMAGING:|REFERRAL:|MDT:|TISSUE:|CORRELATION:` |
| D | `prune_v1` directive | its contrast and no-prior-assert bullets removed (now base-prompt rules) |

Full suite 232 passed. Anthropic analyser variant shares E1, E6, E7, E12–E15.

**Validation** — same cell as L-35 (`v1 medium + prune_v1`), rerun ×3 on ct_tap after the edits
(`test_output/reasoning_q38_cerebras_on_on_medium_prune_v2/`):

| | before (L-35) | after |
|---|---|---|
| history items in impression | 5 / 4 / 5 | **0 / 0 / 0** |
| tag labels in report | 3/3 (REFERRAL:, CORRELATION: incl. as sections) | **0/3** |
| steatosis asserted from prior | 2/3 | **0/3** |
| colon/faecal loading covered | 2/3 | **3/3** |
| gate (now incl. tag_leak) | 3/3 | **3/3** |
| sheet / report / e2e | 20.2k / 3.4k / 21.2s | 21.2k / 3.4k / 19.9s |

Impressions after: diagnosis-led, negatives answered, referrals as prose, no demographics,
labs, drugs or presenting symptoms anywhere.

- LIMITATIONS rendered 2/3 ("no arterial phase obtained" in the dictation) — this is the
  sanctioned path (Phase 6: dictated technical limitation triggers LIMITATIONS), not a leak.
- Run 1 dropped background atherosclerosis (1/3). Watch.
- **Open regression, now 0/6 across both pruned cells vs 2/3 unpruned medium**: no general
  surgical referral for the duodenal pneumatosis; run 1's impression states the duodenal finding
  without interpretation. Candidate cause is the pruned Interpretive Clause Rules or exemplar
  tiers. Cell 3 = restore interpretive clauses only.
- Run 1: "haematology review for anticoagulant management" — names what the specialty should do;
  scope rule says name the specialty only. Minor; watch.

---

### L-37 · COMPARISON content and impression opening — two per-run analyser drifts, closed at the instruction

**Verdict: both closed; 3/3 on each after the edit.** Confidence: moderate (n=3, 1 case, no judge).

Hassan flagged two aberrancies in L-36 run 1 that runs 2–3 did not show: (a) COMPARISON carried
a finding and an interval measurement plus an invented "no prior CT TAP available" sentence;
(b) the impression opened on the negative answer to mesenteric ischaemia rather than the
confirmed bleed. Traced by pairing each sheet with its report:

- (a) The v1 stack said *whether* COMPARISON acknowledges a prior (three-tier rule) but never
  *what it contains*. The analyser rewrites that rule per run; run 1 wrote "comparison … where
  relevant to liver and aortic findings" plus a study-specific fourth branch, and the generator
  obeyed both. Runs 2–3 restated the three-tier rule and were clean. Fix: the sentence v3's
  POLICY already had — "COMPARISON names the prior study and its date and nothing else … interval
  change is stated in FINDINGS beside the lesion" — appended to the analyser's COMPARISON content
  rule (both variants, C1/C2) and to the global guide's Output Structure (G6).
- (b) Phase 7's opening convention ("governed by the clinical question, not the magnitude of
  positive findings") covered single-question studies only. Run 1's sheet ranked mesenteric
  ischaemia as *the* primary question, demoted the bleed to "secondary", and wrote "clinical
  answer to the primary question first"; the generator led with the negative. Runs 2–3 bundled
  the bleed into the primary hypothesis or ranked by acuity. Fix (O1/O2, both variants): any
  confirmed acute pathology opens the impression whichever question it answers; ranking among
  questions decides the opening only when every question is negative; output-format placeholder
  tightened to match.

Validation, same cell (`v1 medium + prune_v1`) ×3, `reasoning_q38_cerebras_on_on_medium_prune_v3/`:

| | L-36 cell | after L-37 |
|---|---|---|
| COMPARISON = study + date only | 2/3 | **3/3** ("Abdominal ultrasound, six months ago.") |
| impression opens on confirmed pathology | 2/3 | **3/3** |
| sheet opening convention says "index finding when any acute pathology is confirmed" | 0/3 | **3/3** |
| history in impression / tag labels / steatosis from prior | 0 / 0 / 0 | 0 / 0 / 0 |
| gate | 3/3 | 3/3 |
| sheet / report / e2e | 21.2k / 3.4k / 19.9s | 19.8k / 3.1k / 16.8s |

Watch list carried forward: colon/faecal loading dropped in 1/3 (the recurring pruned-cell
coverage wobble, now 2 drops in 9 pruned runs vs 0 in 6 unpruned); general surgical referral
for the duodenal pneumatosis 1/3; run 1 "haematology review for anticoagulation management"
names what the specialty should do; run 1 asserts "no pulmonary embolism" on a portal-venous
study — a sheet mandatory negative the modality cannot support, worth a rule that mandatory
negatives are bounded by modality non-assessables.

---

### L-38 · Ten varied CT/MR cases, two input tiers — structure holds 20/20; scanty input exposes the design question

**Verdict: the pruned v1 stack at medium generalises across modality and input quality on every
structural measure; two content rules still missing.** Confidence: moderate (n=1 per case, 20
runs, no judge, lexical screens + manual read of impressions).

Suites (`test_cases/varied_10.json`, `varied_10_mixed.json`; outputs
`test_output/VARIED10_q38_medium_prune/`, `VARIED10MIX_q38_medium_prune/`): CT head haemorrhage,
CT thorax nodule, CTPA with RV strain, CT trauma pan-scan, CT pancreatic staging, CT AP
diverticulitis abscess, MRI brain mets, MRI whole spine MSCC, MRI lumbar disc, MRI ankle. Mixed
suite: 4 scanty (positives only, terse, negatives stripped — pure reductions), 3 fuller (prose
with conventional negatives added — synthetic, flagged for review), 3 unchanged.

| measure | orig 10 | mixed 10 |
|---|---|---|
| gate | 10/10 | 10/10 |
| four sections, no extras | 10/10 | 10/10 |
| tag labels | 0 | 0 |
| history in impression | 0 | 0 |
| COMPARISON study/date only | 10/10 | 9/10 (thorax scanty: "recent chest radiograph" — from the referral, not the dictation) |
| impression opens on confirmed finding | 10/10 | 10/10 |
| dictated mm/cm values carried | all | all |
| mean wall | 15s | 17s |
| mean sheet | 16.4k | 16.0k |

- **Scanty input → full report by design.** Trauma scanty asserts cervical spine, aorta, solid
  organs, bladder, haemothorax as clear; none dictated. This is the canonical default-normal
  mechanism (silence = normal) doing exactly what v1 specifies. Product decision, not a prompt
  defect: does a radiologist signing from bullets want the systems review written for them?
- **Fabricated and incorrect classification**: lung-nodule orig impression "cT2aN2M0" — not
  dictated, and 22 mm is T1c. v1 stack has no "no staging/grading tier unless dictated or
  mapped from dictated features" rule; GENERATOR_V2 §1 had one. → one-sentence edit to the
  global guide's Data Authority.
- **COMPARISON from the referral** (1/20): needs "a prior counts only when the dictation names
  it" at the L-37 site.
- Remit-boundary recommendations (colonoscopy at 6 weeks, malignancy screen post-PE, Doppler):
  within scope as guideline next steps; read with the scope rule in mind.

---

### L-39 · Three phrasings dissected and closed: concordance sentence (mine), invented trauma MDT, fabricated TNM

**Verdict: all three traced to instruction text and closed; 12 recheck runs clean on each.**
Confidence: moderate (recheck n=2 per case on the four affected cases; no judge).

- **"Findings sufficient to account for the presentation"** — introduced by the L-36 edit
  itself: the replacement paragraph quoted the phrase as an example of stating concordance
  "against the imaging", in both analyser variants and the global guide. A quoted phrase in an
  instruction is a sanctioned string; 2/17 suite reports copied it. Hassan: concordance
  statements never belong in a report. Fix (P1, ×3 sites): "The impression answers the question
  asked; it never comments on whether the findings explain the presentation." Recheck 0/12.
- **"Trauma MDT for polytrauma involving five compartments"** — two causes. The recommendation
  scope's closed tag set has an `MDT:` slot and the output format asks for tagged entries with no
  statement that the slot may be empty, so the analyser filled it on a trauma sheet; and it
  wrote the trigger in sheet-internal vocabulary ("≥3 compartments"), which the generator quoted
  as justification. First fix (P2/P3: MDT must exist; never justify in sheet vocabulary) removed
  the vocabulary leak (0/8) but not the MDT (2/4 trauma reports): the model believes a trauma MDT
  exists. Second fix, a property not a list (P4, analyser ×2 + guide): an MDT is a scheduled
  planning forum and is never recommended on an acute or emergency study, where coordination is
  by referral. Recheck: trauma MDT in reports 0/4 (one sheet wrote "Not applicable for acute
  trauma"); oncology MDTs on lung / brain cases unchanged and correct.
- **"cT2aN2M0"** on the lung nodule (not dictated; 22 mm is T1c). No v1 rule forbade assigning a
  classification tier; the sheet's Guideline hooks offered TNM "as vocabulary". Fix (C1 guide
  Data Authority; C2 analyser Guideline hooks ×2): no staging/grading/classification tier unless
  dictated or mapped explicitly by Measurement Conventions. Recheck 0/2 (dictated "Grade III"
  splenic laceration correctly retained).

Edits this entry: 9, exact-match asserted, 232 tests pass. Outputs `RECHECK4_q38_medium_prune/`,
`RECHECK_TRAUMA_q38_medium_prune/`.

Watch: "Clinical observation with serial neurological assessment" / "serial neurological
observation" in 2/8 trauma-original runs — clinical monitoring, already prohibited in the guide's
Recommendations prose. Candidate countable fix: a VERIFICATION line "no recommendation for
clinical monitoring, observation, treatment or drugs". Not applied.

---

### L-40 · Production swap — quick-report pipeline on Qwen 3.8 27B / Cerebras / medium / prune_v1; v2 and v3 deleted

**Status: on branch `skill-sheet-v3`, uncommitted, smoke-tested through the production entry
points.** Decision by Hassan 2026-09-24 after L-33..L-39.

Config (`enhancement_utils.MODEL_CONFIG`, `quick_report_api.GENERATOR_MODEL`):

| role | before | after | fallback (declared, not yet consulted by the routes) |
|---|---|---|---|
| QUICK_REPORT_ANALYZER_FAST (production lane) | qwen/qwen3.6-27b (Groq) | **qwen-3.8-27b** (Cerebras) | qwen/qwen3.6-27b |
| QUICK_REPORT_ANALYZER_BEST (parallel lane, off) | claude-haiku-4-5 | **qwen-3.8-27b** | claude-haiku-4-5 |
| TEMPLATE_REPORT_GENERATOR + GENERATOR_MODEL | qwen/qwen3.6-27b (Groq) | **qwen-3.8-27b** | qwen/qwen3.6-27b |

Settings, keyed on `model_name == "qwen-3.8-27b"` inside the existing Cerebras branches so
gpt-oss is untouched: analyser temperature 0.5 / top_p 0.95 / **max_tokens 65536 /
extra_body reasoning_effort medium**; generator temperature 0.8 / top_p 0.95 / same cap and
effort. `generate_ephemeral_skill_sheet(directives=None)` now means
`PRODUCTION_DIRECTIVES = ("prune_v1",)`; `analyser_prompt_version()` hashes with them, so the
stored prompt version changes (now `3d85a1c0bc3b` for qwen-3.8-27b). Harnesses passing an
explicit tuple are unaffected; `reasoning_matrix` without `--directive` now mirrors production.

Deleted (git rm; history retains them): `report_v2.py`, `report_v3_policy.py`,
`sheet_budget/v2_run.py`, `sheet_budget/report_checks.py`, `tests/test_report_v2.py`,
`tests/test_report_v3.py`, `tests/test_report_checks.py`, the v3 plan and design spec, the
open-arm spec, `sheet_budget/policy_run.py`. No remaining imports. Suite 204 passed (was 232;
the 28 removed were the v2/v3 tests). `test_qwen_migration.KNOWN_CEREBRAS_DEBT` lists the three
quick-report roles as deliberate.

Smoke through the production functions with no overrides (ct_tap): analyser 8.9s, sheet
20,831 ch, "Contrast: Per dictation", no clause rules / canonical list / must-appear; generator
9.3s, gate pass, COMPARISON "Abdominal ultrasound, 6 months prior.", impression opens on the
bleed, no history, no tags; **18.2s end to end** (production before: ~37–42s on Groq 3.6).

Not done here: Railway deploy; wiring the declared `_FALLBACK` roles into the quick-report
routes; the `_run_agent_with_model` Cerebras log still prints "reasoning_effort: NOT SET" because
it reads the top-level key while the honoured value is in extra_body (cosmetic).

---

### L-41 · Fallback wired — Groq `qwen/qwen3.8-27b` behind every quick-report role; Groq 3.6 retired from the registry

**Status: implemented and unit-tested; live Groq validation blocked on the console.** Decision by
Hassan 2026-09-24.

- `MODEL_PROVIDERS`: `qwen/qwen3.6-27b` removed, `qwen/qwen3.8-27b` (Groq) added. Every reference
  in `src/` and `tests/` renamed mechanically (13 files), including the `prompt_manager` template
  mapping and `GROQ_REASONING_MODELS`, so the tuned report template still resolves for the Groq
  model (the L-23-era rename lesson).
- Fallbacks: `QUICK_REPORT_ANALYZER_FAST/BEST_FALLBACK` and `TEMPLATE_REPORT_GENERATOR_FALLBACK`
  all `qwen/qwen3.8-27b`. New `enhancement_utils._fallback_model_for(model)` resolves a primary to
  its declared fallback.
- Lookup is scoped to the quick-report roles (single hop): a direct Groq call that fails raises rather than inheriting CANVAS_PROCESS_FALLBACK (gpt-oss) — found by the live smoke, fixed, tested.
- Wiring: `generate_ephemeral_skill_sheet` now builds settings per attempt and retries once on
  the fallback when the primary raises, returning `fallback_from`; the skill-sheet-guided
  generator does the same around its report call (description sidecar is not re-run; a generic
  description is substituted). Every caller — /analyse, /generate inline analyser, the proto
  endpoint — inherits it.
- Groq settings for `qwen/qwen3.8-27b`: Groq's docs list `reasoning_effort` none/low/medium/high
  for this model (3.6 was binary) and a **16,384 output ceiling with reasoning counted**. The
  pruned analyser at medium averages ~18k output tokens (L-35), so the fallback runs at **low**
  (analyser max_tokens 16384; generator cap unchanged). Truncation on the fallback path is still
  possible on long cases; it is a degraded path by construction.
- Tests: `tests/test_quick_report_fallback.py` (5) stub the agent runner and assert call order,
  per-model settings and the recorded `fallback_from`. Suite 209 passed.
- **Blocked**: Groq returns 403 "model blocked at the project level" for `qwen/qwen3.8-27b` on
  this key. Enable it under Model Permissions in the Groq console; until then the fallback and
  every renamed non-quick-report Groq role (canvas, audit, planner, skill-sheet tools) will fail
  with that 403. Do not deploy before enabling.
- Primary path re-smoked after the refactor: Cerebras analyser 8–9s, `fallback_from=None`.
- **Live validation after Hassan enabled the model in the Groq console (same day):**

  | path | analyser | generator | e2e | gate | sheet | notes |
  |---|---|---|---|---|---|---|
  | Groq direct, ct_tap | 29.6s | 29.1s | 58.8s | pass | 14.1k, 9 sections, ends cleanly | four sections |
  | Groq direct, ct_head | 17.9s | 21.2s | 39.1s | pass | 13.8k, ends cleanly | four sections |
  | forced failover (Cerebras primary made to raise), ct_thorax nodule | 23.9s on Groq | on Groq | 40.3s | pass | 13.6k | both stages record `fallback_from=qwen-3.8-27b` |

  At `low` the analyser stays under Groq's 16,384 ceiling on all three cases (no `length`
  finishes); reports are shorter (1.1–2.5k ch vs 3–4k on the primary) — the expected shape of a
  degraded path. Groq at ~450 tps is 2–3× slower per stage than Cerebras at medium; e2e 40–60s
  vs ~18s. The blocker is cleared.

---

### L-42 · REGIONS macro-structure — headed regional blocks for multi-region protocols; FLAT everywhere else

**Verdict: works as specified; single-region studies unaffected.** Confidence: moderate (trauma
×6, TAP ×3, ten-case suite ×1; no judge).

Hassan's observation on the L-38 trauma report: findings ran spleen → lung → head → spine with no
map. Cause: v1's only structural rule is causal (Phase 3 "causal, not anatomical"; hardening 2
"never park a causal companion in a distant sweep paragraph"; hardening 6's unheaded flow), and
the global guide's `header: "[text]"` rendering hook was never emitted by the ephemeral analyser.
v2's COMPARTMENTS had the mechanism but applied it to the TAP, which is where it went wrong.

Six edits: Phase 3 + Output Format (both analyser variants) add a **Macro-structure**
declaration — FLAT by default; REGIONS only for a multi-region protocol read as separate
examinations, regions in render order (cranio-caudal, vertebral column its own region, soft
tissues/bones last), each marked `header: "<REGION>"`, causal clustering applied *within* a
region, priority across regions left to the impression, "when in doubt, FLAT". Hardening 2, 6
and 9 gain the within-region clause and the sub-heading layout. Global guide names region headers
as the sanctioned use of the header marking. Suite 210 passed.

| cell | sheet declares | report renders | impression opens | gate |
|---|---|---|---|---|
| trauma pan-scan ×3 (`REGIONS_check/`) | REGIONS 3/3 | HEAD / CERVICAL SPINE / CHEST / ABDOMEN / PELVIS (+BONES AND SOFT TISSUES 1/3) 3/3 | splenic laceration 3/3 | 3/3 |
| trauma scanty ×3 | REGIONS 3/3 | headers 2/3 (run 3's sheet copied the template's backtick syntax into the macro line and the generator rendered no headers) | splenic laceration 3/3 | 3/3 |
| GDA bleed TAP ×3 | **FLAT 3/3** | none | active extravasation 3/3 | 3/3 |
| ten-case mixed suite ×1 (`VARIED10MIX_regions/`) | REGIONS only on the pan-scan; FLAT 9/9 | headers only on the pan-scan | — | 10/10 |

Trauma run 1 reads as a regional map with the impression prioritised by acuity (spleen → chest →
pelvis/L1 → SDH → negatives). Watch: the L1 endplate fracture landed under ABDOMEN in 2/3 rather
than a spine region (the rule says the vertebral column is its own region; the sheets gave only
CERVICAL SPINE); one scanty sheet leaked the template's backtick syntax into its macro line
(1/6) — a placeholder-fidelity wobble, not a design fault.

---

### L-43 · REGIONS on five further multi-region CT/MR protocols — criterion right 3/5, one clear miss, one classification leak

**Verdict: the macro-structure rule generalises, with two edits indicated.** Confidence: low-moderate
(one pass, four synthetic dictations authored for this test, `test_cases/multiregion_5.json`,
outputs `test_output/MULTIREGION5/`).

| case | sheet | report headers | impression opens | gate |
|---|---|---|---|---|
| CT head + cervical spine (fall, anticoagulated) | REGIONS | HEAD / CERVICAL SPINE | SDH | pass |
| CT NCAP lymphoma staging | FLAT | none — disease-organised: all nodal stations in one paragraph, then organs | "Stage IVB classical Hodgkin lymphoma" | pass |
| MRI brain + whole spine (query demyelination) | FLAT | none — FINDINGS opened on the **cord**, then brain, then optic nerve | demyelination | pass |
| CT aortogram + lower-limb run-off | REGIONS | THORAX / ABDOMEN / PELVIS / BILATERAL LOWER LIMBS | SFA occlusion | pass |
| CT TAVI | FLAT | none | valve calcification | pass |

- Head + c-spine and run-off are exactly what the rule is for; TAVI correctly FLAT; NCAP FLAT is
  defensible (a disease-organised staging read) though a radiologist may prefer regions.
- **Miss: MRI brain + whole spine went FLAT** and the causal rule then led with the cord lesions
  before the brain. Brain and spine are separate acquisitions read as separate examinations; the
  analyser read "one disease across two regions" as one field. Edit: the REGIONS test is whether
  the regions were acquired as separate examinations, not whether one disease spans them.
- **Classification leak via the exception**: "Stage IVB" was never dictated. The L-39 rule allows
  a tier "the sheet's Measurement Conventions map dictated features to"; the sheet carried Ann
  Arbor/Lugano and the generator staged — and the "B" came from history (night sweats, weight
  loss), which is banned outright. Edit: remove the mapping exception; no stage or grade unless
  dictated.
- Scope wobbles (1/5 each): "coagulation status and anticoagulant level should be assessed to
  inform haemorrhage management" (head + c-spine: management + history); serology and CSF
  recommendations on the MRI case (laboratory direction, borderline).
- Structure otherwise held: gate 5/5, four sections, no tags, COMPARISON date-only 5/5.

---

### L-44 · Separate acquisitions are REGIONS; no stage unless dictated — the prose rule lost, the countable one won

**Verdict: both L-43 edits hold, after the staging rule was moved to countable sites.** Confidence:
moderate (two cases ×3, `test_output/L44_check/` then `L44_check2/`).

**Edit 1** (Phase 3, both variants): the REGIONS test is whether regions were acquired as separate
examinations, not whether one disease spans them. MRI brain + whole spine: FLAT 1/1 before →
REGIONS 2/3 after the first pass → **3/3** on the second, BRAIN / SPINE blocks, FINDINGS opening
on BRAIN (it had opened on the cord). NCAP also moved to NECK / CHEST / ABDOMEN / PELVIS 3/3.

**Edit 2, first attempt — failed.** Hassan asked whether the two staged reports had drawn their
tier from a verifiable sheet mapping. Audit of all 16 output folders: 2 stages ever assigned, 0
correct. NCAP "Stage IVB": the sheet's own Lugano rule listed the spleen as *extranodal* (it is
lymphoid → stage III), and "B" came from history. Lung nodule "cT2aN2M0": no T thresholds in the
sheet at all; staged from memory; 22 mm is T1c. So the exception ("sheet maps dictated features
to a tier") was removed from the global guide and both analyser guideline-hook lines. Rerun: NCAP
still staged **3/3** (III correct once, IV twice; one "IVB"). The history says "Staging", so
"answer the question asked" beat a prose prohibition — L-03/L-18 again.

**Edit 2, second attempt — held.** Four countable/at-source edits: (a) the Phase 2 example that
taught the sheet to frame the gate as "stage per applicable system to guide MDT treatment
planning" now reads "map nodal and extranodal extent and bulk so the MDT can stage"; (b) the
output-format terminology placeholder says a tier is never impression-permitted unless dictated;
(c) a VERIFICATION_CHECKLIST line: no staging/grading/classification tier anywhere unless
dictated — a staging question is answered by describing extent and bulk; (d) PRE_WRITING step 4
plans it. Rerun: **stage in report 0/3**; impressions describe distribution above and below the
diaphragm, splenic involvement, bulk and negatives, and recommend PET-CT and the lymphoma MDT.
Sheets still sketch a Lugano rule 3/3 (harmless now; the generator ignores it). MRI: "dissemination
in space/time" retained — a radiological criterion statement, not a stage; acceptable.

Decision recorded: staging from an ephemeral, analyser-written mapping is not a verifiable source;
if staging-from-imaging is wanted later it needs a curated, reviewed threshold table, not a
generated one. Suite 210 passed. 12 edits this entry (L-43 follow-through).

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

### L-45 · Negatives keyed by reported finding — coverage check (gate), 2026-09-29

Spec `docs/superpowers/specs/2026-09-29-policy1-confirmed-branch-negatives-design.md` (rev 2),
branch `feat/confirmed-negatives`. Trigger: prod report 064ff6f1 (jaundice, pancreatic head
mass) omitted every resectability negative.

**Rev 1 (branch-keyed) failed on first contact:** arm B, 8 cases, 0 stated anywhere. Jev scored
the diagnosis branch 0.68 (pancreatic adenocarcinoma) and 0.35 (lung carcinoma), which is
correct because imaging reports findings, not diagnoses. The main finding (haemorrhage, PE,
vertebral metastases) is the primary hypothesis, not an aetiology line. Branch names matched
0/4 on the cerebellar case.

**Rev 2 coverage** (directive `finding_negatives`, Jev "reports this imaging finding"), one
sheet per case:

| Set | Main finding keyed ≥0.5 | Notes |
|---|---|---|
| silent_staging (6) | 5/6 | MSCC miss 0.10: key "vertebral body lesion *with epidural extension*" too specific |
| varied_10 (10) | 10/10 | lowest 0.86 (disc extrusion) |
| controls (2) | 0 false triggers | max 0.03 |
| **Total** | **15/16 = 94%** (target ≥90%) | |

**Calibration** (clear vs hedged restatements of the same findings): clear 0.86–0.99; hedged
0.16 (pancreas), 0.72 (lung "nodule versus vessel"), 0.16 (cerebellar). `PRESENT_HIGH = 0.8`
sits in the gap. n is small (3 hedged), so re-check on the A/B.

**Negatives quality (by hand):**
- **Good:** pancreas (PV/SMV encasement, distant deposits; core); cerebellar haemorrhage in
  varied_10 (fourth ventricle, hydrocephalus; core); PE (contralateral filling defect);
  trauma (flail segment); pancreatic staging (coeliac/SMV encasement).
- **Varies between sheets for the same finding:** silent cerebellar got only contextual,
  off-target negatives ("no surrounding mass lesion") where varied_10 got the core ones.
  Silent lung got no core negatives at all.
- **Inferential or odd:** "No features of underlying colonic malignancy"; "No feeding vessel
  from the pulmonary artery".
- **Contradicted by the dictation:** brain metastases "No haemorrhagic component" beside a
  dictated haemorrhage; MSCC "No epidural extension" beside dictated epidural disease. The
  Qwen check must catch these, which makes it load-bearing.
- **One bundled negative** ("…dilatation or interventricular septal bowing") despite the
  one-finding rule.

**Gate:** the link passes (coverage and false triggers). Whether the negatives are good enough
is left to the A/B and the hand read, with the Qwen check as the safety net.

**L-45 A/B predictions** (written 2026-09-29 before any A/B run; the brief is rev 2 with the fallback):

| Measure | A | B |
|---|---|---|
| Silent (6): ≥1 finding-linked negative stated in FINDINGS | ~0/6 | ≥5/6 cases in the majority of runs |
| Report negative contradicting the dictation | 0 | 0 |
| Expected-consequence negative anywhere | n/a | 0 |
| Negatives in the impression | as generator does today | median ≤1 per case, each changing interpretation |
| Offered finding negatives per silent case (median) | 0 | 1–2 |
| Hedged (3): stated finding negatives | 0 | 0 (offered at most) |
| Controls (2): new negatives or options | 0 | 0 |
| Regression gate (varied_10) | 100% | 100% |
| Analyser median latency | baseline | within +1.5 s |
| Brief reconcile median | baseline | within +0.5 s (fallback in parallel) |

Smoke before the A/B (prod case, 1 run): SMA/PV encasement and hepatic deposits stated. Watch
for: one bundled negative ("SMA or portal vein encasement"); the fallback misjudging coverage
for the "CBD compression" line; the generator carrying negatives into the impression despite
`carry_negatives=[]`.

**L-45 A/B results** (2026-09-29). Arm B: silent_staging × 2 runs (22) + varied_10 × 1 (10).
Arm A: not re-run in full. Production sheets carry no If-present list, so A states none of
these negatives by construction; prod report 064ff6f1 is the real-case A. A was run on the three
cases where B lost a section (6 runs). Run count cut from 3 to 2, reusing existing outputs
(Hassan).

| Prediction | Predicted (B) | Observed (B) | |
|---|---|---|---|
| Silent: ≥1 negative stated in FINDINGS | ≥5/6 cases, majority of runs | **5/6 in ≥1 run; 3/6 in both runs** (pancreas 2/2, lung 2/2, diverticulitis 2/2, cerebellar 1/2, PE 1/2, MSCC 0/2) | partly contradicted |
| Contradicting negative in a report | 0 | **0** (by hand). Qwen dropped every contradicted candidate: varied_10 PE RV dilatation, diverticulitis collection, brain-mets haemorrhage, MSCC epidural | held |
| Expected-consequence negative anywhere | 0 | 0 | held |
| Stated negatives in the impression | only when carried | 2 of 32 leaked uncarried (lung atelectasis, diverticulitis obstruction); carried ones (diverticulitis "no abscess/perforation", lung contralateral nodes) change the interpretation | mostly held |
| Offered per silent case (median) | 1–2 | 1.5 | held |
| Hedged: stated | 0 | **0/6** (offered 0–3) | held |
| Controls: new negatives or options | 0 | **0/4** | held |
| Regression gate | 100% | **29/32**: 3 missing TECHNIQUE (cerebellar ×2, diverticulitis ×1). Their sheets' Sections line omits it. A 0/7 sheets, prod 0/10 in the last 10 days vs B 2/33 sheets | **contradicted: likely directive side effect** |
| Analyser median | within +1.5 s | 11.0 s (silent), 10.3 s (varied); two outliers of 68/74 s under 2-stream load | held (no A median to compare) |
| Brief median | within +0.5 s | 1.5 s (silent), 2.5 s (varied); one 10.3 s plan timeout under load | held |

**Quality notes:**
- The pancreas case is fixed: SMA, SMV and PV encasement plus hepatic deposits stated in 2/2
  runs, and the impression says "No vascular encasement".
- Several stated negatives are **bundled** ("SMV *or* portal vein encasement"). The directive's
  one-finding rule is not always followed, and `_split_bundled` covers only mandatory
  negatives.
- **MSCC key misses** in both runs (as in the coverage check): the negatives were only offered.
- Some offered items are weak or odd ("No liver dome lesion", "No hemothorax", US spelling).
  They are offered only, and hidden until the side panel exists.

**Bugs found and fixed during the run:**
- A negative under two keys was stated twice (e.g. diverticulitis);
- passed-through options started lowercase;
- **the fallback ran on production sheets** (A offered 3–4 per case), now gated on an
  If-present list;
- the plan prompt changed with the directive off, now conditional.

Production's report path is now unchanged until `finding_negatives` joins
`PRODUCTION_DIRECTIVES`.

**Open before sign-off:**
1. The TECHNIQUE drop (about 8% of B sheets).
2. Bundled stated negatives: extend `_split_bundled` to candidates.
3. MSCC-type misses, where the key is too specific.

**L-45 rerun after three fixes** (c18a97f; arm B silent_staging × 2 + varied_10 × 1 = 32).
The fixes:
- one finding per key;
- finding-linked negatives through `_split_bundled`;
- the directive states it leaves the Sections line alone.

| Measure | Before | After |
|---|---|---|
| Sheets without TECHNIQUE in Sections | 2/32 | **0/32** |
| Gate | 29/32 | **32/32** |
| Bundled stated negatives | 6 | **0** |
| Compound keys (with/and/or) | 25 | 16 |
| Silent: ≥1 negative stated in FINDINGS, both runs (by hand) | 3/6 | **4/6** (pancreas, lung, cerebellar, PE) |
| Silent: in ≥1 run | 5/6 | 5/6 (diverticulitis 1/2: key negatives tagged contextual, so offered; MSCC 0/2) |
| Hedged stated / controls new | 0 / 0 | 0 / 0 |
| Analyser / brief median | 10.7 s / 1.8 s | 11.0 s / 1.9 s |

**Still open:**
1. **Content variance on the case that started this.** Pancreas run 1's If-present list for
   "pancreatic head mass" gave peritoneal studding, nodes and splenic vein thrombus, not
   SMA/SMV contact. Vascular negatives were stated in 4/5 arm-B runs of this case across the
   day. The cap of three per finding forces a choice, and the analyser does not always pick the
   management-deciding one.
2. **MSCC keys.** One key was compound ("…deposit *with collapse*"); one was written as a sign
   rather than dictation vocabulary ("vertebral body marrow replacement", 0.33).
3. **The fallback is unsafe as built.** 4/43 fallback negatives contradict the dictation, plus
   1 borderline:
   - "No intra-/extrahepatic biliary duct dilatation" beside dictated dilatation;
   - "No interventricular septal bowing" beside dictated septal flattening;
   - "No SMV … encasement" beside dictated 190° SMV contact;
   - borderline: "No brainstem compression" beside marked cerebellar oedema.

   It is parallel by design, so its output never passes the Qwen contradiction check. It is
   unsplit ("or" bundles) and misjudges coverage (attached to keyed findings). The items are
   offered only and hidden in the UI, but they must not reach the side panel like this.

### L-46 · Post-generation quality check — can Jev do it? (probe, 2026-09-30)

Proposal (Hassan): a lightweight catch-all check after every report, so a good report ships
first time. Probe scripts: `backend/src/rapid_reports_ai/scripts/jev_quality_probe*.py`, run on
the 32 L-45 rerun reports.
- **Negative class:** real clauses and items as generated. They were hand-read on L-45 and are
  consistent.
- **Positive class:**
  - the 4 real fallback contradictions;
  - synthetic flips (a dictated item negated);
  - deleted sentences;
  - inserted history, fabrications and concordance lines.

Jev latency: 0.28 s median per call, ≤11 questions.

| Question (state) | Result | Verdict |
|---|---|---|
| "The dictated findings state something that this report statement denies or contradicts" (dictation) | **31/31** contradictions caught at 0.5 (4 real fallback ones 0.75–0.86); 4/127 clean clauses flagged, 2 of them clause-splitter artefacts ("No pericolic") and 2 defensible ("no epidural collection" beside epidural disease) | **fold in** |
| "The report states this dictated finding" (report) | **24/24** deleted findings caught; 3/68 present items missed, all dictated negatives or background lines | **fold in**, positive dictated items only |
| "The impression mentions this finding" (impression) | deleted 43/43 caught, but present items recognised only 22/43: the impression synthesises at diagnosis level, Jev matches literally | **not reliable** as phrased |
| History restated (history) | 8/32 | **fails**: use code (history tokens in report but not dictation) |
| Undictated abnormal finding (dictation) | 5/32 and 49 false alarms | **fails**: stays with prompt + Phase 1 audit |
| Concordance / attribution (history) | 12/32 and 21 false alarms | **fails**: use a code regex on the L-39 constructions |

**Conclusion:**
- **Jev reliably does two things:**
  - **contradiction per clause**, which also screens offered options;
  - **omission of a dictated positive finding.**

  The "report states X" form also covers DO NOT ASSERT / OMIT compliance (not separately probed).
- **Code checks** fold into the same step at no cost:
  - `gate.py` into prod: sections, tag leak, thinking leak, truncation, self-contradiction;
  - staging / grade / RADS tier not dictated (L-44; "AAST grade III" seen in L-45);
  - measurement values not in the dictation;
  - history-token leak (L-36);
  - L-39 concordance phrasing.
- **Not foldable:** impression completeness as phrased, fabricated descriptors, and clinical
  judgement (recommendations, characterisation, flagging).

### L-47 · Post-generation check (Jev flags, focal repair): offline evaluation, 2026-09-30

Spec `docs/superpowers/specs/2026-09-30-post-generation-check-design.md`, branch
`feat/post-generation-check` (on `feat/confirmed-negatives`). Eval
`scripts/quality_check_eval.py`:
- the 32 L-45 rerun reports as generated (clean);
- plus one perturbed copy each: 14 contradictions injected (a dictated finding negated), 11
  findings deleted;
- plus the 4 known-bad fallback options on their cases.

**The first build failed the pass bar dangerously.** Two false-flagged negatives were
"corrected" by Qwen into the malignant findings they denied: "No focal mass-like colonic wall
thickening is identified" became "Focal mass-like colonic wall thickening is identified."
Fixes, each found on hand read and each tested:
1. A flagged **negative** is removed in code (a list item dropped or the sentence deleted),
   never by the LLM. A false flag can only lose a negative, never create a finding.
2. `edit_allowed` rejects any edit that drops a negation.
3. **Omissions** are inserted by code after an anchor Qwen picks. Asked for insert-only edits,
   Qwen rewrote the neighbouring sentence (omissions fixed 5/11).
4. A negative is removed only when a **second Jev question in the same call** confirms the
   denied finding is dictated. This cut false negative-removals from 3 to 1.
5. **Duplicate guard:** skip an insertion that restates a report sentence (80% of words, every
   number, filler words ignored). It stopped a reworded finding and an existing nodule being
   re-inserted.

**Final** (0f2e28f):

| Measure | Result | Bar |
|---|---|---|
| Injected contradictions fixed | **14/14** | ≥90% |
| Deleted findings restored, where the finding was absent from the whole report | **7/7**. The 4 unrepaired omissions all still had the finding in the impression (2 not flagged; 2 insertions correctly refused as duplicates) | ≥90% |
| Known-bad options dropped | **6/6** (+6 other options dropped, all plausible: "No acute hydrocephalus" beside dictated aqueduct effacement, …) | — |
| Clean reports edited | 5/32, by hand: 4 correct ("encasement" → dictated "abutting … no occlusion"; "no focal abdominal lesion" removed beside a dictated hypodensity; herniation negative removed beside dictated herniation; "no other parenchymal abnormality" removed beside a dictated opacity), **1 correct negative lost** ("No focal mass-like colonic wall thickening", diverticulitis) | 0 damaging: **1 near miss** |
| Fabricated or inverted findings | **0** | 0 |
| Added latency | median 0.37 s, max 0.74 s (repair included when flagged) | ≤0.8 s |

**Residual risk:** a Jev false flag on a negative whose denied finding shares words with a
dictated one ("focal mass-like wall thickening" vs "segmental wall thickening") can remove that
negative. It fails safe: the report loses one negative and asserts nothing new.

**L-45 step: order by consequence, cap 4** (6c9f432; post-generation check on). Pancreas case
× 5, plus the silent basket × 1 for regression. One earlier parallel run was lost to an output
filename collision (fixed: pid in the name).
- **Vascular negative stated in FINDINGS: 4/5**, unchanged from 4/5 before the change.
- **The miss (run 3):** the sheet listed no vessel at all. Its four negatives were stricture,
  duct dilatation, nodes and peritoneal deposits. The cap was not the limit; what gets
  anticipated varies between sheets.
- **Hits are partial:** SMV only, SMA only, or SMV + PV. None gave the full resectability set
  (SMA, SMV, PV, coeliac).
- **Basket regression:** gate 11/11; controls and hedged stated 0.

### L-48 · Negatives out of the quick-report impression by default, 2026-09-30

Trigger (Hassan, before/after review): impressions read as lists of absent findings. The
evidence says this was **pre-existing**:
- the finding-negatives plan carried none;
- production arm A listed them too;
- 7 of the last 11 prod impressions had a negative sentence.

The fix (0871db9) is quick reports only, made at the sites that taught the lists:
- a countable checklist rule (at most one negative: the answer when nothing positive answers
  the question, or one clause that changes the next step; never a list);
- hardening principle 10 no longer lists negatives as an impression obligation;
- analyser, both copies: the opening convention, the normal exemplar, and excluded triage
  differentials;
- the impression plan carries at most one negative, and the finding-negatives carry path is
  removed.

**Rerun, impressions before → after:**

| Case | Before | After |
|---|---|---|
| PE | "Aortic dissection, pneumothorax, pericardial effusion, pleural effusion, and pulmonary consolidation are excluded" | clean |
| Diverticulitis | "No pericolic abscess or free perforation. No colonic mass lesion. No adnexal abnormality" | "Acute sigmoid diverticulitis, uncomplicated." |
| Controls | — | still "No acute intracranial abnormality" / "No acute intra-abdominal or pelvic abnormality identified" |
| PE with RV strain, diverticulitis with abscess, trauma | — | positives that change management kept |

**Residual:** some impressions still carry one negative sentence joining two items ("No distant
metastatic or peritoneal disease"); one abscess case lost "No free perforation". Gate 17/17.

**Tag parser bug found on the same rerun** (b9cf3c3): annotated tags ("(core — resectability, …)",
"(peritonitis) (core)") parsed as contextual. Earlier arm-B runs under-stated core negatives
because of it. After the fix, pancreas × 5:
- **vascular negative in FINDINGS 4/5**, still missing from one sheet's anticipated list;
- run 1 states the full set (no SMA, SMV or portal vein encasement).

### L-49 · Jev wording v2 — quick path (questions, thresholds, Jev in place of word overlap), 2026-10-01

Plan `docs/superpowers/plans/2026-10-01-jev-wording-v2.md`, Part Q. Branch `fix/quick-split-and-classifier`.
Evidence: the wording suite in the session scratchpad, `jev_wording_suite/{A_already_said, B_presence,
C_contradiction, D_conditions, E_sheet_regex}/` (run.py / arms.py / analysis_*.txt per group; DEV and
HOLDOUT splits, two runs each). Production re-score: `jev_v2_rescore/run_67723/{summary,changed,handread}.md`.

| Question | Old | New | Threshold | Suite evidence |
|---|---|---|---|---|
| Omission (quality check) | "The report states this dictated finding, in any wording: " over positive items only (`_BACKGROUND` filter) | `Q_CONVEYS` "The report itself states everything this statement says, in any wording, abbreviation or synonym (not merely implied or inferable): " over **every** dictated item | flag < 0.40 (was < 0.5) | A/S2: stated ≥ 0.51, omitted ≤ 0.31 |
| Inserter duplicate guard | `_restates` word overlap | Jev `Q_CONVEYS` on the report; `_restates` is the fallback when Jev fails | skip ≥ 0.25 | A: conveyed ≥ 0.32, new ≤ 0.14 |
| Inserted negative | any negation allowed when any omitted item had negation | `_negative_allowed`: only when an omitted negated item shares a content word | — | user decision 1 (**reversed**, below) |
| If-present finding presence | noul "report this imaging finding, in any wording or size" | score, 4 levels (absent / not mentioned / possible / present), read as level / 3 | route_finding cut-offs unchanged (0.5 / 0.8) | B |
| Branch presence | "A dictated finding shows that this diagnosis or branch is present" + whole line | names the diagnosis; the discriminator is "an example only; it need not be dictated"; `PRESENT_TRUE/FALSE` criteria | 0.5 | B R3 (R2 without discriminator) |
| Removal confirmation | "The dictated findings report this finding: " | "…, including as a possibility: " + criteria (different qualifier = false) | 0.5 | B S1 |
| Recommendation condition | "condition … is not met" (unmet polarity) | `Q_REC_MET` met polarity; unmet = 1 − score | unmet ≥ 0.5 removes | D R2 |
| Negatives the findings make untrue (Q7) | Qwen label only | ~~Jev choice OR'd onto a Qwen keep~~ — **removed** (d790657, reverts 0b985a7) | — | C ECH, n = 50, directional; failed in production |

User decisions (2026-10-01): (1) omitted dictated negatives are inserted back — restores dictated content,
never turns a negative into a finding; (2) "organ unremarkable" does not make a specific negative option a
repeat. **Decision 1 was reversed after the re-score below** (see "Decisions after the re-score").

**Production re-score (Q9), 150 most recent prod quick reports (2026-04-19 → 2026-10-01), Jev on the same
inputs, no regeneration.** Only 3 of the 150 have a compiled brief / quality telemetry and only 3 sheets
carry an If-present list (168 quick reports exist in prod in total), so old and new were both recomputed
from dictation + sheet + stored report. Changed decisions, hand-read verdict (better / neutral / worse):

| Question | Changes | Better | Neutral | Worse |
|---|---|---|---|---|
| Omission: old flag → conveyed | 63 | 63 | 0 | 0 |
| Omission: newly flagged (normals / negatives), stored report present | 150 | 78 inserted correctly | 53 (51 not inserted, 2 positives already present) | **19 inserted** |
| Restated (removal confirmation) | 7 | 4 | 1 | 2 |
| Branch presence (label only: no change reaches removed) | 22 | 9 | 8 | 5 |
| Recommendation (Jev removal) | 15 | 12 | 3 | 0 |
| If-present bands | 0 of 9 keys | — | — | — |
| Q7 OR | 118 | 10 | 6 | **102** |

The 19 worse insertions: 15 context-lost negatives (side, level or knee dropped: "No calculi or
hydronephrosis" beside a left ureteric calculus; "No spinal canal stenosis" beside L4–5 stenosis; "No
articular defect" from the other knee), 1 dictation typo inserted ("kidneys … obstructed"), 3 duplicates the
Jev guard scored < 0.25 ("No vertebral body fractures" in two 3.4 k-character reports; a conclusion line).
A probe on the would-insert sentences (report state, noul "This sentence, added to the report, conflicts with
what the report already states") scored all 19 at ≥ 0.64 and the correct new insertions mostly ≤ 0.3
(`jev_v2_rescore/contra_gate.json`). Not built: decision 1 was reversed instead.

**Q7 failed.** 93 of its 118 changes are "expected", and all 93 are wrong: on normal studies
(CT head "No acute intracranial haemorrhage", normal knee "No ACL tear", normal CTA "No large vessel
occlusion") Jev chose `expected` for negatives the dictation states, i.e. it read the criterion as "this
negative is expected" — a polarity inversion inside a choice criterion. The contradicted escalations are
10 better / 6 neutral / 9 worse.

**Decisions after the re-score (Hassan, 2026-10-01):**
1. **Decision 1 reversed.** Dictated negatives and normals are never omission-checked or inserted, as in
   L-46. Why: the dictation splitter loses a negative's scope (side, level, knee, structure), so a restored
   negative reads as a global denial — 15 of the 19 worse insertions contradicted the report ("No calculi
   or hydronephrosis" beside a left ureteric calculus; "No spinal canal stenosis" beside L4–5 stenosis;
   "No articular defect" from the other knee). A Jev selector (abnormal findings, limitations, mixed lines)
   will choose the checked items; until it lands, Q1's every-item check stays in the code. No conflict gate.
2. **Q7 removed** (d790657): `RR_NEG_JEV_OR`, `q_negative_relation`, `decisions["negative_or"]` and their
   tests. Why: the `expected` criterion is read inverted on normal studies (93/93 wrong, DO NOT ASSERT "No
   acute intracranial haemorrhage" on a normal CT head); `contradicted` alone is near break-even (10 / 6 / 9).
3. **Q3 kept** (If-present score / 3) on the suite evidence: production cannot validate it yet (3 sheets
   with an If-present list, 9 keys, no band changed).

Lessons:
- **Polarity** (group D and Q7): a question's instructions and its criteria must point the same way; a
  choice criterion that names a cause and a denial ("would cause what the negative denies") is read the
  other way round on normal studies. The n = 50 suite had no normal-study negatives; production did.
- **Drift**: run-to-run drift is small (mean ≈ 0.01, max 0.20 on E1), so thresholds sit in measured gaps,
  never on a single run's boundary.
- **Context**: the dictation splitter makes items context-free ("no oedema", "No calculi or hydronephrosis");
  restoring a negative needs its structure, side or level, or a conflict check against the report.
- **Report length** (open weakness): the conveys question under-scores items in long multi-region reports
  (0.1–0.2 for plainly stated negatives such as "No vertebral body fractures" against "No vertebral body,
  spinous process or transverse foramen fractures are identified" in 3.4 k-character reports). That raises
  false omission flags and weakens the 0.25 duplicate guard there (3 duplicates passed it). The selector
  removes the negatives from the check, but positive items in long reports keep this exposure.
