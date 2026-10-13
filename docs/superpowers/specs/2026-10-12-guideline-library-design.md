# Guideline library: curated, executable guideline packs for the Scratchpad Copilot

Date: 2026-10-12. Branch `feat/scratchpad-copilot`. Agreed with Hassan in a grilling session (Q1–Q27) after the
step-back review (`docs/superpowers/handover/2026-10-12-copilot-evidence/stepback_review.md`).

This spec replaces the runtime web-retrieval back half of the Copilot spec
(`2026-10-12-scratchpad-copilot-design.md` §5.1 registry, §5.3 `resolve_guideline`, and decisions 2–5 and 17–21).
The front half of that spec stands: cards, Apply as the only path into the report, the enrichment line, the
Recommendations checklist, the matcher, the preview, and offline TNM.

**Amended 2026-10-13** (Hassan approved the redesign after the settling root-cause review,
`.superpowers/sdd/2026-10-13-guideline-library-next-slice/settling-root-cause-review.md`): the card becomes a visible
draft with a Calculate step (§7.4–§7.10), the safety rule becomes "nothing reaches the report unseen" (§7.10), and the
preview lab gives way to the real-dictation lab, which reports metrics with recommendations so that Hassan can decide
whether to enable Apply (§12, "Draft card slice"). Plan:
`docs/superpowers/plans/2026-10-13-guideline-draft-card.md`.

## 1. Why

**Goal:** give the radiologist guideline help while they dictate, not after the report is written. The help has four
parts:
- cards for the systems that apply to each finding;
- quick reading;
- questions answered in context;
- an explicit Apply that adds a classification under the finding and a ticked recommendation under the conclusion.

**Constraints:** what reaches a report must be correct, and the flow must stay frictionless. Safety rule (2026-10-13,
§7.10): **nothing reaches the report unseen**. Every value behind an applied result is shown to the radiologist, who can
change it, and Apply writes only the result of a Calculate the radiologist tapped.

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
| **Outcomes** | Classification, recommendation and caveats. Each carries a source locator. An optional short `category` label from the source (2026-10-13) lets checker mode recognise a dictated category (§7.8). |
| **Reference** | Summary, definitions, tables and pitfalls. Each field has a stable field id and a locator. Optional `links` (2026-10-13) tie a field or a table row to the outcome, step value or input value it describes (§7.11). |

### 3.1 Input states

| State | Meaning | Example |
|---|---|---|
| `present` | It has a value. | "8 mm" |
| `absent` | Stated as not there. | "no calcification" |
| `unknown` | Not stated. It can be asked. | |
| `not_assessable` | Stated as impossible to assess. | TNM's X convention; "margins obscured" |
| `not_applicable` | A prerequisite is false. | a growth rate when there is no prior study |

The model never sets `unknown` or `not_applicable`. They follow from what is missing and from the prerequisites. The
radiologist may set `unknown` by choosing "Not stated" on the card (§7.6); `not_applicable` only ever follows from a
prerequisite.

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
  clinical history or the dictation, with the same checks and the same value states (§7.5). An unstated eligibility
  input stays unknown (asked) and is never assumed eligible.
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
- **The model** only proposes input values from the dictation. Every proposed value carries a verbatim quote. Code reads
  numbers from the quote and, with one batched Jev claim per scope, decides each value's state: read, pre-filled or
  asked (§7.5). Nothing the model proposes reaches the report unless the radiologist sees it and taps Calculate (§7.10).
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
evaluates, and code builds the proposal. (2026-10-13: the preview builds the draft and a draft outcome; only Calculate,
over the values the radiologist confirmed, builds the result that Apply writes, §7.7.)

**Scope: one evaluation per lesion.**
- The host supplies context that spans lesions as ordinary inputs, e.g. the nodule count or the most suspicious
  nodule.
- The host handles aggregation across lesions.
- The engine never sees more than one lesion.

## 5. Matching

