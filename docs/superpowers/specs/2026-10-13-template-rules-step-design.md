# Template creation: the Rules step — design

Date: 2026-10-13. Status: agreed in conversation with Hassan (brainstorm, independent review folded in); not built.
Post-merge work, after `feat/template-stack` ships. Related: `2026-10-13-template-rules-next-design.md` (build
order), `2026-10-12-template-requirements-design.md` (value cluster in the scratchpad). Follow-on spec: the chat-edit
router (below, "Next").

## Aim

Settle template decisions once, at creation: short confirmation cards for required values, study-level wording
and always-printed text, applied by code, never rewritten by an LLM. Fewer fix-ups after generation, and missing
measurements prompted while dictating rather than found in the report.

Non-claims: the cards cover the sheet's rule lines only. Voice, exemplars and generation stay probabilistic, so
the post-generation check stays. Nothing here is described to users as "verified" or as clinical safety.

## Today

One analyser call (`template_writer.write_sheet`) returns the whole grammar sheet, the Style summary and 3
free-text questions together. The creator (`SkillSheetCreator.svelte`) shows Style → Questions → Test → Refine; each
question answer goes through chat-to-edit (a model rewrite of the existing sheet, then the save function), which is
where repair loops come from. The sheet is saved on Create.

## New flow (decisions before the sheet)

1. **Paste examples.**
2. **Decision run** (new, Qwen, low temperature, structured output; one job): from the examples alone, list what
   needs the radiologist: candidate required values (with the example reports each appears in), and wording for the
   standard study-level concepts. In parallel, Jev answers per example and per standard concept (comparison/prior
   imaging, contrast, sequences not acquired, technical limitation): "Does this report state <concept>?"
3. **Rules step** (replaces Questions): cards, below. "Checking your examples…" shows while the run finishes.
4. **Writer** builds the sheet with the confirmed decisions as ground truth, through the prompt's existing
   authoritative-context input (today used for protocol notes). Its rule-guessing instructions for these items are
   removed; it no longer writes questions. "Building your template…" shows meanwhile (~11 s).
5. **Sheet checks** after the build, shown on the **Style** step ("how your report will read"): flagged
   always-printed lines and your normal report.
6. **Test**, **Refine**, **Create** as today. The save function applies the ledger last on every save.

## Cards

Exceptions only, quoted evidence, about 8 decisions. Ranked: examples disagree, then uncertain values, then flagged
always-printed lines. Items every example agrees on fold into a collapsed "kept as-is" list. No "confirm all".
Evidence is shown as which reports said what ("reports 1, 2, 4, 5: 'ECV 28%'"), never percentages. Nothing seen in
fewer than every example is pre-ticked. Every quote is checked by code against the example text; a candidate whose
quote is not found is dropped.

| Card | Step | Choices |
|---|---|---|
| Required values | Rules | values in every example ticked; candidates with Every report / Only when relevant / Not needed; + add |
| Study-level wording (comparison, contrast, sequences, limitation) | Rules | wording prefilled from the examples: Keep / Edit wording / Not used |
| Your examples disagree | Rules | the differing quotes; choose how the template handles it (e.g. "contrast varies: use whichever is dictated") |
| Always printed | Style | per flagged FIXED line (Jev: "Could this be false for a different patient having this scan?"): Always the same / Only when dictated / Remove |
| Your normal report | Style | the all-normal report built by code from NORMAL/NEGATIVE lines in section order, each sentence tagged with its line; tap a sentence to edit or remove; plus "mentioned in your examples but no normal sentence" (structures in COVERS without a NORMAL): Add wording / Leave unmentioned |

"Only when relevant" values are recorded and parked for the findings-triggered rows work; they are not required.
Not in v1: finding-habit cards (wait for triggered rows; the decision run may record habit candidates, hidden, for
that lab), terms and section layout (already on the Style card), per-user overrides on shared templates.

## Decision ledger

Stored as `template_config["decisions"]`, a list of entries `{kind, key, choice, by, at, source}`; `source` is
creation, chat, first-use review or default (skipped step). The effective sheet is the writer's or chat's output
with the ledger applied by code.

| Kind | Key | Applied as |
|---|---|---|
| value | value name | the items of the single `LIST_MISSING` rule |
| concept | concept name | the concept's FIXED default plus its one context rule with the standard condition text, or nothing for "not used" |
| fixed | the line's text | FIXED kept, removed, or left to dictation (removed from the sheet) |
| normal | region + structure label | the NORMAL/NEGATIVE line's text, or removed |

- `apply_ledger(sheet, ledger)` runs inside the save function as its last step, on every origin (creation, chat,
  rebuild, restore, upgrade script), after the writer and any model repair. It edits the parsed structure and
  re-renders; no free-text matching.
