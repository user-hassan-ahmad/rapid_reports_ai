# Scratchpad Copilot: step-back review (2026-10-12)

Reviewer: fresh senior pass, decision-oriented. Branch `feat/scratchpad-copilot`, worktree
`.claude/worktrees/scratchpad-copilot`. Nothing was modified.

## Verdict in one paragraph

The **front half** of the design is right and should be kept: guideline cards in a side panel, Apply as the only way
into the report, the enrichment line under the finding, a ticked Recommendations checklist, and above all the preview
rule "the model settles inputs with verbatim quotes, Jev checks the quotes, code copies the classification". The
**back half** has drifted. To fill the cards it builds a self-assembling web knowledge base: a lazy live fetch into a
shared registry, model-invented branch skeletons, structure-then-verify, background fill, ask-time supplements,
draft/verified states and a review page. The seed lab shows that this half fails at the one property that matters for
Apply, which is a **complete and correctly attributed decision table**. Its error class (secondary pages taken as the
guideline, partial tables marked `checked`) belongs to the approach, not to tuning. My recommendation: **replace the
runtime web pipeline with a small curated offline library** ("guideline packs", the same pattern as
`resources/tnm_9th_clean.json`) for the systems radiologists actually apply. Use model knowledge plus a source link,
read-only and never Apply-able, for the long tail. That also removes the verified/draft tagging by construction, with
no extra machinery.

---

## 1. Mission fit

**What the radiologist needs at read time.** For a given finding:
1. the right system named (Fleischner 2017, Bosniak 2019, …), fast;
2. its decision table, complete, readable in seconds;
3. which inputs the dictation already settles, and what is still missing;
4. on Apply, a correct category and recommendation;
5. occasionally, a short contextual answer ("does perifissural change this?").

Items 2 and 4 must be **complete and correct**, because they reach the report. Item 5 is mostly reading.

**What was built.** A system whose main engineering effort goes into *acquiring* guideline knowledge at runtime:
- `search.py`: identity-only queries, tiering, a Jev relevance gate, refill.
- `fetch.py`: coverage gate, retry query, gpt-oss structure, Jev evidence gate, branch merge, background fill, locks.
- `registry.py`: a shared mutable store with draft and verified states.
- `ask.py`: gap search and supplements, so the registry "grows where radiologists ask".
- the review page (Task 20).

This is a general web-knowledge engine scoped to guidelines. It answers a question the mission never asked: how to
support *any* guideline on first sight. And it is weakest exactly where the mission is strictest, on correctness of
what reaches the report.

**Mismatch with the UX.** The card is "mostly reading", but first open costs 5 to 11 s (seed log: Fleischner 9.6 s,
LI-RADS 11.3 s, Bosniak 5.0 s), and a common branch can come back `not_available`. Reading needs an instant, complete
table, not a fetched partial one.

## 2. Where we are boxed in

### Early assumptions and the patches they forced

| Early assumption | What later reviews patched around it |
|---|---|
| **Lazy web fetch into a shared registry** (§2.2) | draft/verified states (§2.5); review page; per-key and per-branch locks; `NOT_AVAILABLE_RETRY_DAYS`; outage-vs-low-score rules; "a verified entry is never overwritten"; branch merging; the `safe_identity` privacy choke point; the case-free supplement rule (§2.15); the reviewer-only supplements view |
| **Skeleton (branch names) from model knowledge at match time** (§5.2) | normalising branch names to the registry; Jev branch pick; edition pick; the versionless-key rule; the KNOWN SYSTEMS prompt rows; the Overview branch for ask-originated cards. Branch granularity is whatever the model said on first sight, frozen into the shared registry (e.g. Kellgren–Lawrence as one branch, "Grades 0 to 4") |
| **Structure-then-verify, per output** | the Jev evidence gate, the exact-match signal, the claim-number checks, rule blanking. All of them check **precision of each row**. Nothing checks **completeness of the table**, so `checked` means "at least one supported output" |
| **Open web as the source** | tiering; relevance gate; abstract demotion; access-block snippet fallback; refill below 1,500 characters; a page capped to one Jev window (`PAGE_MAX ≈ 11.8k chars`, `search.py`), which truncates long guideline papers; curated URLs needed in the lab itself (`seedlab.py` `CURATED` for O-RADS and LI-RADS) |

### Moving parts (counted from the code)

- **Size:** `hybrid_stack/copilot/` is about 2,640 lines over 11 modules, about 6,000 inserted lines on the branch.
  31 commits, 14 of them review fixes.
