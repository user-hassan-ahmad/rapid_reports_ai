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
| `aliases` | text[], lower-cased names and abbreviations |
| `status` | `draft` \| `verified` |
| `content` | JSON (§5.1.1) |
| `sources` | JSON list `{url, title, fetched_at}` |
| `created_at`, `updated_at`, `verified_by`, `verified_at` | |

#### 5.1.1 `content` schema

```json
{
  "applies_to": "one line: which findings this system classifies",
  "inputs": [{"id": "risk", "question": "Patient risk", "options": ["Low risk", "High risk"],
              "settled_by": "how a dictation would state it"}],
  "rule": "the decision rule as compact plain text, citing thresholds exactly as the source states them",
  "outputs": [{"when": "condition over inputs", "classification": "Bosniak IIF",
               "recommendation": "Follow-up CT or MRI at 6 months, then 12 months, then annually for 5 years"}],
  "summary": "two-sentence reference summary shown at the top of an opened card"
}
```

- Seed set, verified before release: Fleischner 2017, Bosniak 2019, ESE adrenal incidentaloma 2023, BTA U-grading,
  O-RADS US, LI-RADS CT/MR, TNM 8 for lung, colorectal, pancreas and kidney, Kellgren–Lawrence.
- Hassan may change the seed list during plan review.
- Review page `/stack-guidelines`, guarded with `requireDevRoute`. It lists entries, shows content and sources,
  verifies an entry, and edits its JSON.

### 5.2 Matcher (`POST /match`)

- Input: scan type, referral, and the abnormal units `{id, text}` from `/group`.
- It runs after `/group` settles (debounced) and is cached per unit text. A unit whose text is unchanged is never
  re-matched.
- One gpt-oss-120b call on Cerebras, about 1 s, with structured output.
  - Per unit, it returns ranked candidates `{key, name, version, why}`.
  - The prompt carries the list of existing registry keys and names, so the model reuses them, plus the UK locale.
  - The prompt is case-agnostic (structural form, multi-domain examples).
  - "No guideline" is a valid answer and is expected for most findings.
- Normalisation:
  - an exact key or alias hits the registry;
  - otherwise, a registry entry of the same system with a different version goes to Jev, which chooses between distinct
    entries or "none";
  - otherwise the candidate becomes a new key, stored only when opened.
- Caps are applied after ranking (§4.1).

### 5.3 `resolve_guideline(key | name)`

- Shared by the matcher's cards (on open) and by ask.
- **Registry hit:** return the entry.
- **Miss:**
  1. A targeted fetch reuses the prefetch's Tavily search, triage and page extraction stages from
     `guideline_prefetch.py`, with a single-guideline query.
  2. gpt-oss extracts the pages into the `content` schema. Nested structured output goes to gpt-oss, per the routing rules.
  3. The entry is stored as `draft` with its sources.
- One lock per key, so concurrent opens share a single fetch.
- Failure: the card shows "couldn't load guideline · retry", and nothing is stored.

### 5.4 Preview (`POST /open` and `POST /preview`)

- `open`: `resolve_guideline`, then the preview.
- `preview`: the preview alone, when an input is answered.
- One Qwen call on Cerebras with low reasoning and JSON output. Input: the entry content, the current findings, the
  referral and the answered inputs. Output:

```json
{"settled": [{"input": "risk", "value": "High risk", "quote": "smoker"}],
 "missing": ["risk"],
 "proposal": {"classification": "Fleischner 2017 · high risk", "line": "…", "recommendation": "…"} | null}
```

- The proposal is null while any required input is missing.
- **Code check:** every number in `line` and `recommendation` must appear in the entry's `rule` or `outputs`. Otherwise
  the proposal is dropped and the card shows the inputs only. This uses the same idea as the post-generation numeric
  guards.

### 5.5 Ask (`POST /ask`)

- Input: the question, the open card's key (or none), case context, and the last few Q&As in scope.
- One Qwen call with a single tool, `resolve_guideline(name)`.
  - **Card in scope:** the answer is grounded in that entry, with no tool.
  - **No card in scope:** the model either calls the tool (the response carries the card, and the frontend files the
    Q&A under it) or answers plainly (a General block).
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

## 6. Into the report

- **Gate record** (`GateRecord` in `hybrid-stack/types.ts`) gains:
  - `enrichments: {key, version, status, unit_id, region, line, recommendation}[]`
  - `recommendations: {text, source: 'guideline' | 'suggested' | 'typed', key?, ticked}[]`
- **Findings block:** each enrichment line is added as a confirmed statement under its finding's region. The generator
  places it in that finding's paragraph, under the existing Scratchpad Session rule. The conclusion draft (`/draft`)
  reads the same block, so it may name the classification (§2.9).
- **Recommendations:** a new request field `stack_recommendations: list[str]`, made of the ticked items.
  - `stack_fallback` adds one section instructing the generator to write a RECOMMENDATIONS section after the
    impression, containing exactly these items in report style and nothing else. With no items, there is no section.
  - The Impression Plan's "no recommendation" rule stays. Recommendations live only in this section.
- Template path: the same fields, mirrored where the template stack path builds its brief.

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
2. **Extraction.** Live fetch for the seed set, checked by hand against the sources. This doubles as seed verification.
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
