# Guideline library: handover (2026-10-13)

Start here. The next session executes the **draft-card redesign** plan.

## Mission
The guideline library is a curated, offline library of the guidelines UK radiologists use, built for the Scratchpad Copilot.
- **Packs:** each is hand-authored from the primary source. It holds inputs, data-only logic and outcomes, and every fact has a locator.
- **Engine:** a deterministic engine evaluates the packs.
- **Model:** it only reads values from the dictation.
- **Safety standard (from 2026-10-13):** nothing reaches the report unseen.

The card is a quick, source-based fact check. It works in this order:
1. A visible draft, in which each value is read, pre-filled or asked, and can be edited inline, including none or n/a.
2. **Calculate**, which runs the engine on the confirmed values and returns a cited classification or recommendation.
3. **Apply**, which writes that result into the report.

## Where things are
| What | Where |
|---|---|
| Worktree and branch | `.claude/worktrees/scratchpad-copilot`, `feat/scratchpad-copilot`. Local only; never push. Merging needs Hassan's go-ahead. |
| Spec (the authority) | `docs/superpowers/specs/2026-10-12-guideline-library-design.md`. §7 was rewritten for the draft card. |
| **Next plan** | `docs/superpowers/plans/2026-10-13-guideline-draft-card.md` |
| Previous plan (done) | `docs/superpowers/plans/2026-10-13-guideline-library-next-slice.md` |
| Ledger: every ruling and decision | `.superpowers/sdd/2026-10-13-guideline-library-next-slice/progress.md` |
| Root-cause review behind the redesign | `.superpowers/sdd/2026-10-13-guideline-library-next-slice/settling-root-cause-review.md` |
| Visual plan for Hassan | https://claude.ai/artifact/7Kon9t3GwqNcSszmdBfT9o (local copy: `.superpowers/sources-archive/copilot-card-redesign.html`) |
| Lab results | `docs/superpowers/handover/2026-10-12-copilot-evidence/preview_lab_next_slice.md` |
| Currency check of every system | `.superpowers/sdd/2026-10-13-guideline-library-next-slice/currency-check.md` |
| Pack-authoring skill | `.claude/skills/guideline-pack/`: SKILL, AUTHORING-RULES, TRAPS, SOURCES. Gitignored, so it isn't versioned. |
| Source PDFs | `guidelines/<id>/sources/`, gitignored; each manifest holds the sha256. Raw downloads: `.superpowers/sources-archive/`, also gitignored. |
| Private backup (sources, ledgers, skill) | https://github.com/user-hassan-ahmad/rr-guideline-library-private (local `~/Code/rr-guideline-library-private`). To restore a pack's sources, copy `pack-sources/<id>/` into `guidelines/<id>/sources/`. |
| Committed bundle | `backend/src/rapid_reports_ai/resources/guideline_bundle.json`, 21 entries. A drift test guards it. |

Run commands from `backend/` as `PYTHONPATH=src .venv/bin/python …` or `.venv/bin/pytest`. Check one pack with `scripts/guidelines/check_pack.py <id>`. Rebuild with `scripts/guidelines/build_bundle.py`; `--check` reports drift.

## State
- **Code:** tasks 1–6, 8 and 9 of the next slice are done and reviewed. That covers:
  - per-finding settling;
  - eligibility triage, with three card states;
  - the preview cache;
  - reference-only cards;
  - `check_pack`.

  After that came 5 fix rounds on settling plus a lab-fix round. Library and copilot tests pass, about 935.
- **Packs:** there are 21 in the bundle.
  - The original three are Fleischner, BTS and Bosniak, with eligibility added this slice.
  - The 18 new ones are:
    - BTA U-grade (lookup);
    - ESE adrenal 2023;
    - RCOG GTG 62 premenopausal and GTG 34 postmenopausal;
    - PI-RADS v2.1;
    - NHS AAA surveillance (screening programme only);
    - CAD-RADS 2.0 (category plus the I, E and P modifiers);
    - CAC-DRS (category or Agatston; the US management wording sits in the reference section only);
    - SINS (lookup on the dictated total);
    - tier 2 reference cards: Kellgren–Lawrence, Garden, Weber/AO 44, Salter–Harris (prognosis only), Fazekas, ASPECTS, AO Spine, Stoller and Lund–Mackay.

  Every pack had an independent clinical read, and each read's findings were fixed. Outerbridge was dropped from this slice.
- **Preview lab, run 2:** 0 wrong values and 0 wrong proposals. Friction is too high, at a mean of 5.5 asks per card. **Apply is OFF**, and Hassan decides when to enable it, from the real-dictation lab's report. That result prompted the redesign.
- **Ask material cap:** `PACK_MATERIAL_MAX` is 48k. CAD-RADS is at 40.4k.

## Next: execute the draft-card plan
Its tasks, in order:
- (a) Ask parent questions first.
- (b) Build the real-dictation lab before the redesign, as the baseline:
  - production findings come read-only via Metabase and stay in the scratchpad, never committed;
  - the grouper runs offline;
  - an independent Claude Opus 5.5 subagent labels the truth with every pack's sources. The harness writes the cards and a labelling brief, then validates the labels: the schema, every card labelled, and `served_by` recorded. Labels are made once and reused, and the labeller never sees the settler's output. It runs under the Max plan, so there is no API spend;
  - Hassan spot-checks the boundary items.
