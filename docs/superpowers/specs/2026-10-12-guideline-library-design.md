# Guideline library: curated, executable guideline packs for the Scratchpad Copilot

Date: 2026-10-12. Branch `feat/scratchpad-copilot`. Agreed with Hassan in a grilling session (Q1–Q27) after the
step-back review (`docs/superpowers/handover/2026-10-12-copilot-evidence/stepback_review.md`).

This spec replaces the runtime web-retrieval back half of the Copilot spec
(`2026-10-12-scratchpad-copilot-design.md` §5.1 registry, §5.3 `resolve_guideline`, and decisions 2–5 and 17–21).
The front half of that spec stands: cards, Apply as the only path into the report, the enrichment line, the
Recommendations checklist, the matcher, the preview, and offline TNM.

## 1. Why

**Goal:** give the radiologist guideline help while they dictate, not after the report is written. The help has four
parts:
- cards for the systems that apply to each finding;
- quick reading;
- questions answered in context;
- an explicit Apply that adds a classification under the finding and a ticked recommendation under the conclusion.

**Constraints:** what reaches a report must be correct, and the flow must stay frictionless.

**Evidence from the seed lab:**
- About 26 of 30 rows fetched from real pages were correct.
- Whole tables were incomplete while still marked `checked`.
- The errors were confident and credited to the wrong source:
  - a flattened PDF table;
  - a poster's own scheme;
  - a study's rule;
  - another society's interval.

**Why runtime retrieval can't be fixed by tuning:**
- Pages that discuss a guideline outnumber the guideline itself.
- Checking rows one at a time can't notice a missing row.
- PDF tables flatten into rows that can be quoted but are wrong.

**Principle:** don't verify knowledge at request time. Curate it once, encode its decisions as data, and execute
them deterministically.

## 2. Decisions

1. **Two tiers in one library.**
   - **Tier 1 packs** hold executable decision logic. Only tier 1 packs and TNM can be Applied.
   - **Tier 2 reference entries** are structured and read-only. They serve the reading pane and Ask, and replace the
     "model-knowledge summary" on long-tail cards.
   - A tier 2 entry becomes tier 1 when its logic is added. No rewrite is needed.
2. **Breadth, UK-first, ordered by demand.**
   - Aim to cover as many bodies as we can.
   - A research task builds the catalogue: issuer, current edition, source URL, licence notes, and an estimated
     clinical frequency.
   - UK bodies come first: RCR, BTS, NICE, BSGAR, BSTI, BSUR, and UKHSA/NHS screening.
   - International systems used in UK practice come next: Fleischner, ACR \*-RADS, ESUR, ESGAR and ESR.
   - The coverage lab on prod dictations ranks the catalogue. Our own usage comes first and the literature estimate
     second.
3. **One entry has one issuing body.** Sources from different bodies are never merged. Where bodies disagree, their
   entries are siblings under one topic and appear side by side (§7.1). The library never picks one over another.
4. **The source of truth is git files, compiled into one bundle.**
   - Per-entry files live in the repo.
   - A build step validates them and compiles one versioned, immutable bundle, which is loaded into memory.
   - The database holds logs only, never content.
   - The alternatives were rejected:
     - Reading the files directly at runtime gives no single version and no one place for validation.
     - A database plus admin UI means building an audit trail and an approval flow, adds a runtime dependency, and
       gives live edits that the review gate rules out anyway.
5. **The library is a module inside the backend, not a separate service.**
   - It has a narrow, stateless, typed interface (§6).
   - It can be split out later if a second consumer appears. The bundle is the artefact a separate service would
     load.
6. **Updates are detected and drafted automatically, and published by a human.** Nothing is published without the
   hand read (§9).
7. **Every applied item records its version.** It stores `pack_id@version`, and the report stores the bundle version.
   Superseded versions stay in the bundle so old stamps still resolve.
8. **Facts are written in our own words, with citations and links.** No long verbatim passages or figures are
   copied.
