# Scratchpad v2 — implementation plan

**Spec:** `docs/superpowers/specs/2026-10-11-scratchpad-v2-design.md` · **Branch:** `feat/hybrid-stack` (inline execution) · **Ship:** PR to `main`, merge on Hassan's go-ahead.

Rules for every task: TDD (test first, see it fail, implement, see it pass); match the surrounding code; commit per task; prompts case-agnostic; fail open on every model call.

## Lab outcomes that change the spec (recorded in spec §10 at the end)
- **Commands** (96 blind finals): ship `delete` (≥ 0.6; with a named region it only *selects* the region's lines; without, today's previous-utterance delete) and `accept_suggestion` (Jev names a visible chip and the command is not `dictate`). `correct` = today's path. **`send_to_region` dropped**: Jev reads routed content as dictation (2/13); the grouper places named regions; target region 19/19 is kept for delete. Result: 90/96 right + 3 harmless (dictated text equals the chip), 2 accept phrasings missed, 1 paraphrase replaced by the chip wording.
- **Chip "already stated?"** (64 pairs): threshold 0.8 → 0 false "stated", recall 24/30. Precision first.
- **Commands are a parallel Jev call** in `/api/canvas/bundle` (same latency as the bundle, the validated wording and state form unchanged), not extra questions inside the bundle.

## Backend

### B1 Abnormal flag (done in lab commit)
`Placement.abnormal`, `Part.abnormal`, `StackUnit.abnormal`, `PartOut.abnormal`; prompt bullet after `covers`; field order pinned; eval scores it against `tests/fixtures/hybrid_stack/abnormal_gold.json`; grouper logs every endpoint failure.

### B2 `jev_stack` (done in lab commit) + tests
`hybrid_stack/jev_stack.py`: `ask_command`, `ask_stated`, question builders, `parse_command`; thresholds `COMMAND_DELETE_MIN = 0.6`, `STATED_MIN = 0.8`; `decide_command(parsed) -> {"action": "dictate"|"delete"|"accept", "region", "chip"}`. Tests with `httpx.MockTransport`: parse, decide rules (each lab rule), payload shape.

