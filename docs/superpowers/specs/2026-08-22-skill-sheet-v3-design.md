# Skill Sheet v3 — Design

- **Date:** 2026-08-22
- **Status:** Draft for review
- **Supersedes (in the parallel path):** `backend/src/rapid_reports_ai/report_v2.py`
- **Evidence base:** `docs/model-migration/parameter-ledger.md` L-01 … L-32
- **Production impact:** none. v3 is a parallel path, test-guarded, exactly as v2 was.

---

## 1. Why v3

Two generations of quick-report prompts have shipped: v1 (`ANALYSER_SYSTEM_PROMPT_OPEN_WEIGHTS`,
8 phases → 10-section sheet, ~14.6 KB) and v2 (`ANALYSER_V2`, → 7-section DECISION SHEET,
~5–6 KB). Neither has closed the quality gap, and the reasons are now specific rather than
diffuse.

**Three findings frame the work.**

**(a) Sheet size is not a lever.** L-01 (size → quality: flat), L-02 (size → latency:
sub-linear), L-30 (YAML re-encoding: −16 input tokens), L-26 (generator output set by clinical
task, not input bytes). Four independent measurements. v3 does not target a smaller sheet and
may produce a slightly larger one.

**(b) The remaining gaps are two nameable behaviours.** L-32 measured `off_on` at ~4.1 against
an `on_on` baseline of 4.4, with the best finding-coverage of any cell (7/7 canaries × 3 runs,
zero drops). The two residual failures were **collision-blind mandatory negatives** and
**must-appear erosion** — both located in the sheet layer, not the architecture.

**(c) v2's current form has never been measured.** The last v2 artifact is
`test_output/V2_FMT2/runs.json` (Aug 15 04:03). Six prompt commits landed after it — including
`4f1eb43` which introduced `## STRUCTURE`, absent from **0 of 17** sheets in `V2_FULL` and
unchecked by `validate_sheet_v2`. Any claim that "v2 didn't move the needle" is currently
unsupported by data.

---

## 2. What the sheet is for

The generator already holds medical knowledge, writing skill, and the dictation. It lacks
exactly four things, and these are the only things the sheet may carry:

1. **A denominator** — what was *not* dictated but must still be covered. Only a pre-dictation
   artefact can supply this. (L-16: without it, real findings fall through the floor.)
2. **Pre-commitments made before the evidence arrives** — what "normal" looks like at a station,
   decided uncontaminated by what was found.
3. **Tiering** — what this study is *for*, decided once, so the impression does not re-litigate
   priority per case.
4. **A stable skeleton** — so the same case shapes the same way on every run.

**The editing rule that follows:** for every candidate field, ask whether the generator does it
better *with the dictation in hand*. If yes, it does not belong in the sheet.

Applied, this deletes style exemplars, impression exemplars, interpretive clause rules and most
terminology rules — which is approximately what v2 already did. It also identifies what v2 is
missing, all of it in category (2): anticipated collisions, impression coverage, and thresholds.

---

## 3. Design rules

| # | Rule | Source |
|---|---|---|
| R1 | Countable over prose. A requirement that can be counted complies ~100%; prose ~40%. | L-03, L-18, L-20 |
| R2 | Bind at point of use. Distance between a rule and the field it governs kills it. | L-24 |
| R3 | **Anything the analyser can decide without the dictation, it decides.** Every conditional left in the generator is a place reasoning-off breaks. | L-31 |
| R4 | Constrain impression *coverage*, never *composition*. | L-13 vs L-32 |
| R5 | No emittable prose in the sheet except explicitly marked templates. | prompt review F1/F7 |
| R6 | If a rule is the same for every case, it never belongs in the sheet. | §4 below |

R6 is new in v3 and is the main structural change: v2 carries invariant policy inside both
prompts. v3 hoists it into a third artefact.

---

## 4. Three layers

### 4.0 What production already does

A global layer exists and is already injected into quick reports — two of them. The composition
happens in `template_manager.py:2547`, reached because `quick_report_api.py:430` places
`QUICK_REPORT_HARDENING_PREAMBLE + <sheet>` into the `skill_sheet` slot of `template_config`:

