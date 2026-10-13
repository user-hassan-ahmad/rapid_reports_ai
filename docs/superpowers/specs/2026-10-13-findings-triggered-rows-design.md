# Findings-triggered template rows — design (roadmap item 5)

Date: 2026-10-13. Status: draft for Hassan's approval. This expands §3 of
`2026-10-13-template-rules-next-design.md` and part 2 of `2026-10-12-template-requirements-design.md`.
It depends on:
- the Rules step (`2026-10-13-template-rules-step-design.md`): cards and ledger;
- the chat-edit router (`2026-10-13-chat-edit-router-design.md`): chat add and remove.

Principle: **Jev decides, code applies, nothing is written unasked.**

## Decisions (Hassan, 2026-10-13)

1. **Template rows only, in the scratchpad checklist.**
   - The guideline draft cards stay in the copilot panel, so this item does not merge with them.
   - One known follow-up for when the copilot branch lands: a template row and a copilot card input asking the
     same thing about one finding are deduped, and the template row wins.
2. **Two row shapes:**
   - a required statement, pre-filled and confirmed or removed like an assumed normal;
   - a habit question with quick answers that write the template's own sentence.
3. **Proposed at creation, then confirmed.** The decision run proposes a habit only with evidence in at least 2
   example reports, with quotes. The radiologist confirms it on a Rules-step card. Chat can add or remove one
   later through the router. Nothing is active until it is confirmed.
4. **Template rows first, within the same caps** (`hybrid_stack/items.py:25-26`: 2 per region, 4 in all).
   Generic Qwen rows that no longer fit go behind "N more checks". The scratchpad never gets longer.

## Today

- A findings-conditioned habit is banned as a template rule (`template_sheet_grammar.py:615-619`, `NOT_LEAN`). It
  lives only as prose exemplars, which Jev never checks and the scratchpad never asks.
- The generic checklist rows are Qwen-written (`hybrid_stack/items.py`, `Item` kind `finding | referral`) and
  capped by `_limit`.

## Grammar (template mode)

Two new forms are allowed, only inside a findings paragraph:

```
NEGATIVE "No intra-articular extension." WHEN [findings: a fracture is reported]
RULE WHEN [findings: a fracture is reported] ASK "Intra-articular extension?" YES "The fracture extends to the articular surface." NO "No intra-articular extension."
```

- **Required statement:** `NEGATIVE … WHEN [findings: …]`.
- **Habit question:** `RULE … ASK "<question>" YES "<sentence>" NO "<sentence>"`.
  - YES and NO are the template's own sentences.
  - "Not assessed" is always offered and writes nothing.
- Every other findings-conditioned unit stays `NOT_LEAN`.
- `STRUCTURE_VERSION` is bumped, so stored parses refresh.
- The Rules step's ledger gets a fourth kind, `habit`:
  - key: `paragraph :: condition`;
  - choice: `ask` / `state` / `removed`.
  - `state` renders the NEGATIVE form, and `ask` renders the RULE form.

## Scratchpad

1. **Trigger.** At the `gateReview` hook, one Jev call carries one `noul` question per distinct condition: "Does
   the dictation report <condition>?". The threshold is the same as for the other checks. An answered row stays
   answered while the dictation changes, until its condition stops being met.
2. **Rows.**
   - A met required statement joins that paragraph-region's assumed tray (`data-state="assumed"`). It can be
     confirmed or removed like any assumed normal.
   - A met habit question becomes an `Item` with kind `template`. It is shown in the region under the dictated
     sentence that met the condition, with the buttons Yes / No / Not assessed.
   - Template rows are ranked before generic finding rows in `_limit`. Referral rows are still never capped.
3. **Already answered.** Before showing a question, the existing stated check (`ask_checks` shape) asks whether
   the dictation already states its YES or NO sentence. If so, the row is folded as answered.
4. **Generate.** A chosen YES/NO sentence is an "Answered by the radiologist:" statement in the findings block.
   A confirmed required statement is an assumed line, as today. Removed sentences arrive as DO NOT ASSERT. The
   generator needs no change.

## Failure behaviour

| Failure | Behaviour |
|---|---|
| Jev trigger call fails | no template rows; generic rows as today; logged |
| Stated check fails | rows shown unfolded |
| Sheet without habits | no change |
| Grammar lint rejects a habit at save | the habit is not saved; it shows as a card at next review (Rules-step rule) |

## Lab first (reported; Hassan decides)

Synthetic data seeded from production: Opus subagents generate it into
`~/Code/rr-template-conversion-private/synthetic/triggered_rows/`, with the ground truth planted.
- **Proposal lab:**
  - example-report sets for 6 templates, with planted habits (in ≥2 of N, in 1 of N, or absent);
  - measure the decision run's habit proposals: precision, recall, and quotes verified.
- **Trigger lab:**
  - hand-written triggers on 5 templates;
  - about 60 dictations per trigger kind: met, not met, negated, hedged, the finding in another region, two
    findings;
  - measure Jev trigger accuracy, already-answered accuracy, and template rows per session against the caps,
    i.e. how often a generic row is pushed out.
- Real production dictations are run separately, as a held-out set.

## Build order

1. Grammar forms, renderer round trip, and the ledger kind `habit`. Lands with or after the Rules step's phase 1.
2. The lab.
3. The decision-run proposal and the Rules-step card ("When <condition>: Ask every time / Always state / Not
   needed", with quotes).
4. Scratchpad trigger, rows and ranking, plus the Generate wiring.
5. Chat add and remove through the router (a new `habit` tag kind).

## Testing

- **Unit:**
  - the grammar forms parse, and other findings forms are still `NOT_LEAN`;
  - the renderer round-trips;
  - ledger `habit` apply;
  - trigger to row mapping;
  - ranking under the caps;
  - already-answered folding;
  - Generate statements.
- **Frontend:**
  - the template row's buttons write the sentence;
  - "Not assessed" writes nothing;
  - the required statement sits in the assumed tray;
  - the gate key includes template rows.
