# v1 by subtraction — the compromise cell

**Status:** approved in conversation 2026-09-24; cell 1 recorded as L-35; history-emission and tag-leak guardrails recorded as L-36 (24 edits); COMPARISON content and impression opening recorded as L-37 (5 edits); both validated 3/3.
**Ledger:** L-33 (Qwen 3.8 on Cerebras probe and baseline), L-34 (effort dial, arm C), L-35 reserved for this.
**Supersedes:** the v2 sheet grammar and §2 of `2026-08-22-skill-sheet-v3-design.md` (the four-purpose sheet). The open arm (`2026-08-23-open-arm-design.md`) is not run.

## 1. What changed

Qwen 3.8 27B is live on Cerebras (`qwen-3.8-27b`). Reasoning defaults to `high` and the
effort dial is graded. At `medium`, v1's full production prompt stack runs the GDA bleed
case in ~25 s end to end with reasoning on at both stages (L-34). The latency pressure that
drove v2 and v3 is gone, so the design question reverts to quality per token, not quality
per second.

## 2. What the evidence says

Read side by side on the same dictation (v1 medium run 1 against arm C medium run 1), v1
is better for reasons that trace to instruction text, not sampling:

1. **Causal index paragraph.** v1 Phase 3: structure is causal, not anatomical; P1
   collects the pathological story across compartments. ANALYSER_V2 forbids this once
   COMPARTMENTS is declared ("priority lives in the impression, never in block order"),
   and the model declares COMPARTMENTS on any multi-region scan name.
2. **Differential-targeted mandatory negatives**, atomic, quoted, never dropped. v2's
   T-NEG is one normal sentence per station; a partly abnormal station loses every
   negative in it (arm C run 1 has no perforation negative).
3. **History modifiers with management implications.** v2's CASE block is one line;
   arm C impressions omit anticoagulation and lactate on a bleed-on-apixaban case.
4. **Synthesis epistemics** (hardening preamble: four sanctioned moves, attribution
   proportioned to imaging evidence, risk articulation, deferral as an endpoint). POLICY
   reduces this to a lexicon; arm C attributed duodenal mural gas to adjacent haemorrhage
   and dropped the surgical referral.
5. **Impression exemplars carrying must-appear hooks.** The analyser prompt's own rule:
   prose is decorative, exemplars are load-bearing. v2 deleted exemplars.
6. **"Do not copy input phrasing verbatim."** Absent from POLICY; arm C transcribes.

Shared defects to fix regardless: steatosis asserted from the prior; "no mesenteric fat
stranding" beside dictated stranding; contrast phase inferred from the scan-type string.

## 3. Decision

- Discard the v2 OBLIGATIONS/T-NEG/COMPARTMENTS grammar and the v3 four-purpose sheet.
- Keep from v3: static per-stage system prompt with per-case content in the user message
  (prompt caching), the deterministic gate and section splitter, "a mis-scoped sheet can
  never delete a dictated finding".
- Rebuild by subtraction from v1's production prompts. Production path stays byte-identical;
  every change ships as an opt-in analyser directive until a radiologist signs it off.

## 4. Cell 1 — `prune_v1` directive, one variable

New named directive `prune_v1` in `quick_report_analyser.DIRECTIVES`, appended to the
open-weights analyser prompt. It cuts:

| section | change |
|---|---|
| Interpretive Clause Rules | omitted |
| Style Exemplars | one variant (abnormal, uncomplicated), ≤4 findings |
| Canonical default-normal lines | omitted; Normal-study path is the single source |
| Measurement Conventions | ≤3 entries |
| Modality non-assessables, Out of scope | ≤3 entries each |
| Clinical history modifiers | every item kept, one line each with management implication |

And fixes two defects at the sheet level:

- contrast and phase are never inferred; "Contrast: per dictation" when the scan-type name
  does not state them, and the Normal-study path / negatives / TECHNIQUE hold either way;
- no canonical line asserts a finding the history reports.

Unchanged: Clinical Lane, Structural Pattern, Companion Matrix and mandatory negatives,
Terminology Rules, Conditional Suppression Rules, Impression Exemplars, must-appear hooks.
The generator stack (global guide, hardening preamble, pre-writing analysis, verification)
is untouched in this cell.

Run: `reasoning_matrix --model qwen-3.8-27b --cell on_on --effort medium --directive prune_v1
--max-tokens 65536 --runs 3 --no-judge` on `ct_tap_acute_abdomen_gda_bleed`. Baseline is
the v1 medium cell from L-34 (sheet 33.8k ch, e2e 25.4 s, gate 3/3).

Predictions, written before the result: sheet −35–50 % (high); analyser latency −20–30 %
(moderate); gate 3/3 holds (moderate); impression engagement unchanged because Clinical Lane
and exemplars are intact (moderate); the contrast line reads "per dictation" 3/3 (high).

## 5. Later cells, each one variable

- Done 2026-09-24 (L-36): clinical history is never emitted in any section; recommendation tags
  never appear; a history/prior finding is never asserted; contrast never inferred. 24 edits
  at the instruction sites, base prompts, both analyser variants.
- Done 2026-09-24 (L-37): COMPARISON names study and date only; any confirmed acute pathology
  opens the impression regardless of which question it answers. 5 edits, both variants + guide.

- Cell 2: hardening preamble trimmed where it duplicates the global guide (sections,
  header layout, placeholders). Generator-side.
- Cell 3: sheet moved from system prompt to user message; system prompt static per stage.
  Caching only; expect no quality change.
- Cell 4: negatives rescoping directive for the "small bowel / duodenum" class (a negative
  about a superset structure when the dictation names a member of it).
- Then the 5-case suite at the winning configuration, then radiologist review. The judge
  is not used as a gate; L-30 and L-33 showed it scoring truncated and mis-scoped sheets 5.00.

## 6. Production follow-through, independent of the cells

- Cerebras settings branches in `quick_report_analyser` and `template_manager` must set
  `reasoning_effort` explicitly (default is `high`) and raise `max_tokens` well above
  16,000 (Qwen 3.8 analyser reasoning is 20–38k tokens; L-33 truncated at 16k).
- The scan-type input should carry contrast phase where the RIS knows it.
