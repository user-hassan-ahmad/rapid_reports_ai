# Jev field research — what others do, what it means for us (2026-09-26)

**Purpose.** A single reference of facts, field patterns and ranked ideas for using Jev (TypeSafe System One) across Rapid Reports. The dictation lab is the first consumer, not the only one. Read this with the handover (`../handover/2026-09-24-jev-dictation-lab-handover.md`) and decision-first rev 2 (`../specs/2026-09-24-decision-first-dictation-design.md`).

**IDs are stable.** Cite them in specs and plans as `F-03`, `P-07`, `D-02` and so on. Add entries at the end of each section. Don't renumber.

## 0. Sources and how much to trust them

| Grade | Source | Notes |
|---|---|---|
| **A** (primary, specific) | TypeSafe docs: primitives, confidence, patterns (fan-out, confidence routing, composite scoring, intent routing), `llms.txt` | Vendor-authored, but concrete and measured |
| **A** | `moritzkremb/jev-voice-browser` README (MIT, Sep 2026) | The closest analogue to our dictation problem: speech in, typed decisions, act before the sentence ends. Has measured numbers and tests |
| **A** | Our own lab: bake-offs, bundle parity, 5 mic sessions (handover §3–4) | In-sample and small, but it is *our* data |
| **B** | Latent Space interview with Diogo Almeida (founder); LangChain "Building a harness with Jev"; flaviocopes deep dive; OpenRouter "gate tool calls" cookbook | Informed practitioners and the vendor's own framing |
| **C** | NotebookLM notebook "Jev", 8 YouTube transcripts (Riley Brown, Sam Witteveen ×2, Nate Herk, Julian Goldie ×2, Dave Ebbelaar, Greg Isenberg/Ryan Vogel) | Demos and hype. Several are sponsored or funnel to a paid course. Useful for *what people build*; weak for numbers. Contains errors (see F-12) |

Evidence rule: a **C** claim becomes a working assumption only when an **A** source or our own measurement agrees.

---

## 1. Facts database (F)