9. **No retrieval or web calls at request time.** External calls happen only at authoring time and in the monthly
   update routine.
10. **The repo goes private** (§11). The publisher PDFs live in each entry's `sources/` folder.

## 3. Entry model

Each entry has four layers.

| Layer | Contents |
|---|---|
| **Inputs** | Typed. Numeric inputs have explicit inclusive or exclusive band edges. Each input has a `how_stated` hint (how a dictation would phrase it), prerequisites, and five states (§3.1). |
| **Logic** | A pipeline of six step types, all data-only (§3.2). Tier 1 only. |
| **Outcomes** | Classification, recommendation and caveats. Each carries a source locator. |
| **Reference** | Summary, definitions, tables and pitfalls. Each field has a stable field id and a locator. |

### 3.1 Input states

| State | Meaning | Example |
|---|---|---|
| `present` | It has a value. | "8 mm" |
| `absent` | Stated as not there. | "no calcification" |
| `unknown` | Not stated. It can be asked. | |
| `not_assessable` | Stated as impossible to assess. | TNM's X convention; "margins obscured" |
| `not_applicable` | A prerequisite is false. | a growth rate when there is no prior study |

The model never sets `unknown` or `not_applicable`. They follow from what is missing and from the prerequisites.

### 3.2 Logic step types

Steps run in order. Each step reads inputs or earlier step outputs, and writes one named value.

| Step | What it does | Rules |
|---|---|---|
| `derive` | Computes a value from inputs, e.g. volume doubling time. | A fixed formula from a small whitelist of operators, with no free code. |
| `table` | Maps a combination of discrete values and band ids to an outcome or value. | **No default rows.** Every combination in the input domain is listed. |
| `rules` | Boolean conditions: `all`, `any`, `none`, `count_gte`. | They must be mutually exclusive and exhaustive over the enumerated domain. |
| `score` | Linear or logistic. | Coefficients and intercept come from the source. |
| `band` | Maps a number to a band id. | Bands cover the whole number line exactly, with explicit edges. |
| `adjust` | Applies a ceiling, a floor, or a conflict rule (e.g. "the higher category wins"). | |

### 3.3 Sketch of `entry.json`

```json
{
  "id": "bts-pulmonary-nodule",
  "version": "2015.1",
  "topic": "pulmonary-nodule-solid",
  "issuer": "BTS",
  "system": "Guidelines for the investigation and management of pulmonary nodules",
  "edition": "2015",
  "tier": 1,
  "status": "current",
  "applies_to": {"region": ["chest"], "modality": ["CT"], "finding_type": ["nodule"], "context": ["incidental", "screening"]},
  "aliases": ["BTS nodule", "BTS 2015"],
  "inputs": [
    {"id": "diameter_mm", "type": "number", "unit": "mm", "how_stated": "maximum diameter in mm",
     "locator": {"source": "S1", "page": 12, "section": "4.1"}},
    {"id": "prior_volume", "type": "number", "unit": "mm3", "prerequisites": [{"input": "prior_study", "eq": true}]}
  ],
  "logic": [
    {"step": "band", "id": "size_band", "input": "diameter_mm",
     "bands": [{"id": "lt5", "max": 5, "max_inclusive": false}, {"id": "5to8", "min": 5, "max": 8, "max_inclusive": false},
               {"id": "ge8", "min": 8}]},
    {"step": "score", "id": "brock", "kind": "logistic", "terms": ["…"], "locator": {"source": "S2", "table": "3"}},
    {"step": "rules", "id": "pathway", "cases": [{"when": {"all": ["…"]}, "outcome": "ct_surveillance"}]}
  ],
  "outcomes": [
    {"id": "ct_surveillance", "classification": "…", "recommendation": "…", "caveats": ["…"],
     "locator": {"source": "S1", "page": 14, "table": "2"}}
  ],
  "reference": {
    "summary": [{"id": "sum.1", "text": "…", "locator": {"source": "S1", "page": 3}}],
    "definitions": [], "tables": [], "pitfalls": []
  }
}
```

