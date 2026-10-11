# Handover — Scratchpad v2 (hybrid dictation stack, unified view)

**Date:** 2026-10-11 · **Decision:** build v2 on `feat/hybrid-stack` and ship once (Hassan: "build it now and ship it")
**Start here next session:** read this file, then the v1 spec and the mockup canvas, then write the v2 spec (§6 lists what it must settle) → plan → build → ship.

## 1. Where things are

| Thing | Location / state |
|---|---|
| Feature branch | `feat/hybrid-stack`, worktree `.claude/worktrees/hybrid-stack`, 42 commits off `main`, **local only, not pushed** (HEAD `5349574`) |
| v1 spec | `docs/superpowers/specs/2026-10-10-hybrid-dictation-stack-design.md` (grouping engine, schemas, reconciler, pills, gate, rollout) |
| v1 plan | `docs/superpowers/plans/2026-10-10-hybrid-dictation-stack.md` (Tasks 1–20 done; 21–22 = deploy/live testing, not done) |
| Lab (research) | branch `lab/hybrid-dictation-stack`, `backend/src/rapid_reports_ai/scripts/hybrid_stack_lab/` |
| Mockup canvas | https://claude.ai/artifact/APGB67xivazEuDssbJmSNB — frames: By anatomy + chips, chip states, dictated-normals options A/B/C (A chosen). Main frame predates the v2 decisions below (still shows the "Not yet mentioned" block and two chip colours — both rejected). |
| Replay eval | `PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_eval` (fixtures `backend/tests/fixtures/hybrid_stack/`) |

**Built and tested on the branch (v1):** backend package `backend/src/rapid_reports_ai/hybrid_stack/` (schemas + library, units, grouper, Jev conclusion gate + uncued closing check, Jev family choice with "none", reconciler, template regions, derived pills, service, routes `/api/canvas/stack/{schema,group,close,log,families}`), tables `stack_schema_families` + `dictation_stack_logs` (migration `20261010120000`), frontend `frontend/src/lib/hybrid-stack/` + scratchpad wiring + IntelliDictateTab/TemplateForm pills + `/dev/hybrid-stack` + `/stack-families`. Flags: server `RR_HYBRID_STACK` (default on, needs the dictation package), shadow rate `RR_STACK_SHADOW_RATE` (0.25), reviewers `RR_STACK_REVIEWERS`; client opt-out `localStorage rr_hybrid_stack=0`.

**Verification state:** backend suite 3513 pass; frontend 645/646 (the failing `src/routes/page.svelte.spec.js` "should render h1" fails on main too); svelte-check at baseline 1198 errors (pre-existing). Replay eval after fixes: dev 131/133, template 106/109, all grouper calls served by Cerebras; run-to-run spread ≈ ±5 checks.

**Fixes found during the build (keep):**
- Grouper JSON-schema **field order is decoding order** on Cerebras Qwen: `covers` must come before `attach_to`/`parts`, else every reply runs away to `finish_reason: length` and silently falls back to Groq (dropped follow-on links). Pinned by a test; `place()` reports runaways.
- Grouper prompt = the lab's validated text + one decided change (a list spanning ≥2 regions → General with `covers` naming each).
- Every reconciler result is **provisional** (a kept family too) and goes to `/stack-families`.
- Grouped view shows dictated words at once (live tail + interim words); dark-theme colours.

**Hand-read session 2026-10-11 (local):** one real case (sigmoid diverticulitis) grouped correctly; observed over-ticking (`covers` read "solid organs" as including gallbladder and kidneys; Jev shadow pills did not); "normal apart from X" hid a finding in General; IntelliPrompts do not show in the grouped view (their margin anchors to the hidden editor).