| ID | Fact | Grade | Status for us |
|---|---|---|---|
| F-01 | Three primitives: Choice (option + per-option probabilities + confidence), Score (ordered levels ≤10 + distribution + confidence), Noul (P(yes) 0–1, no confidence field). | A | Known; our wire contract, handover §7 |
| F-02 | `confidence` is a statistic *derived from the shape* of `probabilities` (concentrated → high). The full distribution is returned so you can compute your own statistic (margin, entropy). | A | **Not used.** We threshold on `confidence` only. Top-2 margin is the natural input for rev 2 pattern E |
| F-03 | Many questions per call run in parallel. TypeSafe cookbook: 13 questions in one call vs one at a time → **12.2× cheaper, 10× faster, identical answers**. | A | Corroborated by our bundle parity (p95 361 ms, parity PASS) |
| F-04 | **Speculative fan-out** is an official pattern: ask questions that may turn out irrelevant; code decides which answers to use. | A | This is exactly rev 2 §6.1 "ask the gate and the gated question in the same call". Vendor-endorsed |
| F-05 | Confidence routing is three bands: high → act, medium → confirm/flag/gather more, low → human or slower system. The docs use 0.5 (review floor) and 0.9 (before destructive) only as *examples*. | A | Same as rev 2 §3.2 bands. Thresholds come from our cost matrix, not the docs |
| F-06 | Question-writing rules (docs + field): **one judgement per question**; write the exact condition (read literally, including negations and scope words); **phrase so high = yes**; a statement works as well as a question ("The customer is requesting a refund"), so try both; **instructions and criteria must agree** or accuracy drops; give an **exit option** (`other` / "none of these" / "not stated"). | A | Partly followed. `noise` is our only exit on `action`. Statement-form nouls untested |
| F-07 | **Examples inside criteria move confidence a lot when they resemble real inputs.** Docs, Safari export bug: plain levels → 1.43 @ 0.35 confidence; the same levels as `{what, examples:[…]}` with one *relevant* example → 1.03 @ 0.96. An *unrelated* example changed nothing. | A | **Untried, high-yield.** Direct lever for `standalone` under-firing and collective recall gaps (D-05) |
| F-08 | **Numbers, dates and counting stay in code.** | A | Fits "ask about the page, not the clock". Also covers measurement and date comparison (our one shared triage miss was a temporal comparison) |
| F-09 | Longer, richer state tends to give more confident answers; two-word inputs lose confidence (Sam Witteveen demo). | C, consistent with our data | Our bundle scored `standalone` *better* with open line + latest utterance in state (handover §3). Never send a bare chunk |
| F-10 | Repeated identical calls vary a little (stochastic). Between-version drift is claimed smaller than repeat-call noise for string models. | B/C | Our parity run's "noise" column measures this. Matters for band edges (D-09) |
| F-11 | "Cannot hallucinate" means **cannot go off-schema** (no invented option or tool name). It can still pick the wrong option. | B | Treat as a type guarantee, not a correctness one |
| F-12 | Context window: our contract note says **32K**; one video says 64K. | A vs C | Trust 32K until we measure it. Full scratchpad plus a long checklist fits; a prior report plus the scratchpad might not |
| F-13 | Latency: vendor says 70–500 ms. EU-based developer saw ~500–600 ms. Voice browser: p50 ~300 ms, avg ~330 ms with 3–6K input tokens, and **the first request of a process ~700 ms because of the TLS handshake**. | A | We measure ~290 ms p50 from the UK. **We open a new `httpx.AsyncClient` per call** (`utterance_bundle.py:106`, `dictation_triage.py:141`, `section_coverage.py:101`), so every call pays a handshake. See D-01 |
| F-14 | Pricing: $0.042/M input, output free. Field reports: 1,000 emails × 7 questions ≈ 9 ¢; 1,700 emails ≈ 18 ¢; 586-page internal-link map 21 ¢. | A/C | Cost is irrelevant at our volume. Latency and calibration are the currencies |
| F-15 | Jev **selects tools but cannot extract arguments**. Anything that must become text (search query, typed value, URL) is extracted as candidate spans by code, Jev *points* at one, and code copies it verbatim. | A (voice browser) | Core pattern for corrections, ASR repair and navigation (D-02) |
| F-16 | Failure domains reported: price/Bitcoin prediction (no edge, lost to fees); tasks that need world knowledge or multi-step reasoning; free-form "analyse this" questions. | C | Consistent with our "weak" column (time, taste, unstated domain knowledge) |
| F-17 | RLCD (reinforcement learning for calibrated decisions) is unpublished. The founder explicitly **did not claim calibration is perfect**; fine-tuning is "a desire, not a promise". | B | Calibration is a vendor claim we have **never measured** (D-03) |
| F-18 | Open alternatives exist with the same wire API: **OpenJev** (DiffusionGemma 26B-A4B; vLLM on NVIDIA, MLX on Apple, MLX serial-only); Sam Witteveen ran a local "open Jev" at 88 ms. | B | Gives the vendor-neutral `classify(state)` protocol (rev 2 §5) a real third implementation, and a data-residency exit (X-09) |
| F-19 | Data governance: clinical text goes to a new US vendor through OpenRouter. One reviewer (Dave Ebbelaar, NL) flags this as the main blocker for client work. | B | **Open governance question for us**, not yet answered anywhere in our docs (X-09) |

---

## 2. Field patterns (P): what people build, and the transferable mechanism