A tier 2 entry has the same shape without `logic` or `outcomes`. Tables in `reference` are structured data (rows and
cells), not markdown.

### 3.4 Sources and locators (`manifest.json`)

```json
{"sources": [
  {"id": "S1", "role": "primary", "title": "…", "issuer": "BTS", "edition": "2015", "url": "…",
   "sha256": "…", "file": "sources/<sha256>.pdf", "retrieved": "2026-10-12"}
]}
```

- Each source has one of three **roles**:
  - `primary` is the guideline itself.
  - `amendment` is an erratum, update or addendum from the same issuer.
  - `explanatory` is a review article or a society explainer.
- Inputs, rules, bands, scores and outcomes may only cite `primary` or `amendment` sources.
- `explanatory` sources may shape tier 2 wording and pitfalls only.
- Every locator names a source id, plus a page and a table or section.

### 3.5 Golden cases (`cases.json`)

- Each case gives inputs (with states), the expected outcome id and the expected key trace steps.
- Cases come from the guideline's own worked examples first, then from cases we write.
- The cases we write must include values either side of every cut-off.

### 3.6 Input scope and eligibility

Agreed with Hassan on 2026-10-12. Not built yet: it is part of the next slice (§12).

**Two input attributes, both optional:**

| Attribute | Values | Default | Effect |
|---|---|---|---|
| `scope` | `lesion` \| `patient` | `lesion` | Lesion-scoped inputs are settled only from the card's own finding unit. Patient-scoped inputs are settled from the clinical history and the whole dictation, and their answers are shared across every card in the case. |
| `role` | `clinical` \| `eligibility` | `clinical` | Eligibility inputs encode the guideline's own scope statement: who and what the guideline applies to. They are evaluated and asked first. |

**Eligibility inputs:**
- **Source.** Eligibility inputs come only from the guideline's stated scope or exclusions, each with a locator like any
  other fact. We never invent our own criteria. Examples:
  - Fleischner: age under 35; lung cancer screening, immunocompromise or known primary cancer.
  - BTS: age under 18; a nodule already proven to be lung cancer or a metastasis. Previous or active cancer is not an
    exclusion (BTS covers these patients; the December 2015 correction makes small-nodule follow-up clinical
    judgement), so it stays a caveat.
  - Bosniak: an infectious, inflammatory or vascular lesion, or a haemorrhagic or necrotic solid mass.
- **Form.** They are usually yes/no inputs, patient-scoped or lesion-scoped as the clause reads. A pack may combine
  closely related exclusions into one input when the guideline treats them alike (Fleischner's screening,
  immunocompromise and known primary cancer are one input). Age is a separate number input with the shared fact
  `age_years`, banded at each guideline's own cut-off, so one answer serves every card in the case.
- **Logic.** An eligibility input that excludes leads to a `does_not_apply` outcome. Its classification states that
  the guideline does not apply and why, its recommendation says to manage on clinical context, and it carries the
  locator of the scope clause. It never has an Apply.
- **Settling.** The model settles eligibility inputs exactly as it settles clinical ones: verbatim quotes from the
  clinical history or the dictation, with the same checks. An unstated eligibility input stays unknown and is never
  assumed eligible.
- **Size.** A pack has at most three eligibility inputs. If a guideline's scope needs more, the scope belongs in the
  matcher's `applies_to` or in a pitfall, not in questions.

**Two layers of fit, kept separate:**

| Layer | Question | Mechanism | Visible to the radiologist |
|---|---|---|---|
| Finding fit | Is this the right kind of finding? (a renal cyst, not a liver cyst) | Silent Jev applicability gate in the matcher (§5) | No: the card never appears |
| Patient and context eligibility | Does this guideline apply to this patient? (not known cancer, not screening) | Eligibility inputs inside the pack | Yes: the eligibility strip (§7.4) |

