# Section Pill Coverage as System 1 Decisions (Jev) — Design

**Date:** 2026-09-24
**Status:** Implemented on branch `dictation-triage-lab`; bake-off run 1 in §7; production default unchanged (`RR_COVERAGE_CANDIDATE=qwen`)
**Branch:** dictation-triage-lab (builds on the triage lab; see `2026-09-24-jev-dictation-triage-shadow-design.md`)
**Parent:** first component of `2026-09-24-decision-first-dictation-design.md`

## 1. Problem

The checklist pills above the scratchpad (LUNGS, PLEURA, MEDIASTINUM, …) light up when the review endpoint decides a section has been "meaningfully addressed". Today that decision is a generation call: Qwen 27B receives the scratchpad and the checklist and is asked to emit a list of covered section names. Because the output is free text inside a `list[str]` schema, the route carries a normaliser that splits comma-joined names and drops hallucinated ones. The call runs after every polish and on every typing pause, and it is binary: a section is either lit or not.

The question is a set of independent yes/no judgements, one per section, each governed by rules the prompt already states precisely (direct coverage, collective coverage over a recognisable group, specific claims overriding collectives, bare mentions not counting). That is the shape a System 1 model answers natively: one Noul per section, evaluated in parallel, keyed by the section name, with a probability instead of a membership.

## 2. Goals / Non-goals

### Goals
- One Jev call returning a probability per checklist section, using the coverage prompt's own rules as the Noul criteria.
- A lab trace on the review endpoint showing Jev and Qwen side by side per section, with latencies.
- Three-state pills in the lab (covered / partial / absent) driven by the probabilities, thresholds adjustable in the panel.
- A production selection switch, `RR_COVERAGE_CANDIDATE`, defaulting to the current Qwen path. Selecting `jev` makes the normaliser dead code for that path.
- A labelled fixture set that exercises every rule in the coverage prompt, and a bake-off in the existing summary format.
- Fixture export from the lab for coverage cases, like the triage export.

### Non-goals
- Changing the production pill UI. Production keeps binary pills from `covered_sections` until the switch is flipped and, separately, until a decision on three-state pills is made.
- Touching IntelliPrompts. They stay a generation call in the same endpoint; the parent spec covers their future.
- Running coverage inside the per-utterance triage call. That belongs to the decision bundle (parent spec); here coverage stays on `/review`.
- Removing the Qwen coverage path. It remains the default and the shadow comparator.

## 3. Coverage as Noul questions

State sent to Jev:

```json
{"scan_type": "CT chest", "checklist": ["LUNGS", "PLEURA", "..."], "scratchpad": "<scratchpad text>"}
```

One Noul per section, id = the section string exactly as the checklist has it:

```
instructions: "The scratchpad meaningfully addresses the checklist section {SECTION}."
criteria:
  true:  "The scratchpad contains a definitive clinical claim about {SECTION} or a standard
          radiological abbreviation of it: a finding, a measurement, a qualifier, or an explicit
          normality statement. The claim may be direct ({SECTION} is the subject, the location via a
          prepositional phrase, or an adjectival modifier of the subject) or collective (a definitive
          claim over a recognisable anatomical group that {SECTION} genuinely belongs to, such as
          normality or absence of pathology). A specific claim about {SECTION} counts even when a
          collective also exists."
  false: "There is no definitive claim about {SECTION}: only a bare mention with nothing asserted; a
          claim about an adjacent but distinct structure; a parent-structure claim that does not
          enumerate {SECTION} when the checklist lists it separately; an incidental co-mention inside a
          statement about another structure; a vague filler with no anatomical scope; or a collective
          whose group {SECTION} does not clearly belong to. When in doubt, this is the answer."
```

The criteria text is generated from a single constant, `COVERAGE_CRITERIA`, with `{SECTION}` substituted, so all sections share one definition and edits happen in one place. The wording is lifted from `CANVAS_COVERAGE_SYSTEM_PROMPT`; when that prompt changes, this constant is updated in the same commit (a test asserts the key phrases appear in both).

Answer: `{section: probability}`. Thresholds live in code, not in the model:

- production binary (when `RR_COVERAGE_CANDIDATE=jev`): covered if `p >= 0.5`
- lab three-state: covered `p >= t_hi`, partial `t_lo <= p < t_hi`, absent otherwise; defaults `t_hi = 0.8`, `t_lo = 0.4`, both adjustable in the panel.

## 4. Components

### 4.1 `backend/src/rapid_reports_ai/section_coverage.py` (new)

