# Policy 1 for dictated findings — negatives that follow a reported finding

**Status:** revision 2, approved in conversation 2026-09-29 · **Ledger:** L-45 (to open)
**Depends on:** compiled brief (bd938a0), policy 1 (`docs/superpowers/research/2026-09-29-sheet-reconciliation-bakeoff.md`)
**Sub-project 1 of 2.** Sub-project 2 (a side panel of optional items grouped by report
section) gets its own spec once this payload shape is settled. See "Hand-off to the UI spec".

> **Revision 2 (2026-09-29).** Revision 1 keyed the negatives to *confirmed differential
> branches*. The first live run (arm B, 8 cases) stated nothing in any case:
> - **Imaging confirms findings, not diagnoses.** Jev scored "pancreatic head mass
>   (adenocarcinoma)" 0.68 and "primary lung carcinoma" 0.35, and those scores are right.
> - **The main finding is usually not a differential line.** Haemorrhage, PE and vertebral
>   metastases are the primary hypothesis; the aetiology tier lists their causes.
> - **Branch names did not match** (0/4 on the cerebellar case).
>
> Revision 2 keys the negatives to the **imaging finding** instead, and adds a fallback for
> findings the sheet did not anticipate. Rule C, the Qwen check, the impression limit, the
> options payload, persistence and the frontend are unchanged from revision 1 and already
> built (`feat/confirmed-negatives`, Tasks 1–7).

## Problem

Prod report `064ff6f1` (CT AP with contrast, history "jaundice"; dictated 3 cm pancreatic head
mass, distal CBD compressed to 12 mm, intra- and extrahepatic duct dilatation). The report
named the mass and the obstruction but said nothing about the features that decide
resectability: SMA / SMV / portal vein / coeliac contact, peripancreatic extension. The QA
audit flagged exactly this (`characterisation_gap`, severity critical).

Under policy 1 the report should have said it. By reporting convention, a finding whose
imaging sign is visible on this technique but was not dictated was not seen. So the negatives
that follow a reported finding belong in the report, as "No focal hepatic lesion" and "No
porta hepatis lymphadenopathy" already were.

## Root cause

1. **The sheet is written before anything is dictated.** Its mandatory negatives answer the
   question as asked. None of them follows from a finding that has actually been reported.
2. **The staging features exist only as descriptors of what is present:** In-scope companions,
   one Measurement convention, exemplars.
3. **The brief removes the carriers.** It always drops In-scope companions.
4. **The generator can't bridge the gap.** An undictated descriptor with no listed negative
   falls under the no-fabrication rule, so the generator says nothing.

## Decisions (2026-09-29)

1. **Stated by default.** An unambiguous finding-linked negative is stated in FINDINGS as a KEEP
   mandatory negative.
2. **Ambiguous means offered (rule C).** A negative is stated only if **both** of these hold:
   - its finding is **clearly** reported (Jev ≥ high cut-off);
   - the analyser tagged the negative **core**.

   Otherwise it is offered.
3. **The impression stays a synthesis.** One of these negatives reaches the impression only
   when the impression plan judges it changes the interpretation of a carried finding.
4. **Optionals are their own tier,** tagged with the report section they would go into.
5. **Unanticipated findings get offered negatives only.** A finding the sheet did not foresee
   gets negatives written at brief time by Qwen, and those are never stated.

## The link: how a reported finding reaches its negatives

| Step | Who | What |
|---|---|---|
| Anticipate findings and write their negatives | **Analyser**, at sheet time (during dictation, reasoning on) | The findings this question anticipates, keyed as a radiologist would dictate them; each key's negatives; core or contextual |
| Is the key's finding reported? | **Jev**, one question per distinct key, in the existing parallel call | Text matching (the bake-off's strong case); the calibrated score feeds rule C |
| Is each negative kept, contradicted, or an expected consequence? | **Qwen**, reasoning off, existing negatives call | Clinical reasoning; Qwen 0.88 vs Jev 0.65 |
| A carried finding with no key scoring ≥ 0.5 | **Qwen**, reasoning off, parallel fallback | Writes its pertinent negatives; all offered, never stated |
| Stated, offered, labelled, dropped | **Code** | Routing table below |

**The Jev question**, phrased to avoid the bake-off failures (no diagnosis, no negative
sentence embedded in a claim):

> *The dictated findings report this imaging finding, in any wording or size: {key}*

## Design

### 1. Analyser — opt-in directive `finding_negatives`

It replaces the revision-1 `confirmed_negatives` directive, and remains opt-in until you sign
it off. The sheet gains one Companion Matrix bullet, one line per negative:

```
- **If present:** (negatives stated only when the dictation reports the finding)
  - <imaging finding as a radiologist would dictate it> → "<negative in report form>" (core | contextual)
```

The directive text is case-agnostic (structural form, no clinical example):