Revised 2026-10-13 after the matching lab (152 hand-selected production cases: the gpt-oss → name → Jev-gate path
found 67/184 expected topics; one Jev choice per finding found 169/184). Hassan approved the change.

### 5.1 Two kinds of pack

- **Finding-triggered** (`trigger` includes `"finding"`): incidental and lesion guidelines (nodule, adrenal, renal
  cyst, thyroid, ovarian, AAA, fractures, SINS…). An abnormal finding unit triggers them. A normal unit never does:
  "no nodule" gives no card.
- **Exam-level** (`trigger` includes `"exam"`): reporting frameworks that score the whole examination (CAD-RADS on a
  coronary CT angiogram, CAC-DRS on a calcium-score study, ASPECTS on hyperacute stroke CT, Lund-Mackay on sinus CT
  for chronic rhinosinusitis, the NHS AAA Screening Programme on a programme aortic ultrasound). The study's identity
  binds them, whatever is dictated, and a normal study settles to its normal outcome (e.g. CAD-RADS 0). A pack may carry
  both triggers (CAC-DRS: exam-level on a calcium-score study, finding-triggered for coronary calcification seen on any
  other CT). NHS AAA is exam-level only: an aneurysm seen on an ordinary scan gets no card. PI-RADS scores
  lesions and defines no study-level normal outcome, so it is finding-triggered (2026-10-13 clinical review).
- An exam-level entry may carry `exam_presets`: input values its exam implies (NHS AAA: programme scan, male, not
  treated). Only the exam card gets them; they are the one pre-fill without a quote, shown on the card as set by the
  exam (`Settled.by = "exam"`), and a value the dictation states, or an answer, overrides them (§7.10).
- Each entry carries `purpose`: one or two sentences, from its own source, on what the system is for and in what
  setting. No thresholds, categories or eligibility lists (those stay on the card). Exam-level entries also carry
  `exam`: a one-line description of the study that binds them.

### 5.2 Who decides what

- **Per case** (cached by scan type + referral): one Jev request reads SCAN TYPE and CLINICAL HISTORY and answers
  (a) the imaging modality (CT / MRI / US / XR / other), as a choice, and (b) for each exam-level pack, whether this
  study is its `exam`, as a yes/no.
- **Per new abnormal finding unit** (cached by scan type + referral + unit text): one Jev choice over the
  finding-triggered topics, each option built in code from the entries' names, `purpose` and `applies_to`
  (finding type, region, modality), plus "none". Topics, not packs: siblings (BTS/Fleischner, RCOG pre/post) are one
  option and become columns on one card; CAC-DRS and CAD-RADS are offered as one coronary option. A pick below the
  confidence floor is "none".
- **Code**: maps the topic to its packs; drops a pack whose `applies_to.modality` excludes the resolved modality (an
  "other" or failed modality drops nothing); merges an exam-bound pack with the same pack picked by a finding into one
  card; applies the per-finding and per-case caps.
- **Exam-level cards** settle from the whole dictation (normal units included), not from one finding unit.
- **Failure**: a failed Jev request yields no library card for that finding or case and caches nothing (fails open).
- **No gpt-oss in library matching.** The gpt-oss matcher (registry systems from model knowledge, TNM) moves to an
  explicit, on-demand "other guidelines" request; it no longer runs on every finding.
- **Systems outside the library** yield no library card; a named one is logged as a demand signal (§9.3).

### 5.3 Card weight

A pre-resolved normal exam-level outcome (CAD-RADS 0, CAC-DRS 0) renders as a quiet one-line card with a single
insert; it never prompts for optional inputs. It is still seen before it reaches the report (§7.10), and Apply stays
off until Hassan enables it.

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
  (rule ids and locators), and (2026-10-13) each value Calculate used with its state (read, pre-filled, answered or
  edited) and quote, so an applied result shows which values the radiologist confirmed without changing.