```python
COVERAGE_CRITERIA: dict[str, str]          # {"true": ..., "false": ...} with {SECTION}
def coverage_questions(sections: list[str]) -> dict[str, dict]   # one noul per section
@dataclass(frozen=True)
class CoverageDecision:
    candidate: Literal["jev", "qwen"]
    scores: dict[str, float]                # jev: probabilities; qwen: 1.0/0.0 from membership
    covered: list[str]                      # sections at/above the binary threshold, checklist order
    latency_ms: int
    input_tokens: int | None
    cost_usd: float | None

class JevCoverage:
    async def classify(self, scratchpad: str, sections: list[str], scan_type: str) -> CoverageDecision
```

- Reuses the HTTP discipline of `JevTriager` (same endpoint, key, 3 s timeout, `TriageError` on any invalid answer). Every section id must be present in `answers` with a value in [0, 1]; otherwise raise.
- Empty checklist → returns an empty decision without a call.
- The Qwen side is not reimplemented: the existing `run_coverage` closure is lifted into a module-level `async def qwen_coverage(request) -> CoverageDecision` in `canvas_routes.py` so both candidates return the same shape. Its normaliser stays where it is.

### 4.2 Review endpoint changes (`canvas_routes.py`)

```python
class CanvasReviewRequest(BaseModel):
    ...
    coverage_debug: bool = False            # lab only (RR_TRIAGE_DEBUG=1): attach both candidates

class CoverageCandidateTrace(BaseModel):
    scores: dict[str, float] | None; covered: list[str] | None
    latency_ms: int | None; input_tokens: int | None; cost_usd: float | None; error: str | None

class CoverageTrace(BaseModel):
    selected: Literal["jev", "qwen"]
    jev: CoverageCandidateTrace | None
    qwen: CoverageCandidateTrace | None

class CanvasReviewResponse(BaseModel):
    covered_sections: list[str]
    prompts: list[IntelliPrompt] = []
    coverage_scores: dict[str, float] | None = None   # from the selected candidate; Qwen gives 1.0/0.0
    coverage: CoverageTrace | None = None             # lab only
```

Selection: `_coverage_candidate()` reads `RR_COVERAGE_CANDIDATE` (`"qwen"` default; `"jev"` only honoured when `OPENROUTER_API_KEY` is set, with the same warn-once pattern as the triage flags).

Flow inside `review_scratchpad`, replacing the `run_coverage` closure:

1. `selected = _coverage_candidate()`; `debug = _triage_debug_enabled() and request.coverage_debug`.
2. Coverage tasks: the selected candidate always; the other candidate too when `debug`. Gather with `return_exceptions=True` alongside `run_intelliprompts()` exactly as today.
3. `covered_sections` and `coverage_scores` come from the selected candidate. If the selected candidate failed, fall back to the other candidate's result if it ran, else `[]` (today's degrade behaviour). Log the fallback.
4. When `debug`, attach `coverage` with both traces.

Nothing in this flow blocks on the non-selected candidate for longer than the gather already waits for IntelliPrompts, which is the slowest leg.

### 4.3 Frontend

- `DictationScratchpad.svelte`: `_runReview` adds `coverage_debug: !!labConfig?.coverageDebug` to the body, forwards `data.coverage_scores` through a new prop `onCoverageScoresChange(scores)` (no-op by default), and, when present, reports `data.coverage` through a new `onCoverageTrace(trace)` callback. Home page unchanged.
- `IntelliDictateTab.svelte`: pass-through of the two callbacks; new optional prop `pillThresholds: { hi: number; lo: number } | null = null`. When non-null and scores exist, pills render three-state (emerald / amber / grey); when null, the current binary rendering from `coveredSections` is untouched.
- `LabConfig` gains `coverageDebug: boolean` (default true) and `pillThresholds: { hi: 0.8, lo: 0.4 }`; persisted with the rest.
- `DictationLabPanel.svelte`: a **Coverage** section showing, per section, the Jev probability, the Qwen membership, and agreement colouring; latencies per candidate; two sliders for `hi` and `lo`; and an **Add to coverage fixtures** button that captures `{scratchpad, checklist, scan_type}` plus a per-section expected checklist (pre-filled from the Jev result at 0.5, editable) into a second export buffer.
- `src/lib/dictation-lab/coverage.ts`: pure helpers, `pillState(score, thresholds)`, `coverageAgreement(jevScores, qwenCovered, threshold)`, `buildCoverageFixtureLine(...)`, with vitest tests.

### 4.4 Fixtures and bake-off