**Shared answers.** Patient-scoped answers (settled or tapped) are held per case and passed to every card's preview as
`answered`. One answer to "known primary cancer?" serves the Fleischner and BTS cards alike. Inputs are matched across
packs by a shared vocabulary of patient facts (for example `known_primary_cancer`, `immunocompromised`,
`screening_programme`, `age_years`). An input that maps to no shared fact stays card-local.

## 4. Evaluation engine

**Who does what:**
- **The model** only settles inputs from the dictation. Every settled value carries a verbatim quote, which Jev checks
  (the existing preview rule).
- **Code** evaluates the logic and returns a **trace**. The trace records:
  - which steps ran;
  - which rules fired;
  - the inputs and quotes each step used;
  - the locators behind each one.
- **The trace feeds three things:**
  - the card's "why";
  - the record of what was applied;
  - the wording.
- **The model writes only from the trace or from reference fields,** citing field ids. The existing numeric check
  stays as the backstop.

**Partial evaluation.** When some inputs are `unknown`:
- the engine enumerates their domains (band ids for numbers);
- it reports which unknown inputs could still change the outcome, and only those are asked in the card;
- it shows the set of possible outcomes meanwhile.

An input whose value cannot change the outcome is never asked.

**Change to the preview.** The "model picks an output index" step goes away. The model settles inputs, code
evaluates, and code builds the proposal.

**Scope: one evaluation per lesion.**
- The host supplies context that spans lesions as ordinary inputs, e.g. the nodule count or the most suspicious
  nodule.
- The host handles aggregation across lesions.
- The engine never sees more than one lesion.

## 5. Matching

- **Controlled vocabulary.** Each entry's `applies_to` uses fixed vocabularies for region, modality, finding type and
  context.
- **Who fills each field:**
  - anatomy comes from the scratchpad region;
  - modality and protocol come from the scan type;
  - the matcher (gpt-oss with the Jev gate, as now) fills finding type and context.
- **Shortlist.** Entries whose `applies_to` matches form a closed shortlist, and the matcher picks from it. The
  matcher never invents an entry.
- **Embeddings.** A lexical or embedding prefilter is added only if the vocabulary shortlist grows too large to hand
  to the matcher whole.
- **Systems outside the library.** A system the matcher recognises but the library doesn't hold yields no card. Its
  name is logged as a demand signal for authoring (§9.3).

## 6. Runtime interface

A module `hybrid_stack/copilot/library/`:

| Function | Returns |
|---|---|
| `version()` | bundle version |
| `list(filter)` | entry ids and headers matching `applies_to` terms |
| `lookup(id, version=None)` | the entry, current version by default, any version on request |
| `evaluate(id, inputs) → Trace` | outcome or possible outcomes, the inputs still needed, and the trace |
| `siblings(topic)` | entries from other bodies on the same topic |

- **Loading.** The bundle is loaded once, at startup.
- **Failure.** If it fails to load or fails validation, the Copilot shows no library cards and logs an error. It
  fails open, like every other Copilot failure, and never crashes the app.

## 7. Into the card and the report

### 7.1 Disagreeing bodies

- Sibling entries on one topic render as compact columns on **one** card. Neither is preselected.
- A **department-preferred body** (a setting) only orders the columns and gives the preferred column a single-tap
  Apply. Nothing is ticked or applied until the radiologist taps.
- The radiologist applies **one** column. The column not applied is logged as seen but not applied.

### 7.2 Provenance

- `GateRecord.enrichments[]` already carries `key` and `version`. It gains `outcome_id` and a compact trace
  (rule ids and locators).
- The report stores the bundle version.
- When a pack is corrected, past reports that used the affected `pack_id@version` can be found.

### 7.3 Ask

- **Card in scope:** answers are grounded only in the open entry's fields and the evaluation trace, and cite field
  ids.
