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
   keeps its order (accept, then delete), then holds when P(instruction) >= `INSTRUCTION_MIN`. The bar is chosen by
   Hassan from the lab.
2. **The bundle route returns it.** `stack_command.action == "instruction"` (canvas `/bundle`), with the score.
3. **The held utterance is kept outside the verbatim text.** The scratchpad removes the words from the pending range,
   as it does for the other voice commands, and keeps them in a held list shown as a card above the findings. Every
   writer input (units, findings block, draft, gate conclusion text) is built from the verbatim text. A held
   utterance therefore cannot reach the writer or the conclusion until **Keep as text** appends it as dictation.
   **Remove** discards it. The decision is logged either way.
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