- (c) Add the read / pre-filled / asked states and Calculate. Retire the per-input QUOTE Jev claim, `_no_prior`, `Q.many`, `_ORGANS` and the negation allowlist. Demote the one-lesion check, `Q.alone`, the modifier guard and the HU phase claim to highlight signals.
- Highlight the reference rows that match the case, using explicit links in the pack data.
- (d) Checker mode, for when the category is dictated.
- (e) "Which lesion?"
- (f) Re-run the lab. It reports, with the baseline beside each figure:
  - wrong "read" values, with each case named;
  - wrong pre-fills per input;
  - taps to Calculate (median and distribution);
  - checker agreement, latency and degraded rows.

  It then recommends whether to turn Apply on, which inputs to demote to "asked", and what to fix next. Then it stops for Hassan's decision. There are no automatic gates: 0 wrong "read" values and a median of 2 taps or fewer are reference targets only. A wrong value during a run is reported, not tuned.
- (g) Spec §12 and the handover.

No Copilot card UI exists on this branch, so the plan covers the backend API contract only.

## Hassan's standing decisions (do not re-ask)
- **Safety:** nothing reaches the report unseen. Chips can be confirmed. Every value can be edited inline, including none or n/a. Calculate, then Apply. This reverses "no chips" and "asked, never wrong".
- **Sources:**
  - only the primary source;
  - legal lookups only (OpenAlex, Europe PMC, Firecrawl), never Sci-Hub;
  - **tell Hassan about any source you can't get**, giving the citation and DOI. He supplies it.
- **Band edges:**
  - explicit wording in the source wins (<, ≤, "more than", "and larger");
  - round half up only when the source says to round;
  - where the figure and the text disagree, follow the figure and list the conflict;
  - combinations the source doesn't define go to an explicit "does not fit" outcome.
- **What reaches the report:**
  - management from a non-UK body never reaches UK report text without a UK source;
  - a fact the radiologist rarely knows, such as symptoms, gets one outcome whose wording is true either way, rather than a question;
  - outcome caveats are never moved into the reference section.
- **Earlier pack verdicts:**
  - F1: Fleischner gets an exclusion input.
  - F6: half-up rounding, but only where Fleischner says to round.
  - T12: the BTS diameter route.
  - T14: the "resolved" route.
  - B7: enhancing contents means the lesion is not cystic.
  - B8: unclassifiable.
  - The Bosniak infection caveat applies to IIF, III and IV, not to class II.
  - BTS prior imaging is lesion-scoped. "No" may settle from the whole dictation only when the history mentions no imaging.
  - Small pelvic free fluid is not ascites.
- **Queued for the next slice:** a UK non-gated CT calcium pack (Williams, BJR 2020) and a Likert prostate MRI pack (NICE NG131). Also proposed: an incidental-AAA pack (NICE NG156).
- **Process:**
  - reviews are done by independent agents;
  - each pack gets a clinical read;
  - packs authored in parallel never `git add` until they commit, and never amend;
  - merging needs Hassan's go-ahead;
  - prod data may be read but stays in the scratchpad.

## Open items for Hassan
- **Provisional rulings to confirm:**
  - RCOG GTG 62 eligibility: "not pregnant" settles from a pelvic ultrasound that describes the uterus; "acute" settles from the indication only.
  - CAC-DRS: a dictated category still asks whether an Agatston score exists. This is friction to revisit with the draft card.
- **Possible sources** if the pack is wanted later:
  - Outerbridge: Potter 1998 (DOI 10.2106/00004623-199809000-00005) and ICRS, Brittberg 2003.
  - The RCR/RCOG 2025 consensus document behind GTG 34.


## Decisions the plan needs from Hassan (raised by the plan writer, commit 1b38fb3)
1. **Demotion:** the lab reports each input's pre-fill error rate and recommends which inputs to demote; Hassan decides.
2. **Checker disagreement.** When the dictated category disagrees with the features and nothing is corrected, the plan applies the computed result with a flag and never writes the dictated category. Confirm, or offer the dictated category instead.
3. **To confirm:**
   - the preview's draft outcome ("on these values") can never be applied; only Calculate's result can;
   - booleans and absent / not-assessable states are only ever "pre-filled", never "read";
   - prior_study stays lesion-scoped and is asked first as a parent.
4. **About 20 dictations in Hassan's own style** are wanted before labelling, or confirm that real production findings are enough.

## Gotchas
- **Permissions:** the auto-mode permission classifier sometimes blocks new subagent dispatches. Don't work around it. Ask Hassan to allow it in `/permissions`, or to run `claude -p "<brief path>"` himself. Writing a brief file first keeps that a one-liner.
- **Production workers:** the read-once cache is per process. Check the Railway worker count before relying on it in production.
- **Gate 5** (the Jev evidence check) scores facts from table images and multi-page facts low. Authors resolve those flags by reading the source.
- **Two-column PDFs:** `pdftotext -layout` scrambles them. Use plain `pdftotext` or page images.
- **The skill** now covers `check_pack.py`, the PDF-page locator convention and a tier 2 template. Other pack-author friction (tier 2 schema docs, region vocabulary, per-caveat locators for gate 5) is listed in the ledger and not yet folded in.
