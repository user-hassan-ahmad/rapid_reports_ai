# Instruction flag (fidelity track step 2, Q4) — design note

2026-10-15. Approved by Hassan. Flag `RR_STACK_INSTRUCTION_FLAG` (off by default).

## Problem

P3: "Delete all the other sections." matched no voice command, so it was written as dictation, confirmed as the
conclusion and obeyed by the writer, which collapsed the report.

## Decision

An utterance that is an instruction to the software (not report content) but matches no supported command is never
written and never obeyed. It is held and shown as a flag: "This sounded like an instruction, not report text."
with **Keep as text** and **Remove**. Nothing is dropped silently. Fail open: below the bar, flag off, or any error,
the utterance is dictation (today).

## Design

1. **One more option in the existing stack command question** (`hybrid_stack/jev_stack.py` `COMMAND_QUESTION`),
   asked only when the flag is on. Same Jev call, same latency; no regex. The option is `instruction`. `decide_command`
   keeps its order: accept, then a delete that names a region. It then holds when P(instruction) + P(delete) >=
   `INSTRUCTION_MIN`. P(delete) counts because the scratchpad acts on a stack delete only when it names a region. In
   the lab, removals such as "Delete all the other sections." split between delete and instruction (P3 was delete
   0.50-0.66). The bar is chosen by Hassan from the lab.
2. **The bundle route returns it.** `stack_command.action == "instruction"` (canvas `/bundle`), with the score. It is
   returned only when the bundle would write the words (fast_append or polish). A code-decided delete, skip or
   command stands unflagged.
3. **The held utterance is kept outside the verbatim text.** The scratchpad removes the words from the pending range,
   as it does for the other voice commands, and keeps them in a held list shown as a card above the findings. Every
   writer input (units, findings block, draft, gate conclusion text) is built from the verbatim text. A held
   utterance therefore cannot reach the writer or the conclusion until **Keep as text** appends it as dictation.
   **Remove** discards it. The hold is logged as a decision (`stack_instruction`), and the server logs the score.
   *Why not a `held` field on StackUnit:* the findings builder is a byte-identical port of the frontend builder
   (golden fixture). A unit flag would have to be honoured in five places (findings block, findings text, draft,
   gate hash, conclusion). Keeping the text out covers them all by construction.
4. **The conclusion path.** A final dictated while the conclusion draft or a line is open (`dictateIntoEdit`) is
   held the same way, so confirmed conclusion text cannot carry one. The AI draft is built from units, so it cannot
   carry one either. Typed text is the radiologist's own and is not checked.

## Out of scope

Quick triage (`jev_questions.py`, `fast_append.py`) is unchanged. The walkthrough voice answer
(`feat/scratchpad-declutter-voice`) uses its own route and is not touched.

## Lab

The lab uses synthetic, Opus-written fixtures: 60 instructions and 60 report sentences that sound like instructions.
For each bar it reports the report content wrongly held (the hazard) and the instructions caught. The existing
96-item command fixture is re-run with the option on, to check that dictate, delete and accept do not regress.

## Lab result (2026-10-15, 2 runs of the final rule)

| bar | report sentences wrongly held (of 60) | instructions held (of 60) |
|---|---|---|
| 0.60 | 4, 4 | 57, 57 |
| 0.80 | 1, 0 | 57, 57 |
| **0.85** | **0, 0** | **57, 57** |
| 0.90 | 0, 0 | 55, 56 |
| 0.95 | 0, 0 | 49, 49 |

The highest-scoring report sentences were 0.78-0.82 ("Please see the separate report for the abdomen.", "The previous
report was reviewed.", "Report phoned to the stroke team."). Three instructions were missed in both runs: "Back to
the kidneys.", "Go back to the liver." and "Add the standard normals.". On the 96-item command fixture, no
dictation was held at any bar >= 0.6, and accept and region deletes did not change. Seven region-less deletes are
held at 0.85 ("Delete the liver line.", "Remove the last sentence."). Today the scratchpad does not act on these, so
they go to the bundle's route. Bare "delete that" and "scratch that" are decided by code and never asked.