- **No answer in the entry:** Ask says so, then adds brief general knowledge prefixed "From general knowledge:", as
  now.
- **No gap search.** Ask never searches the web.

### 7.4 Card states and the eligibility strip

Agreed with Hassan on 2026-10-12. Not built yet: it is part of the next slice.

A pack card is always in one of three states, worked out from the preview:

| State | When | What the card shows |
|---|---|---|
| **Does not apply** | An eligibility input settles to an exclusion | The card dims and shows the reason, with the scope clause's citation. There is no Apply. |
| **Check first** | Some eligibility inputs are unknown and could change the outcome | A short "Does this apply?" strip of one to three yes/no chips, above everything else. The clinical questions and possible outcomes appear dimmed beneath it. |
| **Applies** | Every eligibility input is settled and eligible, or none can change the outcome | The normal card: the clinical questions (only those that can change the outcome), then the proposal. |

- **Ordering.** `Preview.asks` lists eligibility inputs before clinical ones. Within each group the order is the pack's
  input order.
- **Every ask is explained.** Each ask carries its definition, the outcomes it decides between with their citations,
  and the citation of the rule it feeds. These are the `asks` fields already built.
- **Once per case.** A patient-scoped answer given on one card fills that input on every other card in the case, and
  their previews re-run from the cache key, which includes the answers.
- **No questionnaires.** If a card would need more than three eligibility chips, the pack is wrong (§3.6 Size). The
  gates check this.
- **Logging.** `does_not_apply` outcomes and every tap on an eligibility chip are logged with the stack session, as
  data on how often guidelines are excluded and on which facts.

## 8. Quality gates

Every entry passes these before it merges. All except gate 6 run as pytest tests (`backend/tests/test_library_*.py`),
and the bundle build runs them. The repo has no GitHub Actions; a pre-commit hook or a workflow can wrap the same
tests later.

1. **Schema valid.**
2. **Verification by step type:**
   - discrete steps (`table`, `rules`) are enumerated in full, so every combination maps to exactly one result;
   - bands are checked to cover the number line exactly, with no gap or overlap at an edge;
   - scores are checked against the published calculator, including values either side of each cut-off;
   - downstream rules are enumerated over band ids.
3. **Golden cases pass.**
4. **Locators.** Every rule and outcome has a `primary` or `amendment` locator.
5. **Jev evidence check** of each field against its located source text. This is produced by the authoring run and
   recorded in the PR.
6. **Hand read and version bump.**
   - Claude reads the entry against the source.
   - Hassan reviews only the boundary items that the Jev check or the hand read flagged.
   - The version is bumped, and the superseded version is kept.

**Bundle drift test.** A test asserts that the committed bundle equals a fresh compile of `guidelines/`.

## 9. Operations

### 9.1 Layout

```
guidelines/<entry-id>/
  entry.json
  cases.json
  manifest.json
  sources/<sha256>.pdf        # publisher files; repo is private (§11)
backend/src/rapid_reports_ai/resources/guideline_bundle.json   # compiled, committed (beside tnm_9th_clean.json)
backend/scripts/guidelines/build_bundle.py
```

The source folders sit at the repo root. They are kept out of the deployed backend; only the bundle ships.

### 9.2 Authoring

- **Tier 1 logic and tables are written by hand from the primary source.**
- **A parser drafts tier 2 breadth.**
  - Candidates: LlamaParse (paid), Docling (local) and Firecrawl parse.
  - A lab chooses between them, on typical tier 2 sources (RCR and NICE guidance with prose and tables).
  - The lab scores cell-level table accuracy and section structure.
  - Paying is acceptable if the paid tool wins. Parsing runs only on new or updated sources, never on every build.
- **The copilot's fetch code** (`registry.py`, `search.py`, `fetch.py`, and the Jev evidence gates) becomes the
  authoring tool. It finds candidate sources and drafts fields for review. It never feeds runtime.