| layer | size | origin |
|---|---|---|
| `SYSTEM_PREAMBLE` | small | `global_style_guide.py` |
| `GLOBAL_STYLE_GUIDE` | 13.4 KB, 16 sections | shared with the templated path |
| `QUICK_REPORT_HARDENING_PREAMBLE` | ~23 KB, 12 numbered principles | quick-specific |
| ephemeral sheet | ~14.6 KB | analyser |
| `PRE_WRITING_ANALYSIS` + `VERIFICATION_CHECKLIST` | user prompt | `global_style_guide.py` |

Approximately 50 KB of policy reaches the generator before the dictation does. v2
(`report_v2.py`, imports `re`/`time`/`typing` only) deliberately uses none of it — a clean-slate
choice, not an oversight.

**Two problems with the current stack.**

*Templated-path contamination.* `GLOBAL_STYLE_GUIDE` was authored for the templated path and
carries `Parameter Placeholders`, `Fixed Blocks and Parametrisation` and `Skill Sheet Internals
vs Output`. v1's analyser states plainly that "the emitted sheet contains no curly braces and no
parameter placeholders" — so the quick generator carries rules governing a construct that by
design never occurs. Dead prose competing for attention against live rules is L-24's mechanism.

*Duplication across layers.* Hardening principle 12 (a canonical line is a proposal, not a
warrant) is the defeasibility rule, which also appears inside the sheet via v1 Phase 6. A rule
living in two layers is the "analyser prompt exists TWICE, edit both" hazard already recorded in
project memory, one level up. The impression is the worst case: its rules live in **five** places
— `GLOBAL_STYLE_GUIDE`'s "Impression as Synthesis", hardening principles 1/3/10, the v1 sheet's
`## Impression Exemplars`, `PRE_WRITING_ANALYSIS` step 2, and `VERIFICATION_CHECKLIST` — with
descriptor propagation, clinical-context propagation and semicolon-clause recommendations each
duplicated across two or three of them. That the impression is simultaneously the most-praised
section (L-13) and the most persistently failing one is unlikely to be a coincidence.

*The policy layer is coupled to the v1 sheet grammar.* This is the finding that explains the
programme's shape. `QUICK_REPORT_HARDENING_PREAMBLE` and `VERIFICATION_CHECKLIST` name v1 sheet
fields directly — *style exemplars*, *impression exemplars*, *canonical line*, *mandatory
negatives*, *fixed blocks*. A v2 sheet has none of them; it has `OBLIGATIONS`, `T-NEG`, `T-IND`,
`UNASSESSABLE-IF`. So feeding a v2 sheet into the existing scaffolding hands the generator a page
of rules about fields that are not in the sheet it was given.

**Consequence: v2 has never run inside the system scaffolding, and could not have.** `v2_run.py`
calls `generate_sheet_v2`/`generate_report_v2`, which pass `ANALYSER_V2`/`GENERATOR_V2` bare,
while every v1 harness goes through `template_manager` and inherits the full stack — roughly
42 KB + 33 KB against roughly 8 KB + 13 KB. `report_v2.py` going self-contained was not a
deviation from the intent of "change the sheet only"; it was the only way to change the sheet at
all. Every v2 number therefore measures a different *pipeline*, not a different *sheet*, and
"v2 didn't move the needle" has never actually been tested.

A sheet-agnostic policy layer is what makes "change only the sheet" a coherent operation, and it
is the precondition for §9's experiment.

### 4.1 What v3 changes

Three layers, and the global one is a **consolidation of two existing artefacts**, not a new
invention:

```
GLOBAL POLICY  (invariant; same bytes every case)
      ↓ referenced by both stages
SHEET          (per case; the four things from §2)
      ↓ consumed by
GENERATOR      (absolutes + one real conditional + free composition)
```

`report_v3_policy.py` **supersedes** `QUICK_REPORT_HARDENING_PREAMBLE` and ends the quick path's
use of `GLOBAL_STYLE_GUIDE`. `global_style_guide.py` is left untouched for the templated path,
which decouples the two paths and removes the contamination above in one move.

