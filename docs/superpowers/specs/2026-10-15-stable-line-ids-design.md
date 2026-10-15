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
4. Reports and confirms record a stable sheet revision.

Out: any UI (slice 3); NORMAL behaviours other than today's rule (decision 6, separate lab); Generate and provenance; report-time row IDs (`hybrid_stack/items.py:175`); writer uncertainty (the writer naming a sheet line per uncertainty, resolved to a `uid` at Create) and uncertainty scoring, both slice 4 (decision 8); deleting the legacy analyser at `template_manager.py:3311` (still used by `scripts/template_e2e_lab.py:327` and three tests; separate cleanup).

Not line-bound, unchanged: value entries (keyed by value name; Always / If dictated / Leave out map onto `need: every | relevant | not_needed`, `template_decisions.py:7-9`) and concept entries (comparison, contrast, sequences, limitation). TERM lines get no uid (no ledger kind uses them; the parser gives them no id).

## Decision: a sidecar registry, not IDs in the sheet text

IDs written into the sheet (`… {#n_k3f9qa}`) would be dropped, copied or invented by every LLM whole-sheet rewrite (chat fallback, rebuild), and would have to be stripped from every prompt the sheet reaches. A sidecar registry leaves the sheet text exactly as today; identity lives in `template_config["line_registry"]` and is re-bound by code on every persisted save.

## Identity: what a uid stands for

A uid names a **slot** in the template, not a string. What defines the slot depends on the kind; text that is not part of the identity can change without changing the uid, and that change is tracked separately (`text_hash`) where it matters for safety.

| Kind | Identity (all must match) | Text in identity? |
| --- | --- | --- |
| section | name | n/a |
| paragraph | section uid + name; or, for a rename, section uid + the **same non-empty** COVERS set + the **same side** (the laterality of the old and new names, decision 9; the rest of the name ignored) | n/a |
| normal | paragraph uid + side + structure (side: the structure's own laterality if its name states one, else the paragraph name's, else none; decision 9) | No, within an unchanged paragraph: the normal's answer is its text (`_normal` rewrites the line), so text is tracked by `text_hash`. **Across a paragraph rename** (the paragraph kept its uid by the COVERS rule) a normal keeps its uid only if its text is also exactly equal; otherwise it is a new unit and its answer is asked again |
| negative | paragraph uid + `condition` + `condition_source` + `kind` + `origin` + text | Yes (exact) |
| fixed | section uid + `paragraph` + text | Yes (exact) |
| rule (incl. LIST_MISSING, ASK) | section uid + paragraph uid (or none for section-level rules) + `effect` + `condition` + `condition_source` + `target` + `anchor` + `position` + output (`then_text`, `else_text`, `items`, `question`) | Yes: condition and every output field, exact |

Side is the whole words `left`, `right`, `bilateral` (case-insensitive) in a name: one distinct side is that side, several are kept together ("left and right" never equals "left"), none is no side. Left, right and bilateral never share a slot, whatever the paragraph is called.

Every name, structure, COVERS entry and text in the table compares **exactly** after representation-only normalising (below); nothing in identity is case-folded.

Consequences, by design:

- A rule whose condition or output changes ("score > 0" → "score ≥ 100") is a new rule; the old answer resolves by key or becomes a card.
- Two SUPPRESS rules with the same condition but different targets are different rules.
- A conditional negative (`NEGATIVE "No free fluid." WHEN [findings: …]`) and the unconditional one with the same text are different units.
- Identical FIXED lines in two paragraphs are different units.

## Wrong matches are worse than lost answers

Carrying an answer to the wrong line is a clinical error; losing one costs a repeat question. Word-overlap similarity is unsafe ("No pleural effusion" / "No pericardial effusion", "left" / "right", "mild" / "moderate", "no evidence of" / "evidence of"). So there is **no similarity and no cosmetic matching** (decision 7). A text field matches only if it is **exactly equal after normalising its representation** (`template_line_match.rep_key`):

1. **Unify lookalike characters:** en and em dashes, minus signs and other Unicode dashes → `-`; curly quotes and apostrophes → straight; `×` → `x`; non-breaking and other Unicode spaces → space. Nothing else merges: prime (`′`) is not an apostrophe, `≤` is not `<`, a zero-width space is not a space, `X` is not `x`.
2. **Collapse whitespace:** runs become one space; ends trimmed.