- The report stores the bundle version.
- When a pack is corrected, past reports that used the affected `pack_id@version` can be found.

### 7.3 Ask

- **Card in scope:** answers are grounded only in the open entry's fields and the evaluation trace, and cite field
  ids.
- **No answer in the entry:** Ask says so, then adds brief general knowledge prefixed "From general knowledge:", as
  now.
- **No gap search.** Ask never searches the web.

### 7.4 The draft card

Agreed with Hassan on 2026-10-13, after the settling root-cause review. This replaces the card states of 2026-10-12,
which kept "asked, never wrong" (§7.10). Not built yet: see `docs/superpowers/plans/2026-10-13-guideline-draft-card.md`.

**What the card is.** A quick fact check against the source. It shows what the guideline needs to decide this
finding. It drafts each value from the dictation, with the quote that value came from, and lets the radiologist
correct any value in place. It then calculates the classification or recommendation from the confirmed values, with
citations. Apply writes that result and nothing else.

**Flow:**
1. **Paint.** The card opens with the pack's reference body and the inputs that decide the outcome, in `needed`
   order. Painting needs no model call.
2. **Draft.** The settlement (prewarmed by /match, cached per §12) gives each input one of the value states in §7.5.
3. **Which lesion?** If the finding describes more than one lesion, the card asks that one pick before anything else
   (§7.9).
4. **Eligibility.** Unknown eligibility inputs that could change the outcome lead the card, as "Does this apply?"
   rows.
5. **Edit.** The radiologist can change any value inline (§7.6).
6. **Calculate.** The engine runs over the confirmed values (§7.7).
7. **Apply.** Writes the last Calculate result (§7.7).

**Order of `needed`:**
- Eligibility inputs come first, then parent inputs, then the rest. Within each group the order is the pack's input
  order. A parent input is one that some other input's prerequisite tests.
- An input behind a prerequisite that is still unknown is not asked yet. It is listed in `waiting` and appears only
  once its parent is known and applicable. For BTS, the five follow-up inputs appear only after "prior study: Yes".
- If a waiting input could change the outcome, its unknown parent is asked in its place.
- An input whose value cannot change the outcome is never asked (§4).

**Card states**, worked out in code from the preview:

| State | When | What the card shows |
|---|---|---|
| **Which lesion** | The finding describes more than one lesion, and no span has been picked yet | The verbatim lesion spans to pick from. Patient inputs are drafted; lesion inputs wait for the pick. |
| **Does not apply** | An eligibility input (read, pre-filled, answered or edited) excludes | The card dims and shows the reason with the scope clause's citation. Changing that value brings the card back. There is no Calculate and no Apply. |
| **Check first** | Some eligibility inputs are unknown and could change the outcome | One to three "Does this apply?" rows above everything else. The clinical values appear dimmed beneath them. |
| **Applies** | Every eligibility input is known and eligible, or none can change the outcome | The draft values in `needed` order, the draft outcome, and Calculate |

**Unchanged from 2026-10-12:**
- **Every ask is explained.** Each asked input carries its definition, the outcomes it decides between (with their
  citations), and the citation of the rule it feeds. These are the existing `asks` fields.
- **Once per case.** A patient-scoped answer given on one card fills that input on every other card in the case, as
  an answered value. Their previews re-run from the cache, keyed by the answers.
- **No questionnaires.** A card needing more than three eligibility rows means the pack is wrong (§3.6 Size).
- **Logging.** `does_not_apply` outcomes and every eligibility answer are logged with the stack session.

### 7.5 Value states

Each input on the card is in exactly one state:

