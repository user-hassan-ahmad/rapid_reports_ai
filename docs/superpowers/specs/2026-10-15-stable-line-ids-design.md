# Stable sheet-line IDs and the normals confirm record: design

Date: 2026-10-15. Slice 2 of "Build your template" (spec doc "RadFlow: Build Your Template", section *Review and decisions*, build order step 2). Status: revised after independent review (round 1: not ready, 11 findings; all addressed below).

## Why

Every later slice keys on a sheet line: card answers, deferred items, normal confirms, uncertainty scoring, provenance. Today no line has a stable identity:

- Parsed units get positional IDs (`p1`, `r3`, `n7`, `m2`, `f1`) on every parse (`template_sheet_grammar.py:488-545`); any insert or delete shifts them.
- Ledger keys are names and text (`template_decisions.py:144-176`): `paragraph :: structure` for normals, the quoted text for negatives and FIXED lines, `paragraph :: condition` for habits. A renamed paragraph, a reworded negative or a reworded condition orphans the entry.
- `apply_ledger` finds lines by exact raw text (`template_ledger_apply.py:74`); orphans stay in the ledger and come back as cards (`template_rules_cards.py:182`).
- So a rebuild (the writer rewrites the whole sheet) loses answers whose line text moved. That is the "add more reports and rebuild" path the new flow depends on.

The 2026-10-13 Rules-step spec asked for "stable keys only… no free-text matching" (`2026-10-13-template-rules-step-design.md:72-77`); the code never got there.

## Scope

In:

1. A line registry: a stable `uid` per line-bound sheet unit, kept across persisted edits, stored beside the sheet.
2. Ledger entries carry the `uid`; resolution is uid first, today's key matching second.
3. A normals confirm record (decision 5), server-written, with staleness.
4. The writer names a sheet line for each uncertainty; code resolves it to a `uid` at Create.
5. Reports and confirms record a stable sheet revision.

Out: any UI (slice 3); NORMAL behaviours other than today's rule (decision 6, separate lab); Generate and provenance; report-time row IDs (`hybrid_stack/items.py:175`); uncertainty scoring (slice 4); deleting the legacy analyser at `template_manager.py:3311` (still used by `scripts/template_e2e_lab.py:327` and three tests; separate cleanup).

Not line-bound, unchanged: value entries (keyed by value name; Always / If dictated / Leave out map onto `need: every | relevant | not_needed`, `template_decisions.py:7-9`) and concept entries (comparison, contrast, sequences, limitation). TERM lines get no uid (no ledger kind uses them; the parser gives them no id).

## Decision: a sidecar registry, not IDs in the sheet text

IDs written into the sheet (`… {#n_k3f9qa}`) would be dropped, copied or invented by every LLM whole-sheet rewrite (chat fallback, rebuild), and would have to be stripped from every prompt the sheet reaches. A sidecar registry leaves the sheet text exactly as today; identity lives in `template_config["line_registry"]` and is re-bound by code on every persisted save.

## Identity: what a uid stands for

A uid names a **slot** in the template, not a string. What defines the slot depends on the kind; text that is not part of the identity can change without changing the uid, and that change is tracked separately (`text_hash`) where it matters for safety.

| Kind | Identity (all must match) | Text in identity? |
| --- | --- | --- |
| section | normalised name | n/a |
| paragraph | section uid + normalised name; or, for a rename, section uid + the **same non-empty** COVERS set, with the names passing the clinical gates | n/a |
| normal | paragraph uid + normalised structure | No. The normal's answer is its text (`_normal` rewrites the line), so text is tracked by `text_hash`, not identity |
| negative | paragraph uid + `condition` + `condition_source` + `kind` + `origin` + text | Yes (exact or cosmetic) |
| fixed | section uid + `paragraph` + text | Yes (exact or cosmetic) |
| rule (incl. LIST_MISSING, ASK) | section uid + paragraph uid (or none for section-level rules) + `effect` + `condition` + `condition_source` + `target` + `anchor` + `position` + output (`then_text`, `else_text`, `items`, `question`) | Yes: condition and every output field, exact or cosmetic |

Consequences, by design:

- A rule whose condition or output changes ("score > 0" → "score ≥ 100") is a new rule; the old answer resolves by key or becomes a card.
- Two SUPPRESS rules with the same condition but different targets are different rules.
- A conditional negative (`NEGATIVE "No free fluid." WHEN [findings: …]`) and the unconditional one with the same text are different units.
- Identical FIXED lines in two paragraphs are different units.

## Wrong matches are worse than lost answers