| ID | Build (who) | Mechanism | Maps to us |
|---|---|---|---|
| P-01 | **Voice browser** (Moritz Kremb) | Web Speech partials → **200 ms debounce** → one Jev call with 9–11 questions per partial → **≤2 in flight, older aborted** → policy: act / wait / ignore / confirm / disambiguate. **A partial may act only if its words already commit to a closed-set action ("go back"); free text is never final on a partial.** | D-04: interim-transcript speculation for commands |
| P-02 | Voice browser | Questions include `is_command` ("is this addressed to me?", ≈0.02 on chatter), "is the command complete?", "is it destructive?" | `noise` action; `standalone`; confirm on committed-zone edits |
| P-03 | Voice browser | **Numbered badges** when target confidence < 0.45: the user says "two", and **code** resolves it with no model call | D-06: numbered correction targets |
| P-04 | Voice browser | Page snapshot of ≤100 elements with short ids (e01…) as the **runtime option set**; Jev's answer is one id, so it cannot click something that isn't there | Rev 2 §6.1 "runtime options": scratchpad lines/sections as ids |
| P-05 | Voice browser | All question texts, thresholds and the model pin in **one file** (`constants.js`), "the one file to review". Word-by-word replay of real sessions is the end-to-end test (34 real-API cases incl. corrections) | We scatter question text across 4 modules (D-10) |
| P-06 | Model router (Sam Witteveen; LangChain `ModelRouterMiddleware`) | Choice = lane, Score = difficulty, Noul = privacy gate, all in one call; low confidence → safe default; "choose the least costly model that can finish the job" | X-02: FAST vs BEST analyser routing |
| P-07 | **Auto-mode guard** (LangChain `AutoModeMiddleware`; OpenRouter cookbook) | Noul-gate every tool call *before* it executes. **Fail closed**: a transport error or missing answer throws, never approves | X-03: agentic pipeline tool gating. Note that our dictation path fails *open* by design, which is right for capture and wrong for gating |
| P-08 | **Publishing traffic light** (Goldie) | 3 nouls per draft (answers the brief? unsourced claim? links sensible?) → green publish / amber review / red back to the writer | X-01: report pre-sign-off light |
| P-09 | **Claim verification** (podcast summaries, flaviocopes) | An LLM writes; Jev nouls each claim against the transcript; code flags the low ones | X-01: per-sentence "supported by dictation" noul, a hallucination guard |
| P-10 | **MinusPod** ad removal | One noul per transcript segment → join flagged segments into spans | Rev 2 pattern B (audit spans), shown to work in practice |
| P-11 | **Internal link map** (586 pages, 21 ¢) | Per-page Choice "which page should this link to, if any"; **139 pages left alone because nothing fitted**. The exit option was the valuable output | Every chained choice needs "none" (rev 2 §6.3). Same for guideline suggestions |
| P-12 | **Context meter** (Claude plugin, ~1M → 86K tokens) | Score each tool call in an agent's history for "still matters"; drop the rest. **Theo's pushback: filtering loses the trail of why the agent acted → prefer reorder or soft-demote to delete** | X-04: guideline/context selection for generation |
| P-13 | Email/YouTube/meeting corpus analytics (Nate Herk) | Jev can't find themes, but **many atomic questions over a corpus give a dataset that tells the story** (e.g. "% of calls with no owned next step") | X-05: report-corpus analytics in Metabase |
| P-14 | Generative UI from a component library (Riley Brown) | Jev doesn't write UI. It *selects* and arranges pre-built components in under a second | X-06: normal-fill as selection from canonical phrases |
| P-15 | Composite scoring (docs); code review per file | Break one judgement into atomic Scores/Nouls; **combine with weights in code**; change a number, not a prompt | X-07: critical-finding / significance tiers |
| P-16 | Competitor monitor (Goldie) | One Noul "does this change actually matter to us"; only the tiles above the line light up | X-08: interval change vs prior report |
| P-17 | "Is the task done?" in a coding-agent loop (flaviocopes) | A cheap noul asked many times per task | X-03 |
| P-18 | Clipfast / clip finder | Segment-level scoring of a long transcript in ~2–3 s | Retrospective dictation review (idea O-03) |

---

## 3. Dictation — high-yield insights (D), ranked by value ÷ effort

**D-01 · Reuse one HTTP client (connection pooling + warm-up).** *Effort: an hour. Value: every Jev call.*
All three Jev clients build a new `httpx.AsyncClient` per request, so every call pays DNS, TCP and TLS setup. The voice browser measured a first call of ~700 ms against ~300 ms for warm calls; ours are all "first calls". Fix: one module-level `AsyncClient` (HTTP/2 or keep-alive) shared by triage, bundle and coverage, plus a warm-up ping when the dictation socket opens. Then remeasure p50/p95 with a baseline and interval. Expected result: a lower p50 and, more importantly, a thinner p95 tail. Our "latency" numbers so far include the handshake, so rev 2's 500 ms gate has more headroom than we thought.