| State | When | How it is shown |
|---|---|---|
| **Read** | Code read the value with certainty. One of: **(a)** a number that `quantity.settle` reads as one value; for a lesion input, its finding holds no other number (`quantity.alone`). **(b)** An enum option that appears in its quote, with no negation or hedge before it. Either way, the scope's batched Jev claim must confirm it, and a lesion value also needs a finding that describes one lesion. An attenuation must also be stated as unenhanced. Booleans and the states (absent, not assessable) are never read. | Plainly, with its quote available |
| **Pre-filled** | Any other value the model proposes with a quote that is verbatim and in scope (§3.6) | Highlighted, with its quote and the reasons it is not read |
| **Asked** | No value was proposed; or the quote is not verbatim in scope; or a number cannot be read (a range, a bound, a fraction, an unknown unit, out of range); or the input is demoted (below) | Empty, with the `asks` explanation |
| **Answered** | The radiologist set the value, on this card or as a shared patient answer | As set; an answer always wins over a draft |

- **Quotes only.** A value is never pre-filled from inference alone. The model still leaves out anything not stated,
  and a proposal without a verbatim quote is dropped.
- **Highlight reasons.** Guards that used to force an ask now only say why a value is pre-filled rather than read:
  - another number in the finding (`alone`);
  - a negation or hedge before the quote (`_MODIFIER`);
  - an attenuation not stated as unenhanced (the HU phase claim);
  - the scope's Jev claim scoring below its bar;
  - the Jev call failing.
- **Jev failure.** Nothing is read; every proposal is pre-filled. The card is otherwise usable.
- **Demotion.** The real-dictation lab reports each input's pre-fill error rate and recommends which inputs to demote
  (§12). Hassan decides. A demoted input's proposals are dropped and it is asked. The list lives in code, by pack and
  input, with the lab run behind it.

### 7.6 Inline edit

- **Every value is editable in place**, whatever its state: read, pre-filled, asked or answered.
- **The choices are:**
  - the input's own options: the enum options, Yes/No, the band labels, or a typed number read as a quote would be;
  - the states the input allows: "Absent" and "Not assessable";
  - "Not stated" (`unknown`), which is always offered.
- **`not_applicable` is never chosen.** An input whose prerequisite is false shows "N/A" and changes only when its
  parent is edited.
- **An edit is an answer.** It re-runs only the engine over the cached settlement (`finish`), with no model or Jev
  call, so nothing else on the card moves.
- **Every edit is logged** with the value and state before and after, as data on automation bias.

### 7.7 Calculate and Apply

- **The draft outcome.** The preview runs the engine over the draft (read and pre-filled values, plus answers) and
  shows the outcome as a draft, labelled "on these values". It can never be applied.
- **Calculate** runs the engine over the confirmed values: every value as the card shows it, with each edit. The tap
  confirms every value shown. Calculate makes no model or Jev call and is deterministic. It returns:
  - the classification, recommendation and caveats as the entry words them;
  - the citations of the steps that fired and of the outcome;
  - each value used, with its state and quote;
  - the trace;
  - `pack_id@version` and the bundle version.
- **No guessing.** If an input that could change the outcome is still unknown, Calculate returns no outcome. It
  returns the possible outcomes and what is still needed.
- **Exclusions.** A `does_not_apply` result is shown as the exclusion and never applied.
- **Apply** writes exactly the last Calculate result: the classification line under the finding, and the ticked
  recommendation under the conclusion. Any edit after Calculate clears that result, so Apply needs a fresh
  Calculate.

### 7.8 Checker mode

- **When it starts.** The finding states the pack's category. That means a short `category` label on an outcome, from
  the source, quoted verbatim in the finding and confirmed by Jev in the lesion batch, as in "Bosniak IIF". The card
  then checks the dictated category instead of computing one.
- **How it checks.** The engine runs over the draft values, and D is the set of outcomes with the dictated category:
  - **Agrees:** the draft outcome is in D, or every possible outcome is. Calculate gives the guideline's result for
    that category.
  - **Disagrees:** no outcome in D is still possible. A flag shows the computed category, or the possible ones, and
    the values and citations behind it. The radiologist can correct a value, which re-checks it.
  - **Cannot be checked:** some outcome in D is still possible, but the draft reaches no outcome. Calculate uses the
    dictated category. If D holds more than one outcome, only the inputs that choose between them are asked.
