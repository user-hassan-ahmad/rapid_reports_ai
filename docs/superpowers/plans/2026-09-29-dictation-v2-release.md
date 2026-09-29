# Plan — release the dictation package as `rr_dictation_v2` (2026-09-29)

**Decision (user, 2026-09-29):** the lab has found the dictation package. Ship everything that ran in the last sessions, together, behind one production switch, on for the user first. gpt-4o-transcribe stays in (scratchpad content is anonymised findings). Audio capture stays lab-only.

## The package

- **Deepgram:** nova-3-medical, en-GB, numerals, MIP opt-out; dictation mode off; UK spelling (`replace`); spoken formatting; per-case keyterms.
- **Finals:** forced finals (0.9 s gap) with the audio guard; interim ghost text.
- **Decision-first engine:** Jev bundle per final → fast-append / command / delete / polish; the lean polish on Cerebras, raced; held corrections; faded render; one-step undo; outcome tracking.
- **Checks on what is written:** the fidelity check; units mm/cm/ml; the word-sense spotter and fixer.
- **Two-pass:** Deepgram batch + gpt-4o-transcribe, Jev referee (swaps ≥ 0.90, suggestions 0.60–0.90, recovered words, dropped negation/side/number inserts).
- **Around the scratchpad:** Jev coverage pills; the audit (model tier at 0.6 s, new rendering); Verbatim / Structured as two views.

**Safe for everyone now (not behind the switch):** the pills/questions split, audit rendering and `other_quote`, and the Deepgram `numerals` / MIP opt-out / no-`punctuate` settings. The two-view toggle ships after one browser click-through.

**Lab-only:** audio capture, the lab page/panel/export, the review and bake-off scripts.

**Removed:** the Jev boundary front door (`/utterance`), the triage route/debug/shadow modes in `/process`, the Jev tier-2 audit experiment.

## Tasks

1. **Merge `main` into the branch** and resolve the 7 conflicts:
   - `main`'s model table, `normalise_model_settings` and retired-models test win;
   - the lab's `/review` structure is kept, with `main`'s reasoning-off intent;
   - imports are merged;
   - v2 tests are deleted;
   - the lab docs win.

   Then point lab code at live models (the lean polish and IntelliPrompts fallbacks name the retired `qwen/qwen3.6-27b`) and run the full suites.
2. **One switch.**
   - **Frontend:** `rr_dictation_v2` (localStorage, like `rr_discretionary`) turns the normal Quick Reports tab into the package, with the settings the lab ran; the lab page keeps its own config.
   - **Backend:** the package's endpoints and websocket features are enabled *per connection* when the client asks (`v2=1`) and the env allows (`RR_DICTATION_V2=1`, the kill switch); `RR_TRIAGE_DEBUG` still enables the lab.
   - Production without the flag is unchanged.
3. **Prune** the removed experiments and their tests.
4. **Verify:**
   - suites and the type-check baseline;
   - a live replay of a captured session through the switch;
   - the user's smoke test on the normal tab (flag on and off, the toggle).

   Then a PR, and deploy with `RR_DICTATION_V2=1`, the flag on for the user.

## Status (2026-09-29)

- **Task 1 done** (`cac5468`): `main` merged; 840 → 855 backend and 131 frontend tests pass; the type-check baseline is unchanged. Live on `main`'s models: lean polish 458 ms, bundle 457 ms, Jev pills 251 ms, IntelliPrompts 538 ms.
- **Task 2 done** (`9fee762`, `2dcf364`). On a server with only `RR_DICTATION_V2=1`, a normal client gets production dictation unchanged, and a `v2=1` client gets the package (forced finals + guard, two-pass revisions, word confidences). No audio capture either way. Engine calls retry once on a dropped connection.
- **Task 3 deferred to a follow-up PR.** The retired experiments are dormant behind lab-only flags and entangled with shared modules; pruning them inside the release adds risk for no user-facing gain.
- **Task 4:** the user's smoke test on the normal tab, then the PR.