**D-02 · Pointer, not writer: code extracts candidate spans, Jev picks, code copies verbatim (F-15, P-04).**
This is the most transferable single pattern in the field. For us:
- *Corrections* ("no, right kidney", "change 12 to 14 mm"): code enumerates target spans in the section(s) the bundle's section nouls selected (laterality tokens, measurements, negations), Jev picks the target from a runtime Choice, and the replacement is **copied from the utterance span**. Most laterality, measurement and negation corrections then need no model call. This is rev 2 pattern C made concrete, with a stronger no-fabrication guarantee than a Qwen rewrite.
- *ASR repair*: candidates from the scan-type keyterms, with "(as heard)" mandatory. That's rev 2 pattern A, now confirmed as a field pattern.
- *Navigation* ("go to liver", "next section"): section ids as options.

**D-03 · Measure calibration before relying on it.** *Effort: small. Value: validates the whole band design.*
Rev 2 says "Jev's distinct value is calibration, not accuracy", but `bakeoff_stats.py` computes accuracy, Wilson intervals and p95 only. Add **Brier score, ECE (5–10 bins) and a reliability table** per question to every bake-off, for Jev *and* Qwen-off (Qwen via logprobs or a verbal confidence, as a contrast). If Jev isn't better calibrated than Qwen-off on our data, rev 2's own rule says the vendor dependency isn't earned. This is the check that decides whether we keep Jev at all, and we haven't run it.

**D-04 · Speculate on Deepgram interim results; act early only on closed-set commands (P-01).**
Today we wait for Deepgram *finals*. The voice browser asks Jev on every partial (200 ms debounce, ≤2 in flight, abort older) and allows early action **only when the words already commit to a closed-set action**. Free text waits for the final. Our equivalent: run the bundle on interim transcripts so the decision is already there when the final lands. Let `command` answers ("new paragraph", "delete that", "next section", "undo") fire on a stable interim; appends and corrections always wait for the final. This takes Jev latency off the perceived critical path altogether, which is a better win than shaving ms.

**D-05 · Put real-input examples inside criteria (F-07).** *Directly targets our two known weak spots.*
- `standalone` under-fires on finished statements split across buffer + chunk or carrying ASR errors (cmp-02/04/10/12/13, asr-01/02 at 0.23–0.48). Add two or three examples *shaped like those inputs* to the criteria.
- Coverage under-credits collectives ("thoracic structures", solid-organ collectives). Add in-domain examples per section *and* keep the static collective→section map in code (rev 2 §3.3).
- Guardrail: freeze the fixtures first and use **new** lab exports as the test set, because we already tuned against the current fixtures (overfitting note, 2026-09-26).

**D-06 · Numbered disambiguation instead of a guess (P-03).**
When the correction target's confidence is below band, show small numbered badges on the candidate lines in the scratchpad; the radiologist says "two"; **code** resolves it. That's cheap, visible and reversible, and it replaces "escalate to Qwen" for the commonest ambiguous case. Keeps the rev 2 invariant "a wrong decision must be visible and undoable".

**D-07 · Use the full distribution: top-2 margin and named confusion pairs (F-02).**
Threshold on `p1 − p2` for the known expensive pair (correct ↔ append) rather than on `confidence` alone. The only triage miss (append-06) came in at 0.93 *confidence*; its margin is the more informative number. Log `probabilities` in shadow (lengths and hashes only, never text).

**D-08 · Phrase nouls as statements, high = yes; one judgement each (F-06).**
Cheap A/B on the existing fixtures: `standalone` as "These words form a complete clinical statement" against the question form, and split any compound nouls. Keep whichever wins on unseen lab exports.

**D-09 · Double-ask at band edges only.**
Repeat calls vary (F-10). For the small share of answers that land inside the escalate band, a second identical call (~$0.00002, run in parallel with the first retry) and averaging reduces variance before we pay for Qwen. That's a rev 2 pattern-E variant and needs measuring: how often does the second sample move the answer out of the band?

**D-10 · One question registry (P-05).**
Move every question text, criteria, option map and threshold for triage, bundle and coverage into one module (`jev_questions.py`) with a version string logged per decision. It makes review, the lexicon/wording freeze and shadow attribution trivial.