- **Lookup packs** have no checker mode, because their category is itself an input and the dictated grade is a value
  (CAD-RADS, CAC-DRS, SINS).
- **The checker never writes text by itself.** A settling error can only cause a wrong flag. A missed flag leaves
  things as they are today.

### 7.9 Which lesion?

- **Trigger.** The finding describes more than one lesion of any kind. Either the Jev one-lesion claim in the lesion
  batch scores below its bar, or the settle call lists two or more lesion spans.
- **The ask.** The card asks once. It offers the verbatim spans, each checked in code as verbatim in the finding.
  The radiologist picks one, and the card drafts the lesion inputs from that span alone. Patient inputs are not
  affected.
- **No usable spans.** Fewer than two verbatim spans means no pick; the lesion inputs are asked.
- **Showing the pick.** The picked span is shown on the card and carried in the Calculate result.
- **Latency.** The settlement of each span is prewarmed, a bounded number of them, as soon as the spans are known.

### 7.10 Safety rule and the reversal

**The rule: nothing reaches the report unseen.**
- Every value behind an applied result is shown on the card, with its state and quote, and the radiologist can change
  it.
- Apply writes only the result of a Calculate that the radiologist tapped over those values.
- Code still reads every number and the engine still decides.
- Every word of the result comes from the entry.
- A value is shown as read only when code read it with certainty. No value is pre-filled from inference alone.

**Reversal, recorded 2026-10-13 (Hassan).** This replaces two rulings:
- **"Asked, never wrong":** every value not confirmed was asked, and no unconfirmed value was shown.
- **"No chips":** no confirmable value chips on the card.

**Why.** "Asked, never wrong" held (preview lab run 2 had 0 wrong values) while friction got worse:
- on the same 41 cases, mean asks rose from 4.0 to 4.4, and cards with 2 asks or fewer fell from 58.5% to 39%;
- across all 51 cases the mean was 5.47, and two-lesion cards averaged 9.7.

The cause was a false premise: a finding unit is a sentence, not a lesion. Every guard turned a doubt into a tap, and
the list of guards could never be finished. Of the 279 asks, 174 were inputs the dictation never stated and about 105
came from guards.

**The trade.** The card can now show a wrong pre-filled value. It can no longer put a value into the report without
the radiologist seeing it.

**Containment:**
- pre-fills are highlighted and never shown as read;
- nothing is pre-filled from inference;
- edits are logged;
- an input can be demoted to asked when Hassan decides so from the real-dictation lab's pre-fill error rates (§12).

### 7.11 Case-aware reference

Agreed with Hassan on 2026-10-13.

**What it does.** When the card opens, its reference section highlights the rows, bands, definitions and pitfalls
that match what has been read, dictated or calculated, for example:
- Fleischner: the 6–8 mm solid row;
- Bosniak: the IIF definition;
- CAD-RADS: the category 3 line and its footnote.

The rest of the reference stays available, collapsed.

**How it works:**
- **Explicit links in pack data.** A reference text item (summary, definition or pitfall), a whole reference table,
  or a single table row may carry `links`. Each link names the id it describes:
  - an outcome;
  - a step's value: a band id, a table or rules result, or an adjust id;
  - an input's value: an enum option, true or false, or a band id.
- **No text matching**, ever.
- **Hits come from the engine trace.** The trace already records the outcome reached, each step's value (band ids,
  table rows, rules results) and each present input. Hits are worked out from the trace of the draft, then from the
  trace of the last Calculate. In checker mode the dictated category's outcomes also count as hits.
- **No links, no highlight.** A pack with no links highlights nothing, and the card shows the full reference
  expanded, as it does today.
- **The verify gate** checks that every link names a real outcome, step, input and value of the entry, and that a
  table's row links line up with its rows.