- **Thresholds:** about 10 tunable ones in `jev.py`, `matcher.py`, `preview.py` and `search.py`:
  `COVER_MIN`, `EVIDENCE_MIN`, `ANSWERS_MIN`, `RELEVANT_MIN`, `MIN_SCORE`, `MIN_EXTRACT_CHARS`, `TNM_GATE_MIN`,
  `PICK_MIN`, `SETTLED_MIN`, plus the window caps. Most are marked "provisional".
- **Jev question types:** 8 (relevance, coverage, evidence, answers, scoped answers, edition pick, branch pick, TNM
  gate, settled quote).
- **Model roles:** gpt-oss for match and structure; Qwen for preview, ask route, ask answer, ask phrase and recs.
- **External calls:** Tavily search, extract, refill extract and retry query.
- **Timeouts:** 7 separate ones, from 4 s to 60 s.

**One first open on a cold key can run:** 2 searches → 1 relevance Jev → 4 extracts → refill → windowed coverage Jev
→ maybe a retry search, extract and Jev → gpt-oss structure → windowed evidence Jev → DB upsert → preview Qwen → quote
Jev, and then the same chain again for every other branch in the background.

### Load-bearing versus accidental

**Load-bearing (keep):**
- the matcher;
- preview quote settling plus the code-built proposal;
- the numeric guard;
- the offline TNM provider and the closed-site list;
- the Apply-only rule;
- the `stack_fallback` Recommendations rule;
- the recommendation suggestions;
- the kill switch.

**Accidental (exists only because knowledge is fetched at runtime):**
- search, fetch, registry writes, locks, background fill, supplements, the draft/verified split, the review page;
- the relevance, coverage and evidence gates;
- edition and branch normalisation;
- most of the privacy plumbing in `search.safe_identity`.

## 3. Retrieval quality: is fetch → structure → Jev-verify sound?

**The evidence lab is sound but answers a narrower question.** In `evlab/run1_*.json` and `run2_*.json`, Jev separates
a true claim from a false one *on a given source* very well (true ≥ 0.73, false ≤ 0.19, wrong branch ≤ 0.08). Jev does
what it is good at, which is checking stated text.

**The seed lab shows the pipeline is not a foundation for Apply-able content.** My read of
`searchlab/seed_*_88178.json` agrees with the controller's ~26/30 per-row correctness. But looking at **tables rather
than rows**, the picture is worse:

| System | What the seed lab stored |
|---|---|
| Fleischner, single solid nodule | `checked` with only the two 6–8 mm rows; the < 6 mm and > 8 mm rows, the commonest cases, are absent; no rule; the low-risk row is wrong (flattened PDF table) |
| Kellgren–Lawrence | `checked` with **grade 0 only**; inputs are opaque ids (I1–I4) with mixed options |
| Bosniak | III and IV (the actionable classes) `not_available`; IIF's "when" is "no progression over five years", which is a management statement, not a criterion; labels "I" and "II" without the system name; CUA guidance attributed to Bosniak |
| BTA U | U4 and U5 missing; the U1/U2 recommendation empty; the input *is* the U grade (`1:U3`), so the card would ask the radiologist for the answer it should help with |
| LI-RADS | LR-5 missing; LR-4 condition garbled; LR-M inputs are `f1`–`f4` |
| O-RADS US | O-RADS 2 and 5 missing; O-RADS 3 output is "any of the criteria listed in the rule"; O-RADS 4 holds a research study's CA125 rule |
| ESE adrenal | the classification labels "Category 1 (Benign)" and "Category 2 (Likely Benign)" come from an ESR poster, not ESE 2023 |
| Sources overall | Fleischner had **no tier-1 source** among 14; ACR systems needed hand-curated PMC URLs to work at all |

Three error modes are inherent, not tuning problems:
1. **Attribution.** On the open web, pages that *discuss* a guideline far outnumber the guideline itself, especially
   when the primary is paywalled (Radiology/RSNA) or an ACR PDF. Jev is asked "does the SOURCE state this", and
   answers correctly. Asking Jev "is this page *the* guideline" is an inference about provenance, which is Jev's weak
   side (reference_jev_capability_profile). A source allow-list helps, but then you are curating sources anyway.
2. **Completeness.** Row-wise verification cannot detect a missing row. Detecting it needs a known shape of the table,
   which is curation again.
3. **Tables.** Decision grids live in PDF tables and figures. Extraction flattens them, and a flattened grid gives
   plausible, verifiable, wrong rows (the Fleischner low-risk case: the quote *is* on the page).