### B3 Chips endpoint
`hybrid_stack/chips.py`: `suggest(scan_type, history, region, sentences, dictation) -> list[str]`: `report_reconcile._fallback(state, items=sentences, keys=[])`, flatten negatives in order, dedupe (case/space-insensitive, `duplicates_negative` against the dictation's negated clauses), then `ask_stated` drops P ≥ 0.8; keep ≤ 3. In-process LRU (256) keyed by (scan key, region, normalised sentences). Fail open → `[]`. Route `POST /api/canvas/stack/chips` `{scan_type, clinical_history, region, sentences, dictation}` → `{chips, cached, ms, error}`. Tests: flatten/dedupe/cap, stated filter, cache hit, failure → [].

### B4 `/group` re-asks visible chips
`GroupRequest.chips: list[str] = []`; when there are new sentences and chips, `ask_stated(text, chips)` runs concurrently with the gate; `GroupResult.chips_stated: list[str]` (P ≥ 0.8). Fail open → []. Tests.

### B5 Conclusion draft
`hybrid_stack/draft.py`: `draft_conclusion(scan_type, history, findings_text) -> str` Cerebras Qwen (reasoning low, temperature 0.2, plain text, ≤ 4 sentences, impression style: brief, synthesised, answers the clinical question, recommendation one line only if warranted, only dictated findings, no list of absent findings). Route `POST /api/canvas/stack/draft` → `{text, ms, error}`. Tests: prompt contents, empty/failed → error, strips quotes/headings.

### B6 Command in the bundle
`BundleRequest.stack_regions: list[str] = []`, `stack_chips: list[str] = []`. When `stack_regions` is non-empty, `/bundle` runs `ask_command(active+open_line, utterance, regions, chips)` concurrently with the bundle (and only when `code_route` is None); `BundleRouteResponse.stack_command: dict | None` = `decide_command(...)` plus confidence. Fail open → None. Logged (numbers and the action only). Tests.

### B7 Gate in the log
Migration: `dictation_stack_logs.gate` (JSON, nullable), `report_id` (string, nullable). `LogRequest.gate`, `report_id`. Tests (route round trip).

## Frontend (`frontend/src/lib/hybrid-stack/`)

### F1 Types + region state (pure)
`types.ts`: `abnormal` on unit and part; `Chip`, `GateRecord`. `regionState.ts`: `effectiveUnits(units)`, `regionStates(units, pillRegions) -> {abnormal: string[], dictatedNormal: Map<region, string[] words>, assumedNormal: string[], mixedNeedsRemainder: string[]}` per spec §2.1 (parts and attached units handled). Vitest.

### F2 Findings block (pure)
`findingsBlock.ts`: `buildFindingsBlock(units, groups, gate) -> string` per spec §6 (Technique, regions in schema order with their sentences, General lines, Other findings, "Confirmed normal …" line, "Conclusion (confirmed by the radiologist): …"). Vitest with parts, attached, headings hidden, no conclusion.

### F3 Chip state (pure + api)
`chips.ts`: `visibleChips(byRegion, abnormalRegions, max=6, perRegion=3)`, `removeChip`, `regionKey(sentences)`. `api.ts`: `postChips`, `postDraft`; `postGroup` gains `chips`. Vitest.

### F4 The v2 view
Rewrite `HybridStackView.svelte`: live strip (ghost + pending + unplaced) at top; Technique; abnormal regions (rows editable, nested follow-ons, structure muted, "Remainder of X: assumed normal" line, chips under each); tray (dashed / solid pills; hover = words); conclusion block (dictated / AI draft / "Findings changed — refresh?"); gate (list + Confirm). Svelte `crossfade` keyed by unit id between strip/regions, `flip` in regions, chips `fade`; reduced motion → 0 ms. Props/callbacks: `onSelect`, `onMove`, `onEditLine(id, partIndex|null, text)`, `onTarget(target|null)`, `onChipAccept(chip)`, `onDraftRefresh`, `onDraftEdit(text)`, `onConfirm()`. Component tests (testing-library): tray vs scratchpad placement, chip click, gate disabled/enabled.

### F5 Scratchpad wiring (`DictationScratchpad.svelte`)
- Remove the order toggle in stack mode; always the v2 view.
- Chips: after each group result, for each abnormal region whose abnormal sentence key changed → `postChips` (debounced 400 ms), store per region; pass visible chips in `postGroup`; drop `chips_stated`.
- Chip accept (click or voice): append the chip sentence to the verbatim text (as a dictated sentence, one separator) → regrouped.
- Draft: in `scheduleClose`, after the closing check, if no Conclusion unit → `postDraft(findings block without conclusion)`; store `{text, unitsHash, edited}`; findings change → stale flag.
- Gate: state `{confirmed: GateRecord|null}`; any change of units hash / conclusion / tray / chip accepted → `confirmed = null`; Confirm builds the record, `postLog` with `gate`; `onGateChange(confirmed, findingsBlock)` to the parent.
- IntelliPrompts: not requested, margin hidden in stack mode.

### F6 Inline edit + edit target
- `onEditLine`: replace that sentence's / part's characters in the editor (offset via `sentenceOffset` + part offset); empty → remove the sentence and one separator.
- Edit target: `{kind: 'caret'|'selection', from, to}` in verbatim offsets (or `{kind:'draft', ...}`); shown "Listening to edit"; Escape/outside click clears.
- `handleFinalTranscript` with a target: no faded pending at the end; ask the bundle (for `clean_text`, command, word-sense flags) and write `clean_text` at the target (replace selection / insert at caret, join spacing via `separatorFor` rules), underline flags; target moves to the end of the inserted text (caret). Draft target: insert into the draft text.

### F7 Voice commands
`askBundle` sends `stack_regions` (schema groups' region names) and `stack_chips` (visible). In `decideUtterance`, before routing: `stack_command.action === 'accept'` → accept that chip, drop the faded words; `'delete'` with region → drop the faded words and set the edit target to a selection over that region's lines (the view highlights, Delete key removes via F6); `'delete'` without region → the existing delete route.

### F8 Parents
`IntelliDictateTab.svelte`, `TemplateForm.svelte`: in stack mode hide the pill strip; `onGateChange` → `stackGate`; Generate disabled until `stackGate.confirmed`; Generate sends the findings block instead of the scratchpad text; after Generate returns a report id → `postLog` with `report_id`. Without the stack: unchanged.

## Verify and ship
1. Backend suite, frontend vitest, svelte-check at baseline; replay eval (dev ≥ 128/133 scorable, template ≥ 103/109 scorable; abnormal recall ≥ 98%; no runaways in the log).
2. Local hand read in Chrome (backend :8000, frontend :4173): one quick case end to end (chips, tray, draft, gate, edit by caret/selection, accept by voice-injected text, Generate with the findings block).
3. Independent review (code-reviewer agent) before the PR; fix findings.
4. Push `feat/hybrid-stack`, PR to `main`; merge only on Hassan's go-ahead; then Railway `RR_STACK_REVIEWERS`, Cerebras rate-limit check, prod smoke.
