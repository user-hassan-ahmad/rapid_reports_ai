# Template skill-sheet grammar v1 — design addendum

**Date:** 2026-10-01 · **Branch:** `feat/template-pipeline-mirror` · **Parent spec:**
`2026-09-30-template-pipeline-mirror-design.md` (this addendum changes §2's source of the structure;
§3–§6 stand). **Status:** approach approved by Hassan 2026-10-01; analyser/refine prompt wording needs his
sign-off before it reaches production.

## Why

E1/E1b (ledger, to be logged) showed the structuring ceiling is the sheet format, not extraction:
14/26 stored sheets usable whatever the model or call design, the rest blocked by rule kinds the
schema can't represent (target-less suppressions, missing-value lists, header choice, ordering,
insert-before, section suppression). Every sheet is written by a prompt we control — the creator
analyses example reports, Refine is an LLM chat edit, passive updates are LLM passes; there is no
hand editor. So the format can be guaranteed at the source and parsed by code, as quick sheets are.

## Principle

Prose for the radiologist's voice; a strict, keyword-led line grammar for every unit the brief
reconciles against a dictation. Code parses the grammar into the existing `SheetStructure`; the LLM
extractor (E1b) remains only as a fallback for sheets not yet in grammar form.

## Grammar v1

A **unit line** starts (after optional indentation and an optional `- ` bullet) with an uppercase
keyword. Quoted text uses straight double quotes and never contains a double quote. `{slot}`
placeholders are allowed inside quoted text. Anything that is not a unit line is prose and passes
through untouched.

### Structure

```
## Report Structure
SECTION <NAME> | header: none | role: <role>
SECTION <NAME> | header: "<as written in reports>" | role: <role>
```
`<role>` ∈ findings | impression | history | technique | comparison | other. Order of SECTION lines =
output order. `<NAME>` is uppercase words/`/`/`&`. Exactly one `## Report Structure` block.

```
## Paragraph: <name> (<SECTION NAME>)
```
Every unit below a paragraph heading belongs to that paragraph and section until the next `## `
heading. Units under `## Report-wide` belong to no paragraph (section given per unit or FINDINGS).

### Units

```
NORMAL [<structure>] "<text>"
NEGATIVE "<text>"
NEGATIVE "<text>" WHEN [<source>: <statement>]
FIXED "<text>"
TERM PREFER "<term>"
TERM AVOID "<term>"
IF_PRESENT [<finding>] "<negative>" (core|contextual)        ← v1: parsed, stored, not used (If-present off)
RULE WHEN [<source>: <statement>] <EFFECT>
```

