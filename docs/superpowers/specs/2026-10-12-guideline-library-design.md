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

1. **Schema proof.** Four systems, each with golden cases:
   - **Fleischner 2017** (a `table`);
   - **Bosniak 2019** (`rules`);
   - **BTS 2015** (`derive` → `score` → `band` → `rules`);
   - **TNM re-expressed in the schema.** It must reproduce all 6,479 verified combinations from
     `tnm_9th_clean.json` v2.2.

   **Gate:** if all four fit with no special-case attributes, the schema is sound. Fleischner and BTS are also the
   first sibling pair (§7.1).
2. **Coverage lab** on prod stack dictations, run alongside the **catalogue research task**. Together they set the
   authoring order.
   - **Gate:** N entries cover about 90% of correctly named systems.
   - **Gate:** negative controls yield no card that can be Applied.
3. **Rewire the preview to the engine.** The model settles inputs, code evaluates, and the output-index step is
   removed. **Gate:** zero wrong proposals on the preview lab; inputs settled and missing correctly; under 2 s.
4. **Frontend Tasks 14–19.** Apply appears only on pack and TNM cards. The Task 14 mock-up needs Hassan's approval
   first. Task 20, the review page, is dropped.
5. **Then:** the tier 2 parser lab, further packs in demand order, the monthly routine, and retiring prefetch (§10).

**Separately:** make the repo private (§11).

## 13. Out of scope

- A separate guideline service or a public API.
- Live editing of content in a database or admin UI.
- Embedding retrieval, unless the vocabulary shortlist proves too large (§5).
- Evaluating several lesions together inside the engine.
- Automatic publishing of any update.