**Local dev setup that works:** backend from the worktree, `RR_DICTATION_V2=1 RR_STACK_REVIEWERS=hassan.ahmad.ucl@gmail.com PYTHONPATH=src .venv/bin/python -m uvicorn rapid_reports_ai.main:app --host :: --port 8000` (bind IPv6: the browser reaches `localhost` over ::1). Frontend from the worktree on **port 4173** (in the backend's CORS list; 5175 is not): `PUBLIC_ENABLE_DEV_ROUTES=true npx vite dev --port 4173 --strictPort`. The worktree needs its **own** `node_modules` (`bun install --frozen-lockfile`): a symlinked one is outside Vite's serving allow-list, so the page loads without JS and forms submit natively. Local login: `hassan.ahmad.ucl@gmail.com` (local password).

## 2. The product intent

The scratchpad captures the radiologist's raw thinking in a clean, structured way with a few high-impact insights. **It is a smart formatter, not a clinical decision tool:** every clinical statement in the final report is either dictated by the radiologist or explicitly confirmed by them in the scratchpad before Generate. The AI groups, suggests and drafts; the radiologist decides; the generator only formats and phrases.

(Regulatory framing is Hassan's product positioning; it is not legal advice and should be checked with a regulatory adviser before it is relied on externally.)

## 3. Decision framework (how we decide things in this feature)

1. **The words never change.** Models return labels; code assembles. The verbatim scratchpad text is the only text; every view is derived from it; every edit edits it.
2. **One reasoning call owns each judgement.** The grouper (Qwen) owns placement; it gains fields rather than new calls where the judgement is about the same sentence.
3. **Jev for yes/no on stated text and pick-from-a-short-list** (conclusion boundary, family choice, command type, "is this chip already stated?"). Validate each new Jev question on a labelled fixture before trusting it (the conclusion gate: 63/65 on 65 sentences).
4. **Code enforces invariants only**, never meaning (no hand-grown regex for clinical judgement; a tiny structural backstop is fine).
5. **Non-blocking and sparse.** Suggestions never stop dictation; anything captured animates away; nothing lingers greyed out.
6. **Fail open.** If a model call fails, the verbatim text stays on screen and the next settle retries.
7. **Measure before trusting.** Blind held-out sets and blind gold labels for anything tuned on seen cases; the lab sets and the replay eval are the regression gate.
8. **Rollout:** ship the new behaviour active by default, keep the old path in shadow behind a kill switch, retire after live testing (memory: rollout active-with-shadow).
9. **Prompts stay case-agnostic** (structural rules, no single-domain examples). Request **Title Case** from Qwen for names and uppercase in code.

## 4. v2 decisions (agreed 2026-10-11)

### Layout (one unified view)
- **No "As dictated" tab.** One view; the tab is hidden (the grouping preserves fidelity, so it adds nothing).
- **Top: live strip** — the words being spoken (interim) and finished sentences not yet placed. When the grouper places a sentence it **animates down** into its region (or lifts its region out of the tray).
- **Middle: scratchpad** — only **abnormal regions**, each with its sentences in dictated order (follow-ons nested), structure labels muted, and its check chips underneath.
- **Assumed-normal tray** (compact pills/boxes) — every region starts here. It replaces the pill strip and the "not yet mentioned" idea (both dropped; no "+ Normal" buttons — the generator fills normals).
  - **Abnormal finding dictated in a region → the region animates up** into the scratchpad.
  - **Dictated normal** ("The kidneys are normal") → the region **stays in the tray**, its pill turns **solid** ("dictated normal"); hover shows the radiologist's words (which are what the report uses). Untouched regions stay **dashed** ("assumed normal").
  - **Mixed region** (abnormal + normal in the same region) → moves up **whole**: the abnormal finding plus an explicit sentence naming what in that region is normal ("Small 8 mm liver cyst. The remainder of the liver is unremarkable.").
- **Bottom: conclusion**, always visible (see below), and the gate.
- **IntelliPrompts are replaced by check chips** in this view (their margin anchors to the hidden editor anyway).

### Check chips ("smart suggestions")
- One uniform style — no colour coding by kind (complication vs negative vs descriptor is not a distinction the user needs).
- Only under **abnormal regions**; **≤ 3 per region, ≤ 6 on screen**, most relevant first, the next ones slide in as chips clear.
- **Source:** the existing finding-linked negatives selection (L-45), run live when a region first rises or its finding changes.
- **Captured → animates out and disappears**, either by **click** (adds the sentence to the dictation, so it counts as dictated) or by **dictation** (a Jev yes/no per visible chip after each new sentence: "does the dictation now state this?"). No inactive/greyed states.
- Non-blocking: they never gate anything.

### Conclusion and the gate
- **Dictated conclusion → used verbatim.** The AI may offer at most 1–2 chips under it for something missing (same chip rules).
- **No dictated conclusion → an "AI draft" appears once, when dictation stops** (same moment as the closing check). Editable in place and by voice. Style = our impression style (brief, synthesised, high-yield, one-line recommendation if warranted).
- If findings change after the draft exists: the gate re-arms and the draft shows "findings changed — refresh?" (it never rewrites itself).
- **Gate = one Confirm** at the bottom covering **the conclusion + the list of assumed-normal regions**. Generate stays disabled until confirmed. **Re-arms** on any change (new sentence, edited conclusion, region leaving the tray). The confirmation is **logged** (what exactly was confirmed). **No voice confirm** — a deliberate click only.

### Editing — inline, by keyboard or voice
- Lines are **editable in place** (typing).
- **Cursor semantics drive dictation:** click (caret) → the next utterance **inserts** at the caret; highlight → it **replaces** the selection; highlight then delete → caret again → **insert**. The frontend carries this signal and shows a clear "listening to edit" state.
- **Jev command classifier as the first call** for every final (one more question in the existing `utterance_bundle` Jev call, no extra latency), choosing from: **dictate** (default), **correct** ("actually, make that 9 mm" — the lean polish already applies it), **delete** ("scratch that", "delete the liver line"), **send to region** ("for the liver, …" — pins what follows; Jev picks the region from the now-distinct region list), **accept suggestion** ("accept free gas"). **Not included:** "confirm conclusion".

## 5. What carries over from v1 unchanged
Grouper (+ the new `abnormal` judgement), schemas/families/reconciler (+ provisional review), template regions from grammar sheets, the Jev conclusion gate and closing check, derived `covers`, the shadow logging table and kill switches, the replay eval and fixtures.

## 6. Open questions the v2 spec must settle
1. **Abnormal flag:** add `abnormal: bool` to the grouper's `Placement` (field order: keep `covers` before `attach_to`/`parts`; re-run the runaway check). Definition, and a labelled fixture to validate it (e.g. from the dev/held-out replay sets).
2. **Generator contract under "formatter":** the generator must state only (a) scratchpad sentences, (b) accepted chips, (c) normals for the confirmed assumed-normal regions (from the template's normals / skill sheet), (d) the confirmed conclusion — and nothing else. Today it also adds pertinent negatives from the brief (L-45/L-59): decide whether those now only enter via accepted chips. This touches the quick and template generation paths and the post-gen check.
3. **Live chip service:** L-45 runs inside generation; v2 needs a live endpoint (latency, caching per region+finding, Cerebras load).
4. **Jev questions to validate on fixtures before trusting:** command type (+ target region for "send to region"); "is this chip already stated?". Thresholds from the labs.
5. **Caret/selection-aware writing** in the v2 write path: fast-append and `polish_span` currently write at the open line; they need an arbitrary target range (insert at caret, replace selection), with the fidelity guard intact.
6. **Conclusion draft:** model, prompt (reuse the impression-plan style), when "dictation stops" fires, refresh behaviour, how a dictated conclusion plus chips is handled.
7. **Gate record:** schema (conclusion text, assumed-normal list, timestamp, report id), where it lives (`dictation_stack_logs` or the report), and how Generate consumes it.
8. **Animations:** Svelte `crossfade`/`flip` for sentence-to-region and tray-to-scratchpad moves; reduced-motion fallback.
9. **Retirements in this release vs later:** the As-dictated tab (hidden), IntelliPrompts in stack mode, the pill strip (replaced by the tray), `/sections` + Jev coverage (still shadow until live testing).
10. **Over-ticking of `covers`** seen in the hand read ("solid organs" → gallbladder, kidneys): tighten the collective rule or accept; matters more now that the tray shows normal regions.

## 7. Next steps (in order)
1. Write the v2 spec from §4 + answers to §6 → `docs/superpowers/specs/2026-10-11-scratchpad-v2-design.md`; Hassan reviews.
2. Labs (small, blind where tuned): abnormal flag; Jev command classifier; chip-already-stated question; conclusion draft quality (hand read).
3. Plan → build on `feat/hybrid-stack` (inline execution worked; subagent dispatch was blocked by the auto-mode classifier in this session).
4. Ship: full suites + replay eval gate; push branch, PR to `main` (merge on Hassan's go-ahead); Railway `RR_STACK_REVIEWERS`; check Cerebras rate limits (grouper + chips + draft + shadow); prod smoke via Chrome; live-testing gates (pill agreement, manual moves, polish latency from `[canvas.polish_span]`, provisional families).
