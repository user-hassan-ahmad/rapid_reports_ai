# Hybrid dictation stack: one tab, the radiologist's words, grouped

**Date:** 2026-10-10 · **Status:** design agreed, plan not written · **Path:** quick and template
**Lab:** branch `lab/hybrid-dictation-stack`, `backend/src/rapid_reports_ai/scripts/hybrid_stack_lab/` (commits eee940f … a3703e8)

## 1. Problem

The scratchpad has two tabs that show the same dictation two ways:

| Tab | Words | Layout | Cost |
|---|---|---|---|
| Verbatim (Clean) | the radiologist's sentences, tidied | dictated order | — |
| Structured | rewritten into terse notes, descriptors merged | grouped by anatomy | a second derived copy; hand edits there are overwritten when the dictation changes (`structuredView.ts`) |

What radiologists value in Structured is the **grouping**. What costs fidelity is the **rewriting**. They are bundled only because one model call does both (`CANVAS_PROCESS_SYSTEM_PROMPT`).

The group vocabulary has its own problem. The checklist pills and the structured groups come from `/sections` (Qwen, reasoning off), which in the lab:
- changed between runs for the same scan type;
- listed prostate and seminal vesicles for 5–8 of 20 scans where sex was not stated;
- pulled groups from the clinical history ("LEFT NECK MASS");
- rarely gave spine levels;
- with reasoning on, corrupted uppercase names ("MEDIASTINUM" → "MEDIUMIUM" in 11/12 lists; Title Case 0/12).

Coverage pills then need a second call per update (`section_coverage.py`, one Jev noul per section).

## 2. Rule

**Scope: the dictation machinery is preserved.** Audio capture, Deepgram streaming, two-pass ASR, the v2 write path (fast-append, lean span polish, Jev band router) and the verbatim scratchpad text are unchanged. This design adds an intelligent grouping layer on top of that text and a view that shows it.

**The words never change; only labels are decided.**

- One text: the verbatim scratchpad, as v2 writes it today. Nothing in this design rewrites it.
- One reasoning call owns each placement: the grouper (Qwen) returns labels only — a group, a link, an exact split, the regions a sentence speaks for.
- Jev verifies the one boundary that is a yes/no judgement about stated text: is a sentence after the conclusion part of it.
- Code enforces invariants only (the view rebuilds the text exactly; splits are exact substrings; links point backwards). Code makes no judgement about meaning.

## 3. Design

### 3.1 The view

One tab replaces Verbatim and Structured, with a sort toggle: **By anatomy** (default) / **As dictated**. Same text, two orders, no rebuild.

By anatomy:
- **Technique** first, then the groups in report order, then **General**, then **Conclusion**.
- Within a group, sentences in dictated order. A sentence that continues another ("It measures 11 mm") shows indented under its parent (↳).
- A sentence that is only a heading cue ("Conclusion.") is not shown as a line; the group heading says it (prod `spoken_format.heading_only`).
- Each line may show its structure label (`· left palatine tonsil`), muted.
- A new sentence appears faded under "just dictated" and moves into its group when placed (the optimistic faded-render pattern of `rr_incremental`).
- **Sticky:** a placed sentence never moves unless its text changes. The radiologist can drag a line to another group; that placement is then pinned and never overridden.
- Edits in either order edit the one underlying text. There is no derived copy, so nothing is overwritten.

### 3.2 Flow per Deepgram final

```
final ─► v2 write path (unchanged: fast-append / lean span polish / Jev band router)
      ─► sentence units (code): split at . ? ! + space and at line breaks; decimals whole
      ─► diff (code): unchanged sentence text keeps its id and placement
      ─► grouper (Qwen) for new / edited sentences only
      ─► invariant checks + placement (code)
      ─► conclusion gate (Jev) for new sentences after the conclusion has begun
      ─► view + pills
```

The grouper is off the critical path: the sentence is already on screen as verbatim text.

### 3.3 Where the groups come from

One engine, two sources. Either way the grouper receives an ordered list of regions, each with an **includes** description.