**One document, both stages.** It was drafted as two constants split by audience — principles to
both, composition to the generator only — on the reasoning that the analyser never writes a
COMPARISON section or an impression. That was wrong. The analyser does not *write* those sections
but *designs the structure they will have*: its `T-NEG` templates land verbatim in FINDINGS and
must obey findings register, and `FLOW/ORDER` is a consolidation plan governed by the
consolidation rules. Withholding either would separate a rule from the field it governs — L-24,
reproduced. A split with no runtime meaning also invites the next wrong call about what belongs
where, so there is one `POLICY`, ordered principles-then-composition, and both stages receive all
of it.

**A structural side-effect worth measuring.** Because the sheet now travels in the *user* message,
both system prompts are byte-identical on every call. v1 builds the generator's system prompt as
`SYSTEM_PREAMBLE + GLOBAL_STYLE_GUIDE + hardening + the sheet`, so it varies per case and can
never be prefix-cached. No claim is made about the size of the win — it has not been measured —
but v3's arrangement is capable of it and v1's is not. Instrument it alongside §9's experiment.
`PRE_WRITING_ANALYSIS` and `VERIFICATION_CHECKLIST` are not carried into v3 — ledger
open-question #5 already names them as the most likely lever on generator reasoning cost, and
their function is replaced by §6's Checks step plus §7's deterministic gate.

`QUICK_REPORT_HARDENING_PREAMBLE` is the right shape to build on — principle-stated,
case-agnostic, single source of truth across proto and production. Most of its content is
retained; what changes is that policy stops being scattered across four layers with overlap.

**Already present in the hardening layer, retained rather than invented:** descriptor
propagation, causal structure over anatomical sweep, strict section boundaries, gender-signal
calibration, canonical-line defeasibility, impression-obligations-over-length.

**Genuinely absent from every current layer, and therefore net-new below:** the calibrated
uncertainty lexicon and the banned-phrase list. The COMPARISON rule exists in v1's sheet
(Phase 3) and moves here — a relocation, not an addition.

Contents, all scan-type-invariant and therefore free per case:

**Calibrated uncertainty lexicon.** Fixed phrase → probability band. The system currently has
nothing of the kind, and L-30's worst manual-read defect was exactly this failure: dictated
"hypodensities … not fully characterised" reported as "renal cysts".

| Phrase | Band |
|---|---|
| diagnostic of / consistent with | >90% |
| probable / likely represents | ~70–90% |
| possible / may represent | ~25–50% |
| unlikely | <10% |
| no evidence of | below detection **on this study** — not proof of absence |

The last row is the report-facing statement of the same epistemics the `T-NEG` / `T-IND` split
encodes internally.

**Banned phrases**, enforced by regex in the gate:
- "cannot be excluded" without a probability qualifier *and* a resolution path
- standalone "clinical correlation recommended"
- "no significant abnormality"
- "stable" applied to a measurable lesion without both numbers
- management-trespass vocabulary (L-24): treatment, dosing, operative choice, hardware,
  rehabilitation

**COMPARISON content rule.** Restored from v1; v2 mandates the section in §0 and never says what
goes in it. Three branches:
1. dictation names a prior → carry it as given
2. no reference **and** no comparison-dependent language → state no prior available
3. no reference **but** findings use *new / stable / improved / progressed / unchanged /
   resolved* → acknowledge generically, never inventing scan type or date

**Style register.** British English, impersonal, present tense for findings, DD/MM/YYYY, mm/cm,
consistent precision. Laterality and vertebral levels checked between body and impression, never
assumed.

**Not adopted from the NHS reporting skill**, with reasons:
- *"Pertinent negatives only; no organ-by-organ litany"* and *"normal body ≤ 5–8 lines"* —
  contradicts L-16 and the systems-review architecture. That guidance is calibrated for drafting
  from human-curated findings; here, silence in dictation is ambiguous and the enumerated
  denominator is what stops findings vanishing. L-13's consultant asked for editorial selectivity
  **on incidentals in the impression**, never for deletion of the sweep.
