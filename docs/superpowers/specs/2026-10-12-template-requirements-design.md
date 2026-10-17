# Template requirements in the scratchpad — design

Date: 2026-10-12. Status: agreed in conversation with Hassan; not built. Builds on `feat/template-stack`
(template stack Generate, `template_structure`, the session rules in `template_stack.stack_brief`).

## Problem

In a templated scratchpad session the radiologist confirms every statement, and Generate writes only what was
confirmed. Two kinds of template content still reach the report without being shown first:

1. **Required values.** A grammar sheet's `LIST_MISSING` rule names the values every report of this type must
   carry (CMR: LVEDVi, LVESVi, LVEF, LV mass index, RVEDVi, RVESVi, RVEF). The scratchpad never shows them. A value
   the radiologist forgot to dictate surfaces only after Generate, as "Values not provided: …".
2. **Required statements.** `## Domain Rules` is free prose (`FREE_PROSE_SECTIONS`, effectively unlinted). A rule
   such as "the LGE paragraph always closes with a thrombus statement" can make the writer add "No intracardiac
   thrombus" that nobody confirmed. Since ff52b7a the session rules subordinate such rules ("applies only when
   the FINDINGS input contains that statement"), so today the statement is held back rather than shown; this
   design shows it instead.

Goal: everything a template requires is visible in the scratchpad before confirmation, as something the
radiologist fills, confirms, removes or marks N/A. The session rule stays as the backstop.

## Design

One feature, three parts, all tagged once at template save and resolved per case in the scratchpad.

| Part | Tagged at save | Shown in the scratchpad |
|---|---|---|
| Required values | `LIST_MISSING` items (confirmed by the radiologist) | value cluster: smart-filled, rest entered or N/A; blocking |
| Unconditional required statements | Domain Rules sentence → `NORMAL`/`NEGATIVE` unit in its paragraph | assumed normal (existing path) |
| Conditional required statements | `NEGATIVE "…" WHEN [findings: …]` in its paragraph | assumed normal, shown only when Jev says the condition is met |

### 1. Required values — the value cluster

**Source.** `Rule(effect="list_missing").items` and `position` from the parsed structure
(`template_structure(config)`). Only unconditional, every-report values; conditional measurements ("measure the
aorta if dilated") stay out by design.

**Smart fill.** When dictation stops (the `gateReview` hook, mic off, text still 800 ms), one Jev call asks per
item: "Does the dictation state the <item>?" (`noul`, keyed `value_i`, same shape as `ask_stated`). For each yes,
the value is read from the dictation by code (the number and unit in the matched sentence) and shown with its
source sentence; if code cannot read a single unambiguous number, the chip shows "stated" with the quote and no
value. No model writes a number.

**Render.** One compact block, not a row per value: chips in a wrapped line, e.g.
`LVEF 45% · LVEDVi 98 mL/m² · LV mass — · RVEF —`. States per chip: `filled` (from dictation, quote on hover),
`entered` (typed in the check phase), `na` (explicitly marked N/A), `open`. Values that belong together stay
together in the template's order. Click an open chip to type; a single "Mark rest N/A" action covers the case
where a sequence was not acquired.

**Blocking.** Confirm waits until every chip is `filled`, `entered` or `na` (added to the blockers beside open
referral rows, `HybridStackView.svelte:273-275`). The chip states go into `gateKey`, so editing a value re-arms the
gate.

**Generate.** Filled and entered values go into the FINDINGS input as confirmed statements under their region
("Answered by the radiologist: LVEF 45%"). N/A items produce the template's "Values not provided: …" line at its
`position`, so that line is now the radiologist's explicit choice. `LIST_MISSING` stays in the stack brief.

**A filled value the report lacks (approved by Hassan 2026-10-15; replaces "list it as not provided").** After
Generate, the backstop (Jev) asks whether the report states each filled value. A value the gate filled from the
dictation was provided, so it never joins the "Values not provided" line. Code writes its dictated sentence back,
verbatim, as a pre-applied insertion shown on the rail (undo there):
- The sentence is the dictated unit holding the value's clause (never the bare clause), capitalised and
  terminated. It is checked on the server against the request's units; one holding removed text is never written.
- It goes at the end of the headed report section named for the value's region (a paragraph region maps to its
  section), with the section's bullet marker if it is a list, and before the "Values not provided" line is written.
- Before writing, the quick path's duplicate check (Jev, "already said in other words?") runs. Said: nothing is
  written and there is no flag.
- Flag only (value_missing, nothing written, not listed): no dictated sentence (a "stated?" or kept chip), no
  region, no headed section for the region, a region naming the conclusion, a report without headers, or the
  duplicate check failing (fail closed).

**Template editor.** The sheet is never shown to the user (standing rule); requirements are shown as report
behaviour. After the sheet is built, `SkillSheetCreator.svelte` / `TemplateRefinePanel.svelte` show "Every report
will include:" as removable chips with "+ add", derived from the parsed structure. A chip edit is applied by code
to the `LIST_MISSING` line (never by showing or hand-editing the sheet); the save path re-parses as today
(`_queue_structure`). Guidance: keep the list short; one block per measurement group.

### 2. Required statements

