# Scratchpad v2: one view, assumed-normal tray, check chips, conclusion gate, voice edits

**Date:** 2026-10-11 · **Status:** design agreed (handover §4), open questions settled here · **Path:** quick and template
**Builds on:** `2026-10-10-hybrid-dictation-stack-design.md` (v1: grouper, schemas, reconciler, conclusion gate, derived pills). Everything in v1 §2–§3 still holds unless this spec says otherwise.
**Handover:** `docs/superpowers/handover/2026-10-11-scratchpad-v2-handover.md` (decision framework §3, agreed decisions §4).

> **Revision 2026-10-11 (after Hassan's review, supersedes the sections it names):**
> - **§4 Chips are assumed statements.** An untouched chip carries no information, so chips work like the tray: an *included* chip is in the report unless removed (×) and is listed at the gate; an *optional* chip (the dictation hedges or half-covers it) is opt-in (+). Jev asks "already stated?" and "contradicted?" in one call: gone at stated ≥ 0.8 or contradicted ≥ 0.7; optional at either ≥ 0.3; included otherwise (lab: contradicted 4/4 at 0.7 with no others; 1/10 weaker chips still included, visible at the gate). Chips are re-checked against each new dictation, so a chip the radiologist later contradicts leaves. If the check fails, chips are optional (never included unchecked). Accepting no longer writes into the dictation; included chips reach Generate in the findings block ("Confirmed by the radiologist (not dictated): …" on their region's line).
> - **§6 Brief negatives in v2 sessions.** Generate gets `stack: true` and `stack_declined`. The quick brief offers (never states) a finding-linked negative it would have stated and an implicated sheet negative; removed chips are `DO NOT ASSERT` and never offered. The production template path (`template_lean`) never states negatives of its own already; removed chips are not offered there. Generator prompts unchanged.
> - **§5 Confirm needs a conclusion.** With none (dictation not stopped, or the draft failed), the conclusion field asks "Type or dictate a conclusion" with a "Draft one" button; Confirm stays disabled until a conclusion exists (source: dictated / draft / draft_edited / typed). A failed draft never blocks: the radiologist types one.
> - **§7.2 Edits.** A final while a line or the draft is open goes into that field at the caret (or over the selection), as typing does, and the line is written back on Enter/blur — no live caret mapping onto shifting verbatim offsets.
> - **Next (separate spec):** chips from the sheet's If-present lists; replay findings-block + slim structuring sheet vs today's analyser + brief; if it holds, shrink the analyser to a cached structuring sheet plus the chip knowledge step and retire the brief's negatives stage for v2.

## 1. Intent

The scratchpad is a **smart formatter, not a clinical decision tool**. Every clinical statement in the report is dictated by the radiologist or explicitly confirmed by them in the scratchpad before Generate. The AI groups, suggests and drafts; the radiologist decides; the generator formats and phrases.

(Product positioning, not legal advice; to be checked with a regulatory adviser before it is relied on externally.)

## 2. The view

One view replaces the v1 "By anatomy / As dictated" toggle (the As-dictated order is gone from the UI; the hidden CodeMirror editor still holds the verbatim text, which remains the only text).

Top to bottom:

1. **Live strip.** Interim words (ghost) and finished sentences the grouper has not placed yet (v1 `liveTail` + unplaced units). When a sentence is placed it animates out of the strip into its region (or its region animates up out of the tray).
2. **Technique** line(s), muted, when dictated.
3. **Scratchpad: abnormal regions only**, in schema order. Each region: its sentences in dictated order, follow-ons nested (↳), structure labels muted, dictated normals of the same region included, then its check chips. **General** shows here only when it holds an abnormal sentence; **Other findings** shows when it holds any sentence.
   - **Mixed region** (abnormal and normal in one region): the region rises whole. If the radiologist dictated no normal for it, a muted line **"Remainder of {region}: assumed normal"** closes the region; it is part of what the gate confirms (§5) and never dictation text.
4. **Assumed-normal tray**: one compact pill per region not in the scratchpad (the schema's pill regions; never Other findings).
   - **Dashed** = assumed normal (nothing dictated).
   - **Solid** = dictated normal (only normal sentences cover it). Hover shows the radiologist's words.
   - A region leaves the tray (animates up) when an abnormal sentence lands in it, and returns if that sentence is deleted or moved.
5. **Conclusion** (always visible) and the **gate** (§5).

Not in this view: the pill strip (replaced by the tray), "+ Normal" buttons, a "not yet mentioned" block, IntelliPrompts (replaced by chips; §9).

### 2.1 Region state (code, from the units)

A unit's **effective** labels: a split unit contributes each part (part group, part `abnormal`); an attached unit takes its parent's group and its own `abnormal`.

- A region is **abnormal** when any effective unit in it has `abnormal = true`. It sits in the scratchpad.
- Otherwise a region is **dictated normal** when any effective unit lists it in `covers` (this includes General collectives such as "The solid organs are unremarkable").
- Otherwise it is **assumed normal**.
- Pinned (dragged) units keep their region; a drag re-evaluates region state.

## 3. The abnormal judgement (grouper field)

The grouper's `Placement` gains `abnormal: bool`, and `Part` gains `abnormal: bool`. Field order (decoding order on Cerebras): `id, group, structure, covers, abnormal, attach_to, parts`; `covers` stays before `attach_to`/`parts`. The runaway check (`finish_reason: length`) is re-run in the lab.

**Definition (prompt, structural):** `abnormal` is true when the sentence (or part) reports something that departs from normal: any finding, lesion, variant worth reporting, post-procedural change, measurement given as abnormal, or a hedged or possible finding ("possible", "cannot exclude", "query"); a statement that something is unchanged or stable is abnormal when what is stable is a finding. It is false for normality statements, absent findings (negatives), technique, comparison wording with no finding, and headings. Conclusion sentences get it too but it does not move regions.

**Asymmetry:** an abnormal sentence flagged false would hide its region in the tray, so recall of abnormal sentences is the gate metric (lab §10).

## 4. Check chips

- One uniform style. Only under abnormal regions; **≤ 3 per region, ≤ 6 on screen**; regions in report order fill the six slots; the next chip slides in as one clears.
- **Source (the L-45 selection, live):** `POST /api/canvas/stack/chips` with the scan type, clinical history, the region and its abnormal sentences, and the whole dictation. One Qwen call (Cerebras `qwen-3.8-27b`, reasoning off, the L-45 fallback instruction `report_reconcile.FALLBACK_SYS` with no prepared finding types, so every finding gets ≤ 3 negatives: absent extension, spread or complication that changes the next step; one finding per negative, final report form, never denying anything dictated). Then one Jev call drops any chip the dictation already states (§4.1).
- **When:** when a region first rises or its set of abnormal sentences changes (after the grouper settles, debounced). Server cache in process, keyed by (scan key, region, normalised abnormal sentences); the client keeps chips per region and only asks again on change.
- **Captured → animates out and disappears**:
  - **click**: the chip's sentence is appended to the dictation (verbatim text, as if dictated), so it counts as dictated and is grouped like any sentence;
  - **dictation**: after each group update that adds sentences, the visible chips are re-asked with the "already stated?" question in the same `/group` request (no extra round trip); stated chips leave.
  - **voice "accept …"**: §7.3.
- No greyed or inactive states; chips never gate anything; a failed call shows no chips (fail open).
- **Conclusion chips** (1–2 under a dictated conclusion) are **deferred** to a follow-on: they need their own source and lab.

### 4.1 "Already stated?" (Jev)

One noul per chip: *"The dictation states this, or states something that makes it redundant (the same structure and finding, at the same or stronger certainty): {chip}"*. Removed at P ≥ threshold from the lab (§10). Also asked once on the fresh chips before they are shown.

## 5. Conclusion and the gate

- **Dictated conclusion** (units in Conclusion): shown as dictated, used as the conclusion.
- **No dictated conclusion:** when dictation stops (the same moment as the v1 closing check: recording stopped + idle), if the closing check leaves no Conclusion, an **AI draft** is requested once: `POST /api/canvas/stack/draft` (Cerebras `qwen-3.8-27b`, reasoning low, plain text, ≤ 4 sentences; style = our impression style: brief, synthesised, high-yield, the clinical question answered, one-line recommendation only if warranted; it may only use the dictated findings). Shown labelled **AI draft**, editable in place by typing and by voice (caret/selection in the draft, §7).
- **Findings change after the draft exists** (any unit added, removed or edited outside Conclusion): the draft shows "Findings changed — refresh?" and the gate re-arms. It never rewrites itself; refresh replaces it (an edited draft asks first).
- **Gate = one Confirm button** at the bottom. It confirms, in one list:
  1. the conclusion (dictated, draft or edited draft);
  2. the **assumed-normal** regions (dashed pills, and "remainder of …" lines);
  3. the **dictated-normal** regions with the words that cover them (collapsed; this closes the over-ticking hole, §11.10).
- **Generate is disabled until confirmed.** The gate **re-arms** on any change: a new or edited sentence, an edited conclusion, a region leaving or entering the tray, a chip accepted. **No voice confirm**: a click only.
- **Gate record** (logged on confirm): `{confirmed_at, conclusion_text, conclusion_source: dictated|draft|draft_edited, assumed_normal: [region], remainder_normal: [region], dictated_normal: [{region, words}], accepted_chips: [text], units_hash}`. Stored as JSON column `gate` on `dictation_stack_logs` (one row per stack session, migration adds `gate` and `report_id`), sent with the session log; the report id is added when Generate returns.

## 6. What Generate receives (the formatter contract)

The generator, its prompts, the brief and the post-generation check are **unchanged**: they already require faithfulness to the dictation ("never fabricate findings", "Output Consistency", "Never deny anything dictated"), and the generator keeps its freedom to phrase, pad and reorder for fluency. Nothing is substituted word for word.

What changes is the **input**: in a stack session the `findings` text sent to Generate (quick `/api/quick-report/generate`, template generate) is the **confirmed findings block**, built in code from the units and the gate record:

```
{Technique sentences}

{Region}: {its dictated sentences, in order}
...
Other findings: …

Confirmed normal (not dictated; confirmed by the radiologist): {assumed-normal regions}; remainder of {mixed region}.

Conclusion (confirmed by the radiologist): {conclusion text}
```

- Sentences are the radiologist's own words (accepted chips are already dictated sentences). Dictated normals stay in their own words under their region (General collectives as a line of their own).
- The "Confirmed normal" line states intent plainly: these regions are normal and may be written as normal, which is today's default-normals behaviour, now explicitly confirmed.
- The conclusion line tells the impression what the radiologist concluded; the generator phrases it in report style.
- Brief-added negatives (finding-linked, implicated) behave as today; the chips are where the radiologist sees and accepts them up front. Revisit after live testing if reports carry negatives the radiologist declined as chips.
- Without the stack (kill switch, opt-out, no schema) Generate gets the verbatim scratchpad exactly as today.

## 7. Editing: inline, by keyboard or voice

### 7.1 Typing
Every scratchpad line (a unit, or a part of a split unit) is editable in place. A commit (Enter, blur) replaces exactly that sentence's (or part's) characters in the verbatim text (offset from `sentenceOffset`, part offset inside it); the editor change re-triggers grouping as any edit does. Deleting all of a line's text removes the sentence.

### 7.2 Cursor semantics (the edit target)
- **Caret** in a line (or the draft) → the next final is **inserted** at the caret.
- **Selection** → the next final **replaces** the selection.
- Highlight then Delete → caret → insert.
- No caret or selection in the view → dictation appends at the end, as today.
- The view shows a clear **"Listening to edit"** state on the target line while a target is set; Escape or a click outside clears it.

**Write path for a targeted final:** written **verbatim** (the bundle's `clean_text`: lexicon, units, fillers, spoken punctuation) at the target; no span polish (the span polish rewrites the open line at the end of the text, the wrong place for an edit, and an edit is explicit intent). Low-confidence words keep the word-sense underline. Spacing and capitalisation at the join are code (as `separatorFor`). The fidelity guard holds trivially: the inserted words are the radiologist's words; the replaced words are the ones they selected.

### 7.3 Voice commands (Jev, in the utterance bundle)
In stack mode the bundle gains one choice question, **command**, asked with every final (same Jev call, no extra latency):

| option | meaning | action |
|---|---|---|
| `dictate` (default) | report content | today's write path (or §7.2 when a target is set) |
| `correct` | revises something just said ("actually, make that 9 mm") | today's polish (the lean polish applies it) |
| `delete` | "scratch that", "delete the liver line" | previous utterance: today's code delete; a named line: the view **selects** the target region's lines and asks for Delete (a model never removes the radiologist's words on its own) |
| ~~`send_to_region`~~ | "for the liver, …" | dropped after the lab (§10.1): the grouper places it |
| `accept_suggestion` | "accept free gas" | the named visible chip is accepted (as a click); the utterance is not written |

Two further choices are added only when needed: **target_region** (options = the session's regions + none) when regions exist, and **target_chip** (options = visible chips + none) when chips are visible. A command acts only at confidence ≥ its lab threshold; otherwise the final is treated as `dictate`. "Confirm conclusion" is not a command.

## 8. Animations
Svelte `crossfade` keyed by unit id between the live strip, regions and the tray pills; `flip` for reordering inside the scratchpad; chips leave with `fade`/`fly`. `prefers-reduced-motion: reduce` → duration 0.

## 9. Retirements in this release

| Item | This release | Later |
|---|---|---|
| As-dictated order toggle | removed from the stack view (verbatim stays the hidden source) | — |
| IntelliPrompts in stack mode | not requested, margin hidden; replaced by chips | retire with the old path |
| Pill strip (IntelliDictateTab / TemplateForm) in stack mode | hidden; the tray replaces it | retire with the old path |
| `/sections`, Jev coverage | shadow, logged (v1 §4) | retire after live testing |
| Old Verbatim/Structured tabs | the kill-switch fallback; Structured built in shadow for a sample (v1) | retire after live testing |

## 10. Labs (before trusting each new judgement)

| Lab | Fixture | Gate |
|---|---|---|
| Abnormal flag | every unit of the dev, held-out and template replay sets, gold `abnormal` labelled from the text before the run | abnormal recall ≥ 98% (no region hidden on the held-out set), precision ≥ 90%; placement checks within the v1 spread (dev ≥ 128/133, template ≥ 103/109); no runaways |
| Command classifier | ~90 finals written blind: dictation (incl. look-alikes: "no free gas", "for completeness the liver…", "delete" as a clinical word), and each command with phrasing variants; gold labels written with the set | per-command threshold where wrong-command actions = 0 on the set; dictate recall ≥ 98% at that threshold |
| Chip "already stated?" | ~60 (dictation, chip) pairs: stated verbatim, paraphrased, stronger, weaker/hedged, different structure, contradicted | threshold with 0 false "stated" on different-structure/weaker pairs; stated recall ≥ 85% |
| Conclusion draft | hand read on the dev cases | no content not in the dictation; impression style |

### 10.1 Lab results (2026-10-11)

- **Abnormal flag** (592 sentences, gold labelled blind before the run; `tests/fixtures/hybrid_stack/abnormal_gold.json`): recall dev 118/121, held-out 98/103, template 96/100; precision 118/118, 98/101, 96/99; one region would be hidden (a measurement with no "enlarged": "main pulmonary artery measures 34 mm"). Below the 98% recall target on held-out; most misses are borderline gold calls. Shipped because a miss changes display only: every dictated sentence still reaches Generate (§6), and a region shown as dictated-normal appears in the gate list with its words (§5). Placements unchanged (dev 131/133, template 106/109 scorable, all Cerebras, no runaways); held-out placement varies with Jev's family choice in the eval path (production asks the reconciler first).
- **Commands** (96 blind finals, `command_fixture.json`): `send_to_region` is **dropped** — Jev reads routed content as dictation (2/13 recognised), and the grouper already places sentences that name their region; the target-region choice (19/19) is kept for named deletes. Shipped rule: `delete` at ≥ 0.6 (a named region only selects its lines for a keyboard Delete; otherwise today's previous-utterance delete); `accept` when Jev names a visible chip and the command is not `dictate`; `correct` is today's path. 90/96 right, 3 harmless (dictated text equal to the chip), 2 accept phrasings missed, 1 paraphrase replaced by the chip's wording. Asked as a parallel Jev call beside the bundle (same latency), not inside it.
- **Already stated?** (64 pairs, `chip_fixture.json`): at 0.8, 0 false "stated", recall 24/30 (below the 85% target; precision chosen: a hedged dictation never removes a chip; a missed one only lingers).

## 11. Open questions settled (handover §6)

1. **Abnormal flag** — §3, lab §10.
2. **Generator contract** — §6: input becomes the confirmed findings block; generator, brief and checks unchanged; fluent phrasing kept (Hassan, 2026-10-11).
3. **Live chip service** — §4: `/stack/chips`, L-45 fallback instruction live, per-region cache, Jev "already stated" filter; Cerebras load is one call per region change (typically 1–4 per report) plus the draft once per report.
4. **Jev questions** — §7.3 command (+ target region / chip) and §4.1 already-stated; thresholds from §10.
5. **Caret/selection writing** — §7.2: targeted finals are written verbatim at the target; the span polish stays for end-of-text dictation.
6. **Conclusion draft** — §5.
7. **Gate record** — §5; Generate consumes it through the findings block (§6).
8. **Animations** — §8.
9. **Retirements** — §9.
10. **Over-ticking of `covers`** — no prompt change (the validated prompt stays); the gate lists dictated-normal regions with their words (§5), so an over-ticked region is still confirmed by the radiologist.

## 12. Rollout
- Active by default wherever the v1 stack is on (dictation package + `RR_HYBRID_STACK` not "0"); per-user opt-out `localStorage rr_hybrid_stack=0`; the kill switch restores the old tabs, pills, IntelliPrompts and verbatim Generate input.
- Logged per session: placements and manual moves, abnormal flags, chips shown / accepted (click, dictation, voice) / never captured, commands and their confidence, draft shown / edited / refreshed, gate confirms and re-arms, latency of grouper, chips, draft.
- Live-testing gates (v1 §5 plus): abnormal regions hidden in the tray (from peer reads) = 0; command misfires rare; chip acceptance rate; no fidelity or latency regressions.

## 13. Out of scope
Conclusion chips; named-line deletion by voice without a keyboard Delete; the visual body map; generation from routed sentences beyond the findings block; impression-first dictation.