`<source>` ∈ findings | history | context. `<statement>` is one plain statement judgeable true/false
for a case and **always names its subject** ("findings: abnormal ascending aorta dimensions are
reported", never "findings: abnormal").

### Rule effects

| Effect | Syntax | Brief when met | Brief when not met |
|---|---|---|---|
| replace | `REPLACE "<target>" WITH "<text>"` | `OMIT: "<target>" — <statement>` + `INSTEAD: "<text>"` | rule removed; target stands |
| suppress | `SUPPRESS "<target>"` | `OMIT: "<target>" — <statement>` | removed |
| append | `APPEND "<text>"` | `APPLY: "<text>"` | removed |
| use | `USE "<text>"` | `USE: "<text>"` | removed |
| insert_before | `INSERT "<text>" BEFORE "<anchor>"` | `INSERT: "<text>" BEFORE "<anchor>"` | removed |
| suppress_paragraph_negatives | `SUPPRESS NEGATIVES` | every NEGATIVE of this paragraph → `OMIT … — <statement>`; the paragraph is described from the dictation | removed |
| list_missing | `LIST_MISSING ["<item>" | "<item>" …] AT TOP|AT END` | Jev per item ("the dictated findings state <item>"); `MISSING (list at top): <items not stated>` (omitted when none) | — (always evaluated; the WHEN is `[findings: any listed value is not stated]`) |
| suppress_section | `SUPPRESS_SECTION <NAME>` | `OMIT SECTION: <NAME> — <statement>` | removed |
| suppress_headers | `SUPPRESS_HEADERS` | `NO PARAGRAPH HEADERS — <statement>` | removed |
| order | `ORDER FIRST|LAST` | `PLACE THIS PARAGRAPH FIRST|LAST — <statement>` | removed |

"Target-less suppress and replace with description" (E1's most frequent unrepresentable kind) is
`SUPPRESS NEGATIVES` on the paragraph; "suppress the specific negative" is `SUPPRESS "<target>"` with
the target quoted. The new labels (INSERT, MISSING, OMIT SECTION, NO PARAGRAPH HEADERS, PLACE)
extend `TEMPLATE_SHEET_HEADER_BRIEF` — a wording change that goes to Hassan for sign-off with the
analyser prompt.

## Parser and lint

`template_sheet_grammar.py` (new): `parse_sheet(sheet) -> (SheetStructure, List[LintError])`.
- Pure code, deterministic; `model="grammar"`; `usable` iff no lint errors and the Report Structure
  block is present with ≥ 1 findings-role and ≥ 1 impression-role section.
- Lint errors (line number + reason): unknown keyword-like line (a line starting with an uppercase
  word followed by `[`/`"`/`WHEN` that isn't a known keyword), malformed quotes, unknown source,
  statement without subject words (fewer than 2 content words), unknown section in a paragraph
  heading, duplicate SECTION, unit outside any paragraph without a section, a conditional phrase
  ("if", "when", "unless") in prose under a paragraph (it should have been a RULE/WHEN — warning
  level, blocks usable), an uppercase `IF [` anywhere (old syntax).
- `SheetStructure` gains: `Rule.effect` extended to the table's effects; `Rule.items: List[str]`
  (list_missing), `Rule.anchor: str` (insert_before), `Rule.position: Literal["top","end","first","last"] | None`;
  `source: Literal["grammar","extracted"]` on SheetStructure. `source_lines` hold the unit line text.
- Lint on save: analyse / refine / passive-update outputs are parsed; on lint errors, one LLM repair
  call receives the sheet + numbered errors and returns the corrected sheet; still failing → saved
  as-is, structure unusable (raw path), errors logged. `tss.fresh()` serves grammar structures the
  same way (hash-keyed).

## Upstream prompts (lab first)

- **Analyser** (`analyze_examples_to_skill_sheet`): emits the grammar. Units are derived from the
  example reports: NEGATIVE/NORMAL from what the radiologist states as normal/absent; RULE from how
  their wording changes when a finding is present; IF_PRESENT from negatives they write next to a
  finding (grounded in the examples — stored, unused in v1). Case-agnostic instructions; structural
  examples only.
- **Refine** (`refine_skill_sheet`): edits preserve the grammar; new constraints become RULE/
  NEGATIVE units.
- **Conversion** (existing sheets, one-off, opt-in per template, versioned via TemplateVersion):
  an LLM pass rewrites a legacy-format sheet into the grammar; acceptance requires every converted
  unit's quoted text to be grounded in the old sheet (the E1 verifier's provenance checks reused)
  and zero lint errors.

## Lab harness and acceptance

`scripts/template_sheet_lab.py`: lab copies of the analyse/refine prompts (production untouched).
Inputs: real templated reports (133 in prod) as example sets — 4–5 per template for TAVI, CT
coronary, CT AP acute, CT trauma polytrauma, CT aorta, CMR non-stress, Cardiac MR 2, CT AP portal
venous. Measures:
1. parse rate (target 100% after the lint-repair pass; ≥ 90% first pass);
2. hand read: units correct, in the radiologist's voice, conditions name subjects, rule kinds used
   correctly (CMR missing values → LIST_MISSING, coronary → SUPPRESS_SECTION …);
3. cross-linking: brief compiled against held-out real dictations of the same template (reports not
   used as examples) — labels read correctly;
4. refine round-trip: 3 instructions per template keep 0 lint errors;
5. conversion of the 26 stored sheets: grounded + lint-clean rate.
Evaluation economy: ≤ 2 full lab runs; dev iterations on ≤ 3 templates.

## Out of scope for v1

IF_PRESENT use in the brief (stored only), passive-update prompt changes beyond the lint-on-save
hook, UI changes.