**Quick path — visual schemas.**
- A **region library** (~60 broad regions, each one visual zone) with an includes list per region: e.g. *Peritoneum and mesentery — free fluid, ascites, free gas, collections, omentum, mesentery, peritoneal deposits, pouch of Douglas*; *Pelvic organs — uterus, endometrium, cervix, ovaries, adnexa, prostate, seminal vesicles* (neutral about sex by construction).
- **Families** compose regions in report order: abdomen-pelvis, chest (incl. CTPA), chest-abdomen-pelvis, head, neck, cervical spine, lumbar spine (levels expanded), knee, shoulder, pelvis MR, trauma. Every family ends with **Other findings**.
- **Choosing the family:** Jev choice over the family descriptions plus an explicit **none** option (instant first guess). Confidence alone does not detect a missing family (cardiac MRI → chest at 1.0).
- **Reconciler, once per scan type ever:** Qwen (reasoning medium, plain JSON, Title Case requested, uppercased in code) sees the families and the library. It either keeps a family as-is, or composes one from library regions plus new regions for gaps. Code validates (keys exist, names unique, ≤ 8 new regions, no Technique/General/Conclusion/Other/Incidental duplicates) and caches it by normalised scan type. Generated families are provisional until approved into the library.
- Until the reconciler result exists, the Jev choice (or a generic head / neck / chest / abdomen / pelvis / spine / limbs family) is used; sentences placed under it are re-placed once when the cached family arrives.

**Template path — the radiologist's own structure.**
- When the template has a fresh grammar structure (`template_sheet_structure`, source "grammar"): regions = the findings-role paragraphs in template order; includes = each paragraph's `COVERS`. Deterministic, cached by `sheet_hash`, refreshed on template edit. No reconciler.
- Sections with role technique / comparison feed **Technique**; role impression feeds **Conclusion**. **Other findings** is added when the template has none.
- A template without a fresh grammar structure (raw path) uses the quick-path schema for its scan type until the sheet is parsed.

### 3.4 Grouper contract

- **Model:** Cerebras `qwen-3.8-27b`, reasoning off, temperature 0; Groq `qwen/qwen3.8-27b` fallback. A direct call with a strict JSON schema: pydantic-ai tool output failed on this nested schema with Qwen. A warm keep-alive client.
- **Input:** scan type; the ordered regions with includes; the sentences already placed with their groups (fixed context); the new sentences with ids.
- **Output per new sentence:**
  - `group` — one region, or Technique / General / Conclusion / Other findings;
  - `structure` — the specific structure, a few words;
  - `attach_to` — id of an earlier sentence this one continues (refers back, or adds an attribute of the same observation, or is a verb-less fragment completing the previous sentence), else null;
  - `parts` — only for independent clauses about different regions run together (including a missing full stop); exact contiguous pieces that together cover the whole sentence;
  - `covers` — the regions the sentence makes a definitive claim about (§3.6).
- **Placement rules (prompt, structural, no clinical examples):** one home — where the abnormality is, not what it touches; interpretation of one finding stays with it; once the conclusion has begun, following sentences stay in it until the radiologist returns to describing the images; Technique = protocol, sequences, contrast, quality, which priors were compared; a comparison about one finding stays with that finding; General = sweeping statements naming no structure, **and a list of structures sharing one predicate that spans two or more regions** (with `covers` listing each); never split a single observation or a shared predicate.
- **Latency (lab):** p50 0.4–0.8 s per update including network; ~0.07 s compute.

### 3.5 Invariants (code)

- The sentence units joined rebuild the scratchpad text exactly.
- Split parts are exact substrings, in order, covering the whole sentence with only whitespace between them; otherwise the split is rejected and the sentence stays whole.
- `attach_to` points to an earlier id; an attached sentence takes its parent's group.
- An unknown group or a missing placement goes to General and is logged.
- `covers` names must be regions of the current list (never Technique / General / Conclusion).

### 3.6 Conclusion gate (Jev)

For each new sentence after a Conclusion sentence exists (cue-only sentences excepted), one Jev choice:
- **summary** — summarises, restates or interprets findings already given; diagnosis, differential, staging, response; recommendation or communication note;
- **images** — returns to describing the images with something not already given.

At confidence ≥ 0.6 Jev decides (summary → Conclusion; images → leaves Conclusion); below, the grouper's placement stands. On a fixture of 65 labelled sentences: 63/65, late findings 23/23, both misses < 0.6. It replaced a code rule that buried a finding dictated after a mid-read summary.

### 3.7 Pills derived from the grouping

- A region's pill is ticked when any sentence lists it in `covers`. The `covers` rule copies prod's coverage criteria (`COVERAGE_CRITERIA`): direct claims (subject, location, modifier) or a definitive claim over a recognisable group the region belongs to; not bare mentions, not a structure only touched by a finding about another, not vague fillers ("no other abnormality").
- **Other findings** never has a pill (Jev ticked it whenever any incidental was mentioned).
- Lab: derived pills agree with prod's Jev coverage on 96% of region decisions (215/223 dev, 113/118 held-out); in the disagreements derived was right about as often as Jev.
- This retires `/sections` for dictation and the per-update Jev coverage call, after the shadow comparison in §5.

## 4. What moves to shadow, then is archived

Nothing is deleted at launch. The old grouping and pill machinery keeps running in shadow — not shown, logged for comparison, and the instant fallback — until live testing says it can be retired or archived.

