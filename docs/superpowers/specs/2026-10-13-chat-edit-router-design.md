# Chat-to-edit: the edit router — design

Date: 2026-10-13. Status: agreed in conversation with Hassan; not built. Builds on the Rules step
(`2026-10-13-template-rules-step-design.md`): it reuses that spec's ledger operations and one-tap cards. Build after
the Rules step.

## Aim

A chat instruction that changes a template's rules is applied by code, the same way a card tap is; a change of style
or wording is applied by a lightweight model that can only touch prose. No model rewrites the whole sheet, so a
small instruction cannot break unrelated lines, and confirmed decisions stay as confirmed.

## Today

`/skill-sheet/refine` (`main.skill_sheet_refine_endpoint`) sends the whole sheet, the instruction and the chat
history to `TemplateManager.refine_skill_sheet` (Cerebras), which returns a rewritten sheet, a reply and a
`behavioral_claim` (the change it says it made; the panel's verification loop lets the radiologist reject it, and a
rejected claim comes back as `rejection_context`). The save function then vets the rewrite (origin "chat"):
refused → previous sheet kept; unchanged → "No change was needed." unless the reply asks a question; adjusted →
saved with a notice. Each turn is stored (`template_chat_turns.record_turn`). Failure modes: the rewrite touches
lines the instruction never mentioned; a rule ends up as prose; repeated refusals → repair loops.

## Flow

1. **Tag (Jev).** One Jev call on the whole instruction (with the last assistant turn for context), one yes/no
   per kind of change. No splitting: a mixed instruction ("drop ECV and make the impression more concise") is
   several yeses.

   | Key | Question (noul) |
   |---|---|
   | value | Does this ask to change which values every report must state? |
   | concept | Does this ask to change how comparison / prior imaging, contrast, sequences not acquired or a technical limitation is worded? |
   | fixed | Does this ask to change a sentence printed in every report? |
   | normal | Does this ask to change how a normal finding for a region is worded, or whether it is stated? |
   | layout | Does this ask to add, remove, rename or reorder a section or paragraph? |
   | style | Does this ask to change style, tone, length or phrasing? |
   | misfit | Does this ask for something that does not belong in a report of this scan type? |

   Threshold 0.5 as elsewhere. No yes, or misfit yes → no change; the reply asks what was meant (with the scan
   type), as the current refine does when an instruction may not fit.

2. **Targeted calls (one per yes, in parallel).** Each lightweight call reads the whole instruction, is told it
   handles only its own kind and to ignore the rest, and gets only the part of the sheet it needs (the value list;
   the concept's lines; the fixed lines; the region's normals; the section list; for style, the prose blocks).

   - **Rule kinds (value, concept, fixed, normal, layout)** return a structured change, never sheet text, e.g.
     `{"change": "value", "name": "ECV", "to": "not_needed"}`,
     `{"change": "concept", "concept": "comparison", "prior_text": "Compared with the {study} of {date}."}`,
     `{"change": "normal", "region": "Liver", "structure": "liver", "to": "removed"}`.
     Code validates: the target exists (or, for a new value, the name is a short noun phrase); any new wording
     appears in the instruction word for word, or is marked as proposed wording; slots only from the allowed set.
     Valid → applied by the Rules step's ledger operations (source "chat"), which edit the parsed structure and
     re-render. Layout changes use the same structure operations on SECTION / paragraph headings.
   - **Style** returns edited prose blocks only. Code rejects the result if any unit line differs from the input.

3. **Rule-in-disguise check.** After a style edit, one Jev call per new or changed prose line: "Does this line
   require the report to state something?" A yes is not applied as prose: it is sent back through the rule route
   (normal or fixed), or shown as a card if no rule kind fits.

4. **Save.** The save function vets the result (origin "chat") and applies the ledger last, as on every save.

5. **Reply.** Plain report-behaviour language, one line per applied change ("ECV is no longer required." "The
   impression is now shorter: …"). A change to a confirmed item says "This changes something you confirmed:
   <item> <old> → <new>". The `behavioral_claim` / rejection loop stays: a rejected change is undone by reversing its
   ledger entry (rule kinds) or restoring the previous prose (style).

## Uncertain or rejected changes become cards

A tag between 0.35 and 0.5, a targeted call that is unsure, proposed wording not in the instruction, or a structured
change code rejects: nothing is applied for that part; the reply shows the same one-tap card the Rules step uses,
prefilled ("Make ECV: Every report / Only when relevant / Not needed"). Other parts of the same instruction that
were clear are applied.

## Failure behaviour

| Failure | Behaviour |
|---|---|
| Jev tag call fails | fall back to today's refine path (whole-sheet rewrite + vet) for this turn; logged |
| A targeted call fails | that part not applied; reply says so for that part; other parts applied |
| Style output changed a unit line | style part rejected; reply asks to rephrase |
| Save function refuses | previous sheet kept, as today |

The fallback to today's path is removed once the router's lab and live data show it is not needed.

## Evidence

Each turn is stored as today (scrubbed), plus the tags, the structured changes, which were applied or carded, and
the rule-in-disguise results, so routing accuracy can be measured from production.

## Testing

- Unit: tag → targeted-call fan-out; each structured change validated and applied through the ledger operations;
  style output with a changed unit line rejected; rule-in-disguise re-route; partial apply of a mixed instruction;
  card fallback; rejection undo for both routes; Jev failure → today's path.
- Labs (reported, Hassan decides; synthetic data per `feedback_synthetic_labs`):
  - **Tagging:** stored refine chat turns from production plus Opus-generated instructions seeded from them and from
    the 31 templates, with planted labels: single-kind, mixed (2–3 kinds), rules disguised as style ("always mention
    the pericardium"), misfit instructions, vague instructions. Measure Jev precision/recall per kind.
  - **Targeted calls:** structured-change accuracy per kind against the planted truth; how often code rejects; how
    often proposed wording is invented.
  - **End to end:** sheets after a scripted sequence of mixed instructions vs the expected sheet; unrelated lines
    changed (target 0 by construction for rule kinds).

## Measuring after launch

Refine turns per template, share of turns applied without a card, cards shown and how they were answered, rejected
claims (the verification loop) per route, and repeat instructions for the same change (a repair-loop signal),
compared with the whole-sheet rewrite era.
