# Context rules: kept defaults are written word for word — design (item 1b)

Date: 2026-10-13. Status: draft for Hassan's approval. Follow-on to `2026-10-13-context-rules-resolved-design.md`
(item 1), on `feat/context-rules`.

## Problem

The item 1 lab (`final/E2E_CONTEXT_RULES.md`, ct_trauma_polytrauma) shows the problem.
- The case is a garbled no-prior dictation with a bare date: "no previous … no comparison … 02/12/2025".
- Jev correctly judged "the dictation names a previous imaging study" not met (0.23).
- So code kept the default FIXED line, "No previous imaging available for comparison.".
- The scratchpad report still printed "Previous CT 02/12/2025; no comparison made.".

The generator rewrote the kept default using the stray date. The stack prompt's FIXED rule tells it to "adapt the
line's values" where the input gives different values (`template_stack.stack_brief`, "Fixed lines"). For a line
whose wording a rule already decided, that adaptation undoes the decision.

## Change

Jev decides, code applies, and the generator writes the decided line as it stands.

1. **Record kept defaults.** `apply_rules` also records the target text of each REPLACE or SUPPRESS rule that is
   not met, matched and applied, and whose target is a FIXED line. These are the "kept defaults".
   - USE rules have no default.
   - NORMAL/NEGATIVE targets are not FIXED lines, and the stack brief strips them anyway.
   - Rules left on stack (`left_stack`) and unmatched or conflicting rules are excluded: no decision was made for
     them.
2. **Tell the generator.** The decided block gains a second list, "Write word for word", holding the kept
   defaults. Its instruction: the template's rules decided this line for this case; write it exactly as it stands,
   in its place, and do not change, merge or add values.
   - The block is now emitted when either list is non-empty.
   - The existing slot list and its instruction are unchanged.
3. **Prompt exception.** The stack prompt's Fixed-lines rule already names Decided for This Case as an exception.
   No further wording change is needed beyond the block's own instruction.

Not changed:
- FIXED lines that no context rule targets keep today's adapt-to-input rule. That rule is how "with contrast"
  becomes "without contrast" when dictated.
- The straight-dictation path gets the same block. It reads the same sheet text.

## Failure behaviour

None new. The block is text built by code, and everything is fail-soft through `resolve_context_rules` as in
item 1.

## Testing

- **Unit:**
  - a not-met REPLACE on a FIXED target is recorded as kept, and appears under "Write word for word";
  - a met rule, a USE rule, a `left_stack` rule and an unmatched rule are never recorded as kept;
  - the block is emitted with only kept defaults present.
- **Lab:** re-run the after arm on ct_trauma_polytrauma (3 runs, since generation is stochastic) and on 4 other
  no-prior cases. Report the comparison line printed. Expected: the default verbatim, and no date merged in.