- `backend/tests/fixtures/coverage_cases.jsonl`: `{"id", "scan_type", "checklist": [...], "scratchpad", "expected_covered": [...], "rule", "hard", "note"}`. Seed of 24 hand-written cases, at least three per rule: direct-subject, direct-location, direct-modifier, collective-solid-organs, collective-boundary (solid organs do not cover bowel), specific-overrides-collective, bare-mention, adjacent-structure, parent-not-enumerating-child, incidental-co-mention, vague-filler, abbreviation (CBD, IVC).
- `backend/tests/test_coverage_fixtures.py`: well-formed, ids unique, every `expected_covered` entry is in that case's checklist, ≥ 3 cases per rule.
- `backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py`: runs every case through `JevCoverage` and `qwen_coverage`, scores per-section precision/recall/F1 per candidate, exact-set accuracy per case, latency p50/p95, cost, Jev calibration by probability bucket; writes `docs/model-migration/coverage-bakeoff-<date>.json`. Reuses `triage_summary`'s bucket and percentile helpers (factored out into `scripts/_stats.py` if needed).

### 4.5 Tests

- `test_section_coverage.py`: `coverage_questions` yields one noul per section with the section as id and `{SECTION}` substituted; criteria contain the key phrases from the coverage prompt (bare mention, collective, adjacent, abbreviation); Jev request/response parsing through `httpx.MockTransport`; raises on missing section, out-of-range value, non-2xx, timeout; empty checklist makes no call.
- `test_canvas_coverage_modes.py` (route level, fakes for both candidates and IntelliPrompts):
  - default env: Qwen selected, no Jev call, response identical to today plus `coverage_scores` of 1.0/0.0, `coverage` absent.
  - `RR_COVERAGE_CANDIDATE=jev`: Jev selected, `covered_sections` at 0.5, `coverage_scores` are probabilities, no normaliser involvement.
  - selected candidate fails, other not running: `covered_sections == []`, 200.
  - `coverage_debug` with `RR_TRIAGE_DEBUG=1`: both run once, both traces present, selected drives `covered_sections`; selected fails → other's result used and logged.
  - `coverage_debug` without the debug flag: ignored, no trace.
- Frontend: `coverage.test.ts` for the pure helpers.

## 5. Exit criteria for flipping `RR_COVERAGE_CANDIDATE=jev` in production

On the coverage fixture set: per-section F1 ≥ Qwen's, exact-set accuracy ≥ Qwen's, zero cases where a bare mention or an out-of-group collective is scored ≥ 0.5, p95 ≤ 800 ms. Plus one week of lab use with no coverage disagreement a reviewer would side with Qwen on (tracked through the export buffer's `note`).

## 6. Risks

- **Criteria drift.** The Noul criteria and the Qwen prompt must say the same thing. A test pins the shared phrases; the constant carries a comment pointing at the prompt.
- **Collective boundaries.** The prompt's hardest rule (solid organs do not cover hollow viscera) is where Jev is least likely to match a reasoning model. The fixture set over-represents it and the bake-off reports it as its own rule.
- **Cost.** One call per review with N nouls; at ~600 input tokens that is ~$0.00003 per review, and reviews already happen per utterance.

## 7. Bake-off run 1 (2026-09-24, 25 fixtures, 11 hard)

Data: `docs/model-migration/coverage-bakeoff-2026-09-24.json`.

| | Jev 1.13 | Qwen 27B (Groq, current path) |
|---|---|---|
| per-section precision / recall | 1.000 / 0.955 | 1.000 / 1.000 |
| exact-set accuracy (all / hard) | 0.920 / 0.909 | 1.000 / 1.000 |
| errors | 0 | 0 |
| p50 / p95 latency | 303 ms / 445 ms | 860 ms / 1669 ms |
| cost, 25 calls | $0.0013 | $0 |
| Jev per-section confidence ≥0.8 (n=68) | accuracy 1.000 | n/a |
| Jev per-section confidence 0.5–0.8 (n=16) | accuracy 0.875 | n/a |

**What it says against §5.** Jev never over-covers (precision 1.0, and no bare mention or out-of-group collective scored ≥ 0.5), clears the p95 bar comfortably, and matches Qwen on ten of twelve rules. It does not yet match Qwen's recall: two collective cases (`cb-02` "thoracic structures" → PLEURA not credited; `so-02` "remaining thoracic structures are normal" → LUNGS not credited) fall just below 0.5. Both misses sit in the 0.5–0.8 confidence band, where the three-state pill renders **partial** rather than absent, so the lab shows them as amber rather than silently missing. Qwen is exact on every case but ~3× slower at p50 and ~4× at p95. The recall gap is the thing to close before flipping the production switch: either sharpen the collective criteria wording (the group-membership sentence) or accept a lower binary threshold for collectives after a larger fixture run.

**Lab check (2026-09-24).** Coverage panel renders Jev probabilities beside Qwen ticks with per-section agreement colouring; thresholds move pill states live; export to the coverage fixture buffer works end to end (see the lab-exported case appended to `coverage_cases.jsonl`).
