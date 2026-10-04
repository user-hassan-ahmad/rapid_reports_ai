# Review Rail Frontend (Slices B–E) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to work through this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal.** Replace today's Copilot aside with the Review rail beside the report editor:
- the review items, shown in a rail and as CM6 overlays;
- the editor marks for normals and negatives: green = assumed normal, amber = check, red strike = removed, ghost text = options;
- one-click fixes, a live probe loop, chat edits, and sessions and History.

It ships dark and lights up when the backend reports `mode: live`.

**Architecture.**
- **One item store** per open report (`lib/review/store.ts`) holds the `ReviewItem`s from `GET /api/reports/{id}/review`.
- **Pure commands** (`lib/review/commands.ts`) turn store state into CM6 `TransactionSpec`s and item events.
- **One CM6 extension bundle** (`lib/review/editor/`), generalised from the tested negatives prototype (`lib/review/negatives-proto/`), renders the overlays and widgets. It maps anchors through edits.
- **The rail component** (`lib/review/rail/`) renders the same store. Rail and editor stay in sync because both read one store, and every change goes through a command.
- **The document is the report.** Removed text and options are widgets, never document text. Copy and export read `view.state.doc`.

**Tech stack.** SvelteKit with Svelte 5. New code uses runes; existing Svelte 4 components keep their syntax. CodeMirror 6. Tests use vitest, in two projects:
- `server` (node): pure logic, `*.test.ts`;
- `client` (browser, Chromium): `*.svelte.test.ts`.

Run them with `bun run test`. The backend is FastAPI; the endpoints are already in `backend/src/rapid_reports_ai/review_engine/api.py`.

**Spec.** `docs/superpowers/specs/2026-10-02-review-engine-and-rail-design.md`, §10 and §12. Also these memories: `default-negatives` (presentation, legend, copy invariant), `split-decide-subtract-render` (brief normals labels), `review-item-policy`, `dev-route-guard`.

**Release model (Hassan, 2026-10-04).** Build the full rail and the editor enhancements, then ship everything together with the backend integration branch `feat/review-rail-v2`:
- the review engine with the Jev type and certainty-tier changes;
- linked normals;
- live mode.

Everything here is built on `feat/review-rail-v2` (frontend under `frontend/`). The rail only renders when `GET /review` returns `rail: true`, which needs `RR_REVIEW_ENGINE=live`. Until then today's UI is unchanged. `/dev/review-rail` (dev-route guarded) renders saved shadow runs for development and the Gate F read.

---

## Conventions for every task