- *Worked good/bad example pairs* — F1/F7. v2 made verbatim leakage structurally impossible;
  reintroducing exemplars anywhere reopens it. Ruled out.
- *"No abbreviations in the conclusion"* — conflicts with `project_skill_sheet_as_framework`:
  classification taxonomies (Bosniak, CAD-RADS, RECIST) are clinical vocabulary, not jargon.

---

## 5. Sheet grammar

```
# SHEET
## CASE          — question ⇒ gate, plus the history that conditions it
## FLOW          — topology × breadth × render order
## LIMITS
## OBLIGATIONS   — the denominator
## VERDICT       — one line; the sheet's only word on the impression
## MEASURE
```

### 5.1 CASE

```
- MODALITY: <modality and technique>
- QUESTION: <primary clinical question, decomposed> => GATES: <the management decision it gates>
- BEARING: <a datum from this history> => <how it moves that gate or conditions the reading>
- SECONDARY: <further questions, comma-separated, or "none">
```

`BEARING` is new and carries what §5.5 previously proposed as an impression manifest. A prior
stroke does not matter because it sits on a list — it matters because it changes what the gate
turns on. Stated here it conditions the question, so engaging it is *entailed* by answering the
question properly rather than *enumerated* as an item to discharge. Optional, typically 0 to 4,
and never required: a minimum would make the analyser manufacture entries.

### 5.2 FLOW — adaptive density

Merges v2's `VOLUME` and `STRUCTURE`. Two axes, both derived from the imaged volume, neither
fixed by the prompt:

- **Topology** determines block structure: `FLAT` (single field of assessment — the default),
  `COMPARTMENTS` (anatomically disjoint fields, each effectively its own examination), `UNITS`
  (the same criteria repeat across serial units).
- **Breadth** determines skeleton density *within* that structure: `FOCUSED` (volume spans one
  organ system → one group, canonical negatives inline) or `BROAD` (volume spans multiple organ
  systems a consultant would systematically comment on → per-station groups, each with its
  canonical line).

```
- TOPOLOGY: FLAT | COMPARTMENTS: <name> => <stations> ; … | UNITS: GLOBAL => … ; PER-UNIT => …
- BREADTH: FOCUSED | BROAD
- ORDER: <the groups, in render order, each naming its stations>
- OUT: <structure> => <alternative test>   (one line each; only structures the question implicates)
```

`ORDER` is the skeleton for the **all-silent case**. The generator breaks a station out into its
own paragraph when the dictation makes it positive — that decision is dictation-dependent and
therefore stays with the generator per R3's converse. This is v1's "Normal-study path"
behaviour, restored and made explicit.

Coverage is total: everything the scan images belongs to exactly one group. Structures running
continuously through several compartments (the vertebral column on any body protocol above all)
are their own compartment at their anatomical position, never entries in a terminal block. A
terminal group holds only soft tissues and true incidentals.

### 5.3 LIMITS

Unchanged from v2. Facts about physics bearing on the question — the only assertions the
analyser is permitted.

### 5.4 OBLIGATIONS — the denominator

One block per station. **Every station in `FLOW/ORDER` carries at least one obligation**, whose
`T-NEG` is that station's canonical normal statement. This is the systems review; a station
without an obligation vanishes silently from the report (L-16).

```
- OB<n> | <QUESTION or COMPLETENESS> | <station>
  OBSERVES: <the single observation this obligation rests on>
  EXPECT: <finding classes this clinical question makes plausible at this station, or "none">
  T-NEG: "<sentence emitted when dictation is silent AND the observation was assessable>"
  UNASSESSABLE-IF: <dictated classes that make OBSERVES unreadable> ; NOT: <near-miss terms>
  T-IND: "<indeterminate sentence naming {obscurant}>"
```

**Two changes from v2.**

**`EXPECT` is new, and `T-NEG` is constrained by it.** A `T-NEG` may not negate any class named
in its own `EXPECT`; where the question makes a class likely, the analyser writes the
discriminating subset instead. This is L-32's root cause addressed at source: the reasoning-ON
analyser wrote *"No pneumoperitoneum"* — leaving room for the mural gas the question makes
likely — while the reasoning-off analyser wrote textbook negatives blind to collision risk. Made
countable, the behaviour no longer requires reasoning to produce, and the gate can check it.

