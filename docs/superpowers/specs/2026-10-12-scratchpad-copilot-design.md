# Scratchpad Copilot: guideline cards, card threads and recommendations, before Generate

Date: 2026-10-12. Branch `feat/scratchpad-copilot`, cut from `feat/hybrid-stack` (PR #31). It ships as part of the new
scratchpad layout.

## 1. Why

Guideline and classification help comes after Generate today:
- The prefetch starts at Generate. Synthesis runs in `/api/reports/{id}/enhance`.
- The chat (`/api/reports/{id}/chat`) can only edit a finished report.

Radiologists use guidelines while they read, not after. The scratchpad already asks for every clinical statement before
Generate (the checklist model). The Copilot brings guideline knowledge into that same moment, in three ways:
- It shows the guidelines that apply to what has been dictated.
- It answers questions in the context of those guidelines.
- It lets the radiologist **explicitly apply** a guideline's classification and recommendation to the report.

Nothing reaches the report unless the radiologist presses Apply or ticks it.

## 2. Decisions (agreed with Hassan, 2026-10-12)

1. **The core output is guideline cards**, not a free chat. The chat lives inside the card model (§4.3).
2. **Two layers of knowledge.**
   - *Recognising* the guideline that applies uses the model's own knowledge. It is fast and needs no search.
   - *Detail* (criteria, thresholds, required inputs, recommendation wording) comes from a **normalised guideline
     registry**. The registry is filled lazily: the first time a guideline is opened, a live search fetches it and the
     result is cached. Later sessions take it from the registry.
3. **The registry caches the guideline, never how it applies to a case.** Working out which inputs this case settles,
   and what it would add, is a per-case call against the cached entry.
4. **A registry entry's identity includes version and locale**: for example `fleischner@2017`, `bosniak@2019`, and BTA
   U-grading rather than ACR TI-RADS for UK practice. Matching is by exact key or alias first. Jev only breaks ties
   between distinct registry candidates.
5. **An entry fetched for the first time is a `draft`.** Cards built from it carry an "unverified · sources" label.
   Hassan verifies entries on a review page. The common systems are seeded and verified before release.
6. **Opening a card is just for reading.** Opening one fetches the detail and shows a *proposed application*. Only the
   **Apply** button puts content into the report. Often the radiologist only wants to read.
7. **Missing inputs are asked inside the card**, with neutral choice buttons. They are never amber checklist rows:
   amber means "the report needs your answer", a card means "here is what this guideline would add". Apply stays
   disabled until the required inputs are answered.
8. **An applied guideline renders as an enrichment line under its finding**, in its own style. It is distinct from
   amber rows and from the rail's rose and violet.
9. **Classification goes into the findings, not the conclusion.** The conclusion draft already reads only the findings
   and keeps what changes management. So a staging line reaches the conclusion, while a Bosniak II line stays in the
   findings. This needs no new conclusion rules.
10. **Applying or removing an enrichment counts as a material change.**
    - An unedited conclusion draft is redrawn.
    - A conclusion the radiologist owns gets the existing quiet suggestion note.
    - The recommendations list is redrawn.
    - There is no stale or "review" state on enrichments. An enrichment is the radiologist's choice and stays as it is.
      It is removed only with its finding, or with ×.
11. **A Recommendations section sits under the conclusion, as a checklist.**
    - Recommendations from applied guidelines start ticked.
    - General suggestions from the findings and referral start unticked.
    - Only ticked items enter the report. The rest are dropped.
12. **The Copilot is a side panel next to the scratchpad.** The scratchpad shows only *resolved* output: enrichment
    lines and the recommendations checklist.
13. **One ask input, pinned at the bottom of the panel.**
    - A question asked while a card is open goes into that card's thread.
    - A question asked with no card open is about the whole case.
    - A general question that resolves to a guideline acts like a tool call. It runs the same resolve pipeline as the
      background matcher, and the Q&A lands in that guideline's card thread. The card is new if it wasn't listed, and
      opens if it was.
    - A question that involves no guideline gets a plain answer block in a "General" group.
14. **Thread answers are only for reading.** They never change a card's proposal. Inputs do.
15. **Threads last only for the session.** They are logged with the stack session for analysis and are never shared
    across cases. Only registry content is shared.
16. **Rollout is for all users, with no per-user gate.** It is tested in the lab and locally, then switched on by
    default when the new scratchpad layout is deployed. A kill switch (`RR_STACK_COPILOT=0`) turns off the panel and
    every background call.

17. **The fetch is source first (option A).** Search, then extract, then structure, every claim backed by a quote.
    A card never shows a number that hasn't been checked against a source, and a shown card never changes.
18. **Queries use the guideline's own terms, never the case's.** The case picks which **branch** of the guideline is
    fetched first. Query words are the guideline's name, version, publication and branch names, never dictated
    words, which also keeps patient text away from the search API. Fitting the guideline to the case happens
    afterwards, in the preview.
19. **The case's branch comes first; the rest fill in the background.** The card is ready once *its* branch is
    checked. The other branches fill afterwards, so the registry holds the whole system for every later case.
20. **Jev judges every evidence claim; code can only remove, never approve.**
    - Branch coverage: "SOURCE states the criteria or management for X".
    - Evidence: every output's claim, and the branch rule, goes to Jev in one batch — "The SOURCE states this for
      exactly the guideline, edition and category named, with the same values (a statement the SOURCE makes only
      about a different category, edition or guideline does not count): claim". There is no exact-match shortcut:
      a verbatim quote can belong to a sibling branch, edition or guideline, and only Jev's strict wording can tell.
      The exact match is still computed and logged alongside the score, as a signal for the seed lab, never as a
      pass. Bar: 0.5 (lab 2026-10-12, 24 claims x 2 runs on real fetched sources: true min 0.73, false max 0.19,
      wrong-branch max 0.08).
    - Ask-time gaps: Jev decides whether the stored entry already answers a question, before any new search.
    - Other thresholds (branch coverage) remain provisional, set where false yes answers reach zero in the lab.
21. **The registry grows where radiologists ask.** A question the entry can't answer runs one targeted query within
    that guideline. The answer is grounded in the new chunks, which are added to the entry as supplementary evidence
    (still a draft until verified).

22. **TNM staging uses the offline UICC TNM 9th edition data** (`resources/tnm_9th_clean.json`, cleaned to v2.1 on
    2026-10-12), never a web fetch. TNM entries count as `verified` because of their source.
23. **TNM follows the "X" convention.** An axis that can't be assessed is `TX`, `NX` or `MX`. UICC 9 defines TX and
    NX; MX is offered as the reporting convention even though UICC no longer lists it. Any X axis means no stage group,
    unless the table's row uses "Any" for that axis.
24. **A TNM site is chosen from a closed list, then gated by Jev; there's no embedding search.** The prefetch's pgvector
    hybrid search stays where it is. The Copilot path replaces it only once the lab (§8.5) shows the closed list plus
    Jev picks the site at least as well, with no false staging cards.
25. **Stage groups come from rebuilt, hand-checked tables.** The original parse lost rows from the stage tables. The
    clinical tables were rebuilt from the raw extraction (data v2.2, `stage_tables`) for 36 sites, with oesophagus
    split by histology. Sites whose stage needs more than T, N and M, or whose category table is incomplete, have no
    table: their cards propose T, N and M only. For a site whose table varies by histology, the card asks for it.

## 3. Layout

```
┌─ Scratchpad ─────────────────────────────┐ ┌─ Copilot ───────────────────────────────────┐
│ KIDNEYS                                  │ │ ▸ Bosniak 2019 · left renal cyst            │
│ 3.2 cm left renal cyst, one thin septum. │ │ ▾ Fleischner 2017 · 7 mm RLL nodule         │
│  ┃📘 Bosniak 2019 · Bosniak II        ×   │ │    Solid · single · [Low risk] [High risk]  │
│ LUNG BASES                               │ │    Proposed: CT at 6–12 m, then 18–24 m     │
│ 7 mm solid RLL nodule.                   │ │                                  [Apply]    │
│                                          │ │    ─ Does a perifissural shape change this? │
├──────────────────────────────────────────┤ │      If typical perifissural, …             │
│ CONCLUSION (drafted from findings)       │ │ ▸ Adrenal incidentaloma (ESE 2023)          │
├──────────────────────────────────────────┤ │ General                                     │
│ RECOMMENDATIONS                          │ │    ─ Normal CBD post-cholecystectomy? …     │
│ ☑ CT chest 6–12 m · Fleischner 2017      │ │ ┌─────────────────────────────────────────┐ │
│ ☐ Correlate with prior imaging           │ │ │ Ask…                                 🎤 │ │
└──────────────────────────────────────────┘ │ └─────────────────────────────────────────┘ │
                                             └─────────────────────────────────────────────┘
```

The final tint and spacing are settled with a mock-up before the frontend task. The enrichment style must not collide
with amber (checklist), violet (rail tint) or rose (the radiologist's additions).

## 4. Interaction model

### 4.1 Card lifecycle

| State | Trigger | Panel shows | Report effect |
|---|---|---|---|
| Matched | background matcher | name, version, the finding, one line on why it applies | none |
| Opened | click | loading → criteria that apply, what the findings settle, missing inputs (choice buttons), proposed application | none |
| Applied | **Apply** | "Applied ✓ · Undo" | enrichment line on the finding; the recommendation is ticked in the checklist |

- Cards are grouped by finding. A staging system that draws on several findings (TNM) attaches to the primary finding.
- Caps: 2 cards per finding and 6 per case. The matcher ranks them.
- A finding that is deleted takes its cards and its enrichment with it.
- A card built from a `draft` entry shows "unverified · sources", and the sources link out.
- Answering an input re-runs the preview (§5.4). Apply is enabled only when the preview has a proposal.
- Undo in the panel and × on the enrichment line do the same thing.

### 4.2 Enrichment line

- It sits under the finding and holds the guideline label and the classification line, e.g. "Bosniak 2019 · Bosniak II".
- In the report it becomes a confirmed statement in that finding's paragraph (§6). Its recommendation goes to the
  checklist, never into the line.

### 4.3 Ask and threads

| Question | Lands in |
|---|---|
| Asked with a card open | that card's thread |
| General, and resolves to a guideline already listed | that card, which opens, with the Q&A in its thread |
| General, and resolves to a new guideline | a new card marked "from your question", opened, with the Q&A as the first thread item |
| General, no guideline | an answer block in the "General" group |

- The input accepts dictation, using the same mic controls and hotkey model as the scratchpad's inline edits.
- A thread collapses with its card and shows a count.
- Answers are short, about two to four sentences. Any threshold an answer cites must come from the registry entry
  when a card is in scope.

### 4.4 Recommendations checklist

- It sits under the conclusion in the scratchpad.
- Items from applied enrichments are ticked and labelled with their guideline. Removing the enrichment removes the item.
- General suggestions are unticked: specialist or MDT referral, correlation with prior imaging, further imaging the
  findings point to. They are redrawn when the conclusion is redrawn or an enrichment changes. A tick or untick by the
  radiologist survives a redraw when the item's text is unchanged.
- The radiologist can type or dictate their own item, which starts ticked.
- Confirm never waits on it. An empty or failed list means no Recommendations section.

## 5. Backend

All routes sit under `/api/canvas/stack/guidelines/`, in a new package `hybrid_stack/copilot/`.

### 5.1 Registry

Table `guideline_registry`, with an alembic migration:

| column | notes |
|---|---|
| `key` (pk) | canonical `slug@version`, e.g. `fleischner@2017` |
| `name`, `version`, `locale` | display name, version string, `uk` by default |
| `publication` | title, issuing body, year (the Q1 search key) |
| `aliases` | JSON list of lower-cased names and abbreviations |
| `status` | `draft` \| `verified` |
| `content` | JSON (§5.1.1) |
| `sources` | JSON list `{url, title, tier, fetched_at}` |
| `chunks` | JSON list `{url, text, branch}`: the extracted evidence text, kept for ask-time grounding and review |
| `created_at`, `updated_at`, `verified_by`, `verified_at` | |

#### 5.1.1 `content` schema

```json
{
  "applies_to": "one line: which findings this system classifies",
  "summary": "two-sentence reference summary shown at the top of an opened card",
  "branches": [
    {"name": "Subsolid · single part-solid · ≥ 6 mm",
     "state": "checked | not_available | pending",
     "inputs": [{"id": "risk", "question": "Patient risk", "options": ["Low risk", "High risk"],
                 "settled_by": "how a dictation would state it"}],
     "rule": "the decision rule for this branch, citing thresholds as the source states them",
     "outputs": [{"when": "condition over inputs", "classification": "label",
                  "recommendation": "interval or action", "quote": "verbatim evidence from chunks"}]}
  ],
  "supplements": [{"question": "…", "answer": "…", "quote": "…", "url": "…"}]
}
```

- Branches come from the skeleton (§5.2). Each branch has its own state, so a partly filled entry is usable for its
  `checked` branches.
- Only a `checked` branch can drive a proposal.

**Seeds and review**
- Seed set, fetched by the same pipeline and verified before release: Fleischner 2017, Bosniak 2019, ESE adrenal
  incidentaloma 2023, BTA U-grading, O-RADS US, LI-RADS CT/MR, Kellgren–Lawrence. TNM comes from the offline
  provider (§5.8), not the fetch. Hassan may change the list during plan review.
- Review page `/stack-guidelines`. It is a production review page like `/stack-families`, not a dev route: the
  entries live in the production database, and the server allows only `RR_STACK_REVIEWERS`.
  - It lists entries and shows each branch with its quotes and sources.
  - Hassan checks correctness and coverage, then verifies, edits the JSON, or discards (the next open re-fetches).

### 5.2 Matcher (`POST /match`)

- Input: scan type, referral, and the abnormal units `{id, text}` from `/group`.
- It runs after `/group` settles (debounced) and is cached per unit text. A unit whose text is unchanged is never
  re-matched.
- One gpt-oss-120b call on Cerebras, about 1 s, with structured output. Per unit it returns ranked candidates
  `{name, version, why, publication, skeleton[], branch}`:
  - `publication`: title, issuing body and year, from model knowledge. Never a URL.
  - `skeleton`: the system's branch names only, never thresholds.
  - `branch`: the skeleton branch this finding falls into, the only case-aware output.
- The prompt:
  - carries the existing registry keys and names, so the model reuses them, plus the UK locale;
  - is case-agnostic (structural form, multi-domain examples);
  - treats "no guideline" as a valid answer, and the expected one for most findings.
- Normalisation:
  - an exact key or alias hits the registry, and the registry's own branches replace the model's skeleton;
  - otherwise, a registry entry of the same system with a different version goes to Jev, which chooses between
    distinct entries or "none";
  - otherwise the candidate becomes a new key, stored only when opened.
- Caps are applied after ranking (§4.1).

### 5.3 `resolve_guideline(card)`: the targeted fetch

Shared by card open and by ask. The steps:

1. **Registry hit with the card's branch `checked`:** return the entry, with no search.
2. **First pass**, for a missing entry or an unchecked branch. Runs in parallel:
   - Q1 `"<publication title>" <year>`
   - Q2 `<name> <version> <branch name> criteria recommendations`
   Then:
   - Tavily search, basic depth, 5 results each, no domain filter.
   - Code ranks the results by source tier: 1 = publisher or issuing society, 2 = PubMed Central full text,
     3 = other reputable secondary summaries.
   - Results scoring below 0.3 are dropped first, unless none pass; known access-block pages fall back to their
     search snippet; URLs are canonicalised before de-duplication.
   - Tavily extract runs on the top 2 URLs with a focus query: "<branch>: categories, criteria, thresholds, required
     features, management recommendations".
3. **Coverage (Jev).** One call with one yes/no question per branch in scope: "SOURCE states the criteria or
   management for: <branch>". If the case's branch is below the bar, one more query runs
   (`<name> <version> <branch> recommendations`) over pages not already read, then extract and Jev again. Still below the bar → `not_available`.
4. **Structure (gpt-oss).** The branch is filled (inputs, rule, outputs) from the chunks, with a quote per output.
5. **Evidence.** Every output's claim, and the branch rule (riding in the same batch, with no quote of its own),
   is judged by Jev — the strict wording from §2.20, bar 0.5. The exact-match check (whitespace, case, punctuation
   and dash variants normalised, token boundaries, quote at least 4 tokens, every number in the claim present in
   the quote) is still computed and logged alongside the Jev score, but it never approves a claim by itself: a
   verbatim quote can belong to the wrong branch, edition or guideline. Unsupported outputs are dropped; a
   low-scored rule is blanked without dropping the outputs. A branch with no supported outputs becomes
   `not_available`.
6. **Save:** an upsert as `draft`, merging branches. A `verified` entry is never overwritten. The card's preview runs
   now.
7. **Background fill:** steps 2–5 for each remaining skeleton branch, using Q3+ (one query per branch), saved as each
   finishes. It is fire-and-forget: a failure leaves the branch `pending`, and the next open retries it.

**Rules**
- **Query text** comes only from the identity, the publication and branch names. No dictated words are ever sent. The
  ask path's search phrase is model-written from the question; code replaces it with the bare identity if it
  carries digits, sides or demographics.
- **Jev source length:** long source text is split into windows on chunk boundaries and asked in parallel; the
  highest score per question counts, since each one asks whether something exists.
- **Locks:** one per key for the first pass, and one per branch for background fills, so concurrent opens share work.
- **Failure:** the card shows "couldn't load guideline · retry", and nothing is stored for that branch.

### 5.4 Preview (`POST /open` and `POST /preview`)

- `open`: `resolve_guideline`, then the preview.
- `preview`: the preview alone, when an input is answered.
- One Qwen call on Cerebras with low reasoning and JSON output.
  - Input: the card's branch (and any other `checked` branches), the current findings, the referral and the
    answered inputs.
  - Output:

```json
{"settled": [{"input": "risk", "value": "High risk", "quote": "smoker"}],
 "missing": ["risk"],
 "proposal": {"classification": "Fleischner 2017 · high risk", "line": "…", "recommendation": "…"} | null}
```

- The proposal is null while any required input is missing, or when the branch is not `checked`.
- **Code check:** every number in `classification`, `line` and `recommendation` must appear in the branch's rule or
  outputs, the entry's name or version, or the findings. Otherwise the proposal is dropped, and the card shows the
  inputs only.

### 5.5 Ask (`POST /ask`)

- Input: the question, the open card's key (or none), case context, and the last few Q&As in scope.
- It works like a tool call, written as structured steps rather than native tool use (simpler to test, and the same
  on every provider).
- **Card in scope:**
  1. Jev: "SOURCE answers: <question>", over the entry's branches, chunks and supplements.
  2. At or above the bar: one Qwen call answers, grounded in that material.
  3. Below the bar:
     - one targeted query runs: `<name> <version> <question keywords from the guideline's vocabulary>`;
     - Qwen writes the search phrase from the question with no case details;
     - extract, then Jev checks again.
     - If supported: answer, and append a supplement to the entry.
     - If not: answer "the guideline doesn't address this", plus brief general knowledge clearly labelled as not from
       the guideline.
- **No card in scope:** a first Qwen call returns `{guideline: name | null, answer}`.
  - `null`: the answer becomes a General block.
  - A name: the matcher's normalisation runs, so a listed card is reused, then `resolve_guideline`, then the
    card-in-scope path. The response carries the card, and the frontend files the Q&A under it.
- Answers are about two to four sentences, in British English.

### 5.6 Recommendations (`POST /recommendations`)

- Input: findings, referral, applied enrichments and the conclusion.
- One Qwen call at low reasoning. It returns up to four general suggestions, each a short sentence, and never a
  duplicate of an applied recommendation.
- It is called with the conclusion draft and when an enrichment changes.

### 5.7 Logging

`DictationStackLog` gains a `copilot` JSON field holding:
- cards matched, opened and applied (key, status)
- thread Q&As
- recommendations offered and ticked
- latencies

### 5.8 TNM provider (`copilot/tnm.py`)

- **Data.**
  - `resources/tnm_9th_clean.json` v2.1: 60 sites, each with structured T, N and M category dictionaries, the
    `rules` text and a `stage_grouping` table. It is loaded once into memory, with no database and no network.
  - Excluded, because they are not TNM-staged in practice or have no T/N/M table: Brain & Spinal Cord, Hodgkin
    Lymphoma, Non-Hodgkin Lymphomas.
- **Matcher.**
  - The prompt carries the site names as a closed list. For a primary malignancy, known or suspected, the matcher
    returns `name: "TNM"` and `site: <exact list name>`. Code rejects a site that isn't on the list.
  - **Jev gate**, one yes/no per TNM candidate: "The FINDING describes a primary malignant tumour (known or suspected)
    of <site> that would be staged." A card is made only at or above `TNM_GATE_MIN`, which the lab sets.
  - The key is `tnm-<slug(site)>@9`.
- **Entry.** Built on the fly, with no fetch and no registry row:
  - one branch, "Staging", state `checked`;
  - inputs `T`, `N` and `M`, whose options are the site's categories, with the X option added first when absent,
    plus `histology` when the site's stage table varies by it;
  - rule: the category definitions (the `format_tnm_evidence` text);
  - outputs: the stage grouping rows;
  - status `verified`; source "UICC TNM Classification of Malignant Tumours, 9th edition (offline)".
- **Preview.**
  - Qwen settles each axis it can from the findings, each with a quote. Unsettled axes are in-card choices.
  - The proposal is assembled **in code**: classification `cT2b N1 M0 (UICC TNM 9th)`, and line "Staging (UICC TNM
    9th): cT2b N1 M0."
  - The stage group comes from the site's verified `stage_tables`, and only when the lookup gives exactly one stage:
    - "Any" matches anything;
    - X matches only "Any" or a cell that lists it;
    - a category matches its parent row (T2b matches "T2");
    - a substage beats its summary stage (IIA over II);
    - when several rows still tie and disagree, no stage is given.
  - There is no recommendation.
- **Ask.** Material is the `format_tnm_evidence` text for the site. There is no gap search for TNM.

## 6. Into the report

- **Gate record** (`GateRecord` in `hybrid-stack/types.ts`) gains:
  - `enrichments: {key, version, status, unit_id, region, line, recommendation}[]`
  - `recommendations: {text, source: 'guideline' | 'suggested' | 'typed', key?, ticked}[]`
- **Findings block:** each enrichment line is added as a confirmed statement under its finding's region. The generator
  places it in that finding's paragraph, under the existing Scratchpad Session rule. The conclusion draft (`/draft`)
  reads the same block, so it may name the classification (§2.9).
- **Recommendations** travel in the findings block, as its last part: `Recommendations (selected by the radiologist):
  <items>`. Both paths already send that block (quick as `findings`, template as `FINDINGS`), so no new request field
  is needed.
  - `stack_fallback` (quick path) adds one rule: when the findings carry that line, write a RECOMMENDATIONS section
    after the impression, with exactly those items in report style and nothing else. With no line, there is no section.
  - The Impression Plan's "no recommendation" rule stays. Recommendations live only in that section.
  - The template path relies on the labelled line. Its placement gets checked in the local hand read.

## 7. Failure behaviour

Everything fails open, and dictation, Confirm and Generate never wait on the Copilot.

| Failure | Result |
|---|---|
| Matcher fails | no cards |
| Fetch fails | retry state on the card |
| Preview fails | criteria only, no Apply |
| Ask fails | an inline error with retry |
| Recommendations fail | no suggestions (applied ones still show) |

`RR_STACK_COPILOT=0` hides the panel and skips every background call.

## 8. Testing

**Labs.** Hand reads by Claude, two runs at most, outputs reused, pid in output filenames:
1. **Matcher.** Prod stack dictations with guideline-bearing findings, plus negative controls. Measured:
   - recall of the correct key;
   - wrong or irrelevant cards (precision matters most);
   - key normalisation.
2. **Fetch and extraction.** The targeted fetch runs on the seed set and is checked by hand against the sources, for
   correctness and branch coverage. This doubles as seed verification and supplies the Jev fixtures:
   - covered and missing branches (coverage bar);
   - true, reformatted and wrong quotes (evidence bar);
   - questions the entry answers and questions it doesn't (ask-gap bar).

   Each bar is set where false yes answers reach zero. First-open latency (card branch) and background-fill
   completeness are recorded.
5. **TNM site selection.** Primary tumours across common sites, plus metastases, benign masses and incidental lesions
   as negative controls. Two arms are compared on site accuracy and false staging cards:
   - (a) the closed list plus the Jev gate;
   - (b) `hybrid_tnm_search` on the finding text.
   Arm (a) replaces (b) on the Copilot path only if it is at least as accurate, with zero false cards at the chosen
   bar.
3. **Preview.** Seed entries × case findings. Measured: settled and missing inputs are correct, the proposal is
   correct, and numbers come from the entry (the numeric check catches violations).
4. **Ask routing.** Questions split into card-scoped, existing-guideline, new-guideline and general. Each must land in
   the right place.

**Code tests:**
- key and alias normalisation, the per-key lock, the numeric check
- the gate record fields
- `stack_fallback` writing the Recommendations section only from ticked items
- Apply and remove each trigger the conclusion redraw
- fail-open paths
- frontend component tests for the card states, the Apply gate, thread routing, the enrichment line and the checklist

## 9. Out of scope

- Applying guidelines after Generate. The post-generation rail and chat are unchanged.
- Sharing threads across sessions.
- Automatic re-verification of registry entries.
- Version upgrades are manual: a new version is a new key.