- **The API.** The preview and the Calculate result each carry `highlight`:
  - `linked`: whether the pack has any links;
  - the reference field ids hit;
  - the row indices hit in each table.

  The UI expands what is hit and collapses the rest.

**Links on the existing packs** are added as a follow-up, most dictated first: CAD-RADS, CAC-DRS (Agatston),
Fleischner, BTS, Bosniak, PI-RADS.

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
   - **Frontend must not start Apply until this passes** a re-run of the preview lab. (Superseded 2026-10-13: the
     real-dictation lab reports metrics and Hassan decides on Apply; see "Draft card slice" below.)
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
   *Superseded 2026-10-13* (see "Draft card slice"): (1) and (3) now only make a value pre-filled rather than read,
   and (3) triggers "Which lesion?". (2) is retired.
2. **Eligibility triage.** Add `role: eligibility` (§3.6) with shared patient answers, and the three card states and
   the eligibility strip (§7.4; folded into the draft card on 2026-10-13). The existing packs' scope clauses become eligibility inputs: Fleischner's exclusion
   input is reclassified, and BTS and Bosniak gain theirs from the source. The gates enforce at most three eligibility
   inputs, each with a scope-clause locator.
3. **Preview cache.** Run the preview when the card is produced and cache it by (pack, unit text, history, answered),
   so opening a card is instant.
4. **Preview lab re-run.** Add cases with clinical history, two lesions in one sentence, eligibility exclusions stated
   in the history, and shared patient answers across two cards. This lab decided Apply until 2026-10-13.
   *Result (run 2, HEAD 4341832, 3bf81c0):*
   - passed, marginally: 0 wrong values and 0 wrong proposals;
   - (b) p95 was 1991 ms against the 2000 ms bar, with BTS alone at 3300 ms;
   - friction got worse: mean asks 5.47, and only 31% of cards had 2 asks or fewer.

   Apply was not switched on. The lab is now a regression suite only, because its phrasings were invented and its
   truth maps were written by the fixer. Results: `docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab_next_slice.md`.
5. **Lookup packs and reference cards** for the graded systems that lead real use (CAD-RADS 2.0, CAC-DRS, then tier 2
   cards for Outerbridge, Lund-Mackay, AO Spine, Stoller and SINS), using the light authoring procedure.

**Changes the build made to §3, §4 and §5:**
- **§3 inputs:** numeric inputs may declare `min_value` / `max_value` ranges. The engine rejects out-of-range values,
  domains sample inside the ranges, and `verify` checks `derive` steps over them (fixes ln(0) and 0÷0 in BTS).
- **§4 partial evaluation:** when the set of possible outcomes has exactly one member, the outcome is settled even if
  inputs are unknown. No proposal is built with an unfilled placeholder.
- **§5 pack applicability gate:** pack cards pass a Jev yes/no check built from the pack's `applies_to`, threshold
  `PACK_GATE_MIN`, fail closed. Explicit asks that name a system bypass the gate, as TNM does.

**Draft card slice (agreed with Hassan on 2026-10-13, after the settling root-cause review):**

Plan: `docs/superpowers/plans/2026-10-13-guideline-draft-card.md`.

**Banked from the next slice:**
- run 2's 0 wrong values is the state of the code;
- Apply is off, and Hassan decides when to enable it;
- guard rounds stop;
- packs continue unaffected.

**Build:**
1. **Parent questions first.** `needed` lists eligibility inputs first, then parent inputs. An input behind an
   unknown prerequisite waits (§7.4).
