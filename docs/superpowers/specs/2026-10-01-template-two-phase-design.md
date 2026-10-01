# Templated reports — two-phase clinical layer (design addendum 2)

**Date:** 2026-10-01 · **Branch:** `feat/template-pipeline-mirror` · **Parents:**
`2026-09-30-template-pipeline-mirror-design.md`, `2026-10-01-template-sheet-grammar-design.md`.
**Status:** direction agreed with Hassan 2026-10-01; prompt wording (lean analyser, Phase 1 analyser,
brief header labels) needs his sign-off before production.

## Why

Quick reports carry their clinical intelligence in a per-case sheet: Clinical Lane (question,
differentials with visibility tags), Companion Matrix (differential-targeted negatives, If-present),
Recommendation scope — reconciled with the findings by the brief (policy 1, L-45, L-48 …). A template
sheet is built from 3–5 reports of one scan type: it captures voice, style and structure, but has no
case anchors, so today the clinical reasoning for each templated case happens raw inside the generator.
The G2 lab also showed that learning clinical rules from 3–5 examples over-constrains (RULE precision
0.11–0.44). So: the template sheet goes lean (voice + structure + template-intrinsic units); a per-case
clinical analyser, extracted from quick's machinery and grounded by the template sheet, supplies the
clinical layer; one brief reconciles both with the findings.

## Flow

```
Set up workspace (template + clinical history final; history edits force re-setup)
  └─► PHASE 1 (during dictation, no findings): template-grounded case deliberation
        inputs  : parsed template structure + sheet prose (Scan Context, technique), scan type, history
        output  : case units in grammar → appended to the template sheet = MASTER SHEET (cached)
        checks  : placement in existing paragraphs, single-finding negatives, no duplicate of a template
                  unit, tags present, master sheet parses usable; pre-split bundles, pre-built Jev questions
Generate (findings in) — always waits for Phase 1
  └─► PHASE 2: one brief over the master sheet (Jev + Qwen in parallel, ~0.5–1 s)
        template units (as G3) + case units (quick's routing, shared) → labels in template paragraphs
  └─► template generator → post-generation check → options (stated / offered) → artifacts → rail
```

Cache key: (template id, sheet hash, history hash). No history (API-only path): Phase 1 deliberates on
the template's typical question from Scan Context, flagged `default_question`, recommendations held to
optional.

## Lean template sheet (changes to grammar v1)

Keep: `## Report Structure`/SECTION, `## Paragraph:` headings, prose voice, NORMAL (one per structure),
NEGATIVE (unconditional routine sweep negatives), FIXED (with slots), TERM, LIST_MISSING, and
**study/context rules** only: `RULE WHEN [context: …]` with REPLACE/SUPPRESS/USE/SUPPRESS_SECTION/
SUPPRESS_HEADERS (what was performed, protocol, prior imaging availability).

Add: `COVERS ["<structure>" | "<structure>" …]` — one per paragraph, the structures the paragraph
reports (Phase 1 places case units by it; NORMAL labels alone don't cover every paragraph). Required
per findings-role paragraph (lint).

Remove from the template analyser's output (lint error in a template sheet): findings-conditioned
RULEs (APPEND/REPLACE/USE/INSERT/ORDER/SUPPRESS NEGATIVES with `findings:`), `NEGATIVE … WHEN
[findings: …]`, IF_PRESENT. Their content moves to (a) Phase 1 (case-dependent negatives, If-present,
recommendations) or (b) paragraph prose as quoted voice exemplars ("Abnormal pattern:", interpretive
phrasing, recommendation phrasing) that the generator imitates.

Lint relaxation: "conditional phrase in prose" becomes a stored **warning** (not blocking) — voice
guidance legitimately says "when present, give the maximal diameter"; it changes phrasing, not which
negatives are stated. Still **blocking**: a prose line that states a negative, decorated/miscased
units, mis-levelled headings, old `IF [` syntax, malformed units.

## Case units (Phase 1 output; master sheet only)

```
## Case Deliberation
QUESTION "<clinical question, one line>"
DIFFERENTIAL [<name>] TIER triage|aetiology "<imaging discriminator>" VISIBLE yes|no|silent
RECOMMEND <IMAGING|REFERRAL|MDT|TISSUE|CORRELATION> "<report-form sentence>" WHEN [findings: <statement>]

(inside the template's paragraphs, after its own units)
NEGATIVE "<text>" TARGETS [<differential>] | origin: case
IF_PRESENT [<finding>] "<negative>" (core|contextual) | origin: case
```
- `VISIBLE` is judged against the template's actual technique/phases/sequences (Scan Context,
  technique paragraph, FIXED technique text).