### 9.3 Monthly update routine

A scheduled Claude routine does the following:

1. A script runs Tavily, already integrated:
   - one query per entry: "<issuer> <system> latest edition, update or erratum after <edition date>";
   - one broad sweep per UK body, which catches **new** guidelines as well as updates.
2. Claude reads the results against each manifest. It sorts each into no change, possible update, or new guideline.
3. Each actionable item becomes a GitHub issue labelled `needs-triage`, with links to the evidence. When nothing has
   changed, no issue is opened.
4. Hassan relabels a real item `ready-for-agent`. That starts an authoring run, which drafts a new version as a PR
   with its gate results.

The names logged from long-tail matches (§5) and from ask demand feed the same triage queue.

## 10. Retirement

- **Prefetch** (`guideline_prefetch.py` and its request-time Tavily calls) is **removed outright**, with no shadow
  period. It is removed once the post-generation review rail reads guideline content from the library instead.
- **Follow-on removals:** `guideline_fetcher.py`, `tnm_lookup.py` and the pgvector TNM table follow once the library
  covers what they serve.

## 11. Repo privacy

Checked on 2026-10-12. Nothing in the repo depends on it being public:
- There are no GitHub Actions workflows, so the private-repo minute limit doesn't apply.
- No branch protection or rulesets are set.
- There are no webhooks, no Pages site and no forks.
- The code contains no links to its own GitHub URLs.

Steps:
1. Confirm at github.com/settings/installations that the Railway and Vercel GitHub apps can see this repo.
2. Switch the repo to private.
3. Push a test commit and confirm both deploys.

What we accept:
- **TNM history.** TNM data has been public on `main` since April 2026 (`6779495`), and the rebuilt v2.1/v2.2 data is
  on pushed branches. Making the repo private stops further exposure but does not recall copies already made.
- **Secret scanning.** GitHub's free secret scanning for public repos is lost.

## 12. First slice

Status (2026-10-12): items 1 and 2 done, item 3 **failed** its gate, item 4 not started.

1. **Schema proof. DONE, PASSED.** Four systems, each with golden cases: Fleischner 2017 (`table`), Bosniak 2019
   (`rules`), BTS 2015 (`derive` → `score` → `band` → `rules`), and TNM re-expressed in the schema (all 6,479 verified
   combinations from `tnm_9th_clean.json` v2.2). All four fit with no special-case attributes. Two general changes
   were needed (see "Changes the build made" below). Fleischner and BTS are the first sibling pair (§7.1). Result:
   `docs/superpowers/handover/2026-10-12-copilot-evidence/schema_proof.md`.
2. **Coverage lab. DONE, one gate mitigated.** Ran on prod `reports` dictations (the hybrid stack is not deployed, so
   no stack logs exist): 333 of 393 reports (60 rate-limited). Precision 55.8%, recall about 60%.
   - **Coverage gate: met.** N at 90% is 22 raw, 27 de-duplicated, of 47 systems seen. Only 3 of the top 25 have
     packs; 10 of the top 25 are missing from the catalogue.
   - **Negative-control gate: initially FAILED.** 9 Apply-able false cards in 100 wrong namings (17 across all 240).
     Mitigated by a Jev applicability gate for pack cards (§5): offline, 0/15 false passes and recall 25/33.
     Fleischner recall of 3/9 is weak. Not yet re-run end to end.
   - Result and authoring order: `docs/guidelines/coverage-lab-2026-10.md`.
3. **Rewire the preview to the engine. BUILT, GATE FAILED.** The model settles inputs, code evaluates, and the
   output-index step is removed. Preview lab run 2: **1 wrong proposal** (BTS: size, upper lobe and benign features
   were settled from a different lesion in the same dictation, a calcified granuloma; every quote was verbatim, so
   nothing caught it), 29/30 outcomes, **p95 3568 ms against the 2 s target**. Result:
   `docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab.md`.
   - **Proposed fix (not built):** give each input a scope (lesion or patient). Lesion-scoped quotes must come from
     the card's own finding unit, not the whole dictation. Latency needs a smaller settle prompt or a faster model.
   - **Frontend must not start Apply until this passes** a re-run of the preview lab.
