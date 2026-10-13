# Template integration: rollout and handover (2026-10-14)

Branch: `feat/template-integration`, worktree `.claude/worktrees/integration`. It contains:
- `feat/template-stack`;
- items 1, 1b, 2, 3 and 5 (Phases 1–4);
- the chat-edit router, which ships **dark**.

Nothing is pushed. Merge, push and deploy happen only on Hassan's go-ahead.

## What ships

| Item | Branch (built and reviewed) | Spec |
|---|---|---|
| Template pipeline (grammar sheets, upgrade script, banner) | feat/template-stack | 2026-10-12-template-pipeline-design.md |
| 1 + 1b: context rules resolved by Jev before Generate; kept defaults word for word; scan type; shared condition state | feat/context-rules | 2026-10-13-context-rules-resolved-design.md, …-kept-defaults-design.md |
| 2: value chips (number→item fill, picks, typed values only stated, "Values not provided", post-gen backstop) | feat/value-cluster | 2026-10-12-template-requirements-design.md part 1 |
| 3: Rules step (decision ledger, decision run with study setup first, cards, writer at 0.4, Style checks) | feat/rules-step | 2026-10-13-template-rules-step-design.md |
| 5: findings-triggered habit rows (Phases 1–4; trigger wording B1 at 0.5, stated findings only) | feat/triggered-rows | 2026-10-13-findings-triggered-rows-design.md |
| 4: chat-edit router, hybrid propose-verify-apply (**dark**) | feat/chat-router | 2026-10-13-chat-edit-router-design.md |

Every branch had independent reviews per phase and whole-branch, and every finding was fixed. The integration itself is reviewed below.

## Deploy order

1. **Migrations run first, before the new code serves traffic.** Production's Alembic head is `20261005120000`. The new ones are:
   - `20261013090000_template_evidence`, which adds the template_chat_turns table;
   - `20261014090000`, the router's `routing` column.
2. **Environment:**
   - leave `RR_CHAT_ROUTER` **unset** (the router stays off and chat uses today's refine);
   - no other new flags.
3. **Upgrade script, straight after deploy** (legacy guided templates can't be chat-edited until it has run):
   - `railway run .venv/bin/python -m rapid_reports_ai.scripts.template_upgrade_apply <manifest.json>`. This is a dry run: it writes nothing, but it vets every sheet through the save function, which makes paid LLM calls.
   - Show Hassan the per-template result, then re-run with `--apply` on his yes.
   - A JSON backup is written next to the manifest first.
   - The manifest is `~/Code/rr-template-conversion-private/manifest.json`: 31 templates, unchanged since the 2026-10-12 pull and all guided; 16 legacy ids from 4 owners. Rebuild it with `build_manifest.py` (PYTHONPATH=src from a backend/) if anything changes.
   - The rebuilt cardiac_mr_2 sheet now names "Left/Right atrium area".
4. **Metabase SQL:** `docs/analytics/metabase/trace_and_quality.sql` (Q8/Q9a path).
5. **Smoke test:** create a template from 3 examples and go through the Rules and Style steps; refine twice; a scratchpad session with value chips and a habit row; Generate. Check the generation stamp, the gate fields and the stored example row.

## Browser checks not yet done (do them in the smoke, or right after)

- **Value chips:** fill and pick; "stated?"; Mark N not provided; Confirm blocking; the N/A line in the report; the `value_missing` flag reaches the review rail (unconfirmed).
- **Rules step:** the cards, including contrast "usual"; More groups; setup evidence; Skip; failure fallback. **Style step:** Always printed, the normal report editor, may-be-stated-twice.
- **Habit rows:** a proposed habit card; an ask row in the scratchpad; Yes / No / Not assessed; hedged or negated findings show no row; "state" habits in the assumed tray.

## Router (dark): where it stands

- **Design:** the hybrid, adopted on the consultant's advice. One Qwen call proposes typed changes; Jev verifies each claim against the instruction, and each style edit against its claim; code applies what is verified, and anything else becomes a card. A screen call checks habit, undo and misfit first. Undo is server-bound and signed.
- **Provisional held-out numbers** (one run, not adjudicated), per 100 turns:

  | | today's refine | old router | hybrid |
  |---|---|---|---|
  | unrequested changes | 181 | 34 | 19 |
  | correct changes | 60/91 | 46/98 | 36/98 |

  The hybrid also resolved 45% of requests in one turn. Its recall is too low to switch on.
- **Next session:**
  1. Put the habit-screen wording W3 in: held-out P 1.0 / R 1.0 against 0.32 today. The text is in `synthetic/chat_router/habit_wording_round.json`.
  2. Re-run the 3-arm lab: two runs, adjudicated.
  3. Judge against Hassan's switch-on numbers: ≤ 5 unrequested per 100; resolved in one turn ≥ 80%; applied without a card ≥ 55%; cards per turn ≤ 0.6; p50/p90 ≤ 6/12 s; habit false parks ≤ 5%.
- **Screen scores so far:** undo P .70 / R 1.0; misfit P .75 / R .75 on held-out.
- **Item 5 Phase 5** (chat adds and removes habits) waits for the router.

## Follow-ups

- **Repo hygiene:** a `backend/.venv` symlink committed in d71d377b (on origin/feat/hybrid-stack) should be removed; there is a stray `backend/uv.lock`.
- **Shared venv:** its editable install points at a worktree. Run any script outside pytest with `PYTHONPATH=src`.
- **Carried over:** E1b M5/M7; `/options` returns no artifacts for "skipped"; "abandoned" capture is incomplete.
- **Worktrees to remove after the merge:** hybrid-stack, context-rules, context-rules-fix, value-cluster, value-cluster-lab, rules-step, rules-step-lab, chat-router, chat-router-lab, triggered-rows, triggered-rows-lab.
- **Hassan's spot-checks, still open:** `synthetic/rules_step/REALISM_REVIEW.md`, `ANSWERS_SPOTCHECK.md`.
- **Labs and private data:** `~/Code/rr-template-conversion-private/synthetic/{value_cluster,rules_step,triggered_rows,chat_router}/`.