This is structurally stronger than L-20's countable defeasibility, which complied perfectly and
still did not fix the contradiction: L-20 encoded *a rule the generator must apply*, whereas
`EXPECT` changes *what the analyser writes*. The unsafe negative never exists, so there is
nothing left to conditionally suppress. Removal beats conditional application.

**`SUPPRESS-IF-HISTORY` is deleted.** The analyser holds the history; it must resolve it rather
than pass a conditional downstream. Where the history voids a normal line, the analyser omits
`T-NEG` entirely or writes a contingent form that does not assert. v2's own ct_tap sheet shows
the failure this removes:

```
- OB5 | COMPLETENESS | abdominal aorta
  T-NEG: "Abdominal aorta shows no acute change."
  SUPPRESS-IF-HISTORY: known 3.8 cm infrarenal aneurysm (voids routine normal line)
```

The analyser knew the line was void and wrote it anyway, plus a rule to suppress it. Generator
branch (c) exists only to service this. Both go.

### 5.5 VERDICT — one line, and the sheet says nothing else about the impression

v2 gives FINDINGS nine typed blocks and IMPRESSION pure prose. Against R1 that asymmetry predicts
exactly what L-31 and L-32 measured (stroke 0/3, AF 1/3, lactate 2/3). The obvious fix — a typed
impression block with a `CARRY` manifest — was drafted and then rejected in review, for good
reason.

**Why a manifest is the wrong shape.** The impression is a distillation of the findings, not a set
of slots. A list of items to include gets *discharged* rather than distilled: the generator
appends "the previous stroke is noted" and the section drifts back toward the inventory register
`c4b6bc4` was written to eliminate. This mechanism is already documented twice in your own system.
v1's prompt: *"Narrative prescriptions… the generator copies them verbatim and the impression
bloats."* And v2's generator has to say `RECOMMEND` is *"not a quota to spend"* — a sentence that
exists only because a list in the sheet created pressure to spend it. A `CARRY` block would
reproduce exactly that.

So the sheet carries one line:

```
## VERDICT
- <the CASE question, restated> => FORMS: CONFIRMED | EXCLUDED | INDETERMINATE (<which LIMIT>)
```

`VERDICT` is a *constraint*, not a slot — "answer the question you were asked" adds nothing the
impression did not already owe, and cannot produce repetition, because the answer is the opening
sentence anyway. What the history contributes now sits in `CASE/BEARING` (§5.1), where it
qualifies the question rather than queueing for mention.

**The check survives; only the slot is removed.** `check_report_against_sheet_v3` still verifies
that every `BEARING` item reached the impression, so L-32's erosion remains detectable. The
generator is never shown a checklist; the instrument still catches the failure. That asymmetry is
the whole design.

**Format is integrated prose, not numbered points.** This is a deliberate departure from RCR
convention and from the NHS reporting skill, on the strength of the only direct clinician signal
in the ledger — L-13, where the consultant reviewed `off_on`'s integrated impressions and said
he "would be quite happy to sign those off". Numbering is more auditable but invites the
inventory register `c4b6bc4` was written to eliminate. Revisit only on radiologist request.

### 5.6 MEASURE — with thresholds

v2 §1 forbids "any reference value or threshold not in the sheet" while giving the sheet nowhere
to put one. Closed:

```
- <finding type>: <dimensions> <unit> — <when required>
  THRESHOLD: <value> => <what crossing it means>        (opt)
  PRIOR: <value> (<date>)                                (opt — surveillance cases)
```

`PRIOR` makes the "stable without numbers" gate check enforceable for surveillance lesions.

### 5.7 RECOMMEND — deleted

An earlier draft restored v1's urgency tier, which v2 had dropped. Review killed the section
outright instead. Run §2's editing rule over its fields:

| field | who decides it better |
|---|---|
| urgency tier | **the generator, decisively** — urgency follows from what was found, and the analyser is guessing pre-dictation |
| which service | the generator; the destination follows from the findings, and it knows UK NHS services |
| what an investigation resolves | the generator; general medical knowledge |
| the remit boundary | neither — it is invariant, and now lives in `POLICY`'s Scope derivation |