Carrying an answer to the wrong line is a clinical error; losing one costs a repeat question. Word-overlap similarity is unsafe ("No pleural effusion" / "No pericardial effusion", "left" / "right", "mild" / "moderate", "no evidence of" / "evidence of"). So there is **no similarity threshold**. A text field matches only if it is exactly equal after `norm_key`, or cosmetically equal:

1. **Tokenise first, normalise after.** Numbers (including decimals: `1.5` is one token, distinct from `15`), comparators (`<`, `>`, `≤`, `≥`, `=`, `±`, `+`, `/`, `%`) and units are split into their own tokens before anything else, and are never removed.
2. **Normalise:** lower case; collapse whitespace; drop sentence punctuation (`. , ; :` and quotes) only, never the tokens in step 1; map spelling with a fixed UK↔US lookup table (no suffix rules); remove a fixed list of filler phrases: "is seen", "is noted", "is identified", "is demonstrated", "there is", "there are".
3. **Compare every remaining token, in order.** No stopword removal: "with" / "without", "and" / "or" stay. Order is kept because reordering can swap laterality between structures ("left kidney, right adrenal").
4. **Hard gates, checked on the raw tokens, fail closed:** negation tokens (`no`, `not`, `without`, `absent`, `neither`, `nor`, `non-` prefix, `negative for`), laterality (`left`, `right`, `bilateral`, `unilateral`), severity grades (`minimal`, `mild`, `moderate`, `severe`, `marked`, `small`, `large`, grade and category numbers), numbers, comparators and units must be identical as multisets and in order.
5. When in doubt, a new uid. The filler list and spelling table are versioned constants with a collision test (no two distinct words map to the same form).

## The registry

```json
{
  "v": 1,
  "units": {
    "n_k3f9qa": {
      "kind": "normal",
      "identity": {"section": "s_8wq2mz", "paragraph": "p_2hd7vc", "structure": "lad"},
      "text": "LAD: Normal proximal, mid and distal LAD.",
      "text_hash": "sha256:9f2c…",
      "status": "live",
      "minted": "2026-10-15T10:02:11Z"
    }
  }
}
```

- `uid` = kind prefix (`s_ p_ n_ g_ f_ r_`) + 6 random base32 characters; minted once.
- `text_hash` = sha256 of the exact line text (no normalisation).
- `status`: `live` or `gone`. Gone units are kept, so a ledger entry pointing at one is visibly orphaned rather than silently rebound. A gone unit may be **revived only by an exact identity match** (restore, or a rebuild that brings the identical line back); never by cosmetic match.
- `minted` is written once. No per-save timestamps (they would churn the config).

## Rebind (pure code, no model)

`rebind(registry, structure, carried) -> (registry, report)`:

1. Inputs: the new parse, the previous registry, and `carried`, a map `{uid: new raw line}` returned by `apply_ledger` for every line it rewrote (below).
2. Carried units keep their uid unconditionally: the ledger rewrote that exact unit, so no re-matching.
3. For the rest, kind by kind in parent-first order (sections, paragraphs, then lines), pair new units with previous units: exact identity first, then cosmetic identity. Live units first; gone units only on exact identity (revival).
4. Pairs are 1:1. If a new unit has more than one candidate, or a previous unit is the candidate of more than one new unit, none of them pairs: each new unit gets a new uid and the event is logged `ambiguous`.
5. Unpaired new units get new uids; unpaired previous live units become `gone`.
6. Returns the registry and `report = {exact, cosmetic, carried, revived, new, gone, ambiguous}`.

Deterministic: same inputs, same result.

Reading uids: `uids_for(structure, registry)` is a pure function that maps each parsed unit to its uid by exact identity against live units. Consumers call it at read time; uids are not stored on the cached `sheet_structure`, because `_queue_structure` (`main.py:1791`) and the read path (`hybrid_stack/template.py:27`) re-parse independently.

## Where rebind runs: persisting paths only

Several endpoints are stateless: they return a sheet to the client and never write the database. They must never mint uids. A uid in a client-held ledger that the stored registry doesn't know is treated as no uid.

