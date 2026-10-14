# Context rules resolved before generation — design

Date: 2026-10-13. Status: draft for Hassan's approval. Roadmap item 1 of
`2026-10-13-template-rules-next-design.md` (§1 there is the outline this spec expands).
Principle: **Jev decides, code applies, the generator only writes what is already decided.**

## Aim

A template's context rules (`RULE WHEN [context: …] REPLACE / SUPPRESS / USE`) are settled by Jev and applied to
the sheet by code before the generator sees it. The generator then sees one line of text where there used to be
a default line plus a rule to interpret. It cannot merge both branches, and it cannot print an unfilled `{slot}`.

## Today

- Both template Generates go through one function, `template_lean.generate_template_report_lean` (called
  from `main.py`):
  - the scratchpad path (`stack` set: FINDINGS is the confirmed findings block, the sheet reduced by
    `template_stack.stack_brief`);
  - the straight-dictation path (`stack` None: the raw sheet).
- In both, the rule lines reach the generator as text, and the generator interprets them.
- Jev judges a context condition only in the scratchpad's assumed-normals step
  (`hybrid_stack/normals.assumed`, via `template_suppressions`), and only to hide an offered normal.
- Seen 2026-10-13 (`final/E2E_PRIOR.md`, 23 cases):
  - "No comparison made with previous study dated 02/12/2025." Both branches were merged, on garbled dictation.
  - "Comparison made with previous CT dated {date}." A raw slot was printed for a vague prior.
  - No comparison line at all on the scratchpad path for the same vague prior. The stack prompt drops a FIXED
    line with an unfilled slot.
- Production sheets have 53 context rules: 29 REPLACE, 21 USE, 3 SUPPRESS_SECTION and 3 SUPPRESS_HEADERS. Twenty
  of the REPLACE rules are the prior-imaging pattern.

## Change

One new pure-code module, `template_context_rules.py`, plus one call site.

1. **Collect.** Parse the sheet (`parse_sheet(sheet, mode="template")`). If the sheet is not a grammar sheet or
   does not parse clean, nothing changes: the sheet is used as today. The rules in scope are context rules with
   effect `replace`, `suppress` or `use`. Distinct condition texts are asked once each.
2. **Decide.** One Jev call (`jev_stack.ask_conditions`, the same `q_condition` wording and `CONDITION_MIN` 0.5
   cut-off as the scratchpad, so silence is not met).
   - The state is the clinical history plus the FINDINGS input. On the scratchpad path that input is the
     confirmed findings block; on the straight path it is the dictation.
   - The scratchpad needs no change. A rule that targets a NORMAL/NEGATIVE line was already settled there, and
     the stack brief strips those units anyway.
3. **Apply** (code, by the line numbers the parse gives; rule lines are removed in every case):

   | Effect | Condition met | Not met |
   |---|---|---|
   | REPLACE "a" WITH "b" | the unit line quoting "a" is rewritten to quote "b" | default line kept |
   | SUPPRESS "a" | the unit line quoting "a" is removed | default line kept |
   | USE "b" (section S) | a `FIXED "b" \| section: S` line takes the rule line's place | nothing added |

   A target matches a unit line by `norm_key` on its quoted text, exactly as `template_suppressions` matches. A
   target that no unit line quotes is left as today: the rule line stays and the generator reads it. This is
   logged as `unmatched`.

   Two met rules on the same target: the first in sheet order applies. The other stays as today and is logged as
   `conflict`. That is a sheet defect for the Rules step to prevent.
4. **Slots.** A line written by a met rule may carry `{slots}`, filled by the generator from the input, which
   already holds every value the dictation gives.
   - Today's stack prompt drops a FIXED line with any unfilled slot. That rule changes for lines produced by this
     step only: they are marked as decided by code, and the generator writes them with the values the input
     states, leaving out the words that carry a value it does not state. ("Comparison made with previous CT
     dated {date}." with no date becomes "Comparison made with previous CT.")
   - **Hard guard (code, after generation):** any `{…}` left in the report is removed with the sentence that
     holds it, and logged as `slot_leak`. No `{slot}` reaches a report from either lean path. Today's fallback path is untouched.
5. **Hand over.** `generate_template_report_lean` passes the resolved sheet to the generator in place of the
   stored one. Everything downstream is unchanged (stack brief, prompts, post-generation check). The stored
   sheet is never modified.

Out of scope, unchanged: SUPPRESS_SECTION / SUPPRESS_HEADERS context rules, `history` and `findings` rules,
conditional negatives, today's fallback path (`generate_report_from_config` when lean fails), the stamp path
values.

## Failure behaviour

Nothing blocks Generate.

| Failure | Behaviour |
|---|---|
| Sheet not grammar / parse not clean | sheet used as today; `skipped: "parse"` |
| Jev call fails or times out | sheet used as today (rules reach the generator raw); `error` logged |
| Target not found / conflicting rules | that rule left as today; logged per rule |
| Any exception in apply | sheet used as today; logged |
| Slot survives generation | sentence removed by the guard; `slot_leak` logged |

## Evidence

The lean record gains `context_rules`. It is stored with the candidate record (`tp.candidate_record`) and
holds:
- `asked`: the number of conditions asked;
- `ms`: the time taken;
- `error`;
- per rule: `{line, condition, effect, score, met, applied | unmatched | conflict}`;
- `slot_leaks`: the count from the guard.

One log line per Generate (`[template.context_rules]`).

## Testing

- **Unit (no network; Jev stubbed by score):**
  - each effect met / not met;
  - rule lines always removed;
  - the resolved sheet still lints clean;
  - norm_key matching;
  - unmatched and conflicting rules left as today;
  - a non-grammar sheet unchanged;
  - Jev failure gives the unchanged sheet;
  - the slot guard;
  - the stack brief of a resolved sheet carries no rule line for a resolved rule;
  - `generate_template_report_lean` passes the resolved sheet on both paths.
- **Lab (reported; Hassan decides):** the 23 prior/no-prior e2e cases in the private folder
  (`run_prior_e2e.sh` / `check_prior_e2e.py`), on both paths, before (`2cb46d32`) and after. Reported:
  - merged-branch lines;
  - raw slots;
  - missing comparison lines;
  - the vague-prior case;
  - the garbled case;
  - Jev condition scores per case.
- **Synthetic follow-up** (Opus subagent, private folder, planted truth): about 30 dictations over the
  prior-imaging pattern and 5 other context rules from the 31 sheets (contrast, artefact, protocol variant).
  Variants: stated, silent, negated, vague, and two priors. This reports Jev condition accuracy separately from
  the 23 real-derived cases.

## Measuring after launch

From `context_rules` in the candidate records:
- rules met per Generate, by condition text;
- unmatched / conflict counts (sheet defects);
- `slot_leak` count, which should be 0 after the generator change;
- radiologist edits to the comparison line in the final report versus the generated one.