Every case-specific field fails the test. The one thing the section genuinely bought was L-24's
trespass guardrail, and that is now a banned-vocabulary rule prepended directly to the generator —
*closer* to the point of use than a sheet section, which matters because L-24's diagnosis was
rule-to-field distance in the first place.

Untested, and L-18 stands: directives are a coin-flip until run. The report checks flag
`management_trespass` deterministically, so one v3 run says whether the guardrail held without
the sheet section.

---

## 6. Generator prompt

Reordered so absolutes come first and flat (R2), and so the conditional surface is as small as
the design allows (R3).

| § | Content | Notes |
|---|---|---|
| 1 | **Authority** | Absolute, flat, first. Dictation semantically untouchable; truncation rule; unmatched dictated findings still reported; laterality-conflict rule |
| 2 | **Resolution** | Three branches as a table, not prose: DICTATED / UNASSESSABLE / SILENT-ASSESSABLE |
| 3 | **Render FLOW** | One line — the sheet computed the skeleton. Positives break out of their group |
| 4 | **Impression** | Free composition. The sheet fixes only what must be *resolved* (`VERDICT`), and `BEARING` is engaged because it conditions the question — not because it is listed |
| 5 | **Checks** | Terse, gate-aligned |

Branch count falls 4 → 3, and genuine dictation-dependent conditionals fall 2 → 1
(`UNASSESSABLE` only). v2 §3's three rendering-mode paragraphs — two of which are dead weight on
every call — collapse to a line.

---

## 7. Gate checks unlocked

All deterministic, all free, none requiring a model. This is the defect checklist L-30 asked for.

| Check | Mechanism |
|---|---|
| No `T-NEG` negates a class in its own `EXPECT` | sheet-level term match |
| Every `FLOW/ORDER` station appears in FINDINGS | station-token sweep |
| Every `CASE/BEARING` item appears in IMPRESSION | token match — the check the sheet no longer states as a slot |
| Nothing in IMPRESSION absent from FINDINGS, and vice versa for material findings | bidirectional closure |
| Numbers identical between FINDINGS and IMPRESSION | numeric extraction |
| Laterality consistent between FINDINGS and IMPRESSION | term match |
| Banned phrases absent | regex |
| "Stable" on a measurable lesion carries both numbers | regex + `MEASURE/PRIOR` |
| COMPARISON non-empty and consistent with comparison-dependent language | regex |
| No unfilled `{braces}`, no sheet notation | regex |
| `FLOW` present and well-formed | **fixes the `STRUCTURE` blind spot in `validate_sheet_v2`** |

Against the four defects L-30's manual read found while rubric v2.2 scored 5.00 on all 24
dimensions: renal "cysts" overcall (lexicon + qualifier), stripped "not fully characterised"
(banned/qualifier), stroke absent from impression (closure), dropped background atherosclerosis
(closure). Three to four of four, deterministically.

---

## 8. Out of scope

- Retrieval, scan-type matching, sheet persistence — parked by decision.
- Sheet compression as a goal (L-01/L-02/L-30).
- Any reintroduction of exemplars (F1/F7).
- Production cutover. v3 is parallel and test-guarded, like v2.

---

## 9. Sequencing

v3 must not become a third unmeasured iteration, and per §4.0 the previous two were never
compared on equal footing.

1. **Build the policy layer and the instrument.** `POLICY`, then the §7
   deterministic checks. Cheap, model-free, and they catch most of what L-30's manual read found.
   Optionally add a policy-driven semantic screen (`gpt-oss-safeguard-20b`, Apache 2.0, already
   served on Groq) *alongside* the gate for unencoded modes per L-28 — as a screen surfacing
   candidates for review, never as a score to optimise against (L-14).

