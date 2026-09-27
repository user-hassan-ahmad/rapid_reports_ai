# Plan — racing with a lean scoped polish, plus four small fixes (2026-09-27)

**Why:** replays 1–4 (2026-09-26/27, lab logs): a scoped polish rewrites one span instead of the whole scratchpad; with a lean prompt (1.4k chars vs 4.8k) it answers in p50 268 ms, so it can be fired *together with* the Jev bundle. Polish-routed lines then land at p50 ~272 ms instead of ~650 ms (Jev, then polish), and total prompt volume is about half of today even with a polish on every line. Jev still decides every route; nothing about routing, questions or thresholds changes except the gate below. The lean prompt was written after seeing those sessions, so it is judged on fresh ones, behind a lab switch.

Production unchanged: every new path is lab only (`RR_TRIAGE_DEBUG=1` and the lab's decision-first front door).

## Tasks (TDD, one commit each)

1. **Gate 0.70 → 0.80**, QSET `2026-09-27.1` (gate sweep: 6/6 vs 5/6 misheard caught on Jev-confident appends; clean lines sent to polish 31 % vs 19 %).
2. **Polish token logging:** `_run_canvas_with_fallback` reports usage; `canvas.process` logs input/output tokens; lab responses carry them so decision records and the summary show cost next to call counts.
3. **Jev endpoint setting:** `RR_JEV_ROUTE=direct` sends to `api.typesafe.ai/v1/systemone` with `JEV_API_KEY` and model `jev-1.13.0`; default stays OpenRouter (direct ~25 ms faster at p50, same answers; governance decision pending).
4. **Capital after a disc level or heading:** "L4/5 there is" → "L4/5 There is", "Conclusion: acute" → "Conclusion: Acute".
5. **Lean scoped polish endpoint:** `POST /api/canvas/polish-span` (lab only): {context, span, new} → {active_scratchpad, committed_edits, usage, latency}. Code-decided utterances return `skipped` without a model call. Prompt in `lean_polish.py`.
6. **Racing in the scratchpad:** lab switch `polish: full | race` (Verbatim mode only; Structured keeps the full polish). On each non-trivial final the bundle and the lean polish fire together on the same solid text; code chooses the span (last two sentences, current paragraph as context).
   - fast_append / command / skip → as today; the lean result is discarded.
   - polish (and Jev error) → apply the lean result to [span start, end of this final's faded text], plus `committed_edits` found verbatim once; undo restores the span.
   - fall back to today's full polish when the lean call failed or was skipped, when the span changed underneath it, or when a full polish is already queued or running.
   - records carry `polish_kind` (full | lean), polish time and tokens.
7. **Panel + summary:** route rows show the polish kind; summary reports polish latency per kind and token totals.
8. **Docs:** work order and handover (how to switch it on, what to watch).

## Judging it (fresh sessions only)

Per session, with the existing summary + a correction check: polish-routed time to final text by kind; token totals vs the full polish; undo / edit rate on lean-polished lines vs full-polished; every correction utterance reviewed (the lean prompt's known failures: "Sorry that's the right kidney" not applied; a misheard correction rewriting a finding).