Everything else stays significant: case, punctuation (a final full stop included), spelling ("Oedema" ≠ "Edema"), filler words ("There is no mass." ≠ "No mass."), hyphens. A rewording, however small, is a new uid and its answer is asked again.

Why (Hassan, 2026-10-15): the measured gain of the earlier cosmetic layer (filler list, UK/US spelling table, tokeniser, negation / hedge / laterality / severity gates) was about one carried answer per rebuild, and every false match the reviewers found lived in that layer. Exact matching makes the adversarial pairs non-matching by construction; they stay in the tests as a tripwire against fuzzy matching coming back. The lookalike map is a constant (`LOOKALIKES`) with a collision test; changing it changes which lines keep their uid.

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
- `status`: `live` or `gone`. Gone units are kept, so a ledger entry pointing at one is visibly orphaned rather than silently rebound. A gone unit may be **revived only by an exact identity match** (restore, or a rebuild that brings the identical line back); never by any other match.
- Gone units are capped (end review M3): after each persisted save, `tlr.prune` keeps the 200 most recently minted gone units (`MAX_GONE`) and drops older ones, except any uid a ledger entry or a `normal_confirms` record (its group id or a unit) still names: those stay, visibly orphaned. Live units are never pruned. A pruned uid's identical line, if it returns, gets a new uid.
- `minted` is written once. No per-save timestamps (they would churn the config).

## Rebind (pure code, no model)

`rebind(registry, structure, carried) -> (registry, report)`:

1. Inputs: the new parse, the previous registry, and `carried`, a map `{uid: new raw line}` returned by `apply_ledger` for every line it rewrote (below).
2. Carried units keep their uid unconditionally: the ledger rewrote that exact unit, so no re-matching.
3. For the rest, kind by kind in parent-first order (sections, paragraphs, then lines), pair new units with previous units by exact identity. Live units first; a paragraph not paired exactly may then pair with a live paragraph by the COVERS rename rule (same section uid, same non-empty COVERS set; reported as `exact`), and across that rename its normals also need exactly equal text; gone units last, on exact identity only (revival).
4. Pairs are 1:1. If a new unit has more than one candidate, or a previous unit is the candidate of more than one new unit, none of them pairs: each new unit gets a new uid and the event is logged `ambiguous`.
5. Unpaired new units get new uids; unpaired previous live units become `gone`.
6. Returns the registry and `report = {exact, carried, revived, new, gone, ambiguous}`.

Deterministic: same inputs, same result.

Reading uids: `uids_for(structure, registry)` is a pure function that maps each parsed unit to its uid by exact identity against live units. Consumers call it at read time; uids are not stored on the cached `sheet_structure`, because `_queue_structure` (`main.py:1791`) and the read path (`hybrid_stack/template.py:27`) re-parse independently.

## Where rebind runs: persisting paths only

Several endpoints are stateless: they return a sheet to the client and never write the database. They must never mint uids. A uid in a client-held ledger that the stored registry doesn't know is treated as no uid.