- Matching uses stable keys only (the single LIST_MISSING line; a concept's standard condition text; region +
  structure label). An entry whose target cannot be found is re-inserted where code can write it from scratch
  (values, concepts); otherwise (normals, fixed lines) it is shown as a card at the next review. Never guessed.
- Automatic writes never override the ledger. A chat edit that changes a ledger item updates it (source chat) and
  the reply says "This changes something you confirmed: <item> <old> → <new>".
- Prose is not rewritten. A lint flags any exact quote of an old unit sentence left in the free-prose blocks (the
  grammar already keeps absences out of paragraph prose and exemplars to abnormal wording).
- Existing templates (the 31 upgraded ones and any later) get the decision run on first edit, using stored example
  reports where present; without examples, only the Style-step cards.

## Failure behaviour

Nothing blocks template creation.

| Failure | Behaviour |
|---|---|
| Decision run fails / times out | no Rules cards; the writer infers rules as today; notice "We couldn't pre-check your rules; review them on the Style step" |
| Jev concept questions fail | no study-level cards; grammar defaults apply; value cards still shown |
| Candidate quote not found in the examples | card dropped |
| Writer ignores a confirmed decision | the ledger overwrites that line at save; logged (writer drift rate) |
| A ledger edit fails lint | a bug: sheet saved without that decision, which becomes a card at next review; error logged |
| Sheet checks fail | Style step shows the summary without those cards |
| Rules step skipped | pre-ticked defaults recorded with source "default", not confirmed |

## Testing

- Unit: card builder (evidence check, ranking, budget); each ledger operation on the parsed structure,
  round-tripped through the parser and renderer; key matching after a reworded rebuild; unmatched entries become
  cards; automatic writes never override; chat updates the ledger.
- Frontend: card states, budget and the collapsed "kept as-is" list, three-way value chip, tap-to-edit normal
  report, skipped step.
- Labs before wiring, reported (results and recommendations; Hassan decides; no pass/fail gates).

### Labs run on synthetic data seeded from production

Production data is too thin to test each step on real cases alone. Every lab for this work uses synthetic data
generated by Claude Opus 5.5 subagents (Max plan, no API spend), closely matched to what production shows:

- **Seeds:** the 31 production templates' example reports and sheets (private folder; de-identified), giving the
  modality mix, report shapes, section conventions, measurement styles and the radiologists' voice.
- **Planted ground truth:** each synthetic example set is generated with known answers built in, so labels exist by
  construction: e.g. ECV in 4 of 6 reports; contrast stated in one example and "No contrast given." in another; a
  patient-specific line repeated across examples; prior imaging in some reports; a structure mentioned only when
  abnormal; near-duplicate or all-normal example sets (the hard cases for the evidence thresholds).
- **Per step:** example-report sets for the decision run and writer; dictations for the scratchpad and Generate
  (with and without priors, vague priors, messy real-style dictation); chat instructions for the router (single,
  mixed, rule-in-disguise).
- **Checks on the synthetic data itself:** Hassan spot-checks a sample for realism; where real cases exist they run
  alongside as a held-out set and are reported separately from synthetic results; the generator (Claude) is never
  the model under test (Qwen, Jev), and each lab notes how the synthetic set may be easier or cleaner than
  production.
- Synthetic sets seeded from production stay in the private folder, never in the repo.

### The lab for this spec

On synthetic example sets for the 11 production templates with ≥ 3 examples, plus planted-truth variants: run the
decision run; a Claude subagent answers the cards, with Hassan's spot-checks; build each sheet with and without the
decisions; compare against the curated production sheets and the planted truth: required normals captured (today
33/43), patient-specific FIXED lines, comparison/contrast handling, disagreements found, cards per template (target
≤ 8), quotes dropped as unverifiable.

## Measuring after launch

- Primary: share of a template's first 10 reports where the radiologist edits template-owned text (FIXED, NORMAL,
  comparison/contrast lines), from generated-vs-final report versions and the sheet stamped on each report.
- Secondary: Refine chat turns per template in its first week; "[MISSING DATA]" / "Values not provided" rate;
  override rate per card kind; time on the Rules step and abandonment there.
- Compared against templates created in the Questions era.

## Next: the chat-edit router (own spec)

Jev tags each instruction with yes/no per kind of change (required value, study-level concept, always-printed
line, normal wording, section layout, style), so mixed instructions need no splitting. Each yes goes to its own
targeted lightweight call that reads the whole instruction and handles only its kind. Rule kinds return a
structured change (e.g. `{change: "required value", name: "ECV", to: "not needed"}`) that code validates and
applies through the same ledger operations as the cards; style returns a prose-only edit, rejected by code if any
unit line changed; after a style edit Jev asks whether a new prose line requires the report to state something,
and if so it goes through the rule route. Uncertain or rejected changes come back as the one-tap card. Lab: the
stored refine chat turns plus synthetic mixed instructions.
