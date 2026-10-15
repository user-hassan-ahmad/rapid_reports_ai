# Stable sheet-line IDs and the confirm record: design

Date: 2026-10-15. Slice 2 of "Build your template" (spec doc "RadFlow: Build Your Template", section *Review and decisions*, build order step 2). Status: draft for review.

## Why

Every later slice keys on a sheet line: card answers, deferred items, per-section normal confirms, uncertainty scoring, provenance. Today no line has a stable identity:

- Parsed units get positional IDs (`p1`, `r3`, `n7`, `m2`, `f1`) on every parse (`template_sheet_grammar.py:488-545`); any insert or delete shifts them.
- Ledger keys are names and text (`template_decisions.py:145-176`): `paragraph :: structure` for normals, the quoted text for negatives and FIXED lines, `paragraph :: condition` for habits. A renamed paragraph, a reworded negative or a reworded condition orphans the entry.
- `apply_ledger` finds lines by exact raw text (`template_ledger_apply.py:74`); orphans stay in the ledger and come back as cards (`template_rules_cards.py:182`).
- A rebuild (writer rewrites the whole sheet) therefore loses most earlier answers. That is exactly the "add more reports and rebuild" path the new flow depends on.

The 2026-10-13 Rules-step spec asked for "stable keys only… no free-text matching" (`2026-10-13-template-rules-step-design.md:72-77`); the code never got there. This spec closes that gap.

## Scope

In:

1. A line registry: a stable `uid` per sheet unit, kept across every kind of edit, stored beside the sheet.
2. Ledger entries carry the `uid`; `apply_ledger` resolves by `uid` first.
3. A `confirm` ledger kind: the per-section normal attestation (decision 5), with staleness.
4. The writer names a sheet line for each uncertainty; code resolves it to a `uid` and stores it.
5. Reports record the template version they were generated from.

Out (later slices or separate decisions): any UI; NORMAL behaviours other than today's rule (decision 6, separate lab); changes to Generate or provenance; changes to report-time row IDs (`hybrid_stack/items.py:175`); uncertainty scoring (slice 4).

Value-ask needs no new kind: Always / If dictated / Leave out map onto the existing value choice `need: every | relevant | not_needed` (`template_decisions.py:7-9`).

## Decision: a sidecar registry, not IDs in the sheet text

Two ways to give lines identity:

| | IDs written into the sheet text (`… {#n_k3f9qa}`) | Sidecar registry re-bound by code after every save |
| --- | --- | --- |
| Survives chat router line patches | Yes | Yes (re-bound) |
| Survives LLM whole-sheet rewrites (chat fallback, rebuild) | No: models drop, copy or invent IDs | Yes, when the line is still recognisable |
| Generate / analyser prompts | Must strip IDs everywhere the sheet is sent | Unchanged |
| Grammar and lint | New syntax, fail-closed sweep must learn it | Unchanged |

Recommendation: **sidecar registry**. The sheet text stays exactly as today; identity lives in `template_config["line_registry"]` and is re-bound by code after every write. An ID that a model can delete is not stable.

## The registry

Stored at `template_config["line_registry"]`:

```json
{
  "v": 1,
  "units": {
    "n_k3f9qa": {
      "kind": "normal",
      "anchor": {"section": "Coronary findings", "paragraph": "Coronary arteries", "structure": "LAD"},
      "text": "LAD: Normal proximal, mid and distal LAD.",
      "text_hash": "9f2c1e0a",
      "status": "live",
      "first_seen": "2026-10-15T10:02:11Z",
      "last_seen": "2026-10-15T10:02:11Z",
      "match": "exact"
    }
  }
}
```

- `uid` = kind prefix + 6 random base32 characters (`s_` section, `p_` paragraph, `n_` normal, `g_` negative, `f_` fixed, `r_` rule, `t_` term). Minted once, never reused.
- `kind` and `anchor` per unit kind:

| Kind | Anchor fields | Primary match | Cosmetic match (same parent only) |
| --- | --- | --- | --- |
| section | name | normalised name | none (a new name is a new section) |
| paragraph | section uid, name, covers | section + normalised name | same section and the **same** COVERS set (a rename only) |
| normal | paragraph uid, structure, text | paragraph + normalised structure + `norm_key(text)` | same paragraph and structure, text cosmetically equal |
| negative | paragraph uid, text, targets | paragraph + `norm_key(text)` | same paragraph and targets, text cosmetically equal |
| fixed | section uid, text | section + `norm_key(text)` | same section, text cosmetically equal |
| rule (incl. LIST_MISSING, ASK) | paragraph uid, effect, condition, output (USE/REPLACE text, items, question) | paragraph + effect + normalised condition + normalised output | same paragraph and effect; condition and output each cosmetically equal; LIST_MISSING items equal by name and unit |
| term | preferred | normalised preferred term | none |

### Wrong matches are worse than lost answers

Carrying an answer to the wrong line is a clinical error; losing one only costs a repeat question. Word-overlap similarity is unsafe in clinical text: "No pleural effusion" and "No pericardial effusion", "left" and "right", "mild" and "moderate", "no evidence of" and "evidence of" all overlap heavily. So there is **no similarity threshold**. The only non-exact match is *cosmetic equivalence*:

- Both texts are normalised: case, whitespace, punctuation, UK/US spelling, and a short fixed list of filler phrases ("is seen", "there is", "is noted", "is identified", "demonstrated").
- After that, the remaining content words must be **identical and in the same order**. Any added, removed or changed content word is a different line. Order is kept because reordering can swap laterality between structures ("left kidney, right adrenal").
- Hard gates are checked first and fail closed: same unit kind; same structure (normals) or same targets (negatives); same value slot name and unit (values); negation, laterality, severity grades, numbers and units identical token for token.
- When in doubt, a new uid. Ties (two candidates both cosmetically equal) are `ambiguous` and also get a new uid.

What changed decides whether an answer carries, not the line type: a rule keeps its uid (and its answer) only when its condition and output are both unchanged; "score > 0" becoming "score ≥ 100" is a new rule, and the old answer is unmatched and asked again. A value keeps its answer only with the same name and unit. Fixed lines carry when cosmetically equal. Normal sentences carry their uid the same way, and any text change makes their section's confirm stale (below).

- `status`: `live` or `gone`. A unit that disappears is kept as `gone` (never deleted), so a ledger entry pointing at it is visibly orphaned rather than silently rebound.
- `match`: how the unit was last bound (`exact`, `cosmetic`, `new`), for the metric below.
- Parent before child: sections bind first, then paragraphs, then their lines, so a renamed paragraph whose covers still match keeps its uid and its normals keep theirs.

### Rebind algorithm (pure code, no model)

`rebind(registry, structure) -> (registry, report)`:

1. Parse result in, previous registry in.
2. For each kind in parent-first order, pair every new unit with the previous live units of that kind: first by primary match, then (for those still unpaired) by cosmetic match. The hard gates run before either.
3. Pairs are 1:1. If a new unit has more than one candidate at the same level, do not guess: mint a new uid and log `ambiguous`.
4. Unmatched new units get new uids (`new`); unmatched previous live units become `gone`.
5. Returns the registry plus `report = {exact, cosmetic, new, gone, ambiguous}` counts.

Rebind is deterministic: the same sheet and registry give the same result. It also attaches `uid` to every unit in the cached `sheet_structure`, so later slices can read uids at report time without a second lookup.

### Where rebind runs

Every path that changes `skill_sheet` already ends in `vet_sheet` + `apply_ledger`, except one. Rebind is added:

| Path | Entry point | Change |
| --- | --- | --- |
| Creation save | `main.py:3111` → `_vet_config` origin analyser | rebind inside `vet_sheet` |
| PUT template (refine panel final save) | `main.py:1846` → `_vet_config` origin chat | rebind inside `vet_sheet` |
| Chat router line patches | `chat_router_ledger.save` (`chat_router_ledger.py:280`) | rebind inside `vet_sheet` |
| Chat fallback whole rewrite | `main.py:2877` → `vet_sheet` origin chat | rebind inside `vet_sheet` |
| Restore | `main.py:2396` origin restore | restore the registry from the same version snapshot, then rebind |
| Rebuild / upgrade | `scripts/template_upgrade_apply.py`, `write_sheet` | rebind inside `vet_sheet` |
| Rules / Style step cards | `/skill-sheet/apply-decisions` (`main.py:2912`) calls `apply_ledger` with no vet | add an explicit rebind after `apply_ledger` |

Inside `vet_sheet` the order is: parse → rebind → `apply_ledger` (resolves by uid) → re-parse → rebind again (ledger rewrites keep anchors, so this second pass is near-all `exact`) → persist registry with the sheet.

## Ledger changes

- Each entry gains an optional `uid`. Existing fields (`kind, key, choice, by, at, source`) are unchanged; `key` stays as the human-readable label and the back-compat fallback.
- `apply_ledger` order: if `uid` is present and `live`, take the unit's current raw line from the parse and run the existing edit path on it. If `uid` is `gone`, the entry is unmatched (as today). If there is no `uid`, use today's key and text matching, and on success stamp the `uid` onto the entry.
- When a rebind keeps a uid on a line whose key differs (paragraph renamed, negative cosmetically reworded), the entry's `key` is updated to the new label and the change is logged. This is the drift fix. Because uids only survive cosmetic changes, an answer never follows a line whose meaning changed.
- `ledger_drift` stays a logged metric; the rebind `report` is logged beside it on every save.

### New kind: `confirm`

The normal attestation (decision 5). One confirm per section; a section holding more than 8 normal statements (a CT abdomen and pelvis Findings section can hold 15–20) is split into its paragraph groups, the same groups the scratchpad shows, so no single tap attests to more than about 8 sentences. Same record and component either way; `key` is then `Section › Paragraph` and `uid` the paragraph's.

```json
{
  "kind": "confirm",
  "key": "Coronary findings",
  "uid": "s_8wq2mz",
  "choice": {
    "units": {"n_k3f9qa": "9f2c1e0a", "n_b71xpd": "41d0c3aa"},
    "version_number": 7,
    "sheet_hash": "c0ffee12"
  },
  "by": "radiologist",
  "at": "2026-10-15T10:04:52Z",
  "source": "creation"
}
```

- `units` maps every NORMAL (and default NEGATIVE) uid in that section or group to its `text_hash` at the moment of confirming. The conclusion's normal line is its own entry.
- `confirm_state(entry, registry) -> "valid" | "stale" | "missing"`:
  - `valid`: every listed uid is live with the same `text_hash`, and the section has no live normal uid that isn't listed.
  - `stale`: any listed uid is gone or its text changed, or a new normal appeared in the section. A stale confirm is shown again for confirming; it never counts as confirmed.
  - `missing`: no confirm entry for the section.
- Confirms are never written by code (`by` must be `radiologist`) and never carried silently across a rebuild. If the text didn't change, the confirm stays valid; if it did, the radiologist confirms again.
- `apply_ledger` ignores `confirm` entries (they change no sheet text).

## Writer: name the line for each uncertainty

Today the writer is told to drop its questions (`template_sheet_lab_prompts.py:458-476`, `questions=False` at :519). Uncertainty survives only as "## Open Questions" prose, which nothing reads.

Change:

- Re-enable `questions` in the writer's JSON with one required field per item: `line`, the sheet line copied verbatim, plus `why`, one sentence. Remove the "## Open Questions" prose instruction.
- Code resolves each `line` to a uid by `norm_key` match against the parsed units. An item that matches no line, or more than one, is dropped and logged (never guessed).
- Store resolved items at `template_config["uncertain"] = [{"uid", "why", "source": "writer", "at"}]`. Nothing consumes them in this slice; slice 4 (support scoring) reads them as one input.
- The dead analyser copy at `template_manager.py:3311` is deleted in the same change, so there is one prompt to keep in sync.
- Check: run the writer on the existing synthetic template sets before and after (eval economy: reuse outputs, at most 2 runs) and report sheet quality, question count and resolve rate. Report only; Hassan decides.