**D-11 · "Addressed to me" and destructive confirm (P-02).**
Radiologists talk to colleagues and answer phones mid-dictation. An explicit `addressed_to_system` noul is a sharper question than folding it into `action = noise`, so test it in the bundle. Edits touching the frozen/committed zone get a confirm toast (the voice browser's "say confirm").

---

## 4. Beyond dictation (X): other parts of the product

**X-01 · Report integrity guard: per-sentence support nouls (P-09, P-08).**
After generation, split the report into sentences in code and ask one noul per sentence: "This sentence is supported by the dictated findings" (state = scratchpad + sentence). Add fixed nouls for our standing rules: "restates clinical history" (L-36), "asserts a normal the radiologist didn't dictate and the sheet didn't default" (defeasible normal-fill), "contains a measurement not present in the dictation". Code turns these into a traffic light before sign-off. This is a ~300 ms fabrication detector that runs on every report, not a sampled Sonnet audit. It complements the report-integrity hardening (Aug 2026) and is rev 2 pattern B turned on our own output.

**X-02 · Per-case FAST/BEST routing for the analyser (P-06).**
Today GLM FAST and Haiku BEST run as a dual variant by design (memory: `project_analyser_dual_variant`). A Score "how much capability does this case need" plus nouls (multi-region? prior comparison? critical finding?) could route per case. Measure it first as a shadow: how often does FAST's output match BEST on cases Jev calls easy? Don't change the dual-variant design until that data exists.

**X-03 · Gate agentic-pipeline tool calls; "is it done?" (P-07, P-17).**
`agentic_pipeline.py` could noul-gate tool calls (relevant? redundant with a prior call?) and ask "is the plan complete?" instead of spending another reasoning turn. **Fail closed** here, unlike dictation.

**X-04 · Guideline and context selection as Scores (P-12).**
`guideline_prefetch` and IntelliPrompts (rev 2 component 6): a Score per candidate guideline or prompt for "relevant to these findings", keep the top-k, **demote rather than delete** (Theo's caution) so the generator can still see why. The registry supplies the options, so there's no fabrication. IntelliPrompts is our largest measured dictation latency (2.8–6 s), so this has the biggest payoff in the product.

**X-05 · Corpus analytics on production reports (P-13).**
A fixed battery of atomic nouls over every stored report (comparison present? incidental finding with recommendation? laterality stated for paired organs? critical finding communicated?) at fractions of a cent per report, feeding the Metabase dashboard (`reference_metabase_dashboard`). Use it to pre-screen, with the v2.1 Sonnet judge running only on flagged reports, which cuts judge cost and widens coverage from a sample to the whole corpus.

**X-06 · Normal-fill as selection, not generation (P-14, F-15).**
For sections the radiologist didn't dictate, don't have Qwen write the normal. Have Jev (or code) **select** from the skill sheet's canonical normal sentences per section: Choice over the sheet's approved phrases plus "none — leave for the radiologist". Normals are then verbatim, pre-approved text with zero fabrication risk, and generation is reserved for abnormal prose. Fits the defeasible normal-fill design and reduces the load on the 93–95 % reasoning budget (rev 2 pattern D).

**X-07 · Significance and critical-finding tiers by composite scoring (P-15).**
Atomic nouls (new vs prior? acute? potentially life-threatening? needs action within 24 h?) combined with weights in code → the severity banner tier in `enhancement_models`. Weights live in code and are auditable, and changing a number doesn't require a prompt change. This needs its own labelled set and a calibration check (D-03) before it touches a banner.

**X-08 · Interval change against the prior report (P-16).**
When a prior report exists: per finding, noul "changed compared with the prior" and Choice (new / larger / smaller / stable / resolved / not in prior). Code aligns findings by organ first. This feeds the comparison sentence and the traffic light (X-01).

**X-09 · Data residency and the vendor exit (F-18, F-19).**
Before production default-on, answer: does sending de-identified dictation text to TypeSafe via OpenRouter meet our governance position (UK/NHS)? Can we send hashes and positions instead of text for any question? Is OpenJev on our own GPU (or MLX for dev) accurate enough on our fixtures to be the fallback? The `classify(state)` protocol already allows the swap; a bake-off column for OpenJev turns this from a hope into a measured fact.

---

## 5. Outside-the-box ideas (O), speculative, each needs a cheap test first

- **O-01 · Template/protocol autoselect at session start.** One Choice over the skill-sheet library, fed with the first utterance plus the worklist metadata, suggests the sheet before the radiologist picks. Same idea as P-14 (select from a library).
- **O-02 · Live "what's left" prompt.** Section nouls already accumulate coverage. At a dictation pause, the uncovered sections plus one noul ("is this section usually commented on for this indication?") give a quiet reminder, like a checklist the radiologist can ignore. It's the monitor pattern P-16 applied to omissions.
- **O-03 · Retrospective dictation review.** Score every utterance of a finished session (like the clip finder, P-18) for "caused an edit", "ASR-suspect" and "hesitation". That produces a labelled fixture set with no human labelling, which feeds rev 2's "fixtures grow from the lab".
- **O-04 · Radiologist-style profile as fixed nouls.** Per-user decisions (prefers "no" vs "not seen", measurement format, section order) become typed preferences learned from their edits, and code applies them. No model writes style.
- **O-05 · Jev as eval judge for our own classifiers.** Rather than hand-labelling everything, use Jev at ≥0.95 plus Qwen-off agreement as a silver label, with humans reviewing only disagreements. This must never replace blind radiologist labels for the gate sets.

---

## 6. Cautions (keep us honest)

1. Most field "wins" are sorting at scale with a human reviewing the unsure pile. Very few are reported with accuracy numbers. Our own bake-offs remain the only accuracy evidence that counts.
2. Our accuracy numbers are in-sample on small fixtures we wrote ourselves (overfitting review, 2026-09-26). Freeze the lexicon and question texts before any comparison in this doc.
3. Calibration is claimed, not shown (F-17, D-03).
4. The fail-open vs fail-closed choice is per use: capture fails open, gates fail closed (P-07).
5. Governance (X-09) is a precondition for production default-on, not a later detail.

---

## 7. Suggested order of work (fits rev 2's build order; doesn't replace it)

| # | Item | Why now | Exit |
|---|---|---|---|
| 1 | **D-01** shared client + warm-up | Hours; changes every latency number we report | p50/p95 with intervals, before vs after |
| 2 | **D-03** Brier/ECE/reliability in `bakeoff_stats` | Decides whether Jev earns its place (rev 2 §2) | Jev vs Qwen-off calibration on all three sets |
| 3 | **D-10** question registry + version in logs | Needed before the production shadow (component 0) so decisions are attributable | One module; shadow logs carry `qset_version` |
| 4 | **D-05 / D-08** criteria examples and statement form, tested on *new* lab exports | Targets `standalone` and collective recall | Beats frozen lexicon on unseen sessions |
| 5 | **D-04** interim-transcript speculation for commands | Removes decision latency from the critical path | Command precision 1.0; perceived command latency |
| 6 | **D-02 + D-06** span-pointer corrections with numbered fallback | Rev 2 component 5 without Qwen for the common kinds | Laterality/measurement/negation fixed with no model call |
| 7 | **X-01** per-sentence integrity nouls (shadow) | Highest value outside dictation; reuses the same client and registry | Agreement with the current audit on flagged set; zero added latency on the render path |
| 8 | **X-09** governance answer + OpenJev bake-off column | Precondition for default-on | Written decision; OpenJev accuracy/latency column |

## Sources

- NotebookLM notebook "Jev" (8 sources, exported 2026-09-26)
- TypeSafe docs: https://docs.typesafe.ai/llms.txt · patterns/fan-out · patterns/confidence-routing · patterns/composite-scoring · primitives/noul · primitives/choice · confidence
- Voice browser: https://github.com/moritzkremb/jev-voice-browser
- Latent Space, "Jev: System One models for Prod, not God": https://www.latent.space/p/jev
- LangChain, "Building a harness with Jev": https://www.langchain.com/blog/building-a-harness-with-jev
- Flavio Copes, "A deep dive into Jev": https://flaviocopes.com/jev/
- Kartik Pansuriya, "Calibration beats accuracy": https://www.kartikpansuriya.com/blog/jev-system-one-model-calibrated-decisions
- OpenRouter cookbook, "Gate tool calls with Jev"
- OpenJev: https://github.com/longzhenren/openjev