The preview's safety net (no proposal without a valid output number) makes these failures mostly fail closed. That
keeps a wrong row out of the report only if nobody picks it. The **wrong-attribution rows (~13%) would be offered and
Apply-able**, and the missing rows make common cases unusable.

## 4. Alternatives

| Option | Correctness | Latency | Cost | Maintenance | Verdict |
|---|---|---|---|---|---|
| **A. Current:** lazy web fetch, shared registry | per row ~87%; tables incomplete; wrong attribution | 5–11 s first open | Tavily plus many Jev and LLM calls per key | high: thresholds, locks, review queue that never empties | stop |
| **B. Curated offline packs** for the top N systems, hand-checked JSON in the repo; long tail read-only | as good as the hand read; complete grids checkable in code | about 0 s to show; preview ~1–2 s | near zero at runtime | about 1–2 h per system once; a version bump every few years (Fleischner 2017, Bosniak 2019, LI-RADS 2018, O-RADS 2022, ESE 2023, BTA 2014) | **recommend** |
| **C. One authoritative source per guideline** (a pinned URL or PDF), runtime fetch and structure | better attribution; still flattened tables and missing rows | still seconds | moderate | pinned URLs rot; still needs review | use only as the **authoring input** for B |
| **D. Model writes the entry from its own knowledge; retrieval attaches or checks citations** | complete, but thresholds can be wrong; Jev can confirm a citation, not completeness | fast if precomputed | low | same review need as B | good **authoring assistant** for B, not a runtime path |
| **E. Per-system hand decision templates in code** (code computes the category from the inputs) | the best for grids (Fleischner, Bosniak, O-RADS, LI-RADS) | instant | lowest | code changes per system | fold into B as an `evaluate` table: the pack's outputs keyed by input combinations |
| **F. Reuse `guideline_prefetch.py`** | same open-web problems; GLM multi-stage; post-generation timing | 10 s or more | high | already large (1,784 lines) | do not reuse beyond its domain allow-list idea, if a long-tail link search is wanted |

### Recommendation: B, with D and C as authoring tools and E inside the pack

**Pack format.** One JSON per system, for example `resources/guidelines/fleischner_2017.json`:
- identity: key, name, version, publication, a source URL or DOI;
- `applies_to` and a summary;
- inputs with human labels and options;
- a **complete** output grid (input combination → classification and recommendation, verbatim from the primary);
- short rule notes and caveats, which ground the ask;
- `authored_by` and `checked_on`.

**Authoring.** Feed the primary PDF that Hassan supplies, or one pinned URL, to the existing structure prompt. Then
three checks:
- Jev evidence check per row (the existing gate, reused as a **linter**);
- a code completeness check (every option combination maps to exactly one row);
- Hassan's hand read.

Commit only after all three pass. "Verified" then means "it is in the repo", so the runtime has no draft state.

**Runtime.** The matcher picks from the closed pack list, plus TNM sites, as it already does for TNM:
- **A pack card** opens instantly and shows the full table. The preview settles inputs with quotes, as today. Code
  evaluates the grid, so classification and recommendation are copied, never written.
- **A long-tail card** (a system recognised but not packed) is **read-only**: a model-knowledge summary, labelled as
  general knowledge, plus a link to the primary source. It has no Apply and no table. The link comes from the model's
  publication field, or from at most one identity-only search for a link. That honours "the radiologist can open
  source links" without fetching content into the report path.
- **Ask:** with a pack card in scope, it is grounded on the pack. Otherwise it is a general-knowledge answer,
  labelled, with a link. The gap search and the supplements are dropped. The ask logs (already planned in §5.7) show
  which systems to pack next. "The registry grows where radiologists ask" becomes a human loop rather than an
  automatic write into shared content.

**Why this fits the binding principles:**
- Jev keeps validating stated text (quotes from the dictation; rows against the primary at authoring time).
- Qwen judges which inputs the dictation settles; code applies the grid.
- One reasoning call owns each judgement.
- No case text, and at runtime almost no text at all, reaches a search API.
- The mission's "correctness of anything that reaches a report is paramount" is met by construction.

**Main risk: coverage.** How much of real practice do N packs cover? This is measurable: run the matcher, unchanged,
over production stack dictations (standing read permission) and count the systems it names.

My prior: about 15–20 systems cover nearly all Apply-worthy findings in UK general CT/US/MR/XR reporting:
- Fleischner, BTS nodule;
- Bosniak;
- adrenal (ESE);
- BTA U and TI-RADS;
- O-RADS US/MR;
- LI-RADS;
- PI-RADS;
- BI-RADS;
- Kellgren–Lawrence;
- incidental pancreatic cyst;
- AAA surveillance (UK NAAASP);
- gallbladder polyp;
- simple adnexal cyst (SRU);
- incidental thyroid on CT (ACR);
- incidental liver lesion;
- TNM (already offline).