| Today | Active at launch | Old path after launch |
|---|---|---|
| Structured tab (`CANVAS_PROCESS_SYSTEM_PROMPT` structured mode, `structuredView.ts`) | the one grouped view | shadow: still built in the background for comparison; reachable via the kill switch |
| `/sections` checklist (quick) | schema library + reconciler | shadow: still called; its list logged beside the schema |
| `/sections-from-template` (grammar templates) | the sheet's paragraphs | shadow, as above |
| Jev coverage call per update | pills from `covers` | shadow: still called; its pills logged beside the derived pills |

Retire or archive each row once the live comparison supports it (§5). Unchanged and outside this design: the dictation machinery (§2) and IntelliPrompts.

## 5. Rollout

- **Phase 0 — build, dark.** `/canvas/group` (grouper + invariants + conclusion gate), `/canvas/schema` (family choice, reconciler, cache, template regions). Schema library and families as data. Unit tests on the invariants; the lab's fixtures become regression tests (dev 20, held-out 12, template 14, conclusion boundary 65). Dev route behind `requireDevRoute` from the first commit for a hand read before deploy.
- **Phase 1 — deploy with the new layout active.** The grouped view and derived pills are the default for everyone on the dictation package. The old Structured build, `/sections` and Jev pills run in shadow (§4). Switches: server kill switch `RR_HYBRID_STACK=0` restores the old tabs and pills for everyone; per-user opt-out `localStorage rr_hybrid_stack=0`, as for v2.
- **Phase 2 — live testing.** Log per session: placements and manual moves (a drag is a correction signal), derived-vs-Jev pill disagreements, derived schema vs `/sections` list, grouper and gate latency, reconciler outputs awaiting approval. Peer-read a sample of sessions. Gate for retirement: pill agreement holds on real dictation, manual moves are rare, no fidelity or latency regressions.
- **Phase 3 — retire or archive.** Per §4 row, once its gate is met: stop the shadow call, then archive the code path (structured prompt mode, `structuredView.ts`, `/sections` dictation use, coverage call).

## 6. Evidence (lab, synthetic TTS dictation → Deepgram → v2-like write path)

| Test | Result |
|---|---|
| Dev, 20 CT/MR cases, fixed schema | 133/139; all 6 misses ASR-lost check phrases; live-vs-fresh 4/225 |
| Held-out: 12 cases written blind, gold blind, exact-region scoring | 97/108 (97/100 scorable); family 12/12 |
| Template mode: 4 blind templates (fine, coarse, by level, by compartment) + real CMR sheet, 14 cases, blind gold | 104/122 (104/109 scorable); CMR 9/9 |
| Conclusion gate | 63/65 |
| Pills derived vs Jev | 96% agreement |
| Reconciler, 48 scan types | 22/24 common kept their family; specialist examinations got specific schemas |
| `/sections` as vocabulary (before the schema) | 120–122/139 with run-to-run variation; see §1 |
| Fidelity | the view rebuilt the text exactly in every case, by construction |

Caveats: synthetic speech and synthetic cases; the dev schema's includes were written after seeing dev failures (hence the held-out set); only one real grammar template exists locally; reconciled schemas were checked by hand only.

## 7. Open questions and risks

1. **Lost full stop between utterances.** A final without terminal punctuation runs into the next ("Small Baker's cyst Displaced medial meniscal…"). Either the write path closes a sentence at a final boundary, or the grouper splits it (the prompt allows it; it did not always).
2. **Fragment splits.** The grouper occasionally splits one observation ("… disc osteophyte complex | with moderate foraminal narrowing"). Candidate: a Jev yes/no "does this part read as a complete statement" on split parts only.
3. **Uncued closing line** ("Segment 8 observation is LI-RADS 5, consistent with HCC" at the end, no cue): finding or conclusion? Needs a policy decision.
4. **Reconciler governance:** who approves generated families into the library, and how a provisional family is shown.
5. **Template paragraphs to body regions** (for a future visual map): one cached mapping per template version; not needed for grouping.
6. **Prod templates in grammar form** are few today; the template path falls back to the quick schema until sheets are parsed.
7. **Latency under load:** the grouper p50 rose to ~2 s with 10 concurrent sessions in the lab (Cerebras queueing); measure in Phase 2.
8. **Two-pass clip lead-in:** prod's guard stops a dropped "no" flipping a finding; a minimum 0.5 s lead-in per clip would improve second-pass accuracy on fast speech (separate change).

## 8. Out of scope

- The visual body map (the schema regions are designed to be its zones).
- Generation consuming the grouped sentences (template filling from routed sentences) — a follow-on once the new layout is live (Phase 1).
- Impression-first dictation / reverse generation.