2. **The real-dictation lab**, run first on today's settler as the baseline.
3. **Value states and Calculate** (§7.5–§7.7).
4. **Retire and demote guards.** These are retired:
   - the per-input "QUOTE states" Jev claim;
   - `_no_prior` and its regexes and claims (`_FOLLOW_UP`, `_ELSEWHERE`, `_PRIOR_WORD`, `PRIOR_MENTIONED`,
     `HISTORY_MENTIONED`). prior_study is now proposed like any input, and asked first as a parent;
   - `quantity.many`, with `_ORGANS` and the negation-slot allowlist (`_QUALIFIER`, `_MANY_WORDS`).

   These are demoted to highlight reasons (§7.5): `quantity.alone`, the Jev one-lesion claim (now the trigger for
   "Which lesion?"), `_MODIFIER`, and the HU phase claim.

   These are kept:
   - the engine and the packs;
   - scope and eligibility;
   - the verbatim check;
   - `quantity.readings` and `quantity.settle`, with their refusals;
   - the Settlement/`finish` split and the cache;
   - one batched Jev claim per scope.
5. **Case-aware reference** (§7.11), then links on the existing packs, most dictated first.
6. **Checker mode** (§7.8). Outcomes gain an optional `category` label from the source.
7. **"Which lesion?"** (§7.9).
8. **Re-run the real-dictation lab**, report the metrics beside the baseline with recommendations, and write the
   results here. Hassan decides whether to enable Apply.
9. **Frontend.** No Copilot card UI exists on this branch. The plan builds the backend contract (/open, /preview and
   /calculate). The card UI and the Task 14 mock-up are a separate plan, and Hassan approves the mock-up first.

**Real-dictation lab: metrics reported with recommendations; Hassan decides whether to enable Apply.** It replaces
the preview lab. It has no automatic pass or fail.
- **Sample.**
  - About 100 production findings, read only through Metabase from `reports` (scan type, clinical history,
    findings). They are grouped offline by the stack grouper, matched by the matcher with the pack gate, and spread
    across packs.
  - About 20 cases that Hassan dictates in his own style, without seeing the guards.
  - All of it stays in the session scratchpad and is never committed.
- **Truth.**
  - An independent Claude Opus 5.5 subagent labels every input of every card. It is read-only on code, and has every
    pack's `sources/` folder and the entry itself. The harness writes the cards and a labelling brief, and validates
    the labels it gets back. Labels are made once and reused.
  - For each input it gives the value or "not stated", with the quote and the source locator. It also gives the
    lesion spans and any dictated category.
  - It never sees the settler's output.
  - Hassan spot-checks the boundary items: those the labeller flags, every disagreement between labeller and settler,
    and any card the labeller could not label. His verdict wins. The fixer never writes truth.
- **Reported, against reference targets (not automatic gates):**
  - wrong values shown as **read**, with each case named. The reference target is 0.
  - Taps to Calculate, as the median and the distribution. The reference target is a median of 2 or fewer. Taps are
    counted until Calculate returns an outcome when it is filled from truth. They are:
    - an answer to each asked input the engine needs;
    - a correction of each wrong draft value;
    - the "Which lesion?" pick.

    The Calculate tap itself is not counted.
  - The pre-fill error rate (wrong pre-fills over pre-fills) for each input.
- **Also reported:**
  - wrong pre-fills overall;
  - Calculate's outcome against the outcome truth gives;
  - how often the category is dictated, and how correct checker-mode flags are;
  - how often "Which lesion?" is shown, and how correct the picked spans are;
  - time to first paint and time to the draft (p50 and p95);
  - degraded rows.
- **Recommendations.** The report ends with recommendations: whether to turn Apply on, which inputs to demote to
  asked (§7.5), and what to fix next. Then it stops for Hassan's decision.
- **A wrong value during a run** is reported, not tuned. Hassan decides what follows.
- **Regression.** The 51-case preview lab stays as a regression suite only.

*Results:* written here by plan task G.

**Separately:** make the repo private (§11).

## 13. Out of scope

- A separate guideline service or a public API.
- Live editing of content in a database or admin UI.
- Embedding retrieval, unless the vocabulary shortlist proves too large (§5).
- Evaluating several lesions together inside the engine.
- Automatic publishing of any update.
