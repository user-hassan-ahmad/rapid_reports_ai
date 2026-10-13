# Scratchpad Copilot: handover (2026-10-12)

> **Update (2026-10-12, later):** Hassan adopted the packs. The design is the curated guideline library. Its spec is
> `docs/superpowers/specs/2026-10-12-guideline-library-design.md`, and its §12 "First slice" replaces §6 below.
> **First slice closed (2026-10-12).** Schema proof passed; coverage lab ran (negative-control gate mitigated by a
> pack applicability gate); preview lab **failed** (1 wrong proposal from a different lesion, p95 3568 ms vs 2 s).
> See spec §12. Next, in order:
> 1. Fix preview lesion scoping (input scope lesion/patient; lesion-scoped quotes from the card's own finding unit)
>    and latency (smaller settle prompt or faster model), then re-run the preview lab. Frontend must not start Apply
>    until it passes.
> 2. Frontend Tasks 14–19 from `docs/superpowers/plans/2026-10-12-scratchpad-copilot.md`, Apply only on pack and TNM
>    cards. Task 14 (the mock-up) needs Hassan's approval first.
> 3. Next packs in coverage-lab order (`docs/guidelines/coverage-lab-2026-10.md`).

**Start here next session.** The backend has been built and reviewed. A step-back review then found that its runtime
web-retrieval half cannot deliver what Apply needs. **The open decision for Hassan is whether to pivot to curated
offline packs.** Building is paused until he decides.

- Branch: `feat/scratchpad-copilot`, in the worktree `.claude/worktrees/scratchpad-copilot`. It was cut from
  `feat/hybrid-stack` (PR #31) and is not pushed. HEAD is `d6cc4f2`.
- Spec: `docs/superpowers/specs/2026-10-12-scratchpad-copilot-design.md`. Its §2 lists 25 numbered decisions.
- Plan: `docs/superpowers/plans/2026-10-12-scratchpad-copilot.md`. It has 21 tasks plus 5b. Tasks 1–11 are done.
- Evidence (copied from the session scratchpad): `docs/superpowers/handover/2026-10-12-copilot-evidence/`. It holds
  the step-back report, the lab scripts and the lab outputs.

## 1. Mission

The aim is to enrich context at the moment of the first read, so that the radiologist confirms assumptions up front
and generation stays lean. The Copilot is a side panel beside the dictation scratchpad. It has four parts:

- **Cards:** guidelines and classifications that match what has been dictated (Fleischner, Bosniak, TNM, …).
- **Reading:** opening a card is for reading only.
- **Apply:** this is the only way content enters the report. It adds a classification line under the finding and a
  ticked recommendation to a Recommendations checklist under the conclusion.
- **Ask:** one input that files each question under the open card, or under "General".

What reaches a report must be correct.

## 2. What is built (backend Tasks 1–11, all independently reviewed)

The code is in `backend/src/rapid_reports_ai/hybrid_stack/copilot/`. There are about 2,640 lines, and 560 tests
pass across the copilot, stack, quick-report and review suites.

| Module | Role | Status |
|---|---|---|
| `types.py` | Shared pydantic types | keep |
| `tnm.py` + `resources/tnm_9th_clean.json` v2.2 | Offline UICC TNM 9. Category text cleaned (`scripts/tnm/clean_tnm_9th.py`); clinical stage tables for 36 sites rebuilt and hand-checked (`scripts/tnm/rebuild_stage_tables.py`); X convention; histology variants for oesophagus | **keep (load-bearing)** |
| `matcher.py` | Which systems apply to each abnormal finding (gpt-oss); TNM closed site list plus Jev gate; caches | **keep**, simplify to a closed list |
| `preview.py` | Model settles inputs with verbatim quotes; Jev checks quotes that are not verbatim; model picks an output index; **code copies** the classification and recommendation; code computes what is missing | **keep (load-bearing)** |
| `recs.py` | General recommendation suggestions; a backstop drops items containing numbers | keep |
| `ask.py` | Routing, grounded answers, gap search, supplements | simplify |
| `routes.py` | `/api/canvas/stack/guidelines/*`, kill switch `RR_STACK_COPILOT`, validation, timeouts, background tasks | keep, then simplify |
| `quick_report_brief.stack_fallback`, `quick_report_prompts`, `report_review` | `RECOMMENDATIONS:` section from ticked items, consistent across brief, prompt and review | **keep** |
| `registry.py`, `search.py`, `fetch.py`, `jev.py` gates, migration `20261012150000` | Lazy web fetch into a shared registry, with relevance/coverage/evidence gates, locks and background fill | **park** (see §4) |

The local dev DB (`tnm_test`) has `guideline_registry` and `dictation_stack_logs.copilot`. They were created by
hand, matching the migration. The worktree has no `.env`; scripts load the main `backend/.env` through `dotenv`.

## 3. Lab evidence

**Evidence lab** (`evidence_lab.py`, `evidence_lab_run*.json`): 24 hand-written claims with branch context,
2 runs. With the strict wording, Jev separated every true claim (lowest 0.73) from every false one (highest 0.19).
Wrong-branch claims scored ≤ 0.08. `EVIDENCE_MIN` was set to 0.5. The lab is valid but optimistic, because the
claims and sources were clean.

**Search lab** (`diag.py` / `armb.py` / `armc.py`, `search_arm*.json`), on 7 seeds: branch coverage rose from 11/24
to **18/24** (arm B) once abstracts were ranked last and 4 full pages were read; arm C scored 17/24. Searching the
issuer's own domain backfired. O-RADS and LI-RADS criteria sit in ACR PDFs and images that search does not reach.

**Seed lab, real end-to-end run** (`seedlab.py`, `seed_lab_run1_entries.json`): first open takes about 5–11 s, and
background fill another 6–11 s.

- Per row, about 26/30 stored outputs were correct.
- About 4 were wrong and confidently attributed to the wrong source:
  - A flattened PDF table gave Fleischner low-risk 6–8 mm "No routine follow-up CT at 6–12 months…".
  - An ESR poster's own categories were stored as ESE 2023.
  - A research study's CA125 rule was stored as O-RADS 4.
  - A CUA follow-up recommendation was credited to Bosniak 2019.
- **Read as tables, the result is worse:**
  - Fleischner single solid was marked `checked` with only its 6–8 mm rows; the <6 mm and >8 mm rows were missing.
  - Kellgren–Lawrence held grade 0 only.
  - LR-5, Bosniak III/IV, BTA U4/U5 and O-RADS 2/5 were `not_available`.
  - LI-RADS and O-RADS had unusable input ids (`I1`, `f1`).

## 4. The insight (step-back review, `stepback_review.md`)

**Keep the front half; replace the back half.** The front half is right: cards, Apply as the only path into the
report, the enrichment line, the checklist, preview, TNM and the matcher.

The back half drifted into a general web-knowledge engine. One early choice, a lazy web fetch into a shared
registry, forced most of the complexity that later reviews kept patching:

- draft/verified status and the review page;
- per-key and per-branch locks, background fill and the 7-day retry;
- branch merging and edition/branch normalisation;
- `safe_identity`, case-free supplements and outage rules.

In numbers: 14 of 31 commits were review fixes, there were about 10 provisional thresholds, and 8 Jev question types.

**The errors are built into the approach and cannot be tuned away:**

1. Pages that *discuss* a guideline outnumber the guideline itself. "Is this page *the* guideline?" is a
   provenance inference, which is Jev's weak side.
2. Checking each row for support can never notice a missing row, so `checked` only means "at least one supported
   row".
3. PDF tables flatten into rows that can be quoted but are wrong.

**Recommendation: curated offline packs**, following the TNM pattern.

- **Pack format:** one hand-checked JSON per system in the repo. Each holds a complete grid from input combinations
  to classification and recommendation, human labels, rule notes and a source link.
- **Check:** a code check confirms every input combination maps to exactly one row.
- **Runtime:** a closed-list matcher. Pack and TNM cards open instantly, code evaluates them, and they have Apply.
- **Long tail:** systems that are recognised but have no pack get a **read-only** card: a model-knowledge summary,
  labelled as such, plus a link, and never Apply.
- **Effect:** the card path makes no search calls, uses no registry table and needs no verified/draft tagging.
- **Coverage estimate:** 15–20 packs plus TNM should cover nearly every finding worth applying. The coverage lab
  measures this.

**Controller's addition (Claude):** keep the fetch pipeline as an **authoring tool**, not a runtime path. It drafts
a pack from a primary source Hassan picks. Jev evidence and the completeness check flag issues, and the pack ships
after Claude's hand read. The library still grows, prioritised by which long-tail cards radiologists open, but
nothing unchecked can be applied.

## 5. Decisions made this session (do not reopen)

- Cards, explicit Apply, an enrichment line under the finding, and a Recommendations checklist under the conclusion.
  Items from applied guidelines start ticked; suggestions start unticked; unticked items are dropped.
- One ask input. Threads sit under cards and are session-only.
- Jev judges meaning; code only removes things or checks deterministic facts.
- "Model chooses, code copies" for proposals.
- No case text reaches external search.
- Supplements never hold the question or the answer.
- TNM: offline, X convention, closed site list plus Jev gate (lab it against `hybrid_tnm_search` before replacing
  that), and stage taken only from the rebuilt tables.
- Rollout to all users with no per-user gate, as part of the new scratchpad layout.
- **Drop the verified/draft tagging** (Hassan): guards on the information flow, plus source links, are enough.
- Licensing: the UICC text came from a shadow-library PDF. This was raised once, and Hassan chose to proceed.

## 6. Next steps

**If Hassan adopts the packs:**

0. Freeze the search/fetch/registry commits out of the shippable line, and mark them as the authoring tool. Update
   the spec and plan.
1. **Coverage lab:** run the matcher unchanged on prod stack dictations. Gate: N packs cover about 90% of correctly
   named systems, and negative controls produce no card that can be applied.
2. **Pack format plus 3 packs** (Fleischner, Bosniak, ESE adrenal). Gate: every row correct against the primary
   source, the grid complete, labels readable.
3. **Preview lab on packs.** Gate: zero wrong proposals, inputs settled and missing correctly, under 2 s.
4. **Closed-list matcher plus read-only long-tail cards.** Gate: matcher precision.
5. **Simplified ask.** Gate: routing lab.
6. **Frontend Tasks 14–19,** with Apply only on pack and TNM cards. **Task 14 is a mock-up that Hassan must
   approve.** Drop Task 20, the review page.
7. **Remaining packs,** in batches ordered by frequency, then by ask logs.

**If Hassan keeps the web pipeline:** add a Jev page-role gate ("this page states the guideline itself"), structure
prompt rules for plain `when` text and table cells, branch-matched window selection on long pages, and recalibrate
`EVIDENCE_MIN` on the real fixture, then rerun the seed lab. Expect slow first opens and incomplete tables.

## 7. Gotchas

- Run tests with `cd backend && PYTHONPATH=src .venv/bin/pytest …`. The editable install points at the main
  checkout, so `PYTHONPATH=src` is required.
- Labs load keys from `/Users/hassan/Code/rapid_reports_ai/backend/.env` via `dotenv`. The shell cannot `source`
  that file. Before any lab write, assert that `DATABASE_URL` is localhost.
- Frontend notes for Tasks 16/19 are already in the plan:
  - the `/open` fetch timeout must be ≥ 90 s;
  - handle the `loading` flags;
  - join `RECS_LINE` items with "; " and send that line only in the Generate payload, never in `/draft`.
- The prefetch path's `tnm_embeddings.json` still holds v2.0 TNM text. Re-embedding it needs an OpenAI run.