| Path | Persists? | Change |
| --- | --- | --- |
| `POST /api/templates` (`main.py:1814`) | Yes | `persist_sheet` |
| `POST /skill-sheet/save` (`main.py:3111`) | Yes | `persist_sheet` |
| `PUT /api/templates/{id}` (`main.py:1846`) | Yes | `persist_sheet` against the **stored** registry |
| Restore (`main.py:2396`) | Yes | `persist_sheet` with the restored sheet against the **current** registry (not the snapshot's), exact revival allowed |
| `scripts/template_upgrade_apply.py` (calls `tsave.vet_sheet` at :99, writes at :164; never `_vet_config`) | Yes | switch to `persist_sheet` |
| `scripts/audit_and_fix_organization_defaults.py:129` | Edits `config["sections"]` only | none |
| `scripts/copy_template_to_user.py:60` | Yes | copies registry and ledger verbatim; uids stay valid within the copy (stated, no change) |
| Refine router / fallback (`main.py:2877`), `/refine/card` (`:3065`), `/refine/undo` (`:3031`), `/apply-decisions` (`:2912`), `template_writer.py:28` | No | no rebind, no minting |
| `store_structure` (`template_sheet_structure.py:1049`), `template_decision_run.py:470` | Writes `sheet_structure` / `rules_step` only | none |

**One helper owns the persisted save.** `persist_sheet(config, stored_config, origin)` = load the stored registry → `vet_sheet(…, registry=registry)` → rebind → stamp uids → bump `sheet_rev` if the sheet changed. `_vet_config` and the upgrade script both call it, so no persisting path can skip a step.

**Registry threading.** `vet_sheet` and `apply_ledger` gain `registry=None`:

- Stateless callers pass `None`: key and text matching only, no `carried` map, no uids touched.
- With a registry, `apply_ledger` resolves uid-first (via `uids_for` on the current parse) and returns `carried = {uid: new raw line}` for **every** line it rewrites, including secondary rewrites (`_normal` retargeting context rules that pointed at the old wording, `template_ledger_apply.py:~350`). A line edited by more than one step has its edits composed, so `carried` holds its final text.
- Uids are stamped **after** the rebind: each entry's matched unit in the final parse gets its uid from `uids_for(final parse, new registry)`. On a first save this is where every entry first gets a uid.

`_carry_structure` (`main.py:1728`) treats `line_registry`, `uncertain` (reserved for slice 4), `normal_confirms` and `sheet_rev` as server-written, like `sheet_structure`: a client copy on PUT is ignored and the stored one kept.

## Ledger changes

- `clean_ledger` (`template_decisions.py:472`) keeps `uid` (it currently rebuilds entries from a fixed key list).
- Resolution in `apply_ledger`, per entry:
  1. `uid` known and live → the unit's current line; run the existing edit path on it.
  2. `uid` unknown, gone, or absent → today's key and text matching; on success the matched unit's uid is stamped after the rebind (above).
  3. Otherwise unmatched, as today (card through `unmatched_cards`).
- **Removal decisions** (fixed `keep: remove`, normal `text: ""`) whose line is **shown** absent count as **satisfied**, not unmatched; they never become cards.
  "Its uid matched nothing" is never that evidence on its own (end review C1). Satisfied needs all of: the registry knows the uid and no unit of the parse holds it; the uid's stored parent (paragraph, else section) uid is matched in the current parse; no unit of that kind anywhere in the parse carries the registry's last text for the uid (`rep_key`); and, for a normal, no NORMAL in that paragraph has the same structure label and side. Anything else (a paragraph renamed beyond the COVERS rule, a line moved to another paragraph, the NORMAL still there) stays unmatched, a card. The check runs on every save, so an orphaned uid that `stamp_uids` keeps never re-satisfies a removal on its own.
- A normal entry binds to the slot (paragraph uid + structure), so it survives a writer rewording and keeps rewriting the line to the radiologist's text.
- `reconcile_chat` (`template_ledger_apply.py:688`) runs inside `vet_sheet` before any new uid exists, so it **clears** `uid` on any entry it re-keys; the post-rebind stamping then gives it the right one.
- When resolution keeps a uid on a line whose key label differs, the entry's `key` is updated to the new label and the change logged.
- `ledger_drift` stays a logged metric; the rebind `report` is logged beside it.

## The normals confirm record

Decision 5: normals are confirmed in small groups beside their sentences, each confirm recorded. Stored at `template_config["normal_confirms"]`, server-written only, through a dedicated endpoint (`POST /api/templates/{id}/normal-confirms`, used by slice 3). It is not a ledger kind: it changes no sheet text, and keeping it out of the client-held ledger means a client can't forge one.

The endpoint:

- Takes only `{group, sheet_rev, sheet_hash}` from the client: the group and the sheet the radiologist was looking at.
- Rejects the confirm (409) if `sheet_rev` / `sheet_hash` differ from the stored ones, so a concurrent edit is never attested unseen.
- Works out the group's units and their `text_hash` from the stored sheet and registry itself; never from the client.
- Sets `user_id` from the session.
- Confirms exist only on a saved template. The creator flow refines before Create (refine, card and apply-decisions accept requests with no `template_id`), so constraint for slice 3: the confirm UI is offered only once the template is saved; there are no creation-time confirms. The endpoint returns 404 for a template that doesn't exist (tested).

```json
{
  "group": "p_2hd7vc",
  "label": "Coronary findings › Coronary arteries",
  "units": {"n_k3f9qa": "sha256:9f2c…", "g_b71xpd": "sha256:41d0…"},
  "sheet_rev": 12,
  "sheet_hash": "c0ffee12",
  "group_name": "coronary arteries",
  "rules": "",
  "user_id": 42,
  "at": "2026-10-15T10:04:52Z"
}
```

**Groups** (one definition, no threshold flip):

- In the findings section: one group per paragraph from `paragraph_regions` (`hybrid_stack/template.py:42`), the groups the scratchpad shows. Findings-section units with no paragraph form one section-level group.
- Every other section: one group per section.
- A group with more than 8 attestable units is split into consecutive chunks of at most 8, in document order (`group` = `<uid>#1`, `#2`, …). Inserting or removing a normal shifts later chunks, so every chunk from that point goes stale and is confirmed again. That is the safe outcome and is accepted.

**Attestable units** of a group: its live NORMAL lines and its unconditional default NEGATIVE lines. One predicate is used both when confirming and when checking.

**State**, `confirm_state(group, record, registry)`:

- `valid`: the group's current attestable units are exactly the record's units, each with the same `text_hash`.
- `stale`: anything else: a unit added, removed or gone, or **any unit's `text_hash` changed**, including a normal reworded in place that kept its slot uid (a normal's identity holds no text, so the `text_hash` check is what catches it); **or the group's paragraph or section has been renamed since the confirm** (`group_name` differs), even if every sentence carried over unchanged. The record stores the group name after `rep_key` (`group_name`) to check this; any rename, case included, makes it stale. A confirm given in one context ("Arterial phase") never silently covers another. **Or a rule acting on the group changed** (end review M5): the record stores `rules`, a hash over the RULE lines that suppress, replace or are anchored on one of the group's units (matched as the generator matches), SUPPRESS NEGATIVES in its paragraph and SUPPRESS_SECTION of its section (`""` when there are none); adding, removing or changing any of them makes the confirm stale, while a rule on other lines never does. A stale confirm is asked again and never counts as confirmed.
- `missing`: no record for the group.

