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