- Targeted negatives are written in the template's negative phrasing (the analyser sees the sweep
  negatives and terminology), one finding each, placed by COVERS, never duplicating a template unit.
- Parser: case keywords and `| origin: case` are valid only in a master sheet (lint error in a stored
  template sheet). `SheetStructure` gains `question`, `differentials[]`, `recommendations[]`, and
  `origin` on Negative/IfPresent.

## Phase 2 brief additions (shared logic, quick byte-identical)

Port from `quick_report_brief.compile_brief` into `report_reconcile` (as with the engine):
- **Differentials (policy 1):** Jev "findings show this branch present" → present; absent ∧ VISIBLE
  yes → closed by silence (removed); VISIBLE no / silent → kept open with deferral framing.
- **Targeted negatives:** Qwen classifier as today (KEEP / OMIT / DO NOT ASSERT); a negative whose
  differential is present is OMIT.
- **If-present (case):** Jev finding present (PRESENT_LOW/HIGH) + `route_finding` → stated / offered /
  do not assert / dropped, cap 4 (L-45).
- **Recommendations:** Jev condition-unmet → removed; plan include / exclude (routine_workup →
  "Do not recommend") / optional (offered).
- **Impression plan:** shared `_plan` with the template's Impression Construction prose as
  inclusion_logic; L-48 guard via the signed-off checklist.
- **One label per claim:** template sweep negative and case negative with the same claim → safer label
  wins (OMIT > DO NOT ASSERT > KEEP), logged in `decisions["conflicts"]`.
- New brief labels (OPEN DIFFERENTIAL, CLOSED, RECOMMEND/OFFERED …) go into the
  `TEMPLATE_SHEET_HEADER_BRIEF` sign-off package with the G3 labels.

### Sign-off package

Header lines staged here for `global_style_guide.TEMPLATE_SHEET_HEADER_BRIEF`; not in the code until signed off.

- (2026-10-01, Jev wording v2 T5) "ADDRESS AS POSSIBLE — the dictation raises this as a possibility; the
  impression keeps the hedge." A present branch (`q_present` ≥ 0.5) whose present-vs-possible choice in the
  same findings-state call gives P(possible) ≥ 0.5 is labelled `ADDRESS AS POSSIBLE` instead of `ADDRESS`.

## Prompts

1. **Lean template analyser** (replaces the G2 lab prompt): sections, paragraphs + COVERS, NORMAL per
   structure, routine NEGATIVEs, FIXED with slots, TERM, LIST_MISSING, context rules only; rich voice
   prose (opening, order, multiple quoted abnormal-pattern exemplars, interpretive and recommendation
   phrasing, impression construction). No findings-conditioned rules, no IF_PRESENT. Sheet returned
   between delimiters, summary/questions JSON after (removes the broken-JSON failure).
2. **Phase 1 case analyser** (new): quick analyser's Clinical Lane, Companion Matrix and
   Recommendation-scope phases (prune_v1 lineage, L-36 history-not-emitted, UK services, closed tag set,
   single-finding negatives, visibility tags), with no voice/structure phases; template structure as
   grounding input; output in case-unit grammar. Case-agnostic instructions.
3. **Repair prompt:** lean grammar + case units.
4. **Refine / conversion prompts (G5/G6):** lean grammar.

## Testing

- Synthetic sets (5802d5b): answer keys re-cut — template-intrinsic units scored against the lean sheet;
  case-dependent planted items (targeted negatives, If-present, recommendations) scored against Phase 1
  output for each held-out dictation's history; brief accuracy per dictation as before.
- Phase 1 latency measured (target: finishes within typical dictation time, ≤ 20 s).
- Golden quick tests unchanged through the routing port.