| Path | Persists? | Change |
| --- | --- | --- |
| `POST /api/templates` (`main.py:1814`) | Yes | rebind in `_vet_config`; resolve the writer's uncertain lines |
| `POST /skill-sheet/save` (`main.py:3111`) | Yes | rebind in `_vet_config`; resolve the writer's uncertain lines |
| `PUT /api/templates/{id}` (`main.py:1846`) | Yes | rebind in `_vet_config` against the **stored** registry |
| Restore (`main.py:2396`) | Yes | rebind the restored sheet against the **current** registry (not the snapshot's), exact revival allowed |
| `scripts/template_upgrade_apply.py:164` | Yes | rebind in `_vet_config` |
| `scripts/copy_template_to_user.py:60` | Yes | copies registry and ledger verbatim; uids stay valid within the copy (stated, no change) |
| Refine router / fallback (`main.py:2877`), `/refine/card` (`:3065`), `/refine/undo` (`:3031`), `/apply-decisions` (`:2912`), `template_writer.py:28` | No | no rebind, no minting |
| `store_structure` (`template_sheet_structure.py:1049`), `template_decision_run.py:470` | Writes `sheet_structure` / `rules_step` only | none |
| `scripts/audit_and_fix_organization_defaults.py:129` | Config write | check during planning whether it touches the sheet; if so, rebind |

`_vet_config` loads the stored registry, calls `vet_sheet`, then rebinds. `vet_sheet` gains no registry parameter; `apply_ledger` gains a returned `carried` map (`{uid: new raw line}`), computed by resolving each entry's uid before the edit.

`_carry_structure` (`main.py:1728`) treats `line_registry`, `uncertain` and `normal_confirms` as server-written, like `sheet_structure`: a client copy on PUT is ignored and the stored one kept.

## Ledger changes

- `clean_ledger` (`template_decisions.py:472`) keeps `uid` (it currently rebuilds entries from a fixed key list).
- Resolution in `apply_ledger`, per entry:
  1. `uid` known and live → the unit's current line; run the existing edit path on it.
  2. `uid` unknown, gone, or absent → today's key and text matching; on success, stamp the matched unit's uid.
  3. Otherwise unmatched, as today (card through `unmatched_cards`).
- **Removal decisions** (fixed `keep: remove`, normal `text: ""`) whose line is absent count as **satisfied**, not unmatched; they never become cards.
- A normal entry binds to the slot (paragraph uid + structure), so it survives a writer rewording and keeps rewriting the line to the radiologist's text.
- `reconcile_chat` (`template_ledger_apply.py:688`) re-stamps the uid of any entry it re-keys.
- When resolution keeps a uid on a line whose key label differs, the entry's `key` is updated to the new label and the change logged.
- `ledger_drift` stays a logged metric; the rebind `report` is logged beside it.

## The normals confirm record

Decision 5: normals are confirmed in small groups beside their sentences, each confirm recorded. Stored at `template_config["normal_confirms"]`, server-written only, through a dedicated endpoint (`POST /api/templates/{id}/normal-confirms`, used by slice 3). It is not a ledger kind: it changes no sheet text, and keeping it out of the client-held ledger means a client can't forge one.

```json
{
  "group": "p_2hd7vc",
  "label": "Coronary findings › Coronary arteries",
  "units": {"n_k3f9qa": "sha256:9f2c…", "g_b71xpd": "sha256:41d0…"},
  "sheet_rev": 12,
  "sheet_hash": "c0ffee12",
  "user_id": 42,
  "at": "2026-10-15T10:04:52Z"
}
```

**Groups** (one definition, no threshold flip):

- In the findings section: one group per paragraph from `paragraph_regions` (`hybrid_stack/template.py:42`), the groups the scratchpad shows.
- Every other section: one group per section.
- A group with more than 8 attestable units is split into consecutive chunks of at most 8, in document order (`group` = `<uid>#1`, `#2`, …).

**Attestable units** of a group: its live NORMAL lines and its unconditional default NEGATIVE lines. One predicate is used both when confirming and when checking.

**State**, `confirm_state(group, record, registry)`:

- `valid`: the group's current attestable units are exactly the record's units, each with the same `text_hash`.
- `stale`: anything else (a unit added, removed, gone, or its text changed). A stale confirm is asked again and never counts as confirmed.
- `missing`: no record for the group.

Confirms are never written by code and never carried across a text change.

## Sheet revision

`version_number` is not stable (`renumber_template_versions` renumbers after a delete; `cleanup_old_versions` keeps 10; it is not in config). Instead:

- `template_config["sheet_rev"]`: a monotonic integer, incremented by `_vet_config` on every persisted change to `skill_sheet`. Never renumbered, survives version cleanup.
- `generation_stamp` (`template_sheet_structure.py:268-279`) already carries `sheet_hash`; it gains `sheet_rev`. Confirms carry both.

## Writer: name the line for each uncertainty

Today the writer drops its questions (`template_sheet_lab_prompts.py:457-476`, `questions=False` about :519); uncertainty survives only as "## Open Questions" prose that nothing reads.

- Re-enable `questions` in the writer's JSON, each item `{line, why}`: `line` is the sheet line copied verbatim, `why` one sentence. Remove the "## Open Questions" prose instruction.
- The writer is stateless, so the items travel to the client with the sheet and come back on Create. At Create, code resolves each `line` by `norm_key` to exactly one parsed unit, then to its uid via the fresh registry. No match or several matches → dropped and logged.
- Stored at `template_config["uncertain"] = [{"uid", "why", "source": "writer", "at"}]` (server-written). Nothing consumes it in this slice; slice 4 reads it.
- Check before merge: run the writer on the existing synthetic template sets before and after (reuse outputs, at most 2 runs) and report sheet quality, question count and resolve rate to Hassan.

## Existing templates and the backfill

- No registry: everything works as today. The registry is minted on the next persisted save. Reads never write (the read path re-parses without persisting today; unchanged).
- `scripts/backfill_line_registry.py --dry-run | --apply`:
  - Skips inactive and non-grammar templates.
  - Mints a registry, stamps uids onto ledger entries that resolve by today's exact key and text matching (never cosmetic), sets `sheet_rev = 1`.
  - Leaves every unresolved entry exactly as it is. Value and concept entries are reported as `not line-bound`, not as unresolved.
  - Dry run: read-only session, rolled back, with a test that it commits nothing. Writes a per-template report to the scratchpad (never the repo; it reflects production templates): resolved count, and one row per unresolved entry with kind, key and reason (`no line`, `paragraph not found`, `paragraph ambiguous`, `lint failure`).
  - Apply: takes the row lock the upgrade script uses (`_locked_check`), writes config directly, creates no new `TemplateVersion`. On Hassan's go-ahead only.

## Metrics (logged, no gates)

Per persisted save: the rebind report and origin. Per rebuild: share of earlier line-bound ledger entries resolved by uid, against today's text matching on the same rebuild.

## Tests

`test_template_line_registry.py` (new), pure code:

- First save mints a uid per line-bound unit; an identical second save is all `exact`.
- Reordering sections or paragraphs keeps every uid. Inserting a normal mints one uid and changes no other.
- A cosmetic rewording ("There is no pleural effusion." → "No pleural effusion") keeps the uid; any token change gives `gone` + `new`.
- **Adversarial pairs never match** (pass condition: zero wrong matches): pleural / pericardial effusion; left / right; mild / moderate; "no evidence of" / "evidence of"; with / without; "score > 0" / "score < 0" / "score ≥ 100"; `1.5` / `15`; mGycm / mGy; "left kidney, right adrenal" / "right kidney, left adrenal"; the same normal text under a different structure; a conditional and an unconditional negative with the same text; two SUPPRESS rules with the same condition and different targets; identical FIXED lines in two paragraphs.
- Paragraph rename keeps uids only with an identical non-empty COVERS set and passing name gates.
- One old uid matched by two new lines, and two old by one new: both `ambiguous`, new uids.
- Carried units keep their uid after `apply_ledger` rewrites them.
- Gone units revive on exact identity only.
- Spelling table and filler list: collision test.

Existing suites:

- `test_template_ledger_apply.py`: uid-first then key fallback with re-stamp; a normal entry survives a writer rewording; removal decisions across a rebuild count as satisfied; `carried` map returned.
- `test_template_decisions.py`: `clean_ledger` keeps `uid`.
- `reconcile_chat` re-stamps the uid of a re-keyed entry.
- `test_template_sheet_save.py` / route tests: rebind runs on the five persisting paths and never on the stateless ones; `_carry_structure` ignores a client `line_registry`, `uncertain` and `normal_confirms`; `sheet_rev` increments only on a sheet change.
- Restore of a version with no registry rebinds against the current registry.
- Confirms: grouping (findings paragraphs, other sections, chunks of ≤ 8), `valid` / `stale` / `missing`, endpoint sets `user_id` from the session.
- Backfill: dry run commits nothing; unresolved entries listed with reasons and untouched; no new version on apply.
- Rebuild fixture: two writer outputs for the same synthetic reports. Primary metric: wrong matches (0). Secondary: resolved share against text matching.

## Decisions taken (2026-10-15)

1. No similarity threshold: exact or cosmetic equivalence only, tokenised before normalising, with hard clinical-token gates; zero wrong matches on adversarial pairs is the pass condition, survival rate the secondary metric.
2. Answers carry only when nothing meaningful changed: rules need the same condition and output, values the same name and unit; fixed lines carry when cosmetically equal; a changed normal makes its group's confirm stale.
3. Normals are confirmed per group (findings paragraphs, other sections), chunked at 8.
4. Independent review before the implementation plan (round 1 done; round 2 pending).