4. **Frontend Tasks 14–19.** Apply appears only on pack and TNM cards. The Task 14 mock-up needs Hassan's approval
   first. Task 20, the review page, is dropped. Blocked on item 3.
5. **Then:** the tier 2 parser lab, further packs in coverage-lab order, the monthly routine, and retiring prefetch
   (§10).

**Next slice (agreed with Hassan on 2026-10-12, after the big-picture review):**
1. **Per-finding settling.** Add `scope` (§3.6) and a `finding` request field. Lesion quotes must be verbatim in the
   card's own unit. Code reads numbers and units from the quote, using one conversion table. One batched Jev check,
   "the FINDING states `<label>`: `<value>`", runs for enum and yes/no inputs.
   *Result (fix rounds 1, 3, 4 and 5):* a number is read from the whole measurement its quote sits in, and Jev checks
   numbers too. A lesion number settles only when its finding describes one lesion: (1) the finding holds no other
   number (digits or number words such as "eight", "two", "both"), apart from the same reading again, image
   references, dates and years, anatomical labels (segment 6, S6, T4, L2/3, rib 5) and "single"/"solitary"; (2) no
   multiplicity word (further, other, another, scattered, bilateral, …, or the plural of the pack's finding type),
   except in an unqualified negation such as "No other pulmonary nodules" (a qualifier such as new, enlarging,
   changed or "apart from" keeps it); a label or image number is never one that a connector (x, by, to, -) follows;
   and (3) Jev scores "The FINDING describes only one <finding type>" at 0.8 or more, asked in the same lesion
   batch. Anything else ("8 and 4 mm", "two nodules", "further subcentimetre nodules", a prior size) asks it.
2. **Eligibility triage.** Add `role: eligibility` (§3.6) with shared patient answers, and the three card states and
   the eligibility strip (§7.4). The existing packs' scope clauses become eligibility inputs: Fleischner's exclusion
   input is reclassified, and BTS and Bosniak gain theirs from the source. The gates enforce at most three eligibility
   inputs, each with a scope-clause locator.
3. **Preview cache.** Run the preview when the card is produced and cache it by (pack, unit text, history, answered),
   so opening a card is instant.
4. **Preview lab re-run.** Add cases with clinical history, two lesions in one sentence, eligibility exclusions stated
   in the history, and shared patient answers across two cards. This lab is the gate for Apply.
5. **Lookup packs and reference cards** for the graded systems that lead real use (CAD-RADS 2.0, CAC-DRS, then tier 2
   cards for Outerbridge, Lund-Mackay, AO Spine, Stoller and SINS), using the light authoring procedure.

**Changes the build made to §3, §4 and §5:**
- **§3 inputs:** numeric inputs may declare `min_value` / `max_value` ranges. The engine rejects out-of-range values,
  domains sample inside the ranges, and `verify` checks `derive` steps over them (fixes ln(0) and 0÷0 in BTS).
- **§4 partial evaluation:** when the set of possible outcomes has exactly one member, the outcome is settled even if
  inputs are unknown. No proposal is built with an unfilled placeholder.
- **§5 pack applicability gate:** pack cards pass a Jev yes/no check built from the pack's `applies_to`, threshold
  `PACK_GATE_MIN`, fail closed. Explicit asks that name a system bypass the gate, as TNM does.

**Separately:** make the repo private (§11).

## 13. Out of scope

- A separate guideline service or a public API.
- Live editing of content in a database or admin UI.
- Embedding retrieval, unless the vocabulary shortlist proves too large (§5).
- Evaluating several lesions together inside the engine.
- Automatic publishing of any update.
