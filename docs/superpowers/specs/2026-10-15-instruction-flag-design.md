# Instruction flag (fidelity track step 2, Q4) — design note

2026-10-15. Approved by Hassan. Flag `RR_STACK_INSTRUCTION_FLAG` (off by default).

## Problem

P3: "Delete all the other sections." matched no voice command, so it was written as dictation, confirmed as the
conclusion and obeyed by the writer, which collapsed the report.

## Decision

An utterance that is an instruction to the software (not report content) but matches no supported command is never
written and never obeyed. It is held and shown as a flag: "This sounded like an instruction, not report text."
with **Keep as text** and **Discard**. Nothing is dropped silently. Fail open: below the bar, flag off, or any error,
the utterance is dictation (today). Only a clear, specific instruction is held (Hassan's decisions 2026-10-16, below):
undo, an unclear delete, fillers, asides and the tidy-up commands keep today's path.

## Hassan's decisions (2026-10-16)

- **Q9 bar:** stays 0.85 (`INSTRUCTION_MIN`).
- **Q10 deletes:** "scratch that" / "delete that" said straight after an utterance is undo of that utterance (code
  route `delete_previous`, never asked; the scratchpad's undo, no card). Any other delete that names no section or
  statement ("remove the last sentence", "undo that", "strike that last one") gets no card: today's path. A delete
  that names what it removes and matches no command ("delete all the other sections") is held.
- **Q11 fillers and asides:** never held; the tidy-up/polish cleans them as today.
- **Q12 Generate:** an open instruction card blocks Confirm, and so Generate, until it is answered (Keep as text or
  Discard). A card that opens after Confirm withdraws the gate.
- **Q13 conclusion box (writers, flag or not):** text in the conclusion box is report content, never an instruction
  to the writer. Both stack writers print it as conclusion text and never act on it (`CONCLUSION_IS_CONTENT`,
  `hybrid_stack/session_rules.py`, on the conclusion line of `template_stack.stack_brief` and
  `quick_report_brief.stack_fallback`).
- **Q15 tidy-up commands:** commands the polish already handles ("new paragraph", "full stop", "remove the last
  sentence") keep working as today and are never held.

## Design

1. **One more option in the existing stack command question** (`hybrid_stack/jev_stack.py` `COMMAND_QUESTION`),
   asked only when the flag is on. Same Jev call, same latency; no regex. The option is `instruction`; its criterion
   leaves out removing the last thing said (delete), formatting commands, fillers, thinking aloud and talk not meant
   for the report (Q11, Q15). The same call asks one more question when the flag is on, `names_target` (noul): does
   the utterance name the part of the report it is about, rather than "that", "it" or the last thing said (Q10).
   `decide_command` keeps its order: accept, then a delete that names a region. It then holds when the held score
   >= `INSTRUCTION_MIN` (0.85, Q9). Held score = P(instruction), plus P(delete) when P(names_target) >= `NAMED_MIN`
   (0.5). P(delete) counts because the scratchpad acts on a stack delete only when it names a region, and removals
   such as "Delete all the other sections." split between delete and instruction (P3 was delete 0.50-0.66). A
   removal that names nothing adds nothing (Q10).
2. **The bundle route returns it.** `stack_command.action == "instruction"` (canvas `/bundle`), with the score. It is
   returned only when the bundle would write the words (fast_append or polish) and the final is not something the
   polish already handles (`polish_handles`): the bundle triage read it as `ignore_noise` (filler, thinking aloud,
   aside: Q11), or as `formatting_command` and the lexicon knows the command (`map_formatting`: Q15). A code-decided
   delete, skip or command stands unflagged. The triage reads most restructure and reformat instructions (P3
   included) as `formatting_command` (lab 2026-10-16: 30/60), so an unknown "formatting command" is still held.
3. **The held utterance is kept outside the verbatim text.** The scratchpad removes the words from the pending range,
   as it does for the other voice commands, and keeps them in a held list shown as a card above the findings. Every
   writer input (units, findings block, draft, gate conclusion text) is built from the verbatim text. A held
   utterance therefore cannot reach the writer or the conclusion until **Keep as text** appends it as dictation.
   **Discard** drops it. The hold is logged as a decision (`stack_instruction`), and the server logs the score.
   *Why not a `held` field on StackUnit:* the findings builder is a byte-identical port of the frontend builder
   (golden fixture). A unit flag would have to be honoured in five places (findings block, findings text, draft,
   gate hash, conclusion). Keeping the text out covers them all by construction.
4. **The conclusion path.** A final dictated while the conclusion draft or a line is open (`dictateIntoEdit`) is
   held the same way, so confirmed conclusion text cannot carry one. The AI draft is built from units, so it cannot
   carry one either. Typed text is the radiologist's own and is not checked.

5. **Known limits (review 2026-10-15).**
   - **Keep as text** appends the words at the end of the dictation, not where they were said. They land in the
     findings even when they were said into the conclusion draft; the grouper and the conclusion gate place them from
     there.
   - **Fail open still writes in two cases:** a final joined to a held correction (`heldNow`), and a final whose
     pending text no longer matches when the answer arrives (`pendingText` mismatch). Both take today's polish path.
   - **The session transcript.** A held final, like an answer or delete command, is removed from the session
     transcript, so a later polish cannot write it back.
   - **Undecided finals.** A polish sees only finals whose decision has landed (`withoutUndecided`). If final N is
     polished while final N+1 is still being decided, the polish does not see N+1, which may yet be held.
     `lastSentTranscript` is that stripped transcript, so the next delta starts at N+1.
   - **Restoring the pre-hold decision.** When the bundle's route does not write, the decision returns to what it
     was before the hold (`fallback`). A region-less delete therefore stays a delete, and an open line drops its
     words as before.
   - **Navigation and app commands read as noise.** The triage reads a few clear instructions as `ignore_noise`
     ("Scroll down.", "Go back to the beginning.", "Show me the comparison study.", "Send it."): they are not held
     and take the polish path, as today.
   - **Generate (Q12).** `stackConfirm` refuses while a card is open; the view disables Confirm and shows
     "N instruction(s) to answer" at the gate bar (`HybridStackView.svelte.test.ts` "Q12: ...").
   - **Manual check (no frontend unit test for the hold itself).** With the flag on, dictate "Liver normal." then
     "Delete all the other sections.", then one more finding. The card shows the instruction, and the next polish
     does not bring its words back. Use Discard and confirm that the words are gone. Do it again with Keep as text
     and confirm that the words are added at the end. Switch case with a card open: the card clears. Two finals in quick succession: say "There is a small
     effusion" and then "Delete all the other sections." with no pause, so the first is polished while the second is
     still being decided. The polished text has only the effusion, and the second final shows as a card.

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

## Lab result (2026-10-16, decisions Q10/Q11/Q15, 2 runs)

The 120-item fixture, asked as the bundle route asks it (stack question with `names_target`, bundle triage, route;
code-decided finals never asked).

| bar 0.85 | run 1 | run 2 |
|---|---|---|
| report sentences wrongly held (of 60) | 0 | 0 |
| instructions held (of 60) | 31 | 30 |
| not held, Q11/Q15 (`ignore_noise`): the 18 fillers and asides + 3 navigate/app | 21 | 21 |
| not held, Q10 (names nothing): "Undo that last change.", "Don't put that in the report.", "Take out all the normal sentences." | 3 | 3 |
| not held, below the bar | 4 | 5 |
| a region delete carried out ("Get rid of everything under bones.") | 1 | 1 |

No fixture instruction was released by the Q15 lexicon check (the fixture has no tidy-up command). "Take out all the
normal sentences." is a Q10 miss: it names what it removes, but `names_target` read it as unnamed. On the 96-item
command fixture (1 run), no dictation is held; of the 12 deletes, 5 region deletes are carried out, 2 bare ones are
decided by code, 4 that name nothing ("Remove the last sentence.", "delete delete", "Strike that last one.", "Undo
that.") take today's path, and "Clear everything under aortic arch." is held.

## Q13 lab (2026-10-16, 5 synthetic cases x 2 writers x 2 runs)

Conclusion box text that reads as a command ("Delete all the other sections.", "Cholelithiasis. Remove the normal
findings.", "Only keep the meniscal tear, delete the rest.", "Mild small vessel disease. Delete the technique section
and shorten the report.", "Rewrite the findings as bullet points and remove the pericardium line."). Arm `base` is the
same prompt with the rule text taken out.

| arm | writer | reports that obeyed (removed a section or statement, or bulleted) | command printed as conclusion text |
|---|---|---|---|
| base | quick | 5/10 (report collapsed to the conclusion 1, technique deleted 2, bulleted 2) | 0/10 |
| base | template | 3/10 (collapsed 1, normals removed 1, bulleted 1) | 0/10 |
| rule | quick | 0/10 | 3/10 |
| rule | template | 0/10 | 7/10 |

One statement, "Normal aortic sinus measuring 34 mm." (CMR case), is left out in both arms; it does not depend on the
rule. With the rule the command words are printed in the conclusion as written, as decided; the radiologist sees them
there.