**Save-time extraction (once per sheet save, not per dictation).** For each sentence under `## Domain Rules`, a
Jev yes/no: "Does this rule require the report to state something?" For each yes, one writer call (Qwen, the
sheet's model) turns it into a unit in the right paragraph:

- unconditional → `NEGATIVE "No intracardiac thrombus."` (or `NORMAL "…"`) under the paragraph the rule names;
- conditional → `NEGATIVE "No intracardiac thrombus." WHEN [findings: LGE is reported]`.

The rule sentence itself stays in Domain Rules (it may also carry placement, which the session rule keeps). The
converted units are shown in the template editor as report behaviour, "Every report will also state:" with
remove (the sheet itself is never shown), and the save
lints and stores them like any other unit. A sentence the extraction misses is still held back by the session
rule.

**Grammar change.** Template (lean) mode today rejects any conditioned `NEGATIVE` (`NOT_LEAN`,
`template_sheet_grammar.py:598-600`). Allow exactly one form in template mode: `NEGATIVE "<sentence>" WHEN
[findings: <condition>]` inside a findings paragraph. History conditions and other findings-conditioned units stay
lint errors. Bump `STRUCTURE_VERSION` so stored parses refresh (`template_structure` re-parses stale copies).

**Scratchpad.** `template_region_normals` keeps returning `NORMAL` plus unconditioned `NEGATIVE` (so converted
unconditional rules need no new code). Conditioned negatives go to a new step at the `gateReview` hook: one Jev
call, one `noul` question per condition ("Does the dictation report <condition>?"), threshold as `ask_checks`.
Each yes adds the sentence to that region's assumed tray (`data-state="assumed"`), confirmable and removable like
any assumed normal; each no shows nothing. The answers go into `gateKey`.

**Generate.** Unchanged: confirmed assumed lines are in the FINDINGS input; removed ones arrive as DO NOT ASSERT.

## Failure behaviour

- No usable structure → no cluster, no conditional checks; the existing `template_unusable` notice and today's
  Generate path apply.
- Jev error or timeout on smart fill → every chip `open` (the radiologist fills or marks N/A); never blocks on
  the network.
- Jev error on conditions → no conditional lines shown; the session rule holds the statements back.
- Save-time extraction fails → sheet saved without converted units; the session rule holds them back.

## Testing

- Grammar: the new `NEGATIVE … WHEN [findings: …]` form parses in template mode; other conditioned forms still
  `NOT_LEAN`; renderer round-trips.
- Value fill: code reads one unambiguous number; two numbers or none → "stated" without value; Jev wording lab on
  the CMR fixtures plus prod CMR dictations (yes/no on "states the LVEF", including "EF 45", "ejection fraction
  mildly reduced at 45", and a LVEF-free dictation).
- Extraction lab: Domain Rules sentences from prod grammar sheets, hand-labelled require/not; measure Jev
  precision before wiring.
- Frontend: chip states, Mark rest N/A, Confirm blocked until all resolved, gate re-arms on edit.
- Endpoint: N/A items produce the "Values not provided" line; entered values appear as statements.
- Endpoint: a filled value the report lacks is written back (or flagged), never listed as not provided.

## Open questions

1. **Where grammar sheets come from in production.** The prod analyser
   (`template_manager.analyze_examples_to_skill_sheet`) writes the free-form sheet; the grammar conversion
   (`TEMPLATE_SHEET_CONVERT_PROMPT`) is a lab script. Templates without a grammar sheet get no structure, so no
   scratchpad template stack at all. Check how many prod templates carry a usable grammar `sheet_structure`, and
   decide whether conversion runs on save, before building this.
2. Value units and ranges: show the template's reference range beside a chip? (Proposed: later.)
3. Should a filled value that disagrees with a dictated value elsewhere raise a check? (Proposed: the existing
   contradiction check covers it.)

## Shipping requirements (with the template stack and the conversion)

The sheet is never exposed to the user; every path below works on it behind the scenes.

1. **Chat-to-edit keeps the grammar.** `refine_skill_sheet` gets the grammar (as `TEMPLATE_SHEET_CONVERT_PROMPT`
   carries it), then lint; on errors one repair call (`REPAIR_SYSTEM_PROMPT`); still failing → keep the previous
   sheet and tell the user the change could not be applied. The reply stays framed as report behaviour.
2. **New templates are written in the grammar.** The conversion step runs after
   `analyze_examples_to_skill_sheet`; a failed conversion keeps the free-form sheet (today's path).
3. **Existing templates converted once** (31 skill-sheet templates, hand read + one end-to-end test each), written
   by a one-off script: old sheet kept as a pre-upgrade TemplateVersion and a JSON backup (see the template pipeline
   design). Legacy templates (no generation mode) soft-deleted.

## Build order

1. Answer open question 1.
2. Value cluster (backend fill + chips + blocking + Generate wiring), using existing `LIST_MISSING` lines.
3. Template-editor chips for `LIST_MISSING` (report behaviour; the sheet is never shown).
4. Grammar change + conditional Jev check.
5. Save-time Domain Rules extraction (after its lab).

Each step ships behind the scratchpad stack flag and gets an independent review before merge.