## 5. Simplification list

**Delete or park (keep on a branch, do not merge):**
- `copilot/search.py` and almost all of `copilot/fetch.py`: search, refill, coverage and retry, background fill,
  `_spawn_fill`, locks, `FILL_CONCURRENCY`, `NOT_AVAILABLE_RETRY_DAYS`.
- The `guideline_registry` table and migration, and `registry.py` writes. If an index is wanted, the packs load into
  memory like `tnm.py`.
- Draft/verified states, the "unverified · sources" label, `verified_by`/`verified_at`, the reviewer registry routes,
  and the `/stack-guidelines` review page (Task 20). Review happens in the PR that adds the pack.
- Supplements and the ask gap search (`ask.py` gap phrase, vocabulary filter, scoped re-check). Most of
  `safe_identity`'s purpose disappears with them; keep it only if a long-tail link search stays.
- Edition pick, versionless-key resolution and most of the branch-normalisation code in `matcher.py`. The closed list
  makes them redundant. Branch pick becomes an input on the pack, not a fetch unit.
- The Jev relevance, coverage and runtime-evidence gates, with their provisional thresholds.

**Keep and reuse:**
- `types.py` (slimmed);
- `matcher.py`'s model call and caps, with a closed list;
- `tnm.py` with its rebuilt stage tables, already the model for packs;
- `preview.py`'s quote-settle, the Jev quote check, the code-built proposal and the numeric guard;
- `recs.py`;
- `routes.py` (fewer routes: match, open, preview, ask, recommendations);
- the `stack_fallback` rule (Task 11);
- the evidence-gate prompt in `jev.py`, as the authoring linter;
- the structure prompt in `fetch.py`, as the authoring assistant.

**Minimal version that delivers the mission:**
- the matcher over the closed pack list plus TNM;
- pack cards that open instantly with the full table;
- the preview with quote-verified inputs and code-evaluated output;
- Apply → enrichment line and a ticked recommendation;
- read-only long-tail cards with a link;
- ask grounded on the pack or labelled general;
- recommendation suggestions.

At a rough estimate that is about half of the current backend, with no database table and no external calls on the
card path.

## 6. Next-iteration plan (smallest steps, each with a lab gate)

0. **Freeze.** Don't merge the fetch, search and registry commits into the shippable line. Branch the keep-set off the
   current head.
1. **Coverage lab** (matcher unchanged; prod stack dictations; hand read).
   - Output: the systems named, their frequency, and the negative controls.
   - **Gate:** pick N so the packs cover at least about 90% of the guideline-bearing findings the matcher names
     correctly. Record matcher precision on the negative controls (zero Apply-able wrong cards).
2. **Pack format and 3 packs**: Fleischner 2017, Bosniak 2019, ESE adrenal 2023 (one grid, one class ladder, one HU
   pathway).
   - Authoring: structure prompt over the supplied primary → Jev row linter → code completeness check → Hassan hand
     read.
   - **Gate:** every row correct against the primary, grid complete, and labels human-readable (no `I1`/`f1`).
3. **Preview lab on packs**: packs × real findings. Reuse `preview.py`, with code evaluation of the grid.
   - **Gate:** zero wrong proposals; settled and missing inputs correct on hand read; latency logged (target under
     2 s).
4. **Closed-list matcher and read-only long-tail cards.**
   - **Gate:** the matcher lab shows no pack card on a negative control, and long-tail cards carry the correct
     name/version and a working primary link.
5. **Ask, simplified** (pack-grounded or labelled general).
   - **Gate:** the routing lab (§8.4), and no threshold in an answer that isn't in the pack when a card is in scope.
6. **Frontend**, Tasks 14–19 largely as planned, minus the "unverified" label and with Apply shown only on pack and
   TNM cards. Drop Task 20.
   - **Gate:** the local end-to-end hand read and an independent review (Task 21).
7. **Author the remaining packs in batches of 3–5**, ordered by step 1's frequency table and by ask logs after
   launch.
   - **Gate per batch:** the same three authoring checks.

**Decision for Hassan:** accept B (packs and read-only long tail) and park the runtime fetch, or keep A and accept
seconds-long opens, incomplete tables marked `checked`, and an ongoing review queue for a shared registry. The lab
evidence favours B.