- **TDD.** Write the failing test, watch it fail, implement, watch it pass, commit. Pure logic goes in node tests (`*.test.ts`). Components go in browser tests (`*.svelte.test.ts`, using `render` from `vitest-browser-svelte` and `page` from `@vitest/browser/context`).
- **New modules use Svelte 5 runes.** Don't convert existing Svelte 4 components beyond what the task needs.
- **API calls** follow the house pattern: `API_URL` from `lib/config.js`, plus a `Bearer $token` header from `lib/stores/auth.js` (`get(token)` outside components). Check `data.success`. Put the review API calls in `lib/review/api.ts` only.
- **`text_hash`** must equal the backend's `sha256(text)[:16]` (hex). Use `crypto.subtle` with a test vector computed from the backend.
- **Every new route under `routes/dev/`** ships a `+page.ts` calling `requireDevRoute()` in its first commit.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018p787D9fYjGvCu5x35pwJR
  ```
- **No colour-only meaning.** Every mark has an icon or label and an accessible name, and light and dark tokens.

## File structure

| Path | Responsibility |
|---|---|
| `lib/review/types.ts` | `ReviewItem`, `Span`, `Edit`, `ReviewRun`, `ReviewResponse` (mirror of backend §10.1), `ItemStatus`, `Cls` |
| `lib/review/hash.ts` | `textHash(text)`, matching the backend |
| `lib/review/api.ts` | `getReview`, `postEvent`, `probe`, `reprepare`, `rerun` |
| `lib/review/store.ts` | the per-report item store: load, poll until lanes are done, apply server updates, derived groups and counts |
| `lib/review/anchors.ts` | locate an item in the current document (span plus text check, then a unique text search, otherwise stale) |
| `lib/review/edits.ts` | `Edit` to CM6 changes: replace / insert (FINDINGS anchoring, after-anchor, section append) / upgrade / remove (seam tidy). Ported from `impressionOptions.ts` and the backend `verifier.apply_edit` rules |
| `lib/review/commands.ts` | the command registry: `apply`, `undo`, `edit`, `dismiss`, `restore`, `apply_all`, `ask_chat`, `rerun`, `finalise`, `open_item`, `next_item` |
| `lib/review/editor/field.ts` | `reviewField` StateField: live marks and widgets mapped through changes, plus inverted effects for undo. Generalised from `negatives-proto/state.ts` |
| `lib/review/editor/decorations.ts` | mark classes, `ItemWidget` (removed / option / pre-applied), gutter markers, popover tooltip. Generalised from `negatives-proto/decorations.ts` |
| `lib/review/editor/theme.ts` | `--rv-*` tokens (light/dark), density (`full` / `quiet` / `hidden`) |
| `lib/review/editor/index.ts` | `reviewExtensions(store)`: the bundle mounted into ReportEditor via a Compartment |
| `lib/review/probe.ts` | the live probe loop: debounce, changed ranges, staleness |
| `lib/review/rail/ReviewRail.svelte` | the rail shell: tabs (Review / Guidelines), urgency banner, collapse below 1100 px |
| `lib/review/rail/ItemCard.svelte`, `ItemRow.svelte`, `ItemTag.svelte` | rendering by class: action card / minor row / info tag; pre-applied and removed variants |
| `lib/review/rail/Legend.svelte` | the legend (label set "E · meaning"; Quiet default) |
| `lib/review/rail/ChatThread.svelte` | the chat thread in the rail (Slice D) |
| `routes/components/ReportEditor.svelte` | add the `extensions` Compartment prop and expose `view` |
| `routes/components/ReportResponseViewer.svelte` | mount the rail and the review extensions when `rail` is true; copy from the live document |
| `routes/+page.svelte` | when the rail is on, hide the Copilot aside (ReportEnhancementSidebar) and its layout modes |
| `routes/dev/review-rail/+page.ts`, `+page.svelte` | the guarded dev page: pick a report with a review run, render editor and rail |
| `routes/components/HistoryTab.svelte` / the history modal | reopen into the full viewer and rail (Slice E) |

---

## Slice B: the item store, commands, edit application

### Task B1: types, hash, API client

**Files:**
- Create `lib/review/types.ts`, `hash.ts`, `api.ts`.
- Tests: `lib/review/hash.test.ts`, `api.test.ts`.

- [ ] Step 1: failing tests.
  - `textHash('No ascites.')` equals the backend value. Generate it once with `.venv/bin/python -c "from rapid_reports_ai.review_engine.items import text_hash; print(text_hash('No ascites.'))"` and paste the literal into the test.
  - `api.getReview` builds `GET {API_URL}/api/reports/{id}/review?include=normals` with the bearer header, and returns `data` on `success`. It throws on `success:false`. Use `vi.stubGlobal('fetch', ...)`.
  - `postEvent` sends `{command, text_hash, detail}`. A 422 surfaces as an error.
- [ ] Step 2: run, and see it fail.
- [ ] Step 3: implement.
  - `types.ts` mirrors backend §10.1 exactly, field names included.
  - `hash.ts`:
    ```ts
    export async function textHash(text: string): Promise<string> {
      const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
      return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
    }
    ```
- [ ] Step 4: run, and see it pass. Commit with `feat(review-ui): types, text hash, API client`.

### Task B2: anchors

**Files:** create `lib/review/anchors.ts`; test `anchors.test.ts`.

`locate(doc: string, item: ReviewItem): {from, to} | null`, in this order:
1. if `doc.slice(start, end) === anchor.text`, return it;
2. else if `anchor.text` occurs exactly once in `doc`, return that position;
3. else if `anchor.text` is empty (a zero-width removed anchor) and the item carries `evidence.removed_text`, use the item's stored widget position (supplied by the field, Task C1);
4. else return `null`, and the caller marks the item `stale`.

- [ ] Steps 1–4 (TDD). Cover:
  - an exact span;
  - a shifted span found by unique search;
  - an ambiguous duplicate, which gives null;
  - an empty anchor.

  Commit.

### Task B3: edit application

**Files:**
- Create `lib/review/edits.ts`; test `edits.test.ts`.
- Port the rules from `lib/utils/impressionOptions.ts` (`insertEdit` / `removeEdit` / `applyEdit`) and from backend `review_engine/verifier.py` (`apply_edit`, `_remove_span`; read both).

`toChanges(doc, edit, sections?): ChangeSpec | null`:
- **replace / upgrade:** `find` must occur exactly once (otherwise null). Replace it.
- **insert:**
  - `after` anchor: must occur once and not end mid-word. Insert with exactly one space, or on the next line after a heading.
  - `after` null: append to the end of the `section` body (FINDINGS by default). Find the heading the same way `impressionOptions` does.
- **remove:** splice the span and tidy only the seam (collapse the double space, drop the emptied line, renumber a numbered list). Never re-substitute the whole document.

Tests: one case per mode, plus the backend's tricky cases (mid-word anchor → null; a heading anchor; the "2." renumbering; the empty-line drop). Commit.

### Task B4: the item store

**Files:** create `lib/review/store.ts`; test `store.test.ts`.

`createReviewStore(reportId)` returns a Svelte store (`writable`, consumable from Svelte 4 components) holding:

```ts
{ mode, rail, run, lanes, items: ReviewItem[], loading, error }
```

Its methods:
- `load()`;
- `pollUntilDone({intervalMs=1500, maxMs=90000})`, which polls while any lane is not `done` or `failed`;
- `upsert(items)`;
- `setStatus(id, status, historyEvent)`, an optimistic update rolled back on server error;
- `markStale(ids)`.

Derived values:
- `groups`: items by `section`, in the report's section order; "Unanchored" goes last; `suppress` and dismissed items fold away;
- `counts` per cls;
- `openActions`.

- [ ] TDD with a mocked `api`:
  - grouping order;
  - the fold;
  - polling stops when lanes are done, and stops at `maxMs`;
  - optimistic rollback.

  Commit.

### Task B5: the command registry

**Files:** create `lib/review/commands.ts`; test `commands.test.ts`.

Commands are pure: `(ctx: {doc, items, item?, args}) => {changes?: ChangeSpec, effects?: StateEffect[], event?: {itemId, command, detail}}`. They never call the network. The caller (Task C3) dispatches the transaction, then posts the event and updates the store.

| Command | What it does |
|---|---|
| `apply` | `toChanges(edit)`; event `apply`; status → applied |
| `undo` | only if the applied replacement is still present verbatim: invert it; event `undo` |
| `edit` | `{replacement}` arg: run the same as apply with the user's text; event `edit` |
| `dismiss` | no change; event `dismiss` |
| `restore` | for removed/pre-applied items: re-insert `evidence.removed_text` at the widget position; event `restore` |
| `apply_all(lane|kind)` | apply each eligible open item in document order, re-locating after each |
| `ask_chat` | returns `{openChat: prefill}`; event `ask_chat` |
| `next_item` / `open_item` | navigation only |

The names match the backend's allowed user commands (`apply, edit, undo, dismiss, restore, view, ask_chat`); engine-only statuses are never sent.

- [ ] TDD for each command, plus `apply_all` when an earlier edit shifts later anchors. Commit.

---

## Slice C: the editor overlays and the rail

### Task C1: the review field (generalise the negatives prototype)

**Files:**
- Create `lib/review/editor/field.ts`.
- Port `lib/review/negatives-proto/state.ts` and its 15 tests into `field.test.ts`, then extend.

The field state is `{marks: LiveMark[], widgets: WidgetItem[]}`, built from store items:

| Item | Becomes |
|---|---|
| `kind: assumed_normal` (cls info) | mark, class `rv-normal` (green, Quiet) |
| `kind: check` (cls minor) | mark, class `rv-check` (amber), `checkReason(evidence)` |
| other anchored `action` / `minor` / `info` items | marks `rv-action` / `rv-minor` / `rv-info` (an underline coloured by lane group; `minor` dotted; `info` gutter-only) |
| `status: pre_applied` insert | mark `rv-preapplied` on the inserted text, with an "added from your dictation · undo" chip |
| `status: pre_applied` removal / `kind: removed` | widget `rv-removed` (red strike, "removed · contradicts your dictation · restore") at the anchor |
| `kind: option` (cls minor) | ghost widget `rv-option` ("suggested · not included", click to include) |

Rules carried over from the prototype:
- marks map through changes;
- editing inside a mark drops it, and the item becomes `stale` via a store callback;
- `setItems` effect snapshots plus `invertedEffects` make undo and redo restore both the text and the items;
- **the copy invariant:** widgets are never document text.

- [ ] TDD: port the 15 prototype tests, rename, and keep them green. Then add:
  - lane-group marks;
  - a pre-applied insert;
  - a mark dropped on interior edit, which reports stale;
  - `fromItems` skips `suppress` and dismissed items.

  Commit.

### Task C2: decorations, popover, gutter, theme

**Files:**
- Create `lib/review/editor/decorations.ts`, `theme.ts`, `index.ts`.
- Port from `negatives-proto/decorations.ts`.

- Marks get their class plus `data-rv-id`. `ItemWidget` renders removed and option widgets with buttons that dispatch commands through a callback facet.
- **The popover** (`showTooltip`, opened on click, closed with Escape) shows:
  - label, reason, `source_line` ("you dictated: …");
  - the edit as a diff;
  - **Apply / Edit / Dismiss**, or **Keep / Remove** for checks, or **Restore** for removed items.
  - Edit opens an inline input. On confirm it sends the `edit` command; the verifier guards are server-side, so the probe loop (C6) checks the result.
- **Gutter markers** per anchored item, keyed by cls.
- **Theme:** `--rv-*` tokens for light and dark. Density on `view.dom.dataset.density`, Quiet by default.
- `index.ts` exports `reviewExtensions({onCommand, density})`.

- [ ] Browser tests (`decorations.svelte.test.ts`, mounting an EditorView in a test component):
  - a mark renders with its accessible name;
  - clicking opens the popover;
  - Apply dispatches the callback;
  - Escape closes it;
  - a removed widget's text is not in `view.state.doc`.

  Commit.

### Task C3: wire the extensions into ReportEditor

**Files:**
- Modify `routes/components/ReportEditor.svelte`.
- Test: a browser test.

- Add a prop `extraExtensions: Extension[] = []` held in a new `extrasCompartment`, reconfigured when the prop changes.
- Expose `getView(): EditorView`.
- Keep the existing full-document replace on `content` change. When it happens, the review layer re-locates its items (C5).
- [ ] Test: mounting with an extension that adds a known decoration renders it; changing the prop reconfigures it. Commit.

### Task C4: the rail component

**Files:**
- Create `lib/review/rail/ReviewRail.svelte`, `ItemCard.svelte`, `ItemRow.svelte`, `ItemTag.svelte`, `Legend.svelte`.
- Tests: `ReviewRail.svelte.test.ts`.

Spec §12.1:
- **Rail:** always open beside the editor. Tabs **Review** and **Guidelines**; Guidelines reuses the guidelines panel from ReportEnhancementSidebar, moved as it is. The **urgency banner** sits at the top.
- **Below 1100 px:** a strip with the open count that opens as an overlay.
- **Groups by section,** with "Unanchored" last.
- **Rendering by class:**
  - `action`: a card;
  - `minor`: a compact row with the fix ready;
  - `info`: a subtle tag;
  - `pre_applied`: "added from your dictation · undo".
- **Normals and checks:**
  - **checks** (amber) show as one collapsible "N to check" group, with a row each, Keep or Remove;
  - **assumed normals** never appear in the rail, only in the editor;
  - **options** show in an "Options" group with Add.
- **Header:** "▸ N other checks passed" folds the rest. No score. The legend sits in the rail header, with a density toggle (Full / Quiet / Hidden), Quiet the default.
- **States:**
  - loading: skeleton rows, "Reviewing…" while lanes are running;
  - a failed lane: "Review incomplete";
  - mode off or shadow: the component renders nothing.
- **Clicking a row** scrolls the editor to the anchor and opens the popover (`open_item`). Row actions call the same commands as the popover.

- [ ] Browser tests:
  - grouping and order;
  - class rendering;
  - the "N to check" group;
  - the folding count;
  - Apply on a card calls the command callback;
  - mode shadow renders nothing.

  Commit.

### Task C5: mount in ReportResponseViewer, and retire the old panels behind the rail flag

**Files:**
- Modify `routes/components/ReportResponseViewer.svelte` and `routes/+page.svelte`, plus the tabs that mount the viewer (`IntelliDictateTab.svelte`, `TemplatedReportTab.svelte`, `AutoReportTab.svelte`) only where props must pass through.

On mount, for a `reportId`, the viewer:
1. calls `createReviewStore(reportId).load()`;
2. if `rail`:
   - passes `reviewExtensions(...)` to ReportEditor;
   - renders ReviewRail beside the editor (a two-column layout inside the viewer);
   - starts `pollUntilDone`;
   - hides `OptionalAdditions`;
   - tells `+page.svelte` (via a dispatched event or a store) to hide the Copilot aside and its layout modes. **AuditBanner and ReportEnhancementSidebar stay in the code for one release, but are not rendered when the rail is on** (spec §14, retire step).

Command flow:
- the rail and popover call `onCommand(cmd, item)`;
- the commands module returns changes;
- the viewer dispatches them to the editor view, posts the event through the store, and marks `hasUnsavedChanges`.

**Copy fix:** `copy` dispatches `view.state.doc.toString()` (the live document) rather than the saved prop. This applies with the rail off as well, since the bug exists today.

**Finalise:**
- `applied_option_ids` keeps working: options applied through the rail call the same `appliedOptionIds`;
- the finalise call also sends `review_applied_item_ids`. The backend stores them on the run (a small backend change: add the field to the finalise body and save it in `report_review_runs.lanes` meta or a JSON column; covered by a backend test).

**Regeneration and new versions:** when the `response` prop changes (a new candidate, or a version restore), reload the store and re-locate items. Items that can't be located become `stale`.

- [ ] Browser tests:
  - rail off → today's UI (OptionalAdditions present, no rail);
  - rail on → rail present, OptionalAdditions hidden;
  - applying a card changes the editor text and marks unsaved;
  - copy returns the live document.

  Backend pytest for the finalise field. Commit.

### Task C6: the live probe loop

**Files:** create `lib/review/probe.ts`; test `probe.test.ts`. Wired in the viewer.

Spec §12.4. Triggers:
- a command;
- a chat edit;
- about 1.5 s after typing stops (debounced on editor changes).

The loop:
1. compute `changed_ranges` since the last probe (track them through CM6 changes);
2. call `POST …/review/probe {text, text_hash, changed_ranges}`;
3. drop the answer if `text_hash` no longer matches the current document;
4. mark `addressed` ids;
5. add `new_items` (contradictions) to the store and field;
6. for `reprepare` ids, show "updating…" on those items, call `…/reprepare`, and upsert the results (again only if the hash still matches).

At most one probe is in flight; later triggers coalesce. The full engine never re-runs automatically: **Re-review** is a manual button in the rail header (`rerun`).

- [ ] TDD with fake timers and a mocked API:
  - debounce;
  - coalescing;
  - stale answers dropped;
  - addressed items update;
  - reprepare flow.

  Commit.

### Task C7: `/dev/review-rail`

**Files:**
- Create `routes/dev/review-rail/+page.ts` (`requireDevRoute()`, in the first commit) and `+page.svelte`.

The page:
- lists the user's recent reports that have a review run, via `GET /api/reports` filtered client-side by calling `getReview`;
- renders ReportEditor and ReviewRail for one of them;
- **forces the rail on** even in shadow (dev only), with the legend, density toggle and counts;
- is read-only with respect to the server for events. Commands apply locally; nothing is posted unless a "post events" toggle is on.

This page serves both rail development and the Gate F hand read.

- [ ] Browser test: the page module calls the guard; a fixture renders the rail. Commit.

---

## Slice D: chat edits

### Task D1: backend, the chat reply gains `edits[]`

**Files:**
- Modify the chat endpoint (`backend/src/rapid_reports_ai/main.py` ~L4165, and its service).
- Test: a backend pytest with a mocked model.

Spec §12.5:
- the reply carries `edits: [{section, find, replace}]` alongside prose;
- the request includes the open items, so chat doesn't duplicate them;
- each edit runs through `verifier.guard_failures` (one-click rules), and edits that fail are returned with `failed: [...]` and no Apply.

The old `edit_proposal` stays for one release, for the old sidebar.

- [ ] TDD; commit.

### Task D2: chat thread in the rail

**Files:** create `lib/review/rail/ChatThread.svelte`; modify ReviewRail.

- Sending a message switches the rail to the thread, with a strip "← Review · N open".
- "⤢ Expand" widens the rail.
- Each verified edit has Apply.
- Applying creates a `lane: chat` item locally, linked to the message, through the store and the `apply` command; the event is posted.
- Unapplied edits stay in the thread.
- "Ask in chat" on an item pre-fills it.

Chat history uses `report_chat_messages` if the backend persists it (check). Otherwise the thread lives for the session.

- [ ] Browser tests for the thread switch, Apply → editor change, and pre-fill. Commit.

---

## Slice E: sessions and History

### Task E1: workspace state

**Files:**
- Backend: a small endpoint `PUT /api/reports/{id}/workspace` that writes `reports.workspace_state` (the column exists from migration `20261003120000`; re-add the ORM mapping, removed in 0f1a8a3). Test with pytest.
- Frontend: the store saves `{tab, expanded_ids, density, last_text_hash}`, debounced.

- [ ] TDD; commit.

### Task E2: History reopens into the full viewer and rail

**Files:**
- Modify `routes/+page.svelte` (history modal), `HistoryTab.svelte`.
- Tests: browser.

"Open" on a history report loads it into the main viewer (the relevant tab, with `reportId` and `response`), restores the workspace state, and loads the stored review run and items. **Nothing is re-run.** The read-only modal stays as a "Preview".

- [ ] Browser test: open from History renders the viewer, the rail and items from the stored run, without calling rerun or probe. Commit.

### Task E3: the Metabase view `v_review_item_events`

**Files:**
- A migration creating the view: unnest `report_review_items.history` into `(item_id, report_id, lane, kind, cls, event, actor, at)`.
- Test: a pytest on the SQLite test DB if possible, otherwise Postgres-only SQL guarded and checked in a migration test.

- [ ] Commit.

---

## Final: integration, Gate G, release checklist

### Task F1: end-to-end in Chrome (Gate G), on a local stack with `RR_REVIEW_ENGINE=live`

- Generate the synthetic pancreas case and one MSK case.
- Check:
  - the rail appears;
  - green, amber, red and ghost marks render with the legend;
  - Apply, Undo, Dismiss, Restore and Keep/Remove work and persist (reload → statuses kept);
  - copy excludes removed text;
  - typing triggers the probe;
  - chat edit → Apply;
  - History reopen.
- Record a GIF.

### Task F2: whole-branch code review, then the release PR

- **Review:** the whole `feat/review-rail-v2` branch, backend plus frontend.
- **PR** to main.
- **Merge** (Hassan).
- **Railway settings** (Hassan approves each):
  - `RR_GROUPED_NORMALS=1`;
  - `RR_REVIEW_ENGINE=live`;
  - `RR_REVIEW_RAIL` unset.
- **Verify by data:**
  - `report_review_runs.mode='live'` on new reports;
  - the UI in the Chrome session.
- **Ledger:** a new L-number for the release.
- **Kill switches:**
  - `RR_REVIEW_RAIL=0` hides the rail;
  - `RR_REVIEW_ENGINE=shadow` returns to today's UI;
  - `RR_GROUPED_NORMALS=0` restores today's normals.

---

## Execution and parallelism

| Wave | Tasks (parallel within a wave, on disjoint files) |
|---|---|
| 1 | B1, B2, B3 |
| 2 | B4, B5, C1 |
| 3 | C2, C3, D1 (backend) |
| 4 | C4, C6, E1 |
| 5 | C5 (integration; alone) |
| 6 | C7, D2, E2, E3 |
| 7 | F1, then F2 |

After each wave:
- a reviewer subagent checks the wave's diff against this plan and spec §12;
- the full frontend test run (`bun run test`) and the backend suite run;
- only then does the next wave start.

## Self-review notes

- **Spec §12 coverage:**
  - layout: C4, C5;
  - overlays: C1, C2;
  - commands: B5;
  - probe: C6;
  - chat: D1, D2;
  - sessions/History: E1, E2;
  - routes/flags: C5, C7;
  - retire: C5, which hides the old panels; deletion follows in the release after.
- **Additions since the spec:**
  - editor marks for normals and checks (C1);
  - the legend and density (C2, C4);
  - copy from the live document (C5);
  - pre-applied and removed widgets (C1);
  - the brief's linked-normals labels arrive as items from the backend integration branch, so the frontend needs nothing extra.
- **Known gap:** the generator may re-merge implicated normals into grouped sentences. The backend anchors them on the structure term (integration step 3a); unanchored ones appear only in the rail's "N to check" group.