> **If present.** List the imaging findings this clinical question anticipates: the
> primary finding and each alternative the study could show. For each, list the negatives a
> consultant states once that finding is reported: the absence of each extension, spread or
> complication this technique shows and the next management step depends on. Write each key
> as the imaging finding a radiologist would dictate, never the diagnosis it suggests, and at
> the most general level at which its negatives still apply. Write every negative on its own
> line with its key repeated, in the form shown. One finding per negative: no "or", no
> comma-separated list. Tag each negative core when any consultant states it once that
> finding is reported, contextual when stating it depends on the case or local practice. At
> most three negatives per finding and fifteen in total. Never repeat a mandatory negative.
> Never write a negative denying something the finding is expected to cause.

### 2. Brief — link, check, route

- **Parse** If-present lines as `(key, negative, tag)`. Both the one-line and the nested
  shape are accepted, since Qwen emits both. A missing tag counts as `contextual`.
- **Jev:** one question per distinct key (`f{i}`) with the wording above, added to the
  existing parallel call.
- **Qwen:** every candidate negative goes into the existing negatives call.
- **Route** each candidate by rule C:

| Qwen label | Jev (key reported) | Tag | Outcome |
|---|---|---|---|
| any | < low (0.5) | any | dropped |
| contradicted | ≥ low | any | dropped |
| expected | ≥ low | any | **DO NOT ASSERT** |
| keep | ≥ high | core | **stated** (KEEP, annotated `(finding: <key>)`) |
| keep | ≥ high | contextual | **offered** |
| keep | low ≤ p < high | any | **offered** |

Offered items are `{"kind": "finding_negative", "section": "FINDINGS", "text", "finding", "reason"}`,
with their own cap `MAX_FINDING_OPTIONS = 4`. Decisions record `finding_negatives` (each
candidate's key, text, tag, qwen label, p and outcome) and each negative's `source`.

### 3. Fallback for unanticipated findings

The impression plan already returns `impression` (the carried finding numbers). After it
returns, code lists each carried finding that has no key scoring ≥ 0.5. If there are any, one
Qwen call (reasoning off, 6 s timeout) writes up to three pertinent negatives per such
finding. The call runs from the same `gather`, speculatively: it is given every dictated
finding and returns negatives per finding number. Code keeps only those for uncovered carried
findings, so latency is unchanged. They are **offered** (reason `"unanticipated finding"`),
never stated, and they still count against the `MAX_FINDING_OPTIONS` cap. If the call fails,
nothing is offered.

### 4. Impression, options payload, persistence, frontend

These are unchanged from revision 1 (already built):
- the impression plan sees every candidate and may carry only stated ones;
- every option carries `section`, and FINDINGS items pass through verbatim;
- the brief is persisted on the candidate;
- the frontend hides FINDINGS-scoped kinds until the side panel exists.

The kind `confirmed_negative` is renamed `finding_negative`.

## Coverage check (gate before further build)

Before the brief changes, run the new directive against `silent_staging.json` + three hedged
variants + `varied_10.json`, one run each, and measure:
- **Key coverage:** for each silent and `varied_10` case, the main dictated finding has a
  key scoring ≥ 0.5. Target ≥ 90%.
- **False triggers:** any key scoring ≥ 0.5 on the two controls. Target 0.
- **Calibration:** Jev scores of the matched key for clearly-reported vs hedged findings.
  This sets `PRESENT_HIGH`; if they don't separate, `PRESENT_HIGH = PRESENT_LOW` and the tag
  alone decides.
- **Negatives quality (by hand):** single-finding, pertinent, and not an expected
  consequence.

If coverage is below 90%, the fallback carries more weight. Record which findings were missed
and why before deciding whether to rework the directive.

## Evaluation (after the gate)

As revision 1: arms A (production) vs B (+ `finding_negatives`), silent-staging basket × 3,
`varied_10` regression × 1, predictions written first in L-45, then read by hand.

| Measure | A | B |
|---|---|---|
| Silent: ≥1 finding-linked negative stated in FINDINGS | ~0/6 | ≥5/6 |
| Report negative contradicting the dictation | 0 | 0 |
| Expected-consequence negative anywhere | n/a | 0 |
| Negatives carried into the impression | n/a | median ≤1 per case, each changing interpretation |
| Offered negatives per silent case (median) | 0 | 1–2 |
| Controls: new negatives or options | 0 | 0 |
| Regression gate | 100% | 100% |
| Analyser median latency | baseline | within +1.5 s |

## Risks

- **Asserting staging from silence.** Intended under policy 1; rule C restricts it to clearly
  reported findings and core negatives.
- **Anticipation gaps.** The coverage check measures them; the fallback offers negatives for
  them.
- **Key too specific or too general.** A key that is too specific is missed; one that is too
  general fires on the wrong finding. The coverage check and controls measure both.
- **Naming primes.** A stated negative names a structure. If positive descriptors get invented
  for it, the fabrication read catches it.

## Hand-off to the UI spec (sub-project 2)

Every option carries `id`, `kind`, `section`, `sentence`, `reason`, and `finding` where one
applies. The UI spec designs the side panel grouped by `section`. It also decides where a
FINDINGS option goes: next to its finding's paragraph, or at the end of FINDINGS.