Confirms are never written by code and never carried across a text change.

## Sheet revision

`version_number` is not stable (`renumber_template_versions` renumbers after a delete; `cleanup_old_versions` keeps 10; it is not in config). Instead:

- `template_config["sheet_rev"]`: an integer, server-written, incremented by `persist_sheet` from the **stored** value on every persisted change to `skill_sheet`. Never renumbered, survives version cleanup.
- Two concurrent saves can store the same number, so the reference is always the pair `sheet_rev` + `sheet_hash`, never `sheet_rev` alone.
- `generation_stamp` (`template_sheet_structure.py:268-279`) already carries `sheet_hash`; it gains `sheet_rev`. Confirms carry both.

## Writer uncertainty: deferred to slice 4

The writer naming a sheet line for each uncertainty (re-enabling `questions` as `{line, why}`, resolving each `line` to a uid at Create, storing `template_config["uncertain"]`) moves to slice 4, where uncertainty is consumed (decision 8). This slice only reserves the `uncertain` key as server-written in `_carry_structure`.

## Existing templates

- No registry: everything works as today. The registry is minted on the next persisted save. Reads never write (the read path re-parses without persisting today; unchanged).

## Metrics (logged, no gates)

Per persisted save: the rebind report and origin. Per rebuild: share of earlier line-bound ledger entries resolved by uid, against today's text matching on the same rebuild.

## Tests

`test_template_line_registry.py` (new), pure code:

- First save mints a uid per line-bound unit; an identical second save is all `exact`.
- Reordering sections or paragraphs keeps every uid. Inserting a normal mints one uid and changes no other.
- Any rewording gives `gone` + `new`: filler ("There is no pleural effusion." → "No pleural effusion"), spelling ("Oedema" → "Edema"), case, a final full stop. These pairs were cosmetic matches before decision 7 and now assert the opposite.
- **Adversarial pairs never match** (pass condition: zero wrong matches): pleural / pericardial effusion; left / right; mild / moderate; "no evidence of" / "evidence of"; with / without; "score > 0" / "score < 0" / "score ≥ 100"; `1.5` / `15`; mGycm / mGy; "left kidney, right adrenal" / "right kidney, left adrenal"; the same normal text under a different structure; a conditional and an unconditional negative with the same text; two SUPPRESS rules with the same condition and different targets; identical FIXED lines in two paragraphs; `.5 mm` / `5 mm`; "No fracture. Dislocation." / "No fracture, dislocation."; "No mass; effusion." / "No mass effusion."; `<25%` / `25%`; `5 x 3 mm` / `53 mm`; "non-enhancing" / "enhancing"; "is seen" / "is not seen"; "likely pneumonia" / "pneumonia"; "cannot be excluded" / "excluded"; "possible" / "probable"; "No collapse, there is consolidation." / "No collapse, consolidation."; "No mass, fluid is seen." / "No mass, fluid."; `5'` / `5`.
- **Typography-only differences always match:** en dash / hyphen, curly / straight quotes, `×` / `x`, non-breaking or other Unicode space / space, extra whitespace.
- **Lookalike collision:** the lookalike map merges only into `-`, `"`, `'`, `x`, space, and never merges a different character (`X` / `x`, `′` / `'`, `≤` / `<`, zero-width space / nothing).
- Paragraph rename (Arterial phase → Portal venous phase, same COVERS): a normal with different text (a full stop included) gets a new uid; a normal with exactly equal text (typography aside) keeps its uid, **and** that group's confirm becomes stale.
- Paragraph rename keeps uids only with an identical non-empty COVERS set; a paragraph without COVERS, or with different COVERS ("left kidney" → "right kidney"), is a new paragraph.
- One old uid matched by two new lines, and two old by one new: both `ambiguous`, new uids.
- Carried units keep their uid after `apply_ledger` rewrites them, including context rules retargeted by `_normal` and a line edited by two steps.
- Gone units revive on exact identity only.
- The adversarial pairs above stay as a tripwire: exact matching makes them non-matching by construction.