## Reports record the template version

`generation_stamp` (`template_sheet_structure.py:268-279`) gains `version_number` beside `sheet_hash`. That links every report, every confirm and every later just-in-time answer to the exact approved sheet, which the hazard log and DCB0129 will need.

## Existing templates

- No registry yet: everything works as today (key and text matching). The registry is minted on the next save that passes through `vet_sheet`; reads never write.
- A one-off script, `scripts/backfill_line_registry.py --dry-run | --apply`, mints registries for all templates and stamps uids onto ledger entries that resolve by today's exact key and text matching (the backfill never uses cosmetic matching: there is no previous registry to compare against).
- Entries that don't resolve are left exactly as they are: no uid, still in the ledger, still shown as cards through `unmatched_cards` as today. Nothing is deleted or rebound.
- The dry run writes a per-template report (to the scratchpad, never the repo, since it reflects production templates): resolved count, and one row per unresolved entry with kind, key and reason (`no line`, `paragraph not found`, `paragraph ambiguous`, `lint failure`). Totals are reported to Hassan; apply on his go-ahead.

## Metrics (logged, no gates)

Per save: rebind counts `{exact, cosmetic, new, gone, ambiguous}` and origin. Per rebuild: share of previous ledger entries still resolved by uid, against today's text-match baseline on the same rebuild. This is the number that shows whether answers now survive "add reports and rebuild".

## Tests

- `test_template_line_registry.py` (new), pure code:
  - first save mints a uid for every unit; a second identical save is all `exact`;
  - reordering sections or paragraphs keeps every uid;
  - inserting a normal mints one new uid and changes no other (positional IDs shift; uids don't);
  - a cosmetic rewording ("There is no pleural effusion." → "No pleural effusion") keeps its uid (`cosmetic`); any content-word change gives `gone` + `new`;
  - **adversarial near-miss pairs never match** (the pass condition is zero wrong matches): pleural / pericardial effusion, left / right, mild / moderate, "no evidence of" / "evidence of", "score > 0" / "score ≥ 100", "mGycm" / "mGy", "left kidney, right adrenal" / "right kidney, left adrenal", and the same normal text under a different structure;
  - a rule whose condition or output changes gets a new uid and its answer is unmatched;
  - renaming a paragraph with an identical COVERS set keeps its uid and its normals' uids; a changed COVERS set does not;
  - two equally good candidates give `ambiguous` + a new uid;
  - a deleted unit is `gone` and is never re-used.
- `test_template_ledger_apply.py`: uid-first resolution; key relabel after a rename; `gone` uid is unmatched; no-uid entries still work and get stamped.
- `test_template_decisions.py`: `confirm` validation (`by` must be radiologist), `confirm_state` valid / stale / missing cases, and the split into paragraph groups above 8 normals.
- Backfill script: dry run writes nothing to the database; unresolved entries are listed with their reason and left untouched.
- `test_template_sheet_save.py` and the apply-decisions route test: rebind runs on every path in the table above.
- A rebuild fixture: two writer outputs for the same synthetic reports plus the adversarial pairs. Primary metric: wrong matches (must be 0). Secondary: share of earlier ledger entries resolved by uid, against today's text matching.

## Decisions taken (2026-10-15)

1. No similarity threshold: exact or cosmetic equivalence only, with hard clinical-token gates; zero wrong matches on adversarial pairs is the pass condition, survival rate the secondary metric.
2. Answers carry silently only when nothing meaningful changed: rules need the same condition and output, values the same name and unit; fixed lines carry when cosmetically equal; a changed normal makes its section's confirm stale.
3. One confirm per section, split into paragraph groups above 8 normal statements.
4. An independent review of this spec before the implementation plan, focused on wrong matches, the backfill's unresolved entries, and coverage of all seven save paths.
