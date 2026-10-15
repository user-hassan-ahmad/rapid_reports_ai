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

| Kind | Anchor fields | Primary match | Fallback match (same parent only) |
| --- | --- | --- | --- |
| section | name | normalised name | none (a new name is a new section) |
| paragraph | section uid, name, covers | section + normalised name | same section, covers overlap ≥ 50% |
| normal | paragraph uid, structure | paragraph + normalised structure | none |
| negative | paragraph uid, text, targets | paragraph + `norm_key(text)` | same paragraph and targets, content-word Jaccard ≥ 0.6 |
| fixed | section uid, text | section + `norm_key(text)` | same section, Jaccard ≥ 0.6 |
| rule (incl. LIST_MISSING, ASK) | paragraph uid, effect, condition, target or items | paragraph + effect + normalised condition | same paragraph + effect; condition Jaccard ≥ 0.6, or for LIST_MISSING item-set overlap ≥ 50% |
| term | preferred | normalised preferred term | none |

- `status`: `live` or `gone`. A unit that disappears is kept as `gone` (never deleted), so a ledger entry pointing at it is visibly orphaned rather than silently rebound.
- `match`: how the unit was last bound (`exact`, `fallback`, `new`), for the metric below.
- Parent before child: sections bind first, then paragraphs, then their lines, so a renamed paragraph whose covers still match keeps its uid and its normals keep theirs.

### Rebind algorithm (pure code, no model)

`rebind(registry, structure) -> (registry, report)`:

1. Parse result in, previous registry in.
2. For each kind in parent-first order, score every (new unit, previous live unit) pair of that kind: primary match = 1.0; fallback match = its similarity; otherwise no pair.
3. Assign 1:1 greedily by score, ties broken by document order. If a new unit has two candidates within 0.05 of each other, do not guess: mint a new uid and log `ambiguous`.
4. Unmatched new units get new uids (`new`); unmatched previous live units become `gone`.
5. Returns the registry plus `report = {exact, fallback, new, gone, ambiguous}` counts.

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
- When a rebind moves a uid to a line whose key differs (paragraph renamed, negative reworded), the entry's `key` is updated to the new label and the change is logged. This is the drift fix.
- `ledger_drift` stays a logged metric; the rebind `report` is logged beside it on every save.

### New kind: `confirm`

The per-section normal attestation (decision 5).

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

- `units` maps every NORMAL (and default NEGATIVE) uid in that section to its `text_hash` at the moment of confirming. The conclusion's normal line is its own section entry.
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
- A one-off script, `scripts/backfill_line_registry.py --dry-run | --apply`, mints registries for all templates and stamps uids onto ledger entries that resolve. Dry run first; counts reported to Hassan; apply on his go-ahead.

## Metrics (logged, no gates)

Per save: rebind counts `{exact, fallback, new, gone, ambiguous}` and origin. Per rebuild: share of previous ledger entries still resolved by uid, against today's text-match baseline on the same rebuild. This is the number that shows whether answers now survive "add reports and rebuild".

## Tests

- `test_template_line_registry.py` (new), pure code:
  - first save mints a uid for every unit; a second identical save is all `exact`;
  - reordering sections or paragraphs keeps every uid;
  - inserting a normal mints one new uid and changes no other (positional IDs shift; uids don't);
  - rewording a negative slightly keeps its uid (`fallback`); rewording it heavily gives `gone` + `new`;
  - renaming a paragraph whose covers still match keeps its uid and its normals' uids;
  - two equally good candidates give `ambiguous` + a new uid;
  - a deleted unit is `gone` and is never re-used.
- `test_template_ledger_apply.py`: uid-first resolution; key relabel after a rename; `gone` uid is unmatched; no-uid entries still work and get stamped.
- `test_template_decisions.py`: `confirm` validation (`by` must be radiologist) and `confirm_state` valid / stale / missing cases.
- `test_template_sheet_save.py` and the apply-decisions route test: rebind runs on every path in the table above.
- A rebuild fixture: two writer outputs for the same synthetic reports; most earlier ledger entries resolve by uid where text matching loses them.

## Open questions

1. Fallback thresholds (0.6 Jaccard, 50% covers) are starting values. Tune them on the rebuild fixture, or run a small lab of real-shaped rebuilds first?
2. Should a `fallback` rebind of a line that a radiologist decided on (a ledger entry exists) be surfaced as a quiet card ("we kept your answer for this reworded line"), or stay silent?
3. Confirm granularity: one confirm per section (as here) or per paragraph? Sections match the Refine layout; paragraphs match how the scratchpad groups normals.