Existing suites:

- `test_template_ledger_apply.py`: uid-first then key fallback with re-stamp; a normal entry survives a writer rewording; removal decisions across a rebuild count as satisfied; `carried` map returned.
- `test_template_decisions.py`: `clean_ledger` keeps `uid`.
- `reconcile_chat` clears the uid of a re-keyed entry and the post-rebind stamp restores the right one.
- `vet_sheet` / `apply_ledger` with `registry=None` behave exactly as today (existing suites unchanged).
- `test_template_sheet_save.py` / route tests: `persist_sheet` runs on the five persisting paths (including the upgrade script) and never on the stateless ones; `_carry_structure` ignores a client `line_registry`, `uncertain`, `normal_confirms` and `sheet_rev`; `sheet_rev` increments from the stored value only on a sheet change.
- Confirm endpoint: 409 on a stale `sheet_rev` / `sheet_hash`; units computed server-side; a client-sent unit list is ignored.
- Restore of a version with no registry rebinds against the current registry.
- Confirms: grouping (findings paragraphs, other sections, chunks of ≤ 8), `valid` / `stale` / `missing`, endpoint sets `user_id` from the session. Stale safety nets: (a) a normal reworded in place keeps its slot uid but its changed `text_hash` makes the confirm stale; (b) a paragraph or section rename with every sentence identical makes the confirm stale (`group_name`).
- Rebuild fixture: two writer outputs for the same synthetic reports. Primary metric: wrong matches (0). Secondary: resolved share against text matching.

## Decisions taken (2026-10-15)

1. No similarity threshold; zero wrong matches on adversarial pairs is the pass condition, survival rate the secondary metric. (The cosmetic equivalence first chosen here is superseded by decision 7.)
2. Uids carry only when nothing meaningful changed: rules need the same condition and output, values the same name and unit; fixed lines carry when exactly equal; a changed normal makes its group's confirm stale. One known, safe exception: today's key fallback for habits matches on paragraph and condition, so a habit answer still carries when only its question wording changes; the ledger then re-imposes its own question.
3. Normals are confirmed per group (findings paragraphs, other sections), chunked at 8, through a server-computed endpoint that rejects a stale sheet.
4. Superseded by decision 7 (it defined the cosmetic layer's tokens, gates and filler protection).
5. A normal's answer follows a renamed paragraph only if its own text is exactly equal (option c); any paragraph or section rename makes that group's normal confirm stale (Hassan, 2026-10-15).
6. Independent review before the implementation plan: round 1 not ready (11 findings), round 2 ready with fixes (9 findings), round 3 ready (one wording fix); all addressed.
7. Exact matching only, representation-normalised; cosmetic layer removed (Hassan, 2026-10-15). Lookalike characters and whitespace are the only normalisation; case, punctuation, spelling and filler words are significant. A paragraph rename is the COVERS rule alone (no name gates).
8. Writer uncertainty (the writer naming a line per uncertainty, resolved at Create) moves to slice 4 (Hassan, 2026-10-15).
9. Laterality is part of identity: left/right/bilateral can never share a slot, whatever the paragraph is called (Hassan, 2026-10-15). (Numbered 9 because decision 8 was already taken by writer uncertainty.)