2. **Run the three-arm experiment — and treat it as a gate.** A sheet and its generator are a
   matched pair, so the sheet grammar cannot be A/B'd alone. The policy layer *can* be, precisely
   because `POLICY` names no sheet fields:

   | arm | composition | what it is |
   |---|---|---|
   | A | v1 sheet + v1 generator + full legacy stack | production as shipped |
   | B | v2 sheet + `GENERATOR_V2`, bare | reproduces the existing artifacts |
   | C | v2 sheet + `GENERATOR_V2` + `POLICY` | **v2 as intended — never run** |

   C vs B answers whether dropping the policy stack cost anything. C vs A is the first fair
   comparison of the two pipelines. Sheets are generated once per case and reused across arms so
   sheet stochasticity cannot confound the result (L-30's method).

3. **Build v3 only if the gate says so.** If all three arms come out flat, the sheet grammar is
   not the lever and the work belongs at L-15 — inclusion/exclusion policy, with the radiologist —
   not in a third prompt rewrite. If the gate passes, measure v3 on the same 17-case
   `broad_suite.json` the v2 artifacts used, so the comparison stays like-for-like.

---

## 10. Risks

**Highest — generator-reasoning-off is a stated target, and the impression is integrated prose.**
These pull against each other. Integrated synthesis with correct prioritisation is the most
reasoning-dependent behaviour in the pipeline, and L-13's praise was of `off_on` — reasoning
**on**. L-31's `off_off` produced 546–826 output tokens against 6,900–8,700.

The case for reachability is nonetheless real: L-31's two named `off_off` failures were
conditional negative suppression and must-appear collapse, and `EXPECT` and `BEARING` target
exactly those. Its other faults — dropped dictated findings, unsupported assertions, one L-24
trespass — are each addressed by §1 Authority, a §7 check, or the banned list.

Treatment: **design for it, flip only on evidence.** Generator-off is a measured decision with
named gates, not an assumption. Record explicitly that an ~800-token report is a materially
different artefact from an ~8,000-token one, and that the consultant has reviewed only the
latter — so a generator-off flip needs its own clinical review, not just a passing gate.

**Medium — `EXPECT` may comply perfectly and not work.** This is L-20's pattern. The mitigation
is structural (removal beats conditional application, §5.4) but unproven. L-18 stands: directives
are a coin-flip until run.

**Medium — §6's reordering is where L-24's distance effects live.** Moving Authority to the front
should help; it could equally disturb something that currently works. Isolate it from the sheet
changes when measuring.

**Lower — `FLOW` breadth calibration.** If the analyser mis-classifies a broad study as focused,
the skeleton thins and L-16's failure mode returns. The §7 station-sweep check catches it
downstream, but the classification itself is a judgement the analyser makes blind.

---

## 11. Success criteria

**Primary:** analyser `reasoning_effort: none` becomes shippable — ~22s → ~8.5s, −60% analyser
tokens. The only clean efficiency win the evidence supports.

**Secondary:** both L-32 failure classes covered by deterministic gate checks, so neither needs a
manual read to detect.

**Stretch, gated on evidence:** generator reasoning off, subject to §10's clinical review
requirement.

**Explicitly not a criterion:** a smaller sheet.

---

## 12. Open items

1. **FLOW topology × breadth** — is the two-axis reading in §5.2 what was intended, or should
   breadth subsume topology into a single derived declaration?
2. **Critical-finding communication** (RCR actionable reporting). Proposal: emit
   `[CRITICAL FINDING — document direct communication: name, role, time, method]` as a
   placeholder rather than fabricating a communication event. Genuine compliance gap; product
   decision, not a prompt decision. Needs sign-off.
3. **Impression numbering** — settled as prose on L-13, but that is n=1 clinician on 5 cases.
   Worth re-testing at the next radiologist review.
4. **Global-layer decoupling.** v3 ends the quick path's use of `global_style_guide.py` (§4.1).
   `QUICK_REPORT_HARDENING_PREAMBLE` currently has seven importers — `quick_report_api.py`,
   `main.py`, and five scripts under `scripts/` — so v3 introduces its own constant rather than
   mutating the shared one, and production keeps using the existing preamble until a cutover is
   separately proposed. Open: whether the templated path should later adopt v3's uncertainty
   lexicon and banned-phrase list, which are not templated-specific and would benefit it too.
